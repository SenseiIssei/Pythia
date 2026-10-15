"""pump.fun paper watcher: AMM fills, the pre-registered rules, rugs as total losses, exits,
the daily report's feed header, and that nothing here can touch a wallet. No network.

Run from research/lab:  python -m pytest tests/test_pumpfun.py
"""

from __future__ import annotations

import inspect
from datetime import datetime, timezone

import pytest

from lab.paper import pumpfun as pf

NOW = 1_792_080_000_000
H = pf.HOUR_MS
MINT = "Grad1111111111111111111111111111111111pump"
MINT2 = "Grad2222222222222222222222222222222222pump"


def iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def pool(addr: str, mint: str, dex: str, created: int, price: float = 0.001, liq: float = 40_000.0) -> dict:
    return {"id": f"solana_{addr}", "type": "pool",
            "attributes": {"address": addr, "name": f"{mint[:4]} / SOL", "pool_created_at": iso(created),
                           "base_token_price_usd": str(price), "quote_token_price_usd": "150",
                           "reserve_in_usd": str(liq), "fdv_usd": str(price * 1e9)},
            "relationships": {"base_token": {"data": {"id": f"solana_{mint}"}},
                              "dex": {"data": {"id": dex}}}}


class Feed:
    """GeckoTerminal and DexScreener answers, by URL, editable between runs."""

    def __init__(self):
        self.pools = [pool("P1", MINT, "pumpswap", NOW - 60_000),
                      pool("P2", "Launch33333333333333333333333333333333pump", "pump-fun", NOW - 30_000, liq=0.0),
                      pool("P3", MINT2, "pumpswap", NOW - 90_000, liq=12_000.0)]
        self.info = {MINT: {"holders": {"count": 800, "distribution_percentage": {"top_10": "18.5"}},
                            "mint_authority": "no", "freeze_authority": "no", "is_honeypot": "no",
                            "launchpad_details": {"completed": True}},
                     MINT2: {"holders": {"count": 120, "distribution_percentage": {"top_10": "55"}},
                             "mint_authority": "no", "freeze_authority": "no", "is_honeypot": "unknown"}}
        self.marks = {MINT: (0.001, 40_000.0), MINT2: (0.001, 12_000.0)}
        self.urls: list[str] = []

    def __call__(self, url: str):
        self.urls.append(url)
        if "new_pools" in url:
            return {"data": self.pools if url.endswith("page=1") else []}
        if "/info" in url:
            mint = url.split("/tokens/")[1].split("/")[0]
            return {"data": {"attributes": self.info.get(mint, {})}}
        if "dexscreener" in url:
            mints = url.rsplit("/", 1)[1].split(",")
            out = []
            for m in mints:
                if m in self.marks and self.marks[m] is not None:
                    p, liq = self.marks[m]
                    out.append({"baseToken": {"address": m}, "priceUsd": str(p), "dexId": "pumpswap",
                                "pairAddress": "X", "liquidity": {"usd": liq}})
            return out
        raise AssertionError(url)


def test_amm_arithmetic_charges_fee_and_slippage():
    # $100 into a pool with $20,000 on the quote side at $1: about 1.25 % fee and 0.5 % impact.
    tokens = pf.amm_buy(100.0, 20_000.0, 1.0)
    assert tokens == pytest.approx(20_000 * 98.75 / (20_000 + 98.75))
    assert 97.5 < tokens < 98.75
    back = pf.amm_sell(tokens, 20_000.0, 1.0)
    assert back < 100 * (1 - pf.POOL_FEE) ** 2, "a round trip loses two fees and the impact both ways"
    assert pf.amm_buy(100.0, 0.0, 1.0) == 0.0 and pf.amm_sell(10.0, 1000.0, 0.0) == 0.0


