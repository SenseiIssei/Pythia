# Polymarket (Y4): pre-registration

Written on 2026-10-21, before any model was fitted, any bias table computed
or any forecast scored. The data collector was tested on one month (2023-06,
83 markets) to check the endpoints, nothing else was looked at. Anything
below that changes after this file is committed is reported as a change, with
the reason, in `results/polymarket.md`.

**PAPER ONLY.** No wallet, no key, no signer, no order. Polymarket restricts
trading in several countries; this asks whether a model can beat the market
price at all, after the costs a taker would pay.

## Question

Can our own model, a Claude forecaster, or a mix of them, assign
probabilities to Polymarket's binary markets that beat the market's own
price out of sample by time, by enough to pay the spread and the taker fee?

## Data (`lab.polymarket.collect`)

Public, keyless endpoints only: Gamma (`/markets/keyset`, metadata,
outcomes, tags, fee schedule) and CLOB (`/prices-history`, `/books`). At most
8 requests a second (the published limits are 300 to 1,500 per 10 seconds
per endpoint), backoff on 429 and 5xx.

- **Resolved set.** Every closed market with at least $1,000 of volume,
  listed per end month from 2020-06. Per month, category and kind a
  deterministic sample (the first 300 event markets, 150 single-game
  markets, 40 recurring up-or-down markets, ordered by a hash of the market
  id: the sample cannot depend on volume, price or outcome). Universe counts
  per stratum are kept, so every table can be reweighted to the universe.
  Markets that resolved 50-50 or are not resolved are counted and left out.
- **History** of the YES (first) outcome token: daily over the whole life,
  hourly over the last 14 days before close, 10-minute over the whole life
  for markets that lived under two days.
- **Live record.** Once a day every open market with at least $1,000 of
  liquidity (about 56,000 of 271,000 open markets on 2026-10-20; best bid and ask, spread,
  last price, volume, 24 h volume, liquidity, end date, fee schedule), and
  15 levels of both order books for up to 2,000 candidates (accepting
  orders, not up-or-down, resolving within 120 days, liquidity at least
  $2,000).
- **Categories** are Polymarket's fee categories (crypto, sports, politics,
  geopolitics, finance, economics, tech, culture, mentions, weather, other),
  from the tags, else from keywords in the question (old markets carry only
  the tag "All"). **Kinds:** updown, game, event.

## Market states (the panel)

A decision time is the first history sample of each UTC day while a market
is open (of each hour for markets that lived under two days), from its
creation plus one hour to its close; the price is that sample. Lags (1 and 7
days) are the last sample at or before the same time earlier, at most 36
hours older. Features, all known at the decision time:

(Changed on 2026-10-20 after a test run on the first 9,000 markets, before
the full set existed: the registered grid was every 00:00 UTC with the last
sample at or before it. Polymarket's daily samples are taken a few seconds
after midnight, so that grid used the previous day's price, and the paper
twin "bought" at prices up to a day old. Found because the twin's return was
implausible while the model's Brier score was worse than the market's.)

- price `p`, `logit(p)`, distance to the nearer edge `min(p, 1 - p)`
- days to the scheduled end date (known from creation), days since creation,
  share of the life gone
- price change over 1 and 7 days, the 7-day realised volatility of daily
  logit changes, the life-to-date high and low
- category, kind, negative-risk flag

(Changed before anything was computed: "number of markets in the same event
in the sample" is dropped. The sample caps strata, so the count in the
sample is not the count a live market shows, and the live model would see a
different feature than it was trained on.)

Not a feature: final volume or liquidity (only known at the end; using them
would select markets that turned out busy). Label: 1 when the first outcome
won. Each market weighs one in every table and score: a state's weight is
one over the number of states its market has in the same slice.

## B. The biases (descriptive, before any model)

Each with a 95 % band from a bootstrap that resamples whole events (markets
of one event move together), and reweighted to the universe counts:

- **B1 favourite/longshot.** Outcome rate against mean price in twelve price
  buckets (0-2, 2-5, 5-10, 10-20, 20-35, 35-50, 50-65, 65-80, 80-90, 90-95,
  95-98, 98-100 %), and the calibration line
  `logit P(win) = a + b * logit(p)` (b < 1: longshots too dear and
  favourites too cheap).
