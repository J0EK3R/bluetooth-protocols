#!/usr/bin/env python3
"""
XN297L sniffer - Wireshark extcap interface and command line tool.

Talks to the nRF52840 dongle firmware (../firmware) over its USB virtual COM
port and either

  * streams the received frames into Wireshark (extcap mode, DLT_USER0), or
  * prints decoded frames to the console (--print mode).

Two extcap interfaces are offered by this one script:

  xn297l      XN297L / raw GFSK frames, DLT_USER0 (147)        - see below
  xn297l_ble  Bluetooth LE sniffer, DLT 256 (LE LL with PHDR)  - ble_*.py modules,
              interface toolbar with device list (extcap control channel)

The BLE interface needs firmware 2.0.0 or newer and the modules ble_phdr.py,
ble_pdu.py, ble_session.py and ble_control.py next to this script.

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

Raw mode: sync on any 3..5 bytes and print the captured bytes undecoded, e.g.
the alternating preamble AA AA AA to find an unknown (non-XN297L) transmitter:
    python xn297l_sniffer.py --print --port COM5 --mode raw --sync AAAAAA \
        --raw-length 64 --channels 0-83 --dwell 50

Pseudo header in front of every frame (12 bytes, little endian)
-------------------------------------------------------------
    offset size  field
    0      1     version (= 1)
    1      1     flags: bit0 = scrambler on, bit1 = promiscuous capture,
                 bit2 = raw capture (bytes start with the sync word, no XN297L decoding)
    2      1     RF channel (MHz - 2400)
    3      1     RSSI in dBm (signed)
    4      1     address length (3..5); raw capture: sync word length
    5      1     payload length (0 = unknown, find it via CRC)
    6      1     data rate: 0 = nrf1m, 1 = nrf2m, 2 = ble1m
    7      1     reserved (0)
    8      4     device timestamp in microseconds
    12     ...   on-air bytes starting with the first address byte
                 (raw capture: starting with the sync word)
"""

import argparse
import os
import struct
import sys
import time

__version__ = "2.0.0"

# ---------------------------------------------------------------------------
# XN297L constants and helpers (see Chips/XN297L.md, section 5)
# ---------------------------------------------------------------------------

PREAMBLE = bytes([0x71, 0x0F, 0x55])   # fixed XN297L preamble, never scrambled
MAX_PAYLOAD = 32                       # normal mode payload limit
LINKTYPE_USER0 = 147                   # pcap link type DLT_USER0
PSEUDO_HEADER_LEN = 12

RATES = {"nrf1m": 0, "nrf2m": 1, "ble1m": 2}

RAW_LEN_MAX = 250                      # firmware limit for the bytes after the sync word

PYSERIAL_HINT = ("pyserial is not installed for the Python interpreter running this script "
                 "({exe}). Install it with:  \"{exe}\" -m pip install pyserial")


def import_serial():
    """Import pyserial or exit with a clear message (shown by Wireshark on failure)."""
    try:
        import serial
        return serial
    except ImportError:
        sys.stderr.write(PYSERIAL_HINT.format(exe=sys.executable) + "\n")
        sys.exit(1)


def list_serial_ports() -> list:
    """Return the available serial ports as a list of (device, description).

    Uses pyserial if available. Without pyserial, Windows ports are read from
    the registry (HKLM\\HARDWARE\\DEVICEMAP\\SERIALCOMM) so that the port list
    in Wireshark is not empty.
    """
    try:
        from serial.tools import list_ports
        return [(p.device, p.description) for p in list_ports.comports()]
    except ImportError:
        pass

    ports = []
    if sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                r"HARDWARE\DEVICEMAP\SERIALCOMM") as key:
                index = 0
                while True:
                    try:
                        name, value, _ = winreg.EnumValue(key, index)
                    except OSError:
                        break           # no more values
                    ports.append((value, name))
                    index += 1
        except OSError:
            pass                        # key missing: no serial ports at all
    return ports


def pyserial_available() -> bool:
    """True if pyserial can be imported."""
    try:
        import serial  # noqa: F401
        return True
    except ImportError:
        return False


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


SCRAMBLE = scramble_table(256)         # enough for the maximum capture (sync + 250 bytes)


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
        # imported here so --extcap-interfaces/--extcap-config work without pyserial
        serial = import_serial()
        # Baud rate is irrelevant for USB CDC ACM; DTR must be asserted so the
        # firmware starts sending (pyserial asserts DTR by default).
        # The port may still be held for a moment by a previous capture that is
        # shutting down, so retry for a few seconds before giving up.
        last_error = None
        for _ in range(10):
            try:
                self.ser = serial.Serial(port, 115200, timeout=0.2)
                break
            except serial.SerialException as exc:
                last_error = exc
                time.sleep(0.5)
        else:
            sys.stderr.write(
                f"Cannot open serial port {port}: {last_error}\n"
                "The port is probably in use by another program, e.g. a terminal, "
                "the nRF Sniffer extcap or a python.exe left over from a previous "
                "capture (end it in the Task Manager or re-plug the dongle).\n")
            sys.exit(1)
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


CHANNEL_MAX = 100                      # highest RF channel (2500 MHz), firmware limit
CHANNEL_LIST_MAX = 84                  # max. entries in the expanded channel list (firmware)

