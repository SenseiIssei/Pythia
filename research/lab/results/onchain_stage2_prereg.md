# Own wallet, stage 2: the evidence a book must show before real money on chain (pre-registration, 2026-10-23)

Written and committed before any stage-2 code exists and before any book traded on chain, on paper beyond
stage 1 or with real money. Design: `docs/ONCHAIN-STAGE2.md`. A change to a number below is a new
registration with a new date in this file, in git; nothing here may be loosened after a book's result is
known.

## Why

Stage 1 (`docs/ONCHAIN.md`) measured 1 to 22 bps one way for a 100 USDC swap through Jupiter against
Kraken's 40 bps taker fee, in one reading. Cheaper fills do not make a book profitable, and on chain three
new things can go wrong that Kraken handles for us: the book on chain is not the same book (coins without a
Solana form sit in cash), the fills are worse than the quotes (impact, failed or late landings), and the
executor builds or signs something it should not. Each gets its own test below, and all of them must pass
for each book separately.

## Who is judged

A book named in the stage-2 ack (`books=`). Today the only candidate is `breakout_top10_live` through its
on-chain paper twin `onchain_breakout_top10_live` (`lab.onchain.book`). Another book first needs its own
on-chain paper twin; its days count from that twin's first journal row.

## The gate, in four steps (all in order, none skipped)

### A. The strategy itself

The book passes the real money readiness rule of `docs/LIVE-READINESS.md` (all nine rules, at the risk step
the owner set) on its paper record, on the day the gate is judged. Stage 2 adds nothing to that rule and
takes nothing away.

### B. The on-chain paper twin (from its journal, `paper/onchain_<book>/`)

All must hold over the twin's whole record:

| # | rule | passes when |
|---|---|---|
| B1 | days | at least **30 calendar days** of journal rows |
| B2 | rebalances | at least **20 days with at least one fill** that was not a cost probe |
| B3 | cost | median cost per unit traded (`paper_cost_bps`, each fill half its round trip plus the network fees) at most **15 bps**, and the 90th percentile of single fills at most **40 bps** |
| B4 | same book | the twin's mean share of target weight held as cash because a coin has no listed mint at most **25 %**; above that the book on chain is a different book |
| B5 | tracking | the twin's return over the record at least the lab book's return over the same days **minus 1.5 points** (the gap is costs plus the cash of B4; a larger gap means the twin does not do what the book does) |
| B6 | quotes | at most **2 %** of planned swaps without a usable quote (no route, error, over the 50 bps cost limit) |

### C. Shadow execution (`lab.onchain.shadow`, built in a later task)

The stage-2 executor runs on every planned swap of the twin for at least **14 calendar days and 40 swaps**:
it builds the transaction through `/swap/v2/build`, runs the guard, simulates it on mainnet with the stage-2
wallet's public address as payer and the account diff, and never signs or sends.

| # | rule | passes when |
|---|---|---|
| C1 | clean | at least **98 %** of simulations succeed and pass the effect check (input debit at most the amount, output credit at least the minimum, no other account of ours touched) |
| C2 | guard | **zero** guard refusals of a Jupiter build without a written explanation in the shadow report; a refusal that points at a guard bug resets the 14 days after the fix |
| C3 | fill | median simulated output against the quote's `outAmount` no worse than **-5 bps**, and no simulation below `otherAmountThreshold` that passed |
| C4 | fees | median network cost per swap (base fee, priority fee, Sender tip) at most **0.0001 SOL**, none above the 0.0005 SOL cap |

### D. The capped test

Only after A to C: the owner may arm `mode=test` with `max_total_usd` at most **200 USD** for the first
**14 calendar days**. It passes when:

| # | rule | passes when |
|---|---|---|
| D1 | landed | at least **95 %** of sent swaps land within their blockhash; none lands twice |
| D2 | cost | median realised cost per swap (against the quote mid, network fees included) within **10 bps** of the twin's paper cost over the same days |
| D3 | ledger | the ledger reconciles with the chain (token balances and SOL) on every one of the 14 days, no unexplained difference |
| D4 | tracking | the live account's return within **1 point** of the twin's over the same days |

Then, and only then, the owner may raise the caps up to the code's test maxima. Any failed rule of D stops
new buys and goes to the owner with its numbers.

## How it is computed

`lab.onchain.proof` (a later task) writes `reports/onchain/proof.json` and `.md` once a day with every rule
per book, its value and pass or fail, from the twin's journal, the shadow report, the readiness report and
the live ledger. It never arms anything: when a step newly passes, the owner gets one Telegram post. Arming
stays the owner's written ack.

## What does not count

- Days before the twin's first journal row, backfilled or replayed days, and days on which the twin's signal
  was stale (the twin holds; the day counts for B1 but not B2).
- Shadow swaps simulated with a different payer than the stage-2 wallet, or after the guard was changed
  without the tests of every refused variant.
- The pump.fun bot: its own gates (`docs/PUMPFUN-LIVE.md`) are untouched by this registration.
