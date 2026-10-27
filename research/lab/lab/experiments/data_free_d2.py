"""D2: what the new free series said about next-day and next-week BTC, ETH and SPYx returns and
volatility in 2019 to 2025. A measurement, not a strategy: nothing live, no paper book.

    python -m lab.experiments.data_free_d2          reads $PYTHIA_FREE (lab.collect.pit), writes
                                                    results/data_free_d2.md and reports/data_free_d2/latest.json

Point in time. A decision is taken at the close: BTC and ETH at 00:00 UTC after the Binance
day (their daily bars), SPYx at 20:00 UTC on a US trading day (SPY's close stands for the
token, as in S2). A feature uses only rows of the lake with known_us at or before that
moment (pit.as_of), so a value published the next day (FRED's yields, DefiLlama's day) is
used a day later, and a backfilled row only from its conservative publication time.

Targets, per asset and horizon h (1 and 7 days for the coins, 1 and 5 trading days for SPY):
the log return over the next h bars, and the volatility over them relative to the trailing
one (root mean square of the next h daily returns over that of the last 30 bars, 21 for SPY),
so a feature that only knows that volatility persists does not score.

Rank IC with a purge gap: the decision days are split into h + 1 interleaved subsamples, each
with one free bar between consecutive target windows (no overlap, a gap of one), the Spearman
correlation and its t computed on each; the IC is their mean and the t their mean (each is
valid alone; the mean is conservative). p two-sided from the t. Every test run is counted:
Holm and Benjamini-Hochberg over all of them. The IC in 2019-2022 and 2023-2025 is listed too.

The option surface (ATM IV, skew, put/call OI) and Hyperliquid's open interest and mark/oracle
snapshots have no free history: they start with the collectors and are not tested.
"""

from __future__ import annotations

import json
import math
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import polars as pl
from scipy.stats import norm, rankdata, spearmanr

from ..collect import macro, pit

NAME = "data_free_d2"
RESULTS = Path(__file__).resolve().parents[2] / "results"
FROM, UNTIL = date(2019, 1, 1), date(2025, 12, 31)
HALF = date(2023, 1, 1)
UTC = timezone.utc
MIN_N = 100  # observations a subsample needs for a test to count
ASSETS = {"BTC": (1, 7), "ETH": (1, 7), "SPYx": (1, 5)}


# ---------------------------------------------------------------------------
# Prices and targets
# ---------------------------------------------------------------------------

def crypto_closes(symbol: str) -> tuple[list[date], np.ndarray]:
    from .. import history
    d = history.cached(symbol)
    return [pit.day_of(int(x)) for x in d["day"]], d["close"].to_numpy().astype(float)


def spy_closes() -> tuple[list[date], np.ndarray]:
    from ..data import ROOT
    d = pl.read_csv(ROOT / "etf" / "daily" / "SPY.csv", try_parse_dates=True).drop_nulls()
    return d["Date"].to_list(), d["Close"].to_numpy().astype(float)


def targets(days: list[date], close: np.ndarray, h: int, trail: int) -> dict[str, np.ndarray]:
    """ret: log return over the next h bars; vol: their RMS daily return over the trailing `trail` bars'."""
    r = np.diff(np.log(close), prepend=np.nan)
    n = len(close)
    ret = np.full(n, np.nan)
    vol = np.full(n, np.nan)
    for i in range(trail, n - h):
        ret[i] = math.log(close[i + h] / close[i])
        fut = math.sqrt(np.mean(r[i + 1:i + h + 1] ** 2))
        past = math.sqrt(np.mean(r[i - trail + 1:i + 1] ** 2))
        vol[i] = fut / past if past > 0 else np.nan
    return {"ret": ret, "vol": vol}


def rv_ratio(close: np.ndarray, short: int, trail: int) -> np.ndarray:
    """RMS daily return of the last `short` bars over that of the last `trail` bars, known at the close."""
    r = np.diff(np.log(close), prepend=np.nan)
    s = pl.Series(r * r)
    a = s.rolling_mean(short, min_samples=short).to_numpy()
    b = s.rolling_mean(trail, min_samples=trail).to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.sqrt(a / b)


# ---------------------------------------------------------------------------
# Features, point in time
# ---------------------------------------------------------------------------

