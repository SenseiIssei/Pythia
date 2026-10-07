# PROFIT-PLAN — how Pythia earns money, and how it becomes better than the alternatives

> Companion to [`PLAN.md`](PLAN.md) (what the system *is*) and [`SAFETY.md`](SAFETY.md) (what it must
> never do). This document is about the only two questions that decide whether any of it was worth
> building: **where does the edge come from**, and **why would a user pick this over what they
> already have?**

Nothing here is financial advice, and nothing here is a promise. It is an engineering plan with
falsifiable checkpoints.

---

## 0. The honest starting point

Pythia currently ships **no strategy that is known to be profitable**. The shipped set — EMA cross,
Bollinger revert, RSI reversal, MACD, Donchian, multi-timeframe momentum, BTC/ETH pairs — are
textbook indicators on daily-ish bars. They are the most widely known signals in existence. Anything
that obvious was arbitraged into noise decades ago; what survives of it is a small, regime-dependent
trend premium that a naive implementation gives straight back in costs.

The Prob-Edge "model" on Polymarket is worse than that: `model_prob` is an EWMA of the market's own
price. An EWMA of the price cannot disagree with the price except by lagging it, so its "edge" is a
lag artefact. It is fine as a plumbing demo. It is not a forecast, and the code says so.

So the plan is not "tune the parameters". It is:

1. Build the **cost model** that says what a strategy must beat.
2. Build the **validation pipeline** that no strategy can pass by luck.
3. Put **real, non-obvious edge candidates** through it and keep the survivors.
4. Make **execution** good enough that surviving edge is not lost in the fill.
5. Make the product better than the alternatives at the thing users actually struggle with, which is
   not signal generation.

Steps 1, 2, 4 and 5 are engineering with predictable outcomes. Step 3 is research and most candidates
will fail. That asymmetry is the whole point: the machinery is what makes failure cheap and fast.

---

## 1. The cost model — the bar every strategy has to clear

**Status: built, not yet calibrated.** `crates/pythia-core/src/costs.rs` holds the per-venue model;
the numbers live in `config/costs.json` (public fee schedules and typical spreads, shared with the
TypeScript engine and the Python lab). Paper fills and both backtesters charge it, results are reported
as gross, costs and net, and live fills are compared against it. What is missing is calibration from
recorded spreads and real fills, and live top-of-book depth for the impact term.

A backtest that ignores costs is a random-number generator with a nice chart. Until this was built,
Pythia's paper fill applied a flat 8 bps slippage and 6 bps fee and nothing else. Real costs, per venue:

| Component | Equities (Alpaca) | Crypto spot (Kraken/Binance/Bybit/OKX) | Prediction (Polymarket) |
|---|---|---|---|
| Commission | $0 | 10–40 bps taker, 0–20 bps maker | 0, but gas on Polygon |
| Half-spread | 0.5–5 bps (liquid), 20 bps+ (small caps) | 1–5 bps (majors), 30 bps+ (alts) | 100–500 bps — the dominant cost |
| Market impact | ~0 at retail size | ~0 at retail size, real in alts | large: thin books, you *are* the book |
| Overnight / funding | 0 (spot) | 0 (spot), ±yearly 10–30% (perps) | n/a |
| Borrow (shorts) | 25–500 bps/yr | n/a (spot cannot short) | n/a |
| Tax drag | jurisdiction-dependent; short-term rates are punitive on high-turnover strategies |

**The arithmetic that kills most retail bots.** A strategy trading 20 round trips a month at a 25 bps
all-in cost per round trip burns **60% of capital per year** in costs. To net 10% it must gross 70%.
Almost nothing does. Which yields the first hard design rule:

> **Turnover is the enemy.** Every increment of trading frequency must pay for itself, explicitly,
> in the backtest, after costs. A strategy that is profitable at 5 trades a month and unprofitable at
> 50 is not "a strategy that needs tuning" — it is a costs discovery.

### Deliverables

- `crates/pythia-core/src/costs.rs` — a per-venue `CostModel { taker_bps, maker_bps, half_spread_bps,
  impact_coeff, borrow_bps_yr, min_notional }`, calibrated from live quotes rather than guessed.
- Slippage estimated from the **actual order book** (top-of-book depth vs. our size), not a constant.
- The backtester reports **gross P&L, costs, net P&L** as three separate lines. A strategy whose
  costs exceed 40% of gross is flagged in the UI before it can be armed.
