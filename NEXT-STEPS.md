# Next steps — handover

> Written 2026-07-27. Everything below is on branch
> `feat/live-execution-and-wallets`, pushed to
> <https://github.com/SenseiIssei/Pythia>. Nothing is merged to `main` yet.
>
> Companion docs: [`PROFIT-PLAN.md`](PROFIT-PLAN.md) (what must be true before
> real money), [`docs/BREAKTHROUGH.md`](docs/BREAKTHROUGH.md) (the algorithm
> roadmap), [`docs/FORECASTING.md`](docs/FORECASTING.md) (how predictions work),
> [`docs/LIVE-RUN.md`](docs/LIVE-RUN.md) (the live runbook).

---

## 0 · Get running at home (5 minutes)

```bash
git clone https://github.com/SenseiIssei/Pythia
cd Pythia
git checkout feat/live-execution-and-wallets
npm install
```

**Set the git identity before your first commit.** The machine default is wrong
on at least one of your machines:

```bash
git config user.email "superwarper@t-online.de"
```

```bash
git config user.name "SenseiIssei"
```

Then verify with `git log -1 --pretty='%an <%ae>'`. Never commit as
`jaho <j.hollwedel@visicon.eu>`, and never add a Co-Authored-By trailer.

### Run it

```bash
npm run tauri dev
```

Desktop app with the full engine. Or backend + web:

```bash
npm run server
```

```bash
npm run dev
```

For the web build to talk to the backend, put
`VITE_PYTHIA_SERVER=http://localhost:8787` in `.env.local` (gitignored).

### Check it still builds

```bash
npm run check
```

That runs `cargo test --workspace` (361 Rust tests, one benchmark
`#[ignore]`d), vitest (27 tests) and `npm run build`. The Tauri shell is a separate workspace:

```bash
cd src-tauri && cargo build
```

> **Windows note:** if `cargo` fails with `failed to find tool "C:\Program"`,
> unset the machine-scope `CC`/`CXX`/`CFLAGS`/`CXXFLAGS` vars first. The npm
> scripts already strip them; raw `cargo` does not.

---

## 1 · The single most important open item

**None of the venue code has ever run against a real API.** Signatures are
verified against each venue's documented test vectors, endpoints and payloads
follow their docs, and the whole order state machine is unit-tested — but no
order has ever actually reached a broker.

Do this first, before any new features:

- [ ] Alpaca **paper** keys into *Settings → Alpaca*
- [ ] Live page → *Test paper connection* → expect `ACTIVE` + buying power
- [ ] Arm with **Dry-run** on. Confirm the journal shows
      `DRY-RUN submit …` → `dry-run: not submitted`
- [ ] Dry-run off, still paper endpoint, arm, and press **Connection test** on
      an equity market (Live page, per-market trace). Watch for
      `PAPER-LIVE submit` → `LIVE FILL`. Setting *Donchian Breakout · Equities*
      to Live now needs a green Strategy Passport (§2), so the connection test
      is the way to exercise the pipeline
- [ ] Cross-check every fill against the Alpaca dashboard. **If they disagree,
      Alpaca is right** — that is a bug in Pythia, write it down
- [ ] Restart mid-session with a position open. Confirm reconciliation picks it
      up and journals `Reconciled … — broker wins`
- [ ] Repeat the connection test for one crypto exchange (Kraken is the most
      forgiving)

Until this is done, treat every venue connector as unproven code.

---

## 2 · PROFIT-PLAN Phase A — make the numbers honest

**Built on `feat/honest-numbers` (2026-10-06).** The machinery exists; what is
left is calibration, which needs real fills and recorded books.

- [x] `crates/pythia-core/src/costs.rs`: per-venue `CostModel { taker_bps,
      maker_bps, half_spread_bps, impact_coeff, borrow_bps_yr, min_notional }`
      with per-symbol overrides and square-root impact against top-of-book
      depth. Defaults live in `config/costs.json` (embedded at build time,
      overridable at runtime with `PYTHIA_COSTS_FILE`; the server also picks up
      the repo file). Paper fills and both backtesters use it; the flat 8 bps +
      6 bps is gone
