"""Correctness tests on small synthetic networks with known answers, plus the real snapshot.
Run: .venv\\Scripts\\python -m unittest discover -s research/transfer_aware_v02 -v
"""
import json
import sys
import unittest
from pathlib import Path

import networkx as nx

sys.path.insert(0, str(Path(__file__).resolve().parent))
import experiment as E  # noqa: E402


def mk(lines):
    """lines: {line: [station, ...] or ([...], 'loop')} -> (stations, connections)."""
    stations, conns = {}, {}
    for l, seq in lines.items():
        loop = isinstance(seq, tuple)
        seq = seq[0] if loop else seq
        pairs = list(zip(seq, seq[1:])) + ([(seq[-1], seq[0])] if loop else [])
        for s in seq:
            stations.setdefault(s, {"name": s, "lines": [], "lon": 0.0, "lat": 0.0})["lines"].append(l)
        for u, v in pairs:
            conns.setdefault(frozenset((u, v)), {"id": f"{u}--{v}", "source": u, "target": v, "lines": []})["lines"].append(l)
    for s in stations.values():
        s["lines"].sort()
    for c in conns.values():
        c["lines"].sort()
    return stations, list(conns.values())


def same_station(stations):
    return E.fusion_transfers(stations)


def rt(b, stations, o, d, w):
    """(primary, secondary) of the optimal cost for one pair, or None if unreachable."""
    ids = sorted(stations)
    a, z = sorted((o, d), key=ids.index)
    pairs = E.all_pairs_optimal(b, stations, w, "B")
    if (a, z) not in pairs:
        return None
    return divmod(pairs[(a, z)][0], E.BIG)


