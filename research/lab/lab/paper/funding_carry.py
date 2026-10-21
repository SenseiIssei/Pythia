"""EXPERIMENTAL paper book: cross-sectional funding carry on perps, and its engine signal. No real money.

The funding_carry study's pick (results/funding_carry.md: long the 10 perps with the
lowest funding settled over the last 7 days, short the 10 with the highest, half the
capital per side, three overlapping 3-day tranches) passes its registered gates,
including the residual after the low-vol book and BTC, but FAILS deflation (residual
deflated p 0.0026 over 1,777 trials). It therefore runs as an EXPERIMENT: its signal is
marked experimental and autopilot_only, so the engine never runs it on its own, the
auto pick never picks it, a live autopilot refuses it, and only an autopilot that
names it trades it, on a perps DEMO route.

Every run (daily, after the nightly backfill):
  1. the Kraken Futures listing (public instruments endpoint, no key); the last good
     one is kept in the state and used when the fetch fails; with neither the run
     stops (exit 1, no signal);
  2. the xs_daily panel rebuilt like m4_ls (`m4_ls.live_panel`): F7 = funding settled
     over the 7 days to the decision day, per USDT perp;
  3. mark the book to the live Binance USD-M mid and book the settled Binance funding,
     exactly like m4_ls;
  4. among the coins Kraken lists, the 100 most liquid perps with a live quote (the
     study's Kraken-listed line, holdout Sharpe 0.77 at 10 bps against 0.74 for the
     judged survivorship-free book), the 10 lowest F7 long and the 10 highest short
     form today's tranche; the book is the sum of the last three tranches;
  5. the engine signal <data>/signals/funding_carry/latest.json: signed weights per coin
     (about +0.5 and -0.5 of capital) with each coin's Kraken symbol.

The funding the backtest earned is Binance's; Kraken sets its own (results/
kraken_funding_gap.md: lower than Binance's on most coins), so the demo route's
funding will differ from this book's.

  python -m lab.paper.funding_carry             one step, writes state, journal and signal
  python -m lab.paper.funding_carry --dry-run   prints the decision and the signal; writes
                                                nothing but the panel cache

Cache: $PYTHIA_CACHE (default <data>/lab-cache). State and journal: <data>/paper/funding_carry/.
"""

from __future__ import annotations

import csv
import json
import sys
import time
from datetime import datetime, timezone

import polars as pl

from ..data import ROOT
from ..experiments import perps_common as pc
from ..experiments import xs_daily as xs
from . import m4_ls as m4
from .experimental import LABEL
from .tsmom import save_signal

NAME = "funding_carry"
K, HOLD, N_LIQUID = 10, 3, 100
VARIANT = (f"{LABEL} · funding carry · long the 10 lowest, short the 10 highest 7-day funding of the 100 most "
           "liquid perps Kraken Futures lists · three 3-day tranches")
START_EQUITY = 10_000.0
MODEL_COST = pc.JUDGED
SIGNAL_VALID_MS = 36 * 3600 * 1000
DAY_US = xs.DAY_US
DIR = ROOT / "paper" / NAME
LISTED_ON = "kraken_futures"

# Source: results/funding_carry.md (pick F7 · 10/10 · 3-day tranches, 10 bps per unit of
# one-way turnover, selection 2020-08-01 to 2023-12-31, holdout 2024-01-01 to 2026-10-18).
EVIDENCE = {
    "report": "funding_carry",
    "experimental": True,
    "is_sharpe": 2.17,
    "oos_sharpe": 0.74,
    "oos_sharpe_20bps": 0.46,
    "oos_sharpe_41bps": -0.11,
    "residual_oos_sharpe": 1.08,
    "bootstrap_90": [0.15, 2.03],
    "b_lowvol": -0.173,
    "b_btc": -0.051,
    "regime_sharpes": {"2024": 0.75, "2025": 1.46, "2026 to 2026-10-18": -0.06},
    "regime_filter": False,
    "deflated_p": 0.0026,
    "variants_tried": 1777,
    "kraken_listed_oos_sharpe": 0.77,
    "cost_note": "Sharpe at 10 bps per unit of one-way turnover (Kraken taker plus half-spread), Binance funding "
                 "charged and received; residual_oos_sharpe is what is left after the frozen low-vol and BTC betas",
    "why_failed": "deflated p 0.0026 over 1,777 trials; flat in 2026; negative at 41 bps",
    "caveat": "The long leg earns large negative funding on coins whose prices fall about as fast; Kraken's own "
              "funding differs from Binance's",
    "verdict": "experiment, passes the registered gates and the residual test, fails deflation",
}
WOULD_CHANGE = "90 forward days above the backtest's 5 % band net of Kraken fees and Kraken's own funding"


