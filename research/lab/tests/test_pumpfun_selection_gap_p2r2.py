"""P2R2: P2's paper minus live gap on the realistic era only (lab.pumpfun_rt.selection_p2r2). On P2's fake live and
paper folders (test_pumpfun_selection_gap_p2's world, the cut moved to its start): the sample from the cut, the stale
pool state rows left out, counted and named, R7's band by linearization (one mean's equals factory.by_day's, every
influence sums to zero, the parts add up), too few to judge, the trades still needed, the line under P2's in the
calibration report with P2's gate unchanged, and the trials registered before the first number. Nothing live is
written.

Run from research/lab:  python -m pytest tests/test_pumpfun_selection_gap_p2r2.py
"""

from __future__ import annotations

import json

import numpy as np
import pytest
from test_pumpfun_selection_gap_p2 import T0, t, world  # noqa: F401 - the fixture

from lab.pumpfun_rt import realistic as R
from lab.pumpfun_rt import selection_p2 as S
from lab.pumpfun_rt import selection_p2r2 as S2

DAY = 86_400_000


@pytest.fixture(autouse=True)
def cut(monkeypatch, tmp_path):
    monkeypatch.setattr(S2, "CUT_MS", T0)                    # the world starts at the cut
    monkeypatch.setenv("PYTHIA_TRIALS_REGISTRY", str(tmp_path / "registry.jsonl"))


def stale_on(monkeypatch, mints):
    monkeypatch.setattr(R, "stale", lambda r: r.get("mint") in mints)


def sig(i, ret, reason=S.TRADED, live_ret=None, day=0):
    return {"rule": "P_pool0", "mint": f"m{i}", "t": T0 + day * DAY + i * 1000, "ret": ret, "reason": reason,
            "live_ret": live_ret}


# ---------------------------------------------------------------- the sample

def test_only_what_came_from_the_cut_counts(world, monkeypatch):
    live, paper = world
    monkeypatch.setattr(S2, "CUT_MS", t(300))
    r = S2.compute(S.read_live(live), S.read_paper(paper))
    assert {x["mint"] for x in r["res"]["signals"]} == {"P0"} and r["n_live"] == 1
    assert list(r["live_days"].values()) == [1] and r["judged"] is False


def test_stale_rows_are_left_out_counted_and_named(world, monkeypatch):
    live, paper = world
    stale_on(monkeypatch, {"TRD2"})
    r = S2.compute(S.read_live(live), S.read_paper(paper))
    assert "TRD2" not in {x["mint"] for x in r["res"]["signals"]} and r["res"]["left_out"]["stale"] == 1
    lo = {x["mint"]: x["why"] for x in r["res"]["live_only"]}
    assert lo["TRD2"] == "paper row on a stale pool state"
    kept = S.compute(S.read_live(live), S.read_paper(paper), since=T0)   # P2 itself keeps them
    assert "TRD2" in {x["mint"] for x in kept["signals"]} and "stale" not in kept["left_out"]
    assert r["kept"]["n_paper"] == kept["gap"]["n_paper"] == r["res"]["gap"]["n_paper"] + 1


# ---------------------------------------------------------------- R7's band

def test_one_mean_has_factory_by_days_band():
    from lab.pumpfun_rt import factory as F
    rng = np.random.default_rng(1)
    s = [sig(i, float(rng.normal(0.05, 0.3)), day=i % 4) for i in range(40)]
    lv = [(T0 + (i % 4) * DAY + i, float(rng.normal(0, 0.3))) for i in range(40)]
    b = S2.r7(S2.influence(s, lv))
    p = np.array([x["ret"] for x in s])
    ref = F.by_day(p, np.array([i % 4 for i in range(40)]), 4)
    assert b["P_all"]["lo"] == pytest.approx(ref["lo"]) and b["P_all"]["hi"] == pytest.approx(ref["hi"])


def test_the_parts_add_up_and_every_influence_sums_to_zero():
    rng = np.random.default_rng(2)
    reasons = [S.TRADED, S.PAUSED, S.UNSEEN, S.OTHER]
    s = []
    for i in range(60):
        why = reasons[i % 4]
        s.append(sig(i, float(rng.normal(0.02, 0.4)), why, float(rng.normal(0, 0.3)) if why == S.TRADED else None,
                     day=i % 6))
    lv = [(T0 + (i % 5) * DAY + i, float(rng.normal(-0.03, 0.3))) for i in range(30)]
    inf = S2.influence(s, lv)
    e, by = inf["est"], inf["by_day"]
    g = S.gap(s, [r for _, r in lv], draws=10)
    for k in S2.KEYS:
        assert e[k] == pytest.approx(g[k]) and by[k].sum() == pytest.approx(0, abs=1e-12)
    assert e["gap"] == pytest.approx(e["selection"] + e["same_coins"] + e["live_own"])
    assert e["selection"] == pytest.approx(sum(e[f"term:{r}"] for r in reasons[1:]))
    assert np.allclose(by["gap"], by["selection"] + by["same_coins"] + by["live_own"])
    assert np.allclose(by["selection"], sum(by[f"term:{r}"] for r in reasons[1:]))


