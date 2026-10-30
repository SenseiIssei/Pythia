"""M4H's paper book and its Hyperliquid dry-run executor: every hard limit (250 USD, 2x gross, the -20 % stop, the
GO_FLAT switch, the 10 USD minimum), the order shapes (size decimals, price rule, reduce-only), and the paper book's
Hyperliquid parse, coin mapping, restriction, marks, sizing and fills. Offline: no network, no data, no model.

Run from research/lab:  python -m pytest tests/test_m4_hl_small.py
"""

from __future__ import annotations

import inspect

import polars as pl
import pytest

from lab.paper import hl_dryrun as hx
from lab.paper import m4_hl_small as hs

MIDS = {"BTC": 60_000.0, "ETH": 3_000.0, "kPEPE": 0.012, "DOGE": 0.2}
DEC = {"BTC": 5, "ETH": 4, "kPEPE": 0, "DOGE": 0}


def plan(pos, tgt, equity=230.0, start=230.0, **kw):
    return hx.plan(pos, tgt, MIDS, DEC, equity, start, **kw)


# ---------------------------------------------------------------- the hard limits

def test_limits_are_constants():
    assert hx.MAX_ACCOUNT_USD == 250.0 and hx.MAX_GROSS == 2.0 and hx.STOP_DRAWDOWN == 0.20
    assert hx.MIN_ORDER_USD == 10.0


def test_sizing_equity_is_capped_at_250_usd():
    assert hx.sizing_equity(230.0) == 230.0
    assert hx.sizing_equity(400.0) == 250.0
    assert hx.sizing_equity(-5.0) == 0.0


def test_a_start_above_250_usd_is_refused():
    p = plan({}, {"BTC": 0.0002}, equity=300.0, start=300.0)
    assert p["mode"] == "refused" and p["orders"] == []
    assert plan({}, {"BTC": 0.0002}, start=0.0)["mode"] == "refused"


def test_gross_above_2x_sends_nothing():
    # 2x of 230 is 460 USD; 0.008 BTC is 480 USD
    p = plan({"ETH": 0.01}, {"BTC": 0.008})
    assert p["mode"] == "refused" and p["orders"] == []
    assert plan({}, {"BTC": 0.0076})["mode"] == "trade"                   # 456 USD
    # above 250 USD of equity the cap stays 2 x 250
    assert plan({}, {"BTC": 0.0085}, equity=600.0)["mode"] == "refused"  # 510 USD


def test_a_target_without_a_price_sends_nothing():
    p = hx.plan({}, {"XYZ": 1.0}, MIDS, DEC, 230.0, 230.0)
    assert p["mode"] == "refused" and p["orders"] == []


def test_the_stop_at_minus_20_percent_closes_everything_and_sticks():
    pos = {"BTC": 0.0002, "ETH": -0.004}
    p = plan(pos, {"BTC": 0.0004}, equity=184.0)                          # 0.8 x 230
    assert p["mode"] == "stopped" and p["stopped"]
    assert {(o["coin"], o["side"], o["reduce_only"]) for o in p["orders"]} == {("BTC", "sell", True),
                                                                                ("ETH", "buy", True)}
    assert plan(pos, {"BTC": 0.0004}, equity=184.01)["mode"] == "trade"
    p = plan({}, {"BTC": 0.0004}, equity=300.0, stopped=True)              # the flag holds after a recovery
    assert p["mode"] == "stopped" and p["orders"] == [] and p["stopped"]


def test_the_flat_switch_closes_everything(tmp_path):
    assert not hx.flat_switch(tmp_path)
    (tmp_path / hx.FLAT_FILE).write_text("")
    assert hx.flat_switch(tmp_path)
    p = plan({"DOGE": 30.0}, {"DOGE": 60.0, "BTC": 0.0002}, flat=True)
    assert p["mode"] == "flat" and not p["stopped"]
    assert p["orders"] == [{"coin": "DOGE", "side": "sell", "size": "30", "limit_px": "0.198", "tif": "Ioc",
                            "reduce_only": True, "notional_usd": 6.0}]       # a 6 USD close is still sent


