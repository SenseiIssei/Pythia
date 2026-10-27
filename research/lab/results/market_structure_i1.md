# I1: calendar and lead-lag on the hourly panel

Pre-registered in `results/market_structure_i1_prereg.md` (committed before the
first run). Code: `lab.experiments.market_structure_i1`. Paper only: no paper
book, no gate, no job, nothing live. The regime part (HMM, change point
detector, a regime gate in the factory, regimes in the zoo's allocator) was
dropped after the review of 2026-10-27: M5 and M7 failed already.

## Answer

Nothing passes. 304 tests on Binance's 1h bars of the lab's 20 coins from
2020-01-01 to 2026-10-26 (59,784 hours), Holm over all of them: 59 survive
Holm and keep their sign in both halves, none clears its costs in the holdout
(2024 on). So no calendar or lead-lag feature is added to `lab.features`, and
there is nothing for the factory or the allocator to use.

- **Calendar (132 tests).** The long history confirms the earlier sweep
  (`family_season`): 10 raw p under 0.05 where 6.6 are expected by chance,
  none under Holm. The best is BTC's 21:00 UTC hour (+3.8 bps an hour against
  the rest, t 2.8, both halves positive), worth 3.5 bps a time in the holdout
  against a 30 bps round trip. US cash open and close, the Asian open, month
  turn, Deribit's monthly expiry, the funding hours, FOMC and CPI days: all
  |t| under 2.6. The holdout trade per occurrence of a long window (a weekday,
  the month turn, an expiry day) is mostly the market's drift and its noise
  (33 to 147 occurrences); some clear 30 bps by that, none is significant.
- **BTC leads alts (40).** No catch-up. 19 of 40 survive Holm, all with a
  negative IC (about -0.03 to -0.05 at 1 hour): after BTC rises, the alt does
  worse than BTC the next hour. That is not a lead: BTC's own next hour
  reverses (IC -0.057, t -9.9, a check outside the count) and the alts carry
  more of the same reversal. Holdout trades make -1.5 to +4.8 bps against
  60 bps for two legs.
- **US index hours (12).** SPY's and QQQ's last 1h bar says nothing about the
  next 1 or 4 hours of BTC, ETH or the alt basket (all |t| under 1.3, Yahoo's
  two years of 1h bars, 3,486 each).
- **Funding and open interest (120).** Funding: nothing (best |t| 1.7). Open
  interest: 40 of 80 survive Holm, all negative (rising OI, lower next hour),
  but the archive's open interest is in USD and so moves with the price (rank
  correlation of the 1-hour change with the coin's own last hour 0.72 for LTC,
  0.58 for BTC). With the own return regressed out the IC is +0.005 (LTC) and
  +0.007 (BTC), t under 1.1 (a check outside the count): the "OI lead" is the
  same hourly reversal. Holdout trades -2.7 to +9.3 bps against 30.

What is real here is one thing the lab already knew in other forms: hourly
returns reverse a little (IC about -0.05 to -0.07 at one hour). At 15 bps a
side it pays nothing; at the 4-hour horizon only 4 of the 59 Holm survivors
remain.

Caveats: today's 20 coins (survivorship accepted for a timing study), US
holidays not removed from the US windows, the cash ETFs stand for the index
futures (no futures history in the lab), the cost check of long calendar
windows rides on the holdout's drift.

## Tables

<!-- generated below by lab.experiments.market_structure_i1; edit above this line only -->

Generated 2026-10-27T11:18:16+00:00, hours 2020-01-01 to 2026-10-26 (59,784 on the grid), 304 tests counted, Holm over all of them. Yahoo 1h bars: SPY 3,486, QQQ 3,486.

| Family | Tests | Raw p < 0.05 | Holm 5 % | and both halves | and the cost check (passes) |
|---|---|---|---|---|---|
| calendar | 132 | 10 | 0 | 0 | 0 |
| BTC leads alts | 40 | 36 | 19 | 19 | 0 |
| US index hours lead crypto | 12 | 0 | 0 | 0 | 0 |
| funding and OI lead price | 120 | 68 | 40 | 40 | 0 |

### Every test under Holm 5 %

