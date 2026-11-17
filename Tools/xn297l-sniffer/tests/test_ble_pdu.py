#!/usr/bin/env python3
"""Tests of ble_pdu.py: advertising PDU parsing with hand-built packets."""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "extcap"))

import ble_pdu  # noqa: E402

AA = bytes.fromhex("D6BE898E")          # advertising access address on air
CRC = bytes.fromhex("ABCDEF")           # content irrelevant for the parser
ADDR_A = bytes.fromhex("665544332211")  # 11:22:33:44:55:66 on air (LSB first)
ADDR_B = bytes.fromhex("BBAA99887766")  # 66:77:88:99:AA:BB


def adv_packet(header0: int, payload: bytes) -> bytes:
    """Assemble AA + header + payload + CRC."""
    return AA + bytes([header0, len(payload)]) + payload + CRC


class AdvParsingTests(unittest.TestCase):
    def test_adv_ind_with_name(self):
        ad = bytes([2, 0x01, 0x06]) + bytes([5, 0x09]) + b"Test"
        pdu = ble_pdu.parse_adv_packet(adv_packet(0x40, ADDR_A + ad))   # ADV_IND, TxAdd = random
        self.assertEqual(pdu.pdu_type, ble_pdu.ADV_IND)
        self.assertEqual(pdu.type_name, "ADV_IND")
        self.assertEqual(pdu.adv_addr, "11:22:33:44:55:66")
        self.assertEqual(pdu.tx_add, 1)
        self.assertEqual(pdu.name, "Test")
        self.assertTrue(pdu.connectable)

    def test_short_name_used_if_no_complete_name(self):
        ad = bytes([4, 0x08]) + b"abc"
        pdu = ble_pdu.parse_adv_packet(adv_packet(0x02, ADDR_A + ad))   # ADV_NONCONN_IND
        self.assertEqual(pdu.name, "abc")
        self.assertFalse(pdu.connectable)

    def test_complete_name_wins_over_short_name(self):
        ad = bytes([3, 0x08]) + b"ab" + bytes([6, 0x09]) + b"abcde"
        self.assertEqual(ble_pdu.parse_ad_name(ad), "abcde")

    def test_malformed_ad_structure_is_ignored(self):
        self.assertIsNone(ble_pdu.parse_ad_name(bytes([9, 0x09, 0x41])))     # length beyond data
        self.assertIsNone(ble_pdu.parse_ad_name(bytes([0, 0, 0])))           # padding
        self.assertEqual(ble_pdu.parse_ad_name(bytes([2, 0x09, 0xFF])), "�")  # bad UTF-8

    def test_scan_rsp_name(self):
        pdu = ble_pdu.parse_adv_packet(adv_packet(0x04, ADDR_A + bytes([3, 0x09]) + b"Hi"))
        self.assertEqual(pdu.type_name, "SCAN_RSP")
        self.assertEqual(pdu.name, "Hi")

    def test_adv_direct_ind_has_target(self):
        pdu = ble_pdu.parse_adv_packet(adv_packet(0x01, ADDR_A + ADDR_B))
        self.assertEqual(pdu.adv_addr, "11:22:33:44:55:66")
        self.assertEqual(pdu.target_addr, "66:77:88:99:AA:BB")
        self.assertTrue(pdu.connectable)

    def test_scan_req_and_connect_ind_name_the_advertiser(self):
        # SCAN_REQ payload: ScanA (initiator) then AdvA
        pdu = ble_pdu.parse_adv_packet(adv_packet(0xC3, ADDR_B + ADDR_A))
        self.assertEqual(pdu.type_name, "SCAN_REQ")
        self.assertEqual(pdu.adv_addr, "11:22:33:44:55:66")
        self.assertEqual(pdu.target_addr, "66:77:88:99:AA:BB")
        self.assertEqual((pdu.tx_add, pdu.rx_add), (1, 1))
        # CONNECT_IND: InitA, AdvA, then 22 bytes LLData; ChSel bit 5 of the header
        llData = bytes(22)
        pdu = ble_pdu.parse_adv_packet(adv_packet(0x25, ADDR_B + ADDR_A + llData))
        self.assertEqual(pdu.type_name, "CONNECT_IND")
        self.assertEqual(pdu.ch_sel, 1)
        self.assertEqual(pdu.adv_addr, "11:22:33:44:55:66")

    def test_adv_ext_ind_with_adv_a(self):
        # ext header length 7 (flags + AdvA), AdvMode 00; flags bit 0 = AdvA present
        payload = bytes([7, 0x01]) + ADDR_A
        pdu = ble_pdu.parse_adv_packet(adv_packet(0x07, payload))
        self.assertEqual(pdu.type_name, "ADV_EXT_IND")
        self.assertEqual(pdu.adv_addr, "11:22:33:44:55:66")

    def test_adv_ext_ind_without_adv_a(self):
        pdu = ble_pdu.parse_adv_packet(adv_packet(0x07, bytes([1, 0x00])))
        self.assertIsNone(pdu.adv_addr)

    def test_inconsistent_length_is_rejected(self):
        packet = bytearray(adv_packet(0x00, ADDR_A))
        packet[5] = 20                                   # length field larger than the packet
        self.assertIsNone(ble_pdu.parse_adv_packet(bytes(packet)))
        self.assertIsNone(ble_pdu.parse_adv_packet(b"\x00" * 5))

    def test_unknown_type_name(self):
        pdu = ble_pdu.parse_adv_packet(adv_packet(0x0F, bytes(6)))
        self.assertEqual(pdu.type_name, "TYPE_F")


if __name__ == "__main__":
    unittest.main()
