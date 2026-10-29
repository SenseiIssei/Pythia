"""T6b without a data folder: the fill hour is the latest hour of the day (the deeper of two perps), the depth cost
rises with the leg's notional and matches the collector's model, a day without a depth file falls back to T5's
tier and a size beyond the hour's depth pays 500 bps, the counters under one set of weights, the capacity, the
section kept above the file's generated part, T5's LAB20 through lab.universe.tradable with its own trials, and
lead A end to end on synthetic books with its 10 trials registered before any validation number.

Run from research/lab:  python -m pytest tests/test_two_leads_t6b.py
"""

from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from lab import metrics
from lab import universe as U
from lab.collect import book_depth as bd
from lab.experiments import director_common as dc
from lab.experiments import fam_common as fc
from lab.experiments import pit_universe_t5 as t5
from lab.experiments import two_leads_t6 as t6
from lab.experiments import two_leads_t6b as t6b

D, H = fc.DAY_US, 3_600_000_000


def write_hours(root, sym: str, rows: list[tuple]) -> None:
    """Hourly rows (ts_us, bid02, ask02, bid1, ask1, cost10k, cost100k) of one perp in T4's layout."""
    df = pl.DataFrame(rows, schema=["ts_us", "bid02", "ask02", "bid1", "ask1", "cost10k", "cost100k"], orient="row")
    df = df.with_columns(n=pl.lit(120, pl.Int32), n_fine=pl.lit(120, pl.Int32), published_us=pl.col("ts_us") + D,
                         **{c: pl.col(c).cast(pl.Float64) for c in t6b.COLS})
    p = root / "hourly" / f"symbol={sym}" / "2024-01.parquet"
    p.parent.mkdir(parents=True, exist_ok=True)
    df.select(list(bd.HOURLY_SCHEMA)).write_parquet(p)


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHIA_BOOK_DEPTH", str(tmp_path / "bd"))
    return tmp_path / "bd"


def book(k: float, first: float | None = None) -> tuple:
    """An hour of a uniform book of notional k per percent a side (first: a thinner 0.2 % level)."""
    c = np.array([[0.2 * k if first is None else first, k, 2 * k, 3 * k, 4 * k, 5 * k]])
    return (c[0, 0], c[0, 0], k, k, float(bd.cost_bps(c, 1e4)[0]), float(bd.cost_bps(c, 1e5)[0]))


# ---------------------------------------------------------------- the depth at the fill

def test_the_fill_hour_is_the_days_latest_and_a_coin_keeps_its_deeper_perp(store):
    d0 = dc.us("2024-01-02")
    write_hours(store, "AAAUSDT", [(d0 + 3 * H, *book(1e6)), (d0 + 23 * H, *book(2e6)), (d0 + D + 5 * H, *book(3e6))])
    write_hours(store, "1000AAAUSDT", [(d0 + 23 * H, *book(5e5))])
    write_hours(store, "BBBUSDT", [(d0 + 22 * H, *book(4e6)), (dc.us("2026-07-01") + H, *book(4e6))])
    fh = t6b.fill_hours()
    a = fh.filter(pl.col("asset") == "AAA").sort("day_us")
    assert a["day_us"].to_list() == [d0, d0 + D] and a["ts_us"].to_list() == [d0 + 23 * H, d0 + D + 5 * H]
    assert a["bid1"].to_list() == [2e6, 3e6]                          # the 23:00 hour, the deeper perp
    b = fh.filter(pl.col("asset") == "BBB")
    assert b["ts_us"].to_list() == [d0 + 22 * H]                      # nothing of the lockbox is read
    assert t6b.coin_key("1000PEPEUSDT") == "PEPE" and t6b.coin_key("LUNAUSDT~0") == ""


def test_the_depth_cost_rises_with_the_legs_notional_and_matches_the_collectors_model():
    fh = pl.DataFrame([book(2e5, first=1.5e4), book(1e6), book(5e7)],
                      schema=["bid02", "ask02", "bid1", "ask1", "cost10k", "cost100k"], orient="row")
    c = {k: t6b.order_cost(fh, s) for k, s in t6b.SIZES.items()}
    assert (c["1k"] < c["10k"]).all() and (c["10k"] < c["100k"]).all()
    assert (c["1k"][:2] > c["1k"][2]).all()                          # a thinner book costs more
    cum = np.array([[1.5e4, 2e5, 2e5, 2e5, 2e5, 2e5]])
    assert c["1k"][0] == pytest.approx(bd.cost_bps(cum, 1e3)[0] / 1e4)
    assert c["1k"][1] == pytest.approx(1e3 / (2 * 1e6) * 100 / 1e4)    # a uniform book: Q / 2k percent
    assert c["10k"][1] == pytest.approx(fh["cost10k"][1] / 1e4)


