"""D4 first study of the DexScreener archive: survival by launchpad and paid status, and whether a
snapshot feature at age 1 h predicts survival or a 2x by age 24 h after realistic costs at 40 EUR.
Paper only; nothing here trades.

    python -m lab.experiments.dexscreener_d4                     derived tables + <write root>/reports/dexscreener/latest.md
    python -m lab.experiments.dexscreener_d4 --out results/dexscreener_d4.md   the same text into a file

Two sources:

  archive   lab.collect.dexscreener (every 2 min while a pair is young), through
            lab.collect.dexscreener_derived: pair outcomes at 1 h, 1 d, 7 d, point in time.
  trending  <data>/trending/snapshots (lab.ops.trending, since 2026-10-15, every 15 minutes): the
            top boosted tokens with price, liquidity and age. A token is only in it while it is in
            the top boosted list, so a token that left the list has no known outcome; results are
            given both ways (left = dead and left = excluded) and the exit of a trade is the 24 h
            price or, for a token that left, its last listed price (optimistic) or nothing (-100 %).

Costs of a 40 EUR trade (EURUSD fixed at EUR_USD): the pool fee a side by dex (PumpSwap 1.25 %,
as lab.paper.pumpfun), the constant-product price impact of the stake against half the pool's
liquidity on the way in and on the way out, 0.002 SOL network fee a transaction, and SLIP a side for
slippage and sandwiches. A rug (liquidity pulled by more than 90 %) without an exit price is a total
loss; with one, the exit price already holds the fall.

Prediction: every feature at age 1 h is ranked against each label on the earlier 60 % of tokens
(by first seen), its direction fixed there, then scored on the later 40 % by AUC; every feature and
label is one trial and the bar is Bonferroni over all of them (two-sided 5 %). The best training
feature's top third is then bought on the later 40 % and compared with buying every token.
"""

from __future__ import annotations

import argparse
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import polars as pl

from ..collect import dexscreener as ds
from ..collect import dexscreener_derived as dd
from ..data import ROOT, WRITE_ROOT
from ..paper.pumpfun import amm_buy, amm_sell

STAKE_EUR = 40.0
EUR_USD = 1.16
TX_SOL = 0.002
SLIP = 0.01
POOL_FEES = {"pumpswap": 0.0125, "pumpfun": 0.0125, "raydium": 0.0025, "meteora": 0.01, "meteoradbc": 0.01,
             "orca": 0.003, "uniswap": 0.003, "pancakeswap": 0.0025, "aerodrome": 0.003}
DEFAULT_FEE = 0.01
SOL_USD_DEFAULT = 150.0
TRAIN = 0.6
MIN_TOKENS = 30
H = ds.HOUR_MS


def pool_fee(dex: str | None) -> float:
    return POOL_FEES.get(dex or "", DEFAULT_FEE)


def net_multiple(p_in: float | None, liq_in: float | None, p_out: float | None, liq_out: float | None,
                 dex: str | None, sol_usd: float = SOL_USD_DEFAULT, rug: bool = False,
                 stake_eur: float = STAKE_EUR) -> float | None:
    """End value over stake of one paper round trip; 0 for a rug without an exit price, None without prices."""
    if not p_out or p_out <= 0:
        return 0.0 if rug else None
    if not p_in or p_in <= 0:
        return None
    usd = stake_eur * EUR_USD
    fee = pool_fee(dex)
    tx = TX_SOL * sol_usd
    q_in = (liq_in or 0) / 2 or 1e12                         # no liquidity figure (a curve): no impact modelled
    q_out = (liq_out or 0) / 2 or 1e12
    tokens = amm_buy((usd - tx) * (1 - SLIP), q_in, p_in, fee)
    back = amm_sell(tokens, q_out, p_out, fee) * (1 - SLIP) - tx
    return max(0.0, back) / usd


