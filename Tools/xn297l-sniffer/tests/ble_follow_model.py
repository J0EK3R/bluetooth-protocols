"""
Python model of the connection following logic firmware/src/ble_follow.c.

It has the same inputs and outputs as the C code, line by line, so the unit
tests can drive both with the same scripts (see run_script and the format
described in tests/c/follow_driver.c) and compare. All times are 32 bit
microsecond values that wrap, exactly like in C.

Core Specification Vol 6 Part B 4.5 (connection state), 5.1 (control procedures).
"""

import os
import sys

import ble_csa_model as csa

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "extcap"))
import ble_pdu  # noqa: E402  (path set above)

M32 = 0xFFFFFFFF
M16 = 0xFFFF

TIFS_US = 150
OWN_PPM = 50
JITTER_US = 16
RX_LEAD_US = 50
AA_DETECT_US = 40
RX_MARGIN_US = 30
IFS_LISTEN_US = 240
GAP_TOLERANCE_US = 20
ESTABLISH_EVENTS = 6
TRANSMIT_WINDOW_DELAY_US = 1250
INTERVAL_MIN, INTERVAL_MAX = 6, 3200
SCA_PPM = (500, 250, 150, 100, 75, 50, 30, 20)

FOLLOW_FORWARD, FOLLOW_WAIT, FOLLOW_CONNECT = 0x01, 0x02, 0x04
PKT_DIR_S2M, PKT_ANCHOR, PKT_GAP, PKT_CONTINUE = 0x01, 0x02, 0x04, 0x08
PLAN_UPDATED = 0x01
LOST_NONE, LOST_TIMEOUT, LOST_TERMINATE, LOST_ESTABLISH = 0, 1, 2, 3
TARGET_ANY = 2


def pkt_end_us(start_us: int, payload_len: int) -> int:
    """End of a packet on LE 1M: preamble + AA + header + payload + CRC, 8 us per byte."""
    return (start_us + (10 + payload_len) * 8) & M32


def instant_reached(counter: int, instant: int) -> bool:
    return ((counter - instant) & M16) < 0x8000


