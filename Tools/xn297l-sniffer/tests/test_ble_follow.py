#!/usr/bin/env python3
"""
Tests of the connection following logic (firmware/src/ble_follow.c and its
Python model tests/ble_follow_model.py).

Every scenario is a script in the line format of tests/c/follow_driver.c. It
is executed on the Python model, whose output is compared with hand
calculated expectations, and - if a host C compiler exists - on the firmware C
code, whose output must be identical to the model's. A final fuzz test
compares both on random scripts.

Time values: 1 us units, interval 24 = 30 ms = 30000 us.
"""

import os
import random
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "extcap"))

import ble_csa_model as csa  # noqa: E402
import ble_follow_model as model  # noqa: E402
import c_driver  # noqa: E402

HAVE_C = c_driver.driver_path() is not None

TARGET = "665544332211"          # followed device 11:22:33:44:55:66 (on-air order)
OTHER = "BBAA99887766"
INITIATOR = "A1A2A3A4A5A6"
CONN_AA = 0x50655A21
FULL_MAP = "FFFFFFFF1F"


# ---------------------------------------------------------------------------
# Packet builders (PDU = header + payload, hex strings)
# ---------------------------------------------------------------------------

def pdu(header0: int, payload: bytes) -> str:
    return (bytes([header0, len(payload)]) + payload).hex()


def adv_ind(addr=TARGET, chsel=False, tx_random=False) -> str:
    return pdu(0x00 | chsel << 5 | tx_random << 6, bytes.fromhex(addr) + bytes([2, 1, 6]))


def scan_req(adv_a=TARGET) -> str:
    return pdu(0x03, bytes.fromhex(INITIATOR + adv_a))


def scan_rsp(addr=TARGET) -> str:
    return pdu(0x04, bytes.fromhex(addr) + bytes([3, 9]) + b"ab")


def connect_ind(adv_a=TARGET, chsel=False, win_size=2, win_offset=2, interval=24, latency=0,
                timeout=200, chmap=FULL_MAP, hop=7, sca=5, aa=CONN_AA, crc_init=0x123456) -> str:
    ll_data = (aa.to_bytes(4, "little") + crc_init.to_bytes(3, "little") + bytes([win_size])
               + win_offset.to_bytes(2, "little") + interval.to_bytes(2, "little")
               + latency.to_bytes(2, "little") + timeout.to_bytes(2, "little")
               + bytes.fromhex(chmap) + bytes([hop | sca << 5]))
    return pdu(0x05 | chsel << 5, bytes.fromhex(INITIATOR + adv_a) + ll_data)


def data(llid=1, md=False, payload=b"") -> str:
    return pdu(llid | md << 4, payload)


def ctrl(opcode: int, body: bytes = b"", md=False) -> str:
    return data(3, md, bytes([opcode]) + body)


def conn_update(instant, interval=40, win_size=1, win_offset=3, latency=0, timeout=300) -> str:
    return ctrl(0x00, bytes([win_size]) + win_offset.to_bytes(2, "little")
                + interval.to_bytes(2, "little") + latency.to_bytes(2, "little")
                + timeout.to_bytes(2, "little") + instant.to_bytes(2, "little"))


def chmap_update(chmap: str, instant: int) -> str:
    return ctrl(0x01, bytes.fromhex(chmap) + instant.to_bytes(2, "little"))


def parse_plan(line: str) -> dict:
    """'plan ch=1 ctr=2 on=3 off=4 fl=0' -> dict of ints."""
    assert line.startswith("plan "), line
    names = {"on": "rx_on_us", "off": "rx_off_us"}
    return {names.get(k, k): int(v) for k, v in (t.split("=") for t in line.split()[1:])}


class ScriptTestCase(unittest.TestCase):
    """Runs scripts on the model and (if possible) the C code and compares them."""

    def run_script(self, lines):
        out = model.run_script(lines)
        if HAVE_C:
            self.assertEqual(c_driver.run_script(lines), out, "C code differs from the model")
        return out

    def connect(self, extra=(), **kwargs):
        """Script prefix: follow TARGET, see its ADV_IND (chsel), then its CONNECT_IND at t=1,000,000."""
        chsel = kwargs.pop("chsel", False)
        return ["init", f"target {TARGET} 2", f"adv 1 900000 {adv_ind(chsel=chsel)}",
                f"adv 1 1000000 {connect_ind(chsel=chsel, **kwargs)}", *extra]


