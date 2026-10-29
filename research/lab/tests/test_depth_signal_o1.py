"""O1 without a data folder: a depth feature is known only after its bucket (an hour, a day) and O1's two 30-day
features read only the rows before, the feature matrices put a day's row on its close and never read the
lockbox, the books' targets (XS fifths, TS signs, a thin day holds), the late forward return, the rank IC and the
depth-falling test on planted relations, T1's harness passing the books' weights and catching a planted look-ahead,
and the study end to end with its 7 trials registered before any validation number.

Run from research/lab:  python -m pytest tests/test_depth_signal_o1.py
"""

from __future__ import annotations

import json
import math
from types import SimpleNamespace

import numpy as np
import polars as pl
import pytest

from lab import metrics
from lab.collect import book_depth as bd
from lab.experiments import depth_signal_o1 as o1
from lab.experiments import director_common as dc
from lab.experiments import fam_common as fc
from lab.features import book as fbook  # noqa: F401  (registers the book_depth features)
from lab.features import registry as R
from lab.leak import checks
from test_pit_universe_t5 import toy_panel

D, H = fc.DAY_US, 3_600_000_000


def write_hours(root, sym: str, rows: list[tuple], month: str = "2024-01") -> None:
    """Hourly rows (ts_us, bid1, ask1, cost100k) of one perp in T4's layout."""
    df = pl.DataFrame(rows, schema=["ts_us", "bid1", "ask1", "cost100k"], orient="row")
    df = df.with_columns(bid02=pl.lit(None, pl.Float64), ask02=pl.lit(None, pl.Float64), cost10k=pl.lit(1.0),
                         n=pl.lit(120, pl.Int32), n_fine=pl.lit(0, pl.Int32), published_us=pl.col("ts_us") + D,
                         **{c: pl.col(c).cast(pl.Float64) for c in ("bid1", "ask1", "cost100k")})
    p = root / "hourly" / f"symbol={sym}" / f"{month}.parquet"
    p.parent.mkdir(parents=True, exist_ok=True)
    df.select(list(bd.HOURLY_SCHEMA)).write_parquet(p)


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHIA_BOOK_DEPTH", str(tmp_path / "bd"))
    R.clear()
    yield tmp_path / "bd"
    R.clear()


def day_rows(d0: int, days: int, bid=lambda i: 3.0, ask=lambda i: 1.0, cost=lambda i: 2.0) -> list[tuple]:
    return [(d0 + i * D + h * H, bid(i), ask(i), cost(i)) for i in range(days) for h in range(24)]


# ---------------------------------------------------------------- the features, point in time

def test_a_depth_feature_is_known_only_after_its_hour_and_its_day(store):
    d0 = dc.us("2024-01-01")
    write_hours(store, "AAAUSDT", day_rows(d0, 2, bid=lambda i: 3.0 + i))
    f = R.frame(["bd_imb1"], ["AAA"], [d0 + H - 1, d0 + H, d0 + 2 * H], "1h")
    assert f["bd_imb1"][0] is None                                  # the first hour is not over yet
    assert f["bd_imb1"][1] == pytest.approx(0.5) and f["bd_imb1"][2] == pytest.approx(0.5)
    g = R.frame(["bd_imb1"], ["AAA"], [d0 + D - 1, d0 + D, d0 + 2 * D - 1, d0 + 2 * D], "1d")
    assert g["bd_imb1"].to_list()[0] is None                        # the day's row only from its close
    assert g["bd_imb1"].to_list()[1:] == pytest.approx([0.5, 0.5, 0.6])


def test_the_30_day_features_read_only_the_rows_before(store):
    d0 = dc.us("2024-01-01")
    bid = lambda i: 1.0 + (i % 7)                                    # noqa: E731
    cost = lambda i: 1.0 + i                                         # noqa: E731
    write_hours(store, "AAAUSDT", day_rows(d0, 40, bid=bid, cost=cost))
    imb = R.values("bd_imb1_dev30", "1d", ["AAA"]).sort("ts_us")
    c = R.values("bd_cost100k_dev30", "1d", ["AAA"]).sort("ts_us")
    assert imb["ts_us"][0] == d0 + 20 * D and c["ts_us"][0] == d0 + 20 * D       # at least 20 rows before
    assert imb["known_us"][0] == d0 + 21 * D
    i = 35
    x = [(bid(k) - 1) / (bid(k) + 1) for k in range(40)]
    row = imb.filter(pl.col("ts_us") == d0 + i * D)["value"][0]
    assert row == pytest.approx(x[i] - np.mean(x[i - 30:i]))
    row = c.filter(pl.col("ts_us") == d0 + i * D)["value"][0]
    assert row == pytest.approx(math.log(cost(i)) - np.mean([math.log(cost(k)) for k in range(i - 30, i)]))
    for n in ("bd_imb1_dev30", "bd_cost100k_dev30"):
        assert R.get(n).freqs == ("1d",)


