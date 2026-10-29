"""E1, shrunk after the review of 2026-10-27: a slippage and tip policy for the pump.fun bot's buys, from its own
fills and R1's realistic replay. PAPER ONLY: a rule written down, nothing live, no sizing or bot file touched.

    python -m lab.experiments.execution_e1              the live part: results/execution_e1.md (below the marker)
                                                        and reports/execution_e1/latest.json
    python -m lab.experiments.execution_e1 --replay     with R1's replay of P_pool0_wait at every pool buy limit
                                                        (heavy: run under the heavy lock)

Jupiter swaps cost about 2 bps already and pump.fun's pool fee cannot be cut, so the cost map and the rebalance
timing of the first brief were dropped; what is left to choose is how far a buy may run (the slippage limit) and
what a transaction pays to land (priority fee and Sender tip; a loose limit is what a sandwich lives on).

Live part (<data>/live/pumpfun_rt: measured.jsonl, orders.jsonl, ledger.csv):
  run       a pool buy's run past its quote: the tokens the order asked for over the tokens it got, less 1. The live
            bound fails a buy exactly when run > limit (the order accepts no fewer than its quote / (1 + limit);
            the pre-send check is the same test earlier, without the fee), so each limit's counterfactual is exact
            for the buys that filled: a buy with run > L would have failed and paid a failed buy's fee instead of
            its trade. The buys that failed with 6040 or ran away before the send fail under every tighter limit
            too; limits looser than the live one are not seen live (the replay covers them).
  picked    pre-set before looking: the limit with the best mean P&L per buy order whose missed good fills (trades
            with a positive P&L dropped) hold at most MISS_MAX of the winners' P&L and that is better than the live
            limit in both chronological halves; none: keep the live limit. Bootstrap interval of the difference.
  fee       the network fee each landed transaction paid (base and priority) against its send to landing, on the
            fills since the dynamic priority fee (a fee under FIXED_FEE_L): does paying more land sooner? And the
            fee's share of a round trip at the live stake.
  sandwich  the bot's own trades on the recorded PumpSwap stream (its wallet is the one whose rows match its fills;
            never written out): another wallet trading the same side just before ours in our slot and the other
            side after ours within SAND_SLOTS slots.
Replay part: R1's realistic book of P_pool0_wait (realistic.RealExecutor: the live latency, fills at the first
recorded trade after the landing, the pre-send skip and 6040) at 0.1 SOL with no slot or loss limit, one book per
limit with the same latency draws (one key), on the whole record; the coins the live limit's book won and the tighter
book missed are the missed good fills.
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import dataclasses
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from scipy import stats

NAME = "execution_e1"
RESULTS = Path(os.environ.get("PYTHIA_RESULTS", Path(__file__).resolve().parents[2] / "results"))
MARKER = "<!-- generated below by lab.experiments.execution_e1; edit above this line only -->"
LAMPORTS = 1_000_000_000
LIVE_LIMIT = 0.60                          # live_exec.LIVE_POOL_BUY_TOL (a test keeps them equal)
LIMITS = (0.05, 0.10, 0.15, 0.20, 0.30, 0.45, 0.60)
REPLAY_LIMITS = LIMITS + (1.00,)
MISS_MAX = 0.10                            # the share of the winners' P&L a limit may drop and still be picked
FIXED_FEE_L = 1_000_000                    # fees at or above this: the fixed 0.001 SOL priority before the dynamic fee
SAND_SLOTS = 2                             # the attacker's other leg may land this many slots after ours
BOOT = 2_000
SEED = 7
TWIN = "P_pool0_wait"
REPLAY_STAKE_SOL = 0.1


# ---------------------------------------------------------------- the live record

def read_jsonl(p: Path) -> list[dict]:
    out = []
    try:
        with p.open(encoding="utf-8") as fh:
            for line in fh:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        pass
    return out


def read_csv(p: Path) -> list[dict]:
    try:
        with p.open(encoding="utf-8", newline="") as fh:
            return list(csv.DictReader(fh))
    except OSError:
        return []


def live_dir() -> Path:
    from ..pumpfun_rt.live_exec import data_dir
    return data_dir()


def load_live(d: Path) -> dict:
    return {"measured": read_jsonl(d / "measured.jsonl"), "orders": read_jsonl(d / "orders.jsonl"),
            "ledger": read_csv(d / "ledger.csv"), "skipped": read_jsonl(d / "skipped.jsonl")}


def _f(x) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if np.isfinite(v) else None


def pool_buys(measured: list[dict], orders: list[dict], ledger: list[dict]) -> list[dict]:
    """The live pool buys that filled, each with its run past the quote (the sent order's tokens over the filled
    ones, less 1), its slippage against the signal's spot price, its fee, send to landing and its closed trade
    from the ledger (matched by coin and landing time; a buy without a closed trade is left out)."""
    sent = {o["sig"]: o for o in orders if o.get("what") == "sent" and o.get("sig")}
    fee = {m["sig"]: int(m["fee_l"]) for m in measured if m.get("what") == "fee" and m.get("sig") and m.get("fee_l")}
    led = {(r.get("mint"), int(float(r["land_ms"]))): r for r in ledger if _f(r.get("land_ms")) is not None}
    out = []
    for m in measured:
        if m.get("what") != "fill" or m.get("side") != "buy" or m.get("venue") != "pool":
            continue
        o, r = sent.get(m.get("sig")), led.get((m.get("mint"), int(m.get("land_ms") or 0)))
        if o is None or r is None or not m.get("tokens") or _f(r.get("pnl_sol")) is None:
            continue
        stake = _f(r.get("stake_sol")) or (m.get("sol_l") or 0) / LAMPORTS
        if not stake:
            continue
        out.append({"t": int(m["land_ms"]), "rule": m.get("rule"), "run": int(o["tokens"]) / int(m["tokens"]) - 1,
                    "slip": _f(m.get("slip")), "fee_l": fee.get(m["sig"]), "send_ms": m.get("send_to_land_ms"),
                    "lat_ms": m.get("lat_ms"), "stake_sol": stake, "pnl_sol": float(r["pnl_sol"]),
                    "ret": float(r["pnl_sol"]) / stake})
    return sorted(out, key=lambda x: x["t"])


def failed_buys(measured: list[dict], skipped: list[dict]) -> list[dict]:
    """The live pool buys that ran past their bound: 6040 on landing (fee paid) and the pre-send skip (no fee)."""
    from ..pumpfun_rt.realistic import fail_kind
    out = [{"t": int(m.get("t") or 0), "kind": "6040", "fee_l": int(m.get("fee_l") or 0)} for m in measured
           if m.get("what") == "failed" and m.get("side") == "buy" and fail_kind(m.get("why")) == "6040"]
    out += [{"t": int(s.get("t") or 0), "kind": "ran away", "fee_l": 0} for s in skipped
            if str(s.get("why") or "").startswith("price ran away (")]
    return sorted(out, key=lambda x: x["t"])


def fail_fee_l(fails: list[dict], buys: list[dict]) -> int:
    """What a buy failing on its bound pays: the median fee of the live 6040s, else the buys' median fee."""
    xs = [f["fee_l"] for f in fails if f["kind"] == "6040" and f["fee_l"]] or \
        [b["fee_l"] for b in buys if b.get("fee_l")]
    return int(np.median(xs)) if xs else 0


