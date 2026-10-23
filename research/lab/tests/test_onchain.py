"""The on-chain paper book: the mint table, Jupiter's quotes (mocked, no network), fills, rebalances, the journal."""

import csv
import json
import re

import pytest

from lab import report
from lab import universe as uni
from lab.onchain import book as B
from lab.onchain import jupiter as J
from lab.onchain import mints as M
from lab.onchain import paper as P

BASE58 = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")


# ---------------------------------------------------------------- mint table

def test_the_mint_table_has_one_checked_token_per_coin():
    assert M.USDC.decimals == 6 and M.SOL.mint.startswith("So1111")
    seen = set()
    for coin, m in M.COINS.items():
        assert m.coin == coin and BASE58.match(m.mint) and m.mint not in seen
        seen.add(m.mint)
        assert isinstance(m.decimals, int) and 0 <= m.decimals <= 12
        assert m.kraken == f"{coin}/USD" and m.source.startswith("Jupiter verified list")
        assert (m.alpaca == f"{coin}/USD") == (coin in uni.ALPACA)        # stands for the Alpaca coin it names
    assert {"SOL", "BTC", "ETH", "JUP", "BONK", "WIF"} <= set(M.COINS)
    assert not {"NEAR", "SUI", "DOGE", "USDC"} & set(M.COINS)              # no SPL version taken, cash is not a coin
    assert set(M.BY_MINT) == seen | {M.USDC.mint}


def test_raw_and_ui_amounts():
    btc = M.COINS["BTC"]
    assert M.raw(btc, 0.29) == 29_000_000 and M.ui(btc, 29_000_000) == pytest.approx(0.29)
    assert M.raw(M.USDC, 12.3456789) == 12_345_678 and M.raw(M.USDC, -1) == 0


# ---------------------------------------------------------------- quotes

QUOTE = {"inputMint": M.USDC.mint, "inAmount": "100000000", "outputMint": M.SOL.mint, "outAmount": "950000000",
         "otherAmountThreshold": "945000000", "swapMode": "ExactIn", "slippageBps": 50, "platformFee": None,
         "priceImpactPct": "0.0012", "contextSlot": 7,
         "routePlan": [
             {"percent": 100, "swapInfo": {"label": "Whirlpool", "inputMint": M.USDC.mint, "outputMint": "MID",
                                            "inAmount": "100000000", "outAmount": "5000", "feeAmount": "30000",
                                            "feeMint": M.USDC.mint}},
             {"percent": 100, "swapInfo": {"label": "Raydium", "inputMint": "MID", "outputMint": M.SOL.mint,
                                            "inAmount": "5000", "outAmount": "950000000", "feeAmount": "1",
                                            "feeMint": "MID"}}]}


def test_quote_parsing():
    q = J.parse_quote(QUOTE)
    assert (q.in_amount, q.out_amount, q.slot) == (100_000_000, 950_000_000, 7)
    assert q.price_impact_pct == pytest.approx(0.0012) and q.labels == ["Whirlpool", "Raydium"]
    assert q.route_fee_bps == pytest.approx(3 + 2)          # 0.03 % on the first hop, 1 in 5,000 on the second
    assert q.platform_fee_bps == 0
    plain = {k: v for k, v in QUOTE.items() if k != "routePlan"}
    assert J.parse_quote(plain).route_fee_bps is None        # no fee named, none guessed
    with pytest.raises(J.QuoteError):
        J.parse_quote({"error": "no route"})


class Net:
    """A scripted network: each call takes the next (status, headers, body)."""

    def __init__(self, *answers):
        self.answers, self.urls, self.slept, self.t = list(answers), [], [], 1_792_000_000.0

    def fetch(self, url, timeout):
        self.urls.append(url)
        a = self.answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return a

    def sleep(self, s):
        self.slept.append(s)
        self.t += s

    def client(self, **kw):
        return J.Jupiter(fetch=self.fetch, sleep=self.sleep, clock=lambda: self.t, **kw)


def ok(d):
    return 200, {}, json.dumps(d).encode()


def test_the_client_retries_rate_limits_and_timeouts_then_answers():
    net = Net((429, {"Retry-After": "3"}, b"slow down"), TimeoutError("read timed out"), ok(QUOTE))
    q = net.client().quote(M.USDC.mint, M.SOL.mint, 100_000_000)
    assert q.out_amount == 950_000_000 and len(net.urls) == 3
    assert "lite-api.jup.ag/swap/v1/quote?" in net.urls[0] and "amount=100000000" in net.urls[0]
    assert 3.0 in net.slept and 2.0 in net.slept             # Retry-After, then the backoff for the second try


