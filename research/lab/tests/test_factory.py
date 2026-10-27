"""The strategy factory on a synthetic panel: grammar, simulator, honesty of the gates, ledger, shadow books.

No network, no lab data. Run from research/lab:  python -m pytest tests
"""

from __future__ import annotations

import csv
import json
import math
import random
from datetime import datetime, timezone

import numpy as np
import pytest

from lab import history, metrics, report
from lab.experiments import fam_common as fc
from lab.factory import build, evaluate, grammar, ledger, run, search, shadow

DAY_US = fc.DAY_US
START = int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp() * 1e6)


def synthetic_panel(T: int = 1600, n_other: int = 24, seed: int = 3, bump: tuple[int, float] | None = None) -> fc.Panel:
    """Coins with random-walk prices, some trending, one dying in 2022. `bump=(t, x)`
    multiplies every price from day t on by x (to check that nothing looks ahead)."""
    rng = np.random.default_rng(seed)
    names = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT", "LINKUSDT"] + [
        f"C{i:02d}USDT" for i in range(n_other)]
    N = len(names)
    drift = rng.normal(0.0004, 0.0015, N)
    r = rng.normal(drift, 0.04, (T, N))
    px = 100 * np.exp(np.cumsum(r, 0))
    alive = np.ones((T, N), dtype=bool)
    alive[:30, 10:14] = False                  # late listings
    alive[900:, 12] = False                    # a coin that dies
    if bump:
        px[bump[0]:] *= bump[1]
    close = np.where(alive, px, np.nan)
    ret = np.full((T, N), np.nan)
    ret[1:] = np.where(alive[1:] & alive[:-1], close[1:] / close[:-1] - 1, np.nan)
    first = np.argmax(alive, 0)
    age = np.where(alive, np.arange(T)[:, None] - first[None, :], -1)
    qv = np.where(alive, rng.lognormal(16, 1, (T, N)) * np.linspace(3, 0.5, N)[None, :], np.nan)
    adv28 = fc.rolling(qv, 28, 20)
    rv = np.where(alive, r ** 2, np.nan)
    sigma = np.sqrt(fc.rolling(rv, 30, 20))
    eligible = alive & (age >= 60) & (np.nan_to_num(adv28) >= fc.MIN_ADV_USD)
    days = START + np.arange(T, dtype=np.int64) * DAY_US
    ma200 = fc.rolling(close[:, :1], 200, 200)[:, 0]
    btc_on = np.nan_to_num(close[:, 0] > ma200, nan=0.0).astype(bool)
    return fc.Panel(days, names, [fc.base_of(n) for n in names], close, close.copy(), close * 1.01, close * 0.99,
                    ret, alive, alive.copy(), age, adv28, sigma, eligible, np.zeros((T, N), dtype=bool),
                    np.zeros((T, N)), btc_on, 0, extra={"qv": qv, "rv": rv})


@pytest.fixture(scope="module")
def ctx():
    return build.make_ctx(synthetic_panel())


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHIA_FACTORY_DIR", str(tmp_path / "factory"))
    monkeypatch.setenv("PYTHIA_FACTORY_SEED", str(tmp_path / "no_seed"))
    monkeypatch.setattr(report, "REPORTS", tmp_path / "reports")
    monkeypatch.delenv("PYTHIA_RESULTS", raising=False)
    for k in ("PYTHIA_ALERT_WEBHOOK", "PYTHIA_TELEGRAM_BOT_TOKEN", "PYTHIA_TELEGRAM_CHAT_ID"):
        monkeypatch.delenv(k, raising=False)
    return tmp_path


# ---------------------------------------------------------------- grammar

def test_random_genomes_are_valid_and_bounded():
    rng = random.Random(1)
    for _ in range(500):
        g = grammar.random_genome(rng)
        ok, why = grammar.valid(g)
        assert ok, why
        assert grammar.complexity(g) <= grammar.MAX_COMPLEXITY
        assert len(g["filters"]) <= grammar.MAX_FILTERS
        assert "\u2014" not in grammar.describe(g)


