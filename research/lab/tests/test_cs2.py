"""W8, the CS2 skins pipeline: collector (against a mock fetch, no network),
fees, sales-window buckets, the bootstrap and walk-forward models on planted
signals, the paper portfolio, alerts and the hourly job end to end.

Run from research/lab:  python -m pytest tests/test_cs2.py
"""

from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta, timezone

import brotli
import numpy as np
import polars as pl
import pytest

from lab.collect import cs2 as collect
from lab.cs2 import book, market, model
from lab.cs2 import run as cs2run

NOW = int(datetime(2026, 10, 15, 12, 5, tzinfo=timezone.utc).timestamp() * 1000)


# ---------------------------------------------------------------- synthetic market

def sales_row(name: str, path: np.ndarray, per_day: int, rng) -> dict:
    """Skinport's sales/history row from a 90-day daily price path (index -1 is today)."""
    def win(days):
        p = path[-days:]
        sales = np.repeat(p, per_day) * np.exp(rng.normal(0, 0.01, len(p) * per_day))
        return {"min": float(sales.min()), "max": float(sales.max()), "avg": float(sales.mean()),
                "median": float(np.median(sales)), "volume": int(len(sales))}
    return {"market_hash_name": name, "version": None, "currency": "EUR",
            "last_24_hours": win(1), "last_7_days": win(7), "last_30_days": win(30), "last_90_days": win(90)}


def item_row(name: str, price: float, qty: int = 30) -> dict:
    return {"market_hash_name": name, "currency": "EUR", "suggested_price": price * 1.1, "min_price": round(price * 1.01, 2),
            "max_price": price * 3, "mean_price": price * 1.2, "median_price": price * 1.1, "quantity": qty,
            "created_at": 1_600_000_000, "updated_at": 1_700_000_000}


def momentum_market(n: int = 600, seed: int = 1):
    """Items whose 90-day paths keep their drift: momentum is planted."""
    rng = np.random.default_rng(seed)
    items, sales = [], []
    for i in range(n):
        name = f"AK-47 | Test {i} (Field-Tested)" if i % 3 else f"Sticker | Test {i}"
        drift = rng.normal(0, 0.004)
        path = 5 * np.exp(np.cumsum(drift + rng.normal(0, 0.003, 90)))
        sales.append(sales_row(name, path, 2 + i % 5, rng))
        items.append(item_row(name, float(path[-1])))
    return items, sales


# ---------------------------------------------------------------- fees and parsing

def test_steam_fee_round_trip():
    assert market.steam_buyer_pays(1.00) == pytest.approx(1.15)
    assert market.steam_seller_gets(1.15) == pytest.approx(1.00)
    assert market.steam_seller_gets(0.03) == pytest.approx(0.01)
    assert market.steam_seller_gets(0.02) == 0.0
    for b in (0.5, 1.37, 12.34, 250.0):
        s = market.steam_seller_gets(b)
        assert market.steam_buyer_pays(s) <= b + 1e-9 < market.steam_buyer_pays(s + 0.01)


def test_gaps_are_net_of_fees():
    g = market.gaps(10.0, 10.0)
    assert g["to_steam"] < -0.12 and g["to_skinport"] < -0.07
    g = market.gaps(10.0, 13.0)  # Steam 30 % above: worth it to Steam, not back
    assert g["to_steam"] == pytest.approx(market.steam_seller_gets(12.99) / 10 - 1)
    assert g["to_steam"] > 0.1 and g["to_skinport"] < -0.25
    assert market.gaps(None, 3.0) == {"to_steam": None, "to_skinport": None}


def test_steam_number_formats():
    assert collect.steam_number("1,23€") == 1.23
    assert collect.steam_number("1.234,56€") == 1234.56
    assert collect.steam_number("5,--€") == 5.0
    assert collect.steam_number("0,03 €") == 0.03
    assert collect.steam_number(None) is None
    row = collect.parse_steam("X", 200, json.dumps({"success": True, "lowest_price": "2,50€", "volume": "1,234",
                                                     "median_price": "2,40€"}).encode(), 1)
    assert row["ok"] and row["lowest"] == 2.5 and row["median"] == 2.4 and row["volume"] == 1234
    assert not collect.parse_steam("X", 200, b'{"success": false}', 1)["ok"]
    assert not collect.parse_steam("X", 500, b"", 1)["ok"]


