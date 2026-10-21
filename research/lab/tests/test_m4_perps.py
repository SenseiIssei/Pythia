"""M4 reg7n on the perps Kraken Futures lists: coin mapping, the listing parse, the
restriction before ranking, the signal's shape and the evidence against the study.
Offline: no network, no real data, no model training.

Run from research/lab:  python -m pytest tests/test_m4_perps.py
"""

from __future__ import annotations

import re

import polars as pl
import pytest

from lab.experiments import fam_common as fc
from lab.paper import experimental as ex
from lab.paper import m4_ls
from lab.paper import m4_perps as mp
from lab.paper.families import _md_tables

DAY_US = 86_400_000_000
NOW_US = 1_792_000_000_000_000 // DAY_US * DAY_US + 5 * 3_600_000_000      # 05:00 UTC

# Shaped like the real answer of /derivatives/api/v3/instruments (fields trimmed).
INSTRUMENTS = {
    "result": "success",
    "serverTime": "2026-10-21T05:15:00.000Z",
    "instruments": [
        {"symbol": "PF_XBTUSD", "type": "flexible_futures", "tradeable": True, "suspended": False,
         "base": "BTC", "quote": "USD", "contractSize": 1},
        {"symbol": "PF_ETHUSD", "type": "flexible_futures", "tradeable": True, "base": "ETH", "quote": "USD"},
        {"symbol": "PF_PEPEUSD", "type": "flexible_futures", "tradeable": True, "suspended": False,
         "base": "PEPE", "quote": "USD"},
        {"symbol": "PF_POLUSD", "type": "flexible_futures", "tradeable": True, "suspended": False},   # no base
        {"symbol": "PI_XBTUSD", "type": "futures_inverse", "tradeable": True, "suspended": False},
        {"symbol": "FF_XBTUSD_261225", "type": "flexible_futures", "tradeable": True, "suspended": False,
         "base": "BTC"},
        {"symbol": "PF_SOLUSD", "type": "flexible_futures", "tradeable": True, "suspended": True, "base": "SOL"},
        {"symbol": "PF_DOGEUSD", "type": "flexible_futures", "tradeable": False, "suspended": False,
         "base": "DOGE"},
    ],
}


# ---------------------------------------------------------------- coins and listing

def test_coin_mapping():
    assert mp.coin_of("1000PEPEUSDT") == "PEPE"
    assert mp.coin_of("1000SHIBUSDT") == "SHIB"
    assert mp.coin_of("1000000MOGUSDT") == "MOG"
    assert mp.coin_of("1MBABYDOGEUSDT") == "BABYDOGE"
    assert mp.coin_of("BTCUSDT") == "BTC"
    assert mp.coin_of("MATICUSDT") == "POL"
    assert mp.coin_of("XBT") == "BTC"
    assert mp.coin_of("1INCHUSDT") == "1INCH", "a coin that starts with a digit keeps it"
    assert mp.kraken_coin({"symbol": "PF_XBTUSD"}) == "BTC"
    assert mp.kraken_coin({"symbol": "PF_XBTUSD", "base": "BTC"}) == "BTC"
    assert mp.kraken_coin({"symbol": "PF_LINKUSD"}) == "LINK"


def test_kraken_listing_parse():
    got = mp.parse_listing(INSTRUMENTS)
    assert got == {"BTC": "PF_XBTUSD", "ETH": "PF_ETHUSD", "PEPE": "PF_PEPEUSD", "POL": "PF_POLUSD"}
    with pytest.raises(ValueError):
        mp.parse_listing({"result": "error", "error": "apiLimitExceeded"})
    with pytest.raises(ValueError):
        mp.parse_listing({"result": "success", "instruments": INSTRUMENTS["instruments"][4:]})


def test_listing_falls_back_to_the_cache_and_stops_without_one():
    def down():
        raise OSError("timed out")

    live, cache, note = mp.listing_for(None, 1_000, fetch=lambda: {"BTC": "PF_XBTUSD"})
    assert live == {"BTC": "PF_XBTUSD"} and cache == {"fetched_ms": 1_000, "symbols": live} and note == "live"
    old = {"fetched_ms": 1_792_000_000_000, "symbols": {"ETH": "PF_ETHUSD"}}
    got, kept, note = mp.listing_for(old, 2_000, fetch=down)
    assert got == {"ETH": "PF_ETHUSD"} and kept is old and note.startswith("cached ") and "OSError" in note
    with pytest.raises(mp.NoListing):
        mp.listing_for(None, 2_000, fetch=down)
    with pytest.raises(mp.NoListing):
        mp.listing_for({"fetched_ms": 1, "symbols": {}}, 2_000, fetch=down)


