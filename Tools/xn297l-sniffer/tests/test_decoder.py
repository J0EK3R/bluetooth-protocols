#!/usr/bin/env python3
"""
Unit tests for the XN297L decoder (Python extcap and Lua dissector core).

The reference frames are built with an INDEPENDENT encoder that follows the
BLE-domain description (LSB-first bytes, whitening LFSR as in BLE), i.e. a
different formulation than the decoder under test. Both must agree.

Run:   python tests/test_decoder.py
Lua tests run only if the 'lupa' package is installed (pip install lupa).
"""

import os
import random
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "extcap"))

import xn297l_sniffer as xs  # noqa: E402

LUA_FILE = os.path.join(HERE, "..", "wireshark", "xn297l.lua")


# ---------------------------------------------------------------------------
# Independent reference encoder (LSB-first / BLE domain)
# ---------------------------------------------------------------------------

def rev8(b):
    return int(f"{b:08b}"[::-1], 2)


def rev16(v):
    return int(f"{v:016b}"[::-1], 2)


def crc16_ccitt(data, crc=0xFFFF):
    """Plain CRC-16/CCITT-FALSE (no final XOR)."""
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


class Whitening:
    """7-bit whitening LFSR in the BLE formulation, ctx = [1, v5..v0]."""

    def __init__(self, v):
        self.ctx = [1] + [(v >> (5 - i)) & 1 for i in range(6)]

    def next(self):
        c = self.ctx
        t3, t6 = c[3], c[6]
        c[3], c[2], c[1], c[0] = c[2], c[1], c[0], c[6]
        c[6], c[5] = c[5], c[4]
        c[4] = t3 ^ t6
        return c[0]

    def encode(self, data):
        out = []
        for b in data:
            for bit in range(8):          # bit 0 -> bit 7 (LSB first on air)
                b ^= self.next() << bit
            out.append(b)
        return out


def reference_frame(tx_addr, payload, scramble=True):
    """Build an XN297L frame and return it as on-air bytes (MSB-first notation).

    The buffer is assembled in the LSB-first domain (as a BLE transmitter
    would send it) and converted with rev8() at the end.
    """
    addr_on_air = list(reversed(tx_addr))
    buf = [rev8(b) for b in [0x71, 0x0F, 0x55] + addr_on_air]   # preamble + address
    buf += list(payload)                                           # payload unchanged
    crc = crc16_ccitt(addr_on_air + [rev8(b) for b in payload])
    crc = rev16(crc) ^ 0xFFFF
    buf += [crc & 0xFF, crc >> 8]                                  # little endian
    if scramble:
        buf = buf[:3] + Whitening(0x3F).encode(buf[3:])
    return bytes(rev8(b) for b in buf)


# Sample payloads (arbitrary bytes, only the encoding matters here)
SAMPLES = [
    (bytes([0xC1, 0xC2, 0xC3, 0xC4, 0xC5]), bytes([0xAD, 0x12, 0x34, 0x80, 0x80, 0x80, 0x4F, 0x52])),
    (bytes([0xC1, 0xC2, 0xC3, 0xC4, 0xC5]), bytes([0x7D, 0x12, 0x34, 0x88, 0x88, 0x88, 0x88, 0x88, 0x88, 0x82])),
    (bytes([0x11, 0x22, 0x33]), bytes([0x01])),
    (bytes([0xA0, 0xB1, 0xC2, 0xD3]), bytes(range(32))),
]


# ---------------------------------------------------------------------------
# Python decoder tests
# ---------------------------------------------------------------------------

