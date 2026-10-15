# flow_overlays (X6)

`python -m lab.experiments.flow_overlays`

Flow and positioning signals as exposure overlays on the daily books.
Pre-registered here before the study code existed and before any of the new
data was downloaded; nothing below the generated marker was known when this
was written.

## Question

Can public flow and positioning data (US and Korean exchange premiums,
stablecoin supply, perpetual funding, basis, open interest, account
long/short ratios, a liquidation proxy, option implied volatility) tell the
daily books when to hold less? Each signal only scales a book's exposure to
100, 50 or 0 % of what the book wants; nothing new is traded. The aim is
lower drawdowns and fewer bad weeks without giving up Sharpe, at Alpaca
costs, judged out of sample.

## What the lab already knows

- The sweep (`family_funding.md`) timed BTC+ETH and a top-20 book by their
  own funding z-score as stand-alone strategies (fails, 0.08 and 0.64 at 15
  bps) and traded open interest with price (0.69 at 15 bps, 0.13 at 41,
  fails). "Trend plus carry" removed crowded-funding coins from tsmom (0.71,
  fails). None of these used market-wide funding, basis, OI, long/short
  ratios or liquidations as a switch on the books that run.
- `regime` (M5) and `regime_hmm` (M7): price, breadth and funding features
  do not forecast BTC drawdowns out of sample (AUC under 0.5); the BTC
  200-day rule stays. `vol_managed` (C11): vol-scaling overlays hurt both
  books (1.05 vs 1.11, 0.27 vs 0.52). The bar for an overlay is the book alone.
- Not tried anywhere in the repo: the Coinbase premium, the Korean premium,
  stablecoin supply, Deribit implied volatility, account long/short ratios,
  liquidation proxies, ETF flows.

## Books

The three daily paper books as the autopilot runs them on Alpaca: every coin
Alpaca does not list held as cash (C16's group C; `alpaca_universe.originals`
then `cash_left`):

- `breakout_top10` (Donchian 20/10, top 10 liquid, no regime)
- `tsmom_top20` (28-day momentum, 40 % coin vol, BTC 200-day regime, daily)
- `tsmom_tranches` (the same targets in seven weekly tranches)

The **twin** of each is the original book on the survivorship-free panel
(the top coins by liquidity each day, delisted ones included, nothing left
in cash), since the cash-left book uses today's Alpaca list.

## Data (all keyless; daily values known at the 00:00 UTC close of day d)

| key | source | raw daily value x_d | history |
|---|---|---|---|
| `cb_prem` | Coinbase Exchange public candles, BTC-USD 1h; Binance BTCUSDT 1h (lake) | mean over the 24 hours of day d of Coinbase close / Binance close - 1, then the 7-day mean | 2020-01 |
| `kr_prem` | Upbit public candles, KRW-BTC 1d (the Upbit day is 00:00 to 24:00 UTC); USD/KRW ECB reference rate via frankfurter.dev, last rate on or before d; Binance BTCUSDT daily close | Upbit close / (Binance close x USDKRW) - 1, 7-day mean | 2020-01 |
| `stable_30` | DefiLlama stablecoins API, USDT (id 1) + USDC (id 2) circulating USD | 30-day log change; DefiLlama's value stamped D is used from the close of D+1 (one extra day, its stamp time is not documented) | 2019 |
| `stable_7` | as above | 7-day log change (the pace of mints and burns) | 2019 |
| `funding` | Binance USD-M funding history (lake, `perp_daily`) | funding summed over day d, mean over the 20 most liquid perps that day weighted by perp quote volume; 7-day mean | 2020-01 |
| `basis` | Binance USD-M 1d klines and the spot panel, the 20 lab coins | perp close / spot close - 1, weighted by perp quote volume; 7-day mean | 2020-01 |
| `oi_7` | Binance USD-M metrics archives (lake), the 20 lab coins | 7-day log change of open interest in coins (not USD, so price moves do not count), weighted by OI value at d-7 | 2022-01 |
| `ls_ratio` | as above | daily mean of the all-accounts long/short ratio, weighted by OI value; 7-day mean | 2022-01-19 |
| `liq` | as above | long-liquidation proxy: per coin, the share of open interest lost on a day its price fell (max(0, -dlog OI in coins) if the day's return < 0), weighted by the previous day's OI value; summed over 7 days | 2022-01 |
| `dvol` | Deribit public API, BTC DVOL index, daily close | the level | 2021-03-24 |

Each signal becomes z_d = (x_d - mean) / std over the 365 days up to and
including d (at least 180 values), so every value is known at the close of d.

**US spot BTC ETF flows: skipped.** The keyless source in common use (Farside
Investors) answers scripted requests with 403 behind Cloudflare; the
alternatives need an API key. ETF flows also start in 2024-01, so they have
no in-sample window.

**25-delta skew: not backtested.** Deribit serves no skew history without a
key; the collector records it daily from now on (from the option book
summary, delta from the mark IV), so it can be studied later.

## The overlay

For a signal with orientation o (+1: risk-off when the signal is high, -1:
risk-off when it is low) and thresholds (a, b), the scale decided at the
close of d is

    s_d = 1    if o z_d < a
          0.5  if a <= o z_d < b
          0    if o z_d >= b

and 1 while the signal does not exist yet. The book is run unchanged; the
overlay holds s_d times its weights: the return of day d+1 is s_d times the
book's, turnover is s_d times the book's plus |s_d - s_{d-1}| times the book's
exposure (as `vol_managed` did). Thresholds (a, b): (1, 2) and (0.5, 1.5).

Prior expectation of the sign (written down, but both signs are run and
counted, since several of these are argued both ways): low Coinbase premium
risk-off; high Korean premium risk-off (retail froth); low stablecoin growth
risk-off; high funding, basis, OI growth and long/short ratio risk-off
(crowded longs); high liquidations risk-on (capitulation); high DVOL
risk-off.

**Single-signal trials: 120** = 10 signals x 2 orientations x 2 threshold
pairs x 3 books. Pick per signal and book: the best in-sample Sharpe at
35 bps (30 picks). In sample is 2020-08-01 to 2023-12-31 restricted to the
days the signal exists (OI, long/short and liquidations from 2022-07, DVOL
from 2021-09); out of sample from 2024-01-01 to the panel's end.

## The combination

L2-regularised logistic regression on the ten z-scores (as signed inputs;
the fit chooses the signs) for the probability of a bad week: the
equal-weight basket of eligible Alpaca coins (rebalanced daily) losing more
than 5 % over days d+1 to d+7. One model for all three books. Walk-forward:
refit at the start of each quarter on every labelled day whose label window
ended before the refit (expanding, 7-day purge), first prediction in the
first quarter with at least 365 training rows. Scale: 1 while the predicted
probability is below the 70th percentile of the model's fitted probabilities
on its training rows, 0.5 up to the 90th, 0 above.

Feature sets: `long` (cb_prem, kr_prem, stable_30, stable_7, funding, basis,
dvol; from 2021-09) and `all` (plus oi_7, ls_ratio, liq; from 2022-07, so
its first predictions are only months before 2024). C (inverse penalty on
standardised inputs) 0.1 and 1.

**Primary combination, fixed now: `long`, C = 0.1.** The other three are
counted and reported, nothing is picked among them.

**Combination trials: 12** = 2 feature sets x 2 C x 3 books.

## Robustness runs (counted)

- Every single-signal pick and the primary combination one day late (s_d
  applied a day later): 33.
- The same on the twin book: 33.

**Counted here: 198 trials.** The pool before this study: 377 hand trials
to C16 (bar 2.43), the 111 counted in parallel (listings 16, memecoins 50,
equities 45), fast_maker 53, intraday_equities 46, alpaca36 21, and the
factory's ledger (300 in the committed seed, more if the server's ledger is
present): about **908**, with this study about 1,106. Variance as
`fast_maker.pool`: the hand trials at the variance backed out of the
published bar, the factory at the variance of its ledger, this study at its
own (annual Sharpes clipped at +-3).

## Costs

35 bps per unit of one-way turnover (Alpaca taker plus slippage) is the
base; 15 bps (maker) and 70 bps (stress) reported. Decided at a close, filled
at that close.

## Pass rule (every one must hold for a pick, else it is written up as negative)

On the cash-left book, out of sample from 2024, at 35 bps:

1. Sharpe higher than the book alone, and higher in at least 2 of the 3
   out-of-sample years (2024, 2025, 2026 partial);
2. maximum drawdown lower than the book alone;
3. the stationary-bootstrap (20-day blocks, 4000 draws) 90 % band of the
   Sharpe difference (overlay minus book) above 0;
4. one day late: Sharpe still higher than the book alone;
5. on the twin: Sharpe not below the twin book alone;
6. the improvement deflated: the daily return difference (overlay minus
   book) has a deflated p above 0.95 over this study's 198 trials (variance
   of the trials' difference Sharpes).

The overlay's own Sharpe is also deflated over the whole pool and reported;
the books themselves do not clear that bar (about 2.7), so it is not a gate
for an overlay.

**If something passes:** a proposal (not a deployment) of the overlay as a
lab signal field the engine could read, with its exact rule. **If nothing
passes:** the result is the record, and the collector keeps the data coming.

## Reported

For every trial: Sharpe at 15 / 35 / 70 bps in and out of sample, CAGR,
drawdown, average exposure, turnover a year, share of days at 0.5 and 0,
per-year Sharpe; for picks the Sharpe difference, its bootstrap band, years
better, drawdown against the book, late and twin results and both deflated
p values. For the combination: out-of-sample AUC and Brier against the base
rate, and the coefficients of the last fit. Each signal's out-of-sample
rank correlation with the next 7 days of the basket, for reading only.

## Data going forward

`lab.collect.flow` (job `flow-collect` in `research/ops/jobs.yaml`, daily)
writes the new sources to `<data>/flow/`: Coinbase BTC-USD 1h, Upbit
KRW-BTC 1d, USD/KRW, DefiLlama USDT and USDC supply, Deribit BTC and ETH
DVOL, and a daily Deribit option snapshot for 25-delta skew. Funding, OI and
long/short ratios already arrive with the nightly backfill.

## Findings (written after the run, 2026-10-15)

**Nothing passes; no overlay is proposed and nothing changes in the engine.**
All 33 judged picks fail at least one gate; the closest two fail only the
deflated improvement.

- **Data.** Every keyless source answered: Coinbase 68,237 hours and Upbit
  2,844 days from 2019-01, USD/KRW from the ECB, DefiLlama supply from 2017,
  DVOL from 2021-03-24 (all in `<data>/flow/`, written by the collector's
  first run, about 4 minutes). ETF flows skipped as registered (Farside
  answers 403). Panel to 2026-10-11, out of sample 1,015 days. The books
  alone from 2024 at 35 bps: breakout_top10 1.17 (drawdown 16 %),
  tsmom_top20 0.64 (9 %), tsmom_tranches 0.73 (9 %), the same as alpaca36.
- **Overlays mostly cost Sharpe.** Of the 120 single-signal trials, 28 beat
  their book out of sample (breakout 11 of 40, tsmom_top20 10, tranches 7);
  with the sign written down in advance, 24 of 60. 75 of 120 lower the
  drawdown, but there is little to cut: the books hold cash most of the time
  (average exposure 15, 9 and 9 %) and their drawdowns are already small.
  The in-sample choice carries little: the in-sample improvement and the
  out-of-sample difference correlate at 0.22 across the 120.
- **Closest: the retail long/short ratio.** Cutting exposure when the
  all-accounts long/short ratio on Binance perps is high (z above 1 to half,
  above 2 to zero) makes breakout_top10 1.39 against 1.17 and tsmom_top20
  0.78 against 0.64; gates 1 to 5 hold for both (better in 2024 and 2025,
  bootstrap band of the Sharpe difference 0.03 to 0.40 and 0.01 to 0.27, one
  day late 1.26 and 0.74, twin 1.28 against 1.07 and 0.48 against 0.32), but
  the improvement's deflated p is 0.03 over this study's 198 trials, so it
  fails gate 6. Its in-sample window is only 2022-07 to 2023-12, it trims
  exposure on about a fifth of the days, and the opposite sign loses on every
  book (0.98, 0.48, 0.54), which is what a real effect would look like and
  also what a lucky one would. On tranches its pick (z 0.5/1.5) makes 0.80
  against 0.73 with a band from -0.08.
- **Basis, the other near miss, points the "wrong" way.** Cutting exposure
  when the perp basis of the 20 lab coins is LOW (backwardation, stress)
  makes breakout_top10 1.33 (better in all three years, late 1.22, twin 1.24
  against 1.07) but the band reaches -0.01 and the deflated p is 0.03. It
  behaves like one more trend filter, not like the crowded-long brake it was
  registered as; the crowded-long sign (cut when basis is high) loses.
- **Premiums, stablecoin supply, funding, OI growth, liquidations, DVOL: no.**
  Their picks lose 0.01 to 0.3 Sharpe against the books, mostly by sitting
  out rebounds; 7-day stablecoin growth is about neutral (1.18, 0.69, 0.77
  against 1.17, 0.64, 0.73, bands from -0.08). The in-sample hints (DVOL's
  7-day rank correlation with the Alpaca basket 0.23, basis and funding 0.15
  to 0.16) are 0.04, 0.06 and -0.04 out of sample.
- **Market funding as registered is contaminated from 2025.** Weighted by
  volume over the 20 most liquid perps, it is pulled by newly listed perps
  with extreme negative funding (on 2025-07-01 HFT paid -1.4 % a day and MYX
  -2.8 %), so from 2025 its z-score measures squeezes in new listings, not
  crowded longs. The basis on the 20 lab coins is the clean version of the
  same idea and is reported above. The registered definition was kept.
- **The combination cannot see bad weeks.** Out-of-sample AUC 0.48 for all
  four logistic models, Brier 0.20 against 0.19 for the base rate (bad weeks
  26 % of days), the same answer as M5 and M7. As an overlay the primary
  model nearly erases the books (0.03 against 1.17, 0.11 against 0.64, 0.10
  against 0.73). The `all` set showed 3.3 to 4.4 on its three in-sample
  months and 0.25 to 0.46 out of sample, which is why it was not allowed to
  be the primary.
- **Deflation.** Pool 1,106 trials (608 hand, 300 factory, 198 here), the
  best noise trial at an annual Sharpe of about 2.40; every overlay's
  deflated p over the pool is 0.00, as for the books themselves.

**What it leaves.** The collector keeps the flow data and the 25-delta skew
(which has no history at all) arriving daily. The long/short ratio rule is
the only one worth a second look, and the honest way is a confirmatory test
on data that does not exist yet: the same rule (ls_ratio, risk-off when high,
z 1/2, on breakout_top10 and tsmom_top20, two trials, no re-picking) judged
only on days after 2026-10-11, once there are 12 months of them.

**Where it ran.** On the PC, from the synced lake (panel, perp caches, spot
1h, USD-M 1d and metrics) and a local first run of the collector
(`PYTHIA_FLOW` pointed outside the mirror). On the server the collector's
first run is the backfill, then the study reads the same files:

```bash
docker run --rm --cpus 1 --memory 1g -v /srv/pythia-data:/data -v /opt/pythia-lab:/app pythia-lab python -m lab.collect.flow
docker run --rm --cpus 4 --memory 8g -v /srv/pythia-data:/data -v /opt/pythia-lab:/app -e PYTHIA_AGENT_OUT=/data/lab-cache pythia-lab python -m lab.experiments.flow_overlays
```