class Synthetic(unittest.TestCase):
    def setUp(self):
        # L1: a-x-b ; L2: c-x-d  (cross at x)
        self.st, self.cn = mk({"L1": ["a", "x", "b"], "L2": ["c", "x", "d"]})
        self.b = E.build_model_b(self.st, self.cn, same_station(self.st))

    def test_ride_and_transfer_counts(self):
        self.assertEqual(rt(self.b, self.st, "a", "b", "w_R"), (2, 0))  # same line, no transfer
        self.assertEqual(rt(self.b, self.st, "a", "c", "w_R"), (2, 1))  # one transfer at x
        self.assertEqual(rt(self.b, self.st, "a", "c", "w_T"), (1, 2))  # (transfers, rides)

    def test_origin_with_multiple_line_states_boards_free(self):
        self.assertEqual(rt(self.b, self.st, "x", "d", "w_R"), (1, 0))
        self.assertEqual(rt(self.b, self.st, "x", "a", "w_R"), (1, 0))

    def test_no_transfers_means_separate_components(self):
        b0 = E.build_model_b(self.st, self.cn, [])
        self.assertEqual(nx.number_connected_components(b0), 2)
        self.assertIsNone(rt(b0, self.st, "a", "c", "w_R"))
        # x is in both line components; pairs: {a,x},{x,b},{a,b},{c,x},{x,d},{c,d} = 6
        self.assertEqual(E.reachable_pair_count(b0, E.station_b), 6)
        self.assertEqual(E.reachable_pair_count(self.b, E.station_b), 10)

    def test_model_a_matches_projection(self):
        a = E.build_model_a(self.st, self.cn)
        ap = E.all_pairs_optimal(a, self.st, None, "A")
        rp = E.all_pairs_optimal(self.b, self.st, "w_R", "B")
        self.assertEqual({k: v[0] for k, v in ap.items()}, {k: divmod(v[0], E.BIG)[0] for k, v in rp.items()})

    def test_cross_station_transfer(self):
        st, cn = mk({"L1": ["a", "x1", "b"], "L2": ["c", "x2", "d"]})
        t = [E.transfer(("x1", "L1"), ("x2", "L2"), "test", "confirmed", "TEST")]
        b = E.build_model_b(st, cn, t)
        self.assertEqual(rt(b, st, "a", "c", "w_R"), (2, 1))
        self.assertEqual(rt(b, st, "x1", "x2", "w_R"), (0, 1))  # pure transfer link, zero rides
        self.assertIsNone(rt(E.build_model_b(st, cn, []), st, "a", "c", "w_R"))

    def test_transfer_link_is_not_equivalent_to_an_ordinary_edge_in_a(self):
        # A transfer edge adds 0 ride edges; an ordinary edge x1-x2 added to Model A adds 1 hop.
        st, cn = mk({"L1": ["a", "x1", "b"], "L2": ["c", "x2", "d"]})
        t = [E.transfer(("x1", "L1"), ("x2", "L2"), "test", "confirmed", "TEST")]
        b = E.build_model_b(st, cn, t)
        a = E.build_model_a(st, cn)
        a.add_edge("x1", "x2")
        hops = {k: v[0] for k, v in E.all_pairs_optimal(a, st, None, "A").items()}
        self.assertEqual(hops[("a", "c")], 3)                       # a-x1, x1-x2, x2-c
        self.assertEqual(rt(b, st, "a", "c", "w_R"), (2, 1))        # 2 rides + 1 transfer
        self.assertEqual(hops[("x1", "x2")], 1)
        self.assertEqual(rt(b, st, "x1", "x2", "w_R"), (0, 1))      # 0 rides
        # one state-level transfer edge = one physical station pair; a 2-state station gives 2 edges for 1 pair
        st2, cn2 = mk({"L1": ["a", "m", "b"], "L2": ["c", "m", "d"], "L3": ["e", "z"]})
        t2 = [E.transfer(("m", "L1"), ("z", "L3"), "t", "c", "s"), E.transfer(("m", "L2"), ("z", "L3"), "t", "c", "s")]
        b2 = E.build_model_b(st2, cn2, t2)
        cross = [(u, v) for u, v, d in b2.edges(data=True) if d["edge_type"] == E.TRANSFER and u[0] != v[0]]
        self.assertEqual(len(cross), 2)
        self.assertEqual(len({frozenset((u[0], v[0])) for u, v in cross}), 1)

    def test_rides_vs_transfers_tradeoff(self):
        # direct line A: o-a1-a2-a3-d (4 rides, 0 transfers); B: o-m ; C: m-d -> 2 rides, 1 transfer at m
        st, cn = mk({"A": ["o", "a1", "a2", "a3", "d"], "B": ["o", "m"], "C": ["m", "d"]})
        b = E.build_model_b(st, cn, same_station(st))
        self.assertEqual(rt(b, st, "o", "d", "w_R"), (2, 1))
        self.assertEqual(rt(b, st, "o", "d", "w_T"), (0, 4))

    def test_circular_line(self):
        st, cn = mk({"L": (["p0", "p1", "p2", "p3"], "loop")})
        a = E.build_model_a(st, cn)
        self.assertEqual(a.number_of_edges(), 4)
        b = E.build_model_b(st, cn, [])
        chk = {c.split(": ", 1)[1]: ok for c, ok, _ in E.validate_model_b(a, b, st, cn, [], "t")}
        self.assertTrue(chk["each line's ride subgraph is connected and is a tree or a simple cycle"])
        self.assertEqual(rt(b, st, "p0", "p2", "w_R"), (2, 0))
        pairs = E.all_pairs_optimal(b, st, "w_R", "B")
        self.assertEqual(len(pairs[("p0", "p2")][1]), 2)  # both ways round the loop are optimal

    def test_shared_segment_is_one_edge_in_a_two_ride_edges_in_b(self):
        st, cn = mk({"L1": ["a", "m", "n", "b"], "L2": ["c", "m", "n", "d"]})
        a = E.build_model_a(st, cn)
        b = E.build_model_b(st, cn, same_station(st))
        self.assertEqual(a.number_of_edges(), 5)  # a-m, m-n (shared), n-b, c-m, n-d
        self.assertEqual(sum(1 for *_, d in b.edges(data=True) if d["edge_type"] == E.RIDE), 6)
        own = E.betweenness_from_pairs(E.all_pairs_optimal(a, st, None, "A"), E.station_a, len(st))
        ref = nx.betweenness_centrality(a)
        for s in a:
            self.assertAlmostEqual(own.get(s, 0.0), ref[s])

    def test_betweenness_path_graph(self):
        st, cn = mk({"L": ["a", "b", "c"]})
        a = E.build_model_a(st, cn)
        own = E.betweenness_from_pairs(E.all_pairs_optimal(a, st, None, "A"), E.station_a, 3)
        self.assertAlmostEqual(own["b"], 1.0)  # b is on the only a-c path; normaliser (3-1)(3-2)/2 = 1
        self.assertNotIn("a", own)

    def test_articulation(self):
        a = E.build_model_a(self.st, self.cn)
        self.assertEqual(set(E.physical_articulation(a, self.st, E.station_a)), {"x"})
        self.assertEqual(set(E.physical_articulation(self.b, self.st, E.station_b)), {"x"})
        self.assertEqual(set(nx.articulation_points(a)), {"x"})

    def test_invalid_inputs_rejected(self):
        with self.assertRaises(ValueError):  # transfer to unknown state
            E.build_model_b(self.st, self.cn, [E.transfer(("a", "L1"), ("a", "L9"), "t", "c", "s")])
        dup = same_station(self.st)
        with self.assertRaises(ValueError):  # duplicate transfer edge
            E.build_model_b(self.st, self.cn, dup + dup[:1])
        with self.assertRaises(ValueError):  # duplicate connection
            E.build_model_a(self.st, self.cn + self.cn[:1])

    def test_validator_catches_corruption(self):
        a = E.build_model_a(self.st, self.cn)
        tr = same_station(self.st)
        b = E.build_model_b(self.st, self.cn, tr)
        b.add_edge(("a", "L1"), ("c", "L2"), edge_type=E.RIDE, line="L1")  # inter-line ride edge
        failed = [c for c, ok, _ in E.validate_model_b(a, b, self.st, self.cn, tr, "t") if not ok]
        self.assertTrue(any("inter-line ride" in c for c in failed))

    def test_path_consistency_validator(self):
        for w, obj in (("w_R", "R"), ("w_T", "T")):
            pairs = E.all_pairs_optimal(self.b, self.st, w, "B")
            self.assertEqual(E.validate_paths(self.b, pairs, obj), 0)


