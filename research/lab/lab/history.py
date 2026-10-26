"""D1: the long daily history, from 2017, for the small-account rules and the factories.

    python -m lab.history fetch     every universe pair's daily bars before the hourly panel from Binance's
                                    archive (lab.klines_daily, cached in <data>/hist/binance_spot/klines_1d),
                                    and PAXG in full; resumable, a pair is listed once
    python -m lab.history check     the overlaps: Binance's daily closes against the panel's, Kraken's OHLC
                                    against Binance, Yahoo against <data>/etf/daily; closes more than 0.5 %
                                    apart are listed

The sweep's panel (fam_common.build_daily_panel) is built from hourly bars,
which the recorder has from 2020-01. Binance's archive has daily bars of every
USDT pair it ever listed, delisted ones included (the universe in
<data>/hist/universe.json lists them), from 2017-08. long_frame() puts the daily
bars before each pair's first panel day in front of the panel, in its format:
realised variance from the day's range (Parkinson), quote volume as it is, n
24. The bars are split where the panel splits them (a gap of more than three
days or a tenfold move); the part that runs into the pair's first panel
segment takes that segment's name, an earlier part is its own segment
(<pair>~p<i>). The months up to UNTIL are fetched, so three months overlap
the panel for the check. The ETF closes are the lab's copy (<data>/etf/daily,
SPY and QQQ from 2000, GLD from 2004).

Standard library, numpy and polars. No key, nothing written but the cache.
"""

from __future__ import annotations

import json
import math
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import polars as pl

from . import klines_daily as kd
from .data import ROOT

FROM = "2017-08"                    # Binance's first month of USDT pairs
UNTIL = "2020-04"                   # fetched before this month: the panel starts 2020-01, three months overlap
LONG_FROM = "2018-01-01"            # where the long in-sample windows start (four and a half months of warm-up)
DIFF_BAR = 0.005                    # closes further apart than this are listed
GAP_DAYS = 3
JUMP = math.log(10)
KRAKEN = "https://api.kraken.com/0/public/OHLC?pair={}&interval=1440"
KRAKEN_PAIRS = {"BTCUSDT": "XBTUSD", "ETHUSDT": "ETHUSD", "SOLUSDT": "SOLUSD", "PAXGUSDT": "PAXGUSD"}
FULL = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "PAXGUSDT")     # fetched to today, for the checks
ETFS = ("SPY", "QQQ", "GLD")
COLS = ["day", "symbol", "close", "high", "low", "rv", "qv", "n"]
_FRAME: pl.DataFrame | None = None


def state_path() -> Path:
    return ROOT / "hist" / "binance_spot" / "klines_1d" / "_long.json"


def read_state(path: Path | None = None) -> dict:
    try:
        return json.loads((path or state_path()).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"until": UNTIL, "symbols": {}}


def write_state(st: dict, path: Path | None = None) -> None:
    p = path or state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, indent=0, sort_keys=True), encoding="utf-8")
    os.replace(tmp, p)


def universe() -> list[str]:
    """The sweep's pairs: <data>/hist/universe.json less what the panel excludes (stables, gold, wrapped)."""
    from .experiments import fam_common as fc
    syms = json.loads((ROOT / "hist" / "universe.json").read_text(encoding="utf-8"))
    return [s for s in syms if s not in fc.EXCLUDE and s.isascii()]


def fetch_long(symbols: list[str] | None = None, until: str = UNTIL, verbose: bool = False,
               listing=kd.list_months, getter=kd.fetch) -> dict:
    """The months before `until` of every pair not yet in the state file; a pair is listed once (its early
    months never change). Returns the state: {"symbols": {pair: [months fetched]}}."""
    st = read_state()
    if st.get("until") != until:
        st = {"until": until, "symbols": {}}
    todo = [s for s in (symbols if symbols is not None else universe()) if s not in st["symbols"]]
    for i, s in enumerate(todo):
        try:
            months = [m for m in listing(s) if FROM <= m < until]
            if months:
                getter(s, until=until, months=months)
        except (urllib.error.URLError, OSError, ValueError) as e:
            print(f"  {s}: {e}; next run again", file=sys.stderr, flush=True)
            continue
        st["symbols"][s] = months
        if verbose and months:
            print(f"  {s}: {months[0]} to {months[-1]}", flush=True)
        if i % 25 == 24:
            write_state(st)
    if todo:
        write_state(st)
    return st


