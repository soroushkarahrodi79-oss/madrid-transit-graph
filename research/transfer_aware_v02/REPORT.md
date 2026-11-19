# Transfer-aware vs aggregated graph — Madrid Metro (research v0.2, branch `research/transfer-aware-v02`)

**Question.** How does explicit modelling of line transfers affect connectivity, shortest paths and station
centrality compared with the station-aggregated graph of v0.1.0?

**Decision: MODIFY** (see [Decision](#decision)). All numbers below come from `results_summary.json`, produced by
`experiment.py` (62 internal checks, all passed) and covered by `test_experiment.py` (17 tests, all passed).

## 1. Data and evidence

| Input | Version | Role |
|---|---|---|
| `data/stations.geojson`, `connections.geojson` | v0.1.0 snapshot, OSM state 2026-11-19T18:17:06Z; SHA-256 checked against `manifest.json` on every run | only source of topology (Models A and B) |
| `data/crtm_audit.json` (local, **not distributed**) | CRTM records 2026-05-29, audit generated 2026-11-19 | transfer evidence: 38 confirmed same-station interchanges, 2 official cross-name transfers, 1 ambiguous (Noviciado) |

No OSM regeneration, no network access, `data/` untouched. OSM and CRTM are not independent (OSM wiki documents a CRTM
import; scope not analysed), so "confirmed" means *consistent with*, not *independently verified*.

## 2. Models

| | Model A (baseline) | Model B (transfer-aware) |
|---|---|---|
| Node | physical station (aggregated) | station-line state `(station_id, line_id)` |
| Edge | undirected adjacency, one edge per segment however many lines share it | `ride`: consecutive stations on one line (one per segment *per line*); `transfer`: between line states of one interchange |
| Interchange | implicit (node fusion) | explicit transfer edges, each with `source`, `evidence`, `confidence` |
| Size | 242 nodes, 277 edges, 1 component | 291 nodes, 280 ride edges, 0–66 transfer edges depending on scenario |

Scenarios: **B0** rides only (control, no transfers) · **B1** + 61 same-station transfers (38 stations, all
CRTM-confirmed) · **B2** = B1 + 3 transfer edges for the two official cross-name interchanges (Embajadores L3–Acacias L5;
Santo Domingo L2–Callao L3/L5) · **B3** = B2 + 2 edges linking Noviciado L2 to Plaza de España L3/L10. B3 is an
explicitly labelled *sensitivity* scenario: CRTM says Noviciado's `LINEAS` field cites L3 and L10 but gives it its own
interchange code, and does not name the partner station; Plaza de España (285 m, nearest station serving L3 and L10) is
**my inference**. Transfer edges carry no time, distance or penalty.

**Path semantics (B).** For a physical pair (o, d) a path may start at *any* line state of o and end at *any* line state
of d at no cost; boarding and alighting are not transfers. Two lexicographic objectives, no weighting between rides and
transfers: **R** = fewest ride edges, ties → fewest transfers (reproduces A's hop count); **T** = fewest transfers,
ties → fewest rides. Costs are encoded as `rides·10⁴ + transfers` (or swapped) and decoded; decoded counts are verified
against every reconstructed path. A hop is an edge count, never minutes or metres.

**Station-level centrality in B (aggregation).** Betweenness is defined over *physical* station pairs: the share of
pairs whose optimal paths pass through station s (s not an endpoint), where a path "passes through" s if it uses any
state of s, averaged over the distinct optimal *station sequences* of each pair (so parallel line states on a shared
segment are not double-counted), normalised by (n−1)(n−2)/2. The same code computes A's betweenness and matches
`networkx.betweenness_centrality` exactly. Degree is the number of distinct neighbouring stations over ride edges.
Articulation: station whose removal (all its states) disconnects some other station pair.
*Remaining non-equivalence:* B's betweenness depends on the objective (R vs T), which has no behavioural validation;
it is not passenger demand and not comparable to raw state-level values.

## 3. Results (unit: unordered physical station pairs; denominator 29,161 = 242·241/2)

**Connectivity**

| | A | B0 rides only | B1 | B2 | B3 |
|---|---|---|---|---|---|
| Components (state graph) | 1 | 13 | 1 | 1 | 1 |
| Largest component, stations | 242 | 33 (13.6 %) | 242 | 242 | 242 |
| Reachable station pairs | 29,161 (100 %) | 3,759 (12.9 %) | 29,161 | 29,161 | 29,161 |

Transfer representation explains *all* connectivity: without transfers the network is 13 line components. With the
validated same-station transfers B1 is identical to A. The cross-name transfers cannot add connectivity because A was
already connected.

**Shortest paths (B1 vs A).** Ride count under R equals A's hop count for all 29,161 pairs (mean 14.04, median 13,
max 42) — an exact projection, not a finding. What B adds is the transfer dimension:

- Fewest-rides route (R): transfers mean 1.93, median 2, max 6; 2,749 pairs need 0 transfers.
- Fewest-transfers route (T): transfers mean 1.13, max 3; rides mean 16.42 (vs 14.04). 3,759 pairs (12.9 %) are
  reachable on one line (equals B0's reachable pairs — independent cross-check).
- **15,449 pairs (53.0 %)** have a genuine trade-off: the fewest-rides route needs more transfers than the
  fewest-transfers route, which costs on average **+2.38 rides** (max +25).
- A has several equally short physical routes for 11,580 pairs (39.7 %); B's transfer tie-break narrows the route set for
  10,213 of them (88 %). A cannot express this.
- 1,010 same-line pairs are *not* fastest on their own line (the shortest-hop route changes line).

**Cross-name transfers (B2, B3 vs A).** 1,184 pairs (4.1 %) get fewer ride edges (B2); 1,346 (4.6 %) in B3; none get more.
Caveat: a transfer link between *different* stations counts zero rides, so part of this gain is the unmodelled walk. The
same gain could be had in A by adding three edges, so it is not an argument for the multilayer form.

**Centrality (station level, vs A; 242 stations)**

| Scenario / objective | Spearman ρ | Top-10 overlap | Stations with changed value | Max abs. difference* |
|---|---|---|---|---|
| B1 R | 0.994 | 10/10 | 157 | 0.051 |
| B1 T | 0.812 | 7/10 | 157 | 0.116 |
| B2 R / T | 0.985 / 0.811 | 10 / 7 | 157 / 157 | 0.050 / 0.116 |
| B3 R / T | 0.982 / 0.804 | 9 / 7 | 157 / 157 | 0.050 / 0.112 |

\*in share of station pairs (normalised betweenness). Degree: ride-degree identical to A for every station in every
scenario (identity by construction). Articulation stations: 84 in A and in B1–B3, identical sets. B0 values (187
"articulation" stations) describe isolated lines and are not meaningful.

## 4. Validation (all passed)

Synthetic networks with known answers (cross at one station, cross-name transfer, rides-vs-transfers trade-off,
circular line, shared segment, path graph, articulation, multi-line origin) and the real snapshot. Checked: every ride
edge belongs to one valid line and matches exactly one (connection, line); no inter-line ride edges; no self-loops or
duplicate edges (builders raise); every transfer edge has evidence, confidence and source; circular lines (L6, L12)
detected as simple cycles and every other line a connected tree; station identity and line sets consistent across A
and B; own betweenness and articulation equal NetworkX on A; B1 ride counts equal A hops; decoded transfer/ride counts
equal counts on all reconstructed paths; v0.1.0 data hashes and 242/277/1 preserved. A deliberately corrupted graph is
rejected by the validator.

## 5. Limitations and uncertainties

- Every measure that A can express is identical in B1; the value of B is the transfer dimension. No external
  ground truth (timetables, ridership, walking times) was used, so none of this establishes *real* accessibility or that
  the T or R objective matches passenger behaviour.
- Any line change at a station is one transfer regardless of walking effort; same-station cliques come from the v0.1.0
  name-fusion (≤ 300 m), validated against CRTM (38/38) that is not independent of OSM.
- Stop order and adjacency were not contrasted with CRTM. Noviciado's partner is inferred. Lines are tree-or-loop; no
  branching service patterns are modelled. Single Madrid snapshot; no uncertainty intervals.
- Licensing: per-station results mix OSM (ODbL) and CRTM-derived evidence, so they are kept in git-ignored `local/`;
  only aggregates are committed (`NOTICE.md` unchanged). The mixed Model B database is not exported.

## Decision

**MODIFY.** Model B is valid and its comparisons are interpretable, but demonstrable value is confined to one
dimension: transfer counts and the rides-vs-transfers trade-off (53 % of pairs), plus a moderate change in betweenness
only under objective T (ρ = 0.81). Connectivity, hop distance, degree and articulation points are identical to A, and
the cross-name transfers are expressible as plain edges in A. Not GO because nothing here is validated against an
external reference; not NO-GO because the transfer dimension is real and A cannot represent it. Recommended
modification before any map change: keep B as a research layer for transfer-count analysis, and validate adjacency and
transfers against an independent source (e.g. a CRTM timetable or walking-time data) before attributing meaning to T-based
rankings.

## Reproduce

```powershell
.venv\Scripts\python research/transfer_aware_v02/experiment.py
.venv\Scripts\python -m unittest discover -s research/transfer_aware_v02
```

Without the local `data/crtm_audit.json` (create it with `audit_crtm.py`) only B0 and B1 run, and same-station transfers
are labelled `unvalidated`.
