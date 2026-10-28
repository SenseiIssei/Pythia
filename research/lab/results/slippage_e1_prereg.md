# E1: slippage bounds for pump.fun buys and sales, on realistic paper. Pre-registration

Registered 2026-10-28 and committed before any count, mean or band of this study was computed. Brief E1 of the
training plan of 2026-10-28, on the review of 2026-10-27 (`results/review_2026-10-27.md`, sections 2, 3 and 5, and
its queue line on E1), R5's registry (`metrics.trial_pool`, `<data>/trials/registry.jsonl`), R6's windows and P1's
taint rule (`realistic.tainted`). Paper only: nothing a live bot, its sizing, a wallet or the engine reads changes;
the live bot's bounds are the owner's (`live_exec.LIVE_POOL_BUY_TOL`, `PYTHIA_PUMPFUN_BUY_TOL`) and stay as they are.
Numbers seen before this file: the review's (network fees 0.7 % of a 3 % round trip, pool fee about 1.2 % a side, live
buy slippage median +3.1 % against +1.4 % on paper, 135 failed transactions), R1's (6040 at 5.7 % of live buys, the
bound 0.30 until 2026-10-23 18:56 UTC, 0.60 since), P1's and P2's headlines. No fill of the live bot was looked at for
this study.

## The question

The network fee cannot be cut much and the pool fee not at all; what the bot can choose is how loose its price
bounds are. A loose bound accepts fills far worse than the signal's quote and leaves room a sandwich can take; a
tight one fails more often (6040 on a pool buy, a sale under its floor) and pays the transaction fee for nothing.
Which bounds, on the realistic paper engine (`lab.pumpfun_rt.realistic`), make the most after all costs?

## The rules

The live bot's rules: **P_pool0**, **P_pool0_wait** (the live rule now) and **P_cmig_model** (a bonding-curve rule).
Each runs as its own realistic book per bound, the same strategy, the same latency, failure and fee draws (the rule's
own key, `p["base"]`), only the bounds differ.

## The grid (fixed)

Ten bound pairs, named as below. A buy bound b: a pool buy accepts no fewer tokens than the signal's quote / (1 + b)
(at the landing; under it the buy fails as 6040, "price ran away on landing", and pays the live 6040 fee), and the
pre-send check skips without a send or a fee when the price at the send has already run more than b (the live
check, its bound from the fresher quote, never looser than the signal's). A curve buy keeps a cost cap of the stake x
(1 + min(b, SLIP_TOL)): the sizing's room never counts more than the live 30 %. A sale bound s: every sale (the
protective exits too) accepts no less than max(the rule's own floor, the sale's value at its decision / (1 + s)); the
live sales keep the rule's floor (0 for a protective exit, half the expected proceeds for a take-profit step).

| name | buy bound b | sale bound |
|---|---|---|
| b02 | 0.02 | live |
| b05 | 0.05 | live |
| b10 | 0.10 | live |
| b20 | 0.20 | live |
| b30 | 0.30 (the live bound until 2026-10-23) | live |
| **b60** | **0.60 (the live bound, the reference)** | **live** |
| b100 | 1.00 (`BUY_TOL_MAX`) | live |
| s05 | 0.60 | 0.05 |
| s15 | 0.60 | 0.15 |
| s30 | 0.60 | 0.30 |

Every book of this study, b60 included, holds a failed sale back as the live executor does (1, 2, 4 ... 60 s,
`live_exec.backoff_ms`); after `SELL_MAX_FAILS` (6) failures in a row the live bot gives the position up as stuck and
the owner sells it by hand: here it is then sold without a bound, and counted.

## Two views of sandwiches

The realistic engine fills at the first recorded trade after the landing; other bots' trades are in the record, but
nobody there reacts to our bound. So every bound pair runs twice:

- **none**: the engine as it is.
- **sandwich**: every profitable sandwich is taken. At the fill, an attacker buys x before our buy (sells y before our
  sale) and trades back after it, on the exact constant-product arithmetic of the pool or curve (the coin's own fee
  on each of its two trades, our order's own impact), paying two transactions at the fit's fee and tip. It chooses x
  (y) to maximise its profit with our order still inside its bound; when the best profit is positive our order fills
  where it leaves it (never past the bound), else as in "none". No rate is fitted: this is the worst case the bound
  allows to an attacker who pays fees like everyone.

## The books and the data

- **Replay** of the collector's recorded days (`store.days`, the last `study.WINDOW_DAYS`, the creator history warmed
  as R1) through `lab.pumpfun_rt.sim`, to the run's time, entries until 15 minutes before the record's end. The fit
  (latency, failures, fees) from the live orders of the FIT_DAYS days to the end (`realistic.fit`). P_cmig_model's
  model filter uses the model files in `<data>/models/pumpfun_rt` as they are at the run, the same for every bound:
  its selection is in sample, only the differences between bounds are read.
  Per (rule, bound pair, view) two books:
  - **C** (measuring): 0.1 SOL a trade, no slot, exposure or loss limit (`realistic.R1_CALIB_LIMITS`), so every
    signal is tried under every bound and the books compare signal by signal;
  - **W** (the live sizing): the owner's control file and settings on a 0.55 SOL paper wallet (`PaperWallet`, topped
    up as R1).
- **Forward** in the shadow books: `<rule>@e1_<name>` for the ten pairs and the three rules, the sandwich view, the
  live sizing on their own 0.55 SOL paper wallets, from the deploy on; read from `<data>/paper/pumpfun_rt`
  (`ledger.csv`, `failed.csv`).

## The window

The pump.fun record starts 2026-10-20, after R6's lockbox start (2026-07-01); R6's windows split the daily panels of
the factories, not this collector, and nothing here is a strategy or a held-back claim: it measures execution on a
fixed rule set. The replay runs the fixed code, so P1's taint (rows the late-row bug wrote into the shadow ledger
before 2026-10-28 19:40 UTC) does not reach it; the forward books start after that deploy and their rows go through
`realistic.untainted` all the same.

## The measures, per bound pair (C books; each rule and the three pooled)

- signals; trades (filled buys); 6040 failures and their fees; pre-send skips (no fee); every other buy failure and
  its fee; failed sales and their fees; sales given up to the owner;
- mean and median return per closed trade after all costs (`ret`: P&L over the stake, every fee included);
- **P&L per signal** (SOL at 0.1 SOL a trade: closed trades and the fees of failed buys over all signals): the
  decision measure;
- the share of filled buys that filled **worse than the signal by more than 2 %**: price paid per token over the
  signal's quote per token (stake over the tokens quoted at the signal), minus 1;
- in the sandwich view: sandwiched buys and sales and what they took;
- against b60: the paired difference in P&L per signal, signals matched by rule and coin, a 95 % percentile bootstrap
  band (2,000 draws, seed 0, coins drawn);
- per recorded day: which buy bound made the most per signal (does the ranking hold day by day);
- W books: closed trades, P&L in SOL, top-ups;
- **P2's selection gap per bound**: `selection_p2.compute` with the C book of each bound as the paper side (the rules'
  rows renamed to the rule), over the live runs P2 found: paper minus live on all live signals and its split into
  selection, same coins and live's own trades. P2's numbers exist where the record and the live runs overlap
  (2026-10-22 to 2026-10-24).

## The proposal rule (fixed)

On P_pool0_wait (the live rule), sandwich view, C books:

- **buy bound**: the b of b02 to b100 with the highest P&L per signal; proposed in place of 0.60 only if its paired
  band against b60 lies above 0, else "keep 0.60".
- **sale bound**: the best of live, s05, s15 and s30 by the same rule against b60 (live).
- The other two rules and the "none" view are reported next to it; a bound that wins only without sandwiches is said
  so. The proposal is a line for the owner; nothing here changes the live settings.

## Trials

One per (rule, bound pair, view), family hand, counted only (no Sharpe, no DSR), registered in R5's registry before
the first number: `hand:e1:<rule>:<name>:<view>`, 3 x 10 x 2 = **60 trials**. The forward books are the same 30
sandwich-view hypotheses and add none. The report: `python -m lab.pumpfun_rt.slippage_e1` writes
`results/slippage_e1.md`.

## Tests (before the run)

A pool buy beyond its bound fails as 6040 with its fee; a tighter bound never fills worse than it allows (a pool buy
and a full curve buy); the pre-send skip uses the book's bound; a sale under its bound fails with its fee and waits
for the backoff; the sandwich arithmetic: none when unprofitable, never past the bound, the attacker's profit what the
pool says; the books, their names and the forward books in the shadow.
