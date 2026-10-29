# The live bot's pump.fun rules on the readiness ladder, judged per trade: pre-registration (2026-10-29)

Written and committed before the code that computes any number below. Background: the review of 2026-10-27
(`results/review_2026-10-27.md`, sections 2 and 3), R5's registry (`metrics.trial_pool`, `<data>/trials/registry.jsonl`),
R6's windows (in sample to 2023-12-31, validation 2024-01-01 to 2026-06-30, lockbox from 2026-07-01), the readiness
ladder (`lab.ops.ladder`, `results/readiness_ladder_prereg.md`). Paper only: the ladder proposes, it never arms,
changes or sends anything, and nothing a live bot, a wallet or the engine reads changes.

## Why

The ladder lists 35 candidates, of pump.fun only R2's three small-wallet books. The rules the live bot ran
(`P_pool0_wait`, `P_pool0`, `P_cmig_model`) and the best rules of the real-time report (`P_pool0_wait_norug_half`,
`E_d0_x1`) have no step. They trade hundreds of times a week, so unlike the daily books (`reports/forward/power.md`:
3.6 to 30 or more years to show an edge) their evidence can arrive in weeks. Judged per trade, clustered by UTC day.

## The candidates

One row per rule, id `pumpfun:<rule>`, kind `rule`, family `pumpfun`, benchmark 0 (the stake held in SOL). Listed when
the paper ledger or the realistic report exists. Step 1 is the ladder's own: the rule's pre-registration against its
first results file.

| rule | pre-registration | first results | realistic paper book |
|---|---|---|---|
| P_pool0_wait | `pumpfun_exits_y8_prereg.md` | `pumpfun_exits_y8.md` | yes |
| P_pool0 | `pumpfun_pool0_prereg.md` | none (its first ledger day) | yes |
| P_cmig_model | `pumpfun_realtime_plan.md` | `pumpfun_realtime.md` | yes |
| P_pool0_wait_norug_half | `pumpfun_rugfilter_prereg.md` | `pumpfun_rugfilter.md` | yes |
| E_d0_x1 | `pumpfun_realtime_plan.md` | `pumpfun_realtime.md` | no: the collector runs it on the old paper model (`P_pool0` is the same rule as a realistic book) |

## The record

The paper ledger `<data>/paper/pumpfun_rt/ledger.csv`, the rows under the rule's own name (not `_ideal`, `_10eur`,
`@e1_`), realistic execution only: signalled at or after 2026-10-24 01:43 UTC (`REAL_FROM`, R1's switch; `state.json`'s
`realistic_since` when later). Left out: P1's tainted rows (`realistic.tainted`, `lab/pumpfun_rt/taint_p1.py`) and the
collector's restart closes. An entry is a closed trade (its `ret`, the book's own stake, every cost of the fit in it)
or a failed buy of the rule in `failed.csv` (its fee over the median stake of the rule's trades), as F3 counts entries.
The days of realistic record run from the rule's first such entry to now.

## The steps, per trade

1. **idea.** As the ladder: the pre-registration above exists and was committed before its first results file.
2. **tested.** All of:
   - **P1 out** (the ladder's leak condition for pump.fun): the tainted rows are counted and left out; an unreadable
     ledger fails.
   - **latency doubled still positive** (the one close late analogue): the `lat 2x` column of the real-time report
     (`reports/pumpfun_rt/latest.json`, the rule's out-of-sample `stress.lat2x.mean`) above 0; no row fails.
   - **costs of their era**: a realistic paper book (the table above) with at least one entry since `REAL_FROM`.
   - **R7's bar** (`results/pumpfun_factory_f3.md`, `factory.by_day` and `factory.deflated`): the Sharpe per entry
     (mean over standard deviation of the entries' returns, skew and kurtosis with it) deflated
     (`metrics.deflated_sharpe`) on the effective entries of the mean's standard error clustered by UTC day, at least
     20 entries and at least 10 scored days (UTC days with an entry). N: over the whole registry, R5's count of all
     (these five trials included) plus F3's ledger trials (`<data>/pumpfun_rt/factory/ledger.jsonl`, outside R5: its
     per-entry Sharpes do not pool with daily ones); over the family, R5's `pumpfun` family plus F3's trials. The
     noise variance: F3's per-entry Sharpes of its trials with at least 20 entries (`factory.pool`); fewer than two
     fail. Pass at 0.95 over both (higher is better).
   - No PBO: there is no matrix of pump.fun configurations on the realistic record; the deflation over R5 and F3 and
     the 10 scored days stand in for it. Written here so that it is not read as a pass.
3. **shadow.** The realistic record is the collector's forward record (each trade logged when it happened). T8's
   logic (`lab.paper.power`) per trade instead of per day: the e-process `power.log_e` on the day sums of the entries'
   returns less 0 (the sum and the clustered square of each UTC day, so a day's shared market is one observation),
   its scale from the first 10 days with entries (T8's `REF_DAYS`, not tested), its horizon the days the fixed sample
   needs at a reference Sharpe of 0.1 per entry (`PF_REF_SHARPE`, fixed here) at those days' effective entries per
   day. Passes when E reaches 1 / 0.05 = 20 on any later day (Ville: valid looked at every day).
4. **lockbox.** R6's lockbox began before the pump.fun record (2026-10-20), and every day of it has been looked at. The
   analogue: the same e-process (its scale and horizon from step 3, nothing fitted on the new days) on the days from
   2026-10-30 00:00 UTC on only, after this pre-registration. Passes when E reaches 20, against 0.
5. **execution.** P2's selection gate (`selection` in `reports/pumpfun_rt/realistic.json`: paper minus live under 2
   points, `pass`) and P3's gate of the rule's 10 EUR book (`<rule>_10eur` in `ten`: 30 days, mean and the band's lower
   end above 0 after all costs, P1 out; `results/ten_eur_p3_prereg.md`). Absent evidence is an **open** line, shown as
   open, not a failure; as everywhere from step 2 on it still blocks the step.
6. **larger.** Only the owner.

## What is shown per rule

Step, next missing, days of realistic record, entries (and effective entries), mean per entry with R7's day band, the
two DSRs, E now, and the days still needed at its current mean per entry: to step 2's bar (effective entries
`1 + (1.645 x d / (S - SR0))^2`, d the skew and kurtosis term, SR0 over the whole N; at least 10 scored days) and to
T8's power at 0 (`(z_0.95 + z_0.80)^2 / S^2`, the fixed sample, which the sequential test needs at least), each at the
record's effective entries per day, less the days already there. A mean at or under the bar: never at its current mean.

## Trials

Five, one per rule (`pumpfun:ladder:<rule>`, family `pumpfun`, counted only, no Sharpe), counted in every DSR above
whether or not the registry holds them yet, registered by the ladder's first report. Results in
`results/ladder_pumpfun.md`. Nothing above is changed after the first number.
