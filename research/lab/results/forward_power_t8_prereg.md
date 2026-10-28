# T8: forward evidence that can prove something. Pre-registration

Registered 2026-10-28 and committed before any number on the lab's data was computed (the code is written and
tested on simulated returns only; while scoping, one look at which inputs exist on the data folder: the paper
journals, the exported backtest series of five books, one weekly factory shadow, no F2 shadow, no G2 shadow, R5's
registry; no performance number). Brief T8 of the training plan of 2026-10-28, on the review of 2026-10-27
(`results/review_2026-10-27.md`, sections 2 and 3: "telling a true Sharpe of 1.0 from zero takes about 12 years at
80 % power; a 30-day record only catches bugs"), R5's registry (`metrics.trial_pool`) and R6's windows
(`results/factory_lockbox_r6.md`). Code: `lab.paper.power`, called by `lab.paper.forward_report`. Results go to
`results/forward_power_t8.md` and daily to `reports/forward/power.{md,json}`. Nothing here may change once a result
exists. Paper only: no book, gate, engine setting, live path or wallet changes; `evidence.json` (the engine reads
it) is not touched.

## Question

For each paper book and shadow: how many forward days would it need to show its validated edge, what does its
record prove today, and is it still consistent with what validation promised? And do many small records of one
family add up to something?

## What is tested

- **Paper books**: every book of the forward report with a journal (`<data>/paper/<book>/journal.csv`), its fresh
  record (the forward audit's freeze, `forward_report.fresh_record`), one row a date (the last row of a date
  counts), the daily return the change of `equity`, the first day against the record's start equity.
- **Weekly factory shadows** (`<factory>/shadow/<key>.csv`, `net_ret`), **F2's shadows** (`<factory>/small/shadow/
  <key>.csv`, the change of `equity_eur` from `capital_eur`). Active and retired ones alike.
- **G2's shadows** log forecasts and losses scored on the panel, not daily returns; they are listed and skipped
  until a daily series exists (none today).

## The validated distribution (best first)

1. The backtest's exported daily net returns (`reports/forward/backtest/<book>.json`), cut at 2026-06-30 (R6:
   nothing from the lockbox), resampled day by day.
2. A factory shadow's held-back daily net returns (`oos_net_35bps` from `holdout.oos_from`; F2: `oos_returns_40`),
   cut at 2026-06-30.
3. The experiment report's growth and volatility (`forward_report.report_stats`), or a published validation
   number (perps_neutral: T6, Sharpe 1.74 and 35.6 % a year late at the costs of its era): a normal day with mean
   ln(1 + CAGR) / 365 and sd vol / sqrt(365). Labelled approximate.
4. None: no validated Sharpe. The zero test runs at a reference Sharpe of 1.0 a year with the sd of the first 10
   forward days and counts from day 11; no days needed and no band test.

## Days needed (from validation only)

- Daily Sharpe s = mean / sd of the validated days (365 a year). Fixed sample, one-sided at 5 %, 80 % power:
  n = ((z 0.95 + z 0.80) / s)^2.
- Sequential: the days by which 80 % of 1,000 simulated records (iid draws of the validated days, normal for an
  approximate one; seed fixed) have crossed the test below; more than 30 years is written as such. A validated
  Sharpe of 0 or less: never.

## The test (valid when looked at every day)

- On y_i the day's return less m0: S = sum y, V = sum y^2. The one-sided self-normalised mixture (de la Pena,
  Robbins' mixture over a half-normal lambda with precision rho):
  E = 2 sqrt(rho / (rho + V)) exp(S^2 / (2 (rho + V))) Phi(S / sqrt(rho + V)).
  A nonnegative supermartingale under a mean of m0 for conditionally symmetric days, whatever their tails; Ville's
  inequality makes P(E ever reaches 20) at most 5 %. Skewed days are checked by simulation (below).
- rho = sigma^2 n / (2 ln 20 + ln(1 + 2 ln 20)), sigma^2 the validated mean square and n the fixed-sample days (the
  mixture tuned to the horizon where the edge should show; at the reference Sharpe 1.0 without one).
- **Edge shown**: E for m0 = 0 has reached 20 on some day. **Below its band**: the same e-process on the validated
  mean less the day's return (m0 = 0 on mu_val - x) has reached 20. Otherwise **consistent with validation** (no
  validated Sharpe: **no evidence yet**). Each verdict per day, the day it first held kept.
- 5 % for each book; across about 35 books one false "edge shown" ever is not unlikely, which is why the pooled read
  and the ladder exist.

## Pooled evidence per family (partial pooling)

- Families: momentum (tsmom*, small50_tsmom1, small40_vol_target), breakout (breakout_top10, onchain_breakout_*,
  small100_breakout_sol3), market-neutral (m4_ls, m4_perps, picks_ls*, perps_neutral, funding_carry), memes
  (memes_*, onchain_meme_*, pumpfun_*), trend (trend4h_pullback, btc_gated, small40_spy_trend, onchain_longterm),
  the weekly factory's shadows, F2's shadows; any other book its own family.
- Each member's forward daily Sharpe m = mean / sigma (sigma the validated sd blended with the forward days,
  30 days' weight for validation), its standard error 1 / sqrt(days), inflated by the design effect
  1 + (k - 1) rho_bar (rho_bar the mean pairwise correlation of the members' common days, at least 5 of them,
  clipped to 0 to 1; 0 when none), k members with at least 2 days.
- Normal hierarchical model, numpy only: m_i ~ N(theta_i, se_i^2), theta_i ~ N(mu, tau^2), mu flat, tau uniform on
  0 to 2 a year, a 400-point grid (Gelman et al., BDA 5.4). Reported: the family's mu a year (posterior mean, 90 %
  band), P(mu > 0), each member shrunk; the same on the gap to validation (m less the validated daily Sharpe,
  members with one) with P(gap < 0). A Bayesian summary, not a sequential test: it never moves a book on its own.

## Simulation checks (tests, before any run on data)

- A true zero edge, normal, Student t with 3 degrees and a skewed mix: the share of 2,000 records of 3 years that
  ever reach 20 is at most 5 % (plus the simulation's error).
- A true edge (2.0 a year, normal and Student t): about 80 % of fresh records found by the predicted sequential
  days (70 to 90 %).
- The pooled model: many short records of one true edge give P(mu > 0) above each member's own.

## The ladder

T3's ladder is not on main. Each row carries `ladder`: paper days, consistent with validation, and the provisional
ladder's paper half (90 days, `two_leads_t6.LADDER_PAPER_DAYS`, not below its band) for T3 to read when it lands.

## Trials

Each tested book and shadow is one trial of R5's registry, counted only (no Sharpe, no variance):
`hand:t8:<book>`, `factory:t8:<key>`, `small:t8:<key>`, and each pooled family `hand:t8:pool:<family>` (or the
factory's and F2's family), registered before the day's numbers are written. A rerun is a no-op.

## Reported

`results/forward_power_t8.md` on today's books: per book the validated Sharpe and its source, days so far, the
days needed (fixed and sequential), today's e-values, the verdict; per family the pooled numbers. Daily:
`reports/forward/power.{md,json}` and a section in the forward report.
