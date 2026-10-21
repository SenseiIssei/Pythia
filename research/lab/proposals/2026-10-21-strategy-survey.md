# Strategy survey: what the literature says is left to test (2026-10-21)

*Research survey by the research director (claude-opus-5-5, 2026-10-21). Nothing here runs anything. Every sketch below is a draft: before a result exists, the owner fixes its numbers, commits it as a pre-registration in `results/` and counts its trials into the global pool (1,724 after `gated_btc`).*

## How to read this

- **Scope.** Published strategies and anomalies with out-of-sample, replicated or post-publication evidence, held against what `research/lab/README.md` already tested, the venues the lab has (Alpaca paper: US stocks and ETFs commission free, about 30 spot coins at about 25 bps taker / 15 maker, stock shorting, Level 3 options in paper; Kraken Futures demo: perpetuals, being added; Polymarket read-only) and the data in the lake (Binance spot and USD-M daily, hourly, 5-minute and 1-minute klines since 2020 including delisted pairs, perp funding, OI and long/short metrics, order books since 2026-09-30, point-in-time S&P 500 daily since 1996, Yahoo ETF closes, SEC EDGAR, Deribit DVOL and option snapshots since 2026-10-15, DefiLlama stablecoins, Upbit and Coinbase BTC).
- **What changed.** Two things move the ranking against older lab write-ups. First, Kraken Futures makes perpetuals tradeable, so the one robust family (low vol and M4 long/short, `m4_residual` pass) and every short leg are no longer academic. Kraken advertises 5 bps taker on futures and, for EEA clients, a zero-fee perps waiver up to $10M of volume [S59]; eligibility needs checking, but the cost of a perp long/short book may be a fraction of the 15 / 41 bps the lab charges. Second, Alpaca paper accounts have Level 3 options [S58], which opens the volatility risk premium on IBIT and SPY.
- **Prior expectation.** Post-publication returns fall by about a third on average in US equities [S32], most anomalies still replicate in new data [S33], and crypto factors weaken after 2020 and concentrate in micro caps and bull markets [S3, S6]. The crypto carry trade went from a Sharpe of 6.45 (2020 to 2025) to 4.06 from 2024 and negative in 2025 [S3]. Expect most of the list below to fail; that is why the ranking is by expected value per hour of work, not by headline Sharpe.

## Top 10 untested candidates, ranked by expected value per unit of effort

| Rank | Candidate | Venue | Effort | Why it ranks here |
|---|---|---|---|---|
| 1 | Cross-sectional funding carry on perps | Kraken Futures | Hours (xs_daily panel and book code exist) | Tradeable as soon as Kraken is wired; cheap to test; tells whether M4's edge is just funding avoidance |
| 2 | VIX term-structure short-volatility sleeve | Alpaca (SVXY, VIXY) | About a day | Well documented premium, uncorrelated with the crypto books; `book_portfolio` showed an equity-like sleeve is what improves them |
| 3 | Earnings announcement premium | Alpaca stocks | Hours (`edgar.py` events exist) | The only equity anomaly with a decades-long record that our EDGAR events can test today with no new data |
| 4 | S&P 500 discretionary deletions | Alpaca stocks | Hours to a day | Membership and dead names are already in the lake; large reported effect; untested |
| 5 | Time-series momentum with a short leg on perps | Kraken Futures | Hours | The gate carries the long-only books (`gated_btc`); a bear-market short leg is the natural next question once shorting exists |
| 6 | Same-calendar-month return seasonality | Alpaca stocks | Hours | Replicates well across markets and in the post-publication data; S&P 500 point-in-time panel is enough |
| 7 | Gross profitability plus net share issuance | Alpaca stocks | Days (XBRL parsing) | Two of the most robust equity factors; `equities_ranking` noted the missing quality proxy |
| 8 | Turn of the month and pre-holiday in SPY / QQQ | Alpaca ETFs | Hours (overnight study code) | Nearly free to run; small, contested edge; useful only as a low-exposure sleeve |
| 9 | BTC volatility risk premium (put-write / covered call) | Alpaca paper options on IBIT | Days | Documented premium, regime dependent; history only synthetic (DVOL), forward on real IBIT quotes |
| 10 | Opportunistic insider purchases (Form 4) | Alpaca stocks | Days (SEC flat files) | Strong published evidence, weaker in large caps; needs a new collector |