def auc(score: np.ndarray, label: np.ndarray) -> float | None:
    """Mann-Whitney AUC; None without both classes."""
    ok = ~np.isnan(score)
    score, label = score[ok], label[ok].astype(bool)
    n1, n0 = int(label.sum()), int((~label).sum())
    if n1 == 0 or n0 == 0:
        return None
    ranks = pl.Series(score).rank("average").to_numpy()
    return float((ranks[label].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def auc_p(a: float, n1: int, n0: int) -> float:
    """Two-sided normal p of an AUC against 0.5 (Hanley and McNeil variance under the null)."""
    if n1 == 0 or n0 == 0:
        return 1.0
    se = math.sqrt((n1 + n0 + 1) / (12 * n1 * n0))
    return math.erfc(abs(a - 0.5) / se / math.sqrt(2))


# ---------------------------------------------------------------- trending: top boosted tokens

def trending_frame(root: Path | None = None) -> pl.DataFrame:
    files = sorted(((root or ROOT) / "trending" / "snapshots").glob("date=*/*.parquet"))
    if not files:
        return pl.DataFrame()
    cols = ["ts_ms", "source", "chain", "address", "dex", "pair_url", "price_usd", "liquidity_usd", "fdv", "age_h",
            "change_h1", "volume_h24", "buys_h24", "sells_h24", "boost"]
    frames = []
    for f in files:
        d = pl.read_parquet(f)
        if "source" in d.columns:
            frames.append(d.select([c for c in cols if c in d.columns]))
    d = pl.concat(frames, how="diagonal_relaxed")
    return d.filter((pl.col("source") == "boosted") & pl.col("address").is_not_null() & pl.col("age_h").is_not_null())


def trending_tokens(t: pl.DataFrame, floor: float) -> pl.DataFrame:
    """One row a token first listed by age 1.5 h: features at the listing nearest 1 h, the outcome at 24 h."""
    if t.is_empty():
        return pl.DataFrame()
    t = t.with_columns((pl.col("ts_ms") - (pl.col("age_h") * H).cast(pl.Int64)).alias("created"))
    if "pair_url" in t.columns:                                     # follow the pair listed at 1 h, not the best of the day
        p1 = (t.filter(pl.col("age_h").is_between(0.5, 1.5)).with_columns((pl.col("age_h") - 1).abs().alias("_d"))
              .sort("_d").unique(["chain", "address"], keep="first").select("chain", "address", pl.col("pair_url").alias("_p1")))
        t = (t.join(p1, on=["chain", "address"], how="left")
             .filter(pl.col("_p1").is_null() | (pl.col("pair_url") == pl.col("_p1")) | pl.col("pair_url").is_null()).drop("_p1"))
    first = t.group_by(["chain", "address"]).agg(pl.col("age_h").min().alias("age0"), pl.col("ts_ms").max().alias("last_ts"),
                                                 pl.col("ts_ms").min().alias("first_ts"))
    early = first.filter(pl.col("age0") <= 1.5)
    at1 = (t.filter(pl.col("age_h").is_between(0.5, 1.5)).with_columns((pl.col("age_h") - 1).abs().alias("_d"))
           .sort("_d").unique(["chain", "address"], keep="first").drop("_d"))
    at24 = (t.filter(pl.col("age_h").is_between(20, 28)).with_columns((pl.col("age_h") - 24).abs().alias("_d"))
            .sort("_d").unique(["chain", "address"], keep="first")
            .select("chain", "address", pl.col("price_usd").alias("p24"), pl.col("liquidity_usd").alias("liq24"),
                    (pl.col("buys_h24").fill_null(0) + pl.col("sells_h24").fill_null(0)).alias("trades24"),
                    pl.lit(True).alias("seen24")))
    upto = (t.join(at1.select("chain", "address", pl.col("ts_ms").alias("t1")), on=["chain", "address"])
            .filter(pl.col("ts_ms") >= pl.col("t1")).sort("ts_ms")
            .group_by(["chain", "address"]).agg(pl.col("price_usd").last().alias("p_last"),
                                                pl.col("liquidity_usd").last().alias("liq_last"),
                                                pl.col("liquidity_usd").max().alias("liq_max"),
                                                pl.col("liquidity_usd").min().alias("liq_min"),
                                                pl.col("age_h").max().alias("age_last")))
    d = (early.join(at1, on=["chain", "address"]).join(at24, on=["chain", "address"], how="left")
         .join(upto, on=["chain", "address"], how="left"))
    newest = t["ts_ms"].max()
    d = d.filter(pl.col("created") + 28 * H <= newest)             # 24 h could have been seen
    d = d.with_columns(
        pl.col("seen24").fill_null(False),
        ((pl.col("liq_max") >= floor) & (pl.col("liq_min") < (1 - ds.RUG_DROP) * pl.col("liq_max"))).fill_null(False).alias("rug"),
        pl.when(pl.col("liq24").is_not_null()).then(pl.col("liq24") >= floor)       # a curve has no liquidity figure
        .otherwise(pl.col("trades24") > 0).alias("alive24"))
    return d


# ---------------------------------------------------------------- features

def add_features(d: pl.DataFrame, liq: str, fdv: str, vol: str, buys: str, sells: str, chg: str, boost: str) -> pl.DataFrame:
    return d.with_columns(
        pl.col(liq).log10().alias("x_log_liq"), pl.col(fdv).log10().alias("x_log_fdv"),
        (pl.col(fdv) / pl.col(liq)).log10().alias("x_fdv_liq"),
        (pl.col(vol) / pl.col(liq)).alias("x_vol_liq"),
        (pl.col(buys) / (pl.col(buys) + pl.col(sells))).alias("x_buy_share"),
        (pl.col(buys) + pl.col(sells)).log1p().alias("x_log_trades"),
        pl.col(chg).alias("x_chg_h1"), pl.col(boost).cast(pl.Float64).alias("x_boost"))


FEATURES = ("x_log_liq", "x_log_fdv", "x_fdv_liq", "x_vol_liq", "x_buy_share", "x_log_trades", "x_chg_h1", "x_boost")


def predict(d: pl.DataFrame, labels: tuple[str, ...]) -> dict:
    """Direction on the earlier TRAIN share, AUC on the rest; Bonferroni over every feature and label."""
    d = d.sort("first_ts")
    n_train = int(len(d) * TRAIN)
    tr, te = d[:n_train], d[n_train:]
    feats = [f for f in FEATURES if f in d.columns and d[f].drop_nulls().n_unique() > 1]
    trials = len(feats) * len(labels)
    bar = 0.05 / max(1, trials)
    rows = []
    for lab in labels:
        for f in feats:
            a_tr = auc(tr[f].cast(pl.Float64).fill_null(np.nan).to_numpy(), tr[lab].fill_null(False).to_numpy())
            if a_tr is None:
                continue
            sign = 1.0 if a_tr >= 0.5 else -1.0
            y = te[lab].fill_null(False).to_numpy()
            a_te = auc(sign * te[f].cast(pl.Float64).fill_null(np.nan).to_numpy(), y)
            n1, n0 = int(y.sum()), int((~y.astype(bool)).sum())
            p = auc_p(a_te, n1, n0) if a_te is not None else 1.0
            rows.append({"label": lab, "feature": f, "train_auc": max(a_tr, 1 - a_tr), "sign": sign,
                         "test_auc": a_te, "p": p, "passes": p < bar and (a_te or 0) > 0.5, "n1": n1, "n0": n0})
    return {"rows": rows, "trials": trials, "bar": bar, "n_train": n_train, "n_test": len(te)}


def rule_book(d: pl.DataFrame, pred: dict, mult: str) -> dict | None:
    """The best training feature for `mult` > 1 (by train AUC), its top third bought on the test part."""
    rows = [r for r in pred["rows"] if r["label"] == "win"]
    if not rows:
        return None
    best = max(rows, key=lambda r: r["train_auc"])
    d = d.sort("first_ts")
    n = pred["n_train"]
    tr, te = d[:n], d[n:]
    s_tr = (best["sign"] * tr[best["feature"]].cast(pl.Float64)).drop_nulls()
    if s_tr.is_empty() or te.is_empty():
        return None
    cut = float(s_tr.quantile(2 / 3))
    pick = te.filter(best["sign"] * pl.col(best["feature"]) >= cut)
    allm = te[mult].drop_nulls()
    pm = pick[mult].drop_nulls()
    return {"feature": best["feature"], "sign": best["sign"], "cut": cut, "n_all": len(allm), "n_pick": len(pm),
            "mean_all": float(allm.mean()) if len(allm) else None, "mean_pick": float(pm.mean()) if len(pm) else None,
            "median_pick": float(pm.median()) if len(pm) else None, "median_all": float(allm.median()) if len(allm) else None}


# ---------------------------------------------------------------- report

def pct(a: int, b: int) -> str:
    return f"{a}/{b} ({100 * a / b:.0f} %)" if b else "0/0"


def fmt(x, nd: int = 2) -> str:
    return "n/a" if x is None or (isinstance(x, float) and not math.isfinite(x)) else f"{x:.{nd}f}"


def sol_usd_of(s: pl.DataFrame) -> float:
    if s.is_empty():
        return SOL_USD_DEFAULT
    x = s.filter((pl.col("quote_symbol") == "SOL") & (pl.col("price_native") > 0)).select(
        (pl.col("price_usd") / pl.col("price_native")).median()).item()
    return float(x) if x else SOL_USD_DEFAULT


def archive_section(out: dict, s: pl.DataFrame, root: Path | None) -> list[str]:
    o, L = out["outcomes"], []
    st = ds.load_state(root)
    disc = dd.table("discovery", ds.DISC_SCHEMA, root)
    if o.is_empty() or s.is_empty():
        return ["No archive yet: the collector has not written a snapshot."]
    t0, t1 = int(s["collected_at"].min()), int(s["collected_at"].max())
    L += [f"Collected {datetime.fromtimestamp(t0 / 1000, timezone.utc):%Y-%m-%d %H:%M} to "
          f"{datetime.fromtimestamp(t1 / 1000, timezone.utc):%Y-%m-%d %H:%M} UTC ({(t1 - t0) / H:.1f} h, "
          f"{s['collected_at'].n_unique()} runs that wrote snapshots): {s.height} snapshots of {o.height} pairs of "
          f"{o['token'].n_unique()} tokens; {st.get('runs', 0)} runs in all.", ""]
    if not disc.is_empty():
        src = (disc.with_columns(pl.col("source").str.replace(r"^search:.*", "search"))
               .group_by("source").agg(pl.col("token").n_unique().alias("tokens")).sort("tokens", descending=True))
        L.append("Tokens by discovery source: " + ", ".join(f"{r['source']} {r['tokens']}" for r in src.to_dicts()) + ".")
    by_dex = o.group_by("dex").agg(pl.len().alias("n")).sort("n", descending=True)
    L += ["Pairs by dex: " + ", ".join(f"{r['dex']} {r['n']}" for r in by_dex.to_dicts()) + ".", ""]
    early = o.filter(pl.col("first_age") <= dd.HORIZONS["1h"][2])
    L += ["Pairs the archive saw before age 90 minutes, still trading at age 1 h (liquidity at the floor and a "
          "trade in the hour), by dex and by paid status at 1 h:", "",
          "| group | pairs seen early | known at 1 h | trading at 1 h | known at 1 d | trading at 1 d | rugged |",
          "|---|---|---|---|---|---|---|"]
    for key in ("dex", "paid_1h"):
        g = early.group_by(key).agg(pl.len().alias("n"), *dd._share("trading_1h"), *dd._share("trading_1d"),
                                    pl.col("rugged").fill_null(False).sum().alias("rug")).sort("n", descending=True)
        for r in g.to_dicts():
            L.append(f"| {key} {r[key]} | {r['n']} | {r['known_1h']} | {pct(r['alive_1h'], r['known_1h'])} | "
                     f"{r['known_1d']} | {pct(r['alive_1d'], r['known_1d'])} | {r['rug']} |")
    paid = out["paid"]
    if not paid.is_empty():
        L += ["", "Paid status at 1 h (a boost or a paid profile by then, from the snapshot and the orders) and what "
              "followed, pairs seen before 90 minutes; price ratio from the 1 h to the 24 h snapshot, before costs:", "",
              "| paid at 1 h | pairs | trading at 1 d | trading at 7 d | rugged by 24 h | median ratio 24 h / 1 h | 2x |",
              "|---|---|---|---|---|---|---|"]
        for r in paid.to_dicts():
            L.append(f"| {r['paid_1h']} | {r['pairs']} | {pct(r['alive_1d'], r['known_1d'])} | "
                     f"{pct(r['alive_7d'], r['known_7d'])} | {r['rug_24h']} | {fmt(r['median_ratio_24h'])} | "
                     f"{pct(r['x2_24h'], r['known_ratio'])} |")
    tok = out["tokens"]
    if not tok.is_empty():
        g = tok.group_by("launchpad").agg(pl.len().alias("n"), *dd._share("trading_1h"), *dd._share("trading_1d")).sort("n", descending=True)
        L += ["", "Tokens by launchpad (pump.fun for a curve pair, a migration or a mint ending in pump, letsbonk for "
              "bonk, else the dex of a token's first pair; a token trades when any of its pairs does):", "",
              "| launchpad | tokens | trading at 1 h | trading at 1 d |", "|---|---|---|---|"]
        for r in g.to_dicts():
            L.append(f"| {r['launchpad']} | {r['n']} | {pct(r['alive_1h'], r['known_1h'])} | {pct(r['alive_1d'], r['known_1d'])} |")
    mig = out["migration"]
    if not mig.is_empty():
        n = mig.height
        other = mig.filter(pl.col("has_other_pool"))
        dexes: dict[str, int] = {}
        for x in other["other_dexes"].drop_nulls().to_list():
            for dx in x.split(","):
                dexes[dx] = dexes.get(dx, 0) + 1
        L += ["", f"pump.fun coins after migration: {n} with a PumpSwap pool in the archive, {other.height} of them also "
              f"on another dex ({', '.join(f'{k} {v}' for k, v in sorted(dexes.items(), key=lambda kv: -kv[1])) or 'none'}); "
              f"median PumpSwap share of their liquidity {fmt(mig['pumpswap_liq_share'].median())}."]
    return L


def trending_section(td: pl.DataFrame, floor: float, sol_usd: float) -> tuple[list[str], pl.DataFrame]:
    if td.is_empty():
        return ["The trending snapshots hold no boosted token first listed by age 1.5 h."], td
    td = td.with_columns(
        pl.struct(["price_usd", "liquidity_usd", "p24", "liq24", "dex", "rug"]).map_elements(
            lambda r: net_multiple(r["price_usd"], r["liquidity_usd"], r["p24"], r["liq24"], r["dex"], sol_usd, r["rug"]),
            return_dtype=pl.Float64).alias("m24"),
        pl.struct(["price_usd", "liquidity_usd", "p_last", "liq_last", "dex", "rug"]).map_elements(
            lambda r: net_multiple(r["price_usd"], r["liquidity_usd"], r["p_last"], r["liq_last"], r["dex"], sol_usd, r["rug"]),
            return_dtype=pl.Float64).alias("m_last"))
    td = td.with_columns(
        pl.when(pl.col("seen24")).then(pl.col("m24")).otherwise(pl.col("m_last")).alias("m_opt"),
        pl.when(pl.col("seen24") | pl.col("rug")).then(pl.col("m24")).otherwise(0.0).alias("m_pess"))
    td = td.with_columns((pl.col("m_opt") >= 2).alias("x2"), pl.col("alive24").fill_null(False).alias("alive24f"),
                         (pl.col("m_opt") > 1).alias("win"),
                         pl.when(pl.col("boost") >= 500).then(pl.lit("500+")).when(pl.col("boost") >= 100)
                         .then(pl.lit("100 to 499")).otherwise(pl.lit("under 100")).alias("boost_band"))
    n, seen = td.height, int(td["seen24"].sum())
    L = [f"{n} boosted tokens were first listed by age 1.5 h and could have been seen at 24 h; {seen} were still "
         f"listed at 20 to 28 h, {n - seen} had left the list (outcome unknown).", "",
         "| group | tokens | listed at 24 h | alive at 24 h (left = dead) | alive at 24 h (of listed) | rugged | "
         "2x net at 24 h (of listed) | mean net multiple (left = last price) | (left = 0) |",
         "|---|---|---|---|---|---|---|---|---|"]
    for key in ("all", "dex", "boost_band"):
        g = (td.with_columns(pl.lit("all").alias("all")) if key == "all" else td).group_by(key).agg(
            pl.len().alias("n"), pl.col("seen24").sum().alias("seen"), pl.col("alive24f").sum().alias("alive"),
            pl.col("rug").sum().alias("rug"), (pl.col("x2") & pl.col("seen24")).sum().alias("x2"),
            pl.col("m_opt").mean().alias("mo"), pl.col("m_pess").mean().alias("mp")).sort("n", descending=True)
        for r in g.to_dicts():
            L.append(f"| {key} {r[key]} | {r['n']} | {r['seen']} | {pct(r['alive'], r['n'])} | {pct(r['alive'], r['seen'])} | "
                     f"{r['rug']} | {pct(r['x2'], r['seen'])} | {fmt(r['mo'])} | {fmt(r['mp'])} |")
    return L, td


def prediction_section(d: pl.DataFrame, name: str) -> list[str]:
    if d.height < MIN_TOKENS:
        return [f"{name}: {d.height} tokens with a 1 h snapshot and a 24 h outcome, fewer than {MIN_TOKENS}; no test."]
    pred = predict(d, ("alive24f", "x2", "win"))
    L = [f"{name}: {d.height} tokens, the earlier {pred['n_train']} to fix each feature's direction, the later "
         f"{pred['n_test']} to score it. {pred['trials']} trials, so the bar is p < {pred['bar']:.4f}.", "",
         "| label | feature | train AUC | test AUC | positives in test | p | passes |", "|---|---|---|---|---|---|---|"]
    for r in sorted(pred["rows"], key=lambda r: (r["label"], -(r["test_auc"] or 0))):
        L.append(f"| {r['label']} | {r['feature'][2:]}{' (low)' if r['sign'] < 0 else ''} | {fmt(r['train_auc'])} | "
                 f"{fmt(r['test_auc'])} | {r['n1']}/{r['n1'] + r['n0']} | {fmt(r['p'], 3)} | {'yes' if r['passes'] else 'no'} |")
    passed = [r for r in pred["rows"] if r["passes"]]
    L += ["", f"Passing the bar: {', '.join(r['feature'][2:] + ' for ' + r['label'] for r in passed) if passed else 'none'}."]
    b = rule_book(d, pred, "m")
    if b:
        L.append(f"Paper rule on the later part: buy at 1 h when {b['feature'][2:]} is "
                 f"{'at or above' if b['sign'] > 0 else 'at or below'} {fmt(b['sign'] * b['cut'], 3)} (train's top third), "
                 f"sell at 24 h: {b['n_pick']} trades, mean net multiple {fmt(b['mean_pick'])} (median "
                 f"{fmt(b['median_pick'])}) against {fmt(b['mean_all'])} (median {fmt(b['median_all'])}) for all "
                 f"{b['n_all']}.")
    return L


def report(root: Path | None = None, trend_root: Path | None = None, now: int | None = None) -> str:
    now = now or int(time.time() * 1000)
    floor = float(ds.config()["liq_floor_usd"])
    out = dd.build(root, now, floor, write=True)
    s = dd.snapshots(root, since_ms=now - 30 * ds.DAY_MS, cols=dd.COLS, pairs=dd.pairs_table(root))
    sol = sol_usd_of(s)
    L = ["# D4: DexScreener archive, first study", "",
         f"Generated {datetime.fromtimestamp(now / 1000, timezone.utc):%Y-%m-%d %H:%M} UTC by "
         "`python -m lab.experiments.dexscreener_d4`. Paper only, nothing live. Costs: a "
         f"{STAKE_EUR:.0f} EUR stake at {EUR_USD} USD, pool fee by dex (PumpSwap {POOL_FEES['pumpswap'] * 100:.2f} % a side), "
         f"constant-product impact against half the liquidity, {TX_SOL} SOL a transaction at {sol:.0f} USD a SOL, "
         f"{SLIP * 100:.0f} % slippage a side; a rug is a total loss. Liquidity floor {floor:.0f} USD.", "",
         "## 1. The archive", ""]
    L += archive_section(out, s, root)
    o = out["outcomes"]
    L += ["", "## 2. Top boosted tokens in the trending snapshots (since 2026-10-15)", ""]
    tl, td = trending_section(trending_tokens(trending_frame(trend_root), floor), floor, sol)
    L += tl
    L += ["", "## 3. Does a feature at age 1 h predict survival or a 2x by 24 h?", "",
          "Labels: alive24f (liquidity at the floor at 24 h), x2 (a net multiple of 2 or more after costs), win (a net "
          "multiple above 1). Trending: only tokens still listed at 20 to 28 h, since a token that left the list has "
          "no outcome (leaving it is mostly the boost running out, so counting it as dead would teach the boost "
          "amount, not survival). Archive: a pair gone from DexScreener by 24 h is a total loss. Features at "
          "the snapshot nearest 1 h: log liquidity, log FDV, FDV over liquidity, volume over liquidity, buy share of "
          "trades, log trades, price change in the hour, boost amount.", ""]
    if not td.is_empty():
        d = add_features(td.filter(pl.col("seen24")).with_columns(pl.col("m24").alias("m")),
                         "liquidity_usd", "fdv", "volume_h24", "buys_h24", "sells_h24", "change_h1", "boost")
        L += prediction_section(d, "Trending (top boosted)")
    if not o.is_empty():
        ao = o.filter(pl.col("trading_1d").is_not_null() & pl.col("price_1h").is_not_null())
        if not ao.is_empty():
            ao = ao.with_columns(
                pl.struct(["price_1h", "f_liq", "price_1d", "liq_1d", "dex", "rug_24h"]).map_elements(
                    lambda r: net_multiple(r["price_1h"], r["f_liq"], r["price_1d"], r["liq_1d"], r["dex"], sol, r["rug_24h"]),
                    return_dtype=pl.Float64).alias("m_opt"))
            ao = ao.with_columns(pl.col("m_opt").fill_null(0.0).alias("m"), pl.col("trading_1d").alias("alive24f"))
            ao = ao.with_columns((pl.col("m") >= 2).alias("x2"), (pl.col("m") > 1).alias("win"),
                                 pl.col("first_seen").alias("first_ts"))
            ao = add_features(ao, "f_liq", "f_fdv", "f_vol_h1", "f_buys_h1", "f_sells_h1", "f_chg_h1", "f_boosts")
        L += [""] + prediction_section(ao, "Archive (every pair seen before 1 h)")
    return "\n".join(L) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", help="write the report here instead of <write root>/reports/dexscreener/latest.md")
    a = ap.parse_args(argv)
    text = report()
    path = Path(a.out) if a.out else WRITE_ROOT / "reports" / "dexscreener" / "latest.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
