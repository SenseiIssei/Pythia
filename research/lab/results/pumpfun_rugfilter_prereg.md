# A rug filter for P_pool0_wait (Y16): pre-registration (2026-10-24)

Written and committed before any replay below was computed. Code: `lab/pumpfun_rt/pipeline.py` (`_build_y16`,
`RUG_CUT`, `Pipeline.cut_ok` and its branch in `signal`), `lab/pumpfun_rt/rug16.py` (the run), tests
`tests/test_pumpfun_rugfilter_y16.py`. Paper only: nothing here holds a wallet, reads a key, signs or sends anything;
the live service, its executor, its sizing and its confirmation file are not touched. A change to anything below
after the first result is a new trial with a new name.

## Why

The live bot trades `P_pool0_wait` (buy the PumpSwap pool at the migration or up to 5 s later at its first trade,
+30 %, stop -20 %, 300 s). On 2026-10-23 from 15:00 UTC it closed 26 trades: 12 winners, most losers at the -20 %
stop, and several one-step crashes the stop cannot catch at our latency (SpaceX AI -81 %, ROOM -52 % within 2 s,
SHEKEL -37 %, MITY -31 %). The owner: "we keep buying rugs". Y9's `P_pool0_norug` (P(rug0) at most its base rate)
did not beat P_pool0 out of sample; Y10 found that the trend features lift the rug models' AUC (rug0 0.638 to 0.675)
and not the win models'. Y16 asks whether a rug rule at P_pool0_wait's entry, with Y10's rug model or with one
feature, beats P_pool0_wait.

## What was looked at before this plan

Disclosed: Y9's and Y10's reports and pre-registrations, Y11 to Y15's; the live journal (`live_trades.json`,
`orders.jsonl`) of 2026-10-23, returns and exits of the live trades listed above; the record's list of days
(2026-10-20 to 2026-10-23 23:55 UTC); that the server's model folder has no `sel_rug0t` yet (the daily retrain has
not trained the trend models; the replay trains its own). The code was checked on synthetic records in the tests and
by replaying every rule and every strategy on the recorded 2026-10-20 with the code before and after (section 4);
only the equality and the count of the new books' trades were looked at, no return of any book and no feature of any
recorded entry. No rule below was replayed on the record.

## 1. The crash, and the features at the entry

**A one-step crash**: a closed trade of P_pool0_wait that lost more than 35 % over its stake after every cost, or
during which one pool trade took 30 % or more off the pool's price (price after that trade against the price after
the pool trade before it, from the landing to the exit). A failed buy is no crash.

Noted at every signal of the X0 books (what a decision may know at that moment, `rug16.RugPipe.snapshot`):

| group | features |
|---|---|
| the Y10 rug twins' scores | P(rug0t) (Y9's rug label, the trend features too) and P(rug0) (without them), the day's walk-forward models |
| the creator | its holding (`dev_hold_share`), dev buy SOL, prior coins, prior migrations, dump rate |
| the top holders after the migration | the top 10 wallets' share at the completion (`c_top10_share`), the top 1 and top 5 now |
| liquidity | the pool's SOL at the signal (`pool_sol`) |
| the curve | its duration (`age_at_complete_s`), distinct buyers (`unique_buyers`, and over its last 5 min) |
| bundled buys | other wallets buying in the slot of the coin's first curve trade, the creation's when the dev buys there (count and share of the supply), the first five buyers' share |
| the dev's sales so far | the share of its buys sold on the curve (`dev_sold_frac`), its sales on curve and pool over the supply |
| LP status | not in the record: every pool is made by the migration through the pump.fun program, the same for every coin; reported as such |

Reported per feature on X0's out-of-sample entries (both latencies, 1.0 SOL): known for how many crashes and others,
the median in each, and the AUC of the feature for a crash. Descriptive, not judged.

## 2. The twins

Each is P_pool0_wait (same entry, wait, exits, stake 0.1 SOL) that skips the entry when its rule fires; the rule is
asked where P_pool0_wait would buy (also at the pool's first trade after a wait).

| book | strategy | skips the entry when |
|---|---|---|
| X0 | `P_pool0_wait` (unchanged) | |
| R1 | `P_pool0_wait_norug` | P(rug0t) is above its base rate (Y9's select filter, `("max", 1.0)`) |
| R2 | `P_pool0_wait_norug_half` | P(rug0t) is above half its base rate (`("max", 0.5)`, the stricter cut) |
| R3 | `P_pool0_wait_rugcut` | the best single-feature rule, picked in sample (below), says so |

R1 and R2 skip "no model" while no rug0t model exists. **R3's pick**: at the start of the out-of-sample part, on the
closed in-sample entries of X0 at the measured latency under 1.0 SOL (failed buys included, as entries that lost their
fee), each of ten candidates on its registered rug side, cut at the in-sample tail of 10 % and of 20 % of the entries
with the value known: skip when high, `c_top10_share`, `top5_share`, `dev_hold_share`, `first5_share`,
`creator_dump_rate`, `dev_sold_frac`; skip when low, `pool_sol`, `age_at_complete_s`, `unique_buyers`, `c_ubuyers_300`
(20 rules). The rule whose kept entries have the highest mean return per entry wins; a tie goes to the one keeping
more. A value not known keeps the entry. Only features the paper engine computes at the decision are candidates (the
slot buys are reported, not used). Before the pick R3 trades as X0 (in sample, not judged); the pick is used at both
latencies and under both limits from then on. The result commit writes the picked rule into `pipeline.RUG_CUT`, so
the paper engine's R3 trades it; until then R3 skips "no model" there.

## 3. Record, models, latency, costs, limits

- **Record**: every recorded day from the record's start (2026-10-20) up to the cutoff **2026-10-23 23:00 UTC** (the
  last complete UTC hour at registration), entries until 15 minutes before it, so every position closes inside.
- **Models**: Y9's label book (`selfeat.LabelPipe`, every plain migration bought as P_pool0 would, Y9's latency) in
  the same replay, with the trend tracker; at the end of every UTC day `selmodel.train` on what was decided and
  labelled before the next day starts, used through that day (`select9.DayModels`), as Y10.
