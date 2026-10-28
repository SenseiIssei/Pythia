"""T8's forward evidence on simulated records: the e-process holds its 5 % under daily looks, a true edge shows in
about the predicted days, partial pooling adds short records up. No lab data.

Run from research/lab:  python -m pytest tests/test_power.py
"""

from __future__ import annotations

import csv
import json
import math

import numpy as np
import pytest

from lab import metrics, report
from lab.paper import forward_report as fr
from lab.paper import power as pw

SD = 0.02
YEARS3 = 3 * 365


def ever_rejects(y: np.ndarray, rho: float) -> np.ndarray:
    le = pw.log_e(np.cumsum(y, 1), np.cumsum(y * y, 1), rho)
    return (le >= math.log(pw.LEVEL)).any(1)


def rho_at(sharpe: float) -> float:
    return pw.rho_for(SD ** 2, pw.fixed_days(sharpe / math.sqrt(365)))


@pytest.mark.parametrize("kind", ["normal", "t3", "skewed"])
def test_zero_edge_rejects_at_most_5_percent_over_daily_looks(kind):
    rng = np.random.default_rng(1)
    shape = (2000, YEARS3)
    if kind == "normal":
        y = rng.normal(0, SD, shape)
    elif kind == "t3":
        y = rng.standard_t(3, shape) * SD / math.sqrt(3)
    else:                                            # mostly small gains, rare big losses, mean 0
        z = rng.exponential(1.0, shape)
        y = (1 - z) * SD
    for sharpe in (1.0, 2.0):
        share = ever_rejects(y, rho_at(sharpe)).mean()
        assert share <= 0.05 + 3 * math.sqrt(0.05 * 0.95 / 2000), (kind, sharpe, share)


def test_below_band_test_holds_its_level_at_the_validated_mean():
    rng = np.random.default_rng(2)
    mu = 2.0 / math.sqrt(365) * SD
    x = rng.normal(mu, SD, (2000, YEARS3))
    assert ever_rejects(mu - x, rho_at(2.0)).mean() <= 0.065


@pytest.mark.parametrize("kind", ["normal", "t3"])
def test_true_edge_found_in_about_the_predicted_days(kind):
    mu = 2.0 / math.sqrt(365) * SD
    draw = ((lambda rng, s: rng.normal(mu, SD, s)) if kind == "normal" else
            (lambda rng, s: mu + rng.standard_t(3, s) * SD / math.sqrt(3)))
    rho = pw.rho_for(SD ** 2 + mu ** 2, pw.fixed_days(mu / SD))
    need = pw.sequential_days(lambda rng, s: rng.normal(mu, SD, s), rho)
    assert pw.fixed_days(mu / SD) < need < 3 * pw.fixed_days(mu / SD)
    y = draw(np.random.default_rng(99), (2000, int(need)))
    found = ever_rejects(y, rho).mean()
    assert 0.70 <= found <= 0.90, (kind, need, found)


def test_fixed_days_for_a_sharpe_of_one_is_about_six_years():
    assert pw.fixed_days(1 / math.sqrt(365)) / 365 == pytest.approx(6.19, abs=0.05)
    assert pw.fixed_days(0.0) == math.inf


def test_e_path_and_first_cross():
    e = pw.e_path(np.full(400, 0.01), pw.rho_for(1e-4, 100))
    assert e[0] < pw.LEVEL and pw.first_cross(e) is not None
    assert pw.first_cross(np.array([1.0, 5.0, 19.9])) is None


def test_cut_keeps_validation_only():
    r = np.ones(400) * 0.001
    assert len(pw._cut(r, "2026-01-01")) == 181          # 2026-01-01 to 2026-06-30
    assert len(pw._cut(r, None)) == 400


def test_pooling_adds_short_records_up():
    rng = np.random.default_rng(5)
    mu = 2.0 / math.sqrt(365)
    m = np.array([rng.normal(mu, 1 / math.sqrt(30)) for _ in range(12)])
    se = np.full(12, 1 / math.sqrt(30))
    h = pw.hierarchical(m, se)
    from scipy import stats
    alone = stats.norm.cdf(m / se)
    assert h["p_pos"] > np.median(alone)
    assert h["band"][0] < h["mean"] < h["band"][1]
    assert np.std(h["theta"]) < np.std(m)                 # shrunk toward the family


def test_correlated_members_count_as_fewer():
    d = [f"2026-10-{i:02d}" for i in range(1, 21)]
    x = np.random.default_rng(3).normal(0, 0.01, 20)
    assert pw.mean_corr([dict(zip(d, x)), dict(zip(d, 2 * x)), dict(zip(d, x + 1))]) == pytest.approx(1.0)
    assert pw.mean_corr([dict(zip(d, x)), dict(zip(d, -x))]) == 0.0           # clipped at 0
    assert pw.mean_corr([dict(zip(d, x))]) == 0.0


