# Realistic paper for pump.fun (R1): result (2026-10-24)

Code `lab/pumpfun_rt/realistic.py`, the paper books in `lab/pumpfun_rt/live.py`, the daily job `pumpfun-rt-realistic`.
Paper only; the live bot is unchanged. Reproduce: `python -m lab.pumpfun_rt.realistic run --until 2026-10-24T00:00`.

## The question

Since 2026-10-23 17:31 UTC the paper P_pool0_wait made +78 % per trade over 23 trades while the live bot with the
same strategy lost money. The paper gains were spikes sold within seconds at prices live never got (JIFFPOM +309 %
after 1.5 s on paper, -21 % live). The old paper model lands a buy 0.4 to 3 s after the signal; live buys land a
median 9.8 s after it. What do the pump.fun paper books make when they are executed the way the live bot is?

## The answer

The realistic model roughly **halves the paper gains** of the main strategies: P_pool0 from +11.9 % to +6.4 % per
trade, P_pool0_wait from +10.5 % to +6.5 % (0.1 SOL, the whole record 2026-10-20 16:39 to 2026-10-24 00:00 UTC). It is
the default of every pipeline paper book from now on; the old books run on as `<name>_ideal` until 2026-11-06.

On the live bot's own coins it meets the owner's rule on the median but is **still too optimistic on average**: on
the 21 coins both the live bot and the replay traded, the median P&L difference is +0.1 points (old model -1.5), but
the mean is +17.0 points (old +25.8). The difference sits in three coins the paper bought before a 3x to 4x run that
the live bot bought after: BITCHES (live +31 %, paper +282 %, paper entry 75 % cheaper), YMB (-33 % against +66 %,
entry 70 % cheaper), CHUNGUS. The latency is drawn per trade independently of the coin, while the live bot seems to be
late exactly on the coins that run in their first seconds (a coin made and migrated within a minute: live median 9.0 s
against 6.7 s on older coins, 82 of the live buys; too few to model yet). Those 21 trades are one evening: the model
counts as calibrated only after 7 days of realistic paper (the daily line in `reports/pumpfun_rt/realistic.md`).

With the live bot's sizing as the owner has set it (100 % of the wallet, brake off, floor 0, one position) every book
loses its 0.55 SOL wallet again and again: a positive mean per trade does not survive all-in stakes, a single -80 %
trade takes most of the wallet. P_pool0_wait at 100 %: 496 trades, -3.1 SOL over 6 top-ups, a fall of 57 SOL from its
high on the way. Only the two Y12 floors (P_pool0_wait_lock +5.9 SOL, _lock_half +5.0 SOL, one top-up each) end up.

## The model

| what | realistic (the fit to the cutoff) | old paper model |
|---|---|---|
| buy, signal to landing | the live bot's 97 buys of the last 7 days, empirical quantiles: median 8.8 s, 10 to 90 % 0.7 to 28.5 s | lognormal median 1 s, 0.4 to 3 s |
| sale, decision to landing | the live bot's 95 sales: median 0.6 s, 90 % within 11.8 s | the same as the buy |
| draw | per trade, seeded by (strategy, coin, side, leg): a replay draws the same | the same |
| fill | the pool or curve state of the first recorded trade at or after the landing, that trade included (we are not first in our slot), the stake's own impact | the state at the landing |
| pool buy bound | the quote / 1.60 (live since 2026-10-23), checked at the send (landing less the drawn send time, median 0.6 s): run away is the skip "price ran away", no fee; under the bound at the landing "price ran away on landing" (6040), fee paid | the quote / 1.30 at the landing |
| failures | not landed 1.9 %, simulation failed 0.9 % per buy, as live (6040, 5.7 % live, comes from the bound) | none |
| fees | 0.000215 SOL a transaction (the live median) plus the 0.000005 SOL Sender tip; a failed one pays no tip | 0.001005 SOL |
| stake | the live sizing on a 0.55 SOL paper wallet per book, the owner's share, brake, floor and slots, 0.01 SOL reserve; topped up to 0.55 SOL when it cannot pay a trade | 0.1 SOL |

Under 30 live fills a side, that side takes a fixed fallback (lognormal median 9.8 s for buys, 3.9 s for sales). The
job refits every morning at 06:40 UTC from the last 7 days and writes the calibration line.

## The headline numbers

Ideal: the old model, 0.1 SOL, at most 4 open, daily loss limit 1.0 SOL. Realistic: the realistic fills at the same
stake and limits. Live sizing: realistic with the owner's sizing (limits=wallet, 100 %, brake off, floor 0, at most 1
open) from 0.55 SOL. Means are per closed trade; P&L includes every failed buy's fee. The whole record, trades open
across a gap in the record kept; the Y9 filters on Y9's walk-forward models, so from the second day on. No test here:
the studies' own verdicts (paired bands out of sample) are not re-run.

