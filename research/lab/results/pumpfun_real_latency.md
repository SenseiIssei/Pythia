# pump.fun rules at the measured latency (Y5)

PAPER ONLY. Nothing here holds a wallet, reads a key, signs or sends
anything; the live service, its executor and its confirmation file were not
touched. The live test's files were only read.

Pre-registration: `results/pumpfun_real_latency_prereg.md` (140 trials,
committed before the first replay). Code: `lab/pumpfun_rt/reallat.py`;
tests: `tests/test_pumpfun_real_latency.py`. Data: the server's record,
2026-10-20 16:40 to 2026-10-22 21:00 UTC (the registered cutoff), split at
2026-10-21 18:49 UTC; out of sample is the 26 hours after the split. The
in-sample pick was `E_d0_x2`, so the model-filter book is `E_d0_x2+model`.

## Short answer

**No rule and no pipeline strategy is positive at the latency we measured,
and none is positive at the study's latency or with a 1.5 s send path
either.** Every one of the 35 books loses out of sample in all four
scenarios at 0.03 SOL. The least bad are the post-migration pool buys
(`E_d0_x1`, `E_d0_x2`): -4.6 % per trade at today's latency, -1.7 to -2.5 %
with a fast send path, bands that touch zero only from below. `P_cmig_model`
loses about 11 % per trade at every speed: its problem is not latency.

## 1. The latency model

The measured latencies (4 buys, 3 sales, as registered) as a kernel density
in log space, Silverman bandwidth on the logs (buys 0.37, sales at the 0.25
floor), clipped to 1 to 60 s; quantiles over 20,000 synthetic keys:

| scenario | buy, median (10 to 90 %) | sale, median (10 to 90 %) | fee per transaction |
|---|---|---|---|
| (a) the study's assumption | 1.0 s (0.5 to 1.9) | 1.0 s (0.5 to 1.9) | 0.001005 SOL |
| (b) measured | 5.9 s (2.1 to 11.8) | 11.6 s (6.1 to 19.8) | 0.001005 SOL |
| (c) 1.5 s send path | 1.5 s (1.2 to 1.9) | 1.5 s (1.2 to 1.9) | 0.001005 SOL |
| (c) + tip | as (c) | as (c) | 0.001010 SOL |

Measured, for comparison: buys median 6.6 s (10 to 90 %: 3.1 to 8.7 s),
sales 6.9 to 17.2 s. The model keeps the measured median and is wider in
both tails on purpose.

Check on the slippage: the replay of `P_cmig_model` at (b) has a median buy
slippage of +1.3 % against the signal price, the live test measured +1.3 %.

Disclosed after the run: since the pre-registration the live executor logged
one more buy (27.0 s from signal to landing) and one more sale (26.7 s), and
its ledger now has seven closed trades, all losses (mean -23.2 % per trade).
Both new fills are slower than anything in (b), so (b) is, if anything, too
kind. The registered model was not changed (a refit would be a new trial).

## 2. Every book, out of sample

Entries are closed trades plus failed buys (a failed buy is a trade that
lost its 0.001005 SOL fee, -3.4 % of the stake). Stake 0.03 SOL. Band: the
hour-block bootstrap 90 % band of the mean (n/a under 10 hours with trades).
Sorted by the mean at (b).

