# Do the Alpaca books beat BTC held only above its 200-day average? Pre-registration

Registered 2026-10-21 and committed before any number below was computed.
Drafted by the lab's research director job
(`proposals/2026-10-20-alpaca-books-vs-gated-btc.md`); every number and data
reference was checked against the code and the published results before this
file was committed, and the corrections are listed at the end. Code:
`lab.experiments.gated_btc` (written after this file). Results go to
`results/gated_btc.md`. Nothing here may change once a result exists.

## Question

Does at least one of the four long-only books the autopilots run on Alpaca
beat BTC held only while it closes above its 200-day average (G), at the same
in-sample volatility, out of sample at 35 bps, with the bootstrap 90 % band of
the difference above zero?

## Why now

Every book the autopilots run depends on the BTC gate. breakout_study finds
1.67 with BTC above its 200-day average and -0.74 below it (out of sample,
41 bps); tsmom_tranches 0.76 and -0.81. fast_strategies says every 4h pick
leans on the gate. In regime (M5), the 200-day switch alone on BTC makes
0.79 / 0.71 at 15 / 41 bps from 2024 with a 32 % drawdown, against 53 % for
plain holding. The book studies compare the books with ungated BTC (0.74 from
2024 in alpaca_universe), the weaker benchmark. No study has yet tested the
books against the gate on its own.

## Data

- The sweep's survivorship-free daily panel (`fam_common.load_panel`), rebuilt
  from the hourly Binance history on the PC (which runs to 2026-10-19) and cut
  at **2026-10-14**, so all four books end on the same day as the
  trend4h_pullback run (fast_maker's `DATA_END`). The cached panel on the PC
  ends 2026-10-11 and is not used.
- breakout_top10, tsmom_top20 and tsmom_tranches as they run on Alpaca: the
  paper books' own targets (`alpaca_universe.originals`), every coin Alpaca
  does not list held as cash (`alpaca_universe.cash_left`, the C rows of
  alpaca_universe), the books' own simulators (`alpaca_universe.simulate`).
- trend4h_pullback: fast_maker's in-sample pick in its only paying family,
  "B EMA 24/96 · p 0.5 · W 1h · BTC gate", on the 33 coins, on the 1h bars the
  PC holds (the registered 5-minute run is a server command; the 1h and 5m runs
  agree, results/fast_maker_5m.md). fast_maker does not store the pick's daily
  returns, so the pick alone is rerun with fast_maker's own code; that adds no
  trial.
- G: BTC's daily close and its 200-day average from the same panel
  (`Panel.btc_on`, the gate the books use).

## Design

- In sample 2020-08-01 to 2023-12-31, out of sample 2024-01-01 to 2026-10-14
  (fast_maker uses the same windows).
- **G** holds BTC at weight k while BTC's close at day t is above its 200-day
  average and cash otherwise, earning day t+1. It buys to k at a switch-on
  close, sells everything at a switch-off close, and in between trades back to
  k only at a close where the drifted weight is more than 25 % away from k
  (relative). At k = 1 it never trades in between.
- **k per book** = the book's in-sample daily volatility (net at its judged
  cost, cash days included) divided by G's in-sample daily volatility at
  k = 1 (net at 35 bps), capped at 1. It is fixed from in-sample data before
  any out-of-sample number is computed.
- **D** = the book's daily net return minus G's (at that book's k) on the same
  days, both at the same cost level.
- Reported for each book and for G: Sharpe (daily, x sqrt 365) and drawdown in
  and out of sample, D's Sharpe overall and in 2024, 2025 and 2026 (to
  2026-10-14), a stationary bootstrap of D's Sharpe (mean block 20 days, 4,000
  draws, seed 20261020, 5 % and 95 %), the out-of-sample vol ratio next to the
  in-sample one, D at 70 bps, and D's deflated p.

## Costs

- The three daily books and G: 35 bps per unit of one-way turnover (Alpaca
  taker plus slippage), 70 bps as stress; G's switches and trims pay the same.
- trend4h_pullback: judged at fast_maker's base (every maker fill pays 15 bps
  and is booked 3 bps worse; an exit still open after 24 h is sold at 35 bps),
  against G at 35 bps. Stress: every order filled at the close at 70 bps,
  against G at 70 bps. Also reported, not judged: every order at the close at
  35 bps.

