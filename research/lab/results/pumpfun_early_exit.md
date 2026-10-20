# pump.fun early detection and exit timing (X14)

PAPER ONLY. Nothing here holds a wallet, reads a key or sends a transaction;
every buy and sale is the curve or pool arithmetic of the recorded chain, with
latency, the token's fee and the priority fee (`lab/pumpfun_rt/curve.py`,
`pipeline.PaperExecutor`).

Pre-registration: `results/pumpfun_early_exit_plan.md`, committed before any
number below was computed. Code: `lab/pumpfun_rt/early.py` (rows, features,
labels, paths, step rows), `lab/pumpfun_rt/exitpol.py` (the 38 exit policies,
the hazard and upside models, the evaluation, the live models), the hazard
exit and the early filter in `pipeline.py`. Daily report:
`reports/pumpfun_rt/early_exit.md`.

## The record is hours, not days

The task said the server had collected about two days of every token. It has
not: the server's collector started on 2026-10-20 at 16:40 UTC, and the PC's
earlier 2 h 15 min are no longer on disk. The numbers below are on a read-only
copy taken at 20:28 UTC: **3 hours 48 minutes**, 7,897 tokens (3,741 on plain
SOL curves), 658,099 curve trades, 131 completed curves. The split for the
exit study is at 18:33 UTC, so about 2 hours are out of sample, and of those
only the positions whose 30 minutes were recorded count.

Everything is therefore **too early** by the lab's bar (14 days, 300 trades out
of sample, a band from at least 10 hours). The bootstrap bands are "n/a"
because there are 2 hours out of sample. The same jobs re-run all of this every
morning on the growing record; this write-up records the method and the first
reading, not a verdict.

How fragile the reading is: on a copy taken four minutes earlier (20:24) the
`peak3x` model was "useful" (AUC 0.768, Brier skill +0.043, beating the
logistic baseline in 3 of 3 folds); at 20:28 it is "not useful" (Brier skill
-0.074, 1 of 3 folds). Three of the five folds run at all, because a 1-hour
label plus the 10-minute embargo leaves the early folds without training rows.

## 1. Early detection

19,681 rows (every plain token at 5, 10, 20, 30 and 60 s and when its curve
passed 25, 50 and 75 %; 423 more dropped for a curve gap), 19,673 of whose
paper buys filled. Purged walk-forward over 5 folds by decision time, out of
fold:

| label | rate | AUC | logistic AUC | Brier skill | logistic | top 1 % precision (lift) | top 5 % (lift) | logistic top 5 % (lift) | verdict |
|---|---|---|---|---|---|---|---|---|---|
| mig1h: completes within 1 h | 1.6 % | 0.769 | 0.630 | +0.136 | -2.80 | 48 % (28x) | 13.6 % (8.0x) | 9.1 % (5.7x) | useful, 3 of 3 folds |
| peak3x from our landing | 3.3 % | 0.760 | 0.766 | -0.074 | +0.049 | 9.0 % (2.7x) | 9.5 % (2.9x) | 10.6 % (3.2x) | not useful |
| peak10x | 0.8 % | 0.391 | 0.305 | -0.041 | -0.012 | 8.0 % (5.2x) | 3.2 % (2.1x) | 1.6 % (1.0x) | not useful |
| alive5m: no dev or top-10 dump | 55.9 % | 0.874 | 0.814 | +0.424 | +0.269 | 100 % (1.8x) | 100 % (1.8x) | 99 % (1.8x) | useful, 5 of 5 folds |

What the first hours say:

- **Which tokens complete their curve is predictable early.** From the first 5
  seconds the top 5 % of tokens by P(mig1h) complete within the hour 5.9 % of
  the time against 0.9 % for all (lift 6.6); at 25 % progress the top 5 %
  complete 27 % of the time against 5 %. The logistic baseline ranks too but
  is badly calibrated (Brier skill -2.8: it extrapolates the hour of day and
  the market counts, which drift within a few hours).
- **Who dumps within 5 minutes is the easiest label** (AUC 0.87, Brier skill
  +0.42). The tokens rated safest are the ones where nothing happens.
- **A 3x from our landing price is rare (3.3 %) and only weakly ranked**
  (lift 2.9 at the top 5 %); 10x (0.8 %) is not ranked at all on this little
  data (AUC under 0.5, a handful of tokens).

