# Eigene Wallet, Stufe 2: unabhängiges Review

## Teil 2: der gebaute Trader, der Alpha-Modus und der Wallet-Tab (2026-10-23, Stand 87b1f52)

Geprüft wie von einem Angreifer und einem Prüfer, unter der Annahme, dass der Besitzer morgen mit echtem Geld
scharf schaltet. Gelesen: `git log -p` der Commits 7711186, ce06328 und 87b1f52 über `research/lab/lab/onchain/`,
`src/`, `server/src/`, `crates/pythia-core/src/` und `research/ops/`. Angegriffen wurden Guard, Tore, Caps,
Wiederholen, Neustart, Ledger und die Schreibwege der App. Jeder Befund hoher und mittlerer Schwere ist behoben;
sein Test in `research/lab/tests/test_onchain_review.py` scheitert ohne die Korrektur (geprüft: alle 9 rot auf
dem alten Code, grün mit der Korrektur). Keine Prüfung wurde gelockert.

### Behoben

| # | Schwere | Ort | Szenario | Korrektur, Test |
|---|---|---|---|---|
| R1 | Hoch | `lab/onchain/live_service.py:345` (`confirmed`), `live_exec.py:818` (`recover`) | Doppelt ausgeben. Die Ergebnisdatei eines Umtauschs entstand erst nach `execute`. (a) `docker stop` gibt 10 s, dann SIGKILL, während der Swap bis 150 s auf die Landung wartet; der Neustart findet Anfrage, Vorschlag und Bestätigung ohne Ergebnis und tauscht innerhalb der 75 s ein zweites Mal. (b) Ohne Neustart: wirft das Schreiben der Ledger-Zeile nach der Landung (`OSError`, Platte voll), fängt die Hauptschleife das ab, und zwei Sekunden später tauscht `converts()` dieselbe Bestätigung noch einmal. Der gesendete Swap fehlte zudem im Ledger, zählte also für keinen Tages-Cap. Entwurf B1 war im Code nicht umgesetzt. | Die Bestätigung wird vor dem Signieren exklusiv als genommen markiert (`live/onchain/taken/<id>`, wo die App nicht schreiben kann); eine genommene wird nie wieder gesendet, das Ergebnis sagt es mit Signatur. Beim Start bekommt jeder gesendete, nicht beendete und nicht gebuchte Swap aus `orders.jsonl` eine ungelesene Ledger-Zeile zur Sendezeit; er zählt sofort für die Caps, `reread()` bucht, was die Chain sagt. Tests `test_a_confirm_is_sent_once_even_when_the_round_fails_after_the_send`, `test_a_restart_reads_back_a_sent_swap_and_never_sends_the_confirm_again` |
| R2 | Hoch | `lab/onchain/live_exec.py:410` (`kill_why`), `:676` (vor `sign`) | Der Notschalter griff nicht im Signierpfad. Die Caps prüften ihn einmal vor allen Versuchen; Umtausch und Notverkauf riefen das Tor ohne den Kill-Grund (`keep_kill=False`). Drückt der Besitzer den Knopf, während der Swap gebaut und zweimal simuliert wird (mehrere Sekunden, Jupiter mit 2,1 s Abstand), oder nach einem abgelaufenen ersten Versuch, wurde trotzdem signiert und gesendet, bis zu drei Mal. Entwurf B2 verlangt die Prüfung direkt vor dem Signieren. | Unmittelbar vor jeder Signatur dieselbe Regel wie in den Caps (unter dem Notschalter nur ein Notverkauf nach USDC mit `on_kill=usdc`). Tests `test_a_kill_set_while_the_swap_is_built_stops_the_signature`, `test_a_kill_set_after_the_first_send_stops_the_retries` |
| R3 | Mittel | `lab/onchain/live_exec.py:487` (`_prices_ok`) | Die Mindestmenge hing nur an Jupiters Preisen. Jede Seite darf 2 % von Kraken abweichen und die Kosten werden gegen Jupiters Preise gerechnet; eine fehlerhafte oder kompromittierte API mit zwei je knapp 2 % schiefen Preisen lässt eine Quote durch, die zu Krakens Mittelkursen gut 4 % plus Schlupf schlechter ist (Beispiel im Test: SOL 10 statt 9,81, Mindestmenge 2,3 % unter dem Kraken-Wert). Entwurf B3 war nicht umgesetzt. | Die Mindestmenge muss auch über dem Eingabewert zu Krakens Mittelkursen abzüglich Schlupf der Klasse und 50 bps liegen, sonst wird nichts gebaut. Test `test_the_minimum_out_must_hold_at_krakens_mids` |
| R4 | Mittel | `lab/onchain/guard.py:186` (`check_program`), `live_exec.py:544` (`check_jupiter`), `live_gate.py:375` | Jupiter v6 ist aufrüstbar. Ein neuer Deploy ändert den Code, nicht das IDL-Konto; die IDL-Prüfung allein merkt nichts, der Guard vertraut aber Jupiters Programm mit der Unterschrift der Wallet. Entwurf B7 (Deploy-Slot pinnen) war nicht umgesetzt. | `python -m lab.onchain.live_exec pin` (nur lesen, verweigert ohne passendes IDL) schreibt ProgramData-Konto und Deploy-Slot nach `live/onchain/jupiter_pin.json`; ohne gültigen Pin bleibt das Tor zu; jeder Swap liest beides neu von der Chain und signiert nichts bei Abweichung. Tests `test_the_gate_needs_the_pin_and_a_new_deploy_of_jupiter_signs_nothing`, `test_the_owner_pins_jupiter_only_with_a_matching_idl` |
| R5 | Mittel | `lab/onchain/guard.py:439`, `:470` (`check_effect`) | Ein Schließen an andere, versteckt im Weg: Die Effekt-Prüfung erlaubte das Schließen des eigenen wSOL-Kontos ohne Blick darauf, wohin dessen Lamports gingen. Hält die Wallet wSOL (etwa nach einem abgebrochenen Swap) und schließt ein Programm innerhalb der Route das Konto an ein fremdes Ziel, sah die Simulation nur die Gebühr als SOL-Abfluss: bestanden, Verlust des ganzen wSOL-Bestands. | Die Lamports des geschlossenen wSOL-Kontos müssen in der Wallet ankommen, sonst "SOL fell". Test `test_a_wrapped_sol_account_closed_to_someone_else_is_refused` |
| R6 | Mittel | `lab/onchain/live_service.py:158` (`start`), `:520` (`main`) | `live_service --once` ("Tor prüfen, Status schreiben") öffnete bei offenem Tor die Wallet-Datei, schrieb einen neuen Ausgangspunkt ins Journal und handelte über `run_books` ein neues Signal. Neben dem laufenden Dienst führen so zwei Prozesse dasselbe Signal aus (doppelte Buch-Orders) und der neue Ausgangspunkt verdeckt einen Swap, der gerade landet. | `--once` öffnet die Wallet-Datei nie und handelt nie (Grund im Status); `run_books` zeigt nur, warum ein Buch handeln darf oder nicht. Test `test_once_checks_and_writes_the_status_but_never_opens_the_wallet_file` |

