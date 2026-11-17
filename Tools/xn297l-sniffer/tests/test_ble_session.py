#!/usr/bin/env python3
"""
Tests of the BLE host side without hardware:
  ble_session.py   line parsing, timestamp unwrap, device table, RSSI filter, pcap records
  ble_control.py   extcap control channel framing
  xn297l_sniffer   extcap output of both interfaces, BLE configuration, toolbar handler,
                   end-to-end capture with a fake dongle writing into a FIFO
"""

import contextlib
import hashlib
import io
import os
import re
import struct
import sys
import tempfile
import threading
import time
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "extcap"))

import ble_control  # noqa: E402
import ble_pdu  # noqa: E402
import ble_phdr  # noqa: E402
import ble_session  # noqa: E402
import xn297l_sniffer as xs  # noqa: E402

AA = "D6BE898E"


def adv_hex(header0, payload: bytes, crc="ABCDEF") -> str:
    """Hex of an advertising LL packet as the firmware reports it."""
    return AA + bytes([header0, len(payload)]).hex().upper() + payload.hex().upper() + crc


ADV_IND_TEST = adv_hex(0x40, bytes.fromhex("665544332211") + bytes([2, 1, 6, 5, 9]) + b"Test")
ADV_IND_NONAME = adv_hex(0x00, bytes.fromhex("BBAA99887766") + bytes([2, 1, 6]))


def b_line(t_us, ch, rssi, flags, hexdata, phy=1, evt=0):
    return f"B {t_us} {ch} {rssi} {phy} {flags:02X} {evt} {hexdata}"


def capture_output(func, *args):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        func(*args)
    return buf.getvalue().splitlines()


class LineParsingTests(unittest.TestCase):
    def test_b_line(self):
        pkt = ble_session.parse_ble_line(b_line(1234, 38, -62, 1, ADV_IND_TEST))
        self.assertEqual((pkt.t_us, pkt.channel, pkt.rssi, pkt.phy), (1234, 38, -62, 1))
        self.assertTrue(pkt.crc_ok)
        self.assertEqual(pkt.data.hex().upper(), ADV_IND_TEST)

    def test_flags_are_hex(self):
        pkt = ble_session.parse_ble_line(f"B 1 37 -50 1 1A 0 {ADV_IND_TEST}")
        self.assertEqual(pkt.flags, 0x1A)
        self.assertFalse(pkt.crc_ok)

    def test_garbage_is_rejected(self):
        for line in ("", "B", "B 1 2 3", "P 1 2 -50 AABB", f"B x 38 -62 1 1 0 {ADV_IND_TEST}",
                     "B 1 38 -62 1 1 0 ZZ", "B 1 38 -62 1 1 0 AABB", f"B 1 99 -62 1 1 0 {ADV_IND_TEST}"):
            self.assertIsNone(ble_session.parse_ble_line(line), line)

    def test_info_line(self):
        info = ble_session.parse_info_line("I version=2.0.0 mode=ble caps=ble")
        self.assertEqual(info["mode"], "ble")
        self.assertIsNone(ble_session.parse_info_line("OK"))


class TimeUnwrapTests(unittest.TestCase):
    def test_monotonic_without_wrap(self):
        u = ble_session.TimeUnwrapper()
        self.assertEqual([u.unwrap(t) for t in (10, 20, 1000)], [10, 20, 1000])

    def test_wrap_of_32_bit_counter(self):
        u = ble_session.TimeUnwrapper()
        u.unwrap(0xFFFFFF00)
        self.assertEqual(u.unwrap(0x00000100), 0x100000100)         # wrapped once
        self.assertEqual(u.unwrap(0x00000200), 0x100000200)

    def test_small_step_backwards_is_not_a_wrap(self):
        u = ble_session.TimeUnwrapper()
        u.unwrap(5000)
        self.assertEqual(u.unwrap(4000), 4000)

    def test_two_wraps(self):
        u = ble_session.TimeUnwrapper()
        values = [u.unwrap(t) for t in (0xF0000000, 0x30000000, 0x70000000, 0xB0000000,
                                        0xF0000000, 0x30000000)]
        self.assertEqual(values[1], 0x130000000)             # first wrap
        self.assertEqual(values[-1], 0x230000000)            # second wrap


