"""L1: the 50 EUR Kraken dry run on a fixture AssetPairs answer (Kraken's of 2026-10-28, six pairs): an order under
ordermin dropped and counted, rounding down to the lot, the fee by the tier, the replay's drift and fees, the report
on a fake data folder, and no code path that signs or sends.

Run from research/lab:  python -m pytest tests/test_exec_dryrun.py
"""

from __future__ import annotations

import ast
import copy
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import pytest

from lab import metrics
from lab.exec import dryrun as D

FIX = json.loads((Path(__file__).parent / "fixtures" / "kraken_assetpairs_l1.json").read_text())["result"]
NOW = datetime(2026, 10, 28, 6, 0, tzinfo=timezone.utc).timestamp()
TICKER = {"XXBTZEUR": {"a": ["72900.0", "1", "1"], "b": ["72899.9", "1", "1"]},
          "PEPEEUR": {"a": ["0.000004523", "1", "1"], "b": ["0.000004522", "1", "1"]},
          "PAXGEUR": {"a": ["3570.91", "1", "1"], "b": ["3570.70", "1", "1"]},
          "ZEURZUSD": {"a": ["1.1150", "1", "1"], "b": ["1.1144", "1", "1"]},
          "SPYxUSD": {"a": ["770.21", "1", "1"], "b": ["767.84", "1", "1"]}}


def mk():
    return D.market(FIX)


def test_market_takes_the_eur_pair_and_the_usd_pair_only_without_one():
    m = mk()
    assert m["BTC"]["pair"] == "XBT/EUR" and m["BTC"]["quote"] == "EUR"         # XBT is BTC, EUR before USD
    assert D.rule_of(m, "GOLD")["pair"] == "PAXG/EUR"
    assert D.rule_of(m, "SPY")["pair"] == "SPYx/USD" and D.rule_of(m, "SPY")["aclass"] == "tokenized_asset"
    assert m["EUR"]["pair"] == "EUR/USD"
    off = copy.deepcopy(FIX)
    off["PAXGEUR"]["status"] = "cancel_only"
    assert D.rule_of(D.market(off), "GOLD") is None


def test_an_order_under_ordermin_is_dropped():
    pepe = mk()["PEPE"]                                     # ordermin 1,100,000 PEPE, about 5 EUR
    o = D.size("PEPE", pepe, 0.71, 0.000004523, 1.0)
    assert not o["placed"] and o["why"] == "below ordermin"
    assert o["units_raw"] == pytest.approx(0.71 / 0.000004523) and o["fee_eur"] == 0.0
    o = D.size("PEPE", pepe, 6.0, 0.000004523, 1.0)
    assert o["placed"] and o["units"] >= 1_100_000
    assert D.size("FOO", None, 5.0, 1.0, 1.0)["why"] == "no pair"
    assert D.size("PEPE", pepe, 5.0, math.nan, 1.0)["why"] == "no price"


def test_rounding_down_to_the_lot_and_the_price_decimals():
    btc = mk()["BTC"]                                        # lot_decimals 8, pair_decimals 1
    o = D.size("BTC", btc, 10.0, 72900.04, 1.0)
    assert o["price"] == 72900.0
    assert o["units"] == math.floor(10.0 / 72900.0 * 1e8) / 1e8 and o["units"] <= o["units_raw"]
    assert o["cost_eur"] <= 10.0
    lot5 = {**btc, "lot_decimals": 5, "ordermin": 0.0, "costmin": 0.0}
    o = D.size("BTC", lot5, 10.0, 72900.0, 1.0)
    assert o["units"] == 0.00013                             # 0.000137... rounded down, never up
    o = D.size("BTC", lot5, 0.5, 72900.0, 1.0)
    assert o["why"] == "rounds to 0"
    o = D.size("BTC", {**btc, "ordermin": 0.0}, 0.40, 72900.0, 1.0)
    assert o["why"] == "below costmin"                      # 0.40 EUR under costmin 0.45
    o = D.size("BTC", btc, -10.0, 72900.0, 1.0, held=0.0001)
    assert o["side"] == "sell" and o["units"] == 0.0001 and o["cut"]   # a sell never more than held
    o = D.size("BTC", btc, 10.0, 72900.0, 1.0, cash=5.0)
    assert o["cut"] and o["cost_eur"] + o["fee_eur"] <= 5.0


