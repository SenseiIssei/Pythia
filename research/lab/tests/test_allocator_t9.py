"""T9: the allocator weighted by posterior, shared entries, and the replay study (results/allocator_t9_prereg.md)."""

import json
from datetime import datetime, timezone

import numpy as np
import pytest

from lab import metrics
from lab.pumpfun_rt import allocator as A
from lab.pumpfun_rt import allocator_t9 as T

DAY = 86_400_000
T0 = int(datetime(2026, 10, 20, tzinfo=timezone.utc).timestamp() * 1000)
DAYS = [f"2026-10-{d:02d}" for d in range(1, 21)]


def rewards(days, means, seed=6, sd=0.02):
    rng = np.random.default_rng(seed)
    return {a: {d: float(m + rng.normal(0, sd)) for d in days} for a, m in means.items()}


def test_identical_arms_get_the_same_weight():
    rw = rewards(DAYS, {"a": 0.02, "c": 0.0})
    rw["b"] = dict(rw["a"])                                   # b holds exactly a's entries
    res = A.decide(rw, DAYS, "2026-10-21", shares={a: {d: 0.5 for d in DAYS} for a in ("a", "b")})
    w = {a: v["weight"] for a, v in res["arms"].items()}
    assert w["a"] == pytest.approx(w["b"], abs=1e-12) and w["a"] > w["c"]
    assert sum(w.values()) == pytest.approx(1.0)
    assert res["arms"]["a"]["post"]["n"] == pytest.approx(res["arms"]["b"]["post"]["n"])


def test_shares_count_a_shared_entry_once():
    tr = {"a": [(T0 + 10, 0.1, "x"), (T0 + 20, 0.1, "y")], "b": [(T0 + 30, -0.1, "x")], "c": [(T0 + DAY, 0.0, "x")]}
    sh = A.day_shares(tr, ["2026-10-20", "2026-10-21"])
    assert sh["a"]["2026-10-20"] == pytest.approx((0.5 + 1.0) / 2) and sh["b"]["2026-10-20"] == 0.5
    assert sh["c"]["2026-10-20"] == 1.0 and sh["c"]["2026-10-21"] == 1.0        # another day is another entry
    p_full = A.posterior(np.array([0.1, 0.1]), np.array([1.0, 0.0]), 0.01)
    p_half = A.posterior(np.array([0.1, 0.1]), np.array([1.0, 0.0]), 0.01, share=np.array([0.5, 0.5]))
    assert p_half["n"] == pytest.approx(p_full["n"] / 2) and p_half["sd_mean"] > p_full["sd_mean"]
    assert A.day_rewards({"a": [(T0 + 10, 0.5, "x")]}, ["2026-10-20"])["a"]["2026-10-20"] == pytest.approx(np.log(1.05))


def test_a_clearly_better_arm_gets_more():
    rw = rewards(DAYS, {"a": 0.05, "b": 0.0, "c": -0.01})
    res = A.decide(rw, DAYS, "2026-10-21")
    w = {a: v["weight"] for a, v in res["arms"].items()}
    assert res["mode"] == "weighted" and res["choice"] == "a"
    assert w["a"] > 0.85 and w["b"] >= A.FLOOR - 1e-12 and w["c"] >= A.FLOOR - 1e-12
    assert A.decide(rw, DAYS, "2026-10-22")["arms"]["a"]["weight"] == w["a"]       # no draw: the seed does nothing


def test_exact_p_best_matches_the_draws():
    rng = np.random.default_rng(1)
    posts = [A.posterior(rng.normal(m, s, 20), np.arange(20.0)[::-1], 0.01)
             for m, s in ((0.05, 0.02), (0.0, 0.02), (0.03, 0.2))]
    exact = A.p_best(posts)
    g = np.random.default_rng(2)
    dr = np.column_stack([A.draw_means(p, g, 200_000) for p in posts])
    mc = np.bincount(dr.argmax(axis=1), minlength=3) / len(dr)
    assert exact.sum() == pytest.approx(1.0) and np.abs(exact - mc).max() < 0.01
    flat = A.posterior(np.zeros(0), np.zeros(0), 0.01)
    assert A.p_best([flat] * 3) == pytest.approx([1 / 3] * 3)


