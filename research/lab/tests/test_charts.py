"""The chart that goes with the daily digest and the weekly report: a PNG is
written, it is the size a phone wants, and odd data does not break it.

Needs matplotlib (research/lab/requirements.txt). Run from research/lab:
python -m pytest tests/test_charts.py
"""

from __future__ import annotations

import math
import struct

import pytest

pytest.importorskip("matplotlib")

from lab.ops import charts, notify  # noqa: E402

NOW = 1_760_424_600_000


def png_size(b: bytes) -> tuple[int, int]:
    assert b[:8] == b"\x89PNG\r\n\x1a\n", "a PNG"
    w, h = struct.unpack(">II", b[16:24])
    return w, h


def data(n_ap: int = 1, sleeves=True, positions=True, btc=True) -> dict:
    start = NOW - 9 * 86_400_000
    aps = []
    for k in range(n_ap):
        pts = [(start + i * 3_600_000, 3 * math.sin(i / (10 + k)) + i * 0.01 * (1 if k % 2 == 0 else -1)) for i in range(216)]
        aps.append({"name": f"Autopilot {k}", "points": pts})
    return {
        "autopilots": aps,
        "btc": [(start + i * 3_600_000, i * 0.02) for i in range(216)] if btc else [],
        "sleeves": [("tsmom", 31.2), ("m4_ls", -6.4), ("a very long sleeve name that goes on", 2.0)] if sleeves else [],
        "positions": [("BTC", 269.0), ("ETH", 307.0), ("DOGE", 760.0)] if positions else [],
    }


def test_the_chart_is_a_phone_sized_png(tmp_path):
    p = charts.render(data(), tmp_path / "daily.png", "Equity since start", "Wed 14 Oct")
    b = p.read_bytes()
    assert png_size(b) == (1200, 1440)
    assert 20_000 < len(b) < 1_500_000, len(b)


@pytest.mark.parametrize("kw", [
    {"n_ap": 4},
    {"sleeves": False, "positions": False},
    {"btc": False},
])
def test_odd_data_still_draws(tmp_path, kw):
    p = charts.render(data(**kw), tmp_path / "x.png", "Equity this week", "")
    assert png_size(p.read_bytes()) == (1200, 1440)


def test_flat_and_tiny_numbers_draw(tmp_path):
    d = data()
    d["autopilots"][0]["points"] = [(NOW - 3_600_000, 0.0), (NOW, 0.0)]
    d["btc"] = []
    d["sleeves"] = [("only", 0.0)]
    d["positions"] = [("PEPE", 0.004)]
    assert png_size(charts.render(d, tmp_path / "flat.png", "t").read_bytes()) == (1200, 1440)


def test_make_chart_builds_it_from_the_engine_state(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHIA_DATA", str(tmp_path))
    monkeypatch.delenv("PYTHIA_REPORTS", raising=False)
    start = NOW - 2 * 86_400_000
    state = {"autopilots": [{
        "config": {"name": "Momentum"}, "state": "running", "startedMs": start, "startCapital": 1000, "equity": 1012,
        "history": [[start + i * 60_000, 1000 + i * 0.004] for i in range(0, 2880, 10)],
        "bySleeve": [{"name": "tsmom", "pnl": 12}], "held": ["crypto:BTC/USD"]}],
        "positions": [{"marketId": "crypto:BTC/USD", "symbol": "BTC/USD", "qty": 0.01, "lastPrice": 60000}]}
    img = notify.make_chart(state, None, NOW, "Equity since start", "Tue 14 Oct", btc_fetch=lambda a, b: [])
    assert img is not None and png_size(img) == (1200, 1440)
    assert list((tmp_path / "reports" / "notify" / "charts").glob("chart-*.png"))
    assert notify.make_chart({"autopilots": []}, None, NOW, "x", "y", btc_fetch=None) is None
