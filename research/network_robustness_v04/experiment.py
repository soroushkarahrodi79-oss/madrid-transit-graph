"""Reproduce the Madrid Metro structural disruption study from the public v0.1.0 snapshot."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from math import comb
from pathlib import Path
from statistics import median

import networkx as nx

# Also support direct execution of this file from outside the repository.
if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research.transfer_aware_v02 import experiment as v02

HERE = Path(__file__).resolve().parent
RELEASE_MANIFEST_SHA256 = "975bb4b4e9861eb4971dd0584ee46bfd1cc2f7a5e06ef057f540b76a141a1dde"
OBJECTIVES = {
    "R": "fewest ride edges, ties fewest transfers",
    "T": "fewest transfers, ties fewest ride edges",
}


def remove_station(model_a, model_b, station):
    """Remove the physical station, including every station-line state in B1."""
    return (
        model_a.subgraph([node for node in model_a if node != station]),
        model_b.subgraph([node for node in model_b if v02.station_b(node) != station]),
    )


def disable_interchange(model_b, station):
    """Remove all transfer edges at this station, retaining all nodes and ride edges."""
    disrupted = model_b.copy()
    disrupted.remove_edges_from([
        (u, v) for u, v, edge in model_b.edges(data=True)
        if u[0] == v[0] == station and edge["edge_type"] == v02.TRANSFER
    ])
    return disrupted


def connectivity(graph, node_station, station_count):
    components = v02.station_components(graph, node_station)
    total = comb(station_count, 2)
    reachable = v02.reachable_pair_count(graph, node_station)
    return {
        "station_pairs": total,
        "reachable_pairs": reachable,
        "disconnected_pairs": total - reachable,
        "disconnected_fraction": round((total - reachable) / total, 6) if total else 0.0,
        "graph_components": len(components),
        "largest_component_stations": max(map(len, components), default=0),
    }


def station_failures(model_a, model_b):
    """Compare the actual physical partitions, not just their sizes."""
    failures = {}
    for station in sorted(model_a):
        remaining_a, remaining_b = remove_station(model_a, model_b, station)
        partition_a = {frozenset(c) for c in nx.connected_components(remaining_a)}
        partition_b = {frozenset(c) for c in v02.station_components(remaining_b, v02.station_b)}
        if partition_a != partition_b or sum(map(len, partition_b)) != len(remaining_a):
            raise RuntimeError(f"A/B1 component partitions diverged at {station}")
        failures[station] = connectivity(remaining_a, v02.station_a, len(remaining_a))

    fragmented = {station for station, row in failures.items() if row["disconnected_pairs"]}
    if fragmented != set(nx.articulation_points(model_a)):
        raise RuntimeError("Fragmenting removals differ from NetworkX articulation stations")
    return failures


def compare_paths(before, after, objective):
    """Compare lexicographic costs and equal-cost alternatives for surviving pairs."""
    if not after.keys() <= before.keys():
        raise RuntimeError("An intervention increased reachability")
    ride_deltas, transfer_deltas = Counter(), Counter()
    worse_cost = fewer_ties = 0
    for pair, (new_cost, new_paths) in after.items():
        old_cost, old_paths = before[pair]
        if new_cost < old_cost:
            raise RuntimeError(f"{objective} optimum improved for {pair} after removal")
        if new_cost == old_cost:
            if len(new_paths) > len(old_paths):
                raise RuntimeError(f"{objective} gained equal-cost paths for {pair} after removal")
            fewer_ties += len(new_paths) < len(old_paths)
        else:
            worse_cost += 1

        old_primary, old_secondary = divmod(old_cost, v02.BIG)
        new_primary, new_secondary = divmod(new_cost, v02.BIG)
        primary_delta = new_primary - old_primary
        secondary_delta = new_secondary - old_secondary
        if objective == "R":
            ride_deltas[primary_delta] += 1
            transfer_deltas[secondary_delta] += 1
        else:
            transfer_deltas[primary_delta] += 1
            ride_deltas[secondary_delta] += 1

    return {
        "pairs_with_worse_lexicographic_cost": worse_cost,
        "pairs_with_same_cost_and_fewer_optimal_state_paths": fewer_ties,
        "ride_delta_histogram": ride_deltas,
        "transfer_delta_histogram": transfer_deltas,
    }


def validated_paths(graph, stations, objective, expected_reachable):
    paths = v02.all_pairs_optimal(graph, stations, f"w_{objective}", "B")
    if len(paths) != expected_reachable or v02.validate_paths(graph, paths, objective):
        raise RuntimeError(f"{objective} paths failed component reachability or edge-count validation")
    return paths


def check_ride_projection(model_a, paths):
    hops = {
        (source, target): distance
        for source, distances in nx.all_pairs_shortest_path_length(model_a)
        for target, distance in distances.items() if source < target
    }
    if hops != {pair: cost // v02.BIG for pair, (cost, _) in paths.items()}:
        raise RuntimeError("Model A hop counts and B1 minimum rides differ after projection")


def route_effects(graph, stations, baseline_paths, reachable, projected_a=None):
    effects = {}
    for objective, before in baseline_paths.items():
        after = validated_paths(graph, stations, objective, reachable)
        if objective == "R":
            reachable_pairs = set(after)
            if projected_a is not None:
                check_ride_projection(projected_a, after)
        elif after.keys() != reachable_pairs:
            raise RuntimeError("R and T disagree about reachable station pairs")
        effects[objective] = compare_paths(before, after, objective)
    return effects


def positive_pair_count(deltas):
    return sum(count for delta, count in deltas.items() if delta > 0)


def summarize_deltas(deltas):
    increased = positive_pair_count(deltas)
    return {
        "increased_pairs": increased,
        "decreased_pairs": sum(count for delta, count in deltas.items() if delta < 0),
        "unchanged_pairs": deltas[0],
        "mean_increase_among_increased": round(
            sum(delta * count for delta, count in deltas.items() if delta > 0) / increased, 4
        ) if increased else None,
        "max_increase": max((delta for delta in deltas if delta > 0), default=0),
    }


def summarize_routes(scenarios):
    summary = {}
    for objective in OBJECTIVES:
        rides, transfers = Counter(), Counter()
        effects = [scenario["routes"][objective] for scenario in scenarios]
        for row in effects:
            rides.update(row["ride_delta_histogram"])
            transfers.update(row["transfer_delta_histogram"])
        summary[objective] = {
            "pairs_with_worse_lexicographic_cost": sum(
                row["pairs_with_worse_lexicographic_cost"] for row in effects
            ),
            "pairs_with_same_cost_and_fewer_optimal_state_paths": sum(
                row["pairs_with_same_cost_and_fewer_optimal_state_paths"] for row in effects
            ),
            "ride_edges": summarize_deltas(rides),
            "transfers": summarize_deltas(transfers),
        }
    return summary


def summarize_station_failures(failures):
    rows = list(failures.values())
    fragmented = sorted(row["disconnected_pairs"] for row in rows if row["disconnected_pairs"])
    return {
        "scenarios": len(rows),
        "remaining_station_pairs_per_scenario": rows[0]["station_pairs"],
        "scenarios_with_disconnected_pairs": len(fragmented),
        "scenarios_with_all_remaining_pairs_reachable": len(rows) - len(fragmented),
        "component_count_histogram": dict(sorted(Counter(row["graph_components"] for row in rows).items())),
        "smallest_largest_component_stations": min(row["largest_component_stations"] for row in rows),
        "disconnected_pairs_min_among_fragmenting": min(fragmented, default=0),
        "disconnected_pairs_median_among_fragmenting": median(fragmented) if fragmented else None,
        "disconnected_pairs_max": max(fragmented, default=0),
        "disconnected_fraction_max": max(row["disconnected_fraction"] for row in rows),
    }


def summarize_interchange_disruptions(disruptions):
    rows = list(disruptions.values())
    fully_reachable = [row for row in rows if row["disconnected_pairs"] == 0]
    no_effect = sum(
        all(
            effect["pairs_with_worse_lexicographic_cost"] == 0
            and effect["pairs_with_same_cost_and_fewer_optimal_state_paths"] == 0
            for effect in row["routes"].values()
        )
        for row in fully_reachable
    )
    return {
        "scenarios": len(rows),
        "station_pairs_per_scenario": rows[0]["station_pairs"],
        "scenario_pairs_total": sum(row["station_pairs"] for row in rows),
        "reachable_scenario_pairs": sum(row["reachable_pairs"] for row in rows),
        "disconnected_scenario_pairs": sum(row["disconnected_pairs"] for row in rows),
        "scenarios_with_disconnected_pairs": len(rows) - len(fully_reachable),
        "max_disconnected_pairs_in_one_scenario": max(row["disconnected_pairs"] for row in rows),
        "min_largest_state_component_stations": min(row["largest_component_stations"] for row in rows),
        "state_component_count_histogram": dict(sorted(Counter(row["graph_components"] for row in rows).items())),
        "scenarios_with_increased_minimum_rides": sum(
            positive_pair_count(row["routes"]["R"]["ride_delta_histogram"]) > 0 for row in rows
        ),
        "scenarios_with_increased_minimum_transfers": sum(
            positive_pair_count(row["routes"]["T"]["transfer_delta_histogram"]) > 0 for row in rows
        ),
        "fully_reachable_scenarios_with_optimal_path_effect": len(fully_reachable) - no_effect,
        "scenarios_with_no_reachability_or_optimal_path_effect": no_effect,
        "routes": summarize_routes(rows),
    }


def sensitivity_cases(model_a, model_b, stations, station_rows, interchange_rows, baseline_paths):
    # Selection rules fixed before evaluating detailed cases. All ties use ascending station ID.
    positive = {s: row["disconnected_pairs"] for s, row in station_rows.items() if row["disconnected_pairs"]}
    selected = {
        "highest_fragmentation": min(positive, key=lambda s: (-positive[s], s)),
        "lowest_positive_fragmentation": min(positive, key=lambda s: (positive[s], s)),
        "single_line_leaf_control": min(s for s in model_a if model_a.degree[s] == 1 and len(stations[s]["lines"]) == 1),
    }
    cases = {}
    for label, station in selected.items():
        a, b = remove_station(model_a, model_b, station)
        eligible = {s: stations[s] for s in a}
        before = {
            objective: {pair: paths for pair, paths in pairs.items() if station not in pair}
            for objective, pairs in baseline_paths.items()
        }
        row = station_rows[station]
        effects = route_effects(b, eligible, before, row["reachable_pairs"], projected_a=a)
        cases[label] = {
            **row,
            "pairs_excluded_with_removed_endpoint": len(stations) - 1,
            "routes": summarize_routes([{"routes": effects}]),
        }

    most_transfer_increases = min(interchange_rows, key=lambda s: (
        -positive_pair_count(interchange_rows[s]["routes"]["T"]["transfer_delta_histogram"]), s
    ))
    row = interchange_rows[most_transfer_increases]
    cases["interchange_with_most_minimum_transfer_increases"] = {
        **row,
        "pairs_excluded_with_removed_endpoint": 0,
        "routes": summarize_routes([row]),
    }
    return cases


def run():
    manifest_path = v02.DATA / "manifest.json"
    if v02.sha256(manifest_path) != RELEASE_MANIFEST_SHA256:
        raise RuntimeError("Manifest does not match the published v0.1.0 manifest")
    manifest = json.loads(manifest_path.read_text("utf-8"))
    for filename, entry in manifest["files"].items():
        path = v02.DATA / filename
        if path.stat().st_size != entry["bytes"] or v02.sha256(path) != entry["sha256"]:
            raise RuntimeError(f"{filename} does not match the published v0.1.0 snapshot")

    stations, connections = v02.load_snapshot()
    transfers = v02.fusion_transfers(stations)
    model_a = v02.build_model_a(stations, connections)
    model_b = v02.build_model_b(stations, connections, transfers)
    checks = v02.validate_model_b(model_a, model_b, stations, connections, transfers, "B1")
    failures = [name for name, ok, _ in checks if not ok]
    a_size = (len(model_a), model_a.number_of_edges(), nx.number_connected_components(model_a))
    interchange_ids = sorted({edge["a"][0] for edge in transfers})
    if failures or a_size != (242, 277, 1) or (len(model_b), len(transfers), len(interchange_ids)) != (291, 61, 38):
        raise RuntimeError(f"Baseline graph changed or failed validation: {failures}")

    total = comb(len(stations), 2)
    baseline_paths = {
        objective: validated_paths(model_b, stations, objective, total) for objective in OBJECTIVES
    }
    check_ride_projection(model_a, baseline_paths["R"])

    station_rows = station_failures(model_a, model_b)
    station_summary = summarize_station_failures(station_rows)
    earlier = json.loads((v02.HERE / "results_summary.json").read_text("utf-8"))
    if station_summary["scenarios_with_disconnected_pairs"] != earlier["model_a"]["articulation_stations"]:
        raise RuntimeError("Fragmenting station count differs from the v0.2 result")

    interchange_rows = {}
    for station in interchange_ids:
        disrupted = disable_interchange(model_b, station)
        row = connectivity(disrupted, v02.station_b, len(stations))
        row["transfer_edges_removed"] = model_b.number_of_edges() - disrupted.number_of_edges()
        row["routes"] = route_effects(disrupted, stations, baseline_paths, row["reachable_pairs"])
        interchange_rows[station] = row
    interchange_summary = summarize_interchange_disruptions(interchange_rows)
    cases = {}
    if (station_summary["scenarios_with_disconnected_pairs"]
            and interchange_summary["scenarios_with_no_reachability_or_optimal_path_effect"] < len(interchange_rows)):
        cases = sensitivity_cases(model_a, model_b, stations, station_rows, interchange_rows, baseline_paths)

    return {
        "snapshot": {
            "release": manifest["release"],
            "osm_data_timestamp": manifest["snapshot"]["osm_data_timestamp"],
            "manifest_sha256": RELEASE_MANIFEST_SHA256,
            "files": manifest["files"],
            "uses_crtm_audit": False,
        },
        "networkx": nx.__version__,
        "pair_unit": "unordered physical station pair; cross-scenario totals count a pair once per scenario",
        "objectives": OBJECTIVES,
        "baseline": {
            "stations": len(stations),
            "reachable_pairs": total,
            "model_A": {"nodes": a_size[0], "edges": a_size[1], "components": a_size[2]},
            "model_B1": {
                "state_nodes": len(model_b),
                "ride_edges": model_b.number_of_edges() - len(transfers),
                "transfer_edges": len(transfers),
                "components": nx.number_connected_components(model_b),
            },
        },
        "station_failures": station_summary,
        "interchange_disruptions": interchange_summary,
        "sensitivity_cases": cases,
        "validation": {
            "A_B1_equal_component_partitions_after_station_removal": len(station_rows),
            "fragmenting_stations_match_networkx_and_v02_count": True,
            "A_hops_equal_B1_minimum_rides_in_baseline_and_station_path_cases": True,
            "reconstructed_paths_match_edge_counts_and_component_reachability": True,
            "no_gained_reachability_or_improved_lexicographic_optima_in_path_cases": True,
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=HERE / "results_summary.json")
    args = parser.parse_args()
    summary = run()
    args.output.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