## Trials (4)

- D for each of the 4 books: 4.
- G itself: 0 (the BTC 200-day switch is already counted in regime, M5).
- The 70 bps lines and trend4h's close-fill line are the same books at other
  costs, not new trials.

**Pool.** 1,115 hand trials after X15 and X16 (results/candles.md), 600
genomes in the factory ledger, and the 9 trials of the three studies
registered together today (this one 4, `genome_gates` 4, `m4_residual` 1):
**1,724** trials. The next study starts from 1,124 hand trials. Deflation as
in the other studies: the hand trials at the variance backed out of the
published bar (377 trials at 2.43), the factory's in-sample Sharpes, this
study's own trials, each at its own variance; the best of that many noise
trials sits at an annual Sharpe of about 2.73.

## Pass rule (per book)

A book beats the gate when all of these hold:

1. D's out-of-sample Sharpe is above 0 at its judged cost;
2. D is positive in at least 2 of 2024, 2025 and 2026;
3. the bootstrap 5 % bound of D's Sharpe is above 0;
4. D's Sharpe is above 0 at the stress cost;
5. the book's out-of-sample drawdown is at most G's plus 5 percentage points.

It counts as confirmed only if D's deflated p is also above 0.95 over the
pool of 1,724.

## Kill rule

A book whose D has a Sharpe at or below 0 at its judged cost is written up as
"no better than gated BTC at the same risk", and the write-up recommends to
the owner that the autopilots stop choosing it (nothing is changed here;
trend4h_pullback is experimental and never auto-picked already). If all four
fail this way, the lab records that its Alpaca book set is gated BTC exposure
and stops adding trend variants on Alpaca coins. A book that neither passes
nor is killed is "not shown to beat gated BTC".

## If gated BTC carries the books: G as a paper book

If no book passes, G's own record at k = 1 decides whether the study proposes
it as a lab paper book. G must pass the factory's shadow gates plus a year
rule, out of sample at 35 bps unless said otherwise:

- G1 both in-sample halves (split at the middle day of the in-sample window)
  have a Sharpe above 0;
- G2 Sharpe above 0 at 35 bps and at 70 bps;
- G3 drawdown below BTC bought and held over the same days;
- G4 still above 0 when every decision is filled one close later;
- G5 positive in at least 2 of 2024, 2025 and 2026.

Its deflated p over the pool is reported; like every paper book the lab runs
today it is not required for a forward paper book, only for anything beyond
paper. If G passes G1 to G5, the study adds it as the lab paper book
`btc_gated`: a signal file in the format of the other books, marked
`autopilot_only` (no engine runs it on its own and no autopilot runs it until
one is configured to name it), forward evidence only, and a job entry in
`research/ops/jobs.yaml` in the same format as the others, not deployed. If
G fails any of G1 to G5, nothing is proposed.

## What could fool us

The vol ratio is set in sample. If a book's volatility shifted out of sample,
G is over- or under-sized and D carries a hidden BTC bet, so the
out-of-sample vol ratio is reported next to the result. A pass by breakout
alone could rest on 2024 (breakout_study: its Sharpe halves without 2024),
which is why the year rule is there. G at k = 1 is BTC itself while the gate
is on: if it passes, the paper book is a slower, cheaper version of what the
books already hold, and it holds a single coin.

## Corrections to the draft

- Pool: the draft counted 977 trials (the factory's 377 hand trials plus its
  600 genomes, as the factory ledger reports them). The hand count is 1,115
  after X15 and X16, so the pool is 1,724 with today's 9, and the noise bar
  about 2.73, not 2.56.
- Data end: the cached panel on the PC ends 2026-10-11; the panel is rebuilt
  from the hourly history and cut at 2026-10-14.
- trend4h_pullback: run on the PC's 1h bars (the 5-minute run is the
  server's); its stress line is defined (every order at the close at 70 bps).
- G's holding rule (buy at a switch-on, 25 % trim band) and the bootstrap
  draws and seed are fixed here; the draft left them open.
- Kill rule: "the owner takes it out of Auto-Pick's candidates" becomes a
  recommendation; nothing live is changed by this study.
- Added: what follows if gated BTC carries the books (G1 to G5 and the
  `btc_gated` paper book, off by default).
