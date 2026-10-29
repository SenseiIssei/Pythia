"""EQ1 without a data folder: the closes (the lockbox cut, bad prints, the IWM twin), the rules read nothing after
their close, a book trades one close late, an order under a broker's minimum is not sent (whole units, the lab's
10 EUR, an exit always), the top-up is booked on its day (a plan where the broker has one, cash at IB), the brokers'
fees, the time-weighted measures, and the study end to end with its 30 trials registered before any validation
number.

Run from research/lab:  python -m pytest tests/test_etf_books_eq1.py
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from lab import metrics
from lab.experiments import etf_books_eq1 as eq1

PX = {"EUNL.DE": 100.0, "SXR8.DE": 700.0, "EXSA.DE": 50.0, "EUNM.DE": 50.0, "IUSN.DE": 8.0, "EUNH.DE": 100.0,
      "4GLD.DE": 100.0, "XEON.DE": 150.0}


def bdays(a: str, z: str) -> np.ndarray:
    d = np.arange(np.datetime64(a), np.datetime64(z) + np.timedelta64(1, "D"))
    return d[np.is_busday(d)]


def series(a="2010-05-03", z="2026-08-31", seed=1, drift=None) -> dict:
    rng = np.random.default_rng(seed)
    d = bdays(a, z)
    out = {}
    for k, (s, p0) in enumerate(PX.items()):
        mu = (drift or {}).get(s, 0.0003)
        out[s] = (d, p0 * np.exp(np.cumsum(rng.normal(mu, 0.01, len(d)))))
    return out


def flat(a="2024-01-01", z="2024-06-28", px=None) -> eq1.Closes:
    d = bdays(a, z)
    return eq1.build({s: (d, np.full(len(d), (px or PX)[s])) for s in eq1.SYMBOLS}, to=None)


def test_the_lockbox_is_cut_before_anything_and_the_calendar_is_sxr8s():
    C = eq1.build(series())
    assert C.days[-1] <= np.datetime64(eq1.VAL_TO) and C.names == list(eq1.SYMBOLS)
    s = series()
    d, c = s["EXSA.DE"]
    s["EXSA.DE"] = (d[d != np.datetime64("2015-03-03")], c[d != np.datetime64("2015-03-03")])
    C = eq1.build(s)
    t, j = int(np.searchsorted(C.days, np.datetime64("2015-03-03"))), C.col("EXSA.DE")
    assert not C.fresh[t, j] and C.close[t, j] == C.close[t - 1, j] and C.fresh[t, C.col(eq1.SP500)]


def test_a_bad_print_is_dropped_and_a_real_move_kept():
    d = bdays("2020-01-01", "2020-01-10")
    c = np.array([100, 101, 140, 101, 102, 80, 79, 78.0])
    d2, c2, n = eq1.drop_spikes(d, c)
    assert n == 1 and 140 not in c2 and 80 in c2 and len(d2) == len(c2) == 7


def test_the_twin_joins_the_short_fund_in_eur():
    own = (bdays("2018-04-26", "2018-05-10"), np.full(11, 8.0))
    td = bdays("2018-04-02", "2018-05-10")
    twin = (td, np.linspace(150, 160, len(td)))
    fx = (np.array(["2018-03-30", "2018-04-16"], dtype="datetime64[D]"), np.array([1.25, 1.20]))
    d, c = eq1.splice_twin(own, twin, fx)
    assert d[0] == td[0] and (np.diff(d.astype(int)) > 0).all()
    k = int(np.searchsorted(d, own[0][0]))
    assert c[k] == 8.0 and np.all(np.isfinite(c[:k]))
    eur = twin[1][: k] / np.where(td[:k] < np.datetime64("2018-04-16"), 1.25, 1.20)
    assert np.allclose(c[:k] / c[k - 1], eur / eur[-1])


@pytest.mark.parametrize("book", eq1.BOOKS)
def test_a_rule_reads_nothing_after_its_close(book):
    C = eq1.build(series())
    t = int(np.searchsorted(C.days, np.datetime64("2024-03-28")))
    before = eq1.targets(book, C, t)
    C.close[t + 1:] *= np.random.default_rng(3).uniform(0.5, 2.0, C.close[t + 1:].shape)
    C.count[t + 1:] = 0
    assert eq1.targets(book, C, t) == before
    assert sum(before.values()) <= 1 + 1e-9


def test_a_book_trades_one_close_late():
    """trend_sp500: SXR8 falls under its 200-day mean on the month's last close t; the switch to XEON fills at the
    close of t+1 at t+1's prices, nothing at t."""
    d = bdays("2023-01-02", "2024-03-29")
    px = np.full(len(d), 700.0)
    t = int(np.flatnonzero(d == np.datetime64("2024-02-29"))[0])
    px[t:] = 500.0
    px[t + 1:] = 520.0
    s = {x: (d, np.full(len(d), PX[x])) for x in eq1.SYMBOLS}
    s[eq1.SP500] = (d, px)
    C = eq1.build(s, to=None)
    w = eq1.new_wallet(str(d[t - 5]))
    w["tgt"] = {eq1.SP500: 1.0}
    w["units"], w["cash"] = {eq1.SP500: 0.1}, 0.0
    b = eq1.BROKERS["tr"]
    r = eq1.step(w, "trend_sp500", "once", b, C, t)              # decides on close t-1 (not a month's end): nothing
    assert not r["fills"] and w["units"] == {eq1.SP500: 0.1}
    r = eq1.step(w, "trend_sp500", "once", b, C, t + 1)          # close t was February's last: fills at t+1
    assert r["decided"] and r["targets"] == {eq1.CASH: 1.0}
    sell = [f for f in r["fills"] if f["side"] == "sell"][0]
    assert sell["fund"] == eq1.SP500 and sell["eur"] == pytest.approx(0.1 * 520.0)
    assert eq1.CASH in w["units"] and eq1.SP500 not in w["units"]


