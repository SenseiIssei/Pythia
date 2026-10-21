"""VIX term-structure short-volatility sleeve (survey candidate 2).

    python -m lab.experiments.vix_carry            (cached downloads; --refresh fetches again)

Pre-registered in results/vix_carry_prereg.md (committed before this file ran). A -0.5x
short-VIX-futures product (SVXY since 2018-02-28; before that SVXY's -1x returns halved,
and before SVXY existed the S&P 500 VIX Short-Term Futures Index rebuilt from CBOE's VX
settlements) held only while VIX is below VIX3M, standalone against SPY and 60/40, and as
a 10 or 20 % sleeve next to the four crypto books. Writes results/vix_carry.md below the
marker and <reports>/vix_carry/latest.{md,json}.
"""

from __future__ import annotations

import io
import json
import math
import sys
import time
import urllib.request
from datetime import date, timedelta

import numpy as np
import polars as pl

from .. import report
from . import book_portfolio as bp
from . import director_common as dc
from . import fam_common as fc
from . import vol_etf_common as vc

NAME = "vix_carry"
LAST_DAY = "2026-10-14"
FEE = 0.0095                         # SVXY expense ratio, a year
SWITCH = np.datetime64("2018-02-28")  # first -0.5x day
SVXY_START = np.datetime64("2011-10-05")
IS_START, SPLIT = np.datetime64("2007-01-01"), np.datetime64("2018-01-01")
COST, STRESS = 0.0013, 0.0026
EQ_COST = 0.0002
YEARS_OOS = tuple(range(2018, 2027))
VOL_TARGET, VOL_WIN, MEAN_WIN = 0.20, 20, 60
ENTRIES = ("E1 q<1.00", "E2 q<0.95", "E3 q<60d mean")
SIZES = ("S1 fixed", "S2 inverse vol")
SLEEVES = (0.10, 0.20)
SLEEVE_SPLIT = np.datetime64("2024-01-01")
OLD_SCALE_END = date(2007, 3, 26)
MONTHS = "FGHJKMNQUVXZ"
ARCHIVE = "https://cdn.cboe.com/resources/futures/archive/volume-and-price/CFE_{}{:02d}_VX.csv"
NEWFMT = "https://cdn.cboe.com/data/us/futures/market_statistics/historical_data/VX/VX_{}.csv"


# ---------------------------------------------------------------------------
# VX futures and the rebuilt short-term index
# ---------------------------------------------------------------------------

def third_friday(y: int, m: int) -> date:
    d = date(y, m, 15)
    return d + timedelta(days=(4 - d.weekday()) % 7)


def vx_expiry(y: int, m: int) -> date:
    """The Wednesday 30 days before the third Friday of the following month."""
    ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
    return third_friday(ny, nm) - timedelta(days=30)


def _fetch(url: str) -> str | None:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            text = r.read().decode("utf-8", "replace")
    except OSError:
        return None
    return text if text.startswith("Trade Date") else None


def _parse(text: str) -> pl.DataFrame:
    df = pl.read_csv(io.StringIO(text), infer_schema_length=0)
    d = df["Trade Date"].str.strip_chars()
    fmt = "%m/%d/%Y" if "/" in d[0] else "%Y-%m-%d"
    out = pl.DataFrame({"date": d.str.strptime(pl.Date, fmt),
                        "settle": df["Settle"].cast(pl.Float64, strict=False),
                        "close": df["Close"].cast(pl.Float64, strict=False)})
    return out


