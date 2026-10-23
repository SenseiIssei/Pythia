# Telegram samples (German)

One sample of every card Pythia posts to the owner's chat, in German, as the
chat shows it without its markup (bold titles, monospace blocks). The numbers
are made up. The engine's cards come from

    cargo test -p pythia-core --lib print_german_samples -- --ignored --nocapture

and the lab's from the card builders in `research/lab` (`lab.ops.notify`,
`lab.ops.readiness`, `lab.ai.critic`, `lab.ai.director`, `lab.polymarket.card`,
`lab.pumpfun_rt.card`) with `PYTHIA_ALERT_LANG=de`. The number in brackets is
the post's length in characters (Telegram allows 4096).

What changed on 2026-10-23, and why:

- pump.fun real money: the test mode is the "Alpha-Phase" in every card, never
  "TEST". A card's colour is its outcome (a buy blue, a win green, a loss red,
  break-even grey) instead of red for everything; the title says the result
  first, then one block with stake, proceeds, P&L in SOL and euro, hold time
  and the reason for the sale in plain words, then the measured latency.
  A closed trade carries the coin's chart around it, the day card the day's
  cumulative P&L.
- Every picture in one dark look (fonts, margins, title block, colours), and
  end labels that no longer overlap.
- The morning briefing at 9:00 Berlin replaces the daily digest after the
  learning loop. It and every real-money trade card also go to Discord when
  a webhook is set (research/ops/discord-setup.sh).

What changed on 2026-10-21, and why:

- Daily digest: "Heute" was the same as "Seit Start" for every autopilot. The
  engine's equity curve kept only its start and the last 19 hours (its
  thinning halved the oldest points at every pass), so the equity "a day ago"
  was the start capital. The curve is now thinned evenly, the learning report
  calls today unknown without a point near a day ago, and the digest counts
  today from its own snapshot of yesterday's digest.
- Daily digest and weekly report: one table, one row per autopilot, instead of
  seven lines each. The header says "BTC 24 h" (or "BTC diese Woche"); the
  column "±BTC" is points against BTC since the start.
- "Abschlüsse heute 0 · Gebühren 11,39 $": fees are paid on every fill, a
  closed position is counted once. The digest now says orders filled,
  positions closed and fees on one line.
- Trades: the partial maker fills of a rebalance were a card each (14 cards
  in 9 minutes). Fills now wait per autopilot until none came for 150 s (at
  most 600 s) and go out as one card.
- After quiet hours: one line per autopilot and per kind of alert, not every
  held alert line by line; nothing is cut in the middle of a line.

## Engine (pythia-core)

### Einzelne Ausführung [183]

```
🟢 Test · TSMOM tranches kaufte BTC
Menge      0,004 BTC
Preis   108.250,00 $
Wert        433,00 $
Gebühr        0,15 $
Demo: virtuelles Geld beim Handelsplatz
```

### Umschichtung aus 14 Teilausführungen, eine Karte [397]

```
🔁 Umschichtung · Test · TSMOM tranches
14 Ausführungen in 4 Zeilen: gekauft für 1.308,20 $, verkauft für 865,23 $.
Richtung Coin    Wert    Ø Preis
Verkauf  SOL    621 $   186,40 $
Verkauf  AVAX   244 $    27,10 $
Kauf     ETH  1.093 $ 3.905,00 $
Kauf     LINK   215 $    17,90 $
Realisiert  +8,40 $ 🟢
Gebühren     2,10 $
Demo: virtuelles Geld beim Handelsplatz
```

### Ruhezeit vorbei [404]

```
🌙 Ruhezeit vorbei
18 Meldungen wurden von 23:00 bis 07:00 zurückgehalten. Dringende gingen sofort raus.
Test · TSMOM tranches: Umschichtung, 7 Verkäufe, 7 Käufe, verkauft 865 $, gekauft 1.308 $, Gebühren 2,10 $, realisiert +8,40 $
Auto-Pick (main): Umschichtung, 1 Kauf, gekauft 1.080 $, Gebühren 0,15 $
Starke Bewegung: 2, zuletzt Momentum: Wert -10,0 % in 24 h
Neue Listungen: Neu bei Kraken: ZK
```

### Autopilot gestartet [502]

```
🚀 Momentum gestartet
Regeln: stoppt bei 5 % Verlust (Wert 9.500,00 $); stoppt bei 400,00 $ Verlust (Wert 9.600,00 $); gibt höchstens 3,5 % vom Höchststand ab; sichert bei jeweils 10 % Gewinn die Hälfte (zuerst bei Wert 11.000,00 $) und läuft weiter; endet Do 15. Okt, 16:00.
Kapital                       10.000,00 $
Modus                               Paper
Handelsplatz         Krypto und US-Aktien
Aufteilung    Krypto 70 %, US-Aktien 30 %
Bücher                    TSMOM, Breakout
```

