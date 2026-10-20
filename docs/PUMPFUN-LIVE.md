# pump.fun mit echtem Geld: Runbook für den Besitzer

Dieses Runbook ist für dich, Jakob, als Besitzer des Geldes. Es führt durch
den Echtgeld-TEST des pump.fun-Bots: eine eigene Wallet, ein kleines Budget,
harte Grenzen, ein Notschalter, und vor allem Messwerte (Latenz, Schlupf,
Gebühren), die eine Papierstudie nicht liefern kann.

Nichts davon passiert von selbst. Jeder Schritt unten ist ein Befehl, den du
selbst auf dem Server ausführst. Kein Job, kein Autostart, keine KI startet
den Echtgeld-Dienst.

## Ehrlich vorweg

- **Die Papierergebnisse sind bisher negativ.** Die meisten Strategien
  verlieren nach Kosten; nur die Pool-Regeln nach der Migration waren in
  wenigen Trades positiv (results/pumpfun_realtime.md). Rechne damit, dass
  das Testbudget ganz weg ist. Setz nur ein, was du verlieren kannst.
- **pump.fun verbietet Bots auf seiner Website und seiner API** (Nutzungsbedingungen,
  Abschnitte 6.1 und 21(h), Stand 08.10.2026). Pythia nutzt beides nicht: Es
  liest die öffentliche Blockchain und schickt einfache Kauf- und
  Verkaufstransaktionen der öffentlichen Programme an einen öffentlichen
  RPC-Endpunkt. Keine Bundles, keine privaten Relays, kein Front-Running,
  keine Umgehung irgendeiner Erkennung. Tips gibt es nur, wenn du selbst
  `PYTHIA_PUMPFUN_JITO=1` setzt, und dann nur als Trinkgeld in deiner eigenen
  einzelnen Kauf- oder Verkaufstransaktion (Abschnitt 10). Du entscheidest mit
  diesem Wissen.
- **Steuern sind deine Sache.** Jeder Kauf und Verkauf eines Tokens ist ein
  steuerlich relevanter Vorgang. Die Abschlüsse stehen in
  `/srv/pythia-data/live/pumpfun_rt/ledger.csv` und `orders.jsonl` (mit den
  Signaturen), die Wallet-Historie ist öffentlich auf der Blockchain.
- **Pythia bewegt nie Geld aus der Wallet heraus.** Es gibt keine
  Auszahl- oder Überweisungsfunktion, nirgends. Der Bot kauft und verkauft nur
  pump.fun-Token mit dem SOL der Wallet; `txbuild.check_own` lehnt vor dem
  Signieren alles andere ab. Auszahlen machst du selbst, mit deiner
  Sicherung in deiner eigenen Wallet (Schritt 9).

## Was die Grenzen sind

Im Testmodus gelten diese Höchstwerte fest im Code, egal was in einer Datei
steht (eine Bestätigungsdatei darüber wird abgelehnt):

| Grenze | Höchstwert im Code | was sie tut |
|---|---|---|
| `max_total_sol` | 2,0 SOL | Gesamtbudget: Sind seit dem ersten Echtgeld-Abschluss so viel SOL verloren, kauft der Bot nichts mehr. Offene Positionen und ein neuer Kauf zählen schon vorher mit. |
| `max_daily_loss_sol` | 0,5 SOL | Tagesverluststopp: keine Käufe mehr bis zum nächsten UTC-Tag. |
| `max_trade_sol` | 0,05 SOL | höchstens so viel pro Kauf (plus 30 % Schlupftoleranz als Preisgrenze). |
| offene Positionen | 5 | gleichzeitig offen. |
| Reserve | 0,01 SOL | bleibt immer für Gebühren, damit offene Positionen verkauft werden können. |

In der App (Seite "pump.fun wallet") kannst du jede Grenze nur **senken**.
Anheben geht nur über eine neue Bestätigungsdatei auf dem Server, und auch
dann nie über die Werte oben.

## 1. Wallet erzeugen

Einmalig nach dem Deploy das Lab-Image neu bauen (es braucht jetzt `solders`):

```bash
research/ops/deploy_lab.sh            # vom Rechner aus, wie immer
ssh root@<server>
docker build -t pythia-lab /opt/pythia-lab
```

Der Ordner für die Wallet darf nicht für alle lesbar sein:

```bash
ls -ld /etc/pythia
chmod 700 /etc/pythia                 # nur root; Docker und die Cron-Jobs laufen als root
```

