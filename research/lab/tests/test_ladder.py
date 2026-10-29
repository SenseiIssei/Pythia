"""T3: the readiness ladder on fake reports, one candidate stopped at each step for the condition named; open
conditions that do not block on step 1 and fail closed from step 2 (the audit of 2026-10-29: no leak record, no PBO,
no T8 report, a stale DSR; shadow days by date); the briefing's card and Lab Live's step; the recorded data of 2026-10-27 and (when
mounted) the lab's own, where nothing stands above step 3. The moved-out-capital case of the readiness drawdown is in
tests/test_readiness.py (test_capital_moved_out_is_not_a_drawdown).

Run from research/lab:  python -m pytest tests/test_ladder.py
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest

from lab import metrics
from lab.ops import briefing, ladder, lablive, notify
from test_i18n import no_english

NOW = int(datetime(2026, 11, 20, 8, 0, tzinfo=timezone.utc).timestamp() * 1000)
SPEC_ID = "abcdef123456"
RECORDED = Path(__file__).parent / "fixtures" / "briefing_2026-10-27"


def ts(day: str) -> int:
    return int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp())


def write(root: Path, rel: str, d) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(d if isinstance(d, str) else json.dumps(d), encoding="utf-8")


def jsonl(root: Path, rel: str, rows: list[dict]) -> None:
    write(root, rel, "".join(json.dumps(r) + "\n" for r in rows))


def journal(root: Path, rel: str, days: int, head: str = "date,equity") -> None:
    first = datetime(2026, 10, 1, tzinfo=timezone.utc).timestamp()
    write(root, rel, head + "\n" + "".join(f"{_day(first + i * 86_400)},1.0\n" for i in range(days)))


def _day(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d")


@pytest.fixture()
def env(tmp_path, monkeypatch):
    data, results = tmp_path / "data", tmp_path / "results"
    data.mkdir()
    results.mkdir()
    monkeypatch.setenv("PYTHIA_DATA", str(data))
    monkeypatch.delenv("PYTHIA_REPORTS", raising=False)
    monkeypatch.delenv("PYTHIA_TRIALS_REGISTRY", raising=False)
    jsonl(data, "trials/registry.jsonl", [{"id": "factory:block", "family": "factory", "source": "test", "n": 500,
                                           "sharpe": None, "var": 1e-4}])
    for f in ("smallaccount_s1_prereg.md", "smallaccount_s1.md", "factory_lockbox_r6.md"):
        (results / f).write_text("# x\n", encoding="utf-8")
    return data, results


# Commits: S1's pre-registration before its results; R6 on 2026-10-27.
COMMITS = {"smallaccount_s1_prereg.md": (ts("2026-10-23"), "a1"), "smallaccount_s1.md": (ts("2026-10-24"), "b2"),
           "factory_lockbox_r6.md": (ts("2026-10-27"), "c3")}


def added(commits=None):
    commits = COMMITS if commits is None else commits
    return lambda p: commits.get(p.name)


def run(env, commits=None) -> dict:
    data, results = env
    return {r["id"]: r for r in ladder.build(data, NOW, results=results, added=added(commits))["rows"]}


# ---------------------------------------------------------------- a paper book (S1) up to step 3

def s1_book(data: Path, upto: int, **kw) -> None:
    write(data, "reports/smallaccount/latest.json",
          {"books": {"small50_tsmom1": {"variant": "S1 small account · 50 EUR · 28d momentum", "started": "2026-10-24",
                                        "equity_eur": 49.0}}})
    if upto >= 2:
        late = {"cagr": kw.get("late", 0.12), "dsr": kw.get("dsr", 0.97), "dsr_small": kw.get("dsr_small", 0.96)}
        write(data, "reports/smallaccount_r10/latest.json",
              {"rows": [{"study": "S1", "name": "tsmom1", "crypto": True, "late@40": late, "late@100": late}]})
        write(data, "reports/leak/latest.json",
              {"results": [{"kind": "book", "name": "smallaccount small50_tsmom1", "ok": kw.get("leak_ok", True),
                            "why": "pass"}]})
    if upto >= 3:
        journal(data, "paper/small50_tsmom1/journal.csv", kw.get("days", 30))


def test_no_preregistration_is_step_0(env):
    data, _ = env
    write(data, "reports/forward/latest.json", {"books": [{"kind": "book", "name": "tsmom", "since": "2026-10-06",
                                                          "days": 22}]})
    r = run(env)["book:tsmom"]
    assert r["step"] == 0 and r["missing"] == ["prereg"]
    assert "no pre-registration" in r["next"]


def test_a_preregistration_in_the_same_commit_as_its_results_is_not_one(env):
    s1_book(env[0], 1)
    r = run(env, {**COMMITS, "smallaccount_s1_prereg.md": (ts("2026-10-24"), "b2")})["book:small50_tsmom1"]
    assert r["step"] == 0 and r["missing"] == ["prereg_date"] and "same commit" in r["next"]
    r = run(env, {**COMMITS, "smallaccount_s1_prereg.md": (ts("2026-10-25"), "z9")})["book:small50_tsmom1"]
    assert r["step"] == 0 and r["missing"] == ["prereg_date"]


def test_without_git_the_title_date_or_open(env):
    data, results = env
    s1_book(data, 1)
    r = run(env, {})["book:small50_tsmom1"]
    assert r["step"] == 1 and "prereg_date" in r["open"]          # no date anywhere: open, not blocking
    (results / "smallaccount_s1_prereg.md").write_text("# S1 (pre-registration, 2026-10-30)\n", encoding="utf-8")
    r = run(env, {})["book:small50_tsmom1"]                       # after the book's first day 2026-10-24
    assert r["step"] == 0 and r["missing"] == ["prereg_date"]


def test_pre_registered_but_untested_is_step_1(env):
    s1_book(env[0], 1)
    r = run(env)["book:small50_tsmom1"]
    assert r["step"] == 1 and set(r["missing"]) == {"leak", "late", "era", "dsr_all", "dsr_family", "pbo"}
    assert r["open"] == []                                         # no T1 report, no T2 for a book: they fail
    steps = {x["id"]: x for x in r["steps"]["2"]}
    assert "no T1 report" in steps["leak"]["value"] and "not measured" in steps["pbo"]["value"]


@pytest.mark.parametrize("kw, miss", [({"dsr": 0.5}, "dsr_all"), ({"dsr_small": 0.94}, "dsr_family"),
                                      ({"late": -0.01}, "late"), ({"leak_ok": False}, "leak")])
def test_each_tested_condition_holds_a_book_at_step_1(env, kw, miss):
    s1_book(env[0], 3, **kw)
    r = run(env)["book:small50_tsmom1"]
    assert r["step"] == 1 and set(r["missing"]) == {miss, "pbo"}


def test_a_book_without_a_pbo_stays_at_step_1(env):
    s1_book(env[0], 3)                                             # leak passed, R10 passes, 30 days logged
    r = run(env)["book:small50_tsmom1"]
    assert r["step"] == 1 and r["missing"] == ["pbo"] and "not measured" in r["next"]


def test_a_book_not_in_t1s_list_fails_the_leak_check(env):
    data, _ = env
    s1_book(data, 3)
    write(data, "reports/leak/latest.json", {"results": [{"kind": "book", "name": "tsmom", "ok": True}]})
    r = run(env)["book:small50_tsmom1"]
    assert r["step"] == 1 and set(r["missing"]) == {"leak", "pbo"} and "not in T1's book list" in r["next"]


def test_shadow_days_are_unique_dates(tmp_path):
    p = tmp_path / "journal.csv"
    p.write_text("date,equity\n" + "".join(f"2026-10-{1 + i // 2:02d},1.0\n" for i in range(30)), encoding="utf-8")
    assert ladder._days_in(p) == 15                                # a rerun's second row of a day is not a day
    p.write_text("day,equity\n2026-10-01,1\n2026-10-01T09:00,1\n2026-10-02,1\n\n", encoding="utf-8")
    assert ladder._days_in(p) == 2                                 # no date column: the first; its first 10 chars
    assert ladder._days_in(tmp_path / "none.csv") == 0


def test_r10s_results_table_when_its_report_is_missing(env):
    data, results = env
    s1_book(data, 1)
    shutil.copy(Path(__file__).parents[1] / "results" / "smallaccount_r10.md", results / "smallaccount_r10.md")
    rows = ladder.r10_rows(data, results)
    assert rows["S1 tsmom1"]["late_cagr"] == pytest.approx(14.3) and rows["S1 tsmom1"]["dsr_family"] == 0.028
    assert rows["S2 spy_trend"]["crypto"] is False and rows["F2 f2 07493e8a8adb"]["dsr_all"] == 0.0
    r = run(env)["book:small50_tsmom1"]
    assert r["step"] == 1 and set(r["missing"]) == {"leak", "dsr_all", "dsr_family", "pbo"}


def test_s1s_era_line_names_kraken_s_fee_and_the_rerun_replaces_r10s_s1_rows(env):
    from lab.exec import kraken_fee as kf
    data, results = env
    s1_book(data, 2)
    late = {"cagr": -0.05, "dsr": 0.01, "dsr_small": 0.02}
    write(data, "reports/kraken_fee_s1/latest.json",
          {"rows": [{"study": "S1", "name": "tsmom1", "crypto": True, "late@40": late, "late@100": late},
                    {"study": "S2", "name": "spy_trend", "late@40": late, "late@100": late}]})
    rows = ladder.r10_rows(data, results)
    assert rows["S1 tsmom1"]["late_cagr"] == pytest.approx(-5.0) and "S2 spy_trend" not in rows
    assert rows["S1 tsmom1"]["path"] == "reports/kraken_fee_s1/latest.json"
    era = {x["id"]: x for x in run(env)["book:small50_tsmom1"]["steps"]["2"]}["era"]
    assert era["ok"] and f"Kraken {kf.kraken_fee() * 100:.2f} % taker" in era["value"] and kf.URL in era["value"]


# ---------------------------------------------------------------- a weekly factory genome up to step 6

def today() -> tuple[int, int]:
    """Today's N of all and of the factory family in the test's registry (the seed and 500 factory trials)."""
    p = metrics.trial_pool()
    return p["n_trials"], p["families"]["factory"]["n_trials"]


def holdout(**kw) -> dict:
    n_all, n_fam = today()
    return {"run": "2026-11-01", "date": "2026-10-31", "key": SPEC_ID, "name": "low vol", "behaviour": "beh1",
            "decision": "shadow", "deflated_p": 0.97, "dsr_family": 0.96, "oos_late_sharpe": 0.5,
            "pool_trials": n_all, "family_trials": n_fam,
            "gates": {"stress": {"passed": True, "why": "0.6 at 70 bps"}}, **kw}


def genome(data: Path, upto: int, look: dict | None = None, record: dict | None = None, leak: bool = True,
           t8: bool = True, **kw) -> None:
    pbo = kw.pop("pbo", 0.1)
    jsonl(data, "factory/holdout.jsonl", [holdout(**kw)])
    if pbo is not None:
        write(data, "factory/runs/2026-11-01.json", {"night": {"family": {"pbo": pbo}}})
    jsonl(data, "factory/leak_passed.jsonl", [{"run": "2026-11-01", "date": "2026-10-31", "key": SPEC_ID, "ok": True,
                                               "reason": "no leak (12 runs at 3 cuts)"}] if leak else [])
    if upto >= 3:
        write(data, f"factory/shadow/{SPEC_ID}.json", {"key": SPEC_ID, "name": "low vol", "status": "active",
                                                   "entered_run": "2026-11-01", "entry_day": "2026-10-31"})
        journal(data, f"factory/shadow/{SPEC_ID}.csv", 30)
        if t8:
            write(data, "reports/shadow/latest.json", {"rows": [{"id": f"weekly:{SPEC_ID}", "ok": True,
                                                                 "why": "logged before the outcome"}]})
    if upto >= 4:
        jsonl(data, "factory/lockbox.jsonl", [{"look": 1, "factory": "factory", "date": "2026-11-01", "key": SPEC_ID,
                                               "behaviour": "beh1", "dsr": 0.6, "looks": 1, "benchmark": "btc_eth",
                                               **(look or {})}])
    if upto >= 5:
        swaps = [{"ok": True, "cost_bps": 3.0, "model_bps": 2.0} for _ in range(12)]
        write(data, "reports/execution/latest.json",
              {"books": {f"weekly:{SPEC_ID}": {"start": "2026-08-01", "cap_eur": 50, "topups": [], "swaps": swaps,
                                           "reconcile_mismatches": 0, "drift_pct": 0.4, **(record or {})}}})


def test_a_genome_climbs_to_step_5_and_only_the_owner_goes_further(env):
    genome(env[0], 5)
    r = run(env)[f"weekly:{SPEC_ID}"]
    assert r["kind"] == "shadow" and r["step"] == 5 and r["step_name"] == "execution", r["next"]
    assert r["missing"] == ["owner"] and "only the owner" in r["next"]
    assert r["open"] == []


@pytest.mark.parametrize("upto, step, miss", [(2, 2, ["days", "before"]), (3, 3, ["look"]), (4, 4, ["record"])])
def test_a_genome_stops_where_its_evidence_ends(env, upto, step, miss):
    genome(env[0], upto)
    r = run(env)[f"weekly:{SPEC_ID}"]
    assert r["step"] == step and r["missing"] == miss, r


def test_without_a_t8_report_a_shadow_stays_at_step_2(env):
    genome(env[0], 5, t8=False)
    r = run(env)[f"weekly:{SPEC_ID}"]
    assert r["step"] == 2 and r["missing"] == ["before"] and "no T8 report" in r["next"]


def test_shadow_days_by_date_not_by_row(env):
    data, _ = env
    genome(data, 5)
    write(data, f"factory/shadow/{SPEC_ID}.csv", "date,net_ret\n" + "".join(f"2026-10-{1 + i // 2:02d},0.0\n"
                                                                             for i in range(40)))
    r = run(env)[f"weekly:{SPEC_ID}"]                              # 40 rows, 20 dates
    assert r["step"] == 2 and r["missing"] == ["days"] and "20 of 30" in r["next"]


@pytest.mark.parametrize("kw, miss", [({"deflated_p": 0.9}, "dsr_all"), ({"dsr_family": None}, "dsr_family"),
                                      ({"pbo": 0.25}, "pbo"), ({"pbo": None}, "pbo"), ({"leak": False}, "leak"),
                                      ({"oos_late_sharpe": -0.1}, "late"),
                                      ({"gates": {"stress": {"passed": False, "why": "-0.2 at 70 bps"}}}, "era")])
def test_each_tested_condition_holds_a_genome_at_step_1(env, kw, miss):
    genome(env[0], 5, **kw)
    r = run(env)[f"weekly:{SPEC_ID}"]
    assert r["step"] == 1 and r["missing"] == [miss], r


def test_the_leak_harness_rejects_and_a_genome_without_a_clean_record_fails(env):
    data, _ = env
    genome(data, 5)
    jsonl(data, "factory/leaks.jsonl", [{"key": SPEC_ID, "reason": "moved at t"}])
    assert run(env)[f"weekly:{SPEC_ID}"]["missing"] == ["leak"]
    (data / "factory" / "leaks.jsonl").unlink()
    r = run(env)[f"weekly:{SPEC_ID}"]
    assert r["step"] == 5 and next(x for x in r["steps"]["2"] if x["id"] == "leak")["value"].startswith("no leak")
    genome(data, 5, leak=False)                                    # held back after T1 but no record: not by date
    r = run(env)[f"weekly:{SPEC_ID}"]
    assert r["step"] == 1 and r["missing"] == ["leak"] and "no clean leak record" in r["next"]
    genome(data, 5, leak=False, date="2026-10-20", run="2026-10-21")
    jsonl(data, "factory/runs/2026-10-21.json", [])                # an old run without T2's PBO
    r = run(env)[f"weekly:{SPEC_ID}"]
    assert r["step"] == 0 and r["missing"] == ["prereg_date"]       # R6 came after its first number
    r = run(env, {**COMMITS, "factory_lockbox_r6.md": (ts("2026-10-01"), "c3")})[f"weekly:{SPEC_ID}"]
    assert r["step"] == 1 and r["missing"] == ["leak", "pbo"] and r["open"] == []
    assert "held back before T1" in r["next"]


# ---------------------------------------------------------------- the DSR as of today's registry

def test_a_stale_dsr_without_its_series_is_refused(env):
    data, _ = env
    n_all, n_fam = today()
    genome(data, 5, deflated_p=0.99, pool_trials=677, dsr_family=0.99, family_trials=n_fam)
    r = run(env)[f"weekly:{SPEC_ID}"]                              # the weekly row of 2026-10-14: 677 trials
    assert r["step"] == 1 and r["missing"] == ["dsr_all"] and f"677 trials, today {n_all:,}" in r["next"]
    assert "stale" in r["next"]
    genome(data, 5, pool_trials=int(n_all * 0.95))                 # within DSR_STALE of today's: as written
    assert run(env)[f"weekly:{SPEC_ID}"]["step"] == 5
    genome(data, 5, pool_trials=None)
    assert run(env)[f"weekly:{SPEC_ID}"]["missing"] == ["dsr_all"]


def test_the_dsr_is_recomputed_from_the_stored_series(env):
    data, _ = env
    n_all, n_fam = today()
    rng = np.random.default_rng(1)
    strong = list(rng.normal(0.02, 0.01, 900))                     # daily Sharpe 2: passes any N
    noise = list(rng.normal(0.0, 0.01, 900))
    genome(data, 5, deflated_p=0.1, dsr_family=0.1, pool_trials=10, family_trials=1, oos_excess_returns=strong)
    r = run(env)[f"weekly:{SPEC_ID}"]                              # the row's own numbers are ignored
    assert r["step"] == 5
    v = {x["id"]: x["value"] for x in r["steps"]["2"]}
    assert f"recomputed over today's {n_all:,} trials" in v["dsr_all"] and f"{n_fam:,} factory" in v["dsr_family"]
    genome(data, 5, deflated_p=0.99, dsr_family=0.99, oos_excess_returns=noise + [None])
    r = run(env)[f"weekly:{SPEC_ID}"]
    assert r["step"] == 1 and r["missing"] == ["dsr_all", "dsr_family"]
    pool = metrics.trial_pool()
    want = metrics.dsr(np.array(noise), {"n_trials": pool["n_trials"], "var": pool["var"]})
    assert v["dsr_all"] != r["steps"]["2"][3]["value"] and f"{want:.3f} recomputed" in r["next"]


def test_without_the_registry_no_dsr_passes(env, monkeypatch):
    genome(env[0], 5)
    monkeypatch.setattr(ladder, "today_pool", lambda: None)
    r = run(env)[f"weekly:{SPEC_ID}"]
    assert r["step"] == 1 and r["missing"] == ["dsr_all", "dsr_family"] and "not readable" in r["next"]


def test_a_lockbox_look_against_the_wrong_benchmark_or_below_the_bar_fails(env):
    data, _ = env
    genome(data, 5, look={"benchmark": None})                      # the weekly factory's look is against BTC alone
    r = run(env)[f"weekly:{SPEC_ID}"]
    assert r["step"] == 3 and r["missing"] == ["bench"] and "needs BTC and ETH held" in r["next"]
    genome(data, 5, look={"dsr": 0.4})
    assert run(env)[f"weekly:{SPEC_ID}"]["missing"] == ["look_pass"]
    genome(data, 5, look={"key": "other", "behaviour": "beh1"})   # the same behaviour under another key counts
    assert run(env)[f"weekly:{SPEC_ID}"]["step"] == 5


@pytest.mark.parametrize("record, miss", [
    ({"cap_eur": 60}, "cap"), ({"topups": ["2026-09-15"]}, "topup"), ({"reconcile_mismatches": 1}, "reconcile"),
    ({"swaps": [{"ok": True, "cost_bps": 2, "model_bps": 2}] * 10 + [{"ok": False}, {"ok": False}]
      + [{"ok": True, "cost_bps": 2, "model_bps": 2}]}, "failed"),
    ({"swaps": [{"ok": True, "cost_bps": 5, "model_bps": 2}] * 10}, "costs"),
    ({"swaps": [{"ok": True, "cost_bps": 2, "model_bps": 2}] * 9}, "costs"),
    ({"drift_pct": -1.5}, "drift"), ({"start": "2026-09-01"}, "exec_days")])
def test_each_execution_rule_holds_it_at_step_4(env, record, miss):
    genome(env[0], 5, record=record)
    r = run(env)[f"weekly:{SPEC_ID}"]
    assert r["step"] == 4 and r["missing"] == [miss], r


def test_a_top_up_after_90_days_is_allowed(env):
    genome(env[0], 5, record={"topups": ["2026-11-05"]})
    assert run(env)[f"weekly:{SPEC_ID}"]["step"] == 5


def test_the_climb_stops_at_the_first_fail_and_open_blocks_from_step_2():
    c = ladder.cond
    steps = {1: [c("prereg", True), c("prereg_date", None)], 2: [c("late", True)], 3: [c("days", False, "3 of 30")],
             4: [c("look", True)]}
    step, missing, opened = ladder.climb(steps)
    assert step == 2 and [x["id"] for x in missing] == ["days"] and [x["id"] for x in opened] == ["prereg_date"]
    steps[2].append(c("leak", None))                               # open on step 2: fails closed
    step, missing, opened = ladder.climb(steps)
    assert step == 1 and [x["id"] for x in missing] == ["leak"] and [x["id"] for x in opened] == ["prereg_date"]


# ---------------------------------------------------------------- EQ1's ETF books

def eq1_book(data: Path, results: Path, book: str = "dual_mom", **kw) -> None:
    """An EQ1 paper book, its pre-registration, its study row at Trade Republic and (optionally) T1's leak record."""
    for f in ("etf_books_eq1_prereg.md", "etf_books_eq1.md"):
        (results / f).write_text("# x\n", encoding="utf-8")
    write(data, "reports/etf_books/latest.json", {"books": {f"eq1_{book}_plus50": {
        "variant": "EXPERIMENT, paper only · EQ1 ETF book · 50 EUR and 50 EUR a month · x", "started": "2026-10-29",
        "book": book, "topup": "plus50", "equity_eur": 101.0, "paid_eur": 100.0}}})
    n_all = metrics.trial_pool()["n_trials"]
    val = {"cagr": kw.get("cagr", 0.21), "max_dd": 0.18, "under_water_months": 7.0, "vs_bench_cagr": 0.02,
           "months_beat": 0.55}
    (results / "etf_books_eq1.json").write_text(json.dumps({
        "judged": "tr", "pbo": kw.get("pbo", 0.1), "pool_all": {"n_trials": kw.get("n", n_all)},
        "pool_small": {"n_trials": metrics.trial_pool("small")["n_trials"]},
        "rows": [{"book": book, "variant": "plus50", "broker": br, "dsr_all": kw.get("dsr", 0.97),
                  "dsr_small": 0.98, "val": {**val, "cagr": val["cagr"] - (br != "tr")}} for br in ("tr", "ibkr")]}))
    if kw.get("leak", True):
        write(data, "reports/leak/latest.json", {"results": [{"kind": "book", "name": f"eq1_{book}_plus50", "ok": True}]})