### Autopilot gestoppt [391]

```
🛑 Momentum gestoppt
Nachgezogene Untergrenze erreicht: Wert 9.412,30 $ hat 3 % vom Höchststand 9.700,00 $ abgegeben (Untergrenze 9.409,00 $).
Wert                        9.412,30 $
GuV seit Start       -587,70 $ -5,88 % 🔴
ggü. BTC seit Start         -4,68 Pkt. 🔴
Bisher geschlossen                  14
Gebühren                       12,50 $
3 Positionen geschlossen.
```

### Marktdaten veraltet und wieder aktuell [144, 93]

```
📡 Marktdaten veraltet
Seit 12 min: Kurse für BTC, ETH, Kerzen für SOL. Einstiege werden abgelehnt, Stops warten auf einen frischen Preis.
```

```
📡 Marktdaten wieder aktuell
Einstiege und Stops arbeiten wieder mit aktuellen Preisen.
```

### Tagesverlust-Bremse [137]

```
🧯 Tagesverlust-Bremse
Das Buch liegt heute 3,2 % im Minus, Grenze 3,0 %. Neue Einstiege werden bis zum nächsten UTC-Tag abgelehnt.
```

### Not-Aus [169, 89, 48]

```
🚨 Not-Aus
Von der Drawdown-Bremse ausgelöst: Wert 9.100,00 $ liegt 9,1 % unter dem Höchststand, Grenze 9,0 %. Bis zur Freigabe gehen nur schließende Orders durch.
```

```
🚨 Not-Aus
Von Hand ausgelöst. Bis zur Freigabe gehen nur schließende Orders durch.
```

```
🚨 Not-Aus aufgehoben
Von Hand aufgehoben.
```

### Abgleich weicht ab [150, 114]

```
⚖️ Abgleich weicht ab
Kraken und Pythias Buch wichen bei 2 Positionen ab; Pythia hat die Zahlen des Handelsplatzes übernommen. Mehr im Journal.
```

```
⚖️ Abgleich weicht ab
Das Alpaca-Paper-Konto und Pythias Demo-Buch weichen bei 1 Paar ab; siehe Seite Live.
```

### Orders abgelehnt [87]

```
⛔ Orders abgelehnt
4 Demo-Orders in Folge abgelehnt (zuletzt: BTC/USD): HTTP 403
```

### Modell-Drift [263, 100]

```
🧭 Volatilitätsmodell stummgeschaltet
Eingaben außerhalb des Trainingsbereichs: nicht verlässlich, bis sie zurück sind oder neu trainiert wurde.
Eingaben außerhalb       2 von 12
rv_24h              7 % außerhalb
funding             6 % außerhalb
```

```
🧭 M2-Coin-Rangliste wieder im Bereich
M2-Coin-Rangliste: Eingaben wieder im Trainingsbereich.
```

### Starke Bewegung [128, 203]

```
🌊 BTC +3,8 % in 1 h
Gehalten von Momentum.
Jetzt     61.234,50 $
vor 1 h   59.000,00 $
Änderung      +3,79 % 🟢
```

```
🌊 Momentum: Wert -10,0 % in 24 h
Der Wert des Autopiloten, Positionen zum aktuellen Preis.
Wert                9.000,00 $
vor 24 h           10.000,00 $
Änderung  -1.000,00 $ -10,00 % 🔴
```

### Testnachricht [294]

```
✅ Testnachricht
Meldungen von Pythia kommen in diesem Chat an.
Kategorien an                   12 von 14
Ruhezeit                  23:00 bis 07:00
Starke Bewegung   2,5 % / 1 h, 8 % / 24 h
Beispiel Gewinn       +1.234,50 $ +1,23 % 🟢
Beispiel Verlust         -87,65 $ -0,42 % 🔴
```

## Lab (research/lab)

### Tagesbericht, mit Grafik [1130]

