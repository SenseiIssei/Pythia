# W3: the weekly page's paper line by the capital rule, pre-registration

Pre-registered 2026-11-23, before the code that makes the line and before its first run. From the review
`results/review_2026-10-27.md` (sections 2 and 3), R5's registry, R6's windows, the readiness ladder (`lab.ops.ladder`)
and W2's capital rule (`results/weekly_capital_line_prereg.md`).

## Why

The paper line of the weekly page (`lab.ops.weekly`, `reports/weekly/latest.md`) sums every paper book's wallet change
in EUR and SOL against the snapshot of the week before, times 30/7. On 2026-11-22 it read "Papier: Woche +141,13 EUR
über 23 Bücher, auf 30 Tage +604,83 EUR, zum Ziel fehlen 0,00 EUR". Most of that is P_pool0_10eur compounding 10 EUR
to 322 EUR at half its wallet a trade (`reports/pumpfun_rt/realistic.md`), a stake no live cap allows, and before
P2's paper-minus-live gap of +8.8 points a trade. The capital line under it already follows W2's rule (never from
wallet growth); the paper line on top did not.

## The rule

The paper line takes W2's arithmetic per paper book, unchanged, and sums money a month instead of capital:

1. **Books.** Every paper book of `lab.ops.paper_books` (the books the old line summed, the forward books and the
   on-chain book with them).
2. **Record and band, as W2.** A book counts only with at least 30 days of record (W2's step 1: its days since its
   start, a forward book at most the days it ran on, a 10 EUR book its `days`) and a band (W2's step 2: at least 2
   steps of its dated reports; a 10 EUR book its `band` per entry, P2's gap, the ack's cap and `sol_eur`). R2's and
   F3's SOL books carry no band and do not count.
3. **Its figure a month.**
   - A paper book: W2's lower monthly band, less W2's fill gap (step 4), times the money paid into it in EUR (the
     `paid_eur` or `capital_eur` of its newest point in its dated reports), not its grown value. A book without
     money paid in EUR (a forward book in % since start, the on-chain book in USDC) has no stake in EUR and is not
     added.
   - A pump.fun 10 EUR book: per trade, never from wallet growth: (the lower end of its band per entry minus P2's gap,
     `selection.pts`) x its stake x `sol_eur` x its trades a month (entries over days x 30). Its stake is its real
     capped stake: the live cap (`ack.max_trade_sol` in `reports/pumpfun_rt/live_status.json`), or P3's share of the
     wallet (0.5, `realistic.TEN_SHARE`) times its wallet now where that is less (a wallet that shrank stakes less;
     one that grew stakes no more than the cap).
4. **The line.** "Papier nach der Kapital-Regel": the sum of these figures a month over the books that count, and
   180 EUR less the sum as what is missing to the goal. A figure below 0 is added as it is: leaving it out would be
   a selection. The books that count are named with their figure; the others are counted and named by why ("unter
   30 Tagen", "ohne Band", "ohne Einsatz in EUR"), not added. The Telegram summary carries the new sum.
5. **Wallet growth stays, labelled.** The old figure (the week's wallet change, times 30/7; on the first page since
   the start) stays as a second line "Wallet-Wachstum, zählt nicht", with no gap to the goal and not in the Telegram
   summary.

The 30 days, the 95 % band, P2's gap, the cap, P3's share and the fill gap are W2's and P3's, fixed before this line
and not chosen on its numbers; the inputs are read from the reports each week. The progress page shows the weekly
page's first lines as text (`lab.ops.progress`, `src/progress.ts`) and so shows the new line without a change.

## Trials

None. The line tests no strategy, picks no variant and fits nothing: it restates the reports' records with W2's
fixed arithmetic. R5's registry (`trials/registry.jsonl`) does not change; family none. No performance number is
written here. Nothing a live bot, a wallet or the engine reads changes.

## Checks

Tests on synthetic reports for each branch: no book counts, one book counts (its lower band times its money paid
in), a 10 EUR book with P2's gap applied, a 10 EUR book whose stake is cut to the cap, one whose shrunk wallet stakes
less than the cap, a book without a stake in EUR named and not added, the wallet growth line labelled. Then the page
is rerun on the server's reports of 2026-11-23 into a scratch folder, the old and the new paper line side by side;
no other line of the page may change.
