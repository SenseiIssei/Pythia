# Cross-sectional positioning on perpetuals: pre-registration

Registered 2026-10-21 and committed before the positioning history was
downloaded and before any return below was computed. Code:
`lab.collect.um_metrics` (collector) and `lab.experiments.positioning_xs`
(written after this file). Results go to `results/positioning_xs.md`.
Nothing here may change once a result exists. Registered together with
`taker_imbalance_xs`, `hedged_breakout` and `pead_xbrl` (24 trials in all,
see "Pool").

## Question

Binance publishes, for every USD-M perpetual, how its top traders and its
takers are positioned. The lab used these numbers only as one market-wide
overlay (X6 `flow_overlays`, the all-accounts ratio on the 20 lab coins).
Across the 100 most liquid perps, does a coin whose positioning is crowded
relative to its own history do worse than one whose positioning is not,
after funding and Kraken Futures costs, out of sample from 2024, and is it
more than the low-vol book and BTC?

## Hypothesis (decided here, from the literature and the lab's record)

**Crowding, traded contrarian.** Long the least crowded, short the most
crowded. Reasons: leveraged longs in crowded coins pay to hold them and
unwind together (Brunnermeier, Nagel and Pedersen 2008 for crowded carry
trades; Schmeling, Schrimpf and Todorov 2023 for crypto, where high funding,
the price of crowded leverage, comes before lower returns); the lab's own
record points the same way: in X6 a high all-accounts long/short ratio was
the closest thing to a risk-off signal for the books, and `funding_carry`
found the high-funding (crowded) coins losing in price. The opposite case
exists for open interest (Hong and Yogo 2012: open interest growth in
commodity futures predicts higher returns, as demand that prices have not
caught up with); it is the main way this registration could be wrong, and
the information-only IC of each component shows which way each one points.

## Data

- **Positioning**: Binance's public daily metrics archive
  (`data.binance.vision/data/futures/um/daily/metrics/<SYMBOL>/`), one file
  a day per perpetual with a row every five minutes, from 2021-12-01 for most
  symbols. `lab.collect.um_metrics` keeps one row per symbol and UTC day for
  every perp that ranked among the 120 most liquid eligible perps of the
  `xs_daily` panel on any day since 2021-12-01, from 100 days before its first
  such day: open interest (contracts and USD) at the last snapshot of the
  day, and the daily mean of the log of the top traders' long/short account
  ratio, the top traders' long/short position ratio, the all-accounts ratio
  and the taker buy/sell volume ratio. Cached under
  `<data>/flow/um_metrics/`. One GET a file, at most 25 a second.
- **Prices, funding, universe**: the `xs_daily` panel as the paper job
  `paper-m4-ls` built it on 2026-10-21 (copied unchanged into a study
  folder, `PYTHIA_CACHE`), with `xs_daily.add_net_labels` unchanged. The
  coin's perp on a day is the panel's `perp` (the base's most liquid USDT
  perp that day); its metrics are that symbol's.
- Returns `R1` between consecutive entry prices (the first hourly close after
  the decision day), funding `fund_hold` paid while held: entry is the day
  after the metrics, one hour after they are complete, as every M4 book.

## The signal (known at the end of decision day d)

Per perp symbol, each of five inputs is turned into a z-score against its
own trailing 90 daily values (days d-90 to d-1, at least 60):

1. `top_acct`: mean log top-trader account ratio of day d.
2. `top_pos`: mean log top-trader position ratio of day d.
3. `taker`: mean log taker buy/sell volume ratio of day d.
4. OI growth over 3 days: log of open interest in contracts at the end of
   d over the end of d-3.
5. OI growth over 7 days: the same over 7 days.

Crowding C = the mean of the five z-scores (all five needed, each clipped at
+-5). **Score = -C**: long the lowest crowding, short the highest. Contracts,
not USD, for open interest, so a price move alone is not counted as growth.

## Books

