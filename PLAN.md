# Pythia — Master Plan

> An autonomous, multi-venue prediction & trading engine with a native desktop cockpit.
> Prediction markets (Polymarket) + crypto exchanges + equities (Alpaca), unified behind
> one strategy engine, one risk manager, and one neon control panel.

**Status (0.5.1, November 2026):** this is the original design document. Paper trading, gated live
execution, autopilots and the research lab are built; what changed in each release is in
[`CHANGELOG.md`](CHANGELOG.md), and the lab's verdicts are in
[`research/lab/README.md`](research/lab/README.md). The plan from here, with a comparison and the order
of work, is [section 10](#10-what-comes-next-written-2026-11-25). **Read [`SAFETY.md`](SAFETY.md) before you flip
anything to live.**

---

## 0. The one-paragraph pitch

Pythia watches a set of markets you care about, forms a probabilistic *edge estimate* for each
(from models, signals, or manual input), sizes a bet/trade against that edge using a disciplined
risk model, and — if and only if you have explicitly armed a strategy for live execution — routes
the order to the venue. Everything runs first in **paper mode** against a simulated matching engine
so you can prove a strategy is profitable on paper before a single real cent is at risk. A global
kill switch and hard risk limits sit above every strategy and cannot be bypassed.

---

## 1. Design principles (non-negotiable)

1. **Paper-first, always.** New strategies are born in simulation. Going live is a deliberate,
   per-strategy, typed-confirmation action — never a default, never global.
2. **The risk manager is sovereign.** No strategy can place an order that violates a global limit
   (max daily loss, max position size, max open exposure, kill switch). Risk checks happen in the
   execution path, not in the strategy's good intentions.
3. **Keys are yours.** API keys/secrets are entered by you, stored encrypted in the OS keystore,
   never committed, never logged, never sent anywhere except the venue they belong to.
4. **Every decision is auditable.** Every signal, sizing decision, order, fill, and rejection is
   written to an append-only journal. You can reconstruct *why* the bot did anything.
5. **Fail closed.** On any ambiguity — lost connection, stale data, failed risk check, unparseable
   response — the engine halts that strategy rather than guessing.
6. **The UI never lies about mode.** Paper vs. live is unmissable: color, banner, and a persistent
   badge. You should never be confused about whether real money is in play.

---

## 2. What "the whole thing" is (system architecture)

```
┌──────────────────────────────────────────────────────────────────────┐
│  DESKTOP COCKPIT  (Tauri v2 window · React 19 · neon UI)               │
│  Dashboard · Markets · Positions · Strategies · Risk · Journal · Cfg   │
└───────────────▲───────────────────────────────────────────┬───────────┘
                │ Tauri IPC (typed commands + events)        │
┌───────────────┴───────────────────────────────────────────▼───────────┐
│  ENGINE CORE  (Rust · tokio async runtime · runs even if UI closed)    │
│                                                                        │
│   ┌────────────┐   ┌──────────────┐   ┌───────────────┐                │
│   │  Market    │──▶│  Strategy    │──▶│  Risk Manager │──┐             │
│   │  Data Bus  │   │  Engine      │   │  (sovereign)  │  │             │
│   └────▲───────┘   └──────────────┘   └───────────────┘  │ approved    │
│        │ ticks/books                                      ▼ orders      │
│   ┌────┴─────────────────────────────────┐   ┌───────────────────────┐ │
│   │  CONNECTORS (trait: MarketConnector) │   │  Order Router         │ │
│   │  · PaperConnector  (default)         │◀──│  + Portfolio/Ledger   │ │
│   │  · Polymarket (CLOB)                 │   └───────────────────────┘ │
│   │  · Crypto (CCXT-style: Kraken/…)     │                             │
│   │  · Alpaca (equities)                 │   ┌───────────────────────┐ │
│   └──────────────────────────────────────┘   │  Journal (append-only)│ │
│                                               │  + SQLite state       │ │
│   ┌──────────────────────────────────────┐   └───────────────────────┘ │
│   │  Secrets vault (OS keystore)         │                             │
│   └──────────────────────────────────────┘                             │
└────────────────────────────────────────────────────────────────────────┘
```

### Component responsibilities

| Component | Job |
|---|---|
| **Market Data Bus** | Normalizes ticks/order-books/prices from every connector into one internal `MarketTick`/`OrderBook` type; fans out to subscribed strategies. |
| **Strategy Engine** | Runs each active strategy on its schedule; a strategy consumes market data + signals and emits `Intent`s (desired positions), never raw orders. |
| **Risk Manager** | Turns `Intent`s into `Order`s *or rejections*, enforcing global + per-strategy limits, kill switch, and sizing rules. The only path to the router. |
| **Order Router** | Sends approved orders to the correct connector; tracks acknowledgements, fills, partials, cancels; updates the Portfolio/Ledger. |
| **Connectors** | One trait, many venues. `PaperConnector` simulates fills against live/replayed prices. Live connectors talk to real APIs. |
| **Portfolio / Ledger** | Source of truth for cash, positions, realized/unrealized P&L, per-venue balances. Double-entry so it always reconciles. |
| **Journal** | Append-only event log (signal → sizing → order → fill/reject). Powers the audit view and post-hoc analysis. |
| **Secrets vault** | Encrypted API-key storage via the OS keychain (Windows Credential Manager / macOS Keychain / libsecret). |

---

## 3. The venues (connectors)

All connectors implement the same `MarketConnector` trait so strategies are venue-agnostic.

### 3.1 Polymarket (prediction markets)
- **API:** CLOB REST + WebSocket (`https://clob.polymarket.com`), Gamma API for market metadata.
- **Auth:** EIP-712 signed headers derived from an Ethereum private key (L2 headers). USDC on Polygon.
- **Order model:** limit orders into a central-limit order book; outcome tokens priced 0–1 (= implied probability).
- **Edge source:** your probability estimate vs. market's implied probability. Bet when `p_model − p_market > threshold + fees`.
- **⚠️ Legal:** Geoblocked for US persons; automated access must comply with Polymarket ToS and local law. See [`SAFETY.md`](SAFETY.md).

### 3.2 Crypto exchange (CCXT-style)
- **First target:** Kraken (clean API, good docs, spot). Abstraction is CCXT-shaped so Binance/Coinbase/Bybit slot in.
- **Auth:** API key + secret, HMAC-signed requests. Spot only in v1 (no leverage/derivatives until risk model is proven).
- **Order model:** limit/market on spot pairs; standard L2 order book.
- **Edge source:** momentum / mean-reversion / stat-arb signals (pluggable).

### 3.3 Alpaca (US equities)
- **API:** Alpaca Trading API v2 + market-data feed. Native **paper** endpoint (`paper-api.alpaca.markets`) — great for validation.
- **Auth:** key id + secret.
- **Order model:** equities/ETFs, market/limit/bracket. Respect market hours + PDT rules (enforced in risk manager).
- **Edge source:** same signal framework as crypto.

---

## 4. Strategy framework

A strategy is a small module implementing:

```rust
trait Strategy {
    fn id(&self) -> &str;
    fn universe(&self) -> Vec<MarketId>;          // what it watches
    fn on_tick(&mut self, ctx: &StrategyCtx) -> Vec<Intent>;  // emit desired positions
    fn params(&self) -> ParamSchema;              // UI-editable knobs
}
```

An `Intent` = "I want target exposure X in market M at confidence C". The strategy **never** talks
to a venue directly. Shipped strategies (Phase 1–2):

| Strategy | Venue class | Idea |
|---|---|---|
| **Prob-Edge** | Polymarket | Bet outcomes where your probability model beats implied odds by a margin. |
| **Momentum** | crypto/equity | Trend-follow on multi-timeframe breakouts with ATR stops. |
| **Mean-Revert** | crypto/equity | Fade stretched moves back to a moving-average band. |
| **Cross-Market Arb** | Polymarket × Polymarket | Exploit mispriced complementary/correlated markets (e.g. sum of outcomes ≠ 1). |
| **Manual** | any | You supply the edge estimate; the engine just sizes + routes + manages risk. |

**Edge estimation** is pluggable: a `SignalProvider` can be a rule, a statistical model, or an
external inference service (a local model server). Pythia does **not** promise a magic alpha model —
it gives you the disciplined machinery to *express, size, risk-manage, and execute* an edge you bring.

---

## 5. Risk model (the part that saves you)

Enforced in the execution path for **every** order, paper or live:

- **Kill switch** — one global flag; when set, all live execution halts, open orders are cancelled
  (configurable), and only flatten/close intents pass.
- **Max daily loss** — realized+unrealized drawdown ceiling per UTC day; breach → kill switch trips.
- **Max position size** — per-market cap (absolute + % of equity).
- **Max open exposure** — aggregate gross exposure ceiling across all venues.
- **Per-strategy budget** — each strategy gets an allowance; it can't spend the whole account.
- **Sizing** — fractional Kelly (default ¼-Kelly) bounded by the caps above; never full-Kelly.
- **Cooldowns / rate limits** — cap orders/minute per strategy to prevent runaway loops.
- **Sanity gates** — reject orders on stale data (> N seconds old), crossed/locked books, or price
  outside a sane band vs. last trade.

If a check fails, the order is **rejected and journaled** with the reason. Fail closed.

---

## 6. UI (the cockpit) — matches Odysync's neon aesthetic

Frameless transparent window, JetBrains Mono, cyan/purple glow, framer-motion. Pages:

| Page | Contents |
|---|---|
| **Dashboard** | Equity curve, today's P&L, open exposure, mode badge, kill-switch, live activity feed, per-venue balances. |
| **Markets** | Browse/search markets across venues; implied odds/prices; add to a strategy's universe or watchlist. |
| **Positions** | Open positions + orders across all venues; per-position P&L; one-click flatten. |
| **Strategies** | List of strategies; per-strategy status (paper/live/paused), params editor, equity curve, arm-live flow. |
| **Risk** | All limits with live utilization bars; kill-switch; daily-loss meter; edit caps. |
| **Journal** | Append-only, filterable audit log of every signal/order/fill/rejection. |
| **Backtest** | Replay a strategy over historical data; stats (Sharpe, max DD, win rate, profit factor). *(Phase 2)* |
| **Settings** | API keys per venue (into OS vault), mode defaults, connection status, data dirs. |
| **About** | Version, links, the standing risk disclaimer. |

**Mode safety in UI:** a persistent badge + top banner shows PAPER (cyan) or LIVE (red, pulsing).
Arming a strategy live requires typing the strategy name to confirm.

---

## 7. Build phases / roadmap

- **Phase 0 — Scaffold (this repo).** Tauri+React cockpit, neon UI, all pages rendering, a working
  **client-side paper engine** so the app is runnable immediately (`npm run dev`), typed IPC layer,
  the full data model, risk manager logic, connector traits with a paper connector. ✅
- **Phase 1 — Rust engine core. ✅ (mostly)** The paper engine now lives in the Rust backend as a
  persistent tokio daemon that ticks and pushes full state to the UI over a Tauri event. Real
  **Kraken (crypto)** + **Polymarket (Gamma odds)** read-only market data, paper execution against
  live prices. The UI runs identically native or in-browser. *Remaining Phase-1 polish: SQLite-
  persisted journal, OS-keychain secrets vault, live Alpaca read data (needs keys).*
- **Phase 2 — Live execution (gated).** Implement order placement/cancel/fill tracking for each
  connector behind the arm-live flow. Backtest page. Reconciliation. Paper→live promotion workflow.
- **Phase 3 — Signals & models.** Pluggable signal providers; optional local inference server;
  cross-market arb; parameter optimization from backtests.
- **Phase 4 — Hardening.** Alerting (Discord/webhook), crash recovery, position reconciliation on
  restart, full test suite, installer + auto-update (Tauri updater, like Odysync).

## 8. Tech stack (mirrors Odysync)

Tauri v2 · React 19 · TypeScript · Vite · Tailwind v3 (cyber theme) · framer-motion · lucide-react ·
JetBrains Mono · Rust core (tokio, serde, reqwest/rustls, sqlx or rusqlite) · OS keychain for secrets.

## 9. Explicitly out of scope (for now)

Leverage/margin/derivatives, options, high-frequency/co-location, anything requiring you to enter
credentials into *me* (I never do that), and any promise of profit. Pythia is disciplined
machinery, not a money printer. See [`SAFETY.md`](SAFETY.md).

---

## 10. What comes next (written 2026-11-25)

Sections 0 to 9 are the design Pythia started from. This section is the plan from here: how Pythia
compares today, what is missing, and what to build in which order. `PROFIT-PLAN.md` stays the plan for
the research; nothing here promises a profit.

### 10.1 Where Pythia stands

Better than most: every study is registered before its first run and every trial is counted for good,
paper is the default and real money needs several separate steps, one engine runs in the desktop app,
on a server and behind a CLI, and the desktop installer is under 5 MB.

Weaker than most, found in the audit of 2026-11-25:

- **The first ten minutes are the owner's, not a stranger's.** Of the 13 entries in the simple menu four
  (Wallet, pump.fun live, Trends, Cards) show nothing without the owner's server or data. Three advanced
  pages are German inside an English app. There is no path from "installed" to "I tested something on
  real data" without reading the source.
- **The thing that sets it apart is not in the product.** The trial ledger lives in the Python lab and
  needs the owner's recorded data. The app's own Optimizer deflates one sweep, and forgets it.
- **Nothing ran on a push** until the workflows of this branch; releases are built, not tested.
- **No signature, no update, no checksum** on any download. 0.5.1 is five weeks and 49 app commits old.
- **No login** on the server, so every remote use needs a reverse proxy someone else sets up.
- **The kill switch and two size caps look at the side of an order**, not at whether it opens (item 1).
- **A tick waits for the network.** Quotes, bars, the broker check and reconciliation run inside it.

### 10.2 The comparison

Read from the projects' own pages and repositories on 2026-11-25; nothing was installed and no time was
measured. Stars are rounded. "None found" is not proof.

| Tool | Stars, licence | What it does better than Pythia today | Guard against overfitting |
|---|---|---|---|
| [Freqtrade](https://www.freqtrade.io/en/stable/) | 57k, GPL-3 | finds [lookahead](https://www.freqtrade.io/en/stable/lookahead-analysis/) and [recursive](https://www.freqtrade.io/en/stable/recursive-analysis/) bugs by re-running a backtest; about 33 [Telegram commands](https://www.freqtrade.io/en/stable/telegram-usage/); a web UI with a [login](https://www.freqtrade.io/en/stable/freq-ui/) | those two analyses; no trial count |
| [Hummingbot](https://hummingbot.org/) | 21k, Apache-2 | [50+ venues](https://hummingbot.org/exchanges/) by its own count, DEXs among them | none found |
| [NautilusTrader](https://nautilustrader.io/docs/latest/) | 32k, LGPL-3 | one event-driven engine for [backtest](https://nautilustrader.io/docs/latest/concepts/backtesting/) and live; far more [adapters](https://nautilustrader.io/docs/latest/integrations/); attested packages | none found |
| [LEAN](https://www.quantconnect.com/docs/v2/) | 23k, Apache-2 | [20 brokers](https://www.quantconnect.com/docs/v2/cloud-platform/live-trading/brokerages), hosted data, backtests in a browser | probabilistic Sharpe, a hold-out period |
| [Jesse](https://docs.jesse.trade/) | 8.8k, MIT core, paid live plugin | tests an entry rule [by bootstrap](https://docs.jesse.trade/docs/rule-significance-testing/) before a strategy exists; [Monte Carlo](https://docs.jesse.trade/docs/monte-carlo/) in the product | per rule, no correction for many tries |
| [OctoBot](https://github.com/Drakkar-Software/OctoBot) | 7k, GPL-3 | one .exe, grid and DCA without code, a phone app | none found |
| [vectorbt](https://vectorbt.dev/) | 9.9k, Apache-2 with Commons Clause | grids over whole parameter spaces; two steps to a first backtest | [deflated Sharpe](https://vectorbt.dev/api/returns/accessors/), trials of that one call |
| [OpenBB](https://docs.openbb.co/) | 76k, Apache-2 | the same Tauri stack with a [signed](https://github.com/openbq-org/OpenBB/blob/develop/.github/workflows/build-desktop-win64.yml) and self-updating desktop app; data only | not applicable |
| [Vibe-Trading](https://github.com/HKUDS/Vibe-Trading) | 39k, MIT | deflated Sharpe, PBO and false discovery rate in the product, 8 live venues | per benchmark; no ledger found across sessions |
| [martex-quant](https://github.com/martex-dev/martex-quant) | about 20, MIT | three commands to a first result that then explains why it is no evidence | a permanent ledger, like Pythia's lab |

A count of every try that nobody can reset, across sessions, was found in no large tool. One small one
has it. That is what Pythia should be known for, and it has to be in the app to count.

### 10.3 The work, in order

Effort: S is up to a day, M up to a week, L more. **[Jakob]** marks what needs his decision, his money,
his keys or a real account. Everything else can be built and tested on paper.

**A. Safety first**

1. **The kill switch and the size caps ask whether an order opens, not which side it has.** S. **[Jakob:
   risk logic]** `risk::evaluate` stops buys only when the switch is on, and the position and gross caps
   bind buys only (`engine/risk.rs`, checks 1, 6, 7). Perps shorts have their own check (`engine/perps.rs`).
   A share short from a live strategy with `PYTHIA_ALLOW_SHORTS` on has none that the audit found; it
   read the code and did not try it. Fix: refuse every order that does not reduce, with the `reduces` test
   check 8 uses already. *Done:* a sell that opens a short is refused with the switch on and cut by both
   caps; every closing order still passes. *Verify:* a table test over side, position and switch.
2. **`setKill {on}` next to `toggleKill`.** S. **[Jakob: one new command]** Two people pressing Stop in the
   same second switch it off again. The app's Stop button and `pythia kill on` use the new one. *Done:*
   sending it twice leaves the switch on. *Verify:* API test, UI test.
3. **`mode` becomes mandatory in the pump.fun confirmation file.** S. **[Jakob: the lab's live code]** A
   file without the line means full mode: 1.0 SOL a day instead of 0.5, no total budget, and neither the
   simulation nor the "I accept" line (the readiness report guards it instead). *Done:* a file without
   `mode` is refused. *Verify:* a test in the lab.
4. **The typed phrase is checked by the server too.** S. **[Jakob: arming]** `armed: true` with a working
   key is enough for the API today. *Done:* arming real money without the phrase is refused. *Verify:* API test.

**B. The first ten minutes**

5. **Release 0.6.0 with checksums and build provenance.** S. **[Jakob: tag and push]** `SHA256SUMS` and
   GitHub's free build attestations in `release.yml`; the release waits for the tests. *Done:* `gh
   attestation verify` passes on every download. *Verify:* a release candidate tag.
6. **The menu follows what is connected.** S. **[Jakob: menu]** A page whose source does not exist on this
   machine is not listed: Wallet, pump.fun live, Trends, Cards, CS2, News, Lab Live, Progress. Deep links
   and the owner's embedded pages stay as they are. *Done:* a fresh install in simple mode lists at most
   nine entries and none answers "Needs the server". *Verify:* a test of the menu for each runtime, and a
   walk through a clean Windows sandbox with screenshots.
7. **A first honest test in five minutes.** M. One flow on Home: pick a coin and a rule, the engine loads
   daily candles without a key, runs it with the venue's costs next to buying and holding, and says how
   many variants were tried and what pure luck would have shown. The Rust sweep exists
   (`research::sweep`). *Done:* from the installer's double click to that result in under five minutes,
   without a terminal. *Verify:* timed three times in Windows Sandbox.
8. **Install without an administrator.** S. **[Jakob: breaks the upgrade path of old installs]**
   `installMode: currentUser`. *Done:* no UAC prompt. *Verify:* Windows Sandbox.
9. **English and German, one at a time.** M. The app's texts go into one table per language, as the alerts
   have already; News, Lab Live and Progress stop being German for everyone. *Done:* no page mixes
   languages; a test finds texts outside the table. *Verify:* that test, screenshots in both.

**C. What only Pythia does**

10. **The trial ledger in the engine.** M. Every sweep, backtest and composer test run from the app or the
    CLI is appended to one file (data span, parameters, Sharpe, time); the deflated Sharpe uses the whole
    count for that data, and the file can only grow. *Done:* running the same sweep ten times raises the
    bar each time, across restarts; a truncated file is noticed and said. *Verify:* Rust tests against the
    lab's numbers, like the candle parity tests.
11. **`pythia check returns.csv --trials N`.** S after 10. Anyone can judge a backtest from any tool:
    deflated Sharpe, what noise would show, the trades needed for a verdict. *Done:* it reads Freqtrade's and
    vectorbt's exports. *Verify:* golden files from both. This is the cheapest way to be useful to
    people who will never switch.
12. **A lookahead check for every strategy.** M. Each built-in and composer strategy runs on a prefix of
    the candles and on all of them; a signal that changes is a bug. Freqtrade has this, Pythia's lab has a
    leak harness, the engine has neither in the product. *Done:* a test for all built-ins, a button on the
    Composer. *Verify:* a strategy with a planted leak is caught.
13. **The same events in backtest and paper.** L. Replay a recorded day of the paper engine through the
    backtester and compare fills. *Done:* equal orders and fills within the cost model, difference
    reported. *Verify:* a recorded fixture in CI.
14. **Bring your own signal.** S. The folder of signal files the lab writes is already an interface. Give it
    a page in `docs/`, a JSON schema and `pythia signals validate`, so a strategy in any language can trade
    on paper. *Done:* a 20-line Python example trades on paper. *Verify:* in CI, paper only.

**D. Reach it from anywhere, safely**

15. **A login for the server.** M. **[Jakob: changes the server he runs]** `PYTHIA_API_TOKEN`: with it set,
    every route but the health check asks for it (constant-time compare, cookie for the UI, header for the
    CLI, rate limit on failures). Not set: as today, loopback only, and a bind to another address is
    refused instead of warned about. *Done:* every route answers 401 without it. *Verify:* a test that
    walks the route table, so a new route cannot be forgotten.
16. **Telegram that answers.** M. **[Jakob: bot token]** `/status`, `/autopilots`, `/pause`, `/kill on`.
    Reading and stopping only: nothing that opens, arms or raises. *Done:* an unknown chat is ignored and
    logged. *Verify:* against a local mock.
17. **The phone.** S. The web UI as an installable app behind the login of 15. *Done:* Lighthouse installable,
    the Stop button within reach on a 375 px screen. *Verify:* screenshots in CI.

**E. Trust in the download**

18. **Signed Windows and macOS builds.** M. **[Jakob: money and identity]** Ask SignPath Foundation (signs
    open source without a fee, to be checked) before buying a certificate; Apple's developer programme is
    paid per year. *Done:* no SmartScreen or Gatekeeper warning on a clean machine. *Verify:* a sandbox and a Mac.
19. **Updates in the app.** M after 18. **[Jakob: an updater key, kept offline]** Tauri's updater, asked
    for, never silent, never while a live order is open. *Done:* 0.6.0 offers 0.6.1 and keeps its state.
    *Verify:* a test channel.
20. **winget, Scoop, Homebrew.** S after 18. **[Jakob: submits]** *Done:* `winget install` works.

**F. Engine and house**

21. **The tick never waits for the network.** L. **[Jakob: touches the order path]** Quotes, bars, broker
    status, execution and reconciliation on their own tasks, the engine ticks on time. Quotes and bars run
    together since 2026-11-25 (worst case 15 s down to 5). *Done:* with a venue that answers after 5 s the
    99th percentile of the tick interval stays under 1.75 s. *Verify:* a test with a slow mock venue, the
    interval in `/api/state`.
22. **Only what changed goes over the stream.** M. Measure the state's size with ten autopilots first; stop
    here if it is under 50 kB. *Done:* bytes a minute down by 80 %. *Verify:* `bench:ui` against a recorded server.
23. **Split `engine/mod.rs` (10,400 lines) and `autopilot.rs` (5,200).** L, in steps without a behaviour
    change. *Done:* no file over 2,500 lines. *Verify:* the 1,028 engine tests unchanged.
24. **The next dependency round.** M. `chrono` and `chrono-tz` (unmaintained) to `jiff`; axum 0.8, reqwest
    0.13, keyring 4, tokio-tungstenite 0.30, hmac and sha2 with the signing tests as the guard; Tailwind 4.
    *Done:* `cargo audit` shows only what Tauri brings. *Verify:* CI, the venue signing vectors.
25. **Make it a project.** S. **[Jakob: GitHub settings]** `CONTRIBUTING.md`, issue forms, Discussions, ten
    good first issues from this list, the README's screenshots redrawn by `npm run shots` (its page list is
    out of date). *Done:* a stranger gets from clone to a green test run with the README alone. *Verify:* in a container.

### 10.4 Not planned

More venues before 21 and 15. Leverage with real money. A strategy market, copy trading or anything that
sells signals. Any number without its trial count next to it.
