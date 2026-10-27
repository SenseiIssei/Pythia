"""C1: the collectors that keep lab.candles.store current. Public endpoints only, no key, read only.

    python -m lab.candles.live live       every 10 minutes (job candles-live): the last days of Binance spot 1m
                                          from the public klines REST endpoint for the lab's coins and PAXG
                                          (the archive lags about a day), then 1m candles from the recorded
                                          Kraken trades, each minute against Binance's (ref_dev_bps)
    python -m lab.candles.live markets    hourly (job candles-markets): GeckoTerminal 1h and 1d of the
                                          xStocks tokens, PAXG and the on-chain coins' deepest Solana pools
                                          with their liquidity; Yahoo 1d and 1h of the underlyings every
                                          yahoo_every_h hours

Binance: GET /api/v3/klines (weight 2, 1000 bars a call) from the newest bar the archive or the store has,
at most rest_max_days back; a bar is kept only once closed. Kraken: <data>/kraken/trades, a finished day
rebuilt whole when its files change (the recorder compacts it into day.parquet), today's minutes once the
recorder has received a minute past their end; open/high/low/close by exchange time, volume, quote
volume, trades, the buy side (Kraken's side is the taker's) as taker buy volume, VWAP. The minutes stay in
the store when the recorder's retention removes the raw trades.

GeckoTerminal (polite: one call per gecko_gap_s, gecko_calls_per_run a run, a 429 ends the run's calls to
it and backs it off 2 minutes, doubling to 30, while 429s go on): the pool of a token is the deepest against USDC or SOL, looked up every pool_refresh_days; the pools'
liquidity in one /pools/multi call a run, put on the newest closed bar; each run asks for the bars since
the newest stored, then walks the 1h history back gecko_hour_days (the keyless API's reach). Mints: the
coins' from lab.onchain.mints, the tokens' from results/smallaccount_s2_tokens.csv (S2's list).
Yahoo: v8 chart, 1d from yahoo_from, 1h the last yahoo_1h_days; a daily bar is complete from the next UTC
midnight. Settings in lab/candles/markets.json. State: <write root>/candles/state.json.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import polars as pl

from .. import data
from . import store as S

MIN, HOUR, DAY = S.MIN, S.HOUR, S.DAY
KRAKEN_LAG_US = 60_000_000          # a minute is built once a trade received this long after its end was seen
GECKO = "https://api.geckoterminal.com/api/v2/networks/solana"
YAHOO = "https://query1.finance.yahoo.com/v8/finance/chart/{}?period1={}&period2={}&interval={}"
TOKENS_CSV = Path(__file__).resolve().parents[2] / "results" / "smallaccount_s2_tokens.csv"
GECKO_TF = {"1h": "hour", "1d": "day"}
BACKOFF_MIN_S, BACKOFF_MAX_S = 120, 1800


class RateLimited(OSError):
    pass


class Http:
    """GET JSON with a minimum gap and a call budget per host; a 429 blocks the host for the rest of the run."""

    def __init__(self, gaps: dict[str, float] | None = None, budgets: dict[str, int] | None = None,
                 sleep=time.sleep, clock=time.monotonic, opener=None):
        self.gaps, self.budgets = gaps or {}, budgets or {}
        self.calls: dict[str, int] = {}
        self.last: dict[str, float] = {}
        self.blocked: set[str] = set()
        self.sleep, self.clock = sleep, clock
        self.opener = opener or urllib.request.urlopen

    def __call__(self, url: str):
        host = url.split("/")[2]
        if host in self.blocked:
            raise RateLimited(f"{host} rate limited in this run")
        if self.calls.get(host, 0) >= self.budgets.get(host, 10**9):
            raise RateLimited(f"{host}: this run's budget is spent")
        wait = self.last.get(host, -1e9) + self.gaps.get(host, 0.0) - self.clock()
        if wait > 0:
            self.sleep(wait)
        self.last[host] = self.clock()
        self.calls[host] = self.calls.get(host, 0) + 1
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (pythia-lab candles, read only)",
                                                   "Accept": "application/json"})
        try:
            with self.opener(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code in (418, 429):
                self.blocked.add(host)
                raise RateLimited(f"{host} HTTP {e.code}") from e
            raise


def load_state(root: Path | None = None) -> dict:
    for base in reversed(S.store_dirs(root)):
        try:
            return json.loads((base / "state.json").read_text())
        except (OSError, ValueError):
            continue
    return {}


def save_state(st: dict, root: Path | None = None) -> None:
    S._write_json(S.out_dir(root) / "state.json", st)


def _last_end(source: str, asset: str, tf: str, root: Path | None = None) -> int:
    e = S.read_manifest(root).get("markets", {}).get(f"{source}/{asset}/{tf}") or {}
    return int(e.get("last_end_us") or 0)


def _first_open(source: str, asset: str, tf: str, root: Path | None = None) -> int:
    e = S.read_manifest(root).get("markets", {}).get(f"{source}/{asset}/{tf}") or {}
    return int(e.get("first_us") or 0)


# ---------------------------------------------------------------- Binance REST

def binance_rows(payload: list, fetched: int) -> pl.DataFrame:
    """/api/v3/klines rows to the store's columns; the bar still forming is dropped."""
    rows = [{"open_time_us": int(k[0]) * 1000, "open": float(k[1]), "high": float(k[2]), "low": float(k[3]),
             "close": float(k[4]), "volume": float(k[5]), "quote_volume": float(k[7]), "trades": int(k[8]),
             "taker_buy_volume": float(k[9]), "taker_buy_quote_volume": float(k[10]), "fetched_us": fetched}
            for k in payload or []]
    if not rows:
        return S.norm(pl.DataFrame())
    df = pl.DataFrame(rows).with_columns(close_time_us=pl.col("open_time_us") + MIN)
    return S.norm(df).filter(pl.col("close_time_us") <= fetched)


