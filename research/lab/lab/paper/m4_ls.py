"""Shadow paper book of M4, the daily cross-sectional model, market-neutral on perps. No real money.

M4 fails the deflation gate (results/xs_daily.md, results/m4_funding.md). This
book runs so that forward evidence accumulates, labelled as such in its
variant string. Lab-only: no signal file, nothing reaches the engine.

Configuration: the selection window's (2022-2023) pick among the slower
long/short books of xs_daily, i.e. every model book held longer than one day,
round three's funding-aware labels included. See CONFIG below for which one
and results/m4_funding.md for why.

Every run (daily, after the nightly backfill):
  1. rebuild the xs_daily panel from the history files (same code as the
     backtest) into the lab cache, with yesterday as the decision day;
  2. retrain the model on all labelled history if the cached one is older
     than RETRAIN_DAYS (same features and parameters as the walk-forward);
  3. mark the book to the live Binance USD-M mid (bookTicker), book the
     funding that settled since the last run (fundingRate; longs pay positive
     rates, shorts receive them), with the live premiumIndex rate as fallback;
  4. score yesterday's coins, keep the 100 most liquid perps that trade now,
     pick the book exactly like xs_daily.book / book_buffer and trade into it
     at the touch (buys at the ask, sells at the bid) plus the futures taker
     fee. The backtest's 15 bps per unit of turnover is journaled next to it.

Timing differs from the backtest: it enters at the first hourly close after
the decision day (01:00 UTC), this book enters when it runs. The journal's
entry_hour_utc keeps that visible.

  python -m lab.paper.m4_ls             one step, writes state and journal
  python -m lab.paper.m4_ls --dry-run   everything except writing state and journal

Cache (panel and model): $PYTHIA_CACHE, default <data>/lab-cache.
State: <data>/paper/m4_ls/state.json   Journal: <data>/paper/m4_ls/journal.csv
"""

from __future__ import annotations

import csv
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import lightgbm as lgb
import numpy as np
import polars as pl

from ..data import ROOT
from ..experiments import xs_daily as xs

CONFIG = {
    "model": "rank3",       # rank3: LambdaRank on fwd3 quintiles; regHn: regression on the funding-net H-day rank
    "k": 10,                # longs and shorts each
    "n_liquid": 100,        # the most liquid USDT perps of the day
    "mode": "hold",         # "hold": overlapping tranches; "buffer": rank buffer (xs_daily.book_buffer)
    "hold": 3,              # days per tranche (mode hold)
    "exit_frac": None,      # rank buffer (mode buffer)
}
VARIANT = ("M4 rank3 · 10/10 of the 100 most liquid perps · hold 3d · "
           "fails deflation, forward evidence only")
NAME = "m4_ls"
START_EQUITY = 10_000.0
TAKER_UM = 0.0005           # Binance USD-M taker, regular tier
MODEL_COST = xs.COSTS["15bps"]
RETRAIN_DAYS = 7
FAPI = "https://fapi.binance.com/fapi/v1"
DAY_US = xs.DAY_US
CACHE = Path(os.environ.get("PYTHIA_CACHE", str(ROOT / "lab-cache")))
DIR = ROOT / "paper" / NAME


def get(url: str):
    with urllib.request.urlopen(url, timeout=20) as r:
        return json.load(r)


def peak_mb() -> float:
    try:
        import resource
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    except ImportError:  # Windows
        import ctypes
        from ctypes import wintypes

        class PMC(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                        ("a", ctypes.c_size_t), ("b", ctypes.c_size_t), ("c", ctypes.c_size_t),
                        ("d", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t),
                        ("PeakPagefileUsage", ctypes.c_size_t)]
        pmc = PMC()
        pmc.cb = ctypes.sizeof(PMC)
        k32 = ctypes.windll.kernel32
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        fn = ctypes.windll.psapi.GetProcessMemoryInfo
        fn.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
        fn(k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb)
        return pmc.PeakWorkingSetSize / 2 ** 20


# ---------------------------------------------------------------- model

