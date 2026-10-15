"""W3, the extended Alpaca universe: universe settings, coverage, the study's books and report,
and the paper books' universe option. No lab data.

Run from research/lab:  python -m pytest tests
"""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pytest

from lab import universe as uni
from lab.experiments import alpaca36 as a36
from lab.experiments import alpaca_universe as au
from lab.experiments import fam_common as fc
from lab.paper import families

T = 1000
NAMES = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "ARBUSDT", "TRXUSDT", "CRVUSDT", "LDOUSDT", "DOGEUSDT", "PEPEUSDT",
         "BONKUSDT", "WIFUSDT", "SHIBUSDT", "LUNAUSDT", "LDOUSDT~0"]
FIRST = int(datetime(2022, 9, 1, tzinfo=timezone.utc).timestamp() * 1e6)


def make_panel() -> fc.Panel:
    N = len(NAMES)
    rng = np.random.default_rng(11)
    ret = rng.normal(0.0015, 0.04, (T, N))
    ret[:, 7:12] *= 2.0                         # memecoins swing more
    ret[0] = np.nan
    idx = np.arange(T)[:, None]
    first = np.zeros(N, dtype=int)
    first[10] = 500                             # WIF lists late: short history
    first[3] = 200
    alive = idx >= first[None, :]
    alive[400:, 12] = False                     # LUNA dies
    px = 100 * np.cumprod(1 + np.where(alive, np.nan_to_num(ret), 0.0), axis=0)
    px[~alive] = np.nan
    ret = np.where(alive & np.roll(alive, 1, 0), ret, np.nan)
    ret[0] = np.nan
    traded = alive.copy()
    close = np.where(traded, px, np.nan)
    days = FIRST + np.arange(T, dtype=np.int64) * fc.DAY_US
    age = np.where(alive, idx - first[None, :], -1)
    return fc.Panel(days=days, names=list(NAMES), bases=[fc.base_of(n) for n in NAMES], close=close, px=px,
                    high=px, low=px, ret=ret, alive=alive, traded=traded, age=age,
                    adv28=np.where(alive, 1e7 * (N - np.arange(N))[None, :], np.nan),
                    sigma=np.full((T, N), 0.04), eligible=alive & traded & (age >= 60),
                    perp_ok=np.zeros((T, N), dtype=bool), funding=np.zeros((T, N)),
                    btc_on=np.arange(T) % 90 < 60, btc=0)


@pytest.fixture()
def panel() -> fc.Panel:
    return make_panel()


# ---------------------------------------------------------------------------
# Universes
# ---------------------------------------------------------------------------

def test_the_lists_match_the_engine():
    assert len(uni.ALPACA) == 32 and len(set(uni.ALPACA)) == 32
    assert set(uni.ALPACA15) <= set(uni.ALPACA) and set(uni.ALPACA15) <= set(uni.LAB20)
    assert set(uni.MEMES) == {"DOGE", "PEPE", "BONK", "SHIB", "TRUMP", "WIF"}
    assert len(uni.CORE) == 26 and not set(uni.CORE) & set(uni.MEMES)
    assert len(uni.ENGINE) == 37 and set(uni.LAB20) <= set(uni.ENGINE)
    assert not set(uni.ALPACA) & set(uni.NOT_TRADED)


def test_parse_reads_the_engines_format():
    assert uni.parse("btc, eth\nbonk # memes") == ("BTC", "ETH", "BONK")
    assert uni.parse("XBTUSD xdg/usd ETH-USD SOLUSDT ADA/EUR ok") == ("BTC", "DOGE", "ETH", "OK")
    assert uni.parse("A TOOLONGTICKER1 9LIVES USDT PAXG") == ()
    mixed = uni.parse("lab20 BONK WIF BTC")
    assert len(mixed) == 22 and mixed[20:] == ("BONK", "WIF")
    assert uni.parse("alpaca") == uni.ALPACA and uni.parse("default") == uni.ENGINE


def test_engine_coins_env_then_file_then_default(tmp_path):
    f = tmp_path / "u.txt"
    f.write_text("SOL\n")
    assert uni.engine_coins({"PYTHIA_CRYPTO_UNIVERSE": "memes"}) == uni.MEMES
    assert uni.engine_coins({"PYTHIA_CRYPTO_UNIVERSE": " # none", "PYTHIA_CRYPTO_UNIVERSE_FILE": str(f)}) == ("SOL",)
    assert uni.engine_coins({"PYTHIA_CRYPTO_UNIVERSE_FILE": str(tmp_path / "missing")}) == uni.ENGINE
    assert uni.engine_coins({}) == uni.ENGINE
    with pytest.raises(ValueError):
        uni.named("USDT")


def test_mask_takes_current_segments_only(panel):
    m = uni.mask(panel, ("LDO", "BTC", "LUNA"))
    assert [panel.names[j] for j in np.flatnonzero(m)] == ["BTCUSDT", "LDOUSDT", "LUNAUSDT"]


def test_coverage_marks_missing_and_short_history(panel):
    cov = {c["coin"]: c for c in uni.coverage(panel, ("BTC", "WIF", "HYPE", "ARB"))}
    assert cov["HYPE"]["history"] == "none" and not cov["HYPE"]["in_panel"]
    assert cov["BTC"]["history"] == "long"
    # WIF lists on day 500 (2024-01-14), after the split: nothing in sample.
    assert cov["WIF"]["history"] == "short" and cov["WIF"]["eligible_days_is"] == 0
    assert cov["ARB"]["first_eligible"] == str(np.datetime64(int(panel.days[260]), "us").astype("datetime64[D]"))