def archive_end(asset: str, root: Path | None = None) -> int:
    """The end of the newest 1m bar in the Binance archive (0 without one)."""
    d = S.archive_dir("1m", asset, root)
    files = sorted(d.glob("*.parquet"), key=lambda p: p.stem) if d.is_dir() else []
    for f in reversed(files[-3:]):
        try:
            t = pl.read_parquet(f, columns=["open_time_us"])
        except (OSError, pl.exceptions.PolarsError):
            continue
        if t.height:
            return int(t["open_time_us"].max()) + MIN
    return 0


def fill_binance(get, assets: list[str], now: int, cfg: dict, root: Path | None = None) -> dict:
    """The 1m bars after the archive's and the store's newest, at most rest_max_days back."""
    base = cfg.get("rest_base", "https://api.binance.com")
    out, errors = {}, []
    for a in assets:
        start = max(archive_end(a, root), _last_end("binance_rest", a, "1m", root),
                    now - int(cfg.get("rest_max_days", 3) * DAY))
        n = 0
        for _ in range(8):
            if start + MIN > now:
                break
            try:
                payload = get(f"{base}/api/v3/klines?symbol={a}USDT&interval=1m&startTime={start // 1000}&limit=1000")
            except RateLimited as e:
                errors.append(str(e))
                return {"rows": out, "errors": errors}
            except (OSError, ValueError) as e:
                errors.append(f"{a}: {e}")
                break
            rows = binance_rows(payload, now)
            if not rows.height:
                break
            n += S.write("binance_rest", a, "1m", rows, now, root)
            start = int(rows["close_time_us"].max())
            if len(payload) < 1000:
                break
        out[a] = n
    return {"rows": out, "errors": errors}


# ---------------------------------------------------------------- Kraken trades to 1m

