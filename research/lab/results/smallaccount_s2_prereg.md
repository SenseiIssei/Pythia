# S2: a fairly safe auto-trading wallet for 20 to 50 EUR on Solana, with stocks and ETFs, against an ETF. Pre-registration

Registered 2026-10-24 and committed before any number below was computed. Code:
`lab.experiments.smallaccount_s2` (written after this file). Results go to
`results/smallaccount_s2.md`. Nothing here may change once a result exists.

## Question

The owner has about 40 EUR in SOL and wants it to trade itself in the on-chain
wallet (Jupiter, `lab.onchain`, switched off since 2026-10-24): fairly safe, and
ideally better than holding an ETF. S1 (`results/smallaccount_s1.md`) found that
at 50 EUR only 1 to 3 big coins with a trend rule work. S2 asks:

1. what a Solana wallet can hold besides SOL, BTC and ETH (tokenized stocks and
   ETFs, tokenized gold, USDC), what a swap of 5 to 50 USD costs, how closely
   each token followed its underlying, who may hold them and what extra risks
   they carry;
2. whether any of 8 rules on the S&P 500 token, BTC, gold and USDC is "fairly
   safe" (drawdown under 20 %) and still beats or matches holding the S&P 500
   token, at 20, 40 and 50 EUR with realistic costs, out of sample;
3. which two run as paper books with 40 EUR wallets, and what an on-chain book
   would need if one passes.

## What exists: the snapshot, recorded at run time

`python -m lab.experiments.smallaccount_s2 --snapshot`, written to `results/`:

- **Tokens** (`smallaccount_s2_tokens.csv`): Jupiter's verified token list
  (lite-api.jup.ag/tokens/v2, tag verified), every token tagged xstocks, ondo,
  backpack, prestocks, tessera, stocks, rwa or commodities with at least
  50,000 USD of liquidity as Jupiter reports it, plus every ETF and gold token
  regardless of liquidity: symbol, name, mint, decimals, token program,
  liquidity, holders, issuer family (from the tags), ETF or gold or single share.
- **Quotes** (`smallaccount_s2_quotes.csv`): USDC to the token and straight
  back at 5, 10, 25, 50 and 100 USD with `lab.onchain.jupiter` (half the round
  trip in bps, Jupiter's price impact, the route) for the shortlist: every S&P
  500, Nasdaq 100 and total-market ETF token, every gold token, the three most
  liquid single shares, cbBTC, WETH and SOL.
- **Tracking** (`smallaccount_s2_tracking.csv`): for each shortlisted token
  with an underlying on Yahoo, the token's USD price against the underlying's
  close (unadjusted, because xStocks pay dividends by raising balances, not the
  price). The keyless sources reach back only so far, which is stated in the
  result: the hourly candles of the token's deepest pool on GeckoTerminal (the
  last 180 days), taking the candle that ends at the US close (20:00 UTC in
  summer time, 21:00 in winter time); and CoinGecko's daily price (the last
  365 days, 00:00 UTC, against the previous US close). Measured: the mean and
  the spread of the premium at the close, the 95th percentile of its absolute
  size, the daily tracking error (standard deviation of the daily return
  difference, x sqrt 252), the drift of the premium a year (a line through the
  log premium), the correlation of daily returns, and the weekend wander: the
  token's price on Sunday at the close hour against Friday's close.
- **Who may hold them:** what the issuers' public pages say, fetched at run
  time where reachable, quoted in the result; otherwise "must be checked".

**Picks fixed now.** The S&P 500 token is the one with the lowest half round
trip at 50 USD among the S&P 500 tokens with at least 100,000 USD of liquidity.
The gold token is the one with the lowest half round trip at 50 USD among the
gold tokens with at least 100,000 USD of liquidity (tokenized physical gold or
the gold ETF token). If no S&P 500 token qualifies, the study stops and says so.

## Costs (S1's wallet, with three changes)

S1's `Wallet` and `rebalance` from `lab.experiments.smallaccount`, in EUR at S1's
recorded EUR/USD mid (`smallaccount_kraken_pairs.csv`), Jupiter only:

- route cost: half the recorded round trip at the order's size from this
  snapshot's ladder (S1's interpolation);
- network fee: S1's 0.000105 SOL plus the 0.0001 SOL Sender tip the live
  on-chain trader pays, 0.000205 SOL a swap, at the day's SOL price;
- MIN_TRADE 5 USDC; an order under it is not sent, a position under it is dust;
- the SOL reserve as in S1 (0.01 SOL plus 0.00204 SOL of rent per token account
  the rule can hold, USDC included), held idle;
