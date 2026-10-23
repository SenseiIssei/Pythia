"""Y13, the bombers: the registered constants, the labels on a synthetic record (p0, the peak through the pool, the
first time at a multiple, the multiple after 1 to 60 s), the decision's features (the dev's buy, whales, the
creation slot's buyers) with no look-ahead (later trades and later outcomes change nothing), the creator's and the
early buyers' history counted from the moment it happened, the walk-forward's purge, precision by block, and the
paper books end to end through the engine (a third at 3x, a third at 10x, the rest on the trail, the stop, a quiet
coin marked at the cutoff, only the picks bought, the code's caps). No existing book or strategy changes. No
network, no wallet.

Run from research/lab:  python -m pytest tests/test_pumpfun_bombers_y13.py
"""

from __future__ import annotations

import math

import numpy as np
import polars as pl
import pytest

from lab.pumpfun_rt import bombers13 as Y13
from lab.pumpfun_rt import curve as C
from lab.pumpfun_rt import pipeline as P
from lab.pumpfun_rt import store
from lab.pumpfun_rt import strategies as S
from test_pumpfun_rt import T0, Fixed, key

SOL = C.LAMPORTS
DEV, DEV2, X, W, Y = key(2), key(4), key(5), key(6), key(7)
POOL = key(3)
A, B, D, E, F = (key(40 + i) for i in range(5))      # A goes 200x, B goes quiet, D dumps, E and F come later


class Rec:
    """A synthetic record: curves by the curve arithmetic, a pool by given reserves, a row's slot by its time (400 ms
    slots, so chain time is the slot's first time) unless one is given."""

    def __init__(self, root):
        self.w = store.Writer(root)
        self.tx = 0
        self.cur: dict[str, list[int]] = {}
        self.held: dict[tuple, int] = {}

    @staticmethod
    def _slot(t, slot=None):
        return 1_000 + (t - T0) // 400 if slot is None else slot

    def create(self, t, mint, dev, symbol="SYM", name="Some Name"):
        self.tx += 1
        s = self._slot(t)
        self.cur[mint] = [30 * SOL, 1_073_000_000 * 10 ** 6, C.INITIAL_RT, 0]
        self.w.add("creates", {"t": t, "slot": s, "tx": self.tx, "sig": "s", "mint": mint, "creator": dev,
                               "user": dev, "vs": 30 * SOL, "vt": 1_073_000_000 * 10 ** 6, "rt": C.INITIAL_RT,
                               "supply": 10 ** 15, "name": name, "symbol": symbol, "uri": "https://ipfs.io/ipfs/x",
                               "mayhem": False})
        return s, self.tx

    def buy(self, t, mint, user, sol_, slot=None, tx=None):
        vs, vt, rt, rs = self.cur[mint]
        sol = int(sol_ * SOL)
        tok = int(vt * sol / (vs + sol))
        self.cur[mint] = [vs + sol, vt - tok, rt - tok, rs + sol]
        self.held[(mint, user)] = self.held.get((mint, user), 0) + tok
        self._trade(t, mint, user, True, sol, tok, slot, tx)

    def sell_all(self, t, mint, user, slot=None):
        tok = self.held.pop((mint, user))
        vs, vt, rt, rs = self.cur[mint]
        sol = int(vs * tok / (vt + tok))
        self.cur[mint] = [vs - sol, vt + tok, rt + tok, rs - sol]
        self._trade(t, mint, user, False, sol, tok, slot, None)

    def _trade(self, t, mint, user, buy, sol, tok, slot, tx):
        if tx is None:
            self.tx += 1
            tx = self.tx
        vs, vt, rt, rs = self.cur[mint]
        self.w.add("trades", {"t": t, "slot": self._slot(t, slot), "tx": tx, "mint": mint, "buy": buy, "sol": sol,
                              "tok": tok, "user": user, "vs": vs, "vt": vt, "rs": rs, "rt": rt, "fb": 95, "cfb": 30,
                              "ix": "buy" if buy else "sell"})

    def migrate(self, t, mint):
        for kind, dt in (("complete", 0), ("migrate", 1)):
            self.tx += 1
            self.w.add("other", {"kind": kind, "t": t + dt, "slot": self._slot(t + dt), "tx": self.tx, "mint": mint,
                                 "user": DEV, "pool": POOL, "sol": 85 * SOL, "tok": 206 * 10 ** 12})

    def pool(self, t, mint, sol_per_tok, pb=200 * 10 ** 12, buy=True):
        """A small pool trade whose reserves before it price the token at sol_per_tok."""
        pq = int(sol_per_tok * (pb / C.TOKEN_UNIT) * SOL)
        self.tx += 1
        self.w.add("amm", {"t": t, "slot": self._slot(t), "tx": self.tx, "pool": POOL, "mint": mint, "buy": buy,
                           "base": 10 ** 6, "quote": 1_000, "user": Y, "pb": pb, "pq": pq, "lpb": 20, "pfb": 5,
                           "cfb": 0})

    def gap(self, t0, t, program):
        self.w.add("other", {"kind": "gap", "t": t, "t0": t0, "user": program})


