"""The pre-registered rules of the real-time pump.fun study (results/pumpfun_realtime_plan.md).

Written down on 2026-10-20 before any of them was computed on recorded data.
A change is a new rule with a new name, never an edit; every rule here is one
trial in the lab's global deflation pool, the model filter one more.

Every rule stakes STAKE_SOL a trade, at most MAX_OPEN open at once (a signal
while full is skipped and counted), trades only plain SOL-quoted curves
(no mayhem mode, no other quote mint, no fee-free curve with erratic
reserves), enters once per token, and exits on the first of: take profit
(the position's sale value, net of the fee, at or above stake x (1 + tp)),
stop loss (at or below stake x (1 - sl)), or the time stop (hold_s after the
buy landed). Exits are checked on every trade of the token and the sale
lands one latency draw later (curve.py), at whatever the curve then pays.

Families (signal time in brackets):

  A  snipe      [the creation transaction is received]  every new token, or a
                filter known at creation: the dev buy, or a creator whose
                earlier token completed its curve while we watched.
  B  pressure   [creation + W s]  enough unique buyers (the dev not counted)
                and net SOL inflow in the first W seconds, the dev not selling.
  C  momentum   [the trade that makes it]  X unique buyers within Y seconds of
                creation while the curve is under half done, the dev not selling.
  D  premigrate [the trade that crosses]  curve progress crosses p; sold on the
                curve or, if it completes first, into the PumpSwap pool.
  E  postmigrate [migration + d s]  bought in the PumpSwap pool after migration.
"""

from __future__ import annotations

from dataclasses import dataclass, field

STAKE_SOL = 0.1
MAX_OPEN = 50
PLAN_DATE = "2026-10-20"


@dataclass(frozen=True)
class Rule:
    name: str
    family: str
    entry: str                       # create | checkpoint | momentum | progress | migration
    tp: float
    sl: float
    hold_s: float
    p: dict = field(default_factory=dict, hash=False, compare=False)
    label: str = ""

    def wants_create(self, tok) -> bool:
        """Family A filters, known at creation (the dev buy is in the same transaction)."""
        f = self.p.get("filter")
        if f == "all":
            return True
        if f == "devbuy":
            return self.p["lo"] <= tok.dev_buy_l / 1e9 <= self.p["hi"]
        if f == "creator_migrated":
            return (tok.hist or {}).get("migrated", 0) >= 1
        return False

    def wants_checkpoint(self, tok, t: int) -> bool:
        """Family B at creation + W s."""
        buyers = tok.outside_buyers()
        net = (tok.buy_l - tok.sell_l) / 1e9
        return buyers >= self.p["buyers"] and net >= self.p["net_sol"] and tok.dev_sold == 0

    def wants_momentum(self, tok, t: int) -> bool:
        """Family C after each trade."""
        if (t - tok.t0) > self.p["within_s"] * 1000 or tok.dev_sold > 0 or tok.progress() >= 0.5:
            return False
        return tok.outside_buyers() >= self.p["buyers"]

    def wants_progress(self, tok, t: int) -> bool:
        return tok.on_curve and tok.progress() >= self.p["at"]


def _exits(a: tuple, b: tuple) -> list[tuple[str, float, float, float]]:
    return [("x1", *a), ("x2", *b)]


def _build() -> list[Rule]:
    rules: list[Rule] = []
    # A: snipe at creation
    for fname, fp, flabel in (("all", {"filter": "all"}, "every new token"),
                              ("dev", {"filter": "devbuy", "lo": 0.5, "hi": 5.0}, "dev buy 0.5 to 5 SOL"),
                              ("cmig", {"filter": "creator_migrated"}, "creator had a token complete its curve")):
        for x, tp, sl, hold in _exits((0.5, 0.3, 15), (1.0, 0.4, 60)):
            rules.append(Rule(f"A_{fname}_{x}", "A", "create", tp, sl, hold, fp,
                              f"snipe at creation, {flabel}; +{tp:.0%} / -{sl:.0%} / {hold:.0f} s"))
    # B: pressure at creation + W
    for w, buyers, net in ((3, 5, 1.0), (10, 10, 2.0)):
        for x, tp, sl, hold in _exits((0.5, 0.3, 30), (1.0, 0.4, 120)):
            rules.append(Rule(f"B_w{w}_{x}", "B", "checkpoint", tp, sl, hold,
                              {"w_s": w, "buyers": buyers, "net_sol": net},
                              f"at creation + {w} s: {buyers}+ unique buyers, {net:g}+ SOL net in, dev not sold; "
                              f"+{tp:.0%} / -{sl:.0%} / {hold:.0f} s"))
    # C: momentum
    for buyers, within in ((20, 60), (50, 300)):
        for x, tp, sl, hold in _exits((0.5, 0.25, 120), (1.0, 0.35, 600)):
            rules.append(Rule(f"C_{buyers}in{within}_{x}", "C", "momentum", tp, sl, hold,
                              {"buyers": buyers, "within_s": within},
                              f"{buyers} unique buyers within {within} s, curve under half, dev not sold; "
                              f"+{tp:.0%} / -{sl:.0%} / {hold:.0f} s"))
    # D: pre-migration
    for at in (0.8, 0.9):
        for x, tp, sl, hold in _exits((0.3, 0.2, 300), (0.6, 0.3, 1800)):
            rules.append(Rule(f"D_p{int(at * 100)}_{x}", "D", "progress", tp, sl, hold, {"at": at},
                              f"curve progress crosses {at:.0%}; +{tp:.0%} / -{sl:.0%} / {hold:.0f} s"))
    # E: post-migration
    for d in (0, 60):
        for x, tp, sl, hold in _exits((0.3, 0.2, 300), (1.0, 0.4, 1800)):
            rules.append(Rule(f"E_d{d}_{x}", "E", "migration", tp, sl, hold, {"delay_s": d},
                              f"PumpSwap pool, migration + {d} s; +{tp:.0%} / -{sl:.0%} / {hold:.0f} s"))
    return rules