# ---------------------------------------------------------------------------
# The study's books
# ---------------------------------------------------------------------------

def test_core_variants_never_leave_core(panel):
    core = uni.mask(panel, uni.CORE)
    vs = a36.core_variants(panel, core)
    assert len(vs) == 8
    assert sorted({b for b, _, _ in vs}) == ["breakout", "tsmom_daily", "tsmom_tranches"]
    for _, _, W in vs:
        assert np.nan_to_num(W[:, ~core]).max() == 0.0


def test_meme_sleeve_holds_memes_only_and_never_levers(panel):
    memes = uni.mask(panel, uni.MEMES)
    vs = a36.meme_variants(panel, memes)
    assert len(vs) == 3
    for _, _, W in vs:
        assert np.nan_to_num(W[:, ~memes]).max() == 0.0
        _, _, ex, held = au.sim_daily(panel, W)
        assert held.sum(1).max() <= 1 + 1e-9
    W = a36.meme_tsmom(panel, memes)
    assert (W[~panel.btc_on] == 0).all()


def test_sleeve_mix_is_ninety_ten():
    a = tuple(np.full(5, x) for x in (1.0, 2.0, 3.0, 4.0))
    b = tuple(np.full(5, x) for x in (11.0, 12.0, 13.0, 14.0))
    out = a36.sleeve_mix(a, b)
    assert np.allclose(out[0], 0.9 * 1 + 0.1 * 11) and np.allclose(out[3], 0.9 * 4 + 0.1 * 14)


def test_prior_var_reproduces_the_published_bar():
    v = a36.prior_var()
    assert fc._sr0(v, a36.PRIOR_TRIALS) * np.sqrt(365) == pytest.approx(a36.PRIOR_SR0)


def test_judge_rules(panel):
    rng = np.random.default_rng(0)
    T_ = panel.T
    good = (np.full(T_, 0.004) + np.random.default_rng(1).normal(0, 0.01, T_), np.zeros(T_), np.ones(T_), None)
    bad = (np.random.default_rng(2).normal(-0.001, 0.02, T_), np.zeros(T_), np.ones(T_), None)
    j = a36.judge(panel, good, bad, good, None, rng)
    assert j["passes"] and j["failed"] == []
    j = a36.judge(panel, bad, good, bad, good, rng)
    assert not j["passes"]
    assert "1 higher Sharpe, 2 of 3 years" in j["failed"] and "6 meme sleeve positive" not in j["failed"]
    j = a36.judge(panel, good, bad, good, bad, rng)
    assert j["failed"] == ["6 meme sleeve positive"]


def test_the_study_runs_21_trials_and_writes_its_report(panel, tmp_path, monkeypatch):
    monkeypatch.setattr(fc, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(fc, "OUT", tmp_path)
    monkeypatch.setattr(au.tt, "BOOT_DRAWS", 50)
    (tmp_path / "alpaca36.md").write_text("# pre-registered\n\n" + a36.MARKER + "\nold\n", encoding="utf-8")
    res = a36.run_study(panel)
    assert sum(r["counted"] for r in res["rows"]) == a36.HERE_TRIALS
    assert res["pool"]["n_total"] == a36.PRIOR_TRIALS + a36.HERE_TRIALS
    assert len(res["verdicts"]) == 6
    assert {v["book"] for v in res["verdicts"]} == {"a36_breakout", "a36_tsmom", "a36_tranches", "a36_breakout_memes",
                                                    "a36_tsmom_memes", "a36_tranches_memes"}
    for v in res["verdicts"]:
        assert v["passes"] == (v["failed"] == "-")
        assert 0.0 <= v["deflated_p"] <= 1.0
    a36.write(res)
    text = (tmp_path / "alpaca36.md").read_text(encoding="utf-8")
    assert text.startswith("# pre-registered\n\n" + a36.MARKER) and "old" not in text
    assert "### Coverage of the 32 Alpaca coins" in text and "HYPE" in text
    assert (tmp_path / "reports" / "alpaca36.json").exists()


# ---------------------------------------------------------------------------
# Paper books on a universe
# ---------------------------------------------------------------------------

def test_targets_on_a_universe_stay_inside_it_and_default_is_unchanged(panel):
    member = uni.mask(panel, uni.ALPACA)
    W = families.targets(panel, member)
    assert set(W) == set(families.BOOKS)
    for w in W.values():
        assert np.nan_to_num(w[:, ~member]).max() == 0.0
    top10 = panel.top_liquid(10)
    ref = au.breakout_on(panel, top10, 20, 10)
    assert np.allclose(families.targets(panel)["breakout_top10"], ref, equal_nan=True)


def test_universe_books_have_their_own_names():
    assert families.book_name("breakout_top10", None) == "breakout_top10"
    assert families.book_name("breakout_top10", "Alpaca") == "breakout_top10@alpaca"
    assert families.variant("tsmom_top20@core").startswith(families.BOOKS["tsmom_top20"])
    assert "universe core" in families.variant("tsmom_top20@core")
    assert families.ENGINE_COINS == frozenset(uni.engine_coins())