def test_fee_by_the_tier():
    btc = mk()["BTC"]
    assert btc["fees"] == []                                 # empty in Kraken's answer: the published schedule
    assert D.fee_rate(btc, 0.0) == pytest.approx(0.0080)
    assert D.fee_rate(btc, 0.0, maker=True) == pytest.approx(0.0040)
    assert D.fee_rate(btc, 2_500.0) == pytest.approx(0.0060)
    assert D.fee_rate(btc, 30_000.0) == pytest.approx(0.0035)
    assert D.fee_rate(btc, 20_000_000.0) == pytest.approx(0.0010)
    tiered = {**btc, "fees": [[0, 0.26], [50000, 0.24], [100000, 0.22]], "fees_maker": [[0, 0.16], [50000, 0.14]]}
    assert D.fee_rate(tiered, 60_000.0) == pytest.approx(0.0024)        # AssetPairs' own tiers when filled
    assert D.fee_rate(tiered, 60_000.0, maker=True) == pytest.approx(0.0014)
    assert D.fee_rate(D.rule_of(mk(), "SPY"), 0.0) == pytest.approx(0.0080 + D.FX_FEE)
    o = D.size("BTC", btc, 20.0, 72900.0, 1.0, vol_usd=30_000.0)
    assert o["fee_eur"] == pytest.approx(o["cost_eur"] * 0.0035)


def test_todays_orders_from_a_fresh_wallet():
    m = mk()
    usd = D.eurusd(m, TICKER)
    assert usd == pytest.approx(1.1147)
    out = D.orders({"BTC": 0.6, "PEPE": 0.02, "SPY": 0.3, "FOO": 0.05, "ETH": 0.0}, m, TICKER, usd)
    by = {o["coin"]: o for o in out}
    assert set(by) == {"BTC", "PEPE", "SPY", "FOO"}
    assert by["BTC"]["placed"] and by["BTC"]["eur"] == pytest.approx(30.0)
    assert by["PEPE"]["why"] == "below ordermin" and by["PEPE"]["drift"] == pytest.approx(-0.02)
    assert by["FOO"]["why"] == "no pair"
    assert by["SPY"]["placed"] and by["SPY"]["cost_eur"] == pytest.approx(by["SPY"]["units"] * 770.21 / usd)
    assert -0.01 < by["BTC"]["drift"] <= 0


def test_replay_counts_the_orders_it_could_not_place():
    m = mk()
    closes = {"XXBTZEUR": {"2026-10-01": 70000.0, "2026-10-02": 71400.0, "2026-10-03": 70000.0},
              "PEPEEUR": {"2026-10-01": 0.000005, "2026-10-02": 0.0000055, "2026-10-03": 0.000005}}
    days = [("2026-10-01", {"BTC": 0.5, "PEPE": 0.01}), ("2026-10-02", {"BTC": 0.5, "PEPE": 0.01}),
            ("2026-10-03", {"BTC": 0.0, "PEPE": 0.0})]
    r = D.replay(days, m, closes, {}, 1.11)
    # day 1: BTC bought, PEPE under ordermin; day 2 no change, no order; day 3 BTC sold, PEPE has nothing to sell
    assert r["orders"] == 2 + 1 and r["placed"] == 2 and r["not_placed"] == 1
    assert r["why"]["below ordermin"] == 1 and r["share_not_placed"] == pytest.approx(1 / 3)
    sold = [o for o in r["list"] if o["side"] == "sell"][0]
    assert sold["placed"] and sold["units"] == r["list"][0]["units"]   # sells everything it holds
    assert r["fees_eur"] == pytest.approx(sum(o["cost_eur"] for o in r["list"] if o["placed"]) * 0.008)
    assert r["fees_month_pct"] == pytest.approx(r["fees_eur"] / 3 * 30 / 50 * 100)
    # off target on days 1 and 2: PEPE's 0.01 missing plus BTC's rounding and day 2's move; 0 after the sale
    assert 0.01 * 2 / 3 < r["off_mean"] < 0.03 * 2 / 3
    assert len(r["list"]) == 3 and r["span_days"] == 3
    assert r["wallet_end_eur"] < 50.0


