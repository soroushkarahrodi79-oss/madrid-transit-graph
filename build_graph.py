#!/usr/bin/env python3
"""Build the Metro de Madrid station graph from OpenStreetMap with City2Graph 1.1.0.

Pipeline (data -> graph -> export; the map in index.html only reads data/*):

1. Discover Metro de Madrid ``route=subway`` relations in OSM (Overpass).
2. ``city2graph.load_osm_transport``      -> ordered stop sequences per relation.
3. ``city2graph.travel_summary_graph``    -> stop-level undirected graph.
   ``city2graph.gdf_to_nx`` / ``validate_gdf`` -> NetworkX graph + schema checks.
4. Station consolidation (own code): OSM stop areas are mapped *per line*, so the
   transfers between lines are inferred with an explicit, documented rule.
5. Independent audit: the exported stop order is compared with the raw OSM
   relation members (parsed here, not by City2Graph).
6. Export GeoJSON + metadata.json.

Only topology is used. City2Graph's OSM loader also fills placeholder calendars and
headways (GTFS "simple-v1" assumptions); they are discarded and never exported.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import warnings
from collections import Counter, defaultdict
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

try:  # Windows' certificate store can contain expired roots; prefer certifi's bundle.
    import certifi

    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
except ImportError:
    pass

import city2graph as c2g
import networkx as nx
import pandas as pd
import geopandas as gpd
from shapely.geometry import LineString, Point

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"

OVERPASS = "https://overpass-api.de/api/interpreter"
USER_AGENT = "madrid-transit-graph-prototype/0.1 (research prototype)"
NETWORK = "Metro de Madrid"
BBOX = (40.25, -3.95, 40.65, -3.35)  # south, west, north, east: only used for discovery
MERGE_MAX_M = 300.0  # interchange rule: same normalised name, all members within this
LINE_ORDER = [f"L{i}" for i in range(1, 13)] + ["R"]
DISPLAY_COLOUR_OVERRIDE = {"R": "#8c8c8c"}  # OSM colour is "white": invisible on a light map
STOP_ROLES = {"stop", "stop_entry_only", "stop_exit_only"}


# --------------------------------------------------------------------------- helpers
def retry(fn, what: str, attempts: int = 8, wait: float = 30.0):
    """Public Overpass servers are often at capacity (HTTP 502/504): back off and retry."""
    for i in range(1, attempts + 1):
        try:
            return fn()
        except (RuntimeError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            print(f"  [{what}] attempt {i}/{attempts} failed: {str(exc)[:120]}", file=sys.stderr)
            if i == attempts:
                raise
            time.sleep(wait)


def overpass(query: str, timeout: float = 180) -> dict:
    req = urllib.request.Request(
        OVERPASS,
        data=urllib.parse.urlencode({"data": query}).encode(),
        headers={"User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.load(resp)
    if payload.get("remark"):
        raise RuntimeError(f"incomplete Overpass response: {payload['remark']}")
    return payload


def strip_line_suffix(name: str) -> str:
    """'Plaza Elíptica L11' -> 'Plaza Elíptica'; 'El Casar (Metro L3)' -> 'El Casar'."""
    name = re.sub(r"\s*\(Metro(?:\s+L\d+)?\)$", "", name.strip())
    return re.sub(r"\s+(L\d+|R|Metro)$", "", name)


def norm_name(name: str) -> str:
    base = unicodedata.normalize("NFKD", strip_line_suffix(name))
    return base.encode("ascii", "ignore").decode().casefold().strip()


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", norm_name(name)).strip("-")


def haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dx = math.radians(lon2 - lon1) * math.cos((p1 + p2) / 2)
    return 6371008.8 * math.hypot(dx, p2 - p1)


def line_key(ref: str) -> int:
    return LINE_ORDER.index(ref) if ref in LINE_ORDER else len(LINE_ORDER)


# --------------------------------------------------------------------------- steps
def discover_relations() -> list[dict]:
    s, w, n, e = BBOX
    q = (
        f'[out:json][timeout:90];relation["type"="route"]["route"="subway"]'
        f'["network"="{NETWORK}"]({s},{w},{n},{e});out tags;'
    )
    payload = retry(lambda: overpass(q), "discovery")
    rels = [
        {"id": r["id"], "ref": r["tags"].get("ref"), "name": r["tags"].get("name"),
         "colour": r["tags"].get("colour")}
        for r in payload["elements"]
    ]
    if not rels:
        raise SystemExit("No Metro de Madrid subway relations found")
    return sorted(rels, key=lambda r: (line_key(r["ref"]), r["id"]))


def load_feed(relation_ids: list[int]):
    """City2Graph step 1: OSM PTv2 relations -> ordered stops (feed in a DuckDB connection)."""
    return retry(
        lambda: c2g.load_osm_transport(
            relation_ids=relation_ids,
            modes="subway",
            stop_level="station",
            on_invalid="raise",
            use_source_tags=False,
        ),
        "load_osm_transport",
    )


def feed_provenance(con) -> dict:
    rows = dict(
        con.execute(
            "select field, value from _city2graph_metadata "
            "where field in ('retrieved_at','source_timestamp','endpoint')"
        ).fetchall()
    )
    return {"osm_data_timestamp": rows.get("source_timestamp"),
            "retrieved_at": rows.get("retrieved_at"), "endpoint": rows.get("endpoint")}


def stop_level_graph(con):
    """City2Graph step 2: stop-level graph; verify it equals the pairs in stop_times."""
    nodes, edges = c2g.travel_summary_graph(con, directed=False)
    # travel_time_sec / frequency derive from placeholder timing: drop them.
    edges = edges.drop(columns=["travel_time_sec", "frequency"], errors="ignore")
    nodes["stop_lon"] = nodes["stop_lon"].astype(float)
    nodes["stop_lat"] = nodes["stop_lat"].astype(float)
    c2g.validate_gdf(nodes, edges)
    g = c2g.gdf_to_nx(nodes, edges)
    c2g.validate_nx(g)
    return nodes, edges, g


def line_segments(con) -> pd.DataFrame:
    """Consecutive stop pairs per OSM relation, straight from the feed's stop_times."""
    return con.execute(
        """
        select a, b, line, route_id from (
          select lag(st.stop_id) over (
                   partition by st.trip_id order by cast(st.stop_sequence as integer)) as a,
                 st.stop_id as b, r.route_short_name as line, r.route_id as route_id
          from stop_times st join trips t using (trip_id) join routes r using (route_id)
        ) where a is not null and a <> b
        """
    ).df()