- **Realised-vs-expected slippage tracking**: every live fill records `fill_price − ref_price`. After
  30 fills the UI compares realised cost against the model. This is the number that tells a user
  their backtest was fiction, and no competitor shows it.

---

## 2. The validation pipeline — how a strategy earns real money

**Status: built.** `crates/pythia-core/src/validation.rs` judges all eight gates (pass, fail or
pending, with a reason and the number), the Strategies page shows them as a Strategy Passport, and the
engine refuses to set a strategy Live until gates 1 to 7 pass. The Optimizer page shows deflated
Sharpe and the OOS/IS ratio next to every result. No shipped strategy passes yet, which is the gates
working: an optimizer without gates is a machine for manufacturing overfit.

Concrete definitions the code uses: gate 1 judges the configured parameters on the first 60 % of
history; gate 4's neighbourhood is one grid step either side per parameter (all combinations, 60 % must
be net-positive in-sample); gate 5 splits bars by the 20-bar efficiency ratio (trending at 0.4 or more)
and by 20-bar realised volatility against its median; gate 7 counts only trades on real prices.

A strategy must pass, in order, and the UI must refuse to arm it live until it has:

1. **In-sample fit** — on the first 60% of history. Necessary, meaningless alone.
2. **Walk-forward** — rolling re-fit, out-of-sample evaluation. Report OOS/IS performance ratio; a
   ratio below 0.5 means the parameters are noise.
3. **Cost sensitivity** — re-run at 1×, 2× and 3× the modelled cost. If 2× costs kill it, live will.
4. **Parameter plateau** — the neighbourhood of the chosen parameters must also be profitable. A
   lone spike in the parameter surface is an overfit, not a discovery. (The Monte-Carlo optimizer
   already samples the surface; it must report plateau width, not just the best point.)
5. **Regime split** — separate results for trending/ranging, high/low volatility, and (for equities)
   bull/bear. A strategy that only works in one regime is fine *if* the regime filter is part of it
   and was not chosen after seeing the answer.
6. **Deflated Sharpe** — correct the Sharpe ratio for the number of configurations tried. Testing 500
   parameter sets and keeping the best is guaranteed to produce a Sharpe of ~2 from pure noise.
   Without this correction the optimizer page is actively harmful.
7. **Paper forward-test** — a minimum of 30 trading days and 30 trades on live prices, with realised
   slippage compared against the model.
8. **Live at minimum size** — the smallest size the venue accepts, until the live/paper P&L
   correlation is credible.

### Deliverables

- `crates/pythia-core/src/validation.rs` — the gate chain, each stage returning a pass/fail with a
  reason string.
- A **Strategy Passport** on the Strategies page: the eight gates as a checklist, each green/red with
  its number. Arming live is disabled until gates 1–7 are green.
- Deflated Sharpe and OOS/IS ratio surfaced on the Optimizer page next to every result.

---

## 3. Where edge could actually come from

Ranked by *feasibility for a self-hosted retail stack*, not by glamour. Each is a research project
with an explicit falsification test.

### 3.1 Cross-venue and cross-instrument mispricing — **best feasibility**

Pythia already talks to Kraken, Binance, Bybit, OKX and Alpaca simultaneously. Almost no retail tool
does. That is a structural advantage that costs nothing to exploit:

- **Basis / stablecoin dislocation.** BTC/USDT on Binance vs. BTC/USD on Kraken diverge whenever
  USDT wobbles or a venue has a liquidity event. Trading the *spread* is market-neutral: no
  directional forecast is required, which removes the hardest part of the problem.
- **Triangular inconsistency** within one venue (BTC/USD, ETH/USD, ETH/BTC). Rare, brief, and real.
- **Polymarket internal coherence.** Complementary outcomes on the same event must sum to 1. When
  they do not, the arbitrage is model-free — the one place a prediction market gives an edge without
  requiring a forecast. Needs order signing (§7.3).

**Falsification test:** log the spread series for 30 days without trading. If the spread rarely
exceeds round-trip costs, the opportunity does not exist at retail size. Answer known in a month, at
zero risk. This is the first thing to build.

### 3.2 Execution alpha — **highest certainty, smallest per-trade, applies to everything**

Not a strategy: a multiplier on every strategy. Detailed in §4. Ten basis points saved per round trip
on a strategy doing 20 round trips a month is 24 points a year, which is larger than most of the
"alpha" retail strategies claim. It is also the only item on this list that is *guaranteed* to work.

### 3.3 Time-series momentum, done properly — **modest, real, well-documented**