def write_journal(root: Path, book: str, rows: list[tuple[str, dict]]) -> None:
    p = root / "paper" / book / "journal.csv"
    p.parent.mkdir(parents=True, exist_ok=True)
    lines = ["date,equity,weights"] + ['%s,10000,"%s"' % (d, json.dumps(w).replace('"', '""')) for d, w in rows]
    p.write_text("\n".join(lines) + "\n")


def test_run_on_a_fake_data_folder(tmp_path, monkeypatch):
    write_journal(tmp_path, "tsmom", [("2026-10-26", {"PEPE": 0.014}), ("2026-10-27", {"PEPE": 0.02, "BTC": 0.3})])
    write_journal(tmp_path, "small50_tsmom1", [("2026-10-27", {"BTC": 1.0})])
    calls = []
    bars = [[int(datetime(2026, 10, d, tzinfo=timezone.utc).timestamp()), "0", "0", "0", c, "0", "0", 1]
            for d, c in ((25, "70000"), (26, "71000"), (27, "72000"))]

    def get(path):
        calls.append(path)
        if path.startswith("AssetPairs"):
            return {} if "tokenized" in path else FIX
        if path.startswith("Ticker"):
            return {} if "tokenized" in path else TICKER
        key = path.split("pair=")[1].split("&")[0]
        return {key: bars if key == "XXBTZEUR" else [[b[0], "0", "0", "0", "0.000005", "0", "0", 1] for b in bars],
                "last": 0}

    res = D.run(tmp_path, tmp_path / "w", NOW, get, pause=0.0)
    assert (tmp_path / "w" / "exec" / "kraken_pairs.json").exists() and (tmp_path / "w" / "exec" / "kraken_ohlc.json").exists()
    by = {b["book"]: b for b in res["books"]}
    assert by["tsmom"]["replay"]["orders"] == 3 and by["tsmom"]["replay"]["why"]["below ordermin"] == 2
    assert by["small50_tsmom1"]["orders"][0]["placed"] and by["tsmom_regime"]["replay"]["days"] == 0
    assert res["venue"]["taker_pct"] == pytest.approx(0.80)
    md = D.markdown(res)
    assert "below ordermin 2" in md and "no journal" in md and "\u2014" not in md
    ids = {r["id"] for r in metrics.read_registry()}
    assert {f"small:l1:exec_dryrun_{b}" for b in D.BOOKS} <= ids and len(D.trials()) == 11
    n = len(calls)
    D.run(tmp_path, tmp_path / "w", NOW + 3600, get, pause=0.0)              # within CACHE_H: the caches only
    assert len(calls) == n

    def down(path):
        raise OSError("down")

    res = D.run(tmp_path, tmp_path / "w", NOW + 25 * 3600, down, pause=0.0)  # stale cache when Kraken is down
    assert res["venue"]["stale"]


def test_no_code_path_signs_or_sends():
    src = Path(D.__file__).read_text(encoding="utf-8")
    low = src.lower()
    for bad in ("api-key", "api-sign", "hmac", "hashlib", "base64", "nonce", "/private", "addorder", "cancelorder",
                "withdraw", "secret", "getenv", "environ.get(\"kraken", "post", "data="):
        assert bad not in low, bad
    tree = ast.parse(src)
    urls = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and "://" in n.value]
    assert urls == ["https://api.kraken.com/0/public"]
    opens = [n for n in ast.walk(tree) if isinstance(n, ast.Attribute) and n.attr in ("urlopen", "Request")]
    assert len(opens) == 2                                     # one Request, one urlopen, both in _get
    req = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "Request"][0]
    assert [k.arg for k in req.keywords] == ["headers"] and len(req.args) == 1    # no body, no method
    assert not any(isinstance(n, (ast.Import, ast.ImportFrom)) and any(
        a.name.split(".")[0] in ("requests", "http", "socket", "ssl", "hmac") for a in n.names)
        for n in ast.walk(tree))
