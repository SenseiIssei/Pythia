"""The harness on each kind of function the lab has (T1, results/leak_harness_prereg.md).

  genome     a G1 genome of the strategy factory: build.weights on the factory's context (F2: small.weights on
             its own), every array of the context and its panel changed after t
  feature    a feature of lab.features at one frequency: registry.frame on its group's table, the rows known
             after t (end_us + delay) changed. The table is the newest rows of the real one when there are any,
             else synthetic, a column for every one the feature reads (synthetic_table)
  candles    C1/C2's window candles (features.candles.windowed) on one coin's bars
  zoo        the zoo's feature builders from their raw rows: M8 (and the 7-day forward target, the same panel)
             and M10 from hourly bars (M10 with funding and open interest too), M12 from BTC's and SPY's closes;
             only the inputs (FEATURES), not the targets, are compared
  spec       a G2 spec: its features as the target's panel has them and its G1 trees (tree_column) on that panel
  book       a paper book's weight function on a fam_common.Panel, compared as held (NaN "leave it" carried
             forward); and the panel builder (fam_common.panel_from) on its long frame

Each returns check()'s dict with "kind" and "name". A table's own reading of raw files is not part of a feature's
check (the raw rows are where "known at" is set: registry and store say how).
"""

from __future__ import annotations

import dataclasses
import json
import os
from contextlib import contextmanager
from pathlib import Path

import numpy as np
import polars as pl

from . import check

HOUR = 3_600_000_000
DAY = 24 * HOUR
START = 1_577_836_800_000_000            # 2020-01-01


def _tag(res: dict, kind: str, name: str) -> dict:
    return {"kind": kind, **res, "name": name}


@contextmanager
def patched(obj, **attrs):
    """Module attributes swapped for the duration (a builder that reads a loader by name)."""
    old = {k: getattr(obj, k) for k in attrs}
    for k, v in attrs.items():
        setattr(obj, k, v)
    try:
        yield
    finally:
        for k, v in old.items():
            setattr(obj, k, v)


# ---------------------------------------------------------------- factory genomes

def genome(c, g: dict, n_cuts: int = 3, small: bool = False) -> dict:
    """A genome's target weights on the factory's context; small: F2's context and weights."""
    if small:
        from ..factory import small as sm
        fn = lambda x: sm.weights(dataclasses.replace(x, memo={}), g)       # noqa: E731
        cols = list(sm.ASSETS)
    else:
        from ..factory import build
        fn = lambda x: build.weights(dataclasses.replace(x, memo={}), g)    # noqa: E731
        cols = c.names
    from ..factory import grammar
    key = grammar.key(g)
    return _tag(check(fn, dataclasses.replace(c, memo={}), n_cuts=n_cuts, columns=cols, name=key), "genome", key)


# ---------------------------------------------------------------- features

def synthetic_table(cols, freq: str, market: bool = False, n: int = 240, seed: int = 0) -> pl.DataFrame:
    """A group table (ts_us, asset, end_us, cols) of positive noise on a regular grid with a few gaps."""
    from ..features import registry as R
    p = R.PERIOD[freq]
    rng = np.random.default_rng(seed)
    assets = [R.MARKET] if market else ["AAA", "BBB", "CCC"]
    ts = START + np.arange(n, dtype=np.int64) * p
    rows = []
    for a in assets:
        keep = rng.random(n) > 0.03
        d = {"ts_us": ts[keep], "asset": [a] * int(keep.sum()), "end_us": ts[keep] + p}
        for c in cols:
            d[c] = np.exp(rng.normal(0, 1, int(keep.sum())))
        rows.append(pl.DataFrame(d))
    return pl.concat(rows).sort("asset", "ts_us")


def feature_columns(name: str, freq: str) -> list[str]:
    from ..features import registry as R
    return [c for c in R.get(name).fn(R.PERIOD[freq]).meta.root_names() if c not in ("ts_us", "asset", "end_us")]


def real_table(name: str, freq: str, assets=("BTC", "ETH", "SOL", "XRP"), buckets: int = 400) -> pl.DataFrame:
    """The newest `buckets` rows per asset of the feature's real group table (empty without data)."""
    from ..features import registry as R
    f = R.get(name)
    try:
        t = R.table(f.group, freq, None if f.market else list(assets))
    except Exception:          # noqa: BLE001 (a group without its files is checked on synthetic rows)
        return pl.DataFrame()
    if not t.height or "end_us" not in t.columns:
        return pl.DataFrame()
    t = t.filter(pl.col("end_us").is_not_null())
    lo = t["ts_us"].max() - buckets * R.PERIOD[freq]
    return t.filter(pl.col("ts_us") > lo)