### Geprüft und im Code ausreichend

- **Guard gegen Abfluss:** Fremdes Token-Konto als Quelle oder Ziel, Transfer, Approve, Delegate,
  SetAuthority, Burn, Close an andere (oberste Ebene), zweiter Signierer, fremder Zahler, anderes Programm
  unter Jupiters Namen (nur die feste Programm-ID, aufgerufene Programme müssen statisch sein), ExactOut,
  Plattformgebühr, zwei Jupiter-Instruktionen, Trinkgeld über 0,0001 SOL oder ohne Sender, zweites Trinkgeld,
  fehlendes oder doppeltes Compute-Limit, Preis mal Limit über 0,0005 SOL, `RequestHeapFrame`: alles abgelehnt
  (`guard.check_message`). Lookup-Tabellen kommen von der Chain, deaktivierte werden abgelehnt (`tx.parse_table`),
  der Guard sieht die aufgelösten Konten der eigenen Bytes (`tx.decompile`). Jedes schreibbare Token-Konto der
  Wallet muss erwartet sein und ohne Delegate oder Close-Authority; Token-2022-Konten und -Mints abgelehnt. Die
  Simulation prüft Wallet und alle Token-Konten: Delegate, Besitzerwechsel, Schließen, Abfluss, auch ein
  `Assign` der Wallet selbst.