def test_the_new_features_pass_t1_and_a_planted_one_does_not():
    for n in ("bd_imb1_dev30", "bd_cost100k_dev30"):
        t = checks.synthetic_table(checks.feature_columns(n, "1d"), "1d")
        assert checks.feature(n, "1d", t)["ok"], n
    bad = R.Feature("bd_o1_planted", "book_depth", ("book_depth/hourly",), "30s", 0,
                    lambda p: pl.col("bid1") - pl.col("bid1").shift(-1).rolling_mean(5).over("asset"), freqs=("1d",))
    R.register(bad)
    try:
        t = checks.synthetic_table(["bid1"], "1d")
        assert not checks.feature("bd_o1_planted", "1d", t)["ok"]
    finally:
        R.REGISTRY.pop("bd_o1_planted")


def test_the_matrices_put_a_day_on_its_close_by_coin_and_never_read_the_lockbox(store):
    d0 = dc.us("2026-06-28")
    write_hours(store, "AAAUSDT", day_rows(d0, 2, bid=lambda i: 3.0 + i), month="2026-06")
    write_hours(store, "1000BBBUSDT", day_rows(dc.us("2026-07-01"), 1), month="2026-07")
    days = d0 + np.arange(4) * D
    P = SimpleNamespace(days=days, names=["AAAUSDT", "BBBUSDT", "OLDUSDT~0"], T=4, N=3)
    F = o1.feature_matrices(P, ("bd_imb1",), cut="2026-07-01", since="2026-06-01")["bd_imb1"]
    assert F[:2, 0] == pytest.approx([0.5, 0.6]) and np.isnan(F[2:, 0]).all()
    assert np.isnan(F[:, 1:]).all()                                  # BBB's only day is in the lockbox
    assert not R._TABLES                                             # the cut table is not left behind


# ---------------------------------------------------------------- the books

def test_targets_xs_fifths_ts_signs_and_a_thin_day_holds(monkeypatch):
    T, N = 3, 25
    s = np.tile(np.arange(N, dtype=float), (T, 1)) - 12
    uni = np.ones((T, N), dtype=bool)
    uni[2, 5:] = False                                               # 5 coins: below MIN_COINS
    W = o1.targets(s, uni, "xs", np.array([True, False, True]))
    assert W[0, -5:] == pytest.approx([0.1] * 5) and W[0, :5] == pytest.approx([-0.1] * 5)
    assert W[0].sum() == pytest.approx(0) and np.abs(W[0]).sum() == pytest.approx(1)
    assert np.isnan(W[1]).all() and np.isnan(W[2]).all()             # not a rebalance day; too few coins
    V = o1.targets(s, uni, "ts", np.ones(T, dtype=bool))
    assert V[0, 0] == pytest.approx(-1 / 25) and V[0, 12] == 0 and V[0, -1] == pytest.approx(1 / 25)


def test_the_forward_return_starts_one_close_late():
    px = np.array([[1.0], [2.0], [4.0], [8.0], [16.0]])
    f1 = o1.forward(SimpleNamespace(px=px, T=5), 1)
    f2 = o1.forward(SimpleNamespace(px=px, T=5), 2)
    assert f1[:3, 0] == pytest.approx([1.0, 1.0, 1.0]) and np.isnan(f1[3:]).all()   # close 1 to 2 for day 0
    assert f2[:2, 0] == pytest.approx([3.0, 3.0]) and np.isnan(f2[2:]).all()


def test_the_rank_ic_and_the_depth_falling_test_find_planted_relations():
    rng = np.random.default_rng(1)
    T, N = 200, 40
    s = rng.normal(size=(T, N))
    y = 0.5 * s + rng.normal(size=(T, N))
    uni = np.ones((T, N), dtype=bool)
    ic = o1.rank_ic(s, y, uni, np.ones(T, dtype=bool))
    assert 0.3 < np.nanmean(ic) < 0.6 and o1.hac_t(ic, 10) > 5
    assert np.nanmean(o1.rank_ic(rng.normal(size=(T, N)), y, uni, np.ones(T, dtype=bool))) == pytest.approx(0, abs=0.03)
    chg = rng.normal(size=(T, N))
    ret = rng.normal(0, 0.02, (T, N))
    ret[1:] *= np.exp(-0.5 * chg[:-1])                               # depth falling: a bigger move next day
    P = SimpleNamespace(ret=ret, T=T)
    v = o1.vol_test(P, chg, uni, np.arange(T) >= 40)
    assert np.nanmean(v) > 0.1 and o1.hac_t(v, 10) > 5
    v0 = o1.vol_test(SimpleNamespace(ret=rng.normal(0, 0.02, (T, N)), T=T), chg, uni, np.arange(T) >= 40)
    assert abs(o1.hac_t(v0, 10)) < 3


