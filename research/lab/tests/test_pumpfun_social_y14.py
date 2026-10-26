"""Y14, the coins' social links as features: the collector's normalised links (and nothing else of the document), the
store's columns, the social tracker's counts (only earlier coins, migrations before t, no look-ahead), its warm-up from
the record, the twins of the select and early models that wait for rows with metadata, the registered books and rule,
the run's helpers, and every strategy before Y14 trading exactly as before with the social tracker and the Y14 books
next to it. No network, no wallet.

Run from research/lab:  python -m pytest tests/test_pumpfun_social_y14.py
"""

from __future__ import annotations

import math
from types import SimpleNamespace

import numpy as np
import pytest

from lab.pumpfun_rt import collector as COL
from lab.pumpfun_rt import exitpol as XP
from lab.pumpfun_rt import model as M
from lab.pumpfun_rt import pipeline as P
from lab.pumpfun_rt import selfeat as SF
from lab.pumpfun_rt import selmodel as SM
from lab.pumpfun_rt import sim
from lab.pumpfun_rt import social14 as Y14
from lab.pumpfun_rt import socialfeat as SO
from lab.pumpfun_rt import store
from lab.pumpfun_rt import strategies as S
from lab.pumpfun_rt import trendfeat as TF
from test_pumpfun_exit_runners import Pool
from test_pumpfun_rt import MINT, T0, Fixed, key
from test_pumpfun_select_y9 import full, market, stub_models

Y14_NAMES = ["P_pool5_top30s", "P_pool0_wait_social"]
OLD = P.STRATEGIES[:[s.name for s in P.STRATEGIES].index(Y14_NAMES[0])]   # every strategy before Y14
MIN = 60_000


@pytest.fixture(autouse=True)
def small_models(monkeypatch):
    monkeypatch.setitem(M.PARAMS, "n_estimators", 30)
    monkeypatch.setitem(SM.PARAMS, "n_estimators", 30)


# ---------------------------------------------------------------- the collector's links

@pytest.mark.parametrize("v,want", [
    (None, ("none", None, None)), ("", ("none", None, None)),
    ("https://x.com/MissionGains/status/2114835278720548932", ("status", "missiongains", "2114835278720548932")),
    ("https://twitter.com/Foo_Bar?s=21", ("profile", "foo_bar", None)),
    ("x.com/foo/", ("profile", "foo", None)), ("www.x.com/foo", ("profile", "foo", None)),
    ("@Foo", ("profile", "foo", None)), ("foo_1", ("profile", "foo_1", None)),
    ("https://x.com/i/communities/1912345678901234567", ("community", None, None)),
    ("https://x.com/i/status/123", ("status", None, "123")),
    ("https://x.com/i/web/status/456", ("status", None, "456")),
    ("https://x.com/search?q=%24TCG", ("search", None, None)), ("https://x.com/hashtag/sol", ("search", None, None)),
    ("https://x.com/home", ("other", None, None)), ("https://example.com/foo", ("other", None, None)),
    ("https://x.com", ("other", None, None)), ("not a link at all", ("other", None, None)),
    ("https://evilx.com/foo", ("other", None, None)),
])
def test_the_x_link_kinds_handles_and_tweet_ids(v, want):
    assert COL.x_link(v) == want


def test_telegram_handles_and_website_domains():
    assert COL.tg_handle("https://t.me/MyCoinPortal") == "mycoinportal"
    assert COL.tg_handle("t.me/s/mycoin_chat") == "mycoin_chat" and COL.tg_handle("@MyCoin") == "mycoin"
    assert COL.tg_handle("https://t.me/+AbCdEf123") is None and COL.tg_handle("https://t.me/joinchat/xyz") is None
    assert COL.tg_handle("https://example.com/foo") is None and COL.tg_handle("") is None
    assert COL.web_domain("https://www.Shop.Example.COM/a?b=1") == "example.com"
    assert COL.web_domain("foo.co.uk") == "foo.co.uk" and COL.web_domain("https://a.b.foo.co.uk/") == "foo.co.uk"
    assert COL.web_domain("https://linktr.ee/vibes") == "linktr.ee"
    for v in ("https://x.com/foo", "https://t.me/foo", "https://pump.fun/coin/abc", "N/A", "localhost", "",
              "https://10.0.0.1/x", "javascript:alert(1)"):
        assert COL.web_domain(v) is None, v


