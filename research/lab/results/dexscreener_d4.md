# D4: DexScreener archive, first study

**Verdict: nothing tradeable, as expected after two hours.** The archive started on 2026-10-27 and holds 1.9
hours (58 runs, 251 pairs of 237 tokens, no error, no 429), so no pair it saw young is 24 hours old yet; the
24 h questions are answered here from the trending snapshots only, which follow just the top boosted tokens.
What can be said:

- **1 h survival, archive.** Of pairs seen before 90 minutes, 64 % of PumpSwap pools still traded (liquidity
  at 1,000 USD and a trade in the hour) at 1 h, 73 % of pump.fun curves; 18 of 102 PumpSwap pools had their
  liquidity fall by more than 90 % in the first hours. By paid status at 1 h: 58 % of unpaid pairs against
  16 of 16 with a paid profile. That is a description, not an edge: paying for a profile is itself a sign
  that the team is still there at that hour.
- **Launchpads.** 215 of 237 tokens are pump.fun coins (migrations from the real-time collector are the
  biggest source); Raydium, Meteora and Meteora DBC pools come from the search words. Only 3 of 166
  migrated coins had a pool on another dex (Meteora), PumpSwap holds a median 100 % of their liquidity.
- **24 h, top boosted tokens (trending, since 2026-10-15).** 94 tokens listed by age 1.5 h; 72 still listed
  at 24 h, all of them above the liquidity floor, but 43 had lost more than 90 % of their liquidity from its
  peak and the mean net multiple of a 40 EUR round trip from 1 h to 24 h was 0.46 (0.33 if every token that
  left the list is a total loss). 3 of 72 doubled after costs. Bigger boosts did not do better (500+: 0 of
  11 doubled, mean 0.35).
- **Prediction at 1 h.** No feature passes the bar (Bonferroni over 24 trials, p < 0.0021). Survival has
  no test in the trending data, since every token still listed was alive. The best "win" feature (low
  volume over liquidity, test AUC 1.00 on 3 winners of 29, p 0.005) bought 4 tokens at a mean net multiple
  of 1.30 against 0.23 for all: four trades, a hint at most. It is pre-registered here for the archive:
  low volume over liquidity at 1 h, judged when the archive has 30 days of pairs seen before 1 h.

Paper only, nothing live, no book started. The job `dexscreener-study` rewrites the same report daily
under `reports/dexscreener/latest.md`; the archive section and its own prediction test fill in from day 2.

Generated 2026-10-27 08:05 UTC by `python -m lab.experiments.dexscreener_d4`. Paper only, nothing live. Costs: a 40 EUR stake at 1.16 USD, pool fee by dex (PumpSwap 1.25 % a side), constant-product impact against half the liquidity, 0.002 SOL a transaction at 100 USD a SOL, 1 % slippage a side; a rug is a total loss. Liquidity floor 1000 USD.

## 1. The archive

Collected 2026-10-27 06:11 to 2026-10-27 08:04 UTC (1.9 h, 58 runs that wrote snapshots): 2959 snapshots of 251 pairs of 237 tokens; 58 runs in all.

Tokens by discovery source: pumpfun_migration 111, search 50, profile 39, boost_top 29, boost_latest 25, ad 16, cto 5.
Pairs by dex: pumpswap 166, pumpfun 60, raydium 12, meteora 9, meteoradbc 4.

Pairs the archive saw before age 90 minutes, still trading at age 1 h (liquidity at the floor and a trade in the hour), by dex and by paid status at 1 h:

| group | pairs seen early | known at 1 h | trading at 1 h | known at 1 d | trading at 1 d | rugged |
|---|---|---|---|---|---|---|
| dex pumpswap | 102 | 77 | 49/77 (64 %) | 0 | 0/0 | 18 |
| dex pumpfun | 20 | 15 | 11/15 (73 %) | 0 | 0/0 | 0 |
| dex raydium | 4 | 3 | 3/3 (100 %) | 0 | 0/0 | 0 |
| paid_1h none | 104 | 77 | 45/77 (58 %) | 0 | 0/0 | 17 |
| paid_1h profile | 20 | 16 | 16/16 (100 %) | 0 | 0/0 | 1 |
| paid_1h both | 2 | 2 | 2/2 (100 %) | 0 | 0/0 | 0 |

Paid status at 1 h (a boost or a paid profile by then, from the snapshot and the orders) and what followed, pairs seen before 90 minutes; price ratio from the 1 h to the 24 h snapshot, before costs:

| paid at 1 h | pairs | trading at 1 d | trading at 7 d | rugged by 24 h | median ratio 24 h / 1 h | 2x |
|---|---|---|---|---|---|---|
| both | 2 | 0/0 | 0/0 | 0 | n/a | 0/0 |
| none | 104 | 0/0 | 0/0 | 17 | n/a | 0/0 |
| profile | 20 | 0/0 | 0/0 | 1 | n/a | 0/0 |

