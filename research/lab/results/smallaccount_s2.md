# S2: a fairly safe 20 to 50 EUR wallet on Solana, against an ETF

Pre-registered in `results/smallaccount_s2_prereg.md`, code `lab.experiments.smallaccount_s2`, snapshot taken
2026-10-24 (`smallaccount_s2_tokens.csv`, `_quotes.csv`, `_tracking.csv`, `_premiums.csv`, `_snapshot.json`).
Out of sample 2024-01-01 to 2026-10-09 (the last close in `<data>/etf/daily`), S1's wallet with Jupiter's
recorded costs, the Sender tip and the 5 USDC minimum, at 20, 40 and 50 EUR. The tables below are generated.

## Answer

- **Nothing beats holding the S&P 500 token convincingly.** At 40 EUR, holding SPYx makes 20.4 % a year with
  a drawdown of 18.1 % (2024 to 2026 had no 20 % fall; in sample, 2020 to 2023, it fell 23.6 %).
- **Only one candidate passes the bar** (drawdown under 20 %, at most 1 point below the ETF): `tsmom1`, S1's
  28-day momentum on the most liquid coin (BTC, some days ETH, USDC 58 % of the days): 28.5 % a year,
  drawdown 17.8 %, Sharpe 1.10, worst month -5.6 %, 27 orders a year, costs 6.5 % of the gain. But
  not convincingly: the bootstrap band of its lead over the ETF runs from -22.6 to +48.2 points, deflated
  p 0.65, and it holds no stocks at all.
- **The safe ETF rules are safer but earn less:** the 200-day trend on SPYx (16.4 %, drawdown 9.9 %) and the
  10 % vol target over SPYx, BTC and gold (14.4 %, drawdown 10.0 %) lose 4 to 6 points a year to holding.
  The 60/40 of SPYx and BTC (25.1 %, 23.1 %) and dual momentum (35.8 %, 25.4 %) beat it but are not safe;
  trend_mix misses by 2 points (18.4 %, 18.0 %). BTC held: 24.3 %, drawdown 52 %.
- **Costs do not decide it:** SPYx costs 0.5 to 1 bps a swap at 5 to 100 USD, PAXG 1.4 to 3.7, plus about
  0.02 EUR network fee and tip a swap. At 20 EUR the SOL reserve and the minimum cost 0.7 to 3 points a year.
- **Recommendation:** fairly safe and as good as an ETF is the ETF itself: hold SPYx (or a real S&P 500 ETF
  at a broker). Do not switch the on-chain wallet on for a rule on this evidence. If the owner wants it to
  trade anyway, the only candidate that passed is the crypto rule tsmom1 (proposal below), small and as alpha.

## What a Solana wallet can hold (snapshot 2026-10-24)

Jupiter's verified list has 257 tokenized assets with some liquidity or an ETF or gold name: xStocks (81,
Backed Assets), Ondo Global Markets (109), Backpack Securities (50), pre-IPO tokens (PreStocks, Tessera)
and four gold tokens. Only a few are deep enough for a wallet: **SPYx** (S&P 500, 3.8 M USD of liquidity,
0.5 to 1.0 bps half round trip), **QQQx** (Nasdaq 100, 1.7 M, 2 to 7 bps), **GLDx** (gold ETF, 0.5 M, 4 bps),
**PAXG** (Paxos gold, 0.3 M, 1.4 to 3.7 bps), **XAUt0** (Tether gold, 0.2 M, 3 to 6 bps) and single shares
(NVDAx, TTWO, SPCX under 2 bps). SPYon (Ondo) costs 12 bps but has only 10,000 USD of liquidity; QQQon,
IVVon, GLDon, IAUon, VTIon, VTIx, VTx and VOOx are unusable (no route, or 9 to 100 % lost on a round trip).
USDC is the cash. Picks by the registered rule: **SPYx** (mint
`XsoCS1TfEyfFhfvj8EtZ528L3CaKBDBRqRapnBbDF2W`, 8 decimals, Token-2022) and **PAXG** (mint
`5GgRAEmv8ZxF2PR5hY72Qs5x1bnQ6UK2RbTPoqJ3wSwW`, 6 decimals, Token-2022).