def fetch_full(symbols=FULL, verbose: bool = False) -> dict[str, pl.DataFrame]:
    """BTC, ETH, SOL and PAXG to yesterday (for the checks); the cache when the archive does not answer."""
    out = {}
    for s in symbols:
        try:
            out[s] = kd.fetch(s, verbose=verbose)
        except (urllib.error.URLError, OSError) as e:
            print(f"  {s}: {e}; the cache", file=sys.stderr)
            out[s] = cached(s)
    return out


def cached(symbol: str, until: str | None = None) -> pl.DataFrame:
    files = [p for p in sorted(kd.cache_dir(symbol).glob("*.parquet")) if until is None or p.stem < until]
    if not files:
        return kd.empty()
    return pl.concat([pl.read_parquet(p) for p in files], how="vertical_relaxed").unique("day", keep="last").sort("day")


# ---------------------------------------------------------------- the long frame

def segments(d: pl.DataFrame) -> list[pl.DataFrame]:
    """Daily bars split where the panel would split hourly ones: a gap over GAP_DAYS or a tenfold move."""
    if d.is_empty():
        return []
    d = d.sort("day").with_columns(
        brk=((pl.col("day").diff() > GAP_DAYS * kd.DAY_US)
             | ((pl.col("close").log() - pl.col("close").shift(1).log()).abs() > JUMP)).fill_null(False)
    ).with_columns(seg=pl.col("brk").cum_sum())
    return [g.drop("brk", "seg") for _, g in d.group_by("seg", maintain_order=True)]


def to_panel_rows(d: pl.DataFrame, name: str) -> pl.DataFrame:
    """Daily klines in the panel's columns: rv from the range (Parkinson), n 24 (a full day of hours)."""
    return d.select(
        pl.col("day").cast(pl.Int64), pl.lit(name).alias("symbol"), pl.col("close"), pl.col("high"), pl.col("low"),
        ((pl.col("high") / pl.col("low")).log() ** 2 / (4 * math.log(2))).alias("rv"), pl.col("qv"),
        pl.lit(24).cast(pl.UInt32).alias("n"))