- [ ] **Calibrate `config/costs.json`** from recorded data. The shipped numbers
      are public fee schedules and typical spreads, not measurements. Spread and
      depth should come from the data recorder; fees from your actual tier
- [x] Backtester reports **gross P&L, costs, net P&L** as three separate
      figures (Rust `PnlBreakdown`, the Backtest, Composer and Analytics pages),
      flagged when costs exceed 40 % of gross
- [x] Realised slippage recorded on every live and paper-live fill next to the
      model's expectation, in the execution policy's own fill record. The
      Analytics page shows count, median realised, median modelled and their
      ratio per venue
- [x] Deflated Sharpe and out-of-sample/in-sample ratio next to every result on
      the Optimizer page, from a real-candle sweep in the Rust core (fit on 60 %,
      hold out 40 %). The walk-forward report carries the OOS/IS ratio too
- [x] The eight validation gates (`PROFIT-PLAN.md` §2) in
      `crates/pythia-core/src/validation.rs`, and a **Strategy Passport** on the
      Strategies page. The engine refuses *Live* until gates 1 to 7 are green
- [ ] Feed `ExecContext` real spread and depth, and pass live top-of-book depth
      into `CostModel::impact_bps` instead of the per-instrument default

**Done when:** you can see, for your own strategy, the gap between backtest and
live, and what it is made of. That is now true once a strategy has live fills;
until then the realised-slippage table is empty by design.

Things worth knowing from building it:

- **The deflated Sharpe was mis-scaled before this branch.** It was fed
  annualised Sharpes, which inflates the z-score by the square root of the bars
  per year and turns the verdict into a step function. Fixed in
  `metrics::deflated_sharpe_annualised`. The verdicts in `docs/VALIDATION.md`
  predate the fix; re-run `npm run validate` before quoting them.
- **The research backtester only exits on stops**, so several EMA parameter sets
  hold the very same position out-of-sample and score identically. That is a
  property of the backtest design, not of the sweep, and worth a look before
  trusting any parameter surface.
- **Nothing can go live today, on purpose.** Gate 7 needs 30 trading days and
  30 closed trades on real prices. To prove keys and the broker work, use the
  *Connection test* on the Live page: it sends one buy at the venue's minimum
  size and is the only order that needs no passport.

---

## 3 · BREAKTHROUGH roadmap — where it stands

| | Item | Status |
|---|---|---|
| 1 | Hierarchical calibration (partial pooling) | ✅ shipped |
| 2 | Correlation-aware ensemble weighting | ✅ shipped |
| 3 | Adaptive execution as a contextual bandit | ✅ shipped |
| 4 | Cross-venue statistical arbitrage | ⬜ **next** |
| 5 | LLM as extractor, statistics as forecaster | ⬜ |

### 4 · Cross-venue spread — *do the cheap half first*

A few hours of work for a real answer at zero risk. **Do not build the strategy
yet.**

- [ ] Log the BTC and ETH spread between two venues (Kraken USD vs Binance USDT
      is the widest and most interesting) every 15 s to a CSV or the journal
- [ ] Leave it for 30 days
- [ ] Then look: does the spread ever exceed the round-trip cost of both legs?

If it does not, the opportunity does not exist at retail size, and you have
learned that for a few hours instead of a few months. If it does, *then* build
the Ornstein–Uhlenbeck entry model with inventory caps
(`docs/BREAKTHROUGH.md` §3.4).

### 5 · LLM as extractor

