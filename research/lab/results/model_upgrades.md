# X11 model upgrades

2026-10-20. Can the models that still have a job get better, out of sample
from 2024, against the version that runs today? Every test was
pre-registered in `model_upgrades_prereg.md` (committed before any number
below existed). The generated reports are `m2_v3.md`, `m1_flow.md`,
`m8_trim.md` and `drift_window.md`; runs on the PC against the server's
mirror (data to 2026-10-19).

## The short version

| Part | Registered test | Result | Verdict |
|---|---|---|---|
| a. M2 v3 | new feature groups, selected on 2022-23, against v2 from 2024 (H1 whole universe, H2 Alpaca, H3 with low vol; t above 2.39, 2 of 3 years) | selection kept only the market group; IC 0.140 vs 0.146 (t -2.44), Alpaca 0.114 vs 0.122 (t -1.52), with low vol 0.155 vs 0.158 (t -2.54) | **Fails. v2 stays.** |
| b1. M1 + flow | QLIKE lower, DM p below 0.025, 2 of 3 quarters | 0.2189 vs 0.2216 (1.2 % lower), DM p 0.054, 7 of 12 quarters | **Fails.** M1 unchanged |
| b2. M1 + order book | the same on the recorder's book, at least 3,000 coin-hours | 0.2682 vs 0.2601 for M1 alone (worse), 5,740 coin-hours | **Fails** |
| c1. M8u (90 % quantile only) | 0.9 pinball below baseline, DM p below 0.05 | 88.0 vs 92.3 bps (4.6 % lower), DM p 6e-12, 19 of 24 quarters; from 2024 80.2 vs 84.0 bps, DM p 1e-6 | **Passes.** Joins the zoo (shadow, nothing reads it) |
| c2. M8u trim on the books | X6's six gates plus above the control, 18 trials | every pick fails gates 1, 3 and 6 (best: tranches 0.68 vs 0.64, band -0.03 to 0.12, 1 of 3 years) | **Fails.** Nothing wired |
| d. Calibrated drift test | leave-one-year-out false alarms at most 7.5 %, OOS shift at most 20 %, power 90 % on 2-sigma, frozen-feed and unit faults | false alarms 26 to 58 %, power 74 to 87 % (2 sigma), 73 to 83 % (frozen), 100 % (units) | **Not accepted.** Rule unchanged |
| e1. Claude analyst | forward only, after 26 weeks | built, not yet run (no key on the PC) | shadow job, disabled until deployed |
| e2. Claude news sentiment | forward only, after 26 M2 weeks | built, collector checked on the live feeds | shadow job, disabled until deployed |

Nothing changes live behaviour. One model joins the zoo (M8u), one forward
shadow is registered after the fact (M2 v3 without the market group, below),
and three jobs are added disabled.

## The pool

Sharpe trials: 930 hand trials before this study, 600 in the factory ledger,
18 here (c2): **1,548**, a noise bar of Sharpe 2.69. The IC and loss tests
(a: 3, b: 2, c1: 1, d: 1) are corrected inside their parts as registered.
The addendum to a (below) looked at 7 variants after the fact; it is not a
result and only its forward record will count.

## a. M2 v3: fails as registered

Same 581,663 coin-days, parameters and quarterly walk-forward from 2022 as
v2. Mean daily rank IC on the 7-day label:

| variant | 2022-23 (selection) | from 2024 | Alpaca 32 | Alpaca 15 | with low vol |
|---|---|---|---|---|---|
| v2 (today) | 0.127 | 0.146 | 0.122 | 0.089 | 0.158 |
| v3, all five groups | 0.126 | 0.151 | 0.124 | 0.071 | 0.160 |
| v3 without F (funding dynamics) | 0.129 | 0.150 | 0.117 | 0.053 | 0.160 |
| v3 without P (positioning) | 0.126 | 0.146 | 0.116 | 0.083 | 0.158 |
| v3 without M (market state) | 0.126 | 0.154 | 0.125 | 0.072 | 0.162 |
| v3 without T (52-week high, volume) | 0.132 | 0.150 | 0.114 | 0.055 | 0.159 |
| v3 without V (90-day and idiosyncratic vol) | 0.127 | 0.145 | 0.118 | 0.067 | 0.158 |
| **v3[M] (the registered pick)** | 0.125 | **0.140** | 0.114 | 0.095 | 0.155 |

The selection window barely separated the groups (all within 0.006 of each
other in 2022-23), and the rule kept only M, the market-state inputs (premiums,
stablecoin growth, DVOL, market funding). Alone they make the ranking worse
from 2024 (H1 t -2.44, 3 of 3 years worse). The trees spend 31 % of their gain
on the six market inputs: one value per day lets them split days into regimes,
which fits the past and does not carry forward. Positioning (P) covers only
the 20 coins with Binance metrics archives (6 to 9 % of coin-days). None of
the new groups helps among the Alpaca coins: their best is +0.003 (t 0.5).