class DeviceTableTests(unittest.TestCase):
    def pdu(self, hexdata):
        return ble_pdu.parse_adv_packet(bytes.fromhex(hexdata))

    def test_new_device_is_added_with_name_and_rssi(self):
        table = ble_session.DeviceTable()
        events = table.update(self.pdu(ADV_IND_TEST), -62, 100.0)
        self.assertEqual(events, [("add", "11:22:33:44:55:66,1", '11:22:33:44:55:66 "Test" -62 dBm')])
        self.assertEqual(table.update(self.pdu(ADV_IND_TEST), -50, 101.0), [])   # no repeat

    def test_name_learned_later_replaces_entry(self):
        table = ble_session.DeviceTable()
        no_name = adv_hex(0x40, bytes.fromhex("665544332211") + bytes([2, 1, 6]))
        first = table.update(self.pdu(no_name), -70, 1.0)
        self.assertEqual(first[0][2], "11:22:33:44:55:66 -70 dBm")
        events = table.update(self.pdu(ADV_IND_TEST), -60, 2.0)
        self.assertEqual([e[0] for e in events], ["remove", "add"])
        self.assertIn('"Test"', events[1][2])

    def test_public_and_random_address_are_different_devices(self):
        table = ble_session.DeviceTable()
        payload = bytes.fromhex("665544332211") + bytes([2, 1, 6])
        table.update(self.pdu(adv_hex(0x00, payload)), -60, 1.0)
        table.update(self.pdu(adv_hex(0x40, payload)), -60, 1.0)
        self.assertEqual(len(table.devices), 2)

    def test_limit_removes_least_recently_seen(self):
        table = ble_session.DeviceTable(limit=2)
        for i, addr in enumerate(("01", "02", "03")):
            payload = bytes.fromhex(f"{addr}0000000000") + bytes([2, 1, 6])
            events = table.update(self.pdu(adv_hex(0x00, payload)), -60, float(i))
        self.assertEqual(len(table.devices), 2)
        self.assertEqual([e[0] for e in events], ["add", "remove"])
        self.assertEqual(events[1][1], "00:00:00:00:00:01,0")           # the oldest one

    def test_stale_devices_expire(self):
        table = ble_session.DeviceTable(stale_s=30)
        table.update(self.pdu(ADV_IND_TEST), -60, 100.0)
        self.assertEqual(table.expire(120.0), [])
        self.assertEqual(table.expire(131.0), [("remove", "11:22:33:44:55:66,1")])
        self.assertEqual(table.devices, {})

    def test_pdu_without_advertiser_address_is_ignored(self):
        table = ble_session.DeviceTable()
        pdu = self.pdu(adv_hex(0x07, bytes([1, 0x00])))
        self.assertEqual(table.update(pdu, -60, 1.0), [])


