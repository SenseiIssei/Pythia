"""G1: the factory's expression trees: grammar, canonical form, look-ahead safety, honest counting, budget share,
the report, and the same trees in the small-account mode.

No network, no lab data. Run from research/lab:  python -m pytest tests/test_factory_trees.py
"""

from __future__ import annotations

import dataclasses
import random
from collections import OrderedDict
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from lab import history
from lab.experiments import fam_common as fc
from lab.factory import build, evaluate, grammar, ledger, run, search, small
from test_factory import home, synthetic_panel  # noqa: F401  (fixture)
from test_factory_small import EURUSD, make_venue, synthetic

SEED_LEDGER = Path(__file__).resolve().parents[1] / "results" / "factory_seed" / "ledger.jsonl"


@pytest.fixture(scope="module")
def ctx():
    return build.make_ctx(synthetic_panel())


def leaf(op):
    return {"op": op}


def w(op, n, x):
    return {"op": op, "n": n, "args": [x]}


# ---------------------------------------------------------------- grammar

def test_random_trees_are_valid_bounded_and_canonical():
    rng = random.Random(1)
    for market in (False, True):
        for _ in range(400):
            t = grammar.random_tree(rng, market=market)
            assert grammar.valid_tree(t, market)[0]
            assert grammar.depth(t) <= grammar.MAX_DEPTH and grammar.nodes(t) <= grammar.MAX_NODES
            assert grammar.canonical_tree(t) == t
            if market:
                assert grammar.leaves_of(t) == {"btc"} and '"rank"' not in grammar.tree_text(t)


def test_equal_trees_are_one_trial():
    a, b = w("ret", 20, leaf("close")), w("z", 50, leaf("volume"))
    m1 = grammar.canonical_tree({"op": "min", "args": [a, b]})
    m2 = grammar.canonical_tree({"op": "min", "args": [b, a]})
    assert m1 == m2
    assert grammar.canonical_tree({"op": "rank", "args": [{"op": "rank", "args": [a]}]}) == {"op": "rank", "args": [a]}
    assert grammar.canonical_tree({"op": "clip", "c": 3.0, "args": [{"op": "clip", "c": 0.5, "args": [a]}]}) \
        == {"op": "clip", "c": 0.5, "args": [a]}
    g = {"universe": {"kind": "top", "n": 20}, "signal": {"kind": "expr", "tree": {"op": "min", "args": [a, b]}},
         "filters": [], "select": {"k": 10, "rank": "signal"}, "weight": {"scheme": "equal", "fill": "slots"},
         "rebalance": {"every": 1, "tranches": 1, "band": 0.0}}
    g2 = dict(g, signal={"kind": "expr", "tree": {"op": "min", "args": [b, a]}})
    assert grammar.key(g) == grammar.key(g2)
    assert grammar.valid(grammar.canonical(g))[0]
    # As a condition above 0, z_n(x) is x above its n-day average: the same gate as ma_n(x).
    gz = dict(g, filters=[{"kind": "xgate", "tree": w("z", 100, leaf("btc")), "cut": 0.0}])
    gm = dict(g, filters=[{"kind": "xgate", "tree": w("ma", 100, leaf("btc")), "cut": 0.0}])
    assert grammar.key(gz) == grammar.key(gm)
    assert grammar.key(dict(gz, filters=[dict(gz["filters"][0], cut=0.5)])) != grammar.key(gm)