**The paper books lose.** Entering the top of each model at realistic latency
(thresholds from the training scores, one entry per token, exit E0), out of
fold:

| label | book | trades | mean per trade | median | hit | P&L SOL | doubled latency |
|---|---|---|---|---|---|---|---|
| mig1h | LightGBM top 1 % | 16 | -4.0 % | -1.0 % | 6 % | -0.07 | -4.0 % |
| mig1h | LightGBM top 5 % | 71 | -8.6 % | -5.1 % | 13 % | -0.61 | -9.0 % |
| peak3x | LightGBM top 1 % | 10 | -27.4 % | -21.3 % | 0 % | -0.27 | -26.2 % |
| peak3x | LightGBM top 5 % | 155 | -11.4 % | -6.8 % | 10 % | -1.77 | -10.9 % |
| peak10x | LightGBM top 1 % | 16 | -0.1 % | -7.4 % | 6 % | -0.00 | -0.0 % |
| peak10x | logistic top 1 % | 33 | +0.2 % | -5.1 % | 15 % | +0.01 | -2.2 % |
| alive5m | LightGBM top 5 % | 250 | -5.1 % | -5.1 % | 0 % | -1.28 | -5.1 % |

All 16 books are in `reports/pumpfun_rt/early_exit.md`; one is above zero
(+0.2 % over 33 trades), none by more than noise. Knowing that a token is more
likely than most to complete or triple does not pay once we buy a second
after the signal and sell into whatever is left: the median trade loses the
round-trip cost (1.25 % fee a side, the priority fee, the impact paid twice).

## 2. Exit timing

Positions: every filled early-detection buy with 30 minutes recorded and no
gap, 9,431 in sample and 4,844 out of sample. **84 % of them are never worth
their cost at any trade in their first 30 minutes**, so for most positions the
best exit is "at once" and the capture ratio is a statement about the other
16 %.

The exit models out of sample (103,647 step rows): the hazard of a 25 % drop
within 10 s (rate 5.7 %) is ranked (AUC 0.755 against the logistic 0.711,
Brier skill +0.043); the upside over the next 30 s barely (R2 +0.039 against
the training mean, correlation 0.26). A dump step loses 44 % of the position's
value on average (|L| = 0.573 in logs).

Selected in sample (mean net return per position): HZ4+ev, the hazard policy
with the most eager k (sell when the predicted 30-second upside is below 4 x
P(dump in 10 s) x |L|), with the dev-sell and pull exits. Out of sample:

| policy | in-sample mean | out-of-sample mean | capture out of sample | P&L SOL (4,844 positions) |
|---|---|---|---|---|
| HZ4+ev (the pick, k* = 4) | -6.2 % | -5.6 % | +0.5 % | -27.2 |
| HZ4-ev | -7.1 % | -5.6 % | +3.2 % | -27.0 |
| HZ2+ev | -7.1 % | -6.1 % | +1.9 % | -29.7 |
| T30+ev (best baseline in sample: sell after 30 s) | -6.4 % | -6.3 % | +1.9 % | -30.7 |
| TS50_30+ev (take +50 %, stop -30 %) | -7.8 % | -7.3 % | +3.2 % | -35.4 |
| L30_80-ev (ladder +30 %/+80 %, stop -35 %, no event exits; best capture) | -9.6 % | -8.3 % | +6.7 % | -40.2 |
| TR25_50+ev (trail 25 % after +50 %) | -8.7 % | -8.2 % | -4.4 % | -39.6 |

The hazard pick beats the best baseline by 0.7 points per position out of
sample (90 % band of the difference +0.1 to +1.4 points), but over 2 hours,
and the band of a mean needs at least 10 hours: **not judged, "too early"**.
What it does is clear from its exits: it sells early (1,850 hazard exits,
797 pulls, 462 dev sales, 1,735 time stops at 30 minutes on dead tokens), so
it loses less on the many tokens that only fall, and it gives up nearly all of
the upside of the few that run: capture +0.5 %. Every policy keeps less than 7
% of the best possible gain. On the 70 top-5 % `peak3x` entries that landed out
of sample, every policy loses (HZ4+ev -5.8 % per trade, the least).