def test_mutation_and_crossover_stay_inside_the_grammar():
    rng = random.Random(2)
    a, b = grammar.random_genome(rng), grammar.random_genome(rng)
    for _ in range(300):
        m = grammar.mutate(a, rng)
        assert grammar.valid(m)[0] and grammar.key(m) != grammar.key(a)
        x = grammar.crossover(a, b, rng)
        assert grammar.valid(x)[0]
        a = m


def test_key_is_canonical_and_invalid_genomes_are_refused():
    g = {"universe": {"kind": "top", "n": 20}, "signal": {"kind": "mom", "lb": 28},
         "filters": [{"kind": "trend", "ma": 100}, {"kind": "regime", "ma": 200}],
         "select": {"k": 10, "rank": "signal"}, "weight": {"scheme": "equal", "fill": "slots"},
         "rebalance": {"every": 1, "tranches": 1, "band": 0.0}}
    g2 = dict(g, filters=list(reversed(g["filters"])))
    assert grammar.key(grammar.canonical(g)) == grammar.key(grammar.canonical(g2))
    assert grammar.valid(grammar.canonical(g))[0]
    bad = grammar.canonical(dict(g, signal={"kind": "mom", "lb": 29}))
    assert not grammar.valid(bad)[0]
    bad = grammar.canonical(dict(g, signal={"kind": "ma", "fast": 50, "slow": 50}))
    assert not grammar.valid(bad)[0]
    many = grammar.canonical(dict(g, filters=[{"kind": "trend", "ma": 50}, {"kind": "regime", "ma": 200},
                                              {"kind": "vol", "max": 0.8}, {"kind": "btcmom", "lb": 28}]))
    assert not grammar.valid(many)[0]
    assert not grammar.valid(grammar.canonical(dict(g, universe={"kind": "alpaca"},
                                                    select={"k": 20, "rank": "signal"})))[0]


# ---------------------------------------------------------------- simulator

def test_simulator_matches_the_sweep_simulator(ctx):
    rng = random.Random(4)
    for _ in range(5):
        g = grammar.random_genome(rng)
        W = build.weights(ctx, g)
        mine = build.simulate(ctx, W)
        full = np.zeros((ctx.T, ctx.P.N))
        full[:, ctx.cols] = W
        gross, tov, _, _ = fc.simulate(ctx.P, full)
        assert np.allclose(mine[0], gross)
        assert np.allclose(mine[1][:-1], tov[:-1])


def test_cadence_and_band_cut_turnover(ctx):
    g = {"universe": {"kind": "top", "n": 20}, "signal": {"kind": "mom", "lb": 7}, "filters": [],
         "select": {"k": 10, "rank": "signal"}, "weight": {"scheme": "invvol", "fill": "full"},
         "rebalance": {"every": 1, "tranches": 1, "band": 0.0}}
    W = build.weights(ctx, g)
    daily = build.simulate(ctx, W)[1].sum()
    weekly = build.simulate(ctx, W, every=7)
    banded = build.simulate(ctx, W, band=0.5)[1].sum()
    assert weekly[1].sum() < daily and banded < daily
    dayno = ctx.days // DAY_US
    traded_on = np.flatnonzero(weekly[1] > 0)
    # Off-cadence turnover only from a coin whose series ended.
    off = [t for t in traded_on if dayno[t] % 7 != 0]
    assert all(not ctx.alive[t].all() for t in off)


def test_weights_never_look_ahead():
    t_cut = 1000
    a = build.make_ctx(synthetic_panel())
    b = build.make_ctx(synthetic_panel(bump=(t_cut + 1, 3.0)))
    rng = random.Random(5)
    for _ in range(25):
        g = grammar.random_genome(rng)
        assert np.allclose(build.weights(a, g)[: t_cut + 1], build.weights(b, g)[: t_cut + 1]), grammar.describe(g)


def test_weights_are_long_only_and_capped(ctx):
    rng = random.Random(6)
    for _ in range(40):
        g = grammar.random_genome(rng)
        W = build.weights(ctx, g)
        assert np.isfinite(W).all() and (W >= 0).all()
        assert (W.sum(1) <= 1 + 1e-9).all()
        assert ((W > 0).sum(1) <= g["select"]["k"]).all()


