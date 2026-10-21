"""EXPERIMENTAL paper book: the three market-neutral perp books held as one, and its engine signal. No real money.

The perps_neutral_portfolio study (results/perps_neutral_portfolio.md) holds M4 reg7n,
funding carry and the sweep's low-vol beta-neutral book (family 7, vol 60d, top 50,
weekly) in one book, weighted by equal risk contribution on the trailing 90 days and
reweighted on the first day of each month. It passes its registered gates (from 2024
Sharpe 2.47 at 10 bps, drawdown 10 %, correlation with BTC -0.05) but FAILS deflation
(deflated p 0.32 over 1,953 trials). It therefore runs as an EXPERIMENT: its signal is
marked experimental and autopilot_only, so the engine never runs it on its own, the auto
pick never picks it, a live autopilot refuses it, and only an autopilot that names it
trades it, on a perps DEMO route.

Every run (daily, after paper-m4-perps and paper-funding-carry):
  1. the Kraken Futures listing (public, no key; the last good one is kept in the state);
  2. the targets of the two running books from their engine signals
     (<data>/signals/m4_perps and funding_carry, signed weights per coin); a missing or
     expired one stops the run (exit 1, no signal);
  3. the low-vol book's target from the sweep panel the paper jobs build
     ($PYTHIA_AGENT_OUT, default <data>/lab-cache) with perp data rebuilt in memory, on
     its last day with perp data: recomputed on the weekly rebalance rows
     (fam_common.every(P, 7)), kept otherwise; coins Kraken Futures does not list are
     dropped and each leg scaled back to its gross;
  4. each sub-book and the combined book marked to the live Binance USD-M mid with the
     settled Binance funding (m4_ls's machinery); the sub-books' daily returns are kept;
  5. book weights: on the first run of a calendar month, equal risk contribution on the
     last 90 daily returns of the three sub-books when 60 or more exist, else the
     study's mean weights from 2024 (START_WEIGHTS); drifting with the sub-books between;
  6. the combined target (sum of book weight x sub-book target, netted per coin) as the
     engine signal <data>/signals/perps_neutral/latest.json with each coin's Kraken symbol.

  python -m lab.paper.perps_neutral             one step, writes state, journal and signal
  python -m lab.paper.perps_neutral --dry-run   prints the decision and the signal; writes nothing

State and journal: <data>/paper/perps_neutral/.
"""

from __future__ import annotations

import csv
import json
import sys
import time
from datetime import datetime, timezone

import numpy as np

from ..data import ROOT
from ..experiments import fam_common as fc
from ..experiments import perps_common as pc
from ..experiments.perps_neutral_portfolio import erc
from . import funding_carry as carry
from . import m4_ls as m4
from .experimental import LABEL
from .tsmom import save_signal

NAME = "perps_neutral"
SUBS = {"M4": "m4_perps", "Carry": "funding_carry"}
BOOKS = ("M4", "Carry", "LowVol")
START_WEIGHTS = {"M4": 0.30, "Carry": 0.38, "LowVol": 0.32}
LOOKBACK, MIN_OBS = 90, 60
VARIANT = (f"{LABEL} · M4 reg7n, funding carry and low-vol beta-neutral perps books in one book · equal risk "
           "contribution, monthly · coins Kraken Futures lists")
START_EQUITY = 10_000.0
MODEL_COST = pc.JUDGED
SIGNAL_VALID_MS = 36 * 3600 * 1000
DIR = ROOT / "paper" / NAME
LISTED_ON = "kraken_futures"
MAX_LAG_DAYS = 2

# Source: results/perps_neutral_portfolio.md (pick ERC; holdout 2024-01-02 to 2026-09-29,
# 10 bps per unit of one-way turnover, Binance funding both ways).
EVIDENCE = {
    "report": "perps_neutral_portfolio",
    "experimental": True,
    "is_sharpe": 1.18,
    "oos_sharpe": 2.47,
    "oos_sharpe_2bps": 2.66,
    "oos_sharpe_20bps": 2.23,
    "oos_sharpe_41bps": 1.73,
    "oos_max_dd": 0.10,
    "corr_btc": -0.05,
    "bootstrap_90": [1.66, 3.28],
    "reference_book": "M4 alone 2.20, drawdown 15 %",
    "regime_sharpes": {"2024": 2.28, "2025": 3.10, "2026 to 2026-09-29": 1.86},
    "regime_filter": False,
    "deflated_p": 0.32,
    "variants_tried": 1953,
    "cost_note": "Sharpe at 10 bps per unit of one-way turnover (Kraken taker plus half-spread), Binance funding "
                 "charged and received, netting between books not credited",
    "why_failed": "deflated p 0.32 over 1,953 trials; equal weight does as well as ERC; M4 and low vol are one bet "
                  "(correlation 0.44)",
    "caveat": "Two of the three books short the same hot small caps that bled from 2024; low vol earned 0.50 in sample",
    "verdict": "experiment, passes the registered gates, fails deflation",
}
WOULD_CHANGE = "90 forward days above the backtest's 5 % band net of Kraken fees and Kraken's own funding"