EQ1_COMMITS = {**COMMITS, "etf_books_eq1_prereg.md": (ts("2026-10-29"), "e1"), "etf_books_eq1.md": (ts("2026-10-29") + 60, "e2")}


def test_an_eq1_book_climbs_on_its_study_row_at_trade_republic(env):
    data, results = env
    eq1_book(data, results)
    r = run(env, EQ1_COMMITS)["book:eq1_dual_mom_plus50"]
    assert r["study"] == "EQ1" and r["step"] == 2 and set(r["missing"]) == {"days", "before"}
    assert r["benchmark"] == "a UCITS S&P 500 fund in EUR"
    st = {x["id"]: x for x in r["steps"]["2"]}
    assert "21.0 %" in st["late"]["value"] and "tr" in st["late"]["value"] and "0.10" in st["pbo"]["value"]
    assert r["eq1"]["cagr"] == 0.21 and r["eq1"]["under_water_months"] == 7.0 and r["eq1"]["equity_eur"] == 101.0


@pytest.mark.parametrize("kw, miss", [({"dsr": 0.5}, {"dsr_all"}), ({"cagr": -0.01}, {"late"}),
                                      ({"pbo": 0.3}, {"pbo"}), ({"leak": False}, {"leak"}),
                                      ({"n": 100}, {"dsr_all"})])
