# X14 r2: an order-flow exit for the live P_pool0 at today's latency: pre-registration (2026-10-29)

Written and committed before any replay, model or exit below was computed. Code (next commit):
`lab/pumpfun_rt/flowexit.py` (the replay, the paths, the step features, the measurements, the exits, the
evaluation), tests `tests/test_pumpfun_flow_exit_x14r2.py`. Paper only: nothing here holds a wallet, reads a key,
signs or sends anything; the live service, its executor, its exits, its sizing and its confirmation file are not
touched; the live executor's files (`ledger.csv`, `orders.jsonl`, `measured.jsonl`) are only read, never a key or
the wallet. A change to anything below after the first result is a new trial with a new name.

## Why

The owner asked (2026-10-29) whether order flow would help. On the exchanges three studies said no
(`taker_imbalance_xs`, `depth_signal_o1`, `m1_flow`); not repeated. On pump.fun every swap is on chain and the
engine sees the flow. It hurts at the exit: the 20 EUR live test of `P_pool0` (since 2026-10-29 13:26 UTC, 0.05 SOL,
1 open) took 4 stops in its first 14 trades that landed at -20 % to -33 % instead of the stop. X14 found the
5-minute dump predictable (AUC 0.87) but had 3 h 48 min of record; Y8's sell-pressure exit leaned negative at a
latency where -20 % stops landed at -43 %. The live sale now lands a median 0.6 s after its signal.

## What was looked at before this plan

Disclosed: X14's, Y7's, Y8's, Y11's and the live twin's reports; the live executor's records since 2026-10-29
13:26 UTC (the latencies and fees below, the ledger's 15 stop exits and their returns, -2 % to -93 %); the owner's
note on "Zaio" (landed 26.5 % under the signal price, stopped 10 s later at -27.2 %). For the buyback (owner note
3), on 2026-10-27 and 28 the pool trades of migrated coins were grouped by signer: signers that trade one pool
only, buy only, at least 8 times, were found in 923 of 1,497 migrated pools, their last buy mostly 300 to 360 s
after the migration (the histogram of that last buy was seen; no price, no return, no exit). The record does not
hold `base_supply` or `can_boost`: the collector decodes them (`events.py`) but `store.py` keeps neither, so the
buyback is inferred from that signature (section 4). Nothing else: no exit, model or book of this plan was run.

## 1. Record, entries, scenarios

- **Record**: every recorded UTC day from the start (2026-10-20 16:40 UTC) to the cutoff **2026-10-29 18:00 UTC**;
  P_pool0 signals until 17:50 UTC, so every position closes inside the record. No warm-up days (none before).
- **Entries, the full replay**: every P_pool0 signal (`pipeline.BY_NAME["P_pool0"]`, its checks unchanged: a plain
  SOL pool, the pool state known, depth), at **0.05 SOL**, **no book limit** (a study-only Risk that allows every
  entry; the books of section 6 apply the limits afterwards). The buy lands one draw of the scenario's buy latency
  after the signal (key P_pool0, mint, buy: the same draw for every exit) and fills as the paper executor does.
  Every exit below is simulated on the same entries: **paired by entry**. A failed buy is an entry that lost its
  transaction fee, the same in every variant.
- **Paths**: for every filled entry, every pool trade of the coin from the signal to the landing plus 420 s, with the
  pool's state after it (base, effective quote, fee), its side, size and signer (hashed, never stored).
- **(N) today's latency, judged**: Y5's kernel density in log space (`reallat.LogKDE`) of the live executor's
  P_pool0 fills, `measured.jsonl`, what = fill, mode test, logged from 2026-10-29 13:26 UTC to the cutoff, buys and
  sales apart, each value clipped to 0.2 to 60 s (a sale cannot land in the slot it was sent in):

  | side | lat_ms as logged |
  |---|---|
  | buys (33) | 1036, 2177, 1065, 1395, 1778, 1205, 588, 3672, 1127, 659, 1721, 1375, 1666, 2928, 1353, 1586, 722, 2851, 1353, 2966, 4420, 754, 823, 1088, 1565, 1221, 2669, 1219, 3717, 5125, 1341, 3278, 1992 |
  | sales (32) | 600, 1553, 411, 458, 788, -17, 130, 648, 635, 607, -812, 3449, 546, 407, 7825, 1005, 416, 377, 906, 546, 644, 407, 1505, 579, 429, -477, 2030, 645, 761, 538, 5599, 590 |

  Medians after the clip: buy 1.40 s, sale 0.60 s. Fee per transaction: the mean of the 64 `fee` rows of the same
  window, 108,837 lamports (0.000109 SOL).
- **(O) the old latency, a diagnostic only**: Y8's registered points (`exits8.SENDER_BUY_MS`, `SENDER_SELL_MS`, 26
  each, clipped 1 to 60 s, buy median 10.0 s, sale 4.4 s), 0.001005 SOL per transaction. Its own entries (its buy
  latency), its own models. Reported, never judged.