- **Out of sample**: from the start of the first UTC day with a rug0t model (Y10's rule, expected 2026-10-22). The
  in-sample part is only reported (and picks R3's rule).
- **Latency, two models, both judged**: **A**, the paper engine's own (`curve.Costs`: lognormal, median 1 s, 0.4 to
  3 s); **B**, the measured live latency, Y9's (the live executor's Sender fills, buy median about 10 s, sale about
  4 s), as Y12 to Y15. Same failure model as the paper books.
- **Fee**: 0.001005 SOL per transaction; a failed buy pays it. **Draws**: every book draws with P_pool0's key, so a
  migration's buy lands at the same moment in all books of one latency.
- **Limits**: at most 4 positions, exposure cap 0.6 SOL, under two daily loss limits, both judged: **L25, 0.25 SOL**
  (the live bot's) and **L100, 1.0 SOL** (the code's cap). Gapped trades kept (Y8's rule).

## 4. Code changes and the equality check

`_build_y16` (three strategies appended after `P_pool0_wait_tol60`), `RUG_CUT` (None), `Pipeline.cut_ok` and one
branch in `signal` (a strategy without `cut` in its filter never reaches it), `strategies.RUGFILTER_Y16_TRIALS`. Every
strategy before Y16 and the 22 rules were replayed in one shared paper book with the label book, the select and trend
trackers and the server's models on the recorded 2026-10-20, with the code before the change and after it (the new
books in the same book, and once more with a rule in `RUG_CUT` so that R3 trades): the closed trades, failed buys and
skip counts of the old strategies identical field for field (the pid aside, as Y9 to Y15): 18,872 closed trades and
1,049 failed buys, the 109 skip counts too, both times. Printed besides the equality: the new books' trades that day,
none for R1 and R2 (no `sel_rug0t` on the server: "no model") and none for R3 without a rule, 37 closed for R3 with
the test rule; no return. The tests do the same on a synthetic record. The live service is not touched.

## 5. Reported, per book, latency and limit (out of sample)

Entries (closed trades plus failed buys), hours, mean and median return per entry over the stake after every cost,
win rate, total P&L in SOL, the hour-block 90 % band of the mean, maximum drawdown, exits, skips (rule, no model,
daily loss limit). Per twin: **on X0's own entries** (path-free) the entries the rule keeps, the crashes it avoids,
the winners it loses, the mean of the kept and of the cut, the cut's P&L; and **the twin's own book** against X0: the
difference of the means with its band, the P&L difference. R3's pick and its 20 candidates (in sample). The live
book's trades of 2026-10-23 from 15:00 UTC with what each rule says on the features the replay noted at that coin's
last signal (B, 1.0 SOL; n/a where the replay never signalled it). The in-sample part.

## 6. Verdict

Y8's rule, per latency and limit: a twin is **better than X0** (out of sample, gapped trades kept) only if both hold:

1. the difference of its mean return per entry against X0's has an hour-block bootstrap 90 % band above zero
   (`study.boot_diff`, 5,000 draws, the same hours for both, each book's mean over all its own entries, failed buys
   included); with fewer than 10 hours of entries in either book the band is n/a and the answer is no;
2. its total P&L is higher.

A twin **beats P_pool0_wait at a latency** only if it is better than X0 under both limits at that latency; the answer
for the live bot is the one at **B**. Every book is reported, whatever the answer. **Trials**: three twins, two limits,
two latencies, `strategies.RUGFILTER_Y16_TRIALS = 12`, added to `strategies.N_TRIALS` (R3's 20 candidates are chosen
in sample, only the pick goes out of sample).

## 7. Paper forward test

R1 to R3 join `pipeline.STRATEGIES` (`_build_y16`), 0.1 SOL each, and run in the paper engine from the deploy on (R1
and R2 once the daily retrain has trained `sel_rug0t`, R3 once the result commit set `RUG_CUT`), at least two weeks
before anything about the live bot is decided, whatever this replay says. Nothing goes live: the live executor trades
the strategy its confirmation file names, and moving the live book to a twin is the owner's decision.

## 8. Too early

About three and a half days of record, out of sample under two days, the rug models trained on two and three days of
label rows, a few dozen crashes. Under the 0.25 SOL limit earlier studies saw X0 stop after a handful of entries.
The verdict says what this record shows; the paper books are where the evidence has to come from.
