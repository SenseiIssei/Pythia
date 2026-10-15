# Strategy factory (W10): the first real run

`lab.factory` composes long-only daily strategies from the lab's own building
blocks, searches them on the in-sample window only, counts every one as a
trial in a global ledger, sends a few to the held-back window, and lets the
survivors run 30 days as forward shadow books before anything can become a
paper book. Never live. This is its first real run, made on the PC against
the synced survivorship-free panel (591 coin segments, to 2026-10-14) with
the default budget of 300 new genomes:

```bash
PYTHIA_DATA=F:/PythiaData PYTHIA_AGENT_OUT=F:/PythiaData/lab-cache PYTHIA_FACTORY_DIR=F:/PythiaData/agent-models/factory PYTHIA_REPORTS=F:/PythiaData/agent-models/reports F:/PythiaData/venv-net/Scripts/python.exe -m lab.factory --budget 300 --run-id 2026-10-15
```

Its ledger, holdout log and the one shadow book it opened are committed in
`results/factory_seed/` (written by `python -m lab.factory export-seed`), and
every factory run merges that seed first, so these 300 trials count on the
server's first weekly run too and the bar does not start low there.

## What it found

- **The in-sample window flatters everything long-only.** 95 % of the 300
  genomes have a positive in-sample Sharpe at 35 bps (median 1.55, 10th to
  90th percentile 0.53 to 2.25), because 2020-08 to 2023 contains the 2021
  bull market. Random draws median 0.94; bred genomes (mutation 1.98,
  crossover 1.96) climbed quickly into one cluster: a top-20 trend signal
  (MA 10/100, mom 90d or 14d), BTC 28 or 56-day momentum as a gate, a 120 %
  vol cap, best 3 or 5, every 3 days with a 50 % band.
- **That cluster does not survive the held-back window.** The six genomes
  sent there (best fitness, both halves positive, in-sample correlation below
  0.90 with each other) had in-sample Sharpes 2.19 to 2.59; held back from
  2024 at 35 bps they made -0.09 to 0.88 (median 0.19). Five stop: four lose
  money at 70 bps, five draw down more than BTC (54 to 69 % against 53 %).
- **One survivor goes to the forward shadow:** `44444c97ba5e`, the five
  lowest-volatility coins of the 20 most liquid, held only while BTC is above
  its 200-day average and up over 28 days, vol cap 120 %, rebalanced every
  3 days with a 50 % band. Held back: Sharpe 0.98 / 0.88 / 0.69 at 15 / 35 /
  70 bps, 25 % a year, drawdown 35 % (BTC 53 %), 17x turnover a year, 38 %
  invested on average, 0.66 filled a close late; in sample 2.25 (halves 2.89
  and 1.36). It passes every held-back gate but its deflated p is 0.00 over
  677 trials (noise bar Sharpe 2.45), so it cannot be promoted on this
  evidence: the shadow month can only add confirmation, not clear deflation.
  It is the hand studies' low-vol idea (long-only low vol failed in the
  sweep at 0.23 at 41 bps) made to sit out bear markets, the same lesson as
  `vol_managed` and `regime`: the BTC gate does the work.
- **The pool grew from 377 to 677 trials** and the noise bar from Sharpe
  2.43 to 2.45. Every later run adds its budget, so the bar keeps rising.

Verdict: no paper book. One shadow book runs for 30 days as forward evidence.
The factory's report below is exactly what the job wrote.

---

## The factory report, run 2026-10-15

Generated 2026-10-15T10:48:52+00:00 by `python -m lab.factory`. Panel: 591 coin segments, 2020-01-01 to 2026-10-14; in sample 2020-08-01 to 2023-12-31, held back 2024-01-01 to 2026-10-14. Costs per unit of turnover: 15, 35 (judging) and 70 bps.

### Verdict

1 genome(s) pass the held-back gates and start a 30-day forward shadow; none is near promotion until then, and deflation over 677 trials must also pass.

### The bar

Every genome evaluated is a trial in the global ledger. Pool before this run: 377 trials (377 hand-study trials plus 0 factory trials), best noise trial expected at an annual Sharpe of 2.43. After: 677 trials, bar 2.45. Promotion needs deflated p above 0.95 against that pool, positive at 70 bps, drawdown below BTC's, the late-fill and twin checks, and 30 forward shadow days not below the backtest's 5 % quantile.

