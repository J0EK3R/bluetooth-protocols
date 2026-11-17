#!/usr/bin/env python3
"""
Host side of connection following (milestone M2), without hardware:
  - 'I conn ...' status lines and data channel packets in ble_session (pcap direction flags)
  - CONNECT_IND / LL control / data PDU parsing of ble_pdu
  - the device selection (toolbar and command line) and the 'bfollow' firmware command
"""

import os
import struct
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "extcap"))

import ble_control  # noqa: E402
import ble_pdu  # noqa: E402
import ble_phdr  # noqa: E402
import ble_session  # noqa: E402
import xn297l_sniffer as xs  # noqa: E402
from test_ble_session import RecordingDongle, b_line, ble_args  # noqa: E402

CONN_AA = bytes.fromhex("215A6550")           # access address 0x50655A21 on air


def data_packet_hex(header0: int, payload: bytes = b"", crc="ABCDEF") -> str:
    """Hex of a data channel LL packet as the firmware reports it."""
    return (CONN_AA + bytes([header0, len(payload)]) + payload).hex().upper() + crc


def connect_ind_pdu(ch_sel=1) -> bytes:
    ll_data = (bytes.fromhex("215A6550") + bytes.fromhex("563412") + bytes([2])
               + (2).to_bytes(2, "little") + (24).to_bytes(2, "little") + (0).to_bytes(2, "little")
               + (200).to_bytes(2, "little") + bytes.fromhex("FFFFFFFFFF") + bytes([7 | 5 << 5]))
    payload = bytes.fromhex("A1A2A3A4A5A6") + bytes.fromhex("665544332211") + ll_data
    return bytes([0x05 | ch_sel << 5, len(payload)]) + payload


class PduParsingTests(unittest.TestCase):
    def test_connect_ind(self):
        ci = ble_pdu.parse_connect_ind(connect_ind_pdu())
        self.assertEqual(ci["access_address"], 0x50655A21)
        self.assertEqual(ci["crc_init"], 0x123456)
        self.assertEqual((ci["win_size"], ci["win_offset"], ci["interval"], ci["latency"],
                          ci["timeout"]), (2, 2, 24, 0, 200))
        self.assertEqual((ci["hop"], ci["sca"], ci["ch_sel"]), (7, 5, 1))
        self.assertEqual(ci["chmap"], bytes.fromhex("FFFFFFFF1F"))   # reserved bits cleared
        self.assertEqual(ble_pdu.format_address(ci["adv_a"]), "11:22:33:44:55:66")

    def test_connect_ind_malformed(self):
        pdu = connect_ind_pdu()
        self.assertIsNone(ble_pdu.parse_connect_ind(pdu[:-1]))
        self.assertIsNone(ble_pdu.parse_connect_ind(b"\x00" + pdu[1:]))       # not a CONNECT_IND
        self.assertIsNone(ble_pdu.parse_connect_ind(b""))

    def test_conn_update_and_chmap_update(self):
        upd = ble_pdu.parse_conn_update(bytes([0, 1]) + (3).to_bytes(2, "little")
                                        + (40).to_bytes(2, "little") + (1).to_bytes(2, "little")
                                        + (300).to_bytes(2, "little") + (500).to_bytes(2, "little"))
        self.assertEqual(upd, {"win_size": 1, "win_offset": 3, "interval": 40, "latency": 1,
                               "timeout": 300, "instant": 500})
        cmu = ble_pdu.parse_chmap_update(bytes([1]) + bytes.fromhex("FF00FF00FF") + (9).to_bytes(2, "little"))
        self.assertEqual(cmu, {"chmap": bytes.fromhex("FF00FF001F"),
                               "instant": 9})
        self.assertIsNone(ble_pdu.parse_conn_update(b"\x00\x01"))
        self.assertIsNone(ble_pdu.parse_chmap_update(b"\x01"))

    def test_describe_data_pdu(self):
        d = lambda h, p=b"": ble_pdu.describe_data_pdu(bytes.fromhex(data_packet_hex(h, p)))
        self.assertEqual(d(0x01), "LL empty PDU")
        self.assertEqual(d(0x11), "LL empty PDU MD")
        self.assertEqual(d(0x02, b"abc"), "LL data (start/complete) 3 bytes")
        self.assertEqual(d(0x03, bytes([0x02, 0x13])), "LL control LL_TERMINATE_IND")
        self.assertEqual(d(0x03, bytes([0x77])), "LL control opcode 0x77")


