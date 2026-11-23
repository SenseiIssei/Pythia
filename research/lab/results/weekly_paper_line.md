# W3: the weekly page's paper line by the capital rule, result

Pre-registered in `results/weekly_paper_line_prereg.md` (its own commit), code in `lab/ops/weekly.py` (`paper_month`),
tests in `tests/test_weekly.py`. No trial: arithmetic on the reports, no selection; R5's registry unchanged.

## Rerun

The page rebuilt on the server's reports of 2026-11-23 for the page date 2026-11-22 (the week against
`reports/weekly/2026-11-15.json`), old code and new code on the same reports. Only the paper line changes; every
other line of the page is the same.

Old:

    Papier: Woche +152,59 € über 23 Bücher in EUR und SOL, auf 30 Tage +653,96 €, zum Ziel fehlen 0,00 €

New:

    Papier nach der Kapital-Regel: +0,00 € im Monat aus 0 Büchern mit 30 Tagen und Band (untere Grenze des
    95-%-Bands mal eingezahltes Geld; pump.fun je Trade minus P2s Lücke beim Einsatz von höchstens 0,05 SOL),
    zum Ziel fehlen 180,00 €
    Papier, nicht addiert: 28 unter 30 Tagen (...); 4 ohne Band (P_pool5_top30t_sw10o3n, P_pool5_top30t_sw10o2n,
    P_pool5_top30t_sw10o1n, P_pool0_wait_10eur); 19 ohne Einsatz in EUR (tsmom, tsmom_regime, ...)
    Wallet-Wachstum, zählt nicht: Woche +152,59 € über 23 Bücher in EUR und SOL, auf 30 Tage +653,96 €

Telegram: "Papier: Woche +152,59 €, Monat +653,96 €" becomes "Papier (Kapital-Regel): Monat +0,00 € aus 0 Büchern,
fehlen 180,00 €"; wallet growth is not in the summary.

No book counts today. P_pool0_10eur, most of the old figure, has 25 days of record (P3), under 30. The books with 30
days and a band (m4_perps among them) are forward books in % since start, with no money paid in EUR: named, not
added. The small-account and ETF books are under 30 days. R2's books and P_pool0_wait_10eur carry no band.

## For a ui task

The progress page (`lab.ops.progress`, `src/progress.ts`) shows the weekly page's first 12 lines as text and parses no
number from them: it shows the new line and the labelled wallet growth line without a change. Nothing for the app.
