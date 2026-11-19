# Madrid Metro network robustness v0.4

**Decision — GO.** Complete station removal quantifies a wide range of fragmentation severity. Disabling transfers exposes route changes even when every physical station pair remains reachable. These are results for the fixed graph and the specified hypothetical interventions.

## Research question

How do complete station removals and transfer-only disruptions affect physical station-pair reachability and alternative routes? Which effects require explicit line states?

## Snapshot and methods

The input is the [published v0.1.0 snapshot](https://github.com/soroushkarahrodi79-oss/madrid-transit-graph/releases/tag/v0.1.0) at `637f392`, with OSM state timestamp `2026-11-19T18:17:06Z`. The experiment verifies the release manifest and all three data files against SHA-256. It reuses the [v0.2 graph builders and path solver](../transfer_aware_v02/experiment.py).

- **A** has 242 physical stations, 277 undirected adjacency edges and one component. **B1** has 291 station-line states, 280 ride edges and 61 same-station transfer edges, with one component. A ride joins consecutive stops on one line, and the inferred line states at each interchange form a transfer clique.
- **Station failure** removes the station node in A and every state of that station in B1, with their incident edges. The 241 pairs involving the closed station are excluded, leaving 28,920 unordered pairs per scenario. For component sizes $s_i$, the disconnected count is $\binom{241}{2}-\sum_i\binom{s_i}{2}$.
- **Interchange disruption** removes the full same-station transfer clique at one of 38 locations and preserves all station-line states, ride edges and other interchanges. All 29,161 unordered pairs are eligible. A pair is reachable if some state of each endpoint lies in a common state component. A physical station may appear in several projected components, and a pair is counted once.
- **Routes** use the v0.2 lexicographic objectives. R minimizes ride edges, breaking ties by transfers. T minimizes transfers, breaking ties by ride edges. A route may start or end in any state at its endpoint, including at a disrupted interchange. Among surviving pairs, a worse optimum means every formerly optimal route was lost and a costlier route remains. An unchanged optimum with fewer optimal state paths means at least one equally good route survives, with fewer choices. Each distinct station-line path is counted separately.

## Complete station failure

| Measure | Result |
| --- | ---: |
| Scenarios with 1 / 2 / 3 remaining components | 158 / 83 / 1 |
| Fragmenting scenarios | 84 of 242 |
| Disconnected pairs among fragmenting scenarios, min / median / max | 240 / 1,180 / 4,296 |
| Worst disconnected share | 4,296 / 28,920 (14.85%) |
| Smallest largest component | 222 of 241 remaining stations |

A and B1 yielded identical physical component partitions in all 242 cases. The intact transfer cliques at surviving stations let every A walk be lifted to B1, and projecting any B1 path yields an A walk. The same argument gives equality between A's shortest-hop distance and B1's minimum ride count under R, checked for the baseline and the three station cases with detailed path analysis. The match with v0.2's 84 articulation stations is also a validation result. v0.2 computed lost-pair counts internally. This study reports their aggregate severity and compares severed pairs with changes for pairs that survive.

## Interchange disruption

One of 38 disruptions produced two state components and disconnected 1,410 of 29,161 pairs (4.84% in that scenario). Its largest state component covered 236 physical stations. The other 37 scenarios preserved all reachability and each affected at least one optimal cost or tied optimal path. Across all scenarios, 1,106,708 of 1,108,118 scenario-pair observations remained reachable. The same physical pair can contribute once per scenario.

| Effect on surviving scenario-pairs | Scenarios with an increase | Observations | Mean increase among increases | Maximum increase |
| --- | ---: | ---: | ---: | ---: |
| Minimum rides increased under R | 35 of 38 | 42,319 | 2.80 rides | 30 rides |
| Minimum transfers increased under T | 18 of 38 | 12,260 | 1.00 transfer | 1 transfer |

The full lexicographic optimum worsened for 50,208 surviving observations under R and 29,122 under T. Under R, 7,889 of those kept their minimum ride count and required more transfers to achieve it. At unchanged cost, 9,879 observations under R and 5,242 under T lost at least one equally optimal station-line path. An unreachable pair contributes only to reachability statistics.

## Path sensitivity

Selection rules were fixed before inspecting detailed outcomes. The three complete removals use the highest disconnected count, the lowest positive count and the first single-line degree-one station. The transfer-only case uses the largest number of increases in minimum transfers. All ties and the leaf selection use ascending snapshot station ID. The cases illustrate different effects in this graph.

| Selected case | Reachable / eligible | Largest component, stations | More minimum rides under R | More minimum transfers under T |
| --- | ---: | ---: | ---: | ---: |
| Highest fragmentation | 24,624 / 28,920 | 222 | 11 (mean +1.73, max +5) | 234 (all +1) |
| Lowest positive fragmentation | 28,680 / 28,920 | 240 | 0 | 0 |
| Single-line leaf control | 28,920 / 28,920 | 241 | 0 | 0 |
| Interchange with most increases in minimum transfers | 29,161 / 29,161 | 242 | 3,129 (mean +8.38, max +30) | 2,184 (all +1) |

The lowest positive fragmentation case left every surviving pair's R and T optima and tied alternatives intact. The leaf control preserved reachability, costs and alternatives for all eligible pairs. In the selected interchange case, all pairs remained reachable, and 54 R observations and 134 T observations kept their optimal cost with fewer tied paths. The [aggregate JSON](results_summary.json) includes secondary cost changes and their denominators.

## Validation and limitations

Six synthetic tests cover chain and cycle deletions, a tied route, a costlier surviving alternative, removal of every station state, overlapping component projections, and the difference between deleting one transfer edge and disabling a three-line clique. The Madrid run checked every reconstructed route's endpoints and ride/transfer counts. Component reachability agreed with route reachability, and no evaluated deletion improved a lexicographic optimum or gained reachable pairs. The public checkout passed all 28 applicable snapshot checks and 17 v0.2 tests, with the audit-only test skipped. The original checkout's preserved audit also passed all 32 snapshot checks and all 18 v0.2 tests.

GO applies to this structural experiment. The severity distribution is specific to Madrid's snapshot. Explicit line states let the model disable an interchange while preserving through rides, quantify any consequent loss of reachability, and count transfer changes with the ride count held fixed. A's fused station node encodes adjacency only. The scenario results depend on the snapshot's inferred same-station transfers, undirected topology and endpoint rules. These data do not support estimates of ridership, service performance, failure probability or operational resilience. Walking routes, alternative modes, closure procedures and actual train service are outside the model.

## Reproduction and attribution

Run these commands from the repository root using the existing Python environment with NetworkX 3.7.

```powershell
python -m research.network_robustness_v04.experiment
python -m unittest discover -s research/network_robustness_v04
python -m unittest discover -s research/transfer_aware_v02
python validate.py
```

The experiment runs offline and uses the public OpenStreetMap snapshot under ODbL 1.0. Published outputs are aggregates. CRTM data, cross-name links and the inferred Noviciado link are outside the study. [© OpenStreetMap contributors](https://www.openstreetmap.org/copyright) · [Repository licensing and attribution](../../NOTICE.md).
