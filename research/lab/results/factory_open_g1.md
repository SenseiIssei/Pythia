# G1: the strategy factory invents its own building blocks

Code `lab/factory/grammar.py` (trees), `build.py` (`tree_values`), `search.py` (the budget share), `evaluate.py`
(the penalty), `small.py` (the same trees in F2), `run.py` and `writeup.py` (the report); tests
`tests/test_factory_trees.py`. No language model anywhere. Paper only: nothing here reaches the engine, a live
setting or a wallet.

What it is: besides the fixed families (momentum, Donchian, MA cross, reversal, low vol and their filters) a
genome's signal, a coin filter or a gate may now be a small expression tree the factory invents. Series: close,
volume, range ((high - low) / close), annualised vol and BTC's close. Operators: return over n, moving average
ratio and z-score over n (n from 3, 5, 10, 20, 50, 100, 200), cross-sectional rank within the universe, sign,
clip, difference, ratio, min and max. A tree has at most 3 operator levels and at most 9 nodes. Close, volume and
BTC only appear inside a window operator, and a gate is made of BTC alone. A canonical form (min and max sorted,
rank(rank x) and sign(sign x) once, nested clips merged, a condition z_n(x) > 0 written as ma_n(x) > 0) makes equal
trees one key and so one trial. A tree counts its nodes as moving parts and costs 0.05 of fitness a node (0.03 like
any part plus 0.02, because an invented block needs more evidence than a hand-made one). Every operator reads only
bars up to the one it scores: the test replaces every bar after t (prices, volume, range, vol, BTC, the universes)
with noise and checks, for 360 random trees and 60 tree genomes, that no score or weight at or before t moves. 30 %
of each run's budget goes to tree genomes (`PYTHIA_FACTORY_TREE_SHARE` or `--tree-share`, weekly and small mode
alike), the rest to the families; each kind breeds from its own elite. Genomes without a tree keep their keys, so
the 900 old rows of the server's ledger stay the same trials, and the bar counts every row, trees included.
Rotation is unchanged: survivors become 30-day shadow books within the existing limits (6 at a time, 2 new a run)
and are promoted only through the hand studies' bar.

## The run

