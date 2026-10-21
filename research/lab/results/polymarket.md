# Polymarket (Y4): can a model beat the market price after costs?

**PAPER ONLY.** No wallet, no key, no signer, no order: Pythia reads
Polymarket's public market data and simulates fills against the order books
it read. Trading on Polymarket is restricted in the United States and a
growing list of other countries; this is research into whether there is
anything to trade at all.

Pre-registration: `results/polymarket_prereg.md` (committed before anything
was computed; every later change is listed there with its reason). All
tables: `results/polymarket_study.md`. Code: `lab/polymarket/`. Tests:
`tests/test_polymarket.py`.

## Answer (2026-10-21)

**No evidence that money can be made, and a clear reason why the backtest
says otherwise.**

- **Where people trade, the market price is hard to beat.** Out of sample
  by quarter from 2024 (73,609 resolved markets), both our models pass the
  registered test against the recorded price: a logistic recalibration
  (Brier skill +1.0 %) and gradient boosting plus isotonic calibration
  (+3.4 %, Holm p 0.000, better in 9 of 10 categories). But the skill sits
  in markets nobody traded: in markets that ended with under $5,000 of
  volume the boosted model is 6.8 % better than the recorded price; from
  $33,000 it is worse (-0.8 %), from $100,000 clearly worse (-1.8 %, band
  below zero) and over $1 million worse still (-3.4 %).
- **The recorded price is often not a quote.** Polymarket's history is a
  midpoint. Of the open markets on 2026-10-20 with a mid between 35 and 65
  cents, the median quoted spread was 90 to 96 cents and 82 to 93 % were
  wider than 10 cents; markets with $10,000 of liquidity quote about 2
  cents. A "price" of 0.45 in a thin market is often the middle of a bid at
  1 cent and an ask at 89.
- **The historical paper twin is therefore not evidence.** Filled at the
  recorded price plus half a cent, the registered rule "makes" +14,700 to
  +19,700 % with the recalibration and about +42,000 % with the boosted
  model (Sharpe 3.5 to 5.2, deflated p up to 1.00). That is what buying at a
  midpoint nobody quoted looks like. Leaving out first-day states and prices
  that never moved shrinks the recalibration to +2.5 % a trade (band -0.4 to
  +5.3 %) but leaves the boosted model at +17.6 % a trade, because it simply
  moves to the same thin markets a day later. No fill model built from
  history can tell these apart, so the only test that counts is forward,
  against real books.
- **The Claude forecaster has no score yet.** 535 forecasts (Sonnet 5.5,
  never shown a price) are in the append-only ledger; the first markets end
  on 2026-10-23, half of them by 2026-11-04 (the US midterms). 82 % of the
  forecasts flag that the answer most likely depends on events after the
  model's training data; there it disagrees with the market by a median 11
  points, elsewhere by 3.
