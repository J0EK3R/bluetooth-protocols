"""
Bluetooth LE advertising channel PDU parsing (Core Spec Vol 6 Part B 2.3).

Only what the sniffer host needs to build a device list is parsed: the PDU
type, the address of the device that is "speaking" and its name from the
advertising data. Input is the LL packet as sent by the dongle:

    access address (4) + header (2) + payload + CRC (3)
"""

# Advertising PDU types (header byte 0, bits 3..0)
ADV_IND = 0x0
ADV_DIRECT_IND = 0x1
ADV_NONCONN_IND = 0x2
SCAN_REQ = 0x3
SCAN_RSP = 0x4
CONNECT_IND = 0x5
ADV_SCAN_IND = 0x6
ADV_EXT_IND = 0x7          # also AUX_ADV_IND, AUX_SCAN_RSP, AUX_SYNC_IND, AUX_CHAIN_IND
AUX_CONNECT_RSP = 0x8

PDU_NAMES = {
    ADV_IND: "ADV_IND", ADV_DIRECT_IND: "ADV_DIRECT_IND", ADV_NONCONN_IND: "ADV_NONCONN_IND",
    SCAN_REQ: "SCAN_REQ", SCAN_RSP: "SCAN_RSP", CONNECT_IND: "CONNECT_IND",
    ADV_SCAN_IND: "ADV_SCAN_IND", ADV_EXT_IND: "ADV_EXT_IND", AUX_CONNECT_RSP: "AUX_CONNECT_RSP",
}

# Advertising data types carrying the device name
AD_SHORT_NAME = 0x08
AD_COMPLETE_NAME = 0x09

# PDU types sent by an advertiser (their first address is the advertiser address)
_ADVERTISER_TYPES = (ADV_IND, ADV_DIRECT_IND, ADV_NONCONN_IND, SCAN_RSP, ADV_SCAN_IND)
# PDU types that can be connected to / scanned (shown as "connectable" in the list)
_CONNECTABLE_TYPES = (ADV_IND, ADV_DIRECT_IND)

HEADER_LEN = 2
AA_LEN = 4
CRC_LEN = 3


class AdvPdu:
    """Parsed advertising channel PDU (fields are None if not present)."""

    def __init__(self):
        self.pdu_type = 0
        self.tx_add = 0              # address type bit of the first address (1 = random)
        self.rx_add = 0
        self.ch_sel = 0              # CSA #2 supported (ADV_*, CONNECT_IND)
        self.length = 0              # length field of the header
        self.adv_addr = None         # advertiser address, "AA:BB:CC:DD:EE:FF" (display order)
        self.target_addr = None      # ScanA / InitA / TargetA of directed PDUs
        self.name = None             # device name from the AD structures
        self.connectable = False
        self.payload = b""

    @property
    def type_name(self) -> str:
        return PDU_NAMES.get(self.pdu_type, f"TYPE_{self.pdu_type:X}")


def format_address(raw: bytes) -> str:
    """Format a 6 byte over-the-air address (LSB first) as AA:BB:CC:DD:EE:FF."""
    return ":".join(f"{b:02X}" for b in reversed(raw))


def parse_ad_name(ad: bytes):
    """Return the device name found in a sequence of AD structures, or None.

    The complete name (0x09) wins over the shortened name (0x08). Malformed
    structures end the search; invalid UTF-8 is replaced.
    """
    short = None
    pos = 0
    while pos < len(ad):
        length = ad[pos]
        if length == 0 or pos + 1 + length > len(ad):
            break                                    # padding or truncated structure
        ad_type = ad[pos + 1]
        value = ad[pos + 2:pos + 1 + length]
        if ad_type == AD_COMPLETE_NAME:
            return value.decode("utf-8", errors="replace")
        if ad_type == AD_SHORT_NAME and short is None:
            short = value.decode("utf-8", errors="replace")
        pos += 1 + length
    return short


