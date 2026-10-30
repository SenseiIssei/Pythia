# M4H: the M4 reg7n long/short at a 200 EUR account on Hyperliquid, after every cost

Pre-registered in `results/m4h_prereg.md`, run as M4H2 (`results/m4h2_prereg.md`), each committed before its first
run. Code: `lab.experiments.m4h`, tests `tests/test_m4h.py`; the paper book `lab.paper.m4_hl_small` and the dry-run
executor `lab.paper.hl_dryrun`, tests `tests/test_m4_hl_small.py`. Paper only: nothing a live bot, a wallet or the
engine reads changed; no key, no account, no order sent.

Run 2026-10-30, the lockbox not read. 97 trials in R5's registry (small family, with their in-sample Sharpes,
written to a copy in the agent run; the server's registry gets them from it). Data: xs_daily's panel in
`<data>/lab-cache` cut at 2026-06-30, Binance spot 1-hour bars for the 02:00 fill and the spread proxy, T12b's
Hyperliquid listing history and hourly funding, Hyperliquid's public `meta` for the size decimals, `<data>/etf/daily`.

## Reading

**Yes, on the record: reg7n can run at 230 USD on Hyperliquid, and the 10/10 book passes every registered check
there. It is not confirmed (DSR 0.024), so it starts as a paper book with dry-run orders, not with money.**

- **What it made.** 10 long and 10 short of the coins Hyperliquid lists, 1x, taker, filled at 01:00 UTC: 230 USD
  became 784 USD from 2024-01 to 2026-06 (Sharpe 1.79, 64 % a year, drawdown 20.0 %, worst month 2024-03 at
  -10.6 %, 8 of 30 months negative). In EUR: about **+111 EUR a year** on 200 EUR, bootstrap band +61 to +157. One
  hour later (02:00) it is the same (1.80); maker fees add little (1.83).
- **Against an ETF the same days**: 200 EUR in the MSCI World fund EUNL became 301 EUR (Sharpe 1.26, drawdown
  21.7 %), in SPY 309 EUR, in BTC 255 EUR (drawdown 52 %). The book made almost five times the ETF's gain, with a
  similar worst fall, and did not need a rising market (BTC fell 33 % in 2026 to June, the book made 19.5 %).
- **The 10 USD minimum is not the problem at 230 USD.** An entry is 5 % of the account, 11.5 USD: every one of 507
  entries was sent; 110 of 125 cut-backs (a winner trimmed to 10 %) were under 10 USD and skipped, so the account
  drifts 0.7 % from the ideal book (correlation 0.999). At 115 USD nothing is sent (5.75 USD an entry); at 460 USD
  it is the ideal book (1.81). Below about 200 USD of equity the entries start to fall under the minimum.
- **Fees are small, funding is not.** Fees 0.8 % and slippage 0.8 % of the account a year, Hyperliquid's funding
  10.4 % (about twice Binance's rates on the same coins): without funding the Sharpe would be 2.02.
- **Why only k 10.** Three or five names a side make as much or more (k 5: 952 USD) but fall 28 to 35 % from a peak,
  the ideal account too: the drawdown check fails, not the edge. 2x doubles the return and the drawdown (38 % at
  k 10) and fails too.

What tempers it, plainly:

- **The window is not fresh.** 2024 to 2026-06 is the holdout reg7n was picked on (m4_funding) and judged on
  (m4_residual); a pass here repeats that holdout at a real account size, it does not renew it. Deflated against
  the registry's 4,275 trials the DSR is 0.024 (0.47 against the small family's 749).
