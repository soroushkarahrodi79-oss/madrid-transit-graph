"""Sensitivity: does the matched disruption also close the walking links of the disrupted station?

The main experiment keeps every documented walk open. Here a disruption at station S removes the same-station
transfer clique and, optionally, every pedestrian link incident to S. Costs are computed independently of the
main solver (explicit lexicographic tuples encoded with a large base) and only counts worse R/T cost per scenario.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path

import networkx as nx

from research.evidence_informed_robustness import experiment as exp
from research.transfer_aware_v02 import experiment as v02

HERE = Path(__file__).resolve().parent
BASE = 10**6


def step(kind, a, b, objective):
    rides, changes = {v02.RIDE: (1, 0), v02.TRANSFER: (0, 1), exp.REBOARD: (0, 0),
                      exp.WALK: (0, int(a[1] != b[1]))}[kind]
    return rides * BASE + changes if objective == "R" else changes * BASE + rides


def station_costs(graph, objective, disrupted=None, close_walks=False):
    h = nx.Graph()
    h.add_nodes_from(graph)
    for a, b, data in graph.edges(data=True):
        kind = data["edge_type"]
        if disrupted and kind == v02.TRANSFER and a[0] == b[0] == disrupted:
            continue
        if disrupted and close_walks and kind == exp.WALK and disrupted in (a[0], b[0]):
            continue
        cost = step(kind, a, b, objective)
        h.add_edge(a, b, w=min(cost, h[a][b]["w"]) if h.has_edge(a, b) else cost)
    states = defaultdict(list)
    for node in h:
        states[node[0]].append(node)
    out = {}
    for o in sorted(states):
        best = {}
        for node, d in nx.multi_source_dijkstra_path_length(h, states[o], weight="w").items():
            if node[0] > o and d < best.get(node[0], d + 1):
                best[node[0]] = d
        out.update({(o, d): c for d, c in best.items()})
    return out


def run():
    evidence = json.loads((HERE / "evidence.json").read_bytes())
    stations, b1, interchanges = exp.load_control(evidence)
    sections, splits = exp.ride_sections(b1, stations, evidence["mandatory_train_changes"])
    walks = evidence["confirmed_walks"]
    models = {
        "B1": b1,
        "E": exp.build_evidence_model(b1, stations, sections, splits, walks),
        "E_with_Sol_Gran_Via": exp.build_evidence_model(
            b1, stations, sections, splits, walks + evidence["sensitivity_walks"]),
    }
    result = {"unit": "scenario-pair observations with strictly worse lexicographic cost (not travellers)",
              "scenarios": len(interchanges)}
    for name, graph in models.items():
        base = {o: station_costs(graph, o) for o in "RT"}
        result[name] = {}
        for label, close in (("walks_open", False), ("walks_closed_at_disrupted_station", True)):
            worse = {"R": 0, "T": 0}
            changed = {}
            for sid in interchanges:
                row = {}
                for o in "RT":
                    after = station_costs(graph, o, sid, close)
                    if any(c < base[o][p] for p, c in after.items()):
                        raise RuntimeError("A disruption improved a route")
                    row[o] = sum(c > base[o][p] for p, c in after.items())
                    worse[o] += row[o]
                changed[sid] = row
            result[name][label] = {"R_worse_cost": worse["R"], "T_worse_cost": worse["T"], "by_scenario": changed}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=HERE / "corridor_closure_summary.json")
    args = parser.parse_args()
    args.output.write_text(json.dumps(run(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
