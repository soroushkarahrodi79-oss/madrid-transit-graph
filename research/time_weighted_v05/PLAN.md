# Time-weighted Madrid Metro graph (v0.5) — Phase 0 plan and feasibility

Status: **PLAN. Nothing beyond the feasibility probes below has been run.** No pre-registration exists yet (it is a Phase 2
deliverable). Publication status of the repository stays **NEEDS_VALIDATION**.

## 1. Research question

> Which Metro de Madrid stations, when (a) their interchange function is disabled or (b) the station is closed,
> produce the largest increase in **scheduled** shortest travel time over all station pairs, by time band? Is that
> ranking explained by simple structural metrics (degree, betweenness, line count)?

"Scheduled" means derived from the last official CRTM Metro GTFS timetable feed. It is not real-time, not observed and not
demand-weighted. Both questions concern the fixed v0.1.0 graph (242 stations, OSM snapshot 2026-11-19T18:17:06Z).

## 2. Why the B1-vs-E line is closed

From `research/absolute_comparability/REPORT.md`:

- "E is never costlier than B1" follows from edge inclusion (E contains every lifted B1 edge). It is a property of the
  construction, not an empirical result.
- 80 % (R) and 90 % (T) of B1's deteriorations that are absent in E occur on pairs E already served more cheaply when
  intact. Only 724 R and 140 T observations (at most 0.07 % of 1,106,708) start at equal cost and are absorbed by a walk.
- The sign of the Sol–Gran Vía effect flips with the assumption "the corridor stays open during the disruption".
- Costs are lexicographic hop/transfer counts. No available input could separate the models further. More runs of the
  same structure would add parameters, not evidence. The line stays exhausted until time-weighted or observed data exist.

## 3. What Phase 0 established

| Item | Finding | Consequence |
| --- | --- | --- |
| Access | Official Metro GTFS (`GTFS Red de Metro`, ArcGIS item `5c7f2951962540d69ffe8f640d94c246`, owner `ConsorcioRegional`) is public: HTTP 200, no token. Size 1,503,773 B, identical to the v0.3 copy (SHA-256 `16e8e53c…38204fb7`). | Phase 1 needs nothing manual for this feed. |
| Currency | Item last modified **2025-05-30**; `feed_version` 20250527; `calendar` ends **2026-05-27** (expired); `feed_info` start/end blank. EMT, Cercanías, interurban, urban bus and Metro Ligero items were modified in Nov 2026; Metro was not. | Everything is "last published timetable", not current service. |
| Coverage | 120 trip templates over 12 routes. **Line 3 has a route record and zero trips.** Four service patterns (Sat, Sun, Mon–Thu, Fri). | See next row and R2. |
| L3 impact | 19 of 291 station-line states, **12 nodes served only by L3** and 17 of 277 edges have no GTFS time. Every other line is complete. | Needs a stated handling (R2). |
| Files | `stop_times.txt` (2,216 rows, second resolution), `frequencies.txt` (790 windows, all `exact_times` blank), `calendar*.txt`, `shapes.txt`. **`transfers.txt` and `pathways.txt` absent.** | Transfer time has no data source: it is a parameter. |
| Mapping | 272/272 used boarding stops match a v0.1.0 node by (normalised name, line), the same rule as `audit_crtm.py`. Stop-to-node distance median 43 m, max 280 m. 0 unmatched stops, 0 GTFS adjacencies absent from the graph, 260/277 edges observed (the 17 missing are all L3). | Node mapping is feasible. Caveat: OSM and CRTM are not independent (OSM imported CRTM data), so a clean match is partly expected and is not independent confirmation. |
| What the times are | In-vehicle leg times ≈ CRTM segment length ÷ one constant speed per line (lines 1, 2, 4, 5, 8, 11: Pearson 0.98–0.999, median ratio 1.00; reversed-direction control −0.94…0.15). Running-time profiles do **not** vary with service day or time band (lines 7, 9, 10 show two profiles each, which are short vs full patterns). Direction asymmetry ≤ 25 s. | GTFS gives **planned distance ÷ speed times**, not measured running times. Time-band variation can come only from headways. |
| Waiting | Headways exist per window (210–1,350 s); 54 distinct window shapes across lines and services. | Waiting is data-driven, but "half the headway" still assumes random passenger arrivals. |
| Licence | CRTM open static-data licence, read from the official page: reuse commercial and non-commercial; cite CRTM as source stating raw vs processed; "Powered by CRTM" with link on digital platforms; keep update-date and reuse metadata; no implied endorsement; **the reuser must ensure the information shown is always up to date**; original data shareable under the same licence type, value-added derived works may use other licences. | Do not commit raw GTFS (the "same type of licence" wording is ambiguous and the "up to date" clause conflicts with a stale feed). Ship a fetch script and a hash manifest. Owner to review. |

## 4. Hypotheses (to be formalised in `PRE_REGISTRATION.md` before any Phase 2 run)