def consolidate(nodes: pd.DataFrame, seg: pd.DataFrame):
    """Merge per-line stop nodes of one physical station (inferred, flagged as derived)."""
    seg_lines = defaultdict(set)
    for r in seg.itertuples():
        seg_lines[r.a].add(r.line)
        seg_lines[r.b].add(r.line)
    groups = defaultdict(list)
    for sid, row in nodes.iterrows():
        groups[norm_name(row["stop_name"])].append(sid)

    stop_to_station, stations, unmerged = {}, {}, []
    for nn, members in sorted(groups.items()):
        coords = [(nodes.at[m, "stop_lon"], nodes.at[m, "stop_lat"]) for m in members]
        dmax = max((haversine_m(*a, *b) for a in coords for b in coords), default=0.0)
        parts = [members] if dmax <= MERGE_MAX_M else [[m] for m in members]
        if len(parts) > 1:
            unmerged.append({"name_key": nn, "max_distance_m": round(dmax, 1), "stops": members})
        for k, part in enumerate(parts):
            sid = slug(nn) + (f"-{k + 1}" if len(parts) > 1 else "")
            names = Counter(strip_line_suffix(nodes.at[m, "stop_name"]) for m in part)
            lines = sorted({ln for m in part for ln in seg_lines[m]}, key=line_key)
            stations[sid] = {
                "name": names.most_common(1)[0][0],
                "lon": sum(nodes.at[m, "stop_lon"] for m in part) / len(part),
                "lat": sum(nodes.at[m, "stop_lat"] for m in part) / len(part),
                "lines": lines,
                "osm_stop_ids": sorted(part),
            }
            for m in part:
                stop_to_station[m] = sid
    assert len(stop_to_station) == len(nodes)
    return stations, stop_to_station, unmerged