def test_a_missing_day_falls_back_to_the_tier_and_a_size_beyond_the_depth_pays_500_bps():
    days = dc.us("2024-01-01") + np.arange(4) * D
    thin = (np.nan, np.nan, 3e4, 3e4, 40.0, np.nan)                    # 100k beyond its recorded depth
    fh = pl.DataFrame([(int(days[1]), "BTC", *book(1e8)), (int(days[2]), "BTC", *thin),
                       (int(days[2]), "ETH", np.nan, np.nan, np.nan, np.nan, np.nan, np.nan)],
                      schema=["day_us", "asset", "bid02", "ask02", "bid1", "ask1", "cost10k", "cost100k"],
                      orient="row")
    vol = np.full((4, 2), 5e6)                                          # tier: 5 + 25 bps
    Cs = t6b.cost_matrices(days, ["BTC", "ETH"], vol, fh)
    tier = t5.PERP_FEE + t5.half_spread(vol)[0, 0]
    for k in t6b.SIZES:
        assert Cs[k][0, 0] == pytest.approx(tier) and Cs[k][3, 0] == pytest.approx(tier)
        assert Cs[k][2, 1] == pytest.approx(tier)                      # an hour without its book: the tier
        assert Cs[k][1, 0] < tier                                       # a deep book is cheaper than the tier
    assert Cs["1k"][1, 0] < Cs["10k"][1, 0] < Cs["100k"][1, 0]
    assert Cs["100k"][2, 0] == pytest.approx(t5.PERP_FEE + t6b.BEYOND) and Cs["beyond 100k"][2, 0] == 1
    assert Cs["10k"][2, 0] == pytest.approx(t5.PERP_FEE + 40e-4) and Cs["beyond 10k"].sum() == 0
    assert Cs["at tier"][:, 0].tolist() == [1, 0, 0, 1] and Cs["at tier"][2, 1] == 1
    assert np.array_equal(Cs["tier"], t5.era_cost(vol, True)) and (Cs["fee"] == t5.PERP_FEE).all()
    D_, b = t6b.depth_matrix(days, ["BTC"], fh.head(0), 1e4)
    assert np.isnan(D_).all() and not b.any()


def test_the_counters_charge_the_turnover_at_the_tier_on_one_set_of_weights(monkeypatch):
    from tests.test_pit_universe_t5 import toy_panel
    P = toy_panel(monkeypatch, days=300)
    vol = U.median_volume(P)
    uni = U.pit(P, 5, table=pl.DataFrame({"base": [], "kind": [], "known_us": []}), vol=vol)
    half = np.zeros((P.T, P.N))
    half[::2] = 1.0
    C = t5.era_cost(vol, True)
    r = t6b.run_costs(P, "carry", uni, 5, {"era": C, "all": np.ones((P.T, P.N)), "at tier": half})
    assert np.allclose(r["era"][0], t5.run_rule(P, "carry", uni, 5, C))
    assert (r["at tier"][1] <= r["all"][1] + 1e-12).all() and r["at tier"][1].sum() > 0
    assert r["at tier"][1].sum() < r["all"][1].sum()


# ---------------------------------------------------------------- capacity, the report

def test_capacity_is_where_the_sharpe_halves_in_log_notional():
    c = t6b.capacity({"1k": 1.8, "10k": 1.4, "100k": 0.6}, 2.0)
    assert c["side"] == "at" and c["usd"] == pytest.approx(10 ** (4 + 0.4 / 0.8))
    assert t6b.capacity({"1k": 0.9, "10k": 0.5, "100k": 0.1}, 2.0)["side"] == "below"
    assert t6b.capacity({"1k": 1.9, "10k": 1.8, "100k": 1.5}, 2.0) == {"usd": None, "side": "above", "bar": 1.0}


def test_the_section_sits_above_the_generated_part_and_only_its_body_is_replaced(monkeypatch, tmp_path):
    monkeypatch.setattr(dc, "RESULTS", tmp_path)
    p = tmp_path / "x.md"
    p.write_text("# X\n\nhand text\n\n" + dc.marker("x") + "\n\nold generated\n", encoding="utf-8")
    t6b.put_section("x", "T6b: with order book depth", "body one")
    s = p.read_text(encoding="utf-8")
    at = [s.index(x) for x in ("hand text", "## T6b: with order book depth", "body one", dc.marker("x"))]
    assert at == sorted(at)
    assert s.endswith("old generated\n")
    p.write_text(s.replace("## T6b: with order book depth\n", "## T6b: with order book depth\n\nmy lines\n"))
    t6b.put_section("x", "T6b: with order book depth", "body two")
    s = p.read_text(encoding="utf-8")
    assert "body one" not in s and "body two" in s and "my lines" in s and s.count("## T6b") == 1
    assert s.endswith("old generated\n")