def test_trees_outside_the_grammar_are_refused():
    bad = [leaf("close"),                                            # a bare series
           {"op": "rank", "args": [leaf("close")]},                  # a level without ret, ma or z
           w("ret", 21, leaf("close")),                              # a window not on the list
           w("ret", 20, w("ret", 5, leaf("close"))),                 # ret only on a series
           {"op": "diff", "args": [w("ret", 5, leaf("close"))] * 2},  # a tree minus itself
           w("ma", 100, leaf("btc")),                                # a coin score from BTC alone
           {"op": "sign", "args": [{"op": "rank", "args": [w("ret", 5, leaf("close"))]}]},
           {"op": "rank", "args": [{"op": "rank", "args": [{"op": "rank", "args": [
               {"op": "z", "n": 5, "args": [w("ret", 5, leaf("close"))]}]}]}]}]   # not canonical (and too deep)
    for t in bad:
        assert not grammar.valid_tree(t)[0], t
    assert not grammar.valid_tree({"op": "rank", "args": [w("ma", 100, leaf("btc"))]}, market=True)[0]
    assert not grammar.valid_tree(w("ret", 20, leaf("close")), market=True)[0]
    assert grammar.valid_tree(w("ma", 100, leaf("btc")), market=True)[0]
    deep = {"op": "rank", "args": [{"op": "diff", "args": [{"op": "z", "n": 5, "args": [w("ret", 5, leaf("close"))]},
                                                             w("ret", 20, leaf("close"))]}]}
    assert grammar.depth(deep) == 4 and not grammar.valid_tree(deep)[0]


def test_complexity_counts_nodes_and_old_genomes_are_unchanged():
    g = {"universe": {"kind": "top", "n": 20}, "signal": {"kind": "mom", "lb": 28}, "filters": [],
         "select": {"k": 10, "rank": "signal"}, "weight": {"scheme": "equal", "fill": "slots"},
         "rebalance": {"every": 1, "tranches": 1, "band": 0.0}}
    assert grammar.complexity(g) == 1 and not grammar.has_tree(g)
    t = {"op": "rank", "args": [w("ret", 20, leaf("close"))]}
    gt = dict(g, signal={"kind": "expr", "tree": t},
              filters=[{"kind": "xgate", "tree": w("ma", 100, leaf("btc")), "cut": 0.0}])
    assert grammar.complexity(gt) == 3 + 2 and grammar.tree_nodes(gt) == 5
    assert grammar.expression(gt) == "rank(ret_20) where btc > ma_100"
    assert "rank(ret_20)" in grammar.describe(gt) and "where btc > ma_100" in grammar.describe(gt)
    # The ledger's old rows: the same keys, still valid genomes.
    rows = ledger.read_jsonl(SEED_LEDGER)
    assert rows
    for r in rows[:300]:
        assert grammar.key(r["genome"]) == r["key"] and grammar.valid(r["genome"])[0]
        assert grammar.complexity(r["genome"]) == r["complexity"]


def test_mutation_and_crossover_of_trees():
    rng = random.Random(2)
    a, b = grammar.random_tree_genome(rng), grammar.random_tree_genome(rng)
    for _ in range(300):
        m = grammar.mutate(a, rng, trees=True)
        assert grammar.valid(m)[0] and grammar.has_tree(m) and grammar.key(m) != grammar.key(a)
        x = grammar.crossover(a, b, rng)
        assert grammar.valid(x)[0]
        f = grammar.mutate(grammar.random_genome(rng), rng)
        assert not grammar.has_tree(f)                  # a family slot never gets a tree
        a = m
    t = grammar.random_tree(rng)
    for _ in range(200):
        t2 = grammar.mutate_tree(t, rng)
        assert grammar.valid_tree(t2)[0] and t2 != t
        assert grammar.valid_tree(grammar.crossover_tree(t, t2, rng))[0]
        t = t2


# ---------------------------------------------------------------- the evaluator and look-ahead

