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

import numpy as np

from . import curve as C
from . import pipeline as P
from . import strategies as S
from . import wallets as W
from .categorize import CAT_FEATURES
from .categorize import empty_features as no_cats
from .tokens import FEATURES, CreatorBook, Token

OFFSETS = (3, 10, 30, 60, 120, 300)          # model decision points, seconds after creation
LABEL_HORIZONS = (30, 300)                    # the round-trip labels, seconds
SELL10_HORIZONS = (10, 30)                    # creator or top-10 holder sells within N s (plan addendum 2)
UP_HORIZONS = (10, 30, 120)                   # price N s after the landing above the landing price
SELL10_SHARE = 0.25
ALL_FEATURES = FEATURES + W.WALLET_FEATURES + CAT_FEATURES
MIG_LABEL_H = 6                               # "completes its curve within 6 hours"
EVICT_AGE_MS = (MIG_LABEL_H * 3600 + 120) * 1000
IDLE_MS = 30 * 60_000
STUCK_RETRY_MS, STUCK_MAX_MS = 2_000, 10 * 60_000
STAKE = int(S.STAKE_SOL * C.LAMPORTS)
DUMP = 0.5                                    # "the dev dumps": sells half or more of what it held at t


def model_rule(rule: S.Rule) -> S.Rule:
    """The same rule with the model filter in front (a separate book)."""
    return dataclasses.replace(rule, name=rule.name + "+model", p={**rule.p, "model": True, "base": rule.name},
                               label=rule.label + "; model filter")


def variant(rule: S.Rule, suffix: str) -> S.Rule:
    """The same rule under another name (for a stress case with its own costs); its
    latency draws are the base rule's, scaled."""
    return dataclasses.replace(rule, name=f"{rule.name}@{suffix}", p={**rule.p, "base": rule.name})


def base_name(r: S.Rule) -> str:
    return r.p.get("base") or r.name