def test_the_metadata_keeps_the_flags_and_the_normalised_links_only():
    doc = {"name": "vibes tcg", "symbol": "TCG", "description": "secret text", "image": "https://ipfs.io/ipfs/i",
           "twitter": "https://x.com/MissionGains/status/2114835278720548932", "website": "https://linktr.ee/vibes",
           "extensions": {"telegram": "https://t.me/VibesTCG"}, "createdOn": "https://pump.fun"}
    got = COL.meta_flags(doc)
    assert got == {"ok": True, "twitter": True, "telegram": True, "website": True, "desc_len": 11, "image": True,
                   "x_kind": "status", "x_handle": "missiongains", "x_tweet": "2114835278720548932",
                   "tg_handle": "vibestcg", "web_domain": "linktr.ee"}
    assert set(got) <= set(store.SCHEMAS["meta"].names) | {"ok"}
    assert COL.meta_flags({})["x_kind"] == "none" and COL.meta_flags([1]) == {"ok": False}
    assert COL.META_MAX_BYTES == 64_000 and COL.META_PER_S == 1.0          # the fetch's limits stay


def test_the_store_writes_and_widens_the_new_columns(tmp_path):
    w = store.Writer(tmp_path)
    w.add("meta", {"t": T0, "mint": MINT, **COL.meta_flags({"twitter": "@Foo", "description": "x"})})
    w.flush(T0)
    df = store.read("meta", [store.day_of(T0)], tmp_path)
    assert df["x_kind"].to_list() == ["profile"] and df["x_handle"].to_list() == ["foo"]
    assert df["x_tweet"].to_list() == [None] and "description" not in df.columns


# ---------------------------------------------------------------- the tracker

def tok(mint, t0, creator="c1", meta=None, meta_t=None, symbol="ABC", name="Abc"):
    return SimpleNamespace(mint=mint, t0=t0, creator=creator, meta=meta, meta_t=meta_t, symbol=symbol, name=name)


def flags(handle=None, tweet=None, tg=None, dom=None, kind=None):
    return {"ok": True, "x_kind": kind or ("status" if tweet else "profile" if handle else "none"), "x_handle": handle,
            "x_tweet": tweet, "tg_handle": tg, "web_domain": dom}


def test_the_counts_take_earlier_coins_only_and_migrations_before_t():
    tr = SO.Tracker()
    tr.meta("a", T0, "c1", flags("foo", "111", "tg1", "site.com"))
    tr.meta("b", T0 + 5 * MIN, "c2", flags("foo", "111"))
    tr.meta("later", T0 + 30 * MIN, "c1", flags("foo", "111", "tg1"))         # created after the coin scored
    tr.migrated("a", T0 + 8 * MIN)
    me = tok("me", T0 + 20 * MIN, "c1", flags("foo", "111", "tg1", "site.com"), T0 + 20 * MIN + 2_000, symbol="FOO")
    tr.meta("me", me.t0, me.creator, me.meta)
    f = tr.features(me, T0 + 40 * MIN)
    assert (f["soc_known"], f["soc_x_kind"]) == (1.0, float(SO.X_KINDS.index("status")))
    assert (f["soc_handle_prev"], f["soc_handle_mig"], f["soc_tweet_prev"], f["soc_tweet_mig"]) == (2, 1, 2, 1)
    assert (f["soc_tg_prev"], f["soc_tg_mig"], f["soc_dom_prev"], f["soc_dom_mig"]) == (1, 1, 1, 1)
    assert f["soc_creator_handle"] == 1 and f["soc_handle_is_name"] == 1.0
    assert (f["soc_burst10"], f["soc_burst60"]) == (0, 2)                    # b 15 min before, a 20 min before
    tr.migrated("later", T0 + 41 * MIN)                                     # a later coin's migration does not count
    assert tr.features(me, T0 + 42 * MIN)["soc_handle_mig"] == 1