def _parse_ext_adv_addr(payload: bytes):
    """AdvA of an ADV_EXT_IND (extended header flag bit 0), or None.

    Layout: byte 0 = ext header length (6 bits) + AdvMode (2 bits), then the
    extended header: flags byte, then AdvA (6 bytes) if flag bit 0 is set.
    """
    if len(payload) < 2:
        return None
    ext_len = payload[0] & 0x3F
    if ext_len < 7 or len(payload) < 1 + ext_len or not payload[1] & 0x01:
        return None
    return format_address(payload[2:8])


def parse_adv_packet(packet: bytes):
    """Parse an LL packet (AA + header + payload + CRC) on an advertising channel.

    Returns an AdvPdu, or None if the packet is too short or inconsistent
    (the length field does not match the packet size).
    """
    if len(packet) < AA_LEN + HEADER_LEN + CRC_LEN:
        return None
    pdu = packet[AA_LEN:-CRC_LEN]
    length = pdu[1]
    if len(pdu) != HEADER_LEN + length:
        return None
    pkt = AdvPdu()
    pkt.pdu_type = pdu[0] & 0x0F
    pkt.ch_sel = (pdu[0] >> 5) & 1
    pkt.tx_add = (pdu[0] >> 6) & 1
    pkt.rx_add = (pdu[0] >> 7) & 1
    pkt.length = length
    pkt.payload = pdu[HEADER_LEN:]
    payload = pkt.payload

    if pkt.pdu_type in _ADVERTISER_TYPES and len(payload) >= 6:
        pkt.adv_addr = format_address(payload[:6])
        if pkt.pdu_type == ADV_DIRECT_IND and len(payload) >= 12:
            pkt.target_addr = format_address(payload[6:12])
        elif pkt.pdu_type in (ADV_IND, ADV_NONCONN_IND, ADV_SCAN_IND, SCAN_RSP):
            pkt.name = parse_ad_name(payload[6:])
        pkt.connectable = pkt.pdu_type in _CONNECTABLE_TYPES
    elif pkt.pdu_type in (SCAN_REQ, CONNECT_IND) and len(payload) >= 12:
        # ScanA/InitA first, then AdvA: the "device" of such a PDU is the advertiser
        pkt.target_addr = format_address(payload[:6])
        pkt.adv_addr = format_address(payload[6:12])
    elif pkt.pdu_type == ADV_EXT_IND:
        pkt.adv_addr = _parse_ext_adv_addr(payload)
    return pkt


# ---------------------------------------------------------------------------
# Connection following: CONNECT_IND and data channel PDUs
# (Core Spec Vol 6 Part B 2.3.3.1, 2.4). The C twin is firmware/src/ble_pdu.c.
# ---------------------------------------------------------------------------

CONNECT_IND_LEN = 34                 # InitA (6) + AdvA (6) + LLData (22)
CHANNEL_MAP_LEN = 5                  # 37 channel bits, channel 0 = bit 0 of byte 0

# Data channel PDU header byte 0
LLID_RESERVED, LLID_CONT, LLID_START, LLID_CONTROL = 0, 1, 2, 3
DATA_MD = 0x10                       # More Data

LL_CONNECTION_UPDATE_IND = 0x00
LL_CHANNEL_MAP_IND = 0x01
LL_TERMINATE_IND = 0x02
LL_ENC_REQ = 0x03
LL_ENC_RSP = 0x04
LL_START_ENC_REQ = 0x05
LL_START_ENC_RSP = 0x06

LL_CONTROL_NAMES = {
    0x00: "LL_CONNECTION_UPDATE_IND", 0x01: "LL_CHANNEL_MAP_IND", 0x02: "LL_TERMINATE_IND",
    0x03: "LL_ENC_REQ", 0x04: "LL_ENC_RSP", 0x05: "LL_START_ENC_REQ", 0x06: "LL_START_ENC_RSP",
    0x07: "LL_UNKNOWN_RSP", 0x08: "LL_FEATURE_REQ", 0x09: "LL_FEATURE_RSP",
    0x0A: "LL_PAUSE_ENC_REQ", 0x0B: "LL_PAUSE_ENC_RSP", 0x0C: "LL_VERSION_IND",
    0x0D: "LL_REJECT_IND", 0x0E: "LL_SLAVE_FEATURE_REQ", 0x0F: "LL_CONNECTION_PARAM_REQ",
    0x10: "LL_CONNECTION_PARAM_RSP", 0x11: "LL_REJECT_EXT_IND", 0x12: "LL_PING_REQ",
    0x13: "LL_PING_RSP", 0x14: "LL_LENGTH_REQ", 0x15: "LL_LENGTH_RSP", 0x16: "LL_PHY_REQ",
    0x17: "LL_PHY_RSP", 0x18: "LL_PHY_UPDATE_IND", 0x19: "LL_MIN_USED_CHANNELS_IND",
}


