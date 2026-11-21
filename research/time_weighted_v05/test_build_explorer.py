"""Unit tests for build_explorer.py: synthetic cross network (known answers) and the real public layer (no CRTM data needed)."""
import json
import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import build_explorer as B  # noqa: E402
from research.time_weighted_v05 import test_experiment as TE  # noqa: E402


class Scenario(unittest.TestCase):
    def setUp(self):
        self.n = TE.net()
        self.T0 = self.n.times(mode="hop")
        self.x = self.n.sidx["X"]

    def test_closing_a_leaf_changes_nothing_for_the_others(self):
        a = self.n.sidx["A"]
        sc = B.scenario(self.T0, self.n.times(removed=[a], mode="hop"))
        self.assertEqual(sc["effect"]["n_disc"], 0)
        self.assertEqual(sc["cut"], [])
        self.assertEqual(sc["main_size"], 4)
        self.assertTrue(np.isnan(sc["dest"][a]))
        others = [i for i in range(self.n.n) if i != a]
        self.assertTrue(np.allclose(sc["dest"][others], 0.0))

    def test_closing_the_interchange_leaves_isolated_stations(self):
        sc = B.scenario(self.T0, self.n.times(removed=[self.x], mode="hop"))
        self.assertEqual(sc["effect"]["n_disc"], 12)
        self.assertEqual(sc["main_size"], 1)
        self.assertEqual(len(sc["cut"]), 3)  # ties between isolated stations: one is kept as 'main', the rest are cut
        self.assertTrue(np.isnan(sc["dest"]).all())

    def test_disabling_the_interchange_splits_the_network_in_two_pieces(self):
        sc = B.scenario(self.T0, self.n.times(disabled=[self.x], mode="hop"), exclude=self.x)
        self.assertEqual(sc["effect"]["n_disc"], 8)
        self.assertEqual(sc["main_size"], 3)  # the reference piece {A, B, X}; X itself reaches both pieces
        self.assertEqual(len(sc["cut"]), 2)
        self.assertEqual(sc["effect"]["dT"], 0.0)

    def test_clean_replaces_non_finite_values(self):
        self.assertIsNone(B.clean(float("nan")))
        self.assertIsNone(B.clean(float("inf")))
        self.assertEqual(B.clean(1.23456, 2), 1.23)
        self.assertIsNone(B.clean(None))


class PublicLayer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = json.loads(B.dumps(B.public_payload()))

    def test_replicates_v04_without_any_crtm_input(self):
        g1 = self.d["meta"]["gate_G1_replication_of_v04"]
        self.assertTrue(g1["ok"], g1)
        self.assertEqual(g1["got"]["fragmenting_closures"], 84)

    def test_shape(self):
        d = self.d
        self.assertEqual(len(d["ids"]), 242)
        self.assertEqual(len(d["close"]), 242)
        self.assertEqual(len(d["inter"]), len(d["inter_ids"]))
        self.assertEqual(len(d["inter_ids"]), 38)
        self.assertEqual(len(d["T0_hop"]), 242)
        self.assertTrue(all(len(r["dest"]) == 242 for r in d["close"]))
        self.assertEqual(sum(1 for c in d["inter"] if c["disc"] > 0), 1)

    def test_no_times_or_crtm_values_in_the_public_file(self):
        text = B.dumps(self.d)
        for key in ("seconds", "headway", "travel_time", "frequency", "calendar", "ride_times", "stop_times"):
            self.assertNotIn(f'"{key}"', text)

    def test_fragmenting_closures_report_a_cut_set(self):
        for c in self.d["close"]:
            self.assertEqual(c["n_cut"] > 0, c["disc"] > 0)
            self.assertEqual(c["n_cut"], len(c["cut"]))

    def test_committed_file_matches_a_fresh_build(self):
        committed = B.PUBLIC_OUT.read_text(encoding="utf-8")
        self.assertEqual(committed, B.dumps(self.d))


if __name__ == "__main__":
    unittest.main()
