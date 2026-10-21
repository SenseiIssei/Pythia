# One book from the market-neutral perp books

Run 2026-10-21 on the server as registered in
`results/perps_neutral_portfolio_prereg.md` (committed first). Code:
`lab.experiments.perps_neutral_portfolio`; M4 and funding carry on the
2026-10-07 `xs_daily` cache (copied unchanged from the PC into a study folder
on the server, `PYTHIA_CACHE`, removed after the run; a re-run needs the
same three cache files again), low vol on the sweep panel as the paper jobs
built it on 2026-10-21. The tables below the marker are generated.

## What it says

**Pass as registered, not confirmed: an experiment.** The pick (equal risk
contribution, the best of the three methods in 2022-03 to 2023 at 10 bps,
1.18 against 1.08 and 1.07) holds M4 reg7n, funding carry and the low-vol
beta-neutral book, reweighted monthly:

- from 2024 (1,002 days to 2026-09-29) Sharpe **2.47 at 10 bps** (2.66 at
  the 2 bps maker level, 2.23 at 20, 1.73 at 41), 63 % a year, **drawdown
  10 %**, correlation with BTC **-0.05**, 49x turnover a year; 2024 2.28,
  2025 3.10, 2026 1.86; bootstrap band 1.66 to 3.28;
- the reference book (the single book a researcher would have picked in
  2022-23, M4) makes 2.20 with a 15 % drawdown; the combination beats it on
  both, but the band of the Sharpe difference is -0.55 to 1.06 (69 % of
  draws above 0): the gain is diversification, not proven to be more;
- deflated p **0.32** over the pool of 1,953 (bar 2.75): **not confirmed**.

What tempers it:

- The three methods are the same book: equal weight makes 2.56 out of
  sample, inverse vol 2.54, ERC 2.47; the trailing weights stay within 0.2
  to 0.5 per book. Picking ERC bought nothing; any fixed one-third split does
  as well.
- Two of the three books are one bet: M4 and low vol are 0.44 to 0.49
  correlated (both short the hot, volatile small caps that bled in
  2024 to 2026). Funding carry is the diversifier (correlation -0.04 to
  -0.16 with both) but the weakest book: 0.68 at 10 bps, -0.32 in 2026,
  negative at 41 bps.
- Low vol earned 0.50 in the selection window and 2.08 after it: the
  holdout years were the kind this bet likes (see `family_lowvol.md`).
- Each book alone and the combination are on Binance's survivorship-free
  perps; the Kraken-listed restriction the paper books apply was not
  tested here. Netting between books is not credited (costs are an upper
  bound), and the price legs use spot entry prices.

Added as the experimental paper book `perps_neutral` (job
`paper-perps-neutral`, disabled): see "If it passes" in the
pre-registration. It needs `paper-m4-perps` and `paper-funding-carry`
(disabled) running first.

<!-- generated below by lab.experiments.perps_neutral_portfolio; edit above this line only -->

# One book from the market-neutral perp books: results

Generated 2026-10-21T19:19:58+00:00. Registered in `results/perps_neutral_portfolio_prereg.md` before the run.

Selection 2022-03-01 to 2023-12-31, holdout 2024-01-02 to 2026-09-29 (1002 days, return days). M4 rebuilt from the 2026-10-07 xs_daily cache matches the cached pick series (largest difference 8.3e-17). Costs per unit of one-way turnover; judged at 10 bps.

## Verdict

**Pass, experimental (fails deflation).** Pick (best selection Sharpe at 10 bps): **ERC**; reference single book: **M4**.

- 1 Sharpe above 0.5 at 10 bps and above 0 at 20 bps: yes
- 2 positive in 2 of 2024, 2025, 2026: yes
- 3 bootstrap 5 % above 0: yes
- 4 above the reference book's Sharpe with a lower drawdown: yes
- 5 correlation with BTC within +-0.3: yes