# ---------------------------------------------------------------- the restricted book

def _candidates(n: int = 100) -> tuple[pl.DataFrame, dict[str, str]]:
    """n liquid perps, best score first; every third coin is not on Kraken."""
    perps = [f"C{i:03d}USDT" for i in range(n)]
    perps[0] = "1000PEPEUSDT"
    perps[1] = "BTCUSDT"
    c = pl.DataFrame({"symbol": perps, "perp": perps, "score": [1.0 - i / n for i in range(n)],
                      "perp_adv28": [20.0 - (i % 7) / 10 for i in range(n)], "fund7_raw": [0.0] * n})
    listing = {mp.coin_of(p): f"PF_{mp.coin_of(p)}USD" for i, p in enumerate(perps) if i % 3 != 2}
    listing["BTC"] = "PF_XBTUSD"
    return c, listing


def test_unlisted_coins_are_dropped_before_ranking():
    c, listing = _candidates()
    listed, dropped = mp.restrict(c, listing)
    assert dropped == sorted(mp.coin_of(p) for i, p in enumerate(c["perp"]) if i % 3 == 2)
    assert listed.height == 100 - len(dropped)
    assert set(listed["coin"]) <= set(listing)
    assert listed["score"].to_list() == sorted(listed["score"].to_list(), reverse=True), "still best first"

    tgt = mp.target(listed, {})
    longs = [s for s, x in tgt.items() if x > 0]
    shorts = [s for s, x in tgt.items() if x < 0]
    assert len(longs) == 10 and len(shorts) == 10
    order = listed["perp"].to_list()
    assert set(longs) == set(order[:10]) and set(shorts) == set(order[-10:]), "10/10 among the listed coins"
    assert not {mp.coin_of(s) for s in tgt} & set(dropped)


def test_the_buffer_keeps_a_held_coin_and_drops_one_kraken_delisted():
    c, listing = _candidates()
    listed, _ = mp.restrict(c, listing)
    order = listed["perp"].to_list()
    held_mid = order[20]                      # rank 21 of ~67: inside the top 50 %, stays long
    held_gone = "C002USDT"                    # index 2: not on Kraken, so out of the ranking
    w = {held_mid: 0.05, held_gone: 0.05}
    tgt = mp.target(listed, w)
    assert tgt[held_mid] == pytest.approx(0.05)
    assert held_gone not in tgt
    assert sum(1 for x in tgt.values() if x > 0) == 10 and sum(1 for x in tgt.values() if x < 0) == 10


def test_mark_drifts_weights_and_closes_unquoted_perps():
    gross, w, gone = mp.mark({"A": 0.5, "B": -0.5, "C": 0.1}, {"A": 100.0, "B": 10.0, "C": 1.0},
                             {"A": 110.0, "B": 10.0})
    assert gross == pytest.approx(0.05)
    assert gone == {"C"} and set(w) == {"A", "B"}
    assert w["A"] == pytest.approx(0.5 * 1.1 / 1.05)


# ---------------------------------------------------------------- the signal

