# T12: lead A on venues the owner can reach

Run 2026-10-29 as registered in `results/reachable_venues_t12_prereg.md` (committed first, unchanged). Code
`lab.experiments.reachable_venues_t12`, tests `tests/test_reachable_venues_t12.py`. 17 trials in R5's registry (hand
family; the lines were written to a copy in the agent run, the server's registry gets them when the study runs there,
the ids are fixed). In sample and validation only; the lockbox was not read. Paper only: no book, gate, engine
setting, live path or wallet changes. Nothing was downloaded. Tables below the marker are generated.

## What it says

**No on both venues: lead A is parked as not reachable.**

- **Hyperliquid**: the ERC keeps a validation Sharpe of 0.58 against Binance's 2.40 on the same 912 days (kept
  share 0.24, difference -1.82, band -2.62 to -0.99); the bootstrap's 5 % is below 0. The universe alone costs a
  Sharpe of 1.0 (2.40 to 1.40: about half of Binance's M4 and carry turnover is in coins Hyperliquid did not list),
  the venue's funding another 0.5 (carry on Hyperliquid's funding loses, -1.61, drawdown 62 %), its costs 0.3.
- **Kraken Futures**: over the only window it has (2025-10-24 to 2026-06-30, 250 days, a short record) the ERC makes
  0.69 against Binance's 1.95 (kept 0.35, band of the difference -3.11 to +0.84). M4 falls apart (-0.27 against
  2.55; 71 % of its Binance turnover is in coins Kraken does not list) while carry on Kraken's own funding is strong
  (3.31 against 1.48); ERC's risk weights do not lean on carry enough to save the book.
- DSR 0.000 (Hyperliquid) and 0.039 (Kraken) over 3,195 trials; the bar needs about 3.9 and 5.1.
- Kraken's carry on its own funding (3.31 over eight months) is the one number worth a look; it is one leg, one
  short window, picked after the fact, and would be its own pre-registered study.

## Deviations from the pre-registration

- **The Binance check does not reproduce 1.74.** The 2026-10-07 score cache is gone, so reg7n was refit as in T6b,
  and the lab's panels were rebuilt on 2026-10-29 (after T6b's run): T6's ERC rebuilt with T6's functions makes 2.40
  in validation (T6 1.74, T6b's tier rerun 2.08). Every venue is judged against this rebuild, the same inputs and days.
- **Listings and funding from T12b's collector** (`<data>/free/perps_all`, health done for both venues) instead of a
  snapshot file committed with the code and the `--fetch` step; `--fetch` was not written (download nothing).
- **Which venue can be reached**: Kraken's `countriesBanned` and EU platform fields and Hyperliquid's terms were not
  read (the collector keeps neither, nothing downloaded); all three lines stay UNVERIFIED.
- **Reported, not judged**: the share of T6's Binance book in coins a venue does not list is the share of its one-way
  turnover (xs_daily's books do not return weights), not of its gross weight; funding is the net a year per leg, not
  paid and received apart.
- A coin first recorded during day d is on the venue from day d + 1, decided at that close and filled one close later
  (the registered universe and late rules; the summary line "traded at the close of d + 1" is one day earlier).
- The widest half-spread tier (50 bps) has no wider tier and stays 50 bps.

<!-- generated below by lab.experiments.reachable_venues_t12; edit above this line only -->

Generated 2026-10-29T17:00:13+00:00. Data: T12b's collector (health.json of 2026-10-29T15:49:21Z, Hyperliquid 235 perps (56 delisted), Kraken Futures 209 (today's list only)), Binance's prices and volumes from the lab's panels, every input cut at 2026-06-30 24:00 UTC, the lockbox not read. Costs: Hyperliquid's base taker 2.5 / 3.5 / 4.5 bps (to 2023-12-31, to 2025-04-30, after), Kraken Futures 5 bps, each plus T5's half-spread tier one tier wider (3 to 50 bps); Binance as T6 (USD-M taker 5 bps plus T5's tiers, T4's depth not used); book reweights 10 bps. Binance check: T6's ERC rebuilt (reg7n refit as in T6b, T4's delisting table present) has a validation Sharpe of 2.40 (T6 published 1.74 on the lost 2026-10-07 cache; T6b's tier rerun on today's inputs 2.08).

## Which venue can be reached (as the venues state it; no account, key or legal opinion)

- **Binance USD-M**: the training plan's premise: not open to German retail customers (UNVERIFIED here).
- **Kraken Futures**: its instrument list names its EU platforms per contract and a `countriesBanned` field; T12b's collector keeps neither, so this run could not read them (UNVERIFIED).
- **Hyperliquid**: a decentralised venue whose terms name the restricted places; not read in this run, nothing downloaded (UNVERIFIED).

## Hyperliquid: NO

