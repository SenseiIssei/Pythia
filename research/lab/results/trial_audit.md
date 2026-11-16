# Trial register audit: what the studies declared against what R5 holds

Pre-registration `results/trial_audit_prereg.md`. Code `lab.ops.trial_audit` (the declared counts with their file and
a verbatim quote, checked against the file), tests `tests/test_trial_audit.py`. Read on 2026-11-16 against
`<data>/trials/registry.jsonl`: 4,647 rows, 6,124 trials (hand 2,242, factory 2,134, small 1,602, pumpfun 146). Since
the task was written (4,600 rows, 6,035 trials, pumpfun 57) T14 merged E1 (60), P3 (3), T7 (39), T8, O1 (7), RF1 (12),
T12 (17), SW1 (222), DT1 (656), EQ2 (16) and the pool state fix (81): they show as registered below. Two trials
counted for this audit (`audit:recheck:P_pool0`, `audit:recheck:genome`), counted only.

## Result

- 100 pre-registered studies (with this one), 104 lines by family, every quote found in its file. 21 of them had
  trials R5 did not hold: **617 trials** (pumpfun 601, hand 13, small 3) plus this audit's 2, appended through `metrics.register` into
  the run's copy (T14 merges it): R5 now 6,743 trials (hand 2,255, factory 2,135, small 1,605, pumpfun 748).
- Almost all of the gap is pump.fun: Y5 real latency 140, R2 small wallet 336, A1 29, the Y books (Y6 to Y17) 84,
  the bombers 12. They were deflated inside the real-time study's own pool (`strategies.N_TRIALS`) or their own
  and never reached R5. Outside pump.fun: T9 (4), T11 (5, with its in-sample Sharpes under its own ids), the
  analyst's PC model (1), the equity sleeve (1), the exit shadow (2), onchain meme (3).
- Registered above declared, shown and not removed: T8 (hand 41 against 36, factory 5 against 2; its daily job
  registers new records), M4L (3 against 2), the fit window (n 5 against 3), A4's lockbox look (1 against 0).
- Seed groups: every group's declared sum matches its block (the 2026-10-21 batch 188, the 2026-10-21 trio 25, the
  pair study block 24, the director 9, X15 47, X16 120, Polymarket 16, S2 8); the C16 to X11 block (571) and S1's
  (61 configurations) hold more than the pre-registered studies in them declare.
- Not audited (no `_prereg.md` file): the three pump.fun plans `pumpfun_realtime_plan.md`, `pumpfun_early_exit_plan.md`
  and `pumpfun_speed_plan.md`, 224 more of `strategies.N_TRIALS` (444 in all: 22 rules, the model filter, 12
  pipeline strategies, X14's 54, Y3's 135). They are pre-registrations under another name and not in R5 either.

## F3 and the one total

F3's pump.fun genomes live in `<data>/pumpfun_rt/factory/ledger.jsonl` (per-entry Sharpes, outside R5 by design):
1,085 trial lines today. The ladder deflates each pump.fun rule over N all = R5 (every family, with its own five
`pumpfun:ladder:*`) + F3's lines, and N family = R5's pumpfun + F3's lines; the noise variance is F3's per-entry
Sharpes (those with enough entries), never R5's per-day one. The 7,120 of the task was that sum on its day; the weekly page printed R5 alone (5,983 on
2026-11-15). Now `ladder.register_total` is the one total:
the ladder's header, its pump.fun DSRs, the progress page and the weekly page print the same number and one line
naming both registers ("R5's registry ... plus F3's ledger ...").

## DSR before and after (higher is better, pass at 0.95; both can only fall as N grows)

