# pump.fun for a small wallet, under realistic execution (R2): pre-registration (2026-10-24)

Written and committed before any replay below was computed. Code: `lab/pumpfun_rt/labels_r2.py` (the realistic
labels), `sim.py`, `early.py`, `selfeat.py`, `study.py`, `retrain.py` (where they go), `lab/pumpfun_rt/smallwallet.py`
(the search), `realistic.py` and `live.py` (the paper books), tests `tests/test_pumpfun_smallwallet_r2.py`. Paper
only: nothing here holds a wallet, reads a key, signs or sends anything; the live service, its executor, its sizing
and its confirmation file are not touched. A change to anything below after the first result is a new trial with a
new name.

## Why

R1 (`results/pumpfun_realistic_r1.md`) made the realistic execution model the paper default: buys land a median
8.8 s after the signal, not 0.4 to 3 s, and that halves the paper gains. The lab's models are still trained on labels
made at the old latency, and the owner trades with 50 to 100 EUR (0.55 to 1.1 SOL), where R1 found that every book
loses its wallet again and again at the owner's all-in sizing. R2 asks: which labels change at the realistic entry,
and which strategy and sizing gets the most out of 0.55 or 1.1 SOL when the trades are executed the way the live bot
gets them?

## What was looked at before this plan

Disclosed: R1's result and code, the reports and pre-registrations of X8, X14, Y8 to Y16; the live bot's settings
files (100 % share, brake off, floor 0, one position); the record's list of days (2026-10-20 16:39 to 2026-10-24
UTC). No replay, label or model below was computed before this file was committed.

## 1. The labels at the realistic entry and exit

The draws are R1's (`realistic.Fit`, the daily job's fit of the live orders of the last 7 days): the buy lands the
drawn buy latency after the decision, failures are drawn at the live rates with their fees, the fill is at the
state of the first recorded trade of the coin at or after the landing (that trade included), else 2 s later as it
stands; a sale lands the drawn sale latency after its decision, filled the same way; the fee per transaction is the
live median plus the Sender tip. Each draw is seeded by the row's own key, so a replay draws the same.

| models | label | at the realistic entry and exit |
|---|---|---|
| models.md (decision rows, 0.1 SOL on the curve) | win30, win300 | the buy as above with the cost limit (curve.SLIP_TOL); sold at the later of decision + 30 s (300 s) and the fill, landing one drawn sale latency later; win when the net return after every cost is above 0; a failed buy is a loss of its fee; a sale into a completed curve with no pool yet is unknown (NaN), as before |
| | up10, up30, up120 | the price 10, 30, 120 s after the realistic fill above the fill price |
| | dump60, mig, sell10_10, sell10_30 | no execution in them: unchanged |
| Y9 select (selfeat.LabelPipe) | win0, win5 (and Y10's win0t, win5t) | P_pool0 at the migration and 5 s after it, executed by `realistic.RealExecutor` at 0.1 SOL (R1's fills, pool bound with the pre-send skip and 6040, failures, fees, sale latency), P_pool0's exits; win = the trade's P&L above 0 |
| | rug0, rug5 (and rug0t, rug5t) | the pool's price at or under half the pool's price at the drawn landing, within 60 s after that landing |
| X14 early (early.Tracker) | peak3x, peak10x | the buy of 0.1 SOL lands at the drawn latency (failures drawn, first trade at or after, cost limit); the peak of its value net of the realistic sale fee within one hour of the fill at 3x (10x) its cost and fee |
| | mig1h, alive5m | no execution in them: unchanged |
| X14 exit (steps) | hz_dump10, hz_up30 | the step labels describe the path ahead of a held position; unchanged. hz_policy's k* is chosen with the realistic sale latency and fees |

Features: unchanged, the same sets and the same adoption rule for every label.

