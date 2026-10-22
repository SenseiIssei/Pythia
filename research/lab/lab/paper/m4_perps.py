"""EXPERIMENTAL shadow book of M4 reg7n on the perps Kraken Futures lists, and its engine signal. No real money.

M4's registered pick reg7n (results/m4_residual.md: LightGBM regression on the
funding-net 7-day rank label y7n, 10 long / 10 short of the 100 most liquid
perps, rank buffer 50 %) earns beyond the low-vol factor and BTC in the residual
test, but it FAILS deflation (deflated p 0.0020 over 1,724 trials). It therefore
runs as an EXPERIMENT: its signal is marked experimental and autopilot_only, so
the engine never runs it on its own, the auto pick never picks it, a live
autopilot refuses it, and only an autopilot that names it trades it, on a perps
DEMO route. Demo and paper only, no real money.

Configuration: m4_ls's machinery (same panel, same features and parameters, same
retrain rule, same funding booking) with CONFIG below: model reg7n, mode buffer,
exit_frac 0.5, k 10, n_liquid 100. m4_ls itself is untouched and keeps running
rank3 held 3 days.

Every run (daily, after the nightly backfill):
  1. fetch the Kraken Futures listing (public instruments endpoint, no key):
     PF_ perpetuals that are tradeable and not suspended. The last good listing
     is kept in the state; when the fetch fails the cached one is used and the
     journal says so; with no cache at all the run stops (exit 1, no signal);
  2. rebuild the xs_daily panel and the model exactly like m4_ls (model cache
     m4_perps_reg7n.txt/.json under $PYTHIA_CACHE, apart from m4_ls's);
  3. mark the book to the live Binance USD-M mid and book the settled Binance
     funding, exactly like m4_ls;
  4. take the 100 most liquid perps of the day exactly as m4_ls.candidates picks
     them, THEN drop every coin Kraken Futures does not list (journaled as
     dropped_unlisted), then rank and apply the 50 % rank buffer among the
     listed ones, so the book is 10 long / 10 short of the listed coins;
  5. write the target as the engine signal <data>/signals/m4_perps/latest.json:
     signed weights per coin (longs positive, shorts negative, about +0.5 and
     -0.5 of capital) with the Kraken symbol of each coin.

The residual test ran on the 100 most liquid Binance perps; this book keeps only
the ones Kraken lists, so its forward record is that restricted book's, not the
tested one's.

  python -m lab.paper.m4_perps             one step, writes state, journal and signal
  python -m lab.paper.m4_perps --dry-run   prints the decision, the signal and its evidence;
                                           writes nothing but the lab cache (panel, model)

Cache (panel and model): $PYTHIA_CACHE, default <data>/lab-cache.
State: <data>/paper/m4_perps/state.json   Journal: <data>/paper/m4_perps/journal.csv
Signal: <data>/signals/m4_perps/latest.json
"""

from __future__ import annotations

import csv
import json
import sys
import time
from datetime import datetime, timezone

import polars as pl

from ..data import ROOT, WRITE_ROOT
from ..experiments import xs_daily as xs
from . import m4_ls as m4
from .experimental import LABEL
from .tsmom import save_signal

NAME = "m4_perps"
CONFIG = {
    "model": "reg7n",       # regression on the funding-net 7-day rank label y7n
    "k": 10,                # longs and shorts each
    "n_liquid": 100,        # the most liquid USDT perps of the day, before the Kraken restriction
    "mode": "buffer",       # rank buffer (xs_daily.book_buffer)
    "hold": None,
    "exit_frac": 0.5,
}
VARIANT = (f"{LABEL} · M4 reg7n · 10/10 of the 100 most liquid perps listed on Kraken Futures · "
           "rank buffer 50 %")
START_EQUITY = 10_000.0
MODEL_COST = xs.COSTS["41bps"]      # the cost the evidence below is quoted at
SIGNAL_VALID_MS = 36 * 3600 * 1000
DAY_US = xs.DAY_US
DIR = WRITE_ROOT / "paper" / NAME
KRAKEN_INSTRUMENTS = "https://futures.kraken.com/derivatives/api/v3/instruments"
LISTED_ON = "kraken_futures"

# Binance lists some low-priced coins per 1,000 (or a million) units.
MULTIPLIERS = ("1000000", "100000", "10000", "1000", "1M")
# One coin, two tickers: a renamed coin (MATIC is POL now) and Kraken's name for BTC.
ALIASES = {"MATIC": "POL", "XBT": "BTC"}