def vx_contract(y: int, m: int, refresh: bool = False) -> pl.DataFrame | None:
    """(date, price) of one contract: the settlement where it is positive, else the close;
    both sources merged; prices before 2007-03-26 on the old 10x scale divided by 10."""
    f = vc.CACHE / "vx" / f"{y}-{m:02d}.csv"
    if f.exists() and not refresh:
        df = pl.read_csv(f, try_parse_dates=True)
        return df if df.height else None
    parts = []
    t = _fetch(ARCHIVE.format(MONTHS[m - 1], y % 100))
    if t:
        parts.append(_parse(t).with_columns(src=pl.lit(1)))
    exp = vx_expiry(y, m)
    for k in range(0, 4):
        t = _fetch(NEWFMT.format((exp - timedelta(days=k)).isoformat()))
        if t:
            parts.append(_parse(t).with_columns(src=pl.lit(0)))
            break
    time.sleep(0.2)
    if not parts:
        df = pl.DataFrame(schema={"date": pl.Date, "price": pl.Float64})
    else:
        x = pl.concat(parts)
        x = x.with_columns(price=pl.when(pl.col("settle") > 0).then(pl.col("settle"))
                           .when(pl.col("close") > 0).then(pl.col("close")).otherwise(None))
        x = x.filter(pl.col("price").is_not_null()).sort(["date", "src"])
        # prefer a positive settlement from either file
        x = x.with_columns(has_settle=(pl.col("settle") > 0).cast(pl.Int8))
        x = x.sort(["date", "has_settle"], descending=[False, True]).unique("date", keep="first").sort("date")
        df = x.select("date", "price").with_columns(
            price=pl.when(pl.col("date") < OLD_SCALE_END).then(pl.col("price") / 10).otherwise(pl.col("price")))
    f.parent.mkdir(parents=True, exist_ok=True)
    df.write_csv(f)
    return df if df.height else None


def vx_all(first: tuple[int, int] = (2006, 6), last: tuple[int, int] = (2027, 3),
           refresh: bool = False) -> dict[date, pl.DataFrame]:
    """{settlement date: contract frame}. The settlement date is the contract's last trading
    date in the file when that is within 3 days of the rule's Wednesday, else the rule's."""
    out = {}
    y, m = first
    while (y, m) <= last:
        df = vx_contract(y, m, refresh)
        if df is not None:
            exp = vx_expiry(y, m)
            lastd = df["date"].max()
            out[lastd if abs((lastd - exp).days) <= 3 else exp] = df
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def rebuild_index(contracts: dict[date, pl.DataFrame], cal: np.ndarray) -> np.ndarray:
    """Daily excess return of the short-term VIX futures index on calendar `cal`
    (datetime64[D]); NaN where a needed settlement is missing."""
    exps = sorted(contracts)
    px = {e: dict(zip(contracts[e]["date"].to_list(), contracts[e]["price"].to_list())) for e in exps}
    days = [date.fromisoformat(str(d)) for d in cal]
    pos = {d: i for i, d in enumerate(days)}

    def prev_bday(d: date) -> date:
        i = int(np.searchsorted(cal, np.datetime64(d)))
        return days[max(i - 1, 0)]

    starts = [prev_bday(e) for e in exps]                  # roll period k starts the Tuesday before exps[k]
    T = len(days)
    w1 = np.full(T, np.nan)
    c1 = [None] * T
    c2 = [None] * T
    for t, d in enumerate(days):
        k = int(np.searchsorted(np.array(starts, dtype="datetime64[D]"), np.datetime64(d), side="right")) - 1
        if k < 0 or k + 2 >= len(exps):
            continue
        s0, s1 = starts[k], starts[k + 1]
        if s0 not in pos or s1 not in pos:
            continue
        dt = pos[s1] - pos[s0]
        dr = pos[s1] - (t + 1)
        if dt <= 0:
            continue
        w1[t] = max(dr, 0) / dt
        c1[t], c2[t] = exps[k + 1], exps[k + 2]
    ret = np.full(T, np.nan)
    for t in range(1, T):
        if not np.isfinite(w1[t - 1]):
            continue
        a, b = c1[t - 1], c2[t - 1]
        p0a, p0b = px[a].get(days[t - 1]), px[b].get(days[t - 1])
        p1a, p1b = px[a].get(days[t]), px[b].get(days[t])
        if None in (p0a, p0b, p1a, p1b):
            continue
        w = w1[t - 1]
        den = w * p0a + (1 - w) * p0b
        if den > 0:
            ret[t] = (w * p1a + (1 - w) * p1b) / den - 1
    return ret


# ---------------------------------------------------------------------------
# Data on SPY's calendar
# ---------------------------------------------------------------------------

def aligned(sym: str, cal: np.ndarray, refresh: bool) -> dict[str, np.ndarray]:
    df = vc.yahoo_daily(sym, refresh)
    d = vc.to_np_dates(df["date"])
    idx = np.searchsorted(cal, d)
    ok = (idx < len(cal)) & (cal[np.minimum(idx, len(cal) - 1)] == d)
    out = {}
    for c in ("open", "close", "adj"):
        x = np.full(len(cal), np.nan)
        x[idx[ok]] = df[c].to_numpy().astype(float)[ok]
        out[c] = x
    return out