class Engine:
    def __init__(self, rules: list[S.Rule] | None = None, costs: C.Costs | None = None,
                 book: CreatorBook | None = None, decisions: bool = False, model=None, on_close=None,
                 entry_from: int | None = None, entry_until: int | None = None,
                 rule_costs: dict[str, C.Costs] | None = None, strategies: list | None = None,
                 wallets: W.WalletBook | None = None, cats=None, models: dict | None = None, kill=None):
        self.rules = list(S.RULES if rules is None else rules)
        self.costs = costs or C.Costs()
        self.rule_costs = rule_costs or {}
        self.book = book or CreatorBook()
        self.wallets = wallets if wallets is not None else W.WalletBook()
        self.cats = cats                                 # categorize.CategoryIndex or None
        self.models = models or {}                       # label -> model.Fitted, for the pipeline's filters and exits
        self.decisions_on = decisions
        self.model = model                               # .allow(rule, features) -> (bool, prob)
        self.on_close = on_close
        self.entry_from, self.entry_until = entry_from, entry_until
        self.pipes: list[P.Pipeline] = []
        if strategies:
            self.pipes.append(P.Pipeline(self, list(strategies), P.PaperExecutor(), name="paper", kill=kill))
        self._index_rules()
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
        self.rows = Rows()
        self.rows_by_mint: dict[str, list[int]] = {}
        self.gaps: list[tuple[int, int]] = []
        self.counts: Counter = Counter()
        self.next_pid = 0

    def _index_rules(self) -> None:
        """The rules and every pipe's strategies, by entry kind (a strategy signals once for all pipes)."""
        allr = list(self.rules)
        names = {r.name for r in allr}
        for pipe in self.pipes:
            for s in pipe.strats.values():
                if s.name not in names:
                    allr.append(s)
                    names.add(s.name)
        self.rule_by = {r.name: r for r in allr}
        self.by_entry: dict[str, list[S.Rule]] = {}
        for r in allr:
            self.by_entry.setdefault(r.entry, []).append(r)

    def add_pipe(self, pipe: P.Pipeline) -> P.Pipeline:
        self.pipes.append(pipe)
        self._index_rules()
        return pipe

    def new_pid(self) -> int:
        pid = self.next_pid
        self.next_pid += 1
        return pid

    # ------------------------------------------------------------ what a decision may know
    def features(self, tok: Token, t: int) -> dict:
        """The token's own features, the wallet reputation of its early buyers and its name's
        category, all as known at t."""
        f = tok.features(t)
        if tok.early is not None:
            f.update(tok.early.features(self.wallets.get(tok.creator)))
        else:
            f.update(W.empty_features())
        f.update(self.cats.features(tok.name, tok.symbol, t) if self.cats is not None else no_cats())
        return f

    def prob(self, label: str, f: dict) -> tuple[float, float] | None:
        """(calibrated probability, training base rate) of a label, None without a trained model."""
        m = self.models.get(label)
        if m is None or m.booster is None:
            return None
        x = np.array([[float(f.get(k, math.nan)) for k in m.features]], dtype=float)
        return float(m.predict(x)[0]), float(m.base)

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
               quote=None, user=None) -> None:
        self.advance(t)
        if mint in self.tokens:
            return
        hist = self.book.snapshot(creator, t)
        self.book.created(creator, t)
        tok = Token(mint, creator, t, tx, vs, vt, rt, hist, name, symbol, uri, mayhem, cashback, quote, user)
        tok.early = W.EarlyBuyers()
        self.tokens[mint] = tok
        self.counts["tokens"] += 1
        self.push(t, "signal_create", mint)
        for r in self.by_entry.get("checkpoint", ()):
            self.push(t + r.p["w_s"] * 1000, "checkpoint", (mint, r.name))
        if self.decisions_on:
            for off in OFFSETS:
                self.push(t + off * 1000, "decide", (mint, off))
        self.push(t + EVICT_AGE_MS, "evict", mint)

    def trade(self, t, tx, mint, buy, sol, tok_amt, user, vs, vt, rs, rt, fb, cfb, slot=None) -> None:
        self.advance(t)
        tok = self.tokens.get(mint)
        if tok is None:
            return
        tok.trade(t, tx, buy, sol, tok_amt, user, vs, vt, rs, rt, fb, cfb, self.book, slot)
        if tok.early is not None and user not in tok.devs:
            if buy:
                if t - tok.t0 <= W.EARLY_S * 1000:
                    tok.early.add(user, t, self.wallets, self.book)
            else:
                tok.early.sold(user, t, self.wallets)
        for pipe in self.pipes:
            pipe.exec.on_trade("trades", {"t": t, "mint": mint, "buy": buy, "sol": sol, "tok": tok_amt, "user": user,
                                          "fee_bps": tok.fee_bps})
        if tok.tradeable():
            for r in self.by_entry.get("momentum", ()):
                if r.wants_momentum(tok, t):
                    self.signal(r, tok, t)
            for r in self.by_entry.get("progress", ()):
                if r.wants_progress(tok, t):
                    self.signal(r, tok, t)
        for pid in tuple(self.by_mint.get(mint, ())):
            self.check_exit(pid, t)
        for pipe in self.pipes:
            pipe.on_trade(tok, t, buy, user, tok_amt, "curve")

    def complete(self, t, mint) -> None:
        self.advance(t)
        tok = self.tokens.get(mint)
        if tok is not None:
            if tok.complete_t is None and tok.early is not None:
                for w in tok.early.wallets:
                    self.wallets.completed(w)
            tok.completed(t, self.book)

    def migrate(self, t, mint, pool, sol, tok_amt) -> None:
        self.advance(t)
        tok = self.tokens.get(mint)
        if tok is None:
            return
        if tok.complete_t is None:
            if tok.early is not None:
                for w in tok.early.wallets:
                    self.wallets.completed(w)
            tok.completed(t, self.book)
        tok.migrated(t, pool, sol, tok_amt)
        tok.last_t = t
        for r in self.by_entry.get("migration", ()):
            self.push(t + r.p["delay_s"] * 1000, "signal_rule", (mint, r.name))

    def amm(self, t, mint, buy, base, quote, pb, pq, lpb, pfb, cfb, slot=None, user=None) -> None:
        self.advance(t)
        tok = self.tokens.get(mint)
        if tok is None:
            return
        tok.amm(buy, base or 0, quote or 0, pb, pq, lpb, pfb, cfb, slot, user, int(t))
        tok.last_t = t
        for pipe in self.pipes:
            pipe.exec.on_trade("amm", {"t": t, "mint": mint, "buy": buy, "sol": quote or 0, "tok": base or 0,
                                       "user": user, "fee_bps": tok.amm_fee_bps})
        for pid in tuple(self.by_mint.get(mint, ())):
            self.check_exit(pid, t)
        for pipe in self.pipes:
            pipe.on_trade(tok, t, buy, user or "", base or 0, "pool")

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
        for pipe in self.pipes:
            pipe.mark_gap()

    def _a_pipe(self, at, data) -> None:
        """An action of a pipeline or its paper executor (a landing, a time stop)."""
        obj, meth, arg = data
        getattr(obj, meth)(at, arg)

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
        if P.is_strategy(r):
            for pipe in self.pipes:
                if pipe.has(r.name):
                    pipe.signal(r, tok, t)
            return
        self.counts["signals"] += 1
        if r.family != "E" and not tok.tradeable():
            self.skipped[(r.name, "not a plain SOL curve")] += 1
            return
        if r.family == "E" and (tok.quote is not None or tok.mayhem or tok.irregular):
            self.skipped[(r.name, "not a plain SOL pool")] += 1
            return
        if self.open_n[r.name] >= S.MAX_OPEN:
            self.skipped[(r.name, "book full")] += 1
            return
        prob = None
        if r.p.get("model"):
            if self.model is None:
                self.skipped[(r.name, "no model")] += 1
                return
            ok, prob = self.model.allow(r, self.features(tok, int(t)))
            if not ok:
                self.skipped[(r.name, "model")] += 1
                return
        pid = self.next_pid
        self.next_pid += 1
        lat = self.cost_of(r.name).latency(base_name(r), tok.mint, "buy")
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
        c = self.cost_of(r.name)
        tx = c.tx_lamports()
        why = None
        got = 0
        if tok is None:
            why = "token gone"
        elif r.family == "E":
            if not tok.pq or not tok.pb:
                why = "no pool state"
            else:
                pr = C.price(tok.pq, tok.pb)
                if pr > p["signal_price"] * (1 + c.slip_tol):
                    why = "slippage"
                else:
                    got = C.pool_buy(STAKE, tok.pb, tok.pq, max(tok.amm_fee_bps, c.fee_bps_floor))
        elif not tok.on_curve:
            why = "curve completed before the buy landed"
        else:
            pr = tok.price()
            if pr > p["signal_price"] * (1 + c.slip_tol):
                why = "slippage"
            else:
                got = C.curve_buy(STAKE, tok.vs, tok.vt, tok.rt, max(tok.fee_bps, c.fee_bps_floor))
        if why is None and got <= 0:
            why = "nothing filled"
        if why is not None:
            self._drop(p)
            f = {"rule": p["rule"], "mint": p["mint"], "signal_ms": p["signal_ms"], "land_ms": int(at),
                 "why": why, "pnl_sol": -tx / C.LAMPORTS}
            self.failed.append(f)
            return
        p.update(state="open", tokens=got, land_ms=int(at), entry_price=tok.price() if r.family != "E" else
                 C.price(tok.pq, tok.pb), cost_l=STAKE + tx, exiting=False, breaks0=tok.breaks)
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
    def cost_of(self, rule_name: str) -> C.Costs:
        return self.rule_costs.get(rule_name, self.costs)

    def sale_value(self, tok: Token | None, tokens: int, c: C.Costs | None = None) -> int | None:
        """Lamports a sale of `tokens` would bring now (after the fee), None if it cannot be sold now."""
        floor = (c or self.costs).fee_bps_floor
        if tok is None:
            return 0
        if tok.on_curve:
            return C.curve_sell(tokens, tok.vs, tok.vt, max(tok.fee_bps, floor))
        if tok.pq and tok.pb:
            return C.pool_sell(tokens, tok.pb, tok.pq, max(tok.amm_fee_bps, floor))
        return None

    def check_exit(self, pid: int, t: float) -> None:
        p = self.positions.get(pid)
        if p is None or p["state"] != "open" or p["exiting"]:
            return
        r = self._rule(p["rule"])
        v = self.sale_value(self.tokens.get(p["mint"]), p["tokens"], self.cost_of(r.name))
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
        r = self._rule(p["rule"])
        lat = self.cost_of(p["rule"]).latency(base_name(r) if r else p["rule"], p["mint"], "sell")
        self.push(t + lat, "land_sell", (p["pid"], int(t)))

    def _a_land_sell(self, at, data) -> None:
        pid, t_sig = data
        p = self.positions.get(pid)
        if p is None:
            return
        tok = self.tokens.get(p["mint"])
        c = self.cost_of(p["rule"])
        v = self.sale_value(tok, p["tokens"], c)
        if v is None:
            if at - t_sig < STUCK_MAX_MS:                  # curve complete, pool not seen yet: try again
                self.push(at + STUCK_RETRY_MS, "land_sell", (pid, t_sig))
                return
            v, p["exit_why"] = 0, "stuck"
        tx = c.tx_lamports()
        pnl = v - STAKE - 2 * tx
        rec = {k: p.get(k) for k in ("rule", "family", "mint", "name", "symbol", "created_ms", "signal_ms",
                                     "land_ms", "exit_signal_ms", "exit_why", "prob", "gap", "age_s", "progress",
                                     "signal_price", "entry_price")}
        rec.update(exit_ms=int(at), exit_price=tok.price() if tok else 0.0, proceeds_sol=v / C.LAMPORTS,
                   pnl_sol=pnl / C.LAMPORTS, ret=pnl / STAKE, hold_s=(at - p["land_ms"]) / 1000,
                   dev_dumped=bool(tok and tok.dev_dumped and not p.get("dev_dumped_at_entry")),
                   breaks=(tok.breaks - p.get("breaks0", 0)) if tok else 0,
                   migrated=bool(tok and tok.complete_t is not None and tok.complete_t <= at),
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
        f = self.features(tok, int(at))
        row = {"mint": mint, "t": int(at), "created_ms": tok.t0, "off": off, **f,
               "dev_hold_at": tok.dev_hold(), "dev_sold_at": tok.dev_sold, "price_at": tok.price(),
               "_watch": tok.sell_watch()}
        idx = self.rows.new(row)
        self.rows_by_mint.setdefault(mint, []).append(idx)
        lat = self.costs.latency("model", mint, off, "buy")
        self.push(at + lat, "label_buy", idx)
        for h in LABEL_HORIZONS:
            self.push(at + h * 1000, "label_price", (idx, h))
            self.push(at + h * 1000 + self.costs.latency("model", mint, off, h, "sell"), "label_sell", (idx, h))
        for h in SELL10_HORIZONS:
            self.push(at + h * 1000, "label_sell10", (idx, h))
        self.push(at + 60_000, "label_dump", idx)
        last = max(max(LABEL_HORIZONS) * 1000 + self.costs.lat_hi_ms, max(UP_HORIZONS) * 1000 + self.costs.lat_hi_ms)
        self.push(at + last + 1_000, "label_pack", idx)

    def _a_label_sell10(self, at, data) -> None:
        """The dev or a top-10 holder at t sold a quarter or more of what it held at t."""
        idx, h = data
        row = self.rows.get(idx)
        tok = self.tokens.get(row.get("mint"))
        watch = row.get("_watch") or {}
        if tok is None or not watch:
            return
        hit = any(tok.sold.get(w, 0) - s0 >= SELL10_SHARE * h0 for w, (h0, s0) in watch.items())
        row[f"sell10_{h}"] = float(hit)

    def _a_label_up(self, at, data) -> None:
        idx, h = data
        row = self.rows.get(idx)
        tok = self.tokens.get(row.get("mint"))
        e = row.get("_entry_p")
        if tok is not None and e and e > 0 and tok.price() > 0:
            row[f"up{h}"] = float(tok.price() > e)

    def _a_label_pack(self, at, idx) -> None:
        self.rows.pack(idx)

    def _a_label_buy(self, at, idx) -> None:
        row = self.rows.get(idx)
        tok = self.tokens.get(row["mint"])
        if tok is not None and tok.price() > 0:
            row["_entry_p"] = tok.price()                   # the price at the landing, for the up labels
            for h in UP_HORIZONS:
                self.push(at + h * 1000, "label_up", (idx, h))
        if tok is None or not tok.on_curve or tok.price() > row["price_at"] * (1 + self.costs.slip_tol):
            row["_tokens"] = 0                              # the buy fails: a loss of the transaction fee
            return
        row["_tokens"] = C.curve_buy(STAKE, tok.vs, tok.vt, tok.rt, tok.fee_bps)

    def _a_label_price(self, at, data) -> None:
        idx, h = data
        row = self.rows.get(idx)
        tok = self.tokens.get(row["mint"])
        if tok is not None and tok.price() > 0 and row["price_at"] > 0:
            row[f"r{h}"] = math.log(tok.price() / row["price_at"])

    def _a_label_sell(self, at, data) -> None:
        idx, h = data
        row = self.rows.get(idx)
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
        row = self.rows.get(idx)
        tok = self.tokens.get(row["mint"])
        if tok is None or row["dev_hold_at"] <= 0:
            return
        row["dump60"] = float(tok.dev_sold - row["dev_sold_at"] >= DUMP * row["dev_hold_at"])

    # ------------------------------------------------------------ housekeeping
    def _a_evict(self, at, mint) -> None:
        tok = self.tokens.get(mint)
        if tok is None:
            return
        if mint in self.by_mint or at - tok.last_t < IDLE_MS or any(mint in p.by_mint for p in self.pipes):
            self.push(at + IDLE_MS, "evict", mint)
            return
        self._settle_mig(tok, at)
        self._quality(tok)
        del self.tokens[mint]
        self.entered.pop(mint, None)
        self.rows_by_mint.pop(mint, None)

    def _quality(self, tok: Token) -> None:
        """How complete the record of plain curves is: slots whose trades did not chain up."""
        if tok.tradeable():
            self.counts["curve_trades"] += tok.n_buys + tok.n_sells
            self.counts["curve_breaks"] += tok.breaks + (0 if tok.slot_ok else 1)
            self.counts["curve_tokens"] += 1
            self.counts["curve_tokens_broken"] += int(tok.breaks > 0 or not tok.slot_ok)

    def _settle_mig(self, tok: Token, at: float) -> None:
        horizon = tok.t0 + MIG_LABEL_H * 3_600_000
        done = tok.complete_t is not None and tok.complete_t <= horizon
        known = done or at >= horizon
        for idx in self.rows_by_mint.get(tok.mint, ()):
            self.rows.set(idx, "mig", float(done) if known else float("nan"))

    def finish(self, t_end: float) -> None:
        """End of data: run what is due, settle what can be settled; open positions stay open."""
        self.advance(t_end)
        for tok in self.tokens.values():
            self._settle_mig(tok, t_end)
            self._quality(tok)
        self.rows.pack_all()
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
        self.counts["rows_dropped_gap"] += self.rows.drop(self.gaps, 360_000)

    def table(self) -> dict:
        """The decision rows as columns (numpy arrays), for the model."""
        return self.rows.frame()

    def row_dicts(self) -> list[dict]:
        fr = self.rows.frame()
        n = len(fr["t"])
        return [{c: float(v[i]) for c, v in fr.items()} for i in range(n)]


ROW_COLS = (["t", "created_ms", "off"] + ALL_FEATURES
            + [f"{k}{h}" for h in LABEL_HORIZONS for k in ("r", "win", "net")] + ["dump60", "mig"]
            + [f"sell10_{h}" for h in SELL10_HORIZONS] + [f"up{h}" for h in UP_HORIZONS])
_COL = {c: i for i, c in enumerate(ROW_COLS)}
CHUNK = 65_536


class Rows:
    """Decision rows: a dict while its labels come in (about five minutes), then packed into a
    float array, so a fortnight of rows fits in a few hundred MB. The 6-hour completion label
    is written into the packed row when the token settles."""

    def __init__(self):
        self.pending: dict[int, dict] = {}
        self.chunks: list[np.ndarray] = []
        self.n = 0
        self.dropped: np.ndarray | None = None

    def __len__(self) -> int:
        return self.n

    def new(self, row: dict) -> int:
        idx = self.n
        self.n += 1
        self.pending[idx] = row
        return idx

    def get(self, idx: int) -> dict:
        return self.pending.get(idx) or {}

    def _arr(self, idx: int) -> np.ndarray:
        k = idx // CHUNK
        while len(self.chunks) <= k:
            self.chunks.append(np.full((CHUNK, len(ROW_COLS)), np.nan))
        return self.chunks[k]

    def set(self, idx: int, col: str, v: float) -> None:
        p = self.pending.get(idx)
        if p is not None:
            p[col] = v
        else:
            self._arr(idx)[idx % CHUNK, _COL[col]] = v

    def pack(self, idx: int) -> None:
        row = self.pending.pop(idx, None)
        if row is None:
            return
        self._arr(idx)[idx % CHUNK] = [float(row[c]) if row.get(c) is not None else np.nan for c in ROW_COLS]

    def pack_all(self) -> None:
        for idx in list(self.pending):
            self.pack(idx)

    def drop(self, gaps: list[tuple[int, int]], tail_ms: int) -> int:
        """Mark rows whose window [created, t + tail] overlaps a gap; returns how many."""
        self.pack_all()
        fr = self.frame(raw=True)
        a, b = fr["created_ms"], fr["t"] + tail_ms
        bad = np.zeros(len(a), dtype=bool)
        for g0, g1 in gaps:
            bad |= (g0 < b) & (a < g1)
        self.dropped = bad if self.dropped is None else (self.dropped | bad)
        return int(bad.sum())

    def frame(self, raw: bool = False) -> dict[str, np.ndarray]:
        self.pack_all()
        A = np.vstack(self.chunks)[:self.n] if self.chunks else np.zeros((0, len(ROW_COLS)))
        if not raw and self.dropped is not None:
            A = A[~self.dropped[:len(A)]]
        return {c: A[:, i] for c, i in _COL.items()}


# ---------------------------------------------------------------- replaying the store

def feed_row(eng: Engine, table: str, r) -> None:
    """Feed one store row (a dict) to the engine."""
    if table == "trades":
        if r.get("quote") is not None:
            tok = eng.tokens.get(r["mint"])
            if tok is not None:
                tok.irregular = True
        eng.trade(r["t"], r["tx"], r["mint"], r["buy"], r["sol"] or 0, r["tok"] or 0, r["user"], r["vs"] or 0,
                  r["vt"] or 0, r["rs"] or 0, r["rt"] or 0, r["fb"], r["cfb"], r.get("slot"))
    elif table == "creates":
        eng.create(r["t"], r["tx"], r["mint"], r["creator"], r["vs"] or 0, r["vt"] or 0, r["rt"] or 0,
                   r.get("name") or "", r.get("symbol") or "", r.get("uri") or "", r.get("mayhem"),
                   r.get("cashback"), r.get("quote"), r.get("user"))
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
                    r["cfb"], r.get("slot"), r.get("user"))
    elif table == "meta":
        eng.meta(r["t"], r["mint"], {k: r.get(k) for k in ("ok", "twitter", "telegram", "website", "desc_len",
                                                             "image")})