def test_each_eq1_condition_holds_it_at_step_1(env, kw, miss):
    data, results = env
    eq1_book(data, results, **kw)
    r = run(env, EQ1_COMMITS)["book:eq1_dual_mom_plus50"]
    assert r["step"] == 1 and set(r["missing"]) == miss
    if "n" in kw:
        assert "stale" in r["next"]


def test_the_eq1_benchmark_book_has_no_excess_and_without_its_study_nothing_passes(env):
    data, results = env
    eq1_book(data, results, book="hold_sp500")
    r = run(env, EQ1_COMMITS)["book:eq1_hold_sp500_plus50"]
    assert r["step"] == 1 and set(r["missing"]) == {"dsr_all", "dsr_family"} and "benchmark itself" in r["next"]
    md = ladder.markdown(ladder.build(data, NOW, results=results, added=added(EQ1_COMMITS)))
    assert "EQ1's ETF books" in md and "| eq1_hold_sp500_plus50 | tr | 21.0 % | 18.0 % | 7 | benchmark |" in md
    (results / "etf_books_eq1.json").unlink()
    r = run(env, EQ1_COMMITS)["book:eq1_hold_sp500_plus50"]
    assert r["step"] == 1 and set(r["missing"]) == {"late", "era", "dsr_all", "dsr_family", "pbo"}