# Regex used by Wireshark ({validation=...}) to mark an invalid channel list red.
# It accepts the same syntax as parse_channels(): numbers 0..100 (leading zeros and
# spaces tolerated), optional ranges n-m, comma separated. It does NOT check n <= m
# or the 84 entry limit (a regex cannot); parse_channels() does that. No braces are
# used because braces would end the extcap field.
_CH_NUM = r"0*(100|[1-9]?[0-9])"
_CH_ENTRY = rf"{_CH_NUM}(\s*-\s*{_CH_NUM})?"
CHANNEL_REGEX = rf"^\s*{_CH_ENTRY}(\s*,\s*{_CH_ENTRY})*\s*$"


def parse_channels(text: str) -> list:
    """Parse and validate an RF channel list, mirroring the firmware 'ch' command.

    Syntax: single channels and ranges n-m, comma separated, e.g. "2,26,80",
    "0-83" or "1,20,30,40-83". Channel = MHz - 2400, allowed 0..100. The
    expanded list may have at most 84 entries (duplicates count).

    Returns the expanded list of channel numbers; raises ValueError with a
    clear message if the list is invalid.
    """
    channels = []
    for entry in text.split(","):
        entry = entry.strip()           # spaces around an entry are tolerated
        if not entry:
            raise ValueError(f"channel list '{text}' has an empty entry "
                             "(example: 2,26,80 or 0-83)")
        first_s, sep, last_s = (part.strip() for part in entry.partition("-"))
        # isdigit() also rejects signs, so "-5" or "1--3" end up here
        if not first_s.isdigit() or (sep and not last_s.isdigit()):
            raise ValueError(f"'{entry}' is not a channel or range n-m "
                             "(example: 2,26,80 or 0-83)")
        first = int(first_s)
        last = int(last_s) if sep else first
        if first > CHANNEL_MAX or last > CHANNEL_MAX:
            raise ValueError(f"'{entry}': channels must be 0..{CHANNEL_MAX} (MHz - 2400)")
        if last < first:
            raise ValueError(f"'{entry}': range must be n-m with n <= m")
        channels.extend(range(first, last + 1))
        if len(channels) > CHANNEL_LIST_MAX:
            raise ValueError(f"channel list has more than {CHANNEL_LIST_MAX} entries "
                             "(firmware limit)")
    return channels


def configure(dongle: Dongle, args) -> dict:
    """Send the configuration to the dongle and return capture parameters."""
    scrambled = not args.no_scramble
    payload_len = args.payload_length
    parse_channels(args.channels)       # fail early with a clear message, before touching the dongle
    # bytes to capture behind the address: payload (+ search margin) + CRC
    # + optional extra bytes, e.g. to see an acknowledgement that follows the frame
    body_len = (payload_len if payload_len > 0 else MAX_PAYLOAD) + 2 + args.extra_bytes

    if args.mode == "raw":
        sync = parse_sync(args.sync)
        if not 1 <= args.raw_length <= RAW_LEN_MAX:
            raise ValueError(f"raw length must be 1..{RAW_LEN_MAX}")
        addr_len = len(sync)                            # reported as sync word length
        payload_len = 0
        capture_len = args.raw_length
    elif args.mode == "address":
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
    dongle.command(f"len {min(capture_len, 250)}")
    dongle.command("ch " + args.channels.replace(" ", ""))   # validated above
    dongle.command(f"dwell {args.dwell}")
    dongle.command(f"rate {args.rate}")
    dongle.command("start")

    return {
        "promiscuous": args.mode == "promiscuous",
        "raw": args.mode == "raw",
        "addr_len": addr_len,
        "payload_len": payload_len,
        "scrambled": scrambled,
        "rate": RATES[args.rate],
    }


def parse_sync(text: str) -> bytes:
    """Parse a raw sync word (3..5 hex bytes, on-air order, MSB first)."""
    sync = bytes.fromhex(text.replace(":", "").replace(" ", ""))
    if len(sync) not in (3, 4, 5):
        raise ValueError("sync word must be 3, 4 or 5 bytes")
    return sync


def format_raw(data: bytes, sync_len: int) -> str:
    """Raw capture as hex: sync word | captured bytes."""
    return f"{data[:sync_len].hex(' ').upper()} | {data[sync_len:].hex(' ').upper()}"


def frame_bytes(data: bytes, params: dict) -> bytes:
    """Strip the preamble in promiscuous mode so the frame starts at the address.

    Raw captures are passed on unchanged (sync word + captured bytes).
    """
    if params.get("raw"):
        return data
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
    flags = ((1 if params["scrambled"] else 0) | (2 if params["promiscuous"] else 0)
             | (4 if params.get("raw") else 0))
    return struct.pack("<BBBbBBBBI", 1, flags, ch, max(-128, min(127, rssi)),
                       params["addr_len"], params["payload_len"], params["rate"],
                       0, t_us & 0xFFFFFFFF)


# ---------------------------------------------------------------------------
# extcap protocol
# ---------------------------------------------------------------------------

