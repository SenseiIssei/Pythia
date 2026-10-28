# T9: the allocator weighted by posterior: result (2026-10-28)

Pre-registration: `results/allocator_t9_prereg.md` (committed before the first run). Code: `lab/pumpfun_rt/allocator.py`
(the daily allocator, now weighted), `lab/pumpfun_rt/allocator_t9.py` (the study); tests `tests/test_allocator_t9.py`.
Paper only; no paper book, the live bot or a wallet changes. Reproduce: `python -m lab.pumpfun_rt.allocator_t9 run
--out DIR` (the replay takes about 25 minutes, 4.6 GB; `--replay FILE` reads a saved one).

## Short answer

- **The allocator now splits the paper wallet by each strategy's posterior probability of being best** (floor 5 %,
  drawdown guard 30 %, as in A1) instead of one random draw a day; every arm runs as paper, so every reward is seen
  anyway. P(best) is exact (quadrature over the posteriors' Student t marginals): two arms with the same entries get
  the same weight, a clearly better arm more (tests).
- **Shared entries: counted once, 1 over k.** An entry (a mint on a UTC day) held by k arms counts 1 / k in each
  arm's posterior; P_pool0_wait and its lock share every entry, so each counts half of its days. The correlation is
  not modelled; the posteriors stay independent.
- **Replay** (R2's realistic replay to 2026-10-28 at the live latency, 6 test days 2026-10-22 to 27): weighted
  +296 % in log growth at 10 % a trade (band +53 to +555 %), A1's draw +223 % (+52 to +438 %; over 1,000 other
  seeds +237 %, +85 to +400 %), equal thirds +262 %, the best single arm in hindsight P_pool0_wait_lock +381 %.
  Weighted less drawn +73 points (band -86 to +317, DSR 0.61); weighted less equal +35 points (band +1 to +71, DSR
  0.92). On the paper books (3 days): weighted +217 %, drawn +129 %, equal +192 %.
- **Weighted beats drawn: no**, in both histories: 6 and 3 days where the registered rule needs 10, the band of the
  difference spans 0 and the DSR is under 0.95. The weighted split is ahead of the draw in total in both histories (behind
  it on 3 of the 6 replay days); it is the daily allocator from now on because it removes a coin flip, not because it is proven.
- **R5's convention**: A1's "deflated p 0.97" was 1 - DSR. It is DSR 0.03 (higher is better, pass at 0.95), now so
  in A1's report and `results/pumpfun_adaptive_a1.md` (the selector table's column too: 0.000 on every label).