| rule | entries (b) | mean (a) | mean (b) | mean (c) | mean (c+tip) | median (b) | win (b) | P&L (b), SOL | band of mean (b) |
|---|---|---|---|---|---|---|---|---|---|
| E_d0_x2 | 292 | -3.5 % | -4.6 % | -2.5 % | -2.6 % | -3.4 % | 12 % | -0.400 | -9.5 % to +0.4 % |
| E_d0_x2+model | 292 | -3.5 % | -4.6 % | -2.5 % | -2.6 % | -3.4 % | 12 % | -0.400 | -9.5 % to +0.4 % |
| E_d0_x1 | 341 | -1.7 % | -4.6 % | -1.7 % | -1.7 % | -3.4 % | 19 % | -0.467 | -6.5 % to -2.5 % |
| P_mom_model | 4 | -4.2 % | -5.0 % | -4.2 % | -4.2 % | -17.3 % | 25 % | -0.006 | n/a |
| D_p80_x1 | 648 | -8.9 % | -8.6 % | -8.5 % | -8.6 % | -3.4 % | 14 % | -1.675 | -10.9 % to -6.5 % |
| P_pool60_hz | 304 | -8.6 % | -8.9 % | -8.9 % | -9.0 % | -8.6 % | 10 % | -0.811 | -11.0 % to -6.7 % |
| A_cmig_x1 | 520 | -6.3 % | -9.7 % | -6.8 % | -6.9 % | -9.4 % | 13 % | -1.513 | -11.5 % to -7.9 % |
| A_all_x1 | 12245 | -9.7 % | -10.4 % | -9.8 % | -9.8 % | -9.4 % | 7 % | -38.229 | -10.8 % to -10.1 % |
| D_p90_x1 | 492 | -10.4 % | -10.7 % | -10.6 % | -10.6 % | -3.4 % | 12 % | -1.577 | -13.0 % to -8.4 % |
| **P_cmig_model** | 200 | -10.7 % | -11.1 % | -10.8 % | -10.8 % | -11.8 % | 17 % | -0.667 | -16.6 % to -5.1 % |
| D_p80_x2 | 593 | -10.8 % | -11.2 % | -10.8 % | -10.9 % | -3.4 % | 9 % | -2.000 | -13.7 % to -8.9 % |
| A_all_x2 | 10138 | -11.3 % | -11.2 % | -11.3 % | -11.3 % | -9.4 % | 7 % | -34.185 | -12.5 % to -9.6 % |
| A_dev_x1 | 5719 | -10.4 % | -11.6 % | -10.5 % | -10.5 % | -9.4 % | 11 % | -19.886 | -12.2 % to -11.0 % |
| A_cmig_x2 | 448 | -9.8 % | -11.7 % | -9.8 % | -9.8 % | -11.5 % | 11 % | -1.571 | -14.1 % to -9.2 % |
| P_press10_hz | 235 | -10.2 % | -12.0 % | -10.2 % | -10.2 % | -11.1 % | 13 % | -0.845 | n/a |
| C_20in60_x1 | 617 | -12.9 % | -12.7 % | -12.9 % | -13.0 % | -18.0 % | 19 % | -2.346 | -15.6 % to -9.8 % |
| P_early30 | 14 | -9.2 % | -12.8 % | -8.5 % | -8.6 % | -9.3 % | 7 % | -0.054 | n/a |
| A_dev_x2 | 4733 | -12.9 % | -13.0 % | -12.9 % | -13.0 % | -14.7 % | 10 % | -18.525 | -15.5 % to -9.6 % |
| D_p90_x2 | 456 | -14.0 % | -13.2 % | -14.1 % | -14.1 % | -3.4 % | 8 % | -1.801 | -16.5 % to -10.0 % |
| B_w3_x1 | 2165 | -12.9 % | -13.3 % | -13.0 % | -13.0 % | -13.3 % | 16 % | -8.668 | -15.1 % to -11.5 % |
| P_snipe_cmig | 201 | -8.2 % | -13.7 % | -8.3 % | -8.3 % | -11.5 % | 11 % | -0.827 | n/a |
| P_snipe_dev | 192 | -10.4 % | -14.0 % | -10.3 % | -10.5 % | -9.4 % | 8 % | -0.805 | n/a |
| E_d60_x1 | 207 | -13.8 % | -14.1 % | -14.0 % | -14.1 % | -6.4 % | 41 % | -0.874 | -18.9 % to -9.3 % |
| B_w10_x1 | 833 | -13.4 % | -14.2 % | -13.3 % | -13.3 % | -12.5 % | 18 % | -3.538 | -16.1 % to -12.4 % |
| P_press10 | 201 | -12.0 % | -14.3 % | -12.6 % | -12.6 % | -14.2 % | 19 % | -0.863 | n/a |
| C_50in300_x1 | 175 | -15.5 % | -16.3 % | -15.8 % | -15.9 % | -15.9 % | 21 % | -0.855 | -20.6 % to -11.5 % |
| B_w10_x2 | 649 | -18.5 % | -16.4 % | -17.8 % | -17.9 % | -22.6 % | 19 % | -3.194 | -20.0 % to -12.7 % |
| B_w3_x2 | 1712 | -18.3 % | -18.0 % | -18.3 % | -18.3 % | -24.2 % | 14 % | -9.252 | -20.2 % to -16.0 % |
| P_pool60 | 71 | -22.1 % | -18.6 % | -21.0 % | -21.1 % | -20.4 % | 32 % | -0.396 | -25.4 % to -11.1 % |
| C_20in60_x2 | 442 | -18.3 % | -18.9 % | -18.7 % | -18.8 % | -40.2 % | 12 % | -2.508 | -23.3 % to -15.0 % |
| P_p90 | 135 | -16.5 % | -20.4 % | -16.9 % | -16.9 % | -10.0 % | 16 % | -0.827 | -24.8 % to -16.2 % |
| P_p80_smart | 59 | -14.9 % | -20.8 % | -15.1 % | -15.1 % | -3.4 % | 14 % | -0.368 | -26.0 % to -15.2 % |
| E_d60_x2 | 131 | -28.5 % | -27.1 % | -28.9 % | -29.0 % | -53.9 % | 26 % | -1.067 | -39.4 % to -15.8 % |
| C_50in300_x2 | 123 | -26.8 % | -28.5 % | -27.0 % | -27.0 % | -43.2 % | 8 % | -1.053 | -34.4 % to -22.9 % |
| P_early10 | 3 | -9.2 % | -39.9 % | -30.0 % | -30.1 % | -18.9 % | 0 % | -0.036 | n/a |