def asof_values(rows: pl.DataFrame, cutoffs: list[int]) -> np.ndarray:
    """The value of the newest row known at each cutoff (rows: ts_us, known_us, value)."""
    if rows is None or rows.is_empty():
        return np.full(len(cutoffs), np.nan)
    r = rows.select("ts_us", "known_us", "value").drop_nulls().sort(["known_us", "ts_us"])
    # the newest described time among the rows known so far, and its value
    r = r.with_columns(best=pl.col("ts_us").cum_max()).filter(pl.col("ts_us") == pl.col("best"))
    q = pl.DataFrame({"cut": cutoffs}, schema={"cut": pl.Int64}).with_row_index("i")
    j = q.sort("cut").join_asof(r, left_on="cut", right_on="known_us", strategy="backward").sort("i")
    return j["value"].to_numpy().astype(float)


def series(source: str, table: str, name: str | None = None, col: str = "value", where: dict | None = None,
           ) -> pl.DataFrame | None:
    df = pit.read(source, table)
    if df is None:
        return None
    if name is not None:
        df = df.filter(pl.col("series") == name)
    for k, v in (where or {}).items():
        df = df.filter(pl.col(k) == v)
    return df.select("ts_us", "known_us", pl.col(col).alias("value"))


def rolling_mean_rows(rows: pl.DataFrame | None, hours: int) -> pl.DataFrame | None:
    """Hourly settlements to their trailing mean over `hours`, each known when its newest member is."""
    if rows is None or rows.is_empty():
        return None
    return rows.sort("ts_us").with_columns(ts=pl.col("ts_us").cast(pl.Datetime("us"))).with_columns(
        value=pl.col("value").rolling_mean_by("ts", window_size=f"{hours}h")).drop("ts")


def _lag(x: np.ndarray, k: int) -> np.ndarray:
    out = np.full_like(x, np.nan)
    out[k:] = x[:-k]
    return out


def feature_set(days: list[date], cut_us: list[int], coin: str, window: np.ndarray, week: int
                ) -> dict[str, np.ndarray]:
    """Every tested feature on the asset's decision days. Weekly changes are taken between the
    values known at the two cutoffs, `week` decision days apart (7 for the coins, 5 trading days
    for SPY), monthly ones 30 or 21 apart; `window` is the target window in calendar days per day
    (for the release dates)."""
    month = 30 if week == 7 else 21
    a = lambda rows: asof_values(rows, cut_us)  # noqa: E731
    out: dict[str, np.ndarray] = {}
    dv = a(series("deribit", "dvol", col="close", where={"currency": coin}))
    out["dvol"] = dv
    out["dvol_chg7"] = dv - _lag(dv, week)
    f = series("hyperliquid", "funding", col="funding_rate", where={"coin": coin})
    p = series("hyperliquid", "funding", col="premium", where={"coin": coin})
    out["hl_funding_24h"] = a(rolling_mean_rows(f, 24))
    out["hl_premium_24h"] = a(rolling_mean_rows(p, 24))
    for name in ("stables_total", "usdt", "usdc"):
        lv = np.log(a(series("defillama", "daily", name)))
        out[f"{name}_growth7"] = lv - _lag(lv, week)
        if name == "stables_total":
            out["stables_total_growth30"] = lv - _lag(lv, month)
    tot = a(series("defillama", "daily", "stables_total"))
    out["stables_total_chg1"] = a(series("defillama", "daily", "stables_total_chg")) / tot
    for name in ("dex_volume", "dex_volume_solana"):
        v = a(series("defillama", "daily", name))
        with np.errstate(divide="ignore", invalid="ignore"):
            out[f"{name}_7_30"] = np.log(_roll(v, week) / _roll(v, month))
    tvl = np.log(a(series("defillama", "daily", "tvl_solana")))
    out["tvl_solana_chg7"] = tvl - _lag(tvl, week)
    fg = a(series("fear_greed", "daily"))
    out["fear_greed"] = fg
    out["fear_greed_chg7"] = fg - _lag(fg, week)
    m = {k: a(series("macro", "daily", k)) for k in ("us2y", "us10y", "vix", "dxy", "gold")}
    out["us2y_chg7"] = m["us2y"] - _lag(m["us2y"], week)
    out["us10y_chg7"] = m["us10y"] - _lag(m["us10y"], week)
    out["curve_10y_2y"] = m["us10y"] - m["us2y"]
    out["vix"] = m["vix"]
    out["vix_chg7"] = m["vix"] - _lag(m["vix"], week)
    out["dxy_chg7"] = np.log(m["dxy"]) - np.log(_lag(m["dxy"], week))
    out["gold_chg7"] = np.log(m["gold"]) - np.log(_lag(m["gold"], week))
    cal = macro.calendar_features(days)
    out["fomc_ahead"] = _within(cal["days_to_fomc"], window)
    out["cpi_ahead"] = _within(cal["days_to_cpi"], window)
    return out