| Family | Test | Asset | h | Statistic (t or IC) | t | p | Holm p | Discovery half | Holdout half | Holdout trade bps | Cost bps | Passes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| BTC leads alts | BTC last hour -> alt minus BTC | LTC | 1 | -0.0465 | -8.05 | 8.6e-16 | 0.000 | -0.0594 | -0.0257 | +0.3 | 60 | no |
| BTC leads alts | BTC last hour -> alt minus BTC | DOT | 1 | -0.0458 | -7.54 | 4.6e-14 | 0.000 | -0.0575 | -0.0291 | +1.1 | 60 | no |
| funding and OI lead price | OI change 1h -> own return | LTC | 1 | -0.0503 | -7.31 | 2.6e-13 | 0.000 | -0.0475 | -0.0526 | +4.1 | 30 | no |
| funding and OI lead price | OI change 4h -> own return | DOGE | 1 | -0.0493 | -7.16 | 8.1e-13 | 0.000 | -0.0671 | -0.0372 | +3.2 | 30 | no |
| BTC leads alts | BTC last hour -> alt minus BTC | FIL | 1 | -0.0439 | -7.14 | 9.1e-13 | 0.000 | -0.0545 | -0.0305 | -1.0 | 60 | no |
| funding and OI lead price | OI change 1h -> own return | XRP | 1 | -0.0465 | -6.75 | 1.4e-11 | 0.000 | -0.0514 | -0.0428 | +4.4 | 30 | no |
| BTC leads alts | BTC last hour -> alt minus BTC | NEAR | 1 | -0.0411 | -6.69 | 2.2e-11 | 0.000 | -0.0512 | -0.0274 | +1.7 | 60 | no |
| BTC leads alts | BTC last hour -> alt minus BTC | LINK | 1 | -0.0387 | -6.69 | 2.2e-11 | 0.000 | -0.0482 | -0.0224 | +0.0 | 60 | no |
| BTC leads alts | BTC last hour -> alt minus BTC | ALT | 1 | -0.0384 | -6.64 | 3.1e-11 | 0.000 | -0.0462 | -0.0254 | +0.4 | 60 | no |
| funding and OI lead price | OI change 4h -> own return | LTC | 1 | -0.0455 | -6.61 | 3.8e-11 | 0.000 | -0.0511 | -0.0410 | +1.8 | 30 | no |
| funding and OI lead price | OI change 1h -> own return | DOGE | 1 | -0.0451 | -6.55 | 5.8e-11 | 0.000 | -0.0566 | -0.0374 | +2.8 | 30 | no |
| funding and OI lead price | OI change 4h -> own return | FIL | 1 | -0.0445 | -6.47 | 9.7e-11 | 0.000 | -0.0582 | -0.0347 | +1.1 | 30 | no |
| BTC leads alts | BTC last hour -> alt minus BTC | ADA | 1 | -0.0373 | -6.45 | 1.1e-10 | 0.000 | -0.0436 | -0.0269 | +2.1 | 60 | no |
| funding and OI lead price | OI change 1h -> own return | SUI | 1 | -0.0517 | -6.38 | 1.7e-10 | 0.000 | -0.0849 | -0.0433 | +8.3 | 30 | no |
| funding and OI lead price | OI change 4h -> own return | XRP | 1 | -0.0426 | -6.19 | 6.1e-10 | 0.000 | -0.0460 | -0.0401 | +3.8 | 30 | no |
| BTC leads alts | BTC last hour -> alt minus BTC | DOGE | 1 | -0.0347 | -5.99 | 2.1e-09 | 0.000 | -0.0379 | -0.0296 | +1.2 | 60 | no |
| funding and OI lead price | OI change 1h -> own return | BTC | 1 | -0.0401 | -5.82 | 5.7e-09 | 0.000 | -0.0457 | -0.0362 | -0.3 | 30 | no |
| BTC leads alts | BTC last hour -> alt minus BTC | BCH | 1 | -0.0333 | -5.76 | 8.6e-09 | 0.000 | -0.0391 | -0.0242 | -1.0 | 60 | no |
| funding and OI lead price | OI change 1h -> own return | FIL | 1 | -0.0391 | -5.68 | 1.3e-08 | 0.000 | -0.0480 | -0.0331 | -0.4 | 30 | no |
| funding and OI lead price | OI change 1h -> own return | DOT | 1 | -0.0389 | -5.65 | 1.6e-08 | 0.000 | -0.0378 | -0.0404 | +2.2 | 30 | no |
| funding and OI lead price | OI change 1h -> own return | PEPE | 1 | -0.0449 | -5.54 | 3e-08 | 0.000 | -0.0625 | -0.0389 | -1.1 | 30 | no |
| BTC leads alts | BTC last hour -> alt minus BTC | AVAX | 1 | -0.0336 | -5.49 | 3.9e-08 | 0.000 | -0.0415 | -0.0219 | -1.4 | 60 | no |
| funding and OI lead price | OI change 1h -> own return | BCH | 1 | -0.0373 | -5.41 | 6.2e-08 | 0.000 | -0.0333 | -0.0408 | -2.1 | 30 | no |
| funding and OI lead price | OI change 4h -> own return | BCH | 1 | -0.0371 | -5.40 | 6.8e-08 | 0.000 | -0.0460 | -0.0308 | -2.7 | 30 | no |
| funding and OI lead price | OI change 4h -> own return | PEPE | 1 | -0.0432 | -5.34 | 9.5e-08 | 0.000 | -0.0604 | -0.0381 | +0.6 | 30 | no |
| funding and OI lead price | OI change 1h -> own return | SOL | 1 | -0.0357 | -5.19 | 2.1e-07 | 0.000 | -0.0345 | -0.0365 | +6.6 | 30 | no |
| BTC leads alts | BTC last hour -> alt minus BTC | ATOM | 1 | -0.0299 | -5.18 | 2.2e-07 | 0.000 | -0.0317 | -0.0265 | +0.3 | 60 | no |
| funding and OI lead price | OI change 4h -> own return | ATOM | 1 | -0.0354 | -5.14 | 2.8e-07 | 0.000 | -0.0392 | -0.0324 | +1.7 | 30 | no |
| BTC leads alts | BTC last hour -> alt minus BTC | PEPE | 1 | -0.0415 | -5.13 | 2.8e-07 | 0.000 | -0.0484 | -0.0396 | +4.8 | 60 | no |
| funding and OI lead price | OI change 1h -> own return | XLM | 1 | -0.0351 | -5.10 | 3.4e-07 | 0.000 | -0.0434 | -0.0297 | +1.0 | 30 | no |
| funding and OI lead price | OI change 1h -> own return | AVAX | 1 | -0.0345 | -5.02 | 5.3e-07 | 0.000 | -0.0327 | -0.0360 | +1.3 | 30 | no |
| funding and OI lead price | OI change 1h -> own return | ADA | 1 | -0.0344 | -5.00 | 5.7e-07 | 0.000 | -0.0290 | -0.0383 | +0.8 | 30 | no |
| funding and OI lead price | OI change 4h -> own return | ADA | 1 | -0.0341 | -4.96 | 7.2e-07 | 0.000 | -0.0371 | -0.0325 | -0.2 | 30 | no |
| funding and OI lead price | OI change 4h -> own return | ETH | 1 | -0.0340 | -4.94 | 7.9e-07 | 0.000 | -0.0405 | -0.0295 | -1.9 | 30 | no |
| funding and OI lead price | OI change 1h -> own return | ETH | 1 | -0.0338 | -4.91 | 9.1e-07 | 0.000 | -0.0294 | -0.0373 | +0.6 | 30 | no |
| funding and OI lead price | OI change 4h -> own return | SUI | 1 | -0.0396 | -4.89 | 1e-06 | 0.000 | -0.0583 | -0.0352 | -0.7 | 30 | no |
| BTC leads alts | BTC last hour -> alt minus BTC | XLM | 1 | -0.0281 | -4.86 | 1.2e-06 | 0.000 | -0.0391 | -0.0106 | -1.5 | 60 | no |
| funding and OI lead price | OI change 1h -> own return | ATOM | 1 | -0.0334 | -4.85 | 1.3e-06 | 0.000 | -0.0337 | -0.0330 | +5.9 | 30 | no |
| BTC leads alts | BTC last hour -> alt minus BTC | XRP | 1 | -0.0280 | -4.83 | 1.3e-06 | 0.000 | -0.0374 | -0.0122 | +1.5 | 60 | no |
| BTC leads alts | BTC last hour -> alt minus BTC | UNI | 1 | -0.0291 | -4.76 | 1.9e-06 | 0.001 | -0.0299 | -0.0276 | +0.2 | 60 | no |
| funding and OI lead price | OI change 4h -> own return | AVAX | 1 | -0.0324 | -4.70 | 2.6e-06 | 0.001 | -0.0276 | -0.0364 | +3.6 | 30 | no |
| funding and OI lead price | OI change 4h -> own return | LINK | 1 | -0.0322 | -4.67 | 3e-06 | 0.001 | -0.0346 | -0.0304 | -0.6 | 30 | no |
| funding and OI lead price | OI change 4h -> own return | DOT | 1 | -0.0307 | -4.46 | 8.1e-06 | 0.002 | -0.0358 | -0.0279 | +0.9 | 30 | no |
| BTC leads alts | BTC last hour -> alt minus BTC | SOL | 1 | -0.0269 | -4.43 | 9.4e-06 | 0.002 | -0.0266 | -0.0257 | +1.0 | 60 | no |
| funding and OI lead price | OI change 4h -> own return | AAVE | 1 | -0.0302 | -4.38 | 1.2e-05 | 0.003 | -0.0269 | -0.0327 | +1.2 | 30 | no |
| BTC leads alts | BTC last hour -> alt minus BTC | SUI | 1 | -0.0348 | -4.30 | 1.7e-05 | 0.004 | -0.0666 | -0.0283 | -0.2 | 60 | no |
| funding and OI lead price | OI change 1h -> own return | NEAR | 1 | -0.0295 | -4.29 | 1.8e-05 | 0.005 | -0.0308 | -0.0289 | +3.7 | 30 | no |
| funding and OI lead price | OI change 4h -> own return | XLM | 1 | -0.0294 | -4.27 | 2e-05 | 0.005 | -0.0284 | -0.0303 | +1.8 | 30 | no |
| funding and OI lead price | OI change 4h -> own return | SOL | 1 | -0.0293 | -4.26 | 2.1e-05 | 0.005 | -0.0246 | -0.0342 | +6.7 | 30 | no |
| funding and OI lead price | OI change 4h -> own return | NEAR | 1 | -0.0293 | -4.26 | 2.1e-05 | 0.005 | -0.0337 | -0.0265 | +0.1 | 30 | no |
| funding and OI lead price | OI change 4h -> own return | DOGE | 4 | -0.0457 | -4.20 | 2.7e-05 | 0.007 | -0.0692 | -0.0298 | +4.6 | 30 | no |
| funding and OI lead price | OI change 4h -> own return | BTC | 1 | -0.0281 | -4.07 | 4.7e-05 | 0.012 | -0.0253 | -0.0300 | +0.4 | 30 | no |
| funding and OI lead price | OI change 1h -> own return | LINK | 1 | -0.0280 | -4.06 | 4.8e-05 | 0.012 | -0.0251 | -0.0303 | +1.2 | 30 | no |
| funding and OI lead price | OI change 1h -> own return | UNI | 1 | -0.0277 | -4.03 | 5.6e-05 | 0.014 | -0.0185 | -0.0345 | -0.9 | 30 | no |
| BTC leads alts | BTC last hour -> alt minus BTC | AAVE | 1 | -0.0246 | -4.01 | 6.2e-05 | 0.015 | -0.0258 | -0.0227 | +0.0 | 60 | no |
| funding and OI lead price | OI change 1h -> own return | AAVE | 1 | -0.0274 | -3.98 | 7e-05 | 0.017 | -0.0157 | -0.0361 | +2.0 | 30 | no |
| funding and OI lead price | OI change 4h -> own return | FIL | 4 | -0.0426 | -3.91 | 9.2e-05 | 0.023 | -0.0636 | -0.0280 | +5.0 | 30 | no |
| funding and OI lead price | OI change 4h -> own return | XRP | 4 | -0.0416 | -3.82 | 0.00013 | 0.033 | -0.0445 | -0.0394 | +9.3 | 30 | no |
| BTC leads alts | BTC last hour -> alt minus BTC | DOT | 4 | -0.0365 | -3.80 | 0.00014 | 0.036 | -0.0429 | -0.0279 | +1.4 | 60 | no |