def test_rules_and_filters():
    g = {"liq_usd": 40_000.0, "price_usd": 0.001}
    good = {"holders": 800, "top10_pct": 18.5, "mint_authority": "no", "freeze_authority": "no", "honeypot": "no"}
    assert pf.passes("migration", g, None) == (True, "ok")
    assert pf.passes("filtered", g, good) == (True, "ok")
    assert pf.passes("filtered", g, None)[0] is False, "no holder data, no paper buy"
    assert not pf.passes("filtered", g, {**good, "holders": 100})[0]
    assert not pf.passes("filtered", g, {**good, "top10_pct": 45})[0]
    assert not pf.passes("filtered", g, {**good, "mint_authority": "yes"})[0]
    assert not pf.passes("filtered", g, {**good, "honeypot": "yes"})[0]
    assert not pf.passes("migration", {**g, "liq_usd": 5_000.0}, None)[0]
    assert pf.is_graduation({"dex": "pumpswap", "mint": MINT})
    assert not pf.is_graduation({"dex": "pump-fun", "mint": MINT})
    assert not pf.is_graduation({"dex": "pumpswap", "mint": "So11111111111111111111111111111111111111112"})


def test_a_run_buys_graduations_by_rule_and_counts_launches():
    f = Feed()
    res = pf.run(f, NOW)
    st = res["state"]
    assert res["launches"] == 1 and len(res["graduations"]) == 2
    bought = sorted((r, g["mint"]) for r, g in res["bought"])
    assert bought == [("filtered", MINT), ("filtered_quick", MINT), ("migration", MINT), ("migration", MINT2)]
    for rule in pf.RULES:
        n = len(pf.open_positions(st, rule))
        assert st["books"][rule]["cash"] == pytest.approx(pf.START_EQUITY - pf.STAKE_USD * n)
    p = pf.open_positions(st, "migration")[0]
    assert p["eff_price"] > p["entry_price"], "fees, priority fee and slippage make the fill dearer than spot"
    # A second run sees the same pools again and buys nothing twice.
    res2 = pf.run(f, NOW + 5 * 60_000, st)
    assert res2["bought"] == []


def test_vanished_liquidity_is_a_total_loss():
    f = Feed()
    st = pf.run(f, NOW)["state"]
    f.marks[MINT] = (0.0009, 120.0)                       # the pool was drained
    res = pf.run(f, NOW + 10 * 60_000, st)
    rugs = [p for p in res["closed"] if p["mint"] == MINT]
    assert rugs and all(p["exit"]["usd"] == 0.0 and p["exit"]["reason"].startswith("rug") for p in rugs)
    assert all(p["exit"]["ret"] == -1.0 for p in rugs)


def test_a_token_without_any_pool_is_a_rug_after_an_hour_of_runs():
    f = Feed()
    st = pf.run(f, NOW)["state"]
    f.marks[MINT2] = None
    for k in range(1, 4):
        res = pf.run(f, NOW + k * 5 * 60_000, st)
        st = res["state"]
    assert all(p["open"] for p in st["positions"] if p["mint"] == MINT2), "three runs in 15 minutes are not an hour"
    res = pf.run(f, NOW + 70 * 60_000, st)
    gone = [p for p in res["closed"] if p["mint"] == MINT2]
    assert gone and gone[0]["exit"]["reason"] == "rug: no pool left" and gone[0]["exit"]["usd"] == 0.0


def test_take_profit_trailing_stop_and_time_exits():
    f = Feed()
    st = pf.run(f, NOW)["state"]
    f.marks[MINT] = (0.0021, 80_000.0)                    # +110 %: filtered_quick takes its profit
    res = pf.run(f, NOW + 30 * 60_000, st)
    quick = [p for p in res["closed"] if p["rule"] == "filtered_quick"]
    assert quick and quick[0]["exit"]["reason"].startswith("take profit") and quick[0]["exit"]["ret"] > 0.9
    f.marks[MINT] = (0.0014, 60_000.0)                    # -33 % from the peak: the 30 % trail of migration fires
    res = pf.run(f, NOW + 60 * 60_000, res["state"])
    reasons = {p["rule"]: p["exit"]["reason"] for p in res["closed"]}
    assert reasons.get("migration", "").startswith("trailing stop 30")
    assert "filtered" not in reasons, "the filtered rule trails at 40 %"
    st = res["state"]
    res = pf.run(f, NOW + 73 * H, st)                       # past 72 h
    assert any(p["rule"] == "filtered" and p["exit"]["reason"] == "time 72 h" for p in res["closed"])


