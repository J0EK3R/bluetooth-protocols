"""
Host side processing of the BLE sniffer stream.

The firmware (mode "ble") sends text lines:

    B <t_us> <ch> <rssi> <phy> <flags> <evt> <hex>     one captured packet
    I drop n=<count>                                   packets lost in the dongle
    I conn new|upd|lost ...                            state of the followed connection
    P ...                                              XN297L lines, ignored here

This module turns them into pcap records (DLT 256, see ble_phdr.py) and keeps
the state a Wireshark user sees in the toolbar: a table of the advertising
devices seen recently (for the "Device" selector) and status messages. It has
no I/O of its own, so it is fully unit testable.
"""

import time

import ble_pdu
import ble_phdr

# Report flag bits sent by the firmware (see firmware/src/ble_radio.h)
FLAG_CRC_OK = 0x01
FLAG_DIR_S2M = 0x02
FLAG_DATA = 0x04
FLAG_AUX = 0x08
FLAG_TRUNC = 0x10
FLAG_ANCHOR = 0x20             # first packet of a connection event
FLAG_GAP = 0x40                # a packet of the event was probably missed

DEVICE_LIST_MAX = 50           # most recently seen devices offered in the toolbar
DEVICE_STALE_S = 30.0          # devices not seen for this long are removed
NO_RSSI_FILTER = -127          # RSSI threshold meaning "off"

# Why a followed connection ended (value of "reason=" in 'I conn lost')
LOST_TEXT = {
    "timeout": "Connection lost: supervision timeout (the sniffer lost the connection or the link broke)",
    "terminate": "Connection terminated (LL_TERMINATE_IND); scanning for the device again",
    "establish": "Connection not established: no packet seen after the CONNECT_IND; "
                 "scanning for the device again",
}

ALL_DEVICES_VALUE = "all"      # selector value of the "no device selected" entry
ALL_DEVICES_DISPLAY = "All advertising devices"


class BlePacket:
    """One 'B' line of the firmware."""

    def __init__(self, t_us, channel, rssi, phy, flags, evt, data):
        self.t_us = t_us            # device time of the packet start, u32, wraps
        self.channel = channel      # BLE channel index 0..39
        self.rssi = rssi            # dBm
        self.phy = phy              # 1 = 1M, 2 = 2M, 3/4 = coded
        self.flags = flags
        self.evt = evt              # connection event counter
        self.data = data            # access address + header + payload + CRC

    @property
    def crc_ok(self) -> bool:
        return bool(self.flags & FLAG_CRC_OK)


def parse_ble_line(line: str):
    """Parse a 'B <t_us> <ch> <rssi> <phy> <flags> <evt> <hex>' line.

    Returns a BlePacket, or None if the line is not a well formed B line
    (the host must tolerate garbage and unknown lines).
    """
    parts = line.split()
    if len(parts) != 8 or parts[0] != "B":
        return None
    try:
        t_us, channel, rssi, phy = int(parts[1]), int(parts[2]), int(parts[3]), int(parts[4])
        flags, evt, data = int(parts[5], 16), int(parts[6]), bytes.fromhex(parts[7])
    except ValueError:
        return None
    if not 0 <= channel <= 39 or len(data) < ble_pdu.AA_LEN + ble_pdu.HEADER_LEN + ble_pdu.CRC_LEN:
        return None
    return BlePacket(t_us, channel, rssi, phy, flags, evt, data)


def parse_info_line(line: str):
    """Parse an 'I key=value ...' line into a dict (tokens without '=' are ignored)."""
    if not line.startswith("I "):
        return None
    info = {}
    for token in line[2:].split():
        key, sep, value = token.partition("=")
        if sep:
            info[key] = value
    return info


def parse_conn_line(line: str):
    """Parse an 'I conn new|upd|lost key=value ...' line into (kind, dict), or None.

    Numbers stay strings; use conn_int() for the decimal and conn_hex() for the
    hexadecimal fields. Unknown or malformed lines give None (they are ignored).
    """
    tokens = line.split()
    if len(tokens) < 3 or tokens[0] != "I" or tokens[1] != "conn" \
            or tokens[2] not in ("new", "upd", "lost"):
        return None
    fields = {}
    for token in tokens[3:]:
        key, sep, value = token.partition("=")
        if sep:
            fields[key] = value
    return tokens[2], fields


def conn_int(fields: dict, key: str, default=0) -> int:
    """Decimal field of a connection line (default if missing or malformed)."""
    try:
        return int(fields.get(key, default))
    except ValueError:
        return default


