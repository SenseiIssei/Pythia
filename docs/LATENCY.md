# Latenz der Live-Bots: was kostenlos schneller wird und was Geld kostet

Stand 2026-10-23. Gemessen aus `live/pumpfun_rt/measured.jsonl` und `orders.jsonl` (65 Abschlüsse des
pump.fun-Bots, 33 Käufe und 32 Verkäufe, 2026-10-22 und 2026-10-23). Nachrechnen jederzeit mit

```bash
docker run --rm -v /opt/pythia-lab:/app -v /opt/pythia-data:/data pythia-lab \
  python -m lab.pumpfun_rt.measure split
```

(dieselbe Tabelle steht jetzt auch in `reports/pumpfun_rt/execution.md`, Abschnitt "Where the time goes").

## 1. Wo die Zeit hingeht

Begriffe: "Signal" ist die Zeit des Ereignisses, das entschieden hat (die Slot-Zeit unseres Datenstroms),
"Order" die Wanduhr bei `buy()` / `sell()`, "gesendet" die Antwort des Endpunkts, "gelandet" die Slot-Zeit
unseres Abschlusses im Strom (bei einem von der Chain zurückgelesenen Abschluss die Blockzeit), "gebucht" der
Moment, in dem der Bot den Abschluss kennt und mit ihm weiterrechnet. Alte Abschlüsse haben noch keine
getrennte Zeit für "gebaut"; ihr "Order bis gesendet" endet an der Zeile im Order-Log, die erst beim nächsten
Sekundentakt geschrieben wurde (also bis zu 1 s zu spät). Ab jetzt schreibt der Executor jeden Schritt
einzeln (`queued_ms`, `built_ms`, `sent_at_ms`, `confirmed_ms`, `seen_ms`).

| Schritt (Sekunden) | Kauf n | p25 | Median | p75 | p90 | Verkauf n | p25 | Median | p75 | p90 |
|---|---|---|---|---|---|---|---|---|---|---|
| Signal bis Order | 33 | 0,29 | 3,07 | 7,22 | 18,96 | 32 | 0,00 | 0,34 | 3,49 | 17,20 |
| Order bis gesendet (Log-Zeile) | 33 | 0,57 | 0,84 | 1,16 | 1,27 | 32 | 0,45 | 0,74 | 0,96 | 1,03 |
| gesendet bis gelandet | 33 | -0,81 | 1,70 | 6,33 | 14,02 | 32 | -0,98 | 0,14 | 5,40 | 11,24 |
| gelandet bis gebucht | 33 | 0,57 | 12,49 | 37,56 | 38,04 | 32 | 0,17 | 16,48 | 37,52 | 37,80 |
| davon: Abschluss aus dem Strom | 20 | 0,14 | 0,98 | 7,72 | 13,17 | 17 | 0,00 | 0,23 | 1,14 | 7,61 |
| davon: von der Chain zurückgelesen | 13 | 37,51 | 37,60 | 38,07 | 38,24 | 15 | 37,34 | 37,57 | 37,78 | 38,18 |
| Signal bis gebucht | 33 | 15,80 | 28,62 | 38,74 | 55,38 | 32 | 8,21 | 32,23 | 40,42 | 54,83 |

Negative Werte bei "gesendet bis gelandet": der Strom stempelt einen Slot mit dem ersten Empfang dieses Slots,
der vor unserer Order liegen kann; auf etwa eine Sekunde genau.

**Der größte Posten war bisher nicht sichtbar: 28 von 65 Abschlüssen (13 Käufe, 15 Verkäufe) hat der Strom
nie gezeigt.** Der Bot hat sie erst über den Signatur-Status erfahren, und den fragte er erst 30 s nach dem
Senden, dann wartete er noch 5 s auf den Strom, bevor er die Transaktion zurücklas: im Median 37,6 s nach der
Landung. Bei einem Kauf heißt das: 37 s lang war die Position offen, aber für den Bot noch "unterwegs", kein
Stop konnte feuern. Die Stops dieser Positionen landeten im Mittel bei -43 % (7 Stops, Haltedauer 37 bis 54 s),
die Stops der Positionen, deren Kauf der Strom zeigte, bei etwa -32 % (6 Stops, ohne einen Ausreißer von
+158 %). Wenige Fälle, aber dieselbe Richtung wie Y8 (Stops bei -20 % landen bei -43 %).

