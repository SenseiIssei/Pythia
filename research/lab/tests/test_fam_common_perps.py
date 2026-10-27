"""R4: the sweep panel's short side. A perp bar without volume is not shortable, and the
perp cache is rebuilt when it ends before the price panel and the archive has news.

No network, no lab data. Run from research/lab:  python -m pytest tests/test_fam_common_perps.py
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone

import numpy as np
import polars as pl
import pytest

from lab.experiments import fam_common as fc
from lab.experiments import picks_ls

DAY = fc.DAY_US
T = 220                                    # rolling() needs more rows than the 200-day regime window


def us(day: str) -> int:
    return int(datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1e6)


D0 = us("2025-01-01")


def long_frame() -> pl.DataFrame:
    rows = []
    for sym, p0, step in (("BTCUSDT", 50_000.0, 100.0), ("DEADUSDT", 10.0, -0.2)):
        for i in range(T):
            c = p0 + step * i
            rows.append({"day": D0 + i * DAY, "symbol": sym, "close": c, "high": c * 1.01, "low": c * 0.99,
                         "rv": 1e-4, "qv": 5e6, "n": 24})
    return pl.DataFrame(rows)


def perp_frame(days: int, dead_from: int) -> pl.DataFrame:
    """BTC trades every day; DEAD's perp prints flat zero-volume bars from `dead_from` on."""
    rows = []
    for i in range(days):
        rows.append({"day": D0 + i * DAY, "base": "BTC", "funding": 1e-4, "perp_qv": 1e9})
        rows.append({"day": D0 + i * DAY, "base": "DEAD", "funding": 0.0 if i >= dead_from else 5e-4,
                     "perp_qv": 0.0 if i >= dead_from else 2e6})
    return pl.DataFrame(rows)


@pytest.fixture
def lake(tmp_path, monkeypatch):
    monkeypatch.setattr(fc, "OUT", tmp_path / "agent")
    monkeypatch.setattr(fc, "ROOT", tmp_path)
    (tmp_path / "agent" / "cache").mkdir(parents=True)
    return tmp_path


def write_cache(frame: pl.DataFrame, age_s: float = 0.0) -> None:
    p = fc.OUT / "cache" / "perp_daily.parquet"
    frame.write_parquet(p)
    t = time.time() - age_s
    os.utime(p, (t, t))


def touch_archive(root, symbol: str = "DEADUSDT") -> None:
    d = root / "hist" / "binance_um" / "klines_1d" / f"symbol={symbol}"
    d.mkdir(parents=True, exist_ok=True)
    (d / "2025-02-09.parquet").write_bytes(b"")


def test_a_dead_perp_with_flat_zero_volume_bars_is_not_shortable(lake):
    write_cache(perp_frame(T, dead_from=20))
    P = fc.panel_from(long_frame())
    j = P.col("DEADUSDT")
    assert P.perp_ok[:20, j].all() and not P.perp_ok[20:, j].any()
    assert P.funding[19, j] == 5e-4 and (P.funding[20:, j] == 0).all()
    assert P.perp_ok[:, P.btc].all()
    # Short the falling coin from day 0: the book holds it while the perp trades, then is closed out.
    W = np.zeros((P.T, P.N))
    W[:, j] = -0.5
    g, tov, le, se = fc.simulate(P, W)
    assert se[19] == pytest.approx(0.5, rel=0.05) and (se[20:] == 0).all()
    assert tov[20] == pytest.approx(0.5, rel=0.1)             # the drifted short is bought back on the first dead day
    assert (g[21:] == 0).all()                              # nothing earned or funded on the dead perp


def test_a_stale_cache_is_rebuilt_when_the_archive_has_news(lake, monkeypatch):
    write_cache(perp_frame(10, dead_from=99), age_s=3600)    # ends on day 9, the prices run to day 219
    touch_archive(lake)
    built = []

    def perp_panel():
        built.append(1)
        f = perp_frame(T, dead_from=30)
        return f.select("day", "base", "funding", qv="perp_qv")

    monkeypatch.setattr(picks_ls, "perp_panel", perp_panel)
    P = fc.panel_from(long_frame())
    assert built == [1]
    j = P.col("DEADUSDT")
    assert P.perp_ok[:30, j].all() and not P.perp_ok[30:, j].any()
    assert pl.read_parquet(fc.OUT / "cache" / "perp_daily.parquet")["day"].max() == D0 + (T - 1) * DAY
    # The fresh cache covers the panel: the next build reads it as it is.
    fc.panel_from(long_frame())
    assert built == [1]


def test_a_stale_cache_is_kept_when_the_archive_has_nothing_newer(lake, monkeypatch):
    touch_archive(lake)
    write_cache(perp_frame(10, dead_from=99))                 # written after the archive's last file
    monkeypatch.setattr(picks_ls, "perp_panel", lambda: pytest.fail("rebuilt for nothing"))
    P = fc.panel_from(long_frame())
    assert P.perp_ok[:10].all() and not P.perp_ok[10:].any()
