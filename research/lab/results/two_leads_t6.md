# T6: the two leads to the end

Pre-registered in `results/two_leads_t6_prereg.md` (committed first). Code `lab.experiments.two_leads_t6`
(`xs_daily.book` and `book_buffer` take an optional per-coin cost matrix), tests `tests/test_two_leads_t6.py`.
9 trials in R5's registry. In sample and validation only; the lockbox was not read. Paper only: no book, gate,
engine setting, live path or wallet changes.

## The answer

- **Lead A (perps_neutral): no.** Late at the costs of its era it still earns: validation Sharpe 1.74, 35.6 % a
  year, drawdown 11.0 %, correlation with BTC -0.06, every year positive (the published pipeline on time at 10 bps
  gives 2.56 on the same days, so the late fill and the era's costs take about 0.8). It passes its gates, CPCV
  (10th percentile 1.15) and the leak harness on its low-vol leg, and its 6 paper days (+1.9 %) sit at the 77th
  percentile of its validated 6-day returns. It fails deflation: DSR 0.050 over all 2,829 trials, 0.057 over the
  hand family; the bar needs a validation Sharpe near 3.8. PBO over the six books and combinations it was picked
  from is 0.55: the in-sample best is no better than a coin flip out of sample (EW beats ERC in validation).
- **Lead B (F2's 07493e8a8adb): no.** R10's numbers reproduce (late 22.5 % / 17.7 % at 40 EUR, 28.1 % / 17.7 % at
  100 EUR, above SXR8's 18.4 % with a smaller drawdown), its gates, F2's family PBO (0.38), CPCV and the leak
  harness pass, but the excess over the fund is small (excess Sharpe 0.20 at 40 EUR): DSR 0.000 over all, 0.031 in
  the small family, and there is no paper record.
- Neither reaches R6's lockbox. Both stand on step 1 of the provisional ladder (T3 is not on main): their gates
  hold late at era costs, deflation does not.
- **What would change the answer.** A: a validation Sharpe of about 3.8 on these days (twice today's), or a
  far smaller trial pool, which the registry does not allow; the paper book's forward record cannot overturn the
  DSR, but 90 days inside the band would be step 4's other half. B: an excess Sharpe over the fund near 2.5 in its
  family; a shadow wallet would at least start its record. Lead A's numbers used T5's cost tiers, since T4's depth
  files were not on the data folder; with them the perp costs could move either way.

<!-- generated below by lab.experiments.two_leads_t6; edit above this line only -->

Generated 2026-10-28T03:14:51+00:00. Validation 2024-01-01 to 2026-06-30; every series cut at 2026-06-30, the lockbox not read. Costs: no T4 depth file on the data folder, so the USD-M taker 5 bps plus T5's half-spread tiers (1 to 50 bps by the coin's volume that day) for every perp leg, book reweights 10 bps; T4's delisting table not present; lead B R10's costs of their era.

## Lead A: the perps_neutral portfolio (ERC of M4, carry, low vol), late at the costs of its era

Validation (2024-01-01 to 2026-06-30): Sharpe 1.74, 35.6 % a year, drawdown 11.0 %; by year 2024 1.59, 2025 1.97, 2026 1.55; correlation with BTC -0.06; 90 % band 0.81 to 2.68. Check, the published pipeline on time at 10 bps over the same days: 2.56 (published 2.47 to 2026-09-29).

| candidate | in sample Sharpe | validation Sharpe / CAGR / DD |
|---|---|---|
| M4 | 0.93 | 1.60 / 60.2 % / 29.4 % |
| Carry | 0.58 | 0.77 / 21.1 % / 34.4 % |
| LowVol | 1.01 | 1.19 / 31.1 % / 18.8 % |
| EW | 1.31 | 1.88 / 39.7 % / 12.1 % |
| IV | 1.28 | 1.81 / 37.4 % / 11.2 % |
| ERC | 1.35 | 1.74 / 35.6 % / 11.0 % |

| condition | result | evidence |
|---|---|---|
| A1 gates | pass | Sharpe above 0.5 yes; positive in 2 of 2024, 2025, 2026 yes; bootstrap 5 % above 0 yes; correlation with BTC within +-0.3 yes |
| A2 DSR all | fail | 0.050 over 2,829 trials (noise bar 2.78 a year) |
| A3 DSR family | fail | 0.057 over the hand family's 1,383 (2.74) |
| A4 PBO | fail | 0.55 over 6 candidates, 12,870 splits |
| A5 CPCV | pass | median 1.28, 10th percentile 1.15 over 55 paths, 2 near variant(s) |
| A6 leak | pass | low-vol weight function on PIT50: no leak (12 runs); M4's cached scores and carry's xs_daily features not covered by T1 |
| A7 paper record | pass | 6 days 1.9 %, percentile 77.0 % of the validation's 6-day returns (5 % -2.7 %, 95 % 4.3 %); sub-books M4 84.8 %, Carry 21.4 %, LowVol 92.4 % |

**Validation fails.** Lockbox: no look (validation fails). Step on the provisional ladder: 1. The DSR bar on this pool needs a validation Sharpe of about 3.83 (all) / 3.78 (family) on as many days.

## Lead B: F2's survivor 07493e8a8adb (Donchian 100/50 on the six), late through R10's wallets

| EUR | late CAGR / DD / Sharpe | SXR8.DE CAGR / DD / Sharpe | excess Sharpe | DSR all / small | in sample Sharpe |
|---|---|---|---|---|---|
| 40 | 22.5 % / 17.7 % / 0.94 | 18.4 % / 23.3 % / 1.21 | 0.20 | 0.000 / 0.031 | 1.67 |
| 100 | 28.1 % / 17.7 % / 1.10 | 18.9 % / 23.3 % / 1.24 | 0.34 | 0.000 / 0.052 | 1.60 |

| condition | result | evidence |
|---|---|---|
| B1 gates | pass | 40 EUR: DD < 20 % yes; 40 EUR: CAGR >= fund - 1 pt yes; 100 EUR: DD < 20 % yes; 100 EUR: CAGR >= fund - 1 pt yes |
| B2 DSR all | fail | 0.000 of the 40 EUR excess over 2,832 trials |
| B3 DSR family | fail | 0.031 over the small family's 249 (1.38 a year) |
| B4 PBO | pass | 0.38 over F2's 116 genomes (run 2026-10-28) |
| B5 CPCV | pass | median 1.12, 10th percentile 1.12 over 55 paths, 0 near variant(s) |
| B6 leak | pass | no leak (12 runs) |
| B7 paper record | fail | none: F2 lost the survivor before a shadow wallet ran |

Point in time: the six assets cannot be chosen point in time; T5's rule on coins made 0.98 on today's 20 and 0.10 on PIT20 in validation (`results/pit_universe_t5.md`, not rerun).

**Validation fails.** Lockbox: no look (validation fails). Step on the provisional ladder: 1. The DSR bar on this pool needs a validation excess Sharpe over SXR8 at 40 EUR of about 3.93 (all) / 2.48 (family) on as many days.

Trials (R5's registry, before the validation numbers): hand:t6:a:M4, hand:t6:a:Carry, hand:t6:a:LowVol, hand:t6:a:EW, hand:t6:a:IV, hand:t6:a:ERC, small:t6:07493e8a8adb:late@40, small:t6:07493e8a8adb:late@100, small:t6:07493e8a8adb:cpcv.