# Source: results/m4_residual.md (the 41 bps rows of its tables, reg7n fit window
# 2022-2023, holdout 2024-01-01 to 2026-09-28; deflated p and the pool from its text).
EVIDENCE = {
    "report": "m4_residual",
    "experimental": True,
    "is_sharpe": 0.93,
    "oos_sharpe": 2.02,
    "residual_oos_sharpe": 0.96,
    "residual_oos_sharpe_15bps": 1.08,
    "bootstrap_90": [0.16, 1.77],
    "boot_above0": 0.98,
    "b_lowvol": 0.707,
    "b_btc": 0.009,
    "r2_fit": 0.513,
    "regime_sharpes": {"2023 (fit window)": 0.76, "2024": 1.08, "2025": 1.13, "2026 to 2026-09-28": 0.65},
    "regime_filter": False,
    "deflated_p": 0.002,
    "variants_tried": 1724,
    "sharpe_2x_cost": None,
    "cost_note": "Sharpe at 41 bps per unit of one-way turnover, funding charged; residual_oos_sharpe is what "
                 "is left after the frozen low-vol and BTC betas, regime_sharpes are that residual by year",
    "why_failed": "deflated p 0.0020 over 1,724 trials: one holdout, the same one that favoured the low-vol bet",
    "caveat": "Leans on the low-vol factor (beta 0.71, rolling 0.5 to 0.84); the residual test ran on the 100 "
              "most liquid Binance perps, this book keeps only the ones Kraken Futures lists",
    "verdict": "experiment, passes the residual test, fails deflation",
}
WOULD_CHANGE = ("a forward record that beats the low-vol book of the same shape net of fees and funding "
                "(the next registration results/m4_residual.md names)")


class NoListing(RuntimeError):
    """Neither a fresh nor a cached Kraken Futures listing: nothing can be traded."""


# ---------------------------------------------------------------- coins and the Kraken listing

def coin_of(symbol: str) -> str:
    """The coin a Binance USDT perp (or a bare ticker) names: 1000PEPEUSDT -> PEPE,
    BTCUSDT -> BTC, MATICUSDT -> POL, XBT -> BTC."""
    s = symbol.upper()
    if s.endswith("USDT"):
        s = s[:-4]
    for p in MULTIPLIERS:
        if s.startswith(p) and len(s) > len(p):
            s = s[len(p):]
            break
    return ALIASES.get(s, s)


def kraken_coin(instrument: dict) -> str | None:
    """The coin of a Kraken Futures perpetual: its `base` field (BTC for PF_XBTUSD),
    else parsed from the symbol PF_<X>USD."""
    base = instrument.get("base")
    if isinstance(base, str) and base:
        return ALIASES.get(base, base)
    sym = str(instrument.get("symbol", ""))
    if sym.startswith("PF_") and sym.endswith("USD") and len(sym) > 6:
        x = sym[3:-3]
        return ALIASES.get(x, x)
    return None


def parse_listing(answer: dict) -> dict[str, str]:
    """{coin: Kraken symbol} of the PF_ perpetuals Kraken Futures trades right now
    (type flexible_futures, tradeable, not suspended). Raises ValueError on an answer
    that is not a successful listing or lists nothing."""
    if not isinstance(answer, dict) or answer.get("result") not in (None, "success"):
        raise ValueError(f"instruments answer: {str(answer)[:200]}")
    out: dict[str, str] = {}
    for ins in answer.get("instruments") or []:
        sym = str(ins.get("symbol", ""))
        if not sym.startswith("PF_") or ins.get("type") != "flexible_futures":
            continue
        if ins.get("tradeable") is not True or ins.get("suspended", False):
            continue
        coin = kraken_coin(ins)
        if coin:
            out.setdefault(coin, sym)
    if not out:
        raise ValueError("instruments answer lists no tradeable PF_ perpetual")
    return out


def fetch_listing() -> dict[str, str]:
    return parse_listing(m4.get(KRAKEN_INSTRUMENTS))


def listing_for(cached: dict | None, now_ms: int, fetch=fetch_listing) -> tuple[dict[str, str], dict, str]:
    """(listing, what to cache, journal note). A failed fetch falls back to the cached
    listing; with no cache it raises NoListing."""
    try:
        listing = fetch()
        return listing, {"fetched_ms": now_ms, "symbols": listing}, "live"
    except Exception as e:  # noqa: BLE001 - any failure falls back to the cache
        if cached and cached.get("symbols"):
            day = datetime.fromtimestamp(cached["fetched_ms"] / 1000, timezone.utc).strftime("%Y-%m-%d")
            return dict(cached["symbols"]), cached, f"cached {day} (fetch failed: {type(e).__name__})"
        raise NoListing(f"Kraken Futures listing unavailable and no cached one ({type(e).__name__}: {e})") from e


# ---------------------------------------------------------------- the book