### The 15 smallest p per family

#### calendar

| Family | Test | Asset | h | Statistic (t or IC) | t | p | Holm p | Discovery half | Holdout half | Holdout trade bps | Cost bps | Passes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| calendar | hour 21 | BTC |  | +2.76 | +2.76 | 0.0059 | 1.000 | +1.95 | +2.25 | +3.5 | 30 | no |
| calendar | hour 21 | ETH |  | +2.57 | +2.57 | 0.01 | 1.000 | +1.04 | +3.11 | +6.8 | 30 | no |
| calendar | FOMC day | ALT |  | +2.54 | +2.54 | 0.011 | 1.000 | +2.97 | +0.17 | +12.2 | 30 | no |
| calendar | hour 23 | BTC |  | -2.39 | -2.39 | 0.017 | 1.000 | -1.62 | -2.41 | +2.7 | 30 | no |
| calendar | hour 02 | ETH |  | -2.33 | -2.33 | 0.02 | 1.000 | -2.90 | +0.22 | -0.4 | 30 | no |
| calendar | hour 22 | BTC |  | +2.16 | +2.16 | 0.031 | 1.000 | +1.42 | +1.82 | +3.0 | 30 | no |
| calendar | weekday Thu | BTC |  | -2.12 | -2.12 | 0.034 | 1.000 | -1.47 | -1.74 | +27.6 | 30 | no |
| calendar | FOMC day | BTC |  | +2.12 | +2.12 | 0.034 | 1.000 | +2.61 | -0.28 | -10.7 | 30 | no |
| calendar | weekday Thu | ETH |  | -2.10 | -2.10 | 0.036 | 1.000 | -1.08 | -2.32 | +60.6 | 30 | no |
| calendar | hour 22 | ETH |  | +2.03 | +2.03 | 0.043 | 1.000 | +1.34 | +1.65 | +3.5 | 30 | no |
| calendar | US cash open | ETH |  | -1.92 | -1.92 | 0.054 | 1.000 | -0.60 | -2.35 | +12.4 | 30 | no |
| calendar | hour 23 | ETH |  | -1.90 | -1.90 | 0.057 | 1.000 | -1.19 | -2.02 | +3.3 | 30 | no |
| calendar | weekday Wed | ETH |  | +1.86 | +1.86 | 0.063 | 1.000 | +0.93 | +2.04 | +55.0 | 30 | no |
| calendar | hour 21 | ALT |  | +1.85 | +1.85 | 0.064 | 1.000 | +1.05 | +1.70 | +4.4 | 30 | no |
| calendar | weekday Wed | BTC |  | +1.82 | +1.82 | 0.069 | 1.000 | +1.25 | +1.46 | +35.2 | 30 | no |

