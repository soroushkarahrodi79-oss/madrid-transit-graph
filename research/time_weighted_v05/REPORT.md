# Scheduled-time disruption ranking, Madrid Metro (v0.5, Phase 2)

**Status: NEEDS_VALIDATION.** Planned/scheduled model on a fixed graph. Not real-time, not demand, not observed.
Pre-registered in [PRE_REGISTRATION.md](PRE_REGISTRATION.md) (commit `e1882b6`, pushed before any run). Aggregates:
[results_summary.json](results_summary.json), [posthoc_summary.json](posthoc_summary.json). Code: [experiment.py](experiment.py),
[posthoc.py](posthoc.py), tests [test_experiment.py](test_experiment.py) (19) and [test_gtfs_ingest.py](test_gtfs_ingest.py) (20).

## 1. Headline, stated with its limits

1. **Pre-registered verdict: ADDED_VALUE.** Ranking stations by the mean planned-time increase after closure (`ΔT̄`, weekday
   peak, central parameters) is **not** reproduced by simple structural metrics: the largest Spearman ρ is **0.518**
   (time-weighted betweenness; bootstrap 95 % interval for hop-betweenness 0.39–0.61), top-10 overlap 3/10. The same class
   holds in **all 174** time-model cells of the grid (ρ_max range 0.49–0.52), with the Line 3 treatment (imputed vs removed)
   and at the 0.80 and 0.95 rule thresholds. No freeze trigger fired.
2. **That verdict is largely produced by the metric, not by the network (post-hoc, not pre-registered).** `ΔT̄` averages only
   over pairs that stay connected. 84 of 242 closures fragment the network, and those stations average 4.7 s against
   36.9 s for the 158 that do not, so the most structurally critical stations look mild. Among the **158 non-fragmenting**
   closures, ρ with time-betweenness is **0.91** (hop-betweenness 0.89). The verdict changes with the penalty charged per
   disconnected pair (post-hoc, arbitrary values): ρ_max 0.93, 0.83, 0.72, 0.64 for 600, 1,800, 3,600, 7,200 s, i.e.
   INCONCLUSIVE, INCONCLUSIVE, INCONCLUSIVE, ADDED_VALUE by the registered rule. **So the supportable statement is
   "rank agreement with betweenness is high where no pair is disconnected and low where closures fragment the
   network", not "simulation adds value over betweenness".**
3. **Planned times add little to the v0.4 hop-count ranking.** H4: ρ between the time-based and hop-based closure rankings
   is **0.956** (hypothesis "times change the ranking" **not supported**); 0.89 among non-fragmenting closures.
4. **Time bands do not change the ranking.** H3: minimum ρ between bands **0.999**. Expected: in-vehicle times are one
   planned value per leg in every band (Phase 0); only headways differ.
5. **Interchange-disabled and station-closed rankings differ** (H2, 38 interchanges): ρ = **0.74** (supported).
6. **Magnitudes are small relative to a trip.** Mean planned pair time 2,416 s (about 40 min). Closure `ΔT̄` (connected
   pairs): median 8 s, 95th percentile 138 s, maximum 251 s. Interchange disabling: median 5 s, maximum 125 s. 84 closures
   and 1 interchange disruption disconnect pairs.
7. **External validation: none usable.** Status stays NEEDS_VALIDATION (Section 6).

## 2. What was run

B1 on the frozen v0.1.0 snapshot (242 stations, 291 states, 61 same-station transfers; public snapshot only), planned ride
seconds and band headways from Phase 1, Line 3 imputed (length ÷ speed) with an assumed Line 3 headway. Times are
ordered-pair seconds: origin wait `wait_factor × headway`, ride seconds, transfer `T + wait of the new line`. 242 closures
and 38 interchange disablings per cell. **179 cells** = the 178 pre-registered cells plus one hop-mode replication cell.
Seed 20261121; 10,000 permutations; 2,000 bootstrap resamples. Runtime 203 s on 7 workers (Windows 11, Python 3.14.5,
NumPy 2.5.5, SciPy 1.18.1, NetworkX 3.7).

| Gate | Result |
| --- | --- |
| G1 hop-mode replication of v0.4 | **exact**: 84 fragmenting closures, min 240, median 1,180, max 4,296 unordered pairs; 1 interchange scenario disconnecting 1,410 |
| G2 SciPy vs NetworkX (intact + 3 disrupted graphs, all ordered pairs) | max difference 0 s |
| G3 monotonicity (no pair faster after a removal) | min delta −9e-13 s |
| G3 through-running never slower than full closure (pair level) | 0 violations |
| G4 `validate.py` 46/46; v0.1.0 and Phase 1 hashes | pass |
| G5 unit tests | pass |

## 3. Primary endpoint and sensitivity

| Quantity (closure, weekday peak, central parameters) | Value |
| --- | --- |
| ρ with degree / line count / hop-betweenness / time-betweenness | 0.47 / 0.40 / 0.51 / 0.52 |
| Top-10 overlap with the best baseline | 3 |
| Class by the registered rule | ADDED_VALUE |
| Cells in the same class: 162 weekday-peak, 12 other-band | 162/162, 12/12 |
| Line 3 removed (230 stations), ρ_max | 0.43, ADDED_VALUE |
| ρ_max range over the 162 peak cells / 12 other-band cells | 0.491–0.519 / 0.492–0.518 |