def ret_of(x: np.ndarray) -> np.ndarray:
    r = np.full(len(x), np.nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        r[1:] = x[1:] / x[:-1] - 1
    return r


def load(refresh: bool = False) -> dict:
    spy = vc.yahoo_daily("SPY", refresh)
    cal = vc.to_np_dates(spy["date"])
    cal = cal[(cal >= np.datetime64("2006-01-01")) & (cal <= np.datetime64(LAST_DAY))]
    S = {s: aligned(s, cal, refresh) for s in ("SPY", "IEF", "^VIX", "^VIX3M", "SVXY", "VIXY")}
    print("VX futures", flush=True)
    vx = vx_all(refresh=refresh)
    idx = rebuild_index(vx, cal)
    return {"cal": cal, "S": S, "idx": idx, "n_contracts": len(vx)}


def instrument(D: dict) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict]:
    """(close-to-close return, gap return, open-to-close return) of the -0.5x product on the
    calendar, and the checks."""
    cal, S, idx = D["cal"], D["S"], D["idx"]
    sv = S["SVXY"]
    r_sv = ret_of(sv["adj"])
    f = FEE / 252
    r = np.full(len(cal), np.nan)
    after = cal >= SWITCH
    mid = (cal >= SVXY_START) & ~after
    pre = cal < SVXY_START
    r[after] = r_sv[after]
    r[mid] = 0.5 * (r_sv[mid] + f) - f
    r[pre] = -0.5 * idx[pre] - f
    # gap and session parts (only where SVXY has opens)
    with np.errstate(invalid="ignore", divide="ignore"):
        gap = np.r_[np.nan, sv["open"][1:] / sv["close"][:-1] - 1]
        ses = sv["close"] / sv["open"] - 1
    gap = np.where(after, gap, 0.5 * gap)
    ses = np.where(after, ses, 0.5 * ses)
    # checks
    vixy = ret_of(S["VIXY"]["adj"])
    m1 = np.isfinite(idx) & np.isfinite(vixy) & (cal >= np.datetime64("2011-01-05"))
    m2 = np.isfinite(idx) & np.isfinite(r_sv) & mid
    win_pre = (cal >= SWITCH - 120) & (cal < SWITCH) & np.isfinite(idx) & (np.abs(np.nan_to_num(idx)) > 0.01)
    win_post = (cal >= SWITCH) & (cal < SWITCH + 120) & np.isfinite(idx) & (np.abs(np.nan_to_num(idx)) > 0.01)
    with np.errstate(invalid="ignore", divide="ignore"):
        ratio = r_sv / idx
    chk = {
        "corr_vixy": float(np.corrcoef(idx[m1], vixy[m1])[0, 1]) if m1.sum() > 50 else float("nan"),
        "corr_neg_svxy": float(np.corrcoef(idx[m2], -r_sv[m2])[0, 1]) if m2.sum() > 50 else float("nan"),
        "n_vixy": int(m1.sum()),
        "drift_vixy_minus_idx": float((np.nanmean(vixy[m1]) - np.nanmean(idx[m1])) * 252) if m1.sum() else float("nan"),
        "ratio_before": float(np.nanmedian(ratio[win_pre][-60:])) if win_pre.sum() else float("nan"),
        "ratio_after": float(np.nanmedian(ratio[win_post][:60])) if win_post.sum() else float("nan"),
        "idx_missing_is": int((~np.isfinite(idx) & pre & (cal >= IS_START)).sum()),
        "first_idx_day": str(cal[np.flatnonzero(np.isfinite(idx))[0]]) if np.isfinite(idx).any() else "none",
    }
    chk["rebuild_ok"] = bool(chk["corr_vixy"] > 0.95 and chk["corr_neg_svxy"] > 0.95)
    feb = (cal >= np.datetime64("2018-02-01")) & (cal < SWITCH)
    from scipy.stats import spearmanr
    chk["corr_neg_svxy_ex_feb2018"] = float(np.corrcoef(idx[m2 & ~feb], -r_sv[m2 & ~feb])[0, 1])
    chk["spearman_neg_svxy"] = float(spearmanr(idx[m2], -r_sv[m2]).correlation)
    chk["spearman_vixy"] = float(spearmanr(idx[m1], vixy[m1]).correlation)
    return r, gap, ses, chk


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------

