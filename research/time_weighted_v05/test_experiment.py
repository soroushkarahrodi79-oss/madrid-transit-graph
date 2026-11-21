"""Unit tests for experiment.py on synthetic networks with known answers (no GTFS data needed).

Cross network: L1 = A - X - B (100 s, 200 s), L2 = C - X - D (120 s, 80 s); X is the interchange.
Headways 600 s (L1) and 300 s (L2), wait factor 0.5 -> boarding waits 300 s and 150 s; transfer 180 s.
"""
import sys
import unittest
from pathlib import Path

import networkx as nx
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from research.time_weighted_v05 import experiment as E  # noqa: E402

STATIONS = {
    "A": {"name": "A", "lines": ["L1"]}, "B": {"name": "B", "lines": ["L1"]},
    "C": {"name": "C", "lines": ["L2"]}, "D": {"name": "D", "lines": ["L2"]},
    "X": {"name": "X", "lines": ["L1", "L2"]},
}
RIDES = [
    {"line": "L1", "a": "A", "b": "X", "seconds": 100.0, "source": "gtfs"},
    {"line": "L1", "a": "B", "b": "X", "seconds": 200.0, "source": "gtfs"},
    {"line": "L2", "a": "C", "b": "X", "seconds": 120.0, "source": "gtfs"},
    {"line": "L2", "a": "D", "b": "X", "seconds": 80.0, "source": "gtfs"},
]
TRANSFERS = [{"a": ("X", "L1"), "b": ("X", "L2")}]


def hw(s, l):
    return 600.0 if l == "L1" else 300.0


def net(**p):
    params = {"wait": 0.5, "transfer": 180.0, "speed": 1.0, **p}
    return E.Net(STATIONS, TRANSFERS, RIDES, hw, params)


def ix(n, *names):
    return [n.sidx[s] for s in names]


class Times(unittest.TestCase):
    def test_single_line_pair_pays_origin_wait_and_rides(self):
        n = net()
        T = n.times()
        a, b = ix(n, "A", "B")
        self.assertAlmostEqual(T[a, b], 300 + 100 + 200, places=5)
        self.assertAlmostEqual(T[b, a], 300 + 200 + 100, places=5)

    def test_transfer_adds_penalty_and_boarding_wait_of_new_line(self):
        n = net()
        T = n.times()
        a, c = ix(n, "A", "C")
        self.assertAlmostEqual(T[a, c], 300 + 100 + (180 + 150) + 120, places=5)  # 850
        self.assertAlmostEqual(T[c, a], 150 + 120 + (180 + 300) + 100, places=5)  # 850

    def test_interchange_origin_boards_on_the_needed_line_and_diagonal_is_nan(self):
        n = net()
        T = n.times()
        x, a = ix(n, "X", "A")
        self.assertAlmostEqual(T[x, a], 300 + 100, places=5)
        self.assertTrue(np.isnan(T[x, x]))

    def test_parameter_effects(self):
        a, c = ix(net(), "A", "C")
        self.assertAlmostEqual(net(wait=0.0, transfer=0.0).times()[a, c], 100 + 120, places=5)
        self.assertAlmostEqual(net(transfer=600.0).times()[a, c], 300 + 100 + (600 + 150) + 120, places=5)

    def test_hop_mode_counts_rides_and_ignores_transfers(self):
        n = net()
        T = n.times(mode="hop")
        a, c, b = ix(n, "A", "C", "B")
        self.assertEqual(T[a, c], 2.0)
        self.assertEqual(T[a, b], 2.0)

    def test_imputed_leg_scales_with_speed_multiplier(self):
        rides = [dict(r) for r in RIDES]
        rides[0] = {"line": "L1", "a": "A", "b": "X", "seconds": 0.0, "source": "imputed_arcgis_length_speed",
                    "length_m": 1000.0, "speed_kmh": 36.0}

        def mk(m):
            return E.Net(STATIONS, TRANSFERS, rides, hw, {"wait": 0.5, "transfer": 180.0, "speed": m})
        a, x = ix(mk(1.0), "A", "X")
        self.assertAlmostEqual(mk(1.0).times()[a, x], 300 + 100.0, places=5)
        self.assertAlmostEqual(mk(0.5).times()[a, x], 300 + 200.0, places=5)

    def test_scipy_agrees_with_networkx(self):
        n = net()
        G = nx.from_scipy_sparse_array(n.csr(), create_using=nx.DiGraph)
        T = n.times()
        ends = list(n.starts) + [n.S]
        for o in range(n.n):
            d = nx.single_source_dijkstra_path_length(G, n.S + o)
            for t in range(n.n):
                if t != o:
                    best = min(d.get(i, np.inf) for i in range(ends[t], ends[t + 1]))
                    self.assertAlmostEqual(T[o, t], best, places=6)