class SessionTests(unittest.TestCase):
    def session(self, **kw):
        return ble_session.Session(host_start=1000.0, **kw)

    def test_packet_becomes_pcap_record_with_phdr(self):
        s = self.session()
        events = s.handle_line(b_line(5_000_000, 37, -60, 1, ADV_IND_TEST), now=50.0)
        kinds = [e[0] for e in events]
        self.assertEqual(kinds, ["pcap", "add"])
        record = events[0][1]
        sec, usec, incl, orig = struct.unpack_from("<IIII", record)
        self.assertEqual((sec, usec), (1000, 0))               # first packet = host start
        phdr, packet = record[16:26], record[26:]
        self.assertEqual(phdr, ble_phdr.build_phdr(37, -60, 0x8E89BED6, True))
        self.assertEqual(packet.hex().upper(), ADV_IND_TEST)
        self.assertEqual(incl, len(phdr) + len(packet))

    def test_timestamps_follow_device_time(self):
        s = self.session()
        s.handle_line(b_line(1_000_000, 37, -60, 1, ADV_IND_TEST))
        rec = s.handle_line(b_line(3_500_000, 38, -60, 1, ADV_IND_TEST))[0][1]
        sec, usec = struct.unpack_from("<II", rec)
        self.assertEqual((sec, usec), (1002, 500000))

    def test_bad_crc_packet_is_kept_but_marked_and_not_listed(self):
        s = self.session()
        events = s.handle_line(b_line(1, 37, -60, 0, ADV_IND_TEST))
        self.assertEqual([e[0] for e in events], ["pcap"])         # no device list entry
        flags = struct.unpack_from("<H", events[0][1], 16 + 8)[0]
        self.assertEqual(flags & 0x0C00, 0x0400)                   # CRC checked, not valid

    def test_rssi_filter_hides_weak_advertising_packets(self):
        s = self.session(rssi_min=-70)
        self.assertEqual(s.handle_line(b_line(1, 37, -80, 1, ADV_IND_TEST)), [])
        self.assertEqual(s.handle_line(b_line(2, 37, -70, 1, ADV_IND_TEST))[0][0], "pcap")

    def test_rssi_filter_never_hides_connection_packets(self):
        s = self.session(rssi_min=-50)
        conn = "11223344" + "0200" + "ABCDEF"                      # some data PDU of AA 44332211
        events = s.handle_line(b_line(1, 5, -90, 0x05, conn))
        self.assertEqual(events[0][0], "pcap")
        phdr = events[0][1][16:26]
        self.assertEqual(struct.unpack_from("<I", phdr, 4)[0], 0x44332211)   # connection AA

    def test_drop_line_gives_status_message(self):
        s = self.session()
        events = s.handle_line("I drop n=7")
        self.assertEqual(events[0][0], "status")
        self.assertIn("7", events[0][1])
        self.assertEqual(s.dropped, 7)

    def test_xn297l_and_other_lines_are_ignored(self):
        s = self.session()
        for line in ("P 1000 40 -55 AAAAAA0380", "OK", "I version=2.0.0", "E nope", "garbage", ""):
            self.assertEqual(s.handle_line(line), [], line)

    def test_summary_text(self):
        s = self.session()
        text = s.handle_line(b_line(1, 38, -62, 1, ADV_IND_TEST))[0][2]
        self.assertIn("ADV_IND", text)
        self.assertIn("11:22:33:44:55:66", text)
        self.assertIn('"Test"', text)
        self.assertIn("CRC ok", text)


class ControlChannelTests(unittest.TestCase):
    def test_encode_exact_bytes(self):
        # 'T', length 2+3 = 5 (big endian, 3 bytes), control 3, command 1 (SET), payload "abc"
        self.assertEqual(ble_control.encode_message(3, ble_control.CMD_SET, "abc"),
                         b"T\x00\x00\x05\x03\x01abc")

    def test_empty_payload(self):
        self.assertEqual(ble_control.encode_message(0, ble_control.CMD_INITIALIZED),
                         b"T\x00\x00\x02\x00\x00")

    def test_round_trip(self):
        decoder = ble_control.MessageDecoder()
        data = (ble_control.encode_message(1, ble_control.CMD_SET, "x") +
                ble_control.encode_message(2, ble_control.CMD_REMOVE, "AA:BB"))
        self.assertEqual(decoder.feed(data),
                         [(1, 1, b"x"), (2, 3, b"AA:BB")])

    def test_split_across_reads_and_garbage(self):
        decoder = ble_control.MessageDecoder()
        msg = ble_control.encode_message(4, ble_control.CMD_SET, "-70")
        out = decoder.feed(b"zz" + msg[:3])
        self.assertEqual(out, [])
        out = decoder.feed(msg[3:] + msg)
        self.assertEqual(out, [(4, 1, b"-70")] * 2)

    def test_invalid_length_does_not_hang(self):
        decoder = ble_control.MessageDecoder()
        self.assertEqual(decoder.feed(b"T\x00\x00\x00" + ble_control.encode_message(1, 1, "a")),
                         [(1, 1, b"a")])

    def test_add_message_has_nul_separated_payload(self):
        msg = ble_control.add_entry_message(0, "AA:BB:CC:DD:EE:FF,0", 'AA:BB:CC:DD:EE:FF "x" -60 dBm')
        control, command, payload = ble_control.MessageDecoder().feed(msg)[0]
        self.assertEqual((control, command), (0, ble_control.CMD_ADD))
        self.assertEqual(payload.split(b"\0"), [b"AA:BB:CC:DD:EE:FF,0", b'AA:BB:CC:DD:EE:FF "x" -60 dBm'])


