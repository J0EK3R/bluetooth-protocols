#!/usr/bin/env python3
"""
Tests of the channel selection algorithms #1 and #2.

Test vectors: Bluetooth Core Specification Vol 6 Part C 3 ("Channel selection
algorithm #2 sample data"): access address 0x8E89BED6, channel identifier
0x305F.
  Sample 1 (all 37 channels used): event counter 0, 1, 2, 3 -> prn_e 56857, 1685,
           38301, 27475 -> channels 25, 20, 6, 21.
  Sample 2 (9 used channels 9,10,21,22,23,33,34,35,36): event counter 6, 7, 8 ->
           prn_e 10975, 5490, 46970 -> channels 23, 9, 34.
The values were verified independently by the reviewer (separate
re-implementation from the specification); the algorithm reproduces these 16
bit pseudo random numbers exactly.
Algorithm #1 has no sample data in the specification; it is tested with hand
calculated sequences and properties.

Every vector is checked on the Python model AND on the C code (host build via
tests/c_driver.py; skipped without a C compiler).
"""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "extcap"))

import ble_csa_model as csa  # noqa: E402
import ble_phdr  # noqa: E402
import c_driver  # noqa: E402

SPEC_AA = 0x8E89BED6
SAMPLE2_USED = [9, 10, 21, 22, 23, 33, 34, 35, 36]
FULL_MAP = csa.map_to_bytes(range(37))


class Csa2SpecVectors(unittest.TestCase):
    def test_channel_identifier(self):
        self.assertEqual(csa.csa2_channel_id(SPEC_AA), 0x305F)

    def test_sample1_all_channels(self):
        for counter, prn_e, channel in ((0, 56857, 25), (1, 1685, 20), (2, 38301, 6), (3, 27475, 21)):
            self.assertEqual(csa.csa2_prn_e(0x305F, counter), prn_e)
            self.assertEqual(csa.csa2_channel(0x305F, counter, FULL_MAP), channel)

    def test_sample2_nine_channels(self):
        chmap = csa.map_to_bytes(SAMPLE2_USED)
        for counter, prn_e, channel in ((6, 10975, 23), (7, 5490, 9), (8, 46970, 34)):
            self.assertEqual(csa.csa2_prn_e(0x305F, counter), prn_e)
            self.assertEqual(csa.csa2_channel(0x305F, counter, chmap), channel)

    def test_event_counter_wraps_at_16_bit(self):
        self.assertEqual(csa.csa2_channel(0x305F, 0x10000, FULL_MAP),
                         csa.csa2_channel(0x305F, 0, FULL_MAP))

    def test_only_used_channels_are_returned(self):
        chmap = csa.map_to_bytes(SAMPLE2_USED)
        for aa in (SPEC_AA, 0x12345678, 0xAF9A2B01):
            cid = csa.csa2_channel_id(aa)
            for counter in range(0, 70000, 13):
                self.assertIn(csa.csa2_channel(cid, counter, chmap), SAMPLE2_USED)


class Csa1Tests(unittest.TestCase):
    @staticmethod
    def sequence(chmap, hop, count):
        last, out = 0, []
        for _ in range(count):
            channel, last = csa.csa1_next(last, hop, chmap)
            out.append(channel)
        return out

    def test_full_map_hand_calculated(self):
        # (0+7)%37=7, 14, 21, 28, 35, 42%37=5, 12 ...
        self.assertEqual(self.sequence(FULL_MAP, 7, 7), [7, 14, 21, 28, 35, 5, 12])

    def test_remapping_hand_calculated(self):
        # used channels (ascending): 2 4 6 8 10 12 20 30 -> 8 of them
        # unmapped 5 -> 5 % 8 = 5 -> used[5] = 12;  10 is used;  15 -> 7 -> 30;
        # 20 is used;  25 -> 1 -> 4;  30 is used;  35 -> 3 -> 8;  40 % 37 = 3 -> 3 -> 8
        chmap = csa.map_to_bytes([2, 4, 6, 8, 10, 12, 20, 30])
        self.assertEqual(self.sequence(chmap, 5, 8), [12, 10, 30, 20, 4, 30, 8, 8])

    def test_every_hop_visits_all_channels(self):
        for hop in range(5, 17):
            self.assertEqual(sorted(self.sequence(FULL_MAP, hop, 37)), list(range(37)))

    def test_only_used_channels_are_returned(self):
        chmap = csa.map_to_bytes(SAMPLE2_USED)
        for hop in range(5, 17):
            for channel in self.sequence(chmap, hop, 200):
                self.assertIn(channel, SAMPLE2_USED)


class FrequencyTests(unittest.TestCase):
    def test_matches_pcap_rf_channel_numbers(self):
        # RF channel number of the PHDR = (MHz - 2402) / 2 = (FREQUENCY - 2) / 2
        for index in range(40):
            self.assertEqual((csa.channel_frequency(index) - 2) // 2, ble_phdr.rf_channel(index))


@unittest.skipIf(c_driver.driver_path() is None, "no host C compiler")
class CImplementationMatchesModel(unittest.TestCase):
    """The firmware C code gives the same results as the Python model."""

    def test_spec_vectors(self):
        out = c_driver.run_script([
            "prn 305f 0", "prn 305f 1", "prn 305f 2", "prn 305f 6", "prn 305f 7", "prn 305f 8",
            f"csa2 8E89BED6 {FULL_MAP.hex()} 0 3",
            f"csa2 8E89BED6 {csa.map_to_bytes(SAMPLE2_USED).hex()} 6 3"])
        self.assertEqual(out, ["prn 56857", "prn 1685", "prn 38301", "prn 10975", "prn 5490",
                               "prn 46970", "csa2 25 20 6", "csa2 23 9 34"])

    def test_many_vectors(self):
        import random
        rng = random.Random(1234)
        script = []
        for _ in range(300):
            used = rng.sample(range(37), rng.randint(2, 37))
            chmap = csa.map_to_bytes(used).hex()
            first = rng.randint(0, 65535)           # includes ranges that wrap past 65535
            script.append(f"csa2 {rng.getrandbits(32):08X} {chmap} {first} 40")
            script.append(f"csa1 {chmap} {rng.randint(5, 16)} 60")
        script += [f"freq {i}" for i in range(40)]
        script += [f"prn {rng.getrandbits(16):04x} {rng.randint(0, 65535)}" for _ in range(200)]
        import ble_follow_model
        self.assertEqual(c_driver.run_script(script), ble_follow_model.run_script(script))


if __name__ == "__main__":
    unittest.main()
