# The tests that failed on main, made independent of the lab's data folder (2026-10-29)

T3, T4, T7 and T8 found 13 or 14 failures in the full research/lab suite on unchanged main. Each test file was
run on its own on main (571d1dd) three ways: as the lanes run it (PYTHIA_DATA=/data), with PYTHIA_DATA unset (the
code's default is /data as well) and with PYTHIA_DATA on an empty temp folder. No trial, no number: the fixes only
change where tests read from, and one code fix.

## The list

| test | failed | cause | fix |
|---|---|---|---|
| `test_notify.py`: numbers_have_signs_separators_and_percent, tables_put_words_left_and_numbers_right_and_long_posts_fit, digest_says_what_the_money_did, the_table_also_holds_each_autopilot_against_btc_above_its_200_day_average, today_and_its_trades_come_from_yesterdays_snapshot, losses_red_health_and_a_stale_report_are_said, many_autopilots_are_cut_to_a_phone_screen, the_weekly_card_counts_the_week (8) | with /data | alert language: `notify.alert_lang` reads the owner's `<data>/reports/notify/settings.json` (German) wherever a test gives the data folder no temp root | an autouse fixture sets PYTHIA_ALERT_LANG=en; the tests that check German still set de themselves |
| `test_model_zoo.py`: train_due_promotes_shadows_reports_and_alerts, drift_is_alerted_once (2) | with /data | alert language: the zoo's alerts go through notify, which read the settings from /data (T2's finding) | the `root` fixture points PYTHIA_DATA at its temp folder (PYTHIA_REPORTS unset) and sets PYTHIA_ALERT_LANG=en |
| `test_forward_report.py`: modelled_only_books_and_funding (1) | with /data | reads real data: `forward_report.ROOT` is bound from `lab.data` at import, so `report_stats` found the lab's real report for picks_ls and the book got an expected band | the `reports` fixture sets `fr.ROOT` to its temp folder too |
| `test_factory_trees.py`: every_tree_is_a_trial_and_the_report_shows_it (1, the "once") | with /data | reads real data: `build.feature_leaves` reads the lab's `features/coverage.json` and the search drew feature leaves (and read candles) the synthetic panel has not got, so one of the 40 trials came out a duplicate | test_factory's `home` fixture (shared by the factory tests) points `lab.data.ROOT`, `WRITE_ROOT` and the feature store's `ROOT` and `OUT` at its temp folder; the test also runs in 16 s instead of 140 |
| `test_execution_e1.py`: the_replay_executor_applies_its_limit_before_the_send (1) | always | a real bug: since E1's bounds (cf5a74a, 2026-10-28) `RealExecutor` reads its class's `buy_tol`, set once from `POOL_BUY_TOL`, and E1's `tol_executor` still only patched the module's `POOL_BUY_TOL`, so every replay limit ran at the live 0.60 | `tol_executor`'s class sets `buy_tol = tol` (2 lines in `lab/experiments/execution_e1.py`); the test also passes the default `LiveConfig()` so the live bot's control and status files are not read; a new test checks each limit executor keeps its own bound |
| `test_pokemon.py` (2 in the lanes' runs) | before 244c265 | clock: the alert tests ran on the real clock; 244c265 (2026-10-29 morning) froze it | nothing more needed: 43 passed with /data and with an empty folder, no file under /data read (checked with an audit hook) |

E1's published result (`results/execution_e1.md`, 2026-10-27) was made before cf5a74a, so it is not affected; an
E1 replay run between 2026-10-28 22:00 UTC and this commit would have given the same numbers for every limit.

## Slow, not failing

With other runs in parallel, `test_pokemon.py` (walk forward, about 5 min a test), `test_model_zoo.py`,
`test_overfit_t2.py` and `test_model_factory_g2.py` each take 5 to 25 min; a per-file timeout of 15 min killed
them once. Each passes on its own in both modes. `test_ladder.py`'s smoke test on the real folder still reads /data
on purpose and skips where it is not mounted.
