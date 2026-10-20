# X9 model review

2026-10-20. A critical look at every model the lab keeps and at the machinery
that turns evidence into picks, then the improvements that were pre-registered
in `model_review_prereg.md` (committed before any number below was computed)
and measured in `model_review_studies.md` and `drift_study.md`. Numbers come
from the zoo report of 2026-10-19, the forward report of 2026-10-19 and runs
on the PC against the server's mirror.

## The short version

- Of the models with a gate, only **M2** (weekly coin ranking) and **M1**
  (next-hour vol) show solid out-of-sample skill; **M8q** passes its gate,
  but only through its 90 % quantile: the 10 % quantile has no skill over its
  baseline (DM p 0.91).
- None of the tried improvements for the long-only books makes money: M8q as a
  risk overlay and M2 as a loser filter both make every book worse.
- **M2 averaged with low volatility** ranks coins better than M2 alone, as
  registered (IC 0.158 against 0.149 from 2024, t 3.1). It now runs as an
  opt-in shadow ranking; it is not a book.
- The **drift test is miscalibrated**: "shift" fires on 100 % of 30-day
  windows, the training years included. Neither the registered fix nor a
  second form passed acceptance, so the rule is unchanged and the report now
  says what the labels mean.
- The **auto pick's evidence score** did not favour the books that then did
  worst (it ranked breakout_top10 first, the best long-only book forward). The
  forward penalty changes nothing in history. What did hurt the main auto
  pick is the engine's **"no edge" rule on lab books**: their rebalancing
  sales, pooled across every autopilot and earlier run, ruled breakout_top10
  and tsmom_regime out after about a week. A setting
  (`labEdgeFromTrades`, on by default, the behaviour so far) can now turn
  that off.
- The weekly `costs` job no longer dies on a symbol with empty book arrays.

## Every model

| Model | Predicts | Out of sample vs baseline | Drift | Used by | Verdict |
|---|---|---|---|---|---|
| M1 `vol_1h` | log realised variance of the next hour, 20 coins | QLIKE 0.245 vs HAR 0.278 (11.7 % lower), DM p 7e-9, better in 24 of 24 quarters | n/a (engine drift on M1's own card) | nothing; shadow in the engine | **Keep in shadow.** The forecast is real; `vol_managed` showed it sizes worse than the 30-day mean at Alpaca costs (7 to 37x more turnover). No book should read it. |
| M2 `picks_7d` | rank of each coin's next 7-day return, about 280 coins a day | rank IC 0.139 to 0.149 (t 19 to 30) from 2022 against 0; 0.208 among the 20 most liquid, 0.093 on the 15 Alpaca coins (from 2024) | n/a | `picks_ls`, `picks_ls_v2` (paper, perps) | **Keep.** Its skill is relative and mostly on the short side (bottom decile -3.2 % a week vs the day's mean). Long-only it has never paid (C6, `momentum_m2`, here b). Low vol alone gets close (IC 0.142), so M2 is largely a low-vol and reversal ranking. |
| M3 Pythia-Net (and hybrid, listwise) | the same ranking with a neural net | IC 0.092 / 0.127 / 0.014 against M2's 0.144; the blend with M2 adds 0.001 (reports/ensemble) | n/a | nothing | **Retire.** Below M2 on M2's own task, and the blend adds nothing. |
| M4 `xs_daily` | 3-day cross-sectional rank, 584 coins | rank IC 0.148 (t 47); long-only dead (0.04), long/short fails deflation and loses to a plain low-vol book | n/a | `m4_ls` (paper, perps) | **Keep as paper only.** Forward -1.5 % after 11 days, inside its band. Same caveat as M2: needs shorting the owner has not cleared. |
| M5 `regime` | P(15 % BTC drawdown in 30 days) | AUC under 0.5 for every model | n/a | nothing | **Retired** (the 200-day rule stays). |
| M6 `vol_daily` | next-day vol | LGBM 9 % better than HAR next day, 6 % worse next week; sizing worse than RW30 | n/a | nothing | **Retired for sizing** (RW30 stays). |
| M7 `regime_hmm` | bull or bear state | no difference to the 200-day rule survives deflation | n/a | nothing | **Retired.** |
| M8 `m8_direction` | P(next day up), 15 Alpaca coins | log loss 0.6957 vs 0.6937 for the base rate (worse), DM p 0.15, AUC 0.497 | shift (meaningless, see c) | nothing | **Retire.** Daily direction has no signal in these inputs; 13 of 24 quarters, AUC at chance. Retraining weekly costs compute for nothing. |
| M8q `m8_quantiles` | next-day 10/50/90 % return quantiles | pinball 1.0 % lower, DM p 0.012 (passes the Bonferroni 0.025), 15 of 24 quarters; **by quantile: q10 p 0.91, q50 p 0.13, q90 p 7e-12**; inside 10-90 band 76.7 % (should be 80) | shift (meaningless) | nothing (shadow) | **Change target.** The skill is the upper tail; the downside quantile, the one a risk tool needs, is no better than "usual spread times today's vol" and the model's q10 is too tight (11.4 % of days below it from 2024). As a risk tool it fails (a). Keep the shadow, report per-quantile gates, and do not offer q10 to any book. |
| M10 `m10_vol_regime` | next-day log RV, 20 coins | QLIKE 0.2895 vs HAR 0.3142 (7.8 % lower) but DM p 0.17; without regime inputs 0.2861 (better) | shift / drift | nothing | **Retire** as a separate model: the regime inputs add nothing (M6 already found sizing on better daily vol worse). Its 28 % live gain is 80 rows. |
| M11 `m11_slippage` | slippage of demo market orders | MAE 6.46 vs 5.82 bps for the cost model (11 % worse), 51 fills | shift | nothing | **Retrain later.** 51 fills is too few; rerun when the demo fills reach a few hundred. The cost model stays. |
| M12 `m12_cross_asset` | BTC and SPY correlation regime | MSE 0.1026 vs 0.0900 for persistence (14 % worse), regime hit 49 % vs 58 % | shift | nothing | **Retire.** Persistence wins; nothing would use a correlation forecast today. |
| Strategy factory survivor | 5 lowest-vol of the top 20 while BTC is in an up trend | 0.88 at 35 bps held back, deflated p 0.00 | n/a | 30-day shadow book | **Keep in shadow** until its 30 days end. Its signal (low vol) is the one that helps M2 in e. |

