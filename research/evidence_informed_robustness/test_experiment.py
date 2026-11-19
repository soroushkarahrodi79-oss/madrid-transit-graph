"""Focused tests for the evidence model and the common route evaluator."""

from itertools import product
import json
import unittest

import networkx as nx

from research.evidence_informed_robustness import experiment as exp
from research.network_robustness_v04 import experiment as v04
from research.transfer_aware_v02 import experiment as v02


def control(*segments):
    stations = {}
    connections = []
    for i, (a, b, line) in enumerate(segments):
        for sid in (a, b):
            station = stations.setdefault(sid, {"name": sid, "lines": []})
            if line not in station["lines"]:
                station["lines"].append(line)
        connections.append({"id": str(i), "source": a, "target": b, "lines": [line]})
    return stations, v02.build_model_b(stations, connections, v02.fusion_transfers(stations))


def walk(a, a_lines, b, b_lines):
    return {"endpoints": [{"station": a, "lines": a_lines}, {"station": b, "lines": b_lines}]}


def split(stations, b1):
    return exp.ride_sections(b1, stations, [
        {"station": "x", "line": "L7", "sections": {"L7A": "a", "L7B": "b"}}
    ])


def score(graph, stations, pair, objective="R", sections=None):
    route_graph = exp.routing_graph(graph)
    cost, paths = exp.optimal_pairs(route_graph, objective, exp.model_states(graph, stations))[pair]
    return exp.score_paths(route_graph, pair, paths, cost, objective, sections or {})


