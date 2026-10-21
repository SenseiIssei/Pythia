# VIX term-structure short-volatility sleeve (survey #2): pre-registration

Registered 2026-10-21 and committed before any number below was computed.
Drafted from candidate 2 of `proposals/2026-10-21-strategy-survey.md`; the
changes to that sketch are listed at the end. Code: `lab.experiments.vix_carry`
(written after this file). Results go to `results/vix_carry.md`. Nothing here
may change once a result exists. Registered together with `etf_routing`,
`crypto_open_gap`, `treasury_premium` and `btc_vrp` (one pool, see below).

## Question

Does holding a -0.5x short-VIX-futures product (SVXY today) only while VIX is
below VIX3M, cash otherwise, beat SPY on Sharpe with a smaller drawdown out of
sample, a window that contains February 2018 and March 2020; and does a 10 or
20 % sleeve of it next to the crypto books beat the best crypto book alone by
`book_portfolio`'s rule?

## Mechanism

VIX futures sit above expected spot VIX in contango because investors pay for
crash insurance; the futures basis predicts futures returns, not spot VIX
changes (Simon and Campasano). Backwardation (VIX above VIX3M) marks stress,
when short volatility loses. The premium is real and the tail is the risk:
the question is whether the term-structure switch steps aside early enough.

## Data

- Yahoo daily, adjusted and unadjusted: `^VIX` (from 2000), `^VIX3M` (from
  2006-07-17, formerly VXV), SVXY (from 2011-10-04), VIXY (from 2011-01-04),
  SPY, IEF. Cached under `<data>/agent-s3/yahoo/`. Data end: the last day all
  of them have, expected 2026-10-14.
- CBOE VIX futures (VX) daily settlement prices per contract, public CSVs
  (`cdn.cboe.com`, the archive files `CFE_<month><yy>_VX.csv` and the newer
  `VX/VX_<expiry>.csv`), cached under `<data>/agent-s3/vx/`, to rebuild the
  S&P 500 VIX Short-Term Futures Index (excess return) before SVXY existed.

## The instrument, one honest series from 2006

SVXY was -1x the short-term futures index until the close of 2018-02-27 and
-0.5x from 2018-02-28. Every period is put on the -0.5x basis of today's
product (expense ratio f = 0.95 % a year, 252 days):

1. **From 2018-02-28:** SVXY's own adjusted close-to-close return.
2. **2011-10-05 to 2018-02-27:** a -0.5x product built from SVXY's -1x
   returns: r = 0.5 x (r_SVXY + f/252) - f/252.
3. **Before 2011-10-05:** -0.5 x the rebuilt index's daily return - f/252.

The rebuilt index follows S&P's methodology: weights on the first and second
VX contracts roll linearly over the roll period (from the Tuesday before a
monthly settlement Wednesday to the Tuesday before the next), the daily
return is the old weights applied to today's against yesterday's settlements.
Contracts quoted on the old 10x scale (before 2007-03-26) are divided by 10.