- **B2 drift to resolution.** The same line and the market's Brier score by
  days to the end date (under 1, 1-3, 3-7, 7-30, 30-90, over 90).
- **B3 category and kind.** The line by category and kind.
- **B4 liquidity and spread.** By final volume tercile (descriptive only,
  final volume is hindsight); by the quoted spread and liquidity of the live
  record once enough of it has resolved.
- **B5 recent moves.** Whether the 7-day price change adds to `logit(p)` in
  a logistic fit (positive: the market under-reacts; negative: it
  over-reacts).

## M. The calibrated model (M-PM1)

Out of sample by time. Test quarters 2024Q1 to 2026Q4 (the last partial).
For a test quarter, training uses only states of markets that closed before
the quarter began (labels known then); test states are those whose decision
time falls inside the quarter. Three forecasts of P(YES):

1. **market**: `p` itself (the baseline).
2. **recal**: the logistic line `a + b * logit(p)` with one (a, b) per
   horizon bucket and an offset per category (few parameters).
3. **gbm**: LightGBM (binary, 300 trees, learning rate 0.03, 31 leaves,
   at least 200 states a leaf, feature fraction 0.8, market-weighted), then
   isotonic regression fitted on the latest 20 % of the training window by
   decision time, then clipped to [0.001, 0.999].

Scores: Brier and log loss (clipped at 0.001), market-weighted, on all test
states and by year, category, horizon bucket. **Pass rule** for a model
against the market: lower Brier and lower log loss over all test states; the
95 % event-bootstrap band of the Brier difference above zero; better in at
least 2 of the 3 test years (2024, 2025, 2026); better in at least half of
the categories with 300 or more test markets. Holm over the four loss tests
of this study (recal, gbm, Claude, ensemble against the market).

## C. The Claude forecaster (forward only)

A forecast is scored only if its market resolved **after** the forecast was
written. Nothing is backtested on resolved markets: the model may know how
they ended.

- **Which markets.** From the day's candidates: politics, geopolitics,
  economics, tech, culture, mentions and other (where public information
  decides; not crypto, finance, weather or sports, which are prices, data
  feeds or games), scheduled to end within 2 to 60 days, liquidity at least
  $5,000, YES ask between 3 and 97 cents. Up to 300 markets a day (479
  qualified on the first day, at about $0.001 a market), new ones first,
  soonest-ending first; a market is forecast again after 7 days if it is
  still open. (A first request of 8 markets checked the path on
  2026-10-20; those 8 rows are in the ledger like every other.)
- **What it sees.** Today's date, its own knowledge cutoff, the question, the
  rules (the market description), the end date, the category, the event's
  title and the other questions of the same event (no prices). **It never
  sees a price**, so it cannot copy the market.
- **What it gives.** A probability (0.01 to 0.99), a confidence (low,
  medium, high), whether its knowledge is likely out of date for this
  question, and one sentence of reasoning. JSON schema, Sonnet 5.5
  (`claude-sonnet-5-5`), effort medium, Batches API, 8 markets per request,
  through the engine's metered endpoint (`lab.ai.engine`, budget enforced
  there). (Changed after the first run on 2026-10-20, before anything
  resolved: at effort low with a free-length list, 13 of 38 requests came
  back with one item and a placeholder reason, so 194 of 300 markets got a
  forecast. The schema now has one required entry per market and the effort
  is medium. The 194 rows stay in the ledger and count like every other.)
- **Ledger.** `<data>/polymarket/forecasts/ledger.jsonl`, append only: id,
  market, the time written, the model, the inputs' hash, the answer, the
  market's mid, bid and ask at that time, the cost. Never edited.
- **Score.** First forecast per market, against the market mid recorded in
  the same row. Pass: lower Brier and log loss than the mid, 95 % event
  bootstrap band of the Brier difference above zero, at least 200 resolved
  markets over at least 30 days.

## E. Ensemble

