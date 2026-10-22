# pump.fun rules at the measured latency (Y5): pre-registration (2026-10-22)

Written and committed before any replay below was computed. Code:
`lab/pumpfun_rt/reallat.py` (the latency models and the run). Paper only:
nothing here holds a wallet, reads a key, signs or sends anything, and the
live service, its executor and its confirmation file are not touched. A change
to anything below is a new trial with a new name.

## Why

The real-time study (`results/pumpfun_realtime_plan.md`, plan addendum 2 for
the pipeline strategies) fills every paper order 0.4 to 3 s after its signal
(lognormal, median 1 s). The owner's capped live test of `P_cmig_model`
(stake 0.03 SOL, curve venue) measured something else on mainnet, and all five
of its trades lost money. The question: is any rule or pipeline strategy the
study has positive after costs at the latency we actually have, and what would
a faster send path change?

## What was looked at before this plan

Disclosed, because it shaped the plan: the live test's own files (the
executor's fills and fees, its orders, its ledger of five trades, the
measured-execution summary) and the study's last daily report (readiness and
out-of-sample means of every rule at the registered fill model, 0.1 SOL). No
replay at any latency other than the study's own was computed.

Measured (the executor's fills, 2026-10-22 17:09 to 19:21 UTC):

| what | values |
|---|---|
| buy, signal to landing | 2,391, 4,852, 8,381, 8,770 ms (4 fills; median 6,616) |
| sale, signal to landing | 6,940, 11,817, 17,179 ms (3 fills the stream saw) |
| fee per transaction | 0.001005 SOL (5,000 base + 0.001 priority), every one of 7 |
| buy slippage against the signal price | median +1.3 % |

Not used as latency points, disclosed: a fourth sale that the stream missed
(read back from the chain, its block time has whole seconds only), and a
fifth buy that did not land within the executor's window and landed later
(found in the wallet). The second says the real tail is longer than any model
below; no model here fails a buy for being late, so (b) flatters.

## 1. Latency model (`reallat.py`)

Every draw stays reproducible and is keyed as in the study (rule, token, leg):
one uniform u per key, mapped through the scenario's quantile function, so
the same signal gets the same rank of draw in every scenario.

- **Measured, per side** (buys and sales separately): a kernel density of the
  measured latencies in log space (a lognormal kernel on each point), the
  bandwidth by Silverman's rule on the logs (0.9 x min(sd, IQR / 1.34) x
  n^-0.2) with a floor of 0.25, so the tails are wider than the handful of
  points; clipped to 1 s to 60 s. Its quantile function is the inverse of the
  mixture's distribution function on a fine grid. With 4 buys and 3 sales
  this is the "empirical quantiles widened"; its median, 10 % and 90 % points
  are reported next to the measured ones.
- **Fee and stake**: 0.001005 SOL per transaction (as measured; it equals the
  study's base fee plus 0.001 SOL priority fee), stake 0.03 SOL for every rule
  and strategy in every scenario (rules: the engine's stake; strategies:
  their stake, still capped at 2 % of the curve's virtual SOL).

## 2. Scenarios

Only the fill latency (and in (c+tip) the fee) changes; signals, filters,
models, exits, limits, slippage limit (30 %) and fill arithmetic are the
study's.

| scenario | buys land after the signal | sales land after the exit signal | fee per transaction |
|---|---|---|---|
| (a) `A` study | lognormal median 1 s, sigma 0.5, clipped 0.4 to 3 s | the same | 0.001005 SOL |
| (b) `B` measured | the measured buy model above | the measured sale model above | 0.001005 SOL |
| (c) `C` fast send path | lognormal median 1.5 s, sigma 0.175, clipped 1 to 2 s | the same | 0.001005 SOL |
| (c+tip) `Ct` | as (c) | as (c) | 0.001010 SOL (an extra 0.000005 SOL tip) |

(c) is what a stake-weighted sending service would plausibly give; it is an
assumption, not a measurement.

## 3. Replay

The study's own procedure (`study.py`) on the recorded days, with no rule or
strategy added or changed:

- Record: every recorded day up to **2026-10-22 21:00 UTC** (fixed here);
  warm-up from earlier days where they exist (none: the record starts
  2026-10-20). The split is the midpoint of the record's time span; in sample
  before, out of sample after (trades signalled after the split).
- Pass 1 (in sample), exactly the study's: the study's registered fill model
  and 0.1 SOL, every rule and the decision rows; the in-sample pick and the
  models (the filters' and X14's) are fitted on in-sample rows only. The
  models stay the same in all four scenarios (they are part of the
  strategies as registered).
- Pass 2 (whole record): the 22 rules, the model filter on the in-sample pick,
  and the 12 pipeline strategies, each once per scenario (35 x 4 = 140
  books), at 0.03 SOL. A scenario's books share signals; the pipeline books
  keep their registered risk limits (5 open at most per strategy).

**Trials: 35 x 4 = 140**, added to `strategies.N_TRIALS` (the global pool the
study's deflation reads).

## 4. Reported per scenario and rule (out of sample)

Entries (closed trades plus failed buys, each failed buy a trade that lost its
fee), failed buys, mean and median return per trade over the stake after
every cost, win rate (P&L above zero), total P&L in SOL at 0.03 SOL, the
hour-block bootstrap 90 % band of the mean (`study.boot_mean`, n/a under 10
hours), and the deflation:

- **the study's**: deflated p of the out-of-sample daily P&L against the pool
  (`study.deflated_p`, g5: above 0.95); n/a under 5 days, which is the case
  on this record;
- **stand-in while it is n/a**: the hour-block z of the mean (the mean over
  the band's width / 3.29) above the one-sided Bonferroni bar over the whole
  pool, z > Phi^-1(1 - 0.05 / n_total).

A rule is **positive** at a scenario when its mean is above zero, the band's
lower end is above zero and it passes the deflation (the study's where it can
be computed, else the stand-in), with 30 or more out-of-sample entries.

Also reported: for (b) the replay's median buy slippage of `P_cmig_model`
against the measured +1.3 %, and the five live tokens where the replay
signalled them (descriptive); the value of the fast path per rule, mean (c)
minus mean (b) with the hour-block band of the difference (`study.boot_diff`)
and the P&L difference in SOL; the tip's cost, (c+tip) minus (c).

**Better than `P_cmig_model`** at (b): 30 or more entries, a higher mean and
the hour-block band of the difference above zero. Reported, nothing changed:
the live book and its confirmation file are the owner's decision.

## 5. Too early

The record is about two days, so the out-of-sample half is about a day. The
bar of the study (300 trades over 14 days) cannot be met; the verdict says
whether any rule is positive at (b) at all and how far (c) moves the means.
