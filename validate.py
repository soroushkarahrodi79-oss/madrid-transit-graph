#!/usr/bin/env python3
"""Offline consistency checks on data/*.  Standard library only (independent of City2Graph).

These checks prove the exported files are internally consistent and match the reported
indicators. They do NOT prove that the OSM data is complete or that the services run.
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path

import audit_crtm  # same_lines / line_key are regression-tested below

DATA = Path(__file__).resolve().parent / "data"
MADRID_BBOX = (-4.1, 40.2, -3.3, 40.7)  # lon_min, lat_min, lon_max, lat_max (generous)
FORBIDDEN_KEYS = {"frequency", "headway", "headway_secs", "travel_time", "travel_time_sec",
                  "calendar", "service_id", "schedule"}

results: list[tuple[str, bool, str]] = []
notes: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))


def load(name: str):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def main() -> int:
    stations = load("stations.geojson")["features"]
    conns = load("connections.geojson")["features"]
    meta = load("metadata.json")
    sp = {f["properties"]["id"]: f for f in stations}
    ind = meta["indicators"]

    # ---- identifiers and references
    check("station ids unique", len(sp) == len(stations), f"{len(stations)} features")
    eids = [f["properties"]["id"] for f in conns]
    check("connection ids unique", len(set(eids)) == len(eids))
    refs_ok = all(f["properties"]["source"] in sp and f["properties"]["target"] in sp for f in conns)
    check("every connection references existing stations", refs_ok)
    check("no self-loops", all(f["properties"]["source"] != f["properties"]["target"] for f in conns))
    undirected = [frozenset((f["properties"]["source"], f["properties"]["target"])) for f in conns]
    check("no duplicate undirected connections", len(set(undirected)) == len(undirected))
    stop_ids = [s for f in stations for s in f["properties"]["osm_stop_ids"]]
    check("each OSM stop belongs to exactly one station", len(stop_ids) == len(set(stop_ids)),
          f"{len(stop_ids)} source stops")

    # ---- coordinates
    def in_box(lon, lat):
        return MADRID_BBOX[0] <= lon <= MADRID_BBOX[2] and MADRID_BBOX[1] <= lat <= MADRID_BBOX[3]

    check("station coordinates inside Madrid region",
          all(in_box(*f["geometry"]["coordinates"]) for f in stations))
    ends_ok = True
    for f in conns:
        a, b = f["geometry"]["coordinates"]
        ends_ok &= (a == sp[f["properties"]["source"]]["geometry"]["coordinates"]
                    and b == sp[f["properties"]["target"]]["geometry"]["coordinates"])
    check("connection endpoints coincide with their stations", ends_ok)

    # ---- graph recomputation (pure python, independent of City2Graph/NetworkX)
    adj = defaultdict(set)
    for f in conns:
        s, t = f["properties"]["source"], f["properties"]["target"]
        adj[s].add(t)
        adj[t].add(s)
    check("no isolated stations", all(adj[i] for i in sp))
    check("exported degree == recomputed degree",
          all(f["properties"]["degree"] == len(adj[i]) for i, f in sp.items()))
    check("neighbours property consistent with connections",
          all(sorted(adj[i]) == f["properties"]["neighbours"] for i, f in sp.items()))
    seen, comps = set(), []
    for start in sp:
        if start in seen:
            continue
        stack, comp = [start], set()
        while stack:
            n = stack.pop()
            if n in comp:
                continue
            comp.add(n)
            stack.extend(adj[n] - comp)
        seen |= comp
        comps.append(comp)
    comps.sort(key=len, reverse=True)
    check("exported component index consistent",
          all(sp[n]["properties"]["component"] == i for i, c in enumerate(comps) for n in c))

    # ---- line attribution
    rel_ids = set(meta["sources"]["openstreetmap"]["relation_ids"])
    check("connection lines belong to both end stations",
          all(set(f["properties"]["lines"]) <= set(sp[f["properties"]["source"]]["properties"]["lines"])
              & set(sp[f["properties"]["target"]]["properties"]["lines"]) for f in conns))
    check("connection relation ids are among the extracted OSM relations",
          all(set(f["properties"]["osm_relation_ids"]) <= rel_ids and f["properties"]["osm_relation_ids"]
              for f in conns))
    check("stations are interchange iff >1 line",
          all(f["properties"]["is_interchange"] == (len(f["properties"]["lines"]) > 1) for f in stations))

    # ---- indicators == exported data
    check("n_stations matches", ind["n_stations"] == len(stations), f"{ind['n_stations']}")
    check("n_connections matches", ind["n_connections"] == len(conns), f"{ind['n_connections']}")
    check("n_components matches", ind["n_components"] == len(comps), f"{ind['n_components']}")
    check("component sizes match", ind["component_sizes"] == [len(c) for c in comps])
    check("interchange count matches",
          ind["n_interchange_stations"] == sum(f["properties"]["is_interchange"] for f in stations))
    ranked = sorted(sp, key=lambda i: (-len(adj[i]), sp[i]["properties"]["name"]))
    check("top-degree list matches",
          [(t["id"], t["degree"]) for t in ind["top_degree"]] == [(i, len(adj[i])) for i in ranked[:10]])
    lines_ok = True
    for ref, li in meta["lines"].items():
        lines_ok &= li["n_stations"] == sum(ref in f["properties"]["lines"] for f in stations)
        lines_ok &= li["n_connections"] == sum(ref in f["properties"]["lines"] for f in conns)
    check("per-line counts match", lines_ok)

    # ---- provenance and scientific-honesty guards
    osm = meta["sources"]["openstreetmap"]
    check("provenance metadata present",
          all(osm.get(k) for k in ("license", "attribution", "osm_data_timestamp", "retrieved_at",
                                   "relation_ids")) and meta["software"].get("city2graph") == "1.1.0")
    keys = {k for f in stations + conns for k in f["properties"]}
    check("no timing/frequency/service attributes exported", not (keys & FORBIDDEN_KEYS))
    audit = meta["quality"]["raw_osm_audit"]
    check("raw-OSM audit: no stop-order failures", not audit["order_failures"],
          f"{audit['stop_slots_checked']} slots, {len(audit['slots_label_differs_position_matches'])} label-only")

    # ---- regression: the CRTM audit once compared lexicographically sorted line lists (L10 < L4)
    check("line-set comparison is order-independent (L10 regression)",
          audit_crtm.same_lines(["L10", "L4", "L5"], ["L4", "L5", "L10"])
          and not audit_crtm.same_lines(["L4"], ["L4", "L5"])
          and sorted(["L10", "L4", "R", "L2"], key=audit_crtm.line_key) == ["L2", "L4", "L10", "R"])

    # ---- published snapshot identity (hashes of the distributed data files)
    mf = load("manifest.json")
    drift = [n for n, v in mf["files"].items()
             if hashlib.sha256((DATA / n).read_bytes()).hexdigest() != v["sha256"]]
    if drift:
        notes.append(f"NOTE data differ from the published v0.1.0 snapshot ({', '.join(drift)}): expected "
                     "after regenerating with build_graph.py (a later OSM state), not an error by itself")
    else:
        check("data files match the SHA-256 hashes of the published snapshot", True, f"{len(mf['files'])} files")
    check("manifest snapshot identity equals metadata.json when data are unchanged",
          drift or mf["snapshot"]["osm_data_timestamp"] == osm["osm_data_timestamp"])

    # ---- CRTM audit file (separate official source; derived comparison only)
    path = DATA / "crtm_audit.json"  # local artefact, not distributed (mixed OSM/CRTM licensing)
    if not path.exists():
        notes.append("SKIPPED crtm_audit.json checks: file not present (it is not distributed); "
                     "run audit_crtm.py to create it, then rerun validate.py")
    else:
        au = load("crtm_audit.json")
        sm = au["summary"]
        check("audit covers every inferred interchange exactly once",
              sm["osm_inferred_interchanges"] == ind["n_interchange_stations"]
              and len(au["confirmed_interchanges"]) + len(au["false_interchanges"])
              + sum("station_id" in u for u in au["unverified"]) == ind["n_interchange_stations"])
        audited = [c["station_id"] for c in au["confirmed_interchanges"] + au["false_interchanges"]]
        check("audited station ids exist in stations.geojson", all(i in sp for i in audited))
        raw = {"DENOMINACION", "CODIGOESTACION", "geometry", "X", "Y"}
        check("audit stores no raw CRTM records or geometries",
              not (raw & set(json.dumps(au, ensure_ascii=False).replace('"', " ").split())))
        check("CRTM attribution and licence recorded",
              "CRTM" in au["source_official"]["attribution"] and au["source_official"]["licence_url"])

    # ---- planned-time artefacts (v0.5): manifest is distributed, per-edge outputs are local (CRTM + OSM ids)
    gm_path = DATA / "gtfs_derived" / "gtfs_manifest.json"
    if not gm_path.exists():
        notes.append("SKIPPED gtfs_derived checks: manifest not present (v0.5 artefacts are optional)")
    else:
        gm = json.loads(gm_path.read_text(encoding="utf-8"))
        check("gtfs manifest: attribution, status and no-endorsement wording",
              "Powered by CRTM" in gm["attribution"] and "No CRTM endorsement" in gm["attribution"]
              and gm["status"].startswith("NEEDS_VALIDATION"))
        check("gtfs manifest: v0.1.0 snapshot hashes unchanged",
              all(gm["inputs"]["v010_data_sha256"].get(n) == v["sha256"] for n, v in mf["files"].items()))
        sw = gm["parameters"]["sweeps"]
        check("gtfs manifest: every assumed parameter is named, justified and has a sweep grid",
              {"wait_factor", "transfer_seconds", "walk_link_seconds", "imputed_speed_multiplier"} <= set(sw)
              and all(len(s["grid"]) >= 3 and s["status"] and s["meaning"] for s in sw.values()))
        check("gtfs manifest: feed vintage recorded",
              bool(gm["inputs"]["gtfs_calendar_end"] and gm["inputs"]["gtfs_sha256"]),
              f"calendar {gm['inputs']['gtfs_calendar_start']}..{gm['inputs']['gtfs_calendar_end']}")
        check("gtfs manifest: no ride edge lacks a time and no GTFS adjacency contradicts the graph",
              gm["rides"]["without_any_time"] == 0 and gm["match"]["gtfs_leg_pairs_not_in_graph"] == 0
              and gm["match"]["non_positive_leg_times"] == 0)
        check("gtfs manifest: imputed legs only where a line has no GTFS trips",
              gm["rides"]["imputed"] == 0 or bool(gm["routes"]["graph_lines_without_gtfs_times"]))
        gd = DATA / "gtfs_derived"
        local = [n for n in gm["outputs_sha256"] if (gd / n).exists()]
        if len(local) < len(gm["outputs_sha256"]):
            notes.append("SKIPPED local gtfs_derived output checks: run gtfs_ingest.py fetch && build to create them")
        else:
            check("gtfs outputs match the SHA-256 hashes in the manifest",
                  all(hashlib.sha256((gd / n).read_bytes()).hexdigest() == h for n, h in gm["outputs_sha256"].items()))
            rides = json.loads((gd / "ride_times.json").read_text(encoding="utf-8"))
            check("planned ride times: no zero or negative values",
                  all(r["seconds"] > 0 and all(r[k] is None or r[k] > 0 for k in ("seconds_ab", "seconds_ba"))
                      for r in rides), f"{len(rides)} ride edges")
            edge_lines = {(frozenset((f["properties"]["source"], f["properties"]["target"])), ln)
                          for f in conns for ln in f["properties"]["lines"]}
            check("planned ride times: exactly one per (connection, line), all referencing the graph",
                  {(frozenset((r["a"], r["b"])), r["line"]) for r in rides} == edge_lines and len(rides) == len(edge_lines))
            tol = gm["parameters"]["symmetry_tolerance_s"]
            check("planned ride times: directional symmetry within tolerance",
                  all(abs(r["seconds_ab"] - r["seconds_ba"]) <= tol for r in rides
                      if r["seconds_ab"] is not None and r["seconds_ba"] is not None), f"tolerance {tol:.0f} s")
            timed = defaultdict(set)
            for r in rides:
                timed[r["a"]].add(r["b"])
                timed[r["b"]].add(r["a"])
            check("planned ride times: every station has a timed ride", set(timed) == set(sp))
            seen_t, stack = set(), [next(iter(sp))]
            while stack:
                n = stack.pop()
                if n not in seen_t:
                    seen_t.add(n)
                    stack.extend(timed[n] - seen_t)
            check("planned ride times: every station reachable on the timed graph", seen_t == set(sp),
                  f"{len(seen_t)}/{len(sp)}")
            hws = json.loads((gd / "headways.json").read_text(encoding="utf-8"))
            check("headways: positive, nodes exist in the graph",
                  all(h["node"] in sp and (h["headway_s"] is None or h["headway_s"] > 0) for h in hws),
                  f"{len(hws)} node-line-band rows")
        raw_zip = DATA / "gtfs_raw" / "metro.zip"
        if raw_zip.exists():
            check("raw GTFS zip matches the SHA-256 recorded in the manifest",
                  hashlib.sha256(raw_zip.read_bytes()).hexdigest() == gm["inputs"]["gtfs_sha256"])
        else:
            notes.append("SKIPPED raw GTFS hash check: data/gtfs_raw/metro.zip not present (gtfs_ingest.py fetch)")

    width = max(len(n) for n, *_ in results)
    for name, ok, detail in results:
        print(f"[{'PASS' if ok else 'FAIL'}] {name.ljust(width)}  {detail}")
    failed = [n for n, ok, _ in results if not ok]
    for n in notes:
        print(f"[note] {n}")
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