def test_no_metadata_no_handle_and_a_meta_not_known_yet():
    tr = SO.Tracker()
    t = tok("x", T0)
    f = tr.features(t, T0 + MIN)
    assert f["soc_known"] == 0.0 and all(math.isnan(f[k]) for k in SO.SOCIAL_FEATURES if k != "soc_known")
    t = tok("x", T0, meta=flags(), meta_t=T0 + 5_000)
    assert tr.features(t, T0 + 4_000)["soc_known"] == 0.0                    # received after t
    f = tr.features(t, T0 + 6_000)
    assert f["soc_known"] == 1 and f["soc_x_kind"] == 0 and f["soc_handle_prev"] == 0 and f["soc_burst60"] == 0
    assert math.isnan(f["soc_handle_is_name"])
    t = tok("y", T0, meta={"ok": False}, meta_t=T0)
    assert tr.features(t, T0 + MIN)["soc_known"] == 0.0


def test_a_coin_is_registered_once_and_old_coins_are_forgotten():
    tr = SO.Tracker(keep_ms=60 * MIN)
    tr.meta("a", T0, "c", flags("foo"))
    tr.meta("a", T0, "c", flags("bar"))
    tr.meta("f", T0, "c", {"ok": False, "x_handle": "foo"})
    assert list(tr.of) == ["a"] and ("handle", "bar") not in tr.keys
    tr.migrated("a", T0 + MIN)
    tr.meta("b", T0 + 30 * MIN, "c", flags("foo"))
    assert tr.keys[("handle", "foo")].n_mig == 1
    tr.meta("c", T0 + 61 * MIN, "c", flags("baz"))
    assert "a" not in tr.of and tr.keys[("handle", "foo")].n_mig == 0 and len(tr.keys[("handle", "foo")].recs) == 1


def social_market(n=24, every_ms=1_500_000) -> list[tuple[str, dict]]:
    """The Y9 synthetic market with a metadata row 3 s after each creation: every third coin on one shared handle, every
    fourth on one tweet, the rest on their own handle; every fifth without metadata."""
    ev = market(n=n, every_ms=every_ms)
    out = list(ev)
    for k, (_, r) in enumerate([e for e in ev if e[0] == "creates"]):
        if k % 5 == 4:
            continue
        h = "shared" if k % 3 == 0 else f"h{k}"
        tw = "777" if k % 4 == 0 else None
        out.append(("meta", {"t": r["t"] + 3_000, "mint": r["mint"], "ok": True, "twitter": True, "telegram": False,
                             "website": k % 2 == 1, "desc_len": 5, "image": True,
                             **flags(h, tw, None, "site.com" if k % 2 else None)}))
    order = {"creates": 0, "trades": 1, "other": 2, "amm": 3, "meta": 4}
    return sorted(out, key=lambda e: (e[1]["t"], order[e[0]]))


def test_no_look_ahead_the_features_at_t_equal_a_record_cut_at_t():
    ev = social_market()
    eng = sim.Engine([], costs=Fixed(), social=True)
    for table, row in ev:
        sim.feed_row(eng, table, full(table, row))
    mints = [r["mint"] for t, r in ev if t == "creates"]
    for i in (6, 12, 18):
        m = mints[i]
        tk = eng.tokens.get(m)
        if tk is None:
            continue
        for at in (tk.t0 + 2_000, tk.t0 + 900_000 - 1, tk.t0 + 900_000 + 60_000):
            cut = sim.Engine([], costs=Fixed(), social=True)
            for table, row in ev:
                if row["t"] >= at:
                    break
                sim.feed_row(cut, table, full(table, row))
            cut.advance(at)
            assert cut.social.features(cut.tokens[m], at) == pytest.approx(
                _frozen(eng, ev, at).features(tk, at), nan_ok=True)