INTERFACE = "xn297l"                    # XN297L / raw frames, DLT_USER0
INTERFACE_BLE = "xn297l_ble"            # Bluetooth LE sniffer, DLT 256
LINKTYPE_BLE_PHDR = 256                 # LINKTYPE_BLUETOOTH_LE_LL_WITH_PHDR


def extcap_interfaces() -> None:
    print(f"extcap {{version={__version__}}}{{help=https://github.com/J0EK3R/bluetooth-protocols}}")
    print(f"interface {{value={INTERFACE}}}{{display=XN297L sniffer (nRF52840 dongle)}}")
    print(f"interface {{value={INTERFACE_BLE}}}{{display=BLE sniffer (nRF52840 dongle)}}")


def extcap_dlts(interface: str = INTERFACE) -> None:
    """Print the link type of an interface (Wireshark asks per interface)."""
    if interface == INTERFACE_BLE:
        print(f"dlt {{number={LINKTYPE_BLE_PHDR}}}{{name=BLUETOOTH_LE_LL_WITH_PHDR}}"
              "{display=Bluetooth Low Energy Link Layer with pseudo header}")
    else:
        print(f"dlt {{number={LINKTYPE_USER0}}}{{name=USER0}}{{display=XN297L on-air frames}}")


def extcap_text(text: str) -> str:
    """Make a text safe for the extcap protocol: braces would end a field."""
    return str(text).replace("{", "(").replace("}", ")")


GROUP_GENERAL = "General"
GROUP_XN297L = "XN297L (address / promiscuous)"
GROUP_RAW = "Raw mode"


def extcap_config(interface: str = INTERFACE) -> None:
    """Describe the options shown in Wireshark's interface settings dialog.

    The BLE interface has its own options and toolbar (extcap_config_ble()).

    The options are grouped into tabs ({group=...}). Argument numbers and
    --call names are stable so saved Wireshark settings stay valid. Labels and
    tooltips say which sync mode uses an option and which values are allowed.
    """
    if interface == INTERFACE_BLE:
        extcap_config_ble()
        return
    g = f"{{group={GROUP_GENERAL}}}"
    x = f"{{group={GROUP_XN297L}}}"
    r = f"{{group={GROUP_RAW}}}"

    # Serial port: editable list of detected ports
    # The tooltip warns if pyserial is missing (capturing would fail later).
    tooltip = "Virtual COM port of the dongle (the field is editable, e.g. COM8). Used in all modes"
    if not pyserial_available():
        tooltip = "WARNING: " + PYSERIAL_HINT.format(exe=sys.executable)
    print("arg {number=0}{call=--port}{display=Serial port}{type=editselector}"
          f"{{required=true}}{{tooltip={extcap_text(tooltip)}}}{g}")
    for device, description in list_serial_ports():
        print(f"value {{arg=0}}{{value={extcap_text(device)}}}"
              f"{{display={extcap_text(device)} {extcap_text(description)}}}")

    print("arg {number=1}{call=--mode}{display=Sync mode}{type=selector}"
          "{tooltip=Used in all modes. address: sync on a known address (robust); "
          "promiscuous: sync on the preamble 71 0F 55 (experimental); "
          "raw: sync on any 3..5 bytes, no XN297L decoding (unknown transmitters)}" + g)
    print("value {arg=1}{value=address}{display=Known address}{default=true}")
    print("value {arg=1}{value=promiscuous}{display=Promiscuous (preamble)}")
    print("value {arg=1}{value=raw}{display=Raw (any sync word)}")

    print("arg {number=5}{call=--channels}"
          "{display=RF channels (0-100, e.g. 2,26,80 or 0-83)}"
          "{type=string}{default=2,26,80}{placeholder=2,26,80 or 0-83 or 1,20,30,40-83}"
          f"{{validation={CHANNEL_REGEX}}}"
          "{tooltip=Used in all modes. Channel = frequency in MHz - 2400, allowed 0..100. "
          "Single channels and ranges n-m can be mixed, e.g. 1,20,30,40-83. "
          f"At most {CHANNEL_LIST_MAX} channels in total (firmware limit)}}" + g)

    print("arg {number=6}{call=--dwell}{display=Dwell time per channel (ms, 0-60000)}"
          "{type=integer}{range=0,60000}{default=300}"
          "{tooltip=Used in all modes. Time spent on each channel before hopping to the next. "
          "0 = stay on the first channel. Allowed 0..60000}" + g)

    print("arg {number=7}{call=--rate}{display=Data rate}{type=selector}"
          "{tooltip=Used in all modes. Air data rate / frequency deviation of the receiver}" + g)
    print("value {arg=7}{value=nrf1m}{display=1 Mbps (nRF)}{default=true}")
    print("value {arg=7}{value=ble1m}{display=1 Mbps (BLE deviation)}")
    print("value {arg=7}{value=nrf2m}{display=2 Mbps (old XN297)}")

    print("arg {number=2}{call=--address}{display=Address (TX_ADDR order, hex) - address mode}"
          "{type=string}{default=C1C2C3C4C5}{placeholder=C1C2C3C4C5}"
          "{validation=^\\s*([0-9A-Fa-f][0-9A-Fa-f][:\\s]*)+\\s*$}"
          "{tooltip=Address mode only. 3, 4 or 5 bytes as hex (6, 8 or 10 digits), "
          "as written to the TX_ADDR register, LSByte first}" + x)

    print("arg {number=3}{call=--address-length}{display=Address length - promiscuous mode}"
          "{type=selector}"
          "{tooltip=Promiscuous mode only. Length of the address after the preamble: "
          "3, 4 or 5 bytes}" + x)
    for n in (3, 4, 5):
        default = "{default=true}" if n == 5 else ""
        print(f"value {{arg=3}}{{value={n}}}{{display={n} bytes}}{default}")

    print("arg {number=4}{call=--payload-length}"
          "{display=Payload length (0-64, 0 = auto) - address + promiscuous}"
          "{type=integer}{range=0,64}{default=0}"
          "{tooltip=Address and promiscuous mode. Allowed 0..64. "
          "0 = find the length by checking the CRC}" + x)

    print("arg {number=8}{call=--no-scramble}{display=Scrambler off - address + promiscuous}"
          "{type=boolflag}{default=false}"
          "{tooltip=Address and promiscuous mode. Tick if the transmitter has its "
          "scrambler switched off}" + x)

    print("arg {number=9}{call=--extra-bytes}"
          "{display=Extra bytes after the frame (0-200) - address + promiscuous}"
          "{type=integer}{range=0,200}{default=0}"
          "{tooltip=Address and promiscuous mode. Allowed 0..200. Capture this many "
          "additional bytes (8 us each at 1 Mbps), e.g. to see an "
          "acknowledgement sent right after the frame. Total capture is limited to 250 bytes}" + x)

    print("arg {number=10}{call=--sync}{display=Sync word (hex, 3-5 bytes) - raw mode}"
          "{type=string}{default=AAAAAA}{placeholder=AAAAAA}"
          "{validation=^\\s*([0-9A-Fa-f][0-9A-Fa-f][:\\s]*)+\\s*$}"
          "{tooltip=Raw mode only. 3..5 bytes (6, 8 or 10 hex digits) in on-air order, "
          "MSB first; AAAAAA or 555555 = alternating "
          "preamble of an unknown transmitter}" + r)

    print("arg {number=11}{call=--raw-length}{display=Capture length (1-250) - raw mode}"
          "{type=integer}{range=1,250}{default=64}"
          "{tooltip=Raw mode only. Bytes captured after the sync word, allowed 1..250}" + r)