def at_limit(buys: list[dict], limit: float, fee_l: int) -> np.ndarray:
    """Each buy's P&L in SOL under `limit`: its trade when its run fits, else a failed buy's fee."""
    return np.array([b["pnl_sol"] if b["run"] <= limit else -fee_l / LAMPORTS for b in buys], dtype=float)


def limit_rows(buys: list[dict], fails: list[dict], limits=LIMITS, live: float = LIVE_LIMIT,
               boot: int = BOOT, seed: int = SEED) -> list[dict]:
    """Per limit: buy orders (the filled ones and the live failures, which fail under it too), the dropped trades,
    the good fills missed (count and their P&L), the losses avoided, the P&L, the mean P&L per order in SOL and in
    % of the stake, the difference to the live limit with its bootstrap 90 % interval and per chronological half."""
    fee = fail_fee_l(fails, buys)
    failed_sol = -sum(f["fee_l"] for f in fails) / LAMPORTS
    n = len(buys) + len(fails)
    if not buys:
        return []
    stake = np.array([b["stake_sol"] for b in buys])
    base = at_limit(buys, live, fee)
    wins = sum(b["pnl_sol"] for b in buys if b["pnl_sol"] > 0)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(buys), size=(boot, len(buys)))
    half = len(buys) // 2
    rows = []
    for lim in limits:
        x = at_limit(buys, lim, fee)
        drop = [b for b in buys if b["run"] > lim]
        miss = [b for b in drop if b["pnl_sol"] > 0]
        d = x - base
        bd = d[idx].sum(axis=1) / n
        rows.append({"limit": lim, "orders": n, "trades": len(buys) - len(drop), "dropped": len(drop),
                     "missed": len(miss), "missed_sol": sum(b["pnl_sol"] for b in miss),
                     "missed_share": (sum(b["pnl_sol"] for b in miss) / wins) if wins > 0 else 0.0,
                     "avoided_sol": -sum(b["pnl_sol"] for b in drop if b["pnl_sol"] <= 0),
                     "pnl_sol": float(x.sum()) + failed_sol, "mean_sol": (float(x.sum()) + failed_sol) / n,
                     "mean_ret": float(np.mean(x / stake)), "d_mean_sol": float(d.sum()) / n,
                     "d_lo": float(np.quantile(bd, 0.05)), "d_hi": float(np.quantile(bd, 0.95)),
                     "d_half1": float(d[:half].sum()), "d_half2": float(d[half:].sum())})
    return rows


