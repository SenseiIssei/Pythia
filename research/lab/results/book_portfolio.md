# book_portfolio (X7 B) · A portfolio of the live books

Pre-registered 2026-10-15, before any number of this study was computed.
Everything above the generated marker is fixed; anything tried beyond it is
added to the trial count.

## Question

The four live crypto paper books are each mediocre alone. Does an honest
combination of them (and of a small US equity sleeve) beat the best of them
on both Sharpe and drawdown out of sample?

## Books (return series)

Daily net returns on UTC calendar days, every book as the autopilot runs it
on Alpaca: coins Alpaca does not list are held as cash (C16 showed that this
is better than the original books), costs 35 bps per unit of turnover (Alpaca
taker plus slippage).

- `breakout_top10`, `tsmom_top20`, `tsmom_tranches`: the C rows of
  `alpaca_universe` (the paper books' own weight functions and simulators on
  the survivorship-free panel).
- `tsmom_regime`: `lab.experiments.tsmom` 28 days, daily, 40 % vol per coin,
  flat while BTC is below its 200-day average, on its fixed 20 coins (today's
  survivors, a known bias) with the non-Alpaca coins in cash.

The server's `reports/forward/backtest/*.json` hold only 2024 onward at
15 bps, so the series are regenerated from the same modules. In sample
2020-08-01 to 2023-12-31, out of sample 2024-01-01 to the panel's last day.

Equity sleeves (returns on the session's UTC date, zero on days without a
session):

- SPY buy and hold (Yahoo adjusted closes, 2 bps a side on sleeve trades)
- the overnight pick of `overnight.md` at its base costs (tested whether or
  not it passes there; only proposable if it does)

## Mixes (crypto weights over the four books)

Weights are set from data up to the previous close. A sleeve whose book is in
cash leaves that share in cash. Drift between sleeves is traded back every day
at 35 bps (crypto) or 2 bps (equity) per unit moved; the engine's per-coin
netting of lab books would trade less, so this is conservative.

