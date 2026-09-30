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

### Crypto exchange (optional — 24/7, unlike equities)

Equities only trade during US market hours. If you want something to actually happen at 3am, add a
crypto exchange: **Kraken**, **Binance**, **Bybit** or **OKX**.

- Desktop: *Settings → Crypto exchanges* → paste key + secret (+ passphrase for OKX) → **Save & select**.
- Server: `PYTHIA_EXCHANGE=kraken`, `PYTHIA_EXCHANGE_KEY`, `PYTHIA_EXCHANGE_SECRET` in `.env`.

> 🔐 Give the key **trade** permission and **not** withdrawal. Then the worst case from a leaked key
> is unwanted trades, not a drained account. Spot is **long only** — a sell signal on a coin you do
> not hold is refused before it is sent.

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

**Live** page → pick your venues under *1 · Venues* → **Test paper connection**. Expect:

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
2. Under *1 · Venues*, enable only what you want routing. A venue left off keeps simulating even
   while the others are live.
3. Optional dress rehearsal: flip **Dry-run** on. Orders get logged as
   `DRY-RUN submit …` and resolve to `dry-run: not submitted` — nothing reaches a venue.
4. Set the **order timeout** (default 120s). This is how long an unfilled order may sit before
   Pythia **cancels it at the venue** and books whatever filled. It is not a local giveup: the order
   really is stopped, so your book cannot drift away from the broker's.
5. Type `ARM LIVE` → **Arm live**.

Arming runs a read-only credential check against every enabled venue first and **refuses** if one
does not answer. If you see `cannot arm Alpaca: authentication failed …`, that is the check doing its
job — you would otherwise have found out when the first signal fired, with the order already gone.

The banner turns amber: *LIVE ARMED — paper endpoint · alpaca, crypto*.

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

Outside that window, **new Alpaca entries are refused up front** with a readable reason
(`Live entry blocked for AAPL: US equity market closed (next open …)`) instead of being submitted
and left to time out. The Live page shows the same reason in an amber banner, and a readiness
checklist plus a per-market trace say which gate is holding each market back.

**Exits are never blocked** by that session check. Being unable to open a position is an
inconvenience; being unable to close one is a real risk, so the session, day-trade and account
checks apply to entries only. The connector's own preflight still refuses a *market* order into a
closed session:

```
LIVE order not sent (AAPL): US market closed — next open 2026-07-27T13:30:00Z.
Enable extended hours to trade the pre/post session.
```

That is deliberate. Alpaca would happily accept a market order at 03:00 and fill it at tomorrow's
open, across an unknown overnight gap, which is a bet nobody asked for.

**Extended hours** (04:00 to 20:00 ET) is an opt-in toggle on the Live page, locked while armed. It
only takes effect while Alpaca's calendar reports a pre/post session running; opting in cannot
override the broker. In that session orders go out as whole-share DAY **limit** orders (dollar
entries are converted to whole shares) with the band widened to at least 75bps, because that is
the only shape Alpaca accepts there. On the server, `PYTHIA_EXTENDED_HOURS=true` sets the default
for arm requests that do not say.

Crypto has no such window: an armed crypto venue trades 24/7.

### Other things it refuses before sending

| Journal line | What happened |
|---|---|
| `order needs $4,210.00 but buying power is $980.00` | Sized past the account, caught before the broker saw it |
| `selling 3.0 AAPL would open a short (held 0.0); shorts are disabled` | Set `PYTHIA_ALLOW_SHORTS=true` if you have a margin account and mean it |
| `spot sell of 0.5 BTC but only 0.0 free on Kraken — spot cannot short` | Spot is long-only, everywhere |
| `0.00003 AAPL is below Alpaca's minimum order size` | Dust, dropped rather than rejected |

### What the Alpaca order path actually does

