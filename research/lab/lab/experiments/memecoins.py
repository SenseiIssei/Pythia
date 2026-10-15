"""W7: memecoin strategies on the six memecoins Alpaca lists.

    python -m lab.experiments.memecoins

Pre-registered in results/memecoins.md (the part above the marker was committed
before this file ran). Daily long-only rules on DOGE SHIB PEPE BONK WIF TRUMP
(universe A) with a sleeve sized for 6 coins at 40 % vol: Donchian breakout,
time-series momentum, rotation, attention (volume surges and Binance trade
count jumps) and two hype filters; every one also on a survivorship-free twin
(M: the 6 most liquid of 24 Binance memecoins each day, crashed ones
included), each family pick also filled one day late. Judged out of sample
from 2024 at 35 bps (Alpaca taker plus slippage), deflated over every trial
counted so far.

The panel is built from Binance's daily klines (lab/klines_daily.py) into the
sweep's Panel shape, so the books use the sweep's own breakout rule and the
same simulator as C16. Writes results/memecoins.md and
<agent-strategies>/reports/memecoins.json.
"""

from __future__ import annotations

import json
import math
import warnings
from datetime import datetime, timezone

import numpy as np
import polars as pl
from scipy import stats

from .. import klines_daily
from . import alpaca_universe as au
from . import fam_breakout, fam_common as fc

NAME = "memecoins"
MARKER = "<!-- generated below by lab.experiments.memecoins; edit above this line only -->"
ALPACA_MEMES = ("DOGE", "SHIB", "PEPE", "BONK", "WIF", "TRUMP")
TWIN_MEMES = ALPACA_MEMES + ("FLOKI", "BOME", "MEME", "PEOPLE", "1000SATS", "TURBO", "NEIRO", "1MBABYDOGE",
                             "PNUT", "ACT", "DOGS", "PENGU", "BROCCOLI714", "MUBARAK", "TST", "1000CAT",
                             "BANANAS31", "PUMP")
SYMBOLS = ("BTCUSDT",) + tuple(f"{b}USDT" for b in TWIN_MEMES)
SLOTS = 6
COIN_VOL = 0.40
SURGE_DAYS = 28
COSTS = {"maker 15bps": 0.0015, "taker 35bps": 0.0035, "stress 70bps": 0.0070}
BASE = "taker 35bps"
YEARS = (2021, 2022, 2023, 2024, 2025, 2026)
YEARS_OOS = (2024, 2025, 2026)
PRIOR_TRIALS, PRIOR_SR0 = 377, 2.43
HERE_TRIALS = 50
RISK_BUDGET = 0.10
FAMILIES = ("F1 breakout", "F2 trend", "F3 rotation", "F4 attention, volume", "F5 attention, trades",
            "F6 hype filters")
# The main books out of sample from 2024 at 35 bps, cash-left on Alpaca (results/alpaca_universe.md).
MAIN_BOOKS = [("breakout_top10 (cash-left)", 1.17, 0.15), ("tsmom_top20 (cash-left)", 0.54, 0.09),
              ("tsmom_tranches (cash-left)", 0.65, 0.09)]


# ---------------------------------------------------------------------------
# The panel
# ---------------------------------------------------------------------------

def load_frames(symbols=SYMBOLS) -> dict[str, pl.DataFrame]:
    out = {}
    for s in symbols:
        df = klines_daily.fetch(s)
        if df.height:
            out[s] = df
        print(f"  {s}: {df.height} days", flush=True)
    return out