class RecordingDongle:
    """Records configuration commands (like the FakeDongle of test_decoder)."""

    def __init__(self, reject=()):
        self.commands = []
        self.reject = reject

    def command(self, cmd):
        self.commands.append(cmd)
        if cmd in self.reject:
            raise RuntimeError(f"dongle rejected '{cmd}': unknown command")


def ble_args(*argv):
    return xs.build_parser().parse_args(["--print", "--extcap-interface", "xn297l_ble",
                                         "--port", "X", *argv])


class ExtcapOutputTests(unittest.TestCase):
    def test_interfaces_lists_both(self):
        lines = capture_output(xs.extcap_interfaces)
        self.assertTrue(any("{value=xn297l}" in l for l in lines))
        self.assertTrue(any("{value=xn297l_ble}" in l for l in lines))

    def test_dlts_per_interface(self):
        self.assertIn("{number=147}", capture_output(xs.extcap_dlts, "xn297l")[0])
        self.assertIn("{number=256}", capture_output(xs.extcap_dlts, "xn297l_ble")[0])
        self.assertIn("{number=147}", capture_output(xs.extcap_dlts)[0])      # default unchanged

    def test_dlts_via_command_line(self):
        for interface, number in (("xn297l", "147"), ("xn297l_ble", "256")):
            buf = io.StringIO()
            old = sys.argv
            sys.argv = ["x", "--extcap-dlts", "--extcap-interface", interface]
            try:
                with contextlib.redirect_stdout(buf):
                    self.assertEqual(xs.main(), 0)
            finally:
                sys.argv = old
            self.assertIn(f"{{number={number}}}", buf.getvalue())

    def ble_config(self):
        return capture_output(xs.extcap_config, "xn297l_ble")

    def test_ble_config_is_well_formed(self):
        for line in self.ble_config():
            self.assertRegex(line, r"^(arg|value|control) (\{[a-z]+=[^{}]*\})+$")

    def test_ble_arg_numbers_unique_and_not_colliding_with_xn297l(self):
        numbers = {}
        for line in self.ble_config():
            m = re.match(r"arg \{number=(\d+)\}\{call=([^}]+)\}", line)
            if m:
                numbers[int(m.group(1))] = m.group(2)
        self.assertEqual(numbers, {100: "--port", 101: "--only-advertising", 102: "--adv-hop",
                                   103: "--rssi-filter", 104: "--adv-dwell"})
        self.assertTrue(all(n >= 100 for n in numbers))

    def test_ble_toolbar_controls(self):
        controls = {}
        for line in self.ble_config():
            m = re.match(r"control \{number=(\d+)\}\{type=([a-z]+)\}", line)
            if m:
                controls[int(m.group(1))] = m.group(2)
        self.assertEqual(controls, {0: "selector", 3: "string", 4: "string", 5: "button"})
        text = "\n".join(self.ble_config())
        self.assertIn("{display=Device}", text)
        self.assertIn("{value=all}{display=All advertising devices}", text)
        self.assertIn("{role=restore}", text)

    def test_every_call_name_is_accepted_by_the_parser(self):
        for line in self.ble_config():
            m = re.match(r"arg .*\{call=(--[a-z-]+)\}", line)
            if m:
                self.assertIn(m.group(1), xs.build_parser().format_help())

    def test_validation_regexes(self):
        hop = re.compile(xs.ADV_HOP_REGEX)
        for ok in ("37,38,39", "39", " 38 , 37 "):
            self.assertTrue(hop.match(ok), ok)
        for bad in ("", "36", "40", "37,", "37 38"):
            self.assertFalse(hop.match(bad), bad)
        rssi = re.compile(xs.RSSI_REGEX)
        for ok in ("0", "-1", "-99", "-100", "-127", " -60 "):
            self.assertTrue(rssi.match(ok), ok)
        for bad in ("-128", "1", "-0", "abc", "", "-"):
            self.assertFalse(rssi.match(bad), bad)

    def test_xn297l_config_unchanged(self):
        """Snapshot of the XN297L options (without the serial port list, which depends on the PC)."""
        lines = [l for l in capture_output(xs.extcap_config)
                 if not l.startswith("value {arg=0}") and "{number=0}" not in l]
        digest = hashlib.sha256("\n".join(lines).encode()).hexdigest()
        self.assertEqual(len(lines), 20)
        self.assertEqual(digest, "4fd9e788614c3dab64cc96911adf3111fee3349799cb77b1300f53b674314a51")


