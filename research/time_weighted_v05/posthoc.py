#!/usr/bin/env python3
"""POST-HOC diagnostics for Phase 2. NOT pre-registered: written after seeing results_summary.json.

Why: the pre-registered effect size (mean time increase over pairs that stay connected) ignores disconnected pairs, so
stations whose closure fragments the network can look mild. These diagnostics probe that, and nothing here changes the
pre-registered verdict. Penalty values are arbitrary assumptions and are swept, not estimated.
Run: python -m research.time_weighted_v05.posthoc
"""
import json
from pathlib import Path

import numpy as np

from research.time_weighted_v05 import experiment as E

HERE = Path(__file__).resolve().parent
PENALTIES_S = [600, 1800, 3600, 7200]  # time assigned to a disconnected pair (assumption, swept)


def station_table(cell):
    r = E.run_cell(cell)
    net, drop = E.make_net(cell)
    stations, connections, transfers, rides, hw = E.load_inputs()
    base = E.baselines(net, rides, cell["speed"], drop)
    n = net.n
    eligible = (n - 1) * (n - 2)  # ordered pairs among the stations that remain
    dT = np.array(r["dT_close"])
    disc = np.array(r["disc_close"], float)
    return dT, disc, eligible - disc, base


def main():
    out = {"status": "POST-HOC, not pre-registered; does not change the pre-registered verdict"}
    dT, disc, conn, base = station_table(E.CENTRAL)
    frag = disc > 0
    out["fragmenting_closures"] = int(frag.sum())
    out["rho_dT_vs_disconnected_pairs_among_fragmenting"] = E.rho(dT[frag], disc[frag])
    out["rho_baseline_vs_disconnected_pairs_all"] = {b: E.rho(base[b], disc) for b in E.SIMPLE}
    out["mean_dT_s_fragmenting_vs_not"] = {"fragmenting": float(np.nanmean(dT[frag])),
                                           "non_fragmenting": float(np.nanmean(dT[~frag]))}
    sub = {b: base[b][~frag] for b in E.SIMPLE}
    out["nonfragmenting"] = {"rho_vs_simple": {b: E.rho(dT[~frag], sub[b]) for b in E.SIMPLE},
                             "class_by_preregistered_rule": E.decision(dT[~frag], sub)["class"]}
    pen = {}
    for P in PENALTIES_S:
        mean_pen = (np.nan_to_num(dT, nan=0.0) * conn + disc * P) / (conn + disc)
        d = E.decision(mean_pen, base)
        pen[str(P)] = {"rho": d["rho"], "rho_max": d["rho_max"], "best": d["best_baseline"],
                       "overlap10": d["overlap10"], "class_by_preregistered_rule": d["class"]}
    out["penalised_mean_increase_disconnected_pairs_charged_P_seconds"] = pen
    hdT, hdisc, _, hbase = station_table({**E.CENTRAL, "mode": "hop", "wait": 0.0, "transfer": 0.0})
    hfrag = hdisc > 0
    out["hop_mode"] = {"rho_dT_vs_hop_betweenness_all": E.rho(hdT, hbase["betweenness_hop"]),
                       "rho_dT_vs_hop_betweenness_nonfragmenting": E.rho(hdT[~hfrag], hbase["betweenness_hop"][~hfrag]),
                       "rho_time_vs_hop_nonfragmenting": E.rho(dT[~frag], hdT[~frag])}
    (HERE / "posthoc_summary.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
