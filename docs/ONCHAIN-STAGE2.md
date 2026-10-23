# Eigene Wallet, Stufe 2: Echtgeld auf der Chain, Recherche und Entwurf

**Stand 2026-10-23.** Abschnitte 1 bis 6 sind der Entwurf, nach dem Review (`docs/ONCHAIN-REVIEW.md`) ergänzt:
Notschalter, Wiederholen und Neustart, Mindestmenge, Compute Budget, Token-2022, Code-Pin, Werte der App. Der Händler
selbst ist seit dem 2026-10-23 gebaut und **gesperrt**, bis du ihn scharf schaltest (Abschnitt 7: was gebaut ist, und
deine Schritte). Abschnitt 8 beschreibt die Wallet-Seite der App, den Alpha-Modus (Bücher mit kleinem echtem Geld
ohne den Nachweis, zum Trainieren und Messen unserer Modelle) und die Messung jedes Swaps. Nichts davon ist scharf:
kein Ack, keine Wallet, kein Start. Der Nachweis vor echtem Geld steht vorab
registriert in
`research/lab/results/onchain_stage2_prereg.md`.

## English summary (for code reviewers)

- **Swap path: Jupiter Swap V2 `GET /swap/v2/build`**, not `/order` + `/execute` (the old Ultra flow) and not
  the old Metis `/swap/v1` endpoints. Jupiter now calls Metis v1 and Ultra "no longer actively maintained,
  superseded by Swap V2" [J1, J2]. `/build` returns raw instructions (compute budget, setup, swap, cleanup,
  other, address lookup tables, a blockhash) and charges no Jupiter swap fee; `/order` transactions "are built
  for `/execute`", cannot be modified (JupiterZ market makers have last look) and are broadcast by Jupiter [J1].
  We compile the v0 message ourselves from the instruction lists, run the guard over every instruction,
  simulate with an account diff, then sign locally and send through Helius Sender. A keyless `/build` worked
  from the lab on 2026-10-23 (three pairs, fixtures in this run's scratch, not committed).
- **Guard (new `lab/onchain/guard.py`)**, modelled on `pumpfun_rt.txbuild.check_own`: allowed programs are
  ComputeBudget (limit and price only, price capped), the ATA program (create idempotent, owner = wallet,
  allowlisted mint), Token (close of our own wSOL account to the wallet, sync native), System (the wrap into
  our wSOL account, one Sender tip within the hard cap) and Jupiter v6 (`JUP6Lkb...`, observed as the swap
  program in every `/build` response) with only `route_v2` and `shared_accounts_route_v2` (Anchor
  discriminators checked, the ExactIn variants), account 1 = wallet as the only signer, account 2 =
  ATA(wallet, input mint), account 5 = ATA(wallet, output mint), both mints allowlisted, no platform fee
  account. Every writable account of the message that is a token account owned by the wallet must be one of
  our expected ATAs (read from chain). The simulation must show: input debit <= inAmount, output credit >=
  otherAmountThreshold, SOL debit <= fees + tip + rent, no other account of ours changed, no owner, delegate or
  close authority changed. Token-2022 mints and Token-2022 intermediates are refused in stage 2; intermediate
  mints must be on a short route allowlist (wSOL, USDC, USDT, JitoSOL and the stage-2 list).
- **Assets:** SOL, USDC (Circle), cbBTC (Coinbase), WETH (Wormhole Portal), JUP, TRUMP, RAY, BONK, WIF in the
  first list; PYTH, JTO, RENDER, POPCAT only with a 100 USD per-trade cap (20 to 50 bps at 1,000 USD, measured
  2026-10-23). WBTC is not used (it routes through cbBTC anyway, bridge risk). Coins without an issuer-confirmed
  Solana form stay cash.
- **Ack / caps (test mode):** total 1,000 USD, per trade 250 USD, daily loss 100 USD, converts 250 USD a day,
  hard in code; allowlisted mints and books in the file; a simulate within 24 h; kill files; a watcher; the
  narrow mounts of the pump.fun service. No transfer instruction exists in the guard, so no code path moves
  funds out. Withdrawals stay with the owner's own wallet and backup.
- **Alpha mode (section 8):** `mode=alpha` in the ack lets the books it names trade without the proof gate,
  under lower hard maxima in code (`live_gate.ALPHA_MAX_TOTAL_USD = 100`, `ALPHA_MAX_TRADE_USD = 25`,
  `ALPHA_MAX_DAILY_LOSS_USD = 25`; the ack can only go lower); every other gate stays as in test mode. Every
  alpha swap posts a card (Telegram, Discord's real-money route) and lands in the ledger reconciled against
  the chain. Every sent swap is measured (`live/onchain/execution.jsonl`, `reports/onchain/execution.md`).
- **Proof gate:** the book passes LIVE-READINESS on paper, its on-chain paper twin has 30 days and 20
  rebalances with on-chain cost <= 15 bps median per unit traded, and 14 days of shadow execution (build,
  guard, simulate every planned swap, never send) with >= 98 % clean simulations and zero unexplained guard
  refusals. Then 14 days at 200 USD before any cap is raised.
- **pump.fun latency:** since the Sender path, sales land a median 3.9 s after their signal, but 12.9 s at
  p75 and 37 s at p90; the send itself is no longer the bottleneck (median 0.5 s queue to seen-landed). The
  tail sits between the slot's first event and our order (p90 37 s) and in the public feed's lag behind the
  chain (median 8 s, not even inside these numbers). Free fixes first (pool-vault subscriptions for open
  positions, signature status instead of the stream fill, regional Sender with keep-alive, prebuilt sales,
  fees from recent fees), then at most a one-month Helius Developer trial (49 USD); LaserStream (499 USD a
  month) and shreds (1,000 USD a month) do not pay at today's stakes. Y5 says a 1.5 s path is worth about +3
  points per trade to the migration pool buy and still leaves it negative.

## Quellen

Alle am 2026-10-23 gelesen.

- [J1] Jupiter, Swap V2 Übersicht: https://developers.jup.ag/docs/swap
- [J2] Jupiter, Ultra (veraltet): https://developers.jup.ag/docs/ultra ; Metis `/swap/v1`:
  https://developers.jup.ag/docs/swap/build-swap-transaction
- [J3] Jupiter, `/build`: https://developers.jup.ag/docs/swap/build
- [J4] Jupiter, Rate Limits: https://developers.jup.ag/docs/portal/rate-limits
- [J5] Jupiter Token API v2 (`lite-api.jup.ag/tokens/v2/search`, Tags `verified`, `strict`, Feld
  `tokenProgram`), live abgefragt
- [S1] Solana, Gebühren: https://solana.com/docs/core/fees
- [S2] Solana, Bestätigung und Blockhash-Ablauf: https://solana.com/developers/guides/advanced/confirmation
- [S3] Solana, Token-2022-Erweiterungen: https://solana.com/docs/tokens/extensions
- [H1] Helius Sender: https://www.helius.dev/docs/sending-transactions/sender
- [H2] Helius Priority Fee API: https://www.helius.dev/docs/priority-fee-api
- [H3] Helius LaserStream: https://www.helius.dev/docs/laserstream
- [H4] Helius Preise: https://www.helius.dev/pricing
- [I1] Circle, USDC-Adressen: https://developers.circle.com/stablecoins/usdc-contract-addresses
- [I2] Coinbase, cbBTC: https://www.coinbase.com/blog/coinbase-wrapped-btc-cbbtc-is-now-live
- Eigene Messungen: Jupiter-Quotes und ein `/build` am 2026-10-23 (öffentliche API ohne Schlüssel); die
  Dateien des pump.fun-Bots (`live/pumpfun_rt/measured.jsonl`, `orders.jsonl`,
  `reports/pumpfun_rt/latency.md`), Studien Y5, Y8, Y9 (`research/lab/results/`).

## 1. Der Swap-Weg und was wir signieren

### Entscheidung: `/swap/v2/build`, eigene Transaktion, lokal signiert

Jupiter hat im Herbst 2026 umgebaut. Die alte Metis-API (`/swap/v1/quote`, `/swap-instructions`), die Stufe 1
für ihre Paper-Quotes nutzt, und Ultra (`/order` + `/execute`) gelten als "no longer actively maintained" und
sind durch Swap V2 ersetzt [J1, J2]. Swap V2 hat zwei Wege [J1]:

| | `/order` + `/execute` (Meta-Aggregator, früher Ultra) | `/build` (Router, Metis) |
|---|---|---|
| was zurückkommt | eine fertige, serialisierte Transaktion | die einzelnen Instruktionen, Lookup-Tabellen, ein Blockhash |
| ändern | nein: "built for `/execute`", JupiterZ-Market-Maker haben Last Look | ja, wir bauen die Transaktion selbst |
| wer sendet | Jupiter (`/execute`, eigene Infrastruktur) | wir (eigener RPC, Helius Sender) |
| Gebühr | 0 bis 10 bps je Paar, 50 bps bei Token unter 24 h | keine Jupiter-Swap-Gebühr |
| Priority Fee | setzt Jupiter | Vorschlag aus jüngsten Gebühren (`computeUnitPricePercentile`) |
| ohne Schlüssel | ja | ja, 0,5 Anfragen pro Sekunde [J4] |

**Wir nehmen `/build`.** Gründe: Wir müssen jede Instruktion prüfen und selbst zusammensetzen können (der
Guard), wir senden über Helius Sender (schon für pump.fun im Einsatz), und wir zahlen keine Jupiter-Gebühr.
`/order` liefert eine Transaktion, die wir nur ganz oder gar nicht signieren könnten, mit einer zweiten
Signatur eines Market Makers und Jupiters Versand. Das widerspricht der Regel "wir bauen oder prüfen jede
Transaktion vollständig und signieren nur, was der Guard angenommen hat". `/order` bleibt höchstens als
Preisvergleich im Paper (Quote ansehen, nie signieren).

Ein `/build` ohne Schlüssel lief am 2026-10-23 aus dem Lab (USDC nach SOL, BONK, JTO, Absender eine
erfundene Adresse). Die Antwort hatte genau diese Instruktionen:

| Gruppe | Programm | Inhalt |
|---|---|---|
| `computeBudgetInstructions` | ComputeBudget | nur `SetComputeUnitPrice` (72.000 bis 85.000 Micro-Lamports bei `veryHigh`); das Limit setzen wir selbst (1,2 x simulierter Verbrauch, höchstens 1,4 Mio. [J3, S1]) |
| `setupInstructions` | Associated Token Account | `CreateIdempotent` (Daten `[1]`) für das Ziel-Token-Konto der Wallet |
| `swapInstruction` | Jupiter v6 `JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4` | `route_v2` (direkt) oder `shared_accounts_route_v2` (mehrere Hops), 24 bis 79 Konten |
| `cleanupInstruction` | Token | `CloseAccount` (Daten `[9]`) des Wrapped-SOL-Kontos, nur beim Kauf von SOL |
| `otherInstructions`, `tipInstruction` | | leer (kein `tipAmount` gesetzt) |
| `addressesByLookupTableAddress` | | 1 bis 5 Lookup-Tabellen |

Die Diskriminatoren der Jupiter-Instruktionen stimmen mit Anchor (`sha256("global:<name>")[:8]`) überein:
`route_v2` `bb64facc31c4af14`, `shared_accounts_route_v2` `d19853937cfed8e9`. In
`shared_accounts_route_v2` waren Konto 1 die Wallet (einziger Signierer), Konto 2 ATA(Wallet, Eingabe-Mint),
Konto 5 ATA(Wallet, Ausgabe-Mint), Konto 6 und 7 die beiden Mints, 8 und 9 ihre Token-Programme; ab Konto 12
die Konten der Pools (39 von 67 schreibbar beim JTO-Weg). Die Stufe-2-Aufgabe legt diese Positionen gegen
Jupiters on-chain IDL fest (wie `txbuild.check_idl` für pump.fun), je Instruktion eigene Positionen (`route_v2`
hat eine andere Kontenfolge als `shared_accounts_route_v2`), und verweigert, wenn das IDL sich ändert. Weil ein
Upgrade des Programms das IDL-Konto nicht anfasst, pinnt der Guard zusätzlich den Code: den Slot des letzten
Deploys im ProgramData-Konto von Jupiter v6, vor jedem Signieren gelesen; weicht er vom gepinnten Wert ab, wird
nichts signiert, bis der Besitzer den neuen Wert bestätigt (Review B7).

### Was der Guard zulässt (neu: `lab/onchain/guard.py`)

Vorbild ist `txbuild.check_own`. Der Guard bekommt die Instruktionen, die aufgelösten Lookup-Tabellen
(von uns selbst von der Chain gelesen, nicht aus Jupiters Antwort übernommen), die Wallet, den erwarteten
Swap (Eingabe-Mint, Ausgabe-Mint, Betrag, Mindestmenge) und die Allowlist. Er wirft bei jeder Abweichung,
dann wird nichts signiert.

| Programm | erlaubt | sonst |
|---|---|---|
| ComputeBudget | genau ein `SetComputeUnitLimit` (<= 1,4 Mio.) und genau ein `SetComputeUnitPrice` (Preis x Limit <= harte Grenze 0,0005 SOL); fehlt eines, wird abgelehnt (ohne Limit gibt es kein Produkt zu prüfen, Review B6) | alles andere, auch `RequestHeapFrame` und `SetLoadedAccountsDataSizeLimit` |
| Associated Token Account | `Create` / `CreateIdempotent` mit Zahler = Eigentümer = Wallet, Mint auf der Allowlist, Token-Programm = klassisches Token | ATA für fremde Eigentümer, fremde Mints |
| Token (klassisch) | `CloseAccount` nur des eigenen Wrapped-SOL-Kontos, Ziel und Autorität = Wallet; `SyncNative` des eigenen Wrapped-SOL-Kontos | jedes Transfer, Approve, SetAuthority, Burn, Close an andere |
| System | eine Überweisung von der Wallet in ihr eigenes Wrapped-SOL-Konto (Wrap); höchstens ein Trinkgeld an ein Konto aus `txbuild.HELIUS_TIP_ACCOUNTS`, höchstens 0,0001 SOL | jede andere Überweisung, CreateAccount, Assign |
| Jupiter v6 | nur `route_v2`, `shared_accounts_route_v2`; Signierer = Wallet; Quelle = ATA(Wallet, Eingabe), Ziel = ATA(Wallet, Ausgabe); beide Mints auf der Allowlist; Eingabebetrag = geplanter Betrag; Mindestmenge (`quoted_out_amount` abzüglich `slippage_bps`) >= unsere Grenze, und diese Grenze auch >= Eingabewert zum Kraken-Mittelkurs abzüglich Schlupf der Klasse und 50 bps, also unabhängig von Jupiters eigener Quote (Review B3); kein Plattformgebühr-Konto | ExactOut, Token-Ledger, Gebühren an Dritte, ein anderes Ziel-Konto |
| alle anderen | nichts | |

Dazu für die ganze Nachricht: genau ein Signierer (die Wallet), Zahler = Wallet, Version 0, höchstens eine
Transaktion je Order.

**Beweis, dass jedes belastete oder gutgeschriebene Token-Konto uns gehört**, in zwei Schritten:

1. Statisch vor dem Simulieren: alle schreibbaren Konten der Nachricht (aus den Instruktionen und den
   aufgelösten Lookup-Tabellen) per `getMultipleAccounts` lesen. Jedes Konto, das ein Token-Konto mit der
   Wallet als Eigentümer ist (Feld `owner` bei Offset 32), muss eines der erwarteten sein: ATA(Wallet,
   Eingabe), ATA(Wallet, Ausgabe), ATA(Wallet, wSOL). Ein Token-Konto der Wallet mit Delegate oder fremder
   Close-Authority wird nie angefasst. Die Pool-Konten gehören den DEX-Programmen; ihre Tokens bewegt nur
   deren Programm, nicht unsere Signatur.
2. Dynamisch: `simulateTransaction` mit `accounts.addresses` = Wallet, alle ihre Token-Konten (beide
   Token-Programme, `getTokenAccountsByOwner`) und die drei erwarteten ATAs. Erlaubt ist nur: Eingabe sinkt
   um höchstens den Eingabebetrag, Ausgabe steigt um mindestens die Mindestmenge, SOL sinkt um höchstens
   Grundgebühr + Priority Fee + Trinkgeld + Miete neuer ATAs (bzw. um den Eingabebetrag beim Verkauf von
   SOL), kein anderes Konto der Wallet ändert sich, bei keinem ändert sich Eigentümer, Delegate oder
   Close-Authority. Nur eine Transaktion, die beides besteht, wird signiert. Weil wir selbst signieren, ist
   die signierte Nachricht genau die simulierte (gleicher Blockhash, gleiche Bytes).

Das fängt auch den schlimmsten Fall ab: eine kompromittierte Jupiter-API, die eine Instruktion unterschiebt,
die ein anderes Token-Konto der Wallet leert. Der statische Teil lehnt fremde Programme und Instruktionen ab,
der dynamische jede unerwartete Bewegung innerhalb des erlaubten Jupiter-Programms.

### Zwischen-Token und Token-2022

- **Zwischen-Token:** Mehrere Hops laufen über `shared_accounts_route_v2`; die Zwischenbeträge liegen in
  Konten von Jupiters Programmautorität, nicht in unserer Wallet. Gemessen: BONK, WIF, POPCAT, RAY über SOL,
  JTO über JitoSOL und SOL, PYTH zum Teil über TRUMP. Regel: jede Mint im `routePlan` muss auf der
  Weg-Allowlist stehen (wSOL, USDC, USDT, JitoSOL und die Stufe-2-Liste). Sonst eine neue Quote mit
  `maxAccounts` 40 oder `onlyDirectRoutes`, sonst kein Swap. Bleibt nach einem `route_v2` Restguthaben in
  einem Zwischen-ATA der Wallet, bucht das Ledger es und der nächste Lauf verkauft es.
- **Token-2022:** Alle Mints der Liste nutzen das klassische Token-Programm (`tokenProgram` aus [J5],
  2026-10-23). Stufe 2 lehnt Token-2022-Mints ab, auch als Zwischen-Token. Soll später eine dazu kommen
  (etwa PYUSD), dann nur einzeln und nur, wenn die Mint keine dieser Erweiterungen hat [S3]: TransferHook
  (fremder Code bei jeder Überweisung), PermanentDelegate (jemand kann unsere Tokens bewegen), Pausable,
  NonTransferable, DefaultAccountState gefroren, und TransferFee nur mit 0. Der Guard liest die Erweiterungen
  der Mint vor jedem Swap. Ob ein Zwischen-Token Token-2022 ist, entscheidet nicht der `routePlan` (Daten der
  API), sondern die Nachricht selbst: steht die Programm-ID von Token-2022 unter ihren Konten (auch aus den
  Lookup-Tabellen), wird abgelehnt (Review B5).
- **Größe:** Eine v0-Transaktion ist höchstens 1.232 Byte groß. Das Sender-Trinkgeld bringt ein Konto
  außerhalb der Lookup-Tabellen mit. Darum fragen wir mit `maxAccounts` 48 an; passt es trotzdem nicht,
  mit 40, dann kein Swap.

## 2. Die Liste für echtes Geld

Gemessen am 2026-10-23 aus der öffentlichen Quote-API (USDC nach Coin und sofort zurück, die Hälfte der
Rundreise in bps; daneben Jupiters `priceImpactPct` der Hinrichtung), ohne Netzgebühren. Mints gegen Jupiters
Token-Liste geprüft (Tag `verified`, die meisten auch `strict`), Herausgeber wo es einen gibt.

| Coin | Token, Mint | Herausgeber, Prüfung | Liquidität (Jupiter) | 10 USD | 100 USD | 1.000 USD | Weg |
|---|---|---|---|---|---|---|---|
| USDC | `EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v` | Circle [I1], verified, strict | Cash | | | | |
| SOL | wSOL `So11111111111111111111111111111111111111112` | nativ, verified, strict | 930 Mio. USD | -1,7 | -0,5 | 0,2 | direkt |
| BTC | cbBTC `cbbtcf3aa214zXHbiAZQwf4122FBYbraNdFqgw4iMij` | Coinbase [I2], verified | 28 Mio. | 0,1 | 0,6 | 0,7 | direkt |
| ETH | WETH (Portal) `7vfCXTUXx5WJV5JADk17DUJ4ksgau7utNKj4b963voxs` | Wormhole-Bridge, verified, strict | 21 Mio. | 0,8 | 2,4 | 0,7 | direkt |
| JUP | `JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN` | Jupiter, verified, strict | 5,4 Mio. | 0,6 | 1,2 | 3,6 | direkt |
| TRUMP | `6p6xgHyF7AeE6TZkSmFsko444wqoP15icUSqi2jfGiPN` | verified | 25 Mio. | 0,4 | 5,5 | 1,3 | direkt / über SOL |
| RAY | `4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R` | Raydium, verified, strict | 17 Mio. | 4,8 | 5,6 | 4,3 | über SOL / direkt |
| BONK | `DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263` | verified, strict | 6,1 Mio. | 5,3 | 6,4 | 19,9 (Impact 16) | über SOL |
| WIF | `EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm` | verified, strict | 6,1 Mio. | 4,5 | 7,8 | 28,7 | über SOL |
| PYTH | `HZ1JovNiVvGrGNiiYvEozEVgZ58xaU3RKwX8eACQBCt3` | verified, strict | 0,4 Mio. | 1,3 | 11,8 | 33,0 (Impact 38) | über SOL, TRUMP |
| RENDER | `rndrizKT3MK1iimdxRdWabcF7Zg7AR5T4nud4EkHBof` | verified, strict | 0,3 Mio. | 12,1 | 13,9 | 28,8 | ein Orderbuch (Manifest) |
| JTO | `jtojtomepa8beP8AuQc6eXt5FriJwfFMwQx2v2f9mCL` | Jito, verified, strict | 0,5 Mio. | 21,0 | 21,6 | 26,8 (Impact 51) | über JitoSOL, SOL |
| POPCAT | `7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr` | verified, strict | 4,2 Mio. | 11,3 | 25,2 | 30,6 | über SOL |
| (WBTC) | Portal `3NZ9JMVBmGAqocybic2c7LQCJScmgsAZ6vQqTDzcqmJh` | Wormhole, verified, strict | 38 Mio. | 0,7 | 0,4 | 0,6 | über cbBTC |

Netzgebühren kommen dazu: 5.000 Lamports Grundgebühr, eine Priority Fee von heute etwa 25.000 Lamports
(80.000 Micro-Lamports x etwa 300.000 CU) und 5.000 Lamports Sender-Trinkgeld, zusammen etwa 0,00004 SOL,
rund 0,4 Cent: 4 bps bei 10 USD, 0,4 bps bei 100 USD. Ein neues Token-Konto bindet einmal 0,00204 SOL Miete
(rund 21 Cent, zurück beim Schließen). Ein 10-USD-Trade ist also erst ab dem zweiten Swap in derselben Mint
billig; die Bücher handeln nicht unter 25 USD je Swap.

**Entscheidung für die erste Echtgeld-Liste:**

- Voll: SOL, USDC, BTC als cbBTC (vom Herausgeber, direkte Pools; WBTC nicht, es läuft ohnehin über cbBTC
  und trägt das Bridge-Risiko), ETH als WETH (Portal; es gibt keine Herausgeber-Version auf Solana, darum
  höchstens 25 % des Gesamtbetrags), JUP, TRUMP, RAY, BONK, WIF.
- Nur bis 100 USD je Trade: PYTH, RENDER, JTO, POPCAT (20 bis 50 bps bei 1.000 USD).
- Risiko der Herausgeber, offen genannt: Circle kann USDC-Konten einfrieren, Coinbase hält Mint- und
  Freeze-Recht an cbBTC, WETH hängt an der Wormhole-Bridge. Das steht im Ack; ein eingefrorenes Konto
  meldet der Watcher.
- Gegengeprüft, aber **nicht** auf der Liste, weil kein Herausgeber die Mint bestätigt: wNEAR (3,6 Mio.
  Liquidität, 1,6 / 0,7 bps bei 100 / 1.000 USD), HYPE (3,7 Mio., 0,8 / 1,2), DOGE (4,4 / 6,7), wXRP
  (10 / 28), LINK (20 / 60), cbLTC (31 / 101). wNEAR ist interessant, weil `breakout_top10_live` heute NEAR
  hält; das ist eine eigene Prüfung (Bridge, Herausgeber), keine Annahme.
- **Ohne sichere Solana-Form, die Bücher halten Cash:** von Kraken NEAR, SUI, DOGE, XRP, ADA, AVAX, LINK,
  LTC, DOT, BCH, PEPE, SHIB; von Alpaca zusätzlich AAVE, ARB, BAT, CRV, FIL, GRT, HYPE, LDO, ONDO, POL, SKY,
  SUSHI, UNI, XTZ, YFI.

Die Stufe-2-Mints sind dieselben wie in `lab/onchain/mints.py`; der Code liest die Allowlist von dort und
prüft jeden Tag gegen [J5] (Tag `verified`, `tokenProgram` klassisch, Freeze-Recht unverändert). Weicht etwas
ab, wird die Mint gesperrt, bis der Besitzer sie neu bestätigt. Die Kosten je Größe misst das Paper-Buch
weiter täglich (Proben bei 10, 100 und 1.000 USD statt nur 100).

## 3. Einzahlen, Umtauschen, Abheben

- **Einzahlen:** Eine eigene Wallet, erzeugt mit dem vorhandenen Werkzeug
  (`python -m lab.pumpfun_rt.wallet new --out /etc/pythia/onchain-keypair.json`), nie die pump.fun-Wallet.
  Die App zeigt die öffentliche Adresse mit QR-Code wie auf der Seite "pump.fun wallet" (im Browser
  erzeugt). Du schickst SOL (oder USDC) von deiner eigenen Wallet oder Börse, nicht mehr als dein
  `max_total_usd` plus 0,05 SOL für Gebühren und Kontomieten.
- **Umtauschen ("convert") in der App:** Du wählst "von", "nach" und Betrag. Die App schreibt nur eine
  Anfrage in ihren Ordner (`reports/onchain_live/convert/`, wie `settings.json` und `KILL` beim pump.fun-Bot).
  Der Live-Dienst holt eine Quote, prüft Caps und Allowlist und zeigt dir einen Vorschlag: erwartete Menge,
  Mindestmenge, Kosten in bps, Weg. Erst deine Bestätigung in der App (gültig 60 Sekunden, an genau diesen
  Vorschlag gebunden) lässt ihn tauschen: neue Quote, höchstens so schlecht wie die Mindestmenge des
  Vorschlags, dann Guard, Simulation, Senden. Es ist derselbe Weg wie bei einem Buch-Trade, also gibt es
  keine Überweisung: Der Guard kennt keine Transfer-Instruktion, nur Tausch innerhalb der eigenen Wallet.
  Umtausch zählt zu den Tages-Caps (`max_convert_usd` je Tag). Der Vorschlag trägt eine zufällige ID, die der
  Dienst vergibt; eine Bestätigung gilt nur für diese ID, und der Dienst schreibt sie als verbraucht ins Ledger,
  bevor er signiert. Eine zweite Bestätigung derselben ID, auch nach einem Neustart, tauscht nie ein zweites
  Mal. Den Betrag prüft der Dienst selbst (endliche Zahl > 0, höchstens `max_trade_usd` und der Tagesrest),
  die Prüfung im Server ist nur Komfort; Server und App schreiben nur Anfrage, Bestätigung und `KILL`, nie
  eine Transaktion oder einen Schlüssel (Review B1, B8).
- **Buch gegen Besitzer:** Die Wallet hat zwei Konten im Ledger: den Teil des Buchs (`book_usd` im Ack) und
  deinen Rest. Ein Buch handelt nie mehr als seinen Teil; du tauschst nur in deinem Rest. Die Summe beider
  muss jeden Tag mit den Guthaben auf der Chain übereinstimmen.
- **Abheben bleibt außerhalb von Pythia:** wie beim pump.fun-Bot (PUMPFUN-LIVE.md, Schritt 9). Dienst per
  Notschalter stoppen, warten bis nichts mehr läuft, das Backup-Secret in deine eigene Wallet (Phantom oder
  Solflare) importieren und von dort senden. Pythia hat keine Funktion dafür und bekommt keine.

## 4. Caps und Tore im Ack

Die Bestätigungsdatei `/etc/pythia/onchain-live-ack` (Rechte 600), gelesen wie `live_exec.read_ack`:

```
mode=test
books=onchain_breakout_top10_live
mints=SOL,USDC,BTC,ETH,JUP
book_usd=150
max_total_usd=200
max_trade_usd=100
max_daily_loss_usd=30
max_convert_usd=100
expires=2026-12-31
I accept that I can lose all of it
```

| Grenze | Höchstwert im Code (Testmodus) | was sie tut |
|---|---|---|
| `max_total_usd` | 500 USD (im Entwurf 1.000; der Code nimmt den kleineren Wert) | Wert der Wallet (Buch und Rest) zu Jupiter-Preisen; darüber kauft nichts mehr, nur Verkäufe nach USDC |
| `max_trade_usd` | 100 USD (im Entwurf 250) | je Swap; PYTH, RENDER, JTO, POPCAT ebenfalls höchstens 100 |
| `max_daily_loss_usd` | 100 USD | Rückgang des Buchwerts seit Beginn des UTC-Tages; dann keine Käufe bis morgen, Verkäufe nach USDC weiter erlaubt |
| `max_convert_usd` | 250 USD je Tag | Umtausch aus der App |
| Swaps je Tag | 40 je Buch, 10 Umtausch | gegen Schleifen |
| Schlupf | 30 bps (SOL, USDC, cbBTC, WETH, JUP, TRUMP, RAY), 75 (BONK, WIF), 150 (PYTH, RENDER, JTO, POPCAT) | Mindestmenge der Quote |
| Kosten je Swap | Hälfte der Rundreise über 50 bps: kein Swap | gegen dünne Märkte |
| Priority Fee | 0,0005 SOL je Transaktion | harte Grenze |
| Sender-Trinkgeld | 0,0001 SOL | wie beim pump.fun-Bot |
| Reserve | 0,02 SOL | bleibt immer für Gebühren |
| `mints`, `books` | Teilmenge der Liste im Code | was nicht dasteht, wird nicht gehandelt |
| `expires` | höchstens 90 Tage | danach kein Swap |

Wie beim pump.fun-Bot: Eine Datei über den Höchstwerten wird abgelehnt, die App kann jede Grenze nur senken,
und die letzte Zeile muss wörtlich dastehen. Ein Wert der App gilt nur, wenn er eine endliche Zahl > 0 ist
(kein NaN, kein Inf, kein bool, wie `live_exec.read_settings`), sonst der Wert des Acks: ein NaN als Grenze
ließe jeden Vergleich `Betrag > Grenze` falsch ausgehen (Review B8). Preise in USD von Jupiter, gegen Krakens Mittelkurs geprüft;
weichen sie um mehr als 2 % ab, kein Swap.

Die übrigen Tore, alle wie beim pump.fun-Bot:

- `PYTHIA_ONCHAIN_LIVE=1` und `PYTHIA_ONCHAIN_KEYPAIR`, Wallet-Datei mit `.pub`, Rechte 600, außerhalb des
  Code-Ordners.
- **Simulation innerhalb von 24 Stunden:** `python -m lab.onchain.live_exec simulate` baut einen Kauf und
  einen Verkauf (USDC nach SOL und zurück, 10 USD) mit dem echten Guthaben als Zahler, mit Trinkgeld, und
  simuliert beide; geschrieben nach `live/onchain/simulate.json`. Älter als 24 Stunden: keine Käufe.
- **Notschalter:** `reports/onchain_live/KILL` aus der App oder `/etc/pythia/onchain-kill`. Ab dann wird nichts
  mehr signiert, auch kein Verkauf, kein Rebalance und kein Umtausch: der Schalter ist für den Fall gedacht,
  dass Guard oder API verdächtig sind, und jeder Swap läuft durch denselben Weg (Review B2). Nur mit
  `on_kill=usdc` im Ack verkauft der Dienst einmal alles nach USDC, mit allen Prüfungen; Standard `hold`.
  Geprüft wird der Schalter im Signierpfad unmittelbar vor dem Signieren, nicht nur im Status.
  Lösen nur auf dem Server.
- **Watcher:** Job `onchain-live-watch` alle zwei Minuten: Dienst läuft, keine hängende Order, Ledger gegen
  Chain sauber, Simulation bald abgelaufen, ein Token-Konto eingefroren, Mint-Prüfung fehlgeschlagen. Jeder
  Fund geht sofort an Telegram und Discord.
- **Enge Mounts:** der Container sieht von `/etc/pythia` nur Wallet-Datei, `.pub` und Ack, den Code
  schreibgeschützt aus `/opt/pythia-live`.
- **Ledger gegen Chain:** jede Signatur nachlesen (`getTransaction`, `preTokenBalances` /
  `postTokenBalances` der Wallet), wie `chain_pnl.reconcile`. Tages- und Gesamtergebnis werden aus dem
  Ledger neu berechnet, nie hochgezählt.
- **Nachweis vor echtem Geld:** `research/lab/results/onchain_stage2_prereg.md`. Kurz: das Buch besteht die
  Paper-Regel aus LIVE-READINESS.md, sein On-Chain-Paper-Zwilling hat 30 Tage und 20 Rebalances mit
  Kosten im Median höchstens 15 bps je gehandelter Einheit, und der Executor lief 14 Tage im Schatten
  (bauen, prüfen, simulieren, nie senden) mit mindestens 98 % sauberen Simulationen und null ungeklärten
  Guard-Ablehnungen. Danach 14 Tage mit höchstens 200 USD, erst dann höhere Grenzen.

## 5. Geschwindigkeit und Landen

### Für die Bücher (Stufe 2)

Die Bücher handeln einmal am Tag; "so schnell wie möglich" heißt hier vor allem sicher landen und keine
veraltete Quote senden.

- **Quote und Bau vorbereiten:** Blockhash alle 10 s mit `confirmed` holen (nach [S2] die richtige Wahl;
  `/build` liefert auch einen), Lookup-Tabellen und die Token-Konten der Wallet im Speicher. Der Rebalance
  holt alle `/build`-Antworten zuerst (Verkäufe, dann Käufe aus dem frei gewordenen USDC). Ohne Schlüssel
  sind es 0,5 Anfragen pro Sekunde [J4], also 20 s für 10 Coins; mit dem kostenlosen Jupiter-Schlüssel 1 pro
  Sekunde, mit "Developer" 10. Für Stufe 2 reicht der kostenlose Schlüssel (`PYTHIA_JUPITER_API_KEY`).
- **Priority Fee:** Vorschlag aus `/build` (`computeUnitPricePercentile=high`, das 50. Perzentil der
  jüngsten Gebühren [J3]) oder Helius `getPriorityFeeEstimate` mit der Transaktion (Stufe `Medium` laut
  Helius der Startpunkt [H2]), gedeckelt auf 0,0005 SOL je Transaktion. Heute waren das etwa 0,000025 SOL.
- **Senden:** Helius Sender `/fast?swqos_only=true` wie beim pump.fun-Bot [H1]: ein Trinkgeld ab 0,000005 SOL,
  Pflicht sind Trinkgeld und `SetComputeUnitPrice`. Für Swaps zusätzlich `mev-protect=true`, das laut Helius
  an Validatoren vorbei leitet, die mit Sandwich-Angriffen verbunden sind [H1]. Ohne Schlüssel 1 Anfrage pro
  Sekunde je IP und Region; eine regionale Adresse (Frankfurt oder Amsterdam) und ein `/ping` alle 5 s halten
  die Verbindung warm [H1]. Gleichzeitig dieselbe signierte Transaktion an den normalen RPC.
- **Bestätigung:** `signatureSubscribe` per Websocket mit `confirmed`, dazu `getSignatureStatuses` jede
  Sekunde als Rückfall.
- **Wiederholen:** Jede Order hat eine ID; ihre Signatur, der signierte Blockhash und dessen
  `lastValidBlockHeight` stehen im Ledger (geschrieben und synchronisiert), bevor das erste Mal gesendet wird.
  Ein Blockhash, eine Quelle: der, den wir signiert haben. Dieselbe signierte Transaktion alle 2 s erneut
  senden, bis sie bestätigt ist oder die Blockhöhe (`confirmed`, wie der Blockhash) über `lastValidBlockHeight`
  liegt (60 bis 90 s [S2]). Danach einmal `getSignatureStatuses` mit `searchTransactionHistory`: erst wenn die
  Signatur auch dort fehlt, gilt die Order als nicht gelandet (Review B4). Ein Neustart liest offene Orders
  aus dem Ledger und klärt erst deren Signatur so, bevor er für dieselbe Order etwas Neues baut. Erst danach eine neue Quote, neuer Guard,
  neue Simulation; höchstens 3 Versuche je Order, dann Abbruch und Meldung. Nie zwei Versionen derselben
  Order gleichzeitig unterwegs.
- **Schlupf:** fest je Klasse (Tabelle oben), nicht Jupiters RTSE: Der Guard braucht eine Mindestmenge, die
  wir selbst gesetzt haben.

### Der pump.fun-Bot: woher die 5 bis 20 s kommen

Gelesen aus `live/pumpfun_rt/measured.jsonl` und `orders.jsonl` (65 Abschlüsse vom 22.10. 17:09 bis
23.10. 06:45 UTC, 28 Käufe und 28 Verkäufe seit dem Sender-Pfad ab 22.10. 21:41 UTC). Wichtig zum Lesen:
"Signal" ist die Zeit, zu der unser Datenstrom das erste Ereignis des Slots empfangen hat, nicht die Zeit
des Blocks; "gelandet" ist die Zeit, zu der derselbe Strom unseren Abschluss zeigt. "Signal bis Order" ist
die Zeit bis `buy()` / `sell()` im Executor, "Order bis gesehen" der Rest.

| seit Sender | n | p25 | Median | p75 | p90 |
|---|---|---|---|---|---|
| Kauf, Signal bis gelandet | 28 | 2,9 s | 10,8 s | 19,4 s | 29,6 s |
| Kauf, Signal bis Order | 28 | 0,7 s | 3,3 s | 10,6 s | 28,7 s |
| Kauf, Order bis gesehen | 28 | 0,1 s | 1,6 s | 8,2 s | 14,9 s |
| Verkauf, Signal bis gelandet | 28 | 1,0 s | 3,9 s | 12,9 s | 37,0 s |
| Verkauf, Signal bis Order | 28 | 0,0 s | 0,5 s | 4,7 s | 37,4 s |
| Verkauf, Order bis gesehen | 28 | -0,3 s | 0,5 s | 2,3 s | 10,0 s |
| vor Sender: Verkauf, Order bis gesehen | 4 | 11,8 s | 15,8 s | 26,7 s | |

Jeder Abschluss brauchte genau einen Sendeversuch (kein Wiederholen). Die 121 Fehlschläge "Transaction
simulation failed" betreffen fast alle ein einziges Token, das sich nicht verkaufen ließ; sie verlängern
keine der Zeiten oben.

Daraus:

1. **Das Senden ist nicht mehr der Engpass.** Vor Sender lag ein Verkauf 16 s zwischen Order und Landung,
   seit Sender 0,5 s im Median. Negative Werte heißen: Der Strom zeigt unseren Abschluss mit einem Slot-
   Zeitstempel, der vor unserer Order lag; die Messung ist auf etwa eine Sekunde genau.
2. **Der lange Schwanz liegt vor der Order.** Die drei langsamsten Verkäufe (37 bis 38 s, zwei Stops, ein
   Take) hatten 37 s zwischen dem ersten Ereignis ihres Slots und unserer Order: Das Handelsereignis des
   Pools kam über den öffentlichen Websocket so viel später als andere Ereignisse desselben Slots
   (`latency.md`: "behind the first event of the slot", p90 4,9 s, p99 64 s). Ein Stop sieht den Kurs erst,
   wenn dieses Ereignis ankommt.
3. **Dazu kommt der Rückstand des Stroms hinter der Chain, der in diesen Zahlen gar nicht steckt:** neue
   Token im Median 8,2 s nach ihrem Block (p90 39,7 s), Kurvenhandel 8,7 s (p90 40,9 s), mit Stunden von
   1,5 s bis 20 s im Median (`latency.md`). Ein Stop bei -10 % landete deshalb im Mittel bei -23 % (Y8).

**Kostenlose Verbesserungen (eigene Aufgabe, in dieser Reihenfolge):**

- Für jede offene Position die beiden Tresor-Konten des Pools per `accountSubscribe` mit `processed`
  beobachten (wenige Konten, auch auf dem öffentlichen Websocket). Der Stop rechnet dann aus dem Tresor,
  ohne auf das Handelsereignis zu warten. Betrifft den Schwanz aus Punkt 2.
- Die Landung über den Status der eigenen Signatur messen und bestätigen (`signatureSubscribe` am
  Sende-RPC), nicht über den Strom. Macht die Zahlen ehrlich und das Wiederholen früher.
- Sender über die regionale Adresse und mit `/ping` alle 5 s [H1]; heute globale Adresse ohne Ping.
- Verkaufs-Transaktionen für offene Positionen vorbauen (der schnelle Pfad braucht 0,3 ms), Blockhash alle
  10 s erneuern; bei einem Stop nur noch Mindestmenge setzen, signieren, senden.
- Priority Fee aus den jüngsten Gebühren der Pool-Konten statt fest 0,001 SOL: billiger in ruhigen Minuten,
  höher, wenn es eng wird (Obergrenze bleibt).

**Bezahlte Optionen** (Preise [H4], [H3], am 2026-10-23):

| Option | Preis im Monat | was es ändert | geschätzt für P_pool0 |
|---|---|---|---|
| Helius Developer | 49 USD | Schlüssel-RPC mit gestakten Verbindungen, 50 Anfragen/s, `transactionSubscribe`; LaserStream nur Devnet | Strom eher 0,5 bis 2 s statt 8 s hinter der Chain (Richtwert aus PUMPFUN-LIVE.md, nicht gemessen); nahe am Szenario (c) |
| Helius Business | 499 USD | LaserStream gRPC auf Mainnet (Yellowstone-kompatibel), 200 Anfragen/s | etwa 1 bis 2 Slots hinter dem Block; für P_pool0 kaum mehr als Developer |
| Shred Delivery | 1.000 USD je IP (800 mit Pro) | rohe Shreds | nur für den Erstellungs-Slot; laut `results/pumpfun_speed.md` lohnt das Sniping nicht |
| eigener Knoten | ab 2.900 USD | dediziert | wie oben |
| andere Anbieter (Triton, QuickNode, Chainstack) | 50 bis 1.000 USD | siehe PUMPFUN-LIVE.md, nicht für heute geprüft | ähnlich |

**Was das für P_pool0 wert ist:** Y5 hat die Kauf-zur-Migration-Regel (`E_d0_x1`, der Vorläufer von P_pool0)
bei gemessener Latenz mit -4,6 % je Trade und bei einem 1,5-s-Pfad (Szenario c) mit -1,7 % gemessen: etwa
+3 Punkte je Trade, aber weiterhin negativ. Y8: Der registrierte Test von P_pool0 lag bei (c) bei -25 % gegen
-41 % bei (b), aber mit 8 bis 16 Einträgen und dem Tageslimit kein belastbarer Wert; die Stops landeten bei
-23 % statt -10 %, und nur ein schnellerer Verkauf kommt näher. Y9: Die "Top 30 %"-Filter liegen 6 bis 9
Punkte vorn, ohne die Schwelle zu bestehen. Bei 0,05 SOL Einsatz und 20 bis 60 Trades am Tag sind 3 Punkte
etwa 0,03 bis 0,09 SOL am Tag, rund 3 bis 9 USD (SOL bei etwa 104 USD laut Quote), also 90 bis 280 USD im
Monat weniger Verlust. Das deckt Developer (49 USD), nicht Business (499 USD), und macht die Strategie nicht
positiv.

**Empfehlung:** erst die kostenlosen Verbesserungen, eine Woche messen. Dann, wenn du willst, einen Monat
Helius Developer, mit `latency probe` vorher und nachher. LaserStream, Shreds und einen eigenen Knoten
nicht kaufen, solange keine Pool-Regel nach Kosten positiv ist.

## 6. Bauplan und Risiken

### Aufgaben, in dieser Reihenfolge (jede eigene Aufgabe, jede mit Tests)

| # | Modul, Dateien | was | Tests |
|---|---|---|---|
| 1 | `lab/onchain/swapapi.py` | Client für `/swap/v2/build` (Schlüssel optional aus `PYTHIA_JUPITER_API_KEY`), Antwort in Instruktionen; Stufe 1 und das Paper-Buch wechseln auf denselben Weg | aufgezeichnete Antworten (Absender erfunden), Rate-Limit, Fehler |
| 2 | `lab/onchain/tx.py` | v0-Nachricht mit Lookup-Tabellen bauen und zurücklesen (ohne pump.fun-Code zu ändern) | Rundreise Bauen / Lesen, Größe, Vergleich mit `solders` |
| 3 | `lab/onchain/guard.py` | statischer Guard, Effekt-Prüfung der Simulation, Jupiter-IDL-Prüfung, Mint-Prüfung (Token-2022, Erweiterungen) | jede verbotene Variante einzeln: fremdes Ziel-Konto, zweiter Signierer, Transfer, Approve, SetAuthority, Close an andere, falsche Mint, ExactOut, Gebührenkonto, zwei Trinkgelder, Trinkgeld über der Grenze, Token-2022-Zwischen-Token (nur in der Nachricht, nicht im `routePlan`), Simulation mit Abfluss aus einem dritten Konto, fehlendes oder doppeltes Compute-Limit, Mindestmenge unter dem Kraken-Wert, Jupiter-Code neu deployt |
| 4 | `lab/onchain/shadow.py`, Job `onchain-shadow` | Schatten-Ausführung: jeden geplanten Swap des Paper-Buchs bauen, prüfen, mit der öffentlichen Adresse als Zahler simulieren, nie signieren; Bericht | Plan zu Simulation, Zählung für den Nachweis |
| 5 | `lab/onchain/live_gate.py` | Ack, Caps, Notschalter, Simulation-Datei, Mounts (wie `LiveGate`) | Ack über den Grenzen, abgelaufen, fehlende Zeile, App senkt nur, NaN/Inf/bool/negativ der App ignoriert, Notschalter sperrt auch Verkauf und Umtausch |
| 6 | `lab/onchain/live_exec.py`, `live_service.py` | Signieren (wie `load_signer`), Sender, Bestätigung, Wiederholen, Ledger; Testmodus | Fake-RPC, Kill mitten im Lauf, Ablauf des Blockhash, Caps, Neustart mit offener Order sendet nie doppelt, späte Landung nach Ablauf, Umtausch-Bestätigung nur einmal |
| 7 | `lab/onchain/chain_ledger.py`, Job `onchain-live-watch` | Ledger gegen Chain, Watcher, Telegram und Discord | Abweichung, eingefrorenes Konto |
| 8 | App: Seite "Solana wallet" | Adresse mit QR, Guthaben, Grenzen senken, Notschalter, Umtausch mit Bestätigung | vitest |
| 9 | `lab/onchain/proof.py` | Bericht zum Nachweis (`reports/onchain/proof.json`) | Regeln aus der Vorab-Registrierung |

### Was du zum Scharfschalten tust (erst nach dem Nachweis)

1. Wallet erzeugen (`wallet new --out /etc/pythia/onchain-keypair.json`), Backup sichern (wie
   PUMPFUN-LIVE.md, Schritt 2).
2. Kleinen Betrag einzahlen (höchstens `max_total_usd` plus 0,05 SOL).
3. Ack schreiben (Abschnitt 4), `/etc/pythia/onchain-live.env` mit `PYTHIA_ONCHAIN_LIVE=1`,
   `PYTHIA_ONCHAIN_KEYPAIR`, optional `PYTHIA_JUPITER_API_KEY` und der Sender-Adresse.
4. `live_exec simulate`, dann `live_exec check`.
5. Den Container mit den engen Mounts starten; Watcher prüfen.

### Risiken, nach Schwere

1. **Ein Fehler im Guard signiert etwas Fremdes.** Dagegen: statische Prüfung plus Effekt-Prüfung der
   Simulation, die Tests jeder verbotenen Variante, kleiner Betrag in der Wallet, kein Transfer im Guard.
2. **Jupiters Programm wird geändert** (es ist aufrüstbar) oder seine API liefert Unerwartetes. Dagegen:
   IDL-Prüfung, Effekt-Prüfung, Ablehnung bei jeder Abweichung.
3. **Diebstahl des Schlüssels vom Server.** Dagegen: Datei 600 in `/etc/pythia`, nur der Live-Container
   sieht sie, nie in der Umgebung, nie im Log; nur Geld, das verloren gehen darf.
4. **Herausgeber und Bridges:** USDC und cbBTC können eingefroren werden, WETH hängt an Wormhole. Dagegen:
   ETH-Anteil gedeckelt, Watcher meldet eingefrorene Konten.
5. **Schlechte Fills:** veraltete Quote, Sandwich, dünne Märkte. Dagegen: Mindestmenge je Klasse,
   `mev-protect`, Kosten-Grenze 50 bps, Kraken-Preis als Gegenprobe.
6. **Hängende oder doppelte Orders.** Dagegen: eine Version je Order, Wiederholen nur bis zum Ablauf des
   Blockhash, Ledger gegen Chain.
7. **Die Strategie selbst.** Billigere Fills machen kein Buch profitabel. `breakout_top10_live` hat noch keinen
   Nachweis; der Nachweis in der Vorab-Registrierung ist die Bedingung, nicht die Kostenmessung.
8. **Steuern:** jeder Swap ist ein steuerlich relevanter Vorgang; das Ledger hat jede Signatur.

## 7. Der Händler ist gebaut: was er tut und wie du ihn scharf schaltest

### Was gebaut ist (alles gesperrt, bis jeder Schritt unten erledigt ist)

| Datei | was |
|---|---|
| `lab/onchain/swapapi.py` | `/swap/v2/build` für unsere Wallet, mit unserem Schlupf; Jupiters Compute-Budget wird verworfen, Lookup-Tabellen nur als Adressen übernommen |
| `lab/onchain/tx.py` | v0-Nachricht mit Lookup-Tabellen bauen und aus denselben Bytes zurücklesen (gegen `solders` getestet) |
| `lab/onchain/guard.py` | der Guard: prüft die vollständige Nachricht, jedes schreibbare Konto auf der Chain und die Kontodifferenz der Simulation (Abschnitt 1) |
| `lab/onchain/live_gate.py` | die Tore: Umgebung, Ack, Wallet-Datei (nicht die pump.fun-Wallet), Simulation in 24 h, Notschalter, Jupiter-IDL, Endpunkte; die Höchstwerte im Code |
| `lab/onchain/live_exec.py` | Caps, Bauen, Guard, Simulation, Signieren, Senden (Sender und RPC), Wiederholen bis zum Ablauf des Blockhash, höchstens 3 Versuche; Ledger aus der Chain, Abgleich mit den echten Guthaben; `check` und `simulate` |
| `lab/onchain/live_service.py` | der Dienst `pythia-onchain-live`: Status für die App, Umtausch mit Bestätigung, Bücher nur nach bestandenem Nachweis, Notschalter |
| `lab/onchain/wallet.py` | das Wallet-Werkzeug für diese Wallet (eigene Datei, eigener App-Ordner) |
| `research/ops/onchain_live_watch.py` | der Watcher, Job `onchain-live-watch` alle zwei Minuten |
| App, Seite "Real money" | Abschnitt "On-chain wallet": Adresse mit QR, Guthaben in USD und EUR, Umtausch mit Vorschau und Bestätigung, Trades, Gründe des Tors, Notschalter |

Höchstwerte im Code (Testmodus; der Alpha-Modus hat niedrigere, Abschnitt 8): 500 USD Wert der Wallet, 100 USD je Swap, 100 USD
Tagesverlust, 250 USD Umtausch am Tag, 10 Umtausche und 40 Swaps je Buch am Tag, ETH höchstens ein Viertel von
`max_total_usd`, 0,02 SOL Reserve, Kosten höchstens 50 bps, Jupiter-Preis höchstens 2 % neben Kraken,
Priority Fee höchstens 0,0005 SOL, Sender-Trinkgeld höchstens 0,0001 SOL. Ein Ack über einem Höchstwert wird
abgelehnt. Ein Buch handelt nur, wenn der Ack es nennt und `reports/onchain/proof.json` (kommt mit
`lab.onchain.proof`, einer späteren Aufgabe) sagt, dass es den Nachweis bestanden hat; bis dahin handelt
kein Buch, nur dein Umtausch.

Der Ledger (`live/onchain/ledger.csv`) bekommt jeden Swap so, wie die Chain ihn zeigt (`getTransaction`).
Alle 30 Sekunden vergleicht der Dienst: Guthaben beim Start plus alle Swaps plus erkannte Einzahlungen muss
gleich dem sein, was die Chain zeigt. Mehr ist eine Einzahlung (`live/onchain/journal.jsonl`), weniger ohne
Swap stoppt jeden Kauf, bis du den Dienst neu startest, und geht sofort an Telegram und Discord.

### Deine Schritte (erst nach dem Nachweis, Abschnitt 4)

Alle Befehle auf dem Server, als root.

1. **Code bereitstellen:** `research/ops/deploy_live.sh` (der Dienst läuft aus `/opt/pythia-live`, wie der
   pump.fun-Bot; das Image `pythia-lab` hat `cryptography` schon).
2. **Neue Wallet, nur für diesen Händler** (nie die pump.fun-Wallet; das Werkzeug verweigert deren Datei,
   das Tor verweigert deren Adresse):

   ```bash
   docker run --rm -it -v /etc/pythia:/etc/pythia -v /srv/pythia-data:/data -v /opt/pythia-live:/app:ro \
     pythia-lab python -m lab.onchain.wallet new --out /etc/pythia/onchain-keypair.json
   ```

   Das Backup-Secret wird einmal gezeigt, nach `YES`. Offline aufbewahren (wie PUMPFUN-LIVE.md, Schritt 2):
   es ist dein einziger Weg, Geld abzuheben. Die App zeigt die Adresse danach mit QR-Code.
3. **Jupiters IDL ablegen:** das On-Chain-IDL des Programms `JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4`
   (z. B. `anchor idl fetch JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4`) als
   `/srv/pythia-data/onchain/idl/jupiter.json`. Das Tor prüft, dass `route_v2` und `shared_accounts_route_v2`
   die erwarteten Diskriminatoren, Konten und Beträge an festen Stellen haben; sonst bleibt es zu.
4. **Einzahlen:** SOL (und wenn du willst USDC) an die Adresse schicken, höchstens dein `max_total_usd` plus
   0,05 SOL für Gebühren und Kontomieten.
5. **Ack schreiben**, `/etc/pythia/onchain-live-ack`, Rechte 600, mit einem Ablaufdatum höchstens 90 Tage
   voraus. Für den ersten Test (Nachweis Schritt D) höchstens 200 USD:

   ```
   mode=test
   mints=SOL,USDC,BTC,ETH
   max_total_usd=200
   max_trade_usd=50
   max_daily_loss_usd=30
   max_convert_usd=100
   expires=2026-12-31
   on_kill=hold
   I accept that I can lose all of it
   ```

   `books=onchain_breakout_top10_live` und `book_usd=150` erst, wenn der Nachweis bestanden ist.
6. **Umgebung**, `/etc/pythia/onchain-live.env`, Rechte 600: `PYTHIA_ONCHAIN_LIVE=1`,
   `PYTHIA_ONCHAIN_KEYPAIR=/etc/pythia/onchain-keypair.json`, optional `PYTHIA_ONCHAIN_RPC` (https),
   `PYTHIA_ONCHAIN_SENDER` (Helius Sender, `/fast?swqos_only=true&mev-protect=true`),
   `PYTHIA_ONCHAIN_SENDER_TIP_SOL` und `PYTHIA_JUPITER_API_KEY`.
7. **Simulieren und prüfen** (nichts wird signiert oder gesendet; die Simulation braucht nur die `.pub`):

   ```bash
   docker run --rm --env-file /etc/pythia/onchain-live.env -v /srv/pythia-data:/data -v /opt/pythia-live:/app:ro \
     -v /etc/pythia/onchain-live-ack:/etc/pythia/onchain-live-ack:ro \
     -v /etc/pythia/onchain-keypair.json.pub:/etc/pythia/onchain-keypair.json.pub:ro \
     pythia-lab python -m lab.onchain.live_exec simulate
   docker run --rm --env-file /etc/pythia/onchain-live.env -v /srv/pythia-data:/data -v /opt/pythia-live:/app:ro \
     -v /etc/pythia/onchain-live-ack:/etc/pythia/onchain-live-ack:ro \
     -v /etc/pythia/onchain-keypair.json:/etc/pythia/onchain-keypair.json:ro \
     -v /etc/pythia/onchain-keypair.json.pub:/etc/pythia/onchain-keypair.json.pub:ro \
     pythia-lab python -m lab.onchain.live_exec check
   ```

   `simulate` tauscht testweise 10 USD SOL nach USDC (und USDC nach SOL, wenn USDC da ist) durch Guard und
   Simulation. Sie muss alle 24 Stunden neu laufen, sonst schließt das Tor (der Watcher warnt nach 20 h).
8. **Der Engine Schreibrecht für Umtausch und Notschalter geben:** im `docker run` der Engine
   `-v /srv/pythia-data/reports/onchain_live:/data/reports/onchain_live` ergänzen und sie neu erstellen.
9. **Starten**, von Hand, ohne automatischen Neustart (fällt er aus, meldet der Watcher es; du startest ihn
   neu, und jeder Start nimmt die Guthaben als neuen Ausgangspunkt):

   ```bash
   docker run -d --name pythia-onchain-live --cpus 0.5 --memory 512m \
     --env-file /etc/pythia/alerts.env --env-file /etc/pythia/onchain-live.env \
     --log-opt max-size=20m --log-opt max-file=3 \
     -v /srv/pythia-data:/data -v /opt/pythia-live:/app:ro \
     -v /etc/pythia/onchain-keypair.json:/etc/pythia/onchain-keypair.json:ro \
     -v /etc/pythia/onchain-keypair.json.pub:/etc/pythia/onchain-keypair.json.pub:ro \
     -v /etc/pythia/onchain-live-ack:/etc/pythia/onchain-live-ack:ro \
     pythia-lab python -m lab.onchain.live_service
   ```

   Das Log sagt `onchain live: ON (test)` oder nennt jeden Grund, warum nicht; die App zeigt dieselben Gründe.

**Umtausch in der App:** von, nach, Betrag, "Get quote". Der Dienst antwortet mit erwarteter Menge,
Mindestmenge, Kosten und Weg; 60 Sekunden lang kannst du bestätigen. Getauscht wird nur genau dieser
Vorschlag, nie unter seiner Mindestmenge.

**Stoppen:** Notschalter in der App (schreibt `reports/onchain_live/KILL`) oder
`touch /srv/pythia-data/live/onchain/KILL`. Dann kein Swap mehr; mit `on_kill=usdc` im Ack verkauft der Dienst
alle Coins außer SOL nach USDC. Danach `docker stop pythia-onchain-live`. Wieder erlauben: die KILL-Dateien
auf dem Server löschen und neu starten; die App kann das nicht.

**Abheben** bleibt außerhalb von Pythia (Abschnitt 3): stoppen, dann das Backup in deine eigene Wallet
importieren und von dort senden.

## 8. Die Wallet-Seite, der Alpha-Modus und die Messung

### Die Seite "Wallet" in der App

Ein eigener Eintrag "Wallet" in der Navigation (einfache und erweiterte Ansicht, direkt nach "Real money"). Oben
der Wert der Wallet in Euro und Dollar mit der Änderung über 24 Stunden und der Wertverlauf (ein Punkt alle 15
Minuten, `reports/onchain_live/values.json`, vom Dienst geschrieben), darunter der Zustand des Tors in Worten
(gesperrt, Alpha, Test) mit jedem Grund, die Coins mit Menge, Dollar, Euro und 24-h-Änderung, die Adresse mit
QR-Code und Kopierknopf ("Send SOL here"), der Umtausch (Vorschau mit erwarteter Menge, Mindestmenge, Price
Impact, Netzwerkgebühr höchstens, Kosten, Weg, 60 Sekunden zum Bestätigen), die Historie, die Wallet des
pump.fun-Bots (nur lesen: Adresse, SOL, Link auf ihre Seite) und der Notschalter. Die Seite "Real money" zeigt nur
noch Wert und Zustand mit einem Link hierher.

Es gibt keinen Knopf zum Senden: Pythia bewegt nie Geld aus einer Wallet. **Abheben:** Notschalter, dann das Backup
in Phantom (oder eine andere eigene Wallet) importieren und von dort senden.

**Direkt per URL** (für dein DevPanel, das die Web-Version im iframe zeigt): `?page=wallet` öffnet die Seite,
`?page=wallet&embed=1` zeigt nur sie über die ganze Breite, ohne Seitenleiste, Kopfzeile und Einführung, mit einem
kleinen Link "Open Pythia". Der rechtliche Hinweis kommt nur, bis er einmal bestätigt ist. Jede andere Seite geht
genauso (`?page=pumpfun`, `?page=realmoney`, ...).

**Historie:** der Job `onchain-history` (alle 5 Minuten, nur lesend) holt für die öffentliche Adresse
`getSignaturesForAddress` und `getTransaction` und schreibt `reports/onchain/history.json`: Einzahlungen,
Swaps mit Mengen und Preis, Gebühren (Basis, Priority, Sender-Trinkgeld, Kontomiete), gesendete Beträge und
fehlgeschlagene Transaktionen, jede mit Solscan-Link. Nach jedem eigenen Swap liest der Dienst sie sofort neu.
Der Job nimmt den öffentlichen Mainnet-RPC (nur lesend, wenige Anfragen alle 5 Minuten).

### Der Alpha-Modus

Wie der Testmodus des pump.fun-Bots: mit `mode=alpha` im Ack handeln die Bücher, die der Ack nennt, echtes Geld
**ohne** den Nachweis (`reports/onchain/proof.json`), damit du unsere eigenen Modelle mit kleinem echtem Geld
trainieren und messen kannst. Dafür gelten niedrigere Höchstwerte im Code; der Ack kann sie nur senken:

| Grenze | Alpha (im Code) | Test (im Code) |
|---|---|---|
| `max_total_usd` | 100 USD (`live_gate.ALPHA_MAX_TOTAL_USD`) | 500 USD |
| `max_trade_usd` | 25 USD (`live_gate.ALPHA_MAX_TRADE_USD`) | 100 USD |
| `max_daily_loss_usd` | 25 USD (`live_gate.ALPHA_MAX_DAILY_LOSS_USD`) | 100 USD |
| `max_convert_usd` | 100 USD am Tag | 250 USD am Tag |

Alles andere bleibt so streng wie im Testmodus: Guard, Simulation innerhalb von 24 Stunden, Notschalter,
Watcher, Liste der Coins, Sperrliste, Reserve, Kosten- und Preisprüfung, Ledger gegen Chain. Eine Order eines
Buchs über 25 USD wird in mehrere Swaps unter der Grenze geteilt. Jeder Alpha-Swap, der auf der Chain ankommt
(gefüllt oder fehlgeschlagen), schickt eine Karte an Telegram und Discord (derselbe Weg wie die Echtgeld-Karten
des pump.fun-Bots), mit "Alpha-Phase" im Titel und der Farbe nach Ausgang: grün gefüllt, orange gefüllt aber
teurer als 25 bps, rot fehlgeschlagen. Die App zeigt "Alpha" deutlich im Kopf der Wallet-Seite.

Beispiel, `/etc/pythia/onchain-live-ack`, Rechte 600, höchstens 90 Tage gültig:

```
mode=alpha
books=onchain_breakout_top10_live
mints=SOL,USDC,BTC,ETH
book_usd=80
max_total_usd=100
max_trade_usd=25
max_daily_loss_usd=25
max_convert_usd=50
expires=2026-12-31
on_kill=hold
I accept that I can lose all of it
```

Die übrigen Schritte sind die aus Abschnitt 7 (Wallet, IDL, Umgebung, Simulation, Start). Das Log sagt
`onchain live: ON (alpha)`. Zurück in den Testmodus: `mode=test` und Dienst neu starten.

### Die Messung jedes Swaps

Für jeden gesendeten Swap schreibt der Händler eine Zeile nach `live/onchain/execution.jsonl`: Signal bis Senden
(dein Bestätigen, die Signaldatei des Buchs oder der Notschalter), Senden bis Landen, die Gebühr (Basis, Priority,
Trinkgeld) und was wirklich herauskam gegen die Quote. Der Job `onchain-execution` (täglich) macht daraus
`reports/onchain/execution.md` und `.json`: der Vergleich mit der gemessenen Ausführung des pump.fun-Bots
(`reports/pumpfun_rt/execution.json`) und mit Krakens Gebühren (Taker 40 bps, die Proben des Paper-Buchs mit
halbem Spread). Landet unser Weg (Sender und RPC zugleich, Priority Fee mit Grenze im Code, dieselben Bytes alle
2 Sekunden bis der Blockhash abläuft) schneller als der des pump.fun-Bots, sagt der Bericht das, damit der
pump.fun-Executor dieselben Teile übernehmen kann (eine eigene Aufgabe; dieser Bericht ändert dort nichts).
