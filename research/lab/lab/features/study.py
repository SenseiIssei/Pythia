"""Coverage and rank IC of every registered feature: results/feature_store_d3.md.

Coverage per feature: the first and last time a value is known (any asset), how many assets, and the gap
days between (UTC days without any value).

Rank IC: at every hour end t (hourly features) and every day close (daily features) the feature as known at t
against the next hour's and the next day's return of the 20 lab coins (Binance spot 1h closes, USDT).
A coin feature is scored across the coins at each t (Spearman, at least MIN_ASSETS coins) and the IC is the
mean over the t's. A market feature (one value for all coins) has no cross-section: it is scored over time
against the next return of the coins' equal-weighted average (Spearman: the mean over t of the product of
the two standardised ranks). Features move slowly (a 7-day change, a daily index read every hour), so the
t-statistic of that mean is Newey-West's with LAGS of a week of hours or ten days, not sqrt(n). Every
(feature, horizon) with data is one test; the p-values are two-sided and judged at 5 % after Bonferroni and
Benjamini-Hochberg over all of them.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

import numpy as np
import polars as pl

from ..data import UNIVERSE
from . import registry as R
from . import store

MIN_ASSETS = 5
LAGS = {"1h": 168, "1d": 10}
HORIZONS = (("1h", "next hour"), ("1d", "next day"))


def day(us) -> str:
    return "" if us is None else datetime.fromtimestamp(us / 1e6, timezone.utc).strftime("%Y-%m-%d")


def coverage(names: list[str] | None = None, log=print) -> dict:
    """{feature: {first_us, last_us, assets, gap_days, gaps (the first few as from..to)}} from the hourly
    values (daily for daily-native features); none for a feature without data."""
    out = {}
    for n in names or R.names():
        f = R.get(n)
        v = R.values(n, "1d" if f.native == "1d" else "1h")
        if not v.height:
            out[n] = {"first_us": None, "last_us": None, "assets": 0, "gap_days": 0, "gaps": []}
            continue
        days = np.unique(v["known_us"].to_numpy() // R.DAY)
        allday = np.arange(days.min(), days.max() + 1)
        miss = np.setdiff1d(allday, days)
        runs = []
        for d in miss:
            if runs and d == runs[-1][1] + 1:
                runs[-1][1] = d
            else:
                runs.append([d, d])
        out[n] = {"first_us": int(v["known_us"].min()), "last_us": int(v["known_us"].max()),
                  "assets": int(v.filter(pl.col("asset") != R.MARKET)["asset"].n_unique()) or 1,
                  "gap_days": int(len(miss)),
                  "gaps": [f"{day(int(a) * R.DAY)}..{day(int(b) * R.DAY)}" for a, b in runs[:5]]}
        log(f"  coverage {n}: {day(out[n]['first_us'])} to {day(out[n]['last_us'])}, {out[n]['gap_days']} gap days")
    return out


def prices(assets=UNIVERSE) -> pl.DataFrame:
    """(t, asset, px): the close known at t (the close of the 1h bar that ends at t)."""
    rows = []
    for a in assets:
        d = store.ROOT / "hist" / "binance_spot" / "klines_1h" / f"symbol={a}USDT"
        files = sorted(d.glob("*.parquet"))
        if files:
            k = pl.concat([pl.read_parquet(f, columns=["open_time_us", "close"]) for f in files], how="vertical_relaxed")
            rows.append(k.select(t=pl.col("open_time_us") + R.HOUR, px="close").unique("t").with_columns(asset=pl.lit(a)))
    return pl.concat(rows).sort("asset", "t") if rows else pl.DataFrame(
        schema={"t": pl.Int64, "px": pl.Float64, "asset": pl.String})


def forward(px: pl.DataFrame, freq: str) -> pl.DataFrame:
    """(ts_us, asset, y): the return from t to t + one bucket, on the bucket's grid."""
    p = R.PERIOD[freq]
    g = px.filter(pl.col("t") % p == 0)
    nxt = g.select("asset", t=pl.col("t") - p, px1="px")
    return (g.join(nxt, on=["asset", "t"]).select(ts_us="t", asset="asset", y=pl.col("px1") / pl.col("px") - 1)
            .filter(pl.col("y").is_finite()))


def hac_t(x: np.ndarray, lags: int) -> float:
    """The t-statistic of the mean of x with Newey-West (Bartlett) standard errors."""
    x = np.asarray(x, dtype=float)
    n = len(x)
    if n < 3:
        return float("nan")
    e = x - x.mean()
    v = e @ e / n
    for k in range(1, min(lags, n - 1) + 1):
        v += 2 * (1 - k / (lags + 1)) * (e[k:] @ e[:-k]) / n
    return float(x.mean() / math.sqrt(v / n)) if v > 0 else float("nan")


def _p(t: float) -> float:
    return math.erfc(abs(t) / math.sqrt(2)) if math.isfinite(t) else float("nan")