```
📊 Tagesbericht · Mi 21. Okt
6 Autopiloten laufen, heute +118,36 $ 🟢 · BTC 24 h +1,15 %
Autopilot      Wert Heute Start  ±BTC
Auto-Pick    20.124 +0,20 +0,62 -1,67
Memecoin ro…  9.861 +0,01 -1,39 -3,68
TSMOM regime  9.951 +0,26 -0,49 -2,78
TSMOM top 20 10.012 +0,13 +0,12 -2,17
TSMOM tranc…  9.991 +0,39 -0,09 -2,38
Safe BTC fi…     95 +0,42 +0,42 -1,87
Wert in $, Heute und Start in %, ±BTC in Punkten gegenüber BTC seit Start; alle Demo; Konto safe: Safe BTC fi…
Heute 60 Orders ausgeführt · 12 Positionen geschlossen · Gebühren 12,00 $
Vorwärtstest tsmom ✅ im Plan · m4_ls 👀 beobachten · picks_ls 🌱 noch früh
Echtgeld noch keiner bereit; am nächsten Auto-Pick: 6 von 9 Regeln, noch 34 Tage
Systemzustand ✅ alles grün
Lernen 2 Kostenänderungen; 6 Autopiloten laufen, der beste mit +0,40 Punkten ggü. BTC seit Start.
KI-Kurzbericht (Schatten) BTC hielt über Nacht die 108.000 $, die Finanzierung blieb neutral.
Die TSMOM-Bücher kauften nach; kein Autopilot nahe an seiner Verlustgrenze.
Heute um 14:30 Uhr kommen US-Arbeitsmarktdaten; mit mehr Schwankung ist zu rechnen.
```

### Wochenbericht, mit Grafik [801]

```
🗓️ Wochenbericht · 14. bis 21. Okt
6 Autopiloten: diese Woche +298,11 $ 🟢 · BTC diese Woche +3,10 %
Autopilot      Wert Woche Start  ±BTC
Auto-Pick    20.124 +0,50 +0,62 -2,60
Memecoin ro…  9.861 +0,31 -1,39 -2,79
TSMOM regime  9.951 +0,56 -0,49 -2,54
TSMOM top 20 10.012 +0,43 +0,12 -2,67
TSMOM tranc…  9.991 +0,69 -0,09 -2,41
Safe BTC fi…     95 +0,72 +0,42 -2,38
Wert in $, Woche und Start in %, ±BTC in Punkten gegenüber BTC in dieser Woche; alle Demo; Konto safe: Safe BTC fi…
Diese Woche 75 Orders ausgeführt · 30 Positionen geschlossen
Unter Höchststand am tiefsten Safe BTC fi… 1,40 %
Bestes Teilportfolio sleeve0 +123,85 $ · schwächstes sleeve1 -138,80 $
Claude-API diese Woche 4,12 $, 0,59 $ am Tag: Tagesbericht 2,10 $, Strategie-Prüfung 1,40 $
```

### Systemprüfung rot und wieder grün [188, 73]

```
🩺 Systemprüfung seit 2 Läufen rot
2 Prüfungen nicht in Ordnung, Stand Mi 21. Okt, 11:00.
Platte nur noch 4 GB frei auf /data
paper tsmom letzte Zeile von gestern 06:00
```

```
✅ Systemprüfung wieder grün
Seit der Prüfung am Mi 21. Okt, 12:00.
```

### Ruhezeit vorbei (Labor) [181]

```
🌙 Ruhezeit vorbei
4 Labor-Meldungen wurden von 23:00 bis 07:00 zurückgehalten.
Trends 3, zuletzt PEPE auf Alpaca +22 % in 24 h
Neue Listungen Neu bei Kraken: ZK
```

### Echtgeld-Bereitschaft [649]

```
🟢 Bereit für einen Echtgeld-Vorschlag
Auto-Pick erfüllt jede Echtgeld-Regel auf seinem Alpaca-Paper-Konto (Risikostufe 3, ausgewogen).
Zeit, Abschlüsse  45,2 Tage, 41 Abschlüsse 🟢
Netto-GuV                        +412,30 $ 🟢
Plus-Wochen                        4 von 4 🟢
Vergleichswert                  +1,92 Pkt. 🟢
Rückgang                            3,10 % 🟢
Backtest-Band                    innerhalb 🟢
Abgleich                          7/7 Tage 🟢
Inflation                 +18,20 % im Jahr 🟢
ETF-Hürde                 +18,20 % im Jahr 🟢
Scharf schalten kann nur der Besitzer. Nichts wurde scharf geschaltet oder geändert.
```

### Strategie-Prüfung [437]

```
🔍 Strategie-Prüfung: 2 Befunde
Die Orders von gestern je Autopilot gegen seine Regeln. Antworte /real ID oder /notreal ID, um einen Befund zu bewerten.
[c41] Regelbruch TSMOM tranches: kaufte ETH, obwohl das 4-Stunden-Signal negativ war. Signal -0,8 um 09:00. (die Zahlen bestätigen es)
[c42] Gebühren Auto-Pick: zahlte 11 $ Gebühren für 3 $ Umschichtung. 14 Ausführungen in 9 Minuten. (aus den Zahlen nicht prüfbar)
```