def test_orders_under_10_usd_are_skipped_unless_they_close():
    p = plan({"DOGE": 100.0}, {"DOGE": 120.0, "ETH": 0.003})               # +4 USD, +9 USD: both skipped
    assert p["orders"] == [] and {s["coin"] for s in p["skipped"]} == {"DOGE", "ETH"}
    p = plan({"DOGE": 30.0}, {})                                            # a 6 USD close
    assert len(p["orders"]) == 1 and p["orders"][0]["reduce_only"]


# ---------------------------------------------------------------- the orders

def test_orders_round_sizes_and_mark_reduce_only():
    p = plan({"ETH": 0.02, "DOGE": -200.0}, {"ETH": 0.0161234, "BTC": 0.00019876, "DOGE": 0.0, "kPEPE": 1500.4})
    o = {x["coin"]: x for x in p["orders"]}
    assert o["ETH"] == {"coin": "ETH", "side": "sell", "size": "0.0039", "limit_px": "2970", "tif": "Ioc",
                        "reduce_only": True, "notional_usd": 11.7}
    assert o["DOGE"]["side"] == "buy" and o["DOGE"]["reduce_only"] and o["DOGE"]["size"] == "200"
    assert o["BTC"]["size"] == "0.0002" and not o["BTC"]["reduce_only"] and o["BTC"]["limit_px"] == "60600"
    assert o["kPEPE"]["size"] == "1500" and o["kPEPE"]["limit_px"] == "0.01212"
    reduce = [x["reduce_only"] for x in p["orders"]]
    assert reduce == sorted(reduce, reverse=True)                           # closes and cuts first


def test_a_flip_closes_reduce_only_then_opens():
    p = plan({"ETH": 0.01}, {"ETH": -0.01})
    assert [(o["side"], o["size"], o["reduce_only"]) for o in p["orders"]] == [("sell", "0.01", True),
                                                                               ("sell", "0.01", False)]


def test_price_rule():
    assert hx.price_str(123456.7, 5) == "123457"
    assert hx.price_str(60600.0, 5) == "60600"
    assert hx.price_str(2970.123, 4) == "2970.1"
    assert hx.price_str(0.0121234, 0) == "0.012123"
    assert hx.price_str(1.23456, 2) == "1.2346"
    assert hx.price_str(1.23456, 5) == "1.2"
    assert hx.price_str(2000.04, 4) == "2000" and hx.size_str(-0.02, 4) == "0.02" and hx.size_str(30.0, 0) == "30"


def test_nothing_can_be_sent_or_signed():
    for mod in (hx, hs):
        src = inspect.getsource(mod)
        for word in ("hyperliquid.xyz/exchange", '"/exchange"', "private_key", "sign_", "eth_account", "PRIVATE", "secret"):
            assert word not in src, f"{mod.__name__} mentions {word}"
    assert '"type": "metaAndAssetCtxs"' in inspect.getsource(hs) and hs.HL_INFO.endswith("/info")


# ---------------------------------------------------------------- the paper book

CTXS = [{"universe": [{"name": "BTC", "szDecimals": 5}, {"name": "kPEPE", "szDecimals": 0},
                      {"name": "MATIC", "szDecimals": 1, "isDelisted": True}, {"name": "POL", "szDecimals": 0},
                      {"name": "NOPX", "szDecimals": 2}]},
        [{"midPx": "60000.0", "funding": "0.0000125", "impactPxs": ["59994.0", "60006.0"]},
          {"midPx": "0.012", "funding": "-0.00001", "impactPxs": ["0.0119", "0.0121"]},
          {"midPx": "0.5"}, {"midPx": "0.4", "markPx": "0.4"}, {"midPx": None, "markPx": None}]]