Die übrigen Posten:

- **Signal bis Order** (Median 0,3 bis 3 s, p90 17 bis 19 s): der Rückstand des öffentlichen Websockets hinter
  dem ersten Ereignis desselben Slots. Unser Code braucht hier Mikrosekunden; das Ereignis kommt einfach spät.
  Kostenlos ist das nicht zu beheben, ein bezahlter Strom (Abschnitt 3) zielt genau darauf.
- **Order bis gesendet** (Median 0,7 bis 0,8 s): darin bis zu 1 s Warten auf den Sekundentakt des Dienstes
  (nur die Log-Zeile, das Senden selbst lief sofort), dazu Bauen, Signieren und eine neue TLS-Verbindung je
  Sendung (100 bis 300 ms).
- **gesendet bis gelandet** (Median 0,1 bis 1,7 s): seit Helius Sender klein.
- **Dazu**, in keiner dieser Zahlen: der Rückstand des Stroms hinter der Chain, im Median 8 s
  (`reports/pumpfun_rt/latency.md`).

## 2. Was kostenlos eingebaut ist (alles aus, bis du es einschaltest)

Ein Schalter für alles: `PYTHIA_PUMPFUN_FAST=1` in `/etc/pythia/pumpfun-live.env`, dann den Container neu
anlegen (Abschnitt 8 in PUMPFUN-LIVE.md). Jede Einzelne lässt sich mit `=0` wieder ausschalten. Keine ändert,
was der Bot entscheidet, und jede Transaktion geht weiterhin durch `check_own`, die Caps, das Tor und die
Notschalter.

| Einstellung | Schalter | was sie tut | erwartete Wirkung |
|---|---|---|---|
| Signatur per Websocket | `PYTHIA_PUMPFUN_WS_CONFIRM` (Adresse `PYTHIA_PUMPFUN_RPC_WS`, sonst der RPC als `wss://`) | `signatureSubscribe` (confirmed) für jede Order, abonniert bevor sie gesendet wird; die Landung wird sofort gemeldet, die Transaktion sofort zurückgelesen und gebucht (der späte Strom-Abschluss wird an der Signatur erkannt und nicht doppelt gebucht). In den ersten 5 s wird nur die Transaktion selbst gebucht, deren Zahlen exakt sind | die 28 von 65 Fällen mit 37,6 s: etwa 0,5 bis 2 s |
| schnellere Status-Abfrage | `PYTHIA_PUMPFUN_STATUS_MS` (mit FAST 2.000 ms, nie über 30.000, nie unter 500) | der Rückfall, falls der Websocket fehlt: Status nach 2 s und alle 2 s statt nach 30 s | dieselben Fälle, falls der Websocket ausfällt: etwa 2 bis 3 s |
| sofort reagieren | `PYTHIA_PUMPFUN_WAKE` | jedes Ergebnis der Hintergrund-Threads (Antwort beim Senden, Bestätigung, Rücklesen) weckt den Dienst sofort statt beim nächsten Sekundentakt; eine wartende Wiederholung eines Verkaufs geht genau zu ihrer Zeit | bis 1 s je Schritt |
| Lesen hinter Senden | `PYTHIA_PUMPFUN_SEND_FIRST` | Status, Gebühren und Bestände laufen auf einem eigenen Thread; ein Stop-Verkauf wartet nie hinter einer RPC-Abfrage (bisher nach jedem Abschluss eine Gebührenabfrage, bis 8 s Zeitlimit) | im Mittel klein, im schlechten Fall Sekunden |
| vorgebaute Verkäufe | `PYTHIA_PUMPFUN_PREPARE_SELLS` | für jede offene Position liegt der Verkauf von allem (ohne Mindestmenge, Konto schließen) fertig gebaut und kompiliert bereit, mit dem aktuellen Blockhash erneuert; benutzt nur, wenn die Order genau diese ist, und vor dem Signieren noch einmal durch `check_own` | spart Kontolesen und Bauen beim Stop |
| Blockhash vorab | `PYTHIA_PUMPFUN_PREFETCH` | Blockhash alle 10 s im Hintergrund, nie mehr beim Senden | spart eine RPC-Abfrage alle 20 s |
| Gebühr aus jüngsten Gebühren | `PYTHIA_PUMPFUN_DYNAMIC_FEE`, Obergrenze `PYTHIA_PUMPFUN_FEE_CAP_SOL` | Priority Fee aus `getRecentPrioritizationFees` der Pools der offenen Positionen und der Gebührenkonten (75. Perzentil, Untergrenze), gedeckelt; Standard-Deckel ist die heutige feste Gebühr 0,001 SOL, also nie teurer als heute; höher nur, wenn du den Deckel anhebst, und nie über 0,01 SOL | in ruhigen Minuten billiger |
| parallel senden | `PYTHIA_PUMPFUN_PARALLEL_SEND` | dieselben signierten Bytes gleichzeitig an Sender (ohne Preflight) und den normalen RPC (mit Preflight); eine Signatur, also landet sie höchstens einmal | kein Warten auf den Rückfall |
| Verbindungen halten | `PYTHIA_PUMPFUN_KEEPALIVE` | HTTPS-Verbindungen werden wiederverwendet, Sender bekommt alle 5 s ein `/ping` (laut Sender-Doku) | 100 bis 300 ms je Sendung |

