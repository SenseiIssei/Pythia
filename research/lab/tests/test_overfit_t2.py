"""T2: the overfitting yardsticks (results/overfit_yardsticks_prereg.md). The purge and CPCV (lab.cv), CSCV, the
stationary bootstrap, SPA and MCS (lab.metrics), the factories' family PBO, CPCV and candidate lines, G2's PBO and
CPCV, the zoo's SPA promotion and gate hold, the replay, M4's SPA. Synthetic data only, no network.

Run from research/lab:  python -m pytest tests/test_overfit_t2.py
"""

from __future__ import annotations

import json
import math
import random

import numpy as np
import polars as pl
import pytest

from lab import cv, history, labels, metrics, report
from lab.experiments import xs_daily
from lab.factory import evaluate, ledger, run, small
from lab.models import factory as F
from lab.models import train
from lab.ops import registry

from test_factory import synthetic_panel
from test_factory_lockbox import home  # noqa: F401 (fixture)
from test_factory_small import EURUSD, make_venue
from test_factory_small import synthetic as small_synthetic
from test_model_factory_g2 import dirs, planted, raw, spec  # noqa: F401 (fixtures)
from test_model_zoo import NOW, coins, loaders, root  # noqa: F401 (fixtures)

DAY_US = 86_400_000_000


def _sr(annual: float) -> float:
    return annual / math.sqrt(365)


# ---------------------------------------------------------------- the purge (cv.walk_forward)

def test_walk_forward_purges_labels_that_reach_into_the_test_quarter():
    start = 1_672_531_200_000_000                      # 2023-01-01
    ts = start + np.arange(400) * DAY_US
    folds = cv.walk_forward(ts, start + 100 * DAY_US, embargo_h=0, horizon_h=24 * 7)
    for f in folds:
        s = ts[f.test].min()
        assert np.all(ts[f.train] + 7 * DAY_US < s)                   # no training label overlaps the test
        assert ts[f.train].max() + 8 * DAY_US >= s                    # and nothing more is dropped
    end = ts + np.where(np.arange(400) % 2, 30, 0) * DAY_US           # every other label runs 30 days
    f = cv.walk_forward(ts, start + 100 * DAY_US, embargo_h=0, label_end_us=end)[0]
    s = ts[f.test].min()
    assert np.all(end[f.train] < s) and (f.train & (end >= s)).sum() == 0
    assert f.train[(ts < s) & (end < s)].all()
    old = cv.walk_forward(ts, start + 100 * DAY_US, embargo_h=48)     # no horizon: the embargo alone, as before
    assert all(ts[o.train].max() == ts[o.test].min() - 3 * DAY_US for o in old)


# ---------------------------------------------------------------- CPCV (cv.cpcv)

@pytest.mark.parametrize("n,k", [(6, 2), (10, 2), (12, 3)])
def test_cpcv_splits_and_paths_cover_every_row_once(n, k):
    t = np.arange(600)
    sp = cv.cpcv(t, n, k, purge=3, embargo=5)
    assert len(sp) == math.comb(n, k)
    P = cv.cpcv_paths(n, k)
    assert P.max() + 1 == math.comb(n - 1, k - 1) and ((P >= 0).sum(1) == k).all()
    g = cv.groups_of(t, n)
    for s in sp:
        assert set(np.unique(g[s.test])) == set(s.groups) and not (s.train & s.test).any()
        for i in s.groups:
            lo, hi = t[g == i].min(), t[g == i].max()
            tr = t[s.train]
            assert not np.any((tr < lo) & (tr + 3 >= lo))             # purged: no label reaches into the group
            assert not np.any((tr > hi) & (tr <= hi + 5))             # embargoed after it
    vals = [np.where(s.test, t * 1.0 + 1000 * j, np.nan) for j, s in enumerate(sp)]
    paths = cv.assemble(sp, vals, n, k, t)
    assert paths.shape == (math.comb(n - 1, k - 1), 600) and np.isfinite(paths).all()
    assert np.allclose(paths % 1000, t)                                # every row once per path, its own value


def test_cpcv_on_a_panel_keeps_a_time_in_one_group():
    ts = np.repeat(np.arange(100), 3)
    for s in cv.cpcv(ts, 5, 2, purge=1):
        for t0 in np.unique(ts):
            m = ts == t0
            assert s.test[m].all() or not s.test[m].any()