The best five per scenario (30 or more entries) with `P_cmig_model` below
them; z is the mean over the band's width / 3.29:

| scenario | rule | entries | failed | mean | median | win | P&L SOL | band of mean | z |
|---|---|---|---|---|---|---|---|---|---|
| (a) | E_d0_x1 | 353 | 212 | -1.7 % | -3.4 % | 20 % | -0.175 | -4.3 % to +0.8 % | -1.07 |
| (a) | E_d0_x2 (and +model) | 303 | 214 | -3.5 % | -3.4 % | 10 % | -0.316 | -6.8 % to +0.1 % | -1.67 |
| (a) | A_cmig_x1 | 546 | 28 | -6.3 % | -9.4 % | 21 % | -1.030 | -8.0 % to -4.4 % | -5.69 |
| (a) | P_snipe_cmig | 351 | 6 | -8.2 % | -11.5 % | 20 % | -0.867 | -11.1 % to -5.3 % | -4.68 |
| (a) | P_cmig_model | 214 | 5 | -10.7 % | -14.8 % | 20 % | -0.685 | -15.7 % to -5.8 % | -3.55 |
| (b) | E_d0_x2 (and +model) | 292 | 200 | -4.6 % | -3.4 % | 12 % | -0.400 | -9.5 % to +0.4 % | -1.53 |
| (b) | E_d0_x1 | 341 | 197 | -4.6 % | -3.4 % | 19 % | -0.467 | -6.5 % to -2.5 % | -3.80 |
| (b) | D_p80_x1 | 648 | 395 | -8.6 % | -3.4 % | 14 % | -1.675 | -10.9 % to -6.5 % | -6.51 |
| (b) | P_pool60_hz | 304 | 6 | -8.9 % | -8.6 % | 10 % | -0.811 | -11.0 % to -6.7 % | -6.82 |
| (b) | P_cmig_model | 200 | 21 | -11.1 % | -11.8 % | 17 % | -0.667 | -16.6 % to -5.1 % | -3.17 |
| (c) | E_d0_x1 | 352 | 212 | -1.7 % | -3.4 % | 20 % | -0.179 | -4.4 % to +0.9 % | -1.05 |
| (c) | E_d0_x2 (and +model) | 303 | 212 | -2.5 % | -3.4 % | 11 % | -0.230 | -5.9 % to +1.1 % | -1.19 |
| (c) | A_cmig_x1 | 549 | 28 | -6.8 % | -9.4 % | 21 % | -1.127 | -8.6 % to -4.9 % | -6.19 |
| (c) | P_snipe_cmig | 338 | 9 | -8.3 % | -11.5 % | 20 % | -0.839 | -11.0 % to -5.3 % | -4.76 |
| (c) | P_cmig_model | 213 | 6 | -10.8 % | -14.9 % | 19 % | -0.688 | -15.8 % to -5.8 % | -3.52 |
| (c+tip) | E_d0_x1 | 352 | 212 | -1.7 % | -3.4 % | 20 % | -0.181 | -4.4 % to +0.9 % | -1.07 |
| (c+tip) | E_d0_x2 (and +model) | 303 | 212 | -2.6 % | -3.4 % | 11 % | -0.232 | -5.9 % to +1.0 % | -1.20 |
| (c+tip) | A_cmig_x1 | 549 | 28 | -6.9 % | -9.4 % | 21 % | -1.132 | -8.6 % to -5.0 % | -6.22 |
| (c+tip) | P_snipe_cmig | 338 | 9 | -8.3 % | -11.5 % | 20 % | -0.841 | -11.1 % to -5.3 % | -4.74 |
| (c+tip) | P_cmig_model | 213 | 6 | -10.8 % | -15.0 % | 19 % | -0.690 | -15.9 % to -5.8 % | -3.53 |

**Deflation.** The study's deflated p needs 5 out-of-sample days; the record
has 2, so it is n/a for every book. The registered stand-in (hour-block z
above the one-sided Bonferroni bar over the pool of 1,871 trials, z > 4.04)
is not passed by anything: no book has a positive z at all. Positive at a
scenario (mean above zero, band above zero, deflation passed, 30+ entries):
**none, in any scenario.**