def test_alerts_for_big_winners_and_grouped_losers():
    f = Feed()
    st = pf.run(f, NOW)["state"]
    f.marks[MINT] = (0.0021, 80_000.0)
    res = pf.run(f, NOW + 30 * 60_000, st)
    cards = pf.alert_cards(res["closed"], res["state"], NOW + 30 * 60_000)
    assert any("winner" in c.title for c in cards)
    f.marks[MINT] = (0.0001, 100.0)
    res = pf.run(f, NOW + 40 * 60_000, res["state"])
    cards = pf.alert_cards(res["closed"], res["state"], NOW + 40 * 60_000)
    assert [c for c in cards if "losers" in c.title]
    again = pf.alert_cards(res["closed"], res["state"], NOW + 45 * 60_000)
    assert not [c for c in again if "losers" in c.title], "losers at most once an hour"


def test_cards_come_from_the_message_catalog_in_english_or_german():
    from lab.ops import notify

    f = Feed()
    st = pf.run(f, NOW)["state"]
    f.marks[MINT] = (0.0021, 80_000.0)
    res = pf.run(f, NOW + 30 * 60_000, st)
    de = pf.alert_cards(res["closed"], res["state"], NOW + 30 * 60_000, "de")
    text = notify.plain(notify.render_post(de))
    assert "Paper-Gewinner" in text and "Gewinnmitnahme" in text and "Nur Paper" in text
    import re
    for english in ("winner", "became", "take profit", "Paper only", "Rule"):
        assert not re.search(rf"\b{english}\b", text), english
    f.marks[MINT] = (0.0001, 100.0)
    res = pf.run(f, NOW + 40 * 60_000, res["state"])
    de = pf.alert_cards(res["closed"], res["state"], NOW + 40 * 60_000, "de")
    text = notify.plain(notify.render_post(de))
    assert "Paper-Verlierer" in text and "Rug: Liquidität" in text and "Totalverlust" in text
    data, _ = pf.report(res["state"], NOW + 50 * 60_000)
    card = notify.plain(notify.render_post([pf.report_card(data, "de")]))
    assert "pump.fun Paper-Bücher" in card and "Regel" in card and "Gestern" in card
    en = notify.plain(notify.render_post([pf.report_card(data, "en")]))
    assert "pump.fun paper books" in en and "Yesterday" in en


def test_report_carries_the_lab_feed_header():
    f = Feed()
    st = pf.run(f, NOW)["state"]
    f.marks[MINT] = (0.0001, 100.0)
    st = pf.run(f, NOW + 10 * 60_000, st)["state"]
    data, md = pf.report(st, NOW + 12 * 60_000)
    for k in ("title", "updated_ms", "status", "headline", "items"):
        assert k in data
    assert data["status"] in ("ok", "watch", "bad")
    assert "Paper only" in data["headline"]
    assert all(i.get("label") for i in data["items"])
    assert "| migration |" in md
    stale, _ = pf.report(st, NOW + 5 * H)
    assert stale["status"] == "bad", "a watcher silent for hours is red"


def test_rate_limit_stops_calls_to_that_host_for_the_run():
    import urllib.error

    http = pf.Http(gaps={"a.example": 0.0}, budgets={"a.example": 5})
    http.blocked.add("a.example")
    with pytest.raises(pf.RateLimited):
        http("https://a.example/x")
    http2 = pf.Http(gaps={"b.example": 0.0}, budgets={"b.example": 0})
    with pytest.raises(pf.RateLimited):
        http2("https://b.example/x")
    assert issubclass(pf.RateLimited, OSError) and urllib.error  # caught like any network failure


def test_nothing_here_can_touch_a_wallet_or_send_a_transaction():
    src = inspect.getsource(pf).lower()
    for word in ("sendtransaction", "signtransaction", "keypair", "private_key", "privatekey", "secret_key",
                 "mnemonic", "seed phrase", "solana.rpc", "solders", "jupiter", "swap?"):
        assert word not in src, word
    assert "frontend-api" not in src, "pump.fun's own API is not used (its terms forbid bots)"