def listing_for(cached: dict | None, now_ms: int) -> tuple[dict[str, str], dict, str]:
    live = pc.kraken_listing()
    if live:
        return live, {"fetched_ms": now_ms, "symbols": live}, "live"
    if cached and cached.get("symbols"):
        day = datetime.fromtimestamp(cached["fetched_ms"] / 1000, timezone.utc).strftime("%Y-%m-%d")
        return dict(cached["symbols"]), cached, f"cached {day}"
    raise RuntimeError("Kraken Futures listing unavailable and no cached one")


# How many days the decision may step back when the newest day is incomplete.
MAX_LAG_DAYS = 2


def candidates(E: pl.DataFrame, decision_day: int, live: set[str], listing: dict[str, str]) -> pl.DataFrame:
    """The decision day's perps that Kraken lists and that trade now, the N_LIQUID most
    liquid, sorted by score = minus F7 (best long first)."""
    today = E.filter((pl.col("day") == decision_day) & pl.col("perp").is_not_null()
                     & pl.col("perp_adv28").is_not_null() & pl.col("fund7_raw").is_not_null())
    today = today.with_columns(coin=pl.Series([pc.coin_of(p) for p in today["perp"].to_list()], dtype=pl.Utf8))
    return (today.filter(pl.col("perp").is_in(sorted(live)) & pl.col("coin").is_in(sorted(listing)))
            .sort("perp_adv28", descending=True).unique("coin", keep="first", maintain_order=True)
            .head(N_LIQUID).with_columns(score=-pl.col("fund7_raw")).sort("score", descending=True)
            .select("symbol", "perp", "coin", "score", "fund7_raw", "perp_adv28"))


def new_tranche(c: pl.DataFrame) -> dict[str, float]:
    if c.height < 2 * K:
        return {}
    perps = c["perp"].to_list()
    return {s: 0.5 / K / HOLD for s in perps[:K]} | {s: -0.5 / K / HOLD for s in perps[::-1][:K]}


def book_of(tranches: list[dict[str, float]]) -> dict[str, float]:
    out: dict[str, float] = {}
    for tr in tranches:
        for s, x in tr.items():
            out[s] = out.get(s, 0.0) + x
    return {s: x for s, x in out.items() if abs(x) > 1e-12}


def signal(tgt: dict[str, float], listing: dict[str, str], as_of_us: int, now_us: int) -> dict:
    weights: dict[str, float] = {}
    for perp, x in sorted(tgt.items()):
        c = pc.coin_of(perp)
        weights[c] = weights.get(c, 0.0) + x
    weights = {k: round(x, 6) for k, x in sorted(weights.items()) if round(x, 6) != 0 and k in listing}
    long = round(sum(x for x in weights.values() if x > 0), 6)
    short = round(sum(x for x in weights.values() if x < 0), 6)
    return {
        "strategy": NAME, "variant": VARIANT, "as_of_ms": as_of_us // 1000, "generated_ms": now_us // 1000,
        "valid_until_ms": now_us // 1000 + SIGNAL_VALID_MS, "quote": "USD", "asset_class": "perp",
        "weights": weights, "venue_symbols": {k: listing[k] for k in weights}, "listed_on": LISTED_ON,
        "dropped": [], "regime_on": None, "cadence": "daily",
        "lab_exposure": {"long": long, "short": short, "gross": round(long - short, 6), "net": round(long + short, 6)},
        "autopilot_only": True, "experimental": True,
        "experiment": {"label": LABEL, "why_failed": EVIDENCE["why_failed"], "would_change": WOULD_CHANGE,
                       "notes": "results/funding_carry.md"},
        "evidence": dict(EVIDENCE),
    }


