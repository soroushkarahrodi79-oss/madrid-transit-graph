"""Absolute R/T costs of B1, E and E+Sol on identical scenario-pairs, before and after each matched disruption.

The evidence-informed study compared each model with its own intact baseline. This check reuses the
independent cost evaluator of corridor_closure.py (same graphs, objectives, units and scenarios) and
separates three quantities for every unordered station pair p and matched disruption s:

* intact difference      c_right(0, p) vs c_left(0, p)
* post-disruption difference c_right(s, p) vs c_left(s, p)
* relative deterioration c_m(s, p) > c_m(0, p), separately for each model m

Costs stay in the original lexicographic units: R = (ride edges, commercial-line state changes),
T = (commercial-line state changes, ride edges). No minutes, penalties or demand are introduced.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path

from research.evidence_informed_robustness import corridor_closure as cc
from research.evidence_informed_robustness import experiment as exp

HERE = Path(__file__).resolve().parent
PUBLISHED = exp.HERE / "corridor_closure_summary.json"
MODELS = ("B1", "E", "E_with_Sol_Gran_Via")
COMPARISONS = (("B1", "E"), ("B1", "E_with_Sol_Gran_Via"), ("E", "E_with_Sol_Gran_Via"))
VARIANTS = {"walks_open": False, "walks_closed_at_disrupted_station": True}
COMPONENTS = {"R": ("ride_edges", "commercial_line_state_changes"),
              "T": ("commercial_line_state_changes", "ride_edges")}


def parts(cost):
    return divmod(cost, cc.BASE)


def sign(a, b):
    """'right_better', 'equal' or 'right_worse' for right cost a against left cost b."""
    return "right_better" if a < b else "equal" if a == b else "right_worse"


def gap_change(left0, right0, left_s, right_s):
    """How the lexicographic advantage of right over left changes from intact to disrupted."""
    before = tuple(x - y for x, y in zip(parts(left0), parts(right0)))
    after = tuple(x - y for x, y in zip(parts(left_s), parts(right_s)))
    zero = (0, 0)
    if after == before:
        return "unchanged"
    if before == zero:
        return "appeared"
    if after == zero:
        return "vanished"
    if (before > zero) != (after > zero):
        return "reversed"
    return "widened" if abs_lex(after) > abs_lex(before) else "narrowed"


def abs_lex(t):
    return t if t >= (0, 0) else tuple(-x for x in t)


def load_models():
    evidence = json.loads((exp.HERE / "evidence.json").read_bytes())
    stations, b1, interchanges = exp.load_control(evidence)
    sections, splits = exp.ride_sections(b1, stations, evidence["mandatory_train_changes"])
    walks = evidence["confirmed_walks"]
    models = {
        "B1": b1,
        "E": exp.build_evidence_model(b1, stations, sections, splits, walks),
        "E_with_Sol_Gran_Via": exp.build_evidence_model(
            b1, stations, sections, splits, walks + evidence["sensitivity_walks"]),
    }
    return models, interchanges


def mean_parts(costs):
    n = len(costs)
    return [round(sum(parts(c)[i] for c in costs) / n, 4) for i in (0, 1)] if n else None


def run():
    models, interchanges = load_models()
    published = json.loads(PUBLISHED.read_bytes())
    out = {
        "unit": "scenario-pair observations (unordered physical station pairs repeated across 38 scenarios); "
                "not travellers",
        "objectives": {o: list(c) for o, c in COMPONENTS.items()},
        "comparison_orientation": "left vs right; 'right_better' means the right model has the lower cost",
        "scenarios": len(interchanges),
        "variants": {},
    }
    for variant, close in VARIANTS.items():
        vout = out["variants"][variant] = {}
        for o in "RT":
            base = {m: cc.station_costs(models[m], o) for m in MODELS}
            after = {m: {s: cc.station_costs(models[m], o, s, close) for s in interchanges} for m in MODELS}
            # Reproduce the published per-model deterioration counts before using these costs.
            for m in MODELS:
                worse = sum(c > base[m][p] for s in interchanges for p, c in after[m][s].items())
                if worse != published[m][variant][f"{o}_worse_cost"]:
                    raise RuntimeError(f"{m} {variant} {o}: {worse} worse observations differ from the published value")
            common = [(s, p) for s in interchanges for p in after["B1"][s]
                      if all(p in after[m][s] for m in MODELS)]
            if any(set(after[m][s]) != set(after["B1"][s]) for m in MODELS for s in interchanges):
                raise RuntimeError("Reachable pair sets differ between models")
            oout = vout[o] = {
                "common_surviving_observations": len(common),
                "mean_cost_components_on_common_survivors": {
                    m: {"intact": dict(zip(COMPONENTS[o], mean_parts([base[m][p] for _, p in common]))),
                        "after_disruption": dict(zip(COMPONENTS[o], mean_parts([after[m][s][p] for s, p in common])))}
                    for m in MODELS
                },
                "comparisons": {},
            }
            for left, right in COMPARISONS:
                intact_pairs = Counter(sign(base[right][p], base[left][p]) for p in base[left])
                post = Counter()
                transition = Counter()
                relative = Counter()
                discordant = Counter()
                gaps = Counter()
                for s, p in common:
                    b_sign = sign(base[right][p], base[left][p])
                    a_sign = sign(after[right][s][p], after[left][s][p])
                    wl = after[left][s][p] > base[left][p]
                    wr = after[right][s][p] > base[right][p]
                    post[a_sign] += 1
                    transition[f"intact_{b_sign}|after_{a_sign}"] += 1
                    rel = "both" if wl and wr else "left_only" if wl else "right_only" if wr else "neither"
                    relative[rel] += 1
                    if rel in ("left_only", "right_only"):
                        discordant[f"{rel}|intact_{b_sign}|after_{a_sign}"] += 1
                    gaps[gap_change(base[left][p], base[right][p], after[left][s][p], after[right][s][p])] += 1
                oout["comparisons"][f"{left}_vs_{right}"] = {
                    "intact_pairs": dict(sorted(intact_pairs.items())),
                    "after_disruption_observations": dict(sorted(post.items())),
                    "intact_to_after_transition": dict(sorted(transition.items())),
                    "relative_deterioration_against_own_baseline": dict(sorted(relative.items())),
                    "discordant_deteriorations_by_absolute_position": dict(sorted(discordant.items())),
                    "advantage_of_right_from_intact_to_after": dict(sorted(gaps.items())),
                }
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=HERE / "results_summary.json")
    args = parser.parse_args()
    args.output.write_text(json.dumps(run(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