def _roll(x: np.ndarray, k: int) -> np.ndarray:
    s = pl.Series(x).rolling_mean(k, min_samples=k)
    return s.to_numpy().astype(float)


def _within(days_to: pl.Series, window: np.ndarray) -> np.ndarray:
    """1 when the next release falls inside the target window (1 to `window` calendar days after the decision)."""
    d = days_to.to_numpy().astype(float)
    return np.where(np.isnan(d), np.nan, ((d >= 1) & (d <= window)).astype(float))


# ---------------------------------------------------------------------------
# The rank IC with a purge gap
# ---------------------------------------------------------------------------

def _resid(a: np.ndarray, z: np.ndarray) -> np.ndarray:
    """Ranks of a with the ranks of z regressed out."""
    ra, rz = rankdata(a), rankdata(z)
    rz = rz - rz.mean()
    return ra - ra.mean() - rz * (rz @ (ra - ra.mean())) / max(1e-12, rz @ rz)


def purged_ic(x: np.ndarray, y: np.ndarray, h: int, z: np.ndarray | None = None) -> dict | None:
    """The rank IC of x with y (with z given: the partial rank IC, the ranks of z regressed out of both)."""
    ok = np.isfinite(x) & np.isfinite(y) & (np.isfinite(z) if z is not None else True)
    idx = np.flatnonzero(ok)
    if len(idx) < MIN_N * (h + 1):
        return None
    step = h + 1
    ics, ts, ns = [], [], []
    for o in range(step):
        sub = idx[(idx - idx[0]) % step == o]
        xs, ys = x[sub], y[sub]
        if len(sub) < MIN_N or np.ptp(xs) == 0:
            continue
        if z is None:
            rho = float(spearmanr(xs, ys).statistic)
        else:
            ex, ey = _resid(xs, z[sub]), _resid(ys, z[sub])
            rho = float(ex @ ey / math.sqrt(max(1e-12, (ex @ ex) * (ey @ ey))))
        if not math.isfinite(rho):
            continue
        ics.append(rho)
        ts.append(rho * math.sqrt((len(sub) - 2) / max(1e-12, 1 - rho * rho)))
        ns.append(len(sub))
    if not ics:
        return None
    t = float(np.mean(ts))
    return {"ic": float(np.mean(ics)), "t": t, "p": float(2 * norm.sf(abs(t))), "n": int(len(idx)),
            "n_sub": int(np.mean(ns))}


def holm(ps: list[float]) -> list[float]:
    order = np.argsort(ps)
    m = len(ps)
    adj = np.empty(m)
    run = 0.0
    for k, i in enumerate(order):
        run = max(run, min(1.0, (m - k) * ps[i]))
        adj[i] = run
    return adj.tolist()


def bh(ps: list[float]) -> list[float]:
    order = np.argsort(ps)[::-1]
    m = len(ps)
    adj = np.empty(m)
    run = 1.0
    for k, i in enumerate(order):
        run = min(run, ps[i] * m / (m - k))
        adj[i] = run
    return adj.tolist()


# ---------------------------------------------------------------------------
# The study
# ---------------------------------------------------------------------------

def asset_frame(asset: str) -> tuple[list[date], np.ndarray, list[int], int]:
    if asset == "SPYx":
        days, close = spy_closes()
        cut = [pit.us_of(d) + 20 * pit.HOUR_US for d in days]
        return days, close, cut, 21
    days, close = crypto_closes(f"{asset}USDT")
    return days, close, [pit.us_of(d + timedelta(days=1)) for d in days], 30


