"""Search pause (results/search_pause_prereg.md): the rule, the measures and the four flags in jobs.yaml."""

import json
from pathlib import Path

import pytest

from lab import metrics
from lab.ops import jobs
from lab.ops import search_pause as S

REPO_TABLE = Path(__file__).resolve().parents[2] / "ops" / "jobs.yaml"


def _w(p: Path, rows) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(rows, list):
        p.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    else:
        p.write_text(json.dumps(rows), encoding="utf-8")


def _rec(job, start, end, status="ok"):
    return {"job": job, "start": start, "end": end, "status": status, "duration_s": 0}


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHIA_TRIALS_REGISTRY", str(tmp_path / "trials" / "registry.jsonl"))
    _w(tmp_path / "factory" / "ledger.jsonl",
       [{"key": f"w{i}", "run": "2026-11-01"} for i in range(30)] + [{"key": "w30", "run": "2026-11-01", "same_as": "w0"}]
       + [{"key": f"o{i}", "run": "2026-10-01"} for i in range(5)])               # before the window
    _w(tmp_path / "factory" / "small" / "ledger.jsonl", [{"key": f"s{i}", "run": "2026-11-17"} for i in range(14)])
    _w(tmp_path / "pumpfun_rt" / "factory" / "ledger.jsonl",
       [{"kind": "trial", "id": f"F3_{i}", "night": "2026-11-20", "sharpe": 0.01 * (i % 5 - 2), "entries": 100}
        for i in range(20)] + [{"kind": "holdback", "id": "F3_1", "night": "2026-11-20"}])
    _w(tmp_path / "models" / "factory" / "ledger.jsonl", [{"key": f"g{i}", "run": "2026-11-10"} for i in range(70)])
    _w(tmp_path / "reports" / "ladder" / "latest.json", {"rows": [{"id": "weekly:w1", "step": 1},
                                                                  {"id": "book:tsmom", "step": 3}]})
    _w(tmp_path / "reports" / "weekly" / "2026-11-08.json", {"ladder": {"weekly:w2": 0}})
    _w(tmp_path / "_ops" / "runs" / "2026-11.jsonl", [
        _rec("pumpfun-factory", "2026-11-20T01:00:00Z", "2026-11-20T03:00:00Z"),
        _rec("factory-small", "2026-11-20T03:00:00Z", "2026-11-20T03:30:00Z"),   # waited 0 min
        _rec("factory-small", "2026-11-21T02:30:00Z", "2026-11-21T03:30:00Z"),   # waited for features to 03:00
        _rec("features", "2026-11-21T02:00:00Z", "2026-11-21T03:00:00Z"),
        _rec("model-factory", "2026-11-21T10:00:00Z", "2026-11-21T11:00:00Z", "skipped")])
    return tmp_path


def _reg():
    hand = [{"id": f"hand:{i}", "family": "hand", "n": 100, "sharpe": None, "var": metrics.prior_var()} for i in range(3)]
    fac = [{"id": f"factory:w{i}", "family": "factory", "n": 1, "sharpe": (i % 7 - 3) * 0.4, "var": None,
            "source": "factory ledger"} for i in range(30)]
    t7 = [{"id": "factory:t7", "family": "factory", "n": 1, "sharpe": 0.5, "var": None, "source": "results/t7.md"}]
    sm = [{"id": f"small:s{i}", "family": "small", "n": 1, "sharpe": (i % 5 - 2) * 0.3, "var": None,
           "source": "small ledger"} for i in range(14)]
    return hand + fac + t7 + sm


def test_the_rule_pauses_without_a_candidate_on_step_2_in_the_window(root):
    assert S.verdict({}) == "pause" and S.verdict({"weekly:a": 1, "weekly:b": 0}) == "pause"
    assert S.verdict({"weekly:a": 2}) == "keep" and S.verdict({"weekly:a": 4}) == "keep"
    assert S.ladder_steps(root, ("weekly:",)) == {"weekly:w1": 1, "weekly:w2": 0}   # not another family's book
    _w(root / "reports" / "weekly" / "2026-11-15.json", {"ladder": {"weekly:w2": 2}})
    assert S.verdict(S.ladder_steps(root, ("weekly:",))) == "keep"               # on step 2 once in the window
    _w(root / "reports" / "weekly" / "2026-11-15.json", {"ladder": {}})
    _w(root / "reports" / "weekly" / "2026-10-04.json", {"ladder": {"weekly:w2": 3}})
    assert S.verdict(S.ladder_steps(root, ("weekly:",))) == "pause"              # before the window: does not count


def test_trials_a_week_one_per_behaviour_and_by_night(root):
    led = S._jsonl(root / "factory" / "ledger.jsonl")
    days = S.trial_days("factory-weekly", led)
    assert len(days) == 35                                                       # the same_as line is no trial
    wk = S.per_week(days)
    assert list(wk) == S.weeks() and len(wk) == 6 and wk["2026-10-26"] == 30 and sum(wk.values()) == 30
    assert S.rate(wk) == 30 / 4
    f3 = S.trial_days("pumpfun-factory", S._jsonl(root / "pumpfun_rt" / "factory" / "ledger.jsonl"))
    assert len(f3) == 20                                                         # the holdback line is no trial