def restrict(c: pl.DataFrame, listing: dict[str, str]) -> tuple[pl.DataFrame, list[str]]:
    """m4_ls.candidates' liquid set (best score first) cut to the coins Kraken lists.
    Returns the listed candidates (with a `coin` column, still best first) and the
    coins dropped as unlisted. Two perps of one coin keep the more liquid one."""
    c = c.with_columns(coin=pl.Series([coin_of(p) for p in c["perp"].to_list()], dtype=pl.Utf8))
    dropped = sorted({x for x in c["coin"].to_list() if x not in listing})
    listed = (c.filter(pl.col("coin").is_in(sorted(listing)))
              .sort("perp_adv28", descending=True).unique("coin", keep="first", maintain_order=True)
              .sort("score", descending=True))
    return listed, dropped


def target(listed: pl.DataFrame, w: dict[str, float]) -> dict[str, float]:
    """The rank-buffer book among the listed coins, on the drifted weights w (Binance
    perp symbol -> signed fraction)."""
    tgt = m4.buffer_target(listed, w, cfg=CONFIG)
    return {s: x for s, x in tgt.items() if abs(x) > 1e-12}


def mark(w: dict[str, float], prev_mid: dict[str, float], mid: dict[str, float]) -> tuple[float, dict, set]:
    """m4_ls's mark to market: (gross return, drifted weights without the gone perps,
    the perps without a live quote, closed at their last mark)."""
    rets = {s: mid[s] / prev_mid[s] - 1 for s in w if s in mid and prev_mid.get(s)}
    gross = sum(w[s] * r for s, r in rets.items())
    denom = 1 + gross
    if denom > 0:
        w = {s: x * (1 + rets.get(s, 0.0)) / denom for s, x in w.items()}
    gone = {s for s in w if s not in mid}
    return gross, {s: x for s, x in w.items() if s not in gone}, gone


def signal(tgt: dict[str, float], listing: dict[str, str], dropped_unlisted: list[str], as_of_us: int,
           now_us: int) -> dict:
    """The engine signal: signed weights per coin with each coin's Kraken symbol."""
    weights: dict[str, float] = {}
    dropped: list[str] = []
    dropped_weight = 0.0
    for perp, x in sorted(tgt.items()):
        coin = coin_of(perp)
        if coin not in listing:
            dropped.append(coin)
            dropped_weight += abs(x)
            continue
        weights[coin] = weights.get(coin, 0.0) + x
    weights = {k: round(x, 6) for k, x in sorted(weights.items()) if round(x, 6) != 0}
    long = round(sum(x for x in weights.values() if x > 0), 6)
    short = round(sum(x for x in weights.values() if x < 0), 6)
    sig = {
        "strategy": NAME,
        "variant": VARIANT,
        "as_of_ms": as_of_us // 1000,            # the decision day the scores were computed from
        "generated_ms": now_us // 1000,
        "valid_until_ms": now_us // 1000 + SIGNAL_VALID_MS,
        "quote": "USD",
        "asset_class": "perp",
        "weights": weights,                      # longs positive, shorts negative
        "venue_symbols": {k: listing[k] for k in weights},
        "listed_on": LISTED_ON,
        "dropped": sorted(set(dropped)),
        "dropped_unlisted": list(dropped_unlisted),
        "dropped_weight": round(dropped_weight, 6),
        "regime_on": None,
        "cadence": "daily",
        # Signed like the weights: short is the (negative) sum of the short side.
        "lab_exposure": {"long": long, "short": short, "gross": round(long - short, 6),
                         "net": round(long + short, 6)},
        "autopilot_only": True,
        "experimental": True,
        "experiment": {"label": LABEL, "why_failed": EVIDENCE["why_failed"], "would_change": WOULD_CHANGE,
                       "notes": "results/m4_residual.md"},
        "evidence": dict(EVIDENCE),
    }
    return sig


def new_state(listing_cache: dict) -> dict:
    return {"variant": VARIANT, "config": CONFIG, "started": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "equity": START_EQUITY, "weights": {}, "mid": {}, "last_run_ms": None, "kraken_listing": listing_cache}