- **H1 (explanation).** The station ranking by mean scheduled-time increase under closure is explained by betweenness:
  Spearman ρ with hop-betweenness ≥ 0.9 and negligible incremental explanatory power of the simulation. **Prior
  expectation: H1 true** (weighted and unweighted centrality usually agree on a network of this size). If H1 holds, the
  reported outcome is **ABSTAIN / NO ROBUST DIFFERENCE**, with the same prominence as a positive result.
- **H2 (disruption type).** Interchange-disabled and station-closed rankings differ in the top-k set (k = 10). No prior.
- **H3 (time band).** The ranking is stable across time bands (ρ between bands ≥ 0.9). In-vehicle times do not vary by
  band, so any instability can come only from headways and the transfer parameter.

Thresholds (0.9, k = 10) are placeholders to be fixed and justified in the pre-registration.

## 5. Baselines and null models

- Baselines: degree, line count, hop-betweenness (v0.2 code, validated against NetworkX), time-weighted betweenness.
  Time-weighted betweenness is the strongest baseline: if it explains the ranking, the disruption simulation adds nothing
  over a centrality.
- Null: random disruption sets of equal size, seeded, to calibrate what counts as a large increase.
- Inference caveat: the 242 stations are the population, not a sample. Station-level quantities are deterministic;
  uncertainty comes from assumptions (transfer time, waiting, L3 handling), not from sampling. Reported intervals will be
  sensitivity ranges, not confidence intervals.

## 6. Stopping criteria

Stop and **FREEZE** (write the decision memo, mark the README) if any of these holds:

1. No defensible handling of Line 3 (R2), and the conclusion flips between L3 imputed and L3 excluded.
2. Phase 2 yields ABSTAIN and the owner judges the result not worth a Phase 3 research framing. Phase 3 may still proceed
   as a clearly labelled portfolio visual, never as a finding.
3. The ranking is not stable across the sensitivity grid (transfer time, waiting, L3), so no conclusion survives.
4. A licence doubt about publishing derived timings that the owner cannot resolve.

## 7. Risks

| # | Risk | Mitigation |
| --- | --- | --- |
| R1 | "Time-weighted" overstates the data: in-vehicle time is planned length ÷ line speed, so the weighting is mostly distance weighting | Call it "planned/scheduled time" everywhere; test whether the time-weighted ranking differs from a pure length-weighted one |
| R2 | L3 missing from the feed (a central trunk line) | Primary: impute L3 from CRTM segment length ÷ CRTM line speed (24.99 km/h, `M4_ParadasPorItinerario`), a method that reproduces the other lines' GTFS leg times (ratio 1.00, range about 0.84–1.30 per leg, six lines checked); label it an assumption. Sensitivity: speed range and L3 excluded |
| R3 | Feed expired (2026-05-27) and 18 months old; licence "always up to date" clause | State the vintage on every output; owner decides; check whether a newer complete feed exists (Section 8) |
| R4 | No transfer times | Parameter swept over a stated range; never a single hidden constant; results reported per value |
| R5 | No external validation: v0.3 found no dated trip-linked arrival data | Phase 2 searches for documented closures with citable official URLs; otherwise NEEDS_VALIDATION |
| R6 | Name matching is circular (OSM imported CRTM) | Report as consistency, not verification; geometry check done (max 280 m) |
| R7 | Multiplicity: 5 bands × 2 disruptions × 4 baselines | One pre-registered primary endpoint, Holm correction on the rest |
| R8 | Raw feed not committed, so numbers are not self-contained | Fetch script plus SHA-256 manifest; the feed currently resolves to the same bytes as on 2026-11-19 |
| R9 | Literature positioning: weighted vs unweighted vulnerability of metro networks is well studied | Cite only verified references, unverified ones marked `[X]`; claim limited to Madrid, scheduled times, transfer-only intervention |

## 8. Open items for the owner

- `CRTM_GTFS_TOKEN` is **not set in this session's environment** (checked as a boolean only; the value was never printed).
  The Metro GTFS used here needs no token. The token matters only for a possible newer or complete feed (for example
  National Access Point record 1134, which returned HTTP 401 without a key in v0.3). Tell me which endpoint it belongs to,
  and make it visible to this app (user environment variable, then restart the app) if you want that route tried.
- Decide whether `research/temporal_validation_v03/` (untracked, not in `origin/main`) is committed as its own PR.

## 9. Recommendation

**Conditional GO, limited to Phase 1 and Phase 2, with the FREEZE triggers of Section 6.**

For GO: node mapping is clean (100 %, no contradictions); Phase 1 is cheap and static; the Phase 2 question is well
defined and a negative answer (ABSTAIN) is reportable and honest.

Against, stated plainly: the planned times are length ÷ speed, L3 is absent, the feed is expired, transfers are
unmeasured, and nothing here can be validated against observations. The best attainable status is **NEEDS_VALIDATION**.
The likely scientific outcome is ABSTAIN. This will not become a finding a thesis committee accepts as "resilience". It
can become a documented methodological result plus a visual portfolio piece with honest labelling.