def test_the_linearized_term_matches_a_numerical_derivative():
    # weight one day's records by 1 + h: the term moves by h times that day's influence sum
    rng = np.random.default_rng(3)
    s = [sig(i, float(rng.normal(0.02, 0.4)), S.TRADED if i % 3 == 0 else S.PAUSED,
             float(rng.normal(0, 0.3)) if i % 3 == 0 else None, day=i % 3) for i in range(30)]
    inf = S2.influence(s, [(T0, 0.0)])
    p = np.array([x["ret"] for x in s])
    pair = np.array([x["reason"] == S.TRADED for x in s])

    def term(ws):
        pm = np.average(p[pair], weights=ws[pair])
        return float(np.sum(ws * np.where(~pair, p - pm, 0.0)) / ws.sum())
    h = 1e-7
    for day in (0, 1):
        ws = np.array([1 + h if i % 3 == day else 1.0 for i in range(30)])
        d = (term(ws) - term(np.ones(30))) / h
        assert d == pytest.approx(inf["by_day"][f"term:{S.PAUSED}"][day], rel=1e-4, abs=1e-6)


def test_under_two_days_there_is_no_band():
    s = [sig(i, 0.1 * i, S.TRADED, 0.05) for i in range(5)]
    b = S2.r7(S2.influence(s, [(T0, 0.0), (T0 + 1, 0.1)]))
    assert b["gap"]["lo"] is None and b["gap"]["est"] == pytest.approx(0.2 - 0.05)


# ---------------------------------------------------------------- too few, the trades still needed

def test_the_trades_still_needed_bring_the_width_under_2_points():
    se, n, g = 0.036, 37, 5
    x = S2.needed(se, n, g)
    assert S2.width(se, n, g, x["trades"]) < 0.02 <= S2.width(se, n, g, x["trades"] - 1)
    assert x["more"] == x["trades"] - n and x["days"] == pytest.approx(x["more"] / (n / g))
    assert S2.needed(None, n, g) is None and S2.needed(se, n, 1) is None
    assert S2.needed(0.001, 100, 20)["more"] == 0


def test_too_few_to_judge_and_the_verdict():
    g = {"gap": 0.01, "n_paper": 50, "n_pairs": 5, "selection": 0.0, "same_coins": 0.0, "live_own": 0.01}
    r = {"res": {"gap": g}, "band": {}, "n_live": 29, "live_days": {f"d{i}": 1 for i in range(9)}, "judged": False,
         "needed": None}
    assert "too few to judge" in S2.line(r) and "P3's gate reads P2's line" in S2.line(r)
    assert S2.verdict({**r, "judged": True}) == "under 2 points"
    assert S2.verdict({**r, "judged": True, "res": {"gap": {**g, "gap": 0.02}}}) == "not under 2 points"
    assert "not measured" in S2.line({**r, "res": {"gap": {"gap": None}}})


# ---------------------------------------------------------------- the report, the calibration line, the trials

def test_the_study_registers_its_trials_first_and_writes_the_report(world, tmp_path):
    live, paper = world
    out = tmp_path / "p2r2.md"
    S2.run(live, paper, out, log=lambda *a: None)
    ids = [json.loads(x)["id"] for x in (tmp_path / "registry.jsonl").read_text(encoding="utf-8").splitlines()]
    assert {f"hand:p2r2:{k}" for k in ("paper_minus_live", "selection", "same_coins", "reasons",
                                       "stale_kept")} <= set(ids)
    md = out.read_text(encoding="utf-8")
    assert "paper minus live on the realistic era only (P2R2" in md and "P2's line as `realistic.md`" in md
    assert "| UTC day | live trades |" in md and "R7 band (by day)" in md and chr(0x2014) not in md


def test_nothing_live_is_written(world):
    live, paper = world
    before = {p.name: p.read_bytes() for p in list(live.iterdir()) + list(paper.iterdir())}
    S2.gate(live, paper)
    assert {p.name: p.read_bytes() for p in list(live.iterdir()) + list(paper.iterdir())} == before


def test_the_daily_job_writes_both_lines_and_p2_stays_the_gate(world, tmp_path, monkeypatch):
    from lab import report as rep
    from lab.pumpfun_rt import live as L
    from lab.pumpfun_rt import live_exec as LX
    live, paper = world
    monkeypatch.setattr(rep, "REPORTS", tmp_path / "reports")
    monkeypatch.setattr(LX, "data_dir", lambda: live)
    monkeypatch.setattr(L, "paper_dir", lambda: paper)
    (tmp_path / "reports" / "pumpfun_rt").mkdir(parents=True)
    R.daily(t(400))
    d = json.loads((tmp_path / "reports" / "pumpfun_rt" / "realistic.json").read_text(encoding="utf-8"))
    assert d["selection"] == S.gate(live, paper)                # P3's gate reads P2's, as before
    assert d["selection_r2"]["pts"] == pytest.approx(S2.gate(live, paper)["pts"])
    assert d["selection_r2"]["n_live"] == 7 and d["selection_r2"]["judged"] is False
    md = (tmp_path / "reports" / "pumpfun_rt" / "realistic.md").read_text(encoding="utf-8")
    assert md.index("paper minus live on all live signals") < md.index("paper minus live on the realistic era only")
    assert chr(0x2014) not in md
