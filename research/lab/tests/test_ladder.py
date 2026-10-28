"""T3: the readiness ladder on fake reports, one candidate stopped at each step for the condition named; open
conditions that do not block; the briefing's card and Lab Live's step; the recorded data of 2026-10-27 and (when
mounted) the lab's own, where nothing stands above step 3. The moved-out-capital case of the readiness drawdown is in
tests/test_readiness.py (test_capital_moved_out_is_not_a_drawdown).

Run from research/lab:  python -m pytest tests/test_ladder.py
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest

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
    write(root, rel, head + "\n" + "".join(f"2026-10-{1 + i % 28:02d},1.0\n" for i in range(days)))


@pytest.fixture()
def env(tmp_path, monkeypatch):
    data, results = tmp_path / "data", tmp_path / "results"
    data.mkdir()
    results.mkdir()
    monkeypatch.setenv("PYTHIA_DATA", str(data))
    monkeypatch.delenv("PYTHIA_REPORTS", raising=False)
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
    assert r["step"] == 1 and set(r["missing"]) == {"late", "era", "dsr_all", "dsr_family"}
    assert r["open"] == ["leak", "pbo"]                            # no T1 report, no T2 for a book: open


@pytest.mark.parametrize("kw, miss", [({"dsr": 0.5}, "dsr_all"), ({"dsr_small": 0.94}, "dsr_family"),
                                      ({"late": -0.01}, "late"), ({"leak_ok": False}, "leak")])
def test_each_tested_condition_holds_a_book_at_step_1(env, kw, miss):
    s1_book(env[0], 3, **kw)
    r = run(env)["book:small50_tsmom1"]
    assert r["step"] == 1 and r["missing"] == [miss]


def test_a_tested_book_needs_30_days_of_shadow(env):
    s1_book(env[0], 3, days=29)
    r = run(env)["book:small50_tsmom1"]
    assert r["step"] == 2 and r["missing"] == ["days"] and "29 of 30" in r["next"]
    assert r["evidence"] == "paper/small50_tsmom1/journal.csv"


def test_a_book_never_gets_a_lockbox_look_so_it_stops_at_step_3(env):
    s1_book(env[0], 3)
    r = run(env)["book:small50_tsmom1"]
    assert r["step"] == 3 and r["missing"] == ["look"] and "before" in r["open"]


def test_r10s_results_table_when_its_report_is_missing(env):
    data, results = env
    s1_book(data, 1)
    shutil.copy(Path(__file__).parents[1] / "results" / "smallaccount_r10.md", results / "smallaccount_r10.md")
    rows = ladder.r10_rows(data, results)
    assert rows["S1 tsmom1"]["late_cagr"] == pytest.approx(14.3) and rows["S1 tsmom1"]["dsr_family"] == 0.028
    assert rows["S2 spy_trend"]["crypto"] is False and rows["F2 f2 07493e8a8adb"]["dsr_all"] == 0.0
    r = run(env)["book:small50_tsmom1"]
    assert r["step"] == 1 and set(r["missing"]) == {"dsr_all", "dsr_family"}


# ---------------------------------------------------------------- a weekly factory genome up to step 6

def holdout(**kw) -> dict:
    return {"run": "2026-11-01", "date": "2026-10-31", "key": SPEC_ID, "name": "low vol", "behaviour": "beh1",
            "decision": "shadow", "deflated_p": 0.97, "dsr_family": 0.96, "oos_late_sharpe": 0.5,
            "gates": {"stress": {"passed": True, "why": "0.6 at 70 bps"}}, **kw}


def genome(data: Path, upto: int, look: dict | None = None, record: dict | None = None, **kw) -> None:
    jsonl(data, "factory/holdout.jsonl", [holdout(**kw)])
    write(data, "factory/runs/2026-11-01.json", {"night": {"family": {"pbo": kw.pop("pbo", 0.1)}}})
    if upto >= 3:
        write(data, f"factory/shadow/{SPEC_ID}.json", {"key": SPEC_ID, "name": "low vol", "status": "active",
                                                   "entered_run": "2026-11-01", "entry_day": "2026-10-31"})
        journal(data, f"factory/shadow/{SPEC_ID}.csv", 30)
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
    assert r["kind"] == "shadow" and r["step"] == 5 and r["step_name"] == "execution"
    assert r["missing"] == ["owner"] and "only the owner" in r["next"]
    assert r["open"] == ["before"]                                 # T8 not there yet


@pytest.mark.parametrize("upto, step, miss", [(2, 2, "days"), (3, 3, "look"), (4, 4, "record")])
def test_a_genome_stops_where_its_evidence_ends(env, upto, step, miss):
    genome(env[0], upto)
    r = run(env)[f"weekly:{SPEC_ID}"]
    assert r["step"] == step and r["missing"] == [miss], r


@pytest.mark.parametrize("kw, miss", [({"deflated_p": 0.9}, "dsr_all"), ({"dsr_family": None}, "dsr_family"),
                                      ({"pbo": 0.25}, "pbo"), ({"oos_late_sharpe": -0.1}, "late"),
                                      ({"gates": {"stress": {"passed": False, "why": "-0.2 at 70 bps"}}}, "era")])
def test_each_tested_condition_holds_a_genome_at_step_1(env, kw, miss):
    genome(env[0], 5, **kw)
    r = run(env)[f"weekly:{SPEC_ID}"]
    assert r["step"] == 1 and r["missing"] == [miss], r


def test_the_leak_harness_rejects_and_a_genome_held_back_before_t1_is_open(env):
    data, _ = env
    genome(data, 5)
    jsonl(data, "factory/leaks.jsonl", [{"key": SPEC_ID, "reason": "moved at t"}])
    assert run(env)[f"weekly:{SPEC_ID}"]["missing"] == ["leak"]
    genome(data, 5, date="2026-10-20", run="2026-10-21")
    (data / "factory" / "leaks.jsonl").unlink()
    jsonl(data, "factory/runs/2026-10-21.json", [])                # an old run without T2's PBO
    r = run(env)[f"weekly:{SPEC_ID}"]
    assert r["step"] == 0 and r["missing"] == ["prereg_date"]       # R6 came after its first number
    r = run(env, {**COMMITS, "factory_lockbox_r6.md": (ts("2026-10-01"), "c3")})[f"weekly:{SPEC_ID}"]
    assert r["step"] == 5 and {"leak", "pbo"} <= set(r["open"])


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


def test_the_climb_stops_at_the_first_fail_and_open_never_blocks():
    c = ladder.cond
    steps = {1: [c("prereg", True)], 2: [c("leak", None), c("late", True)], 3: [c("days", False, "3 of 30")],
             4: [c("look", True)]}
    step, missing, opened = ladder.climb(steps)
    assert step == 2 and [x["id"] for x in missing] == ["days"] and [x["id"] for x in opened] == ["leak"]


# ---------------------------------------------------------------- the report, the briefing, Lab Live

def test_the_report_is_written_sorted_by_step(env, monkeypatch):
    data, results = env
    s1_book(data, 3)
    genome(data, 4)
    write(data, "reports/forward/latest.json", {"books": [{"kind": "book", "name": "tsmom", "since": "2026-10-06"}]})
    d = ladder.build(data, NOW, results=results, added=added())
    assert [r["step"] for r in d["rows"]] == [4, 3, 0]
    assert d["counts"]["4"] == 1 and d["title"] == "Readiness ladder" and d["items"]
    ladder.publish(d)
    out = json.loads((data / "reports" / "ladder" / "latest.json").read_text())
    md = (data / "reports" / "ladder" / "latest.md").read_text()
    assert out["rows"][0]["id"] == f"weekly:{SPEC_ID}" and "| small50_tsmom1 | book | 3 shadow |" in md
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
