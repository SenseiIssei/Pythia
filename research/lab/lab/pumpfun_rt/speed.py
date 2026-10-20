"""Speed tiers: would being faster at a token's release pay after costs? PAPER ONLY.

Pre-registered in results/pumpfun_speed_plan.md (Y3). Every plain token is a snipe
candidate at its creation; the same buy is landed at eight speeds, from first in
the creation slot to the feed's own measured delay, and sold with three exits, so
the tiers compare like with like. Nothing here holds a wallet, reads a key or
sends a transaction: fills are the recorded curve's arithmetic.

    python -m lab.pumpfun_rt.speed                   the tiers on the record: reports/pumpfun_rt/speed.{md,json}
    python -m lab.pumpfun_rt.speed blocks --n 150    the block sample (public RPC, read only, cached)

Order inside a slot: the trades of a token in one slot are put in chain order by
their reserves (the virtual SOL reserve before a trade is the one after it minus
its SOL amount for a buy, plus it for a sale; the chain is followed from the
state before the slot), and by the collector's receive order where the chain is
ambiguous. The block sample checks that order against the block's own.

Tiers (where the buy lands; "back" is after every trade of the token in that slot):

  S0f  the creation slot, right after the creation transaction (our bid beats every same-slot buyer)
  S0b  the creation slot, back                 S1  creation slot + 1, back      S2  + 2, back
  T1   the last slot that starts within 1 s of the creation slot, back          T2  within 2 s
  NOW  the token's own measured detection delay (latency.py) plus two slots to send, back
  LM   the paper model's latency (curve.Costs), back

The buy asks for what the stake buys right after the creation transaction (what a
fast path sees) with a cost limit of stake x 1.30; it fails above the limit or once
the curve completed. Sales land as fast as the tier (S0f, S0b, S1 one slot after the
signal's slot, S2 two, T1/T2 1 s/2 s, NOW a draw of the record's trade delays plus
two slots, LM the model's draw) and take what the curve (else the pool) pays.
"""

from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import math
import sys
import time
import urllib.request
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import curve as C
from . import pipeline as P
from . import wallets as W
from .txbuild import JITO_TIP_ACCOUNTS

TIERS = ("S0f", "S0r", "S0b", "S1", "S2", "T1", "T2", "NOW", "LM")      # S0r: plan addendum 1
FILTERS = ("all", "dev", "cmig", "clean", "wallet")
EXITS = ("lad", "hz", "t15")
SEND_SLOTS = 2
STAKE_L = int(P.HARD_STAKE_SOL * C.LAMPORTS)
RUG = -0.5
BASE_FEE = 5_000

EXIT_PLANS = {
    "lad": P.Exits(30, 0.30, ((0.30, 0.5), (0.80, 1.0)), 0.20, 0.15),
    "hz": P.HZ_EXITS,
    "t15": P.Exits(15, 2.0, (), None, None, dev_sell=False, pull=False),
}
N_TRIALS = len(TIERS) * len(FILTERS) * len(EXITS)


# ---------------------------------------------------------------- chain order inside a slot

def chain_order(trades: list[dict], start_vs: int | None) -> tuple[list[dict], bool]:
    """The trades of one token in one slot in chain order: from the reserve before the slot, each next trade is
    the one whose reserve before it (vs after minus its SOL for a buy, plus for a sale) is the current reserve.
    Where no trade or several fit, the earliest received (collector tx number) goes next. Returns (ordered,
    whether the whole chain was resolved by reserves)."""
    left = sorted(trades, key=lambda r: (r["tx"], r.get("i", 0)))
    out: list[dict] = []
    cur = start_vs
    resolved = True
    while left:
        pick = None
        if cur is not None:
            hits = [k for k, r in enumerate(left) if _pre_vs(r) == cur]
            if len(hits) == 1:
                pick = hits[0]
            elif len(hits) > 1:
                pick = hits[0]
                resolved = False
        if pick is None:
            pick = 0
            if cur is not None:
                resolved = False
        r = left.pop(pick)
        out.append(r)
        cur = r["vs"]
    return out, resolved


def _pre_vs(r: dict) -> int:
    return r["vs"] - r["sol"] if r["buy"] else r["vs"] + r["sol"]


# ---------------------------------------------------------------- the index

@dataclass
class Mint:
    slot: int
    tx: int
    recv_ms: int
    vs0: int
    vt0: int
    rt0: int
    slots: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.int64))
    vs: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.int64))
    vt: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.int64))
    rt: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.int64))
    n_create: int = 0                     # trades of the creation transaction (the dev buy) at the start
    n_run: int = 0                        # then the unbroken run of transactions right behind it (S0r)
    run_txs: int = 0                      # how many transactions that run is
    done_slot: int | None = None          # the slot its curve completed in
    devs: set = field(default_factory=set)  # the creator and the creation's payer