Dann die Wallet erzeugen, **interaktiv** (`-it`) und mit `--rm`, damit keine
Container-Logs mit der Ausgabe liegen bleiben:

```bash
docker run --rm -it \
  -v /etc/pythia:/etc/pythia -v /srv/pythia-data:/data -v /opt/pythia-lab:/app \
  pythia-lab python -m lab.pumpfun_rt.wallet new --out /etc/pythia/pumpfun-keypair.json
```

Das Werkzeug

- legt `/etc/pythia/pumpfun-keypair.json` mit Rechten 600 an (es
  überschreibt nie eine vorhandene Datei und verweigert einen Ordner, den alle
  lesen oder schreiben können),
- schreibt die **öffentliche** Adresse nach
  `/etc/pythia/pumpfun-keypair.json.pub` und nach
  `/srv/pythia-data/reports/pumpfun_rt/wallet.json` (für die App),
- zeigt die Adresse,
- und zeigt das **Backup-Secret genau einmal**, nachdem du `YES` tippst.

Die Adresse später noch einmal (liest nur die .pub-Datei, nie den Schlüssel):

```bash
docker run --rm -v /etc/pythia:/etc/pythia:ro -v /opt/pythia-lab:/app \
  pythia-lab python -m lab.pumpfun_rt.wallet address
```

## 2. Sicherung

Das Backup-Secret ist der Schlüssel zu allem Geld in dieser Wallet.

- Schreib es auf Papier oder in einen Passwortmanager, der lokal bleibt.
- Nie in einen Chat, eine Mail, ein Ticket, einen Screenshot, ein Repo.
- Danach `clear` im Terminal.
- Pythia zeigt es nie wieder; nichts in Pythia liest, loggt oder sendet es.

Hast du es nicht gesichert: **vor dem Aufladen** beide Dateien löschen
(`rm /etc/pythia/pumpfun-keypair.json /etc/pythia/pumpfun-keypair.json.pub`)
und Schritt 1 wiederholen.

## 3. Aufladen

Schick SOL von deiner eigenen Wallet oder Börse an die Adresse. In der App
steht sie mit QR-Code auf der Seite "pump.fun wallet" (der Code wird im
Browser erzeugt, kein fremder Dienst sieht die Adresse). Schick nicht mehr
als dein `max_total_sol` plus etwa 0,05 SOL für Gebühren und Kontomieten.

## 4. Programm-IDLs

Wie bisher: die IDLs aus github.com/pump-fun/pump-public-docs
(`idl/pump.json`, `idl/pump_amm.json`) nach
`/srv/pythia-data/pumpfun_rt/idl/`. Der Executor vergleicht sie mit dem, was er
baut, und verweigert bei jeder Abweichung.

## 5. Bestätigungsdatei schreiben

Genau diese Vorlage, die Zahlen nach deinem Willen (höchstens die Werte oben):

```bash
cat > /etc/pythia/pumpfun-live-ack <<'EOF'
mode=test
strategy=auto
max_total_sol=1.0
max_daily_loss_sol=0.25
max_trade_sol=0.02
I accept that I can lose all of it
EOF
chmod 600 /etc/pythia/pumpfun-live-ack
```

`strategy=auto` nimmt die am wenigsten schlechte vorab registrierte
Pool-Regel nach der Migration aus dem letzten Studienbericht (heute
`P_pool60`: PumpSwap 60 s nach der Migration). Du kannst stattdessen eine
Strategie fest nennen, zum Beispiel `strategy=P_pool60`. Die letzte Zeile muss
wörtlich so dastehen.

## 6. Umgebung für den Dienst

```bash
cat > /etc/pythia/pumpfun-live.env <<'EOF'
PYTHIA_PUMPFUN_LIVE=1
PYTHIA_PUMPFUN_KEYPAIR=/etc/pythia/pumpfun-keypair.json
# optional, nur https, kein Bundle- oder Relay-Dienst:
# PYTHIA_PUMPFUN_RPC=https://...
# optional, weitere https-RPCs für paralleles Senden (Abschnitt 10):
# PYTHIA_PUMPFUN_RPC_URLS=https://...,https://...
# optional, nur wenn du Jito willst (Abschnitt 10), beide Zeilen:
# PYTHIA_PUMPFUN_JITO=1
# PYTHIA_PUMPFUN_JITO_URL=https://<block-engine>/api/v1/transactions
EOF
chmod 600 /etc/pythia/pumpfun-live.env
```