class EvidenceTests(unittest.TestCase):
    def test_cross_name_walk_is_separate_and_boarding_is_free(self):
        stations, b1 = control(("a", "x", "L1"), ("b", "y", "L2"))
        e = exp.build_evidence_model(b1, stations, {}, {}, [walk("x", ["L1"], "y", ["L2"])])
        self.assertNotIn(("a", "b"), exp.connected_pairs(b1))
        counts, physical, _ = score(e, stations, ("a", "b"))
        self.assertEqual(counts, (2, 1, 1, 1, 1))
        self.assertEqual(physical, {("a", "x", "y", "b")})
        self.assertEqual(score(e, stations, ("b", "x"))[0], (1, 1, 0, 0, 1))

    def test_internal_change_splits_through_rides_and_preserves_cost(self):
        stations, b1 = control(("a", "x", "L7"), ("x", "b", "L7"))
        sections, splits = split(stations, b1)
        e = exp.build_evidence_model(b1, stations, sections, splits, [])
        exp.verify_lift(b1, e, sections, splits)
        self.assertEqual(e[("x", "L7", "L7A")][("x", "L7", "L7B")]["edge_type"], exp.REBOARD)
        self.assertFalse(nx.has_path(nx.subgraph_view(e, filter_edge=lambda u, v: e[u][v]["edge_type"] != exp.REBOARD),
                                     ("a", "L7"), ("b", "L7")))
        for objective in v04.OBJECTIVES:
            self.assertEqual(score(e, stations, ("a", "b"), objective, sections),
                             score(b1, stations, ("a", "b"), objective, sections))
            self.assertEqual(score(e, stations, ("a", "b"), objective, sections)[0], (2, 0, 0, 1, 0))
            counts, physical, service = score(e, stations, ("a", "x"), objective, sections)
            self.assertEqual(counts, (1, 0, 0, 0, 0))
            self.assertEqual((len(physical), len(service)), (1, 1))

    def test_commercial_line_change_means_reboarding_between_rides(self):
        stations, b1 = control(("a", "x", "L1"), ("b", "x", "L2"))
        for objective in v04.OBJECTIVES:
            self.assertEqual(score(b1, stations, ("a", "b"), objective)[0], (2, 1, 1, 1, 0))
            self.assertEqual(score(b1, stations, ("a", "x"), objective)[0], (1, 0, 0, 0, 0))

    def test_multiline_disruption_preserves_walk_and_rides(self):
        stations, b1 = control(("a", "x", "L1"), ("b", "x", "L2"), ("c", "x", "L3"), ("d", "y", "L4"))
        e = exp.build_evidence_model(b1, stations, {}, {}, [walk("x", ["L1"], "y", ["L4"])])
        disrupted = v04.disable_interchange(e, "x")
        self.assertEqual(e.number_of_edges() - disrupted.number_of_edges(), 3)
        self.assertIn(("a", "d"), exp.connected_pairs(disrupted))
        self.assertNotIn(("a", "b"), exp.connected_pairs(disrupted))
        self.assertEqual(set(disrupted), set(e))

    def test_ride_cost_can_increase_with_reachability_preserved(self):
        stations, b1 = control(("a", "x", "L1"), ("x", "y", "L1"), ("y", "z", "L1"),
                               ("b", "x", "L2"), ("b", "z", "L2"))
        disrupted = v04.disable_interchange(b1, "x")
        self.assertEqual(exp.connected_pairs(disrupted), exp.connected_pairs(b1))
        before = score(b1, stations, ("a", "b"))[0]
        after = score(disrupted, stations, ("a", "b"))[0]
        self.assertEqual((before[:2], after[:2]), ((2, 1), (4, 1)))

    def test_equal_station_sequences_can_be_distinct_ridden_services(self):
        stations, b1 = control(("a", "x", "L1"), ("x", "b", "L1"), ("a", "x", "L2"), ("x", "b", "L2"))
        _, physical, service = score(b1, stations, ("a", "b"))
        self.assertEqual(physical, {("a", "x", "b")})
        self.assertEqual(len(service), 2)

    def test_same_line_walk_between_rides_requires_a_new_train(self):
        stations, b1 = control(("a", "x", "L1"), ("x", "y", "L1"), ("y", "b", "L1"))
        e = exp.build_evidence_model(b1, stations, {}, {}, [walk("x", ["L1"], "y", ["L1"])])
        self.assertEqual(score(b1, stations, ("a", "b"))[0], (3, 0, 0, 0, 0))
        self.assertEqual(score(e, stations, ("a", "b"))[0], (2, 0, 0, 1, 1))
        self.assertEqual(score(e, stations, ("x", "y"))[0], (0, 0, 0, 0, 1))
        self.assertEqual(e.number_of_edges(), b1.number_of_edges() + 1)

    def test_neutral_edges_match_an_exhaustive_small_graph_oracle(self):
        stations, b1 = control(("a", "x", "L7"), ("x", "b", "L7"), ("a", "y", "L1"),
                               ("y", "z", "L1"), ("b", "z", "L1"))
        sections, splits = split(stations, b1)
        e = exp.build_evidence_model(b1, stations, sections, splits, [walk("y", ["L1"], "z", ["L1"])])
        states = exp.model_states(e, stations)
        graph = exp.routing_graph(e)
        for objective in v04.OBJECTIVES:
            weight = f"w_{objective}"
            for (o, d), (cost, paths) in exp.optimal_pairs(graph, objective, states).items():
                candidates = {
                    tuple(path): sum(graph[u][v][weight] for u, v in zip(path, path[1:]))
                    for a, b in product(states[o], states[d])
                    for path in nx.all_simple_paths(graph, a, b)
                }
                expected = min(candidates.values())
                self.assertEqual(cost, expected)
                self.assertEqual(set(paths), {path for path, cost in candidates.items() if cost == expected})

    def test_projection_does_not_fuse_a_disrupted_interchange(self):
        stations, b1 = control(("a", "x", "L1"), ("b", "x", "L2"))
        e = exp.build_evidence_model(b1, stations, {}, {}, [])
        states = exp.model_states(e, stations)
        disrupted = v04.disable_interchange(e, "x")
        self.assertEqual(set(exp.optimal_pairs(disrupted, "R", states)), {("a", "x"), ("b", "x")})
        self.assertEqual(v04.connectivity(disrupted, v02.station_b, len(states))["disconnected_pairs"], 1)

    def test_removal_cannot_improve_cost_and_reversed_comparison_is_rejected(self):
        stations, b1 = control(("a", "x", "L1"), ("x", "y", "L1"), ("y", "z", "L1"),
                               ("b", "x", "L2"), ("b", "z", "L2"))
        states, before, scores = exp.prepare(b1, stations, {})
        disrupted = v04.disable_interchange(b1, "x")
        after = exp.optimal_pairs(disrupted, "R", states)
        _, events, _ = exp.compare_paths(disrupted, before["R"], scores["R"], after, "R", {})
        self.assertTrue(events["a", "b"] & exp.WORSENED)
        disrupted_scores = {
            pair: exp.score_paths(disrupted, pair, paths, cost, "R", {})
            for pair, (cost, paths) in after.items()
        }
        with self.assertRaisesRegex(RuntimeError, "optimum improved"):
            exp.compare_paths(b1, after, disrupted_scores, before["R"], "R", {})


