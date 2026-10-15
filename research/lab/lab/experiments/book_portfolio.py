"""X7 B: a portfolio of the live books, with and without a small US equity sleeve.

    python -m lab.experiments.book_portfolio      (after lab.experiments.overnight, whose cache it reads)

Pre-registered in results/book_portfolio.md (the part above the marker was
committed before this file existed). Writes that file below the marker and
<reports>/book_portfolio/latest.{md,json}.

The four crypto books are rebuilt as the autopilot runs them on Alpaca (coins
Alpaca does not list held as cash, 35 bps per unit of turnover):
breakout_top10, tsmom_top20 and tsmom_tranches through alpaca_universe's
cash-left books, tsmom_regime through lab.experiments.tsmom. The mixes work on
the books' daily net returns; drift between sleeves is traded back daily.
"""

from __future__ import annotations

import json
import math
import sys
from datetime import datetime, timezone

import numpy as np

from . import alpaca_universe as au
from . import fam_common as fc
from . import overnight as on
from . import tsmom as ts

NAME = "book_portfolio"
MARKER = "<!-- generated below by lab.experiments.book_portfolio; edit above this line only -->"
BOOKS = ("breakout_top10", "tsmom_top20", "tsmom_tranches", "tsmom_regime")
CRYPTO_COST = 0.0035
EQUITY_COST = 0.0002
YEAR = 365
IS_START = np.datetime64("2020-08-01")
SPLIT = np.datetime64("2024-01-01")
YEARS_OOS = (2024, 2025, 2026)
VOL_WIN, COV_WIN, PVOL_WIN = 90, 90, 30
VOL_FLOOR = 0.05
RIDGE = 1e-6
REWEIGHT_DAYS = 7
MIXES = ("EW", "IV", "RP", "VT15", "VT25", "DDB")
EQUITY = (("none", None, 0.0), ("SPY 20 %", "spy", 0.2), ("SPY 40 %", "spy", 0.4),
          ("overnight 20 %", "overnight", 0.2), ("overnight 40 %", "overnight", 0.4))
TRIALS_HERE = 30
A_TRIALS = 39


# ---------------------------------------------------------------------------
# Return series
# ---------------------------------------------------------------------------

