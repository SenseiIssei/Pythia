# breakout_top10 with its BTC beta hedged

Run 2026-10-21 on the server as registered in
`results/hedged_breakout_prereg.md` (committed first). Code:
`lab.experiments.hedged_breakout`; the sweep panel as the paper jobs built it
on 2026-10-21 and the 2026-10-07 `xs_daily` cache (for `perps_neutral`),
both copied unchanged into a study folder and removed after the run. The
tables below the marker are generated.

## What it says

**No. Both trials fail; nothing is added.**

- **H, the hedged book, fails one gate.** Hedged by minus its holdings beta
  in the BTC perp (on average 0.32 of book equity on invested days), the
  book keeps a Sharpe of **0.63 from 2024 at 35/10 bps** (0.27 at the 70/20
  stress, 0.77 at the Binance 15/10 level), 7 % a year, drawdown 13 %,
  correlation with BTC +0.02, a day late 0.38. The bootstrap band runs from
  -0.50 to 1.57 (83 % of draws above 0): the alpha is not shown to exist.
  2026 is negative (-0.47). Deflated p 0.0002 over 1,977.
- The unhedged book (1.06 from 2024 at 35 bps, reproducing
  `alpaca_universe`'s 1.06) is only 0.23 BTC beta by regression but 0.52
  correlated with BTC; its alpha against BTC is 13.7 % a year with t 1.31
  out of sample (22.7 %, t 1.86, in sample). Most of what the book earns is
  timed market exposure, and the hedge takes the 2024 rally out with it.
- H is close to uncorrelated with `perps_neutral` (-0.13; -0.20 with M4,
  -0.03 with carry and low vol), so it would diversify. But it is too weak:
- **C, H and `perps_neutral` at equal risk, fails gate 1**: Sharpe 1.98
  against `perps_neutral`'s 2.47 alone on the same days (drawdown 5.5 %
  against 10 %), the band of the difference -1.37 to 0.28. Equal risk puts
  two thirds of the capital in H because H is the calmer book, and H's
  Sharpe of 0.68 drags the mix down. Deflated p 0.09.
- Reported, not judged: hedged by the book's trailing 60-day return beta
  H makes 0.85 (it hedges less right after entries, so it keeps more BTC
  exposure), and on the coins Alpaca lists 0.79 with 2026 at -1.89.

Data note: the sweep panel's perp funding file is the one the paper job
built on 2026-10-08 (funding to 2026-10-06), so the hedge earns no funding
on the last 14 of 1,024 out-of-sample days. The hedge's margin is not charged.

<!-- generated below by lab.experiments.hedged_breakout; edit above this line only -->

# breakout_top10 with its BTC beta hedged: results

Generated 2026-10-21T20:39:40+00:00. Registered in `results/hedged_breakout_prereg.md` before the run.

Sweep panel to 2026-10-20; out of sample from 2024-01-01 (1024 days). Costs per unit of one-way turnover as (long leg, hedge): judged 35/10 bps, stress 70/20, the paper book's Binance level 15/10. perps_neutral rebuilt from its study's functions: holdout Sharpe 2.4672 at 10 bps (published 2.47).

## Trial 1, H: the hedged book

**Fail.**

- 1 Sharpe above 0.5 at the judged cost and above 0 at the stress cost: yes
- 2 positive in 2 of 2024, 2025, 2026: yes
- 3 bootstrap 5 % above 0: no
- 4 correlation with BTC within +-0.3: yes
- 5 one day late above 0: yes

From 2024 at the judged cost H makes Sharpe 0.63, 7.3 % a year, drawdown 13.1 %, correlation with BTC +0.02; bootstrap band -0.50 to 1.57 (83 % of draws above 0); deflated p 0.0002. The unhedged book's alpha against BTC: 13.7 % a year (t 1.31), beta 0.23 out of sample; in sample 22.7 % (t 1.86), beta 0.22.