Cross-sectional and time-series momentum survive out-of-sample across decades and asset classes.
What kills retail implementations is turnover and position sizing, not the signal. Doing it properly
means: monthly-to-weekly rebalancing (not per-tick), volatility-scaled positions, a broad universe,
and no stop-losses inside the noise band. Expect a Sharpe around 0.4–0.7 — unglamorous, and far above
what a 5-minute EMA cross delivers after costs.

**Falsification test:** if the walk-forward Sharpe is below 0.3 after costs, drop it.

### 3.4 Volatility-regime and carry effects — **medium feasibility**

Realised-vs-implied volatility spreads, funding-rate carry on perpetuals, and term-structure signals
have documented persistence. Funding carry in particular is a genuine yield with a known and
measurable risk. Requires perpetuals support, which is currently out of scope (§9).

### 3.5 Event and news reaction — **feasible, needs care**

Post-earnings-announcement drift is one of the most robust anomalies in the literature. Requires an
earnings calendar and reaction measurement. The trap is that the naive version is a latency race
against people with better infrastructure; the durable version trades the multi-day *drift*, not the
first second.

### 3.6 Forecast ensembles on event markets — **built; unproven by construction**

**Status: implemented.** See [`docs/FORECASTING.md`](docs/FORECASTING.md) and the Predictions page.

An LLM asked "will BTC go up" produces a plausible sentence, not a calibrated probability. So the
implementation does not trust one, and does not trust ten either. Every source — the statistical
hypotheses and each model — is pooled in log-odds, weighted by a **measured Brier skill score against
the market on the same questions**, and shrunk back toward the market price by how little evidence
there is for it. A source that has not beaten the market gets exactly zero weight and cannot move an
order.

Two design choices carry most of the value:

- **Scoring data arrives in hours, not months.** Every event forecast also produces a derived
  directional forecast — `logistic(logit(model) − logit(market))` — which resolves on a timer. So the
  calibration machinery has data long before any election settles, and every source is scored
  continuously without a cent at risk.
- **The falsification test is the product.** The scoreboard is a page in the app, not a research
  note. Within a few hundred resolved forecasts it will say, with a number, whether any of this has
  skill.

The narrow version still worth adding is **structured extraction**: use the model to parse filings
and classify news as material/immaterial, and feed the extracted *facts* into a statistical model.
Language to the language model, probability to the statistics.

**The honest expectation:** most likely every source lands at zero skill on liquid markets, because
those markets are efficient. That is a real result, it costs nothing to establish, and it is worth
far more than a backtest that says otherwise.

### 3.7 Prediction-market coherence — **built; the only model-free edge here**

**Status: implemented.** The outcomes of one event must price to 1. When they sum to 0.96, buying
every leg costs 96 cents and pays a dollar, whatever happens — arithmetic, not a forecast. Breaks are
reported net of costs, with cost scaling by leg count, and near-misses stay visible so the question
"does this exist at my size?" gets a real answer.

Capturing them needs Polymarket order routing, which is gated for the reasons in §7.3.

---

## 4. Execution quality — the cheapest alpha there is

Alpaca equities are commission-free; the cost is entirely spread and timing. Crypto taker fees are
10–40 bps and maker fees are often zero or negative. So:

- **Post-only limit orders** where the strategy's urgency allows. Crossing the spread on a signal that
  is valid for hours is pure waste. Target: fill 70% of entries as maker.
- **Passive-then-aggressive escalation**: rest at the mid for N seconds, step toward the touch, cross
  only on timeout. The order-lifecycle state machine already built (submit → poll → cancel) is exactly
  the machinery this needs — it exists today.
- **Order slicing** for anything above ~1% of top-of-book depth.
- **Session awareness.** The open and close have the widest spreads and the worst fills; the middle of
  the session is cheapest. Cost per trade varies by more than 2× across a session.
- **Never market-order into a closed or thin book.** Already enforced: the Alpaca preflight refuses
  equity market orders outside regular hours rather than queuing them across an unknown overnight gap.

### Deliverables

- Limit-order support end-to-end (the connector layer already carries `limit_price`; the engine only
  emits market orders).
- An `ExecutionPolicy` per strategy: `Aggressive | Passive | Adaptive`.
- Realised slippage attribution per strategy, per venue, per hour of day, on the Analytics page.

---

## 5. Capital allocation and risk — where the compounding actually happens