2026-10-26 in the agent container, on a copy of the server's factory folder (900 trials) and the current panel
(598 segments, Binance's daily bars before 2020 in front, to 2026-10-25), the normal budget of 300, run id
`g1-2026-10-26`. In sample 2018-01-01 to 2023-12-31 (the window since D1, so no older row was bred from), held back
2024-01-01 to 2026-10-25. 72 s for the search, peak memory 1.5 GB.

- Trials: 300 new genomes (150 random, 108 mutation, 42 crossover; 9 proposals already tried and not counted
  again), of them 90 with a tree (42 as the signal, 12 as a coin filter, 43 as a gate; median 3 nodes, at most 9).
- The pool: 1,277 trials before (377 hand-study plus 900 factory), 1,577 after; the noise bar rises from an annual
  Sharpe of 2.63 to 2.68.
- In sample at 35 bps the trees do worse than the families: median Sharpe 1.01 against 1.14, best 1.76 against
  2.11; after the penalty the best tree's fitness is 1.16, the best family's 1.62. 91 % of the trees and 92 % of
  the families are positive in sample, which says more about 2018 to 2023 than about either.
- Best tree in sample: `MA 50/100 where btc > ma_100` (MA 50/100 on the top 10, BTC up over 28 days, the whole book
  in cash unless BTC is above its 100-day average, best 10, inverse vol, weekly), in-sample Sharpe 1.38 (halves
  0.96 / 1.73), fitness 1.16. The tree here only re-invents the hand-made BTC gate at a window the families do not
  offer (100 days); the next six trees are the same gate on other books.
- Best tree as a signal: `rank(z_3(volume))` (the 10 coins of the top 20 whose volume is most unusual against its
  last 3 days, each above its 50-day average and under 120 % vol, inverse vol, weekly, band 25 %), in-sample 1.27.

## Held back

The search sent its usual six to the held-back window, all families, because no tree was among the best by
fitness. BTC there: Sharpe 0.72, drawdown 53 %.

| Key | Genome | IS 35 | OOS 35 | OOS 70 | DD | Late | Twin | Deflated p | Decision |
|---|---|---|---|---|---|---|---|---|---|
| `ff867ca2cd9a` | MA 10/50 · Alpaca 15 · BTC 28d up · BTC > MA100 · best 5 by signal · equal slots · daily band 50 % | 2.09 | 0.50 | 0.27 | 56 % | 0.53 | 0.52 | 0.000 | stopped (drawdown) |
| `38fcdd4789c0` | MA 20/50 · core 20 · BTC 28d up · BTC > MA100 · best 3 by lowvol · equal slots · daily band 50 % | 1.69 | 0.47 | 0.09 | 33 % | 0.49 | 0.64 | 0.000 | passes the shadow gates |
| `572b02511ff7` | MA 20/50 · top 20 · BTC 28d up · BTC > MA100 · coin > MA200 · best 3 by lowvol · equal slots · daily band 50 % | 1.71 | 0.26 | -0.13 | 49 % | 0.60 | | 0.000 | stopped (70 bps) |
| `c72712431dc7` | MA 10/50 · top 10 · BTC 28d up · BTC > MA100 · coin > MA200 · best 5 by lowvol · equal slots · daily band 50 % | 1.70 | 0.65 | 0.34 | 36 % | 0.64 | | 0.000 | passes the shadow gates |
| `19304de6ab44` | MA 20/200 · core 20 · BTC 28d up · BTC > MA100 · best 3 by lowvol · equal slots · daily band 50 % | 1.61 | 0.74 | 0.43 | 33 % | 0.74 | 1.35 | 0.000 | duplicate of `38fcdd4789c0` |
| `6ed390590d0f` | MA 10/50 · Alpaca 15 · BTC 28d up · BTC > MA100 · best 5 by signal · equal full · weekly | 1.79 | 0.56 | 0.43 | 59 % | 0.71 | 0.35 | 0.000 | stopped (drawdown) |

For this write-up the two best trees were also checked held back. Both checks are in the held-back log, so the
server does not send them there again:

| Key | Expression | IS 35 | OOS 35 | OOS 70 | DD | Late | Deflated p | Gates |
|---|---|---|---|---|---|---|---|---|
| `819cd2b77872` | `MA 50/100 where btc > ma_100` | 1.38 | 0.67 | 0.52 | 43 % | 0.47 | 0.000 | all six pass |
| `38c0885daa3c` | `rank(z_3(volume))` | 1.27 | 1.02 | 0.83 | 22 % | 0.70 | 0.002 | all six pass |

## Verdict

Nothing passes the bar. Deflated p is 0.00 for every genome checked against 1,577 trials (it needs 0.95). The
best in-sample Sharpes (1.4 to 2.1) sit far below the noise bar of 2.68, and held back they fall to 0.3 to 1.0. The invented volume score `rank(z_3(volume))` is the most interesting thing the run found: held back it makes
1.02 at 35 bps and 0.83 at 70 with a drawdown of 22 % against BTC's 53 %. But it was picked as the best of 42 tree
signals and looked at once, so it is a lead for a hand study, not evidence. The trees cost 90 of the run's 300
trials and raise the bar for everything after them; that is the price of an open menu, and it is paid in the open.

Two families pass the shadow gates (`38fcdd4789c0`, `c72712431dc7`, both gated MA crosses ranked by low vol). In
this container they started as shadows on the scratch copy only. Their held-back lines are left out of
`results/factory_seed/`, so the server's next weekly run (2026-11-01) checks them again (the same numbers, not new
trials) and starts their shadow books there, within its limits. The run's 300 trials and its other eight held-back
lines are in the seed, which every run merges first, so they count on the server. Three of the 300 rows were
written before the z/ma rule; they keep their keys and stay trials (one is a gate already tried in its ma form,
counted twice, which only raises the bar).

The small-account mode (F2) has the same trees from tonight's job on; it was only run on synthetic prices here.