# ---------------------------------------------------------------------------
# Pieces (pure, tested)
# ---------------------------------------------------------------------------

def coin_to_perp(live_perps: set[str]) -> dict[str, str]:
    """{coin: Binance USDT perp} among the live perps (the most liquid duplicate is not
    known here, so the plain one wins over a 1000x one)."""
    out: dict[str, str] = {}
    for s in sorted(live_perps, key=lambda x: (len(x), x)):
        out.setdefault(pc.coin_of(s), s)
    return out


def sub_target(sig: dict | None, now_ms: int) -> dict[str, float] | None:
    """A book's signed weights per coin from its engine signal, None when missing or expired."""
    if not sig or int(sig.get("valid_until_ms", 0)) < now_ms:
        return None
    return {str(c): float(x) for c, x in (sig.get("weights") or {}).items() if float(x) != 0.0}


def lowvol_target(P: fc.Panel, t: int, listing: dict[str, str]) -> dict[str, float]:
    """The sweep's beta-neutral low-vol target on panel row t, per coin, restricted to the
    coins Kraken Futures lists with a live Binance perp; each leg scaled back to its gross."""
    from ..experiments import fam_lowvol as flv
    W = flv.weights(P, "vol 60d", 50, "beta-neutral BAB")[t]
    return restrict_legs({pc.coin_of(P.names[j]): float(W[j]) for j in np.flatnonzero(np.nan_to_num(W) != 0)
                          if "~" not in P.names[j] and P.perp_ok[t, j]}, listing)


def with_fresh_perps(P: fc.Panel) -> fc.Panel:
    """The panel with perp_ok and funding rebuilt in memory from today's perp archive
    (the cached perp_daily under the paper jobs' folder is built once and goes stale; it
    is neither read nor written here)."""
    import dataclasses

    import polars as pl

    from ..experiments.picks_ls import perp_panel
    pp = perp_panel()
    perp = (pp.sort("qv", descending=True).group_by(["day", "base"]).first()
            .select("day", "base", "funding").filter(pl.col("day").is_in(P.days.tolist())))
    di = {int(d): i for i, d in enumerate(P.days)}
    cols: dict[str, list[int]] = {}
    for j, b in enumerate(P.bases):
        cols.setdefault(b, []).append(j)
    perp_ok = np.zeros((P.T, P.N), dtype=bool)
    funding = np.zeros((P.T, P.N))
    for d, b, f in zip(perp["day"].to_numpy(), perp["base"].to_list(), perp["funding"].to_numpy()):
        t = di.get(int(d))
        for j in cols.get(b, ()):
            if t is not None and P.alive[t, j]:
                perp_ok[t, j] = True
                funding[t, j] = 0.0 if not np.isfinite(f) else f
    return dataclasses.replace(P, perp_ok=perp_ok, funding=funding)


def restrict_legs(w: dict[str, float], listing: dict[str, str]) -> dict[str, float]:
    L0, S0 = sum(x for x in w.values() if x > 0), -sum(x for x in w.values() if x < 0)
    kept = {c: x for c, x in w.items() if c in listing}
    L1, S1 = sum(x for x in kept.values() if x > 0), -sum(x for x in kept.values() if x < 0)
    if L1 <= 0 or S1 <= 0:
        return {}
    return {c: x * (L0 / L1 if x > 0 else S0 / S1) for c, x in kept.items()}


def book_weights(st_w: dict[str, float] | None, returns: list[dict], new_month: bool) -> tuple[dict[str, float], str]:
    """Weights for today and how they were set: on a new month ERC on the last LOOKBACK
    returns (at least MIN_OBS complete rows), else START_WEIGHTS; otherwise the drifted ones."""
    if st_w and not new_month:
        return dict(st_w), "drift"
    rows = [r for r in returns[-LOOKBACK:] if all(isinstance(r.get(b), (int, float)) for b in BOOKS)]
    if len(rows) >= MIN_OBS:
        X = np.array([[r[b] for b in BOOKS] for r in rows])
        w = erc(np.cov(X, rowvar=False))
        return {b: float(x) for b, x in zip(BOOKS, w)}, f"ERC on {len(rows)} days"
    return dict(START_WEIGHTS), f"start weights ({len(rows)} days of history)"