def pick(rows: list[dict], live: float = LIVE_LIMIT, miss_max: float = MISS_MAX) -> dict | None:
    """The pre-set choice: the best mean per order among the limits that miss at most miss_max of the winners'
    P&L and beat the live limit in both halves, the loosest of equals; None keeps the live limit."""
    ok = [r for r in rows if r["limit"] != live and r["missed_share"] <= miss_max
          and r["d_half1"] > 0 and r["d_half2"] > 0]
    return max(ok, key=lambda r: (r["mean_sol"], r["limit"])) if ok else None


def run_buckets(buys: list[dict], edges=(-1.0, 0.0, 0.05, 0.10, 0.20, 0.30, 0.60, 10.0)) -> list[dict]:
    """The trades by their run past the quote: count, mean and median return, win share."""
    out = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        r = np.array([b["ret"] for b in buys if lo < b["run"] <= hi])
        out.append({"lo": lo, "hi": hi, "n": len(r), "mean": float(r.mean()) if len(r) else None,
                    "median": float(np.median(r)) if len(r) else None,
                    "win": float((r > 0).mean()) if len(r) else None})
    return out


# ---------------------------------------------------------------- fee and tip

def fee_rows(buys_or_fills: list[dict], groups: int = 3) -> dict:
    """Landed transactions since the dynamic priority fee by fee tercile: the fee, send to landing (median, p90)
    and the Spearman correlation of fee and send to landing (a higher fee that lands sooner shows as negative)."""
    xs = [(int(b["fee_l"]), float(b["send_ms"])) for b in buys_or_fills
          if b.get("fee_l") and b.get("send_ms") is not None and int(b["fee_l"]) < FIXED_FEE_L]
    if len(xs) < 3 * groups:
        return {"n": len(xs), "rows": []}
    xs.sort()
    rows = []
    for g in np.array_split(np.arange(len(xs)), groups):
        f = np.array([xs[i][0] for i in g]) / LAMPORTS
        s = np.array([xs[i][1] for i in g])
        rows.append({"n": len(g), "fee_lo": float(f.min()), "fee_hi": float(f.max()), "fee_med": float(np.median(f)),
                     "send_med": float(np.median(s)), "send_p90": float(np.quantile(s, 0.9))})
    rho, p = stats.spearmanr([x[0] for x in xs], [x[1] for x in xs])
    return {"n": len(xs), "rows": rows, "rho": float(rho), "p": float(p)}


def landed_fills(measured: list[dict]) -> list[dict]:
    """Every landed live transaction (both sides) with its fee and send to landing."""
    fee = {m["sig"]: int(m["fee_l"]) for m in measured if m.get("what") == "fee" and m.get("sig") and m.get("fee_l")}
    return [{"t": int(m.get("land_ms") or 0), "side": m.get("side"), "fee_l": fee.get(m.get("sig")),
             "send_ms": m.get("send_to_land_ms")} for m in measured if m.get("what") == "fill"]


