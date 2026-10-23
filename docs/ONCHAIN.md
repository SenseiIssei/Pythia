# Eigene Wallet als Handelsplatz: Stufe 1, Paper auf der Chain

**Stand 2026-10-23. EXPERIMENT, nur Paper.** Nichts in Stufe 1 signiert,
sendet oder liest einen Schlüssel.

## Was Stufe 1 macht

- `research/lab/lab/onchain/mints.py`: die Coins, die auf Solana tief handelbar
  sind, als SPL-Token mit Mint, Dezimalstellen und dem Kraken/Alpaca-Coin, für den
  sie stehen: SOL, BTC (cbBTC), ETH (WETH, Wormhole), JUP, BONK, WIF, POPCAT, RAY,
  PYTH, JTO, RENDER, TRUMP; USDC ist Cash. Jede Mint am 2026-10-23 gegen
  Jupiters verifizierte Token-Liste geprüft (die älteren auch gegen die Solana
  Labs Token-Liste). Ohne etablierte SPL-Version und daher nicht dabei: NEAR,
  SUI, DOGE, XRP, ADA, AVAX, LINK, LTC, DOT, BCH, PEPE, SHIB. Ein Ziel auf so
  einem Coin bleibt Cash.
- `jupiter.py`: Jupiters öffentliche Quote- und Preis-API (lite-api.jup.ag, ohne
  Schlüssel), mit Timeouts, Wiederholungen und Pausen nach den Rate-Limit-Headern.
- `paper.py`: ein Swap wird zum Out-Betrag der Quote gefüllt, abzüglich Solanas
  Grundgebühr (5.000 Lamports) und einer Priority Fee (Standard 0,0001 SOL,
  `PYTHIA_ONCHAIN_PRIORITY_SOL`). Kosten je Fill: die halbe Rundreise (der
  erhaltene Betrag sofort zurück quotiert) plus Netzgebühren.
- `book.py`, Jobs `onchain-paper` (täglich nach `paper-live-copy`) und
  `onchain-mark` (stündlich, nur Bewertung): ein Paper-Konto mit 1.000 USDC folgt
  den Gewichten von `breakout_top10_live`, dem Zwilling, den der Kraken-Live-Test
  handelt. Journal wie bei den anderen Paper-Büchern unter
  `paper/onchain_breakout_top10_live/` (`equity` auf der 10.000er-Basis der
  Lab-Bücher, `equity_usdc` das Konto), damit Forward-Report und Lab-Seite es
  zeigen. Jeden Tag zusätzlich eine Rundreise von 100 USDC je Coin, damit die
  Kosten auch sichtbar sind, solange das Buch in Cash steht.
- Bericht `reports/onchain/latest.md`: Kosten je Rebalance auf der Chain gegen
  dieselben Trades bei Kraken (Taker 40 bps plus der gemessene halbe Spread aus
  `reports/costs`) und gegen die Paper-Fills der Engine auf Kraken.

## Kosten bisher (2026-10-23, eine Messung, 100 USDC, eine Richtung)

| Coin | Chain | Kraken |
|---|---|---|
| SOL | 1,2 bps | 40,5 |
| BTC (cbBTC) | 1,4 | 40,0 |
| ETH (WETH) | 1,9 | 40,1 |
| JUP, TRUMP, RAY | 0,9 bis 4,6 | 40 + Spread |
| BONK, WIF, PYTH, RENDER | 7,5 bis 13,5 | 40 + Spread |
| POPCAT, JTO | 20 bis 22 | 40 + Spread |

Die Kraken-Gebühr allein (40 bps) liegt über jedem Wert auf der Chain. Für die
kleinen Coins hat Kraken noch keinen gemessenen Spread; der Bericht nimmt dort
die 25 bps aus `config/costs.json`. Eine Messung ist kein Ergebnis: die Zahlen
zählen erst nach Wochen und echten Rebalances. Größere Orders zahlen mehr Price
Impact. Heute hält `breakout_top10_live` nur NEAR, das es auf Solana nicht gibt:
das Buch steht vorerst ganz in Cash.

## Was Stufe 2 bräuchte (eigene Aufgabe, erst nach Durchsicht von Stufe 1)

Entwurf und Entscheidungen jetzt in `docs/ONCHAIN-STAGE2.md`, der Nachweis vor echtem Geld vorab
registriert in `research/lab/results/onchain_stage2_prereg.md`. Wichtig für Stufe 1: Jupiter führt die
Metis-API `/swap/v1`, die `jupiter.py` heute abfragt, nicht mehr weiter (ersetzt durch Swap V2); Stufe 2
und das Paper-Buch wechseln auf `/swap/v2/build`. Die Punkte unten bleiben die Grundsätze:


1. Eine eigene Wallet, gemacht mit dem Wallet-Tool (`python -m
   lab.pumpfun_rt.wallet new`, eigene Datei, nicht die pump.fun-Wallet), nur mit
   dem Betrag, der verloren gehen darf.
2. Ein schriftliches Ack des Besitzers mit Caps: Betrag je Swap, je Tag, gesamt,
   maximaler Verlust, Ablaufdatum. Ohne gültiges Ack kein Swap.
3. Ein Guard vor jedem Signieren: nur Jupiter-Swap-Instruktionen, nur Mints aus
   der Tabelle, Quelle und Ziel nur Token-Konten der eigenen Wallet, kein
   Transfer, kein Close an fremde Adressen, keine anderen Programme außer den
   nötigen (Compute Budget, Token, Associated Token).
4. Simulieren vor dem Senden; weicht das Ergebnis von der Quote ab, wird nicht
   gesendet.
5. Der Kill-Switch wie beim pump.fun-Bot: eine KILL-Datei stoppt alles sofort,
   Status-Dateien für die App, Meldung bei jedem Stopp.
6. Kein Code, der Geld aus der Wallet heraus bewegt. Abheben macht der Besitzer
   selbst mit seiner Sicherung.
