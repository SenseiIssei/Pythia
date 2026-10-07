"""Family 5: calendar seasonality in BTC and ETH, with multiple-testing control.

66 hypotheses, tested on 2020-08 to 2023 only, on hourly closes:
  hour of day     24 per coin: is the mean return in this UTC hour different from the rest?
  day of week     7 per coin, on daily returns
  weekend         Saturday and Sunday against weekdays
  turn of month   the last day and the first three days of a month against the rest
Welch t-tests; Benjamini-Hochberg at a 5 % false discovery rate and Holm at 5 %
over all 66 together. The full table, with the same statistics out of sample,
is printed below the variants.

Tradable rules (12 variants), long the coin only inside the chosen windows,
flat (cash) otherwise. Turnover is two units each time a window opens and
closes, charged on the day it happens:
  hours BH        the hours that are positive and significant after BH (none: flat)
  hours top 3     the 3 hours with the highest in-sample t, no correction (the naive way)
  weekdays BH     the weekdays positive and significant after BH
  weekdays top 2  the 2 best weekdays in sample, no correction
  weekdays only   long Monday to Friday, flat at weekends (fixed in advance)
  turn of month   long the last day and the first three days of each month (fixed in advance)
"""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import polars as pl
from scipy import stats

from . import fam_common as fc
from ..data import HOUR_US

FAMILY = "season"
COINS = ["BTC", "ETH"]
_cache: dict = {}


def hourly_returns(P: fc.Panel, coin: str) -> tuple[np.ndarray, np.ndarray]:
    """(open_time_us, return of that hour), consecutive hours only."""
    from .picks import hourly_segments
    h = hourly_segments(f"{coin}USDT")[-1].sort("open_time_us")
    t = h["open_time_us"].to_numpy()
    c = h["close"].to_numpy()
    r = np.full(len(c), np.nan)
    ok = np.diff(t) == HOUR_US
    r[1:] = np.where(ok, c[1:] / c[:-1] - 1, np.nan)
    return t, r


