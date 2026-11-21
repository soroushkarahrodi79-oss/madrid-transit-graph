#!/usr/bin/env python3
"""Phase 2: scheduled-time disruption ranking on the v0.1.0 graph (B1) with planned ride times and band headways.

Implements research/time_weighted_v05/PRE_REGISTRATION.md (commit e1882b6). Read that file first: every parameter,
metric, rule and gate below comes from it. Deviations are listed in REPORT.md.

Inputs : frozen v0.1.0 snapshot (public), data/gtfs_derived/{ride_times,headways}.json (local, from gtfs_ingest.py).
Outputs: results_summary.json (aggregates, committed); local/ (per-station tables, git-ignored; OSM ids + CRTM timings).
Run    : python -m research.time_weighted_v05.experiment [--workers N] [--quick]
Needs  : numpy, scipy, networkx (the first two are installed with City2Graph; scipy is a direct dependency here).
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import networkx as nx
import numpy as np
from scipy import sparse
from scipy.sparse.csgraph import dijkstra
from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from research.transfer_aware_v02 import experiment as v02  # noqa: E402

HERE = Path(__file__).resolve().parent
DATA = ROOT / "data"
GD = DATA / "gtfs_derived"
PREREG_COMMIT = "e1882b6"
SEED = 20261121
EPS = 1e-9  # SciPy treats missing entries as non-edges; zero-cost edges are written as EPS
BANDS = ["weekday_peak", "weekday_offpeak", "evening", "saturday", "sunday"]
CENTRAL = {"band": "weekday_peak", "wait": 0.5, "transfer": 180.0, "speed": 1.0, "l3h": 1.0,
           "l3": "imputed", "closure": "full", "mode": "time"}
SIMPLE = ["degree", "line_count", "betweenness_hop", "betweenness_time"]


# ----------------------------------------------------------------------------- network
class Net:
    """B1 state graph with planned times. States are sorted by (station, line) so station minima use reduceat."""

    def __init__(self, stations, transfers, rides, headway, params, drop_lines=()):
        self.p = params
        drop = set(drop_lines)
        self.stations = sorted(s for s in stations if set(stations[s]["lines"]) - drop)
        self.sidx = {s: i for i, s in enumerate(self.stations)}
        self.states = [(s, l) for s in self.stations for l in stations[s]["lines"] if l not in drop]
        self.idx = {st: i for i, st in enumerate(self.states)}
        self.S, self.n = len(self.states), len(self.stations)
        self.st_of = np.array([self.sidx[s] for s, _ in self.states])
        self.starts = np.flatnonzero(np.r_[True, np.diff(self.st_of) != 0])
        self.lines_of = {s: [l for l in stations[s]["lines"] if l not in drop] for s in self.stations}
        f = params["wait"]
        self.board = np.array([f * headway(s, l) for s, l in self.states])
        ru, rv, rw = [], [], []
        for r in rides:
            if r["line"] in drop:
                continue
            u, v = self.idx[(r["a"], r["line"])], self.idx[(r["b"], r["line"])]
            sec = r["seconds"]
            if str(r["source"]).startswith("imputed"):
                sec = r["length_m"] / (r["speed_kmh"] * params["speed"] / 3.6)
            ru.append(u), rv.append(v), rw.append(sec)
        self.ru, self.rv, self.rw = np.array(ru), np.array(rv), np.array(rw, dtype=float)
        tu, tv = [], []
        for t in transfers:
            if t["a"] in self.idx and t["b"] in self.idx:
                tu.append(self.idx[t["a"]]), tv.append(self.idx[t["b"]])
        self.tu, self.tv = np.array(tu, dtype=int), np.array(tv, dtype=int)
        self.nbr = [[] for _ in range(self.S)]
        for u, v, w in zip(self.ru, self.rv, self.rw):
            self.nbr[u].append((v, w))
            self.nbr[v].append((u, w))

    def csr(self, removed=None, disabled=None, mode="time", through=False):
        """Directed CSR over S states + n virtual origin nodes. `removed`/`disabled`: sets of station indices."""
        removed, disabled = set(removed or ()), set(disabled or ())
        alive_st = np.ones(self.S, bool)
        if removed:
            alive_st = ~np.isin(self.st_of, list(removed))
        hop = mode == "hop"
        ru, rv, rw = self.ru, self.rv, (np.ones_like(self.rw) if hop else self.rw)
        keep = alive_st[ru] & alive_st[rv]
        U, V, W = [ru[keep]], [rv[keep]], [rw[keep]]
        if through and removed:
            bu, bv, bw = [], [], []
            for st in range(self.S):
                if self.st_of[st] in removed and len(self.nbr[st]) == 2:
                    (a, wa), (b, wb) = self.nbr[st]
                    if alive_st[a] and alive_st[b]:
                        bu.append(a), bv.append(b), bw.append(wa + wb)
            if bu:
                U.append(np.array(bu)), V.append(np.array(bv)), W.append(np.ones(len(bu)) if hop else np.array(bw))
        U, V, W = np.concatenate(U), np.concatenate(V), np.concatenate(W)
        U, V, W = np.r_[U, V], np.r_[V, U], np.r_[W, W]  # undirected rides
        if len(self.tu):
            tk = alive_st[self.tu] & alive_st[self.tv]
            if disabled:
                tk &= ~np.isin(self.st_of[self.tu], list(disabled))
            tu, tv = self.tu[tk], self.tv[tk]
            tw = np.full(len(tu), EPS) if hop else self.p["transfer"] + self.board[tv]
            tw2 = np.full(len(tu), EPS) if hop else self.p["transfer"] + self.board[tu]
            U, V, W = np.r_[U, tu, tv], np.r_[V, tv, tu], np.r_[W, tw, tw2]
        live = np.flatnonzero(alive_st)
        vo = self.S + self.st_of[live]
        U, V = np.r_[U, vo], np.r_[V, live]
        W = np.r_[W, np.full(len(live), EPS) if hop else self.board[live]]
        W = np.maximum(W, EPS)
        return sparse.csr_matrix((W, (U, V)), shape=(self.S + self.n,) * 2)

    def times(self, removed=None, disabled=None, mode="time", through=False, predecessors=False):
        """Ordered station-pair times (n x n): inf = unreachable, nan on the diagonal and for removed stations."""
        g = self.csr(removed, disabled, mode, through)
        gone = set(removed or ())
        src = np.array([i for i in range(self.n) if i not in gone], dtype=int)
        out = dijkstra(g, directed=True, indices=self.S + src, return_predecessors=predecessors)
        dist, pred = out if predecessors else (out, None)
        per_station = np.minimum.reduceat(dist[:, : self.S], self.starts, axis=1)
        T = np.full((self.n, self.n), np.nan)
        T[src] = per_station
        np.fill_diagonal(T, np.nan)
        if gone:
            T[:, list(gone)] = np.nan
        if mode == "hop":
            T = np.where(np.isfinite(T), np.rint(T), T)
        return (T, dist, pred) if predecessors else T


def effect(T0, Ts):
    """Disruption effect over ordered pairs connected both intact and disrupted (pre-registered definition).

    Pairs involving a removed station are nan in Ts and therefore excluded; every other off-diagonal pair is eligible.
    """
    elig = ~np.isnan(T0) & ~np.isnan(Ts)
    conn = elig & np.isfinite(T0) & np.isfinite(Ts)
    n_disc = int((elig & np.isfinite(T0) & ~np.isfinite(Ts)).sum())
    d = (Ts - T0)[conn]
    return {"dT": float(d.mean()) if d.size else float("nan"),
            "rel": float(d.sum() / T0[conn].sum()) if d.size else float("nan"),
            "n_disc": n_disc, "n_conn": int(conn.sum()), "min_delta": float(d.min()) if d.size else 0.0}


# ----------------------------------------------------------------------------- baselines and statistics
def station_graph(net, rides, speed, drop=()):
    g = nx.Graph()
    g.add_nodes_from(net.stations)
    best = {}
    for r in rides:
        if r["line"] in drop:
            continue
        sec = r["seconds"]
        if str(r["source"]).startswith("imputed"):
            sec = r["length_m"] / (r["speed_kmh"] * speed / 3.6)
        k = frozenset((r["a"], r["b"]))
        best[k] = min(best.get(k, 1e18), sec)
    for k, sec in best.items():
        a, b = sorted(k)
        g.add_edge(a, b, seconds=sec)
    return g


def baselines(net, rides, speed, drop=()):
    g = station_graph(net, rides, speed, drop)
    bh = nx.betweenness_centrality(g)
    bt = nx.betweenness_centrality(g, weight="seconds")
    return {"degree": np.array([g.degree(s) for s in net.stations], float),
            "line_count": np.array([len(net.lines_of[s]) for s in net.stations], float),
            "betweenness_hop": np.array([bh[s] for s in net.stations]),
            "betweenness_time": np.array([bt[s] for s in net.stations])}


def rho(x, y):
    x, y = np.asarray(x, float), np.asarray(y, float)
    ok = np.isfinite(x) & np.isfinite(y)
    return float(spearmanr(x[ok], y[ok]).statistic)


def top_ids(v, k):
    v = np.asarray(v, float)
    return set(np.lexsort((np.arange(len(v)), -np.nan_to_num(v, nan=-np.inf)))[:k].tolist())


def classify(r_max, ov10, hi=0.90, lo=0.70, ov=7):
    if r_max >= hi and ov10 >= ov:
        return "ABSTAIN"
    return "ADDED_VALUE" if r_max < lo else "INCONCLUSIVE"


def decision(dT, base, k=10):
    rs = {b: rho(dT, base[b]) for b in SIMPLE}
    best = max(rs, key=lambda b: (rs[b] if np.isfinite(rs[b]) else -2))
    ov = len(top_ids(dT, k) & top_ids(base[best], k))
    return {"rho": rs, "rho_max": rs[best], "best_baseline": best, "overlap10": ov,
            "class": classify(rs[best], ov), "class_0.80": classify(rs[best], ov, hi=0.80),
            "class_0.95": classify(rs[best], ov, hi=0.95)}


def holm(pvals):
    order = np.argsort(pvals)
    m, adj, run = len(pvals), np.empty(len(pvals)), 0.0
    for rank, i in enumerate(order):
        run = max(run, min(1.0, (m - rank) * pvals[i]))
        adj[i] = run
    return adj


def perm_p(x, y, n=10_000, rng=None):
    rng = rng or np.random.default_rng(SEED)
    x, y = np.asarray(x, float), np.asarray(y, float)
    ok = np.isfinite(x) & np.isfinite(y)
    ra = np.argsort(np.argsort(x[ok])).astype(float)
    rb = np.argsort(np.argsort(y[ok])).astype(float)
    ra, rb = ra - ra.mean(), rb - rb.mean()
    den = np.sqrt((ra**2).sum() * (rb**2).sum())
    obs = abs((ra * rb).sum() / den)
    cnt = sum(abs((ra * rng.permutation(rb)).sum() / den) >= obs - 1e-12 for _ in range(n))
    return (cnt + 1) / (n + 1)


def bootstrap_ci(x, y, n=2000, rng=None):
    rng = rng or np.random.default_rng(SEED)
    x, y = np.asarray(x, float), np.asarray(y, float)
    vals = []
    for _ in range(n):
        i = rng.integers(0, len(x), len(x))
        vals.append(spearmanr(x[i], y[i]).statistic)
    return [float(np.nanpercentile(vals, 2.5)), float(np.nanpercentile(vals, 97.5))]


# ----------------------------------------------------------------------------- data and cells
_CACHE = {}


def load_inputs():
    if "in" not in _CACHE:
        stations, connections = v02.load_snapshot()
        transfers = v02.fusion_transfers(stations, None)  # public snapshot only
        rides = json.loads((GD / "ride_times.json").read_text(encoding="utf-8"))
        hw = json.loads((GD / "headways.json").read_text(encoding="utf-8"))
        _CACHE["in"] = (stations, connections, transfers, rides, hw)
    return _CACHE["in"]


def headway_fn(hw, band, l3h):
    table = {(r["node"], r["line"]): r["headway_s"] for r in hw if r["band"] == band and r["headway_s"]}
    l3 = float(np.median([v for (n, l), v in table.items() if l != "L3"])) * l3h

    def fn(s, l):
        return l3 if l == "L3" else table[(s, l)]
    return fn


def make_net(cell):
    stations, connections, transfers, rides, hw = load_inputs()
    drop = ("L3",) if cell["l3"] == "removed" else ()
    params = {"wait": cell["wait"], "transfer": cell["transfer"], "speed": cell["speed"]}
    return Net(stations, transfers, rides, headway_fn(hw, cell["band"], cell["l3h"]), params, drop), drop


def interchange_ids(net, transfers):
    ids = {t["a"][0] for t in transfers if t["a"] in net.idx and t["b"] in net.idx}
    return sorted(net.sidx[s] for s in ids)


def run_cell(cell):
    t0 = time.time()
    stations, connections, transfers, rides, hw = load_inputs()
    net, drop = make_net(cell)
    mode, through = cell["mode"], cell["closure"] == "through"
    base = baselines(net, rides, cell["speed"], drop)
    T0 = net.times(mode=mode)
    closures = [effect(T0, net.times(removed=[s], mode=mode, through=through)) for s in range(net.n)]
    inter_ids = interchange_ids(net, transfers)
    inter = [effect(T0, net.times(disabled=[s], mode=mode)) for s in inter_ids]
    dT = np.array([c["dT"] for c in closures])
    return {"cell": cell, "n_stations": net.n, "dT_close": dT.tolist(), "disc_close": [c["n_disc"] for c in closures],
            "inter_ids": inter_ids, "dT_inter": [c["dT"] for c in inter], "disc_inter": [c["n_disc"] for c in inter],
            "min_delta": min(min(c["min_delta"] for c in closures), min(c["min_delta"] for c in inter)),
            "T0_mean": float(np.nanmean(np.where(np.isfinite(T0), T0, np.nan))),
            "decision": decision(dT, base), "seconds": round(time.time() - t0, 1)}


def cells_grid(quick=False):
    c = dict(CENTRAL)
    waits, trs, sps, l3s = [0.0, 0.25, 0.5], [0, 60, 120, 180, 300, 600], [0.9, 1.0, 1.1], [0.75, 1.0, 1.25]
    if quick:
        waits, trs, sps, l3s = [0.5], [0, 180], [1.0], [1.0]
    cells = [{**c, "wait": w, "transfer": float(t), "speed": s, "l3h": h}
             for w, t, s, h in itertools.product(waits, trs, sps, l3s)]
    tr_extra = [180, 0, 600] if not quick else [180]
    cells += [{**c, "band": b, "transfer": float(t)} for b in BANDS[1:] for t in tr_extra]
    cells += [{**c, "l3": "removed", "transfer": float(t)} for t in tr_extra]
    cells.append({**c, "closure": "through"})
    cells.append({**c, "mode": "hop", "wait": 0.0, "transfer": 0.0})
    return cells


def is_central(cell):
    return {k: cell[k] for k in CENTRAL} == CENTRAL


# ----------------------------------------------------------------------------- gates, central analyses
def gate_solver(net, tol=1e-6):
    """G2: SciPy against NetworkX Dijkstra on the intact graph and three disrupted graphs."""
    worst = 0.0
    multi = [i for i, s in enumerate(net.stations) if len(net.lines_of[s]) > 1]
    ends = list(net.starts) + [net.S]
    for sc in (dict(), dict(removed=[5]), dict(removed=[60, 61]), dict(disabled=multi[:1])):
        gone = set(sc.get("removed") or ())
        G = nx.from_scipy_sparse_array(net.csr(sc.get("removed"), sc.get("disabled")), create_using=nx.DiGraph)
        T = net.times(sc.get("removed"), sc.get("disabled"))
        for o in range(net.n):
            if o in gone:
                continue
            d = nx.single_source_dijkstra_path_length(G, net.S + o)
            for dst in range(net.n):
                if dst == o or dst in gone:
                    continue
                best = min((d.get(i, np.inf) for i in range(ends[dst], ends[dst + 1])), default=np.inf)
                a = T[o, dst]
                if np.isinf(a) != np.isinf(best):
                    return {"ok": False, "reason": "reachability mismatch"}
                if np.isfinite(a):
                    worst = max(worst, abs(a - best))
    return {"ok": worst <= tol, "max_abs_diff_s": worst, "scenarios": 4}


def gate_through(net, tol=1e-6):
    """G3 (pair level, as pre-registered): through-running is never slower than full closure on pairs connected in both."""
    bad, pairs = 0, 0
    for s in range(net.n):
        full, thr = net.times(removed=[s]), net.times(removed=[s], through=True)
        both = np.isfinite(full) & np.isfinite(thr)
        bad += int((thr[both] > full[both] + tol).sum())
        pairs += int(both.sum())
        # a pair connected under full closure must stay connected under through-running
        bad += int((np.isfinite(full) & ~np.isfinite(thr)).sum())
    return {"ok": bad == 0, "violations": bad, "pairs_compared": pairs}


def passage_shares(net):
    """Share of ordered pairs whose intact optimal path passes through a station / transfers at a station."""
    T, dist, pred = net.times(predecessors=True)
    n, S = net.n, net.S
    ends = list(net.starts) + [S]
    passage, transfer_use, pairs, ties = np.zeros(n), np.zeros(n), 0, 0
    for o in range(n):
        for d in range(n):
            if o == d or not np.isfinite(T[o, d]):
                continue
            vals = dist[o, ends[d]:ends[d + 1]]
            ties += int((np.abs(vals - vals.min()) < 1e-9).sum() > 1)
            cur, seen, tr = ends[d] + int(np.argmin(vals)), [], []
            while 0 <= cur < S:
                p = pred[o, cur]
                if 0 <= p < S and net.st_of[p] == net.st_of[cur]:
                    tr.append(net.st_of[cur])
                seen.append(net.st_of[cur])
                cur = p
            for s in set(seen) - {o, d}:
                passage[s] += 1
            for s in set(tr) - {o, d}:
                transfer_use[s] += 1
            pairs += 1
    return passage / pairs, transfer_use / pairs, ties


def set_level(net, central, base, rng):
    T0 = net.times()
    dT = np.array(central["dT_close"])
    out = {}
    for k in (3, 5):
        res = {}
        sets = {"by_dT": top_ids(dT, k), **{f"by_{b}": top_ids(base[b], k) for b in SIMPLE}}
        for name, ids in sets.items():
            e = effect(T0, net.times(removed=sorted(ids)))
            res[name] = {"dT": e["dT"], "n_disc": e["n_disc"]}
        rand = []
        for _ in range(200):
            ids = sorted(rng.choice(net.n, k, replace=False).tolist())
            e = effect(T0, net.times(removed=ids))
            rand.append((e["dT"], e["n_disc"]))
        rd = np.array([r[0] for r in rand])
        res["random_200"] = {"dT_mean": float(np.nanmean(rd)),
                             "dT_p05_p95": [float(np.nanpercentile(rd, 5)), float(np.nanpercentile(rd, 95))],
                             "n_disc_mean": float(np.mean([r[1] for r in rand]))}
        out[f"k{k}"] = res
    return out


def hop_replication(hop_result):
    c = np.array(hop_result["disc_close"]) // 2  # ordered -> unordered
    frag = c[c > 0]
    inter = np.array(hop_result["disc_inter"]) // 2
    got = {"fragmenting_closures": int((c > 0).sum()), "min_fragmenting": int(frag.min()),
           "median_fragmenting": float(np.median(frag)), "max": int(c.max()),
           "interchange_scenarios_disconnecting": int((inter > 0).sum()), "interchange_max_disconnected": int(inter.max())}
    want = {"fragmenting_closures": 84, "min_fragmenting": 240, "median_fragmenting": 1180.0, "max": 4296,
            "interchange_scenarios_disconnecting": 1, "interchange_max_disconnected": 1410}
    return {"ok": got == want, "got": got, "expected_v04": want}


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--quick", action="store_true", help="tiny grid for a smoke test; not the pre-registered run")
    ap.add_argument("--output", type=Path, default=HERE / "results_summary.json")
    a = ap.parse_args(argv)
    t_start = time.time()
    (HERE / "local").mkdir(exist_ok=True)

    gates = {}
    vp = subprocess.run([sys.executable, str(ROOT / "validate.py")], capture_output=True, text=True, cwd=ROOT)
    gates["G4_validate_py"] = {"ok": vp.returncode == 0, "last_line": vp.stdout.strip().splitlines()[-1]}
    mf = json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))["files"]
    gates["G4_v010_hashes"] = {"ok": all(sha(DATA / n) == v["sha256"] for n, v in mf.items())}
    gm = json.loads((GD / "gtfs_manifest.json").read_text(encoding="utf-8"))
    gates["G4_phase1_hashes"] = {"ok": all(sha(GD / n) == h for n, h in gm["outputs_sha256"].items())}
    if not all(g["ok"] for g in gates.values()):
        print(json.dumps(gates, indent=1))
        raise SystemExit("G4 failed: no results produced")

    cells = cells_grid(a.quick)
    print(f"{len(cells)} cells, workers={a.workers}", flush=True)
    with ProcessPoolExecutor(max_workers=a.workers) as ex:
        results = list(ex.map(run_cell, cells))
    print(f"cells done in {time.time() - t_start:.0f} s", flush=True)

    central = next(r for r in results if is_central(r["cell"]))
    hop = next(r for r in results if r["cell"]["mode"] == "hop")
    through = next(r for r in results if r["cell"]["closure"] == "through")
    removed = [r for r in results if r["cell"]["l3"] == "removed" and r["cell"]["transfer"] == 180.0]
    net, _ = make_net(CENTRAL)
    stations, connections, transfers, rides, hw = load_inputs()
    base = baselines(net, rides, 1.0)

    gates["G1_hop_replication_of_v04"] = hop_replication(hop)
    gates["G2_independent_solver"] = gate_solver(net)
    time_cells = [r for r in results if r["cell"]["mode"] == "time"]
    worst = min(r["min_delta"] for r in time_cells)
    gates["G3_monotonicity"] = {"ok": worst >= -1e-6, "min_delta_s": worst}
    d_full, d_thr = np.array(central["dT_close"]), np.array(through["dT_close"])
    gates["G3_through_not_worse_than_full"] = gate_through(net)
    ut = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", str(HERE), "-p", "test_experiment.py"],
                        capture_output=True, text=True, cwd=ROOT)
    gates["G5_unit_tests"] = {"ok": ut.returncode == 0,
                              "summary": (ut.stderr.strip().splitlines() or [""])[-1]}
    if not all(g["ok"] for g in gates.values()):
        print(json.dumps(gates, indent=1))
        raise SystemExit("A pre-registered gate failed: results are NOT valid (see gates above)")

    rng = np.random.default_rng(SEED)
    dT = np.array(central["dT_close"])
    primary = central["decision"]
    primary["ci95_rho_betweenness_hop"] = bootstrap_ci(dT, base["betweenness_hop"], rng=rng)
    cls = lambda r: r["decision"]["class"]  # noqa: E731
    peak = [r for r in time_cells if r["cell"]["band"] == "weekday_peak" and r["cell"]["l3"] == "imputed"
            and r["cell"]["closure"] == "full"]
    other = [r for r in time_cells if r["cell"]["band"] != "weekday_peak" and r["cell"]["l3"] == "imputed"]
    share = lambda rs, c: sum(cls(r) == c for r in rs) / len(rs)  # noqa: E731
    robust = share(peak, primary["class"]) >= 0.9 and share(other, primary["class"]) >= 0.9
    classes = ("ABSTAIN", "INCONCLUSIVE", "ADDED_VALUE")
    sens = {"weekday_peak_cells": len(peak), "other_band_cells": len(other),
            "peak_class_shares": {c: share(peak, c) for c in classes},
            "other_class_shares": {c: share(other, c) for c in classes},
            "rho_max_range_peak": [min(r["decision"]["rho_max"] for r in peak), max(r["decision"]["rho_max"] for r in peak)],
            "rho_max_range_other": [min(r["decision"]["rho_max"] for r in other), max(r["decision"]["rho_max"] for r in other)],
            "class_at_0.80_threshold_central": central["decision"]["class_0.80"],
            "class_at_0.95_threshold_central": central["decision"]["class_0.95"],
            "robust": bool(robust),
            "l3_removed_classes": {f"transfer_{int(r['cell']['transfer'])}": cls(r) for r in removed},
            "l3_removed_rho_max": {f"transfer_{int(r['cell']['transfer'])}": r["decision"]["rho_max"] for r in removed}}
    verdict = primary["class"] if robust else "SENSITIVE_TO_ASSUMPTIONS"
    freeze = (cls(removed[0]) != primary["class"]) or not robust

    inter_ids = central["inter_ids"]
    dTa, dTb = np.array(central["dT_inter"]), dT[inter_ids]
    h2 = rho(dTa, dTb)
    band_c = {r["cell"]["band"]: np.array(r["dT_close"]) for r in time_cells
              if r["cell"]["transfer"] == 180.0 and r["cell"]["wait"] == 0.5 and r["cell"]["speed"] == 1.0
              and r["cell"]["l3h"] == 1.0 and r["cell"]["l3"] == "imputed" and r["cell"]["closure"] == "full"}
    pairs_rho = {f"{x}|{y}": rho(band_c[x], band_c[y]) for x, y in itertools.combinations(BANDS, 2)}
    worst_pair = min(pairs_rho, key=pairs_rho.get)
    h3, h4 = pairs_rho[worst_pair], rho(dT, np.array(hop["dT_close"]))
    sec = {"H2_rho_interchange_disabled_vs_closed": h2, "H2_supported_rankings_differ": bool(h2 < 0.90),
           "H3_min_rho_between_bands": h3, "H3_supported_stable": bool(h3 >= 0.90), "H3_pairs": pairs_rho,
           "H4_rho_time_vs_hop": h4, "H4_supported_times_change_ranking": bool(h4 < 0.90)}
    wa, wb = worst_pair.split("|")
    plist = {"H2": perm_p(dTa, dTb, rng=rng), "H3_min_pair": perm_p(band_c[wa], band_c[wb], rng=rng),
             "H4": perm_p(dT, np.array(hop["dT_close"]), rng=rng),
             **{f"baseline_{b}": perm_p(dT, base[b], rng=rng) for b in SIMPLE}}
    sec["permutation_p_descriptive"] = plist
    sec["holm_adjusted_p_descriptive"] = dict(zip(plist, holm(np.array(list(plist.values()))).tolist()))

    nofrag = np.array(central["disc_close"]) == 0
    passage, tuse, ties = passage_shares(net)
    expl = {"nonfragmenting_closures": int(nofrag.sum()),
            "rho_vs_simple_nonfragmenting": {b: rho(dT[nofrag], base[b][nofrag]) for b in SIMPLE},
            "through_vs_full": {"rho": rho(dT, d_thr), "mean_dT_full_s": float(np.nanmean(d_full)),
                                "mean_dT_through_s": float(np.nanmean(d_thr))},
            "set_level": set_level(net, central, base, rng),
            "simulation_tier": {"rho_dT_vs_passage_share": rho(dT, passage), "tied_pairs_in_passage_calc": ties,
                                "rho_dT_inter_vs_transfer_use_share": rho(dTa, tuse[inter_ids]),
                                "rho_dT_inter_vs_simple": {b: rho(dTa, base[b][inter_ids]) for b in SIMPLE}},
            "disruption_distribution_central": {
                "closure_dT_s": {q: float(np.nanpercentile(dT, p)) for q, p in
                                 (("min", 0), ("p25", 25), ("median", 50), ("p75", 75), ("p95", 95), ("max", 100))},
                "mean_T0_s": central["T0_mean"], "closures_with_disconnection": int(sum(d > 0 for d in central["disc_close"])),
                "interchange_dT_s": {q: float(np.nanpercentile(dTa, p)) for q, p in (("min", 0), ("median", 50), ("max", 100))},
                "interchange_scenarios_with_disconnection": int(sum(d > 0 for d in central["disc_inter"]))}}
    grid = [{"cell": {k: r["cell"][k] for k in ("band", "wait", "transfer", "speed", "l3h", "l3", "closure", "mode")},
             "class": cls(r), "rho_max": r["decision"]["rho_max"], "best": r["decision"]["best_baseline"],
             "overlap10": r["decision"]["overlap10"]} for r in time_cells]
    summary = {
        "pre_registration": {"commit": PREREG_COMMIT, "sha256": sha(HERE / "PRE_REGISTRATION.md")},
        "status": "NEEDS_VALIDATION; planned/scheduled model; not real-time, not demand, not observed",
        "quick_run": a.quick, "cells": len(cells), "seed": SEED,
        "inputs": {"v010_manifest_sha256": sha(DATA / "manifest.json"), "gtfs_sha256": gm["inputs"]["gtfs_sha256"],
                   "gtfs_calendar_end": gm["inputs"]["gtfs_calendar_end"]},
        "gates": gates, "primary": {"verdict": verdict, "freeze_trigger": bool(freeze), **primary},
        "sensitivity": sens, "secondary": sec, "exploratory": expl, "grid": grid,
        "runtime_s": round(time.time() - t_start),
        "versions": {"numpy": np.__version__, "networkx": nx.__version__, "python": sys.version.split()[0]}}
    a.output.write_text(json.dumps(summary, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    (HERE / "local" / "station_level_central.json").write_text(json.dumps(
        [{"station_id": s, "name": stations[s]["name"], "dT_close_s": float(dT[i]), "n_disc_close": central["disc_close"][i],
          **{b: float(base[b][i]) for b in SIMPLE}, "passage_share": float(passage[i])}
         for i, s in enumerate(net.stations)], ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"verdict": verdict, "rho_max": primary["rho_max"], "best": primary["best_baseline"],
                      "overlap10": primary["overlap10"], "robust": robust}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
