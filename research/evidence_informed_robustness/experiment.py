"""Paired Madrid Metro interchange disruptions under documented normal service."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from itertools import combinations, groupby, pairwise, product
import json
from math import comb
from pathlib import Path

import networkx as nx

from research.network_robustness_v04 import experiment as v04
from research.transfer_aware_v02 import experiment as v02

HERE = Path(__file__).resolve().parent
WALK = "pedestrian_interchange"
REBOARD = "mandatory_train_change"
WORSENED, FEWER_STATIONS, FEWER_SERVICES, MORE_TRAINS = (1, 2, 4, 8)
EFFECTS = {
    "worse_lexicographic_cost": WORSENED,
    "equal_cost_fewer_station_sequences": FEWER_STATIONS,
    "equal_cost_fewer_service_itineraries": FEWER_SERVICES,
    "more_required_train_changes_among_optima": MORE_TRAINS,
}


def station_id(stations, name, line):
    matches = [sid for sid, station in stations.items()
               if station["name"] == name and line in station["lines"]]
    if len(matches) != 1:
        raise ValueError(f"Expected one frozen station for {name!r} on {line}")
    return matches[0]


def ride_sections(b1, stations, rules):
    """Assign each ride to a service section and identify the three split states."""
    sections = {}
    splits = {}
    for rule in rules:
        line = rule["line"]
        boundary = (station_id(stations, rule["station"], line), line)
        line_graph = nx.Graph(
            (u, v) for u, v, edge in b1.edges(data=True)
            if edge["edge_type"] == v02.RIDE and edge["line"] == line
        )
        if boundary in splits or set(stations[boundary[0]]["lines"]) != {line}:
            raise ValueError(f"Expected a distinct single-line boundary at {boundary}")
        remainder = line_graph.copy()
        remainder.remove_node(boundary)
        parts = []
        for section, terminus in rule["sections"].items():
            terminal = (station_id(stations, terminus, line), line)
            part = nx.node_connected_component(remainder, terminal)
            if remainder.degree(terminal) > 1 or len(set(line_graph[boundary]) & part) != 1:
                raise ValueError(f"{terminus} does not identify one side of {boundary}")
            for u, v in line_graph.subgraph(part | {boundary}).edges:
                sections[frozenset((u, v))] = section
            parts.append(part)
        if len(parts) != 2 or not parts[0].isdisjoint(parts[1]) or parts[0] | parts[1] != set(remainder):
            raise ValueError(f"Sections do not partition {line} at {boundary}")
        splits[boundary] = tuple(rule["sections"])
    return sections, splits


def build_evidence_model(b1, stations, sections, splits, walks):
    graph = nx.Graph()
    for node in b1:
        if node in splits:
            graph.add_nodes_from((*node, section) for section in splits[node])
            a, b = ((*node, section) for section in splits[node])
            graph.add_edge(a, b, edge_type=REBOARD, w_R=0, w_T=0)
        else:
            graph.add_node(node)

    for u, v, edge in b1.edges(data=True):
        section = sections.get(frozenset((u, v)))
        a = (*u, section) if u in splits else u
        b = (*v, section) if v in splits else v
        if a not in graph or b not in graph or graph.has_edge(a, b):
            raise ValueError(f"Cannot lift control edge {u}–{v}")
        graph.add_edge(a, b, **edge)

    for walk in walks:
        endpoints = [[(station_id(stations, end["station"], line), line) for line in end["lines"]]
                     for end in walk["endpoints"]]
        for a, b in product(*endpoints):
            if a not in graph or b not in graph or a[0] == b[0]:
                raise ValueError(f"Invalid pedestrian connection {a}–{b}")
            changes = int(a[1] != b[1])
            if graph.has_edge(a, b):
                # The sensitivity walk and the existing L1 ride are two different edges.
                if graph.is_multigraph() or changes or graph[a][b]["edge_type"] != v02.RIDE:
                    raise ValueError(f"Unexpected parallel pedestrian connection {a}–{b}")
                graph = nx.MultiGraph(graph)
            graph.add_edge(a, b, edge_type=WALK, w_R=changes, w_T=changes * v02.BIG)
    return graph


def routing_graph(graph):
    if not graph.is_multigraph():
        return graph
    routing = nx.Graph()
    routing.add_nodes_from(graph)
    for a, b, edge in graph.edges(data=True):
        if routing.has_edge(a, b):
            incumbent = routing[a][b]
            if edge["edge_type"] == v02.RIDE:
                incumbent, edge = edge, incumbent
            if (edge["edge_type"] != WALK or incumbent["edge_type"] != v02.RIDE
                    or not all(edge[w] < incumbent[w] for w in ("w_R", "w_T"))):
                raise RuntimeError("Parallel edges lack a strictly dominating walk")
        routing.add_edge(a, b, **edge)
    return routing


def neutral_peers(graph, weight):
    """In these models, neutral edges form disjoint pairs of states."""
    peers = {}
    for a, b, edge in graph.edges(data=True):
        if edge[weight] == 0:
            if a in peers or b in peers:
                raise ValueError("The shortest-path recurrence requires disjoint zero-cost edges")
            peers[a], peers[b] = b, a
    return peers


def optimal_from(graph, origins, weight, origin, peers):
    if not peers:
        return v02.optimal_paths_from(graph, origins, weight, v02.station_b, origin)
    distances = nx.multi_source_dijkstra_path_length(graph, origins, weight=weight)
    paths_to = {}
    best = {}
    for distance, nodes in groupby(sorted(distances, key=distances.get), distances.get):
        # A shortest simple path either enters a distance group at its last state
        # or uses the group's single neutral edge after entering at the peer.
        arrivals = {
            v: ([(v,)] if v in origins else []) + [
                path + (v,) for u, edge in graph[v].items()
                if edge[weight] > 0 and u in paths_to and distances[u] + edge[weight] == distance
                for path in paths_to[u]
            ]
            for v in nodes
        }
        for v, paths in arrivals.items():
            paths_to[v] = paths + [path + (v,) for path in arrivals.get(peers.get(v), ())]
            if not paths_to[v] or len(paths_to[v]) > 20000:
                raise RuntimeError("Missing optimal paths or path count exceeded the control's limit")
            sid = v02.station_b(v)
            if sid == origin:
                continue
            if sid not in best:
                best[sid] = (distance, paths_to[v].copy())
            elif best[sid][0] == distance:
                best[sid][1].extend(paths_to[v])
    return best


def optimal_pairs(graph, objective, states):
    weight = f"w_{objective}"
    peers = neutral_peers(graph, weight)
    return {
        (o, d): result
        for o, origins in sorted(states.items())
        for d, result in optimal_from(graph, origins, weight, o, peers).items()
        if o < d
    }


def route_signature(graph, path, sections):
    """Keep physical movements and their ridden services, ignoring unused endpoint states."""
    legs = []
    rides = changes = train_changes = line_changes = walks = 0
    previous_service = None
    previous_line = None
    left_train = False
    for u, v in pairwise(path):
        edge = graph[u][v]
        kind = edge["edge_type"]
        changes += u[1] != v[1]
        if kind == v02.RIDE:
            service = sections.get(frozenset((u[:2], v[:2])), u[1])
            rides += 1
            if previous_service is not None:
                line_changes += previous_line != u[1]
                train_changes += left_train or previous_service != service
            previous_service, previous_line, left_train = service, u[1], False
            legs.append((u[0], v[0], service))
        else:
            left_train = True
            if kind == WALK:
                walks += 1
                legs.append((u[0], v[0], WALK))
    physical = (path[0][0], *(leg[1] for leg in legs))
    return physical, tuple(legs), (rides, changes, line_changes, train_changes, walks)


def score_paths(graph, pair, paths, cost, objective, sections):
    physical, service = set(), set()
    minimum = None
    expected = divmod(cost, v02.BIG)
    expected = expected if objective == "R" else expected[::-1]
    for path in paths:
        if (path[0][0], path[-1][0]) != pair:
            raise RuntimeError(f"Incorrect route endpoints for {pair}")
        physical_path, service_path, metrics = route_signature(graph, path, sections)
        if metrics[:2] != expected:
            raise RuntimeError(f"Incorrect route cost for {pair}")
        physical.add(physical_path)
        service.add(service_path)
        extra = metrics[2:]
        minimum = extra if minimum is None else tuple(map(min, zip(minimum, extra)))
    return expected + minimum, physical, service


METRICS = ("ride_edges", "commercial_line_state_changes", "ridden_commercial_line_changes",
           "physical_train_changes", "pedestrian_connections")


def compare_paths(graph, before, scores, after, objective, sections, keep_raw_paths=False):
    if not after.keys() <= before.keys():
        raise RuntimeError("An interchange disruption gained reachable pairs")
    delta = {metric: Counter() for metric in METRICS}
    events = {}
    fewer_raw_paths = 0
    for pair, (new_cost, new_paths) in after.items():
        old_cost, old_paths = before[pair]
        old_counts, old_physical, old_service = scores[pair]
        if new_cost < old_cost:
            raise RuntimeError(f"{objective} optimum improved after removal for {pair}")
        if (new_cost, new_paths) == (old_cost, old_paths):
            for histogram in delta.values():
                histogram[0] += 1
            continue

        new_counts, new_physical, new_service = score_paths(
            graph, pair, new_paths, new_cost, objective, sections
        )
        event = WORSENED if new_cost > old_cost else 0
        if new_cost == old_cost:
            if not new_physical <= old_physical or not new_service <= old_service:
                raise RuntimeError(f"{objective} gained equal-cost alternatives after removal for {pair}")
            if new_physical < old_physical:
                event |= FEWER_STATIONS
            if new_service < old_service:
                event |= FEWER_SERVICES
            if keep_raw_paths:
                if not set(new_paths) <= set(old_paths):
                    raise RuntimeError(f"Original B1 gained equal-cost state paths for {pair}")
                fewer_raw_paths += len(new_paths) < len(old_paths)
        if new_counts[3] > old_counts[3]:
            event |= MORE_TRAINS
        for metric, old_count, new_count in zip(METRICS, old_counts, new_counts, strict=True):
            delta[metric][new_count - old_count] += 1
        if event:
            events[pair] = event
    return delta, events, fewer_raw_paths


def model_states(graph, stations):
    states = defaultdict(set)
    for node in graph:
        states[node[0]].add(node)
    actual = {node[:2] for node in graph}
    expected = {(sid, line) for sid, station in stations.items() for line in station["lines"]}
    if actual != expected:
        raise RuntimeError("Physical station IDs or commercial service incidence changed")
    return dict(states)


def connected_pairs(graph):
    return {
        pair
        for component in v02.station_components(graph, v02.station_b)
        for pair in combinations(sorted(component), 2)
    }


def prepare(graph, stations, sections):
    states = model_states(graph, stations)
    baseline = {}
    scores = {}
    all_pairs = connected_pairs(graph)
    if len(all_pairs) != comb(len(stations), 2):
        raise RuntimeError("Intact model does not connect the full OD universe")
    graph = routing_graph(graph)
    for objective in v04.OBJECTIVES:
        paths = optimal_pairs(graph, objective, states)
        if paths.keys() != all_pairs:
            raise RuntimeError(f"{objective} solver disagrees with intact component reachability")
        baseline[objective] = paths
        scores[objective] = {
            pair: score_paths(graph, pair, options, cost, objective, sections)
            for pair, (cost, options) in paths.items()
        }
    return states, baseline, scores


def analyze_disruption(graph, station, prepared, sections, keep_raw_paths):
    states, baseline, scores = prepared
    disrupted = v04.disable_interchange(graph, station)
    removed = graph.number_of_edges() - disrupted.number_of_edges()
    expected = comb(len({node[1] for node in states[station]}), 2)
    if removed != expected:
        raise RuntimeError(f"Intervention did not remove exactly the original clique at {station}")
    reachable = connected_pairs(disrupted)
    connectivity = {
        "station_pairs": comb(len(states), 2),
        "reachable_pairs": len(reachable),
        "disconnected_pairs": comb(len(states), 2) - len(reachable),
        "graph_components": nx.number_connected_components(disrupted),
        "largest_component_stations": max(map(len, v02.station_components(disrupted, v02.station_b))),
    }
    effects = {}
    route_graph = routing_graph(disrupted)
    for objective in v04.OBJECTIVES:
        after = optimal_pairs(route_graph, objective, states)
        if after.keys() != reachable:
            raise RuntimeError(f"{objective} reachability disagrees with components at {station}")
        effects[objective] = compare_paths(
            route_graph, baseline[objective], scores[objective], after, objective, sections, keep_raw_paths
        )
    return connectivity, effects, reachable


def summarize_disruptions(rows, raw=False):
    legacy = []
    fully_reachable_degraded = fully_reachable_higher_cost = 0
    total_deltas = {objective: {metric: Counter() for metric in METRICS} for objective in v04.OBJECTIVES}
    total_events = {objective: Counter() for objective in v04.OBJECTIVES}
    for connectivity, effects in rows:
        routes = {}
        for objective, (deltas, histogram, fewer_raw_paths) in effects.items():
            for metric, counts in deltas.items():
                total_deltas[objective][metric].update(counts)
            total_events[objective].update({
                name: sum(count for event, count in histogram.items() if event & flag)
                for name, flag in EFFECTS.items()
            })
            routes[objective] = {
                "pairs_with_worse_lexicographic_cost": sum(count for event, count in histogram.items()
                                                          if event & WORSENED),
                "pairs_with_same_cost_and_fewer_optimal_state_paths": (
                    fewer_raw_paths if raw else sum(count for event, count in histogram.items()
                                                   if event & FEWER_SERVICES)
                ),
                "ride_delta_histogram": deltas["ride_edges"],
                "transfer_delta_histogram": deltas["commercial_line_state_changes"],
            }

        if not connectivity["disconnected_pairs"]:
            events = set().union(*(histogram for _, histogram, _ in effects.values()))
            fully_reachable_degraded += any(event & (WORSENED | FEWER_STATIONS | FEWER_SERVICES) for event in events)
            fully_reachable_higher_cost += any(event & WORSENED for event in events)
        legacy.append({**connectivity, "routes": routes})

    legacy_summary = v04.summarize_interchange_disruptions(dict(enumerate(legacy)))
    summary = {key: value for key, value in legacy_summary.items()
               if key not in ("routes", "scenarios_with_increased_minimum_transfers",
                              "fully_reachable_scenarios_with_optimal_path_effect",
                              "scenarios_with_no_reachability_or_optimal_path_effect")}
    summary["scenarios_with_increased_minimum_commercial_line_state_changes"] = (
        legacy_summary["scenarios_with_increased_minimum_transfers"]
    )
    summary["fully_reachable_scenarios_with_optimal_path_effect"] = fully_reachable_degraded
    summary["fully_reachable_scenarios_with_worse_lexicographic_cost"] = fully_reachable_higher_cost
    summary["routes"] = {
        objective: {
            **total_events[objective],
            **{metric: v04.summarize_deltas(counts) for metric, counts in total_deltas[objective].items()},
        }
        for objective in v04.OBJECTIVES
    }
    return summary, legacy_summary


def pair_disruption(left, right, counts):
    _, left_effects, left_reachable = left
    _, right_effects, right_reachable = right
    common = left_reachable & right_reachable
    counts["reachable_both"] += len(common)
    counts["reachable_left_only"] += len(left_reachable - right_reachable)
    counts["reachable_right_only"] += len(right_reachable - left_reachable)
    counts["reachable_neither"] += left[0]["station_pairs"] - len(left_reachable | right_reachable)
    for objective in v04.OBJECTIVES:
        left_events = left_effects[objective][1]
        right_events = right_effects[objective][1]
        histogram = Counter(
            (left_events.get(pair, 0), right_events.get(pair, 0))
            for pair in (left_events.keys() | right_events.keys()) & common
        )
        histogram[0, 0] += len(common) - histogram.total()
        for name, flag in EFFECTS.items():
            for (a, b), number in histogram.items():
                category = ("both" if b & flag else "left_only") if a & flag else (
                    "right_only" if b & flag else "neither"
                )
                counts[objective, name, category] += number


def paired_summary(counts):
    return {
        "reachability": {key: value for key, value in counts.items() if isinstance(key, str)},
        "route_effects_on_common_survivors": {
            objective: {
                name: {key: counts[objective, name, key] for key in ("left_only", "right_only", "both", "neither")}
                for name in EFFECTS
            }
            for objective in v04.OBJECTIVES
        },
    }


def compare_intact(left, right):
    differences = {}
    for objective in v04.OBJECTIVES:
        deltas = {metric: Counter() for metric in METRICS}
        improved = worsened = 0
        for pair, (before, _, _) in left[2][objective].items():
            after = right[2][objective][pair][0]
            ordering = (0, 1) if objective == "R" else (1, 0)
            old_cost, new_cost = (tuple(row[i] for i in ordering) for row in (before, after))
            improved += new_cost < old_cost
            worsened += new_cost > old_cost
            for metric, old_count, new_count in zip(METRICS, before, after, strict=True):
                deltas[metric][new_count - old_count] += 1
        if worsened:
            raise RuntimeError("Adding links and tracing same-line reboarding worsened intact R/T")
        differences[objective] = {
            "better_lexicographic_cost": improved,
            **{metric: v04.summarize_deltas(counts) for metric, counts in deltas.items()},
        }
    return differences


def station_removals(graph, stations):
    return v04.summarize_station_failures({
        sid: v04.connectivity(
            nx.subgraph_view(graph, filter_node=lambda node: node[0] != sid),
            v02.station_b,
            len(stations) - 1,
        )
        for sid in sorted(stations)
    })



def load_control(evidence):
    manifest_path = v02.DATA / "manifest.json"
    if v02.sha256(manifest_path) != v04.RELEASE_MANIFEST_SHA256:
        raise RuntimeError("Snapshot manifest does not match the v0.1.0 release")
    manifest = json.loads(manifest_path.read_bytes())
    if evidence["snapshot"]["manifest_sha256"] != v04.RELEASE_MANIFEST_SHA256:
        raise RuntimeError("Evidence manifest references a different snapshot")
    for name, entry in manifest["files"].items():
        path = v02.DATA / name
        if path.stat().st_size != entry["bytes"] or v02.sha256(path) != entry["sha256"]:
            raise RuntimeError(f"Snapshot integrity check failed for {name}")
    stations, connections = v02.load_snapshot()
    transfers = v02.fusion_transfers(stations)
    b1 = v02.build_model_b(stations, connections, transfers)
    interchanges = sorted({edge["a"][0] for edge in transfers})
    counts = len(stations), len(b1), b1.number_of_edges() - len(transfers), len(transfers), len(interchanges)
    if counts != (242, 291, 280, 61, 38):
        raise RuntimeError(f"Unexpected original graph size: {counts}")
    return stations, b1, interchanges


def graph_counts(graph):
    edges = Counter(data["edge_type"] for _, _, data in graph.edges(data=True))
    return {
        "physical_stations": len({node[0] for node in graph}),
        "states": len(graph),
        "ride_edges": edges[v02.RIDE],
        "same_station_commercial_transfer_edges": edges[v02.TRANSFER],
        "mandatory_train_change_edges": edges[REBOARD],
        "pedestrian_state_edges": edges[WALK],
        "pedestrian_station_links": len({
            frozenset((u[0], v[0])) for u, v, data in graph.edges(data=True) if data["edge_type"] == WALK
        }),
    }


def verify_lift(b1, graph, sections, splits):
    original = {frozenset((u, v)): data["edge_type"] for u, v, data in b1.edges(data=True)}
    lifted = {}
    for u, v, data in graph.edges(data=True):
        kind = data["edge_type"]
        if kind in (WALK, REBOARD):
            continue
        key = frozenset((u[:2], v[:2]))
        if key in lifted or any(node[:2] in splits and node[2:] != (sections.get(key),) for node in (u, v)):
            raise RuntimeError("Ride or interchange edge duplicated or attached to the wrong service section")
        lifted[key] = kind
    if lifted != original:
        raise RuntimeError("The evidence model changed the original rides or same-station interchange edges")


def verify_local_captures(root, evidence):
    files = {"PHASE1.md": evidence["local_phase1_report_sha256"]}
    files.update({row["local_capture"]: row["sha256"] for row in evidence["sources"]})
    for filename, expected in files.items():
        path = root / filename
        if not path.is_file() or v02.sha256(path) != expected:
            raise RuntimeError(f"Local Phase 1 evidence differs from the manifest: {path}")
    print(f"Verified {len(files)} local Phase 1 references")


def run(evidence):
    stations, b1, interchanges = load_control(evidence)
    sections, splits = ride_sections(b1, stations, evidence["mandatory_train_changes"])
    confirmed = evidence["confirmed_walks"]
    models = {
        "B1": b1,
        "E": build_evidence_model(b1, stations, sections, splits, confirmed),
        "E_with_Sol_Gran_Via": build_evidence_model(
            b1, stations, sections, splits, confirmed + evidence["sensitivity_walks"]
        ),
    }
    for name in ("E", "E_with_Sol_Gran_Via"):
        verify_lift(b1, models[name], sections, splits)
    prepared = {name: prepare(graph, stations, sections) for name, graph in models.items()}
    comparisons = (("B1", "E"), ("E", "E_with_Sol_Gran_Via"))
    paired = {pair: Counter() for pair in comparisons}
    rows = {name: [] for name in models}
    for index, station in enumerate(interchanges, 1):
        scenarios = {
            name: analyze_disruption(graph, station, prepared[name], sections, keep_raw_paths=name == "B1")
            for name, graph in models.items()
        }
        for left, right in comparisons:
            if not scenarios[left][2] <= scenarios[right][2]:
                raise RuntimeError(f"Added walking links reduced reachability in scenario {station}")
            pair_disruption(scenarios[left], scenarios[right], paired[left, right])
        for name, (connectivity, effects, _) in scenarios.items():
            rows[name].append((connectivity, {
                objective: (deltas, Counter(events.values()), raw_paths)
                for objective, (deltas, events, raw_paths) in effects.items()
            }))
        print(f"Completed interchange scenario {index}/{len(interchanges)}", flush=True)
    disruptions = {}
    legacy = {}
    for name, model_rows in rows.items():
        disruptions[name], legacy[name] = summarize_disruptions(model_rows, raw=name == "B1")
    station_controls = {name: station_removals(graph, stations) for name, graph in models.items()}
    published = json.loads((v04.HERE / "results_summary.json").read_bytes())
    controls = {"interchange_disruptions": legacy["B1"], "station_failures": station_controls["B1"]}
    for key, result in controls.items():
        # JSON stores the integer component-count histogram keys as strings.
        actual = json.loads(json.dumps(result))
        if actual != published[key]:
            differing = sorted(name for name in actual.keys() | published[key].keys()
                               if actual.get(name) != published[key].get(name))
            raise RuntimeError(f"B1 differs from the published v0.4 {key} control in {differing}")
    return {
        "snapshot": evidence["snapshot"],
        "networkx": nx.__version__,
        "pair_unit": "Unordered physical station pair; repeated across scenarios, not passengers",
        "objectives": {
            "R": ["ride_edges", "commercial_line_state_changes"],
            "T": ["commercial_line_state_changes", "ride_edges"],
            "additional_metrics": "Minimum of each separately over the R/T-optimal route set",
        },
        "models": {name: graph_counts(graph) for name, graph in models.items()},
        "interchange_disruptions": disruptions,
        "matched_comparisons": {
            f"{left}_vs_{right}": {
                "intact": compare_intact(prepared[left], prepared[right]),
                "after_matched_disruptions": paired_summary(paired[left, right]),
            }
            for left, right in comparisons
        },
        "complete_station_removal_connectivity": station_controls,
        "v04_control": {
            "published_interchange_aggregates_equal": True,
            "published_station_removal_aggregates_equal": True,
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=HERE / "results_summary.json")
    parser.add_argument("--phase1-dir", type=Path, help="Optionally verify the preserved local source captures")
    args = parser.parse_args()
    evidence = json.loads((HERE / "evidence.json").read_bytes())
    if args.phase1_dir:
        verify_local_captures(args.phase1_dir, evidence)
    summary = run(evidence)
    args.output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