class ConfigureBleTests(unittest.TestCase):
    def test_default_commands(self):
        dongle = RecordingDongle()
        params = xs.configure_ble(dongle, ble_args())
        self.assertEqual(dongle.commands, ["stop", "mode ble", "bch 37,38,39", "bdwell 300",
                                           "brssi -127", "badv off", "start"])
        self.assertEqual(params["channels"], [37, 38, 39])

    def test_custom_options(self):
        dongle = RecordingDongle()
        xs.configure_ble(dongle, ble_args("--adv-hop", "39, 37", "--rssi-filter", "-75",
                                          "--adv-dwell", "50", "--only-advertising"))
        self.assertEqual(dongle.commands[2:6], ["bch 39,37", "bdwell 50", "brssi -75", "badv on"])

    def test_invalid_options_send_nothing(self):
        for argv in (["--adv-hop", "36"], ["--adv-hop", "37,37"], ["--rssi-filter", "5"],
                     ["--rssi-filter", "x"], ["--adv-dwell", "70000"]):
            dongle = RecordingDongle()
            with self.assertRaises(ValueError):
                xs.configure_ble(dongle, ble_args(*argv))
            self.assertEqual(dongle.commands, [], argv)

    def test_old_firmware_gives_clear_error(self):
        with self.assertRaises(RuntimeError) as ctx:
            xs.configure_ble(RecordingDongle(reject=("mode ble",)), ble_args())
        self.assertIn("firmware 2.0.0", str(ctx.exception))

    def test_xn297l_configure_unchanged(self):
        args = xs.build_parser().parse_args(["--print", "--port", "X", "--mode", "raw"])
        dongle = RecordingDongle()
        xs.configure(dongle, args)
        self.assertNotIn("mode ble", dongle.commands)       # the old interface never selects BLE
        self.assertEqual(dongle.commands[0], "stop")


