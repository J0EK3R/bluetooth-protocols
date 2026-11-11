#!/usr/bin/env python3
"""
XN297L sniffer - Wireshark extcap interface and command line tool.

Talks to the nRF52840 dongle firmware (../firmware) over its USB virtual COM
port and either

  * streams the received frames into Wireshark (extcap mode, DLT_USER0), or
  * prints decoded frames to the console (--print mode).

All byte values are in ON-AIR ORDER, MSB FIRST, as in Chips/XN297L.md.

Requirements: Python 3.8+, pyserial  (pip install pyserial)

Examples
--------
List serial ports:
    python xn297l_sniffer.py --list-ports

Print frames of a known address on 2402 MHz:
    python xn297l_sniffer.py --print --port COM5 --mode address \
        --address C1C2C3C4C5 --channels 2

Print everything that starts with the XN297L preamble (experimental):
    python xn297l_sniffer.py --print --port COM5 --mode promiscuous

Pseudo header in front of every frame (12 bytes, little endian)
-------------------------------------------------------------
    offset size  field
    0      1     version (= 1)
    1      1     flags: bit0 = scrambler on, bit1 = promiscuous capture
    2      1     RF channel (MHz - 2400)
    3      1     RSSI in dBm (signed)
    4      1     address length (3..5)
    5      1     payload length (0 = unknown, find it via CRC)
    6      1     data rate: 0 = nrf1m, 1 = nrf2m, 2 = ble1m
    7      1     reserved (0)
    8      4     device timestamp in microseconds
    12     ...   on-air bytes starting with the first address byte
"""

import argparse
import os
import struct
import sys
import time

__version__ = "1.0.0"

# ---------------------------------------------------------------------------
# XN297L constants and helpers (see Chips/XN297L.md, section 5)
# ---------------------------------------------------------------------------

PREAMBLE = bytes([0x71, 0x0F, 0x55])   # fixed XN297L preamble, never scrambled
MAX_PAYLOAD = 32                       # normal mode payload limit
LINKTYPE_USER0 = 147                   # pcap link type DLT_USER0
PSEUDO_HEADER_LEN = 12

RATES = {"nrf1m": 0, "nrf2m": 1, "ble1m": 2}


def rev8(b: int) -> int:
    """Reverse the bit order of one byte (0b00000001 -> 0b10000000)."""
    return int(f"{b:08b}"[::-1], 2)


def scramble_table(length: int) -> list:
    """XN297L scramble sequence as MSB-first bytes (E3 B1 4B EA 85 BC ...).

    7-bit LFSR, polynomial x^7 + x^4 + 1 (same generator as BLE whitening),
    initialised to all ones. The output bits are collected LSB first and the
    byte is bit-reversed so it can be XORed onto MSB-first on-air bytes.
    """
    lfsr = [1, 1, 1, 1, 1, 1, 1]
    out = []
    for _ in range(length):
        byte = 0
        for bit in range(8):
            v3, v6 = lfsr[3], lfsr[6]
            lfsr[3], lfsr[2], lfsr[1], lfsr[0] = lfsr[2], lfsr[1], lfsr[0], lfsr[6]
            lfsr[6], lfsr[5] = lfsr[5], lfsr[4]
            lfsr[4] = v3 ^ v6
            byte |= lfsr[0] << bit
        out.append(rev8(byte))
    return out


SCRAMBLE = scramble_table(80)          # enough for 5 + 64 + 2 bytes


def crc16_genibus(data) -> int:
    """CRC-16/CCITT, poly 0x1021, init 0xFFFF, MSB first, final XOR 0xFFFF."""
    crc = 0xFFFF
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else (crc << 1)
            crc &= 0xFFFF
    return crc ^ 0xFFFF


def descramble(data, scrambled: bool = True) -> list:
    """Remove the scrambler from on-air bytes that start at the address."""
    if not scrambled:
        return list(data)
    return [b ^ SCRAMBLE[i] for i, b in enumerate(data)]


def address_to_on_air(tx_addr: bytes, scrambled: bool = True) -> bytes:
    """Convert an address in TX_ADDR (SPI write) order to its on-air form.

    TX_ADDR is written LSByte first and sent MSByte first, so the byte order
    is reversed; then the scrambler is applied (if enabled).
    Example: C1 C2 C3 C4 C5 -> on air C5 C4 C3 C2 C1 -> scrambled 26 75 88 28 44
    """
    on_air = list(reversed(tx_addr))
    if scrambled:
        on_air = [b ^ SCRAMBLE[i] for i, b in enumerate(on_air)]
    return bytes(on_air)


