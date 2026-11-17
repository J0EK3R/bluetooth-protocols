#!/usr/bin/env python3
"""
Tests of ble_phdr.py: pcap output for LINKTYPE_BLUETOOTH_LE_LL_WITH_PHDR (256).

The expected bytes are written out by hand from the link type description
(https://www.tcpdump.org/linktypes/LINKTYPE_BLUETOOTH_LE_LL_WITH_PHDR.html).
"""

import os
import struct
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "extcap"))

import ble_phdr  # noqa: E402


class RfChannelTests(unittest.TestCase):
    def test_advertising_channels(self):
        self.assertEqual(ble_phdr.rf_channel(37), 0)      # 2402 MHz
        self.assertEqual(ble_phdr.rf_channel(38), 12)     # 2426 MHz
        self.assertEqual(ble_phdr.rf_channel(39), 39)     # 2480 MHz

    def test_data_channels(self):
        self.assertEqual(ble_phdr.rf_channel(0), 1)       # 2404 MHz
        self.assertEqual(ble_phdr.rf_channel(10), 11)     # 2424 MHz
        self.assertEqual(ble_phdr.rf_channel(11), 13)     # 2428 MHz
        self.assertEqual(ble_phdr.rf_channel(36), 38)     # 2478 MHz

    def test_mapping_is_a_bijection_onto_0_39(self):
        self.assertEqual(sorted(ble_phdr.rf_channel(i) for i in range(40)), list(range(40)))

    def test_frequency_formula(self):
        # frequency = 2402 + 2 * rf_channel; data channels skip the advertising frequencies
        adv = {2402, 2426, 2480}
        data = [2402 + 2 * ble_phdr.rf_channel(i) for i in range(37)]
        self.assertTrue(adv.isdisjoint(data))
        self.assertEqual(data, sorted(data))               # index order = frequency order

    def test_out_of_range(self):
        for bad in (-1, 40):
            with self.assertRaises(ValueError):
                ble_phdr.rf_channel(bad)


class PhdrTests(unittest.TestCase):
    def test_exact_bytes_advertising_crc_ok(self):
        # RF 0, -60 dBm = 0xC4, noise 0, offenses 0, AA D6 BE 89 8E,
        # flags 0x0C13 = dewhitened | signal valid | ref AA valid | CRC checked | CRC valid
        expected = bytes.fromhex("00 C4 00 00 D6BE898E 130C".replace(" ", ""))
        self.assertEqual(ble_phdr.build_phdr(37, -60, 0x8E89BED6, True), expected)

    def test_crc_bad_clears_valid_flag(self):
        phdr = ble_phdr.build_phdr(38, -70, 0x8E89BED6, False)
        flags = struct.unpack_from("<H", phdr, 8)[0]
        self.assertEqual(flags, 0x0413)                    # CRC checked but not valid
        self.assertEqual(phdr[0], 12)                      # channel 38 -> RF channel 12

    def test_length_is_10_and_little_endian_aa(self):
        phdr = ble_phdr.build_phdr(0, -1, 0x12345678, True)
        self.assertEqual(len(phdr), ble_phdr.PHDR_LEN)
        self.assertEqual(phdr[4:8], bytes([0x78, 0x56, 0x34, 0x12]))

    def test_rssi_is_clamped_to_int8(self):
        self.assertEqual(struct.unpack_from("<b", ble_phdr.build_phdr(37, -200, 1, True), 1)[0], -128)
        self.assertEqual(struct.unpack_from("<b", ble_phdr.build_phdr(37, 50, 1, True), 1)[0], 50)

    def test_phy_and_pdu_type_bits(self):
        flags = struct.unpack_from("<H", ble_phdr.build_phdr(
            5, -50, 1, True, phy=ble_phdr.PHY_2M, pdu_type=ble_phdr.PDU_DATA_S2M), 8)[0]
        self.assertEqual((flags >> 14) & 3, 1)             # LE 2M
        self.assertEqual((flags >> 7) & 7, 3)              # data, slave to master

    def test_decrypted_and_mic_flags(self):
        flags = struct.unpack_from("<H", ble_phdr.build_phdr(
            5, -50, 1, True, decrypted=True, mic_checked=True, mic_valid=True), 8)[0]
        self.assertTrue(flags & 0x0008)
        self.assertTrue(flags & 0x1000 and flags & 0x2000)


class PcapTests(unittest.TestCase):
    def test_global_header(self):
        hdr = ble_phdr.pcap_header_256()
        magic, major, minor, _, _, snaplen, linktype = struct.unpack("<IHHiIII", hdr)
        self.assertEqual((magic, major, minor, linktype), (0xA1B2C3D4, 2, 4, 256))
        self.assertGreaterEqual(snaplen, 300)

    def test_record_layout(self):
        record = ble_phdr.pcap_record(b"\x01\x02\x03", 1000.25)
        sec, usec, incl, orig = struct.unpack_from("<IIII", record)
        self.assertEqual((sec, usec, incl, orig), (1000, 250000, 3, 3))
        self.assertEqual(record[16:], b"\x01\x02\x03")

    def test_usec_rounding_does_not_overflow(self):
        sec, usec, _, _ = struct.unpack_from("<IIII", ble_phdr.pcap_record(b"x", 5.9999999))
        self.assertEqual((sec, usec), (6, 0))


if __name__ == "__main__":
    unittest.main()