def station_edges(seg: pd.DataFrame, stop_to_station: dict, stations: dict):
    pairs = defaultdict(lambda: {"lines": set(), "relations": set()})
    self_loops = 0
    for r in seg.itertuples():
        u, v = stop_to_station[r.a], stop_to_station[r.b]
        if u == v:
            self_loops += 1
            continue
        key = tuple(sorted((u, v)))
        pairs[key]["lines"].add(r.line)
        pairs[key]["relations"].add(int(r.route_id.rsplit(":", 1)[1]))
    edges = []
    for (u, v), info in sorted(pairs.items()):
        su, sv = stations[u], stations[v]
        edges.append({
            "id": f"{u}--{v}", "source": u, "target": v,
            "source_name": su["name"], "target_name": sv["name"],
            "lines": sorted(info["lines"], key=line_key),
            "osm_relation_ids": sorted(info["relations"]),
            "straight_length_m": round(haversine_m(su["lon"], su["lat"], sv["lon"], sv["lat"]), 1),
        })
    return edges, self_loops


def analyse(stations: dict, edges: list[dict]):
    """City2Graph GeoDataFrames -> validated -> NetworkX; indicators from NetworkX."""
    nodes_gdf = gpd.GeoDataFrame(
        [{"station_id": k, "name": v["name"], "geometry": Point(v["lon"], v["lat"])}
         for k, v in stations.items()], crs="EPSG:4326").set_index("station_id")
    edges_gdf = gpd.GeoDataFrame(
        [{"from_id": e["source"], "to_id": e["target"],
          "geometry": LineString([(stations[e["source"]]["lon"], stations[e["source"]]["lat"]),
                                  (stations[e["target"]]["lon"], stations[e["target"]]["lat"])])}
         for e in edges], crs="EPSG:4326").set_index(["from_id", "to_id"])
    c2g.validate_gdf(nodes_gdf, edges_gdf)
    g = c2g.gdf_to_nx(nodes_gdf, edges_gdf)
    c2g.validate_nx(g)
    ids = {n: d["_original_index"] for n, d in g.nodes(data=True)}
    degree = {ids[n]: d for n, d in g.degree()}
    comps = sorted((sorted(ids[n] for n in c) for c in nx.connected_components(g)), key=len, reverse=True)
    return degree, comps


AUDIT_MAX_OFFSET_M = 250.0  # raw stop node vs feed station position at the same sequence slot


def loose_name(name: str) -> str:
    """Aggressive label normalisation, only for the audit (never for ids or merging)."""
    n = norm_name(name)
    n = re.sub(r"\(metro\)|^estacion de ", "", n)
    return re.sub(r"[^a-z0-9]", "", n)


def audit_against_raw_osm(relation_ids: list[int], con) -> dict:
    """Compare per-relation stop order (feed) with raw OSM members parsed independently.

    A slot passes if the labels match (loosely) OR the raw OSM stop node lies within
    AUDIT_MAX_OFFSET_M of the feed station at the same position in the sequence.
    """
    id_list = ",".join(map(str, relation_ids))
    q = (f"[out:json][timeout:120];relation(id:{id_list})->.r;.r out body;"
         "node(r.r)->.n;.n out qt;")
    payload = retry(lambda: overpass(q), "audit")
    nodes = {e["id"]: e for e in payload["elements"] if e["type"] == "node"}
    feed = defaultdict(list)
    for rid, name, lon, lat in con.execute(
        "select t.route_id, s.stop_name, s.stop_lon, s.stop_lat from stop_times st "
        "join trips t using (trip_id) join stops s using (stop_id) "
        "order by t.route_id, cast(st.stop_sequence as integer)"
    ).fetchall():
        feed[rid].append((norm_name(name), float(lon), float(lat), name))

    def collapse(seq):  # the loader collapses consecutive duplicate stops
        return [x for i, x in enumerate(seq) if i == 0 or x[0] != seq[i - 1][0]]

    order_failures, label_only, slots, name_equal, max_off, unnamed = [], [], 0, 0, 0.0, 0
    rels = [e for e in payload["elements"] if e["type"] == "relation"]
    for rel in rels:
        raw = []
        for m in rel["members"]:
            if m["type"] == "node" and m.get("role") in STOP_ROLES and m["ref"] in nodes:
                nd = nodes[m["ref"]]
                nm = nd.get("tags", {}).get("name")
                unnamed += nm is None
                raw.append((norm_name(nm or ""), nd["lon"], nd["lat"], nm))
        got, want = collapse(feed[f"osm:relation:{rel['id']}"]), collapse(raw)
        if len(got) != len(want):
            order_failures.append({"relation": rel["id"], "feed_len": len(got), "osm_len": len(want)})
            continue
        for pos, (g, w) in enumerate(zip(got, want)):
            slots += 1
            off = haversine_m(g[1], g[2], w[1], w[2])
            max_off = max(max_off, off)
            if loose_name(g[3]) == loose_name(w[3] or ""):
                name_equal += 1
            elif off <= AUDIT_MAX_OFFSET_M:
                label_only.append({"relation": rel["id"], "position": pos, "feed_name": g[3],
                                   "osm_stop_node_name": w[3], "offset_m": round(off)})
            else:
                order_failures.append({"relation": rel["id"], "position": pos, "feed_name": g[3],
                                       "osm_stop_node_name": w[3], "offset_m": round(off)})
    return {"relations_checked": len(rels), "stop_slots_checked": slots,
            "slots_label_match": name_equal,
            "slots_label_differs_position_matches": label_only,
            "order_failures": order_failures,
            "max_position_offset_m": round(max_off),
            "stop_members_without_name_tag": unnamed,
            "method": "per relation, the ordered role stop* node members of the raw OSM relation "
                      "vs the ordered stop_times of the City2Graph feed (consecutive duplicates "
                      f"collapsed); a slot passes when labels match or the raw stop node is within "
                      f"{AUDIT_MAX_OFFSET_M:.0f} m of the feed station"}


