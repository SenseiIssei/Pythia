"""R7b (results/dsr_bar_r7b_prereg.md): the trial variance net of sampling noise and its floor, the effective trial
count (near copies one cluster, independent trials apart, no entries one cluster, short trials one each), and the
false pass rate of both bars on a small simulated zero-edge family, reproduced from its seed.

Run from research/lab:  python -m pytest tests/test_dsr_r7b.py
"""

from __future__ import annotations

import numpy as np

from lab.pumpfun_rt import dsr_r7b as D

DAYS = [f"2026-10-{d:02d}" for d in range(22, 30)]
SMALL = {"nights": [(20, 3, False), (40, 8, True)], "entries": [0, 5, 20, 30, 40, 60, 120, 300], "skew": 0.0,
         "kurt": 3.0}


def trial(sharpe: float, entries: int, pnl=None, skew: float = 0.0, kurt: float = 3.0) -> dict:
    r = {"sharpe": sharpe, "entries": entries, "skew": skew, "kurt": kurt, "days": DAYS}
    if pnl is not None:
        r["day_pnl"] = [float(v) for v in pnl]
    return r


def test_noise_var_nets_out_one_over_n_and_floors_at_it():
    tr = [trial(s, 100) for s in (-0.5, 0.0, 0.5)] + [trial(3.0, 5)]          # under MIN_ENTRIES: left out
    x = D.noise_var(tr)
    assert x["used"] == 3 and abs(x["v_raw"] - 0.25) < 1e-12
    q = 1 + 1 / 2 * 0.25                                                       # normal tails at |SR| 0.5
    assert abs(x["m"] - (2 * q + 1) / 3 / 100) < 1e-12 and abs(x["v_new"] - (0.25 - x["m"])) < 1e-12
    y = D.noise_var([trial(s, 100) for s in (-0.05, 0.0, 0.05)])               # spread under the noise: the floor
    assert y["v_new"] == y["m"] > y["v_raw"] - y["m"]
    assert D.noise_var([trial(0.1, 100)])["v_new"] == 0.0


def test_effective_trials_merges_copies_only():
    rng = np.random.default_rng(1)
    mkt = rng.standard_normal(8) * 3
    base = [rng.standard_normal(8) for _ in range(4)]
    tr = [trial(0.1, 50, mkt + b + 0.01 * rng.standard_normal(8)) for b in base for _ in range(5)]   # 4 genomes x 5
    tr += [trial(0.0, 0), trial(0.0, 0), trial(0.1, 50), trial(0.1, 10, rng.standard_normal(8))]
    tr += [trial(0.1, 50, list(rng.standard_normal(4)) + [0, 0, 0, 0])]       # 4 days with P&L only
    e = D.effective_trials(tr)
    assert (e["clustered"], e["clusters"], e["flat"], e["singles"]) == (20, 4, 2, 3) and e["n_eff"] == 8
    alone = D.effective_trials([trial(0.1, 50, rng.standard_normal(8)) for _ in range(30)])
    assert alone["n_eff"] == 30                                               # independent residuals stay apart


def test_bar_and_deflated_use_the_given_variance_and_count():
    assert D.sr0(0.01, 1000) < D.sr0(0.04, 1000) and D.sr0(0.01, 100) < D.sr0(0.01, 1000)
    r = {"sharpe": 0.3, "entries": 500, "n_eff": 500, "skew": 0.0, "kurt": 3.0}
    assert D.deflated(r, 0.01, 50) > D.deflated(r, 0.01, 5000) > D.deflated(r, 0.04, 5000)
    assert D.deflated({"sharpe": 1.0, "entries": 1}, 0.01, 10) == 0.0


def test_family_has_the_shape_asked():
    rng = np.random.default_rng(2)
    f = D.family(SMALL, 5, 0.1, "f3", rng)
    assert len(f) == 60 and sum("day_pnl" in r for r in f) == 40
    assert {r["entries"] for r in f} <= set(SMALL["entries"])
    assert len({r["genome"] for r in f}) < 60
    x = D._noise(np.random.default_rng(0), 200_000, "f3")
    assert abs(x.mean()) < 0.01 and abs(x.std() - 1) < 0.01 and -1.6 < float(((x - x.mean()) ** 3).mean()) < -1.3


F3ISH = {"nights": [(60, 3, False), (90, 8, True)], "entries": [0, 0, 2, 20, 25, 30, 40, 60, 120, 300, 600],
         "skew": 0.0, "kurt": 3.0}


def test_false_pass_rate_reproduced_on_a_small_family():
    """The failure of (c) on a family of 150 trials with F3's short trials, copies, a market day and F3's tails: the
    in-sample best passes the new bar in 9 of 100 null families (the old bar 6), over the 5 % allowed."""
    a = D.false_rate(F3ISH, 5, 0.3, "f3", 100, seed=11)
    assert a == D.false_rate(F3ISH, 5, 0.3, "f3", 100, seed=11) and a["trials"] == 150
    assert (a["false_old"], a["false_new"]) == (0.06, 0.09) and a["false_new"] > D.FALSE_MAX
    assert a["sr0_new"] < a["sr0_old"] and a["n_eff"] < a["trials"]
    n = D.false_rate(F3ISH, 1, 0.0, "normal", 100, seed=11)
    assert (n["false_old"], n["false_new"]) == (0.0, 0.02)                    # normal tails, no copies: held
    assert n["genomes"] == 150 and n["n_eff"] <= 150


def test_ladder_keeps_r7s_bar_since_the_simulation_failed():
    from lab.ops import ladder
    ids = {t["id"] for t in ladder.pf_trials()}
    assert D.PASSED is False and not any(i.startswith("pumpfun:r7b:") for i in ids)
