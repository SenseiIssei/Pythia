# X11 model upgrades: pre-registration

Written and committed on 2026-10-20 before any number below was computed.
What was known when this was written: the X9 model review
(`model_review.md`, `model_review_studies.md`, `drift_study.md`), the X6 flow
overlays (`flow_overlays.md`), the M2 v2 report of 2026-10-13 (rank IC 0.137
from 2022), and which data exist on the PC's mirror (coverage only, no
outcome). Nothing in this file is changed after the first result exists;
anything added later goes into `model_upgrades.md` and says so.

The question for every part: does a model that still has a job get better,
out of sample from 2024-01-01, against the version that runs today?

## The pool

Sharpe trials before this study: 930 hand trials (907 as counted by the
real-time pump.fun plan, X9's 29 included, plus that study's 23) at the
variance backed out of the published bar, and every genome in the factory
ledger at run time. This study adds **18** Sharpe trials (part c). Deflation
as in X6 and X9 (pooled variance of daily Sharpes, each group at its own).

The model tests below are not Sharpe trials. Each part corrects inside
itself (Bonferroni over the tests named there) and they are listed here so
they are not run twice: part a 3 IC tests, part b 2 loss tests, part c 1
model gate, part d one acceptance test, part e two forward tests (judged
later, on forward data only).

## a. M2 v3 (3 IC tests)

**Today (v2).** `lab.experiments.picks --perp-features`: LightGBM
LambdaRank, one group per day, label the 7-day forward return in day
quintiles; 16 spot features plus `fund7`, `basis`, `perp_share`, all as
cross-sectional ranks; eligibility 60 days of history and 1 M USD a day.

**v3 = v2 plus five feature groups**, computed from data known at the close
of the row's UTC day:

| group | features | coins | from |
|---|---|---|---|
| F funding and basis dynamics | `fund1` funding paid over the last day; `fund28` over the last 28; `basis_chg7` basis today minus 7 rows ago | every coin with a USDT perpetual | 2020 |
| P positioning | `oi_chg7` 7-day log change of open interest in coins; `ls_acct` all-accounts long/short ratio, 7-day mean of daily means; `ls_chg7` its 7-day log change | the 20 coins with Binance metrics archives | 2022-01 |
| M market state (one value per day) | X6's definitions: `cb_prem` Coinbase premium, `kr_prem` Korean premium, `stable_30` and `stable_7` USDT+USDC supply growth, `dvol` BTC DVOL, `mkt_funding` the top-20 perps' funding; each as a z-score over the trailing 365 days (at least 180) | all | 2020 (DVOL 2021-03) |
| T trend and attention | `dist_hi365` log distance to the 365-row high (at least 28 rows); `volu_28_180` log of mean quote volume over 28 rows over that over 180 (at least 56) | all | 2020 |
| V longer and idiosyncratic risk | `vol90` square root of the 90-row mean daily realised variance; `ivol56` idiosyncratic vol against BTC over 56 rows | all | 2020 |

F, P, T and V are ranked within the day like every M2 feature (a missing
value stays missing). M is not ranked (a rank of a value every coin shares is
a constant); it lets the trees condition the ranking on the market. Funding
and basis per coin and the 28-day volume trend (`volu_trend`) and the 28-day
low-vol rank (`vol28`) are already in v2; the groups add what is new.

**Same everything else.** The same coin-days as v2 (the new features never
drop a row), the same LightGBM parameters, the same quarterly walk-forward
from 2022-01-01 with a 7-day embargo, run in the same script for v2, v3 and
the five ablations (v3 minus one group).

**Selection (2022-01-01 to 2023-12-31, the walk-forward's own out-of-sample
days).** A group stays in v3 when removing it lowers the mean daily rank IC
over these two years. If every group stays, v3 is v2 plus all five; else v3
is v2 plus the groups that stay (one more walk-forward run); if none stays,
there is no v3 and the verdict is "v2 stays".

**Judged from 2024-01-01** to the last labelled day, daily Spearman IC
against the 7-day forward log return, Newey-West t (lag 7) of the paired
daily difference:

- **H1 whole universe**: v3 against v2 on every scored coin-day.
- **H2 Alpaca**: v3 against v2 ranked among the coins the Alpaca paper
  account lists (`universe.ALPACA`, the 32 non-stable coins, those with
  Binance history), on days with at least 8 of them eligible. This is the
  universe the long-only books can hold.
- **H3 with low vol**: the mean of v3's and the low-vol percentile ranks
  (minus `vol28`, as the live X9 shadow) against the same mean with v2.