# --------------------------------------------------------------------------- export
def write_geojson(path: Path, features: list[dict]):
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features},
                               ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")


def main(argv=None):
    argparse.ArgumentParser(description=__doc__.split("\n")[0]).parse_args(argv)
    DATA.mkdir(exist_ok=True)

    print("1/6 discovering relations in OSM ...")
    rels = discover_relations()
    ids = [r["id"] for r in rels]
    print(f"    {len(ids)} relations: {sorted({r['ref'] for r in rels}, key=line_key)}")

    print("2/6 City2Graph load_osm_transport ...")
    con = load_feed(ids)
    prov = feed_provenance(con)

    print("3/6 City2Graph travel_summary_graph + gdf_to_nx ...")
    nodes, c2g_edges, g_stop = stop_level_graph(con)
    seg = line_segments(con)
    pairs_feed = {frozenset((r.a, r.b)) for r in seg.itertuples()}
    pairs_c2g = {frozenset(i) for i in c2g_edges.index}
    assert pairs_feed == pairs_c2g, "stop_times pairs differ from City2Graph edges"
    stop_components = nx.number_connected_components(g_stop)

    print("4/6 consolidating stations ...")
    stations, stop_to_station, unmerged = consolidate(nodes, seg)
    edges, self_loops = station_edges(seg, stop_to_station, stations)
    degree, comps = analyse(stations, edges)

    print("5/6 auditing against raw OSM relations ...")
    audit = audit_against_raw_osm(ids, con)

    print("6/6 exporting ...")
    neighbours = defaultdict(set)
    for e in edges:
        neighbours[e["source"]].add(e["target"])
        neighbours[e["target"]].add(e["source"])
    comp_of = {sid: i for i, c in enumerate(comps) for sid in c}
    st_feats = [{
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [round(s["lon"], 6), round(s["lat"], 6)]},
        "properties": {
            "id": sid, "name": s["name"], "lines": s["lines"], "n_lines": len(s["lines"]),
            "is_interchange": len(s["lines"]) > 1, "degree": degree[sid],
            "neighbours": sorted(neighbours[sid]), "component": comp_of[sid],
            "osm_stop_ids": s["osm_stop_ids"],
        },
    } for sid, s in sorted(stations.items())]
    ed_feats = [{
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": [
            [round(stations[e["source"]]["lon"], 6), round(stations[e["source"]]["lat"], 6)],
            [round(stations[e["target"]]["lon"], 6), round(stations[e["target"]]["lat"], 6)]]},
        "properties": e,
    } for e in edges]
    write_geojson(DATA / "stations.geojson", st_feats)
    write_geojson(DATA / "connections.geojson", ed_feats)

    ranked = sorted(stations, key=lambda k: (-degree[k], stations[k]["name"]))
    top = [{"id": k, "name": stations[k]["name"], "degree": degree[k], "lines": stations[k]["lines"]}
           for k in ranked[:10]]
    tied_beyond_top = sum(degree[k] == degree[ranked[9]] for k in ranked[10:])
    line_info = {}
    for ref in sorted({r["ref"] for r in rels}, key=line_key):
        rr = [r for r in rels if r["ref"] == ref]
        line_info[ref] = {
            "colour_osm": rr[0]["colour"],
            "colour_display": DISPLAY_COLOUR_OVERRIDE.get(ref, rr[0]["colour"]),
            "osm_relations": [{"id": r["id"], "name": r["name"]} for r in rr],
            "n_stations": sum(ref in s["lines"] for s in stations.values()),
            "n_connections": sum(ref in e["lines"] for e in edges),
        }
    meta = {
        "title": "Metro de Madrid station graph (prototype)",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sources": {
            "openstreetmap": {
                "what": f"route=subway relations with network={NETWORK} (PTv2), via Overpass API",
                "endpoint": prov["endpoint"], "osm_data_timestamp": prov["osm_data_timestamp"],
                "retrieved_at": prov["retrieved_at"], "relation_ids": ids,
                "license": "ODbL 1.0", "attribution": "© OpenStreetMap contributors",
                "license_url": "https://www.openstreetmap.org/copyright",
            },
            "basemap": "OpenStreetMap standard tiles (tile.openstreetmap.org), © OpenStreetMap contributors; "
                       "loaded by index.html at view time, not part of the exported data",
        },
        "software": {"city2graph": version("city2graph"), "networkx": nx.__version__,
                     "geopandas": gpd.__version__, "python": sys.version.split()[0]},
        "city2graph_operations": [
            "load_osm_transport (OSM PTv2 relations -> ordered stops; timing/calendar discarded)",
            "travel_summary_graph (stop-level undirected graph)",
            "validate_gdf / gdf_to_nx / validate_nx (schema checks, NetworkX graph)",
        ],
        "method": {
            "nodes": "Physical stations. OSM stop areas are mapped per line, so stop nodes with the "
                     f"same normalised name (line suffix, accents, case removed) whose members lie "
                     f"within {MERGE_MAX_M:.0f} m of each other are merged. This interchange rule is "
                     "DERIVED, not an OSM fact (OSM has only 2 stop_area_group relations here).",
            "edges": "Consecutive stops in OSM relation order (both directions merged, "
                     "undirected). Geometry is a straight schematic segment, not the track alignment.",
            "not_included": "No timetables, frequencies, travel times, or service-validity claims. "
                            "Metro Ligero and Cercanías are out of scope.",
        },
        "indicators": {  # derived from the exported graph; not OSM attributes
            "n_stations": len(stations), "n_connections": len(edges),
            "n_components": len(comps), "component_sizes": [len(c) for c in comps],
            "n_interchange_stations": sum(len(s["lines"]) > 1 for s in stations.values()),
            "max_degree": degree[ranked[0]], "top_degree": top,
            "top_degree_note": f"top 10 by degree, ties broken alphabetically; "
                               f"{tied_beyond_top} more station(s) tie with the 10th",
            "degree_definition": "number of distinct adjacent stations; NOT ridership, "
                                 "importance or accessibility",
        },
        "lines": line_info,
        "quality": {
            "stop_level_components_before_consolidation": stop_components,
            "stop_level_nodes_before_consolidation": len(nodes),
            "same_name_groups_not_merged": unmerged,
            "self_loops_dropped": self_loops,
            "raw_osm_audit": audit,
        },
        "limitations": [
            "An OSM relation does not prove an operating service on any given date.",
            "Interchange links are inferred from names and distance (<= %d m), not from OSM tags." % MERGE_MAX_M,
            "Interchanges and line-station counts were compared with CRTM open data by audit_crtm.py, "
            "which writes data/crtm_audit.json locally; that file is not distributed (mixed OSM/CRTM "
            "licensing). CRTM data is not merged into this graph, and stop sequences/adjacency were "
            "not compared with CRTM.",
            "Edges are straight lines between stations, not the real alignment.",
        ],
    }
    (DATA / "metadata.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    ind = meta["indicators"]
    print(f"done: {ind['n_stations']} stations, {ind['n_connections']} connections, "
          f"{ind['n_components']} component(s); audit: "
          f"{len(audit['order_failures'])} order failure(s), "
          f"{len(audit['slots_label_differs_position_matches'])} label-only difference(s)")


if __name__ == "__main__":
    main()