#### BTC leads alts

| Family | Test | Asset | h | Statistic (t or IC) | t | p | Holm p | Discovery half | Holdout half | Holdout trade bps | Cost bps | Passes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| BTC leads alts | BTC last hour -> alt minus BTC | LTC | 1 | -0.0465 | -8.05 | 8.6e-16 | 0.000 | -0.0594 | -0.0257 | +0.3 | 60 | no |
| BTC leads alts | BTC last hour -> alt minus BTC | DOT | 1 | -0.0458 | -7.54 | 4.6e-14 | 0.000 | -0.0575 | -0.0291 | +1.1 | 60 | no |
| BTC leads alts | BTC last hour -> alt minus BTC | FIL | 1 | -0.0439 | -7.14 | 9.1e-13 | 0.000 | -0.0545 | -0.0305 | -1.0 | 60 | no |
| BTC leads alts | BTC last hour -> alt minus BTC | NEAR | 1 | -0.0411 | -6.69 | 2.2e-11 | 0.000 | -0.0512 | -0.0274 | +1.7 | 60 | no |
| BTC leads alts | BTC last hour -> alt minus BTC | LINK | 1 | -0.0387 | -6.69 | 2.2e-11 | 0.000 | -0.0482 | -0.0224 | +0.0 | 60 | no |
| BTC leads alts | BTC last hour -> alt minus BTC | ALT | 1 | -0.0384 | -6.64 | 3.1e-11 | 0.000 | -0.0462 | -0.0254 | +0.4 | 60 | no |
| BTC leads alts | BTC last hour -> alt minus BTC | ADA | 1 | -0.0373 | -6.45 | 1.1e-10 | 0.000 | -0.0436 | -0.0269 | +2.1 | 60 | no |
| BTC leads alts | BTC last hour -> alt minus BTC | DOGE | 1 | -0.0347 | -5.99 | 2.1e-09 | 0.000 | -0.0379 | -0.0296 | +1.2 | 60 | no |
| BTC leads alts | BTC last hour -> alt minus BTC | BCH | 1 | -0.0333 | -5.76 | 8.6e-09 | 0.000 | -0.0391 | -0.0242 | -1.0 | 60 | no |
| BTC leads alts | BTC last hour -> alt minus BTC | AVAX | 1 | -0.0336 | -5.49 | 3.9e-08 | 0.000 | -0.0415 | -0.0219 | -1.4 | 60 | no |
| BTC leads alts | BTC last hour -> alt minus BTC | ATOM | 1 | -0.0299 | -5.18 | 2.2e-07 | 0.000 | -0.0317 | -0.0265 | +0.3 | 60 | no |
| BTC leads alts | BTC last hour -> alt minus BTC | PEPE | 1 | -0.0415 | -5.13 | 2.8e-07 | 0.000 | -0.0484 | -0.0396 | +4.8 | 60 | no |
| BTC leads alts | BTC last hour -> alt minus BTC | XLM | 1 | -0.0281 | -4.86 | 1.2e-06 | 0.000 | -0.0391 | -0.0106 | -1.5 | 60 | no |
| BTC leads alts | BTC last hour -> alt minus BTC | XRP | 1 | -0.0280 | -4.83 | 1.3e-06 | 0.000 | -0.0374 | -0.0122 | +1.5 | 60 | no |
| BTC leads alts | BTC last hour -> alt minus BTC | UNI | 1 | -0.0291 | -4.76 | 1.9e-06 | 0.001 | -0.0299 | -0.0276 | +0.2 | 60 | no |