### Forschungsleitung [419]

```
🧭 Forschungsleitung: 2 Studienentwürfe
Entwürfe für Vorab-Registrierungen, über die du entscheidest; nichts startet sie. Dateien in research/lab/proposals. Kosten 0,84 $.
1. TSMOM mit Volatilitätsziel 15 % statt 20 %: weniger Rückgang bei gleichem Ertrag?
2. Memecoin-Rotation nur bei positivem BTC-Trend: hilft der Filter?
Nicht weiter verfolgen Keine weiteren Varianten des Breakout-Buchs.
```

### Polymarket, Tageskarte und großer Vorsprung [562, 254]

```
🎯 Polymarket-Paperbücher
Fr 15. Jan: 5 offene Positionen, 2 eröffnet, 1 heute aufgelöst.
Buch         Kapital  Start Offen Treffer
Modellbuch  10.120 $ +120 $     3     3/4
Claude-Buch  9.900 $ -100 $     2     0/0
Claude: 40 Prognosen, 3 aufgelöst; Brier 0,200 gegenüber 0,150 des Markts
Modell auf offenen Märkten: 300 Prognosen, 0 aufgelöst; zu früh für eine Wertung
Kombination: wartet auf 200 aufgelöste Claude-Prognosen
Claude-Kosten bisher 0,42 $
Nur Paper: keine Wallet, keine Orders. Polymarket ist in mehreren Ländern gesperrt.
```

```
🎯 Polymarket: großer Vorsprung (Paper)
Will it happen?
Claude-Buch kaufte JA zu 0,310, Prognose 0,550, Vorsprung 22,0 Punkte, Einsatz 150 $
Endet Di 26. Jan
Nur Paper: keine Wallet, keine Orders. Polymarket ist in mehreren Ländern gesperrt.
```

The market's question stays in the language Polymarket asks it in.

### pump.fun, Tageskarte des Labors [1261]

```
⚡ pump.fun Echtzeit-Labor, Di 20. Okt
Aufgezeichnet: 91.234 neue Token, 4.120.000 Käufe und Verkäufe auf der Kurve, 912 volle Kurven.
Buch    Geschl. Mittel G/V SOL
P_p90        35 +4,0 %  +0,210
B_w3_x1     140 -9,0 %  -1,360
Paper-Bücher gestern: 2 mit geschlossenen Positionen, -1,150 SOL insgesamt.
Unser Datenstrom sah neue Token 1,4 s nach ihrem Block (Median; 90. Perzentil 2,6 s), 31 % innerhalb einer Sekunde, 12 % innerhalb von zwei Slots.
Zu früh für ein Urteil: 9 Tage aufgezeichnet; die Schwelle braucht 14 Tage und 300 Positionen außerhalb der Stichprobe.
Studie: 1 von 2 Regeln bestehen die Schwelle außerhalb der Stichprobe; Auswahl B_w3_x1.
Modelle: 1 von 2 Zielen schlagen ihre Vergleichsmodelle; Wallet-Merkmale bei 1 übernommen, Namenskategorien bei 0.
Am nächsten an echtem Geld: P_p90, 9 von 14 Tagen, 140 von 300 Positionen außerhalb der Stichprobe, 7 von 30 Tagen im Schattenbuch, die Schwellen sind bestanden.
0 von 1 Strategien sind bereit für echtes Geld.
Echtgeld: gesperrt, nichts handelt mit echtem Geld.
Nur Paper: keine Wallet, kein Schlüssel, keine Transaktion. Ausführungen sind mit 0,4 bis 3 s Verzögerung nach dem Signal modelliert; die schnellsten Sniper sind vorher drin.
Nur Paper · Echtzeit-Labor
```

### pump.fun Alpha-Phase, Kauf [281]

```
🔵 Kauf · KIMCHINU
pump.fun · Alpha-Phase · P_pool0
Einsatz  0,0525 SOL · 8,31 €
Token             11.700.000
⏱ 1,4 s nach dem Signal gelandet (Modell 1,0 s) · Schlupf +1,2 %
Alpha-Phase: kleiner Echtgeld-Einsatz, Notschalter in der App.
pump.fun · Echtgeld
```

### pump.fun Alpha-Phase, Gewinn (mit Grafik) [430]

