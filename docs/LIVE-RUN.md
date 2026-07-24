# First live run — Alpaca paper

A step-by-step runbook for taking Pythia from simulation to a **real broker order**
using an Alpaca **paper** account (real API, real order lifecycle, no real money).

> Read [`SAFETY.md`](../SAFETY.md) first. Nothing here is financial advice.

---

## 0 · Get paper keys (2 min)

1. <https://app.alpaca.markets> → make sure the account switcher (top-left) says **Paper Trading**.
2. **API** → generate a key. Copy the **Key ID** *and* the **Secret** — Alpaca shows the secret once.
3. Paper and live accounts have **separate keys**. Paper keys only work against the paper endpoint,
   which is what Pythia selects by default.

> 🔐 Never paste keys into a screenshot, a chat, a commit, or `.env.example`. If a secret is ever
> exposed, regenerate it immediately — a key with trade permission can place and cancel orders.

---

## 1 · Give the keys to Pythia

Pick whichever runtime you're using. **Never both from the same secret** — just re-paste it.

### Desktop app
*Settings → Alpaca (equities)* → paste Key ID + Secret → **Save to vault**.
Stored in the Windows Credential Manager; never shown again, never logged.

### Backend server
```bash
cp .env.example .env
```
Fill in `APCA_API_KEY_ID` and `APCA_API_SECRET_KEY`, then start it:
```bash
npm run server
```

> **Windows build note.** If a native crate (`ring`) ever fails with
> `failed to find tool "C:\Program"`, that's machine-scope `CC`/`CXX` env vars whose value contains
> a space — `cc-rs` splits on it. The npm scripts run through `scripts/clean-env.mjs`, which strips
> `CC`/`CXX`/`CFLAGS`/`CXXFLAGS` for the child process, so `npm run server` and `npm run tauri` are
> immune. Raw `cargo` in your own shell is not — prefix it with
> `unset CC CXX CFLAGS CXXFLAGS` (bash) if you hit it.
`.env` is gitignored. On boot the log tells you what it found:
```
Alpaca: keys present → real equity quotes (iex feed) + live execution available
```
If it says *no keys*, the `.env` wasn't picked up (check you're in the repo root).

---

## 1b · Run the preflight (the fastest way to find a problem)

With the server running, in a second terminal:

```bash
npm run preflight
```

Every way a live run fails silently produces the *same* symptom — an armed engine that places no
trades. This tells you which one you actually have:

```
  ok   alpaca_keys        APCA_API_KEY_ID set (…J4XQ)
  ok   alpaca_account     paper-api.alpaca.markets: ACTIVE · equity $100000.00 · buying power $200000.00
  ok   pattern_day_trader 0 day trade(s) used; equity $100000.00
  ok   market_session     open until 2026-07-24T20:00:00Z
  ok   equity_quotes      5 symbol(s) on the 'iex' feed
  ok   equity_candles     5 series, 1840 5Min bars — indicators need ≥30 per market
  ok   crypto_candles     9 Kraken series (no keys needed)
  ok   ai_provider        configured: anthropic
  ok   live_gate          disarmed (paper only)
```

`equity_candles` is the one people miss. Strategies signal off **completed candles**, not the live
quote — a market with fewer than 30 bars is skipped entirely, so a fresh start with a market-data
plan that doesn't cover your feed will look armed and idle forever.

---

## 2 · Verify the connection (read-only)

**Live** page → **Test paper connection**. Expect:

| Field | Expected |
|---|---|
| Status | `ACTIVE` |
| Endpoint | `paper` |
| Buying power | your paper balance (e.g. `$100,000.00`) |

Common failures:

| Symptom | Cause |
|---|---|
| `401` / `403` | Wrong keys, or **live** keys against the paper endpoint (or vice-versa) |
| `Alpaca keys not in vault` | Desktop: keys not saved yet |
| `keys not set (APCA_…)` | Server: `.env` missing or not loaded |

Once this is green, your equity markets (AAPL, NVDA, MSFT, AMZN, TSLA) are showing **real quotes**
— the Markets page will start moving with the actual tape.

---

## 3 · Arm (still no real money)