def drift(w: dict[str, float], r: dict[str, float]) -> dict[str, float]:
    g = sum(w[b] * r.get(b, 0.0) for b in w)
    if 1 + g <= 0:
        return dict(w)
    out = {b: w[b] * (1 + r.get(b, 0.0)) / (1 + g) for b in w}
    s = sum(out.values())
    return {b: x / s for b, x in out.items()}


def combined(w: dict[str, float], targets: dict[str, dict[str, float]]) -> dict[str, float]:
    out: dict[str, float] = {}
    for b, tgt in targets.items():
        for c, x in tgt.items():
            out[c] = out.get(c, 0.0) + w[b] * x
    return {c: x for c, x in out.items() if abs(x) > 1e-12}


def book_return(w: dict[str, float], prev_mid: dict[str, float], mid: dict[str, float],
                funding: dict[str, float]) -> float:
    """One day of a coin-weighted perp book: price change of each held coin plus the
    funding it paid (long) or received (short)."""
    r = 0.0
    for c, x in w.items():
        if c in mid and prev_mid.get(c):
            r += x * (mid[c] / prev_mid[c] - 1)
        r -= x * funding.get(c, 0.0)
    return r


def signal(tgt: dict[str, float], listing: dict[str, str], as_of_us: int, now_us: int, book_w: dict) -> dict:
    weights = {k: round(x, 6) for k, x in sorted(tgt.items()) if round(x, 6) != 0 and k in listing}
    long = round(sum(x for x in weights.values() if x > 0), 6)
    short = round(sum(x for x in weights.values() if x < 0), 6)
    return {
        "strategy": NAME, "variant": VARIANT, "as_of_ms": as_of_us // 1000, "generated_ms": now_us // 1000,
        "valid_until_ms": now_us // 1000 + SIGNAL_VALID_MS, "quote": "USD", "asset_class": "perp",
        "weights": weights, "venue_symbols": {k: listing[k] for k in weights}, "listed_on": LISTED_ON,
        "dropped": [], "regime_on": None, "cadence": "daily",
        "lab_exposure": {"long": long, "short": short, "gross": round(long - short, 6), "net": round(long + short, 6)},
        "book_weights": {b: round(x, 4) for b, x in book_w.items()},
        "autopilot_only": True, "experimental": True,
        "experiment": {"label": LABEL, "why_failed": EVIDENCE["why_failed"], "would_change": WOULD_CHANGE,
                       "notes": "results/perps_neutral_portfolio.md"},
        "evidence": dict(EVIDENCE),
    }