# ---------------------------------------------------------------------------
# Advertising filter
# ---------------------------------------------------------------------------

class AdvFilterTests(ScriptTestCase):
    def test_no_target_forwards_everything(self):
        out = self.run_script(["init", f"adv 1 0 {adv_ind(OTHER)}", f"adv 0 0 {scan_rsp(OTHER)}"])
        self.assertEqual(out, ["adv 1", "adv 1"])

    def test_target_forwards_only_its_packets(self):
        out = self.run_script([
            "init", f"target {TARGET} 2",
            f"adv 1 0 {adv_ind(OTHER)}",                  # another device
            f"adv 1 0 {adv_ind(TARGET)}",                 # ADV_IND: forward + wait for response
            f"adv 1 0 {scan_req(TARGET)}",                # SCAN_REQ to it: forward + wait for SCAN_RSP
            f"adv 1 0 {scan_req(OTHER)}",
            f"adv 1 0 {scan_rsp(TARGET)}",                # SCAN_RSP: forward, nothing follows
            f"adv 1 0 {scan_rsp(OTHER)}"])
        self.assertEqual(out, ["adv 0", "adv 3", "adv 3", "adv 0", "adv 1", "adv 0"])

    def test_address_type_is_matched_when_given(self):
        out = self.run_script(["init", f"target {TARGET} 1",
                               f"adv 1 0 {adv_ind(TARGET, tx_random=False)}",
                               f"adv 1 0 {adv_ind(TARGET, tx_random=True)}"])
        self.assertEqual(out, ["adv 0", "adv 3"])

    def test_scan_traffic_can_be_switched_off(self):
        out = self.run_script(["init", f"target {TARGET} 2", "opts 0 0",
                               f"adv 1 0 {adv_ind(TARGET)}", f"adv 1 0 {scan_req(TARGET)}",
                               f"adv 1 0 {scan_rsp(TARGET)}"])
        self.assertEqual(out, ["adv 1", "adv 0", "adv 0"])     # no wait, no scan traffic

    def test_malformed_and_unknown_pdus_are_ignored(self):
        out = self.run_script(["init", f"target {TARGET} 2", "adv 1 0 00", "adv 1 0 0006665544",
                               f"adv 1 0 {pdu(0x0F, bytes(8))}"])
        self.assertEqual(out, ["adv 0", "adv 0", "adv 0"])

    def test_following_off_again(self):
        out = self.run_script(["init", f"target {TARGET} 2", "target off 0",
                               f"adv 1 0 {adv_ind(OTHER)}"])
        self.assertEqual(out, ["adv 1"])


# ---------------------------------------------------------------------------
# CONNECT_IND
# ---------------------------------------------------------------------------

class ConnectIndTests(ScriptTestCase):
    def test_connect_ind_of_target_starts_connection(self):
        out = self.run_script(self.connect(["info"]))
        self.assertEqual(out[1], "adv 5")        # forward + connect
        self.assertEqual(out[2], "info aa=50655a21 crc=123456 int=24 lat=0 to=200 "
                                 "map=ffffffff1f hop=7 csa=1 sca=5 ctr=0")

    def test_connect_ind_of_other_device_is_ignored(self):
        out = self.run_script(["init", f"target {TARGET} 2", f"adv 1 0 {connect_ind(adv_a=OTHER)}"])
        self.assertEqual(out, ["adv 0"])

    def test_connect_ind_with_bad_crc_is_forwarded_but_not_followed(self):
        out = self.run_script(["init", f"target {TARGET} 2", f"adv 0 0 {connect_ind()}", "next"])
        self.assertEqual(out, ["adv 1", "lost 0"])

    def test_connection_following_can_be_switched_off(self):
        out = self.run_script(["init", f"target {TARGET} 2", "opts 0 1", f"adv 1 0 {connect_ind()}"])
        self.assertEqual(out, ["adv 1"])

    def test_invalid_parameters_are_rejected(self):
        for kwargs in ({"interval": 5}, {"interval": 3201}, {"hop": 4}, {"hop": 17},
                       {"chmap": "0100000000"}, {"chmap": "0000000000"}):
            out = self.run_script(["init", f"target {TARGET} 2", f"adv 1 0 {connect_ind(**kwargs)}"])
            self.assertEqual(out, ["adv 1"], kwargs)

    def test_reserved_channel_map_bits_are_ignored(self):
        out = self.run_script(self.connect(["info"], chmap="FFFFFFFFFF"))
        self.assertIn("map=ffffffff1f", out[2])

    def test_csa2_needs_chsel_in_advertiser_and_initiator(self):
        for adv_chsel, conn_chsel, expected in ((True, True, 2), (True, False, 1),
                                                (False, True, 1), (False, False, 1)):
            out = self.run_script([
                "init", f"target {TARGET} 2", f"adv 1 0 {adv_ind(chsel=adv_chsel)}",
                f"adv 1 0 {connect_ind(chsel=conn_chsel)}", "info"])
            self.assertIn(f"csa={expected}", out[2], (adv_chsel, conn_chsel))


