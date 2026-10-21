"""Buy after a market-wide deleveraging flush (OI collapse, negative funding, BTC down hard)?

    PYTHIA_AGENT_OUT=<fresh panel folder> python -m lab.experiments.flush_long

Pre-registered in results/flush_long_prereg.md (committed before this file ran).
Events from the 20 coins with Binance USD-M metrics (open interest in contracts at
constant prices over 3 days, the day's mean funding, BTC's 3-day perp return); trades
on the sweep's daily panel (cut at 2026-10-19): long the BTC perp or the 5 most liquid
perps for 3 or 7 days from the event close, funding paid, 10 bps a side; against
entries on matched days (same month, same BTC 200-day state). Writes
results/flush_long.md below the marker and <reports>/flush_long/latest.*.
"""

from __future__ import annotations

import itertools
from datetime import datetime, timezone

import numpy as np
import polars as pl

from .. import report
from ..data import ROOT
from . import director_common as dc
from . import fam_common as fc
from . import perps_common as pc
from .trend_shorts import sim

NAME = "flush_long"
LAST_DAY = "2026-10-19"
DAY = fc.DAY_US
XS = (0.03, 0.05)
DROP = 0.05
INSTRUMENTS = ("BTC", "top5")
HOLDS = (3, 7)
REFRACTORY = 7
MIN_COINS = 15
MIN_OOS_EVENTS = 6
IS_FROM, OOS_FROM = "2022-01-04", "2024-01-01"
DRAWS = 4000


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