class ConnectionLineTests(unittest.TestCase):
    NEW = ("I conn new aa=50655A21 crcinit=123456 int=24 lat=0 to=200 map=FFFFFFFF1F hop=7 "
           "chsel=2 sca=5 t=1000")

    def test_parse(self):
        kind, fields = ble_session.parse_conn_line(self.NEW)
        self.assertEqual(kind, "new")
        self.assertEqual(fields["aa"], "50655A21")
        self.assertEqual(ble_session.conn_int(fields, "int"), 24)
        self.assertIsNone(ble_session.parse_conn_line("I conn bogus x=1"))
        self.assertIsNone(ble_session.parse_conn_line("I drop n=3"))
        self.assertIsNone(ble_session.parse_conn_line("I conn"))

    def test_new_connection_status(self):
        s = ble_session.Session(host_start=0.0)
        events = s.handle_line(self.NEW)
        self.assertEqual(events[0][:2], ("conn", "new"))
        text = events[1][1]
        for part in ("50655A21", "channel selection #2", "interval 30 ms", "latency 0",
                     "timeout 2000 ms", "37 channels"):
            self.assertIn(part, text)
        self.assertTrue(s.connected)
        self.assertEqual(s.connections, 1)

    def test_update_and_lost(self):
        s = ble_session.Session(host_start=0.0)
        s.handle_line(self.NEW)
        upd = s.handle_line("I conn upd evt=6 int=40 lat=1 to=300 map=0F00000000 t=5")
        self.assertIn("interval 50 ms", upd[1][1])
        self.assertIn("4 channels", upd[1][1])
        for reason, word in (("timeout", "supervision timeout"), ("terminate", "terminated"),
                             ("establish", "not established")):
            lost = s.handle_line(f"I conn lost reason={reason} evt=9 t=7")
            self.assertIn(word, lost[1][1])
            self.assertFalse(s.connected)

    def test_malformed_values_do_not_raise(self):
        s = ble_session.Session(host_start=0.0)
        events = s.handle_line("I conn new aa=? int=x lat=y map=zz")
        self.assertEqual(events[0][:2], ("conn", "new"))


class DataPacketTests(unittest.TestCase):
    def packet(self, flags, header0=0x01, payload=b"", rssi=-70, evt=4, ch=12):
        s = ble_session.Session(host_start=100.0)
        line = b_line(5000, ch, rssi, flags, data_packet_hex(header0, payload), evt=evt)
        return s, s.handle_line(line, now=1.0)

    def phdr_of(self, event):
        record = event[1]
        return record[16:16 + ble_phdr.PHDR_LEN], record[16 + ble_phdr.PHDR_LEN:]

    def test_master_to_slave_packet(self):
        _, events = self.packet(0x05)                   # CRC ok + data
        phdr, packet = self.phdr_of(events[0])
        rf, signal, _noise, _off, ref_aa, flags = struct.unpack("<BbbBIH", phdr)
        self.assertEqual((rf, signal, ref_aa), (ble_phdr.rf_channel(12), -70, 0x50655A21))
        self.assertEqual((flags >> ble_phdr.PDU_TYPE_SHIFT) & 7, ble_phdr.PDU_DATA_M2S)
        self.assertTrue(flags & ble_phdr.FLAG_CRC_VALID)
        self.assertEqual(packet.hex().upper(), data_packet_hex(0x01))

    def test_slave_to_master_packet(self):
        _, events = self.packet(0x07)                   # CRC ok + slave -> master + data
        _, _, _, _, _, flags = struct.unpack("<BbbBIH", self.phdr_of(events[0])[0])
        self.assertEqual((flags >> ble_phdr.PDU_TYPE_SHIFT) & 7, ble_phdr.PDU_DATA_S2M)

    def test_bad_crc_flag(self):
        _, events = self.packet(0x04)
        _, _, _, _, _, flags = struct.unpack("<BbbBIH", self.phdr_of(events[0])[0])
        self.assertFalse(flags & ble_phdr.FLAG_CRC_VALID)
        self.assertTrue(flags & ble_phdr.FLAG_CRC_CHECKED)

    def test_rssi_filter_applies_to_advertising_only(self):
        s = ble_session.Session(rssi_min=-60, host_start=0.0)
        self.assertEqual(s.handle_line(b_line(1, 12, -90, 0x05, data_packet_hex(1)))[0][0], "pcap")
        from test_ble_session import ADV_IND_TEST
        self.assertEqual(s.handle_line(b_line(2, 37, -90, 0x01, ADV_IND_TEST)), [])

    def test_summary_describes_direction_and_pdu(self):
        _, events = self.packet(0x27, header0=0x03, payload=bytes([0x02, 0x13]))  # anchor + S->M
        text = events[0][2]
        for part in ("S->M", "event 4", "(anchor)", "LL_TERMINATE_IND", "CRC ok"):
            self.assertIn(part, text)
        _, events = self.packet(0x45)                   # gap flag, master
        self.assertIn("M->S", events[0][2])
        self.assertIn("gap", events[0][2])

    def test_device_table_not_updated_by_data_packets(self):
        s, _ = self.packet(0x05)
        self.assertEqual(s.devices.devices, {})