def test_holdings_match_the_simulation(ctx):
    g = grammar.random_genome(random.Random(8))
    r = g["rebalance"]
    t = ctx.T - 1
    *_, w = build.simulate(ctx, build.weights(ctx, g), r["every"], r["band"], keep_at=t)
    h = build.holdings(ctx, g, t)
    assert pytest.approx(sum(h.values())) == float(w.sum())


# ---------------------------------------------------------------- ledger and deflation

def test_ledger_counts_each_genome_once_and_survives_a_torn_line(home):
    L = ledger.Ledger()
    base = metrics.trial_pool()["n_trials"]                # the registry's seed: hand and small-account trials
    assert L.n_trials() == base
    rows = [{"key": f"k{i}", "is_sharpe": float(i % 5 - 2), "fitness": 0.0} for i in range(10)]
    assert len(L.add(rows)) == 10
    assert len(L.add(rows[:3] + [{"key": "new", "is_sharpe": 0.5, "fitness": 0.0}])) == 1
    with ledger.ledger_path().open("a") as fh:
        fh.write('{"key": "torn"')
    L2 = ledger.Ledger()
    assert len(L2) == 11 and L2.n_trials() == base + 11
    reg = metrics.read_registry()
    assert sum(r["family"] == "factory" for r in reg) == 11 and len({r["id"] for r in reg}) == len(reg)


def test_prior_pool_reproduces_the_published_bar(home):
    assert metrics.expected_max_sharpe(ledger.prior_var(), ledger.PRIOR_TRIALS) * math.sqrt(365) == pytest.approx(
        ledger.PRIOR_SR0, abs=1e-6)
    p = ledger.Ledger().pool()                             # the hand family at the prior's variance, more trials
    assert p["families"]["hand"]["var"] == pytest.approx(ledger.prior_var())
    assert p["n_trials"] == metrics.trial_pool()["n_trials"] and p["sr0_annual"] > ledger.PRIOR_SR0


def test_bar_rises_as_trials_accumulate(home):
    L = ledger.Ledger()
    rng = np.random.default_rng(0)
    pool0 = L.pool()
    L.add([{"key": f"k{i}", "is_sharpe": float(x), "fitness": 0.0} for i, x in enumerate(rng.normal(0, 1.5, 2000))])
    after = L.pool()
    assert after["n_trials"] == pool0["n_trials"] + 2000 and after["family_trials"] == 2000
    assert after["sr0_annual"] > pool0["sr0_annual"]
    x = rng.normal(0.002, 0.03, 900)
    assert ledger.deflated(x, after) < ledger.deflated(x, pool0)
    assert 0.0 <= ledger.deflated_family(x, after) <= 1.0


def test_lock_refuses_a_second_process(home):
    with ledger.lock():
        with pytest.raises(RuntimeError):
            with ledger.lock():
                pass


# ---------------------------------------------------------------- search and gates

def test_search_spends_its_budget_on_new_genomes_only(ctx):
    rng = random.Random(9)
    tried = {grammar.key(grammar.random_genome(rng)) for _ in range(50)}
    res = search.search(ctx, tried, [], "t1", budget=30, seed=1, log=lambda *_: None)
    keys = [r["key"] for r in res["rows"]]
    assert len(keys) == 30 == len(set(keys))
    assert not set(keys) & tried
    again = search.search(ctx, tried, [], "t1", budget=30, seed=1, log=lambda *_: None)
    assert [r["key"] for r in again["rows"]] == keys
    bred = search.search(ctx, tried | set(keys), res["rows"], "t2", budget=20, seed=2, log=lambda *_: None)
    assert bred["origin"]["mutation"] + bred["origin"]["crossover"] > 0


def test_in_sample_row_never_reads_the_held_back_window(ctx):
    g = grammar.random_genome(random.Random(10))
    P2 = synthetic_panel(bump=(int(np.flatnonzero(ctx.days >= fc.SPLIT)[0]) + 1, 0.2))
    a = evaluate.in_sample(ctx, g, "x")
    b = evaluate.in_sample(build.make_ctx(P2), g, "x")
    for k in ("is_sharpe", "is_h1", "is_h2", "is_turnover_yr", "fitness"):
        assert a[k] == pytest.approx(b[k])


