# X15 candlestick patterns

Pre-registration: `candles_prereg.md` (committed before any number below
existed). Code: `lab/candles` (the library, 74 patterns and 6 derived
signals, tests in `tests/test_candles.py`), `lab/experiments/candles_data.py`,
`candles_study.py`, `candles_report.py`. Run on the PC on 2026-10-20: crypto
to 2026-10-19, equities to 2026-10-16.

## Verdict: nothing holds

| part | question | answer |
|---|---|---|
| A event study | does any of 80 signals predict the next 1, 3, 5 or 10 bars better than a random entry on the same bar? | No. 3 of 1,280 cells pass the in-sample screen (t >= 3, 100 events), all three bearish, and none holds out of sample (best OOS t 0.47, Holm over 3). More in-sample cells point the wrong way (t <= -3: 23) than the right way (3). Out of sample the number of cells with t >= 2 is what chance gives (14 against about 19 expected). |
| B long-only rules | do the best bullish signals make money as slot books after costs? | No. 12 rules, 0 pass. The best out of sample: SP harami_cross_bull 5 days, Sharpe 0.27 against SPY's 0.87 and the random books' 95th percentile 0.46; CD closing_marubozu_white 10 days 0.35 against BTC's 0.74, twin -0.28. Crypto 4h rules lose (-1.06 to -2.55). Deflated p 0.00 for every rule. |
| C M2 features | do candle inputs raise M2's rank IC? | No. v2 + C: IC 0.148 against 0.146 from 2024 (t 1.48); among the Alpaca coins 0.127 against 0.122, better in 3 of 3 years but t 1.58, below the registered 2.24. |
| D breakout filter | do candles improve breakout_top10's entries? | No. The pick (skip an entry when a bearish pattern ends on the breakout day) makes 1.21 against the book's 1.17, better in 1 of 3 years, bootstrap band of the difference -0.00 to 0.11, a day late 0.97; fails 5 of 6 gates. |

What the numbers say beyond the verdict:

- **Candles carry information, mostly the wrong way round for their names.**
  Across M2's whole universe, coins printing bullish candles on high volume
  rank worse over the next 7 days (`c_pick_bull_volume` IC -0.049, t -13.6
  from 2024; long white candle -0.042; a long upper shadow -0.029). That is
  the lab's old finding ("calm, beaten-down coins beat wild, hot ones") seen
  through candles, and M2 already has it: adding the candle group moves its
  IC by 0.002.
- **On the Alpaca coins the same bullish candles look better than random
  picks** (long white candle, 5 days: +93 bps against +47 bps for random
  entries on the same days). The permutation that says so treats events as
  independent; they are not (they cluster on strong days, and the 5-day
  windows overlap), so the registered Newey-West test is the one that
  counts, and it gives t 1.1.
- **Gap patterns do not exist on 24/7 markets.** Kickers, abandoned babies,
  tasuki gaps, neck lines, two crows and the ladder bottom fire almost never
  on crypto (0 to 0.1 per 1,000 bars); on equities they fire 0 to about 1
  per 1,000 bars and still show nothing.
- **Costs settle the rest.** Equity patterns that looked fine in sample at one
  day (homing pigeon, matching low, harami on ETFs: +12 to +15 bps a trade in
  sample, ahead of random entries) are flat or negative out of sample and do
  not survive double costs.

## The pool, with the studies run in parallel

This study ran on 948 hand trials, 600 factory genomes and its own 47
(1,595). X16 (`equities_training`, 120 trials) was published while it ran;
counting it, the hand count after X15 is **1,115** (948 + 120 + 47). A larger
pool only lowers a deflated p, and every part B rule is already at 0.00;
part D is deflated over its own 5 trials as registered. X14 (pump.fun early
exits, 58 trials) keeps its own pool as it reports.

## What is wired

- Nothing in the lab: no shadow signal, no M2 feature, no breakout variant,
  no `jobs.yaml` entry (the registered consequence of a pass; there is none).
- The engine has the library as a strategy kind (`candles`, Rust
  `crates/pythia-core/src/engine/candles.rs`, the same 74 definitions and
  the derived signals, checked bar for bar against this library on 10,942
  bars). The default `candles-1` ships **paused** and is labelled "research,
  no edge yet"; its switches start on the classic reversals (hammer,
  engulfing, piercing, the morning stars, three white soldiers, three inside
  and outside up), and every bullish pattern, including this study's part B
  picks, can be switched on in its parameters.

<!-- generated below by lab.experiments.candles_study -->

Generated 2026-10-20 by `python -m lab.experiments.candles_study`; crypto panel to 2026-10-19.

## A. Event study

Coverage (eligible instrument-bars):

| set | instruments | bars | eligible in sample | eligible out of sample | member days without a candle, in sample | same, out of sample |
|---|---|---|---|---|---|---|
| CD | 31 | 2,484 | 27,040 | 28,148 | n/a | n/a |
| CD twin | 307 | 2,484 | 42,030 | 30,690 | n/a | n/a |
| C4 | 31 | 14,904 | 162,001 | 168,868 | n/a | n/a |
| C4 twin | 307 | 14,904 | 251,803 | 184,112 | n/a | n/a |
| EF | 25 | 7,495 | 87,572 | 67,206 | 0.00 | 0.00 |
| SP | 1,742 | 7,495 | 1,839,623 | 1,367,543 | 0.19 | 0.00 |

