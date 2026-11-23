"""M4S2, step 2 for the M4 paper books: the era's fees and depth, the weight traded and its share at depth, one close
late, Kraken's coins for carry and low vol with the legs scaled back, the band check, the PBO of a book's families,
the five rows and their bars, the 30 trials, the stored series and the results table. Synthetic data only.

Run from research/lab:  python -m pytest tests/test_m4_step2.py
"""

from __future__ import annotations

import json

import numpy as np
import polars as pl
import pytest

from lab import metrics
from lab.experiments import director_common as dc
from lab.experiments import m4_step2 as S
from lab.experiments import m4h

D0 = dc.us("2024-01-01")
DAY = S.DAY_US


def world(T: int = 6, N: int = 30, r: float = 0.0) -> dict:
    """N coins, column 0 the best score and the most liquid, return r a day, no cost."""
    R = np.full((T, N), r)
    return {"days": D0 + np.arange(T) * DAY, "score": np.tile(-np.arange(N, dtype=float), (T, 1)),
            "liq": np.tile(1e9 - np.arange(N, dtype=float), (T, 1)), "R": R, "R2": R.copy(),
            "P": np.ones((T, N)), "P2": np.ones((T, N)), "F": np.zeros((T, N)), "F2": np.zeros((T, N)),
            "Fb": np.zeros((T, N)), "F_hl": np.zeros((T, N)), "slip": np.zeros((T, N)), "dec": [None] * N,
            "mult": np.ones(N)}


# ---------------------------------------------------------------- costs of their era

def test_hyperliquids_fee_follows_the_fill_day_and_krakens_is_flat():
    d = np.array([dc.us(x) for x in ("2023-12-30", "2023-12-31", "2025-04-29", "2025-04-30", "2026-06-28")])
    assert list(S.hl_fee(d) * 1e4) == pytest.approx([2.5, 3.5, 3.5, 4.5, 4.5])
    assert list(S.venue_fee(d, "kraken_futures") * 1e4) == pytest.approx([5.0] * 5)


def test_the_era_cost_takes_the_depth_where_its_file_exists_else_the_proxy():
    depth = np.array([[1e-4, np.nan], [np.nan, 0.05]])
    proxy = np.full((2, 2), 3e-4)
    c = S.era_cost(np.array([5e-4, 2.5e-4]), depth, proxy)
    assert np.allclose(c, [[6e-4, 8e-4], [5.5e-4, 0.05025]])


def test_traded_rebuilds_the_weights_before_each_days_orders():
    X = world(r=0.01)
    r = S.m4_run(X, 0, 5, "m4_perps", X["slip"], None, False)
    tr = r["tr"].sum(1)
    assert tr[0] == pytest.approx(1.0)                       # 20 entries of 0.5 / 10
    assert np.allclose(tr[1:], 0.0, atol=1e-12)              # held names drift inside the buffer: nothing traded
    X["score"][3] = X["score"][3, ::-1]                      # the ranking flips on day 3: every name changes side
    assert S.m4_run(X, 0, 5, "m4_perps", X["slip"], None, False)["tr"].sum(1)[3] > 1.0


def test_one_close_late_trades_on_yesterdays_score():
    X = world()
    X["score"][2] = X["score"][2, ::-1]
    on = S.m4_run(X, 0, 5, "m4_perps", X["slip"], None, False)["tr"].sum(1)
    late = S.m4_run(X, 0, 5, "m4_perps", X["slip"], None, True)["tr"].sum(1)
    assert late[0] == 0.0 and late[1] == pytest.approx(1.0)  # no score before the first day
    assert on[2] > 1.0 and late[3] > 1.0 and late[2] == pytest.approx(0.0, abs=1e-12)