"Drift" is the zoo's own label; as c shows, "shift" is on for every model in
every window, so it carries no information today.

## The live books, forward (to 2026-10-19)

Thirteen days in a falling market, all long-only crypto books negative, the
two market-neutral M2 books positive (paper only, perps not cleared):
`picks_ls` +2.4 %, `picks_ls_v2` +6.0 %; `tsmom` -6.3 %, `tsmom_regime` -4.6 %,
`tsmom_top20` -4.5 %, `breakout_top10` -0.7 %, `tsmom_tranches` -2.1 % (7
days). The autopilots since 2026-10-15 all trail BTC bought and held. None of
this is evidence of skill or of its absence yet: the bands from the books' own
backtests are -4 to +8 % over that stretch.

## a. M8q as a risk tool: fails

The M8q downside (minus the mean 10 % quantile over the Alpaca coins) scaling
or capping each live book, against the same rule from M8q's baseline quantile
(plain vol targeting) and the book alone, out of sample from 2024 at 35 bps:

| book | alone | M8q scale (pick) | M8q cap | control scale | control cap |
|---|---|---|---|---|---|
| breakout_top10 | 1.17 | 1.16 | 1.08 | 1.24 | 1.30 |
| tsmom_top20 | 0.64 | 0.50 | 0.44 | 0.65 | 0.70 |
| tsmom_tranches | 0.73 | 0.55 | 0.46 | 0.73 | 0.81 |

Every pick fails gates 1, 3, 4, 5, 6 and 7 (the bootstrap band of the
difference is -0.30 to -0.05 for tranches); deflated p 0.00 over 1,504 trials.
The reason is in the model card: M8q's 10 % quantile has no skill, and it
reacts to more than vol, which only adds turnover. The control cap looks
better than the book in all three cases (+0.06 to +0.13), but that was not a
registered candidate (the pick could only be an M8q rule), it is the opposite
of `vol_managed`'s finding for RW30 overlays, and its improvement would face
the same 1,504-trial bar; it is a candidate for a future registration, no
more.

