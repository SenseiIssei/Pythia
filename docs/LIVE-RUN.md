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
`.env` is gitignored. On boot the log tells you what it found:
```
Alpaca: keys present → real equity quotes (iex feed) + live execution available
```
If it says *no keys*, the `.env` wasn't picked up (check you're in the repo root).

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
Market orders only fill during **US regular hours, 9:30–16:00 ET** (= **15:30–22:00 CEST**).
Outside that window an order sits and then logs
`LIVE order not filled: not filled within timeout (market closed, or still working)`.
That's expected, not a bug.

---

## 5 · Watch it

| Where | What you'll see |
|---|---|
| **Journal** | `PAPER-LIVE submit BUY 4.1 AAPL @ ~231.50` → `LIVE FILL BUY 4.1 AAPL @ 231.47` |
| **Live** page | `pending` count while an order is in flight |
| **Orders** | status `pending` → `filled`, with the broker's average fill price |
| **Alpaca dashboard** | the same order under *Recent Orders* — the ground truth |
| Discord webhook | the arm event and every fill, if you configured one |

If the two disagree, **Alpaca is right** — tell me and we'll reconcile.

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

Known limitation: an order that's in flight during a restart isn't re-reconciled — it still executes
at Alpaca, but Pythia won't record that one fill. Check the dashboard after any restart mid-session.