def test_the_client_paces_calls_and_reads_the_reset_header():
    net = Net(ok(QUOTE), (429, {"x-ratelimit-reset": "1792000005"}, b""), ok(QUOTE))
    c = net.client(min_interval=1.1)
    c.quote(M.USDC.mint, M.SOL.mint, 100_000_000)
    c.quote(M.USDC.mint, M.SOL.mint, 100_000_000)
    # the second call waits its turn, the third until the reset the 429 named
    assert net.slept == pytest.approx([1.1, 3.9])
    assert c.calls == 3


def test_the_client_gives_up_and_never_retries_a_bad_request():
    net = Net(*[(503, {}, b"down")] * 3)
    with pytest.raises(J.QuoteError, match="gave up after 3"):
        net.client(retries=2).quote(M.USDC.mint, M.SOL.mint, 1)
    net = Net((400, {}, b"bad mint"), ok(QUOTE))
    with pytest.raises(J.QuoteError, match="HTTP 400"):
        net.client().quote(M.USDC.mint, "x", 1)
    assert len(net.urls) == 1
    with pytest.raises(J.QuoteError):
        Net().client().quote(M.USDC.mint, M.SOL.mint, 0)


def test_a_quote_for_another_pair_amount_or_mode_is_refused():
    # review finding 1 (docs/ONCHAIN-REVIEW.md): booked, such an answer filled the wrong coin or spent
    # more USDC than the account asked to spend
    for bad in ({"outputMint": M.COINS["BONK"].mint}, {"inputMint": M.SOL.mint}, {"inAmount": "900000000"},
                {"swapMode": "ExactOut"}, {"outAmount": "0"}):
        net = Net(ok({**QUOTE, **bad}))
        with pytest.raises(J.QuoteError):
            net.client().quote(M.USDC.mint, M.SOL.mint, 100_000_000)
        assert len(net.urls) == 1                                        # refused, not retried
    for junk in ({"inAmount": "lots"}, {"inputMint": None, "outAmount": None}):
        with pytest.raises(J.QuoteError, match="not a quote"):          # a crash past the book's handlers before
            J.parse_quote({**QUOTE, **junk})
    assert Net(ok(QUOTE)).client().quote(M.USDC.mint, M.SOL.mint, 100_000_000).out_amount == 950_000_000


def test_a_wrong_answer_leaves_the_account_alone():
    class Liar(Pools):
        def quote(self, in_mint, out_mint, amount, slippage_bps=50):
            net = Net(ok({**QUOTE, "inputMint": in_mint, "outputMint": out_mint, "inAmount": str(amount * 10)}))
            return net.client().quote(in_mint, out_mint, amount)
    pools = Liar(MIDS)
    st = state(100.0, {})
    fills, errors = B.rebalance(st, {"SOL": 0.5}, P.PaperExecutor(pools, pools.prices(list(M.BY_MINT))), 100.0)
    assert fills == [] and errors[0].startswith("buy SOL") and st["usdc"] == 100.0 and st["units"] == {}


def test_a_usdc_price_off_its_peg_marks_nothing(lab):
    # review finding 2: USDC's price divides every mark; a broken one wrote a false equity into the journal
    assert B.mids({M.USDC.mint: 0.5, M.SOL.mint: 100.0}) == {}
    assert B.mids({M.USDC.mint: 1.03, M.SOL.mint: 100.0}) == {}
    assert B.mids({M.USDC.mint: 0.999, M.SOL.mint: 100.0}) == {"SOL": pytest.approx(100.1, abs=0.01)}

    class Depeg(Pools):
        def prices(self, mints):
            return {**super().prices(mints), M.USDC.mint: 0.2}
    signal(lab, {"SOL": 0.5})
    B.step(Pools(MIDS), NOW, root=lab, write_root=lab, probes=False)
    with pytest.raises(J.QuoteError, match="peg"):
        B.step(Depeg(MIDS), NOW + DAY, root=lab, write_root=lab, probes=False)
    with pytest.raises(J.QuoteError, match="peg"):
        B.mark_only(Depeg(MIDS), NOW + DAY, write_root=lab)
    assert len(journal(lab)) == 1 and not (B.book_dir(lab) / "marks.csv").exists()


def test_prices():
    net = Net(ok({M.SOL.mint: {"usdPrice": 104.4, "decimals": 9}, M.USDC.mint: {"usdPrice": 0.9995},
                  "junk": None}))
    assert net.client().prices([M.SOL.mint, M.USDC.mint, "junk"]) == {M.SOL.mint: 104.4, M.USDC.mint: 0.9995}
    assert "price/v3?ids=" in net.urls[0]