def p_after_dev(sol_=1.0):
    vs, vt = 30 * SOL, 1_073_000_000 * 10 ** 6
    s = int(sol_ * SOL)
    return C.price(vs + s, vt - int(vt * s / (vs + s)))


def record(root):
    r = Rec(root)
    # A: the dev's 1 SOL and X's 2 SOL in the creation slot, a 4 SOL whale at 2 s, more buyers, then the pool to 200x
    s0, tx0 = r.create(T0, A, DEV)
    r.buy(T0, A, DEV, 1.0, slot=s0, tx=tx0)
    r.buy(T0, A, X, 2.0, slot=s0)
    r.buy(T0 + 2_000, A, W, 4.0)
    for i in range(6):
        r.buy(T0 + 5_000 + i * 3_000, A, key(60 + i), 1.5)
    # B: goes quiet after 2 s
    s1, tx1 = r.create(T0 + 500, B, DEV2)
    r.buy(T0 + 500, B, DEV2, 0.5, slot=s1, tx=tx1)
    r.buy(T0 + 2_500, B, key(70), 0.3)
    # D: bought into, then everyone sells at 20 s
    s2, tx2 = r.create(T0 + 800, D, key(8))
    r.buy(T0 + 800, D, key(8), 2.0, slot=s2, tx=tx2)
    r.buy(T0 + 3_000, D, key(71), 12.0)
    r.buy(T0 + 15_000, D, key(72), 0.2)
    r.sell_all(T0 + 20_000, D, key(8))
    r.sell_all(T0 + 21_000, D, key(71))
    r.buy(T0 + 25_000, D, key(73), 0.01)
    p0 = p_after_dev()
    r.migrate(T0 + 60_000, A)
    for k, (dt, m) in enumerate(((70, 20), (120, 60), (200, 120), (300, 200), (330, 190), (400, 80), (500, 70))):
        r.pool(T0 + dt * 1000, A, m * p0)
    # E: the same creator as A after A's 100x, X buys it at 1 s; F: X too, but created before A migrated
    s3, tx3 = r.create(T0 + 30_000, F, key(9))
    r.buy(T0 + 30_000, F, key(9), 0.2, slot=s3, tx=tx3)
    r.buy(T0 + 31_000, F, X, 0.5)
    s4, tx4 = r.create(T0 + 600_000, E, DEV, symbol="sym")
    r.buy(T0 + 600_000, E, DEV, 0.2, slot=s4, tx=tx4)
    r.buy(T0 + 601_000, E, X, 0.5)
    r.buy(T0 + 700_000, E, key(74), 0.1)
    r.w.flush(T0)
    return p0


UNTIL = T0 + 2 * 3_600_000


@pytest.fixture
def rec(tmp_path):
    p0 = record(tmp_path)
    return Y13.load(tmp_path, UNTIL, log=lambda *a: None), p0, tmp_path


# ---------------------------------------------------------------- registered

def test_the_registered_constants_are_what_the_prereg_says():
    assert Y13.UNTIL_MS == Y13._ms(2026, 10, 23, 18, 0) and Y13.LABEL_H_MS == 6 * 3_600_000
    assert Y13.MULTS == (50, 100, 1000) and Y13.AT_S == (1, 3, 10, 30, 60) and Y13.DECISIONS == (3, 10)
    assert Y13.FOLDS[0] == Y13._ms(2026, 10, 21, 12) and len(Y13.FOLDS) == 5 and Y13.PURGE_MS == Y13.LABEL_H_MS
    assert Y13.LABEL == "b50" and Y13.TOPS == (0.001, 0.01) and Y13.BOOK_TOP == 0.01
    assert Y13.SIGNALS == {"G3": 3, "G10": 10, "W10": 10} and Y13.RANDOM_MOD == 20
    assert Y13.STAKE_SOL == 0.05 and Y13.LATENCIES == ("L1", "L3", "L10", "B")
    assert Y13.EXITS == P.Exits(86_400, 0.50, ((2.0, 1 / 3), (9.0, 2 / 3)), 0.0, 0.50, dev_sell=False, pull=False)
    assert Y13.LIMITS.capped() == Y13.LIMITS == P.Limits(0.05, 5, 0.6, 1.0)
    assert len(Y13.SIGNALS) * len(Y13.LATENCIES) == 12
    lat = Y13.latencies()
    assert lat["L1"].lat_median_ms == 1000 and lat["L3"].lat_median_ms == 3000 and lat["L10"].lat_median_ms == 10_000
    assert lat["L1"].tx_lamports() == lat["B"].tx_lamports() == 1_005_000 and lat["B"].lat_median_ms > 5_000
    assert len(Y13.FEATURES) == len(set(Y13.FEATURES))