# ---------------------------------------------------------------- the report, the briefing, Lab Live

def test_the_report_is_written_sorted_by_step(env, monkeypatch):
    data, results = env
    s1_book(data, 3)
    genome(data, 4)
    write(data, "reports/forward/latest.json", {"books": [{"kind": "book", "name": "tsmom", "since": "2026-10-06"}]})
    d = ladder.build(data, NOW, results=results, added=added())
    assert [r["step"] for r in d["rows"]] == [4, 1, 0]
    assert d["counts"]["4"] == 1 and d["title"] == "Readiness ladder" and d["items"]
    ladder.publish(d)
    out = json.loads((data / "reports" / "ladder" / "latest.json").read_text())
    md = (data / "reports" / "ladder" / "latest.md").read_text()
    assert out["rows"][0]["id"] == f"weekly:{SPEC_ID}" and "| small50_tsmom1 | book | 1 idea |" in md
    assert "higher is better" in md and "\u2014" not in md


def test_the_briefing_card_shows_the_top_5_in_german():
    rows = [{"step": k % 4, "name": f"book_{k}", "short": f"b{k}", "next": "lockbox look", "next_de":
             "R6-Lockbox-Blick gemacht"} for k in range(8)]
    lines = briefing.ladder_section({"rows": rows}, "de")
    assert len(lines) == 5 and [ln.lead for ln in lines[:2]] == ["Stufe 3 Schatten", "Stufe 3 Schatten"]
    assert lines[0].text == "b3: R6-Lockbox-Blick gemacht"
    card = notify.Card("🪜", "Stufenleiter", None, lines)
    no_english(notify.render_post([card], "telegram", 4000, "de"))
    assert briefing.ladder_section({"rows": []}, "en") == [] and briefing.ladder_section(None, "en") == []
    assert briefing.ladder_section({"rows": rows}, "en")[0].lead == "Step 3 shadow"