def test_the_share_at_depth_and_beyond_by_year():
    tr = np.array([[1.0, 1.0], [2.0, 0.0], [1.0, 3.0]])
    depth = np.array([[1e-4, np.nan], [1e-4, 1e-4], [np.nan, 0.05]])
    beyond = np.array([[0.0, 0.0], [0.0, 0.0], [0.0, 1.0]])
    days = np.array([dc.us("2024-12-31"), dc.us("2025-01-01"), dc.us("2025-01-02")])
    s = S.shares(tr, depth, beyond, days)
    assert s["depth"] == pytest.approx(6 / 8) and s["beyond"] == pytest.approx(3 / 8)
    assert s["by_year"]["2024"]["depth"] == pytest.approx(0.5) and s["by_year"]["2025"]["depth"] == pytest.approx(5 / 6)


# ---------------------------------------------------------------- carry and low vol on Kraken's coins

def test_the_legs_are_scaled_back_to_their_gross_and_a_missing_leg_is_flat():
    W = np.array([[0.2, 0.3, -0.25, -0.25], [np.nan] * 4, [0.5, 0.0, -0.5, 0.0]])
    keep = np.array([[True, False, True, True], [True] * 4, [True, True, False, True]])
    out = S.restrict_rows(W, keep)
    assert out[0].tolist() == pytest.approx([0.5, 0.0, -0.25, -0.25])
    assert np.isnan(out[1]).all() and out[2].tolist() == [0.0, 0.0, 0.0, 0.0]


