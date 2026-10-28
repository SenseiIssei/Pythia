"""E1 (results/slippage_e1_prereg.md): slippage bounds for pump.fun buys and sales, on realistic paper. PAPER ONLY:
nothing a live bot, its sizing, a wallet or the engine reads changes; the live bounds are the owner's.

    python -m lab.pumpfun_rt.slippage_e1 [--out results/slippage_e1.md] [--until 2026-10-28T19:40]

The live bot's rules (RULES) as realistic books (realistic.RealExecutor) per bound pair of the fixed grid (PAIRS: a
buy bound with the live sales, or the live buy bound with a sale bound) and per view of sandwiches (none: the engine as
it is; sandwich: every profitable sandwich taken, the exact constant-product arithmetic with the coin's fee, two
transactions at the fit's fee and tip for the attacker, our order never past its bound). A pool buy accepts no fewer
tokens than the signal's quote / (1 + b) (6040 at the landing with its fee, the pre-send skip at b), a curve buy a cost
of the stake x (1 + min(b, SLIP_TOL)), a sale no less than max(the rule's floor, its value at the decision / (1 + s));
a failed sale waits the live backoff, and after SELL_MAX_FAILS in a row goes without a bound (the owner's hand sale).

Replay (run): the collector's recorded days through sim, per (rule, pair, view) a measuring book at 0.1 SOL on every
signal (C) and one with the live sizing on a 0.55 SOL paper wallet (W). Forward (shadow_books, forward): the sandwich
view with the live sizing as `<rule>@e1_<pair>` in the shadow, read from the paper ledger and failed buys; the daily
realistic job writes their table into realistic.md. 60 trials in R5's registry, counted only, registered before any
number.
"""

from __future__ import annotations

import argparse
import collections
import dataclasses
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from scipy.optimize import minimize_scalar

from .. import metrics
from . import curve as C
from . import pipeline as P
from . import realistic as R

PREREG = "results/slippage_e1_prereg.md"
OUT = Path(__file__).resolve().parents[2] / "results" / "slippage_e1.md"
RULES = ("P_pool0", "P_pool0_wait", "P_cmig_model")   # the live bot's rules; P_pool0_wait the live one now
TWIN = R.TWIN
LIVE = "b60"
# name -> (buy bound, sale bound or None for the rule's own floor)
PAIRS = {"b02": (0.02, None), "b05": (0.05, None), "b10": (0.10, None), "b20": (0.20, None), "b30": (0.30, None),
         "b60": (R.POOL_BUY_TOL, None), "b100": (1.00, None),
         "s05": (R.POOL_BUY_TOL, 0.05), "s15": (R.POOL_BUY_TOL, 0.15), "s30": (R.POOL_BUY_TOL, 0.30)}
BUYS = ("b02", "b05", "b10", "b20", "b30", "b60", "b100")
SALES = ("b60", "s05", "s15", "s30")
VIEWS = ("none", "sandwich")
FORWARD_VIEW = "sandwich"
SELL_MAX_FAILS = 6                        # live_exec.SELL_MAX_FAILS: the live bot then gives the position up
SELL_BACKOFF_MAX_S = 60                   # live_exec.SELL_BACKOFF_MAX_S
WORSE = 0.02                              # "filled worse than the signal by more than 2 %"
DRAWS, SEED = 2_000, 0
TAG = "@e1_"


def trials() -> list[dict]:
    return [{"id": f"hand:e1:{r}:{k}:{v}", "family": "hand", "n": 1, "sharpe": None, "source": PREREG}
            for r in RULES for k in PAIRS for v in VIEWS]


def backoff_ms(fails: int) -> int:
    """live_exec.backoff_ms: the wait before the next try of a sale that failed `fails` times in a row."""
    return int(min(SELL_BACKOFF_MAX_S, 2 ** max(0, fails - 1)) * 1000)


# ---------------------------------------------------------------- the sandwich arithmetic

# Constant product on (s: lamports, t: raw tokens), the fee on top of a buy and off a sale's proceeds, as
# curve.curve_buy / pool_buy and curve_sell / pool_sell; the fee leaves the reserves. Floats throughout.

def _buy(lam: float, s: float, t: float, f: float) -> tuple[float, float, float]:
    net = lam / (1 + f)
    out = t * net / (s + net)
    return out, s + net, t - out


def _sell(k: float, s: float, t: float, f: float) -> tuple[float, float, float]:
    gross = s * k / (t + k)
    return gross * (1 - f), s - gross, t + k