def _frozen(eng, ev, at):
    """The full engine's tracker seen at `at`: the coins whose meta came after it and the migrations after it
    removed (what a decision at `at` may not know)."""
    meta_t = {r["mint"]: r["t"] for t, r in ev if t == "meta"}
    tr = SO.Tracker()
    for mint, (rec, links) in sorted(eng.social.of.items(), key=lambda x: x[1][0].t0):
        if meta_t[mint] >= at:
            continue
        tr.meta(mint, rec.t0, rec.creator, {"ok": True, **{SO.COLS[k]: v for k, v in links.items()}})
        if rec.mig_t is not None and rec.mig_t < at:
            tr.migrated(mint, rec.mig_t)
    return tr


def test_the_engine_feeds_the_tracker_and_warm_reads_the_record(tmp_path):
    ev = social_market()
    w = store.Writer(tmp_path)
    for table, row in ev:
        w.add(table, row)
    w.flush(T0)
    days = store.days(tmp_path)
    eng = sim.Engine([], costs=Fixed(), social=True)
    sim.replay(days, eng, tmp_path)
    tr = SO.warm(days, tmp_path)
    assert set(tr.of) == set(eng.social.of) and len(tr.of) == sum(1 for t, r in ev if t == "meta")
    assert {m: r.mig_t for m, (r, _) in tr.of.items()} == {m: r.mig_t for m, (r, _) in eng.social.of.items()}
    assert {k: len(v.recs) for k, v in tr.keys.items()} == {k: len(v.recs) for k, v in eng.social.keys.items()}
    assert tr.keys[("handle", "shared")].n_mig == eng.social.keys[("handle", "shared")].n_mig > 0
    assert SO.warm([], tmp_path).of == {} and sim.Engine([], social=tr).social is tr
    assert sim.Engine([]).social is None                                    # the live service's engine


# ---------------------------------------------------------------- the books and the rule

def test_the_y14_strategies_and_trials_are_what_the_prereg_says():
    names = [s.name for s in P.STRATEGIES]
    assert names[-2:] == Y14_NAMES and [n for _, n in Y14.VARIANTS][3:] == Y14_NAMES
    a2, b1 = P.BY_NAME["P_pool5_top30t"], P.BY_NAME["P_pool5_top30s"]
    assert (b1.exits, b1.p, b1.stake_sol, b1.family, b1.entry) == (a2.exits, a2.p, 0.1, "E", "migration")
    assert b1.flt == {"select": {"win5s": ("top", 0.3)}}
    w, b2 = P.BY_NAME["P_pool0_wait"], P.BY_NAME["P_pool0_wait_social"]
    assert (b2.exits, b2.p, b2.stake_sol, b2.flt) == (w.exits, w.p, 0.1, {"social": "Y14"})
    assert P.SOCIAL_RULE == ((("soc_handle_prev", "min", 2), ("soc_handle_mig", "eq", 0)),
                             (("soc_tg_prev", "min", 2), ("soc_tg_mig", "eq", 0)),
                             (("soc_dom_prev", "min", 2), ("soc_dom_mig", "eq", 0)),
                             (("soc_creator_handle", "min", 1),), (("soc_burst10", "min", 10),))
    for s in OLD:
        assert "social" not in s.flt and not any(k.endswith("s") for k in (s.flt.get("select") or {}))
    assert S.SOCIAL_Y14_TRIALS == 4 == len(Y14.JUDGED) * len(Y14.LIMITS)
    assert Y14.JUDGED == {"B1": "A2", "B2": "W0"} and Y14.LIMITS == {"L25": Y14.LIMITS["L25"],
                                                                    "L100": Y14.LIMITS["L100"]}
    strats, costs = Y14.books()
    assert len(strats) == len(costs) == 10 and {sim.base_name(s) for s, _ in strats} == {"P_pool0"}


def social_pool(handle_prev=0, handle_mig=0, meta=True, creator_reuse=False):
    eng = sim.Engine([], costs=Fixed(), strategies=[P.BY_NAME["P_pool0_wait_social"]], select=True, social=True)
    for i in range(handle_prev):
        m = key(100 + i)
        eng.social.meta(m, T0 - 3_600_000 + i, key(2) if creator_reuse else key(150 + i), flags("dup"))
        if i < handle_mig:
            eng.social.migrated(m, T0 - 1_000_000)
    p = Pool(eng)
    if meta:
        eng.meta(T0 - 100_000, MINT, flags("dup"))
    return eng, p