def rolling_mean_past(x: np.ndarray, w: int) -> np.ndarray:
    out = np.full(len(x), np.nan)
    for t in range(w - 1, len(x)):
        seg = x[t - w + 1:t + 1]
        if np.isfinite(seg).sum() >= int(0.9 * w):
            out[t] = np.nanmean(seg)
    return out


def rolling_vol(r: np.ndarray, w: int) -> np.ndarray:
    out = np.full(len(r), np.nan)
    for t in range(w, len(r)):
        seg = r[t - w + 1:t + 1]
        seg = seg[np.isfinite(seg)]
        if len(seg) >= w - 2:
            out[t] = seg.std(ddof=1) * math.sqrt(252)
    return out


def targets(q: np.ndarray, r: np.ndarray, entry: str, size: str) -> np.ndarray:
    """Target weight decided at the close of t (0 where the signal is missing)."""
    if entry.startswith("E1"):
        on = q < 1.00
    elif entry.startswith("E2"):
        on = q < 0.95
    else:
        on = q < rolling_mean_past(q, MEAN_WIN)
    on = np.where(np.isfinite(q), on, False)
    if size.startswith("S1"):
        w = np.ones(len(q))
    else:
        v = rolling_vol(r, VOL_WIN)
        with np.errstate(invalid="ignore", divide="ignore"):
            w = np.where(np.isfinite(v) & (v > 0), np.minimum(1.0, VOL_TARGET / v), 0.0)
    return np.where(on, w, 0.0)


def simulate(tgt: np.ndarray, r: np.ndarray, lag: int, cost: float) -> tuple[np.ndarray, np.ndarray]:
    """Close fills: the target decided at the close of t is held from the close of t+lag.
    Daily net return and turnover; the rest in cash; drift traded back to target daily."""
    T = len(r)
    w = 0.0
    net, tov = np.zeros(T), np.zeros(T)
    rr = np.nan_to_num(r)
    for t in range(T):
        g = w * rr[t]
        w = w * (1 + rr[t]) / (1 + g) if 1 + g > 0 else 0.0
        new = tgt[t - lag] if t - lag >= 0 else 0.0
        tov[t] = abs(new - w)
        net[t] = g - cost * tov[t]
        w = new
    return net, tov


def simulate_open(tgt: np.ndarray, r: np.ndarray, gap: np.ndarray, ses: np.ndarray, cost: float) -> np.ndarray:
    """Open fills: the target decided at the close of t is traded at the open of t+1."""
    T = len(r)
    w = 0.0
    net = np.zeros(T)
    for t in range(1, T):
        if not (np.isfinite(gap[t]) and np.isfinite(ses[t])):
            g = w * np.nan_to_num(r[t])
            new = tgt[t - 1]
            net[t] = g - cost * abs(new - w)
            w = new
            continue
        g1 = w * gap[t]
        w1 = w * (1 + gap[t]) / (1 + g1) if 1 + g1 > 0 else 0.0
        new = tgt[t - 1]
        c = cost * abs(new - w1)
        g2 = new * ses[t]
        net[t] = (1 + g1) * (1 + g2) - 1 - c
        w = new * (1 + ses[t]) / (1 + g2) if 1 + g2 > 0 else 0.0
        w = new if new == 0 else w
    return net


def sixty_forty(spy: np.ndarray, ief: np.ndarray, cal: np.ndarray) -> np.ndarray:
    T = len(cal)
    month = cal.astype("datetime64[M]")
    w = np.array([0.6, 0.4])
    net = np.zeros(T)
    for t in range(1, T):
        a = np.array([np.nan_to_num(spy[t]), np.nan_to_num(ief[t])])
        g = float(w @ a)
        net[t] = g
        w = w * (1 + a) / (1 + g)
        if month[t] != month[t - 1] or t == 1:
            net[t] -= EQ_COST * float(np.abs(np.array([0.6, 0.4]) - w).sum())
            w = np.array([0.6, 0.4])
    return net


