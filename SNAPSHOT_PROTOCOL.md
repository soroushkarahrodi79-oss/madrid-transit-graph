# Next-snapshot protocol

How to take a new OpenStreetMap snapshot of the Metro de Madrid network **without touching the frozen v0.1.0 files** and
**with the raw Overpass responses preserved**. Written 2026-11-21. Technical reading of the licences, not legal advice.

## Why

The v0.1.0 files in `data/` (`stations.geojson`, `connections.geojson`, `metadata.json`, hashes in `data/manifest.json`)
are the snapshot of OSM state `2026-11-19T18:17:06Z`. The raw Overpass responses were not kept, so that snapshot cannot be
re-derived (`raw_osm_responses_preserved: false`). Running the old script overwrote `data/` with a later OSM state. Both
problems are closed for the next snapshot.

## May the raw responses be committed? (ODbL reading)

Short answer: yes, under conditions. An Overpass response is an extract of the OpenStreetMap database, which is licensed
ODbL 1.0. ODbL allows copying, distributing and adapting it if:

1. **Attribution** "© OpenStreetMap contributors" and a pointer to the licence travel with the data. `raw/RAW_MANIFEST.json`
   carries both and `validate.py` fails if either is missing.
2. **Share-alike.** Any adapted database that is published must be offered under ODbL. The archive is stored as a
   canonical re-serialisation of the parsed response (an adaptation), so it is offered under ODbL, like `data/`.
3. **Keep open.** No technical restrictions on the files (they are plain gzip of JSON).
4. **No mixing with CRTM data.** CRTM data have their own licence with a different "same type of licence" clause that is not
   reconciled with ODbL (NOTICE.md). The raw archive holds OSM only; no CRTM value or file may be put in it.

Doubts, flagged: whether a verbatim extract counts as the Database or as a Derivative Database does not change what is
required above; no jurisdiction-specific advice was sought. The Overpass instance's usage policy asks for modest query
volume: one snapshot is a handful of requests (see "What is archived").

## Procedure

1. New branch from `main`, clean working tree, `python validate.py` passing.
2. Pick a new directory named by the UTC retrieval date, for example `data/snapshots/2026-12-01`.
3. Build:

   ```powershell
   .venv\Scripts\python build_graph.py --out data\snapshots\2026-12-01
   ```

   `--out` is required. The script **refuses** `data/` and any non-empty directory. Overpass often answers 502/504; the script
   retries by itself. Every response it uses is written to `<out>/raw/`, and `<out>/manifest.json` records file hashes, the
   OSM base timestamp, the retrieval time and the hash of `raw/RAW_MANIFEST.json`.
4. Verify: `python validate.py` (checks that every archived file exists, that its SHA-256 matches, and that the ODbL notice is
   present). `python -m unittest discover -s tests` for the helpers.
5. Compare with v0.1.0 and put the differences in the PR text (station, connection and component counts, changed line sets).
   Do not copy anything into the frozen files.
6. Commit the snapshot directory as it is (`.gitattributes` keeps `data/**` byte-for-byte). Add a row to `NOTICE.md` if the
   directory holds anything new. CI fails a PR that changes a frozen file.
7. A new release or tag is the owner's decision. The frozen v0.1.0 stays what it is.
8. A study that uses a new snapshot needs its **own pre-registration** before it runs: it is a new dataset, not a re-run.

## What is archived

`raw/` holds, per snapshot, the responses of: (1) the relation discovery query in `build_graph.py`, (2) City2Graph's own
download of the selected relations (a wrapper around `city2graph.gtfs.sources._request_osm`, a private function of City2Graph
1.1.0; the script stops with a clear message if it is missing), (3) the audit query. Each response is stored as
`NN_<label>.json.gz` and registered in `RAW_MANIFEST.json` with its query, endpoint, retrieval time, OSM base timestamp,
element count and the SHA-256 of the uncompressed canonical JSON.

## What this does not give you

- **Not the server's bytes.** The archive is the parsed response re-serialised canonically (sorted keys, compact, UTF-8). The
  hash proves integrity of the archive, not equality with the HTTP body.
- **No offline rebuild yet.** The archive preserves the inputs. A loader that rebuilds the graph from the archive instead of
  Overpass has not been written; until it exists, `build_graph.py` always downloads the current state.
- **No history.** An Overpass response is a point in time. OSM edit history and the exact query planner state are not kept.
- **Tested on:** one live run into a scratch folder (see PHASE4.md for the outcome) and offline unit tests. Windows 11 and Python
  3.14 only for the live run.
