"""EQ3: the equity books' orders on Alpaca's paper account, against a fake Alpaca server (a transport that answers
like the paper API): an order sent once (also after a lost answer), a rejection recorded with its reason, the live
URL refused, no key in any log, ledger or report, the market closed, the ladder line, the plan's sells first.

Run from research/lab:  python -m pytest tests/test_alpaca_paper.py
"""

from __future__ import annotations

import ast
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from lab import metrics, report
from lab.exec import alpaca_paper as A

KEY, SECRET = "PKFAKEKEY0123456789", "fakeSECRETvalue9876543210abcdef"
HDR = {"APCA-API-KEY-ID": KEY, "APCA-API-SECRET-KEY": SECRET}
DAY1 = datetime(2026, 10, 29, 15, 0, 5, tzinfo=timezone.utc).timestamp()
DAY2 = datetime(2026, 10, 30, 15, 0, 5, tzinfo=timezone.utc).timestamp()
QUOTES = {"SPY": (680.10, 680.16), "GLD": (370.00, 370.10)}


class FakeAlpaca:
    """Alpaca's paper API as far as the module uses it: clock, assets, positions, latest quotes, orders. Market
    orders fill at the ask (buy) or the bid (sell) at 15:00:05.523; `reject` symbols answer 403."""

    def __init__(self, is_open=True, reject=(), lose_answer=False, echo_key=False):
        self.is_open, self.reject, self.lose, self.echo = is_open, set(reject), lose_answer, echo_key
        self.calls, self.orders, self.positions = [], {}, {}

    def __call__(self, method, url, headers, body=None):
        assert headers == HDR
        self.calls.append((method, url, body))
        path = url.split(".markets", 1)[1]
        if method == "POST":
            assert url == "https://paper-api.alpaca.markets/v2/orders"
            return self.post(body)
        if path == "/v2/clock":
            return 200, {"timestamp": "2026-10-29T11:00:05.123456789-04:00", "is_open": self.is_open}
        if path.startswith("/v2/assets/"):
            return 200, {"symbol": path.rsplit("/", 1)[1], "tradable": True, "fractionable": True}
        if path.startswith("/v2/positions/"):
            q = self.positions.get(path.rsplit("/", 1)[1])
            return (200, {"qty": str(q)}) if q else (404, {"code": 40410000, "message": "position does not exist"})
        if path.startswith("/v2/stocks/"):
            assert "feed=iex" in url and url.startswith("https://data.alpaca.markets/")
            b, a = QUOTES[path.split("/")[3]]
            return 200, {"quote": {"bp": b, "ap": a, "t": "2026-10-29T15:00:04.9Z"}}
        if path.startswith("/v2/orders:by_client_order_id"):
            cid = url.split("client_order_id=", 1)[1]
            o = next((o for o in self.orders.values() if o["client_order_id"] == cid), None)
            return (200, o) if o else (404, {"message": "order not found"})
        if path.startswith("/v2/orders/"):
            return 200, self.orders[path.rsplit("/", 1)[1]]
        raise AssertionError(url)

    def post(self, body):
        if any(o["client_order_id"] == body["client_order_id"] for o in self.orders.values()):
            return 422, {"code": 40010001, "message": "client_order_id must be unique"}
        if body["symbol"] in self.reject:
            msg = "insufficient buying power" + (f" for {KEY}" if self.echo else "")
            return 403, {"code": 40310000, "message": msg}
        b, a = QUOTES[body["symbol"]]
        px = a if body["side"] == "buy" else b
        qty = float(body["notional"]) / px if "notional" in body else float(body["qty"])
        oid = f"oid-{len(self.orders) + 1}"
        self.orders[oid] = {"id": oid, "client_order_id": body["client_order_id"], "status": "filled",
                            "filled_qty": f"{qty:.9f}", "filled_avg_price": f"{px}", "symbol": body["symbol"],
                            "filled_at": "2026-10-29T15:00:05.523Z"}
        sign = 1 if body["side"] == "buy" else -1
        self.positions[body["symbol"]] = self.positions.get(body["symbol"], 0.0) + sign * qty
        if self.lose:
            self.lose = False
            raise TimeoutError("the answer was lost")
        return 200, {**self.orders[oid], "status": "accepted", "filled_qty": "0", "filled_avg_price": None}

    def posts(self):
        return [c for c in self.calls if c[0] == "POST"]