def _cost(k: float, s: float, t: float, f: float) -> float:
    """Lamports, fee included, to buy exactly k tokens."""
    return math.inf if k >= t else s * k / (t - k) * (1 + f)


def _best(profit, ok, hi: float) -> tuple[float, float]:
    """(z, profit) of the attacker's best size in (0, z_max]; z_max the largest z <= hi that keeps our order in its
    bound (ok(z)), by bisection; then a geometric grid and a bounded refinement around its best point."""
    if ok(hi):
        zmax = hi
    else:
        lo, top = 0.0, hi
        for _ in range(100):
            mid = (lo + top) / 2
            lo, top = (mid, top) if ok(mid) else (lo, mid)
        zmax = lo
    if zmax <= 0:
        return 0.0, -math.inf
    zs = zmax * np.geomspace(1e-7, 1.0, 141)
    ps = [profit(z) for z in zs]
    i = int(np.argmax(ps))
    a, b = zs[max(0, i - 1)], zs[min(len(zs) - 1, i + 1)]
    if b > a:
        r = minimize_scalar(lambda z: -profit(z), bounds=(a, b), method="bounded", options={"xatol": 1.0})
        if r.success and ok(r.x) and -r.fun > ps[i]:
            return float(r.x), float(-r.fun)
    return float(zs[i]), float(ps[i])


def sandwich_buy(spend: int, s: int, t: int, fee_bps: int, least: int, cost_l: int) -> tuple[int, int]:
    """A buy spending `spend` that accepts no fewer than `least` tokens, sandwiched: the attacker buys x before it and
    sells what it got after it. (our tokens, the attacker's profit in lamports after cost_l); our tokens as without
    an attacker when no x pays."""
    f = fee_bps / 10_000
    plain = _buy(spend, s, t, f)[0]

    def ours(x):
        a, s1, t1 = _buy(x, s, t, f)
        return a, _buy(spend, s1, t1, f)

    def profit(x):
        a, (g, s2, t2) = ours(x)
        return _sell(a, s2, t2, f)[0] - x - cost_l

    z, p = _best(profit, lambda x: ours(x)[1][0] >= least, 20.0 * s)
    if p <= 0:
        return int(plain), 0
    return max(int(least), int(ours(z)[1][0])), int(p)


def sandwich_curve_buy(want: int, s: int, t: int, fee_bps: int, cap: int, cost_l: int) -> tuple[int, int]:
    """A curve buy of exactly `want` tokens for at most `cap` lamports, sandwiched: (our cost, the attacker's
    profit); our cost as without an attacker when no x pays."""
    f = fee_bps / 10_000
    plain = _cost(want, s, t, f)

    def ours(x):
        a, s1, t1 = _buy(x, s, t, f)
        c = _cost(want, s1, t1, f)
        return a, c, s1 + c / (1 + f), t1 - want

    def profit(x):
        a, c, s2, t2 = ours(x)
        return -math.inf if not math.isfinite(c) else _sell(a, s2, t2, f)[0] - x - cost_l

    z, p = _best(profit, lambda x: ours(x)[1] <= cap, 20.0 * s)
    if p <= 0:
        return int(math.ceil(plain)), 0
    return min(int(cap), int(math.ceil(ours(z)[1]))), int(p)


def sandwich_sell(tokens: int, s: int, t: int, fee_bps: int, min_out: int, cost_l: int) -> tuple[int, int]:
    """A sale of `tokens` that accepts no less than `min_out`, sandwiched: the attacker sells y tokens before it and
    buys them back after it. (our proceeds, the attacker's profit); our proceeds as without an attacker when no y
    pays."""
    f = fee_bps / 10_000
    plain = _sell(tokens, s, t, f)[0]

    def ours(y):
        a, s1, t1 = _sell(y, s, t, f)
        return a, _sell(tokens, s1, t1, f)

    def profit(y):
        a, (v, s2, t2) = ours(y)
        return a - _cost(y, s2, t2, f) - cost_l

    z, p = _best(profit, lambda y: ours(y)[1][0] >= min_out, 20.0 * t)
    if p <= 0:
        return int(plain), 0
    return max(int(min_out), int(ours(z)[1][0])), int(p)


# ---------------------------------------------------------------- the books

