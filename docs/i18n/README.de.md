# Pythia

[English](../../README.md) · Deutsch · [简体中文](README.zh-CN.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · [Español](README.es.md) · [Français](README.fr.md) · [Português](README.pt-BR.md)

Pythia ist ein Trading-Cockpit, das auf Papier anfängt und dort bleibt, bis eine Strategie sich mehr verdient hat. Es besteht aus einer Engine in Rust, einer Desktop-App und einer Web-Oberfläche darüber und einem Forschungslabor in Python, das entscheidet, was die Engine handeln darf. Das Labor zählt jede Idee, die es je ausprobiert hat, damit ein glücklicher Backtest nicht durchrutscht.

Keine Strategie hier ist nachweislich profitabel. Lies [SAFETY.md](../../SAFETY.md), bevor du ein echtes Konto verbindest.

<table>
  <tr>
    <td width="50%"><img src="../img/app-home.png" alt="Startseite"></td>
    <td width="50%"><img src="../img/app-autopilot.png" alt="Autopilot"></td>
  </tr>
</table>

Bildschirmfotos aus einem Entwicklungs-Build mit Beispieldaten.

## Was es macht

- Ein Autopilot ist ein Betrag, der selbstständig eine Strategie handelt, bis du ihn stoppst oder eine Stoppregel greift. Mehrere laufen nebeneinander, jeder wird an BTC gemessen.
- Krypto, US-Aktien und ETFs laufen auf dem Alpaca-Papierkonto. Die Long/Short-Bücher handeln Perps auf Papier oder auf einem Bybit-Demokonto, wenn du Demo-Schlüssel hinterlegst.
- Vor jeder Order steht der Risikomanager: Not-Aus, Tagesverlust- und Drawdown-Grenzen, Positionsobergrenzen, Volatilitätssteuerung. Ist etwas unklar, lehnt er ab.
- Jede Studie im Labor wird vor ihrem ersten Lauf festgeschrieben, nach Kosten außerhalb der Stichprobe getestet, und ihre Sharpe wird um die Zahl aller bisherigen Versuche bereinigt.
- Modelle (Volatilität, Coin-Ranking, Renditequantile) werden im Labor trainiert und von der Engine ausgeführt. Sie laufen zuerst im Schatten, bevor sie einen Trade beeinflussen dürfen.
- Meldungen kommen über Telegram oder einen beliebigen Webhook, auf Deutsch oder Englisch.

## Aufbau

<img src="../img/architecture.svg" alt="Pythia: oben die Oberflächen, darunter die Rust-Engine, dann Labor und Recorder, unten die Märkte" width="100%">

Ein Laborbuch kommt nur zusammen mit seinen Belegen zu einem Autopiloten. Die automatische Auswahl ordnet die Bücher nach diesen Belegen und nach ihrer Vorwärtsbilanz, und ein experimentelles Buch läuft nur dort, wo ein Autopilot es ausdrücklich anfordert.

## Ergebnisse bisher

Alle Zahlen stammen aus den Ergebnisdateien des Labors oder aus den Aufzeichnungen der Engine. [`scripts/readme_charts.py`](../../scripts/readme_charts.py) zeichnet jede Grafik hier und nennt ihre Quellen.

<img src="../img/scoreboard.png" alt="Sharpe außerhalb der Stichprobe für die getesteten Strategien" width="100%">

Das beste Buch ist ein Donchian-Ausbruch auf den zehn liquidesten Coins: Sharpe 1,17 seit 2024, gegenüber 0,74 für einfaches Halten von BTC. Die Bereinigung besteht es trotzdem nicht. Bei 1.836 gezählten Versuchen würde die beste von so vielen reinen Zufallsstrategien etwa 2,69 zeigen.

Zwei Long/Short-Studien auf Perps haben ihre vorab festgelegten Tests bestanden (das M4-Residuum und ein Funding-Carry). Keine übersteht die Bereinigung, deshalb laufen beide nur als Experimente. Die meisten Momentum-Bücher sind in Wahrheit der 200-Tage-Filter von BTC: an Tagen, an denen der Filter aus ist, verlieren sie alle Geld.

<img src="../img/forward.png" alt="Vorwärtsbilanz der Papier-Autopiloten seit dem 15. Oktober 2026" width="100%">

Die Papier-Autopiloten laufen seit dem 15. Oktober 2026. Nach sechs Tagen liegt die Hauptauswahl bei +0,48 % und BTC bei +3,22 %. Das ist viel zu kurz, um etwas zu bedeuten; die Grafik steht hier, damit die Bilanz vom ersten Tag an öffentlich ist.

<img src="../img/research_funnel.png" alt="Wachstum der Versuchszahl und das Urteil jeder Studie" width="100%">

Bisher 69 Studien: 43 gescheitert oder abgebrochen, 7 laufen als gekennzeichnete Experimente auf Papier, 2 haben ohne Bestätigung bestanden, 5 haben ein Modell geliefert, das seine Vergleichsbasis schlägt. Jedes Urteil steht in [`research/lab/README.md`](../../research/lab/README.md).

<img src="../img/by_year.png" alt="Sharpe pro Jahr für die Bücher, die noch laufen" width="100%">

Grafiken neu zeichnen:

```bash
pip install matplotlib
PYTHIA_DATA=/path/to/lab/data python scripts/readme_charts.py
```

Ohne `PYTHIA_DATA` fällt die Vorwärtsgrafik weg.

## Loslegen

Du brauchst Node.js (aktuelles LTS), Rust 1.85 oder neuer und für das Labor Python 3.

Desktop-App:

```bash
npm install
npm run tauri dev
npm run tauri build
```

Server und Web-Oberfläche:

```bash
cp .env.example .env
npm run server
```

```bash
echo "VITE_PYTHIA_SERVER=http://localhost:8787" > .env.local
npm run dev
```

Der Server lauscht auf `127.0.0.1:8787` (änderbar mit `PYTHIA_BIND`). Schlüssel in `.env` sind optional; ohne sie bleibt alles auf Papier. Ohne `VITE_PYTHIA_SERVER` läuft in der Web-Oberfläche eine kleine Papier-Engine im Browser.

Forschungslabor:

```bash
cd research/lab
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python -m pytest tests
```

Die Daten kommen vom Recorder in `research/recorder` und seinem Verlaufs-Backfill. [`research/lab/README.md`](../../research/lab/README.md) listet jede Studie, [`research/ops/README.md`](../../research/ops/README.md) die geplanten Jobs.

Prüfungen:

```bash
npm run check
npm run preflight
npm run security:scan
```

Unter Windows entfernen die npm-Skripte `CC` und `CXX` aus der Umgebung, weil Pfade mit Leerzeichen native Rust-Builds kaputt machen.

## Verzeichnisse

| Pfad | Inhalt |
|---|---|
| [`crates/pythia-core`](../../crates/pythia-core) | Engine: Strategien, Risiko, Autopiloten, Ausführung, Börsen, Prognosen, Meldungen |
| [`crates/pythia-ml`](../../crates/pythia-ml) | Modellausführung (LightGBM, ONNX) mit Paritätstests gegen das Labor |
| [`server`](../../server) | HTTP- und WebSocket-Server über der Engine |
| [`src-tauri`](../../src-tauri) | Desktop-App |
| [`src`](../../src) | React-Oberfläche |
| [`research/lab`](../../research/lab/README.md) | Studien, Modelle, Papierbücher, Strategiefabrik |
| [`research/recorder`](../../research/recorder/README.md) | Marktdaten-Recorder und Verlaufs-Backfill |
| [`research/ops`](../../research/ops/README.md) | Jobtabelle, Gesundheitsprüfungen, Deploy-Skripte |
| [`docs`](..) | Anleitungen für [Demo-Handel](../DEMO.md), [Live-Läufe](../LIVE-RUN.md), [Meldungen](../ALERTS.md), [Modelle](../MODELS.md), [die Claude-API](../AI.md) und die [Bereitschaftsregel](../LIVE-READINESS.md) (englisch) |

## Sicherheit

- Eine frische Installation handelt nichts Echtes. Autopiloten starten auf Papier oder auf dem Demokonto einer Börse.
- Live-Handel braucht deine eigenen Schlüssel und eine getippte Bestätigung pro Börse. Nichts schaltet sich selbst scharf.
- Schlüssel liegen im Schlüsselbund des Betriebssystems oder in der Umgebung des Servers und werden nie geloggt oder an die Oberfläche geschickt.
- Pythia hat keine Funktion für Auszahlungen, Einzahlungen oder Überweisungen. Gib API-Schlüsseln nur Handelsrechte.
- Krypto-Spot ist nur long, Shorts gibt es nur auf Perps, Polymarket wird nur gelesen.

Die vollständige Liste steht in [SAFETY.md](../../SAFETY.md). Sicherheitslücken bitte über [SECURITY.md](../../SECURITY.md) melden.

## Lizenz

[MIT](../../LICENSE). Marktdaten von Alpaca, Binance, Kraken, Bybit, OKX, Coinbase, Deribit, DefiLlama, Polymarket und SEC EDGAR; für die Daten gelten jeweils die Bedingungen der Quelle. Wenn dir Pythia hilft, kannst du es [auf Ko-fi unterstützen](https://ko-fi.com/senseiissei).