def to_day(us: np.ndarray) -> np.ndarray:
    return (np.asarray(us, dtype=np.int64) // 86_400_000_000).astype("datetime64[D]")


def crypto_books() -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """(days, {book: daily net return at 35 bps}) on the sweep panel's calendar."""
    P = fc.load_panel()
    alp = au.alpaca_mask(P)
    O = au.originals(P)
    out = {}
    for b, name in (("breakout", "breakout_top10"), ("tsmom_daily", "tsmom_top20"), ("tsmom_tranches", "tsmom_tranches")):
        g, tv, _, _ = au.simulate(P, b, au.cash_left(O[b], alp))
        out[name] = au.net(g, tv, CRYPTO_COST)
    days = to_day(P.days)
    rd, rr = tsmom_regime()
    x = np.zeros(len(days))
    idx = np.searchsorted(rd, days)
    ok = (idx < len(rd)) & (rd[np.minimum(idx, len(rd) - 1)] == days)
    x[ok] = rr[idx[ok]]
    out["tsmom_regime"] = x
    return days, out


def tsmom_regime() -> tuple[np.ndarray, np.ndarray]:
    """lab.paper.tsmom's tsmom_regime (28 d, daily, 40 % vol, BTC 200-day gate) on its 20 coins,
    the coins Alpaca does not list held as cash, 35 bps per unit of turnover."""
    days, close, rv, names = ts.daily_matrix()
    sigma = np.sqrt(ts.rolling_mean(rv, 30, 20))
    history = np.cumsum(np.isfinite(close), axis=0)
    btc = close[:, names.index("BTC")]
    ma200 = ts.rolling_mean(btc[:, None], 200, 200)[:, 0]
    risk_on = np.nan_to_num(btc > ma200, nan=0.0).astype(bool)
    listed = np.array([n in au.ALPACA for n in names], dtype=float)
    return to_day(days), regime_returns(close, sigma, history, risk_on, listed)


def regime_returns(close: np.ndarray, sigma: np.ndarray, history: np.ndarray, risk_on: np.ndarray,
                   listed: np.ndarray, start: int = 200, cost: float = CRYPTO_COST) -> np.ndarray:
    """momentum2.run for the regime book with a cash-left mask: targets at the close of t, held over t+1."""
    T, N = close.shape
    ret = np.full_like(close, np.nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        ret[1:] = close[1:] / close[:-1] - 1
    w = np.zeros(N)
    net = np.zeros(T)
    for t in range(start, T - 1):
        r_next = np.nan_to_num(ret[t + 1])
        tgt = ts.target_weights(close, sigma, history, t, [28], 0.40) * (1.0 if risk_on[t] else 0.0) * listed
        c = float(np.abs(tgt - w).sum()) * cost
        w = tgt
        g = float(np.dot(w, r_next))
        net[t + 1] = g - c
        if 1 + g > 0:
            w = w * (1 + r_next) / (1 + g)
    return net


def equity_series(days: np.ndarray) -> dict[str, np.ndarray]:
    """SPY's total return and the overnight pick's net return on the crypto calendar (0 without a session)."""
    P = on.load_panel()
    N = on.nights(P)
    spy = np.nan_to_num(N.total[:, P.col("SPY")])
    d, pick, name = on.pick_series(P)
    out = {}
    for k, x in (("spy", spy), ("overnight", pick)):
        y = np.zeros(len(days))
        idx = np.searchsorted(days, P.dates)
        ok = (idx < len(days)) & (days[np.minimum(idx, len(days) - 1)] == P.dates)
        y[idx[ok]] = x[ok]
        out[k] = y
    out["overnight_name"] = name
    return out


# ---------------------------------------------------------------------------
# Mixes
# ---------------------------------------------------------------------------

def inv_vol(R: np.ndarray, t: int, win: int = VOL_WIN) -> np.ndarray:
    x = R[max(0, t - win):t]
    if len(x) < 20:
        return np.full(R.shape[1], 1 / R.shape[1])
    v = np.maximum(x.std(0, ddof=1) * math.sqrt(YEAR), VOL_FLOOR)
    w = 1 / v
    return w / w.sum()


def risk_parity(R: np.ndarray, t: int, win: int = COV_WIN, iters: int = 500) -> np.ndarray:
    """Equal risk contributions from the trailing covariance plus a ridge, long only, summing to 1."""
    x = R[max(0, t - win):t]
    K = R.shape[1]
    if len(x) < 20:
        return np.full(K, 1 / K)
    S = np.cov(x, rowvar=False, ddof=1) + RIDGE * np.eye(K)
    w = np.full(K, 1 / K)
    for _ in range(iters):
        rc = w * (S @ w)
        new = w * np.sqrt(rc.mean() / np.maximum(rc, 1e-18))
        new /= new.sum()
        done = np.abs(new - w).max() < 1e-12
        w = new
        if done:
            break
    return w


def crypto_weights(R: np.ndarray, mix: str, days: np.ndarray) -> np.ndarray:
    """(T, K) weights over the crypto books decided from data up to t-1 (EW for the scaled mixes)."""
    T, K = R.shape
    W = np.full((T, K), 1 / K)
    if mix not in ("IV", "RP"):
        return W
    dn = days.astype(np.int64)
    w = np.full(K, 1 / K)
    for t in range(T):
        if t == 0 or dn[t] % REWEIGHT_DAYS == 0:
            w = inv_vol(R, t) if mix == "IV" else risk_parity(R, t)
        W[t] = w
    return W


def realised_vol(x: np.ndarray, win: int = PVOL_WIN) -> np.ndarray:
    """Annualised vol of x over the `win` days before t (NaN before there are win days)."""
    out = np.full(len(x), np.nan)
    c1, c2 = np.r_[0.0, np.cumsum(x)], np.r_[0.0, np.cumsum(x * x)]
    for t in range(win, len(x) + 1):
        if t < len(x):
            s1, s2 = c1[t] - c1[t - win], c2[t] - c2[t - win]
            out[t] = math.sqrt(max(s2 / win - (s1 / win) ** 2, 0) * win / (win - 1) * YEAR)
    return out


def scale(base: np.ndarray, mix: str) -> np.ndarray:
    """Exposure multiplier at t for the scaled mixes, from the unscaled portfolio up to t-1."""
    s = np.ones(len(base))
    if mix in ("VT15", "VT25"):
        tgt = 0.15 if mix == "VT15" else 0.25
        v = realised_vol(base)
        with np.errstate(invalid="ignore", divide="ignore"):
            s = np.where(np.isfinite(v) & (v > 0), np.minimum(1.0, tgt / v), 1.0)
    elif mix == "DDB":
        eq = np.cumprod(1 + base)
        peak = np.maximum.accumulate(np.r_[1.0, eq])[1:]
        dd = 1 - eq / peak
        prev = np.r_[0.0, dd[:-1]]
        s = np.where(prev >= 0.20, 0.25, np.where(prev >= 0.10, 0.5, 1.0))
    return s


def portfolio(R: np.ndarray, W: np.ndarray, costs: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Daily net return of holding weights W[t] over day t (rest in cash), with the drift since the
    previous day traded back at `costs` per unit. Returns (net, turnover)."""
    T, K = R.shape
    net, tov = np.zeros(T), np.zeros(T)
    held = np.zeros(K)
    for t in range(T):
        d = np.abs(W[t] - held)
        tov[t] = d.sum()
        g = float(W[t] @ R[t])
        net[t] = g - float(d @ costs)
        grown = W[t] * (1 + R[t])
        held = grown / (1 + g) if 1 + g > 0 else np.zeros(K)
    return net, tov


def build(R: np.ndarray, days: np.ndarray, mix: str, eq: np.ndarray | None, share: float) -> tuple[np.ndarray, np.ndarray]:
    """(net return, exposure) of one trial."""
    Wc = crypto_weights(R, mix, days)
    if eq is None or share == 0:
        A, W = R, Wc
        costs = np.full(R.shape[1], CRYPTO_COST)
    else:
        A = np.column_stack([R, eq])
        W = np.column_stack([(1 - share) * Wc, np.full(len(R), share)])
        costs = np.r_[np.full(R.shape[1], CRYPTO_COST), EQUITY_COST]
    base = (W * A).sum(1)
    s = scale(base, mix)
    W = W * s[:, None]
    net, _ = portfolio(A, W, costs)
    return net, W.sum(1)


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

def perf(x: np.ndarray) -> dict:
    return on.perf(x, YEAR)


def year_mask(days: np.ndarray, y: int) -> np.ndarray:
    return (days >= np.datetime64(f"{y}-01-01")) & (days < np.datetime64(f"{y + 1}-01-01"))


def a_trial_sharpes() -> list[float]:
    """Study A's 39 out-of-sample Sharpes (per session), from its report, when it is there."""
    try:
        res = json.loads((on.report_dir() / "latest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    s = [r["oos_sharpe"] for r in res.get("rows", [])]
    f = res.get("fill") or {}
    s += [f[k]["sharpe"] for k in ("F1", "F2") if k in f]
    if res.get("pick_row"):
        s.append(res["pick_row"]["oos_sharpe_stress"])
    return [v / math.sqrt(on.YEAR_DAYS) for v in s]


def run(days: np.ndarray, books: dict[str, np.ndarray], equity: dict, seed: int = 20261015) -> dict:
    R = np.column_stack([books[b] for b in BOOKS])
    ins, oos = (days >= IS_START) & (days < SPLIT), days >= SPLIT
    rng = np.random.default_rng(seed)

    book_rows = []
    for b in BOOKS:
        x = books[b]
        po = perf(x[oos])
        book_rows.append({"book": b, "is_sharpe": perf(x[ins])["sharpe"], "oos_sharpe": po["sharpe"],
                          "oos_cagr": po["cagr"], "oos_dd": po["max_dd"],
                          **{f"s{y}": perf(x[oos & year_mask(days, y)])["sharpe"] for y in YEARS_OOS},
                          **{f"dd{y}": perf(x[oos & year_mask(days, y)])["max_dd"] for y in YEARS_OOS}})
    best = max(book_rows, key=lambda r: r["oos_sharpe"])
    xb = books[best["book"]]
    corr = np.corrcoef(R[oos], rowvar=False)

    rows, series = [], {}
    for mix in MIXES:
        for label, key, share in EQUITY:
            eq = equity[key] if key else None
            x, expo = build(R, days, mix, eq, share)
            po = perf(x[oos])
            name = f"{mix} · {label}"
            series[name] = x
            rows.append({"name": name, "mix": mix, "equity": label, "is_sharpe": perf(x[ins])["sharpe"],
                         "oos_sharpe": po["sharpe"], "oos_cagr": po["cagr"], "oos_vol": po["vol"],
                         "oos_dd": po["max_dd"], "oos_expo": float(expo[oos].mean()),
                         **{f"s{y}": perf(x[oos & year_mask(days, y)])["sharpe"] for y in YEARS_OOS},
                         **{f"dd{y}": perf(x[oos & year_mask(days, y)])["max_dd"] for y in YEARS_OOS}})
    assert len(rows) == TRIALS_HERE

    a_s = a_trial_sharpes()
    mine = [on.trial_stats(series[r["name"]][oos])["sr_daily"] for r in rows]
    prior = on.PRIOR_TRIALS + (0 if a_s else A_TRIALS)
    pool_ = on.pool(mine, prior_trials=prior, prior_extra=a_s)
    for r in rows:
        r["deflated_p"] = on.deflated(series[r["name"]][oos], pool_["n_total"], pool_["var"])
        r["beats_best_sharpe"] = r["oos_sharpe"] > best["oos_sharpe"]
        r["beats_best_dd"] = r["oos_dd"] < best["oos_dd"]

    pk = max(rows, key=lambda r: r["is_sharpe"])
    x = series[pk["name"]]
    idx = on.boot_index(int(oos.sum()), rng)
    diff = on.boot_sharpes(x[oos], idx, YEAR) - on.boot_sharpes(xb[oos], idx, YEAR)
    yrs_s = sum(pk[f"s{y}"] > best[f"s{y}"] for y in YEARS_OOS)
    yrs_d = sum(pk[f"dd{y}"] < best[f"dd{y}"] for y in YEARS_OOS)
    gates = {
        "Sharpe higher than the best single book's": pk["oos_sharpe"] > best["oos_sharpe"],
        "drawdown lower than the best single book's": pk["oos_dd"] < best["oos_dd"],
        "higher Sharpe in 2 of 3 years and lower drawdown in 2 of 3 years": yrs_s >= 2 and yrs_d >= 2,
        "bootstrap 5 % of the Sharpe difference above 0": float(np.quantile(diff, 0.05)) > 0,
    }
    full = [r for r in rows if r["beats_best_sharpe"] and r["beats_best_dd"]]
    crypto_only = [r for r in rows if r["equity"] == "none"]
    with_equity = [r for r in rows if r["equity"] != "none"]
    off = corr[~np.eye(len(BOOKS), dtype=bool)]
    summary = {"corr_min": float(off.min()), "corr_max": float(off.max()),
               "crypto_only_best_oos": max(r["oos_sharpe"] for r in crypto_only),
               "crypto_only_beat_best": sum(r["beats_best_sharpe"] for r in crypto_only),
               "with_equity_beat_best": sum(r["beats_best_sharpe"] for r in with_equity),
               "with_equity_beat_both": sum(r["beats_best_sharpe"] and r["beats_best_dd"] for r in with_equity),
               "with_equity_median_oos": float(np.median([r["oos_sharpe"] for r in with_equity])),
               "with_equity_median_dd": float(np.median([r["oos_dd"] for r in with_equity]))}
    return {
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "window": {"is": [str(days[ins][0]), str(days[ins][-1])], "oos": [str(days[oos][0]), str(days[oos][-1])]},
        "books": book_rows, "best_book": best["book"],
        "corr": {BOOKS[i]: {BOOKS[j]: float(corr[i, j]) for j in range(len(BOOKS))} for i in range(len(BOOKS))},
        "equity_oos": {"SPY buy and hold": perf(equity["spy"][oos]), equity["overnight_name"]: perf(equity["overnight"][oos])},
        "equity_corr": {k: float(np.corrcoef(equity[k][oos], R[oos].mean(1))[0, 1]) for k in ("spy", "overnight")},
        "overnight_pick": equity["overnight_name"],
        "rows": rows, "pick": pk["name"], "pick_row": pk, "years_sharpe": yrs_s, "years_dd": yrs_d,
        "bootstrap": {"diff_p05": float(np.quantile(diff, 0.05)), "diff_p95": float(np.quantile(diff, 0.95)),
                      "share_above_0": float((diff > 0).mean())},
        "both_beaten_by": [r["name"] for r in full], "summary": summary, "pool": pool_, "a_trials_from_report": len(a_s),
        "gates": gates, "passes": all(gates.values()),
    }


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def markdown(res: dict) -> str:
    from ..report import table
    pct = on.pct
    pk, pool_ = res["pick_row"], res["pool"]
    best = next(b for b in res["books"] if b["book"] == res["best_book"])
    failed = [g for g, ok in res["gates"].items() if not ok]
    sr0 = pool_["sr0_daily"] * math.sqrt(YEAR)
    verdict = ("**Verdict: the pick passes the pre-registered rule.**" if res["passes"] else
               f"**Verdict: fails ({len(failed)} of 4 rules), no portfolio autopilot is proposed.**")
    b = res["bootstrap"]
    lines = [
        f"## Results (generated {res['generated'][:10]}, in sample {res['window']['is'][0]} to "
        f"{res['window']['is'][1]}, out of sample {res['window']['oos'][0]} to {res['window']['oos'][1]})", "",
        verdict + f" The in-sample pick is {res['pick']} (in-sample Sharpe {pk['is_sharpe']:.2f}). Out of sample it "
        f"makes Sharpe {pk['oos_sharpe']:.2f}, {pct(pk['oos_cagr'])} a year, drawdown {pct(pk['oos_dd'])}, against "
        f"the best single book, {best['book']}, at {best['oos_sharpe']:.2f}, {pct(best['oos_cagr'])}, drawdown "
        f"{pct(best['oos_dd'])}. Higher Sharpe in {res['years_sharpe']} of 3 years, lower drawdown in "
        f"{res['years_dd']} of 3; the bootstrap's 90 % band of the Sharpe difference is {b['diff_p05']:.2f} to "
        f"{b['diff_p95']:.2f} ({b['share_above_0']:.0%} of draws above 0). Deflated p {pk['deflated_p']:.2f} over "
        f"{pool_['n_total']} trials (noise bar about {sr0:.2f} on 365 days).", ""]
    if failed:
        lines += ["Failed: " + "; ".join(failed) + ".", ""]
    n_both = len(res["both_beaten_by"])
    lines += [f"{n_both} of 30 trials beat the best book on both Sharpe and drawdown out of sample"
              + (f" ({', '.join(res['both_beaten_by'])}), none of them the in-sample pick." if n_both and
                 res["pick"] not in res["both_beaten_by"] else "." if not n_both else
                 f" ({', '.join(res['both_beaten_by'])})."), ""]
    s = res["summary"]
    lines += [f"Among the crypto books alone, {s['crypto_only_beat_best']} of 6 mixes beat the best book's Sharpe (the "
              f"best of them makes {s['crypto_only_best_oos']:.2f}): the four books are {s['corr_min']:.2f} to "
              f"{s['corr_max']:.2f} correlated. "
              f"With an equity sleeve {s['with_equity_beat_best']} of 24 beat it and {s['with_equity_beat_both']} "
              f"beat it on drawdown too (median Sharpe {s['with_equity_median_oos']:.2f}, median drawdown "
              f"{pct(s['with_equity_median_dd'])}). These are after-the-fact counts, not the registered verdict.", ""]

    lines += ["### The books (35 bps, non-Alpaca coins in cash)", ""]
    br = [{"book": r["book"], "IS Sharpe": r["is_sharpe"], "OOS Sharpe": r["oos_sharpe"], "OOS CAGR": pct(r["oos_cagr"]),
           "OOS DD": pct(r["oos_dd"]), **{str(y): r[f"s{y}"] for y in YEARS_OOS}} for r in res["books"]]
    lines += [table(br, list(br[0])), ""]
    cr = [{"": k, **v} for k, v in res["corr"].items()]
    lines += ["Correlation of the daily returns out of sample:", "", table(cr, list(cr[0])), ""]
    eo = res["equity_oos"]
    lines += ["Equity sleeves out of sample on the crypto calendar (zero on days without a session): "
              + "; ".join(f"{k} Sharpe {v['sharpe']:.2f}, drawdown {pct(v['max_dd'])}" for k, v in eo.items())
              + f". Correlation with the equal-weight crypto books: SPY {res['equity_corr']['spy']:.2f}, "
              f"overnight {res['equity_corr']['overnight']:.2f}.", ""]

    lines += ["### The 30 trials", "", "Sharpe over 365 days, net of every cost. Sleeve weight: the share of the "
              "portfolio given to the books (below 100 % only when the vol target or the brake scales it down); "
              "the books themselves sit partly in cash.", ""]
    tr = [{"trial": r["name"], "IS Sharpe": r["is_sharpe"], "OOS Sharpe": r["oos_sharpe"], "OOS CAGR": pct(r["oos_cagr"]),
           "OOS DD": pct(r["oos_dd"]), "sleeve weight": pct(r["oos_expo"]),
           **{str(y): r[f"s{y}"] for y in YEARS_OOS}, "deflated p": r["deflated_p"]} for r in res["rows"]]
    lines += [table(tr, list(tr[0])), ""]

    lines += ["### The pick against the best book, per year", ""]
    yr = [{"year": y, "pick Sharpe": pk[f"s{y}"], f"{best['book']} Sharpe": best[f"s{y}"],
           "pick DD": pct(pk[f"dd{y}"]), f"{best['book']} DD": pct(best[f"dd{y}"])} for y in YEARS_OOS]
    lines += [table(yr, list(yr[0])), ""]
    lines += ["### Rules", ""] + [f"- {'pass' if ok else 'FAIL'}: {g}" for g, ok in res["gates"].items()] + [""]

    lines += ["### How an autopilot would run it", ""]
    if res["passes"]:
        lines += ["One autopilot with the four lab books as explicit sleeves (weights fixed, never re-picked), their "
                  "targets netted per coin, plus the equity sleeve as a portfolio autopilot's US-share lab book. "
                  "Fixed weights are what the engine supports today; a mix that changes its weights or its "
                  "exposure over time needs one combined lab signal (the lab computes the netted targets and "
                  "writes them as one book) or a daily `autopilot_update` of the weights.", ""]
    else:
        lines += ["Nothing is proposed. For the record: equal weights over the four books are possible today (one "
                  "autopilot, the four lab books as explicit sleeves at 25 % each, netted per coin; a SPY sleeve "
                  "would need a portfolio autopilot and a US-share lab book). Inverse vol, risk parity, the vol "
                  "target and the brake change weights or exposure over time, which the engine's fixed sleeve "
                  "weights cannot do; they would need one combined lab signal.", ""]

    lines += ["### Deflation pool", "",
              f"{pool_['prior_trials']} earlier trials at the variance of the published bar, study A's "
              f"{res['a_trials_from_report']} out-of-sample Sharpes from its report, and these 30 (out of sample, "
              f"clipped at an annual +-3): {pool_['n_total']} trials.", ""]
    return "\n".join(lines)


def write(res: dict) -> str:
    from .. import report
    path = fc.RESULTS_DIR / f"{NAME}.md"
    try:
        head = path.read_text(encoding="utf-8").split(MARKER)[0]
    except OSError:
        head = f"# {NAME}\n\n"
    body = markdown(res)
    md = head + MARKER + "\n\n" + body
    path.write_text(md, encoding="utf-8")
    report.write(NAME, body, res)
    return md


def main() -> int:
    days, books = crypto_books()
    try:
        equity = equity_series(days)
    except on.DataUnavailable as e:
        print(f"{NAME}: no equity data: {e}", file=sys.stderr)
        return 2
    write(run(days, books, equity))
    return 0


if __name__ == "__main__":
    sys.exit(main())
