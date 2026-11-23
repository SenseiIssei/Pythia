"""The trial register audit (results/trial_audit_prereg.md): every pre-registered study's declared trial count and
family against what R5's registry holds, and the missing ones appended as counted-only blocks.

The rule, as pre-registered: a trial is a configuration whose performance number a study computed (what the study
calls a trial; 0 for studies that compute none). The declared count is read from the result when it states it, else
from the pre-registration, and kept below (DECLARED) with that file and a verbatim quote: a quote no longer in its
file fails the row. R5 holds for a study every registry line whose source names its pre-registration or result
(`results/` or `research/lab/results/`), plus its own audit block; studies counted together in one of
metrics.TRIAL_SEED's blocks form a group, the group's declared sum against the block's n. The factory and small
ledgers' genomes are their factories' own count and not audited here; F3's pump.fun genomes live in their own ledger
(outside R5 by design) and the ladder adds them (ladder.register_total). Missing = declared less registered, at
least 0, appended through metrics.register as `audit:<study>:<family>` (n the missing count, sharpe and var null:
N grows, the variance stays), first id wins; registered above declared is shown, never removed.

  python -m lab.ops.trial_audit                 print the table, write nothing
  python -m lab.ops.trial_audit --register      append the missing blocks to R5 (PYTHIA_TRIALS_REGISTRY: the run's
                                                copy, T14 merges it) and write results/trial_audit.md's table
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from .. import metrics

RESULTS = Path(__file__).resolve().parents[2] / "results"
PREREG = "results/trial_audit_prereg.md"
F3_LEDGER = "pumpfun_rt/factory/ledger.jsonl"
# The audit's own two numbers: today's DSR of P_pool0 and of the weekly factory's best held-back genome, recomputed
# over the grown N (counted only, registered before the missing blocks).
RECHECK = [{"id": "audit:recheck:P_pool0", "family": "pumpfun", "n": 1, "sharpe": None, "source": PREREG},
           {"id": "audit:recheck:genome", "family": "factory", "n": 1, "sharpe": None, "source": PREREG}]

# (study, family, declared, file the count is read from, verbatim quote of one line there, seed block or "").
# A study over two families has a line per family; a study with no trial declares 0. "study:<name>": the same
# trials as that study's (M4H's 97 are M4H2's ids), counted there once. Read on 2026-11-16 from the files named;
# where a file states no number the count is the product it quotes (forward_power_t8: 38 = 36 hand, power.py
# registers the small books as hand, + 2 factory; pumpfun_activity: O9's 2 counted as hand in the 2026-10-21 batch).
DECLARED: list[tuple[str, str, int, str, str, str]] = [
    ('allocator_t9', 'hand', 4, 'allocator_t9.md',
     'Trials: 4 (`hand:t9:<history>:weighted_vs_<drawn|equal>`, counted only).', ''),
    ('analyst_local', 'hand', 2, 'analyst_local_prereg.md',
     'The PC model and the VPS model are one trial each; a later model is another.', ''),
    ('attention_wiki', 'hand', 13, 'attention_wiki.md',
     'perps_neutral_portfolio 3, attention_wiki 13, intraday_tsmom 9', 'hand:perps_attention_intraday'),
    ('book_depth_t4', 'hand', 0, 'book_depth_t4.md',
     'Data only: no trial, no performance', ''),
    ('btc_vrp', 'hand', 6, 'btc_vrp_prereg.md',
     '{P0, P10, CC} x {always, F}.', 'hand:batches_2026_10_21'),
    ('candles', 'hand', 47, 'candles.md',
     'This study ran on 948 hand trials, 600 factory genomes and its own 47', 'hand:x15_candles'),
    ('categories_local_ai2', 'hand', 3, 'categories_local_ai2_prereg.md',
     "R5's registry, family hand, counted only (no Sharpe):", ''),
    ('cost_aware_t7', 'factory', 33, 'cost_aware_t7.md',
     'Shadows admitted: none. Trials: 33 (`factory:t7_net:<key>` and `factory:t7_net:plain_signal`).', ''),
    ('cost_aware_t7', 'hand', 6, 'cost_aware_t7_prereg.md',
     '6 meta variants (family hand, in sample 2020-08-01 to 2023-12-31)', ''),
    ('crypto_open_gap', 'hand', 2, 'crypto_open_gap_prereg.md',
     '2 Sharpe trials (the rule on COIN and on MSTR) and 2 slope tests.', 'hand:batches_2026_10_21'),
    ('crypto_own', 'hand', 94, 'crypto_own_prereg.md',
     '| **This registration** | **94** |', 'hand:batches_2026_10_21'),
    ('daytrade_dt1', 'hand', 656, 'daytrade_dt1.md',
     "656 trials in R5's registry (hand family, with their in-sample Sharpes", ''),
    ('daytrade_eq2', 'small', 16, 'daytrade_eq2.md',
     "Trials (R5's registry, family small, before the validation numbers): 16, `small:eq2:<rule>:<cash|margin>`.", ''),
    ('depth_signal_o1', 'hand', 7, 'depth_signal_o1.md',
     "Trials (R5's registry, before the validation numbers): hand:o1:imb:xs, hand:o1:imb:ts", ''),
    ('disk_breakdown', 'hand', 0, 'disk_breakdown_prereg.md',
     "study: it makes no performance number, so no trial goes to R5's registry.", ''),
    ('dsr_bar_r7b', 'pumpfun', 0, 'dsr_bar_r7b.md',
     'the four `pumpfun:r7b:<rule>` trials were not made', ''),
    ('equities_training', 'hand', 120, 'equities_training.md',
     '**120** here (A 57, B1 30, C 6, B2 27): **1,668**', 'hand:x16_equities_training'),
    ('equity_sleeve', 'hand', 1, 'equity_sleeve_prereg.md',
     'H: a portfolio of **80 % breakout_top10 and 20 % SPY bought and held**, run on', ''),
    ('etf_books_eq1', 'small', 30, 'etf_books_eq1.md',
     "Trials (R5's registry, family small, before the validation numbers): 30, `small:eq1:<book>:<variant>:<broker>`.", ''),
    ('etf_routing', 'hand', 4, 'etf_routing_prereg.md',
     'D for each of the four books.', 'hand:batches_2026_10_21'),
    ('exec_alpaca_eq3', 'small', 4, 'exec_alpaca_eq3_prereg.md',
     '`small:eq3:exec_alpaca_<book>` (4 trials)', ''),
    ('exec_dryrun_l1', 'small', 11, 'exec_dryrun_l1.md',
     "11 counted trials in R5's", ''),
    ('exit_shadow', 'hand', 2, 'exit_shadow_prereg.md',
     'Bonferroni over the two tests);', ''),
    ('flush_long', 'hand', 8, 'flush_long_prereg.md',
     'X {3 %, 5 %} x instrument {BTC, top-5 basket} x H {3, 7} = 8.', 'hand:batches_2026_10_21'),
    ('forward_audit', 'hand', 0, 'forward_audit.md',
     'No Sharpe trial, nothing added to the pool.', ''),
    ('forward_power_t8', 'factory', 2, 'forward_power_t8.md',
     "38 trials in R5's registry (32 records", ''),
    ('forward_power_t8', 'hand', 36, 'forward_power_t8.md',
     "38 trials in R5's registry (32 records", ''),
    ('funding_carry', 'hand', 13, 'funding_carry_prereg.md',
     '3 signals x 2 sizes x 2 rebalances = 12 books, plus R = 13.', 'hand:batches_2026_10_21'),
    ('gated_btc', 'hand', 4, 'gated_btc_prereg.md',
     '- D for each of the 4 books: 4.', 'hand:director_2026_10_20'),
    ('genome_gates', 'hand', 4, 'genome_gates_prereg.md',
     '(`gated_btc` 4, this one 4, `m4_residual` 1): **1,724** trials', 'hand:director_2026_10_20'),
    ('hedged_breakout', 'hand', 2, 'hedged_breakout.md',
     'positioning_xs 5, taker_imbalance_xs 13, hedged_breakout 2, pead_xbrl 4', 'hand:positioning_taker_hedged_pead'),
    ('hl_funding_t11', 'hand', 5, 'hl_funding_t11.md',
     "5 trials in R5's registry (hand family; the", ''),
    ('intraday_tsmom', 'hand', 9, 'intraday_tsmom.md',
     '25 registered together on 2026-10-21: perps_neutral_portfolio 3, attention_wiki 13, intraday_tsmom 9', 'hand:perps_attention_intraday'),
    ('kraken_fee_s1', 'small', 8, 'kraken_fee_s1.md',
     "validation window 2024-01-01 to 2026-06-30 only (the lockbox stays shut). 8 counted trials in R5's registry", ''),
    ('kraken_funding_gap', 'hand', 4, 'kraken_funding_gap_prereg.md',
     'theta {20 %, 50 %} x W {24 h, 72 h} = 4. **Pool: 1,777** (see', 'hand:batches_2026_10_21'),
    ('ladder_promotion_a4', 'factory', 0, 'ladder_promotion_a4_prereg.md',
     'nothing and makes no number and no trial.', ''),
    ('ladder_pumpfun', 'pumpfun', 5, 'ladder_pumpfun.md',
     'Five trials, counted only (`pumpfun:ladder:<rule>`, family `pumpfun`), in every DSR', ''),
    ('leak_coverage', 'hand', 0, 'leak_coverage_prereg.md',
     'None. The leak check answers yes or no per function and makes no performance number', ''),
    ('leak_harness', 'hand', 0, 'leak_harness_prereg.md',
     'on no window of returns. It registers no trial in `<data>/trials/registry.jsonl`', ''),
    ('m4_perps_forward_audit', 'hand', 0, 'm4_perps_forward_audit.md',
     "a wallet or the engine reads was changed. No trial: R5's registry does not change.", ''),
    ('m4_residual', 'hand', 1, 'm4_residual_prereg.md',
     '(`gated_btc` 4, `genome_gates` 4, this one 1): **1,724** trials, noise bar', 'hand:director_2026_10_20'),
    ('m4_step2', 'hand', 26, 'm4_step2_prereg.md',
     '26 hand, 4 small. The run writes them to a copy of the registry', ''),
    ('m4_step2', 'small', 4, 'm4_step2_prereg.md',
     '26 hand, 4 small. The run writes them to a copy of the registry', ''),
    ('m4h', 'small', 97, 'm4h.md',
     "Run 2026-10-30, the lockbox not read. 97 trials in R5's registry (small family, with their in-sample Sharpes,", 'study:m4h2'),
    ('m4h2', 'small', 97, 'm4h2_prereg.md',
     'in-sample Sharpe. 97 trials, registered before any out-of-sample number as before. M4H registered none.', ''),
    ('m4l', 'small', 2, 'm4l.md',
     "2 trials in R5's registry", ''),
    ('market_structure_i1', 'hand', 0, 'market_structure_i1_prereg.md',
     'No Sharpe trial (no strategy is selected or backtested); 304 tests counted,', ''),
    ('model_review', 'hand', 29, 'model_review_prereg.md',
     'adds the Sharpe trials counted below (**29**). Deflation as in X6: pooled', 'hand:c16_to_x11'),
    ('model_upgrades', 'hand', 18, 'model_upgrades.md',
     '18 here (c2): **1,548**, a noise bar of Sharpe 2.69. The next study starts', 'hand:c16_to_x11'),
    ('onchain_meme', 'small', 3, 'onchain_meme_prereg.md',
     'These 3 trials join the global pool: 907 hand trials, 600 factory genomes and 386 pump.fun trials', ''),
    ('onchain_stage2', 'small', 0, 'onchain_stage2_prereg.md',
     'Written and committed before any stage-2 code exists and before any book traded on chain, on paper beyond', ''),
    ('overfit_yardsticks', 'hand', 0, 'overfit_yardsticks.md',
     "None registered by this run: the PBO and CPCV above are on genomes already counted, in sample only, and the zoo's", ''),
    ('pead_xbrl', 'hand', 4, 'pead_xbrl.md',
     'positioning_xs 5, taker_imbalance_xs 13, hedged_breakout 2, pead_xbrl 4', 'hand:positioning_taker_hedged_pead'),
    ('perps_neutral_portfolio', 'hand', 3, 'perps_neutral_portfolio.md',
     '25 registered together on 2026-10-21: perps_neutral_portfolio 3, attention_wiki 13, intraday_tsmom 9', 'hand:perps_attention_intraday'),
    ('pit_universe_t5', 'hand', 18, 'pit_universe_t5.md',
     "`lab.experiments.pit_universe_t5`. 18 trials in R5's registry (`hand:t5_pit:<rule>:<universe>`). In sample and", ''),
    ('polymarket', 'hand', 16, 'polymarket.md',
     '16 Sharpe trials (6 registered twin variants, 8 addendum checks, 2 live', 'hand:polymarket'),
    ('positioning_xs', 'hand', 5, 'positioning_xs_prereg.md',
     'and the 24 trials registered here (`positioning_xs` 5, `taker_imbalance_xs`', 'hand:positioning_taker_hedged_pead'),
    ('progress_page_u1', 'hand', 0, 'progress_page_u1_prereg.md',
     'None. The page tests nothing, picks nothing among variants and measures no new statistic', ''),
    ('pumpfun_activity', 'hand', 2, 'pumpfun_activity_prereg.md',
     '- Q1 and Q2 count as 2 trials in the global pool from today (pool 1,836', 'hand:batches_2026_10_21'),
    ('pumpfun_adaptive_a1', 'pumpfun', 29, 'pumpfun_adaptive_a1.md',
     "Trials: 26 model comparisons and 3 strategy comparisons in this study (the deflation's counts).", ''),
    ('pumpfun_bombers', 'pumpfun', 12, 'pumpfun_bombers.md',
     'two days out of sample. Trials: 12.', ''),
    ('pumpfun_clock_audit', 'pumpfun', 0, 'pumpfun_clock_audit.md',
     "No trial: R5's registry does not change.", ''),
    ('pumpfun_creation_gap', 'pumpfun', 3, 'pumpfun_creation_gap.md',
     "Three trials in R5's registry, family pumpfun, counted only (`pumpfun:creation_gap:split`,", ''),
    ('pumpfun_entry_e2', 'pumpfun', 29, 'pumpfun_entry_e2.md',
     "the 29 trials were registered into a copy of R5's", ''),
    ('pumpfun_exit_runners', 'pumpfun', 6, 'pumpfun_exit_runners.md',
     'Trials: 6 (`strategies.EXIT_RUNNER_TRIALS`).', ''),
    ('pumpfun_exits_y8', 'pumpfun', 5, 'pumpfun_exits_y8.md',
     'Trials: 5 (`strategies.EXITS_Y8_TRIALS`).', ''),
    ('pumpfun_flow_exit_x14r2', 'pumpfun', 11, 'pumpfun_flow_exit_x14r2.md',
     "Pre-registration: `results/pumpfun_flow_exit_x14r2_prereg.md` (11 trials in R5's registry, committed before the", ''),
    ('pumpfun_freeride', 'pumpfun', 16, 'pumpfun_freeride.md',
     'and when it comes it mostly ends right there. Trials: 16', ''),
    ('pumpfun_gap_reconcile_g1', 'pumpfun', 5, 'pumpfun_gap_reconcile_g1.md',
     "Four trials in R5's registry, family pumpfun, counted only (`pumpfun:gap_g1:*`); no Sharpe, no DSR.", ''),
    ('pumpfun_ledger_taint_p1', 'hand', 2, 'pumpfun_ledger_taint_p1.md',
     "Two trials in R5's registry, counted only (`hand:p1:ledger_taint`, `hand:p1:ledger_taint_strict`)", ''),
    ('pumpfun_live_twin', 'pumpfun', 5, 'pumpfun_live_twin.md',
     "Five trials in R5's registry, family pumpfun, counted only (`pumpfun:live_twin:*`); no Sharpe, no DSR", ''),
    ('pumpfun_lock', 'pumpfun', 12, 'pumpfun_lock.md',
     'into small gains. Trials: 12 (`strategies.LOCK_Y12_TRIALS`).', ''),
    ('pumpfun_os1', 'pumpfun', 2, 'pumpfun_os1.md',
     "Pre-registration: `results/pumpfun_os1_prereg.md` (2 trials in R5's registry, committed before the first run).", ''),
    ('pumpfun_pool0', 'pumpfun', 1, 'pumpfun_pool0_prereg.md',
     'One trial (`strategies.POOL0_TRIALS`), counted in the global pool.', ''),
    ('pumpfun_pool_state_fix', 'pumpfun', 81, 'pumpfun_pool_state_fix_prereg.md',
     '`<rule>@e1_<pair>` (`slippage_e1.shadow_books`): 40 books.', ''),
    ('pumpfun_real_latency', 'pumpfun', 140, 'pumpfun_real_latency.md',
     'Pre-registration: `results/pumpfun_real_latency_prereg.md` (140 trials,', ''),
    ('pumpfun_realistic_fit_window', 'pumpfun', 3, 'pumpfun_realistic_fit_window.md',
     "Three trials in R5's registry, family pumpfun, counted only (`pumpfun:fit_window:*`)", ''),
    ('pumpfun_rugfilter', 'pumpfun', 12, 'pumpfun_rugfilter.md',
     "Trials: 12 (`strategies.RUGFILTER_Y16_TRIALS`; R3's 20 candidates were chosen in sample).", ''),
    ('pumpfun_runner', 'pumpfun', 4, 'pumpfun_runner.md',
     'Trials: 4 (`strategies.RUNNER_Y11_TRIALS`).', ''),
    ('pumpfun_select_y9', 'pumpfun', 10, 'pumpfun_select_y9.md',
     'Trials: 10 (`strategies.SELECT_Y9_TRIALS`).', ''),
    ('pumpfun_selection_gap_p2', 'hand', 5, 'pumpfun_selection_gap_p2.md',
     "Five trials in R5's registry, counted only (`hand:p2:*`); no Sharpe, no DSR.", ''),
    ('pumpfun_shapes_y17', 'pumpfun', 4, 'pumpfun_shapes_y17_prereg.md',
     'A coin younger than 10 s at the signal keeps its entry. 4 trials.', ''),
    ('pumpfun_smallwallet_r2', 'pumpfun', 336, 'pumpfun_smallwallet_r2_prereg.md',
     '336 settings, counted as 336 trials.', ''),
    ('pumpfun_social_y14', 'pumpfun', 4, 'pumpfun_social_y14.md',
     'Pre-registration: `results/pumpfun_social_y14_prereg.md` (4 trials)', ''),
    ('pumpfun_trends_y10', 'pumpfun', 10, 'pumpfun_trends_y10.md',
     'The live service builds its engine without the tracker and is unchanged. Trials: 10', ''),
    ('range_forecast_rf1', 'hand', 12, 'range_forecast_rf1.md',
     "12 trials in R5's registry (hand family, counted without a", ''),
    ('reachable_venues_t12', 'hand', 17, 'reachable_venues_t12.md',
     "17 trials in R5's registry (hand", ''),
    ('readiness_ladder', 'hand', 0, 'readiness_ladder_prereg.md',
     "no trial. Recomputing a stored DSR against today's registry (step 2) is the same candidate", ''),
    ('recordings_t13', 'hand', 0, 'recordings_t13.md',
     "number, no trial in R5's registry. It stops nothing.", ''),
    ('slippage_e1', 'hand', 60, 'slippage_e1.md',
     "60 trials in R5's registry, counted only (`hand:e1:*`); no Sharpe, no DSR.", ''),
    ('smallaccount_r10', 'small', 0, 'smallaccount_r10_prereg.md',
     '(`small:l1`, R5); R10 adds none.', ''),
    ('smallaccount_s1', 'small', 8, 'smallaccount_s1_prereg.md',
     '- Trials: 8 candidates; the grid is a description, not a search', 'small:s1'),
    ('smallaccount_s2', 'small', 8, 'smallaccount_s2.md',
     'deflated p under 0.05 (8 trials)', 'small:s2'),
    ('smallaccount_weekly', 'small', 7, 'smallaccount_weekly_prereg.md',
     "Seven new rules, each one trial of R5's registry in the small family", ''),
    ('survey_equities', 'hand', 33, 'survey_equities_prereg.md',
     'starts at 1,740 and is 1,773 with these 33 trials.', 'hand:batches_2026_10_21'),
    ('swing_sw1', 'small', 222, 'swing_sw1.md',
     "222 trials in R5's registry (small family, with their in-sample", ''),
    ('taker_imbalance_xs', 'hand', 13, 'taker_imbalance_xs.md',
     'positioning_xs 5, taker_imbalance_xs 13, hedged_breakout 2, pead_xbrl 4', 'hand:positioning_taker_hedged_pead'),
    ('ten_eur_p3', 'hand', 3, 'ten_eur_p3_prereg.md',
     "Three in R5's registry, family hand, counted only, registered by the daily job", ''),
    ('treasury_premium', 'hand', 2, 'treasury_premium.md',
     '(its 2 trials are already counted in the pool, though nothing was run)', 'hand:batches_2026_10_21'),
    ('trend_shorts', 'hand', 12, 'trend_shorts_prereg.md',
     '5 variants x 2 books = 10, plus the difference D of each pick against gated', 'hand:batches_2026_10_21'),
    ('two_leads_t6', 'hand', 6, 'two_leads_t6_prereg.md',
     '`hand:t6:a:<M4|Carry|LowVol|EW|IV|ERC>` (family hand, 6)', ''),
    ('two_leads_t6', 'small', 3, 'two_leads_t6_prereg.md',
     '`small:t6:07493e8a8adb:cpcv` (family small, 3)', ''),
    ('two_leads_t6b', 'hand', 28, 'two_leads_t6.md',
     "`tests/test_two_leads_t6b.py`. 10 trials in R5's registry.", ''),
    ('vix_carry', 'hand', 8, 'vix_carry_prereg.md',
     "(the owner's count), plus this batch's 22 Sharpe trials (`vix_carry` 8,", 'hand:batches_2026_10_21'),
    ('weekly_capital_line', 'hand', 0, 'weekly_capital_line_prereg.md',
     'not change; family none. No performance number is written here.', ''),
    ('weekly_page_w1', 'hand', 0, 'weekly_page_w1_prereg.md',
     'None. The page tests nothing, picks nothing among variants and measures no new statistic', ''),
    ('xstocks_t10', 'small', 1, 'xstocks_t10.md',
     "One trial in R5's registry (`small:t10:xstocks_premium`, counted only)", ''),
    ('trial_audit', 'factory', 1, 'trial_audit_prereg.md',
     '(`audit:recheck:P_pool0`, family pumpfun; `audit:recheck:genome`, family factory).', ''),
    ('trial_audit', 'pumpfun', 1, 'trial_audit_prereg.md',
     '(`audit:recheck:P_pool0`, family pumpfun; `audit:recheck:genome`, family factory).', ''),
]


# A missing study whose result stored its trials' in-sample Sharpes (annual, daily books, R5's convention) under the
# ids it named: those lines instead of a counted-only block (the first id wins if the study registers them later).
SERIES: dict[str, list[tuple[str, float | None]]] = {
    # results/hl_funding_t11.md, "Every variant" (IS Sharpe) and its trial list; the 10k variant has no IS Sharpe
    "hl_funding_t11": [("hand:t11:hl_funding:15_8", 2.86), ("hand:t11:hl_funding:15_24", 6.55),
                       ("hand:t11:hl_funding:30_8", 4.65), ("hand:t11:hl_funding:30_24", 7.34),
                       ("hand:t11:hl_funding:30_24:10k", None)],
}


def studies(results: Path = RESULTS) -> list[str]:
    """Every pre-registered study in results/, by name (results/<name>_prereg.md)."""
    return sorted(p.name[:-len("_prereg.md")] for p in results.glob("*_prereg.md"))


def _files(source: str) -> set[str]:
    """The results files a registry line's source names: `results/<file>.md` with or without research/lab/."""
    return set(re.findall(r"(?:research/lab/)?results/([\w.-]+?\.md)", source or ""))