def feature(name: str, freq: str, table: pl.DataFrame | None = None, n_cuts: int = 3) -> dict:
    """One feature at one frequency through registry.frame on `table` (default: real rows, else synthetic)."""
    from ..features import registry as R
    f = R.get(name)
    src = "given"
    if table is None:
        table = real_table(name, freq)
        src = "real" if table.height else "synthetic"
        if not table.height:
            table = synthetic_table(feature_columns(name, freq), freq, f.market)
    table = table.with_columns(known_us=pl.col("end_us") + f.delay_us).sort("asset", "ts_us")
    assets = [R.MARKET] if f.market else sorted(set(table["asset"].to_list()))
    times = np.unique(table["known_us"].to_numpy())
    key = (f.group, freq, None if f.market else tuple(sorted(assets)))

    def run(tb: pl.DataFrame) -> pl.DataFrame:
        saved = dict(R._TABLES)
        R._TABLES.clear()
        R._TABLES[key] = tb.drop("known_us").sort("asset", "ts_us")
        try:
            return R.frame([name], ["_"] if f.market else assets, times, freq)
        finally:
            R._TABLES.clear()
            R._TABLES.update(saved)
    res = check(run, table, time="known_us", out_time="ts_us", n_cuts=n_cuts, name=f"{name} {freq}")
    return {**_tag(res, "feature", f"{name} {freq}"), "data": src}


def all_features(n_cuts: int = 3) -> list[dict]:
    from .. import features
    return [feature(n, fq, n_cuts=n_cuts) for n in features.names() for fq in features.get(n).freqs]


def synthetic_bars(freq: str, n: int = 300, seed: int = 0) -> pl.DataFrame:
    """One coin's candle measures as lab.candles.store gives them (open_time_us, close_time_us, open, high, low,
    close, range), a gap of one bar in the middle."""
    from ..features import registry as R
    p = R.PERIOD[freq]
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.02, n)))
    op = np.r_[close[0], close[:-1]]
    hi = np.maximum(op, close) * np.exp(np.abs(rng.normal(0, 0.01, n)))
    lo = np.minimum(op, close) * np.exp(-np.abs(rng.normal(0, 0.01, n)))
    ot = START + np.arange(n, dtype=np.int64) * p
    keep = np.arange(n) != n // 3
    return pl.DataFrame({"open_time_us": ot, "close_time_us": ot + p, "open": op, "high": hi, "low": lo,
                         "close": close, "range": np.log(hi / lo)}).filter(pl.Series(keep))


def candles(freq: str, bars: pl.DataFrame | None = None, n_cuts: int = 3) -> dict:
    from ..features import candles as fcd
    bars = (bars if bars is not None else synthetic_bars(freq)).with_columns(known_us=pl.col("close_time_us"))
    new = None

    def run(b: pl.DataFrame) -> pl.DataFrame:
        nonlocal new
        m = fcd.windowed(b.drop("known_us").sort("open_time_us"), freq)
        new = new or [c for c in m.columns if c not in b.columns]
        return m.select(known_us="close_time_us", *new)
    return _tag(check(run, bars, n_cuts=n_cuts, name=f"windowed {freq}"), "candles", f"candles.windowed {freq}")


# ---------------------------------------------------------------- the zoo's feature builders

def synthetic_hourly(bases=("BTC", "ETH", "SOL", "XRP", "ADA"), days: int = 420, seed: int = 0) -> pl.DataFrame:
    """data.hourly's bars for a few coins (ts_us, open, high, low, close, ret, rv, volume_q, taker_buy_q, trades,
    minutes, symbol), BTC first."""
    rng = np.random.default_rng(seed)
    n = days * 24
    ts = START + np.arange(n, dtype=np.int64) * HOUR
    out = []
    for k, b in enumerate(bases):
        r = rng.normal(0, 0.006, n)
        close = 100 * (k + 1) * np.exp(np.cumsum(r))
        rv = r ** 2 * np.exp(rng.normal(0, 0.3, n)) + 1e-7
        out.append(pl.DataFrame({
            "ts_us": ts, "open": close * np.exp(-r), "high": close * (1 + np.sqrt(rv)), "low": close * (1 - np.sqrt(rv)),
            "close": close, "ret": r, "rv": rv, "volume_q": np.exp(rng.normal(14, 0.5, n)),
            "taker_buy_q": np.exp(rng.normal(13, 0.5, n)), "trades": rng.integers(100, 5000, n),
            "minutes": np.full(n, 60), "symbol": [f"{b}USDT"] * n}))
    return pl.concat(out)