- **Tore im Signierpfad:** Den Schlüssel lädt nur `Service.start`, und nur bei offenem Tor; vor jedem Versuch
  läuft das ganze Tor neu (Umgebung, Ack mit Höchstwerten im Code, Wallet-Datei, Simulation unter 24 h, IDL,
  jetzt Pin, Endpunkte), ein geschlossenes Tor schaltet den Dienst bis zum Neustart ab.
- **Alpha-Modus:** nur der Nachweis entfällt; `Ack.cap` nimmt nie mehr als `ALPHA_MAX_*`, Werte darüber machen
  das Ack ungültig; aufgeteilte Buch-Orders bleiben einzeln unter 98 % des Swap-Caps und gehen durch alle Caps.
- **App und Server:** schreiben nur `request`, `confirm` (Zeit und Mindestmenge aus dem Vorschlag des Dienstes)
  und `KILL`; Betrag nur endlich und positiv; Caps, Tagesrest und Mindestmenge prüft der Dienst selbst. Kein
  Schlüssel, keine Signatur, kein Weg, den Notschalter zu löschen.
- **Geheimnisse:** RPC- und Sender-URL (mit API-Schlüssel) stehen in keiner Fehlermeldung, keinem Status und
  keiner Karte; Jupiters Schlüssel nur als Header. Telegram und Discord bekommen Beträge, öffentliche Adresse
  und Signatur.
- **Korrektheit:** Rohbeträge je Mint aus den Ganzzahlen der Chain, Dezimalstellen gegen Jupiters Liste;
  ExactIn ist atomar (keine Teilfüllung); ein Ablauf zählt erst nach `confirmed`-Blockhöhe über
  `lastValidBlockHeight` und einer Statusabfrage mit `searchTransactionHistory` (Entwurf B4); "kein Status nach
  150 s" wird nie wiederholt; fehlgeschlagene Swaps buchen ihre Gebühr; Tag und Gesamt aus dem Ledger neu
  gerechnet.

### Offen, niedrige Schwere

| # | Ort | Szenario |
|---|---|---|
| R7 | `lab/onchain/live_service.py:301` (`propose`) | Ein Betrag `Infinity` in einer Anfrage (der Server lässt ihn nicht durch, nur eine von Hand geschriebene Datei) wirft `OverflowError` an der Behandlung vorbei; die Anfrage wird 10 min lang alle 2 s erneut versucht und läuft dann ab. Kein Swap. |
| R8 | `lab/onchain/guard.py:261` (Token-2022) | Abweichung vom Entwurf B5: Die Programm-ID von Token-2022 in der Nachricht wird nicht abgelehnt (Raydium CLMM und andere führen sie auch bei klassischen Mints). Abgelehnt werden Token-2022-Mints, jedes bestehende schreibbare Token-2022-Konto und jede Änderung eigener Token-2022-Konten; ein Transfer-Hook bekommt keine Signer-Rechte, eine Transfer-Gebühr kürzt nur die Ausgabe, die Mindestmenge hält. |
| R9 | `lab/onchain/guard.py:313` | Mehrere Wrap-Überweisungen ins eigene wSOL-Konto, jede höchstens der Eingabebetrag (Entwurf N9 nur halb): das Geld bleibt im eigenen Konto, die Effekt-Prüfung begrenzt den SOL-Abfluss. |
| R10 | `lab/onchain/live_exec.py:671` (`prepare` bis `sign`) | Kein Höchstalter zwischen `/build` und Signatur (Entwurf N8); bei langsamem RPC einige zehn Sekunden. Die Mindestmenge begrenzt den Schaden. |
| R11 | `lab/onchain/live_exec.py:299` (`read_view`) | Gesamtwert und Tagesverlust zu Jupiters Preisen ohne Kraken-Gegenprobe (Entwurf N6); der Swap selbst wird gegen Kraken geprüft. |
| R12 | `lab/onchain/live_service.py:182` (`start`) | Jeder Start nimmt die Guthaben als neuen Ausgangspunkt: eine Differenz aus der Zeit, in der der Dienst stand, wird nicht gemeldet; ein Swap, der nach einem Absturz erst nach dem neuen Ausgangspunkt landet, erscheint als ungeklärt und sperrt Käufe bis zum nächsten Start (sicher, aber laut). |
| R13 | `lab/onchain/live_exec.py:634` (`_read_back`) | Bei SOL als Eingabe oder Ausgabe enthalten `in_raw`/`out_raw` im Ledger Trinkgeld und Kontomiete; der Abgleich nutzt `sol_delta_l` und stimmt, nur die Buchmenge des Buchs weicht um Bruchteile ab. |
| R14 | `lab/onchain/live_service.py` (`run_books`) | Scheitert das Schreiben von `books.json` still und stirbt der Dienst danach, handelt ein Neustart dasselbe Signal noch einmal; die gesendeten Swaps stehen dann als ungelesene Zeilen im Ledger, aber noch nicht im Buchstand. |
| R15 | `lab/onchain/live_exec.py:655` (`execute`) | Ohne `gate_why` prüft `execute` das Tor nicht erneut; der Dienst übergibt es immer, ein anderer Aufrufer müsste es auch. |