def test_lablive_shows_the_step_in_each_books_node(env):
    data, results = env
    write(data, "reports/forward/latest.json",
          {"generated_ms": NOW, "books": [{"kind": "book", "name": "tsmom", "since": "2026-10-06", "days": 22}]})
    lad = ladder.build(data, NOW, results=results, added=added())
    g = lablive.build(data, NOW, ladder=lad)
    n = next(x for x in g["nodes"] if x["id"] == "book:tsmom")
    nums = {x["label"]: x["value"] for x in n["numbers"]}
    assert nums["Stufe"] == "0 keine" and nums["Es fehlt"] == "vorregistriert"
    assert n["ladder"]["step"] == 0


# ---------------------------------------------------------------- today's data: nothing above step 3

def test_the_recorded_data_of_2026_10_27_has_no_candidate_above_step_3(tmp_path):
    shutil.copytree(RECORDED, tmp_path, dirs_exist_ok=True)
    d = ladder.build(tmp_path, int(datetime(2026, 10, 28, 8, tzinfo=timezone.utc).timestamp() * 1000))
    assert d["rows"] and max(r["step"] for r in d["rows"]) <= 3


@pytest.mark.skipif(not Path("/data/reports/forward/latest.json").exists(), reason="the lab's data folder is not mounted")
def test_the_labs_data_has_no_candidate_above_step_3():
    d = ladder.build(Path("/data"))
    assert d["rows"] and max(r["step"] for r in d["rows"]) <= 3


