# crypto_open_gap (survey O6) · overnight BTC and the COIN / MSTR session

Pre-registered in `results/crypto_open_gap_prereg.md` (committed before any
number was computed). Code: `lab.experiments.crypto_open_gap`.

**Summary.** No. The gap prices the overnight BTC move almost fully (its
correlation with BTC's 16:00-to-09:30 move is 0.74 for COIN and 0.88 for MSTR
out of sample). In sample the session leaned against the gap's surprise
(slope t -2.6 COIN, -1.6 MSTR), out of sample the slope is t -0.6 and -1.1:
COIN is killed (below 1), MSTR fails. Traded at the official open the rule
looks fine for MSTR (0.86), but that needs the opening print it trades on;
entered an hour later it loses on both (-0.69 COIN, -0.23 MSTR): what there
is sits in the first hour after the open. No book (the engine also has no
intraday lab book to run it).

<!-- generated below by lab.experiments.crypto_open_gap; edit above this line only -->

## Results (generated 2026-10-21, out of sample 2023-01-01 to 2026-10-14)

**Verdict: no pass.**

- **COIN**: killed (slope t below 1). Slope of the session on the gap surprise in sample -0.319 (t -2.63, 313 sessions), out of sample -0.061 (t -0.62, 948 sessions). The rule at the official open makes Sharpe 0.32 out of sample (0.00 at 10 bps), trading 80 % of sessions, +10.1 bps a trade; an hour late (from 2023-11-22, 725 sessions) -0.69 (-1.18 at 10 bps) against 0.11 at the open on the same days. Deflated p 0.00.
- **MSTR**: fails: slope t above 2 in the in-sample sign; rule above 0 an hour late at 5 bps; rule above 0 an hour late at 10 bps. Slope of the session on the gap surprise in sample -0.263 (t -1.60, 465 sessions), out of sample -0.196 (t -1.12, 948 sessions). The rule at the official open makes Sharpe 0.86 out of sample (0.57 at 10 bps), trading 75 % of sessions, +30.2 bps a trade; an hour late (from 2023-11-22, 725 sessions) -0.23 (-0.63 at 10 bps) against 0.38 at the open on the same days. Deflated p 0.00.

| stock | is_days | oos_days | b_is | t_is | b_oos | t_oos | is_open | oos_open | oos_open_stress | late_days | late_open_same_days | late | late_stress | first_hour_slope_t | late_slope_t | corr_gap_btc_oos | beta_median_oos | deflated_p_late |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| COIN | 313 | 948 | -0.319 | -2.627 | -0.061 | -0.618 | 0.416 | 0.322 | 0.003 | 725 | 0.109 | -0.692 | -1.184 | 0.065 | -1.437 | 0.735 | 1.084 | 0.000 |
| MSTR | 465 | 948 | -0.263 | -1.601 | -0.196 | -1.118 | 0.702 | 0.858 | 0.574 | 725 | 0.383 | -0.232 | -0.629 | 0.920 | 0.041 | 0.879 | 1.353 | 0.000 |

COIN at the open per year: 2023 1.17, 2024 0.56, 2025 0.10, 2026 -1.25.
MSTR at the open per year: 2023 3.16, 2024 0.93, 2025 -0.65, 2026 0.35.

`first_hour_slope_t` and `late_slope_t`: the slope's t (in the in-sample sign) for the first hour alone and for 10:30 to the close, on the sessions with hourly bars.

Pool 1,762 trials; noise bar about 2.72.