RULES: list[Rule] = _build()
BY_NAME = {r.name: r for r in RULES}
# The model filter on the in-sample pick is one more trial; the pipeline strategies
# (pipeline.STRATEGIES, plan addendum 2) are eight more, X14's four strategies four more
# (results/pumpfun_early_exit_plan.md), and X14's 16 early books and 38 exit policies 54 more.
MODEL_FILTER_TRIALS = 1
PIPELINE_TRIALS = 12
X14_TRIALS = 16 + 38
# Y3's speed tiers (results/pumpfun_speed_plan.md): 8 tiers x 5 filters x 3 exits, and addendum 1's tier S0r 15 more.
SPEED_TRIALS = 8 * 5 * 3 + 15
# Y5 (results/pumpfun_real_latency_prereg.md): the 22 rules, the model filter and the 12 pipeline strategies at
# four fill scenarios (the study's latency, the measured one, a 1.5 s send path, the same with a tip).
REAL_LATENCY_TRIALS = 35 * 4
# Y6 (results/pumpfun_pool0_prereg.md): E_d0_x1 as the pipeline strategy P_pool0, one more.
POOL0_TRIALS = 1
# Y7 (results/pumpfun_exit_runners_prereg.md): five new exits on P_pool0's entry (pipeline._build_y7) and P_pool0
# itself judged again at the latency measured since the Sender path, six books at the judged latency.
EXIT_RUNNER_TRIALS = 6
# Y8 (results/pumpfun_exits_y8_prereg.md): P_pool0 with a -10 % stop, a sell-pressure exit, an entry that waits up to
# 5 s for the pool's state, and the two combinations (pipeline._build_y8), five more.
EXITS_Y8_TRIALS = 5
# Y9 (results/pumpfun_select_y9_prereg.md): five filters on P_pool0's migrations (pipeline._build_y9), each judged under
# the live daily loss limit of 0.25 SOL and under the code's cap of 1.0 SOL, ten more.
SELECT_Y9_TRIALS = 5 * 2
# Y10 (results/pumpfun_trends_y10_prereg.md): two top-30 % filters on the models with the trend features and three trend
# strategies (pipeline._build_y10), each judged under the 0.25 SOL and the 1.0 SOL daily loss limit, ten more.
TRENDS_Y10_TRIALS = 5 * 2
# Y11 (results/pumpfun_runner_prereg.md): P_pool0_wait keeping 20 % after its time stop, two rest exits
# (pipeline._build_y11), each judged under the 0.25 SOL and the 1.0 SOL daily loss limit, four more.
RUNNER_Y11_TRIALS = 2 * 2
# Y12 (results/pumpfun_lock_prereg.md): P_pool0_wait with three profit floors (pipeline._build_y12), each judged
# under the 0.25 SOL and the 1.0 SOL daily loss limit at the paper model's and at the measured latency, twelve more.
LOCK_Y12_TRIALS = 3 * 2 * 2
# Y15 (results/pumpfun_freeride_prereg.md): P_pool0_wait with four free rides after the +30 % (pipeline._build_y15),
# each judged under the 0.25 SOL and the 1.0 SOL daily loss limit at the paper model's and at the measured latency.
FREE_Y15_TRIALS = 4 * 2 * 2
N_TRIALS = (len(RULES) + MODEL_FILTER_TRIALS + PIPELINE_TRIALS + X14_TRIALS + SPEED_TRIALS
            + REAL_LATENCY_TRIALS + POOL0_TRIALS + EXIT_RUNNER_TRIALS + EXITS_Y8_TRIALS + SELECT_Y9_TRIALS
            + TRENDS_Y10_TRIALS + RUNNER_Y11_TRIALS + LOCK_Y12_TRIALS + FREE_Y15_TRIALS)
# The rule the shadow book runs until the study has picked one (pick.json).
DEFAULT_PICK = "C_20in60_x1"
# The model filter: enter only when the calibrated probability that this entry,
# filled with latency and sold at the rule's horizon (30 s for holds up to a
# minute, else 5 minutes), ends above zero after costs is at least
# FILTER_LIFT times the training base rate.
FILTER_LIFT = 1.25


def checkpoints() -> list[tuple[str, float]]:
    """(rule, offset s) of every checkpoint rule."""
    return [(r.name, r.p["w_s"]) for r in RULES if r.entry == "checkpoint"]