class Index:
    """Per token: the creation and every curve trade in chain order (state after each); the record's slot
    clock (slot -> the time the engine gives that slot); the chain clock; the delivery delays."""

    def __init__(self):
        self.mints: dict[str, Mint] = {}
        self.ct_slots = np.zeros(0, dtype=np.int64)
        self.ct = np.zeros(0, dtype=np.int64)
        self.slot_ms = 400.0
        self.lag_ms: dict[str, float] = {}
        self.delays = np.zeros(0)
        self.stats: dict = {}

    # slots and times
    def time_of(self, slot: int) -> int:
        """The engine's time of a slot: the slot time of the first recorded slot at or after it."""
        i = int(np.searchsorted(self.ct_slots, slot, side="left"))
        if i >= len(self.ct_slots):
            return int(self.ct[-1]) + int((slot - self.ct_slots[-1]) * self.slot_ms)
        return int(self.ct[i])

    def slot_at(self, t: float) -> int:
        """The newest recorded slot whose slot time is at or before t."""
        i = int(np.searchsorted(self.ct, t, side="right")) - 1     # ct rises with the slot (a lower envelope)
        if i < 0:
            return int(self.ct_slots[0]) if len(self.ct_slots) else 0
        return int(self.ct_slots[i])

    # curve states
    def after_create(self, mint: str) -> tuple[int, int, int] | None:
        m = self.mints.get(mint)
        if m is None:
            return None
        if m.n_create:
            k = m.n_create - 1
            return int(m.vs[k]), int(m.vt[k]), int(m.rt[k])
        return m.vs0, m.vt0, m.rt0

    def after_run(self, mint: str) -> tuple[int, int, int] | None:
        """The curve after the creation transaction and the unbroken run behind it (S0r)."""
        m = self.mints.get(mint)
        if m is None:
            return None
        k = m.n_create + m.n_run - 1
        if k < 0:
            return m.vs0, m.vt0, m.rt0
        return int(m.vs[k]), int(m.vt[k]), int(m.rt[k])

    def through(self, mint: str, slot: int) -> tuple[int, int, int] | None:
        """The curve after every trade of the token up to and including `slot`; None once it completed."""
        m = self.mints.get(mint)
        if m is None:
            return None
        if m.done_slot is not None and slot >= m.done_slot:
            return None
        k = int(np.searchsorted(m.slots, slot, side="right")) - 1
        if k < 0:
            return m.vs0, m.vt0, m.rt0
        return int(m.vs[k]), int(m.vt[k]), int(m.rt[k])

    def delay_draw(self, *key) -> float:
        """A reproducible draw of the record's curve-trade delivery delay (ms)."""
        if not len(self.delays):
            return 0.0
        h = hashlib.blake2b(repr(key).encode(), digest_size=8).digest()
        u = int.from_bytes(h, "big") / 2 ** 64
        return float(max(0.0, self.delays[min(len(self.delays) - 1, int(u * len(self.delays)))]))


