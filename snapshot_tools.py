#!/usr/bin/env python3
"""Helpers for the next-snapshot protocol (SNAPSHOT_PROTOCOL.md). Standard library only.

A new OSM snapshot is written to its own directory (data/snapshots/<date>/), never over the frozen v0.1.0 files in data/.
Every Overpass response used to build it is archived next to it as canonical JSON (gzip), with the query, the endpoint,
the retrieval time, the OSM base timestamp and a SHA-256 of the JSON bytes in raw/RAW_MANIFEST.json.

What is archived is the PARSED response re-serialised canonically (sorted keys, no extra whitespace, UTF-8), not the
server's raw bytes: the HTTP layer of the libraries used does not expose them. The hash is over that canonical JSON.
"""
from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path

RAW_MANIFEST = "RAW_MANIFEST.json"
LICENCE_NOTE = {
    "licence": "ODbL 1.0 (Open Database License)",
    "attribution": "(c) OpenStreetMap contributors, https://www.openstreetmap.org/copyright",
    "terms": "These files are extracts of the OpenStreetMap database. Keep this notice, keep the attribution and, if you "
             "publish an adapted database, offer it under ODbL. They contain no CRTM data and must not be merged with any.",
}


def canonical(payload) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_manifest(raw_dir: Path) -> dict:
    p = raw_dir / RAW_MANIFEST
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {**LICENCE_NOTE,
            "serialisation": "canonical JSON of the parsed Overpass response (sorted keys, compact separators, UTF-8), "
                             "gzip-compressed; sha256_json is over the uncompressed canonical JSON",
            "entries": []}


def archive_payload(raw_dir: Path, name: str, query: str, endpoint: str, payload: dict, retrieved_at: str) -> dict:
    """Write one response to raw_dir/<name>.json.gz and register it in RAW_MANIFEST.json. Returns the manifest entry."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    manifest = _read_manifest(raw_dir)
    if any(e["name"] == name for e in manifest["entries"]):
        raise ValueError(f"raw response name already archived: {name}")
    data = canonical(payload)
    (raw_dir / f"{name}.json.gz").write_bytes(gzip.compress(data, compresslevel=9, mtime=0))
    entry = {"name": name, "file": f"{name}.json.gz", "endpoint": endpoint, "query": query,
             "retrieved_at": retrieved_at, "osm_base_timestamp": (payload.get("osm3s") or {}).get("timestamp_osm_base"),
             "elements": len(payload.get("elements", [])), "bytes_json": len(data), "sha256_json": sha256(data)}
    manifest["entries"] = sorted(manifest["entries"] + [entry], key=lambda e: e["name"])
    (raw_dir / RAW_MANIFEST).write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return entry


def verify_raw_archive(raw_dir: Path) -> list[str]:
    """Return a list of problems (empty = consistent): licence notice, every file present, hashes equal."""
    problems: list[str] = []
    mp = raw_dir / RAW_MANIFEST
    if not mp.exists():
        return [f"{RAW_MANIFEST} missing"]
    m = json.loads(mp.read_text(encoding="utf-8"))
    if "ODbL" not in m.get("licence", "") or "OpenStreetMap" not in m.get("attribution", ""):
        problems.append("licence or attribution notice missing")
    if not m.get("entries"):
        problems.append("no entries")
    listed = set()
    for e in m.get("entries", []):
        listed.add(e["file"])
        f = raw_dir / e["file"]
        if not f.exists():
            problems.append(f"{e['file']} missing")
            continue
        data = gzip.decompress(f.read_bytes())
        if sha256(data) != e["sha256_json"] or len(data) != e["bytes_json"]:
            problems.append(f"{e['file']} does not match its recorded hash")
        if not e.get("retrieved_at") or not e.get("query"):
            problems.append(f"{e['file']} lacks query or retrieval time")
    extra = {p.name for p in raw_dir.glob("*.json.gz")} - listed
    if extra:
        problems.append(f"files not in the manifest: {sorted(extra)}")
    return problems
