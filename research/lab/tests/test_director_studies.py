"""The three studies registered together on 2026-10-21 (gated_btc, genome_gates,
m4_residual) and the experimental paper book btc_gated. No network: data are synthetic.

Run from research/lab:  python -m pytest tests/test_director_studies.py
"""

from __future__ import annotations

import json

import numpy as np
import polars as pl
import pytest

from lab import metrics
from lab.experiments import director_common as dc
from lab.experiments import gated_btc as gb
from lab.experiments import genome_gates as gg
from lab.experiments import m4_residual as m4r
from lab.experiments import memecoins as w7
from lab.factory import grammar
from lab.paper import btc_gated
from lab.paper import experimental as ex

DAY_US = 86_400_000_000


# ---------------------------------------------------------------- G, the gated BTC holding

def test_gate_buys_k_holds_and_sells():
    ret = np.array([0.0, 0.10, 0.10, -0.05, 0.02, 0.0])
    on = np.array([True, True, True, False, False, False])
    g, tov = gb.sim_gate(ret, on, 0.5, band=0.25)
    assert tov[0] == pytest.approx(0.5), "bought to k at the first switch-on close"
    assert g[1] == pytest.approx(0.05) and tov[1] == 0.0, "drift inside the band is not traded"
    w2 = 0.5 * 1.1 / 1.05
    assert g[2] == pytest.approx(w2 * 0.10)
    w3 = w2 * 1.1 / (1 + w2 * 0.10)
    assert g[3] == pytest.approx(w3 * -0.05)
    w4 = w3 * 0.95 / (1 - w3 * 0.05)
    assert tov[3] == pytest.approx(w4), "everything sold at the switch-off close"
    assert g[4] == 0.0 and g[5] == 0.0, "cash after the switch-off"


def test_gate_trims_outside_the_band_and_full_weight_never_trims():
    ret = np.r_[0.0, np.full(10, 0.2)]
    on = np.ones(11, dtype=bool)
    _, tov = gb.sim_gate(ret, on, 0.5, band=0.25)
    assert (tov[1:] > 0).any(), "a drift past 25 % of k is traded back"
    _, tov1 = gb.sim_gate(ret, on, 1.0)
    assert tov1[0] == pytest.approx(1.0) and np.all(tov1[1:] == 0.0)


def test_net_charges_turnover_on_the_next_day():
    n = gb.net(np.zeros(3), np.array([1.0, 0.0, 0.0]), 0.0035)
    assert n.tolist() == pytest.approx([0.0, -0.0035, 0.0])


# ---------------------------------------------------------------- common pieces

def test_pool_is_the_trial_registry_with_the_factory_ledgers(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHIA_FACTORY_DIR", str(tmp_path / "factory"))
    monkeypatch.setenv("PYTHIA_FACTORY_SEED", str(tmp_path / "no_seed"))
    p = dc.pool([0.1, -0.2, 0.3, 0.0])
    assert p["hand_trials"] == 1377 and p["n_total"] == 1377 + 70 and p["factory_trials"] == 70   # S1, S2, L1
    led = tmp_path / "factory" / "ledger.jsonl"
    led.parent.mkdir(parents=True)
    led.write_text("".join(json.dumps({"key": f"g{i}", "is_sharpe": 0.5 * i}) + "\n" for i in range(5)))
    q = dc.pool([])
    assert q["n_total"] == p["n_total"] + 5 and q["families"]["factory"] == 5
    assert not metrics.registry_path().exists()               # read only: a hand study does not write the registry
    assert dc.TODAY_TRIALS == 9 and 1.5 < p["sr0_annual"] < 4.0


def test_bootstrap_band_is_ordered_and_reproducible():
    x = np.random.default_rng(3).normal(0.001, 0.02, 600)
    a, b = dc.boot_band(x), dc.boot_band(x)
    assert a == b and a[0] < a[1]


def test_cut_panel_keeps_days_up_to_the_cut():
    P = w7.build_panel(_frames(300))
    last = dc.day_str(P.days[200])
    C = dc.cut_panel(P, last)
    assert C.T == 201 and C.N == P.N
    assert np.array_equal(C.px, P.px[:201], equal_nan=True) and C.btc_on.shape == (201,)


def test_results_writer_keeps_the_hand_written_part(tmp_path, monkeypatch):
    monkeypatch.setattr(dc, "RESULTS", tmp_path)
    dc.write_results("x", "first")
    p = tmp_path / "x.md"
    p.write_text("# hand\n\nnotes\n\n" + p.read_text(encoding="utf-8"), encoding="utf-8")
    dc.write_results("x", "second")
    text = p.read_text(encoding="utf-8")
    assert text.startswith("# hand") and "second" in text and "first" not in text


# ---------------------------------------------------------------- genome nulls and M4 regression

def test_null_a_only_changes_the_ranking():
    g = gg.genome()
    a = gg.null_a(g)
    assert grammar.key(g) == gg.KEY and grammar.valid(a)[0]
    assert a["select"]["rank"] == "liquidity" and g["select"]["rank"] == "signal"
    assert {k: v for k, v in a.items() if k != "select"} == {k: v for k, v in g.items() if k != "select"}


def test_ols_recovers_betas():
    rng = np.random.default_rng(5)
    X = rng.normal(0, 0.02, (2000, 2))
    y = 0.0005 + 0.7 * X[:, 0] + 0.1 * X[:, 1] + rng.normal(0, 0.001, 2000)
    coef, r2 = m4r.ols(y, X)
    assert coef == pytest.approx([0.0005, 0.7, 0.1], abs=0.01) and r2 > 0.9


# ---------------------------------------------------------------- the btc_gated paper book

def _frames(T: int = 420, drift: float = 0.004) -> dict[str, pl.DataFrame]:
    rng = np.random.default_rng(1)
    day0 = 1_700_000_000_000_000 // DAY_US * DAY_US
    close = np.exp(np.cumsum(drift + 0.01 * rng.standard_normal(T)))
    return {"BTCUSDT": pl.DataFrame({"day": [day0 + i * DAY_US for i in range(T)], "open": close,
                                     "high": close * 1.01, "low": close * 0.99, "close": close,
                                     "volume": np.full(T, 1e9), "qv": np.full(T, 5e7),
                                     "n": np.full(T, 1000, dtype=np.int64), "taker_qv": np.full(T, 2e7)})}


def test_btc_gated_signal_is_experimental_and_follows_the_gate():
    P = w7.build_panel(_frames())
    W = btc_gated.targets(P)
    t = P.T - 1
    assert P.btc_on[t]
    sig = btc_gated.signal(P, W, t, 1)
    assert sig["experimental"] and sig["autopilot_only"] and sig["variant"].startswith(ex.LABEL)
    assert sig["weights"] == {"BTC": 1.0} and sig["regime_on"] is True
    assert sig["evidence"]["report"] == "gated_btc" and not sig["evidence"].get("missing")
    D = w7.build_panel(_frames(drift=-0.004))
    off = btc_gated.signal(D, btc_gated.targets(D), D.T - 1, 1)
    assert not D.btc_on[D.T - 1] and off["weights"] == {} and off["lab_exposure"] == 0.0


def test_btc_gated_targets_match_the_study_gate():
    P = w7.build_panel(_frames())
    W = btc_gated.targets(P)
    assert np.array_equal(W[:, P.btc] > 0, P.btc_on)