**Addendum, after the registered test (not a result).** v3 without the market
group is the best variant from 2024: IC 0.154 vs 0.146, paired t 3.41, better
in 3 of 3 years; among the Alpaca coins +0.003 (t 0.5). It was picked after
seeing 2024-26, out of 7 variants, so it proves nothing. It is registered
here for a forward test only: `python -m lab.experiments.m2_v3 --shadow`
(job `m2-v3-shadow`, disabled until deployed) trains v2 and v3[F, P, T, V]
each Monday on all labelled history, writes both rankings down before the
outcome and scores them after 7 days (`<data>/paper/m2_v3_shadow/`). It passes
after 26 weekly rankings if v3's mean weekly IC is above v2's with a paired t
above 2. Nothing reads it; v2 stays the engine's and the paper books' M2.

## b. M1 with flow inputs and the order book

**b1.** Nine flow inputs (per coin: latest funding, open-interest changes
over 1 and 24 hours, long/short ratio, perp taker ratio; market: the Coinbase
premium at that hour, yesterday's DVOL, Korean premium and stablecoin growth),
both models refit on each of 12 quarters from 2024-Q1, 491,020 coin-hours:

| model | QLIKE | vs M1 | DM p | quarters better |
|---|---|---|---|---|
| M1 | 0.2216 | | | |
| M1 + flow (the test) | 0.2189 | 1.2 % lower | 0.054 | 7 of 12 |
| M1 + per-coin flow (diagnostic) | 0.2167 | 2.2 % lower | 0.17 | 10 of 12 |
| M1 + market flow (diagnostic) | 0.2198 | 0.8 % lower | 0.40 | 6 of 12 |

Fails (p above 0.025, 7 of 12 quarters). Nearly half the gain is one quarter
(2025-Q4, 0.451 vs 0.465, the quarter with the October 2025 liquidations); the
per-coin inputs look steadier (10 of 12) but were a diagnostic, not the test.
If anyone wants it, it needs its own registration; and even a pass would only
give a lab-side shadow, since the engine cannot compute these inputs live.

**b2.** A daily-refit linear correction of M1 on top-5 imbalance, spread and
depth change from the recorder's Binance book (2026-09-30 on, 5,740 coin-hours
scored from 2026-10-08): QLIKE 0.2682 against 0.2601 for M1 alone, worse. An
intercept-only correction (not registered) does the same (0.2678): the three
weeks of book add nothing over re-centring. Rerun when the record is 90 days.

## c. M8q's upper tail

**c1. M8u passes.** One quantile regression at 0.9, M8q's inputs and
parameters: 0.9 pinball 88.0 bps against 92.3 for the baseline (4.6 % lower),
DM p 6e-12, 19 of 24 quarters; from 2024 80.2 against 84.0 bps (DM p 1e-6).
88.8 % of days at or below the forecast from 2024 (90 % wanted; the baseline
90.1 %). M8u joins the zoo (`lab/models/m8_upper.py`): retrained weekly by the
`models` job, scored in shadow daily, nothing reads it. M8q stays with a use
rule that says only its 90 % quantile has skill.

**c2. The trim fails.** Out of sample from 2024 at 35 bps, books as the
autopilot runs them on Alpaca:

| pick | OOS 35 | book alone | band of the difference | years better | control | gates failed |
|---|---|---|---|---|---|---|
| take-profit, breakout_top10 | 1.15 | 1.17 | -0.04 to 0.01 | 0 of 3 | 0.56 | 1, 2, 3, 4, 5, 6 |
| take-profit, tsmom_top20 | 0.50 | 0.53 | -0.07 to 0.00 | 1 of 3 | 0.07 | 1, 3, 5, 6 |
| exhaust, tsmom_tranches | 0.68 | 0.64 | -0.03 to 0.12 | 1 of 3 | 0.55 | 1, 3, 6 |

M8u does beat its control (plain trimming after a run-up, which costs these
momentum books 0.1 to 0.6 of Sharpe), so its upside forecast is real; it is
just too rarely low on coins the books hold (2 to 16 % of held coin-days) to
help them. The tranches pick's small gain is not distinguishable from zero
(deflated p of the difference 0.01). A first run left breakout's held
positions untrimmed (that book keeps positions with empty targets); it was
fixed before the numbers above, with a test, and nothing else changed.

## d. The drift test: form W not accepted

Per input, cuts at a quantile of its own training windows' PSI and outside
share, one quantile per model so at most 5 % of training windows trip:

| model | false alarms, fitted | leave one year out | OOS shift | 2 sigma | frozen feed | units x 100 | 1 sigma (X9: 31 to 58 %) |
|---|---|---|---|---|---|---|---|
| M8 | 13 % | 35 % | 13 % | 87 % | 73 % | 100 % | 55 % |
| M10 | 14 % | 58 % | 30 % | 74 % | 74 % | 100 % | 53 % |
| M12 | 1 % | 26 % | 17 % | 80 % | 83 % | 100 % | 52 % |

