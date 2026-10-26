"""EXPERIMENT, paper first: onchain_longterm, the relaxed long-term book for the owner's on-chain wallet (task L1).

S2 (results/smallaccount_s2.md) found one candidate that passed its bar at 20 to 50 EUR:
tsmom1, S1's tsmom_top20 on the single most liquid coin
(lab.experiments.smallaccount.candidate(P, "tsmom_top20", 1)): that coin held while
its 28-day return is above 0 and BTC is above its 200-day average, sized to 40 %
annual vol, the rest USDC; daily (S1 and S2 ran it daily). Out of sample at 40 EUR
28.5 % a year, drawdown 17.8 %, against the S&P 500 token's 20.4 % and 18.1 %; not
convincing (deflated p 0.65). This book is that rule on chain, with the live trader's
own limits written into its targets so paper and live hold the same:

  - only BTC (cbBTC) and ETH (WETH); a day whose most liquid coin is anything else is
    USDC (the signal names it in `dropped`). No tokenized ETF or gold: S2 recorded
    routes for SPYx and PAXG, but both are Token-2022 and the stage-2 guard refuses
    every Token-2022 account (guard.check_accounts); SOL only for the fees
  - ETH at most MAX_ETH of the book (live_gate.MAX_ETH_SHARE, WETH is bridged), the
    rest of its weight USDC
  - USDC is the safe asset

The band, the split into swaps and the fees are the book's entry in lab.onchain.book.BOOKS,
used by its paper twin and by the live trader alike: no swap for a change under 10 % of
the book or under 3 USD (book.min_trade), none above a quarter of the wallet (the live cap
with limits=wallet; a larger order is several swaps), the cheapest send path live
(live_exec.Trader.cheap: no Sender, no tip, fees.cheap_price at most 0.00002 SOL a swap,
live_gate.fitted_slippage), which the paper twin charges at its cap.

  python -m lab.onchain.longterm            daily: the targets, then the paper twin through Jupiter
  python -m lab.onchain.longterm --dry-run  print the targets, write nothing
  python -m lab.onchain.longterm --costs    the cost per swap on the recorded quotes (results/*.csv)
  python -m lab.onchain.longterm --backtest the book's own rules over S1's windows (heavy lock)

<data>/signals/onchain_longterm/latest.json  the targets, in the format of the lab's signals.
              The on-chain live service trades them when the ack names the book
              (books=onchain_longterm, docs/ONCHAIN-STAGE2.md, section 10). Marked
              experimental and autopilot_only: the exchange engine never runs it.
<data>/paper/onchain_longterm/  the paper twin: a 0.5 SOL wallet that keeps 0.035 SOL for
              fees and the token accounts' rent and swaps the rest into USDC on its
              first run, then lab.onchain.book's files and rules (Jupiter quotes,
              journal on the 10,000 basis for the forward report)
reports/onchain_longterm/  its report (lab.onchain.book.write_report); the morning briefing's
              paper card shows the wallet (lab.ops.briefing.onchain_line)

Nothing here signs, sends or holds a key.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from . import book as B
from . import fees as F

NAME = B.LT_NAME
HOLD = ("BTC", "ETH")
MAX_ETH = 0.25                         # live_gate.MAX_ETH_SHARE
SIGNAL_VALID_MS = 36 * 3_600_000       # lab.paper.families.SIGNAL_VALID_MS
RESULTS = Path(__file__).resolve().parents[2] / "results"
QUOTES_CSV = RESULTS / "smallaccount_s2_quotes.csv"
LAMPORTS = 1_000_000_000
BASE_FEE_L = 5_000
SWAP_UNITS = 250_000                   # a Jupiter swap's compute limit as live_exec sets it (1.2 x used + 10,000)
DEFAULT_FEE_L = BASE_FEE_L + 100_000 + 5_000   # what the other books pay: S1's 0.0001 SOL priority and the Sender tip


# What the owner saves to arm the book (docs/ONCHAIN-STAGE2.md, section 10): /etc/pythia/onchain-live-ack and the
# lines of /etc/pythia/onchain-live.env, without Sender (its tip and the paid plan are not needed here). With
# limits=wallet the four max_* lines do not apply (live_gate.Ack.cap); they are there within the alpha maxima.
ACK = """mode=alpha
books=onchain_longterm
mints=SOL,USDC,BTC,ETH
book_usd=45
max_total_usd=100
max_trade_usd=25
max_daily_loss_usd=25
max_convert_usd=100
limits=wallet
expires=2027-01-20
on_kill=hold
I accept that I can lose all of it
"""
ENV = """PYTHIA_ONCHAIN_LIVE=1
PYTHIA_ONCHAIN_KEYPAIR=/etc/pythia/onchain-keypair.json
PYTHIA_ONCHAIN_RPC=https://api.mainnet-beta.solana.com
"""


def rule(P) -> np.ndarray:
    """(T, N) tsmom1's weights known at each close: S1's tsmom_top20 on 1 coin, as S2 ran it."""
    from ..experiments import smallaccount as s1
    return s1.ffill(s1.candidate(P, "tsmom_top20", 1))


def weights_at(P, t: int, W: np.ndarray | None = None) -> tuple[dict[str, float], dict[str, float]]:
    """(the book's weights at the close t, the weight left in USDC by coin): tsmom1's weight of the day's
    coin, only BTC or ETH, ETH at most MAX_ETH."""
    from ..experiments import fam_common as fc
    W = rule(P) if W is None else W
    out, dropped = {}, {}
    for j in np.flatnonzero(np.nan_to_num(W[t]) > 0):
        if "~" in P.names[j]:
            continue
        c, w = fc.base_of(P.names[j]), float(W[t, j])
        keep = min(w, MAX_ETH) if c == "ETH" else w if c in HOLD else 0.0
        if round(keep, 6) > 0:
            out[c] = out.get(c, 0.0) + round(keep, 6)
        if w - keep > 1e-6:
            dropped[c] = round(w - keep, 6)
    return out, dropped


def signal(P, t: int, now_us: int) -> dict:
    """The targets after the close t, in the format of the lab's signals."""
    w, dropped = weights_at(P, t)
    return {
        "strategy": NAME,
        "variant": B.LT_VARIANT,
        "as_of_ms": int(P.days[t]) // 1000,
        "generated_ms": now_us // 1000,
        "valid_until_ms": now_us // 1000 + SIGNAL_VALID_MS,
        "quote": "USD",
        "weights": w,
        "regime_on": bool(P.btc_on[t]),
        "evidence": {"report": NAME, "missing": True, "experimental": True, "explicit_only": True,
                     "caveat": "S2's tsmom1 (passed its bar, not convincingly); forward evidence only"},
        "autopilot_only": True,
        "experimental": True,
        "universe": list(HOLD),
        "no_history": [],
        "dropped": sorted(dropped),
        "dropped_weight": round(sum(dropped.values()), 6),
        "lab_exposure": round(sum(w.values()), 6),
        "cadence": "daily",
    }


# ---------------------------------------------------------------- the cost per swap on the recorded quotes

def cost_rows(quotes: Path = QUOTES_CSV, sol_usd: float = 100.0, coins=HOLD, units: int = SWAP_UNITS) -> list[dict]:
    """Per coin and size of S2's quote ladder: the route's half round trip, the network fee of the cheapest path
    (base fee plus fees.cheap_price at its floor and at its cap) and of the other books' path (0.0001 SOL priority
    plus the Sender tip), all in bps of the swap."""
    floor_l = F.cheap_price([], units, 1)[1]
    out = []
    try:
        with quotes.open(newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
    except OSError:
        return out
    for r in rows:
        c = r.get("symbol") or r.get("coin")
        if c not in coins:
            continue
        usd, half = float(r["usd"]), float(r["half_rt_bps"])
        fee = lambda lam: lam / LAMPORTS * sol_usd / usd * 1e4
        out.append({"coin": c, "usd": usd, "route_bps": round(half, 2),
                    "cheap_bps": round(max(half, 0.0) + fee(BASE_FEE_L + floor_l), 2),
                    "cheap_cap_bps": round(max(half, 0.0) + fee(BASE_FEE_L + F.CHEAP_MAX_PRIORITY_L), 2),
                    "default_bps": round(max(half, 0.0) + fee(DEFAULT_FEE_L), 2),
                    "cheap_usd": round((BASE_FEE_L + F.CHEAP_MAX_PRIORITY_L) / LAMPORTS * sol_usd, 5),
                    "default_usd": round(DEFAULT_FEE_L / LAMPORTS * sol_usd, 5)})
    return out


# ---------------------------------------------------------------- the book's own rules over the history

def simulate(P, t0: int, t1: int, usd: float = 50.0, band: bool = True, fee_l: int = BASE_FEE_L + F.CHEAP_MAX_PRIORITY_L,
             W: np.ndarray | None = None, venue=None) -> dict:
    """The book from the close of t0 (all USDC, the SOL reserve bought) to the close of t1 with its own rules:
    the targets above, book.plan with the band (band False: S1's 5 USDC minimum instead), every order cut by
    book.pieces at the split share of the wallet, each piece paying S1's recorded half round trip at its size
    plus `fee_l` lamports at the day's SOL price; the reserve is marked at SOL's close, never traded."""
    from ..experiments import smallaccount as s1
    spec = B.BOOKS[NAME]
    W = rule(P) if W is None else W
    venue = venue or s1.venues()["jupiter"]
    cols = {c: P.col(f"{c}USDT") for c in (*HOLD, "SOL")}
    px = lambda c, t: float(P.px[t, cols[c]]) if np.isfinite(P.px[t, cols[c]]) else None
    reserve = spec["reserve_sol"]
    st = {"usdc": usd - reserve * (px("SOL", t0) or 0.0), "units": {}, "marks": {}}
    costs, orders, eq = usd - st["usdc"] - reserve * (px("SOL", t0) or 0.0), 0, []

    def swap(c: str, amount: float, sol: float) -> float:
        return amount * max(venue.half_rt_bps(c, amount), 0.0) / 1e4 + fee_l / LAMPORTS * sol

    for t in range(t0, t1 + 1):
        st["marks"].update({c: p for c in HOLD if (p := px(c, t))})
        sol = px("SOL", t) or 0.0
        trade_eq = st["usdc"] + sum(u * st["marks"].get(c, 0.0) for c, u in st["units"].items())
        wallet = trade_eq + reserve * sol
        tgt, _ = weights_at(P, t, W)
        tgt = {c: w for c, w in tgt.items() if c in st["marks"]}
        least = B.min_trade(NAME, trade_eq) if band else s1.JUP_MIN_TRADE_USD
        sells, buys = B.plan(st, tgt, trade_eq, least)
        for c, units in sells:
            for part in B.pieces(units * st["marks"][c], spec["split"] * wallet):
                cost = swap(c, part, sol)
                st["units"][c] = st["units"].get(c, 0.0) - part / st["marks"][c]
                st["usdc"] += part - cost
                costs, orders = costs + cost, orders + 1
            if st["units"].get(c, 0.0) * st["marks"][c] < B.DUST or c not in tgt:
                st["usdc"] += st["units"].pop(c, 0.0) * st["marks"][c]
        need = sum(x for _, x in buys)
        scale = min(1.0, st["usdc"] / need) if need > 0 else 1.0
        for c, amount in buys:
            amount = min(amount * scale, st["usdc"])
            if amount < least:
                continue
            for part in B.pieces(amount, spec["split"] * wallet):
                cost = swap(c, part, sol)
                st["usdc"] -= part
                st["units"][c] = st["units"].get(c, 0.0) + (part - cost) / st["marks"][c]
                costs, orders = costs + cost, orders + 1
        eq.append(st["usdc"] + sum(u * st["marks"].get(c, 0.0) for c, u in st["units"].items()) + reserve * sol)
    return {"equity": np.array(eq), "costs": costs, "orders": orders}


def backtest(P, usd: float = 50.0) -> list[dict]:
    """The book, the book with the other books' fee, the book without its band, and BTC held, in and out of
    S1's windows (lab.experiments.smallaccount.windows)."""
    from ..experiments import fam_common as fc
    from ..experiments import smallaccount as s1
    W = rule(P)
    venue = s1.venues()["jupiter"]
    out = []
    for win, (t0, t1) in s1.windows(P).items():
        btc = P.px[t0:t1 + 1, P.btc]
        runs = {"onchain_longterm": simulate(P, t0, t1, usd, W=W, venue=venue),
                "with the default fee": simulate(P, t0, t1, usd, fee_l=DEFAULT_FEE_L, W=W, venue=venue),
                "without the band (5 USDC)": simulate(P, t0, t1, usd, band=False, W=W, venue=venue),
                "btc_hold": {"equity": usd * btc / btc[0], "costs": 0.0, "orders": 1}}
        for k, r in runs.items():
            e = r["equity"]
            p = fc.perf(np.r_[e[0] / usd - 1, e[1:] / e[:-1] - 1])
            years = len(e) / 365
            gain = e[-1] - usd + r["costs"]
            out.append({"window": win, "run": k, "cagr": round(p["cagr"] * 100, 1), "max_dd": round(p["max_dd"] * 100, 1),
                        "sharpe": round(p["sharpe"], 2), "orders_yr": round(r["orders"] / years, 1),
                        "costs_usd_yr": round(r["costs"] / years, 2),
                        "costs_share": round(r["costs"] / gain * 100, 1) if gain > 0 else None})
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--costs", action="store_true")
    ap.add_argument("--backtest", action="store_true", help="the book's own rules over S1's windows (heavy lock)")
    ap.add_argument("--sol-usd", type=float, default=100.0)
    a = ap.parse_args(argv)
    if a.costs:
        for r in cost_rows(sol_usd=a.sol_usd):
            print(json.dumps(r))
        return 0
    from ..experiments import fam_common as fc
    from ..paper.tsmom import save_signal
    from .jupiter import Jupiter, QuoteError, default_fetch
    if a.backtest:
        for r in backtest(fc.load_panel()):
            print(json.dumps(r))
        return 0
    now_us = time.time_ns() // 1000
    yesterday = (now_us // fc.DAY_US - 1) * fc.DAY_US
    P = fc.load_panel()
    if P.days[-1] < yesterday:
        ends = f"{datetime.fromtimestamp(P.days[-1] / 1e6, timezone.utc):%Y-%m-%d}"
        if not a.dry_run:
            print(f"{NAME}: history ends {ends}, yesterday is missing; no new targets", file=sys.stderr)
            return 1
        t = P.T - 1
    else:
        t = int(np.flatnonzero(P.days == yesterday)[0])
    sig = signal(P, t, now_us)
    print(f"{NAME}: targets {json.dumps(sig['weights'])}, exposure {sig['lab_exposure']:.4f}"
          + (f", in USDC instead: {', '.join(sig['dropped'])}" if sig["dropped"] else ""))
    if a.dry_run:
        return 0
    save_signal(NAME, sig, now_us)
    client = Jupiter(fetch=default_fetch())
    try:
        row = B.step(client, root=B.WRITE_ROOT, probes=False, name=NAME)
    except QuoteError as e:
        print(f"{NAME}: {e}", file=sys.stderr)
        return 1
    print(f"{NAME}: {json.dumps(row)} ({client.calls} API calls)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