Tracking (section 3): SPYx's daily price sat 28 bps above SPY on average (spread 35 bps, 95 % of days within
74 bps), daily tracking error 5.2 % a year, correlation 0.92; its premium rose from about 0 to about 60 bps
over the year (+0.75 % a year, used as the drift, less 30 % withholding on 1.36 % dividends: +0.34 % a year).
The hourly series of its deepest pool at the US close is noisier (spread 105 bps, a few outliers). On
weekends the ETF tokens moved 0.3 to 0.5 % on average while the market was shut (SPYx at most 1.6 %), single
shares 0.7 to 1.5 % (up to 4.7 %). PAXG followed GLD with a tracking error of 4.0 % a year over its 79 days of pool history.

**Who may hold them.** The xStocks issuer says: "xStocks are not marketed, offered, or solicited in the
United States, to U.S. Persons, or in any other prohibited jurisdiction"; for the EU/EEA a base prospectus
approved by the Liechtenstein FMA is passported, "enabling licensed third-party distributors to offer
xStocks to retail clients" (in the EU via Kraken's Cyprus entity). Ondo says its tokens are "offered only
outside the United States and only to eligible non-U.S. persons". Buying on Jupiter is the secondary market,
not the issuer's offer: whether a German resident may hold them this way must be checked against the
issuer's list of restricted countries (assets.backed.fi/legal-documentation). Paxos's and Tether's pages
did not answer: for PAXG and XAUt0 on Solana it must be checked too, including whether the Solana token
is the issuer's own or a bridge.

**Extra risks.** Issuer: an xStock is a tracker certificate (a bearer debt instrument of a Jersey SPV),
not a share, no vote; collateral with custodians under a security agent, redemption only for KYC'd and
whitelisted wallets. Control: SPYx, GLDx and PAXG have a freeze authority, the issuer can freeze a wallet's
tokens. Depeg: the price is whatever the pools pay; premiums of 0.5 to 1 % are normal, more when markets
move. Trading hours: issuance and redemption follow US market hours (24/5), weekends and US holidays are
priced by the pools alone and gap on Monday. Dividends come as more tokens (a multiplier, net of
withholding, activated 00:30 UTC after the ex-date, venues are told to pause around it).

## Paper books (from the deploy, job `paper-smallaccount`, report `reports/smallaccount/` in EUR)