The pick from 2024 at 10 bps: Sharpe 2.47 (2 bps 2.66, 20 bps 2.23, 41 bps 1.73), 63.0 % a year, drawdown 10.0 %, correlation with BTC -0.05, turnover 49x a year; bootstrap 90 % band 1.66 to 3.28. The reference M4 alone: 2.20, drawdown 15.3 %; band of the difference -0.55 to 1.06 (69 % of draws above 0). Deflated p 0.3191.

## Each book alone

| book | sel_10bps | hold_2bps | hold_10bps | hold_20bps | hold_41bps | hold_cagr_pct | hold_dd_pct | turnover_yr | corr_btc_sel | corr_btc_hold | y2024 | y2025 | y2026 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| M4 | 0.95 | 2.24 | 2.20 | 2.14 | 2.02 | 94.73 | 15.26 | 18.33 | -0.26 | -0.11 | 2.02 | 2.52 | 2.02 |
| Carry | 0.71 | 0.90 | 0.68 | 0.40 | -0.17 | 18.95 | 35.04 | 93.64 | -0.03 | -0.09 | 0.91 | 1.39 | -0.32 |
| LowVol | 0.50 | 2.14 | 2.08 | 2.01 | 1.85 | 81.28 | 16.41 | 22.82 | 0.02 | 0.10 | 2.19 | 2.03 | 2.11 |

Sharpe at each cost (daily x sqrt 365); CAGR, drawdown, turnover, years and correlations at 10 bps. LowVol has both legs on perps (longs pay funding).


Pairwise correlations of the books' daily net returns at 10 bps:

| window | M4_Carry | M4_LowVol | Carry_LowVol |
|---|---|---|---|
| selection | -0.05 | 0.49 | -0.16 |
| holdout | -0.06 | 0.44 | -0.04 |

Reproduction: the sweep's low-vol book (spot long leg, no funding on it) makes 2.15 / 1.96 at 15 / 41 bps from 2024 on today's panel (the sweep reported 2.11 / 1.91 to 2026-10-07), in sample 0.54 (0.54).


## The combinations

| method | sel_10bps | hold_2bps | hold_10bps | hold_20bps | hold_41bps | hold_cagr_pct | hold_dd_pct | turnover_yr | corr_btc_hold | y2024 | y2025 | y2026 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| EW | 1.08 | 2.73 | 2.56 | 2.34 | 1.89 | 66.44 | 9.62 | 45.15 | -0.05 | 2.50 | 3.01 | 2.07 |
| IV | 1.07 | 2.72 | 2.54 | 2.32 | 1.86 | 66.48 | 9.51 | 46.04 | -0.04 | 2.31 | 3.13 | 2.08 |
| ERC | 1.18 | 2.66 | 2.47 | 2.23 | 1.73 | 62.96 | 10.02 | 49.27 | -0.05 | 2.28 | 3.10 | 1.86 |

Book weights from 2024 at 10 bps (mean, min, max):

| method | w_M4_mean | w_M4_min | w_M4_max | w_Carry_mean | w_Carry_min | w_Carry_max | w_LowVol_mean | w_LowVol_min | w_LowVol_max |
|---|---|---|---|---|---|---|---|---|---|
| EW | 0.34 | 0.29 | 0.38 | 0.33 | 0.24 | 0.40 | 0.33 | 0.28 | 0.40 |
| IV | 0.31 | 0.22 | 0.42 | 0.34 | 0.17 | 0.46 | 0.35 | 0.27 | 0.44 |
| ERC | 0.30 | 0.19 | 0.45 | 0.38 | 0.22 | 0.52 | 0.32 | 0.26 | 0.43 |

Reweighted on the first day of each month from the trailing 90 days; book weights sum to 1, every book at 1x gross, so the book is at 1x gross before netting. Reweight trades are charged; netting between books is not credited.


## Pool

Pool: 1,953 trials (1,328 hand before this registration, 600 factory as read now, 25 registered together on 2026-10-21: perps_neutral_portfolio 3, attention_wiki 13, intraday_tsmom 9); the best noise trial sits at an annual Sharpe of about 2.75. The next study starts from 1,353 hand trials.
