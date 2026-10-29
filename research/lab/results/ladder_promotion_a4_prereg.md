# A4: the readiness ladder promotes on its own, steps 2 to 4 (pre-registration, 2026-10-29)

Written before any code of A4 and before any number it makes. Background: the review of 2026-10-27
(`results/review_2026-10-27.md`, sections 2 and 3), R5's registry (`metrics.trial_pool`, `<data>/trials/registry.jsonl`),
R6's windows (`results/factory_lockbox_r6.md`: in sample to 2023-12-31, validation 2024-01-01 to 2026-06-30, lockbox from
2026-07-01) and the ladder's own rules (`results/readiness_ladder_prereg.md`, T3; the pump.fun rules:
`results/ladder_pumpfun_prereg.md`). Paper only: nothing here trades, arms, reads a key or changes what a live bot, a
wallet or the engine reads.

## What is automatic

The ladder (`lab.ops.ladder`) keeps deciding on which step a candidate stands; it changes no step 1 or 2 rule. A daily
job `promote` (`lab.ops.promote`) acts on its rows:

- **2 to 3.** A candidate whose row stands on step 2 or higher gets one forward shadow, keyed by its ladder id, in
  `<data>/promotions/shadows.json`. Once ever: an id already in the registry is never created again or restarted, also
  after it fell back below step 2. The start is the day of the run (UTC); only dates after the start count. Each new
  shadow is one trial of R5's registry (`promote:shadow:<id>`, its ladder family, counted only), registered when it
  is created.
- **3 to 4.** A shadow that passed its length and its gate (below) gets **one** lockbox look.
- **4 hand-over.** `<data>/promotions/live_ready.json` lists the step 4 passes only.
- Step 5 (at most 50 EUR, real money) and step 6 are not part of A4. Nothing reads `live_ready.json` in A4.

## The shadow of each kind, from what the ladder records

Each shadow is `<data>/promotions/shadow/<id>.csv` (date, ret, trades, logged_ms), appended once a day by the job,
never rewritten.

- **paper book** (`book:<name>`): its own journal `paper/<name>/journal.csv`, stepped by the book's own job, copied
  date by date: the day's return from equity (the last row of a date), a trade (rebalance) when the turnover is above
  0.01 (gate 7 of the paper review, `lab.paper.review`).
- **weekly factory genome** (`weekly:<key>`): the weekly factory's own shadow journal (`factory/shadow/<key>.csv`,
  net_ret at 35 bps and turnover) when the factory runs one; else the genome from `factory/holdout.jsonl` re-simulated
  on the long panel with the backtest's fills (`factory.build.run`, net at 35 bps), as `factory.shadow` does. A trade:
  turnover above 0.01.
- **F2 genome** (`F2:<key>`): F2's own 40 EUR shadow wallet (`factory/small/shadow/<key>.csv`: the day's return of
  equity_eur, a trade when orders grows) when F2 runs one. Otherwise **missing tool**: nothing starts an F2 wallet from
  the ladder's record yet.
- **pump.fun rule** (`pumpfun:<rule>`): the realistic paper ledger (`paper/pumpfun_rt/ledger.csv`) as the ladder
  reads it (P1's tainted rows and restart closes out, failed buys in): a day is a UTC date with any row of the five
  judged rules, the day's return the sum of the rule's entry returns, its trades its entries.
- **G2 model** (`G2:<key>`): **missing tool**: G2's shadows log forecast losses; no paper book trades a model.

A missing tool is shown on the ladder (step 3, "missing tool", with what is missing) instead of a guess, and is
checked again every run; the shadow starts on the first run the tool exists.

## Step 3 for a promoted candidate: length and gate

All of, from the shadow's own file (the ladder's step 3 reads them for every candidate in the registry):

