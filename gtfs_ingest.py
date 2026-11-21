#!/usr/bin/env python3
"""Derive PLANNED (scheduled) in-vehicle times and headways for the v0.1.0 graph from the CRTM Metro GTFS.

Standard library only. Does not touch build_graph.py or the frozen v0.1.0 files in data/.

What the numbers are (verified in research/time_weighted_v05/PLAN.md):
  * In-vehicle leg times in the CRTM Metro GTFS are planned values equal to CRTM segment length / one constant
    speed per line. They are not measured running times and do not vary by time band.
  * Line 3 has no trips in the feed. Its legs are imputed with the same length/speed rule from the CRTM ArcGIS
    layer M4_ParadasPorItinerario, flagged source="imputed_arcgis_length_speed", and the rule is validated against
    every line that has both sources. The speed multiplier is a sensitivity parameter (consumers must sweep it).
  * Headways come from frequencies.txt (windows shifted by each stop's offset in the template).
  * Waiting time and transfer time are NOT computed here. They are parameters recorded in the manifest.

Commands:
    python gtfs_ingest.py fetch           # download feed + CRTM layer into data/gtfs_raw/ (git-ignored; no token needed)
    python gtfs_ingest.py build           # derive data/gtfs_derived/* and the manifest from data/gtfs_raw/*

Licence: CRTM open static-data licence (https://www.crtm.es/licencia-de-uso). Raw data are processed here, never
committed. Powered by CRTM - https://www.crtm.es/. No CRTM endorsement.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import statistics
import sys
import urllib.parse
import urllib.request
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import audit_crtm  # norm(), ALIASES, base_line() are reused so matching is identical to the CRTM audit

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
RAW = DATA / "gtfs_raw"
OUT = DATA / "gtfs_derived"
ITEM_ID = "5c7f2951962540d69ffe8f640d94c246"
GTFS_URL = f"https://www.arcgis.com/sharing/rest/content/items/{ITEM_ID}/data"  # no query string, no token
ITEM_URL = f"https://www.arcgis.com/sharing/rest/content/items/{ITEM_ID}"
ARCGIS_QUERY = f"{audit_crtm.SERVICE}/{audit_crtm.STOPS_TABLE}/query"
ARCGIS_FIELDS = ("NUMEROLINEAUSUARIO,SENTIDO,NUMEROORDEN,DENOMINACION,CODIGOESTACION,"
                 "LONGITUDTRAMOANTERIOR,VELOCIDADTRAMOANTERIOR")
USER_AGENT = "madrid-transit-graph-research/0.5"  # generic on purpose
MATCH_MAX_M = 300.0  # same merge radius as v0.1.0
SYMMETRY_TOL_S = 60.0  # |a->b - b->a| above this is flagged (observed GTFS maximum: 25 s)

H = 3600
# Time bands: ASSUMPTIONS (named, not data). Clock times are GTFS service-day seconds.
# Fridays (4_I15 pattern) are not used. calendar_dates exceptions are not applied: bands describe regular days.
BANDS = {
    "weekday_peak": {"days": "mon_thu", "intervals": [(7 * H, 10 * H), (17 * H, 20 * H)]},
    "weekday_offpeak": {"days": "mon_thu", "intervals": [(6 * H, 7 * H), (10 * H, 17 * H)]},
    "evening": {"days": "mon_thu", "intervals": [(20 * H, 24 * H)]},
    "saturday": {"days": "sat", "intervals": [(6 * H, 24 * H)]},
    "sunday": {"days": "sun", "intervals": [(6 * H, 24 * H)]},
}
DAY_PATTERNS = {"mon_thu": (1, 1, 1, 1, 0, 0, 0), "sat": (0, 0, 0, 0, 0, 1, 0), "sun": (0, 0, 0, 0, 0, 0, 1)}
# Sensitivity grids recorded in the manifest. No source exists for them; they are ranges, not estimates.
PARAMETERS = {
    "wait_factor": {"status": "assumption", "grid": [0.0, 0.25, 0.5],
                    "meaning": "expected wait = factor x headway; 0.5 = random passenger arrival, 0 = timetable-aware"},
    "transfer_seconds": {"status": "assumption (no transfers.txt in the feed)", "grid": [0, 60, 120, 180, 300, 600],
                         "meaning": "illustrative range, not an estimate; 0 reproduces the zero-cost transfers of v0.2"},
    "walk_link_seconds": {"status": "assumption (no pathways.txt in the feed)", "grid": [0, 60, 120, 180, 300, 600],
                          "meaning": "cross-name walk links (Noviciado-Plaza de Espana, Embajadores-Acacias)"},
    "imputed_speed_multiplier": {"status": "assumption", "grid": [0.9, 1.0, 1.1],
                                 "meaning": "applied to the CRTM line speed when imputing legs absent from the feed"},
}


# ----------------------------------------------------------------------------- generic helpers
def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def hms(text: str) -> int:
    h, m, s = text.strip().split(":")
    return int(h) * 3600 + int(m) * 60 + int(s)


def haversine_m(lon1, lat1, lon2, lat2) -> float:
    p = math.pi / 180
    a = math.sin((lat2 - lat1) * p / 2) ** 2 + math.cos(lat1 * p) * math.cos(lat2 * p) * math.sin((lon2 - lon1) * p / 2) ** 2
    return 12742000 * math.asin(math.sqrt(a))


def read_gtfs(zip_path: Path) -> dict[str, list[dict]]:
    """Read the needed tables straight from the zip (nothing is extracted to disk)."""
    out = {}
    with zipfile.ZipFile(zip_path) as z:
        bad = z.testzip()
        if bad:
            raise ValueError(f"corrupt member in {zip_path}: {bad}")
        for name in ("routes", "trips", "stop_times", "stops", "frequencies", "calendar", "feed_info"):
            fn = f"{name}.txt"
            if fn in z.namelist():
                with z.open(fn) as fh:
                    out[name] = list(csv.DictReader(io.TextIOWrapper(fh, encoding="utf-8-sig", newline="")))
            else:
                out[name] = []
        out["_files"] = sorted(z.namelist())
    return out


def line_of_route(short_name: str) -> str:
    short_name = short_name.strip()
    return "R" if short_name.upper() == "R" else f"L{short_name}"


def load_graph(data: Path = DATA):
    st = json.loads((data / "stations.geojson").read_text(encoding="utf-8"))["features"]
    cn = json.loads((data / "connections.geojson").read_text(encoding="utf-8"))["features"]
    nodes = {f["properties"]["id"]: {"name": f["properties"]["name"], "lines": list(f["properties"]["lines"]),
                                     "lonlat": tuple(f["geometry"]["coordinates"])} for f in st}
    edges = {frozenset((f["properties"]["source"], f["properties"]["target"])): set(f["properties"]["lines"]) for f in cn}
    return nodes, edges


def name_index(nodes: dict) -> dict:
    idx = defaultdict(list)
    for nid, n in nodes.items():
        for ln in n["lines"]:
            idx[(audit_crtm.norm(n["name"]), ln)].append(nid)
    return idx


# ----------------------------------------------------------------------------- stop -> node matching
def match_stops(gtfs: dict, nodes: dict) -> dict:
    routes = {r["route_id"]: line_of_route(r["route_short_name"]) for r in gtfs["routes"]}
    trips = {t["trip_id"]: t for t in gtfs["trips"]}
    lines_of_stop = defaultdict(set)
    for r in gtfs["stop_times"]:
        lines_of_stop[r["stop_id"]].add(routes[trips[r["trip_id"]]["route_id"]])
    stops = {s["stop_id"]: s for s in gtfs["stops"]}
    idx = name_index(nodes)
    match, report = {}, []
    for sid in sorted(lines_of_stop):
        s = stops[sid]
        lon, lat = float(s["stop_lon"]), float(s["stop_lat"])
        lns = lines_of_stop[sid]
        nm = audit_crtm.norm(s["stop_name"])
        cand = set()
        for ln in lns:
            cand |= set(idx.get((audit_crtm.ALIASES.get((nm, ln), nm), ln), []))
        tier, nid = "unmatched", None
        if cand:
            nid = min(sorted(cand), key=lambda n: haversine_m(lon, lat, *nodes[n]["lonlat"]))
            tier = "name+line" if len(cand) == 1 else "name+line (ambiguous, nearest)"
        else:
            near = sorted((haversine_m(lon, lat, *n["lonlat"]), i) for i, n in nodes.items() if lns & set(n["lines"]))
            if near and near[0][0] <= MATCH_MAX_M:
                nid, tier = near[0][1], "distance (name differs)"
        d = round(haversine_m(lon, lat, *nodes[nid]["lonlat"]), 1) if nid else None
        if nid and d > MATCH_MAX_M:
            tier += " [>300 m]"
        if nid:
            match[sid] = nid
        report.append({"stop_id": sid, "stop_name": s["stop_name"], "lines": sorted(lns), "node_id": nid,
                       "tier": tier, "distance_m": d})
    return {"match": match, "report": report, "lines_of_stop": {k: sorted(v) for k, v in lines_of_stop.items()}}


# ----------------------------------------------------------------------------- in-vehicle legs
def derive_legs(gtfs: dict, match: dict, edges: dict) -> dict:
    """Directional leg seconds per (line, a, b) (a->b as travelled) from consecutive stop_times."""
    routes = {r["route_id"]: line_of_route(r["route_short_name"]) for r in gtfs["routes"]}
    trips = {t["trip_id"]: t for t in gtfs["trips"]}
    by_trip = defaultdict(list)
    for r in gtfs["stop_times"]:
        by_trip[r["trip_id"]].append(r)
    legs, bad_times, contradictions, unmatched_legs, self_legs = defaultdict(list), [], [], 0, 0
    for tid, rows in by_trip.items():
        rows.sort(key=lambda r: int(r["stop_sequence"]))
        line = routes[trips[tid]["route_id"]]
        for a, b in zip(rows, rows[1:]):
            dt = hms(b["arrival_time"]) - hms(a["departure_time"])
            if dt <= 0:
                bad_times.append((tid, a["stop_id"], b["stop_id"], dt))
                continue
            if a["stop_id"] not in match or b["stop_id"] not in match:
                unmatched_legs += 1
                continue
            na, nb = match[a["stop_id"]], match[b["stop_id"]]
            if na == nb:
                self_legs += 1
                continue
            if frozenset((na, nb)) not in edges:
                contradictions.append((line, na, nb))
                continue
            legs[(line, na, nb)].append(dt)
    return {"legs": legs, "bad_times": bad_times, "contradictions": contradictions,
            "unmatched_legs": unmatched_legs, "self_legs": self_legs}


# ----------------------------------------------------------------------------- headways by band
def _overlap(a0: int, a1: int, intervals) -> int:
    return sum(max(0, min(a1, e) - max(a0, s)) for s, e in intervals)


def _union_len(spans, intervals) -> int:
    clipped = sorted((max(s, bs), min(e, be)) for s, e in spans for bs, be in intervals if min(e, be) > max(s, bs))
    total, cur = 0, None
    for s, e in clipped:
        if cur is None or s > cur[1]:
            if cur:
                total += cur[1] - cur[0]
            cur = [s, e]
        else:
            cur[1] = max(cur[1], e)
    return total + (cur[1] - cur[0] if cur else 0)


def derive_headways(gtfs: dict, match: dict, bands: dict = BANDS) -> dict:
    """Per (node, line, direction, band): trains per hour, headway and the share of the band that is served.

    A frequency window refers to the first stop of the template; it is shifted by the stop's offset in the template.
    """
    routes = {r["route_id"]: line_of_route(r["route_short_name"]) for r in gtfs["routes"]}
    trips = {t["trip_id"]: t for t in gtfs["trips"]}
    cal = {c["service_id"]: tuple(int(c[k]) for k in ("monday", "tuesday", "wednesday", "thursday", "friday",
                                                       "saturday", "sunday")) for c in gtfs["calendar"]}
    by_trip = defaultdict(list)
    for r in gtfs["stop_times"]:
        by_trip[r["trip_id"]].append(r)
    windows = defaultdict(list)
    for f in gtfs["frequencies"]:
        windows[f["trip_id"]].append((hms(f["start_time"]), hms(f["end_time"]), int(f["headway_secs"])))
    exact = [f for f in gtfs["frequencies"] if (f.get("exact_times") or "").strip() == "1"]
    acc = defaultdict(lambda: {"trains": 0.0, "spans": []})
    for tid, rows in by_trip.items():
        t = trips[tid]
        rows.sort(key=lambda r: int(r["stop_sequence"]))
        first = hms(rows[0]["arrival_time"])
        seen = set()
        for r in rows:
            node = match.get(r["stop_id"])
            if node is None or node in seen:
                continue
            seen.add(node)
            off = hms(r["arrival_time"]) - first
            for bname, b in bands.items():
                if cal.get(t["service_id"]) != DAY_PATTERNS[b["days"]]:
                    continue
                for w0, w1, hw in windows.get(tid, []):
                    ov = _overlap(w0 + off, w1 + off, b["intervals"])
                    if ov:
                        k = (node, routes[t["route_id"]], t["direction_id"], bname)
                        acc[k]["trains"] += ov / hw
                        acc[k]["spans"].append((w0 + off, w1 + off))
    out = {}
    for (node, line, direction, bname), v in acc.items():
        total = sum(e - s for s, e in bands[bname]["intervals"])
        out[(node, line, direction, bname)] = {
            "trains_per_hour": round(v["trains"] / (total / H), 4),
            "headway_s": round(total / v["trains"], 1) if v["trains"] > 0 else None,
            "served_fraction": round(_union_len(v["spans"], bands[bname]["intervals"]) / total, 4),
        }
    return {"headways": out, "exact_times_rows": len(exact)}


# ----------------------------------------------------------------------------- imputation from CRTM ArcGIS layer
def arcgis_legs(rows: list[dict], nodes: dict) -> dict:
    """(line, a, b) -> {'seconds','length_m','speed_kmh'} using length / speed, per direction (SENTIDO order)."""
    idx = name_index(nodes)
    seqs = defaultdict(list)
    for r in rows:
        seqs[(str(r["NUMEROLINEAUSUARIO"]).strip(), str(r["SENTIDO"]))].append(r)
    out = {}
    for (ref, _sentido), seq in seqs.items():
        line = audit_crtm.base_line(ref)
        seq.sort(key=lambda r: r["NUMEROORDEN"])
        mapped = []
        for r in seq:
            nm = audit_crtm.norm(r["DENOMINACION"])
            c = idx.get((audit_crtm.ALIASES.get((nm, line), nm), line), [])
            mapped.append(c[0] if len(c) == 1 else None)
        for prev, cur, r in zip(mapped, mapped[1:], seq[1:]):
            length, speed = r.get("LONGITUDTRAMOANTERIOR"), r.get("VELOCIDADTRAMOANTERIOR")
            if prev is None or cur is None or prev == cur or not length or not speed or length <= 0 or speed <= 0:
                continue
            out[(line, prev, cur)] = {"seconds": length / (speed / 3.6), "length_m": float(length),
                                      "speed_kmh": float(speed)}
    return out


def validate_imputation(imputed: dict, gtfs_legs: dict) -> dict:
    """Compare length/speed against GTFS legs on every (line, pair) present in both sources."""
    per_line = defaultdict(lambda: {"ratios": [], "g": 0.0, "i": 0.0})
    for key, rec in imputed.items():
        obs = gtfs_legs.get(key)
        if obs:
            g = statistics.median(obs)
            d = per_line[key[0]]
            d["ratios"].append(rec["seconds"] / g)
            d["g"] += g
            d["i"] += rec["seconds"]
    res = {}
    for ln, d in sorted(per_line.items()):
        r = sorted(d["ratios"])
        res[ln] = {"n_legs": len(r), "median_ratio": round(statistics.median(r), 3), "min_ratio": round(r[0], 3),
                   "max_ratio": round(r[-1], 3), "line_total_ratio": round(d["i"] / d["g"], 3)}
    return res


# ----------------------------------------------------------------------------- assemble ride table
def build_ride_table(edges: dict, legs: dict, imputed: dict) -> tuple[list[dict], list[dict]]:
    rides, missing = [], []
    for pair in sorted(edges, key=lambda p: sorted(p)):
        a, b = sorted(pair)
        for line in sorted(edges[pair]):
            ab, ba = legs.get((line, a, b)), legs.get((line, b, a))
            if ab or ba:
                s_ab = statistics.median(ab) if ab else None
                s_ba = statistics.median(ba) if ba else None
                have = [x for x in (s_ab, s_ba) if x is not None]
                rides.append({"line": line, "a": a, "b": b, "seconds": round(statistics.mean(have), 1),
                              "seconds_ab": s_ab, "seconds_ba": s_ba, "source": "gtfs", "n_obs": len(ab or []) + len(ba or [])})
                continue
            imp = imputed.get((line, a, b)) or imputed.get((line, b, a))
            if imp:
                rides.append({"line": line, "a": a, "b": b, "seconds": round(imp["seconds"], 1), "seconds_ab": None,
                              "seconds_ba": None, "source": "imputed_arcgis_length_speed", "n_obs": 0,
                              "length_m": round(imp["length_m"], 1), "speed_kmh": imp["speed_kmh"]})
            else:
                missing.append({"line": line, "a": a, "b": b})
    return rides, missing


def node_headways(headways: dict) -> list[dict]:
    """Collapse directions: mean of the defined per-direction headways (assumption, stated in the manifest)."""
    grouped = defaultdict(dict)
    for (node, line, direction, band), v in headways.items():
        grouped[(node, line, band)][direction] = v
    rows = []
    for (node, line, band), dirs in sorted(grouped.items()):
        hw = [v["headway_s"] for v in dirs.values() if v["headway_s"]]
        rows.append({"node": node, "line": line, "band": band,
                     "headway_s": round(statistics.mean(hw), 1) if hw else None,
                     "by_direction": {d: v for d, v in sorted(dirs.items())},
                     "min_served_fraction": min(v["served_fraction"] for v in dirs.values())})
    return rows


# ----------------------------------------------------------------------------- IO
def dump(path: Path, obj) -> str:
    text = json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=1) + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def http_get(url: str, params: dict | None = None):
    full = url + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(full, headers={"User-Agent": USER_AGENT})
    return urllib.request.urlopen(req, timeout=180)


def fetch() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    with http_get(ITEM_URL, {"f": "pjson"}) as r:
        item = json.load(r)
    with http_get(GTFS_URL) as r:
        body, headers = r.read(), dict(r.headers)
    (RAW / "metro.zip").write_bytes(body)
    with http_get(ARCGIS_QUERY, {"where": "1=1", "outFields": ARCGIS_FIELDS, "returnGeometry": "false",
                                 "f": "json", "resultRecordCount": 2000}) as r:
        payload = json.load(r)
    if payload.get("exceededTransferLimit"):
        raise SystemExit("ArcGIS layer exceeded the transfer limit: paging is not implemented")
    rows = [f["attributes"] for f in payload["features"]]
    dump(RAW / "m4_paradas_por_itinerario.json", rows)
    dump(RAW / "fetch_info.json", {
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "gtfs_url": GTFS_URL, "item_modified_utc": datetime.fromtimestamp(item["modified"] / 1000, timezone.utc).isoformat(),
        "http_etag": headers.get("ETag"), "bytes": len(body), "arcgis_layer": ARCGIS_QUERY})
    print(f"metro.zip {len(body)} bytes sha256={hashlib.sha256(body).hexdigest()}; arcgis rows {len(rows)}")


def build(zip_path: Path, arcgis_path: Path, data: Path = DATA, out: Path = OUT) -> dict:
    nodes, edges = load_graph(data)
    gtfs = read_gtfs(zip_path)
    arc_rows = json.loads(arcgis_path.read_text(encoding="utf-8"))
    m = match_stops(gtfs, nodes)
    d = derive_legs(gtfs, m["match"], edges)
    hw = derive_headways(gtfs, m["match"])
    imputed = arcgis_legs(arc_rows, nodes)
    rides, missing = build_ride_table(edges, d["legs"], imputed)
    check = validate_imputation(imputed, d["legs"])

    covered = set(m["match"].values())
    uncovered_nodes = sorted(set(nodes) - covered)
    route_lines = {line_of_route(r["route_short_name"]) for r in gtfs["routes"]}
    with_trip_ids = {t["route_id"] for t in gtfs["trips"]}
    trip_lines = {line_of_route(r["route_short_name"]) for r in gtfs["routes"] if r["route_id"] in with_trip_ids}
    out.mkdir(parents=True, exist_ok=True)
    fi = zip_path.parent / "fetch_info.json"
    fetch_info = json.loads(fi.read_text(encoding="utf-8")) if fi.exists() else {}
    h_rides = dump(out / "ride_times.json", rides)
    h_head = dump(out / "headways.json", node_headways(hw["headways"]))
    h_match = dump(out / "match_report.json", {
        "stops": m["report"],
        "nodes_without_gtfs_stop": [{"node_id": n, "name": nodes[n]["name"], "lines": nodes[n]["lines"]} for n in uncovered_nodes],
        "gtfs_leg_pairs_not_in_graph": sorted(set(map(tuple, d["contradictions"]))),
        "rides_without_any_time": missing})
    cal = gtfs["calendar"]
    tiers = defaultdict(int)
    for r in m["report"]:
        tiers[r["tier"]] += 1
    graph_lines = {ln for n in nodes.values() for ln in n["lines"]}
    manifest = {
        "artefact": "planned in-vehicle times and headways derived from the CRTM Metro GTFS (processed data)",
        "status": "NEEDS_VALIDATION; structural/scheduled; not real-time, not demand, not observed",
        "attribution": "Source: CRTM (https://www.crtm.es/), processed data. Powered by CRTM. No CRTM endorsement. "
                       "Topology (c) OpenStreetMap contributors (ODbL).",
        "licence_note": "CRTM open static-data licence https://www.crtm.es/licencia-de-uso. Per-edge and per-station "
                        "outputs join OSM-derived ids (ODbL) with CRTM-derived values, so they are local, git-ignored "
                        "artefacts (same treatment as crtm_audit.json). This manifest holds hashes and aggregates only.",
        "inputs": {
            "gtfs_url": GTFS_URL, "gtfs_sha256": sha256_file(zip_path), "gtfs_bytes": zip_path.stat().st_size,
            "gtfs_feed_version": (gtfs["feed_info"][0].get("feed_version") if gtfs["feed_info"] else None),
            "gtfs_calendar_start": min(c["start_date"] for c in cal), "gtfs_calendar_end": max(c["end_date"] for c in cal),
            "gtfs_files": gtfs["_files"], "fetch": fetch_info,
            "arcgis_layer": ARCGIS_QUERY, "arcgis_sha256": sha256_file(arcgis_path), "arcgis_rows": len(arc_rows),
            "v010_data_sha256": {n: sha256_file(data / n) for n in ("stations.geojson", "connections.geojson", "metadata.json")},
        },
        "outputs_sha256": {"ride_times.json": h_rides, "headways.json": h_head, "match_report.json": h_match},
        "parameters": {"bands": {k: {"days": v["days"], "intervals_s": v["intervals"], "status": "assumption"}
                                 for k, v in BANDS.items()},
                       "friday_used": False, "calendar_dates_exceptions_applied": False,
                       "direction_collapse": "mean of defined per-direction headways (assumption)",
                       "headway_definition": "band length / expected trains in the band (band average; periods with no "
                                             "service stay in the denominator, see served_fraction)",
                       "symmetry_tolerance_s": SYMMETRY_TOL_S, "sweeps": PARAMETERS,
                       "dwell": "none: GTFS arrival == departure; dwell is not modelled"},
        "match": {"gtfs_boarding_stops_used": len(m["report"]), "tiers": dict(sorted(tiers.items())),
                  "nodes": len(nodes), "nodes_with_gtfs_stop": len(covered), "nodes_without_gtfs_stop": len(uncovered_nodes),
                  "gtfs_leg_pairs_not_in_graph": len(set(map(tuple, d["contradictions"]))),
                  "legs_on_unmatched_stops": d["unmatched_legs"], "legs_collapsing_to_one_node": d["self_legs"],
                  "non_positive_leg_times": len(d["bad_times"])},
        "routes": {"in_feed": sorted(route_lines), "with_trips": sorted(trip_lines),
                   "without_trips": sorted(route_lines - trip_lines),
                   "graph_lines_without_gtfs_times": sorted(graph_lines - trip_lines)},
        "rides": {"total_ride_edges": len(rides) + len(missing), "gtfs": sum(r["source"] == "gtfs" for r in rides),
                  "imputed": sum(r["source"].startswith("imputed") for r in rides), "without_any_time": len(missing),
                  "asymmetric_over_tolerance": sum(1 for r in rides if r["seconds_ab"] is not None and r["seconds_ba"] is not None
                                                   and abs(r["seconds_ab"] - r["seconds_ba"]) > SYMMETRY_TOL_S)},
        "imputation_validation_vs_gtfs": check,
        "frequencies": {"exact_times_rows": hw["exact_times_rows"], "mode": "frequency-based (exact_times blank)"},
    }
    dump(out / "gtfs_manifest.json", manifest)
    return manifest


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("fetch")
    b = sub.add_parser("build")
    b.add_argument("--zip", type=Path, default=RAW / "metro.zip")
    b.add_argument("--arcgis", type=Path, default=RAW / "m4_paradas_por_itinerario.json")
    args = ap.parse_args(argv)
    if args.cmd == "fetch":
        fetch()
        return 0
    man = build(args.zip, args.arcgis)
    print(json.dumps({k: man[k] for k in ("match", "rides", "routes", "imputation_validation_vs_gtfs")},
                     indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