def synthetic_perp(hourly: pl.DataFrame, seed: int = 0) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Funding every 8 hours and hourly open interest for the coins of `hourly` (symbol per row)."""
    rng = np.random.default_rng(seed)
    ts = np.unique(hourly["ts_us"].to_numpy())
    fu, oi = [], []
    for s in sorted(set(hourly["symbol"].to_list())):
        ft = ts[(ts % (8 * HOUR)) == 0]
        fu.append(pl.DataFrame({"funding_time_us": ft, "funding_rate": rng.normal(1e-4, 1e-4, len(ft)),
                                "symbol": [s] * len(ft)}))
        oi.append(pl.DataFrame({"ts_us": ts, "oi_usd": np.exp(np.cumsum(rng.normal(0, 0.01, len(ts))) + 20),
                                "symbol": [s] * len(ts)}))
    return pl.concat(fu), pl.concat(oi)


def real_hourly(bases=("BTC", "ETH", "SOL", "XRP", "ADA"), days: int = 420) -> pl.DataFrame:
    """The newest `days` of data.hourly's bars of these coins (empty without the 1-minute history)."""
    from .. import data
    out = []
    for b in bases:
        h = data.hourly(f"{b}USDT")
        if h.height:
            out.append(h.filter(pl.col("ts_us") > h["ts_us"].max() - days * DAY))
    return pl.concat(out, how="vertical_relaxed") if out else pl.DataFrame()


def real_perp(bases) -> tuple[pl.DataFrame, pl.DataFrame]:
    from .. import data
    fu, oi = [], []
    for b in bases:
        f, o = data.funding(b), data.open_interest_hourly(b)
        if f.height:
            fu.append(f.with_columns(symbol=pl.lit(f"{b}USDT")))
        if o.height:
            oi.append(o.with_columns(symbol=pl.lit(f"{b}USDT")))
    return (pl.concat(fu) if fu else pl.DataFrame(), pl.concat(oi) if oi else pl.DataFrame())


def _by_symbol(df: pl.DataFrame, sym: str) -> pl.DataFrame:
    if not df.height or "symbol" not in df.columns:
        return pl.DataFrame()
    return df.filter(pl.col("symbol") == sym).drop("symbol", "known_us", strict=False)


def m8_builder(hourly: pl.DataFrame, features: list[str] | None = None) -> pl.DataFrame:
    """M8's inputs per (day, coin) built from hourly bars, known at the day's end (also fwd7's: the same panel)."""
    from ..experiments import vol_daily
    from ..models import daily, m8_direction as m8
    bases = [s.removesuffix("USDT") for s in dict.fromkeys(hourly["symbol"].to_list())]
    with patched(vol_daily, hourly=lambda s: _by_symbol(hourly, s)):
        p = m8.panel_from(daily.daily_panel(bases, loader=vol_daily.coin_daily))
    return p.select(pl.col("symbol"), known_us=pl.col("ts_us") + DAY, *(features or m8.FEATURES))


def m10_builder(raw: dict[str, pl.DataFrame], features: list[str] | None = None) -> pl.DataFrame:
    """M10's inputs from hourly bars, funding and open interest ({"hourly", "funding", "oi"})."""
    from .. import data
    from ..experiments import vol_daily
    from ..models import daily, m10_vol_regime as m10
    h = raw["hourly"]
    bases = [s.removesuffix("USDT") for s in dict.fromkeys(h["symbol"].to_list())]
    with patched(vol_daily, hourly=lambda s: _by_symbol(h, s)), \
            patched(data, funding=lambda b: _by_symbol(raw["funding"], f"{b}USDT"),
                    open_interest_hourly=lambda b: _by_symbol(raw["oi"], f"{b}USDT")):
        p = m10.panel_from(daily.enrich(daily.coin_frames(bases, m10.coin_with_perp)))
    return p.select(pl.col("symbol"), known_us=pl.col("ts_us") + DAY, *(features or m10.FEATURES))


def m12_builder(raw: dict[str, pl.DataFrame], features: list[str] | None = None) -> pl.DataFrame:
    """M12's inputs from BTC's and SPY's daily closes ({"btc", "spy"}: date, close, known_us)."""
    from ..models import m12_cross_asset as m12
    s = lambda k: (raw[k]["date"].to_numpy().astype("datetime64[D]"), raw[k]["close"].to_numpy())  # noqa: E731
    p = m12.panel_from(s("btc"), s("spy"))
    return p.select(pl.col("symbol"), known_us=pl.col("ts_us") + DAY, *(features or m12.FEATURES))