def build_index(days: list[str], root=None) -> Index:
    import polars as pl

    from . import latency as L
    from . import store
    idx = Index()
    cr = store.read("creates", days, root)
    tr = store.read("trades", days, root)
    ot = store.read("other", days, root)
    am = store.read("amm", days, root)
    # the engine's slot clock (sim.day_events): the earliest receive of a slot or of any later one
    pairs = pl.concat([df.select(pl.col("slot").cast(pl.Int64), pl.col("t").cast(pl.Int64))
                       for df in (cr, tr, ot, am) if df.height]).filter(pl.col("slot").is_not_null())
    first = pairs.group_by("slot").agg(pl.col("t").min().alias("ct")).sort("slot", descending=True)
    first = first.with_columns(pl.col("ct").cum_min()).sort("slot")
    idx.ct_slots = first["slot"].to_numpy().astype(np.int64)
    idx.ct = first["ct"].to_numpy().astype(np.int64)
    fr = L.frames(days, root)
    clock = L.ChainClock(fr["e_slot"], fr["e_bts"])
    idx.slot_ms = clock.slot_ms()
    chain = clock.at(fr["c_slot"])
    idx.lag_ms = {m: float(t - c) for m, t, c in zip(fr["c_mint"], fr["c_t"], chain) if np.isfinite(c)}
    idx.delays = L.trade_delays(fr)
    done = ot.filter(pl.col("kind").is_in(["complete", "migrate"])).group_by("mint").agg(pl.col("slot").min())
    done_slot = dict(zip(done["mint"].to_list(), done["slot"].to_list()))
    for r in cr.iter_rows(named=True):
        if r["mint"] in idx.mints or r["slot"] is None:
            continue
        idx.mints[r["mint"]] = Mint(int(r["slot"]), int(r["tx"] or 0), int(r["t"]), int(r["vs"] or 0),
                                    int(r["vt"] or 0), int(r["rt"] or 0), done_slot=done_slot.get(r["mint"]),
                                    devs={d for d in (r.get("creator"), r.get("user")) if d})
    tr = tr.filter(pl.col("mint").is_in(list(idx.mints)) & pl.col("quote").is_null()).with_row_index("i")
    tr = tr.select("i", "mint", "slot", "tx", "buy", "sol", "vs", "vt", "rt").sort(["mint", "slot", "tx", "i"])
    n_slots = n_multi = n_resolved = n_same_as_rx = 0
    for (mint,), g in tr.group_by(["mint"], maintain_order=True):
        m = idx.mints[mint]
        rows = g.to_dicts()
        ordered = []
        cur = m.vs0
        by_slot: dict[int, list] = defaultdict(list)
        for r in rows:
            if r["slot"] is None or r["vs"] is None or r["sol"] is None:
                continue
            by_slot[int(r["slot"])].append(r)
        for s in sorted(by_slot):
            grp = by_slot[s]
            n_slots += 1
            if len(grp) > 1:
                n_multi += 1
                o, ok = chain_order(grp, cur)
                n_resolved += int(ok)
                n_same_as_rx += int([r["i"] for r in o] == [r["i"] for r in sorted(grp, key=lambda r: (r["tx"],
                                                                                                         r["i"]))])
            else:
                o = grp
            ordered.extend(o)
            cur = o[-1]["vs"]
        if not ordered:
            continue
        m.slots = np.array([r["slot"] for r in ordered], dtype=np.int64)
        m.vs = np.array([r["vs"] for r in ordered], dtype=np.int64)
        m.vt = np.array([r["vt"] or 0 for r in ordered], dtype=np.int64)
        m.rt = np.array([r["rt"] or 0 for r in ordered], dtype=np.int64)
        k = 0
        while k < len(ordered) and ordered[k]["slot"] == m.slot and ordered[k]["tx"] == m.tx:
            k += 1
        m.n_create = k
        j, last = k, m.tx                          # the run: the next transaction numbers without a gap
        while j < len(ordered) and ordered[j]["slot"] == m.slot and ordered[j]["tx"] in (last, last + 1):
            last = ordered[j]["tx"]
            j += 1
        m.n_run = j - k
        m.run_txs = len({ordered[x]["tx"] for x in range(k, j)})
    idx.stats = {"slots": n_slots, "multi": n_multi, "chain_resolved": n_resolved / n_multi if n_multi else None,
                 "chain_equals_receive_order": n_same_as_rx / n_multi if n_multi else None,
                 "slot_ms": idx.slot_ms}
    return idx


# ---------------------------------------------------------------- strategies, filters, risk

@dataclass(frozen=True)
class SpeedStrategy(P.Strategy):
    """A snipe at creation for one tier, filter and exit (the filter is applied by SpeedPipeline)."""

    def wants_create(self, tok) -> bool:
        return True


def strategies() -> list[SpeedStrategy]:
    out = []
    for tier in TIERS:
        for flt in FILTERS:
            for ex in EXITS:
                e = EXIT_PLANS[ex]
                out.append(SpeedStrategy(f"SP_{tier}_{flt}_{ex}", "A", "create",
                                         e.ladder[-1][0] if e.ladder else 0.0, e.sl, e.time_s,
                                         {"tier": tier, "filter": flt, "exit": ex},
                                         f"speed tier {tier}, filter {flt}, exit {ex}", exits=e))
    return out


def passes(flt: str, tok, wallets: W.WalletBook) -> bool:
    """The pre-registered filters, known at creation."""
    hist = tok.hist or {}
    dev = tok.dev_buy_l / C.LAMPORTS
    if flt == "all":
        return True
    if flt == "dev":
        return 0.5 <= dev <= 5.0
    if flt == "cmig":
        return hist.get("migrated", 0) >= 1
    if flt == "clean":
        return hist.get("dumped", 0) == 0 and hist.get("n", 0) < 3
    if flt == "wallet":
        return dev >= 0.5 and not W.flipper(wallets.get(tok.creator))
    raise ValueError(flt)


class Unlimited(P.Risk):
    """No position limits: every candidate is entered, so the tiers compare like with like."""

    def why_not(self, t: float, cost_l: int) -> str | None:
        return None

    def booked(self, t: float, pnl_l: int) -> None:
        pass


class SpeedPipeline(P.Pipeline):
    def __init__(self, eng, strats, executor, **kw):
        super().__init__(eng, strats, executor, **kw)
        self.risk = {s.name: Unlimited() for s in strats}

    def signal(self, s, tok, t: float) -> None:
        if not passes(s.p["filter"], tok, self.eng.wallets):
            self.eng.skipped[(s.name, "filter")] += 1
            return
        super().signal(s, tok, t)


# ---------------------------------------------------------------- the executor