def run() -> dict:
    tests = []
    coverage: dict[str, dict] = {}
    for asset, horizons in ASSETS.items():
        days, close, cut, trail = asset_frame(asset)
        coin = "BTC" if asset == "SPYx" else asset
        for h in horizons:
            # the target window in calendar days: to the h-th next bar
            window = np.array([(days[min(i + h, len(days) - 1)] - days[i]).days for i in range(len(days))])
            feats = feature_set(days, cut, coin, window, 5 if asset == "SPYx" else 7)
            tg = targets(days, close, h, trail)
            rv = rv_ratio(close, 5 if asset == "SPYx" else 7, trail)
            feats["rv_7_30"] = rv  # the benchmark: the asset's own recent over trailing realized vol
            last = UNTIL - timedelta(days=h if asset != "SPYx" else 7)
            inwin = np.array([FROM <= d <= last for d in days])
            first_half = np.array([d < HALF for d in days])
            for fname, x in feats.items():
                xx = np.where(inwin, x, np.nan)
                have = np.flatnonzero(np.isfinite(xx))
                if have.size:
                    coverage.setdefault(fname, {})[asset] = [str(days[have[0]]), str(days[have[-1]])]
                for tname, y in tg.items():
                    r = purged_ic(xx, y, h)
                    if r is None:
                        continue
                    a = purged_ic(np.where(first_half, xx, np.nan), y, h)
                    b = purged_ic(np.where(~first_half, xx, np.nan), y, h)
                    c = purged_ic(xx, y, h, rv) if tname == "vol" and fname != "rv_7_30" else None
                    tests.append({"feature": fname, "asset": asset, "h": h, "target": tname, **r,
                                  "ic_2019_22": a["ic"] if a else None, "ic_2023_25": b["ic"] if b else None,
                                  "ic_net_rv": c["ic"] if c else None, "t_net_rv": c["t"] if c else None})
    ps = [t["p"] for t in tests]
    for t, ph, pb in zip(tests, holm(ps), bh(ps)):
        t["p_holm"], t["q_bh"] = ph, pb
    return {"generated": datetime.now(UTC).isoformat(timespec="seconds"), "window": [str(FROM), str(UNTIL)],
            "lake": str(pit.FREE), "tests": tests, "coverage": coverage}


MARKER = "<!-- generated below by lab.experiments.data_free_d2; edit above this line only -->"


def _f(v, nd: int = 3) -> str:
    return "" if v is None else f"{v:+.{nd}f}"


def tables(out: dict) -> str:
    tests = out["tests"]
    lines = [MARKER, "", f"Generated {out['generated']}, decision days {out['window'][0]} to {out['window'][1]}, "
             f"{len(tests)} tests counted.", ""]
    lines += ["### Coverage (first and last decision day with a value, in the window)", "",
              "| Feature | BTC | ETH | SPYx |", "|---|---|---|---|"]
    for f, cov in out["coverage"].items():
        lines.append(f"| {f} | " + " | ".join(" to ".join(cov[a]) if a in cov else "none" for a in ASSETS) + " |")
    lines += ["", "### Tests that survive Benjamini-Hochberg at 10 %", ""]
    keep = sorted((t for t in tests if t["q_bh"] <= 0.10), key=lambda t: t["p"])
    if not keep:
        lines.append("None.")
    else:
        lines += ["| Feature | Asset | h | Target | IC | t | p | Holm | BH q | IC 2019-22 | IC 2023-25 | IC net of rv "
                  "(t) | n |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for t in keep:
            net = "" if t["ic_net_rv"] is None else f"{t['ic_net_rv']:+.3f} ({t['t_net_rv']:+.2f})"
            lines.append(f"| {t['feature']} | {t['asset']} | {t['h']} | {t['target']} | {_f(t['ic'])} | "
                         f"{t['t']:+.2f} | {t['p']:.4f} | {t['p_holm']:.3f} | {t['q_bh']:.3f} | "
                         f"{_f(t['ic_2019_22'])} | {_f(t['ic_2023_25'])} | {net} | {t['n']} |")
    lines += ["", "### Every test", "",
              "| Feature | Asset | h | Target | IC | t | p | BH q | IC 2019-22 | IC 2023-25 | IC net of rv |",
              "|---|---|---|---|---|---|---|---|---|---|---|"]
    for t in sorted(tests, key=lambda t: (t["feature"], t["asset"], t["h"], t["target"])):
        lines.append(f"| {t['feature']} | {t['asset']} | {t['h']} | {t['target']} | {_f(t['ic'])} | "
                     f"{t['t']:+.2f} | {t['p']:.3f} | {t['q_bh']:.2f} | {_f(t['ic_2019_22'])} | "
                     f"{_f(t['ic_2023_25'])} | {_f(t['ic_net_rv'])} |")
    return "\n".join(lines) + "\n"


def write(out: dict) -> Path:
    p = RESULTS / f"{NAME}.md"
    head = p.read_text(encoding="utf-8").split(MARKER)[0] if p.exists() else "# D2: free data\n\n"
    p.write_text(head + tables(out), encoding="utf-8")
    return p


def main() -> int:
    out = run()
    from .. import report
    d = report.REPORTS / NAME
    try:
        d.mkdir(parents=True, exist_ok=True)
        (d / "latest.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    except OSError as e:
        print(f"  no report copy ({e})", file=sys.stderr)
    print(f"{len(out['tests'])} tests, {sum(t['q_bh'] <= 0.10 for t in out['tests'])} at BH q <= 0.10, "
          f"{sum(t['p_holm'] <= 0.05 for t in out['tests'])} at Holm 5 % -> {write(out)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
