"""Y9, models that pick the coins worth buying at the migration: the registered strategies and trials, the
Tracker's features (what they count, and no look-ahead: a feature at t never reads an event after t), the label
book (its return is P_pool0's, the rug label, its own pid space), the select filter's wiring, the models
(threshold, purge, walk-forward, files), the day-by-day models of the replay, the replay end to end, and every
strategy before Y9 trading exactly as before with the Y9 books, the tracker and the label book next to it. No
network, no wallet.

Run from research/lab:  python -m pytest tests/test_pumpfun_select_y9.py
"""

from __future__ import annotations

import json
import math

import numpy as np
import pytest

from lab.pumpfun_rt import curve as C
from lab.pumpfun_rt import exitlab as XL
from lab.pumpfun_rt import model as M
from lab.pumpfun_rt import pipeline as P
from lab.pumpfun_rt import select9 as Y9
from lab.pumpfun_rt import selfeat as SF
from lab.pumpfun_rt import selmodel as SM
from lab.pumpfun_rt import sim
from lab.pumpfun_rt import store
from lab.pumpfun_rt import strategies as S
from test_pumpfun_exit_runners import BASE0, QUOTE0, Pool
from test_pumpfun_rt import BUYERS, MINT, SOL, T0, Curve, Fixed, key

Y9_NAMES = ["P_pool0_norug", "P_pool0_top30", "P_pool0_norug_top30", "P_pool5_top30", "P_pool0_smart2"]
OLD = P.STRATEGIES[:[s.name for s in P.STRATEGIES].index(Y9_NAMES[0])]    # every strategy before Y9


@pytest.fixture(autouse=True)
def small_models(monkeypatch):
    monkeypatch.setitem(M.PARAMS, "n_estimators", 30)
    monkeypatch.setitem(SM.PARAMS, "n_estimators", 30)


# ---------------------------------------------------------------- a synthetic market

def full(table: str, row: dict) -> dict:
    return {f: row.get(f) for f in store.SCHEMAS[table].names}


def slot_of(t: int) -> int:
    return 5_000_000 + (t - T0) // 10


def market(n=12, every_ms=1_800_000, start=T0 + 600_000, seed=3) -> list[tuple[str, dict]]:
    """Migrations every `every_ms`: a dev buy in the creation (every other token), 12 early buyers in the first 10 s,
    20 more buyers over the last 10 minutes of the curve, the completion and the migration, then 160 pool trades 4 s
    apart from 1 s before to 2 s after the migration; every fifth pool is dumped 20 s in (down about 60 %), the rest
    drift down, sideways or up. (table, row) in time order."""
    rng = np.random.default_rng(seed)
    ev = []
    tx = 10
    for k in range(n):
        t = start + k * every_ms
        mint, dev = key(60 + k % 40) + "s" + str(k), key(200 + k % 7)
        vs, vt, rt, rs = 30 * SOL, 1_073_000_000 * 10 ** 6, C.INITIAL_RT, 0
        t0 = t - 900_000
        tx += 1
        ev.append(("creates", {"t": t0, "slot": slot_of(t0), "tx": tx, "sig": "s", "mint": mint, "creator": dev,
                               "vs": vs, "vt": vt, "rt": rt, "name": "N", "symbol": f"Y{k}",
                               "uri": "https://ipfs.io/ipfs/x"}))

        def buy(tt, sol, user, same=False):
            nonlocal vs, vt, rt, rs, tx
            tok = int(vt * sol / (vs + sol))
            vs, vt, rt, rs = vs + sol, vt - tok, rt - tok, rs + sol
            if not same:
                tx += 1
            ev.append(("trades", {"t": tt, "slot": slot_of(tt), "tx": tx, "mint": mint, "buy": True, "sol": sol,
                                  "tok": tok, "user": user, "vs": vs, "vt": vt, "rs": rs, "rt": rt, "fb": 95,
                                  "cfb": 30, "ix": "buy"}))
        if k % 2 == 0:
            buy(t0, SOL, dev, same=True)
        for i in range(12):
            buy(t0 + 500 + 700 * i, int(0.4 * SOL), BUYERS[(k + i) % 60])
        for i in range(20):
            buy(t - 600_000 + 29_000 * i, int(SOL * (2.0 + rng.random())), BUYERS[(3 * k + i + 20) % 60])
        tx += 1
        ev.append(("other", {"kind": "complete", "t": t, "slot": slot_of(t), "tx": tx, "mint": mint}))
        ev.append(("other", {"kind": "migrate", "t": t, "slot": slot_of(t), "tx": tx, "mint": mint, "pool": f"Q{k}",
                             "sol": 85 * SOL, "tok": BASE0}))
        pb, pq = BASE0, QUOTE0
        drift = [-0.1, 0.0, 0.05, 0.15][k % 4]
        first = (-1_000, 1_000, 2_000)[k % 3]
        for j in range(160):
            tt = t + first + j * 4_000
            tx += 1
            if k % 5 == 0 and j == 5:
                buy_, b = False, int(pb * 0.6)
                q = int(pq * b / (pb + b))
            else:
                buy_ = bool(rng.random() < 0.5 + drift)
                if buy_:
                    q = int(SOL * 0.5 * (1 + rng.random()))
                    b = int(pb * q / (pq + q))
                else:
                    b = int(pb * 0.006 * (1 + rng.random()))
                    q = int(pq * b / (pb + b))
            ev.append(("amm", {"t": tt, "slot": slot_of(tt), "tx": tx, "pool": f"Q{k}", "mint": mint, "buy": buy_,
                               "base": b, "quote": q, "user": BUYERS[int(rng.integers(0, 60))], "pb": pb, "pq": pq,
                               "lpb": 20, "pfb": 5, "cfb": 5}))
            pb, pq = (pb - b, pq + q) if buy_ else (pb + b, pq - q)
    order = {"creates": 0, "trades": 1, "other": 2, "amm": 3}
    return sorted(ev, key=lambda e: (e[1]["t"], order[e[0]]))


