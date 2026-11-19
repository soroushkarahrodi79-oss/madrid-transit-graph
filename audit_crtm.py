#!/usr/bin/env python3
"""Audit the OSM-inferred interchanges in data/stations.geojson against CRTM open data.

Source kept SEPARATE from OSM: CRTM records are fetched at run time, compared, and only the
comparison result is written to data/crtm_audit.json (our station ids + official interchange
codes). Raw CRTM data, names and geometries are NOT stored here, and nothing from CRTM is merged
into stations.geojson / connections.geojson. The output mixes OSM-derived ids (ODbL) with CRTM
identifiers (CRTM licence), so it is a LOCAL artefact: it is git-ignored and not distributed.

CRTM terms (Licencia de datos abiertos y estáticos, https://www.crtm.es/licencia-de-uso):
cite CRTM as source and say whether data is raw or processed; keep the data up to date; do not
distort it. Original CRTM data must be shared under the same licence (derived works need not).
Standard library only.
"""

from __future__ import annotations

import collections
import json
import os
import re
import unicodedata
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

try:
    import certifi

    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
except ImportError:
    pass

DATA = Path(__file__).resolve().parent / "data"
SERVICE = "https://services5.arcgis.com/UxADft6QPcvFyDU1/arcgis/rest/services/M4_Red/FeatureServer"
STATIONS_LAYER, STOPS_TABLE = 0, 5  # M4_Estaciones, M4_ParadasPorItinerario
# Manual name aliases (normalised CRTM name, line) -> normalised OSM name. Naming-only
# differences found by hand; both records occupy the same slot of the same line.
ALIASES = {("vicentealeixandre", "L6"): "metropolitano", ("hospitaldelhenares", "L7"): "hospitaldehenares"}