### Der pump.fun-Bot

Unberührt: keine Datei unter `lab/pumpfun_rt/` geändert. Seine Tests (`tests/test_pumpfun*.py`, 293 bestanden,
1 übersprungen) laufen grün.

## Teil 1: Review des Entwurfs (vor dem Bau)

Geprüft wie von einem Angreifer und einem Prüfer, unter der Annahme, dass der Besitzer morgen mit echtem Geld
scharf schaltet. Gelesen: alle Commits, die `research/lab/lab/onchain/`, `src/`, `server/src/`,
`crates/pythia-core/src/` und `research/ops/` seit Stufe 1 berühren (`git log -p`), `docs/ONCHAIN.md`,
`docs/ONCHAIN-STAGE2.md`, die Vorab-Registrierung und zum Vergleich die Tore des pump.fun-Bots.

### Das Wichtigste zuerst: Es gibt noch keinen Echtgeld-Trader

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

### Behoben im Code (Stufe 1)

| # | Schwere | Ort | Szenario | Korrektur, Test |
|---|---|---|---|---|
| C1 | Mittel | `lab/onchain/jupiter.py:146` (`quote`), `:57` (`parse_quote`) | Die Antwort wurde nicht mit der Anfrage verglichen. Eine Antwort für ein anderes Paar (BONK statt SOL), einen größeren `inAmount` oder ExactOut wurde gebucht: falsche Münze mit falschen Dezimalstellen, mehr USDC ausgegeben als vorhanden, negative Bestände. Ein nicht numerischer Betrag warf `ValueError` an den Handlern des Buchs vorbei und brach den Tageslauf ab. | Paar, Betrag, ExactIn und `outAmount > 0` werden geprüft, sonst `QuoteError` (die Münze bleibt, wie sie ist); kaputte Felder sind `QuoteError`. Tests `test_a_quote_for_another_pair_amount_or_mode_is_refused`, `test_a_wrong_answer_leaves_the_account_alone` |
| C2 | Mittel | `lab/onchain/book.py:156` (`mids`) | Jupiters USD-Preis von USDC teilt jede Bewertung, ohne Prüfung. Ein Ausreißer (0,2 statt 1,0) schrieb das Fünffache des Kontos ins Journal; genau dieses Journal liest der Nachweis B der Vorab-Registrierung. | Außerhalb von 0,98 bis 1,02 wird nichts bewertet und nichts journalisiert (`QuoteError`, der Job meldet den Fehler). Test `test_a_usdc_price_off_its_peg_marks_nothing` |

### Im Entwurf geschlossen (`docs/ONCHAIN-STAGE2.md`, Zeilen nach Stand ccbdf9a)

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

### Offen, niedrige Schwere

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

### Der pump.fun-Bot

Unberührt: keine Datei unter `lab/pumpfun_rt/` geändert. Seine Tests (`tests/test_pumpfun*.py`) laufen grün.
