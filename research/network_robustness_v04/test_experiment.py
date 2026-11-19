"""Synthetic checks with known answers for the disruption interventions."""

import unittest

import networkx as nx

from research.network_robustness_v04 import experiment as lab
from research.transfer_aware_v02 import experiment as v02


def models(segments):
    """Build both public models from synthetic (station, station, line) segments."""
    station_lines = {}
    connections = []
    for source, target, line in segments:
        station_lines.setdefault(source, set()).add(line)
        station_lines.setdefault(target, set()).add(line)
        connections.append({
            "id": f"{source}-{target}", "source": source, "target": target, "lines": [line],
        })
    stations = {s: {"name": s, "lines": sorted(lines)} for s, lines in station_lines.items()}
    return (
        stations,
        v02.build_model_a(stations, connections),
        v02.build_model_b(stations, connections, v02.fusion_transfers(stations)),
    )


def path_results(graph, stations, objective):
    reachable = v02.reachable_pair_count(graph, v02.station_b)
    return lab.validated_paths(graph, stations, objective, reachable)


class StationFailureTests(unittest.TestCase):
    def test_interior_chain_removal_splits_remaining_pairs(self):
        _, a, b = models([("a", "b", "L1"), ("b", "x", "L1"), ("x", "c", "L1"), ("c", "d", "L1")])
        failures = lab.station_failures(a, b)
        self.assertEqual(failures["x"], {
            "station_pairs": 6,
            "reachable_pairs": 2,
            "disconnected_pairs": 4,
            "disconnected_fraction": 0.666667,
            "graph_components": 2,
            "largest_component_stations": 2,
        })
        self.assertEqual(failures["a"]["disconnected_pairs"], 0)

    def test_cycle_removal_keeps_reachability_and_loses_one_tied_route(self):
        stations, a, b = models([
            ("a", "x", "L1"), ("x", "c", "L1"), ("a", "y", "L1"), ("y", "c", "L1"),
        ])
        self.assertTrue(all(row["disconnected_pairs"] == 0 for row in lab.station_failures(a, b).values()))
        remaining_a, remaining_b = lab.remove_station(a, b, "x")
        before = path_results(b, stations, "R")
        after = path_results(remaining_b, {s: stations[s] for s in remaining_a}, "R")
        self.assertEqual(len(before["a", "c"][1]), 2)
        self.assertEqual(len(after["a", "c"][1]), 1)
        self.assertEqual(after["a", "c"][0], before["a", "c"][0])
        effect = lab.compare_paths(before, after, "R")
        self.assertEqual(effect["pairs_with_same_cost_and_fewer_optimal_state_paths"], 1)
        self.assertEqual(effect["pairs_with_worse_lexicographic_cost"], 0)

    def test_complete_deletion_removes_all_line_states_and_matches_projection(self):
        _, a, b = models([("a", "x", "L1"), ("x", "b", "L1"), ("c", "x", "L2"), ("x", "d", "L2")])
        remaining_a, remaining_b = lab.remove_station(a, b, "x")
        self.assertEqual(set(remaining_a), {"a", "b", "c", "d"})
        self.assertEqual(set(remaining_b), {("a", "L1"), ("b", "L1"), ("c", "L2"), ("d", "L2")})
        self.assertEqual(remaining_b.number_of_edges(), 0)
        self.assertEqual({frozenset(c) for c in nx.connected_components(remaining_a)},
                         {frozenset(c) for c in v02.station_components(remaining_b, v02.station_b)})
        self.assertEqual(lab.station_failures(a, b)["x"]["disconnected_pairs"], 6)


class InterchangeDisruptionTests(unittest.TestCase):
    def test_losses_count_pairs_once_when_physical_components_overlap(self):
        stations, _, b = models([("a", "x", "L1"), ("x", "b", "L1"), ("c", "x", "L2"), ("x", "d", "L2")])
        disrupted = lab.disable_interchange(b, "x")
        self.assertEqual(set(disrupted), set(b))
        self.assertEqual(set(disrupted.edges), {
            (u, v) for u, v, data in b.edges(data=True) if data["edge_type"] == v02.RIDE
        })
        row = lab.connectivity(disrupted, v02.station_b, len(stations))
        self.assertEqual((row["station_pairs"], row["disconnected_pairs"], row["graph_components"]), (10, 4, 2))
        self.assertEqual(row["largest_component_stations"], 3)
        for objective in lab.OBJECTIVES:
            with self.subTest(objective=objective):
                before = path_results(b, stations, objective)
                after = path_results(disrupted, stations, objective)
                self.assertLess(after.keys(), before.keys())
                self.assertEqual(v02.count_edges(disrupted, after["c", "x"][1][0]), (1, 0))
                self.assertNotIn(("a", "c"), after)
                with self.assertRaisesRegex(RuntimeError, "increased reachability"):
                    lab.compare_paths(after, before, objective)

    def test_deleting_one_edge_preserves_indirect_transfer_in_three_line_clique(self):
        stations, _, b = models([("a", "x", "L1"), ("b", "x", "L2"), ("c", "x", "L3")])
        one_edge = b.copy()
        one_edge.remove_edge(("x", "L1"), ("x", "L2"))
        no_transfers = lab.disable_interchange(b, "x")
        self.assertEqual(b.number_of_edges() - no_transfers.number_of_edges(), 3)
        self.assertEqual(lab.connectivity(one_edge, v02.station_b, len(stations))["reachable_pairs"], 6)
        self.assertEqual(lab.connectivity(no_transfers, v02.station_b, len(stations))["reachable_pairs"], 3)
        paths = path_results(one_edge, stations, "T")
        self.assertEqual(divmod(paths["a", "b"][0], v02.BIG), (2, 2))

    def test_alternative_route_can_preserve_reachability_with_more_rides_and_transfers(self):
        stations, _, b = models([
            ("a", "x", "L1"), ("x", "p", "L1"), ("x", "b", "L2"), ("q", "b", "L2"), ("p", "q", "L3"),
        ])
        disrupted = lab.disable_interchange(b, "x")
        for objective, old, new in (("R", (2, 1), (4, 2)), ("T", (1, 2), (2, 4))):
            with self.subTest(objective=objective):
                before = path_results(b, stations, objective)
                after = path_results(disrupted, stations, objective)
                self.assertEqual(before.keys(), after.keys())
                self.assertEqual(divmod(before["a", "b"][0], v02.BIG), old)
                self.assertEqual(divmod(after["a", "b"][0], v02.BIG), new)
                self.assertEqual(v02.count_edges(disrupted, after["a", "b"][1][0]), (4, 2))
                with self.assertRaisesRegex(RuntimeError, "optimum improved"):
                    lab.compare_paths(after, before, objective)


if __name__ == "__main__":
    unittest.main()
