"""The point-in-time S&P 500 with opens, and the sector ETFs, for next-open fills.

The source is M9's (lab.experiments.equities_ranking: github.com/Johnbrick123/
sp500-data, release "data", cached under <data>/equities/). M9 used closes
only; X16 fills at the next open, so this panel also keeps the open, high and
low, adjusted for splits and dividends by the same day's factor (adjusted
close over close), and the raw volume.

The CRSP rows of the dataset (mostly names that later left the index, and
most rows before 2006) have a close but no open, high, low or volume. A fill
on such a day uses that day's close (`fill`), and the studies report how
often that happened.

Calendar: the days SPY traded, from 1996-01-02. The sector ETFs (and SPY) come
from the same dataset; Yahoo's chart API (lab.experiments.overnight) only
fills an ETF the dataset lacks.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ..experiments import equities_ranking as er

START = np.datetime64("1996-01-01")
SECTORS = ("XLB", "XLC", "XLE", "XLF", "XLI", "XLK", "XLP", "XLRE", "XLU", "XLV", "XLY")
ETFS = ("SPY",) + SECTORS
CACHE = er.CACHE
PANEL_FILE = "x16_panel.npz"
YEAR_DAYS = 252


@dataclass
class Panel:
    dates: np.ndarray        # (T,) datetime64[D], the days SPY traded
    names: list[str]         # (N,)
    close: np.ndarray        # (T, N) adjusted close, carried forward after the series ends, NaN before it starts
    open: np.ndarray         # (T, N) adjusted open on days with a row and a known open, else NaN
    high: np.ndarray         # (T, N) adjusted, NaN where unknown
    low: np.ndarray
    dv: np.ndarray           # (T, N) dollar volume (close x volume, both split-adjusted), NaN where unknown
    traded: np.ndarray       # (T, N) bool, a row exists that day
    alive: np.ndarray        # (T, N) bool, between the series' first and last row
    member: np.ndarray       # (T, N) bool, in the S&P 500 that day (ETFs: alive)
    extra: dict = field(default_factory=dict)

    @property
    def T(self) -> int:
        return len(self.dates)

    @property
    def N(self) -> int:
        return len(self.names)

    def col(self, name: str) -> int:
        return self.names.index(name)

    def fill(self) -> np.ndarray:
        """The price a trade on day t gets: the open, or that day's close where the open is
        unknown; carried forward after the series ends (a dead name earns nothing more)."""
        if "fill" not in self.extra:
            f = np.where(self.traded & np.isfinite(self.open), self.open, np.where(self.traded, self.close, np.nan))
            # The day after a series ends, a position is closed at the last close (not the last open).
            last = np.where(self.traded.any(0), self.T - 1 - self.traded[::-1].argmax(0), -1)
            j = np.flatnonzero((last >= 0) & (last + 1 < self.T))
            f[last[j] + 1, j] = self.close[last[j], j]
            self.extra["fill"] = er._ffill(f)
        return self.extra["fill"]

    def fill_at_close(self) -> np.ndarray:
        """(T, N) True where a fill on day t had to use the close."""
        return self.traded & ~np.isfinite(self.open)

    def r_oo(self) -> np.ndarray:
        """Open-to-open return earned by a position held from the fill of day t to the fill of t+1."""
        if "r_oo" not in self.extra:
            f = self.fill()
            r = np.zeros(f.shape)
            with np.errstate(invalid="ignore", divide="ignore"):
                r[:-1] = f[1:] / f[:-1] - 1
            self.extra["r_oo"] = np.where(np.isfinite(r), r, 0.0)
        return self.extra["r_oo"]

    def r_cc(self) -> np.ndarray:
        """Close-to-close return of day t (NaN outside the series)."""
        if "r_cc" not in self.extra:
            c = np.where(self.alive, self.close, np.nan)
            r = np.full(c.shape, np.nan)
            with np.errstate(invalid="ignore", divide="ignore"):
                r[1:] = c[1:] / c[:-1] - 1
            self.extra["r_cc"] = r
        return self.extra["r_cc"]


def _matrix(dates: np.ndarray, names: list[str], d_idx: np.ndarray, j: np.ndarray, v: np.ndarray) -> np.ndarray:
    out = np.full((len(dates), len(names)), np.nan)
    out[d_idx, j] = v
    return out


def build(prices, members, etfs: tuple[str, ...] = ETFS, start=START) -> tuple[Panel, Panel]:
    """(stocks, etfs) from the dataset's polars frames: prices (date, ticker, open, high,
    low, close, volume, adj_close) and members (ticker, start, end)."""
    import polars as pl
    px = (prices.with_columns(pl.col("date").cast(pl.Date))
          .filter(pl.col("date") >= start.astype(object))
          .filter(pl.col("adj_close") > 0)
          .unique(["ticker", "date"], keep="last"))
    tickers = set(px["ticker"].unique().to_list())
    if "SPY" not in tickers:
        raise er.DataUnavailable("no SPY in the price file")
    dates = np.array(sorted(px.filter(pl.col("ticker") == "SPY")["date"].to_list()), dtype="datetime64[D]")
    mem = members.with_columns(pl.col("start").cast(pl.Date), pl.col("end").cast(pl.Date))
    stock_names = sorted(set(mem["ticker"].to_list()) & tickers)
    etf_names = [s for s in etfs if s in tickers]

    def one(names: list[str]) -> Panel:
        col = {s: k for k, s in enumerate(names)}
        sub = px.filter(pl.col("ticker").is_in(names))
        d = sub["date"].to_numpy().astype("datetime64[D]")
        di = np.searchsorted(dates, d)
        ok = (di < len(dates)) & (dates[np.minimum(di, len(dates) - 1)] == d)
        sub = sub.filter(pl.Series(ok))
        di = di[ok]
        j = np.array([col[s] for s in sub["ticker"].to_list()])
        adj = sub["adj_close"].to_numpy().astype(float)
        raw = sub["close"].to_numpy().astype(float)
        with np.errstate(invalid="ignore", divide="ignore"):
            fac = np.where(raw > 0, adj / raw, np.nan)
        get = lambda c: sub[c].fill_null(np.nan).to_numpy().astype(float)  # noqa: E731
        o, h, lo, vol = get("open"), get("high"), get("low"), get("volume")
        o = np.where(o > 0, o * fac, np.nan)
        h = np.where(h > 0, h * fac, np.nan)
        lo = np.where(lo > 0, lo * fac, np.nan)
        dv = np.where(vol > 0, raw * vol, np.nan)
        close = _matrix(dates, names, di, j, adj)
        traded = np.isfinite(close)
        T = len(dates)
        first = np.where(traded.any(0), traded.argmax(0), T)
        last = np.where(traded.any(0), T - 1 - traded[::-1].argmax(0), -1)
        t_ix = np.arange(T)[:, None]
        alive = (t_ix >= first[None, :]) & (t_ix <= last[None, :])
        return Panel(dates=dates, names=names, close=er._ffill(close), open=_matrix(dates, names, di, j, o),
                     high=_matrix(dates, names, di, j, h), low=_matrix(dates, names, di, j, lo),
                     dv=_matrix(dates, names, di, j, dv), traded=traded, alive=alive, member=alive.copy())

    S = one(stock_names)
    member = np.zeros((S.T, S.N), dtype=bool)
    col = {s: k for k, s in enumerate(stock_names)}
    for s, a, b in mem.select("ticker", "start", "end").iter_rows():
        if s not in col:
            continue
        lo = np.searchsorted(dates, np.datetime64(a, "D"))
        hi = S.T if b is None else np.searchsorted(dates, np.datetime64(b, "D"))
        member[lo:hi, col[s]] = True
    S.member = member & S.alive
    E = one(etf_names)
    return S, E


_SAVE = ("close", "open", "high", "low", "dv", "traded", "alive", "member")


def _save(p: Panel, f: Path, prefix: str, store: dict) -> None:
    store[f"{prefix}_names"] = np.array(p.names)
    for k in _SAVE:
        a = getattr(p, k)
        store[f"{prefix}_{k}"] = a.astype(np.float32) if a.dtype == np.float64 else a


def _load(z, prefix: str, dates: np.ndarray) -> Panel:
    kw = {k: (z[f"{prefix}_{k}"].astype(np.float64) if z[f"{prefix}_{k}"].dtype == np.float32 else z[f"{prefix}_{k}"])
          for k in _SAVE}
    return Panel(dates=dates, names=[str(s) for s in z[f"{prefix}_names"]], **kw)


def load(refresh: bool = False, get=er.fetch, yahoo=None) -> tuple[Panel, Panel]:
    """(stocks, etfs), cached as <data>/equities/x16_panel.npz next to the source files.
    The cache is rebuilt when the price file changes. float32 in the cache, so a price
    carries about 7 significant digits."""
    import polars as pl
    files = er.load_files(refresh, get)
    src = files["prices.parquet"]
    key = f"{src.stat().st_size}:{int(src.stat().st_mtime)}"
    cache = CACHE / PANEL_FILE
    if cache.exists() and not refresh:
        z = np.load(cache, allow_pickle=False)
        if str(z["key"]) == key:
            dates = z["dates"].astype("datetime64[D]")
            return _load(z, "s", dates), _load(z, "e", dates)
    prices = pl.read_parquet(src, columns=["date", "ticker", "open", "high", "low", "close", "volume", "adj_close"])
    S, E = build(prices, pl.read_parquet(files["membership_intervals.parquet"]))
    missing = [s for s in ETFS if s not in E.names]
    if missing:
        E = _with_yahoo(E, missing, yahoo)
    store: dict = {"key": np.array(key), "dates": S.dates.astype("datetime64[D]").astype(str)}
    _save(S, cache, "s", store)
    _save(E, cache, "e", store)
    cache.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache.with_name(cache.stem + ".part.npz")
    np.savez_compressed(tmp, **store)
    tmp.replace(cache)
    print(f"x16 panel: {S.N} stocks, {E.N} ETFs, {S.dates[0]} to {S.dates[-1]}", file=sys.stderr, flush=True)
    return S, E


def _with_yahoo(E: Panel, missing: list[str], yahoo=None) -> Panel:
    """Add ETFs the dataset lacks from Yahoo's daily OHLC (open, close, adjusted close)."""
    from ..experiments import overnight as on
    fetch = yahoo or on.download_yahoo
    names = list(E.names)
    cols = {k: [getattr(E, k)] for k in ("close", "open", "high", "low", "dv")}
    for s in missing:
        try:
            d = on.parse_ohlc(fetch(s))
        except Exception as e:  # noqa: BLE001 - one missing ETF must not stop the panel
            print(f"x16 panel: {s} not available from Yahoo either: {e}", file=sys.stderr)
            continue
        dd = np.asarray(d["dates"], dtype="datetime64[D]")
        idx = np.searchsorted(E.dates, dd)
        ok = (idx < E.T) & (E.dates[np.minimum(idx, E.T - 1)] == dd)
        fac = d["adj"] / d["close"]
        c = np.full(E.T, np.nan)
        o = np.full(E.T, np.nan)
        c[idx[ok]] = d["adj"][ok]
        o[idx[ok]] = (d["open"] * fac)[ok]
        cols["close"].append(c[:, None])
        cols["open"].append(o[:, None])
        for k in ("high", "low", "dv"):
            cols[k].append(np.full((E.T, 1), np.nan))
        names.append(s)
    close = np.hstack(cols["close"])
    traded = np.isfinite(close)
    T = E.T
    first = np.where(traded.any(0), traded.argmax(0), T)
    last = np.where(traded.any(0), T - 1 - traded[::-1].argmax(0), -1)
    t_ix = np.arange(T)[:, None]
    alive = (t_ix >= first[None, :]) & (t_ix <= last[None, :])
    return Panel(dates=E.dates, names=names, close=er._ffill(close), open=np.hstack(cols["open"]),
                 high=np.hstack(cols["high"]), low=np.hstack(cols["low"]), dv=np.hstack(cols["dv"]),
                 traded=traded, alive=alive, member=alive.copy())