class ParentWatchdog:
    """Detect that the capture was stopped by Wireshark (Windows wrapper chain).

    On Windows, Wireshark starts the .bat wrapper (cmd.exe), which starts
    py.exe, which starts python.exe (this script). When the capture is
    stopped, Wireshark terminates only cmd.exe; py.exe and python.exe would
    keep running and keep the COM port open, so the next capture fails with
    "access denied".

    The watchdog therefore keeps handles to the wrapper processes between
    this script and cmd.exe (py.exe and cmd.exe) and reports when one of them
    has exited. Processes above cmd.exe are NOT watched: GLib starts extcaps
    through a short-lived helper process (gspawn-win64-helper), which exits
    right after the start and must not stop the capture.

    On other systems Wireshark starts the script directly and stops it with a
    signal, so nothing needs to be watched. All errors are ignored: the
    watchdog is a best-effort helper.
    """

    SYNCHRONIZE = 0x00100000
    WRAPPER_NAMES = ("py.exe", "pyw.exe", "python.exe", "pythonw.exe", "cmd.exe")

    def __init__(self):
        self.handles = []
        self._k32 = None
        if sys.platform == "win32":
            try:
                self._open_wrappers()
            except Exception:
                self.handles = []

    def _open_wrappers(self) -> None:
        import ctypes
        from ctypes import wintypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        k32.OpenProcess.restype = wintypes.HANDLE

        class PROCESSENTRY32W(ctypes.Structure):
            _fields_ = [("dwSize", wintypes.DWORD),
                        ("cntUsage", wintypes.DWORD),
                        ("th32ProcessID", wintypes.DWORD),
                        ("th32DefaultHeapID", ctypes.c_size_t),
                        ("th32ModuleID", wintypes.DWORD),
                        ("cntThreads", wintypes.DWORD),
                        ("th32ParentProcessID", wintypes.DWORD),
                        ("pcPriClassBase", ctypes.c_long),
                        ("dwFlags", wintypes.DWORD),
                        ("szExeFile", ctypes.c_wchar * 260)]

        # Snapshot of all processes -> pid: (parent pid, exe name)
        snap = k32.CreateToolhelp32Snapshot(0x2, 0)       # TH32CS_SNAPPROCESS
        procs = {}
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        ok = k32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            procs[entry.th32ProcessID] = (entry.th32ParentProcessID,
                                          entry.szExeFile.lower())
            ok = k32.Process32NextW(snap, ctypes.byref(entry))
        k32.CloseHandle(snap)

        # Walk up: watch py.exe / cmd.exe wrappers, stop at (and include) cmd.exe
        pid = procs.get(os.getpid(), (0, ""))[0]
        for _ in range(4):
            parent, name = procs.get(pid, (0, ""))
            if pid in (0, 4) or name not in self.WRAPPER_NAMES:
                break                                      # not a wrapper: stop
            handle = k32.OpenProcess(self.SYNCHRONIZE, False, pid)
            if handle:
                self.handles.append(handle)
            if name == "cmd.exe":
                break                                      # top of the wrapper chain
            pid = parent
        self._k32 = k32

    def parent_gone(self) -> bool:
        """True if one of the watched wrapper processes has exited."""
        try:
            for handle in self.handles:
                # WAIT_OBJECT_0 (0) = process has terminated
                if self._k32.WaitForSingleObject(handle, 0) == 0:
                    return True
        except Exception:
            pass
        return False