def read_signal(name: str) -> dict | None:
    p = ROOT / "signals" / name / "latest.json"
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------------------
# One step
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    t_start = time.time()
    dry = "--dry-run" in argv
    now_us = time.time_ns() // 1000
    now_ms = now_us // 1000
    today = datetime.fromtimestamp(now_us / 1e6, timezone.utc)
    state_file = DIR / "state.json"
    st = json.loads(state_file.read_text()) if state_file.exists() else None
    try:
        listing, listing_cache, listing_note = carry.listing_for((st or {}).get("kraken_listing"), now_ms)
    except RuntimeError as e:
        print(f"{e}; no signal written", file=sys.stderr)
        return 1

    targets: dict[str, dict[str, float]] = {}
    for b, name in SUBS.items():
        tgt = sub_target(read_signal(name), now_ms)
        if tgt is None:
            print(f"the {name} signal is missing or expired; no signal written", file=sys.stderr)
            return 1
        targets[b] = tgt

    P = with_fresh_perps(fc.load_panel())
    # Binance's daily perps archive for yesterday often arrives after the morning
    # backfill: the latest day with perp data decides, at most MAX_LAG_DAYS back.
    t = P.T - 1
    for _ in range(MAX_LAG_DAYS):
        if P.perp_ok[t].any():
            break
        t -= 1
    if not P.perp_ok[t].any():
        print("no perp data in the panel's last days; not rebalancing on stale data", file=sys.stderr)
        return 1
    if (st or {}).get("lowvol") and not fc.every(P, 7)[t]:
        targets["LowVol"] = {c: float(x) for c, x in st["lowvol"].items()}
        lv_note = f"kept from {st.get('lowvol_day')}"
    else:
        targets["LowVol"] = lowvol_target(P, t, listing)
        lv_note = f"rebalanced on {datetime.fromtimestamp(int(P.days[t]) / 1e6, timezone.utc):%Y-%m-%d}"
    if not targets["LowVol"]:
        print("the low-vol book has no listed long or short leg; no signal written", file=sys.stderr)
        return 1

    exch = m4.get(f"{m4.FAPI}/exchangeInfo")["symbols"]
    live = {s["symbol"] for s in exch if s.get("contractType") == "PERPETUAL" and s["status"] == "TRADING"
            and s.get("quoteAsset") == "USDT"}
    perp_of = coin_to_perp(live)
    quotes = {q["symbol"]: (float(q["bidPrice"]), float(q["askPrice"])) for q in m4.get(f"{m4.FAPI}/ticker/bookTicker")
              if float(q["bidPrice"]) > 0 and float(q["askPrice"]) > 0}
    mid = {c: (quotes[s][0] + quotes[s][1]) / 2 for c, s in perp_of.items() if s in quotes}
    half = {c: (quotes[s][1] - quotes[s][0]) / mid[c] / 2 for c, s in perp_of.items() if s in quotes}

    if st is None:
        st = {"variant": VARIANT, "started": today.isoformat(timespec="seconds"), "equity": START_EQUITY,
              "weights": {}, "subs": {}, "mid": {}, "returns": [], "book_w": None, "w_month": None,
              "last_run_ms": None, "kraken_listing": listing_cache}
    equity = st["equity"]
    held = {c: float(x) for c, x in st["weights"].items()}

    # Mark yesterday's holdings: each sub-book and the combined book.
    fund: dict[str, float] = {}
    if st["last_run_ms"]:
        for c in set(held) | {c for s in st["subs"].values() for c in s}:
            if c in perp_of:
                fund[c] = m4.settled_funding(perp_of[c], st["last_run_ms"], now_ms) or 0.0
    r_sub = {b: book_return(st["subs"].get(b, {}), st["mid"], mid, fund) for b in BOOKS} if st["last_run_ms"] else {}
    r_all = book_return(held, st["mid"], mid, fund) if st["last_run_ms"] else 0.0
    equity *= 1 + r_all
    returns = list(st["returns"])
    if r_sub:
        returns.append({"date": today.strftime("%Y-%m-%d"), **{b: round(r_sub[b], 8) for b in BOOKS}})
    w_now = drift(st["book_w"], r_sub) if st["book_w"] and r_sub else st["book_w"]
    month = today.strftime("%Y-%m")
    book_w, how = book_weights(w_now, returns, st["w_month"] != month)

    tgt = combined(book_w, targets)
    tgt = {c: x for c, x in tgt.items() if c in listing and c in mid}
    delta = {c: tgt.get(c, 0.0) - held.get(c, 0.0) for c in set(tgt) | set(held)}
    paper_cost = sum(abs(x) * (m4.TAKER_UM + half.get(c, 0.0)) for c, x in delta.items())
    model_cost = sum(abs(x) for x in delta.values()) * MODEL_COST
    equity *= 1 - paper_cost
    row = {
        "date": today.strftime("%Y-%m-%d"), "equity": round(equity, 2), "ret_pct": round(r_all * 100, 4),
        **{f"ret_{b}_pct": round(r_sub.get(b, 0.0) * 100, 4) for b in BOOKS},
        **{f"w_{b}": round(book_w[b], 4) for b in BOOKS}, "weights_set": how, "lowvol": lv_note,
        "paper_cost_bps": round(paper_cost * 1e4, 2), "model_cost_bps": round(model_cost * 1e4, 2),
        "turnover": round(sum(abs(x) for x in delta.values()), 4),
        "long_exposure": round(sum(x for x in tgt.values() if x > 0), 4),
        "short_exposure": round(-sum(x for x in tgt.values() if x < 0), 4), "held": len(tgt),
        "kraken_listing": listing_note,
    }
    sig = signal(tgt, listing, int(P.days[t]), now_us, book_w)
    if dry:
        print(json.dumps({"dry_run": True, "variant": VARIANT, "row": row, "weights": sig["weights"],
                          "lab_exposure": sig["lab_exposure"], "secs": round(time.time() - t_start)}, indent=2))
        return 0
    DIR.mkdir(parents=True, exist_ok=True)
    journal = DIR / "journal.csv"
    new = not journal.exists()
    with journal.open("a", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=list(row))
        if new:
            wr.writeheader()
        wr.writerow(row)
    keep = set(tgt) | {c for s in targets.values() for c in s}
    st.update(equity=equity, weights=tgt, subs=targets, mid={c: mid[c] for c in keep if c in mid},
              returns=returns[-400:], book_w=book_w, w_month=month, last_run_ms=now_ms, kraken_listing=listing_cache,
              lowvol=targets["LowVol"], lowvol_day=st.get("lowvol_day") if lv_note.startswith("kept")
              else f"{datetime.fromtimestamp(int(P.days[t]) / 1e6, timezone.utc):%Y-%m-%d}")
    state_file.write_text(json.dumps(st, indent=2))
    save_signal(NAME, sig, now_us)
    print(json.dumps(row))
    return 0


if __name__ == "__main__":
    sys.exit(main())