def conn_status_text(kind: str, fields: dict) -> str:
    """Human readable text of a connection state line for the status bar."""
    if kind == "lost":
        return LOST_TEXT.get(fields.get("reason", ""), "Connection ended")
    interval_ms = conn_int(fields, "int") * 1.25
    try:
        channels = bin(int(fields.get("map", "0"), 16)).count("1")
    except ValueError:
        channels = 0
    details = (f"interval {interval_ms:g} ms, latency {conn_int(fields, 'lat')}, "
               f"supervision timeout {conn_int(fields, 'to') * 10} ms, {channels} channels")
    if kind == "new":
        return (f"Following connection {fields.get('aa', '?')} "
                f"(channel selection #{conn_int(fields, 'chsel', 1)}), {details}")
    return f"Connection updated: {details}"


class TimeUnwrapper:
    """Convert the wrapping 32 bit microsecond device time into a growing counter.

    The device clock wraps every 2^32 us (about 71.6 minutes). As long as
    consecutive timestamps are less than half a period apart the unwrapped
    value is monotonic; a small step backwards (packets are reported in
    capture order, but a retried packet may be older) does not count as wrap.
    """

    def __init__(self):
        self.last = None            # last unwrapped value
        self.base = 0               # offset added for the wraps seen so far

    def unwrap(self, t_us: int) -> int:
        if self.last is None:
            self.last = t_us
            return t_us
        # signed 32 bit difference to the previous raw value
        raw_last = self.last & 0xFFFFFFFF
        delta = ((t_us - raw_last + 0x80000000) & 0xFFFFFFFF) - 0x80000000
        self.last += delta
        return self.last


class Device:
    """One advertising device in the device table."""

    def __init__(self, addr, tx_add, name, rssi, now):
        self.addr = addr
        self.tx_add = tx_add        # 0 public, 1 random
        self.name = name
        self.rssi = rssi            # RSSI when it was last announced to the toolbar
        self.last_seen = now
        self.announced = False      # ADD sent to the toolbar

    @property
    def value(self) -> str:
        """Selector value: address and address type, e.g. 'C0:FF:EE:00:11:22,1'."""
        return f"{self.addr},{self.tx_add}"

    @property
    def display(self) -> str:
        """Text shown in the toolbar selector."""
        name = f' "{self.name}"' if self.name else ""
        return f"{self.addr}{name} {self.rssi} dBm"


class DeviceTable:
    """Advertising devices seen recently, bounded and with stale entry removal."""

    def __init__(self, limit=DEVICE_LIST_MAX, stale_s=DEVICE_STALE_S):
        self.limit = limit
        self.stale_s = stale_s
        self.devices = {}           # value -> Device

    def update(self, pdu, rssi, now) -> list:
        """Register one parsed advertising PDU; returns toolbar events.

        Events are ('add', value, display) and ('remove', value). A device is
        announced when first seen and re-announced once when its name becomes
        known; the RSSI shown is the one at that moment.
        """
        if pdu.adv_addr is None:
            return []
        events = []
        key = f"{pdu.adv_addr},{pdu.tx_add}"
        dev = self.devices.get(key)
        if dev is None:
            dev = Device(pdu.adv_addr, pdu.tx_add, pdu.name, rssi, now)
            self.devices[key] = dev
        dev.last_seen = now
        # Re-announce when the name appears: the old entry must be removed first
        if pdu.name and not dev.name:
            if dev.announced:
                events.append(("remove", dev.value))
                dev.announced = False
            dev.name = pdu.name
            dev.rssi = rssi
        if not dev.announced:
            events.append(("add", dev.value, dev.display))
            dev.announced = True
        events.extend(self._enforce_limit())
        return events

    def _enforce_limit(self) -> list:
        """Remove the least recently seen devices above the limit."""
        events = []
        while len(self.devices) > self.limit:
            oldest = min(self.devices.values(), key=lambda d: d.last_seen)
            del self.devices[oldest.value]
            events.append(("remove", oldest.value))
        return events

    def expire(self, now) -> list:
        """Remove devices not seen for stale_s seconds; returns ('remove', value) events."""
        events = []
        for dev in list(self.devices.values()):
            if now - dev.last_seen > self.stale_s:
                del self.devices[dev.value]
                events.append(("remove", dev.value))
        return events