## b. M2's bottom third as a long-only filter: fails, again

| book | alone | filtered | late | twin | twin alone |
|---|---|---|---|---|---|
| breakout_top10 | 1.17 | 1.11 | 1.11 | 1.16 | 1.07 |
| tsmom_top20 | 0.64 | 0.33 | 0.39 | 0.31 | 0.32 |
| tsmom_tranches | 0.73 | 0.52 | 0.57 | 0.50 | 0.47 |

Gates 1, 3, 4 and 6 fail for all three. Why "recognises losers" does not
carry over: on the 15 Alpaca coins the live books hold, M2's IC is 0.093 and
its bottom third did **better** than the rest (+0.8 % over 7 days from 2024),
while among the 20 most liquid coins of all Binance it is 0.208 and the bottom
third lags by 3.2 %. M2's short-side skill lives in coins the long-only books
cannot hold. With C6 (70 trials) and `momentum_m2` (4), this idea has now
failed three times; it should not be tried again on these books.

## c. Drift: the test is miscalibrated, the fix did not pass

Bins from training rows before 2024, every 30-day window (120 for M12)
stepping 7 days:

| model | today's rule, shift or worse: in sample / out of sample | drift (over 5 % outside): in / out |
|---|---|---|
| M8 and M8q (22 inputs) | 100 % / 100 % | 35 % / 25 % |
| M10 (30 inputs) | 100 % / 100 % | 35 % / 24 % |
| M12 (10 inputs) | 100 % / 100 % | 41 % / 13 % |

