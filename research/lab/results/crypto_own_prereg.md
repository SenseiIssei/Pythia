# Own crypto ideas and untested cross-sectional factors: pre-registration

Registered 2026-10-21 and committed before any number below was computed and
before the Upbit per-coin history was downloaded. Three studies registered
together, drawn from `proposals/2026-10-21-strategy-survey.md`:

- **`delist_hazard`** (survey O3): a Binance delisting hazard model, used as an
  exclusion filter on the long books.
- **`kr_premium_xs`** (survey O4): each coin's own Korean premium (Upbit
  against Binance) as a cross-sectional signal, as a filter or tilt on the long
  books, and a long/short for information.
- **`xs_factors`** (the survey's crypto cross-section catalog): six factors the
  lab has not tested as filters or tilts on the books (idiosyncratic
  volatility, MAX, skewness, abnormal volume, size within liquid coins,
  weekly reversal).

The fourth idea of the same request (survey O9, pump.fun activity as a
memecoin gauge) has too little history to test; its forward registration is
`results/pumpfun_activity_prereg.md`.

Code: `lab.experiments.crypto_own` (shared harness), `lab.experiments.delist_hazard`,
`lab.experiments.kr_premium_xs`, `lab.experiments.xs_factors`, and the Upbit
collector `lab.collect.flow --only upbit_all`, all written after this file.
Results go to `results/delist_hazard.md`, `results/kr_premium_xs.md` and
`results/xs_factors.md`. Nothing here may change once a result exists; any
correction is added at the end with its reason.

## Common ground

### Panel and windows

- The sweep's survivorship-free daily panel (`fam_common.load_panel`): every
  USDT pair Binance ever listed, delisted ones included, reused or
  redenominated tickers split into separate coins, rebuilt fresh from the
  hourly history on the PC (which runs to 2026-10-20) and cut at
  **2026-10-20**.
- In sample 2020-08-01 to 2023-12-31; out of sample 2024-01-01 to 2026-10-20.

### Books

The three daily books the Alpaca autopilots run, exactly as `gated_btc` and
`flow_overlays` used them: `breakout_top10`, `tsmom_top20` and
`tsmom_tranches`, their own target functions (`alpaca_universe.originals`),
every coin Alpaca does not list held as cash (`alpaca_universe.cash_left`, the
15 coins), their own simulators (`alpaca_universe.simulate`). The **twin** of
each is the original book on the survivorship-free panel (the most liquid
coins of each day, delisted ones included, nothing held as cash) with the same
modification.

### What a signal does to a book

A signal decided at the close of day t changes only the book's targets at that
close; nothing new is bought.

- **Filter.** A held or targeted coin that the signal flags at the close of t
  gets a target of 0 (also where the book's target is "leave as is"). The
  freed weight stays in cash.
- **Tilt.** Each coin with a positive target is multiplied by m = 1.5 - q,
  where q in (0, 1] is the coin's percentile rank of "badness" in the
  signal's reference set that day (q = 1 is the worst); coins without a value
  keep m = 1. The changed targets are then scaled so their sum equals the sum
  they had before (a tilt moves weight, it does not add or remove exposure).
  Targets that say "leave as is" are not touched.
- **One day late.** The flags or multipliers decided at the close of t are
  applied at the close of t+1 (the book itself unchanged).

### Costs

35 bps per unit of one-way turnover (Alpaca taker plus slippage), the judged
cost; 70 bps reported as stress. The long/short line of `kr_premium_xs` is at
41 bps with real funding (perps), information only.

### Gates against the book alone (as X6 `flow_overlays`)

For a modified book against the same book unmodified, at 35 bps, out of
sample:

1. Sharpe higher, and higher in at least 2 of 2024, 2025 and 2026;
2. maximum drawdown lower;
3. the 5 % bound of a stationary bootstrap of the Sharpe difference (mean
   block 20 days, 4,000 draws, seed 20261021) above 0;
4. filled one day late, Sharpe still higher than the book's;
5. the survivorship-free twin with the same modification at least as good as
   the twin alone;
6. the improvement (the daily difference series) has a deflated p above 0.95
   over the 94 trials of this registration, at the variance of their
   difference Sharpes (X6's rule).

### Gate against gated BTC

7. The modified book's daily net return minus G's, where G holds BTC at
   weight k while BTC closes above its 200-day average (`gated_btc.sim_gate`,
   25 % trim band) and k is the unmodified book's in-sample volatility over
   G's at k = 1 (capped at 1), has an out-of-sample Sharpe above 0 at 35 bps.
   Its bootstrap band and the unmodified book's own difference are reported
   next to it.

### Verdict and wiring

- **Pass**: gates 1 to 5 and 7. A pass is wired as a shadow paper book (the
  book with the filter or tilt applied, a signal file like the other books,
  `autopilot_only`) with a job entry in `research/ops/jobs.yaml` in the same
  format, not deployed. It is marked **experimental** unless gate 6 also
  passes and the modified book's own deflated p over the pool is above 0.95.
- **Fail**: anything else; nothing is wired.
- Each study adds its own kill rule below.

### Trials and the pool

| Study | Trials |
|---|---|
| `delist_hazard` | 9 (3 books filtered, each a day late and on the twin) |
| `kr_premium_xs` | 13 (3 books x filter and tilt; the in-sample better form per book a day late and on the twin; 1 long/short) |
| `xs_factors` | 72 (6 factors x 3 books x filter and tilt; the in-sample better form per factor and book a day late and on the twin) |
| **This registration** | **94** |

The model tests (AUC, rank IC) are not Sharpe trials. The pool before this
registration: 1,124 hand trials, 600 factory genomes and Polymarket's 16
(`results/polymarket_study.md`): **1,740**. With these 94 and the 2 forward
trials registered with O9 the pool is **1,836** (1,236 hand trials). Studies
registered in parallel by other runs on the same day are not known here and
are added when they publish. Deflation as in `director_common`: the hand
trials at the variance backed out of the published bar (377 trials at 2.43),
the factory's in-sample Sharpes, this registration's trial Sharpes at their
own variance.

## 1. `delist_hazard` (O3)

**Question.** Can a model on the survivorship-free panel tell which coins
Binance will delist within 60 days better than "the lowest 90-day volume",
and does excluding the riskiest coins improve the long books out of sample?

**Event.** A coin segment's last daily bar followed by at least 30 days
without any bar of the same symbol (a delisting, a token swap or a ticker
that was later reused; Binance's swaps such as MATIC to POL are kept, since a
book holding the coin is forced out the same way, and the report lists the
most liquid events so they can be seen). A split at a 10x jump inside an hour
(a redenomination) is not an event.

**Rows.** Every day t from 2020-08-01 and coin alive, traded that day, at
least 60 days old, with a 28-day volume. Label: 1 if the coin's event is 1 to
60 days after t. Rows on an event's own last day are dropped. Labels are used
only for t at most 90 days before the panel end (so every event inside a
labelled window is at least 30 days old).

**Features at the close of t.** log age; log 28-day mean quote volume; log
7-day over 28-day volume; log 28-day over 90-day volume; the day's percentile
rank of 28-day volume among all rows; log Amihud (28-day mean of |return| /
quote volume); log price; log distance from the segment's all-time high
close; 90-day log return; 30-day realised volatility; the share of hours with
a bar over 28 days; a USD-M perpetual traded that day; a perpetual traded in
the last 90 days but not today (perp removed); 7-day mean funding (0 without a
perp). Exchange coverage beyond Binance (Coinbase, Kraken, Upbit) is **not**
in the judged model: those lists only hold products the venues still serve,
so they leak survival. A second model with the Coinbase and Kraken first-listing
flags is reported as information only.

**Model.** LightGBM binary classifier with fixed settings (300 trees, learning
rate 0.03, 15 leaves, at least 200 rows per leaf, 80 % row and column
sampling, seed 7). Quarterly walk-forward: the first scored quarter is
2022-Q1; each quarter's model is trained on labelled rows whose label window
ended at least 10 days before the quarter starts (t + 60 + 10 before the
start). **Baseline**: minus the 90-day mean quote volume.

**Model pass.** On labelled rows from 2024-01-01: AUC at least 0.05 above the
baseline's, and the 5 % bound of a stationary day-block bootstrap of the AUC
difference (mean block 20 days, 1,000 draws, seed 20261021) above 0. Also
reported: AUC and baseline per year, the 30-day label, precision in the top
5 %.

**Filter.** Each day, coins in the top 5 % of hazard among that day's scored
rows are flagged and filtered from each book (no scores before 2022-Q1, so no
filter there). Also reported (no trial): the forward 60-day return of flagged
coins against the other scored coins from 2024 (a delisted coin keeps its
return to the last close), and the share of book-days that held a flagged
coin.

**Useful** only if the model passes and at least one book passes the gates.
**Kill**: out-of-sample AUC at or below the baseline's.

**What could fool us.** Swaps and rebrands are events the model cannot see
coming; they lower its AUC and are kept honestly. Binance announces delistings
about a week ahead; the panel has no announcement times, so part of what the
model "predicts" in the last week is the announcement's own effect on volume.
The books hold the most liquid coins, which Binance rarely delists, so the
filter may barely act on them.

## 2. `kr_premium_xs` (O4)

**Question.** Does a coin whose Upbit price sits far above its Binance price
(relative to BTC's own premium) underperform over the next 1 to 4 weeks, and
does that help the long books as a filter or tilt?

**Data.** Upbit day candles (the Upbit day runs 00:00 to 24:00 UTC) for every
KRW market Upbit lists today, from the public quotation API, collected into
`<flow>/upbit_krw_1d.parquet` by `lab.collect.flow --only upbit_all`; USD/KRW
ECB reference rates already in the lake (`fx_usdkrw.parquet`, last rate on or
before the day); Binance daily closes from the panel.

**Signal.** p(j, d) = log(Upbit close / (Binance close x USDKRW)) for every
coin on both, x(j, d) = p(j, d) - p(BTC, d), s(j, d) = the 7-day mean of x
(at least 5 values), known at the close of d. Same ticker, different asset:
a pair is used only if the median |p| over its first 30 shared days is at
most 0.10; a day with |p| above 0.5 is missing (wallet suspensions and
plumbing). Ranking set each day: coins on both that are eligible in the panel
(alive, traded, 60 days old, 1 M USD a day), at least 10 of them. High s is
bad (the prior: Korean retail buys the alt top).

**Rank IC.** Spearman IC of s against the forward 7-day and 28-day log return
(a delisted coin keeps its return to the last close), every day; t-statistics
on non-overlapping days (every 7th, every 28th). In sample and from 2024.
**IC pass**: the out-of-sample 7-day IC t-statistic at or below -2.

**Books.** Filter: drop held coins in the worst third of s. Tilt as defined
above. 3 books x 2 forms; for each book the form with the higher in-sample
Sharpe (wherever s exists before 2024) at 35 bps is also run a day late and
on the twin.

**Long/short (information, needs perps).** Each week (Mondays), long the
bottom fifth and short the top fifth of s among ranking coins with a USD-M
perpetual, equal weight, 41 bps per unit of turnover, real funding; Sharpe in
and out of sample. Counted as 1 trial; never wired (perps are not traded).

**Kill**: out-of-sample 7-day IC t above -1.

**What could fool us.** Upbit's API serves only markets it lists today, so
the coins on both are today's Upbit survivors: a coin Upbit delisted (often
after a wild premium) is missing. Because of that a pass can never be more
than experimental and forward only. Deposit and withdrawal suspensions create
premiums that are plumbing, not demand; the 0.5 cut removes only the extreme
ones.

## 3. `xs_factors` (survey catalog)

**Question.** Does any of six cross-sectional crypto factors that the lab has
used at most as model inputs improve the Alpaca books as a filter or a tilt,
judged against the books alone and against gated BTC?

**Factors at the close of t** (higher = worse, the prior from the
literature and the lab, fixed here):

| key | definition | prior |
|---|---|---|
| `ivol` | std of the residuals of daily log returns on BTC's over 60 days (at least 40) | high idiosyncratic vol is bad (lottery demand; lab: calm beats wild) |
| `max` | the largest daily return over 28 days | high MAX is bad |
| `skew` | skewness of daily log returns over 60 days (at least 40) | high skew is bad |
| `vshock` | log of 7-day over 90-day mean quote volume | a volume surge is bad (lab: hot coins lose) |
| `size` | log 28-day mean quote volume (no market caps in the lake, dollar volume stands in) | big is bad (size premium) |
| `rev7` | 7-day log return | short-term reversal: last week's winners are bad |

**Reference set.** The 50 eligible coins with the highest 28-day volume each
day; a held coin outside it is left as it is.

**Forms.** Filter: drop held coins in the worst third of the reference set.
Tilt as defined above. 6 x 3 x 2 = 36; for each factor and book the form with
the higher in-sample Sharpe at 35 bps is run a day late and on the twin (36).

**Kill (per factor)**: the in-sample pick below its unmodified book out of
sample in all three books.

**What could fool us.** The books hold at most 15 coins, mostly the largest,
so a factor ranked among 50 coins may flag BTC and ETH (size above all); that
is the test as registered, not a bug. Six factors on three books are 18
chances; gate 6 and the year rule are there for that.
