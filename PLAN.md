# Pythia — Master Plan

> An autonomous, multi-venue prediction & trading engine with a native desktop cockpit.
> Prediction markets (Polymarket) + crypto exchanges + equities (Alpaca), unified behind
> one strategy engine, one risk manager, and one neon control panel.

**Status:** Phase 0 scaffold (this repo). Paper-trading works end-to-end. Live connectors are
stubbed and gated. **Read [`SAFETY.md`](SAFETY.md) before you flip anything to live.**

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