# ---------------------------------------------------------------- the pump.fun rules per trade

PF_HEAD = "rule,mint,signal_ms,land_ms,exit_signal_ms,exit_ms,exit_why,ret,hold_s,stake_sol"
PF_COMMITS = {**COMMITS, "pumpfun_exits_y8_prereg.md": (ts("2026-10-23"), "y1"),
              "pumpfun_exits_y8.md": (ts("2026-10-23") + 600, "y2"), "pumpfun_pool0_prereg.md": (ts("2026-10-22"), "y3"),
              "pumpfun_realtime_plan.md": (ts("2026-10-20"), "x1"), "pumpfun_realtime.md": (ts("2026-10-20") + 60, "x2")}


def pf_rows(rule: str, first: str, days: int, mean: float, per_day: int = 30, seed: int = 1, sd: float = 0.3,
            tainted: float | None = None) -> list[str]:
    """per_day closed trades a day from `first` on, returns N(mean, sd); with `tainted` one more row a day with that
    return which landed before its signal (P1)."""
    rng = np.random.default_rng(seed)
    t0 = ts(first) * 1000 + 3_600_000
    out = []
    for d in range(days):
        for k in range(per_day + (tainted is not None)):
            s = t0 + d * 86_400_000 + k * 60_000
            bad = k == per_day
            land = s - 1_000 if bad else s + 5_000
            ret = tainted if bad else float(rng.normal(mean, sd))
            out.append(f"{rule},m{d}_{k},{s},{land},{land + 60_000},{land + 60_500},take,{ret},60,0.1")
    return out