Over the grid, `ΔT̄` and the ranking barely move with transfer time (0–600 s), wait factor (0–0.5), L3 speed (×0.9–1.1) or
L3 headway (×0.75–1.25). The assumption that matters is **not** in the grid: how disconnected pairs enter the effect size.
Descriptive permutation p-values are 1e-4 (the minimum for 10,000 permutations) for every correlation; after Holm
correction 7e-4. They only say that the rankings are not independent, which is trivial.

## 4. Exploratory and post-hoc results

- **Simulation tier (reported, excluded from the rule).** ρ between `ΔT̄` and the passage share of intact optimal paths: 0.60
  (0 tied pairs). For interchanges, ρ with transfer-use share 0.85 versus 0.70 with hop-betweenness and 0.28 with degree.
  Disabling an interchange is better predicted by how often passengers transfer there than by centrality.
- **Through-running vs closure.** Letting trains pass the closed station cuts the mean `ΔT̄` from 25.7 s to 2.0 s (ρ 0.33).
  Whether a station or a line section is closed changes the ranking more than any numeric assumption.
- **Set-level comparison (k = 3, 5).** Not interpretable: the sets chosen by `ΔT̄` fragment the network (up to 17,550
  disconnected ordered pairs) and the mean is taken over what remains connected. Reported in `results_summary.json`
  without a conclusion.
- **Post-hoc diagnostics** (`posthoc.py`, written after seeing results): the fragmenting/non-fragmenting split, the
  penalised mean and the hop-mode correlations quoted in Section 1. The penalty values are assumptions, swept, not estimated.

## 5. Deviations from the pre-registration

1. G3 "through-running never slower" was first implemented on station means (a different pair set per scenario) and failed
   for one station. It was corrected to the registered pair-level definition before the full run. Not a change of rule.
2. A 9-cell smoke run was executed before the full run to test the pipeline. It had no pre-registered status; its output was
   discarded. It printed the same class as the full run for the central cell, so the full-run verdict was not a surprise to me.
3. The post-hoc diagnostics of Section 4 are outside the pre-registration and are labelled as such.
4. Exploratory item (iii) (set-level) turned out not interpretable, see Section 4.
5. The pre-registered prior (ABSTAIN) was wrong for the registered metric. It was not revised.

## 6. External validation attempt

Searched official Metro de Madrid and CRTM notices on 21 Nov 2026. What could be read and cited:

- [CRTM notice 04/11/2026](https://crtm.es/comunicacion/actualidad-del-servicio/avisos/04112026-servicio-especial-de-autobuses-durante-las-pruebas-de-seguridad-en-la-linea-6-de-metro):
  Line 6 closed between Arganzuela-Planetario and Ciudad Universitaria (both stations stay open) on 7–9 and 21–22 Nov 2026
  for safety tests; free bus SE6 Legazpi–Ciudad Universitaria, interval 3–5 min. **Observable:** replacement service and
  headway. **Not published:** any travel time, delay or ridership. **Comparable with this model?** No. The model closes
  stations, not line sections, and no observed travel time exists to compare with.
- Titles only (the pages returned a security block page to my fetch, so their content was **not** read and is not used):
  Metro de Madrid notices on Line 10 Nuevos Ministerios–Cuzco (2026-03-26) and Line 3 Sol–Moncloa (`/en/node/8279`).
- Search results also list a CRTM notice of 22/09/2026 (Line 6 Cuatro Caminos–Lucero) and a Metro de Madrid release of
  2026-07-15 on August works. I did not read them.

No case with a citable, dated, **measured** travel-time effect was found. Section closures would need an edge-removal
model that was not built. **NEEDS_VALIDATION stands; no validation is claimed.**

## 7. Limits

- Planned times are segment length ÷ one speed per line (Phase 0), not measured running times; no dwell. The GTFS is expired
  (calendar to 2026-05-27, item modified 2025-05-30) and has no Line 3 (imputed; headway assumed). Transfer time and
  Line 3 headway have no data. The band clock times and direction-mean headway are assumptions.
- B1 only: no cross-name walk links, no fare gates, no crowding, no demand, no replacement bus service, no recovery dynamics.
- Ordered station pairs are weighted equally; they are not travellers.
- The 242 stations are the population: intervals describe sensitivity to the station set, not sampling error. Permutation
  p-values are descriptive.
- The effect size excludes disconnected pairs (Section 1, item 2). Any ranking claim depends on that choice.
- Per-station tables mix OSM-derived names/ids (ODbL) with CRTM-derived timings and stay in git-ignored `local/`; this
  report names no station's score. © CRTM · Powered by CRTM, no endorsement. Topology © OpenStreetMap contributors.
- Prior literature on weighted vulnerability of metro networks is extensive; I cite none here and have verified none for this
  report (`[X]`). A claim of novelty is not made.

## 8. Reproduce

```powershell
.venv\Scripts\python gtfs_ingest.py fetch
.venv\Scripts\python gtfs_ingest.py build
.venv\Scripts\python -m research.time_weighted_v05.experiment --workers 7
.venv\Scripts\python -m research.time_weighted_v05.posthoc
.venv\Scripts\python -m unittest discover -s research/time_weighted_v05
```

The raw feed and per-edge outputs are not distributed (NOTICE.md); the feed currently resolves to the same bytes as on
2026-11-19 (SHA-256 recorded in `data/gtfs_derived/gtfs_manifest.json`).