class PythonDecoderTests(unittest.TestCase):

    def test_scramble_table_start(self):
        self.assertEqual(xs.SCRAMBLE[:8], [0xE3, 0xB1, 0x4B, 0xEA, 0x85, 0xBC, 0xE5, 0x66])

    def test_reference_frame_starts_with_preamble(self):
        for addr, pl in SAMPLES:
            self.assertEqual(reference_frame(addr, pl)[:3], bytes([0x71, 0x0F, 0x55]))

    def test_address_to_on_air(self):
        on_air = xs.address_to_on_air(bytes.fromhex("C1C2C3C4C5"))
        self.assertEqual(on_air, bytes.fromhex("2675882844"))
        # must match the address bytes of a reference frame
        self.assertEqual(reference_frame(*SAMPLES[0])[3:8], on_air)

    def test_decode_known_length(self):
        for addr, pl in SAMPLES:
            frame = reference_frame(addr, pl)[3:]            # strip preamble
            res = xs.decode_frame(frame, len(addr), len(pl))
            self.assertTrue(res["crc_ok"])
            self.assertEqual(res["address_tx"], addr)
            self.assertEqual(res["payload"], pl)

    def test_decode_length_search_with_trailing_garbage(self):
        rnd = random.Random(1)
        for addr, pl in SAMPLES:
            frame = reference_frame(addr, pl)[3:]
            # promiscuous capture: fixed length, followed by noise
            frame += bytes(rnd.randrange(256) for _ in range(len(addr) + 34 - len(frame)))
            res = xs.decode_frame(frame, len(addr), 0)
            self.assertIsNotNone(res)
            self.assertEqual(res["payload"], pl)
            self.assertEqual(res["payload_len"], len(pl))

    def test_decode_unscrambled(self):
        addr, pl = SAMPLES[1]
        frame = reference_frame(addr, pl, scramble=False)[3:]
        res = xs.decode_frame(frame, len(addr), 0, scrambled=False)
        self.assertEqual(res["payload"], pl)

    def test_bad_crc_detected(self):
        addr, pl = SAMPLES[1]
        frame = bytearray(reference_frame(addr, pl)[3:])
        frame[7] ^= 0x01                                    # flip one payload bit
        res = xs.decode_frame(bytes(frame), len(addr), len(pl))
        self.assertFalse(res["crc_ok"])

    def test_firmware_line_both_modes(self):
        addr, pl = SAMPLES[1]
        full = reference_frame(addr, pl)
        # promiscuous: firmware prints sync (= preamble) + captured bytes
        line = f"P 123456 2 -60 {full.hex().upper()}"
        t_us, ch, rssi, data = xs.parse_packet_line(line)
        params = {"promiscuous": True}
        frame = xs.frame_bytes(data, params)
        self.assertEqual(xs.decode_frame(frame, 5, 0)["payload"], pl)
        # address mode: sync (= scrambled address) + payload + CRC
        params = {"promiscuous": False}
        frame = xs.frame_bytes(full[3:], params)
        self.assertEqual(xs.decode_frame(frame, 5, len(pl))["payload"], pl)
        self.assertEqual((t_us, ch, rssi), (123456, 2, -60))

    def test_pseudo_header(self):
        params = {"scrambled": True, "promiscuous": False, "addr_len": 5,
                  "payload_len": 10, "rate": 0}
        hdr = xs.pseudo_header(params, 2, -60, 0x12345678)
        self.assertEqual(len(hdr), xs.PSEUDO_HEADER_LEN)
        self.assertEqual(hdr.hex(), "010102c4050a000078563412")


# ---------------------------------------------------------------------------
# Lua core tests (same frames, same expectations)
# ---------------------------------------------------------------------------

try:
    import lupa  # noqa: F401
    HAVE_LUPA = True
except ImportError:
    HAVE_LUPA = False


@unittest.skipUnless(HAVE_LUPA, "lupa not installed")
class LuaDecoderTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from lupa import LuaRuntime
        cls.lua = LuaRuntime()
        with open(LUA_FILE, encoding="utf-8") as fh:
            cls.lua.execute(fh.read())       # no 'Proto' global -> test mode
        cls.core = cls.lua.globals().XN297L_CORE

    def to_lua(self, data):
        return self.lua.table_from(list(data))

    def test_lua_version(self):
        print("\n  Lua runtime:", self.lua.eval("_VERSION"), end=" ")

    def test_scramble_table_matches_python(self):
        t = self.core.SCRAMBLE
        self.assertEqual([t[i] for i in range(1, 257)], xs.SCRAMBLE[:256])

    def test_crc_matches_python(self):
        rnd = random.Random(2)
        for _ in range(50):
            data = [rnd.randrange(256) for _ in range(rnd.randrange(1, 40))]
            self.assertEqual(self.core.crc16(self.to_lua(data), 1, len(data)),
                             xs.crc16_genibus(data))

    def test_decode(self):
        rnd = random.Random(3)
        for addr, pl in SAMPLES:
            frame = reference_frame(addr, pl)[3:]
            frame += bytes(rnd.randrange(256) for _ in range(len(addr) + 34 - len(frame)))
            res = self.core.decode(self.to_lua(frame), len(addr), 0, True)
            self.assertIsNotNone(res)
            self.assertTrue(res.crc_ok)
            plen = res.payload_len
            self.assertEqual(plen, len(pl))
            payload = bytes(int(self.core.rev8(res.plain[len(addr) + i + 1])) for i in range(plen))
            self.assertEqual(payload, pl)

    def test_integer_results(self):
        # Lua 5.4: results must stay integers (string.format("%02X") needs them)
        v = self.core.bxor(0xFFFF, 0x1234)
        self.assertEqual(v, 0xFFFF ^ 0x1234)
        self.assertIsInstance(v, int)


if __name__ == "__main__":
    unittest.main(verbosity=2)