class BoundExecutor(R.RealExecutor):
    """A realistic executor with a bound pair of the grid and a view of sandwiches."""

    def __init__(self, model: R.Model, wallet: R.PaperWallet | None = None, pair: str = LIVE, view: str = "none"):
        super().__init__(model, wallet)
        self.pair, self.view = pair, view
        self.buy_tol, self.sale_tol = PAIRS[pair]
        self.fails: dict[int, int] = {}                   # pid -> failed sales in a row
        self.given_up = 0
        self.sw = {"buys": 0, "buy_l": 0, "sales": 0, "sale_l": 0}   # sandwiches: count, what they took

    def curve_cap(self, o: P.Order) -> int:
        spend = o.stake_l or int(o.limit_l / (1 + C.SLIP_TOL))
        return min(o.limit_l, int(spend * (1 + min(self.buy_tol, C.SLIP_TOL))))

    def sell(self, o: P.Order) -> None:
        n = self.fails.get(o.pid, 0)
        if n >= SELL_MAX_FAILS:                          # stuck live: the owner sells it by hand, no bound
            if n == SELL_MAX_FAILS:
                self.given_up += 1
                self.fails[o.pid] = n + 1
            o = dataclasses.replace(o, limit_l=0)
        elif self.sale_tol is not None:
            eng = self.pipe.eng
            v = eng.sale_value(eng.tokens.get(o.mint), o.tokens, eng.cost_of(self.pipe.strat_of(o.pid).name))
            if v:
                o = dataclasses.replace(o, limit_l=max(o.limit_l, int(v / (1 + self.sale_tol))))
        if n:
            o = dataclasses.replace(o, signal_ms=int(o.signal_ms + backoff_ms(min(n, SELL_MAX_FAILS))))
        super().sell(o)

    def _attack_l(self, c) -> int:
        return 2 * c.tx_lamports()

    def squeeze_pool_buy(self, o, tok, spend, got, least, c) -> int:
        if self.view != "sandwich":
            return got
        g, p = sandwich_buy(spend, tok.pq, tok.pb, max(tok.amm_fee_bps, c.fee_bps_floor), least, self._attack_l(c))
        if p > 0 and g < got:
            self.sw["buys"] += 1
            self.sw["buy_l"] += int(spend * (1 - g / got))
            return g
        return got

    def squeeze_curve_buy(self, o, tok, want, cost, cap, c) -> int:
        if self.view != "sandwich":
            return cost
        k, p = sandwich_curve_buy(want, tok.vs, tok.vt, max(tok.fee_bps, c.fee_bps_floor), cap, self._attack_l(c))
        if p > 0 and k > cost:
            self.sw["buys"] += 1
            self.sw["buy_l"] += k - cost
            return k
        return cost

    def squeeze_sell(self, o, tok, v, c) -> int:
        if self.view != "sandwich" or tok is None:
            return v
        if tok.on_curve:
            s, t, fee = tok.vs, tok.vt, max(tok.fee_bps, c.fee_bps_floor)
        elif tok.pq and tok.pb:
            s, t, fee = tok.pq, tok.pb, max(tok.amm_fee_bps, c.fee_bps_floor)
        else:
            return v
        w, p = sandwich_sell(o.tokens, s, t, fee, o.limit_l, self._attack_l(c))
        if p > 0 and w < v:
            self.sw["sales"] += 1
            self.sw["sale_l"] += v - w
            return w
        return v