def test_sales_keep_one_row_per_name():
    rows = [{"market_hash_name": "K", "version": "Phase 1", "last_30_days": {"volume": 5}},
            {"market_hash_name": "K", "version": "Phase 2", "last_30_days": {"volume": 9}},
            {"market_hash_name": "L", "version": "Phase 1", "last_30_days": {"volume": 1}},
            {"market_hash_name": "L", "version": None, "last_30_days": {"volume": 0}}]
    df = collect.parse_sales(rows, 1)
    got = dict(zip(df["name"], df["version"]))
    assert got == {"K": "Phase 2", "L": None}


def test_buckets_recover_disjoint_averages():
    df = pl.DataFrame({"s7_avg": [11.0], "s7_volume": [7.0], "s30_avg": [10.0], "s30_volume": [30.0],
                       "s90_avg": [9.0], "s90_volume": [90.0], "s90_min": [5.0], "s90_max": [15.0]})
    b = market.buckets(df).row(0, named=True)
    assert b["b0_7"] == 11.0
    assert b["b7_30"] == pytest.approx((300 - 77) / 23)
    assert b["b30_90"] == pytest.approx((810 - 300) / 60)
    bad = market.buckets(df.with_columns(s90_max=pl.lit(10.5))).row(0, named=True)
    assert bad["b0_7"] is None  # outside the 90-day range: the windows do not fit together


def test_category():
    assert market.category("Recoil Case") == "case"
    assert market.category("CS:GO Weapon Case") == "case"
    assert market.category("Sticker | Crown (Foil)") == "sticker"
    assert market.category("Copenhagen 2024 Legends Sticker Capsule") == "sticker"
    assert market.category("AK-47 | Redline (Field-Tested)") == "skin"
    assert market.category("★ Karambit | Fade (Factory New)") == "knife_glove"


# ---------------------------------------------------------------- collector

class FakeNet:
    def __init__(self, items, sales, steam_429: int = 0):
        self.items, self.sales, self.steam_429 = items, sales, steam_429
        self.calls: list[str] = []

    def __call__(self, url, headers):
        self.calls.append(url)
        if url == collect.SKINPORT_ITEMS or url == collect.SKINPORT_SALES:
            assert headers.get("Accept-Encoding") == "br"
            body = brotli.compress(json.dumps(self.items if url == collect.SKINPORT_ITEMS else self.sales).encode())
            return 200, body, {"Content-Encoding": "br"}
        if self.steam_429 > 0:
            self.steam_429 -= 1
            return 429, b"", {"Retry-After": "5"}
        return 200, json.dumps({"success": True, "lowest_price": "3,00€", "volume": "150", "median_price": "2,90€"}).encode(), {}


def test_collector_writes_the_lake(tmp_path):
    items, sales = momentum_market(50)
    net, slept = FakeNet(items, sales, steam_429=1), []
    rep = collect.run(tmp_path, fetch=net, steam_max=5, now_ms=NOW, sleep=slept.append)
    base = tmp_path / "cs2"
    assert rep["ok"] and rep["skinport_items"] == 50 and rep["skinport_sales"] == 50
    assert (base / "skinport_items" / "date=2026-10-15" / "1205.parquet").exists()
    daily = pl.read_parquet(base / "daily" / "skinport" / "date=2026-10-15.parquet")
    assert {"min_price", "s7_volume", "s90_avg"} <= set(daily.columns) and daily.height == 50
    assert rep["steam_requested"] == 5 and rep["steam_ok"] == 5 and not rep["steam_rate_limited"]
    assert 60 in slept  # the 429 waited the first backoff (longer than Retry-After)
    assert all(s >= collect.STEAM_INTERVAL_S for s in slept if s != 60)
    assert rep["steam_cursor"] == 5
    rep2 = collect.run(tmp_path, fetch=FakeNet(items, sales), steam_max=5, now_ms=NOW + 3_600_000, sleep=lambda s: None)
    assert rep2["steam_cursor"] == 10
    assert pl.read_parquet(base / "daily" / "steam" / "date=2026-10-15.parquet").height == 10


