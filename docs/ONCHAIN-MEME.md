# Eigene Wallet: das Meme-Modul (Memecoins über Jupiter, erst Papier)

**Stand 2026-10-23.** Unsere eigene Wallet (Stufe 2, `docs/ONCHAIN-STAGE2.md`) kann jetzt auch Memecoins
handeln, ohne pump.fun-Programme: Coins auf Raydium (mit LaunchLab/LetsBonk), Meteora (mit dem Dynamic Bonding
Curve), Orca und PumpSwap, alle über Jupiter. Der pump.fun-Bot bleibt, wie er ist. Alles läuft **auf Papier**;
der Echtgeld-Weg ist gebaut und **gesperrt**, bis eine Regel ihren vorab registrierten Nachweis bestanden hat
und du sie im Ack freigibst.

## Was es tut

Alle 2 Minuten (Job `onchain-meme`, `python -m lab.onchain.meme`):

1. **Kandidaten** aus unserer Trends-Datei (`reports/pumpfun_rt/trends.json`: frische Pools und heiße
   migrierte Coins, mit den Badges der Y9-Modelle), aus DexScreeners Boosts und Profilen auf Solana und aus
   Jupiters öffentlichen Trend-Listen (`toptrending`, `toporganicscore`).
2. **Sicherheitsprüfung pro Coin** (unten), bevor eine Regel einen Coin überhaupt quotet.
3. **Drei Papierbücher**, eins je Regel (`paper/onchain_meme_<regel>/`): 1 SOL, 0,1 SOL je Kauf, gefüllt zur
   echten Jupiter-Quote minus Netzwerk- und Priority-Gebühr (der Papier-Executor aus Stufe 1). Ausstiege werden
   bei jedem Lauf gegen eine echte Verkaufsquote geprüft. Journal wie die anderen Papierbücher: Forward-Report,
   Lab-Seite und Briefing zeigen sie. Stand der Bücher: `reports/onchain_meme/books.json`.

Täglich (Job `onchain-meme-proof`) schreibt `python -m lab.onchain.meme --proof` den Nachweis nach
`reports/onchain_meme/proof.json` und `latest.md`.

## Die Sicherheitsprüfung (`lab/onchain/meme_safety.py`)

Ein Coin besteht nur, wenn alles gilt; jede Ablehnung nennt ihren Grund in Worten:

- Mint-Konto auf der Chain: klassisches SPL-Token (**Token-2022 wird abgelehnt**, wie im Guard, mit Namen der
  Erweiterungen wie Transfer Fee oder Transfer Hook), keine Mint Authority, keine Freeze Authority (Ausnahme
  nur für Mints in deiner Liste `/etc/pythia/meme-exceptions.txt` oder `<data>/onchain/meme-exceptions.txt`,
  und nur für diese zwei Punkte)
- bester Pool auf Raydium, LaunchLab, LetsBonk, Meteora, Orca oder PumpSwap (nie die pump.fun-Kurve) mit
  mindestens **20.000 USD** Liquidität
- die 10 größten Halter (ohne Pools, Programm-Konten und Burn-Adressen) halten **unter 30 %**
- der erste Pool ist mindestens **5 Minuten** alt
- weder der Mint noch sein Ersteller steht auf deiner Sperrliste (`/etc/pythia/blocked-mints.txt` und die
  Lab-Kopie, ein Mint je Zeile, `creator:<adresse>` für einen Ersteller)

Jupiters Token-API liefert dazu Verified/Strict, Organic Score und Liquidität für den Bericht. Das Urteil wird je
Mint mit Zeit gespeichert (`<data>/onchain/meme/safety.json`). Von Hand: `python -m lab.onchain.meme_safety <mint>`.

**Wichtig:** Die meisten neuen pump.fun-Coins sind heute Token-2022 (Metadata Pointer, manche mit Transfer
Fee). Sie fallen durch die Prüfung. Das ist gewollt: der Guard der Wallet lässt Token-2022 nicht zu.

## Die Regeln (vorab registriert: `research/lab/results/onchain_meme_prereg.md`, 3 Versuche)