`logit q = w * logit(claude) + (1 - w) * logit(mid)` (and the same with the
gbm in place of Claude), w fitted on the first half of the resolved forecasts
by time, judged on the second half under the pass rule of C. It goes into a
book only if it passes.

## P. The paper rule

At a decision time with a forecast `q` and the order books:

- **Edge.** Buying YES at ask `a`: `q - a - fee(a)`, buying NO at ask `b`:
  `(1 - q) - b - fee(b)`, with Polymarket's taker fee per share
  `rate * (a * (1 - a)) ** exponent` (the market's fee schedule, else the
  category's published rate: crypto 0.07, sports 0.05, finance, politics,
  mentions, tech 0.04, economics, culture, weather, other 0.05, geopolitics
  0). Makers pay nothing, but a resting order is not modelled: every fill is
  a taker fill.
- **Enter** when the edge is at least the margin `m` (primary 0.03), the
  ask is between 3 and 97 cents, the end date is within 90 days, the market
  is not up-or-down. One position per market, never both sides.
- **Size.** Quarter Kelly, `0.25 * (q - a) / (1 - a)` of equity for YES
  (the same with `1 - q` and `b` for NO), at most 2 % of equity per market,
  10 % per event, 25 % per category, 60 % invested; at least 5 shares.
- **Fill.** Walk the ask side of the book up to the price where the edge
  falls below the margin; take what the depth offers, no more.
- **Exit.** Hold to resolution (a winning share pays $1, a losing one 0,
  a 50-50 pays 0.50). No early exits (fewer trials).
- **Books.** $10,000 of play money each:
  `pm_model` (q from M-PM1's gbm, the latest fit, m = 0.03) and
  `pm_claude` (q from the latest Claude forecast under 7 days old, m = 0.05,
  wider because it is unscored). `pm_ensemble` only once E passes.
- **Historical twin.** The same rule on the test states of M with recal and
  gbm, at m = 0.02, 0.03 and 0.05 (6 variants). No historical books exist,
  so the ask is the history price plus the median half-spread the live
  record shows for that price bucket and category (at least half a cent),
  at most $500 per market (depth unknown), and a stress case at twice the
  half-spread. Equity is marked daily at the history price.

## Trials and the bar

Sharpe trials: the 6 historical variants and the 2 live books (8; 16 with
the addendum's checks), into the
global pool (1,115 hand trials after X15 with X16, plus the factory
ledger; 1,124 once the director studies published in parallel are counted). Loss tests: 4 (Holm). The paper books are forward evidence only:
before anything near money could be discussed a book needs at least 100
resolved trades over at least 60 days, a positive mean return per trade
with its event-bootstrap band above zero, a positive result in each of its
two largest categories, and a deflated p above 0.95 over the pool.

## Addendum (2026-10-20, after the test run, before the full run)

The test run's paper twin made most of its money in the first hours of new
markets, where the history price sits at 0.5 at creation and then drops to a
mid of a thin book; the live record's median half-spread (taken from markets
with $2,000 of liquidity) says nothing about those books. Two checks are
added and counted as trials: the twin at m = 0.03 for recal and gbm (1)
without states in a market's first 24 hours, and (2) with the half-spread
looked up by the market's age as well (under 1 day, 1 to 7 days, over 7
days) from the live record.

Second addendum (2026-10-21, after a preliminary run on the markets that
ended up to 2026-01, before the full set): the twin returned thousands of
percent for both models, and recal without first-day states only +0.6 % a
trade. 4 % of all states have a price that never moved since the market
opened (on average 0.39 against an outcome rate of 0.27): no one traded
there, so the history shows a placeholder, not a quote. Two more checks per
model, (3) only states whose price has moved since the market opened and (4)
after day one and moved, so 8 checks and 16 Sharpe trials in all. The model
scores are also reported on the same three slices (after day one, moved,
both) of the registered test. None of this replaces the registered verdict;
it says how far to trust it.

## Reports

`reports/polymarket/latest.json` with the lab feed header (title,
updated_ms, status, headline, items); a daily Telegram card (English or
German); an alert when a book opens a position with an edge of 10 points or
more (at most 3 a day). `results/polymarket.md` with the answers.