1. **Live** page → leave **Endpoint = Paper**.
2. Optional dress rehearsal: flip **Dry-run** on. Orders get logged as
   `DRY-RUN submit …` and resolve to `dry-run: not submitted` — nothing reaches Alpaca.
3. Type `ARM LIVE` → **Arm live**. The banner turns amber: *LIVE ARMED — paper endpoint*.

---

## 4 · Let a strategy trade

**Strategies** → *Donchian Breakout · Equities* → set **Live** (it ships Paused).

That's the one strategy whose universe is the Alpaca tickers. From here:

- entries route live when the breakout triggers,
- the position is tagged live, so its **stop-loss / trailing exits also route live**,
- crypto and Polymarket strategies keep simulating — they never touch a broker.

### Timing matters
US regular hours are **9:30–16:00 ET** (= **15:30–22:00 CEST**). Pythia asks Alpaca's own clock
rather than guessing, so holidays and half-days are handled.

Outside that window, **new entries are refused up front** with a readable reason
(`Live entry blocked for AAPL: US equity market closed (next open …)`) instead of being submitted
and left to time out. The Live page shows the same reason in an amber banner.

**Exits are never blocked.** Being unable to open a position is an inconvenience; being unable to
close one is a real risk, so the session, day-trade and account checks apply to entries only.

### What the order path actually does

| | |
|---|---|
| **Entries** are sent as **dollar notional** | No client-side share rounding, and it cannot over-spend the sizing decision. |
| **Exits** are sent as **shares** | "Sell exactly what I hold" can't be expressed in dollars. |
| Whole-share orders go out as **marketable limits** (`PYTHIA_SLIPPAGE_BPS`, default 25bps) | A market order into a thin or gapped book fills at whatever is there. Set `0` for plain market orders. |
| An order that doesn't fill in ~10s is **cancelled, then re-read** | The dangerous version is giving up while the order is still working: the broker fills it later and you hold an untracked position with no stop on it. |
| **Partial fills are booked** | A cancel can lose the race to a partial fill. Those shares are real. |
| Every submission carries a deterministic `client_order_id` | If the connection drops mid-POST, the retry resolves to the *same* broker order instead of opening a second one. |

### Pattern Day Trader
Under **$25,000** of equity, FINRA allows three day trades per five business days; a fourth flags
the account and restricts it for 90 days. Pythia reads `daytrade_count` from Alpaca and blocks new
entries at three. Above $25k the rule doesn't apply and the check goes quiet.

---

## 5 · Watch it

| Where | What you'll see |
|---|---|
| **Journal** | `PAPER-LIVE submit BUY 4.1 AAPL @ ~231.50` → `LIVE FILL BUY 4.1 AAPL @ 231.47` |
| **Live** page | `pending` count while an order is in flight |
| **Orders** | status `pending` → `filled`, with the broker's average fill price |
| **Alpaca dashboard** | the same order under *Recent Orders* — the ground truth |
| Discord webhook | the arm event and every fill, if you configured one |

If the two disagree, **Alpaca is right** — and Pythia now acts on that. Every ~5 minutes (and at
startup) it pulls `/v2/positions` and makes its own ledger match: quantities are corrected, positions
the broker doesn't have are dropped, and positions it didn't know about are adopted. Each difference
is written to the Journal as a `Reconciled — …` entry and pushed to your webhook.

Stops are deliberately **cleared** on a corrected position and recomputed on the next tick — a stop
sized for 10 shares means nothing once you hold 4.

---

## 6 · Stop

- **Disarm** (Live page) — new live orders stop immediately; everything reverts to simulation.
- **KILL** (titlebar) — the global kill switch blocks all new buys, live or paper.
- Set the strategy back to **Paused** to stop it generating signals at all.

Existing live positions are *not* auto-closed by disarming. Flatten them from **Positions**
(a live-opened position closes live) or in the Alpaca dashboard.

---

## Going to real money later

Only after the paper run behaves for a while: put **live** Alpaca keys in, flip the Live page
endpoint to **Live**, and re-arm (the banner turns red and pulses). Everything else is identical —
same risk manager, same kill switch, same gates.

An order in flight during a restart still executes at Alpaca. Pythia won't see that individual fill
event, but the startup reconciliation picks the resulting position up within a few minutes and
journals it — so you end up in the right state, just without that one order's history.
