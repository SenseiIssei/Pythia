# Strategy validation

Run it yourself:

```bash
npm run server
```

```bash
npm run validate
```

Every number it prints comes from **out-of-sample** bars — parameters fitted on
earlier data and scored only on what came after. Nothing here is a promise about
the future; it is the least flattering honest measurement available.

---

## How it works

**Walk-forward, portfolio level.** History is split into `folds + 1` windows.
For each fold, every parameter set in the strategy's grid is backtested on
everything *before* the window, one set is chosen for the whole universe, and
only then is it run on the window itself. The chosen set never saw the data it
is scored on.

Parameters are fitted once per fold for **all markets at once**, not per market.
Fitting nine separate parameter sets on ~110-bar windows is overfitting with
extra steps; one set that works across nine markets is a much stronger claim.

**The backtester is deliberately pessimistic** ([`backtest.rs`](../crates/pythia-core/src/research/backtest.rs)):

| | |
|---|---|
| Signal on bar `t`, fill at bar `t+1`'s **open** | Filling at the signal bar's close uses a price that didn't exist when the decision was made. It is worth a fortune in imaginary profit. |
| Exits checked against each bar's **high/low** | A stop touched intrabar was hit, wherever the bar closed. |
| Stop assumed to hit **before** target when a bar contains both | The path is unknowable from OHLC, and the optimistic assumption is exactly the one that makes bad strategies look good. |
| Costs on **both sides**, including slippage on market exits | Default 6bps fee + 8bps slippage per side. |
| Strategies see a rolling **260-bar** window | Same cap as the live engine. A backtest with unlimited history tests a different indicator that happens to share a name. |
| Open positions are **closed at the last bar** | A position marked at a hopeful price is not a result. |

Signals come from the same `run_strategy` the live engine calls. A backtest that
reimplements the strategy is testing the reimplementation.

## Reading the verdict

**DSR** (deflated Sharpe ratio) is the column that matters. Try enough parameter
sets and one will look excellent — that is arithmetic, not alpha. The DSR asks
how good the *best of N attempts* would look with no edge at all, and reports
the probability the observed result beats that bar.

| Verdict | Meaning |
|---|---|
| **PASS** | Positive out-of-sample, DSR ≥ 95% |
| **MARGINAL** | Made money, but not distinguishable from a lucky search |
| **FAIL** | Lost money out-of-sample after costs |
| **NO DATA** | Too few trades or too little history to claim anything |

A MARGINAL is not a rejection. It usually means the parameter grid produced
wildly different in-sample results, so the winner may have been noise. More
history, or a strategy less sensitive to its parameters, moves it.

---

## Results — 2026-07-24

9 Kraken markets · 721 daily bars (~2 years) · 4 folds · 6bps fee + 8bps
slippage per side.

| Strategy | Verdict | OOS return | Sharpe | Max DD | Trades | Win | DSR |
|---|---|---:|---:|---:|---:|---:|---:|
| Multi-TF Momentum | **PASS** | +90.4% | 1.06 | 38.3% | 41 | 65.9% | 100% |
| EMA Cross | **PASS** | +22.2% | 0.51 | 46.8% | 46 | 54.3% | 100% |
| Bollinger Revert | MARGINAL | +51.3% | 0.84 | 43.4% | 37 | 62.2% | 0% |
| RSI Reversal | MARGINAL | +3.9% | 0.26 | 43.1% | 31 | 38.7% | 0% |
| MACD Trend | **FAIL** | −10.0% | 0.09 | 48.1% | 56 | 44.6% | 98% |

**Acted on:** MACD Trend now ships **paused**. It lost money out-of-sample with
a 98% deflated Sharpe — that loss is not an artifact of the search — and it has
no parameters to re-fit.

Both mean-reversion rules land MARGINAL for the same reason: their parameter
grids produce widely varying in-sample Sharpes, so the deflation cannot rule out
that the winner was picked from noise. They stay paused.

### What this does not prove

Read these before treating the table as a green light.

- **Two years is one regime.** 721 daily bars is Kraken's per-request cap. That
  sample contains one broad crypto cycle, and a trend follower's +90% may be
  mostly "crypto went up during the test window". Trend rules look good in
  trending samples; that is what they are.
- **Four folds of ~144 bars is thin.** After the 70-bar warmup each window
  leaves ~74 decision bars. Fold-level results are noisy even when the pooled
  one isn't.
- **41 trades is not a large sample.** A Sharpe of 1.06 on 41 trades has wide
  error bars whatever the DSR says; the DSR prices in the *search*, not the
  sample size on its own.
- **Equities were not tested.** That run had no Alpaca keys, so Donchian
  Breakout is unscored. Set keys and re-run to include it.
- **Costs are an estimate.** 6bps + 8bps is a reasonable liquid-crypto figure.
  Run `FRICTIONLESS=1 npm run validate` to see how much of each result the cost
  model is eating — if a strategy only works at zero cost, it doesn't work.

The correct use of this table is to *reject* strategies, not to size positions.
A PASS means "not yet disproven".
