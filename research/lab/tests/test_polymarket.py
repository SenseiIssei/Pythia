"""Polymarket (Y4): the client, the market record, the sample, point-in-time features, the paper
book's rule, the forecaster's prompt and ledger, forward scoring, the cards. No network.

Run from research/lab:  python -m pytest tests/test_polymarket.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from lab.polymarket import api, book as B, collect, forecast as F, markets as M, panel as P, store

DAY = 86_400


@pytest.fixture()
def pmdir(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHIA_PM_DIR", str(tmp_path / "pm"))
    return tmp_path / "pm"


def gamma_market(**kw) -> dict:
    m = {"id": "1", "question": "Will X happen by June 30?", "conditionId": "0xabc", "slug": "x",
         "endDate": "2026-06-30T00:00:00Z", "closedTime": "2026-06-30 12:00:00+00", "createdAt": "2026-05-01T00:00:00Z",
         "outcomes": '["Yes", "No"]', "outcomePrices": '["1", "0"]', "clobTokenIds": '["111", "222"]',
         "closed": True, "volumeNum": 5000, "liquidityNum": 2000, "tags": [{"label": "Politics"}],
         "events": [{"id": "9", "slug": "ev", "title": "Event"}], "negRisk": False, "description": "Rules."}
    m.update(kw)
    return m


# ---------------------------------------------------------------- paper only

def test_the_package_has_no_wallet_key_or_order_path():
    src = Path(__file__).resolve().parents[1] / "lab" / "polymarket"
    banned = re.compile(r"private[_ ]?key|seed phrase|mnemonic|eth_account|web3|sign_typed|/order\b|post_order|"
                        r"create_order|py_clob_client|POLY_API_KEY", re.I)
    for f in src.glob("*.py"):
        assert not banned.search(f.read_text(encoding="utf-8")), f.name


# ---------------------------------------------------------------- the client

def test_client_retries_429_and_5xx_and_not_a_bad_request():
    calls = []

    def fetch(method, url, body, timeout):
        calls.append(url)
        return (429, b"slow down") if len(calls) == 1 else (502, b"") if len(calls) == 2 else (200, b'{"ok": 1}')

    c = api.Client(rps=1000, fetch=fetch, sleep=lambda s: None)
    assert c.get("https://x/y", {"a": 1}) == {"ok": 1}
    assert len(calls) == 3 and calls[0].endswith("?a=1")
    bad = api.Client(rps=1000, fetch=lambda *a: (422, b"order fields are not valid"), sleep=lambda s: None)
    with pytest.raises(api.ApiError) as e:
        bad.get("https://x/y")
    assert e.value.status == 422


def test_keyset_paging_follows_the_cursor_and_history_parses():
    pages = {None: {"markets": [{"id": "1"}, {"id": "2"}], "next_cursor": "c1"},
             "c1": {"markets": [{"id": "3"}]}}

    def fetch(method, url, body, timeout):
        if "prices-history" in url:
            return 200, json.dumps({"history": [{"t": 1, "p": 0.4}, {"t": 2, "p": "0.5"}, {"bad": 1}]}).encode()
        cur = re.search(r"after_cursor=([^&]+)", url)
        return 200, json.dumps(pages[cur.group(1) if cur else None]).encode()

    c = api.Client(rps=1000, fetch=fetch, sleep=lambda s: None)
    assert [m["id"] for m in c.markets(True)] == ["1", "2", "3"]
    assert c.history("111") == [(1, 0.4), (2, 0.5)]


def test_bucket_limits_the_rate():
    now = [0.0]
    slept = []

    def sleep(s):
        slept.append(s)
        now[0] += s

    b = api.Bucket(2.0, burst=1.0, clock=lambda: now[0], sleep=sleep)
    for _ in range(5):
        b.take()
    assert now[0] == pytest.approx(2.0, abs=1e-6)  # four waits of half a second


# ---------------------------------------------------------------- the record

def test_record_category_kind_fees_and_outcome():
    r = M.record(gamma_market())
    assert r["category"] == "politics" and r["kind"] == "event" and r["outcome"] == 1.0
    assert r["yes_token"] == "111" and r["no_token"] == "222" and r["event_id"] == "9"
    assert r["fee_rate"] == 0.04 and r["fee_source"] == "table"
    assert r["closed_ms"] == M.parse_ms("2026-06-30T12:00:00Z")
    assert M.record(gamma_market(outcomePrices='["0", "1"]'))["outcome"] == 0.0
    assert M.record(gamma_market(outcomePrices='["0.5", "0.5"]'))["outcome"] == 0.5
    assert M.record(gamma_market(closed=False))["outcome"] is None
    sports = M.record(gamma_market(tags=[{"label": "Politics"}, {"label": "NBA"}], gameStartTime="2026-06-01 19:00:00+00"))
    assert sports["category"] == "sports" and sports["kind"] == "game"
    old = M.record(gamma_market(tags=[{"label": "All"}], question="Will Bitcoin close above $50k?"))
    assert old["category"] == "crypto"
    ud = M.record(gamma_market(question="Bitcoin Up or Down - June 1, 3PM ET", tags=[{"label": "Crypto"}]))
    assert ud["kind"] == "updown"
    geo = M.record(gamma_market(tags=[{"label": "Geopolitics"}],
                                feeSchedule={"exponent": 1, "rate": 0, "takerOnly": True}))
    assert geo["category"] == "geopolitics" and geo["fee_rate"] == 0.0 and geo["fee_source"] == "market"


def test_taker_fee_matches_the_published_examples():
    assert M.taker_fee(100, 0.5, 0.07) == pytest.approx(1.75)
    assert M.taker_fee(100, 0.3, 0.07) == pytest.approx(1.47)
    assert M.taker_fee(100, 0.5, 0.05) == pytest.approx(1.25)
    assert M.taker_fee(100, 0.5, 0.04) == pytest.approx(1.00)
    assert M.taker_fee(100, 0.3, 0.05) == M.taker_fee(100, 0.7, 0.05)
    assert M.taker_fee(100, 0.5, 0.0) == 0.0


# ---------------------------------------------------------------- the sample

def test_sample_is_deterministic_capped_and_ignores_volume_and_outcome():
    recs = [{"id": str(i), "category": "politics", "kind": "event", "outcome": float(i % 2), "yes_token": "t",
             "volume": float(i)} for i in range(1000)]
    recs += [{"id": "x", "category": "politics", "kind": "event", "outcome": 0.5, "yes_token": "t"}]
    a, ca = collect.sample(recs, {"event": 50})
    b, _ = collect.sample(list(reversed(recs)), {"event": 50})
    assert [r["id"] for r in a] == [r["id"] for r in b] and len(a) == 50
    assert ca["politics|event"] == {"all": 1001, "resolved": 1000, "taken": 50}
    assert "x" not in {r["id"] for r in a}
    # changing volumes or outcomes does not change which markets are taken
    c, _ = collect.sample([{**r, "volume": -r.get("volume", 0), "outcome": 1.0 - r["outcome"]
                            if r["outcome"] in (0.0, 1.0) else 0.5} for r in recs], {"event": 50})
    assert {r["id"] for r in c} == {r["id"] for r in a}


def test_month_windows_run_past_now_for_early_closes():
    from datetime import datetime, timezone
    w = collect.month_windows("2026-09", datetime(2026, 10, 21, tzinfo=timezone.utc), ahead_months=2)
    assert [x[0] for x in w] == ["2026-09", "2026-10", "2026-11", "2026-12"]
    assert w[0][1] == "2026-09-01T00:00:00Z" and w[0][2] == "2026-10-01T00:00:00Z"


# ---------------------------------------------------------------- the panel

def _rec(**kw):
    r = {"id": "m1", "event_id": "e1", "category": "politics", "kind": "event", "neg_risk": False,
         "created_ms": 0, "end_ms": 30 * DAY * 1000, "closed_ms": 30 * DAY * 1000, "outcome": 1.0, "volume": 1.0}
    r.update(kw)
    return r


def test_states_use_only_the_past():
    t = np.arange(0, 30 * DAY, 6 * 3600, dtype=np.int64)
    p = np.linspace(0.2, 0.9, len(t))
    rows = P.states_for(_rec(), t, p)
    assert rows and all(r["t_s"] < 30 * DAY for r in rows)
    # change every price after day 10: the states at or before day 10 must not move
    p2 = p.copy()
    p2[t > 10 * DAY] = 0.01
    rows2 = P.states_for(_rec(), t, p2)
    early = [(a, b) for a, b in zip(rows, rows2) if a["t_s"] <= 10 * DAY]
    same = lambda x, y: x == y or (isinstance(x, float) and np.isnan(x) and np.isnan(y))  # noqa: E731
    assert early and all(same(a[k], b[k]) for a, b in early for k in a)
    r = next(x for x in rows if x["t_s"] == 8 * DAY)
    assert r["p"] == pytest.approx(p[t <= 8 * DAY][-1])
    assert r["days_to_end"] == pytest.approx(22.0) and r["days_since"] == pytest.approx(8.0)
    assert r["hi"] == pytest.approx(r["p"]) and r["lo"] == pytest.approx(0.2)


def test_stale_prices_make_no_state_and_short_markets_get_hourly_states():
    t = np.array([0, 3600], dtype=np.int64)
    rows = P.states_for(_rec(), t, np.array([0.5, 0.5]))
    assert len(rows) == 1  # day 1 only; after that the last price is more than 36 hours old
    short = _rec(end_ms=20 * 3600 * 1000, closed_ms=20 * 3600 * 1000)
    ts = np.arange(0, 20 * 3600, 600, dtype=np.int64)
    rows = P.states_for(short, ts, np.full(len(ts), 0.4))
    assert len(rows) >= 15 and all(r["t_s"] % 3600 == 0 for r in rows)


def test_live_features_match_the_panel_at_the_same_time():
    t = np.arange(0, 20 * DAY, DAY, dtype=np.int64)
    p = np.linspace(0.3, 0.6, len(t))
    rows = P.states_for(_rec(), t, p)
    r = next(x for x in rows if x["t_s"] == 12 * DAY)
    live = P.live_features(_rec(), t, p, 12 * DAY, r["p"])
    for k in ("p", "logit_p", "days_to_end", "days_since", "chg_1d", "chg_7d", "vol_7d", "hi", "lo"):
        assert live[k] == pytest.approx(r[k], nan_ok=True), k


# ---------------------------------------------------------------- the paper book

def test_edge_kelly_and_walk():
    assert B.edge(0.6, 0.5, 0.04) == pytest.approx(0.6 - 0.5 - 0.01)
    assert B.kelly_fraction(0.6, 0.5) == pytest.approx(0.25 * 0.2)
    f = B.walk([(0.52, 100), (0.50, 100), (0.58, 1000)], q=0.6, margin=0.03, budget=10_000, rate=0.0)
    assert f["shares"] == pytest.approx(200) and f["levels"] == 2  # 0.58 leaves no margin
    f = B.walk([(0.50, 1000)], q=0.6, margin=0.03, budget=51, rate=0.04)
    assert f["cost"] + f["fee"] == pytest.approx(51)


def market(i="m1", **kw):
    m = {"id": i, "event_id": "e1", "category": "politics", "kind": "event", "end_ms": 10 * DAY * 1000,
         "fee_rate": 0.04, "fee_exponent": 1.0, "question": "Q?"}
    m.update(kw)
    return m


def test_book_enters_the_better_side_with_caps_and_settles():
    bk = B.Book("t", 0.03)
    f = bk.consider(market(), 0.2, 0, [(0.30, 1e6)], [(0.72, 1e6)])
    assert f and f["side"] == "no"  # 0.8 vs 0.72 beats 0.2 vs 0.30
    assert f["usd"] == pytest.approx(0.02 * B.START_USD, rel=1e-6)  # Kelly 0.25*0.08/0.28 = 7 % capped at 2 %
    assert bk.consider(market(), 0.2, 0, [(0.30, 1e6)], [(0.72, 1e6)]) is None  # one position per market
    # the event cap: 10 % of equity over at most 5 markets of one event
    n = sum(1 for k in range(2, 12) if bk.consider(market(f"m{k}"), 0.2, 0, [(0.30, 1e6)], [(0.72, 1e6)]))
    assert n == 4
    rec = bk.settle("m1", 0.0, 1)
    assert rec["won"] and rec["payout"] == pytest.approx(rec["shares"])
    rec = bk.settle("m2", 1.0, 1)
    assert not rec["won"] and rec["payout"] == 0.0


def test_book_refuses_extremes_far_ends_updown_and_small_edges():
    bk = B.Book("t", 0.03)
    assert bk.consider(market(), 0.99, 0, [(0.98, 1e6)], [(0.03, 1e6)]) is None   # YES ask above 97 cents
    assert bk.consider(market(end_ms=100 * DAY * 1000), 0.9, 0, [(0.5, 1e6)], [(0.6, 1e6)]) is None
    assert bk.consider(market(kind="updown"), 0.9, 0, [(0.5, 1e6)], [(0.6, 1e6)]) is None
    assert bk.consider(market(), 0.53, 0, [(0.5, 1e6)], [(0.6, 1e6)]) is None    # 3 points minus the fee
    assert bk.consider(market(), 0.9, 0, [(0.5, 3)], [(0.6, 1e6)]) is None        # under 5 shares of depth


def test_book_round_trips_through_json(pmdir):
    bk = B.Book("pm_model", 0.03)
    bk.consider(market(), 0.2, 0, [(0.30, 1e6)], [(0.72, 1e6)])
    B.save(bk)
    b2 = B.load("pm_model", 0.03)
    assert b2.cash == pytest.approx(bk.cash) and set(b2.positions) == {"m1"} and "m1" in b2.traded


# ---------------------------------------------------------------- the forecaster

def live_frame(ts):
    rows = []
    for i, (cat, days, ask) in enumerate([("politics", 10, 0.4), ("sports", 10, 0.4), ("politics", 90, 0.4),
                                          ("geopolitics", 5, 0.99), ("politics", 3, 0.2)]):
        rows.append({"id": f"m{i}", "question": f"Question {i}?", "category": cat, "kind": "event",
                     "candidate": True, "end_ms": ts + days * DAY * 1000, "liquidity": 10_000.0,
                     "best_bid": ask - 0.02, "best_ask": ask, "last_price": ask - 0.01, "event_id": "e",
                     "event_title": "Event", "description": "Resolves Yes if it happens.\x07 Price 55c now!",
                     "outcome_a": "Yes", "outcome_b": "No", "ts_ms": ts})
    return pl.DataFrame(rows)


def test_selection_and_the_prompt_carries_no_price():
    ts = 1_800_000_000_000
    live = live_frame(ts)
    pick = F.select(live, None, ts, [])
    assert [r["id"] for r in pick] == ["m4", "m0"]  # politics and soonest first; not sports, not 90 days, not 99c
    text = F.prompt(pick, F.siblings(live), ts)
    for r in pick:
        assert str(r["best_ask"]) not in text and str(r["best_bid"]) not in text
    assert "\x07" not in text and "Other questions in this event" in text
    # a market forecast 3 days ago is not asked again; 8 days ago it is
    led = [{"market_id": "m0", "ts_ms": ts - 3 * DAY * 1000}]
    assert [r["id"] for r in F.select(live, None, ts, led)] == ["m4"]
    led = [{"market_id": "m0", "ts_ms": ts - 8 * DAY * 1000}]
    assert [r["id"] for r in F.select(live, None, ts, led)] == ["m4", "m0"]


def test_run_writes_the_ledger_and_drops_bad_answers(pmdir):
    ts = 1_800_000_000_000
    live = live_frame(ts)
    seen = {}

    def complete(job, system, user, max_tokens, **kw):
        seen.update(kw, user=user)
        return {"json": {"m0": {"p": 0.3, "conf": "medium", "stale": False, "why": "base rate"},
                         "m1": {"p": 1.7, "conf": "low", "stale": True, "why": "x"},
                         "m7": {"p": 0.5, "conf": "low", "stale": True, "why": "x"}},
                "model": "claude-sonnet-5-5", "costUsd": 0.002, "batchId": "b1"}

    res = F.run(live, None, ts=ts, complete=complete)
    assert res["written"] == 1 and seen["batch"] is True
    assert seen["schema"]["required"] == ["m0", "m1"] and "[m1] Question" in seen["user"]
    rows = store.read_jsonl(F.ledger_path())
    assert len(rows) == 1 and rows[0]["p_yes"] == 0.3 and rows[0]["ts_ms"] == ts and rows[0]["ask"] == 0.2
    assert rows[0]["mid"] == pytest.approx(0.19)
    # append only: a second run adds, never rewrites
    F.run(live, None, ts=ts + 8 * DAY * 1000, complete=complete)
    assert len(store.read_jsonl(F.ledger_path())) >= 2


# ---------------------------------------------------------------- forward scoring

def test_only_markets_resolved_after_the_forecast_count():
    from lab.polymarket import daily as D
    rows = [{"market_id": "a", "ts_ms": 100, "p_yes": 0.9, "mid": 0.5, "event_id": "a"},
            {"market_id": "a", "ts_ms": 200, "p_yes": 0.1, "mid": 0.5, "event_id": "a"},   # not the first
            {"market_id": "b", "ts_ms": 100, "p_yes": 0.9, "mid": 0.5, "event_id": "b"},   # resolved before
            {"market_id": "c", "ts_ms": 100, "p_yes": 0.2, "mid": 0.5, "event_id": "c"},   # 50-50
            {"market_id": "d", "ts_ms": 100, "p_yes": 0.2, "mid": 0.5, "event_id": "d"}]   # still open
    known = {"a": {"outcome": 1.0, "closed_ms": 500}, "b": {"outcome": 1.0, "closed_ms": 50},
             "c": {"outcome": 0.5, "closed_ms": 500}}
    s = D.forward_scores(rows, known, "p_yes")
    assert s["forecasts"] == 4 and s["resolved"] == 1
    assert s["brier_model"] == pytest.approx(0.01) and s["brier_market"] == pytest.approx(0.25)
    assert not s["passes"]  # one market is not evidence


def test_ensemble_waits_for_enough_resolved_forecasts():
    from lab.polymarket import daily as D
    assert D.ensemble([], {})["status"] == "waiting"


# ---------------------------------------------------------------- cards and feed

def fake_res():
    return {"ts_ms": 1_800_000_000_000, "day": "2027-01-15", "open_markets": 100, "candidates": 20, "eligible": 10,
            "q_model": 10, "q_claude": 4, "model_ready": True, "ai_cost_usd": 0.42,
            "daily": [{"day": "2027-01-15", "book": "pm_model", "equity": 10120.0, "cash": 9000, "invested": 1000,
                       "open": 3, "opened": 1, "settled": 1, "closed_total": 4, "won_total": 3, "realized": 150.0},
                      {"day": "2027-01-15", "book": "pm_claude", "equity": 9900.0, "cash": 9500, "invested": 500,
                       "open": 2, "opened": 1, "settled": 0, "closed_total": 0, "won_total": 0, "realized": 0.0}],
            "fills": [{"book": "pm_claude", "side": "yes", "ask": 0.31, "q": 0.55, "edge": 0.22, "usd": 150.0,
                       "market_id": "m1", "question": "Will it happen?", "ts_ms": 1, "end_ms": 1_801_000_000_000,
                       "category": "politics"}],
            "settled": [], "claude_score": {"forecasts": 40, "resolved": 3, "brier_model": 0.2, "brier_market": 0.15},
            "model_score": {"forecasts": 300, "resolved": 0}, "ensemble": {"status": "waiting", "needed": 200}}


def test_cards_in_both_languages():
    from lab.polymarket import card
    from test_i18n import no_english
    from lab.ops import notify
    for lang in ("en", "de"):
        txt = notify.render_post([card.daily_card(fake_res(), lang)], "telegram")
        assert "Polymarket" in txt and "—" not in txt
        al = notify.render_post([card.alert_card(fake_res()["fills"][0], lang)], "telegram")
        assert "22" in al
        if lang == "de":
            no_english(txt)
            no_english(al)
    assert len(card.big_edges(fake_res())) == 1


def test_feed_has_the_lab_header(pmdir, monkeypatch, tmp_path):
    from lab.polymarket import card
    d = card.report(fake_res(), write=False)
    for k in ("title", "updated_ms", "status", "headline", "items"):
        assert k in d
    assert d["status"] in ("ok", "watch", "bad") and all(i.get("label") for i in d["items"])


def test_prune_deletes_books_then_live_days_but_never_today(pmdir):
    for folder in ("books", "live"):
        for day in ("2026-10-01", "2026-10-02", "2026-10-03"):
            p = store.path(folder, f"{day}.parquet")
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"x" * 1000)
    store.path("forecasts").mkdir(parents=True)
    store.path("forecasts", "ledger.jsonl").write_bytes(b"y" * 1000)
    gone = store.prune(budget_bytes=4500, today="2026-10-03")
    assert gone == ["books/2026-10-01.parquet", "books/2026-10-02.parquet", "live/2026-10-01.parquet"]
    assert store.path("forecasts", "ledger.jsonl").exists()