Original idea O1 (route the crypto books' BTC and ETH legs through spot ETFs during US hours) is a cost saving rather than an anomaly and could jump this queue: see "Original ideas".

### 1. Cross-sectional funding carry on perpetuals

**Question.** Does a long/short book long the 10 lowest and short the 10 highest mean funding rates among the 100 most liquid USDT perps (restricted to the symbols Kraken Futures lists, with a point-in-time twin of the 100 most liquid by date), net of the funding each side pays, earn a holdout Sharpe above 0.5 at 41 bps, and does any of it survive after removing the low-vol book and BTC with frozen betas, as in `m4_residual`? **Mechanism.** Funding is the price of leverage demanded by trend-chasing retail longs and limited arbitrage capital [S12, S13]; coins with high funding are crowded and should underperform after funding, coins with negative funding carry a short-squeeze premium. **Data.** `hist/binance_um/funding` and `klines_1d` (have); Kraken Futures instrument list from its public API (need, one call). **Trials (13).** Signal window {1, 7, 28-day mean funding} x book {10/10, 20/20} x rebalance {3-day tranches, weekly} = 12, plus the residual test of the in-sample pick = 1. Selection 2020-08 to 2023, holdout 2024-01-01 to the funding archive end. **Pass rule.** The in-sample pick: holdout Sharpe above 0.5 at 41 bps and above 0 at 70; positive in 2 of 3 holdout years; one close late still positive; twin positive; the residual against low vol and BTC (betas frozen on 2022-23) above 0.3 with a 90 % stationary bootstrap band above 0; counted as confirmed only with deflated p above 0.95 over the pool. **Kill rule.** Residual Sharpe at or below 0.1: record funding carry as a re-labelled low-vol bet and stop. **What could fool us.** High funding is mostly the hot, high-vol coins, so carry and low vol overlap; the published decay of carry after 2024 [S3] says a gross number from 2021 means little. The only standalone carry study found on perps is a negative post-mortem [S68].

### 2. VIX term-structure short-volatility sleeve

**Question.** Does holding a -0.5x short-VIX-futures ETP (SVXY since its 2018-02-28 re-leverage; before that a synthetic -0.5x daily VIXY / VXX return) only when VIX is below VIX3M, cash otherwise, beat SPY on Sharpe with a smaller drawdown out of sample, and does a 10 or 20 % sleeve of it improve the crypto books by `book_portfolio`'s rule? **Mechanism.** VIX futures sit above expected spot VIX in contango because investors pay for crash insurance; the basis predicts futures returns, not spot VIX changes [S43]. Term structure is the conditioning signal: backwardation marks stress, when short volatility loses [S44, S45]. **Data.** Yahoo `^VIX`, `^VIX3M` (formerly VXV, from 2007), SVXY, VIXY, VXX (need; the ETF downloader already exists). **Trials (8).** Entry {ratio below 1.00, below 0.95, below its own 60-day mean} x sizing {fixed, scaled by VIX / 100 as in [S45]} = 6, plus the two sleeve sizes = 8. Selection 2009 to 2017, out of sample 2018 to 2026-10, so that February 2018 (VIX doubled in a day with the curve still in contango at the prior close) and March 2020 sit in the judged window. **Pass rule.** Out-of-sample Sharpe above SPY's at 3 bps a side plus a modelled 10 bps of ETP spread on every switch, drawdown below SPY's, positive in 6 of 9 years, still positive a day late; for the sleeve, `book_portfolio`'s rule (higher Sharpe and lower drawdown than the best crypto book alone, 2 of 3 years, bootstrap band of the difference above 0). Deflated over the pool. **Kill rule.** A single-day loss larger than 30 % of the sleeve in the out-of-sample path, or Sharpe below 60/40's. **Costs and capacity.** Tiny relative to SVXY volume; the risk is the tail, not the cost.

### 3. Earnings announcement premium

**Question.** Do S&P 500 members with an expected earnings announcement in the next N trading days outperform the equal-weight index over those days, after 5 bps a side? **Mechanism.** Attention and volume spike at announcements, short-sale constraints and limited risk capacity let prices rise into scheduled news [S36, S37]; reported at 7 % a year in the US and about 8 % a year in 46 countries [S38]. Predicted dates (needed to trade) give smaller premia than actual ones [S37]. **Data.** `equities/edgar/events.parquet` (have): expected date = the same fiscal quarter's event one year earlier plus 364 days; prices and membership (have). **Trials (6).** Window {announcing within 5, within 10 trading days} x entry {5, 2 days before the expected date} = 4, plus the Frazzini and Lamont volume filter (names whose past announcement months had the highest volume) on the in-sample pick's two windows = 6. Selection 2004 to 2015 (EDGAR item 2.02 coverage), out of sample from 2016. **Pass rule.** Out of sample: alpha against equal weight above 0 with a month-block bootstrap band above 0, information ratio above 0.3, still positive with the entry a day late, a long-only book (all names in the window, equal weight, cash otherwise blended with SPY) beating SPY's Sharpe; deflated. **Kill rule.** Information ratio below 0.1 out of sample. **What could fool us.** EDGAR filing dates lag the press release for 10-Q-only events; use 8-K 2.02 events only for the judged run.

### 4. S&P 500 discretionary deletions

**Question.** Do stocks removed from the S&P 500 for reasons other than a takeover, bought at the first close after removal and held 3, 6 or 12 months, beat the equal-weight index, and does deletions minus additions (additions shorted on Alpaca) pay? **Mechanism.** Index funds sell deletions at depressed valuations and buy additions at more than four times the deletions' multiples; reported excess of deletions over additions is about 22 % in the following year [S41]. The announcement-day index effect itself has nearly disappeared since 2010 (+0.8 % for additions, -0.6 % for deletions) [S42], so only the slow reversal is tested here. **Data.** `equities/membership_intervals.parquet` and `prices.parquet` (have). Discretionary = still priced 60 trading days after removal. Check first that `prices.parquet` carries names after they leave the index; if not, Alpaca daily bars from 2016 and Yahoo before. **Trials (5).** Long deletions {3, 6, 12 months}, deletions minus additions {6, 12 months}. Selection 1996 to 2012, out of sample 2013 on (at most about 15 to 25 events a year). **Pass rule.** Out-of-sample mean cumulative return over equal weight above 0 with an event-bootstrap band above 0, positive in 2 of 3 out-of-sample sub-periods, the book (equal weight across live positions) above equal weight's Sharpe; deflated. **Kill rule.** Mean excess below 0 out of sample. **What could fool us.** Few events, fat tails, and the lake's dead-name coverage; a handful of bankruptcies can decide it, which is a result in itself.

### 5. Time-series momentum with a short leg on perpetuals

**Question.** Adding a short leg to `tsmom_top20` and `breakout_top10` on perps (short the coins whose rule says exit, while BTC is below its 200-day average), net of funding and at 15 / 41 bps, does it beat the long-only book with cash? **Mechanism.** Time-series momentum is symmetric in futures markets [S25, S26]; in crypto time-series momentum is strong where cross-sectional momentum is weak [S2]. The lab's books are flat in bear regimes (`gated_btc`: the gate carries them); a short leg tests whether the trend persists down as well. **Data.** Have (perp klines and funding since 2020). **Trials (8).** Short rule {mirror of the long rule, only when BTC is below its 200-day average} x book {tsmom_top20, breakout_top10} x short size {50, 100 % of the long gross} = 8. **Pass rule.** The six gates of `flow_overlays` against the long-only book (Sharpe and 2 of 3 years, drawdown, bootstrap band of the difference above 0, a day late, survivorship-free twin, deflated improvement). **Kill rule.** The short leg alone negative from 2024 at 41 bps. **What could fool us.** 2022 alone (one long bear market) can carry it; report the leg per year.

### 6. Same-calendar-month return seasonality

**Question.** Does a stock's average return in the same calendar month over prior years predict its return this month among S&P 500 members? **Mechanism.** Recurring seasonal demand and seasonal exposure to priced factors [S34, S35]; a same-month-winners strategy earned about 13 % a year in the US [S35], appears in commodities and country indices, and holds in developed markets; the seasonality cluster replicates well in new data [S33]. **Data.** Have (point-in-time members from 1996; lags need at least 5 years, so signals start 2001). **Trials (6).** Lags {years 1 to 5, 1 to 10, all available up to 20} x book {top 50 long-only, top minus bottom decile with Alpaca shorting} = 6. Selection 2001 to 2015, out of sample from 2016. **Pass rule.** Out-of-sample rank IC t above 2 (non-overlapping months), long/short Sharpe above 0.3 at 5 bps a side, information ratio of the long-only book against equal weight above 0 with a bootstrap band above 0; deflated. **Kill rule.** IC t below 1. **Costs.** Ranks change completely each month, so turnover is close to 200 % a month; 5 bps a side keeps that near 2.4 % a year, which the reported premium covers if it is there.

### 7. Gross profitability plus net share issuance

**Question.** Does a composite of gross profit to assets and one-year net share issuance, point-in-time by EDGAR filing date, pick S&P 500 members that beat equal weight from 2011? **Mechanism.** Profitable firms earn more than their valuations imply [S29, S30]; firms that issue shares underperform and buyers of their own stock outperform [S31]; both are in the replicating core of the factor zoo [S33]. **Data.** SEC XBRL `companyfacts` (need; free, keyless, includes a `filed` date per fact, coverage from about 2009 to 2011), prices and members (have). **Trials (6).** Signal {GP/A, issuance, composite} x book {top 50 long-only, quintile long/short} = 6. Selection 2011 to 2017, out of sample from 2018 (short; say so). **Pass rule.** As `equities_ranking`'s six gates: information ratio above 0.3 against equal weight, bootstrap band above 0, above the 12-1 momentum baseline (IR 0.20), deflated. **Kill rule.** IR below 0.1. **What could fool us.** Large caps only and a short out-of-sample window; the factor's large-cap premium is smaller than the published all-stock numbers.

### 8. Turn of the month and pre-holiday in index ETFs

**Question.** Does holding SPY or QQQ only from the last trading day of a month through the third trading day of the next (and the day before US market holidays) earn most of the index premium with a fraction of the exposure, and does it help the crypto books as a sleeve? **Mechanism.** Month-end pay flows and window dressing [S53]; reported to have faded in futures after 1990 [S54] but still found in ETF-era data, concentrated on the first day. `overnight` used turn of month only as a night filter. **Data.** Have (Yahoo from 1993). **Trials (10).** Window {[-1, +3], [-2, +3], [-1, +1]} x ETF {SPY, QQQ, IWM} = 9, plus pre-holiday days = 10. Selection 1993 to 2015, out of sample from 2016. **Pass rule.** Mean daily return on window days above other days with t above 2 out of sample; Sharpe above SPY's at 2 bps a side; the 20 % sleeve passes `book_portfolio`'s rule. **Kill rule.** Window days not above other days out of sample.

### 9. BTC volatility risk premium

**Question.** Does selling 30-day BTC volatility (a cash-secured at-the-money put, a 10 % out-of-the-money put, or a covered call, rolled monthly) priced from DVOL minus a skew and spread haircut earn more per unit of risk than BTC and than gated BTC since 2021, and does a DVOL-minus-realized filter improve it? **Mechanism.** Investors pay for short-term insurance; the Bitcoin variance risk premium is positive on average and larger in calm regimes [S16, S17]. **Data.** DVOL (have, from 2021), Binance BTC (have); Deribit option snapshots only from 2026-10-15, so history is synthetic (Black-Scholes at DVOL less a haircut); forward on real IBIT option quotes in Alpaca paper (Level 3 in paper [S58]). **Trials (6).** {ATM put-write, 10 % OTM put-write, ATM covered call} x {always, only when DVOL exceeds the trailing 30-day realized vol by its in-sample median} = 6. **Pass rule.** Synthetic Sharpe above BTC's and gated BTC's with a 3 vol-point haircut (and still above 0 with 6 points), drawdown below BTC's, positive in 3 of 5 years; then 60 days of paper on IBIT options with fills recorded inside the quoted spread, landing inside the synthetic band. **Kill rule.** Sharpe below BTC's at the 3-point haircut. **What could fool us.** DVOL is a 30-day at-the-money-ish index; out-of-the-money puts are priced off the skew, so the OTM variants are the least trustworthy.

### 10. Opportunistic insider purchases

**Question.** Do open-market purchases (Form 4 code P) by insiders who are not routine traders, filed in the last 30 days, predict 1 and 3-month returns of S&P 500 members and, from 2016, of the Alpaca-tradeable universe? **Mechanism.** Insiders hold private information; separating routine traders (same month in each of the three prior years) from opportunistic ones yields 82 bps a month value-weighted for the latter and nothing for the former [S39]. **Data.** SEC Insider Transactions Data Sets (need; free quarterly flat files [S40]); prices (have; Alpaca bars beyond the S&P 500). **Trials (6).** Signal {all purchases, opportunistic only, cluster buys by 2 or more insiders} x hold {1, 3 months} = 6. Selection to 2015, out of sample from 2016. **Pass rule.** Mean excess over equal weight above 0 with an event-bootstrap band above 0; the book's Sharpe above equal weight's; deflated. **Kill rule.** Excess below 0 in the S&P 500 out of sample (the broader universe then only as a forward shadow).

## Full catalog

Status uses the README's study names. "Tested" means the lab ran it or the same idea; "close" means a neighbour was tested and the gap is named; "untested" means no study touched it. Data: "have" means in the lake today, "need" names the source.

### Crypto cross-section

| Idea | Mechanism | Best sources | Reported performance, out of sample and decay | Costs and capacity | Data | Venue | Lab status |
|---|---|---|---|---|---|---|---|
| Short-horizon cross-sectional momentum (1 to 2 weeks) | Underreaction and herding in retail-driven coins | [S1], [S3], [S7] | Strong in 2014 to 2018 [S1]; CMOM 2.1 % a week post-2020, smaller than full sample [S3]; reverses beyond 4 weeks [S7]; momentum survives mainly in larger coins but costs are heavy [S6] | Weekly turnover, high | Have | Kraken perps | Tested close: family 8 XS momentum 28d L/S -1.01 at 41 bps; M2/M4 use r1 to r112 |
| Long-horizon reversal (1 to 24 months) | Overreaction to narratives, supply overhang | [S7] | Significant reversal from 4 weeks to 2 years in 2014 to 2020 [S7]; no post-2020 test found | Low turnover | Have | Kraken perps | Close: reversal family tested 1 to 7 days only; M4 has r112 |
| Size | Small coins illiquid and risky | [S1], [S3], [S6] | Weakens post-2020 (t -1.7) [S3]; comes from micro caps of negligible size [S6] | Untradeable at the small end | Have | None in practice | Close: adv28 in M2/M4; not worth a study |
| Value: price to new addresses | Network adoption is the fundamental | [S2], [S3] | CVALUE -2.3 % a week, post-2020 t -2.3 [S3]; new-user growth explains about 8 % of returns, priced in the same week [S3] | Weekly | Need on-chain addresses (Coin Metrics community [S60], partial coverage) | Kraken perps, Alpaca for the long leg | Untested |
| MVRV / NVT timing of BTC | Holders' unrealized profit marks tops | Practitioner notes; Vaasa thesis | No peer-reviewed out-of-sample test found; three cycles only | Low | Need (Coin Metrics community, if free) | Alpaca | Untested; low prior |
| Liquidity-provision reversal in low-volume pairs | Reversal is pay for absorbing order flow | [S8] | Reversal returns concentrate in low-volume pairs, 2017 to 2022 [S8] | Highest exactly where costs are highest | Have | Kraken perps | Close: reversal family failed; M4 has amihud28, qv_shock |
| Lottery / MAX | Gamblers overpay for skew | [S9], [S10] | Low-MAX beats high-MAX by 1.5 % a week [S9]; another paper finds the opposite sign (MAX momentum) [S10] | Weekly | Have | Kraken perps | Tested inside M4 (max28, skew28: calm beats wild) |
| Low vol, low IVOL, beta | Leverage-constrained and lottery demand | Lab families; [S27] | Lab: L/S OOS 2.11 / 1.91, in-sample 0.54 | Short leg pays funding | Have | Kraken perps (now) | Tested: `family_lowvol`, M4, `m4_residual` pass |
| Aggregate technical signal (CTREND) | Many weak price and volume signals combined | [S5] | Survives costs, holds in big liquid coins and subperiods, 2015 to 2022 [S5] | Weekly | Have | Kraken perps | Tested close: M2/M4 with 51 features; long-only dead, L/S signal real |
| Factor momentum | Factor returns autocorrelate | [S4] | Holds across subperiods but comes mainly from size and volatility factors [S4] | Monthly | Have (lab factor returns) | Kraken perps | Untested; cheap follow-up to candidate 1 |
| Same-weekday cross-sectional seasonality | Recurring weekday flows | [S64] | 151 coins, 2016 to 2019 only | Daily | Have | Kraken perps | Untested; family 5 failed for BTC/ETH calendar effects |
| Search attention | Attention-induced price pressure | [S2], [S11] | Abnormal Google search predicts higher returns then partial reversal [S11] | Weekly | Need (Google Trends, unofficial, rate limited) | Alpaca / Kraken | Close: `memecoins` volume and trade-count surges pay only in 2024 |
| Developer activity | Code work proxies fundamentals | [S63] | Mostly correlation and co-movement evidence; no clean out-of-sample return test | Low | Need (GitHub API) | Kraken perps | Untested; low prior |
| Token unlocks and supply inflation | Insiders sell into unlocks | [S14], [S15] | 90 % of 16,000 unlocks show negative pressure from 30 days before to 14 after, team unlocks worst, ETH-relative (market maker's note) [S14]; inflation vs returns weak, p 0.25 [S15] | Event shorts; borrow via perps | Need unlock calendar (DefiLlama emissions, may be Pro [S61]) | Kraken perps (short) | Untested |
| Exchange listings | Demand shock on access | Lab | Lab: every cell loses vs BTC; the pop comes at the announcement | | Have | | Tested: `listings` |
| Delistings and monitoring tags | Forced selling, lost access | News only | No controlled study found | Event | Have the delisted panel; need announcement times | Kraken perps (short) | Untested; see O3 |
| Funding carry, cross-sectional | Crowded leverage pays funding and underperforms | [S12], [S13], [S68] | No published cross-sectional carry book found; a 10-perp post-mortem is negative [S68]; carry decays after 2024 [S3] | Funding both sides | Have | Kraken perps | Untested standalone (M4 uses fund1, fund7, basis as features) |
| Basis momentum (change in funding / basis) | Slow-moving speculative pressure | Boons and Prado for commodities [S62] | Strong in commodity futures; no crypto test found | Weekly | Have | Kraken perps | Untested; one extra signal in candidate 1 |

### Crypto time series and carry

| Idea | Mechanism | Best sources | Reported performance, out of sample and decay | Costs and capacity | Data | Venue | Lab status |
|---|---|---|---|---|---|---|---|
| Time-series momentum, long-only | Trend persistence | [S2], [S25] | Strong in crypto [S2] | Low | Have | Alpaca | Tested: `tsmom`, `momentum2`, `tsmom_tranches` (paper books) |
| Time-series momentum with shorts | Same, symmetric | [S25], [S26] | Symmetric in futures; crypto short side untested in the literature found | Funding on shorts | Have | Kraken perps | Untested (candidate 5) |
| Cash-and-carry (spot long, perp short) | Leverage demand vs scarce arbitrage capital | [S12], [S3] | Sharpe 6.45 (2020 to 2025), 4.06 from 2024, negative in 2025 [S3] | Two venues, margin | Have | Alpaca spot + Kraken perp | Tested: `carry` (1.4 % a year from 2024) |
| Conditional perp arbitrage outside no-arbitrage bounds | Deviations beyond cost bounds mean-revert | [S13] | Large Sharpe even at Binance's highest fees; deviations shrink over time [S13] | One-sided here (no spot short) | Have Binance; need Kraken funding history | Alpaca + Kraken | Close: `carry` was unconditional; see O7 |
| Options volatility risk premium | Insurance demand | [S16], [S17] | Positive, larger in calm regimes [S17] | Option spreads | DVOL have; option history only since 2026-10-15 | Alpaca paper options (IBIT) | Untested (candidate 9) |
| Risk reversal / skew as a predictor | Hedging pressure | [S18] | Significant 2021 to 2025, weakened after early 2024 [S18] | Daily | Skew collected since 2026-10, no history | Alpaca | Untestable now |
| DVOL level timing | Fear | Lab | Lab: fails as an overlay | | Have | | Tested: `flow_overlays` |
| Weekend, weekday, turn of month | Flow calendars | Lab | 1 of 66 effects survives BH and vanishes | | Have | | Tested: family 5 |
| Hour of day (BTC 21 to 23 UTC) | Exchange-closure liquidity | [S20] | 40.6 % a year 2015 to 2023 in a vendor backtest, weak 2022 to 2023 [S20] | Daily round trips | Have | | Tested: `fast_maker` hour-of-day (Sharpe -17 to -22) |
| Pre-holiday drift in BTC | Holiday sentiment | [S21] | Vendor backtest only | Few trades | Have | Alpaca | Untested; low prior, cheap |
| Intraday time-series momentum | First half-hour predicts last | [S19] | In-sample predictability, strongest in high-volume sessions [S19] | Intraday round trips | Have | | Tested close: `fast_strategies` (1h fails) |
| BTC leads small alts | Slow information diffusion | Robot Wealth, Kurihara and Matsumoto (2026) | Small caps respond with delay at high frequency; hourly forecasting mostly no better than a random walk | Needs very low fees | Have | Kraken perps (cheap) | Untested specifically; `fast_maker` says sub-48-hour holds earn a median -15 bps gross |
| Session decomposition (US vs Asia hours) | ETF flows moved volume to US hours | [S67] | US share of variance 24 % to 33 % after the ETFs; Asia still drives the biggest weeks [S67] | Daily | Have | | Tested close: `fast_maker` |
| Stablecoin issuance | Fresh dollars buy coins | [S22] | Contested; 2017 to 2018 sample | | Have | | Tested: `flow_overlays` |
| Coinbase and Korean premium (market level) | Regional demand | [S24] | Korean premium peaks with alt tops (blog) [S24] | | Have | | Tested: `flow_overlays`; per coin see O4 |
| Funding and OI timing | Leverage cycle | Lab | Fails | | Have | | Tested: family 6, `flow_overlays` |
| Volatility-managed exposure | Vol is predictable, returns are not | [S56] | Lab: barely moves Sharpe | | Have | | Tested: `vol_managed` |

### Market-neutral and statistical arbitrage

| Idea | Mechanism | Best sources | Reported performance, out of sample and decay | Costs and capacity | Data | Venue | Lab status |
|---|---|---|---|---|---|---|---|
| Crypto pairs (distance, cointegration) | Temporary divergence of related coins | [S23] | Mostly unprofitable after costs, underperforms buy and hold [S23] | High | Have | Kraken perps | Tested: family 4 |
| Cross-exchange BTC spreads | Segmented fiat markets | [S3] | Implementable only across open markets, framed as risk pay [S3] | Transfers, capital controls | Partial | Not our venues | Tested: `spread` (edge 2 to 9 bps vs 50 bps fees) |
| Spot ETF vs underlying (IBIT premium) | Creation / redemption keeps it tight | arXiv 2409.00270 | Premium mostly within ±0.5 %; no predictive study found | Tiny | Need IBIT NAV | Alpaca | Untested; see O1 for the cost use |
| BTC treasury companies vs BTC | Equity premium to held coins swings with sentiment | None academic | None found | Borrow on MSTR | EDGAR 8-K holdings + Alpaca + Binance | Alpaca (short stock possible) | Untested; see O2 |
| Equity pairs | Mean reversion of close substitutes | [S55] | Profitable 1962 to 2002, declining after | Medium | Have S&P 500 | Alpaca | Untested; low prior |

### Equities and ETFs

| Idea | Mechanism | Best sources | Reported performance, out of sample and decay | Costs and capacity | Data | Venue | Lab status |
|---|---|---|---|---|---|---|---|
| Managed-futures replication with ETFs | Trend persistence across asset classes | [S25], [S26] | Profitable across 110 years; weaker after 2009 [S26] | Low | Have | Alpaca | Tested: `etf_trend` (0.68 vs SPY 0.88) |
| Dual momentum | Relative plus absolute momentum | [S57] | Practitioner backtests | Low | Have | Alpaca | Tested: `etf_trend` |
| Low vol / defensive (long-only) | Leverage constraints | [S27] | Robust | Low | Have | Alpaca | Tested close: `equities_ranking` low-vol baseline (Sharpe 0.76 to 0.83, below index return) |
| Betting against beta (long/short) | Leverage constraints | [S27], [S28] | Much of BAB is equal-weighted micro caps; after costs it loads on profitability and investment [S28] | Shorting, rebalance | Have | Alpaca | Untested as L/S; low priority |
| Gross profitability, quality | Profitable firms underpriced | [S29], [S30] | Replicates [S33] | Low | Need XBRL | Alpaca | Untested (candidate 7) |
| Net share issuance | Managers time issues and buybacks | [S31] | Replicates; US anomalies lose about a third after publication [S32], decay is US-only in 39 markets [S70] | Low | Need XBRL | Alpaca | Untested (candidate 7) |
| Residual momentum | Momentum net of factor exposure crashes less | [S52] | Higher risk-adjusted return than raw momentum [S52] | Monthly | Have | Alpaca | Close: M9 used raw momentum (12-1 baseline IR 0.20) |
| Short-term reversal (industry-relative, announcement-adjusted) | Pay for liquidity provision | [S51] | Strongest in volatile, low-turnover stocks [S51]; raw large-cap reversal largely gone | Weekly turnover | Have | Alpaca | Close: 1-week reversal was an M9 feature; not as an L/S book |
| Same-month seasonality | Recurring seasonal factor exposure | [S34], [S35] | About 13 % a year [S35]; replicates [S33] | Monthly turnover | Have | Alpaca | Untested (candidate 6) |
| Turn of month, pre-holiday | Month-end flows | [S53], [S54] | Contested after 1990 [S54] | Low | Have | Alpaca | Close: `overnight` used it only as a night filter (candidate 8) |
| Pre-FOMC drift | Uncertainty resolution | [S47], [S46] | 49 bps in the 24 hours before (1994 to 2011) [S47]; gone after 2015 [S46] | Low | Have | Alpaca | Untested; dead by the literature |
| Overnight drift | Institutional vs retail clientele | [S48] | Strong before costs | Spread twice a day | Have | Alpaca | Tested: `overnight` |
| Intraday momentum, leveraged-ETF rebalancing | Hedging flows at the close | [S49], [S50] | Leveraged-ETF effects weakened over time [S49] | Intraday | Have | Alpaca | Tested close: `intraday_equities` (end-of-day momentum about -2 after costs) |
| VIX term structure | Insurance premium in VIX futures | [S43], [S44], [S45] | 0.73 Sharpe 2016 to 2026 in a public backtest [S45]; catastrophic days (2018-02-05) | ETP spreads, tail | Need Yahoo VIX symbols | Alpaca | Untested (candidate 2) |
| Index additions (announcement) | Index-fund demand | [S42] | Faded from +7.4 % (1990s) to under 1 % [S42] | | Have | Alpaca | Untested; dead by the literature |
| Index deletions (post-removal) | Forced selling at low valuations | [S41] | Deletions beat additions by about 22 % in the year after [S41] | Few events | Have | Alpaca | Untested (candidate 4) |
| Earnings announcement premium | Attention, risk at scheduled news | [S36], [S37], [S38] | 7 % a year US; 8 % a year in 46 countries; smaller on predicted dates [S37] | Weekly | Have (EDGAR events) | Alpaca | Untested (candidate 3) |
| Post-earnings drift | Underreaction | Lab | Lab: 0.54 vs 0.78 | | Have | | Tested: `equities_training` |
| 52-week high | Anchoring | Lab | Lab: loses | | Have | | Tested: `equities_ranking`, `equities_training` |
| Sector rotation / industry momentum | Slow diffusion | Lab | Lab: 0.59 vs SPY 0.92 | | Have | | Tested: `equities_training` |
| Insider purchases | Private information | [S39], [S40] | 82 bps a month for opportunistic insiders [S39] | Monthly | Need SEC Form 345 files | Alpaca | Untested (candidate 10) |
| Option-implied signals (skew, put-call parity) | Informed option trading | [S65] | Smirk predicts underperformance [S65] | | Need option history (Alpaca only from 2024) | Alpaca | Untestable historically; forward only |
| Equity index put-write | Variance risk premium | CBOE PUT index | Long record | Option spreads | Need option quotes | Alpaca paper options | Untested; same machinery as candidate 9 |

## Original ideas (combinations of our data the literature does not cover)

### O1. Route the crypto books' BTC and ETH legs through spot ETFs

**Mechanism.** Alpaca charges about 25 bps taker on spot crypto; IBIT, FBTC, ETHA and the newer single-coin ETFs trade commission free with a cent-wide spread and cost about 0.25 % a year to hold. The books turn over 5 to 13 times a year, and BTC and ETH are a large share of breakout_top10's weight (`genome_gates`: 91 % of the genome's weight in six large coins). Filling those legs at the next US open instead of 04:15 UTC costs a few hours of delay, which `breakout_study` and `alpaca_universe` showed the books tolerate (robust to a day late). **Test.** Replay breakout_top10, tsmom_top20 and tsmom_tranches with every leg that has a US spot ETF filled at the next 09:35 ET Alpaca bar of the ETF (5-minute bars, 2 bps a side plus the expense ratio daily), against the same books at 35 bps at 04:15 UTC, from 2024-01-11 (ETF launch) or each ETF's launch. **Pass.** Sharpe difference above 0 with a bootstrap band above 0, tracking error of the ETF leg against spot below 2 % a year, no year worse. **Kill.** Difference at or below 0. Note: a weekend move leaves the ETF leg stale until Monday; the test includes that.

### O2. Treasury-company premium reversion

**Mechanism.** Companies that hold BTC as a treasury (MSTR first, then miners and others) trade at a multiple of their coins' value (mNAV) that swings with retail sentiment and with how cheaply they can issue equity. Their 8-K filings report holdings, so the multiple is computable daily from EDGAR, Binance and Alpaca. **Test.** Build mNAV for every US-listed company whose 8-Ks report BTC holdings; signal = mNAV z-score over a trailing year. Long-only form: hold MSTR instead of BTC when the z-score is below -1, BTC otherwise; long/short form: short the stock against an equal-dollar BTC long when the z-score is above +1 (Alpaca allows the stock short, borrow permitting). In-sample to 2023, out of sample from 2024. **Pass.** Long/short leg Sharpe above 0.5 at 10 bps plus a 3 % a year borrow cost, positive in 2 of 3 out-of-sample years; long-only form beats BTC held. **Kill.** The long/short leg negative out of sample. Risk: dilution and conversion events move mNAV mechanically; treat the filing date as the information date.

### O3. A delisting hazard model on the survivorship-free panel

**Mechanism.** Binance delists coins whose volume, liquidity and project health decay; the lake holds every delisted pair with its last trading day, so the event label exists without scraping announcements. Prices of soon-delisted coins likely drift down before the announcement and collapse after it. **Test.** Label: delisted from Binance spot within the next 60 days. Features known at each day: 28 and 90-day volume trend, Amihud, age, drawdown from the high, perp listed or removed, funding, OI change. LightGBM with quarterly purged walk-forward against a baseline of "bottom decile of 90-day volume". Uses: (a) exclude the top 5 % hazard from the long books; (b) short the top 5 % on Kraken perps where listed. **Pass.** Out-of-sample AUC at least 0.05 above the baseline with a bootstrap band above 0, and (a) improves a long book by the six gates, or (b) the short book earns above 0 at 41 bps after funding. **Kill.** AUC no better than the volume baseline.

### O4. Per-coin Korean premium as a cross-sectional signal

**Mechanism.** Korean retail concentrates on altcoins and its mania marks alt tops [S24]; capital controls keep the premium from closing. The lab tested the market-level premium (`flow_overlays`), not the cross-section. A coin whose Upbit price sits far above its Binance price is being bought by the most speculative marginal buyer and should underperform over the next 1 to 4 weeks. **Test.** Collect Upbit daily KRW candles for every KRW market (public, keyless; need), convert with the lake's USD/KRW, premium per coin minus the BTC premium. Rank IC against 7 and 28-day forward returns on the coins listed on both, quarterly walk-forward from 2021; book: short the top quintile on Kraken perps against the bottom quintile. **Pass.** Out-of-sample IC t above 2 (non-overlapping weeks) and the residual against low vol and BTC (frozen betas) above 0. **Kill.** IC t below 1. Risk: deposit and withdrawal suspensions create premiums that are about plumbing, not demand; drop coins with suspended wallets where the Upbit API flags them.

### O5. Deleveraging flush as a long entry

**Mechanism.** When OI collapses alongside price and the retail long/short ratio, forced sellers have finished and the funding market resets; the price impact of forced selling should partly reverse. The lab tested these metrics only as reasons to cut exposure (`flow_overlays`), never as an entry. **Test.** Event: aggregate OI over the top 20 perps down at least X % over 3 days, BTC down, long/short ratio down (X fixed in sample from {15, 25 %}). Action: buy BTC (and an equal-weight top-5 basket) on Alpaca at the next close, hold {7, 14} days. Baseline: random entries in the same BTC regime and same calendar months, many draws. Binance metrics from 2021, in sample to 2023. **Pass.** Out-of-sample mean excess over the random-entry baseline above 0 with an event-bootstrap band above 0, at 35 bps. **Kill.** Below the random baseline. Risk: few events (perhaps 10 to 20 out of sample); that is the honest size of the evidence.

### O6. Overnight BTC moves and US crypto equities

**Mechanism.** COIN, MSTR, miners and the spot ETFs close at 16:00 ET while BTC keeps trading. The open gap prices the overnight BTC move, but crypto-equity holders are a different clientele; if the gap underreacts, the residual drifts during the session. **Test.** Regress each stock's open-to-close return (09:35 to 15:55, Alpaca 5-minute bars from 2016) on BTC's US-close-to-US-open return net of the stock's open gap times its beta. Trade the sign of the predicted residual when its magnitude exceeds the in-sample cost threshold (3 to 5 bps a side). In sample 2016 to 2022, out of sample from 2023. **Pass.** Out-of-sample slope t above 2 and the rule positive after costs with the entry a bar late. **Kill.** Slope t below 1. Prior: `intraday_equities` says most intraday rules die on spread; this one has an information source the others lacked.

### O7. Kraken against Binance funding divergence

**Mechanism.** Funding is set venue by venue. When Kraken's funding on a coin sits far above Binance's, Kraken's longs are paying for leverage that is cheaper elsewhere; a short Kraken perp hedged with an Alpaca spot long collects the gap with no directional risk, and only needs a long spot leg, which Alpaca has. **Test.** Kraken Futures publishes historical funding rates through its public API (need: collect for every perp that has an Alpaca spot pair). Hourly series aligned with Binance funding; entry when Kraken funding minus Binance funding annualized exceeds the round-trip cost amortized over the expected hold (Alpaca 25 bps plus Kraken 5 bps a side), exit when it closes. **Pass.** Net carry above 5 % a year on deployed capital out of sample (2025 on) with at least 20 independent entries, worst week above -2 %. **Kill.** Fewer than 20 qualifying entries a year or net carry below 2 %. Prior: `carry` found 1.4 % a year unconditionally; this asks whether the conditional, venue-specific version is better.

### O8. Polymarket crypto price markets against DVOL

**Mechanism.** Polymarket lists "BTC above X on date" markets. Their prices imply a probability; DVOL and the spot price imply another (lognormal, with the 25-delta skew once its history exists). Two markets with different clienteles pricing the same event can disagree, and the disagreement may carry information either about BTC or about Polymarket's own bias (`polymarket` found longshots too dear in busy markets). **Test.** From the Polymarket collector, every resolved BTC and ETH threshold market since 2024 with its daily midpoint and, where recorded, the quoted spread; the DVOL-implied probability at the same time. Two questions: (a) which forecast has the lower Brier score; (b) does the sign of (Polymarket minus DVOL) predict BTC's return to the market's end date. **Pass.** (a) a Brier difference with a bootstrap band excluding 0; (b) slope t above 2 out of sample from 2026. **Kill.** Neither. Read-only either way: a pass on (b) is a BTC signal for Alpaca; a pass on (a) is information only, since the lab does not trade Polymarket.

### O9. pump.fun activity as a memecoin sentiment gauge

**Mechanism.** The rate of pump.fun creations, completions and SOL volume measures retail speculative appetite in real time, and the six Alpaca memecoins are the listed end of the same appetite. **Test.** Daily counts from the `pumpfun_rt` collector (forward only; it started this month) against next 1 and 7-day returns of DOGE, SHIB, PEPE, BONK, WIF and TRUMP, and as a gate on `memes_rotation`. Pre-register now, judge after 180 days. **Pass.** Slope t above 2 on non-overlapping weeks and the gated rotation beats the ungated one in the forward record. **Kill.** t below 1 at 180 days. History beyond our collector would need a paid or Dune source; not proposed.

## Sources

- [S1] Liu, Tsyvinski, Wu (2022), Common Risk Factors in Cryptocurrency, Journal of Finance. https://papers.ssrn.com/abstract=3379131
- [S2] Liu, Tsyvinski (2021), Risks and Returns of Cryptocurrency, Review of Financial Studies. https://papers.ssrn.com/abstract=3226806
- [S3] Borri, Liu, Tsyvinski, Wu (2025, rev. 2026), Cryptocurrency as an Investable Asset Class: Coming of Age, arXiv 2510.14435. https://arxiv.org/abs/2510.14435
- [S4] Fieberg, Liedtke, Metko, Zaremba (2023), Cryptocurrency factor momentum, Quantitative Finance 23(12). https://ideas.repec.org/a/taf/quantf/v23y2023i12p1853-1869.html
- [S5] Fieberg, Liedtke, Poddig, Walker, Zaremba (2025), A Trend Factor for the Cross-Section of Cryptocurrency Returns, JFQA. https://www.cambridge.org/core/journals/journal-of-financial-and-quantitative-analysis/article/trend-factor-for-the-cross-section-of-cryptocurrency-returns/4C1509ACBA33D5DCAF0AC24379148178
- [S6] Cryptocurrency anomalies and economic constraints (2024), International Review of Financial Analysis. https://www.sciencedirect.com/science/article/abs/pii/S1057521924001509
- [S7] Dobrynskaya, Cryptocurrency momentum and reversal (HSE summary). https://www.hse.ru/en/news/research/559533243.html
- [S8] Bianchi, Babiak, Dickerson (2022), Trading volume and liquidity provision in cryptocurrency markets, Journal of Banking and Finance 142. https://ideas.repec.org/a/eee/jbfina/v142y2022ics0378426622001418.html
- [S9] Grobys, Junttila (2021), Speculation and lottery-like demand in cryptocurrency markets, JIFMIM 74. https://osuva.uwasa.fi/handle/11111/1871
- [S10] Li, Urquhart, Wang, Zhang (2021), MAX momentum in cryptocurrency markets, IRFA 77. https://ideas.repec.org/a/eee/finana/v77y2021ics1057521921001630.html
- [S11] Hoang, Vo (2024), Google search and cross-section of cryptocurrency returns and trading activities, JBEF 44. https://ideas.repec.org/a/eee/beexfi/v44y2024ics2214635024001060.html
- [S12] Schmeling, Schrimpf, Todorov (2023), Crypto carry, BIS Working Paper 1087. https://www.bis.org/publ/work1087.pdf
- [S13] He, Manela, Ross, von Wachter, Fundamentals of Perpetual Futures, arXiv 2212.06888. https://arxiv.org/abs/2212.06888
- [S14] Keyrock, From Locked to Liquidity: What 16,000+ Token Unlocks Teach Us. https://keyrock.com/from-locked-to-liquidity-what-16000-token-unlocks-teach-us/
- [S15] Crypto.com Research, Token inflation. https://crypto.com/us/research/token-inflation
- [S16] Alexander, Imeraj, The Bitcoin VIX and its variance risk premium. https://sro.sussex.ac.uk/id/eprint/91094/
- [S17] Risk Premia in the Bitcoin Market, arXiv 2410.15195. https://arxiv.org/abs/2410.15195
- [S18] Neo (2026), dissertation on Deribit risk reversals and Bitcoin returns, Singapore Management University. https://ink.library.smu.edu.sg/etd_coll/887
- [S19] Shen, Urquhart, Wang (2022), Bitcoin intraday time series momentum, Financial Review 57(2). https://research.birmingham.ac.uk/en/publications/bitcoin-intraday-time-series-momentum/
- [S20] Quantpedia (2023), The Seasonality of Bitcoin. https://quantpedia.com/the-seasonality-of-bitcoin/
- [S21] Quantpedia, Surprisingly Profitable Pre-Holiday Drift Signal for Bitcoin. https://quantpedia.com/surprisingly-profitable-pre-holiday-drift-signal-for-bitcoin/
- [S22] Griffin, Shams (2020), Is Bitcoin Really Untethered?, Journal of Finance. https://doi.org/10.1111/jofi.12903
- [S23] Fil, Kristoufek (2020), Pairs Trading in Cryptocurrency Markets, IEEE Access. https://ieeexplore.ieee.org/document/9200323
- [S24] 4pillars Research, Koreans buy the alt top, not the Bitcoin top. https://research.4pillars.io/en/data/content/koreans-buy-the-alt-top-not-the-bitcoin-top
- [S25] Moskowitz, Ooi, Pedersen (2012), Time series momentum, JFE 104(2). https://doi.org/10.1016/j.jfineco.2011.11.003
- [S26] Hurst, Ooi, Pedersen (2017), A Century of Evidence on Trend-Following Investing, AQR. https://www.aqr.com/Insights/Research/Journal-Article/A-Century-of-Evidence-on-Trend-Following-Investing
- [S27] Frazzini, Pedersen (2014), Betting against beta, JFE 111(1). https://doi.org/10.1016/j.jfineco.2013.10.005
- [S28] Novy-Marx, Velikov (2022), Betting against betting against beta, JFE. https://mysimon.rochester.edu/novy-marx/research/BABAB.pdf
- [S29] Novy-Marx (2013), The other side of value: The gross profitability premium, JFE 108(1). https://doi.org/10.1016/j.jfineco.2013.01.003
- [S30] Asness, Frazzini, Pedersen (2019), Quality minus junk, Review of Accounting Studies 24. https://doi.org/10.1007/s11142-018-9470-2
- [S31] Pontiff, Woodgate (2008), Share issuance and cross-sectional returns, Journal of Finance 63(2). https://doi.org/10.1111/j.1540-6261.2008.01324.x
- [S32] McLean, Pontiff (2016), Does academic research destroy stock return predictability?, Journal of Finance 71(1). https://doi.org/10.1111/jofi.12365
- [S33] Jensen, Kelly, Pedersen (2023), Is There a Replication Crisis in Finance?, Journal of Finance 78(5). https://www.nber.org/papers/w28432
- [S34] Heston, Sadka (2008), Seasonality in the cross-section of stock returns, JFE 87(2). https://doi.org/10.1016/j.jfineco.2007.02.003
- [S35] Keloharju, Linnainmaa, Nyberg (2016), Return seasonalities, Journal of Finance. https://www.nber.org/papers/w20815
- [S36] Frazzini, Lamont (2007), The earnings announcement premium and trading volume, NBER w13090. https://www.nber.org/papers/w13090
- [S37] Cohen, Dey, Lys, Sunder (2007), Earnings announcement premia and the limits to arbitrage, JAE. https://archive.nyu.edu/handle/2451/27555
- [S38] Barber, De George, Lehavy, Trueman (2013), The earnings announcement premium around the globe, JFE. https://en-coller.tau.ac.il/sites/nihul_en.tau.ac.il/files/media_server/Recanati/management/seminars/account/barber.pdf
- [S39] Cohen, Malloy, Pomorski (2012), Decoding inside information, Journal of Finance 67(3). https://doi.org/10.1111/j.1540-6261.2012.01740.x
- [S40] SEC DERA, Insider Transactions Data Sets. https://www.sec.gov/dera/data/form-345
- [S41] Arnott, Brightman, Kalesnik, Wu (2023), Earning Alpha by Avoiding the Index Rebalancing Crowd, Financial Analysts Journal. https://rpc.cfainstitute.org/research/financial-analysts-journal/2023/earning-alpha-by-avoiding-the-index-rebalancing-crowd
- [S42] Greenwood, Sammon (2022, JF 2025), The Disappearing Index Effect, NBER w30748. https://www.nber.org/papers/w30748
- [S43] Simon, Campasano, The VIX Futures Basis: Evidence and Trading Strategies (EFMA 2013 version). https://www.efmaefm.org/0EFMAMEETINGS/EFMA%20ANNUAL%20MEETINGS/2013-Reading/papers/EFMA2013_0164_fullpaper.pdf
- [S44] Cooper (2013), Easy Volatility Investing (CXO Advisory summary). https://www.cxoadvisory.com/volatility-effects/volatility-trading-strategies/
- [S45] QuantConnect, Exploiting Term Structure of VIX Futures (after Zarattini, Mele, Aziz 2025). https://www.quantconnect.com/research/15261/exploiting-term-structure-of-vix-futures/
- [S46] Kurov, Wolfe, Gilbert (2021), The disappearing pre-FOMC announcement drift, Finance Research Letters 40. https://doi.org/10.1016/j.frl.2020.101781
- [S47] Lucca, Moench (2015), The pre-FOMC announcement drift, Journal of Finance 70(1). https://doi.org/10.1111/jofi.12196
- [S48] Lou, Polk, Skouras (2019), A tug of war: Overnight versus intraday expected returns, JFE. https://doi.org/10.1016/j.jfineco.2019.03.011
- [S49] Barbon, Beckmeyer, Buraschi, Moerke, Liquidity Provision to Leveraged ETFs and Equity Options Rebalancing Flows, SFI 22-40. https://papers.ssrn.com/abstract=3925725
- [S50] Gao, Han, Li, Zhou (2018), Market intraday momentum, JFE. https://doi.org/10.1016/j.jfineco.2018.05.009
- [S51] Dai, Medhat, Novy-Marx, Rizova (2024), Reversals and the Returns to Liquidity Provision, Financial Analysts Journal. https://rpc.cfainstitute.org/research/financial-analysts-journal/2024/reversals-and-the-returns-to-liquidity-provision
- [S52] Blitz, Huij, Martens (2011), Residual momentum, Journal of Empirical Finance 18(3). https://doi.org/10.1016/j.jempfin.2011.01.003
- [S53] Quantpedia, Turn of the Month in Equity Indexes. https://quantpedia.com/strategies/turn-of-the-month-in-equity-indexes
- [S54] Maberly, Waggoner (2000), Closing the question on the continuation of turn-of-the-month effects, Atlanta Fed WP 2000-11. https://www.atlantafed.org/research/publications/wp/2000/11.aspx
- [S55] Gatev, Goetzmann, Rouwenhorst (2006), Pairs trading, Review of Financial Studies 19(3). https://doi.org/10.1093/rfs/hhj020
- [S56] Moreira, Muir (2017), Volatility-managed portfolios, Journal of Finance 72(4). https://doi.org/10.1111/jofi.12513
- [S57] Antonacci, Risk Premia Harvesting Through Dual Momentum, SSRN. https://papers.ssrn.com/abstract=2042750
- [S58] Alpaca, Multi-leg (Level 3) options trading in paper. https://docs.alpaca.markets/us/changelog/multi-leg-level-3-options-trading-in-paper
- [S59] Kraken, EEA perpetual futures fee waiver. https://www.kraken.com/pro/futures-eea-fee-waiver
- [S60] Coin Metrics, Community Data. https://docs.coinmetrics.io/packages/coin-metrics-community-data
- [S61] DefiLlama, API tiers. https://docs.llama.fi/pro-api
- [S62] Boons, Prado (2019), Basis-Momentum, Journal of Finance. https://doi.org/10.1111/jofi.12738
- [S63] From code to market: Network of developers and correlated returns of cryptocurrencies, arXiv 2004.07290. https://arxiv.org/abs/2004.07290
- [S64] Seasonality in the Cross-Section of Cryptocurrency Returns (2020), Finance Research Letters. https://www.sciencedirect.com/science/article/pii/S154461232030235X
- [S65] Xing, Zhang, Zhao (2010), What does the individual option volatility smirk tell us about future equity returns?, JFQA. https://doi.org/10.1017/S0022109010000220
- [S67] ParaFi (2026), Non-U.S. Hours Still Drive Bitcoin's Biggest Moves. https://parafi.com/signals/bitcoin-biggest-moves-market-hours
- [S68] Fayez Junior (2026), Failure of Cross-Sectional Alpha Screening on Cryptocurrency Perpetual Futures, SSRN. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6701738
- [S70] Jacobs, Müller (2020), Anomalies across the globe: Once public, no longer existent?, JFE. https://hemf.wiwi.uni-due.de/en/research/publications/anomalies-across-the-globe-once-public-no-longer-existent-14591

## Caveats on the sources

- Several figures come from abstracts and secondary summaries, not full texts: the Keyrock unlock numbers (a market maker's own note, no stated window), the Quantpedia and QuantConnect backtests (vendor research), the 4pillars Korean-premium post and the ParaFi session study. They set priors, not pass marks.
- DOIs for the classic journal papers ([S22], [S25] to [S35], [S39], [S46] to [S48], [S50], [S52], [S55], [S56], [S62], [S65]) were given from the citation record and not each opened in this session; check before quoting a page number.
- The Kraken fee figures (5 bps taker, EEA zero-fee waiver) are from Kraken's marketing page and a secondary guide; confirm on the account before costs enter a pre-registration.