Even at the 99.9 % quantile the fitted rate stays above 5 % for M8 and M10,
and judged honestly (cuts from the other years) a year that was not in the
calibration trips 26 to 58 % of the time: each training year is its own
regime, so input spread is never "stable" out of sample. The slowest
market-wide inputs (market vol, the 200-day gap, BTC trend) stay hard to move
even by two sigma. Third attempt at an input-spread test, third failure; the
next attempt should test the model's recent loss against its training loss, as
X9 recommended. `core.drift_check` stays; the calibration function stays
in `core` for that study.

## e. Claude as a model

Both are judged on forward data only: a language model has read the news of
any period we could backtest on.

**e1. Weekly analyst** (`lab/ai/analyst.py`, Sonnet 5.5 through the engine's
metered endpoint, Batches API). Runs after the M2 v2 paper book on its
rebalance day, so its ranking and M2's share a reference close. A fact sheet
per Alpaca coin with Binance history (returns, vol, distance to the 52-week
high and 200-day mean, volume trend, funding) and four market lines; no model
of ours. It returns per coin the probability of a higher close in 7 days and
an expected rank. Recorded in `<data>/ai/analyst.jsonl` before the week,
scored weekly by rank IC against the low-vol rank, 28-day momentum and M2's
rank on the same day (`reports/ai_analyst/latest.json`). Pass after 26 weeks:
IC above 0 with t above 2 and above low vol with a paired t above 2.

**e2. Daily news sentiment** (`lab/ai/news.py`, Haiku 5.5, Batches API).
Headlines (titles only) from the public RSS feeds of CoinDesk, Cointelegraph,
Decrypt, The Block, CryptoSlate and Bitcoin Magazine, collected every 4 hours
and matched to coins by name and ticker; one call a day scores yesterday's
headlines per coin from -1 to 1, so nothing published after the reference
close is used. Google News RSS was checked and dropped: its feed allows use
only in a personal feed reader. A trial collection on the PC found 131
headlines over five days, 53 about BTC and only a handful about any other
coin, so most Alpaca coins will score neutral on most days; the registered
test (M2's percentile averaged with the sentiment's against M2 alone among
the Alpaca coins, 26 M2 weeks, paired t above 2) will say whether that is
enough.

**Cost.** Nothing was called from the PC (no key here); spent by this work:
$0.00. The engine's ledger on the mirror holds $0.021 lifetime (seven brief
calls). Expected: the analyst prompt is about 1,900 tokens in and up to
6,000 out once a week (Sonnet, batch: about $0.01 to $0.05 a call by the
weekly review's numbers in `docs/AI.md`), the news call about 600 to 1,500 in
and under 1,000 out a day (Haiku, batch: about the brief's $0.0005). Together
well under $1 a month, far inside the caps on the mirror (5 USD a day, 90 a
month, 180 lifetime) and the owner's 8 USD a day. Every call is in the
engine's ledger; each job's report sums its own calls (`cost_usd_total`).

## What changed

| Change | Where | Default |
|---|---|---|
| M8u in the zoo (weekly retrain, daily shadow) | `lab/models/m8_upper.py`, `zoo.py`, `guard.py`, German title in `i18n.py` | on with the `models` job; nothing reads it |
| M8q's use rule: only q90 | `lab/models/m8_quantiles.py` | |
| M2 v3 study and weekly forward shadow | `lab/experiments/m2_v3.py`, `results/m2_v3_final.json` | job `m2-v3-shadow` disabled |
| M1 flow and order-book study | `lab/experiments/m1_flow.py` | |
| Trim study | `lab/experiments/m8_trim.py` | |
| Window drift calibration and study | `core.drift_calibration_window`, `lab/models/drift_study_w.py` | not used by the zoo |
| Claude analyst | `lab/ai/analyst.py` | job `ai-analyst` disabled |
| News collector and sentiment | `lab/ai/news.py` | jobs `news-collect`, `ai-news` disabled |
| Tests | `tests/test_model_upgrades.py`, `tests/test_model_zoo.py` | |

### Switching things on (on the server, after the lab code is deployed)

```bash
research/ops/deploy_lab.sh        # from a checkout with this branch merged
```

Then set `enabled: true` on `m2-v3-shadow`, `ai-analyst`, `news-collect` and
`ai-news` in `research/ops/jobs.yaml` and run `research/ops/deploy_ops.sh`.
Check each once by hand:

```bash
docker run --rm -v /srv/pythia-data:/data -v /opt/pythia-lab:/app pythia-lab python -m lab.ai.news --collect
docker run --rm --network host --env-file /etc/pythia/alerts.env -v /srv/pythia-data:/data -v /opt/pythia-lab:/app pythia-lab python -m lab.ai.analyst --dry-run
docker run --rm --network host --env-file /etc/pythia/alerts.env -v /srv/pythia-data:/data -v /opt/pythia-lab:/app pythia-lab python -m lab.ai.news --dry-run
```

The M8u card appears after the next `models` run (Sundays retrain M8, M8q
and M8u). Nothing above reaches an order.
