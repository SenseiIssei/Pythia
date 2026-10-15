# CS2 skins market (2026-10-15)

**Read this first.** Paper only: nothing here buys or sells, and nothing will (automated trading on Steam or a skin marketplace breaks their terms). History collected so far: **1 day** (first 2026-10-15). The bootstrap numbers come from one snapshot of Skinport's 90-day sales windows, cross-validated across items, so they are an in-sample cross-section, not a time-series backtest. The walk-forward numbers are backtests on the collector's own history and appear once there is enough of it. The paper portfolio is the only forward evidence, and it is play money.

**Verdict:** Too early: 1 day of history. Bootstrap (one snapshot, cross-sectional): 7d rank IC 0.208, momentum alone -0.130.

## Data

- Skinport items in the latest snapshot: 25143; with sales in all three windows: 4360
- Steam price rows: 0 over 0 days
- Daily panel for the walk-forward model: 1 day, 4852 liquid items

## 1. Spread between Skinport and Steam, net of fees

Fees: Steam keeps about 15 % of what the seller gets (5 % Steam, 10 % CS2, at least a cent each) and pays in wallet funds that cannot be withdrawn; Skinport keeps 8% of the sale and pays cash. Both routes undercut the other side's lowest ask by a cent.

- no Steam prices yet
- Steam in the last collector run (2026-10-15T12:24:37Z): 0 of 88 prices; steam: refused (429) after one try, cooling off

## 2. Momentum or reversion

Bootstrap: does the change from the 30-90 day average to the 7-30 day average predict the change to the last 7 days? Positive rank IC is momentum, negative is reversion. Caution: the 7-30 day average is in both the signal and the outcome, so noise in it alone makes the rank IC negative; a reversion number here is an upper bound on real reversion until the walk-forward test, whose windows do not share days, confirms it.

- All items: rank IC -0.130 over 4360 items
- Liquid items (20+ sales in days 7-30): -0.075 over 2073
- Walk-forward (collected history): needs 52 labelled days, has 0

## 3. Cases: age, discontinuation, operations

Release dates from `lab/collect/cs2_watchlist.json`; drop pool changes and operations are added there as events when they happen.

- Cases with sales in all windows: 40 (39 with a known release date)
- Rank correlation of age with the 90-day change (avg 30-90 to avg 0-7): 0.063

| group | cases | median_change |
|---|---|---|
| 3 to 7 years | 10 | -0.162 |
| over 7 years | 26 | -0.104 |
| under 3 years | 3 | -0.072 |

- Event study (abnormal return from 7 days before to 30 days after, against the median case): no event inside the history yet

## 4. Forecaster of 7 and 30-day returns

Bootstrap LightGBM, 5-fold across items (same weeks in train and test, so a market-wide move is shared): 7 days from the earlier windows' change, sales rate and trend, level, category and case age; 30 days from static traits only. The 7-day model sees the 7-30 day average that is also the base of its outcome, so part of its rank IC is the measurement effect of section 2; the walk-forward test does not have it.

| horizon | items | rank IC | top decile minus all | MSE model | MSE zero | MSE mean |
|---|---|---|---|---|---|---|
| 7d bootstrap | 4360 | 0.208 | 0.103 | 0.081 | 0.096 | 0.093 |
| 30d bootstrap | 11361 | 0.174 | 0.114 | 0.116 | 0.135 | 0.118 |

Walk-forward (monthly expanding refits, training labels end before the test month, rank IC from non-overlapping periods, top decile held to the horizon after 10% round trip):

- 7d: needs 52 labelled days, has 0
- 30d: needs 75 labelled days, has 0

## 5. Paper portfolio (forward, play money)

- Equity 10,000.00 EUR after the sale fee (+0.00 %) since 2026-10-15, 0 positions, 0 paper trades, 1 journal day.
- Rules: top 10 after fees, 10 % each, weekly look, 30-day minimum hold, Skinport prices and fee (see `lab/cs2/book.py`).

## Notes on the first run (added by hand)

This file is the daily report as written by `lab.cs2.run` on 2026-10-15
from two real collector runs (12:15 and 12:24 UTC, on the PC, not yet on the
lab machine). What is and is not evidence here:

- **Not a backtest.** Every model number above comes from one snapshot. The
  bootstrap splits Skinport's 90-day sales windows into days 30-90, 7-30 and
  0-7 and compares items with each other; train and test folds share the
  same weeks. It ranks items within the market, it says nothing about where
  the whole market goes, and part of the 7-day IC is the measurement effect
  named in section 2. The first real backtest (walk-forward on collected
  daily snapshots) needs about 52 days for 7 days and 75 for 30 days; a
  number worth acting on needs months more.
- **Steam answered nothing.** Every `priceoverview` request from the
  collector got 429, from the first one on, while the same URL fetched with
  curl from the same machine was answered at the same time. The collector
  keeps its honest client and backs off (one knock per hour while refused).
  Until Steam answers, sections 1 and the gap alerts are empty; whether the
  lab machine fares better shows in `steam_ok` of `cs2/collector.json`.
- **Cases fell.** All three case age groups trade about 7 to 15 % below their
  30-90 day average (median), with no clear age effect (rank correlation
  0.06). No drop pool event is inside the history yet.
- **Paper portfolio.** The first local look bought six music kits the model
  expected to clear the 10 % round trip by 0.0 to 0.9 %, which is noise; buys
  now need 3 % over the round trip (`MIN_EDGE`), and with that rule nothing
  qualified, so the play-money book holds cash. That is the expected answer
  for most weeks.

## Steam market trends (lab.cs2.trends, added by hand, first run 2026-10-15)

Because Steam refuses the collector, the Steam side now comes from a public
aggregate instead of Steam itself: the price files of the open-source CSGO
Trader browser extension (`prices.csgotrader.app/latest/steam.json`, average
Steam Community Market sale prices in USD over 24 hours, 7, 30 and 90 days,
rebuilt daily; no volume; no published terms, so the lab takes it once a day
and names the source). The daily job `cs2-trends` stores one snapshot a day
and reports in `reports/cs2_trends/` and on the CS2 page. Information only.

First run, one snapshot (PC, 2026-10-15; the file was rebuilt 13:25 UTC):

- 32,077 items with a Steam price, 17,678 of them sold in the last 24 hours.
  1,124 are liquid by the lab's rule (1 EUR or more, 10 or more Skinport sales
  in 7 days; the Steam file has no volume).
- **Steam against Skinport.** On 1,120 liquid items Steam's average sale
  price is +62 % over Skinport's recent sale price (median). After fees,
  buying on Skinport and selling on Steam nets +43 %, but in Steam wallet
  funds that cannot be withdrawn; buying on Steam and selling on Skinport
  nets -47 % in cash. The premium is the price of wallet money, not a free
  lunch. Cases carry the largest premium (+88 %), Factory New skins +100 %,
  Battle-Scarred +54 %. Three liquid items cleared the cash route by 5 % or
  more after fees that day (two stickers and a sealed graffiti, 1.36 to 2.65
  EUR on Steam, +8 to +13 %); 24 more had a Steam premium far above their
  group's (4 robust deviations and twice the group median).
  The Steam price is an average of sales, not an ask, and the spread uses the
  less flattering of the 24-hour and 7-day averages for each route.
- **Changes.** Before there are older snapshots, "7 days" is the 24-hour
  average against the 7-day one. Median by group: within 2 % either way for
  every group; cases +0.0 % on that measure and -3.7 % against their 30-day
  average. Top mover M4A4 | Dark Operative (Minimal Wear) +84 %, biggest
  drop StatTrak UMP-45 | Momentum (Minimal Wear) -40 %, both on thin items
  (10 to 14 Skinport sales a week).
- **Momentum or reversion.** From the averages of one day (30 days against
  90, then 24 hours against 7 days), the rank IC across liquid items is
  +0.02: no lean. By group it ranges from -0.40 (capsules, 24 items) to +0.17
  (Field-Tested skins, 240 items); with these few items and nested windows
  that is a hint at most. The real test, a week's change against the next
  week's from our own snapshots, starts after 21 days.
- **Drops.** No release or drop-pool event in the last 45 days in the
  watchlist, and a new case or capsule can only be seen from the second
  snapshot on.