**Checks, fixed now.** The rebuilt index must correlate above 0.95 with
VIXY's daily returns over 2011-2026 and with -SVXY's over 2011-10 to
2018-02-27. The leverage change is verified in the data: the ratio of SVXY's
daily return to the rebuilt index's must be near -1 before 2018-02-28 and near
-0.5 after (median over each side's 60 days). If the rebuild fails its
correlation check, the in-sample window starts 2011-10-05 instead and the
report says so.

## Rules (decided at the close of day t from `^VIX` and `^VIX3M`)

Ratio q_t = VIX_t / VIX3M_t. Entry conditions (on = hold, off = cash):

- **E1** q_t < 1.00
- **E2** q_t < 0.95
- **E3** q_t below its own 60-session mean (through t)

Sizing while on:

- **S1** fixed: weight 1
- **S2** inverse vol: weight min(1, 20 % / sigma_t), sigma_t the 20-session
  realised volatility (x sqrt 252) of the instrument series through t

**Fill.** The trade happens at the close of day t+1 (the VIX close is 16:15,
the ETF's 16:00, so trading at the close of t would look 15 minutes ahead);
the position earns from the close of t+1. "A day late" = the close of t+2.
Also reported, not judged: the open of t+1 (SVXY opens exist from 2011-10).
Cash earns nothing.

**Costs.** 3 bps a side plus a modelled 10 bps of ETP spread: 13 bps per unit
of turnover on every trade (switches and resizing). Stress: 26 bps.

## Windows

In sample 2007-01-01 to 2017-12-31 (the 60-session mean and the 20-session
vol need 2006's second half), out of sample 2018-01-01 to the data end. The
out-of-sample window contains 2018-02-05 (VIX doubled in a day; the curve was
in contango at the prior close) and March 2020.

## Trials (8)

E1 to E3 x S1, S2 = 6 standalone trials; the in-sample pick (best in-sample
Sharpe at 13 bps) is the one judged. Plus the sleeve at 10 % and at 20 % = 2.

## Benchmarks

SPY bought and held; 60/40 SPY/IEF rebalanced monthly (each at 2 bps a
side); the instrument held always (the unconditional premium).

## Pass rule, standalone (the pick, out of sample, at 13 bps)

1. Sharpe (x sqrt 252) above SPY's;
2. maximum drawdown below SPY's;
3. positive in at least 6 of the 9 years 2018 to 2026 (2026 to date);
4. Sharpe still above 0 a day late;
5. bootstrap 5 % bound of Sharpe(pick) - Sharpe(SPY) above 0 (stationary,
   mean block 20 days, 4,000 draws, seed 20261021).

Confirmed only with deflated p above 0.95 over the pool.

## Kill rule

A single-day loss larger than 30 % of the sleeve anywhere in the
out-of-sample path, or an out-of-sample Sharpe below 60/40's. A killed rule
is never proposed as a book, experimental or not.

## Sleeve (book_portfolio's rule)

The crypto side is `book_portfolio`'s equal weight of the four crypto books
as they run on Alpaca (breakout_top10, tsmom_top20, tsmom_tranches,
tsmom_regime; coins Alpaca does not list in cash; 35 bps), rebuilt with that
study's code on the panel cut at the data end. The sleeve is the standalone
pick at 10 % or 20 % of capital, the crypto mix the rest; returns on the
session's UTC date, zero on days without a session; drift traded back daily at
35 bps (crypto) and 13 bps (sleeve). Out of sample 2024-01-01 to the data end,
on 365 days. The yardstick is the best single crypto book out of sample
(chosen after the fact, as in `book_portfolio`). A sleeve passes when:

1. Sharpe higher than the best book's;
2. maximum drawdown lower;
3. higher Sharpe in at least 2 of 2024, 2025, 2026, and lower drawdown in at
   least 2 of 3;
4. the bootstrap 5 % bound of Sharpe(mix) - Sharpe(best book) above 0.

Also reported, not judged: the same mixes against the equal-weight crypto mix
without the sleeve, and with SPY as the sleeve instead.

## Pool (all five studies registered today)

1,724 trials published after `gated_btc`, `genome_gates` and `m4_residual`,
rounded up to **1,740** to cover the parallel studies registered the same day
(the owner's count), plus this batch's 22 Sharpe trials (`vix_carry` 8,
`etf_routing` 4, `crypto_open_gap` 2, `treasury_premium` 2, `btc_vrp` 6):
**1,762**. Variance as in the director studies: the 1,140 hand trials at the
variance backed out of the published bar (377 at 2.43), the factory's 600 at
their own, this batch's 22 at their own, all in annual units and converted to
each series' own calendar (252 sessions here, 365 for crypto).

## If it passes, or passes all but deflation

A lab paper book `vix_carry` whose engine signal is a US-equity book
(`"asset_class": "us_equity"`, weights `{"SVXY": w}`), traded by the engine in
the regular session, autopilot-only, and a job entry in `research/ops/jobs.yaml`
in the same format as the others, disabled. A pass on everything but
deflation makes it an experiment (`"experimental": true`). A killed rule gets
nothing.

## What could fool us

- The synthetic history: one product built from three sources. The checks
  above say how close the rebuild is; the out-of-sample years from
  2018-02-28 are the real product.
- A single event decides short-volatility results. The kill rule is there for
  that, and the report lists the ten worst days of the pick with the signal
  on each prior close.
- Survivorship of the product: XIV died on 2018-02-05. SVXY survived because
  it changed its leverage; the series uses -0.5x throughout, so the history
  is the product that exists today, not the one that existed then.

## Changes to the survey's sketch

- Sizing "scaled by VIX / 100" is replaced by inverse realised vol at a 20 %
  target: VIX / 100 as a weight would cap exposure at about 0.15 to 0.3 and
  rise in stress, the opposite of what a scaled short-vol position needs.
- The history starts 2006 (rebuilt index) instead of 2009, the longest honest
  history the free data allows; in sample 2007 to 2017.
- Fill at the next close (16:15 against 16:00); the survey left it open.
- The pool is 1,762 with this batch, not the survey's 1,724.