Each passes when the mean IC difference is positive, its t is above 2.39
(two-sided 0.05 over three tests) and v3 is higher in at least 2 of 2024,
2025, 2026. Reported but not tests: the same on the 15 lab coins Alpaca
lists (`ALPACA15`), the top-third minus the rest and the bottom decile among
the Alpaca coins, IC per quarter, feature importance.

**If H1 or H2 passes**, v3 is trained weekly as "M2 v3" in shadow next to
v2: on each run both are trained on all labelled history, both rankings are
written down before the outcome and scored after 7 days (rank IC, whole
universe and Alpaca). It is not exported to the engine and no book reads it.

## b. M1 next-hour volatility (2 loss tests)

**Today.** `lab.experiments.vol`: LightGBM on 21 HAR, range, flow and
calendar inputs, 20 coins, QLIKE against HAR.

**b1. Flow inputs.** M1 plus, per coin-hour and known at the end of the
hour: `fund_last` the latest settled funding rate; `oi_chg1h` and
`oi_chg24h` log changes of open interest in coins (metrics, from 2022-01);
`ls_acct_h` the all-accounts long/short ratio at the hour's last snapshot;
`perp_taker_h` the log of the hour's mean taker long/short volume ratio; and
market-wide `cb_prem_h` (Coinbase over Binance BTC close at that hour - 1),
from the previous UTC day `dvol_prev` (log BTC DVOL close), `kr_prem_prev`
and `stable7_prev` (the 7-day supply change, the value stamped D used from
the close of D+1). Same parameters, folds by quarter with a 24 h embargo;
both models are refit on every fold; test quarters from 2024-Q1.
**Pass**: lower QLIKE than M1 over every hour from 2024-01-01, Diebold-Mariano
p below 0.025 on per-hour mean losses (lag 24), and lower in at least two
thirds of the test quarters. The two groups (per coin, market) are reported
alone as diagnostics, not tests.

**b2. Order-book imbalance** from the recorder's Binance spot `book20`
(2026-09-30 on). Per coin-hour: `imb5` the mean over the hour's snapshots of
(bid minus ask quantity over the top 5 levels) / their sum; `spread_l` the
log of the mean spread in bps; `depth_chg` the log of the hour's mean top-5
notional over that of the previous 24 hours. M1 fit on every row before
2026-09-30 minus 24 h predicts every hour after; a linear correction of its
log forecast (OLS of the log-RV residual on the three inputs, refit each day
on all earlier days of the record with a 24 h gap, first fit after 7 days)
is the candidate. **Pass**: lower QLIKE than M1 alone on the corrected hours,
DM p below 0.025, at least 3,000 coin-hours. Fewer hours: "too little data",
rerun when the record is 90 days long.

**If b1 passes**, it runs as a lab-side shadow forecast (the engine cannot
compute these inputs live); M1 in the engine is unchanged. b2 the same.

## c. M8q's upper tail (1 model gate, 18 Sharpe trials)

X9 found M8q's skill only in its 90 % quantile (DM p 7e-12; q10 0.91).

**c1. Retarget.** `M8u`: one LightGBM quantile regression at 0.9 on the
vol-scaled next-day return, M8q's inputs and parameters, baseline the
training window's 90 % quantile of the vol-scaled return times today's vol,
loss the 0.9 pinball. Gate: lower than the baseline with DM p below 0.05 over
M8q's purged quarterly walk-forward from 2021. If it passes, M8u joins the
zoo (weekly retrain, daily shadow, nothing reads it) and M8q's card says its
lower quantiles are not to be used.

**c2. Trim on predicted upside exhaustion.** U(i, t) = M8u's forecast over
its baseline's for coin i, made at the close of day t (below 1: less upside
than usual at today's vol). The cut is the 20th percentile of every coin's U
over the trailing 365 days (at least 180 days). Rules, applied to each book's
targets as the autopilot runs them on Alpaca (unlisted coins in cash):

- *exhaust*: a coin's target is halved while U is below the cut;
- *take-profit*: halved while U is below the cut and the coin's 7-day return
  is above 0.

A coin without a forecast is never trimmed. **Control** (what M8u must add
to): the same rules with U replaced by minus the coin's vol-scaled 7-day
return (r7 / (sigma30 x sqrt 7)), so a plain "trim after a run-up".
Trials: 2 rules x 2 sources x 3 books (`breakout_top10`, `tsmom_top20`,
`tsmom_tranches`) = 12; the in-sample pick per book (better 35 bps Sharpe of
the two M8u rules on 2021-07-01 to 2023-12-31) gets a day-late and a twin
run: 6. Total **18**. **Pass**: X6's six gates (as in X9) and 7, the pick's
out-of-sample Sharpe at 35 bps above the control's with the same rule on the
same book. **Prior**: every overlay on these books has failed so far.