# ---------------------------------------------------------------- fills

class Pools:
    """A fake Jupiter: every coin at its mid in USDC, `spread` taken on each swap."""

    def __init__(self, mids, spread=0.001, fail=()):
        self.mids, self.spread, self.fail, self.quotes = mids, spread, set(fail), []

    def prices(self, mints):
        out = {M.USDC.mint: 1.0}
        out.update({M.COINS[c].mint: p for c, p in self.mids.items()})
        return {m: p for m, p in out.items() if m in mints}

    def quote(self, in_mint, out_mint, amount, slippage_bps=50):
        a, b = M.BY_MINT[in_mint], M.BY_MINT[out_mint]
        if {a.coin, b.coin} & self.fail or {a.coin, b.coin} - set(self.mids) - {"USDC"}:
            raise J.QuoteError("no route")
        pa, pb = self.mids.get(a.coin, 1.0), self.mids.get(b.coin, 1.0)
        out = int(M.ui(a, amount) * pa / pb * (1 - self.spread) * 10 ** b.decimals)
        self.quotes.append((a.coin, b.coin, amount))
        return J.Quote(in_mint, out_mint, amount, out, 0.0, 10.0, 0.0, ["Fake"], 1)


MIDS = {"SOL": 100.0, "BTC": 80_000.0, "ETH": 2_500.0}


def test_a_buy_gets_the_quote_less_the_network_fee():
    pools = Pools(MIDS)
    ex = P.PaperExecutor(pools, pools.prices(list(M.BY_MINT)), priority=0.0001)
    f = ex.buy("SOL", 100.0)
    fee_usdc = (0.000005 + 0.0001) * 100.0
    assert f.fee_sol == pytest.approx(0.000105) and f.fee_usdc == pytest.approx(fee_usdc)
    assert f.usdc == 100.0 and f.units == pytest.approx(0.999 * (1 - fee_usdc / 100), rel=1e-6)
    fee_bps = fee_usdc / 100 * 1e4
    assert f.mid_cost_bps == pytest.approx(10 + fee_bps, abs=0.01)           # 10 bps spread, ~1 bp fee on 100
    assert f.cost_bps == pytest.approx(10 + fee_bps, abs=0.02)               # half of a 20 bps round trip, plus the fee
    assert f.quote["out_amount"] == pytest.approx(0.999e9, abs=1) and len(pools.quotes) == 2   # and the way back
    s = ex.sell("SOL", f.units)
    assert s.usdc == pytest.approx(f.units * 100 * 0.999 - fee_usdc, rel=1e-6)
    no_rt = P.PaperExecutor(pools, pools.prices(list(M.BY_MINT)), priority=0.0, roundtrip=False).buy("BTC", 50)
    assert no_rt.cost_bps == no_rt.mid_cost_bps


def test_the_priority_fee_comes_from_the_environment_within_bounds():
    assert P.priority_sol({}) == 0.0001
    assert P.priority_sol({"PYTHIA_ONCHAIN_PRIORITY_SOL": "0.00005"}) == 0.00005
    assert P.priority_sol({"PYTHIA_ONCHAIN_PRIORITY_SOL": "5"}) == 0.0001          # an absurd bid is ignored
    assert P.priority_sol({"PYTHIA_ONCHAIN_PRIORITY_SOL": "x"}) == 0.0001


# ---------------------------------------------------------------- rebalance math

def test_targets_keep_only_coins_with_a_mint():
    tgt, dropped = B.split_targets({"SOL": 0.2, "NEAR": 0.1, "BTC": "0.3", "ETH": 0, "X": "y"})
    assert tgt == {"SOL": 0.2, "BTC": 0.3} and dropped == {"NEAR": 0.1}
    tgt, _ = B.split_targets({"SOL": 0.9, "BTC": 0.6})
    assert sum(tgt.values()) == pytest.approx(1.0)


def state(usdc, units):
    st = B.new_state(0)
    st.update(usdc=usdc, units=dict(units))
    return st


def test_the_plan_sells_leavers_whole_trims_and_buys_and_leaves_small_changes():
    st = state(500.0, {"SOL": 2.0, "ETH": 0.1, "BTC": 0.001})
    eq = B.mark(st, MIDS)                       # 500 + 200 + 250 + 80
    assert eq == pytest.approx(1030.0)
    sells, buys = B.plan(st, {"SOL": 0.1, "BTC": 0.08, "JUP": 0.003}, eq)
    assert ("ETH", 0.1) in sells                                       # leaves the book: sold whole
    sol = dict(sells)["SOL"]
    assert sol == pytest.approx(2.0 * (200 - 103) / 200)                # trimmed to 10 %
    assert "BTC" not in dict(sells) and "BTC" not in dict(buys)         # 82.4 against 80: under MIN_TRADE
    assert buys == []                                                   # JUP 3 USDC: under MIN_TRADE


