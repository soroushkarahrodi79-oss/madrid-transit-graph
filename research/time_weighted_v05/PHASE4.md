# Phase 4 report: engineering hygiene

**Status: NEEDS_VALIDATION for the research; this phase changes tooling and documentation only.** No result, data file or
hash of the frozen v0.1.0 snapshot was modified.

## 1. What was done

| Item | Where | Notes |
| --- | --- | --- |
| CI matrix | `.github/workflows/ci.yml` | Ubuntu and Windows × Python 3.12, 3.13, 3.14 (6 jobs). Runs `validate.py`, `build_explorer.py --check` and the unit tests of `tests/` and the four research folders. Read-only token (`contents: read`); no secret is used. |
| Frozen-snapshot guard | same file, job `frozen-snapshot` (pull requests) | `git diff --exit-code` against the base branch for the three `data/` files and `data/manifest.json`. A PR that changes them fails. |
| Next-snapshot protocol | `SNAPSHOT_PROTOCOL.md`, `snapshot_tools.py`, `build_graph.py` | `build_graph.py` now requires `--out`, refuses `data/` and non-empty folders, archives every Overpass response and writes a snapshot manifest. |
| Raw-archive check | `validate.py` | For any `data/snapshots/*/raw`: files exist, SHA-256 equal, ODbL notice and attribution present. None exists yet (a note says so). |
| Tests | `tests/test_snapshot_tools.py` (12) | Offline: archive, tamper, missing/unlisted file, duplicate name, write guards, City2Graph recorder with a fake request. |
| Requirements | `requirements.txt` | `numpy` and `scipy` declared as direct dependencies (they were only transitive). |
| NOTICE.md | rows for future snapshots and for the new MIT files | Spanish, as the rest of the file. |
| README (Spanish) | limitations rewritten, protocol, citation, file list | Removes statements that were no longer true ("no simulation", "28 checks"). |
| CITATION.cff | repository root | Only fields verified in the repository, see section 3. |

## 2. ODbL decision for raw Overpass responses (written, with doubts)

Decision: **allowed, under four conditions**: attribution and licence notice shipped with the files (in
`RAW_MANIFEST.json`, enforced by `validate.py`); the archive offered under ODbL (it is an adaptation: canonical
re-serialisation of the parsed response); no technical restriction; and **no CRTM data in that folder**. Full reading and
procedure in `SNAPSHOT_PROTOCOL.md`; the matching row is in `NOTICE.md`. This is a technical reading of the licence text,
not legal advice, and nobody with legal training has reviewed it.

## 3. CITATION.cff: what was verified and what was left out

| Field | Source of verification |
| --- | --- |
| title | README heading |
| author (family and given name) | `LICENSE` copyright holder and the commit author name |
| version `0.1.0`, `date-released` 2026-11-19 | GitHub release v0.1.0 (published 2026-11-19T20:25:29Z) and the tag |
| url, repository-code | `gh repo view` |
| license `MIT` | `LICENSE` (code only; the abstract and message state the data licences) |

**Left out, unknown:** ORCID, affiliation, DOI, email. **Not run:** `cffconvert` validation (not installed; it would need a
download). The author name is already public in the repository; remove it if you prefer another form.

## 4. Evidence

Commands on Windows 11, Python 3.14.5. Trimmed outputs.

```
$ python validate.py                          # local checkout, with local CRTM-derived files
51/51 checks passed

$ # clean checkout of HEAD in a temporary git worktree (no .gitignored local files), as CI sees it
$ python validate.py                          -> 39/39 checks passed   (the 12 local-file checks are skipped with a note)
$ python build_explorer.py --check            -> public file matches a fresh build
$ python -m unittest discover -s tests                                   -> Ran 12 tests ... OK
$ python -m unittest discover -s research/transfer_aware_v02             -> Ran 18 tests ... OK (skipped=1)
$ python -m unittest discover -s research/network_robustness_v04         -> Ran 6 tests ... OK
$ python -m unittest discover -s research/evidence_informed_robustness   -> Ran 12 tests ... OK
$ python -m unittest discover -s research/time_weighted_v05              -> Ran 45 tests ... OK (skipped=1)
```

**Live test of the protocol** (one real snapshot written to a scratch folder outside the repository and not committed;
2026-11-21, Windows 11, Python 3.14.5): `python build_graph.py --out <scratch>`. The public Overpass server answered HTTP 502
three times on discovery and twice on the audit before succeeding; the retry logic coped.

```
done: 242 stations, 277 connections, 1 component(s); audit: 0 order failure(s), 2 label-only difference(s)
raw/: 01_discovery 1.8 KB, 02_city2graph 333 KB, 03_city2graph 18 KB, 04_audit 21 KB (gzip) + RAW_MANIFEST.json
verify_raw_archive(raw) -> []            # all hashes match; ODbL notice and attribution present
stations.geojson, connections.geojson    -> byte-identical to the frozen v0.1.0 files (OSM base 2026-11-21T13:03:34Z vs 2026-11-19T18:17:06Z)
frozen data/ files: SHA-256 unchanged     # build wrote only to the scratch folder
```

This shows the protocol works end to end once, and that the topology did not change in those two days. It is one run on one
machine. It does not show that the archive can rebuild the graph (no loader exists).

**CI.** At the last check, before this commit: the `frozen-snapshot` job and the three Ubuntu jobs (Python 3.12, 3.13, 3.14)
had passed, and the three Windows jobs were still running. The pull request's checks are the authority; if a job fails, the
failure and its fix belong in this report. The clean-checkout run above is a local Windows / Python 3.14 approximation of one job.

## 5. What failed or needed attention

- A shell `cd` into a site-packages folder (to read City2Graph's source) changed the working directory of later commands; it
  was noticed and reset before anything was written there.
- The public Overpass server answered HTTP 502 five times in total during the live test, as the README already warned; the
  script's retry logic coped (about 3 minutes of waiting).
- Nothing else failed in this phase.

## 6. Unknown, assumed, not done

- **Unknown:** the final result of the three Windows CI jobs (running at the last check). The Ubuntu jobs on 3.12, 3.13 and
  3.14 had passed, so wheels for Python 3.14 on Linux do exist for these requirements.
- **Assumed:** GitHub Actions `actions/checkout@v4` and `actions/setup-python@v5` exist and accept the inputs used (pinned by
  tag, not by commit SHA, because the SHAs could not be verified offline).
- **Not built:** a loader that rebuilds the graph from the archived responses instead of downloading again; a verbatim
  (byte-for-byte) copy of the HTTP bodies; branch-protection rules (a repository setting, not code); a Pages deployment
  workflow (Pages is configured outside the repository).
- **Dependency on a private function:** the City2Graph response capture wraps `city2graph.gtfs.sources._request_osm` of
  version 1.1.0. A different version may break it; the script stops with a clear message, and `requirements.txt` pins 1.1.0.
- **Literature:** none cited and none verified (`[X]`).

## 7. Decisions that are the owner's

1. **Require the CI to pass before merging** (branch protection) and whether to pin the actions to commit SHAs.
2. **When to take the next snapshot.** It is a new dataset: it needs its own pre-registration before any study uses it, and a
   tag or release is your call.
3. **The author name in CITATION.cff**, and whether you want an ORCID or affiliation added.
4. **NOTICE.md and the ODbL reading** are still unreviewed by anyone legally qualified.
5. `research/temporal_validation_v03/` is still untracked.