def live_panel(decision_day: int) -> tuple[pl.DataFrame, dict]:
    """The xs_daily panel with the decision day made scoreable. The backtest needs an
    entry price to call a coin eligible; the live decision day has none yet, so there
    eligibility is the same rule without it, and the market dispersion is recomputed."""
    xs.CACHE = CACHE
    P = xs.build_panel(refresh=True)
    P, fund_end = xs.add_net_labels(P)
    last = P["day"] == decision_day
    base = ((pl.col("age") >= xs.MIN_HISTORY_D) & (pl.col("adv28") >= np.log(xs.MIN_ADV_USD + 1))
            & pl.col("r112").is_not_null()).fill_null(False)
    P = P.with_columns(eligible=pl.when(last).then(base).otherwise(pl.col("eligible")))
    disp = P.filter(last & pl.col("eligible"))["r1"].std()
    P = P.with_columns(disp1=pl.when(last).then(pl.lit(disp)).otherwise(pl.col("disp1")))
    # Funding features are only as fresh as the funding backfill: report it, the model
    # sees zeros where the files stop.
    perps = P.filter(last & pl.col("perp").is_not_null())
    info = {"fund_end": datetime.fromtimestamp(fund_end / 1e6, timezone.utc).strftime("%Y-%m-%d"),
            "funding_fresh": bool(perps.height and (perps["fund1"].fill_null(0) != 0).mean() >= 0.5)}
    E = xs.ranked(P.with_columns(adv28_raw=pl.col("adv28"), fund7_raw=pl.col("fund7")))
    return E, info


def model_for(E: pl.DataFrame, decision_day: int):
    """The cached model if it is younger than RETRAIN_DAYS, else one trained on every
    labelled row (labels known by the decision day), with the walk-forward's parameters."""
    m = CONFIG["model"]
    path, meta_path = CACHE / f"m4_ls_{m}.txt", CACHE / f"m4_ls_{m}.json"
    if path.exists() and meta_path.exists():
        meta = json.loads(meta_path.read_text())
        if meta.get("features") == xs.FEATURES and decision_day - meta["decision_day"] < RETRAIN_DAYS * DAY_US:
            return lgb.Booster(model_file=str(path)), meta
    t0 = time.time()
    days = E["day"].to_numpy()
    X = E.select(xs.FEATURES).to_numpy().astype(np.float32)
    if m == "rank3":
        y = np.asarray(E["q3"].to_numpy(), dtype=float)
        tr = np.isfinite(y) & np.isfinite(np.asarray(E["fwd3"].to_numpy(), dtype=float))
        order = np.argsort(days[tr], kind="stable")
        _, group = np.unique(days[tr][order], return_counts=True)
        est = lgb.LGBMRanker(**xs.RANK_PARAMS).fit(X[tr][order], y[tr][order].astype(np.int32), group=group)
    else:
        y = np.asarray(E[f"y{m[3:-1]}n" if m.endswith("n") else f"y{m[3:]}"].to_numpy(), dtype=float)
        tr = np.isfinite(y)
        est = lgb.LGBMRegressor(**xs.REG_PARAMS).fit(X[tr], y[tr])
    CACHE.mkdir(parents=True, exist_ok=True)
    est.booster_.save_model(str(path))
    meta = {"model": m, "decision_day": decision_day, "rows": int(tr.sum()),
            "last_label_day": datetime.fromtimestamp(int(days[tr].max()) / 1e6, timezone.utc).strftime("%Y-%m-%d"),
            "trained": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "secs": round(time.time() - t0), "features": xs.FEATURES}
    meta_path.write_text(json.dumps(meta, indent=2))
    return est.booster_, meta


# ---------------------------------------------------------------- book

def candidates(E: pl.DataFrame, booster, decision_day: int, live: set[str]) -> pl.DataFrame:
    """Yesterday's scores on the n_liquid most liquid perps that trade right now, best first."""
    today = E.filter(pl.col("day") == decision_day)
    score = booster.predict(today.select(xs.FEATURES).to_numpy().astype(np.float32))
    return (today.with_columns(score=pl.Series(score))
            .filter(pl.col("perp").is_in(sorted(live)) & pl.col("perp_adv28").is_not_null())
            .sort("perp_adv28", descending=True).head(CONFIG["n_liquid"])
            .sort("score", descending=True)
            .select("symbol", "perp", "score", "perp_adv28", "fund7_raw"))


def new_tranche(c: pl.DataFrame) -> dict[str, float]:
    """xs_daily.book for one day: the best k long, the worst k short, half the capital
    per side, scaled by 1 / hold because hold tranches make up the book."""
    k, hold = CONFIG["k"], CONFIG["hold"]
    if c.height < 2 * k:
        return {}
    perps = c["perp"].to_list()
    out = {s: 0.5 / k / hold for s in perps[:k]}
    out |= {s: -0.5 / k / hold for s in perps[::-1][:k]}
    return out


