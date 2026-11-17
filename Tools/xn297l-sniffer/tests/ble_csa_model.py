"""
Python reference model of firmware/src/ble_csa.c (channel selection algorithms
#1 and #2, channel maps, channel index -> frequency).

Used as test oracle: tests/test_ble_csa.py checks it against the Core
Specification sample data and against the C implementation (host build).
Core Specification Vol 6 Part B 4.5.8.
"""

DATA_CHANNELS = 37


def map_to_bytes(channels) -> bytes:
    """Channel map bytes (37 bit, channel 0 = bit 0 of byte 0) from a list of used channels."""
    value = 0
    for ch in channels:
        value |= 1 << ch
    return value.to_bytes(5, "little")


def used_channels(chmap: bytes) -> list:
    """Used data channels in ascending order (the 'remapping table'); reserved bits ignored."""
    return [ch for ch in range(DATA_CHANNELS) if chmap[ch >> 3] >> (ch & 7) & 1]


def csa1_next(last_unmapped: int, hop: int, chmap: bytes):
    """Algorithm #1: returns (channel, new last_unmapped)."""
    unmapped = (last_unmapped + hop) % DATA_CHANNELS
    used = used_channels(chmap)
    if unmapped in used or not used:
        return unmapped, unmapped
    return used[unmapped % len(used)], unmapped


def csa2_channel_id(access_address: int) -> int:
    """Channel identifier: access address high half xor low half."""
    return ((access_address >> 16) ^ access_address) & 0xFFFF


def _perm(value: int) -> int:
    """Reverse the bit order inside each of the two bytes."""
    low = int(f"{value & 0xFF:08b}"[::-1], 2)
    high = int(f"{value >> 8 & 0xFF:08b}"[::-1], 2)
    return low | high << 8


def csa2_prn_e(channel_id: int, counter: int) -> int:
    """Pseudo random number prn_e of algorithm #2."""
    prn = (counter ^ channel_id) & 0xFFFF
    for _ in range(3):
        prn = (17 * _perm(prn) + channel_id) & 0xFFFF       # PERM, then MAM
    return prn ^ channel_id


def csa2_channel(channel_id: int, counter: int, chmap: bytes) -> int:
    """Algorithm #2: data channel of the event with the given (16 bit) counter."""
    prn_e = csa2_prn_e(channel_id, counter & 0xFFFF)
    unmapped = prn_e % DATA_CHANNELS
    used = used_channels(chmap)
    if unmapped in used or not used:
        return unmapped
    return used[(len(used) * prn_e) >> 16]


def channel_frequency(channel: int) -> int:
    """RADIO FREQUENCY value (MHz - 2400) of channel index 0..39."""
    if channel == 37:
        return 2
    if channel == 38:
        return 26
    if channel == 39:
        return 80
    return 4 + 2 * channel if channel <= 10 else 6 + 2 * channel