def test_a_coin_is_listed_from_its_first_fill_day_and_old_segments_never():
    first = {"PEPE": int(D0 // DAY) + 2, "BTC": int(D0 // DAY)}
    m = S.coin_listed(D0 + np.arange(4) * DAY, ["1000PEPEUSDT", "BTCUSDT", "BTCUSDT~0", "XYZUSDT"], first)
    assert m[:, 0].tolist() == [False, True, True, True]             # decided the day before the first fill day
    assert m[:, 1].all() and not m[:, 2].any() and not m[:, 3].any()


def test_carry_holds_only_the_listed_coins():
    T, N = 8, 30
    F = {"days": D0 + np.arange(T) * DAY, "R": np.zeros((T, N)), "fund": np.zeros((T, N)),
         "perp_adv28": np.tile(1e9 - np.arange(N, dtype=float), (T, 1)),
         "s_F7": np.tile(-np.arange(N, dtype=float), (T, 1)), "fund7_raw": np.zeros((T, N))}
    F["R"][:, 0] = 0.05                                      # the best coin gains, but Kraken does not list it
    listed = np.ones((T, N), dtype=bool)
    listed[:, 0] = False
    C = np.zeros((T, N))
    net_all, _ = S.carry_run(F, None, C, False)
    net_kr, _ = S.carry_run(F, listed, C, False)
    assert net_all[1:].sum() > 0 and net_kr.sum() == pytest.approx(0.0)


def test_the_combination_starts_when_all_three_books_have_returns():
    class P:
        days = D0 + np.arange(200) * DAY
    rng = np.random.default_rng(3)
    legs = {b: rng.normal(0.001, 0.01, 200) for b in S.PN_BOOKS}
    legs["Carry"][:5] = np.nan
    c, common = S.pn_candidates(P, legs)
    assert set(c) == set(S.PN_BOOKS) | set(S.PN_METHODS) and not common[:5].any() and common[5:].all()
    assert np.isnan(c["ERC"][:64]).all() and np.isfinite(c["ERC"][-100:]).all()   # 60 returns before the weights


# ---------------------------------------------------------------- the band check

def test_the_band_check_compares_both_books_with_their_stored_series(tmp_path):
    X = world(T=8)
    X["R"][:, :10] = 0.01
    X["perp"] = [f"C{j}USDT" for j in range(30)]
    X["days"] = dc.us(S.OOS_FROM) + np.arange(8) * DAY
    listed = {"hyperliquid": np.ones((8, 30), dtype=bool), "kraken_futures": np.ones((8, 30), dtype=bool)}
    for b, c in m4h.SERIES.items():
        X["F"] = X["F_hl"] if c["venue"] == "hyperliquid" else np.full((8, 30), np.nan)
        x = m4h.simulate(X, 0, 7, 10, 1, c["capital"], c["fee"], "base", listed[c["venue"]])["ret"]
        pl.DataFrame({"day": X["days"], "ret": x}).write_parquet(tmp_path / c["file"])
    ck = S.band_check(X, listed, tmp_path)
    assert all(v["ok"] and v["max_diff"] == 0.0 and v["days"] == 8 for v in ck.values())
    df = pl.read_parquet(tmp_path / m4h.SERIES["m4_perps"]["file"])
    df.with_columns(pl.col("ret") + 1e-6).write_parquet(tmp_path / m4h.SERIES["m4_perps"]["file"])
    ck = S.band_check(X, listed, tmp_path)
    assert not ck["m4_perps"]["ok"] and ck["m4_hl_small"]["ok"]


# ---------------------------------------------------------------- judging

def test_pbo_of_a_planted_edge_is_low_and_the_book_takes_its_highest_family():
    rng = np.random.default_rng(5)
    noise = {f"s{i}": rng.normal(0, 0.01, 1600) for i in range(6)}
    edge = {**noise, "edge": rng.normal(0.004, 0.01, 1600)}
    edge["edge"][:3] = np.nan                               # rows with a gap are left out
    lo, hi = S.pbo_of(edge), S.pbo_of(noise)
    assert lo["pbo"] < 0.05 and lo["n"] == 7 and lo["days"] == 1597 and hi["pbo"] > lo["pbo"]
    j = S.judged_pbo("perps_neutral", {"fa": lo, "pn": hi, "m4h": None})
    assert j["value"] == hi["pbo"] and set(j["families"]) == {"fa", "pn"}
    assert S.judged_pbo("m4_hl_small", {"fa": lo, "m4h": None})["value"] is None


def row(**kw) -> dict:
    r = {"family": "hand", "late": {"cagr": 0.2, "sharpe": 1.0, "max_dd": 0.2}, "era": {"cagr": 0.3, "sharpe": 1.2,
         "max_dd": 0.1, "proxy": "p"}, "dsr_all": 0.96, "dsr_hand": 0.97, "dsr_small": 0.5,
         "pbo": {"value": 0.1, "families": {"fa": {"pbo": 0.1, "n": 18}}}}
    for k, v in kw.items():
        if k in ("late", "era"):
            r[k] = {**r[k], "cagr": v}
        elif k == "pbo":
            r["pbo"] = {**r["pbo"], "value": v}
        else:
            r[k] = v
    return r


@pytest.mark.parametrize("kw, fail", [({}, set()), ({"late": -0.01}, {"late"}), ({"era": 0.0}, {"era"}),
                                      ({"dsr_all": 0.94}, {"dsr_all"}), ({"dsr_hand": 0.5}, {"dsr_family"}),
                                      ({"family": "small"}, {"dsr_family"}), ({"pbo": 0.2}, {"pbo"}),
                                      ({"pbo": None}, {"pbo"})])
def test_the_five_rows_and_their_bars(kw, fail):
    c = S.conditions(row(**kw))
    assert set(c) == set(S.CONDS) and {k for k, v in c.items() if not v["ok"]} == fail


def test_thirty_trials_26_hand_and_4_small_with_their_in_sample_sharpe():
    ins = {f"{b}:{c}": 0.5 for b in ("m4_perps", "m4_hl_small", "perps_neutral") for c in ("late", "era")}
    ins.update({f"fa:reg{h}n:{n}:{k}": 0.1 for h in (3, 5, 7) for n in (50, 100) for k in ("hold", "buf30", "buf50")})
    ins.update({"m4h:k3": 0.2, "m4h:k5": 0.3, **{f"pn:{k}": 0.4 for k in ("Carry", "LowVol", "EW", "IV")}})
    T = S.trials_of(ins)
    ids = [t["id"] for t in T]
    assert len(T) == 30 == len(set(ids)) and sum(t["family"] == "hand" for t in T) == 26
    assert {i for i in ids if i.startswith("small:")} == {"small:m4s2:m4_hl_small:late", "small:m4s2:m4_hl_small:era",
                                                          "small:m4s2:pbo:m4h:k3", "small:m4s2:pbo:m4h:k5"}
    assert "hand:m4s2:pbo:fa:reg7n:100:buf50" in ids and all(t["source"] == S.PREREG and t["n"] == 1 for t in T)


def test_book_row_stores_the_late_series_and_its_dsrs(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHIA_TRIALS_REGISTRY", str(tmp_path / "registry.jsonl"))
    pools = {f: metrics.trial_pool(None if f == "all" else f) for f in ("all", "hand", "small")}
    days = dc.us(S.OOS_FROM) + np.arange(400) * DAY
    x = np.random.default_rng(4).normal(0.002, 0.01, 400)
    sh = {"depth": 0.9, "beyond": 0.0, "by_year": {"2024": {"depth": 0.9, "beyond": 0.0}}}
    r = S.book_row("m4_hl_small", x, x + 1e-4, days, sh, pools)
    assert r["family"] == "small" and r["days"] == 400 and len(r["oos_returns"]) == 400
    assert r["dsr_small"] == pytest.approx(metrics.dsr(x, pools["small"]), abs=1e-6)
    assert r["era"]["cagr"] > r["late"]["cagr"] and "Hyperliquid" in r["era"]["proxy"] and "10 %" in r["era"]["proxy"]


def out_of(rows: dict) -> dict:
    return {"generated": "2026-11-23T10:00:00+00:00", "panel": {"sha256": "36774aa37afa00", "built": "2026-11-02"},
            "check": {"m4_perps": {"ok": True, "days": 910, "max_diff": 0.0}},
            "pool": {f: {"n_trials": 7390, "sr0_annual": 3.0} for f in ("all", "hand", "small")},
            "trials": ["a"] * 30, "trial_counts": {"hand": 26, "small": 4},
            "families": {"fa": {"pbo": 0.1, "n": 18, "combos": 12870, "days": 1640, "median_logit": 1.0},
                         "m4h": None, "pn": None},
            "books": rows}


def test_the_json_and_the_table_have_a_row_per_book_and_requirement(tmp_path, monkeypatch):
    monkeypatch.setattr(dc, "RESULTS", tmp_path)
    sh = {"depth": 0.9, "beyond": 0.01, "by_year": {"2024": {"depth": 0.8, "beyond": 0.0}}}
    rows = {}
    for b in S.BOOKS:
        r = row(dsr_all=0.1)
        r.update(book=b, family=S.BOOKS[b]["family"], first="2024-01-01", last="2026-06-28", days=3,
                 pool_all=7390, pool_family=2281, oos_returns=[0.01, -0.02, 0.0])
        r["era"].update(by_year={"2024": 1.0}, shares=sh)
        r["conditions"] = S.conditions(r)
        rows[b] = r
    o = out_of(rows)
    S.write_json(o)
    d = json.loads((tmp_path / "m4_step2.json").read_text())
    assert set(d["books"]) == set(S.BOOKS) and d["books"]["m4_perps"]["oos_returns"] == [0.01, -0.02, 0.0]
    assert d["books"]["m4_perps"]["pbo"]["families"]["fa"]["label"] == "reg7n's family"
    md = S.markdown(o)
    lines = [x for x in md.splitlines() if x.startswith("| m4_") or x.startswith("| perps_neutral |")]
    step2 = [x for x in lines if any(f"| {S.LABEL[c]} |" in x for c in S.CONDS)]
    fails = [x for x in step2 if "| fail |" in x]                               # DSR over R5 for each book, and
    assert len(step2) == 15 and len(fails) == 4 and "small family's" in fails[-1]  # m4_hl_small's small one
    assert "| m4_perps | DSR over R5 >= 0.95 | fail | 0.100 over 7,390 trials |" in md
    assert "0.10 (the highest of: reg7n's family 0.10 over 18)" in md and "| M4H's k" in md


def test_a_stopped_run_says_so_and_judges_nothing():
    o = {"generated": "x", "panel": {}, "check": {"m4_perps": {"ok": False, "days": 910, "max_diff": 1e-3}},
         "stopped": "the band check failed", "books": {}}
    md = S.markdown(o)
    assert "DIFFERS" in md and "**Stopped**" in md and "No trial was registered" in md