def test_no_existing_book_or_strategy_changes():
    assert not any("Y13" in s.name for s in P.STRATEGIES) and not any("Y13" in r.name for r in S.RULES)
    assert "Y13" not in "".join(P.BY_NAME)


# ---------------------------------------------------------------- part 1

def test_labels_follow_the_curve_and_the_pool_from_the_first_trade(rec):
    r, p0, _ = rec
    lab = {x["mint"]: x for x in Y13.labels(r, until_ms=UNTIL).with_columns(pl.col("mint").cast(pl.Utf8)).to_dicts()}
    a = lab[A]
    assert a["peak6"] == pytest.approx(200, rel=1e-6) and a["b50"] and a["b100"] and not a["b1000"]
    assert a["t_50"] == pytest.approx(120) and a["t_100"] == pytest.approx(200) and a["t_1000"] is None
    after_x = C.price(*curve_after(1.0, 2.0)) / p0
    assert a["m_1s"] == pytest.approx(after_x) and a["m_1s"] > 1
    assert a["migrated"] and a["pool_seen"] and not a["known6"]          # 2 h of record: its 6 h not in it
    b = lab[B]
    assert not b["b50"] and b["m_60s"] == b["m_3s"] and not b["migrated"]
    d1 = Y13.describe(Y13.labels(r, until_ms=T0 + 7 * 3_600_000))
    assert d1["x100"]["n"] == 1 and d1["x1000"]["n"] == 0 and d1["x100"]["t_median_s"] == pytest.approx(200)
    assert d1["x100"]["at"][10]["left_median"] == pytest.approx(200 / lab[A]["m_10s"])


def curve_after(*sols):
    vs, vt = 30 * SOL, 1_073_000_000 * 10 ** 6
    for s_ in sols:
        s = int(s_ * SOL)
        tok = int(vt * s / (vs + s))
        vs, vt = vs + s, vt - tok
    return vs, vt


def test_a_curve_gap_in_the_first_minute_marks_the_token(tmp_path):
    from lab.pumpfun_rt.events import PUMP
    record(tmp_path)
    w = store.Writer(tmp_path)
    w.add("other", {"kind": "gap", "t": T0 + 30_000, "t0": T0 + 20_000, "user": PUMP})
    w.flush(T0)
    r = Y13.load(tmp_path, UNTIL, log=lambda *a: None)
    lab = Y13.labels(r, until_ms=UNTIL)
    gap = dict(zip(lab["mint"].cast(str).to_list(), lab["gap60"].to_list()))
    assert gap[A] and gap[B] and not gap[E]
    assert Y13.overlaps([(10, 20), (30, 40)], np.array([0, 20, 21, 35, 41]), np.array([9, 25, 29, 50, 50])).tolist() \
        == [False, False, False, True, False]
    assert Y13._merge([(5, 8), (1, 3), (2, 4), (None, 1)]) == [(1, 4), (5, 8)]


# ---------------------------------------------------------------- part 2

def rows(r, d, until=UNTIL):
    lab = Y13.labels(r, until_ms=until)
    tabs = Y13.table(r, lab, log=lambda *a: None)
    t = tabs[d]
    return {m: {c: t[c][i] for c in t} for i, m in enumerate(t["mint"])}


def test_the_decision_sees_the_dev_the_whales_and_the_creation_slot(rec):
    r, _, _ = rec
    a3 = rows(r, 3)[A]
    assert a3["dev_sol"] == pytest.approx(1.0) and a3["max_buy_sol"] == pytest.approx(4.0)
    assert (a3["whale1_n"], a3["whale3_n"], a3["whale10_n"]) == (2, 1, 0)
    assert a3["slot0_buyers"] == 1 and a3["slot0_sol"] == pytest.approx(2.0) and a3["n_buyers"] == 2
    assert a3["dev_share"] > 0 and a3["dev_sold"] == 0 and a3["eb_n"] == 2
    a10 = rows(r, 10)[A]
    assert a10["n_buyers"] == 4 and a10["buy_sol"] == pytest.approx(9.0) and a10["mult"] > a3["mult"]
    d10 = rows(r, 10)[D]
    assert d10["dev_sold"] == 0 and d10["n_buys"] == 1


