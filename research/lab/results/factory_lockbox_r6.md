# R6: a fresh lockbox and an honest bar for the factories (pre-registration, 2026-10-27)

Code `lab/factory/{evaluate,ledger,run,small,grammar}.py`, tests `tests/test_factory_lockbox.py` (and the factory
tests updated). From the review `results/review_2026-10-27.md` (verdict 3, section 3). Built on R5's trial
registry (`metrics.trial_pool`, `<data>/trials/registry.jsonl`): the registry stays the only count of trials and the
only source of trial variances. Everything below is fixed before the first run that uses it. Paper only.

## Why

- The 2024+ window is spent: every study since the families sweep and every factory run (4 to 6 a run, F2 daily)
  has looked at it. It is validation, not out of sample.
- The weekly bar deflated the raw held-back Sharpe with a noise variance from in-sample Sharpes that mostly measure
  bull-market beta. Over the registry's 2,467 trials (R5, server data) the noise bar is an annual Sharpe of 2.77;
  BTC's held-back Sharpe is 0.72. Nothing could pass, for the wrong reason.
- Equivalent genomes under different keys (G1's `btc > ma_100` and `z_100(btc) > 0`) were separate trials and could
  be sent to the held-back window again and again (one strategy four times on 2026-10-25).

## The windows

| window | days | who sees it |
|---|---|---|
| in sample | 2018-01-01 to 2023-12-31 (weekly and F2, unchanged) | the search |
| validation | 2024-01-01 to 2026-06-30 | the held-back gates, the deflated excess bar, the shadow review |
| lockbox | 2026-07-01 to the last close | only the weekly run (`run.lockbox_step`), once per behaviour |

F2's daily run never reads the lockbox; its survivors are looked at by the weekly run (`small.lockbox_step`, called
from `run.weekly`). A look is made only when the lockbox holds 60 days or more (about 118 days on 2026-10-27).

## One trial per behaviour

- `grammar.behaviour`: a hash of a genome's in-sample daily net returns at 35 bps, rounded to 1e-9 (F2: both
  wallets'). Equal returns mean one behaviour.
- `Ledger.add`: a genome whose behaviour is already in the ledger is written with `same_as` the first key (the
  search still knows it was tried) and is not registered. The registry gets one trial per behaviour; there is no
  second count. Lines registered before R6 stay as they are (the registry never rewrites).
- Holdout picks skip `same_as` genomes and every behaviour held back before (keys and behaviours in the log).

## The bar: deflated excess

- Weekly: the daily excess of the genome at 35 bps over holding BTC. F2: the 40 EUR wallet's daily excess over the
  40 EUR SPYx wallet (same costs).
- DSR (higher is better, pass above 0.95) of the validation excess: N = the registry's pool of all, the noise
  variance = the variance of the family's in-sample excess Sharpes (clipped at +-3 a year), read back from the
  registry, where every new genome carries `excess_sharpe`. Until the family has 30 of them, the raw pool's
  variance is used (stricter). The raw DSR stays in every row as `dsr_raw`.
- Weekly promotion (`evaluate.bar_gates`): every shadow gate, the deflated excess gate, the lockbox gate, and the
  forward month as before. F2 promotes nothing; its DSR is reported and a pass queues the lockbox look.

## The lockbox and its log

- `<data>/factory/lockbox.jsonl`: one line per look by any factory (`factory`, `run`, `date`, `key`, `behaviour`,
  the lockbox days, Sharpe, excess Sharpe, the look's number and the looks counted). It is written before the look's
  result is used, and never rewritten.
- Who is looked at: weekly genomes held back this run and active shadows that pass every shadow gate and the
  deflated excess bar; F2 survivors whose excess DSR passed. Each behaviour once, ever.
- The look's DSR deflates the lockbox excess over N = every look so far across the factories (the look included),
  with the same excess variance. The lockbox gate passes at 0.5 or more: the excess must beat the best of that many
  looks' noise. On a lockbox of a few months a 0.95 bar would need an excess Sharpe near 3. This gate checks fresh
  data in the right direction; the validation bar carries the multiple-testing weight.

## Effective N and PBO (reported, not gates)

- Effective N: the clusters of this run's genomes (one per behaviour) by average linkage on 1 - correlation of their
  in-sample returns, cut at a correlation of 0.5; books that never move are one cluster.
- PBO by CSCV (Bailey, Borwein, Lopez de Prado, Zhu) over the same genomes: 16 blocks, all 12,870 half splits; the
  share of splits in which the in-sample best by Sharpe ranks in the lower half out of sample.
- Both are in every weekly and F2 report ("Overfitting of the search"). Neither changes N: the registry's count is
  larger and decides.

## Judged by (tests)

- A pure-noise search (300 genomes, the best 6 by in-sample Sharpe each checked on 912 validation days) passes the
  bar in at most 5 % of 200 runs; a planted excess Sharpe of 3 a year passes in more than 80 %
  (`test_a_noise_ledger_passes_at_most_5_percent_and_a_planted_edge_mostly`).
- Prices moved after 2026-07-01 change no in-sample or validation number; only the logged look reads them.
- Equivalent genomes are one trial and one holdout pick; the clone shares the first one's look.
- PBO is near 0.5 for noise and under 0.1 for a clear edge; effective N finds planted clusters.
- The first weekly report after this commit states PBO and effective N.

## What changes for the books

- The active weekly shadow (44444c97ba5e, entered 2026-10-14, validation DSR 0.004 on the raw bar) is reviewed
  against the excess bar and needs a lockbox look; without one it is retired at review.
- Nothing new can be promoted before a lockbox look. Numbers from the first run (the excess variance, the new bar,
  PBO, effective N) follow in its report.
