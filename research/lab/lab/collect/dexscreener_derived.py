"""Derived tables of the DexScreener archive (D4), for the studies (there is no lab.features yet).

    python -m lab.collect.dexscreener_derived        rebuild <write root>/dexscreener/derived/*.parquet

Read from the archive lab.collect.dexscreener writes (snapshots, pairs, orders, discovery), point
in time: a value "at age 1 h" is the snapshot nearest to 1 h after the pair was created, inside a
window (50 to 90 minutes), never a later one.

  outcomes.parquet   one row a pair: dex, launchpad (pump.fun for a token
                     with a curve pair, a migration or a mint ending in pump, letsbonk for one ending in
                     bonk, else the dex of its token's first pair), the snapshot
                     at 1 h (features), trading at 1 h, 1 d, 7 d (null when not yet that old, when the
                     archive found it too late, or when the collector has a gap there), rugged (its
                     liquidity fell more than 90 % below its most), price at 1 h and 24 h, the highest
                     snapshot price in between, paid signs at 1 h and ever
  survival.parquet   per chain, day created and dex (and "all"): pairs found, and of those with a
                     known state how many still trade after 1 h, 1 d, 7 d; rugs
  tokens.parquet     one row a token: launchpad, trading at 1 h, 1 d, 7 d on any of its pairs
  paid.parquet       survival, rugs and returns by paid status at 1 h (none, profile, boost, both)
  migration.parquet  pump.fun coins after migration: their pools on other dexes, when the first one
                     came, PumpSwap's share of the liquidity, survival with and without another pool

"Trading" is: liquidity at the floor or above (or, without a liquidity figure, trades in 24 h)
and at least one trade in the hour before the snapshot.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import polars as pl

from . import dexscreener as ds

H, D = ds.HOUR_MS, ds.DAY_MS
# horizon: (target age, window low, window high)
HORIZONS = {"1h": (H, 50 * ds.MIN_MS, 90 * ds.MIN_MS), "1d": (D, 22 * H, 30 * H), "7d": (7 * D, 156 * H, 192 * H)}
FEATURE_AGE = "1h"
MAX_CREATED_DAYS = 30                         # outcomes only for pairs created in the last 30 days
MAX_AGE_MS = HORIZONS["7d"][2]                # no snapshot past the last window is read
COLS = ["collected_at", "chain", "pair", "token", "dex", "quote_symbol", "price_usd", "price_native", "liq_usd",
        "fdv", "mcap", "boosts_active", "has_profile", "n_websites", "n_socials", "vol_m5", "vol_h1", "chg_m5",
        "chg_h1", "buys_h1", "sells_h1", "buys_h24", "sells_h24"]


def snapshots(root: Path | None = None, since_ms: int | None = None, cols: list[str] | None = None,
              pairs: pl.DataFrame | None = None) -> pl.DataFrame:
    """Snapshot rows since since_ms; with `pairs`, only those of a pair younger than 8 days then (less memory)."""
    files = sorted(ds.base(root).glob("snapshots/chain=*/date=*/*.parquet"))
    schema = {k: v for k, v in ds.SNAP_SCHEMA.items() if cols is None or k in cols}
    if not files:
        return pl.DataFrame(schema=schema)
    lf = pl.concat([pl.scan_parquet(f).cast(ds.SNAP_SCHEMA, strict=False).select(list(schema)) for f in files],
                   how="diagonal_relaxed")
    if since_ms:
        lf = lf.filter(pl.col("collected_at") >= since_ms)
    if pairs is not None:
        born = pairs.lazy().select("chain", "pair", pl.coalesce("created_at", "first_seen").alias("_born"))
        lf = (lf.join(born, on=["chain", "pair"]).filter(pl.col("collected_at") - pl.col("_born") <= MAX_AGE_MS)
              .drop("_born"))
    return lf.collect()


def table(name: str, schema: dict, root: Path | None = None) -> pl.DataFrame:
    files = sorted(ds.base(root).glob(f"{name}/chain=*/date=*/*.parquet"))
    if not files:
        return pl.DataFrame(schema=schema)
    return pl.concat([pl.read_parquet(f).cast(schema, strict=False) for f in files], how="diagonal_relaxed")


def pairs_table(root: Path | None = None) -> pl.DataFrame:
    path = ds.base(root) / "pairs.parquet"
    return pl.read_parquet(path) if path.exists() else pl.DataFrame(schema=ds.PAIR_SCHEMA)


def trading_expr(floor: float) -> pl.Expr:
    traded24 = (pl.col("buys_h24").fill_null(0) + pl.col("sells_h24").fill_null(0)) > 0
    alive = pl.when(pl.col("liq_usd").is_not_null()).then(pl.col("liq_usd") >= floor).otherwise(traded24)
    return alive & ((pl.col("buys_h1").fill_null(0) + pl.col("sells_h1").fill_null(0)) > 0)


def at_age(s: pl.DataFrame, horizon: str) -> pl.DataFrame:
    """The snapshot nearest to the horizon's age inside its window, one a pair."""
    x, lo, hi = HORIZONS[horizon]
    return (s.filter(pl.col("age").is_between(lo, hi))
            .with_columns((pl.col("age") - x).abs().alias("_d"))
            .sort(["chain", "pair", "_d"]).unique(["chain", "pair"], keep="first").drop("_d"))


