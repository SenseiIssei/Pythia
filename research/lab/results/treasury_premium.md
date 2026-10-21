# treasury_premium (survey O2) · MSTR premium to its BTC

Pre-registered in `results/treasury_premium_prereg.md` (committed before any
number was computed). Code: `lab.experiments.treasury_premium` (the
registered feasibility check only).

**Summary.** Not run: the registered feasibility rule fails on this machine.
The weekly holdings sit in 8-K documents that SEC serves only to a
User-Agent naming a contact (`PYTHIA_SEC_UA`, unset here); XBRL tags the BTC
count only at quarter ends and only from the 10-K filed 2026-02-19. With the
documents readable the 8-K route would cover 81 % of the out-of-sample weeks,
so the study can run once the variable is set and an 8-K parser exists.

<!-- generated below by lab.experiments.treasury_premium; edit above this line only -->

## Results (generated 2026-10-21)

**Stops at feasibility, as registered.** No return was computed.

- MSTR filed 232 8-Ks from 2020-08-01 (199 with item 8.01, where the weekly holdings updates sit); the submissions index on data.sec.gov answers the lab's default User-Agent.
- The filing documents themselves (www.sec.gov/Archives) answer with the SEC page for undeclared automated tools: SEC asks for a User-Agent that names a contact, and `PYTHIA_SEC_UA` is not set on this machine. Without the documents there is no weekly holdings series. Were they readable, the 8.01 filings would cover 81 % of the out-of-sample weeks by the 14-day rule.
- XBRL company facts carry `CryptoAssetNumberOfUnits` only at quarter ends, 8 points, the first of them known on 2026-02-19 (the 10-K that first tagged it): 0 % of the out-of-sample weeks have a figure no older than 14 days, against the 80 % the registration needs.
- `dei:EntityCommonStockSharesOutstanding` is absent in MSTR's company facts, so the share count would also have to come from the documents.
- Peers (MARA, RIOT, CLSK, HUT mine and their holdings move daily; SMLR, GME and the newer treasury companies have under two years of holdings filings; TSLA and COIN hold BTC as a side position): not tested, as registered.

What it would take: `PYTHIA_SEC_UA` set to a real contact where the study runs, a parser for the 8-K holdings and at-the-market tables; then this registration can run as written (its 2 trials are already counted in the pool, though nothing was run).

| as_of | filed | btc |
|---|---|---|
| 2022-12-31 | 2026-02-19 | 132500 |
| 2023-12-31 | 2026-02-19 | 189150 |
| 2024-12-31 | 2026-02-19 | 447470 |
| 2025-12-31 | 2026-02-19 | 672500 |
| 2025-12-31 | 2026-05-06 | 672500 |
| 2025-12-31 | 2026-08-03 | 672500 |
| 2026-03-31 | 2026-05-06 | 762099 |
| 2026-06-30 | 2026-08-03 | 846000 |
