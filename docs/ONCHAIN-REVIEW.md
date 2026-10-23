# Eigene Wallet, Stufe 2: unabhängiges Review (2026-10-23)

Geprüft wie von einem Angreifer und einem Prüfer, unter der Annahme, dass der Besitzer morgen mit echtem Geld
scharf schaltet. Gelesen: alle Commits, die `research/lab/lab/onchain/`, `src/`, `server/src/`,
`crates/pythia-core/src/` und `research/ops/` seit Stufe 1 berühren (`git log -p`), `docs/ONCHAIN.md`,
`docs/ONCHAIN-STAGE2.md`, die Vorab-Registrierung und zum Vergleich die Tore des pump.fun-Bots.

## Das Wichtigste zuerst: Es gibt noch keinen Echtgeld-Trader

Der letzte Commit (ccbdf9a, "On-chain stage 2 design") ist **nur ein Entwurf**: `docs/ONCHAIN-STAGE2.md` und
`research/lab/results/onchain_stage2_prereg.md`. Es gibt kein `guard.py`, kein `live_exec.py`, keinen
Live-Dienst, keine Server-Endpunkte und keine App-Seite für die eigene Wallet. Im Code geprüft:

- `lab/onchain/` (Stufe 1) enthält keinen Schlüssel, kein Signieren, kein Senden und keinen Aufruf von
  `/swap`; `test_nothing_in_the_package_signs_or_sends` sichert das ab.
- `server/src/` und `crates/pythia-core/src/` haben keinen Endpunkt, der für diese Wallet schreibt. Die
  Wallet-Ansicht (`wallets.rs:329`) liest nur Guthaben beobachteter Adressen. Die einzigen schreibenden
  Endpunkte der Echtgeld-Seite gehören dem pump.fun-Bot und schreiben nur `live_settings.json` und `KILL`
  (`pumpfun_live.rs:495`, `:544`).
- Es kann also morgen nichts mit echtem Geld auf der Chain handeln. Scharfschalten ist erst nach den
  Bauaufgaben 1 bis 9 und dem Nachweis der Vorab-Registrierung möglich.

Darum ist das Review zweigeteilt: Der **Entwurf** wurde so angegriffen, als wäre er gebaut (die Lücken sind im
Entwurf geschlossen und als Pflichttests in den Bauplan geschrieben, weil es noch keinen Code gibt, an dem ein
Test scheitern könnte). Der **Code von Stufe 1** (Paper-Buch, Quote-Client, Mint-Liste), auf dem Stufe 2 laut
Entwurf aufbaut, wurde auf Korrektheit geprüft; seine Befunde mittlerer Schwere sind behoben, mit Tests, die
vor der Korrektur scheitern.

## Behoben im Code (Stufe 1)

| # | Schwere | Ort | Szenario | Korrektur, Test |
|---|---|---|---|---|
| C1 | Mittel | `lab/onchain/jupiter.py:146` (`quote`), `:57` (`parse_quote`) | Die Antwort wurde nicht mit der Anfrage verglichen. Eine Antwort für ein anderes Paar (BONK statt SOL), einen größeren `inAmount` oder ExactOut wurde gebucht: falsche Münze mit falschen Dezimalstellen, mehr USDC ausgegeben als vorhanden, negative Bestände. Ein nicht numerischer Betrag warf `ValueError` an den Handlern des Buchs vorbei und brach den Tageslauf ab. | Paar, Betrag, ExactIn und `outAmount > 0` werden geprüft, sonst `QuoteError` (die Münze bleibt, wie sie ist); kaputte Felder sind `QuoteError`. Tests `test_a_quote_for_another_pair_amount_or_mode_is_refused`, `test_a_wrong_answer_leaves_the_account_alone` |
| C2 | Mittel | `lab/onchain/book.py:156` (`mids`) | Jupiters USD-Preis von USDC teilt jede Bewertung, ohne Prüfung. Ein Ausreißer (0,2 statt 1,0) schrieb das Fünffache des Kontos ins Journal; genau dieses Journal liest der Nachweis B der Vorab-Registrierung. | Außerhalb von 0,98 bis 1,02 wird nichts bewertet und nichts journalisiert (`QuoteError`, der Job meldet den Fehler). Test `test_a_usdc_price_off_its_peg_marks_nothing` |