def outcomes(s: pl.DataFrame, pairs: pl.DataFrame, orders: pl.DataFrame, now: int,
             floor: float = 1000.0, disc: pl.DataFrame | None = None) -> pl.DataFrame:
    if s.is_empty() or pairs.is_empty():
        return pl.DataFrame()
    p = pairs.select("chain", "pair", "token", "dex", "first_seen", "last_seen", "rugged", "rug_at",
                     pl.coalesce("created_at", "first_seen").alias("created"))
    p = p.filter(pl.col("created") >= now - MAX_CREATED_DAYS * D)
    s = (s.join(p.select("chain", "pair", "created"), on=["chain", "pair"])
         .with_columns((pl.col("collected_at") - pl.col("created")).alias("age"), trading_expr(floor).alias("trading")))
    first = s.group_by(["chain", "pair"]).agg(pl.col("age").min().alias("first_age"),
                                              (pl.col("boosts_active") > 0).any().alias("boosted_ever"),
                                              pl.col("has_profile").any().alias("profile_ever"))
    out = p.join(first, on=["chain", "pair"], how="left")
    for hz, (x, lo, hi) in HORIZONS.items():
        snap = at_age(s, hz).select("chain", "pair", pl.col("trading").alias(f"trading_{hz}"),
                                    pl.col("price_usd").alias(f"price_{hz}"), pl.col("liq_usd").alias(f"liq_{hz}"))
        out = out.join(snap, on=["chain", "pair"], how="left")
        known = pl.col(f"trading_{hz}")
        gone = pl.col("last_seen") < pl.col("created") + lo           # no longer in DexScreener's answers
        out = out.with_columns(
            pl.when(known.is_not_null()).then(known)
            .when(now - pl.col("created") < hi).then(None)             # not that old yet
            .when(pl.col("first_age") > x).then(None)                  # found too late
            .when(gone).then(False)
            .otherwise(None).alias(f"trading_{hz}"))
    feat = at_age(s, FEATURE_AGE).select(
        "chain", "pair", pl.col("liq_usd").alias("f_liq"), pl.col("fdv").alias("f_fdv"), pl.col("mcap").alias("f_mcap"),
        pl.col("vol_h1").alias("f_vol_h1"), pl.col("vol_m5").alias("f_vol_m5"),
        pl.col("buys_h1").alias("f_buys_h1"), pl.col("sells_h1").alias("f_sells_h1"),
        pl.col("chg_h1").alias("f_chg_h1"), pl.col("chg_m5").alias("f_chg_m5"),
        (pl.col("boosts_active") > 0).alias("f_boosted"), pl.col("boosts_active").alias("f_boosts"),
        pl.col("has_profile").alias("f_profile"), pl.col("n_socials").alias("f_socials"),
        pl.col("n_websites").alias("f_websites"), pl.col("quote_symbol").alias("quote_symbol"))
    out = out.join(feat, on=["chain", "pair"], how="left")
    mid = (s.filter(pl.col("age").is_between(H, HORIZONS["1d"][0]))
           .group_by(["chain", "pair"]).agg(pl.col("price_usd").max().alias("price_max_1h_24h")))
    out = out.join(mid, on=["chain", "pair"], how="left")
    paid = (orders.filter(pl.col("paid_at").is_not_null())
            .group_by(["chain", "token"]).agg(
                pl.col("paid_at").filter(pl.col("kind") == "boost").min().alias("boost_paid_at"),
                pl.col("paid_at").filter(pl.col("type") == "tokenProfile").min().alias("profile_paid_at"),
                pl.col("paid_at").filter(pl.col("type").is_in(["tokenAd", "trendingBarAd"])).min().alias("ad_paid_at")))
    out = out.join(paid, on=["chain", "token"], how="left")
    cut = pl.col("created") + H
    out = out.with_columns(
        (pl.col("f_boosted").fill_null(False) | (pl.col("boost_paid_at") <= cut).fill_null(False)).alias("boost_1h"),
        (pl.col("f_profile").fill_null(False) | (pl.col("profile_paid_at") <= cut).fill_null(False)).alias("profile_1h"),
        (pl.col("rugged").fill_null(False) & ((pl.col("rug_at") - pl.col("created")) <= D)).alias("rug_24h"))
    out = out.with_columns(
        pl.when(pl.col("boost_1h") & pl.col("profile_1h")).then(pl.lit("both"))
        .when(pl.col("boost_1h")).then(pl.lit("boost")).when(pl.col("profile_1h")).then(pl.lit("profile"))
        .otherwise(pl.lit("none")).alias("paid_1h"),
        (pl.col("price_1d") / pl.col("price_1h")).alias("ratio_24h"))
    migrated = (disc.filter(pl.col("source") == "pumpfun_migration")["token"].unique().to_list()
                if disc is not None and not disc.is_empty() else [])
    launch = (out.sort("created").group_by(["chain", "token"]).agg(
        pl.col("dex").first().alias("_first"), (pl.col("dex") == "pumpfun").any().alias("_curve")))
    launch = launch.with_columns(
        pl.when(pl.col("_curve") | pl.col("token").is_in(migrated) | pl.col("token").str.ends_with("pump"))
        .then(pl.lit("pump.fun")).when(pl.col("token").str.ends_with("bonk")).then(pl.lit("letsbonk"))
        .otherwise(pl.col("_first")).alias("launchpad")).drop("_first", "_curve")
    return out.join(launch, on=["chain", "token"], how="left")