def fee_share(fee_l: float, tip_l: float, stake_sol: float) -> float:
    """A round trip's network fee and tip (two transactions) as a share of the stake."""
    return 2 * (fee_l + tip_l) / LAMPORTS / stake_sol if stake_sol > 0 else float("nan")


# ---------------------------------------------------------------- sandwiches

def own_wallet(fills: list[dict], amm: list[dict], window_ms: int = 90_000) -> str | None:
    """The wallet whose stream rows match the fills (coin, side, tokens within 2 %, within window_ms); kept in
    memory only."""
    by_mint: dict[str, list[dict]] = {}
    for r in amm:
        by_mint.setdefault(r["mint"], []).append(r)
    votes: dict[str, int] = {}
    for m in fills:
        if m.get("venue") != "pool" or not m.get("tokens"):
            continue
        hit = [r for r in by_mint.get(m.get("mint"), ()) if bool(r["buy"]) == (m.get("side") == "buy")
               and abs(r["base"] / m["tokens"] - 1) < 0.02 and abs(r["t"] - int(m.get("land_ms") or 0)) < window_ms]
        if len(hit) == 1:
            votes[hit[0]["user"]] = votes.get(hit[0]["user"], 0) + 1
    return max(votes, key=votes.get) if votes else None


def sandwiches(amm: list[dict], me: str, slots: int = SAND_SLOTS) -> dict:
    """Our rows on the stream (user `me`): per side, how many, how many had another wallet's same-side trade
    before ours in our slot, and how many were sandwiched (that wallet trading the other side after ours within
    `slots` slots). Order inside a slot is the stream's tx index."""
    by_mint: dict[str, list[dict]] = {}
    for r in amm:
        by_mint.setdefault(r["mint"], []).append(r)
    for v in by_mint.values():
        v.sort(key=lambda r: (r["slot"], r["tx"]))
    out = {s: {"n": 0, "front": 0, "sandwich": 0} for s in ("buy", "sell")}
    for rows in by_mint.values():
        for i, r in enumerate(rows):
            if r["user"] != me:
                continue
            o = out["buy" if r["buy"] else "sell"]
            o["n"] += 1
            before = {x["user"] for x in rows[:i] if x["slot"] == r["slot"] and x["user"] != me
                      and bool(x["buy"]) == bool(r["buy"])}
            after = {x["user"] for x in rows[i + 1:] if x["slot"] <= r["slot"] + slots and x["user"] != me
                     and bool(x["buy"]) != bool(r["buy"])}
            o["front"] += bool(before)
            o["sandwich"] += bool(before & after)
    return out


def stream_rows(mints: set[str], root: Path | None = None) -> list[dict]:
    """The recorded PumpSwap rows of these coins."""
    import polars as pl
    from ..pumpfun_rt import store
    root = root or store.base()
    if not mints:
        return []
    df = store.read("amm", store.days(root), root)
    if df.is_empty():
        return []
    return df.filter(pl.col("mint").is_in(sorted(mints))).select(
        ["t", "slot", "tx", "mint", "buy", "base", "user"]).to_dicts()


# ---------------------------------------------------------------- the replay

@contextlib.contextmanager
def pool_tol(tol: float):
    """realistic's pool bound set to `tol` for one call (its methods read the module's POOL_BUY_TOL)."""
    from ..pumpfun_rt import realistic as R
    old = R.POOL_BUY_TOL
    R.POOL_BUY_TOL = tol
    try:
        yield
    finally:
        R.POOL_BUY_TOL = old


def tol_executor(model, tol: float):
    """A realistic executor whose pool buys accept down to the quote / (1 + tol)."""
    from ..pumpfun_rt import realistic as R

    class TolExecutor(R.RealExecutor):
        buy_tol = tol                       # RealExecutor reads its own buy_tol since E1's bounds (slippage_e1)

        def _presend(self, at, data):
            with pool_tol(tol):
                return super()._presend(at, data)

        def _fill(self, at, side, o):
            with pool_tol(tol):
                return super()._fill(at, side, o)
    return TolExecutor(model)


