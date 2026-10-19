"""The paper engine: rules, fills with latency, exits, and the model's decision rows.

One engine serves both the live stream (live.py feeds it decoded rows as they
arrive) and recorded days (replay() feeds it the store's rows in receive
order), so a rule's paper result on recorded data is what the shadow book
would have done.

Time: every action (a signal at a checkpoint, an order landing, a time stop,
a label read) is scheduled at a time T and runs after every event received at
or before T and before any event received after T. So an action at T sees the
whole batch received at T, and a trade received exactly at our landing time
counts as before it, which errs against us.
"""

from __future__ import annotations

import dataclasses
import heapq
import math
from collections import Counter

from . import curve as C
from . import strategies as S
from .tokens import CreatorBook, Token

OFFSETS = (3, 10, 30, 60, 120, 300)          # model decision points, seconds after creation
LABEL_HORIZONS = (30, 300)                    # the round-trip labels, seconds
MIG_LABEL_H = 6                               # "completes its curve within 6 hours"
EVICT_AGE_MS = (MIG_LABEL_H * 3600 + 120) * 1000
IDLE_MS = 30 * 60_000
STUCK_RETRY_MS, STUCK_MAX_MS = 2_000, 10 * 60_000
STAKE = int(S.STAKE_SOL * C.LAMPORTS)
DUMP = 0.5                                    # "the dev dumps": sells half or more of what it held at t


def model_rule(rule: S.Rule) -> S.Rule:
    """The same rule with the model filter in front (a separate book)."""
    return dataclasses.replace(rule, name=rule.name + "+model", p={**rule.p, "model": True},
                               label=rule.label + "; model filter")


