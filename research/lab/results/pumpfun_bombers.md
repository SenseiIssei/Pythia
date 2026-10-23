# The bombers (Y13): result (2026-10-23)

Pre-registered in `results/pumpfun_bombers_prereg.md` (committed before the run). Code `lab/pumpfun_rt/bombers13.py`,
tests `tests/test_pumpfun_bombers_y13.py`; `python -m lab.pumpfun_rt.bombers13` writes the full tables to
`reports/pumpfun_rt/bombers13.md`. Paper only.

## The answer

**No, not at our speed and not at 1 s either.** Coins that go 100x from their first trade are common (about 62 a
day), but 84 % of them have their whole curve bought out within 3 s of creation, almost all in the creation slot
(bundles), and are in their pool before any decision of ours. A model sees them very well at 3 or 10 s, because by
then the run has mostly happened. Paper books that buy the model's picks or the owner's whale rule on the curve
lose 21 to 38 % per trade at every latency, 1 s included. Nothing changes for the live bot or any paper book.

## 1. How many, how fast, how much is left

39,566 plain SOL curves with their first 6 h in the record (2.81 days to 2026-10-23 18:00 UTC), multiples of the
curve's price after the first trade:

| within 6 h | coins | per day | share | median time | 75 % reached within | migrated within 3 s |
|---|---|---|---|---|---|---|
| 50x | 266 | 95 | 0.67 % | 23 s | 15.5 min | 205 (77 %) |
| 100x | 174 | 62 | 0.44 % | 30 s | 13.8 min | 146 (84 %) |
| 1000x | 37 | 13 | 0.09 % | 4 s | 25 s | 36 (97 %) |

How much of a 100x coin's run is left (the median multiple already reached, and still ahead to its 6 h peak):

| after creation | 1 s | 3 s | 10 s | 30 s | 60 s |
|---|---|---|---|---|---|
| already reached | 9.7x | 11.4x | 54x | 97x | 106x |
| still ahead | 18.5x | 14.3x | 8.7x | 1.8x | 1.6x |
| 10x or more still ahead | 62 % | 57 % | 48 % | 29 % | 21 % |

At 10 s, close to where our live buys land, half the 100x coins still have 9x ahead, but they are in a pool by
then, not on the curve. Only 28 of the 174 were still on the curve at 10 s (median 24x still ahead), against about
39,500 coins that were not bombers.

## 2. What the first seconds show (out of sample, 25,797 coins in 5 purged blocks)

| at 10 s, 100x within 6 h | AUC | top 0.1 % | top 1 % | base rate |
|---|---|---|---|---|
| LightGBM | 0.989 | 79 % (22 of 28) | 33 % (85 of 261) | 0.42 % |
| logistic | 0.987 | 86 % (24 of 28) | 31 % (81 of 261) | |

By the registered rule both separate the bombers (3 s: AUC 0.984 and 0.980). But the strongest features are the
curve's progress (AUC 0.96 alone: the 100x coins are at 100 % at 10 s, the rest at 5 %), the multiple already
reached (0.87) and a creator with an earlier migration (0.88). The model recognizes a run that has already
happened. Of the G10 book's picks with their 6 h known, 69 % had migrated before the decision (G3 74 %).

Simple flags (at 10 s, share of coins, then how many of them went 100x):

| flag | coins | 100x |
|---|---|---|
| any buy of 1 SOL or more (not the dev) | 41 % | 0.6 % |
| any buy of 3 SOL or more (the W10 rule) | 10 % | 2.3 % |
| any buy of 10 SOL or more | 1.7 % | 13 % |
| 3 or more buyers in the creation slot | 31 % | 0.8 % |
| creator with an earlier migration | 5.7 % | 6.1 % |
| an early buyer who was early in an earlier 50x | 46 % | 0.2 % |

Whales and serial creators raise the odds 5 to 30 times, but mostly on coins already bought out. The early buyers'
history points the wrong way (AUC 0.38): the sniper bots that buy every launch are on the dead coins too.

## 3. Paper books (0.05 SOL, a third at 3x, a third at 10x, the rest on a 50 % trail, -50 % stop, 24 h)

Out of sample (coins created 2026-10-21 12:00 to 2026-10-23 17:00, 2.21 days), every pick on its own:

| signal | latency | entries | mean per trade | 90 % band | P&L SOL | SOL per day | trades on 100x coins | losers per 100x |
|---|---|---|---|---|---|---|---|---|
| G3 (headline) | 1 s | 88 | -31.7 % | -45.1 to -17.0 % | -1.39 | -0.63 | 6 | 4.3 |
| G3 | 3 s | 88 | -35.0 % | -48.4 to -20.6 % | -1.54 | -0.70 | 6 | 3.9 |
| G3 | 10 s | 88 | -38.1 % | -53.0 to -21.7 % | -1.68 | -0.76 | 6 | 3.6 |
| G3 | live | 88 | -37.5 % | -51.2 to -20.8 % | -1.65 | -0.75 | 6 | 3.1 |
| G10 | 1 s / live | 114 | -31.5 % / -30.6 % | both below zero | -1.80 / -1.75 | -0.81 / -0.79 | 7 | 4.6 / 4.1 |
| W10 | 1 s / live | 2,650 | -25.0 % / -21.5 % | both below zero | -33.1 / -28.5 | -15.0 / -12.9 | 14 | 9.1 / 9.1 |
| R (1 coin in 20) | 1 s / live | 1,375 | -14.7 % / -12.6 % | both below zero | -10.1 / -8.7 | -4.6 / -3.9 | 0 | |

- **Expected value** at our stake, headline G3 at the live latency: -0.019 SOL per trade, -0.75 SOL per day (40
  trades a day).
- **One bomber pays for 3 to 4 losers** (a G3 trade on a 100x coin made +0.08 to +0.10 SOL, about +200 % of the
  stake; the others lost 0.026 SOL on average), but there were **about 14 losers per bomber** (6 of 88). With W10
  one pays for 9 but there are about 190 per bomber. The best trade of any book made +735 % of its stake; none
  reached the 10x step's +900 %. By the time we can buy, the run left is short, and the -50 % stop or the trail
  catches the shakeouts along the way.
- **Latency**: no book pays at any of the four, so none of them is fast enough. Most 100x coins are gone from the
  curve within 3 s, so even 1 s is too late. The only place ahead of them is the creation slot itself, held by the
  creator's own bundle (Y3).
- As one bot with the code's caps (5 open, 1.0 SOL a day): G3 identical, G10 -37.5 % at the live latency over 89
  entries (25 skipped for the daily loss limit). W10 and R fill their 5 slots with coins that went quiet, held 24 h
  (15 to 39 entries in 2.2 days, no band).

## What it means

At our speed, and on the curve, catching bombers is buying the run after it happened. The number to watch is not
the latency but where the coin is at the decision: 84 % of the 100x coins are in a pool within 3 s. A pool entry
right after an instant migration is what the live P_pool0_wait already does (and it sells at +30 %). A runner exit
there would be a new, separately registered study, not a conclusion of this one. Too early by the lab's bar: three
days of record, two days out of sample. Trials: 12. The live bot, P_pool0_wait and every paper book trade exactly
as before: no existing module was changed, and 2026-10-20 replayed with the 42 strategies and 22 rules in one
shared paper book before and after this study's commits gives the same 18,599 closed trades, 1,039 failed buys and
104 skip counts, byte for byte.