def test_gates_say_why(home, ctx):
    g = grammar.random_genome(random.Random(11))
    p = ledger.Ledger(ledger.ledger_path().with_name("none.jsonl")).pool()
    h = evaluate.holdout(ctx, g, p, evaluate.btc_benchmark(ctx))
    r = evaluate.in_sample(ctx, g, "x")
    gates = evaluate.bar_gates(r, h)
    assert set(gates) == set(evaluate.SHADOW_GATES) | {"deflated"}
    assert all(v["why"] for v in gates.values())
    lo, mid, hi = h["band30"]
    assert lo <= mid <= hi


# ---------------------------------------------------------------- the weekly run and shadow books

def test_weekly_run_end_to_end(home, monkeypatch):
    P = synthetic_panel()
    monkeypatch.setattr(history, "load_long_panel", lambda fetch=False, fresh=False: P)
    d1 = run.weekly(40, False, "2026-10-17", log=lambda *_: None)
    run.publish(d1)
    assert (report.REPORTS / "factory" / "latest.md").exists()
    L = ledger.Ledger()
    assert len(L) == 40 and d1["pool_after"]["n_trials"] == d1["pool_before"]["n_trials"] + 40
    d2 = run.weekly(40, False, "2026-10-24", log=lambda *_: None)
    assert len(ledger.Ledger()) == 80
    assert d2["pool_after"]["sr0_annual"] != d1["pool_after"]["sr0_annual"]
    first = {h["key"] for h in d1["holdout"] if h["decision"] != "waiting"}
    assert not first & {h["key"] for h in d2["holdout"]}
    text = run.writeup.digest(d2)
    assert "\u2014" not in text and "Factory 2026-10-24" in text
    md = run.writeup.markdown(d2)
    assert "## Held back: what survived and why" in md


def test_shadow_days_are_frozen_and_reviewed_after_a_month(home, ctx):
    g = grammar.random_genome(random.Random(12))
    r = evaluate.in_sample(ctx, g, "run")
    p = ledger.Ledger().pool()
    btc = evaluate.btc_benchmark(ctx)
    h = evaluate.holdout(ctx, g, p, btc)
    x = np.zeros(400)
    entry = datetime.fromtimestamp(ctx.days[-41] / 1e6, timezone.utc).strftime("%Y-%m-%d")
    shadow.start(r, h, evaluate.shadow_gates(r, h), x, "run", entry)
    up = shadow.update(ctx)
    assert up[0]["appended"] == 40
    assert shadow.update(ctx)[0]["appended"] == 0
    rows = shadow.journal(r["key"])
    assert rows[0]["date"] > entry and len(rows) == 40
    dec = shadow.review(ctx, p, btc, "today")
    assert len(dec) == 1 and dec[0]["status"] in ("promoted", "retired")
    meta = json.loads((shadow.shadow_dir() / f"{r['key']}.json").read_text())
    assert meta["status"] == dec[0]["status"] and meta["review_gates"]["deflated"]["why"]
    assert shadow.review(ctx, p, btc, "today") == []
    if dec[0]["status"] == "retired":
        assert shadow.promoted()["books"] == {}


def test_a_shadow_that_clears_every_gate_is_promoted_to_paper_only(home, ctx, monkeypatch):
    g = grammar.random_genome(random.Random(13))
    r = evaluate.in_sample(ctx, g, "run")
    p = ledger.Ledger().pool()
    btc = evaluate.btc_benchmark(ctx)
    h = evaluate.holdout(ctx, g, p, btc)
    entry = datetime.fromtimestamp(ctx.days[-35] / 1e6, timezone.utc).strftime("%Y-%m-%d")
    shadow.start(r, h, {}, np.full(400, 0.001), "run", entry)
    shadow.update(ctx)
    passing = {k: {"passed": True, "why": "ok"} for k in evaluate.SHADOW_GATES + ("deflated",)}
    monkeypatch.setattr(evaluate, "bar_gates", lambda *_: dict(passing))
    monkeypatch.setattr(shadow, "forward_stats",
                        lambda m: {"days": 34, "return": 0.05, "band": [-0.1, 0.0, 0.1], "below_band": False})
    dec = shadow.review(ctx, p, btc, "2026-11-20")
    assert dec[0]["status"] == "promoted"
    books = shadow.promoted()["books"]
    assert list(books) == [shadow.book_name(r["key"])]
    assert books[shadow.book_name(r["key"])]["genome"] == g