def buffer_target(c: pl.DataFrame, w: dict[str, float]) -> dict[str, float]:
    """xs_daily.book_buffer for one day, on the drifted weights w."""
    k, frac = CONFIG["k"], CONFIG["exit_frac"]
    order = c["perp"].to_list()
    if len(order) < 2 * k:
        return {}
    exit_k = max(k, int(frac * len(order)))
    top, bot = set(order[:exit_k]), set(order[-exit_k:])
    longs = [s for s, x in w.items() if x > 0 and s in top]
    shorts = [s for s, x in w.items() if x < 0 and s in bot]
    tgt = {s: min(w[s], 1.0 / k) for s in longs} | {s: max(w[s], -1.0 / k) for s in shorts}
    for s in order:
        if len(longs) >= k:
            break
        if s not in tgt:
            longs.append(s)
            tgt[s] = 0.5 / k
    for s in order[::-1]:
        if len(shorts) >= k:
            break
        if s not in tgt:
            shorts.append(s)
            tgt[s] = -0.5 / k
    return tgt


def settled_funding(sym: str, since_ms: int, now_ms: int) -> float | None:
    try:
        rows = get(f"{FAPI}/fundingRate?symbol={sym}&startTime={since_ms + 1}&endTime={now_ms}&limit=1000")
        return float(sum(float(r["fundingRate"]) for r in rows if since_ms < int(r["fundingTime"]) <= now_ms))
    except Exception:  # noqa: BLE001 - fall back to the live rate
        return None