def test_operators_on_a_small_example():
    x = np.array([[1.0, 2.0, 4.0], [2.0, 2.0, 2.0], [4.0, 1.0, 3.0], [8.0, 4.0, 3.0]])
    series = {"close": x, "btc": x[:, :1]}
    r = build.tree_values(w("ret", 1, leaf("close")), series.get)
    assert np.isnan(r[0]).all() and np.allclose(r[3], [1.0, 3.0, 0.0])
    m = build.tree_values(w("ma", 2, leaf("close")), series.get)
    assert np.allclose(m[1], [2 / 1.5 - 1, 0.0, 2 / 3 - 1])
    mask = np.array([[True, True, True]] * 3 + [[True, False, True]])
    k = build.tree_values({"op": "rank", "args": [w("ret", 1, leaf("close"))]}, series.get, mask)
    assert np.allclose(k[3, [0, 2]], [1.0, 0.5]) and np.isnan(k[3, 1])
    z = build.tree_values({"op": "z", "n": 3, "args": [w("ret", 1, leaf("close"))]}, series.get)
    assert np.isnan(z[:3]).all() and np.isnan(z[3, 0]) and z[3, 2] == pytest.approx(0.0)   # col 0: returns 1, 1, 1
    assert z[3, 1] == pytest.approx((3.0 - np.mean([0, -0.5, 3])) / np.std([0, -0.5, 3]))


def _scrambled(c: build.Ctx, t: int, seed: int) -> build.Ctx:
    """The same context with every bar after t replaced by noise (prices, volume, range, candles, vol, BTC,
    universes)."""
    rng = np.random.default_rng(seed)
    def after(a, fn):
        a = a.copy()
        a[t + 1:] = fn(a[t + 1:].shape)
        return a
    pos = lambda s: np.exp(rng.normal(3, 2, s))      # noqa: E731
    return dataclasses.replace(
        c, px=after(c.px, pos), qv=after(c.qv, pos), hl=after(c.hl, lambda s: rng.uniform(0, 0.3, s)),
        hlc=tuple(after(x, pos) for x in c.hlc),
        sigma=after(c.sigma, lambda s: rng.uniform(0.001, 0.2, s)), btc_px=after(c.btc_px, pos),
        alive=after(c.alive, lambda s: rng.random(s) < 0.7),
        uni={k: after(v, lambda s: rng.random(s) < 0.5) for k, v in c.uni.items()}, memo={})


def test_no_score_at_or_before_t_moves_when_every_later_bar_changes(ctx):
    rng = random.Random(7)
    for i, t_cut in enumerate((400, 900, 1300)):
        b = _scrambled(ctx, t_cut, i)
        a = dataclasses.replace(ctx, memo={})
        mask = ctx.uni["top20"]
        for _ in range(120):
            market = rng.random() < 0.3
            tr = grammar.random_tree(rng, market=market)
            x = build.tree_score(a, tr, None if market else mask, "top20", market)
            y = build.tree_score(b, tr, None if market else b.uni["top20"], "top20", market)
            assert np.array_equal(x[: t_cut + 1], y[: t_cut + 1], equal_nan=True), grammar.show_tree(tr)


def test_tree_genomes_never_look_ahead(ctx):
    rng = random.Random(8)
    t_cut = 1000
    b = _scrambled(ctx, t_cut, 3)
    a = dataclasses.replace(ctx, memo={})
    for _ in range(60):
        g = grammar.random_tree_genome(rng)
        assert np.allclose(build.weights(a, g)[: t_cut + 1], build.weights(b, g)[: t_cut + 1]), grammar.describe(g)
    p1, p2 = build.make_ctx(synthetic_panel()), build.make_ctx(synthetic_panel(bump=(t_cut + 1, 3.0)))
    for _ in range(20):
        g = grammar.random_tree_genome(rng)
        assert np.allclose(build.weights(p1, g)[: t_cut + 1], build.weights(p2, g)[: t_cut + 1])


def test_tree_weights_are_long_only_and_capped(ctx):
    rng = random.Random(9)
    for _ in range(40):
        g = grammar.random_tree_genome(rng)
        W = build.weights(ctx, g)
        assert np.isfinite(W).all() and (W >= 0).all() and (W.sum(1) <= 1 + 1e-9).all()
        assert ((W > 0).sum(1) <= g["select"]["k"]).all()