def test_an_order_under_the_brokers_minimum_is_not_sent():
    C = flat()
    # one SXR8 unit is 700 EUR: whole units at IB, 50 EUR buys none
    for br in ("ibkr",):
        w = eq1.new_wallet(str(C.days[0]))
        r = eq1.step(w, "hold_sp500", "once", eq1.BROKERS[br], C, 1)
        assert not r["fills"] and w["not_sent"] == 1 and w["sent"] == 0 and w["cash"] == 50.0 and w["fees"] == 0
    # Scalable's whole units: dual momentum's one-off orders of 16.67 EUR buy whole cheap units only
    w = eq1.new_wallet(str(C.days[0]))
    px = {s: PX[s] for s in eq1.SYMBOLS}
    fresh = {s: True for s in eq1.SYMBOLS}
    eq1.orders(w, {"IUSN.DE": 0.5, "SXR8.DE": 0.5}, px, fresh, eq1.BROKERS["scalable"])
    assert set(w["units"]) == {"IUSN.DE"} and w["units"]["IUSN.DE"] == pytest.approx(2.0)   # 24 EUR: 2 units
    assert w["not_sent"] == 1 and w["sent"] == 1 and w["fees"] == pytest.approx(0.99)
    # the lab's 10 EUR: a 7.50 EUR entry at Trade Republic is not sent, a 50 EUR one is
    w = eq1.new_wallet(str(C.days[0]))
    eq1.orders(w, {eq1.SP500: 0.15}, px, fresh, eq1.BROKERS["tr"])
    assert w["not_sent"] == 1 and w["sent"] == 0 and w["cash"] == 50.0
    eq1.orders(w, {eq1.SP500: 1.0}, px, fresh, eq1.BROKERS["tr"])
    assert w["sent"] == 1 and w["fees"] == 1.0 and w["cash"] == pytest.approx(0.0, abs=1e-9)
    assert w["units"][eq1.SP500] * 700 * 1.0005 == pytest.approx(49.0)
    # an exit is always sent, even under 10 EUR, fractions included
    w = {**eq1.new_wallet(str(C.days[0])), "cash": 45.0, "units": {"IUSN.DE": 0.5}}
    eq1.orders(w, {}, px, fresh, eq1.BROKERS["scalable"])
    assert w["units"] == {} and w["sent"] == 1 and w["cash"] == pytest.approx(45 + 4 * (1 - 0.001) - 0.99)
    # a gap under the band does not trade
    w = {**eq1.new_wallet(str(C.days[0])), "cash": 4.0, "units": {eq1.SP500: 46 / 700}}
    assert eq1.orders(w, {eq1.SP500: 1.0}, px, fresh, eq1.BROKERS["tr"]) == [] and w["not_sent"] == 0


def test_a_fund_without_its_own_close_is_not_traded():
    C = flat()
    C.fresh[1, C.col(eq1.SP500)] = False
    w = eq1.new_wallet(str(C.days[0]))
    eq1.step(w, "hold_sp500", "once", eq1.BROKERS["tr"], C, 1)
    assert w["units"] == {} and w["cash"] == 50.0