def pre_rows(base: pl.DataFrame, daily: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """The daily bars of each pair before its first panel day, named like the panel's segments."""
    raw = base.with_columns(raw=pl.col("symbol").str.split("~").list.first())
    first = (raw.sort("day").group_by("raw").agg(day=pl.col("day").first(), symbol=pl.col("symbol").first(),
                                                 close=pl.col("close").first()))
    first = {r["raw"]: r for r in first.iter_rows(named=True)}
    frames = []
    for s, d in daily.items():
        d = d.filter(pl.col("close") > 0)
        f = first.get(s)
        if f is not None:
            d = d.filter(pl.col("day") < f["day"])
        segs = segments(d)
        for i, g in enumerate(segs):
            last = i == len(segs) - 1
            if last and f is not None:
                joins = (f["day"] - g["day"][-1] <= GAP_DAYS * kd.DAY_US
                         and abs(math.log(f["close"] / g["close"][-1])) <= JUMP)
                name = f["symbol"] if joins else f"{s}~p{i}"
            else:
                name = s if last else f"{s}~p{i}"
            frames.append(to_panel_rows(g, name))
    if not frames:
        return pl.DataFrame(schema=base.select(COLS).schema)
    return pl.concat(frames, how="vertical_relaxed").select(COLS).cast(dict(base.select(COLS).schema))


def _pre_cache() -> Path:
    from .experiments import fam_common as fc
    return fc.OUT / "cache" / "daily_pre2020.parquet"


def long_frame(fetch: bool = False, fresh: bool = False) -> pl.DataFrame:
    """build_daily_panel's frame with the daily bars before 2020 in front. `fetch` fetches what the state file
    does not have yet (a no-op once every pair is listed); the pre-2020 rows are cached next to the panel's
    cache and rebuilt when either is newer."""
    global _FRAME
    if _FRAME is not None and not fresh and not fetch:
        return _FRAME
    from .experiments import fam_common as fc
    base = fc.build_daily_panel(fresh)
    if fetch:
        fetch_long()
    st = read_state()
    pc, sp = _pre_cache(), state_path()
    base_cache = fc.OUT / "cache" / "daily_panel.parquet"
    newest = max([p.stat().st_mtime for p in (sp, base_cache) if p.exists()], default=0.0)
    if pc.exists() and not fresh and pc.stat().st_mtime >= newest:
        pre = pl.read_parquet(pc)
    else:
        pre = pre_rows(base, {s: cached(s, st.get("until", UNTIL)) for s, m in st.get("symbols", {}).items() if m})
        try:
            pc.parent.mkdir(parents=True, exist_ok=True)
            pre.write_parquet(pc)
        except OSError:
            pass                                    # a read-only data root: rebuilt next time
    _FRAME = pl.concat([pre, base.select(COLS)], how="vertical_relaxed").sort(["symbol", "day"])
    return _FRAME


def load_long_panel(fetch: bool = False, fresh: bool = False):
    """The sweep's panel from 2017 (fam_common.Panel); fam_common.load_panel stays the 2020 one."""
    from .experiments import fam_common as fc
    return fc.panel_from(long_frame(fetch, fresh))


def coverage(frame: pl.DataFrame, symbols=("BTCUSDT", "ETHUSDT", "SOLUSDT")) -> list[dict]:
    """First and last day of each pair's segments in the frame."""
    out = []
    raw = frame.with_columns(raw=pl.col("symbol").str.split("~").list.first())
    for s in symbols:
        q = raw.filter(pl.col("raw") == s)
        if q.height:
            out.append({"pair": s, "first": _d(int(q["day"].min())), "last": _d(int(q["day"].max())), "days": q.height})
    return out


def pairs_before(frame: pl.DataFrame, day: str = "2020-01-01") -> int:
    us = int(datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1e6)
    return frame.filter(pl.col("day") < us)["symbol"].n_unique()


def _d(us: int) -> str:
    return datetime.fromtimestamp(us / 1e6, timezone.utc).strftime("%Y-%m-%d")


# ---------------------------------------------------------------- the overlap checks

def compare(a: dict[str, float], b: dict[str, float], bar: float = DIFF_BAR) -> dict:
    """Closes on the days both have: how many, the largest gap, and every day further apart than `bar`."""
    days = sorted(set(a) & set(b))
    diffs = [(d, a[d], b[d], a[d] / b[d] - 1) for d in days if b[d] > 0]
    off = [x for x in diffs if abs(x[3]) > bar]
    return {"days": len(diffs), "first": days[0] if days else None, "last": days[-1] if days else None,
            "max_abs": max((abs(x[3]) for x in diffs), default=0.0), "over": len(off),
            "rows": [{"day": d, "a": x, "b": y, "diff": r} for d, x, y, r in off]}


def by_day(d: pl.DataFrame, col: str = "close") -> dict[str, float]:
    return {_d(int(t)): float(c) for t, c in zip(d["day"].to_list(), d[col].to_list()) if c is not None}


def binance_vs_panel(base: pl.DataFrame, daily: dict[str, pl.DataFrame]) -> dict[str, dict]:
    """Binance's daily close against the panel's (the last hourly close of the UTC day), pair by pair."""
    raw = base.with_columns(raw=pl.col("symbol").str.split("~").list.first())
    out = {}
    for s, d in daily.items():
        p = raw.filter(pl.col("raw") == s)
        if p.height and d.height:
            out[s] = compare(by_day(d), by_day(p))
    return out


def kraken_rows(payload: dict) -> dict[str, float]:
    """Kraken's OHLC answer as {day: close}; the running day (the last row) is left out."""
    res = payload.get("result") or {}
    rows = next((v for k, v in res.items() if k != "last"), [])
    return {_d(int(r[0]) * 1_000_000): float(r[4]) for r in rows[:-1]}


def kraken_vs_binance(daily: dict[str, pl.DataFrame], get=None) -> dict[str, dict]:
    """Kraken's USD closes against Binance's USDT closes (Kraken's keyless OHLC goes back 720 days)."""
    get = get or _get_json
    out = {}
    for s, pair in KRAKEN_PAIRS.items():
        if s not in daily:
            continue
        try:
            k = kraken_rows(get(KRAKEN.format(pair)))
        except (urllib.error.URLError, OSError, ValueError, KeyError, IndexError, TypeError) as e:
            print(f"  kraken {pair}: {e}", file=sys.stderr)
            continue
        out[s] = compare(by_day(daily[s]), k)
        time.sleep(1.0)
    return out


def yahoo_vs_copy(fetch=None) -> dict[str, dict]:
    """Yahoo's adjusted closes now against the lab's copy in <data>/etf/daily."""
    from .experiments import etf_trend as et
    fetch = fetch or et.download_yahoo
    out = {}
    for s in ETFS:
        try:
            y = et.parse_stooq(fetch(s))
            c = et.parse_stooq(et.load_csv(s))
        except et.DataUnavailable as e:
            print(f"  yahoo {s}: {e}", file=sys.stderr)
            continue
        out[s] = compare({str(d): float(x) for d, x in zip(*c)}, {str(d): float(x) for d, x in zip(*y)})
        out[s]["copy_first"] = str(c[0][0])
    return out


def paxg_vs_gld(paxg: pl.DataFrame) -> dict:
    """PAXG (an ounce) against GLD (a tenth of an ounce less fees) around their median ratio: tracking error a
    year and the largest gap on the days both have."""
    from .experiments import etf_trend as et
    g = et.parse_stooq(et.load_csv("GLD"))
    gld = {str(d): float(x) for d, x in zip(*g)}
    p = by_day(paxg)
    days = sorted(set(p) & set(gld))
    if len(days) < 20:
        return {"days": len(days)}
    r = np.array([p[d] / gld[d] for d in days])
    k = float(np.median(r))
    a, b = np.array([p[d] for d in days]), np.array([gld[d] for d in days])
    te = float(np.std(np.diff(np.log(a)) - np.diff(np.log(b))) * math.sqrt(252))
    return {"days": len(days), "first": days[0], "last": days[-1], "ratio": k, "te_yr": te,
            "max_abs": float(np.max(np.abs(r / k - 1))), "over_2pct": int(np.sum(np.abs(r / k - 1) > 0.02))}


def _get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "pythia-lab"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def check(verbose: bool = True) -> dict:
    """Every overlap check; what the study's report shows."""
    from .experiments import fam_common as fc
    base = fc.build_daily_panel()
    st = read_state()
    until = st.get("until", UNTIL)
    early = {s: cached(s, until) for s, m in st.get("symbols", {}).items() if m}
    full = {s: cached(s) for s in FULL}
    bp = binance_vs_panel(base, {**early, **{s: full[s] for s in FULL if s in full}})
    out = {"binance_vs_panel": bp, "kraken_vs_binance": kraken_vs_binance(full), "yahoo_vs_copy": yahoo_vs_copy(),
           "paxg_vs_gld": paxg_vs_gld(full.get("PAXGUSDT", kd.empty())),
           "paxg_first": _d(int(full["PAXGUSDT"]["day"].min())) if full.get("PAXGUSDT") is not None
           and full["PAXGUSDT"].height else None}
    if verbose:
        n = sum(v["days"] for v in bp.values())
        o = sum(v["over"] for v in bp.values())
        print(f"binance vs panel: {len(bp)} pairs, {n} days, {o} over {DIFF_BAR:.1%}")
        for k in ("kraken_vs_binance", "yahoo_vs_copy"):
            for s, v in out[k].items():
                print(f"{k} {s}: {v['days']} days, {v['over']} over, max {v['max_abs']:.2%}")
    return out


def main(argv: list[str]) -> int:
    if argv[:1] == ["fetch"]:
        st = fetch_long(verbose=True)
        fetch_full(verbose=True)
        print(f"{sum(1 for m in st['symbols'].values() if m)} pairs with bars before {UNTIL}")
        return 0
    if argv[:1] == ["check"]:
        check()
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