def run_capture(args) -> None:
    """Stream frames into the FIFO given by Wireshark."""
    watchdog = ParentWatchdog()
    dongle = Dongle(args.port)
    last_check = time.time()
    try:
        params = configure(dongle, args)
        with open(args.fifo, "wb", buffering=0) as fifo:
            fifo.write(pcap_global_header())
            while True:
                # Stop when Wireshark has stopped the capture (checked once a second)
                if time.time() - last_check >= 1.0:
                    last_check = time.time()
                    if watchdog.parent_gone():
                        break
                line = dongle.readline()
                if line is None:
                    continue
                pkt = parse_packet_line(line)
                if pkt is None:
                    continue
                t_us, ch, rssi, data = pkt
                frame = pseudo_header(params, ch, rssi, t_us) + frame_bytes(data, params)
                fifo.write(pcap_record(frame))
    except (BrokenPipeError, OSError, KeyboardInterrupt):
        pass        # Wireshark stopped the capture (pipe closed)
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
        extra = (f", sync={args.sync.upper()}, length={args.raw_length}"
                 if args.mode == "raw" else "")
        print(f"# capturing, mode={args.mode}{extra}, channels={args.channels}, "
              f"rate={args.rate} (Ctrl+C to stop)", flush=True)
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
            head = f"{t_us / 1e6:12.6f}s {2400 + ch} MHz {rssi:4d} dBm"
            if params["raw"]:
                print(f"{head}  raw {format_raw(data, params['addr_len'])}", flush=True)
                continue
            frame = frame_bytes(data, params)
            res = decode_frame(frame, params["addr_len"], params["payload_len"],
                               params["scrambled"])
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
# Bluetooth LE interface (xn297l_ble)
# ---------------------------------------------------------------------------

GROUP_BLE = "General"

# Argument numbers of the BLE interface (XN297L uses 0..11, these start at 100)
BLE_ARG_PORT = 100
BLE_ARG_ONLY_ADV = 101
BLE_ARG_ADV_HOP = 102
BLE_ARG_RSSI = 103
BLE_ARG_DWELL = 104

# Control numbers of the interface toolbar (keep stable: Wireshark stores values by number).
# 1 and 2 are reserved for the key type / key value controls (decryption, later milestone).
CTRL_DEVICE = 0
CTRL_ADV_HOP = 3
CTRL_RSSI = 4
CTRL_DEFAULTS = 5

ADV_CHANNELS = (37, 38, 39)
DEFAULT_ADV_HOP = "37,38,39"
RSSI_OFF = -127                         # "no RSSI filter" (also the firmware default)
BLE_DWELL_DEFAULT = 300                 # ms per advertising channel
FIRMWARE_TOO_OLD = ("The dongle firmware does not support the BLE sniffer (command 'mode ble' "
                    "rejected). Flash firmware 2.0.0 or newer (firmware/prebuilt/).")

# Regex for the advertising channel list fields: 37, 38, 39 in any order, comma separated
ADV_HOP_REGEX = r"^\s*3[789](\s*,\s*3[789])*\s*$"
# Regex for the RSSI threshold: 0 or -1 ... -127
RSSI_REGEX = r"^\s*(0|-([1-9]|[1-9][0-9]|1[01][0-9]|12[0-7]))\s*$"


def parse_adv_hop(text: str) -> list:
    """Parse the advertising channel hop list, e.g. "37,38,39" or "39,37".

    Only the channel indices 37, 38 and 39 are allowed, each at most once;
    the order is the hop order. Raises ValueError with a clear message.
    """
    channels = []
    for entry in text.split(","):
        entry = entry.strip()
        if not entry.isdigit() or int(entry) not in ADV_CHANNELS:
            raise ValueError(f"'{entry}' is not an advertising channel; use 37, 38 and 39, "
                             "e.g. 37,38,39")
        if int(entry) in channels:
            raise ValueError(f"advertising channel {entry} is listed twice")
        channels.append(int(entry))
    return channels


def parse_rssi(text) -> int:
    """Parse an RSSI threshold in dBm (-127 ... 0, -127 = filter off)."""
    try:
        value = int(str(text).strip())
    except ValueError:
        raise ValueError(f"RSSI filter '{text}' is not a number (-127 ... 0 dBm)") from None
    if not RSSI_OFF <= value <= 0:
        raise ValueError(f"RSSI filter {value} out of range (-127 ... 0 dBm)")
    return value