def test_later_trades_and_later_outcomes_change_no_feature(rec):
    r, _, root = rec
    full = rows(r, 10)
    cut = Y13.load(root, T0 + 610_000, log=lambda *a: None)
    part = rows(cut, 10, T0 + 610_000)
    for m in (A, B, D, F, E):
        for c in Y13.FEATURES:
            a, b = full[m][c], part[m][c]
            assert (a == b) or (math.isnan(a) and math.isnan(b)), (m, c)


def test_the_creator_and_the_early_buyers_count_from_the_moment_it_happened(rec):
    r, _, _ = rec
    got = rows(r, 3)
    e, f = got[E], got[F]
    assert e["cr_prev_n"] == 1 and e["cr_prev_mig"] == 1 and e["cr_prev_b50"] == 1    # A: 50x at 120 s, E at 600 s
    assert e["eb_n"] == 1 and e["eb_b50"] == 1 and e["eb_mig"] == 1 and e["eb_bot_mean"] == 2   # X: A and F before
    assert f["eb_b50"] == 0 and f["eb_mig"] == 0 and f["eb_bot_mean"] == 1             # F at 33 s: A not yet
    assert got[A]["cr_prev_n"] == 0 and got[A]["eb_b50"] == 0
    assert e["sym_copies_1h"] == 4 and e["name_len"] == 9 and e["uri_ipfs"] == 1 and e["sym_upper"] == 0
    assert not math.isnan(e["mkt_buy_sol_15m"]) and e["mkt_buy_sol_15m"] > 0


def test_the_walk_forward_purges_and_scores_only_test_blocks(monkeypatch):
    rng = np.random.default_rng(1)
    n = 6_000
    t0 = np.sort(rng.integers(0, 10 * 3_600_000, n)) + T0
    tab = {c: rng.normal(size=n) for c in Y13.FEATURES}
    y = (tab["max_buy_sol"] + rng.normal(scale=0.5, size=n)) > 2.3
    tab.update(t0=t0, known6=np.ones(n, bool), b50=y, b100=y, b1000=np.zeros(n, bool),
               mint=np.array([str(i) for i in range(n)]))
    monkeypatch.setattr(Y13, "FOLDS", (T0 + 4 * 3_600_000, T0 + 7 * 3_600_000))
    monkeypatch.setattr(Y13, "PURGE_MS", 3_600_000)
    until = T0 + 11 * 3_600_000
    f = Y13.folds(t0, until)
    assert f == [(T0 + 3 * 3_600_000, T0 + 4 * 3_600_000, T0 + 7 * 3_600_000),
                 (T0 + 6 * 3_600_000, T0 + 7 * 3_600_000, T0 + 10 * 3_600_000)]
    wf = Y13.walk_forward(tab, until_ms=until, log=lambda *a: None)
    test = (t0 >= T0 + 4 * 3_600_000) & (t0 < T0 + 10 * 3_600_000)
    assert np.isfinite(wf["gbm"][test]).all() and np.isnan(wf["gbm"][~test]).all()
    assert wf["folds"][0]["train_rows"] == int((t0 < T0 + 3 * 3_600_000).sum())
    assert Y13._auc(wf["gbm"][test], y[test].astype(int)) > 0.8
    pick = wf["gbm"] >= wf["thr"]
    assert 0 < pick[test].sum() and pick[test].mean() < 0.05 and np.isnan(wf["thr"][~test]).all()
    h, k = Y13.precision_at(wf["gbm"], y.astype(int), wf["fold"], 0.01)
    assert k == sum(math.ceil(0.01 * (wf["fold"] == i).sum()) for i in (0, 1)) and h / k > y.mean()


def test_precision_takes_the_top_of_each_block():
    s = np.array([0.9, 0.1, 0.2, 0.8, 0.7, 0.3])
    y = np.array([1, 0, 0, 0, 1, 0])
    fold = np.array([0, 0, 0, 1, 1, -1])
    assert Y13.precision_at(s, y, fold, 0.01) == (1, 2)
    assert Y13.precision_at(s, y, fold, 0.5) == (1, 3)                    # 2 of fold 0, 1 of fold 1


# ---------------------------------------------------------------- part 3