def test_the_tree_cache_is_bounded(ctx):
    c = dataclasses.replace(ctx, memo={})
    rng = random.Random(10)
    for _ in range(60):
        build.tree_score(c, grammar.random_tree(rng), c.uni["top20"], "top20")
    assert len(c.memo["_trees"]) <= build.TREE_CACHE


# ---------------------------------------------------------------- C2: candle shapes as leaves

def test_candle_shapes_from_high_low_close():
    close = np.array([[10.0], [12.0], [11.0], [11.0], [np.nan], [12.0], [13.0], [14.0], [15.0], [16.0], [17.0],
                      [18.0], [19.0]])
    high, low = close + 1, close - 2
    body, up, lo = (build.candle(high, low, close, n) for n in ("body", "upper", "lower"))
    assert np.isnan(body[0, 0])                                                     # no close before: no open
    assert body[1, 0] == pytest.approx(2 / 3) and up[1, 0] == pytest.approx(1 / 3) and lo[1, 0] == 0.0
    assert body[2, 0] == pytest.approx(-1 / 3) and up[2, 0] == 0.0 and lo[2, 0] == pytest.approx(2 / 3)
    assert np.isnan(body[4, 0]) and np.isnan(body[5, 0])                             # no bar, no open
    ok = np.isfinite(body[:, 0])
    assert np.allclose((np.abs(body) + up + lo)[ok, 0], 1.0)
    bw, rw = build.candle(high, low, close, "body_w"), build.candle(high, low, close, "range_w")
    assert np.isnan(bw[:12, 0]).all()                                               # the missing bar in each week
    assert bw[12, 0] == pytest.approx((19 - 12) / (20 - 11)) and rw[12, 0] == pytest.approx((20 - 11) / 19)
    one = np.ones((5, 1))
    assert np.isnan(build.candle(one, one, one, "body")).all()                      # no range, no shape


def test_candle_leaves_are_in_the_grammar_and_never_look_ahead(ctx):
    assert set(grammar.CANDLE_LEAVES) <= set(grammar.LEAVES) and set(grammar.CANDLE_LEAVES) <= set(small.LEAVES)
    for n in grammar.CANDLE_LEAVES:
        assert not grammar.is_level(n) and not grammar.is_market(n)
        t = {"op": "rank", "args": [w("ma", 5, leaf(n))]}
        assert grammar.valid_tree(t)[0] and grammar.show_tree(t) == f"rank(ma_5({n}))"
        x = build.leaf(dataclasses.replace(ctx, memo={}), n)
        assert x.shape == ctx.px.shape and np.isfinite(x[300:][ctx.alive[300:]]).mean() > 0.95
        assert np.isnan(x[~ctx.alive]).all()
    rng = random.Random(21)
    drawn = set()
    for _ in range(200):
        drawn |= grammar.leaves_of(grammar.random_tree(rng))
    assert set(grammar.CANDLE_LEAVES) <= drawn
    t_cut = 800
    b, a = _scrambled(ctx, t_cut, 5), dataclasses.replace(ctx, memo={})
    for n in grammar.CANDLE_LEAVES:
        t = {"op": "rank", "args": [w("z", 20, leaf(n))]}
        x = build.tree_score(a, t, a.uni["top20"], "top20")
        y = build.tree_score(b, t, b.uni["top20"], "top20")
        assert np.array_equal(x[: t_cut + 1], y[: t_cut + 1], equal_nan=True), n
        assert not np.array_equal(x[t_cut + 8:], y[t_cut + 8:], equal_nan=True), n