def kraken_minutes(trades: pl.DataFrame) -> pl.DataFrame:
    """Recorded Kraken trades (ts_exch_us, ts_recv_us, symbol, side, price, qty) to 1m bars per asset."""
    if not trades.height:
        return S.norm(pl.DataFrame()).with_columns(asset=pl.lit(None, pl.String))
    buy = pl.col("side") == "buy"
    t = (trades.filter(pl.col("symbol").str.ends_with("/USD"))
         .with_columns(asset=pl.col("symbol").str.split("/").list.first(), q=pl.col("price") * pl.col("qty"),
                       m=pl.col("ts_exch_us") // MIN * MIN)
         .sort("ts_exch_us", *(["trade_id"] if "trade_id" in trades.columns else [])))
    g = t.group_by("asset", "m", maintain_order=True).agg(
        pl.col("price").first().alias("open"), pl.col("price").max().alias("high"), pl.col("price").min().alias("low"),
        pl.col("price").last().alias("close"), pl.col("qty").sum().alias("volume"), pl.col("q").sum().alias("quote_volume"),
        pl.len().cast(pl.Int64).alias("trades"), pl.col("qty").filter(buy).sum().alias("taker_buy_volume"),
        pl.col("q").filter(buy).sum().alias("taker_buy_quote_volume"), pl.col("ts_recv_us").max().alias("fetched_us"))
    return g.with_columns(open_time_us=pl.col("m"), close_time_us=pl.col("m") + MIN).drop("m").sort("asset", "open_time_us")


def kraken_files(day_dir: Path) -> list[Path]:
    day = day_dir / "day.parquet"
    return [day] if day.exists() else sorted(day_dir.glob("part-*.parquet"))


def _sig(files: list[Path]) -> str:
    return "|".join(f"{f.name}:{f.stat().st_size}:{f.stat().st_mtime_ns}" for f in files)


def with_reference(rows: pl.DataFrame, asset: str, now: int, root: Path | None = None) -> pl.DataFrame:
    """ref_dev_bps: the Kraken close against Binance's 1m close of the same minute (null without one)."""
    if not rows.height:
        return rows
    lo, hi = int(rows["open_time_us"].min()), int(rows["open_time_us"].max()) + MIN
    b = S.candles(asset, "1m", lo, hi, source="binance", as_of=now, root=root)
    if not b.height:
        return rows.with_columns(ref_dev_bps=pl.lit(None, pl.Float64))
    b = b.select("open_time_us", pl.col("close").alias("_b"))
    return (rows.drop("ref_dev_bps", strict=False).join(b, on="open_time_us", how="left")
            .with_columns(ref_dev_bps=pl.when(pl.col("_b") > 0).then((pl.col("close") / pl.col("_b") - 1) * 1e4))
            .drop("_b"))


def build_kraken(now: int, state: dict, root: Path | None = None) -> dict:
    """Finished days whose files changed, rebuilt whole; today's minutes after the last one written."""
    st = state.setdefault("kraken", {"days": {}, "last": {}})
    src = (root or data.ROOT) / "kraken" / "trades"
    today = datetime.fromtimestamp(now / 1e6, timezone.utc).strftime("%Y-%m-%d")
    written, flagged = 0, 0
    for d in sorted(src.glob("date=*")) if src.is_dir() else []:
        day = d.name.removeprefix("date=")
        files = kraken_files(d)
        if not files or day > today:
            continue
        sig = _sig(files)
        finished = day < today
        if finished and st["days"].get(day) == sig:
            continue
        cols = ["ts_exch_us", "ts_recv_us", "symbol", "side", "price", "qty", "trade_id"]
        try:
            trades = pl.concat([pl.read_parquet(f, columns=cols) for f in files], how="vertical_relaxed")
        except (OSError, pl.exceptions.PolarsError):
            continue
        m = kraken_minutes(trades)
        if not m.height:
            continue
        cutoff = (int(trades["ts_recv_us"].max()) - KRAKEN_LAG_US) // MIN * MIN
        if not (finished and (d / "day.parquet").exists()):
            m = m.filter(pl.col("close_time_us") <= cutoff)
        for (a,), rows in m.group_by(["asset"], maintain_order=True):
            if not finished:
                rows = rows.filter(pl.col("open_time_us") >= int(st["last"].get(a) or 0))
            rows = with_reference(rows.drop("asset"), a, now, root)
            if not rows.height:
                continue
            written += S.write("kraken", a, "1m", rows, now, root)
            flagged += rows.filter(pl.col("ref_dev_bps").abs() > S.DISAGREE_BPS).height
            st["last"][a] = max(int(st["last"].get(a) or 0), int(rows["close_time_us"].max()))
        if finished:
            st["days"][day] = sig
    return {"rows": written, "flagged": flagged}


# ---------------------------------------------------------------- GeckoTerminal

def mints(cfg: dict, tokens_csv: Path = TOKENS_CSV) -> dict[str, str]:
    """asset -> mint: the configured on-chain coins (lab.onchain.mints) and tokens (S2's list)."""
    from ..onchain import mints as M
    out = {c: M.COINS[c].mint for c in cfg.get("coins", []) if c in M.COINS}
    want = set(cfg.get("tokens", []))
    if tokens_csv.exists():
        with tokens_csv.open(encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                if r.get("symbol") in want and r.get("mint"):
                    out.setdefault(r["symbol"], r["mint"])
    return out


def pick_pool(payload: dict, mint: str) -> dict | None:
    """The deepest pool of the token against USDC or SOL: {pool, side, liquidity_usd}."""
    from ..onchain import mints as M
    best = None
    for p in (payload or {}).get("data") or []:
        a, rel = p.get("attributes") or {}, p.get("relationships") or {}
        base = ((rel.get("base_token") or {}).get("data") or {}).get("id", "")
        quote = ((rel.get("quote_token") or {}).get("data") or {}).get("id", "")
        side = "base" if base.endswith(mint) else "quote" if quote.endswith(mint) else None
        other = quote if side == "base" else base
        if side is None or not other.endswith((M.USDC.mint, M.SOL.mint)) or other.endswith(mint):
            continue
        liq = float(a.get("reserve_in_usd") or 0.0)
        if best is None or liq > best["liquidity_usd"]:
            best = {"pool": a.get("address"), "side": side, "liquidity_usd": liq}
    return best


def gecko_rows(payload: dict, tf: str, fetched: int, liquidity: float | None = None) -> pl.DataFrame:
    """An ohlcv answer ([ts, o, h, l, c, volume in USD]) to the store's columns; the forming bar dropped, the
    liquidity on the newest closed bar."""
    lst = (((payload or {}).get("data") or {}).get("attributes") or {}).get("ohlcv_list") or []
    p = S.TF[tf]
    rows = [{"open_time_us": int(c[0]) * 1_000_000, "open": float(c[1]), "high": float(c[2]), "low": float(c[3]),
             "close": float(c[4]), "quote_volume": float(c[5]), "fetched_us": fetched} for c in lst if len(c) >= 6]
    if not rows:
        return S.norm(pl.DataFrame())
    df = (pl.DataFrame(rows).with_columns(close_time_us=pl.col("open_time_us") + p)
          .filter(pl.col("close_time_us") <= fetched).unique("open_time_us").sort("open_time_us"))
    if liquidity is not None and df.height:
        df = df.with_columns(liquidity_usd=pl.when(pl.col("close_time_us") > fetched - p).then(pl.lit(float(liquidity))))
    return S.norm(df)


def _ohlcv_url(pool: dict, tf: str, limit: int, before: int | None = None) -> str:
    return (f"{GECKO}/pools/{pool['pool']}/ohlcv/{GECKO_TF[tf]}?aggregate=1&limit={limit}&currency=usd"
            f"&token={pool['side']}" + (f"&before_timestamp={before}" if before else ""))


def run_gecko(get, cfg: dict, state: dict, now: int, root: Path | None = None, tokens_csv: Path = TOKENS_CSV) -> dict:
    gs = state.setdefault("gecko", {"pools": {}, "backfilled": {}})
    pools, done = gs["pools"], gs["backfilled"]
    errors, rows = [], 0
    bo = gs.get("backoff") or {}
    if now < int(bo.get("until_us") or 0):
        return {"rows": 0, "pools": len(pools), "errors": [f"gecko backing off for {bo.get('secs')} s after a 429"]}
    ms = mints(cfg, tokens_csv)

    def lookup(due) -> None:
        """The pools a token's due(pool or None) asks for, its deepest against USDC or SOL."""
        for a, mint in ms.items():
            if due(pools.get(a)):
                best = pick_pool(get(f"{GECKO}/tokens/{mint}/pools?page=1"), mint)
                if best:
                    pools[a] = {**best, "at_us": now}

    try:
        lookup(lambda p: not p)                                     # new tokens first: no bars without a pool
        live = [a for a in ms if a in pools]
        due = [(tf, a, _last_end("gecko", a, tf, root)) for tf in ("1h", "1d") for a in live]
        due = [(tf, a, last) for tf, a, last in due if not last or now - last >= S.TF[tf]]
        liq = {}
        hourly = [a for tf, a, _ in due if tf == "1h"]
        for i in range(0, len(hourly), 30):                         # the pools' liquidity now, one call per 30
            chunk = hourly[i:i + 30]
            ans = get(f"{GECKO}/pools/multi/{','.join(pools[a]['pool'] for a in chunk)}") or {}
            by = {(x.get("attributes") or {}).get("address"): float((x.get("attributes") or {}).get("reserve_in_usd") or 0)
                  for x in ans.get("data") or []}
            liq.update({a: by.get(pools[a]["pool"]) for a in chunk})
        for tf, a, last in due:                                     # the bars since the newest stored
            limit = 1000 if not last else int(min(1000, (now - last) // S.TF[tf] + 2))
            r = gecko_rows(get(_ohlcv_url(pools[a], tf, limit)), tf, now, liq.get(a) if tf == "1h" else None)
            rows += S.write("gecko", a, tf, r, now, root)
        refresh = cfg.get("pool_refresh_days", 7) * DAY             # known pools again every few days, after the bars
        lookup(lambda p: p is not None and now - int(p.get("at_us") or 0) >= refresh)
        for a in live:                                              # the 1h history, back as far as the API goes
            if done.get(a):
                continue
            first = _first_open("gecko", a, "1h", root)
            if not first:
                continue
            if first <= now - cfg.get("gecko_hour_days", 180) * DAY:
                done[a] = True
                continue
            r = gecko_rows(get(_ohlcv_url(pools[a], "1h", 1000, first // 1_000_000)), "1h", now)
            r = r.filter(pl.col("open_time_us") < first)
            if not r.height:
                done[a] = True
                continue
            rows += S.write("gecko", a, "1h", r, now, root)
        gs.pop("backoff", None)
    except RateLimited as e:
        errors.append(str(e))
        if "HTTP" in str(e):                                        # 2 minutes, doubling up to 30 after each 429
            secs = min(BACKOFF_MAX_S, max(BACKOFF_MIN_S, 2 * int(bo.get("secs") or 0)))
            gs["backoff"] = {"secs": secs, "until_us": now + secs * 1_000_000}
    except (OSError, ValueError) as e:
        errors.append(f"gecko: {e}")
    return {"rows": rows, "pools": len(pools), "errors": errors}


# ---------------------------------------------------------------- Yahoo

def yahoo_rows(payload: dict, tf: str, fetched: int) -> pl.DataFrame:
    """A v8 chart answer to the store's columns: 1d bars open at 00:00 UTC of the trading day and close at the
    next midnight, 1h bars at their own start; bars not closed by `fetched` and empty ones dropped."""
    try:
        r = payload["chart"]["result"][0]
        ts, q = r.get("timestamp") or [], r["indicators"]["quote"][0]
    except (KeyError, IndexError, TypeError):
        return S.norm(pl.DataFrame())
    rows = []
    for i, t in enumerate(ts):
        o, h, lo, c, v = (q.get(k, [None] * len(ts))[i] for k in ("open", "high", "low", "close", "volume"))
        if None in (o, h, lo, c):
            continue
        start = int(t) * 1_000_000
        start = start // DAY * DAY if tf == "1d" else start
        rows.append({"open_time_us": start, "close_time_us": start + S.TF[tf], "open": float(o), "high": float(h),
                     "low": float(lo), "close": float(c), "volume": None if v is None else float(v), "fetched_us": fetched})
    if not rows:
        return S.norm(pl.DataFrame())
    return (S.norm(pl.DataFrame(rows)).filter(pl.col("close_time_us") <= fetched)
            .unique("open_time_us", keep="last").sort("open_time_us"))


def run_yahoo(get, cfg: dict, state: dict, now: int, root: Path | None = None) -> dict:
    ys = state.setdefault("yahoo", {})
    if now - int(ys.get("at_us") or 0) < cfg.get("yahoo_every_h", 6) * HOUR:
        return {"rows": 0, "skipped": True, "errors": []}
    rows, errors = 0, []
    t_from = S.to_us(cfg.get("yahoo_from", "2000-01-01"))
    for tk in cfg.get("yahoo", []):
        for tf, interval, floor in (("1d", "1d", t_from), ("1h", "60m", now - cfg.get("yahoo_1h_days", 729) * DAY)):
            last = _last_end("yahoo", tk, tf, root)
            p1 = max(floor, last - (10 * DAY if tf == "1d" else 2 * DAY)) if last else floor
            try:
                ans = get(YAHOO.format(tk, p1 // 1_000_000, now // 1_000_000, interval))
            except RateLimited as e:
                errors.append(str(e))
                return {"rows": rows, "errors": errors}
            except (OSError, ValueError) as e:
                errors.append(f"{tk} {tf}: {e}")
                continue
            rows += S.write("yahoo", tk, tf, yahoo_rows(ans, tf, now), now, root)
    if not errors:
        ys["at_us"] = now
    return {"rows": rows, "errors": errors}


# ---------------------------------------------------------------- runs

def live_assets(cfg: dict) -> list[str]:
    return list(dict.fromkeys(list(data.UNIVERSE) + cfg.get("binance_extra", [])))


def run_live(get=None, now: int | None = None, root: Path | None = None) -> dict:
    cfg, now = S.config(), now or S.now_us()
    get = get or Http(gaps={"api.binance.com": 0.2})
    state = load_state(root)
    b = fill_binance(get, live_assets(cfg), now, cfg, root)
    k = build_kraken(now, state, root)
    state.setdefault("runs", {})["live"] = {"at_us": now, "binance": sum(b["rows"].values()), "kraken": k["rows"],
                                            "flagged": k["flagged"], "errors": b["errors"][:5]}
    save_state(state, root)
    return state["runs"]["live"]


def run_markets(get=None, now: int | None = None, root: Path | None = None, tokens_csv: Path = TOKENS_CSV) -> dict:
    cfg, now = S.config(), now or S.now_us()
    get = get or Http(gaps={"api.geckoterminal.com": float(cfg.get("gecko_gap_s", 6.0)), "query1.finance.yahoo.com": 1.0},
                      budgets={"api.geckoterminal.com": int(cfg.get("gecko_calls_per_run", 40))})
    state = load_state(root)
    g = run_gecko(get, cfg, state, now, root, tokens_csv)
    y = run_yahoo(get, cfg, state, now, root)
    state.setdefault("runs", {})["markets"] = {"at_us": now, "gecko": g["rows"], "pools": g["pools"],
                                               "yahoo": y["rows"], "errors": (g["errors"] + y["errors"])[:5]}
    save_state(state, root)
    return state["runs"]["markets"]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m lab.candles.live")
    ap.add_argument("command", choices=["live", "markets"])
    a = ap.parse_args(argv)
    res = run_live() if a.command == "live" else run_markets()
    print(json.dumps(res, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