- **Two paper books run forward** on real order books (taker fills walking
  the depth, Polymarket's fee schedule): the Claude book opened 31 positions
  on 2026-10-20, the model book 30 on 2026-10-21. Nothing has resolved.
- **Ensemble:** not fitted; it needs 200 resolved Claude forecasts first.

## Data and terms

**Sources.** Gamma `/markets/keyset` (metadata, tags, outcomes, the fee
schedule), CLOB `/prices-history` and `/books`. All public and keyless; the
docs (2026-10) list per-IP limits per 10 seconds of 300 (Gamma markets),
1,000 (price history), 1,500 (`/book`), 500 (`/books`). The collector
stayed at 8 requests a second (14 for part of the one-off backfill), with
backoff. The docs say read-only market data is not subject to the
geographic restrictions; order placement is. The user agent says what the
client is. `/markets` without keyset is deprecated (a `sunset` header), so
only keyset paging is used.

**Resolved set** (`lab.polymarket.collect --history`):

- Gamma lists 1,089,674 closed markets with at least $1,000 of volume from
  2020-06 to 2026-10, 1,084,133 resolved to one side. Volume exploded in
  2025 and 2026 (76,216 in February 2026 alone, most of them sports and
  recurring up-or-down markets).
- Per end month, category and kind a deterministic sample by a hash of the
  market id (300 event markets, 150 games, 40 up-or-down): 75,554 sampled
  markets with history. Markets of the AMM era (before the order book, late
  2022) return no price history; the panel starts on 2022-11-18.
- Panel: 74,751 markets of 30,405 events, 2,445,333 market states (one a
  day, one an hour for markets that lived under two days), 2023 to
  2026-10-21: 2023 1,423 markets, 2024 10,818, 2025 30,816, 2026 37,086;
  every category from 456 (other) to 13,701 (sports). 223 MB on disk.

**Live record** (`lab.polymarket.collect --live`, daily): every open market
with $1,000 of liquidity (55,372 of about 271,000 on 2026-10-21; the rest
are dead), and 15 levels of both books for the 2,000 most liquid candidates
(accepting orders, not up-or-down, ending within 120 days). About 9.5 MB
a day; the folder has a 6 GB budget.

**Fees** (docs, 2026-10): takers pay `shares * rate * p * (1 - p)`
(crypto 0.07, sports, economics, culture, weather, other 0.05, finance,
politics, mentions, tech 0.04, geopolitics 0), makers nothing. The book
uses each market's own `feeSchedule` when Gamma gives one. On 2026-10-21
98 % of open crypto and 97 % of open sports markets charged a taker fee,
almost no politics, geopolitics, economics, culture or tech market did (the
category table is a ceiling, not what every market pays). The historical
twin charges the table rates although most past markets had no fee.

## B. Biases

Each market weighs one, reweighted to the universe, 95 % bands from
resampling whole events.

- **B1 favourite/longshot.** Over everything, the calibration line is flat:
  `a = -0.07` (se 0.05), `b = 1.02` (se 0.035). YES looks too dear in the
  35-50 % bucket (won 38.4 % at a mean price of 44.8 %) and 65-80 % (64.9 %
  at 71.7 %), but these are the buckets where empty books put their
  midpoint. In markets that ended with $100,000 or more (hindsight
  selection, descriptive only) YES won 2 to 6 points more often than priced
  between 5 and 80 % (`a = +0.14`, se 0.03, `b = 0.99`): a market that ends
  up busy is one where something happened, so this cannot be traded.
- **B2 drift to resolution.** The intercept falls from +0.02 under a day to
  -0.39 at 30 to 90 days and -0.40 beyond: far from the end, YES is priced
  above how often it happens (money locked for months, and "nothing
  happens" is underrated). The slope stays near 1.
- **B3 category and kind.** Single games in finance (`b = 0.67`), crypto
  (0.83) and sports (0.90) show a classic longshot bias; sports and weather
  event markets price YES too high (`a = -0.48`, -0.51); geopolitics too low
  (+0.22).
- **B4 volume.** The top final-volume tercile (over $33,000) has
  `b = 0.88` (se 0.05): longshots too dear where markets are busy. Quoted
  spread and live liquidity effects need the live record to resolve first.
- **B5 recent moves.** The 7-day logit change adds `-0.21` (se 0.09) to
  `logit(p)`: moves of a week partly reverse. The 1-day change adds
  nothing (-0.03, se 0.04).

## M. The calibrated model against the market

Walk-forward by quarter from 2024Q1 to 2026Q4, training only on markets
resolved before the quarter. Registered verdict: **both pass** (lower Brier
and log loss, event-bootstrap band above zero, at least 2 of 3 years, at
least half the large categories).

| Model | Brier market | Brier model | Skill | Gain (95 %) | Years better | Categories better |
|---|---|---|---|---|---|---|
| recal | 0.1071 | 0.1061 | +1.01 % | +0.00108 (+0.00082 to +0.00131) | 3/3 | 7/10 |
| gbm | 0.1071 | 0.1035 | +3.41 % | +0.00365 (+0.00321 to +0.00410) | 2/3 | 9/10 |

Where the price is more likely a real price (declared in the addendum
before the full run):

| Slice | recal skill | gbm skill (95 % gain band) |
|---|---|---|
| after day one | +0.12 % | +1.31 % (+0.00080 to +0.00149) |
| price has moved | +0.32 % | +1.64 % (+0.00127 to +0.00197) |
| both | +0.10 % (band includes 0) | +1.32 % (+0.00082 to +0.00151) |

By the market's final volume (both slices, hindsight, descriptive):

| Final volume | Markets | recal skill | gbm skill (95 % gain band) |
|---|---|---|---|
| under $5,000 | 20,189 | +2.39 % | +6.76 % (+0.00488 to +0.00627) |
| $5,000 to $33,000 | 24,596 | -0.48 % | +0.21 % (-0.00030 to +0.00064) |
| $33,000 to $100,000 | 10,027 | -0.91 % | -0.79 % (-0.00152 to +0.00006) |
| $100,000 to $1 million | 11,204 | -1.15 % | -1.84 % (-0.00242 to -0.00107) |
| over $1 million | 2,764 | -0.89 % | -3.36 % (-0.00462 to -0.00186) |

So the models learn what a placeholder price means (a market opened at
0.5, an empty book's midpoint, a price that never traded) and beat that,
not the traders. The live model the paper book uses is fitted on all
2,445,333 states, as registered.

## P. The paper rule

Edge after the taker fee and the ask, margin 3 points (Claude 5), quarter
Kelly, at most 2 % of equity per market, 10 % per event, 25 % per category,
60 % invested, held to resolution.

**Historical twin** (ask = recorded price plus the live record's median
half-spread, at least half a cent, at most $500 a market): every variant
returns thousands of percent (table in `polymarket_study.md`). Not evidence,
for the reasons above; its deflated p values (up to 1.00 over 1,740 trials)
only show how badly a midpoint backtest misleads. Two defects were found on
the way and are documented in the pre-registration: a midnight grid that
used the previous day's price, and first-hour prices at the 0.5 placeholder.

**Live books** (forward, real books, from 2026-10-20):

| Book | Opened | Invested | Equity at mid | Resolved |
|---|---|---|---|---|
| `pm_claude` | 31 on 2026-10-20 | $5,900 | $9,563 on 2026-10-21 | 0 |
| `pm_model` | 30 on 2026-10-21 | $5,956 | $9,926 on 2026-10-21 | 0 |

The Claude book mostly bets against the market on 2026 elections where its
knowledge is stale (it gives 5 % to an outcome the market prices at 70 %);
the model book mostly buys NO near 50 cents on game totals and spreads and
on election markets, the pattern it learned from thin markets. Both are
the registered rule, and both will be scored as they resolve: sports in
days, the midterms on 2026-11-03.

## C. The Claude forecaster

Sonnet 5.5 through the engine's metered endpoint (Batches, effort medium, 8
markets a request). It sees the question, the rules, the end date, the
event and its other questions, never a price. On the first run at effort
low with a free-length answer list, 13 of 38 requests came back with a
single item; the schema now requires one entry per market (documented in
the pre-registration; the 194 rows of that run stay in the ledger).

- 535 forecasts on 2026-10-20 and 21: politics 385, geopolitics 90,
  economics 10, tech 1 (the categories where public information decides and
  that had liquid books ending within 60 days).
- Cost: $0.57 in all (82 batch requests and two direct test calls), about
  $0.001 a market. Daily from now on: up to 300 markets, under $0.40.
- Scored only on markets resolved after the forecast was written, the first
  forecast per market against the mid in the same ledger row. Pass needs
  200 resolved markets over 30 days.

## What evidence would be needed

- **A forecaster:** at least 200 resolved forward forecasts over at least
  30 days, Brier and log loss below the market mid written at the same time,
  event-bootstrap band above zero; and the same in markets with real books
  ($10,000 of liquidity), where the history says the market is better.
- **Money:** a paper book with at least 100 resolved trades over at least
  60 days, a mean return per trade after fees and spread with its
  event-bootstrap band above zero, positive in each of its two largest
  categories, deflated p above 0.95 over the pool. Even then: no wallet, no
  key, and trading would be the owner's legal question first.

## Trials

16 Sharpe trials (6 registered twin variants, 8 addendum checks, 2 live
books). The pool is 1,124 hand trials (after X15, X16 and the director
studies), 600 factory genomes and these 16: 1,740 (noise bar 2.73). The
next study starts from **1,140** hand trials. Loss tests: 2 of 4 run
(recal and gbm, Holm over 4); Claude and the ensemble are pending.

## Jobs (added disabled)

| Job | When (UTC) | What |
|---|---|---|
| `polymarket-daily` | 05:15 | snapshot and books, Claude forecasts, settle, step both books, score, report `reports/polymarket/latest.json`, card and big-edge alerts (category Studies) |
| `polymarket-history` | Mondays 01:30 | markets resolved since the last run, with history |
| `polymarket-study` | after the history | biases, the walk-forward, the twin, the live model |

See `research/ops/README.md`, "Polymarket (Y4)", for switching them on and
copying the resolved set built on the PC to the server.