def decode_frame(raw, addr_len: int, payload_len: int = 0, scrambled: bool = True):
    """Decode on-air bytes that start with the first address byte.

    raw          on-air bytes (address first), MSB-first notation
    addr_len     3, 4 or 5
    payload_len  known payload length, or 0 to search the length via CRC
    scrambled    scrambler enabled on the transmitter

    Returns a dict, or None if no payload length with a valid CRC was found
    (in that case 'crc_ok' is False in the returned dict for a known length).
    """
    plain = descramble(raw, scrambled)
    max_len = len(raw) - addr_len - 2

    # Candidate payload lengths: the known one, or all possible ones
    if payload_len > 0:
        candidates = [payload_len] if payload_len <= max_len else []
    else:
        candidates = range(1, min(max_len, 64) + 1)

    for plen in candidates:
        body = plain[:addr_len + plen]                  # address + payload, on-air form
        crc_rx = plain[addr_len + plen] << 8 | plain[addr_len + plen + 1]
        crc_calc = crc16_genibus(body)
        if crc_calc == crc_rx or payload_len > 0:
            address_on_air = plain[:addr_len]
            return {
                "address_tx": bytes(reversed(address_on_air)),     # TX_ADDR order
                # payload bytes are sent LSB first -> bit-reverse to get FIFO values
                "payload": bytes(rev8(b) for b in plain[addr_len:addr_len + plen]),
                "payload_len": plen,
                "crc_rx": crc_rx,
                "crc_calc": crc_calc,
                "crc_ok": crc_calc == crc_rx,
            }
    return None


# ---------------------------------------------------------------------------
# Serial link to the dongle
# ---------------------------------------------------------------------------

class Dongle:
    """Minimal driver for the line based protocol of the firmware."""

    def __init__(self, port: str):
        import serial  # imported here so --extcap-interfaces works without pyserial
        # Baud rate is irrelevant for USB CDC ACM; DTR must be asserted so the
        # firmware starts sending (pyserial asserts DTR by default).
        self.ser = serial.Serial(port, 115200, timeout=0.2)
        try:
            self.ser.dtr = True
        except OSError:
            pass    # e.g. pseudo terminals without modem lines (tests)
        time.sleep(0.2)
        self.ser.reset_input_buffer()

    def command(self, cmd: str, timeout: float = 2.0) -> None:
        """Send one command and wait for 'OK' (raises on 'E ...')."""
        self.ser.write((cmd + "\n").encode("ascii"))
        deadline = time.time() + timeout
        while time.time() < deadline:
            line = self.readline()
            if line is None:
                continue
            if line == "OK":
                return
            if line.startswith("E "):
                raise RuntimeError(f"dongle rejected '{cmd}': {line[2:]}")
            # 'I' lines and late 'P' lines are ignored here
        raise TimeoutError(f"no answer from dongle for '{cmd}'")

    def readline(self):
        """Return one line without line ending, or None on timeout."""
        raw = self.ser.readline()
        if not raw:
            return None
        return raw.decode("ascii", errors="replace").strip()

    def close(self) -> None:
        try:
            self.ser.write(b"stop\n")
            self.ser.flush()
        except Exception:
            pass
        self.ser.close()


def parse_packet_line(line: str):
    """Parse 'P <t_us> <ch> <rssi> <hex>' -> (t_us, ch, rssi, bytes) or None."""
    parts = line.split()
    if len(parts) != 5 or parts[0] != "P":
        return None
    try:
        return int(parts[1]), int(parts[2]), int(parts[3]), bytes.fromhex(parts[4])
    except ValueError:
        return None


def configure(dongle: Dongle, args) -> dict:
    """Send the configuration to the dongle and return capture parameters."""
    scrambled = not args.no_scramble
    payload_len = args.payload_length
    # bytes to capture behind the address: payload (+ search margin) + CRC
    body_len = (payload_len if payload_len > 0 else MAX_PAYLOAD) + 2

    if args.mode == "address":
        tx_addr = bytes.fromhex(args.address.replace(":", "").replace(" ", ""))
        if len(tx_addr) not in (3, 4, 5):
            raise ValueError("address must be 3, 4 or 5 bytes")
        addr_len = len(tx_addr)
        sync = address_to_on_air(tx_addr, scrambled)    # sync on the address
        capture_len = body_len
    else:
        addr_len = args.address_length
        sync = PREAMBLE                                 # sync on the preamble
        capture_len = addr_len + body_len

    dongle.command("stop")
    dongle.command("sync " + sync.hex().upper())
    dongle.command(f"len {capture_len}")
    dongle.command("ch " + args.channels.replace(" ", ""))
    dongle.command(f"dwell {args.dwell}")
    dongle.command(f"rate {args.rate}")
    dongle.command("start")

    return {
        "promiscuous": args.mode != "address",
        "addr_len": addr_len,
        "payload_len": payload_len,
        "scrambled": scrambled,
        "rate": RATES[args.rate],
    }