def get(layer: int, query: str = "") -> dict:
    url = f"{SERVICE}/{layer}" + (f"/query?{query}" if query else "?f=json")
    req = urllib.request.Request(url, headers={"User-Agent": "madrid-transit-graph-prototype/0.1"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.load(resp)


def norm(s: str | None) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().casefold()
    s = re.sub(r"\(.*?\)|\bmetro\b|\bestacion de\b|\s+l\d+$", "", s)
    return re.sub(r"[^a-z0-9]", "", s)


def base_line(ref: str) -> str:
    m = re.match(r"\s*(\d+)", str(ref))
    return f"L{m.group(1)}" if m else str(ref).strip().upper()


def line_key(ln: str) -> tuple[int, str]:
    m = re.match(r"L(\d+)$", ln)
    return (int(m.group(1)), "") if m else (99, ln)  # L1..L12 first, then R


def same_lines(a: list[str], b: list[str]) -> bool:
    """Line sets are equal regardless of order (a lexicographic sort puts L10 before L4)."""
    return set(a) == set(b)


def main() -> None:
    q = "where=1%3D1&outFields=*&returnGeometry=false&f=json"
    stations_layer = get(STATIONS_LAYER)
    rec = [f["attributes"] for f in get(STATIONS_LAYER, q)["features"]]
    stops = [f["attributes"] for f in get(STOPS_TABLE, q)["features"]]
    lines_of = collections.defaultdict(set)
    for a in stops:
        lines_of[a["CODIGOESTACION"]].add(base_line(a["NUMEROLINEAUSUARIO"]))
    recs = []
    for a in rec:
        own = sorted(lines_of[a["CODIGOESTACION"]])
        if a["DENOMINACION"] and own:  # blank official records are skipped
            recs.append({"name": norm(a["DENOMINACION"]), "lines": own, "code": a["CODIGOINTERCAMBIADOR"],
                         "claimed": sorted("L" + x.strip() for x in (a["LINEAS"] or "").split(",") if x.strip()),
                         "date": a["FECHAACTUAL"]})

    ours = {f["properties"]["id"]: f["properties"]
            for f in json.loads((DATA / "stations.geojson").read_text(encoding="utf-8"))["features"]}
    osm_meta = json.loads((DATA / "metadata.json").read_text(encoding="utf-8"))["sources"]["openstreetmap"]
    idx = collections.defaultdict(list)
    for sid, p in ours.items():
        for ln in p["lines"]:
            idx[(norm(p["name"]), ln)].append(sid)
    for r in recs:
        r["stations"] = sorted({s for ln in r["lines"] for s in idx.get(
            (ALIASES.get((r["name"], ln), r["name"]), ln), [])})

    matched_osm = {(sid, ln) for r in recs for sid in r["stations"] for ln in r["lines"]
                   if sid in ours and ln in ours[sid]["lines"]}
    all_osm = {(sid, ln) for sid, p in ours.items() for ln in p["lines"]}
    unmatched_official = sorted((r["name"], ln) for r in recs for ln in r["lines"] if not r["stations"])

    confirmed, unverified, false_pos = [], [], []
    for sid, p in sorted(ours.items()):
        if len(p["lines"]) < 2:
            continue
        rs = [r for r in recs if sid in r["stations"]]
        codes = {r["code"] for r in rs}
        official_lines = sorted({ln for r in rs for ln in r["lines"]}, key=line_key)
        entry = {"station_id": sid, "osm_lines": p["lines"], "official_lines": official_lines,
                 "official_interchange_codes": sorted(map(str, codes))}
        if not rs:
            unverified.append({**entry, "reason": "no matching CRTM record"})
        elif len(codes) == 1 and None not in codes and same_lines(official_lines, p["lines"]):
            confirmed.append({**entry, "official_interchange_code": next(iter(codes))})
        else:
            false_pos.append(entry)  # CRTM does not place these lines in one interchange

    # official interchange groups that join records belonging to different stations of ours
    groups = collections.defaultdict(list)
    for r in recs:
        if r["code"]:
            groups[r["code"]].append(r)
    missing = []
    for code, rs in sorted(groups.items()):
        sts = sorted({s for r in rs for s in r["stations"]})
        lines = sorted({ln for r in rs for ln in r["lines"]}, key=line_key)
        if len(sts) > 1 and len(lines) > 1:
            missing.append({"official_interchange_code": code, "our_station_ids": sts, "lines": lines})
    # records whose own LINEAS field names lines they do not serve, with no shared group code
    for r in recs:
        extra = sorted(set(r["claimed"]) - set(r["lines"]))
        if extra and len(groups.get(r["code"], [])) == 1:
            unverified.append({"station_ids": r["stations"], "own_line": r["lines"],
                               "official_lines_field_also_lists": extra,
                               "official_interchange_code": r["code"],
                               "reason": "CRTM 'LINEAS' field lists more lines but the record has its "
                                         "own interchange code: transfer not confirmed"})

    out = {
        "title": "Audit of OSM-inferred interchanges against CRTM open data",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_official": {
            "provider": "Consorcio Regional de Transportes de Madrid (CRTM)",
            "dataset": "Datos abiertos: Elementos de la Red de Metro (M4_Estaciones, M4_ParadasPorItinerario)",
            "portal": "https://datos.crtm.es/", "service": SERVICE,
            "records_date_field_FECHAACTUAL": sorted({r["date"] for r in recs}),
            "layer_last_data_edit": datetime.fromtimestamp(
                stations_layer["editingInfo"]["dataLastEditDate"] / 1000, timezone.utc).isoformat(timespec="seconds"),
            "licence": "CRTM Licencia de datos abiertos y estáticos", "licence_url": "https://www.crtm.es/licencia-de-uso",
            "attribution": "© CRTM · Powered by CRTM (https://www.crtm.es/). Processed data: only a comparison "
                           "against OSM-derived stations; raw CRTM data not redistributed.",
        },
        "source_osm_reference": {"osm_data_timestamp": osm_meta["osm_data_timestamp"],
                                 "relation_count": len(osm_meta["relation_ids"])},
        "independence_note": "OSM and CRTM are not guaranteed independent: the OpenStreetMap wiki documents "
                             "a CRTM import into OSM whose scope was not analysed here.",
        "method": "Official records matched to our stations by normalised name + line (2 manual name aliases). "
                  "An interchange is 'confirmed' when all its CRTM records share one CODIGOINTERCAMBIADOR and "
                  "the official line set equals ours. Official groups joining records of different stations of "
                  "ours are 'missing'.",
        "summary": {
            "osm_inferred_interchanges": sum(len(p["lines"]) > 1 for p in ours.values()),
            "confirmed": len(confirmed), "inferred_not_confirmed_false": len(false_pos),
            "unverified": len(unverified), "missing_official_transfers": len(missing),
            "official_line_station_records": len(recs),
            "official_records_unmatched": len(unmatched_official),
            "our_line_stations": len(all_osm), "our_line_stations_without_official_record": len(all_osm - matched_osm),
        },
        "confirmed_interchanges": confirmed,
        "false_interchanges": false_pos,
        "unverified": unverified,
        "missing_official_transfers_between_different_names": missing,
        "name_aliases_applied": [{"official_normalised": k[0], "line": k[1], "osm_normalised": v}
                                 for k, v in ALIASES.items()],
        "not_verified": ["stop order / adjacency of each line", "walking time or accessibility of transfers",
                         "service on any date (CRTM static data is not a timetable)"],
    }
    (DATA / "crtm_audit.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out["summary"], indent=1))


if __name__ == "__main__":
    main()