def test_small_candle_trees_score_the_coins_only(sctx):
    g = dict(small.hold_genome("SPY"), signal={"kind": "expr", "tree": {"op": "rank", "args": [w("ma", 5, leaf("body_w"))]}})
    g = small.canonical(g)
    assert small.valid(g)[0]
    s = small.tree_score(dataclasses.replace(sctx, memo={}), g["signal"]["tree"], np.ones(len(small.ASSETS), bool))
    coins = [small.ASSETS.index(a) for a in small.CRYPTO]
    etfs = [j for j in range(len(small.ASSETS)) if j not in coins]
    assert np.isnan(s[:, etfs]).all() and np.isfinite(s[1000:, coins]).all()
    none = small.make_ctx(*synthetic(), EURUSD, {})
    assert np.isnan(small.tree_score(none, g["signal"]["tree"], np.ones(len(small.ASSETS), bool))).all()
    days = synthetic()[0]
    fr = pl.DataFrame({"day": days[:5], "symbol": ["BTCUSDT"] * 5, "high": [2.0] * 5, "low": [1.0] * 5,
                       "close": [1.5] * 5})
    hb = small.crypto_bars(days, fr)
    assert hb["BTC"][0][:5].tolist() == [2.0] * 5 and np.isnan(hb["BTC"][0][5:]).all() and np.isnan(hb["ETH"][2]).all()


# ---------------------------------------------------------------- counting, penalty, budget

def test_a_tree_node_costs_more_than_a_part(ctx):
    rng = random.Random(11)
    g = grammar.random_tree_genome(rng)
    r = evaluate.in_sample(ctx, g, "x")
    base = min(r["is_sharpe"], r["is_twin"]) if r["is_twin"] is not None else r["is_sharpe"]
    pen = evaluate.COMPLEXITY_COST * r["complexity"] + evaluate.TREE_NODE_COST * r["tree_nodes"]
    assert r["fitness"] == pytest.approx(base - pen - (1.0 if r["is_exposure"] < evaluate.MIN_EXPOSURE else 0.0))
    assert r["tree_nodes"] == grammar.tree_nodes(g) > 0 and r["expression"] == grammar.expression(g)


def test_share_of_the_budget_goes_to_trees(ctx, monkeypatch):
    res = search.search(ctx, set(), [], "t1", budget=30, seed=1, log=lambda *_: None, share=0.3)
    assert res["trees"] == 9 == sum(grammar.has_tree(r["genome"]) for r in res["rows"])
    assert len({r["key"] for r in res["rows"]}) == 30
    bred = search.search(ctx, {r["key"] for r in res["rows"]}, search.elite_of(res["rows"]), "t2", budget=20,
                         seed=2, log=lambda *_: None, share=0.3)
    assert bred["trees"] == 6 and bred["origin"]["mutation"] + bred["origin"]["crossover"] > 0
    none = search.search(ctx, set(), [], "t3", budget=10, seed=3, log=lambda *_: None, share=0.0)
    assert none["trees"] == 0
    monkeypatch.setenv("PYTHIA_FACTORY_TREE_SHARE", "0.5")
    assert search.tree_share() == 0.5
    monkeypatch.setenv("PYTHIA_FACTORY_TREE_SHARE", "nonsense")
    assert search.tree_share() == search.TREE_SHARE
    monkeypatch.setenv("PYTHIA_FACTORY_TREE_SHARE", "7")
    assert search.tree_share() == 1.0


def test_every_tree_is_a_trial_and_the_report_shows_it(home, monkeypatch):  # noqa: F811
    P = synthetic_panel()
    monkeypatch.setattr(history, "load_long_panel", lambda fetch=False, fresh=False: P)
    d = run.weekly(40, False, "2026-10-31", log=lambda *_: None, share=0.3)
    L = ledger.Ledger()
    n_tree = sum(grammar.has_tree(r["genome"]) for r in L.rows)
    assert n_tree == d["search"]["trees"] == d["trees"]["this_run"] == 12
    assert d["pool_after"]["n_trials"] == d["pool_before"]["n_trials"] + 40   # trees and families alike
    md = run.writeup.markdown(d)
    assert "## Invented building blocks (expression trees)" in md and "Best tree in sample: `" in md
    assert "\u2014" not in md
    run.publish(d)