def depth_panel(monkeypatch, days: int = 400):
    P = toy_panel(monkeypatch, days=days, extra=30)
    rng = np.random.default_rng(3)
    for f in o1.FEATURES:
        x = rng.normal(size=(P.T, P.N)) if "cost" not in f or "dev" in f else np.exp(rng.normal(size=(P.T, P.N)))
        P.extra[f] = np.where(P.traded, x, np.nan)
    return P


def test_t1_passes_the_books_weights_and_catches_a_planted_look_ahead(monkeypatch):
    monkeypatch.setattr(o1, "MIN_COINS", 4)
    P = depth_panel(monkeypatch)
    for b in ("imb:xs", "illiq:ts"):
        sig, how = b.split(":")
        W = o1.weights(P, sig, how)
        assert np.isfinite(W).any()
        assert checks.book(b, lambda X, s=sig, h=how: o1.weights(X, s, h), P)["ok"], b
    real = o1.score

    def planted(X, sig, how):                                        # tomorrow's imbalance as today's score
        s = real(X, sig, how)
        return np.vstack([s[1:], np.full((1, s.shape[1]), np.nan)])
    monkeypatch.setattr(o1, "score", planted)
    res = checks.book("planted", lambda X: o1.weights(X, "imb", "xs"), P)
    assert not res["ok"] and res["first"]["kind"] in ("shuffle", "shift", "nan", "recursive")


# ---------------------------------------------------------------- end to end

def test_the_study_end_to_end_registers_its_7_trials_first(monkeypatch):
    monkeypatch.setattr(o1, "MIN_COINS", 4)
    monkeypatch.setattr(dc, "ledger_trials", lambda: [])
    P = dc.cut_panel(depth_panel(monkeypatch, days=2400), o1.VAL_TO)
    C = np.full((P.T, P.N), 0.0010)
    order = []
    real_reg, real_dsr = metrics.register, metrics.dsr
    monkeypatch.setattr(metrics, "register", lambda rows, path=None: order.append(("reg", len(rows)))
                        or real_reg(rows, path))
    monkeypatch.setattr(metrics, "dsr", lambda *a, **k: order.append(("dsr", 0)) or real_dsr(*a, **k))
    leaks = {b: {"name": b, "ok": True, "runs": 12, "first": None} for b in o1.BOOKS}
    out = o1.evaluate(P, C, None, leaks, log=lambda *_: None)
    assert order[0] == ("reg", 7) and all(k == "dsr" for k, _ in order[1:])
    ids = {r["id"] for r in metrics.read_registry()}
    assert {f"hand:o1:{b}" for b in o1.BOOKS} | {"hand:o1:dchg:vol"} <= ids
    assert set(out["books"]) == set(o1.BOOKS) and out["to"] == o1.VAL_TO
    for r in out["books"].values():
        assert r["val"]["days"] > 0 and np.isfinite(r["is"]["sharpe"]) and 0 <= r["coverage"]["val"] <= 1
        assert set(r["conditions"]) == {"1 Sharpe and years", "2 test t", "3 DSR all and family", "4 PBO", "5 leak"}
    assert out["passed"] == [] or out["lockbox"].startswith("look due")
    md = o1.markdown(json.loads(json.dumps(out, default=float)), {"generated": "test", "delist": "not present",
                                                                   "feature_leak": {"bd_imb1": True}})
    assert md.count("| imb:xs |") == 2 and "\u2014" not in md and "Depth falling" in md


def test_a_book_passes_only_when_every_condition_holds():
    v = {"sharpe": 1.0}
    yrs = {2024: 1.0, 2025: 0.5, 2026: -0.2}
    ok = o1.passes(v, yrs, 2.5, 0.96, 0.97, {"pbo": 0.3}, True)
    assert all(ok.values())
    assert not o1.passes(v, {2024: 1.0, 2025: -0.5, 2026: -0.2}, 2.5, 0.96, 0.97, {"pbo": 0.3}, True)["1 Sharpe and years"]
    assert not o1.passes(v, yrs, 1.9, 0.96, 0.97, {"pbo": 0.3}, True)["2 test t"]
    assert not o1.passes(v, yrs, 2.5, 0.96, 0.90, {"pbo": 0.3}, True)["3 DSR all and family"]
    assert not o1.passes(v, yrs, 2.5, 0.96, 0.97, None, True)["4 PBO"]
    assert not o1.passes(v, yrs, 2.5, 0.96, 0.97, {"pbo": 0.3}, False)["5 leak"]
