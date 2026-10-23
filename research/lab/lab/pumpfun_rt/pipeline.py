"""The trading pipeline: signal, filter, sizing, risk, entry and exit management.

One decision layer for every book: the study's replay, the live paper shadow and
a live executor all run this code. Only the executor differs:

  PaperExecutor   fills an order by the curve (or pool) arithmetic one latency draw
                  after it was sent (curve.py), as the rest of the lab does
  LiveExecutor    (live_exec.py, LOCKED) sends the same order to the chain and takes
                  its fill from the program's own trade event of our wallet

Both take the same orders and report back through the same four calls
(bought, buy_failed, sold, sell_failed), so a paper book does what a live one
would do, its risk limits included. Pre-registered in results/pumpfun_realtime_plan.md,
addendum 2 (2026-10-20).

Orders (both executors):

  buy    want tokens (what the stake buys at the signal's state), max_cost lamports
         (stake x (1 + SLIP_TOL), fee included). At landing the cost of `want` at the
         then state; above max_cost the buy fails and only the fee is lost; when less
         is left on the curve, what is left.
  sell   tokens and min_out lamports: 0 for every protective exit, half the expected
         proceeds for a take-profit step. A sale under min_out fails and pays its fee.

Exits, checked on every trade of the token and signalled at that event's slot time
(the same slot window): take-profit ladder, stop loss, trailing stop, dev sell,
liquidity pull, the risk model (where a strategy names it), time stop, kill switch.
"""

from __future__ import annotations

import dataclasses
import math
import os
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import curve as C
from . import strategies as S

# ---------------------------------------------------------------- hard caps

# The code's hard caps. Paper books run at exactly these (but stake S.STAKE_SOL, 0.1 SOL, whatever the stake
# cap); a live owner can only lower them, and the live stake follows the wallet under them (sizing.py).
HARD_STAKE_SOL = 0.25
HARD_MAX_OPEN = 5
HARD_MAX_EXPOSURE_SOL = 0.6
HARD_MAX_DAILY_LOSS_SOL = 1.0
MAX_IMPACT = 0.02                     # a buy never spends more than 2 % of the curve's virtual SOL (pool: its SOL)
TP_FLOOR = 0.5                        # a take-profit sale accepts no less than half its expected proceeds
DEV_SELL_FRAC = 0.10                  # the dev selling 10 % or more of its holding is an exit
PULL_WINDOW_MS = 2_000
PULL_SOL_DROP = 0.15
PULL_SUPPLY_SHARE = 0.02
RISK_EVERY_MS = 1_000                 # the risk model is asked at most once a second per position
DAY_MS = 86_400_000


def kill_paths() -> list[Path]:
    """Files whose presence stops every book from buying and sells what is open."""
    from ..data import ROOT
    return [Path("/etc/pythia/pumpfun-kill"), ROOT / "pumpfun_rt" / "KILL"]


def killed(paths: list[Path] | None = None) -> bool:
    for p in paths if paths is not None else kill_paths():
        try:
            if p.exists():
                return True
        except OSError:
            return True                 # cannot even look: treat as killed
    return False


def never() -> bool:
    """The study's replay: no kill switch (a file on the server must not change history)."""
    return False


class KillSwitch:
    """The kill switch files, looked at no more than once a second (the books ask on every trade)."""

    def __init__(self, paths: list[Path] | None = None, every_s: float = 1.0):
        import time
        self.paths, self.every, self._clock = paths, every_s, time.monotonic
        self.last, self.state = -1e18, False

    def __call__(self) -> bool:
        now = self._clock()
        if now - self.last >= self.every:
            self.last, self.state = now, killed(self.paths)
        return self.state


@dataclass(frozen=True)
class Limits:
    stake_sol: float = HARD_STAKE_SOL
    max_open: int = HARD_MAX_OPEN
    max_exposure_sol: float = HARD_MAX_EXPOSURE_SOL
    max_daily_loss_sol: float = HARD_MAX_DAILY_LOSS_SOL

    def capped(self) -> "Limits":
        """Never above the hard caps, never negative."""
        return Limits(min(max(self.stake_sol, 0.0), HARD_STAKE_SOL), min(max(int(self.max_open), 0), HARD_MAX_OPEN),
                      min(max(self.max_exposure_sol, 0.0), HARD_MAX_EXPOSURE_SOL),
                      min(max(self.max_daily_loss_sol, 0.0), HARD_MAX_DAILY_LOSS_SOL))