def main() -> int:
    t_start = time.time()
    dry = "--dry-run" in sys.argv
    now_us = time.time_ns() // 1000
    now_ms = now_us // 1000
    decision_day = (now_us // DAY_US - 1) * DAY_US
    E, info = live_panel(decision_day)
    if E["day"].max() < decision_day:
        print(f"history ends {datetime.fromtimestamp(E['day'].max() / 1e6, timezone.utc):%Y-%m-%d}, "
              "yesterday is missing; not rebalancing on stale data", file=sys.stderr)
        return 1
    booster, meta = model_for(E, decision_day)

    exch = get(f"{FAPI}/exchangeInfo")["symbols"]
    live = {s["symbol"] for s in exch if s.get("contractType") == "PERPETUAL" and s["status"] == "TRADING"
            and s.get("quoteAsset") == "USDT"}
    quotes = {q["symbol"]: (float(q["bidPrice"]), float(q["askPrice"])) for q in get(f"{FAPI}/ticker/bookTicker")
              if float(q["bidPrice"]) > 0 and float(q["askPrice"]) > 0}
    prem = {p["symbol"]: p for p in get(f"{FAPI}/premiumIndex")}
    intervals = {f["symbol"]: int(f["fundingIntervalHours"]) for f in get(f"{FAPI}/fundingInfo")}
    mid = {s: (b + a) / 2 for s, (b, a) in quotes.items()}
    c = candidates(E, booster, decision_day, live & set(quotes))

    state_file = DIR / "state.json"
    if state_file.exists():
        st = json.loads(state_file.read_text())
    else:
        st = {"variant": VARIANT, "config": CONFIG, "started": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "equity": START_EQUITY, "tranches": [{} for _ in range(CONFIG["hold"] or 1)], "weights": {}, "mid": {},
              "last_run_ms": None}
        if CONFIG["mode"] == "hold":
            # A new book starts where the backtest stands: the older tranches come from
            # the previous days' scores, so day one is fully invested, not a third.
            for j in range(1, CONFIG["hold"]):
                d = decision_day - j * DAY_US
                st["tranches"][int(d // DAY_US) % CONFIG["hold"]] = new_tranche(candidates(E, booster, d, live & set(quotes)))
    equity = st["equity"]
    tranches = [{s: float(x) for s, x in tr.items()} for tr in st["tranches"]]
    w = {s: float(x) for s, x in st["weights"].items()}

    # 1 · mark to market and book funding since the last run. A held perp without a
    # live quote (delisted) is closed at its last mark.
    rets = {s: mid[s] / st["mid"][s] - 1 for s in w if s in mid and st["mid"].get(s)}
    gross = sum(w[s] * r for s, r in rets.items())
    funding, fallback = 0.0, []
    if st["last_run_ms"]:
        for s, x in w.items():
            rate = settled_funding(s, st["last_run_ms"], now_ms)
            if rate is None and s in prem:
                # Live rate times the settlements that fell in the interval.
                n = (now_ms - st["last_run_ms"]) / 3_600_000 / intervals.get(s, 8)
                rate = float(prem[s]["lastFundingRate"]) * round(n)
                fallback.append(s)
            funding += -x * (rate or 0.0)
    equity *= 1 + gross + funding
    denom = 1 + gross
    if denom > 0:
        w = {s: x * (1 + rets.get(s, 0.0)) / denom for s, x in w.items()}
        tranches = [{s: x * (1 + rets.get(s, 0.0)) / denom for s, x in tr.items()} for tr in tranches]
    gone = {s for s in w if s not in mid}
    w = {s: x for s, x in w.items() if s not in gone}
    tranches = [{s: x for s, x in tr.items() if s not in gone} for tr in tranches]

    # 2 · today's target
    if CONFIG["mode"] == "hold":
        slot = int(decision_day // DAY_US) % CONFIG["hold"]
        tranches[slot] = new_tranche(c)
        tgt: dict[str, float] = {}
        for tr in tranches:
            for s, x in tr.items():
                tgt[s] = tgt.get(s, 0.0) + x
        picked = tranches[slot]
    else:
        tgt = buffer_target(c, w)
        picked = {s: x for s, x in tgt.items() if s not in w}
    tgt = {s: x for s, x in tgt.items() if abs(x) > 1e-12}
    syms = set(w) | set(tgt)
    delta = {s: tgt.get(s, 0.0) - w.get(s, 0.0) for s in syms}
    half = {s: (quotes[s][1] - quotes[s][0]) / mid[s] / 2 for s in syms if s in quotes}
    paper_cost = sum(abs(x) * (TAKER_UM + half.get(s, 0.0)) for s, x in delta.items())
    model_cost = sum(abs(x) for x in delta.values()) * MODEL_COST
    equity *= 1 - paper_cost
    # What the new book earns or pays in funding per day at today's live rates.
    carry = sum(-x * float(prem[s]["lastFundingRate"]) * 24 / intervals.get(s, 8) for s, x in tgt.items() if s in prem)

    row = {
        "date": datetime.fromtimestamp(now_us / 1e6, timezone.utc).strftime("%Y-%m-%d"),
        "equity": round(equity, 2),
        "gross_ret_pct": round(gross * 100, 4),
        "funding_pct": round(funding * 100, 4),
        "paper_cost_bps": round(paper_cost * 1e4, 2),
        "model_cost_bps": round(model_cost * 1e4, 2),
        "turnover": round(sum(abs(x) for x in delta.values()), 4),
        "long_exposure": round(sum(x for x in tgt.values() if x > 0), 4),
        "short_exposure": round(-sum(x for x in tgt.values() if x < 0), 4),
        "held": len(tgt),
        "funding_carry_bps_day": round(carry * 1e4, 2),
        "entry_hour_utc": datetime.fromtimestamp(now_us / 1e6, timezone.utc).hour,
        "model_trained": datetime.fromtimestamp(meta["decision_day"] / 1e6, timezone.utc).strftime("%Y-%m-%d"),
        "funding_fresh": info["funding_fresh"],
        "longs": " ".join(sorted(s for s, x in picked.items() if x > 0)),
        "shorts": " ".join(sorted(s for s, x in picked.items() if x < 0)),
        "weights": json.dumps({s: round(x, 4) for s, x in sorted(tgt.items())}),
    }
    took = {"secs": round(time.time() - t_start), "peak_mb": round(peak_mb())}
    if dry:
        print(json.dumps({"dry_run": True, "decision_day": datetime.fromtimestamp(decision_day / 1e6, timezone.utc)
                          .strftime("%Y-%m-%d"), "variant": VARIANT, "model": {k: v for k, v in meta.items()
                                                                                if k != "features"},
                          "panel": info, "universe": c.height, "funding_fallback": fallback, "row": row,
                          "top": c.head(5).select("perp", "score").to_dicts(),
                          "bottom": c.tail(5).select("perp", "score").to_dicts(), "took": took}, indent=2))
        return 0

    DIR.mkdir(parents=True, exist_ok=True)
    journal = DIR / "journal.csv"
    new = not journal.exists()
    with journal.open("a", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=list(row))
        if new:
            wr.writeheader()
        wr.writerow(row)
    st.update(equity=equity, tranches=tranches, weights=tgt, mid={s: mid[s] for s in tgt}, last_run_ms=now_ms)
    state_file.write_text(json.dumps(st, indent=2))
    print(json.dumps(row))
    print(json.dumps(took), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