def panel_from_arrays(dates, names, close, open_=None, high=None, low=None, dv=None, member=None) -> Panel:
    """A panel from plain arrays (tests and synthetic data). NaN close = no row that day."""
    close = np.asarray(close, float)
    traded = np.isfinite(close)
    T = close.shape[0]
    first = np.where(traded.any(0), traded.argmax(0), T)
    last = np.where(traded.any(0), T - 1 - traded[::-1].argmax(0), -1)
    t_ix = np.arange(T)[:, None]
    alive = (t_ix >= first[None, :]) & (t_ix <= last[None, :])
    nan = np.full(close.shape, np.nan)
    return Panel(dates=np.asarray(dates, dtype="datetime64[D]"), names=list(names), close=er._ffill(close),
                 open=nan.copy() if open_ is None else np.where(traded, np.asarray(open_, float), np.nan),
                 high=nan.copy() if high is None else np.asarray(high, float),
                 low=nan.copy() if low is None else np.asarray(low, float),
                 dv=nan.copy() if dv is None else np.asarray(dv, float), traded=traded, alive=alive,
                 member=alive.copy() if member is None else np.asarray(member, bool) & alive)


def env_cache() -> Path:
    return Path(os.environ.get("PYTHIA_EQ_DATA", str(CACHE)))
