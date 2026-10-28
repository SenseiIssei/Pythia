"""T6 without a data folder: xs_daily's books with a per-coin cost matrix (unchanged without one), T4's depth
replacing the tier where it exists, the cut of xs_daily's matrices, the paper record against rolling validation
returns, the journal, the Sharpe the DSR bar needs, the ladder, the lockbox line (never a look), F2's PBO read from
its newest run, and lead A end to end on synthetic books: its 6 trials registered before any validation number,
a planted edge through the gates, noise not.

Run from research/lab:  python -m pytest tests/test_two_leads_t6.py
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone

import numpy as np
import polars as pl
import pytest

from lab import metrics
from lab.experiments import director_common as dc
from lab.experiments import fam_common as fc
from lab.experiments import pit_universe_t5 as t5
from lab.experiments import two_leads_t6 as t6
from lab.experiments import xs_daily as xs

D = fc.DAY_US


def toy_m(T: int = 120, N: int = 30, seed: int = 3) -> dict:
    rng = np.random.default_rng(seed)
    d0 = dc.us("2026-05-01")
    return {"days": d0 + np.arange(T) * D, "syms": np.array([f"C{i:02d}USDT" for i in range(N)]),
            "R": rng.normal(0, 0.03, (T, N)), "fund": rng.normal(1e-4, 2e-4, (T, N)),
            "perp_adv28": 10 ** rng.uniform(5, 9.5, (T, N)), "adv28_raw": 10 ** rng.uniform(5, 9.5, (T, N)),
            "fund7_raw": rng.normal(1e-4, 5e-4, (T, N)), "score": rng.normal(0, 1, (T, N))}


# ---------------------------------------------------------------- costs

@pytest.mark.parametrize("kind", ["book", "buffer"])
def test_a_flat_cost_matrix_charges_the_flat_cost_and_no_matrix_changes_nothing(kind):
    M = toy_m()
    run = ((lambda **k: xs.book(M, M["score"], 3, 3, 20, True, **k)) if kind == "book"
           else (lambda **k: xs.book_buffer(M, M["score"], 3, 0.5, 20, **k)))
    g, tu, fu, ex = run()
    g2, cost, fu2, ex2 = run(C=np.full(M["R"].shape, 0.0007))
    assert np.allclose(g, g2) and np.allclose(fu, fu2) and np.allclose(ex, ex2)
    assert np.allclose(cost, 0.0007 * tu)
    C = t6.era_cost(M["perp_adv28"])
    _, cost3, _, _ = run(C=C)
    assert (cost3 >= t5.PERP_FEE * tu - 1e-12).all() and (cost3 <= (t5.PERP_FEE + t5.SPREAD_BELOW) * tu + 1e-12).all()


def test_t4_depth_replaces_the_tier_where_it_exists():
    days = dc.us("2024-01-01") + np.arange(5) * D
    tb = pl.DataFrame({"ts_us": [int(days[1]), int(days[3]), int(days[3]) + 3600 * 10 ** 6],
                       "asset": ["BTC", "ETH", "XRP"], "cost10k": [0.5, 2.0, 9.0]})
    dep = t6.depth_costs(days, ["BTC", "ETH"], tb)
    assert dep[1, 0] == pytest.approx(0.5e-4) and dep[3, 1] == pytest.approx(2e-4)
    assert np.isfinite(dep).sum() == 2
    vol = np.full((5, 2), 5e6)
    c = t6.era_cost(vol, dep)
    assert c[1, 0] == pytest.approx(t5.PERP_FEE + 0.5e-4)
    assert c[0, 0] == pytest.approx(t5.PERP_FEE + t5.half_spread(vol)[0, 0])
    assert t6.depth_costs(days, ["BTC"], tb.head(0)) is None and t6.depth_costs(days, ["BTC"], None) is None
    assert np.array_equal(t6.era_cost(vol, None), t5.era_cost(vol, True))


def test_the_matrices_are_cut_at_the_last_validation_day():
    M = toy_m()
    C = t6.cut_matrices(M, "2026-06-30")
    assert dc.day_str(C["days"][-1]) == "2026-06-30"
    assert C["R"].shape == (len(C["days"]), M["R"].shape[1]) and len(C["syms"]) == len(M["syms"])
    assert np.array_equal(C["R"], M["R"][:len(C["days"])])


# ---------------------------------------------------------------- the paper record

def test_rolling_compound_is_every_window():
    x = np.array([0.1, -0.1, 0.2, np.nan, 0.0])
    w = t6.rolling_compound(x, 2)
    assert np.allclose(w, [1.1 * 0.9 - 1, 0.9 * 1.2 - 1, 1.2 * 1.0 - 1])
    assert len(t6.rolling_compound(x, 9)) == 0


def test_a_paper_record_far_below_the_validated_band_fails_and_an_ordinary_one_passes():
    rng = np.random.default_rng(1)
    val = rng.normal(0.001, 0.01, 900)
    good = t6.paper_rank(np.full(6, 0.001), val)
    bad = t6.paper_rank(np.full(6, -0.03), val)
    assert good["passes"] and 0.2 < good["pct"] < 0.8
    assert not bad["passes"] and bad["pct"] < 0.01 and bad["ret"] < bad["p05"]
    assert not t6.paper_rank(np.zeros(0), val)["passes"]


def test_the_journal_is_read_from_the_first_marked_day(tmp_path):
    p = tmp_path / "journal.csv"
    p.write_text("date,equity,ret_pct,ret_M4_pct,ret_Carry_pct,ret_LowVol_pct,w_M4\n"
                 "2026-10-21,9994,0.0,0.0,0.0,0.0,0.3\n2026-10-22,10066,0.7344,1.6657,-0.7995,1.6829,0.3\n"
                 "2026-10-23,10100,0.3398,0.3186,0.0814,0.6591,0.3\n", encoding="utf-8")
    j = t6.read_journal(p)
    assert list(j["days"]) == ["2026-10-22", "2026-10-23"]
    assert np.allclose(j["book"], [0.007344, 0.003398]) and np.allclose(j["Carry"], [-0.007995, 0.000814])
    assert len(t6.read_journal(tmp_path / "none.csv")["book"]) == 0


# ---------------------------------------------------------------- the bar, the ladder, the lockbox

def test_the_needed_sharpe_gives_a_dsr_of_095():
    rng = np.random.default_rng(2)
    x = rng.normal(0.0005, 0.01, 900)
    pool = {"n_trials": 2800, "var": metrics.prior_var()}
    need = t6.needed_sharpe(x, pool)
    from scipy import stats
    sk, ku = float(stats.skew(x)), float(stats.kurtosis(x, fisher=False))
    d = metrics.deflated_sharpe(need / math.sqrt(365), len(x), pool["n_trials"], pool["var"], sk, ku)
    assert d == pytest.approx(0.95, abs=1e-6)
    assert need > metrics.expected_max_sharpe(pool["var"], pool["n_trials"]) * math.sqrt(365)


def test_the_ladder_climbs_only_in_order():
    assert t6.ladder(False, True, True, 200, True) == 0
    assert t6.ladder(True, False) == 1
    assert t6.ladder(True, True) == 2
    assert t6.ladder(True, True, True, 30, True) == 3
    assert t6.ladder(True, True, True, 90, True) == 4


def test_the_lockbox_is_never_looked_at_here():
    assert t6.lockbox_line(False, "A").startswith("no look")
    for lead in ("A", "B"):
        assert "not looked" in t6.lockbox_line(True, lead)


def test_f2s_pbo_comes_from_its_newest_run(monkeypatch, tmp_path):
    from lab.factory import ledger as lg
    monkeypatch.setattr(lg, "small_dir", lambda: tmp_path)
    assert t6.f2_pbo() is None
    (tmp_path / "runs").mkdir()
    for day, pbo in (("2026-10-27", 0.2), ("2026-10-28", 0.38)):
        (tmp_path / "runs" / f"{day}.json").write_text(json.dumps({"night": {"family": {"pbo": pbo, "genomes": 9}}}))
    assert t6.f2_pbo() == {"run": "2026-10-28", "pbo": 0.38, "genomes": 9}


# ---------------------------------------------------------------- lead A end to end

class ToyPanel:
    def __init__(self, days, btc):
        self.days, self.T, self.btc = days, len(days), 0
        self.ret = btc[:, None]


def toy_lead(edge: float, seed: int = 4):
    days = dc.us("2022-01-01") + np.arange(dc.us("2026-06-30") // D - dc.us("2022-01-01") // D + 1) * D
    rng = np.random.default_rng(seed)
    T = len(days)
    common = rng.normal(0, 0.004, T)
    net = {b: edge / 365 ** 0.5 * 0.01 + common + rng.normal(0, 0.008, T) for b in t6.BOOKS}
    for b in t6.BOOKS:
        net[b][:20] = np.nan
    return ToyPanel(days, rng.normal(0, 0.03, T)), net


@pytest.mark.parametrize("edge,passes", [(4.0, True), (0.0, False)])
def test_lead_a_registers_its_trials_first_and_a_planted_edge_clears_the_gates(monkeypatch, tmp_path, edge, passes):
    reg = tmp_path / "registry.jsonl"
    monkeypatch.setenv("PYTHIA_TRIALS_REGISTRY", str(reg))
    monkeypatch.setattr(dc, "ledger_trials", lambda: [])
    seen = []
    real = metrics.dsr
    monkeypatch.setattr(metrics, "dsr", lambda *a, **k: seen.append(reg.exists()) or real(*a, **k))
    P, net = toy_lead(edge)
    out = t6.lead_a(P, net, {"book": np.full(6, 0.001), **{b: np.full(6, 0.001) for b in t6.BOOKS}},
                    {"ok": True, "runs": 4}, log=lambda *_: None)
    ids = [r["id"] for r in metrics._read(reg)]
    assert all(f"hand:t6:a:{k}" in ids for k in t6.CANDIDATES) and seen and all(seen)
    assert out["conditions"]["A1 gates"] is passes
    assert out["to"] == "2026-06-30" and out["from"] == "2024-01-01"
    assert out["pbo"] is not None and out["cpcv"] is not None
    assert out["step"] >= (1 if passes else 0) and out["step"] <= 2
    assert out["validation"] is all(v for k, v in out["conditions"].items() if k != "A7 paper record")
    md_ok = "lockbox" in out and ("no look" in out["lockbox"] or "not looked" in out["lockbox"])
    assert md_ok