Tokens by launchpad (pump.fun for a curve pair, a migration or a mint ending in pump, letsbonk for bonk, else the dex of a token's first pair; a token trades when any of its pairs does):

| launchpad | tokens | trading at 1 h | trading at 1 d |
|---|---|---|---|
| pump.fun | 215 | 59/89 (66 %) | 1/2 (50 %) |
| raydium | 12 | 3/3 (100 %) | 2/2 (100 %) |
| pumpswap | 4 | 0/0 | 0/0 |
| meteoradbc | 4 | 0/0 | 0/0 |
| meteora | 2 | 0/0 | 0/0 |

pump.fun coins after migration: 166 with a PumpSwap pool in the archive, 3 of them also on another dex (meteora 3); median PumpSwap share of their liquidity 1.00.

## 2. Top boosted tokens in the trending snapshots (since 2026-10-15)

94 boosted tokens were first listed by age 1.5 h and could have been seen at 24 h; 72 were still listed at 20 to 28 h, 22 had left the list (outcome unknown).

| group | tokens | listed at 24 h | alive at 24 h (left = dead) | alive at 24 h (of listed) | rugged | 2x net at 24 h (of listed) | mean net multiple (left = last price) | (left = 0) |
|---|---|---|---|---|---|---|---|---|
| all all | 94 | 72 | 72/94 (77 %) | 72/72 (100 %) | 43 | 3/72 (4 %) | 0.46 | 0.33 |
| dex pumpswap | 71 | 59 | 59/71 (83 %) | 59/59 (100 %) | 43 | 2/59 (3 %) | 0.29 | 0.25 |
| dex pumpfun | 15 | 6 | 6/15 (40 %) | 6/6 (100 %) | 0 | 0/6 (0 %) | 0.92 | 0.39 |
| dex uniswap | 5 | 4 | 4/5 (80 %) | 4/4 (100 %) | 0 | 1/4 (25 %) | 1.31 | 1.14 |
| dex meteora | 1 | 1 | 1/1 (100 %) | 1/1 (100 %) | 0 | 0/1 (0 %) | 1.28 | 1.28 |
| dex meteoradbc | 1 | 1 | 1/1 (100 %) | 1/1 (100 %) | 0 | 0/1 (0 %) | 0.19 | 0.19 |
| dex flapsh | 1 | 1 | 1/1 (100 %) | 1/1 (100 %) | 0 | 0/1 (0 %) | 0.42 | 0.42 |
| boost_band 100 to 499 | 62 | 60 | 60/62 (97 %) | 60/60 (100 %) | 31 | 3/60 (5 %) | 0.45 | 0.43 |
| boost_band under 100 | 21 | 1 | 1/21 (5 %) | 1/1 (100 %) | 5 | 0/1 (0 %) | 0.55 | 0.03 |
| boost_band 500+ | 11 | 11 | 11/11 (100 %) | 11/11 (100 %) | 7 | 0/11 (0 %) | 0.35 | 0.35 |

## 3. Does a feature at age 1 h predict survival or a 2x by 24 h?

Labels: alive24f (liquidity at the floor at 24 h), x2 (a net multiple of 2 or more after costs), win (a net multiple above 1). Trending: only tokens still listed at 20 to 28 h, since a token that left the list has no outcome (leaving it is mostly the boost running out, so counting it as dead would teach the boost amount, not survival). Archive: a pair gone from DexScreener by 24 h is a total loss. Features at the snapshot nearest 1 h: log liquidity, log FDV, FDV over liquidity, volume over liquidity, buy share of trades, log trades, price change in the hour, boost amount.

Trending (top boosted): 72 tokens, the earlier 43 to fix each feature's direction, the later 29 to score it. 24 trials, so the bar is p < 0.0021.

| label | feature | train AUC | test AUC | positives in test | p | passes |
|---|---|---|---|---|---|---|
| win | vol_liq (low) | 0.67 | 1.00 | 3/29 | 0.005 | no |
| win | log_trades (low) | 0.60 | 0.94 | 3/29 | 0.015 | no |
| win | log_fdv (low) | 0.56 | 0.81 | 3/29 | 0.086 | no |
| win | boost (low) | 0.53 | 0.42 | 3/29 | 0.642 | no |
| win | chg_h1 | 0.54 | 0.26 | 3/29 | 0.174 | no |
| win | buy_share | 0.51 | 0.24 | 3/29 | 0.152 | no |
| win | fdv_liq | 0.50 | 0.17 | 3/29 | 0.063 | no |
| win | log_liq | 0.53 | 0.10 | 3/29 | 0.024 | no |
| x2 | log_liq (low) | 0.54 | n/a | 0/29 | 1.000 | no |
| x2 | log_fdv (low) | 0.51 | n/a | 0/29 | 1.000 | no |
| x2 | fdv_liq (low) | 0.62 | n/a | 0/29 | 1.000 | no |
| x2 | vol_liq (low) | 0.77 | n/a | 0/29 | 1.000 | no |
| x2 | buy_share (low) | 0.72 | n/a | 0/29 | 1.000 | no |
| x2 | log_trades (low) | 0.62 | n/a | 0/29 | 1.000 | no |
| x2 | chg_h1 (low) | 0.50 | n/a | 0/29 | 1.000 | no |
| x2 | boost (low) | 0.59 | n/a | 0/29 | 1.000 | no |

Passing the bar: none.
Paper rule on the later part: buy at 1 h when vol_liq is at or below 4.169 (train's top third), sell at 24 h: 4 trades, mean net multiple 1.30 (median 1.59) against 0.23 (median 0.00) for all 29.

Archive (every pair seen before 1 h): 0 tokens with a 1 h snapshot and a 24 h outcome, fewer than 30; no test.