class Spearman(unittest.TestCase):
    def test_known(self):
        self.assertAlmostEqual(E.spearman([1, 2, 3, 4], [10, 20, 30, 40]), 1.0)
        self.assertAlmostEqual(E.spearman([1, 2, 3, 4], [4, 3, 2, 1]), -1.0)


class RealSnapshot(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.st, cls.cn = E.load_snapshot()
        cls.audit = E.load_audit()
        cls.a = E.build_model_a(cls.st, cls.cn)

    def test_baseline_preserved(self):
        man = json.loads((E.DATA / "manifest.json").read_text("utf-8"))
        for f, m in man["files"].items():
            self.assertEqual(E.sha256(E.DATA / f), m["sha256"], f)
        self.assertEqual((self.a.number_of_nodes(), self.a.number_of_edges(), nx.number_connected_components(self.a)),
                         (242, 277, 1))

    def test_model_b_structure_valid(self):
        tr = E.fusion_transfers(self.st, self.audit)
        b = E.build_model_b(self.st, self.cn, tr)
        failed = [(c, d) for c, ok, d in E.validate_model_b(self.a, b, self.st, self.cn, tr, "B1") if not ok]
        self.assertEqual(failed, [])
        self.assertEqual(b.number_of_nodes(), 291)

    @unittest.skipUnless(E.load_audit(), "local CRTM audit not present")
    def test_cross_name_transfers_are_the_documented_ones(self):
        tr = E.cross_name_transfers(self.st, self.audit)
        got = {frozenset((t["a"], t["b"])) for t in tr}
        self.assertEqual(got, {
            frozenset((("embajadores", "L3"), ("acacias", "L5"))),
            frozenset((("callao", "L3"), ("santo-domingo", "L2"))),
            frozenset((("callao", "L5"), ("santo-domingo", "L2")))})
        for t in tr:
            self.assertTrue(t["evidence"] and t["confidence"] and t["source"])


if __name__ == "__main__":
    unittest.main()
