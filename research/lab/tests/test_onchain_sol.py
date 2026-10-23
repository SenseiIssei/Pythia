"""The on-chain book onchain_breakout_sol (lab.onchain.sol_book): breakout_top10's rule among the coins with a
Solana mint, its target file, the live service trading it in the alpha mode, its paper twin's journal. Synthetic
candles, a fake Jupiter and a fake chain; no lab data, no network, no key.

Run from research/lab:  python -m pytest tests/test_onchain_sol.py
"""

from __future__ import annotations

import csv
import dataclasses
import json
import time

import numpy as np
import pytest

from lab.experiments import fam_breakout, fam_common as fc
from lab.onchain import book as B
from lab.onchain import live_exec as LX
from lab.onchain import live_gate as LG
from lab.onchain import live_service as SV
from lab.onchain import mints as M
from lab.onchain import sol_book as S
from lab.paper import families as F
from lab.paper import forward_report as FR
from lab.paper import tsmom

import test_onchain_live as T
import test_onchain_wallet as TW
from test_onchain import MIDS, Pools, lab  # noqa: F401 - lab is a fixture

ONCHAIN = list(M.COINS)                    # SOL BTC ETH JUP BONK WIF POPCAT RAY PYTH JTO RENDER TRUMP
DAYS = 400


def panel(names: list[str], seed: int = 11, last_day_us: int | None = None) -> fc.Panel:
    """Synthetic daily candles: random walks with drift (breakouts and exits), liquidity falling with the column
    index (so the daily top 10 is the first ten live columns), every coin 60 days old from day 60."""
    T_, N = DAYS, len(names)
    rng = np.random.default_rng(seed)
    ret = rng.normal(0.002, 0.04, (T_, N))
    ret[0] = np.nan
    px = 100 * np.cumprod(1 + np.nan_to_num(ret), axis=0)
    alive = np.ones((T_, N), dtype=bool)
    traded = alive.copy()
    close = np.where(traded, px, np.nan)
    last = last_day_us if last_day_us is not None else fc.DAY_US * (20_000 + T_)
    days = last - np.arange(T_ - 1, -1, -1, dtype=np.int64) * fc.DAY_US
    idx = np.arange(T_)[:, None]
    sigma = np.abs(rng.normal(0.035, 0.01, (T_, N))) + 0.01
    return fc.Panel(days=days, names=names, bases=[fc.base_of(n) for n in names], close=close, px=px,
                    high=px, low=px, ret=ret, alive=alive, traded=traded, age=np.where(alive, idx, -1),
                    adv28=np.where(alive, 1e7 * (N - np.arange(N))[None, :], np.nan), sigma=sigma,
                    eligible=alive & traded & (idx >= 60), perp_ok=np.zeros((T_, N), dtype=bool),
                    funding=np.zeros((T_, N)), btc_on=np.arange(T_) % 100 < 70, btc=names.index("BTCUSDT"))


def columns(P: fc.Panel, keep: list[int]) -> fc.Panel:
    """The same panel with only the columns `keep`."""
    two = {f.name: getattr(P, f.name)[:, keep] for f in dataclasses.fields(P)
           if isinstance(getattr(P, f.name), np.ndarray) and getattr(P, f.name).ndim == 2}
    names = [P.names[j] for j in keep]
    return dataclasses.replace(P, **two, names=names, bases=[P.bases[j] for j in keep], btc=names.index("BTCUSDT"))


# ---------------------------------------------------------------- the rule and the universe

def test_the_ranking_is_breakout_top10s_on_the_same_candles():
    P = panel([f"{c}USDT" for c in ONCHAIN])                 # 12 coins, all with a mint
    W = S.targets(P)
    assert np.allclose(W, F.targets(P)["breakout_top10"], equal_nan=True)
    top10 = P.top_liquid(10)
    ref = fam_breakout.breakout_weights(P, np.flatnonzero(top10.any(0)), top10, 20, 10, regime=False)
    assert np.allclose(W, ref, equal_nan=True)
    held = np.nan_to_num(W) > 0
    assert held.any() and not held[:, 10:].any()             # only the day's ten most liquid are entered
    t = P.T - 1
    assert np.allclose(F.backtest_weights(P, W, t), F.backtest_weights(P, F.targets(P)["breakout_top10"], t))