Drift (mean return of every eligible bar, entry next open, before costs, bps):

| set | in sample 1 | in sample 3 | in sample 5 | in sample 10 | out of sample 1 | out of sample 3 | out of sample 5 | out of sample 10 |
|---|---|---|---|---|---|---|---|---|
| CD | 25.4 | 72.5 | 123.1 | 255.2 | 2.1 | 8.1 | 14.4 | 36.6 |
| CD twin | 15.8 | 40.3 | 71.7 | 153.8 | -9.5 | -26.2 | -40.6 | -73.8 |
| C4 | 3.8 | 11.6 | 19.9 | 40.0 | 0.4 | 1.3 | 2.2 | 3.7 |
| C4 twin | 2.3 | 6.1 | 11.1 | 22.0 | -1.5 | -4.7 | -7.7 | -16.0 |
| EF | -1.0 | 5.6 | 12.0 | 27.1 | 1.2 | 10.3 | 19.6 | 42.9 |
| SP | 2.0 | 11.1 | 19.7 | 40.5 | 1.3 | 12.0 | 23.0 | 50.1 |

1,280 cells (80 signals x 4 sets x 4 horizons). In-sample screen (at least 100 events, t >= 3): **3** candidates (CD 1, C4 0, EF 0, SP 2). Out of sample (Holm over 3, family 0.05, crypto twin agreeing): **0** hold, **0** of them bullish and tradeable after costs.

- CD: 140 cells with enough events; out of sample 2 have t >= 2 in the signal's direction (about 3 expected by chance); of the 25 with |t| >= 2 in sample, 13 keep the sign.
- C4: 212 cells with enough events; out of sample 6 have t >= 2 in the signal's direction (about 5 expected by chance); of the 25 with |t| >= 2 in sample, 19 keep the sign.
- EF: 192 cells with enough events; out of sample 4 have t >= 2 in the signal's direction (about 4 expected by chance); of the 20 with |t| >= 2 in sample, 10 keep the sign.
- SP: 292 cells with enough events; out of sample 2 have t >= 2 in the signal's direction (about 7 expected by chance); of the 53 with |t| >= 2 in sample, 29 keep the sign.

### Every in-sample candidate

Excess is over the same bar's random entry, signed by the signal's direction (positive = the pattern did what it says). Net is the mean return minus the round trip; drift is the mean of every eligible bar.

| set | signal | h | dir | IS events | IS excess bps | IS t | OOS events | OOS excess bps | OOS t | OOS p | twin OOS excess bps | OOS mean bps | OOS net bps | OOS drift bps | holds | tradeable |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| CD | engulfing_bear | 1 | -1 | 1,591 | 45.2 | 3.2 | 1,346 | 6.3 | 0.5 | 0.3 | 33.8 | -60.9 | -130.9 | 2.1 | no | no |
| SP | belt_hold_bear | 1 | -1 | 43,552 | 6.6 | 3.8 | 24,889 | 0.1 | 0.0 | 0.5 | n/a | 0.6 | -9.7 | 1.3 | no | no |
| SP | long_black | 1 | -1 | 229,368 | 3.4 | 3.0 | 168,305 | -1.6 | -1.3 | 0.9 | n/a | 6.1 | -4.2 | 1.3 | no | no |

### Every signal at 5 bars

In-sample and out-of-sample t of the signed excess, and how often the signal fires (per 1,000 eligible bars). All four horizons are in the JSON.