class Engine:
    def __init__(self, rules: list[S.Rule] | None = None, costs: C.Costs | None = None,
                 book: CreatorBook | None = None, decisions: bool = False, model=None, on_close=None,
                 entry_from: int | None = None, entry_until: int | None = None):
        self.rules = list(S.RULES if rules is None else rules)
        self.costs = costs or C.Costs()
        self.book = book or CreatorBook()
        self.decisions_on = decisions
        self.model = model                               # .allow(rule, features) -> (bool, prob)
        self.on_close = on_close
        self.entry_from, self.entry_until = entry_from, entry_until
        self.rule_by = {r.name: r for r in self.rules}
        self.by_entry: dict[str, list[S.Rule]] = {}
        for r in self.rules:
            self.by_entry.setdefault(r.entry, []).append(r)
        self.tokens: dict[str, Token] = {}
        self.entered: dict[str, set] = {}
        self.heap: list = []
        self.seq = 0
        self.now = 0
        self.positions: dict[int, dict] = {}
        self.by_mint: dict[str, set] = {}
        self.open_n: Counter = Counter()
        self.closed: list[dict] = []
        self.failed: list[dict] = []
        self.skipped: Counter = Counter()
        self.rows: list[dict] = []
        self.rows_by_mint: dict[str, list[int]] = {}
        self.gaps: list[tuple[int, int]] = []
        self.counts: Counter = Counter()
        self.next_pid = 0

    # ------------------------------------------------------------ scheduling
    def push(self, t: float, kind: str, data) -> None:
        heapq.heappush(self.heap, (t, self.seq, kind, data))
        self.seq += 1

    def advance(self, t: float) -> None:
        """Run every action due before an event at time t (or up to t from a timer)."""
        h = self.heap
        while h and h[0][0] < t:
            at, _, kind, data = heapq.heappop(h)
            self.now = at
            getattr(self, "_a_" + kind)(at, data)
        self.now = max(self.now, t)

    # ------------------------------------------------------------ events
    def create(self, t, tx, mint, creator, vs, vt, rt, name="", symbol="", uri="", mayhem=False, cashback=False,
               quote=None) -> None:
        self.advance(t)
        if mint in self.tokens:
            return
        hist = self.book.snapshot(creator, t)
        self.book.created(creator, t)
        tok = Token(mint, creator, t, tx, vs, vt, rt, hist, name, symbol, uri, mayhem, cashback, quote)
        self.tokens[mint] = tok
        self.counts["tokens"] += 1
        self.push(t, "signal_create", mint)
        for r in self.by_entry.get("checkpoint", ()):
            self.push(t + r.p["w_s"] * 1000, "checkpoint", (mint, r.name))
        if self.decisions_on:
            for off in OFFSETS:
                self.push(t + off * 1000, "decide", (mint, off))
        self.push(t + EVICT_AGE_MS, "evict", mint)

    def trade(self, t, tx, mint, buy, sol, tok_amt, user, vs, vt, rs, rt, fb, cfb) -> None:
        self.advance(t)
        tok = self.tokens.get(mint)
        if tok is None:
            return
        tok.trade(t, tx, buy, sol, tok_amt, user, vs, vt, rs, rt, fb, cfb, self.book)
        if tok.tradeable():
            for r in self.by_entry.get("momentum", ()):
                if r.wants_momentum(tok, t):
                    self.signal(r, tok, t)
            for r in self.by_entry.get("progress", ()):
                if r.wants_progress(tok, t):
                    self.signal(r, tok, t)
        for pid in tuple(self.by_mint.get(mint, ())):
            self.check_exit(pid, t)

    def complete(self, t, mint) -> None:
        self.advance(t)
        tok = self.tokens.get(mint)
        if tok is not None:
            tok.completed(t, self.book)

    def migrate(self, t, mint, pool, sol, tok_amt) -> None:
        self.advance(t)
        tok = self.tokens.get(mint)
        if tok is None:
            return
        if tok.complete_t is None:
            tok.completed(t, self.book)
        tok.migrated(t, pool, sol, tok_amt)
        tok.last_t = t
        for r in self.by_entry.get("migration", ()):
            self.push(t + r.p["delay_s"] * 1000, "signal_rule", (mint, r.name))

    def amm(self, t, mint, buy, base, quote, pb, pq, lpb, pfb, cfb) -> None:
        self.advance(t)
        tok = self.tokens.get(mint)
        if tok is None:
            return
        tok.amm(buy, base or 0, quote or 0, pb, pq, lpb, pfb, cfb)
        tok.last_t = t
        for pid in tuple(self.by_mint.get(mint, ())):
            self.check_exit(pid, t)

    def meta(self, t, mint, flags: dict) -> None:
        self.advance(t)
        tok = self.tokens.get(mint)
        if tok is not None:
            tok.set_meta(t, flags)

    def gap(self, t0, t1) -> None:
        """The stream was down from t0 to t1: everything open across it is marked."""
        self.advance(t1)
        self.gaps.append((t0, t1))
        for p in self.positions.values():
            p["gap"] = True

    # ------------------------------------------------------------ entries
    def _a_signal_create(self, at, mint) -> None:
        tok = self.tokens.get(mint)
        if tok is None:
            return
        for r in self.by_entry.get("create", ()):
            if r.wants_create(tok):
                self.signal(r, tok, at)

    def _a_checkpoint(self, at, data) -> None:
        mint, name = data
        tok = self.tokens.get(mint)
        r = self._rule(name)
        if tok is not None and r is not None and tok.on_curve and r.wants_checkpoint(tok, at):
            self.signal(r, tok, at)

    def _a_signal_rule(self, at, data) -> None:
        mint, name = data
        tok = self.tokens.get(mint)
        r = self._rule(name)
        if tok is not None and r is not None:
            self.signal(r, tok, at)

    def _rule(self, name: str) -> S.Rule | None:
        return self.rule_by.get(name)

    def signal(self, r: S.Rule, tok: Token, t: float) -> None:
        done = self.entered.setdefault(tok.mint, set())
        if r.name in done:
            return
        done.add(r.name)
        if self.entry_from is not None and tok.t0 < self.entry_from:
            return
        if self.entry_until is not None and t >= self.entry_until:
            return
        self.counts["signals"] += 1
        if r.family != "E" and not tok.tradeable():
            self.skipped[(r.name, "not a plain SOL curve")] += 1
            return
        if r.family == "E" and (not tok.pq or tok.quote is not None):
            self.skipped[(r.name, "no pool state")] += 1
            return
        if self.open_n[r.name] >= S.MAX_OPEN:
            self.skipped[(r.name, "book full")] += 1
            return
        prob = None
        if r.p.get("model"):
            if self.model is None:
                self.skipped[(r.name, "no model")] += 1
                return
            ok, prob = self.model.allow(r, tok.features(int(t)))
            if not ok:
                self.skipped[(r.name, "model")] += 1
                return
        pid = self.next_pid
        self.next_pid += 1
        lat = self.costs.latency(r.name, tok.mint, "buy")
        self.positions[pid] = {"pid": pid, "rule": r.name, "family": r.family, "mint": tok.mint,
                               "name": tok.name, "symbol": tok.symbol, "created_ms": tok.t0, "signal_ms": int(t),
                               "signal_price": tok.price(), "lat_buy": lat, "state": "pending", "tokens": 0,
                               "prob": prob, "gap": False, "age_s": (t - tok.t0) / 1000,
                               "progress": tok.progress(), "dev_dumped_at_entry": tok.dev_dumped}
        self.by_mint.setdefault(tok.mint, set()).add(pid)
        self.open_n[r.name] += 1
        self.push(t + lat, "land_buy", pid)

    def _a_land_buy(self, at, pid) -> None:
        p = self.positions.get(pid)
        if p is None:
            return
        tok = self.tokens.get(p["mint"])
        r = self._rule(p["rule"])
        tx = self.costs.tx_lamports()
        why = None
        got = 0
        if tok is None:
            why = "token gone"
        elif r.family == "E":
            if not tok.pq or not tok.pb:
                why = "no pool state"
            else:
                pr = C.price(tok.pq, tok.pb)
                if pr > p["signal_price"] * (1 + self.costs.slip_tol):
                    why = "slippage"
                else:
                    got = C.pool_buy(STAKE, tok.pb, tok.pq, max(tok.amm_fee_bps, self.costs.fee_bps_floor))
        elif not tok.on_curve:
            why = "curve completed before the buy landed"
        else:
            pr = tok.price()
            if pr > p["signal_price"] * (1 + self.costs.slip_tol):
                why = "slippage"
            else:
                got = C.curve_buy(STAKE, tok.vs, tok.vt, tok.rt, max(tok.fee_bps, self.costs.fee_bps_floor))
        if why is None and got <= 0:
            why = "nothing filled"
        if why is not None:
            self._drop(p)
            f = {"rule": p["rule"], "mint": p["mint"], "signal_ms": p["signal_ms"], "land_ms": int(at),
                 "why": why, "pnl_sol": -tx / C.LAMPORTS}
            self.failed.append(f)
            return
        p.update(state="open", tokens=got, land_ms=int(at), entry_price=tok.price() if r.family != "E" else
                 C.price(tok.pq, tok.pb), cost_l=STAKE + tx, exiting=False)
        self.push(at + r.hold_s * 1000, "time_stop", pid)
        self.check_exit(pid, at)

    def _drop(self, p: dict) -> None:
        self.positions.pop(p["pid"], None)
        s = self.by_mint.get(p["mint"])
        if s is not None:
            s.discard(p["pid"])
            if not s:
                self.by_mint.pop(p["mint"], None)
        self.open_n[p["rule"]] -= 1

    # ------------------------------------------------------------ exits
    def sale_value(self, tok: Token | None, tokens: int) -> int | None:
        """Lamports a sale of `tokens` would bring now (after the fee), None if it cannot be sold now."""
        if tok is None:
            return 0
        if tok.on_curve:
            return C.curve_sell(tokens, tok.vs, tok.vt, max(tok.fee_bps, self.costs.fee_bps_floor))
        if tok.pq and tok.pb:
            return C.pool_sell(tokens, tok.pb, tok.pq, max(tok.amm_fee_bps, self.costs.fee_bps_floor))
        return None

    def check_exit(self, pid: int, t: float) -> None:
        p = self.positions.get(pid)
        if p is None or p["state"] != "open" or p["exiting"]:
            return
        r = self._rule(p["rule"])
        v = self.sale_value(self.tokens.get(p["mint"]), p["tokens"])
        if v is None:
            return
        p["mark_l"] = v
        if v >= STAKE * (1 + r.tp):
            self._exit(p, t, "take")
        elif v <= STAKE * (1 - r.sl):
            self._exit(p, t, "stop")

    def _a_time_stop(self, at, pid) -> None:
        p = self.positions.get(pid)
        if p is not None and p["state"] == "open" and not p["exiting"]:
            self._exit(p, at, "time")

    def _exit(self, p: dict, t: float, why: str) -> None:
        p["exiting"] = True
        p["exit_why"] = why
        p["exit_signal_ms"] = int(t)
        self.push(t + self.costs.latency(p["rule"], p["mint"], "sell"), "land_sell", (p["pid"], int(t)))

    def _a_land_sell(self, at, data) -> None:
        pid, t_sig = data
        p = self.positions.get(pid)
        if p is None:
            return
        tok = self.tokens.get(p["mint"])
        v = self.sale_value(tok, p["tokens"])
        if v is None:
            if at - t_sig < STUCK_MAX_MS:                  # curve complete, pool not seen yet: try again
                self.push(at + STUCK_RETRY_MS, "land_sell", (pid, t_sig))
                return
            v, p["exit_why"] = 0, "stuck"
        tx = self.costs.tx_lamports()
        pnl = v - STAKE - 2 * tx
        rec = {k: p.get(k) for k in ("rule", "family", "mint", "name", "symbol", "created_ms", "signal_ms",
                                     "land_ms", "exit_signal_ms", "exit_why", "prob", "gap", "age_s", "progress",
                                     "signal_price", "entry_price")}
        rec.update(exit_ms=int(at), exit_price=tok.price() if tok else 0.0, proceeds_sol=v / C.LAMPORTS,
                   pnl_sol=pnl / C.LAMPORTS, ret=pnl / STAKE, hold_s=(at - p["land_ms"]) / 1000,
                   dev_dumped=bool(tok and tok.dev_dumped and tok.dev_sell_t is not None
                                   and tok.dev_sell_t <= at), migrated=bool(tok and tok.complete_t is not None
                                                                           and tok.complete_t <= at),
                   lat_buy_ms=p["lat_buy"], slip=(p["entry_price"] / p["signal_price"] - 1)
                   if p.get("signal_price") else None)
        self._drop(p)
        self.closed.append(rec)
        if self.on_close is not None:
            self.on_close(rec)

    # ------------------------------------------------------------ model rows
    def _a_decide(self, at, data) -> None:
        mint, off = data
        tok = self.tokens.get(mint)
        if tok is None or not tok.on_curve or not tok.tradeable():
            return
        f = tok.features(int(at))
        row = {"mint": mint, "t": int(at), "created_ms": tok.t0, "off": off, **f,
               "dev_hold_at": tok.dev_hold(), "dev_sold_at": tok.dev_sold, "price_at": tok.price()}
        for h in LABEL_HORIZONS:
            row[f"r{h}"] = float("nan")
            row[f"win{h}"] = float("nan")
        row["dump60"] = float("nan")
        row["mig"] = float("nan")
        idx = len(self.rows)
        self.rows.append(row)
        self.rows_by_mint.setdefault(mint, []).append(idx)
        lat = self.costs.latency("model", mint, off, "buy")
        self.push(at + lat, "label_buy", idx)
        for h in LABEL_HORIZONS:
            self.push(at + h * 1000, "label_price", (idx, h))
            self.push(at + h * 1000 + self.costs.latency("model", mint, off, h, "sell"), "label_sell", (idx, h))
        self.push(at + 60_000, "label_dump", idx)

    def _a_label_buy(self, at, idx) -> None:
        row = self.rows[idx]
        tok = self.tokens.get(row["mint"])
        if tok is None or not tok.on_curve or tok.price() > row["price_at"] * (1 + self.costs.slip_tol):
            row["_tokens"] = 0                              # the buy fails: a loss of the transaction fee
            return
        row["_tokens"] = C.curve_buy(STAKE, tok.vs, tok.vt, tok.rt, tok.fee_bps)

    def _a_label_price(self, at, data) -> None:
        idx, h = data
        row = self.rows[idx]
        tok = self.tokens.get(row["mint"])
        if tok is not None and tok.price() > 0 and row["price_at"] > 0:
            row[f"r{h}"] = math.log(tok.price() / row["price_at"])

    def _a_label_sell(self, at, data) -> None:
        idx, h = data
        row = self.rows[idx]
        tx = self.costs.tx_lamports()
        n = row.get("_tokens", 0)
        if not n:
            row[f"win{h}"] = 0.0
            row[f"net{h}"] = -tx / STAKE
            return
        v = self.sale_value(self.tokens.get(row["mint"]), n)
        if v is None:
            return                                           # completed, pool not seen: unknown, stays NaN
        net = (v - STAKE - 2 * tx) / STAKE
        row[f"net{h}"] = net
        row[f"win{h}"] = float(net > 0)

    def _a_label_dump(self, at, idx) -> None:
        row = self.rows[idx]
        tok = self.tokens.get(row["mint"])
        if tok is None or row["dev_hold_at"] <= 0:
            return
        row["dump60"] = float(tok.dev_sold - row["dev_sold_at"] >= DUMP * row["dev_hold_at"])

    # ------------------------------------------------------------ housekeeping
    def _a_evict(self, at, mint) -> None:
        tok = self.tokens.get(mint)
        if tok is None:
            return
        if mint in self.by_mint or at - tok.last_t < IDLE_MS:
            self.push(at + IDLE_MS, "evict", mint)
            return
        self._settle_mig(tok, at)
        del self.tokens[mint]
        self.entered.pop(mint, None)
        self.rows_by_mint.pop(mint, None)

    def _settle_mig(self, tok: Token, at: float) -> None:
        horizon = tok.t0 + MIG_LABEL_H * 3_600_000
        done = tok.complete_t is not None and tok.complete_t <= horizon
        known = done or at >= horizon
        for idx in self.rows_by_mint.get(tok.mint, ()):
            self.rows[idx]["mig"] = float(done) if known else float("nan")

    def finish(self, t_end: float) -> None:
        """End of data: run what is due, settle what can be settled; open positions stay open."""
        self.advance(t_end)
        for tok in self.tokens.values():
            self._settle_mig(tok, t_end)
        self.counts["open_at_end"] = sum(1 for p in self.positions.values() if p["state"] == "open")
        self.counts["pending_at_end"] = sum(1 for p in self.positions.values() if p["state"] == "pending")

    def drop_gapped(self) -> None:
        """Remove closed trades and decision rows whose window overlaps a gap in the record."""
        if not self.gaps:
            return

        def hit(a, b):
            return any(g0 < b and a < g1 for g0, g1 in self.gaps)
        before = len(self.closed)
        self.closed = [c for c in self.closed if not c.get("gap") and not hit(c["signal_ms"], c["exit_ms"])]
        self.counts["closed_dropped_gap"] += before - len(self.closed)
        before = len(self.rows)
        self.rows = [r for r in self.rows if not hit(r["created_ms"], r["t"] + 360_000)]
        self.counts["rows_dropped_gap"] += before - len(self.rows)