# ---------------------------------------------------------------- the small-account mode

def bars_of(crypto: dict) -> dict:
    """Daily (high, low, close) around the synthetic closes, a wick each way."""
    return {a: (p * 1.03, p * 0.98, p) for a, p in crypto.items()}


@pytest.fixture(scope="module")
def sctx():
    days, crypto, etf = synthetic()
    return small.make_ctx(days, crypto, etf, EURUSD, {"SPY": 0.003, "QQQ": 0.0, "GOLD": 0.01}, bars=bars_of(crypto))


def test_small_tree_genomes_stay_in_its_grammar():
    rng = random.Random(12)
    for _ in range(200):
        g = small.random_tree_genome(rng)
        assert small.valid(g)[0] and grammar.has_tree(g)
        assert all(grammar.leaves_of(t) <= set(small.LEAVES) for _, t in grammar.trees_of(g))
        m = small.mutate(g, rng, trees=True)
        assert small.valid(m)[0] and grammar.has_tree(m)
        assert not grammar.has_tree(small.mutate(small.random_genome(rng), rng))
    t = {"op": "rank", "args": [w("ret", 20, leaf("volume"))]}
    g = dict(small.hold_genome("SPY"), signal={"kind": "expr", "tree": t})
    assert not small.valid(small.canonical(g))[0]          # no volume series in this market


def test_small_tree_weights_never_look_ahead(sctx):
    rng = random.Random(13)
    days, crypto, etf = synthetic(bump=(2400, 2.5))
    b = small.make_ctx(days, crypto, etf, EURUSD, {"SPY": 0.003, "QQQ": 0.0, "GOLD": 0.01}, bars=bars_of(crypto))
    for _ in range(40):
        g = small.random_tree_genome(rng)
        W1, W2 = small.weights(sctx, g), small.weights(b, g)
        assert np.allclose(W1[:2400], W2[:2400]), small.describe(g)
        assert (W1 >= 0).all() and (W1.sum(1) <= 1 + 1e-9).all() and ((W1 > 0).sum(1) <= small.MAX_HELD).all()


def test_small_search_gives_its_share_to_trees_and_resumes(sctx, tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHIA_FACTORY_SMALL_DIR", str(tmp_path / "small"))
    v = make_venue()
    led = small.Ledger()
    res = small.search(sctx, v, led, "r1", 10, log=lambda *_: None, share=0.3)
    assert res["trees"] == 3 == sum(grammar.has_tree(r["genome"]) for r in small.Ledger().rows)
    again = small.search(sctx, v, small.Ledger(), "r1", 20, log=lambda *_: None, share=0.3)
    assert again["resumed"] == 10 and again["trees"] == 6 and len(small.Ledger()) == 20
    r = next(r for r in again["rows"] if grammar.has_tree(r["genome"]))
    assert r["fitness"] <= r["is_sharpe"] - (small.COMPLEXITY_COST + small.TREE_NODE_COST) * r["tree_nodes"] + 1e-9


def test_small_report_shows_the_trees(sctx, tmp_path, monkeypatch):
    from lab import report
    monkeypatch.setenv("PYTHIA_FACTORY_DIR", str(tmp_path / "factory"))
    monkeypatch.setenv("PYTHIA_FACTORY_SMALL_SEED", str(tmp_path / "no_seed"))
    monkeypatch.delenv("PYTHIA_FACTORY_SMALL_DIR", raising=False)
    monkeypatch.setattr(report, "REPORTS", tmp_path / "reports")
    d = small.run(sctx, make_venue(), 10, "2026-10-31", log=lambda *_: None, share=0.3)
    assert d["trees"]["this_run"] == 3
    md = small.markdown(d)
    assert "## Invented building blocks (expression trees)" in md and "\u2014" not in md
    small.publish(d)