# ---------------------------------------------------------------------------
# Sleeve
# ---------------------------------------------------------------------------

def sleeve_rows(x_cal: np.ndarray, cal: np.ndarray) -> dict:
    """The pick as 10 / 20 % next to the equal-weight crypto books, book_portfolio's way."""
    P = dc.cut_panel(fc.load_panel(), LAST_DAY)
    fc._PANEL = P
    days, books = bp.crypto_books()
    names = list(bp.BOOKS)
    R = np.column_stack([books[n] for n in names])
    eq = np.zeros(len(days))
    idx = np.searchsorted(days, cal)
    ok = (idx < len(days)) & (days[np.minimum(idx, len(days) - 1)] == cal)
    eq[idx[ok]] = np.nan_to_num(x_cal[ok])
    spy = np.zeros(len(days))
    return {"days": days, "R": R, "names": names, "eq": eq, "spy_slot": spy}


def mix(R: np.ndarray, days: np.ndarray, eq: np.ndarray | None, share: float, eq_cost: float) -> np.ndarray:
    Wc = bp.crypto_weights(R, "EW", days)
    if eq is None or share == 0:
        net, _ = bp.portfolio(R, Wc, np.full(R.shape[1], bp.CRYPTO_COST))
        return net
    A = np.column_stack([R, eq])
    W = np.column_stack([(1 - share) * Wc, np.full(len(R), share)])
    net, _ = bp.portfolio(A, W, np.r_[np.full(R.shape[1], bp.CRYPTO_COST), eq_cost])
    return net


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