class ToolbarHandlerTests(unittest.TestCase):
    def setUp(self):
        self.dongle = RecordingDongle()
        self.session = ble_session.Session(host_start=0.0)
        self.handler = xs.ToolbarHandler(self.dongle, self.session, ble_control)

    def set_msg(self, control, text):
        return self.handler.handle(control, ble_control.CMD_SET, text.encode())

    def test_adv_hop_is_sent_to_dongle(self):
        replies = self.set_msg(xs.CTRL_ADV_HOP, "38,39")
        self.assertEqual(self.dongle.commands, ["bch 38,39"])
        self.assertEqual(replies[0][1], ble_control.CMD_STATUSBAR)

    def test_invalid_hop_gives_status_error_and_no_command(self):
        replies = self.set_msg(xs.CTRL_ADV_HOP, "12")
        self.assertEqual(self.dongle.commands, [])
        self.assertIn("Error", replies[0][2])

    def test_rssi_sets_host_and_firmware_filter(self):
        self.set_msg(xs.CTRL_RSSI, "-80")
        self.assertEqual(self.session.rssi_min, -80)
        self.assertEqual(self.dongle.commands, ["brssi -80"])

    def test_invalid_rssi_rejected(self):
        self.set_msg(xs.CTRL_RSSI, "-200")
        self.assertEqual(self.session.rssi_min, ble_session.NO_RSSI_FILTER)
        self.assertEqual(self.dongle.commands, [])

    def test_dongle_error_is_reported_not_raised(self):
        self.dongle.reject = ("bch 39",)
        replies = self.set_msg(xs.CTRL_ADV_HOP, "39")
        self.assertIn("Error", replies[0][2])

    def test_device_selection_is_remembered(self):
        replies = self.set_msg(xs.CTRL_DEVICE, "11:22:33:44:55:66,1")
        self.assertEqual(self.handler.follow, "11:22:33:44:55:66,1")
        self.assertIn("not supported", replies[0][2])
        self.set_msg(xs.CTRL_DEVICE, "all")
        self.assertEqual(self.handler.follow, "all")
        self.assertEqual(self.dongle.commands, [])          # following needs a later firmware

    def test_defaults_button_restores_everything(self):
        self.set_msg(xs.CTRL_RSSI, "-60")
        self.dongle.commands.clear()
        replies = self.set_msg(xs.CTRL_DEFAULTS, "")
        self.assertEqual(self.dongle.commands, ["bch 37,38,39", "brssi -127"])
        self.assertEqual(self.session.rssi_min, -127)
        sets = {(c, p) for c, cmd, p in replies if cmd == ble_control.CMD_SET}
        self.assertEqual(sets, {(xs.CTRL_ADV_HOP, "37,38,39"), (xs.CTRL_RSSI, "-127"),
                                (xs.CTRL_DEVICE, "all")})

    def test_initialized_announces_known_devices(self):
        self.session.handle_line(b_line(1, 37, -60, 1, ADV_IND_TEST), now=1.0)
        replies = self.handler.handle(0, ble_control.CMD_INITIALIZED, b"")
        self.assertEqual(replies[0][1], ble_control.CMD_ADD)
        self.assertTrue(replies[0][2].startswith("11:22:33:44:55:66,1\0"))
        self.assertEqual(replies[-1][1], ble_control.CMD_STATUSBAR)

    def test_device_events_translate_to_messages(self):
        msgs = xs.device_event_messages([("add", "v", "d"), ("remove", "v"), ("status", "s")],
                                        ble_control)
        self.assertEqual(msgs, [(0, ble_control.CMD_ADD, "v\0d"), (0, ble_control.CMD_REMOVE, "v"),
                                (0, ble_control.CMD_STATUSBAR, "s")])


class ScriptedDongle:
    """Fake dongle for end-to-end tests: delivers scripted lines, then idles briefly."""

    instances = []

    def __init__(self, port):
        self.lines = list(self.script)
        self.commands = []
        self.deadline = None
        ScriptedDongle.instances.append(self)

    script = []

    def command(self, cmd, timeout=2.0):
        self.commands.append(cmd)

    def readline(self):
        time.sleep(0.002)
        if self.lines:
            return self.lines.pop(0)
        if self.deadline is None:
            self.deadline = time.time() + self.idle
        if time.time() > self.deadline:
            raise KeyboardInterrupt          # ends the capture loop like Ctrl+C
        return None

    idle = 0.2

    def close(self):
        self.closed = True


