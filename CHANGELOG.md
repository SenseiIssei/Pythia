# Changelog

All notable changes to Pythia. Versions follow [Semantic Versioning](https://semver.org); while the
major version is 0, a minor release may change behaviour.

## 0.5.1 (2026-10-21)

- Installers for Windows (setup .exe), macOS (universal .dmg) and Linux (.AppImage, .deb, .rpm),
  built by GitHub Actions from the version tag.
- `pythia`, a command line over the engine's HTTP API: status, list and show autopilots, pause,
  resume, stop, kill switch, preflight, watch, and `pythia serve` to start the headless engine.
  Shipped per platform together with `pythia-server`.
- README in eight languages with a plain architecture picture.

## 0.5.0 (2026-10-21)

Everything since 0.4.0 (2026-07-22): the autopilots, the research lab and its first full round of
studies, perps on paper, the model zoo, Telegram alerts and a calmer app.

### Engine

- Real OHLC candles drive the indicators; strategies fire once per closed bar and every market is
  badged `real bars` or `sim`.
- Gated live execution on Alpaca and the Kraken, Binance, Bybit, OKX and Coinbase spot connectors,
  with an order lifecycle that cancels at the venue on timeout, books partial fills once and
  reconciles against the broker (the broker always wins).
- Alpaca paper and live keys kept apart; extended hours as an opt-in; a readiness checklist, a
  per-market routing trace and a one-click test order on the Live page.
- Engine state persists across restarts (`PYTHIA_STATE_FILE`): positions, ids, client order ids,
  pending orders and forward records survive, and an unreadable state file is never overwritten.
- Lab strategies trade in the engine as books with their evidence attached; the auto pick reads the
  lab's forward evidence; experimental books are never auto-picked and run only where an autopilot
  names them.
- Strategy passports, and a live switch that respects them; hand orders never go live.
- Configurable crypto universe and US equity list, with Alpaca as a keyless feed for every coin.
- Candlestick patterns (the lab's 74 definitions, parity-tested) as a strategy kind, shipped paused
  as research with no edge.
- An append-only record of every real fill, with a CoinTracking export and a FIFO preview using
  German tax dates.

### Autopilots

- An amount that trades itself until stopped or a stop rule fires, on paper or on a venue's demo
  account; several run side by side as sub-accounts, each with its own book.
- Several lab books per autopilot, netted per coin, with a re-pick by evidence; a re-pick waits for
  the next lab signal instead of trading on its own.
- A running autopilot can be changed in place; a changed amount rescales its curve.
- Portfolio autopilots across crypto and US shares, chosen automatically or by hand, with a blended
  benchmark.
- Every crypto autopilot is held against BTC bought and held and against BTC above its 200-day
  average.
- Fixes for stale marks, late fills, cash checks, rounding dust, broker corrections, Alpaca's fee
  gap on a shared account and orders under the venue minimum.

### Perps

- Perps demo route with Kraken Futures and Bybit linear connectors: shorts on perps only, margin
  checks, funding per position, reconciliation.
- Perps paper books for M4 (reg7n on the coins Kraken Futures lists) and the funding carry, with
  signed weights; setup, long, short and funding shown in the app.

### Risk and costs

- Correlation-adjusted exposure caps, sizing on measured edge after 30 trades, drawdown-scaled
  entries, a portfolio volatility target and a volatility spike trim.
- A per-venue cost model calibrated from recorded order books replaces the flat guess; analytics
  show gross, costs and net as three figures; realised against modelled slippage per venue.
- Maker limits on the Alpaca crypto route, with fill statistics per route.

### Research lab (verdicts)

Every study is pre-registered, judged out of sample after costs and deflated over all trials ever
made (1,836 at this release). The full table is in `research/lab/README.md`.

- **Passed as registered, not confirmed:** the M4 residual (perps long/short beyond low vol and BTC,
  Sharpe 0.96 at 41 bps) and the funding carry (0.74 at 10 bps); both fail deflation and run only
  as experiments.
- **Run on paper as labelled experiments (failed deflation):** breakout top 10, momentum (daily,
  regime, seven weekly tranches), the tranche book with a MAX or Korean-premium filter, memecoin
  rotation and momentum, the 4h pullback trend and BTC above its 200-day average.
- **Failed or killed:** cross-venue spread, hourly meta-labels, spot-perp carry, the regime and HMM
  gates, daily vol for sizing, blends, ETF trend, fast and maker-only strategies, vol management,
  daily meta-labels, wider Alpaca universes, listings, S&P 500 ranking, intraday equities, the
  overnight drift, book portfolios, flow overlays, exit overlays, equity early detection,
  candlestick patterns, Polymarket models after the spread, the factory's genome, the gated BTC
  comparison, the earnings premium, index deletions, seasonality, quality and issuance, turn of the
  month, VIX carry, ETF routing, the crypto open gap, BTC variance premium, trend shorts, the
  deleveraging flush and the Kraken funding gap.
- **Too early or not run:** CS2 skins, Pokemon cards, the real-time pump.fun lab, the Crypto plus
  SPY forward test, pump.fun activity, insider purchases and the treasury premium.
- A strategy factory that breeds long-only rules from a typed grammar and holds them to the same
  bar; a forward report that holds every paper book and autopilot against its backtest; a forward
  audit and an autopilot cost audit.

### Models

- `pythia-ml` crate: LightGBM and ONNX inference with train/serve parity and model cards.
- M1 hourly volatility live in shadow mode; M2 weekly coin ranking in shadow; a model zoo with
  champion and challenger, daily shadow scores, drift checks and one retrain entry point.
- Models that beat their baseline: M1 volatility, M8q return quantiles, M8u upper tail, M2 plus low
  vol, the delisting hazard. Pythia-Net retired after three attempts that did not beat M2.

### AI

- Claude 5 models with a hard budget and a persisted ledger; metered calls for lab jobs.
- A daily brief and weekly review, news sentiment and a Polymarket forecaster, all scored like any
  other forecaster and shown against our own models.

### Alerts

- Telegram and webhook alerts for engine events and the lab: cards with trades tables, a daily
  digest with charts, a weekly report, quiet hours, categories and a mute that survives a restart.
- Every message in English or German.

### App

- A design system with light and dark themes, AA contrast enforced by a test, and a calm page kit
  across every page.
- Simple view by default, advanced behind one switch; onboarding, a legal gate and plain-language
  explanations.
- New pages: Autopilot, Activity, Notifications, Lab, Research, Models, Cards (Pokemon), CS2 Skins,
  and the pump.fun wallet page; bottom tabs on phones.

### Data and ops

- A 24/7 market data recorder (books, funding, open interest, liquidations) and verified history
  backfills into a parquet lake.
- One job table with a runner, health checks over every job and engine, and safe deploy scripts.
- Collectors for flow data, Polymarket, CS2, Pokemon cards and pump.fun, all read only.

### Docs

- New README with charts redrawn from the result files by `scripts/readme_charts.py`.
- Runbooks for demo trading, perps demo, alerts, models, the Claude API, real money readiness and
  the pump.fun live test.
- Removed the July handover notes (`NEXT-STEPS.md`) and the screenshots of the old interface.

## 0.4.0 (2026-07-22)

Multi-venue paper trading, the AI signal providers, the strategy composer, backtests, the
Monte-Carlo optimizer and the desktop, server and browser runtimes.
