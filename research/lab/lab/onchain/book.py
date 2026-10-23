"""EXPERIMENT, paper only: breakout_top10_live's target weights held in a Solana wallet, filled through Jupiter quotes.

The live twin the Kraken live test trades (lab.paper.live_copy writes
<data>/signals/breakout_top10_live/latest.json after paper-families) is mirrored
on a 1,000 USDC paper account: every daily run marks the account at Jupiter's
prices, rebalances it to the signal's weights through real quotes (sales first,
then buys out of the USDC they free; a change under MIN_TRADE USDC is left),
journals the day like the other paper books and writes the cost report. A coin
without a mint in lab.onchain.mints stays cash and is named in the report. A
stale or missing signal changes nothing: the account holds and is marked.

  python -m lab.onchain.book              daily: mark, rebalance, journal, probes, report
  python -m lab.onchain.book --mark       hourly: mark only (state.json, marks.csv)
  python -m lab.onchain.book --dry-run    quotes and the plan, writes nothing
  python -m lab.onchain.book --no-probes  the daily run without the cost probes

<data>/paper/onchain_breakout_top10_live/
  journal.csv   one row per day. `equity` is on the 10,000 basis every lab book
                starts from (the forward report and the app's Lab page assume
                it), `equity_usdc` the account itself: its coins marked at
                Jupiter's price. paper_cost_bps is what the rebalance's swaps cost
                (each half its round trip plus the network fees, lab.onchain.paper),
                model_cost_bps the backtest's 15 bps per unit of turnover,
                kraken_cost_bps the same trades at Kraken's taker fee plus its
                measured half spread
  state.json    USDC, coin units, marks, the last signal
  trades.csv    every fill with its quote
  marks.csv     the hourly marks
  probes.csv    each day a PROBE_USDC round trip USDC -> coin -> USDC per listed
                coin, so costs are seen while the book sits in cash

reports/onchain/latest.md and .json: on-chain against Kraken per rebalance and
per coin. Nothing here signs, sends or holds a key.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from .. import report
from ..data import ROOT, WRITE_ROOT
from . import mints as M
from .jupiter import Jupiter, QuoteError
from .paper import Fill, PaperExecutor

SIGNAL = "breakout_top10_live"
NAME = f"onchain_{SIGNAL}"
REPORT = "onchain"
START_USDC = 1_000.0
INDEX = 10_000.0                # START_EQUITY of every lab paper book
MIN_TRADE = 5.0                 # USDC; a smaller change is left (a swap costs about a cent to land)
DUST = 0.05                     # USDC; a remainder this small is not worth a swap
MODEL_COST = 0.0015             # the backtest's cost per unit of turnover (lab.experiments.tsmom.COST)
KRAKEN_TAKER_BPS = 40.0         # Kraken Pro spot, lowest tier (config/costs.json)
KRAKEN_HALF_DEFAULT = 25.0      # config/costs.json's Kraken half spread for a coin it has not measured
PROBE_USDC = 100.0
USDC_BAND = (0.98, 1.02)        # Jupiter's USD price of USDC outside it: no mark (a glitch or a depeg)
VARIANT = ("EXPERIMENT, paper only · breakout_top10_live's weights in a Solana wallet, Jupiter quotes, "
           "1,000 USDC (journal equity on the 10,000 basis)")
JOURNAL_COLS = ["date", "equity", "equity_usdc", "gross_ret_pct", "paper_cost_bps", "model_cost_bps",
                "kraken_cost_bps", "turnover", "exposure", "held", "swaps", "fees_usdc", "signal", "weights"]
TRADE_COLS = ["ts", "side", "coin", "usdc", "units", "fee_usdc", "cost_bps", "mid_cost_bps", "kraken_bps", "price_impact_pct",
              "route_fee_bps", "route", "in_amount", "out_amount"]


def _now_ms() -> int:
    return int(time.time() * 1000)


def _day(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d")


def book_dir(root: Path | None = None) -> Path:
    return (WRITE_ROOT if root is None else root) / "paper" / NAME


def new_state(now_ms: int) -> dict:
    return {"variant": VARIANT, "started": datetime.fromtimestamp(now_ms / 1000, timezone.utc).isoformat(
        timespec="seconds"), "equity": INDEX, "equity_usdc": START_USDC,
        "usdc": START_USDC, "units": {}, "marks": {}, "journal_equity_usdc": START_USDC, "signal": None}


def load_state(d: Path) -> dict | None:
    try:
        return json.loads((d / "state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def save_state(d: Path, st: dict) -> None:
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / "state.json.tmp"
    tmp.write_text(json.dumps(st, indent=2), encoding="utf-8")
    tmp.replace(d / "state.json")


def _append(path: Path, cols: list[str], rows: list[dict]) -> None:
    if not rows:
        return
    new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as fh:
        wr = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        if new:
            wr.writeheader()
        wr.writerows(rows)


def read_csv(path: Path) -> list[dict]:
    try:
        with path.open(newline="", encoding="utf-8") as fh:
            return list(csv.DictReader(fh))
    except OSError:
        return []


# ---------------------------------------------------------------- signal and marks

def read_signal(root: Path, now_ms: int, strategy: str = SIGNAL) -> tuple[dict | None, str]:
    """The book's signal when it is fresh, else None and why."""
    try:
        sig = json.loads((root / "signals" / strategy / "latest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return None, f"no readable signal ({type(e).__name__})"
    if sig.get("strategy") != strategy:
        return None, "the signal file names another strategy"
    if int(sig.get("valid_until_ms") or 0) < now_ms:
        return None, "the signal is stale"
    return sig, "fresh"


def split_targets(weights: dict) -> tuple[dict[str, float], dict[str, float]]:
    """Signal weights to (coins with a mint, coins without): the second stay cash."""
    tgt, dropped = {}, {}
    for c, w in (weights or {}).items():
        try:
            w = float(w)
        except (TypeError, ValueError):
            continue
        if w <= 0:
            continue
        (tgt if c in M.COINS else dropped)[c] = w
    total = sum(tgt.values())
    if total > 1:          # a long-only book never holds more than the account
        tgt = {c: w / total for c, w in tgt.items()}
    return tgt, dropped


def mids(prices: dict[str, float]) -> dict[str, float]:
    """Jupiter's USD prices to prices in USDC by coin; none when USDC's own price is off its peg,
    since it divides every mark and a broken one would write a false equity into the journal."""
    u = prices.get(M.USDC.mint)
    if not u or not USDC_BAND[0] <= u <= USDC_BAND[1]:
        return {}
    return {c: prices[m.mint] / u for c, m in M.COINS.items() if prices.get(m.mint)}


def mark(st: dict, mid: dict[str, float]) -> float:
    """Equity in USDC at the mid; a held coin without a price keeps its last mark."""
    for c in st["units"]:
        if c in mid:
            st["marks"][c] = mid[c]
    return st["usdc"] + sum(u * st["marks"].get(c, 0.0) for c, u in st["units"].items())


# ---------------------------------------------------------------- rebalance

def plan(st: dict, tgt: dict[str, float], equity: float, min_trade: float = MIN_TRADE
         ) -> tuple[list[tuple[str, float]], list[tuple[str, float]]]:
    """(sales as (coin, units), buys as (coin, USDC)) that bring the account to `tgt`.
    A coin leaving the book is sold whole; otherwise a change under min_trade is left."""
    sells, buys = [], []
    for c in sorted(set(st["units"]) | set(tgt)):
        units = st["units"].get(c, 0.0)
        px = st["marks"].get(c, 0.0)
        have = units * px
        want = tgt.get(c, 0.0) * equity
        if c not in tgt:
            if units > 0 and have >= DUST:
                sells.append((c, units))
        elif want - have <= -min_trade and px > 0:
            sells.append((c, units * min((have - want) / have, 1.0)))
        elif want - have >= min_trade:
            buys.append((c, want - have))
    return sells, buys


def rebalance(st: dict, tgt: dict[str, float], ex: PaperExecutor, equity: float,
              min_trade: float = MIN_TRADE) -> tuple[list[Fill], list[str]]:
    """Sales first, then buys out of the USDC on hand (scaled down together when short).
    A coin whose quote fails is left as it is and named in the errors."""
    sells, buys = plan(st, tgt, equity, min_trade)
    fills, errors = [], []
    for c, units in sells:
        try:
            f = ex.sell(c, units)
        except (QuoteError, KeyError) as e:
            errors.append(f"sell {c}: {e}")
            continue
        st["units"][c] = st["units"].get(c, 0.0) - f.units
        if st["units"][c] * st["marks"].get(c, 0.0) < DUST or c not in tgt:
            st["units"].pop(c)
        st["usdc"] += f.usdc
        fills.append(f)
    need = sum(x for _, x in buys)
    scale = min(1.0, st["usdc"] / need) if need > 0 else 1.0
    for c, usdc in buys:
        usdc = min(usdc * scale, st["usdc"])
        if usdc < min_trade:
            continue
        try:
            f = ex.buy(c, usdc)
        except (QuoteError, KeyError) as e:
            errors.append(f"buy {c}: {e}")
            continue
        st["usdc"] -= f.usdc
        st["units"][c] = st["units"].get(c, 0.0) + f.units
        fills.append(f)
    return fills, errors


# ---------------------------------------------------------------- Kraken's side

def kraken_half(costs: dict | None) -> dict[str, float]:
    """Kraken's measured half spread per coin (reports/costs, lab experiment costs)."""
    out = {}
    for c, v in ((costs or {}).get("measured") or {}).get("kraken", {}).items():
        try:
            out[c] = float(v["halfSpreadBps"])
        except (KeyError, TypeError, ValueError):
            continue
    return out


def kraken_bps(coin: str, half: dict[str, float]) -> float:
    """One Kraken taker fill: the fee plus the half spread, measured where the recorder has the coin."""
    return KRAKEN_TAKER_BPS + half.get(coin, KRAKEN_HALF_DEFAULT)


def kraken_paper_fills(state: dict | None) -> dict:
    """The engine's own paper fills on the Kraken route (autopilot state.json): their realised
    slippage against the mid, to which the taker fee comes on top."""
    slips = [float(o["realisedSlippageBps"]) for o in (state or {}).get("orders") or []
             if o.get("route") == "paper" and o.get("venue") == "crypto" and o.get("status") == "filled"
             and isinstance(o.get("realisedSlippageBps"), (int, float))]
    if not slips:
        return {"fills": 0}
    med = statistics.median(slips)
    return {"fills": len(slips), "slippage_median_bps": round(med, 2),
            "slippage_mean_bps": round(statistics.fmean(slips), 2),
            "all_in_median_bps": round(med + KRAKEN_TAKER_BPS, 2)}


def _read_json(p: Path) -> dict | None:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------- one run

def probe(ex: PaperExecutor, half: dict[str, float], usdc: float = PROBE_USDC, now_ms: int = 0) -> list[dict]:
    """A round trip USDC -> coin -> USDC per listed coin, both swaps' network fees included."""
    rows = []
    for c in M.COINS:
        try:
            b = ex.buy(c, usdc)
            s = ex.sell(c, b.units)
        except (QuoteError, KeyError) as e:
            print(f"onchain: probe {c}: {e}", file=sys.stderr)
            continue
        rt = (1 - s.usdc / b.usdc) * 1e4 if b.usdc > 0 else None
        rows.append({"date": _day(now_ms), "coin": c, "usdc": round(b.usdc, 2),
                     "roundtrip_bps": None if rt is None else round(rt, 2),
                     "buy_cost_bps": None if b.cost_bps is None else round(b.cost_bps, 2),
                     "sell_cost_bps": None if s.cost_bps is None else round(s.cost_bps, 2),
                     "kraken_roundtrip_bps": round(2 * kraken_bps(c, half), 2),
                     "fees_usdc": round(b.fee_usdc + s.fee_usdc, 5),
                     "route": "+".join(b.quote.get("labels") or [])})
    return rows


def trade_row(f: Fill, half: dict[str, float], now_ms: int) -> dict:
    q = f.quote
    return {"ts": now_ms, "side": f.side, "coin": f.coin, "usdc": round(f.usdc, 4), "units": f.units,
            "fee_usdc": round(f.fee_usdc, 5), "cost_bps": None if f.cost_bps is None else round(f.cost_bps, 2),
            "mid_cost_bps": None if f.mid_cost_bps is None else round(f.mid_cost_bps, 2),
            "kraken_bps": round(kraken_bps(f.coin, half), 2), "price_impact_pct": q.get("price_impact_pct"),
            "route_fee_bps": q.get("route_fee_bps"), "route": "+".join(q.get("labels") or []),
            "in_amount": q.get("in_amount"), "out_amount": q.get("out_amount")}


def step(client: Jupiter, now_ms: int | None = None, root: Path | None = None, write_root: Path | None = None,
         probes: bool = True, dry_run: bool = False) -> dict:
    """The daily run. Returns the journal row (or what it would be)."""
    now_ms = _now_ms() if now_ms is None else now_ms
    root = ROOT if root is None else root
    d = book_dir(write_root)
    st = load_state(d) or new_state(now_ms)
    journal = read_csv(d / "journal.csv")
    today = _day(now_ms)
    prices = client.prices([M.USDC.mint, *(m.mint for m in M.COINS.values())])
    mid = mids(prices)
    if not mid:
        raise QuoteError("no USDC price from Jupiter within its peg, nothing marked")
    before = mark(st, mid)
    if journal and journal[-1].get("date") == today:
        print(f"onchain: {NAME} already journaled {today}; marked only", file=sys.stderr)
        if not dry_run:
            st.update(equity=before * INDEX / START_USDC, equity_usdc=before, last_mark_ms=now_ms)
            save_state(d, st)
        return {}
    sig, why = read_signal(root, now_ms)
    tgt, dropped = split_targets(sig["weights"] if sig else {})
    half = kraken_half(_read_json(report.REPORTS / "costs" / "latest.json"))
    ex = PaperExecutor(client, prices)
    fills, errors = [], []
    if sig is None:
        print(f"onchain: {why}; the account holds", file=sys.stderr)
    elif dry_run:
        sells, buys = plan(st, tgt, before)
        print(json.dumps({"equity_usdc": round(before, 2), "targets": tgt, "dropped": dropped,
                          "sells": sells, "buys": buys}))
    else:
        fills, errors = rebalance(st, tgt, ex, before)
    after = mark(st, mid)
    traded = sum(f.usdc for f in fills)
    paid = sum(f.usdc * f.cost_bps / 1e4 if f.cost_bps is not None else f.fee_usdc for f in fills)
    kraken = sum(f.usdc * kraken_bps(f.coin, half) / 1e4 for f in fills)
    prev = float(st.get("journal_equity_usdc") or START_USDC)
    row = {"date": today, "equity": round(after * INDEX / START_USDC, 2), "equity_usdc": round(after, 4),
           "gross_ret_pct": round((before / prev - 1) * 100, 4) if journal else 0,
           "paper_cost_bps": round(paid / before * 1e4, 2) if before > 0 else 0.0,
           "model_cost_bps": round(traded / before * MODEL_COST * 1e4, 2) if before > 0 else 0.0,
           "kraken_cost_bps": round(kraken / before * 1e4, 2) if before > 0 else 0.0,
           "turnover": round(traded / before, 4) if before > 0 else 0.0,
           "exposure": round(1 - st["usdc"] / after, 4) if after > 0 else 0.0,
           "held": len(st["units"]), "swaps": len(fills), "fees_usdc": round(sum(f.fee_usdc for f in fills), 5),
           "signal": _day(int(sig["as_of_ms"])) if sig and sig.get("as_of_ms") else why,
           "weights": json.dumps({c: round(u * st["marks"].get(c, 0.0) / after, 4)
                                  for c, u in sorted(st["units"].items())} if after > 0 else {})}
    probe_rows = (probe(PaperExecutor(client, prices, roundtrip=False), half, now_ms=now_ms)
                  if probes and not dry_run else [])
    if dry_run:
        print(json.dumps(row))
        return row
    d.mkdir(parents=True, exist_ok=True)
    _append(d / "trades.csv", TRADE_COLS, [trade_row(f, half, now_ms) for f in fills])
    _append(d / "journal.csv", JOURNAL_COLS, [row])
    _append(d / "probes.csv", list(probe_rows[0]) if probe_rows else [], probe_rows)
    st.update(equity=after * INDEX / START_USDC, equity_usdc=after, journal_equity_usdc=after, last_mark_ms=now_ms,
              signal={"as_of_ms": sig.get("as_of_ms") if sig else None, "status": why, "targets": tgt,
                      "dropped": dropped}, errors=errors)
    save_state(d, st)
    write_report(d, st, half, _read_json(root / "autopilot" / "state.json"), now_ms)
    return row


def mark_only(client: Jupiter, now_ms: int | None = None, write_root: Path | None = None) -> float | None:
    """The hourly mark: equity at Jupiter's prices into state.json and marks.csv; no trade, no journal row."""
    now_ms = _now_ms() if now_ms is None else now_ms
    d = book_dir(write_root)
    st = load_state(d)
    if st is None:
        print(f"onchain: {NAME} has not started yet, nothing to mark", file=sys.stderr)
        return None
    mid = mids(client.prices([M.USDC.mint, *(M.COINS[c].mint for c in st["units"] if c in M.COINS)]))
    if not mid and st["units"]:
        raise QuoteError("no USDC price from Jupiter within its peg, nothing marked")
    eq = mark(st, mid)
    st.update(equity=eq * INDEX / START_USDC, equity_usdc=eq, last_mark_ms=now_ms)
    save_state(d, st)
    _append(d / "marks.csv", ["ts", "equity_usdc", "held"], [{"ts": now_ms, "equity_usdc": round(eq, 4),
                                                              "held": len(st["units"])}])
    return eq


# ---------------------------------------------------------------- report

def _num(r: dict, k: str) -> float | None:
    try:
        return float(r[k])
    except (KeyError, TypeError, ValueError):
        return None


def summarize(journal: list[dict], trades: list[dict], probes: list[dict], engine: dict) -> dict:
    """On-chain against Kraken: per rebalance (bps of equity), per unit traded, per coin from the probes."""
    reb = [r for r in journal if (_num(r, "turnover") or 0) > 0]
    traded = sum(_num(t, "usdc") or 0 for t in trades)
    onchain_usdc = sum((_num(t, "usdc") or 0) * (_num(t, "cost_bps") or 0) / 1e4 for t in trades)
    kraken_usdc = sum((_num(t, "usdc") or 0) * (_num(t, "kraken_bps") or 0) / 1e4 for t in trades)
    last = {}
    for p in probes:                                   # the latest probe per coin
        last[p["coin"]] = p
    per_coin = []
    for c, p in sorted(last.items()):
        rt, k = _num(p, "roundtrip_bps"), _num(p, "kraken_roundtrip_bps")
        per_coin.append({"coin": c, "date": p.get("date"), "onchain_oneway_bps": None if rt is None else rt / 2,
                         "kraken_oneway_bps": None if k is None else k / 2, "route": p.get("route")})
    cheaper = [r for r in per_coin if r["onchain_oneway_bps"] is not None and r["kraken_oneway_bps"] is not None
               and r["onchain_oneway_bps"] < r["kraken_oneway_bps"]]
    return {
        "rebalances": len(reb),
        "per_rebalance": [{"date": r["date"], "turnover": _num(r, "turnover"), "onchain_bps": _num(r, "paper_cost_bps"),
                           "kraken_bps": _num(r, "kraken_cost_bps"), "swaps": _num(r, "swaps")} for r in reb[-20:]],
        "traded_usdc": round(traded, 2),
        "onchain_bps_per_turnover": round(onchain_usdc / traded * 1e4, 2) if traded else None,
        "kraken_bps_per_turnover": round(kraken_usdc / traded * 1e4, 2) if traded else None,
        "probes": per_coin, "cheaper_on_chain": [r["coin"] for r in cheaper],
        "engine_kraken_paper": engine,
    }


def write_report(d: Path, st: dict, half: dict[str, float], engine_state: dict | None, now_ms: int) -> dict:
    journal, trades, probes = read_csv(d / "journal.csv"), read_csv(d / "trades.csv"), read_csv(d / "probes.csv")
    s = summarize(journal, trades, probes, kraken_paper_fills(engine_state))
    eq = float(st.get("equity_usdc") or START_USDC)
    sig = st.get("signal") or {}
    dropped = sig.get("dropped") or {}
    per = s["onchain_bps_per_turnover"]
    kr = s["kraken_bps_per_turnover"]
    pc = [r for r in s["probes"] if r["onchain_oneway_bps"] is not None]
    med_on = statistics.median(r["onchain_oneway_bps"] for r in pc) if pc else None
    med_kr = statistics.median(r["kraken_oneway_bps"] for r in pc) if pc else None
    if per is not None and kr:
        head = (f"On chain a rebalance cost {per:.1f} bps per unit traded against {kr:.1f} at Kraken "
                f"({s['rebalances']} rebalances).")
    elif med_on is not None:
        head = (f"No rebalance on chain yet; a {PROBE_USDC:.0f} USDC swap costs a median {med_on:.1f} bps one way "
                f"against {med_kr:.1f} at Kraken.")
    else:
        head = "No rebalance and no probe yet."
    md = [f"# On-chain paper book ({NAME}): Solana through Jupiter against Kraken\n",
          f"EXPERIMENT, paper only. {head}\n",
          f"Account {eq:,.2f} USDC (started with {START_USDC:,.0f}), {len(st['units'])} coins held, "
          f"signal {sig.get('status', 'not read')}. Targets on chain: "
          f"{', '.join(f'{c} {w:.1%}' for c, w in (sig.get('targets') or {}).items()) or 'none'}. "
          f"Without an SPL version, held as cash: {', '.join(f'{c} {w:.1%}' for c, w in dropped.items()) or 'none'}.\n",
          "## Per rebalance (bps of equity)\n",
          report.table(s["per_rebalance"], ["date", "turnover", "onchain_bps", "kraken_bps", "swaps"])
          if s["per_rebalance"] else "None yet.\n",
          f"\nPer unit traded: on chain {per if per is not None else 'n/a'} bps, Kraken "
          f"{kr if kr is not None else 'n/a'} bps (taker {KRAKEN_TAKER_BPS:.0f} plus the measured half spread).\n",
          f"\n## Per coin, a {PROBE_USDC:.0f} USDC round trip halved (bps, network and priority fee included)\n",
          report.table(s["probes"], ["coin", "date", "onchain_oneway_bps", "kraken_oneway_bps", "route"])
          if s["probes"] else "No probe yet.\n"]
    e = s["engine_kraken_paper"]
    if e.get("fills"):
        md.append(f"\nThe engine's own Kraken paper fills: {e['fills']}, median slippage {e['slippage_median_bps']} "
                  f"bps against the mid, {e['all_in_median_bps']} bps with the taker fee.\n")
    md.append("\nHow it is measured: docs/ONCHAIN.md. Kraken's half spreads from reports/costs.\n")
    status = "watch" if st.get("errors") else "ok"
    data = {**report.feed_header("On-chain paper book", status, head, updated_ms=now_ms, items=[
        {"label": "Account", "value": f"{eq:,.2f} USDC"},
        {"label": "On chain per unit traded", "value": None if per is None else f"{per:.1f} bps"},
        {"label": "Kraken per unit traded", "value": None if kr is None else f"{kr:.1f} bps"},
        {"label": "Probe median one way", "value": None if med_on is None else f"{med_on:.1f} bps"}]),
        "verdict": head, "book": NAME, "equity_usdc": eq, "summary": s, "errors": st.get("errors") or []}
    report.write(REPORT, "\n".join(md), data)
    return data


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--mark", action="store_true", help="hourly mark only")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-probes", action="store_true")
    a = ap.parse_args(argv)
    client = Jupiter()
    try:
        if a.mark:
            eq = mark_only(client)
            print(f"onchain: marked {eq:,.2f} USDC" if eq is not None else "onchain: nothing to mark")
        else:
            row = step(client, probes=not a.no_probes, dry_run=a.dry_run)
            print(f"onchain: {json.dumps(row)} ({client.calls} API calls)")
    except QuoteError as e:
        print(f"onchain: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
