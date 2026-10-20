# Exit shadow: pre-registration

Registered 2026-10-20, before the first decision. Code: `lab.paper.exit_shadow`;
job `exit-shadow` in `research/ops/jobs.yaml`. Nothing below may change once the
first decision is in the ledger; a change is a new registration with a new name
and a fresh clock.

## Why

X16 B2 (`exit_overlays.md`, write-up in `equities_training.md`) left two exit
ideas that look good out of sample but are not evidence:

- **The M14 model exit on tsmom_tranches**: Sharpe 1.64 against 0.64 from 2024,
  drawdown 1.5 % against 8.8 %, passes gates 1 to 5 and fails the deflated
  improvement (p 0.021). It mostly de-risks (cuts 86 % of the held days, holds
  2 % of the capital instead of 9 %) and times BTC's 28-day momentum (31 % of
  M14's gain).
- **A 40-day time stop**, found after the fact (selected by nobody): out of
  sample 1.35, 0.78 and 1.19 against 1.17, 0.53 and 0.64 for breakout_top10,
  tsmom_top20 and tsmom_tranches.

Both can only become evidence forward, judged on data that did not exist when
this file was committed.

## The books

breakout_top10, tsmom_top20 and tsmom_tranches as the autopilot runs them on
Alpaca, exactly as X16 B2 built them: the paper books' own target functions
(`alpaca_universe.originals`), every coin Alpaca does not list held as cash
(`cash_left`), the books' own simulators (`alpaca_universe.simulate`), on the
daily panel the paper books rebuild each night. The reference ("the book") is
those weights run through `alpaca_universe.sim_daily`; the overlaid book is the
same with the cut coins at 0, freed weight in cash (`exit_overlays.fires`,
`cut_from`, `spells`).

## The two rules (frozen)

A spell is a run of closes after which the book holds a coin. An exit fires on
a close inside a spell and cuts the coin from that close to the end of the
spell; it comes back only when the book's own rule enters it again.

**M14 exit** (on tsmom_tranches): fires when the frozen M14's forecast of the
next 10 days' log return, `z x 30-day vol x sqrt 10`, is below **-70 bps**.
The features are M14's twelve (`m14_exit_hazard.FEATURES`) on the book's own
spell, as in `exit_overlays.held_rows`.

The model is frozen: LightGBM (`lab.equities.features.PARAMS`, LightGBM 4.7.0)
fitted once on every M14 row with a known target, 19,700 coin-days held by the
original breakout_top10 or tsmom_top20 from 2020-08-01 to 2026-10-09 (the
X16 panel to 2026-10-19), written by `python -m lab.paper.exit_shadow --freeze`
to `lab/models/frozen/m14_exit_shadow.txt`:

    sha256 105bacba2a290b19aca8482bafb46018b6f1f7ad259da47abbc00c1cf61a78c6

The job refuses any other file (status bad, nothing recorded). The model is
never refitted for this test. Ongoing spells use the same model on their
earlier days, so a cut that started before registration carries on.

**40-day time stop** (on breakout_top10, tsmom_top20 and tsmom_tranches): fires
on the 40th close after the entry close (`days since the spell's first close >= 40`).

So four pairs, each judged on its own: tsmom_tranches with M14, and each of the
three books with the time stop.

## What is recorded each day

After the paper books' signals (`paper-families`), for the close of
**yesterday (UTC) only**, never an older one, one line per book appended to
`<data>/paper/exit_shadow/decisions.jsonl`: the day, the time written, the
book's weights after that close, for each of its overlays the weights with the
overlay, the coins cut and the coins cut first on this close, and per held coin
its days held and (tsmom_tranches) M14's forecast; the model hash on the
tsmom_tranches line. Records before 2026-10-20 or written after the close of
the following day are refused.

**Scoring.** A record for the close of day D is scored on the return of day
D+2: held from the close of D+1, a full day after the record was written, so no
scored return was known when it was written. Turnover is traded at the close of
D+1 from the record of D-1 drifted over day D+1 and costs **35 bps** per unit
(not charged after a missing day, for either side). A dead coin earns 0. Each
record is scored once, when day D+2 has closed, into `scores.jsonl`. Both files
are append-only. The daily series of a pair are the book's and the overlaid
book's net returns on the same scored days; a missed day is missing from both.

**An exit decision** is a coin cut first on a close (a new cut, the `new` list).

## The pass rule (per pair, once)

Judged on the first **n >= 90 scored days** by which the overlay has made at
least **30 exit decisions**. On those n days:

1. the annual Sharpe (daily, sqrt 365) of the overlaid book is above the book's;
2. the **bootstrap band of the difference** (Sharpe overlaid minus Sharpe book,
   the same resampled days, stationary bootstrap, mean block 20, 4,000 draws,
   seed 20261020) is above 0 at its **1.25th percentile** (one-sided 5 %,
   Bonferroni over the four pairs);
3. the maximum drawdown of the overlaid book is **not worse** than the book's.

All three hold: passed. Otherwise: failed. A pair with fewer than 30 exit
decisions after 365 scored days fails. The verdict is reached once, on that
prefix, and never revisited; later days are still recorded but do not change
it. Interim numbers in the report are not a verdict.

## What follows

**Nothing trades on either rule before it passes, and a pass is not a
deployment.** No paper book, signal, autopilot or engine reads the ledger or
the report; the engine does not change. A pass is written up next to this file
and goes to the owner, who decides whether it becomes a separately registered
paper overlay. A fail is a record, like the X16 trials.

Shown in the app as the lab feed `reports/exit_shadow/latest.json` (Research
page); the daily digest gets one line only on a day a pair changes status
(started, passed, failed).