# ---------------------------------------------------------------- replaying the store

def feed_row(eng: Engine, table: str, r) -> None:
    """Feed one store row (a dict) to the engine."""
    if table == "trades":
        if r.get("quote") is not None:
            tok = eng.tokens.get(r["mint"])
            if tok is not None:
                tok.irregular = True
        eng.trade(r["t"], r["tx"], r["mint"], r["buy"], r["sol"] or 0, r["tok"] or 0, r["user"], r["vs"] or 0,
                  r["vt"] or 0, r["rs"] or 0, r["rt"] or 0, r["fb"], r["cfb"])
    elif table == "creates":
        eng.create(r["t"], r["tx"], r["mint"], r["creator"], r["vs"] or 0, r["vt"] or 0, r["rt"] or 0,
                   r.get("name") or "", r.get("symbol") or "", r.get("uri") or "", r.get("mayhem"),
                   r.get("cashback"), r.get("quote"))
    elif table == "other":
        k = r["kind"]
        if k == "complete":
            eng.complete(r["t"], r["mint"])
        elif k == "migrate":
            eng.migrate(r["t"], r["mint"], r["pool"], r["sol"], r["tok"])
        elif k == "gap":                                 # either stream: whatever overlaps it is dropped
            eng.gap(r["t0"] or r["t"], r["t"])
    elif table == "amm":
        if r.get("mint"):
            eng.amm(r["t"], r["mint"], r["buy"], r["base"], r["quote"], r["pb"], r["pq"], r["lpb"], r["pfb"],
                    r["cfb"])
    elif table == "meta":
        eng.meta(r["t"], r["mint"], {k: r.get(k) for k in ("ok", "twitter", "telegram", "website", "desc_len",
                                                             "image")})