ERC over validation, 2024-01-01 to 2026-06-30 (912 days): Sharpe 0.58 against Binance's 2.40 on the same days, kept share 0.24, difference -1.82 (90 % band -2.62 to -0.99); 8.4 % a year, drawdown 13.1 %; bootstrap 5 % / 95 % -0.30 / 1.49; correlation with BTC -0.13; by year 2024 0.54, 2025 0.83, 2026 0.22. DSR 0.000 over all 3,195 trials, 0.000 over the hand family's 1,569 (pass at 0.95, higher is better); the bar needs a Sharpe of about 3.91 / 3.87 on as many days.

| condition | holds |
|---|---|
| Sharpe 1.0 or more | no |
| at least half of Binance's | no |
| bootstrap 5 % above 0 | no |
| correlation with BTC within +-0.3 | yes |
| positive in 2 of 2024, 2025, 2026 | yes |

| candidate | in sample Sharpe / CAGR / DD | judged window Sharpe / CAGR / DD | Binance, same days |
|---|---|---|---|
| M4 | -0.37 / -12.5 % / 21.0 % | 1.81 / 57.8 % / 18.0 % | 2.74 / 121.5 % / 17.3 % |
| Carry | -0.88 / -16.3 % / 14.4 % | -1.61 / -30.4 % / 62.1 % | 0.77 / 20.9 % / 34.3 % |
| LowVol | -0.19 / -5.2 % / 16.1 % | 1.20 / 28.0 % / 17.4 % | 1.31 / 34.5 % / 18.9 % |
| EW | -0.75 / -10.8 % / 9.6 % | 0.87 / 14.0 % / 11.8 % | 2.57 / 57.1 % / 10.7 % |
| IV | -0.77 / -10.4 % / 8.5 % | 0.77 / 11.7 % / 11.7 % | 2.49 / 53.9 % / 10.0 % |
| ERC | -0.95 / -12.2 % / 9.6 % | 0.58 / 8.4 % / 13.1 % | 2.40 / 51.5 % / 9.9 % |
| ERC_universe | -0.55 / -8.1 % / 9.9 % | 1.40 / 23.4 % / 10.1 % |  |
| ERC_funding | -0.70 / -9.3 % / 8.0 % | 0.88 / 13.7 % / 10.4 % |  |

Decomposition of the ERC over the judged days: Binance 2.40, the venue's coins 1.40, plus its funding 0.88, plus its costs 0.58.