### What it tried

300 new genomes in 37 s (random 150, mutation 109, crossover 41; 15 proposals were already in the ledger and were not counted again). In-sample Sharpe at 35 bps:

| Signal | Tried | Median IS Sharpe | Best | Positive |
|---|---|---|---|---|
| donchian | 31 | 1.28 | 2.32 | 97 % |
| lowvol | 46 | 1.48 | 2.25 | 100 % |
| ma | 141 | 1.82 | 2.59 | 100 % |
| mom | 54 | 1.19 | 2.59 | 100 % |
| rev | 28 | 0.18 | 1.40 | 54 % |


| Universe | Tried | Median IS Sharpe | Best | Positive |
|---|---|---|---|---|
| alpaca | 64 | 1.25 | 1.96 | 95 % |
| core | 55 | 1.21 | 2.19 | 95 % |
| top 10 | 20 | 0.99 | 1.99 | 90 % |
| top 20 | 125 | 2.03 | 2.59 | 98 % |
| top 30 | 16 | 0.73 | 1.81 | 88 % |
| top 50 | 20 | 1.23 | 2.01 | 90 % |


Best of this run by fitness (in-sample Sharpe at 35 bps, for a fixed list the worse of the list and its point-in-time twin, minus 0.03 per moving part):

| Key | Genome | IS Sharpe | IS twin | Halves | Turnover/yr | Exposure | Parts | Fitness |
|---|---|---|---|---|---|---|---|---|
| b1c6815fba27 | MA 10/100 · top 20 · BTC 56d up · coin > MA50 · vol < 120 % · best 3 by signal · equal full · every 3d band 50 % | 2.59 | n/a | 3.15 / 1.91 | 36.4 | 0.53 | 6 | 2.41 |
| 7f804379764e | mom 90d · top 20 · BTC 56d up · coin > MA50 · vol < 120 % · best 3 by signal · equal full · every 3d band 50 % | 2.59 | n/a | 3.41 / 1.47 | 38.9 | 0.51 | 6 | 2.41 |
| fd2de2239bca | MA 5/100 · top 20 · BTC 56d up · coin > MA50 · vol < 120 % · best 3 by signal · equal full · every 3d band 50 % | 2.58 | n/a | 3.14 / 1.88 | 36.4 | 0.54 | 6 | 2.40 |
| 28c897270cd4 | MA 10/100 · top 20 · BTC 56d up · coin > MA50 · vol < 120 % · best 3 by signal · equal full · every 3d | 2.54 | n/a | 3.13 / 1.81 | 38.5 | 0.53 | 5 | 2.39 |
| 732978289056 | MA 10/100 · top 20 · BTC 56d up · coin > MA50 · vol < 120 % · best 3 by signal · invvol full · every 3d band 50 % | 2.57 | n/a | 3.17 / 1.81 | 35.6 | 0.52 | 7 | 2.36 |
| 0ccca49fa6a1 | MA 10/50 · top 20 · BTC 56d up · coin > MA50 · vol < 120 % · best 3 by signal · equal full · every 3d band 50 % | 2.51 | n/a | 3.17 / 1.68 | 36.0 | 0.53 | 6 | 2.33 |
| bcceb8dce64c | MA 10/50 · top 20 · BTC 56d up · coin > MA50 · vol < 120 % · best 3 by signal · equal full · every 3d | 2.46 | n/a | 3.10 / 1.67 | 38.4 | 0.53 | 5 | 2.31 |
| 1e6745e0d7d4 | MA 10/50 · top 20 · BTC 56d up · coin > MA50 · vol < 120 % · best 3 by signal · equal full · every 3d band 25 % | 2.47 | n/a | 3.10 / 1.70 | 37.1 | 0.54 | 6 | 2.29 |
| 8172eb64f423 | MA 10/100 · top 20 · BTC 56d up · coin > MA200 · vol < 120 % · best 3 by signal · equal full · every 3d band 50 % | 2.47 | n/a | 2.98 / 1.82 | 31.4 | 0.54 | 6 | 2.29 |
| 11fa4bc17742 | MA 10/100 · top 20 · BTC 56d up · coin > MA50 · vol < 120 % · best 5 by signal · equal full · every 3d band 50 % | 2.46 | n/a | 3.06 / 1.71 | 34.7 | 0.54 | 6 | 2.28 |