def event_frame() -> pl.DataFrame:
    """Per day: OI change over 3 days at constant prices, mean funding settled that day,
    BTC's 3-day perp return, the number of coins."""
    um = ROOT / "hist" / "binance_um"
    syms = sorted(p.name.split("=", 1)[1] for p in (um / "metrics").glob("symbol=*"))
    oi, px, fu = [], [], []
    for s in syms:
        m = pl.concat([pl.read_parquet(f, columns=["ts_us", "sum_open_interest"])
                       for f in sorted((um / "metrics" / f"symbol={s}").glob("*.parquet"))])
        oi.append(m.unique("ts_us").sort("ts_us").with_columns(day=(pl.col("ts_us") // DAY) * DAY)
                  .group_by("day").agg(q=pl.col("sum_open_interest").last()).with_columns(sym=pl.lit(s)))
        k = pl.concat([pl.read_parquet(f) for f in sorted((um / "klines_1d" / f"symbol={s}").glob("*.parquet"))])
        px.append(k.unique("open_time_us").select(day=(pl.col("open_time_us") // DAY) * DAY, c=pl.col("close"))
                  .with_columns(sym=pl.lit(s)))
        f = pl.concat([pl.read_parquet(x) for x in sorted((um / "funding" / f"symbol={s}").glob("*.parquet"))])
        fu.append(f.unique("funding_time_us").with_columns(day=((pl.col("funding_time_us") - 1) // DAY) * DAY)
                  .group_by("day").agg(f=pl.col("funding_rate").sum()).with_columns(sym=pl.lit(s)))
    d = (pl.concat(oi).join(pl.concat(px), on=["day", "sym"], how="left")
         .join(pl.concat(fu), on=["day", "sym"], how="left").sort(["sym", "day"])
         .with_columns(q3=pl.col("q").shift(3).over("sym"), c3=pl.col("c").shift(3).over("sym")))
    agg = (d.group_by("day").agg(num=((pl.col("q") - pl.col("q3")) * pl.col("c3")).sum(),
                                 den=(pl.col("q3") * pl.col("c3")).sum(), fund=pl.col("f").mean(), n=pl.len())
           .with_columns(doi=pl.col("num") / pl.col("den")))
    btc = d.filter(pl.col("sym") == "BTCUSDT").select("day", r3=pl.col("c") / pl.col("c3") - 1)
    return agg.join(btc, on="day").filter(pl.col("n") >= MIN_COINS).sort("day")


def events(a: pl.DataFrame, x: float) -> pl.DataFrame:
    m = ((a["doi"] <= -x) & (a["r3"] <= -DROP) & (a["fund"] < 0)).to_numpy()
    keep, last = [], -10 ** 9
    for i in np.flatnonzero(m):
        if i - last >= REFRACTORY:
            keep.append(i)
            last = i
    return a[keep]


# ---------------------------------------------------------------------------
# Trades
# ---------------------------------------------------------------------------

def basket(P: fc.Panel, t: int, inst: str, top5: np.ndarray) -> np.ndarray:
    return np.array([P.btc]) if inst == "BTC" else np.flatnonzero(top5[t])


def trade_ret(P: fc.Panel, t: int, H: int, cols: np.ndarray, cost: float, funding: bool = True) -> float:
    """Equal weight in cols at the close of t, held to the close of t+H, unrebalanced:
    the price return minus the funding a long pays minus a round trip."""
    if len(cols) == 0 or t + H >= P.T:
        return float("nan")
    r = np.nan_to_num(P.ret[t + 1:t + H + 1][:, cols])
    gross = np.prod(1 + r, 0) - 1
    f = P.funding[t + 1:t + H + 1][:, cols].sum(0) if funding else 0.0
    return float(np.mean(gross - f) - 2 * cost)


def matched_days(P: fc.Panel, t: int, H: int, blocked: np.ndarray, ym: np.ndarray) -> np.ndarray:
    ok = (ym == ym[t]) & (P.btc_on == P.btc_on[t]) & ~blocked
    ok[P.T - H:] = False
    return np.flatnonzero(ok)


def run_variant(P: fc.Panel, ev: pl.DataFrame, inst: str, H: int, top5: np.ndarray, ym: np.ndarray,
                cost: float, funding: bool = True, lag: int = 0) -> list[dict]:
    di = {int(d): i for i, d in enumerate(P.days)}
    idx = [di[int(d)] for d in ev["day"].to_numpy() if int(d) in di]
    blocked = np.zeros(P.T, dtype=bool)
    for t in idx:
        blocked[t:t + REFRACTORY + 1] = True
    out = []
    for t, row in zip(idx, ev.iter_rows(named=True)):
        te = t + lag
        if te + H >= P.T:
            continue
        r = trade_ret(P, te, H, basket(P, te, inst, top5), cost, funding)
        md = matched_days(P, te, H, blocked, ym)
        rr = np.array([trade_ret(P, s, H, basket(P, s, inst, top5), cost, funding) for s in md])
        rr = rr[np.isfinite(rr)]
        out.append({"day": dc.day_str(P.days[t]), "t": t, "doi": row["doi"], "fund": row["fund"], "r3": row["r3"],
                    "ret": r, "matched": float(rr.mean()) if len(rr) else float("nan"), "n_matched": len(rr),
                    "excess": r - float(rr.mean()) if len(rr) else float("nan"), "_rr": rr})
    return out


def daily_book(P: fc.Panel, evs: list[dict], inst: str, H: int, top5: np.ndarray, cost: float) -> np.ndarray:
    W = np.full((P.T, P.N), np.nan)
    W[0] = 0.0
    for e in evs:
        t = e["t"]
        cols = basket(P, t, inst, top5)
        W[t] = np.where(np.isin(np.arange(P.N), cols), 1.0 / len(cols), 0.0)
        if t + H < P.T:
            W[t + H] = 0.0
    o = sim(P, W, start=1)
    return o["gross"] - cost * np.r_[0.0, o["turnover"][:-1]]


def summary(evs: list[dict]) -> dict:
    ex = np.array([e["excess"] for e in evs], dtype=float)
    ex = ex[np.isfinite(ex)]
    if len(ex) == 0:
        return {"events": 0, "mean_ret": float("nan"), "mean_matched": float("nan"), "mean_excess": float("nan"),
                "hit": float("nan")}
    return {"events": len(ex), "mean_ret": float(np.mean([e["ret"] for e in evs])),
            "mean_matched": float(np.mean([e["matched"] for e in evs])), "mean_excess": float(ex.mean()),
            "hit": float((ex > 0).mean())}


def boot_mean(x: np.ndarray, seed: int = pc.SEED) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    if len(x) == 0:
        return float("nan"), float("nan")
    m = x[rng.integers(0, len(x), (DRAWS, len(x)))].mean(1)
    return float(np.percentile(m, 5)), float(np.percentile(m, 95))


def random_sets_p(evs: list[dict], seed: int = pc.SEED) -> float:
    """Share of random entry sets (one matched day per event) whose mean return reaches
    the events' mean."""
    rng = np.random.default_rng(seed)
    pools = [e["_rr"] for e in evs if len(e["_rr"])]
    if not pools:
        return float("nan")
    target = np.mean([e["ret"] for e in evs if len(e["_rr"])])
    draws = np.array([[p[rng.integers(0, len(p))] for p in pools] for _ in range(DRAWS)]).mean(1)
    return float((draws >= target).mean())


def main() -> None:
    P = dc.cut_panel(fc.load_panel(), LAST_DAY)
    a = event_frame()
    top5 = P.top_liquid(5, need_perp=True)
    ym = np.array([datetime.fromtimestamp(int(d) / 1e6, timezone.utc).strftime("%Y-%m") for d in P.days])
    years = dc.years_of(P.days)
    ins_m = (P.days >= dc.us(IS_FROM)) & (P.days < dc.us(OOS_FROM))
    oos_m = P.days >= dc.us(OOS_FROM)
    rows, detail, books = [], {}, {}
    for x, inst, H in itertools.product(XS, INSTRUMENTS, HOLDS):
        ev = events(a, x)
        name = f"OI -{x * 100:.0f} % · {inst} · {H} d"
        evs = run_variant(P, ev, inst, H, top5, ym, pc.JUDGED)
        ins = [e for e in evs if e["day"] < OOS_FROM]
        oos = [e for e in evs if e["day"] >= OOS_FROM]
        row = {"variant": name, "x": x, "inst": inst, "H": H,
               **{f"is_{k}": v for k, v in summary(ins).items()}, **{f"oos_{k}": v for k, v in summary(oos).items()}}
        book = daily_book(P, evs, inst, H, top5, pc.JUDGED)
        row["book_is"], row["book_oos"] = dc.sharpe(book[ins_m]), dc.sharpe(book[oos_m])
        books[name] = book
        detail[name] = {"ev": ev, "evs": evs}
        rows.append(row)
        print(name, row["is_events"], round(row["is_mean_excess"], 4), row["oos_events"],
              round(row["oos_mean_excess"], 4), flush=True)

    pick = max(rows, key=lambda r: r["is_mean_excess"])
    pname = pick["variant"]
    ev = detail[pname]["ev"]
    oos = [e for e in detail[pname]["evs"] if e["day"] >= OOS_FROM]
    ex = np.array([e["excess"] for e in oos], dtype=float)
    ex = ex[np.isfinite(ex)]
    lo, hi = boot_mean(ex)
    p_rand = random_sets_p(oos)
    late = [e for e in run_variant(P, ev, pick["inst"], pick["H"], top5, ym, pc.JUDGED, lag=1)
            if e["day"] >= OOS_FROM]
    alp = [e for e in run_variant(P, ev, pick["inst"], pick["H"], top5, ym, pc.ALPACA_TAKER, funding=False)
           if e["day"] >= OOS_FROM]
    stress = [e for e in run_variant(P, ev, pick["inst"], pick["H"], top5, ym, pc.STRESS) if e["day"] >= OOS_FROM]
    zero = [e for e in run_variant(P, ev, pick["inst"], pick["H"], top5, ym, 0.0) if e["day"] >= OOS_FROM]
    pl_ = pc.pool([r["book_oos"] for r in rows])
    book = books[pname]
    pk = {"variant": pname, "oos_events": len(ex), "mean_excess": float(ex.mean()) if len(ex) else float("nan"),
          "boot_p05": lo, "boot_p95": hi, "p_random": p_rand,
          "late_excess": summary(late)["mean_excess"], "alpaca_excess": summary(alp)["mean_excess"],
          "stress_excess": summary(stress)["mean_excess"], "zero_excess": summary(zero)["mean_excess"],
          "book_oos": dc.sharpe(book[oos_m]), "book_deflated_p": dc.deflated(book[oos_m], pl_),
          "funding_received_mean": float(np.mean([-P.funding[e["t"] + 1:e["t"] + pick["H"] + 1, P.btc].sum()
                                              for e in oos])) if pick["inst"] == "BTC" and oos else None}
    gates = {"1 at least 6 out-of-sample events": pk["oos_events"] >= MIN_OOS_EVENTS,
             "2 mean excess above 0 at 10 bps": pk["mean_excess"] > 0,
             "3 event bootstrap 5 % above 0": lo > 0,
             "4 a close late still above 0": pk["late_excess"] > 0,
             "5 above 0 at Alpaca spot costs": pk["alpaca_excess"] > 0}
    pk["gates"] = gates
    passed = all(gates.values())
    pk["verdict"] = ("too few events" if not gates["1 at least 6 out-of-sample events"] else
                     "kill" if not pk["mean_excess"] > 0 else
                     ("pass (confirmed)" if pk["book_deflated_p"] > 0.95 else "pass, fails deflation: experimental")
                     if passed else "fails")
    listed = []
    for name, d in detail.items():
        if name != pname:
            continue
        for e in d["evs"]:
            listed.append({k: v for k, v in e.items() if not k.startswith("_") and k != "t"})
    res = {"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "rows": rows, "pick": pk,
           "events": listed, "pool": pl_, "last_day": LAST_DAY,
           "events_per_year": {f"OI -{x * 100:.0f} %": {int(y): int(c) for y, c in zip(*np.unique(
               dc.years_of(events(a, x)["day"].to_numpy()), return_counts=True))} for x in XS}}
    write(res)


def write(res: dict) -> None:
    pk, pl_ = res["pick"], res["pool"]
    bp = lambda v: "n/a" if v is None or not np.isfinite(v) else f"{v * 1e4:+.0f} bps"  # noqa: E731
    md = ["# Buying after a deleveraging flush: results\n",
          f"Generated {res['generated']}. Registered in `results/flush_long_prereg.md` before the run.\n",
          f"Events from 2022-01-04; out of sample from 2024-01-01 with exits by {res['last_day']}. Returns net of 10 bps "
          "a side and the funding a long pays; excess over entries on matched days (same month, same BTC 200-day "
          "state, outside event windows).\n",
          f"## Verdict\n\nPick **{pk['variant']}**: **{pk['verdict']}**. {pk['oos_events']} events out of sample, mean "
          f"excess {bp(pk['mean_excess'])} per trade (event bootstrap 90 % band {bp(pk['boot_p05'])} to "
          f"{bp(pk['boot_p95'])}); a close late {bp(pk['late_excess'])}; at Alpaca spot costs "
          f"{bp(pk['alpaca_excess'])}; at 20 bps {bp(pk['stress_excess'])}, at 0 bps {bp(pk['zero_excess'])}. "
          f"Share of random matched entry sets with a mean as high: {pk['p_random']:.2f}. As a daily book: Sharpe "
          f"{pk['book_oos']:.2f}, deflated p {pk['book_deflated_p']:.4f}.\n"]
    for k, v in pk["gates"].items():
        md.append(f"- {k}: {'yes' if v else 'no'}")
    md.append("\n## Events per year\n")
    for k, v in res["events_per_year"].items():
        md.append(f"- {k}: " + ", ".join(f"{y} {c}" for y, c in v.items()))
    md.append("\n## Every variant\n")
    tab = [{**r, **{f"{w}_{m}_bps": r[f"{w}_{m}"] * 1e4 for w in ("is", "oos") for m in
                    ("mean_ret", "mean_matched", "mean_excess")}} for r in res["rows"]]
    md.append(dc.table(tab, ["variant", "is_events", "is_mean_ret_bps", "is_mean_excess_bps", "is_hit", "oos_events",
                             "oos_mean_ret_bps", "oos_mean_matched_bps", "oos_mean_excess_bps", "oos_hit", "book_is",
                             "book_oos"], ".2f"))
    md.append("\nReturns per trade in bps at 10 bps a side with funding; `hit` is the share of events above their "
              "matched mean; `book_*` the Sharpe of the daily book (in the trade after each event, cash otherwise).\n")
    md.append(f"\n## The pick's events\n")
    ev = [{**e, "doi_pct": e["doi"] * 100, "fund_bps": e["fund"] * 1e4, "btc_r3_pct": e["r3"] * 100,
           "ret_pct": e["ret"] * 100, "matched_pct": e["matched"] * 100, "excess_pct": e["excess"] * 100}
          for e in res["events"]]
    md.append(dc.table(ev, ["day", "doi_pct", "fund_bps", "btc_r3_pct", "ret_pct", "matched_pct", "excess_pct",
                            "n_matched"]))
    md.append(f"\n## Pool\n\n{pl_['n_total']:,} trials ({pl_['hand_trials']:,} hand, {pl_['factory_trials']} factory, "
              f"{pl_['today_trials']} registered today); the best noise trial sits at an annual Sharpe of about "
              f"{pl_['sr0_annual']:.2f}.\n")
    text = "\n".join(md)
    dc.write_results(NAME, text)
    res = {**res, "events": res["events"]}
    report.write(NAME, text, res)


if __name__ == "__main__":
    main()