def calendar(t_us: np.ndarray) -> dict[str, np.ndarray]:
    hour = (t_us // HOUR_US) % 24
    day = t_us // fc.DAY_US
    dow = (day + 3) % 7  # 1970-01-01 was a Thursday: 0 = Monday
    dts = [datetime.fromtimestamp(int(d) * 86400, tz=timezone.utc) for d in np.unique(day)]
    tom_days = set()
    for d in dts:
        nxt = datetime.fromtimestamp((d.timestamp() + 86400), tz=timezone.utc)
        if d.day <= 3 or nxt.month != d.month:
            tom_days.add(int(d.timestamp() // 86400))
    tom = np.array([int(x) in tom_days for x in day])
    return {"hour": hour, "dow": dow, "weekend": dow >= 5, "tom": tom, "day": day}


def welch(x: np.ndarray, m: np.ndarray) -> tuple[float, float, float]:
    a, b = x[m & np.isfinite(x)], x[~m & np.isfinite(x)]
    if len(a) < 10 or len(b) < 10:
        return 0.0, 0.0, 1.0
    t, p = stats.ttest_ind(a, b, equal_var=False)
    return float(a.mean()), float(t), float(p)


def daily_from_hours(t_us: np.ndarray, r: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    day = t_us // fc.DAY_US
    df = pl.DataFrame({"day": day, "r": np.nan_to_num(r)}).group_by("day").agg(
        r=(pl.col("r") + 1).product() - 1).sort("day")
    return df["day"].to_numpy(), df["r"].to_numpy()


def hypotheses(P: fc.Panel) -> list[dict]:
    if "hyp" in _cache:
        return _cache["hyp"]
    rows = []
    for coin in COINS:
        t, r = hourly_returns(P, coin)
        cal = calendar(t)
        ins = (t >= fc.IS_START) & (t < fc.SPLIT)
        oos = t >= fc.SPLIT
        for h in range(24):
            m = cal["hour"] == h
            mi, ti, pi = welch(r[ins], m[ins])
            mo, to, po = welch(r[oos], m[oos])
            rows.append({"coin": coin, "test": f"hour {h:02d} UTC", "kind": "hour", "key": h,
                         "is_mean_bps": mi * 1e4, "is_t": ti, "is_p": pi, "oos_mean_bps": mo * 1e4, "oos_t": to})
        dday, dr = daily_from_hours(t, r)
        dcal = calendar(dday * fc.DAY_US)
        dins = (dday * fc.DAY_US >= fc.IS_START) & (dday * fc.DAY_US < fc.SPLIT)
        doos = dday * fc.DAY_US >= fc.SPLIT
        tests = [(f"weekday {d}", "dow", d, dcal["dow"] == d) for d in range(7)]
        tests += [("weekend", "weekend", 1, dcal["weekend"]), ("turn of month", "tom", 1, dcal["tom"])]
        for name, kind, key, m in tests:
            mi, ti, pi = welch(dr[dins], m[dins])
            mo, to, po = welch(dr[doos], m[doos])
            rows.append({"coin": coin, "test": name, "kind": kind, "key": key, "is_mean_bps": mi * 1e4,
                         "is_t": ti, "is_p": pi, "oos_mean_bps": mo * 1e4, "oos_t": to})
    # Benjamini-Hochberg and Holm over all hypotheses together
    p = np.array([x["is_p"] for x in rows])
    n = len(p)
    order = np.argsort(p)
    bh = np.zeros(n, dtype=bool)
    passed = [i for k, i in enumerate(order) if p[i] <= 0.05 * (k + 1) / n]
    if passed:
        kmax = max(k for k, i in enumerate(order) if p[i] <= 0.05 * (k + 1) / n)
        bh[order[:kmax + 1]] = True
    holm = np.zeros(n, dtype=bool)
    for k, i in enumerate(order):
        if p[i] <= 0.05 / (n - k):
            holm[i] = True
        else:
            break
    for i, x in enumerate(rows):
        x["bh_5pct"] = bool(bh[i])
        x["holm_5pct"] = bool(holm[i])
    _cache["hyp"] = rows
    return rows


def variants(P: fc.Panel) -> list[fc.Result]:
    hyp = hypotheses(P)
    out = []
    for coin in COINS:
        t, r = hourly_returns(P, coin)
        cal = calendar(t)
        H = [x for x in hyp if x["coin"] == coin]
        hours = [x for x in H if x["kind"] == "hour"]
        dows = [x for x in H if x["kind"] == "dow"]
        rules = {
            "hours BH": np.isin(cal["hour"], [x["key"] for x in hours if x["bh_5pct"] and x["is_t"] > 0]),
            "hours top 3": np.isin(cal["hour"], [x["key"] for x in sorted(hours, key=lambda x: -x["is_t"])[:3]]),
            "weekdays BH": np.isin(cal["dow"], [x["key"] for x in dows if x["bh_5pct"] and x["is_t"] > 0]),
            "weekdays top 2": np.isin(cal["dow"], [x["key"] for x in sorted(dows, key=lambda x: -x["is_t"])[:2]]),
            "weekdays only": ~cal["weekend"],
            "turn of month": cal["tom"],
        }
        for rname, pos in rules.items():
            p = pos.astype(float)
            # The position over hour i earns r[i]; it was set at the open of hour i.
            strat = p * np.nan_to_num(r)
            tv = np.abs(np.diff(np.r_[0.0, p]))
            day = cal["day"]
            df = pl.DataFrame({"day": day, "g": strat, "tv": tv}).group_by("day").agg(
                g=(pl.col("g") + 1).product() - 1, tv=pl.col("tv").sum(), ex=pl.lit(0.0)).sort("day")
            gross, turnover, expo = np.zeros(P.T), np.zeros(P.T), np.zeros(P.T)
            idx = {int(d): i for i, d in enumerate(P.days // fc.DAY_US)}
            hold = pl.DataFrame({"day": day, "p": p}).group_by("day").agg(pl.col("p").mean()).sort("day")
            for d, g, v in zip(df["day"].to_numpy(), df["g"].to_numpy(), df["tv"].to_numpy()):
                i = idx.get(int(d))
                if i is not None:
                    gross[i] = g
                    if i > 0:
                        turnover[i - 1] = v  # the convention: turnover[t] is charged against day t+1
            for d, x in zip(hold["day"].to_numpy(), hold["p"].to_numpy()):
                i = idx.get(int(d))
                if i is not None and i > 0:
                    expo[i - 1] = x
            out.append(fc.Result(FAMILY, coin, f"{rname} · {coin}", gross, turnover, expo, np.zeros(P.T),
                                 benchmark="btc", spot_only=True))
    return out


def extra_markdown(P: fc.Panel) -> str:
    hyp = hypotheses(P)
    n_bh = sum(x["bh_5pct"] for x in hyp)
    n_holm = sum(x["holm_5pct"] for x in hyp)
    keep = [x for x in hyp if x["is_p"] < 0.05 or x["bh_5pct"]]
    return ("\n## The 66 calendar hypotheses\n\n"
            f"{n_bh} survive Benjamini-Hochberg at 5 %, {n_holm} survive Holm at 5 %. "
            f"{sum(x['is_p'] < 0.05 for x in hyp)} have a raw in-sample p below 0.05 (3.3 expected by chance). "
            "Those, with their out-of-sample mean and t:\n\n"
            + fc.table(sorted(keep, key=lambda x: x["is_p"]),
                       ["coin", "test", "is_mean_bps", "is_t", "is_p", "bh_5pct", "holm_5pct", "oos_mean_bps",
                        "oos_t"]))


if __name__ == "__main__":
    from .families import run_one
    run_one(FAMILY)
    print(extra_markdown(fc.load_panel()))