Why: PSI compares one month of a slow, market-wide input (breadth, the
200-day gap, market vol, BTC's 7-day return) with years of it. One month
holds one regime, so the PSI is 1 to 6 in a typical training month (median
4.0 for breadth50) against a 0.25 cut meant for independent samples, and the
market-wide inputs are the same number repeated for every coin. The test is
not wrong about the arithmetic; it asks a question whose answer is always yes.

The registered fix (per-input cuts at the 99th percentile of training
windows, a model-level k so at most 5 % of training windows are flagged)
cut the out-of-sample rate to 18 to 25 % but caught a one-standard-deviation
move of one input in only 31 to 54 % of windows (90 % needed). A second form
chosen afterwards (Bonferroni cuts per input, k = 1) reached 7 to 14 % in
sample and 14 to 31 % out of sample with power 57 to 58 %: also not accepted, and
it was not registered. So `core.drift_check` is unchanged (it is also the
engine's rule for M1 and M2 in `pythia-ml`), the calibration code sits in
`core.drift_calibration` and `core.drift_calibration_per_input` for the next
registration, and the zoo report now explains that "shift" is no news on its
own. The next attempt should test drift on what matters (the model's loss on
recent days against its training loss), not on the inputs' spread.

## d. The auto pick's evidence

**The score did not pick the worst books.** With the signals' own evidence
the lab part of `Evidence::score` ranks breakout_top10 (2.70) above
tsmom_tranches (1.73) and tsmom_top20 (1.61); forward, breakout_top10 is the
best long-only book (-0.7 %), the momentum books the worst. Thirteen days
cannot calibrate anything, so no change to the formula is proposed.

**The forward penalty changes nothing in history.** Replayed on the three
books from 2024 (each quarter a new paper start, halved below the 5 % band of
the in-sample bootstrap after 10 days): Sharpe 1.04 with it, 1.05 without,
band of the difference 0.00 to 0.03, deflated p 0.63. Gate 6 fails, so
`FORWARD_BELOW_FACTOR` stays at 0.5. It rarely matters because it hits one
book at a time (17.9 % of days at least one, never all three) and the books
are 0.7 to 0.95 correlated.

**What did matter: "no edge" from a lab book's own trades** (found while
checking the above, so an addendum, not a registered result). On 2026-10-18
the main Auto-Pick dropped breakout_top10 and tsmom_regime ("another lab book
has better evidence now") and kept tsmom_tranches at 100 %; on 2026-10-19 it
found no candidate at all. The reason is in the strategy ledgers: a lab
book's every rebalancing sale is booked as a closed trade with twice the fee,
the ledger is shared by every autopilot and every earlier standalone run of
the book, and after 30 such trades a shrunk Kelly at or below 0 rules the
book out of every pick. breakout_top10 had 11 wins and 39 losses,
tsmom_regime 2 and 32, tsmom_top20 11 and 51, tsmom_tranches 3 and 30, all
within about two weeks of a falling market. Replayed on the books' own
trading from an empty book at each of 24 quarter starts since 2021, the rule
never fires for breakout_top10, fires 4 times for tsmom_top20 (after a median
16 days) and 9 times for tsmom_tranches (24 days), and the 90 days after it
fired were not worse than usual (3.5 % vs 2.7 %, 1.9 % vs 3.2 %). The
per-trade record of a rebalancing book is not a measure of its edge.

Engine change, behind a setting that defaults to today's behaviour:
`RiskLimits.labEdgeFromTrades` (true). False: a lab book's closed trades
neither measure nor rule out an edge; the lab evidence and the forward
report's band decide, and the record is still shown in the pick's sentence.
Built-in strategies are not affected. Tests:
`a_lab_book_whose_rebalancing_trims_lost_is_left_out_by_default_and_judged_by_the_forward_report_when_set`.

## e. Ensembling: M2 plus low vol passes

On M2's coin-days, 7-day label: in the selection window (2022-23) M2's IC is
0.133 (t 15.0), low vol's 0.093 (t 8.8), 28-day momentum's -0.061 (t -5.1,
so it did not join). From 2024 the mean of the M2 and low-vol percentile ranks
makes IC 0.158 against M2's 0.149, Newey-West t of the paired difference 3.13
(2.39 needed), better in 2024 (+0.004), 2025 (+0.013) and 2026 (+0.011), and a
weaker bottom decile (-3.64 % vs -3.21 % relative a week), so it passes every
registered condition. It is a small gain in ranking, and nothing about money:
the M2 books are market-neutral on perps, which are paper only.

## What changed

| Change | Where | Default |
|---|---|---|
| `costs`: a symbol with empty recorded book arrays is skipped, not an IndexError | `lab/experiments/costs.py`, `tests/test_costs.py` | always |
| Shadow ranking M2 + low vol, written before the outcome and scored after 7 days | `lab/paper/m2_lowvol_shadow.py`, hook in `lab/paper/picks_ls.py` | off |
| `labEdgeFromTrades` risk limit | `crates/pythia-core/src/engine/mod.rs`, `autopilot.rs` | on (today's behaviour) |
| Drift calibration functions and the drift study | `lab/models/core.py`, `lab/models/drift_study.py` | not used by the zoo |
| Zoo report explains "shift" and "drift" | `lab/models/train.py` | always |
| The studies | `lab/experiments/model_review.py` | |

### Switching things on

- **Shadow ranking.** Add `env: {PYTHIA_M2_LOWVOL_SHADOW: "1"}` to the
  `paper-ls` job in `research/ops/jobs.yaml` (`python -m lab.paper.picks_ls`;
  for v2 the `paper-ls-v2` job, which writes into its own folder).
  On each weekly rebalance it appends both rankings to
  `<data>/paper/picks_ls/shadow_m2_lowvol.jsonl` and writes the scores so far
  to `shadow_m2_lowvol.json` (rank IC of M2 and of the average, per scored
  day). The book does not change. After about 26 weekly entries the scores
  say whether the gain holds forward.
- **Lab books judged by the forward report instead of their trades.** Read
  the limits from `/api/state` (`limits`), set `labEdgeFromTrades` to false
  and post them back as `{"cmd": "setLimits", "patch": <limits>}` to
  `/api/command`. The Risk page keeps the value when it saves its own fields.
  Takes effect at the next pick or re-pick. To undo, post true.

## Recommendations not acted on

- Retire M8, M10 and M12 from the weekly retrain (their gates fail, nothing
  reads them); keep their cards. Retire M3.
- Give M8q per-quantile gates and only ever offer the 90 % quantile.
- Register a drift test on recent loss instead of input spread.
- If a risk overlay is still wanted, register the control cap from a (half
  the book while the vol-scaled downside is above its 80th percentile) as its
  own study.
- The auto pick takes up to three books that are 0.7 to 0.95 correlated
  (three are the same 28-day momentum rule); picking by score alone buys
  little diversification.