| signal | dir | CD per 1k | CD IS t | CD OOS t | C4 per 1k | C4 IS t | C4 OOS t | EF per 1k | EF IS t | EF OOS t | SP per 1k | SP IS t | SP OOS t |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| doji | neutral | 153.4 | 2.5 | 0.8 | 160.0 | 1.9 | 1.5 | 131.0 | 0.2 | -0.4 | 138.0 | 0.1 | -1.1 |
| long_legged_doji | neutral | 3.7 | 0.6 | 0.2 | 4.4 | 0.8 | 1.0 | 3.0 | 0.4 | -0.6 | 3.2 | 2.7 | -1.4 |
| rickshaw_man | neutral | 2.7 | 0.6 | -2.2 | 3.1 | 1.3 | 0.8 | 2.4 | 0.0 | -0.6 | 2.5 | 2.7 | -1.0 |
| dragonfly_doji | bull | 1.8 | -1.2 | -0.3 | 2.3 | -0.7 | -1.4 | 4.0 | 0.3 | 0.2 | 3.4 | 0.6 | 1.5 |
| gravestone_doji | bear | 1.0 | 3.7 | -0.0 | 1.5 | 0.1 | 0.6 | 2.5 | 0.3 | -0.6 | 2.7 | -1.8 | -1.0 |
| four_price_doji | neutral | 0.0 | n/a | n/a | 0.0 | n/a | n/a | 0.1 | 0.0 | 0.3 | 0.0 | 0.9 | 1.9 |
| takuri | bull | 0.1 | n/a | 2.4 | 0.2 | -1.4 | -0.1 | 0.4 | 0.2 | -0.3 | 0.4 | -0.5 | 0.7 |
| hammer | bull | 8.8 | -1.8 | 0.1 | 9.5 | -0.8 | -1.4 | 8.4 | 0.3 | -0.3 | 8.7 | -1.1 | -0.4 |
| hanging_man | bear | 5.4 | 0.6 | -1.0 | 7.3 | -0.7 | 0.0 | 15.6 | -0.7 | 0.9 | 12.6 | 2.0 | -2.0 |
| inverted_hammer | bull | 5.5 | -0.9 | 1.4 | 5.0 | 0.2 | -1.6 | 6.9 | 1.2 | 0.4 | 8.2 | 1.4 | 0.6 |
| shooting_star | bear | 5.5 | 0.6 | -0.1 | 6.7 | -0.1 | 0.7 | 7.7 | 0.1 | -0.5 | 9.1 | -1.3 | -0.8 |
| marubozu_white | bull | 1.9 | 0.3 | 0.1 | 2.8 | -2.9 | 1.9 | 10.5 | -0.7 | -0.2 | 7.2 | -2.8 | -1.4 |
| marubozu_black | bear | 1.1 | -1.0 | -1.0 | 2.2 | 0.3 | -1.2 | 8.9 | -1.3 | 0.6 | 6.7 | -1.6 | 0.0 |
| closing_marubozu_white | bull | 10.9 | -0.4 | 0.2 | 11.6 | 1.3 | -0.8 | 27.6 | -0.5 | -1.3 | 21.3 | -4.3 | -0.5 |
| closing_marubozu_black | bear | 6.7 | -1.1 | -0.1 | 7.5 | -2.2 | -1.7 | 22.8 | -3.1 | 0.3 | 18.7 | -4.1 | -0.3 |
| belt_hold_bull | bull | 8.6 | -0.9 | 0.8 | 10.8 | 1.1 | -0.6 | 17.5 | 0.7 | 1.2 | 17.0 | 1.3 | -0.1 |
| belt_hold_bear | bear | 11.1 | 0.8 | -0.4 | 11.4 | -0.0 | -0.8 | 26.4 | 0.9 | 1.8 | 21.5 | 2.2 | -1.2 |
| long_white | bull | 112.9 | 1.5 | 1.1 | 107.9 | 2.1 | 0.8 | 132.7 | -2.8 | -0.8 | 128.6 | -3.3 | -1.0 |
| long_black | bear | 108.0 | -0.2 | 0.4 | 109.8 | 0.1 | -2.4 | 139.0 | -1.9 | -0.1 | 124.0 | -2.2 | -0.2 |
| spinning_top | neutral | 91.1 | 0.4 | -0.2 | 90.8 | 0.3 | -1.1 | 80.9 | 0.6 | -1.4 | 87.3 | 0.2 | -3.1 |
| high_wave | neutral | 5.5 | 1.5 | -1.1 | 5.2 | 1.0 | -2.0 | 3.1 | 0.6 | -1.5 | 3.5 | 1.3 | -2.0 |
| engulfing_bull | bull | 66.0 | -1.7 | -1.7 | 60.0 | -1.5 | -1.4 | 14.0 | -1.2 | 0.1 | 20.7 | -0.1 | 0.4 |
| engulfing_bear | bear | 53.4 | 1.5 | 0.1 | 57.6 | 0.3 | 0.2 | 25.6 | 1.3 | -1.9 | 29.1 | 0.3 | -0.1 |
| harami_bull | bull | 7.7 | -3.0 | -1.0 | 7.1 | -0.7 | -0.9 | 6.1 | 0.3 | 1.1 | 6.4 | -1.0 | -0.9 |
| harami_bear | bear | 7.4 | -2.2 | -1.0 | 6.9 | -0.9 | 0.9 | 7.1 | -0.1 | 0.6 | 7.5 | 0.6 | 1.9 |
| harami_cross_bull | bull | 5.5 | -2.0 | -1.4 | 5.0 | -2.0 | -1.3 | 3.7 | -0.4 | -2.2 | 4.2 | 1.3 | 0.3 |
| harami_cross_bear | bear | 4.3 | 1.0 | 1.0 | 5.0 | -0.1 | 0.4 | 4.5 | 1.4 | 0.8 | 5.1 | -0.4 | -0.8 |
| piercing | bull | 7.5 | -2.0 | 1.1 | 7.5 | -1.7 | 1.7 | 2.8 | -1.1 | 1.8 | 3.1 | 1.3 | -0.5 |
| dark_cloud_cover | bear | 9.0 | -0.9 | -2.0 | 7.6 | 1.2 | -0.5 | 3.0 | -0.6 | 0.3 | 4.2 | -0.2 | 1.4 |
| tweezer_bottom | bull | 23.8 | -1.6 | -2.1 | 20.6 | -1.9 | -1.2 | 6.8 | -0.2 | -0.4 | 11.5 | 0.0 | -1.1 |
| tweezer_top | bear | 16.0 | -2.4 | 0.5 | 20.3 | -1.2 | 1.0 | 13.3 | -0.3 | 0.3 | 16.4 | -0.2 | 0.7 |
| kicker_bull | bull | 0.0 | n/a | n/a | 0.0 | n/a | n/a | 0.7 | -2.1 | -0.6 | 0.4 | 0.7 | 0.2 |
| kicker_bear | bear | 0.0 | n/a | n/a | 0.0 | n/a | n/a | 0.7 | -0.0 | 0.8 | 0.5 | 2.5 | 0.7 |
| counterattack_bull | bull | 0.0 | n/a | n/a | 0.0 | n/a | n/a | 0.1 | -0.2 | -2.7 | 0.1 | -0.7 | -0.4 |
| counterattack_bear | bear | 0.0 | n/a | n/a | 0.0 | n/a | n/a | 0.2 | 2.7 | 2.8 | 0.1 | 1.6 | 1.2 |
| homing_pigeon | bull | 1.7 | -2.0 | -1.6 | 1.3 | -0.3 | -0.6 | 6.1 | 0.6 | -0.4 | 5.1 | -0.2 | -0.1 |
| descending_hawk | bear | 1.4 | 0.7 | -2.8 | 1.4 | 0.5 | 0.0 | 6.7 | -1.0 | -0.0 | 5.9 | 0.5 | -0.1 |
| matching_low | bull | 1.7 | -2.0 | -1.6 | 1.3 | -0.4 | -0.6 | 1.3 | -0.8 | -0.6 | 1.7 | -0.4 | -1.1 |
| matching_high | bear | 1.4 | 0.7 | -2.8 | 1.4 | 0.6 | 0.0 | 2.0 | -0.2 | -0.1 | 2.1 | -0.4 | 0.2 |
| on_neck | bear | 0.0 | n/a | n/a | 0.0 | n/a | n/a | 0.8 | -0.3 | 1.6 | 0.7 | 0.1 | 0.2 |
| in_neck | bear | 0.0 | n/a | n/a | 0.0 | n/a | n/a | 0.4 | -0.8 | -0.0 | 0.3 | 0.3 | 0.6 |
| thrusting | bear | 0.0 | n/a | n/a | 0.0 | 13.9 | -2.2 | 2.9 | -1.1 | -0.3 | 2.3 | -0.7 | 1.2 |
| separating_lines_bull | bull | 0.1 | -5.5 | 3.7 | 0.3 | -2.4 | 0.3 | 0.6 | -2.1 | -1.1 | 0.6 | 0.8 | 0.1 |
| separating_lines_bear | bear | 0.4 | 4.2 | 1.0 | 0.4 | 1.0 | -0.3 | 0.3 | 1.2 | -1.6 | 0.4 | 0.5 | 0.5 |
| doji_star_bull | bull | 5.4 | -1.6 | -1.6 | 4.9 | -1.7 | -1.1 | 2.9 | 0.1 | 0.8 | 3.2 | 1.2 | -0.8 |
| doji_star_bear | bear | 4.4 | 1.2 | 0.3 | 5.0 | 1.1 | 1.0 | 5.7 | 2.3 | -0.1 | 4.7 | 1.4 | -0.2 |
| morning_star | bull | 2.6 | -1.5 | 0.3 | 2.4 | -1.6 | -2.6 | 1.8 | -1.1 | 0.2 | 1.8 | -0.0 | 0.8 |
| evening_star | bear | 2.5 | 1.3 | 0.1 | 2.5 | -0.4 | 0.5 | 2.4 | -0.9 | 0.9 | 2.3 | -0.6 | -0.5 |
| morning_doji_star | bull | 1.4 | -0.9 | -0.1 | 1.4 | -2.0 | -1.4 | 0.7 | -1.1 | 0.3 | 0.8 | -0.6 | 0.4 |
| evening_doji_star | bear | 1.3 | 1.4 | 0.1 | 1.5 | 1.5 | 0.2 | 1.1 | 0.3 | 1.9 | 1.0 | -1.3 | -0.3 |
| abandoned_baby_bull | bull | 0.0 | n/a | n/a | 0.0 | n/a | n/a | 0.0 | n/a | -0.8 | 0.0 | -1.5 | -3.5 |
| abandoned_baby_bear | bear | 0.0 | n/a | n/a | 0.0 | n/a | n/a | 0.1 | n/a | 4.1 | 0.0 | 0.8 | 1.7 |
| three_white_soldiers | bull | 0.1 | -24.6 | -3.1 | 0.1 | -2.2 | 1.4 | 0.2 | -1.4 | -0.6 | 0.2 | -2.0 | -0.4 |
| three_black_crows | bear | 0.0 | n/a | n/a | 0.1 | -2.2 | -3.2 | 0.2 | 0.5 | 1.0 | 0.1 | -1.2 | 2.1 |
| identical_three_crows | bear | 0.0 | n/a | n/a | 0.1 | -2.2 | -3.3 | 0.0 | n/a | n/a | 0.0 | 0.6 | -1.1 |
| three_inside_up | bull | 0.9 | -3.7 | 0.9 | 0.8 | 0.2 | -2.3 | 2.5 | -1.6 | -0.8 | 1.7 | -0.1 | -1.3 |
| three_inside_down | bear | 1.1 | -1.3 | -2.5 | 1.0 | -1.6 | -0.9 | 1.9 | -3.4 | 0.7 | 1.7 | -0.9 | -0.4 |
| three_outside_up | bull | 32.1 | -1.4 | -1.3 | 28.1 | -0.0 | -0.4 | 5.8 | -0.8 | -0.7 | 9.0 | -1.3 | -1.1 |
| three_outside_down | bear | 26.0 | -0.3 | 0.4 | 27.1 | 1.7 | -1.3 | 9.4 | 0.8 | -1.0 | 11.7 | -1.0 | -0.2 |
| upside_tasuki_gap | bull | 0.0 | n/a | n/a | 0.0 | n/a | n/a | 1.2 | -1.4 | -1.7 | 0.5 | -0.6 | -0.9 |
| downside_tasuki_gap | bear | 0.0 | n/a | n/a | 0.0 | n/a | n/a | 0.6 | -1.0 | 0.1 | 0.4 | -2.0 | -0.2 |
| stick_sandwich | bull | 0.0 | n/a | n/a | 0.0 | -2.2 | 3.3 | 0.5 | 0.6 | -2.0 | 0.6 | 0.2 | -0.8 |
| unique_three_river | bull | 0.0 | n/a | n/a | 0.0 | n/a | n/a | 0.0 | 1.4 | n/a | 0.1 | 0.8 | 0.5 |
| tri_star_bull | bull | 0.0 | n/a | n/a | 0.0 | 1.7 | n/a | 0.2 | -0.3 | -1.8 | 0.2 | 0.6 | 0.4 |
| tri_star_bear | bear | 0.0 | n/a | n/a | 0.0 | n/a | n/a | 0.3 | 3.4 | -1.3 | 0.3 | 0.1 | -0.2 |
| two_crows | bear | 0.0 | n/a | n/a | 0.0 | n/a | n/a | 0.3 | 1.3 | 0.7 | 0.3 | -1.4 | -0.3 |
| upside_gap_two_crows | bear | 0.0 | n/a | n/a | 0.0 | n/a | n/a | 0.3 | 3.4 | -0.8 | 0.1 | 0.8 | -0.4 |
| advance_block | bear | 3.7 | 1.1 | 0.5 | 3.5 | -1.4 | 1.2 | 0.7 | -0.7 | 2.1 | 1.2 | -1.1 | 0.8 |
| deliberation | bear | 1.1 | -0.1 | 1.7 | 1.2 | 0.5 | -0.6 | 0.4 | 2.2 | -0.1 | 0.5 | 0.3 | 0.2 |
| three_line_strike_bull | bull | 2.3 | 0.8 | 0.3 | 2.2 | -1.2 | 1.6 | 0.5 | 0.1 | 1.1 | 0.6 | 0.6 | 0.3 |
| three_line_strike_bear | bear | 2.6 | 0.6 | -1.1 | 2.0 | -1.0 | 2.6 | 0.2 | 0.1 | -1.9 | 0.4 | -0.6 | -1.3 |
| rising_three_methods | bull | 0.0 | n/a | n/a | 0.0 | -4.1 | 1.7 | 0.0 | n/a | n/a | 0.0 | -0.6 | -0.1 |
| falling_three_methods | bear | 0.1 | n/a | n/a | 0.0 | -6.1 | -0.4 | 0.0 | n/a | n/a | 0.0 | 3.7 | -0.3 |
| ladder_bottom | bull | 0.0 | n/a | n/a | 0.0 | n/a | n/a | 0.6 | -0.1 | 0.5 | 0.5 | -1.0 | -1.2 |
| bull_confluence | bull | 59.5 | -3.3 | -0.5 | 59.5 | 0.7 | -1.3 | 67.5 | -1.2 | -0.6 | 62.5 | -2.6 | -0.0 |
| bear_confluence | bear | 54.2 | 1.2 | -0.1 | 58.9 | 0.6 | -1.0 | 77.8 | -1.3 | 0.9 | 69.7 | -0.8 | 1.0 |
| bull_at_support | bull | 72.6 | -3.1 | -0.5 | 69.8 | -1.4 | -1.7 | 43.5 | -1.4 | 0.3 | 50.7 | 0.4 | 0.8 |
| bear_at_resistance | bear | 69.6 | -1.0 | -1.1 | 75.1 | 0.1 | 0.6 | 75.1 | 0.8 | -0.3 | 72.7 | 0.2 | 0.9 |
| bull_volume | bull | 61.2 | 1.3 | 1.1 | 57.0 | 2.2 | 0.7 | 29.5 | -0.5 | 0.0 | 31.6 | 2.0 | -1.8 |
| bear_volume | bear | 47.3 | -2.4 | -0.4 | 58.1 | -2.9 | -0.5 | 41.6 | 0.3 | -1.1 | 32.5 | -2.2 | -0.5 |