def ic(name: str, freq: str, y: pl.DataFrame) -> dict | None:
    """One test: {ic, t, p, n (time points), from, to} or None without data."""
    f = R.get(name)
    if not y.height:
        return None
    v = R.values(name, freq)
    if not v.height:
        return None
    lo, hi = max(int(v["known_us"].min()), int(y["ts_us"].min())), int(y["ts_us"].max())
    yy = y.filter((pl.col("ts_us") >= lo) & (pl.col("ts_us") <= hi))
    if not yy.height:
        return None
    x = R.frame([name], yy["asset"].unique().to_list(), yy["ts_us"].unique().to_list(), freq)
    d = yy.join(x, on=["ts_us", "asset"]).drop_nulls(name)
    if f.market:
        m = d.group_by("ts_us").agg(pl.col(name).first(), pl.col("y").mean()).sort("ts_us")
        n = m.height
        if n < 20:
            return None
        z = m.select(((c := pl.col(x).rank()) - c.mean()) / c.std(ddof=0) for x in (name, "y"))
        u = (z[name] * z["y"]).to_numpy()
        if not np.isfinite(u).all():
            return None
        r = float(u.mean())
        t = hac_t(u, LAGS[freq])
        frm, to = int(m["ts_us"].min()), int(m["ts_us"].max())
    else:
        per = (d.group_by("ts_us").agg(n=pl.len(), r=pl.corr(name, "y", method="spearman"))
               .filter((pl.col("n") >= MIN_ASSETS) & pl.col("r").is_finite()))
        n = per.height
        if n < 10:
            return None
        rs = per.sort("ts_us")["r"].to_numpy()
        r = float(rs.mean())
        t = hac_t(rs, LAGS[freq])
        frm, to = int(per["ts_us"].min()), int(per["ts_us"].max())
    return {"ic": r, "t": t, "p": _p(t), "n": n, "from": day(frm), "to": day(to)}


def bh(ps: list[float], q: float = 0.05) -> list[bool]:
    """Benjamini-Hochberg: which of the p-values are discoveries at false discovery rate q."""
    m = len(ps)
    order = sorted(range(m), key=lambda i: ps[i])
    k = max((r + 1 for r, i in enumerate(order) if ps[i] <= q * (r + 1) / m), default=0)
    out = [False] * m
    for r, i in enumerate(order):
        out[i] = r < k
    return out


def run(log=print) -> dict:
    cov = coverage(log=log)
    px = prices()
    ys = {freq: forward(px, freq) for freq, _ in HORIZONS}
    tests = []
    for n in R.names():
        for freq, label in HORIZONS:
            r = ic(n, freq, ys[freq])
            if r:
                tests.append({"feature": n, "horizon": label, **r})
                log(f"  ic {n} {label}: {r['ic']:+.4f} (t {r['t']:+.2f}, n {r['n']})")
    m = len(tests)
    disc = bh([x["p"] for x in tests])
    for x, d in zip(tests, disc):
        x["bonferroni"] = bool(x["p"] < 0.05 / m) if m else False
        x["bh"] = bool(d)
    return {"coverage": cov, "tests": tests, "m": m}


def report(res: dict) -> str:
    cov, tests, m = res["coverage"], res["tests"], res["m"]
    md = ["# D3: the point-in-time feature store", "",
          f"Built {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC from the lab's data by "
          "`python -m lab.features report`. Each feature is known at the end of its bucket (an hour or a UTC day, "
          "by the time this machine received the raw row) plus its delay; `lab.features.frame` never returns a "
          "value later than that (tests/test_features.py changes every raw row after t and checks that nothing "
          "at or before t moves).", "",
          "## Features and coverage", "",
          "| Feature | Sources | Native | Delay | Kind | From | To | Assets | Gap days | What |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for n in R.names():
        f, c = R.get(n), cov.get(n, {})
        kind = "market" if f.market else ("level" if f.level else "coin")
        delay = f"{f.delay_us // R.HOUR} h" if f.delay_us else "0"
        gaps = str(c.get("gap_days", 0)) + (f" ({', '.join(c['gaps'][:2])})" if c.get("gaps") else "")
        md.append(f"| `{n}` | {', '.join(f.sources)} | {f.native} | {delay} | {kind} | "
                  f"{day(c.get('first_us')) or 'no data'} | {day(c.get('last_us'))} | {c.get('assets', 0)} | "
                  f"{gaps if c.get('first_us') else ''} | {f.about} |")
    nb = sum(t["bonferroni"] for t in tests)
    nd = sum(t["bh"] for t in tests)
    md += ["", "## Rank IC against the next hour and the next day", "",
           f"{m} tests (every feature and horizon with data). Coin features: mean cross-sectional Spearman over "
           f"the 20 lab coins; market features: Spearman over time against the coins' equal-weighted next return. "
           f"Significant at 5 % after Bonferroni (p < {0.05 / max(m, 1):.5f}): {nb}; after Benjamini-Hochberg: {nd}.",
           "", "| Feature | Horizon | IC | t | p | Points | From | To | Bonferroni | BH |",
           "|---|---|---|---|---|---|---|---|---|---|"]
    for t in sorted(tests, key=lambda x: x["p"]):
        md.append(f"| `{t['feature']}` | {t['horizon']} | {t['ic']:+.4f} | {t['t']:+.2f} | {t['p']:.4f} | {t['n']:,} | "
                  f"{t['from']} | {t['to']} | {'yes' if t['bonferroni'] else 'no'} | {'yes' if t['bh'] else 'no'} |")
    none = [n for n in R.names() if not cov.get(n, {}).get("first_us")]
    if none:
        md += ["", "No data yet (the D2 collectors have not written these files): "
               + ", ".join(f"`{n}`" for n in none) + "."]
    return "\n".join(md) + "\n"