# ---------------------------------------------------------------- labels and the DSR

def test_non_overlapping_skips_signals_while_a_position_is_open():
    sig = np.zeros(20, dtype=bool)
    sig[[1, 2, 5, 6, 9, 15]] = True
    assert labels.non_overlapping(sig, lambda i: i + 4) == [1, 6, 15]
    assert labels.non_overlapping(sig, lambda i: i) == [1, 2, 5, 6, 9, 15]


def test_barriers_scale_with_sigma_and_cost_is_charged_once():
    c = np.full(8, 100.0)
    h = c.copy()
    h[3] = 100 * math.exp(0.02 * 2) + 1e-9                     # sigma 0.02, horizon 4: barrier at 2 sigma
    i, r, hit = labels.triple_barrier(c, h, c, np.array([0]), np.full(8, 0.02), 1.0, 1.0, 4, 0.003)
    assert (i[0], hit[0]) == (3, 1) and r[0] == pytest.approx(0.04 - 0.003)
    i, r, hit = labels.triple_barrier(c, h, c, np.array([0]), np.full(8, 0.05), 1.0, 1.0, 4, 0.003)
    assert hit[0] == 0 and r[0] == pytest.approx(-0.003)        # a wider sigma: the time limit, flat less the cost


def test_dsr_of_the_best_noise_trial_passes_about_5_percent():
    rng = np.random.default_rng(11)
    passed = 0
    for _ in range(200):
        x = rng.normal(0, 0.01, (400, 30))
        sr = x.mean(0) / x.std(0)
        passed += metrics.deflated_sharpe(float(sr.max()), 400, 30, float(np.var(sr))) > 0.95
    assert passed <= 20
    edge = metrics.deflated_sharpe(_sr(4.0), 1000, 30, float(np.var(rng.normal(0, 0.03, 30))))
    assert edge > 0.95


# ---------------------------------------------------------------- CSCV (metrics.cscv)

def test_cscv_noise_families_are_near_one_half_and_a_planted_edge_near_zero():
    rng = np.random.default_rng(4)
    ps = [metrics.cscv(rng.normal(0, 0.02, (1600, 30)))["pbo"] for _ in range(10)]
    assert 0.35 < np.mean(ps) < 0.65
    M = rng.normal(0, 0.02, (1600, 30))
    M[:, 0] += _sr(3.5) * 0.02
    p = metrics.cscv(M)
    assert p["pbo"] < 0.1 and p["median_logit"] > 1
    assert sum(p["logit_hist"]["counts"]) == p["combos"] == math.comb(16, 8)
    assert p["logit_q"]["5"] <= p["logit_q"]["50"] <= p["logit_q"]["95"]
    assert "rank logits" in metrics.logit_text(p) and "\u2014" not in metrics.logit_text(p)
    L = rng.normal(0, 1, (800, 10))
    L[:, 3] -= 0.3                                      # one model with a truly lower loss, by mean
    assert metrics.cscv(-L, stat="mean")["pbo"] < 0.1
    assert metrics.cscv(np.zeros((50, 3))) is None


# ---------------------------------------------------------------- SPA and MCS

def test_stationary_bootstrap_blocks_have_the_mean_length():
    idx = metrics.stationary_bootstrap(2000, draws=20, block=10, seed=1)
    assert idx.shape == (20, 2000) and idx.min() >= 0 and idx.max() < 2000
    runs = (np.diff(idx, axis=1) % 2000 != 1).sum() / idx.size
    assert 0.07 < runs < 0.13                              # a new block about every 10th step


def test_spa_rejects_at_most_10_percent_of_noise_and_finds_a_planted_edge():
    rng = np.random.default_rng(6)
    rej = 0
    for s in range(200):
        rej += metrics.spa(rng.normal(0, 1, 300), rng.normal(0, 1, (300, 5)), draws=300, seed=s)["p"] < 0.05
    assert rej <= 20
    X = rng.normal(0, 1, (300, 5))
    X[:, 2] -= 0.4
    t = metrics.spa(rng.normal(0, 1, 300), X)
    assert t["p"] < 0.05 and t["best"] == 2 and t["p_lower"] <= t["p"] <= t["p_upper"]
    worse = metrics.spa(rng.normal(0, 1, 300), rng.normal(0.5, 1, (300, 3)))
    assert worse["p"] > 0.5                                  # all worse than the benchmark
    assert metrics.spa(np.zeros(5), np.zeros(5))["p"] == 1.0  # too few periods