## B. Long-only rules

- CD picks: long_white h5 (IS t 1.46), bull_volume h5 (IS t 1.27), closing_marubozu_white h10 (IS t 0.49)
- C4 picks: closing_marubozu_white h10 (IS t 1.75), three_inside_up h3 (IS t 1.04), morning_star h5 (IS t -1.61)
- EF picks: homing_pigeon h1 (IS t 2.03), matching_low h1 (IS t 1.69), harami_bull h1 (IS t 1.30)
- SP picks: inverted_hammer h3 (IS t 2.19), doji_star_bull h10 (IS t 2.19), harami_cross_bull h5 (IS t 1.30)

| set | signal | h | OOS entries | IS Sharpe | OOS Sharpe | CAGR | max DD | random median | random 95 % | benchmark | late | double cost | twin | years | deflated p | gates failed | passes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| CD | long_white | 5 | 1,265 | 0.69 | -0.32 | -0.29 | 0.85 | -0.60 | -0.37 | 0.74 | -0.23 | -0.87 | -1.00 | 2024:0.96 2025:-1.62 2026:-0.26 | 0.00 | 1 Sharpe > 0, 3 above the benchmark, 4 late > 0, 5 double cost > 0, 6 twin > 0, 7 years, 8 deflated | no |
| CD | bull_volume | 5 | 822 | 1.00 | 0.29 | 0.03 | 0.69 | 0.23 | 0.48 | 0.74 | 0.20 | -0.17 | -0.40 | 2024:2.06 2025:-0.75 2026:-0.70 | 0.00 | 2 above random books, 3 above the benchmark, 5 double cost > 0, 6 twin > 0, 7 years, 8 deflated | no |
| CD | closing_marubozu_white | 10 | 236 | 1.01 | 0.35 | 0.06 | 0.49 | 0.08 | 0.39 | 0.74 | 0.20 | 0.16 | -0.28 | 2024:1.83 2025:-1.24 2026:0.10 | 0.00 | 2 above random books, 3 above the benchmark, 6 twin > 0, 8 deflated | no |
| C4 | closing_marubozu_white | 10 | 1,655 | 1.12 | -1.19 | -0.33 | 0.71 | -1.21 | -0.88 | 0.74 | -1.22 | -2.59 | -1.61 | 2024:0.09 2025:-0.90 2026:-3.51 | 0.00 | 1 Sharpe > 0, 2 above random books, 3 above the benchmark, 4 late > 0, 5 double cost > 0, 6 twin > 0, 7 years, 8 deflated | no |
| C4 | three_inside_up | 3 | 134 | 0.15 | -2.55 | -0.07 | 0.18 | -2.02 | -1.55 | 0.74 | -1.14 | -3.37 | -0.90 | 2024:-2.74 2025:-2.01 2026:-3.11 | 0.00 | 1 Sharpe > 0, 2 above random books, 3 above the benchmark, 4 late > 0, 5 double cost > 0, 6 twin > 0, 7 years, 8 deflated | no |
| C4 | morning_star | 5 | 428 | 0.05 | -1.06 | -0.11 | 0.33 | -0.82 | -0.57 | 0.74 | -0.85 | -2.00 | -1.82 | 2024:-1.30 2025:-1.63 2026:0.17 | 0.00 | 1 Sharpe > 0, 2 above random books, 3 above the benchmark, 4 late > 0, 5 double cost > 0, 6 twin > 0, 7 years, 8 deflated | no |
| EF | homing_pigeon | 1 | 395 | 0.21 | -0.33 | -0.01 | 0.07 | -0.12 | 0.17 | 0.87 | 0.19 | -0.51 | n/a | 4 of 11 | 0.00 | 1 Sharpe > 0, 2 above random books, 3 above the benchmark, 5 double cost > 0, 7 years, 8 deflated | no |
| EF | matching_low | 1 | 91 | 0.13 | -0.01 | -0.00 | 0.02 | 0.16 | 0.45 | 0.87 | 0.07 | -0.10 | n/a | 6 of 11 | 0.00 | 1 Sharpe > 0, 2 above random books, 3 above the benchmark, 5 double cost > 0, 7 years, 8 deflated | no |
| EF | harami_bull | 1 | 350 | 0.29 | -0.00 | -0.00 | 0.05 | 0.00 | 0.30 | 0.87 | 0.19 | -0.20 | n/a | 6 of 11 | 0.00 | 1 Sharpe > 0, 2 above random books, 3 above the benchmark, 5 double cost > 0, 7 years, 8 deflated | no |
| SP | inverted_hammer | 3 | 8,216 | 0.47 | 0.13 | 0.01 | 0.28 | 0.26 | 0.44 | 0.87 | 0.45 | -0.21 | n/a | 7 of 11 | 0.00 | 2 above random books, 3 above the benchmark, 5 double cost > 0, 8 deflated | no |
| SP | doji_star_bull | 10 | 3,044 | 0.35 | 0.20 | 0.02 | 0.42 | 0.37 | 0.54 | 0.87 | 0.29 | 0.11 | n/a | 7 of 11 | 0.00 | 2 above random books, 3 above the benchmark, 8 deflated | no |
| SP | harami_cross_bull | 5 | 4,617 | 0.32 | 0.27 | 0.03 | 0.30 | 0.27 | 0.46 | 0.87 | 0.07 | 0.08 | n/a | 8 of 11 | 0.00 | 2 above random books, 3 above the benchmark, 8 deflated | no |