def test_t5s_old_gaps_are_read_from_its_table():
    text = ("| rule | gap |\n|---|---|\n| tsmom | +0.39 / +0.45 | +13.0 / +8.2 pts |\n"
            "| lowvol | -1.13 / -2.02 | x |\n| tsmom | LAB20 | 1.65 / 38.4 % / 26.2 % |\n")
    assert t6b.t5_old_gaps(text) == {"tsmom": "+0.45", "lowvol": "-2.02"}


# ---------------------------------------------------------------- T5 with the delisting table

def test_t5s_lab20_leaves_on_its_announcement_day_and_its_trials_get_their_own_ids(monkeypatch, tmp_path):
    from tests.test_pit_universe_t5 import D0, toy_panel
    monkeypatch.setattr(U, "LAB20", ("BTC", "ETH", "SOL"))
    P = toy_panel(monkeypatch)
    table = pl.DataFrame({"base": ["ETH"], "kind": ["perp"], "known_us": [D0 + 150 * D + H]})
    vol = U.median_volume(P)
    u = t5.universes(P, vol, table, lab_delist=True)
    e = P.col("ETHUSDT")
    assert u["LAB20"][149, e] and not u["LAB20"][150:, e].any()
    assert t5.universes(P, vol, table)["LAB20"][150:, e].all()          # T5's run: no drop
    assert t5.trial("tsmom", "LAB20", 1.0, t6b.T5_TAG, t6b.PREREG)["id"] == "hand:t5_pit_dl:tsmom:LAB20"
    assert t5.trial("tsmom", "LAB20", 1.0)["id"] == "hand:t5_pit:tsmom:LAB20"


# ---------------------------------------------------------------- lead A end to end

def test_lead_a_registers_its_10_trials_first_and_reports_every_variant(monkeypatch, tmp_path):
    from tests.test_two_leads_t6 import toy_lead
    reg = tmp_path / "registry.jsonl"
    monkeypatch.setenv("PYTHIA_TRIALS_REGISTRY", str(reg))
    monkeypatch.setattr(dc, "ledger_trials", lambda: [])
    seen = []
    real = metrics.dsr
    monkeypatch.setattr(metrics, "dsr", lambda *a, **k: seen.append(reg.exists()) or real(*a, **k))
    P, base = toy_lead(2.0)
    cost = {"fee": 0.0, "tier": 4e-4, "1k": 1e-4, "10k": 3e-4, "100k": 1.2e-3}
    by = {v: {b: base[b] - cost[v] for b in t6.BOOKS} for v in t6b.VARIANTS}
    cnt = {c: {b: np.where(np.isfinite(base[b]), 1.0 if c in ("all", "at tier") else 0.0, np.nan) for b in t6.BOOKS}
           for c in t6b.COUNTERS}
    A = t6b.lead_a(P, by, cnt, {"book": np.full(6, 0.001), **{b: np.full(6, 0.001) for b in t6.BOOKS}},
                   {"ok": True, "runs": 4}, log=lambda *_: None)
    ids = [r["id"] for r in metrics._read(reg)]
    assert len(A["trials"]) == 10 and all(i in ids for i in A["trials"]) and seen and all(seen)
    assert "hand:t6b:a:ERC" in ids and "hand:t6b:a:ERC@100k" in ids and "hand:t6b:a:ERC@10k" not in ids
    s = {v: A["variants"][v]["val"]["sharpe"] for v in t6b.VARIANTS}
    assert s["fee"] > s["1k"] > s["10k"] > s["100k"]
    assert A["val"]["sharpe"] == pytest.approx(s["10k"])
    assert A["counts"]["M4"]["val"]["tier_share"] == pytest.approx(1.0)
    md = t6b.markdown(A, {"generated": "test", "folds": "f", "delist": "present"})
    assert "Capacity" in md and "| depth, 100k a leg |" in md and "\u2014" not in md
    assert "A2 DSR all" in md and ("Lockbox: no look" in md or "not looked" in md)
    import json
    from lab import report
    monkeypatch.setattr(report, "REPORTS", tmp_path)
    monkeypatch.setattr(dc, "RESULTS", tmp_path)
    (tmp_path / t6b.NAME).mkdir()
    (tmp_path / t6b.NAME / "latest.json").write_text(json.dumps(
        {"A": A, "about": {"generated": "x", "folds": "f", "delist": "present"}}, default=float), encoding="utf-8")
    (tmp_path / f"{t6.NAME}.md").write_text("# T6\n\n" + dc.marker(t6.NAME) + "\n\nT6's numbers\n", encoding="utf-8")
    assert t6b.main(["--report"]) == 0                                 # the section again from the json, no run
    s = (tmp_path / f"{t6.NAME}.md").read_text(encoding="utf-8")
    assert "Capacity" in s and s.endswith("T6's numbers\n")