- **The signal's own record moves with the panel.** M4H stopped as registered: the refit 10/10 book on Binance made
  a 2022-2023 Sharpe of 1.30 against the published 0.93 (2022 3.12 against 1.91; T6b's refit 0.69). M4H2 reran
  without the stop (registered first, before any trial or out-of-sample number).
- **Binance prices stand in for Hyperliquid's**, the forward book fills about 06:00 UTC (not 01:00), and the
  low-vol factor carries much of reg7n (m4_residual).

## What now

1. **Paper book `m4_hl_small`** (job `paper-m4-hl-small`, daily 06:00 UTC): 230 USD, 10/10, on Hyperliquid's
   public mids, size decimals and hourly funding, with the orders a bot would send in `orders/<date>.json`.
   Its journal is the forward record; the forward report picks it up. The ladder's A4 route starts a promoted
   shadow only from step 2, which needs a DSR of 0.95: this book does not get one, its own journal is the record.
2. **Dry-run executor `lab.paper.hl_dryrun`**: exact orders (coin, side, size after rounding, IOC limit 1 % through
   the mid, reduce-only on closes and cuts) behind hard limits in code: sized on at most 250 USD, gross at most 2x
   or nothing is sent, flat and stopped for good at -20 % from the start, the file `GO_FLAT` in the book's folder to
   go flat, the 10 USD minimum. No key, no signing, nothing sent; a test for every limit.
3. **Going live** needs the owner's yes after at least 30 days of this forward record and an API wallet he makes
   himself. Not part of this study.

<!-- generated below by lab.experiments.m4h; edit above this line only -->

Generated 2026-10-30T17:05:32+00:00. xs_daily's panel cut at 2026-06-30, reg7n refit walk-forward (T6b), nothing from 2026-07-01 read. In sample 2022-01-01 to 2023-12-31 (730 days, Binance universe, Binance funding); judged 2024-01-01 to 2026-06-28 (910 decision days) on the coins Hyperliquid lists of the 100 most liquid perps (mean 73 a day, at least 56), Hyperliquid's own funding on 100 % of those coin-days. 97 trials in R5's registry (small family, with their in-sample Sharpes, registered before any out-of-sample number); pool 4,275, noise bar 3.05 a year (small 749, 1.83).

Check, reported (M4H2; M4H stopped on it): the rebuilt 10/10 book on Binance at 41 bps makes a 2022-2023 Sharpe of 1.30 (m4_residual 0.93; 2022 3.12, 2023 -0.04), 2024 1.09 (1.67), 2025 2.47 (2.43).

Passed (230 USD, taker, on time, 1x): 230usd:k10:g1:base:taker. Paper book k: 230usd:k10:g1:base:taker; confirmed (DSR at least 0.95): no. Why, by k: k 3: drawdown (the ideal account's too), k 5: drawdown (the ideal account's too), k 10: pass.

## What 230 USD made, against 200 EUR in an ETF, the same days

| cell | end USD | EUR gained | EUR a year (5 % to 95 %) | worst month | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|---|
| 230usd:k3:g1:base:taker | 742 | +441 | +119 (+47 to +184) | 2024-09 -23.6 % | 56.5 % | 64.8 % | 25.1 % |
| 230usd:k5:g1:base:taker | 952 | +624 | +132 (+75 to +185) | 2024-09 -13.5 % | 56.4 % | 91.7 % | 38.0 % |
| 230usd:k10:g1:base:taker | 784 | +478 | +111 (+61 to +157) | 2024-03 -10.6 % | 75.2 % | 62.8 % | 19.5 % |
| 230usd:k3:g1:late:taker | 711 | +413 | +114 (+42 to +181) | 2024-09 -24.2 % | 53.6 % | 59.2 % | 26.4 % |
| 230usd:k5:g1:late:taker | 944 | +618 | +131 (+73 to +185) | 2024-09 -13.8 % | 58.4 % | 87.2 % | 38.4 % |
| 230usd:k10:g1:late:taker | 777 | +471 | +110 (+60 to +157) | 2024-09 -9.9 % | 77.6 % | 59.3 % | 19.4 % |

| held | Sharpe | CAGR | max DD | 200 EUR became | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|---|
| BTC | 0.48 | 12.1 % | 52.2 % | 255 EUR | 111.1 % | -6.6 % | -32.6 % |
| SPY | 1.27 | 20.9 % | 18.8 % | 309 EUR | 24.9 % | 17.7 % | 9.2 % |
| EUNL | 1.26 | 17.8 % | 21.7 % | 301 EUR | 25.9 % | 7.9 % | 10.8 % |

EUR at the day's rate (mean 1.1180); the ETFs' years in their own currency (EUNL EUR, SPY and BTC USD), 200 EUR in EUR. EUR a year: the mean daily return x 365 x 230 USD at the window's mean rate, the band the 5 % and 95 % of its stationary bootstrap.

## The judged cells and their siblings (out of sample)

Drift: the mean of half the sum of |account weight - ideal weight|; skipped: the share of wanted entries the 10 USD minimum (or rounding to zero) did not send; fees, slippage and funding as a share of equity a year; DSR over all trials.


### 230usd, gross 1x

| cell | Sharpe | CAGR | max DD | end | worst month | boot 5 % | corr ideal | drift | skipped | cuts skipped | fees/yr | slip/yr | funding/yr | DSR | IS Sharpe | fails |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 230usd:k3:g1:base:taker | 1.26 | 60.0 % | 34.7 % | 742.12 | -23.6 % | 0.46 | 1.00 | 0.00 | 0.0 % | 20 | 0.5 % | 0.5 % | 11.7 % | 0.003 | 0.88 | drawdown under 25 % |
| 230usd:k3:g1:base:maker | 1.28 | 61.5 % | 34.7 % | 760.31 | -23.4 % | 0.48 | 1.00 | 0.00 | 0.0 % | 21 | 0.2 % | 0.0 % | 11.7 % | 0.003 | 0.91 | drawdown under 25 % |
| 230usd:k3:g1:late:taker | 1.23 | 57.2 % | 35.8 % | 710.90 | -24.2 % | 0.42 | 1.00 | 0.00 | 0.0 % | 24 | 0.5 % | 0.6 % | 11.3 % | 0.003 | 0.80 | drawdown under 25 % |
| 230usd:k3:g1:late:maker | 1.25 | 58.8 % | 35.8 % | 729.09 | -24.1 % | 0.44 | 1.00 | 0.00 | 0.0 % | 22 | 0.2 % | 0.0 % | 11.3 % | 0.003 | 0.83 | drawdown under 25 % |
| 230usd:k5:g1:base:taker | 1.69 | 76.7 % | 27.6 % | 951.51 | -13.5 % | 0.90 | 1.00 | 0.00 | 0.0 % | 20 | 0.6 % | 0.6 % | 11.6 % | 0.018 | 0.81 | drawdown under 25 % |
| 230usd:k5:g1:base:maker | 1.72 | 78.5 % | 27.6 % | 975.13 | -13.4 % | 0.92 | 1.00 | 0.00 | 0.0 % | 19 | 0.2 % | 0.0 % | 11.6 % | 0.020 | 0.85 | drawdown under 25 % |
| 230usd:k5:g1:late:taker | 1.70 | 76.2 % | 27.0 % | 944.04 | -13.8 % | 0.90 | 1.00 | 0.00 | 0.0 % | 20 | 0.6 % | 0.6 % | 11.2 % | 0.018 | 0.75 | drawdown under 25 % |
| 230usd:k5:g1:late:maker | 1.72 | 77.8 % | 27.0 % | 965.95 | -13.8 % | 0.92 | 1.00 | 0.00 | 0.0 % | 18 | 0.2 % | 0.0 % | 11.2 % | 0.020 | 0.79 | drawdown under 25 % |
| 230usd:k10:g1:base:taker | 1.79 | 63.6 % | 20.0 % | 784.30 | -10.6 % | 0.97 | 1.00 | 0.01 | 0.0 % | 110 | 0.8 % | 0.8 % | 10.4 % | 0.024 | 1.58 | pass |
| 230usd:k10:g1:base:maker | 1.83 | 65.8 % | 19.8 % | 810.96 | -10.4 % | 1.01 | 1.00 | 0.01 | 0.0 % | 112 | 0.3 % | 0.0 % | 10.4 % | 0.029 | 1.64 | pass |
| 230usd:k10:g1:late:taker | 1.80 | 62.9 % | 19.8 % | 776.94 | -9.9 % | 0.96 | 1.00 | 0.01 | 0.0 % | 110 | 0.8 % | 0.8 % | 10.2 % | 0.025 | 1.54 | pass |
| 230usd:k10:g1:late:maker | 1.84 | 65.1 % | 19.5 % | 802.95 | -9.9 % | 1.01 | 1.00 | 0.01 | 0.0 % | 110 | 0.3 % | 0.0 % | 10.3 % | 0.029 | 1.60 | pass |

### 230usd, gross 2x

| cell | Sharpe | CAGR | max DD | end | worst month | boot 5 % | corr ideal | drift | skipped | cuts skipped | fees/yr | slip/yr | funding/yr | DSR | IS Sharpe | fails |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 230usd:k3:g2:base:taker | 1.35 | 122.0 % | 59.2 % | 1680.42 | -43.2 % | 0.56 | 1.00 | 0.00 | 0.0 % | 11 | 0.9 % | 1.1 % | 23.5 % | 0.005 | 0.98 | drawdown under 25 % |
| 230usd:k3:g2:base:maker | 1.37 | 126.3 % | 58.9 % | 1761.92 | -43.0 % | 0.58 | 1.00 | 0.00 | 0.0 % | 9 | 0.3 % | 0.0 % | 23.5 % | 0.005 | 1.01 | drawdown under 25 % |
| 230usd:k3:g2:late:taker | 1.32 | 115.6 % | 60.6 % | 1561.25 | -43.5 % | 0.51 | 1.00 | 0.00 | 0.0 % | 9 | 0.9 % | 1.1 % | 22.7 % | 0.004 | 0.91 | drawdown under 25 % |
| 230usd:k3:g2:late:maker | 1.35 | 119.6 % | 60.4 % | 1634.47 | -43.3 % | 0.53 | 1.00 | 0.00 | 0.0 % | 8 | 0.3 % | 0.0 % | 22.7 % | 0.005 | 0.94 | drawdown under 25 % |
| 230usd:k5:g2:base:taker | 1.76 | 182.6 % | 51.6 % | 3064.94 | -26.4 % | 0.96 | 1.00 | 0.00 | 0.0 % | 10 | 1.0 % | 1.1 % | 25.3 % | 0.023 | 0.81 | drawdown under 25 % |
| 230usd:k5:g2:base:maker | 1.78 | 187.7 % | 51.6 % | 3204.99 | -26.2 % | 0.99 | 1.00 | 0.00 | 0.0 % | 11 | 0.3 % | 0.0 % | 25.4 % | 0.025 | 0.85 | drawdown under 25 % |
| 230usd:k5:g2:late:taker | 1.75 | 178.1 % | 49.9 % | 2945.98 | -26.7 % | 0.94 | 1.00 | 0.00 | 0.0 % | 12 | 1.1 % | 1.1 % | 24.4 % | 0.023 | 0.77 | drawdown under 25 % |
| 230usd:k5:g2:late:maker | 1.78 | 183.9 % | 49.8 % | 3102.33 | -26.5 % | 0.97 | 1.00 | 0.00 | 0.0 % | 13 | 0.3 % | 0.0 % | 24.5 % | 0.025 | 0.80 | drawdown under 25 % |
| 230usd:k10:g2:base:taker | 1.83 | 146.7 % | 38.0 % | 2184.48 | -20.0 % | 1.00 | 1.00 | 0.00 | 0.0 % | 38 | 1.5 % | 1.4 % | 23.8 % | 0.029 | 1.64 | drawdown under 25 % |
| 230usd:k10:g2:base:maker | 1.88 | 153.6 % | 37.6 % | 2339.54 | -19.6 % | 1.05 | 1.00 | 0.00 | 0.0 % | 38 | 0.5 % | 0.0 % | 23.9 % | 0.035 | 1.69 | drawdown under 25 % |
| 230usd:k10:g2:late:taker | 1.85 | 146.7 % | 36.3 % | 2184.67 | -19.2 % | 1.01 | 1.00 | 0.01 | 0.0 % | 26 | 1.5 % | 1.4 % | 23.4 % | 0.030 | 1.57 | drawdown under 25 % |
| 230usd:k10:g2:late:maker | 1.90 | 153.2 % | 36.2 % | 2331.87 | -18.9 % | 1.06 | 1.00 | 0.01 | 0.0 % | 26 | 0.5 % | 0.0 % | 23.5 % | 0.036 | 1.62 | drawdown under 25 % |

### 115usd, gross 1x

| cell | Sharpe | CAGR | max DD | end | worst month | boot 5 % | corr ideal | drift | skipped | cuts skipped | fees/yr | slip/yr | funding/yr | DSR | IS Sharpe | fails |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 115usd:k3:g1:base:taker | 1.28 | 62.2 % | 34.2 % | 384.23 | -23.6 % | 0.50 | 1.00 | 0.01 | 0.0 % | 27 | 0.5 % | 0.5 % | 11.7 % | 0.003 | 0.90 | drawdown under 25 % |
| 115usd:k3:g1:base:maker | 1.30 | 64.0 % | 33.7 % | 394.97 | -23.7 % | 0.52 | 1.00 | 0.01 | 0.0 % | 27 | 0.2 % | 0.0 % | 11.7 % | 0.004 | 0.93 | drawdown under 25 % |
| 115usd:k3:g1:late:taker | 1.24 | 58.3 % | 36.3 % | 361.26 | -24.3 % | 0.43 | 1.00 | 0.01 | 0.0 % | 27 | 0.5 % | 0.5 % | 11.3 % | 0.003 | 0.78 | drawdown under 25 % |
| 115usd:k3:g1:late:maker | 1.25 | 58.8 % | 36.7 % | 364.18 | -24.2 % | 0.44 | 1.00 | 0.01 | 0.0 % | 25 | 0.2 % | 0.0 % | 11.3 % | 0.003 | 0.81 | drawdown under 25 % |
| 115usd:k5:g1:base:taker | 1.71 | 79.6 % | 27.6 % | 495.17 | -13.8 % | 0.92 | 1.00 | 0.01 | 0.0 % | 37 | 0.6 % | 0.6 % | 11.5 % | 0.019 | 0.78 | drawdown under 25 % |
| 115usd:k5:g1:base:maker | 1.73 | 81.1 % | 27.6 % | 505.77 | -13.6 % | 0.94 | 1.00 | 0.01 | 0.0 % | 35 | 0.2 % | 0.0 % | 11.5 % | 0.020 | 0.80 | drawdown under 25 % |
| 115usd:k5:g1:late:taker | 1.65 | 73.8 % | 27.3 % | 456.49 | -13.9 % | 0.85 | 1.00 | 0.01 | 0.0 % | 28 | 0.6 % | 0.6 % | 11.1 % | 0.015 | 0.74 | drawdown under 25 % |
| 115usd:k5:g1:late:maker | 1.67 | 75.0 % | 27.3 % | 464.18 | -14.0 % | 0.86 | 1.00 | 0.01 | 0.0 % | 29 | 0.2 % | 0.0 % | 11.1 % | 0.016 | 0.77 | drawdown under 25 % |
| 115usd:k10:g1:base:taker | 0.00 | 0.0 % | 0.0 % | 115.00 | 0.0 % | 0.00 | 0.00 | 0.48 | 100.0 % | 0 | 0.0 % | 0.0 % | 0.0 % | 0.000 | 0.00 | Sharpe above 1.0; bootstrap 5 % above 0; positive in 2024, 2025 and 2026; correlation to the ideal book above 0.8 |
| 115usd:k10:g1:base:maker | 0.00 | 0.0 % | 0.0 % | 115.00 | 0.0 % | 0.00 | 0.00 | 0.47 | 100.0 % | 0 | 0.0 % | 0.0 % | 0.0 % | 0.000 | 0.00 | Sharpe above 1.0; bootstrap 5 % above 0; positive in 2024, 2025 and 2026; correlation to the ideal book above 0.8 |
| 115usd:k10:g1:late:taker | 0.00 | 0.0 % | 0.0 % | 115.00 | 0.0 % | 0.00 | 0.00 | 0.48 | 100.0 % | 0 | 0.0 % | 0.0 % | 0.0 % | 0.000 | 0.00 | Sharpe above 1.0; bootstrap 5 % above 0; positive in 2024, 2025 and 2026; correlation to the ideal book above 0.8 |
| 115usd:k10:g1:late:maker | 0.00 | 0.0 % | 0.0 % | 115.00 | 0.0 % | 0.00 | 0.00 | 0.48 | 100.0 % | 0 | 0.0 % | 0.0 % | 0.0 % | 0.000 | 0.00 | Sharpe above 1.0; bootstrap 5 % above 0; positive in 2024, 2025 and 2026; correlation to the ideal book above 0.8 |

### 115usd, gross 2x

| cell | Sharpe | CAGR | max DD | end | worst month | boot 5 % | corr ideal | drift | skipped | cuts skipped | fees/yr | slip/yr | funding/yr | DSR | IS Sharpe | fails |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 115usd:k3:g2:base:taker | 1.35 | 122.2 % | 59.2 % | 842.14 | -43.4 % | 0.56 | 1.00 | 0.00 | 0.0 % | 12 | 0.9 % | 1.1 % | 23.5 % | 0.005 | 0.98 | drawdown under 25 % |
| 115usd:k3:g2:base:maker | 1.37 | 126.1 % | 59.0 % | 879.39 | -43.2 % | 0.58 | 1.00 | 0.00 | 0.0 % | 12 | 0.3 % | 0.0 % | 23.5 % | 0.005 | 1.01 | drawdown under 25 % |
| 115usd:k3:g2:late:taker | 1.34 | 118.5 % | 60.5 % | 807.52 | -43.4 % | 0.53 | 1.00 | 0.00 | 0.0 % | 14 | 0.9 % | 1.1 % | 22.8 % | 0.004 | 0.91 | drawdown under 25 % |
| 115usd:k3:g2:late:maker | 1.36 | 122.0 % | 60.5 % | 840.04 | -43.1 % | 0.55 | 1.00 | 0.00 | 0.0 % | 13 | 0.3 % | 0.0 % | 22.8 % | 0.005 | 0.95 | drawdown under 25 % |
| 115usd:k5:g2:base:taker | 1.75 | 181.2 % | 51.7 % | 1514.66 | -27.3 % | 0.95 | 1.00 | 0.01 | 0.0 % | 18 | 1.0 % | 1.1 % | 25.3 % | 0.022 | 0.81 | drawdown under 25 % |
| 115usd:k5:g2:base:maker | 1.78 | 187.1 % | 51.6 % | 1594.85 | -27.0 % | 0.98 | 1.00 | 0.01 | 0.0 % | 18 | 0.3 % | 0.0 % | 25.3 % | 0.025 | 0.85 | drawdown under 25 % |
| 115usd:k5:g2:late:taker | 1.75 | 178.2 % | 49.9 % | 1474.09 | -26.9 % | 0.94 | 1.00 | 0.01 | 0.0 % | 13 | 1.1 % | 1.1 % | 24.4 % | 0.022 | 0.78 | drawdown under 25 % |
| 115usd:k5:g2:late:maker | 1.78 | 183.4 % | 49.8 % | 1543.63 | -26.8 % | 0.97 | 1.00 | 0.01 | 0.0 % | 14 | 0.3 % | 0.0 % | 24.4 % | 0.025 | 0.82 | drawdown under 25 % |
| 115usd:k10:g2:base:taker | 1.84 | 149.7 % | 37.9 % | 1125.41 | -19.4 % | 1.02 | 1.00 | 0.01 | 0.0 % | 64 | 1.5 % | 1.4 % | 23.8 % | 0.030 | 1.64 | drawdown under 25 % |
| 115usd:k10:g2:base:maker | 1.89 | 157.4 % | 37.6 % | 1214.35 | -19.0 % | 1.07 | 1.00 | 0.01 | 0.0 % | 70 | 0.5 % | 0.0 % | 24.0 % | 0.036 | 1.71 | drawdown under 25 % |
| 115usd:k10:g2:late:taker | 1.83 | 145.0 % | 37.5 % | 1073.58 | -19.4 % | 0.98 | 1.00 | 0.01 | 0.0 % | 49 | 1.5 % | 1.4 % | 23.3 % | 0.028 | 1.58 | drawdown under 25 % |
| 115usd:k10:g2:late:maker | 1.87 | 151.4 % | 37.3 % | 1144.99 | -19.2 % | 1.02 | 1.00 | 0.01 | 0.0 % | 45 | 0.5 % | 0.0 % | 23.4 % | 0.033 | 1.63 | drawdown under 25 % |

### 460usd, gross 1x

| cell | Sharpe | CAGR | max DD | end | worst month | boot 5 % | corr ideal | drift | skipped | cuts skipped | fees/yr | slip/yr | funding/yr | DSR | IS Sharpe | fails |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 460usd:k3:g1:base:taker | 1.26 | 59.7 % | 34.7 % | 1476.74 | -23.6 % | 0.46 | 1.00 | 0.00 | 0.0 % | 9 | 0.5 % | 0.6 % | 11.7 % | 0.003 | 0.88 | drawdown under 25 % |
| 460usd:k3:g1:base:maker | 1.28 | 61.3 % | 34.5 % | 1513.96 | -23.4 % | 0.48 | 1.00 | 0.00 | 0.0 % | 9 | 0.2 % | 0.0 % | 11.7 % | 0.003 | 0.91 | drawdown under 25 % |
| 460usd:k3:g1:late:taker | 1.23 | 56.9 % | 36.0 % | 1412.99 | -24.1 % | 0.41 | 1.00 | 0.00 | 0.0 % | 11 | 0.5 % | 0.6 % | 11.3 % | 0.003 | 0.80 | drawdown under 25 % |
| 460usd:k3:g1:late:maker | 1.25 | 58.3 % | 35.8 % | 1446.60 | -24.0 % | 0.43 | 1.00 | 0.00 | 0.0 % | 8 | 0.2 % | 0.0 % | 11.3 % | 0.003 | 0.83 | drawdown under 25 % |
| 460usd:k5:g1:base:taker | 1.69 | 76.4 % | 27.6 % | 1893.28 | -13.4 % | 0.90 | 1.00 | 0.00 | 0.0 % | 11 | 0.6 % | 0.6 % | 11.6 % | 0.018 | 0.79 | drawdown under 25 % |
| 460usd:k5:g1:base:maker | 1.72 | 78.2 % | 27.6 % | 1941.45 | -13.2 % | 0.93 | 1.00 | 0.00 | 0.0 % | 11 | 0.2 % | 0.0 % | 11.6 % | 0.020 | 0.83 | drawdown under 25 % |
| 460usd:k5:g1:late:taker | 1.69 | 75.1 % | 27.0 % | 1858.61 | -13.8 % | 0.89 | 1.00 | 0.00 | 0.0 % | 7 | 0.6 % | 0.6 % | 11.2 % | 0.018 | 0.74 | drawdown under 25 % |
| 460usd:k5:g1:late:maker | 1.72 | 76.8 % | 27.0 % | 1905.54 | -13.6 % | 0.92 | 1.00 | 0.00 | 0.0 % | 7 | 0.2 % | 0.0 % | 11.2 % | 0.020 | 0.78 | drawdown under 25 % |
| 460usd:k10:g1:base:taker | 1.81 | 63.5 % | 19.8 % | 1568.15 | -10.0 % | 0.99 | 1.00 | 0.00 | 0.0 % | 41 | 0.8 % | 0.8 % | 10.4 % | 0.027 | 1.60 | pass |
| 460usd:k10:g1:base:maker | 1.87 | 66.1 % | 19.7 % | 1630.70 | -9.7 % | 1.03 | 1.00 | 0.00 | 0.0 % | 38 | 0.3 % | 0.0 % | 10.5 % | 0.032 | 1.66 | pass |
| 460usd:k10:g1:late:taker | 1.81 | 62.7 % | 19.4 % | 1547.90 | -9.7 % | 0.98 | 1.00 | 0.00 | 0.0 % | 53 | 0.8 % | 0.8 % | 10.2 % | 0.026 | 1.53 | pass |
| 460usd:k10:g1:late:maker | 1.86 | 65.2 % | 19.4 % | 1608.58 | -9.6 % | 1.03 | 1.00 | 0.00 | 0.0 % | 50 | 0.3 % | 0.0 % | 10.2 % | 0.032 | 1.59 | pass |

### 460usd, gross 2x

| cell | Sharpe | CAGR | max DD | end | worst month | boot 5 % | corr ideal | drift | skipped | cuts skipped | fees/yr | slip/yr | funding/yr | DSR | IS Sharpe | fails |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 460usd:k3:g2:base:taker | 1.35 | 122.3 % | 59.1 % | 3370.01 | -43.1 % | 0.56 | 1.00 | 0.00 | 0.0 % | 3 | 0.9 % | 1.1 % | 23.5 % | 0.005 | 0.99 | drawdown under 25 % |
| 460usd:k3:g2:base:maker | 1.37 | 126.2 % | 59.0 % | 3521.82 | -42.9 % | 0.58 | 1.00 | 0.00 | 0.0 % | 3 | 0.3 % | 0.0 % | 23.5 % | 0.005 | 1.01 | drawdown under 25 % |
| 460usd:k3:g2:late:taker | 1.32 | 115.2 % | 60.6 % | 3107.05 | -43.5 % | 0.51 | 1.00 | 0.00 | 0.0 % | 4 | 0.9 % | 1.1 % | 22.7 % | 0.004 | 0.91 | drawdown under 25 % |
| 460usd:k3:g2:late:maker | 1.34 | 119.3 % | 60.4 % | 3258.97 | -43.3 % | 0.53 | 1.00 | 0.00 | 0.0 % | 5 | 0.3 % | 0.0 % | 22.7 % | 0.004 | 0.94 | drawdown under 25 % |
| 460usd:k5:g2:base:taker | 1.75 | 181.3 % | 51.6 % | 6061.25 | -26.4 % | 0.96 | 1.00 | 0.00 | 0.0 % | 10 | 1.0 % | 1.1 % | 25.3 % | 0.023 | 0.81 | drawdown under 25 % |
| 460usd:k5:g2:base:maker | 1.78 | 187.1 % | 51.6 % | 6379.96 | -26.1 % | 0.98 | 1.00 | 0.00 | 0.0 % | 12 | 0.3 % | 0.0 % | 25.4 % | 0.025 | 0.85 | drawdown under 25 % |
| 460usd:k5:g2:late:taker | 1.75 | 177.2 % | 49.9 % | 5842.99 | -26.7 % | 0.94 | 1.00 | 0.00 | 0.0 % | 3 | 1.1 % | 1.1 % | 24.4 % | 0.022 | 0.77 | drawdown under 25 % |
| 460usd:k5:g2:late:maker | 1.78 | 182.6 % | 49.8 % | 6132.88 | -26.4 % | 0.97 | 1.00 | 0.00 | 0.0 % | 3 | 0.3 % | 0.0 % | 24.5 % | 0.025 | 0.81 | drawdown under 25 % |
| 460usd:k10:g2:base:taker | 1.84 | 146.7 % | 37.5 % | 4370.02 | -20.9 % | 1.00 | 1.00 | 0.00 | 0.0 % | 21 | 1.5 % | 1.4 % | 23.8 % | 0.030 | 1.64 | drawdown under 25 % |
| 460usd:k10:g2:base:maker | 1.88 | 153.4 % | 37.1 % | 4671.17 | -20.4 % | 1.05 | 1.00 | 0.00 | 0.0 % | 21 | 0.5 % | 0.0 % | 23.9 % | 0.035 | 1.70 | drawdown under 25 % |
| 460usd:k10:g2:late:taker | 1.83 | 143.2 % | 36.4 % | 4218.61 | -19.0 % | 0.99 | 1.00 | 0.00 | 0.0 % | 16 | 1.5 % | 1.4 % | 23.3 % | 0.029 | 1.57 | drawdown under 25 % |
| 460usd:k10:g2:late:maker | 1.88 | 149.2 % | 36.2 % | 4482.87 | -19.2 % | 1.04 | 1.00 | 0.00 | 0.0 % | 18 | 0.5 % | 0.0 % | 23.4 % | 0.034 | 1.63 | drawdown under 25 % |

### ideal, gross 1x

| cell | Sharpe | CAGR | max DD | end | worst month | boot 5 % | corr ideal | drift | skipped | cuts skipped | fees/yr | slip/yr | funding/yr | DSR | IS Sharpe | fails |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ideal:k3:g1:base:taker | 1.26 | 59.7 % | 34.7 % | 3.21 | -23.5 % | 0.46 | 1.00 | 0.00 | 0.0 % | 0 | 0.5 % | 0.6 % | 11.7 % | 0.003 | 0.89 | drawdown under 25 % |
| ideal:k3:g1:base:maker | 1.28 | 61.2 % | 34.6 % | 3.29 | -23.4 % | 0.48 | 1.00 | 0.00 | 0.0 % | 0 | 0.2 % | 0.0 % | 11.7 % | 0.003 | 0.91 | drawdown under 25 % |
| ideal:k3:g1:late:taker | 1.23 | 56.7 % | 36.0 % | 3.06 | -23.9 % | 0.41 | 1.00 | 0.00 | 0.0 % | 0 | 0.5 % | 0.6 % | 11.3 % | 0.003 | 0.80 | drawdown under 25 % |
| ideal:k3:g1:late:maker | 1.25 | 58.2 % | 35.9 % | 3.14 | -23.8 % | 0.43 | 1.00 | 0.00 | 0.0 % | 0 | 0.2 % | 0.0 % | 11.3 % | 0.003 | 0.83 | drawdown under 25 % |
| ideal:k5:g1:base:taker | 1.70 | 76.7 % | 27.5 % | 4.14 | -13.3 % | 0.91 | 1.00 | 0.00 | 0.0 % | 0 | 0.6 % | 0.6 % | 11.6 % | 0.019 | 0.79 | drawdown under 25 % |
| ideal:k5:g1:base:maker | 1.73 | 78.5 % | 27.5 % | 4.24 | -13.2 % | 0.93 | 1.00 | 0.00 | 0.0 % | 0 | 0.2 % | 0.0 % | 11.6 % | 0.021 | 0.83 | drawdown under 25 % |
| ideal:k5:g1:late:taker | 1.69 | 75.1 % | 27.0 % | 4.04 | -13.6 % | 0.89 | 1.00 | 0.00 | 0.0 % | 0 | 0.6 % | 0.6 % | 11.2 % | 0.018 | 0.74 | drawdown under 25 % |
| ideal:k5:g1:late:maker | 1.72 | 76.8 % | 27.0 % | 4.14 | -13.4 % | 0.92 | 1.00 | 0.00 | 0.0 % | 0 | 0.2 % | 0.0 % | 11.2 % | 0.020 | 0.78 | drawdown under 25 % |
| ideal:k10:g1:base:taker | 1.82 | 63.6 % | 19.8 % | 3.41 | -9.5 % | 0.99 | 1.00 | 0.00 | 0.0 % | 0 | 0.8 % | 0.8 % | 10.4 % | 0.028 | 1.60 | pass |
| ideal:k10:g1:base:maker | 1.87 | 65.9 % | 19.7 % | 3.53 | -9.2 % | 1.04 | 1.00 | 0.00 | 0.0 % | 0 | 0.3 % | 0.0 % | 10.5 % | 0.033 | 1.66 | pass |
| ideal:k10:g1:late:taker | 1.82 | 62.5 % | 19.5 % | 3.36 | -9.6 % | 0.98 | 1.00 | 0.00 | 0.0 % | 0 | 0.8 % | 0.8 % | 10.2 % | 0.027 | 1.54 | pass |
| ideal:k10:g1:late:maker | 1.87 | 64.8 % | 19.4 % | 3.48 | -9.5 % | 1.03 | 1.00 | 0.00 | 0.0 % | 0 | 0.3 % | 0.0 % | 10.3 % | 0.033 | 1.60 | pass |

### ideal, gross 2x

| cell | Sharpe | CAGR | max DD | end | worst month | boot 5 % | corr ideal | drift | skipped | cuts skipped | fees/yr | slip/yr | funding/yr | DSR | IS Sharpe | fails |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ideal:k3:g2:base:taker | 1.35 | 122.0 % | 59.1 % | 7.30 | -43.1 % | 0.56 | 1.00 | 0.00 | 0.0 % | 0 | 0.9 % | 1.1 % | 23.5 % | 0.005 | 0.98 | drawdown under 25 % |
| ideal:k3:g2:base:maker | 1.37 | 126.2 % | 59.0 % | 7.66 | -42.9 % | 0.58 | 1.00 | 0.00 | 0.0 % | 0 | 0.3 % | 0.0 % | 23.5 % | 0.005 | 1.01 | drawdown under 25 % |
| ideal:k3:g2:late:taker | 1.32 | 115.3 % | 60.6 % | 6.77 | -43.5 % | 0.51 | 1.00 | 0.00 | 0.0 % | 0 | 0.9 % | 1.1 % | 22.7 % | 0.004 | 0.91 | drawdown under 25 % |
| ideal:k3:g2:late:maker | 1.35 | 119.4 % | 60.4 % | 7.09 | -43.3 % | 0.53 | 1.00 | 0.00 | 0.0 % | 0 | 0.3 % | 0.0 % | 22.7 % | 0.005 | 0.94 | drawdown under 25 % |
| ideal:k5:g2:base:taker | 1.76 | 182.0 % | 51.4 % | 13.26 | -26.4 % | 0.96 | 1.00 | 0.00 | 0.0 % | 0 | 1.0 % | 1.1 % | 25.3 % | 0.023 | 0.81 | drawdown under 25 % |
| ideal:k5:g2:base:maker | 1.78 | 187.5 % | 51.4 % | 13.92 | -26.1 % | 0.99 | 1.00 | 0.00 | 0.0 % | 0 | 0.3 % | 0.0 % | 25.4 % | 0.025 | 0.85 | drawdown under 25 % |
| ideal:k5:g2:late:taker | 1.75 | 176.5 % | 49.9 % | 12.63 | -26.7 % | 0.94 | 1.00 | 0.00 | 0.0 % | 0 | 1.1 % | 1.1 % | 24.4 % | 0.022 | 0.77 | drawdown under 25 % |
| ideal:k5:g2:late:maker | 1.78 | 182.0 % | 49.8 % | 13.26 | -26.4 % | 0.97 | 1.00 | 0.00 | 0.0 % | 0 | 0.3 % | 0.0 % | 24.5 % | 0.025 | 0.81 | drawdown under 25 % |
| ideal:k10:g2:base:taker | 1.84 | 146.9 % | 37.5 % | 9.52 | -20.1 % | 1.01 | 1.00 | 0.00 | 0.0 % | 0 | 1.5 % | 1.4 % | 23.8 % | 0.030 | 1.64 | drawdown under 25 % |
| ideal:k10:g2:base:maker | 1.89 | 153.9 % | 37.1 % | 10.20 | -19.7 % | 1.06 | 1.00 | 0.00 | 0.0 % | 0 | 0.5 % | 0.0 % | 23.9 % | 0.036 | 1.70 | drawdown under 25 % |
| ideal:k10:g2:late:taker | 1.83 | 143.3 % | 36.4 % | 9.18 | -19.2 % | 0.99 | 1.00 | 0.00 | 0.0 % | 0 | 1.5 % | 1.4 % | 23.3 % | 0.029 | 1.57 | drawdown under 25 % |
| ideal:k10:g2:late:maker | 1.88 | 150.2 % | 36.2 % | 9.84 | -18.8 % | 1.04 | 1.00 | 0.00 | 0.0 % | 0 | 0.5 % | 0.0 % | 23.4 % | 0.034 | 1.63 | drawdown under 25 % |

## By year, 230 USD, taker, on time, 1x (Sharpe)

| k | 2024 | 2025 | 2026 | stop at -20 % |
|---|---|---|---|---|
| 3 | 1.20 | 1.28 | 1.37 | never |
| 5 | 1.29 | 1.89 | 2.33 | never |
| 10 | 2.00 | 1.68 | 1.62 | never |