Gates: 1 Sharpe > 0, 2 above the 95th percentile of 200 random books (same entries per bar, random eligible instruments), 3 above the benchmark (BTC or SPY bought and held, same days), 4 one bar late > 0, 5 double costs > 0, 6 twin > 0 (crypto), 7 positive years (2 of 3 crypto, 7 of 11 equities), 8 deflated p > 0.95 over the pool. Sharpe annualised over 365 days for crypto, 252 for equities.

Random entry on the same bars for the picks (2,000 draws):

| set | signal | h | window | events | mean bps | random mean bps | random 95 % | p |
|---|---|---|---|---|---|---|---|---|
| CD | long_white | 5 | oos | 3,092 | 93.4 | 46.5 | 74.8 | 0.0 |
| CD | long_white | 5 | is | 3,120 | 236.5 | 175.8 | 214.9 | 0.0 |
| CD | bull_volume | 5 | oos | 1,669 | 246.0 | 184.0 | 226.9 | 0.0 |
| CD | bull_volume | 5 | is | 1,699 | 262.2 | 183.1 | 236.3 | 0.0 |
| CD | closing_marubozu_white | 10 | oos | 273 | 205.3 | 84.5 | 237.6 | 0.1 |
| CD | closing_marubozu_white | 10 | is | 327 | 462.7 | 439.5 | 635.7 | 0.4 |
| C4 | closing_marubozu_white | 10 | oos | 1,969 | 16.3 | 15.5 | 32.5 | 0.5 |
| C4 | closing_marubozu_white | 10 | is | 1,851 | 167.9 | 126.9 | 160.1 | 0.0 |
| C4 | three_inside_up | 3 | oos | 134 | -76.0 | -42.5 | -15.7 | 1.0 |
| C4 | three_inside_up | 3 | is | 122 | 98.1 | 71.6 | 110.9 | 0.1 |
| C4 | morning_star | 5 | oos | 450 | 8.6 | 26.2 | 44.8 | 0.9 |
| C4 | morning_star | 5 | is | 347 | 104.8 | 123.1 | 152.7 | 0.9 |
| EF | homing_pigeon | 1 | oos | 408 | -3.9 | 1.2 | 7.1 | 0.9 |
| EF | homing_pigeon | 1 | is | 532 | 13.3 | 3.2 | 10.0 | 0.0 |
| EF | matching_low | 1 | oos | 91 | 3.7 | 10.3 | 22.8 | 0.8 |
| EF | matching_low | 1 | is | 118 | 12.2 | -2.8 | 10.3 | 0.0 |
| EF | harami_bull | 1 | oos | 357 | 4.3 | 4.6 | 10.4 | 0.5 |
| EF | harami_bull | 1 | is | 587 | 14.7 | 6.0 | 12.1 | 0.0 |
| SP | inverted_hammer | 3 | oos | 10,913 | 17.7 | 20.1 | 25.0 | 0.8 |
| SP | inverted_hammer | 3 | is | 15,289 | 35.8 | 28.1 | 33.0 | 0.0 |
| SP | doji_star_bull | 10 | oos | 4,309 | 35.7 | 46.6 | 61.0 | 0.9 |
| SP | doji_star_bull | 10 | is | 5,939 | 54.8 | 42.0 | 56.8 | 0.1 |
| SP | harami_cross_bull | 5 | oos | 5,693 | 31.3 | 29.6 | 38.1 | 0.4 |
| SP | harami_cross_bull | 5 | is | 7,841 | 43.2 | 36.8 | 45.8 | 0.1 |