def test_the_social_book_skips_recycled_handles_and_coins_without_metadata():
    for kw, why in (({}, None), ({"handle_prev": 3}, "social rule"), ({"handle_prev": 3, "handle_mig": 1}, None),
                    ({"handle_prev": 1, "creator_reuse": True}, "social rule"), ({"meta": False}, "no social data")):
        eng, p = social_pool(**kw)
        p.to(T0 + 6_000, 1.5)
        eng.advance(T0 + 400_000)
        if why is None:
            assert [t["rule"] for t in eng.closed] == ["P_pool0_wait_social"], (kw, eng.skipped)
        else:
            assert not eng.closed and eng.skipped[("P_pool0_wait_social", why)] == 1, (kw, eng.skipped)
    off = sim.Engine([], costs=Fixed(), strategies=[P.BY_NAME["P_pool0_wait_social"]], select=True)
    Pool(off)
    off.advance(T0 + 400_000)
    assert off.skipped[("P_pool0_wait_social", "no social data")] == 1


def test_the_rule_clauses_need_every_condition():
    pipe = SimpleNamespace(eng=SimpleNamespace(social=SimpleNamespace(features=lambda tk, t: dict(
        f, soc_known=1.0))))
    f = dict.fromkeys(SO.SOCIAL_FEATURES, 0.0)
    ok = lambda: P.Pipeline.social_ok(pipe, "Y14", None, 0)[0]             # noqa: E731
    assert ok() is True
    f.update(soc_dom_prev=5.0, soc_dom_mig=1.0)
    assert ok() is True
    f.update(soc_dom_mig=0.0)
    assert ok() is False
    f.update(soc_dom_prev=0.0, soc_burst10=9.0)
    assert ok() is True
    f.update(soc_burst10=10.0)
    assert ok() is False
    f.update(soc_burst10=math.nan)
    assert ok() is True


def test_the_social_select_filter_uses_the_y14_model():
    ms = stub_models()
    ms["sel_policy"]["win5s"] = {"0.3": 0.5}
    eng = sim.Engine([], costs=Fixed(), strategies=[P.BY_NAME["P_pool5_top30s"]], models=ms, select=True,
                     trend=True, social=True)
    Pool(eng).to(T0 + 6_000, 1.5)
    eng.advance(T0 + 400_000)
    assert [t["rule"] for t in eng.closed] == ["P_pool5_top30s"]
    assert ms["sel_win5s"].features == SF.SEL5 + TF.TREND_FEATURES + SO.SOCIAL_FEATURES
    del ms["sel_win5s"]
    eng = sim.Engine([], costs=Fixed(), strategies=[P.BY_NAME["P_pool5_top30s"]], models=ms, select=True,
                     trend=True, social=True)
    Pool(eng)
    eng.advance(T0 + 400_000)
    assert eng.skipped[("P_pool5_top30s", "no model")] == 1


# ---------------------------------------------------------------- every strategy before Y14