def feed(eng, ev, until=None) -> None:
    for table, row in ev:
        if until is not None and row["t"] > until:
            break
        sim.feed_row(eng, table, full(table, row))


def write(root, ev) -> None:
    w = store.Writer(root)
    for table, row in ev:
        w.add(table, row)
    w.flush(T0)


class Stub:
    """A booster that always says p."""

    def __init__(self, p):
        self.p = p

    def predict(self, X):
        return np.full(len(X), self.p)


def stub_models(p_rug=0.0, p_win=1.0, base=0.2, thr=0.5) -> dict:
    out = {f"sel_{k}": M.Fitted(Stub(p_rug if k.startswith("rug") else p_win), None, None, base,
                                SM.features_for(k)) for k in SM.LABELS}
    out["sel_policy"] = {k: {"0.3": thr} for k in ("win0", "win5")}
    return out


# ---------------------------------------------------------------- the registered strategies

def test_the_y9_strategies_are_what_the_prereg_says():
    names = [n for _, n in Y9.VARIANTS]
    all_names = [s.name for s in P.STRATEGIES]
    assert names[0] == "P_pool0" and names[1:] == Y9_NAMES and all_names[-25:-20] == Y9_NAMES   # Y10 to Y16, tol60, Y14
    base = P.BY_NAME["P_pool0"]
    for n in Y9_NAMES:
        s = P.BY_NAME[n]
        assert (s.family, s.entry, s.exits, s.stake_sol, s.tp, s.sl, s.hold_s) == (
            "E", "migration", base.exits, 0.1, 0.30, 0.20, 300)
        assert s.p == ({"delay_s": 5} if n == "P_pool5_top30" else {"delay_s": 0})
    assert P.BY_NAME["P_pool0_norug"].flt == {"select": {"rug0": ("max", 1.0)}}
    assert P.BY_NAME["P_pool0_top30"].flt == {"select": {"win0": ("top", 0.3)}}
    assert P.BY_NAME["P_pool0_norug_top30"].flt == {"select": {"rug0": ("max", 1.0), "win0": ("top", 0.3)}}
    assert P.BY_NAME["P_pool5_top30"].flt == {"select": {"win5": ("top", 0.3)}}
    assert P.BY_NAME["P_pool0_smart2"].flt == {"smart_min": 2}
    for s in OLD:                                               # nothing before Y9 has the select filter
        assert "select" not in s.flt


