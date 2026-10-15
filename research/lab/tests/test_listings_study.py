"""The listing-effect study on synthetic prices. No network, no lake.

Run from research/lab:  python -m pytest tests
"""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pytest

from lab.experiments import listings as S

H = S.HOUR_US
D = S.DAY_US


def us(y, m, d=1):
    return int(datetime(y, m, d, tzinfo=timezone.utc).timestamp() * 1e6)


def flat(start, days, px=100.0):
    t = np.arange(start, start + days * D, H, dtype=np.int64)
    return S.Series(t, np.full(len(t), px))


def test_price_at_uses_the_bar_that_ended_and_goes_stale():
    s = S.Series(np.array([0, H, 2 * H], dtype=np.int64), np.array([1.0, 2.0, 3.0]))
    assert np.isnan(s.at(H - 1)), "nothing has closed yet"
    assert s.at(H) == 1.0 and s.at(2 * H + 5) == 2.0 and s.at(3 * H) == 3.0
    assert s.at(3 * H + S.STALE_H * H) == 3.0
    assert np.isnan(s.at(3 * H + S.STALE_H * H + 1))


def test_net_charges_both_sides():
    assert S.net(100, 100) == pytest.approx(0.9965 / 1.0035 - 1)
    assert S.net(100, 110, 0) == pytest.approx(0.10)
    assert np.isnan(S.net(0, 1))


def test_event_returns_against_btc():
    t0 = us(2024, 3, 1)
    coin = flat(t0, 40)
    coin.c[coin.t >= t0 + 7 * D - H] = 120.0       # +20 % from day 7 on
    btc = flat(t0 - 10 * D, 60, 50.0)
    btc.c[btc.t >= t0 + 7 * D - H] = 55.0           # +10 %
    r = S.event_returns(coin, btc, t0 + H)
    assert r["gross_3"] == 0 and r["gross_7"] == pytest.approx(0.2)
    assert r["excess_7"] == pytest.approx(S.net(100, 120) - 0.10)
    assert not np.isnan(r["net_30"]) and r["gross_30"] == pytest.approx(0.2)
    short = flat(t0, 5)
    assert np.isnan(S.event_returns(short, btc, t0 + H)["net_7"]), "no price after the series ends"


def test_family_a_takes_first_segments_after_feb_2020_only():
    btc = flat(us(2019, 12, 1), 2000, 10.0)
    first = {"NEWUSDT": flat(us(2021, 5, 3), 60), "OLDUSDT": flat(us(2020, 1, 1), 60),
             "USDCUSDT": flat(us(2021, 5, 3), 60), "BTCUPUSDT": flat(us(2021, 5, 3), 60)}
    rows = S.family_a(first, btc, us(2026, 1, 1))
    assert {r["symbol"] for r in rows} == {"NEWUSDT"}
    assert sorted(r["entry"] for r in rows) == ["first day", "first hour"]
    assert {r["entry_us"] - us(2021, 5, 3) for r in rows} == {H, 24 * H}


def test_cross_rows_need_thirty_days_on_binance():
    btc = flat(us(2019, 12, 1), 2000, 10.0)
    s = flat(us(2021, 1, 1), 200)
    first = latest = {"AAAUSDT": s, "BBBUSDT": s}
    listed = {"AAA": us(2021, 1, 20), "BBB": us(2021, 3, 1) + 30 * 60 * 1_000_000, "CCC": us(2021, 3, 1)}
    rows = S.cross_rows("B", "coinbase", listed, first, latest, btc, us(2026, 1, 1))
    assert [r["base"] for r in rows] == ["BBB"]
    assert rows[0]["entry_us"] == us(2021, 3, 1) + H, "the first full hour after the listing"


def test_drop_launch_batch():
    t0 = us(2021, 6, 1)
    got = S.drop_launch({"BTC": t0, "ETH": t0 + 3 * D, "LATE": t0 + 100 * D})
    assert got == {"LATE": t0 + 100 * D}
    assert S.drop_launch({}) == {}