def test_mcs_keeps_the_best_and_drops_the_clearly_worse():
    rng = np.random.default_rng(8)
    L = np.column_stack([rng.normal(0, 1, 500) + c for c in (0.0, 0.02, 0.6, 1.0)])
    m = metrics.mcs(L, ["a", "b", "c", "d"])
    assert "a" in m["included"] and "c" not in m["included"] and "d" not in m["included"]
    assert max(m["pvalues"].values()) == 1.0 and m["pvalues"]["d"] <= m["pvalues"]["c"]
    same = metrics.mcs(rng.normal(0, 1, (500, 4)))
    assert len(same["included"]) >= 3


# ---------------------------------------------------------------- the factories: CPCV, family PBO, the lines

def test_cpcv_of_a_noise_candidate_is_near_zero_and_a_planted_edge_above():
    rng = np.random.default_rng(9)
    base = rng.normal(0, 0.02, 2190)
    fam = {f"n{i}": base + rng.normal(0, 0.005, 2190) for i in range(12)}      # near variants of a noise rule
    c = evaluate.cpcv(fam["n0"], fam, "n0")
    assert c["paths"] == math.comb(11, 2) and c["splits"] == math.comb(12, 3) and c["variants"] == 11
    assert abs(c["median"]) < 1.0
    edge = base + _sr(3.0) * 0.02
    fam_e = {f"e{i}": edge + rng.normal(0, 0.005, 2190) for i in range(6)}
    e = evaluate.cpcv(fam_e["e0"], fam_e, "e0")
    assert e["p10"] > 0 and e["median"] > 1.5
    far = {"x": base + rng.normal(0, 0.02, 2190)}                                 # correlates about 0.7: not near
    alone = evaluate.cpcv(edge, far)
    assert alone["variants"] == 0 and alone["median"] == pytest.approx(evaluate.sharpe(edge))
    assert evaluate.cpcv(np.zeros(50)) is None
    line = evaluate.candidate_line({"key": "k1", "name": "rule", "deflated_p": 0.42, "cpcv": c},
                                   metrics.cscv(np.column_stack(list(fam.values()))))
    assert "DSR of the excess over BTC 0.42 (higher is better, pass at 0.95)" in line
    assert "PBO of the family" in line and "10th percentile" in line and "\u2014" not in line


def test_the_weekly_run_has_the_family_pbo_and_a_line_per_candidate(home, monkeypatch):  # noqa: F811
    P = synthetic_panel()
    monkeypatch.setattr(history, "load_long_panel", lambda fetch=False, fresh=False: P)
    d = run.weekly(30, False, "2026-10-31", log=lambda *_: None)
    run.publish(d)
    fam = d["night"]["family"]
    cur = [r for r in evaluate.current(ledger.Ledger().rows) if not r.get("same_as")]
    assert fam is None or fam["family_genomes"] == len(cur)
    md = (report.REPORTS / "factory" / "latest.md").read_text(encoding="utf-8")
    assert "PBO of the family" in md and "\u2014" not in md
    if d["holdout"]:
        assert "## Each candidate held back (T2)" in md and all(h["cpcv"] for h in d["holdout"])
        assert md.count("(higher is better, pass at 0.95)") >= len([h for h in d["holdout"]])


def test_f2_reports_the_family_pbo_and_its_candidates(home):  # noqa: F811
    days, crypto, etf = small_synthetic()
    c = small.make_ctx(days, crypto, etf, EURUSD, {"SPY": 0.003, "QQQ": 0.0, "GOLD": 0.01},
                       {a: np.array([-20.0, -5.0, 0.0, 5.0, 20.0]) for a in small.UNDERLYING})
    d = small.run(c, make_venue(), 8, "2026-12-20", log=lambda *_: None)
    md = small.markdown(d)
    assert "PBO of the family" in md and "\u2014" not in md
    for h in d["holdout"]:
        assert "cpcv" in h
    if d["holdout"]:
        assert "the excess over SPYx (40 EUR)" in md


# ---------------------------------------------------------------- G2