#### US index hours lead crypto

| Family | Test | Asset | h | Statistic (t or IC) | t | p | Holm p | Discovery half | Holdout half | Holdout trade bps | Cost bps | Passes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| US index hours lead crypto | QQQ last 1h bar -> coin | BTC | 1 | -0.0304 | -1.26 | 0.21 | 1.000 | -0.0242 | -0.0390 | +3.8 | 30 | no |
| US index hours lead crypto | QQQ last 1h bar -> coin | ETH | 1 | -0.0299 | -1.25 | 0.21 | 1.000 | -0.0264 | -0.0332 | +5.3 | 30 | no |
| US index hours lead crypto | QQQ last 1h bar -> coin | ALT | 1 | -0.0255 | -1.05 | 0.29 | 1.000 | -0.0159 | -0.0387 | +6.4 | 30 | no |
| US index hours lead crypto | SPY last 1h bar -> coin | ETH | 1 | -0.0226 | -0.93 | 0.35 | 1.000 | -0.0191 | -0.0243 | +9.8 | 30 | no |
| US index hours lead crypto | QQQ last 1h bar -> coin | BTC | 4 | -0.0302 | -0.80 | 0.43 | 1.000 | -0.0213 | -0.0381 | +4.3 | 30 | no |
| US index hours lead crypto | SPY last 1h bar -> coin | ALT | 1 | -0.0178 | -0.73 | 0.47 | 1.000 | -0.0053 | -0.0324 | +11.0 | 30 | no |
| US index hours lead crypto | SPY last 1h bar -> coin | BTC | 1 | -0.0156 | -0.64 | 0.52 | 1.000 | -0.0052 | -0.0277 | +6.6 | 30 | no |
| US index hours lead crypto | SPY last 1h bar -> coin | BTC | 4 | -0.0193 | -0.51 | 0.61 | 1.000 | -0.0044 | -0.0351 | +3.3 | 30 | no |
| US index hours lead crypto | QQQ last 1h bar -> coin | ETH | 4 | -0.0133 | -0.35 | 0.72 | 1.000 | +0.0223 | -0.0529 | +10.8 | 30 | no |
| US index hours lead crypto | SPY last 1h bar -> coin | ETH | 4 | -0.0118 | -0.31 | 0.75 | 1.000 | +0.0225 | -0.0522 | +12.0 | 30 | no |
| US index hours lead crypto | SPY last 1h bar -> coin | ALT | 4 | +0.0038 | +0.10 | 0.92 | 1.000 | +0.0301 | -0.0245 | -9.6 | 30 | no |
| US index hours lead crypto | QQQ last 1h bar -> coin | ALT | 4 | +0.0000 | +0.00 | 1 | 1.000 | +0.0215 | -0.0228 | -11.9 | 30 | no |