The capture ratio of the existing pipeline strategies' paper trades (the
study's replay, out of sample, best within 30 minutes of the landing):
P_pool60 +39 %, P_cmig_model +28 %, P_snipe_cmig +21 %, P_p90 +1 %, P_mom_model
-4 %, P_press10 -21 %; it is now a column of the daily study report.

## 3. What is wired (paper and shadow)

Four pre-registered strategies in `pipeline.STRATEGIES`, run by the study's
replay and by the live paper shadow inside the collector, judged by the X8 bar
and the readiness gate like the other eight:

| strategy | entry | exit | out of sample on this record |
|---|---|---|---|
| P_early10 | creation + 10 s, P(peak3x) above the top-5 % threshold of its training scores at that age and P(alive5m) at least its base rate | HZ(k*) with dev-sell and pull exits, 30 min | 1 trade, -7.2 % |
| P_early30 | the same at 30 s | the same | 2 trades, -5.2 % |
| P_press10_hz | as P_press10 | the same | 120 trades, -5.3 % (P_press10 itself: 12 trades, -27.1 %, then its daily loss stop) |
| P_pool60_hz | as P_pool60 | the same | 16 trades, -4.3 % (P_pool60: 6 trades, +7.5 %) |

The hazard exit (`Pipeline.hazard`) asks the same step features the study's
step rows carry (`early.Tracker.step_features`) at most once a second and
replaces the price exits while its models exist; before the first retrain it
falls back to E0's ladder, stop and trail. The early filter
(`Pipeline.early_ok`) compares the model's uncalibrated score with the
threshold the retrain stored per age. Without models the books skip their
signals ("no model").

**Daily jobs** (no new job; `research/ops/jobs.yaml`):
`pumpfun-rt-study` now records X14's rows, paths and step rows
(`pumpfun_rt/rows/early.parquet`, `steps.parquet`, `paths.npz`; paths and steps
of about two days' worth of tokens by a hash sample, the rows of all) and the
capture column; `pumpfun-rt-retrain` runs this evaluation
(`reports/pumpfun_rt/early_exit.{md,json}`), selects k* on the first half,
trains `e_mig1h`, `e_peak3x`, `e_peak10x`, `e_alive5m`, `hz_dump10`, `hz_up30`
and `hz_policy` on everything and saves them to `models/pumpfun_rt/`, where the
shadow books pick them up within ten minutes. The live shadow keeps its sniper
book in `paper/pumpfun_rt/snipers.json`.

**Telegram**: one more line on the daily card (English and German), for
example "Exits out of sample: HZ4+ev keeps +0% of the best possible gain (best
simple rule T30+ev: +2%). Early detection: the top 5 % by P(3x) reached it 10%
of the time against 3% for all (2.9x)."

## Counting

58 new trials (16 early books, 38 exit policies, 4 strategies) are in
`strategies.N_TRIALS`; the study's deflation pool is now 1,296 trials (907
hand, 300 factory, 89 pump.fun real-time), a noise bar of an annual Sharpe of
about 2.56. Deflation needs 5 days of out-of-sample P&L; not computable.

## Changes after the first run (disclosed)

The first computation (20:24 copy) showed three implementation faults, fixed
before the numbers above, none a change of the registered method:

- the top 1 % and 5 % were drawn on the calibrated probability, whose isotonic
  steps tie, so a "top 1 %" book entered most tokens; they are now drawn on the
  model's uncalibrated score (monotone in the probability), and a fold whose
  model is flat enters nothing;
- a curve gap marked every position opened in the hour before it as gapped,
  not only those whose 30-minute path it falls in;
- the hazard verdict used a difference band from 2 hours; like every band of
  the lab it now needs 10 hours.

## Verdict

Too early: 3 h 48 min of record. On it: completion within the hour and the
5-minute dump are predictable from the first seconds (useful by the registered
rule), a 3x only weakly, a 10x not at all; no early book makes money after
honest fills; the hazard exit loses less than the simple rules by selling
early but captures almost none of the upside (+0.5 %, best simple rule +1.9
%, best of all +6.7 %). The four strategies run on paper and shadow and will
be judged as the record grows. Real money is not this study's decision.