Der Ausführer selbst sendet weiterhin nur an `PYTHIA_PUMPFUN_RPC`. Die
parallelen Endpunkte und Jito gehören zum schnellen Pfad (Abschnitt 10), der
bisher nur als Trockenlauf existiert; die Prüfung (`live_exec check`) kontrolliert
die Adressen trotzdem schon: eine Jito-Adresse ohne `PYTHIA_PUMPFUN_JITO=1`,
eine Bundle-Adresse oder eine http-Adresse lässt das Tor zu.

## 7. Simulieren (Pflicht, gilt 24 Stunden)

Die Wallet muss dafür schon aufgeladen sein (die Simulation rechnet mit dem
echten Guthaben als Gebührenzahler):

```bash
docker run --rm --env-file /etc/pythia/pumpfun-live.env \
  -v /etc/pythia:/etc/pythia:ro -v /srv/pythia-data:/data -v /opt/pythia-lab:/app \
  pythia-lab python -m lab.pumpfun_rt.live_exec simulate
```

Das baut einen Kauf und einen Kauf mit anschließendem Verkauf gegen den
neuesten Pool, den der Collector gesehen hat, und lässt beides per
`simulateTransaction` auf Mainnet durchrechnen. Es wird **nichts signiert und
nichts gesendet**. Das Ergebnis steht in
`/srv/pythia-data/live/pumpfun_rt/simulate.json`; der Testmodus öffnet nur mit
einer erfolgreichen Simulation dieser Wallet aus den letzten 24 Stunden.

Das gilt auch im laufenden Betrieb: Der Dienst prüft alle Bedingungen jede
Minute, und ist die letzte Simulation älter als 24 Stunden, kauft er nichts
mehr (offene Positionen werden weiter verwaltet und verkauft). Telegram
meldet das ("pausiert: keine Käufe mehr", mit Grund). Dann einfach den
Befehl oben wieder ausführen; innerhalb einer Minute kauft der Bot wieder,
ohne Neustart. So prüfst du einmal am Tag, dass die Transaktionen gegen die
aktuellen Programme noch sauber durchlaufen.

Alle Bedingungen auf einmal prüfen:

```bash
docker run --rm --env-file /etc/pythia/pumpfun-live.env \
  -v /etc/pythia:/etc/pythia:ro -v /srv/pythia-data:/data -v /opt/pythia-lab:/app \
  pythia-lab python -m lab.pumpfun_rt.live_exec check
```

## 8. Starten, beobachten, stoppen

Die App braucht Schreibzugriff auf einen Ordner, damit Grenzen und Notschalter
ankommen. Beim Engine-Container, der die App bedient, einmalig
`-v /srv/pythia-data/reports/pumpfun_rt:/data/reports/pumpfun_rt` ergänzen und
ihn neu anlegen (research/ops/README.md, "Live trading").

Starten (ein langlaufender Container wie der Collector, aber **ohne**
Autostart: nach einem Neustart des Servers läuft er nicht von selbst wieder):

```bash
docker run -d --name pythia-pumpfun-live --restart no --cpus 1 --memory 1g \
  --env-file /etc/pythia/alerts.env --env-file /etc/pythia/pumpfun-live.env \
  --log-opt max-size=20m --log-opt max-file=3 \
  -v /srv/pythia-data:/data -v /opt/pythia-lab:/app -v /etc/pythia:/etc/pythia:ro \
  pythia-lab python -m lab.pumpfun_rt.live_service
docker logs --tail 30 pythia-pumpfun-live
```

Das Log sagt `live: ON (test) for P_pool60 ...` oder listet jeden Grund,
warum nichts gehandelt wird. Der Dienst läuft auch dann weiter und zeigt die
Gründe in der App; nach dem Beheben `docker restart pythia-pumpfun-live`.

Beobachten:

- App, Seite **pump.fun wallet**: Adresse, Guthaben, heute und gesamt,
  Grenzen, offene Positionen, Abschlüsse, gemessene Ausführung.
- Telegram (Kategorie Trades, auch in den Ruhezeiten): jeder Kauf, Verkauf,
  jede geschlossene Position und jeder Fehlschlag sofort, mit `TEST` im
  Titel und der gemessenen Landezeit; eine Meldung, wenn der
  Tagesverluststopp oder der Gesamtbudget-Stopp greift; jeden Tag (UTC) eine
  Tageskarte mit Guthaben, Ergebnis, Abschlüssen und gemessener gegen
  angenommene Latenz.
