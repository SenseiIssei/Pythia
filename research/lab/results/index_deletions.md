# S&P 500 discretionary deletions (survey candidate 4)

Pre-registered as study 2 of `results/survey_equities_prereg.md` (5 trials).
Code: `python -m lab.experiments.survey_equities index_deletions`.

**Verdict: fails. Both picks (long deletions 12 months; deletions minus
additions 12 months) fail gates 1 and 2.** In the selection window (1996 to
2012, 187 deletions) the mean excess over the equal weight is huge (+58 %
per event for 12 months) but the median is -1 %: a handful of events carry
it, several of them data errors (PALM's unadjusted 1:20 reverse split in
2002 alone is +1,842 % in a day). Out of sample (147 deletions entered from
2013) the mean excess is +0.9 % per event with an event bootstrap band of
-6.9 % to +9.2 %, positive only in 2018 to 2021 (+21 %, carried by the March
2020 rebound: XEC, CPRI, COTY, KSS, M) and negative in 2013 to 2017 (-5 %) and
from 2022 (-12 %). The median deleted name trails the equal weight by 6 % in
the following year. Two of the five largest out-of-sample events are data
artefacts (FTR's stale price before a +266 % day in 2018, FRC trading at a
cent after its seizure); without them the mean is -0.2 %, which would hit the
registered kill rule. The deletions-minus-additions book makes Sharpe 0.35,
the long deletions book 0.65 against 0.80 for the equal weight on the same
days. Deflated p 0.00. Arnott and co-authors' 22 % a year does not appear
in 2013 to 2026 on this panel. No paper book.

Caveat: the panel has no delisting returns. The registered 30 % haircut for
performance delistings touched no out-of-sample position.

<!-- generated below by lab.experiments.survey_equities (index_deletions); edit above this line only -->

# S&P 500 discretionary deletions: results (2026-10-21)

**long deletions, 252 sessions: FAIL.** Out of sample (entries from 2013): 147 deletion events, mean excess over the equal weight 0.9 % per event (event bootstrap 90 % band -6.9 % to 9.2 %); by period -5.1 %, 20.7 %, -12.4 %; doubled costs 0.7 %, a day later 0.5 %, without the delisting haircut 0.9 %. Book Sharpe 0.65 on the 100 % of sessions it holds something (equal weight 0.80 on those days). Deflated p 0.000.

- fail: 1 mean excess per event above 0, event bootstrap 5 % bound above 0
- fail: 2 positive in at least 2 of 2013-17, 2018-21, 2022 on
- fail: 3 book Sharpe above the equal weight's on its days
- PASS: 4 mean excess above 0 with costs doubled and a day later

Excess by year of entry: 2013 -9 % (n 11), 2014 -19 % (n 14), 2015 -8 % (n 11), 2016 -22 % (n 8), 2017 21 % (n 16), 2018 -12 % (n 10), 2019 -22 % (n 8), 2020 78 % (n 16), 2021 0 % (n 12), 2022 10 % (n 8), 2023 -32 % (n 13), 2024 -14 % (n 11), 2025 -2 % (n 9).

Largest events: FTR 2017-03-28 280 %; XEC 2020-03-10 254 %; CPRI 2020-05-20 245 %; COTY 2020-09-29 147 %; FSLR 2017-03-28 142 %.

Data check (not a gate): median deletion excess -6.1 %, 5 % trimmed mean -4.6 %; without the events that hold a one-day move above +100 % (FRC 2023-05-12, FTR 2017-03-28) the mean excess is -0.2 %.

**deletions minus additions, 252 sessions: FAIL.** Out of sample (entries from 2013): 147 deletion events, mean excess over the equal weight 0.7 % per event (event bootstrap 90 % band -8.4 % to 10.1 %); by period -4.7 %, 23.6 %, -18.2 %; doubled costs 0.6 %, a day later 0.4 %, without the delisting haircut 0.7 %. Book Sharpe 0.35 on the 100 % of sessions it holds something (equal weight 0.80 on those days). Deflated p 0.000.

- fail: 1 mean excess per event above 0, event bootstrap 5 % bound above 0
- fail: 2 positive in at least 2 of 2013-17, 2018-21, 2022 on
- PASS: 3 book Sharpe above 0
- PASS: 4 mean excess above 0 with costs doubled and a day later

Excess by year of entry: 2013 -9 % (n 11), 2014 -19 % (n 14), 2015 -8 % (n 11), 2016 -22 % (n 8), 2017 21 % (n 16), 2018 -12 % (n 10), 2019 -22 % (n 8), 2020 78 % (n 16), 2021 0 % (n 12), 2022 10 % (n 8), 2023 -32 % (n 13), 2024 -14 % (n 11), 2025 -2 % (n 9).

Largest events: FTR 2017-03-28 280 %; XEC 2020-03-10 254 %; CPRI 2020-05-20 245 %; COTY 2020-09-29 147 %; FSLR 2017-03-28 142 %.

Data check (not a gate): median deletion excess -6.1 %, 5 % trimmed mean -4.6 %; without the events that hold a one-day move above +100 % (FRC 2023-05-12, FTR 2017-03-28) the mean excess is -0.4 %.

## All trials

| trial | events 1996-2012 | mean excess IS | events 2013 on | mean excess OOS | book Sharpe OOS | active IR OOS | deflated p |
|---|---|---|---|---|---|---|---|
| long deletions, 63 sessions | 187 | 0.20 | 160 | 0.02 | 0.42 | 0.12 | 0.00 |
| long deletions, 126 sessions | 187 | 0.34 | 156 | 0.02 | 0.46 | 0.24 | 0.00 |
| long deletions, 252 sessions | 187 | 0.58 | 147 | 0.01 | 0.65 | 0.41 | 0.00 |
| deletions minus additions, 126 sessions | 187 | 0.37 | 156 | -0.01 | 0.17 | 0.17 | 0.00 |
| deletions minus additions, 252 sessions | 187 | 0.62 | 147 | 0.01 | 0.35 | 0.35 | 0.00 |

Events: 352 discretionary deletions (163 from 2013), 759 additions (290 from 2013). Held names that hit the delisting haircut, either window: ABKFQ-201304, ACKH-200211, AKS, ANRZQ-201607, BGG, BHMSQ-200401, BMGCA-200101, BVSN, CCTYQ-201009, CITGQ-200912, CNC-200208, CNXT-201104, COV-200203, DALRQ-200704, DNR, DYN-201804, ECO-200301, EKDKQ-201309, ENRNQ-200411, ESV, FLMIQ-200408, FLTWQ-200907, FRC, FTL-A-200004, GAPTQ-201203, GTW-200710, GX-200201, HDLM-201301, HPH-199912, JCP, KM-200212, LDW-B-200012, LUB, MDR, MWW-201610, MZIAQ-201010, NE-202102, NRTLQ-201510, OWENQ-200610, PRD-200110, QEP, RAD, RSHCQ-201510, SGID-200610, SHLD-201810, SHN-200007, SUNEQ-201712, TLAB-201312, UAWGQ-200303, VSTNQ-201010, WCOEQ-200404, WFT, WIN, WNDXQ-200611.

Pool: 1,140 hand trials, 600 factory genomes and the 33 trials registered with this study (21 of them run so far, standing for all): 1,773 trials; the best noise trial sits at an annual Sharpe of about 2.26 on trading days.
