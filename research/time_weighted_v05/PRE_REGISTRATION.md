# Pre-registration — scheduled-time disruption ranking (v0.5, Phase 2)

Committed **before** any Phase 2 experiment is run. At this commit no travel-time increase, ranking, correlation or
baseline value has been computed. What exists: the Phase 0 probes (GTFS access, stop matching) and the Phase 1 artefacts
(planned ride times, band headways), none of which involve disruptions. Changes after this commit are listed in
`REPORT.md` under "Deviations" with the reason. Publication status stays **NEEDS_VALIDATION**.

## 1. Question

Which stations, when (a) their interchange function is disabled or (b) the station is closed, produce the largest
increase in **planned (scheduled) shortest travel time** over all ordered station pairs, by time band? Is that ranking
explained by simple structural metrics (degree, line count, betweenness)?

## 2. Model (fixed before running)

Graph: v0.2 model B1 on the frozen v0.1.0 snapshot (242 stations, 291 station-line states, 280 ride edges, 61
same-station transfer edges; built with the public snapshot only, no CRTM audit). Cross-name walk links (Noviciado–
Plaza de España, Embajadores–Acacias) are **not modelled** (limitation, not tested).

Time of an ordered pair (o, d), in seconds:

- ride edge: planned seconds from `data/gtfs_derived/ride_times.json` (GTFS or, for Line 3, imputed length ÷ speed ×
  `imputed_speed_multiplier`);
- boarding line `l` at station `x` (at the origin, or after a transfer): `wait_factor × headway(x, l, band)`, with headway
  from `headways.json` (band average, mean of the two directions);
- transfer between states of one station: `transfer_seconds` + the boarding wait of the new line;
- no wait at the destination; no walking, dwell, fare gate or crowding. Because the origin wait is paid and the
  destination wait is not, times are asymmetric, so pairs are **ordered** (242 × 241 = 58,322).
- **Line 3 headway** is not in the feed. Assumption: median headway of all other (node, line) rows in the same band,
  × `l3_headway_multiplier` (central 1.0). It is unverifiable and swept.

Hop mode (replication only, no time): ride edge = 1, transfer = 0, wait = 0.

**Disruptions.** (b) *closure*: delete every state of station `s` and the pairs involving `s` (241 × 2 ordered pairs
excluded; 242 scenarios). (a) *interchange disabled*: delete only the transfer edges among the states of `s`; all pairs
stay eligible (38 scenarios). Disconnected pairs have no time; they are counted and excluded from the mean.

**Effect size.** `ΔT̄(s)` = mean over ordered pairs connected both intact and disrupted of `t_disrupted − t_intact`
(seconds). Also reported: `ΔT̄ / T̄_intact` over the same pairs and `n_disconnected(s)`.

## 3. Parameters (all assumptions; none has a data source)

| Parameter | Central (primary) | Sweep | Basis |
| --- | --- | --- | --- |
| time band | `weekday_peak` | 5 bands | Band clock times are assumptions (Phase 1 manifest) |
| `wait_factor` | 0.5 | 0, 0.25, 0.5 | 0.5 = random passenger arrival; 0 = timetable-aware |
| `transfer_seconds` | 180 | 0, 60, 120, 180, 300, 600 | Illustrative range, no measurement; the central value is the middle of the range, not an estimate |
| `imputed_speed_multiplier` (L3 legs) | 1.0 | 0.9, 1.0, 1.1 | Line-total agreement of the method on 12 lines: 0.986–1.020 |
| `l3_headway_multiplier` | 1.0 | 0.75, 1.0, 1.25 | None; neutral |
| L3 treatment | imputed | also: L3 removed (analysis on the 230 stations that remain served) | L3 absent from the feed |
| closure handling | stations fully closed | also: **through-running** (station closed to boarding, alighting and transfer; trains pass at summed leg time; only for states with exactly two ride neighbours, others treated as closed) | Distinguishes closure of a station from closure of a line section |

Runs: full factorial of transfer × wait × speed-multiplier × L3-headway-multiplier in `weekday_peak` (6·3·3·3 = 162);
the other four bands at the central values and at transfer ∈ {0, 600} (12); L3-removed at central, transfer ∈ {0, 600} (3);
through-running at central (1). Total 178 parameter cells, each with 242 closures and 38 interchange disruptions.

## 4. Baselines (station-level predictors, computed without disruption simulation unless stated)

Simple structural tier: **degree** (distinct neighbouring stations); **line count**; **hop-betweenness** (NetworkX
`betweenness_centrality` on the 242-node aggregated graph); **time-betweenness** (same graph, edge weight = minimum planned
ride seconds over the lines on that connection; no transfers or waiting).
Simulation-derived tier (reported, **excluded** from the decision rule because it is the disruption mechanism seen from
the intact network): **passage share** = fraction of ordered pairs whose intact optimal B1 path passes through the station
as an intermediate stop; for (a), **transfer-use share** = fraction whose intact optimal path transfers at the station.
Intact optimal paths use SciPy predecessors; ties, if any, are broken by the library and the number of tied pairs is reported.