- **L**, the sale latency the labels skip: the median of the scenario's clipped sale points, 0.595 s at (N), 4.371 s
  at (O).

## 2. Measured first, before any exit (owner note 2)

**(a) One-transaction stops.** For every stop exit of P_pool0 (X0) in the full replay at (N), and for every live
P_pool0 stop since 13:26 found in the record: the pool trade that first took the position's sale value (all its
tokens, after the pool fee) to or under 80 % of its cost, and the "transaction" it belongs to (the record keeps no
signature in the pool table: the run of consecutive pool trades of that slot by the same signer). The stop is a
**one-transaction stop** when the value just before that transaction was above 80 % of cost and the value right
after it is at or under the value the stop's sale landed at (before the fixed fees): that one transaction did all
the damage, and no exit reacting to anything after it can do better. Reported: their share (also with the slot
instead of the signer run), and the mean landing of the one-transaction stops against the others. If they are the
large majority (over two thirds), the report says so and caps what a reactive exit can save.

**(b) The live stops split.** For every live P_pool0 stop since 13:26 whose sale is found in the record (the pool
sale of that coin with exactly the tokens sold, at or after the stop's signal, never the wallet's address), the gap
from -20 % to the fill, in points of the cost, as five parts that add up: the overshoot at the trigger (the value at
the signal against -20 %), the price path during the latency (the pool's price at the signal against the price
before our sale, without a sandwich's front leg), a same-slot sandwich (a signer that sold in our slot just before
us and bought in it just after us: the price move of its front leg), our own price impact (the pool's output for
our tokens against their value at the price before our sale), and the pool fee; the transaction fees apart. The
slippage setting: our sales go with min_out 0 (`limit_l` 0 in `orders.jsonl`), so it refuses nothing and its part
is 0 by construction; reported as such.

**(c) The buyback (owner note 3).** Per migrated plain SOL pool in the record: the inferred BOOST buyer (section
4), its first and last buy after the migration, how many buys, the SOL; the pools with one; the distribution of the
buyback's end; and the pool's price around it: the mean and median log change from 30 s before the last buy to it,
and from it to 30, 60 and 120 s after.

## 3. Step features and the models

**Step rows**: for every filled entry at the landing and then at every pool trade at least 1 s after the step
before, up to 300 s after the landing. Features: X14's `early.STEP_FEATURES` (the engine's `Tracker.step_features`,
unchanged) and, new:

- the signal to landing window (constant per position, owner's "Zaio" note): `sl_move` the log of the pool price at
  the landing over the price at the signal; `sl_net` net SOL into the pool (buys minus sells) between them over the
  pool's SOL at the signal; `sl_sells` the sells; `sl_big` the largest sale over the pool's tokens at the signal;
- **dump-at-risk** `dar` = 1 - (x / (x + H))^2, x the pool's token reserve then, H the unsold tokens (the engine's
  holdings) of the grouped early wallets: the devs, the snipers (bought within 2 s of the creation) and every group
  of two or more buyers sharing one slot in the coin's first 30 s on the curve (a bundle). Funders are not in the
  record (the transfer table starts 2026-10-29): not used. `dar_h` = H over the supply;
- a **Hawkes-style sell intensity** of the same wallets: the sum over their pool sales so far of mark x exp(-(t -
  t_i) / tau), mark = tokens sold over the pool's token reserve before the sale, `hk5` (tau 5 s) and `hk30` (30 s);
- the buyback: `bb_seen` (a buyer identified), `bb_buys`, `bb_since_s` (seconds since its last buy), `bb_on` (its
  last buy within 45 s).

**Labels, past the latency** (owner note 2): with v(s) the net sale value of all tokens at the pool's state at s,
`dump10` = 1 when the lowest v over (t + L, t + L + 10 s] is at or under 75 % of v(t + L); `up30` = the log of the
highest v over (t + L, t + L + 30 s] over v(t + L), at least 0. A drop inside (t, t + L] is not a label.
|L_loss| = the mean of -log(lowest / v(t + L)) over the training steps with a dump.

**Models**: X14's, unchanged in kind: LightGBM classifier calibrated (`model.fit`) for `dump10`, LightGBM regression
(`exitpol.fit_reg`) for `up30`, on the features above. **Walk-forward by UTC day**: the steps of day d are scored by
models fitted on the steps of the days before d only (their label windows inside those days); the first day has no
model (HZ sells nothing extra there). k* is chosen in sample on these walk-forward scores; the out-of-sample days
use models refitted each day on every earlier day, k* fixed.

## 4. The exits (7 trials)