def test_lock_hours_leave_the_wait_out_and_a_skip_holds_nothing(root):
    recs = S._jsonl(root / "_ops" / "runs" / "2026-11.jsonl")
    heavy = {"pumpfun-factory", "factory-small", "features", "model-factory"}
    h = S.lock_hours(recs, heavy, "factory-small")
    assert h["runs"] == 2 and h["run_h"] == pytest.approx(1.5) and h["lock_h"] == pytest.approx(1.0)
    assert S.lock_hours(recs, heavy, "pumpfun-factory")["lock_h"] == pytest.approx(2.0)
    g2 = S.lock_hours(recs, heavy, "model-factory")
    assert g2["runs"] == 1 and g2["run_h"] == pytest.approx(1.0) and g2["lock_h"] == 0.0


def test_the_bar_without_a_jobs_lines_and_in_eight_weeks(root):
    reg = _reg()
    d = S.build(root, reg_rows=reg)
    by = {j["job"]: j for j in d["jobs"]}
    assert by["factory-weekly"]["r5_trials"] == 30 and by["factory-small"]["r5_trials"] == 14
    assert by["pumpfun-factory"]["r5_trials"] == 0 and by["model-factory"]["r5_trials"] == 0
    assert d["today"]["r5_trials"] == 345 and d["today"]["f3_trials"] == 20 and d["today"]["n_entry"] == 365
    w = by["factory-weekly"]
    assert w["b_day_without"] == pytest.approx(S.pool_of([r for r in reg if r.get("source") != "factory ledger"])
                                               ["sr0_annual"])
    assert w["b_day_n_only"] < w["b_day"]                                        # fewer trials, a lower bar by N
    f3 = by["pumpfun-factory"]
    assert f3["b_day_without"] == f3["b_day"] and f3["b_entry_without"] < f3["b_entry"]
    assert by["model-factory"]["b_entry_without"] == by["model-factory"]["b_entry"]
    assert by["model-factory"]["g2_bar_p"] == pytest.approx(0.05 / 70)
    assert all(j["verdict"] == "pause" for j in d["jobs"])
    assert by["factory-small"]["cpu_h"] == pytest.approx(by["factory-small"]["lock_h"] * 1)
    p = d["projection"]
    assert p["with_pause"]["r5_trials"] == d["today"]["r5_trials"] and p["with_pause"]["f3_trials"] == 20
    assert p["without_pause"]["r5_trials"] == 345 + round(8 * 30 / 4) + round(8 * 14 / 4)
    assert p["without_pause"]["f3_trials"] == 20 + round(8 * 20 / 4)
    assert p["without_pause"]["b_entry"] > p["with_pause"]["b_entry"]
    assert p["without_pause"]["b_day_n_only"] > p["with_pause"]["b_day_n_only"]
    assert p["without_pause"]["g2_bar_p"] < p["with_pause"]["g2_bar_p"]
    md = S.markdown(d)
    assert "\u2014" not in md and "pause" in md and "with the pause" in md


def test_main_registers_the_five_trials_before_the_numbers(root, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("PYTHIA_DATA", str(root))
    assert S.main(["--print"]) == 0
    assert not (tmp_path / "trials" / "registry.jsonl").exists()                # print: nothing written
    out = tmp_path / "sp.json"
    assert S.main(["--out", str(out)]) == 0
    ids = {r["id"] for r in metrics.read_registry()}
    assert {x["id"] for x in S.trials()} <= ids and len(S.trials()) == 5
    assert all(x["family"] == "hand" and x["sharpe"] is None for x in S.trials())
    assert json.loads(out.read_text())["trials"] == [x["id"] for x in S.trials()]


def test_jobs_yaml_carries_the_four_flags_at_0_and_nothing_else_changes():
    t = jobs.load_table(REPO_TABLE)
    j = t.jobs
    assert j["factory-weekly"]["command"] == "python -m lab.factory --notify --budget 0"
    assert j["factory-small"]["env"]["PYTHIA_FACTORY_SMALL_BUDGET"] == "0"
    assert j["pumpfun-factory"]["env"]["PYTHIA_PF_FACTORY_TRIALS"] == "0"
    assert j["model-factory"]["env"]["PYTHIA_MODEL_FACTORY_BUDGET"] == "0"
    for n, sched in (("factory-weekly", "30 7 * * 0"), ("factory-small", "0 3 * * *"), ("pumpfun-factory", "0 1 * * *"),
                     ("model-factory", "0 10 * * *")):
        assert j[n]["schedule"] == sched and j[n]["enabled"] and "heavy" in j[n]["locks"]
    assert j["factory-shadow"]["command"] == "python -m lab.factory shadow --notify" and j["factory-shadow"]["enabled"]
    assert set(S.JOBS) <= set(j)