def test_g2_cpcv_finds_a_planted_edge_and_not_noise(raw):  # noqa: F811
    e = F.cpcv_spec(F.Panels({"fwd7": lambda: planted(raw)}), "fwd7", spec())
    assert e["paths"] == 5 and e["splits"] == 15 and e["p10"] > 0
    p = F.fwd_panel(raw)
    n = F.cpcv_spec(F.Panels({"fwd7": lambda: p}), "fwd7", spec())
    assert abs(n["median"]) < 2.0 and n["median"] < e["p10"]


def test_g2_run_reports_pbo_per_target_and_a_line_per_look(raw, dirs, monkeypatch):  # noqa: F811
    L = {"fwd7": lambda: planted(raw)}
    monkeypatch.setattr(F, "leak_reason", lambda P, r, bad=None: None)
    d = F.run(1_793_059_200_000, budget_s=10 ** 6, loaders=L, targets=["fwd7"], max_trials=4, log=lambda *_: None)
    p = d["pbo"]["fwd7"]
    assert p is None or (0 <= p["pbo"] <= 1 and p["genomes"] >= 2)
    for h in d["looks_today"]:
        assert "DM p against the baseline" in h["line"] and "(lower is better" in h["line"]
    md = (dirs / "reports" / "models" / "factory.md").read_text(encoding="utf-8")
    if d["looks_today"] or p:
        assert "Overfitting (T2)" in md and "\u2014" not in md
    keep = {}
    P = F.Panels({"fwd7": lambda: F.fwd_panel(raw)})
    rng = random.Random(5)
    for _ in range(3):
        F.trial(P, F.random_spec(rng, "fwd7", F.feature_pool("fwd7", P.get("fwd7")), False), "r", keep)
    assert len(keep) == 3 and all(len(v[0]) == len(v[1]) > 100 for v in keep.values())


# ---------------------------------------------------------------- the zoo: SPA promotion, gate hold, replay

def _zoo_fake(root, name, champ_loss_shift, n_days=60, seed=0):  # noqa: F811
    """A registered zoo name with a champion and a gate-passing challenger, its error variance 1 - shift of the
    champion's (0: the same model with fresh noise). Returns (candidate folder, champion predictor)."""
    import shutil
    rng = np.random.default_rng(seed)
    for d in (registry.published_dir(name), registry.registry_dir(name)):
        shutil.rmtree(d, ignore_errors=True)
    registry.register(name, {"metric": "mse", "higher_better": False, "margin": 0.0, "relative": False,
                             "embargo_us": DAY_US, "min_rows": 30, "min_days": 21},
                      lambda folder, card: (True, "passes"),
                      lambda frame, pred: float(np.mean((frame["target"].to_numpy() - pred) ** 2)),
                      lambda folder: (lambda frame: frame["champ"].to_numpy()),
                      lambda frame, pred: (frame["target"].to_numpy() - np.asarray(pred, float)) ** 2)
    v = registry.published_dir(name) / "20260901T0000"
    v.mkdir(parents=True)
    (v / "card.json").write_text(json.dumps({"train_to_us": 0}))
    (v / "model.json").write_text("{}")
    ts = np.repeat(1_790_000_000_000_000 + np.arange(n_days) * DAY_US, 5)
    y = rng.normal(0, 1, len(ts))
    champ = y + rng.normal(0, 1, len(ts))
    ch = y + rng.normal(0, 1, len(ts)) * math.sqrt(max(1 - champ_loss_shift, 0.01))
    cand = registry.candidates_dir(name) / "20261020T0000"
    cand.mkdir(parents=True)
    (cand / "card.json").write_text(json.dumps({"gate": {"passed": True}}))
    pl.DataFrame({"ts_us": ts, "symbol": ["s"] * len(ts), "target": y, "challenger": ch, "champ": champ,
                  "baseline_pred": np.zeros(len(ts))}).write_parquet(cand / "holdout.parquet")
    return cand, lambda frame: frame["champ"].to_numpy()