def pf_data(data: Path, results: Path, rows: list[str], ten: bool = False, selection: dict | None = None,
            lat: float = 0.02) -> None:
    for f in PF_COMMITS:
        (results / f).write_text("# x\n", encoding="utf-8")
    write(data, "paper/pumpfun_rt/ledger.csv", PF_HEAD + "\n" + "".join(r + "\n" for r in rows))
    write(data, "paper/pumpfun_rt/failed.csv", "rule,mint,signal_ms,land_ms,why,pnl_sol\n"
          f"P_pool0_wait,mf,{ts('2026-10-26') * 1000},{ts('2026-10-26') * 1000 + 900},not landed,-0.0002\n")
    rng = np.random.default_rng(7)                            # F3's trials: per-entry Sharpes of no skill
    jsonl(data, "pumpfun_rt/factory/ledger.jsonl", [{"kind": "trial", "id": f"F3_{i:05d}", "entries": 200,
                                                     "sharpe": float(rng.normal(0, 0.05))} for i in range(60)])
    write(data, "reports/pumpfun_rt/latest.json", {"results": [
        {"rule": r, "stress": {"lat2x": {"mean": lat}}} for r in ladder.PF_RULES]})
    rj = {"selection": selection} if selection is not None else {}
    if ten:
        rj["ten"] = [{"book": "P_pool0_wait_10eur", "strategy": "P_pool0_wait", "days": 31.0, "trades": 40,
                      "mean": 0.05, "band": [0.01, 0.09], "tainted": 0, "gap_pts": 1.0, "pass": True,
                      "gate": {"days": True, "mean": True, "band": True, "gap": True, "taint": True}}]
    write(data, "reports/pumpfun_rt/realistic.json", rj)


def pf_run(env) -> dict:
    return run(env, PF_COMMITS)


def test_a_planted_edge_per_trade_reaches_step_2_and_noise_does_not(env):
    data, results = env
    pf_data(data, results, pf_rows("P_pool0_wait", "2026-10-25", 10, 0.25)
            + pf_rows("P_pool0", "2026-10-25", 10, 0.0, seed=2) + pf_rows("E_d0_x1", "2026-10-25", 10, 0.25, seed=3))
    rows = pf_run(env)
    edge, noise, old = rows["pumpfun:P_pool0_wait"], rows["pumpfun:P_pool0"], rows["pumpfun:E_d0_x1"]
    assert edge["step"] == 2 and edge["missing"] == ["pf_edge"] and "11 days" in edge["next"], edge["next"]
    st = {x["id"]: x for x in edge["steps"]["2"]}
    assert all(x["ok"] for x in st.values()) and "pumpfun trials" in st["dsr_family"]["value"]
    x = edge["pumpfun"]
    assert x["entries"] == 301 and x["days_traded"] == 10 and x["dsr_all"] > 0.99 and x["to_bar"] == 0
    assert x["to_power"] >= 1 and x["mean"] > 0.2 and edge["benchmark"] == "0"
    assert noise["step"] == 1 and {"dsr_all", "dsr_family"} <= set(noise["missing"])
    assert noise["pumpfun"]["dsr_all"] < 0.95
    assert old["step"] == 1 and "pf_era" in old["missing"] and "old paper model" in old["next"]
    for r in ("P_cmig_model", "P_pool0_wait_norug_half"):          # listed, with no record
        assert rows[f"pumpfun:{r}"]["step"] <= 1 and rows[f"pumpfun:{r}"]["pumpfun"]["entries"] == 0
    md = ladder.markdown(ladder.build(data, NOW, results=results, added=added(PF_COMMITS)))
    assert "pump.fun rules per trade" in md and "| P_pool0_wait | 2 tested |" in md and "\u2014" not in md