```
🟢 +32,5 % · KIMCHINU
pump.fun · Alpha-Phase · P_pool0
Einsatz       0,0525 SOL · 8,31 €
Erlös        0,0696 SOL · 11,01 €
Ergebnis    +0,0171 SOL · +2,71 €
Haltedauer              3 min 7 s
Ausstieg           Gewinnmitnahme
Heute       +0,0213 SOL · +3,37 €
⏱ 1,4 s nach dem Signal gelandet (Modell 1,0 s) · Schlupf +1,6 %
Alpha-Phase: kleiner Echtgeld-Einsatz, Notschalter in der App.
pump.fun · Echtgeld
```

### pump.fun Alpha-Phase, Verlust (mit Grafik) [433]

```
🔴 -28,1 % · DUCKY
pump.fun · Alpha-Phase · P_pool0
Einsatz        0,0525 SOL · 8,31 €
Erlös          0,0378 SOL · 5,98 €
Ergebnis     -0,0147 SOL · -2,33 €
Haltedauer                    42 s
Ausstieg                 Stop-Loss
Heute       -0,1276 SOL · -20,19 €
⏱ 15 s nach dem Signal gelandet (Modell 1,0 s) · Schlupf +11,2 %
Alpha-Phase: kleiner Echtgeld-Einsatz, Notschalter in der App.
pump.fun · Echtgeld
```

### pump.fun Alpha-Phase, Tag (mit Grafik) [351]

```
🔴 pump.fun Do 22. Okt · Alpha-Phase
P_pool0: 22 Abschlüsse, 8 gewonnen.
Tag     -0,1276 SOL · -20,19 €
Gesamt   -0,0329 SOL · -5,20 €
Wallet   0,7247 SOL · 114,65 €
Latenz 2,3 s Median über 22 Käufe (Modell 1,0 s)
1 Auftrag gescheitert.
Alpha-Phase: kleiner Echtgeld-Einsatz, Notschalter in der App.
pump.fun · Echtgeld
```

### Morgen-Briefing, mit Grafik, auch an Discord [1749]

```
☀️ Morgen-Briefing · Fr 23. Okt
pump.fun -0,0500 SOL · Autopiloten heute -148,71 $ · ✅ alles grün
🎯 pump.fun Alpha-Phase
Gestern                        7 · 2 gewonnen
Ergebnis                -0,0500 SOL · -7,91 €
Bester / Schlechtester      +12,4 % / -28,1 %
Gesamt                  -0,0329 SOL · -5,20 €
Wallet                  0,7247 SOL · 114,65 €
Einsatz                   0,0500 SOL · 7,91 €
📈 Papier und Autopiloten 9 Autopiloten laufen
Autopilot      Wert Heute Start  ±BTC
Auto-Pick    10.079 -0,04 +0,79 -0,43
Crypto + SPY  9.977 -0,24 -0,23 +2,90
M4 perps     10.153 +0,23 +1,53 +4,69
Wert in $, Heute und Start in %, ±BTC in Punkten gegenüber BTC seit Start; alle Demo
Seit Start 261 Orders ausgeführt · 145 Positionen geschlossen · Gebühren 65,25 $
Vorwärtstest 20 Papierbücher: 7 🌱 noch früh, 6 ✅ im Plan, 4 unbekannt, 3 👀 beobachten
Echtgeld noch keiner bereit; am nächsten Auto-Pick: 6 von 9 Regeln, noch 46 Tage
🧪 Labor
Modell-Zoo im Einsatz M2; Schattenlauf M1, M8q, M8u; 4 an der Schwelle gescheitert, 4 ausgemustert
Zuletzt entschieden M8u übernommen
Neue Ergebnisse hedged_breakout, taker_imbalance_xs
🃏 Pokémon
Spielsammlung    788,45 $ · -21,1 %
Wirken günstig                    3
Vorne           Ho-oh (Black Star…
🎮 CS2-Skins
Spielportfolio   10.000 € · +0,0 %
Hinweise 24 h                    1
Steam          1.120 liquide Skins
🪙 Coins
BTC 24 h              -0,6 %
ETH 24 h              -1,0 %
SOL 24 h              +0,1 %
Stärkster Anstieg  BMT +28 %
Neue Listungen Kraken NEXO
📰 Nachrichten
• Bitcoin slides below $81,500 as tech stock sell-off spreads to Asian equities
• Chainlink partners with LG CNS to drive Korean won stablecoin expansion
Systemzustand ✅ alles grün
aus den Dateien von Labor und Servern, ohne KI
```

Die Grafik: oben die Autopiloten seit ihrem Start gegen BTC, unten das
Ergebnis der pump.fun Alpha-Phase der letzten 14 Tage in SOL. Abschnitte ohne
Daten oder mit Daten älter als zwei Tage fallen weg. Auf Discord kommt
dasselbe als Embed mit der Grafik.
