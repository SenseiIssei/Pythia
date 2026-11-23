# M4S2: step 2 of the readiness ladder for m4_perps, perps_neutral and m4_hl_small

Pre-registered in `results/m4_step2_prereg.md` (committed first). Code: `lab.experiments.m4_step2`, tests
`tests/test_m4_step2.py`; the ladder reads `results/m4_step2.json`. The tables below the marker are generated.

Run 2026-11-23 on M4L's frozen panel, the lockbox not read: about 12 minutes under the heavy lock (reg3n and reg5n
refit for reg7n's family). 30 trials in R5's registry (26 hand, 4 small), written to the run's copy; T14's merge
appends them to the server's registry. Paper only: no book, job, cost model, target or gate changed.

## Reading

**All three books fail step 2, on the same two rows: deflation and PBO. Late and at the costs of their era each
stays positive.** They stay on step 1 of the ladder; the ladder now shows the numbers instead of "no tested record".

- **The band reproduces exactly.** m4_perps and m4_hl_small rebuilt on time at the band's costs equal their stored
  series over all 910 days (largest difference 0). The judged numbers are the bands' own rule, nothing re-tuned.
- **One close late helps, it does not hurt**: m4_perps 0.89 against 0.71 on time, m4_hl_small 1.43 against 1.22,
  perps_neutral 1.23 against 1.04 (all at the era's costs). T6 and T6b saw the same for M4 on Binance. A day's delay
  is not where these books are fragile.
- **The era's costs are not the problem either.** T4's depth prices 99 to 100 % of the judged turnover; a 1k order
  in Binance's book costs about what DT1's proxy assumed, so the on-time numbers sit at the bands' (m4_perps 0.71,
  m4_hl_small 1.22 against the band's 1.20 with Hyperliquid's lower 2024 fee). Proxies left: Kraken's fee history
  (today's 5 bps for the whole window), Hyperliquid's fee switch dates, and Binance's book standing in for the
  venues' books, which were never measured.
- **Deflation fails by far.** Over 7,390 trials the DSR is 0.000 (m4_perps), 0.005 (m4_hl_small) and 0.002
  (perps_neutral); over the family 0.000, 0.139 (small) and 0.000. The bar is a Sharpe near 3 a year; these make
  0.9 to 1.4 on a window reg7n was picked on.
- **PBO fails for every family.** reg7n's own family (m4_funding's 18 funding-aware books) 0.58: on these inputs the
  in-sample best of the 18 is worse than the median out of sample more often than not. M4H's k 0.58, perps_neutral's
  six books and combinations 0.67 (T6b had 0.42 on the Binance universe; Kraken's coins weaken the pick further).
- **What would change it**: nothing this window can give. A forward record does not raise a DSR or lower a PBO
  measured on 2022 to 2026; the books keep running on paper as experiments, judged against their bands.


<!-- generated below by lab.experiments.m4_step2; edit above this line only -->

Generated 2026-11-23T08:51:19+00:00. M4L's frozen panel 36774aa37afa (built 2026-11-02), cut at 2026-06-30; judged decision days 2024-01-01 to 2026-06-28 (perps_neutral the same days as return days); in sample 2022-01-01 to 2023-12-31 on the Binance universe; nothing from 2026-07-01 read.

Band check (on time at the band's costs against the stored series): m4_perps matches over 910 days (largest difference 0.0e+00); m4_hl_small matches over 910 days (largest difference 0.0e+00).

30 trials in R5's registry (26 hand, 4 small, with their in-sample Sharpes, before any judged number); pool 7,390 (hand 2,281, small 1,930), noise bar 3.08 a year.

## Step 2, one row per book and requirement

| book | requirement | result | number |
|---|---|---|---|
| m4_perps | one close late still positive | pass | late CAGR 26.0 % a year, Sharpe 0.89, drawdown 33.1 % |
| m4_perps | costs of their era | pass | on time at the era's costs CAGR 19.3 %, Sharpe 0.71; Kraken's 5 bps taker for the whole window (no dated schedule); T4's depth (Binance's book standing in for the venue's) on 100 % of the judged turnover, the proxy on the rest (2024 0 %, 2025 0 %, 2026 0 %) |
| m4_perps | DSR over R5 >= 0.95 | fail | 0.000 over 7,390 trials |
| m4_perps | DSR over its family >= 0.95 | fail | 0.000 over the hand family's 2,281 |
| m4_perps | PBO < 0.2 | fail | 0.58 (the highest of: reg7n's family 0.58 over 18) |
| m4_hl_small | one close late still positive | pass | late CAGR 47.2 % a year, Sharpe 1.43, drawdown 19.6 % |
| m4_hl_small | costs of their era | pass | on time at the era's costs CAGR 38.2 %, Sharpe 1.22; Hyperliquid's 3.5 / 4.5 bps with the 2025-05-01 switch assumed to the quarter; T4's depth (Binance's book standing in for the venue's) on 100 % of the judged turnover, the proxy on the rest (2024 0 %, 2025 0 %, 2026 0 %) |
| m4_hl_small | DSR over R5 >= 0.95 | fail | 0.005 over 7,390 trials |
| m4_hl_small | DSR over its family >= 0.95 | fail | 0.139 over the small family's 1,930 |
| m4_hl_small | PBO < 0.2 | fail | 0.58 (the highest of: reg7n's family 0.58 over 18; M4H's k 0.58 over 3) |
| perps_neutral | one close late still positive | pass | late CAGR 23.2 % a year, Sharpe 1.23, drawdown 19.1 % |
| perps_neutral | costs of their era | pass | on time at the era's costs CAGR 19.7 %, Sharpe 1.04; Kraken's 5 bps taker for the whole window (no dated schedule); T4's depth (Binance's book standing in for the venue's) on 99 % of the judged turnover, the proxy on the rest (2024 1 %, 2025 1 %, 2026 4 %) |
| perps_neutral | DSR over R5 >= 0.95 | fail | 0.002 over 7,390 trials |
| perps_neutral | DSR over its family >= 0.95 | fail | 0.000 over the hand family's 2,281 |
| perps_neutral | PBO < 0.2 | fail | 0.67 (the highest of: reg7n's family 0.58 over 18; perps_neutral's pick 0.67 over 6) |

## The cases

| book | case | Sharpe | CAGR | max DD | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|---|
| m4_perps | one close late, era costs | 0.89 | 26.0 % | 33.1 % | 0.99 | 0.77 | 1.08 |
| m4_perps | on time, era costs | 0.71 | 19.3 % | 27.2 % | 0.75 | 0.84 | 0.24 |
| m4_hl_small | one close late, era costs | 1.43 | 47.2 % | 19.6 % | 1.27 | 1.75 | 1.06 |
| m4_hl_small | on time, era costs | 1.22 | 38.2 % | 28.2 % | 1.02 | 1.26 | 1.75 |
| perps_neutral | one close late, era costs | 1.23 | 23.2 % | 19.1 % | 1.04 | 1.70 | 0.61 |
| perps_neutral | on time, era costs | 1.04 | 19.7 % | 23.6 % | 0.62 | 1.99 | -0.00 |

DSR of the late case (higher is better): over all, hand and small.

| book | family | DSR all | DSR hand | DSR small |
|---|---|---|---|---|
| m4_perps | hand | 0.000 | 0.000 | 0.028 |
| m4_hl_small | small | 0.005 | 0.000 | 0.139 |
| perps_neutral | hand | 0.002 | 0.000 | 0.081 |

## Costs: the share of the judged turnover priced from T4's depth (on time)

| book | at depth | beyond the hour's depth | proxy by year |
|---|---|---|---|
| m4_perps | 100.0 % | 0.5 % | 2024 0.0 %, 2025 0.0 %, 2026 0.0 % |
| m4_hl_small | 99.9 % | 0.4 % | 2024 0.0 %, 2025 0.3 %, 2026 0.0 % |
| perps_neutral | 98.7 % | 0.2 % | 2024 0.6 %, 2025 0.9 %, 2026 3.8 % |

## PBO (CSCV, 16 blocks, every split, in sample and judged days together)

| family | PBO | candidates | splits | days | median logit |
|---|---|---|---|---|---|
| reg7n's family: m4_funding's 18 funding-aware books (Binance's universe, 15 bps) | 0.58 | 18 | 12,870 | 1640 | -0.32 |
| M4H's k: the judged cells k 3, 5 and 10 at 230 USD | 0.58 | 3 | 12,870 | 1640 | 0.00 |
| perps_neutral's pick: M4, Carry, LowVol, EW, IV and ERC, late at the era's costs | 0.67 | 6 | 12,870 | 1580 | -0.29 |
