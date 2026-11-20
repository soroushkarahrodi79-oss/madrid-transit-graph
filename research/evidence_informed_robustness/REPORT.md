# Madrid Metro interchange robustness under documented transfers

This paired study asks whether the v0.4 route degradation persists during a same-station interchange disruption when the model represents documented walks and mandatory train changes. It uses the 242 physical stations in the v0.1.0 OSM snapshot with the advertised normal-service configuration supported by Phase 1. Actual service and passage availability at 19:17 CET on 19 November 2026 remain unverified. [Published v0.4 control](../network_robustness_v04/REPORT.md) · [Issue #3 evidence review](https://github.com/soroushkarahrodi79-oss/madrid-transit-graph/issues/3#issuecomment-7023883778)

## Models and matched intervention

| Model | Physical stations | States | Metro rides | Same-station line-pair edges | Mandatory reboarding edges | Cross-name walking links (state edges) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| B1, original v0.4 | 242 | 291 | 280 | 61 | 0 explicit | 0 (0) |
| E, documented normal service | 242 | 294 | 280 | 61 | 3 | 2 (3) |
| E plus Sol–Gran Vía sensitivity | 242 | 294 | 280 | 61 | 3 | 3 (9) |

E keeps the 61 documented same-station commercial transfers. It adds walk-only connections from Noviciado L2 to Plaza de España L3/L10 and from Embajadores L3 to Acacias L5. Callao–Santo Domingo is excluded because passenger documentation contradicts the administrative grouping as a Metro interchange. E splits Estadio Metropolitano (L7), Puerta de Arganda (L9), and Tres Olivos (L10) into their two published service sections. The only direct graph edge between the sections at each boundary requires reboarding. The source is the passenger change-of-train symbol and sectional timetables. The May/June 2026 ArcGIS records serve as corroboration in Phase 1. [October CRTM schematic](https://www.crtm.es/media/hmllv0q3/0a-esqmetro-oct26-copia.pdf) · [Winter 2026–27 Metro service sheet](https://www.crtm.es/media/rmndt4im/00_intervalos-invierno_26-27a.pdf) · [Evidence manifest](evidence.json)

The sensitivity grants bidirectional walk access between all listed Metro line states at Sol and Gran Vía, including L1–L1. It assumes access through the documented corridor for this structural scenario. The fare, gate and route-specific conditions for Metro passengers remain unresolved. The L1 ride remains in the model. For R and T the parallel same-line walk strictly dominates that ride in objective cost, so the solver can omit the parallel ride from its shortest-path search. It assigns no walking time or penalty. A pedestrian-only trip between the two stations is possible under this sensitivity assumption. [Gallery documentation](https://www.comunidad.madrid/noticias/2020/12/16/reabriremos-nueva-estacion-metro-gran-via-proximo-verano) · [Passage closure notice](https://www.comunidad.madrid/noticias/2026/05/25/comunidad-madrid-reforzara-125-servicio-metro-garantizar-movilidad-peregrinos-visita-papa-leon-xiv)

Each matched disruption deletes exactly the original same-station inter-commercial-line transfer clique at the same station ID in all three graphs. It retains every ride, documented walk, and mandatory reboarding connector. A walk can act as a bypass when the same-station clique is removed. This intervention assumes that preserved walks remain available when a local interchange is disrupted. Shared access or jointly closed corridors would define different scenarios. For each disruption the eligible universe is **29,161 unordered station pairs**. Across **38** disruptions it is **1,108,118 scenario-pair observations** per model. A physical pair may recur in different scenarios.

## Common route evaluation

| Metric | Common definition |
| --- | --- |
| Reachability | At least one state of each endpoint is in a common connected component. Endpoints can board or exit on any of their own states. |
| Ride edges | One per modeled movement between consecutive Metro stations. A walk and an internal reboarding contribute zero ride edges. |
| Commercial-line state changes | One when crossing between different commercial line states. On a walk at the start or end of a trip this can include an access-side line label. |
| Ridden commercial-line changes | One when successive rides use different commercial lines, using the actual rides in the itinerary. |
| Physical train changes | Reboarding between successive rides after a line or documented section change, or after an intervening pedestrian connection. First boarding and final alighting count zero. Within each documented section and on other unsplit lines, a continuous sequence of rides is treated as a single train leg for this structural model. |
| Pedestrian connections | One per cross-name walk traversal. Same-station interchange paths have no modeled walking geometry. |
| Physical alternatives | Distinct station sequences of the R/T-optimal paths. Both ride and walk endpoints are kept. Internal changes at one station add no duplicate station. A genuine return to a station is retained. |
| Service alternatives | Distinct ordered ride legs with service identifiers and walk legs with physical endpoints. The intervening train changes can be inferred from these legs. Unused endpoint states and equivalent service-state encodings add no alternatives. These are structural service itineraries. |

R minimizes `(rides, commercial-line state changes)` and T minimizes the reverse, preserving v0.4's exact objectives and B1 transfers. An original B1 transfer edge changes the commercial line and contributes one transition. In E the same edge does the same, a cross-name walk uses its endpoint line labels, and an internal same-line reboarding contributes zero to both objective coordinates. For a path using only original edges, contracting the three reboarding connectors gives the original B1 state sequence and preserves both coordinates. Conversely, each original optimal route can be lifted by selecting the service section determined by its rides and inserting a connector at every required crossing. Endpoints can begin or end on the needed side. Thus service splitting alone preserves reachability and R/T costs with those connectors available. The walks can change which routes are optimal.

The evaluator labels the rides along each B1 and E itinerary with the same service sections, so a B1 route across one of the three boundaries is scored as reboarding despite its implicit continuity. The measured physical count is the minimum among the R- or T-optimal itineraries, computed independently of the minima for ridden-line changes and walks. It is a conditional measure of reboarding, with no claim that it is the network-wide minimum over routes with worse R/T cost. Raw expanded state-path counts and legacy B1 transfer counts cannot serve as common measures of physical train changes or meaningful alternative itineraries. The legacy B1 state-path counts are used only for the published-control check.

Route effects compare a model's disrupted run against its own intact run. A lost optimum appears as a worse cost if a surviving route is more expensive. Equal-cost alternative loss counts surviving pairs with fewer members in the relevant optimal itinerary set. Pairs without a path contribute to reachability only. Matched route-effect contingency tables use observations surviving in both models. The solver checks that removing edges cannot gain reachability, improve an optimum, or introduce equal-cost itinerary signatures.


## Results

**The v0.4 finding persists.** In all three models, the same 37 disruptions preserved every physical OD pair and still worsened an R/T optimum or removed an equal-cost alternative. Exactly one matched disruption disconnected **1,410** pairs in every model. The reachability sets are identical for each scenario, leaving **1,106,708 common surviving observations** for comparisons of route effects. E retains 36 fully reachable cases with worse cost and one with an alternative loss only. The Sol sensitivity has 35 with worse cost and two with an alternative loss only.

| Effect after disruption | B1 | E | E + Sol–Gran Vía |
| --- | ---: | ---: | ---: |
| Fully reachable scenarios with an optimal cost or alternative effect, of 38 | 37 | 37 | 37 |
| Fully reachable scenarios with worse R or T cost, of 38 | 36 | 36 | 35 |
| Disconnected scenario-pair observations, of 1,108,118 | 1,410 | 1,410 | 1,410 |
| R · worse lexicographic cost | 50,208 | 47,810 | 42,819 |
| T · worse lexicographic cost | 29,122 | 28,027 | 26,001 |
| R · increased minimum ride edges | 42,319 | 39,479 | 36,583 |
| T · increased minimum commercial-line state changes | 12,260 | 11,097 | 10,233 |
| R · increased minimum physical reboardings among R optima | 21,053 | 20,453 | 17,919 |
| T · increased minimum physical reboardings among T optima | 12,260 | 10,990 | 11,276 |
| R · increased minimum cross-name walks among R optima | 0 | 3,481 | 8,666 |
| T · increased minimum cross-name walks among T optima | 0 | 1,971 | 5,786 |
| R · equal cost, fewer station sequences | 8,014 | 8,818 | 13,367 |
| R · equal cost, fewer service itineraries | 9,879 | 10,655 | 15,195 |
| T · equal cost, fewer station sequences | 4,160 | 3,689 | 4,421 |
| T · equal cost, fewer service itineraries | 5,242 | 4,575 | 5,307 |

E had **4.78% fewer** R cost deteriorations and **3.76% fewer** T deteriorations than B1. The marginal changes conceal some shifts in which pairs are affected. Under R, **46,597** observations worsened in both models, **3,611** in B1 only, and **1,213** in E only. Under T the counts were **27,715**, **1,407** and **312**. E had fewer pairs with an increase in minimum rides, while the mean increase among affected observations rose from **2.80 to 2.82 rides**. The aggregate results separate commercial-line state transitions, changes between lines actually ridden, reboardings and walks for both objectives. [Aggregate results](results_summary.json)

All three mandatory reboarding connectors are bridges in E and in the Sol variant. When the endpoints require a crossing, a surviving path must still cross it after the matched disruption. This explains why E's physical-reboarding increase counts coincide with the increases in changes of ridden line here, despite the two metrics having different meanings. Sol–Gran Vía can also replace an L1 ride with a walk between L1 rides, which breaks train continuity without changing the ridden commercial line. On the intact graph, this sensitivity increased the minimum number of physical train changes among T-optimal routes for **1,755 of 29,161** pairs versus E, while the minimum number of commercial-line state changes stayed the same for all pairs.

**Sol–Gran Vía sensitivity.** Relative to E, R deteriorations fell another **10.44%** and T deteriorations fell **7.23%**. R observations with equal cost and fewer service itineraries rose **42.61%**, from 10,655 to 15,195. That is an increase in lost ties relative to the sensitivity model's own intact route set. The corridor assumption changes effect sizes while preserving the headline scenario count.

**Closed-corridor sensitivity.** The comparisons above keep every documented walk open when its own station is disrupted. [corridor_closure.py](corridor_closure.py) repeats the matched disruptions with every walk incident to the disrupted station also closed (independent cost evaluator, same scenarios and denominators; [summary](corridor_closure_summary.json)). B1 is unchanged. R · worse cost becomes 48,761 in E (T 28,797) and **52,171 in the Sol–Gran Vía model (T 33,771)**, versus 50,208 and 29,122 in B1. Only the Plaza de España scenario changes in E; the Sol, Gran Vía and Plaza de España scenarios change in the Sol model. The reductions reported above therefore depend on keeping the corridor open during the disruption: with the corridor closed the Sol model shows more, not fewer, deteriorations than B1. The 37/38 scenario count and the 1,410 disconnected observations do not change. The sign and size of the walking-link effect are assumption-dependent and should not be reported as a robustness gain.

**Complete station-removal control.** Removing all states of each of the 242 physical stations leaves **28,920 eligible OD pairs** per run. All models yielded the v0.4 fragmentation summary, with **84** fragmenting removals, a maximum loss of **4,296** pairs in any one removal and a smallest largest component of **222** stations. This control evaluates connectivity.

## Scientific decision

**NEEDS_VALIDATION** for the publication gate (the earlier ARTICLE_CANDIDATE label is withdrawn); the pull request itself documents a reproducible structural result. The persistence of route degradation with complete reachability survives both the documented-transfer representation and the disputed-corridor sensitivity. The paired data quantify how the magnitude and affected pairs change, and canonical route signatures make the result auditable across graph encodings. The claim concerns one published graph, one normal-service representation and a controlled transfer-only intervention. The Sol corridor assumptions affect the magnitude and belong in any account of the result.

Rodríguez-Núñez and García-Palomares measured missed trips and additional riding time from disrupted Madrid Metro network links using passenger flows. The 2019 Madrid structural study evaluated station and line removals. The contribution here is the matched isolation of same-station transfer functionality with ride edges held fixed, and testing how documented pedestrian connections and mandatory reboarding affect optimal station and service itineraries. This is a distinguishable Madrid comparison, with precedence for the general method. Interchange-station vulnerability in metro networks is well established (for example Derrible and Kennedy, Physica A 389, 2010; Frutos Bernal and Martín del Rey, Sustainability 11(12), 2019), so novelty is limited to the paired transfer-only intervention and the route-alternative metrics. Before submission the study still lacks external validation (observed incidents, passenger flows or an operator-confirmed service and passage status), a sensitivity of the route-alternative definition, and a peer-reviewed literature search beyond the works cited. Gao and Blekanov (2026) is listed as a related reference with the bibliographic data supplied by the repository owner; its scope, methods and any overlap with transfer-edge disruption were not checked against the full text, so it supports no claim about precedence until that is done. [Madrid link vulnerability study](https://oa.upm.es/38831/1/INVE_MEM_2014_213430.pdf) · [Madrid structural robustness study](https://www.mdpi.com/2071-1050/11/12/3486) · [Gao and Blekanov (2026), Entropy, DOI 10.3390/e28090976](https://doi.org/10.3390/e28090976)

Fare gates, walk times, accessibility, observed station operations, demand and complete trip-level continuity remain unverified or outside the structural model. Effect sizes depend on the unpenalized walk definition and on keeping interstation paths open during the matched disruption. These restrictions bound the result to the stated structural experiment.

## Reproduction and licences

Run from the repository root with the existing Python and NetworkX 3.7. The default output is [results_summary.json](results_summary.json). Use `--output` for a separate verification file.

```text
python -m research.evidence_informed_robustness.experiment
python -m research.evidence_informed_robustness.corridor_closure
python -m unittest discover -s research/evidence_informed_robustness
python -m unittest discover -s research/network_robustness_v04
python -m unittest discover -s research/transfer_aware_v02
python validate.py
```

The program checks the release manifest SHA-256 and all three snapshot files. It reconstructs B1 with v0.2 and checks all v0.4 interchange and station-removal aggregates. An independent v0.4 replay also matched the committed JSON blob. The 12 focused tests include a brute-force shortest simple path oracle for zero-cost connectors. Route validation checks component reachability, monotonicity under removals, and canonical alternative subsets at equal cost. The public checkout passed all 28 applicable data checks, 17 v0.2 tests with one local-audit test skipped, and all six v0.4 tests.

A replay with the public inputs alone reproduced the evidence-verified result byte-for-byte. Both runs used the frozen graph and explicit rules. `--phase1-dir` verifies hashes against the original local Phase 1 report and 16 captured references when available. The source manifest records the documents, dates, evidence hashes, and assumptions. It permits audit from public originals where available. It cannot guarantee that live sources still serve the same bytes or independently recreate the local mixed audit and unarchived Overpass extraction. The branch contains processed aggregates, authored rules and source metadata. The mixed matrix, raw CRTM records, graphics and detailed routes remain local. Project code and original documentation are MIT. The frozen graph remains ODbL. CRTM originals remain subject to CRTM reuse terms. © OpenStreetMap contributors and © CRTM · Powered by CRTM, processed evidence. [Evidence manifest](evidence.json) · [Repository NOTICE](../../NOTICE.md) · [CRTM reuse licence](https://www.crtm.es/licencia-de-uso/) · [OpenStreetMap and ODbL](https://www.openstreetmap.org/copyright)