def le16(data: bytes, pos: int) -> int:
    """Little endian 16 bit value at data[pos]."""
    return data[pos] | (data[pos + 1] << 8)


def parse_connect_ind(pdu: bytes):
    """Parse a CONNECT_IND PDU (header + payload, no access address / CRC).

    Returns a dict with the LLData fields in native integers (the channel map
    stays 5 bytes, reserved bits above channel 36 are cleared) or None if
    this is not a well formed CONNECT_IND.
    """
    if len(pdu) < 2 or pdu[0] & 0x0F != CONNECT_IND or pdu[1] != CONNECT_IND_LEN \
            or len(pdu) < 2 + CONNECT_IND_LEN:
        return None
    p = pdu[2:2 + CONNECT_IND_LEN]
    chmap = bytearray(p[28:33])
    chmap[4] &= 0x1F
    return {
        "tx_add": (pdu[0] >> 6) & 1, "rx_add": (pdu[0] >> 7) & 1, "ch_sel": (pdu[0] >> 5) & 1,
        "init_a": p[0:6], "adv_a": p[6:12],
        "access_address": int.from_bytes(p[12:16], "little"),
        "crc_init": int.from_bytes(p[16:19], "little"),
        "win_size": p[19], "win_offset": le16(p, 20), "interval": le16(p, 22),
        "latency": le16(p, 24), "timeout": le16(p, 26),
        "chmap": bytes(chmap), "hop": p[33] & 0x1F, "sca": p[33] >> 5,
    }


def parse_conn_update(payload: bytes):
    """LL_CONNECTION_UPDATE_IND (payload starts at the opcode) or None."""
    if len(payload) != 12 or payload[0] != LL_CONNECTION_UPDATE_IND:
        return None
    return {"win_size": payload[1], "win_offset": le16(payload, 2), "interval": le16(payload, 4),
            "latency": le16(payload, 6), "timeout": le16(payload, 8), "instant": le16(payload, 10)}


def parse_chmap_update(payload: bytes):
    """LL_CHANNEL_MAP_IND (payload starts at the opcode) or None."""
    if len(payload) != 8 or payload[0] != LL_CHANNEL_MAP_IND:
        return None
    chmap = bytearray(payload[1:6])
    chmap[4] &= 0x1F
    return {"chmap": bytes(chmap), "instant": le16(payload, 6)}


def describe_data_pdu(packet: bytes) -> str:
    """Short description of a data channel LL packet (AA + header + payload + CRC).

    Used for the console summary: "LL control LL_TERMINATE_IND", "LL data (start/complete)"...
    """
    if len(packet) < AA_LEN + HEADER_LEN + CRC_LEN:
        return "?"
    pdu = packet[AA_LEN:-CRC_LEN]
    llid, length = pdu[0] & 0x03, pdu[1]
    payload = pdu[HEADER_LEN:]
    md = " MD" if pdu[0] & DATA_MD else ""
    if llid == LLID_CONTROL and payload:
        return f"LL control {LL_CONTROL_NAMES.get(payload[0], f'opcode 0x{payload[0]:02X}')}{md}"
    if llid == LLID_CONTROL:
        return f"LL control{md}"
    if llid == LLID_CONT and length == 0:
        return f"LL empty PDU{md}"
    name = {LLID_CONT: "continuation", LLID_START: "start/complete"}.get(llid, "reserved")
    return f"LL data ({name}) {length} bytes{md}"