class Book(R.Book):
    """A realistic book of E1: counts its failed sales and their fees, and how much worse than the signal's quote
    each buy filled (price paid per token over the stake per token quoted at the signal, less 1)."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.worse: dict[int, float] = {}
        self.sale_fails = 0
        self.sale_fail_l = 0

    def bought(self, pid: int, at: float, tokens: int, cost_l: int, fee_l: int) -> None:
        p = self.pos.get(pid)
        if p is not None and p["state"] == "pending" and tokens > 0 and p.get("want") and p.get("stake_l"):
            self.worse[pid] = (cost_l / tokens) / (p["stake_l"] / p["want"]) - 1
        super().bought(pid, at, tokens, cost_l, fee_l)

    def sell_failed(self, pid: int, at: float, why: str, fee_l: int) -> None:
        if pid in self.pos:
            self.sale_fails += 1
            self.sale_fail_l += int(fee_l)
            self.exec.fails[pid] = self.exec.fails.get(pid, 0) + 1
        super().sell_failed(pid, at, why, fee_l)

    def sold(self, pid: int, at: float, tokens: int, got_l: int, fee_l: int, stuck: bool = False) -> None:
        self.exec.fails.pop(pid, None)
        super().sold(pid, at, tokens, got_l, fee_l, stuck)


def variant(rule: str, pair: str, view: str | None = None, stake_sol: float = math.inf) -> P.Strategy:
    """`<rule>@e1_<pair>` (forward) or `<rule>@e1_<pair>_<view>` (replay): the rule, its own latency key."""
    s = P.BY_NAME[rule]
    name = f"{rule}{TAG}{pair}" + (f"_{view}" if view else "")
    b, sb = PAIRS[pair]
    return dataclasses.replace(s, name=name, p={**s.p, "base": rule}, stake_sol=stake_sol,
                               label=f"{s.label}; E1: buy bound {b:g}, sale bound "
                                     f"{'live' if sb is None else format(sb, 'g')}")


def add_book(eng, rule: str, pair: str, view: str, model: R.Model, wallet: R.PaperWallet | None = None,
             forward: bool = False, kill=None, record: bool = True) -> Book:
    s = variant(rule, pair, None if forward else view, math.inf if wallet is not None else R.R1_STAKE_SOL)
    if not forward:
        s = dataclasses.replace(s, name=s.name + ("W" if wallet is not None else "C"))
    eng.rule_costs[s.name] = R.RealCosts(model=model)
    b = eng.add_pipe(Book(eng, [s], BoundExecutor(model, wallet, pair, view), name=s.name if not forward
                          else "realistic", kill=kill, record=record))
    if wallet is None:                                     # a measuring book: no slot, exposure or loss limit
        b.risk[s.name].limits = R.R1_CALIB_LIMITS
    return b


def shadow_books(eng, model: R.Model, wallets: dict | None = None, kill=None) -> list[Book]:
    """The forward books in the shadow (live.Shadow): every rule and pair, the sandwich view, the live sizing on its
    own START_SOL paper wallet (`wallets`, filled in for new ones)."""
    wallets = wallets if wallets is not None else {}
    return [add_book(eng, r, k, FORWARD_VIEW, model, wallets.setdefault(f"{r}{TAG}{k}", R.PaperWallet()),
                     forward=True, kill=kill) for r in RULES for k in PAIRS]


def parse(name: str) -> tuple[str, str, str | None] | None:
    """(rule, pair, view or None) of an E1 book's name."""
    if TAG not in (name or ""):
        return None
    rule, rest = name.split(TAG, 1)
    rest = rest[:-1] if rest[-1:] in ("C", "W") and "_" in rest else rest      # a replay book's C or W
    pair, _, view = rest.partition("_")
    return (rule, pair, view or None) if rule in RULES and pair in PAIRS else None


# ---------------------------------------------------------------- the measures

def entries(closed: list[dict], failed: list[dict], worse: dict | None = None) -> list[dict]:
    """A book's signals: closed trades and failed buys (a failed buy, or a pre-send skip, lost its fee)."""
    e = [{"mint": t["mint"], "signal_ms": R._f(t.get("signal_ms")), "pnl_sol": R._f(t.get("pnl_sol")) or 0.0,
          "ret": R._f(t.get("ret")), "failed": False, "why": t.get("exit_why"),
          "worse": (worse or {}).get(t.get("pid")) if worse is not None else _slip(t)} for t in closed]
    e += [{"mint": f["mint"], "signal_ms": R._f(f.get("signal_ms")), "pnl_sol": R._f(f.get("pnl_sol")) or 0.0,
           "ret": None, "failed": True, "why": R._why(f), "worse": None} for f in failed]
    return sorted(e, key=lambda x: x["signal_ms"] or 0)


def _slip(t: dict):
    """Forward rows carry no quote: the entry over the signal's spot price, less 1 (with the stake's impact)."""
    return R._f(t.get("slip"))