ORDER = ("creates", "trades", "other", "amm", "meta")


def day_events(day: str, root=None, chunk: int = 200_000):
    """(table, row dict) of one recorded day in CHAIN order: by slot, each event timed by its
    slot (store.slot_times: the earliest receive time of that slot or a later one), then
    receive time, the collector's transaction number, creation before trades before the
    rest. A row's "t" is that slot time; its receive time is kept as "recv_t". Rows
    without a slot (gaps, metadata) keep their receive time."""
    import polars as pl
    from . import store
    frames = {tb: store.read(tb, [day], root) for tb in ORDER}
    pairs = pl.concat([frames[tb].select(pl.col("slot"), pl.col("t")) for tb in ORDER
                       if frames[tb].height and "slot" in frames[tb].columns])
    pairs = pairs.filter(pl.col("slot").is_not_null() & pl.col("t").is_not_null())
    if pairs.height:
        first = pairs.group_by("slot").agg(pl.col("t").min().alias("ct")).sort("slot", descending=True)
        first = first.with_columns(pl.col("ct").cum_min()).with_columns(pl.col("slot").cast(pl.Int64))
    else:
        first = pl.DataFrame({"slot": [], "ct": []}, schema={"slot": pl.Int64, "ct": pl.Int64})
    keys = []
    for o, tb in enumerate(ORDER):
        df = frames[tb]
        if df.height == 0:
            continue
        slot = pl.col("slot").cast(pl.Int64) if "slot" in df.columns else pl.lit(None, dtype=pl.Int64)
        tx = pl.col("tx").fill_null(0).cast(pl.Int64) if "tx" in df.columns else pl.lit(0, dtype=pl.Int64)
        k = df.select(pl.col("t").fill_null(0).alias("rt"), slot.alias("slot"), tx.alias("tx"),
                      pl.lit(o, dtype=pl.Int32).alias("o"), pl.int_range(df.height, dtype=pl.Int64).alias("i"))
        k = k.join(first, on="slot", how="left").with_columns(pl.coalesce("ct", "rt").alias("ct"))
        keys.append(k)
        frames[tb] = df.with_columns(pl.col("t").alias("recv_t"))
    if not keys:
        return
    allk = pl.concat(keys).sort(["ct", "slot", "rt", "tx", "o", "i"], nulls_last=True)
    for s in range(0, allk.height, chunk):
        part = allk.slice(s, chunk)
        os_, is_, cts = part["o"].to_list(), part["i"].to_list(), part["ct"].to_list()
        got: dict[int, dict[int, dict]] = {}
        for o in set(os_):
            idx = [i for oo, i in zip(os_, is_) if oo == o]
            rows = frames[ORDER[o]][idx].to_dicts()
            got[o] = dict(zip(idx, rows))
        for o, i, ct in zip(os_, is_, cts):
            row = got[o][i]
            row["t"] = ct
            yield ORDER[o], row


def replay(day_list: list[str], eng: Engine, root=None, progress=None, until_ms: int | None = None) -> Engine:
    """Feed recorded days to the engine in order (up to until_ms); settle at the end."""
    last = 0
    done = False
    for day in day_list:
        n = 0
        for table, row in day_events(day, root):
            t = row.get("t") or 0
            if until_ms is not None and t > until_ms:
                done = True
                break
            feed_row(eng, table, row)
            last = max(last, t)
            n += 1
        if progress:
            progress(day, n)
        if done:
            break
    eng.finish(last + 1)
    eng.drop_gapped()
    return eng