#### funding and OI lead price

| Family | Test | Asset | h | Statistic (t or IC) | t | p | Holm p | Discovery half | Holdout half | Holdout trade bps | Cost bps | Passes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| funding and OI lead price | OI change 1h -> own return | LTC | 1 | -0.0503 | -7.31 | 2.6e-13 | 0.000 | -0.0475 | -0.0526 | +4.1 | 30 | no |
| funding and OI lead price | OI change 4h -> own return | DOGE | 1 | -0.0493 | -7.16 | 8.1e-13 | 0.000 | -0.0671 | -0.0372 | +3.2 | 30 | no |
| funding and OI lead price | OI change 1h -> own return | XRP | 1 | -0.0465 | -6.75 | 1.4e-11 | 0.000 | -0.0514 | -0.0428 | +4.4 | 30 | no |
| funding and OI lead price | OI change 4h -> own return | LTC | 1 | -0.0455 | -6.61 | 3.8e-11 | 0.000 | -0.0511 | -0.0410 | +1.8 | 30 | no |
| funding and OI lead price | OI change 1h -> own return | DOGE | 1 | -0.0451 | -6.55 | 5.8e-11 | 0.000 | -0.0566 | -0.0374 | +2.8 | 30 | no |
| funding and OI lead price | OI change 4h -> own return | FIL | 1 | -0.0445 | -6.47 | 9.7e-11 | 0.000 | -0.0582 | -0.0347 | +1.1 | 30 | no |
| funding and OI lead price | OI change 1h -> own return | SUI | 1 | -0.0517 | -6.38 | 1.7e-10 | 0.000 | -0.0849 | -0.0433 | +8.3 | 30 | no |
| funding and OI lead price | OI change 4h -> own return | XRP | 1 | -0.0426 | -6.19 | 6.1e-10 | 0.000 | -0.0460 | -0.0401 | +3.8 | 30 | no |
| funding and OI lead price | OI change 1h -> own return | BTC | 1 | -0.0401 | -5.82 | 5.7e-09 | 0.000 | -0.0457 | -0.0362 | -0.3 | 30 | no |
| funding and OI lead price | OI change 1h -> own return | FIL | 1 | -0.0391 | -5.68 | 1.3e-08 | 0.000 | -0.0480 | -0.0331 | -0.4 | 30 | no |
| funding and OI lead price | OI change 1h -> own return | DOT | 1 | -0.0389 | -5.65 | 1.6e-08 | 0.000 | -0.0378 | -0.0404 | +2.2 | 30 | no |
| funding and OI lead price | OI change 1h -> own return | PEPE | 1 | -0.0449 | -5.54 | 3e-08 | 0.000 | -0.0625 | -0.0389 | -1.1 | 30 | no |
| funding and OI lead price | OI change 1h -> own return | BCH | 1 | -0.0373 | -5.41 | 6.2e-08 | 0.000 | -0.0333 | -0.0408 | -2.1 | 30 | no |
| funding and OI lead price | OI change 4h -> own return | BCH | 1 | -0.0371 | -5.40 | 6.8e-08 | 0.000 | -0.0460 | -0.0308 | -2.7 | 30 | no |
| funding and OI lead price | OI change 4h -> own return | PEPE | 1 | -0.0432 | -5.34 | 9.5e-08 | 0.000 | -0.0604 | -0.0381 | +0.6 | 30 | no |