def test_drawn_mode_is_a1():
    rw = rewards(DAYS, {"a": 0.05, "b": 0.0, "c": -0.01})
    res = A.decide(rw, DAYS, "2026-10-21", mode="drawn")
    assert res["mode"] == "drawn" and res["choice"] in ("a", "b", "c")
    assert A.decide(rw, DAYS, "2026-10-21", mode="drawn")["choice"] == res["choice"]
    assert "split by weight" not in A.why(res, None) and "split by weight" in A.why(A.decide(rw, DAYS, "2026-10-21"), None)


def test_split_reward():
    rw = {"a": {"d": 0.1}, "b": {"d": -0.2}}
    res = {"arms": {"a": {"weight": 0.75}, "b": {"weight": 0.25}}}
    assert A.split_reward(res, rw, "d") == pytest.approx(np.log(0.75 * np.exp(0.1) + 0.25 * np.exp(-0.2)))
    assert A.split_reward({"arms": {"a": {"weight": 0.0}, "b": {"weight": 0.0}}}, rw, "d") == 0.0


def test_study_on_simulated_days(tmp_path, monkeypatch):
    reg = tmp_path / "registry.jsonl"
    monkeypatch.setenv("PYTHIA_TRIALS_REGISTRY", str(reg))
    days = DAYS[:12]
    rw = rewards(days, {"P_pool0_wait": 0.05, "P_pool0_wait_lock": 0.0, "P_pool5_top30t": -0.02}, sd=0.05)
    sh = {a: {d: 1.0 for d in days} for a in rw}
    res = T.study({"replay": (rw, sh, days), "paper": ({a: {} for a in rw}, sh, [])}, log=lambda *_: None)
    ids = {json.loads(x)["id"] for x in reg.read_text().splitlines()}
    assert {t["id"] for t in T.trials()} <= ids and len(T.trials()) == 4
    h = res["histories"]["replay"]
    assert len(h["per_day"]) == 12 and h["enough_days"] and isinstance(h["verdict"], bool)
    for k in T.POLICIES:
        lo, hi = h["band"][k]
        assert lo <= hi and h["total"][k] == pytest.approx(sum(x[k] for x in h["per_day"]))
    eq = h["per_day"][3]
    assert eq["equal"] == pytest.approx(np.log(np.mean([np.exp(v) for v in eq["arms"].values()])))
    assert all(0 <= r["dsr"] <= 1 and 0 <= r["dsr_all"] <= 1 for r in h["vs"].values())
    assert h["drawn_seed_band"][0] <= h["drawn_seed_band"][1]
    md = T.markdown(res, "2026-10-28")
    assert "DSR" in md and "deflated p" not in md and "No days." in md and "\u2014" not in md
    n = len(reg.read_text().splitlines())
    T.study({"replay": (rw, sh, days)}, log=lambda *_: None)
    assert len(reg.read_text().splitlines()) == n                       # the ids are fixed: a rerun adds nothing


def test_replay_history_counts_the_lock_once(monkeypatch):
    e = lambda m, t, pnl: {"mint": m, "exit_ms": t, "pnl": pnl}
    rep = {"days": ["2026-10-20", "2026-10-21"], "trained": {"2026-10-20": ["win5t"], "2026-10-21": ["win5t"]},
           "entries": {"P_pool0_wait": [e("x", T0 + 10, 0.01)], "P_pool0_wait_lock": [e("x", T0 + 20, 0.02)],
                       "P_pool5_top30t": [e("y", T0 + 30, -0.01)]}}
    rw, sh, days = T.replay_history(rep, T0 + 2 * DAY)
    assert days == ["2026-10-20", "2026-10-21"]
    assert sh["P_pool0_wait"]["2026-10-20"] == 0.5 and sh["P_pool5_top30t"]["2026-10-20"] == 1.0
    assert rw["P_pool0_wait_lock"]["2026-10-20"] == pytest.approx(np.log(1.02))