def extcap_config_ble() -> None:
    """Options and interface toolbar of the BLE interface.

    Options (Interface Options dialog) are fixed for a capture. The toolbar
    controls can be changed while capturing; they talk to this script through
    the extcap control channel (see ble_control.py).
    """
    g = f"{{group={GROUP_BLE}}}"
    tooltip = "Virtual COM port of the dongle (the field is editable, e.g. COM8)"
    if not pyserial_available():
        tooltip = "WARNING: " + PYSERIAL_HINT.format(exe=sys.executable)
    print(f"arg {{number={BLE_ARG_PORT}}}{{call=--port}}{{display=Serial port}}{{type=editselector}}"
          f"{{required=true}}{{tooltip={extcap_text(tooltip)}}}{g}")
    for device, description in list_serial_ports():
        print(f"value {{arg={BLE_ARG_PORT}}}{{value={extcap_text(device)}}}"
              f"{{display={extcap_text(device)} {extcap_text(description)}}}")

    print(f"arg {{number={BLE_ARG_ONLY_ADV}}}{{call=--only-advertising}}"
          "{display=Only advertising packets}{type=boolflag}{default=false}"
          "{tooltip=Capture advertising packets only and never follow a connection}" + g)
    print(f"arg {{number={BLE_ARG_ADV_HOP}}}{{call=--adv-hop}}"
          "{display=Advertising channel hop sequence}{type=string}"
          f"{{default={DEFAULT_ADV_HOP}}}{{placeholder={DEFAULT_ADV_HOP}}}"
          f"{{validation={ADV_HOP_REGEX}}}"
          "{tooltip=Advertising channels to scan, in hop order: any of 37, 38, 39 "
          "separated by commas, e.g. 37,38,39 or 39. Can also be changed in the toolbar}" + g)
    print(f"arg {{number={BLE_ARG_RSSI}}}{{call=--rssi-filter}}"
          "{display=RSSI filter (dBm, -127 = off)}{type=integer}{range=-127,0}"
          f"{{default={RSSI_OFF}}}"
          "{tooltip=Hide advertising packets weaker than this signal strength. "
          "-127 switches the filter off. Connection packets are never filtered}" + g)
    print(f"arg {{number={BLE_ARG_DWELL}}}{{call=--adv-dwell}}"
          "{display=Dwell time per advertising channel (ms, 0-60000)}{type=integer}"
          f"{{range=0,60000}}{{default={BLE_DWELL_DEFAULT}}}"
          "{tooltip=Time spent on each advertising channel before hopping to the next one. "
          "0 = stay on the first channel}" + g)

    # Interface toolbar
    print(f"control {{number={CTRL_DEVICE}}}{{type=selector}}{{display=Device}}"
          "{tooltip=Advertising devices seen recently. Selecting one follows it "
          "(connection following needs a later firmware version)}")
    print(f"value {{control={CTRL_DEVICE}}}{{value={'all'}}}"
          "{display=All advertising devices}{default=true}")
    print(f"control {{number={CTRL_ADV_HOP}}}{{type=string}}{{display=Adv Hop}}"
          f"{{default={DEFAULT_ADV_HOP}}}{{validation={ADV_HOP_REGEX}}}"
          "{tooltip=Advertising channels to scan in hop order, e.g. 37,38,39}")
    print(f"control {{number={CTRL_RSSI}}}{{type=string}}{{display=RSSI filter}}"
          f"{{default={RSSI_OFF}}}{{validation={RSSI_REGEX}}}"
          "{tooltip=Hide advertising packets weaker than this RSSI in dBm (-127 = off)}")
    print(f"control {{number={CTRL_DEFAULTS}}}{{type=button}}{{role=restore}}{{display=Defaults}}"
          "{tooltip=Restore the default toolbar settings}")


def configure_ble(dongle, args) -> dict:
    """Send the BLE configuration to the dongle and start the scanner.

    Returns the capture parameters. Raises ValueError for invalid options and
    RuntimeError (with a clear text) if the firmware is too old.
    """
    channels = parse_adv_hop(args.adv_hop)              # validate before touching the dongle
    rssi_min = parse_rssi(args.rssi_filter)
    if not 0 <= args.adv_dwell <= 60000:
        raise ValueError("dwell time must be 0..60000 ms")

    dongle.command("stop")
    try:
        dongle.command("mode ble")
    except RuntimeError as exc:                         # old firmware: unknown command
        raise RuntimeError(FIRMWARE_TOO_OLD) from exc
    dongle.command("bch " + ",".join(str(c) for c in channels))
    dongle.command(f"bdwell {args.adv_dwell}")
    dongle.command(f"brssi {rssi_min}")
    dongle.command("badv " + ("on" if args.only_advertising else "off"))
    dongle.command("start")
    return {"channels": channels, "rssi_min": rssi_min}


