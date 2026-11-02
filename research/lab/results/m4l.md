# M4L: the backtest bands of the M4 paper books, the fill cost of m4_hl_small, and a Hyperliquid executor not armed

Pre-registered in `results/m4l_prereg.md`, committed before the first run. Asked by the owner on 2026-11-02 ("mach
weiter mit M4"). Code: `lab.experiments.m4h --export-series`, `lab.paper.forward_report.export_backtests`, the fill
in `lab.paper.m4_hl_small`, the executor `lab.paper.hl_live`; tests `tests/test_m4h.py`, `test_forward_report.py`,
`test_m4_hl_small.py`, `test_hl_live.py`. Paper only: nothing a live bot, a wallet or the engine reads changed; no
key held, no order sent, no job runs the send path.

Run 2026-11-02, the lockbox not read: M4H's matrices on the paper jobs' xs_daily panel of 2026-11-02 cut at
2026-06-30, reg7n refit walk-forward as in T6b (16 minutes under the heavy lock). 2 trials in R5's registry
(small family, with their in-sample Sharpes, before any out-of-sample number), written to the run's copy; the
server's registry gets them from it. Pool 4,732.

## Reading

**Both books now have a band, and both stand inside it. The band of m4_hl_small is wider and worse than M4H
promised: rebuilt on today's panel, the judged cell makes a Sharpe of 1.20, not 1.79.**

| book | since | days | forward | band (5 % to 95 %) | median | position |
|---|---|---|---|---|---|---|
| m4_hl_small | 2026-10-30 | 3 | +1.37 % | -4.13 % to +4.05 % | +0.42 % | inside, upper half |
| m4_perps | 2026-10-21 | 12 | +7.06 % | -8.84 % to +9.28 % | +1.05 % | inside, near the top |

The bands are the forward report's own bootstrap (`bootstrap_band`) over the two series, for each book's elapsed
days on 2026-11-02, read from its journal. m4_hl_small stays "early" (fewer than 10 days); m4_perps reads "on
track" instead of "no backtest range".

- **m4_hl_small's series** (`m4h_judged.parquet`): M4H's judged cell as registered (230 USD, k 10, 1x, taker,
  01:00 fill, Hyperliquid's coins and hourly funding). Out of sample 2024-01-01 to 2026-06-28: Sharpe **1.20**,
  37.4 % a year, drawdown **27.5 %**, in sample 1.01; DSR 0.002 over 4,732 trials. M4H published 1.79, 63.6 %,
  20.0 % and 1.58 for the same cell on the panel of 2026-10-30. Same code, same windows; what moved is reg7n's
  walk-forward refit on a panel built three days later (M4H2 already found this: 1.30 against 0.93 in sample).
  Rebuilt today the cell would fail M4H's drawdown check (25 %). The band uses the rebuilt series, which is the
  honest one to hold the paper book against, and it says plainly that M4H's pass is not robust to the panel's
  build day.
- **m4_perps' series** (`m4_perps_kraken.parquet`): reg7n 10/10, 1x, the ideal account, on the coins Kraken
  Futures lists from the day after their openingDate (67 of the 100 most liquid a day on average), Kraken's base
  taker 5 bps plus DT1's proxy (3.8 bps a side on average), Binance's funding as the paper book books it. Sharpe
  **0.71**, 19.2 % a year, drawdown 27.3 %, in sample 1.00; DSR 0.000. Kraken's listing holds today's perps only:
  a perp Kraken delisted before the collector started is missing (survivorship, which flatters the series).
  T12 already found M4 weak on Kraken's coins (71 % of its turnover unlisted).

## The 1.9x fill cost of m4_hl_small: both sides were off

| | per USD traded | first 3 days |
|---|---|---|
| journal's paper fill (taker plus half of `impactPxs`) | 4.5 + 6.2 bps | 13.9 bps of equity |
| journal's model (taker plus 1 bp) | 4.5 + 1.0 bps | 7.1 bps |
| M4H's judged cell, what the backtest paid | 4.5 + 4.4 bps | (11.5 bps at this turnover) |
| Hyperliquid's l2Book walked at 11.5 USD, 23 coins, 2026-11-02 | 4.5 + 2.2 bps | (8.7 bps) |

- **Entry day turnover.** The book started flat: 20 entries of 5 % on 2026-10-30 are 1.0x the account traded in a
  day, then 0.3x on 10-31 (three new names), nothing since. The backtest's steady state is 4.5 % a day. Three days
  of costs are mostly the entry day's, which is why the cost line looks large; the ratio is per USD traded.
- **The paper fill charged too much.** Half of Hyperliquid's `impactPxs` is the slippage at its impact notional,
  far above an 11.5 USD order: 5.4 bps on average on the coins held (9.0 bps on 10-31's three). The real book at
  11.5 USD costs 2.2 bps a side (the top of book's half spread is 1.8 bps). Fixed: the fill now walks the coin's
  public `l2Book` at the order's size (`walk`), the impact spread only when the book cannot be read; each order in
  `orders/<date>.json` carries `slip_bps` and `slip_from`.
- **The model charged too little.** The journal's `model_cost_bps` took taker plus 1 bp, but the backtest paid
  taker plus DT1's spread proxy, 4.37 bps per USD traded in the judged cell (the proxy charges 1 bp only for the
  20 most liquid coins; the book's coins are mostly further down). Fixed: `MODEL_SLIP` 4.4 bps.
- After both fixes a day like 10-30 reads about 6.7 against 8.9 bps per USD traded, a ratio near 0.75: Hyperliquid's
  book at this size is cheaper than the backtest assumed. The first four journal rows keep what they said (the
  journal is never rewritten), so the forward report's cost ratio comes down only as new trades add up.

## The executor, built for live and not armed (`lab.paper.hl_live`)

- **Signing**: Hyperliquid's L1 action in plain Python, no new dependency: msgpack of the action, the nonce (ms,
  only rising), no vault, keccak-256, the phantom agent (`source` a on mainnet), EIP-712 typed data (domain
  Exchange, chain 1337) signed with secp256k1 and RFC 6979, low s, v 27 or 28. Checked against the L1 vectors of
  Hyperliquid's official Python SDK 0.24.0 (`tests/signing_test.py`: the production phantom agent, a dummy action,
  a limit order with and without cloid, scheduleCancel with and without time; mainnet and testnet): all equal.
  Left out: the vault vectors (they carry an address), the trigger order (the book sends IOC limits only) and the
  sub-account actions (nothing here moves money). A throwaway key made in the test signs, recovers and is
  deterministic. It signs order actions only: no transfer, no withdrawal, and an API wallet cannot withdraw.
- **Reconciliation, read only**, from the public info endpoint by the account's address: clearinghouseState
  (value, positions, notional, funding paid since open), openOrders, the last day's userFills; against the paper
  book's positions scaled to the live account (at most 250 USD): drift, missing and extra coins. Without
  `/etc/pythia/hl-live.env` it does nothing.
- **The send path refuses unless all hold**: the env file has `HL_LIVE_ADDRESS` and `HL_LIVE_AGENT_KEY_FILE` and
  that file exists; `/etc/pythia/hl-live.ack` holds the line `I accept that I can lose all of it` and a line
  `date=YYYY-MM-DD` not in the future; the account value at most 250 USD; held and target gross at most 2x; the
  value above 80 % of its value at the first armed send (once hit, stopped for good in `live/state.json`); no
  `GO_FLAT` in the book's folder or in its `live/` folder. Then `hl_dryrun.plan` on the live positions with its own
  limits again. Every refusal is a line in `<data>/paper/m4_hl_small/live/log.jsonl` and a card. The key file is
  read only after every gate. A test for every gate. No job, cron or container runs it; `paper-m4-hl-small` stays
  dry run.

## Addendum: the frozen panel (pre-registered in the addendum of `results/m4l_prereg.md`)

**Two numbers for one cell.** M4H's judged cell (230 USD, k 10, 1x, taker) made a Sharpe of **1.79** out of
sample on xs_daily's panel of 2026-10-30 (`results/m4h.md`) and **1.20** on the panel of 2026-11-02 (above). Same
code, same windows, same cut at 2026-06-30. The cause is the panel: the paper jobs rebuild
`<data>/lab-cache/xs_daily_panel.parquet` every morning, and reg7n's walk-forward refit (T6b) trains on whatever
that build holds up to the cut, so a later build gives other scores and another book (M4H2 saw the same in
sample: 1.30 against m4_residual's 0.93). Which rows moved between the two builds cannot be told now: neither
panel was kept. So far no band was built at all on the server: `<data>/lab-cache` holds neither series and
`reports/forward/backtest/` has no file for either book, so the forward report still says "early" and "no
backtest range".

**What changed (no new number, no trial).** `m4h --export-series` and the forward report's export now cut the
panel once and freeze it: `<data>/lab-cache/m4l_panel.parquet` and its stamp `m4l_panel.json` (the panel file's
build day, its last day, the cut's rows and symbols, a sha256 over its values sorted by symbol and day). Every
later export reads the frozen cut (checked against its hash, refused when it does not match) and caches reg7n's
scores under that hash, so a rebuild gives the same series. The stamp goes into `m4l_series.json` and into each
book's `reports/forward/backtest/<book>.json`; the band's source in `reports/forward` reads "frozen panel built
<day> sha256 <12 hex>". A rebuild on another panel says so in its log. `--export-backtests --m4l-only` exports the
two books alone. The ladder now maps `m4_hl_small` to `m4h2_prereg.md` (M4H as amended) and `m4_perps` to
`m4_residual_prereg.md`: both stand on step 1, missing step 2's tested record (T1 leak check, late record, era
costs, DSR, PBO).

**The cost model stays 4.5 + 4.4 bps** (`MODEL_SLIP`, the 4.37 bps the rebuilt judged cell paid per USD traded,
above). Once the frozen series is built, its `m4l_series.json` gives the cell's `slip_bps` on the frozen panel;
if it differs, `MODEL_SLIP` follows it in its own change.

## Anleitung für den Besitzer (M4 live mit etwa 200 EUR; nichts davon ist eingeschaltet)

Erst nach mindestens 30 Tagen Forward-Record von `m4_hl_small` (frühestens 2026-11-29), wenn das Buch nicht unter
seinem Band liegt, und nur mit deinem Ja. Nichts Privates gehört ins Repository; alles unten liegt nur auf dem Server.

1. **API-Wallet selbst anlegen.** In der Hyperliquid-App mit deinem Hauptkonto auf der Seite API
   (app.hyperliquid.xyz/API) eine API-Wallet erzeugen, benennen und autorisieren. Den privaten Schlüssel der API-Wallet nur auf dem Server in
   eine Datei schreiben, zum Beispiel `/etc/pythia/hl-live-agent.key` (eine Zeile Hex, `chmod 600`, Besitzer root).
   Eine API-Wallet kann handeln, aber nichts abheben. Den Schlüssel des Hauptkontos nie auf den Server.
2. **Einzahlen.** USDC auf dein Hauptkonto bei Hyperliquid, so dass der Kontowert höchstens 250 USD ist (darüber
   verweigert der Sende-Pfad).
3. **Env-Datei** `/etc/pythia/hl-live.env` (`chmod 600`):

   ```
   HL_LIVE_ADDRESS=<öffentliche Adresse deines Hauptkontos>
   HL_LIVE_AGENT_KEY_FILE=/etc/pythia/hl-live-agent.key
   ```
4. **Ack** `/etc/pythia/hl-live.ack` (`chmod 600`), mit dem Tag, an dem du Ja sagst:

   ```
   I accept that I can lose all of it
   date=2026-11-29
   ```
5. **Prüfen.** `python -m lab.paper.hl_live` liest nur: Kontowert, Positionen gegen das Papierbuch, Drift, gezahltes
   Funding, offene Orders, Fills. Senden: `python -m lab.paper.hl_live --send`, von Hand; ein täglicher Job dafür
   ist eine eigene Aufgabe mit deinem Ja.
6. **Flat gehen.** Eine leere Datei `GO_FLAT` in `<data>/paper/m4_hl_small/live/` (nur das Live-Konto) oder in
   `<data>/paper/m4_hl_small/` (auch das Papierbuch): der Sende-Pfad schickt nichts mehr. Die Positionen schließt
   du in der App (Positions, Close All).
7. **Stoppen.** Die Ack-Datei löschen: jeder Lauf verweigert, mit Zeile im Log und Karte. Der -20 %-Stopp gilt für
   immer (`live/state.json`, `"stopped": true`); nur du setzt ihn zurück. Ganz aufhören: die API-Wallet in der App
   widerrufen und das USDC selbst abheben.
