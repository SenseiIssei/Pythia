"""EXPERIMENTAL paper book of M4 reg7n at a 230 USD account on Hyperliquid, with the dry-run orders. No real money.

results/m4h.md (M4H2, pre-registered in results/m4h_prereg.md and m4h2_prereg.md) passed reg7n 10/10 at 230 USD,
1x, taker, on Hyperliquid's listed coins of the 100 most liquid perps, out of sample 2024-01 to 2026-06: Sharpe 1.79,
drawdown 20 %, every year positive. It is NOT confirmed (DSR 0.024 over 4,275 trials; the holdout is the one reg7n
was picked on, and the in-sample record of the refit depends on the day the panel was built), so this book runs
as an EXPERIMENT and writes no engine signal: nothing the engine, a live bot or a wallet reads.

Configuration: m4_perps' machinery (same panel, model reg7n, parameters, retrain rule, rank buffer 50 %, k 10,
n_liquid 100) with Hyperliquid in place of Kraken, at the account the study judged:

Every run (daily, after the nightly backfill):
  1. Hyperliquid's public metaAndAssetCtxs (no key): the listed coins (not delisted), mids, size decimals,
     impact prices and the current funding. Without it the run stops (exit 1, no row);
  2. the xs_daily panel and the model exactly like m4_perps (model cache m4_hl_small_reg7n.txt/.json);
  3. mark the paper account to Hyperliquid's mids and book Hyperliquid's own hourly funding of each held coin since
     the last run (public fundingHistory; the current rate x hours when that fails, journaled); a coin
     Hyperliquid no longer lists is closed at its last mark;
  4. the 100 most liquid Binance perps of the day as m4_ls.candidates picks them, THEN only the coins Hyperliquid
     lists (dropped_unlisted), ranked and buffered among those: 10 long, 10 short, entering at 5 % of the sizing
     equity (the account, at most 250 USD) each;
  5. the target in coin units goes through lab.paper.hl_dryrun (the hard limits: 250 USD, 2x gross, -20 % stop,
     the GO_FLAT switch in this book's folder, the 10 USD minimum, size decimals); its orders are filled on paper
     at the mid plus Hyperliquid's taker 4.5 bps and half the impact spread, and written to orders/<date>.json.

The journal's `equity` is the account as an index on 10,000 (the forward report's scale); `equity_usd` is the 230
USD account. The run fills at its run time (about 06:00 UTC), not at 01:00 as the study did; `entry_hour_utc` says.

  python -m lab.paper.m4_hl_small             one step, writes state, journal and the dry-run orders
  python -m lab.paper.m4_hl_small --dry-run   prints the decision and the orders; writes nothing but the lab cache

Cache (panel and model): $PYTHIA_CACHE, default <data>/lab-cache.
State: <data>/paper/m4_hl_small/state.json   Journal: <data>/paper/m4_hl_small/journal.csv
Orders: <data>/paper/m4_hl_small/orders/<date>.json   Switch: <data>/paper/m4_hl_small/GO_FLAT
"""

from __future__ import annotations

import csv
import json
import sys
import time
import urllib.request
from datetime import datetime, timezone

import polars as pl

from ..data import WRITE_ROOT
from ..experiments import xs_daily as xs
from . import hl_dryrun as hx
from . import m4_ls as m4
from . import m4_perps as mp
from .experimental import LABEL

NAME = "m4_hl_small"
CONFIG = {"model": "reg7n", "k": 10, "n_liquid": 100, "mode": "buffer", "hold": None, "exit_frac": 0.5}
VARIANT = (f"{LABEL} · M4 reg7n · 10/10 of the 100 most liquid perps listed on Hyperliquid · rank buffer 50 % · "
           "230 USD account, dry-run orders")
START_USD = 230.0
INDEX = 10_000.0                # the journal's equity scale, as every paper book's
TAKER = 4.5e-4                  # Hyperliquid's base taker
SLIP_CAP = 50e-4
DAY_US = xs.DAY_US
HOUR_MS = 3_600_000
DIR = WRITE_ROOT / "paper" / NAME
HL_INFO = "https://api.hyperliquid.xyz/info"