class Risk:
    """One book's limits: open positions, exposure, the day's loss, the kill switch."""

    def __init__(self, limits: Limits | None = None, kill=None):
        self.limits = (limits or Limits()).capped()
        self.kill = kill or never
        self.held: dict[int, int] = {}            # pid -> lamports at risk (cost limit while pending, cost once open)
        self.day = None
        self.day_pnl_l = 0
        self.stopped_day = None

    def exposure(self) -> int:
        return sum(self.held.values())

    def _roll(self, t: float) -> None:
        d = int(t // DAY_MS)
        if d != self.day:
            self.day, self.day_pnl_l = d, 0

    def why_not(self, t: float, cost_l: int) -> str | None:
        """None when a new buy with this cost limit is allowed, else the reason."""
        lim = self.limits
        self._roll(t)
        if self.kill():
            return "kill switch"
        if self.stopped_day == self.day:
            return "daily loss stop"
        if len(self.held) >= lim.max_open:
            return "max open positions"
        if cost_l > lim.stake_sol * (1 + C.SLIP_TOL) * C.LAMPORTS + 1:
            return "stake above the cap"
        if self.exposure() + cost_l > lim.max_exposure_sol * C.LAMPORTS:
            return "max exposure"
        loss = max(0, -self.day_pnl_l)
        if loss + self.exposure() + cost_l > lim.max_daily_loss_sol * C.LAMPORTS:
            return "daily loss limit"
        return None

    def hold(self, pid: int, lamports: int) -> None:
        self.held[pid] = int(lamports)

    def release(self, pid: int) -> None:
        self.held.pop(pid, None)

    def booked(self, t: float, pnl_l: int) -> None:
        """A realised result (a closed position, a failed buy's fee) of the day it happened."""
        self._roll(t)
        self.day_pnl_l += int(pnl_l)
        if -self.day_pnl_l >= self.limits.max_daily_loss_sol * C.LAMPORTS:
            self.stopped_day = self.day


# ---------------------------------------------------------------- strategies

@dataclass(frozen=True)
class Exits:
    time_s: float
    sl: float
    ladder: tuple = ()                    # ((gain, cumulative share sold), ...), gains rising, last share 1.0
    trail_after: float | None = None
    trail_gap: float | None = None
    dev_sell: bool = True
    pull: bool = True
    risk: tuple | None = None             # (label, multiple of its base rate) for the risk-model exit
    hazard: bool = False                  # X14: the hazard exit HZ(k*) replaces the price exits when its models exist
    time_after_step_s: float | None = None  # Y7: once a ladder step has filled, the time stop is landing + this
    press_exit: tuple | None = None       # Y8: (window s, share): sell all when the pool's net SOL outflow over the
                                          # window (trades since the landing) exceeds share x its SOL at the landing
    runner: tuple | None = None           # Y11: (share kept, stop under the entry, fall from the high, hard stop s):
                                          # the time stop sells all but the share; the rest exits on its own stops
    lock: tuple | None = None             # Y12: ((arm gain, floor gain, cumulative share sold), ...), arms rising: once
                                          # the peak reached 1 + arm, a mark at or under 1 + floor sells to the share


# E0, the X14 plan's exit for the early books, and the hazard strategies' fallback before the first retrain.
E0 = Exits(1800, 0.35, ((1.0, 0.5), (3.0, 1.0)), 0.50, 0.25)
HZ_EXITS = dataclasses.replace(E0, hazard=True)


@dataclass(frozen=True)
class Strategy(S.Rule):
    """A pipeline strategy: a Rule's signal (same wants_* semantics) with a filter,
    a stake and an exit plan. tp/sl/hold_s mirror the plan for the report."""
    exits: Exits = None
    flt: dict = field(default_factory=dict, hash=False, compare=False)
    stake_sol: float = S.STAKE_SOL            # 0.1 SOL on paper; the live book sizes its own (live_exec.attach)

    @property
    def pipeline(self) -> bool:
        return True


@dataclass(frozen=True)
class EarlyStrategy(Strategy):
    """X14: a checkpoint at creation + w_s seconds with no rule of its own; the early models decide (flt "early")."""

    def wants_checkpoint(self, tok, t: int) -> bool:
        return True


def _strategy(name, family, entry, p, flt, exits: Exits, label, stake_sol: float = S.STAKE_SOL) -> Strategy:
    return Strategy(name, family, entry, exits.ladder[-1][0] if exits.ladder else 0.0, exits.sl, exits.time_s,
                    p, label, exits=exits, flt=flt, stake_sol=stake_sol)


def _build() -> list[Strategy]:
    snipe = Exits(30, 0.30, ((0.30, 0.5), (0.80, 1.0)), 0.20, 0.15)
    cmig = Exits(120, 0.35, ((0.50, 0.5), (1.50, 1.0)), 0.30, 0.25)
    press = Exits(60, 0.25, ((0.30, 0.5), (0.80, 1.0)), 0.15, 0.15)
    mom = Exits(120, 0.25, ((0.30, 0.5), (1.00, 1.0)), 0.20, 0.15, risk=("sell10_10", 2.0))
    late = Exits(1800, 0.20, ((0.20, 0.5), (0.50, 1.0)), 0.15, 0.12)
    pool = Exits(1800, 0.25, ((0.30, 0.5), (1.00, 1.0)), 0.20, 0.15)
    return [
        _strategy("P_snipe_dev", "A", "create", {"filter": "devbuy", "lo": 0.5, "hi": 5.0}, {}, snipe,
                  "snipe at creation, dev buy 0.5 to 5 SOL; ladder +30 %/+80 %, stop -30 %, trail 15 % after +20 %, 30 s"),
        _strategy("P_snipe_cmig", "A", "create", {"filter": "creator_migrated"}, {}, cmig,
                  "snipe at creation, creator had a completed curve; ladder +50 %/+150 %, stop -35 %, trail 25 % "
                  "after +30 %, 120 s"),
        _strategy("P_press10", "B", "checkpoint", {"w_s": 10, "buyers": 10, "net_sol": 2.0}, {}, press,
                  "creation + 10 s: 10+ outside buyers, 2+ SOL net, dev not sold; ladder +30 %/+80 %, stop -25 %, "
                  "trail 15 % after +15 %, 60 s"),
        _strategy("P_mom_model", "C", "momentum", {"buyers": 20, "within_s": 60},
                  {"model": {"up30": ("min", 1.25), "sell10_10": ("max", 1.0)}}, mom,
                  "20 outside buyers in 60 s, P(up30) 1.25x base, P(sell10_10) at most base; ladder +30 %/+100 %, "
                  "stop -25 %, trail 15 % after +20 %, risk-model exit, 120 s"),
        _strategy("P_p90", "D", "progress", {"at": 0.9}, {}, late,
                  "curve crosses 90 %; ladder +20 %/+50 %, stop -20 %, trail 12 % after +15 %, 1800 s"),
        _strategy("P_p80_smart", "D", "progress", {"at": 0.8}, {"smart_min": 1}, late,
                  "curve crosses 80 % with a smart early buyer; ladder +20 %/+50 %, stop -20 %, trail 12 % after "
                  "+15 %, 1800 s"),
        _strategy("P_pool60", "E", "migration", {"delay_s": 60}, {}, pool,
                  "PumpSwap, migration + 60 s; ladder +30 %/+100 %, stop -25 %, trail 15 % after +20 %, 1800 s"),
        _strategy("P_cmig_model", "A", "create", {"filter": "creator_migrated"},
                  {"model": {"up30": ("min", 1.25)}}, cmig,
                  "as P_snipe_cmig with P(up30) at least 1.25x base"),
    ]


def _build_x14() -> list[Strategy]:
    """X14 (results/pumpfun_early_exit_plan.md, section 3): early entries and the hazard exit, paper and shadow."""
    early = {"early": {"label": "peak3x", "top": 0.05, "alive": True}}
    hz = "hazard exit HZ(k*) with the dev-sell and pull exits, 30 min (E0's price exits until the models exist)"
    out = [EarlyStrategy(f"P_early{w}", "B", "checkpoint", HZ_EXITS.ladder[-1][0], HZ_EXITS.sl, HZ_EXITS.time_s,
                         {"w_s": w}, f"creation + {w} s, P(peak3x) in the top 5 % of its training scores at that "
                                     f"age and P(alive5m) at least its base rate; {hz}", exits=HZ_EXITS, flt=early)
           for w in (10, 30)]
    out.append(_strategy("P_press10_hz", "B", "checkpoint", {"w_s": 10, "buyers": 10, "net_sol": 2.0}, {}, HZ_EXITS,
                         f"as P_press10; {hz}"))
    out.append(_strategy("P_pool60_hz", "E", "migration", {"delay_s": 60}, {}, HZ_EXITS, f"as P_pool60; {hz}"))
    return out


def _build_y6() -> list[Strategy]:
    """Y6 (results/pumpfun_pool0_prereg.md): Y5's least-bad rule E_d0_x1 as a strategy the executor can run,
    its exits exactly the rule's (no ladder step, trail, dev-sell or pull exit the rule did not have)."""
    pool0 = Exits(300, 0.20, ((0.30, 1.0),), dev_sell=False, pull=False)
    return [_strategy("P_pool0", "E", "migration", {"delay_s": 0}, {}, pool0,
                      "PumpSwap, at the migration (as E_d0_x1); +30 %, stop -20 %, 300 s")]


def _build_y7() -> list[Strategy]:
    """Y7 (results/pumpfun_exit_runners_prereg.md): P_pool0's entry with exits that let a run go on. trail_after
    is the gain over the entry that arms the trail, trail_gap the fall from the peak that sells; a last ladder
    step at +5,000 % means no further take profit. No dev-sell or pull exit except in the guard variant."""
    half = Exits(1800, 0.20, ((0.30, 0.5), (50.0, 1.0)), 0.30, 0.30, dev_sell=False, pull=False)
    ladder3 = Exits(3600, 0.20, ((0.30, 0.34), (1.00, 0.67), (50.0, 1.0)), 0.30, 0.35, dev_sell=False, pull=False)
    trail = Exits(1800, 0.20, ((50.0, 1.0),), 0.20, 0.25, dev_sell=False, pull=False)
    guard = dataclasses.replace(half, dev_sell=True, pull=True)
    ext = dataclasses.replace(half, time_s=300, time_after_step_s=3600)
    at = "PumpSwap, at the migration (as P_pool0); stop -20 %"
    return [
        _strategy("P_pool0_half_trail", "E", "migration", {"delay_s": 0}, {}, half,
                  f"{at}; half at +30 %, the rest on a trail 30 % under the peak once +30 %, 1800 s"),
        _strategy("P_pool0_ladder3", "E", "migration", {"delay_s": 0}, {}, ladder3,
                  f"{at}; a third at +30 %, a third at +100 %, the rest on a trail 35 % under the peak once +30 %, "
                  "3600 s"),
        _strategy("P_pool0_trail", "E", "migration", {"delay_s": 0}, {}, trail,
                  f"{at}; no take profit, all on a trail 25 % under the peak once +20 %, 1800 s"),
        _strategy("P_pool0_half_trail_guard", "E", "migration", {"delay_s": 0}, {}, guard,
                  "as P_pool0_half_trail with the dev-sell and pull exits"),
        _strategy("P_pool0_half_trail_ext", "E", "migration", {"delay_s": 0}, {}, ext,
                  "as P_pool0_half_trail; time stop 300 s until the half at +30 % has sold, then 3600 s"),
    ]


def _build_y8() -> list[Strategy]:
    """Y8 (results/pumpfun_exits_y8_prereg.md): P_pool0 with a -10 % stop, a sell-pressure exit (the pool's net
    SOL outflow over 5 s above 8 % of its SOL at our landing), and an entry that waits up to 5 s for the pool's
    first trade when its state is not known at the migration (p["wait_pool_s"]); 0.1 SOL each."""
    pool0 = Exits(300, 0.20, ((0.30, 1.0),), dev_sell=False, pull=False)
    sl10 = dataclasses.replace(pool0, sl=0.10)
    press = dataclasses.replace(pool0, press_exit=(5.0, 0.08))
    at, wait = {"delay_s": 0}, {"delay_s": 0, "wait_pool_s": 5}
    w = "PumpSwap, at the migration or up to 5 s later at the pool's first trade"
    return [
        _strategy("P_pool0_sl10", "E", "migration", at, {}, sl10,
                  "PumpSwap, at the migration (as P_pool0); +30 %, stop -10 %, 300 s", stake_sol=0.1),
        _strategy("P_pool0_press", "E", "migration", at, {}, press,
                  "as P_pool0; sell all on a net pool outflow over 5 s above 8 % of the pool's SOL at entry",
                  stake_sol=0.1),
        _strategy("P_pool0_wait", "E", "migration", wait, {}, pool0, f"{w}; +30 %, stop -20 %, 300 s", stake_sol=0.1),
        _strategy("P_pool0_wait_press", "E", "migration", wait, {}, press, f"{w}; exits as P_pool0_press",
                  stake_sol=0.1),
        _strategy("P_pool0_wait_sl10", "E", "migration", wait, {}, sl10, f"{w}; +30 %, stop -10 %, 300 s",
                  stake_sol=0.1),
    ]


def _build_y9() -> list[Strategy]:
    """Y9 (results/pumpfun_select_y9_prereg.md): P_pool0's exits on the migrations its models pick: P(rug0) at most
    its base rate, P(win0) in its top 30 %, both, the entry 5 s after the migration with P(win5) in its top 30 %, and
    two or more smart early buyers (no model); 0.1 SOL each."""
    pool0 = Exits(300, 0.20, ((0.30, 1.0),), dev_sell=False, pull=False)
    at, at5 = {"delay_s": 0}, {"delay_s": 5}
    x = "+30 %, stop -20 %, 300 s"
    return [
        _strategy("P_pool0_norug", "E", "migration", at, {"select": {"rug0": ("max", 1.0)}}, pool0,
                  f"PumpSwap at the migration where P(rug within 60 s) is at most its base rate; {x}", stake_sol=0.1),
        _strategy("P_pool0_top30", "E", "migration", at, {"select": {"win0": ("top", 0.3)}}, pool0,
                  f"PumpSwap at the migration where P(win) is in its top 30 %; {x}", stake_sol=0.1),
        _strategy("P_pool0_norug_top30", "E", "migration", at,
                  {"select": {"rug0": ("max", 1.0), "win0": ("top", 0.3)}}, pool0,
                  f"PumpSwap at the migration where P(rug) is at most its base rate and P(win) in its top 30 %; {x}",
                  stake_sol=0.1),
        _strategy("P_pool5_top30", "E", "migration", at5, {"select": {"win5": ("top", 0.3)}}, pool0,
                  f"PumpSwap 5 s after the migration where P(win), with the pool's first seconds, is in its top "
                  f"30 %; {x}", stake_sol=0.1),
        _strategy("P_pool0_smart2", "E", "migration", at, {"smart_min": 2}, pool0,
                  f"PumpSwap at the migration where 2+ of the early buyers are smart wallets; {x}", stake_sol=0.1),
    ]


def _build_y10() -> list[Strategy]:
    """Y10 (results/pumpfun_trends_y10_prereg.md): the Trends page's measures (trendfeat.py) in use, P_pool0's exits
    and 0.1 SOL each. (a) Y9's top-30 % filters on the models that also see the trend features (sel_win0t,
    sel_win5t); (b) a curve in the hot-now top 5 with rising buyers and P(alive5m), from the early model with the
    trend features, at least its base rate; a fresh pool in the top 3 of the fresh pools 2 to 10 minutes after its
    migration; P_pool0 only while the market is hot (its buy SOL over 15 minutes at least the median of the last 6
    hours). The trend entries are asked at every 10 s boundary (sim.Engine's trend clock)."""
    pool0 = Exits(300, 0.20, ((0.30, 1.0),), dev_sell=False, pull=False)
    at, at5 = {"delay_s": 0}, {"delay_s": 5}
    x = "+30 %, stop -20 %, 300 s"
    return [
        _strategy("P_pool0_top30t", "E", "migration", at, {"select": {"win0t": ("top", 0.3)}}, pool0,
                  f"PumpSwap at the migration where P(win), with the trend features, is in its top 30 %; {x}",
                  stake_sol=0.1),
        _strategy("P_pool5_top30t", "E", "migration", at5, {"select": {"win5t": ("top", 0.3)}}, pool0,
                  f"PumpSwap 5 s after the migration where P(win), with the pool's first seconds and the trend "
                  f"features, is in its top 30 %; {x}", stake_sol=0.1),
        _strategy("P_hot5", "C", "trend", {"list": "hot", "top": 5, "rising": True},
                  {"trend": {"alive": "et_alive5m"}}, pool0,
                  f"a curve in the hot-now top 5 (buy SOL over 5 min) with more buyers in the last minute than in "
                  f"the one before, P(alive 5 min) at least its base rate; {x}", stake_sol=0.1),
        _strategy("P_fresh3", "E", "trend", {"list": "fresh", "top": 3, "from_s": 120, "to_s": 600}, {}, pool0,
                  f"PumpSwap, a pool in the top 3 of the pools migrated in the last 30 min (SOL traded over 5 min), "
                  f"2 to 10 min after its migration; {x}", stake_sol=0.1),
        _strategy("P_pool0_heat", "E", "migration", at, {"trend": {"heat": 1.0}}, pool0,
                  f"PumpSwap at the migration while the market's buy SOL over 15 min is at least its median of the "
                  f"last 6 h; {x}", stake_sol=0.1),
    ]


def _build_y11() -> list[Strategy]:
    """Y11 (results/pumpfun_runner_prereg.md): P_pool0_wait with a runner. Before the time stop exactly
    P_pool0_wait (+30 %, stop -20 %); at the 300 s time stop 80 % is sold and 20 % kept, which exits at its stop
    under the entry, or, once its value was above its cost since the time stop, at its fall from the highest value
    since then, or at the hard stop after the landing; 0.1 SOL each."""
    pool0 = Exits(300, 0.20, ((0.30, 1.0),), dev_sell=False, pull=False)
    wait = {"delay_s": 0, "wait_pool_s": 5}
    w = "PumpSwap, at the migration or up to 5 s later at the pool's first trade; +30 %, stop -20 %, at 300 s 80 % sold"
    return [
        _strategy("P_pool0_wait_run20", "E", "migration", wait, {},
                  dataclasses.replace(pool0, runner=(0.20, 0.50, 0.30, 1800)),
                  f"{w}, the rest out at -50 %, 30 % under its high once above the entry, or at 30 min",
                  stake_sol=0.1),
        _strategy("P_pool0_wait_run20w", "E", "migration", wait, {},
                  dataclasses.replace(pool0, runner=(0.20, 0.70, 0.40, 3600)),
                  f"{w}, the rest out at -70 %, 40 % under its high once above the entry, or at 60 min",
                  stake_sol=0.1),
    ]


def _build_y12() -> list[Strategy]:
    """Y12 (results/pumpfun_lock_prereg.md): P_pool0_wait with a ratcheting profit floor. Exactly P_pool0_wait's
    entry, +30 % take profit, -20 % stop and 300 s time stop; once the position's mark has reached an arm, a fall
    back to that arm's floor sells (all, or for the half variant half at the first floor); 0.1 SOL each."""
    pool0 = Exits(300, 0.20, ((0.30, 1.0),), dev_sell=False, pull=False)
    wait = {"delay_s": 0, "wait_pool_s": 5}
    w = "PumpSwap, at the migration or up to 5 s later at the pool's first trade; +30 %, stop -20 %, 300 s"
    return [
        _strategy("P_pool0_wait_lock", "E", "migration", wait, {},
                  dataclasses.replace(pool0, lock=((0.10, 0.02, 1.0), (0.20, 0.10, 1.0))),
                  f"{w}; once +10 % out at +2 %, once +20 % out at +10 %", stake_sol=0.1),
        _strategy("P_pool0_wait_lock_tight", "E", "migration", wait, {},
                  dataclasses.replace(pool0, lock=((0.08, 0.03, 1.0), (0.15, 0.09, 1.0))),
                  f"{w}; once +8 % out at +3 %, once +15 % out at +9 %", stake_sol=0.1),
        _strategy("P_pool0_wait_lock_half", "E", "migration", wait, {},
                  dataclasses.replace(pool0, lock=((0.10, 0.02, 0.5), (0.20, 0.10, 1.0))),
                  f"{w}; once +10 % half out at +2 %, once +20 % the rest out at +10 %", stake_sol=0.1),
    ]


STRATEGIES: list[Strategy] = (_build() + _build_x14() + _build_y6() + _build_y7() + _build_y8() + _build_y9()
                              + _build_y10() + _build_y11() + _build_y12())
BY_NAME: dict[str, Strategy] = {s.name: s for s in STRATEGIES}


def is_strategy(r) -> bool:
    return isinstance(r, Strategy)


def variant(s: Strategy, suffix: str) -> Strategy:
    return dataclasses.replace(s, name=f"{s.name}@{suffix}", p={**s.p, "base": s.name})


def base_name(r) -> str:
    return r.p.get("base") or r.name


# ---------------------------------------------------------------- orders

@dataclass
class Order:
    pid: int
    side: str                       # buy | sell
    mint: str
    venue: str                      # curve | pool
    tokens: int                     # buy: want; sell: amount
    limit_l: int                    # buy: max cost; sell: min proceeds
    signal_ms: int
    why: str = ""                   # sell: the exit that sent it
    leg: int = 0                    # sell number of the position
    stake_l: int = 0                # buy: the lamports to spend (a pool buy spends exactly this)


# ---------------------------------------------------------------- paper executor

class PaperExecutor:
    """Fills by the recorded curve or pool, one latency draw after the order (curve.py)."""

    kind = "paper"

    def __init__(self):
        self.pipe = None

    def attach(self, pipe: "Pipeline") -> None:
        self.pipe = pipe

    def ready(self) -> str | None:
        return None

    def buy(self, o: Order) -> None:
        eng, r = self.pipe.eng, self.pipe.strat_of(o.pid)
        lat = eng.cost_of(r.name).latency(base_name(r), o.mint, "buy")
        self.pipe.lat[o.pid] = lat
        eng.push(o.signal_ms + lat, "pipe", (self, "_land_buy", o))

    def sell(self, o: Order) -> None:
        eng, r = self.pipe.eng, self.pipe.strat_of(o.pid)
        key = (base_name(r), o.mint, "sell") if o.leg == 0 else (base_name(r), o.mint, "sell", o.leg)
        lat = eng.cost_of(r.name).latency(*key)
        eng.push(o.signal_ms + lat, "pipe", (self, "_land_sell", (o, o.signal_ms)))

    def on_trade(self, table: str, row: dict) -> None:
        pass

    def poll(self, now: float) -> None:
        pass

    def _land_buy(self, at: float, o: Order) -> None:
        pipe = self.pipe
        eng = pipe.eng
        c = eng.cost_of(pipe.strat_of(o.pid).name)
        tx = c.tx_lamports()
        tok = eng.tokens.get(o.mint)
        if tok is None:
            return pipe.buy_failed(o.pid, at, "token gone", tx)
        if o.venue == "pool":
            # as the live pool buy (buy_exact_quote_in_v2): the stake is spent exactly, on the pool's
            # effective quote reserves, and the buy fails below the signal's quote less the tolerance
            if not tok.pq or not tok.pb:
                return pipe.buy_failed(o.pid, at, "no pool state", tx)
            stake = o.stake_l or int(o.limit_l / (1 + C.SLIP_TOL))
            got = C.pool_buy(stake, tok.pb, tok.pq, max(tok.amm_fee_bps, c.fee_bps_floor))
            if got <= 0:
                return pipe.buy_failed(o.pid, at, "nothing filled", tx)
            if got < o.tokens / (1 + C.SLIP_TOL):
                return pipe.buy_failed(o.pid, at, "slippage", tx)
            return pipe.bought(o.pid, at, got, stake, tx)
        else:
            if not tok.on_curve:
                return pipe.buy_failed(o.pid, at, "curve completed before the buy landed", tx)
            want = min(o.tokens, tok.rt)
            cost = curve_cost(want, tok.vs, tok.vt, max(tok.fee_bps, c.fee_bps_floor))
        if want <= 0:
            return pipe.buy_failed(o.pid, at, "nothing filled", tx)
        if cost > o.limit_l:
            return pipe.buy_failed(o.pid, at, "slippage", tx)
        pipe.bought(o.pid, at, want, cost, tx)

    def _land_sell(self, at: float, data) -> None:
        o, t_sig = data
        pipe = self.pipe
        eng = pipe.eng
        c = eng.cost_of(pipe.strat_of(o.pid).name)
        tx = c.tx_lamports()
        v = eng.sale_value(eng.tokens.get(o.mint), o.tokens, c)
        if v is None:                                         # curve done, pool not seen yet
            if at - t_sig < 10 * 60_000:
                eng.push(at + 2_000, "pipe", (self, "_land_sell", data))
                return None
            return pipe.sold(o.pid, at, o.tokens, 0, tx, stuck=True)
        if v < o.limit_l:
            return pipe.sell_failed(o.pid, at, "under the floor", tx)
        pipe.sold(o.pid, at, o.tokens, v, tx)


def dev_sell_trigger(tok, user: str, tok_amt: int) -> bool:
    """The dev (creator or the creation's payer) sold 10 % or more of what it held (called after the sale)."""
    return user in tok.devs and tok_amt >= DEV_SELL_FRAC * (tok.dev_hold() + tok_amt)


def press_trigger(tok, t: float, since: float, window_s: float, share: float, ref_l: int) -> bool:
    """Y8's sell pressure: the pool's net SOL outflow (sells minus buys) over (t - window, t], counting only
    trades at or after `since` (our landing), above share x ref_l (the pool's SOL at our landing). The window
    must fit the token's 10 s pool window (tokens.WINDOW_MS)."""
    lo = t - window_s * 1000
    out = sum(before - after for ts, after, before in tok.amm_win if lo < ts <= t and ts >= since)
    return ref_l > 0 and out > share * ref_l


def pull_trigger(tok, t: float, user: str, tok_amt: int, venue: str) -> bool:
    """A liquidity pull (called after the sale): a top-10 holder sold 2 % of the supply at once, or the
    curve's SOL (the pool's) fell 15 % within 2 s."""
    from .tokens import SUPPLY
    if tok_amt >= PULL_SUPPLY_SHARE * SUPPLY and user in tok.top_holders(10, tok_amt_back=(user, tok_amt)):
        return True
    if venue == "pool":
        return tok.pool_drop(t, PULL_WINDOW_MS) >= PULL_SOL_DROP
    out = tok.net_out(t, PULL_WINDOW_MS)
    before = tok.rs + out
    return out > 0 and before > 0 and out >= PULL_SOL_DROP * before


def curve_cost(tokens: int, vs: int, vt: int, fee_bps: int) -> int:
    """Lamports (fee included) to buy exactly `tokens` from the curve; a huge number when it cannot."""
    if tokens <= 0:
        return 0
    if tokens >= vt or vs <= 0:
        return 1 << 62
    net = vs * tokens / (vt - tokens)
    return int(math.ceil(net * (1 + fee_bps / 10_000)))


def pool_cost(tokens: int, base: int, quote: int, fee_bps: int) -> int:
    if tokens <= 0:
        return 0
    if tokens >= base or quote <= 0:
        return 1 << 62
    return int(math.ceil(quote * tokens / (base - tokens) * (1 + fee_bps / 10_000)))


# ---------------------------------------------------------------- the pipeline

class Pipeline:
    """The decision layer of one book (a set of strategies, one executor, a Risk per strategy)."""

    def __init__(self, eng, strategies: list[Strategy], executor, limits: Limits | None = None,
                 name: str = "paper", record: bool = True, on_close=None, on_event=None, kill=None):
        self.eng = eng
        self.name = name
        self.strats = {s.name: s for s in strategies}
        self.exec = executor
        executor.attach(self)
        self.kill = kill or never
        self.risk = {s.name: Risk(limits, self.kill) for s in strategies}
        self.pos: dict[int, dict] = {}
        self.by_mint: dict[str, set] = {}
        self.lat: dict[int, float] = {}
        self.record = record                  # closed trades and failed buys go to the engine's lists too
        self.on_close = on_close
        self.on_event = on_event              # every order and fill, for the live trade alerts
        self.closed: list[dict] = []
        self.failed: list[dict] = []
        self.flattened = False
        self.waiting: dict[str, dict] = {}    # Y8: mint -> {strategy: signal time + wait_pool_s} until a pool trade
        self.on_skip = None                   # (strategy, mint, why) for every signal not bought: the live book's log
        self.blocked = None                   # (strategy, token) -> reason or None: the owner's block list (blocklist.py)

    def strat_of(self, pid: int) -> Strategy:
        return self.strats[self.pos[pid]["rule"]]

    def has(self, name: str) -> bool:
        return name in self.strats

    def _event(self, kind: str, p: dict, **kw) -> None:
        if self.on_event is not None:
            try:
                self.on_event(kind, p, kw)
            except Exception as e:                           # an alert never stops a book
                print(f"pipeline {self.name}: event hook {type(e).__name__}: {e}", flush=True)

    def skip(self, name: str, mint: str, why: str) -> None:
        """A signal that is not bought: counted by reason, and handed to on_skip (the live book logs each coin)."""
        self.eng.skipped[(name, why)] += 1
        if self.on_skip is not None:
            try:
                self.on_skip(name, mint, why)
            except Exception as e:                           # a log line never stops a book
                print(f"pipeline {self.name}: skip hook {type(e).__name__}: {e}", flush=True)

    # ------------------------------------------------------------ entry
    def signal(self, s: Strategy, tok, t: float) -> None:
        eng = self.eng
        pool = s.family == "E"
        why = self.blocked(s.name, tok) if self.blocked is not None else None
        if why:
            self.skip(s.name, tok.mint, why)
            return
        if pool:
            if tok.quote is not None or tok.mayhem or tok.irregular:
                self.skip(s.name, tok.mint, "not a plain SOL pool")
                return
            if not tok.pq or not tok.pb:
                if s.p.get("wait_pool_s"):
                    return self._wait_pool(s, tok, t)
                self.skip(s.name, tok.mint, "no pool state")
                return
        elif not tok.tradeable() or not tok.on_curve:
            self.skip(s.name, tok.mint, "not a plain SOL curve")
            return
        why = self.exec.ready()
        if why:
            self.skip(s.name, tok.mint, why)
            return
        f = None
        prob = None
        if s.flt.get("smart_min"):
            f = eng.features(tok, int(t))
            if (f.get("w_smart_n") or 0) < s.flt["smart_min"]:
                self.skip(s.name, tok.mint, "filter")
                return
        if s.flt.get("model"):
            f = f or eng.features(tok, int(t))
            ok, prob = self.model_ok(s.flt["model"], f)
            if not ok:
                self.skip(s.name, tok.mint, "model" if ok is False else "no model")
                return
        if s.flt.get("early"):
            ok, prob = self.early_ok(s.flt["early"], tok, t)
            if not ok:
                self.skip(s.name, tok.mint, "model" if ok is False else "no model")
                return
        if s.flt.get("select"):
            ok, prob = self.select_ok(s.flt["select"], tok, t)
            if not ok:
                self.skip(s.name, tok.mint, "model" if ok is False else "no model")
                return
        if s.flt.get("trend"):
            ok, prob = self.trend_ok(s.flt["trend"], tok, t)
            if not ok:
                self.skip(s.name, tok.mint, "model" if ok is False else "no model")
                return
        risk = self.risk[s.name]
        stake = int(min(s.stake_sol, risk.limits.stake_sol) * C.LAMPORTS)
        depth = tok.pq if pool else tok.vs
        stake = min(stake, int(MAX_IMPACT * depth)) if depth else 0
        if stake <= 0:
            self.skip(s.name, tok.mint, "no depth")
            return
        limit = int(stake * (1 + C.SLIP_TOL))
        why = risk.why_not(t, limit)
        if why:
            self.skip(s.name, tok.mint, why)
            return
        if pool:
            want = C.pool_buy(stake, tok.pb, tok.pq, tok.amm_fee_bps)
        else:
            want = C.curve_buy(stake, tok.vs, tok.vt, tok.rt, tok.fee_bps)
        if want <= 0:
            self.skip(s.name, tok.mint, "nothing to buy")
            return
        pid = eng.new_pid()
        price = C.price(tok.pq, tok.pb) if pool else tok.price()
        self.pos[pid] = {"pid": pid, "rule": s.name, "family": s.family, "mint": tok.mint, "name": tok.name,
                         "symbol": tok.symbol, "created_ms": tok.t0, "signal_ms": int(t), "signal_price": price,
                         "venue": "pool" if pool else "curve", "state": "pending", "stake_l": stake,
                         "limit_l": limit, "want": want, "prob": prob, "gap": False, "age_s": (t - tok.t0) / 1000,
                         "progress": tok.progress(), "dev_dumped_at_entry": tok.dev_dumped, "tokens": 0, "left": 0,
                         "cost_l": 0, "proceeds_l": 0, "fees_l": 0, "legs": 0, "step": 0, "peak": 0.0,
                         "selling": False, "exit_why": None, "last_risk_ms": 0, "breaks0": tok.breaks}
        self.by_mint.setdefault(tok.mint, set()).add(pid)
        risk.hold(pid, limit)
        eng.counts["pipe_signals"] += 1
        o = Order(pid, "buy", tok.mint, self.pos[pid]["venue"], want, limit, int(t), stake_l=stake)
        self._event("buy_sent", self.pos[pid], order=o)
        self.exec.buy(o)

    def _wait_pool(self, s: Strategy, tok, t: float) -> None:
        """Y8: no pool state at the signal: the signal is given again at the pool's first trade if that comes
        within wait_pool_s, else it is skipped for "no pool state" then."""
        until = t + s.p["wait_pool_s"] * 1000
        self.waiting.setdefault(tok.mint, {})[s.name] = until
        self.eng.push(until, "pipe", (self, "_wait_over", (tok.mint, s.name)))

    def _wait_over(self, at: float, data) -> None:
        mint, name = data
        w = self.waiting.get(mint)
        if w is None or w.pop(name, None) is None:
            return
        if not w:
            self.waiting.pop(mint, None)
        self.skip(name, mint, "no pool state")

    def model_ok(self, spec: dict, f: dict) -> tuple[bool | None, float | None]:
        """Every model criterion of the filter: ("min", k) needs p >= k x base, ("max", k) p <= k x base.
        (None, None) when a model it needs is missing."""
        first = None
        for label, (how, k) in spec.items():
            pb = self.eng.prob(label, f)
            if pb is None:
                return None, None
            p, base = pb
            first = p if first is None else first
            if how == "min" and p < k * base:
                return False, first
            if how == "max" and p > k * base:
                return False, first
        return True, first

    def early_ok(self, spec: dict, tok, t: float) -> tuple[bool | None, float | None]:
        """X14's early filter: P(label) at or above the top `top` threshold of the model's training scores at
        this age, and (alive) P(alive5m) at or above its base rate. (None, None) without the models."""
        eng = self.eng
        pol = eng.models.get("hz_policy")
        m = eng.models.get("e_" + spec["label"])
        tracker = getattr(eng, "early", None)
        if pol is None or m is None or m.booster is None or tracker is None:
            return None, None
        kind = f"t{int(round((t - tok.t0) / 1000))}"
        thr = ((pol.thresholds.get(spec["label"]) or {}).get(str(spec["top"])) or {}).get(kind)
        if thr is None:
            return None, None
        from .exitpol import raw_score
        f = eng.features(tok, int(t))
        f.update(tracker.early_features(tok, t, 0.0))
        x = np.array([[float(f.get(k, math.nan)) for k in m.features]], dtype=float)
        p = float(m.predict(x)[0])
        if float(raw_score(m, x)[0]) <= thr:                 # the thresholds are on the uncalibrated score
            return False, p
        if spec.get("alive"):
            a = eng.models.get("e_alive5m")
            if a is None or a.booster is None:
                return None, p
            pa = float(a.predict(np.array([[float(f.get(k, math.nan)) for k in a.features]], dtype=float))[0])
            if pa < a.base:
                return False, p
        return True, p

    def select_ok(self, spec: dict, tok, t: float) -> tuple[bool | None, float | None]:
        """Y9's select filter on the Y9 models (selmodel.py, as sel_<label>): ("max", k) needs P(label) at most k x
        its training base rate, ("top", q) P(label) at or above the threshold of the top q of its scores
        (sel_policy). (None, None) without the engine's select tracker, a model or its threshold."""
        eng = self.eng
        if getattr(eng, "sel", None) is None:
            return None, None
        from .selfeat import decision_features
        f = None
        first = None
        for label, (how, k) in spec.items():
            m = eng.models.get("sel_" + label)
            if m is None or m.booster is None:
                return None, None
            thr = None
            if how == "top":
                thr = ((eng.models.get("sel_policy") or {}).get(label) or {}).get(str(k))
                if thr is None:
                    return None, None
            f = f if f is not None else decision_features(eng, tok, t)
            p = float(m.predict(np.array([[float(f.get(c, math.nan)) for c in m.features]], dtype=float))[0])
            first = p if first is None else first
            if how == "max" and p > k * m.base:
                return False, first
            if how == "top" and p < thr:
                return False, first
        return True, first

    def trend_ok(self, spec: dict, tok, t: float) -> tuple[bool | None, float | None]:
        """Y10's trend filter: ("heat", k) the market's buy SOL over 15 minutes at least k x its median of the last
        6 hours (trendfeat.Tracker.heat_ok); ("alive", model) P(alive5m) of that early model (the early features
        and the trend features at t, as its rows) at least its base rate. (None, None) without the engine's trend
        tracker, the heat history or the model."""
        eng = self.eng
        tr = getattr(eng, "trend", None)
        if tr is None:
            return None, None
        prob = None
        if "heat" in spec:
            ok = tr.heat_ok(t, spec["heat"])
            if not ok:
                return ok, None
        if "alive" in spec:
            m = eng.models.get(spec["alive"])
            tracker = getattr(eng, "early", None)
            if m is None or m.booster is None or tracker is None:
                return None, None
            from .early import MILESTONES
            prog = tok.progress()
            f = eng.features(tok, int(t))
            f.update(tracker.early_features(tok, t, max((x for x in MILESTONES if prog >= x), default=0.0),
                                            prune=False))
            f.update(tr.features(tok, t))
            prob = float(m.predict(np.array([[float(f.get(c, math.nan)) for c in m.features]], dtype=float))[0])
            if prob < m.base:
                return False, prob
        return True, prob

    # ------------------------------------------------------------ fills
    def bought(self, pid: int, at: float, tokens: int, cost_l: int, fee_l: int) -> None:
        p = self.pos.get(pid)
        if p is None or p["state"] != "pending":
            return
        s = self.strats[p["rule"]]
        tok = self.eng.tokens.get(p["mint"])
        p.update(state="open", tokens=tokens, left=tokens, cost_l=cost_l, fees_l=p["fees_l"] + fee_l,
                 land_ms=int(at), entry_price=(cost_l / C.LAMPORTS) / (tokens / C.TOKEN_UNIT))
        self.risk[s.name].hold(pid, cost_l + fee_l)
        if s.exits.press_exit is not None:
            p["entry_pq"] = tok.pq if tok is not None and not tok.on_curve else 0
        tracker = getattr(self.eng, "early", None)
        if tracker is not None and tracker.rows_on:             # the study: the best exit afterwards (capture)
            tracker.watch_max(self.name, pid, p["mint"], tokens, cost_l + fee_l, at)
        self._event("bought", p, tokens=tokens, cost_l=cost_l)
        self.eng.push(at + s.exits.time_s * 1000, "pipe", (self, "_time_stop", pid))
        if tok is not None:
            self.check(pid, at)

    def buy_failed(self, pid: int, at: float, why: str, fee_l: int) -> None:
        p = self.pos.pop(pid, None)
        if p is None:
            return
        self._unindex(p)
        risk = self.risk[p["rule"]]
        risk.release(pid)
        risk.booked(at, -fee_l)
        f = {"rule": p["rule"], "mint": p["mint"], "signal_ms": p["signal_ms"], "land_ms": int(at), "why": why,
             "pnl_sol": -fee_l / C.LAMPORTS}
        self.failed.append(f)
        if self.record:
            self.eng.failed.append(f)
        self._event("buy_failed", p, why=why, fee_l=fee_l)

    def sold(self, pid: int, at: float, tokens: int, got_l: int, fee_l: int, stuck: bool = False) -> None:
        p = self.pos.get(pid)
        if p is None:
            return
        tokens = min(tokens, p["left"])
        rn = p.get("run")
        if rn is not None:                                    # Y11: the 80 % sale, or a sale of the rest
            if p.pop("run_part", None) is not None:
                rn["part_tokens"] += tokens
                rn["part_l"] += got_l
                rn["part_fee_l"] += fee_l
            else:
                rn["got_l"] += got_l
                rn["fee_l"] += fee_l
        p.pop("lock_part", None)
        p["left"] -= tokens
        p["proceeds_l"] += got_l
        p["fees_l"] += fee_l
        p["legs"] += 1
        p["selling"] = False
        p["last_exit_ms"] = int(at)
        if stuck:
            p["exit_why"] = "stuck"
            p["left"] = 0
        self._event("sold", p, tokens=tokens, got_l=got_l)
        if p["left"] <= 0:
            self._close(p, at)
        elif p.get("exiting"):                                # a protective exit sold only part: the rest goes too
            self._sell_all(p, at, p["exit_why"] or "stop")
        else:
            self._after_leg(p, at)

    def sell_failed(self, pid: int, at: float, why: str, fee_l: int) -> None:
        p = self.pos.get(pid)
        if p is None:
            return
        p["fees_l"] += fee_l
        p["selling"] = False
        p["sell_fails"] = p.get("sell_fails", 0) + 1
        self._event("sell_failed", p, why=why, fee_l=fee_l)
        part = p.pop("run_part", None)
        if part is not None and not p.get("exiting") and "due" not in p:
            return self._run_sell(p, at, part)                # Y11: the time stop's 80 % must go through too
        part = p.pop("lock_part", None)
        if part is not None and not p.get("exiting") and "due" not in p:
            return self._lock_sell(p, at, part)               # Y12: a floor's partial sale goes through too
        if p.get("exiting"):
            # A protective exit must go through: it is sent again at once. The live executor holds it back
            # for its backoff (1, 2, 4 ... 60 s) and gives up after a cap; the paper executor fills it.
            self._sell_all(p, at, p["exit_why"] or "stop")
            return
        p["step"] = max(0, p["step"] - 1)                     # the take-profit step was not taken: it stays due
        self._after_leg(p, at)

    def _after_leg(self, p: dict, at: float) -> None:
        """What came due while a sale was in flight: a protective trigger, the time stop, else a fresh check."""
        due = p.pop("due", None)
        if due is not None:
            self._sell_all(p, at, due)
        elif p.pop("time_due", False) and not self._time_moved(p, at):
            self._time_exit(p, at)
        else:
            self.check(p["pid"], at)

    # ------------------------------------------------------------ exits
    def on_trade(self, tok, t: float, buy: bool, user: str, tok_amt: int, venue: str) -> None:
        """Every trade of a token with open positions: the event-driven exits first, then the price ones. A
        signal waiting for the pool's state (Y8) is given again at the first pool trade that brings it."""
        w = self.waiting.get(tok.mint) if self.waiting else None
        if w and venue == "pool" and tok.pq and tok.pb:
            for name, until in list(w.items()):
                if t <= until:
                    del w[name]
                    self.signal(self.strats[name], tok, t)
            if not w:
                self.waiting.pop(tok.mint, None)
        pids = self.by_mint.get(tok.mint)
        if not pids:
            return
        trigger = None
        if not buy and dev_sell_trigger(tok, user, tok_amt):
            trigger = "dev_sell"
        elif not buy and pull_trigger(tok, t, user, tok_amt, venue):
            trigger = "pull"
        for pid in tuple(pids):
            self.check(pid, t, trigger)

    def _pull(self, tok, t: float, user: str, tok_amt: int, venue: str) -> bool:
        return pull_trigger(tok, t, user, tok_amt, venue)

    def hazard(self, p: dict, s: Strategy, tok, t: float, v: int) -> bool | None:
        """X14's HZ(k*): sell when the predicted upside over the next 30 s is below k* x P(a dump within
        10 s) x |L|. None when its models are missing (the price exits then apply); asked at most once a
        second, with the same step features the study's step rows carry (early.Tracker.step_features)."""
        eng = self.eng
        pol, md, mu = (eng.models.get(k) for k in ("hz_policy", "hz_dump10", "hz_up30"))
        tracker = getattr(eng, "early", None)
        if pol is None or md is None or mu is None or md.booster is None or mu.booster is None or tracker is None:
            return None
        tx = eng.cost_of(s.name).tx_lamports()
        vn = v - tx
        if vn > p.get("hz_peak", -1.0):
            p["hz_peak"], p["hz_peak_ms"] = vn, t
        if t - p.get("last_hz_ms", -1e18) < RISK_EVERY_MS:
            return False
        p["last_hz_ms"] = t
        f = tracker.step_features(tok, t, vn, p["cost_l"] + tx, p["hz_peak"], p["land_ms"], p["hz_peak_ms"])
        pd = float(md.predict(np.array([[float(f.get(k, math.nan)) for k in md.features]], dtype=float))[0])
        pu = float(mu.predict(np.array([[float(f.get(k, math.nan)) for k in mu.features]], dtype=float))[0])
        return pu < pol.k * pd * pol.loss

    def check(self, pid: int, t: float, trigger: str | None = None) -> None:
        p = self.pos.get(pid)
        if p is None or p["state"] != "open" or p["left"] <= 0:
            return
        s = self.strats[p["rule"]]
        ex = s.exits
        if p["selling"]:
            if p.get("run") is not None:
                self._run_mark(p)
            # a trigger the strategy acts on (a dev sale or pull only where its exits have them) is acted on as
            # soon as the sale in flight is back
            if not p.get("exiting") and (trigger == "kill" or (trigger == "dev_sell" and ex.dev_sell)
                                         or (trigger == "pull" and ex.pull)):
                p["due"] = trigger
            return
        eng = self.eng
        tok = eng.tokens.get(p["mint"])
        if self.kill():
            return self._sell_all(p, t, "kill")
        if trigger == "kill":
            return self._sell_all(p, t, "kill")
        if trigger == "dev_sell" and ex.dev_sell:
            return self._sell_all(p, t, "dev_sell")
        if trigger == "pull" and ex.pull:
            return self._sell_all(p, t, "pull")
        v = eng.sale_value(tok, p["left"], eng.cost_of(s.name))
        if v is None:
            return
        basis = p["cost_l"] * p["left"] / p["tokens"]
        mult = v / basis if basis > 0 else 0.0
        p["mark_l"] = v
        p["peak"] = max(p["peak"], mult)
        if p.get("run") is not None:                          # Y11: the rest has only its own exits
            return self._run_check(p, t, mult)
        if ex.risk and tok is not None and t - p["last_risk_ms"] >= RISK_EVERY_MS:
            p["last_risk_ms"] = t
            pb = eng.prob(ex.risk[0], eng.features(tok, int(t)))
            if pb is not None and pb[0] >= ex.risk[1] * pb[1]:
                return self._sell_all(p, t, "risk")
        if ex.hazard and tok is not None and p["left"] == p["tokens"]:
            hz = self.hazard(p, s, tok, t, v)
            if hz:
                return self._sell_all(p, t, "hazard")
            if hz is not None:
                return None                               # the models decide; no price exits (plan section 2)
        if mult <= 1 - ex.sl:
            return self._sell_all(p, t, "stop")
        if ex.lock is not None and self._lock(p, t, mult, ex.lock):
            return None
        if ex.trail_after is not None and p["peak"] >= 1 + ex.trail_after and mult <= p["peak"] * (1 - ex.trail_gap):
            return self._sell_all(p, t, "trail")
        if ex.press_exit is not None and tok is not None and press_trigger(tok, t, p["land_ms"], *ex.press_exit,
                                                                            p.get("entry_pq", 0)):
            return self._sell_all(p, t, "press")
        while p["step"] < len(ex.ladder) and mult >= 1 + ex.ladder[p["step"]][0]:
            gain, share = ex.ladder[p["step"]]
            target_left = 0 if share >= 1 else int(p["tokens"] * (1 - share))
            amount = p["left"] - target_left
            p["step"] += 1
            if amount <= 0:
                continue
            exp = v * amount / p["left"]
            if target_left == 0:
                return self._sell(p, t, amount, int(TP_FLOOR * exp), "take")
            return self._sell(p, t, amount, int(TP_FLOOR * exp), "take_part")
        return None

    def _lock(self, p: dict, t: float, mult: float, lock: tuple) -> bool:
        """Y12's profit floor: the highest arm the peak has reached decides; a mark at or under its floor sells down
        to its share (all with min_out 0 as the stop, or a part, min_out 0 too). False when nothing is left to sell."""
        armed = [x for x in lock if p["peak"] >= 1 + x[0]]
        if not armed or mult > 1 + armed[-1][1]:
            return False
        share = armed[-1][2]
        amount = p["left"] - (0 if share >= 1 else int(p["tokens"] * (1 - share)))
        if amount <= 0:
            return False
        p.setdefault("lock_ms", int(t))
        p["lock_sales"] = p.get("lock_sales", 0) + 1
        if amount >= p["left"]:
            self._sell_all(p, t, "lock")
        else:
            self._lock_sell(p, t, amount)
        return True

    def _lock_sell(self, p: dict, t: float, amount: int) -> None:
        """Y12: a floor's partial sale, min_out 0; the rest keeps every exit."""
        p["lock_part"] = amount
        self._sell(p, t, amount, 0, "lock_part")

    def _time_stop(self, at: float, pid: int) -> None:
        p = self.pos.get(pid)
        if p is not None and p["state"] == "open" and p["left"] > 0:
            if p["selling"]:
                if not p.get("exiting"):
                    p["time_due"] = True
                return
            if self._time_moved(p, at):
                return
            self._time_exit(p, at)

    def _time_exit(self, p: dict, at: float) -> None:
        """The time stop: everything, or with a runner (Y11) all but the rest."""
        rn = self.strats[p["rule"]].exits.runner
        keep = int(p["tokens"] * rn[0]) if rn is not None and p.get("run") is None else 0
        amount = p["left"] - keep
        if keep <= 0 or amount <= 0:
            return self._sell_all(p, at, "time")
        p["run"] = {"from_ms": int(at), "keep": keep, "high": 0.0, "part_tokens": 0, "part_l": 0, "part_fee_l": 0,
                    "got_l": 0, "fee_l": 0}
        self._run_mark(p)
        self.eng.push(p["land_ms"] + rn[3] * 1000, "pipe", (self, "_run_end", p["pid"]))
        self._run_sell(p, at, amount)

    def _run_sell(self, p: dict, t: float, amount: int) -> None:
        """Y11: the time stop's sale of all but the rest, min_out 0 as every protective exit."""
        p["run_part"] = amount
        self._sell(p, t, amount, 0, "time_part")

    def _run_mark(self, p: dict) -> float | None:
        """Y11: the rest's value now (its sale after the fee) over its cost; the high since the time stop follows it,
        also while the 80 % sale is in flight."""
        rn = p["run"]
        v = self.eng.sale_value(self.eng.tokens.get(p["mint"]), rn["keep"], self.eng.cost_of(p["rule"]))
        basis = p["cost_l"] * rn["keep"] / p["tokens"]
        if v is None or basis <= 0:
            return None
        mult = v / basis
        rn["high"] = max(rn["high"], mult)
        return mult

    def _run_check(self, p: dict, t: float, mult: float) -> None:
        """Y11: the rest exits at its stop under the entry, or, once its high since the time stop was above the
        entry, at its fall from that high (the hard stop is _run_end)."""
        rn, (_, stop, gap, _) = p["run"], self.strats[p["rule"]].exits.runner
        rn["high"] = max(rn["high"], mult)
        if mult <= 1 - stop:
            return self._sell_all(p, t, "run_stop")
        if rn["high"] > 1 and mult <= rn["high"] * (1 - gap):
            return self._sell_all(p, t, "run_trail")
        return None

    def _run_end(self, at: float, pid: int) -> None:
        """Y11: the rest's hard stop, landing + the runner's last field."""
        p = self.pos.get(pid)
        if p is None or p["state"] != "open" or p["left"] <= 0 or p.get("run") is None:
            return
        if p["selling"]:
            if not p.get("exiting"):
                p["due"] = "run_time"
            return
        self._sell_all(p, at, "run_time")

    def _time_moved(self, p: dict, at: float) -> bool:
        """Y7's later time stop (Exits.time_after_step_s): once a ladder step has filled (a sale landed while
        the position is still open), the time stop is landing + time_after_step_s; True when that is still
        ahead, and the time stop is then set for it."""
        after = self.strats[p["rule"]].exits.time_after_step_s
        if after is None or p["legs"] == 0:
            return False
        due = p["land_ms"] + after * 1000
        if at >= due:
            return False
        self.eng.push(due, "pipe", (self, "_time_stop", p["pid"]))
        return True

    def _sell_all(self, p: dict, t: float, why: str) -> None:
        p["exiting"] = True
        if p["exit_why"] is None or why in ("kill",):
            p["exit_why"] = why
        self._sell(p, t, p["left"], 0, why)

    def _sell(self, p: dict, t: float, amount: int, floor_l: int, why: str) -> None:
        p["selling"] = True
        p["exit_signal_ms"] = int(t)
        if why == "take" and p["exit_why"] is None:
            p["exit_why"] = "take"
        o = Order(p["pid"], "sell", p["mint"], "pool" if self._pool(p) else "curve", amount, floor_l, int(t), why,
                  p["legs"])
        self._event("sell_sent", p, order=o)
        self.exec.sell(o)

    def _pool(self, p: dict) -> bool:
        tok = self.eng.tokens.get(p["mint"])
        return tok is not None and not tok.on_curve

    def flatten(self, t: float) -> None:
        """The kill switch: sell everything open now (a sale in flight is followed by one for the rest)."""
        for p in list(self.pos.values()):
            if p["state"] == "open" and p["left"] > 0:
                self.check(p["pid"], t, "kill")

    def poll(self, now: float) -> None:
        """The live books' clock: the executor's results, and the kill switch between trades."""
        self.exec.poll(now)
        if self.kill():
            if not self.flattened:
                self.flattened = True
                self.flatten(now)
        else:
            self.flattened = False

    # ------------------------------------------------------------ close
    def _unindex(self, p: dict) -> None:
        s = self.by_mint.get(p["mint"])
        if s is not None:
            s.discard(p["pid"])
            if not s:
                self.by_mint.pop(p["mint"], None)

    def _close(self, p: dict, at: float) -> None:
        self.pos.pop(p["pid"], None)
        self._unindex(p)
        eng = self.eng
        tok = eng.tokens.get(p["mint"])
        risk = self.risk[p["rule"]]
        risk.release(p["pid"])
        pnl = p["proceeds_l"] - p["cost_l"] - p["fees_l"]
        risk.booked(at, pnl)
        stake = p["stake_l"] or 1
        rec = {k: p.get(k) for k in ("rule", "family", "mint", "name", "symbol", "created_ms", "signal_ms",
                                     "land_ms", "exit_signal_ms", "exit_why", "prob", "gap", "age_s", "progress",
                                     "signal_price", "entry_price", "legs", "pid")}
        rec.update(exit_ms=int(at), exit_price=tok.price() if tok else 0.0, proceeds_sol=p["proceeds_l"] / C.LAMPORTS,
                   pnl_sol=pnl / C.LAMPORTS, ret=pnl / stake, hold_s=(at - p["land_ms"]) / 1000,
                   stake_sol=stake / C.LAMPORTS,
                   dev_dumped=bool(tok and tok.dev_dumped and not p.get("dev_dumped_at_entry")),
                   breaks=(tok.breaks - p.get("breaks0", 0)) if tok else 0,
                   migrated=bool(tok and tok.complete_t is not None and tok.complete_t <= at),
                   lat_buy_ms=self.lat.pop(p["pid"], None),
                   slip=(p["entry_price"] / p["signal_price"] - 1) if p.get("signal_price") else None,
                   book=self.name)
        rn = p.get("run")
        if rn is not None:                                 # Y11: the rest on its own (only for a runner's rest)
            rest_cost = p["cost_l"] * rn["keep"] / p["tokens"]
            pro_rata = rn["part_l"] * rn["keep"] / rn["part_tokens"] if rn["part_tokens"] else 0.0
            rec.update(run_from_ms=rn["from_ms"], run_high=rn["high"], run_cost_sol=rest_cost / C.LAMPORTS,
                       run_pnl_sol=(rn["got_l"] - rn["fee_l"] - rest_cost) / C.LAMPORTS,
                       run_vs_time_sol=(rn["got_l"] - rn["fee_l"] - pro_rata) / C.LAMPORTS)
        if p.get("lock_ms") is not None:                  # Y12: only where a floor fired
            rec.update(lock_ms=p["lock_ms"], lock_sales=p["lock_sales"], peak=p["peak"])
        self.closed.append(rec)
        if self.record:
            eng.closed.append(rec)
        if self.on_close is not None:                      # booked first, so the card's day P&L holds this trade
            self.on_close(rec)
        self._event("closed", p, rec=rec)

    def mark_gap(self) -> None:
        for p in self.pos.values():
            p["gap"] = True

    def status(self) -> dict:
        return {"book": self.name, "executor": self.exec.kind, "open": len(self.pos),
                "exposure_sol": {k: r.exposure() / C.LAMPORTS for k, r in self.risk.items() if r.held},
                "day_pnl_sol": {k: r.day_pnl_l / C.LAMPORTS for k, r in self.risk.items() if r.day_pnl_l}}


def env_limits() -> Limits:
    """Limits a live owner may set lower in the environment (never above the hard caps)."""
    def f(name, default):
        try:
            return float(os.environ.get(name, default))
        except ValueError:
            return default
    return Limits(f("PYTHIA_PUMPFUN_STAKE_SOL", HARD_STAKE_SOL), int(f("PYTHIA_PUMPFUN_MAX_OPEN", HARD_MAX_OPEN)),
                  f("PYTHIA_PUMPFUN_MAX_EXPOSURE_SOL", HARD_MAX_EXPOSURE_SOL),
                  f("PYTHIA_PUMPFUN_MAX_DAILY_LOSS_SOL", HARD_MAX_DAILY_LOSS_SOL)).capped()