## C. Candle features in M2

Group C (c_net, c_net5, c_sr, c_vol, c_body, c_upper, c_lower, c_pick_long_white, c_pick_bull_volume, c_pick_closing_marubozu_white) joined to X11's M2 panel (581,663 coin-days, 99.0 % with a candle). v2 + C against v2, mean daily rank IC on the 7-day label from 2024-01-01:

| test | days | IC v2 + C | IC v2 | difference | NW t | difference by year (x1000) | years better | passes |
|---|---|---|---|---|---|---|---|---|
| H1 whole universe | 1,016 | 0.1482 | 0.1458 | 0.0023 | 1.4777 | 2024:-0.0 2025:+5.7 2026:+1.1 | 2 | no |
| H2 Alpaca | 1,016 | 0.1269 | 0.1220 | 0.0048 | 1.5767 | 2024:+4.3 2025:+5.5 2026:+4.5 | 3 | no |

Each input alone (within-day rank against the 7-day return):

| feature | IC before 2024 | IC from 2024 | NW t |
|---|---|---|---|
| c_net | -0.0169 | -0.0138 | -4.2676 |
| c_net5 | -0.0211 | -0.0090 | -1.6338 |
| c_sr | -0.0017 | 0.0024 | 0.7042 |
| c_vol | -0.0307 | -0.0223 | -7.9366 |
| c_body | -0.0232 | -0.0237 | -6.2387 |
| c_upper | -0.0412 | -0.0287 | -7.9126 |
| c_lower | 0.0047 | 0.0085 | 2.0594 |
| c_pick_long_white | -0.0517 | -0.0417 | -11.6255 |
| c_pick_bull_volume | -0.0611 | -0.0488 | -13.5997 |
| c_pick_closing_marubozu_white | -0.0034 | -0.0039 | -1.0329 |