def test_rebalance_sells_first_and_scales_buys_to_the_cash():
    pools = Pools(MIDS, spread=0.0)
    st = state(100.0, {"ETH": 0.2})
    eq = B.mark(st, MIDS)                       # 600
    ex = P.PaperExecutor(pools, pools.prices(list(M.BY_MINT)), priority=0.0)
    fills, errors = B.rebalance(st, {"SOL": 0.8, "BTC": 0.4}, ex, eq)
    assert errors == [] and [f.side for f in fills] == ["sell", "buy", "buy"]
    assert "ETH" not in st["units"] and st["usdc"] == pytest.approx(0.0, abs=1e-4)
    # 600 USDC on hand for 480 + 240 wanted: both scaled by 600 / 720
    assert st["units"]["SOL"] * 100 == pytest.approx(400.0, rel=1e-4)
    assert st["units"]["BTC"] * 80_000 == pytest.approx(200.0, rel=1e-4)


def test_a_failed_quote_leaves_that_coin_alone():
    pools = Pools(MIDS, fail={"ETH"})
    st = state(500.0, {"ETH": 0.2})
    ex = P.PaperExecutor(pools, pools.prices(list(M.BY_MINT)))
    fills, errors = B.rebalance(st, {"SOL": 0.3}, ex, B.mark(st, MIDS))
    assert st["units"]["ETH"] == 0.2 and errors and errors[0].startswith("sell ETH")
    assert [f.coin for f in fills] == ["SOL"]


# ---------------------------------------------------------------- Kraken's side

def test_kraken_costs_from_the_measured_spreads_and_the_engine_fills():
    half = B.kraken_half({"measured": {"kraken": {"SOL": {"halfSpreadBps": 0.5}, "BAD": {}}}})
    assert half == {"SOL": 0.5}
    assert B.kraken_bps("SOL", half) == 40.5 and B.kraken_bps("JUP", half) == 65.0
    st = {"orders": [{"route": "paper", "venue": "crypto", "status": "filled", "realisedSlippageBps": s}
                     for s in (1.0, 3.0, -1.0)] + [{"route": "demo", "venue": "crypto", "status": "filled",
                                                    "realisedSlippageBps": 50.0}]}
    e = B.kraken_paper_fills(st)
    assert e["fills"] == 3 and e["slippage_median_bps"] == 1.0 and e["all_in_median_bps"] == 41.0
    assert B.kraken_paper_fills(None) == {"fills": 0}


# ---------------------------------------------------------------- the journal

DAY = 86_400_000
NOW = 1_792_800_000_000


@pytest.fixture
def lab(tmp_path, monkeypatch):
    monkeypatch.setattr(report, "REPORTS", tmp_path / "reports")
    (tmp_path / "reports" / "costs").mkdir(parents=True)
    (tmp_path / "reports" / "costs" / "latest.json").write_text(
        json.dumps({"measured": {"kraken": {"SOL": {"halfSpreadBps": 0.5}, "BTC": {"halfSpreadBps": 0.01}}}}))
    monkeypatch.setattr(report, "write", lambda name, md, data: (
        (tmp_path / "reports" / name).mkdir(parents=True, exist_ok=True),
        (tmp_path / "reports" / name / "latest.md").write_text(md),
        (tmp_path / "reports" / name / "latest.json").write_text(json.dumps(data))))
    return tmp_path


def signal(root, weights, valid_until=NOW + DAY, strategy=B.SIGNAL):
    d = root / "signals" / B.SIGNAL
    d.mkdir(parents=True, exist_ok=True)
    (d / "latest.json").write_text(json.dumps({"strategy": strategy, "as_of_ms": NOW - DAY,
                                               "valid_until_ms": valid_until, "weights": weights}))


def journal(root):
    with (B.book_dir(root) / "journal.csv").open() as fh:
        return list(csv.DictReader(fh))


