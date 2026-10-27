"""F2, the factory's small-account mode, on synthetic prices: grammar, weights, the wallet's costs and minimums,
the ledger's own namespace, the gates, the shadow wallets, the report, the job.

No network, no lab data. Run from research/lab:  python -m pytest tests/test_factory_small.py
"""

from __future__ import annotations

import json
import random
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest

from lab import metrics, report
from lab.experiments import fam_common as fc
from lab.experiments import smallaccount_s2 as s2
from lab.factory import ledger as lg
from lab.factory import run as factory_run
from lab.factory import small

START = int(datetime(2017, 8, 17, tzinfo=timezone.utc).timestamp() * 1e6)   # Binance's first BTCUSDT day (D1)
EURUSD = 1.1


def synthetic(T: int = 3403, seed: int = 5, etf_end: int | None = None, bump: tuple[int, float] | None = None):
    """Crypto closes every day, ETF closes on weekdays (ending at day etf_end), from 2017-08-17."""
    rng = np.random.default_rng(seed)
    days = START + np.arange(T, dtype=np.int64) * fc.DAY_US
    crypto = {}
    for i, a in enumerate(small.CRYPTO):
        r = rng.normal(0.0008 - 0.0002 * i, 0.035, T)
        p = 100 * (i + 1) * np.exp(np.cumsum(r))
        if a == "SOL":
            p[:500] = np.nan                     # listed late, as SOL was
        if bump:
            p[bump[0]:] *= bump[1]
        crypto[a] = p
    d = (days // fc.DAY_US).astype("datetime64[D]")
    wk = np.array([x.astype(datetime).weekday() < 5 for x in d])
    end = T if etf_end is None else etf_end
    etf = {}
    for i, u in enumerate(small.UNDERLYING.values()):
        idx = np.flatnonzero(wk[:end])
        r = rng.normal(0.0005, 0.011, len(idx))
        c = 300 * np.exp(np.cumsum(r))
        if bump:
            c[idx >= bump[0]] *= bump[1]
        etf[u] = (d[idx], c)
    return days, crypto, etf


def make_venue() -> s2.S2Venue:
    lad = {a: [(5.0, 1.0), (25.0, 2.0), (100.0, 4.0)] for a in small.ASSETS}
    return s2.S2Venue("jupiter", EURUSD, ladder=lad)


@pytest.fixture
def ctx():
    days, crypto, etf = synthetic()
    noise = {a: np.array([-20.0, -5.0, 0.0, 5.0, 20.0]) for a in small.UNDERLYING}
    return small.make_ctx(days, crypto, etf, EURUSD, {"SPY": 0.003, "QQQ": 0.0, "GOLD": 0.01}, noise)


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHIA_FACTORY_DIR", str(tmp_path / "factory"))
    monkeypatch.setenv("PYTHIA_FACTORY_SMALL_SEED", str(tmp_path / "no_seed"))
    monkeypatch.delenv("PYTHIA_FACTORY_SMALL_DIR", raising=False)
    monkeypatch.setattr(report, "REPORTS", tmp_path / "reports")
    return tmp_path


# ---------------------------------------------------------------- grammar

def test_random_mutated_and_crossed_genomes_stay_in_the_grammar():
    rng = random.Random(1)
    gs = [small.random_genome(rng) for _ in range(300)]
    for g in gs:
        ok, why = small.valid(g)
        assert ok, why
        assert g["select"]["k"] <= min(small.MAX_HELD, len(small.UNIVERSES[g["universe"]["set"]]))
        assert small.complexity(g) <= small.MAX_COMPLEXITY
        m = small.mutate(g, rng)
        assert small.valid(m)[0] and small.key(m) != small.key(g)
        assert small.valid(small.crossover(g, gs[0], rng))[0]
    assert len({small.key(g) for g in gs}) > 250
    for a in ("SPY", "BTC"):
        assert small.valid(small.hold_genome(a))[0]


def test_grammar_refuses_what_is_outside_it():
    g = small.hold_genome("SPY")
    assert not small.valid({**g, "select": {"k": 2, "rank": "signal"}})[0]      # 2 of a set of 1
    bad = json.loads(json.dumps(g))
    bad["rebalance"]["band"] = 0.5
    assert not small.valid(bad)[0]
    bad = json.loads(json.dumps(g))
    bad["universe"] = {"set": "doge"}
    assert not small.valid(bad)[0]
    # the key is the canonical text: filter order does not matter, and it is not the weekly factory's key
    a = {**g, "filters": [{"kind": "vol", "max": 0.6}, {"kind": "absmom", "lb": 90}]}
    b = {**g, "filters": [{"kind": "absmom", "lb": 90}, {"kind": "vol", "max": 0.6}]}
    assert small.key(small.canonical(a)) == small.key(small.canonical(b))
    assert "SPY" in small.describe(g) and "weekly" in small.describe(g)


# ---------------------------------------------------------------- market and weights

def test_market_prices_in_eur_with_drift_and_premium(ctx):
    j = small.ASSETS.index("SPY")
    assert np.isfinite(ctx.px[:, small.ASSETS.index("BTC")]).all()
    assert np.isnan(ctx.px[:400, small.ASSETS.index("SOL")]).all()           # not before its listing
    ratio = ctx.px[-1, j] / ctx.sig[-1, j]
    assert 0.997 < ratio < 1.003 and ratio != 1.0                            # a premium draw, around 0
    assert ctx.fresh == ctx.T - 1
    assert (ctx.sol_eur > 0).all()                                           # fees before SOL: its first price


def test_fresh_stops_at_a_stale_etf_close():
    days, crypto, etf = synthetic(etf_end=3300)
    c = small.make_ctx(days, crypto, etf, EURUSD, {})
    last_etf = max(etf["SPY"][0])
    assert c.fresh < c.T - 1
    assert (c.days[c.fresh] // fc.DAY_US).astype("datetime64[D]") <= last_etf + np.timedelta64(small.ETF_STALE_DAYS, "D")


def test_weights_hold_at_most_three_and_never_look_ahead(ctx):
    rng = random.Random(4)
    days, crypto, etf = synthetic(bump=(2900, 3.0))
    bumped = small.make_ctx(days, crypto, etf, EURUSD, {"SPY": 0.003, "QQQ": 0.0, "GOLD": 0.01},
                            {a: np.array([-20.0, -5.0, 0.0, 5.0, 20.0]) for a in small.UNDERLYING})
    for _ in range(40):
        g = small.random_genome(rng)
        W = small.weights(ctx, g)
        assert np.isfinite(W).all() and (W >= 0).all()
        assert ((W > 0).sum(1) <= small.MAX_HELD).all()
        assert (W.sum(1) <= 1 + 1e-9).all()
        allowed = np.array([a in small.UNIVERSES[g["universe"]["set"]] for a in small.ASSETS])
        assert not W[:, ~allowed].any()
        assert np.allclose(small.weights(bumped, g)[:2900], W[:2900])


def test_regime_filter_puts_the_whole_book_in_usdc(ctx):
    g = small.canonical({**small.hold_genome("BTC"), "filters": [{"kind": "regime", "on": "SPY", "ma": 200}]})
    W = small.weights(ctx, g)
    j = small.ASSETS.index("SPY")
    with np.errstate(invalid="ignore"):
        off = ~(ctx.sig[:, j] > fc.rolling(ctx.sig, 200, 200)[:, j])
    assert (W[off] == 0).all() and W[~off].sum() > 0


# ---------------------------------------------------------------- the wallet

def test_costs_minimum_reserve_and_way_in(ctx):
    v = make_venue()
    t0, t1 = small.windows(ctx)["is"]
    g = small.hold_genome("SPY")
    W = small.weights(ctx, g)
    res = small.simulate(ctx, W, g, v, 40.0, t0, t1, once=True)
    assert res["orders"] == 1
    idle, way = v.setup(40.0, small.MAX_HELD, float(ctx.sol_eur[t0]))
    assert idle > 0 and way > 0
    assert res["costs"] > way                                      # the swap paid its fee on top of the way in
    assert res["equity"][0] < 40.0
    # 4 EUR after the reserve is under the 5 USDC minimum: nothing is ever bought
    tiny = small.simulate(ctx, W, g, v, idle + 4.0, t0, t1)
    assert tiny["orders"] == 0 and tiny["skipped"] > 0


def test_a_band_trades_less_than_none(ctx):
    v = make_venue()
    t0, t1 = small.windows(ctx)["is"]
    base = small.canonical({"universe": {"set": "mixed"}, "signal": {"kind": "hold"}, "filters": [],
                            "select": {"k": 3, "rank": "signal"},
                            "weight": {"scheme": "invvol", "fill": "full", "target": 0.0},
                            "rebalance": {"every": 1, "band": 0.0}})
    wide = json.loads(json.dumps(base))
    wide["rebalance"]["band"] = 0.25
    a = small.simulate(ctx, small.weights(ctx, base), base, v, 100.0, t0, t1)
    b = small.simulate(ctx, small.weights(ctx, wide), wide, v, 100.0, t0, t1)
    assert b["orders"] < a["orders"]
    assert b["costs"] < a["costs"]


def test_the_fixed_fee_a_swap_weighs_more_on_a_small_order(ctx):
    v = make_venue()
    sol = float(ctx.sol_eur[-1])
    fee = s2.SWAP_FEE_SOL * sol
    assert v.cost("BTC", 5.0, sol) == pytest.approx(5.0 * 1.0 / 1e4 + fee, rel=0.05)
    assert v.cost("BTC", 5.0, sol) / 5.0 > v.cost("BTC", 20.0, sol) / 20.0
    t0, t1 = small.windows(ctx)["is"]
    g = small.canonical({**small.hold_genome("BTC"), "signal": {"kind": "mom", "lb": 28},
                         "rebalance": {"every": 1, "band": 0.0}})
    r = small.simulate(ctx, small.weights(ctx, g), g, v, 40.0, t0, t1)
    least = s2.SWAP_FEE_SOL * float(ctx.sol_eur[t0:t1 + 1].min())
    assert r["orders"] > 10 and r["costs"] > r["orders"] * least      # every swap paid at least its network fee


# ---------------------------------------------------------------- judging

def test_in_sample_row_and_holdout_against_spyx_and_btc(ctx):
    v = make_venue()
    g = small.canonical({**small.hold_genome("BTC"), "universe": {"set": "growth"},
                         "signal": {"kind": "ma", "fast": 1, "slow": 200}})
    r = small.in_sample(ctx, g, v, "r1")
    for k in ("is_sharpe_40", "is_sharpe_100", "is_h1", "is_h2", "fitness", "is_exposure"):
        assert np.isfinite(r[k])
    assert r["is_sharpe"] == min(r["is_sharpe_40"], r["is_sharpe_100"])
    bench = small.benchmarks(ctx, v, small.windows(ctx)["oos"])
    assert set(bench) == {"SPY@40", "SPY@100", "BTC@40", "BTC@100"}
    pool = small.Ledger(Path("/nonexistent/ledger.jsonl")).pool()
    h = small.holdout(ctx, g, v, pool, bench)
    assert h["spy_cagr_40"] == bench["SPY@40"]["cagr"] and h["btc_end_eur_100"] == bench["BTC@100"]["end_eur"]
    assert len(h["oos_returns_40"]) == h["oos_days"]
    gs = small.gates(r, h)
    assert set(gs) == {"is_stable", "drawdown", "beats_spy", "late_fill"}


def test_gates_need_a_small_drawdown_and_spyx_beaten_at_both_capitals():
    is_row = {"is_h1": 0.5, "is_h2": 0.3}
    h = {"oos_max_dd_40": 0.15, "oos_max_dd_100": 0.14, "oos_cagr_40": 0.25, "oos_cagr_100": 0.26,
         "spy_cagr_40": 0.20, "spy_cagr_100": 0.21, "oos_late_cagr": 0.1}
    assert small.failed(small.gates(is_row, h)) == []
    assert small.failed(small.gates(is_row, {**h, "oos_max_dd_100": 0.21})) == ["drawdown"]
    assert small.failed(small.gates(is_row, {**h, "oos_cagr_100": 0.20})) == ["beats_spy"]
    assert small.failed(small.gates({"is_h1": -0.1, "is_h2": 0.3}, h)) == ["is_stable"]


# ---------------------------------------------------------------- ledger, seed, run, shadows, report

def test_own_ledger_namespace_and_bar(dirs):
    led = small.Ledger()
    assert led.path == dirs / "factory" / "small" / "ledger.jsonl"
    p0 = led.pool()
    assert p0["n_trials"] == metrics.trial_pool()["n_trials"] and p0["family_trials"] == 61 + 8 + 1   # S1, S2, L1
    led.add([{"key": f"k{i}", "is_sharpe": s, "fitness": s} for i, s in enumerate([0.5, 1.5, -0.3, 2.0])])
    p = small.Ledger().pool()
    assert p["n_trials"] == p0["n_trials"] + 4 and p["family_trials"] == 70 + 4 and p["sr0_annual"] > 0
    assert p["family"] == "small" and {r["id"] for r in metrics.read_registry()} >= {f"small:k{i}" for i in range(4)}
    assert not lg.ledger_path().exists()                     # the weekly factory's ledger is not touched
    led.add([{"key": "k0", "is_sharpe": 9.0, "fitness": 9.0}])
    assert len(small.Ledger()) == 4                          # a genome is one trial, forever


def test_seed_import_is_idempotent_and_leaves_survivors_to_be_checked_here(dirs, monkeypatch):
    seed = dirs / "seed"
    seed.mkdir()
    (seed / "ledger.jsonl").write_text("".join(json.dumps({"key": f"s{i}", "is_sharpe": 1.0, "fitness": 1.0}) + "\n"
                                               for i in range(3)))
    (seed / "holdout.jsonl").write_text(json.dumps({"run": "r", "key": "s0", "decision": "stopped"}) + "\n"
                                        + json.dumps({"run": "r", "key": "s1", "decision": "shadow"}) + "\n")
    monkeypatch.setenv("PYTHIA_FACTORY_SMALL_SEED", str(seed))
    assert small.import_seed() == {"ledger": 3, "holdout": 1}
    assert small.import_seed() == {"ledger": 0, "holdout": 0}
    assert [h["key"] for h in lg.read_jsonl(small.small_dir() / "holdout.jsonl")] == ["s0"]


def _run(c, v, budget, run_id, monkeypatch=None, force=False):
    if force:
        monkeypatch.setattr(small, "gates", lambda r, h: {"all": {"passed": True, "why": "forced"}})
    return small.run(c, v, budget, run_id, log=lambda *_: None)


def test_run_is_resumable_and_writes_the_report(ctx, dirs):
    v = make_venue()
    d = _run(ctx, v, 12, "2026-10-26")
    led = small.Ledger()
    assert len(led) == 12 and d["search"]["evaluated"] == 12
    assert d["pool_after"]["n_trials"] == d["pool_before"]["n_trials"] + led.trials()   # one trial per behaviour
    assert led.trials() == len({r["behaviour"] for r in led.rows}) and d["night"]["same_behaviour"] == 12 - led.trials()
    assert all(0.0 <= h["deflated_p"] <= 1.0 and 0.0 <= h["dsr_family"] <= 1.0 for h in d["holdout"])
    again = _run(ctx, v, 12, "2026-10-26")
    assert len(small.Ledger()) == 12 and again["search"]["resumed"] == 12
    assert [h["key"] for h in again["holdout"]] == [h["key"] for h in d["holdout"]]
    more = _run(ctx, v, 15, "2026-10-26")                    # a larger budget the same day: only the rest
    assert len(small.Ledger()) == 15 and more["search"]["evaluated"] == 15
    small.publish(more)
    md = (report.REPORTS / "smallaccount" / "factory.md").read_text(encoding="utf-8")
    assert "SPYx" in md and "cbBTC" in md and "EUR" in md and "trials" in md
    js = json.loads((report.REPORTS / "smallaccount" / "factory.json").read_text(encoding="utf-8"))
    assert js["title"] and js["status"] in report.FEED_STATUSES and js["headline"] == more["verdict"]
    assert "\u2014" not in md


def test_shadow_wallets_start_step_forward_and_retire(dirs, monkeypatch):
    v = make_venue()
    days, crypto, etf = synthetic(T=3403)
    c = small.make_ctx(days[:3353], {a: x[:3353] for a, x in crypto.items()},
                       {u: (dd[dd <= (days[3352] // fc.DAY_US).astype("datetime64[D]")],
                            cc[dd <= (days[3352] // fc.DAY_US).astype("datetime64[D]")]) for u, (dd, cc) in etf.items()},
                       EURUSD, {})
    d = _run(c, v, 20, "r1", monkeypatch, force=True)
    sh = [h for h in d["holdout"] if h["decision"] == "shadow"]
    assert 1 <= len(sh) <= small.MAX_NEW_PER_RUN
    act = small.active()
    assert len(act) == len(sh) and all(m["entry_day"] == small._day(c, c.fresh) for m in act)
    assert all(m["wallet"]["costs"] > 0 for m in act)        # the way in and the first swap are paid
    # 50 more days: each shadow appends only what is new, then is reviewed against its SPYx wallet
    full = small.make_ctx(days, crypto, etf, EURUSD, {})
    upd = small.update_shadows(full, v)
    assert all(u["appended"] == 50 for u in upd)
    assert all(u["appended"] == 0 for u in small.update_shadows(full, v))
    rows = small.journal(act[0]["key"])
    assert len(rows) == 50 and rows[0]["date"] > act[0]["entry_day"]
    dec = small.review(small._day(full, full.fresh))
    assert {x["key"] for x in dec} == {m["key"] for m in act}
    for x in dec:
        fw = small.forward(next(m for m in small.all_shadows() if m["key"] == x["key"]))
        assert (x["status"] == "retired") == (fw["sharpe"] <= fw["spy_sharpe"])
    assert small.review(small._day(full, full.fresh)) == []  # the next review is 30 days later
    # never more than MAX_ACTIVE at once
    monkeypatch.setattr(small, "MAX_NEW_PER_RUN", 10)
    _run(full, v, 40, "r2", monkeypatch, force=True)
    assert len(small.active()) <= small.MAX_ACTIVE


# ---------------------------------------------------------------- entry point and job

def test_factory_main_dispatches_small(monkeypatch):
    seen = []
    monkeypatch.setattr(small, "main", lambda argv: seen.append(argv) or 0)
    assert factory_run.main(["small", "--budget", "5"]) == 0
    assert seen == [["--budget", "5"]]


def test_the_job_runs_daily_at_three_under_the_heavy_lock():
    from lab.ops import jobs
    t = jobs.load_table(Path(__file__).resolve().parents[2] / "ops" / "jobs.yaml")
    j = t.jobs["factory-small"]
    assert j["schedule"] == "0 3 * * *" and j["command"] == "python -m lab.factory small"
    assert "heavy" in j["locks"] and j["env"]["PYTHIA_FACTORY_SMALL_BUDGET"] == "60"
    assert j["env"]["PYTHIA_AGENT_OUT"] == "/data/lab-cache"