# How many days the decision may step back when the newest day is incomplete,
# and how many perps a day needs to count as complete.
MAX_LAG_DAYS = 2
MIN_SCOREABLE = 20


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
    except NoListing as e:
        print(f"{e}; no signal written", file=sys.stderr)
        return 1
    if listing_note != "live":
        print(f"Kraken Futures listing: {listing_note}", file=sys.stderr)

    E, info = m4.live_panel(decision_day)
    if E["day"].max() < decision_day:
        print(f"history ends {datetime.fromtimestamp(E['day'].max() / 1e6, timezone.utc):%Y-%m-%d}, "
              "yesterday is missing; not rebalancing on stale data", file=sys.stderr)
        return 1
    booster, meta = m4.model_for(E, decision_day, cfg=CONFIG, name=NAME)

    exch = m4.get(f"{m4.FAPI}/exchangeInfo")["symbols"]
    live = {s["symbol"] for s in exch if s.get("contractType") == "PERPETUAL" and s["status"] == "TRADING"
            and s.get("quoteAsset") == "USDT"}
    quotes = {q["symbol"]: (float(q["bidPrice"]), float(q["askPrice"])) for q in m4.get(f"{m4.FAPI}/ticker/bookTicker")
              if float(q["bidPrice"]) > 0 and float(q["askPrice"]) > 0}
    prem = {p["symbol"]: p for p in m4.get(f"{m4.FAPI}/premiumIndex")}
    intervals = {f["symbol"]: int(f["fundingIntervalHours"]) for f in m4.get(f"{m4.FAPI}/fundingInfo")}
    mid = {s: (b + a) / 2 for s, (b, a) in quotes.items()}
    c = m4.candidates(E, booster, decision_day, live & set(quotes), cfg=CONFIG)
    # Binance's daily perps archive for yesterday often arrives after the morning
    # backfill: the latest day with enough scoreable perps, at most two days back,
    # decides instead.
    for _ in range(MAX_LAG_DAYS):
        if c.height >= MIN_SCOREABLE:
            break
        decision_day -= DAY_US
        booster, meta = m4.model_for(E, decision_day, cfg=CONFIG, name=NAME)
        c = m4.candidates(E, booster, decision_day, live & set(quotes), cfg=CONFIG)
    listed, dropped_unlisted = restrict(c, listing)

    if st is None:
        st = new_state(listing_cache)
    equity = st["equity"]
    w = {s: float(x) for s, x in st["weights"].items()}

    # 1 · mark to market and book funding since the last run, exactly like m4_ls.
    funding, fallback = 0.0, []
    if st["last_run_ms"]:
        for s, x in w.items():
            rate = m4.settled_funding(s, st["last_run_ms"], now_ms)
            if rate is None and s in prem:
                n = (now_ms - st["last_run_ms"]) / 3_600_000 / intervals.get(s, 8)
                rate = float(prem[s]["lastFundingRate"]) * round(n)
                fallback.append(s)
            funding += -x * (rate or 0.0)
    gross, w, _gone = mark(w, st["mid"], mid)
    equity *= 1 + gross + funding

    # 2 · today's target among the listed coins
    tgt = target(listed, w)
    picked = {s: x for s, x in tgt.items() if s not in w}
    syms = set(w) | set(tgt)
    delta = {s: tgt.get(s, 0.0) - w.get(s, 0.0) for s in syms}
    half = {s: (quotes[s][1] - quotes[s][0]) / mid[s] / 2 for s in syms if s in quotes}
    paper_cost = sum(abs(x) * (m4.TAKER_UM + half.get(s, 0.0)) for s, x in delta.items())
    model_cost = sum(abs(x) for x in delta.values()) * MODEL_COST
    equity *= 1 - paper_cost
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
        "dropped_unlisted": " ".join(dropped_unlisted),
        "listed_universe": listed.height,
        "kraken_listing": listing_note,
    }
    sig = signal(tgt, listing, dropped_unlisted, decision_day, now_us)
    took = {"secs": round(time.time() - t_start), "peak_mb": round(m4.peak_mb())}
    if dry:
        print(json.dumps({"dry_run": True,
                          "decision_day": datetime.fromtimestamp(decision_day / 1e6, timezone.utc).strftime("%Y-%m-%d"),
                          "variant": VARIANT, "model": {k: v for k, v in meta.items() if k != "features"},
                          "panel": info, "liquid_universe": c.height, "listed_universe": listed.height,
                          "kraken_listing": listing_note, "dropped_unlisted": dropped_unlisted,
                          "funding_fallback": fallback, "row": row, "weights": sig["weights"],
                          "venue_symbols": sig["venue_symbols"], "lab_exposure": sig["lab_exposure"],
                          "evidence": sig["evidence"], "took": took}, indent=2))
        return 0

    DIR.mkdir(parents=True, exist_ok=True)
    journal = DIR / "journal.csv"
    new = not journal.exists()
    with journal.open("a", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=list(row))
        if new:
            wr.writeheader()
        wr.writerow(row)
    st.update(equity=equity, weights=tgt, mid={s: mid[s] for s in tgt}, last_run_ms=now_ms,
              kraken_listing=listing_cache)
    state_file.write_text(json.dumps(st, indent=2))
    save_signal(NAME, sig, now_us)
    print(json.dumps(row))
    print(json.dumps(took), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