def held(rows: list[dict], study: str, family: str) -> int:
    """R5's trials of one study and family: lines whose source names its pre-registration or result (the seed blocks
    only through their group), its audit block."""
    mine, seed = {f"{study}_prereg.md", f"{study}.md"}, {b["id"] for b in metrics.TRIAL_SEED}
    return sum(int(r.get("n") or 1) for r in rows if (r.get("family") or "hand") == family and r["id"] not in seed
               and (_files(r.get("source", "")) & mine or r["id"] == block_id(study, family)))


def block_id(study: str, family: str) -> str:
    return f"audit:{study}:{family}"


def quote_ok(file: str, quote: str, results: Path = RESULTS) -> bool:
    p = results / file
    try:
        return any(quote in line for line in p.read_text(encoding="utf-8").splitlines())
    except OSError:
        return False


def audit(rows: list[dict] | None = None, results: Path = RESULTS, declared=None) -> dict:
    """{"rows": one per study and family (study, family, declared, registered, missing, file, quote_ok, group),
    "groups": the seed blocks' groups, "undeclared": pre-registered studies with no DECLARED line}."""
    rows = metrics.read_registry() if rows is None else rows
    declared = DECLARED if declared is None else declared
    by_id = {r["id"]: r for r in rows}
    out, groups = [], {}
    for study, fam, n, file, quote, seed in declared:
        ok = quote_ok(file, quote, results)
        r = {"study": study, "family": fam, "declared": n, "file": file, "quote_ok": ok, "group": seed}
        if seed.startswith("study:"):
            r.update({"registered": None, "missing": None, "group": seed[6:]})
        elif seed:
            groups.setdefault(seed, []).append(r)
            r.update({"registered": None, "missing": None})
        else:
            h = held(rows, study, fam)
            r.update({"registered": h, "missing": max(n - h, 0) if ok else None})
        out.append(r)
    gs = []
    for seed, rs in groups.items():
        fam = rs[0]["family"]
        b = by_id.get(seed)
        h = (int(b.get("n") or 1) if b else 0) + held(rows, f"group_{seed.replace(':', '_')}", fam)
        d = sum(r["declared"] for r in rs)
        ok = all(r["quote_ok"] for r in rs)
        gs.append({"group": seed, "family": fam, "studies": [r["study"] for r in rs], "declared": d, "registered": h,
                   "missing": max(d - h, 0) if ok else None, "quote_ok": ok})
    have = {r["study"] for r in out}
    return {"rows": out, "groups": gs, "undeclared": [s for s in studies(results) if s not in have]}