def test_the_universe_is_the_mint_list_and_others_never_enter():
    assert S.universe() == tuple(M.COINS) and "NEAR" not in S.universe() and "USDC" not in S.universe()
    names = ["NEARUSDT", "DOGEUSDT", "SUIUSDT"] + [f"{c}USDT" for c in ONCHAIN if c not in ("JUP", "POPCAT")]
    P = panel(names, seed=5)                                  # the three most liquid coins have no mint
    W = S.targets(P)
    assert (np.nan_to_num(W[:, :3]) == 0).all()
    member = list(range(3, len(names)))
    sub = columns(P, member)
    assert np.allclose(W[:, member], F.targets(sub)["breakout_top10"], equal_nan=True)   # the rule on our coins alone
    unrestricted = F.targets(P)["breakout_top10"]
    assert (np.nan_to_num(unrestricted[:, :3]) > 0).any()    # breakout_top10 itself would pick them
    sig = S.signal(P, W, P.T - 1, int(P.days[-1]) + 2 * fc.DAY_US)
    assert set(sig["weights"]) <= set(M.COINS) and sig["no_history"] == ["JUP", "POPCAT"]
    want = F.backtest_weights(P, W, P.T - 1)
    assert sig["weights"] == {fc.base_of(P.names[j]): round(float(want[j]), 6) for j in np.flatnonzero(want > 0)}
    assert sig["strategy"] == B.SOL_NAME and sig["experimental"] and sig["autopilot_only"]
    assert sig["evidence"]["experimental"] and sig["evidence"]["explicit_only"]


# ---------------------------------------------------------------- the target file and the paper twin