def test_collector_stops_steam_after_repeated_429(tmp_path):
    items, sales = momentum_market(20)
    rep = collect.run(tmp_path, fetch=FakeNet(items, sales, steam_429=10), steam_max=5, now_ms=NOW, sleep=lambda s: None)
    assert rep["steam_rate_limited"] and rep["steam_ok"] == 0 and rep["steam_cursor"] == 0
    assert rep["ok"]  # Skinport still collected


def test_collector_survives_a_skinport_failure(tmp_path):
    def fetch(url, headers):
        return 503, b"", {}
    rep = collect.run(tmp_path, fetch=fetch, steam=False, now_ms=NOW)
    assert not rep["ok"] and len(rep["errors"]) == 2


def test_rotate_wraps():
    assert collect.rotate(list("abcde"), 3, 4) == (["d", "e", "a", "b"], 2)
    assert collect.rotate([], 3, 4) == ([], 0)


# ---------------------------------------------------------------- models

def snap_of(items, sales):
    return book.snapshot(collect.parse_items(items, NOW), collect.parse_sales(sales, NOW))


def test_bootstrap_finds_planted_momentum():
    items, sales = momentum_market(600)
    rep, preds = model.bootstrap(snap_of(items, sales), date(2026, 10, 15))
    h7 = rep["h7"]
    assert h7["status"] == "ok" and h7["n"] > 500
    assert h7["ic_momentum_alone"] > 0.3
    assert h7["ic"] > 0.2
    assert preds["pred7"].drop_nulls().len() > 500
    assert rep["h30"]["status"] == "ok"


def daily_lake(root, n_items: int = 120, n_days: int = 150, seed: int = 3, signal: float = 0.6):
    """Daily snapshots whose 7-day-ahead return is partly the reverse of the last 7 days."""
    rng = np.random.default_rng(seed)
    d0 = date(2026, 10, 15) - timedelta(days=n_days - 1)
    lp = np.zeros((n_days, n_items))
    lp[0] = np.log(rng.uniform(2, 20, n_items))
    shocks = rng.normal(0, 0.02, (n_days, n_items))
    for t in range(1, n_days):
        rev = -signal * (lp[t - 1] - lp[max(t - 8, 0)]) / 7 if t > 7 else 0
        lp[t] = lp[t - 1] + rev + shocks[t]
    names = [f"M4A4 | Synth {i} (Minimal Wear)" for i in range(n_items)]
    out = root / "cs2" / "daily" / "skinport"
    out.mkdir(parents=True, exist_ok=True)
    for t in range(n_days):
        p = np.exp(lp[t])
        pl.DataFrame({"name": names, "min_price": p * 1.01, "quantity": [40] * n_items, "s24_median": p,
                      "s24_volume": [5.0] * n_items, "s7_median": p, "s7_volume": [50.0] * n_items,
                      "s30_volume": [200.0] * n_items}).write_parquet(out / f"date={(d0 + timedelta(days=t)).isoformat()}.parquet")
    return names


def test_walk_forward_scores_a_planted_signal(tmp_path):
    daily_lake(tmp_path)
    mx = model.daily_matrix(market.daily_skinport(tmp_path))
    wf = model.walk_forward(mx, horizons=(7,))
    h7 = wf["h7"]
    assert h7["status"] == "ok", h7
    assert h7["ic_independent"] > 0.1
    assert len(h7["pred_last"]) == 120


def test_walk_forward_waits_for_history(tmp_path):
    daily_lake(tmp_path, n_days=30)
    wf = model.walk_forward(model.daily_matrix(market.daily_skinport(tmp_path)))
    assert wf["h7"]["status"].startswith("needs") and wf["h30"]["status"].startswith("needs")
    assert model.walk_forward(None)["status"] == "no history"


