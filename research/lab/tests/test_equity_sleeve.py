"""The Crypto + SPY forward test's judgement (lab.paper.equity_sleeve) on synthetic daily reports.

Run from research/lab:  python -m pytest tests/test_equity_sleeve.py
"""

from __future__ import annotations

import json

import numpy as np

from lab.paper import equity_sleeve as es

D = es.DAY_MS
T0 = 1_792_600_000_000


def reports(rt, rc, start_t=T0 - D, start_c=T0 - D, skip=(), elapsed0=1.0):
    out, et, ec = [], 10_000.0, 10_000.0
    for i in range(len(rt) + 1):
        if i:
            et *= 1 + rt[i - 1]
            ec *= 1 + rc[i - 1]
        if i in skip:
            continue
        ms = T0 + i * D
        row = lambda n, eq, s: {"name": n, "started_ms": s, "elapsed_days": elapsed0 + i, "state": "running", "equity": eq}
        out.append({"generated_ms": ms, "generated": f"day {i}",
                    "autopilots": [row(es.TREATMENT, et, start_t), row(es.CONTROL, ec, start_c), row("other", 1.0, 0)]})
    return out


def test_a_clearly_better_and_calmer_mix_passes_after_90_days():
    rng = np.random.default_rng(1)
    common = rng.normal(0, 0.02, 90)
    rc = common
    rt = 0.8 * common + 0.002          # less of the same risk, plus a steady edge
    res = es.judge(es.record(reports(rt, rc)))
    assert res["points"] == 91 and res["days"] == 90
    assert res["sharpe_treatment"] > res["sharpe_control"] and res["dd_treatment"] < res["dd_control"]
    assert res["boot_p05"] > 0 and res["verdict"] == "pass", res


def test_better_on_both_but_a_band_through_zero_is_consistent_not_shown():
    rng = np.random.default_rng(2)
    rc = rng.normal(0.0005, 0.02, 90)
    rt = 0.9 * rc + rng.normal(0.0002, 0.004, 90)
    res = es.judge(es.record(reports(rt, rc)))
    if res["rules"]["sharpe_higher"] and res["rules"]["drawdown_lower"]:
        assert res["boot_p05"] <= 0 and res["verdict"] == "consistent", res


def test_before_day_90_it_is_running_and_never_judged():
    rng = np.random.default_rng(3)
    r = rng.normal(0, 0.01, 30)
    res = es.judge(es.record(reports(r * 0.5, r)))
    assert res["verdict"] == "running" and "Not judged before day 90" in res["sentence"]
    assert es.judge(es.record([]))["verdict"] == "early"


def test_point_zero_waits_a_day_gaps_are_named_and_a_restart_starts_again():
    r = np.full(10, 0.001)
    rec = es.record(reports(r, r, elapsed0=0.5))
    assert rec["times"][0] == T0 + D, "the first report under 24 hours of running is not point 0"
    rec = es.record(reports(r, r, skip={4}))
    assert rec["gaps"] == ["day 5"] and len(rec["times"]) == 10
    reps = reports(r, r)
    for rep in reps[6:]:
        for a in rep["autopilots"]:
            if a["name"] == es.CONTROL:
                a["started_ms"] = T0 + 5 * D
    rec = es.record(reps)
    assert rec["times"][0] == T0 + 6 * D and "restart" in rec["notes"][0]
    # More than 90 days: the test ends at day 90.
    long = es.record(reports(np.full(120, 0.001), np.full(120, 0.001)))
    assert (long["times"][-1] - long["times"][0]) / D == 90


def test_it_reads_the_forward_reports_from_their_folder(tmp_path, capsysbinary):
    rng = np.random.default_rng(4)
    r = rng.normal(0, 0.01, 12)
    for rep in reports(r, r):
        day = 20 + (rep["generated_ms"] - T0) // D
        (tmp_path / f"2026-11-{day:02d}.json").write_text(json.dumps(rep), encoding="utf-8")
    (tmp_path / "latest.json").write_text("{}", encoding="utf-8")
    assert es.main(["--reports", str(tmp_path)]) == 0
    out = capsysbinary.readouterr().out.decode("utf-8")
    assert out.startswith("# Crypto + SPY forward test") and "Day 12 of 90" in out, out
    assert "—" not in out
