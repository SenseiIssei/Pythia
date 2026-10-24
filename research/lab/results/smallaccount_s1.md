# S1: the lab's strategies with 50, 100 and 500 EUR

Pre-registered in `results/smallaccount_s1_prereg.md`, code `lab.experiments.smallaccount`, costs recorded
for it on 2026-10-24 (`smallaccount_kraken_pairs.csv`, `smallaccount_jupiter_quotes.csv`). Out of sample
2024-01-01 to 2026-10-21. Paper only; nothing live changed.

## In short

- **Kraken has no fixed fee**, so its cost share is the same at 50 and at 10,000 EUR: taker 40 bps plus a
  spread of 0 to 1 bp on the big EUR pairs. What hurts a small account there is the **minimum order of
  about 3.50 to 4.60 EUR** (BTC 4.34 EUR). With 50 EUR every position under about 9 % of the wallet
  cannot be bought, trimmed or sold.
- **Jupiter is cheaper for BTC, ETH and SOL**: 0 to 2 bps of route cost plus about 0.01 USD of network fee
  a swap (about 20 bps on a 5 USD swap, 5 bps on 25 USD, 2 bps on 100 USD), memecoins 5 to 26 bps. But
  only coins with a Solana mint, and getting there costs once about 2.4 % of 50 EUR (EUR to USDC, the
  withdrawal, a SOL reserve that earns nothing).
- **Many coins do not work at 50 or 100 EUR.** tsmom_top20 and trend_carry on 20 coins send almost no
  order at 50 EUR (about 2,500 refused a year) and earn nothing; breakout_top10 on 10 coins needs about
  250 EUR on Kraken, trend_carry on 20 about 500 EUR. Everything on 1 to 3 coins works from 25 EUR.
- **What works small: 1 to 3 big coins, a trend rule, daily or weekly.** At 50 EUR on Jupiter:
  momentum on the most liquid coin (BTC, some days ETH) 28.8 % a year, drawdown 17 %, Sharpe 1.10,
  costs 5 % of the gain, 30 orders a year; Donchian on BTC and ETH weekly 22.9 %, drawdown 25 %, 0.92.
  BTC bought and held made 24 to 25 % a year with a 52 % drawdown (Sharpe 0.70 to 0.72): the rules beat
  it mainly on drawdown, not on return, in a period that was good for BTC. On Kraken the daily rules
  lose 3 to 7 points a year more to the fee (momentum on 1 coin 22.1 % instead of 28.8 %); weekly
  rules lose almost nothing (Donchian BTC and ETH 22.9 % on both).
- **memes_rotation** (one memecoin, Kraken EUR pairs) shows the highest numbers (weekly: 53 % a year,
  Sharpe 1.39, drawdown 22 %), but it is one coin at a time out of six, failed deflation in W7 and is
  not the in-sample best (1.21 to 1.63 against 1.98); not a pick.
- No bootstrap band or deflation was run on these differences; they are a description at realistic
  costs, not a new proof. A gain of 29 % a year on 50 EUR is about 14 EUR.

## Paper books (from the deploy, job `paper-smallaccount`, report `reports/smallaccount/` in EUR)

Picked by the pre-registered rule (best in-sample Sharpe; the second book from another candidate):

- `small50_tsmom1`: tsmom_top20 on 1 coin, daily, Jupiter costs, 50 EUR wallet (IS 1.98, OOS 1.10).
- `small100_breakout_sol3`: Donchian 20/10 on BTC, ETH and SOL, daily, Jupiter costs, 100 EUR wallet
  (IS 1.88, OOS 0.92).

