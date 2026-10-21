# M4 auf Perps im Demo-Konto (Kraken Futures, Bybit)

Das stärkste Ergebnis des Labors ist M4: ein marktneutrales Long/Short-Buch auf
Perpetual Futures (`research/lab/results/m4_residual.md`). Der registrierte Pick
reg7n hält im Holdout eine Sharpe von 0,96 bei 41 bps, nachdem Low-Vol- und
BTC-Exposure herausgerechnet sind, ist seit 2023 jedes Jahr positiv und hat
einen deflationierten p-Wert von 0,002 über 1.724 Versuche. Damit fällt er
durch Gate 6 und läuft als **Experiment**: nur in Paper- oder Demo-Autopiloten,
nie automatisch gewählt, nie mit echtem Geld.

Alpaca hat keine Perps. Dieses Dokument beschreibt den Weg, M4 mit echten
Fills und echtem Funding auf einem **Demo-Konto** laufen zu lassen.

## Zuerst das Wichtigste: die Kraken-Futures-Demo gibt es nicht mehr

Kraken hat die Demo-Umgebung `demo-futures.kraken.com` am **14. Juli 2026 um
13 Uhr UTC abgeschaltet** (Kraken Support, Artikel "API testing environment
(derivatives)", zuletzt aktualisiert am 7. Juli 2026). Am 21. Oktober 2026
geprüft: jeder Pfad auf dem Demo-Host antwortet mit einer Weiterleitung (301)
auf die Kraken-Website. Kraken nennt keinen Ersatz.

Was das für Pythia heißt:

- Der **Kraken-Futures-Connector ist vollständig gebaut** (Signatur, Orders,
  Status, Fills, Positionen, Konto, Kontrakte, Marks, Funding-Historie) und mit
  Tests gegen die dokumentierten Antworten abgesichert. Zeigt der Demo-Host auf
  die Website, sagt die Route genau das ("Kraken shut its futures demo
  environment ... down on 2026-07-14") und nimmt keine Demo-Order an. Kommt die
  Demo unter derselben Adresse zurück, funktioniert sie ohne Codeänderung.
- **Kursdaten und Funding von Kraken Futures funktionieren weiter**: sie kommen
  vom öffentlichen Live-Host `futures.kraken.com` ohne Schlüssel. Ein
  **Paper-Autopilot** auf Perps braucht deshalb keine Schlüssel: er handelt mit
  Spielgeld, aber auf echten Kraken-Marks und mit dem echten Funding, Long und
  Short.
- Für **echte Demo-Fills** gibt es eine zweite Perps-Route: **Bybit Demo
  Trading** (USDT-Perpetuals, `api-demo.bybit.com`). Laut Bybit sind die
  öffentlichen Daten dort identisch mit dem echten Markt und die
  Handelsregeln dieselben. Das ist heute die einzige Demo-Route für M4, die
  Orders annimmt.

## Was gebaut ist

| Teil | Wo | Was es tut |
|---|---|---|
| Perps-Connectoren | `crates/pythia-core/src/connectors/perps/` | Kraken Futures (REST v3) und Bybit (v5, `linear`). Nur Demo-Host für Orders, es gibt keinen Live-Connector. |
| Engine | `crates/pythia-core/src/engine/perps.rs` | Märkte `perp:BTC` usw., Shorts nur hier, Sizing nach Notional mit Margin-Prüfung, Funding je Position, Abgleich alle 10 Minuten. |
| Labor | `research/lab/lab/paper/m4_perps.py`, Job `paper-m4-perps` | Tägliches Signal für reg7n, nur auf Coins, die Kraken Futures listet, Gewichte mit Vorzeichen, Evidenz aus dem Residual-Test. `m4_ls` läuft unverändert weiter. |
| App | Autopilot-Seite, Positionen | Auswahl "Perps, long and short", Knopf "M4 perps (demo)", Long/Short/Funding im laufenden Autopiloten, Long- oder Short-Badge je Position. |

**Echtes Geld auf Perps ist überall gesperrt**: Engine, Strategiezustand,
Autopilot-Start, Live-Freigabe (Perps werden aus dem Arm entfernt),
Verbindungstest und Connector-Schicht lehnen mit demselben Satz ab:
"Real-money perpetuals are switched off ... The owner has not cleared the legal
question". Das bleibt so, bis du die rechtliche Frage geklärt hast und es
ausdrücklich anders willst.

## Schritt 1: Demo-Konto und API-Schlüssel

### Bybit Demo Trading (funktioniert heute)

1. Auf bybit.com einloggen (normales Bybit-Konto). Oben rechts auf **Demo
   Trading** umschalten. Das Demo-Konto ist ein eigenes Konto mit eigener
   User-ID, es hängt aber an deinem normalen Bybit-Konto.
2. Im Demo-Konto: Avatar, **API**, neuen Schlüssel anlegen. Rechte: Lesen und
   Schreiben für **Contract/Derivatives** (USDT Perpetual). Keine
   Auszahlungsrechte (gibt es im Demo-Konto ohnehin nicht).
3. Schlüssel und Secret notieren. Das Secret wird nur einmal angezeigt.
4. Falls das Demo-Guthaben leer ist: auf der Demo-Trading-Seite virtuelles
   Guthaben anfordern (USDT).

Ein Schlüssel aus dem echten Konto funktioniert auf dem Demo-Host nicht und
umgekehrt. Ob Bybit für das Demo-Konto eine Identitätsprüfung (KYC) verlangt
und ob Bybit dein Konto aus Deutschland heraus für Derivate (auch Demo)
freischaltet, steht nicht in Bybits API-Doku. Bitte selbst in deinem Konto
prüfen. Hast du schon Bybit-Demo-Schlüssel für die Krypto-Demo
(`PYTHIA_DEMO_EXCHANGE=bybit`), nutzt die Perps-Route dieselben, wenn keine
eigenen gesetzt sind: ein Bybit-Demo-Konto handelt Spot und Perps.

### Kraken Futures Demo (abgeschaltet, nur für den Fall der Rückkehr)

So lief es, solange es die Demo gab (Kraken-Doku, Stand vor der Abschaltung):

1. `demo-futures.kraken.com` öffnen und mit einer beliebigen E-Mail und einem
   Passwort registrieren. Es gab keine E-Mail-Bestätigung und kein KYC; es war
   eine vollständig getrennte Umgebung mit virtuellem Guthaben (die Höhe hat
   Kraken nie dokumentiert).
2. Eingeloggt: **Settings, API Keys, Create Key**. "General API" auf **Full
   Access** (nötig für Orders), "Withdrawal API" auf **No Access**.
3. Public Key und Private Key notieren (der Private Key wird nur einmal
   angezeigt).

Demo-Schlüssel funktionierten nie auf dem Live-Host und umgekehrt.

## Schritt 2: Schlüssel auf den Server (nur root lesbar)

Die Schlüssel kommen **nie** ins Repository. Auf dem Server eine eigene
Env-Datei anlegen, wie bei `/etc/pythia/alpaca-paper.env`:

```bash
cat > /etc/pythia/perps-demo.env <<'EOF'
# Perps-Demo-Route für den M4-Autopiloten. Nur Demo, nie echtes Geld.
PYTHIA_PERPS_DEMO=bybit
BYBIT_DEMO_KEY=...
BYBIT_DEMO_SECRET=...
# Falls Kraken die Futures-Demo zurückbringt:
# PYTHIA_PERPS_DEMO=kraken_futures
# KRAKEN_FUTURES_DEMO_KEY=...
# KRAKEN_FUTURES_DEMO_SECRET=...
EOF
chown root:root /etc/pythia/perps-demo.env
chmod 600 /etc/pythia/perps-demo.env
```

Die Variablen:

| Variable | Bedeutung |
|---|---|
| `PYTHIA_PERPS_DEMO` | `bybit` oder `kraken_futures`; `off` schaltet Perps ganz ab. Leer: der Ort, dessen Schlüssel gesetzt sind (Kraken Futures zuerst), ohne Schlüssel Kraken Futures für Paper-Perps. |
| `BYBIT_DEMO_KEY`, `BYBIT_DEMO_SECRET` | Bybit-Demo-Schlüssel. Fehlen sie und ist `PYTHIA_DEMO_EXCHANGE=bybit`, werden `PYTHIA_DEMO_EXCHANGE_KEY` / `_SECRET` genommen. |
| `KRAKEN_FUTURES_DEMO_KEY`, `KRAKEN_FUTURES_DEMO_SECRET` | Kraken-Futures-Demo-Schlüssel (Secret base64, wie Kraken es ausgibt). |

Die Datei gehört zum Autopilot-Engine-Container (`pythia-autopilot`). Ein neu
aufgesetzter Server nimmt sie über `research/ops/bootstrap.sh` automatisch mit,
wenn sie existiert. Ein laufender Container bekommt neue Env-Variablen nur beim
Neuanlegen: den Container mit denselben Optionen wie in `bootstrap.sh` und
zusätzlich `--env-file /etc/pythia/perps-demo.env` neu starten (der Zustand
liegt in `/srv/pythia-data/autopilot`, er bleibt erhalten). Nicht im Rahmen
dieser Änderung deployt.

Nach dem Start steht im Journal "Perps demo route: Bybit perps demo account
(virtual money)". Die Live-Seite zeigt unter `live.perps` das Konto
(Equity, freie Margin), die Zahl der gelisteten Kontrakte, gebuchtes Funding
und den letzten Abgleich.

## Schritt 3: Labor-Signal

Der Job `paper-m4-perps` (`research/ops/jobs.yaml`, täglich 05:15 UTC, nach
`paper-m4`) schreibt `signals/m4_perps/latest.json`: reg7n, 10 Long und 10
Short aus den 100 liquidesten Perps, nur Coins, die Kraken Futures listet (die
anderen fallen vor dem Ranking heraus), Rank-Buffer 50 %, etwa 50 % long und
50 % short. Nach einem Pull: `research/ops/deploy_lab.sh` und
`research/ops/deploy_ops.sh` (rendert die Cron-Datei). Probelauf ohne
Schreiben:

```bash
docker run --rm --cpus 4 --memory 8g -e PYTHIA_CACHE=/data/lab-cache -v /srv/pythia-data:/data -v /opt/pythia-lab:/app pythia-lab python -m lab.paper.m4_perps --dry-run
```

Bybit listet fast alle Coins, die Kraken Futures listet. Ein Coin, für den der
Perps-Ort keinen Kontrakt hat, bleibt in Cash (wie bei den Alpaca-Büchern),
das Buch ist dann an dieser Stelle nicht ganz marktneutral.

## Schritt 4: Autopilot "M4 perps (demo)" in der App starten

1. Autopilot-Seite, oben im Startformular: **Set up "M4 perps (demo)"**. Das
   setzt: Demo-Konto (oder Spielgeld, wenn die Demo-Route nicht bereit ist),
   "Perps, long and short", Strategie `lab:m4_perps` (selbst gewählt, denn
   Pythia wählt Experimente nie von sich aus), Name "M4 perps (demo)" und einen
   Max-Verlust von 20 %.
2. Betrag eintragen. Im Demo-Modus darf die Summe aller Perps-Demo-Autopiloten
   nicht größer sein als die Equity des Demo-Kontos.
3. Starten. Beim nächsten Signal (oder sofort, wenn ein gültiges da ist)
   werden die Orders gesendet. Im laufenden Autopiloten stehen Long, Short und
   Funding; auf der Positionsseite hat jede Perp-Position ein Long- oder
   Short-Badge und ihr Funding.

Was die Engine dabei prüft:

- **Margin.** Eine Order, die eine Position vergrößert, muss das Brutto-Notional
  des Autopiloten (Positionen plus offene Orders) unter dem Zweifachen seiner
  Equity halten, und im Demo-Konto muss die freie Margin das zusätzliche
  Notional bei 10x decken (das EU-Retail-Limit bei Kraken). Die Konto-Lesung
  muss jünger als 30 Minuten sein. Reduzieren geht immer. Der Kill-Switch
  stoppt auch Verkäufe, die einen Short eröffnen.
- **Funding.** Für jede gehaltene Position liest der Server die
  veröffentlichten Funding-Raten (Kraken alle 4 Stunden die stündliche
  Historie, Bybit stündlich die letzten Abrechnungen) und bucht jede Abrechnung
  seit der letzten: Long zahlt bei positiver Rate, Short bekommt sie. Kraken
  anteilig für den gehaltenen Teil der Stunde, Bybit voll an den, der zum
  Abrechnungszeitpunkt hält. Gebucht als realisierter Gewinn oder Verlust des
  Autopiloten, je Position und gesamt sichtbar, im Journal einmal je Symbol und
  Lauf.
- **Abgleich.** Nach 20 Sekunden und dann alle 10 Minuten werden Positionen
  und offene Orders des Demo-Kontos mit der Summe aller Bücher je Symbol
  verglichen. Gleich bis auf einen halben Kontraktschritt: still. Order
  unterwegs: wartet auf ihren eigenen Bericht. Gleiche Richtung, andere Menge:
  das Konto gewinnt, anteilig je Buch, zum Mark gebucht. Fremde offene Order,
  entgegengesetzte Richtung oder ein Symbol, das kein Buch hält: gemeldet, nie
  geraten.
- **Marks.** Alle 15 Sekunden, solange Perps gehalten werden oder ein
  Perps-Autopilot läuft (die Risikoprüfung lehnt Daten über 30 Sekunden ab),
  sonst alle 5 Minuten. Die Kontraktliste einmal am Tag.

Nicht gegen ein echtes Demo-Konto geprüft: aus diesem Zweig wurde keine
einzige Anfrage an einen Demo-Host geschickt. Alle privaten Antwortformen
stammen aus der Doku; die öffentlichen (Kontrakte, Marks, Funding) wurden am
21. Oktober 2026 gegen die Live-Endpunkte geprüft. Der erste Demo-Lauf ist der
Test: im Journal sollten "DEMO submit" und "DEMO FILL" stehen, die Position im
Bybit-Demo-Konto sichtbar sein und der erste Abgleich "equal" melden.

## Hinweis zu Perps für Privatkunden in der EU (keine Rechtsberatung)

Nur zur Information, damit du später entscheiden kannst. Das ist keine
Rechtsberatung und ersetzt keine Prüfung deiner eigenen Lage (Wohnsitz,
Steuern, Einstufung als Privatkunde, Angemessenheitstest).

- **Kraken** bietet Perpetual Futures in der EU über eine MiFID-II-lizenzierte
  Wertpapierfirma an: Payward Europe Digital Solutions (CY) Ltd, zypriotische
  CySEC-Lizenz 342/17 (Kraken hat die Lizenz im Februar 2025 übernommen). Start
  für Privat- und institutionelle Kunden im EWR im Mai 2025, Perps in der
  EU-App seit Januar 2026.
- Voraussetzungen laut Kraken: Wohnsitz im EWR, vollständige Verifizierung,
  Steuer-ID und ein **Angemessenheitstest** zu Kenntnissen und Erfahrung mit
  Derivaten. Für Privatkunden gilt ein **Hebel von höchstens 10x** (in Krakens
  Kontraktdaten als EU-Retail-Margin von 10 % hinterlegt).
- Ob das Angebot konkret für Deutschland freigeschaltet ist, nennt keine Quelle
  ausdrücklich; vermutlich über den EWR-Pass. Das zeigt der Freischaltungsweg in
  der Kraken-App.
- Bybit bedient den EWR über eine eigene EU-Gesellschaft; ob Derivate dort für
  Privatkunden aus Deutschland angeboten werden, ist hier nicht geprüft.
- Für Derivate gelten andere Steuerregeln als für Spot-Krypto (in Deutschland
  zum Beispiel Termingeschäfte statt privater Veräußerungsgeschäfte). Pythias
  Steuerexport (`fills.jsonl`) enthält keine Demo-Fills.

Solange du nichts anderes entscheidest, bleibt echtes Geld auf Perps in Pythia
an jeder Stelle gesperrt.