Record 2026-10-20 to 2026-10-24 (2026-10-20 16:39 to 2026-10-24 00:00 UTC). Fit: buy 8.8 s, sale 0.6 s median, fee 0.000215 + tip 0.000005 SOL; 97 live buys, 95 sales.

| study | strategy | ideal n | ideal mean | ideal P&L SOL | realistic n | realistic mean | realistic P&L SOL | failed or skipped at the buy | live sizing: trades | P&L SOL | top-ups to 0.55 SOL |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Y6 | P_pool0 | 493 | +11.9 % | +5.864 | 509 | +6.4 % | +3.251 | 32 | 424 | -2.171 | 7 |
| Y8 | P_pool0_wait | 553 | +10.5 % | +5.820 | 609 | +6.5 % | +3.986 | 27 | 496 | -3.125 | 6 |
| Y9 | P_pool0_norug | 276 | -1.2 % | -0.335 | 312 | +3.6 % | +1.132 | 21 | 230 | -1.178 | 7 |
| Y9 | P_pool0_top30 | 89 | +3.0 % | +0.268 | 85 | +1.9 % | +0.163 | 4 | 76 | -1.149 | 2 |
| Y9 | P_pool0_norug_top30 | 79 | +3.8 % | +0.297 | 73 | +0.7 % | +0.050 | 6 | 67 | -1.166 | 2 |
| Y9 | P_pool5_top30 | 108 | -2.5 % | -0.270 | 105 | -0.6 % | -0.062 | 3 | 90 | -1.413 | 2 |
| Y9 | P_pool0_smart2 | 100 | -6.0 % | -0.604 | 92 | -5.3 % | -0.484 | 8 | 87 | -1.611 | 3 |
| Y11 | P_pool0_wait_run20 | 550 | +9.4 % | +5.189 | 537 | +7.9 % | +4.231 | 34 | 323 | -3.866 | 9 |
| Y11 | P_pool0_wait_run20w | 522 | +9.3 % | +4.858 | 429 | +6.5 % | +2.804 | 23 | 252 | -4.422 | 9 |
| Y12 | P_pool0_wait_lock | 588 | +10.8 % | +6.355 | 705 | +9.8 % | +6.878 | 40 | 505 | +5.867 | 1 |
| Y12 | P_pool0_wait_lock_tight | 539 | +10.6 % | +5.707 | 648 | +5.5 % | +3.549 | 33 | 509 | -4.391 | 8 |
| Y12 | P_pool0_wait_lock_half | 538 | +10.9 % | +5.843 | 666 | +7.3 % | +4.851 | 37 | 506 | +4.969 | 1 |
| Y15 | P_pool0_wait_free10 | 557 | +10.7 % | +5.940 | 576 | +6.2 % | +3.583 | 34 | 492 | -3.737 | 7 |
| Y15 | P_pool0_wait_free30 | 562 | +10.6 % | +5.938 | 566 | +7.1 % | +4.016 | 31 | 480 | -5.740 | 11 |
| Y15 | P_pool0_wait_free_any | 556 | +8.3 % | +4.597 | 574 | +5.5 % | +3.171 | 42 | 478 | -4.292 | 9 |
| Y15 | P_pool0_wait_free10_tight | 571 | +10.6 % | +6.045 | 581 | +7.8 % | +4.559 | 25 | 484 | -2.062 | 5 |

Calibration on the record (the live bot's P_pool0_wait trades against the paper books on the same coins, 0.1 SOL, no slot or loss limit):

| paper model | matched | entry price, paper over live | exit price | P&L median, points | P&L mean, points | live mean | paper mean |
|---|---|---|---|---|---|---|---|
| realistic | 21 | -1.3 % | +0.2 % | +0.1 | +17.0 | -9.4 % | +7.5 % |
| ideal (old) | 23 | -1.1 % | +0.2 % | -1.5 | +25.8 | -12.8 % | +13.0 % |

## What it means

- The old paper results of the pump.fun studies are about twice too good per trade. The Y9 filters stay at or below
  P_pool0_wait. The variants that sell later or in parts lose less to the realistic fills than P_pool0_wait itself:
  under the old model they were within 0.4 points of it, under the realistic one P_pool0_wait_lock makes +9.8 %,
  P_pool0_wait_run20 +7.9 %, P_pool0_wait_free10_tight +7.8 % against +6.5 %. That is a hint for a re-run of their
  registered evaluations under the realistic model, not a result.
- The realistic model is not calibrated yet: the mean still flatters by about 17 points on the coins where the paper
  lands before a run. The daily line will show whether 7 days of forward data say the same.
- All-in sizing loses the wallet with every strategy here; at the sizing's default 10 % the same P_pool0_wait would
  have grown (a run without the cutoff: +6.8 SOL from 0.55).