### Held back: what survived and why

The search sent 6 genomes (best fitness first, both in-sample halves positive, held-back-unseen, in-sample returns correlated below 0.90 with each other) to the held-back window. BTC there: Sharpe 0.74, drawdown 53 %.

| Key | Genome | IS 35 | OOS 15 | OOS 35 | OOS 70 | DD | Late | Twin | Deflated p | Decision |
|---|---|---|---|---|---|---|---|---|---|---|
| b1c6815fba27 | MA 10/100 · top 20 · BTC 56d up · coin > MA50 · vol < 120 % · best 3 by signal · equal full · every 3d band 50 % | 2.59 | 0.43 | 0.27 | -0.01 | 60 % | 0.37 | n/a | 0.00 | stopped |
| 61ff597ab775 | mom 90d · top 20 · BTC 28d up · BTC > MA200 · vol < 120 % · best 5 by signal · equal full · every 3d band 50 % | 2.46 | 0.05 | -0.09 | -0.32 | 61 % | 0.12 | n/a | 0.00 | stopped |
| 2b4d067a386f | mom 14d · top 20 · BTC 56d up · coin > MA50 · vol < 120 % · best 3 by signal · equal full · every 3d band 50 % | 2.38 | 0.90 | 0.69 | 0.31 | 61 % | 0.64 | n/a | 0.00 | stopped |
| 0d83d1a9ffa0 | MA 10/200 · top 20 · BTC 56d up · vol < 120 % · best 3 by signal · equal full · every 3d band 50 % | 2.35 | 0.24 | 0.11 | -0.11 | 69 % | 0.21 | n/a | 0.00 | stopped |
| 44444c97ba5e | low vol · top 20 · BTC 28d up · BTC > MA200 · vol < 120 % · best 5 by signal · equal full · every 3d band 50 % | 2.25 | 0.98 | 0.88 | 0.69 | 35 % | 0.66 | n/a | 0.00 | shadow |
| 0253ecdfc5d0 | mom 90d · core 20 · BTC 28d up · BTC > MA200 · vol < 120 % · best 5 by signal · equal full · every 3d band 50 % | 2.19 | 0.22 | 0.09 | -0.14 | 54 % | 0.23 | 0.13 | 0.00 | stopped |


Why each one stopped where it did:

- `b1c6815fba27` stopped: 70 bps fails (-0.01 at 70 bps); DD < BTC fails (drawdown 60 % vs BTC 53 %)
- `61ff597ab775` stopped: OOS > 0 fails (held-back Sharpe -0.09 at 35 bps); 70 bps fails (-0.32 at 70 bps); DD < BTC fails (drawdown 61 % vs BTC 53 %)
- `2b4d067a386f` stopped: DD < BTC fails (drawdown 61 % vs BTC 53 %)
- `0d83d1a9ffa0` stopped: 70 bps fails (-0.11 at 70 bps); DD < BTC fails (drawdown 69 % vs BTC 53 %)
- `44444c97ba5e` shadow: passes every held-back gate; deflated p 0.00 (needs 0.95 by the end of its forward month)
- `0253ecdfc5d0` stopped: 70 bps fails (-0.14 at 70 bps); DD < BTC fails (drawdown 54 % vs BTC 53 %)

### Forward shadow books

| Key | Genome | Entered | Status | Days | Forward | Band 5 % | Note |
|---|---|---|---|---|---|---|---|
| 44444c97ba5e | low vol · top 20 · BTC 28d up · BTC > MA200 · vol < 120 % · best 5 by signal · equal full · every 3d band 50 % | 2026-10-14 | active | 0 | 0 % | n/a |  |


### Promoted paper books

None. A promoted genome becomes a paper book run by `lab.paper.families` with live quotes; nothing the factory does can reach live trading.


### How to read this

- Fitness is in-sample only. The held-back window is the hand studies' own; the factory checks a handful of genomes there per run, so it is being used again and again. That is why every trial counts in the pool and why nothing is promoted without a month of forward shadow trading.
- Core and Alpaca lists are today's survivors; their twins (the most liquid coins at the start of each year) must hold up too.
- Shadow books fill at the decision close plus 35 bps, as the backtest does. A promoted book trades live quotes on paper and is judged again by the forward report.