Gain share in one fit on all labelled days (top 12): vol7 23.0 %, vol28 10.0 %, age 9.1 %, adv28 8.8 %, fund7 5.2 %, c_pick_closing_marubozu_white 4.4 %, r56 3.9 %, perp_share 3.6 %, dist_lo28 3.4 %, r28 2.7 %, dist_hi28 2.5 %, r7 2.4 %.

## D. Candle filters on breakout_top10's entries

| variant | IS 35 bps | OOS 35 bps | OOS 70 bps | max DD | CAGR | turnover / yr | 2024 | 2025 | 2026 | deflated p of the difference |
|---|---|---|---|---|---|---|---|---|---|---|
| breakout_top10 live alone | 1.45 | 1.17 | 1.04 | 0.16 | 0.18 | 5.71 | 2.19 | 0.32 | -0.02 | n/a |
| breakout_top10 twin alone | 1.35 | 1.06 | 0.90 | 0.22 | 0.22 | 9.28 | 1.84 | 0.46 | 0.38 | n/a |
| F1 no bearish pattern | 1.45 | 1.21 | 1.08 | 0.16 | 0.19 | 5.64 | 2.29 | 0.32 | -0.02 | 0.57 |
| F2 net at least 1 | 1.38 | 1.07 | 0.95 | 0.16 | 0.16 | 5.30 | 2.18 | 0.23 | -0.35 | 0.00 |
| F3 close in the top third | 1.42 | 1.18 | 1.05 | 0.16 | 0.18 | 5.52 | 2.18 | 0.32 | 0.04 | 0.02 |
| F1 no bearish pattern · one day late | 1.33 | 0.97 | 0.84 | 0.17 | 0.15 | 5.62 | 2.19 | -0.21 | -0.46 | 0.00 |
| F1 no bearish pattern · twin | 1.35 | 1.09 | 0.94 | 0.22 | 0.22 | 9.21 | 1.92 | 0.45 | 0.38 | 0.51 |