Bei Stops: Der Stop entscheidet schon bisher beim ersten Kurs-Tick durch die Schwelle (der Handel im Strom
ruft die Prüfung direkt auf) und legt den Verkauf sofort in die Warteschlange. Neu ist, dass dieser Verkauf
dort nicht mehr hinter Lese-Abfragen wartet, fertig gebaut ist und dass der Dienst sein Ergebnis sofort
verarbeitet. Was der Tick selbst zu spät kommt (Signal bis Order), bleibt eine Frage des Datenstroms.

Nicht eingebaut, weil es die Entscheidung ändern würde: Kurse aus den Tresor-Konten des Pools
(`accountSubscribe`) statt aus den Handelsereignissen. Das wäre eine andere Preisquelle für die Stops und
gehört erst in eine Studie mit Replay.

Für den On-Chain-Trader (Stufe 2) gibt es noch keinen Echtgeld-Teil. Vorbereitet: `lab/onchain/fees.py`
(Priority Fee aus jüngsten Gebühren, 50. Perzentil, höchstens 0,0005 SOL je Transaktion, wie im Entwurf) und
gehaltene Verbindungen für die Jupiter-Quotes (`PYTHIA_ONCHAIN_KEEPALIVE=1`). Bestätigung per Websocket,
paralleles Senden und Blockhash vorab übernimmt der Stufe-2-Executor von hier, wenn er gebaut wird.

**Prüfung, dass sich die Entscheidungen nicht ändern:** Ein Replay fährt den Live-Executor über einen
aufgezeichneten Tag, einmal mit allen Einstellungen aus und einmal mit allen an; jede Order wird in beiden
Läufen zur selben Stromzeit mit demselben Preis gefüllt. Ergebnis für P_pool0: 2026-10-21 173 Einstiege und 173
Ausstiege, 2026-10-22 188 Einstiege und 188 Ausstiege, in beiden Läufen identisch (Kauf, Verkauf, Grund, Menge, Zeit, P&L); der
schnelle Lauf benutzte dabei vorgebaute Verkäufe (111 am 21.10., 133 am 22.10.). Dazu derselbe Vergleich als Test auf einem
synthetischen Tag (`tests/test_pumpfun_latency.py`; der aufgezeichnete Tag mit
`PYTHIA_REPLAY_DAY=2026-10-21`).

## 3. Was Geld kostet (nichts gekauft, nichts eingerichtet)

Preise aus den öffentlichen Preislisten, gelesen am 2026-10-23:

| Option | Preis im Monat | was es an unseren Zahlen ändert |
|---|---|---|
| Helius Developer | 49 USD (50 Anfragen/s, gestakte Verbindungen, erweiterte Websockets mit `transactionSubscribe`; LaserStream nur Devnet) | eigener RPC und Websocket mit Schlüssel: Signal bis Order und der Rückstand hinter der Chain sollten von 3 s Median / 17 bis 19 s p90 und 8 s auf etwa 0,5 bis 2 s fallen (Richtwert aus PUMPFUN-LIVE.md, nicht gemessen); gestakte Verbindungen helfen beim Senden kaum noch, das macht Sender schon |
| Chainstack Growth plus Yellowstone gRPC | 49 USD plus 49 USD (2 Ströme, genug für pump und PumpSwap) | gRPC etwa 1 bis 2 Slots hinter dem Block; der Collector kann gRPC schon (`PYTHIA_SOLANA_GRPC_URL`, braucht `grpcio` im Image) |
| QuickNode Scale (gRPC inklusive) | 499 USD (Build 49 USD plus gRPC 499 USD) | wie oben |
| Helius Business (LaserStream auf Mainnet) | 499 USD (Professional 999 USD) | wie oben, für uns kaum mehr als Developer |
| Triton (Erfinder von Yellowstone) | nutzungsabhängig 0,08 USD je GB plus 10 USD je Million Abfragen, mindestens 125 USD Vorauszahlung; eigener Knoten laut Vergleichsseiten 2.900 bis 3.800 USD | gRPC; Bandbreite der pump.fun-Ströme schwer vorab zu schätzen |
| Shred-Daten (Helius, Triton) | 800 bis 1.500 USD je IP | nur für den Erstellungs-Slot; laut `results/pumpfun_speed.md` lohnt das Sniping nicht |
| eigener dedizierter Knoten | ab 2.900 USD | wie gRPC, plus Platz für eigene Logik |

**Was das für P_pool0 wert ist:** Y8 (`results/pumpfun_exits_y8.md`): P_pool0s Ausstiege (X0) außerhalb der
Stichprobe -0,8 % je Einstieg bei der gemessenen Latenz (b), -0,3 % bei einem 1,5-s-Pfad (c), also etwa +0,5
Punkte; die Stops landen bei (b) bei -43 % statt -20 %. Y5 (`results/pumpfun_real_latency.md`): der Vorläufer
`E_d0_x1` -4,6 % bei (b), -1,7 % bei (c), etwa +3 Punkte. Beide bleiben außerhalb der Stichprobe nicht
positiv. Bei 0,05 bis 0,1 SOL Einsatz, 20 bis 60 Einstiegen am Tag und SOL bei etwa 104 USD sind 0,5 bis 3
Punkte etwa 15 bis 560 USD im Monat weniger Verlust, eher am unteren Ende (Y8 ist die neuere, passendere
Messung). Das deckt 49 bis 98 USD, nicht 499 USD und mehr.

Wichtig: Ein großer Teil von (c) gegen (b) war gar nicht der Strom, sondern die 37,6 s der zurückgelesenen
Abschlüsse. Die behebt der kostenlose Websocket aus Abschnitt 2. Was danach übrig bleibt, zeigt erst die
neue Messung.

## 4. Empfehlung

1. **Jetzt, kostenlos:** `PYTHIA_PUMPFUN_FAST=1` setzen, Container neu anlegen, eine Woche laufen lassen,
   dann `measure split` ansehen. Erwartung: "gelandet bis gebucht" für alle Abschlüsse unter 2 s, "Order bis
   gebaut" unter 10 ms, die Stops näher an ihrer Schwelle.
2. **Danach, falls "Signal bis Order" im p75 über 2 s bleibt:** einen Monat Helius Developer (49 USD) für den
   Datenstrom des Live-Dienstes (`PYTHIA_SOLANA_WS` mit Schlüssel) und als `PYTHIA_PUMPFUN_RPC`, vorher und
   nachher `latency probe` und `measure split`. Gleichwertige Alternative mit gRPC: Chainstack Growth plus
   Yellowstone (98 USD).
3. **Nicht kaufen:** LaserStream oder QuickNode Scale (499 USD), Shreds, einen eigenen Knoten. Das lohnt erst,
   wenn eine Pool-Regel nach Kosten positiv ist; heute ist es keine.

## Quellen

- Helius Preise: https://www.helius.dev/pricing (Free 0, Developer 49, Business 499, Professional 999 USD;
  Shreds 1.000 USD je IP, 800 mit Professional; dedizierte Knoten ab 2.900 USD)
- Helius Sender (`/ping`, paralleles Senden erlaubt): https://www.helius.dev/docs/sending-transactions/sender
- Chainstack, Yellowstone-Anbieter 2026: https://chainstack.com/learn/compare/best-yellowstone-grpc-providers-solana-2026/
- QuickNode Yellowstone gRPC: https://www.quicknode.com/solana-yellowstone-grpc
- Triton, Streaming und Preise: https://blog.triton.one/complete-guide-to-solana-streaming-and-yellowstone-grpc/
- Eigene Messung: `lab/pumpfun_rt/measure.py` (`split`), Studien Y5 und Y8 in `research/lab/results/`
