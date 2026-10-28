"""U1: the progress page's data on a fixture data folder: the ladder sorted by step with what is missing next, P3
"not started" until a book has a wallet, the calibration line and P2's gap, the tsmom books' gate 7, the weekly
page's first lines, the time and staleness of every section, a missing report as found false, the job in the table.

Run from research/lab:  python -m pytest tests/test_progress.py
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from lab.ops import jobs, progress

NOW = int(datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc).timestamp() * 1000)
HOUR = 3_600_000
REPO_TABLE = Path(__file__).resolve().parents[2] / "ops" / "jobs.yaml"


def write(root: Path, rel: str, d) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(d if isinstance(d, str) else json.dumps(d), encoding="utf-8")
    return p


@pytest.fixture()
def root(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHIA_DATA", str(tmp_path))
    monkeypatch.delenv("PYTHIA_REPORTS", raising=False)
    write(tmp_path, progress.LADDER, {
        "updated_ms": NOW - 600_000, "counts": {"0": 1, "1": 1, "2": 1},
        "registry": {"n_trials": 2690, "sr0_annual": 2.7624},
        "rows": [{"id": "book:tsmom", "name": "tsmom", "kind": "book", "step": 0, "next_de": "vorregistriert"},
                 {"id": "book:small40_spy_trend", "name": "small40_spy_trend", "kind": "book", "step": 2,
                  "next_de": "30 Tage im Schatten", "next": "30 days in shadow"},
                 {"id": "book:btc_gated", "name": "btc_gated", "kind": "book", "step": 1,
                  "next": "no tested record \u2014 yet"},
                 "junk"]})
    write(tmp_path, progress.REALISTIC, {
        "updated_ms": NOW - 40 * HOUR, "sol_eur": 90.0, "ten": [],
        "calibration": {"rule": "P_pool0_wait", "n": 14, "live": 41, "paper": 524, "d_pts": -0.4856,
                        "d_pts_mean": -2.742, "from_ms": NOW - 5 * 24 * HOUR, "to_ms": NOW - 24 * HOUR,
                        "verdict": "not yet"},
        "selection": {"pts": 1.5, "gate_pts": 2.0, "pass": True}})
    p = write(tmp_path, progress.REVIEW, {"books": [
        {"book": "tsmom", "since": "2026-10-06", "days": 23, "rebalances": 18, "paper_return_pct": -6.2,
         "backtest_return_pct": -7.2, "daily_corr": 0.77, "gate7": "23/30 days, 18/30 rebalances"},
        {"book": "tsmom_regime", "since": "2026-09-20", "days": 31, "rebalances": 30}, {"no": "book"}]})
    os.utime(p, ((NOW - 8 * HOUR) / 1000, (NOW - 8 * HOUR) / 1000))
    return tmp_path


def test_ladder_by_step_with_what_is_missing(root):
    d = progress.build(root, NOW)
    lad = d["ladder"]
    assert lad["found"] and not lad["stale"] and lad["at_ms"] == NOW - 600_000 and lad["age_ms"] == 600_000
    assert [r["name"] for r in lad["rows"]] == ["small40_spy_trend", "btc_gated", "tsmom"]
    assert lad["rows"][0]["step_name"] == "getestet" and lad["rows"][0]["next"] == "30 Tage im Schatten"
    assert lad["rows"][1]["next"] == "no tested record - yet"           # the English line when there is no German
    assert lad["top_step"] == 2 and lad["top_name"] == "getestet"
    assert lad["counts"] == {"0": 1, "1": 1, "2": 1} and lad["n_trials"] == 2690


def test_p3_not_started_then_its_gate(root):
    d = progress.build(root, NOW)
    assert d["ten"]["found"] and d["ten"]["started"] is False and d["ten"]["books"] == []
    # older than 36 hours: stale, and the page must say so
    assert d["ten"]["stale"] and d["gap"]["stale"] and d["ten"]["at_ms"] == NOW - 40 * HOUR
    real = json.loads((root / progress.REALISTIC).read_text(encoding="utf-8"))
    real["updated_ms"] = NOW - HOUR
    real["ten"] = [{"book": "T10_P_pool0_wait", "strategy": "P_pool0_wait", "start_sol": 0.109, "sol": 0.112,
                    "eur": 10.08, "trades": 12, "mean": 0.02, "median": 0.01, "band": [-0.03, 0.07], "days": 4.5,
                    "can_pay": True, "pass": False, "started": True,
                    "gate": {"days": False, "mean": True, "band": False, "gap": True, "taint": True}}]
    write(root, progress.REALISTIC, real)
    d = progress.build(root, NOW)
    t = d["ten"]
    assert t["started"] and not t["stale"] and len(t["books"]) == 1
    b = t["books"][0]
    assert b["sol"] == 0.112 and b["band"] == [-0.03, 0.07] and b["need_days"] == 30 and b["pass"] is False
    assert [g["label"] for g in b["gate"] if not g["ok"]] == ["30 Tage", "Band über 0"]


def test_paper_minus_live(root):
    g = progress.build(root, NOW)["gap"]
    c = g["calibration"]
    assert c["rule"] == "P_pool0_wait" and c["pairs"] == 14 and c["live"] == 41 and c["paper"] == 524
    assert c["median_pts"] == -0.4856 and c["mean_pts"] == -2.742 and c["verdict"] == "noch nicht"
    assert c["days"] == pytest.approx(4.0)
    assert g["p2"] == {"pts": 1.5, "gate_pts": 2.0, "pass": True, "line": None}


def test_gate7_from_the_review_with_the_files_time(root):
    g = progress.build(root, NOW)["gate7"]
    assert g["found"] and g["at_ms"] == NOW - 8 * HOUR and not g["stale"]
    assert [b["book"] for b in g["books"]] == ["tsmom", "tsmom_regime"]
    assert g["books"][0]["ready"] is False and g["books"][0]["days"] == 23 and g["books"][0]["need_rebalances"] == 30
    assert g["books"][1]["ready"] is True


def test_gate7_constants_are_the_reviews():
    from lab.paper import review
    assert (progress.GATE7_DAYS, progress.GATE7_REBALANCES) == (review.MIN_DAYS, review.MIN_REBALANCES)


def test_weekly_missing_then_its_first_lines(root):
    w = progress.build(root, NOW)["weekly"]
    assert w["found"] is False and w["lines"] == [] and w["stale"] is False and w["at_ms"] is None
    p = write(root, progress.WEEKLY, "# Pythia, Woche bis 2026-11-01\n\n" + "\n".join(f"Zeile {i}" for i in range(30)))
    os.utime(p, ((NOW - 9 * 24 * HOUR) / 1000, (NOW - 9 * 24 * HOUR) / 1000))
    w = progress.build(root, NOW)["weekly"]
    assert w["found"] and w["lines"][0] == "# Pythia, Woche bis 2026-11-01" and len(w["lines"]) == progress.WEEKLY_LINES
    assert w["stale"]                                                     # nine days old, stale after eight


def test_missing_reports_are_found_false(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHIA_DATA", str(tmp_path))
    d = progress.build(tmp_path, NOW)
    for k in ("ladder", "ten", "gap", "gate7", "weekly"):
        assert d[k]["found"] is False and d[k]["stale"] is False, k
    assert d["ladder"]["rows"] == [] and d["ten"]["started"] is False and d["gap"]["calibration"] is None


def test_main_writes_the_file_and_print_writes_nothing(root, capsys):
    assert progress.main(["--print"]) == 0
    assert not (root / "reports/progress/latest.json").exists()
    assert progress.main([]) == 0
    text = (root / "reports/progress/latest.json").read_text(encoding="utf-8")
    d = json.loads(text)
    assert d["ladder"]["rows"][0]["name"] == "small40_spy_trend" and d["updated_ms"] > 0
    assert "\u2014" not in text


def test_job_in_the_table():
    j = jobs.load_table(REPO_TABLE).jobs["progress"]
    assert j["schedule"] == "*/15 * * * *" and j["command"] == "python -m lab.ops.progress" and j["enabled"]
    assert j["kind"] == "lab" and not j["env_files"] and not j.get("network")