class FollowSelectionTests(unittest.TestCase):
    def test_parse_follow(self):
        self.assertEqual(xs.parse_follow("11:22:33:44:55:66"), "112233445566")
        self.assertEqual(xs.parse_follow("aa:bb:cc:dd:ee:ff,1"), "AABBCCDDEEFF,1")
        self.assertEqual(xs.parse_follow("aabbccddeeff, 0"), "AABBCCDDEEFF,0")
        for off in ("", "all", "off", "  "):
            self.assertEqual(xs.parse_follow(off), "off")
        for bad in ("11:22:33:44:55", "11:22:33:44:55:66:77", "GG:22:33:44:55:66",
                    "11:22:33:44:55:66,2", "11:22:33:44:55:66,x", "١١:22:33:44:55:66"):
            with self.assertRaises(ValueError, msg=bad):
                xs.parse_follow(bad)

    def test_command_line_follow_is_configured_before_start(self):
        dongle = RecordingDongle()
        params = xs.configure_ble(dongle, ble_args("--follow", "11:22:33:44:55:66,1",
                                                   "--scan-follow-rsp"))
        self.assertEqual(dongle.commands[-3:], ["brsp on", "bfollow 112233445566,1", "start"])
        self.assertEqual(params["follow"], "112233445566,1")

    def test_invalid_follow_sends_nothing(self):
        dongle = RecordingDongle()
        with self.assertRaises(ValueError):
            xs.configure_ble(dongle, ble_args("--follow", "nonsense"))
        self.assertEqual(dongle.commands, [])

    def test_firmware_without_bfollow_gives_clear_error(self):
        with self.assertRaises(RuntimeError) as ctx:
            xs.configure_ble(RecordingDongle(reject=("bfollow off",)), ble_args())
        self.assertIn("2.1.0", str(ctx.exception))

    def test_toolbar_selection_error_is_reported(self):
        handler = xs.ToolbarHandler(RecordingDongle(), ble_session.Session(host_start=0.0), ble_control)
        replies = handler.handle(xs.CTRL_DEVICE, ble_control.CMD_SET, b"garbage")
        self.assertIn("Error", replies[0][2])
        self.assertEqual(handler.follow, "all")

    def test_initial_message_mentions_followed_device(self):
        handler = xs.ToolbarHandler(RecordingDongle(), ble_session.Session(host_start=0.0), ble_control,
                                    follow="11:22:33:44:55:66,0")
        replies = handler.handle(0, ble_control.CMD_INITIALIZED, b"")
        self.assertIn("following 11:22:33:44:55:66", replies[-1][2])

    def test_extcap_config_offers_follow_options(self):
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            xs.extcap_config_ble()
        text = buf.getvalue()
        self.assertIn("{call=--scan-follow-rsp}", text)
        self.assertIn("{call=--follow}", text)
        self.assertIn("{type=boolflag}{default=true}", text)


if __name__ == "__main__":
    unittest.main()