| | before (R5 as read) | after (with the audit's rows) |
|---|---|---|
| total R5 + F3 | 7,209 | 7,828 |
| P_pool0, N all / pumpfun | 7,209 / 1,231 | 7,828 / 1,833 |
| P_pool0, bar per entry all / pumpfun | 0.946 / 0.829 | 0.951 / 0.857 |
| P_pool0, Sharpe per entry (2,893 entries) | 0.062 | 0.062 |
| P_pool0, DSR all / pumpfun | 0.000 / 0.000 | 0.000 / 0.000 |
| best weekly genome 7f71dc8eb814, DSR of the excess over BTC | 0.00078 (6,124; 0.00080 at the report's 5,983) | 0.00073 (6,743) |
| R5's noise bar of all, a year | 2.91 | 2.98 |

P_pool0's DSR was 0 before and stays 0: its Sharpe per entry is far below the bar either way. The genome's DSR is
backed out of the factory report of 2026-11-15 (its own value reproduced at 5,983 trials) at the same excess variance,
skew and kurtosis, and recomputed at the new N. The hand family's bar rises (3.24 to 3.34 a year) from T11's
in-sample Sharpes; the counted-only blocks raise N only.

## Every study

| study | family | declared | registered | missing | read from |
|---|---|---|---|---|---|
| allocator_t9 | hand | 4 | 0 | 4 | `results/allocator_t9.md` |
| analyst_local | hand | 2 | 1 | 1 | `results/analyst_local_prereg.md` |
| attention_wiki | hand | 13 | in hand:perps_attention_intraday | - | `results/attention_wiki.md` |
| book_depth_t4 | hand | 0 | 0 | 0 | `results/book_depth_t4.md` |
| btc_vrp | hand | 6 | in hand:batches_2026_10_21 | - | `results/btc_vrp_prereg.md` |
| candles | hand | 47 | in hand:x15_candles | - | `results/candles.md` |
| categories_local_ai2 | hand | 3 | 3 | 0 | `results/categories_local_ai2_prereg.md` |
| cost_aware_t7 | factory | 33 | 33 | 0 | `results/cost_aware_t7.md` |
| cost_aware_t7 | hand | 6 | 6 | 0 | `results/cost_aware_t7_prereg.md` |
| crypto_open_gap | hand | 2 | in hand:batches_2026_10_21 | - | `results/crypto_open_gap_prereg.md` |
| crypto_own | hand | 94 | in hand:batches_2026_10_21 | - | `results/crypto_own_prereg.md` |
| daytrade_dt1 | hand | 656 | 656 | 0 | `results/daytrade_dt1.md` |
| daytrade_eq2 | small | 16 | 16 | 0 | `results/daytrade_eq2.md` |
| depth_signal_o1 | hand | 7 | 7 | 0 | `results/depth_signal_o1.md` |
| dsr_bar_r7b | pumpfun | 0 | 0 | 0 | `results/dsr_bar_r7b.md` |
| equities_training | hand | 120 | in hand:x16_equities_training | - | `results/equities_training.md` |
| equity_sleeve | hand | 1 | 0 | 1 | `results/equity_sleeve_prereg.md` |
| etf_books_eq1 | small | 30 | 30 | 0 | `results/etf_books_eq1.md` |
| etf_routing | hand | 4 | in hand:batches_2026_10_21 | - | `results/etf_routing_prereg.md` |
| exec_alpaca_eq3 | small | 4 | 4 | 0 | `results/exec_alpaca_eq3_prereg.md` |
| exec_dryrun_l1 | small | 11 | 11 | 0 | `results/exec_dryrun_l1.md` |
| exit_shadow | hand | 2 | 0 | 2 | `results/exit_shadow_prereg.md` |
| flush_long | hand | 8 | in hand:batches_2026_10_21 | - | `results/flush_long_prereg.md` |
| forward_audit | hand | 0 | 0 | 0 | `results/forward_audit.md` |
| forward_power_t8 | factory | 2 | 5 | 0 | `results/forward_power_t8.md` |
| forward_power_t8 | hand | 36 | 41 | 0 | `results/forward_power_t8.md` |
| funding_carry | hand | 13 | in hand:batches_2026_10_21 | - | `results/funding_carry_prereg.md` |
| gated_btc | hand | 4 | in hand:director_2026_10_20 | - | `results/gated_btc_prereg.md` |
| genome_gates | hand | 4 | in hand:director_2026_10_20 | - | `results/genome_gates_prereg.md` |
| hedged_breakout | hand | 2 | in hand:positioning_taker_hedged_pead | - | `results/hedged_breakout.md` |
| hl_funding_t11 | hand | 5 | 0 | 5 | `results/hl_funding_t11.md` |
| intraday_tsmom | hand | 9 | in hand:perps_attention_intraday | - | `results/intraday_tsmom.md` |
| kraken_fee_s1 | small | 8 | 8 | 0 | `results/kraken_fee_s1.md` |
| kraken_funding_gap | hand | 4 | in hand:batches_2026_10_21 | - | `results/kraken_funding_gap_prereg.md` |
| ladder_promotion_a4 | factory | 0 | 1 | 0 | `results/ladder_promotion_a4_prereg.md` |
| ladder_pumpfun | pumpfun | 5 | 5 | 0 | `results/ladder_pumpfun.md` |
| leak_harness | hand | 0 | 0 | 0 | `results/leak_harness_prereg.md` |
| m4_residual | hand | 1 | in hand:director_2026_10_20 | - | `results/m4_residual_prereg.md` |
| m4h | small | 97 | in m4h2 | - | `results/m4h.md` |
| m4h2 | small | 97 | 97 | 0 | `results/m4h2_prereg.md` |
| m4l | small | 2 | 3 | 0 | `results/m4l.md` |
| market_structure_i1 | hand | 0 | 0 | 0 | `results/market_structure_i1_prereg.md` |
| model_review | hand | 29 | in hand:c16_to_x11 | - | `results/model_review_prereg.md` |
| model_upgrades | hand | 18 | in hand:c16_to_x11 | - | `results/model_upgrades.md` |
| onchain_meme | small | 3 | 0 | 3 | `results/onchain_meme_prereg.md` |
| onchain_stage2 | small | 0 | 0 | 0 | `results/onchain_stage2_prereg.md` |
| overfit_yardsticks | hand | 0 | 0 | 0 | `results/overfit_yardsticks.md` |
| pead_xbrl | hand | 4 | in hand:positioning_taker_hedged_pead | - | `results/pead_xbrl.md` |
| perps_neutral_portfolio | hand | 3 | in hand:perps_attention_intraday | - | `results/perps_neutral_portfolio.md` |
| pit_universe_t5 | hand | 18 | 18 | 0 | `results/pit_universe_t5.md` |
| polymarket | hand | 16 | in hand:polymarket | - | `results/polymarket.md` |
| positioning_xs | hand | 5 | in hand:positioning_taker_hedged_pead | - | `results/positioning_xs_prereg.md` |
| progress_page_u1 | hand | 0 | 0 | 0 | `results/progress_page_u1_prereg.md` |
| pumpfun_activity | hand | 2 | in hand:batches_2026_10_21 | - | `results/pumpfun_activity_prereg.md` |
| pumpfun_adaptive_a1 | pumpfun | 29 | 0 | 29 | `results/pumpfun_adaptive_a1.md` |
| pumpfun_bombers | pumpfun | 12 | 0 | 12 | `results/pumpfun_bombers.md` |
| pumpfun_clock_audit | pumpfun | 0 | 0 | 0 | `results/pumpfun_clock_audit.md` |
| pumpfun_creation_gap | pumpfun | 3 | 3 | 0 | `results/pumpfun_creation_gap.md` |
| pumpfun_entry_e2 | pumpfun | 29 | 29 | 0 | `results/pumpfun_entry_e2.md` |
| pumpfun_exit_runners | pumpfun | 6 | 0 | 6 | `results/pumpfun_exit_runners.md` |
| pumpfun_exits_y8 | pumpfun | 5 | 0 | 5 | `results/pumpfun_exits_y8.md` |
| pumpfun_flow_exit_x14r2 | pumpfun | 11 | 11 | 0 | `results/pumpfun_flow_exit_x14r2.md` |
| pumpfun_freeride | pumpfun | 16 | 0 | 16 | `results/pumpfun_freeride.md` |
| pumpfun_gap_reconcile_g1 | pumpfun | 5 | 5 | 0 | `results/pumpfun_gap_reconcile_g1.md` |
| pumpfun_ledger_taint_p1 | hand | 2 | 2 | 0 | `results/pumpfun_ledger_taint_p1.md` |
| pumpfun_live_twin | pumpfun | 5 | 5 | 0 | `results/pumpfun_live_twin.md` |
| pumpfun_lock | pumpfun | 12 | 0 | 12 | `results/pumpfun_lock.md` |
| pumpfun_os1 | pumpfun | 2 | 2 | 0 | `results/pumpfun_os1.md` |
| pumpfun_pool0 | pumpfun | 1 | 0 | 1 | `results/pumpfun_pool0_prereg.md` |
| pumpfun_pool_state_fix | pumpfun | 81 | 81 | 0 | `results/pumpfun_pool_state_fix_prereg.md` |
| pumpfun_real_latency | pumpfun | 140 | 0 | 140 | `results/pumpfun_real_latency.md` |
| pumpfun_realistic_fit_window | pumpfun | 3 | 5 | 0 | `results/pumpfun_realistic_fit_window.md` |
| pumpfun_rugfilter | pumpfun | 12 | 0 | 12 | `results/pumpfun_rugfilter.md` |
| pumpfun_runner | pumpfun | 4 | 0 | 4 | `results/pumpfun_runner.md` |
| pumpfun_select_y9 | pumpfun | 10 | 0 | 10 | `results/pumpfun_select_y9.md` |
| pumpfun_selection_gap_p2 | hand | 5 | 5 | 0 | `results/pumpfun_selection_gap_p2.md` |
| pumpfun_shapes_y17 | pumpfun | 4 | 0 | 4 | `results/pumpfun_shapes_y17_prereg.md` |
| pumpfun_smallwallet_r2 | pumpfun | 336 | 0 | 336 | `results/pumpfun_smallwallet_r2_prereg.md` |
| pumpfun_social_y14 | pumpfun | 4 | 0 | 4 | `results/pumpfun_social_y14.md` |
| pumpfun_trends_y10 | pumpfun | 10 | 0 | 10 | `results/pumpfun_trends_y10.md` |
| range_forecast_rf1 | hand | 12 | 12 | 0 | `results/range_forecast_rf1.md` |
| reachable_venues_t12 | hand | 17 | 17 | 0 | `results/reachable_venues_t12.md` |
| readiness_ladder | hand | 0 | 0 | 0 | `results/readiness_ladder_prereg.md` |
| recordings_t13 | hand | 0 | 0 | 0 | `results/recordings_t13.md` |
| slippage_e1 | hand | 60 | 60 | 0 | `results/slippage_e1.md` |
| smallaccount_r10 | small | 0 | 0 | 0 | `results/smallaccount_r10_prereg.md` |
| smallaccount_s1 | small | 8 | in small:s1 | - | `results/smallaccount_s1_prereg.md` |
| smallaccount_s2 | small | 8 | in small:s2 | - | `results/smallaccount_s2.md` |
| smallaccount_weekly | small | 7 | 7 | 0 | `results/smallaccount_weekly_prereg.md` |
| survey_equities | hand | 33 | in hand:batches_2026_10_21 | - | `results/survey_equities_prereg.md` |
| swing_sw1 | small | 222 | 222 | 0 | `results/swing_sw1.md` |
| taker_imbalance_xs | hand | 13 | in hand:positioning_taker_hedged_pead | - | `results/taker_imbalance_xs.md` |
| ten_eur_p3 | hand | 3 | 3 | 0 | `results/ten_eur_p3_prereg.md` |
| treasury_premium | hand | 2 | in hand:batches_2026_10_21 | - | `results/treasury_premium.md` |
| trend_shorts | hand | 12 | in hand:batches_2026_10_21 | - | `results/trend_shorts_prereg.md` |
| trial_audit | factory | 1 | 0 | 1 | `results/trial_audit_prereg.md` |
| trial_audit | pumpfun | 1 | 0 | 1 | `results/trial_audit_prereg.md` |
| two_leads_t6 | hand | 6 | 6 | 0 | `results/two_leads_t6_prereg.md` |
| two_leads_t6 | small | 3 | 3 | 0 | `results/two_leads_t6_prereg.md` |
| two_leads_t6b | hand | 28 | 28 | 0 | `results/two_leads_t6.md` |
| vix_carry | hand | 8 | in hand:batches_2026_10_21 | - | `results/vix_carry_prereg.md` |
| weekly_capital_line | hand | 0 | 0 | 0 | `results/weekly_capital_line_prereg.md` |
| weekly_page_w1 | hand | 0 | 0 | 0 | `results/weekly_page_w1_prereg.md` |
| xstocks_t10 | small | 1 | 1 | 0 | `results/xstocks_t10.md` |

| seed block | family | studies | declared | registered | missing |
|---|---|---|---|---|---|
| `hand:perps_attention_intraday` | hand | attention_wiki, intraday_tsmom, perps_neutral_portfolio | 25 | 25 | 0 |
| `hand:batches_2026_10_21` | hand | btc_vrp, crypto_open_gap, crypto_own, etf_routing, flush_long, funding_carry, kraken_funding_gap, pumpfun_activity, survey_equities, treasury_premium, trend_shorts, vix_carry | 188 | 188 | 0 |
| `hand:x15_candles` | hand | candles | 47 | 47 | 0 |
| `hand:x16_equities_training` | hand | equities_training | 120 | 120 | 0 |
| `hand:director_2026_10_20` | hand | gated_btc, genome_gates, m4_residual | 9 | 9 | 0 |
| `hand:positioning_taker_hedged_pead` | hand | hedged_breakout, pead_xbrl, positioning_xs, taker_imbalance_xs | 24 | 24 | 0 |
| `hand:c16_to_x11` | hand | model_review, model_upgrades | 47 | 571 | 0 |
| `hand:polymarket` | hand | polymarket | 16 | 16 | 0 |
| `small:s1` | small | smallaccount_s1 | 8 | 61 | 0 |
| `small:s2` | small | smallaccount_s2 | 8 | 8 | 0 |