def frame_bytes(data: bytes, params: dict) -> bytes:
    """Strip the preamble in promiscuous mode so the frame starts at the address."""
    if params["promiscuous"] and data.startswith(PREAMBLE):
        return data[len(PREAMBLE):]
    return data


# ---------------------------------------------------------------------------
# pcap output (extcap)
# ---------------------------------------------------------------------------

def pcap_global_header() -> bytes:
    """Classic pcap file header, microsecond timestamps, DLT_USER0."""
    return struct.pack("<IHHiIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, LINKTYPE_USER0)


def pcap_record(payload: bytes) -> bytes:
    """One pcap record with the current host time as timestamp."""
    now = time.time()
    sec = int(now)
    usec = int((now - sec) * 1_000_000)
    return struct.pack("<IIII", sec, usec, len(payload), len(payload)) + payload


def pseudo_header(params: dict, ch: int, rssi: int, t_us: int) -> bytes:
    """Build the 12 byte pseudo header described in the module docstring."""
    flags = (1 if params["scrambled"] else 0) | (2 if params["promiscuous"] else 0)
    return struct.pack("<BBBbBBBBI", 1, flags, ch, max(-128, min(127, rssi)),
                       params["addr_len"], params["payload_len"], params["rate"],
                       0, t_us & 0xFFFFFFFF)


# ---------------------------------------------------------------------------
# extcap protocol
# ---------------------------------------------------------------------------

INTERFACE = "xn297l"


def extcap_interfaces() -> None:
    print(f"extcap {{version={__version__}}}{{help=https://github.com/J0EK3R/bluetooth-protocols}}")
    print(f"interface {{value={INTERFACE}}}{{display=XN297L sniffer (nRF52840 dongle)}}")


def extcap_dlts() -> None:
    print(f"dlt {{number={LINKTYPE_USER0}}}{{name=USER0}}{{display=XN297L on-air frames}}")


def extcap_config() -> None:
    """Describe the options shown in Wireshark's interface settings dialog."""
    # Serial port: editable list of detected ports
    print("arg {number=0}{call=--port}{display=Serial port}{type=editselector}"
          "{required=true}{tooltip=Virtual COM port of the dongle}")
    try:
        from serial.tools import list_ports
        for p in list_ports.comports():
            print(f"value {{arg=0}}{{value={p.device}}}{{display={p.device} {p.description}}}")
    except Exception:
        pass

    print("arg {number=1}{call=--mode}{display=Sync mode}{type=selector}"
          "{tooltip=address: sync on a known address (robust); "
          "promiscuous: sync on the preamble 71 0F 55 (experimental)}")
    print("value {arg=1}{value=address}{display=Known address}{default=true}")
    print("value {arg=1}{value=promiscuous}{display=Promiscuous (preamble)}")

    print("arg {number=2}{call=--address}{display=Address (TX_ADDR order, hex)}"
          "{type=string}{default=C1C2C3C4C5}"
          "{tooltip=As written to the TX_ADDR register, LSByte first; mode 'address' only}")

    print("arg {number=3}{call=--address-length}{display=Address length (promiscuous)}"
          "{type=selector}")
    for n in (3, 4, 5):
        default = "{default=true}" if n == 5 else ""
        print(f"value {{arg=3}}{{value={n}}}{{display={n} bytes}}{default}")

    print("arg {number=4}{call=--payload-length}{display=Payload length (0 = auto)}"
          "{type=integer}{range=0,64}{default=0}"
          "{tooltip=0 = find the length by checking the CRC}")

    print("arg {number=5}{call=--channels}{display=RF channels (MHz - 2400)}"
          "{type=string}{default=2,26,80}")

    print("arg {number=6}{call=--dwell}{display=Dwell time per channel (ms)}"
          "{type=integer}{range=0,60000}{default=300}{tooltip=0 = stay on the first channel}")

    print("arg {number=7}{call=--rate}{display=Data rate}{type=selector}")
    print("value {arg=7}{value=nrf1m}{display=1 Mbps (nRF)}{default=true}")
    print("value {arg=7}{value=ble1m}{display=1 Mbps (BLE deviation)}")
    print("value {arg=7}{value=nrf2m}{display=2 Mbps (old XN297)}")

    print("arg {number=8}{call=--no-scramble}{display=Scrambler off}{type=boolflag}"
          "{default=false}")


def run_capture(args) -> None:
    """Stream frames into the FIFO given by Wireshark."""
    dongle = Dongle(args.port)
    try:
        params = configure(dongle, args)
        with open(args.fifo, "wb", buffering=0) as fifo:
            fifo.write(pcap_global_header())
            while True:
                line = dongle.readline()
                if line is None:
                    continue
                pkt = parse_packet_line(line)
                if pkt is None:
                    continue
                t_us, ch, rssi, data = pkt
                frame = pseudo_header(params, ch, rssi, t_us) + frame_bytes(data, params)
                fifo.write(pcap_record(frame))
    except (BrokenPipeError, KeyboardInterrupt):
        pass        # Wireshark stopped the capture
    finally:
        dongle.close()


# ---------------------------------------------------------------------------
# Console mode
# ---------------------------------------------------------------------------

def run_print(args) -> None:
    """Print decoded frames to the console (no Wireshark needed)."""
    dongle = Dongle(args.port)
    try:
        params = configure(dongle, args)
        print(f"# capturing, mode={args.mode}, channels={args.channels} (Ctrl+C to stop)")
        while True:
            line = dongle.readline()
            if line is None:
                continue
            pkt = parse_packet_line(line)
            if pkt is None:
                if line.startswith(("I ", "E ")):
                    print("#", line)
                continue
            t_us, ch, rssi, data = pkt
            frame = frame_bytes(data, params)
            res = decode_frame(frame, params["addr_len"], params["payload_len"],
                               params["scrambled"])
            head = f"{t_us / 1e6:12.6f}s {2400 + ch} MHz {rssi:4d} dBm"
            if res is None:
                if args.show_bad:
                    print(f"{head}  no valid CRC     raw {frame.hex(' ').upper()}")
                continue
            status = "CRC ok " if res["crc_ok"] else "CRC BAD"
            if not res["crc_ok"] and not args.show_bad:
                continue
            print(f"{head}  addr {res['address_tx'].hex(':').upper()}  {status}  "
                  f"len {res['payload_len']:2d}  payload {res['payload'].hex(' ').upper()}")
    except KeyboardInterrupt:
        pass
    finally:
        dongle.close()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="XN297L sniffer for the nRF52840 dongle")

    # extcap protocol arguments (called by Wireshark)
    p.add_argument("--extcap-interfaces", action="store_true")
    p.add_argument("--extcap-interface")
    p.add_argument("--extcap-dlts", action="store_true")
    p.add_argument("--extcap-config", action="store_true")
    p.add_argument("--extcap-version")
    p.add_argument("--extcap-capture-filter")
    p.add_argument("--capture", action="store_true")
    p.add_argument("--fifo")

    # sniffer options (shown in Wireshark, usable on the command line)
    p.add_argument("--port", help="serial port of the dongle, e.g. COM5 or /dev/ttyACM0")
    p.add_argument("--mode", choices=["address", "promiscuous"], default="address")
    p.add_argument("--address", default="C1C2C3C4C5",
                   help="address in TX_ADDR order (hex), used in mode 'address'")
    p.add_argument("--address-length", type=int, choices=[3, 4, 5], default=5,
                   help="address length, used in mode 'promiscuous'")
    p.add_argument("--payload-length", type=int, default=0,
                   help="payload length, 0 = find via CRC")
    p.add_argument("--channels", default="2,26,80",
                   help="RF channels (MHz - 2400), comma separated")
    p.add_argument("--dwell", type=int, default=300, help="ms per channel, 0 = no hopping")
    p.add_argument("--rate", choices=list(RATES), default="nrf1m")
    p.add_argument("--no-scramble", action="store_true", help="transmitter has scrambler off")

    # console mode
    p.add_argument("--print", action="store_true", help="print decoded frames to the console")
    p.add_argument("--show-bad", action="store_true", help="also print frames with bad CRC")
    p.add_argument("--list-ports", action="store_true", help="list serial ports and exit")
    return p


def main() -> int:
    args = build_parser().parse_args()

    if args.extcap_interfaces:
        extcap_interfaces()
        return 0
    if args.extcap_dlts:
        extcap_dlts()
        return 0
    if args.extcap_config:
        extcap_config()
        return 0
    if args.list_ports:
        from serial.tools import list_ports
        for p in list_ports.comports():
            print(f"{p.device:15s} {p.description}")
        return 0

    if args.capture or args.print:
        if not args.port:
            print("error: --port is required", file=sys.stderr)
            return 1
        if args.capture:
            if not args.fifo:
                print("error: --fifo is required for --capture", file=sys.stderr)
                return 1
            run_capture(args)
        else:
            run_print(args)
        return 0

    build_parser().print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