def missing_rows(a: dict) -> list[dict]:
    """The counted-only blocks for what R5 lacks: one per study and family, one per seed group."""
    out = []
    for r in a["rows"]:
        ser = SERIES.get(r["study"]) or []
        if r["missing"] and r["missing"] == len(ser) and not r["registered"]:
            out += [{"id": i, "family": r["family"], "n": 1, "sharpe": x, "var": None,
                     "source": f"results/{r['file']} ({r['study']}: its trial list, in-sample Sharpe; the trial audit)"}
                    for i, x in ser]
        elif r["missing"]:
            out.append({"id": block_id(r["study"], r["family"]), "family": r["family"], "n": r["missing"],
                        "sharpe": None, "var": None,
                        "source": f"results/{r['file']} ({r['study']}: declared {r['declared']}, "
                                  f"registered {r['registered']}; the trial audit)"})
    for g in a["groups"]:
        if g["missing"]:
            s = f"group_{g['group'].replace(':', '_')}"
            out.append({"id": block_id(s, g["family"]), "family": g["family"], "n": g["missing"], "sharpe": None,
                        "var": None, "source": f"{g['group']} ({', '.join(g['studies'])}: declared {g['declared']}, "
                                               f"registered {g['registered']}; the trial audit)"})
    return out


def f3_trials(root: Path) -> int:
    from ..pumpfun_rt import factory as F
    return F.pool(F.read_ledger(root / F3_LEDGER))[1]