def test_shadow_csv_has_the_journal_columns(home, ctx):
    g = grammar.random_genome(random.Random(14))
    r = evaluate.in_sample(ctx, g, "run")
    entry = datetime.fromtimestamp(ctx.days[-5] / 1e6, timezone.utc).strftime("%Y-%m-%d")
    shadow.start(r, {}, {}, np.zeros(10), "run", entry)
    shadow.update(ctx)
    with (shadow.shadow_dir() / f"{r['key']}.csv").open() as fh:
        head = next(csv.reader(fh))
    assert head == ["date", "net_ret", "gross_ret", "turnover", "exposure", "equity"]


def test_paper_families_steps_a_promoted_book_on_its_own_cadence(home, monkeypatch):
    from lab.paper import families
    P = synthetic_panel()
    g = {"universe": {"kind": "top", "n": 20}, "signal": {"kind": "mom", "lb": 28}, "filters": [],
         "select": {"k": 5, "rank": "signal"}, "weight": {"scheme": "equal", "fill": "full"},
         "rebalance": {"every": 7, "tranches": 1, "band": 0.0}}
    assert families.factory_books() == {}
    ledger.write_json(shadow.promoted_path(), {"books": {"factory_abc": {"key": "abc", "name": "x", "genome": g,
                                                                          "promoted": "2026-11-20"}}})
    assert list(families.factory_books()) == ["factory_abc"]
    dayno = P.days // DAY_US
    on = int(np.flatnonzero(dayno % 7 == 0)[-1])
    off = on - 1
    row = families.factory_row(P, g, on)
    assert np.isfinite(row).all() and row.sum() == pytest.approx(1.0, abs=1e-6) or row.sum() == 0
    assert np.isnan(families.factory_row(P, g, off)).all()
    assert np.isfinite(families.factory_row(P, g, off, always=True)).all()
    tr = dict(g, rebalance={"every": 7, "tranches": 7, "band": 0.0})
    assert np.isfinite(families.factory_row(P, tr, off)).all()


# ---------------------------------------------------------------- tranches, the report header, the seed

def _weekly(tranches: int) -> dict:
    return {"universe": {"kind": "top", "n": 20}, "signal": {"kind": "mom", "lb": 28}, "filters": [],
            "select": {"k": 5, "rank": "signal"}, "weight": {"scheme": "equal", "fill": "full"},
            "rebalance": {"every": 7, "tranches": tranches, "band": 0.0}}


def test_tranches_only_for_a_weekly_book():
    g = _weekly(7)
    assert grammar.valid(g)[0] and grammar.complexity(g) == grammar.complexity(_weekly(1)) + 1
    assert "7 tranches" in grammar.describe(g)
    bad = dict(g, rebalance={"every": 3, "tranches": 7, "band": 0.0})
    assert not grammar.valid(bad)[0]
    rng = random.Random(15)
    seen = [grammar.random_genome(rng)["rebalance"] for _ in range(400)]
    assert any(r["tranches"] == 7 for r in seen)
    assert all(r["every"] == 7 for r in seen if r["tranches"] == 7)


