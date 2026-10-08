"""Robustness study of the sweep's Donchian breakout (20/10, 10 most liquid coins of each day).

    python -m lab.experiments.breakout_study

Pre-registered in results/breakout_study.md (the section above the generated
part was committed before this file ran). Six questions: the parameter
neighbourhood, stability over time, dependence on a few days, trades and
coins, costs and execution, deflation with every variant of this study counted,
and one pre-registered improvement (volume confirmation).

Ground: the sweep's cached panel (copied into $PYTHIA_AGENT_OUT/cache, so the
panel is the one the sweep judged), the sweep's simulator and split. The
simulator here is fam_common.simulate for long-only books with two additions:
per-coin contributions and turnover, and fills some hours after the decision
close. With fills at the close it reproduces fam_common.simulate exactly, which
is asserted on the base configuration.

Fills after the close (question 4): a trade decided at the close of day t is
filled at an hourly price h hours later. Until then the old book earns the
move from the close to the fill; from the fill the new book earns the move to
the next close. The next day's open is the first hourly open of day t+1, which
in a 24-hour market is a few seconds after the close; the later fills are the
real test. A full day late shifts the decisions by one row.

The sweep's 100 trials are read from its reports and runs under
$PYTHIA_DATA/agent-strategies (read only).
"""

from __future__ import annotations

import json
import warnings

import numpy as np
from scipy import stats

from ..data import HOUR_US, ROOT
from ..metrics import deflated_sharpe
from . import fam_breakout
from . import fam_common as fc

NAME = "breakout_study"
SWEEP = ROOT / "agent-strategies"
BASE = (20, 10, 10)                      # entry N, exit N, universe size
ENTRIES = [10, 15, 20, 30, 40, 55]
EXIT_DIVS = [2, 3]
TOPS = [5, 10, 20, 30]
START = 60
COSTS = {"15bps": 0.0015, "41bps": 0.0041, "80bps": 0.0080}
FILLS = {"next open": 0, "close + 1h": 1, "close + 4h": 4, "close + 12h": 12}
VOL_MULT, VOL_WIN = 1.5, 20              # question 6, fixed before the run
HALF_SPREAD_IN_MODEL = 0.0005            # the 15 bps model: 10 bps taker + 5 bps half-spread
BOOT_DRAWS, BOOT_BLOCKS = 10_000, (5, 20, 60)
MARKER = "<!-- generated below by lab.experiments.breakout_study; edit above this line only -->"


# ---------------------------------------------------------------------------
# Weights and simulation
# ---------------------------------------------------------------------------

_TOP: dict[int, np.ndarray] = {}


def top_liquid(P: fc.Panel, n: int) -> np.ndarray:
    if n not in _TOP:
        _TOP[n] = P.top_liquid(n)
    return _TOP[n]


def weights(P: fc.Panel, n_entry: int, n_exit: int, top: int, confirm: np.ndarray | None = None) -> np.ndarray:
    """fam_breakout.breakout_weights with a free exit window and an optional entry filter."""
    allowed = top_liquid(P, top)
    cols = np.flatnonzero(allowed.any(0))
    px = P.px[:, cols]
    hi = fc.rolling_extreme(px, n_entry, "max")
    lo = fc.rolling_extreme(px, n_exit, "min")
    with np.errstate(invalid="ignore"):
        enter = (px > hi) & allowed[:, cols]
        leave = (px < lo) | ~P.alive[:, cols]
    if confirm is not None:
        enter &= confirm[:, cols]
    with np.errstate(invalid="ignore", divide="ignore"):
        size = np.minimum(fam_breakout.COIN_VOL / (P.sigma[:, cols] * np.sqrt(365)) / top, 1.0 / top)
    size = np.nan_to_num(size)
    W = np.full((P.T, P.N), np.nan)
    held = np.zeros(len(cols), dtype=bool)
    for t in range(P.T):
        row = np.full(len(cols), np.nan)
        ex = held & leave[t]
        en = ~held & enter[t] & (size[t] > 0)
        row[ex] = 0.0
        row[en] = size[t, en]
        held = (held & ~ex) | en
        W[t, cols] = row
    W[:, np.setdiff1d(np.arange(P.N), cols)] = 0.0
    return W


def simulate(P: fc.Panel, W: np.ndarray, ra: np.ndarray | None = None, detail: bool = False) -> dict:
    """Long-only fc.simulate. ra[t, j]: return of coin j from the close of day t to the fill
    (None = fill at the close). detail adds per-coin contribution, turnover and holdings."""
    T, N = W.shape
    w = np.zeros(N)
    gross, tov, expo = np.zeros(T), np.zeros(T), np.zeros(T)
    if detail:
        contrib, tov_c, held, entry = (np.zeros((T, N)) for _ in range(4))
    for t in range(START, T - 1):
        r = np.nan_to_num(P.ret[t + 1])
        tgt = np.where(np.isnan(W[t]), w, W[t])
        tgt = np.where(P.traded[t] | (tgt == w), tgt, w)
        changed = tgt != w
        ent = changed & (w == 0) & (tgt > 0)
        if ra is None:
            d = np.abs(tgt - w)
            w = tgt
            g = float(np.dot(w, r))
            c = w * r
            step = r
        else:
            a = np.nan_to_num(ra[t])
            ga = float(np.dot(w, a))
            ca = w * a
            w = w * (1 + a) / (1 + ga) if 1 + ga > 0 else np.zeros(N)
            new = np.where(changed, tgt, w)
            d = np.abs(new - w)
            w = new
            step = (1 + r) / (1 + a) - 1
            gb = float(np.dot(w, step))
            g = (1 + ga) * (1 + gb) - 1
            c = ca + w * step
        tov[t] += d.sum()
        gross[t + 1] = g
        expo[t] = w.sum()
        if detail:
            contrib[t + 1] = c
            tov_c[t] += d
            held[t] = w
            entry[t] = np.where(ent, d, 0.0)
        w = w * (1 + step) / (1 + (gb if ra is not None else g)) if 1 + g > 0 else np.zeros(N)
        dead = (w != 0) & ~P.alive[t + 1]
        if dead.any():
            tov[t + 1] += np.abs(w[dead]).sum()
            if detail:
                tov_c[t + 1] += np.abs(np.where(dead, w, 0.0))
            w[dead] = 0.0
    out = {"gross": gross, "turnover": tov, "expo": expo}
    if detail:
        out.update(contrib=contrib, tov_c=tov_c, held=held, entry=entry)
    return out


