# D3: the point-in-time feature store

Built 2026-10-27 01:49 UTC from the lab's data by `python -m lab.features report`. Each feature is known at the end of its bucket (an hour or a UTC day, by the time this machine received the raw row) plus its delay; `lab.features.frame` never returns a value later than that (tests/test_features.py changes every raw row after t and checks that nothing at or before t moves).

## Reading

- 25 of 32 features have data. The book, trade, perp and liquidation features start on 2026-09-30, when the
  recorder started (26 days of returns to score them on: 601 hours, 24 days); the D2 series do not exist yet.
- 10 of 48 tests pass Bonferroni. The strong ones are slow market series against the next hour (stablecoin supply
  growth and the Coinbase premium up, so coins go up next) and the known funding effect across coins (high
  funding, weaker next hour and next day). Among the new microstructure features only the published funding
  estimate and Kraken's trade realised vol pass, each on 601 hours from one month; nothing about the books does.
- An IC is a rank correlation, not a strategy after costs. Nothing here trades; the strategy factory can now draw
  `funding_8h`, `stables_chg7` and `coinbase_prem_bps` (data over half of its in-sample window) and every tree
  that uses them counts as a trial. The book features wait for a longer record.

## Features and coverage

| Feature | Sources | Native | Delay | Kind | From | To | Assets | Gap days | What |
|---|---|---|---|---|---|---|---|---|---|
| `funding_8h` | hist/binance_um/funding | 8h | 0 | coin | 2020-01-01 | 2026-10-25 | 898 | 0 | Binance USD-M settled funding: hourly the last rate on 8 h, daily the day's sum |
| `oi_chg` | hist/binance_um/metrics, binance_um/open_interest | 5m | 0 | coin | 2022-01-01 | 2026-10-27 | 20 | 0 | Binance USD-M open interest (contracts), change over the bucket |
| `oi_chg_24h` | hist/binance_um/metrics, binance_um/open_interest | 5m | 0 | coin | 2022-01-02 | 2026-10-27 | 20 | 1 (2024-02-17..2024-02-17) | Binance USD-M open interest, change over 24 hours |
| `dvol_btc` | flow/dvol | 1d | 1 h | market | 2021-03-25 | 2026-10-27 | 1 | 0 | Deribit BTC DVOL, daily close |
| `skew_rr25_btc` | flow/skew | 1d | 0 | market | 2026-10-16 | 2026-10-28 | 1 | 0 | Deribit BTC 25-delta risk reversal at 30 days (snapshot) |
| `stables_chg7` | flow/stables | 1d | 1 h | market | 2017-12-07 | 2026-10-27 | 1 | 0 | DefiLlama stablecoin supply, change over 7 days |
| `coinbase_prem_bps` | flow/coinbase_btcusd_1h, hist/binance_spot/klines_1h | 1h | 0 | market | 2020-01-01 | 2026-10-26 | 1 | 0 | Coinbase BTC-USD over Binance BTCUSDT close, bp |
| `fear_greed` | flow/fear_greed | 1d | 1 h | market | no data |  | 0 |  | D2: Fear and Greed index |
| `hl_funding` | flow/hyperliquid_funding | 1h | 0 | coin | no data |  | 0 |  | D2: Hyperliquid funding rate |
| `macro_dxy_chg5` | flow/macro | 1d | 0 | market | no data |  | 0 |  | D2: dxy change over 5 days |
| `macro_us10y_chg5` | flow/macro | 1d | 0 | market | no data |  | 0 |  | D2: us10y change over 5 days (difference) |
| `macro_spx_chg5` | flow/macro | 1d | 0 | market | no data |  | 0 |  | D2: spx change over 5 days |
| `macro_vix_chg5` | flow/macro | 1d | 0 | market | no data |  | 0 |  | D2: vix change over 5 days |
| `event_next24h` | flow/events | 1d | 0 | market | no data |  | 0 |  | D2: scheduled events in the next 24 hours, known by then |
| `spread_bps` | binance/book20 | 5s | 0 | coin | 2026-09-30 | 2026-10-27 | 20 | 0 | binance spot: mean quoted spread (ask - bid) / mid, bp |
| `depth10_usd` | binance/book20 | 5s | 0 | level | 2026-09-30 | 2026-10-27 | 20 | 0 | binance spot: mean notional within 10 bp of the mid, both sides |
| `depth50_usd` | binance/book20 | 5s | 0 | level | 2026-09-30 | 2026-10-27 | 20 | 0 | binance spot: mean notional within 50 bp of the mid (20 levels at most) |
| `book_imb` | binance/book20 | 5s | 0 | coin | 2026-09-30 | 2026-10-27 | 20 | 0 | binance spot: mean (bid - ask) / (bid + ask) of the 50 bp notional |
| `book_imb_chg` | binance/book20 | 5s | 0 | coin | 2026-10-01 | 2026-10-27 | 20 | 0 | binance spot: book_imb minus the bucket before (none after a gap) |
| `kraken_spread_bps` | kraken/book20 | 5s | 0 | coin | 2026-09-30 | 2026-10-27 | 20 | 0 | kraken spot: mean quoted spread (ask - bid) / mid, bp |
| `kraken_depth10_usd` | kraken/book20 | 5s | 0 | level | 2026-09-30 | 2026-10-27 | 20 | 0 | kraken spot: mean notional within 10 bp of the mid, both sides |
| `kraken_depth50_usd` | kraken/book20 | 5s | 0 | level | 2026-09-30 | 2026-10-27 | 20 | 0 | kraken spot: mean notional within 50 bp of the mid (20 levels at most) |
| `kraken_book_imb` | kraken/book20 | 5s | 0 | coin | 2026-09-30 | 2026-10-27 | 20 | 0 | kraken spot: mean (bid - ask) / (bid + ask) of the 50 bp notional |
| `kraken_book_imb_chg` | kraken/book20 | 5s | 0 | coin | 2026-10-01 | 2026-10-27 | 20 | 0 | kraken spot: book_imb minus the bucket before (none after a gap) |
| `xvenue_disp_bps` | binance/book20, kraken/book20, bybit/book20, okx/book20, coinbase/book20 | 5s | 0 | coin | 2026-09-30 | 2026-10-27 | 20 | 0 | (max - min) / median of the five venues' minute mids in USD, bp, mean |
| `trade_imb` | kraken/trades | trade | 0 | coin | 2026-09-30 | 2026-10-27 | 20 | 0 | Kraken: (taker buy - taker sell) / both, notional |
| `trade_usd` | kraken/trades | trade | 0 | level | 2026-09-30 | 2026-10-27 | 20 | 0 | Kraken: traded notional, USD |
| `rv_trades` | kraken/trades | trade | 0 | coin | 2026-09-30 | 2026-10-27 | 20 | 0 | Kraken: realised vol from 1-minute trade prices, annualised |
| `funding_est` | binance_um/premium | 60s | 0 | coin | 2026-09-30 | 2026-10-27 | 20 | 0 | Binance USD-M: funding rate as published at the bucket's end |
| `premium_bps` | binance_um/premium | 60s | 0 | coin | 2026-09-30 | 2026-10-27 | 20 | 0 | Binance USD-M: mark over index, bp, mean |
| `liq_long_usd` | binance_um/liquidations | trade | 0 | level | 2026-09-30 | 2026-10-27 | 756 | 0 | Binance USD-M: longs liquidated, notional |
| `liq_short_usd` | binance_um/liquidations | trade | 0 | level | 2026-09-30 | 2026-10-27 | 756 | 0 | Binance USD-M: shorts liquidated, notional |

