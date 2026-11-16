# W2: an honest capital line on the weekly page, pre-registration

Pre-registered 2026-11-16, before the code that makes the line and before its first run. Second attempt of lane 12023
(weekly-capital-line-honest, 2026-11-02, stopped without a run). From the review `results/review_2026-10-27.md`
(sections 2 and 3), R5's registry, R6's windows and the readiness ladder (`lab.ops.ladder`).

## Why

W1's page (`lab.ops.weekly`, `results/weekly_page_w1_prereg.md`) gives each ladder candidate "the capital for 180 EUR
a month" as 180 EUR over its paper return since start times 30 over its days. On 2026-11-15 that printed 4.76 EUR for
P_pool0_10eur (a 10 EUR pump.fun wallet compounding for 19 days) and 1,282 EUR for m4_perps (26 days). The figure
ignores the noise of a short record, the measured gap between paper and live, the fill gap a book has measured and
how much a pump.fun rule may stake a trade. Section 3 of the review: a 30-day record only catches bugs.

## The rule

The capital line replaces W1's. Everything else on the page stays as it is. For each candidate on the ladder:

1. **Record.** A candidate gets a capital figure only with at least 30 days of record: a paper book's days since its
   start (`lab.ops.paper_books`), a pump.fun 10 EUR book's `days` (P3, `reports/pumpfun_rt/realistic.json`), a pump.fun
   rule's `days_record` (`reports/ladder/latest.json`). Under 30 days the page counts it as "unter 30 Tagen".
2. **Lower band, not the point.** A book's monthly return is the lower end of the 95 % band of its mean daily return,
   times 30: the book's value on each dated report of its own report folder (`reports/<folder>/<date>.json`, only the
   points since its current start), each step's return net of money paid in (`paid_eur`, `capital_eur`,
   `start_usdc`) divided by its days, then 30 x (mean - 1.96 x sd / sqrt(n)). Fewer than 2 steps: no band, counted as
   "ohne Band".
3. **pump.fun per trade, never wallet growth.** A pump.fun rule or 10 EUR book is scored per trade: the lower end of
   its 95 % band of the mean per entry after costs (P3's `band`, the ladder's `lo`) minus P2's paper-minus-live gap
   (`selection.pts` in `realistic.json`, +8.8 points a trade on 2026-11-15), times its trades a month (entries over
   record days times 30), at the live stake cap (`ack.max_trade_sol` in `reports/pumpfun_rt/live_status.json`, in EUR
   at `realistic.json`'s `sol_eur`). The most it can make a month is that lower edge x cap x trades a month. If it is
   below 180 EUR the result is "nicht erreichbar" (no capital reaches 180 EUR under the cap). Else the stake a trade
   that makes 180 EUR, over the ack's `stake_share` (the wallet that stakes that much at the live share), is the
   capital. R2's pump.fun books carry no band per entry and count as "ohne Band". Without P2's gap, the ack's cap or
   `sol_eur` no pump.fun figure is given.
4. **Fill gap.** A forward book with a measured fill gap (`costs.ratio` above 1 and not `modelled_only` in
   `reports/forward/latest.json`, the table `reports/forward/latest.md` prints; m4_hl_small showed 1.5x to 1.8x) loses
   its modelled costs a month times (ratio - 1) from its lower band: `costs.model_pct` / 100 x 30 / its days x
   (ratio - 1). A ratio below 1 adds nothing.
5. **Result.** "keins" when the discounted lower band (per month, or per entry for pump.fun) is not above 0;
   "nicht erreichbar" as in 3; else the capital: 180 EUR over the discounted monthly lower band, or the pump.fun
   capital of 3. The cheapest five are printed with their source file, the others counted. The page says in one
   sentence which rule made the numbers and points to this file.

The 30 days, the 95 % band (1.96, normal), P2's gap, the cap and the fill gap are fixed here, not chosen on the
numbers. The inputs (P2's gap, the cap, the ratio) are read from the reports each week, not copied into the code.

## Trials

None. The line tests no strategy, picks no variant and fits nothing: it restates the reports' records with the fixed
arithmetic above, and it can only lower or remove a figure W1 printed. R5's registry (`trials/registry.jsonl`) does
not change; family none. No performance number is written here.

## Checks

Tests on synthetic reports for each branch: a record under 30 days, a lower band not above 0, a pump.fun rule scored
per trade (a figure, and a wallet that grew but whose discounted band is not above 0), a fill gap that lowers a figure
and one that removes it, a stake cap that cannot reach 180 EUR. Then the page is rerun on the server's reports of
2026-11-16 into a scratch folder: no candidate may have a capital figure unless its discounted lower band is above 0,
and no other line of the page may change.
