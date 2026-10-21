# Investor attention from Wikipedia page views: pre-registration

Registered 2026-10-21 and committed before any page view history was
downloaded and before any return below was computed. Only the article titles
and their redirect lists were looked up (MediaWiki API) to build the mapping.
Code: `lab.collect.wiki` (collector) and `lab.experiments.attention_wiki`
(written after this file). Results go to `results/attention_wiki.md`.
Nothing here may change once a result exists. Registered together with
`perps_neutral_portfolio` and `intraday_tsmom` (25 trials in all).

## Question

Does an abnormal spike in Wikipedia attention to a coin predict its next
week's return across coins (the attention literature: Da, Engelberg and Gao
2011 for stocks; for crypto, attention spikes tend to come with a run-up and
precede underperformance), and does a spike in attention to Bitcoin work as
a market-wide risk-off signal for BTC?

## Data

- **Page views**: Wikimedia REST API
  `metrics/pageviews/per-article/en.wikipedia/all-access/user/<title>/daily`,
  public and keyless, from 2015-07-01, with a descriptive User-Agent that
  names the project's public repository. Cached raw under
  `<data>/flow/wiki_pageviews.parquet` (title, day, views) by
  `lab.collect.wiki`, which also continues the series daily.
- **Mapping**: each coin to one English Wikipedia article about the coin or
  its own network, kept in `lab/collect/wiki.py` with a reason for every
  drop. A coin's attention is the sum of the views of the article and of
  every redirect to it (today's redirect list), so a renamed article keeps
  its history. Dropped: coins without an article, articles about an
  exchange or company rather than the coin (BNB to Binance, FTT to FTX, WLFI,
  PUMP), titles that resolve to something else (PEPE, FLOKI, Kusama, Elrond,
  Celestia, Injective, Optimism, the Sandbox), and LUNC (the Terra article
  stays with LUNA, both segments). About 50 coins are mapped; the most
  liquid of them (BTC, ETH, SOL, XRP, DOGE, ADA, LINK, AVAX, LTC, TRX, SHIB,
  DOT, BCH, UNI, AAVE, FIL, NEAR, POL/MATIC, TON, XLM, HBAR, ETC, ZEC, ALGO)
  cover most of the books' holdings.
- **Prices**: the sweep's survivorship-free daily panel (`fam_common`, dead
  coins included) cut at 2026-10-20, as `crypto_own`.

## The signal

Views of day d are published by the next morning, so a decision at the
close of day t uses views up to day t-1. With V7 the mean daily views over
days t-7 to t-1 and V90 the mean over the 90 days before those,

    att(t) = log((1 + V7) / (1 + V90)).

A coin is ranked on day t when it is eligible in the panel, among the 100
most liquid, its article has at least 97 days of views, V90 is at least 100
views a day, and at least 10 coins qualify that day. Higher att = worse (the
prior).

## Test (not a Sharpe trial)

Daily Spearman rank IC of att with the next 7 days' log return (a coin that
dies inside the window keeps its last close), t-statistic on
non-overlapping weekly samples. Passes with an out-of-sample t at or below
-2; killed for the cross-section with a t above -1.

## Trials (13)

1. **Long/short on perps**: every 7th day (weekday rule of `kr_premium_xs`),
   long the fifth with the lowest att and short the fifth with the highest
   among ranked coins with a live perp, half the capital per side, both legs
   perps with funding (`trend_shorts.sim`). Costs per unit of one-way
   turnover: judged 10 bps, stress 20, maker 2 reported.
2. The same decided one day late.
3. to 11. **Filter on the three Alpaca books** (`breakout_top10`,
   `tsmom_top20`, `tsmom_tranches`, coins Alpaca does not list in cash, 35
   bps): every coin in the worst third by att gets a target of 0
   (`crypto_own.filt`), plus per book the same one day late and on the
   survivorship-free twin: 3 x 3 = 9.
12. **BTC unless spike**: BTC held at full weight, cash on days when BTC's
   att is above the 80th percentile of its own trailing 365 values (at least
   180), against BTC bought and held, 35 bps.
13. **Gated BTC unless spike**: the same on top of the 200-day gate
   (`gated_btc`'s G at full weight), against gated BTC, 35 bps.

No variant is chosen; every trial is fixed here.

**Pool.** 1,328 hand trials before this registration (see
`perps_neutral_portfolio_prereg.md`), the factory ledger as read at run
time, and the 25 trials registered together.

## Windows

In sample 2020-08-01 to 2023-12-31 (reported only); out of sample
2024-01-01 to 2026-10-20.

## Pass rules (out of sample)

- **Long/short** (all): Sharpe above 0.5 at 10 bps and above 0 at 20 bps;
  positive in at least 2 of 2024, 2025, 2026; one day late above 0; the 5 %
  bound of the stationary bootstrap (block 20, 4,000 draws, seed 20261021)
  above 0.
- **Filters**: `crypto_own`'s gates 1 to 5 and 7 against the book alone
  (Sharpe and 2 of 3 years better, drawdown lower, bootstrap band of the
  difference above 0, a day late above the book, the twin at least the
  twin book, above gated BTC); gate 6 is the improvement's deflated p over
  the 13 trials at the variance of this study's improvements.
- **BTC rules**: Sharpe above the benchmark's and better in 2 of 3 years,
  drawdown not above the benchmark's, bootstrap band of the Sharpe
  difference above 0, a day late above the benchmark.

A pass on gates without deflation is experimental. Confirmed only with a
deflated p above 0.95 over the pool (and, for the filters, gate 6).

## If something passes

A lab paper book under `lab/paper/` marked EXPERIMENT and a job added
disabled; the page view collector gets an enabled daily job either way
(about 300 small requests a day, at most 5 a second). Nothing wired into an
autopilot.

## Reported, not judged

IC in sample and per year, against 28 days too; coverage (ranked coins per
year, the Alpaca coins' first ranked day); the share of book days that held
a flagged coin; the long/short's legs and funding; BTC's att over time and
the share of days flagged.

## What could fool us

Survivorship of notability: articles exist today for coins that became
famous, so the mapped set leans toward survivors; the views only exist from
the article's creation, which keeps membership point in time, but the
choice of coins is today's. The redirect list is today's. Wikipedia views
include bots that the "user" agent filter misses (a single bot can make a
spike). English Wikipedia is a narrow slice of crypto attention.