class FollowModel:
    """Mirror of struct ble_follow and its functions."""

    def __init__(self):
        self.has_target = False
        self.target = bytes(6)
        self.target_type = TARGET_ANY
        self.follow_conn = True
        self.follow_rsp = True
        self.adv_chsel = False
        self.connected = False
        self.lost_reason = LOST_NONE
        # connection fields (zero until a connection exists, like memset in C)
        self.access_address = self.crc_init = 0
        self.csa2 = False
        self.channel_id = 0
        self.hop = self.last_unmapped = 0
        self.chmap = bytes(5)
        self.sca = 0
        self.interval = self.latency = self.timeout = 0
        self.interval_us = 0
        self.encrypted = self.terminated = False
        self.upd = None                 # pending connection update (dict) or None
        self.map = None                 # pending channel map update (dict) or None
        self.next_counter = self.counter = 0
        self.ref_us = 0
        self.ref_counter = 0
        self.win_us = self.sync_us = self.last_valid_us = self.establish_limit_us = 0
        self.anchored = False
        self.pkt_index = 0
        self.md_master = self.md_slave = False
        self.prev_end_us = 0

    # --- configuration ---------------------------------------------------
    def set_target(self, target, target_type):
        self.connected = False
        self.adv_chsel = False
        if target is None:
            self.has_target = False
            return
        self.target = bytes(target)
        self.target_type = target_type
        self.has_target = True

    def set_options(self, follow_conn, follow_rsp):
        self.follow_conn, self.follow_rsp = follow_conn, follow_rsp

    # --- scanning ----------------------------------------------------------
    def _is_target(self, addr: bytes, random: bool) -> bool:
        return addr == self.target and (self.target_type == TARGET_ANY
                                        or self.target_type == (1 if random else 0))

    def _start_connection(self, pdu: bytes, start_us: int) -> bool:
        ci = ble_pdu.parse_connect_ind(pdu)
        if (ci is None or not INTERVAL_MIN <= ci["interval"] <= INTERVAL_MAX
                or not 5 <= ci["hop"] <= 16 or len(csa.used_channels(ci["chmap"])) < 2):
            return False
        end_us = pkt_end_us(start_us, ble_pdu.CONNECT_IND_LEN)
        self.connected = True
        self.lost_reason = LOST_NONE
        self.access_address = ci["access_address"]
        self.crc_init = ci["crc_init"]
        self.csa2 = bool(ci["ch_sel"]) and self.adv_chsel
        self.channel_id = csa.csa2_channel_id(ci["access_address"])
        self.hop = ci["hop"]
        self.last_unmapped = 0
        self.chmap = ci["chmap"]
        self.sca = ci["sca"]
        self.interval = ci["interval"]
        self.latency = ci["latency"]
        self.timeout = ci["timeout"]
        self.interval_us = ci["interval"] * 1250
        self.encrypted = self.terminated = False
        self.upd = self.map = None
        offset_us = TRANSMIT_WINDOW_DELAY_US + ci["win_offset"] * 1250
        self.next_counter = self.counter = 0
        self.ref_us = (end_us + offset_us) & M32
        self.ref_counter = 0
        self.win_us = ci["win_size"] * 1250
        self.sync_us = end_us
        self.last_valid_us = end_us
        self.establish_limit_us = (offset_us + self.win_us
                                   + ESTABLISH_EVENTS * self.interval_us) & M32
        self.anchored = False
        self.pkt_index = 0
        return True

    def on_adv(self, pdu: bytes, crc_ok: bool, start_us: int) -> int:
        if not self.has_target:
            return FOLLOW_FORWARD
        if len(pdu) < 8 or len(pdu) < 2 + pdu[1]:
            return 0
        payload = pdu[2:]
        length = pdu[1]
        tx_random, rx_random = bool(pdu[0] & 0x40), bool(pdu[0] & 0x80)
        wait = FOLLOW_WAIT if (self.follow_conn or self.follow_rsp) else 0
        ptype = pdu[0] & 0x0F
        if ptype in (ble_pdu.ADV_IND, ble_pdu.ADV_DIRECT_IND):
            if not self._is_target(payload[0:6], tx_random):
                return 0
            self.adv_chsel = bool(pdu[0] & 0x20)
            return FOLLOW_FORWARD | wait
        if ptype == ble_pdu.ADV_SCAN_IND:
            if not self._is_target(payload[0:6], tx_random):
                return 0
            return FOLLOW_FORWARD | (FOLLOW_WAIT if self.follow_rsp else 0)
        if ptype == ble_pdu.ADV_NONCONN_IND:
            return FOLLOW_FORWARD if self._is_target(payload[0:6], tx_random) else 0
        if ptype == ble_pdu.SCAN_RSP:
            return FOLLOW_FORWARD if self.follow_rsp and self._is_target(payload[0:6], tx_random) else 0
        if ptype == ble_pdu.SCAN_REQ:
            if length < 12 or not self.follow_rsp or not self._is_target(payload[6:12], rx_random):
                return 0
            return FOLLOW_FORWARD | FOLLOW_WAIT
        if ptype == ble_pdu.CONNECT_IND:
            if length < 12 or not self._is_target(payload[6:12], rx_random):
                return 0
            if crc_ok and self.follow_conn and self._start_connection(pdu, start_us):
                return FOLLOW_FORWARD | FOLLOW_CONNECT
            return FOLLOW_FORWARD
        return 0

    # --- connection events -----------------------------------------------------
    def _expected_start(self, counter: int) -> int:
        return (self.ref_us + ((counter - self.ref_counter) & M16) * self.interval_us) & M32

    def _apply_connection_update(self, counter: int):
        old_start = self._expected_start(counter)
        u = self.upd
        self.interval = u["interval"]
        self.interval_us = u["interval"] * 1250
        self.latency = u["latency"]
        self.timeout = u["timeout"]
        self.ref_us = (old_start + u["win_offset"] * 1250) & M32
        self.ref_counter = counter
        self.win_us = u["win_size"] * 1250
        self.upd = None

    def next_event(self):
        """Returns a plan dict (channel, counter, rx_on_us, rx_off_us, flags) or None if lost."""
        counter = self.next_counter
        flags = 0
        if not self.connected:
            return None
        if self.terminated:
            self.lost_reason = LOST_TERMINATE
            self.connected = False
            return None
        if self.map is not None and instant_reached(counter, self.map["instant"]):
            self.chmap = self.map["chmap"]
            self.map = None
            flags |= PLAN_UPDATED
        if self.upd is not None and instant_reached(counter, self.upd["instant"]):
            self._apply_connection_update(counter)
            flags |= PLAN_UPDATED
        start = self._expected_start(counter)
        limit = self.timeout * 10000 if self.anchored else self.establish_limit_us
        if ((start - self.last_valid_us) & M32) > limit:
            self.lost_reason = LOST_TIMEOUT if self.anchored else LOST_ESTABLISH
            self.connected = False
            return None
        if self.csa2:
            channel = csa.csa2_channel(self.channel_id, counter, self.chmap)
        else:
            channel, self.last_unmapped = csa.csa1_next(self.last_unmapped, self.hop, self.chmap)
        age_us = (start - self.sync_us) & M32
        widening = (SCA_PPM[self.sca & 7] + OWN_PPM) * age_us // 1000000 + JITTER_US
        widening = min(widening, self.interval_us // 2 - TIFS_US)
        plan = {"channel": channel, "counter": counter,
                "rx_on_us": (start - widening - RX_LEAD_US) & M32,
                "rx_off_us": (start + self.win_us + widening + AA_DETECT_US + RX_MARGIN_US) & M32,
                "flags": flags}
        self.counter = counter
        self.next_counter = (counter + 1) & M16
        self.pkt_index = 0
        self.md_master = self.md_slave = False
        return plan

    def _handle_control(self, from_master: bool, payload: bytes):
        if not payload:
            return
        opcode = payload[0]
        if opcode == ble_pdu.LL_CONNECTION_UPDATE_IND:
            upd = ble_pdu.parse_conn_update(payload) if from_master else None
            if upd is not None:
                ahead = (upd["instant"] - self.counter) & M16
                if 0 < ahead < 0x7FFF and INTERVAL_MIN <= upd["interval"] <= INTERVAL_MAX:
                    self.upd = upd
        elif opcode == ble_pdu.LL_CHANNEL_MAP_IND:
            cmu = ble_pdu.parse_chmap_update(payload) if from_master else None
            if cmu is not None:
                ahead = (cmu["instant"] - self.counter) & M16
                if 0 < ahead < 0x7FFF and len(csa.used_channels(cmu["chmap"])) >= 2:
                    self.map = cmu
        elif opcode == ble_pdu.LL_TERMINATE_IND:
            if len(payload) == 2:
                self.terminated = True
        elif opcode == ble_pdu.LL_START_ENC_REQ:
            if not from_master:
                self.encrypted = True

    def on_data_packet(self, pdu: bytes, crc_ok: bool, start_us: int):
        """Returns (flags, rx_off_us)."""
        master = self.pkt_index % 2 == 0
        payload_len = pdu[1] if len(pdu) >= 2 else 0
        end_us = pkt_end_us(start_us, payload_len)
        flags = 0 if master else PKT_DIR_S2M
        if self.pkt_index == 0:
            flags |= PKT_ANCHOR
            self.ref_us = start_us
            self.ref_counter = self.counter
            self.win_us = 0
            self.sync_us = start_us
            self.anchored = self.anchored or crc_ok
        else:
            gap = ((start_us - self.prev_end_us) & M32)
            gap = gap - (1 << 32) if gap >= 1 << 31 else gap
            gap -= TIFS_US
            if gap > GAP_TOLERANCE_US or gap < -GAP_TOLERANCE_US:
                flags |= PKT_GAP
        more_data = False
        if crc_ok and len(pdu) >= 2:
            self.last_valid_us = start_us
            more_data = bool(pdu[0] & ble_pdu.DATA_MD)
            if pdu[0] & 0x03 == ble_pdu.LLID_CONTROL and not self.encrypted \
                    and len(pdu) >= 2 + payload_len:
                self._handle_control(master, pdu[2:2 + payload_len])
        if master:
            self.md_master = more_data
        else:
            self.md_slave = more_data
        self.prev_end_us = end_us
        self.pkt_index += 1
        rx_off = 0
        if master or (crc_ok and not self.terminated and (self.md_master or self.md_slave)):
            flags |= PKT_CONTINUE
            rx_off = (end_us + IFS_LISTEN_US) & M32
        return flags, rx_off

    def info(self) -> str:
        return (f"info aa={self.access_address:08x} crc={self.crc_init:06x} int={self.interval} "
                f"lat={self.latency} to={self.timeout} map={self.chmap.hex()} hop={self.hop} "
                f"csa={2 if self.csa2 else 1} sca={self.sca} ctr={self.counter}")


def run_script(lines) -> list:
    """Execute a script (format: tests/c/follow_driver.c) and return the output lines."""
    model = FollowModel()
    out = []
    for line in lines:
        parts = line.split()
        if not parts:
            continue
        cmd, args = parts[0], parts[1:]
        if cmd == "init":
            model = FollowModel()
        elif cmd == "target":
            if args[0] == "off":
                model.set_target(None, 0)
            else:
                model.set_target(bytes.fromhex(args[0]), int(args[1]))
        elif cmd == "opts":
            model.set_options(args[0] != "0", args[1] != "0")
        elif cmd == "adv":
            out.append(f"adv {model.on_adv(bytes.fromhex(args[2]), args[0] != '0', int(args[1]))}")
        elif cmd == "next":
            plan = model.next_event()
            if plan is None:
                out.append(f"lost {model.lost_reason}")
            else:
                out.append(f"plan ch={plan['channel']} ctr={plan['counter']} "
                           f"on={plan['rx_on_us']} off={plan['rx_off_us']} fl={plan['flags']}")
        elif cmd == "pkt":
            flags, rx_off = model.on_data_packet(bytes.fromhex(args[2]), args[0] != "0", int(args[1]))
            out.append(f"pkt {flags} {rx_off}")
        elif cmd == "info":
            out.append(model.info())
        elif cmd == "csa1":
            chmap, hop, count = bytes.fromhex(args[0]), int(args[1]), int(args[2])
            last, seq = 0, []
            for _ in range(count):
                channel, last = csa.csa1_next(last, hop, chmap)
                seq.append(channel)
            out.append("csa1 " + " ".join(map(str, seq)))
        elif cmd == "csa2":
            cid = csa.csa2_channel_id(int(args[0], 16))
            chmap, first, count = bytes.fromhex(args[1]), int(args[2]), int(args[3])
            out.append("csa2 " + " ".join(str(csa.csa2_channel(cid, (first + i) & M16, chmap))
                                          for i in range(count)))
        elif cmd == "prn":
            out.append(f"prn {csa.csa2_prn_e(int(args[0], 16), int(args[1]))}")
        elif cmd == "freq":
            out.append(f"freq {csa.channel_frequency(int(args[0]))}")
    return out