Notes. The replay's first four days repeat A1's test days; 2026-10-25 differs a little (+33.9 % for P_pool0_wait
against A1's +32.4 %) because R1's fill model is refitted to the live orders of the 7 days to the new cutoff. The
weighted split's day is log(sum w exp(reward)), the growth of a wallet whose parts trade their arm; A1's "+112 %
weighted" summed w x reward over its 4 days and is not the same number.

Trials: 4 (`hand:t9:<history>:weighted_vs_<drawn|equal>`, counted only). The registry lines were written to a copy
in the agent run; the server's registry gets them when the study runs there (the ids are fixed, a rerun is a no-op).
DSR over the pool of all 2,527 trials (bar 2.75 a year) and over the study's 4 comparisons.

## The run
Run 2026-10-28. Pre-registration `results/allocator_t9_prereg.md`. Reward: the day's log growth of a wallet at 10 % a trade; weighted splits the wallet by the posterior weights (an entry shared by k strategies counted 1 / k in each), drawn is A1's one draw a day, equal splits it in thirds. Bands 90 % over resampled days. DSR in R5's convention (higher is better, pass at 0.95), over the registry's pool of all (2,527 trials, bar 2.75 a year) and over this study's 4 comparisons.

### replay (6 days, 2026-10-22 to 2026-10-27)

| day | P_pool0_wait | P_pool0_wait_lock | P_pool5_top30t | weights (0_wait, 0_wait_lock, 5_top30t) | weighted | drawn (pick) | equal |
|---|---|---|---|---|---|---|---|
| 2026-10-22 | -39.6 % | +50.0 % | +44.0 % | 33 / 33 / 33 | +25.6 % | +50.0 % (P_pool0_wait_lock) | +25.6 % |
| 2026-10-23 | -93.9 % | -12.7 % | +5.7 % | 0 / 52 / 48 | -3.4 % | +5.7 % (P_pool5_top30t) | -25.3 % |
| 2026-10-24 | +116.4 % | +204.9 % | +28.6 % | 0 / 48 / 52 | +148.6 % | +28.6 % (P_pool5_top30t) | +141.1 % |
| 2026-10-25 | +33.9 % | -8.4 % | -33.2 % | 21 / 54 / 25 | -2.9 % | -8.4 % (P_pool0_wait_lock) | +1.3 % |
| 2026-10-26 | +127.8 % | +137.2 % | +23.3 % | 26 / 52 / 23 | +117.6 % | +137.2 % (P_pool0_wait_lock) | +107.5 % |
| 2026-10-27 | +11.2 % | +10.3 % | +13.6 % | 30 / 54 / 16 | +11.1 % | +10.3 % (P_pool0_wait_lock) | +11.7 % |

| policy | total log growth | band |
|---|---|---|
| weighted | +296.5 % | +52.5 % to +555.0 % |
| drawn | +223.2 % | +52.4 % to +437.7 % |
| equal | +261.9 % | +27.5 % to +514.8 % |
| drawn, other seeds | +236.6 % (mean) | +85.1 % to +399.6 % |

Arms alone: P_pool0_wait +155.7 %, P_pool0_wait_lock +381.3 %, P_pool5_top30t +81.9 %.

| weighted less | total | band | daily Sharpe | DSR (pool of all) | DSR (study) |
|---|---|---|---|---|---|
| drawn | +73.2 % | -86.3 % to +316.8 % | +0.23 | 0.613 | 0.431 |
| equal | +34.6 % | +1.0 % to +71.3 % | +0.61 | 0.921 | 0.793 |

Weighted beats drawn: **no** (enough days: no, 6 of 10).

### paper (3 days, 2026-10-25 to 2026-10-27)

| day | P_pool0_wait | P_pool0_wait_lock | P_pool5_top30t | weights (0_wait, 0_wait_lock, 5_top30t) | weighted | drawn (pick) | equal |
|---|---|---|---|---|---|---|---|
| 2026-10-25 | +170.3 % | +49.7 % | +15.8 % | 33 / 33 / 33 | +101.8 % | +15.8 % (P_pool5_top30t) | +101.8 % |
| 2026-10-26 | +42.9 % | +57.9 % | -43.0 % | 54 / 26 / 20 | +35.0 % | +42.9 % (P_pool0_wait) | +28.0 % |
| 2026-10-27 | +70.2 % | +95.7 % | -5.6 % | 63 / 37 / 0 | +80.4 % | +70.2 % (P_pool0_wait) | +61.8 % |

| policy | total log growth | band |
|---|---|---|
| weighted | +217.2 % | +150.4 % to +284.0 % |
| drawn | +128.8 % | +74.4 % to +183.2 % |
| equal | +191.6 % | +117.8 % to +265.4 % |
| drawn, other seeds | +191.8 % (mean) | +77.0 % to +308.8 % |

Arms alone: P_pool0_wait +283.3 %, P_pool0_wait_lock +203.3 %, P_pool5_top30t -32.8 %.

| weighted less | total | band | daily Sharpe | DSR (pool of all) | DSR (study) |
|---|---|---|---|---|---|
| drawn | +88.4 % | -5.6 % to +182.3 % | +0.59 | 0.850 | 0.684 |
| equal | +25.6 % | +7.0 % to +44.2 % | +0.91 | 0.934 | 0.836 |

Weighted beats drawn: **no** (enough days: no, 3 of 10).