def test_a_day_rebalances_journals_and_reports(lab):
    signal(lab, {"SOL": 0.3, "BTC": 0.2, "NEAR": 0.05})
    pools = Pools(MIDS)
    row = B.step(pools, NOW, root=lab, write_root=lab, probes=True)
    rows = journal(lab)
    assert list(rows[0]) == B.JOURNAL_COLS and len(rows) == 1
    assert row["swaps"] == 2 and row["turnover"] == pytest.approx(0.5, abs=1e-3)
    assert float(rows[0]["equity"]) == pytest.approx(float(rows[0]["equity_usdc"]) * 10, abs=0.01)  # 10,000 basis
    assert 9_990 < float(rows[0]["equity"]) < 10_000
    assert row["kraken_cost_bps"] == pytest.approx(0.3 * 40.5 + 0.2 * 40.01, abs=0.05)
    assert row["model_cost_bps"] == pytest.approx(0.5 * 15, abs=0.05)
    assert 0 < row["paper_cost_bps"] < row["kraken_cost_bps"]
    st = json.loads((B.book_dir(lab) / "state.json").read_text())
    assert set(st["units"]) == {"SOL", "BTC"} and st["signal"]["dropped"] == {"NEAR": 0.05}
    assert st["variant"].startswith("EXPERIMENT")
    trades = list(csv.DictReader((B.book_dir(lab) / "trades.csv").open()))
    assert [t["coin"] for t in trades] == ["BTC", "SOL"] and trades[0]["route"] == "Fake"
    probes = list(csv.DictReader((B.book_dir(lab) / "probes.csv").open()))
    assert {p["coin"] for p in probes} == {"SOL", "BTC", "ETH"}       # the coins the fake pools price
    assert float(probes[0]["roundtrip_bps"]) == pytest.approx(20 + 2 * 1.05, abs=0.2)
    rep = json.loads((lab / "reports" / "onchain" / "latest.json").read_text())
    assert rep["status"] == "ok" and rep["summary"]["rebalances"] == 1 and "Kraken" in rep["headline"]
    assert "NEAR 5.0%" in (lab / "reports" / "onchain" / "latest.md").read_text()

    # The same day again: marked, not journaled twice.
    assert B.step(pools, NOW + 3_600_000, root=lab, write_root=lab) == {}
    assert len(journal(lab)) == 1
    # The next day with BTC gone from the signal: sold whole, the day's return journaled.
    signal(lab, {"SOL": 0.3}, valid_until=NOW + 2 * DAY)
    pools.mids = {**MIDS, "SOL": 110.0}
    row = B.step(pools, NOW + DAY, root=lab, write_root=lab, probes=False)
    assert row["gross_ret_pct"] == pytest.approx(3.0, abs=0.1) and row["swaps"] == 2   # sell BTC, trim SOL
    st = json.loads((B.book_dir(lab) / "state.json").read_text())
    assert set(st["units"]) == {"SOL"} and len(journal(lab)) == 2


def test_a_stale_signal_holds_and_the_hourly_mark_writes_no_journal_row(lab):
    signal(lab, {"SOL": 0.5})
    pools = Pools(MIDS)
    B.step(pools, NOW, root=lab, write_root=lab, probes=False)
    signal(lab, {"BTC": 0.5}, valid_until=NOW)                         # expired by the next day
    row = B.step(pools, NOW + DAY, root=lab, write_root=lab, probes=False)
    assert row["swaps"] == 0 and row["signal"] == "the signal is stale" and row["held"] == 1
    pools.mids = {**MIDS, "SOL": 120.0}
    eq = B.mark_only(pools, NOW + DAY + 3_600_000, write_root=lab)
    assert 1_090 < eq < 1_100                                          # 500 USDC and about 5 SOL at 120
    assert len(journal(lab)) == 2
    marks = list(csv.DictReader((B.book_dir(lab) / "marks.csv").open()))
    assert len(marks) == 1 and float(marks[0]["equity_usdc"]) == pytest.approx(eq, abs=1e-3)


def test_signal_reading_and_nothing_to_mark_before_the_start(lab):
    assert B.read_signal(lab, NOW)[0] is None
    signal(lab, {"SOL": 0.1}, strategy="breakout_top10")
    assert B.read_signal(lab, NOW) == (None, "the signal file names another strategy")
    assert B.mark_only(Pools(MIDS), NOW, write_root=lab) is None
    assert not B.book_dir(lab).exists()


def test_a_dry_run_writes_nothing(lab):
    signal(lab, {"SOL": 0.5})
    row = B.step(Pools(MIDS), NOW, root=lab, write_root=lab, dry_run=True)
    assert row["swaps"] == 0 and not B.book_dir(lab).exists()


def test_nothing_in_the_package_signs_or_sends():
    import pathlib
    src = " ".join(p.read_text() for p in pathlib.Path(B.__file__).parent.glob("*.py"))
    for word in ("Keypair", "sign(", "sendTransaction", "/swap?", "swap/v1/swap\"", "keypair"):
        assert word not in src
