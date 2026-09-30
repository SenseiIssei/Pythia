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
cargo test --workspace && npm run build
```

306 Rust tests should pass (one benchmark is `#[ignore]`d). The Tauri shell is a separate workspace:

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
- [ ] Dry-run off, still paper endpoint, arm, set *Donchian Breakout · Equities*
      to **Live**. Watch for `PAPER-LIVE submit` → `LIVE FILL`
- [ ] Cross-check every fill against the Alpaca dashboard. **If they disagree,
      Alpaca is right** — that is a bug in Pythia, write it down
- [ ] Restart mid-session with a position open. Confirm reconciliation picks it
      up and journals `Reconciled … — broker wins`
- [ ] Repeat the connection test for one crypto exchange (Kraken is the most
      forgiving)

Until this is done, treat every venue connector as unproven code.

---

## 2 · PROFIT-PLAN Phase A — make the numbers honest

**Partly started, and it outranks every algorithm below.** A backtest that ignores
costs is a random-number generator with a nice chart, and the app currently
applies a flat 8 bps slippage + 6 bps fee to every paper fill.

> **Update after merging `feat/real-bars-and-opus5`:** the deflated Sharpe item
> below is partly done, just not on the Optimizer page. `crates/pythia-core/src/research/`
> has a walk-forward harness on real daily candles (anchored folds, parameters
> fitted in-sample, scored only out-of-sample) and computes the deflated Sharpe
> ratio against the number of parameter sets tried. Its backtester fills on the
> next bar's open and charges fee + slippage on both sides via a flat
> `CostModel`. It runs as `GET /api/research/validate` / `npm run validate`, and
> `docs/VALIDATION.md` records the first run. Still open: the Optimizer page
> does not use it, there is no out-of-sample/in-sample ratio yet (the per-fold
> in-sample Sharpe is recorded, not compared), costs are one flat model rather
> than the per-venue `costs.rs`, and gross/cost/net are not reported separately.

- [ ] `crates/pythia-core/src/costs.rs` — per-venue `CostModel { taker_bps,
      maker_bps, half_spread_bps, impact_coeff, borrow_bps_yr, min_notional }`,
      calibrated from live quotes rather than guessed
- [ ] Backtester reports **gross P&L, costs, net P&L** as three separate lines
- [ ] Record realised slippage on every live fill and compare against the model
      (the execution bandit already stores the raw material — see
      `ExecPolicy::report`)
- [ ] Deflated Sharpe + out-of-sample/in-sample ratio on the Optimizer page
      (deflated Sharpe exists in the walk-forward validator, see the note above).
      Without this, testing 500 parameter sets and keeping the best manufactures
      a Sharpe of ~2 from pure noise, and the page is actively harmful
- [ ] The eight validation gates (`PROFIT-PLAN.md` §2) as a
      `crates/pythia-core/src/validation.rs`, and a **Strategy Passport** on the
      Strategies page that disables *Live* until gates 1–7 are green

**Done when:** you can see, for your own strategy, the gap between backtest and
live, and what it is made of.

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

- [ ] **There is no JavaScript test runner.** No vitest, no jest. The Rust side
      has 306 tests; the TypeScript side has none. `src/uiMode.ts`,
      `navFor`/`isVisible` and the paper engine are the obvious first targets
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