## Rank IC against the next hour and the next day

48 tests (every feature and horizon with data). Coin features: mean cross-sectional Spearman over the 20 lab coins; market features: Spearman over time against the coins' equal-weighted next return. Significant at 5 % after Bonferroni (p < 0.00104): 10; after Benjamini-Hochberg: 12.

| Feature | Horizon | IC | t | p | Points | From | To | Bonferroni | BH |
|---|---|---|---|---|---|---|---|---|---|
| `stables_chg7` | next hour | +0.0309 | +6.11 | 0.0000 | 59,713 | 2020-01-01 | 2026-10-25 | yes | yes |
| `coinbase_prem_bps` | next hour | +0.0284 | +6.01 | 0.0000 | 59,697 | 2020-01-01 | 2026-10-25 | yes | yes |
| `funding_est` | next hour | -0.0313 | -5.81 | 0.0000 | 601 | 2026-09-30 | 2026-10-25 | yes | yes |
| `funding_8h` | next hour | -0.0058 | -5.60 | 0.0000 | 58,704 | 2020-01-09 | 2026-10-25 | yes | yes |
| `dvol_btc` | next hour | +0.0234 | +4.91 | 0.0000 | 48,966 | 2021-03-25 | 2026-10-25 | yes | yes |
| `oi_chg` | next hour | -0.0062 | -4.48 | 0.0000 | 42,156 | 2022-01-01 | 2026-10-25 | yes | yes |
| `funding_8h` | next day | -0.0216 | -3.84 | 0.0001 | 2,473 | 2020-01-10 | 2026-10-25 | yes | yes |
| `rv_trades` | next hour | -0.0294 | -3.82 | 0.0001 | 601 | 2026-09-30 | 2026-10-25 | yes | yes |
| `stables_chg7` | next day | +0.0735 | +3.47 | 0.0005 | 2,489 | 2020-01-02 | 2026-10-25 | yes | yes |
| `oi_chg_24h` | next hour | -0.0042 | -3.42 | 0.0006 | 42,078 | 2022-01-02 | 2026-10-25 | yes | yes |
| `liq_short_usd` | next hour | -0.0123 | -2.71 | 0.0068 | 601 | 2026-09-30 | 2026-10-25 | no | yes |
| `kraken_book_imb_chg` | next day | -0.0751 | -2.65 | 0.0080 | 23 | 2026-10-03 | 2026-10-25 | no | yes |
| `funding_est` | next day | -0.0760 | -2.36 | 0.0183 | 24 | 2026-10-02 | 2026-10-25 | no | no |
| `dvol_btc` | next day | +0.0510 | +2.26 | 0.0239 | 2,040 | 2021-03-26 | 2026-10-25 | no | no |
| `depth50_usd` | next hour | +0.0243 | +1.94 | 0.0529 | 601 | 2026-09-30 | 2026-10-25 | no | no |
| `kraken_depth50_usd` | next hour | +0.0120 | +1.93 | 0.0541 | 601 | 2026-09-30 | 2026-10-25 | no | no |
| `kraken_book_imb` | next day | -0.1133 | -1.88 | 0.0600 | 24 | 2026-10-02 | 2026-10-25 | no | no |
| `liq_long_usd` | next day | +0.0520 | +1.88 | 0.0603 | 24 | 2026-10-02 | 2026-10-25 | no | no |
| `coinbase_prem_bps` | next day | +0.0397 | +1.86 | 0.0625 | 2,489 | 2020-01-02 | 2026-10-25 | no | no |
| `kraken_spread_bps` | next hour | -0.0187 | -1.86 | 0.0629 | 601 | 2026-09-30 | 2026-10-25 | no | no |
| `depth10_usd` | next hour | +0.0150 | +1.71 | 0.0870 | 601 | 2026-09-30 | 2026-10-25 | no | no |
| `book_imb_chg` | next day | +0.0653 | +1.54 | 0.1227 | 23 | 2026-10-03 | 2026-10-25 | no | no |
| `premium_bps` | next hour | -0.0120 | -1.52 | 0.1281 | 601 | 2026-09-30 | 2026-10-25 | no | no |
| `kraken_book_imb` | next hour | -0.0133 | -1.51 | 0.1302 | 601 | 2026-09-30 | 2026-10-25 | no | no |
| `depth50_usd` | next day | +0.0967 | +1.42 | 0.1557 | 24 | 2026-10-02 | 2026-10-25 | no | no |
| `rv_trades` | next day | -0.1079 | -1.41 | 0.1593 | 24 | 2026-10-02 | 2026-10-25 | no | no |
| `oi_chg` | next day | -0.0072 | -1.20 | 0.2298 | 1,753 | 2022-01-03 | 2026-10-25 | no | no |
| `kraken_depth50_usd` | next day | +0.0338 | +1.15 | 0.2514 | 24 | 2026-10-02 | 2026-10-25 | no | no |
| `kraken_spread_bps` | next day | -0.0672 | -1.04 | 0.2999 | 24 | 2026-10-02 | 2026-10-25 | no | no |
| `xvenue_disp_bps` | next hour | -0.0130 | -0.99 | 0.3212 | 601 | 2026-09-30 | 2026-10-25 | no | no |
| `depth10_usd` | next day | +0.0532 | +0.99 | 0.3221 | 24 | 2026-10-02 | 2026-10-25 | no | no |
| `kraken_depth10_usd` | next hour | +0.0092 | +0.98 | 0.3249 | 601 | 2026-09-30 | 2026-10-25 | no | no |
| `trade_imb` | next hour | +0.0078 | +0.92 | 0.3581 | 601 | 2026-09-30 | 2026-10-25 | no | no |
| `book_imb_chg` | next hour | +0.0085 | +0.81 | 0.4207 | 600 | 2026-10-01 | 2026-10-25 | no | no |
| `xvenue_disp_bps` | next day | -0.0534 | -0.72 | 0.4742 | 24 | 2026-10-02 | 2026-10-25 | no | no |
| `spread_bps` | next hour | -0.0057 | -0.70 | 0.4818 | 601 | 2026-09-30 | 2026-10-25 | no | no |
| `kraken_depth10_usd` | next day | +0.0274 | +0.57 | 0.5715 | 24 | 2026-10-02 | 2026-10-25 | no | no |
| `trade_imb` | next day | -0.0247 | -0.45 | 0.6536 | 24 | 2026-10-02 | 2026-10-25 | no | no |
| `trade_usd` | next day | -0.0143 | -0.44 | 0.6591 | 24 | 2026-10-02 | 2026-10-25 | no | no |
| `kraken_book_imb_chg` | next hour | +0.0030 | +0.44 | 0.6631 | 600 | 2026-10-01 | 2026-10-25 | no | no |
| `skew_rr25_btc` | next hour | -0.0129 | -0.43 | 0.6641 | 245 | 2026-10-15 | 2026-10-25 | no | no |
| `liq_long_usd` | next hour | +0.0032 | +0.42 | 0.6729 | 601 | 2026-09-30 | 2026-10-25 | no | no |
| `spread_bps` | next day | -0.0115 | -0.36 | 0.7193 | 24 | 2026-10-02 | 2026-10-25 | no | no |
| `premium_bps` | next day | -0.0306 | -0.35 | 0.7262 | 24 | 2026-10-02 | 2026-10-25 | no | no |
| `liq_short_usd` | next day | +0.0053 | +0.17 | 0.8686 | 24 | 2026-10-02 | 2026-10-25 | no | no |
| `book_imb` | next day | +0.0118 | +0.14 | 0.8919 | 24 | 2026-10-02 | 2026-10-25 | no | no |
| `book_imb` | next hour | -0.0006 | -0.07 | 0.9419 | 601 | 2026-09-30 | 2026-10-25 | no | no |
| `trade_usd` | next hour | -0.0003 | -0.05 | 0.9629 | 601 | 2026-09-30 | 2026-10-25 | no | no |

No data yet (the D2 collectors have not written these files): `fear_greed`, `hl_funding`, `macro_dxy_chg5`, `macro_us10y_chg5`, `macro_spx_chg5`, `macro_vix_chg5`, `event_next24h`.