class ToolbarHandler:
    """Reacts to the user input of the interface toolbar.

    Messages arrive as (control, command, payload). The handler talks to the
    dongle (hop list, RSSI filter), updates the session and returns the
    messages to send back to Wireshark as (control, command, payload) tuples.
    """

    def __init__(self, dongle, session, ble_control):
        self.dongle = dongle
        self.session = session
        self.ctl = ble_control          # the ble_control module (constants)
        self.follow = "all"             # selected device value

    def _status(self, text: str) -> tuple:
        return (CTRL_DEVICE, self.ctl.CMD_STATUSBAR, text)

    def handle(self, control: int, command: int, payload: bytes) -> list:
        """Process one message from Wireshark."""
        text = payload.decode("utf-8", errors="replace").strip()
        if command == self.ctl.CMD_INITIALIZED:
            return self.initial_messages()
        if command != self.ctl.CMD_SET:
            return []
        try:
            if control == CTRL_DEVICE:
                return self._select_device(text)
            if control == CTRL_ADV_HOP:
                return self._set_hop(text)
            if control == CTRL_RSSI:
                return self._set_rssi(text)
            if control == CTRL_DEFAULTS:
                return self._defaults()
        except (ValueError, RuntimeError, TimeoutError) as exc:
            return [self._status(f"Error: {exc}")]
        return []

    def initial_messages(self) -> list:
        """Toolbar is ready: announce the devices known so far and the state."""
        messages = [(CTRL_DEVICE, self.ctl.CMD_ADD, dev.value + "\0" + dev.display)
                    for dev in self.session.devices.devices.values()]
        messages.append(self._status("BLE sniffer running"))
        return messages

    def _select_device(self, value: str) -> list:
        """Device selector: remember the choice (following is not implemented yet)."""
        self.follow = value
        if value == "all":
            return [self._status("Capturing all advertising devices")]
        return [self._status(f"Selected {value.split(',')[0]}; following connections "
                             "is not supported by this firmware version yet")]

    def _set_hop(self, text: str) -> list:
        channels = parse_adv_hop(text)
        self.dongle.command("bch " + ",".join(str(c) for c in channels))
        return [self._status("Advertising hop sequence: " + ",".join(str(c) for c in channels))]

    def _set_rssi(self, text: str) -> list:
        value = parse_rssi(text)
        self.session.rssi_min = value                   # host filter ...
        self.dongle.command(f"brssi {value}")           # ... and the firmware filter
        return [self._status("RSSI filter off" if value == RSSI_OFF
                             else f"RSSI filter {value} dBm")]

    def _defaults(self) -> list:
        """Defaults button: back to all channels, no RSSI filter, all devices."""
        self.follow = "all"
        self.session.rssi_min = RSSI_OFF
        self.dongle.command("bch " + DEFAULT_ADV_HOP)
        self.dongle.command(f"brssi {RSSI_OFF}")
        return [(CTRL_ADV_HOP, self.ctl.CMD_SET, DEFAULT_ADV_HOP),
                (CTRL_RSSI, self.ctl.CMD_SET, str(RSSI_OFF)),
                (CTRL_DEVICE, self.ctl.CMD_SET, "all"),
                self._status("Defaults restored")]


def device_event_messages(events, ctl) -> list:
    """Translate session events ('add'/'remove'/'status') into toolbar messages."""
    messages = []
    for event in events:
        if event[0] == "add":
            messages.append((CTRL_DEVICE, ctl.CMD_ADD, event[1] + "\0" + event[2]))
        elif event[0] == "remove":
            messages.append((CTRL_DEVICE, ctl.CMD_REMOVE, event[1]))
        elif event[0] == "status":
            messages.append((CTRL_DEVICE, ctl.CMD_STATUSBAR, event[1]))
    return messages