def _share(col: str) -> list[pl.Expr]:
    return [pl.col(col).is_not_null().sum().alias(f"known_{col[8:]}"), pl.col(col).fill_null(False).sum().alias(f"alive_{col[8:]}")]


def survival(o: pl.DataFrame) -> pl.DataFrame:
    if o.is_empty():
        return pl.DataFrame()
    o = o.with_columns(pl.from_epoch("created", time_unit="ms").dt.strftime("%Y-%m-%d").alias("day"))
    aggs = [pl.len().alias("pairs"), *_share("trading_1h"), *_share("trading_1d"), *_share("trading_7d"),
            pl.col("rugged").fill_null(False).sum().alias("rugged")]
    by = o.group_by(["chain", "day", "dex"]).agg(aggs)
    al = o.group_by(["chain", "day"]).agg(aggs).with_columns(pl.lit("all").alias("dex")).select(by.columns)
    return pl.concat([by, al]).sort(["chain", "day", "dex"])


def token_survival(o: pl.DataFrame) -> pl.DataFrame:
    """A token trades at an age when any of its pairs does; unknown when none says yes and one is unknown."""
    if o.is_empty():
        return pl.DataFrame()
    aggs = [pl.col("launchpad").first(), pl.col("created").min(), pl.col("rugged").fill_null(False).all().alias("all_rugged")]
    for hz in HORIZONS:
        c = pl.col(f"trading_{hz}")
        aggs.append(pl.when(c.fill_null(False).any()).then(True).when(c.is_null().any()).then(None)
                    .otherwise(False).alias(f"trading_{hz}"))
    return o.group_by(["chain", "token"]).agg(aggs)