<!-- generated below by lab.experiments.flow_overlays; edit above this line only -->

## Results (generated 2026-10-15, panel to 2026-10-11)

**Verdict: nothing passes** (33 picks judged: 30 single-signal picks and the primary combination on each book). Pool 1106 trials (608 hand, 300 factory, 198 here); the best noise trial is expected at an annual Sharpe of about 2.40. Out of sample 1015 days.

### Gates failed per pick

- cb_prem · + · z 1.0/2.0 · breakout: 1 Sharpe and years, 3 band above 0, 4 one day late, 5 twin, 6 deflated improvement
- cb_prem · + · z 1.0/2.0 · tsmom_daily: 1 Sharpe and years, 3 band above 0, 4 one day late, 5 twin, 6 deflated improvement
- cb_prem · + · z 1.0/2.0 · tsmom_tranches: 1 Sharpe and years, 2 drawdown, 3 band above 0, 4 one day late, 5 twin, 6 deflated improvement
- kr_prem · - · z 1.0/2.0 · breakout: 1 Sharpe and years, 3 band above 0, 4 one day late, 5 twin, 6 deflated improvement
- kr_prem · - · z 1.0/2.0 · tsmom_daily: 1 Sharpe and years, 3 band above 0, 4 one day late, 5 twin, 6 deflated improvement
- kr_prem · - · z 1.0/2.0 · tsmom_tranches: 1 Sharpe and years, 3 band above 0, 4 one day late, 5 twin, 6 deflated improvement
- stable_30 · - · z 0.5/1.5 · breakout: 1 Sharpe and years, 3 band above 0, 4 one day late, 6 deflated improvement
- stable_30 · - · z 0.5/1.5 · tsmom_daily: 1 Sharpe and years, 3 band above 0, 4 one day late, 6 deflated improvement
- stable_30 · - · z 0.5/1.5 · tsmom_tranches: 1 Sharpe and years, 2 drawdown, 3 band above 0, 4 one day late, 6 deflated improvement
- stable_7 · - · z 1.0/2.0 · breakout: 3 band above 0, 4 one day late, 6 deflated improvement
- stable_7 · - · z 1.0/2.0 · tsmom_daily: 3 band above 0, 4 one day late, 6 deflated improvement
- stable_7 · - · z 1.0/2.0 · tsmom_tranches: 3 band above 0, 4 one day late, 6 deflated improvement
- funding · - · z 1.0/2.0 · breakout: 1 Sharpe and years, 2 drawdown, 3 band above 0, 4 one day late, 5 twin, 6 deflated improvement
- funding · - · z 1.0/2.0 · tsmom_daily: 1 Sharpe and years, 2 drawdown, 3 band above 0, 4 one day late, 5 twin, 6 deflated improvement
- funding · - · z 1.0/2.0 · tsmom_tranches: 1 Sharpe and years, 2 drawdown, 3 band above 0, 4 one day late, 5 twin, 6 deflated improvement
- basis · - · z 0.5/1.5 · breakout: 3 band above 0, 6 deflated improvement
- basis · - · z 0.5/1.5 · tsmom_daily: 1 Sharpe and years, 3 band above 0, 6 deflated improvement
- basis · + · z 1.0/2.0 · tsmom_tranches: 1 Sharpe and years, 3 band above 0, 4 one day late, 5 twin, 6 deflated improvement
- oi_7 · - · z 0.5/1.5 · breakout: 1 Sharpe and years, 2 drawdown, 3 band above 0, 4 one day late, 5 twin, 6 deflated improvement
- oi_7 · + · z 1.0/2.0 · tsmom_daily: 1 Sharpe and years, 3 band above 0, 4 one day late, 5 twin, 6 deflated improvement
- oi_7 · + · z 1.0/2.0 · tsmom_tranches: 1 Sharpe and years, 3 band above 0, 4 one day late, 5 twin, 6 deflated improvement
- ls_ratio · + · z 1.0/2.0 · breakout: 6 deflated improvement
- ls_ratio · + · z 1.0/2.0 · tsmom_daily: 6 deflated improvement
- ls_ratio · + · z 0.5/1.5 · tsmom_tranches: 3 band above 0, 6 deflated improvement
- liq · + · z 0.5/1.5 · breakout: 1 Sharpe and years, 3 band above 0, 4 one day late, 5 twin, 6 deflated improvement
- liq · - · z 1.0/2.0 · tsmom_daily: 1 Sharpe and years, 3 band above 0, 4 one day late, 5 twin, 6 deflated improvement
- liq · - · z 1.0/2.0 · tsmom_tranches: 1 Sharpe and years, 3 band above 0, 4 one day late, 5 twin, 6 deflated improvement
- dvol · - · z 0.5/1.5 · breakout: 1 Sharpe and years, 3 band above 0, 4 one day late, 5 twin, 6 deflated improvement
- dvol · - · z 1.0/2.0 · tsmom_daily: 1 Sharpe and years, 2 drawdown, 3 band above 0, 4 one day late, 5 twin, 6 deflated improvement
- dvol · - · z 0.5/1.5 · tsmom_tranches: 1 Sharpe and years, 2 drawdown, 3 band above 0, 4 one day late, 5 twin, 6 deflated improvement
- logit long C 0.1 · breakout: 1 Sharpe and years, 2 drawdown, 3 band above 0, 4 one day late, 5 twin, 6 deflated improvement
- logit long C 0.1 · tsmom_daily: 1 Sharpe and years, 2 drawdown, 3 band above 0, 4 one day late, 5 twin, 6 deflated improvement
- logit long C 0.1 · tsmom_tranches: 1 Sharpe and years, 2 drawdown, 3 band above 0, 4 one day late, 5 twin, 6 deflated improvement

### The picks against the book alone (out of sample, 35 bps)

`book_*` is the cash-left book alone over the same days; `diff_sr` the annual Sharpe of the daily difference; `diff_p05`/`diff_p95` the bootstrap band of the Sharpe difference; `twin_*` the overlay and the book on the survivorship-free original; `zero_days`/`half_days` the share of out-of-sample days at 0 and 0.5.

| pick | is_35 | book_is_35 | oos_35 | book_oos_35 | dd | book_dd | years_better | diff_sr | diff_p05 | diff_p95 | late_35 | twin_35 | twin_book_35 | zero_days | half_days | deflated_p_diff | passes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| cb_prem · + · z 1.0/2.0 · breakout | 1.49 | 1.45 | 0.96 | 1.17 | 0.15 | 0.16 | 1 | -1.00 | -0.51 | 0.12 | 0.90 | 0.91 | 1.07 | 0.00 | 0.07 | 0.00 | no |
| cb_prem · + · z 1.0/2.0 · tsmom_daily | 1.70 | 1.68 | 0.53 | 0.64 | 0.08 | 0.09 | 1 | -0.68 | -0.38 | 0.11 | 0.54 | 0.26 | 0.32 | 0.00 | 0.07 | 0.00 | no |
| cb_prem · + · z 1.0/2.0 · tsmom_tranches | 1.90 | 1.85 | 0.51 | 0.73 | 0.09 | 0.09 | 0 | -1.09 | -0.53 | 0.03 | 0.63 | 0.35 | 0.47 | 0.00 | 0.07 | 0.00 | no |
| kr_prem · - · z 1.0/2.0 · breakout | 1.26 | 1.45 | 1.04 | 1.17 | 0.12 | 0.16 | 1 | -0.94 | -0.39 | 0.21 | 0.98 | 1.00 | 1.07 | 0.00 | 0.19 | 0.00 | no |
| kr_prem · - · z 1.0/2.0 · tsmom_daily | 1.53 | 1.68 | 0.51 | 0.64 | 0.08 | 0.09 | 0 | -0.68 | -0.44 | 0.14 | 0.57 | 0.24 | 0.32 | 0.00 | 0.19 | 0.00 | no |
| kr_prem · - · z 1.0/2.0 · tsmom_tranches | 1.71 | 1.85 | 0.59 | 0.73 | 0.08 | 0.09 | 0 | -0.75 | -0.43 | 0.13 | 0.65 | 0.40 | 0.47 | 0.00 | 0.19 | 0.00 | no |
| stable_30 · - · z 0.5/1.5 · breakout | 1.39 | 1.45 | 1.10 | 1.17 | 0.14 | 0.16 | 1 | -0.56 | -0.33 | 0.14 | 1.04 | 1.08 | 1.07 | 0.11 | 0.27 | 0.00 | no |
| stable_30 · - · z 0.5/1.5 · tsmom_daily | 1.75 | 1.68 | 0.58 | 0.64 | 0.09 | 0.09 | 2 | -0.47 | -0.25 | 0.11 | 0.53 | 0.37 | 0.32 | 0.11 | 0.27 | 0.00 | no |
| stable_30 · - · z 0.5/1.5 · tsmom_tranches | 1.84 | 1.85 | 0.72 | 0.73 | 0.09 | 0.09 | 2 | -0.16 | -0.12 | 0.11 | 0.68 | 0.56 | 0.47 | 0.11 | 0.27 | 0.00 | no |
| stable_7 · - · z 1.0/2.0 · breakout | 1.41 | 1.45 | 1.18 | 1.17 | 0.15 | 0.16 | 2 | -0.08 | -0.08 | 0.09 | 1.13 | 1.08 | 1.07 | 0.01 | 0.16 | 0.00 | no |
| stable_7 · - · z 1.0/2.0 · tsmom_daily | 1.69 | 1.68 | 0.69 | 0.64 | 0.08 | 0.09 | 2 | 0.52 | -0.04 | 0.15 | 0.60 | 0.40 | 0.32 | 0.01 | 0.16 | 0.02 | no |
| stable_7 · - · z 1.0/2.0 · tsmom_tranches | 1.84 | 1.85 | 0.77 | 0.73 | 0.08 | 0.09 | 2 | 0.39 | -0.06 | 0.15 | 0.68 | 0.52 | 0.47 | 0.01 | 0.16 | 0.01 | no |
| funding · - · z 1.0/2.0 · breakout | 1.53 | 1.45 | 1.05 | 1.17 | 0.17 | 0.16 | 2 | -0.88 | -0.42 | 0.09 | 1.03 | 0.95 | 1.07 | 0.05 | 0.11 | 0.00 | no |
| funding · - · z 1.0/2.0 · tsmom_daily | 1.65 | 1.68 | 0.57 | 0.64 | 0.11 | 0.09 | 2 | -0.41 | -0.50 | 0.25 | 0.53 | 0.22 | 0.32 | 0.05 | 0.11 | 0.00 | no |
| funding · - · z 1.0/2.0 · tsmom_tranches | 1.83 | 1.85 | 0.56 | 0.73 | 0.12 | 0.09 | 2 | -0.79 | -0.62 | 0.18 | 0.51 | 0.29 | 0.47 | 0.05 | 0.11 | 0.00 | no |
| basis · - · z 0.5/1.5 · breakout | 1.49 | 1.45 | 1.33 | 1.17 | 0.15 | 0.16 | 3 | 0.61 | -0.01 | 0.34 | 1.22 | 1.24 | 1.07 | 0.00 | 0.44 | 0.03 | no |
| basis · - · z 0.5/1.5 · tsmom_daily | 1.61 | 1.68 | 0.79 | 0.64 | 0.06 | 0.09 | 1 | 0.32 | -0.09 | 0.39 | 0.69 | 0.56 | 0.32 | 0.00 | 0.44 | 0.01 | no |
| basis · + · z 1.0/2.0 · tsmom_tranches | 1.81 | 1.85 | 0.32 | 0.73 | 0.08 | 0.09 | 1 | -0.95 | -1.02 | 0.08 | 0.35 | 0.14 | 0.47 | 0.05 | 0.07 | 0.00 | no |
| oi_7 · - · z 0.5/1.5 · breakout | 1.31 | 1.19 | 0.87 | 1.17 | 0.16 | 0.16 | 0 | -1.44 | -0.61 | -0.10 | 0.97 | 0.73 | 1.07 | 0.06 | 0.15 | 0.00 | no |
| oi_7 · + · z 1.0/2.0 · tsmom_daily | 1.38 | 1.38 | 0.61 | 0.64 | 0.09 | 0.09 | 0 | -0.28 | -0.15 | 0.08 | 0.60 | 0.25 | 0.32 | 0.01 | 0.10 | 0.00 | no |
| oi_7 · + · z 1.0/2.0 · tsmom_tranches | 1.24 | 1.25 | 0.69 | 0.73 | 0.09 | 0.09 | 0 | -0.36 | -0.17 | 0.07 | 0.69 | 0.38 | 0.47 | 0.01 | 0.10 | 0.00 | no |
| ls_ratio · + · z 1.0/2.0 · breakout | 1.18 | 1.14 | 1.39 | 1.17 | 0.16 | 0.16 | 2 | 0.69 | 0.03 | 0.40 | 1.26 | 1.28 | 1.07 | 0.03 | 0.18 | 0.03 | no |
| ls_ratio · + · z 1.0/2.0 · tsmom_daily | 1.46 | 1.40 | 0.78 | 0.64 | 0.08 | 0.09 | 2 | 0.47 | 0.01 | 0.27 | 0.74 | 0.48 | 0.32 | 0.03 | 0.18 | 0.03 | no |
| ls_ratio · + · z 0.5/1.5 · tsmom_tranches | 1.34 | 1.27 | 0.80 | 0.73 | 0.08 | 0.09 | 2 | 0.06 | -0.08 | 0.25 | 0.95 | 0.55 | 0.47 | 0.10 | 0.24 | 0.00 | no |
| liq · + · z 0.5/1.5 · breakout | 1.37 | 1.18 | 1.00 | 1.17 | 0.14 | 0.16 | 2 | -1.01 | -0.44 | 0.04 | 0.96 | 0.90 | 1.07 | 0.04 | 0.14 | 0.00 | no |
| liq · - · z 1.0/2.0 · tsmom_daily | 1.38 | 1.37 | 0.56 | 0.64 | 0.09 | 0.09 | 1 | -0.69 | -0.24 | 0.06 | 0.59 | 0.22 | 0.32 | 0.00 | 0.08 | 0.00 | no |
| liq · - · z 1.0/2.0 · tsmom_tranches | 1.27 | 1.25 | 0.61 | 0.73 | 0.09 | 0.09 | 0 | -0.96 | -0.30 | 0.02 | 0.64 | 0.37 | 0.47 | 0.00 | 0.08 | 0.00 | no |
| dvol · - · z 0.5/1.5 · breakout | 1.08 | 0.84 | 1.01 | 1.17 | 0.15 | 0.16 | 0 | -0.72 | -0.66 | 0.21 | 0.98 | 0.81 | 1.07 | 0.14 | 0.27 | 0.00 | no |
| dvol · - · z 1.0/2.0 · tsmom_daily | 1.18 | 0.96 | 0.54 | 0.64 | 0.11 | 0.09 | 0 | -0.46 | -0.66 | 0.32 | 0.59 | 0.06 | 0.32 | 0.06 | 0.19 | 0.00 | no |
| dvol · - · z 0.5/1.5 · tsmom_tranches | 1.19 | 0.90 | 0.60 | 0.73 | 0.09 | 0.09 | 0 | -0.50 | -0.85 | 0.37 | 0.56 | 0.11 | 0.47 | 0.14 | 0.27 | 0.00 | no |
| logit long C 0.1 · breakout | 1.19 | 1.38 | 0.03 | 1.17 | 0.20 | 0.16 | 0 | -2.08 | -2.14 | -0.11 | -0.20 | 0.27 | 1.07 | 0.14 | 0.22 | 0.00 | no |
| logit long C 0.1 · tsmom_daily | 1.55 | 1.50 | 0.11 | 0.64 | 0.11 | 0.09 | 0 | -1.32 | -1.30 | 0.06 | 0.04 | -0.15 | 0.32 | 0.14 | 0.22 | 0.00 | no |
| logit long C 0.1 · tsmom_tranches | 1.43 | 1.36 | 0.10 | 0.73 | 0.12 | 0.09 | 0 | -1.55 | -1.46 | 0.00 | 0.09 | -0.00 | 0.47 | 0.14 | 0.22 | 0.00 | no |

