"""L1, the on-chain long-term book onchain_longterm (lab.onchain.longterm): its signal (S2's tsmom1 on BTC and ETH,
ETH capped, the rest USDC), the band and the split on paper and live, the 0.5 SOL paper wallet, the cheapest send path
without Sender (no tip, a low priority fee raised on each new attempt and capped, the slippage fitted to the size), the
owner's ack for the book, the morning briefing's line, and that no cap, gate or other book changed.
Synthetic candles, a fake Jupiter and a fake chain; no lab data, no network, no key.

Run from research/lab:  python -m pytest tests/test_onchain_longterm.py
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import re
from pathlib import Path

import numpy as np
import pytest

from lab.experiments import fam_common as fc
from lab.experiments import smallaccount as s1
from lab.onchain import book as B
from lab.onchain import fees as F
from lab.onchain import guard as G
from lab.onchain import live_exec as LX
from lab.onchain import live_gate as LG
from lab.onchain import longterm as L
from lab.onchain import mints as M
from lab.onchain.paper import PaperExecutor
from lab.ops import briefing, notify
from lab.pumpfun_rt import live_exec as PX
from lab.pumpfun_rt import txbuild as X

import test_onchain_live as T
from test_i18n import no_english
from test_onchain import MIDS, NOW, Pools, lab  # noqa: F401 - lab is a fixture
from test_onchain_sol import panel

NAME = "onchain_longterm"
RESULTS = Path(__file__).resolve().parents[1] / "results" / "onchain_longterm_l1.md"


# ---------------------------------------------------------------- the signal

def test_the_signal_is_s2s_tsmom1_on_btc_and_eth_with_eth_capped_and_the_rest_usdc():
    P = panel(["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT"], seed=7)
    W = s1.ffill(s1.candidate(P, "tsmom_top20", 1))
    assert np.allclose(L.rule(P), W)
    seen = set()
    for t in range(60, P.T):
        w, dropped = L.weights_at(P, t, W)
        held = {fc.base_of(P.names[j]): float(W[t, j]) for j in np.flatnonzero(W[t] > 0)}
        assert set(w) <= {"BTC", "ETH"} and sum(w.values()) <= 1 + 1e-9
        for c, x in held.items():
            seen.add(c)
            if c == "BTC":
                assert w["BTC"] == pytest.approx(round(x, 6)) and not dropped
            elif c == "ETH":
                assert w["ETH"] == pytest.approx(min(x, L.MAX_ETH)) and w["ETH"] <= L.MAX_ETH
                assert dropped.get("ETH", 0.0) == pytest.approx(max(x - L.MAX_ETH, 0.0), abs=1e-6)
            else:                                                  # SOL or DOGE most liquid: USDC that day
                assert c not in w and dropped[c] == pytest.approx(x, abs=1e-6)
        if not held:
            assert w == {} and dropped == {}
    assert "BTC" in seen
    sig = L.signal(P, P.T - 1, int(P.days[-1]) + 2 * fc.DAY_US)
    assert sig["strategy"] == NAME and sig["cadence"] == "daily" and sig["experimental"] and sig["autopilot_only"]
    assert sig["valid_until_ms"] - sig["generated_ms"] == L.SIGNAL_VALID_MS == 36 * 3_600_000
    assert sig["universe"] == ["BTC", "ETH"] and sig["weights"] == L.weights_at(P, P.T - 1, W)[0]


def test_the_signal_names_only_mints_the_trader_and_its_guard_accept():
    for c in L.HOLD:
        m = M.COINS[c]
        assert m.mint in G.ROUTE_MINTS and c in LG.CODES
    assert L.MAX_ETH == LG.MAX_ETH_SHARE
    assert {"SPYx", "PAXG"}.isdisjoint({m.symbol for m in M.COINS.values()})   # Token-2022: the guard refuses them


# ---------------------------------------------------------------- the band and the split

def test_the_band_is_ten_percent_of_the_book_or_three_usd_and_only_this_book_has_it():
    assert B.min_trade(NAME, 50.0) == pytest.approx(5.0)
    assert B.min_trade(NAME, 20.0) == pytest.approx(3.0)
    assert B.min_trade(NAME, 500.0) == pytest.approx(50.0)
    for other in (B.NAME, B.SOL_NAME):
        assert B.min_trade(other, 50.0) == B.MIN_TRADE
        assert B.min_trade(other, 50.0, LG.MIN_BOOK_SWAP_USD) == LG.MIN_BOOK_SWAP_USD == 25.0
    st = {"usdc": 30.0, "units": {"BTC": 20.0 / 80_000}, "marks": {"BTC": 80_000.0}}
    eq = 50.0
    assert B.plan(st, {"BTC": 0.48}, eq, B.min_trade(NAME, eq)) == ([], [])           # 4 USD under the band
    sells, buys = B.plan(st, {"BTC": 0.52}, eq, B.min_trade(NAME, eq))
    assert sells == [] and buys == [("BTC", pytest.approx(6.0))]
    sells, buys = B.plan(st, {}, eq, B.min_trade(NAME, eq))                            # leaving: sold whole
    assert sells == [("BTC", pytest.approx(20.0 / 80_000))] and buys == []


def test_an_order_above_a_quarter_of_the_wallet_goes_as_pieces_on_paper():
    assert B.pieces(40.0, None) == [40.0] and B.pieces(10.0, 12.5) == [10.0]
    assert B.pieces(40.0, 12.5) == pytest.approx([10.0] * 4)
    pools = Pools(MIDS)
    ex = PaperExecutor(pools, pools.prices(list(M.BY_MINT)), priority=B.BOOKS[NAME]["priority_sol"], roundtrip=False)
    st = {"usdc": 50.0, "units": {}, "marks": {"BTC": 80_000.0}}
    fills, errors = B.rebalance(st, {"BTC": 0.8}, ex, 50.0, B.min_trade(NAME, 50.0), 0.25 * 50.0)
    assert not errors and len(fills) == 4 and all(f.usdc <= 0.25 * 50 * 0.98 + 1e-9 for f in fills)
    assert sum(f.usdc for f in fills) == pytest.approx(40.0)
    assert all(f.fee_sol == pytest.approx(0.000005 + 0.00002) for f in fills)
    fills, _ = B.rebalance(st, {}, ex, B.mark(st, MIDS), 5.0, 0.25 * 50.0)               # out: sold in pieces too
    assert len(fills) == 4 and "BTC" not in st["units"]


def test_live_book_swaps_use_the_band_and_the_wallets_usdc_and_the_other_books_do_not(tmp_path, monkeypatch):
    tr, fc_ = T.trader(tmp_path, monkeypatch)                    # 50 USDC, 1 SOL at 10, 0.00001 BTC: 61 USD
    tr.gate.ack_path.write_text(L.ACK)
    assert tr.gate.check() == []
    ack, v = tr.gate.ack, T.view(tr)
    assert ack.books == (NAME,) and ack.wallet
    swaps = LX.book_swaps(NAME, ack, v, {"BTC": 0.5})              # 22.5 USD of 45, a swap at most 15.25
    assert [(s.src, s.dst) for s in swaps] == [("USDC", "BTC")] * 2 and sum(s.in_raw for s in swaps) == 22_500_000
    LX.write_row({"t": 1, "kind": "book", "book": NAME, "from": "USDC", "to": "BTC", "in_raw": 20_000_000,
                  "out_raw": 20_000, "status": "filled"})              # 0.0002 BTC, 20 USD at 100,000
    assert LX.book_swaps(NAME, ack, v, {"BTC": 0.5}) == []         # 22.5 against 20: under the 4.5 USD band
    swaps = LX.book_swaps(NAME, ack, v, {"BTC": 0.6})              # 27 against 20: 7 USD, under 25 but over the band
    assert [(s.src, s.dst, s.in_raw) for s in swaps] == [("USDC", "BTC", 7_000_000)]
    other = LG.Ack(**{**ack.__dict__, "books": ("onchain_breakout_top10_live",)})
    LX.write_row({"t": 1, "kind": "book", "book": "onchain_breakout_top10_live", "from": "USDC", "to": "BTC",
                  "in_raw": 20_000_000, "out_raw": 20_000, "status": "filled"})
    assert LX.book_swaps("onchain_breakout_top10_live", other, v, {"BTC": 0.6}) == []   # 7 USD under its 25
    # The owner's share of a wallet whose coins rose: the book never counts more USDC than the wallet holds.
    swaps = LX.book_swaps(NAME, ack, v, {"BTC": 0.6}, book_usd=200.0)
    st_cash = min(LX.book_state(NAME, 200.0)["usdc_raw"], v.held("USDC"))
    want = 0.6 * (st_cash / 1e6 + 20.0) - 20.0
    assert sum(s.in_raw for s in swaps) == pytest.approx(want * 1e6, abs=2)


# ---------------------------------------------------------------- the paper wallet

def lt_signal(root, weights, as_of=NOW - 86_400_000):
    d = root / "signals" / NAME
    d.mkdir(parents=True, exist_ok=True)
    (d / "latest.json").write_text(json.dumps({"strategy": NAME, "as_of_ms": as_of, "valid_until_ms": NOW + 86_400_000,
                                               "weights": weights}))


def test_the_paper_wallet_starts_as_half_a_sol_keeps_the_reserve_and_trades_with_the_live_rules(lab):  # noqa: F811
    spec = B.BOOKS[NAME]
    assert (spec["start_sol"], spec["reserve_sol"], spec["band"], spec["split"]) == (0.5, 0.035, (0.10, 3.0), 0.25)
    lt_signal(lab, {"BTC": 0.8})
    pools = Pools(MIDS)                                            # SOL at 100: a 50 USD wallet
    row = B.step(pools, NOW, root=lab, write_root=lab, probes=False, name=NAME)
    st = json.loads((B.book_dir(lab, NAME) / "state.json").read_text())
    assert st["funded"] and st["start_usdc"] == pytest.approx(50.0) and st["reserve_sol"] == pytest.approx(0.035)
    trades = list(csv.DictReader((B.book_dir(lab, NAME) / "trades.csv").open()))
    sol = [t for t in trades if t["coin"] == "SOL"]
    btc = [t for t in trades if t["coin"] == "BTC"]
    assert len(sol) == 4 and all(t["side"] == "sell" for t in sol)          # 46.5 USD of SOL, a swap at most 12.5
    assert len(btc) == 4 and all(float(t["usdc"]) <= 12.25 + 1e-6 for t in btc)
    assert sum(float(t["usdc"]) for t in btc) == pytest.approx(0.8 * (st["equity_usdc"] - 3.5), rel=0.01)
    assert all(float(t["fee_usdc"]) == pytest.approx(0.000025 * 100) for t in trades)
    assert row["equity"] == pytest.approx(row["equity_usdc"] / 50.0 * 10_000, abs=0.01)
    assert 9_950 < row["equity"] < 10_000 and row["swaps"] == 8
    data = json.loads((lab / "reports" / NAME / "latest.json").read_text())
    assert data["start_usdc"] == pytest.approx(50.0) and set(data["held"]) == {"BTC"}
    md = (lab / "reports" / NAME / "latest.md").read_text()
    assert "0.0350 SOL kept for fees" in md and "started with 50.00" in md
    # The next day: a drift under the band trades nothing, the hourly mark keeps the 10,000 basis.
    lt_signal(lab, {"BTC": 0.82}, as_of=NOW)
    row = B.step(pools, NOW + 86_400_000, root=lab, write_root=lab, probes=False, name=NAME)
    assert row["swaps"] == 0
    eq = B.mark_only(pools, NOW + 90_000_000, write_root=lab, name=NAME)
    st = json.loads((B.book_dir(lab, NAME) / "state.json").read_text())
    assert st["equity"] == pytest.approx(eq / 50.0 * 10_000)


def test_funding_finishes_once_only_the_reserve_is_left_and_waits_for_a_sol_price():
    pools = Pools(MIDS)
    ex = PaperExecutor(pools, pools.prices(list(M.BY_MINT)), priority=0.00002, roundtrip=False)
    st = {"usdc": 46.0, "units": {}, "marks": {"SOL": 100.0}, "reserve_sol": 0.035, "funded": False}
    assert B.fund(st, ex, 0.035, 12.5) == ([], []) and st["funded"]
    st = {"usdc": 0.0, "units": {}, "marks": {}, "reserve_sol": 0.5, "funded": False}
    fills, errors = B.fund(st, ex, 0.035, 12.5)
    assert fills == [] and errors and not st["funded"]


def test_the_other_books_paper_accounts_are_as_before(lab):  # noqa: F811
    st = B.new_state(NOW)
    assert st["usdc"] == B.START_USDC and "reserve_sol" not in st and B.start_of(st) == B.START_USDC
    assert B.reserve_usdc(st) == 0.0
    for name in (B.NAME, B.SOL_NAME):
        assert not {"start_sol", "band", "split", "priority_sol", "cheap", "wallet_cash"} & set(B.BOOKS[name])


# ---------------------------------------------------------------- the cheapest send path

class FeeChain(T.FakeChain):
    """The fake chain with getRecentPrioritizationFees answering `fees` (micro-lamports per unit)."""

    def __init__(self, fees=(), **kw):
        super().__init__(**kw)
        self.fees = list(fees)

    def __call__(self, method, params):
        if method == "getRecentPrioritizationFees":
            self.calls.append(method)
            return {"result": [{"slot": i, "prioritizationFee": f} for i, f in enumerate(self.fees)]}
        return super().__call__(method, params)


def cheap_trader(tmp_path, monkeypatch, chain=None, sender=None, slip=15):
    tmp_path.mkdir(parents=True, exist_ok=True)
    tr, fc_ = T.trader(tmp_path, monkeypatch, chain=chain, answer=T.build_answer(out=999_000_000, slip=slip))
    tr.gate.ack_path.write_text(L.ACK)
    assert tr.gate.check() == []
    if sender is not None:
        tr.sender, tr.tip_l = PX.Rpc("https://sender.example.org", poster=sender), 5_000
    return tr, fc_


def sent(kind=None):
    return [o for o in LX._read_jsonl(LX.orders_path()) if o["what"] == "sent" and (kind is None or o["kind"] == kind)]


def test_the_cheapest_path_sends_to_the_plain_rpc_without_sender_and_without_a_tip(tmp_path, monkeypatch):
    assert LG.ENV_SENDER not in T.armed(tmp_path).env
    tr, fc_ = cheap_trader(tmp_path, monkeypatch, chain=FeeChain())
    assert tr.sender is None and tr.gate.sender() is None
    swap = LX.Swap("book", "USDC", "SOL", 10_000_000, book=NAME)
    assert tr.cheap(swap) and not tr.cheap(LX.Swap("convert", "USDC", "SOL", 10_000_000))
    assert not tr.cheap(LX.Swap("book", "USDC", "SOL", 10_000_000, book="onchain_breakout_sol"))
    r = tr.execute(swap, T.view(tr))
    assert r["status"] == "filled" and len(fc_.sent) >= 1 and "getRecentPrioritizationFees" in fc_.calls
    o = sent()[0]
    assert o["fees"]["tip_l"] == 0 and 0 < o["fees"]["priority_l"] <= F.CHEAP_MAX_PRIORITY_L
    assert o["fees"]["price"] == F.FLOOR_MICRO                        # no recent fees: the floor
    assert LX.read_execution()[-1]["via"] == "rpc"


def test_the_cheapest_path_never_uses_sender_or_tips_even_when_sender_is_set(tmp_path, monkeypatch):
    got = []

    def sender(method, params):
        got.append(method)
        return {"result": "x"}
    tr, fc_ = cheap_trader(tmp_path, monkeypatch, chain=FeeChain(), sender=sender)
    r = tr.execute(LX.Swap("book", "USDC", "SOL", 10_000_000, book=NAME), T.view(tr))
    assert r["status"] == "filled" and got == [] and sent()[0]["fees"]["tip_l"] == 0
    assert not any(ix.program == X.SYSTEM and len(ix.accounts) == 2 and ix.accounts[1][0] in X.HELIUS_TIP_ACCOUNTS
                   for ix in T.T.decompile(tr.signer.signed[0], {T.TABLE: T.POOL}).ixs)
    tr2, fc2 = cheap_trader(tmp_path / "b", monkeypatch, chain=FeeChain(), sender=sender, slip=30)
    r = tr2.execute(LX.Swap("convert", "USDC", "SOL", 10_000_000), T.view(tr2))   # the owner's convert: as before
    assert r["status"] == "filled" and "sendTransaction" in got and sent("convert")[0]["fees"]["tip_l"] == 5_000


def test_each_new_attempt_bids_a_little_more_and_never_above_the_cap(tmp_path, monkeypatch):
    tr, fc_ = cheap_trader(tmp_path, monkeypatch, chain=FeeChain(fees=[0, 2_000, 4_000, 8_000, 16_000], never_land=True))
    r = tr.execute(LX.Swap("book", "USDC", "SOL", 10_000_000, book=NAME), T.view(tr))
    assert r["status"] == "failed" and "3 tries" in r["why"]
    prices = [o["fees"]["price"] for o in sent()]
    assert len(prices) == 3 and prices[0] == 4_000                   # the 25th percentile of the non-zero fees
    assert prices[1] >= prices[0] * F.CHEAP_STEP and prices[2] >= prices[1] * F.CHEAP_STEP
    assert all(o["fees"]["priority_l"] <= F.CHEAP_MAX_PRIORITY_L for o in sent())
    tr, fc_ = cheap_trader(tmp_path / "hot", monkeypatch, chain=FeeChain(fees=[5_000_000] * 10))
    tr.execute(LX.Swap("book", "USDC", "SOL", 10_000_000, book=NAME), T.view(tr))
    o = sent()[-1]
    assert o["fees"]["priority_l"] <= F.CHEAP_MAX_PRIORITY_L and o["fees"]["price"] == F.CHEAP_MAX_PRIORITY_L * 1_000_000 // 250_000


def test_cheap_price_percentiles_floor_step_and_cap():
    assert F.cheap_price([], 250_000) == (F.FLOOR_MICRO, F.FLOOR_MICRO * 250_000 // 1_000_000)
    rows = [{"prioritizationFee": f} for f in (0, 1_000, 3_000, 9_000, 20_000)]
    assert F.cheap_price(rows, 200_000, 1)[0] == 3_000
    assert F.cheap_price(rows, 200_000, 2)[0] == 9_000
    assert F.cheap_price(rows, 200_000, 3)[0] == 9_000 and F.cheap_price(rows, 200_000, 3, 9_000)[0] == 13_500
    micro, lam = F.cheap_price([{"prioritizationFee": 10 ** 9}], 1_400_000, 1)
    assert lam <= F.CHEAP_MAX_PRIORITY_L == 20_000 and micro == 20_000 * 1_000_000 // 1_400_000
    assert F.CHEAP_MAX_PRIORITY_L < F.MAX_PRIORITY_SOL * F.LAMPORTS and F.CHEAP_MAX_PRIORITY_L < G.MAX_PRIORITY_L


def test_the_fitted_slippage_is_tighter_for_small_swaps_and_never_looser(tmp_path, monkeypatch):
    assert LG.fitted_slippage("USDC", "BTC", 10.0) == 15 and LG.fitted_slippage("BTC", "USDC", 60.0) == 20
    assert LG.fitted_slippage("USDC", "BTC", 500.0) == LG.slippage("USDC", "BTC") == 30
    assert LG.fitted_slippage("USDC", "BTC", None) == 30
    for a in LG.SLIPPAGE_BPS:
        for b in LG.SLIPPAGE_BPS:
            for usd in (1.0, 20.0, 80.0, 1_000.0):
                assert LG.fitted_slippage(a, b, usd) <= LG.slippage(a, b)
    tr, fc_ = cheap_trader(tmp_path, monkeypatch, chain=FeeChain())
    v = T.view(tr)
    p = tr.prepare(LX.Swap("book", "USDC", "SOL", 10_000_000, book=NAME), v)
    assert p.plan.slippage_bps == 15 and p.plan.min_out_raw == G.min_out(999_000_000, 15)
    tr, fc_ = cheap_trader(tmp_path / "c", monkeypatch, chain=FeeChain())           # Jupiter's 15 above a convert's 30?
    p = tr.prepare(LX.Swap("convert", "USDC", "SOL", 10_000_000), T.view(tr))
    assert p.plan.slippage_bps == 30                                                # the convert keeps its own


# ---------------------------------------------------------------- the owner's ack and what stays

def test_the_ack_in_the_results_parses_for_the_new_book_and_matches_the_code(tmp_path):
    text = RESULTS.read_text(encoding="utf-8")
    block = re.search(r"```\n(mode=alpha\n.*?)```", text, re.S).group(1)
    assert block == L.ACK
    env = re.search(r"```\n(PYTHIA_ONCHAIN_LIVE=1\n.*?)```", text, re.S).group(1)
    assert env == L.ENV and LG.ENV_SENDER not in env and "TIP" not in env and "KEY" not in env.replace("KEYPAIR", "")
    p = tmp_path / "ack"
    p.write_text(L.ACK)
    a = LG.read_ack(p, dt.date(2026, 10, 26))
    assert a.problems == () and a.mode == "alpha" and a.books == (NAME,) and a.wallet and a.on_kill == "hold"
    assert a.mints == ("SOL", "USDC", "BTC", "ETH") and a.book_usd == 45
    assert LG.book_problems(NAME, a, None, NOW) == []                 # alpha: named and with a paper twin
    assert LG.book_problems(NAME, LG.Ack(**{**a.__dict__, "mode": "test"}), None, NOW)   # test mode: the proof
    assert LX.LG.send_problems({LG.ENV_RPC: "https://api.mainnet-beta.solana.com"}) == []
    for line in ("mode=alpha", "books=onchain_longterm", "limits=wallet", "on_kill=hold"):
        assert line in text
    assert "\u2014" not in text


def test_no_cap_gate_or_guard_limit_moved():
    assert (G.MAX_PRIORITY_L, G.MAX_UNITS, LG.RESERVE_L, LG.MIN_BOOK_SWAP_USD) == (500_000, 1_400_000, 20_000_000, 25.0)
    assert (LG.WALLET_MAX_SWAP_SHARE, LG.MAX_ETH_SHARE, LG.MAX_COST_BPS, LG.MAX_PRICE_GAP_PCT) == (0.25, 0.25, 50.0, 2.0)
    assert (LG.ALPHA_MAX_TOTAL_USD, LG.ALPHA_MAX_TRADE_USD, LG.ALPHA_MAX_DAILY_LOSS_USD) == (100, 25, 25)
    assert LG.SLIPPAGE_BPS["BTC"] == LG.SLIPPAGE_BPS["USDC"] == 30 and LX.MAX_ATTEMPTS == 3
    spec = B.BOOKS[NAME]
    assert spec["split"] == LG.WALLET_MAX_SWAP_SHARE
    assert spec["priority_sol"] == F.CHEAP_MAX_PRIORITY_L / F.LAMPORTS
    reserve = (LG.RESERVE_L + G.MAX_PRIORITY_L + G.BASE_FEE_L + X.HELIUS_MAX_TIP_LAMPORTS + G.ATA_RENT_L) / 1e9
    assert spec["reserve_sol"] >= reserve + 3 * G.ATA_RENT_L / 1e9    # the caps' reserve and the three token accounts


# ---------------------------------------------------------------- the cost per swap, the briefing

def test_the_cost_per_swap_on_the_recorded_quotes():
    rows = L.cost_rows(sol_usd=100.0)
    assert {r["coin"] for r in rows} == {"BTC", "ETH"} and {r["usd"] for r in rows} >= {5.0, 10.0, 25.0, 50.0}
    for r in rows:
        assert r["cheap_bps"] <= r["cheap_cap_bps"] < r["default_bps"]
        assert r["cheap_usd"] == pytest.approx(0.0025) and r["default_usd"] == pytest.approx(0.011)


def test_the_briefing_shows_the_long_term_paper_wallet():
    rep = {"equity_usdc": 51.2, "start_usdc": 50.0, "held": {"BTC": 0.62}}
    de, en = briefing.onchain_line(rep, "de"), briefing.onchain_line(rep, "en")
    assert de.lead == "On-Chain-Langfristbuch (Papier, 0,5 SOL)" and de.text == "51,20 $ (+1,20 $) · BTC 62 %"
    assert en.text == "$51.20 (+$1.20) · BTC 62 %"
    assert briefing.onchain_line({"equity_usdc": 49.0, "start_usdc": 50.0, "held": {}}, "en").text.endswith("· USDC")
    assert briefing.onchain_line(None, "de") is None and briefing.onchain_line({"equity_usdc": 1.0}, "de") is None
    parts, _, _ = briefing.paper_section(None, None, None, {}, NOW, "de", None, rep)
    assert [p.text for p in parts] == [de.text]
    no_english(notify.render_post([notify.Card("📈", "Papier", None, parts)], "telegram", lang="de"))
    assert NAME in briefing.NOT_STUDIES