def net(s: dict, cost: float, extra: np.ndarray | None = None) -> np.ndarray:
    n = s["gross"] - cost * np.r_[0.0, s["turnover"][:-1]]
    if extra is not None:
        n = n - np.r_[0.0, extra[:-1]]
    return n


# ---------------------------------------------------------------------------
# Hourly prices for fills and spread estimates
# ---------------------------------------------------------------------------

def hourly_fields(P: fc.Panel, cols: np.ndarray) -> dict[str, np.ndarray]:
    """(T, N) per day t: fill prices h hours after the close of t, and the Abdi-Ranaldo
    squared spread over the six hourly bars around that close (21:00 to 03:00 UTC)."""
    cache = fc.OUT / "cache" / "breakout_hourly.npz"
    if cache.exists():
        z = np.load(cache)
        if set(np.flatnonzero(z["have"])) >= set(cols.tolist()):
            return {k: z[k] for k in z.files}
    from .picks import hourly_segments
    T, N = P.T, P.N
    out = {f"fill_{h}": np.full((T, N), np.nan) for h in FILLS.values()}
    out["ar_s2"] = np.full((T, N), np.nan)
    out["have"] = np.zeros(N, dtype=bool)
    by_symbol: dict[str, list[int]] = {}
    for j in cols:
        by_symbol.setdefault(P.names[j].split("~")[0], []).append(int(j))
    t0 = int(P.days[0])
    H = (T + 2) * 24
    for i, (sym, js) in enumerate(sorted(by_symbol.items())):
        segs = hourly_segments(sym)
        for k, seg in enumerate(segs):
            name = sym if k == len(segs) - 1 else f"{sym}~{k}"
            if name not in P.names or P.col(name) not in js:
                continue
            j = P.col(name)
            ot = seg["open_time_us"].to_numpy()
            hi = ((ot - t0) // HOUR_US).astype(np.int64)
            ok = (hi >= 0) & (hi < H)
            dense = {f: np.full(H, np.nan) for f in ("open", "high", "low", "close")}
            for f in dense:
                dense[f][hi[ok]] = seg[f].to_numpy().astype(float)[ok]
            end = (np.arange(T) + 1) * 24          # first hour of day t+1
            out["fill_0"][:, j] = dense["open"][end]
            for h in (1, 4, 12):
                out[f"fill_{h}"][:, j] = dense["close"][end + h - 1]
            with np.errstate(invalid="ignore", divide="ignore"):
                lc = np.log(dense["close"])
                eta = (np.log(dense["high"]) + np.log(dense["low"])) / 2
                q = np.full(H, np.nan)
                q[:-1] = 4 * (lc[:-1] - eta[:-1]) * (lc[:-1] - eta[1:])
            win = np.stack([q[end + o] for o in range(-3, 2)], axis=1)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                out["ar_s2"][:, j] = np.nanmean(win, axis=1)
            out["have"][j] = True
        if i % 20 == 0:
            print(f"  hourly {i}/{len(by_symbol)}", flush=True)
    cache.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(cache, **out)
    return out


# ---------------------------------------------------------------------------
# Measuring
# ---------------------------------------------------------------------------

def sharpe(x: np.ndarray) -> float:
    return fc.perf(x)["sharpe"]


def trial_row(x_oos: np.ndarray, label: str) -> dict:
    """What fc.deflate needs of one trial: its out-of-sample Sharpe, skew, kurtosis, length."""
    return {"variant": label, "oos_sharpe_15bps": sharpe(x_oos), "oos_skew": float(stats.skew(x_oos)),
            "oos_kurt": float(stats.kurtosis(x_oos, fisher=False)), "oos_days": int(len(x_oos))}


def describe(P: fc.Panel, s: dict, extra: np.ndarray | None = None) -> dict:
    ins, oos = fc.masks(P)
    row = {}
    for k, c in COSTS.items():
        n = net(s, c, extra)
        pi, po = fc.perf(n[ins]), fc.perf(n[oos])
        row[f"is_{k}"] = pi["sharpe"]
        row[f"oos_{k}"] = po["sharpe"]
        row[f"cagr_{k}"] = po["cagr"]
        row[f"dd_{k}"] = po["max_dd"]
    row["turnover_yr"] = float(s["turnover"][oos].sum() / (oos.sum() / 365))
    row["expo"] = float(s["expo"][oos].mean())
    return row


def stationary_bootstrap(x: np.ndarray, block: float, draws: int, rng: np.random.Generator) -> np.ndarray:
    """Annual Sharpes of Politis-Romano stationary bootstrap resamples of x."""
    n = len(x)
    idx = np.empty((draws, n), dtype=np.int64)
    idx[:, 0] = rng.integers(0, n, draws)
    jump = rng.random((draws, n)) < 1 / block
    fresh = rng.integers(0, n, (draws, n))
    for i in range(1, n):
        idx[:, i] = np.where(jump[:, i], fresh[:, i], (idx[:, i - 1] + 1) % n)
    s = x[idx]
    return s.mean(1) / s.std(1) * np.sqrt(365)


def trades(P: fc.Panel, s: dict, oos: np.ndarray) -> list[dict]:
    """Every position from entry to exit, with its gross contribution to the book's out-of-sample
    returns (sum of the coin's daily weight times return; additive, no compounding)."""
    held = s["held"] > 0
    out = []
    for j in np.flatnonzero(held.any(0)):
        h = held[:, j]
        starts = np.flatnonzero(h & ~np.r_[False, h[:-1]])
        ends = np.flatnonzero(h & ~np.r_[h[1:], False])
        for a, b in zip(starts, ends):
            days = np.arange(a + 1, b + 2)
            days = days[(days < P.T) & oos[np.minimum(days, P.T - 1)]]
            if not len(days):
                continue
            px0, px1 = P.px[a, j], P.px[min(b + 1, P.T - 1), j]
            out.append({"coin": P.names[j], "entry": _date(P, a), "exit": _date(P, b + 1),
                        "days": int(b - a + 1), "pnl": float(s["contrib"][days, j].sum()),
                        "coin_ret": float(px1 / px0 - 1) if np.isfinite(px0) and np.isfinite(px1) else float("nan")})
    return out


def _date(P: fc.Panel, t: int) -> str:
    return str(np.datetime64(int(P.days[min(t, P.T - 1)]), "us").astype("datetime64[D]"))


def years(P: fc.Panel) -> np.ndarray:
    return np.array([int(_date(P, t)[:4]) for t in range(P.T)])


# ---------------------------------------------------------------------------
# The sweep's 100 trials
# ---------------------------------------------------------------------------

def sweep_rows() -> list[dict]:
    rep = json.loads((SWEEP / "reports" / "families_summary.json").read_text(encoding="utf-8"))
    assert rep["n_variants"] == len(rep["all_rows"]) == 100
    return rep["all_rows"]


def sweep_returns(P: fc.Panel) -> np.ndarray:
    """(100, OOS days) net returns at 15 bps of the sweep's trials, in the order of all_rows."""
    _, oos = fc.masks(P)
    out = []
    for fam in ["reversal", "volmom", "breakout", "pairs", "season", "funding", "lowvol", "blend", "ensemble"]:
        z = np.load(SWEEP / "runs" / f"{fam}.npz")
        for g, tv in zip(z["gross"], z["turnover"]):
            out.append((g - 0.0015 * np.r_[0.0, tv[:-1]])[oos])
    return np.array(out)


def effective_trials(R: np.ndarray) -> dict:
    """Two estimates of the number of independent trials, from the correlation of their returns.

    eigen: participation ratio of the correlation matrix's eigenvalues; a strong
    common factor (the market) pulls it far down, so it is the lenient end.
    avg_corr: N_eff = rho + (1 - rho) N with rho the mean off-diagonal
    correlation (Bailey and Lopez de Prado's approximation); the stricter end.
    """
    C = np.nan_to_num(np.corrcoef(R))
    lam = np.clip(np.linalg.eigvalsh(C), 0, None)
    n = len(C)
    rho = float((C.sum() - np.trace(C)) / (n * (n - 1)))
    return {"eigen": float(lam.sum() ** 2 / (lam ** 2).sum()), "avg_corr": rho + (1 - rho) * n, "rho": rho}


def deflate_one(row: dict, pool: list[dict], n_trials: float | None = None) -> dict:
    """fc.deflate's rule for one row against a pool, optionally with an effective trial count."""
    raw = np.array([r["oos_sharpe_15bps"] for r in pool])
    var = float(np.var(np.clip(raw, -fc.SR_CLIP, fc.SR_CLIP) / np.sqrt(365)))
    n = len(pool) if n_trials is None else n_trials
    s = row["oos_sharpe_15bps"] / np.sqrt(365)
    T = row["oos_days"]
    return {"trials": n, "sr0_annual": fc._sr0(var, n) * np.sqrt(365) if n > 1 else 0.0,
            "p": deflated_sharpe(s, T, n, var, row["oos_skew"], row["oos_kurt"]),
            "p_normal": deflated_sharpe(s, T, n, var),
            "p_null": deflated_sharpe(s, T, n, 1 / T, row["oos_skew"], row["oos_kurt"])}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def label(ne: int, nx: int, top: int) -> str:
    return f"Donchian {ne}/{nx} · top {top}"


def main() -> None:
    P = fc.load_panel()
    ins, oos = fc.masks(P)
    yr = years(P)
    rng = np.random.default_rng(20261008)
    res: dict = {}
    study_trials: list[tuple[str, np.ndarray]] = []    # every new return series, counted
    pool_names = {r["variant"] for r in sweep_rows()}

    # Base: reproduce the sweep exactly.
    W0 = weights(P, *BASE)
    cols10 = np.flatnonzero(top_liquid(P, 10).any(0))
    assert np.array_equal(np.isnan(W0), np.isnan(fam_breakout.breakout_weights(P, cols10, top_liquid(P, 10), 20, 10, False)))
    base = simulate(P, W0, detail=True)
    g_ref = fc.simulate(P, fam_breakout.breakout_weights(P, cols10, top_liquid(P, 10), 20, 10, False), start=START)[0]
    assert np.allclose(base["gross"], g_ref), "simulator does not reproduce fam_common.simulate"
    b = describe(P, base)
    res["base"] = b
    print("base", json.dumps({k: round(v, 3) for k, v in b.items()}), flush=True)
    n15, n41, n80 = (net(base, c) for c in COSTS.values())

    # Q1: the grid.
    grid = []
    for ne in ENTRIES:
        for dv in EXIT_DIVS:
            for top in TOPS:
                nx = ne // dv
                s = base if (ne, nx, top) == BASE else simulate(P, weights(P, ne, nx, top))
                row = {"entry": ne, "exit": nx, "exit_rule": f"N/{dv}", "top": top, **describe(P, s)}
                grid.append(row)
                in_pool = (top == 10 and dv == 2 and f"Donchian {ne}/{nx} · top 10 liquid" in pool_names)
                row["in_sweep"] = in_pool
                if not in_pool:
                    study_trials.append((label(ne, nx, top), net(s, COSTS["15bps"])[oos]))
        print(f"  grid N={ne} done", flush=True)
    res["grid"] = grid
    G = {(r["entry"], r["exit_rule"], r["top"]): r for r in grid}

    def nbrs(ne, rule, top):
        i, k = ENTRIES.index(ne), TOPS.index(top)
        out = [(ENTRIES[i + d], rule, top) for d in (-1, 1) if 0 <= i + d < len(ENTRIES)]
        out += [(ne, "N/3" if rule == "N/2" else "N/2", top)]
        out += [(ne, rule, TOPS[k + d]) for d in (-1, 1) if 0 <= k + d < len(TOPS)]
        return out

    nb = [G[x] for x in nbrs(20, "N/2", 10)]
    plateau = {"neighbours": [label(r["entry"], r["exit"], r["top"]) for r in nb],
               "neighbour_oos41": [r["oos_41bps"] for r in nb],
               "median": float(np.median([r["oos_41bps"] for r in nb])),
               "min": float(min(r["oos_41bps"] for r in nb)), "base": b["oos_41bps"]}
    plateau["is_plateau"] = plateau["median"] >= 0.75 * b["oos_41bps"] and plateau["min"] > 0
    res["plateau"] = plateau
    is_pick = max(grid, key=lambda r: r["is_15bps"])
    centre = max(grid, key=lambda r: np.median([r["is_15bps"]] + [G[x]["is_15bps"] for x in nbrs(r["entry"], r["exit_rule"], r["top"])]))
    res["is_pick"], res["is_centre"] = is_pick, centre
    for r in grid:
        r["nbhd_is_median"] = float(np.median([r["is_15bps"]] + [G[x]["is_15bps"] for x in nbrs(r["entry"], r["exit_rule"], r["top"])]))
        r["nbhd_oos41_median"] = float(np.median([r["oos_41bps"]] + [G[x]["oos_41bps"] for x in nbrs(r["entry"], r["exit_rule"], r["top"])]))
    res["grid_positive_41"] = float(np.mean([r["oos_41bps"] > 0 for r in grid]))
    res["grid_median"] = {k: float(np.median([r[k] for r in grid])) for k in ("is_15bps", "oos_15bps", "oos_41bps")}
    res["base_is_rank"] = 1 + sum(r["is_15bps"] > b["is_15bps"] for r in grid)
    res["base_oos41_rank"] = 1 + sum(r["oos_41bps"] > b["oos_41bps"] for r in grid)
    res["grid_positive_80"] = float(np.mean([r["oos_80bps"] > 0 for r in grid]))

    # Q2: time.
    bench = fc.benchmarks(P)
    per_year = []
    for y in range(2021, 2027):
        m = (yr == y) & (P.days >= fc.IS_START)
        m15, m41 = fc.perf(n15[m]), fc.perf(n41[m])
        per_year.append({"year": y, "sample": "in" if y < 2024 else "out", "days": int(m.sum()),
                         "sharpe_15": m15["sharpe"], "sharpe_41": m41["sharpe"], "ret_41": float(np.prod(1 + n41[m]) - 1),
                         "dd_41": m41["max_dd"], "expo": float(base["expo"][m].mean()),
                         "btc_sharpe": fc.perf(bench["btc"][m])["sharpe"],
                         "btc_ret": float(np.prod(1 + bench["btc"][m]) - 1)})
    res["per_year"] = per_year
    drop_year = []
    for y in (2024, 2025, 2026):
        m = oos & (yr != y)
        drop_year.append({"without": y, "sharpe_15": sharpe(n15[m]), "sharpe_41": sharpe(n41[m])})
    res["drop_year"] = drop_year
    roll = []
    for t in np.flatnonzero(oos):
        if t - 364 < 0 or not oos[t - 364]:
            continue
        roll.append((t, sharpe(n41[t - 364:t + 1]), sharpe(bench["btc"][t - 364:t + 1])))
    res["rolling_41"] = {"min": min(r[1] for r in roll), "median": float(np.median([r[1] for r in roll])),
                         "max": max(r[1] for r in roll), "share_positive": float(np.mean([r[1] > 0 for r in roll])),
                         "windows": len(roll),
                         "quarterly": [{"end": _date(P, t), "sharpe_41": a, "btc": c} for t, a, c in roll
                                       if _date(P, t)[5:] in ("03-31", "06-30", "09-30", "12-31") or t == roll[-1][0]]}
    roll_all = [sharpe(n41[t - 364:t + 1]) for t in range(fc.masks(P)[0].argmax() + 364, P.T)]
    res["rolling_41_full"] = {"min": min(roll_all), "median": float(np.median(roll_all)),
                              "share_positive": float(np.mean(np.array(roll_all) > 0)), "windows": len(roll_all)}
    on_prev = np.r_[False, P.btc_on[:-1]]
    res["regime"] = []
    for nm, m in (("in sample", ins), ("out of sample", oos)):
        for st, mm in (("BTC above 200d", on_prev), ("BTC below 200d", ~on_prev)):
            k = m & mm
            res["regime"].append({"period": nm, "state": st, "days": int(k.sum()), "sharpe_15": sharpe(n15[k]),
                                  "sharpe_41": sharpe(n41[k]), "expo": float(base["expo"][k].mean()),
                                  "btc_sharpe": sharpe(bench["btc"][k])})

    # Q3: a few days, a few trades, one coin.
    trim = []
    for nm, x in (("breakout 41 bps", n41[oos]), ("breakout 15 bps", n15[oos]), ("BTC buy and hold", bench["btc"][oos]),
                  ("equal-weight universe", bench["ew"][oos])):
        row = {"series": nm}
        for q in (0, 1, 5):
            y = x.copy()
            if q:
                k = int(round(len(y) * q / 100))
                y[np.argsort(y)[-k:]] = 0.0
            p = fc.perf(y)
            row[f"sharpe_drop{q}"], row[f"cagr_drop{q}"] = p["sharpe"], p["cagr"]
        trim.append(row)
    res["trim"] = trim
    tr = trades(P, base, oos)
    tot = sum(t["pnl"] for t in tr)
    tr_sorted = sorted(tr, key=lambda t: -t["pnl"])
    res["trades"] = {"n": len(tr), "total_pnl": tot, "top10_share": sum(t["pnl"] for t in tr_sorted[:10]) / tot,
                     "top1_share": tr_sorted[0]["pnl"] / tot,
                     "win_rate": float(np.mean([t["pnl"] > 0 for t in tr])),
                     "median_days": float(np.median([t["days"] for t in tr])),
                     "avg_win": float(np.mean([t["pnl"] for t in tr if t["pnl"] > 0])),
                     "avg_loss": float(np.mean([t["pnl"] for t in tr if t["pnl"] <= 0])),
                     "top10": tr_sorted[:10], "bottom5": tr_sorted[-5:],
                     "pnl_without_top10": tot - sum(t["pnl"] for t in tr_sorted[:10])}
    con = base["contrib"][oos].sum(0)
    coins = []
    for j in np.argsort(-np.abs(con))[:12]:
        if con[j] == 0:
            continue
        x = n41 - base["contrib"][:, j] + COSTS["41bps"] * np.r_[0.0, base["tov_c"][:-1, j]]
        coins.append({"coin": P.names[j], "pnl_share": float(con[j] / con.sum()), "pnl": float(con[j]),
                      "days_held": int((base["held"][oos, j] > 0).sum()),
                      "sharpe_41_without": sharpe(x[oos])})
    res["coins"] = coins
    res["coins_held"] = int(((base["held"][oos] > 0).any(0)).sum())

    # Q4: costs and execution.
    hf = hourly_fields(P, np.flatnonzero(top_liquid(P, 10).any(0)))
    # The fill path with no move between close and fill must be the close fill.
    assert np.allclose(simulate(P, W0, ra=np.zeros((P.T, P.N)))["gross"], base["gross"])
    execu = [{"case": "close (the sweep)", **describe(P, base)}]
    for nm, h in FILLS.items():
        with np.errstate(invalid="ignore", divide="ignore"):
            ra = hf[f"fill_{h}"] / P.px - 1
        s = simulate(P, W0, ra=ra)
        execu.append({"case": f"fill at {nm}", **describe(P, s),
                      "fills_found": float(np.isfinite(ra[base['entry'] > 0]).mean())})
        study_trials.append((f"base · fill at {nm}", net(s, COSTS["15bps"])[oos]))
    Wl = np.full_like(W0, np.nan)
    Wl[1:] = W0[:-1]
    Wl[:, ~top_liquid(P, 10).any(0)] = 0.0
    s = simulate(P, Wl)
    execu.append({"case": "fill a day late (next close)", **describe(P, s)})
    study_trials.append(("base · a day late", net(s, COSTS["15bps"])[oos]))
    study_trials.append(("base · 80 bps", n80[oos]))
    # Slippage on breakout days: Abdi-Ranaldo half-spread around the entry close, above the 5 bps in the model.
    half = np.sqrt(np.clip(hf["ar_s2"], 0, None)) / 2
    # The same per-window estimate on the same hours of the 30 days BEFORE t (ordinary days).
    half_base = np.r_[np.full((1, P.N), np.nan), fc.rolling(half, 30, 10)[:-1]]
    ev = (base["entry"] > 0) & np.isfinite(half)
    ev_oos = ev & oos[:, None]
    qv = P.extra["qv"]
    qv_prev = np.r_[np.full((1, P.N), np.nan), fc.rolling(qv, VOL_WIN, 15)[:-1]]
    with np.errstate(invalid="ignore", divide="ignore"):
        rel_vol = qv / qv_prev
    extra_cost = (base["entry"] * np.nan_to_num(np.clip(half - HALF_SPREAD_IN_MODEL, 0, None))).sum(1)
    s_slip = describe(P, base, extra_cost)
    execu.append({"case": "close + breakout-day spread", **s_slip})
    study_trials.append(("base · breakout-day spread", net(base, COSTS["15bps"], extra_cost)[oos]))
    # Exits: the same estimate (not charged; pre-registration names entries).
    exits = (base["tov_c"] > 0) & (base["entry"] == 0) & np.isfinite(half) & oos[:, None]
    res["slippage"] = {
        "entries_oos": int(ev_oos.sum()),
        "half_spread_entry_bps_median": float(np.median(half[ev_oos]) * 1e4),
        "half_spread_entry_bps_mean": float(np.mean(half[ev_oos]) * 1e4),
        "half_spread_same_coin_30d_before_bps_median": float(np.nanmedian(half_base[ev_oos]) * 1e4),
        "half_spread_same_coin_30d_before_bps_mean": float(np.nanmean(half_base[ev_oos]) * 1e4),
        "half_spread_exit_bps_median": float(np.median(half[exits]) * 1e4),
        "ratio_entry_to_before_means": float(np.mean(half[ev_oos]) / np.nanmean(half_base[ev_oos])),
        "rel_volume_entry_median": float(np.nanmedian(rel_vol[ev_oos])),
        "rel_volume_entry_share_above_1_5": float(np.nanmean(rel_vol[ev_oos] >= VOL_MULT)),
        "extra_cost_bps_per_year": float(extra_cost[oos].sum() / (oos.sum() / 365) * 1e4),
    }
    # The move from the close to the fill on entries (positive = the fill is worse).
    drift = {}
    for nm, h in FILLS.items():
        with np.errstate(invalid="ignore", divide="ignore"):
            ra = hf[f"fill_{h}"] / P.px - 1
        x = ra[ev_oos]
        drift[nm] = {"mean_bps": float(np.nanmean(x) * 1e4), "median_bps": float(np.nanmedian(x) * 1e4)}
    res["entry_drift"] = drift
    res["execution"] = execu

    # Q6: volume confirmation, tested once.
    with np.errstate(invalid="ignore"):
        confirm = qv >= VOL_MULT * qv_prev
    s6 = simulate(P, weights(P, *BASE, confirm=confirm))
    res["volume_filter"] = describe(P, s6)
    study_trials.append(("base · volume confirmed 1.5x 20d", net(s6, COSTS["15bps"])[oos]))

    # Q5: deflation and bootstrap.
    pool = sweep_rows()
    base_row = next(r for r in pool if r["variant"] == "Donchian 20/10 · top 10 liquid")
    mine = trial_row(n15[oos], "base")
    assert abs(mine["oos_sharpe_15bps"] - base_row["oos_sharpe_15bps"]) < 1e-9
    ext = pool + [trial_row(x, nm) for nm, x in study_trials]
    R100 = sweep_returns(P)
    R_ext = np.vstack([R100] + [x[None] for _, x in study_trials])
    n_eff100, n_eff_ext = effective_trials(R100), effective_trials(R_ext)
    fam_rows = [r for r in pool if r["family"] == "breakout"]
    bo_rows = fam_rows + [trial_row(x, nm) for nm, x in study_trials]
    defl = {
        "sweep 100, sweep rule": deflate_one(base_row, pool),
        f"sweep 100 + study {len(study_trials)}, sweep rule": deflate_one(base_row, ext),
        "sweep 100, effective trials (mean correlation)": deflate_one(base_row, pool, n_eff100["avg_corr"]),
        "sweep 100 + study, effective trials (mean correlation)": deflate_one(base_row, ext, n_eff_ext["avg_corr"]),
        "sweep 100, effective trials (eigenvalues)": deflate_one(base_row, pool, n_eff100["eigen"]),
        "sweep 100 + study, effective trials (eigenvalues)": deflate_one(base_row, ext, n_eff_ext["eigen"]),
        "breakout family 12 + study, sweep rule": deflate_one(base_row, bo_rows),
        "one trial (probabilistic Sharpe vs 0)": deflate_one(base_row, [base_row]),
    }
    res["deflation"] = defl
    res["n_eff"] = {"sweep": n_eff100, "extended": n_eff_ext}
    res["study_trials"] = [nm for nm, _ in study_trials]
    res["n_study"] = len(study_trials)
    boot = []
    for blk in BOOT_BLOCKS:
        for k, x in (("15bps", n15[oos]), ("41bps", n41[oos])):
            bs = stationary_bootstrap(x, blk, BOOT_DRAWS, rng)
            boot.append({"block": blk, "cost": k, "sharpe": sharpe(x), "p05": float(np.percentile(bs, 5)),
                         "p95": float(np.percentile(bs, 95)), "p2_5": float(np.percentile(bs, 2.5)),
                         "p97_5": float(np.percentile(bs, 97.5)), "share_above_0": float(np.mean(bs > 0))})
        print(f"  bootstrap block {blk} done", flush=True)
    res["bootstrap"] = boot

    write(P, res)


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def _f(v, d=2):
    return fc._fmt(v) if d == 2 else (f"{v:.{d}f}" if isinstance(v, float) else str(v))


def write(P: fc.Panel, res: dict) -> None:
    t = fc.table
    path = fc.RESULTS_DIR / f"{NAME}.md"
    head = path.read_text(encoding="utf-8").split(MARKER)[0].rstrip() + "\n\n"
    g = res["grid"]

    def heat(key):
        lines = "| entry N | " + " | ".join(f"top {k}" for k in TOPS) + " |\n|---|" + "---|" * len(TOPS) + "\n"
        for ne in ENTRIES:
            cells = []
            for top in TOPS:
                a = next(r for r in g if r["entry"] == ne and r["exit_rule"] == "N/2" and r["top"] == top)
                c = next(r for r in g if r["entry"] == ne and r["exit_rule"] == "N/3" and r["top"] == top)
                mark = "**" if (ne, a["exit"], top) == BASE else ""
                cells.append(f"{mark}{a[key]:.2f}{mark} / {c[key]:.2f}")
            lines += f"| {ne} | " + " | ".join(cells) + " |\n"
        return lines

    pl_ = res["plateau"]
    sl = res["slippage"]
    md = head + MARKER + "\n\n## Results (generated)\n\n"
    md += (f"Panel: the sweep's cached panel, {P.N} segments, to "
           f"{_date(P, P.T - 1)}; out of sample from 2024-01-01 ({int(fc.masks(P)[1].sum())} days). The base "
           "reproduces the sweep exactly (asserted).\n\n")
    md += "### 1. Parameter neighbourhood\n\n"
    md += ("Cells: exit N/2 / exit N/3. Bold: the base (20/10, top 10).\n\n"
           "In-sample Sharpe at 15 bps (2020-08 to 2023):\n\n" + heat("is_15bps")
           + "\nOut-of-sample Sharpe at 41 bps (2024-01 on):\n\n" + heat("oos_41bps")
           + "\nOut-of-sample Sharpe at 15 bps:\n\n" + heat("oos_15bps")
           + f"\nShare of the 48 configurations positive out of sample: {res['grid_positive_41'] * 100:.0f} % at 41 bps, "
             f"{res['grid_positive_80'] * 100:.0f} % at 80 bps. Grid median: in sample "
             f"{res['grid_median']['is_15bps']:.2f}, out of sample {res['grid_median']['oos_15bps']:.2f} / "
             f"{res['grid_median']['oos_41bps']:.2f} at 15 / 41 bps. The base ranks {res['base_is_rank']} of 48 in "
             f"sample and {res['base_oos41_rank']} of 48 out of sample at 41 bps. Base neighbours ({', '.join(pl_['neighbours'])}) at "
             f"41 bps: {', '.join(f'{x:.2f}' for x in pl_['neighbour_oos41'])}; median {pl_['median']:.2f} against "
             f"the base's {pl_['base']:.2f} (rule: at least {0.75 * pl_['base']:.2f}, none negative): "
             f"**{'plateau' if pl_['is_plateau'] else 'peak'}**.\n\n")
    ip, ce = res["is_pick"], res["is_centre"]
    md += (f"The grid's in-sample pick: {label(ip['entry'], ip['exit'], ip['top'])} (in sample {ip['is_15bps']:.2f}), "
           f"out of sample {ip['oos_15bps']:.2f} / {ip['oos_41bps']:.2f} at 15 / 41 bps. The in-sample plateau centre "
           f"(best median in-sample Sharpe of itself and its neighbours, {ce['nbhd_is_median']:.2f}): "
           f"{label(ce['entry'], ce['exit'], ce['top'])}, out of sample {ce['oos_15bps']:.2f} / {ce['oos_41bps']:.2f}.\n\n")
    md += "<details><summary>All 48 configurations</summary>\n\n" + t(
        sorted(g, key=lambda r: (r["exit_rule"], r["entry"], r["top"])),
        ["entry", "exit", "top", "is_15bps", "oos_15bps", "oos_41bps", "oos_80bps", "cagr_41bps", "dd_41bps",
         "turnover_yr", "expo", "nbhd_is_median", "nbhd_oos41_median", "in_sweep"]) + "\n</details>\n\n"

    md += "### 2. Stability over time\n\n"
    md += t(res["per_year"], ["year", "sample", "days", "sharpe_15", "sharpe_41", "ret_41", "dd_41", "expo",
                              "btc_sharpe", "btc_ret"])
    md += "\nOut-of-sample Sharpe with one year left out:\n\n" + t(res["drop_year"], ["without", "sharpe_15", "sharpe_41"])
    ro, rf = res["rolling_41"], res["rolling_41_full"]
    md += (f"\nRolling 365-day Sharpe at 41 bps, windows fully out of sample ({ro['windows']}): min {ro['min']:.2f}, "
           f"median {ro['median']:.2f}, max {ro['max']:.2f}, positive in {ro['share_positive'] * 100:.0f} %. Over the "
           f"whole history from 2021-08 ({rf['windows']} windows): min {rf['min']:.2f}, median {rf['median']:.2f}, "
           f"positive in {rf['share_positive'] * 100:.0f} %.\n\n"
           + t(ro["quarterly"], ["end", "sharpe_41", "btc"])
           + "\nBTC 200-day regime (state at the close the position was set):\n\n"
           + t(res["regime"], ["period", "state", "days", "sharpe_15", "sharpe_41", "expo", "btc_sharpe"]) + "\n")

    md += "### 3. Dependence on a few days, trades and coins\n\n"
    md += ("Out of sample, the best 1 % / 5 % of days set to zero:\n\n"
           + t(res["trim"], ["series", "sharpe_drop0", "sharpe_drop1", "sharpe_drop5", "cagr_drop0", "cagr_drop1",
                             "cagr_drop5"]))
    tr = res["trades"]
    md += (f"\n{tr['n']} trades touch the out-of-sample period; win rate {tr['win_rate'] * 100:.0f} %, median "
           f"holding {tr['median_days']:.0f} days, average win {tr['avg_win'] * 1e4:.0f} bps of book, average loss "
           f"{tr['avg_loss'] * 1e4:.0f} bps. The 10 best trades make {tr['top10_share'] * 100:.0f} % of the gross "
           f"P&L (the best one {tr['top1_share'] * 100:.0f} %); without them the sum of the rest is "
           f"{tr['pnl_without_top10'] * 100:.1f} % of book against {tr['total_pnl'] * 100:.1f} %.\n\n"
           + t(tr["top10"], ["coin", "entry", "exit", "days", "pnl", "coin_ret"])
           + f"\nP&L per coin ({res['coins_held']} coins held out of sample; largest twelve by size; Sharpe at "
             "41 bps with that coin's trades left in cash):\n\n"
           + t(res["coins"], ["coin", "pnl_share", "pnl", "days_held", "sharpe_41_without"]) + "\n")

    md += "### 4. Costs and execution\n\n"
    md += t(res["execution"], ["case", "oos_15bps", "oos_41bps", "oos_80bps", "cagr_41bps", "dd_41bps", "turnover_yr"])
    md += ("\nMove from the decision close to the fill on out-of-sample entries (positive: the fill is dearer):\n\n"
           + t([{"fill": k, **v} for k, v in res["entry_drift"].items()], ["fill", "mean_bps", "median_bps"]))
    md += (f"\nBreakout-day spread: {sl['entries_oos']} out-of-sample entries. Abdi-Ranaldo half-spread over the six "
           f"hourly bars around the entry close: median {sl['half_spread_entry_bps_median']:.1f} bps (mean "
           f"{sl['half_spread_entry_bps_mean']:.1f}), against median "
           f"{sl['half_spread_same_coin_30d_before_bps_median']:.1f} (mean "
           f"{sl['half_spread_same_coin_30d_before_bps_mean']:.1f}) bps for the same coin and hours over the 30 days "
           f"before, a ratio of means of {sl['ratio_entry_to_before_means']:.2f}; exits "
           f"{sl['half_spread_exit_bps_median']:.1f} bps (not charged). Breakout-day "
           f"volume is a median {sl['rel_volume_entry_median']:.2f} times the 20 days before. Charging every entry the "
           f"estimate above the model's 5 bps costs {sl['extra_cost_bps_per_year']:.0f} bps a year. The estimator reads "
           "hourly ranges, so it is far above the quoted spreads `costs` measures (one tick to 2 bps); that makes this "
           "line a pessimistic bound.\n\n")
    md += "### 5. Deflation and bootstrap\n\n"
    n_grid = sum(nm.startswith("Donchian") for nm in res["study_trials"])
    md += (f"Variants of this study with their own return series: **{res['n_study']}** ({n_grid} new grid cells; "
           f"the other 2 of the 48 were already sweep trials; {res['n_study'] - n_grid - 1} execution and cost "
           f"cases, 1 improvement). With the sweep: "
           f"{100 + res['n_study']} trials. Effective independent trials from the correlation of their daily "
           f"out-of-sample returns: mean correlation {res['n_eff']['sweep']['rho']:.2f} gives "
           f"{res['n_eff']['sweep']['avg_corr']:.0f} of 100 ({res['n_eff']['extended']['rho']:.2f}, "
           f"{res['n_eff']['extended']['avg_corr']:.0f} of {100 + res['n_study']}); the eigenvalue participation ratio "
           f"gives {res['n_eff']['sweep']['eigen']:.1f} and {res['n_eff']['extended']['eigen']:.1f}, pulled down by "
           "the common market factor, so it is the lenient end.\n\n")
    md += t([{"pool": k, **v} for k, v in res["deflation"].items()],
            ["pool", "trials", "sr0_annual", "p", "p_normal", "p_null"])
    md += ("\np: the sweep's rule (winsorised variance of the trials' Sharpes, own skew and kurtosis). p_normal: the "
           "same with skew 0 and kurtosis 3. p_null: the variance a pure-noise trial would have (1/T). sr0: the "
           "annual Sharpe the best of that many noise trials would show.\n\n"
           "Stationary bootstrap of the out-of-sample Sharpe (10,000 draws):\n\n"
           + t(res["bootstrap"], ["block", "cost", "sharpe", "p2_5", "p05", "p95", "p97_5", "share_above_0"]))
    vf = res["volume_filter"]
    md += (f"\n### 6. Volume confirmation (pre-registered, tested once)\n\n"
           f"Entries only on at least {VOL_MULT}x the 20-day mean quote volume: in sample {vf['is_15bps']:.2f}, "
           f"out of sample {vf['oos_15bps']:.2f} / {vf['oos_41bps']:.2f} at 15 / 41 bps, drawdown "
           f"{vf['dd_41bps'] * 100:.0f} %, turnover {vf['turnover_yr']:.1f}, exposure {vf['expo']:.2f} (base: "
           f"{res['base']['is_15bps']:.2f}, {res['base']['oos_15bps']:.2f} / {res['base']['oos_41bps']:.2f}, "
           f"{res['base']['dd_41bps'] * 100:.0f} %, {res['base']['turnover_yr']:.1f}, {res['base']['expo']:.2f}).\n\n"
           "Every counted study variant: " + "; ".join(res["study_trials"]) + ".\n")
    fc.write_result(NAME, md, res)
    print(md)


if __name__ == "__main__":
    main()