| | Mix |
|---|---|
| EW | equal weight, 1/4 each |
| IV | inverse vol: 1 / (90-day vol of each book's daily returns, floor 5 % a year), updated every 7 days |
| RP | risk parity: equal risk contributions from the 90-day covariance (ridge 1e-6), updated every 7 days |
| VT15 | equal weight, the whole portfolio scaled by min(1, 15 % / its 30-day realised vol), daily |
| VT25 | the same at 25 % |
| DDB | drawdown brake: equal weight at full size while the unbraked portfolio is less than 10 % below its peak, half from 10 %, a quarter from 20 % |

No leverage anywhere (a cash account). Equity sleeve: none, SPY 20 %, SPY
40 %, overnight 20 %, overnight 40 %; the crypto mix gets the rest. For VT and
DDB the scaling applies to the whole portfolio, equity sleeve included.

**30 trials** (6 mixes x 5 equity sleeves).

## Judgement

- Pick: the best in-sample Sharpe at 35 bps among the 30 (annualised over 365
  days).
- The yardstick is the best single book out of sample: the one of the four
  with the highest out-of-sample Sharpe, chosen after the fact (the strictest
  choice).
- Stationary block bootstrap, block 20 days, 4,000 draws, the pick and the
  yardstick resampled on the same days.
- Deflated p over the pool (908 earlier trials as in `overnight.md`, plus its
  39, plus these 30) is reported next to the verdict.

Pass rule, all out of sample from 2024:

1. Sharpe higher than the best single book's
2. max drawdown lower than the best single book's
3. in at least 2 of the 3 years 2024, 2025, 2026 (2026 to date): Sharpe
   higher than that book's, and separately, drawdown lower in at least 2 of 3
4. the bootstrap's 5 % quantile of Sharpe(pick) minus Sharpe(best book) above 0

If the pick passes, the report says how an autopilot runs it with the sleeve
weights the engine already supports (explicit sleeves, lab books netted per
coin, a portfolio autopilot for the equity sleeve) and what it cannot do yet
(time-varying weights). Nothing is deployed.

Run: `python -m lab.experiments.book_portfolio` (after `overnight`).

<!-- generated below by lab.experiments.book_portfolio; edit above this line only -->

## Results (generated 2026-10-15, in sample 2020-08-01 to 2023-12-31, out of sample 2024-01-01 to 2026-10-11)

**Verdict: fails (3 of 4 rules), no portfolio autopilot is proposed.** The in-sample pick is IV · overnight 20 % (in-sample Sharpe 1.84). Out of sample it makes Sharpe 1.15, 10.0 % a year, drawdown 7.7 %, against the best single book, breakout_top10, at 1.17, 18.6 %, drawdown 16.0 %. Higher Sharpe in 1 of 3 years, lower drawdown in 3 of 3; the bootstrap's 90 % band of the Sharpe difference is -0.51 to 0.55 (51% of draws above 0). Deflated p 0.00 over 977 trials (noise bar about 2.73 on 365 days).

Failed: Sharpe higher than the best single book's; higher Sharpe in 2 of 3 years and lower drawdown in 2 of 3 years; bootstrap 5 % of the Sharpe difference above 0.

22 of 30 trials beat the best book on both Sharpe and drawdown out of sample (EW · SPY 20 %, EW · SPY 40 %, EW · overnight 20 %, EW · overnight 40 %, IV · SPY 20 %, IV · SPY 40 %, IV · overnight 40 %, RP · SPY 20 %, RP · SPY 40 %, RP · overnight 40 %, VT15 · SPY 20 %, VT15 · SPY 40 %, VT15 · overnight 20 %, VT15 · overnight 40 %, VT25 · SPY 20 %, VT25 · SPY 40 %, VT25 · overnight 20 %, VT25 · overnight 40 %, DDB · SPY 20 %, DDB · SPY 40 %, DDB · overnight 20 %, DDB · overnight 40 %), none of them the in-sample pick.

Among the crypto books alone, 0 of 6 mixes beat the best book's Sharpe (the best of them makes 0.94): the four books are 0.70 to 0.95 correlated. With an equity sleeve 22 of 24 beat it and 22 beat it on drawdown too (median Sharpe 1.31, median drawdown 9.3 %). These are after-the-fact counts, not the registered verdict.

### The books (35 bps, non-Alpaca coins in cash)

| book | IS Sharpe | OOS Sharpe | OOS CAGR | OOS DD | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|---|
| breakout_top10 | 1.451 | 1.170 | 18.6 % | 16.0 % | 2.190 | 0.320 | -0.022 |
| tsmom_top20 | 1.678 | 0.641 | 5.3 % | 9.0 % | 1.560 | -0.347 | 0.903 |
| tsmom_tranches | 1.852 | 0.730 | 6.6 % | 8.8 % | 1.664 | -0.080 | 0.622 |
| tsmom_regime | 1.836 | 0.796 | 10.1 % | 16.4 % | 1.356 | -0.343 | 1.456 |


Correlation of the daily returns out of sample:

|  | breakout_top10 | tsmom_top20 | tsmom_tranches | tsmom_regime |
|---|---|---|---|---|
| breakout_top10 | 1.000 | 0.714 | 0.704 | 0.718 |
| tsmom_top20 | 0.714 | 1.000 | 0.923 | 0.946 |
| tsmom_tranches | 0.704 | 0.923 | 1.000 | 0.852 |
| tsmom_regime | 0.718 | 0.946 | 0.852 | 1.000 |


Equity sleeves out of sample on the crypto calendar (zero on days without a session): SPY buy and hold Sharpe 1.30, drawdown 18.8 %; U2 QQQ · R1 trend Sharpe 1.42, drawdown 9.7 %. Correlation with the equal-weight crypto books: SPY 0.17, overnight 0.12.

### The 30 trials

Sharpe over 365 days, net of every cost. Sleeve weight: the share of the portfolio given to the books (below 100 % only when the vol target or the brake scales it down); the books themselves sit partly in cash.

| trial | IS Sharpe | OOS Sharpe | OOS CAGR | OOS DD | sleeve weight | 2024 | 2025 | 2026 | deflated p |
|---|---|---|---|---|---|---|---|---|---|
| EW · none | 1.756 | 0.941 | 10.0 % | 10.6 % | 100.0 % | 1.875 | -0.138 | 0.837 | 0.001 |
| EW · SPY 20 % | 1.831 | 1.254 | 12.3 % | 11.0 % | 100.0 % | 2.147 | 0.258 | 1.235 | 0.006 |
| EW · SPY 40 % | 1.678 | 1.450 | 14.5 % | 12.7 % | 100.0 % | 2.337 | 0.598 | 1.498 | 0.016 |
| EW · overnight 20 % | 1.829 | 1.231 | 11.4 % | 8.0 % | 100.0 % | 2.205 | 0.255 | 0.917 | 0.006 |
| EW · overnight 40 % | 1.817 | 1.494 | 12.8 % | 6.0 % | 100.0 % | 2.489 | 0.758 | 0.880 | 0.020 |
| IV · none | 1.761 | 0.836 | 8.3 % | 10.1 % | 100.0 % | 1.723 | -0.152 | 0.833 | 0.001 |
| IV · SPY 20 % | 1.835 | 1.174 | 10.9 % | 10.7 % | 100.0 % | 2.028 | 0.249 | 1.237 | 0.004 |
| IV · SPY 40 % | 1.657 | 1.388 | 13.4 % | 12.5 % | 100.0 % | 2.231 | 0.593 | 1.503 | 0.012 |
| IV · overnight 20 % | 1.837 | 1.147 | 10.0 % | 7.7 % | 100.0 % | 2.089 | 0.243 | 0.916 | 0.004 |
| IV · overnight 40 % | 1.811 | 1.428 | 11.7 % | 5.8 % | 100.0 % | 2.388 | 0.750 | 0.880 | 0.015 |
| RP · none | 1.746 | 0.847 | 8.3 % | 10.0 % | 100.0 % | 1.736 | -0.168 | 0.867 | 0.001 |
| RP · SPY 20 % | 1.824 | 1.186 | 10.9 % | 10.7 % | 100.0 % | 2.039 | 0.238 | 1.280 | 0.005 |
| RP · SPY 40 % | 1.651 | 1.397 | 13.4 % | 12.5 % | 100.0 % | 2.240 | 0.587 | 1.536 | 0.013 |
| RP · overnight 20 % | 1.822 | 1.159 | 10.1 % | 7.8 % | 100.0 % | 2.100 | 0.231 | 0.949 | 0.004 |
| RP · overnight 40 % | 1.798 | 1.439 | 11.7 % | 5.8 % | 100.0 % | 2.397 | 0.742 | 0.902 | 0.016 |
| VT15 · none | 1.681 | 0.899 | 8.5 % | 10.0 % | 95.7 % | 1.875 | -0.113 | 0.745 | 0.001 |
| VT15 · SPY 20 % | 1.783 | 1.244 | 11.7 % | 10.6 % | 98.3 % | 2.168 | 0.270 | 1.202 | 0.006 |
| VT15 · SPY 40 % | 1.658 | 1.420 | 13.9 % | 12.8 % | 99.0 % | 2.324 | 0.509 | 1.498 | 0.014 |
| VT15 · overnight 20 % | 1.784 | 1.220 | 10.9 % | 7.8 % | 98.5 % | 2.221 | 0.274 | 0.870 | 0.005 |
| VT15 · overnight 40 % | 1.828 | 1.487 | 12.7 % | 6.1 % | 99.9 % | 2.473 | 0.758 | 0.880 | 0.019 |
| VT25 · none | 1.761 | 0.941 | 10.0 % | 10.6 % | 100.0 % | 1.874 | -0.138 | 0.837 | 0.001 |
| VT25 · SPY 20 % | 1.829 | 1.254 | 12.3 % | 11.0 % | 100.0 % | 2.147 | 0.258 | 1.235 | 0.006 |
| VT25 · SPY 40 % | 1.678 | 1.450 | 14.5 % | 12.7 % | 100.0 % | 2.337 | 0.598 | 1.498 | 0.016 |
| VT25 · overnight 20 % | 1.828 | 1.231 | 11.4 % | 8.0 % | 100.0 % | 2.205 | 0.255 | 0.917 | 0.006 |
| VT25 · overnight 40 % | 1.817 | 1.494 | 12.8 % | 6.0 % | 100.0 % | 2.489 | 0.758 | 0.880 | 0.020 |
| DDB · none | 1.756 | 0.901 | 9.5 % | 11.3 % | 99.8 % | 1.783 | -0.138 | 0.837 | 0.001 |
| DDB · SPY 20 % | 1.831 | 1.194 | 11.5 % | 11.3 % | 99.7 % | 2.147 | 0.066 | 1.235 | 0.005 |
| DDB · SPY 40 % | 1.592 | 1.371 | 13.2 % | 13.2 % | 99.4 % | 2.337 | 0.312 | 1.498 | 0.012 |
| DDB · overnight 20 % | 1.829 | 1.231 | 11.4 % | 8.0 % | 100.0 % | 2.205 | 0.255 | 0.917 | 0.006 |
| DDB · overnight 40 % | 1.817 | 1.494 | 12.8 % | 6.0 % | 100.0 % | 2.489 | 0.758 | 0.880 | 0.020 |


### The pick against the best book, per year

| year | pick Sharpe | breakout_top10 Sharpe | pick DD | breakout_top10 DD |
|---|---|---|---|---|
| 2024 | 2.089 | 2.190 | 5.0 % | 12.1 % |
| 2025 | 0.243 | 0.320 | 5.5 % | 10.8 % |
| 2026 | 0.916 | -0.022 | 3.2 % | 7.9 % |


### Rules

- FAIL: Sharpe higher than the best single book's
- pass: drawdown lower than the best single book's
- FAIL: higher Sharpe in 2 of 3 years and lower drawdown in 2 of 3 years
- FAIL: bootstrap 5 % of the Sharpe difference above 0

### How an autopilot would run it

Nothing is proposed. For the record: equal weights over the four books are possible today (one autopilot, the four lab books as explicit sleeves at 25 % each, netted per coin; a SPY sleeve would need a portfolio autopilot and a US-share lab book). Inverse vol, risk parity, the vol target and the brake change weights or exposure over time, which the engine's fixed sleeve weights cannot do; they would need one combined lab signal.

### Deflation pool

908 earlier trials at the variance of the published bar, study A's 39 out-of-sample Sharpes from its report, and these 30 (out of sample, clipped at an annual +-3): 977 trials.