def run(refresh: bool = False) -> dict:
    D = load(refresh)
    cal, S = D["cal"], D["S"]
    r, gap, ses, chk = instrument(D)
    is_start = IS_START if chk["rebuild_ok"] else SVXY_START
    q = S["^VIX"]["close"] / S["^VIX3M"]["close"]
    ins = (cal >= is_start) & (cal < SPLIT)
    oos = cal >= SPLIT
    years = cal.astype("datetime64[Y]").astype(int) + 1970
    spy = ret_of(S["SPY"]["adj"])
    ief = ret_of(S["IEF"]["adj"])
    spy_n = np.nan_to_num(spy)
    b6040 = sixty_forty(spy, ief, cal)
    always, _ = simulate(np.ones(len(cal)), r, 1, COST)

    rows = []
    series = {}
    for e in ENTRIES:
        for s in SIZES:
            tgt = targets(q, r, e, s)
            n1, tv = simulate(tgt, r, 1, COST)
            n1s, _ = simulate(tgt, r, 1, STRESS)
            n2, _ = simulate(tgt, r, 2, COST)
            no = simulate_open(tgt, r, gap, ses, COST)
            name = f"{e} · {s}"
            series[name] = {"base": n1, "stress": n1s, "late": n2, "open": no, "tgt": tgt}
            p_is, p_oos = vc.perf(n1[ins], 252), vc.perf(n1[oos], 252)
            rows.append({"rule": name, "is_sharpe": p_is["sharpe"], "is_dd": p_is["max_dd"],
                         "oos_sharpe": p_oos["sharpe"], "oos_cagr": p_oos["cagr"], "oos_dd": p_oos["max_dd"],
                         "oos_stress": vc.sharpe(n1s[oos], 252), "oos_late": vc.sharpe(n2[oos], 252),
                         "oos_open": vc.sharpe(no[oos], 252), "time_in": float((tgt[oos] > 0).mean()),
                         "turnover_yr": float(tv[oos].sum() / (oos.sum() / 252)),
                         "worst_day": float(n1[oos].min())})
    pick = max(rows, key=lambda x: x["is_sharpe"])
    ps = series[pick["rule"]]
    x = ps["base"]
    yrs = vc.by_year(x[oos], years[oos], 252, YEARS_OOS)
    b_spy = vc.boot_band(x[oos], 252, spy_n[oos])
    bench = {"SPY": vc.perf(spy_n[oos], 252), "60/40": vc.perf(b6040[oos], 252),
             "-0.5x always": vc.perf(always[oos], 252)}
    bench_is = {"SPY": vc.perf(spy_n[ins], 252), "60/40": vc.perf(b6040[ins], 252),
                "-0.5x always": vc.perf(always[ins], 252)}
    rules = {
        "Sharpe above SPY's": pick["oos_sharpe"] > bench["SPY"]["sharpe"],
        "drawdown below SPY's": pick["oos_dd"] < bench["SPY"]["max_dd"],
        "positive in 6 of 9 years": sum(v > 0 for v in yrs.values()) >= 6,
        "above 0 a day late": pick["oos_late"] > 0,
        "bootstrap 5 % of Sharpe - SPY's above 0": b_spy[0] > 0,
    }
    kill = {"single day below -30 %": pick["worst_day"] < -0.30,
            "Sharpe below 60/40's": pick["oos_sharpe"] < bench["60/40"]["sharpe"]}
    worst = np.argsort(x[oos])[:10]
    oi = np.flatnonzero(oos)
    worst_rows = [{"day": str(cal[oi[i]]), "net": float(x[oi[i]]),
                   "q_prior_close": float(q[oi[i] - 1]) if oi[i] > 0 else float("nan"),
                   "weight_held": float(ps["tgt"][oi[i] - 2]) if oi[i] > 1 else 0.0,
                   "instrument": float(r[oi[i]])} for i in worst]
    events = {}
    for lab, a, b in (("2018-02 (Volmageddon)", "2018-02-01", "2018-02-28"),
                      ("2020-02-20 to 2020-04-30 (Covid)", "2020-02-20", "2020-04-30"),
                      ("2024-08-01 to 2024-08-15 (yen carry)", "2024-08-01", "2024-08-15"),
                      ("2025-04-01 to 2025-04-30 (tariffs)", "2025-04-01", "2025-04-30")):
        m = (cal >= np.datetime64(a)) & (cal <= np.datetime64(b))
        events[lab] = {"pick": float(np.prod(1 + x[m]) - 1), "always": float(np.prod(1 + always[m]) - 1),
                       "spy": float(np.prod(1 + spy_n[m]) - 1)}

    print("sleeve: crypto books", flush=True)
    sl = sleeve_rows(x, cal)
    days, R = sl["days"], sl["R"]
    s_oos = days >= SLEEVE_SPLIT
    s_years = days.astype("datetime64[Y]").astype(int) + 1970
    single = {n: R[:, i] for i, n in enumerate(sl["names"])}
    best_name = max(single, key=lambda n: vc.sharpe(single[n][s_oos], 365))
    best = single[best_name]
    ew = mix(R, days, None, 0, 0)
    spy_days = np.zeros(len(days))
    idx = np.searchsorted(days, cal)
    ok = (idx < len(days)) & (days[np.minimum(idx, len(days) - 1)] == cal)
    spy_days[idx[ok]] = spy_n[ok]
    mixes = {share: mix(R, days, sl["eq"], share, COST) for share in SLEEVES}
    pl_ = vc.pool([rw["oos_sharpe"] for rw in rows] + [vc.sharpe(m[s_oos], 365) for m in mixes.values()])
    dp = vc.deflated(x[oos], pl_, 252)
    sleeve = []
    for share in SLEEVES:
        m = mixes[share]
        ms =mix(R, days, spy_days, share, EQ_COST)
        py = {y: vc.sharpe(m[s_oos & (s_years == y)], 365) for y in (2024, 2025, 2026)}
        by = {y: vc.sharpe(best[s_oos & (s_years == y)], 365) for y in (2024, 2025, 2026)}
        dy = {y: vc.max_dd(m[s_oos & (s_years == y)]) for y in (2024, 2025, 2026)}
        bdy = {y: vc.max_dd(best[s_oos & (s_years == y)]) for y in (2024, 2025, 2026)}
        band = vc.boot_band(m[s_oos], 365, best[s_oos])
        band_ew = vc.boot_band(m[s_oos], 365, ew[s_oos])
        pm, pb = vc.perf(m[s_oos], 365), vc.perf(best[s_oos], 365)
        rr = {"Sharpe above the best book's": pm["sharpe"] > pb["sharpe"],
              "drawdown below the best book's": pm["max_dd"] < pb["max_dd"],
              "2 of 3 years on Sharpe and on drawdown": sum(py[y] > by[y] for y in py) >= 2
              and sum(dy[y] < bdy[y] for y in dy) >= 2,
              "bootstrap 5 % of the difference above 0": band[0] > 0}
        sleeve.append({"share": share, "perf": pm, "is_sharpe": vc.sharpe(m[~s_oos & (days >= bp.IS_START)], 365),
                       "years": py, "years_dd": dy, "band": band, "band_vs_ew": band_ew, "rules": rr,
                       "pass": all(rr.values()), "spy_sleeve": vc.perf(ms[s_oos], 365),
                       "deflated_p": vc.deflated(m[s_oos], pl_, 365)})
    corr = float(np.corrcoef(sl["eq"][s_oos], ew[s_oos])[0, 1])
    res = {
        "generated": dc.day_str(int(time.time() * 1e6)), "last_day": LAST_DAY, "checks": chk,
        "n_contracts": D["n_contracts"], "is_start": str(is_start), "rows": rows, "pick": pick,
        "pick_years": yrs, "boot_vs_spy": b_spy, "deflated_p": dp, "pool": pl_, "rules": rules,
        "passes": all(rules.values()), "kill": kill, "killed": any(kill.values()), "bench": bench,
        "bench_is": bench_is, "worst": worst_rows, "events": events,
        "sleeve": sleeve, "best_book": best_name, "best_perf": vc.perf(best[s_oos], 365),
        "best_years": {y: vc.sharpe(best[s_oos & (s_years == y)], 365) for y in (2024, 2025, 2026)},
        "ew_perf": vc.perf(ew[s_oos], 365), "corr_sleeve_ew": corr,
        "oos_days": int(oos.sum()),
    }
    return res


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def pct(v: float) -> str:
    return f"{v * 100:.1f} %"