ORDER = ("creates", "trades", "other", "amm", "meta")


def day_events(day: str, root=None, chunk: int = 200_000):
    """(table, row dict) of one recorded day in receive order: time, then the
    collector's transaction number, then creation before trades before the rest."""
    import polars as pl
    from . import store
    frames = {tb: store.read(tb, [day], root) for tb in ORDER}
    keys = []
    for o, tb in enumerate(ORDER):
        df = frames[tb]
        if df.height == 0:
            continue
        tx = pl.col("tx").fill_null(0) if "tx" in df.columns else pl.lit(0, dtype=pl.Int64)
        keys.append(df.select(pl.col("t").fill_null(0).alias("t"), tx.cast(pl.Int64).alias("tx"),
                              pl.lit(o, dtype=pl.Int32).alias("o"), pl.int_range(df.height, dtype=pl.Int64).alias("i")))
    if not keys:
        return
    allk = pl.concat(keys).sort(["t", "tx", "o", "i"])
    for s in range(0, allk.height, chunk):
        part = allk.slice(s, chunk)
        os_, is_ = part["o"].to_list(), part["i"].to_list()
        got: dict[int, dict[int, dict]] = {}
        for o in set(os_):
            idx = [i for oo, i in zip(os_, is_) if oo == o]
            rows = frames[ORDER[o]][idx].to_dicts()
            got[o] = dict(zip(idx, rows))
        for o, i in zip(os_, is_):
            yield ORDER[o], got[o][i]


def replay(day_list: list[str], eng: Engine, root=None, progress=None) -> Engine:
    """Feed recorded days to the engine in order; settle at the end of the record."""
    last = 0
    for day in day_list:
        n = 0
        for table, row in day_events(day, root):
            feed_row(eng, table, row)
            last = max(last, row.get("t") or 0)
            n += 1
        if progress:
            progress(day, n)
    eng.finish(last + 1)
    eng.drop_gapped()
    return eng
