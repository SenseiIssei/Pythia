"""X11 a: M2 v3, the weekly coin ranking with flow, positioning and market inputs.

Pre-registered in results/model_upgrades_prereg.md (section a) before any
number was computed. v2 is today's M2 (lab.experiments.picks --perp-features);
v3 adds five feature groups:

  F  funding and basis dynamics   fund1, fund28, basis_chg7       (every coin with a perp)
  P  positioning                  oi_chg7, ls_acct, ls_chg7       (the 20 coins with metrics, 2022 on)
  M  market state, one per day    cb_prem, kr_prem, stable_30, stable_7, dvol, mkt_funding
                                  (X6's definitions, z-scores over 365 days, not ranked)
  T  trend and attention          dist_hi365, volu_28_180
  V  longer and idiosyncratic     vol90, ivol56

Same coin-days, parameters and quarterly walk-forward from 2022 as v2. Groups
are selected on 2022-23 (a group stays when removing it lowers the mean daily
rank IC there) and judged from 2024: H1 whole universe, H2 among the Alpaca
coins, H3 averaged with low vol, each against v2 with a Newey-West t above
2.39 and better in 2 of 3 years.

    python -m lab.experiments.m2_v3                # the study (cached panel and scores)
    python -m lab.experiments.m2_v3 --refresh      # rebuild the panel
    python -m lab.experiments.m2_v3 --shadow       # weekly: train v2 and v3, record both rankings, score old ones

Writes results/m2_v3.md (PYTHIA_RESULTS) and reports/m2_v3/. The shadow
writes <data>/paper/m2_v3_shadow/ (rankings.jsonl before the outcome,
scores.json after); no book and no engine reads it.
"""

from __future__ import annotations

import json
import math
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import lightgbm as lgb
import numpy as np
import polars as pl

from .. import report, universe
from ..cv import walk_forward
from ..data import ROOT
from . import picks
from .picks import DAY_US, FEATURES, FIRST_TEST, HORIZON, MIN_ADV_USD, MIN_HISTORY_D, PARAMS, PERP_FEATURES
from .picks_ls import perp_base, perp_panel

NAME = "m2_v3"
CACHE = Path(os.environ.get("PYTHIA_CACHE", report.REPORTS / "_cache"))
V2 = FEATURES + PERP_FEATURES
GROUPS = {
    "F": ["fund1", "fund28", "basis_chg7"],
    "P": ["oi_chg7", "ls_acct", "ls_chg7"],
    "M": ["cb_prem", "kr_prem", "stable_30", "stable_7", "dvol", "mkt_funding"],
    "T": ["dist_hi365", "volu_28_180"],
    "V": ["vol90", "ivol56"],
}
UNRANKED = set(GROUPS["M"])
SEL = (int(datetime(2022, 1, 1, tzinfo=timezone.utc).timestamp() * 1e6),
       int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp() * 1e6))
JUDGE_FROM = SEL[1]
YEARS = (2024, 2025, 2026)
PASS_T = 2.39
NW_LAG = 7
MIN_ALPACA = 8
Z_WINDOW, Z_MIN = 365, 180
SMOOTH = 7
TOP_PERPS = 20
SHADOW_DIR = ROOT / "paper" / "m2_v3_shadow"
SHADOW_WEEKS = 26
SHADOW_T = 2.0


def v3_features(groups) -> list[str]:
    return V2 + [f for g in groups for f in GROUPS[g]]


# ---------------------------------------------------------------- per-coin inputs

def segment_frame(seg: pl.DataFrame, name: str, btc: pl.DataFrame) -> pl.DataFrame | None:
    """picks.features for one continuous segment, plus groups T and V, which need
    the segment's whole history (they are computed before eligibility filters rows)."""
    d = picks.daily_from_hourly(seg, name)
    if d.height < MIN_HISTORY_D + 10:
        return None
    f = picks.features(d, btc)
    lc = pl.col("close").log()
    ret = lc - lc.shift(1)
    bret = pl.col("btc_close").log() - pl.col("btc_close").log().shift(1)
    f = f.with_columns(_r=ret, _b=bret).with_columns(
        dist_hi365=lc - pl.col("high").rolling_max(365, min_samples=28).log(),
        volu_28_180=(pl.col("qv").rolling_mean(28) + 1).log() - (pl.col("qv").rolling_mean(180, min_samples=56) + 1).log(),
        vol90=pl.col("rv").rolling_mean(90, min_samples=60).sqrt(),
        _mx=pl.col("_r").rolling_mean(56, min_samples=40), _my=pl.col("_b").rolling_mean(56, min_samples=40),
        _mxy=(pl.col("_r") * pl.col("_b")).rolling_mean(56, min_samples=40),
        _mxx=(pl.col("_r") ** 2).rolling_mean(56, min_samples=40),
        _myy=(pl.col("_b") ** 2).rolling_mean(56, min_samples=40),
    ).with_columns(
        _cov=pl.col("_mxy") - pl.col("_mx") * pl.col("_my"),
        _vx=pl.col("_mxx") - pl.col("_mx") ** 2, _vy=pl.col("_myy") - pl.col("_my") ** 2,
    ).with_columns(_beta=pl.col("_cov") / (pl.col("_vy") + 1e-12)).with_columns(
        ivol56=(pl.col("_vx") - pl.col("_beta") ** 2 * pl.col("_vy")).clip(lower_bound=0).sqrt(),
    )
    return f.drop([c for c in f.columns if c.startswith("_")])


