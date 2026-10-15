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