@pytest.fixture
def daily(lab, monkeypatch):                                  # noqa: F811 - the imported fixture
    """sol_book.main on a synthetic panel that ends yesterday, a fake Jupiter, everything written under lab."""
    yesterday = (time.time_ns() // 1000 // fc.DAY_US - 1) * fc.DAY_US
    P = panel([f"{c}USDT" for c in ONCHAIN if c != "POPCAT"], seed=3, last_day_us=yesterday)
    monkeypatch.setattr(fc, "load_panel", lambda fresh=False: P)
    monkeypatch.setattr(tsmom, "WRITE_ROOT", lab)
    monkeypatch.setattr(B, "WRITE_ROOT", lab)
    pools = Pools({**MIDS, **{c: 1.0 for c in M.COINS if c not in MIDS}})
    pools.calls = 0
    monkeypatch.setattr(S, "Jupiter", lambda fetch=None: pools)
    monkeypatch.setattr(S, "default_fetch", lambda: None)
    return P


def test_the_daily_run_writes_the_targets_the_live_service_reads(lab, daily):  # noqa: F811
    assert S.main([]) == 0
    f = lab / "signals" / "onchain_breakout_sol" / "latest.json"
    sig = json.loads(f.read_text())
    want = S.signal(daily, S.targets(daily), daily.T - 1, time.time_ns() // 1000)["weights"]
    assert sig["weights"] == want and sig["weights"] and sig["no_history"] == ["POPCAT"]
    got, why = B.read_signal(lab, int(time.time() * 1000), B.BOOKS[B.SOL_NAME]["signal"])
    assert why == "fresh" and got["weights"] == want
    assert B.read_signal(lab, int(time.time() * 1000))[0] is None    # the mirror's signal is another file


def test_a_dry_run_or_stale_candles_write_no_targets(lab, daily, monkeypatch):  # noqa: F811
    assert S.main(["--dry-run"]) == 0
    assert not (lab / "signals").exists() and not B.book_dir(lab, B.SOL_NAME).exists()
    old = panel([f"{c}USDT" for c in ONCHAIN], last_day_us=int(daily.days[-1]) - 3 * fc.DAY_US)
    monkeypatch.setattr(fc, "load_panel", lambda fresh=False: old)
    assert S.main([]) == 1 and not (lab / "signals").exists()


def test_the_paper_twin_journals_like_the_mirror_and_shows_in_the_forward_report(lab, daily, monkeypatch):  # noqa: F811
    assert S.main([]) == 0
    d = B.book_dir(lab, B.SOL_NAME)
    assert d == lab / "paper" / "onchain_breakout_sol"
    rows = list(csv.DictReader((d / "journal.csv").open()))
    assert list(rows[0]) == B.JOURNAL_COLS and len(rows) == 1
    sig = json.loads((lab / "signals" / "onchain_breakout_sol" / "latest.json").read_text())
    st = json.loads((d / "state.json").read_text())
    assert st["variant"] == B.SOL_VARIANT and set(st["units"]) == set(sig["weights"])
    assert st["signal"]["targets"] == pytest.approx(sig["weights"]) and st["signal"]["no_history"] == ["POPCAT"]
    assert int(rows[0]["swaps"]) == len(sig["weights"]) and float(rows[0]["exposure"]) == pytest.approx(
        sum(sig["weights"].values()), abs=0.01)
    assert not (d / "probes.csv").exists()                    # the per coin probes are the mirror book's
    assert not B.book_dir(lab).exists()                       # the mirror book is untouched
    rep = json.loads((lab / "reports" / "onchain_sol" / "latest.json").read_text())
    assert rep["book"] == B.SOL_NAME and rep["title"] == "On-chain book among Solana coins"
    assert "POPCAT" in (lab / "reports" / "onchain_sol" / "latest.md").read_text()
    books = {b["name"]: b for b in FR.paper_books(lab)}
    assert books[B.SOL_NAME]["variant"] == B.SOL_VARIANT
    # The hourly mark marks it too.
    assert B.mark_only(Pools({**MIDS, **{c: 1.0 for c in M.COINS if c not in MIDS}}), write_root=lab,
                       name=B.SOL_NAME) is not None
    assert (d / "marks.csv").exists()


# ---------------------------------------------------------------- the live service

ALPHA_SOL = TW.ALPHA.replace("books=onchain_breakout_top10_live", "books=onchain_breakout_sol")


def test_the_gate_knows_the_book_and_the_test_mode_still_needs_the_proof():
    a = LG.Ack(mode="alpha", books=(B.SOL_NAME,), mints=("SOL", "USDC"))
    assert LG.book_problems(B.SOL_NAME, a, None, T.NOW) == []
    assert any("does not name" in w for w in LG.book_problems(B.SOL_NAME, LG.Ack(mode="alpha"), None, T.NOW))
    t = LG.Ack(mode="test", books=(B.SOL_NAME,), mints=("SOL", "USDC"))
    assert any("no proof report" in w for w in LG.book_problems(B.SOL_NAME, t, None, T.NOW))


def test_the_alpha_service_trades_the_book_when_the_ack_names_it(tmp_path, monkeypatch):
    tr, fc_ = T.trader(tmp_path, monkeypatch, chain=TW.Chain20(out_raw=1_998_000_000),
                       answer=T.build_answer(amount=20_000_000, out=1_998_000_000))
    (tmp_path / "ack").write_text(ALPHA_SOL)
    assert tr.gate.check() == [] and tr.gate.ack.books == (B.SOL_NAME,)
    monkeypatch.setattr(SV.Service, "read_history", lambda self: None)
    svc = SV.Service(gate=tr.gate, trader=tr, load=lambda p: tr.signer, alerts=False)
    svc.start()
    monkeypatch.setattr(LG, "proof_path", lambda: tmp_path / "no-proof.json")
    import lab.data
    monkeypatch.setattr(lab.data, "ROOT", tmp_path)
    mirror = tmp_path / "signals" / "breakout_top10_live" / "latest.json"   # the mirror's signal is not read
    mirror.parent.mkdir(parents=True)
    mirror.write_text(json.dumps({"strategy": "breakout_top10_live", "as_of_ms": 1,
                                  "valid_until_ms": LX.now_ms() + 3_600_000, "weights": {"BTC": 0.9}}))
    svc.run_books()
    assert svc.books[0]["allowed"] is False and "no fresh signal" in svc.books[0]["why"] and not fc_.sent
    sig = tmp_path / "signals" / "onchain_breakout_sol" / "latest.json"
    sig.parent.mkdir(parents=True)
    sig.write_text(json.dumps({"strategy": "onchain_breakout_sol", "as_of_ms": 2,
                               "valid_until_ms": LX.now_ms() + 3_600_000, "weights": {"SOL": 0.5, "JUP": 0.1}}))
    svc.run_books()
    assert svc.books == [{"book": B.SOL_NAME, "allowed": True, "why": None}]
    planned = [o for o in LX._read_jsonl(LX.orders_path()) if o["what"] == "planned"]
    # book_usd 80: SOL's 40 USD as two swaps under the alpha cap of 25; JUP is not in the ack's mints: cash.
    assert [(o["to"], o["in_raw"], o["book"]) for o in planned] == [("SOL", 20_000_000, B.SOL_NAME)] * 2
    svc.run_books()                                           # the same signal: nothing again
    assert len([o for o in LX._read_jsonl(LX.orders_path()) if o["what"] == "planned"]) == 2