| Regel | Einstieg | Ausstieg |
|---|---|---|
| `fresh_win` | frischer Pool aus der Trends-Datei, 5 bis 30 Min nach der Migration, Badge `win_high`, kein `rug_risk` | +50 %, Stopp -25 %, Trailing 20 % ab +20 %, 2 h, Liquidität -50 % |
| `momentum_trail` | Pool mindestens 1 Tag alt, mindestens 50.000 USD, +5 % in 1 h und +20 % in 24 h | Stopp -15 %, Trailing 15 %, 24 h, Liquidität -40 % |
| `organic_trend` | Jupiters Organic-Liste, Score mindestens 80, im Plus über 1 h und 24 h, Pool 1 Tag alt | +30 %, Stopp -10 %, Trailing 10 % ab +5 %, 12 h, Liquidität -40 % |

Für alle: nichts mit `rug_risk`, derselbe Coin höchstens einmal in 24 h, höchstens 5 offen.

## Der Nachweis

Je Regel allein, alles muss gelten: mindestens 30 Tage und 100 geschlossene Trades, mittlere Rendite je Trade
über 0 mit dem unteren Ende des 90-%-Bootstrap-Bands über 0, Gewinn nicht von 5 Trades getragen und mindestens
die Hälfte der Tage im Plus, deflationierte Wahrscheinlichkeit über 0,95 gegen den globalen Pool (1.896
Versuche), höchstens 5 % geplanter Käufe und Verkäufe ohne Quote. Der Nachweis schaltet nie etwas scharf.

## Der Echtgeld-Weg (gesperrt, `lab/onchain/meme_live.py`)

Ein Meme-**Kauf** braucht zusätzlich zu jedem Tor der Stufe 2 (Guard, Simulation, Notschalter, nur eigene
Konten, kein Transfer nach außen): deinen `[meme]`-Abschnitt im Ack mit der Regel, den bestandenen Nachweis
(höchstens 36 h alt; auch im Alpha-Modus), eine bestandene Sicherheitsprüfung dieses Mints **aus der letzten
Minute** (vor jedem Versuch neu), SOL-Preis höchstens 2 % neben Kraken, den Coin-Preis höchstens 5 % neben
seinem besten Pool, Kosten höchstens 150 bps. Die Freigabeliste für Meme-Mints ist allein das Urteil der
Prüfung. Höchstwerte im Code (der Ack kann nur senken): **50 USD** in Memecoins insgesamt, **10 USD** je Swap,
**10 USD** Meme-Verlust am Tag, 20 Meme-Swaps am Tag. Der Live-Dienst folgt dem Papierbuch: ein neuer
Papier-Einstieg (höchstens 5 Min alt) wird einmal gekauft, schließt das Papierbuch die Position, wird verkauft.
Ein **Verkauf** braucht den Ack-Abschnitt und den Guard, aber keine frische Prüfung (damit ein Coin mit
schwindendem Pool noch verkauft werden kann), Kosten höchstens 500 bps. Unter dem Notschalter swappt nichts.

## Scharfschalten (erst wenn `reports/onchain_meme/proof.json` für die Regel `passed: true` zeigt)

1. Stufe 2 muss laufen (`docs/ONCHAIN-STAGE2.md`, Abschnitt 7: Wallet, IDL, Pin, Simulation, Dienst).
2. Neuen Code bereitstellen: `research/ops/deploy_live.sh`.
3. Am Ende von `/etc/pythia/onchain-live-ack` (Rechte 600) den Abschnitt ergänzen:

   ```
   [meme]
   rules=organic_trend
   max_total_usd=30
   max_trade_usd=5
   max_daily_loss_usd=5
   ```

4. Dienst neu starten (`docker restart pythia-onchain-live`). `python -m lab.onchain.live_service --once`
   und die App (Status, Feld `memes`) zeigen je Regel, warum sie handeln darf oder nicht.
5. Stoppen: Notschalter wie in Stufe 2, oder den `[meme]`-Abschnitt löschen und neu starten. Gehaltene
   Memecoins bleiben dann liegen; verkaufen kannst du sie über das Backup in deiner eigenen Wallet.