Highest ceiling, highest variance. The concrete first win is **nested
prediction-market questions**: P("Fed cuts in July") ≤ P("Fed cuts before
September") is a hard logical constraint, and a violation is arbitrage in the
same model-free sense as the coherence check that already exists. An LLM is
excellent at spotting that two questions are nested; the arithmetic that follows
needs no model at all.

- [ ] Extend `forecast/coherence.rs` with implication constraints
- [ ] Use the LLM only to *identify* nesting, never to price it

---

## 4 · Risk manager gaps (PROFIT-PLAN §5)

The risk manager is the strongest part of the codebase, but three things are
missing and all three are small:

- [ ] **Correlation-aware exposure.** Ten crypto longs are one trade with ten
      names on it. The Correlation page computes the matrix; the risk manager
      does not consume it. Cap gross exposure on *correlation-adjusted*
      exposure, not the raw sum
- [ ] **Kelly on measured edge.** `place_from_intent` sizes off
      `intent.confidence`, which is an indicator reading, not a win probability.
      Once a strategy has 30+ trades, size from its realised win rate and payoff
      ratio, shrunk toward the prior
- [ ] **Drawdown-proportional de-risking.** Halve size at 50 % of the drawdown
      limit rather than trading full size straight into the breaker

---

## 5 · Venue breadth

- [ ] **Coinbase Advanced Trade** — the only non-HMAC venue in the registry.
      Needs an ES256 JWT signer, then it drops into the existing `Exchange` enum
      with no other change. It is listed in the UI and refuses to trade
- [ ] **Alpaca crypto** — the connector already handles the `crypto` asset class
      (24/7, no clock gate). Only the seeded market list needs entries
- [ ] **Perpetual futures** for funding carry — needs leverage-aware risk limits
      **first**, not after
- [ ] **Polymarket order signing** — deliberately last. Its CLOB signs with a
      Polygon private key, not a revocable API key. All four gates in
      `PROFIT-PLAN.md` §7.3 must exist before a single order: dedicated wallet,
      capped USDC allowance, separate arm flow, session-scoped signing

---

## 6 · UI — finish the beginner path

Simple mode ships and is the default. What is left (`docs/BREAKTHROUGH.md`
Part II):

- [ ] **First-run walkthrough**, four screens: this is practice money · here is
      what it is doing · here is the stop button · here is how you would go live
      and why you should not yet
- [ ] **One-sentence explanations on hover** for every number: "Worst dip — the
      biggest fall from a high point. Smaller is calmer."
- [ ] **Goal-shaped setup.** Ask "how much are you willing to lose in a bad
      month?" and derive the risk limits, instead of asking for
      `maxDailyLossPct`
- [ ] **Weekly plain-English report.** "This week Pythia made 14 trades, was
      right on 8, finished up $212. Its predictions have now been checked 340
      times and are still not beating the market, so it is not betting on them."
- [ ] **Recoverable mistakes** — plain-language confirmation on anything
      destructive, and undo where physics allows

**The metric to test against:** hand the app to someone who has never traded and
see whether they can answer these in two minutes — is real money at risk, am I
up or down today, how do I make it stop. If not, the default view has failed
regardless of the algorithms underneath.

---

## 7 · Housekeeping

- [x] **JavaScript tests.** vitest covers `navFor`/`isVisible`, `uiMode`,
      position accounting, the shared cost model and the browser paper engine.
      `npm run check` runs `cargo test --workspace`, vitest and the build in one
      go
- [ ] **Open a PR** for `feat/live-execution-and-wallets` and squash-merge when
      §1 is done. It is a large branch — five commits, all self-contained
- [ ] The `#[ignore]`d benchmark in `engine/mod.rs` is worth re-running after any
      forecasting change:
      ```bash
      cargo test --release -p pythia-core -- --ignored --nocapture bench_
      ```
- [ ] `ExecContext` wants spread and top-of-book depth. That needs quote data
      the market feed does not carry — when it does, it is a change to that one
      struct and nothing else

---

## 8 · Things that are easy to get wrong

Recorded because each one already cost a wrong first attempt:

1. **Two sources can disagree loudly on every question and still have perfectly
   correlated errors.** If both are constant forecasters, each one's error moves
   only with the outcome. Independence is being wrong at *different times*, not
   disagreeing about the level.
2. **A pure `1.004^i` price series has exactly zero volatility.** Any test of a
   drift model needs real bar-to-bar noise or the z-score goes infinite and the
   test proves nothing.
3. **The bandit exploring an untried arm is correct behaviour, not a bug.** A
   test that demands it immediately pick the known-cheap arm is wrong.
4. **`serde` `rename_all` is per-struct.** `EngineState` was missing it, so
   `forecast_stats` reached the frontend under a name the TypeScript type did not
   have — invisible in Rust, `undefined` in the UI. There is now a wire-contract
   test; keep it passing.
5. **Ollama needs no API key**, so `configured_in_env` reports it as ready on
   every machine. It must be opted into explicitly or it joins every ensemble and
   fails against a local server nobody is running.