def stats(e: list[dict], stake_sol: float = R.R1_STAKE_SOL) -> dict:
    trades = [x for x in e if not x["failed"]]
    r = np.array([x["ret"] for x in trades if x["ret"] is not None], dtype=float)
    fails = [x for x in e if x["failed"]]
    w = [x["worse"] for x in trades if x["worse"] is not None]
    by = collections.Counter(x["why"] for x in fails)
    fee = collections.defaultdict(float)
    for x in fails:
        fee[x["why"]] -= x["pnl_sol"]
    k6040 = R.RAN_AWAY_LANDING
    return {"signals": len(e), "trades": len(trades), "n6040": by.get(k6040, 0), "fee6040": fee.get(k6040, 0.0),
            "presend": by.get(R.RAN_AWAY, 0),
            "other": sum(v for k, v in by.items() if k not in (k6040, R.RAN_AWAY)),
            "fee_other": sum(v for k, v in fee.items() if k not in (k6040, R.RAN_AWAY)),
            "fails": dict(by), "mean": float(r.mean()) if len(r) else None,
            "median": float(np.median(r)) if len(r) else None,
            "pnl_sol": float(sum(x["pnl_sol"] for x in e)),
            "per_signal": float(sum(x["pnl_sol"] for x in e)) / len(e) / stake_sol if e else None,
            "worse2": (sum(1 for v in w if v > WORSE) / len(w)) if w else None, "worse_max": max(w) if w else None}


def paired(a: list[dict], b: list[dict], stake_sol: float = R.R1_STAKE_SOL, draws: int = DRAWS,
           seed: int = SEED) -> dict:
    """a minus b in P&L per signal (points of the stake), signals matched by (rule, coin); 95 % band, coins drawn."""
    def first(e):
        out = {}
        for x in e:
            k = (x.get("rule"), x["mint"])
            out.setdefault(k, 0.0)
            out[k] += x["pnl_sol"]
        return out
    fa, fb = first(a), first(b)
    keys = sorted(set(fa) & set(fb))
    d = np.array([fa[k] - fb[k] for k in keys], dtype=float) / stake_sol
    if not len(d):
        return {"n": 0, "diff": None, "band": None}
    rng = np.random.default_rng(seed)
    bs = d[rng.integers(0, len(d), (draws, len(d)))].mean(axis=1)
    return {"n": len(d), "diff": float(d.mean()),
            "band": (float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5)))}


def best_by_day(books: dict, names, view: str, rule: str) -> collections.Counter:
    """Per recorded UTC day (by signal), which pair made the most per signal."""
    per: dict[str, dict[str, float]] = collections.defaultdict(dict)
    for k in names:
        by = collections.defaultdict(list)
        for x in books[(rule, k, view)]["entries"]:
            by[datetime.fromtimestamp(x["signal_ms"] / 1000, timezone.utc).strftime("%Y-%m-%d")].append(x)
        for day, xs in by.items():
            per[day][k] = sum(x["pnl_sol"] for x in xs) / len(xs)
    return collections.Counter(max(v, key=v.get) for v in per.values() if v)


def propose(books: dict, rule: str = TWIN, view: str = "sandwich") -> dict:
    """The pre-registered rule: the buy bound (BUYS) and the sale bound (SALES) with the highest P&L per signal on
    the rule's C books; proposed in place of the live one only when its paired band against b60 lies above 0."""
    out = {}
    ref = books[(rule, LIVE, view)]["entries"]
    for what, names in (("buy", BUYS), ("sale", SALES)):
        best = max(names, key=lambda k: books[(rule, k, view)]["stats"]["per_signal"] or -math.inf)
        pr = paired(books[(rule, best, view)]["entries"], ref) if best != LIVE else {"diff": 0.0, "band": None}
        ok = best != LIVE and pr["band"] is not None and pr["band"][0] > 0
        out[what] = {"best": best, "paired": pr, "proposed": best if ok else LIVE}
    return out


def p2_gap(live: dict, books: dict, view: str, pair: str) -> dict | None:
    """P2's gap with the C books of a pair as the paper side (the rules' rows under the rule's name)."""
    from . import selection_p2 as S2
    ledger, failed = [], []
    for r in RULES:
        b = books.get((r, pair, view))
        if b is None:
            continue
        ledger += [dict(t, rule=r) for t in b["closed"]]
        failed += [dict(f, rule=r) for f in b["failed"]]
    if not live.get("ledger"):
        return None
    return S2.compute(live, {"ledger": ledger, "failed": failed, "skipped": []})["gap"]


# ---------------------------------------------------------------- the replay