def load_ble_modules():
    """Import the BLE helper modules from the directory of this script.

    Done lazily so the XN297L interface and the extcap queries work even if the
    ble_*.py files are missing, and so the script directory is searched first.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)
    try:
        import ble_control
        import ble_phdr
        import ble_session
    except ImportError as exc:
        sys.stderr.write(f"BLE sniffer modules missing next to {__file__}: {exc}\n"
                         "Copy ble_phdr.py, ble_pdu.py, ble_session.py and ble_control.py "
                         "into the same folder as xn297l_sniffer.py.\n")
        sys.exit(1)
    return ble_control, ble_phdr, ble_session


def run_capture_ble(args) -> None:
    """Stream BLE packets into the FIFO of Wireshark (DLT 256) and serve the toolbar."""
    ble_control, ble_phdr, ble_session = load_ble_modules()
    watchdog = ParentWatchdog()
    dongle = Dongle(args.port)
    session = ble_session.Session(parse_rssi(args.rssi_filter))
    channel = None
    last_check = last_expire = time.time()
    try:
        configure_ble(dongle, args)
        if args.extcap_control_in and args.extcap_control_out:
            channel = ble_control.ControlChannel(args.extcap_control_in, args.extcap_control_out)
            channel.start()
        handler = ToolbarHandler(dongle, session, ble_control)
        with open(args.fifo, "wb", buffering=0) as fifo:
            fifo.write(ble_phdr.pcap_header_256())
            while True:
                now = time.time()
                if now - last_check >= 1.0:
                    last_check = now
                    if watchdog.parent_gone():
                        break
                if now - last_expire >= 1.0 and channel is not None:
                    last_expire = now
                    for msg in device_event_messages(session.device_events_expire(now), ble_control):
                        channel.send(*msg)
                if channel is not None:
                    message = channel.poll()
                    while message is not None:
                        for reply in handler.handle(*message):
                            channel.send(*reply)
                        message = channel.poll()
                line = dongle.readline()
                if line is None:
                    continue
                for event in session.handle_line(line, now):
                    if event[0] == "pcap":
                        fifo.write(event[1])
                    elif channel is not None:
                        for msg in device_event_messages([event], ble_control):
                            channel.send(*msg)
    except (BrokenPipeError, OSError, KeyboardInterrupt):
        pass        # Wireshark stopped the capture (pipe closed)
    except RuntimeError as exc:
        sys.stderr.write(f"{exc}\n")
        if channel is not None:
            channel.send(CTRL_DEVICE, ble_control.CMD_ERROR, str(exc))
    finally:
        if channel is not None:
            channel.stop()
        dongle.close()


def run_print_ble(args) -> None:
    """Console mode of the BLE sniffer: one line per packet and the device list."""
    _, _, ble_session = load_ble_modules()
    dongle = Dongle(args.port)
    session = ble_session.Session(parse_rssi(args.rssi_filter))
    try:
        configure_ble(dongle, args)
        print(f"# capturing BLE advertising, channels={args.adv_hop}, "
              f"rssi filter={args.rssi_filter} (Ctrl+C to stop)", flush=True)
        while True:
            line = dongle.readline()
            if line is None:
                continue
            events = session.handle_line(line)
            for event in events:
                if event[0] == "pcap":
                    print(f"{session.unwrapper.last / 1e6:12.6f}s {event[2]}", flush=True)
                elif event[0] == "add":
                    print(f"# device {event[2]}", flush=True)
                elif event[0] == "status":
                    print(f"# {event[1]}", flush=True)
            if not events and line.startswith(("I ", "E ")):
                print("#", line)
    except RuntimeError as exc:
        sys.stderr.write(f"{exc}\n")
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
    p.add_argument("--extcap-interface", "--interface",
                   help="interface: xn297l (default) or xn297l_ble")
    p.add_argument("--extcap-dlts", action="store_true")
    p.add_argument("--extcap-config", action="store_true")
    p.add_argument("--extcap-version")
    p.add_argument("--extcap-capture-filter")
    p.add_argument("--capture", action="store_true")
    p.add_argument("--fifo")
    p.add_argument("--extcap-control-in", help="extcap toolbar pipe (Wireshark -> extcap)")
    p.add_argument("--extcap-control-out", help="extcap toolbar pipe (extcap -> Wireshark)")

    # sniffer options (shown in Wireshark, usable on the command line)
    p.add_argument("--port", help="serial port of the dongle, e.g. COM5 or /dev/ttyACM0")
    p.add_argument("--mode", choices=["address", "promiscuous", "raw"], default="address")
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
    p.add_argument("--extra-bytes", type=int, default=0,
                   help="additional bytes captured after the frame (0..200)")
    p.add_argument("--sync", default="AAAAAA",
                   help="sync word for mode 'raw': 3..5 hex bytes, on-air order, MSB first")
    p.add_argument("--raw-length", type=int, default=64,
                   help="bytes captured after the sync word in mode 'raw' (1..250)")

    # options of the BLE interface (xn297l_ble)
    p.add_argument("--only-advertising", action="store_true",
                   help="BLE: capture advertising only, never follow a connection")
    p.add_argument("--adv-hop", default=DEFAULT_ADV_HOP,
                   help="BLE: advertising channels in hop order (37,38,39)")
    p.add_argument("--rssi-filter", default=str(RSSI_OFF),
                   help="BLE: hide advertising packets below this RSSI in dBm (-127 = off)")
    p.add_argument("--adv-dwell", type=int, default=BLE_DWELL_DEFAULT,
                   help="BLE: ms per advertising channel, 0 = stay on the first")

    # console mode
    p.add_argument("--print", action="store_true", help="print decoded frames to the console")
    p.add_argument("--show-bad", action="store_true", help="also print frames with bad CRC")
    p.add_argument("--list-ports", action="store_true", help="list serial ports and exit")
    return p


def main() -> int:
    # Wireshark reads the extcap output as UTF-8. On Windows, Python < 3.15 writes
    # piped output in the ANSI code page (e.g. cp1252), so a port description such
    # as "Serielles USB-Gerät (COM8)" would be invalid UTF-8 and the port list
    # would stay empty. Force UTF-8 for stdout/stderr.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    args = build_parser().parse_args()

    if args.extcap_interfaces:
        extcap_interfaces()
        return 0
    interface = args.extcap_interface or INTERFACE
    if args.extcap_dlts:
        extcap_dlts(interface)
        return 0
    if args.extcap_config:
        extcap_config(interface)
        return 0
    if args.list_ports:
        for device, description in list_serial_ports():
            print(f"{device:15s} {description}")
        if not pyserial_available():
            print(PYSERIAL_HINT.format(exe=sys.executable))
        return 0

    if args.capture or args.print:
        if not args.port:
            print("error: --port is required", file=sys.stderr)
            return 1
        if args.capture:
            if not args.fifo:
                print("error: --fifo is required for --capture", file=sys.stderr)
                return 1
            (run_capture_ble if interface == INTERFACE_BLE else run_capture)(args)
        else:
            (run_print_ble if interface == INTERFACE_BLE else run_print)(args)
        return 0

    build_parser().print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