def build_panel(frames: dict[str, pl.DataFrame]) -> fc.Panel:
    """fc.Panel from daily klines. A day is traded when its bar has quote volume;
    sigma is the RMS of the last 30 daily log returns (at least 20)."""
    names = sorted(frames)
    lo = min(int(f["day"].min()) for f in frames.values())
    hi = max(int(f["day"].max()) for f in frames.values())
    days = np.arange(lo, hi + fc.DAY_US, fc.DAY_US, dtype=np.int64)
    T, N = len(days), len(names)

    def mat(c: str) -> np.ndarray:
        m = np.full((T, N), np.nan)
        for j, s in enumerate(names):
            f = frames[s]
            rows = ((f["day"].to_numpy() - lo) // fc.DAY_US).astype(int)
            m[rows, j] = f[c].to_numpy().astype(float)
        return m

    close, high, low, qv, n = mat("close"), mat("high"), mat("low"), mat("qv"), mat("n")
    traded = np.isfinite(close) & (np.nan_to_num(qv) > 0)
    close = np.where(traded, close, np.nan)
    idx = np.arange(T)[:, None]
    first = np.where(traded.any(0), np.argmax(traded, 0), T)
    last = np.where(traded.any(0), T - 1 - np.argmax(traded[::-1], 0), -1)
    alive = (idx >= first[None, :]) & (idx <= last[None, :])
    fidx = np.maximum.accumulate(np.where(traded, idx, 0), axis=0)
    px = np.where(alive, close[fidx, np.arange(N)[None, :]], np.nan)
    ret = np.full((T, N), np.nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        ret[1:] = np.where(alive[1:] & alive[:-1], px[1:] / px[:-1] - 1, np.nan)
        rv = np.log1p(ret) ** 2
    age = np.where(alive, idx - first[None, :], -1)
    adv28 = np.where(alive, fc.rolling(np.where(alive, np.nan_to_num(qv), np.nan), 28, 20), np.nan)
    sigma = np.sqrt(fc.rolling(rv, 30, 20))
    eligible = alive & traded & (age >= fc.MIN_AGE_D) & (np.nan_to_num(adv28) >= fc.MIN_ADV_USD)
    btc = names.index("BTCUSDT")
    bpx = px[:, btc]
    ma200 = fc.rolling(bpx[:, None], 200, 200)[:, 0]
    btc_on = np.nan_to_num(bpx > ma200, nan=0.0).astype(bool)
    return fc.Panel(days, names, [fc.base_of(x) for x in names], close, px, high, low, ret, alive, traded, age,
                    adv28, sigma, eligible, np.zeros((T, N), dtype=bool), np.zeros((T, N)), btc_on, btc,
                    extra={"qv": np.where(traded, qv, np.nan), "n": np.where(traded, n, np.nan)})


def member(P: fc.Panel, bases) -> np.ndarray:
    return np.array([b in bases for b in P.bases])


def universes(P: fc.Panel) -> dict[str, np.ndarray]:
    """A: every eligible Alpaca memecoin. M: the 6 most liquid eligible twin members each day."""
    return {"A": P.eligible & member(P, ALPACA_MEMES)[None, :],
            "M": au.top_within(P, member(P, TWIN_MEMES), SLOTS)}


# ---------------------------------------------------------------------------
# Signals and weights
# ---------------------------------------------------------------------------

def surge_ratio(x: np.ndarray, days: int = SURGE_DAYS) -> np.ndarray:
    """x[t] over the median of x over the previous `days` rows (at least days // 2 of them)."""
    T, N = x.shape
    pad = np.vstack([np.full((days, N), np.nan), x])
    win = np.lib.stride_tricks.sliding_window_view(pad, days, axis=0)[:T]   # rows t-days .. t-1
    ok = np.isfinite(win).sum(-1) >= days // 2
    with np.errstate(invalid="ignore", divide="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        med = np.nanmedian(win, axis=-1)
        out = np.where(ok & (med > 0), x / med, np.nan)
    return out


def size(P: fc.Panel, slots: int) -> np.ndarray:
    """Weight of a held coin: COIN_VOL of annual vol over the slots, at most 1 / slots."""
    with np.errstate(invalid="ignore", divide="ignore"):
        s = np.minimum(COIN_VOL / (P.sigma * np.sqrt(365)) / slots, 1.0 / slots)
    return np.nan_to_num(s)


def trailing_return(P: fc.Panel, days: int) -> np.ndarray:
    past = np.full_like(P.px, np.nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        past[days:] = P.px[days:] / P.px[:-days] - 1
    return past


def gate(W: np.ndarray, P: fc.Panel) -> np.ndarray:
    return W * P.btc_on[:, None]


def breakout(P: fc.Panel, uni: np.ndarray, n: int, gated: bool, allowed: np.ndarray | None = None) -> np.ndarray:
    cols = np.flatnonzero(uni.any(0))
    return fam_breakout.breakout_weights(P, cols, uni if allowed is None else allowed, n, SLOTS, regime=gated)


def trend(P: fc.Panel, uni: np.ndarray, lookback: int, gated: bool, skip: np.ndarray | None = None) -> np.ndarray:
    held = uni & (np.nan_to_num(trailing_return(P, lookback), nan=-1) > 0)
    if skip is not None:
        held &= ~skip
    W = np.where(held, size(P, SLOTS), 0.0)
    return gate(W, P) if gated else W


def rotation(P: fc.Panel, uni: np.ndarray, k: int, lookback: int = 28) -> np.ndarray:
    r = np.where(uni, trailing_return(P, lookback), np.nan)
    score = np.where(np.isfinite(r), r, -np.inf)
    rank = np.argsort(np.argsort(-score, axis=1, kind="stable"), axis=1, kind="stable")
    held = np.isfinite(r) & (rank < k) & (np.nan_to_num(r, nan=-1) > 0)
    return gate(np.where(held, size(P, k), 0.0), P)


def hold_after(P: fc.Panel, signal: np.ndarray, h: int) -> np.ndarray:
    """Enter at the close of a signal day at the vol size, hold h closes from the LAST
    signal (a new signal extends it), let it drift in between (NaN), exit to 0."""
    sz = size(P, SLOTS)
    W = np.full(signal.shape, np.nan)
    left = np.zeros(signal.shape[1], dtype=int)
    for t in range(signal.shape[0]):
        on = left > 0
        sig = signal[t] & (sz[t] > 0)
        enter = sig & ~on
        W[t, enter] = sz[t, enter]
        left = np.where(sig, h, left - 1)
        ex = on & (left <= 0)
        W[t, ex] = 0.0
        dead = on & ~P.alive[t]
        W[t, dead] = 0.0
        left = np.where(dead, 0, np.maximum(left, 0))
    W[0] = np.where(np.isnan(W[0]), 0.0, W[0])
    return W


def attention(P: fc.Panel, uni: np.ndarray, field: str, s: float, h: int) -> np.ndarray:
    ratio = surge_ratio(P.extra[field])
    with np.errstate(invalid="ignore"):
        sig = uni & (np.nan_to_num(ratio) >= s) & (np.nan_to_num(P.ret) > 0)
    return hold_after(P, sig, h)


def recent_surge(P: fc.Panel, s: float = 3.0, days: int = 3) -> np.ndarray:
    hot = np.nan_to_num(surge_ratio(P.extra["qv"])) >= s
    out = hot.copy()
    for k in range(1, days):
        out[k:] |= hot[:-k]
    return out


def variants(P: fc.Panel, uni: np.ndarray) -> list[tuple[str, str, np.ndarray]]:
    """(family, name, W) in the pre-registered order: 22 per universe."""
    out = []
    for n in (20, 55):
        for g in (False, True):
            out.append(("F1 breakout", f"Donchian {n}/{n // 2}" + (" · BTC gate" if g else ""), breakout(P, uni, n, g)))
    for lb in (14, 28, 56):
        for g in (False, True):
            out.append(("F2 trend", f"tsmom {lb}d" + (" · BTC gate" if g else ""), trend(P, uni, lb, g)))
    for k in (1, 2):
        out.append(("F3 rotation", f"top {k} by 28d return · BTC gate", rotation(P, uni, k)))
    for fam, field, what in (("F4 attention, volume", "qv", "volume"), ("F5 attention, trades", "n", "trades")):
        for s in (2, 3):
            for h in (3, 7):
                out.append((fam, f"{what} surge x{s} · up day · hold {h}d", attention(P, uni, field, s, h)))
    out.append(("F6 hype filters", "tsmom 28d · BTC gate · skip after a x3 volume surge",
                trend(P, uni, 28, True, skip=recent_surge(P))))
    surge = np.nan_to_num(surge_ratio(P.extra["qv"])) >= 2
    out.append(("F6 hype filters", "Donchian 20/10 · entry on a x2 volume surge",
                breakout(P, uni, 20, False, allowed=uni & surge)))
    return out


# ---------------------------------------------------------------------------
# Measuring
# ---------------------------------------------------------------------------

def prior_var() -> float:
    g = 0.5772156649
    z = (1 - g) * stats.norm.ppf(1 - 1 / PRIOR_TRIALS) + g * stats.norm.ppf(1 - 1 / (PRIOR_TRIALS * math.e))
    return (PRIOR_SR0 / math.sqrt(365) / z) ** 2


def pooled_var(mine: list[float]) -> tuple[float, dict]:
    v1, n1 = prior_var(), PRIOR_TRIALS
    x = np.clip(np.array(mine), -fc.SR_CLIP, fc.SR_CLIP) / math.sqrt(365)
    n2, v2 = len(x), float(np.var(x))
    n = n1 + n2
    v = (n1 * v1 + n2 * v2) / n
    return v, {"prior_trials": n1, "prior_var": v1, "mine": n2, "mine_var": v2, "pooled_var": v, "n_total": n,
               "sr0_annual": fc._sr0(v, n) * math.sqrt(365)}


def years_of(P: fc.Panel) -> np.ndarray:
    return au.years_of(P)


def months_of(P: fc.Panel) -> np.ndarray:
    return np.array([str(np.datetime64(int(d), "us").astype("datetime64[M]")) for d in P.days])


def worst_month(r: np.ndarray, months: np.ndarray) -> float:
    if not len(r):
        return 0.0
    out = []
    for m in np.unique(months):
        x = r[months == m]
        out.append(float(np.prod(1 + x) - 1))
    return float(min(out))


def longest_underwater(r: np.ndarray) -> int:
    """Days from a peak to the first day back above it (or the end), longest."""
    eq = np.cumprod(1 + r)
    peak = np.maximum.accumulate(eq)
    best = cur = 0
    for under in eq < peak - 1e-12:
        cur = cur + 1 if under else 0
        best = max(best, cur)
    return int(best)


def pnl_by_coin(P: fc.Panel, held: np.ndarray, mask: np.ndarray) -> list[dict]:
    """Gross P&L share by coin over the masked return days (held at t earns t+1)."""
    contrib = np.zeros_like(held)
    contrib[1:] = held[:-1] * np.nan_to_num(P.ret[1:])
    c = contrib[mask].sum(0)
    tot = np.abs(c).sum()
    order = np.argsort(-np.abs(c))
    return [{"coin": P.bases[j], "pnl": float(c[j]), "share_abs": float(abs(c[j]) / tot) if tot > 0 else 0.0}
            for j in order if c[j] != 0][:8]


def describe(P: fc.Panel, universe: str, family: str, name: str, run: tuple, bench_btc: np.ndarray) -> dict:
    gross, tov, ex, held = run
    ins, oos = fc.masks(P)
    yr, mo = years_of(P), months_of(P)
    row: dict = {"universe": universe, "family": family, "variant": name}
    for k, c in COSTS.items():
        n = au.net(gross, tov, c)
        row[f"is_{k}"] = fc.perf(n[ins])["sharpe"]
        row[f"oos_{k}"] = fc.perf(n[oos])["sharpe"]
    n35 = au.net(gross, tov, COSTS[BASE])
    po = fc.perf(n35[oos])
    row["cagr_35"], row["dd_35"], row["vol_35"] = po["cagr"], po["max_dd"], po["vol"]
    row["worst_month"] = worst_month(n35[oos], mo[oos])
    row["underwater_days"] = longest_underwater(n35[oos])
    row["expo"] = float(ex[oos].mean())
    row["turnover_yr"] = float(tov[oos].sum() / (oos.sum() / 365))
    row.update(au.activity(P, held, oos))
    x, b = n35[oos], bench_btc[oos]
    row["corr_btc"] = float(np.corrcoef(x, b)[0, 1]) if x.std() > 0 and b.std() > 0 else 0.0
    for y in YEARS:
        m = (P.days >= fc.IS_START) & (yr == y)
        row[f"y{y}"] = fc.perf(n35[m])["sharpe"]
    return row


def benchmark_rows(P: fc.Panel, unis: dict[str, np.ndarray]) -> tuple[list[dict], dict[str, np.ndarray]]:
    ins, oos = fc.masks(P)
    yr, mo = years_of(P), months_of(P)
    btc = np.nan_to_num(P.ret[:, P.btc])
    series = {"BTC buy and hold": btc}
    Wg = np.zeros((P.T, P.N))
    Wg[:, P.btc] = P.btc_on.astype(float)
    g, tv, _, _ = au.sim_daily(P, Wg)
    series["BTC 200-day gate (35 bps)"] = au.net(g, tv, COSTS[BASE])
    j = P.col("DOGEUSDT")
    series["DOGE buy and hold"] = np.nan_to_num(P.ret[:, j])
    for u, label in (("A", "A memecoins, equal weight"), ("M", "M twin universe, equal weight")):
        ew = np.zeros(P.T)
        for t in range(1, P.T):
            m = unis[u][t - 1] & np.isfinite(P.ret[t])
            ew[t] = float(P.ret[t][m].mean()) if m.any() else 0.0
        series[label] = ew
    rows = []
    for name, r in series.items():
        po = fc.perf(r[oos])
        row = {"universe": "-", "family": "benchmark", "variant": name, "is_taker 35bps": fc.perf(r[ins])["sharpe"],
               "oos_maker 15bps": po["sharpe"], "oos_taker 35bps": po["sharpe"], "oos_stress 70bps": po["sharpe"],
               "cagr_35": po["cagr"], "dd_35": po["max_dd"], "vol_35": po["vol"],
               "worst_month": worst_month(r[oos], mo[oos]), "underwater_days": longest_underwater(r[oos]),
               "corr_btc": float(np.corrcoef(r[oos], btc[oos])[0, 1]) if r[oos].std() > 0 else 0.0}
        for y in YEARS:
            m = (P.days >= fc.IS_START) & (yr == y)
            row[f"y{y}"] = fc.perf(r[m])["sharpe"]
        rows.append(row)
    return rows, series


def availability(P: fc.Panel) -> dict:
    out = {}
    for b in TWIN_MEMES:
        s = f"{b}USDT"
        if s not in P.names:
            out[b] = {"first_bar": None, "first_eligible": None, "last_bar": None, "drawdown_from_peak": None}
            continue
        j = P.col(s)
        tr = np.flatnonzero(P.traded[:, j])
        e = np.flatnonzero(P.eligible[:, j])
        px = P.px[:, j][np.isfinite(P.px[:, j])]
        day = lambda t: str(np.datetime64(int(P.days[t]), "us").astype("datetime64[D]"))  # noqa: E731
        out[b] = {"first_bar": day(tr[0]), "first_eligible": day(e[0]) if len(e) else None,
                  "last_bar": day(tr[-1]), "drawdown_from_peak": float(1 - px[-1] / px.max()) if len(px) else None}
    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    P = build_panel(load_frames())
    ins, oos = fc.masks(P)
    unis = universes(P)
    bench, bseries = benchmark_rows(P, unis)
    btc = bseries["BTC buy and hold"]
    rng = np.random.default_rng(20261015)
    rows, runs = [], {}

    def add(universe: str, family: str, name: str, W: np.ndarray) -> dict:
        run = au.sim_daily(P, W)
        r = describe(P, universe, family, name, run, btc)
        rows.append(r)
        runs[(universe, name)] = (run, W)
        print(f"  {universe} {family:22s} {name:55s} IS {r['is_taker 35bps']:5.2f} OOS {r['oos_taker 35bps']:5.2f}",
              flush=True)
        return r

    for u in ("A", "M"):
        for fam, name, W in variants(P, unis[u]):
            add(u, fam, name, W)

    picks = {}
    for fam in FAMILIES:
        cand = [r for r in rows if r["universe"] == "A" and r["family"] == fam]
        pk = max(cand, key=lambda r: r["is_taker 35bps"])
        twin = next(r for r in rows if r["universe"] == "M" and r["variant"] == pk["variant"])
        late = add("L", fam, pk["variant"] + " · one day late", au.one_day_late(runs[("A", pk["variant"])][1]))
        picks[fam] = {"pick": pk, "twin": twin, "late": late}
    overall = max(FAMILIES, key=lambda f: picks[f]["pick"]["is_taker 35bps"])

    assert len(rows) == HERE_TRIALS, len(rows)
    var, pool = pooled_var([r["oos_taker 35bps"] for r in rows])
    for r in rows:
        (g, tv, _, _), _ = runs[(r["universe"], r["variant"])]
        x = au.net(g, tv, COSTS[BASE])[oos]
        r["deflated_p"] = au.deflated(x, pool["n_total"], var)
        r["boot35_p05"], r["boot35_p95"] = au.boot_band(x, rng)
    for b in bench:
        x = bseries[b["variant"]][oos]
        b["boot35_p05"], b["boot35_p95"] = au.boot_band(x, rng)

    btc_sr = next(b for b in bench if b["variant"] == "BTC buy and hold")["oos_taker 35bps"]
    basket_dd = next(b for b in bench if b["variant"].startswith("A memecoins"))["dd_35"]
    verdicts = []
    for fam in FAMILIES:
        pk, tw, lt = picks[fam]["pick"], picks[fam]["twin"], picks[fam]["late"]
        years_pos = sum(pk[f"y{y}"] > 0 for y in YEARS_OOS)
        why = []
        if pk["oos_taker 35bps"] <= 0 or pk["oos_stress 70bps"] <= 0:
            why.append("Sharpe not above 0 at 35 and 70 bps")
        if years_pos < 2:
            why.append(f"positive in {years_pos} of 3 years")
        if pk["oos_taker 35bps"] <= btc_sr:
            why.append(f"Sharpe {pk['oos_taker 35bps']:.2f} not above BTC's {btc_sr:.2f}")
        if pk["dd_35"] >= 0.5 or pk["dd_35"] >= basket_dd:
            why.append(f"drawdown {pk['dd_35'] * 100:.0f} % (basket {basket_dd * 100:.0f} %)")
        if pk["deflated_p"] <= 0.95:
            why.append(f"deflated p {pk['deflated_p']:.2f} <= 0.95")
        if tw["oos_taker 35bps"] <= 0 or lt["oos_taker 35bps"] <= 0:
            why.append(f"twin {tw['oos_taker 35bps']:.2f} / late {lt['oos_taker 35bps']:.2f}")
        (g, tv, _, held), _ = runs[("A", pk["variant"])]
        verdicts.append({
            "family": fam, "pick": pk["variant"], "overall": fam == overall, "pick_is_35": pk["is_taker 35bps"],
            "pick_oos_15": pk["oos_maker 15bps"], "pick_oos_35": pk["oos_taker 35bps"],
            "pick_oos_70": pk["oos_stress 70bps"], "pick_dd": pk["dd_35"], "pick_deflated_p": pk["deflated_p"],
            "twin_oos_35": tw["oos_taker 35bps"], "late_oos_35": lt["oos_taker 35bps"], "years_pos": years_pos,
            "account_dd_at_10pct": pk["dd_35"] * RISK_BUDGET, "passes": not why, "why": "; ".join(why) or "passes",
            "pnl_by_coin": pnl_by_coin(P, held, oos)})

    res = {"panel_end": str(np.datetime64(int(P.days[-1]), "us").astype("datetime64[D]")),
           "oos_days": int(oos.sum()), "is_days": int(ins.sum()), "rows": rows, "benchmarks": bench,
           "verdicts": verdicts, "overall": overall, "pool": pool, "availability": availability(P),
           "btc_sr": btc_sr, "basket_dd": basket_dd,
           "a_count_oos": [int(unis["A"][oos].sum(1).min()), int(unis["A"][oos].sum(1).max())],
           "a_count_is": [int(unis["A"][ins].sum(1).min()), int(unis["A"][ins].sum(1).max())]}
    write(res)


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def pct(v) -> str:
    return "n/a" if v is None else f"{v * 100:.0f} %"


def write(res: dict) -> None:
    path = fc.RESULTS_DIR / f"{NAME}.md"
    try:
        head = path.read_text(encoding="utf-8").split(MARKER)[0]
    except OSError:
        head = f"# {NAME}\n\n"
    rows, v, pool, av = res["rows"], res["verdicts"], res["pool"], res["availability"]
    ov = next(x for x in v if x["overall"])
    main_cols = ["universe", "family", "variant", "is_taker 35bps", "oos_maker 15bps", "oos_taker 35bps",
                 "oos_stress 70bps", "cagr_35", "dd_35", "worst_month", "underwater_days", "vol_35", "expo",
                 "turnover_yr", "trades_month", "corr_btc", "deflated_p", "boot35_p05", "boot35_p95"]
    year_cols = ["universe", "family", "variant"] + [f"y{y}" for y in YEARS]
    ver_cols = ["family", "pick", "pick_is_35", "pick_oos_15", "pick_oos_35", "pick_oos_70", "pick_dd",
                "account_dd_at_10pct", "pick_deflated_p", "twin_oos_35", "late_oos_35", "years_pos", "passes"]
    md = [head, MARKER, "\n\n",
          f"## Results (generated {datetime.now(timezone.utc):%Y-%m-%d}, data to {res['panel_end']})\n\n",
          f"**Verdict: {'the pick passes' if ov['passes'] else 'nothing passes, no paper book'}.** Overall pick "
          f"({ov['family']}): {ov['pick']}, out of sample Sharpe {ov['pick_oos_35']:.2f} at 35 bps "
          f"(15 bps {ov['pick_oos_15']:.2f}, 70 bps {ov['pick_oos_70']:.2f}), drawdown {pct(ov['pick_dd'])}; "
          f"{ov['why']}. BTC buy and hold over the same days: Sharpe {res['btc_sr']:.2f}. Deflation pool "
          f"{pool['n_total']} trials (prior {pool['prior_trials']}, here {pool['mine']}); the best noise trial is "
          f"expected at an annual Sharpe of about {pool['sr0_annual']:.2f}. Out of sample {res['oos_days']} days, "
          f"in sample {res['is_days']} days with {res['a_count_is'][0]} to {res['a_count_is'][1]} eligible "
          f"Alpaca memecoins ({res['a_count_oos'][0]} to {res['a_count_oos'][1]} out of sample).\n\n",
          "### Family picks (A, best in-sample Sharpe at 35 bps)\n\n",
          "`account_dd_at_10pct` is what the pick's worst drawdown costs an account holding 10 % in it. "
          "`years_pos` counts 2024, 2025, 2026 with a positive Sharpe.\n\n",
          fc.table(v, ver_cols), "\n"]
    for x in v:
        md.append(f"- {x['family']}: {x['why']}. P&L by coin out of sample: " + ", ".join(
            f"{c['coin']} {c['pnl'] * 100:+.0f} %" for c in x["pnl_by_coin"]) + "\n")
    md += ["\n### Against BTC and the main books (out of sample from 2024, 35 bps)\n\n",
           "| book | Sharpe | max drawdown |\n|---|---|---|\n"]
    for b in res["benchmarks"]:
        md.append(f"| {b['variant']} | {b['oos_taker 35bps']:.2f} | {pct(b['dd_35'])} |\n")
    for name, sr, dd in MAIN_BOOKS:
        md.append(f"| {name}, from C16 (data to 2026-09-30) | {sr:.2f} | {pct(dd)} |\n")
    md.append(f"| memecoin pick: {ov['pick']} | {ov['pick_oos_35']:.2f} | {pct(ov['pick_dd'])} |\n")
    md += ["\n### Every book (in sample 2020-08 to 2023, out of sample from 2024)\n\n",
           "A on the six Alpaca memecoins, M its survivorship-free twin (the 6 most liquid of 24 Binance "
           "memecoins each day), L a family pick filled one day late. Sharpe at 15 / 35 / 70 bps; CAGR, "
           "drawdown, worst calendar month, longest time under water (days), vol and the bootstrap band at "
           "35 bps; benchmarks without costs except the BTC gate.\n\n",
           fc.table(res["benchmarks"] + rows, main_cols), "\n",
           "### Per year (Sharpe at 35 bps)\n\n", fc.table(res["benchmarks"] + rows, year_cols), "\n",
           "### The coins\n\n| coin | first bar | first eligible | last bar | down from its peak |\n|---|---|---|---|---|\n"]
    for b, a in av.items():
        md.append(f"| {b}{' (Alpaca)' if b in ALPACA_MEMES else ''} | {a['first_bar']} | {a['first_eligible']} | "
                  f"{a['last_bar']} | {pct(a['drawdown_from_peak'])} |\n")
    md.append(f"\n### Deflation\n\nPrior: {pool['prior_trials']} trials, variance backed out of the published bar "
              f"({PRIOR_SR0} over {PRIOR_TRIALS}); here {pool['mine']} trials at 35 bps. Pooled bar "
              f"{pool['sr0_annual']:.2f} over {pool['n_total']}.\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(md), encoding="utf-8")
    d = fc.OUT / "reports"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{NAME}.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