def run_replay(root=None, until_ms: int | None = None, log=print, model: R.Model | None = None,
               rules=RULES, pairs=tuple(PAIRS), views=VIEWS) -> dict:
    """The recorded days through sim with every (rule, pair, view) as a C and a W book (the module's docstring)."""
    from . import early as EA
    from . import sim, store
    from . import wallets as W
    from .model import load as load_models
    from .selfeat import day_of
    from .study import WARM_DAYS, WINDOW_DAYS, span_of, warm_book
    model = model or R.Model(R.fit(R._measured(), until_ms or int(time.time() * 1000)))
    all_days = [d for d in store.days(root) if until_ms is None or d <= day_of(until_ms)]
    days = all_days[-WINDOW_DAYS:]
    if not days:
        return {"empty": True}
    warm = [d for d in all_days if d < days[0]][-WARM_DAYS:]
    t_lo, t_hi = span_of(days, root)
    t_hi = t_hi if until_ms is None else min(t_hi, until_ms)
    log(f"e1: {len(days)} day(s) {days[0]} to {days[-1]}, warm-up {len(warm)}, "
        f"{len(rules) * len(pairs) * len(views) * 2} books")
    t0 = time.time()
    models = load_models() if "P_cmig_model" in rules else {}
    eng = sim.Engine([], book=warm_book(warm, root), decisions=False, entry_until=t_hi - R.R1_TAIL_MS,
                     wallets=W.warm(warm, root), snipers=EA.warm_snipers(warm, root), select=True, models=models)
    pipes = {}
    for r in rules:
        for k in pairs:
            for v in views:
                pipes[(r, k, v, "C")] = add_book(eng, r, k, v, model, record=False)
                pipes[(r, k, v, "W")] = add_book(eng, r, k, v, model, R.PaperWallet(), record=False)
    sim.replay(days, eng, root, progress=lambda d, n: log(f"e1: {d} done ({n:,} events, {time.time() - t0:.0f} s)"),
               until_ms=t_hi)
    log(f"e1: replay in {time.time() - t0:.0f} s")
    books = {}
    for (r, k, v, kind), p in pipes.items():
        e = [dict(x, rule=r) for x in entries(p.closed, p.failed, p.worse)]
        rec = {"closed": p.closed, "failed": p.failed, "entries": e, "sale_fails": p.sale_fails,
               "sale_fail_sol": p.sale_fail_l / C.LAMPORTS, "given_up": p.exec.given_up, "sw": dict(p.exec.sw)}
        if kind == "C":
            books[(r, k, v)] = rec | {"stats": stats(e)}
        else:
            w = p.exec.wallet
            books[(r, k, v)]["W"] = {"trades": w.n, "pnl_sol": w.pnl_l / C.LAMPORTS, "refills": w.refills,
                                     "sale_fails": p.sale_fails, "given_up": p.exec.given_up}
    return {"days": days, "span": (t_lo, t_hi), "books": books, "fit": model.fit.to_json(),
            "config": model.cfg.to_json(), "rules": list(rules), "pairs": list(pairs), "views": list(views)}


# ---------------------------------------------------------------- forward

def forward(ledger: list[dict], failed: list[dict], register: bool = True) -> dict:
    """The forward books' numbers from the paper ledger and failed buys (P1's tainted rows skipped): per (rule, pair)
    the stats, at the book's own stake, and the days they cover."""
    if register:
        metrics.register(trials())
    rows, _ = R.untainted([t for t in ledger if parse(t.get("rule") or "")])
    by: dict[tuple, dict] = collections.defaultdict(lambda: {"closed": [], "failed": []})
    for t in rows:
        r, k, _v = parse(t["rule"])
        by[(r, k)]["closed"].append(t)
    for f in failed:
        if (x := parse(f.get("rule") or "")) is not None:
            by[(x[0], x[1])]["failed"].append(f)
    out, t0, t1 = {}, None, None
    for key, b in by.items():
        e = entries(b["closed"], b["failed"])
        stake = float(np.median([R._f(t.get("stake_sol")) or 0.0 for t in b["closed"]])) if b["closed"] else 1.0
        out[f"{key[0]}|{key[1]}"] = stats(e, stake or 1.0) | {"stake_sol": stake}
        ts = [x["signal_ms"] for x in e if x["signal_ms"] is not None]
        if ts:
            t0 = min(ts) if t0 is None else min(t0, min(ts))
            t1 = max(ts) if t1 is None else max(t1, max(ts))
    return {"books": out, "from_ms": t0, "to_ms": t1}


