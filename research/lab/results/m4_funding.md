# M4 round three · Funding-aware labels, and the M4 shadow paper book

2026-10-07. Code: `lab/experiments/xs_daily.py` (round three), `lab/paper/m4_ls.py`.
Full tables: `results/xs_daily.md`.

## Question

Round one and two of `xs_daily` showed real ranking skill (Rank-IC 0.148 on
3-day returns) and a long/short perp book that made money gross but paid heavy
funding on the short leg in 2025-26 (the rank3 hold-3d pick paid 39 % of
capital in 2025 and 61 % in 2026 to date). The label ignored funding. Does a
label net of the funding a position pays fix that?

## What was added

- Labels `netH = fwdH - fundhH` for H = 3, 5, 7 days, where `fundhH` is the
  funding a long pays while held from the entry of day d to the entry of d+H
  (the same `fund_hold` the books are charged). One label serves both sides:
  a long earns netH, a short earns -netH, so shorts that receive funding rank
  as better shorts and shorts that pay rank as worse. Coins without a perp pay
  nothing.
- Models `reg3n`, `reg5n`, `reg7n`: LightGBM regression on the daily
  cross-sectional rank of netH, with exactly the walk-forward of `reg3`
  (quarterly from 2022, embargo H + 1 days, same 51 features, same parameters).
- 18 books: each model on the 50 or 100 most liquid perps, held H days in
  overlapping tranches or with the round-two rank buffer at 30 % and 50 %. No
  "no paying shorts" rule, the label prices it already.
- All 18 go into the deflation pool, which grows from **82 to 100 variants**.
  Selection window 2022-2023, holdout 2024-01-01 to 2026-10-05 (1009 days),
  costs 15 and 41 bps per unit of one-way turnover, as before.

These 18 were designed after round one's holdout showed the funding drain, so
they are holdout-informed by construction. Counting them in the deflation is
the minimum correction, not a full one.

## Results per family (selection-window pick, holdout from 2024)

| Family | Variants | Pick (best 2022-23 Sharpe at 15 bps) | IS Sharpe | Holdout 15 / 41 bps | Turnover / yr | Max DD | Deflated p 15 / 41 (of 100) | Family median holdout 15 / 41 |
|---|---|---|---|---|---|---|---|---|
| long-only | 24 | reg1 top 10 of 100, hold 3d, regime | 0.90 | 0.04 / -0.36 | 84 | 64 % | 0.00 / 0.00 | 0.12 / -0.40 |
| long/short, hold 1d | 6 | rank3 10/10 of 100 | 1.20 | 0.24 / -1.39 | 267 | 35 % | 0.00 / 0.00 | 0.64 / -1.05 |
| long/short, round 1 hold 3d | 6 | rank3 10/10 of 100 | 1.54 | 1.19 / 0.33 | 117 | 23 % | 0.03 / 0.00 | 1.49 / 0.59 |
| long/short, round 2 slower | 32 | reg3 10/10 of 100, buffer 30 %, no paying shorts | 1.52 | 1.00 / 0.42 | 82 | 35 % | 0.01 / 0.00 | 1.38 / 0.91 |
| **long/short, funding-aware (round 3)** | 18 | **reg7n 10/10 of 100, buffer 50 %** | 1.13 | **2.15 / 2.00** | 18 | 15 % | 0.39 / 0.09 | 2.10 / 1.69 |
| low-vol factor, same books | 4 | low 28d vol 10/10 of 50, buffer 50 % | 0.11 | 0.77 / 0.69 | 11 | 29 % | 0.01 / 0.00 | 1.65 / 1.45 |
| other baselines (M2, momentum, reversal) | 10 | M2 v2 10/10 of 50, buffer 50 % | 1.17 | 1.31 / 1.17 | 18 | 30 % | 0.05 / 0.00 | -0.69 / -1.11 |

The best single book in the pool is now `reg3n` 10/10 of 100, buffer 50 %:
holdout 2.71 / 2.47, 30x turnover, deflated p 0.74 / 0.28. Its in-sample
Sharpe was 0.56, so no honest rule would have picked it. Nothing passes gate 6
(deflated p above 0.95).

## Funding-aware against its twins in the same book

The clean comparison is `reg3n` against `reg3`: same horizon, same features,
only the label differs.

| Book (100 most liquid perps) | reg3n holdout 15 / 41 | reg3 holdout 15 / 41 | Funding paid, holdout (fraction of capital) reg3n / reg3 | Low vol same book |
|---|---|---|---|---|
| hold 3d | 1.72 / 0.81 | 1.48 / 0.62 | 1.00 / 1.30 | |
| buffer 30 % | 2.20 / 1.78 | 1.58 / 1.20 | 0.93 / 1.23 | |
| buffer 50 % | 2.71 / 2.47 | 2.67 / 2.46 | 0.71 / 0.89 | 1.87 / 1.80 |

Over all 18 round-three books against the gross reg3 book of the same shape:
funding paid is lower in **18 of 18** (by 0.1 to 0.4 of capital over the
holdout), holdout Sharpe is higher in **16 of 18** at 15 bps and 15 of 18 at
41 bps. The two that lose are reg5n and reg7n in the 100-perp buffer-50 book,
against reg3's 2.67 / 2.46, the strongest gross book.