def test_too_few_days_or_a_late_loss_hold_a_planted_edge_at_step_1(env):
    data, results = env
    pf_data(data, results, pf_rows("P_pool0_wait", "2026-10-25", 6, 0.25), lat=-0.01)
    r = pf_run(env)["pumpfun:P_pool0_wait"]
    assert r["step"] == 1 and set(r["missing"]) == {"pf_scored", "pf_late"} and "6 of 10 days" in r["next"]
    assert r["pumpfun"]["to_bar"] == 4


def test_tainted_rows_are_ignored(env):
    data, results = env
    pf_data(data, results, pf_rows("P_pool0", "2026-10-25", 10, 0.0, seed=2, tainted=5.0)
            + pf_rows("P_pool0_wait", "2026-10-25", 10, 0.25, tainted=-1.0))
    rows = pf_run(env)
    noise, edge = rows["pumpfun:P_pool0"], rows["pumpfun:P_pool0_wait"]
    assert noise["step"] == 1 and noise["pumpfun"]["entries"] == 300 and noise["tainted"] == 10
    assert "10 tainted rows left out" in noise["steps"]["2"][0]["value"]
    assert edge["step"] == 2 and edge["pumpfun"]["entries"] == 301 and edge["pumpfun"]["mean"] > 0.2


def test_a_missing_ten_section_stays_open_and_blocks_step_5(env):
    data, results = env
    pf_data(data, results, pf_rows("P_pool0_wait", "2026-10-25", 22, 0.25))
    r = pf_run(env)["pumpfun:P_pool0_wait"]
    assert r["step"] == 4 and r["missing"] == ["p3_gap", "p3_book"]
    assert all(x["ok"] is None for x in r["steps"]["5"]) and "open: no 10 EUR paper book" in r["next"]
    assert r["pumpfun"]["e"] >= 20 and r["pumpfun"]["e_fresh"] >= 20
    pf_data(data, results, pf_rows("P_pool0_wait", "2026-10-25", 22, 0.25), ten=True,
            selection={"pts": 18.9, "pass": False})
    r = pf_run(env)["pumpfun:P_pool0_wait"]
    assert r["step"] == 4 and r["missing"] == ["p3_gap"] and "+18.9 points" in r["next"]
    pf_data(data, results, pf_rows("P_pool0_wait", "2026-10-25", 22, 0.25), ten=True,
            selection={"pts": 1.0, "pass": True})
    assert pf_run(env)["pumpfun:P_pool0_wait"]["step"] == 5


def test_the_fresh_days_alone_judge_step_4():
    # an edge before the pre-registration, noise after it: step 3's e-process crosses, step 4's on the fresh days not
    rng = np.random.default_rng(3)
    t0 = ts("2026-10-08") * 1000
    es = [(t0 + d * 86_400_000 + k * 60_000, float(rng.normal(0.25 if d < 22 else 0.0, 0.3)))
          for d in range(34) for k in range(30)]
    sharpes = list(np.random.default_rng(7).normal(0, 0.05, 60))
    x = ladder.pf_record(es, NOW, 1000, 100, sharpes)
    assert x["days_traded"] == 34 and x["edge_day"] and x["edge_day"] < ladder.PF_FRESH_FROM
    assert x["e_fresh"] is not None and x["e_fresh"] < 20 and x["fresh_day"] is None
    assert ladder.pf_record([], NOW, 1000, 100, sharpes)["mean"] is None


def test_the_report_registers_the_five_trials_once(env):
    data, results = env
    pf_data(data, results, pf_rows("P_pool0_wait", "2026-10-25", 3, 0.0))
    d = ladder.build(data, NOW, results=results, added=added(PF_COMMITS))
    ladder.publish(d)
    ladder.publish(d)
    ids = [r["id"] for r in metrics.read_registry() if r["id"].startswith("pumpfun:ladder:")]
    assert sorted(ids) == sorted(f"pumpfun:ladder:{r}" for r in ladder.PF_RULES)
    assert metrics.trial_pool("pumpfun")["n_trials"] == 5


def test_without_pumpfun_data_no_rule_is_listed(env):
    s1_book(env[0], 1)
    assert not [r for r in run(env).values() if r["kind"] == "rule"]