class TierExecutor:
    """Lands each strategy's orders at its tier's slot, filled from the chain-ordered curve (paper)."""

    kind = "paper"

    def __init__(self, idx: Index, costs: C.Costs | None = None):
        self.idx = idx
        self.costs = costs or C.Costs()
        self.pipe = None

    def attach(self, pipe) -> None:
        self.pipe = pipe

    def ready(self) -> str | None:
        return None

    def on_trade(self, table: str, row: dict) -> None:
        pass

    def poll(self, now: float) -> None:
        pass

    def _slots(self, ms: float) -> int:
        return int(math.ceil(max(0.0, ms) / self.idx.slot_ms))

    def buy_slot(self, tier: str, mint: str, c: int, base: str) -> int:
        if tier in ("S0f", "S0r", "S0b"):
            return c
        if tier == "S1":
            return c + 1
        if tier == "S2":
            return c + 2
        if tier in ("T1", "T2"):
            return c + int((1000.0 if tier == "T1" else 2000.0) // self.idx.slot_ms)
        if tier == "NOW":
            return c + self._slots(self.idx.lag_ms.get(mint, 0.0)) + SEND_SLOTS
        if tier == "LM":
            return c + self._slots(self.costs.latency(base, mint, "buy"))
        raise ValueError(tier)

    def sell_slot(self, tier: str, mint: str, s: int, base: str, leg: int) -> int:
        if tier in ("S0f", "S0r", "S0b", "S1"):
            return s + 1
        if tier == "S2":
            return s + 2
        if tier in ("T1", "T2"):
            return s + max(1, int((1000.0 if tier == "T1" else 2000.0) // self.idx.slot_ms))
        if tier == "NOW":
            return s + self._slots(self.idx.delay_draw(base, mint, "sell", leg)) + SEND_SLOTS
        if tier == "LM":
            key = (base, mint, "sell") if leg == 0 else (base, mint, "sell", leg)
            return s + max(1, self._slots(self.costs.latency(*key)))
        raise ValueError(tier)

    def buy(self, o: P.Order) -> None:
        s = self.pipe.strat_of(o.pid)
        m = self.idx.mints.get(o.mint)
        if m is None:
            return self.pipe.buy_failed(o.pid, o.signal_ms, "not indexed", self.costs.tx_lamports())
        land = self.buy_slot(s.p["tier"], o.mint, m.slot, P.base_name(s))
        at = max(o.signal_ms, self.idx.time_of(land))
        self.pipe.lat[o.pid] = (land - m.slot) * self.idx.slot_ms
        self.pipe.eng.push(at, "pipe", (self, "_land_buy", (o, land)))

    def sell(self, o: P.Order) -> None:
        s = self.pipe.strat_of(o.pid)
        sig = self.idx.slot_at(o.signal_ms)
        land = self.sell_slot(s.p["tier"], o.mint, sig, P.base_name(s), o.leg)
        at = max(o.signal_ms, self.idx.time_of(land))
        self.pipe.eng.push(at, "pipe", (self, "_land_sell", (o, land, at)))

    def _land_buy(self, at: float, data) -> None:
        o, land = data
        pipe, eng = self.pipe, self.pipe.eng
        s = pipe.strat_of(o.pid)
        tx = self.costs.tx_lamports()
        tok = eng.tokens.get(o.mint)
        start = self.idx.after_create(o.mint)
        tier = s.p["tier"]
        state = (start if tier == "S0f" else self.idx.after_run(o.mint) if tier == "S0r"
                 else self.idx.through(o.mint, land))
        if tok is None or start is None:
            return pipe.buy_failed(o.pid, at, "token gone", tx)
        if state is None:
            return pipe.buy_failed(o.pid, at, "curve completed before the buy landed", tx)
        fee = max(tok.fee_bps, self.costs.fee_bps_floor)
        want = C.curve_buy(STAKE_L, *start, fee)                  # what the stake buys right after the creation tx
        vs, vt, rt = state
        want = min(want, rt)
        if want <= 0:
            return pipe.buy_failed(o.pid, at, "nothing filled", tx)
        cost = P.curve_cost(want, vs, vt, fee)
        if cost > int(STAKE_L * (1 + C.SLIP_TOL)):
            return pipe.buy_failed(o.pid, at, "slippage", tx)
        pipe.bought(o.pid, at, want, cost, tx)

    def _land_sell(self, at: float, data) -> None:
        o, land, first_at = data
        pipe, eng = self.pipe, self.pipe.eng
        tx = self.costs.tx_lamports()
        tok = eng.tokens.get(o.mint)
        state = self.idx.through(o.mint, land)
        if state is not None and tok is not None:
            v = C.curve_sell(o.tokens, state[0], state[1], max(tok.fee_bps, self.costs.fee_bps_floor))
        else:
            v = eng.sale_value(tok, o.tokens, self.costs)
            if v is None:                                         # completed, the pool not seen yet: try again
                if at - first_at < 10 * 60_000:
                    eng.push(at + 2_000, "pipe", (self, "_land_sell", (o, land, first_at)))
                    return None
                return pipe.sold(o.pid, at, o.tokens, 0, tx, stuck=True)
        if v < o.limit_l:
            return pipe.sell_failed(o.pid, at, "under the floor", tx)
        pipe.sold(o.pid, at, o.tokens, v, tx)


# ---------------------------------------------------------------- the run

def run(root=None, log=print, until_ms: int | None = None, exits: tuple = EXITS) -> dict:
    """Pass 1 (in sample): the hazard models. Pass 2: every tier, filter and exit on the whole record."""
    from . import early as EA
    from . import exitpol as XP
    from . import sim, store
    from .study import span_of
    days = store.days(root)
    if not days:
        return {"empty": True}
    t_lo, t_hi = span_of(days, root)
    if until_ms is not None:
        t_hi = min(t_hi, until_ms)
    split = t_lo + (t_hi - t_lo) // 2
    t0 = time.time()
    idx = build_index(days, root)
    log(f"speed: index of {len(idx.mints):,} tokens in {time.time() - t0:.0f} s, slot {idx.slot_ms:.0f} ms, "
        f"chain resolved {idx.stats.get('chain_resolved')}")
    models: dict = {}
    if "hz" in exits:
        t0 = time.time()
        e1 = sim.Engine([], early_rows=True, entry_until=split, wallets=W.WalletBook(), snipers=EA.SniperBook())
        sim.replay(days, e1, root, until_ms=split + 45 * 60_000)
        try:
            models = XP.fit_live(e1.early.tables(), until_ms=split, log=log)
        except Exception as e:                                    # the hazard book then uses E0's price exits
            log(f"speed: hazard models failed ({type(e).__name__}: {e})")
        del e1
        log(f"speed: pass 1 (hazard models, in sample) in {time.time() - t0:.0f} s: {sorted(models)}")
    t0 = time.time()
    strats = [s for s in strategies() if s.p["exit"] in exits]
    eng = sim.Engine([], models=models, wallets=W.WalletBook(), snipers=EA.SniperBook(), entry_until=until_ms)
    pipe = SpeedPipeline(eng, strats, TierExecutor(idx), name="speed")
    eng.add_pipe(pipe)
    sim.replay(days, eng, root, until_ms=until_ms)
    log(f"speed: pass 2 in {time.time() - t0:.0f} s, {len(eng.closed):,} closed, {len(eng.failed):,} failed buys")
    return {"days": days, "split_ms": split, "span": (t_lo, t_hi), "closed": eng.closed, "failed": eng.failed,
            "index": idx.stats, "slot_ms": idx.slot_ms, "models": sorted(models),
            "skipped": {f"{k[0]}: {k[1]}": v for k, v in eng.skipped.items()}, "counts": dict(eng.counts)}


def stats(trades: list[dict], failed: list[dict]) -> dict:
    from .study import boot_mean
    allr = [{"ret": t["ret"], "pnl_sol": t["pnl_sol"], "signal_ms": t["signal_ms"]} for t in trades]
    allr += [{"ret": f["pnl_sol"] / (STAKE_L / C.LAMPORTS), "pnl_sol": f["pnl_sol"], "signal_ms": f["signal_ms"]}
             for f in failed]
    n = len(allr)
    out = {"trades": len(trades), "failed": len(failed), "n": n}
    if not n:
        return out
    r = np.array([x["ret"] for x in allr])
    pnl = np.array([x["pnl_sol"] for x in allr])
    lo, hi = boot_mean(allr)
    out.update(mean=float(r.mean()), median=float(np.median(r)), hit=float((pnl > 0).mean()),
               rugs=int((np.array([t["ret"] for t in trades]) <= RUG).sum()) if trades else 0,
               pnl_sol=float(pnl.sum()), mean_sol=float(pnl.mean()), band=(lo, hi),
               break_even_tip_sol=float(pnl.mean()) if pnl.mean() > 0 else None,
               exits={w: sum(1 for t in trades if t.get("exit_why") == w) for w in
                      sorted({t.get("exit_why") or "?" for t in trades})})
    return out


def evaluate(res: dict) -> dict:
    split = res["split_ms"]
    by = defaultdict(lambda: {"is": [], "oos": [], "fis": [], "foos": []})
    for t in res["closed"]:
        if t.get("book") != "speed":
            continue
        by[t["rule"]]["oos" if t["signal_ms"] >= split else "is"].append(t)
    for f in res["failed"]:
        by[f["rule"]]["foos" if f["signal_ms"] >= split else "fis"].append(f)
    table = []
    for s in strategies():
        d = by.get(s.name)
        if d is None:
            continue
        row = {"name": s.name, **s.p, "oos": stats(d["oos"], d["foos"]),
               "all": stats(d["is"] + d["oos"], d["fis"] + d["foos"])}
        table.append(row)
    front = {}
    for flt in FILTERS:
        for ex in EXITS:
            a = {t["mint"]: t for t in by.get(f"SP_S0f_{flt}_{ex}", {}).get("oos", [])}
            b = {t["mint"]: t for t in by.get(f"SP_S0b_{flt}_{ex}", {}).get("oos", [])}
            common = sorted(set(a) & set(b))
            if common:
                diff = np.array([a[m]["pnl_sol"] - b[m]["pnl_sol"] for m in common])
                front[f"{flt}_{ex}"] = {"n": len(common), "mean_sol": float(diff.mean()),
                                        "median_sol": float(np.median(diff))}
    return {"rows": table, "front": front}


# ---------------------------------------------------------------- the block sample

def rpc_call(url: str, method: str, params: list, timeout: float = 60.0) -> dict:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json",
                                                          "User-Agent": "pythia-lab (paper research, read only)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def block_txs(block: dict, mint: str) -> list[dict]:
    """The transactions of a block that traded `mint` (its token balances changed for a signer), in block
    order: index, signers, priority fee, positive SOL deltas of other accounts, token delta of the signer."""
    out = []
    for i, tx in enumerate(block.get("transactions") or []):
        meta = tx.get("meta") or {}
        if meta.get("err") is not None:
            continue
        keys = (tx.get("transaction") or {}).get("accountKeys") or []
        names = [k.get("pubkey") if isinstance(k, dict) else k for k in keys]
        if mint not in names:
            continue
        signers = [k.get("pubkey") for k in keys if isinstance(k, dict) and k.get("signer")]
        pre = {(b.get("owner"), b.get("mint")): int((b.get("uiTokenAmount") or {}).get("amount") or 0)
               for b in meta.get("preTokenBalances") or []}
        post = {(b.get("owner"), b.get("mint")): int((b.get("uiTokenAmount") or {}).get("amount") or 0)
                for b in meta.get("postTokenBalances") or []}
        delta = {o: post.get((o, mint), 0) - pre.get((o, mint), 0) for o in signers}
        who = next((o for o in signers if delta.get(o)), None)
        if who is None:
            continue
        pb, qb = meta.get("preBalances") or [], meta.get("postBalances") or []
        gains = {names[j]: int(qb[j]) - int(pb[j]) for j in range(min(len(names), len(pb), len(qb)))
                 if int(qb[j]) > int(pb[j]) and names[j] not in signers}
        fee = int(meta.get("fee") or 0)
        j = names.index(who)
        spend = int(pb[j]) - int(qb[j]) if j < min(len(pb), len(qb)) else 0
        out.append({"i": i, "n": len(block.get("transactions") or []), "signer": who, "buy": delta[who] > 0,
                    "tok": delta[who], "fee": fee, "prio": max(0, fee - BASE_FEE * max(1, len(signers))),
                    "spend": spend, "gains": gains})
    return out


def sample_slots(idx: Index, n: int, slice_ms: int = 15 * 60_000) -> list[tuple[int, str]]:
    """Up to n plain creation slots spread over quarter-hour slices of the record, those with a same-slot
    buyer other than the creation transaction first."""
    rows = []
    for mint, m in idx.mints.items():
        if not len(m.slots):
            continue
        same = int(((m.slots == m.slot)).sum()) - m.n_create
        rows.append((m.recv_ms // slice_ms, -int(same > 0), m.recv_ms, m.slot, mint))
    rows.sort()
    by: dict[int, list] = defaultdict(list)
    for r in rows:
        by[r[0]].append(r)
    k = max(1, math.ceil(n / max(1, len(by))))
    out = []
    for sl in sorted(by):
        out += [(r[3], r[4]) for r in by[sl][:k]]
    return out[:n]


def fetch_blocks(idx: Index, n: int, url: str, cache: Path, pace_s: float = 3.0, log=print) -> list[dict]:
    """Read the sample's blocks once (cached by slot), keep only the token's transactions."""
    got = []
    if cache.exists():
        got = json.loads(cache.read_text(encoding="utf-8"))
    have = {g["slot"] for g in got}
    for slot, mint in sample_slots(idx, n):
        if slot in have:
            continue
        t0 = time.monotonic()
        try:
            d = rpc_call(url, "getBlock", [slot, {"encoding": "json", "transactionDetails": "accounts",
                                                  "maxSupportedTransactionVersion": 1, "rewards": False,
                                                  "commitment": "confirmed"}])
        except Exception as e:                                    # a block the endpoint cannot serve is skipped
            log(f"speed blocks: {slot} {type(e).__name__}: {e}")
            continue
        b = d.get("result")
        if not b:
            log(f"speed blocks: {slot} {str(d.get('error'))[:120]}")
            continue
        got.append({"slot": slot, "mint": mint, "txs": block_txs(b, mint), "n": len(b.get("transactions") or [])})
        have.add(slot)
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(got), encoding="utf-8")
        time.sleep(max(0.0, pace_s - (time.monotonic() - t0)))
    return got


PROPORTIONAL_IQR = 0.10            # an account paid a fixed share of the trade (log ratio IQR below this) is a fee


def relay_accounts(blocks: list[dict], min_signers: int = 3) -> tuple[set[str], set[str]]:
    """(tip accounts, fee accounts) among the third-party accounts paid by several unrelated buyers of at least
    two tokens in the sample. A fee account (pump.fun's fee recipients, a trading bot's platform fee) is paid a
    fixed share of the trade: the spread (interquartile range) of log(payment / the buyer's spend) is under
    PROPORTIONAL_IQR, or its median share is within 15 % of the protocol fee's share. A tip account (Jito's
    published ones always; other relays' found this way) is paid amounts that do not follow the trade size."""
    share: dict[str, list] = defaultdict(list)
    payers: dict[str, set] = defaultdict(set)
    mints: dict[str, set] = defaultdict(set)
    for b in blocks:
        for tx in b["txs"]:
            if not tx["buy"] or tx.get("spend", 0) <= 0:
                continue
            for acct, g in tx["gains"].items():
                if g > 0:
                    share[acct].append(math.log(g / tx["spend"]))
                    payers[acct].add(tx["signer"])
                    mints[acct].add(b["mint"])
    recurring = [a for a in share if len(payers[a]) >= min_signers and len(mints[a]) >= 2]
    spread = {a: float(np.subtract(*np.percentile(share[a], [75, 25]))) for a in recurring}
    fees = {a for a in recurring if spread[a] < PROPORTIONAL_IQR}
    proto = float(np.median([np.median(share[a]) for a in fees])) if fees else None
    if proto is not None:
        fees |= {a for a in recurring if abs(math.exp(float(np.median(share[a])) - proto) - 1) <= 0.15}
    fees -= set(JITO_TIP_ACCOUNTS)                           # a payment to Jito's tip accounts is a tip, always
    tips = {a for a in recurring if a not in fees} | set(JITO_TIP_ACCOUNTS)
    return tips, fees


def blocks_summary(blocks: list[dict], idx: Index | None = None) -> dict:
    """The creation slot as the block has it: where the creation is, how many outside buyers follow it in the
    same slot, how many of them stand in an unbroken run right behind it (most likely the creator's own bundle,
    which nobody can step in front of), and the bids of the outside buyers (priority fee plus tips)."""
    tips, fees = relay_accounts(blocks)
    bids, ahead, jito_share, other_share, first_bid, create_i, run_share, gap = [], [], [], [], [], [], [], []
    for b in blocks:
        txs = sorted(b["txs"], key=lambda t: t["i"])
        if not txs:
            continue
        m = idx.mints.get(b["mint"]) if idx is not None else None
        devs = (m.devs if m is not None else set()) or {txs[0]["signer"]}
        first = next((t for t in txs if t["signer"] in devs), txs[0])
        create_i.append(first["i"] / max(1, b["n"]))
        snipers = [t for t in txs if t["i"] > first["i"] and t["buy"] and t["signer"] not in devs]
        ahead.append(len(snipers))
        if not snipers:
            continue
        k, run = first["i"], 0
        for t in sorted(snipers, key=lambda t: t["i"]):
            if t["i"] != k + 1:
                break
            run, k = run + 1, t["i"]
        run_share.append(run / len(snipers))
        gap.append(snipers[0]["i"] - first["i"])
        best = 0
        for t in snipers:
            jt = sum(g for a, g in t["gains"].items() if a in JITO_TIP_ACCOUNTS)
            ot = sum(g for a, g in t["gains"].items() if a in tips and a not in JITO_TIP_ACCOUNTS)
            bid = t["prio"] + jt + ot
            bids.append(bid)
            jito_share.append(jt > 0)
            other_share.append(ot > 0)
            best = max(best, bid)
        first_bid.append(best)
    pct = lambda a: {f"p{p}": float(np.percentile(a, p)) for p in (10, 25, 50, 75, 90, 99)} if len(a) else {}  # noqa
    sol = lambda a: {k: v / C.LAMPORTS for k, v in pct(np.array(a, dtype=float)).items()}                    # noqa
    return {"blocks": len(blocks), "with_snipers": len(first_bid),
            "snipers_per_slot": pct(np.array(ahead, dtype=float)), "creation_index_share": pct(np.array(create_i)),
            "first_sniper_after_creation_txs": pct(np.array(gap, dtype=float)),
            "share_of_snipers_in_a_run_behind_creation": float(np.mean(run_share)) if run_share else None,
            "bid_sol": sol(bids), "best_bid_sol": sol(first_bid),
            "prio_only_sol": sol([t["prio"] for b in blocks for t in b["txs"] if t["buy"]]),
            "jito_tip_share": float(np.mean(jito_share)) if jito_share else None,
            "other_relay_tip_share": float(np.mean(other_share)) if other_share else None,
            "tip_accounts_found": len(tips - set(JITO_TIP_ACCOUNTS)), "fee_accounts_found": len(fees),
            "n_bids": len(bids)}


def compare_order(blocks: list[dict], idx: Index) -> dict:
    """Does the reserve chain put the token's creation-slot trades in the block's order (by token amounts), and
    is the record's run behind the creation (S0r) as long as the block's unbroken run of the token's
    transactions behind the creation transaction?"""
    n = ok = rn = rok = 0
    for b in blocks:
        m = idx.mints.get(b["mint"])
        txs = sorted(b["txs"], key=lambda t: t["i"])
        if m is None or not txs:
            continue
        if m.n_create and txs[0]["signer"] in m.devs:
            i0, run = txs[0]["i"], 0
            for t in txs[1:]:
                if t["i"] != i0 + run + 1:
                    break
                run += 1
            rn += 1
            rok += int(run == m.run_txs)
        if len(txs) < 2:
            continue
        sel = m.slots == m.slot
        k = int(sel.sum())
        if k < 2 or k != len(txs):
            continue
        # the curve's token reserve falls by each buy's tokens: the chain's sequence of token moves
        rt = np.concatenate([[m.rt0], m.rt[sel]])
        moves = (rt[:-1] - rt[1:]).tolist()
        n += 1
        ok += int(moves == [t["tok"] for t in txs])
    return {"slots_compared": n, "same_order": ok / n if n else None, "runs_compared": rn,
            "same_run_length": rok / rn if rn else None}


# ---------------------------------------------------------------- report

def pct(x, sign=True) -> str:
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return "n/a"
    return f"{x:+.1%}" if sign else f"{x:.1%}"


def report_md(res: dict, ev: dict, blocks: dict | None, latency: dict | None) -> str:
    md = ["# pump.fun speed tiers (Y3)", "",
          "Paper only. Fills are the recorded curve's arithmetic; nothing was sent.", "",
          f"Record {len(res['days'])} day(s), split at {res['split_ms']}; slot {res['slot_ms']:.0f} ms; "
          f"hazard models: {', '.join(res['models']) or 'none (E0 fallback)'}; "
          f"in-slot chain resolved for {pct(res['index'].get('chain_resolved'), False)} of multi-trade slots "
          f"(equal to the receive order in {pct(res['index'].get('chain_equals_receive_order'), False)}).", "",
          "| tier | filter | exit | trades (oos) | failed | mean | median | hit | rugs | P&L SOL | band | break-even tip "
          "| mean (all) |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in ev["rows"]:
        o, a = r["oos"], r["all"]
        if not a.get("n"):
            continue
        band = o.get("band") or (math.nan, math.nan)
        be = o.get("break_even_tip_sol")
        md.append(f"| {r['tier']} | {r['filter']} | {r['exit']} | {o['trades']} | {o['failed']} | "
                  f"{pct(o.get('mean'))} | {pct(o.get('median'))} | {pct(o.get('hit'), False)} | {o.get('rugs', 0)} | "
                  f"{o.get('pnl_sol', 0.0):+.2f} | {pct(band[0])} to {pct(band[1])} | "
                  f"{'none' if be is None else f'{be:.4f} SOL'} | {pct(a.get('mean'))} |")
    md += ["", "## Value of the front (S0f minus S0b, same token, out of sample)", "",
           "| filter_exit | tokens | mean SOL | median SOL |", "|---|---|---|---|"]
    for k, v in ev["front"].items():
        md.append(f"| {k} | {v['n']} | {v['mean_sol']:+.4f} | {v['median_sol']:+.4f} |")
    if blocks:
        md += ["", "## Block sample", "", "```", json.dumps(blocks, indent=1), "```"]
    if latency:
        md += ["", "## Detection latency (latency.py)", "", f"median {latency.get('lag_ms', {}).get('p50')} ms"]
    return "\n".join(md) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", nargs="?", default="tiers", choices=("tiers", "blocks"))
    ap.add_argument("--n", type=int, default=150)
    ap.add_argument("--rpc", default="https://api.mainnet-beta.solana.com")
    ap.add_argument("--until-ms", type=int, default=None)
    ap.add_argument("--exits", default=",".join(EXITS))
    a = ap.parse_args(argv)
    from .. import report as rep
    from . import store
    out = rep.REPORTS / "pumpfun_rt"
    out.mkdir(parents=True, exist_ok=True)
    if a.cmd == "blocks":
        idx = build_index(store.days())
        got = fetch_blocks(idx, a.n, a.rpc, out / "speed_blocks.json")
        s = blocks_summary(got, idx)
        s["order"] = compare_order(got, idx)
        print(json.dumps(s, indent=1))
        (out / "speed_blocks_summary.json").write_text(json.dumps(s, indent=1), encoding="utf-8")
        return 0
    res = run(until_ms=a.until_ms, exits=tuple(x for x in a.exits.split(",") if x))
    if res.get("empty"):
        print("speed: nothing recorded")
        return 1
    ev = evaluate(res)
    try:
        blocks = json.loads((out / "speed_blocks_summary.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        blocks = None
    md = report_md(res, ev, blocks, None)
    tag = "" if a.exits == ",".join(EXITS) else "_" + a.exits.replace(",", "_")
    (out / f"speed{tag}.json").write_text(json.dumps({k: v for k, v in res.items() if k not in ("closed", "failed")}
                                                     | {"eval": ev}, indent=1, default=str), encoding="utf-8")
    (out / f"speed{tag}.md").write_text(md, encoding="utf-8")
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