Both picks are on Jupiter, so the Kraken maker sensitivity row does not apply. Answer to "what is worth
running at 50 and 100 EUR": one or two big coins with a trend rule (the two books), daily or weekly; on
Kraken only on Kraken Pro (the app's instant buy charges far more), with weekly rebalancing. Nothing with
10 or 20 coins below 250 to 500 EUR.

<!-- generated below by lab.experiments.smallaccount; edit above this line only -->

Generated 2026-10-24T00:26:27+00:00, panel cut 2026-10-21, EUR/USD 1.1194 (Kraken mid). Out of sample 2024-01-01 to the cut unless a column says otherwise. `costs` is the share of the return before costs the costs took (n/a: no gain before costs); `not sent` orders under the venue's minimum; `dust` sales refused because the position was under the minimum.

## 1. What one order costs (bps of the order, network fee included)

| coin | kraken_min_eur | kraken_taker_bps | jup_5usd_bps | jup_25usd_bps | jup_100usd_bps |
|---|---|---|---|---|---|
| BTC | 4.34 | 40.0 | 21.6 | 4.7 | 1.6 |
| ETH | 4.26 | 40.0 | 22.1 | 4.8 | 1.8 |
| SOL | 4.58 | 40.5 | 21.6 | 4.3 | 1.2 |
| DOGE | 3.51 | 40.2 | no mint | no mint | no mint |
| PEPE | 4.48 | 41.2 | no mint | no mint | no mint |
| BONK | 3.62 | 47.2 | 26.6 | 9.1 | 7.6 |
| WIF | 3.37 | 43.0 | 26.1 | 10.0 | 12.5 |
| JUP | 4.01 | 45.8 | 21.6 | 4.6 | 1.9 |

Kraken: taker 40 bps plus the snapshot's half spread on the EUR pair; Jupiter: half the recorded round trip at that size plus 0.000105 SOL. The on-chain paper book's own 100 USDC probes, halved: SOL 0.9, BTC 1.5, ETH 0.8, JUP 1.6, BONK 7.7, WIF 6.2, POPCAT 24.9, RAY 4.7, PYTH 12.9, JTO 11.3, RENDER 15.9, TRUMP 1.9.

## 2a. The rules as the lab runs them, daily, Kraken taker

| candidate | EUR | CAGR | max DD | Sharpe | costs | orders/yr | not sent/yr | dust |
|---|---|---|---|---|---|---|---|---|
| btc_hold | 50 | 25.4 % | 52.8 % | 0.72 | 0.4 % | 0 | 0 | 0 |
| btc_hold | 100 | 25.4 % | 52.8 % | 0.72 | 0.4 % | 0 | 0 | 0 |
| btc_hold | 500 | 25.4 % | 52.8 % | 0.72 | 0.4 % | 0 | 0 | 0 |
| btc_hold | 41 bps, any size | 25.4 % | 52.8 % | 0.72 | 0.5 % | 0 | 0 | 0 |
| btc_gated | 50 | 18.1 % | 33.5 % | 0.64 | 20.3 % | 10 | 0 | 0 |
| btc_gated | 100 | 18.1 % | 33.5 % | 0.64 | 20.3 % | 10 | 0 | 0 |
| btc_gated | 500 | 18.1 % | 33.5 % | 0.64 | 20.3 % | 10 | 0 | 0 |
| btc_gated | 41 bps, any size | 18.0 % | 33.6 % | 0.64 | 20.8 % | 10 | 0 | 0 |
| breakout_btceth | 50 | 22.7 % | 28.1 % | 0.89 | 7.9 % | 10 | 0 | 0 |
| breakout_btceth | 100 | 22.7 % | 28.1 % | 0.89 | 7.9 % | 10 | 0 | 0 |
| breakout_btceth | 500 | 22.7 % | 28.1 % | 0.89 | 7.9 % | 10 | 0 | 0 |
| breakout_btceth | 41 bps, any size | 22.6 % | 28.1 % | 0.89 | 8.1 % | 10 | 0 | 0 |
| breakout_top10 | 50 | 16.0 % | 22.7 % | 1.03 | 11.7 % | 49 | 788 | 11 |
| breakout_top10 | 100 | 16.2 % | 27.8 % | 0.79 | 18.7 % | 122 | 233 | 15 |
| breakout_top10 | 500 | 22.2 % | 22.1 % | 1.09 | 16.8 % | 156 | 0 | 0 |
| breakout_top10 | 41 bps, any size | 20.6 % | 22.1 % | 1.02 | 17.9 % | 161 | 0 | 0 |
| breakout_sol | 50 | 2.2 % | 7.8 % | 0.44 | 18.7 % | 12 | 924 | 3 |
| breakout_sol | 100 | 5.2 % | 24.2 % | 0.39 | 31.3 % | 84 | 307 | 17 |
| breakout_sol | 500 | 6.2 % | 22.4 % | 0.45 | 34.2 % | 130 | 0 | 0 |
| breakout_sol | 41 bps, any size | 6.4 % | 22.3 % | 0.47 | 32.1 % | 130 | 0 | 0 |
| tsmom_top20 | 50 | -0.4 % | 1.4 % | -0.70 | n/a | 3 | 2500 | 0 |
| tsmom_top20 | 100 | 2.6 % | 8.8 % | 0.55 | 29.0 % | 45 | 2466 | 22 |
| tsmom_top20 | 500 | 3.4 % | 20.7 % | 0.29 | 57.6 % | 492 | 2221 | 18 |
| tsmom_top20 | 41 bps, any size | 0.5 % | 24.3 % | 0.11 | 91.4 % | 2934 | 0 | 0 |
| trend_carry | 50 | -0.4 % | 1.4 % | -0.70 | n/a | 3 | 1675 | 0 |
| trend_carry | 100 | 3.2 % | 3.5 % | 1.02 | 24.8 % | 45 | 1643 | 19 |
| trend_carry | 500 | 2.2 % | 15.7 % | 0.26 | 70.4 % | 526 | 1394 | 7 |
| trend_carry | 41 bps, any size | 0.8 % | 17.4 % | 0.13 | 88.1 % | 2045 | 0 | 0 |
| memes_rotation | 50 | 34.2 % | 23.2 % | 1.13 | 24.5 % | 64 | 113 | 0 |
| memes_rotation | 100 | 32.2 % | 23.1 % | 1.11 | 25.3 % | 80 | 98 | 0 |
| memes_rotation | 500 | 31.4 % | 23.5 % | 1.08 | 26.3 % | 148 | 30 | 0 |
| memes_rotation | 41 bps, any size | 31.9 % | 23.4 % | 1.10 | 25.4 % | 178 | 0 | 0 |

## 2b. The rules as the lab runs them, daily, Jupiter

| candidate | EUR | CAGR | max DD | Sharpe | costs | orders/yr | not sent/yr | dust |
|---|---|---|---|---|---|---|---|---|
| btc_hold | 50 | 24.0 % | 52.2 % | 0.70 | 2.6 % | 0 | 0 | 0 |
| btc_hold | 100 | 24.7 % | 52.5 % | 0.71 | 1.5 % | 0 | 0 | 0 |
| btc_hold | 500 | 25.2 % | 52.7 % | 0.72 | 0.7 % | 0 | 0 | 0 |
| btc_hold | 41 bps, any size | 25.4 % | 52.8 % | 0.72 | 0.5 % | 0 | 0 | 0 |
| btc_gated | 50 | 21.1 % | 30.6 % | 0.72 | 4.5 % | 10 | 0 | 0 |
| btc_gated | 100 | 22.0 % | 30.7 % | 0.74 | 2.2 % | 10 | 0 | 0 |
| btc_gated | 500 | 22.6 % | 30.8 % | 0.75 | 1.0 % | 10 | 0 | 0 |
| btc_gated | 41 bps, any size | 18.0 % | 33.6 % | 0.64 | 20.8 % | 10 | 0 | 0 |
| breakout_btceth | 50 | 22.8 % | 26.7 % | 0.92 | 3.9 % | 10 | 0 | 0 |
| breakout_btceth | 100 | 23.7 % | 26.9 % | 0.93 | 2.3 % | 10 | 0 | 0 |
| breakout_btceth | 500 | 24.4 % | 27.0 % | 0.95 | 0.8 % | 10 | 0 | 0 |
| breakout_btceth | 41 bps, any size | 22.6 % | 28.1 % | 0.89 | 8.1 % | 10 | 0 | 0 |
| breakout_top10 | 50 | 1.4 % | 2.6 % | 0.50 | 41.5 % | 7 | 366 | 0 |
| breakout_top10 | 100 | 5.0 % | 6.6 % | 0.78 | 14.6 % | 33 | 150 | 2 |
| breakout_top10 | 500 | 5.8 % | 6.6 % | 0.85 | 5.9 % | 52 | 0 | 0 |
| breakout_top10 | 41 bps, any size | 20.6 % | 22.1 % | 1.02 | 17.9 % | 161 | 0 | 0 |
| breakout_sol | 50 | 1.4 % | 2.6 % | 0.50 | 41.5 % | 7 | 978 | 0 |
| breakout_sol | 100 | 7.3 % | 19.9 % | 0.59 | 14.1 % | 56 | 523 | 12 |
| breakout_sol | 500 | 8.4 % | 20.4 % | 0.59 | 9.0 % | 130 | 0 | 0 |
| breakout_sol | 41 bps, any size | 6.4 % | 22.3 % | 0.47 | 32.1 % | 130 | 0 | 0 |
| tsmom_top20 | 50 | -0.8 % | 0.0 % | -0.60 | n/a | 0 | 577 | 0 |
| tsmom_top20 | 100 | 0.6 % | 1.1 % | 0.38 | 54.0 % | 15 | 566 | 3 |
| tsmom_top20 | 500 | 2.4 % | 4.3 % | 0.57 | 18.1 % | 97 | 522 | 5 |
| tsmom_top20 | 41 bps, any size | 0.5 % | 24.3 % | 0.11 | 91.4 % | 2934 | 0 | 0 |
| trend_carry | 50 | -0.8 % | 0.0 % | -0.60 | n/a | 0 | 416 | 0 |
| trend_carry | 100 | 0.1 % | 1.1 % | 0.07 | 91.1 % | 21 | 402 | 2 |
| trend_carry | 500 | 1.9 % | 2.1 % | 0.62 | 22.8 % | 106 | 359 | 0 |
| trend_carry | 41 bps, any size | 0.8 % | 17.4 % | 0.13 | 88.1 % | 2045 | 0 | 0 |
| memes_rotation | 50 | 6.2 % | 18.5 % | 0.42 | 23.1 % | 28 | 48 | 0 |
| memes_rotation | 100 | 5.5 % | 18.4 % | 0.39 | 18.7 % | 30 | 46 | 0 |
| memes_rotation | 500 | 5.9 % | 18.8 % | 0.41 | 17.4 % | 55 | 21 | 0 |
| memes_rotation | 41 bps, any size | 31.9 % | 23.4 % | 1.10 | 25.4 % | 178 | 0 | 0 |

## 3. Slower and fewer, at 50 and 100 EUR

| variant | IS Sharpe (Kraken 50) | kraken 50 | kraken 100 | jupiter 50 | jupiter 100 |
|---|---|---|---|---|---|
| btc_hold · 1 coin · daily | 0.90 | 25.4 % / 0.72 / 0.4 % / 0 | 25.4 % / 0.72 / 0.4 % / 0 | 24.0 % / 0.70 / 2.6 % / 0 | 24.7 % / 0.71 / 1.5 % / 0 |
| btc_gated · 1 coin · daily | 1.01 | 18.1 % / 0.64 / 20.3 % / 10 | 18.1 % / 0.64 / 20.3 % / 10 | 21.1 % / 0.72 / 4.5 % / 10 | 22.0 % / 0.74 / 2.2 % / 10 |
| btc_gated · 1 coin · 3 days | 1.12 | 13.8 % / 0.54 / 17.6 % / 7 | 13.8 % / 0.54 / 17.6 % / 7 | 15.3 % / 0.58 / 5.6 % / 7 | 16.1 % / 0.60 / 2.9 % / 7 |
| btc_gated · 1 coin · weekly | 1.12 | 22.6 % / 0.74 / 7.1 % / 4 | 22.6 % / 0.74 / 7.1 % / 4 | 22.8 % / 0.75 / 3.2 % / 4 | 23.6 % / 0.77 / 1.8 % / 4 |
| breakout_btceth · 1 coin · daily | 1.39 | 17.6 % / 0.75 / 12.3 % / 6 | 17.6 % / 0.75 / 12.3 % / 6 | 18.5 % / 0.79 / 4.5 % / 6 | 19.3 % / 0.81 / 2.4 % / 6 |
| breakout_btceth · 1 coin · 3 days | 1.38 | 17.5 % / 0.75 / 13.2 % / 6 | 17.5 % / 0.75 / 13.2 % / 6 | 18.5 % / 0.80 / 4.5 % / 6 | 19.3 % / 0.82 / 2.4 % / 6 |
| breakout_btceth · 1 coin · weekly | 1.58 | 18.9 % / 0.79 / 10.6 % / 5 | 18.9 % / 0.79 / 10.6 % / 5 | 19.6 % / 0.83 / 4.1 % / 5 | 20.4 % / 0.85 / 2.2 % / 5 |
| breakout_btceth · 2 coins · daily | 1.30 | 22.7 % / 0.89 / 7.9 % / 10 | 22.7 % / 0.89 / 7.9 % / 10 | 22.8 % / 0.92 / 3.9 % / 10 | 23.7 % / 0.93 / 2.3 % / 10 |
| breakout_btceth · 2 coins · 3 days | 1.32 | 19.7 % / 0.81 / 9.5 % / 10 | 19.7 % / 0.81 / 9.5 % / 10 | 19.9 % / 0.83 / 4.6 % / 10 | 20.8 % / 0.85 / 2.6 % / 10 |
| breakout_btceth · 2 coins · weekly | 1.47 | 22.9 % / 0.90 / 7.7 % / 10 | 22.9 % / 0.90 / 7.7 % / 10 | 22.9 % / 0.92 / 3.8 % / 10 | 23.8 % / 0.94 / 2.2 % / 10 |
| breakout_top10 · 1 coin · daily | 0.93 | 13.6 % / 0.61 / 33.0 % / 16 | 13.6 % / 0.61 / 33.0 % / 16 | 17.7 % / 0.76 / 6.2 % / 16 | 18.6 % / 0.79 / 3.1 % / 16 |
| breakout_top10 · 1 coin · 3 days | 0.86 | 10.9 % / 0.54 / 36.7 % / 15 | 10.9 % / 0.54 / 36.7 % / 15 | 14.8 % / 0.68 / 7.4 % / 15 | 15.6 % / 0.71 / 3.7 % / 15 |
| breakout_top10 · 1 coin · weekly | 0.86 | 22.1 % / 0.87 / 23.0 % / 15 | 22.1 % / 0.87 / 23.0 % / 15 | 26.2 % / 1.01 / 3.9 % / 15 | 27.2 % / 1.03 / 2.0 % / 15 |
| breakout_top10 · 3 coins · daily | 1.10 | 12.1 % / 0.64 / 30.9 % / 50 | 12.1 % / 0.64 / 30.9 % / 50 | 16.5 % / 0.87 / 9.7 % / 46 | 17.7 % / 0.91 / 5.4 % / 46 |
| breakout_top10 · 3 coins · 3 days | 0.82 | 9.0 % / 0.52 / 36.7 % / 49 | 7.7 % / 0.46 / 40.6 % / 50 | 11.4 % / 0.66 / 13.9 % / 46 | 12.5 % / 0.70 / 7.8 % / 46 |
| breakout_top10 · 3 coins · weekly | 0.92 | 12.2 % / 0.63 / 29.1 % / 46 | 12.3 % / 0.64 / 28.8 % / 46 | 16.6 % / 0.84 / 9.2 % / 42 | 17.9 % / 0.89 / 5.2 % / 43 |
| breakout_top10 · 5 coins · daily | 1.00 | 19.8 % / 0.96 / 18.7 % / 72 | 18.3 % / 0.90 / 21.0 % / 79 | 9.2 % / 0.77 / 14.5 % / 35 | 10.7 % / 0.87 / 8.7 % / 48 |
| breakout_top10 · 5 coins · 3 days | 0.99 | 10.9 % / 0.63 / 29.6 % / 72 | 10.4 % / 0.59 / 31.4 % / 79 | 6.1 % / 0.56 / 23.7 % / 46 | 6.9 % / 0.61 / 13.2 % / 48 |
| breakout_top10 · 5 coins · weekly | 0.89 | 16.2 % / 0.82 / 21.2 % / 67 | 15.7 % / 0.78 / 22.3 % / 74 | 9.0 % / 0.74 / 16.3 % / 41 | 9.8 % / 0.78 / 9.1 % / 43 |
| breakout_top10 · 10 coins · daily | 0.61 | 16.0 % / 1.03 / 11.7 % / 49 | 16.2 % / 0.79 / 18.7 % / 122 | 1.4 % / 0.50 / 41.5 % / 7 | 5.0 % / 0.78 / 14.6 % / 33 |
| breakout_top10 · 10 coins · 3 days | 0.76 | 12.7 % / 0.91 / 11.6 % / 38 | 13.4 % / 0.74 / 22.4 % / 121 | 0.8 % / 0.28 / 52.2 % / 5 | 1.7 % / 0.28 / 33.5 % / 30 |
| breakout_top10 · 10 coins · weekly | 0.53 | 19.2 % / 1.40 / 9.2 % / 47 | 18.4 % / 0.93 / 16.5 % / 115 | 0.3 % / 0.11 / 75.0 % / 2 | 3.8 % / 0.58 / 19.6 % / 36 |
| breakout_sol · 1 coin · daily | 0.90 | 13.6 % / 0.61 / 33.0 % / 16 | 13.6 % / 0.61 / 33.0 % / 16 | 17.7 % / 0.76 / 6.2 % / 16 | 18.6 % / 0.79 / 3.1 % / 16 |
| breakout_sol · 1 coin · 3 days | 0.86 | 10.9 % / 0.54 / 36.7 % / 15 | 10.9 % / 0.54 / 36.7 % / 15 | 14.8 % / 0.68 / 7.4 % / 15 | 15.6 % / 0.71 / 3.7 % / 15 |
| breakout_sol · 1 coin · weekly | 0.92 | 22.1 % / 0.87 / 23.0 % / 15 | 22.1 % / 0.87 / 23.0 % / 15 | 26.2 % / 1.01 / 3.9 % / 15 | 27.2 % / 1.03 / 2.0 % / 15 |
| breakout_sol · 3 coins · daily | 1.68 | 14.4 % / 0.75 / 26.6 % / 47 | 14.4 % / 0.75 / 26.6 % / 47 | 17.0 % / 0.88 / 9.5 % / 47 | 18.2 % / 0.92 / 5.3 % / 47 |
| breakout_sol · 3 coins · 3 days | 1.63 | 8.6 % / 0.51 / 37.0 % / 47 | 8.6 % / 0.51 / 37.0 % / 47 | 11.1 % / 0.64 / 14.4 % / 47 | 12.2 % / 0.68 / 8.0 % / 47 |
| breakout_sol · 3 coins · weekly | 1.39 | 13.7 % / 0.70 / 26.2 % / 43 | 13.9 % / 0.71 / 26.0 % / 43 | 15.9 % / 0.81 / 9.7 % / 43 | 17.2 % / 0.85 / 5.5 % / 43 |
| breakout_sol · 5 coins · daily | 1.53 | 12.8 % / 0.74 / 23.8 % / 64 | 9.5 % / 0.51 / 30.6 % / 75 | 6.6 % / 0.49 / 21.3 % / 41 | 10.6 % / 0.54 / 11.7 % / 70 |
| breakout_sol · 5 coins · 3 days | 1.44 | 4.7 % / 0.34 / 44.4 % / 62 | -0.3 % / 0.08 / 107.8 % / 75 | 2.9 % / 0.27 / 42.2 % / 51 | 3.3 % / 0.26 / 31.1 % / 72 |
| breakout_sol · 5 coins · weekly | 1.38 | 3.2 % / 0.26 / 50.4 % / 51 | 0.6 % / 0.13 / 86.3 % / 69 | 5.4 % / 0.43 / 26.6 % / 47 | 3.9 % / 0.28 / 27.3 % / 69 |
| breakout_sol · 10 coins · daily | 0.82 | 2.2 % / 0.44 / 18.7 % / 12 | 5.2 % / 0.39 / 31.3 % / 84 | 1.4 % / 0.50 / 41.5 % / 7 | 7.3 % / 0.59 / 14.1 % / 56 |
| breakout_sol · 10 coins · 3 days | 0.94 | -0.6 % / -0.09 / n/a / 11 | 0.7 % / 0.12 / 75.6 % / 78 | 0.8 % / 0.28 / 52.2 % / 5 | -0.9 % / -0.01 / 492.2 % / 49 |
| breakout_sol · 10 coins · weekly | 0.86 | -0.9 % / -0.16 / n/a / 11 | 2.3 % / 0.22 / 47.5 % / 72 | 0.3 % / 0.11 / 75.0 % / 2 | 3.5 % / 0.33 / 26.0 % / 56 |
| tsmom_top20 · 1 coin · daily | 1.83 | 22.1 % / 0.87 / 26.3 % / 29 | 21.9 % / 0.87 / 26.7 % / 37 | 28.8 % / 1.10 / 5.0 % / 30 | 29.8 % / 1.12 / 2.8 % / 38 |
| tsmom_top20 · 1 coin · 3 days | 1.38 | 20.6 % / 0.82 / 21.1 % / 20 | 20.5 % / 0.82 / 21.3 % / 25 | 24.1 % / 0.94 / 5.1 % / 20 | 24.9 % / 0.96 / 2.9 % / 25 |
| tsmom_top20 · 1 coin · weekly | 1.70 | 20.1 % / 0.80 / 14.4 % / 13 | 19.4 % / 0.78 / 15.1 % / 17 | 21.7 % / 0.86 / 4.7 % / 12 | 22.1 % / 0.87 / 2.8 % / 17 |
| tsmom_top20 · 3 coins · daily | 1.40 | 11.9 % / 0.56 / 36.6 % / 67 | 10.7 % / 0.58 / 40.2 % / 84 | 16.2 % / 0.81 / 12.0 % / 56 | 19.4 % / 0.98 / 7.2 % / 78 |
| tsmom_top20 · 3 coins · 3 days | 1.52 | 8.9 % / 0.46 / 34.1 % / 47 | 8.5 % / 0.48 / 36.2 % / 55 | 14.1 % / 0.71 / 11.2 % / 39 | 13.8 % / 0.72 / 7.7 % / 50 |
| tsmom_top20 · 3 coins · weekly | 1.73 | 18.7 % / 0.77 / 13.3 % / 31 | 18.6 % / 0.85 / 13.9 % / 40 | 23.7 % / 1.07 / 5.2 % / 27 | 22.6 % / 1.02 / 3.6 % / 36 |
| tsmom_top20 · 5 coins · daily | 1.55 | 10.7 % / 0.58 / 33.3 % / 87 | 11.0 % / 0.60 / 35.7 % / 124 | 10.4 % / 0.80 / 16.9 % / 50 | 12.0 % / 0.92 / 10.5 % / 69 |
| tsmom_top20 · 5 coins · 3 days | 1.33 | 6.8 % / 0.40 / 35.9 % / 61 | 9.7 % / 0.54 / 30.8 % / 88 | 9.1 % / 0.72 / 15.9 % / 35 | 8.8 % / 0.69 / 11.1 % / 46 |
| tsmom_top20 · 5 coins · weekly | 1.32 | 18.9 % / 0.86 / 11.9 % / 43 | 17.0 % / 0.80 / 14.5 % / 62 | 14.5 % / 1.04 / 8.1 % / 22 | 12.8 % / 0.91 / 6.1 % / 31 |
| tsmom_top20 · 20 coins · daily | 0.00 | -0.4 % / -0.70 / n/a / 3 | 2.6 % / 0.55 / 29.0 % / 45 | -0.8 % / -0.60 / n/a / 0 | 0.6 % / 0.38 / 54.0 % / 15 |
| tsmom_top20 · 20 coins · 3 days | 0.00 | -0.5 % / -1.03 / n/a / 2 | 2.9 % / 0.76 / 21.3 % / 33 | -0.8 % / -0.60 / n/a / 0 | 0.0 % / 0.02 / 96.7 % / 10 |
| tsmom_top20 · 20 coins · weekly | 0.00 | -0.2 % / -0.48 / n/a / 1 | 3.0 % / 0.62 / 14.1 % / 21 | -0.8 % / -0.60 / n/a / 0 | 0.8 % / 0.51 / 40.0 % / 6 |
| trend_carry · 1 coin · daily | 1.45 | 9.7 % / 0.53 / 50.9 % / 31 | 9.4 % / 0.51 / 51.8 % / 37 | 17.1 % / 0.84 / 9.2 % / 31 | 18.0 % / 0.87 / 5.0 % / 38 |
| trend_carry · 1 coin · 3 days | 1.00 | 6.2 % / 0.38 / 53.0 % / 22 | 5.8 % / 0.36 / 54.5 % / 26 | 10.7 % / 0.57 / 12.5 % / 22 | 11.2 % / 0.59 / 7.0 % / 26 |
| trend_carry · 1 coin · weekly | 1.61 | 2.7 % / 0.23 / 64.2 % / 15 | 2.1 % / 0.20 / 69.5 % / 17 | 5.5 % / 0.35 / 19.3 % / 15 | 5.8 % / 0.36 / 11.4 % / 17 |
| trend_carry · 3 coins · daily | 1.00 | 11.1 % / 0.69 / 42.2 % / 78 | 7.2 % / 0.50 / 53.5 % / 92 | 15.1 % / 0.98 / 14.8 % / 72 | 15.5 % / 0.99 / 9.4 % / 80 |
| trend_carry · 3 coins · 3 days | 0.91 | 7.0 % / 0.47 / 41.8 % / 52 | 4.7 % / 0.36 / 52.1 % / 57 | 10.5 % / 0.65 / 15.1 % / 40 | 10.0 % / 0.68 / 10.8 % / 51 |
| trend_carry · 3 coins · weekly | 1.26 | 7.6 % / 0.51 / 30.1 % / 33 | 7.1 % / 0.48 / 33.0 % / 39 | 9.6 % / 0.64 / 14.1 % / 30 | 10.4 % / 0.68 / 8.5 % / 36 |
| trend_carry · 5 coins · daily | 1.48 | 11.3 % / 0.78 / 35.3 % / 98 | 4.5 % / 0.35 / 60.1 % / 140 | 9.1 % / 0.91 / 22.0 % / 65 | 9.8 % / 0.94 / 13.4 % / 75 |
| trend_carry · 5 coins · 3 days | 1.50 | 5.5 % / 0.42 / 42.6 % / 64 | 1.0 % / 0.14 / 82.2 % / 92 | 6.5 % / 0.66 / 21.6 % / 36 | 6.3 % / 0.63 / 15.5 % / 48 |
| trend_carry · 5 coins · weekly | 1.02 | 6.5 % / 0.48 / 29.4 % / 43 | 6.0 % / 0.42 / 34.3 % / 61 | 5.8 % / 0.60 / 20.4 % / 26 | 5.0 % / 0.51 / 15.5 % / 32 |
| trend_carry · 20 coins · daily | 0.00 | -0.4 % / -0.70 / n/a / 3 | 3.2 % / 1.02 / 24.8 % / 45 | -0.8 % / -0.60 / n/a / 0 | 0.1 % / 0.07 / 91.1 % / 21 |
| trend_carry · 20 coins · 3 days | 0.00 | -0.5 % / -1.03 / n/a / 2 | 2.6 % / 0.95 / 24.4 % / 35 | -0.8 % / -0.60 / n/a / 0 | -0.2 % / -0.17 / 142.5 % / 12 |
| trend_carry · 20 coins · weekly | 0.00 | -0.2 % / -0.48 / n/a / 1 | 2.3 % / 0.85 / 20.0 % / 23 | -0.8 % / -0.60 / n/a / 0 | 0.1 % / 0.11 / 81.1 % / 9 |
| memes_rotation · 1 coin · daily | 1.61 | 34.2 % / 1.13 / 24.5 % / 64 | 32.2 % / 1.11 / 25.3 % / 80 | 6.2 % / 0.42 / 23.1 % / 28 | 5.5 % / 0.39 / 18.7 % / 30 |
| memes_rotation · 1 coin · 3 days | 1.63 | 38.3 % / 1.16 / 16.5 % / 39 | 37.1 % / 1.17 / 16.8 % / 46 | 5.5 % / 0.39 / 20.1 % / 16 | 5.0 % / 0.37 / 15.3 % / 17 |
| memes_rotation · 1 coin · weekly | 1.21 | 53.2 % / 1.39 / 7.8 % / 25 | 52.8 % / 1.38 / 7.9 % / 29 | 1.5 % / 0.17 / 45.3 % / 11 | 2.2 % / 0.21 / 25.2 % / 12 |

Each cell: CAGR / Sharpe / cost share / orders a year. Every capital and the in-sample numbers: reports/smallaccount_s1/latest.json.

## 4. Worth running (CAGR > 0, Sharpe above BTC held on the same venue, costs < 50 %)

- 50 EUR: breakout_top10 · 10 coins · weekly · kraken, memes_rotation · 1 coin · weekly · kraken, memes_rotation · 1 coin · 3 days · kraken, memes_rotation · 1 coin · daily · kraken, tsmom_top20 · 1 coin · daily · jupiter, tsmom_top20 · 3 coins · weekly · jupiter, tsmom_top20 · 5 coins · weekly · jupiter, breakout_top10 · 10 coins · daily · kraken (+47)
- 100 EUR: memes_rotation · 1 coin · weekly · kraken, memes_rotation · 1 coin · 3 days · kraken, tsmom_top20 · 1 coin · daily · jupiter, memes_rotation · 1 coin · daily · kraken, breakout_top10 · 1 coin · weekly · jupiter, breakout_sol · 1 coin · weekly · jupiter, tsmom_top20 · 3 coins · weekly · jupiter, trend_carry · 20 coins · daily · kraken (+51)
- 500 EUR: memes_rotation · 1 coin · weekly · kraken, memes_rotation · 1 coin · 3 days · kraken, tsmom_top20 · 1 coin · daily · jupiter, breakout_top10 · 10 coins · daily · kraken, memes_rotation · 1 coin · daily · kraken, breakout_top10 · 1 coin · weekly · jupiter, breakout_sol · 1 coin · weekly · jupiter, trend_carry · 3 coins · daily · jupiter (+50)

## 5. Capital needed (Kraken taker, best cadence and coins in sample at 10,000 EUR)

| variant | needed | 25 | 50 | 100 | 250 | 500 | 1,000 | 2,500 | 10,000 |
|---|---|---|---|---|---|---|---|---|---|
| btc_hold · 1 coin · daily | 25 EUR | 25.4 % / 0.4 % | 25.4 % / 0.4 % | 25.4 % / 0.4 % | 25.4 % / 0.4 % | 25.4 % / 0.4 % | 25.4 % / 0.4 % | 25.4 % / 0.4 % | 25.4 % / 0.4 % |
| btc_gated · 1 coin · weekly | 25 EUR | 22.6 % / 7.1 % | 22.6 % / 7.1 % | 22.6 % / 7.1 % | 22.6 % / 7.1 % | 22.6 % / 7.1 % | 22.6 % / 7.1 % | 22.6 % / 7.1 % | 22.6 % / 7.1 % |
| breakout_btceth · 1 coin · weekly | 25 EUR | 18.9 % / 10.6 % | 18.9 % / 10.6 % | 18.9 % / 10.6 % | 18.9 % / 10.6 % | 18.9 % / 10.6 % | 18.9 % / 10.6 % | 18.9 % / 10.6 % | 18.9 % / 10.6 % |
| breakout_top10 · 10 coins · daily | 250 EUR | 0.0 % / n/a | 16.0 % / 11.7 % | 16.2 % / 18.7 % | 21.7 % / 17.0 % | 22.2 % / 16.8 % | 22.2 % / 16.8 % | 22.2 % / 16.8 % | 22.2 % / 16.8 % |
| breakout_sol · 3 coins · daily | 25 EUR | 15.0 % / 22.9 % | 14.4 % / 26.6 % | 14.4 % / 26.6 % | 14.4 % / 26.6 % | 14.4 % / 26.6 % | 14.4 % / 26.6 % | 14.4 % / 26.6 % | 14.4 % / 26.6 % |
| tsmom_top20 · 1 coin · daily | 25 EUR | 21.1 % / 26.5 % | 22.1 % / 26.3 % | 21.9 % / 26.7 % | 21.9 % / 27.1 % | 21.6 % / 27.5 % | 21.6 % / 27.5 % | 21.6 % / 27.6 % | 21.6 % / 27.6 % |
| trend_carry · 20 coins · weekly | 500 EUR | 0.0 % / n/a | -0.2 % / n/a | 2.3 % / 20.0 % | 4.9 % / 26.9 % | 7.6 % / 22.8 % | 7.5 % / 23.3 % | 7.5 % / 23.5 % | 7.5 % / 23.7 % |
| memes_rotation · 1 coin · 3 days | 25 EUR | 39.2 % / 15.9 % | 38.3 % / 16.5 % | 37.1 % / 16.8 % | 36.3 % / 17.1 % | 36.6 % / 17.0 % | 36.5 % / 17.1 % | 36.5 % / 17.1 % | 36.5 % / 17.1 % |

Each rung: CAGR / cost share. Needed: the smallest rung from which every larger one keeps the costs under 50 % and the CAGR within 2 points of the 10,000 EUR run.

## 6. The two paper books (picked by in-sample Sharpe)

| book | variant | venue | IS Sharpe | CAGR | max DD | Sharpe | costs | orders/yr | not sent/yr | dust |
|---|---|---|---|---|---|---|---|---|---|---|
| 50 EUR | tsmom_top20 · 1 coin · daily | jupiter | 1.98 | 28.8 % | 17.2 % | 1.10 | 5.0 % | 30 | 97 | 0 |
| 100 EUR | breakout_sol · 3 coins · daily | jupiter | 1.88 | 18.2 % | 20.3 % | 0.92 | 5.3 % | 47 | 0 | 0 |