def test_signal_shape():
    c, listing = _candidates()
    listed, dropped = mp.restrict(c, listing)
    tgt = mp.target(listed, {})
    decision_day = NOW_US // DAY_US * DAY_US - DAY_US
    sig = mp.signal(tgt, listing, dropped, decision_day, NOW_US)

    assert sig["strategy"] == "m4_perps"
    assert sig["variant"].startswith(ex.LABEL)
    assert sig["variant"] == ("EXPERIMENT, failed deflation · M4 reg7n · 10/10 of the 100 most liquid perps "
                              "listed on Kraken Futures · rank buffer 50 %")
    assert sig["as_of_ms"] == decision_day // 1000 and sig["generated_ms"] == NOW_US // 1000
    assert sig["valid_until_ms"] - sig["generated_ms"] == 36 * 3600 * 1000
    assert sig["quote"] == "USD" and sig["asset_class"] == "perp" and sig["cadence"] == "daily"
    assert sig["autopilot_only"] is True and sig["experimental"] is True
    assert sig["evidence"]["experimental"] is True
    assert sig["regime_on"] is None and sig["listed_on"] == "kraken_futures"

    w = sig["weights"]
    assert len(w) == 20 and "PEPE" in w and w["PEPE"] > 0, "1000PEPEUSDT is the best score, keyed as PEPE"
    longs = sum(x for x in w.values() if x > 0)
    shorts = sum(x for x in w.values() if x < 0)
    assert longs == pytest.approx(0.5) and shorts == pytest.approx(-0.5)
    assert all(round(x, 6) == x for x in w.values())
    assert sig["venue_symbols"]["BTC"] == "PF_XBTUSD"
    assert set(sig["venue_symbols"]) == set(w)
    assert all(s.startswith("PF_") for s in sig["venue_symbols"].values())
    assert sig["dropped"] == [] and sig["dropped_weight"] == 0.0
    assert sig["dropped_unlisted"] == dropped and len(dropped) > 0
    assert sig["lab_exposure"] == {"long": pytest.approx(0.5), "short": pytest.approx(-0.5),
                                   "gross": pytest.approx(1.0), "net": pytest.approx(0.0)}


def test_signal_drops_a_held_coin_kraken_no_longer_lists():
    sig = mp.signal({"BTCUSDT": 0.05, "C002USDT": -0.05}, {"BTC": "PF_XBTUSD"}, [], 0, NOW_US)
    assert sig["weights"] == {"BTC": 0.05} and sig["dropped"] == ["C002"]
    assert sig["dropped_weight"] == pytest.approx(0.05)


# ---------------------------------------------------------------- evidence and configs

def test_evidence_is_what_m4_residual_states():
    text = (fc.RESULTS_DIR / "m4_residual.md").read_text(encoding="utf-8")
    rows = [r for tb in _md_tables(text) for r in tb if r.get("cost") == "41bps"]
    hold = next(r for r in rows if "R_hold" in r)
    betas = next(r for r in rows if "b_lowvol" in r)
    years = {int(r["year"]): r["R"] for r in rows if "year" in r}
    deflated = float(re.search(r"Deflated p of R over the pool: ([0-9]+\.[0-9]+)", text).group(1))
    trials = int(re.search(r"([\d,]+) trials", text).group(1).replace(",", ""))
    r15 = next(r for tb in _md_tables(text) for r in tb if r.get("cost") == "15bps" and "R_hold" in r)

    ev = mp.EVIDENCE
    assert ev["oos_sharpe"] == pytest.approx(hold["reg7n_hold"]) == pytest.approx(2.02)
    assert ev["is_sharpe"] == pytest.approx(hold["reg7n_fit"])
    assert ev["residual_oos_sharpe"] == pytest.approx(hold["R_hold"]) == pytest.approx(0.96)
    assert ev["residual_oos_sharpe_15bps"] == pytest.approx(r15["R_hold"])
    assert ev["bootstrap_90"] == [pytest.approx(hold["boot_p05"]), pytest.approx(hold["boot_p95"])]
    assert ev["bootstrap_90"] == [0.16, 1.77]
    assert ev["boot_above0"] == pytest.approx(hold["boot_above0"])
    assert ev["b_lowvol"] == pytest.approx(betas["b_lowvol"]) and ev["b_btc"] == pytest.approx(betas["b_btc"])
    assert ev["r2_fit"] == pytest.approx(betas["r2_fit"])
    assert ev["regime_sharpes"] == {"2023 (fit window)": pytest.approx(years[2023]),
                                    "2024": pytest.approx(years[2024]), "2025": pytest.approx(years[2025]),
                                    "2026 to 2026-09-28": pytest.approx(years[2026])}
    assert deflated == pytest.approx(0.0020) and ev["deflated_p"] == pytest.approx(deflated)
    assert ev["variants_tried"] == trials == 1724
    assert ev["sharpe_2x_cost"] is None and ev["regime_filter"] is False
    assert ev["verdict"] == "experiment, passes the residual test, fails deflation"


def test_configs():
    assert m4_ls.CONFIG["model"] == "rank3" and m4_ls.CONFIG["mode"] == "hold" and m4_ls.CONFIG["hold"] == 3
    assert mp.CONFIG == {"model": "reg7n", "k": 10, "n_liquid": 100, "mode": "buffer", "hold": None,
                         "exit_frac": 0.5}
    assert mp.NAME != m4_ls.NAME, "model cache files are named per book"