def test_event_study_needs_events_inside_history(tmp_path):
    daily_lake(tmp_path, n_days=80)
    mx = model.daily_matrix(market.daily_skinport(tmp_path))
    ev = model.event_study(mx, [{"date": "2020-01-01", "kind": "left_drop_pool", "items": ["x"]}])
    assert ev["status"] == "no event inside the history yet"


# ---------------------------------------------------------------- paper portfolio

def market_frame(rows):
    df = pl.DataFrame(rows)
    for c in ("s24_volume", "s24_median", "s30_median", "s7_median"):
        if c not in df.columns:
            df = df.with_columns(pl.lit(None, pl.Float64).alias(c))
    return df.with_columns(ref=market.ref_price(df))


def test_rebalance_buys_after_fees_and_respects_caps():
    snap = market_frame([
        {"name": "A", "min_price": 10.0, "quantity": 100, "s7_volume": 70.0, "s7_median": 10.0},
        {"name": "B", "min_price": 2.0, "quantity": 3, "s7_volume": 500.0, "s7_median": 2.0},   # too few listed
        {"name": "C", "min_price": 0.5, "quantity": 100, "s7_volume": 500.0, "s7_median": 0.5},  # too cheap
        {"name": "D", "min_price": 50.0, "quantity": 100, "s7_volume": 700.0, "s7_median": 50.0},
        {"name": "E", "min_price": 5.0, "quantity": 100, "s7_volume": 700.0, "s7_median": 5.0},  # below the hurdle
    ])
    preds = {"A": (None, math.log(1.3)), "B": (None, math.log(1.5)), "C": (None, math.log(1.5)),
             "D": (None, math.log(1.2)), "E": (None, math.log(1.05))}
    st = book.rebalance(book.load_state(None) | {"started": "x"}, snap, preds, date(2026, 10, 15))
    assert set(st["positions"]) == {"A", "D"}
    assert st["positions"]["A"]["qty"] == 10   # a day of sales (70 / 7), under 10 % of equity
    assert st["positions"]["D"]["qty"] == 20   # 10 % of 10,000 at 50
    assert st["cash"] == pytest.approx(10_000 - 100 - 1000)
    eq, mv = book.value(st, {"A": 10.0, "D": 50.0})
    assert mv == pytest.approx(1100)
    assert eq == pytest.approx(st["cash"] + 10 * 9.99 * 0.92 + 20 * 49.99 * 0.92)


def test_rebalance_holds_thirty_days_then_sells():
    snap = market_frame([{"name": "A", "min_price": 10.0, "quantity": 100, "s7_volume": 700.0, "s7_median": 10.0}])
    st = book.rebalance(book.load_state(None), snap, {"A": (None, math.log(1.3))}, date(2026, 9, 1))
    assert "A" in st["positions"]
    st2 = book.rebalance(st, snap, {"A": (None, 0.0)}, date(2026, 9, 20))
    assert "A" in st2["positions"]  # not a pick any more, but held under 30 days
    st3 = book.rebalance(st, snap, {"A": (math.log(0.9), None)}, date(2026, 9, 20))
    assert "A" not in st3["positions"] and st3["last_trades"][0]["why"] == "predicted loss"
    st4 = book.rebalance(st, snap, {"A": (None, 0.0)}, date(2026, 10, 2))
    assert "A" not in st4["positions"]
    sell = st4["last_trades"][0]
    assert sell["side"] == "sell" and sell["net"] == pytest.approx(sell["qty"] * 9.99 * 0.92, abs=0.01)
    assert book.due(st4, date(2026, 10, 9)) and not book.due(st4, date(2026, 10, 8))