def test_the_trials_are_counted():
    assert S.SELECT_Y9_TRIALS == 10 == (len(Y9.VARIANTS) - 1) * len(Y9.LIMITS)
    assert S.N_TRIALS == 22 + 1 + 12 + 54 + 135 + 140 + 1 + 6 + 5 + 10 + 10 + 4 + 12 + 16 + 12 + 4


def test_books_latency_fees_and_limits():
    strats, costs = Y9.books()
    assert len(strats) == len(costs) == 12 and all(s.stake_sol == 0.1 for s, _ in strats)
    assert {sim.base_name(s) for s, _ in strats} == {"P_pool0"}
    assert Y9.LIMITS["L25"] == P.Limits(0.1, 4, 0.6, 0.25) and Y9.LIMITS["L100"] == P.Limits(0.1, 4, 0.6, 1.0)
    assert all(lim.capped() == lim for lim in Y9.LIMITS.values())
    b = Y9.scenarios()["B"]
    assert b.tx_lamports() == 1_005_000 and b.buy.points_ms == Y9.SENDER_BUY_MS
    assert len(Y9.SENDER_BUY_MS) == len(Y9.SENDER_SELL_MS) == 28
    assert Y9.SENDER_BUY_MS[-2:] == (1165.0, 14912.0) and Y9.SENDER_SELL_MS[-2:] == (3916.0, 1000.0)


# ---------------------------------------------------------------- the features