def test_the_top_up_is_booked_on_its_day():
    C = flat("2024-01-02", "2024-03-29")
    first = [i for i in range(1, C.T) if eq1._month(C.days[i]) != eq1._month(C.days[i - 1])]
    assert [str(C.days[i]) for i in first] == ["2024-02-01", "2024-03-01"]
    for br in ("tr", "scalable"):
        w = eq1.new_wallet(str(C.days[0]))
        flows = [eq1.step(w, "hold_world", "plus50", eq1.BROKERS[br], C, s)["flow"] for s in range(1, C.T)]
        assert [s for s, f in enumerate(flows, 1) if f] == first and set(flows) == {0.0, 50.0}
        assert w["paid"] == 150.0 and w["topups"] == 2 and w["fees"] == 0.0 and w["sent"] == 0
        assert w["cash"] == pytest.approx(0.0, abs=1e-9) and w["plan_eur"] == pytest.approx(150.0)
        assert w["units"][eq1.WORLD] == pytest.approx(150 / (100 * 1.0005))
    w = eq1.new_wallet(str(C.days[0]))
    rows = [eq1.step(w, "hold_world", "plus50", eq1.BROKERS["ibkr"], C, s) for s in range(1, C.T)]
    assert w["paid"] == 150.0 and w["plan_eur"] == 0.0
    # IB: no plan; the cash waits for the order day after a month's last close (the top-up's day here), whole
    # units: 100 EUR do not buy one unit at 100.05, 150 EUR do
    assert w["units"][eq1.WORLD] == 1 and w["not_sent"] == 2 and w["fees"] == 1.25
    assert not rows[first[0] - 1]["fills"] and rows[first[1] - 1]["fills"] and rows[first[1] - 1]["flow"] == 50.0
    w = eq1.new_wallet(str(C.days[0]))
    once = [eq1.step(w, "hold_world", "once", eq1.BROKERS["tr"], C, s)["flow"] for s in range(1, C.T)]
    assert set(once) == {0.0} and w["paid"] == 50.0


def test_the_brokers_fees_as_stated():
    tr, sc, ib = (eq1.BROKERS[k] for k in ("tr", "scalable", "ibkr"))
    assert tr.fee(5) == tr.fee(5000) == 1.0 and sc.fee(5) == 0.99
    assert ib.fee(100) == 1.25 and ib.fee(10_000) == pytest.approx(5.0)
    assert tr.fractional and tr.plan and not sc.fractional and sc.plan and not ib.fractional and not ib.plan


def test_measures_take_the_top_up_out():
    C = flat("2024-01-02", "2024-12-31")
    run = eq1.simulate(C, "hold_world", "plus50", eq1.BROKERS["tr"], 0, C.T - 1)
    m = eq1.measure(run)
    assert m["paid"] == 600.0 and abs(m["cagr"]) < 0.005 and m["max_dd"] < 0.005 and abs(m["mwr"]) < 0.01
    days = bdays("2024-01-01", "2024-12-31")
    idx = np.r_[np.ones(20), np.full(60, 0.9), np.ones(len(days) - 80) * 1.01]
    uw, now = eq1.under_water_months(days, idx)
    assert uw == pytest.approx(int((days[80] - days[19]).astype(int)) / eq1.MONTH_DAYS) and now == 0
    x = eq1.calendar(days[:3], np.array([0.0, 0.01, 0.02]))
    assert len(x) == int((days[2] - days[0]).astype(int))


def test_dual_mom_holds_the_top_three_with_a_positive_year():
    drift = {s: -0.001 for s in eq1.SYMBOLS}
    drift.update({"EUNM.DE": 0.002, "4GLD.DE": 0.0015})
    C = eq1.build(series(drift=drift, seed=5))
    t = int(np.searchsorted(C.days, np.datetime64("2020-06-30")))
    tg = eq1.targets("dual_mom", C, t)
    assert set(tg) == {"EUNM.DE", "4GLD.DE"} and all(v == pytest.approx(1 / 3) for v in tg.values())


def test_the_study_registers_its_30_trials_before_any_validation_number(tmp_path, monkeypatch):
    reg = tmp_path / "registry.jsonl"
    monkeypatch.setenv("PYTHIA_TRIALS_REGISTRY", str(reg))
    seen = []
    real = metrics.dsr

    def spy(x, pool=None, family=None):
        seen.append(sum(1 for r in metrics._read(reg) if r["id"].startswith("small:eq1:")))
        return real(x, pool, family)
    monkeypatch.setattr(metrics, "dsr", spy)
    C = eq1.build(series(seed=7))
    out = eq1.evaluate(C, log=lambda *a: None)
    assert seen and min(seen) == 30
    rows = [r for r in metrics._read(reg) if r["id"].startswith("small:eq1:")]
    assert len(rows) == 30 and all(r["family"] == "small" for r in rows)
    assert all((r["sharpe"] is None) == (":hold_sp500:" in r["id"]) for r in rows)
    assert len(out["rows"]) == 30 and sum("pass" in r for r in out["rows"]) == 24
    assert all(r["val"]["to"] <= eq1.VAL_TO and r["is"]["from"] >= eq1.IS_FROM for r in out["rows"])
    s = eq1.summary(out)
    json.dumps(s, default=float)
    assert s["judged"] == "tr" and len(s["trials"]) == 30 and "under_water_months" in s["rows"][0]["val"]
    assert "## 1. Validation" in eq1.markdown(out, {"generated": "now"})