def test_every_strategy_before_y14_trades_exactly_as_before(tmp_path, monkeypatch):
    """One shared paper book of every strategy before Y14 on a synthetic record with metadata rows, without the social
    tracker and the Y14 books, and with them (the Y14 books trading): the closed trades, failed buys and skips of the
    old strategies are the same field for field (the pid aside), and so are the select label rows' old columns."""
    from test_pumpfun_select_y9 import write
    write(tmp_path, social_market())
    monkeypatch.setattr(store, "base", lambda: tmp_path)
    days = store.days(tmp_path)
    ms = stub_models()
    ms["sel_policy"].update({k: {"0.3": 0.5} for k in ("win0t", "win5t", "win5s")})

    def run(new: bool):
        eng = sim.Engine(S.RULES, costs=Fixed(), strategies=P.STRATEGIES if new else OLD, models=ms, select=True,
                         trend=True, social=new)
        lab = eng.add_pipe(SF.LabelPipe(eng))
        sim.replay(days, eng, tmp_path)
        return eng, lab
    (a, la), (b, lb) = run(False), run(True)
    old = {s.name for s in OLD} | {r.name for r in S.RULES}

    def strip(xs):
        out = [{k: v for k, v in x.items() if k != "pid"} for x in xs if x["rule"] in old]
        return sorted(out, key=lambda x: (x["rule"], x["mint"], x["signal_ms"], x.get("exit_ms") or x.get("land_ms")))
    assert strip(a.closed) and strip(a.closed) == strip(b.closed) and strip(a.failed) == strip(b.failed)
    assert {k: v for k, v in a.skipped.items() if k[0] in old} == {k: v for k, v in b.skipped.items() if k[0] in old}
    assert {t["rule"] for t in b.closed} >= set(Y14_NAMES)                   # the Y14 books did trade next to them
    ta, tb = la.table(), lb.table()
    cols = [c for c in SF.ROW_COLS if c not in SO.SOCIAL_FEATURES]
    assert all(np.array_equal(ta[c], tb[c], equal_nan=True) for c in cols)
    assert np.isnan(ta["soc_known"]).all() and set(np.unique(tb["soc_known"])) <= {0.0, 1.0}
    assert np.nansum(tb["soc_handle_prev"]) > 0


# ---------------------------------------------------------------- the models

def social_table(n=900, seed=5, known=True) -> dict:
    from test_pumpfun_select_y9 import table
    tb = table(n=n, seed=seed)
    rng = np.random.default_rng(seed)
    tb["tr_rank_5m"] = rng.integers(1, 30, n).astype(float)
    half = np.arange(n) >= n // 3                                            # the first third before Y14
    tb["soc_known"] = np.where(half, 1.0 if known else 0.0, np.nan)
    tb["soc_handle_prev"] = np.where(half, rng.integers(0, 4, n), np.nan).astype(float)
    return tb


def test_the_social_twins_wait_for_rows_with_metadata_and_train_on_them_only():
    tb = social_table(known=False)
    ms = SM.train(tb)
    assert all(ms[f"sel_{k}"].booster is None and ms["sel_rows"][k] == 0 for k in SM.SOCIAL_LABELS)
    assert all(ms[f"sel_{k}"].booster is not None for k in SM.Y9_LABELS + SM.TREND_LABELS)
    tb = social_table()
    ms = SM.train(tb)
    assert all(ms[f"sel_{k}"].booster is not None for k in SM.LABELS)
    assert ms["sel_rows"]["win0s"] == len(SM.rows_for(tb, "win0s")["t"]) < ms["sel_rows"]["win0t"]
    assert np.isfinite(SM.rows_for(tb, "win5s")["soc_known"]).all()
    assert ms["sel_win0s"].features == SF.SEL0 + TF.TREND_FEATURES + SO.SOCIAL_FEATURES
    assert ms["sel_win0t"].features == SF.SEL0 + TF.TREND_FEATURES                # the old ones as they are
    assert ms["sel_win0"].features == SF.SEL0
    wf = SM.walk_forward(Y14.social_rows(tb))
    mc = Y14.model_compare(wf)
    assert [(r["y10"], r["y14"]) for r in mc] == list(Y14.MODEL_PAIRS) and all(r["n"] == r["n_y14"] for r in mc)
    assert not SM.has_social({k: v for k, v in tb.items() if k != "soc_known"})


def test_the_early_social_model_is_et_s_fit_on_the_rows_with_the_tracker():
    from lab.pumpfun_rt import early as E
    rng = np.random.default_rng(2)
    n = 1500
    fr = {c: np.full(n, np.nan) for c in E.ROW_META + XP.social_features() + E.ROW_LABELS}
    fr["t"] = np.sort(rng.integers(T0, T0 + 3 * 86_400_000, n)).astype(float)
    x = rng.normal(size=n)
    fr["buys_5s"], fr["tr_rank_5m"] = x, rng.normal(size=n)
    fr["alive5m"] = (x + 0.3 * rng.normal(size=n) > 0).astype(float)
    assert not XP.has_social(fr)
    fr["soc_known"][300:] = 1.0
    fr["soc_handle_prev"][300:] = rng.integers(0, 3, n - 300)
    assert XP.has_social(fr)
    m = XP.fit_social(fr, "alive5m", until_ms=fr["t"][1400])
    assert m.booster is not None and m.features == XP.social_features()
    late = fr["t"] + 300_000 + XP.EMBARGO_MS >= fr["t"][1400]
    assert m.base == pytest.approx(fr["alive5m"][300:][~late[300:]].mean())
    assert {"es_alive5m", "es_peak3x"} <= set(XP.LIVE_NAMES)