### The books alone (references, not counted)

| variant | is_maker 15bps | is_taker 35bps | oos_maker 15bps | oos_taker 35bps | oos_stress 70bps | cagr_35 | dd_35 | expo | turnover_yr | y2024 | y2025 | y2026 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| breakout_top10 live alone | 1.50 | 1.45 | 1.24 | 1.17 | 1.04 | 0.19 | 0.16 | 0.15 | 5.76 | 2.19 | 0.32 | -0.02 |
| breakout_top10 twin alone | 1.40 | 1.35 | 1.16 | 1.07 | 0.91 | 0.22 | 0.22 | 0.24 | 9.36 | 1.84 | 0.46 | 0.42 |
| tsmom_top20 live alone | 1.79 | 1.68 | 0.78 | 0.64 | 0.39 | 0.05 | 0.09 | 0.09 | 6.10 | 1.56 | -0.35 | 0.90 |
| tsmom_top20 twin alone | 1.44 | 1.31 | 0.48 | 0.32 | 0.03 | 0.04 | 0.24 | 0.17 | 12.86 | 0.37 | -0.29 | 1.18 |
| tsmom_tranches live alone | 1.89 | 1.85 | 0.78 | 0.73 | 0.64 | 0.07 | 0.09 | 0.09 | 2.39 | 1.67 | -0.08 | 0.62 |
| tsmom_tranches twin alone | 1.59 | 1.54 | 0.53 | 0.47 | 0.36 | 0.07 | 0.23 | 0.17 | 5.00 | 0.59 | 0.08 | 0.99 |

### Signals: first z-score and rank correlation with the next 7 days of the Alpaca basket

| signal | first_z | prior_sign | ic_is | ic_oos |
|---|---|---|---|---|
| cb_prem | 2020-07-02 | -1 | 0.02 | 0.05 |
| kr_prem | 2020-07-02 | 1 | 0.10 | 0.02 |
| stable_30 | 2020-07-28 | -1 | 0.08 | 0.08 |
| stable_7 | 2020-07-05 | -1 | 0.07 | 0.09 |
| funding | 2020-07-02 | 1 | 0.15 | -0.04 |
| basis | 2020-07-02 | 1 | 0.16 | 0.06 |
| oi_7 | 2022-07-08 | 1 | 0.06 | -0.05 |
| ls_ratio | 2022-07-21 | 1 | -0.08 | -0.08 |
| liq | 2022-07-04 | -1 | -0.14 | -0.03 |
| dvol | 2021-09-19 | 1 | 0.23 | 0.04 |

### The combination (bad week: the basket down more than 5 % over the next 7 days)

| model | first_prediction | auc_oos | brier_oos | brier_base | bad_rate_oos |
|---|---|---|---|---|---|
| long C 0.1 | 2022-10-01 | 0.48 | 0.20 | 0.19 | 0.26 |
| long C 1.0 | 2022-10-01 | 0.48 | 0.20 | 0.19 | 0.26 |
| all C 0.1 | 2023-10-01 | 0.48 | 0.21 | 0.20 | 0.27 |
| all C 1.0 | 2023-10-01 | 0.48 | 0.21 | 0.20 | 0.27 |

- long C 0.1, last fit 2026-10-01 on 1831 rows (base rate 0.27): cb_prem -0.19, kr_prem -0.03, stable_30 +0.05, stable_7 +0.03, funding +0.08, basis -0.14, dvol -0.18
- long C 1.0, last fit 2026-10-01 on 1831 rows (base rate 0.27): cb_prem -0.21, kr_prem -0.03, stable_30 +0.06, stable_7 +0.03, funding +0.09, basis -0.15, dvol -0.19
- all C 0.1, last fit 2026-10-01 on 1526 rows (base rate 0.25): cb_prem -0.16, kr_prem -0.14, stable_30 +0.06, stable_7 +0.04, funding +0.06, basis -0.04, oi_7 +0.27, ls_ratio +0.18, liq +0.33, dvol -0.11
- all C 1.0, last fit 2026-10-01 on 1526 rows (base rate 0.25): cb_prem -0.18, kr_prem -0.16, stable_30 +0.07, stable_7 +0.05, funding +0.07, basis -0.04, oi_7 +0.31, ls_ratio +0.19, liq +0.38, dvol -0.12

### Every trial

S single signal (+ risk-off when high, - when low), C combination, L a pick one day late, T a pick on the twin. In-sample Sharpe over the days the signal existed.