def closes_frame(series: tuple[np.ndarray, np.ndarray]) -> pl.DataFrame:
    d = series[0].astype("datetime64[D]")
    return pl.DataFrame({"date": d, "close": np.asarray(series[1], dtype=float),
                         "known_us": (d.astype("datetime64[us]").astype(np.int64) + DAY)})


def real_closes() -> dict[str, pl.DataFrame] | None:
    """BTC's and SPY's closes from the zoo's Yahoo cache, never fetched (None without the cache)."""
    from ..data import ROOT
    from ..experiments import etf_trend
    out = {}
    for k, sym in (("btc", "BTC-USD"), ("spy", "SPY")):
        p = ROOT / "models" / "zoo" / "_data" / f"{sym}.csv"
        try:
            out[k] = closes_frame(etf_trend.parse_stooq(p.read_text(encoding="utf-8")))
        except (OSError, etf_trend.DataUnavailable):
            return None
    return out


def zoo(real: bool = True, n_cuts: int = 3) -> list[dict]:
    """The three builders on real rows when there are any (the newest 420 days), else synthetic."""
    from ..models import m12_cross_asset as m12
    out = []
    h = real_hourly() if real else pl.DataFrame()
    src = "real" if h.height else "synthetic"
    h = h if h.height else synthetic_hourly()
    fu, oi = real_perp([s.removesuffix("USDT") for s in dict.fromkeys(h["symbol"].to_list())]) \
        if src == "real" else synthetic_perp(h)
    h = h.with_columns(known_us=pl.col("ts_us") + HOUR)
    fu = fu.with_columns(known_us=pl.col("funding_time_us")) if fu.height else synthetic_perp(h)[0].with_columns(
        known_us=pl.col("funding_time_us"))
    oi = oi.with_columns(known_us=pl.col("ts_us") + HOUR) if oi.height else synthetic_perp(h)[1].with_columns(
        known_us=pl.col("ts_us") + HOUR)
    out.append({**_tag(check(m8_builder, h, n_cuts=n_cuts), "zoo", "M8 (and fwd7)"), "data": src})
    out.append({**_tag(check(m10_builder, {"hourly": h, "funding": fu, "oi": oi}, n_cuts=n_cuts), "zoo", "M10"),
                "data": src})
    raw = real_closes() if real else None
    src12 = "real" if raw else "synthetic"
    if raw is None:
        b, s = m12.synthetic(1400)
        raw = {"btc": closes_frame(b), "spy": closes_frame(s)}
    out.append({**_tag(check(m12_builder, raw, n_cuts=n_cuts), "zoo", "M12"), "data": src12})
    return out


# ---------------------------------------------------------------- G2 specs

def spec_frame(panel: pl.DataFrame, spec: dict) -> pl.DataFrame:
    """The spec's input matrix per panel row (ts_us, symbol, x0..), as the model factory builds it."""
    from ..models import factory as mf
    cols = {f"x{i}": panel[f].fill_null(np.nan).cast(pl.Float64) for i, f in enumerate(spec["features"])}
    for i, tr in enumerate(spec.get("trees") or []):
        cols[f"tree{i}"] = pl.Series(mf.tree_column(panel, tr))
    return pl.DataFrame({"ts_us": panel["ts_us"], "symbol": panel["symbol"], **cols})


def spec(panel: pl.DataFrame, s: dict, bad_inputs=(), n_cuts: int = 3) -> dict:
    """A G2 spec: no input a builder check found leaking, and its trees on the panel (rows known after t
    changed)."""
    from ..models import factory as mf
    name = mf.spec_key(s)
    bad = sorted(set(s["features"]) & set(bad_inputs))
    if bad:
        return {"kind": "spec", "name": name, "ok": False, "runs": 0, "cuts": [], "error": None,
                "leaks": [{"kind": "builder", "cut": None, "first": None, "column": ", ".join(bad)}],
                "first": {"kind": "builder", "cut": None, "first": "the weekly leak check", "column": ", ".join(bad)}}
    keep = [c for c in ("ts_us", "symbol", "close", "high", "low", "qv", "sigma") if c in panel.columns]
    p = panel.select(list(dict.fromkeys(keep + list(s["features"]))))
    return _tag(check(lambda x: spec_frame(x, s), p, time="ts_us", keys=("symbol",), n_cuts=n_cuts, name=name),
                "spec", name)