# ---------------------------------------------------------------- the run

def test_the_cutoff_is_seven_full_days_after_the_first_day_with_the_links(tmp_path):
    assert Y14.cutoff_ms(tmp_path) is None
    w = store.Writer(tmp_path)
    w.add("meta", {"t": T0, "mint": MINT, "ok": True})                       # flags only: before Y14
    w.add("meta", {"t": T0 + 86_400_000, "mint": key(9), **COL.meta_flags({"twitter": "@a"})})
    w.add("trades", {"t": T0, "mint": MINT})
    w.add("trades", {"t": T0 + 86_400_000, "mint": MINT})
    w.flush(T0)
    d1 = store.day_of(T0 + 86_400_000)
    assert Y14.first_social_day(tmp_path) == d1
    assert Y14.cutoff_ms(tmp_path) == SM.day_start(d1) + 8 * 86_400_000


def test_evaluate_judges_each_book_against_its_counterpart():
    def e(t, ret, mint):
        return {"mint": mint, "signal_ms": t, "real_ms": t + 60_000, "ret": ret, "pnl_sol": ret * 0.1, "failed": False,
                "exit_why": "time", "gapped": False, "hold_s": 60.0, "legs": 1, "peak": None, "peak_held": None}
    split = T0 + 86_400_000
    entries, skips = {}, {}
    for k in Y14.LIMITS:
        for x, name in Y14.VARIANTS:
            ret = {"B1": 0.10, "B2": -0.05}.get(x, 0.0)
            entries[f"{name}@{k}"] = ([e(T0 + h * 3_600_000, ret, f"i{h}") for h in range(5)]
                                      + [e(split + h * 3_600_000 + i, ret + 0.01 * (i - 1), f"{x}{h}{i}")
                                         for h in range(12) for i in range(3)])
            skips[f"{name}@{k}"] = [(split + 1, "no social data")] if x == "B2" else []
    ev = Y14.evaluate({"split_ms": split, "entries": entries, "skips": skips})
    assert ev["better"] == {"B1": True, "B2": False}
    assert ev["table"]["L25"]["B2"]["skipped"] == {"no social data": 1}
    assert ev["in_sample"]["L25"]["B1"]["n"] == 5 and ev["table"]["L25"]["B1"]["n"] == 36
    md = Y14._table(ev, "L25")
    assert any(r.startswith("| B1 vs A2 |") and "| yes |" in r for r in md)
    assert Y14.oos_day(["d1", "d2"], {"d1": {"models": ["win5t"]}, "d2": {"models": ["win5t", "win5s"]}}) == "d2"


def test_coverage_and_the_improves_rule():
    tb = social_table()
    tb["soc_x_kind"] = np.where(np.isfinite(tb["soc_known"]), 1.0, np.nan)
    cov = Y14.coverage(tb)
    assert cov["rows"] == cov["known"] == 600 and cov["x_kind"] == {"profile": 600}
    wf = {"win0t": {"n": 100, "model": {"auc": 0.60, "brier_skill": 0.01}},
          "win0s": {"n": 100, "model": {"auc": 0.63, "brier_skill": 0.02}},
          "rug0t": {"n": 100, "model": {"auc": 0.60, "brier_skill": 0.02}},
          "rug0s": {"n": 100, "model": {"auc": 0.65, "brier_skill": 0.01}}}
    mc = {r["y14"]: r["improves"] for r in Y14.model_compare(wf)}
    assert mc == {"win0s": True, "rug0s": False, "win5s": False, "rug5s": False}
    assert Y14.social_rows({"t": np.zeros(3)})["t"].shape == (0,)