def test_the_snapshot_counts_the_windows_before_the_completion_and_the_trend():
    eng = sim.Engine([], costs=Fixed(), select=True)
    cv = Curve(eng, t=T0)
    other = Curve(eng, mint=key(5), t=T0)
    cv.buy(T0 + 1_000, SOL, BUYERS[0])                          # 16+ minutes before: in no window
    c = T0 + 1_000 + 1_000_000
    cv.buy(c - 800_000, 2 * SOL, BUYERS[1])                     # in the 15-minute window only
    cv.buy(c - 200_000, 3 * SOL, BUYERS[2])                     # 5 minutes
    cv.sell(c - 100_000, 10 ** 12, BUYERS[2])
    cv.buy(c - 30_000, SOL, BUYERS[3])                          # 1 minute
    cv.buy(c - 20_000, SOL, BUYERS[3])
    for i in range(4):
        other.buy(c - 50_000 + i, SOL // 10, BUYERS[10 + i])    # the market's trades
    eng.complete(c, MINT)
    cv.buy(c + 1, SOL, BUYERS[4])                               # after the completion: not counted
    f = eng.sel.features(eng.tokens[MINT], c + 5)
    assert (f["c_buys_60"], f["c_sells_60"], f["c_ubuyers_60"]) == (2, 0, 1)
    assert (f["c_buys_300"], f["c_sells_300"], f["c_ubuyers_300"]) == (3, 1, 2)
    assert (f["c_buys_900"], f["c_ubuyers_900"]) == (4, 3) and f["c_buy_sol_900"] == pytest.approx(7.0)
    assert f["trend_60"] == pytest.approx(2 / 6) and f["trend_300"] == pytest.approx(4 / 8)
    assert f["mkt_trades_300"] == 8 and f["mkt_complete_1h"] == 0 and f["c_unique_sellers"] == 1
    assert f["age_at_complete_s"] == pytest.approx((c - T0) / 1000) and f["secs_since_complete"] == pytest.approx(0.005)
    assert MINT not in eng.sel.flow                              # the trades are dropped at the completion


def test_no_look_ahead_the_snapshot_is_hidden_before_the_completion_and_pool_trades_after_t_do_not_count():
    eng = sim.Engine([], costs=Fixed(), select=True)
    pool = Pool(eng)                                            # completes and migrates at T0
    tok = eng.tokens[MINT]
    before = eng.sel.features(tok, T0 - 1)
    assert all(math.isnan(before[k]) for k in SF.MIG_FEATURES)
    pool.trade(T0 + 2_000, False, base=BASE0 // 20)
    pool.trade(T0 + 4_000, True, sol=SOL)
    f3 = eng.sel.pool_features(MINT, T0 + 3_000)
    assert f3["pool_n"] == 2 and f3["pool_sells"] == 1          # the opening buy at T0 and the sale at +2 s
    assert f3["pool_max_sell_share"] > SF.BIG_SELL and f3["pool_big_sells"] == 1
    f5 = eng.sel.pool_features(MINT, T0 + 5_000)
    assert f5["pool_n"] == 3 and f5["pool_buys"] == 2
    assert eng.sel.pool_features(MINT, T0 + 3_000) == f3         # asked again after more trades: the same


def test_no_look_ahead_every_label_row_equals_the_features_of_a_record_cut_at_its_decision():
    ev = market(n=6, every_ms=1_200_000)
    eng = sim.Engine([], costs=Fixed(), select=True)
    lab = eng.add_pipe(SF.LabelPipe(eng))
    feed(eng, ev)
    eng.finish(ev[-1][1]["t"] + 1)
    assert len(lab.rows) >= 8 and {r["entry"] for r in lab.rows} == {0, 5}
    for row in lab.rows:
        cut = sim.Engine([], costs=Fixed(), select=True)
        feed(cut, ev, until=row["t"])
        f = SF.decision_features(cut, cut.tokens[row["mint"]], row["t"])
        for k in SF.SEL5:
            a, b = row[k], f.get(k, math.nan)
            assert (math.isnan(a) and math.isnan(b)) or a == pytest.approx(b), (k, row["entry"], a, b)


# ---------------------------------------------------------------- the labels

def test_the_label_return_is_p_pool0s_and_the_label_book_changes_nothing_next_to_it():
    ev = market(n=10, every_ms=1_200_000)
    costs = Y9.scenarios()["B"]

    def run(with_lab: bool):
        eng = sim.Engine([], rule_costs={"P_pool0": costs}, select=with_lab)
        pipe = eng.add_pipe(XL.PeakPipe(eng, [P.BY_NAME["P_pool0"]], P.PaperExecutor(),
                                        limits=P.Limits(0.1, 5, 0.6, 1.0), name="P_pool0"))
        lab = eng.add_pipe(SF.LabelPipe(eng, costs)) if with_lab else None
        feed(eng, ev)
        eng.finish(ev[-1][1]["t"] + 1)
        return eng, pipe, lab
    e0, p0, _ = run(False)
    e1, p1, lab = run(True)
    assert p0.closed and p0.closed == p1.closed and p0.failed == p1.failed and dict(e0.counts) == dict(e1.counts)
    assert {k: v for k, v in e1.skipped.items() if "@y9lab" not in k[0]} == dict(e0.skipped)
    assert e1.closed == e0.closed and not lab.closed and all(r["rule"] == "P_pool0" for r in e1.closed)
    rows0 = {r["mint"]: r for r in lab.rows if r["entry"] == 0}
    for t in p1.closed:
        r = rows0[t["mint"]]
        assert r["ret"] == pytest.approx(t["ret"]) and r["win"] == float(t["pnl_sol"] > 0) and r["t"] == t["signal_ms"]
    assert len(rows0) == len(p1.closed) + len(p1.failed)


def test_the_rug_label_is_a_fall_to_half_within_60_s():
    def run(drop_at_ms):
        eng = sim.Engine([], costs=Fixed(), select=True)
        lab = eng.add_pipe(SF.LabelPipe(eng))
        pool = Pool(eng)
        pool.to(T0 + drop_at_ms, 0.45)
        pool.to(T0 + drop_at_ms + 10_000, 1.0)
        eng.advance(T0 + 400_000)
        return {r["entry"]: r for r in lab.rows}
    early, late = run(30_000), run(61_000)
    assert early[0]["rug"] == 1.0 and early[5]["rug"] == 1.0
    assert late[0]["rug"] == 0.0 and late[5]["rug"] == 1.0     # 61 s after the migration is 56 s after +5 s
    assert all(r["ret"] == r["ret"] and r["win"] in (0.0, 1.0) for r in early.values())


def test_a_failed_label_buy_is_its_fee_and_the_label_book_has_no_limit():
    eng = sim.Engine([], costs=Fixed(), select=True)
    lab = eng.add_pipe(SF.LabelPipe(eng))
    assert all(isinstance(r, SF.Unlimited) for r in lab.risk.values())
    assert lab.risk["P_pool0_e0@y9lab"].why_not(T0, 10 ** 15) is None
    pool = Pool(eng)
    pool.to(T0 + 500, 1.6)                                      # the price runs away before the landing: slippage
    eng.advance(T0 + 2_000)
    r0 = next(r for r in lab.rows if r["entry"] == 0)
    assert r0["ret"] == pytest.approx(-Fixed().tx_lamports() / (0.1 * C.LAMPORTS)) and r0["win"] == 0.0
    assert not eng.failed and not lab.failed and eng.next_pid == 0


# ---------------------------------------------------------------- the filter's wiring

def test_the_select_filter_enters_below_the_base_rate_and_in_the_top_and_skips_otherwise():
    def run(models, names, select=True):
        eng = sim.Engine([], costs=Fixed(), strategies=[P.BY_NAME[n] for n in names], models=models, select=select)
        pool = Pool(eng)
        pool.to(T0 + 6_000, 1.5)
        eng.advance(T0 + 400_000)
        return eng
    names = ["P_pool0_norug", "P_pool0_top30", "P_pool0_norug_top30", "P_pool5_top30"]
    ok = run(stub_models(p_rug=0.2, p_win=0.5), names)
    assert sorted(t["rule"] for t in ok.closed) == sorted(names)
    assert {t["rule"]: t["prob"] for t in ok.closed}["P_pool0_top30"] == 0.5
    bad = run(stub_models(p_rug=0.21, p_win=0.49), names)
    assert not bad.closed and all(bad.skipped[(n, "model")] == 1 for n in names)
    none = run({}, names)
    assert all(none.skipped[(n, "no model")] == 1 for n in names)
    no_thr = dict(stub_models())
    no_thr["sel_policy"] = {}
    e = run(no_thr, names)
    assert [t["rule"] for t in e.closed] == ["P_pool0_norug"] and e.skipped[("P_pool0_top30", "no model")] == 1
    off = run(stub_models(), names, select=False)               # an engine without the tracker (the live service's)
    assert not off.closed and all(off.skipped[(n, "no model")] == 1 for n in names)


def test_the_smart_wallet_rule_needs_two_smart_early_buyers():
    from lab.pumpfun_rt import wallets as W

    def run(n_smart):
        book = W.WalletBook()
        for w in BUYERS[20:20 + n_smart]:
            book.rows[w] = [5, 3, 0]
        eng = sim.Engine([], costs=Fixed(), strategies=[P.BY_NAME["P_pool0_smart2"]], wallets=book, select=True)
        cv = Curve(eng, t=T0 - 120_000)
        for i, w in enumerate(BUYERS[20:23]):
            cv.buy(T0 - 119_000 + i * 1000, SOL // 10, w)
        Pool(eng, t=T0)
        eng.advance(T0 + 400_000)
        return eng
    assert not run(1).closed and run(1).skipped[("P_pool0_smart2", "filter")] == 1
    assert [t["rule"] for t in run(2).closed] == ["P_pool0_smart2"]


# ---------------------------------------------------------------- the models

def table(n=600, seed=1, days=3) -> dict:
    """Rows for both entries over `days` days, the labels a noisy function of two features."""
    rng = np.random.default_rng(seed)
    t = np.sort(rng.integers(T0 + 86_400_000, T0 + (1 + days) * 86_400_000, n)).astype(float)
    tb = {c: np.full(n, np.nan) for c in SF.ROW_COLS}
    tb["t"], tb["entry"] = t, np.where(np.arange(n) % 2 == 0, 0.0, 5.0)
    x1, x2 = rng.normal(size=n), rng.normal(size=n)
    tb["c_net_sol_60"], tb["pool_net_share"] = x1, x2
    tb["win"] = (x1 + 0.5 * rng.normal(size=n) > 0.3).astype(float)
    tb["rug"] = (x1 + 0.5 * rng.normal(size=n) < -1.0).astype(float)
    tb["ret"] = np.where(tb["win"] == 1, 0.25, -0.3)
    return tb


def test_fit_threshold_purge_and_too_few_rows(monkeypatch):
    tb = table()
    rs = SM.rows_for(tb, "win0", until_ms=tb["t"][300])
    assert (rs["entry"] == 0).all() and (rs["t"] + SM.LABEL_H_MS < tb["t"][300]).all()
    assert np.all(np.diff(rs["t"]) >= 0)
    ms = SM.train(tb)
    assert all(ms[f"sel_{k}"].booster is not None for k in SM.Y9_LABELS)
    assert all(ms[f"sel_{k}"].booster is None for k in SM.TREND_LABELS)    # no trend column in these rows
    m = ms["sel_win0"]
    full_rows = SM.rows_for(tb, "win0")
    cut = int(len(full_rows["t"]) * 0.8)
    p = m.predict(M.matrix(full_rows, m.features))
    assert ms["sel_policy"]["win0"]["0.3"] == pytest.approx(np.quantile(p[cut:], 0.7))
    assert m.base == pytest.approx(full_rows["win"].mean()) and m.features == SF.SEL0
    assert ms["sel_win5"].features == SF.SEL5
    monkeypatch.setattr(SM, "MIN_TRAIN", 10_000)
    few = SM.train(tb)
    assert all(few[f"sel_{k}"].booster is None for k in SM.LABELS) and few["sel_policy"] == {}


def test_walk_forward_by_day_and_the_files_round_trip(tmp_path):
    tb = table(n=1200, days=4)
    wf = SM.walk_forward(tb)
    assert set(wf) == set(SM.Y9_LABELS)                         # no trend column in these rows
    for k in SM.Y9_LABELS:
        days = wf[k]["days"]
        assert days[0]["model"] is False                         # the first day has nothing before it
        tested = [d for d in days if d["model"]]
        assert tested and all(d["train"] < d2["train"] for d, d2 in zip(tested, tested[1:]))
        assert wf[k]["n"] == sum(d["test"] for d in tested)
    assert wf["win0"]["model"]["auc"] > 0.7 and wf["win0"]["logistic"]["auc"] > 0.7
    ms = SM.train(tb)
    SM.save(ms, tmp_path)
    back = SM.load_models(tmp_path)
    assert set(back) == {f"sel_{k}" for k in SM.LABELS} | {"sel_policy"}
    assert back["sel_policy"] == ms["sel_policy"]
    X = M.matrix(SM.rows_for(tb, "rug5"), SF.SEL5)
    assert np.allclose(back["sel_rug5"].predict(X), ms["sel_rug5"].predict(X))
    assert set(M.load(tmp_path)) >= {"sel_win0", "sel_policy"}
    SM.save_rows(tb, {"days": 4}, tmp_path / "r.parquet")
    t2, meta = SM.load_rows(tmp_path / "r.parquet")
    assert np.array_equal(t2["t"], tb["t"]) and meta == {"days": 4}


def test_the_day_models_follow_the_engines_clock():
    eng = sim.Engine([])
    dm = Y9.DayModels()
    dm.eng = eng
    assert not dm and dm.get("sel_win0") is None
    dm.by_day[SF.day_of(T0 + 86_400_000)] = {"sel_win0": "next"}
    eng.now = T0
    assert dm.get("sel_win0") is None and dm.get("x", 7) == 7
    eng.now = T0 + 86_400_000
    assert dm.get("sel_win0") == "next" and dm


# ---------------------------------------------------------------- the replay end to end

def test_the_replay_trains_day_by_day_and_reports(tmp_path, monkeypatch):
    write(tmp_path, market(n=60, every_ms=4_000_000))
    monkeypatch.setattr(store, "base", lambda: tmp_path)
    monkeypatch.setattr("lab.pumpfun_rt.study.WARM_DAYS", 0)
    monkeypatch.setattr(SM, "MIN_TRAIN", 12)
    res = Y9.run(root=tmp_path, until_ms=T0 + 4 * 86_400_000, log=lambda *a: None)
    assert set(res["entries"]) == {f"{n}@{k}" for _, n in Y9.VARIANTS for k in Y9.LIMITS}
    assert res["oos_day"] is not None and res["oos_day"] > res["days"][0] and not res["open_at_end"]
    first = res["trained"][res["oos_day"]]
    assert set(Y9.TRADED) <= set(first["models"])
    sk = {n: XLcount(res["skips"][n]) for n in res["skips"]}
    assert sk["P_pool0_top30@L100"].get("no model", 0) > 0     # before the first model
    assert sum(1 for x in res["entries"]["P_pool0_top30@L100"] if x["signal_ms"] >= res["split_ms"]) > 0
    ev = Y9.evaluate(res)
    assert set(ev["versus"]["L25"]) == {x for x, _ in Y9.VARIANTS[1:]} == set(ev["versus"]["L100"])
    wf = SM.walk_forward(res["table"])
    lat = {k: XL.RL.describe(c, n=500) for k, c in Y9.scenarios().items()}
    md = Y9.report_md(res, ev, wf, lat, {})
    assert "better than X0" in md and "\u2014" not in md and "S5" in md and "walk-forward" in md
    json.dumps({"eval": ev, "wf": wf}, default=str)


def XLcount(skips):
    from collections import Counter
    return Counter(w for _, w in skips)


# ---------------------------------------------------------------- the strategies before Y9

def test_every_strategy_before_y9_trades_exactly_as_before(tmp_path, monkeypatch):
    """One shared paper book of every strategy before Y9 on a synthetic record, without the tracker and the Y9
    strategies, and with them, the Y9 books trading (models that pass) and the label book next to it: the closed
    trades, failed buys and skips of the old strategies are the same field for field (the pid aside: the Y9
    strategies in the same book take pids too, which also orders two rules' sales landing in the same millisecond
    differently, so the records are compared sorted)."""
    write(tmp_path, market(n=24, every_ms=1_500_000))
    monkeypatch.setattr(store, "base", lambda: tmp_path)
    days = store.days(tmp_path)

    def run(new: bool):
        eng = sim.Engine(S.RULES, costs=Fixed(), strategies=P.STRATEGIES if new else OLD,
                         models=stub_models() if new else {}, select=new)
        if new:
            eng.add_pipe(SF.LabelPipe(eng))
        sim.replay(days, eng, tmp_path)
        return eng
    a, b = run(False), run(True)
    old = {s.name for s in OLD} | {r.name for r in S.RULES}

    def strip(xs):
        out = [{k: v for k, v in x.items() if k != "pid"} for x in xs if x["rule"] in old]
        return sorted(out, key=lambda x: (x["rule"], x["mint"], x["signal_ms"], x.get("exit_ms") or x.get("land_ms")))
    assert strip(a.closed) and strip(a.closed) == strip(b.closed) and strip(a.failed) == strip(b.failed)
    assert {k: v for k, v in a.skipped.items() if k[0] in old} == {k: v for k, v in b.skipped.items() if k[0] in old}
    assert {t["rule"] for t in b.closed} & set(Y9_NAMES)        # the Y9 books did trade next to them
    assert {t["rule"] for t in a.closed} >= {"P_pool0"}


def test_the_daily_retrain_trains_and_saves_the_select_models(tmp_path, monkeypatch):
    from lab import report as rep
    from lab.pumpfun_rt import retrain as RT
    tb = table(n=900, days=3)
    SM.save_rows(tb, {"days": ["a", "b", "c"]}, tmp_path / "select.parquet")
    monkeypatch.setattr(SM, "rows_path", lambda: tmp_path / "select.parquet")
    monkeypatch.setattr(M, "model_dir", lambda: tmp_path / "models")
    monkeypatch.setattr(rep, "REPORTS", tmp_path / "reports")
    dry = RT.run_y9(T0, dry=True, log=lambda *a: None)
    assert dry["models"] == {k: k in SM.Y9_LABELS for k in SM.LABELS} and not (tmp_path / "models").exists()
    summ = RT.run_y9(T0, log=lambda *a: None)
    assert set(SM.load_models(tmp_path / "models")) == {f"sel_{k}" for k in SM.LABELS} | {"sel_policy"}
    md = (tmp_path / "reports" / "pumpfun_rt" / "select.md").read_text(encoding="utf-8")
    assert "win0" in md and "\u2014" not in md and summ["rows"]["rug5"] == 450
    monkeypatch.setattr(SM, "rows_path", lambda: tmp_path / "none.parquet")
    assert RT.run_y9(T0, log=lambda *a: None) is None