| variant | is_maker 15bps | is_taker 35bps | oos_maker 15bps | oos_taker 35bps | oos_stress 70bps | cagr_35 | dd_35 | expo | turnover_yr | half_days | zero_days | diff_sr | deflated_p_diff | deflated_p_pool |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| cb_prem · + · z 1.0/2.0 · breakout | 1.55 | 1.49 | 1.07 | 0.96 | 0.77 | 0.13 | 0.15 | 0.13 | 7.12 | 0.07 | 0.00 | -1.00 | 0.00 | 0.01 |
| cb_prem · + · z 0.5/1.5 · breakout | 1.36 | 1.29 | 0.97 | 0.84 | 0.60 | 0.08 | 0.11 | 0.11 | 7.13 | 0.23 | 0.02 | -1.11 | 0.00 | 0.00 |
| cb_prem · - · z 1.0/2.0 · breakout | 1.47 | 1.41 | 1.22 | 1.14 | 1.00 | 0.18 | 0.16 | 0.14 | 6.05 | 0.16 | 0.08 | -0.35 | 0.00 | 0.02 |
| cb_prem · - · z 0.5/1.5 · breakout | 1.42 | 1.36 | 1.19 | 1.11 | 0.98 | 0.17 | 0.15 | 0.13 | 5.84 | 0.25 | 0.12 | -0.52 | 0.00 | 0.02 |
| cb_prem · + · z 1.0/2.0 · tsmom_daily | 1.81 | 1.70 | 0.69 | 0.53 | 0.25 | 0.04 | 0.08 | 0.08 | 6.66 | 0.07 | 0.00 | -0.68 | 0.00 | 0.00 |
| cb_prem · + · z 0.5/1.5 · tsmom_daily | 1.73 | 1.60 | 0.56 | 0.39 | 0.08 | 0.02 | 0.09 | 0.07 | 6.03 | 0.23 | 0.02 | -0.86 | 0.00 | 0.00 |
| cb_prem · - · z 1.0/2.0 · tsmom_daily | 1.73 | 1.62 | 0.81 | 0.67 | 0.42 | 0.05 | 0.08 | 0.09 | 6.16 | 0.16 | 0.08 | 0.23 | 0.01 | 0.00 |
| cb_prem · - · z 0.5/1.5 · tsmom_daily | 1.70 | 1.59 | 0.78 | 0.64 | 0.38 | 0.05 | 0.07 | 0.08 | 5.96 | 0.25 | 0.12 | -0.19 | 0.00 | 0.00 |
| cb_prem · + · z 1.0/2.0 · tsmom_tranches | 1.94 | 1.90 | 0.58 | 0.51 | 0.38 | 0.04 | 0.09 | 0.08 | 3.11 | 0.07 | 0.00 | -1.09 | 0.00 | 0.00 |
| cb_prem · + · z 0.5/1.5 · tsmom_tranches | 1.80 | 1.75 | 0.54 | 0.45 | 0.30 | 0.03 | 0.08 | 0.07 | 3.06 | 0.23 | 0.02 | -0.92 | 0.00 | 0.00 |
| cb_prem · - · z 1.0/2.0 · tsmom_tranches | 1.83 | 1.79 | 0.78 | 0.72 | 0.63 | 0.06 | 0.08 | 0.09 | 2.59 | 0.16 | 0.08 | -0.14 | 0.00 | 0.00 |
| cb_prem · - · z 0.5/1.5 · tsmom_tranches | 1.81 | 1.76 | 0.79 | 0.73 | 0.62 | 0.06 | 0.08 | 0.08 | 2.69 | 0.25 | 0.12 | -0.17 | 0.00 | 0.00 |
| kr_prem · + · z 1.0/2.0 · breakout | 1.26 | 1.20 | 1.29 | 1.21 | 1.07 | 0.18 | 0.16 | 0.13 | 5.60 | 0.09 | 0.05 | -0.18 | 0.00 | 0.02 |
| kr_prem · + · z 0.5/1.5 · breakout | 1.30 | 1.23 | 1.17 | 1.10 | 0.96 | 0.16 | 0.16 | 0.13 | 5.37 | 0.09 | 0.10 | -0.43 | 0.00 | 0.01 |
| kr_prem · - · z 1.0/2.0 · breakout | 1.33 | 1.26 | 1.15 | 1.04 | 0.86 | 0.13 | 0.12 | 0.12 | 6.42 | 0.19 | 0.00 | -0.94 | 0.00 | 0.01 |
| kr_prem · - · z 0.5/1.5 · breakout | 1.24 | 1.18 | 0.91 | 0.80 | 0.59 | 0.08 | 0.10 | 0.09 | 5.93 | 0.39 | 0.06 | -1.07 | 0.00 | 0.00 |
| kr_prem · + · z 1.0/2.0 · tsmom_daily | 1.54 | 1.42 | 0.69 | 0.55 | 0.30 | 0.04 | 0.09 | 0.08 | 5.74 | 0.09 | 0.05 | -0.41 | 0.00 | 0.00 |
| kr_prem · + · z 0.5/1.5 · tsmom_daily | 1.41 | 1.28 | 0.52 | 0.38 | 0.14 | 0.03 | 0.08 | 0.07 | 5.56 | 0.09 | 0.10 | -0.73 | 0.00 | 0.00 |
| kr_prem · - · z 1.0/2.0 · tsmom_daily | 1.66 | 1.53 | 0.67 | 0.51 | 0.24 | 0.04 | 0.08 | 0.08 | 6.14 | 0.19 | 0.00 | -0.68 | 0.00 | 0.00 |
| kr_prem · - · z 0.5/1.5 · tsmom_daily | 1.63 | 1.51 | 0.57 | 0.41 | 0.13 | 0.03 | 0.08 | 0.06 | 5.53 | 0.39 | 0.06 | -0.75 | 0.00 | 0.00 |
| kr_prem · + · z 1.0/2.0 · tsmom_tranches | 1.56 | 1.51 | 0.70 | 0.64 | 0.54 | 0.05 | 0.08 | 0.08 | 2.46 | 0.09 | 0.05 | -0.41 | 0.00 | 0.00 |
| kr_prem · + · z 0.5/1.5 · tsmom_tranches | 1.43 | 1.37 | 0.54 | 0.48 | 0.37 | 0.04 | 0.08 | 0.07 | 2.47 | 0.09 | 0.10 | -0.69 | 0.00 | 0.00 |
| kr_prem · - · z 1.0/2.0 · tsmom_tranches | 1.76 | 1.71 | 0.65 | 0.59 | 0.47 | 0.05 | 0.08 | 0.08 | 2.83 | 0.19 | 0.00 | -0.75 | 0.00 | 0.00 |
| kr_prem · - · z 0.5/1.5 · tsmom_tranches | 1.74 | 1.69 | 0.49 | 0.42 | 0.30 | 0.03 | 0.08 | 0.07 | 2.61 | 0.39 | 0.06 | -0.96 | 0.00 | 0.00 |
| stable_30 · + · z 1.0/2.0 · breakout | 1.36 | 1.29 | 0.89 | 0.78 | 0.60 | 0.08 | 0.16 | 0.11 | 5.70 | 0.09 | 0.08 | -0.95 | 0.00 | 0.00 |
| stable_30 · + · z 0.5/1.5 · breakout | 1.21 | 1.14 | 0.71 | 0.60 | 0.40 | 0.06 | 0.16 | 0.11 | 5.82 | 0.09 | 0.12 | -1.10 | 0.00 | 0.00 |
| stable_30 · - · z 1.0/2.0 · breakout | 1.34 | 1.29 | 1.26 | 1.18 | 1.05 | 0.18 | 0.15 | 0.14 | 6.04 | 0.14 | 0.04 | -0.06 | 0.00 | 0.02 |
| stable_30 · - · z 0.5/1.5 · breakout | 1.44 | 1.39 | 1.18 | 1.10 | 0.96 | 0.16 | 0.14 | 0.12 | 6.00 | 0.27 | 0.11 | -0.56 | 0.00 | 0.01 |
| stable_30 · + · z 1.0/2.0 · tsmom_daily | 1.67 | 1.55 | 0.46 | 0.31 | 0.06 | 0.02 | 0.07 | 0.07 | 5.59 | 0.09 | 0.08 | -0.93 | 0.00 | 0.00 |
| stable_30 · + · z 0.5/1.5 · tsmom_daily | 1.54 | 1.40 | 0.44 | 0.29 | 0.02 | 0.02 | 0.07 | 0.07 | 5.60 | 0.09 | 0.12 | -0.88 | 0.00 | 0.00 |
| stable_30 · - · z 1.0/2.0 · tsmom_daily | 1.77 | 1.66 | 0.74 | 0.60 | 0.36 | 0.05 | 0.09 | 0.09 | 6.02 | 0.14 | 0.04 | -0.49 | 0.00 | 0.00 |
| stable_30 · - · z 0.5/1.5 · tsmom_daily | 1.86 | 1.75 | 0.73 | 0.58 | 0.32 | 0.04 | 0.09 | 0.08 | 6.12 | 0.27 | 0.11 | -0.47 | 0.00 | 0.00 |
| stable_30 · + · z 1.0/2.0 · tsmom_tranches | 1.77 | 1.72 | 0.45 | 0.39 | 0.28 | 0.03 | 0.08 | 0.07 | 2.44 | 0.09 | 0.08 | -0.94 | 0.00 | 0.00 |
| stable_30 · + · z 0.5/1.5 · tsmom_tranches | 1.62 | 1.56 | 0.40 | 0.33 | 0.22 | 0.02 | 0.08 | 0.07 | 2.61 | 0.09 | 0.12 | -0.93 | 0.00 | 0.00 |
| stable_30 · - · z 1.0/2.0 · tsmom_tranches | 1.84 | 1.80 | 0.75 | 0.69 | 0.60 | 0.06 | 0.09 | 0.09 | 2.38 | 0.14 | 0.04 | -0.55 | 0.00 | 0.00 |
| stable_30 · - · z 0.5/1.5 · tsmom_tranches | 1.88 | 1.84 | 0.78 | 0.72 | 0.62 | 0.06 | 0.09 | 0.08 | 2.69 | 0.27 | 0.11 | -0.16 | 0.00 | 0.00 |
| stable_7 · + · z 1.0/2.0 · breakout | 1.43 | 1.35 | 0.16 | 0.02 | -0.23 | -0.00 | 0.16 | 0.12 | 8.21 | 0.08 | 0.06 | -1.76 | 0.00 | 0.00 |
| stable_7 · + · z 0.5/1.5 · breakout | 1.36 | 1.27 | 0.25 | 0.08 | -0.21 | 0.00 | 0.16 | 0.10 | 8.41 | 0.14 | 0.08 | -1.58 | 0.00 | 0.00 |
| stable_7 · - · z 1.0/2.0 · breakout | 1.48 | 1.41 | 1.26 | 1.18 | 1.03 | 0.18 | 0.15 | 0.14 | 6.66 | 0.16 | 0.01 | -0.08 | 0.00 | 0.02 |
| stable_7 · - · z 0.5/1.5 · breakout | 1.41 | 1.34 | 1.29 | 1.20 | 1.04 | 0.18 | 0.16 | 0.13 | 7.10 | 0.30 | 0.04 | -0.06 | 0.00 | 0.02 |
| stable_7 · + · z 1.0/2.0 · tsmom_daily | 1.71 | 1.57 | 0.18 | -0.01 | -0.34 | -0.00 | 0.12 | 0.07 | 7.33 | 0.08 | 0.06 | -1.58 | 0.00 | 0.00 |
| stable_7 · + · z 0.5/1.5 · tsmom_daily | 1.58 | 1.43 | 0.23 | 0.03 | -0.31 | -0.00 | 0.11 | 0.07 | 7.08 | 0.14 | 0.08 | -1.32 | 0.00 | 0.00 |
| stable_7 · - · z 1.0/2.0 · tsmom_daily | 1.82 | 1.69 | 0.85 | 0.69 | 0.43 | 0.06 | 0.08 | 0.09 | 6.54 | 0.16 | 0.01 | 0.52 | 0.02 | 0.00 |
| stable_7 · - · z 0.5/1.5 · tsmom_daily | 1.77 | 1.65 | 0.91 | 0.74 | 0.45 | 0.06 | 0.09 | 0.08 | 6.74 | 0.30 | 0.04 | 0.25 | 0.01 | 0.00 |
| stable_7 · + · z 1.0/2.0 · tsmom_tranches | 1.83 | 1.77 | 0.10 | -0.00 | -0.18 | -0.00 | 0.12 | 0.07 | 4.00 | 0.08 | 0.06 | -1.58 | 0.00 | 0.00 |
| stable_7 · + · z 0.5/1.5 · tsmom_tranches | 1.71 | 1.63 | 0.24 | 0.12 | -0.07 | 0.01 | 0.10 | 0.07 | 4.05 | 0.14 | 0.08 | -1.19 | 0.00 | 0.00 |
| stable_7 · - · z 1.0/2.0 · tsmom_tranches | 1.89 | 1.84 | 0.83 | 0.77 | 0.66 | 0.07 | 0.08 | 0.09 | 2.98 | 0.16 | 0.01 | 0.39 | 0.01 | 0.00 |
| stable_7 · - · z 0.5/1.5 · tsmom_tranches | 1.87 | 1.81 | 0.86 | 0.79 | 0.65 | 0.07 | 0.09 | 0.08 | 3.54 | 0.30 | 0.04 | 0.06 | 0.00 | 0.00 |
| funding · + · z 1.0/2.0 · breakout | 1.28 | 1.21 | 1.29 | 1.21 | 1.06 | 0.18 | 0.16 | 0.14 | 6.19 | 0.07 | 0.00 | -0.23 | 0.00 | 0.02 |
| funding · + · z 0.5/1.5 · breakout | 1.42 | 1.33 | 1.50 | 1.40 | 1.23 | 0.19 | 0.13 | 0.11 | 6.42 | 0.34 | 0.00 | -0.04 | 0.00 | 0.04 |
| funding · - · z 1.0/2.0 · breakout | 1.58 | 1.53 | 1.14 | 1.05 | 0.90 | 0.16 | 0.17 | 0.13 | 6.59 | 0.11 | 0.05 | -0.88 | 0.00 | 0.01 |
| funding · - · z 0.5/1.5 · breakout | 1.51 | 1.44 | 1.09 | 1.00 | 0.85 | 0.15 | 0.18 | 0.13 | 6.35 | 0.13 | 0.09 | -1.02 | 0.00 | 0.01 |
| funding · + · z 1.0/2.0 · tsmom_daily | 1.55 | 1.43 | 0.83 | 0.67 | 0.40 | 0.05 | 0.09 | 0.08 | 6.41 | 0.07 | 0.00 | -0.03 | 0.00 | 0.00 |
| funding · + · z 0.5/1.5 · tsmom_daily | 1.62 | 1.47 | 0.92 | 0.76 | 0.47 | 0.05 | 0.09 | 0.07 | 5.91 | 0.34 | 0.00 | -0.00 | 0.00 | 0.00 |
| funding · - · z 1.0/2.0 · tsmom_daily | 1.77 | 1.65 | 0.72 | 0.57 | 0.31 | 0.04 | 0.11 | 0.08 | 6.09 | 0.11 | 0.05 | -0.41 | 0.00 | 0.00 |
| funding · - · z 0.5/1.5 · tsmom_daily | 1.69 | 1.57 | 0.55 | 0.40 | 0.12 | 0.03 | 0.13 | 0.08 | 6.12 | 0.13 | 0.09 | -0.91 | 0.00 | 0.00 |
| funding · + · z 1.0/2.0 · tsmom_tranches | 1.66 | 1.61 | 0.82 | 0.76 | 0.64 | 0.06 | 0.09 | 0.09 | 2.76 | 0.07 | 0.00 | -0.13 | 0.00 | 0.00 |
| funding · + · z 0.5/1.5 · tsmom_tranches | 1.77 | 1.69 | 1.00 | 0.92 | 0.78 | 0.07 | 0.08 | 0.07 | 2.91 | 0.34 | 0.00 | 0.01 | 0.00 | 0.01 |
| funding · - · z 1.0/2.0 · tsmom_tranches | 1.87 | 1.83 | 0.63 | 0.56 | 0.44 | 0.05 | 0.12 | 0.08 | 3.03 | 0.11 | 0.05 | -0.79 | 0.00 | 0.00 |
| funding · - · z 0.5/1.5 · tsmom_tranches | 1.82 | 1.76 | 0.45 | 0.37 | 0.24 | 0.03 | 0.15 | 0.08 | 3.22 | 0.13 | 0.09 | -1.29 | 0.00 | 0.00 |
| basis · + · z 1.0/2.0 · breakout | 1.48 | 1.40 | 1.02 | 0.90 | 0.71 | 0.10 | 0.16 | 0.11 | 6.35 | 0.07 | 0.05 | -0.95 | 0.00 | 0.01 |
| basis · + · z 0.5/1.5 · breakout | 1.37 | 1.27 | 0.96 | 0.85 | 0.65 | 0.09 | 0.14 | 0.11 | 6.04 | 0.10 | 0.07 | -1.05 | 0.00 | 0.00 |
| basis · - · z 1.0/2.0 · breakout | 1.49 | 1.44 | 1.24 | 1.17 | 1.04 | 0.19 | 0.16 | 0.14 | 5.82 | 0.07 | 0.00 | -0.06 | 0.00 | 0.02 |
| basis · - · z 0.5/1.5 · breakout | 1.54 | 1.49 | 1.41 | 1.33 | 1.20 | 0.21 | 0.15 | 0.13 | 5.51 | 0.44 | 0.00 | 0.61 | 0.03 | 0.03 |
| basis · + · z 1.0/2.0 · tsmom_daily | 1.72 | 1.59 | 0.42 | 0.25 | -0.05 | 0.02 | 0.09 | 0.07 | 6.25 | 0.07 | 0.05 | -0.93 | 0.00 | 0.00 |
| basis · + · z 0.5/1.5 · tsmom_daily | 1.64 | 1.48 | 0.34 | 0.18 | -0.11 | 0.01 | 0.09 | 0.07 | 5.85 | 0.10 | 0.07 | -1.01 | 0.00 | 0.00 |
| basis · - · z 1.0/2.0 · tsmom_daily | 1.71 | 1.59 | 0.78 | 0.64 | 0.40 | 0.05 | 0.09 | 0.09 | 6.07 | 0.07 | 0.00 | 0.92 | 0.00 | 0.00 |
| basis · - · z 0.5/1.5 · tsmom_daily | 1.72 | 1.61 | 0.93 | 0.79 | 0.54 | 0.06 | 0.06 | 0.08 | 5.67 | 0.44 | 0.00 | 0.32 | 0.01 | 0.00 |
| basis · + · z 1.0/2.0 · tsmom_tranches | 1.87 | 1.81 | 0.39 | 0.32 | 0.19 | 0.02 | 0.08 | 0.07 | 2.86 | 0.07 | 0.05 | -0.95 | 0.00 | 0.00 |
| basis · + · z 0.5/1.5 · tsmom_tranches | 1.82 | 1.74 | 0.31 | 0.24 | 0.12 | 0.02 | 0.08 | 0.07 | 2.64 | 0.10 | 0.07 | -1.02 | 0.00 | 0.00 |
| basis · - · z 1.0/2.0 · tsmom_tranches | 1.81 | 1.77 | 0.77 | 0.72 | 0.63 | 0.06 | 0.09 | 0.09 | 2.38 | 0.07 | 0.00 | -0.29 | 0.00 | 0.00 |
| basis · - · z 0.5/1.5 · tsmom_tranches | 1.82 | 1.78 | 0.91 | 0.85 | 0.74 | 0.07 | 0.09 | 0.08 | 2.68 | 0.44 | 0.00 | 0.30 | 0.01 | 0.01 |
| oi_7 · + · z 1.0/2.0 · breakout | 1.28 | 1.17 | 1.19 | 1.07 | 0.86 | 0.16 | 0.15 | 0.13 | 9.30 | 0.10 | 0.01 | -0.92 | 0.00 | 0.01 |
| oi_7 · + · z 0.5/1.5 · breakout | 1.01 | 0.84 | 1.24 | 1.08 | 0.80 | 0.15 | 0.15 | 0.12 | 11.14 | 0.27 | 0.03 | -0.74 | 0.00 | 0.01 |
| oi_7 · - · z 1.0/2.0 · breakout | 1.33 | 1.19 | 1.14 | 1.05 | 0.89 | 0.16 | 0.16 | 0.14 | 6.85 | 0.08 | 0.02 | -1.24 | 0.00 | 0.01 |
| oi_7 · - · z 0.5/1.5 · breakout | 1.48 | 1.31 | 0.99 | 0.87 | 0.65 | 0.12 | 0.16 | 0.13 | 9.10 | 0.15 | 0.06 | -1.44 | 0.00 | 0.00 |
| oi_7 · + · z 1.0/2.0 · tsmom_daily | 1.55 | 1.38 | 0.80 | 0.61 | 0.28 | 0.05 | 0.09 | 0.08 | 7.83 | 0.10 | 0.01 | -0.28 | 0.00 | 0.00 |
| oi_7 · + · z 0.5/1.5 · tsmom_daily | 1.34 | 1.12 | 0.87 | 0.67 | 0.30 | 0.05 | 0.08 | 0.07 | 8.18 | 0.27 | 0.03 | -0.10 | 0.00 | 0.00 |
| oi_7 · - · z 1.0/2.0 · tsmom_daily | 1.46 | 1.27 | 0.62 | 0.46 | 0.18 | 0.04 | 0.09 | 0.08 | 6.75 | 0.08 | 0.02 | -1.20 | 0.00 | 0.00 |
| oi_7 · - · z 0.5/1.5 · tsmom_daily | 1.48 | 1.27 | 0.31 | 0.11 | -0.26 | 0.01 | 0.12 | 0.08 | 8.08 | 0.15 | 0.06 | -1.92 | 0.00 | 0.00 |
| oi_7 · + · z 1.0/2.0 · tsmom_tranches | 1.33 | 1.24 | 0.78 | 0.69 | 0.53 | 0.06 | 0.09 | 0.09 | 4.23 | 0.10 | 0.01 | -0.36 | 0.00 | 0.00 |
| oi_7 · + · z 0.5/1.5 · tsmom_tranches | 1.12 | 0.96 | 0.81 | 0.68 | 0.47 | 0.06 | 0.08 | 0.08 | 5.23 | 0.27 | 0.03 | -0.37 | 0.00 | 0.00 |
| oi_7 · - · z 1.0/2.0 · tsmom_tranches | 1.19 | 1.08 | 0.55 | 0.47 | 0.33 | 0.04 | 0.09 | 0.08 | 3.52 | 0.08 | 0.02 | -1.47 | 0.00 | 0.00 |
| oi_7 · - · z 0.5/1.5 · tsmom_tranches | 1.25 | 1.10 | 0.21 | 0.09 | -0.13 | 0.00 | 0.13 | 0.08 | 5.20 | 0.15 | 0.06 | -2.05 | 0.00 | 0.00 |
| ls_ratio · + · z 1.0/2.0 · breakout | 1.26 | 1.18 | 1.47 | 1.39 | 1.25 | 0.21 | 0.16 | 0.14 | 5.92 | 0.18 | 0.03 | 0.69 | 0.03 | 0.04 |
| ls_ratio · + · z 0.5/1.5 · breakout | 1.23 | 1.15 | 1.31 | 1.22 | 1.08 | 0.18 | 0.16 | 0.13 | 5.91 | 0.24 | 0.10 | -0.24 | 0.00 | 0.02 |
| ls_ratio · - · z 1.0/2.0 · breakout | 1.15 | 1.03 | 1.07 | 0.98 | 0.82 | 0.14 | 0.16 | 0.12 | 6.41 | 0.16 | 0.01 | -1.13 | 0.00 | 0.01 |
| ls_ratio · - · z 0.5/1.5 · breakout | 1.01 | 0.87 | 0.95 | 0.85 | 0.68 | 0.11 | 0.19 | 0.10 | 6.44 | 0.26 | 0.05 | -1.18 | 0.00 | 0.00 |
| ls_ratio · + · z 1.0/2.0 · tsmom_daily | 1.60 | 1.46 | 0.92 | 0.78 | 0.53 | 0.06 | 0.08 | 0.08 | 5.84 | 0.18 | 0.03 | 0.47 | 0.03 | 0.00 |
| ls_ratio · + · z 0.5/1.5 · tsmom_daily | 1.55 | 1.42 | 0.85 | 0.71 | 0.47 | 0.06 | 0.08 | 0.08 | 5.63 | 0.24 | 0.10 | 0.08 | 0.00 | 0.00 |
| ls_ratio · - · z 1.0/2.0 · tsmom_daily | 1.34 | 1.17 | 0.64 | 0.48 | 0.21 | 0.03 | 0.11 | 0.07 | 5.92 | 0.16 | 0.01 | -0.79 | 0.00 | 0.00 |
| ls_ratio · - · z 0.5/1.5 · tsmom_daily | 1.22 | 1.04 | 0.55 | 0.39 | 0.10 | 0.02 | 0.11 | 0.06 | 5.57 | 0.26 | 0.05 | -0.71 | 0.00 | 0.00 |
| ls_ratio · + · z 1.0/2.0 · tsmom_tranches | 1.39 | 1.33 | 0.94 | 0.89 | 0.78 | 0.08 | 0.08 | 0.08 | 2.59 | 0.18 | 0.03 | 0.50 | 0.03 | 0.01 |
| ls_ratio · + · z 0.5/1.5 · tsmom_tranches | 1.41 | 1.34 | 0.87 | 0.80 | 0.70 | 0.07 | 0.08 | 0.08 | 2.68 | 0.24 | 0.10 | 0.06 | 0.00 | 0.00 |
| ls_ratio · - · z 1.0/2.0 · tsmom_tranches | 1.11 | 1.02 | 0.61 | 0.54 | 0.43 | 0.04 | 0.10 | 0.08 | 2.67 | 0.16 | 0.01 | -0.96 | 0.00 | 0.00 |
| ls_ratio · - · z 0.5/1.5 · tsmom_tranches | 1.09 | 1.00 | 0.54 | 0.46 | 0.32 | 0.03 | 0.11 | 0.07 | 2.84 | 0.26 | 0.05 | -0.85 | 0.00 | 0.00 |
| liq · + · z 1.0/2.0 · breakout | 1.39 | 1.26 | 1.17 | 1.08 | 0.94 | 0.17 | 0.15 | 0.14 | 6.45 | 0.05 | 0.04 | -0.81 | 0.00 | 0.01 |
| liq · + · z 0.5/1.5 · breakout | 1.49 | 1.37 | 1.11 | 1.00 | 0.81 | 0.15 | 0.14 | 0.13 | 8.20 | 0.14 | 0.04 | -1.01 | 0.00 | 0.01 |
| liq · - · z 1.0/2.0 · breakout | 1.12 | 1.03 | 1.02 | 0.93 | 0.77 | 0.14 | 0.18 | 0.14 | 6.73 | 0.08 | 0.00 | -1.66 | 0.00 | 0.01 |
| liq · - · z 0.5/1.5 · breakout | 0.77 | 0.65 | 0.98 | 0.85 | 0.62 | 0.11 | 0.15 | 0.12 | 8.55 | 0.37 | 0.01 | -1.48 | 0.00 | 0.01 |
| liq · + · z 1.0/2.0 · tsmom_daily | 1.42 | 1.26 | 0.71 | 0.56 | 0.31 | 0.05 | 0.09 | 0.09 | 6.23 | 0.05 | 0.04 | -0.66 | 0.00 | 0.00 |
| liq · + · z 0.5/1.5 · tsmom_daily | 1.37 | 1.20 | 0.73 | 0.56 | 0.25 | 0.04 | 0.09 | 0.08 | 7.16 | 0.14 | 0.04 | -0.52 | 0.00 | 0.00 |
| liq · - · z 1.0/2.0 · tsmom_daily | 1.54 | 1.38 | 0.71 | 0.56 | 0.28 | 0.04 | 0.09 | 0.08 | 6.55 | 0.08 | 0.00 | -0.69 | 0.00 | 0.00 |
| liq · - · z 0.5/1.5 · tsmom_daily | 1.26 | 1.07 | 0.70 | 0.50 | 0.15 | 0.03 | 0.07 | 0.07 | 7.25 | 0.37 | 0.01 | -0.66 | 0.00 | 0.00 |
| liq · + · z 1.0/2.0 · tsmom_tranches | 1.20 | 1.12 | 0.62 | 0.56 | 0.45 | 0.05 | 0.09 | 0.09 | 2.86 | 0.05 | 0.04 | -1.09 | 0.00 | 0.00 |
| liq · + · z 0.5/1.5 · tsmom_tranches | 1.18 | 1.09 | 0.59 | 0.49 | 0.33 | 0.04 | 0.11 | 0.08 | 4.10 | 0.14 | 0.04 | -1.06 | 0.00 | 0.00 |
| liq · - · z 1.0/2.0 · tsmom_tranches | 1.35 | 1.27 | 0.68 | 0.61 | 0.50 | 0.05 | 0.09 | 0.09 | 2.95 | 0.08 | 0.00 | -0.96 | 0.00 | 0.00 |
| liq · - · z 0.5/1.5 · tsmom_tranches | 1.02 | 0.91 | 0.60 | 0.50 | 0.31 | 0.04 | 0.07 | 0.07 | 4.34 | 0.37 | 0.01 | -1.00 | 0.00 | 0.00 |
| dvol · + · z 1.0/2.0 · breakout | 0.97 | 0.89 | 1.31 | 1.22 | 1.08 | 0.18 | 0.15 | 0.13 | 5.88 | 0.09 | 0.04 | -0.16 | 0.00 | 0.02 |
| dvol · + · z 0.5/1.5 · breakout | 0.92 | 0.81 | 1.29 | 1.20 | 1.04 | 0.17 | 0.14 | 0.12 | 6.23 | 0.11 | 0.08 | -0.26 | 0.00 | 0.02 |
| dvol · - · z 1.0/2.0 · breakout | 0.88 | 0.79 | 1.05 | 0.95 | 0.79 | 0.14 | 0.20 | 0.12 | 6.71 | 0.19 | 0.06 | -1.05 | 0.00 | 0.01 |
| dvol · - · z 0.5/1.5 · breakout | 1.19 | 1.08 | 1.09 | 1.01 | 0.87 | 0.14 | 0.15 | 0.10 | 5.37 | 0.27 | 0.14 | -0.72 | 0.00 | 0.01 |
| dvol · + · z 1.0/2.0 · tsmom_daily | 1.10 | 0.98 | 0.68 | 0.53 | 0.26 | 0.04 | 0.09 | 0.08 | 6.11 | 0.09 | 0.04 | -0.45 | 0.00 | 0.00 |
| dvol · + · z 0.5/1.5 · tsmom_daily | 1.05 | 0.89 | 0.61 | 0.46 | 0.19 | 0.03 | 0.09 | 0.08 | 6.05 | 0.11 | 0.08 | -0.57 | 0.00 | 0.00 |
| dvol · - · z 1.0/2.0 · tsmom_daily | 1.31 | 1.18 | 0.72 | 0.54 | 0.22 | 0.03 | 0.11 | 0.06 | 6.18 | 0.19 | 0.06 | -0.46 | 0.00 | 0.00 |
| dvol · - · z 0.5/1.5 · tsmom_daily | 1.30 | 1.15 | 0.74 | 0.59 | 0.32 | 0.03 | 0.08 | 0.05 | 4.47 | 0.27 | 0.14 | -0.38 | 0.00 | 0.00 |
| dvol · + · z 1.0/2.0 · tsmom_tranches | 0.96 | 0.91 | 0.67 | 0.61 | 0.50 | 0.05 | 0.09 | 0.08 | 2.67 | 0.09 | 0.04 | -0.46 | 0.00 | 0.00 |
| dvol · + · z 0.5/1.5 · tsmom_tranches | 0.91 | 0.82 | 0.56 | 0.50 | 0.38 | 0.04 | 0.09 | 0.08 | 2.75 | 0.11 | 0.08 | -0.66 | 0.00 | 0.00 |
| dvol · - · z 1.0/2.0 · tsmom_tranches | 1.19 | 1.13 | 0.51 | 0.42 | 0.25 | 0.03 | 0.13 | 0.07 | 3.58 | 0.19 | 0.06 | -0.89 | 0.00 | 0.00 |
| dvol · - · z 0.5/1.5 · tsmom_tranches | 1.28 | 1.19 | 0.67 | 0.60 | 0.47 | 0.04 | 0.09 | 0.05 | 2.39 | 0.27 | 0.14 | -0.50 | 0.00 | 0.00 |
| logit long C 0.1 · breakout | 1.29 | 1.19 | 0.17 | 0.03 | -0.21 | -0.00 | 0.20 | 0.10 | 8.17 | 0.22 | 0.14 | -2.08 | 0.00 | 0.00 |
| logit long C 0.1 · tsmom_daily | 1.71 | 1.55 | 0.30 | 0.11 | -0.22 | 0.01 | 0.11 | 0.07 | 6.98 | 0.22 | 0.14 | -1.32 | 0.00 | 0.00 |
| logit long C 0.1 · tsmom_tranches | 1.50 | 1.43 | 0.20 | 0.10 | -0.08 | 0.00 | 0.12 | 0.07 | 4.00 | 0.22 | 0.14 | -1.55 | 0.00 | 0.00 |
| logit long C 1.0 · breakout | 1.35 | 1.25 | 0.17 | 0.03 | -0.21 | -0.00 | 0.20 | 0.10 | 8.20 | 0.23 | 0.13 | -2.08 | 0.00 | 0.00 |
| logit long C 1.0 · tsmom_daily | 1.71 | 1.55 | 0.32 | 0.14 | -0.19 | 0.01 | 0.11 | 0.07 | 6.76 | 0.23 | 0.13 | -1.32 | 0.00 | 0.00 |
| logit long C 1.0 · tsmom_tranches | 1.50 | 1.43 | 0.22 | 0.13 | -0.04 | 0.01 | 0.12 | 0.07 | 3.77 | 0.23 | 0.13 | -1.55 | 0.00 | 0.00 |
| logit all C 0.1 · breakout | 3.41 | 3.29 | 0.61 | 0.46 | 0.21 | 0.05 | 0.13 | 0.11 | 8.33 | 0.15 | 0.11 | -1.24 | 0.00 | 0.00 |
| logit all C 0.1 · tsmom_daily | 4.21 | 4.01 | 0.48 | 0.31 | 0.00 | 0.02 | 0.09 | 0.07 | 6.82 | 0.15 | 0.11 | -0.94 | 0.00 | 0.00 |
| logit all C 0.1 · tsmom_tranches | 4.47 | 4.37 | 0.34 | 0.25 | 0.10 | 0.02 | 0.09 | 0.08 | 3.64 | 0.15 | 0.11 | -1.25 | 0.00 | 0.00 |
| logit all C 1.0 · breakout | 3.48 | 3.31 | 0.58 | 0.44 | 0.18 | 0.04 | 0.14 | 0.11 | 8.29 | 0.15 | 0.11 | -1.26 | 0.00 | 0.00 |
| logit all C 1.0 · tsmom_daily | 4.10 | 3.85 | 0.43 | 0.26 | -0.05 | 0.02 | 0.10 | 0.07 | 6.78 | 0.15 | 0.11 | -1.06 | 0.00 | 0.00 |
| logit all C 1.0 · tsmom_tranches | 4.37 | 4.22 | 0.31 | 0.22 | 0.07 | 0.02 | 0.10 | 0.08 | 3.61 | 0.15 | 0.11 | -1.31 | 0.00 | 0.00 |
| cb_prem · + · z 1.0/2.0 · breakout · one day late | 1.54 | 1.48 | 1.00 | 0.90 | 0.71 | 0.11 | 0.15 | 0.13 | 7.02 | 0.07 | 0.00 | -1.16 | 0.00 | 0.01 |
| cb_prem · + · z 1.0/2.0 · breakout · twin | 1.45 | 1.39 | 1.03 | 0.91 | 0.69 | 0.16 | 0.21 | 0.22 | 11.15 | 0.07 | 0.00 | -0.84 | 0.00 | 0.01 |
| cb_prem · + · z 1.0/2.0 · tsmom_daily · one day late | 1.79 | 1.68 | 0.70 | 0.54 | 0.25 | 0.04 | 0.08 | 0.08 | 6.66 | 0.07 | 0.00 | -0.64 | 0.00 | 0.00 |
| cb_prem · + · z 1.0/2.0 · tsmom_daily · twin | 1.48 | 1.35 | 0.44 | 0.26 | -0.07 | 0.03 | 0.23 | 0.16 | 13.75 | 0.07 | 0.00 | -0.33 | 0.00 | 0.00 |
| cb_prem · + · z 1.0/2.0 · tsmom_tranches · one day late | 1.93 | 1.88 | 0.70 | 0.63 | 0.50 | 0.05 | 0.08 | 0.08 | 3.11 | 0.07 | 0.00 | -0.59 | 0.00 | 0.00 |
| cb_prem · + · z 1.0/2.0 · tsmom_tranches · twin | 1.66 | 1.60 | 0.43 | 0.35 | 0.20 | 0.04 | 0.23 | 0.16 | 6.29 | 0.07 | 0.00 | -0.64 | 0.00 | 0.00 |
| kr_prem · - · z 1.0/2.0 · breakout · one day late | 1.33 | 1.26 | 1.08 | 0.98 | 0.79 | 0.12 | 0.12 | 0.12 | 6.53 | 0.19 | 0.00 | -1.12 | 0.00 | 0.01 |
| kr_prem · - · z 1.0/2.0 · breakout · twin | 1.19 | 1.12 | 1.12 | 1.00 | 0.79 | 0.17 | 0.16 | 0.20 | 10.25 | 0.19 | 0.00 | -0.73 | 0.00 | 0.01 |
| kr_prem · - · z 1.0/2.0 · tsmom_daily · one day late | 1.62 | 1.50 | 0.72 | 0.57 | 0.30 | 0.04 | 0.07 | 0.08 | 6.15 | 0.19 | 0.00 | -0.51 | 0.00 | 0.00 |
| kr_prem · - · z 1.0/2.0 · tsmom_daily · twin | 1.28 | 1.14 | 0.42 | 0.24 | -0.08 | 0.02 | 0.22 | 0.15 | 12.66 | 0.19 | 0.00 | -0.38 | 0.00 | 0.00 |
| kr_prem · - · z 1.0/2.0 · tsmom_tranches · one day late | 1.75 | 1.70 | 0.71 | 0.65 | 0.53 | 0.05 | 0.08 | 0.08 | 2.82 | 0.19 | 0.00 | -0.59 | 0.00 | 0.00 |
| kr_prem · - · z 1.0/2.0 · tsmom_tranches · twin | 1.41 | 1.35 | 0.48 | 0.40 | 0.26 | 0.05 | 0.20 | 0.15 | 5.74 | 0.19 | 0.00 | -0.42 | 0.00 | 0.00 |
| stable_30 · - · z 0.5/1.5 · breakout · one day late | 1.43 | 1.37 | 1.12 | 1.04 | 0.89 | 0.15 | 0.14 | 0.12 | 6.10 | 0.27 | 0.11 | -0.79 | 0.00 | 0.01 |
| stable_30 · - · z 0.5/1.5 · breakout · twin | 1.37 | 1.32 | 1.18 | 1.08 | 0.90 | 0.21 | 0.18 | 0.20 | 9.60 | 0.27 | 0.11 | -0.27 | 0.00 | 0.01 |
| stable_30 · - · z 0.5/1.5 · tsmom_daily · one day late | 1.83 | 1.72 | 0.68 | 0.53 | 0.27 | 0.04 | 0.09 | 0.08 | 6.14 | 0.27 | 0.11 | -0.66 | 0.00 | 0.00 |
| stable_30 · - · z 0.5/1.5 · tsmom_daily · twin | 1.45 | 1.33 | 0.54 | 0.37 | 0.06 | 0.04 | 0.19 | 0.15 | 12.63 | 0.27 | 0.11 | 0.13 | 0.01 | 0.00 |
| stable_30 · - · z 0.5/1.5 · tsmom_tranches · one day late | 1.85 | 1.81 | 0.74 | 0.68 | 0.58 | 0.06 | 0.09 | 0.08 | 2.71 | 0.27 | 0.11 | -0.46 | 0.00 | 0.00 |
| stable_30 · - · z 0.5/1.5 · tsmom_tranches · twin | 1.56 | 1.51 | 0.63 | 0.56 | 0.44 | 0.08 | 0.18 | 0.16 | 5.53 | 0.27 | 0.11 | 0.36 | 0.01 | 0.00 |
| stable_7 · - · z 1.0/2.0 · breakout · one day late | 1.33 | 1.27 | 1.21 | 1.13 | 0.98 | 0.18 | 0.16 | 0.14 | 6.66 | 0.16 | 0.01 | -0.67 | 0.00 | 0.02 |
| stable_7 · - · z 1.0/2.0 · breakout · twin | 1.37 | 1.30 | 1.19 | 1.08 | 0.89 | 0.22 | 0.20 | 0.23 | 11.02 | 0.16 | 0.01 | -0.11 | 0.00 | 0.01 |
| stable_7 · - · z 1.0/2.0 · tsmom_daily · one day late | 1.72 | 1.60 | 0.75 | 0.60 | 0.33 | 0.05 | 0.09 | 0.09 | 6.58 | 0.16 | 0.01 | -0.76 | 0.00 | 0.00 |
| stable_7 · - · z 1.0/2.0 · tsmom_daily · twin | 1.42 | 1.28 | 0.58 | 0.40 | 0.08 | 0.05 | 0.22 | 0.16 | 13.82 | 0.16 | 0.01 | 0.67 | 0.03 | 0.00 |
| stable_7 · - · z 1.0/2.0 · tsmom_tranches · one day late | 1.81 | 1.76 | 0.74 | 0.68 | 0.56 | 0.06 | 0.09 | 0.09 | 2.97 | 0.16 | 0.01 | -0.96 | 0.00 | 0.00 |
| stable_7 · - · z 1.0/2.0 · tsmom_tranches · twin | 1.55 | 1.49 | 0.60 | 0.52 | 0.38 | 0.07 | 0.23 | 0.17 | 6.20 | 0.16 | 0.01 | 0.45 | 0.02 | 0.00 |
| funding · - · z 1.0/2.0 · breakout · one day late | 1.55 | 1.49 | 1.12 | 1.03 | 0.88 | 0.16 | 0.18 | 0.13 | 6.54 | 0.11 | 0.05 | -1.01 | 0.00 | 0.01 |
| funding · - · z 1.0/2.0 · breakout · twin | 1.56 | 1.50 | 1.06 | 0.95 | 0.76 | 0.19 | 0.24 | 0.22 | 10.94 | 0.11 | 0.05 | -0.86 | 0.00 | 0.01 |
| funding · - · z 1.0/2.0 · tsmom_daily · one day late | 1.71 | 1.60 | 0.67 | 0.53 | 0.27 | 0.04 | 0.12 | 0.08 | 6.11 | 0.11 | 0.05 | -0.56 | 0.00 | 0.00 |
| funding · - · z 1.0/2.0 · tsmom_daily · twin | 1.49 | 1.36 | 0.39 | 0.22 | -0.08 | 0.02 | 0.24 | 0.15 | 12.86 | 0.11 | 0.05 | -0.48 | 0.00 | 0.00 |
| funding · - · z 1.0/2.0 · tsmom_tranches · one day late | 1.84 | 1.79 | 0.58 | 0.51 | 0.39 | 0.04 | 0.13 | 0.08 | 3.02 | 0.11 | 0.05 | -0.96 | 0.00 | 0.00 |
| funding · - · z 1.0/2.0 · tsmom_tranches · twin | 1.64 | 1.58 | 0.37 | 0.29 | 0.15 | 0.03 | 0.23 | 0.16 | 6.20 | 0.11 | 0.05 | -0.89 | 0.00 | 0.00 |
| basis · - · z 0.5/1.5 · breakout · one day late | 1.54 | 1.48 | 1.29 | 1.22 | 1.09 | 0.19 | 0.15 | 0.13 | 5.47 | 0.44 | 0.00 | 0.02 | 0.00 | 0.02 |
| basis · - · z 0.5/1.5 · breakout · twin | 1.50 | 1.44 | 1.34 | 1.24 | 1.08 | 0.25 | 0.20 | 0.21 | 9.09 | 0.44 | 0.00 | 0.53 | 0.03 | 0.03 |
| basis · - · z 0.5/1.5 · tsmom_daily · one day late | 1.73 | 1.62 | 0.83 | 0.69 | 0.44 | 0.05 | 0.09 | 0.08 | 5.64 | 0.44 | 0.00 | -0.03 | 0.00 | 0.00 |
| basis · - · z 0.5/1.5 · tsmom_daily · twin | 1.41 | 1.28 | 0.72 | 0.56 | 0.27 | 0.07 | 0.19 | 0.15 | 11.60 | 0.44 | 0.00 | 0.81 | 0.08 | 0.00 |
| basis · + · z 1.0/2.0 · tsmom_tranches · one day late | 1.89 | 1.83 | 0.42 | 0.35 | 0.22 | 0.02 | 0.08 | 0.07 | 2.88 | 0.07 | 0.05 | -0.91 | 0.00 | 0.00 |
| basis · + · z 1.0/2.0 · tsmom_tranches · twin | 1.52 | 1.45 | 0.23 | 0.14 | -0.01 | 0.01 | 0.20 | 0.14 | 5.78 | 0.07 | 0.05 | -0.75 | 0.00 | 0.00 |
| oi_7 · - · z 0.5/1.5 · breakout · one day late | 1.20 | 1.02 | 1.10 | 0.97 | 0.75 | 0.14 | 0.18 | 0.13 | 9.36 | 0.15 | 0.06 | -1.02 | 0.00 | 0.01 |
| oi_7 · - · z 0.5/1.5 · breakout · twin | 1.15 | 0.97 | 0.89 | 0.73 | 0.46 | 0.13 | 0.23 | 0.22 | 14.89 | 0.15 | 0.06 | -1.45 | 0.00 | 0.00 |
| oi_7 · + · z 1.0/2.0 · tsmom_daily · one day late | 1.46 | 1.29 | 0.79 | 0.60 | 0.27 | 0.05 | 0.09 | 0.08 | 7.77 | 0.10 | 0.01 | -0.36 | 0.00 | 0.00 |
| oi_7 · + · z 1.0/2.0 · tsmom_daily · twin | 1.20 | 1.02 | 0.46 | 0.25 | -0.13 | 0.03 | 0.23 | 0.16 | 16.19 | 0.10 | 0.01 | -0.45 | 0.00 | 0.00 |
| oi_7 · + · z 1.0/2.0 · tsmom_tranches · one day late | 1.26 | 1.17 | 0.79 | 0.69 | 0.52 | 0.06 | 0.09 | 0.08 | 4.27 | 0.10 | 0.01 | -0.39 | 0.00 | 0.00 |
| oi_7 · + · z 1.0/2.0 · tsmom_tranches · twin | 1.16 | 1.06 | 0.49 | 0.38 | 0.19 | 0.05 | 0.23 | 0.16 | 8.53 | 0.10 | 0.01 | -0.58 | 0.00 | 0.00 |
| ls_ratio · + · z 1.0/2.0 · breakout · one day late | 1.22 | 1.15 | 1.34 | 1.26 | 1.12 | 0.20 | 0.16 | 0.14 | 5.94 | 0.19 | 0.03 | 0.35 | 0.01 | 0.03 |
| ls_ratio · + · z 1.0/2.0 · breakout · twin | 1.01 | 0.92 | 1.38 | 1.28 | 1.11 | 0.26 | 0.21 | 0.23 | 9.58 | 0.18 | 0.03 | 0.69 | 0.03 | 0.03 |
| ls_ratio · + · z 1.0/2.0 · tsmom_daily · one day late | 1.54 | 1.41 | 0.88 | 0.74 | 0.49 | 0.06 | 0.09 | 0.08 | 5.83 | 0.19 | 0.03 | 0.38 | 0.02 | 0.00 |
| ls_ratio · + · z 1.0/2.0 · tsmom_daily · twin | 1.29 | 1.13 | 0.64 | 0.48 | 0.18 | 0.06 | 0.23 | 0.16 | 12.42 | 0.18 | 0.03 | 0.58 | 0.04 | 0.00 |
| ls_ratio · + · z 0.5/1.5 · tsmom_tranches · one day late | 1.37 | 1.30 | 1.01 | 0.95 | 0.84 | 0.08 | 0.08 | 0.08 | 2.67 | 0.25 | 0.10 | 0.54 | 0.03 | 0.01 |
| ls_ratio · + · z 0.5/1.5 · tsmom_tranches · twin | 1.26 | 1.19 | 0.62 | 0.55 | 0.42 | 0.07 | 0.20 | 0.15 | 5.56 | 0.24 | 0.10 | 0.10 | 0.00 | 0.00 |
| liq · + · z 0.5/1.5 · breakout · one day late | 1.52 | 1.40 | 1.08 | 0.96 | 0.77 | 0.14 | 0.16 | 0.13 | 8.43 | 0.14 | 0.04 | -1.39 | 0.00 | 0.01 |
| liq · + · z 0.5/1.5 · breakout · twin | 1.36 | 1.23 | 1.03 | 0.90 | 0.66 | 0.17 | 0.20 | 0.22 | 13.11 | 0.14 | 0.04 | -0.99 | 0.00 | 0.01 |
| liq · - · z 1.0/2.0 · tsmom_daily · one day late | 1.59 | 1.44 | 0.75 | 0.59 | 0.32 | 0.05 | 0.08 | 0.08 | 6.50 | 0.08 | 0.00 | -0.48 | 0.00 | 0.00 |
| liq · - · z 1.0/2.0 · tsmom_daily · twin | 1.25 | 1.08 | 0.40 | 0.22 | -0.10 | 0.02 | 0.24 | 0.16 | 13.74 | 0.08 | 0.00 | -0.71 | 0.00 | 0.00 |
| liq · - · z 1.0/2.0 · tsmom_tranches · one day late | 1.36 | 1.29 | 0.70 | 0.64 | 0.53 | 0.06 | 0.09 | 0.09 | 2.97 | 0.08 | 0.00 | -0.85 | 0.00 | 0.00 |
| liq · - · z 1.0/2.0 · tsmom_tranches · twin | 1.21 | 1.13 | 0.45 | 0.37 | 0.24 | 0.05 | 0.23 | 0.17 | 6.02 | 0.08 | 0.00 | -0.82 | 0.00 | 0.00 |
| dvol · - · z 0.5/1.5 · breakout · one day late | 1.14 | 1.04 | 1.06 | 0.98 | 0.83 | 0.13 | 0.16 | 0.10 | 5.39 | 0.27 | 0.14 | -0.80 | 0.00 | 0.01 |
| dvol · - · z 0.5/1.5 · breakout · twin | 1.08 | 0.96 | 0.92 | 0.81 | 0.62 | 0.13 | 0.20 | 0.16 | 9.17 | 0.27 | 0.14 | -0.91 | 0.00 | 0.00 |
| dvol · - · z 1.0/2.0 · tsmom_daily · one day late | 1.28 | 1.15 | 0.76 | 0.59 | 0.28 | 0.04 | 0.09 | 0.06 | 6.05 | 0.19 | 0.06 | -0.41 | 0.00 | 0.00 |
| dvol · - · z 1.0/2.0 · tsmom_daily · twin | 1.18 | 1.04 | 0.27 | 0.06 | -0.30 | -0.00 | 0.24 | 0.12 | 13.02 | 0.19 | 0.06 | -0.61 | 0.00 | 0.00 |
| dvol · - · z 0.5/1.5 · tsmom_tranches · one day late | 1.34 | 1.25 | 0.64 | 0.56 | 0.44 | 0.04 | 0.10 | 0.05 | 2.37 | 0.27 | 0.14 | -0.56 | 0.00 | 0.00 |
| dvol · - · z 0.5/1.5 · tsmom_tranches · twin | 1.34 | 1.24 | 0.19 | 0.11 | -0.04 | 0.01 | 0.23 | 0.10 | 5.04 | 0.27 | 0.14 | -0.66 | 0.00 | 0.00 |
| logit long C 0.1 · breakout · one day late | 1.37 | 1.27 | -0.06 | -0.20 | -0.45 | -0.03 | 0.23 | 0.10 | 8.04 | 0.22 | 0.14 | -2.19 | 0.00 | 0.00 |
| logit long C 0.1 · breakout · twin | 1.00 | 0.89 | 0.43 | 0.27 | -0.01 | 0.03 | 0.27 | 0.17 | 12.76 | 0.22 | 0.14 | -1.68 | 0.00 | 0.00 |
| logit long C 0.1 · tsmom_daily · one day late | 1.56 | 1.38 | 0.23 | 0.04 | -0.29 | 0.00 | 0.11 | 0.06 | 6.90 | 0.22 | 0.14 | -1.41 | 0.00 | 0.00 |
| logit long C 0.1 · tsmom_daily · twin | 1.43 | 1.25 | 0.07 | -0.15 | -0.53 | -0.03 | 0.29 | 0.13 | 14.18 | 0.22 | 0.14 | -1.06 | 0.00 | 0.00 |
| logit long C 0.1 · tsmom_tranches · one day late | 1.41 | 1.33 | 0.19 | 0.09 | -0.08 | 0.00 | 0.13 | 0.07 | 4.04 | 0.22 | 0.14 | -1.54 | 0.00 | 0.00 |
| logit long C 0.1 · tsmom_tranches · twin | 1.43 | 1.35 | 0.11 | -0.00 | -0.20 | -0.01 | 0.26 | 0.13 | 7.79 | 0.22 | 0.14 | -1.18 | 0.00 | 0.00 |