Against the plain low-vol factor in the same book (100 perps, buffer 50 %),
all three funding-aware models win: 2.71 / 2.47, 2.40 / 2.23 and 2.15 / 2.00
against 1.87 / 1.80. Against low vol held 7 days on 100 perps (1.65 / 1.45)
reg7n hold 7d makes 2.33 / 1.88. In the 50-perp buffer-50 book low vol is
weak (0.77 / 0.69) and every model beats it. So the model adds something over
"short the wildest coins", but the margin in the best book is 0.2 to 0.8 of
Sharpe on one 2.75-year holdout that favoured exactly that bet.

What the net label does not change: average ranking skill. Rank-IC against
the net 3-day label is 0.144 for reg3n and 0.143 for reg3. The gain sits in
the tails the books trade, where funding is extreme: it stops shorting the
coins that the crowd is already short.

What it does not fix: the books still pay funding. The family pick paid 24 %
of capital in 2025 and 39 % in 2026 to date (the gross rank3 pick 39 % and
61 %). Shorting high-volatility altcoins means sitting on the crowded side.

## The selection rule does not select

Among the 56 slower long/short books (held longer than one day, both
families) the rank correlation between 2022-23 Sharpe and holdout Sharpe is
-0.14 at 15 bps and -0.16 at 41 bps. The 2022-23 window had little funding
(the gross pick paid 1 % and 8 % of capital in 2022 and 2023), so a
funding-aware label could not show its value there, and the window's winner
is a high-turnover book that the holdout then punishes at 41 bps. The protocol
says use the window's pick anyway; that is what the paper book does, and it is
one more reason this is forward evidence, not a candidate.

## Funding data gap

The funding history in the PC mirror ends with the September 2026 monthly
archive: last settlement 2026-09-30 16:00 UTC. Consequences:

- Net labels exist up to decision day 2026-09-28 (a holding window must end
  before the data does); later days are unlabelled, not labelled as zero
  funding. The 2026Q4 fold therefore has no out-of-sample net IC.
- Books are charged no funding on the last 7 holdout days (2026-09-29 to
  10-05, the 29th partly). Cutting the holdout at 2026-09-28 moves Sharpe by
  0.04 at most: rank3 hold 3d 1.15 / 0.29 instead of 1.19 / 0.33, the
  funding-aware pick 2.17 / 2.02 instead of 2.15 / 2.00, low vol 1.88 / 1.82.
- The features fund1 and fund7 are zero for 2026-10-01 onwards, so scores on
  those five days are computed from stale funding features for every model.

## M4 shadow paper book (`lab.paper.m4_ls`)

**Configuration: rank3, long the best 10 and short the worst 10 of the 100
most liquid USDT perps of the day, three overlapping 3-day tranches.** It has
the highest 2022-23 Sharpe (1.54 at 15 bps) of all 56 slower long/short books,
round three included; the funding-aware family's best in that window was 1.13,
so it does not take over. Holdout 1.19 / 0.33, deflated p 0.03 over 100.
Variant string: "M4 rank3 · 10/10 of the 100 most liquid perps · hold 3d ·
fails deflation, forward evidence only". No signal file.

Each run: rebuilds the `xs_daily` panel from the history files with the
backtest's own code, scores yesterday (eligibility without the entry price the
live day cannot have yet, market dispersion recomputed), retrains rank3 on all
labelled history when the cached model is a week old, keeps the 100 most
liquid perps that trade now (exchangeInfo), marks to the bookTicker mid, books
the funding that settled since the last run (fundingRate, premiumIndex live
rate as fallback), replaces today's tranche and trades at the touch plus the
5 bps USD-M taker fee; the backtest's 15 bps is journaled next to it. A new
book starts with all three tranches filled from the last three days' scores.

Journal columns: date, equity, gross_ret_pct, funding_pct, paper_cost_bps,
model_cost_bps, turnover, long_exposure, short_exposure, held,
funding_carry_bps_day (live funding of the new book per day), entry_hour_utc,
model_trained, funding_fresh, longs, shorts (today's tranche), weights. The
Lab page reads date, equity and turnover from it and variant and started from
state.json, as for the other books.

Dry run on the PC (2026-10-07, decision day 2026-10-06): panel rebuilt in
100 s cold (17 s warm), model trained in 10 s on 551,535 rows (labels to
2026-10-02), whole run 114 s cold and 31 s warm, peak memory 3.0 GB. Longs
1000SHIB BNB BTC DOGE ETC LTC SOL TRX XLM XRP; shorts 0G CHIP GTC MET MOVR NMR
QNT RLC SAGA VTHO. Fill cost 5.8 bps per unit of turnover against the modelled
15. The book as picked would pay 10.5 bps of capital a day in funding at
today's live rates (about 38 % a year), the same drain the backtest shows.
`funding_fresh` was false because the mirror's funding stops at September; on
the VPS it depends on the funding backfill.

30 days and 30 rebalances, as for every paper book, before anyone reads
anything into it.