class Disruptions(unittest.TestCase):
    def test_closure_of_the_interchange_disconnects_every_remaining_pair(self):
        n = net()
        e = E.effect(n.times(), n.times(removed=ix(n, "X")))
        self.assertEqual(e["n_disc"], 12)  # 4 remaining stations -> 12 ordered pairs, all need X
        self.assertEqual(e["n_conn"], 0)

    def test_through_running_keeps_same_line_pairs_at_summed_leg_time(self):
        n = net()
        T0 = n.times()
        x = ix(n, "X")
        Tt = n.times(removed=x, through=True)
        a, b, c, d = ix(n, "A", "B", "C", "D")
        self.assertAlmostEqual(Tt[a, b], 300 + 300, places=5)  # 100 + 200 passed through
        self.assertAlmostEqual(Tt[c, d], 150 + 200, places=5)
        self.assertTrue(np.isinf(Tt[a, c]))  # no line change at the closed station
        e = E.effect(T0, Tt)
        self.assertEqual(e["n_disc"], 8)  # 12 ordered pairs, the 4 same-line ones stay connected
        self.assertAlmostEqual(e["dT"], 0.0, places=5)

    def test_interchange_disabled_blocks_transfers_only(self):
        n = net()
        T0 = n.times()
        Ts = n.times(disabled=ix(n, "X"))
        a, b, c = ix(n, "A", "B", "C")
        self.assertAlmostEqual(Ts[a, b], T0[a, b], places=5)
        self.assertTrue(np.isinf(Ts[a, c]))
        self.assertEqual(E.effect(T0, Ts)["n_disc"], 8)  # {A,B} x {C,D} in both directions

    def test_effect_is_never_negative_for_removals(self):
        n = net()
        T0 = n.times()
        for s in range(n.n):
            self.assertGreaterEqual(E.effect(T0, n.times(removed=[s]))["min_delta"], -1e-9)

    def test_removing_an_unused_detour_leaves_remaining_pairs_unchanged(self):
        st = {"A": {"name": "A", "lines": ["L1", "L2"]}, "B": {"name": "B", "lines": ["L1", "L2"]},
              "C": {"name": "C", "lines": ["L2"]}}
        rides = [{"line": "L1", "a": "A", "b": "B", "seconds": 100.0, "source": "gtfs"},
                 {"line": "L2", "a": "A", "b": "C", "seconds": 60.0, "source": "gtfs"},
                 {"line": "L2", "a": "B", "b": "C", "seconds": 60.0, "source": "gtfs"}]
        n = E.Net(st, [], rides, lambda s, l: 0.0, {"wait": 0.0, "transfer": 0.0, "speed": 1.0})
        T0 = n.times()
        a, b, c = n.sidx["A"], n.sidx["B"], n.sidx["C"]
        self.assertAlmostEqual(T0[a, b], 100.0, places=5)
        self.assertAlmostEqual(E.effect(T0, n.times(removed=[c]))["dT"], 0.0, places=5)


class Statistics(unittest.TestCase):
    def test_classification_boundaries(self):
        self.assertEqual(E.classify(0.90, 7), "ABSTAIN")
        self.assertEqual(E.classify(0.95, 6), "INCONCLUSIVE")
        self.assertEqual(E.classify(0.69, 9), "ADDED_VALUE")
        self.assertEqual(E.classify(0.70, 3), "INCONCLUSIVE")
        self.assertEqual(E.classify(0.85, 9, hi=0.80), "ABSTAIN")

    def test_top_ids_is_deterministic_with_ties(self):
        self.assertEqual(E.top_ids([1, 3, 3, 2], 2), {1, 2})
        self.assertEqual(E.top_ids([5, 5, 5, 1], 2), {0, 1})

    def test_rho_perfect_and_reversed(self):
        self.assertAlmostEqual(E.rho([1, 2, 3, 4], [10, 20, 30, 40]), 1.0)
        self.assertAlmostEqual(E.rho([1, 2, 3, 4], [4, 3, 2, 1]), -1.0)

    def test_holm_adjustment(self):
        adj = E.holm(np.array([0.01, 0.04, 0.03]))
        self.assertTrue(np.allclose(adj, [0.03, 0.06, 0.06]))

    def test_permutation_p_is_small_for_perfect_ranking(self):
        x = np.arange(30.0)
        self.assertLess(E.perm_p(x, x, n=500, rng=np.random.default_rng(1)), 0.01)

    def test_seeded_bootstrap_is_reproducible(self):
        x, y = np.arange(30.0), np.arange(30.0) ** 2
        a = E.bootstrap_ci(x, y, n=200, rng=np.random.default_rng(7))
        b = E.bootstrap_ci(x, y, n=200, rng=np.random.default_rng(7))
        self.assertEqual(a, b)


class Grid(unittest.TestCase):
    def test_grid_has_the_preregistered_178_cells_plus_the_hop_replication_cell(self):
        cells = E.cells_grid()
        self.assertEqual(len(cells), 178 + 1)
        self.assertEqual(sum(E.is_central(c) for c in cells), 1)
        self.assertEqual(sum(c["band"] == "weekday_peak" and c["l3"] == "imputed" and c["mode"] == "time"
                             and c["closure"] == "full" for c in cells), 162)


if __name__ == "__main__":
    unittest.main()