The risk manager is the strongest part of the codebase: kill switch, daily-loss cap, drawdown
breaker, per-strategy budgets, fractional Kelly, volatility targeting, loss-streak cooldowns,
adaptive allocation. Phase D added the three portfolio-level pieces below (formulas in
`crates/pythia-core/src/engine/risk.rs`, live numbers on the Risk page):

- **Correlation-aware exposure (built).** Ten crypto longs are one trade with ten names on it. The
  book is measured as `E = sqrt(w' C w)`, signed notional per market against the return correlation
  over the last 60 closes, the same matrix the Correlation page draws. New entries are capped on
  `E` (`maxCorrelatedExposurePct`, default 40 % of equity) as well as on the raw sum, downsized to
  fit or refused with the reason in the journal. Correlations are measured on aligned time: candle
  markets on their shared bar times, tick markets on their shared tail, and a candle market against
  a tick market not at all. An unmeasurable pair counts as the worst case for its signs, `|w_a| |w_b|`:
  two longs move as one, and a long against a short is never credited as a hedge.
- **Kelly on measured edge (built).** Under 30 closed trades a strategy is still sized off
  `intent.confidence`. From 30 on it is sized off its *realised* record: `f = p - (1 - p) / b` on net
  returns, shrunk toward no edge by `n / (n + 30)`, at most quarter Kelly, never above what full
  confidence would deploy. A record with no edge sizes entries to zero, and stays there: the only
  way back is a parameter change, which starts a fresh record (and takes a live strategy back to
  paper). Saves from before the record rebuild it from the saved fills where they reconcile.
- **Drawdown-proportional de-risking (built).** Entries are multiplied by
  `1 - drawdown / maxDrawdownPct`: half size at half the limit, nothing new at the breaker.