def _symbol(s: str, btc: pl.DataFrame) -> list[pl.DataFrame]:
    segs = picks.hourly_segments(s)
    out = []
    for j, seg in enumerate(segs):
        name = s if j == len(segs) - 1 else f"{s}~{j}"
        fr = segment_frame(seg, name, btc)
        if fr is not None:
            out.append(fr)
    return out


def perp_daily() -> pl.DataFrame:
    """Per (day, base), the largest perp that day: funding over 1 and 28 days, close, volume."""
    pp = perp_panel().sort(["perp", "day"]).with_columns(
        fund7=pl.col("funding").rolling_sum(7, min_samples=1).over("perp"),
        fund28=pl.col("funding").rolling_sum(28, min_samples=7).over("perp"),
        fund1=pl.col("funding"))
    return (pp.sort("qv", descending=True).group_by(["day", "base"]).first()
            .select("day", "base", "fund1", "fund7", "fund28", perp_close="close", perp_qv="qv"))


def positioning() -> pl.DataFrame:
    """(day, symbol, oi_chg7, ls_acct, ls_chg7) for the perps with Binance metrics archives."""
    root = ROOT / "hist" / "binance_um" / "metrics"
    frames = []
    for d in sorted(root.glob("symbol=*")):
        sym = d.name.split("=", 1)[1]
        files = sorted(d.glob("*.parquet"))
        if not files:
            continue
        m = (pl.concat([pl.read_parquet(f, columns=["ts_us", "sum_open_interest", "count_long_short_ratio"])
                        for f in files], how="vertical_relaxed").unique("ts_us").sort("ts_us")
             .with_columns(day=(pl.col("ts_us") // DAY_US) * DAY_US)
             .group_by("day").agg(oi=pl.col("sum_open_interest").drop_nulls().last(),
                                  ls=pl.col("count_long_short_ratio").mean()).sort("day"))
        past = m.select(day=pl.col("day") + 7 * DAY_US, oi_7="oi", ls_7="ls")
        m = (m.join(past, on="day", how="left")
             .with_columns(oi_chg7=(pl.col("oi") / pl.col("oi_7")).log(),
                           ls_chg7=(pl.col("ls") / pl.col("ls_7")).log())
             .with_columns(ls_acct=pl.col("ls").rolling_mean(SMOOTH, min_samples=5)))
        frames.append(m.select("day", "oi_chg7", "ls_acct", "ls_chg7")
                      .with_columns(symbol=pl.lit(f"{perp_base(sym)}USDT")))
    if not frames:
        return pl.DataFrame(schema={"day": pl.Int64, "oi_chg7": pl.Float64, "ls_acct": pl.Float64,
                                    "ls_chg7": pl.Float64, "symbol": pl.Utf8})
    return pl.concat(frames, how="vertical_relaxed")


# ---------------------------------------------------------------- market state (X6's definitions)

def _z(x: np.ndarray, w: int = Z_WINDOW, min_obs: int = Z_MIN) -> np.ndarray:
    s = pl.Series(x)
    m = s.rolling_mean(w, min_samples=min_obs).to_numpy()
    sd = s.rolling_std(w, min_samples=min_obs, ddof=0).to_numpy()
    with np.errstate(invalid="ignore", divide="ignore"):
        z = np.where(sd > 0, (x - m) / sd, np.nan)
    return np.where(np.isfinite(x), z, np.nan)


def _flow(name: str) -> pl.DataFrame | None:
    p = Path(os.environ.get("PYTHIA_FLOW", str(ROOT / "flow"))) / f"{name}.parquet"
    return pl.read_parquet(p) if p.exists() else None


def market_state(btc_daily: pl.DataFrame, pp: pl.DataFrame) -> pl.DataFrame:
    """(day, M columns) on a calendar of every day, each a trailing z-score."""
    days = np.arange(int(btc_daily["day"].min()), int(btc_daily["day"].max()) + DAY_US, DAY_US, dtype=np.int64)
    cal = pl.DataFrame({"day": days}).join(btc_daily.select("day", btc="close"), on="day", how="left")

    def place(df: pl.DataFrame | None, day_col: str, val: pl.Expr, shift_days: int = 0) -> np.ndarray:
        if df is None or df.is_empty():
            return np.full(len(days), np.nan)
        x = df.select(day=pl.col(day_col) + shift_days * DAY_US, v=val).unique("day", keep="last")
        return cal.select("day").join(x, on="day", how="left")["v"].fill_null(np.nan).to_numpy().astype(float)

    def smooth(x: np.ndarray) -> np.ndarray:
        return pl.Series(x).fill_nan(None).rolling_mean(SMOOTH, min_samples=5).fill_null(np.nan).to_numpy()

    # Coinbase premium: mean over the day's hours of Coinbase / Binance BTC close - 1, then 7-day mean.
    cb = _flow("coinbase_btcusd_1h")
    if cb is not None:
        bn = picks.hourly_segments("BTCUSDT")
        bn = pl.concat(bn).select(ts_us="open_time_us", bn="close") if bn else pl.DataFrame()
        h = cb.select("ts_us", cb_="close").join(bn, on="ts_us", how="inner") if not bn.is_empty() else None
        if h is not None:
            dd = (h.with_columns(prem=pl.col("cb_") / pl.col("bn") - 1, day=(pl.col("ts_us") // DAY_US) * DAY_US)
                  .group_by("day").agg(pl.col("prem").mean(), n=pl.len()).filter(pl.col("n") >= 12))
            cb_prem = smooth(place(dd, "day", pl.col("prem")))
        else:
            cb_prem = np.full(len(days), np.nan)
    else:
        cb_prem = np.full(len(days), np.nan)
    # Korean premium: Upbit KRW-BTC close / (Binance close x USD/KRW, last rate on or before) - 1.
    up, fx = _flow("upbit_krwbtc_1d"), _flow("fx_usdkrw")
    krw = place(up, "day_us", pl.col("close"))
    if fx is not None:
        f = fx.sort("day_us")
        idx = np.searchsorted(f["day_us"].to_numpy(), days, side="right") - 1
        rate = np.where(idx >= 0, f["usdkrw"].to_numpy()[np.maximum(idx, 0)], np.nan)
    else:
        rate = np.full(len(days), np.nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        kr_prem = smooth(krw / (cal["btc"].fill_null(np.nan).to_numpy() * rate) - 1)
    # Stablecoins: USDT + USDC, the value stamped D used from the close of D+1.
    st = _flow("stables")
    if st is not None:
        st = st.filter(pl.col("usdt").is_not_null() & pl.col("usdc").is_not_null())
    sup = place(st, "day_us", pl.col("usdt") + pl.col("usdc"), shift_days=1)

    def logchg(x, k):
        out = np.full_like(x, np.nan)
        with np.errstate(invalid="ignore", divide="ignore"):
            out[k:] = np.log(x[k:] / x[:-k])
        return out
    dv = _flow("dvol")
    dvol = place(dv.filter(pl.col("currency") == "BTC") if dv is not None else None, "day_us", pl.col("close"))
    # Market funding: the 20 most liquid perps that day, weighted by quote volume, 7-day mean.
    top = (pp.filter(pl.col("perp_qv").is_not_null())
           .with_columns(rk=pl.col("perp_qv").rank("ordinal", descending=True).over("day"))
           .filter(pl.col("rk") <= TOP_PERPS)
           .group_by("day").agg(f=(pl.col("fund1") * pl.col("perp_qv")).sum() / pl.col("perp_qv").sum()))
    mkt_f = smooth(place(top, "day", pl.col("f")))
    raw = {"cb_prem": cb_prem, "kr_prem": kr_prem, "stable_30": logchg(sup, 30), "stable_7": logchg(sup, 7),
           "dvol": dvol, "mkt_funding": mkt_f}
    return pl.DataFrame({"day": days, **{k: _z(v) for k, v in raw.items()}})


# ---------------------------------------------------------------- the panel

def build_raw_v3(refresh: bool = False) -> pl.DataFrame:
    """v2's raw panel (same rows, same values) with the five new groups."""
    path = CACHE / "m2_v3_raw.parquet"
    if path.exists() and not refresh:
        return pl.read_parquet(path)
    t0 = time.time()
    syms = json.loads((ROOT / "hist" / "universe.json").read_text())
    btc = picks.daily_bars("BTCUSDT")
    frames = []
    with ThreadPoolExecutor(8) as ex:
        for i, fr in enumerate(ex.map(lambda s: _symbol(s, btc), syms)):
            frames.extend(fr)
            if i % 100 == 0:
                print(f"{i}/{len(syms)} symbols, {time.time() - t0:.0f}s", flush=True)
    p = pl.concat(frames, how="vertical_relaxed")
    p = p.filter((pl.col("age") >= MIN_HISTORY_D) & (pl.col("adv28") >= np.log(MIN_ADV_USD + 1)))
    p = p.drop_nulls(FEATURES)
    pp = perp_daily()
    p = (p.with_columns(base=pl.col("symbol").str.strip_suffix("USDT"))
         .join(pp, on=["day", "base"], how="left")
         .with_columns(mult=(pl.col("perp_close") / pl.col("close")).log10().round(0))
         .with_columns(basis=(pl.col("perp_close") / (pl.col("close") * 10 ** pl.col("mult"))).log(),
                       perp_share=((pl.col("perp_qv") + 1) / (pl.col("qv") + 1)).log())
         .drop("perp_close", "perp_qv", "mult", "base"))
    past = p.select("symbol", day=pl.col("day") + 7 * DAY_US, basis_7="basis")
    p = p.join(past, on=["symbol", "day"], how="left").with_columns(
        basis_chg7=pl.col("basis") - pl.col("basis_7")).drop("basis_7")
    # A coin without a perp has no funding (v2 leaves fund7 missing; so do fund1 and fund28).
    p = p.join(positioning(), on=["day", "symbol"], how="left")
    p = p.join(market_state(btc, pp), on="day", how="left").sort(["day", "symbol"])
    CACHE.mkdir(parents=True, exist_ok=True)
    p.write_parquet(path)
    print(f"raw panel {p.height:,} rows, {p['symbol'].n_unique()} coins, {time.time() - t0:.0f}s", flush=True)
    return p


def rank_v3(raw: pl.DataFrame, feats: list[str]) -> pl.DataFrame:
    """picks.rank_cross_section on the ranked inputs; market inputs stay as they are. A new
    input that is not finite (an open interest of 0 in the archive) is missing, never ranked."""
    new = [f for g in GROUPS.values() for f in g if f in raw.columns]
    raw = raw.with_columns([pl.when(pl.col(c).is_finite()).then(pl.col(c)).otherwise(None).alias(c) for c in new])
    return picks.rank_cross_section(raw, [f for f in feats if f not in UNRANKED])


# ---------------------------------------------------------------- walk-forward

def walk(panel_path: str, feats: list[str]) -> np.ndarray:
    """M2's quarterly walk-forward (picks.main) on the given inputs: out-of-sample scores."""
    P = pl.read_parquet(panel_path)
    days = P["day"].to_numpy()
    X = P.select(feats).to_numpy().astype(np.float32)
    y = P["label"].to_numpy()
    fwd = P["fwd"].to_numpy()
    score = np.full(len(y), np.nan)
    for fold in walk_forward(days, FIRST_TEST, embargo_h=HORIZON * 24):
        tr = fold.train & np.isfinite(fwd)
        order = np.argsort(days[tr], kind="stable")
        _, group = np.unique(days[tr][order], return_counts=True)
        m = lgb.LGBMRanker(**PARAMS).fit(X[tr][order], y[tr][order].astype(np.int32), group=group)
        score[fold.test] = m.predict(X[fold.test])
    return score


def run_variants(P: pl.DataFrame, variants: dict[str, list[str]], workers: int = 4) -> dict[str, np.ndarray]:
    path = CACHE / "m2_v3_ranked.parquet"
    P.write_parquet(path)
    out = {}
    todo = {}
    for k, feats in variants.items():
        f = CACHE / f"m2_v3_scores_{k}.npy"
        meta = CACHE / f"m2_v3_scores_{k}.json"
        if f.exists() and meta.exists() and json.loads(meta.read_text()) == {"feats": feats, "rows": P.height}:
            out[k] = np.load(f)
        else:
            todo[k] = feats
    # Threads, not processes: LightGBM trains outside the GIL, and a process pool
    # cannot start from a job without a console on Windows.
    with ThreadPoolExecutor(workers) as ex:
        futs = {k: ex.submit(walk, str(path), feats) for k, feats in todo.items()}
        for k, fu in futs.items():
            out[k] = fu.result()
            np.save(CACHE / f"m2_v3_scores_{k}.npy", out[k])
            (CACHE / f"m2_v3_scores_{k}.json").write_text(json.dumps({"feats": todo[k], "rows": P.height}))
            print(f"  variant {k} done", flush=True)
    return out


# ---------------------------------------------------------------- scoring

def nw_t(x: np.ndarray, lag: int = NW_LAG) -> float:
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    n = len(x)
    if n < 3:
        return float("nan")
    e = x - x.mean()
    v = float(e @ e) / n
    for k in range(1, min(lag, n - 1) + 1):
        v += 2 * (1 - k / (lag + 1)) * float(e[k:] @ e[:-k]) / n
    return float(x.mean() / math.sqrt(v / n)) if v > 0 else float("nan")


def pct_in_day(day: np.ndarray, x: np.ndarray) -> np.ndarray:
    df = pl.DataFrame({"d": day, "x": x})
    return df.select(((pl.col("x").rank("average").over("d") - 1) / (pl.len().over("d") - 1).clip(1))
                     .alias("p"))["p"].to_numpy()


def daily_ic(day: np.ndarray, score: np.ndarray, fwd: np.ndarray, mask: np.ndarray, min_n: int = 20) -> pl.DataFrame:
    ok = mask & np.isfinite(score) & np.isfinite(fwd)
    df = pl.DataFrame({"day": day[ok], "s": score[ok], "f": fwd[ok]})
    return (df.group_by("day").agg(ic=pl.corr("s", "f", method="spearman"), n=pl.len())
            .filter(pl.col("n") >= min_n).drop("n").sort("day"))


def year_of(day_us: np.ndarray) -> np.ndarray:
    return np.array([datetime.fromtimestamp(d / 1e6, timezone.utc).year for d in day_us])


def compare(a: pl.DataFrame, b: pl.DataFrame, lo: int, hi: int | None = None) -> dict:
    """Mean IC of a and b on their common days in [lo, hi), the paired difference's NW t, by year."""
    j = a.join(b, on="day", suffix="_b").filter(pl.col("day") >= lo)
    if hi is not None:
        j = j.filter(pl.col("day") < hi)
    j = j.drop_nans().drop_nulls()
    if j.is_empty():
        return {"days": 0}
    d = j["ic"].to_numpy() - j["ic_b"].to_numpy()
    yr = year_of(j["day"].to_numpy())
    by = {int(y): float(d[yr == y].mean()) for y in np.unique(yr)}
    return {"days": j.height, "ic": float(j["ic"].mean()), "ic_base": float(j["ic_b"].mean()),
            "diff": float(d.mean()), "t": nw_t(d), "by_year": by,
            "years_better": int(sum(by.get(y, -1) > 0 for y in YEARS))}


def passes(c: dict) -> bool:
    return bool(c.get("days") and c["diff"] > 0 and c["t"] > PASS_T and c["years_better"] >= 2)


def alpaca_mask(sym: np.ndarray, coins=universe.ALPACA) -> np.ndarray:
    s = set(f"{c}USDT" for c in coins)
    return np.array([x in s for x in sym])


def tail_stats(day, score, fwd, mask) -> dict:
    """Among the masked coins: top third minus the rest and bottom decile minus the day's mean (7-day)."""
    ok = mask & np.isfinite(score) & np.isfinite(fwd)
    df = pl.DataFrame({"d": day[ok], "s": score[ok], "f": np.expm1(fwd[ok])}).filter(pl.len().over("d") >= MIN_ALPACA)
    df = df.with_columns(p=(pl.col("s").rank("average").over("d") - 1) / (pl.len().over("d") - 1),
                         m=pl.col("f").mean().over("d"))
    g = df.group_by("d").agg(top=pl.col("f").filter(pl.col("p") >= 2 / 3).mean(),
                             rest=pl.col("f").filter(pl.col("p") < 2 / 3).mean(),
                             bot=(pl.col("f") - pl.col("m")).filter(pl.col("p") < 0.1).mean())
    return {"top_third_minus_rest": float((g["top"] - g["rest"]).mean()), "bottom_decile_rel": float(g["bot"].mean())}


# ---------------------------------------------------------------- the study

def main() -> None:
    t0 = time.time()
    refresh = "--refresh" in sys.argv
    raw = build_raw_v3(refresh)
    all_feats = v3_features(GROUPS)
    P = rank_v3(raw, all_feats)
    print(f"panel {P.height:,} coin-days, {P['symbol'].n_unique()} coins", flush=True)
    variants = {"v2": V2, "v3": all_feats}
    for g in GROUPS:
        variants[f"v3-{g}"] = v3_features([h for h in GROUPS if h != g])
    S = run_variants(P, variants)
    day, fwd, sym = P["day"].to_numpy(), P["fwd"].to_numpy(), P["symbol"].to_numpy()
    every = np.ones(P.height, dtype=bool)
    ics = {k: daily_ic(day, s, fwd, every) for k, s in S.items()}
    sel = {k: float(v.filter((pl.col("day") >= SEL[0]) & (pl.col("day") < SEL[1]))["ic"].mean()) for k, v in ics.items()}
    keep = [g for g in GROUPS if sel["v3"] - sel[f"v3-{g}"] > 0]
    if not keep:
        final = None
    elif len(keep) == len(GROUPS):
        final = "v3"
    else:
        final = "v3[" + "".join(keep) + "]"
        if final not in S:
            S.update(run_variants(P, {final: v3_features(keep)}))
            ics[final] = daily_ic(day, S[final], fwd, every)
            sel[final] = float(ics[final].filter((pl.col("day") >= SEL[0]) & (pl.col("day") < SEL[1]))["ic"].mean())
    res = {"panel_rows": P.height, "coins": int(P["symbol"].n_unique()), "selection_ic": sel, "kept_groups": keep,
           "final": final, "groups": GROUPS}
    alp = alpaca_mask(sym)
    alp15 = alpaca_mask(sym, universe.ALPACA15)
    lowvol = 1 - P["vol28"].to_numpy()  # vol28 is a within-day rank: low vol ranks high
    rows = []
    for k, s in S.items():
        a = daily_ic(day, s, fwd, alp, MIN_ALPACA)
        a15 = daily_ic(day, s, fwd, alp15, MIN_ALPACA)
        ens = daily_ic(day, (pct_in_day(day, np.where(np.isfinite(s), s, np.nan)) + lowvol) / 2, fwd, every)
        rows.append({"variant": k, "ic_sel": sel.get(k),
                     "ic_oos": float(ics[k].filter(pl.col("day") >= JUDGE_FROM)["ic"].mean()),
                     "ic_alpaca": float(a.filter(pl.col("day") >= JUDGE_FROM)["ic"].mean()),
                     "ic_alpaca15": float(a15.filter(pl.col("day") >= JUDGE_FROM)["ic"].mean()),
                     "ic_lowvol_ens": float(ens.filter(pl.col("day") >= JUDGE_FROM)["ic"].mean()),
                     **tail_stats(day[day >= JUDGE_FROM], s[day >= JUDGE_FROM], fwd[day >= JUDGE_FROM],
                                  alp[day >= JUDGE_FROM])})
    res["variants"] = rows
    if final:
        sf, s2 = S[final], S["v2"]
        tests = {
            "H1 whole universe": compare(ics[final], ics["v2"], JUDGE_FROM),
            "H2 Alpaca": compare(daily_ic(day, sf, fwd, alp, MIN_ALPACA), daily_ic(day, s2, fwd, alp, MIN_ALPACA),
                                 JUDGE_FROM),
            "H3 with low vol": compare(
                daily_ic(day, (pct_in_day(day, sf) + lowvol) / 2, fwd, every),
                daily_ic(day, (pct_in_day(day, s2) + lowvol) / 2, fwd, every), JUDGE_FROM),
        }
        for v in tests.values():
            v["passes"] = passes(v)
        res["tests"] = tests
        res["alpaca15"] = compare(daily_ic(day, sf, fwd, alp15, MIN_ALPACA), daily_ic(day, s2, fwd, alp15, MIN_ALPACA),
                                  JUDGE_FROM)
        res["shadow"] = bool(tests["H1 whole universe"]["passes"] or tests["H2 Alpaca"]["passes"])
        # IC per quarter from 2024, final and v2.
        q = []
        for k in ("v2", final):
            x = ics[k].filter(pl.col("day") >= JUDGE_FROM).with_columns(
                q=pl.from_epoch("day", time_unit="us").dt.year().cast(pl.Utf8) + "Q"
                + pl.from_epoch("day", time_unit="us").dt.quarter().cast(pl.Utf8))
            q.append(x.group_by("q").agg(pl.col("ic").mean().alias(k)))
        res["quarters"] = q[0].join(q[1], on="q").sort("q").to_dicts()
        res["importance"] = importance(P, v3_features(keep))
    else:
        res["shadow"] = False
    res["minutes"] = (time.time() - t0) / 60
    write(res)


def importance(P: pl.DataFrame, feats: list[str]) -> list[dict]:
    """Gain share of each input in one model fit on every labelled day before the last 7."""
    days, fwd = P["day"].to_numpy(), P["fwd"].to_numpy()
    tr = np.isfinite(fwd) & (days < days.max() - HORIZON * DAY_US)
    order = np.argsort(days[tr], kind="stable")
    _, group = np.unique(days[tr][order], return_counts=True)
    X = P.select(feats).to_numpy().astype(np.float32)
    m = lgb.LGBMRanker(**PARAMS).fit(X[tr][order], P["label"].to_numpy()[tr][order].astype(np.int32), group=group)
    g = m.booster_.feature_importance("gain")
    tot = float(g.sum()) or 1.0
    return sorted([{"feature": f, "gain_pct": float(100 * v / tot)} for f, v in zip(feats, g)], key=lambda r: -r["gain_pct"])


def _f(x, nd=3) -> str:
    return "n/a" if x is None or (isinstance(x, float) and not math.isfinite(x)) else f"{x:.{nd}f}"


def write(res: dict) -> None:
    md = [f"# M2 v3 (X11 a)\n\nGenerated by `python -m lab.experiments.m2_v3` from the pre-registration in "
          f"`model_upgrades_prereg.md`. {res['panel_rows']:,} coin-days, {res['coins']} coins (delisted included), "
          f"the same rows, parameters and quarterly walk-forward from 2022 as M2 v2. Selection 2022-23, judged "
          f"from 2024-01-01. Took {res['minutes']:.0f} min.\n\n",
          "## Variants (mean daily rank IC, 7-day label)\n\n"
          "| variant | 2022-23 (selection) | from 2024 | Alpaca 32 | Alpaca 15 | with low vol | Alpaca top third minus rest | Alpaca bottom decile |\n"
          "|---|---|---|---|---|---|---|---|\n"]
    for r in res["variants"]:
        md.append(f"| {r['variant']} | {_f(r['ic_sel'])} | {_f(r['ic_oos'])} | {_f(r['ic_alpaca'])} | "
                  f"{_f(r['ic_alpaca15'])} | {_f(r['ic_lowvol_ens'])} | {_f(100 * r['top_third_minus_rest'], 2)} % | "
                  f"{_f(100 * r['bottom_decile_rel'], 2)} % |\n")
    md.append(f"\nGroups kept by the selection rule (removing them lowers the 2022-23 IC): "
              f"{', '.join(res['kept_groups']) or 'none'}. Final: {res['final'] or 'none (v2 stays)'}.\n")
    if res.get("tests"):
        md.append("\n## The registered tests (from 2024, against v2)\n\n"
                  "| test | days | IC | v2 | difference | NW t | 2024 | 2025 | 2026 | passes |\n|---|---|---|---|---|---|---|---|---|---|\n")
        for k, v in list(res["tests"].items()) + [("Alpaca 15 (reported, not a test)", res["alpaca15"])]:
            by = v.get("by_year", {})
            md.append(f"| {k} | {v.get('days')} | {_f(v.get('ic'))} | {_f(v.get('ic_base'))} | {_f(v.get('diff'), 4)} | "
                      f"{_f(v.get('t'), 2)} | {_f(by.get(2024), 4)} | {_f(by.get(2025), 4)} | {_f(by.get(2026), 4)} | "
                      f"{'yes' if v.get('passes') else 'no' if 'passes' in v else ''} |\n")
        md.append("\n## IC per quarter from 2024\n\n| quarter | v2 | " + res["final"] + " |\n|---|---|---|\n")
        for q in res["quarters"]:
            md.append(f"| {q['q']} | {_f(q['v2'])} | {_f(q[res['final']])} |\n")
        md.append("\n## What the final model uses (gain, one fit on all labelled days)\n\n| feature | gain |\n|---|---|\n")
        for r in res["importance"]:
            md.append(f"| {r['feature']} | {r['gain_pct']:.1f} % |\n")
    md.append(f"\n**Verdict.** {'v3 runs in shadow next to v2 (H1 or H2 passed).' if res['shadow'] else 'v2 stays; v3 is not put in shadow.'}\n")
    report.write(NAME, "".join(md), res)


# ---------------------------------------------------------------- weekly shadow

def shadow_run(now_ms: int | None = None) -> dict:
    """Train v2 and the final v3 on all labelled history, write both rankings of the
    newest day down before the outcome, score every recorded day whose 7 days passed."""
    now = now_ms or int(time.time() * 1000)
    cfg = json.loads((Path(__file__).resolve().parents[2] / "results" / "m2_v3_final.json").read_text())
    feats3 = v3_features(cfg["groups"])
    raw = build_raw_v3(refresh=True)
    P = rank_v3(raw, feats3)
    days, fwd = P["day"].to_numpy(), P["fwd"].to_numpy()
    last = int(days.max())
    tr = np.isfinite(fwd) & (days < last - HORIZON * DAY_US)
    order = np.argsort(days[tr], kind="stable")
    _, group = np.unique(days[tr][order], return_counts=True)
    today = days == last
    sym = P["symbol"].to_numpy()[today]
    out = {}
    for k, feats in (("v2", V2), ("v3", feats3)):
        X = P.select(feats).to_numpy().astype(np.float32)
        m = lgb.LGBMRanker(**PARAMS).fit(X[tr][order], P["label"].to_numpy()[tr][order].astype(np.int32), group=group)
        out[k] = m.predict(X[today])
    SHADOW_DIR.mkdir(parents=True, exist_ok=True)
    f = SHADOW_DIR / "rankings.jsonl"
    have = set()
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            try:
                have.add(json.loads(line)["day_us"])
            except (ValueError, KeyError):
                continue
    if last not in have:
        with f.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps({"day_us": last, "recorded_ms": now, "groups": cfg["groups"],
                                 "scores": {s: [float(a), float(b)] for s, a, b in zip(sym, out["v2"], out["v3"])}}) + "\n")
    return shadow_score(P.select("day", "symbol", "fwd"))


def shadow_score(realised: pl.DataFrame) -> dict:
    f = SHADOW_DIR / "rankings.jsonl"
    rows = []
    for line in (f.read_text(encoding="utf-8").splitlines() if f.exists() else []):
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    fwd = {(int(d), s): float(v) for d, s, v in realised.iter_rows() if v is not None and math.isfinite(v)}
    alp = {f"{c}USDT" for c in universe.ALPACA}
    weeks = []
    for r in rows:
        syms = [s for s in r["scores"] if (r["day_us"], s) in fwd]
        if len(syms) < 20:
            continue
        y = np.array([fwd[(r["day_us"], s)] for s in syms])
        a = np.array([r["scores"][s][0] for s in syms])
        b = np.array([r["scores"][s][1] for s in syms])
        m = np.array([s in alp for s in syms])

        def ic(x, mk):
            if mk.sum() < MIN_ALPACA:
                return None
            return float(pl.DataFrame({"x": x[mk], "y": y[mk]}).select(pl.corr("x", "y", method="spearman")).item())
        weeks.append({"day": datetime.fromtimestamp(r["day_us"] / 1e6, timezone.utc).strftime("%Y-%m-%d"),
                      "coins": len(syms), "ic_v2": ic(a, np.ones(len(syms), bool)), "ic_v3": ic(b, np.ones(len(syms), bool)),
                      "ic_v2_alpaca": ic(a, m), "ic_v3_alpaca": ic(b, m)})
    out = {"what": "rank IC on the realised 7-day return, M2 v2 against M2 v3, written before the outcome",
           "recorded": len(rows), "scored": len(weeks), "weeks": weeks}
    if weeks:
        for k in ("ic_v2", "ic_v3", "ic_v2_alpaca", "ic_v3_alpaca"):
            v = [w[k] for w in weeks if w[k] is not None]
            out[f"mean_{k}"] = float(np.mean(v)) if v else None
    d = np.array([w["ic_v3"] - w["ic_v2"] for w in weeks if w["ic_v3"] is not None and w["ic_v2"] is not None])
    t = float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))) if len(d) > 2 and d.std(ddof=1) > 0 else None
    out["t_v3_minus_v2"] = t
    out["verdict"] = (f"Too early: {len(d)} scored weeks of {SHADOW_WEEKS}." if len(d) < SHADOW_WEEKS else
                      "v3 passes its forward test." if d.mean() > 0 and (t or 0) > SHADOW_T else
                      "v3 fails its forward test: v2 stays.")
    (SHADOW_DIR / "scores.json").write_text(json.dumps(out, indent=1), encoding="utf-8", newline="\n")
    return out


if __name__ == "__main__":
    if "--shadow" in sys.argv:
        print(json.dumps({k: v for k, v in shadow_run().items() if k != "weeks"}))
    else:
        main()
