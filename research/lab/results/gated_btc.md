# Do the Alpaca books beat BTC held only above its 200-day average?

Run 2026-10-21 as registered in `results/gated_btc_prereg.md` (committed
first, in its own commit). Code: `lab.experiments.gated_btc`. The tables below
the marker are generated.

## What it says

**No book beats gated BTC at the same risk with a bootstrap band above zero,
and the gate is what carries the momentum books.**

- **tsmom_top20 is no better than gated BTC** (kill rule): D -0.02 at 35 bps,
  -0.26 at 70, flat in every year. Matched to its in-sample risk, BTC held
  only above its 200-day average at 19 % weight did the same job with a
  slightly smaller drawdown (7 % against 9 %). As registered, the write-up
  recommends that the autopilots stop choosing it; nothing is changed here.
- **tsmom_tranches** (D 0.13) and **trend4h_pullback** (D 0.14 at its maker
  base, -0.09 with close fills at 35 bps, -0.25 at 70; drawdown 44 % against
  G's 31 %) are not shown to beat it either.
- **breakout_top10 comes closest and is the only book with a plausible edge
  over the gate**: D 0.55 at 35 bps and 0.50 at 70, about 8 % a year above G
  at 40 % weight, 78 % of bootstrap draws above zero, but the 5 % bound is
  -0.52 and 2026 so far is negative (-0.99). Not shown.
- Every book loses money on the days the gate is off (Sharpe -0.76 to -2.56
  on those days) and earns on the days it is on; their daily correlation with
  G is 0.55 to 0.70. In sample the books looked far better than G (1.45 to
  1.86 against 1.04 to 1.10); out of sample the margin is gone except for
  breakout.
- One caveat cuts in the books' favour: their out-of-sample vol ran 5 to 25 %
  above the in-sample match (ratios 1.05 to 1.25), so each D carries a little
  extra exposure that G did not get.

Only one of the four is killed, so the registered consequence "the
Alpaca book set is gated BTC exposure, stop adding trend variants on Alpaca
coins" is not triggered as a rule; the plain reading is that it holds for the
two momentum books and the 4h book, and breakout is the open question.

## G as a paper book

No book passes and G's own record at full weight passes G1 to G5, so the
study proposes it, as registered, and says plainly what it is: **BTC held
only above its 200-day average makes Sharpe 0.68 from 2024 against 0.74 for
BTC bought and held, 20 % a year against 27 %, with a 33 % drawdown against
53 %.** It does not beat BTC; it cuts the drawdown. It fails deflation (p
0.0003 over 1,724 trials), so it is added as an **experimental** lab book,
`btc_gated` (`lab.paper.btc_gated`, `results/experiments.md` section 5): an
autopilot-only, experimental signal that no autopilot runs unless one names
`lab:btc_gated`, and a job `paper-btc-gated` in `research/ops/jobs.yaml`
added disabled. Nothing is deployed.

<!-- generated below by lab.experiments.gated_btc; edit above this line only -->

# Alpaca books against gated BTC: results

Generated 2026-10-20T22:09:40+00:00. Registered in `results/gated_btc_prereg.md` before the run.

In sample 2020-08-01 to 2023-12-31, out of sample 2024-01-01 to 2026-10-14 (1018 days). Daily books at 35 bps per unit of turnover (stress 70), coins Alpaca does not list in cash; trend4h_pullback (B EMA 24/96 · p 0.5 · W 1h · BTC gate, 33 coins, 1h bars) at fast_maker's maker base (stress: every order at the close at 70 bps). G = BTC at weight k while its close is above its 200-day average, k = the book's in-sample vol over G's at k = 1, capped at 1.

## Verdict per book

- **breakout_top10**: not shown to beat gated BTC. D 0.55 at 35 bps (book 1.17, G at k 0.40 0.70), band -0.52 to 1.57, stress 0.50, years 0.97 / 0.85 / -0.99, drawdown 16 % against G's 14 %. Failed: 3 bootstrap 5 % <= 0.
- **tsmom_top20**: no better than gated BTC at the same risk. D -0.02 at 35 bps (book 0.54, G at k 0.19 0.68), band -1.03 to 1.00, stress -0.26, years 0.02 / -0.02 / -0.09, drawdown 9 % against G's 7 %. Failed: 1 D Sharpe <= 0; 2 D positive in 1 of 3 years; 3 bootstrap 5 % <= 0; 4 D <= 0 at stress.
- **tsmom_tranches**: not shown to beat gated BTC. D 0.13 at 35 bps (book 0.65, G at k 0.20 0.70), band -0.94 to 1.17, stress 0.11, years 0.31 / 0.30 / -0.63, drawdown 9 % against G's 8 %. Failed: 3 bootstrap 5 % <= 0.
- **trend4h_pullback**: not shown to beat gated BTC. D 0.14 at maker base (book 0.71, G at k 0.90 0.67), band -0.94 to 1.15, stress -0.25, years 0.51 / -0.46 / 0.50, drawdown 44 % against G's 31 %. Failed: 3 bootstrap 5 % <= 0; 4 D <= 0 at stress; 5 drawdown above G's + 5 pp.

## Books and G

| book | judged_at | k | vol_ratio_is | vol_ratio_oos | book_is | g_is | book_oos | g_oos | book_cagr_pct | g_cagr_pct | book_dd_pct | g_dd_pct | book_stress | g_stress | corr | corr_btc |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| breakout_top10 | 35 bps | 0.40 | 0.93 | 1.05 | 1.45 | 1.05 | 1.17 | 0.70 | 18.49 | 9.64 | 15.99 | 14.38 | 1.04 | 0.60 | 0.55 | 0.48 |
| tsmom_top20 | 35 bps | 0.19 | 0.95 | 1.22 | 1.68 | 1.10 | 0.54 | 0.68 | 4.44 | 4.71 | 8.99 | 7.41 | 0.29 | 0.59 | 0.69 | 0.52 |
| tsmom_tranches | 35 bps | 0.20 | 0.95 | 1.25 | 1.85 | 1.10 | 0.65 | 0.70 | 5.85 | 5.10 | 8.79 | 7.85 | 0.56 | 0.61 | 0.70 | 0.54 |
| trend4h_pullback | maker base | 0.90 | 0.95 | 1.13 | 1.86 | 1.04 | 0.71 | 0.67 | 21.66 | 18.29 | 43.77 | 30.99 | 0.30 | 0.57 | 0.62 | 0.48 |

## The difference D = book minus G

| book | d_oos | d_mean_ann | boot_p05 | boot_p95 | boot_above0 | d_stress | d2024 | d2025 | d2026 | d_years_pos | d_deflated_p | passes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| breakout_top10 | 0.55 | 0.08 | -0.52 | 1.57 | 0.78 | 0.50 | 0.97 | 0.85 | -0.99 | 2 | 0.00 | no |
| tsmom_top20 | -0.02 | -0.00 | -1.03 | 1.00 | 0.49 | -0.26 | 0.02 | -0.02 | -0.09 | 1 | 0.00 | no |
| tsmom_tranches | 0.13 | 0.01 | -0.94 | 1.17 | 0.58 | 0.11 | 0.31 | 0.30 | -0.63 | 2 | 0.00 | no |
| trend4h_pullback | 0.14 | 0.04 | -0.94 | 1.15 | 0.58 | -0.25 | 0.51 | -0.46 | 0.50 | 2 | 0.00 | no |

Bootstrap: stationary, mean block 20 days, 4000 draws, seed 20261020, 5 % and 95 % of D's annual Sharpe. `d_mean_ann` is D's mean daily return x 365.


## Per year (Sharpe at the judged cost)

| book | b2024 | g2024 | d2024 | b2025 | g2025 | d2025 | b2026 | g2026 | d2026 |
|---|---|---|---|---|---|---|---|---|---|
| breakout_top10 | 2.19 | 1.52 | 0.97 | 0.32 | -0.54 | 0.85 | -0.02 | 1.12 | -0.99 |
| tsmom_top20 | 1.56 | 1.46 | 0.02 | -0.35 | -0.47 | -0.02 | 0.49 | 1.10 | -0.09 |
| tsmom_tranches | 1.67 | 1.50 | 0.31 | -0.08 | -0.47 | 0.30 | 0.25 | 1.10 | -0.63 |
| trend4h_pullback | 1.70 | 1.42 | 0.51 | -0.91 | -0.52 | -0.46 | 1.12 | 1.18 | 0.50 |

## Where the books earn: by the BTC gate at the previous close

| book | book_sharpe_gate_on | book_sharpe_gate_off | book_ret_gate_off_ann |
|---|---|---|---|
| breakout_top10 | 1.73 | -0.76 | -0.05 |
| tsmom_top20 | 0.71 | -1.85 | -0.00 |
| tsmom_tranches | 0.93 | -1.06 | -0.02 |
| trend4h_pullback | 0.92 | -2.56 | -0.01 |

trend4h_pullback with every order at the close at 35 bps (reported, not judged): Sharpe 0.51, D -0.09.


## G's own record at k = 1

In sample 1.04 (halves 0.94 / 1.36). Out of sample 0.68 at 35 bps, 0.58 at 70, CAGR 20 %, drawdown 33 %; a close late 0.48; years 1.44 / -0.52 / 1.19; in BTC on 61 % of days, 10.0 switches and 10.0x turnover a year. BTC bought and held: 0.74, CAGR 27 %, drawdown 53 %. Deflated p over the pool 0.0003.

| variant | is | h1 | h2 | oos_35 | oos_70 | cagr_pct | dd_pct | late | y2024 | y2025 | y2026 | boot_p05 | boot_p95 | deflated_p | turnover_yr |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| BTC above its 200-day average, k = 1 | 1.04 | 0.94 | 1.36 | 0.68 | 0.58 | 19.79 | 33.26 | 0.48 | 1.44 | -0.52 | 1.19 | -0.34 | 1.73 | 0.00 | 10.04 |

- G1 both in-sample halves above 0: passed
- G2 above 0 at 35 and 70 bps: passed
- G3 drawdown below BTC bought and held: passed
- G4 a close late above 0: passed
- G5 positive in 2 of 3 years: passed

No book passes and G passes G1 to G5: proposed as the lab paper book `btc_gated` (autopilot-only signal, forward evidence only, off by default).


## Pool

1,724 trials (1,115 hand, 600 factory, 9 registered today); the best noise trial sits at an annual Sharpe of about 2.72.