`xs_daily.book` with `long_short=True`, unchanged: among the 100 most liquid
perps (28-day perp volume) that have a score, k long and k short, half the
capital per side, equal weight, overlapping tranches, funding paid and
received, no "no paying shorts" rule.

- k: 10 or 20.
- Hold: three overlapping 3-day tranches, or seven overlapping 7-day tranches.

## Costs (per unit of one-way turnover)

Judged **10 bps** (Kraken Futures taker plus half-spread, `perps_common`),
stress 20 bps; 2 bps (maker, an upper bound) and 41 bps (the lab's earlier
perp level) reported.

## Windows and the pick

Selection: decision days 2022-03-15 (the first with 90 days of metrics plus
the 7-day growth for most perps) to 2023-12-31. Holdout: 2024-01-01 to the
last decision day whose `fund_hold` is complete (`add_net_labels`' rule).
The pick is the book with the highest selection-window Sharpe at 10 bps of
the four.

## The residual

As `funding_carry`: the low-vol book of the pick's shape (score minus
`vol28`, same k, tranches, universe, costs and funding) and BTC (BTCUSDT's
`R1`, no costs). OLS of the pick's daily net return at 10 bps on the low-vol
book's and on BTC's, with an intercept, over the selection window; betas
frozen. In the holdout R = pick - b1 x lowvol - b2 x BTC (intercept kept).

## Trials (5)

2 sizes x 2 holds = 4 books, plus R = 5.

**Pool.** 1,353 hand trials before this registration (1,328 before the
2026-10-21 evening batch plus its 25), the factory ledger as read at run
time (600 in the committed seed, more on the server after the weekly runs),
and the 24 trials registered here (`positioning_xs` 5, `taker_imbalance_xs`
13, `hedged_breakout` 2, `pead_xbrl` 4), each study's own at its own
variance. Hand trials at the variance backed out of the published bar (377
at 2.43), as every study since C16. The next study starts from 1,377 hand
trials.

## Pass rule (all, for the pick)

1. Holdout Sharpe above 0.5 at 10 bps and above 0 at 20 bps.
2. Positive in at least 2 of 2024, 2025 and 2026.
3. One day late (the score of day d-1 used on day d) still above 0 at 10 bps.
4. R's holdout Sharpe above 0.3 at 10 bps, and the 5 % bound of a stationary
   bootstrap of R's Sharpe (mean block 20 days, 4,000 draws, seed 20261021)
   above 0.

Confirmed only with R's deflated p above 0.95 over the pool.
**Kill:** R's holdout Sharpe at or below 0.1 at 10 bps.

## If it passes

A lab paper book `positioning_xs` under `lab/paper/` in the format of
`funding_carry` (Kraken-listed perps, signed weights, marked EXPERIMENT unless
confirmed) and a job in `research/ops/jobs.yaml` added disabled, with a job
for the collector. Nothing wired into an autopilot, no engine restarted.

## Reported, not judged

All four books at 2, 10, 20, 41 bps in and out of sample, per year, drawdown,
turnover, the funding each leg paid or received, correlation with BTC; the
daily rank IC of each of the five components (with the contrarian sign) and
of the composite with the next 3 and 7 days' funding-net return, selection
and holdout, t on non-overlapping blocks; coverage (scored perps per day);
the share of the pick's names that the low-vol book also holds; the pick on
the coins Kraken Futures lists today (not survivorship-free).

## What could fool us

Crowded coins are often the hot, volatile ones, so the book can be low vol
under another name (the residual is there for that). The metrics archive
starts in December 2021, so the selection window is under two years and
holds the 2022 bear market. Binance's "top traders" are its own top 20 % by
margin balance, not a fixed group; the ratios are Binance-only and miss
other venues. The price legs use spot entry prices, as in every M4 book.
Delisted perps keep their metrics only while they traded; a perp without
metrics on a day is not scored that day, so the universe on early days is
smaller than 100.