## 5. Hypotheses and decision rules

**Primary endpoint (H1).** Closure ranking by `ΔT̄` in `weekday_peak` at central parameters against the simple tier.
Let `ρ_max` be the largest Spearman ρ over the four simple baselines and `ov10` the top-10 overlap with that baseline.

- **ABSTAIN / NO ROBUST DIFFERENCE over simple structural metrics:** `ρ_max ≥ 0.90` **and** `ov10 ≥ 7`.
- **ADDED VALUE:** `ρ_max < 0.70`.
- **INCONCLUSIVE:** otherwise.

The verdict is called **robust** only if the same classification holds in at least 90 % of the 162 `weekday_peak` cells
and in the other bands' cells; otherwise **SENSITIVE TO ASSUMPTIONS** and the share of cells per class is reported.
Thresholds (0.90, 0.70, 7) are fixed here; the report also shows 0.80 and 0.95 as a sensitivity of the rule, not as the rule.
Prior expectation, stated before running: H1 falls in ABSTAIN.

**Secondary endpoints** (Holm correction over the family listed; thresholds are deterministic rules, p-values are descriptive):

- **H2 disruption type.** Among the 38 interchanges, Spearman ρ between `ΔT̄` under (a) and under (b) is < 0.90 (rankings differ).
- **H3 band stability.** The minimum Spearman ρ over the 10 band pairs (closure, central parameters) is ≥ 0.90.
- **H4 time vs hops.** Spearman ρ between the closure ranking by `ΔT̄` and by hop-mode `ΔT̄` (increase in ride count, same
  scenarios) is < 0.90, meaning planned times change the ranking relative to the v0.4 hop count.
- **Exploratory, no decision rule:** (i) ranking among the 158 non-fragmenting closures only; (ii) through-running vs full
  closure; (iii) set-level: closing the top-k stations by `ΔT̄`, by each simple baseline, and k random stations
  (200 seeded draws), k ∈ {3, 5}, reporting `ΔT̄` and `n_disconnected` for each set.

**Null model.** Random station sets of equal size (seeded, `seed = 20261121`) for (iii); permutation null for Spearman
(10,000 seeded permutations); bootstrap over stations (2,000 resamples, same seed) for ρ intervals. The 242 stations are
the population, not a sample: the intervals describe sensitivity to which stations are included, not sampling error.

## 6. Validation gates and stopping rules

The experiment must stop and report **without results** if any gate fails:

- **G1 replication of v0.4 in hop mode:** 84 fragmenting closures; smallest fragmentation 240, median 1,180 and maximum 4,296
  disconnected **unordered** pairs; exactly 1 interchange disruption disconnecting pairs, with 1,410 (ordered count ÷ 2).
- **G2 independent solver:** SciPy times equal NetworkX Dijkstra times (tolerance 1e-6 s) for all ordered pairs on the intact
  graph and on three disrupted graphs.
- **G3 monotonicity:** no connected pair gets faster under closure or interchange disabling; through-running is never slower
  than full closure on pairs connected in both.
- **G4 data integrity:** `validate.py` passes; v0.1.0 hashes unchanged; Phase 1 manifest hashes match the local outputs.
- **G5 unit tests** on synthetic networks with known answers pass.

Stop with **FREEZE** (decision memo) under the PLAN §6 conditions, evaluated on these pre-registered cells: the primary
verdict changes between "L3 imputed" and "L3 removed", or no verdict is stable across the grid.

## 7. External validation (planned, no forcing)

Search official Metro de Madrid / CRTM notices for dated, planned closures or works. Use only cases with a citable URL and
date. For each, state what is observable (replacement service, duration, any published travel-time change) and whether the
structural model can be compared at all. If none supports a comparison, the status stays NEEDS_VALIDATION and the reason is
stated.

## 8. Known limits fixed in advance

Planned times are segment length ÷ line speed (not measured); the feed is expired (calendar to 2026-05-27) and Line 3 is
absent; transfer and Line 3 headway have no data; no demand, crowding, fare gates, real-time effects, cross-name walks or
replacement bus services. Results are properties of this model of the scheduled network, not observed resilience.

## 9. Outputs and licensing

`results_summary.json`: aggregates only (correlations, class counts, distributions), committed. Per-station tables mix
OSM-derived names and ids (ODbL) with CRTM-derived timings: written to `research/time_weighted_v05/local/` and
git-ignored, as in v0.2. The report names no individual station's score. © CRTM · Powered by CRTM, no endorsement.
Topology © OpenStreetMap contributors.