def table(a: dict) -> list[str]:
    def c(x):
        return "-" if x is None else f"{x:,}"
    md = ["| study | family | declared | registered | missing | read from |", "|---|---|---|---|---|---|"]
    for r in sorted(a["rows"], key=lambda r: (r["study"], r["family"])):
        reg = f"in {r['group']}" if r["group"] else c(r["registered"])
        src = f"`results/{r['file']}`" + ("" if r["quote_ok"] else " (quote gone)")
        md.append(f"| {r['study']} | {r['family']} | {r['declared']:,} | {reg} | {c(r['missing'])} | {src} |")
    if a["groups"]:
        md += ["", "| seed block | family | studies | declared | registered | missing |", "|---|---|---|---|---|---|"]
        for g in a["groups"]:
            md.append(f"| `{g['group']}` | {g['family']} | {', '.join(g['studies'])} | {g['declared']:,} | "
                      f"{g['registered']:,} | {c(g['missing'])} |")
    if a["undeclared"]:
        md += ["", "Pre-registered with no declared count here: " + ", ".join(a["undeclared"])]
    return md


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--register" in argv:
        metrics.register(RECHECK)
    a = audit()
    print("\n".join(table(a)))
    add = missing_rows(a)
    print(f"\nmissing: {sum(r['n'] for r in add):,} trials in {len(add)} blocks")
    if "--register" in argv:
        new = metrics.register(add)
        print(f"appended {sum(r['n'] for r in new):,} trials in {len(new)} blocks to {metrics.registry_path()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