def test_zoo_promotes_only_when_spa_rejects(root):  # noqa: F811
    swaps_margin = swaps_spa = 0
    for s in range(40):                                  # the challenger is the champion again, with fresh noise
        name = "m8_direction"
        cand, fn = _zoo_fake(root, name, 0.0, n_days=120, seed=s)
        rec = registry.decide(name, cand, 1_793_000_000_000, champion_predict=fn)
        swaps_margin += registry.better(name, rec["challenger_score"], rec["champion_score"])
        swaps_spa += rec["decision"] == "promoted"
        assert "spa" in rec and "mcs" in rec["spa"] and "Hansen's SPA p" in rec["why"]
    assert swaps_margin >= 10 and swaps_spa <= 4
    cand, fn = _zoo_fake(root, "m8_direction", 0.6, seed=99)       # a truly lower loss
    rec = registry.decide("m8_direction", cand, 1_793_000_000_000, champion_predict=fn)
    assert rec["decision"] == "promoted" and rec["spa"]["p"] < 0.05 and "challenger" in rec["spa"]["mcs"]["included"]
    assert "champion" not in rec["spa"]["mcs"]["included"]


def test_models_that_failed_their_gate_are_not_retrained_until_a_book_reads_them(root, coins):  # noqa: F811
    train.run(now_ms=NOW, loaders=loaders(coins), send=False)
    d = train.run(now_ms=NOW + 7 * 86_400_000, loaders=loaders(coins), send=False)
    st = {x["model"]: x for x in d["steps"]}
    assert st["M8"]["status"] == "skipped" and "no book reads it" in st["M8"]["detail"]
    assert st["M8u"]["status"] != "skipped" or "no book reads it" not in st["M8u"]["detail"]
    d = train.run(now_ms=NOW + 8 * 86_400_000, loaders=loaders(coins), send=False, force={"m8"})
    assert next(x for x in d["steps"] if x["model"] == "M8")["status"] == "rejected"     # --force still retrains
    m8 = train.zoo.by_key("m8").SPEC
    m8.used_by.append("a paper book")
    try:
        assert train.gate_hold(m8) is None
    finally:
        m8.used_by.remove("a paper book")
    e = next(e for e in d["models"] if e["code"] == "M8")
    assert "spa_p" in e and "SPA p" in (report.REPORTS / "models" / "latest.md").read_text(encoding="utf-8")


def test_the_replay_counts_swaps_by_both_rules_and_the_skipped_retrains(root, coins):  # noqa: F811
    train.run(now_ms=NOW, loaders=loaders(coins), send=False)
    train.run(now_ms=NOW + 7 * 86_400_000, loaders=loaders(coins), send=False, force={"m8", "m8u", "m10"})
    d = train.replay(30, now_ms=NOW + 8 * 86_400_000)
    by = {p["model"]: p for p in d["pairs"]}
    assert {"M8", "M8u", "M10"} <= set(by) and all(p["rows"] > 0 for p in d["pairs"])
    assert all(isinstance(p["margin_swap"], bool) and 0 <= p["spa_p"] <= 1 for p in d["pairs"])
    assert d["spa_swaps"] <= d["margin_swaps"] + sum(1 for p in d["pairs"] if p["spa_swap"] and not p["margin_swap"])
    assert {x["model"] for x in d["skipped_retrains"]} >= {"M8"}         # M8 failed on day one, retrained by force
    md = train.replay_markdown(d)
    assert "Zoo replay" in md and "\u2014" not in md


# ---------------------------------------------------------------- M4

def test_m4_spa_on_synthetic_books():
    rng = np.random.default_rng(12)
    T = 900
    nets = {f"m{i}": rng.normal(0, 0.01, T) for i in range(8)}
    nets["b"] = rng.normal(0, 0.01, T)
    fams = {**{f"m{i}": "long/short" for i in range(8)}, "b": "baseline"}
    t = xs_daily.spa_tests(nets, fams, {"the low-vol book": ("long/short", nets["b"])})
    assert t["spa"][0]["books"] == 8 and not t["spa"][0]["rejects"]
    nets["m3"] = nets["m3"] + _sr(4.0) * 0.01
    t = xs_daily.spa_tests(nets, fams, {"the low-vol book": ("long/short", nets["b"])})
    assert t["spa"][0]["rejects"] and t["spa"][0]["best"] == "m3" and "m3" in t["mcs"]["included"]
    md = xs_daily.spa_markdown(t)
    assert "SPA p" in md and "model confidence set" in md and "\u2014" not in md
    assert xs_daily.SPA_TRIAL["id"] == "hand:t2_m4_spa" and xs_daily.LOCKBOX > xs_daily.HOLDOUT