The daily retrain trains every model on the realistic labels under its usual name (what the paper books use), and
the old ones on the old labels as `<name>_ideal` (in `models/pumpfun_rt/ideal/`, never read by a book), side by side
in `models.md` and `select.md`, until 2026-11-07; then the `_ideal` twins stop. Their comparison is descriptive,
not a trial.

## 2. The small-wallet search

**Candidates** (7): `P_pool0_wait` (the live strategy); R1's three best realistic exit variants by mean per trade,
`P_pool0_wait_lock`, `P_pool0_wait_run20`, `P_pool0_wait_free10_tight`; the Y9 filter `P_pool0_top30`; Y10's two
leaning books `P_pool5_top30t` and `P_hot5`. No rug filter: Y16 found none that beats P_pool0_wait.

**The replay**: the record to 2026-10-24 00:00 UTC, entries to 23:45, with R1's realistic model fitted to the live
orders of the 7 days to that cutoff. Each candidate is one realistic book at 0.1 SOL without a slot, exposure or loss
limit, so every signal has its realistic outcome. The Y9 select models (on the realistic label rows of section 1)
and et_alive5m are trained at the end of each day for the next (walk-forward). Out of sample are the full UTC days
from the first day on which every candidate has its models to 2026-10-23.

**The wallet**: the live sizing with limits=wallet (`sizing._wallet`): the share of the base (wallet and open cost),
at least 0.05 SOL, rounded down to 0.01 SOL, at most what the wallet can pay (0.01 SOL reserve, the slippage room),
the drawdown brake on or off, the owner's floor 0 (all in until the wallet cannot pay 0.05 SOL); and at most 2 % of
the pool's or curve's SOL (pipeline.MAX_IMPACT). A trade's return at a stake other than 0.1 SOL is the recorded one
with its price impact rescaled on the reserves at the buy and the sale (constant product); the per-transaction fees
as recorded; a failed buy costs its recorded fee, a skip nothing. At most max_open positions; no daily loss limit
(limits=wallet has none); no top-up.

**The grid**: 7 candidates x share 10, 25, 50, 100 % x max_open 1, 2, 3 x brake on, off x start 0.55 and 1.1 SOL:
336 settings, counted as 336 trials.

**The bootstrap**: 2,000 paths of 30 days; each day drawn with replacement from the out-of-sample days, the same
draws for every setting; the day's entries in their time order on the path's wallet, positions open across midnight
carried. Per setting: the wallet after 7 and 30 days (median, 10 and 90 % of the paths), the chance to reach 2x the
start before falling to 20 % of it, the chance of ruin (the wallet cannot pay one trade of 0.05 SOL with nothing
open) within 30 days, the days to 100 EUR from 0.55 SOL (from 1.1 SOL: to 200 EUR; 1 SOL = 91 EUR, the owner's file
of 2026-10-24), as the median over the paths (a path that does not get there counts as more than 30) and the share
of paths that get there.

**Positive expectation**: per candidate, the mean P&L per entry at 0.1 SOL over the out-of-sample days with a
90 % band from a day bootstrap; per setting, the mean wallet after 30 days against the start. A setting has a
positive expectation only when both are above zero.

**The picks** (from 0.55 SOL): (a) the highest median wallet after 30 days, (b) the highest chance to reach 2x before
-80 %, (c) the lowest chance of ruin among the settings whose median wallet after 30 days is above the start. The
paper books are the distinct settings among (a), (b), (c) (two or three; where one repeats, the next of its own
order). The picks are chosen among 336 settings on the same few days: their numbers are optimistic, the paper books
are the forward test.

## 3. The paper books

The picks run as realistic paper books from the deploy, each with its own paper wallet of 0.55 SOL and its sizing
fixed as picked (not the owner's settings), next to the other paper books in the paper ledger; the daily job
`pumpfun-rt-realistic` writes their wallets in SOL and EUR to `reports/pumpfun_rt/realistic.md`, and the daily card
shows them. The live bot is unchanged; the owner decides.