Every variant is P_pool0's exits (+30 % sells all, -20 % stop sells all, both on the sale value after the pool fee
over the cost, checked at every pool trade and at the landing; 300 s time stop after the landing; no dev-sell or pull
exit) plus at most one change. A sale is signalled at the pool trade (or the time), lands one draw of the scenario's
sale latency later (key P_pool0, mint, sell, leg: the same draw in every variant for the same leg) at the pool's
state then, all tokens, min_out 0; a take sale that would land under half its expected proceeds fails, costs its
fee and leaves the take due (as `pipeline.TP_FLOOR`). Nothing else is sent while a sale is in flight.

| id | variant | the change | fitted in sample (days 2026-10-20 to 23) |
|---|---|---|---|
| X0 | P_pool0 as it is | none | none |
| HZ | the hazard exit HZ(k*) | at a step (at most once a second, full position) sell all when the predicted `up30` is below k x P(`dump10`) x \|L_loss\| | k* in 0.5, 1, 2, 4 |
| F1 | outflow burst | sell all when the pool's net SOL outflow over (t - 3 s, t] (trades since the landing) exceeds theta x the pool's SOL at the landing | theta in 0.02, 0.04, 0.06, 0.08, 0.12 |
| F2 | dumping as the buy lands | at the landing, sell all when the pool's price is at least theta under its price at the signal | theta in 0.05, 0.10, 0.15, 0.20 |
| DAR | dump-at-risk | sell all at a trade when `dar` is at or above theta | theta at the 50th, 75th, 90th, 95th percentile of `dar` over the in-sample path points |
| T | time stop | the time stop at T s instead of 300 | T in 180, 240, 270 |
| BB | buyback | sell all when an identified buyback has stopped (no buy from its buyer for 45 s) or, while it still buys, the value falls 10 % under its high since the landing; no buyer identified: X0 | none (45 s and 10 % fixed) |

**The inferred BOOST buyer** of a pool, online: a signer whose every trade in this pool so far is a buy, with at
least 3 buys, its first within 120 s of the migration, that traded no other pool in the replay before. The first
such signer is the pool's buyer; it is never re-chosen.

Each fitted parameter is the in-sample value with the highest mean return per entry at (N); ties to the earlier
in the list. F1 and F2 are the "at most two simple flow rules". In sample is only reported.

## 5. Verdict

Out of sample = signals on 2026-10-24 to the cutoff (6 UTC days). Judged at (N) on the full replay. A variant
**passes** only if all three hold:

1. its mean return per entry (after every cost, failed buys included) is higher than X0's on the same entries;
2. the day-block bootstrap 90 % band of the paired mean difference (variant minus X0 per entry; whole UTC days
   resampled, 5,000 draws, seed 11) lies above 0; with fewer than 5 out-of-sample days with entries, n/a and no;
3. the mean landing loss of its stop exits (their mean return, every cost) is smaller than X0's stops' (a variant
   without stop exits holds this).

Trades open across a gap in the record are kept (the same for every variant); without them, a robustness line.
(O) is a diagnostic line. If more than one passes, the one with the highest out-of-sample mean is the pick.

## 6. Reported, per variant (out of sample, (N); (O) the same, diagnostic)

Entries, failed buys, mean and median return per entry, total P&L (SOL), win rate, the exits by kind, the stop exits
(number, mean and median return, mean below -20 %), the paired difference to X0 and its band, the mean on the
entries X0 stopped (paired), capture of the best exit (the realised gain over the best net sale of all tokens at any
pool trade within 300 s of the landing, minus the cost and two fees; ratio of sums over entries whose best is above
0), the in-sample numbers and the fitted parameter, and the hazard models' out-of-sample AUC and Brier skill.

**Books at two sizings** (on the same entries in signal order, `pipeline.Risk` with the limits; an entry's result
at 0.1 SOL is twice its result at 0.05 plus one more fee per transaction, the impact not simulated again):
the live one, **0.05 SOL, 1 open, daily loss 0.12 SOL**; and **0.1 SOL, 4 open, 1.0 SOL a day**, so the loss limit
does not starve the sample (Y8's lesson). Per book: entries taken, skipped by the limits, mean, total, maximum
drawdown. Reported, not judged.

## 7. Trials

In R5's registry, family pumpfun, before the first number (`flowexit.trials()`): the 7 exits
`pumpfun:flow_x14r2:{X0,HZ,F1,F2,DAR,T,BB}` and, counted only, the measurements
`pumpfun:flow_x14r2:{one_tx,live_stop_split,buyback_end,old_latency}`. 11 in all, no Sharpe.

## 8. If one passes

It becomes a paper strategy in `pipeline.STRATEGIES` next to P_pool0 (`P_pool0_<id>`, 0.05 SOL, PAPER ONLY), so it
runs forward beside the live bot and the live twin; a variant that needs models it cannot load trades P_pool0's
exits. The live bot, its exits and its files are not touched: whether it goes live is the owner's call after the
shadow. If none passes, nothing is added.

## 9. Too early, in any case

Nine days of record, six out of sample, a latency from 32 live sales over four and a half hours. A pass here is a
reason for a shadow, not for money.