## Im Entwurf geschlossen (`docs/ONCHAIN-STAGE2.md`, Zeilen nach Stand ccbdf9a)

| # | Schwere | Ort | Szenario | Jetzt im Entwurf |
|---|---|---|---|---|
| B1 | Hoch | `ONCHAIN-STAGE2.md:233` (Umtausch), `:330` (Wiederholen) | Doppelt ausgeben nach Neustart: Der Dienst stürzt ab, nachdem eine Umtausch-Bestätigung gesendet wurde, aber bevor die Anfrage-Datei weg ist. Beim Start liegt eine gültige Bestätigung da, der Dienst tauscht ein zweites Mal. Ebenso eine Buch-Order, deren Signatur nirgends steht. | Vorschlag mit zufälliger ID des Dienstes, Bestätigung einmal verbraucht und vor dem Signieren ins Ledger geschrieben; Signatur, Blockhash und `lastValidBlockHeight` stehen vor dem ersten Senden im Ledger; ein Neustart klärt offene Signaturen, bevor er Neues baut. Pflichttests in Aufgabe 6 |
| B2 | Hoch | `:291` (Notschalter) | Der Notschalter stoppte nur Käufe. Ist der Guard oder Jupiters API der Grund für den Notschalter, laufen Verkäufe, Rebalance-Verkäufe und Umtausch nach USDC weiter durch genau diesen Weg. | `KILL` sperrt jedes Signieren, geprüft im Signierpfad direkt davor; Verkauf nach USDC nur mit ausdrücklichem `on_kill=usdc`. Pflichttest in Aufgabe 5 |
| B3 | Hoch | `:131` (Jupiter-Regel) | Die Mindestmenge kam aus Jupiters eigener Quote. Eine kompromittierte oder fehlerhafte API liefert eine schlechte Quote mit passend niedriger Mindestmenge; Guard und Simulation (die nur gegen die Mindestmenge prüft) lassen sie durch, Verlust bis zum ganzen Trade. | Die Mindestmenge muss zusätzlich über dem Eingabewert zum Kraken-Mittelkurs abzüglich Schlupf der Klasse und 50 bps liegen. Pflichttest in Aufgabe 3 |
| B4 | Mittel | `:315`, `:330` (Blockhash, Ablauf) | Die Order gilt als abgelaufen, sobald irgendeine Blockhöhe über `lastValidBlockHeight` liegt; eine spät gemeldete Landung (anderer Blockhash als der geprüfte, andere Commitment-Stufe, Status kommt verzögert) führt zu neuer Quote und einem zweiten Kauf. | Ein Blockhash, der signierte; Blockhöhe mit `confirmed`; danach `getSignatureStatuses` mit `searchTransactionHistory`, erst dann gilt die Order als nicht gelandet. Pflichttest in Aufgabe 6 |
| B5 | Mittel | `:165` (Token-2022) | Token-2022 als Zwischen-Token wurde am `routePlan` erkannt, also an Daten der API. Eine API, die lügt, versteckt eine Mint mit Transfer-Hook oder Gebühr. | Abgelehnt, sobald die Programm-ID von Token-2022 unter den Konten der Nachricht steht (auch aus Lookup-Tabellen). Pflichttest in Aufgabe 3 |
| B6 | Mittel | `:127` (ComputeBudget) | "Preis x Limit <= 0,0005 SOL" lässt sich nicht prüfen, wenn kein `SetComputeUnitLimit` dabei ist; ein hoher Preis mit dem Standardlimit (bis 1,4 Mio. CU) ging durch. | Genau ein Limit und genau ein Preis, sonst abgelehnt; `RequestHeapFrame` und `SetLoadedAccountsDataSizeLimit` verboten. Pflichttest in Aufgabe 3 |
| B7 | Mittel | `:115` (IDL-Prüfung) | Jupiter v6 ist aufrüstbar. Ein Upgrade ändert den Code, nicht das IDL-Konto; die IDL-Prüfung allein merkt nichts. | Der Guard pinnt den Deploy-Slot im ProgramData-Konto und signiert bei Abweichung nichts, bis der Besitzer bestätigt; Kontopositionen je Instruktion (`route_v2` und `shared_accounts_route_v2` unterscheiden sich). Pflichttest in Aufgabe 3 |
| B8 | Mittel | `:280` (Werte der App), `:233` (Betrag des Umtauschs) | Ein NaN aus der App als Grenze: `min(ack, NaN)` und `Betrag > NaN` sind in Python je nach Reihenfolge NaN bzw. falsch, der Cap greift nicht. Ein Umtauschbetrag, den nur der Server prüft. | App-Werte nur als endliche Zahl > 0 (wie `live_exec.read_settings`), sonst der Ack-Wert; der Dienst prüft den Betrag selbst gegen Caps und Tagesrest. Pflichttests in Aufgabe 5 |