def paid_effect(o: pl.DataFrame) -> pl.DataFrame:
    """Pairs the archive saw before they were 1 h old, by what was paid for by then."""
    if o.is_empty():
        return pl.DataFrame()
    early = o.filter(pl.col("first_age") <= HORIZONS["1h"][2])
    return (early.group_by("paid_1h").agg(
        pl.len().alias("pairs"), *_share("trading_1d"), *_share("trading_7d"),
        pl.col("rug_24h").sum().alias("rug_24h"),
        pl.col("ratio_24h").drop_nulls().median().alias("median_ratio_24h"),
        (pl.col("ratio_24h") >= 2).sum().alias("x2_24h"), pl.col("ratio_24h").is_not_null().sum().alias("known_ratio"))
        .sort("paid_1h"))


def migration(o: pl.DataFrame, s: pl.DataFrame, disc: pl.DataFrame) -> pl.DataFrame:
    """pump.fun coins (a pumpfun curve or PumpSwap pool, or a migration the real-time collector saw)."""
    if o.is_empty():
        return pl.DataFrame()
    mig_tokens = set(disc.filter(pl.col("source") == "pumpfun_migration")["token"].to_list()) if not disc.is_empty() else set()
    pf = o.filter(pl.col("dex").is_in(["pumpfun", "pumpswap"]) | pl.col("token").is_in(list(mig_tokens)))["token"].unique()
    t = o.filter(pl.col("token").is_in(pf.to_list()) & (pl.col("chain") == "solana"))
    if t.is_empty():
        return pl.DataFrame()
    last = (s.filter(pl.col("token").is_in(pf.to_list())).sort("collected_at")
            .group_by(["chain", "pair"]).agg(pl.col("liq_usd").last().alias("liq_last")))
    t = t.join(last, on=["chain", "pair"], how="left")
    migrated = t.filter(pl.col("dex") == "pumpswap").group_by("token").agg(pl.col("created").min().alias("migrated_at"))
    other = (t.filter(~pl.col("dex").is_in(["pumpfun", "pumpswap"])).sort("created")
             .group_by("token").agg(pl.col("dex").first().alias("first_other_dex"), pl.col("created").first().alias("first_other_at"),
                                    pl.col("dex").unique().sort().str.join(",").alias("other_dexes")))
    liq = t.group_by("token").agg(pl.col("liq_last").fill_null(0).sum().alias("liq_all"),
                                  pl.col("liq_last").filter(pl.col("dex") == "pumpswap").fill_null(0).sum().alias("liq_pumpswap"),
                                  pl.len().alias("n_pairs"))
    tok = token_survival(t).select("token", "trading_1h", "trading_1d", "trading_7d")
    out = (migrated.join(other, on="token", how="left").join(liq, on="token", how="left").join(tok, on="token", how="left")
           .with_columns(((pl.col("first_other_at") - pl.col("migrated_at")) / ds.MIN_MS).alias("other_after_min"),
                         (pl.col("liq_pumpswap") / pl.col("liq_all")).alias("pumpswap_liq_share"),
                         pl.col("first_other_dex").is_not_null().alias("has_other_pool")))
    return out


def build(root: Path | None = None, now: int | None = None, floor: float | None = None, write: bool = True) -> dict:
    now = now or int(time.time() * 1000)
    floor = float(ds.config()["liq_floor_usd"] if floor is None else floor)
    pairs = pairs_table(root)
    s = snapshots(root, since_ms=now - (MAX_CREATED_DAYS + 8) * D, cols=COLS, pairs=pairs)
    disc = table("discovery", ds.DISC_SCHEMA, root)
    o = outcomes(s, pairs, table("orders", ds.ORDER_SCHEMA, root), now, floor, disc)
    out = {"outcomes": o, "survival": survival(o), "tokens": token_survival(o), "paid": paid_effect(o),
           "migration": migration(o, s, disc)}
    if write:
        d = ds.base(root) / "derived"
        for name, df in out.items():
            if not df.is_empty():
                ds._atomic_parquet(df, d / f"{name}.parquet")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.parse_args(argv)
    out = build()
    print(json.dumps({k: v.height for k, v in out.items()}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