def test_assess_verdicts():
    dates = [f"d{i}" for i in range(200)]
    val = {"mean": 0.002, "sd": SD, "days": 900, "method": "series", "source": "test",
           "sample": np.random.default_rng(4).normal(0.002, SD, 900)}
    bad = np.random.default_rng(6).normal(-0.006, SD, 200)
    r = pw.assess("x", "book", dates, bad, val, sim=False)
    assert r["verdict"] == "below its band" and r["below_day"] and not r["ladder"]["paper_ok"]
    good = np.random.default_rng(7).normal(0.008, SD, 200)
    r = pw.assess("x", "book", dates, good, val, sim=False)
    assert r["verdict"] == "edge shown" and r["e_edge"] >= pw.LEVEL and r["ladder"]["paper_ok"]
    r = pw.assess("x", "book", dates[:5], good[:5], None)
    assert r["verdict"] == "no evidence yet" and r["e_edge"] is None
    r = pw.assess("x", "book", dates[:20], good[:20], {**val, "mean": -0.001})
    assert r["seq_days"] == -math.inf and r["verdict"] == "consistent with validation"


def _journal(root, book, equity):
    d = root / "paper" / book
    d.mkdir(parents=True)
    with (d / "journal.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["date", "equity", "turnover"])
        w.writeheader()
        for i, e in enumerate(equity):
            w.writerow({"date": f"2026-10-{i + 1:02d}", "equity": f"{e:.2f}", "turnover": "0.1"})


def test_build_registers_writes_and_feeds_the_forward_report(tmp_path, monkeypatch):
    monkeypatch.setattr(report, "REPORTS", tmp_path / "reports")
    monkeypatch.setenv("PYTHIA_TRIALS_REGISTRY", str(tmp_path / "registry.jsonl"))
    monkeypatch.setenv("PYTHIA_FACTORY_DIR", str(tmp_path / "factory"))
    rng = np.random.default_rng(8)
    eq = list(fr.START_EQUITY * np.cumprod(1 + rng.normal(0.001, 0.01, 20)))
    _journal(tmp_path, "tsmom", eq)
    _journal(tmp_path, "tsmom_regime", eq[:12])
    bt = fr.backtest_dir()
    bt.mkdir(parents=True)
    (bt / "tsmom.json").write_text(json.dumps({"book": "tsmom", "period_days": 1, "first": "2024-01-01",
                                               "returns": list(rng.normal(0.002, 0.02, 1000))}))
    sd = tmp_path / "factory" / "shadow"
    sd.mkdir(parents=True)
    (sd / "abc123.json").write_text(json.dumps({"key": "abc123", "status": "active",
                                                "holdout": {"oos_from": "2024-01-01"},
                                                "oos_net_35bps": list(rng.normal(0.001, 0.02, 1000))}))
    with (sd / "abc123.csv").open("w") as fh:
        fh.write("date,net_ret\n" + "".join(f"2026-10-{i + 1:02d},{v:.6f}\n"
                                            for i, v in enumerate(rng.normal(0, 0.01, 8))))
    data = pw.build(tmp_path)
    names = {r["name"]: r for r in data["rows"]}
    assert set(names) >= {"tsmom", "tsmom_regime", "abc123"}
    assert names["tsmom"]["validated"]["days"] == 912     # cut at 2026-06-30
    assert names["tsmom"]["days"] == 20 and names["abc123"]["family"] == "factory shadows"
    assert data["families"]["momentum"]["members"] == ["tsmom", "tsmom_regime"]
    ids = {r["id"] for r in metrics.read_registry()}
    assert {"hand:t8:tsmom", "factory:t8:abc123", "hand:t8:pool:momentum", "factory:t8:pool:factory shadows"} <= ids
    n = len(metrics.read_registry())
    pw.build(tmp_path, sim=False)
    assert len(metrics.read_registry()) == n              # a rerun is a no-op
    p = pw.write(data)
    assert "Forward evidence" in p.read_text() and (p.parent / "power.json").exists()
    json.loads((p.parent / "power.json").read_text())
    s = pw.summary(data)
    md = fr.markdown({"generated": "now", "verdict": "v", "books": [], "autopilots": [],
                      "engine": {"reachable": True, "slippage": []}, "power": s})
    assert "## Forward evidence (T8)" in md and "`tsmom`:" in md and "abc123" not in md.split("(T8)")[1]


def test_sequential_days_stops_at_the_quantile_without_stepping_into_an_open_path():
    mu = 1.0 / math.sqrt(365) * SD
    rho = pw.rho_for(SD ** 2 + mu ** 2, pw.fixed_days(mu / SD))
    need = pw.sequential_days(lambda rng, s: rng.normal(mu, SD, s), rho, paths=400)
    assert math.isfinite(need) and pw.fixed_days(mu / SD) < need < 3 * pw.fixed_days(mu / SD)