def replay(limits=REPLAY_LIMITS, root=None, until_ms: int | None = None, log=print) -> dict:
    """R1's realistic P_pool0_wait at 0.1 SOL, one measuring book per limit (same latency draws), over the record."""
    from ..pumpfun_rt import curve as C
    from ..pumpfun_rt import pipeline as P
    from ..pumpfun_rt import realistic as R
    from ..pumpfun_rt import sim, store
    from ..pumpfun_rt.study import WARM_DAYS, WINDOW_DAYS, span_of, warm_book
    model = R.Model(R.fit(R._measured(), until_ms or int(time.time() * 1000)))
    all_days = [d for d in store.days(root) if until_ms is None or d <= store.day_of(until_ms)]
    days = all_days[-WINDOW_DAYS:]
    if not days:
        return {"empty": True}
    warm = [d for d in all_days if d < days[0]][-WARM_DAYS:]
    t_lo, t_hi = span_of(days, root)
    t_hi = t_hi if until_ms is None else min(t_hi, until_ms)
    eng = sim.Engine([], book=warm_book(warm, root), decisions=False, entry_until=t_hi - R.R1_TAIL_MS)
    s = P.BY_NAME[TWIN]
    pipes = {}
    for lim in limits:
        v = dataclasses.replace(s, name=f"{TWIN}@{lim:.2f}", p={**s.p, "base": TWIN}, stake_sol=REPLAY_STAKE_SOL)
        eng.rule_costs[v.name] = R.RealCosts(model=model)
        pipes[lim] = eng.add_pipe(R.Book(eng, [v], tol_executor(model, lim), name=v.name))
        pipes[lim].risk[v.name].limits = R.R1_CALIB_LIMITS
    t0 = time.time()
    sim.replay(days, eng, root, progress=lambda day, n: log(f"e1: {day} done ({n:,} events, "
                                                             f"{time.time() - t0:.0f} s)"), until_ms=t_hi)
    ent = {}
    for lim, p in pipes.items():
        e = [{"mint": x["mint"], "pnl_sol": x["pnl_sol"], "ret": x["pnl_sol"] / REPLAY_STAKE_SOL, "failed": False}
             for x in p.closed]
        e += [{"mint": f["mint"], "pnl_sol": f["pnl_sol"], "ret": f["pnl_sol"] / REPLAY_STAKE_SOL, "failed": True,
               "why": R._why(f)} for f in p.failed]
        ent[f"{lim:.2f}"] = e
    return {"days": days, "span": [t_lo, t_hi], "entries": ent, "fit": model.fit.to_json(),
            "tx_l": model.fit.tx_l(), "lamports": C.LAMPORTS}


def replay_rows(entries: dict, live: float = LIVE_LIMIT) -> list[dict]:
    """Per limit: signals, trades, skipped before the send, 6040s, the mean P&L per signal and per trade, the P&L,
    and against the live limit's book the coins it won that this limit did not trade (missed good fills)."""
    key = f"{live:.2f}"
    base = entries.get(key) or []
    won = {x["mint"]: x["pnl_sol"] for x in base if not x["failed"] and x["pnl_sol"] > 0}
    win_sol = sum(won.values())
    rows = []
    for k in sorted(entries, key=float):
        e = entries[k]
        trades = [x for x in e if not x["failed"]]
        traded = {x["mint"] for x in trades}
        miss = [m for m in won if m not in traded]
        pnl = sum(x["pnl_sol"] for x in e)
        rows.append({"limit": float(k), "signals": len(e), "trades": len(trades),
                     "ran_away": sum(1 for x in e if x["failed"] and x.get("why") == "price ran away"),
                     "on_landing": sum(1 for x in e if x["failed"] and x.get("why") == "price ran away on landing"),
                     "pnl_sol": pnl, "mean_sol": pnl / len(e) if e else None,
                     "mean_ret": float(np.mean([x["ret"] for x in trades])) if trades else None,
                     "median_ret": float(np.median([x["ret"] for x in trades])) if trades else None,
                     "missed": len(miss), "missed_share": (sum(won[m] for m in miss) / win_sol) if win_sol else 0.0})
    return rows


# ---------------------------------------------------------------- the run and the report

