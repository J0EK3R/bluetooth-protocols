"""
Pcap output for Bluetooth LE: LINKTYPE_BLUETOOTH_LE_LL_WITH_PHDR (DLT 256).

Every pcap record consists of a 10 byte pseudo header followed by the Link
Layer packet WITHOUT preamble (access address, PDU header, payload, CRC).
Wireshark's built-in BLE dissector decodes it directly.

The format is the public pcap link type description
(https://www.tcpdump.org/linktypes/LINKTYPE_BLUETOOTH_LE_LL_WITH_PHDR.html),
all multi byte fields are little endian:

    offset size  field
    0      1     RF channel 0..39 = (frequency - 2402 MHz) / 2   (NOT the BLE channel index)
    1      1     signal power in dBm (signed), valid with flag 0x0002
    2      1     noise power in dBm (signed), valid with flag 0x0004
    3      1     access address offenses, valid with flag 0x0020
    4      4     reference access address, valid with flag 0x0010
    8      2     flags
    10     ...   LE packet: access address (4) + PDU + CRC (3)
"""

import struct
import time

LINKTYPE_BLUETOOTH_LE_LL_WITH_PHDR = 256
PHDR_LEN = 10

# --- flag bits of the pseudo header (from the link type description) --------
FLAG_DEWHITENED = 0x0001            # the LE packet is de-whitened
FLAG_SIGNAL_POWER_VALID = 0x0002    # signal power field is valid
FLAG_NOISE_POWER_VALID = 0x0004     # noise power field is valid
FLAG_DECRYPTED = 0x0008             # the LE packet is decrypted
FLAG_REF_AA_VALID = 0x0010          # reference access address is valid
FLAG_AA_OFFENSES_VALID = 0x0020     # access address offenses field is valid
FLAG_CHANNEL_ALIASED = 0x0040       # RF channel is subject to aliasing
FLAG_CRC_CHECKED = 0x0400           # the CRC was checked
FLAG_CRC_VALID = 0x0800             # the CRC check passed
FLAG_MIC_CHECKED = 0x1000           # the MIC of a decrypted packet was checked
FLAG_MIC_VALID = 0x2000             # the MIC check passed
# bits 0x0380: PDU type, bits 0xC000: PHY
PDU_TYPE_SHIFT = 7
PDU_ADV_OR_DATA = 0                 # advertising or data channel, direction unspecified
PDU_AUX_ADV = 1                     # auxiliary advertising
PDU_DATA_M2S = 2                    # data, master to slave
PDU_DATA_S2M = 3                    # data, slave to master
PHY_SHIFT = 14
PHY_1M, PHY_2M, PHY_CODED = 0, 1, 2

ADV_ACCESS_ADDRESS = 0x8E89BED6     # access address of all advertising channel packets


def rf_channel(channel_index: int) -> int:
    """Map a BLE channel index (0..39) to the RF channel number (frequency index).

    Advertising channels: 37 -> 0 (2402 MHz), 38 -> 12 (2426 MHz), 39 -> 39 (2480 MHz).
    Data channels: 0..10 -> 1..11, 11..36 -> 13..38 (Core Spec Vol 6 Part B 1.4.1).
    """
    if not 0 <= channel_index <= 39:
        raise ValueError(f"BLE channel index {channel_index} out of range 0..39")
    if channel_index == 37:
        return 0
    if channel_index == 38:
        return 12
    if channel_index == 39:
        return 39
    return channel_index + 1 if channel_index <= 10 else channel_index + 2


def build_phdr(channel_index: int, rssi_dbm: int, access_address: int,
               crc_ok: bool, phy: int = PHY_1M, pdu_type: int = PDU_ADV_OR_DATA,
               decrypted: bool = False, mic_checked: bool = False,
               mic_valid: bool = False) -> bytes:
    """Build the 10 byte pseudo header for one captured packet.

    channel_index   BLE channel index 0..39
    rssi_dbm        signal power, clamped to the int8 range
    access_address  reference access address (advertising or connection AA)
    crc_ok          result of the hardware CRC check (the CRC is always "checked")
    """
    flags = (FLAG_DEWHITENED | FLAG_SIGNAL_POWER_VALID | FLAG_REF_AA_VALID | FLAG_CRC_CHECKED)
    if crc_ok:
        flags |= FLAG_CRC_VALID
    if decrypted:
        flags |= FLAG_DECRYPTED
        if mic_checked:
            flags |= FLAG_MIC_CHECKED
            if mic_valid:
                flags |= FLAG_MIC_VALID
    flags |= (pdu_type & 0x7) << PDU_TYPE_SHIFT
    flags |= (phy & 0x3) << PHY_SHIFT
    return struct.pack("<BbbBIH", rf_channel(channel_index),
                       max(-128, min(127, rssi_dbm)), 0, 0,
                       access_address & 0xFFFFFFFF, flags)


def pcap_header_256() -> bytes:
    """Classic pcap file header (microsecond timestamps) with link type 256."""
    return struct.pack("<IHHiIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535,
                       LINKTYPE_BLUETOOTH_LE_LL_WITH_PHDR)


def pcap_record(packet: bytes, timestamp: float = None) -> bytes:
    """One pcap record; the timestamp is in seconds since the epoch (default: now)."""
    if timestamp is None:
        timestamp = time.time()
    sec = int(timestamp)
    usec = int(round((timestamp - sec) * 1_000_000))
    if usec >= 1_000_000:               # rounding must not overflow the field
        sec, usec = sec + 1, usec - 1_000_000
    return struct.pack("<IIII", sec, usec, len(packet), len(packet)) + packet
