#!/usr/bin/env python3
"""Phase 3: precompute the data behind index.html (disruption explorer). No new hypotheses; descriptive only.

Two outputs, with different licensing (see NOTICE.md):
  data/explorer/disruption_topology.json   PUBLIC, committed, ODbL. Topology only (ride count between stations); uses the
                                           frozen v0.1.0 snapshot and nothing from CRTM. Replicates v0.4 (gate G1).
  research/time_weighted_v05/local/explorer_time.json
                                           LOCAL, git-ignored. Planned times (CRTM-derived) joined with OSM ids. Needs the
                                           Phase 1 outputs from `gtfs_ingest.py fetch` + `build`.

Run:  python build_explorer.py            public layer
      python build_explorer.py --check    fail if the committed public file differs from a fresh build
      python build_explorer.py --time     local time layer (a few minutes; --workers N)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import networkx as nx
import numpy as np

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from research.time_weighted_v05 import experiment as E  # noqa: E402
from research.transfer_aware_v02 import experiment as v02  # noqa: E402

PUBLIC_OUT = ROOT / "data" / "explorer" / "disruption_topology.json"
LOCAL_OUT = ROOT / "research" / "time_weighted_v05" / "local" / "explorer_time.json"


def hop_net():
    """B1 state graph in hop mode (ride = 1, transfer = 0, wait = 0) from the public snapshot only."""
    stations, connections = v02.load_snapshot()
    transfers = v02.fusion_transfers(stations, None)
    rides = [{"line": line, "a": c["source"], "b": c["target"], "seconds": 1.0, "source": "topology"}
             for c in connections for line in c["lines"]]
    net = E.Net(stations, transfers, rides, lambda s, l: 0.0, {"wait": 0.0, "transfer": 0.0, "speed": 1.0})
    return net, stations, connections, transfers


def scenario(T0, Ts, exclude=None):
    """Summary of one disruption: effect (pre-registered definition), stations cut off from the largest piece,
    and for every destination the mean increase over origins that stay connected (nan when none).

    `exclude`: for a disabled interchange, its own index. That station still reaches both pieces, so it is not used as the
    reference origin; the reference is the best-connected other station, and `cut` lists what that station cannot reach."""
    e = E.effect(T0, Ts)
    alive = ~np.all(np.isnan(Ts), axis=1)
    reach = np.where(alive, np.isfinite(Ts).sum(axis=1), -1)
    if exclude is not None:
        reach[exclude] = -1
    o = int(np.argmax(reach))
    member = np.isfinite(Ts[o])
    member[o] = True
    cut = np.flatnonzero(alive & ~member)
    ok = np.isfinite(Ts) & np.isfinite(T0)
    cnt = ok.sum(axis=0)
    with np.errstate(invalid="ignore", divide="ignore"):
        dest = np.where(cnt > 0, np.where(ok, Ts - T0, 0.0).sum(axis=0) / np.maximum(cnt, 1), np.nan)
    return {"effect": e, "cut": cut.tolist(), "main_size": int(reach[o]) + 1, "dest": dest}


def clean(x, nd=2):
    """JSON-safe: nan/inf -> None, floats rounded."""
    if x is None:
        return None
    x = float(x)
    return round(x, nd) if np.isfinite(x) else None


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def public_payload():
    net, stations, connections, transfers = hop_net()
    T0 = net.times(mode="hop")
    close = [scenario(T0, net.times(removed=[s], mode="hop")) for s in range(net.n)]
    inter_ids = E.interchange_ids(net, transfers)
    inter = [scenario(T0, net.times(disabled=[s], mode="hop"), exclude=s) for s in inter_ids]

    g = nx.Graph()
    g.add_nodes_from(net.stations)
    g.add_edges_from((c["source"], c["target"]) for c in connections)
    bet = nx.betweenness_centrality(g)
    base = {"degree": [g.degree(s) for s in net.stations],
            "line_count": [len(net.lines_of[s]) for s in net.stations],
            "betweenness_hop": [round(bet[s], 6) for s in net.stations]}

    def rec(sc):
        e = sc["effect"]
        assert e["n_disc"] % 2 == 0  # hop distances are symmetric: ordered count is twice the unordered one
        return {"disc": e["n_disc"] // 2, "dT": clean(e["dT"], 4), "n_cut": len(sc["cut"]), "cut": sc["cut"],
                "main": sc["main_size"], "dest": [clean(v) for v in sc["dest"]]}

    g1 = E.hop_replication({"disc_close": [c["effect"]["n_disc"] for c in close],
                            "disc_inter": [c["effect"]["n_disc"] for c in inter]})
    dT = np.array([c["effect"]["dT"] for c in close])
    frag = np.array([c["effect"]["n_disc"] for c in close]) > 0
    bh = np.array(base["betweenness_hop"])
    meta = {
        "status": "NEEDS_VALIDATION; structural model (topology only); not real-time, not demand, not observed",
        "model": "v0.2 model B1 on the frozen v0.1.0 snapshot, hop mode: a ride between consecutive stations counts 1, "
                 "a same-station transfer counts 0, no waiting, no walking. No CRTM data and no times.",
        "inputs": {"v010_manifest_sha256": sha(ROOT / "data" / "manifest.json")},
        "definitions": {
            "disc": "unordered station pairs that are connected on the intact network and not after the disruption "
                    "(v0.4 convention); the removed station is excluded from the pairs",
            "dT": "mean increase in rides over ordered pairs connected both before and after (pre-registered effect size); "
                  "null when no pair stays connected. It ignores disconnected pairs.",
            "cut": "indices (into `ids`) of stations outside the largest connected piece after the disruption",
            "dest": "per destination, mean increase in rides over origins that stay connected; null if none or removed",
            "T0_hop": "intact ride counts between all station pairs (diagonal 0)"},
        "gate_G1_replication_of_v04": g1,
        "post_hoc_not_preregistered": {
            "closures_fragmenting": int(frag.sum()),
            "mean_dT_fragmenting": clean(np.nanmean(dT[frag])),
            "mean_dT_non_fragmenting": clean(np.nanmean(dT[~frag])),
            "rho_dT_vs_betweenness_hop_all": clean(E.rho(dT, bh), 3),
            "rho_dT_vs_betweenness_hop_non_fragmenting": clean(E.rho(dT[~frag], bh[~frag]), 3)},
        "attribution": "Topology (c) OpenStreetMap contributors, ODbL 1.0. Powered by CRTM is shown on the page for the "
                       "optional local time layer only; this file contains no CRTM data."}
    return {"meta": meta, "ids": net.stations, "close": [rec(c) for c in close], "inter_ids": inter_ids,
            "inter": [rec(c) for c in inter], "base": base,
            "T0_hop": [[0 if i == j else int(T0[i, j]) for j in range(net.n)] for i in range(net.n)]}


def dumps(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n"


# ----------------------------------------------------------------------------- local time layer
def _nan_list(a, nd=1):
    return [clean(v, nd) for v in np.asarray(a, float).tolist()]


def time_payload(workers):
    for f in ("ride_times.json", "headways.json"):
        if not (E.GD / f).exists():
            raise SystemExit(f"missing data/gtfs_derived/{f}: run `python gtfs_ingest.py fetch` then `build` first")
    cells = E.cells_grid()
    peak = [c for c in cells if c["band"] == "weekday_peak" and c["l3"] == "imputed" and c["mode"] == "time"
            and c["closure"] == "full"]
    others = [c for c in cells if c["band"] != "weekday_peak" and c["l3"] == "imputed" and c["transfer"] == 180.0
              and c["wait"] == 0.5 and c["speed"] == 1.0 and c["l3h"] == 1.0 and c["mode"] == "time"]
    through = [c for c in cells if c["closure"] == "through"]
    run = peak + others + through
    print(f"{len(run)} cells, workers={workers}", flush=True)
    with ProcessPoolExecutor(max_workers=workers) as ex:
        res = list(ex.map(E.run_cell, run))
    pk = [r for r in res if r["cell"] in peak]
    central = next(r for r in pk if E.is_central(r["cell"]))
    inter_ids = central["inter_ids"]
    arr = lambda rs, k: np.array([r[k] for r in rs], float)  # noqa: E731
    with np.errstate(all="ignore"):
        close_rng = {"min": _nan_list(np.nanmin(arr(pk, "dT_close"), axis=0)),
                     "max": _nan_list(np.nanmax(arr(pk, "dT_close"), axis=0))}
        inter_rng = {"min": _nan_list(np.nanmin(arr(pk, "dT_inter"), axis=0)),
                     "max": _nan_list(np.nanmax(arr(pk, "dT_inter"), axis=0))}
    close = {}
    for b in E.BANDS:
        r = central if b == "weekday_peak" else next(x for x in res if x["cell"]["band"] == b)
        close[b] = {"dT": _nan_list(r["dT_close"]), "disc": [d // 2 for d in r["disc_close"]],
                    "inter_dT": _nan_list(r["dT_inter"]), "inter_disc": [d // 2 for d in r["disc_inter"]]}
    thr = next(r for r in res if r["cell"]["closure"] == "through")

    net, _ = E.make_net(E.CENTRAL)
    T0 = net.times()
    dest_close = [_nan_list(scenario(T0, net.times(removed=[s]))["dest"]) for s in range(net.n)]
    dest_inter = [_nan_list(scenario(T0, net.times(disabled=[s]), exclude=s)["dest"]) for s in inter_ids]
    t0 = {}
    for b in E.BANDS:
        nb, _ = E.make_net({**E.CENTRAL, "band": b})
        Tb = nb.times()
        t0[b] = [[0 if i == j else int(round(Tb[i, j])) for j in range(nb.n)] for i in range(nb.n)]
    return {
        "meta": {
            "status": "NEEDS_VALIDATION; planned/scheduled model; not real-time, not demand, not observed. LOCAL FILE: "
                      "joins OSM ids with CRTM-derived planned times; do not distribute (NOTICE.md). (c) CRTM, Powered by "
                      "CRTM, no endorsement; topology (c) OpenStreetMap contributors.",
            "central": {k: E.CENTRAL[k] for k in ("band", "wait", "transfer", "speed", "l3h", "l3")},
            "range": f"min/max of the closure effect over the {len(pk)} pre-registered weekday_peak cells "
                     "(transfer 0-600 s, wait factor 0-0.5, L3 speed x0.9-1.1, L3 headway x0.75-1.25). It covers the "
                     "assumptions swept, not measurement error.",
            "dest": "weekday_peak, central parameters only (the band changes the ranking by rho >= 0.999)",
            "t0": "intact planned time in seconds incl. origin wait, rides, transfers; no walking, no dwell"},
        "ids": net.stations, "bands": E.BANDS, "inter_ids": inter_ids,
        "close": close, "close_range_peak": close_rng, "inter_range_peak": inter_rng,
        "through_peak": {"dT": _nan_list(thr["dT_close"]), "disc": [d // 2 for d in thr["disc_close"]]},
        "dest_close": dest_close, "dest_inter": dest_inter, "T0": t0}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="compare a fresh public build with the committed file")
    ap.add_argument("--time", action="store_true", help="build the local (git-ignored) time layer")
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args(argv)
    if a.time:
        LOCAL_OUT.parent.mkdir(parents=True, exist_ok=True)
        LOCAL_OUT.write_text(dumps(time_payload(a.workers)), encoding="utf-8")
        print(f"wrote {LOCAL_OUT.relative_to(ROOT)} ({LOCAL_OUT.stat().st_size // 1024} KiB), not for distribution")
        return 0
    text = dumps(public_payload())
    if a.check:
        same = PUBLIC_OUT.exists() and PUBLIC_OUT.read_text(encoding="utf-8") == text
        print("public file matches a fresh build" if same else "MISMATCH: regenerate with python build_explorer.py")
        return 0 if same else 1
    PUBLIC_OUT.parent.mkdir(parents=True, exist_ok=True)
    PUBLIC_OUT.write_text(text, encoding="utf-8")
    print(f"wrote {PUBLIC_OUT.relative_to(ROOT)} ({PUBLIC_OUT.stat().st_size // 1024} KiB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