def test_journal_keeps_one_row_per_day(tmp_path):
    st = book.load_state(tmp_path)
    book.journal(tmp_path, st, {}, date(2026, 10, 15), True, 0.2)
    book.journal(tmp_path, st, {}, date(2026, 10, 15), False, 0.0)
    book.journal(tmp_path, st, {}, date(2026, 10, 16), False, 0.0)
    rows = book.read_journal(tmp_path)
    assert [r["date"] for r in rows] == ["2026-10-15", "2026-10-16"]
    assert rows[0]["rebalanced"] == "True" and float(rows[0]["equity"]) == 10_000


# ---------------------------------------------------------------- alerts

def test_alerts_find_gaps_and_drops_and_cool_down():
    snap = market_frame([
        {"name": "Gap", "min_price": 10.0, "quantity": 50, "s7_volume": 100.0, "s7_median": 10.0, "s30_median": 10.0},
        {"name": "Drop", "min_price": 7.0, "quantity": 50, "s7_volume": 300.0, "s24_volume": 10.0, "s24_median": 7.0,
         "s7_median": 9.0, "s30_median": 10.0},
        {"name": "Thin", "min_price": 7.0, "quantity": 50, "s7_volume": 5.0, "s24_volume": 3.0, "s24_median": 5.0,
         "s7_median": 9.0, "s30_median": 10.0},
    ])
    steam = pl.DataFrame({"name": ["Gap", "Drop"], "lowest": [13.0, 7.5], "volume": [100, 100]})
    ago = market_frame([{"name": "Drop", "min_price": 9.0, "quantity": 1, "s7_volume": 1.0, "s24_volume": 5.0,
                         "s24_median": 9.0}])
    found = book.find_alerts(snap, steam, ago)
    kinds = {(a["kind"], a["name"]) for a in found}
    assert kinds == {("gap", "Gap"), ("drop", "Drop")}
    fresh, st = book.fresh_alerts(found, {}, NOW)
    assert len(fresh) == 2
    again, _ = book.fresh_alerts(found, st, NOW + 3_600_000)
    assert again == []
    later, _ = book.fresh_alerts(found, st, NOW + 25 * 3_600_000)
    assert len(later) == 2
    text = book.alert_text(fresh)
    assert "paper only" in text and "Gap" in text and "—" not in text


# ---------------------------------------------------------------- the hourly job end to end

def test_run_end_to_end(tmp_path, monkeypatch):
    monkeypatch.delenv("PYTHIA_ALERT_WEBHOOK", raising=False)
    monkeypatch.delenv("PYTHIA_TELEGRAM_BOT_TOKEN", raising=False)
    items, sales = momentum_market(400)
    items.append(item_row("Recoil Case", 1.0, 500))
    rng = np.random.default_rng(9)
    sales.append(sales_row("Recoil Case", np.full(90, 1.0) * np.exp(rng.normal(0, 0.01, 90)), 50, rng))
    collect.run(tmp_path, fetch=FakeNet(items, sales), steam_max=3, now_ms=NOW, sleep=lambda s: None)
    assert cs2run.main([], root=tmp_path, now_ms=NOW) == 0
    board = json.loads((tmp_path / "reports" / "cs2_board" / "latest.json").read_text())
    assert board["status"] == "ok" and board["items"]
    assert board["model"]["src7"] == "bootstrap" and board["historyDays"] == 1
    row = board["items"][0]
    assert {"name", "price", "change7d", "pred7d", "pred30d", "signal"} <= set(row)
    assert board["portfolio"]["lastRebalance"] == "2026-10-15"
    research = json.loads((tmp_path / "reports" / "cs2" / "latest.json").read_text())
    assert research["history_days"] == 1 and "Too early" in research["verdict"]
    assert (tmp_path / "reports" / "cs2_weekly" / "latest.json").exists()
    # a second run the same day keeps one journal row and does not trade again
    assert cs2run.main([], root=tmp_path, now_ms=NOW + 3_600_000) == 0
    assert len(book.read_journal(tmp_path)) == 1


def test_run_without_data_writes_an_empty_board(tmp_path):
    assert cs2run.main([], root=tmp_path, now_ms=NOW) == 0
    board = json.loads((tmp_path / "reports" / "cs2_board" / "latest.json").read_text())
    assert board["status"] == "no data" and board["items"] == []