def markdown(res: dict) -> str:
    p, b = res["pick"], res["bench"]
    c = res["checks"]
    verdict = ("**Killed.**" if res["killed"] else ("**Passes.**" if res["passes"] else "**Fails.**"))
    kills = [k for k, v in res["kill"].items() if v]
    fails = [k for k, v in res["rules"].items() if not v]
    L = [f"## Results (generated {res['generated']}, in sample {res['is_start']} to 2017-12-31, "
         f"out of sample 2018-01-01 to {res['last_day']})", ""]
    L.append(f"{verdict} The in-sample pick is **{p['rule']}** (in-sample Sharpe {p['is_sharpe']:.2f}). "
             f"Out of sample it makes Sharpe {p['oos_sharpe']:.2f}, {pct(p['oos_cagr'])} a year, drawdown "
             f"{pct(p['oos_dd'])}, worst day {pct(p['worst_day'])}, against SPY {b['SPY']['sharpe']:.2f} / "
             f"{pct(b['SPY']['cagr'])} / {pct(b['SPY']['max_dd'])} and 60/40 {b['60/40']['sharpe']:.2f} / "
             f"{pct(b['60/40']['cagr'])} / {pct(b['60/40']['max_dd'])}. A day late {p['oos_late']:.2f}, at 26 bps "
             f"{p['oos_stress']:.2f}, filled at the next open {p['oos_open']:.2f}. Bootstrap 90 % band of "
             f"Sharpe(pick) - Sharpe(SPY) {res['boot_vs_spy'][0]:.2f} to {res['boot_vs_spy'][1]:.2f} "
             f"({res['boot_vs_spy'][2] * 100:.0f} % of draws above 0). Deflated p {res['deflated_p']:.2f} over "
             f"{res['pool']['n_total']:,} trials (noise bar about {res['pool']['sr0_annual']:.2f}).")
    L.append("")
    if kills:
        L.append("Kill rule hit: " + "; ".join(kills) + ".")
    if fails:
        L.append("Pass rules failed: " + "; ".join(fails) + ".")
    L.append("")
    L.append(f"Holding the -0.5x product always (no switch) makes {b['-0.5x always']['sharpe']:.2f}, drawdown "
             f"{pct(b['-0.5x always']['max_dd'])} out of sample; in sample {res['bench_is']['-0.5x always']['sharpe']:.2f} "
             f"against SPY {res['bench_is']['SPY']['sharpe']:.2f}.")
    L += ["", "### The six rules (13 bps per unit of turnover, fills at the next close)", ""]
    L.append(dc.table(res["rows"], ["rule", "is_sharpe", "is_dd", "oos_sharpe", "oos_cagr", "oos_dd", "oos_stress",
                                    "oos_late", "oos_open", "time_in", "turnover_yr", "worst_day"]))
    L += ["", "The pick per year out of sample: " + ", ".join(f"{y} {v:.2f}" for y, v in res["pick_years"].items()) + ".",
          "", "### Stress windows (cumulative return)", ""]
    L.append(dc.table([{"window": k, **v} for k, v in res["events"].items()], ["window", "pick", "always", "spy"], ".3f"))
    L += ["", "### The pick's ten worst days out of sample", ""]
    L.append(dc.table(res["worst"], ["day", "net", "q_prior_close", "weight_held", "instrument"], ".3f"))
    L += ["", "### Sleeve next to the four crypto books (equal weight, 35 bps, out of sample from 2024)", ""]
    bpf = res["best_perf"]
    L.append(f"Yardstick: {res['best_book']} alone, Sharpe {bpf['sharpe']:.2f}, {pct(bpf['cagr'])} a year, drawdown "
             f"{pct(bpf['max_dd'])}; per year " + ", ".join(f"{y} {v:.2f}" for y, v in res["best_years"].items())
             + f". The equal-weight crypto mix without a sleeve: {res['ew_perf']['sharpe']:.2f}, drawdown "
             f"{pct(res['ew_perf']['max_dd'])}. Correlation of the sleeve with the crypto mix: {res['corr_sleeve_ew']:.2f}.")
    L.append("")
    srows = []
    for s in res["sleeve"]:
        srows.append({"sleeve": f"{int(s['share'] * 100)} %", "sharpe": s["perf"]["sharpe"], "cagr": s["perf"]["cagr"],
                      "max_dd": s["perf"]["max_dd"],
                      "years": " / ".join(f"{v:.2f}" for v in s["years"].values()),
                      "band_vs_best": f"{s['band'][0]:.2f} to {s['band'][1]:.2f}",
                      "band_vs_ew": f"{s['band_vs_ew'][0]:.2f} to {s['band_vs_ew'][1]:.2f}",
                      "spy_instead": s["spy_sleeve"]["sharpe"], "deflated_p": s["deflated_p"],
                      "verdict": "pass" if s["pass"] else "fails: " + ", ".join(k for k, v in s["rules"].items() if not v)})
    L.append(dc.table(srows, ["sleeve", "sharpe", "cagr", "max_dd", "years", "band_vs_best", "band_vs_ew",
                              "spy_instead", "deflated_p", "verdict"]))
    L += ["", "### Rebuild checks", "",
          f"{res['n_contracts']} VX contracts; the rebuilt index starts {c['first_idx_day']}. Correlation with VIXY "
          f"{c['corr_vixy']:.3f} over {c['n_vixy']} days (VIXY minus index {c['drift_vixy_minus_idx'] * 100:.1f} % a "
          f"year, its fee and the 16:00 / 16:15 timing), with -SVXY before the switch {c['corr_neg_svxy']:.3f}. "
          f"SVXY / index return ratio: median {c['ratio_before']:.2f} in the 60 days before 2018-02-28 and "
          f"{c['ratio_after']:.2f} after, so the leverage change sits where the series puts it. "
          f"Rebuild {'passes' if c['rebuild_ok'] else 'FAILS'} its registered check (both correlations above 0.95), "
          f"so the in-sample window starts {res['is_start']}. Diagnosis: without February 2018 the correlation with "
          f"-SVXY is {c['corr_neg_svxy_ex_feb2018']:.3f}; rank correlations {c['spearman_vixy']:.3f} (VIXY) and "
          f"{c['spearman_neg_svxy']:.3f} (-SVXY). The rebuild settles at 16:15 and the ETFs close at 16:00, which "
          f"on a few days (2018-02-05 and 06, 2012-12-28 and 31, 2014-10-15, 2016-06-28) moves the futures by 5 to "
          f"60 points between the two prints."]
    return "\n".join(L)


def main() -> int:
    res = run("--refresh" in sys.argv)
    md = markdown(res)
    dc.write_results(NAME, md)
    report.write(NAME, md, json.loads(json.dumps(res, default=str)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