- **days**: at least 30 dates after the start (the review's 30 days, gate 7).
- **trades**: at least 30 trades or rebalances after the start (gate 7).
- **before**: logged before the outcome, the registry's form of T8's check (T8's `reports/shadow/latest.json` is
  written by no job, so for a promoted shadow the registry proves it): the start was registered before the first
  counted date began, every row was logged after its date ended (logged_ms), and no logged row was changed or removed
  (the registry keeps the row count and a SHA-256 of the file's rows after every step; a different prefix fails).
- **pump.fun rules** also keep their step 3 of the ladder: T8's e-process shows an edge (`pf_edge`).

No other gate: step 3 adds no performance threshold of its own; step 4 is the test. A shadow under 30 days or 30
trades is never claimed for the lockbox (checked in the job itself, not only by the ladder's step).

## Step 4: the one lockbox look

In this order, for one candidate at a time:

1. **Ready**, without reading a return: the kind has a lockbox tool, and its data is long enough (genomes: at least
   60 days from 2026-07-01, `factory.evaluate.LOCKBOX_MIN_DAYS`). Not ready: no claim, asked again next run.
2. **Claim**: a line `{id, claimed_ms}` appended to `<data>/promotions/lockbox.jsonl` and synced to disk.
3. **Trial**: `promote:lockbox:<id>` registered in R5's registry (its family, counted only).
4. **The look**, then its result line `{id, result, conditions, pass}` appended to the same file.
5. Only then is the result read for the decision.

**A second run is refused**: an id with any line in `lockbox.jsonl` is never looked at again. A claim without a
result line (the run died) is a fail. **A fail is final** for that candidate: its shadow is closed, it never gets
another look, and it never enters `live_ready.json`.

The look of each kind:

- **weekly genome**: a look already made by the weekly factory for its key or behaviour (`factory/lockbox.jsonl`) is
  the one look (R6: each behaviour once ever); it is adopted, not repeated, and makes no new trial. Else a new look:
  the genome from 2026-07-01 to the panel's last day, net at 35 bps, its daily excess over BTC and ETH held half and
  half, its DSR (higher is better) over every look so far including this one (`ledger.deflated_excess`, n the looks),
  logged in `factory/lockbox.jsonl` (benchmark `btc_eth`) before it is used, so the weekly factory never looks at it
  again. **Pass**: the ladder's step 4: a look made, against BTC and ETH held, DSR at least 0.5 (`LOCKBOX_BAR`). An
  adopted look against BTC alone fails the benchmark, and that fail is final.
- **pump.fun rule**: no data exists before 2026-10-24, so its lockbox is the ladder's step 4 for the rules (T8's
  e-process on the day sums from 2026-10-30 on, `pf_fresh`), read **once** at the claim and frozen. **Pass**: edge
  shown.
- **paper book**: **missing tool**: no backtest of a paper book over the lockbox from its name (each book's code steps
  forward only).
- **F2 genome**: **missing tool**: its benchmark is a UCITS S&P 500 fund in EUR from 2026-07-01, and no job keeps
  that series (R10's quotes are one snapshot).
- **G2 model**: missing tool (above).

The ladder's step 4 for a promoted candidate reads only this file: no line "not looked yet", a claim without a result
fails, the result's conditions as written.

## The hand-over: live_ready.json

Rebuilt by every run from the result lines that passed, and from nothing else:
`{"generated", "budget_eur": 50, "prereg", "candidates": [{"id", "name", "kind", "study", "venue", "instrument",
"share_eur", "date", "evidence": [paths]}]}`. The share is 50 EUR split equally over the candidates in the file (cents
rounded down). Venue and instrument by study: S1 Kraken spot; S2, L1 and F2 Jupiter on-chain spot (Solana); R2, F3,
P3 and the pump.fun rules pump.fun memecoins; EQ1 Trade Republic ETF; the neutral books perpetual futures long/short;
the weekly genomes and the other books crypto spot, venue not chosen. The evidence: the ladder's report, the shadow's
file and journal, the lockbox file, the look's own file. When an id enters the file for the first time, one Telegram
line through `lab.ops.notify` (category "studies").

## Where it shows

The ladder report (a section "Promotions": each shadow, its days, trades, look and hand-over), the weekly page (W1, a
line under "Leiter") and the progress page's data (U1's `reports/progress/latest.json`: the ladder's rows carry the
promoted steps and "Werkzeug fehlt"; a `promotions` part of the ladder section). The app's page itself is not changed
in A4.

## What it means today

On the lab's data on 2026-10-29 no candidate stands on step 2 (27 on step 0, 22 on step 1), so the first run promotes
nothing and makes no number and no trial.