def run(d: Path | None = None, with_replay: bool = False, root=None, until_ms: int | None = None,
        log=print) -> dict:
    d = d or live_dir()
    live = load_live(d)
    buys = pool_buys(live["measured"], live["orders"], live["ledger"])
    fails = failed_buys(live["measured"], live["skipped"])
    rows = limit_rows(buys, fails)
    p = pick(rows)
    fills = [m for m in live["measured"] if m.get("what") == "fill"]
    sand = None
    try:
        amm = stream_rows({m["mint"] for m in fills if m.get("venue") == "pool" and m.get("mint")}, root)
        me = own_wallet(fills, amm)
        sand = sandwiches(amm, me) if me else None
    except Exception as e:                                # the stream is a bonus; the live part stands without it
        log(f"e1: no sandwich check ({type(e).__name__}: {e})")
    from ..pumpfun_rt.realistic import TIP_L
    stake = float(np.median([b["stake_sol"] for b in buys])) if buys else None
    fees = fee_rows(landed_fills(live["measured"]))
    fee_now = float(np.median([b["fee_l"] for b in landed_fills(live["measured"])
                               if b.get("fee_l") and b["fee_l"] < FIXED_FEE_L] or [0]))
    out = {"made": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
           "span": [buys[0]["t"], buys[-1]["t"]] if buys else None, "buys": len(buys),
           "fails": {k: sum(1 for f in fails if f["kind"] == k) for k in ("6040", "ran away")},
           "fail_fee_l": fail_fee_l(fails, buys), "runs": run_buckets(buys), "limits": rows,
           "pick": p["limit"] if p else None, "fee": fees, "stake_sol": stake, "tip_l": TIP_L,
           "fee_now_l": fee_now, "share_fixed": fee_share(FIXED_FEE_L + 5_000, TIP_L, stake) if stake else None,
           "share_now": fee_share(fee_now, TIP_L, stake) if stake else None, "sandwich": sand,
           "run_q": {q: float(np.quantile([b["run"] for b in buys], q)) for q in (0.5, 0.9, 0.95, 1.0)} if buys
           else {}}
    if with_replay:
        res = replay(root=root, until_ms=until_ms, log=log)
        if not res.get("empty"):
            out["replay"] = {"days": res["days"], "span": res["span"], "tx_l": res["tx_l"],
                             "rows": replay_rows(res["entries"])}
    return out


def _pc(x, digits=1) -> str:
    return "" if x is None else f"{x * 100:+.{digits}f} %"


def _day(ms) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M")