Pick (best in-sample Sharpe): **F1 no bearish pattern**. Bootstrap 90 % band of the Sharpe difference against the book: -0.00 to 0.11; better in 1 of 3 years. Gates failed: 1 Sharpe and years, 2 drawdown, 3 band above 0, 4 one day late, 6 deflated improvement. **Fails.**

## The pool

948 hand trials before this study, 600 in the factory ledger, 42 in part B and 5 in part D: **1,595**. Part B is deflated over its pool of 1,590 (noise bar 2.71); part D's improvement over its own 5 trials as registered. The next study starts from 995 hand trials.

Trials counted in part B: CD long_white h5 base; CD long_white h5 late; CD long_white h5 double cost; CD long_white h5 twin; CD bull_volume h5 base; CD bull_volume h5 late; CD bull_volume h5 double cost; CD bull_volume h5 twin; CD closing_marubozu_white h10 base; CD closing_marubozu_white h10 late; CD closing_marubozu_white h10 double cost; CD closing_marubozu_white h10 twin; C4 closing_marubozu_white h10 base; C4 closing_marubozu_white h10 late; C4 closing_marubozu_white h10 double cost; C4 closing_marubozu_white h10 twin; C4 three_inside_up h3 base; C4 three_inside_up h3 late; C4 three_inside_up h3 double cost; C4 three_inside_up h3 twin; C4 morning_star h5 base; C4 morning_star h5 late; C4 morning_star h5 double cost; C4 morning_star h5 twin; EF homing_pigeon h1 base; EF homing_pigeon h1 late; EF homing_pigeon h1 double cost; EF matching_low h1 base; EF matching_low h1 late; EF matching_low h1 double cost; EF harami_bull h1 base; EF harami_bull h1 late; EF harami_bull h1 double cost; SP inverted_hammer h3 base; SP inverted_hammer h3 late; SP inverted_hammer h3 double cost; SP doji_star_bull h10 base; SP doji_star_bull h10 late; SP doji_star_bull h10 double cost; SP harami_cross_bull h5 base; SP harami_cross_bull h5 late; SP harami_cross_bull h5 double cost.