@pytest.fixture
def fixed(monkeypatch):
    monkeypatch.setattr(Y13, "latencies", lambda: {a: Fixed(priority_sol=0.001) for a in Y13.LATENCIES})


def test_the_books_buy_the_picks_take_a_third_at_3x_and_10x_trail_stop_and_mark(rec, fixed):
    r, _, root = rec
    pk = {"G10": {A: 10, B: 10, D: 10}, "W10": {A: 10}}
    rep = Y13.replay(pk, root, UNTIL, log=lambda *a: None)
    u = {e["mint"]: e for e in rep["books"]["U:Y13_G10@L1"]}
    assert set(u) == {A, B, D}
    a = u[A]
    assert a["legs"] == 3 and a["exit_why"] == "trail" and a["ret"] > 5 and not a["open"]
    assert u[D]["exit_why"] == "stop" and -1 < u[D]["ret"] < -0.5
    b = u[B]
    assert b["open"] and b["exit_why"] == "open at the cutoff" and -0.2 < b["ret"] < 0
    assert {e["mint"] for e in rep["books"]["U:Y13_W10@L1"]} == {A}
    c = {e["mint"]: e for e in rep["books"]["C:Y13_G10@L1"]}
    assert c[A]["ret"] == pytest.approx(a["ret"]) and c[B]["ret"] == pytest.approx(b["ret"])
    assert all(e["signal_ms"] in (T0 + 10_000, T0 + 10_500, T0 + 10_800) for e in u.values())
    st = Y13.book_stats(list(u.values()), {A: 200.0}, 1.0)
    assert st["n"] == 3 and st["open"] == 1 and st["bombers"] == 1
    assert st["losers_per_bomber"] == pytest.approx(a["pnl_sol"] / -np.mean([u[B]["pnl_sol"], u[D]["pnl_sol"]]))
    assert not st["pays"] and math.isnan(st["band"][0])                   # one hour: no band


def test_the_capped_book_holds_what_its_caps_allow(rec, fixed, monkeypatch):
    r, _, root = rec
    monkeypatch.setattr(Y13, "LIMITS", P.Limits(0.05, 1, 0.6, 1.0))
    monkeypatch.setattr(Y13, "GROUP", 1)
    rep = Y13.replay({"G10": {A: 10, B: 10, D: 10}}, root, UNTIL, log=lambda *a: None)
    assert len(rep["books"]["U:Y13_G10@L1"]) == 3                      # a group per pick: each its own book
    assert len(rep["books"]["C:Y13_G10@L1"]) == 1
    assert any("max open positions" in k for k in rep["skips"])


def test_picks_and_the_headline():
    tab = {"t0": np.array([Y13.FOLDS[0] - 1, Y13.FOLDS[0], Y13.FOLDS[0] + 1, Y13.UNTIL_MS - 1]),
           "mint": np.array(["a", "b", "c", "d"]), "max_buy_sol": np.array([5.0, 5.0, 1.0, 5.0])}
    wf = {"fold": np.array([-1, 0, 0, 4]), "gbm": np.array([0.9, 0.9, 0.1, 0.9]), "thr": np.array([0.5] * 4)}
    pk = Y13.picks({3: tab, 10: tab}, {3: wf, 10: wf})
    assert pk["G10"] == {"b": 10} and pk["G3"] == {"b": 3} and pk["W10"] == {"b": 10}
    sig = {d: {"x100": {"book_pick": {"prec": p}, "flags": {"whale3": {"prec": w}}}}
           for d, p, w in ((3, 0.02, 0.01), (10, 0.02, 0.01))}
    assert Y13.headline(sig) == "G10"
    sig[3]["x100"]["book_pick"]["prec"] = 0.05
    assert Y13.headline(sig) == "G3"


def test_separates_and_the_speed_follow_the_registered_rules():
    m = {"auc": 0.8, "top0.01": {"hits": 3, "lift": 12.0}}
    assert Y13.separates(m)
    assert not Y13.separates({**m, "auc": 0.7}) and not Y13.separates({**m, "top0.01": {"hits": 2, "lift": 50.0}})
    assert not Y13.separates({**m, "top0.01": {"hits": 5, "lift": 9.0}})
    bk = {f"U:Y13_G10@{a}": {"pays": a in ("L1", "L3")} for a in Y13.LATENCIES}
    assert Y13.speed(bk, "G10") == "L3" and Y13.speed(bk, "G3") is None
    bk["U:Y13_G10@B"]["pays"] = True
    assert Y13.speed(bk, "G10") == "B"
