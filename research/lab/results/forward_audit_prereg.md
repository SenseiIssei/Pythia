# Forward record audit: pre-registration

Registered 2026-10-20, before any reconciliation, percentile or slippage
figure of this audit was computed. Draft:
`research/lab/proposals/2026-10-20-forward-record-audit-before-more-books.md`.
Code: `lab.paper.forward_audit`. Write-up: `results/forward_audit.md`. Nothing
below may change once the first number is in the write-up; a change is a new
registration with a new name.

## Question

Do the running paper books trade their own backtest signals, does their
forward return sit where their backtests say it can, and does every figure the
forward reports print add up?

## Scope

Paper books with a journal under `<data>/paper/` on 2026-10-20 (the mirror,
synced from the server; read only):

| Book | Signal code the audit reruns | Checks |
|---|---|---|
| `tsmom`, `tsmom_regime` | `experiments.tsmom.target_weights` (as `paper.tsmom`) | 1, 2 |
| `tsmom_top20` | `fam_volmom.base_weights` (as `paper.families.targets`) | 1, 2 |
| `breakout_top10` | `fam_breakout.breakout_weights` and `families.backtest_weights` | 1, 2 |
| `tsmom_tranches` | `tsmom_tranches.targets` and `tsmom_tranches.simulate` | 1, 2 |
| `memes_rotation`, `memes_tsmom` | `memecoins.rotation`, `memecoins.trend` (as `paper.memes`) | 1, 2 |
| `m4_ls` | `paper.m4_ls` | 1 where the inputs exist on the mirror, else reported as not reproducible |
| `picks_ls`, `picks_ls_v2` | `paper.picks_ls` | as `m4_ls` |
| `trend4h_pullback` | `paper.trend4h` | as `m4_ls` |
| `pumpfun_migration`, `pumpfun_filtered`, `pumpfun_filtered_quick` | none: event books on a live stream with no backtest signal | 4 only |

Autopilots: every autopilot in the engine's saved state for check 3 and 4.

## The four checks

1. **Signal reconciliation.** For each journal row (run date D, decision
   close D minus one day), the weights the book's own weight function gives on
   the data available at that close, rerun now from the same history files,
   against the weights the journal says the book held after the run. A
   coin-day is every coin either side holds on that day. It is a mismatch
   when the two weights differ by more than **1 % of the book** (0.01 in
   weight) or have opposite signs. Coins the paper book could not trade (no
   live quote, a dead `~` segment) are counted on the backtest side, so a
   missing quote shows up as a mismatch.
2. **Percentile.** The book's forward cumulative return (journal equity
   against its start) placed among every rolling window of the same number of
   days in its out-of-sample backtest from 2024-01-01, net of **35 bps** per
   unit of one-way turnover, and again at **70 bps**. The paper books trade
   the whole universe (Binance quotes), so the backtest is the same rule on the
   same universe; the Alpaca cash-left variants (`alpaca_universe`) are what
   the autopilots run and are reported for the autopilot test books only.
3. **Realised cost.** For every filled autopilot order in the saved state,
   the fill price against the decision mark in bps (the engine's
   `realisedSlippageBps`, signed so that a worse fill is positive), median and
   90th percentile per coin and overall.
4. **Impossible figures.** Each figure the draft names is traced to code or
   data, explained in the write-up and fixed in code with a test:
   pumpfun_migration at -965.4 %, ap_29742's worst drawdown of 81.91 %, its
   fees of 0.73 % of capital, its -10.0 % in 3 days, "15 real position(s)
   could not be closed" on a demo autopilot, "after 13 days since
   2026-10-17" on 2026-10-20, and the repeated venue quantity corrections.

## Pass rule (per book)

All of:

- signal mismatch on **under 5 %** of coin-days;
- forward return **above the 5th percentile** of its same-length backtest
  windows at 35 bps;
- median measured slippage of **at most 10 bps** on the daily books' autopilot
  fills;
- every impossible figure explained, with a fix committed.

## Kill rule

- A book with a mismatch of **5 % or more**, or a forward return **below the
  1st percentile**, has its forward record frozen and marked invalid: its days
  count toward no forward gate and no readiness rule until the cause is fixed
  and a fresh record starts.
- Median measured slippage **above 20 bps** raises the 35 bps base for every
  Alpaca study, and the running books are judged again at the new cost.

## Trials

None. No Sharpe is tested and nothing is selected, so nothing is added to the
pool and no deflated p applies.

## What could fool us

With 3 to 15 forward days the percentile check has almost no power, and every
book carries BTC exposure: "inside the band" means not yet distinguishable,
not working. Rerunning the signal today uses today's history files; a bar
revised after the decision close shows up as a mismatch that is a data
revision, not a code bug, and is reported as such. Alpaca paper fills are
simulated against quotes and can look cheaper than real fills.