Net funding a year over the judged days (received minus paid, a share of the leg's capital), and the share of T6's Binance book's one-way turnover in coins the venue does not list that day:

| leg | venue | Binance, same days | Binance turnover on coins the venue does not list |
|---|---|---|---|
| M4 | -5.0 % | -17.9 % | 47.3 % |
| Carry | 32.5 % | 56.7 % | 44.4 % |
| LowVol | -4.4 % | -6.9 % | 13.8 % |

Coins on Hyperliquid by month (with Binance data: on the lab's panel; eligible: M4 and carry coins with a score, low vol the PIT50 size):

| month | on the venue | with Binance data | M4 eligible | Carry eligible | LowVol eligible |
|---|---|---|---|---|---|
| 2023-05 | 0 | 0 | 0 | 0 | 0 |
| 2023-06 | 25 | 25 | 22 | 22 | 25 |
| 2023-07 | 28 | 28 | 23 | 23 | 28 |
| 2023-08 | 34 | 33 | 30 | 30 | 32 |
| 2023-09 | 46 | 40 | 37 | 37 | 38 |
| 2023-10 | 53 | 47 | 41 | 40 | 44 |
| 2023-11 | 74 | 64 | 52 | 51 | 50 |
| 2023-12 | 90 | 78 | 63 | 62 | 50 |
| 2024-01 | 100 | 87 | 70 | 69 | 50 |
| 2024-02 | 108 | 95 | 77 | 76 | 50 |
| 2024-03 | 118 | 102 | 81 | 80 | 50 |
| 2024-04 | 122 | 105 | 84 | 83 | 50 |
| 2024-05 | 132 | 112 | 88 | 87 | 50 |
| 2024-06 | 134 | 114 | 93 | 92 | 50 |
| 2024-07 | 132 | 116 | 95 | 94 | 50 |
| 2024-08 | 133 | 116 | 99 | 99 | 50 |
| 2024-09 | 132 | 116 | 101 | 101 | 50 |
| 2024-10 | 136 | 120 | 101 | 101 | 50 |
| 2024-11 | 142 | 122 | 106 | 106 | 50 |
| 2024-12 | 146 | 124 | 111 | 111 | 50 |
| 2025-01 | 154 | 131 | 115 | 114 | 50 |
| 2025-02 | 167 | 136 | 118 | 118 | 50 |
| 2025-03 | 173 | 141 | 121 | 120 | 50 |
| 2025-04 | 172 | 142 | 122 | 121 | 50 |
| 2025-05 | 166 | 136 | 118 | 118 | 50 |
| 2025-06 | 170 | 138 | 122 | 122 | 50 |
| 2025-07 | 172 | 139 | 120 | 120 | 50 |
| 2025-08 | 173 | 140 | 126 | 126 | 50 |
| 2025-09 | 173 | 139 | 130 | 130 | 50 |
| 2025-10 | 178 | 143 | 129 | 129 | 50 |
| 2025-11 | 183 | 147 | 128 | 128 | 50 |
| 2025-12 | 184 | 149 | 131 | 131 | 50 |
| 2026-01 | 187 | 151 | 125 | 125 | 50 |
| 2026-02 | 190 | 153 | 135 | 135 | 50 |
| 2026-03 | 190 | 152 | 118 | 118 | 50 |
| 2026-04 | 190 | 152 | 110 | 110 | 50 |
| 2026-05 | 191 | 153 | 123 | 123 | 50 |
| 2026-06 | 179 | 149 | 125 | 125 | 50 |

## Kraken Futures: NO

ERC over the overlap, inside validation (about eight months: a short record, not a validation), 2025-10-24 to 2026-06-30 (250 days): Sharpe 0.69 against Binance's 1.95 on the same days, kept share 0.35, difference -1.26 (90 % band -3.11 to +0.84); 10.4 % a year, drawdown 11.9 %; bootstrap 5 % / 95 % -1.30 / 3.03; correlation with BTC -0.05. DSR 0.039 over all 3,195 trials, 0.043 over the hand family's 1,569 (pass at 0.95, higher is better); the bar needs a Sharpe of about 5.10 / 5.05 on as many days.

| condition | holds |
|---|---|
| Sharpe 1.0 or more | no |
| at least half of Binance's | no |
| bootstrap 5 % above 0 | no |
| correlation with BTC within +-0.3 | yes |

| candidate | in sample Sharpe / CAGR / DD | judged window Sharpe / CAGR / DD | Binance, same days |
|---|---|---|---|
| M4 | n/a | -0.27 / -10.9 % / 20.6 % | 2.55 / 111.8 % / 13.1 % |
| Carry | n/a | 3.31 / 102.8 % / 6.3 % | 1.48 / 52.0 % / 20.4 % |
| LowVol | n/a | -1.01 / -21.9 % / 18.2 % | -0.11 / -5.6 % / 18.5 % |
| EW | n/a | 0.95 / 14.5 % / 11.1 % | 2.41 / 48.1 % / 7.7 % |
| IV | n/a | 0.56 / 8.1 % / 11.9 % | 2.00 / 39.1 % / 8.2 % |
| ERC | n/a | 0.69 / 10.4 % / 11.9 % | 1.95 / 37.9 % / 8.3 % |
| ERC_universe | n/a | -0.49 / -8.8 % / 12.4 % |  |
| ERC_funding | n/a | 1.10 / 18.1 % / 11.8 % |  |

Decomposition of the ERC over the judged days: Binance 1.95, the venue's coins -0.49, plus its funding 1.10, plus its costs 0.69.

Net funding a year over the judged days (received minus paid, a share of the leg's capital), and the share of T6's Binance book's one-way turnover in coins the venue does not list that day:

| leg | venue | Binance, same days | Binance turnover on coins the venue does not list |
|---|---|---|---|
| M4 | -23.7 % | -47.3 % | 71.0 % |
| Carry | 92.0 % | 117.0 % | 55.3 % |
| LowVol | -0.6 % | -17.1 % | 23.6 % |

Coins on Kraken Futures by month (with Binance data: on the lab's panel; eligible: M4 and carry coins with a score, low vol the PIT50 size):

| month | on the venue | with Binance data | M4 eligible | Carry eligible | LowVol eligible |
|---|---|---|---|---|---|
| 2025-11 | 161 | 135 | 124 | 124 | 50 |
| 2025-12 | 163 | 136 | 124 | 124 | 50 |
| 2026-01 | 168 | 137 | 112 | 112 | 50 |
| 2026-02 | 169 | 137 | 120 | 120 | 50 |
| 2026-03 | 177 | 138 | 108 | 108 | 50 |
| 2026-04 | 178 | 139 | 101 | 101 | 50 |
| 2026-05 | 178 | 139 | 109 | 109 | 50 |
| 2026-06 | 179 | 139 | 109 | 109 | 50 |

## Checks

- T1's leak harness on the low-vol weight function on Hyperliquid's PIT50: no leak (12 runs); M4's scores and carry's xs_daily features are not covered by T1.
- Trials (R5's registry, hand family, before any judged number): hand:t12:hyperliquid:M4, hand:t12:hyperliquid:Carry, hand:t12:hyperliquid:LowVol, hand:t12:hyperliquid:EW, hand:t12:hyperliquid:IV, hand:t12:hyperliquid:ERC, hand:t12:hyperliquid:ERC_universe, hand:t12:hyperliquid:ERC_funding, hand:t12:kraken:M4, hand:t12:kraken:Carry, hand:t12:kraken:LowVol, hand:t12:kraken:EW, hand:t12:kraken:IV, hand:t12:kraken:ERC, hand:t12:kraken:ERC_universe, hand:t12:kraken:ERC_funding, hand:t12:binance:erc_kraken_days.