def test_tranche_book_is_seven_sleeves_on_their_own_days(ctx):
    g = _weekly(7)
    W = build.weights(ctx, g)
    gross, tov, expo = build.run(ctx, g)
    sleeves = [build.simulate(ctx, W, 7, 0.0, offset=i) for i in range(7)]
    # Day by day the book's return lies within its sleeves' returns.
    lo = np.min([s[0] for s in sleeves], 0)
    hi = np.max([s[0] for s in sleeves], 0)
    assert ((gross >= lo - 1e-12) & (gross <= hi + 1e-12)).all()
    # One sleeve trades each day: the book trades on most days, in smaller pieces than a weekly book.
    weekly = build.simulate(ctx, W, 7, 0.0)
    assert (tov > 0).mean() > 3 * (weekly[1] > 0).mean()
    assert tov.max() < weekly[1].max()
    # A one-sleeve tranche book is the plain book.
    one = build.simulate_tranches(ctx, W, 7, 0.0, 1)
    assert np.allclose(one[0], weekly[0]) and np.allclose(one[1], weekly[1])
    t = ctx.T - 1
    h = build.holdings(ctx, g, t)
    assert sum(h.values()) == pytest.approx(expo[t], abs=1e-9)


def test_report_json_carries_the_common_header(home, monkeypatch):
    P = synthetic_panel()
    monkeypatch.setattr(history, "load_long_panel", lambda fetch=False, fresh=False: P)
    d = run.weekly(20, False, "2026-10-17", log=lambda *_: None)
    run.publish(d)
    j = json.loads((report.REPORTS / "factory" / "latest.json").read_text(encoding="utf-8"))
    assert list(j)[:5] == ["title", "updatedMs", "status", "headline", "items"]
    assert j["title"] == "Strategy factory" and j["status"] in ("ok", "watch")
    assert j["headline"] == d["verdict"] and isinstance(j["updatedMs"], int) and j["updatedMs"] > 0
    assert all(it["label"] for it in j["items"]) and len(j["items"]) <= 50
    assert j["items"][0]["importance"] == max(it["importance"] for it in j["items"])


def test_seed_carries_trials_to_another_machine_once(home, tmp_path, monkeypatch):
    P = synthetic_panel()
    monkeypatch.setattr(history, "load_long_panel", lambda fetch=False, fresh=False: P)
    run.weekly(20, False, "2026-10-15", log=lambda *_: None)
    seed = tmp_path / "seed"
    out = ledger.export_seed(seed)
    assert out["ledger"] == 20 and (seed / "ledger.jsonl").exists()
    # A fresh machine: an empty factory folder that imports the seed.
    monkeypatch.setenv("PYTHIA_FACTORY_DIR", str(tmp_path / "server"))
    monkeypatch.setenv("PYTHIA_FACTORY_SEED", str(seed))
    base = metrics.trial_pool()["n_trials"]               # the registry already holds the first machine's 20
    assert ledger.Ledger().n_trials() == base
    first = ledger.import_seed()
    assert first["ledger"] == 20 and first["shadow"] == out["shadow"]
    assert ledger.import_seed() == {"ledger": 0, "holdout": 0, "shadow": 0}
    d = run.weekly(20, False, "2026-10-17", log=lambda *_: None)
    assert d["pool_before"]["n_trials"] == base             # the seed's genomes are the same trials, not new ones
    assert d["pool_after"]["n_trials"] == base + 20


def test_digest_goes_through_notify_post_to_telegram(home, monkeypatch):
    from lab.ops import i18n, notify
    P = synthetic_panel()
    monkeypatch.setattr(history, "load_long_panel", lambda fetch=False, fresh=False: P)
    run.publish(run.weekly(20, False, "2026-10-17", log=lambda *_: None))
    monkeypatch.setenv("PYTHIA_TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("PYTHIA_TELEGRAM_CHAT_ID", "42")
    monkeypatch.setenv("PYTHIA_QUIET_HOURS", "off")
    monkeypatch.setenv(i18n.ENV, "en")         # not the data folder's message language
    sent = []
    monkeypatch.setattr(notify, "post", lambda url, fmt, text: sent.append((url, fmt, text)) or (True, None))
    assert run.main(["digest"]) == 0
    assert len(sent) == 1 and sent[0][1] == "telegram"
    text = sent[0][2]
    assert text.startswith("<b>🧪 Factory 2026-10-17</b>\n") and len(text) <= notify.MAX_CHARS, text
    assert text.endswith("<i>Pythia</i>")
    assert text.count("<b>") == text.count("</b>")