### Per year (Sharpe at 35 bps)

| variant | y2021 | y2022 | y2023 | y2024 | y2025 | y2026 |
|---|---|---|---|---|---|---|
| breakout_top10 live alone | 2.38 | -0.61 | 1.93 | 2.19 | 0.32 | -0.02 |
| breakout_top10 twin alone | 2.43 | -0.84 | 1.72 | 1.84 | 0.46 | 0.42 |
| tsmom_top20 live alone | 1.99 | 0.00 | 1.68 | 1.56 | -0.35 | 0.90 |
| tsmom_top20 twin alone | 2.12 | 0.00 | 1.22 | 0.37 | -0.29 | 1.18 |
| tsmom_tranches live alone | 2.51 | 0.84 | 1.52 | 1.67 | -0.08 | 0.62 |
| tsmom_tranches twin alone | 2.41 | 0.89 | 1.30 | 0.59 | 0.08 | 0.99 |
| cb_prem · + · z 1.0/2.0 · breakout | 2.61 | -0.61 | 1.90 | 1.74 | 0.58 | -0.02 |
| cb_prem · + · z 0.5/1.5 · breakout | 2.17 | -0.59 | 1.96 | 1.75 | 0.04 | 0.14 |
| cb_prem · - · z 1.0/2.0 · breakout | 2.26 | -0.65 | 1.95 | 2.12 | 0.38 | -0.12 |
| cb_prem · - · z 0.5/1.5 · breakout | 2.25 | -0.54 | 1.74 | 2.15 | 0.38 | -0.55 |
| cb_prem · + · z 1.0/2.0 · tsmom_daily | 2.15 | 0.00 | 1.56 | 1.08 | -0.18 | 0.90 |
| cb_prem · + · z 0.5/1.5 · tsmom_daily | 1.97 | 0.00 | 1.55 | 0.76 | -0.54 | 1.04 |
| cb_prem · - · z 1.0/2.0 · tsmom_daily | 1.85 | 0.00 | 1.70 | 1.56 | -0.26 | 0.90 |
| cb_prem · - · z 0.5/1.5 · tsmom_daily | 1.82 | 0.00 | 1.64 | 1.65 | -0.19 | 0.60 |
| cb_prem · + · z 1.0/2.0 · tsmom_tranches | 2.75 | 0.84 | 1.43 | 1.12 | -0.08 | 0.62 |
| cb_prem · + · z 0.5/1.5 · tsmom_tranches | 2.44 | 0.84 | 1.41 | 0.81 | -0.16 | 0.77 |
| cb_prem · - · z 1.0/2.0 · tsmom_tranches | 2.34 | 0.84 | 1.57 | 1.67 | -0.07 | 0.62 |
| cb_prem · - · z 0.5/1.5 · tsmom_tranches | 2.34 | 0.83 | 1.51 | 1.72 | -0.04 | 0.53 |
| kr_prem · + · z 1.0/2.0 · breakout | 2.29 | -0.63 | 1.59 | 2.36 | 0.34 | -0.02 |
| kr_prem · + · z 0.5/1.5 · breakout | 2.28 | -0.58 | 1.77 | 2.09 | 0.40 | -0.02 |
| kr_prem · - · z 1.0/2.0 · breakout | 1.77 | -0.77 | 1.79 | 2.06 | 0.28 | 0.05 |
| kr_prem · - · z 0.5/1.5 · breakout | 1.67 | -0.97 | 1.63 | 1.73 | -0.33 | 0.12 |
| kr_prem · + · z 1.0/2.0 · tsmom_daily | 1.63 | 0.00 | 1.41 | 1.55 | -0.35 | 0.90 |
| kr_prem · + · z 0.5/1.5 · tsmom_daily | 1.24 | 0.00 | 1.43 | 0.96 | -0.31 | 0.90 |
| kr_prem · - · z 1.0/2.0 · tsmom_daily | 1.59 | 0.00 | 1.69 | 1.29 | -0.43 | 0.90 |
| kr_prem · - · z 0.5/1.5 · tsmom_daily | 1.70 | 0.00 | 1.45 | 1.30 | -0.57 | 0.72 |
| kr_prem · + · z 1.0/2.0 · tsmom_tranches | 2.10 | 0.84 | 1.07 | 1.70 | -0.08 | 0.62 |
| kr_prem · + · z 0.5/1.5 · tsmom_tranches | 1.72 | 0.84 | 1.14 | 1.12 | -0.02 | 0.62 |
| kr_prem · - · z 1.0/2.0 · tsmom_tranches | 2.12 | 0.84 | 1.51 | 1.40 | -0.18 | 0.62 |
| kr_prem · - · z 0.5/1.5 · tsmom_tranches | 2.15 | 0.84 | 1.39 | 1.35 | -0.48 | 0.45 |
| stable_30 · + · z 1.0/2.0 · breakout | 2.21 | -0.61 | 1.71 | 1.79 | 0.32 | -0.02 |
| stable_30 · + · z 0.5/1.5 · breakout | 2.56 | -0.61 | 0.89 | 1.46 | 0.34 | -0.02 |
| stable_30 · - · z 1.0/2.0 · breakout | 2.02 | -0.99 | 1.93 | 2.15 | 0.30 | 0.15 |
| stable_30 · - · z 0.5/1.5 · breakout | 1.93 | -0.60 | 1.93 | 2.22 | 0.22 | -0.74 |
| stable_30 · + · z 1.0/2.0 · tsmom_daily | 1.87 | 0.00 | 1.39 | 0.91 | -0.36 | 0.90 |
| stable_30 · + · z 0.5/1.5 · tsmom_daily | 1.63 | 0.00 | 1.01 | 0.80 | -0.31 | 0.90 |
| stable_30 · - · z 1.0/2.0 · tsmom_daily | 1.94 | 0.00 | 1.68 | 1.46 | -0.35 | 0.90 |
| stable_30 · - · z 0.5/1.5 · tsmom_daily | 2.28 | 0.00 | 1.68 | 1.59 | -0.29 | 0.52 |
| stable_30 · + · z 1.0/2.0 · tsmom_tranches | 2.39 | 0.84 | 1.16 | 1.06 | -0.09 | 0.62 |
| stable_30 · + · z 0.5/1.5 · tsmom_tranches | 2.17 | 0.84 | 0.72 | 0.83 | -0.01 | 0.62 |
| stable_30 · - · z 1.0/2.0 · tsmom_tranches | 2.39 | 0.84 | 1.52 | 1.57 | -0.06 | 0.62 |
| stable_30 · - · z 0.5/1.5 · tsmom_tranches | 2.59 | 0.84 | 1.52 | 1.69 | -0.01 | 0.44 |
| stable_7 · + · z 1.0/2.0 · breakout | 2.07 | -0.58 | 2.08 | -0.18 | 0.36 | -0.10 |
| stable_7 · + · z 0.5/1.5 · breakout | 2.42 | -0.56 | 1.54 | 0.04 | 0.27 | -0.10 |
| stable_7 · - · z 1.0/2.0 · breakout | 2.26 | -0.58 | 1.85 | 2.12 | 0.44 | 0.00 |
| stable_7 · - · z 0.5/1.5 · breakout | 2.15 | -0.62 | 1.72 | 2.22 | 0.30 | -0.01 |
| stable_7 · + · z 1.0/2.0 · tsmom_daily | 1.76 | 0.00 | 1.59 | -0.25 | -0.35 | 0.80 |
| stable_7 · + · z 0.5/1.5 · tsmom_daily | 1.95 | 0.00 | 0.86 | -0.05 | -0.45 | 0.88 |
| stable_7 · - · z 1.0/2.0 · tsmom_daily | 2.10 | 0.00 | 1.60 | 1.64 | -0.24 | 0.83 |
| stable_7 · - · z 0.5/1.5 · tsmom_daily | 2.13 | 0.00 | 1.53 | 1.68 | -0.24 | 0.85 |
| stable_7 · + · z 1.0/2.0 · tsmom_tranches | 2.23 | 0.84 | 1.54 | -0.23 | -0.11 | 0.51 |
| stable_7 · + · z 0.5/1.5 · tsmom_tranches | 2.50 | 0.84 | 0.69 | -0.02 | -0.03 | 0.58 |
| stable_7 · - · z 1.0/2.0 · tsmom_tranches | 2.53 | 0.83 | 1.46 | 1.74 | -0.01 | 0.54 |
| stable_7 · - · z 0.5/1.5 · tsmom_tranches | 2.58 | 0.64 | 1.40 | 1.76 | 0.00 | 0.47 |
| funding · + · z 1.0/2.0 · breakout | 1.72 | -0.61 | 1.93 | 2.26 | 0.32 | 0.08 |
| funding · + · z 0.5/1.5 · breakout | 1.64 | -0.61 | 2.14 | 2.40 | 0.70 | 0.34 |
| funding · - · z 1.0/2.0 · breakout | 2.41 | -0.22 | 1.86 | 2.26 | -0.54 | 0.10 |
| funding · - · z 0.5/1.5 · breakout | 2.40 | -0.56 | 1.88 | 2.23 | -0.74 | 0.12 |
| funding · + · z 1.0/2.0 · tsmom_daily | 1.33 | 0.00 | 1.68 | 1.51 | -0.35 | 1.35 |
| funding · + · z 0.5/1.5 · tsmom_daily | 1.14 | 0.00 | 1.83 | 1.58 | -0.08 | 1.34 |
| funding · - · z 1.0/2.0 · tsmom_daily | 2.10 | 0.00 | 1.51 | 1.74 | -0.86 | 1.01 |
| funding · - · z 0.5/1.5 · tsmom_daily | 2.12 | 0.00 | 1.58 | 1.75 | -1.28 | 0.72 |
| funding · + · z 1.0/2.0 · tsmom_tranches | 1.87 | 0.84 | 1.52 | 1.65 | -0.08 | 1.07 |
| funding · + · z 0.5/1.5 · tsmom_tranches | 1.72 | 0.84 | 1.59 | 1.67 | 0.33 | 1.09 |
| funding · - · z 1.0/2.0 · tsmom_tranches | 2.62 | 0.84 | 1.36 | 1.83 | -0.82 | 0.76 |
| funding · - · z 0.5/1.5 · tsmom_tranches | 2.65 | 0.84 | 1.45 | 1.85 | -1.19 | 0.34 |
| basis · + · z 1.0/2.0 · breakout | 2.18 | -0.61 | 1.97 | 2.00 | 0.32 | -0.35 |
| basis · + · z 0.5/1.5 · breakout | 2.70 | -0.59 | 1.13 | 1.96 | 0.40 | -0.77 |
| basis · - · z 1.0/2.0 · breakout | 2.39 | -0.57 | 1.93 | 2.21 | 0.32 | -0.06 |
| basis · - · z 0.5/1.5 · breakout | 2.36 | -0.70 | 1.93 | 2.43 | 0.34 | 0.19 |
| basis · + · z 1.0/2.0 · tsmom_daily | 1.65 | 0.00 | 1.52 | 0.74 | -0.35 | 0.97 |
| basis · + · z 0.5/1.5 · tsmom_daily | 1.79 | 0.00 | 1.00 | 0.80 | -0.34 | 0.55 |
| basis · - · z 1.0/2.0 · tsmom_daily | 1.99 | 0.00 | 1.68 | 1.56 | -0.35 | 0.90 |
| basis · - · z 0.5/1.5 · tsmom_daily | 2.00 | 0.00 | 1.68 | 1.92 | -0.39 | 0.86 |
| basis · + · z 1.0/2.0 · tsmom_tranches | 2.27 | 0.84 | 1.19 | 0.80 | -0.08 | 0.67 |
| basis · + · z 0.5/1.5 · tsmom_tranches | 2.48 | 0.84 | 0.60 | 0.83 | -0.06 | 0.24 |
| basis · - · z 1.0/2.0 · tsmom_tranches | 2.52 | 0.84 | 1.52 | 1.67 | -0.11 | 0.62 |
| basis · - · z 0.5/1.5 · tsmom_tranches | 2.52 | 0.84 | 1.52 | 2.02 | -0.14 | 0.57 |
| oi_7 · + · z 1.0/2.0 · breakout | 2.38 | -0.72 | 1.96 | 2.12 | -0.01 | 0.01 |
| oi_7 · + · z 0.5/1.5 · breakout | 2.38 | -0.74 | 1.54 | 2.29 | -0.19 | -0.01 |
| oi_7 · - · z 1.0/2.0 · breakout | 2.38 | -0.55 | 1.81 | 1.97 | 0.28 | 0.01 |
| oi_7 · - · z 0.5/1.5 · breakout | 2.38 | -0.38 | 1.87 | 1.81 | -0.04 | -0.14 |
| oi_7 · + · z 1.0/2.0 · tsmom_daily | 1.99 | 0.00 | 1.69 | 1.48 | -0.39 | 0.90 |
| oi_7 · + · z 0.5/1.5 · tsmom_daily | 1.99 | 0.00 | 1.36 | 1.65 | -0.34 | 0.84 |
| oi_7 · - · z 1.0/2.0 · tsmom_daily | 1.99 | 0.00 | 1.55 | 1.18 | -0.50 | 0.95 |
| oi_7 · - · z 0.5/1.5 · tsmom_daily | 1.99 | 0.00 | 1.55 | 0.86 | -0.94 | 0.65 |
| oi_7 · + · z 1.0/2.0 · tsmom_tranches | 2.51 | 0.84 | 1.51 | 1.63 | -0.18 | 0.62 |
| oi_7 · + · z 0.5/1.5 · tsmom_tranches | 2.51 | 0.84 | 1.17 | 1.72 | -0.19 | 0.53 |
| oi_7 · - · z 1.0/2.0 · tsmom_tranches | 2.51 | 0.84 | 1.32 | 1.15 | -0.26 | 0.67 |
| oi_7 · - · z 0.5/1.5 · tsmom_tranches | 2.51 | 0.84 | 1.34 | 0.82 | -0.71 | 0.34 |
| ls_ratio · + · z 1.0/2.0 · breakout | 2.38 | -0.62 | 1.99 | 2.68 | 0.36 | -0.02 |
| ls_ratio · + · z 0.5/1.5 · breakout | 2.38 | -0.68 | 1.98 | 2.37 | 0.38 | -0.05 |
| ls_ratio · - · z 1.0/2.0 · breakout | 2.38 | -0.29 | 1.53 | 2.06 | -0.55 | 0.04 |
| ls_ratio · - · z 0.5/1.5 · breakout | 2.38 | -0.21 | 1.26 | 1.90 | -1.63 | 0.36 |
| ls_ratio · + · z 1.0/2.0 · tsmom_daily | 1.99 | 0.00 | 1.76 | 1.95 | -0.26 | 0.90 |
| ls_ratio · + · z 0.5/1.5 · tsmom_daily | 1.99 | 0.00 | 1.70 | 1.81 | -0.27 | 0.90 |
| ls_ratio · - · z 1.0/2.0 · tsmom_daily | 1.99 | 0.00 | 1.41 | 1.41 | -0.86 | 0.90 |
| ls_ratio · - · z 0.5/1.5 · tsmom_daily | 1.99 | 0.00 | 1.25 | 1.30 | -1.36 | 0.91 |
| ls_ratio · + · z 1.0/2.0 · tsmom_tranches | 2.51 | 0.84 | 1.60 | 2.07 | 0.04 | 0.62 |
| ls_ratio · + · z 0.5/1.5 · tsmom_tranches | 2.51 | 0.84 | 1.62 | 1.95 | 0.00 | 0.62 |
| ls_ratio · - · z 1.0/2.0 · tsmom_tranches | 2.51 | 0.84 | 1.23 | 1.54 | -0.55 | 0.62 |
| ls_ratio · - · z 0.5/1.5 · tsmom_tranches | 2.51 | 0.84 | 1.21 | 1.37 | -1.01 | 0.65 |
| liq · + · z 1.0/2.0 · breakout | 2.38 | -0.59 | 1.75 | 1.99 | 0.36 | 0.03 |
| liq · + · z 0.5/1.5 · breakout | 2.38 | -0.48 | 1.79 | 1.78 | 0.37 | 0.11 |
| liq · - · z 1.0/2.0 · breakout | 2.38 | -0.59 | 1.73 | 1.87 | 0.18 | -0.18 |
| liq · - · z 0.5/1.5 · breakout | 2.38 | -0.66 | 1.34 | 1.93 | -0.32 | -0.54 |
| liq · + · z 1.0/2.0 · tsmom_daily | 1.99 | 0.00 | 1.54 | 1.35 | -0.34 | 0.90 |
| liq · + · z 0.5/1.5 · tsmom_daily | 1.99 | 0.00 | 1.47 | 1.13 | -0.16 | 0.89 |
| liq · - · z 1.0/2.0 · tsmom_daily | 1.99 | 0.00 | 1.69 | 1.28 | -0.31 | 0.90 |
| liq · - · z 0.5/1.5 · tsmom_daily | 1.99 | 0.00 | 1.31 | 1.34 | -0.23 | 0.62 |
| liq · + · z 1.0/2.0 · tsmom_tranches | 2.51 | 0.84 | 1.36 | 1.31 | -0.17 | 0.62 |
| liq · + · z 0.5/1.5 · tsmom_tranches | 2.51 | 0.84 | 1.33 | 1.04 | -0.05 | 0.60 |
| liq · - · z 1.0/2.0 · tsmom_tranches | 2.51 | 0.84 | 1.56 | 1.37 | -0.09 | 0.62 |
| liq · - · z 0.5/1.5 · tsmom_tranches | 2.51 | 0.84 | 1.12 | 1.33 | -0.16 | 0.35 |
| dvol · + · z 1.0/2.0 · breakout | 2.38 | -0.61 | 2.04 | 2.32 | 0.31 | 0.14 |
| dvol · + · z 0.5/1.5 · breakout | 2.38 | -0.61 | 2.04 | 2.24 | 0.32 | 0.22 |
| dvol · - · z 1.0/2.0 · breakout | 2.38 | -1.01 | 1.89 | 2.19 | -1.43 | -0.15 |
| dvol · - · z 0.5/1.5 · breakout | 2.49 | -0.14 | 1.81 | 2.02 | -0.92 | -0.31 |
| dvol · + · z 1.0/2.0 · tsmom_daily | 1.99 | 0.00 | 1.71 | 1.47 | -0.36 | 0.90 |
| dvol · + · z 0.5/1.5 · tsmom_daily | 1.99 | 0.00 | 1.60 | 1.31 | -0.36 | 0.90 |
| dvol · - · z 1.0/2.0 · tsmom_daily | 1.99 | 0.00 | 2.13 | 1.56 | -1.58 | 0.79 |
| dvol · - · z 0.5/1.5 · tsmom_daily | 2.12 | 0.00 | 1.95 | 1.46 | -1.29 | 0.36 |
| dvol · + · z 1.0/2.0 · tsmom_tranches | 2.51 | 0.84 | 1.55 | 1.63 | -0.09 | 0.62 |
| dvol · + · z 0.5/1.5 · tsmom_tranches | 2.51 | 0.84 | 1.43 | 1.30 | -0.07 | 0.62 |
| dvol · - · z 1.0/2.0 · tsmom_tranches | 2.51 | 0.84 | 1.97 | 1.67 | -1.42 | 0.29 |
| dvol · - · z 0.5/1.5 · tsmom_tranches | 2.65 | 0.98 | 1.90 | 1.55 | -1.24 | -0.00 |
| logit long C 0.1 · breakout | 2.38 | -0.96 | 1.66 | 0.36 | -0.57 | -0.11 |
| logit long C 0.1 · tsmom_daily | 1.99 | 0.00 | 1.73 | 0.36 | -0.62 | 0.75 |
| logit long C 0.1 · tsmom_tranches | 2.51 | 0.84 | 1.60 | 0.45 | -0.55 | 0.54 |
| logit long C 1.0 · breakout | 2.38 | -0.89 | 1.70 | 0.38 | -0.59 | -0.13 |
| logit long C 1.0 · tsmom_daily | 1.99 | 0.00 | 1.73 | 0.36 | -0.55 | 0.75 |
| logit long C 1.0 · tsmom_tranches | 2.51 | 0.84 | 1.60 | 0.46 | -0.48 | 0.54 |
| logit all C 0.1 · breakout | 2.38 | -0.61 | 1.69 | 0.75 | 0.28 | 0.23 |
| logit all C 0.1 · tsmom_daily | 1.99 | 0.00 | 1.23 | 0.61 | -0.31 | 0.90 |
| logit all C 0.1 · tsmom_tranches | 2.51 | 0.84 | 1.16 | 0.64 | -0.27 | 0.62 |
| logit all C 1.0 · breakout | 2.38 | -0.61 | 1.68 | 0.69 | 0.26 | 0.25 |
| logit all C 1.0 · tsmom_daily | 1.99 | 0.00 | 1.14 | 0.56 | -0.40 | 0.90 |
| logit all C 1.0 · tsmom_tranches | 2.51 | 0.84 | 1.04 | 0.60 | -0.30 | 0.62 |
| cb_prem · + · z 1.0/2.0 · breakout · one day late | 2.57 | -0.61 | 1.88 | 1.68 | 0.50 | -0.02 |
| cb_prem · + · z 1.0/2.0 · breakout · twin | 2.58 | -0.84 | 1.72 | 1.38 | 0.74 | 0.42 |
| cb_prem · + · z 1.0/2.0 · tsmom_daily · one day late | 2.14 | 0.00 | 1.52 | 1.09 | -0.15 | 0.90 |
| cb_prem · + · z 1.0/2.0 · tsmom_daily · twin | 2.35 | 0.00 | 1.14 | 0.03 | -0.12 | 1.18 |
| cb_prem · + · z 1.0/2.0 · tsmom_tranches · one day late | 2.71 | 0.84 | 1.41 | 1.12 | 0.18 | 0.62 |
| cb_prem · + · z 1.0/2.0 · tsmom_tranches · twin | 2.72 | 0.89 | 1.22 | 0.24 | 0.10 | 0.99 |
| kr_prem · - · z 1.0/2.0 · breakout · one day late | 1.78 | -0.63 | 1.69 | 2.06 | 0.04 | -0.01 |
| kr_prem · - · z 1.0/2.0 · breakout · twin | 1.75 | -1.02 | 1.56 | 1.71 | 0.35 | 0.62 |
| kr_prem · - · z 1.0/2.0 · tsmom_daily · one day late | 1.65 | 0.00 | 1.50 | 1.46 | -0.43 | 0.90 |
| kr_prem · - · z 1.0/2.0 · tsmom_daily · twin | 1.64 | 0.00 | 1.19 | 0.20 | -0.40 | 1.18 |
| kr_prem · - · z 1.0/2.0 · tsmom_tranches · one day late | 2.18 | 0.84 | 1.40 | 1.53 | -0.12 | 0.62 |
| kr_prem · - · z 1.0/2.0 · tsmom_tranches · twin | 1.89 | 0.89 | 1.24 | 0.46 | -0.04 | 0.99 |
| stable_30 · - · z 0.5/1.5 · breakout · one day late | 1.86 | -0.58 | 1.93 | 2.07 | 0.23 | -0.68 |
| stable_30 · - · z 0.5/1.5 · breakout · twin | 2.00 | -0.85 | 1.72 | 1.97 | 0.40 | 0.12 |
| stable_30 · - · z 0.5/1.5 · tsmom_daily · one day late | 2.22 | 0.00 | 1.68 | 1.47 | -0.30 | 0.55 |
| stable_30 · - · z 0.5/1.5 · tsmom_daily · twin | 2.31 | 0.00 | 1.22 | 0.66 | -0.20 | 0.84 |
| stable_30 · - · z 0.5/1.5 · tsmom_tranches · one day late | 2.49 | 0.84 | 1.52 | 1.58 | -0.04 | 0.49 |
| stable_30 · - · z 0.5/1.5 · tsmom_tranches · twin | 2.45 | 0.88 | 1.29 | 0.85 | 0.14 | 0.83 |
| stable_7 · - · z 1.0/2.0 · breakout · one day late | 1.94 | -0.75 | 1.87 | 2.07 | 0.32 | 0.03 |
| stable_7 · - · z 1.0/2.0 · breakout · twin | 2.23 | -0.76 | 1.66 | 1.79 | 0.54 | 0.44 |
| stable_7 · - · z 1.0/2.0 · tsmom_daily · one day late | 1.83 | 0.00 | 1.61 | 1.47 | -0.36 | 0.90 |
| stable_7 · - · z 1.0/2.0 · tsmom_daily · twin | 2.15 | 0.00 | 1.14 | 0.50 | -0.18 | 1.13 |
| stable_7 · - · z 1.0/2.0 · tsmom_tranches · one day late | 2.29 | 0.64 | 1.47 | 1.58 | -0.12 | 0.61 |
| stable_7 · - · z 1.0/2.0 · tsmom_tranches · twin | 2.36 | 0.89 | 1.22 | 0.68 | 0.14 | 0.93 |
| funding · - · z 1.0/2.0 · breakout · one day late | 2.38 | -0.29 | 1.78 | 2.26 | -0.52 | -0.04 |
| funding · - · z 1.0/2.0 · breakout · twin | 2.44 | -0.39 | 1.85 | 1.91 | -0.30 | 0.48 |
| funding · - · z 1.0/2.0 · tsmom_daily · one day late | 2.06 | 0.00 | 1.33 | 1.72 | -0.87 | 0.86 |
| funding · - · z 1.0/2.0 · tsmom_daily · twin | 2.23 | 0.00 | 1.24 | 0.48 | -0.78 | 1.28 |
| funding · - · z 1.0/2.0 · tsmom_tranches · one day late | 2.57 | 0.84 | 1.25 | 1.81 | -0.84 | 0.57 |
| funding · - · z 1.0/2.0 · tsmom_tranches · twin | 2.51 | 0.89 | 1.33 | 0.71 | -0.65 | 1.11 |
| basis · - · z 0.5/1.5 · breakout · one day late | 2.35 | -0.91 | 1.94 | 2.32 | 0.15 | 0.08 |
| basis · - · z 0.5/1.5 · breakout · twin | 2.43 | -0.82 | 1.72 | 2.12 | 0.50 | 0.55 |
| basis · - · z 0.5/1.5 · tsmom_daily · one day late | 2.00 | 0.00 | 1.69 | 1.82 | -0.54 | 0.83 |
| basis · - · z 0.5/1.5 · tsmom_daily · twin | 2.13 | 0.00 | 1.22 | 0.90 | -0.24 | 1.11 |
| basis · + · z 1.0/2.0 · tsmom_tranches · one day late | 2.31 | 0.84 | 1.42 | 0.95 | -0.08 | 0.57 |
| basis · + · z 1.0/2.0 · tsmom_tranches · twin | 2.16 | 0.89 | 0.85 | -0.36 | 0.08 | 1.06 |
| oi_7 · - · z 0.5/1.5 · breakout · one day late | 2.38 | -0.47 | 1.52 | 1.96 | 0.19 | -0.22 |
| oi_7 · - · z 0.5/1.5 · breakout · twin | 2.43 | -0.63 | 1.48 | 1.43 | 0.05 | 0.26 |
| oi_7 · + · z 1.0/2.0 · tsmom_daily · one day late | 1.99 | 0.00 | 1.58 | 1.41 | -0.34 | 0.90 |
| oi_7 · + · z 1.0/2.0 · tsmom_daily · twin | 2.12 | 0.00 | 1.24 | 0.27 | -0.40 | 1.18 |
| oi_7 · + · z 1.0/2.0 · tsmom_tranches · one day late | 2.51 | 0.84 | 1.43 | 1.60 | -0.12 | 0.62 |
| oi_7 · + · z 1.0/2.0 · tsmom_tranches · twin | 2.41 | 0.89 | 1.29 | 0.51 | -0.09 | 0.99 |
| ls_ratio · + · z 1.0/2.0 · breakout · one day late | 2.38 | -0.61 | 1.94 | 2.36 | 0.39 | -0.02 |
| ls_ratio · + · z 1.0/2.0 · breakout · twin | 2.43 | -0.84 | 1.81 | 2.32 | 0.51 | 0.42 |
| ls_ratio · + · z 1.0/2.0 · tsmom_daily · one day late | 1.99 | 0.00 | 1.70 | 1.82 | -0.26 | 0.90 |
| ls_ratio · + · z 1.0/2.0 · tsmom_daily · twin | 2.12 | 0.00 | 1.36 | 0.69 | -0.18 | 1.18 |
| ls_ratio · + · z 0.5/1.5 · tsmom_tranches · one day late | 2.51 | 0.84 | 1.57 | 2.33 | 0.04 | 0.62 |
| ls_ratio · + · z 0.5/1.5 · tsmom_tranches · twin | 2.41 | 0.89 | 1.43 | 0.75 | 0.14 | 0.99 |
| liq · + · z 0.5/1.5 · breakout · one day late | 2.38 | -0.14 | 1.73 | 1.85 | 0.29 | -0.14 |
| liq · + · z 0.5/1.5 · breakout · twin | 2.43 | -0.62 | 1.58 | 1.37 | 0.46 | 0.59 |
| liq · - · z 1.0/2.0 · tsmom_daily · one day late | 1.99 | 0.00 | 1.76 | 1.33 | -0.28 | 0.90 |
| liq · - · z 1.0/2.0 · tsmom_daily · twin | 2.12 | 0.00 | 1.32 | 0.14 | -0.33 | 1.18 |
| liq · - · z 1.0/2.0 · tsmom_tranches · one day late | 2.51 | 0.84 | 1.57 | 1.44 | -0.10 | 0.62 |
| liq · - · z 1.0/2.0 · tsmom_tranches · twin | 2.41 | 0.89 | 1.38 | 0.41 | -0.01 | 0.99 |
| dvol · - · z 0.5/1.5 · breakout · one day late | 2.42 | -0.10 | 1.84 | 2.02 | -1.38 | -0.30 |
| dvol · - · z 0.5/1.5 · breakout · twin | 2.54 | -0.42 | 1.64 | 1.63 | -0.65 | -0.10 |
| dvol · - · z 1.0/2.0 · tsmom_daily · one day late | 1.99 | 0.00 | 2.08 | 1.56 | -1.21 | 0.66 |
| dvol · - · z 1.0/2.0 · tsmom_daily · twin | 2.12 | 0.00 | 1.69 | 0.37 | -1.61 | 0.98 |
| dvol · - · z 0.5/1.5 · tsmom_tranches · one day late | 2.55 | 0.87 | 2.15 | 1.49 | -1.54 | 0.42 |
| dvol · - · z 0.5/1.5 · tsmom_tranches · twin | 2.57 | 0.97 | 1.74 | 0.42 | -1.03 | 0.36 |
| logit long C 0.1 · breakout · one day late | 2.38 | -0.29 | 1.46 | 0.10 | -0.51 | -0.71 |
| logit long C 0.1 · breakout · twin | 2.43 | -1.35 | 1.58 | 0.24 | -0.29 | 0.78 |
| logit long C 0.1 · tsmom_daily · one day late | 1.99 | 0.00 | 1.55 | 0.31 | -0.52 | 0.48 |
| logit long C 0.1 · tsmom_daily · twin | 2.12 | 0.00 | 1.40 | -0.55 | -0.65 | 1.07 |
| logit long C 0.1 · tsmom_tranches · one day late | 2.51 | 0.84 | 1.49 | 0.33 | -0.44 | 0.54 |
| logit long C 0.1 · tsmom_tranches · twin | 2.41 | 0.89 | 1.51 | -0.25 | -0.38 | 0.96 |