# ---------------------------------------------------------------------------
# First event, anchors, widening
# ---------------------------------------------------------------------------

class FirstEventTests(ScriptTestCase):
    def test_first_window_numbers(self):
        # CONNECT_IND starts at 1,000,000 and lasts (10 + 34) * 8 = 352 us -> ends 1,000,352.
        # Transmit window: + 1250 + WinOffset(2) * 1250 = 1,004,102, size 2 * 1250 = 2500 us.
        # SCA index 5 = 50 ppm: widening (50 + 50) ppm * 3750 us = 0 + 16 us jitter.
        plan = parse_plan(self.run_script(self.connect(["next"]))[2])
        self.assertEqual(plan["rx_on_us"], 1004102 - 16 - 50)
        self.assertEqual(plan["rx_off_us"], 1004102 + 2500 + 16 + 40 + 30)
        self.assertEqual(plan["ctr"], 0)
        self.assertEqual(plan["ch"], 7)           # CSA #1: (0 + hop 7) % 37
        self.assertEqual(plan["fl"], 0)

    def test_anchor_resynchronises_the_schedule(self):
        # master packet (empty PDU, 0 bytes payload = 80 us) 1,000 us into the window
        out = self.run_script(self.connect([
            "next", "pkt 1 1005000 0100", "pkt 1 1005230 0100", "next"]))
        # master packet: anchor (2) + continue (8); listen until its end (1005000 + 80 us airtime)
        # + T_IFS window of 240 us
        self.assertEqual(out[3], "pkt 10 1005320")
        # slave packet 150 us after the master packet ended: direction slave -> master (1), event over
        self.assertEqual(out[4], "pkt 1 0")
        plan = parse_plan(out[5])
        # next event 30000 us after the anchor, widening (100 ppm * 30000 us = 3) + 16
        self.assertEqual(plan["ctr"], 1)
        self.assertEqual(plan["rx_on_us"], 1005000 + 30000 - 19 - 50)
        self.assertEqual(plan["rx_off_us"], 1005000 + 30000 + 19 + 40 + 30)

    def test_widening_grows_with_missed_events(self):
        out = self.run_script(self.connect(["next", "pkt 1 1005000 0100", "pkt 1 1005230 0100",
                                            "next", "next", "next"]))
        widths = []
        for k, line in enumerate(out[5:], start=1):   # events 1, 2, 3 without any packet
            plan = parse_plan(line)
            start = 1005000 + k * 30000
            widths.append(start - plan["rx_on_us"] - 50)
        # (50+50) ppm * 30 ms, 60 ms, 90 ms = 3, 6, 9 us plus the fixed 16 us
        self.assertEqual(widths, [19, 22, 25])

    def test_widening_is_capped_below_half_an_interval(self):
        # hop 7, SCA 0 (500 ppm), 7.5 ms interval: a missed event run makes the widening huge
        script = self.connect(["next", "pkt 1 1005000 0100"], interval=6, sca=0, timeout=3200)
        script += ["next"] * 1000     # 7.5 s without a packet: (500 + 50) ppm exceeds the cap
        out = self.run_script(script)
        plan = parse_plan(out[-1])
        start = 1005000 + 1000 * 7500
        self.assertEqual(start - plan["rx_on_us"] - 50, 7500 // 2 - 150)

    def test_event_with_no_packet_still_advances_counter_and_channel(self):
        out = self.run_script(self.connect(["next", "next", "next"]))
        plans = [parse_plan(line) for line in out[2:]]
        self.assertEqual([p["ctr"] for p in plans], [0, 1, 2])
        self.assertEqual([p["ch"] for p in plans], [7, 14, 21])


class SupervisionTests(ScriptTestCase):
    def test_no_packet_after_connect_ind_gives_up_after_six_events(self):
        # limit = 1250 + 2 * 1250 + 2500 (window) + 6 * 30000 relative to the end of CONNECT_IND
        out = self.run_script(self.connect(["next"] * 9))
        self.assertEqual([line.split()[0] for line in out[2:]], ["plan"] * 7 + ["lost", "lost"])
        self.assertEqual(out[-1], f"lost {model.LOST_ESTABLISH}")

    def test_supervision_timeout_after_last_valid_packet(self):
        # timeout 200 = 2 s = 66 events of 30 ms
        script = self.connect(["next", "pkt 1 1005000 0100", "pkt 1 1005230 0100"])
        script += ["next"] * 70
        out = self.run_script(script)
        plans = [line for line in out[5:] if line.startswith("plan")]
        self.assertEqual(len(plans), 66)            # events 1..66, 2.0 s after the last packet
        self.assertEqual(out[-1], f"lost {model.LOST_TIMEOUT}")

    def test_bad_crc_packets_do_not_feed_the_supervision_timer(self):
        # anchor with CRC error only: the 6 event establishment limit still applies
        script = self.connect(["next", "pkt 0 1005000 0100"])
        script += ["next"] * 70
        out = self.run_script(script)
        self.assertEqual(out[-1], f"lost {model.LOST_ESTABLISH}")


# ---------------------------------------------------------------------------
# Packets inside an event
# ---------------------------------------------------------------------------

class EventPacketTests(ScriptTestCase):
    def packets(self, *packets):
        """Run (crc, start_us, pdu) packets inside event 0 and return the 'pkt' lines."""
        script = self.connect(["next"] + [f"pkt {int(c)} {t} {p}" for c, t, p in packets])
        return self.run_script(script)[3:]

    def test_direction_alternates_master_slave(self):
        out = self.packets((True, 1005000, data(md=True)), (True, 1005230, data(md=True)),
                           (True, 1005460, data()), (True, 1005690, data()))
        flags = [int(line.split()[1]) for line in out]
        self.assertEqual([f & 1 for f in flags], [0, 1, 0, 1])      # BLE_PKT_DIR_S2M
        self.assertEqual([bool(f & 2) for f in flags], [True, False, False, False])  # anchor

    def test_master_packet_always_expects_a_slave_answer(self):
        out = self.packets((True, 1005000, data()))
        self.assertEqual(int(out[0].split()[1]) & 8, 8)            # continue
        self.assertEqual(int(out[0].split()[2]), 1005000 + 80 + 240)   # airtime + T_IFS window

    def test_event_ends_after_slave_packet_without_more_data(self):
        out = self.packets((True, 1005000, data()), (True, 1005230, data()))
        self.assertEqual(int(out[1].split()[1]) & 8, 0)

    def test_more_data_of_master_or_slave_continues_the_event(self):
        for master_md, slave_md in ((True, False), (False, True), (True, True)):
            out = self.packets((True, 1005000, data(md=master_md)),
                               (True, 1005230, data(md=slave_md)))
            self.assertEqual(int(out[1].split()[1]) & 8, 8, (master_md, slave_md))

    def test_crc_error_in_slave_packet_closes_the_event(self):
        out = self.packets((True, 1005000, data(md=True)), (False, 1005230, data(md=True)))
        self.assertEqual(int(out[1].split()[1]) & 8, 0)

    def test_gap_flag(self):
        # first packet is 80 us long, ends 1005080; the slave should start at 1005230
        for start, gap_flag in ((1005230, False), (1005230 + 20, False), (1005230 + 21, True),
                                (1005230 - 21, True), (1006000, True)):
            out = self.packets((True, 1005000, data()), (True, start, data()))
            self.assertEqual(bool(int(out[1].split()[1]) & 4), gap_flag, start)


# ---------------------------------------------------------------------------
# LL control: instants, terminate, encryption
# ---------------------------------------------------------------------------

def run_events(first_event, last_event, start_us, interval_us, first_pdu=None, payloads=None):
    """Script lines for events first_event .. last_event with one master + one slave packet each.

    `payloads` maps event number -> master PDU (default: empty PDU). Events are
    on schedule: event k starts at start_us + (k - first_event) * interval_us.
    """
    lines = []
    for k in range(first_event, last_event + 1):
        t = start_us + (k - first_event) * interval_us
        lines += ["next", f"pkt 1 {t} {(payloads or {}).get(k, '0100')}", f"pkt 1 {t + 230} 0100"]
    return lines


class ControlPduTests(ScriptTestCase):
    def test_connection_update_applied_at_instant(self):
        # Update at instant 6: interval 40 (50 ms), WinSize 1, WinOffset 3, announced in event 2.
        interval_us = 30000
        script = self.connect(run_events(0, 5, 1005000, interval_us, payloads={2: conn_update(6)}))
        script += ["next", "info"]
        out = self.run_script(script)
        plan = parse_plan(out[-2])
        self.assertEqual(plan["ctr"], 6)
        self.assertEqual(plan["fl"], model.PLAN_UPDATED)
        # old schedule extrapolated to event 6: anchor of event 5 + 30000 = 1005000 + 6 * 30000;
        # new window opens WinOffset (3 * 1250 us) later and is 1 * 1250 us wide.
        start = 1005000 + 6 * 30000 + 3 * 1250
        self.assertEqual(plan["rx_on_us"], start - 50 - (100 * (start - (1005000 + 5 * 30000)) // 1000000 + 16))
        self.assertEqual(plan["rx_off_us"],
                         start + 1250 + (100 * (start - (1005000 + 5 * 30000)) // 1000000 + 16) + 70)
        self.assertIn("int=40 lat=0 to=300", out[-1])
        # after the first packet in the new window the new interval (50 ms) applies
        out = self.run_script(script[:-1] + [f"pkt 1 {start + 500} 0100", "pkt 1 0 0100"] + ["next"])
        self.assertEqual(parse_plan(out[-1])["rx_on_us"] // 1000, (start + 500 + 50000 - 19 - 50) // 1000)

    def test_events_before_the_instant_keep_the_old_schedule(self):
        script = self.connect(run_events(0, 4, 1005000, 30000, payloads={2: conn_update(6)}))
        script += ["next"]
        plan = parse_plan(self.run_script(script)[-1])
        self.assertEqual(plan["ctr"], 5)
        self.assertEqual(plan["fl"], 0)

    def test_update_with_instant_in_the_past_is_ignored(self):
        # announced in event 4 for instant 3
        script = self.connect(run_events(0, 4, 1005000, 30000, payloads={4: conn_update(3)}))
        script += ["next", "next", "info"]
        out = self.run_script(script)
        self.assertIn("int=24", out[-1])

    def test_instant_boundary(self):
        # announced in event 1: an instant 32766 events ahead is accepted, 32767 counts as passed.
        # The pending update is observed by running events up to the instant (C and model compared).
        for ahead, accepted in ((32766, True), (32767, False)):
            instant = 1 + ahead
            script = self.connect(["next", "pkt 1 1005000 0100", "pkt 1 1005230 0100", "next",
                                   f"pkt 1 1035000 {conn_update(instant, interval=40)}",
                                   "pkt 1 1035230 0100"])
            t = 1035000
            for _ in range(2, instant + 1):             # events 2 .. instant, on schedule
                t += 30000
                script += ["next", f"pkt 1 {t} 0100", f"pkt 1 {t + 230} 0100"]
            script += ["info"]
            self.assertIn("int=40" if accepted else "int=24", self.run_script(script)[-1], ahead)

    def test_update_from_slave_is_ignored(self):
        # slave packets are the odd ones: put the update PDU into the slave's slot
        script = self.connect(["next", "pkt 1 1005000 0100", f"pkt 1 1005230 {conn_update(3)}"])
        script += ["next", "next", "next", "next", "info"]
        self.assertIn("int=24", self.run_script(script)[-1])

    def test_update_with_bad_crc_is_ignored(self):
        script = self.connect(["next", f"pkt 0 1005000 {conn_update(3)}", "pkt 1 1005230 0100"])
        script += ["next", "next", "next", "next", "info"]
        self.assertIn("int=24", self.run_script(script)[-1])

    def test_channel_map_update_applied_at_instant(self):
        new_map = csa.map_to_bytes([1, 3, 5, 7, 9, 11, 13, 15]).hex()
        script = self.connect(run_events(0, 3, 1005000, 30000, payloads={1: chmap_update(new_map, 5)}))
        script += ["next", "next", "next"]            # events 4, 5, 6
        out = self.run_script(script)
        plans = [parse_plan(line) for line in out[-3:]]
        self.assertEqual([p["fl"] for p in plans], [0, model.PLAN_UPDATED, 0])
        # expected channels from the model algorithm: event 4 with the old, 5 and 6 with the new map
        last, expected = 0, []
        full, reduced = bytes.fromhex(FULL_MAP), bytes.fromhex(new_map)
        for ctr in range(7):
            channel, last = csa.csa1_next(last, 7, reduced if ctr >= 5 else full)
            expected.append(channel)
        self.assertEqual([p["ch"] for p in plans], expected[4:])
        self.assertTrue(all(ch in [1, 3, 5, 7, 9, 11, 13, 15] for ch in expected[5:]))

    def test_channel_map_update_with_csa2(self):
        new_map = csa.map_to_bytes([0, 2, 4, 6, 8]).hex()
        script = self.connect(run_events(0, 1, 1005000, 30000, payloads={1: chmap_update(new_map, 3)}),
                              chsel=True)
        script += ["next", "next"]                    # events 2, 3
        plans = [parse_plan(line) for line in self.run_script(script)[-2:]]
        cid = csa.csa2_channel_id(CONN_AA)
        self.assertEqual(plans[0]["ch"], csa.csa2_channel(cid, 2, bytes.fromhex(FULL_MAP)))
        self.assertEqual(plans[1]["ch"], csa.csa2_channel(cid, 3, bytes.fromhex(new_map)))

    def test_instant_after_event_counter_wrap(self):
        # Run a connection to event 65534, announce an update there with instant 3 (wraps past
        # 65535 -> 0). interval 6 = 7.5 ms keeps the script short.
        interval_us = 7500
        start = 2000000
        script = self.connect([], interval=6, win_offset=0, win_size=1, timeout=3200)
        script += run_events(0, 65533, start, interval_us)
        script += ["next", f"pkt 1 {start + 65534 * interval_us} {conn_update(3, interval=12, win_offset=0, win_size=1)}",
                   f"pkt 1 {start + 65534 * interval_us + 230} 0100"]
        script += ["next", "next", "next", "next", "next"]      # events 65535, 0, 1, 2, 3
        out = self.run_script(script)
        plans = [parse_plan(line) for line in out[-5:]]
        self.assertEqual([p["ctr"] for p in plans], [65535, 0, 1, 2, 3])
        self.assertEqual([p["fl"] for p in plans], [0, 0, 0, 0, model.PLAN_UPDATED])

    def test_terminate_ind_ends_the_connection_after_the_event(self):
        script = self.connect(["next", f"pkt 1 1005000 {ctrl(0x02, bytes([0x13]))}",
                               "pkt 1 1005230 0100", "next"])
        out = self.run_script(script)
        self.assertEqual(int(out[4].split()[1]) & 8, 0)           # no further packet expected
        self.assertEqual(out[-1], f"lost {model.LOST_TERMINATE}")

    def test_terminate_from_slave(self):
        script = self.connect(["next", "pkt 1 1005000 0100",
                               f"pkt 1 1005230 {ctrl(0x02, bytes([0x08]), md=True)}", "next"])
        self.assertEqual(self.run_script(script)[-1], f"lost {model.LOST_TERMINATE}")

    def test_control_pdus_are_not_parsed_after_encryption_start(self):
        # LL_START_ENC_REQ (slave) switches parsing off; later "terminate"-looking bytes are ciphertext
        script = self.connect(["next", "pkt 1 1005000 0100",
                               f"pkt 1 1005230 {ctrl(0x05)}", "next",
                               f"pkt 1 1035000 {ctrl(0x02, bytes([0x13]))}", "pkt 1 1035230 0100",
                               "next"])
        self.assertTrue(self.run_script(script)[-1].startswith("plan"))

    def test_ll_control_before_encryption_is_parsed(self):
        # ENC_REQ / ENC_RSP are in the clear and do not stop the parser
        script = self.connect(["next", f"pkt 1 1005000 {ctrl(0x03, bytes(22))}", "pkt 1 1005230 0100",
                               "next", "pkt 1 1035000 0100", f"pkt 1 1035230 {ctrl(0x04, bytes(12))}",
                               "next", f"pkt 1 1065000 {ctrl(0x02, bytes([0x13]))}",
                               "pkt 1 1065230 0100", "next"])
        self.assertEqual(self.run_script(script)[-1], f"lost {model.LOST_TERMINATE}")


# ---------------------------------------------------------------------------
# Whole connection and fuzzing
# ---------------------------------------------------------------------------

class WholeConnectionTests(ScriptTestCase):
    def test_csa1_and_csa2_channel_sequences(self):
        for chsel in (False, True):
            script = self.connect(run_events(0, 40, 1005000, 30000), chsel=chsel)
            out = self.run_script(script)
            channels = [parse_plan(line)["ch"] for line in out if line.startswith("plan")]
            cid = csa.csa2_channel_id(CONN_AA)
            if chsel:
                expected = [csa.csa2_channel(cid, k, bytes.fromhex(FULL_MAP)) for k in range(41)]
            else:
                expected = [(7 * (k + 1)) % 37 for k in range(41)]
            self.assertEqual(channels, expected)

    def test_reconnect_after_lost_connection(self):
        script = self.connect(["next"] * 9)                        # establishment fails
        script += [f"adv 1 90000000 {adv_ind()}", f"adv 1 90001000 {connect_ind(hop=9)}", "next"]
        out = self.run_script(script)
        self.assertEqual(out[-2], "adv 5")
        self.assertEqual(parse_plan(out[-1])["ch"], 9)


@unittest.skipUnless(HAVE_C, "no host C compiler")
class FuzzTests(ScriptTestCase):
    def test_c_matches_model_on_random_scripts(self):
        rng = random.Random(20240601)
        for round_no in range(60):
            script = ["init", f"target {TARGET} 2"]
            t = rng.getrandbits(32)                     # includes start times near the 32 bit wrap
            if round_no % 3 == 0:
                t = 0xFFFFF000
            script.append(f"adv 1 {t} {adv_ind(chsel=rng.random() < 0.5)}")
            script.append(f"adv 1 {t + 300} " + connect_ind(
                chsel=rng.random() < 0.5, win_size=rng.randint(0, 10), win_offset=rng.randint(0, 40),
                interval=rng.randint(6, 80), timeout=rng.randint(10, 300), hop=rng.randint(5, 16),
                sca=rng.randint(0, 7), chmap=csa.map_to_bytes(rng.sample(range(37), rng.randint(2, 37))).hex(),
                aa=rng.getrandbits(32)))
            for _ in range(rng.randint(5, 80)):
                choice = rng.random()
                t = (t + rng.randint(100, 60000)) & 0xFFFFFFFF
                if choice < 0.4:
                    script.append("next")
                elif choice < 0.9:
                    pdus = [data(md=rng.random() < 0.3), data(llid=2, payload=bytes(rng.randint(0, 20))),
                            conn_update(rng.getrandbits(16), interval=rng.randint(6, 100)),
                            chmap_update(csa.map_to_bytes(rng.sample(range(37), rng.randint(2, 37))).hex(),
                                         rng.getrandbits(16)),
                            ctrl(rng.randint(0, 0x19), bytes(rng.randint(0, 12))), "0100", "03"]
                    script.append(f"pkt {int(rng.random() < 0.8)} {t} {rng.choice(pdus)}")
                else:
                    script.append("info")
            self.assertEqual(c_driver.run_script(script), model.run_script(script), f"round {round_no}")


if __name__ == "__main__":
    unittest.main()
