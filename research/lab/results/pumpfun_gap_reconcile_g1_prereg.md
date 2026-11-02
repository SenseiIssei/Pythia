# G1: P2's same-coin gap against the live twin, trade by trade. Pre-registration

Registered 2026-11-02 and committed before any number of this study was computed. On the review of 2026-10-27
(`results/review_2026-10-27.md`, sections 2 and 3), R5's registry (`metrics.trial_pool`,
`<data>/trials/registry.jsonl`), R6's windows, P1's taint rule (`realistic.tainted`, `realistic.FIX_MS`), P2
(`results/pumpfun_selection_gap_p2_prereg.md`, `selection_p2.py`) and the live twin
(`results/pumpfun_live_twin_prereg.md`, `live_twin.py`). Paper only and read only on everything live: nothing a live
bot, its rules, sizing, wallet, caps or the engine reads changes.

Numbers seen before this file: P2's line in `<data>/reports/pumpfun_rt/realistic.md` (paper minus live +8.8 points a
trade, band +2.0 to +15.5, 685 paper signals, 186 live trades, selection -5.4, same coins +14.0, live's own +0.2),
`results/pumpfun_selection_gap_p2.md` and `results/pumpfun_live_twin.md` (66 twins of 149, live minus twin -2.5 on
2026-10-22 to 24), and the list of the 37 live trades signalled after the cut (all P_pool0, their times, exit reasons
and holds; not their returns).

## The question

P2 says paper earns +14.0 points a trade more than live on the same coins; the twin says live is only 2.5 points
under the realistic executor on live's own trades. Both cannot describe the same paper. On a common sample the three
records of a trade obey (P - L) = (P - T) - (L - T): P the paper row of the pipeline book (`<data>/paper/pumpfun_rt`
ledger, the book named by the live rule), L the live fill, T the twin. This study measures P - T and says where it
comes from.

## The sample

Live closed trades of `ledger.csv` (modes test and full) signalled at or after 2026-10-28 19:40 UTC (`FIX_MS`, P1's
cut) that have both:

- a P2 paper row: `selection_p2.compute` over every live run, unchanged, reads the paper ledger, failed buys and
  skips and pairs the trade as `traded` (its `live_key`) with a paper ledger row with a return (failed paper buys and
  P1-tainted or restart rows are out, as in P2);
- a twin: `live_twin.replay`, unchanged, on these live trades only (the leave-one-day-out fits of every measured live
  row, the record's lag found as there), `twin` true (bought, buy failed or no buy; misses named and counted).

Every live trade after the cut that falls out is listed with its reason (no P2 paper row: P2's live-only reason;
no twin: the twin's miss).

## Three records a trade

For each trade one line of: signal time (live, paper, twin; the twin's on the record's clock), the record's clock
offset (the twin's lag), landing, stake, entry price, the curve impact of the stake (stake over the pool's quote
reserve, the first recorded pool trade at or after the paper's landing), exit rule (exit_why) and exit decision
time, exit time, exit price (the realised one: proceeds over tokens; the paper ledger's exit_price is the spot at the
close, so a pool buy's tokens are its stake over entry_price), fees and rent (the return less the price move), the
twin's buy outcome. Returns per trade on each side's own stake.

## The decomposition of P - T (points a trade, x 100)

g(e, x) = x / e - 1; m(t) the record's price at the first recorded trade of the coin at or after t (the twin's path,
`live_twin.m_at`). E, X the realised entry and exit prices; s, d, xd the signal, landing and exit decision times on
the record's clock; S the stake; r = ret - g(E, X) the fees and rent part of a return; Q the pool's quote reserve.

- signal time: e_a = E_t m(s_p + d_t - s_t) / m(d_t); g(e_a, X_t) - g(E_t, X_t)
- entry latency: e_b = E_t m(d_p) / m(d_t); g(e_b, X_t) - g(e_a, X_t)
- entry size (curve impact): e_c = e_b (1 + S_p / Q) / (1 + S_t / Q); g(e_c, X_t) - g(e_b, X_t)
- entry price (the rest of the fill): g(E_p, X_t) - g(e_c, X_t)
- exit rule: x_1 = X_t m(xd_p) / m(xd_t); g(E_p, x_1) - g(E_p, X_t) when the two exit_why differ, else 0
- exit time: the same term when the two exit_why agree, else 0
- exit price: g(E_p, X_p) - g(E_p, x_1)
- stake size (fixed fees): r_t S_t / S_p - r_t
- fees and rent: r_p - r_t S_t / S_p
- failed buys: the whole P - T when the twin did not buy or a price is missing (the other parts 0)

The parts telescope to ret_p - ret_t exactly; the report shows their sum against the total (must agree within 0.5
points on the sample, else the run is a failure and says so). A price of the path missing or 0 leaves that move at 1.
The largest part is the one with the largest absolute mean.

Beside it on the same sample: P - L (P2's same-coin difference) and L - T (the twin's), and the check
(P - L) = (P - T) - (L - T).

## The bridge to the headline numbers

P2's same-coin part (P_m - L_m over all its matched pairs) by era of the paper signal: before `realistic_since`
(the ideal paper model), from `realistic_since` to the cut, from the cut; and the twin's -2.5 (2026-10-22 to 24, no
trade after the cut). Count and mean per era. This says how much of the 16 points is the two studies' samples.

## Bands

Trades drawn with replacement (95 % percentile bootstrap, 2,000 draws, seed 0): one or two days after the cut, so no
day clusters. No Sharpe, no DSR.

## Decision rule

1. A trade whose largest part comes from a defect (the pipeline executor filling, timing or charging a paper row
   against its own rules, `realistic.py` or `pipeline.py`; or P2 pairing a live trade with a paper row of another
   entry, `selection_p2.py`): the defect is fixed with a test red before and green after, P2 and the decomposition
   are run again, and P_pool0's paper mean a trade is restated on the fixed ledger (one more trial,
   `pumpfun:gap_g1:fixed`, registered before that run).
2. A real difference (the paper trading on the lagged recording, its own stake, its own latency fit, its own exits'
   timing on its own clock): written down, no book, gate or ledger changes.
3. The ladder's P3 gate: if |P - T| on the sample is under 2 points, the paper books and the executor agree and the
   gate should read P2 on paper the books trade now (signals at or after the later of `realistic_since` and the
   cut), P2's headline being the old eras; if 2 points or more, the gate should read P2 (paper as the books trade it,
   against live), and the twin's number only says the executor is faithful when given live's inputs. Recommended in
   the result in one sentence; no gate code changes in this study.

## Trials

Four in R5's registry, family pumpfun, counted only, registered before the first number (through the registry copy,
`PYTHIA_TRIALS_REGISTRY`): `pumpfun:gap_g1:total` (P - T), `pumpfun:gap_g1:parts`, `pumpfun:gap_g1:identity` (P - L
and L - T on the sample), `pumpfun:gap_g1:eras` (the bridge). `python -m lab.pumpfun_rt.reconcile_g1` writes
`results/pumpfun_gap_reconcile_g1.md`.