| | |
|---|---|
| **Entries** are sent as **dollar notional** | No client-side share rounding, and it cannot over-spend the sizing decision. |
| **Exits** are sent as **shares** | "Sell exactly what I hold" can't be expressed in dollars. |
| Whole-share market orders go out as **marketable limits** (`PYTHIA_SLIPPAGE_BPS`, default 25bps) | A market order into a thin or gapped book fills at whatever is there. Set `0` for plain market orders. |
| An order still working at the **order timeout** is **cancelled at the venue, then re-read** | The dangerous version is giving up while the order is still working: the broker fills it later and you hold an untracked position with no stop on it. |
| **Partial fills are booked** | A cancel can lose the race to a partial fill. Those shares are real. |
| Every submission carries a deterministic `client_order_id` | If the connection drops mid-POST, or Alpaca answers "duplicate id", the order is looked up instead of sent twice. |
| Paper and live use **separate key slots** | Each pair only authenticates against its own endpoint. An empty slot fails as "not configured"; the order path never borrows the other account's keys. |

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
| **Orders** | `pending` → `partial` → `filled`, with the venue's average fill price |
| **Positions** | a real position carries a red **REAL** badge |
| **Alpaca dashboard** | the same order under *Recent Orders* — the ground truth |
| Discord webhook | the arm event and every fill, if you configured one |

A partial fill is booked as it happens, not at the end: if 40% fills and the rest never does, you own
40% and the ledger says so. Polling repeats on purpose, and re-reporting the same numbers cannot
double-book — the engine settles the *delta* against what it already recorded.

If Pythia and the venue ever disagree, **the venue wins**. The daemon pulls the broker's own position
list on boot and every ~2 minutes and corrects its book, journaling the correction:

```
Reconciled AAPL: book had 10.000000, Alpaca has 4.000000 — broker wins
```

It will not, however, *adopt* a position it never opened. Your own long-held NVDA is not Pythia's to
put a stop-loss under. Every correction is also pushed to your webhook, and stops are deliberately
**cleared** on a corrected position and recomputed on the next tick: a stop sized for 10 shares means
nothing once you hold 4.

---

## 6 · Stop

- **Disarm** (Live page) — new live orders stop immediately; everything reverts to simulation.
- **KILL** (titlebar) — the global kill switch blocks all new buys, live or paper.
- Set the strategy back to **Paused** to stop it generating signals at all.

> ⚠️ **Disarming does not close anything.** Real positions stay open at the venue — and while
> disarmed their stop-losses cannot fire. Pythia refuses to book a fake exit and says so:
>
> ```
> AAPL holds a REAL position that wants to close, but live routing is off for Alpaca.
> It is NOT closed. Re-arm to exit, or flatten it in the broker's own dashboard.
> ```
>
> Both the Live and Positions pages show a red banner while any real position is open and disarmed.
> To actually flatten: re-arm, then **Positions → Flatten** (which routes a real reduce-only exit),
> or close it in the venue's own dashboard.

---

## Going to real money later

Only after the paper run behaves for a while: put **live** Alpaca keys in, flip the Live page
endpoint to **Live**, and re-arm (the banner turns red and pulses). Everything else is identical —
same risk manager, same kill switch, same gates.

Live keys go in their own slot: *Settings → Alpaca — Live* on the desktop, or
`APCA_LIVE_API_KEY_ID` / `APCA_LIVE_API_SECRET_KEY` on the server. Test them from the Live page with
the endpoint set to **Live** before arming.

Before you do, read [`../PROFIT-PLAN.md`](../PROFIT-PLAN.md). The shipped strategies are textbook
indicators, and the arithmetic in §1 of that document explains why a high-turnover bot loses to costs
even with a signal that "works". A good paper result is necessary, not sufficient.

### What a restart does now

An order in flight during a restart is no longer lost. Its position is persisted with its **REAL**
flag intact, and the daemon reconciles against the venue's own position list on boot — so a fill that
landed while Pythia was down shows up in the book, journaled as a correction. The one thing a restart
still costs you is the *order row* for that specific fill; the position, which is what matters, is
recovered.

Check the venue's dashboard after any restart mid-session anyway. It is the ground truth, and it is
free to look.
