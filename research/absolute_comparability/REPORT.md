# Absolute R/T costs across B1, E and E + Sol–Gran Vía

The [evidence-informed study](../evidence_informed_robustness/REPORT.md) measured each disruption against the model's own intact baseline. E's intact baseline is already better than B1's for 1,770 R pairs and 1,049 T pairs, so its lower deterioration counts could reflect a better starting point rather than better absorption. This check compares the absolute post-disruption costs of the three models for the same 29,161 station pairs and 38 matched disruptions.

## Method

[experiment.py](experiment.py) reuses the independent cost evaluator of [corridor_closure.py](../evidence_informed_robustness/corridor_closure.py). It uses the same graphs, scenarios and both walk variants. Before using any cost, it reproduces every published deterioration count in [corridor_closure_summary.json](../evidence_informed_robustness/corridor_closure_summary.json). Costs stay in the original lexicographic units: R = (ride edges, commercial-line state changes) and T = (commercial-line state changes, ride edges). No minutes, penalties or demand are introduced. For each pair *p* and disruption *s* it separates:

| Quantity | Definition |
| --- | --- |
| Intact difference | c_right(0, p) against c_left(0, p) |
| Post-disruption difference | c_right(s, p) against c_left(s, p) |
| Relative deterioration | c_m(s, p) > c_m(0, p), for each model m |

The reachable sets are identical in all models, so all comparisons use the same **1,106,708** surviving scenario-pair observations. These are station pairs repeated across scenarios, not travellers. [Aggregate results](results_summary.json)

## Results (walks open, B1 vs E)

| | R | T |
| --- | ---: | ---: |
| Pairs where E is cheaper when intact, of 29,161 | 1,770 | 1,049 |
| Observations where E is cheaper after disruption | 69,869 | 41,461 |
| … of which E was already cheaper when intact | 66,412 (95.1%) | 39,490 (95.2%) |
| Observations where E is costlier after disruption | **0** | **0** |
| Deteriorations in B1 only | 3,611 | 1,407 |
| … with E already cheaper when intact | 2,887 (79.9%) | 1,267 (90.0%) |
| … with equal intact cost, absorbed by a walk in E | 724 (20.1%) | 140 (10.0%) |
| Deteriorations in E only (E cheaper when intact in every case) | 1,213 | 312 |
| … that end at B1's cost (advantage lost) | 412 | 270 |
| Mean primary cost, B1 intact → after | 14.037 → 14.144 rides | 1.131 → 1.142 changes |
| Mean primary cost, E intact → after | 13.962 → 14.062 rides | 1.123 → 1.133 changes |

**The apparent advantage of E is mostly baseline.** Of B1's deteriorations that do not occur in E, 80% (R) and 90% (T) involve pairs that E already served more cheaply before any disruption. Only 724 R and 140 T observations (≤ 0.07% of 1,106,708) start at equal cost and are absorbed by a documented walk. E's mean post-disruption advantage (0.082 rides) is almost entirely present when intact (0.075 rides).

**Absolute order never reverses.** In no objective, variant or model pair is the walk-augmented model costlier than the model it extends, either intact or after a disruption. This follows from edge inclusion: E contains every lifted B1 edge, and the Sol sensitivity contains every E walk. It is therefore not an empirical finding.

**Closed-corridor reading.** With walks closed at the disrupted station, the Sol model has 7,601 R deteriorations that B1 does not have. In 6,229 of them the Sol model falls back to B1's cost, and in the other 1,372 it remains cheaper. It is never costlier than B1. The earlier statement that "the Sol model shows more, not fewer, deteriorations than B1" is true only relative to each model's own baseline. In absolute terms the closure removes an advantage and does not create a disadvantage.

## Interpretation and limits

- The relative counts in the evidence-informed report should not be read as differences in robustness between models.
- Measured against a common absolute cost, the documented walks shift both the intact and the disrupted cost distributions down by almost the same amount.
- The only effect that depends on the disruption is a small set of absorbed or lost advantages.
- All quantities are structural: ride-edge counts and line-state changes on the v0.1.0 graph. They are not minutes, generalized cost, passenger behaviour or demand.
- The publication status remains **NEEDS_VALIDATION**. Existing results are unchanged.

## Reproduction

Run from the repository root with NetworkX 3.7 (about 75 s):

```text
python -m research.absolute_comparability.experiment
```

The run first verifies the snapshot hashes through the existing loader. It then fails if any per-model deterioration count differs from the published closed-corridor summary or if the reachable sets differ between models. © OpenStreetMap contributors (ODbL) · [Repository NOTICE](../../NOTICE.md)
