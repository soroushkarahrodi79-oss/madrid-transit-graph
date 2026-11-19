#!/usr/bin/env python3
"""Transfer-aware (Model B) vs station-aggregated (Model A) Madrid Metro graph.

Research experiment for branch research/transfer-aware-v02. It reads the immutable v0.1.0 snapshot in data/
(never rewrites it, never queries OSM) and, if present locally, data/crtm_audit.json (CRTM-derived, not distributed).

Model A: node = aggregated physical station; undirected edge = consecutive stations on >=1 line.
Model B: node = (station_id, line_id); `ride` edges between consecutive stations of one line, `transfer` edges
         between station-line states of one interchange (evidence-tagged).

Path semantics in B (physical origin o -> destination d): a path may start at ANY state of o and end at ANY state
of d at no cost (boarding/alighting is not a transfer). Two lexicographic objectives, with no time/penalty model:
  R = fewest ride edges, ties -> fewest transfer edges     (the A-compatible objective)
  T = fewest transfer edges, ties -> fewest ride edges
Hops are counts of edges, never minutes or metres.

Outputs: results_summary.json (aggregates only; committed) and local/station_level.json (per-station; git-ignored,
because it mixes OSM-derived topology with CRTM-derived transfer evidence - see NOTICE.md).
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import itertools
import json
import math
import sys
from pathlib import Path

import networkx as nx

RIDE, TRANSFER = "ride", "transfer"
BIG = 10_000  # lexicographic weight; must exceed the number of edges of any optimal path
ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
HERE = Path(__file__).resolve().parent
EXPECTED_LOOP_LINES = {"L6", "L12"}  # circular lines of Metro de Madrid (external knowledge, checked against data)


# --------------------------------------------------------------------------- loading
def load_snapshot(data_dir: Path = DATA):
    stations, connections = {}, []
    for f in json.loads((data_dir / "stations.geojson").read_text("utf-8"))["features"]:
        p = f["properties"]
        lon, lat = f["geometry"]["coordinates"]
        stations[p["id"]] = {"name": p["name"], "lines": sorted(p["lines"]), "lon": lon, "lat": lat}
    for f in json.loads((data_dir / "connections.geojson").read_text("utf-8"))["features"]:
        p = f["properties"]
        connections.append({"id": p["id"], "source": p["source"], "target": p["target"], "lines": sorted(p["lines"])})
    return stations, connections


def load_audit(data_dir: Path = DATA):
    p = data_dir / "crtm_audit.json"
    return json.loads(p.read_text("utf-8")) if p.exists() else None


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def haversine_m(a, b) -> float:
    r = 6371008.8
    p1, p2 = math.radians(a["lat"]), math.radians(b["lat"])
    dp, dl = p2 - p1, math.radians(b["lon"] - a["lon"])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


# --------------------------------------------------------------------------- models
def build_model_a(stations, connections) -> nx.Graph:
    g = nx.Graph()
    for sid, s in stations.items():
        g.add_node(sid, name=s["name"], lines=tuple(s["lines"]))
    for c in connections:
        if c["source"] == c["target"] or g.has_edge(c["source"], c["target"]):
            raise ValueError(f"self-loop or duplicate connection {c['id']}")
        g.add_edge(c["source"], c["target"], lines=tuple(c["lines"]))
    return g


def transfer(a, b, evidence, confidence, source, **extra):
    return {"a": tuple(a), "b": tuple(b), "evidence": evidence, "confidence": confidence, "source": source, **extra}


def fusion_transfers(stations, audit=None):
    """Same-station transfers: all line pairs at one aggregated station (the v0.1.0 fusion, OSM-derived)."""
    confirmed = {c["station_id"]: c for c in audit["confirmed_interchanges"]} if audit else None
    out = []
    for sid in sorted(stations):
        for l, m in itertools.combinations(stations[sid]["lines"], 2):
            if confirmed is None:
                out.append(transfer((sid, l), (sid, m), "osm_name_fusion", "unvalidated", "OSM"))
            elif sid in confirmed:
                out.append(transfer((sid, l), (sid, m), "osm_name_fusion+crtm_interchange_confirmed", "confirmed",
                                    "OSM+CRTM-validation",
                                    crtm_interchange_code=confirmed[sid]["official_interchange_code"]))
            else:
                out.append(transfer((sid, l), (sid, m), "osm_name_fusion", "inferred_not_confirmed", "OSM"))
    return out


def cross_name_transfers(stations, audit):
    """Official interchanges that join stations of different names (CRTM interchange groups)."""
    out = []
    for g in audit["missing_official_transfers_between_different_names"]:
        glines = set(g["lines"])
        for s, t in itertools.combinations(sorted(g["our_station_ids"]), 2):
            for l in sorted(glines & set(stations[s]["lines"])):
                for m in sorted(glines & set(stations[t]["lines"])):
                    if l != m:
                        out.append(transfer((s, l), (t, m), "crtm_interchange_group", "confirmed", "CRTM",
                                            crtm_interchange_code=g["official_interchange_code"]))
    return out


def ambiguous_transfers(stations, audit):
    """Sensitivity only: a station whose CRTM LINEAS field cites other lines but has its own interchange code.
    The partner station is NOT stated by CRTM; it is inferred as the nearest station serving all cited lines."""
    out = []
    for u in audit["unverified"]:
        cited = set(u["official_lines_field_also_lists"])
        for sid in u["station_ids"]:
            cands = [(haversine_m(stations[sid], s), p) for p, s in stations.items()
                     if p != sid and cited <= set(s["lines"])]
            if not cands:
                continue
            dist, partner = min(cands)
            for l in stations[sid]["lines"]:
                for m in sorted(cited):
                    out.append(transfer((sid, l), (partner, m), "crtm_lineas_field_ambiguous",
                                        "ambiguous_sensitivity_only", "CRTM(inferred partner)",
                                        crtm_interchange_code=u["official_interchange_code"],
                                        partner_distance_m=round(dist)))
    return out


def build_model_b(stations, connections, transfers, provenance=None) -> nx.Graph:
    g = nx.Graph(**(provenance or {}))
    for sid in sorted(stations):
        for l in stations[sid]["lines"]:
            g.add_node((sid, l), station=sid, line=l)
    for c in connections:
        for l in c["lines"]:
            u, v = (c["source"], l), (c["target"], l)
            if u == v or g.has_edge(u, v):
                raise ValueError(f"self-loop or duplicate ride edge {c['id']} {l}")
            g.add_edge(u, v, edge_type=RIDE, line=l, source="OSM", evidence="osm_route_relation",
                       confidence="osm_topology", connection_id=c["id"], w_R=BIG, w_T=1)
    for t in transfers:
        a, b = t["a"], t["b"]
        if a not in g or b not in g:
            raise ValueError(f"transfer references unknown station-line state {a} {b}")
        if a == b or g.has_edge(a, b):
            raise ValueError(f"self-loop or duplicate transfer edge {a} {b}")
        attrs = {k: v for k, v in t.items() if k not in ("a", "b")}
        g.add_edge(a, b, edge_type=TRANSFER, lines=(a[1], b[1]), w_R=1, w_T=BIG, **attrs)
    return g


# --------------------------------------------------------------------------- paths
def station_b(n):
    return n[0]


def station_a(n):
    return n


def optimal_paths_from(g, origin_nodes, weight, node_station, origin_station):
    """Multi-source Dijkstra (all origin nodes at cost 0). Returns {dest_station: (cost, [node paths])} for every
    reachable station != origin, with ALL optimal node paths (memoised over the shortest-path DAG)."""
    dist = nx.multi_source_dijkstra_path_length(g, origin_nodes, weight=weight)
    paths_to = {}
    for v in sorted(dist, key=dist.get):
        if dist[v] == 0:
            paths_to[v] = [(v,)]
            continue
        acc = []
        for u in g[v]:
            if u in dist and dist[u] + g[u][v].get(weight, 1) == dist[v]:
                acc.extend(p + (v,) for p in paths_to[u])
        if len(acc) > 20000:
            raise RuntimeError("too many optimal paths")
        paths_to[v] = acc
    best = {}
    for v, d in dist.items():
        s = node_station(v)
        if s == origin_station:
            continue
        if s not in best or d < best[s][0]:
            best[s] = (d, [v])
        elif d == best[s][0]:
            best[s][1].append(v)
    return {s: (d, [p for v in vs for p in paths_to[v]]) for s, (d, vs) in best.items()}


def all_pairs_optimal(g, stations, weight, model):
    """{(o, d): (cost, [node paths])} for o < d (graph is undirected, so one direction suffices)."""
    ids = sorted(stations)
    idx = {s: i for i, s in enumerate(ids)}
    res = {}
    for o in ids:
        if model == "A":
            origin_nodes, ns = [o], station_a
        else:
            origin_nodes, ns = [(o, l) for l in stations[o]["lines"]], station_b
        for d, val in optimal_paths_from(g, origin_nodes, weight, ns, o).items():
            if idx[d] > idx[o]:
                res[(o, d)] = val
    return res


def count_edges(g, path):
    rides = transfers = 0
    for u, v in zip(path, path[1:]):
        if g[u][v].get("edge_type", RIDE) == RIDE:
            rides += 1
        else:
            transfers += 1
    return rides, transfers


def station_seq(path, node_station):
    seq = []
    for n in path:
        s = node_station(n)
        if not seq or seq[-1] != s:
            seq.append(s)
    return tuple(seq)


def betweenness_from_pairs(pairs, node_station, n_stations):
    """Share of station pairs whose optimal paths pass through s (s not an endpoint), averaged over the DISTINCT
    optimal station sequences of each pair, normalised by (n-1)(n-2)/2 (networkx's undirected convention)."""
    b = collections.defaultdict(float)
    for _, paths in pairs.values():
        seqs = {station_seq(p, node_station) for p in paths}
        for sq in seqs:
            for s in set(sq[1:-1]):
                b[s] += 1.0 / len(seqs)
    norm = (n_stations - 1) * (n_stations - 2) / 2
    return {s: v / norm for s, v in b.items()}


# --------------------------------------------------------------------------- connectivity
def station_components(g, node_station):
    return [{node_station(n) for n in comp} for comp in nx.connected_components(g)]


def _pairs_from_components(comps, exclude=None):
    """Number of unordered station pairs sharing at least one component (stations may sit in several)."""
    comps = [c - {exclude} if exclude else c for c in comps]
    if sum(len(c) for c in comps) == len(set().union(*comps)):  # partition -> closed form
        return sum(len(c) * (len(c) - 1) // 2 for c in comps)
    pairs = set()
    for c in comps:
        pairs.update(itertools.combinations(sorted(c), 2))
    return len(pairs)


def reachable_pair_count(g, node_station):
    return _pairs_from_components(station_components(g, node_station))


def physical_articulation(g, stations, node_station):
    """{station: pairs lost} for stations whose removal (all their states) makes some other station pair unreachable."""
    comps = station_components(g, node_station)
    out = {}
    for s in sorted(stations):
        before = _pairs_from_components(comps, exclude=s)
        h = g.subgraph([x for x in g if node_station(x) != s])
        lost = before - reachable_pair_count(h, node_station)
        if lost > 0:
            out[s] = lost
    return out


# --------------------------------------------------------------------------- statistics
def spearman(x, y):
    def ranks(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            for k in range(i, j + 1):
                r[order[k]] = (i + j) / 2 + 1
            i = j + 1
        return r
    rx, ry = ranks(x), ranks(y)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    vx = math.sqrt(sum((a - mx) ** 2 for a in rx))
    vy = math.sqrt(sum((b - my) ** 2 for b in ry))
    return cov / (vx * vy) if vx and vy else float("nan")


def topk(score, ids, k=10):
    return set(sorted(ids, key=lambda s: (-score.get(s, 0.0), s))[:k])


def dist_summary(vals):
    vals = sorted(vals)
    n = len(vals)
    if not n:
        return {"n": 0}
    return {"n": n, "mean": round(sum(vals) / n, 4), "median": vals[n // 2], "max": vals[-1],
            "histogram": {str(k): c for k, c in sorted(collections.Counter(vals).items())}}


# --------------------------------------------------------------------------- validation
def ride_degree(b, s):
    return len({v[0] for u in b if u[0] == s for v, d in b[u].items() if d["edge_type"] == RIDE})


def validate_model_b(a, b, stations, connections, transfers_expected, label):
    """Structural correctness checks; returns [(name, ok, detail)]."""
    chk = []

    def add(name, ok, detail=""):
        chk.append((f"{label}: {name}", bool(ok), detail))

    rides = [(u, v, d) for u, v, d in b.edges(data=True) if d["edge_type"] == RIDE]
    trans = [(u, v, d) for u, v, d in b.edges(data=True) if d["edge_type"] == TRANSFER]
    add("every edge is ride or transfer", len(rides) + len(trans) == b.number_of_edges())
    add("no self-loops", nx.number_of_selfloops(b) == 0)
    add("ride edges join the same line at both ends and that line serves both stations",
        all(u[1] == v[1] == d["line"] and d["line"] in stations[u[0]]["lines"] and d["line"] in stations[v[0]]["lines"]
            for u, v, d in rides))
    exp = {frozenset(((c["source"], l), (c["target"], l))) for c in connections for l in c["lines"]}
    got = {frozenset((u, v)) for u, v, _ in rides}
    add("ride edges == exactly one per (connection, line)", exp == got, f"{len(got)} ride edges")
    add("no inter-line ride edge", all(u[1] == v[1] for u, v, _ in rides))
    add("transfer edges join different lines", all(u[1] != v[1] for u, v, _ in trans))
    add("every transfer edge has evidence, confidence and source",
        all(d.get("evidence") and d.get("confidence") and d.get("source") for _, _, d in trans))
    add("transfer edges == expected transfer list",
        {frozenset((t["a"], t["b"])) for t in transfers_expected} == {frozenset((u, v)) for u, v, _ in trans},
        f"{len(trans)} transfer edges")
    add("station identity: B stations == A stations == snapshot stations",
        {n[0] for n in b} == set(a) == set(stations))
    add("station identity: B line states == station line sets",
        all({n[1] for n in b if n[0] == s} == set(stations[s]["lines"]) for s in stations))
    loops, bad = set(), []
    for line in sorted({n[1] for n in b}):
        h = nx.Graph([(u, v) for u, v, d in rides if d["line"] == line])
        if not nx.is_connected(h):
            bad.append(f"{line} disconnected")
            continue
        cyc = h.number_of_edges() - h.number_of_nodes() + 1
        if cyc == 1 and all(dg == 2 for _, dg in h.degree()):
            loops.add(line)
        elif cyc != 0:
            bad.append(f"{line} cyclomatic {cyc}")
    add("each line's ride subgraph is connected and is a tree or a simple cycle", not bad, "; ".join(bad))
    add("circular lines detected in data == expected circular lines", loops == EXPECTED_LOOP_LINES, str(sorted(loops)))
    add("ride-degree (distinct neighbouring stations) equals Model A degree",
        all(ride_degree(b, s) == a.degree(s) for s in a))
    return chk


def validate_paths(b, pairs, objective):
    """Violations: decoded lexicographic cost != edge counts on a reconstructed path, or wrong endpoints."""
    bad = 0
    for (o, d), (cost, paths) in pairs.items():
        prim, sec = divmod(cost, BIG)
        for p in paths:
            r, t = count_edges(b, p)
            if (objective == "R" and (r, t) != (prim, sec)) or (objective == "T" and (t, r) != (prim, sec)):
                bad += 1
            if station_b(p[0]) != o or station_b(p[-1]) != d:
                bad += 1
    return bad


# --------------------------------------------------------------------------- experiment
def analyse_scenario(a, a_pairs, b, stations, a_btw, a_art):
    ids = sorted(stations)
    n = len(ids)
    total_pairs = n * (n - 1) // 2
    edges = list(b.edges(data=True))
    out = {"state_nodes": b.number_of_nodes(),
           "ride_edges": sum(1 for *_, d in edges if d["edge_type"] == RIDE),
           "transfer_edges": sum(1 for *_, d in edges if d["edge_type"] == TRANSFER),
           "transfer_edges_by_evidence": dict(collections.Counter(
               d["evidence"] for *_, d in edges if d["edge_type"] == TRANSFER)),
           "state_graph_components": nx.number_connected_components(b)}
    comps = station_components(b, station_b)
    rp = reachable_pair_count(b, station_b)
    out["connectivity"] = {
        "largest_component_in_stations": max(len(c) for c in comps),
        "largest_component_fraction_of_stations": round(max(len(c) for c in comps) / n, 4),
        "reachable_station_pairs": rp, "station_pairs_total": total_pairs,
        "reachable_fraction": round(rp / total_pairs, 4)}
    pairs_R = all_pairs_optimal(b, stations, "w_R", "B")
    pairs_T = all_pairs_optimal(b, stations, "w_T", "B")
    out["path_consistency_violations"] = {"R": validate_paths(b, pairs_R, "R"), "T": validate_paths(b, pairs_T, "T")}
    R = {k: divmod(v[0], BIG) for k, v in pairs_R.items()}  # (rides, transfers)
    T = {k: divmod(v[0], BIG) for k, v in pairs_T.items()}  # (transfers, rides)
    a_hops = {k: v[0] for k, v in a_pairs.items()}
    common = [k for k in R if k in a_hops]
    diff = [k for k in common if R[k][0] != a_hops[k]]
    paths = {"pairs_with_a_path": len(R),
             "R_rides_vs_A_hops": {
                 "pairs_compared": len(common), "pairs_with_different_count": len(diff),
                 "rides_fewer_than_A": sum(1 for k in diff if R[k][0] < a_hops[k]),
                 "rides_more_than_A": sum(1 for k in diff if R[k][0] > a_hops[k]),
                 "pairs_reachable_in_A_not_B": len([k for k in a_hops if k not in R]),
                 "pairs_reachable_in_B_not_A": len([k for k in R if k not in a_hops])},
             "R_objective": {"rides": dist_summary([r for r, _ in R.values()]),
                             "transfers": dist_summary([t for _, t in R.values()])},
             "T_objective": {"transfers": dist_summary([t for t, _ in T.values()]),
                             "rides": dist_summary([r for _, r in T.values()])}}
    tk = [k for k in R if k in T]
    paths["tradeoff_R_vs_T"] = {
        "pairs_where_R_path_needs_more_transfers_than_T_path": sum(1 for k in tk if R[k][1] > T[k][0]),
        "pairs_where_T_path_needs_more_rides_than_R_path": sum(1 for k in tk if T[k][1] > R[k][0]),
        "mean_extra_rides_when_minimising_transfers": round(sum(T[k][1] - R[k][0] for k in tk) / max(len(tk), 1), 4),
        "max_extra_rides_when_minimising_transfers": max((T[k][1] - R[k][0] for k in tk), default=0),
        "pairs_reachable_with_zero_transfers": sum(1 for k in tk if T[k][0] == 0)}
    # Does the transfer tie-break (objective R) prune Model A's set of equally short physical routes?
    a_seq = {k: {station_seq(p, station_a) for p in v[1]} for k, v in a_pairs.items()}
    b_seq = {k: {station_seq(p, station_b) for p in v[1]} for k, v in pairs_R.items()}
    both = [k for k in b_seq if k in a_seq]
    paths["route_sets_R_vs_A"] = {
        "pairs_with_several_equally_short_routes_in_A": sum(1 for k in both if len(a_seq[k]) > 1),
        "pairs_whose_route_set_differs_from_A": sum(1 for k in both if a_seq[k] != b_seq[k]),
        "pairs_where_B_route_set_is_a_strict_subset_of_A": sum(1 for k in both if b_seq[k] < a_seq[k])}
    out["paths"] = paths

    btw = {"R": betweenness_from_pairs(pairs_R, station_b, n), "T": betweenness_from_pairs(pairs_T, station_b, n)}
    avec = [a_btw.get(s, 0.0) for s in ids]
    cen = {"betweenness_vs_A": {}}
    for obj in ("R", "T"):
        bv = [btw[obj].get(s, 0.0) for s in ids]
        cen["betweenness_vs_A"][obj] = {
            "spearman": round(spearman(avec, bv), 4),
            "top10_overlap_with_A": len(topk(a_btw, ids) & topk(btw[obj], ids)),
            "stations_with_changed_value": sum(1 for x, y in zip(avec, bv) if abs(x - y) > 1e-12),
            "max_abs_difference": round(max(abs(x - y) for x, y in zip(avec, bv)), 6)}
    art = physical_articulation(b, stations, station_b)
    cen["articulation_stations"] = {
        "count": len(art), "count_in_model_a": len(a_art), "same_set_as_model_a": set(art) == set(a_art),
        "only_in_b": len(set(art) - set(a_art)), "only_in_a": len(set(a_art) - set(art))}
    extra = 0
    for s in ids:
        nb_all = {v[0] for u in b if u[0] == s for v in b[u] if v[0] != s}
        extra += len(nb_all) - len({v[0] for u in b if u[0] == s for v, d in b[u].items()
                                    if d["edge_type"] == RIDE})
    cen["degree"] = {"ride_degree_equals_A_for_all_stations": all(ride_degree(b, s) == a.degree(s) for s in ids),
                     "extra_station_links_via_cross_station_transfers": extra}
    out["centrality"] = cen
    return out, {"betweenness_R": btw["R"], "betweenness_T": btw["T"], "articulation_lost_pairs": art}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, default=DATA)
    ap.add_argument("--out", type=Path, default=HERE)
    args = ap.parse_args(argv)
    stations, connections = load_snapshot(args.data)
    audit = load_audit(args.data)
    manifest = json.loads((args.data / "manifest.json").read_text("utf-8"))
    hashes_ok = all(sha256(args.data / f) == m["sha256"] for f, m in manifest["files"].items())
    if not hashes_ok:
        sys.exit("data/ does not match the v0.1.0 manifest: refusing to run")

    a = build_model_a(stations, connections)
    n = a.number_of_nodes()
    a_pairs = all_pairs_optimal(a, stations, None, "A")
    a_btw = betweenness_from_pairs(a_pairs, station_a, n)
    nxb = nx.betweenness_centrality(a)
    a_btw_nx_ok = all(abs(nxb[s] - a_btw.get(s, 0.0)) < 1e-9 for s in a)
    a_art = physical_articulation(a, stations, station_a)
    a_art_nx_ok = set(a_art) == set(nx.articulation_points(a))

    fusion = fusion_transfers(stations, audit)
    scen = {"B0_rides_only_control": [], "B1_same_station_transfers": fusion}
    if audit:
        scen["B2_plus_confirmed_cross_name_transfers"] = fusion + cross_name_transfers(stations, audit)
        scen["B3_plus_ambiguous_noviciado_sensitivity"] = (
            scen["B2_plus_confirmed_cross_name_transfers"] + ambiguous_transfers(stations, audit))
    prov = {"baseline": "v0.1.0", "osm_data_timestamp": manifest["snapshot"]["osm_data_timestamp"],
            "crtm_records_date": manifest["official_source_reference"]["records_date"],
            "node": "(station_id, line_id)"}

    summary = {
        "meta": {
            "baseline_release": "v0.1.0", "data_hashes_match_manifest": hashes_ok,
            "osm_data_timestamp": prov["osm_data_timestamp"], "crtm_records_date": prov["crtm_records_date"],
            "crtm_audit_available_locally": bool(audit), "networkx": nx.__version__,
            "unit_of_analysis": "physical (aggregated) station; station pairs are unordered",
            "hop_unit": "edge count (never minutes or metres)",
            "objectives": {"R": "fewest ride edges, ties fewest transfer edges",
                           "T": "fewest transfer edges, ties fewest ride edges"},
            "licensing": "Only aggregates are exported; per-station results mix OSM (ODbL) topology with "
                         "CRTM-derived evidence and stay in the git-ignored local/ directory."},
        "model_a": {"nodes": n, "edges": a.number_of_edges(), "components": nx.number_connected_components(a),
                    "station_pairs_total": n * (n - 1) // 2,
                    "reachable_station_pairs": reachable_pair_count(a, station_a),
                    "degree": dist_summary([d for _, d in a.degree()]),
                    "articulation_stations": len(a_art),
                    "hop_distance": dist_summary([v[0] for v in a_pairs.values()])},
        "scenarios": {}}
    local, checks = {}, []
    for name, tr in scen.items():
        b = build_model_b(stations, connections, tr, prov)
        checks += validate_model_b(a, b, stations, connections, tr, name)
        res, loc = analyse_scenario(a, a_pairs, b, stations, a_btw, a_art)
        summary["scenarios"][name] = res
        local[name] = loc
        if name == "B1_same_station_transfers":
            r = res["paths"]["R_rides_vs_A_hops"]
            checks.append((f"{name}: ride counts under R equal Model A hops for every pair, same reachability",
                           r["pairs_with_different_count"] == 0 and r["pairs_reachable_in_A_not_B"] == 0
                           and r["pairs_reachable_in_B_not_A"] == 0, json.dumps(r)))
        checks.append((f"{name}: ride/transfer counts on reconstructed paths match decoded costs",
                       sum(res["path_consistency_violations"].values()) == 0,
                       json.dumps(res["path_consistency_violations"])))
    s0, s1 = summary["scenarios"]["B0_rides_only_control"], summary["scenarios"]["B1_same_station_transfers"]
    checks.append(("B0 reachable pairs (same line only) == B1 pairs reachable with zero transfers",
                   s0["connectivity"]["reachable_station_pairs"] == s1["paths"]["tradeoff_R_vs_T"]["pairs_reachable_with_zero_transfers"],
                   f'{s0["connectivity"]["reachable_station_pairs"]}'))
    checks += [("A: 242 nodes, 277 edges, 1 component (v0.1.0 baseline)",
                (n, a.number_of_edges(), nx.number_connected_components(a)) == (242, 277, 1), ""),
               ("A: own betweenness equals networkx.betweenness_centrality", a_btw_nx_ok, ""),
               ("A: own articulation stations equal networkx.articulation_points", a_art_nx_ok, ""),
               ("data/ files match the v0.1.0 manifest SHA-256", hashes_ok, "")]
    summary["validation"] = [{"check": c, "passed": ok, "detail": d} for c, ok, d in checks]
    summary["validation_all_passed"] = all(ok for _, ok, _ in checks)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "results_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", "utf-8")
    (args.out / "local").mkdir(exist_ok=True)
    (args.out / "local" / "station_level.json").write_text(json.dumps(local, ensure_ascii=False) + "\n", "utf-8")
    failed = [c for c, ok, _ in checks if not ok]
    print(f"checks: {len(checks) - len(failed)}/{len(checks)} passed")
    for c in failed:
        print("FAILED:", c)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