- **Portfolio volatility target (built).** The same quadratic form with each notional weighted by its
  market's annual volatility, `sqrt(u' C u)`: one standard deviation of a year's P&L. Entries that
  would lift it over `portfolioVolTargetPct` (default 30 % of equity) are shrunk or refused.
- **Volatility spike trim (built, off by default).** The target above only stops entries. With
  `volSpikeTrimMult = k` set, a book that stays above k times its target for 30 minutes is cut back
  to the target, every position by the same share, at most once an hour, closing only. Off by
  default because it sells after the move: whether that pays is a question for the backtests, not
  a default.

---

## 6. Why a user would pick Pythia over what they already have

Honest competitive read:

| | Pythia | 3Commas / Cryptohopper | Freqtrade | QuantConnect | TradingView + broker |
|---|---|---|---|---|---|
| Self-hosted, keys never leave the machine | ✅ | ❌ cloud custody of keys | ✅ | ❌ | ❌ |
| Multi-venue in one engine (equities + 4 crypto venues + prediction) | ✅ | crypto only | crypto only | ✅ | ⚠️ per-broker |
| Native desktop app, no Docker, no Python env | ✅ | n/a (SaaS) | ❌ | n/a | n/a |
| Risk manager above every order, kill switch | ✅ | ⚠️ per-bot | ⚠️ config | ✅ | ❌ |
| Cost-aware validation gates before live | ✅ §2 | ❌ | ⚠️ manual | ✅ | ❌ |
| Realised-vs-modelled slippage tracking | ✅ §1 (needs live fills) | ❌ | ❌ | ⚠️ | ❌ |
| Order lifecycle that cannot desync from the venue | ✅ | ❓ | ✅ | ✅ | n/a |
| Bring-your-own LLM | ✅ | ⚠️ marketing | ❌ | ❌ | ❌ |

Three of those are already true and are the honest pitch today: **self-hosted multi-venue execution
with a sovereign risk manager, in an app you double-click.** The gates and the slippage tracking (built
in October 2026, the slippage side still waiting for live fills) are the differentiators, because they
attack the thing that actually loses users money. Not "which indicator", but "my backtest said 40% a
year and I lost 12%".

### The product principle

> Every competitor optimises for making a bot *easy to start*. Pythia should optimise for making a bot
> *hard to fool yourself with*.

Concretely, that means the features nobody else ships:

1. **The Strategy Passport** (§2) — a strategy visibly has not earned live money until it has.
2. **The reality gap report** — backtest vs. paper vs. live, side by side, with the cost decomposition
   that explains the difference. Most users have never seen this number for their own system.
3. **Refuse-with-a-reason** — Pythia already declines orders that cannot fill and says exactly why
   ("US market closed — next open …", "would open a short; shorts are disabled", "$4,210 needed,
   buying power $980"). Every other tool returns the broker's opaque error, if it returns anything.
4. **No lying about mode.** A position opened with real money is tagged `REAL` and the simulator will
   not close it — implemented, and the single most important safety property in the system.

---

## 7. Roadmap

### Phase A — Make the numbers honest (4–6 weeks) · *do this first*

- [x] `costs.rs`: per-venue cost model (defaults in `config/costs.json`)
- [ ] ...calibrated from live spreads and recorded books
- [x] Backtester reports gross / costs / net separately
- [x] Realised-slippage recording on every live fill, compared against the model
- [x] Deflated Sharpe + OOS/IS ratio in the optimizer
- [x] The eight validation gates, and the arm button that respects them

**Definition of done:** a user can see, for their own strategy, the gap between backtest and live, and
what it is made of.

### Phase B — Execution quality (3–4 weeks)

- [ ] Limit orders end-to-end; `ExecutionPolicy` per strategy
- [ ] Passive-then-aggressive escalation on the existing order state machine
- [ ] Slippage attribution by venue and hour on the Analytics page

**Definition of done:** median realised cost per round trip drops measurably against the market-order
baseline, and the improvement is visible in the UI.

### Phase C — The first real edge candidate (4–8 weeks, research)

- [ ] Cross-venue spread logger (§3.1) — 30 days of observation, no trading
- [ ] If spreads clear costs: market-neutral spread strategy, both legs, inventory-managed
- [ ] Time-series momentum done properly (§3.3), through the full gate chain

**Definition of done:** at least one strategy passes gates 1–7. If none does, that is a real answer
and the project says so rather than shipping a losing default.

### Phase D — Correlation-aware risk and portfolio sizing (2–3 weeks)

- [x] Risk manager consumes the correlation matrix
- [x] Kelly from realised edge once a strategy has 30+ trades
- [x] Drawdown-proportional de-risking
- [x] Volatility targeting at the portfolio level

### Phase E — Venue breadth

- [ ] **Coinbase Advanced Trade** — ES256 JWT auth. The only HMAC-less venue in the registry; needs a
      JWT signer, then it drops into the existing `Exchange` enum.
- [ ] **Perpetual futures** (funding carry, §3.4) — needs leverage-aware risk limits *first*.
- [ ] **Polymarket order signing** — see below.

### 7.3 Polymarket, and why it is deliberately last

Every other venue authenticates with a revocable, permission-scoped API key: a leaked Pythia key
costs a key rotation. Polymarket's CLOB is signed with a **Polygon private key** — a wallet, not a
credential. Whoever holds it can move everything in that wallet, forever, and no dashboard can revoke
it.

Putting that behind the same one-click arm flow as a broker key would be a different risk category
wearing the same UI. Doing it properly means:

1. A **dedicated wallet** holding only trading capital, never a main wallet.
2. A **capped USDC allowance** to the exchange contract, so the maximum loss from a bug or a
   compromise is bounded by the allowance rather than by the balance.
3. A **separate arm gate** with its own typed confirmation, and a key that lives in the OS keychain
   under a slot no other code path reads.
4. **Session-scoped signing** — the key is unlocked for a bounded window, not held for the process
   lifetime.

Until all four exist, `polymarket.rs` returns `Unimplemented` on every order path and the odds stay
read-only. That is a deliberate decision, not a gap.

---

## 8. How we will know it worked

Success metrics, in priority order. Note that "profitable" is deliberately not first — a profitable
month proves nothing, and treating it as proof is exactly the failure mode this document exists to
prevent.

1. **Zero desync incidents.** Pythia's book and the venue's never disagree without Pythia noticing
   and saying so. (Directly testable; the reconciliation pass and the order state machine exist.)
2. **Realised slippage within 1.5× of modelled**, across at least 100 live fills.
3. **Live/paper P&L correlation > 0.7** over 60 days for any strategy armed live.
4. **At least one strategy passing gates 1–7** on out-of-sample data.
5. **Positive net P&L after costs over 12 months**, on live capital, on that strategy.

Metric 5 is the goal. Metrics 1–4 are what make it more than a coin flip — and if metric 4 never
lands, the correct outcome is to say so publicly and keep the machinery, which is useful regardless.

---

## 9. Explicitly out of scope

Leverage above 1×, options, market making as a primary strategy, HFT or latency arbitrage,
copy-trading other people's signals, anything requiring a seed phrase or private key for a wallet the
user also keeps savings in, and any claim of guaranteed returns.

**Also permanently out of scope:** a default strategy that ships armed, a backtest figure quoted
without costs, and any UI that makes real money look like paper money.
