# Pythia

English · [Deutsch](docs/i18n/README.de.md) · [简体中文](docs/i18n/README.zh-CN.md) · [日本語](docs/i18n/README.ja.md) · [한국어](docs/i18n/README.ko.md) · [Español](docs/i18n/README.es.md) · [Français](docs/i18n/README.fr.md) · [Português](docs/i18n/README.pt-BR.md)

Pythia is a trading cockpit that starts on paper and stays there until a strategy has earned more. It has a Rust engine, a desktop app and a web UI on top of it, and a research lab in Python that decides what the engine may trade. The lab counts every idea it ever tried, so a lucky backtest does not get through.

No strategy in here is known to be profitable. Read [SAFETY.md](SAFETY.md) before you connect a real account.

<table>
  <tr>
    <td width="50%"><img src="docs/img/app-home.png" alt="Home screen"></td>
    <td width="50%"><img src="docs/img/app-autopilot.png" alt="Autopilot screen"></td>
  </tr>
</table>

Screenshots from a development build with sample data.

## Download

The [latest release](https://github.com/SenseiIssei/Pythia/releases/latest) has:

| Platform | File |
|---|---|
| Windows | `Pythia_<version>_x64-setup.exe` |
| macOS (Apple silicon and Intel) | `Pythia_<version>_universal.dmg` |
| Linux | `.AppImage`, `.deb` or `.rpm` |
| Command line | `pythia-cli-<version>-<platform>`: `pythia` and the headless engine `pythia-server`, see [cli/README.md](cli/README.md) |

The builds are not code-signed yet. Windows asks once (More info, then Run anyway); on macOS, right-click the app and choose Open the first time.

## What it does

- An autopilot is an amount of money that trades one strategy on its own until you stop it or a stop rule fires. Several run side by side, each measured against BTC.
- Crypto, US shares and ETFs trade on the Alpaca paper account. The long/short books trade perps on paper, or on a Bybit demo account if you add demo keys.
- The risk manager sits in front of every order: kill switch, daily loss and drawdown limits, exposure caps, volatility targeting. If something is unclear, it refuses.
- Every study in the lab is written down before its first run, tested out of sample after costs, and its Sharpe is deflated by the number of trials so far.
- Models (volatility, coin ranking, return quantiles) are trained in the lab and served by the engine. They run in shadow before they can affect a trade.
- Alerts go to Telegram or any webhook, in English or German.

## Architecture

<img src="docs/img/architecture.svg" alt="Pythia: UI on top, the Rust engine, the research lab and recorder, the markets at the bottom" width="100%">

A lab book only reaches an autopilot together with its evidence. The auto pick ranks books by that evidence and by their forward record, and an experimental book only runs where an autopilot asks for it by name.

## Results so far

All numbers come from the lab's result files or the engine's own records. [`scripts/readme_charts.py`](scripts/readme_charts.py) draws every chart below and names its sources.

<img src="docs/img/scoreboard.png" alt="Out-of-sample Sharpe of the tested strategies against BTC, gated BTC and the noise bar" width="100%">

The best book is a Donchian breakout on the ten most liquid coins: Sharpe 1.17 since 2024, against 0.74 for holding BTC. It still does not pass deflation. With 1,836 trials counted, the best of that many pure-noise strategies would show about 2.69.

Two perps long/short studies passed their registered tests (the M4 residual and a funding carry). Neither survives deflation, so both run as experiments only. Most of the momentum books turn out to be BTC's 200-day filter in disguise: on days the filter is off, all of them lose money.

<img src="docs/img/forward.png" alt="Forward record of the paper autopilots since 15 October 2026 against BTC" width="100%">

The paper autopilots started on 15 October 2026. After six days the main auto pick is up 0.48 % and BTC is up 3.22 %. That is far too short to mean anything; the chart is here so the record is public from day one.

<img src="docs/img/research_funnel.png" alt="Trial pool growth and the verdict of every study" width="100%">

69 studies so far: 43 failed or were stopped, 7 run on paper as labelled experiments, 2 passed as registered without confirmation, 5 produced a model that beats its baseline. Every verdict is listed in [`research/lab/README.md`](research/lab/README.md).

<img src="docs/img/by_year.png" alt="Sharpe per year for the books that still run" width="100%">

To redraw the charts:

```bash
pip install matplotlib
PYTHIA_DATA=/path/to/lab/data python scripts/readme_charts.py
```

Without `PYTHIA_DATA` the forward chart is skipped.

## Getting started

You need Node.js (current LTS), Rust 1.85 or newer and, for the lab, Python 3.

Desktop app:

```bash
npm install
npm run tauri dev
npm run tauri build
```

Server and web UI:

```bash
cp .env.example .env
npm run server
```

```bash
echo "VITE_PYTHIA_SERVER=http://localhost:8787" > .env.local
npm run dev
```

The server listens on `127.0.0.1:8787` (`PYTHIA_BIND` changes it). Keys in `.env` are optional; without them everything stays on paper. Without `VITE_PYTHIA_SERVER` the web UI runs a small paper engine in the browser.

Research lab:

```bash
cd research/lab
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python -m pytest tests
```

The data comes from the recorder in `research/recorder` and its history backfill. [`research/lab/README.md`](research/lab/README.md) lists every study, [`research/ops/README.md`](research/ops/README.md) the scheduled jobs.

Checks:

```bash
npm run check
npm run preflight
npm run security:scan
```

On Windows the npm scripts remove `CC` and `CXX` from the environment, because paths with spaces break native Rust builds.

## Layout

| Path | Contents |
|---|---|
| [`crates/pythia-core`](crates/pythia-core) | Engine: strategies, risk, autopilots, execution, venues, forecasts, alerts |
| [`crates/pythia-ml`](crates/pythia-ml) | Model inference (LightGBM, ONNX) with parity tests against the lab |
| [`server`](server) | HTTP and WebSocket server over the engine |
| [`cli`](cli/README.md) | `pythia` command line |
| [`src-tauri`](src-tauri) | Desktop app |
| [`src`](src) | React UI |
| [`research/lab`](research/lab/README.md) | Studies, models, paper books, strategy factory |
| [`research/recorder`](research/recorder/README.md) | Market data recorder and history backfill |
| [`research/ops`](research/ops/README.md) | Job table, health checks, deploy scripts |
| [`docs`](docs) | Runbooks for [demo trading](docs/DEMO.md), [live runs](docs/LIVE-RUN.md), [alerts](docs/ALERTS.md), [models](docs/MODELS.md), [the Claude API](docs/AI.md) and the [readiness rule](docs/LIVE-READINESS.md) |

## Safety

- A fresh install trades nothing real. Autopilots start on paper or on a venue's demo account.
- Live trading needs your own keys and a typed confirmation per venue. Nothing arms itself.
- Keys live in the OS keychain or the server's environment and are never logged or sent to the UI.
- Pythia has no withdrawal, deposit or transfer function. Give API keys trade permission only.
- Crypto spot is long only, shorts exist only on perps, Polymarket is read only.

[SAFETY.md](SAFETY.md) has the full list. Security issues go through [SECURITY.md](SECURITY.md).

## License

[MIT](LICENSE). Market data from Alpaca, Binance, Kraken, Bybit, OKX, Coinbase, Deribit, DefiLlama, Polymarket and SEC EDGAR; each source's terms apply to its data. If Pythia is useful to you, you can [support it on Ko-fi](https://ko-fi.com/senseiissei).