- getting there (changed): the owner already holds SOL, so one SOL to USDC swap
  at Jupiter's recorded SOL cost for the whole wallet, no Kraken fee and no
  withdrawal.
- USDC earns nothing (cash).

## The token price before the token existed

The ETF tokens are about a year old. Before and during their life the token is
modelled from its underlying's daily adjusted close in `<data>/etf/daily`
(Yahoo, dividends reinvested): the token's price is the underlying's adjusted
close times exp(drift x t), where drift is the measured premium drift a year
minus the withholding tax on dividends (xStocks reinvest dividends net of
withholding; the rate for the Jersey issuer is not published, so 30 % of the
underlying's dividend yield over the window, taken from Yahoo's adjusted and
unadjusted closes; 0 for gold). Weekends and US holidays carry the last close.
Sensitivity: the same with the measured premium at the close drawn at random
(day by day, from the token's measured premiums, 20 seeds, the median reported).
BTC and ETH: the lab's daily panel (`fam_common.load_panel`), the close at
00:00 UTC; the US close of the same day stands for the ETF token that day.

## Candidates (8, fixed now; trials = 8)

| key | rule | cadence |
|---|---|---|
| spy_hold | the S&P 500 token bought once and held: **the benchmark** "an ETF" | once |
| btc_hold | BTC (cbBTC) bought once and held (reference) | once |
| spy_trend | the S&P 500 token while SPY's close is above its 200-trading-day average, USDC below | daily |
| dual_mom | of the S&P 500 token, BTC and gold, the one with the best 365-day return, if that return is above 0, else USDC | weekly |
| mix_6040 | 60 % S&P 500 token, 40 % BTC, back to 60/40 on the first day of each month | monthly |
| trend_mix | 60 % S&P 500 token while SPY is above its 200-day average, 40 % BTC while BTC is above its 200-day average, USDC otherwise; back to target on the first day of each month | daily |
| tsmom1 | S1's best: tsmom_top20 on the single most liquid coin (BTC, some days ETH), regime, 40 % vol | daily |
| vol_target | S&P 500 token, BTC and gold weighted by 1 / vol (each from its last 60 trading-day returns), scaled to 10 % portfolio vol a year with the 60-day correlations, at most 100 % in all, the rest USDC | weekly |

Weekly is S1's weekly day (calendar days since 2020-01-01 modulo 7). A target
decided at the close of day t is traded at that close, S1's convention. As in
S1, a coin whose target did not change is not traded, except on the monthly
re-weighting days of mix_6040 and trend_mix.

## Windows and measures

In sample 2020-08-01 to 2023-12-31, out of sample 2024-01-01 to the last close
in `<data>/etf/daily` (and at most 2026-10-21). Each candidate at 20, 40 and 50
EUR. Per window: annual return (CAGR), max drawdown, Sharpe (daily, x sqrt
365), the worst calendar month, the share of calendar months that beat
spy_hold, the costs as a share of the gain before costs, orders a year, orders
not sent. Out of sample at 40 EUR, also: a circular block bootstrap (blocks of
20 days, 2,000 draws, seed 0, the same days drawn for candidate and benchmark)
with the 5 % and 95 % band of the CAGR and of the CAGR difference to spy_hold,
and the share of draws above it; and the deflated p-value against the
benchmark: one minus the deflated Sharpe probability (`metrics.deflated_sharpe`)
of the daily return difference candidate minus spy_hold, over the 8 trials,
with the variance of the 7 difference Sharpes and the candidate's own skew and
kurtosis.

## Decisions, fixed now

- **Fairly safe:** out-of-sample max drawdown under 20 % at 40 EUR.
- **Beats or matches the ETF:** out-of-sample CAGR at 40 EUR at least
  spy_hold's minus 1 percentage point.
- **The bar** (for a proposal to the owner): fairly safe and beats or matches.
  **Convincingly:** also the bootstrap's 5 % band of the CAGR difference above
  0 and the deflated p-value under 0.05.
- **Paper books:** the two candidates other than spy_hold, btc_hold and tsmom1
  (S1 already runs it as small50_tsmom1) with the best **in-sample** Sharpe at
  40 EUR among those with an in-sample drawdown under 20 %, filled up by
  in-sample Sharpe if fewer than two. 40 EUR paper wallets with these costs,
  Jupiter's live prices, next to S1's books in `reports/smallaccount`, in the
  daily report and the morning briefing's paper line. Picked in sample, judged
  out of sample and forward.
- **If a candidate passes the bar:** the result names the exact on-chain book it
  would need (coins and mints, rule, cadence, caps) as a proposal. No live file
  changes and nothing is switched on; the owner decides.
