# P3: a 10 EUR realistic paper book for pump.fun. Pre-registration

Registered 2026-10-28 and committed before the books below existed, so before any number of theirs. Brief P3 of the
training plan of 2026-10-28, on the review of 2026-10-27 (`results/review_2026-10-27.md`, sections 2 and 3), R5's
registry (`metrics.trial_pool`, `<data>/trials/registry.jsonl`), R6's windows (the books trade forward from their
deploy, all of it inside R6's lockbox era from 2026-07-01, and no back test is made), P1's taint rule
(`realistic.tainted`) and P2's gap (`selection_p2.gate`). Paper only: nothing a live bot, its sizing, a wallet or the
engine reads changes, and nothing here arms the live bot. Numbers seen before this file: P1's (+5.9 % a trade for
P_pool0_wait over the whole ledger, without the tainted rows) and P2's (paper minus live +18.9 points a trade, band
+3.8 to +35.8; realistic paper only +4.3).

## The question

Can 10 EUR snipe pump.fun with an edge? At 91.68 EUR a SOL 10 EUR is 0.109 SOL: 0.01 SOL fee reserve, at the live
share 0.5 one trade of about 0.05 SOL at a time. A round trip costs about 0.00043 SOL of network fee and tip (0.9 %
of 0.05 SOL), the curve's or pool's fees, and 0.002 SOL rent a token account holds until it is closed. A rule needs
more than about 4 % a trade live to be worth it.

## The rules (three, fixed now)

The three rules the live bot has run (P2's list), chosen for that alone and not by any result: **P_pool0_wait** (the
live rule today), **P_pool0** and **P_cmig_model**. One book each: `P_pool0_wait_10eur`, `P_pool0_10eur`,
`P_cmig_model_10eur` (`realistic.TEN`). No other rule, share, slot count or size is tried.

## The book

`realistic.ten_books`, the R2 machinery (`small_books`, `small_cfg`) with the live executor's model:

- **Wallet**: 0.109 SOL (`TEN_SOL`) per book from its deploy (`since_ms`, the first time the collector runs it).
  **No top-up**, ever: a wallet that can no longer pay a trade stops buying and stays in the numbers.
- **Sizing**: the live bot's (`sizing.sized` with limits=wallet): share 0.5 (the live ack's), at most 1 open (the
  live settings), the brake on (the live control file), the minimum stake 0.05 SOL, rounded down to 0.01 SOL, the
  floor 0 (as R2: the live pause under 0.25 SOL would stop a 10 EUR wallet before its first trade). The stake never
  exceeds what the wallet can pay with the 0.01 SOL reserve, one rent and the 30 % slippage room kept.
- **Rent**: 2,039,280 lamports (`RENT_L`, the rent-exempt minimum of a token account, about 0.002 SOL) leave the
  wallet when a buy lands (the buy creates the coin's token account) and are held while the position is open. They
  come back when the rule's last sale sells everything (the live sale closes the account then, `txbuild.close_own`).
  A position given up as stuck keeps its account: the rent is lost and booked into that trade's fees. A failed buy
  creates no account (the transaction fails as a whole) and pays its fee only. An open position lost to a collector
  restart gives its stake and its rent back (its ledger row says "restart" and is left out of every number).
- **Refused**: a buy is refused ("refused: wallet balance too low", no fee) when the wallet's free SOL cannot pay the
  stake with its slippage room, the reserve and the rent.
- **Execution**: everything of R1's realistic model, as every realistic book: the live latency drawn from the fit,
  the fill at the first recorded trade after the landing, the live 60 % bound and its 6040 with its fee, the pre-send
  skip, the drawn failures with their fees, the network fee and tip of every transaction, the curve's or pool's fees,
  the stake's own price impact.

## The numbers (per book, from its start)

From the paper ledger's rows of the book, without restart rows and without rows `realistic.tainted` flags (P1,
counted), and the book's rows in `failed.csv`:

- the wallet in SOL and in EUR (the day's rate, `realistic.sol_eur`): the start and every realised result, open
  positions at their cost, held rent counted as the wallet's;
- trades: the closed trades;
- per trade after all costs: a trade's return is its P&L over its stake (its fees and any lost rent in the P&L),
  less F / S, the failed buys' fees F over the closed trades' stakes S (the failed buys' cost spread on the trades by
  stake); the mean and the median of those;
- the 95 % percentile bootstrap band of the mean: 2,000 draws of the trades with replacement, seed 0 (F / S held);
  under MIN_TRADES = 10 trades no band;
- days: from the book's start to the report.

They go into the pump.fun realistic report (`reports/pumpfun_rt/realistic.md`, `realistic.json` key `ten`) and the
readiness ladder (`reports/ladder/latest.{json,md}`, a table of its own).

## The gate for real money (ladder step 5; the owner decides)

A book passes when all hold:

1. at least 30 days since its start;
2. the mean per trade after all costs above 0;
3. the band's lower end above 0 (at least 10 trades);
4. P2's paper minus live on all live signals under 2 points a trade (`realistic.json` key `selection`, `pass`);
5. P1's taint excluded (the numbers above skip it by construction; the count is shown).

In the ladder a P3 book's step 5 conditions are these five (the execution record's conditions judge real money
once it runs, which P3 precedes). Steps 1 to 4 are not waived: they ask for a back-tested record and a lockbox look
that a forward paper book does not have, so the ladder also shows the gate's verdict on its own in the P3 table.
Passing proposes; only the owner decides, and nothing in the lab arms the live bot.

## Trials

Three in R5's registry, family hand, counted only, registered by the daily job before it computes the first number:
`hand:p3:ten_eur:P_pool0_wait_10eur`, `hand:p3:ten_eur:P_pool0_10eur`, `hand:p3:ten_eur:P_cmig_model_10eur`. No
Sharpe, no DSR.
