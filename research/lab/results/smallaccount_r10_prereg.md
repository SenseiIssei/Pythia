# R10: the small-account path, honestly costed. Pre-registration

Registered 2026-10-27 and committed before any number below was computed. Brief R10 of the review
(`results/review_2026-10-27.md`), built on R5's trial registry and R6's windows. Code: `lab.experiments.smallaccount_r10`
(written after this file). Results go to `results/smallaccount_r10.md`. Nothing here may change once a result exists.

## Question

Before any real money: do S1's, S2's, L1's and F2's rules still hold when each order is filled one close after the
close its signal reads, when swaps cost what their era charged, when the wallet's EUR value follows a daily EUR/USD
and the way back to EUR is paid, when the ETF tokens are priced as they trade at 00:00 UTC, and when each rule is
judged against what this owner would hold instead?

## The rules (nothing new, nothing tuned)

- **S1**: its two paper picks as the lab runs them, daily: `tsmom1` (tsmom_top20 on 1 coin, which S2 and L1 took over)
  and `breakout_sol3` (Donchian 20/10 on the 3 most liquid coins with a Solana mint). S1's wallet code.
- **S2**: its five candidates that are neither references nor tsmom1 (spy_trend, dual_mom, mix_6040, trend_mix,
  vol_target), at S2's cadences. S2's wallet code.
- **L1**: `onchain_longterm` with its own rules (lab.onchain.longterm.simulate: BTC and ETH only, ETH at most 25 %, the
  10 % band, the pieces, the cheap send path). L1 is already one trial of the registry's small family
  (`small:l1`, R5); R10 adds none.
- **F2**: every genome F2 ever held back (results/factory_small_seed and the server's
  `<data>/factory/small/holdout.jsonl`, once per key), F2's wallet code. The survivor F2 lost to D1's window change
  (07493e8a8adb) is among them.

## Windows

In sample 2020-08-01 to 2023-12-31 (S1's and S2's), validation 2024-01-01 to 2026-06-30 (R6). The lockbox from
2026-07-01 stays closed: R10 never reads a day of it.

## What changes against S1, S2, L1 and F2

1. **Late fills.** Every rule twice: filled at the close its signal reads (as before) and one close late (the
   targets known at close t traded at close t+1; S2's due and re-weight days shift with them).
2. **Costs of their era.** A swap is costed on chain (today's recorded Jupiter quotes, as S1, S2, F2 and L1 charge
   them) only from the day the asset could be swapped there: SOL, USDC, ETH (WETH) and the Solana coins from
   2021-10-01 (Jupiter's launch month), BTC from 2024-11-07 (cbBTC on Solana), the S&P 500, Nasdaq 100 and gold
   tokens from 2025-06-30 (xStocks on Solana). Before that an order costs what a CEX charges: Kraken's taker fee
   (40 bps) plus the half spread of the coin's EUR pair in S1's Kraken snapshot, 10 bps of half spread where Kraken
   has no pair (assumed). The 5 USD minimum stays. The SOL reserve is held only in the on-chain era.
3. **Every wallet in USD, valued in EUR every day.** The wallet holds USDC (USD on a CEX before 2021-10) and is
   worth its USD value at the day's ECB reference EUR/USD (`results/smallaccount_r10_eurusd.csv`, carried over
   weekends and holidays). The way in: EUR to USDC at Kraken's taker fee plus the USDC/EUR half spread and 1 USDC to
   withdraw on chain (none before 2021-10). The way back at the last close: every position sold at its era's cost,
   USDC to EUR at the same fee and spread, and 0.09 EUR for the SEPA withdrawal (assumed). Before R10 a fixed
   1.1194 was used and the way back was never paid.
4. **The ETF tokens at 00:00 UTC.** The token's price at the 00:00 UTC close is its underlying's last close before
   00:00 UTC (adjusted, times S2's drift a year) times one draw of the token's measured deviation at 00:00 UTC from
   that close: CoinGecko's daily 00:00 UTC prices of SPYx, QQQx and PAXG over the last 365 days against Yahoo's last
   close before it (`results/smallaccount_r10_tokens_0000.csv`). Days after a US close draw from the US days'
   deviations, weekends and holidays from the deviations of days without a US close (the weekend staleness), both
   around the US days' mean. One fixed draw (seed 10) for the tables; for the rules that hold a token, the late
   40 EUR wallet over 10 more draws (median CAGR, worst drawdown). The rules read the underlying, not the draw.
5. **The premium series cleaned.** S2's measured premiums at the US close lose every point more than 10 robust
   standard deviations (1.4826 x the median absolute deviation) from the token's median: SPYx's -1094 bps day of
   2026-08-10. S2's noise and F2's premium noise use the cleaned series from now on; the same rule cleans the 00:00
   UTC deviations.
6. **Benchmarks.** A crypto rule (it holds only coins: S1's two, L1, F2 genomes on BTC, ETH and SOL alone) is judged
   against a wallet of half BTC and half ETH bought once at the first close and held, same venue, era costs, way in
   and way back. Every other rule (the safe path: S2's five, F2 genomes with a token) against a UCITS S&P 500 fund
   in EUR, iShares Core S&P 500 UCITS Acc on Xetra (SXR8.DE, Yahoo's close carried over non-Xetra days), bought
   once through a free savings plan with 5 bps of half spread, sold at the end at 1 EUR plus 5 bps (assumed). The
   MSCI World UCITS fund (EUNL.DE) and BTC held are shown next to it.

## The bar: real money only if a rule passes late at both wallet sizes

At 40 and at 100 EUR, filled one close late, over the validation window, in EUR after the way back:
- a crypto rule: CAGR above 0, Sharpe above the BTC/ETH wallet's at the same size, and a DSR of its daily excess
  over the BTC/ETH wallet of 0.95 or more;
- a safe-path rule: drawdown under 20 %, CAGR at least the UCITS fund's minus 1 point, and a DSR of its daily excess
  over the UCITS fund of 0.95 or more.

DSR (higher is better, pass at 0.95 or more): `metrics.dsr` over R5's trial registry, the pool of all (the
registry's lines and seed with the factory ledgers counted once by id, as `director_common.pool`); the small
family's DSR is shown next to it. A rule that passes on time but not late is reported as such and does not pass.

## Reported

`results/smallaccount_r10.md`: per rule and wallet size the on-time against the late wallet (CAGR, drawdown, Sharpe,
end in EUR), the benchmark's, the late DSR (all / small) and the verdict; in sample per rule the Sharpe with
today's quotes back to the start (as before), with era costs on time, and with era costs late; the inputs (FX range,
the deviations at 00:00 UTC by kind of day, the cleaned points, the costs by era). Full numbers in
`reports/smallaccount_r10/latest.json`.