Why the pool buys look least bad: 58 to 71 % of their entries are buys that
failed (no pool state seen yet when the order landed, right at migration)
and cost only the fee, -3.4 %. For `E_d0_x1` the trades that did fill are
about +1 % per trade at (a) and (c) and about -6 % at (b), for `E_d0_x2`
about -4 % at (a) (derived from the means and the failure counts). They are
not an edge in waiting.

## 3. P_cmig_model

At (b), today's latency: 200 entries, mean -11.1 % per trade, median
-11.8 %, 17 % winners, -0.667 SOL, band -16.6 % to -5.1 %. At (a) -10.7 %,
at (c) -10.8 %. Its exits are mostly the dev selling (56) and liquidity
pulls (103): the creator or a holder dumps within seconds of our landing at
any speed, so speed hardly moves it (c minus b: +0.3 points, band -3.4 to
+3.7). The live test lost more (-23.2 % over seven trades), within the
noise of seven trades and with two of them hurt by the executor (a sale the
stream missed, a buy that landed after it was given up). Of the seven live
tokens the replay's book signalled only two (its in-sample models are not
the live book's daily models); one of them it lost 32.5 % on at (b) where
the live trade lost 34.7 %.

**Better than P_cmig_model at (b)?** By the registered rule (30+ entries,
higher mean, band of the difference above zero) one rule qualifies:
`E_d0_x1`, -4.6 % against -11.1 %, difference +6.5 points (band +0.2 to
+12.8). That means it loses less, not that it makes money: its own band is
-6.5 % to -2.5 %. `E_d0_x2` and its model filter have the same mean but a
band of the difference that crosses zero. Nothing was changed; the live
book and its confirmation file are the owner's decision.

## 4. What a 1.5 s send path is worth

Mean (c) minus mean (b), the hour-block band of the difference:

| rule | (b) | (c) | c minus b | band |
|---|---|---|---|---|
| P_p80_smart | -20.8 % | -15.1 % | +5.7 % | +1.5 % to +10.1 % |
| P_snipe_cmig | -13.7 % | -8.3 % | +5.4 % | +1.1 % to +10.7 % |
| P_snipe_dev | -14.0 % | -10.3 % | +3.7 % | +3.4 % to +9.0 % |
| P_p90 | -20.4 % | -16.9 % | +3.6 % | +1.2 % to +5.8 % |
| E_d0_x1 | -4.6 % | -1.7 % | +2.9 % | +1.1 % to +4.7 % |
| A_cmig_x1 | -9.7 % | -6.8 % | +2.9 % | +1.1 % to +4.7 % |
| E_d0_x2 | -4.6 % | -2.5 % | +2.0 % | -1.2 % to +5.5 % |
| A_dev_x1 | -11.6 % | -10.5 % | +1.1 % | +0.6 % to +1.6 % |
| A_all_x1 | -10.4 % | -9.8 % | +0.6 % | +0.4 % to +0.9 % |
| P_cmig_model | -11.1 % | -10.8 % | +0.3 % | -3.4 % to +3.7 % |

The rest move by -2.4 to +1.9 points with bands across zero (leaving out
`P_early10` and `P_early30`, 3 and 14 entries). A fast send
path is worth 0 to 6 points per trade, mostly to the snipes and late-curve
books that hit a dump between signal and landing, and it turns nothing
positive. In SOL it is smaller still, because the pipeline books (5 open at
most) enter more often when they are faster: `P_snipe_cmig` loses 0.827 SOL
at (b) over 201 entries and 0.839 SOL at (c) over 338. Summed over all 35
books the P&L is -162.1 SOL at (b) and -166.8 SOL at (c).

The 0.000005 SOL tip costs 0.03 points per round trip at 0.03 SOL; it is
noise next to everything else.

The fixed costs at this stake matter more than the speed: two transactions
at 0.001005 SOL are 6.7 % of a 0.03 SOL stake before the 1.25 % curve fee a
side and any price impact. A rule needs about 9 % gross per round trip just
to break even at 0.03 SOL; at the study's 0.1 SOL it needed about 4.5 %.

## Verdict

- No rule is positive at today's latency. The best (`E_d0_x1`, `E_d0_x2`)
  lose 4.6 % per trade, the live rule `P_cmig_model` 11.1 %.
- A 1.5 s send path improves the means by 0 to 6 points and the best rule
  to -1.7 %; still nothing is positive, and a tip of 0.000005 SOL changes
  nothing.
- `P_cmig_model` loses about 11 % per trade at every speed; its losses come
  from dumps right after entry, not from our latency. `E_d0_x1` is better by
  the registered rule but still loses money.
- Too early by the lab's bar (two out-of-sample days, the deflation cannot
  be computed); but no book is even close: none has a positive mean.