### Calendar: the holdout trade of every window, BTC

| Window | Inside minus outside, bps an hour | t | Holdout bps per occurrence (in the sign of t) | Occurrences | Cost bps |
|---|---|---|---|---|---|
| hour 00 | +0.32 | +0.23 | -0.4 | 1030 | 30 |
| hour 01 | -1.38 | -0.99 | +1.5 | 1030 | 30 |
| hour 02 | -1.97 | -1.50 | -1.0 | 1030 | 30 |
| hour 03 | -1.24 | -1.06 | -0.8 | 1030 | 30 |
| hour 04 | -1.33 | -1.24 | -0.4 | 1030 | 30 |
| hour 05 | +0.55 | +0.52 | +0.2 | 1030 | 30 |
| hour 06 | +0.54 | +0.48 | -0.1 | 1030 | 30 |
| hour 07 | +0.22 | +0.20 | -0.4 | 1030 | 30 |
| hour 08 | +1.28 | +0.97 | +2.7 | 1030 | 30 |
| hour 09 | -0.52 | -0.46 | -1.3 | 1030 | 30 |
| hour 10 | +0.26 | +0.18 | -0.8 | 1030 | 30 |
| hour 11 | +0.46 | +0.41 | +1.8 | 1030 | 30 |
| hour 12 | +0.34 | +0.23 | -0.4 | 1030 | 30 |
| hour 13 | +0.67 | +0.46 | -2.6 | 1030 | 30 |
| hour 14 | -1.91 | -1.11 | -0.3 | 1030 | 30 |
| hour 15 | +1.27 | +0.81 | +1.1 | 1030 | 30 |
| hour 16 | -1.19 | -0.85 | +1.5 | 1030 | 30 |
| hour 17 | -0.12 | -0.09 | -2.8 | 1030 | 30 |
| hour 18 | -0.72 | -0.55 | +1.4 | 1030 | 30 |
| hour 19 | -0.55 | -0.42 | +1.6 | 1030 | 30 |
| hour 20 | +1.99 | +1.43 | +0.8 | 1030 | 30 |
| hour 21 | +3.80 | +2.76 | +3.5 | 1030 | 30 |
| hour 22 | +2.72 | +2.16 | +3.0 | 1030 | 30 |
| hour 23 | -3.49 | -2.39 | +2.7 | 1030 | 30 |
| weekday Mon | +1.27 | +1.56 | +46.4 | 148 | 30 |
| weekday Tue | -0.33 | -0.43 | +29.3 | 147 | 30 |
| weekday Wed | +1.44 | +1.82 | +35.2 | 147 | 30 |
| weekday Thu | -1.74 | -2.12 | +27.6 | 147 | 30 |
| weekday Fri | -0.11 | -0.13 | -7.3 | 147 | 30 |
| weekday Sat | -0.28 | -0.47 | +0.7 | 147 | 30 |
| weekday Sun | -0.26 | -0.39 | -11.8 | 147 | 30 |
| weekend | -0.32 | -0.63 | -11.1 | 147 | 30 |
| US cash open | -1.33 | -0.86 | +2.4 | 736 | 30 |
| US cash close | +0.93 | +0.77 | +2.0 | 736 | 30 |
| Asian open | -1.08 | -0.85 | +1.8 | 736 | 30 |
| turn of month | -0.23 | -0.31 | +68.7 | 33 | 30 |
| expiry 24h before | -0.84 | -0.61 | +94.2 | 33 | 30 |
| expiry 24h after | -0.10 | -0.06 | +19.0 | 33 | 30 |
| funding hour before | -0.73 | -0.87 | +0.7 | 3090 | 30 |
| funding hour after | +0.15 | +0.18 | +0.3 | 3090 | 30 |
| FOMC day | +4.54 | +2.12 | -10.7 | 22 | 30 |
| FOMC 14-16 NY | +0.45 | +0.03 | -68.8 | 22 | 30 |
| CPI day | +1.45 | +0.84 | +87.5 | 33 | 30 |
| CPI 08-10 NY | +12.93 | +1.13 | +44.7 | 33 | 30 |