def bad_inputs(doc: dict | None = None) -> set[str]:
    """The zoo inputs the last weekly report found leaking (reports/leak/latest.json), none without one."""
    if doc is None:
        from .. import report
        root = Path(os.environ.get("PYTHIA_REPORTS", str(report.REPORTS)))
        try:
            doc = json.loads((root / "leak" / "latest.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return set()
    return {x["first"]["column"] for x in doc.get("results", []) if x.get("kind") == "zoo" and not x.get("ok")
            and x.get("first") and x["first"].get("column") not in (None, "(error)", "(rows)")}


# ---------------------------------------------------------------- paper books

def book_functions() -> dict:
    """name -> weight function of a fam_common.Panel, every paper book in lab/paper that takes one
    (memes and btc_gated run on W7's panel, see panels())."""
    from ..experiments import alpaca_universe as au, fam_lowvol as flv, smallaccount as s1
    from ..paper import btc_gated, exit_shadow, families, memes, smallaccount, tranches_filtered as tf
    out = {"families": families.targets,
           "families@alpaca": lambda P: families.targets(P, au.alpaca_mask(P))}
    for n in tf.FILTERS:
        out[f"tranches_filtered {n}"] = lambda P, n=n: tf.targets(P, n)[0]
    for n, b in smallaccount.BOOKS.items():
        out[f"smallaccount {n}"] = lambda P, b=b: s1.candidate(P, b["key"], b["n"])
    out["exit_shadow live_books"] = exit_shadow.live_books
    out["perps_neutral lowvol"] = lambda P: flv.weights(P, "vol 60d", 50, "beta-neutral BAB")
    out["memes"] = memes.targets
    out["btc_gated"] = btc_gated.targets
    return out


W7_BOOKS = ("memes", "btc_gated")


def held(out):
    """A book's targets as it holds them: NaN means "leave it" (families.step), so the weight each coin has at
    each close is the last one set, 0 before (smallaccount.ffill); a coin never set and one set to 0 hold the same."""
    from ..experiments import smallaccount as s1
    f = lambda w: s1.ffill(w) if isinstance(w, np.ndarray) and w.ndim == 2 and w.dtype.kind == "f" else w  # noqa: E731
    return {k: f(v) for k, v in out.items()} if isinstance(out, dict) else f(out)


def book(name: str, fn, P, n_cuts: int = 3) -> dict:
    return _tag(check(lambda x: held(fn(x)), P, n_cuts=n_cuts, columns=P.names, name=name), "book", name)


def panel_frame(P, fields=("px", "ret", "alive", "traded", "adv28", "sigma", "eligible", "btc_on")) -> pl.DataFrame:
    """A panel's fields as rows (known_us, symbol, one column each), bools as 0/1."""
    T, N = P.T, P.N
    d = {"known_us": np.repeat(P.days + DAY, N), "symbol": np.tile(np.array(P.names), T)}
    for f in fields:
        x = getattr(P, f)
        x = np.broadcast_to(x[:, None], (T, N)) if x.ndim == 1 else x
        d[f] = x.astype(float).ravel()
    return pl.DataFrame(d)


def panel_builder(long: pl.DataFrame, perp: pl.DataFrame, n_cuts: int = 3) -> dict:
    """fam_common.panel_from on a long frame (day, symbol, close, high, low, rv, qv, n) and the perp days it reads
    (day, base, funding, perp_qv): its fields at or before t with the bars after t changed or cut."""
    from ..experiments import fam_common as fc
    raw = {"bars": long.with_columns(known_us=pl.col("day") + DAY),
           "perp": perp.select("day", "base", "funding", "perp_qv").with_columns(known_us=pl.col("day") + DAY)}

    def run(x: dict) -> pl.DataFrame:
        with patched(fc, perp_daily_for=lambda last: x["perp"].drop("known_us")):
            P = fc.panel_from(x["bars"].drop("known_us"))
        return panel_frame(P, PANEL_FIELDS).filter(pl.col("alive") > 0)   # a coin not listed yet has no cell
    res = check(run, raw, keys=("symbol",), n_cuts=n_cuts, name="fam_common.panel_from")
    return _tag(res, "book", "fam_common.panel_from (the books' panel)")


PANEL_FIELDS = ("px", "ret", "alive", "traded", "adv28", "sigma", "eligible", "perp_ok", "funding", "btc_on")