If a pick passes, it becomes a shadow trim signal written daily next to the
books, off by default; no book changes.

## d. A calibrated drift test (one acceptance test)

Today's rule fires "shift" on 100 % of 30-day windows in the training years
(X9 c). The registered fix and an addendum failed X9's acceptance, mostly on
power for a one-standard-deviation move of one input.

**The test (form W).** Per model, bins and windows exactly as today (deciles
of the training rows, the model's drift length, stepping 7 days). Per input
f and window w: s_f(w) = max(PSI_f(w) / c_f, outside_f(w) / o_f), with c_f
and o_f the q-quantiles of that input's PSI and outside share over the
training windows (o_f at least 0.5 %). One q per model, the smallest of
0.95, 0.96, ... 0.99, 0.995, 0.999 at which at most 5 % of the training
windows have max_f s_f above 1. A window is "shift" when max_f s_f > 1, and
"drift" when it is shift and the input that tripped it spent more than 5 %
of the window outside the trained range.

**Acceptance**, on M8 (= M8q's inputs), M10 and M12 as in X9, bins from rows
before 2024:

1. in-sample false-alarm rate at most 7.5 % for every model, measured
   honestly: each training window judged with q and cuts fitted on the
   training windows of the other years (leave one calendar year out);
2. out-of-sample (windows from 2024) shift rate at most 20 % for every model;
3. power on synthetic faults in the out-of-sample windows, one input at a
   time, every input, at least 90 % for each of: (i) a level shift of two
   training standard deviations for the whole window; (ii) a frozen feed (the
   input held at its value on the window's first day); (iii) a unit error
   (the input multiplied by 100).

Why two standard deviations and not one: X9's table shows a slow,
market-wide input has a median in-sample PSI near 4 in an ordinary month; a
one-sigma move of such an input is what an ordinary month looks like, so no
test can flag it at a 5 % false-alarm rate. The one-sigma power is reported
next to X9's for comparison, not as a criterion.

**If accepted**, the zoo's cards carry the calibration and `core.drift`
uses it when a card has one (a card without it keeps today's rule, and so
does the engine, whose M1 and M2 cards the zoo does not write). Otherwise
nothing changes.

## e. Claude as a model (forward only)

Language models have read the news of the years we would backtest on, so no
historical test of a model's forecasts is honest. Both parts are judged on
forward data only, written down before the outcome.

**e1. Weekly analyst** (`claude-sonnet-5-5` through the engine's metered
endpoint, Batches API, one call a week). A compact fact sheet per Alpaca
coin with Binance history: 7, 30 and 90-day returns, 30-day vol, distance to
the 52-week high and the 200-day mean, 28-day volume trend, 7-day funding
where a perp exists, and the market lines (BTC, premiums, stablecoin growth,
DVOL). No model of ours is shown. It answers per coin the probability that
the close 7 days after the reference close is higher and the expected rank of
its 7-day return among the listed coins. Scored like M2: the weekly rank IC
of minus the expected rank against the realised 7-day log return, with on
the same coins and reference day the low-vol rank, 28-day momentum and, where
the M2 shadow recorded that day, M2's rank; Brier of the probability against
the base rate. **Pass** after at least 26 scored weeks: mean weekly IC
positive with t above 2, and above the low-vol rank's on the same coin-weeks
with a paired t above 2. Until then, and unless it passes, it is a shadow
record; passing only opens a registered ensemble study.

**e2. Daily news sentiment** (`claude-haiku-5-5`, Batches API, one call a
day). Headlines from publisher RSS feeds (CoinDesk, Cointelegraph, Decrypt,
The Block, CryptoSlate, Bitcoin Magazine), matched to coins by name and
ticker; titles only are stored and sent. Google News RSS was checked and is
not used: its feed restricts use to rendering in a personal feed reader.
Per coin a sentiment score from -1 to 1 and the headline count. **Candidate
M2 input only if**, over at least 26 weeks of M2's recorded ranking days,
the mean of M2's and the sentiment's percentile ranks among the Alpaca coins
has a higher mean IC than M2 alone with a paired t above 2 (weekly,
non-overlapping). Until then it is recorded, scored and shown, nothing more.

Cost is logged by the engine's ledger (every call, tokens, dollars) and
summed in each job's report.

## What passes, and what happens then

Anything that passes is wired as a shadow score or job, off by default for
live behaviour, with the switch described in `model_upgrades.md`. Nothing
reaches an order or the engine's defaults.