def markdown(out: dict) -> str:
    L = [f"Made {out['made']}. Live pool buys that filled and closed: {out['buys']}"
         + (f" ({_day(out['span'][0])} to {_day(out['span'][1])} UTC)" if out.get("span") else "")
         + f"; failed on their bound: {out['fails']['6040']} with 6040 (median fee "
         f"{out['fail_fee_l'] / LAMPORTS:.6f} SOL), {out['fails']['ran away']} skipped before the send. Run past "
         f"the quote: median {_pc(out['run_q'].get(0.5))}, p90 {_pc(out['run_q'].get(0.9))}, "
         f"max {_pc(out['run_q'].get(1.0))}.", "",
         "### Trades by their run past the quote", "",
         "| run | trades | mean return | median return | won |", "|---|---|---|---|---|"]
    for r in out["runs"]:
        if r["n"]:
            L.append(f"| {_pc(r['lo'], 0)} to {_pc(r['hi'], 0)} | {r['n']} | {_pc(r['mean'])} | "
                     f"{_pc(r['median'])} | {r['win'] * 100:.0f} % |")
    L += ["", "### Each limit on the live buys (a buy over it fails and pays the 6040 fee)", "",
          "| limit | trades | dropped | good fills missed | their P&L SOL (share of winners) | losses avoided SOL | "
          "P&L SOL | per order SOL | per filled buy, % of stake | vs live per order (90 %) | half 1, half 2 SOL |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in out["limits"]:
        L.append(f"| {r['limit'] * 100:.0f} % | {r['trades']} | {r['dropped']} | {r['missed']} | "
                 f"{r['missed_sol']:+.4f} ({r['missed_share'] * 100:.0f} %) | {r['avoided_sol']:.4f} | "
                 f"{r['pnl_sol']:+.4f} | {r['mean_sol']:+.5f} | {_pc(r['mean_ret'], 2)} | "
                 f"{r['d_mean_sol']:+.5f} ({r['d_lo']:+.5f} to {r['d_hi']:+.5f}) | "
                 f"{r['d_half1']:+.4f}, {r['d_half2']:+.4f} |")
    L += ["", f"Picked by the pre-set rule (best per order, at most {MISS_MAX * 100:.0f} % of the winners' P&L "
          f"missed, better than {LIVE_LIMIT * 100:.0f} % in both halves): "
          + (f"**{out['pick'] * 100:.0f} %**." if out.get("pick") is not None else "**none, keep the live limit**."),
          ""]
    rp = out.get("replay")
    if rp:
        L += [f"### R1's realistic replay of {TWIN} ({rp['days'][0]} to {rp['days'][-1]}, 0.1 SOL, every signal, "
              f"same latency draws, {rp['tx_l'] / LAMPORTS:.6f} SOL a transaction)", "",
              "| limit | signals | trades | skipped before the send | 6040 | P&L SOL | per signal SOL | mean return "
              "| median return | good fills of the 60 % book missed (share of its winners' P&L) |",
              "|---|---|---|---|---|---|---|---|---|---|"]
        for r in rp["rows"]:
            L.append(f"| {r['limit'] * 100:.0f} % | {r['signals']} | {r['trades']} | {r['ran_away']} | "
                     f"{r['on_landing']} | {r['pnl_sol']:+.3f} | "
                     f"{'' if r['mean_sol'] is None else format(r['mean_sol'], '+.5f')} | {_pc(r['mean_ret'])} | "
                     f"{_pc(r['median_ret'])} | {r['missed']} ({r['missed_share'] * 100:.0f} %) |")
        L.append("")
    f = out["fee"]
    L += ["### Fee and tip", "",
          f"Landed transactions since the dynamic priority fee: {f['n']}"
          + (f", Spearman of fee and send to landing {f['rho']:+.2f} (p {f['p']:.2f})." if f.get("rows") else "."),
          "", "| fee tercile, SOL | transactions | median fee | send to landing, median ms | p90 ms |",
          "|---|---|---|---|---|"]
    for r in f.get("rows") or []:
        L.append(f"| {r['fee_lo']:.6f} to {r['fee_hi']:.6f} | {r['n']} | {r['fee_med']:.6f} | "
                 f"{r['send_med']:.0f} | {r['send_p90']:.0f} |")
    if out.get("stake_sol"):
        L += ["", f"A round trip's network fee and Sender tip at the live median stake {out['stake_sol']:.3f} SOL: "
              f"{_pc(out['share_fixed'], 2)} with the old fixed 0.001 SOL priority, {_pc(out['share_now'], 2)} at "
              f"the dynamic fee's median {out['fee_now_l'] / LAMPORTS:.6f} SOL (tip {out['tip_l'] / LAMPORTS:.6f})."]
    s = out.get("sandwich")
    if s:
        L += ["", f"Sandwich check on the recorded stream (our own rows found there): buys {s['buy']['n']}, "
              f"{s['buy']['front']} with another wallet buying before ours in our slot, {s['buy']['sandwich']} "
              f"sandwiched; sales {s['sell']['n']}, {s['sell']['front']} with a sale before ours, "
              f"{s['sell']['sandwich']} sandwiched."]
    return "\n".join(L) + "\n"


def write(out: dict, path: Path | None = None) -> Path:
    path = path or RESULTS / f"{NAME}.md"
    head = path.read_text(encoding="utf-8").split(MARKER)[0] if path.exists() else f"# E1: {NAME}\n\n"
    path.write_text(head.rstrip() + "\n\n" + MARKER + "\n\n" + markdown(out), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m lab.experiments.execution_e1")
    ap.add_argument("--replay", action="store_true", help="also R1's replay at every limit (heavy)")
    ap.add_argument("--until", default=None, help="replay up to this UTC time (YYYY-MM-DDTHH:MM)")
    a = ap.parse_args(argv)
    until = int(datetime.strptime(a.until, "%Y-%m-%dT%H:%M").replace(tzinfo=timezone.utc).timestamp() * 1000) \
        if a.until else None
    out = run(with_replay=a.replay, until_ms=until)
    from .. import report
    rd = report.REPORTS / NAME
    try:
        rd.mkdir(parents=True, exist_ok=True)
        (rd / "latest.json").write_text(json.dumps(out, indent=1, default=float), encoding="utf-8")
    except OSError as e:
        print(f"  no report copy ({e})", file=sys.stderr)
    print(f"{out['buys']} live buys, pick {out['pick']} -> {write(out)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