Geprüft und im Entwurf ausreichend: kein Transfer, Approve, SetAuthority oder Close an andere im Guard; ATA nur
für die eigene Wallet und erlaubte Mints; Lookup-Tabellen werden selbst von der Chain gelesen; statischer
Eigentumsnachweis jedes beschreibbaren Token-Kontos plus Effekt-Prüfung der Simulation (fängt auch einen
fremden Programmaufruf innerhalb von Jupiter ab); Trinkgeld höchstens eins und 0,0001 SOL an ein Konto aus
`txbuild.HELIUS_TIP_ACCOUNTS`; Teilfüllungen gibt es bei ExactIn-Swaps nicht (atomar), Reste in
Zwischen-ATAs bucht das Ledger; Tages- und Gesamtergebnis aus dem Ledger neu berechnet; Schlüssel nur als
Datei mit Rechten 600, nie in Umgebung, Log oder Status; Abheben bleibt außerhalb von Pythia.

## Offen, niedrige Schwere

| # | Ort | Szenario |
|---|---|---|
| N1 | `lab/onchain/mints.py:55` (`raw`) | Das `+1e-6` gegen Gleitkommafehler rundet einen wahren Wert knapp unter einer ganzen Einheit (x,9999995) um eine Roh-Einheit auf. Im Paper harmlos; Stufe 2 muss Roh-Beträge aus den Ganzzahlen der Chain nehmen, nie aus Gleitkomma-Beständen. |
| N2 | `lab/onchain/paper.py:41` | Die Paper-Priority-Fee aus der Umgebung darf bis 0,01 SOL, der Entwurf deckelt bei 0,0005. Nur Paper-Kosten. |
| N3 | `lab/onchain/book.py:357` bis `:362` | Journal-Zeile vor `state.json`: Stirbt der Lauf dazwischen, zählt der Tag als gehandelt, aber der Zustand trägt die Fills nicht. Selten, verfälscht B2 der Vorab-Registrierung um höchstens einen Tag. |
| N4 | `lab/onchain/jupiter.py:131` | `http.client.IncompleteRead` und andere `HTTPException` sind keine `OSError` und brechen den Job ab statt eines neuen Versuchs. |
| N5 | `lab/onchain/book.py:150` | NaN oder Inf als Gewicht im Signal werden nicht verworfen; Folge: stilles Nichtstun für diese Münze. |
| N6 | Entwurf, Abschnitt 4 | Tagesverlust zu Jupiter-Preisen; bei dünnen Münzen (POPCAT, RENDER) verschiebbar. Die 2-%-Gegenprobe gegen Kraken sollte auch für die Bewertung des Tagesverlusts gelten. |
| N7 | Entwurf, Abschnitt 1 | Lookup-Tabellen, die deaktiviert werden, sollten abgelehnt werden. |
| N8 | Entwurf, Abschnitt 5 | Kein Höchstalter zwischen `/build` und erstem Senden genannt (Vorschlag 15 s); die Mindestmenge begrenzt den Schaden. |
| N9 | Entwurf, Abschnitt 1 | Der Wrap-Betrag (System-Überweisung ins eigene wSOL-Konto) muss genau dem Eingabebetrag des Swaps entsprechen. |
| N10 | Entwurf, Abschnitt 5 | `PYTHIA_JUPITER_API_KEY` nur als Header, nie in der URL; `jupiter.get` setzt heute alle Parameter in die URL. |

## Der pump.fun-Bot

Unberührt: keine Datei unter `lab/pumpfun_rt/` geändert. Seine Tests (`tests/test_pumpfun*.py`) laufen grün.