def mark(w: dict[str, float], prev_mid: dict[str, float], mid: dict[str, float]) -> tuple[float, dict, set]:
    rets = {s: mid[s] / prev_mid[s] - 1 for s in w if s in mid and prev_mid.get(s)}
    gross = sum(w[s] * r for s, r in rets.items())
    denom = 1 + gross
    gone = {s for s in w if s not in mid}
    if denom > 0:
        w = {s: x * (1 + rets.get(s, 0.0)) / denom for s, x in w.items()}
    return gross, {s: x for s, x in w.items() if s not in gone}, gone


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    t_start = time.time()
    dry = "--dry-run" in argv
    now_us = time.time_ns() // 1000
    now_ms = now_us // 1000
    decision_day = (now_us // DAY_US - 1) * DAY_US
    state_file = DIR / "state.json"
    st = json.loads(state_file.read_text()) if state_file.exists() else None
    try:
        listing, listing_cache, listing_note = listing_for((st or {}).get("kraken_listing"), now_ms)
    except RuntimeError as e:
        print(f"{e}; no signal written", file=sys.stderr)
        return 1

    E, info = m4.live_panel(decision_day)
    if E["day"].max() < decision_day:
        print("history ends before yesterday; not rebalancing on stale data", file=sys.stderr)
        return 1
    exch = m4.get(f"{m4.FAPI}/exchangeInfo")["symbols"]
    live = {s["symbol"] for s in exch if s.get("contractType") == "PERPETUAL" and s["status"] == "TRADING"
            and s.get("quoteAsset") == "USDT"}
    quotes = {q["symbol"]: (float(q["bidPrice"]), float(q["askPrice"])) for q in m4.get(f"{m4.FAPI}/ticker/bookTicker")
              if float(q["bidPrice"]) > 0 and float(q["askPrice"]) > 0}
    prem = {p["symbol"]: p for p in m4.get(f"{m4.FAPI}/premiumIndex")}
    intervals = {f["symbol"]: int(f["fundingIntervalHours"]) for f in m4.get(f"{m4.FAPI}/fundingInfo")}
    mid = {s: (b + a) / 2 for s, (b, a) in quotes.items()}
    c = candidates(E, decision_day, live & set(quotes), listing)
    # Binance's daily perps archive for yesterday often arrives after the morning
    # backfill: the latest complete day, at most two days back, decides instead.
    for _ in range(MAX_LAG_DAYS):
        if c.height >= 2 * K:
            break
        decision_day -= DAY_US
        c = candidates(E, decision_day, live & set(quotes), listing)
    if c.height < 2 * K:
        # Still nothing scoreable: an empty tranche would halve the book for three
        # days, so nothing is traded today.
        print(f"only {c.height} listed perps scoreable on the decision day; not rebalancing on stale data",
              file=sys.stderr)
        return 1

    if st is None:
        st = {"variant": VARIANT, "started": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "equity": START_EQUITY, "tranches": [{} for _ in range(HOLD)], "weights": {}, "mid": {},
              "last_run_ms": None, "kraken_listing": listing_cache}
        # Day one starts where the backtest stands: the older tranches from the previous days' funding.
        for j in range(1, HOLD):
            d = decision_day - j * DAY_US
            st["tranches"][int(d // DAY_US) % HOLD] = new_tranche(candidates(E, d, live & set(quotes), listing))
    equity = st["equity"]
    tranches = [{s: float(x) for s, x in tr.items()} for tr in st["tranches"]]
    w = {s: float(x) for s, x in st["weights"].items()}

    funding, fallback = 0.0, []
    if st["last_run_ms"]:
        for s, x in w.items():
            rate = m4.settled_funding(s, st["last_run_ms"], now_ms)
            if rate is None and s in prem:
                n = (now_ms - st["last_run_ms"]) / 3_600_000 / intervals.get(s, 8)
                rate = float(prem[s]["lastFundingRate"]) * round(n)
                fallback.append(s)
            funding += -x * (rate or 0.0)
    gross, w, gone = mark(w, st["mid"], mid)
    rets = {s: mid[s] / st["mid"][s] - 1 for s in st["weights"] if s in mid and st["mid"].get(s)}
    denom = 1 + gross
    if denom > 0:
        tranches = [{s: x * (1 + rets.get(s, 0.0)) / denom for s, x in tr.items() if s not in gone} for tr in tranches]
    equity *= 1 + gross + funding

    slot = int(decision_day // DAY_US) % HOLD
    tranches[slot] = new_tranche(c)
    tgt = book_of(tranches)
    syms = set(w) | set(tgt)
    delta = {s: tgt.get(s, 0.0) - w.get(s, 0.0) for s in syms}
    half = {s: (quotes[s][1] - quotes[s][0]) / mid[s] / 2 for s in syms if s in quotes}
    paper_cost = sum(abs(x) * (m4.TAKER_UM + half.get(s, 0.0)) for s, x in delta.items())
    model_cost = sum(abs(x) for x in delta.values()) * MODEL_COST
    equity *= 1 - paper_cost
    carry = sum(-x * float(prem[s]["lastFundingRate"]) * 24 / intervals.get(s, 8) for s, x in tgt.items() if s in prem)
    picked = tranches[slot]
    row = {
        "date": datetime.fromtimestamp(now_us / 1e6, timezone.utc).strftime("%Y-%m-%d"),
        "equity": round(equity, 2), "gross_ret_pct": round(gross * 100, 4), "funding_pct": round(funding * 100, 4),
        "paper_cost_bps": round(paper_cost * 1e4, 2), "model_cost_bps": round(model_cost * 1e4, 2),
        "turnover": round(sum(abs(x) for x in delta.values()), 4),
        "long_exposure": round(sum(x for x in tgt.values() if x > 0), 4),
        "short_exposure": round(-sum(x for x in tgt.values() if x < 0), 4), "held": len(tgt),
        "funding_carry_bps_day": round(carry * 1e4, 2), "funding_fresh": info["funding_fresh"],
        "longs": " ".join(sorted(s for s, x in picked.items() if x > 0)),
        "shorts": " ".join(sorted(s for s, x in picked.items() if x < 0)),
        "weights": json.dumps({s: round(x, 4) for s, x in sorted(tgt.items())}),
        "listed_universe": c.height, "kraken_listing": listing_note,
    }
    sig = signal(tgt, listing, decision_day, now_us)
    took = {"secs": round(time.time() - t_start), "peak_mb": round(m4.peak_mb())}
    if dry:
        print(json.dumps({"dry_run": True, "variant": VARIANT, "panel": info, "listed_universe": c.height,
                          "kraken_listing": listing_note, "funding_fallback": fallback, "row": row,
                          "weights": sig["weights"], "lab_exposure": sig["lab_exposure"], "took": took}, indent=2))
        return 0
    DIR.mkdir(parents=True, exist_ok=True)
    journal = DIR / "journal.csv"
    new = not journal.exists()
    with journal.open("a", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=list(row))
        if new:
            wr.writeheader()
        wr.writerow(row)
    st.update(equity=equity, tranches=tranches, weights=tgt, mid={s: mid[s] for s in tgt if s in mid},
              last_run_ms=now_ms, kraken_listing=listing_cache)
    state_file.write_text(json.dumps(st, indent=2))
    save_signal(NAME, sig, now_us)
    print(json.dumps(row))
    return 0


if __name__ == "__main__":
    sys.exit(main())