class SnapshotTests(unittest.TestCase):
    def test_real_model_identities_interventions_and_sol_isolation(self):
        manifest = json.loads((exp.HERE / "evidence.json").read_bytes())
        stations, b1, interchanges = exp.load_control(manifest)
        sections, splits = exp.ride_sections(b1, stations, manifest["mandatory_train_changes"])
        confirmed = manifest["confirmed_walks"]
        e = exp.build_evidence_model(b1, stations, sections, splits, confirmed)
        sol = exp.build_evidence_model(b1, stations, sections, splits, confirmed + manifest["sensitivity_walks"])
        self.assertEqual(set(e), set(sol))
        self.assertEqual({n[0] for n in sol}, set(stations))
        self.assertEqual(len(interchanges), 38)
        self.assertEqual(len(exp.connected_pairs(b1)), 29161)
        self.assertEqual(len(exp.connected_pairs(e)), 29161)
        self.assertEqual(len(exp.connected_pairs(sol)), 29161)
        self.assertEqual(len(interchanges) * len(exp.connected_pairs(b1)), 1108118)
        self.assertEqual(exp.graph_counts(e), {
            "physical_stations": 242, "states": 294, "ride_edges": 280,
            "same_station_commercial_transfer_edges": 61, "mandatory_train_change_edges": 3,
            "pedestrian_state_edges": 3, "pedestrian_station_links": 2,
        })
        self.assertEqual(exp.graph_counts(sol)["pedestrian_state_edges"], 9)
        self.assertEqual(exp.graph_counts(sol)["ride_edges"], 280)
        self.assertEqual(e[("sol", "L1")][("gran-via", "L1")]["edge_type"], v02.RIDE)
        self.assertEqual({edge["edge_type"] for edge in sol[("sol", "L1")][("gran-via", "L1")].values()},
                         {exp.WALK, v02.RIDE})
        for graph in (e, sol):
            bridges = {frozenset(edge) for edge in nx.bridges(graph)}
            reboarding = {frozenset((a, b)) for a, b, data in graph.edges(data=True)
                          if data["edge_type"] == exp.REBOARD}
            self.assertEqual(len(reboarding), 3)
            self.assertLessEqual(reboarding, bridges)
            disrupted = v04.disable_interchange(graph, "sol")
            self.assertEqual(exp.graph_counts(disrupted)["pedestrian_state_edges"],
                             exp.graph_counts(graph)["pedestrian_state_edges"])
            self.assertEqual(exp.graph_counts(disrupted)["mandatory_train_change_edges"], 3)
        self.assertNotIn("santo-domingo", {u[0] for u, v, data in e.edges(data=True) if data["edge_type"] == exp.WALK}
                         | {v[0] for u, v, data in e.edges(data=True) if data["edge_type"] == exp.WALK})


if __name__ == "__main__":
    unittest.main()