| series | is | sharpe | cagr_pct | dd_pct | vol_pct | corr_btc | y2024 | y2025 | y2026 |
|---|---|---|---|---|---|---|---|---|---|
| book · judged | 1.35 | 1.06 | 21.59 | 21.71 | 20.41 | 0.52 | 1.84 | 0.46 | 0.38 |
| H · judged | 1.19 | 0.63 | 7.28 | 13.09 | 12.48 | 0.02 | 1.09 | 0.92 | -0.47 |
| book · stress | 1.25 | 0.90 | 17.71 | 24.17 | 20.39 | 0.52 | 1.71 | 0.28 | 0.16 |
| H · stress | 1.00 | 0.27 | 2.61 | 15.42 | 12.49 | 0.02 | 0.80 | 0.54 | -0.96 |
| book · binance | 1.40 | 1.15 | 23.86 | 20.28 | 20.42 | 0.52 | 1.92 | 0.56 | 0.51 |
| H · binance | 1.28 | 0.77 | 9.29 | 12.45 | 12.47 | 0.02 | 1.21 | 1.06 | -0.26 |
| H · one day late | 1.09 | 0.38 | 4.12 | 14.74 | 12.51 | 0.03 | 0.88 | 0.70 | -0.79 |
| H · trailing book-return beta | 0.90 | 0.85 | 13.97 | 15.44 | 17.05 | -0.04 | 1.24 | 0.50 | 0.65 |
| H · Alpaca coins, rest in cash | 1.15 | 0.79 | 7.48 | 10.58 | 9.73 | 0.03 | 1.72 | 0.47 | -1.89 |

`is` is the Sharpe 2020-08 to 2023, the rest from 2024. `book` is breakout_top10 unhedged, `H` with the hedge; the last three rows are H at the judged cost decided a close late, hedged by the book's own trailing 60-day return beta, and on the coins Alpaca lists (the rest in cash).


The hedge on invested days from 2024: mean -0.32 of book equity (range -1.17 to -0.01); the book is invested on 82 % of days; the hedge earned 2.50 % a year in funding; turnover a year 12.1 on the hedge, 9.3 on the book.


Correlation of H's daily returns with perps_neutral on its holdout (2024-01-02 to 2026-09-29): -0.13; with its books M4 -0.20, carry -0.03, low vol -0.03.

## Trial 2, C: H and perps_neutral at equal risk

**Fail.**

- 1 Sharpe above perps_neutral's and drawdown not above its: no
- 2 Sharpe above 0.5 at the judged cost and above 0 at the stress cost: yes
- 3 positive in 2 of 2024, 2025, 2026: yes
- 4 bootstrap 5 % above 0: yes
- 5 correlation with BTC within +-0.3: yes

On 2024-01-02 to 2026-09-29 (1002 days) C makes Sharpe 1.98, 22.6 % a year, drawdown 5.5 %; bootstrap band 0.91 to 2.96; the band of the difference to perps_neutral alone -1.37 to 0.28 (15 % of draws above 0); deflated p 0.0915. H's weight in C: mean 0.66, range 0.41 to 0.88.

| series | sharpe | cagr_pct | dd_pct | vol_pct | corr_btc | y2024 | y2025 | y2026 |
|---|---|---|---|---|---|---|---|---|
| C · judged | 1.98 | 22.61 | 5.52 | 10.60 | -0.03 | 2.38 | 2.54 | 0.52 |
| C · stress | 1.48 | 16.41 | 7.86 | 10.62 | -0.03 | 1.90 | 2.07 | -0.03 |
| perps_neutral · 10 bps | 2.47 | 62.96 | 10.02 | 20.67 | -0.05 | 2.28 | 3.10 | 1.86 |
| H · judged, same window | 0.68 | 8.11 | 13.09 | 12.56 | 0.02 | 1.07 | 0.92 | -0.26 |

Weights proportional to 1 / trailing 90-day volatility, set on the first day of each month, drifting in between; reweights charged at the long leg's cost. perps_neutral at 10 bps (20 in the stress row).


## Pool

Pool: 1,977 trials (1,353 hand before this registration, 600 factory as read now, 24 registered together on 2026-10-21: positioning_xs 5, taker_imbalance_xs 13, hedged_breakout 2, pead_xbrl 4); the best noise trial sits at an annual Sharpe of about 2.76. The next study starts from 1,377 hand trials.