def forward_md(fw: dict | None) -> list[str]:
    """realistic.md's lines for the forward books of the live rule."""
    if not fw or not fw.get("books"):
        return ["E1 slippage bounds (results/slippage_e1.md): no forward trades of the `@e1_` books yet.", ""]
    md = [f"E1 slippage bounds, forward books of {TWIN} (sandwich view, live sizing, from "
          f"{_day(fw['from_ms'])} UTC; results/slippage_e1.md):", "",
          "| pair | signals | trades | 6040 | pre-send skips | other failures | mean a trade | P&L SOL |",
          "|---|---|---|---|---|---|---|---|"]
    for k in PAIRS:
        s = fw["books"].get(f"{TWIN}|{k}")
        if s:
            md.append(f"| {k} | {s['signals']} | {s['trades']} | {s['n6040']} | {s['presend']} | {s['other']} | "
                      f"{_pc(s['mean'])} | {s['pnl_sol']:+.4f} |")
    return md + [""]


# ---------------------------------------------------------------- the report

def _pc(x) -> str:
    return "n/a" if x is None else f"{x * 100:+.1f} %"


def _pt(x) -> str:
    return "n/a" if x is None else f"{x * 100:+.2f}"


def _band(b) -> str:
    return "n/a" if not b else f"{b[0] * 100:+.2f} to {b[1] * 100:+.2f}"


def _day(ms) -> str:
    return "n/a" if ms is None else datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M")


def pooled(books: dict, k: str, v: str) -> dict:
    return stats(sorted((x for r in RULES if (r, k, v) in books for x in books[(r, k, v)]["entries"]),
                        key=lambda x: x["signal_ms"] or 0))


def table(books: dict, rule: str | None, v: str) -> list[str]:
    md = ["| pair | buy bound | sale bound | signals | trades | 6040 (fees SOL) | pre-send skips | other buy failures "
          "(fees SOL) | failed sales (fees SOL) | given up | mean a trade | median | P&L per signal, points | worse "
          "than the signal by > 2 % | sandwiched buys / sales (SOL) | vs b60, points per signal (band) |",
          "|" + "---|" * 16]
    for k in PAIRS:
        if rule is None:
            if not all((r, k, v) in books for r in RULES):
                continue
            s = pooled(books, k, v)
            bs = [books[(r, k, v)] for r in RULES]
            ref = [x for r in RULES for x in books[(r, LIVE, v)]["entries"]]
            mine = [x for b in bs for x in b["entries"]]
        else:
            if (rule, k, v) not in books:
                continue
            b = books[(rule, k, v)]
            s, bs = b["stats"], [b]
            ref, mine = books[(rule, LIVE, v)]["entries"], b["entries"]
        sf, sfl, gu = (sum(b[x] for b in bs) for x in ("sale_fails", "sale_fail_sol", "given_up"))
        sw = {x: sum(b["sw"][x] for b in bs) for x in ("buys", "buy_l", "sales", "sale_l")}
        pr = paired(mine, ref) if k != LIVE else None
        bb, sb = PAIRS[k]
        md.append(f"| {'**' + k + '**' if k == LIVE else k} | {bb:g} | {'live' if sb is None else format(sb, 'g')} | "
                  f"{s['signals']} | {s['trades']} | {s['n6040']} ({s['fee6040']:.4f}) | {s['presend']} | "
                  f"{s['other']} ({s['fee_other']:.4f}) | {sf} ({sfl:.4f}) | {gu} | {_pc(s['mean'])} | "
                  f"{_pc(s['median'])} | {_pt(s['per_signal'])} | {_pc(s['worse2'])} | {sw['buys']} / {sw['sales']} "
                  f"({(sw['buy_l'] + sw['sale_l']) / C.LAMPORTS:.4f}) | "
                  f"{'reference' if pr is None else _pt(pr['diff']) + ' (' + _band(pr['band']) + ')'} |")
    return md