class Session:
    """State of one BLE capture: time base, device table, RSSI filter, statistics."""

    def __init__(self, rssi_min=NO_RSSI_FILTER, host_start=None):
        self.rssi_min = rssi_min
        self.devices = DeviceTable()
        self.unwrapper = TimeUnwrapper()
        self.host_start = time.time() if host_start is None else host_start
        self.first_t_us = None
        self.packets = 0
        self.dropped = 0            # packets the dongle reported as lost
        self.connections = 0        # connections followed so far
        self.connected = False      # a connection is followed right now

    def timestamp(self, t_us: int) -> float:
        """Pcap timestamp: host start time plus the device time elapsed since the first packet."""
        unwrapped = self.unwrapper.unwrap(t_us)
        if self.first_t_us is None:
            self.first_t_us = unwrapped
        return self.host_start + (unwrapped - self.first_t_us) / 1e6

    def handle_line(self, line: str, now=None) -> list:
        """Process one line of the dongle; returns a list of events.

        ('pcap', record_bytes, summary_text)  a packet for the capture file
        ('add', value, display)               device appeared (toolbar)
        ('remove', value)                     device disappeared (toolbar)
        ('status', text)                      status bar message
        ('conn', kind, fields)                connection state: 'new', 'upd' or 'lost'
        """
        now = time.time() if now is None else now
        if line.startswith("B "):
            pkt = parse_ble_line(line)
            return self._handle_packet(pkt, now) if pkt else []
        if line.startswith("I drop"):
            info = parse_info_line(line) or {}
            try:
                count = int(info.get("n", "0"))
            except ValueError:
                return []
            self.dropped += count
            return [("status", f"Dongle dropped {count} packets (USB too slow), "
                               f"{self.dropped} in total")]
        conn = parse_conn_line(line)
        if conn is not None:
            return self._handle_connection(*conn)
        return []                    # P lines, other I lines, garbage: ignored

    def _handle_connection(self, kind: str, fields: dict) -> list:
        """A connection state line: keep the state, tell the user."""
        if kind == "new":
            self.connections += 1
            self.connected = True
        elif kind == "lost":
            self.connected = False
        return [("conn", kind, fields), ("status", conn_status_text(kind, fields))]

    def _handle_packet(self, pkt: BlePacket, now) -> list:
        """Apply the RSSI filter, update the device table and build the pcap record."""
        # the RSSI threshold applies to advertising packets only (never to connections)
        if not pkt.flags & FLAG_DATA and pkt.rssi < self.rssi_min:
            return []
        self.packets += 1
        aa = int.from_bytes(pkt.data[:4], "little")
        events = []
        pdu = None
        pdu_type = ble_phdr.PDU_ADV_OR_DATA
        if pkt.flags & FLAG_DATA:
            # connection packet: Wireshark needs the direction (master -> slave or back)
            pdu_type = ble_phdr.PDU_DATA_S2M if pkt.flags & FLAG_DIR_S2M else ble_phdr.PDU_DATA_M2S
        elif aa == ble_phdr.ADV_ACCESS_ADDRESS:
            pdu = ble_pdu.parse_adv_packet(pkt.data)
            if pdu is not None and pkt.crc_ok:
                events.extend(self.devices.update(pdu, pkt.rssi, now))
            if pkt.flags & FLAG_AUX:
                pdu_type = ble_phdr.PDU_AUX_ADV
        phy = {2: ble_phdr.PHY_2M, 3: ble_phdr.PHY_CODED, 4: ble_phdr.PHY_CODED}.get(
            pkt.phy, ble_phdr.PHY_1M)
        phdr = ble_phdr.build_phdr(pkt.channel, pkt.rssi, aa, pkt.crc_ok, phy, pdu_type)
        record = ble_phdr.pcap_record(phdr + pkt.data, self.timestamp(pkt.t_us))
        events.insert(0, ("pcap", record, self.summary(pkt, pdu)))
        return events

    @staticmethod
    def summary(pkt: BlePacket, pdu) -> str:
        """One line description for the console mode."""
        crc = "CRC ok " if pkt.crc_ok else "CRC BAD"
        what = "?"
        if pkt.flags & FLAG_DATA:
            direction = "S->M" if pkt.flags & FLAG_DIR_S2M else "M->S"
            anchor = " (anchor)" if pkt.flags & FLAG_ANCHOR else ""
            gap = " [gap: packet missed?]" if pkt.flags & FLAG_GAP else ""
            what = f"{direction} event {pkt.evt}{anchor}{gap} {ble_pdu.describe_data_pdu(pkt.data)}"
        elif pdu is not None:
            what = pdu.type_name
            if pdu.adv_addr:
                what += f" {pdu.adv_addr}"
            if pdu.name:
                what += f' "{pdu.name}"'
        return f"ch {pkt.channel:2d} {pkt.rssi:4d} dBm {crc} len {len(pkt.data) - 9:3d}  {what}"

    def device_events_expire(self, now=None) -> list:
        """Periodic housekeeping: stale device removals (call about once a second)."""
        return self.devices.expire(time.time() if now is None else now)