Picked in sample by the registered rule (best in-sample Sharpe with an in-sample drawdown under 20 %):
`small40_spy_trend` (SPYx above SPY's 200-day average, else USDC; IS 0.97, OOS 1.39) and
`small40_vol_target` (SPYx, BTC, PAXG by inverse vol at 10 % vol, rest USDC, weekly; IS 0.67, OOS 1.35), each
with a 40 EUR paper wallet that starts from SOL, next to S1's two books, in the daily EUR report and in the
morning briefing's paper card ("Kleinkonten"). Both are the safe kind that trails the ETF out of sample.

## Proposal for the owner: the on-chain book tsmom1 would need (nothing changed, nothing switched on)

tsmom1 passed the bar (not convincingly). As an on-chain book it would be:

- **Coins and mints:** BTC as cbBTC `cbbtcf3aa214zXHbiAZQwf4122FBYbraNdFqgw4iMij` (8 decimals), ETH as WETH
  `7vfCXTUXx5WJV5JADk17DUJ4ksgau7utNKj4b963voxs` (8), cash USDC `EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v`
  (6), SOL for fees. All four are already in `lab.onchain.mints`; no stock token is needed.
- **Rule:** S1's `tsmom_top20` on 1 coin (`lab.experiments.smallaccount.candidate(P, "tsmom_top20", 1)`): the
  most liquid coin of the day, held while its 28-day return is above 0 and BTC is above its 200-day
  average, sized to 40 % annual vol, the rest USDC. The same rule as the paper book `small50_tsmom1`.
- **Cadence:** daily, after `paper-families` (04:15), one rebalance per new signal, orders under 5 USDC not sent.
- **Code it needs (a later task):** a signal writer like `lab.onchain.sol_book` that writes
  `signals/onchain_tsmom1/latest.json`, and the book in `lab.onchain.book.BOOKS` with its paper twin; the
  proof gate (30 days of paper twin) applies in test mode.
- **Ack lines** (alpha, with the wallet as the limit): `mode=alpha`, `books=onchain_tsmom1`,
  `mints=SOL,USDC,BTC,ETH`, `limits=wallet`, `book_usd=45`, `expires` at most 90 days ahead. The code's caps stay:
  at most 25 % of the wallet a swap (a full buy is split into up to four swaps), WETH at most 25 % of the book (on the
  65 ETH days out of sample the rest would stay USDC), 0.02 SOL reserve, 30 bps slippage, no swap dearer than
  50 bps or 2 % off Kraken's price, the kill switch and the simulation within 24 hours.

## Deviations and notes

- The first run retried a monthly re-weight under the minimum every day (a daily band, not the registered
  monthly rule); fixed before these numbers (trend_mix had shown 20.0 % / 17.9 %, a pass).
- The physical gold tokens are an ounce, GLD a tenth of one: their premium is measured around the median
  ratio. PAXG's pool is young (hourly data from 2026-06-30, no daily series), its drift +0.98 % a year comes
  from 79 days. The keyless sources reach back 180 days (hourly) and 365 days (daily) only.
- Some quotes hit Jupiter's keyless rate limit; a ladder that failed stops at the last rung that answered.

<!-- generated below by lab.experiments.smallaccount_s2; edit above this line only -->

Generated 2026-10-24T15:21:19+00:00. In sample 2020-08-01 to 2023-12-31, out of sample 2024-01-01 to 2026-10-09. EUR/USD 1.1194. Tokens priced from their underlying (drift a year: SPY +0.34 %, GOLD +0.98 %).

## 1. The tokens (Jupiter's verified list, liquidity as Jupiter reports it)

| token | what | family | kind | liquidity | holders |
|---|---|---|---|---|---|
| SPYx | SP500 xStock | xstocks | sp500 | 3,849,775 USD | 80,769 |
| NVDAx | NVIDIA xStock | xstocks | share | 2,936,569 USD | 182,677 |
| TTWO | Take-Two Interactive Software - Backpack Securities | backpack | share | 2,889,973 USD | 72,490 |
| SPCX | SpaceX - Backpack Securities | backpack | share | 2,886,003 USD | 111,713 |
| SPCXx | SpaceX xStock | xstocks | share | 2,284,891 USD | 68,913 |
| CRCLx | Circle xStock | xstocks | share | 2,085,538 USD | 19,288 |
| QQQx | Nasdaq xStock | xstocks | ndx | 1,707,947 USD | 37,877 |
| TSLAx | Tesla xStock | xstocks | share | 1,676,878 USD | 57,674 |
| ANTHROPIC | Anthropic PreStocks | prestocks | pre_ipo | 1,606,284 USD | 70,112 |
| MU | Micron Technology - Backpack Securities | backpack | share | 1,357,287 USD | 6,163 |
| MSTRx | MicroStrategy xStock | xstocks | share | 1,268,895 USD | 15,377 |
| OPENAI | OpenAI PreStocks | prestocks | pre_ipo | 1,155,754 USD | 66,422 |
| GLDx | Gold xStock | xstocks | gold | 549,703 USD | 42,414 |
| PAXG | PAX Gold | Paxos | gold | 277,157 USD | 909 |
| XAUt0 | Tether Gold | Tether Gold | gold | 163,608 USD | 6,632 |
| VNXAU | VNX Gold | VNX | gold | 76,526 USD | 1,688 |
| XAUM | Matrixdock Gold | Matrixdock | gold | 41,507 USD | 334 |
| SPYon | SPDR S&P 500 ETF (Ondo Tokenized) | ondo | sp500 | 9,829 USD | 1,982 |
| GLDon | SPDR Gold Shares (Ondo Tokenized) | ondo | gold | 1,307 USD | 248 |
| VTIx | Vanguard xStock | xstocks | total | 949 USD | 102 |
| QQQon | Invesco QQQ (Ondo Tokenized) | ondo | ndx | 267 USD | 686 |
| IVVon | iShares Core S&P 500 ETF (Ondo Tokenized) | ondo | sp500 | 195 USD | 123 |
| VTx | Vanguard Total World xStock | xstocks | total | 146 USD | 126 |
| VTIon | Vanguard Total Stock Market ETF (Ondo Tokenized) | ondo | total | 0 USD | 84 |
| VOOx | Vanguard S&P 500 xStock | xstocks | sp500 | 0 USD | 30 |
| IAUon | iShares Gold Trust (Ondo Tokenized) | ondo | gold | 0 USD | 84 |

## 2. What a swap costs (half the round trip USDC to token and back, bps; network fee not in)

| token | 5 USD | 10 USD | 25 USD | 50 USD | 100 USD |
|---|---|---|---|---|---|
| SPYx | 0.5 (0.00 %) | 0.5 (0.00 %) | 0.6 (0.00 %) | 0.7 (0.00 %) | 1.0 (0.00 %) |
| QQQx | 2.3 (0.00 %) | 2.9 (0.00 %) | 5.3 (0.03 %) | 6.7 (0.06 %) | 7.1 (0.06 %) |
| GLDx | 4.0 (0.00 %) | 4.0 (0.08 %) | 4.0 (0.08 %) | 4.0 (0.08 %) | None |
| PAXG | 3.7 (0.07 %) | 1.7 (0.03 %) | 2.9 (0.06 %) | 1.4 (0.02 %) | 1.4 (0.02 %) |
| XAUt0 | 5.8 (0.00 %) | 3.6 (0.00 %) | 3.7 (0.00 %) | 3.0 (0.00 %) | 3.0 (0.00 %) |
| VNXAU | 1.6 (0.00 %) | 1.7 (0.00 %) | 2.2 (0.00 %) | 2.9 (0.00 %) | 4.4 (0.00 %) |
| XAUM | 12.8 (0.02 %) | 15.6 (0.04 %) | 23.9 (0.13 %) | 37.8 (0.27 %) | 65.3 (0.55 %) |
| SPYon | 12.1 (0.23 %) | 12.6 (0.24 %) | 12.7 (0.24 %) | 12.8 (0.24 %) | 14.5 (0.24 %) |
| GLDon | 590.7 (1.74 %) | 847.0 (7.45 %) | 1232.9 (16.05 %) | 1361.6 (18.92 %) | 1425.9 (20.35 %) |
| VTIx | 950.4 (18.01 %) | 975.2 (18.01 %) | 990.1 (18.01 %) | 1024.0 (18.45 %) | 1091.8 (19.18 %) |
| QQQon | 450.1 (7.06 %) | 450.1 (7.06 %) | 450.1 (7.06 %) | 450.1 (7.06 %) | 687.6 (11.91 %) |
| IVVon | 2075.3 (39.58 %) | 2075.3 (39.58 %) | 2075.3 (39.58 %) | 2075.3 (39.58 %) | 2075.3 (39.58 %) |
| VTx | 4053.5 (42.27 %) | 4053.5 (42.27 %) | 4053.5 (42.27 %) | 4061.4 (42.27 %) | 4065.7 (42.27 %) |
| VTIon | 4995.7 (99.91 %) | 4995.6 (99.91 %) | 4995.6 (99.91 %) | None | None |
| IAUon | 4620.1 (74.55 %) | 4620.1 (74.55 %) | 4620.1 (74.55 %) | 4731.8 (82.03 %) | 4863.5 (90.85 %) |
| NVDAx | 0.2 (0.00 %) | -0.4 (0.00 %) | -0.1 (0.00 %) | 0.4 (0.00 %) | 0.3 (0.00 %) |
| TTWO | -0.1 (0.00 %) | -0.0 (0.00 %) | 0.1 (0.34 %) | -0.1 (0.00 %) | 0.1 (0.00 %) |
| SPCX | 0.8 (0.03 %) | 1.4 (0.05 %) | 2.0 (0.06 %) | 1.2 (0.02 %) | 0.3 (0.01 %) |
| BTC | -1.7 (0.00 %) | 0.9 (0.02 %) | 0.1 (0.00 %) | 2.6 (0.00 %) | None |
| ETH | -2.0 (0.00 %) | -3.1 (0.03 %) | 1.3 (0.01 %) | -0.7 (0.00 %) | 6.7 (0.00 %) |
| SOL | -3.1 (0.00 %) | -2.8 (0.00 %) | -2.9 (0.00 %) | -4.1 (0.00 %) | -7.5 (0.00 %) |

In brackets Jupiter's price impact on the way in.

## 3. How closely the tokens followed their underlying

| token | vs | source | days | since | premium mean / sd bps | abs p95 bps | TE a year | drift a year | corr | weekend move mean / max bps |
|---|---|---|---|---|---|---|---|---|---|---|
| SPYx | SPY | hourly at the US close | 124 | 2026-04-27 | 40.6 / 105.2 | 89.5 | 24.75 % | 0.14 % | 0.395 | 46.6 / 156.4 |
| SPYx | SPY | daily 00:00 UTC | 251 | 2025-10-24 | 28.3 / 34.7 | 74.1 | 5.23 % | 0.75 % | 0.915 |  |
| QQQx | QQQ | hourly at the US close | 145 | 2026-03-30 | 19.0 / 25.2 | 60.8 | 5.51 % | 0.41 % | 0.968 | 49.3 / 137.3 |
| QQQx | QQQ | daily 00:00 UTC | 251 | 2025-10-24 | 17.3 / 37.5 | 83.1 | 8.25 % | 0.07 % | 0.918 |  |
| GLDx | GLD | hourly at the US close | 145 | 2026-03-30 | 0.6 / 26.3 | 48.9 | 5.83 % | 0.04 % | 0.971 | 29.1 / 123.1 |
| GLDx | GLD | daily 00:00 UTC | 251 | 2025-10-24 | 10.7 / 57.1 | 114.3 | 12.78 % | -0.46 % | 0.906 |  |
| SPYon | SPY | hourly at the US close | 0 |  | n/a / n/a | n/a | n/a % | n/a % | n/a |  |
| SPYon | SPY | daily 00:00 UTC | 251 | 2025-10-24 | 52.7 / 38.0 | 109.5 | 5.72 % | 0.91 % | 0.899 |  |
| GLDon | GLD | hourly at the US close | 2 |  | n/a / n/a | n/a | n/a % | n/a % | n/a |  |
| GLDon | GLD | daily 00:00 UTC | 201 | 2026-01-07 | -0.3 / 59.0 | 104.8 | 13.10 % | -0.45 % | 0.912 |  |
| VTIx | VTI | hourly at the US close | 6 |  | n/a / n/a | n/a | n/a % | n/a % | n/a |  |
| VTIx | VTI | daily 00:00 UTC | 251 | 2025-10-24 | 76.2 / 113.1 | 255.9 | 21.21 % | 1.62 % | 0.430 |  |
| QQQon | QQQ | hourly at the US close | 2 |  | n/a / n/a | n/a | n/a % | n/a % | n/a |  |
| QQQon | QQQ | daily 00:00 UTC | 251 | 2025-10-24 | 23.7 / 39.4 | 91.6 | 8.80 % | 0.32 % | 0.907 |  |
| IVVon | IVV | hourly at the US close | 0 |  | n/a / n/a | n/a | n/a % | n/a % | n/a |  |
| IVVon | IVV | daily 00:00 UTC | 249 | 2025-10-24 | 57.4 / 42.0 | 135.3 | 7.77 % | 0.66 % | 0.824 |  |
| VTx | VT | hourly at the US close | 1 |  | n/a / n/a | n/a | n/a % | n/a % | n/a |  |
| VTx | VT | daily 00:00 UTC | 140 | 2026-01-21 | 23.9 / 98.5 | 171.4 | 21.91 % | 0.10 % | 0.310 |  |
| VTIon | VTI | hourly at the US close | 0 |  | n/a / n/a | n/a | n/a % | n/a % | n/a |  |
| VOOx | VOO | hourly at the US close | 0 |  | n/a / n/a | n/a | n/a % | n/a % | n/a |  |
| IAUon | IAU | hourly at the US close | 0 |  | n/a / n/a | n/a | n/a % | n/a % | n/a |  |
| IAUon | IAU | daily 00:00 UTC | 250 | 2025-10-24 | -1.3 / 59.3 | 121.6 | 13.26 % | 0.02 % | 0.899 |  |
| NVDAx | NVDA | hourly at the US close | 145 | 2026-03-30 | 3.7 / 21.9 | 40.5 | 4.90 % | 0.40 % | 0.992 | 73.8 / 234.7 |
| NVDAx | NVDA | daily 00:00 UTC | 251 | 2025-10-24 | 6.7 / 69.6 | 116.6 | 15.85 % | 0.13 % | 0.913 |  |
| TTWO | TTWO | hourly at the US close | 34 | 2026-09-08 | -7.1 / 33.9 | 61.0 | 7.17 % | 2.78 % | 0.975 | 140.4 / 470.9 |
| TTWO | TTWO | daily 00:00 UTC | 57 | 2026-08-05 | 19.4 / 40.8 | 102.0 | 8.29 % | -0.28 % | 0.970 |  |
| SPCX | SPCX | hourly at the US close | 93 | 2026-06-12 | -2.2 / 52.8 | 52.3 | 12.19 % | 0.94 % | 0.989 | 153.3 / 376.0 |
| SPCX | SPCX | daily 00:00 UTC | 93 | 2026-06-12 | -4.0 / 151.9 | 293.7 | 35.95 % | 1.03 % | 0.901 |  |
| PAXG | GLD | hourly at the US close | 79 | 2026-06-30 | 1.4 / 22.2 | 46.2 | 3.97 % | 0.98 % | 0.987 | 18.1 / 48.5 |
| XAUt0 | GLD | hourly at the US close | 145 | 2026-03-30 | 0.8 / 35.8 | 75.1 | 5.77 % | 1.10 % | 0.971 | 40.8 / 189.2 |
| XAUt0 | GLD | daily 00:00 UTC | 251 | 2025-10-24 | -4.3 / 73.0 | 106.7 | 16.19 % | 0.26 % | 0.857 |  |
| VNXAU | GLD | hourly at the US close | 119 | 2026-04-15 | 3.3 / 123.4 | 216.2 | 21.28 % | 0.69 % | 0.540 | 58.4 / 245.5 |
| VNXAU | GLD | daily 00:00 UTC | 251 | 2025-10-24 | -17.1 / 172.5 | 346.6 | 28.67 % | 1.06 % | 0.597 |  |
| XAUM | GLD | hourly at the US close | 31 | 2026-03-13 | 30.8 / 150.5 | 227.2 | 34.32 % | 1.06 % | 0.844 | 21.0 / 21.0 |
| XAUM | GLD | daily 00:00 UTC | 251 | 2025-10-24 | -11.3 / 65.5 | 142.3 | 10.30 % | -0.17 % | 0.933 |  |

## 4. The candidates out of sample at 20, 40 and 50 EUR

| candidate | EUR | CAGR | max DD | Sharpe | worst month | months > ETF | costs | orders/yr | not sent/yr | IS CAGR / DD / Sharpe |
|---|---|---|---|---|---|---|---|---|---|---|
| spy_hold | 20 | 19.7 % | 17.6 % | 1.32 | -5.2 % |  | 0.3 % | 0 | 0 | 12.7 % / 23.0 % / 0.81 |
| spy_hold | 40 | 20.4 % | 18.1 % | 1.32 | -5.4 % |  | 0.2 % | 0 | 0 | 13.2 % / 23.6 % / 0.82 |
| spy_hold | 50 | 20.5 % | 18.2 % | 1.32 | -5.4 % |  | 0.1 % | 0 | 0 | 13.3 % / 23.7 % / 0.82 |
| btc_hold | 20 | 23.6 % | 51.4 % | 0.70 | -19.4 % | 53 % | 0.3 % | 0 | 0 | 42.7 % / 75.5 % / 0.88 |
| btc_hold | 40 | 24.3 % | 52.1 % | 0.70 | -19.9 % | 53 % | 0.1 % | 0 | 0 | 43.8 % / 76.0 % / 0.89 |
| btc_hold | 50 | 24.5 % | 52.3 % | 0.71 | -20.0 % | 53 % | 0.1 % | 0 | 0 | 44.0 % / 76.1 % / 0.89 |
| spy_trend | 20 | 15.7 % | 9.8 % | 1.37 | -6.4 % | 12 % | 1.8 % | 3 | 0 | 10.8 % / 19.4 % / 0.96 |
| spy_trend | 40 | 16.4 % | 9.9 % | 1.39 | -6.5 % | 12 % | 1.0 % | 3 | 0 | 11.3 % / 19.6 % / 0.97 |
| spy_trend | 50 | 16.5 % | 9.9 % | 1.39 | -6.5 % | 12 % | 0.8 % | 3 | 0 | 11.4 % / 19.6 % / 0.98 |
| dual_mom | 20 | 34.3 % | 24.8 % | 0.95 | -16.9 % | 50 % | 1.7 % | 6 | 0 | 7.6 % / 54.0 % / 0.39 |
| dual_mom | 40 | 35.8 % | 25.4 % | 0.96 | -17.2 % | 50 % | 1.1 % | 6 | 0 | 8.3 % / 55.1 % / 0.40 |
| dual_mom | 50 | 36.1 % | 25.5 % | 0.97 | -17.3 % | 50 % | 1.0 % | 6 | 0 | 8.4 % / 55.3 % / 0.40 |
| mix_6040 | 20 | 25.1 % | 22.1 % | 1.08 | -9.6 % | 53 % | 0.9 % | 2 | 22 | 28.6 % / 45.4 % / 1.03 |
| mix_6040 | 40 | 25.1 % | 23.1 % | 1.06 | -9.0 % | 53 % | 0.7 % | 4 | 21 | 31.1 % / 47.7 % / 1.04 |
| mix_6040 | 50 | 23.9 % | 22.8 % | 1.04 | -8.6 % | 53 % | 0.7 % | 4 | 21 | 29.9 % / 47.8 % / 1.01 |
| trend_mix | 20 | 16.5 % | 19.3 % | 0.96 | -9.7 % | 41 % | 8.6 % | 13 | 18 | 28.9 % / 31.5 % / 1.27 |
| trend_mix | 40 | 18.4 % | 18.0 % | 1.04 | -9.5 % | 41 % | 4.3 % | 14 | 18 | 29.6 % / 32.4 % / 1.28 |
| trend_mix | 50 | 19.7 % | 18.0 % | 1.12 | -9.5 % | 41 % | 3.6 % | 15 | 17 | 28.6 % / 32.4 % / 1.24 |
| tsmom1 | 20 | 25.4 % | 18.8 % | 1.00 | -6.6 % | 44 % | 10.3 % | 23 | 105 | 61.6 % / 20.5 % / 2.01 |
| tsmom1 | 40 | 28.5 % | 17.8 % | 1.10 | -5.6 % | 44 % | 6.5 % | 27 | 102 | 62.8 % / 20.9 % / 2.02 |
| tsmom1 | 50 | 29.2 % | 18.2 % | 1.10 | -5.6 % | 44 % | 6.3 % | 30 | 95 | 62.0 % / 21.5 % / 2.00 |
| vol_target | 20 | 17.6 % | 7.5 % | 1.83 | -2.0 % | 50 % | 2.8 % | 4 | 152 | 2.3 % / 8.1 % / 0.46 |
| vol_target | 40 | 14.4 % | 10.0 % | 1.35 | -4.0 % | 44 % | 4.0 % | 10 | 144 | 5.4 % / 15.3 % / 0.67 |
| vol_target | 50 | 19.4 % | 9.0 % | 1.72 | -3.6 % | 50 % | 2.8 % | 12 | 145 | 6.3 % / 14.6 % / 0.77 |

`costs`: share of the gain before costs the costs took (n/a: no gain). `months > ETF`: calendar months that beat spy_hold.

## 5. Against the ETF token at 40 EUR: bootstrap, deflation, the bar

| candidate | CAGR band | CAGR minus ETF | band | draws above | deflated p | safe | matches | bar | convincing | with premium noise |
|---|---|---|---|---|---|---|---|---|---|---|
| spy_hold |  |  |  |  |  | yes | yes | no | no | 20.4 % / 18.4 % |
| btc_hold | -22.6 % to 93.5 % | 3.9 % | -39.3 % to 67.9 % | 55 % | 0.662 | no | yes | no | no | 24.3 % / 52.1 % |
| spy_trend | 5.2 % to 28.3 % | -4.1 % | -13.0 % to 3.7 % | 20 % | 0.952 | yes | no | no | no | 16.4 % / 14.4 % |
| dual_mom | -5.6 % to 97.3 % | 15.4 % | -24.1 % to 74.8 % | 72 % | 0.535 | no | yes | no | no | 35.4 % / 27.1 % |
| mix_6040 | -0.5 % to 55.5 % | 4.7 % | -15.6 % to 28.5 % | 63 % | 0.652 | no | yes | no | no | 25.2 % / 24.0 % |
| trend_mix | -0.8 % to 40.9 % | -2.0 % | -19.3 % to 18.0 % | 42 % | 0.846 | yes | no | no | no | 18.4 % / 18.2 % |
| tsmom1 | 0.0 % to 68.8 % | 8.1 % | -22.6 % to 48.2 % | 63 % | 0.650 | yes | yes | yes | no | 28.5 % / 17.8 % |
| vol_target | 4.8 % to 24.2 % | -6.0 % | -17.4 % to 4.8 % | 18 % | 0.966 | yes | no | no | no | 13.4 % / 9.8 % |

Bar: out-of-sample drawdown under 20 % and CAGR at least the ETF token's minus 1 point. Convincing: also the 5 % band of the difference above 0 and deflated p under 0.05 (8 trials). With premium noise: CAGR / drawdown, median of 20 draws of the measured premium at the close.

## 6. Paper books (picked in sample)

`spy_trend`, `vol_target`

