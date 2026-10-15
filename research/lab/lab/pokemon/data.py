"""The Pokemon card lake as frames, and the features every study and model uses.

One row per card and snapshot day. `price` is the card's price in USD: the
TCGplayer market price of its most valuable printing, else the Cardmarket
trend converted at that day's ECB rate (`price_src` says which). Returns
between snapshots are log changes of that price for the same card and the
same source.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
import polars as pl

from ..collect.pokemon import lake

# Characters collectors pay up for. Matched as whole words in the card name.
CHARACTERS: dict[str, list[str]] = {
    "charizard": ["charizard"],
    "pikachu": ["pikachu"],
    "eeveelution": ["eevee", "vaporeon", "jolteon", "flareon", "espeon", "umbreon", "leafeon", "glaceon",
                    "sylveon"],
    "mew": ["mew", "mewtwo"],
    "legendary_bird_dragon": ["rayquaza", "lugia", "gengar", "greninja", "lucario", "gardevoir"],
}

# Rarity strings of the API, grouped. Checked against every rarity string in
# the public card data (2026-10): chase = secret, illustration, shiny, gold
# and other short-print cards; ultra = the rule-box Pokemon (ex, V, GX ...).
CHASE_PHRASES = ("special illustration", "illustration rare", "hyper", "secret", "rainbow", "gold", "shiny",
                 "shining", "trainer gallery", "radiant", "amazing", "prism star", "holo star", "legend",
                 "classic collection")
ULTRA_WORDS = {"ultra", "double", "v", "vmax", "vstar", "gx", "ex", "lv.x", "break", "prime", "mega", "attack"}


def rarity_group(r: str | None) -> str:
    s = (r or "").lower().replace("_", " ")
    words = set(re.findall(r"[a-z.]+", s))
    if not s:
        return "other"
    if any(k in s for k in CHASE_PHRASES) or "ace" in words:
        return "chase"
    if words & ULTRA_WORDS:
        return "ultra"
    if "holo" in words or "promo" in words:
        return "holo"
    if "common" in words or "uncommon" in words:
        return "common"
    if "rare" in words:
        return "rare"
    return "other"


def character(name: str | None) -> str | None:
    words = set(re.findall(r"[a-z]+", (name or "").lower()))
    for c, keys in CHARACTERS.items():
        if words & set(keys):
            return c
    return None


def _number(s: str | None) -> int | None:
    m = re.match(r"^(\d+)$", str(s or ""))
    return int(m.group(1)) if m else None


def is_secret(number: str | None, printed_total) -> bool:
    n = _number(number)
    try:
        return n is not None and printed_total is not None and n > int(printed_total)
    except (TypeError, ValueError):
        return False


def is_alt_art(rarity: str | None, secret: bool) -> bool:
    """Full or alternate art, as far as the rarity string tells: the Scarlet and
    Violet illustration rares, and secret-numbered ultra rares before them. An
    approximation; the API has no alt-art field."""
    r = (rarity or "").lower()
    return "illustration" in r or (secret and ("ultra" in r or "secret" in r or "rainbow" in r))


def fx_by_date(root: Path) -> dict[str, float]:
    out = {}
    for f in sorted((root / "meta").glob("*.json")):
        try:
            m = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        if m.get("eurusd"):
            out[str(m.get("date") or f.stem)] = float(m["eurusd"])
    return out


def load_cards(root: Path | None = None) -> pl.DataFrame:
    """Every snapshot, with `price` (USD) and `price_src`. Empty frame if none."""
    root = root or lake()
    files = sorted((root / "cards").glob("date=*/cards.parquet"))
    if not files:
        return pl.DataFrame()
    df = pl.concat([pl.read_parquet(f) for f in files], how="diagonal_relaxed")
    # The rate of the day, else the last one before it, else the first known.
    fx = fx_by_date(root)
    last = next(iter(fx.values()), None)
    by_day: dict[str, float | None] = {}
    for d in sorted(df["date"].unique().to_list()):
        last = fx.get(d, last)
        by_day[d] = last
    df = df.with_columns(eurusd=pl.col("date").replace_strict(by_day, default=None, return_dtype=pl.Float64))
    return df.with_columns(
        price=pl.when(pl.col("tp_market") > 0).then(pl.col("tp_market"))
        .otherwise(pl.col("cm_trend") * pl.col("eurusd")),
        price_src=pl.when(pl.col("tp_market") > 0).then(pl.lit("tcgplayer")).otherwise(pl.lit("cardmarket")),
    ).filter(pl.col("price") > 0).sort("card_id", "date")


def load_catalog(root: Path | None = None) -> pl.DataFrame:
    p = (root or lake()) / "catalog.parquet"
    return pl.read_parquet(p) if p.exists() else pl.DataFrame()


def features(df: pl.DataFrame) -> pl.DataFrame:
    """Static and Cardmarket-trend features for each row. Known at the snapshot."""
    if df.is_empty():
        return df
    rg = [rarity_group(r) for r in df["rarity"].to_list()]
    ch = [character(n) for n in df["name"].to_list()]
    sec = [is_secret(n, t) for n, t in zip(df["number"].to_list(), df["set_printed_total"].to_list())]
    alt = [is_alt_art(r, s) for r, s in zip(df["rarity"].to_list(), sec)]
    out = df.with_columns(
        rarity_group=pl.Series(rg, dtype=pl.Utf8),
        character=pl.Series(ch, dtype=pl.Utf8),
        secret=pl.Series(sec, dtype=pl.Boolean),
        alt_art=pl.Series(alt, dtype=pl.Boolean),
        set_age_days=(pl.col("date").str.to_date() - pl.col("release_date").str.to_date()).dt.total_days(),
        log_price=pl.col("price").log(),
        cm_mom_1_7=pl.col("cm_avg1") / pl.col("cm_avg7") - 1,
        cm_mom_7_30=pl.col("cm_avg7") / pl.col("cm_avg30") - 1,
        cm_trend_30=pl.col("cm_trend") / pl.col("cm_avg30") - 1,
        spread=(pl.col("tp_market") / (pl.col("cm_trend") * pl.col("eurusd"))).log(),
        is_pokemon=pl.col("supertype").str.starts_with("Pok"),
    )
    # Clip the Cardmarket momentum: thin cards have wild averages.
    return out.with_columns([pl.col(c).clip(-0.9, 3.0).fill_nan(None) for c in ("cm_mom_1_7", "cm_mom_7_30",
                                                                                 "cm_trend_30")])


def with_returns(df: pl.DataFrame) -> pl.DataFrame:
    """Past log returns from earlier snapshots of the same card and price source
    (`ret_1d`, `ret_7d`, `ret_30d`): the change from the latest snapshot at least
    that many days back, within a few days of slack, else null."""
    if df.is_empty():
        return df
    d = df.with_columns(_d=pl.col("date").str.to_date()).sort("card_id", "_d")
    for name, lag, slack in (("ret_1d", 1, 2), ("ret_7d", 7, 3), ("ret_30d", 30, 5)):
        past = d.select("card_id", "price_src", _pd=pl.col("_d"), _pp=pl.col("price")).sort("card_id", "_pd")
        d = (d.with_columns(_target=pl.col("_d") - pl.duration(days=lag))
             .sort("_target")
             .join_asof(past.sort("_pd"), left_on="_target", right_on="_pd", by=["card_id", "price_src"],
                        strategy="backward", tolerance=f"{slack}d", check_sortedness=False)
             .with_columns(pl.when(pl.col("_pd") < pl.col("_d")).then((pl.col("price") / pl.col("_pp")).log())
                           .otherwise(None).alias(name))
             .drop("_target", "_pd", "_pp"))
    return d.sort("card_id", "_d").drop("_d")


def forward_returns(df: pl.DataFrame, horizon: int, slack: int = 3) -> pl.Series:
    """log(price at t + horizon / price at t) for each row, from the first
    snapshot at least `horizon` days later within `slack` days; null if none."""
    d = df.with_columns(_d=pl.col("date").str.to_date(), _i=pl.int_range(pl.len()))
    fut = d.select("card_id", "price_src", _fd=pl.col("_d"), _fp=pl.col("price")).sort("_fd")
    j = (d.with_columns(_target=pl.col("_d") + pl.duration(days=horizon)).sort("_target")
         .join_asof(fut, left_on="_target", right_on="_fd", by=["card_id", "price_src"], strategy="forward",
                    tolerance=f"{slack}d", check_sortedness=False)
         .sort("_i"))
    return (j["_fp"] / j["price"]).log().alias(f"fwd_{horizon}d")


def history_days(df: pl.DataFrame) -> int:
    if df.is_empty():
        return 0
    ds = df["date"].unique().sort().to_list()
    return (np.datetime64(ds[-1]) - np.datetime64(ds[0])).astype(int) + 1