EVIDENCE = {
    "report": "m4h",
    "experimental": True,
    "oos_sharpe": 1.79,
    "oos_cagr": 0.636,
    "oos_max_dd": 0.200,
    "bootstrap_05": 0.97,
    "year_sharpes": {"2024": 2.00, "2025": 1.68, "2026 to 2026-06-28": 1.62},
    "late_sharpe": 1.80,
    "deflated": 0.024,
    "variants_tried": 4275,
    "why_failed": "DSR 0.024 over 4,275 trials: the holdout reg7n was picked on, a refit whose in-sample Sharpe "
                  "moves with the panel's build day (0.69 to 1.30)",
    "caveat": "fills at the run time (about 06:00 UTC), the study filled at 01:00; funding costs about 10 % a year",
}


# ---------------------------------------------------------------- Hyperliquid's public data

def post(body: dict):
    req = urllib.request.Request(HL_INFO, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def parse_ctxs(answer) -> dict[str, dict]:
    """{coin: {mid, dec, funding, half_spread}} of the perps Hyperliquid lists now (not delisted, with a mid).
    Raises ValueError on an answer that is not [meta, ctxs] or lists nothing."""
    if not (isinstance(answer, list) and len(answer) == 2 and isinstance(answer[0], dict)):
        raise ValueError(f"metaAndAssetCtxs answer: {str(answer)[:200]}")
    out: dict[str, dict] = {}
    for u, c in zip(answer[0].get("universe") or [], answer[1] or []):
        if u.get("isDelisted") or not isinstance(c, dict):
            continue
        try:
            mid = float(c.get("midPx") or c.get("markPx"))
        except (TypeError, ValueError):
            continue
        if not mid > 0:
            continue
        imp = c.get("impactPxs") or []
        try:
            half = (float(imp[1]) - float(imp[0])) / mid / 2 if len(imp) == 2 else SLIP_CAP
        except (TypeError, ValueError):
            half = SLIP_CAP
        out[u["name"]] = {"mid": mid, "dec": int(u.get("szDecimals", 0)), "funding": float(c.get("funding") or 0.0),
                          "half_spread": min(max(half, 0.0), SLIP_CAP)}
    if not out:
        raise ValueError("metaAndAssetCtxs lists no perp")
    return out


def hl_coin(perp: str, listed) -> str | None:
    """The Hyperliquid coin of a Binance perp: 1000PEPEUSDT -> kPEPE, BTCUSDT -> BTC (MATIC -> POL as m4_perps)."""
    base = perp[:-4] if perp.endswith("USDT") else perp
    cands = []
    if base.startswith("1000") and len(base) > 4:
        cands.append("k" + base[4:])
    cands += [base, mp.coin_of(perp)]
    return next((c for c in cands if c in listed), None)


def funding_since(coin: str, since_ms: int, now_ms: int, fetch=post) -> float | None:
    """The sum of Hyperliquid's hourly funding rates of a coin settled in (since, now], None when the call fails."""
    try:
        rows = fetch({"type": "fundingHistory", "coin": coin, "startTime": since_ms + 1, "endTime": now_ms})
        return float(sum(float(r["fundingRate"]) for r in rows if since_ms < int(r["time"]) <= now_ms))
    except Exception:  # noqa: BLE001 - fall back to the current rate
        return None


# ---------------------------------------------------------------- the book

def restrict(c: pl.DataFrame, ctx: dict) -> tuple[pl.DataFrame, list[str]]:
    """m4_ls.candidates' liquid set (best first) cut to the coins Hyperliquid lists, with a `coin` column; the
    perps dropped as unlisted. Two perps of one coin keep the more liquid one."""
    coins = [hl_coin(p, ctx) for p in c["perp"].to_list()]
    c = c.with_columns(coin=pl.Series(coins, dtype=pl.Utf8))
    dropped = sorted(p for p, x in zip(c["perp"].to_list(), coins) if x is None)
    listed = (c.filter(pl.col("coin").is_not_null()).sort("perp_adv28", descending=True)
              .unique("coin", keep="first", maintain_order=True).sort("score", descending=True))
    return listed, dropped


def mark(units: dict[str, float], prev_mid: dict[str, float], ctx: dict) -> tuple[float, dict, list[str]]:
    """(P&L in USD at today's mids, the positions still listed, the coins gone: closed at their last mark)."""
    pnl = sum(u * (ctx[c]["mid"] - prev_mid[c]) for c, u in units.items() if c in ctx and c in prev_mid)
    gone = sorted(c for c in units if c not in ctx)
    return pnl, {c: u for c, u in units.items() if c in ctx}, gone


def target_units(tgt: dict[str, float], perp_coin: dict[str, str], ctx: dict, equity: float) -> dict[str, float]:
    """Signed units per coin of the target weights (Binance perp -> fraction) on the sizing equity."""
    base = hx.sizing_equity(equity)
    out: dict[str, float] = {}
    for perp, w in tgt.items():
        c = perp_coin.get(perp)
        if c and c in ctx and w:
            out[c] = out.get(c, 0.0) + w * base / ctx[c]["mid"]
    return out


def fill(units: dict[str, float], orders: list[dict], ctx: dict) -> tuple[dict[str, float], float, float]:
    """The orders filled on paper at the mid: (positions, cost in USD (taker plus half the impact spread),
    traded notional)."""
    units = dict(units)
    cost = traded = 0.0
    for o in orders:
        q = float(o["size"]) * (1 if o["side"] == "buy" else -1)
        c = o["coin"]
        n = abs(q) * ctx[c]["mid"]
        cost += n * (TAKER + ctx[c]["half_spread"])
        traded += n
        u = units.get(c, 0.0) + q
        units[c] = u
        if abs(u) < 0.5 * 10 ** -ctx[c]["dec"]:
            units.pop(c)
    return units, cost, traded


def new_state() -> dict:
    return {"variant": VARIANT, "config": CONFIG, "started": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "start_usd": START_USD, "equity_usd": START_USD, "units": {}, "perp": {}, "mid": {}, "last_run_ms": None,
            "stopped": False}


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    t_start = time.time()
    dry = "--dry-run" in argv
    now_us = time.time_ns() // 1000
    now_ms = now_us // 1000
    decision_day = (now_us // DAY_US - 1) * DAY_US
    state_file = DIR / "state.json"
    st = json.loads(state_file.read_text()) if state_file.exists() else new_state()

    try:
        ctx = parse_ctxs(post({"type": "metaAndAssetCtxs"}))
    except Exception as e:  # noqa: BLE001 - no prices, no step
        print(f"Hyperliquid metaAndAssetCtxs unavailable ({type(e).__name__}: {e}); no step", file=sys.stderr)
        return 1

    E, info = m4.live_panel(decision_day)
    if E["day"].max() < decision_day:
        print(f"history ends {datetime.fromtimestamp(E['day'].max() / 1e6, timezone.utc):%Y-%m-%d}, "
              "yesterday is missing; not rebalancing on stale data", file=sys.stderr)
        return 1
    booster, meta = m4.model_for(E, decision_day, cfg=CONFIG, name=NAME)
    exch = m4.get(f"{m4.FAPI}/exchangeInfo")["symbols"]
    live = {s["symbol"] for s in exch if s.get("contractType") == "PERPETUAL" and s["status"] == "TRADING"
            and s.get("quoteAsset") == "USDT"}
    c = m4.candidates(E, booster, decision_day, live, cfg=CONFIG)
    for _ in range(mp.MAX_LAG_DAYS):
        if c.height >= mp.MIN_SCOREABLE:
            break
        decision_day -= DAY_US
        booster, meta = m4.model_for(E, decision_day, cfg=CONFIG, name=NAME)
        c = m4.candidates(E, booster, decision_day, live, cfg=CONFIG)
    listed, dropped = restrict(c, ctx)

    # 1 · mark to Hyperliquid's mids and book its funding since the last run
    units = {k: float(v) for k, v in st["units"].items()}
    equity = float(st["equity_usd"])
    funding, fallback = 0.0, []
    if st["last_run_ms"]:
        for coin, u in units.items():
            if coin not in ctx:
                continue
            rate = funding_since(coin, st["last_run_ms"], now_ms)
            if rate is None:
                rate = ctx[coin]["funding"] * round((now_ms - st["last_run_ms"]) / HOUR_MS)
                fallback.append(coin)
            funding += u * st["mid"].get(coin, ctx[coin]["mid"]) * rate          # a long pays a positive rate
    pnl, units, gone = mark(units, st["mid"], ctx)
    start_eq = equity
    equity += pnl - funding

    # 2 · today's target among the listed coins, through the dry-run executor
    perp_coin = dict(zip(listed["perp"].to_list(), listed["coin"].to_list())) | dict(st.get("perp", {}))
    coin_perp = {v: k for k, v in perp_coin.items()}
    w = {coin_perp[c]: u * ctx[c]["mid"] / equity for c, u in units.items() if c in coin_perp and equity > 0}
    tgt = m4.buffer_target(listed, w, cfg=CONFIG) if equity > 0 else {}
    want = target_units(tgt, perp_coin, ctx, equity)
    plan = hx.plan(units, want, {k: v["mid"] for k, v in ctx.items()}, {k: v["dec"] for k, v in ctx.items()},
                   equity, float(st["start_usd"]), flat=hx.flat_switch(DIR), stopped=bool(st.get("stopped")))
    held, cost, traded = fill(units, plan["orders"], ctx)
    equity -= cost
    gross_held = sum(u * ctx[c]["mid"] for c, u in held.items())
    long_x = sum(u * ctx[c]["mid"] for c, u in held.items() if u > 0) / equity if equity > 0 else 0.0
    short_x = -sum(u * ctx[c]["mid"] for c, u in held.items() if u < 0) / equity if equity > 0 else 0.0
    opened = {c: u for c, u in held.items() if c not in units}

    row = {
        "date": datetime.fromtimestamp(now_us / 1e6, timezone.utc).strftime("%Y-%m-%d"),
        "equity": round(equity / float(st["start_usd"]) * INDEX, 2),
        "equity_usd": round(equity, 4),
        "gross_ret_pct": round(pnl / start_eq * 100, 4) if start_eq else 0.0,
        "funding_pct": round(-funding / start_eq * 100, 4) if start_eq else 0.0,
        "paper_cost_bps": round(cost / start_eq * 1e4, 2) if start_eq else 0.0,
        "model_cost_bps": round(traded / start_eq * (TAKER + 1e-4) * 1e4, 2) if start_eq else 0.0,
        "turnover": round(traded / start_eq, 4) if start_eq else 0.0,
        "long_exposure": round(long_x, 4),
        "short_exposure": round(short_x, 4),
        "net_usd": round(gross_held, 2),
        "held": len(held),
        "orders": len(plan["orders"]),
        "orders_skipped": len(plan["skipped"]),
        "mode": plan["mode"],
        "entry_hour_utc": datetime.fromtimestamp(now_us / 1e6, timezone.utc).hour,
        "model_trained": datetime.fromtimestamp(meta["decision_day"] / 1e6, timezone.utc).strftime("%Y-%m-%d"),
        "funding_fresh": info["funding_fresh"],
        "longs": " ".join(sorted(c for c, u in opened.items() if u > 0)),
        "shorts": " ".join(sorted(c for c, u in opened.items() if u < 0)),
        "gone": " ".join(gone),
        "dropped_unlisted": " ".join(dropped),
        "listed_universe": listed.height,
        "funding_fallback": " ".join(fallback),
    }
    orders = {"date": row["date"], "dry_run": True, "sent": False, "variant": VARIANT, "equity_usd": round(equity, 4),
              "sizing_equity_usd": hx.sizing_equity(equity), **plan,
              "decision_day": datetime.fromtimestamp(decision_day / 1e6, timezone.utc).strftime("%Y-%m-%d"),
              "evidence": EVIDENCE}
    took = {"secs": round(time.time() - t_start), "peak_mb": round(m4.peak_mb())}
    if dry:
        print(json.dumps({"dry_run": True, "row": row, "orders": orders, "model": {k: v for k, v in meta.items()
                          if k != "features"}, "panel": info, "took": took}, indent=2))
        return 0

    DIR.mkdir(parents=True, exist_ok=True)
    journal = DIR / "journal.csv"
    new = not journal.exists()
    with journal.open("a", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=list(row))
        if new:
            wr.writeheader()
        wr.writerow(row)
    (DIR / "orders").mkdir(exist_ok=True)
    (DIR / "orders" / f"{row['date']}.json").write_text(json.dumps(orders, indent=2))
    st.update(equity_usd=equity, units=held, mid={c: ctx[c]["mid"] for c in held},
              perp={coin_perp[c]: c for c in held if c in coin_perp}, last_run_ms=now_ms, stopped=plan["stopped"])
    state_file.write_text(json.dumps(st, indent=2))
    print(json.dumps(row))
    print(json.dumps(took), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