def test_parse_ctxs():
    c = hs.parse_ctxs(CTXS)
    assert set(c) == {"BTC", "kPEPE", "POL"}
    assert c["BTC"]["dec"] == 5 and c["BTC"]["half_spread"] == pytest.approx(0.0001)
    assert c["kPEPE"]["half_spread"] == hs.SLIP_CAP                       # 83 bps, capped at 50
    assert c["POL"]["half_spread"] == hs.SLIP_CAP                         # no impact prices
    with pytest.raises(ValueError):
        hs.parse_ctxs({"error": "x"})


def test_hl_coin_mapping():
    c = hs.parse_ctxs(CTXS)
    assert hs.hl_coin("1000PEPEUSDT", c) == "kPEPE"
    assert hs.hl_coin("BTCUSDT", c) == "BTC"
    assert hs.hl_coin("MATICUSDT", c) == "POL"
    assert hs.hl_coin("ETHUSDT", c) is None


def test_restrict_drops_the_unlisted_before_ranking():
    c = pl.DataFrame({"perp": ["ETHUSDT", "BTCUSDT", "1000PEPEUSDT"], "score": [3.0, 2.0, 1.0],
                      "perp_adv28": [5.0, 9.0, 1.0]})
    listed, dropped = hs.restrict(c, hs.parse_ctxs(CTXS))
    assert listed["perp"].to_list() == ["BTCUSDT", "1000PEPEUSDT"] and dropped == ["ETHUSDT"]
    assert listed["coin"].to_list() == ["BTC", "kPEPE"]


def test_mark_closes_gone_coins_at_their_last_mark():
    ctx = hs.parse_ctxs(CTXS)
    pnl, units, gone = hs.mark({"BTC": 0.001, "XYZ": 5.0}, {"BTC": 59_000.0, "XYZ": 2.0}, ctx)
    assert pnl == pytest.approx(1.0) and units == {"BTC": 0.001} and gone == ["XYZ"]


def test_target_units_size_on_the_capped_equity():
    ctx = hs.parse_ctxs(CTXS)
    u = hs.target_units({"BTCUSDT": 0.05, "1000PEPEUSDT": -0.05}, {"BTCUSDT": "BTC", "1000PEPEUSDT": "kPEPE"}, ctx,
                        400.0)
    assert u["BTC"] == pytest.approx(0.05 * 250 / 60_000) and u["kPEPE"] == pytest.approx(-0.05 * 250 / 0.012)


def test_fill_charges_taker_and_half_the_impact_spread():
    ctx = hs.parse_ctxs(CTXS)
    p = hx.plan({}, {"BTC": 0.0002}, {"BTC": 60_000.0}, {"BTC": 5}, 230.0, 230.0)
    units, cost, traded = hs.fill({}, p["orders"], ctx)
    assert units == {"BTC": pytest.approx(0.0002)} and traded == pytest.approx(12.0)
    assert cost == pytest.approx(12.0 * (hs.TAKER + 0.0001))
    units, _, _ = hs.fill(units, [{"coin": "BTC", "side": "sell", "size": "0.0002"}], ctx)
    assert units == {}


def test_funding_since_sums_the_window_and_falls_back():
    rows = [{"coin": "BTC", "fundingRate": "0.00001", "time": t} for t in (1000, 2000, 3000)]
    assert hs.funding_since("BTC", 1000, 3000, fetch=lambda body: rows) == pytest.approx(0.00002)

    def boom(body):
        raise OSError("down")
    assert hs.funding_since("BTC", 0, 1, fetch=boom) is None


def test_the_book_is_a_230_usd_experiment_without_an_engine_signal():
    assert hs.START_USD == 230.0 and hs.CONFIG["k"] == 10 and hs.CONFIG["exit_frac"] == 0.5
    assert hs.VARIANT.startswith("EXPERIMENT")
    assert "save_signal" not in inspect.getsource(hs) and "signals" not in inspect.getsource(hs.main)