def data_root(tmp_path: Path, books: dict) -> Path:
    root = tmp_path / "data"
    for b, w in books.items():
        p = root / "paper" / b
        p.mkdir(parents=True)
        with (p / "journal.csv").open("w", newline="") as f:
            csv.writer(f).writerows([["date", "equity", "weights"], ["2026-10-29", "10000", json.dumps(w)]])
    return root


@pytest.fixture(autouse=True)
def registry(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHIA_TRIALS_REGISTRY", str(tmp_path / "trials" / "registry.jsonl"))


def go(root, fake, now=DAY1, **kw):
    return A.run(root=root, write_root=root, cl=A.Client(HDR, send=fake), now=lambda: now, sleep=lambda s: None,
                 poll_s=0.0, log=lambda m: None, **kw)


# ---------------------------------------------------------------- the endpoint

def test_the_live_url_is_refused():
    with pytest.raises(A.Refused):
        A.base_url({"APCA_API_BASE_URL": "https://api.alpaca.markets"})
    with pytest.raises(A.Refused):
        A.base_url({"APCA_API_BASE_URL": "https://api.alpaca.markets/v2"})
    assert A.base_url({}) == A.base_url({"APCA_API_BASE_URL": "https://paper-api.alpaca.markets/v2/"}) == A.PAPER
    with pytest.raises(A.Refused):
        A.Client(HDR, base="https://api.alpaca.markets")
    cl = A.Client(HDR, send=FakeAlpaca())
    for method, url in (("GET", "https://api.alpaca.markets/v2/clock"), ("POST", "https://api.alpaca.markets/v2/orders"),
                        ("DELETE", A.PAPER + "/v2/orders"), ("POST", A.PAPER + "/v2/account/configurations"),
                        ("POST", A.PAPER + "/v2/transfers"), ("POST", A.DATA + "/v2/stocks/SPY/quotes/latest")):
        with pytest.raises(A.Refused):
            cl._req(method, url)


def test_main_refuses_a_live_base_url_and_sends_nothing(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("APCA_API_BASE_URL", "https://api.alpaca.markets")
    monkeypatch.setenv("APCA_API_KEY_ID", KEY)
    monkeypatch.setenv("APCA_API_SECRET_KEY", SECRET)
    monkeypatch.setattr(A, "_http", lambda *a, **k: pytest.fail("a request was made"))
    monkeypatch.setattr(A, "ROOT", tmp_path)
    assert A.main([]) == 2
    out = capsys.readouterr()
    assert "refused" in out.err and KEY not in out.out + out.err and SECRET not in out.out + out.err


def test_the_source_has_no_live_url_and_no_account_change():
    src = Path(A.__file__).read_text(encoding="utf-8")
    hosts = {s for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Constant) and isinstance(n.value, str)
             for s in [n.value] if "alpaca.markets" in s and s.startswith("http")}
    assert hosts and all(h.startswith(("https://paper-api.alpaca.markets", "https://data.alpaca.markets"))
                         for h in hosts)
    for bad in ("transfers", "/v2/account", "ach_relationships", "journals", '"DELETE"', '"PATCH"', "/v2/positions\""):
        assert bad not in src


# ---------------------------------------------------------------- the orders

def test_an_order_is_sent_once(tmp_path):
    root = data_root(tmp_path, {"small40_spy_trend": {"SPY": 1.0}})
    fake = FakeAlpaca()
    res = go(root, fake)
    assert len(fake.posts()) == 1
    body = fake.posts()[0][2]
    assert body["type"] == "market" and body["time_in_force"] == "day" and "extended_hours" not in body
    assert body["client_order_id"] == "eq3-small40_spy_trend-2026-10-29-SPY-buy"
    b = res["books"]["small40_spy_trend"]
    assert b["filled"] == 1 and res["sent"] == 1
    state = A.load_state(root / "exec" / "alpaca_paper" / "state.json")
    bk, o = state["books"]["small40_spy_trend"], state["orders"][0]
    usd = float(body["notional"])
    assert usd == pytest.approx(bk["start_usd"], abs=0.01) and usd == round(usd, 2)
    assert bk["cash"] == pytest.approx(bk["start_usd"] - usd, abs=1e-6)
    assert bk["held"]["SPY"] == pytest.approx(usd / 680.16)
    mid = (680.10 + 680.16) / 2
    assert o["paper_bps"] == pytest.approx((680.16 / mid - 1) * 1e4) and o["model_bps"] == pytest.approx(5.0)
    assert o["bar"] == 18 and o["ack_ms"] >= 0 and o["fill_s"] == pytest.approx(0.523, abs=0.01)
    go(root, fake)                                   # the same day again
    go(root, fake, now=DAY2)                         # the next day, the target unchanged
    assert len(fake.posts()) == 1


def test_a_lost_answer_is_looked_up_not_resent(tmp_path):
    root = data_root(tmp_path, {"small40_spy_trend": {"SPY": 1.0}})
    fake = FakeAlpaca(lose_answer=True)
    res = go(root, fake)
    assert len(fake.posts()) == 1 and res["books"]["small40_spy_trend"]["filled"] == 1
    assert any("by_client_order_id" in c[1] for c in fake.calls)
    go(root, fake)
    assert len(fake.posts()) == 1


def test_a_rejection_is_recorded_with_its_reason(tmp_path):
    root = data_root(tmp_path, {"small40_vol_target": {"BTC": 0.11, "GOLD": 0.17, "SPY": 0.45}})
    fake = FakeAlpaca(reject={"GLD"})
    res = go(root, fake)
    b = res["books"]["small40_vol_target"]
    assert b["dropped"] == ["BTC"] and set(b["targets"]) == {"GLD", "SPY"}
    assert b["rejected"] == 1 and b["filled"] == 1
    assert b["rejections"][0]["why"].startswith("HTTP 403: insufficient buying power")
    go(root, fake, now=DAY2)                         # the rejected leg is tried again the next day, under a new id
    assert [p[2]["client_order_id"] for p in fake.posts()].count("eq3-small40_vol_target-2026-10-30-GLD-buy") == 1


def test_nothing_is_sent_while_the_market_is_closed(tmp_path):
    root = data_root(tmp_path, {"small40_spy_trend": {"SPY": 1.0}})
    fake = FakeAlpaca(is_open=False)
    res = go(root, fake)
    assert res["market"] == "closed" and not fake.posts()


def test_no_key_in_any_log_ledger_or_report(tmp_path, monkeypatch, capsys):
    root = data_root(tmp_path, {"small40_spy_trend": {"SPY": 1.0}, "small40_vol_target": {"GOLD": 0.3}})
    fake = FakeAlpaca(reject={"GLD"}, echo_key=True, lose_answer=True)
    monkeypatch.setenv("APCA_API_KEY_ID", KEY)
    monkeypatch.setenv("APCA_API_SECRET_KEY", SECRET)
    monkeypatch.delenv("APCA_API_BASE_URL", raising=False)
    monkeypatch.setattr(A, "_http", fake)
    monkeypatch.setattr(A, "ROOT", root)
    monkeypatch.setattr(A, "WRITE_ROOT", root)
    monkeypatch.setattr(A, "POLL_S", 0.0)
    monkeypatch.setattr(A.time, "sleep", lambda s: None)
    monkeypatch.setattr(report, "REPORTS", root / "reports")
    assert A.main([]) == 0
    out = capsys.readouterr()
    assert fake.posts()
    texts = [out.out, out.err] + [p.read_text() for p in root.rglob("*") if p.is_file()]
    assert any("insufficient buying power for ***" in t for t in texts)
    for t in texts:
        assert KEY not in t and SECRET not in t
    assert (root / "reports" / "exec_alpaca" / "latest.md").exists()


def test_without_keys_no_order_and_the_job_is_red(tmp_path, monkeypatch):
    monkeypatch.delenv("APCA_API_KEY_ID", raising=False)
    monkeypatch.delenv("APCA_API_SECRET_KEY", raising=False)
    monkeypatch.delenv("APCA_API_SECRET", raising=False)
    monkeypatch.delenv("APCA_API_BASE_URL", raising=False)
    monkeypatch.setattr(A, "_http", lambda *a, **k: pytest.fail("a request was made"))
    res = A.run(root=tmp_path, write_root=tmp_path, log=lambda m: None)
    assert "not set" in res["error"] and "not set" in A.markdown(res)


def test_trials_are_registered_before_any_order(tmp_path):
    root = data_root(tmp_path, {"small40_spy_trend": {"SPY": 1.0}})
    go(root, FakeAlpaca(is_open=False))
    ids = {r["id"] for r in metrics.read_registry()}
    assert {f"small:eq3:exec_alpaca_{b}" for b in A.BOOKS} <= ids and len(A.trials()) == 4


# ---------------------------------------------------------------- the pieces

def test_plan_sells_first_and_sells_everything_at_target_zero():
    q = {"SPY": {"bid": 99.9, "ask": 100.1, "mid": 100.0}, "GLD": {"bid": 49.9, "ask": 50.1, "mid": 50.0}}
    book = {"cash": 0.0, "held": {"SPY": 0.5}, "traded": {"SPY": 1.0}}
    p = A.plan(book, {"GLD": 0.4}, q)
    assert [o["side"] for o in p] == ["sell", "buy"] and p[0]["qty"] == 0.5
    assert p[1]["usd"] == pytest.approx(20.0)
    assert A.plan({**book, "open": ["SPY"]}, {"GLD": 0.4}, q)[0]["symbol"] == "GLD"
    assert A.plan({"cash": 50.0, "held": {}, "traded": {}}, {"SPY": 0.0}, q) == []
    half = A.plan(book, {"SPY": 0.4}, q)
    assert half[0]["side"] == "sell" and half[0]["qty"] == pytest.approx(0.3)


def test_legs_times_and_model_cost():
    assert A.legs({"BTC": 0.2, "GOLD": 0.3, "SPY": 0.5}) == ({"GLD": 0.3, "SPY": 0.5}, ["BTC"])
    assert A.session_bar("2026-10-29T09:44:59-04:00") == 2 and A.session_bar("2026-10-29T10:00:00-04:00") == 6
    assert A.session_bar("2026-10-29T09:00:00-04:00") == 0 and A.session_bar(None) == 0
    assert A.iso_s("2026-10-29T15:00:05.523456789Z") == pytest.approx(
        datetime(2026, 10, 29, 15, 0, 5, 523456, tzinfo=timezone.utc).timestamp())
    assert A.iso_s("2026-10-29T11:00:05-04:00") == datetime(2026, 10, 29, 15, 0, 5, tzinfo=timezone.utc).timestamp()
    assert A.model_bps(680.0, 18) == pytest.approx(5.0) and A.model_bps(680.0, 1) == pytest.approx(10.0)
    assert A.model_bps(10.0, 18) == pytest.approx(10.0)              # a cent on 10 USD
    assert A.fees_bps("buy", 100.0) == 0.0 and A.fees_bps("sell", 100.0) > 0.27
    assert A.scrub(f"x {KEY} y", (KEY,)) == "x *** y"


def test_the_ladder_line():
    def fills(n, paper, model=5.0):
        return [{"status": "filled", "filled_usd": 50.0, "paper_bps": paper, "model_bps": model, "day": "d"}] * n
    assert A.judge(fills(9, 1.0))["ladder"]["ok"] is None
    j = A.judge(fills(10, 7.0))
    assert j["ladder"]["ok"] is True and j["ratio"] == pytest.approx(1.4) and j["gap_bps"] == pytest.approx(2.0)
    assert A.judge(fills(10, 8.0))["ladder"]["ok"] is False
    assert A.judge(fills(12, -1.0))["ladder"]["ok"] is True             # price improvement
    assert A.judge([])["ladder"] == {"line": A.LADDER_LINE, "ok": None, "fills": 0, "need": 10, "x": 1.5,
                                     "ratio": None}
