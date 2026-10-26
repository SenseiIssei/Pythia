# F2: the strategy factory for a small account (0 to 100 EUR), daily

Code `lab/factory/small.py` (`python -m lab.factory small`), job `factory-small` (03:00 UTC, 60 genomes, the
`heavy` lock, resumable), tests `tests/test_factory_small.py`. Paper only: nothing here reaches the engine, a live
setting or a wallet.

What it is: the weekly factory's search (random draws, mutation and crossover of the best, a ledger that only
grows, a few genomes to the held-back window, survivors as forward shadows) with what S1 and S2 measured at small
sizes instead of basis points: six assets (BTC, ETH, SOL; SPYx, QQQx and PAXG from SPY's, QQQ's and GLD's daily
history times S2's measured drift and with S2's measured premium at the close on the traded price), USDC as cash,
at most 3 held, every genome a wallet at 40 and at 100 EUR with Jupiter's recorded round trip, the network fee and
Sender tip a swap, the 5 USDC minimum, dust, the SOL reserve and the way in from SOL. Its own ledger
(`factory/small/ledger.jsonl`) and bar: S1's and S2's 16 trials plus every genome. A survivor needs both in-sample
halves positive, a held-back drawdown under 20 % and an end wallet above holding SPYx after costs at both sizes,
and must stay positive filled a close late. Survivors run as 40 EUR shadow wallets (at most 4) next to a SPYx and a
BTC wallet started the same day, and are retired after 30 days unless their Sharpe beats the SPYx wallet's.