- Dateien: `/srv/pythia-data/live/pumpfun_rt/` (`orders.jsonl`,
  `ledger.csv`, `measured.jsonl`, `totals.json`) und
  `/srv/pythia-data/reports/pumpfun_rt/execution.md` (gemessen gegen das
  Papiermodell; die tägliche Studie übernimmt die Zusammenfassung).

In der ersten Stunde nach dem Start kommen wenige Signale: Der Dienst kennt
nur Token, deren Erstellung er selbst gesehen hat.

**Stoppen:**

1. Notschalter: in der App "Stop trading now" (schreibt
   `/srv/pythia-data/reports/pumpfun_rt/KILL`), oder auf dem Server
   `touch /etc/pythia/pumpfun-kill`. Der Bot kauft nichts mehr und verkauft
   sofort alles Offene.
2. Warten, bis in der App keine Position mehr offen ist.
3. `docker stop pythia-pumpfun-live`.

Positionen, die bei einem Stopp oder Neustart noch offen waren, verkauft der
Dienst beim nächsten Start als Erstes (Telegram meldet es); was er nicht
verkaufen kann, meldet er, dann verkaufst du es selbst in deiner Wallet.

**Notschalter wieder lösen:** Das geht absichtlich nicht über die App. Auf
dem Server die Datei löschen:

```bash
rm /srv/pythia-data/reports/pumpfun_rt/KILL      # aus der App
rm /etc/pythia/pumpfun-kill                      # falls du ihn so gesetzt hast
```

Der Dienst merkt es innerhalb einer Minute.

## 9. Auszahlen

1. Bot stoppen (Schritt 8).
2. In Phantom (oder einer anderen Solana-Wallet): Wallet hinzufügen,
   "Import private key", das Backup-Secret aus Schritt 2 einfügen.
3. SOL an deine eigene Adresse oder Börse senden. Übrig gebliebene Token
   kannst du dort ebenfalls verkaufen oder verschieben.

Danach kannst du die Wallet auf dem Server stilllegen: Dienst gestoppt
lassen, `PYTHIA_PUMPFUN_LIVE` aus `/etc/pythia/pumpfun-live.env` entfernen.

## 10. Geschwindigkeit: schneller Datenstrom, schneller Pfad, Jito (deine Entscheidung)

Du wolltest "immer direkt beim Release drin" sein. Was gemessen ist
(results/pumpfun_speed.md):

- **Heute sind wir spät.** Der öffentliche Datenstrom liefert uns eine neue
  Token-Erstellung im Median 15 s nach ihrem Block (90. Perzentil 44 s), nur
  3,7 % innerhalb einer Sekunde. Der Engpass ist der öffentliche Endpunkt,
  nicht unser Code: Unser schneller Pfad braucht vom Empfang bis zur fertig
  signierten Transaktion etwa 0,3 ms.
- **Schneller allein bringt nichts.** In der Simulation verliert der Snipe von
  "ein Slot nach der Erstellung" (216 ms) bis "15 s danach" gleich viel: 3 bis
  5 % pro Trade nach Kosten. Wer im Erstellungs-Slot hinter den anderen
  Snipern landet, verliert ebenfalls (2 bis 4 %, und jeder fünfte Kauf
  scheitert am Preis).
- **Bezahlt wird nur ganz vorne im Erstellungs-Slot.** Direkt nach der
  Erstellung stehen aber meist Bundles, die die Transaktion des Erstellers
  selbst enthalten. Davor kommt man mit einer eigenen Transaktion nicht, und
  Pythia bündelt keine fremden Transaktionen (keine Bundles mit fremden
  Transaktionen, kein Sandwich, kein Front-Running). Direkt hinter diesem
  Block ist der Vorteil dünn: Er deckt ein Trinkgeld von höchstens etwa
  0,007 SOL pro Runde, die Konkurrenz bietet im Median schon 0,003 SOL und in
  einem Viertel der Fälle über 0,028 SOL.

**Empfehlung:** Für das Sniping lohnt sich ein bezahlter Anbieter nach diesen
Zahlen nicht. Er kann sich für die Qualität der Aufzeichnung lohnen (weniger
Lücken, weniger fehlende Trades), das ist aber eine andere Frage. Die
Entscheidung ist deine; nichts davon ist eingeschaltet.

### Was ein Anbieter ungefähr kostet und was er ändert

Richtwerte aus den öffentlichen Preislisten, nicht für heute geprüft; vor
einem Kauf auf der Seite des Anbieters nachsehen:

| Stufe | Beispiele | ungefähr pro Monat | was es ändert |
|---|---|---|---|
| bezahlter Websocket-RPC | Helius, QuickNode, Chainstack, Alchemy | 50 bis 250 $ | statt 15 s etwa 0,5 bis 2 s Verzögerung (mit `processed`), stabilere Verbindung, vollständigere Aufzeichnung. Laut Simulation: weiterhin minus 3 bis 5 % pro Snipe |
| Yellowstone gRPC (Geyser), geteilt | Triton, Helius LaserStream, QuickNode, Shyft, Chainstack | 150 bis 1.000 $ | etwa 1 bis 2 Slots hinter dem Block. Gleiche Aussage für Snipes |
| Shred-Daten plus Sender nahe den Leadern | Jito ShredStream (Freischaltung nötig) auf eigenem Server, Anbieter mit Shred-Feed, eigener Knoten | 300 bis 3.000 $ und mehr | erst damit ist der Erstellungs-Slot erreichbar; dazu kommen Trinkgelder pro Trade |

Dazu kämen bei Jito die Trinkgelder pro Kauf und Verkauf (Konkurrenz: Median
0,003 SOL, oberes Viertel ab 0,028 SOL).

### Einrichten, falls du es trotzdem willst

Datenstrom (der Collector, nur lesen; in eine Env-Datei wie
`/etc/pythia/pumpfun-feed.env` mit Rechten 600 und beim Container
`--env-file` ergänzen, research/ops/README.md):

```bash
PYTHIA_SOLANA_WS_URLS=wss://<anbieter>/?api-key={token}
PYTHIA_SOLANA_TOKEN=<dein Schlüssel>
PYTHIA_SOLANA_COMMITMENT=processed
# oder zusätzlich gRPC (braucht das Paket grpcio im Image):
# PYTHIA_SOLANA_GRPC_URL=https://<anbieter>:<port>
# PYTHIA_SOLANA_GRPC_TOKEN=<dein Schlüssel>
```

Der Schlüssel steht nur in dieser Datei, nie im Repo; Logs zeigen nur
Schema und Host. Der öffentliche Endpunkt läuft als Rückfallebene weiter
(`PYTHIA_PF_PUBLIC_FALLBACK=0` schaltet ihn ab). Ob es wirkt, zeigt die
tägliche Telegram-Karte ("Unser Datenstrom sah neue Token ... nach ihrem
Block") und der Vergleich der Anbieter:

```bash
docker run --rm --env-file /etc/pythia/pumpfun-feed.env -v /opt/pythia-lab:/app \
  pythia-lab python -m lab.pumpfun_rt.latency probe --seconds 120
```

Schneller Pfad und Jito (nur Trockenlauf, es wird nichts gesendet):

```bash
docker run --rm -v /opt/pythia-lab:/app pythia-lab python -m lab.pumpfun_rt.fastpath bench
docker run --rm -v /opt/pythia-lab:/app pythia-lab python -m lab.pumpfun_rt.fastpath dryrun --seconds 60
```

Jito ist nur mit `PYTHIA_PUMPFUN_JITO=1` und `PYTHIA_PUMPFUN_JITO_URL`
(Abschnitt 6) zugelassen, nur für deine eigene einzelne Transaktion mit
einem Trinkgeld von höchstens 0,01 SOL an eines der veröffentlichten
Jito-Trinkgeldkonten, nie der Bundle-Endpunkt. Den schnellen Pfad in den
Echtgeld-Ausführer einzubauen ist ein eigener Schritt, den nur du anstößt.

## Was gesperrt bleibt

- Ohne `PYTHIA_PUMPFUN_LIVE=1`, Wallet-Datei mit .pub-Adresse, gültige
  Bestätigungsdatei, frische Simulation, passende IDLs, https-RPC ohne
  Bundle/Relay (Jito nur mit `PYTHIA_PUMPFUN_JITO=1`) und ohne Notschalter
  handelt nichts.
- Der volle Echtgeld-Modus (`mode=full`, größere Grenzen) öffnet weiterhin
  nur, wenn der tägliche Bericht die Strategie als bereit meldet (14 Tage, 300
  Trades außerhalb der Stichprobe, alle Schwellen, 30 Tage Schattenbuch).
- Der Collector handelt nie; nur `live_service` kann es.
- Keine Funktion in Pythia überweist oder zahlt aus, und nur das
  Wallet-Werkzeug erzeugt einen Schlüssel.
