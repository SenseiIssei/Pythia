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
