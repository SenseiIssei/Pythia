# Pythia 0.5.0

Pythia 0.5.0 turns the cockpit into a system that trades on paper by itself and checks its own
claims. Autopilots run lab strategies on the Alpaca paper account and on perps paper, a research
lab decides what they may trade, and every study is pre-registered and deflated over all 1,836
trials made so far. Nothing in this release trades real money unless you arm it.

## Highlights

- **Autopilots.** Give one an amount and it trades a lab book until you stop it or a stop rule
  fires. Run several side by side, each with its own book, each held against BTC and against BTC
  above its 200-day average. Portfolio mode spans crypto and US shares.
- **Research lab.** 69 studies with written verdicts: pre-registered, out of sample, costs in
  every number, a deflated Sharpe over the whole pool of tries. A strategy factory breeds rules and
  holds them to the same bar. A daily forward report holds every paper book against its backtest.
- **Perps on paper.** Kraken Futures and Bybit linear connectors with shorts, margin checks and
  funding per position; the M4 and funding carry books run as experiments.
- **Models.** A `pythia-ml` crate for LightGBM and ONNX inference with train/serve parity, and a
  model zoo with champion, challenger and drift checks.
- **Alerts.** Telegram and webhook cards for fills, rebalances and readiness, a daily digest with
  charts and a weekly report, in English or German.
- **A calmer app.** A new design system with light and dark themes, a simple view by default, and
  new pages for Autopilot, Lab, Research, Models and Activity.
- **Optional Claude API.** A budgeted daily brief, news sentiment and a Polymarket forecaster,
  scored like any other forecaster.

## Honest results

- The best book, a Donchian breakout on the ten most liquid coins, makes Sharpe 1.17 out of sample
  from 2024 at 35 bps, against 0.74 for BTC bought and held. It fails deflation: the best of 1,836
  noise trials would show about 2.69.
- Two perps long/short studies passed their registered tests (M4 residual 0.96 at 41 bps, funding
  carry 0.74 at 10 bps). Neither survives deflation, so both run only as labelled experiments.
- Of 69 studies, 43 failed or were killed, 7 run on paper as experiments, 2 passed without
  confirmation and 5 produced a model that beats its baseline.
- The paper autopilots started on 15 October 2026. After six days the main Auto-Pick was up
  0.48 % while BTC rose 3.22 %. Far too early to judge; the record is public from day one.

Charts and sources: the README's "Honest results" section and `research/lab/README.md`.

## Upgrade notes

- **Version 0.5.0** in `package.json`, every crate and `tauri.conf.json`. Rebuild the desktop app
  and the server.
- **Keep your state.** Set `PYTHIA_STATE_FILE` on the server so positions, pending orders and
  forward records survive restarts. An unreadable state file is left untouched, never overwritten.
- **New, all optional settings:** `PYTHIA_DEMO_EXCHANGE=alpaca` routes crypto demo orders to the
  Alpaca paper account; `PYTHIA_PERPS_DEMO` picks the perps demo venue; `PYTHIA_ALERT_WEBHOOK` or
  `PYTHIA_TELEGRAM_BOT_TOKEN` with `PYTHIA_TELEGRAM_CHAT_ID` turn on alerts; `PYTHIA_LAB_ONLY` runs a
  headless engine for lab books only. See `.env.example` and the runbooks in `docs/`.
- **Lab:** install `research/lab/requirements.txt` into a fresh environment; studies read
  `PYTHIA_DATA` and write to `PYTHIA_REPORTS`, never into the data folder.
- **Removed:** the July handover notes (`NEXT-STEPS.md`) and the screenshots of the old interface.
- **Safety is unchanged:** paper first, live only when you arm it with your own keys, no
  withdrawal function anywhere. Read `SAFETY.md` before going live.