First run, 2026-10-26, in the agent container (Yahoo's ETF closes, the panel cache of 2026-10-26): 60 genomes in a
few seconds. The in-sample race is won by gated crypto momentum with a vol target (in-sample Sharpe 1.4 to 2.2,
drawdowns 10 to 25 %); held back, three of four stay 4 to 14 points a year behind holding SPYx. One survives,
narrowly: Donchian 100/50 on all six assets, each above its 100-day average, the best one by 90-day momentum,
scaled to 20 % vol, weekly. At 40 EUR it ends at 66.75 EUR (19.9 % a year, drawdown 14.9 %, Sharpe 0.98) against
65.36 for SPYx (19.0 %, 18.6 %, 0.68) and 70.72 for BTC (22.4 %, 52 %); at 100 EUR 185.62 against 165.26. Deflated
p 0.31 over 76 trials: far from convincing, a lead of one point a year at 40 EUR. Its trials are in
`results/factory_small_seed/`, which every run merges first; the survivor's held-back line is left out of the seed,
so the server's first run checks it again (the same numbers, not a new trial) and opens its 40 EUR shadow wallet
there. The report of that run follows.

# Strategy factory, small-account mode (F2), in EUR

EXPERIMENT, paper only. Strategies for a 40 and a 100 EUR wallet on BTC, ETH, SOL, SPYx, QQQx and PAXG with USDC as cash, at most 3 held, with S1's and S2's costs (Jupiter's recorded round trip, network fee and Sender tip a swap, 5 USDC minimum, the SOL reserve, the way in from SOL). No real money.

Run 2026-10-26, generated 2026-10-26T19:13:40+00:00. In sample 2020-08-01 to 2023-12-31, held back 2024-01-01 to 2026-10-25. EUR/USD 1.1194. Token drift a year: SPYx +0.34 %, QQQx -0.10 %, PAXG +0.98 %.

**1 genome(s) beat holding SPYx held back with a drawdown under 20 % and start a 40 EUR shadow wallet; 1 shadow(s) running.**

## Trials and the bar

- this run: 60 genomes of a budget of 60 (random 30, mutation 20, crossover 10), 4 proposal(s) already tried
- ledger: 60 small-account genomes plus 16 S1/S2 trials = 76 trials; noise bar (the best of that many noise strategies) Sharpe 1.29

## The benchmarks (bought once and held, same wallet and costs)

| hold | EUR | in sample CAGR / DD / Sharpe | held back CAGR / DD / Sharpe | held back end |
|---|---|---|---|---|
| SPYx | 40 | 13.6 % / 31.7 % / 0.53 | 19.0 % / 18.6 % / 0.68 | 65.36 EUR |
| SPYx | 100 | 13.7 % / 31.7 % / 0.53 | 19.5 % / 19.0 % / 0.69 | 165.26 EUR |
| cbBTC | 40 | 44.9 % / 76.5 % / 0.90 | 22.4 % / 51.9 % / 0.67 | 70.72 EUR |
| cbBTC | 100 | 44.9 % / 76.5 % / 0.90 | 23.0 % / 52.4 % / 0.68 | 179.04 EUR |

## Best in sample this run

| key | genome | fitness | Sharpe 40 / 100 | CAGR 40 | DD 40 | orders/yr | costs 40 |
|---|---|---|---|---|---|---|---|
| b5682877eff9 | mom 56d · BTC, ETH, SOL, SPY, QQQ, GOLD · 180d return > 0 · BTC > MA100 · best 1 by mom90 · equal slots vol 20 % · weekly | 1.98 | 2.13 / 2.16 | 44.0 % | 15.8 % | 17 | 1.01 EUR |
| 07493e8a8adb | Donchian 100/50 · BTC, ETH, SOL, SPY, QQQ, GOLD · asset > MA100 · best 1 by mom90 · equal full vol 20 % · weekly | 1.69 | 1.87 / 1.81 | 43.0 % | 15.5 % | 20 | 1.50 EUR |
| e59b67ee5a1d | mom 56d · BTC, QQQ, SPY · 180d return > 0 · BTC > MA200 · best 3 by lowvol · equal slots vol 20 % · daily band 25 % | 1.40 | 1.58 / 1.60 | 24.1 % | 12.4 % | 42 | 2.03 EUR |
| c0e71d553d62 | mom 56d · BTC, ETH, SOL, SPY, QQQ, GOLD · 365d return > 0 · asset > MA100 · best 3 by mom90 · equal full vol 20 % · daily band 25 % | 1.30 | 1.51 / 1.51 | 33.8 % | 20.8 % | 75 | 4.87 EUR |
| 6a7632fa7ca0 | Donchian 20/10 · BTC, ETH, SOL, SPY, QQQ, GOLD · asset > MA100 · best 1 by mom90 · equal full vol 10 % · weekly | 1.29 | 1.41 / 1.78 | 14.4 % | 9.5 % | 33 | 1.61 EUR |
| 4b4a4270f8d0 | Donchian 100/50 · BTC, ETH, SOL, SPY, QQQ, GOLD · best 1 by mom90 · equal full vol 20 % · weekly | 1.27 | 1.63 / 1.59 | 41.2 % | 25.6 % | 19 | 1.34 EUR |
| 8bc39bedd562 | Donchian 100/50 · BTC, QQQ, SPY · best 2 by lowvol · equal slots · weekly | 1.27 | 1.34 / 1.33 | 29.6 % | 19.7 % | 13 | 0.83 EUR |
| 2e04189122b2 | mom 56d · BTC, QQQ, SPY · 180d return > 0 · BTC > MA100 · best 3 by lowvol · equal slots vol 20 % · daily band 25 % | 1.26 | 1.44 / 1.46 | 21.1 % | 15.0 % | 53 | 2.08 EUR |

## Held back (survivor: drawdown under 20 % and above holding SPYx after costs at 40 and 100 EUR)

| key | genome | 40 EUR end / CAGR / DD | 100 EUR end / CAGR / DD | SPYx 40 / 100 | BTC 40 / 100 | Sharpe vs SPYx (40) | deflated p | decision | why |
|---|---|---|---|---|---|---|---|---|---|
| b5682877eff9 | mom 56d · BTC, ETH, SOL, SPY, QQQ, GOLD · 180d return > 0 · BTC > MA100 · best 1 by mom90 · equal slots vol 20 % · weekly | 59.27 / 15.0 % / 13.5 % | 154.96 / 16.8 % / 13.1 % | 65.36 / 165.26 | 70.72 / 179.04 | 1.00 vs 0.68 | 0.31 | stopped | beats_spy fails (40 EUR 15.0 % vs SPYx 19.0 % / 100 EUR 16.8 % vs SPYx 19.5 % a year after costs) |
| 07493e8a8adb | Donchian 100/50 · BTC, ETH, SOL, SPY, QQQ, GOLD · asset > MA100 · best 1 by mom90 · equal full vol 20 % · weekly | 66.75 / 19.9 % / 14.9 % | 185.62 / 24.5 % / 14.6 % | 65.36 / 165.26 | 70.72 / 179.04 | 0.98 vs 0.68 | 0.31 | shadow | passes every held-back gate; deflated p 0.31 over 76 trials |
| e59b67ee5a1d | mom 56d · BTC, QQQ, SPY · 180d return > 0 · BTC > MA200 · best 3 by lowvol · equal slots vol 20 % · daily band 25 % | 46.49 / 5.5 % / 14.6 % | 123.81 / 7.9 % / 13.5 % | 65.36 / 165.26 | 70.72 / 179.04 | 0.45 vs 0.68 | 0.08 | stopped | beats_spy fails (40 EUR 5.5 % vs SPYx 19.0 % / 100 EUR 7.9 % vs SPYx 19.5 % a year after costs) |
| c0e71d553d62 | mom 56d · BTC, ETH, SOL, SPY, QQQ, GOLD · 365d return > 0 · asset > MA100 · best 3 by mom90 · equal full vol 20 % · daily band 25 % | 48.33 / 6.9 % / 22.6 % | 140.30 / 12.8 % / 18.5 % | 65.36 / 165.26 | 70.72 / 179.04 | 0.44 vs 0.68 | 0.08 | stopped | drawdown fails (held-back drawdown 22.6 % (40 and 100 EUR), needs under 20 %); beats_spy fails (40 EUR 6.9 % vs SPYx 19.0 % / 100 EUR 12.8 % vs SPYx 19.5 % a year after costs) |

## Shadow wallets (40 EUR each, the same costs; at most 4, retired after 30 days unless they beat holding SPYx risk-adjusted)

| book | genome | status | since | days | wallet | SPYx wallet | BTC wallet | Sharpe vs SPYx | note |
|---|---|---|---|---|---|---|---|---|---|
| fsmall_07493e8a | Donchian 100/50 · BTC, ETH, SOL, SPY, QQQ, GOLD · asset > MA100 · best 1 by mom90 · equal full vol 20 % · weekly | active | 2026-10-25 | 0 | 40.00 EUR | 40.00 EUR | 40.00 EUR | 0.00 vs 0.00 |  |

Nothing here trades: a shadow that keeps beating is a candidate for a hand study, not a book.

