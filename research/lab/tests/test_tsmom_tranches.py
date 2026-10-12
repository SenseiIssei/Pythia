"""The seven-tranche momentum book: simulator against the blend study's, and the paper book. No lab data.

Run from research/lab:  python -m pytest tests
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from lab.experiments import blend_study as bl
from lab.experiments import fam_common as fc
from lab.experiments import tsmom_tranches as tt

T, N = 400, 6


def make_panel(first_day_us: int = tt.ANCHOR_US) -> fc.Panel:
    rng = np.random.default_rng(7)
    ret = rng.normal(0.001, 0.03, (T, N))
    ret[0] = np.nan
    px = 100 * np.cumprod(1 + np.nan_to_num(ret), axis=0)
    alive = np.ones((T, N), dtype=bool)
    alive[300:, 5] = False                      # coin 5 is delisted at day 300
    px[~alive] = np.nan
    ret[~alive] = np.nan
    traded = alive.copy()
    traded[50, 2] = False
    close = np.where(traded, px, np.nan)
    days = first_day_us + np.arange(T, dtype=np.int64) * fc.DAY_US
    names = [f"C{j}USDT" for j in range(N)]
    names[0], names[1], names[2] = "BTCUSDT", "ETHUSDT", "TRXUSDT"
    idx = np.arange(T)[:, None]
    return fc.Panel(days=days, names=names, bases=[fc.base_of(n) for n in names], close=close, px=px,
                    high=px, low=px, ret=ret, alive=alive, traded=traded, age=np.where(alive, idx, -1),
                    adv28=np.where(alive, 1e7 * (N - np.arange(N))[None, :], np.nan),
                    sigma=np.full((T, N), 0.03), eligible=alive & traded & (idx >= 60),
                    perp_ok=np.zeros((T, N), dtype=bool), funding=np.zeros((T, N)),
                    btc_on=np.arange(T) % 100 < 70, btc=0)


@pytest.fixture()
def panel() -> fc.Panel:
    return make_panel()


def weights(seed: int = 1) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.uniform(0, 0.2, (T, N)) * (rng.random((T, N)) < 0.7)


def test_is_the_blend_studys_seven_tranche_book(panel):
    """On a panel starting at the anchor, the tranche simulator is blend_study's
    "seven weekly tranches" book: seven sim_long books with a 50 % band, one per
    weekday, blended at equal capital re-set every 30 days."""
    W = weights()
    books = [bl.sim_long(panel, W, f"t{off}", ((np.arange(T) - off) % 7) == 0, 0.5) for off in range(7)]
    ref = bl.blend(books, "equal capital", None)
    g, tv, ex, _, _, _ = tt.simulate(panel, W)
    assert np.allclose(g, ref.gross)
    # blend stops one close early; the paper book needs the last close decided too.
    assert np.allclose(tv[:-1], ref.turnover[:-1])
    assert np.allclose(ex[:-1], ref.expo[:-1])


def test_phase_follows_the_calendar_not_the_panel_start(panel):
    late = make_panel(tt.ANCHOR_US + 3 * fc.DAY_US)
    assert tt.due_tranche(int(late.days[0])) == 3
    assert tt.due_tranche(int(panel.days[10])) == 10 % 7


def test_book_weights_sum_to_exposure_and_never_lever(panel):
    W = weights(3) * 3
    g, tv, ex, alloc, inner, held = tt.simulate(panel, W, record=True)
    assert ex.max() <= 1 + 1e-9
    w = tt.book_weights(panel, W, T - 1)
    assert w.sum() == pytest.approx(ex[T - 1])
    assert np.allclose(held[T - 1], w)


def test_delisted_coin_is_closed_and_charged(panel):
    W = np.zeros((T, N))
    W[:, 5] = 0.5
    _, tv, _, _, _, held = tt.simulate(panel, W, band=0.0, record=True)
    assert held[300:, 5].max() == 0
    assert tv[300] > 0


# ---------------------------------------------------------------------------
# The paper book
# ---------------------------------------------------------------------------

def test_paper_book_starts_where_the_backtest_stands_and_trades_one_tranche(panel, tmp_path, monkeypatch):
    from lab.paper import families as fam
    monkeypatch.setattr(fam, "ROOT", tmp_path)
    W = weights(4)
    t = 250
    quotes = {s: (float(panel.px[t, j]) * 0.9995, float(panel.px[t, j]) * 1.0005)
              for j, s in enumerate(panel.names) if np.isfinite(panel.px[t, j])}
    row = fam.step_tranches(panel, W, t, quotes, int(panel.days[t + 1]))
    st = json.loads((tmp_path / "paper" / "tsmom_tranches" / "state.json").read_text())
    want = tt.book_weights(panel, W, t)
    got = np.zeros(N)
    for k, tr in enumerate(st["tranches"]):
        for s, x in tr.items():
            got[panel.col(s)] += st["alloc"][k] * x
    assert np.allclose(got, want, atol=1e-9)
    assert row["tranche"] == tt.due_tranche(int(panel.days[t]))
    # Next day at unchanged prices: only the due tranche changes (no reset that day).
    t2 = t + 1
    assert not tt.reset_due(int(panel.days[t2]))
    before = [dict(x) for x in st["tranches"]]
    fam.step_tranches(panel, W, t2, quotes, int(panel.days[t2 + 1]))
    st2 = json.loads((tmp_path / "paper" / "tsmom_tranches" / "state.json").read_text())
    k2 = tt.due_tranche(int(panel.days[t2]))
    for k in range(tt.K):
        if k != k2:
            assert st2["tranches"][k] == pytest.approx(before[k])


def test_tranche_signal_is_the_combined_book(panel, monkeypatch):
    from lab.paper import families as fam
    monkeypatch.setattr(fam, "ENGINE_COINS", frozenset({"BTC", "ETH", "C3", "C4"}))
    monkeypatch.setattr(fam, "evidence", lambda name: {"report": "x"})
    W = weights(5)
    sig = fam.signal("tsmom_tranches", panel, W, 250, int(panel.days[251]))
    want = tt.book_weights(panel, W, 250)
    assert sig["autopilot_only"] is True
    assert "TRX" in sig["dropped"] or want[2] == 0
    for coin, x in sig["weights"].items():
        assert x == pytest.approx(want[panel.col(coin + "USDT")], abs=1e-6)
    assert sig["lab_exposure"] == pytest.approx(want.sum(), abs=1e-6)


def test_evidence_falls_back_to_the_committed_report(tmp_path, monkeypatch):
    """Without the JSON next to the sweep's caches, the evidence is read from results/tsmom_tranches.md."""
    from lab.paper import families as fam
    monkeypatch.setattr(fc, "OUT", tmp_path)
    ev = fam.evidence("tsmom_tranches")
    assert not ev.get("missing")
    assert ev["source"].endswith("tsmom_tranches.md")
    assert ev["variant"] == tt.VARIANT
    assert ev["deflated_p"] < 0.95 and ev["verdict"].startswith("fails")
    assert ev["variants_tried"] and ev["variants_tried"] >= 184
    assert 0 < ev["non_alpaca_share"] < 1
    for k in ("oos_sharpe", "oos_sharpe_maker", "sharpe_2x_cost", "oos_max_dd", "caveat"):
        assert ev[k] is not None
    # The engine deserialises regime_sharpes as numbers: two of them, no nulls.
    assert len(ev["regime_sharpes"]) == 2
    assert all(isinstance(v, float) for v in ev["regime_sharpes"].values())
    assert all(v is not None for v in ev.values() if not isinstance(v, (dict, list)))