class EndToEndTests(unittest.TestCase):
    def run_capture(self, script, extra_args=(), idle=0.2, control=None):
        """Run run_capture_ble with a scripted dongle; returns (pcap bytes, dongle)."""
        old = xs.Dongle
        ScriptedDongle.script = script
        ScriptedDongle.idle = idle
        xs.Dongle = ScriptedDongle
        try:
            with tempfile.TemporaryDirectory() as tmp:
                fifo = os.path.join(tmp, "capture.pcap")        # a plain file works like the FIFO
                argv = ["--capture", "--extcap-interface", "xn297l_ble", "--port", "X",
                        "--fifo", fifo, *extra_args]
                args = xs.build_parser().parse_args(argv)
                if control:
                    args.extcap_control_in, args.extcap_control_out = control
                xs.run_capture_ble(args)
                with open(fifo, "rb") as f:
                    return f.read(), ScriptedDongle.instances[-1]
        finally:
            xs.Dongle = old

    def test_pcap_file_is_valid_and_complete(self):
        script = [b_line(1000 + i * 500, 37 + i % 3, -60 - i, 1, ADV_IND_TEST) for i in range(6)]
        script.insert(2, "P 1 2 -50 AABB")                         # legacy line, must be ignored
        data, dongle = self.run_capture(script)
        self.assertEqual(data[:24], ble_phdr.pcap_header_256())
        pos, count = 24, 0
        while pos < len(data):
            incl = struct.unpack_from("<I", data, pos + 8)[0]
            record = data[pos + 16:pos + 16 + incl]
            self.assertEqual(record[10:14].hex().upper(), AA)       # packet follows the 10 byte PHDR
            pos += 16 + incl
            count += 1
        self.assertEqual((pos, count), (len(data), 6))
        self.assertEqual(dongle.commands[:2], ["stop", "mode ble"])
        self.assertEqual(dongle.commands[-1], "start")

    def test_capture_with_control_pipes(self):
        """Toolbar round trip over real FIFOs: INITIALIZED, device list ADD, RSSI SET."""
        script = [b_line(1000, 37, -60, 1, ADV_IND_TEST)]
        with tempfile.TemporaryDirectory() as tmp:
            ctl_in, ctl_out = os.path.join(tmp, "in"), os.path.join(tmp, "out")
            os.mkfifo(ctl_in)
            os.mkfifo(ctl_out)
            received = []

            def wireshark_side():
                # Wireshark side: writes user input, reads what the extcap sends
                def reader():
                    decoder = ble_control.MessageDecoder()
                    with open(ctl_out, "rb", buffering=0) as pipe:
                        while True:
                            data = pipe.read(4096)
                            if not data:
                                return
                            received.extend(decoder.feed(data))
                t = threading.Thread(target=reader, daemon=True)
                t.start()
                with open(ctl_in, "wb", buffering=0) as pipe:
                    pipe.write(ble_control.encode_message(0, ble_control.CMD_INITIALIZED))
                    time.sleep(0.1)
                    pipe.write(ble_control.encode_message(xs.CTRL_RSSI, ble_control.CMD_SET, "-75"))
                    time.sleep(0.4)
                t.join(timeout=3)

            thread = threading.Thread(target=wireshark_side, daemon=True)
            thread.start()
            _, dongle = self.run_capture(script, idle=0.7, control=(ctl_in, ctl_out))
            thread.join(timeout=5)
        commands = [(c, cmd) for c, cmd, _ in received]
        self.assertIn((xs.CTRL_DEVICE, ble_control.CMD_ADD), commands)       # device list entry
        self.assertIn((xs.CTRL_DEVICE, ble_control.CMD_STATUSBAR), commands)  # status text
        self.assertIn("brssi -75", dongle.commands)

    def test_old_firmware_reports_error(self):
        class OldDongle(ScriptedDongle):
            def command(self, cmd, timeout=2.0):
                if cmd == "mode ble":
                    raise RuntimeError("dongle rejected 'mode ble': unknown command")
        old = xs.Dongle
        xs.Dongle = OldDongle
        err = io.StringIO()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                args = xs.build_parser().parse_args(["--capture", "--extcap-interface", "xn297l_ble",
                                                     "--port", "X", "--fifo", os.path.join(tmp, "f")])
                with contextlib.redirect_stderr(err):
                    xs.run_capture_ble(args)
        finally:
            xs.Dongle = old
        self.assertIn("firmware 2.0.0", err.getvalue())

    def test_print_mode_prints_packets_and_devices(self):
        ScriptedDongle.script = [b_line(1000, 37, -60, 1, ADV_IND_TEST),
                                 b_line(2000, 38, -61, 1, ADV_IND_NONAME)]
        ScriptedDongle.idle = 0.05
        old = xs.Dongle
        xs.Dongle = ScriptedDongle
        try:
            lines = capture_output(xs.run_print_ble, ble_args())
        finally:
            xs.Dongle = old
        text = "\n".join(lines)
        self.assertIn("ADV_IND 11:22:33:44:55:66", text)
        self.assertIn("# device 11:22:33:44:55:66", text)
        self.assertIn("66:77:88:99:AA:BB", text)


if __name__ == "__main__":
    unittest.main()