def markdown(res: dict, p2: dict, prop: dict, fw: dict | None) -> str:
    books = res["books"]
    f = R.Fit.from_json(res["fit"])
    md = ["# E1: slippage bounds for pump.fun buys and sales, on realistic paper", "",
          f"Pre-registration `{PREREG}`. Code `lab/pumpfun_rt/slippage_e1.py`, the hooks in `realistic.RealExecutor`. "
          f"Replay of the record {res['days'][0]} to {res['days'][-1]} ({_day(res['span'][0])} to "
          f"{_day(res['span'][1])} UTC) through `sim`; the fit: buy {R.describe(f.buy)['median'] / 1000:.1f} s, sale "
          f"{R.describe(f.sell)['median'] / 1000:.1f} s median, fee {f.fee_l / C.LAMPORTS:.6f} + tip "
          f"{f.tip_l / C.LAMPORTS:.6f} SOL, {(f.live or {}).get('buys', 0)} live buys. C books: 0.1 SOL on every "
          "signal; P&L per signal in points of the stake (closed trades and failed buys' fees over all signals); "
          "returns after every fee. Bands: 95 % percentile bootstrap, 2,000 draws, seed 0, coins drawn. 60 trials "
          "in R5's registry, counted only (`hand:e1:*`); no Sharpe, no DSR. Paper only: the live bounds are the "
          "owner's and nothing here changes them.", "",
          "## The answer", ""]
    for v in VIEWS:
        p = prop[v]
        for what in ("buy", "sale"):
            x = p[what]
            md.append(f"- {TWIN}, {v} view, {what} bound: best {x['best']}"
                      + ("" if x["best"] == LIVE else f", {_pt(x['paired']['diff'])} points per signal against b60 "
                                                      f"(band {_band(x['paired']['band'])})")
                      + f": **{'keep the live bound' if x['proposed'] == LIVE else 'propose ' + x['proposed']}**.")
    md += ["", "## Every rule pooled", ""]
    for v in VIEWS:
        md += [f"### {v}", "", *table(books, None, v), ""]
    for r in res["rules"]:
        md += [f"## {r}", ""]
        for v in VIEWS:
            md += [f"### {v}", "", *table(books, r, v), "",
                   "Best buy bound by day (days won): " + ", ".join(
                       f"{k} {n}" for k, n in best_by_day(books, BUYS, v, r).most_common()) + ".", ""]
    md += ["## The live sizing (W books, 0.55 SOL paper wallets)", "",
           "| rule | view | pair | trades | P&L SOL | top-ups | failed sales | given up |",
           "|---|---|---|---|---|---|---|---|"]
    for r in res["rules"]:
        for v in VIEWS:
            for k in PAIRS:
                w = books.get((r, k, v), {}).get("W")
                if w:
                    md.append(f"| {r} | {v} | {k} | {w['trades']} | {w['pnl_sol']:+.3f} | {w['refills']} | "
                              f"{w['sale_fails']} | {w['given_up']} |")
    md += ["", "## P2's selection gap by bound", "",
           "P2's paper side replaced by the C books of each pair (the three rules), against the live bot's trades in "
           "its runs (`selection_p2.compute`); points a trade.", "",
           "| view | pair | paper signals | live trades | matched | paper minus live (band) | selection | same coins "
           "| live's own |", "|---|---|---|---|---|---|---|---|---|"]
    for (v, k), g in p2.items():
        if g:
            md.append(f"| {v} | {k} | {g['n_paper']} | {g['n_live']} | {g['n_pairs']} | {_pt(g.get('gap'))} "
                      f"({_band((g.get('band') or {}).get('gap'))}) | {_pt(g.get('selection'))} | "
                      f"{_pt(g.get('same_coins'))} | {_pt(g.get('live_own'))} |")
    md += ["", "## Forward", "", *forward_md(fw)]
    return "\n".join(md) + "\n"


def run(out: Path = OUT, until_ms: int | None = None, register: bool = True, log=print, root=None) -> dict:
    from .live import paper_dir
    from .live_exec import data_dir
    from . import selection_p2 as S2
    if register:
        metrics.register(trials())                            # before any number exists
    res = run_replay(root, until_ms, log)
    if res.get("empty"):
        log("e1: no recorded days")
        return res
    live = S2.read_live(data_dir())
    p2 = {(v, k): p2_gap(live, res["books"], v, k) for v in VIEWS for k in PAIRS}
    prop = {v: propose(res["books"], TWIN, v) for v in VIEWS}
    fw = forward(R.read_csv(paper_dir() / "ledger.csv"), R.read_csv(paper_dir() / "failed.csv"), register=False)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(markdown(res, p2, prop, fw), encoding="utf-8")
    log(f"e1: {prop} -> {out}")
    return {"replay": res, "p2": p2, "proposal": prop, "forward": fw}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="lab.pumpfun_rt.slippage_e1", description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--until", default=None, help="UTC cutoff, e.g. 2026-10-28T19:40")
    a = ap.parse_args(sys.argv[1:] if argv is None else argv)
    until = int(datetime.fromisoformat(a.until).replace(tzinfo=timezone.utc).timestamp() * 1000) if a.until else None
    run(Path(a.out), until)
    return 0


if __name__ == "__main__":
    sys.exit(main())