def test_holm_and_cluster_boot():
    adj = S.holm({"a": 0.01, "b": 0.04, "c": 0.03})
    assert adj == pytest.approx({"a": 0.03, "c": 0.06, "b": 0.06})
    x = np.array([1.0, 1.0, 1.0, -1.0])
    b = S.cluster_boot(x, np.array([0, 0, 0, 1]), n=2000)
    # Months are resampled whole: a draw is all of month 0, all of month 1, or a mix of the two.
    assert set(np.round(np.unique(b), 6)) <= {1.0, -1.0, 0.5}
    assert 0.2 < (b == 1.0).mean() < 0.3 and 0.2 < (b == -1.0).mean() < 0.3


def synthetic(drift: float, n_months: int = 72, per_month: int = 3, seed: int = 0):
    """Cross-venue events with a per-event 7-day excess of `drift` plus noise."""
    rng = np.random.default_rng(seed)
    start = us(2020, 1, 1)
    btc = flat(start, 2600, 10.0)
    first, latest, listed = {}, {}, {}
    k = 0
    for m in range(n_months):
        for j in range(per_month):
            t_l = us(2020 + (m + 2) // 12, (m + 2) % 12 + 1, 3 + 7 * j)
            s = flat(t_l - 60 * D, 120)
            jump = drift + rng.normal(0, 0.05)
            s.c[s.t >= t_l + H + 7 * D - H] = 100.0 * (1 + jump)
            base = f"C{k:03d}"
            first[base + "USDT"] = latest[base + "USDT"] = s
            listed[base] = t_l
            k += 1
    return first, latest, btc, listed


def test_the_rule_passes_on_a_strong_effect_and_fails_on_none(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "RESULTS", tmp_path)
    monkeypatch.setattr(S, "REPORTS", tmp_path / "reports")
    now = us(2026, 10, 1)
    first, latest, btc, listed = synthetic(0.08)
    res = S.analyse(first, latest, btc, now, listed, {}, {}, [])
    assert res["picks"]["B"] == "B · first hour after · 7d"
    assert res["verdict"]["passed"], res["verdict"]["reasons"]
    assert res["verdict"]["rule"]["horizon_days"] == 7

    first, latest, btc, listed = synthetic(0.0, seed=1)
    res0 = S.analyse(first, latest, btc, now, listed, {}, {}, [])
    assert not res0["verdict"]["passed"]
    assert res0["verdict"]["rule"] is None

    # The Alpaca events can veto: five Alpaca listings that lost block the book.
    alp = {"C000": us(2019, 1, 1)}
    losers = [b for b in listed][-8:]
    first, latest, btc, listed = synthetic(0.08)
    for b in losers[:5]:
        alp[b] = listed[b]
        s = first[b + "USDT"]
        s.c[s.t >= listed[b] + H + 7 * D - H] = 50.0
    res2 = S.analyse(first, latest, btc, now, listed, {}, alp, [])
    assert not res2["verdict"]["passed"]
    assert any("Alpaca listings lost" in r for r in res2["verdict"]["reasons"])


def test_results_file_keeps_the_preregistration(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "RESULTS", tmp_path)
    monkeypatch.setattr(S, "REPORTS", tmp_path / "reports")
    (tmp_path / "listings.md").write_text("# listings\n\nPre-registered text.\n\n" + S.MARKER + "\nold\n")
    first, latest, btc, listed = synthetic(0.0, n_months=30, seed=2)
    res = S.analyse(first, latest, btc, us(2026, 10, 1), listed, {}, {"X": us(2021, 1, 1)}, ["Kraken listing dates (x)"])
    S.write_results(res)
    S.save_report(res)
    text = (tmp_path / "listings.md").read_text()
    assert text.startswith("# listings\n\nPre-registered text.") and "\nold\n" not in text
    assert "## Results" in text and "Not measured: Kraken listing dates (x)." in text
    assert "\u2014" not in text
    import json
    rep = json.loads((tmp_path / "reports" / "listing_effect" / "latest.json").read_text())
    assert rep["passed"] is False and rep["verdict"].startswith("No rule passes")
