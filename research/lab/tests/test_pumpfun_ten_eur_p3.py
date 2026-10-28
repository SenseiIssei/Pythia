"""P3, a 10 EUR realistic paper book for pump.fun: the pre-registered rules, the 0.109 SOL wallet with the live sizing,
the token account's rent held while a position is open and back only when the rule's last sale closes it (a stuck
exit loses it), a buy refused when the wallet cannot pay stake, reserve and rent, no top-up, the wallet kept across a
restart, the numbers (mean and median after all costs, the band, days) and the gate for real money in the pump.fun
report, the paper books and the readiness ladder, the trials. No network, no wallet.

Run from research/lab:  python -m pytest tests/test_pumpfun_ten_eur_p3.py
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from lab import metrics
from lab.ops import ladder, paper_books
from lab.pumpfun_rt import curve as C
from lab.pumpfun_rt import live
from lab.pumpfun_rt import pipeline as P
from lab.pumpfun_rt import realistic as R
from lab.pumpfun_rt import selection_p2 as S2
from lab.pumpfun_rt import sim
from test_pumpfun_exit_runners import Pool
from test_pumpfun_realistic import files, fixed_fit, measured, write_csv  # noqa: F401 - the fixture
from test_pumpfun_rt import MINT, SOL, T0, Fixed

DAY = 86_400_000
EM = "\u2014"                                                  # the em dash, never in a report
TEN = (("P_pool0_10eur", "P_pool0"),)
RESULTS = Path(__file__).resolve().parents[1] / "results"


def ten_engine(fit_=None):
    eng = sim.Engine([], costs=Fixed())
    wallets: dict = {}
    book = R.ten_books(eng, R.Model(fit_ or fixed_fit(), R.LiveConfig()), wallets, ten=TEN, now_ms=T0)[0]
    return eng, book, wallets["P_pool0_10eur"]


def opened(eng, book):
    """A pool buy of P_pool0 that landed and filled (signal T0, landing T0 + 5 s, the next trade at T0 + 6 s)."""
    pool = Pool(eng)
    eng.advance(T0 + 1)
    pool.trade(T0 + 6_000, True, SOL // 1000)
    eng.advance(T0 + 7_000)
    p = next(iter(book.pos.values()))
    assert p["state"] == "open"
    return pool, p


# ---------------------------------------------------------------- the registration

def test_the_books_are_the_preregistered_rules():
    text = (RESULTS / "ten_eur_p3_prereg.md").read_text(encoding="utf-8")
    assert 1 <= len(R.TEN) <= 3 and len({b for b, _ in R.TEN}) == len(R.TEN)
    for name, base in R.TEN:
        assert base in P.BY_NAME and name == f"{base}_10eur" and f"`{name}`" in text
        assert f"hand:p3:ten_eur:{name}" in text
    assert R.TEN_SOL * 91.68 == pytest.approx(10.0, abs=0.01)
    assert R.RENT_L / C.LAMPORTS == pytest.approx(0.002, abs=1e-4)
    assert R.TEN_GAP_PTS == S2.GATE_PTS and R.TEN_DAYS == 30 and R.TEN_SHARE == 0.5 and R.TEN_OPEN == 1
    assert EM not in text
    assert [t["id"] for t in R.ten_trials()] == [f"hand:p3:ten_eur:{n}" for n, _ in R.TEN]


# ---------------------------------------------------------------- the wallet

def test_the_ten_eur_wallet_is_sized_as_the_live_bot_at_share_one_half():
    eng, book, w = ten_engine()
    assert w.cash_l(0) == int(0.109 * SOL) and w.since_ms == T0
    lim, why = w.limits(0, book.exec.model.cfg)
    assert why is None and lim.stake_sol == 0.05 and lim.max_open == 1   # 50 % of 0.109, rounded down to 0.01
    _, p = opened(eng, book)
    assert p["stake_l"] == int(0.05 * SOL) and book.strats["P_pool0_10eur"].p["base"] == "P_pool0"


def test_the_rent_is_held_while_open_and_back_when_the_rule_closes_the_account():
    eng, book, w = ten_engine()
    pool, p = opened(eng, book)
    held = book.exec.open_l()
    assert w.rent_l == R.RENT_L and p["rent_l"] == R.RENT_L
    assert w.cash_l(held) == int(0.109 * SOL) - p["cost_l"] - p["fees_l"] - R.RENT_L
    assert book.status()["wallet"]["sol"] == pytest.approx(0.109)        # held rent is still the wallet's
    pool.to(T0 + 10_000, 1.6)
    pool.trade(T0 + 15_000, True, SOL // 1000)
    eng.advance(T0 + 400_000)
    rec = [t for t in eng.closed if t["rule"] == "P_pool0_10eur"]
    assert len(rec) == 1 and rec[0]["exit_why"] != "stuck" and not book.pos
    assert w.rent_l == 0 and w.rent_lost == 0                            # the last sale closed it: back
    assert w.pnl_l == round(rec[0]["pnl_sol"] * SOL) and w.cash_l(0) == int(0.109 * SOL) + w.pnl_l


def test_a_stuck_exit_keeps_its_account_and_loses_the_rent():
    eng, book, w = ten_engine()
    _, p = opened(eng, book)
    cost, fees = p["cost_l"], p["fees_l"]
    book.sold(p["pid"], T0 + 8_000, p["left"], 0, 0, stuck=True)
    rec = eng.closed[-1]
    assert rec["exit_why"] == "stuck" and w.rent_l == 0 and w.rent_lost == 1
    assert w.pnl_l == -(cost + fees + R.RENT_L) and rec["pnl_sol"] == pytest.approx(w.pnl_l / SOL)
    assert w.cash_l(0) == int(0.109 * SOL) - cost - fees - R.RENT_L


def test_a_failed_buy_makes_no_account():
    eng, book, w = ten_engine(fixed_fit(fail={"other": 1.0}))
    Pool(eng)
    eng.advance(T0 + 6_000)
    assert eng.failed and w.rent_l == 0 and not book.pos


def test_a_buy_is_refused_when_the_wallet_cannot_pay_stake_reserve_and_rent():
    # 0.076 SOL pays a 0.065 SOL buy limit and the 0.01 reserve, but not the rent on top: refused, no fee
    eng, book, w = ten_engine()
    w.book(int(0.076 * SOL) - w.cash_l(0))
    book.pos[7] = {"pid": 7, "rule": "P_pool0_10eur", "mint": MINT, "signal_ms": T0, "state": "pending"}
    book.risk["P_pool0_10eur"].hold(7, int(0.065 * SOL))
    book.exec.buy(P.Order(7, "buy", MINT, "pool", 10 ** 9, int(0.065 * SOL), T0, stake_l=int(0.05 * SOL)))
    assert eng.failed[0]["why"] == "refused: wallet balance too low" and eng.failed[0]["pnl_sol"] == 0
    assert not book.pos and w.rent_l == 0
    plain = R.PaperWallet(start_l=int(0.076 * SOL))                     # without the rent the same cash would pay
    assert plain.cash_l(0) >= int(0.065 * SOL) + int(R.RESERVE_SOL * SOL)
    # and the sizing pauses first: what is left after reserve and rent pays under 0.05 SOL with the 30 % room
    lim, why = w.limits(0, book.exec.model.cfg)
    assert lim.stake_sol == 0 and why.startswith("stake paused: the wallet cannot pay one trade")


def test_a_ten_eur_wallet_is_never_topped_up():
    eng, book, w = ten_engine()
    w.book(-int(0.05 * SOL), -1.0)                                      # 0.059 SOL left, nothing open
    Pool(eng)
    eng.advance(T0 + 1)
    assert not book.pos and any(k[0] == "P_pool0_10eur" and k[1].startswith("stake paused") for k in eng.skipped)
    assert not w.top_up() and w.refills == 0 and w.topped_l == 0 and w.start_l == int(0.109 * SOL)
    assert book.status()["wallet"]["refills"] == 0


def test_the_wallet_keeps_its_start_and_lost_rent_but_not_the_rent_of_positions_a_restart_dropped(tmp_path,
                                                                                                    monkeypatch):
    w = R.TenWallet(pnl_l=-1_000, n=2, rent_l=R.RENT_L, rent_lost=1, since_ms=T0)
    back = R.wallet_of("P_pool0_wait_10eur", json.loads(json.dumps(w.to_json())))
    assert isinstance(back, R.TenWallet) and back.since_ms == T0 and back.rent_lost == 1 and back.rent_l == 0
    assert back.pnl_l == -1_000 and back.start_l == int(0.109 * SOL)
    assert type(R.wallet_of("P_pool0", {"start_l": 1})) is R.PaperWallet
    monkeypatch.setattr(live, "paper_dir", lambda: tmp_path)
    from lab.pumpfun_rt import strategies as S
    sh = live.Shadow(S.DEFAULT_PICK, alerts=False, strategies=[P.BY_NAME["P_pool0"]], realistic=True,
                     real=R.Model(fixed_fit(), R.LiveConfig()), now_ms=T0, ten=TEN)
    assert "P_pool0_10eur" in {s for p in sh.engine.pipes for s in p.strats}
    sh.paper_wallets["P_pool0_10eur"].book(-500)
    sh.save()
    st = json.loads((tmp_path / "state.json").read_text())["paper_wallets"]["P_pool0_10eur"]
    assert st["since_ms"] == T0 and st["pnl_l"] == -500
    again = R.ten_books(sim.Engine([], costs=Fixed()), R.Model(fixed_fit(), R.LiveConfig()),
                        {"P_pool0_10eur": R.wallet_of("P_pool0_10eur", st)}, ten=TEN, now_ms=T0 + DAY)[0]
    assert again.exec.wallet.since_ms == T0 and again.exec.wallet.pnl_l == -500   # no fresh start, no top-up
    full = live.Shadow(S.DEFAULT_PICK, alerts=False, realistic=True, real=R.Model(fixed_fit(), R.LiveConfig()),
                       now_ms=T0)                                       # the collector's full set: P3's books too
    assert {n for n, _ in R.TEN} <= {s for p in full.engine.pipes for s in p.strats}


# ---------------------------------------------------------------- the numbers and the gate

def row(i, ret, rule="P_pool0_10eur", **kw):
    t = T0 + DAY + i * 60_000
    return {"rule": rule, "mint": f"m{i}", "signal_ms": t, "land_ms": t + 5_000, "exit_signal_ms": t + 9_000,
            "exit_ms": t + 10_000, "hold_s": 5.0, "ret": ret, "stake_sol": 0.05, "pnl_sol": ret * 0.05,
            "exit_why": "take", **kw}


def test_the_numbers_are_after_all_costs_with_the_failed_fees_spread_on_the_trades():
    rows = [row(i, 0.10 if i % 2 else -0.02) for i in range(20)]
    fails = [{"rule": "P_pool0_10eur", "pnl_sol": -0.0005}] * 4        # 0.002 SOL over 1 SOL of stakes: 0.2 points
    st = R.ten_stats(rows, fails)
    assert st["trades"] == 20 and st["failed"] == 4 and st["failed_fee_sol"] == pytest.approx(0.002)
    assert st["mean"] == pytest.approx(0.04 - 0.002) and st["median"] == pytest.approx(0.04 - 0.002)
    lo, hi = st["band"]
    assert lo < st["mean"] < hi and R.ten_stats(rows, fails)["band"] == st["band"]     # seeded
    few = R.ten_stats(rows[:9], [])
    assert few["band"] is None and few["mean"] == pytest.approx(sum(r["ret"] for r in rows[:9]) / 9)
    assert R.ten_stats([], fails)["mean"] is None


def state(pnl_l=0, since=T0):
    return {"paper_wallets": {"P_pool0_10eur": R.TenWallet(pnl_l=pnl_l, since_ms=since, n=3).to_json()}}


def test_the_gate_needs_30_days_mean_and_band_above_0_and_p2s_gap(monkeypatch):
    good = [row(i, 0.10 if i % 3 else 0.02) for i in range(30)]
    gap = {"pts": 1.0, "pass": True}
    late = T0 + 31 * DAY
    r = R.ten_status(state(int(0.02 * SOL)), good, [], 90.0, gap, late, ten=TEN)[0]
    assert r["pass"] and all(r["gate"].values()) and r["days"] == pytest.approx(31)
    assert r["sol"] == pytest.approx(0.129) and r["eur"] == pytest.approx(0.129 * 90) and r["can_pay"]
    assert not R.ten_status(state(), good, [], 90.0, gap, T0 + 29 * DAY, ten=TEN)[0]["gate"]["days"]
    for g in ({"pts": 2.0, "pass": False}, None, {"pts": None, "pass": None}):
        x = R.ten_status(state(), good, [], 90.0, g, late, ten=TEN)[0]
        assert not x["pass"] and not x["gate"]["gap"]
    mixed = [row(i, 0.30 if i % 2 else -0.27) for i in range(30)]    # mean above 0, band across 0
    x = R.ten_status(state(), mixed, [], 90.0, gap, late, ten=TEN)[0]
    assert x["gate"]["mean"] and not x["gate"]["band"] and not x["pass"]
    assert "fails: band above 0" in R.ten_gate_text(x)
    poor = R.ten_status(state(-int(0.05 * SOL)), good, [], None, gap, late, ten=TEN)[0]
    assert not poor["can_pay"] and poor["eur"] is None
    assert R.ten_status({}, [], [], 90.0, gap, late, ten=TEN)[0]["started"] is False


def test_tainted_and_restart_rows_are_left_out_and_counted():
    rows = [row(i, 0.05) for i in range(12)]
    rows.append(row(50, -0.9, exit_why="restart"))
    rows.append(row(51, 0.8, land_ms=T0, signal_ms=T0 + 10))           # landed before its signal: P1 taint
    r = R.ten_status(state(int(0.04 * SOL)), rows, [], 90.0, {"pass": True}, T0 + DAY, ten=TEN)[0]
    assert r["trades"] == 12 and r["mean"] == pytest.approx(0.05) and r["tainted"] == 1
    assert r["sol"] == pytest.approx(0.109 + 0.04 - 0.04)                # the tainted trade's P&L out of the wallet


def test_the_report_shows_the_books_in_euro():
    rows = R.ten_status(state(), [row(i, 0.05) for i in range(12)], [], 91.68, {"pass": True}, T0 + 2 * DAY,
                        ten=TEN)
    md = "\n".join(R.ten_md(rows, 91.68))
    assert "P_pool0_10eur" in md and "9.99" in md and "+5.0 %" in md and "fails: 30 days" in md and EM not in md
    assert R.ten_md([], 91.68) == []


def test_the_daily_job_writes_the_books_and_registers_their_trials_first(files, monkeypatch):
    monkeypatch.setattr(R, "TEN", TEN)
    monkeypatch.setattr(R, "sol_eur", lambda: 90.0)
    now = T0 + 8 * DAY
    (files / "live" / "measured.jsonl").write_text("\n".join(json.dumps(r) for r in measured(now)) + "\n")
    write_csv(files / "paper" / "ledger.csv", [row(i, 0.05) for i in range(12)])
    (files / "paper" / "state.json").write_text(json.dumps({"realistic_since": T0, **state()}))
    out = R.daily(now)
    assert [x["book"] for x in out["ten"]] == ["P_pool0_10eur"] and out["ten"][0]["trades"] == 12
    assert out["ten"][0]["days"] == pytest.approx(8)
    assert "hand:p3:ten_eur:P_pool0_10eur" in {r["id"] for r in metrics.read_registry()}
    d = json.loads((files / "reports" / "pumpfun_rt" / "realistic.json").read_text())
    assert d["ten"][0]["book"] == "P_pool0_10eur"
    md = (files / "reports" / "pumpfun_rt" / "realistic.md").read_text()
    assert "10 EUR paper books (P3" in md and EM not in md
    assert list(csv.DictReader((files / "paper" / "ledger.csv").open()))[0]["rule"] == "P_pool0_10eur"


# ---------------------------------------------------------------- the paper books and the ladder

def test_the_paper_books_and_the_ladder_show_the_gate(tmp_path):
    data, results = tmp_path / "data", tmp_path / "results"
    results.mkdir()
    (results / "ten_eur_p3_prereg.md").write_text("# P3\n", encoding="utf-8")
    good = [row(i, 0.10 if i % 3 else 0.02) for i in range(30)]
    ten = R.ten_status(state(), good, [], 90.0, {"pts": 1.0, "pass": True}, T0 + 31 * DAY, ten=TEN)
    poor = R.ten_status(state(), good[:5], [], 90.0, {"pts": 3.0, "pass": False}, T0 + 3 * DAY,
                        ten=(("P_pool0_wait_10eur", "P_pool0_wait"),))
    p = data / "reports" / "pumpfun_rt" / "realistic.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps({"ten": ten + poor, "small": []}), encoding="utf-8")
    books = {b["name"]: b for b in paper_books.books(data)}
    b = books["P_pool0_10eur"]
    assert b["study"] == "P3" and b["value"] == pytest.approx(0.109) and b["p3"]["trades"] == 30
    assert b["start"] == ladder._day(T0)                                # the wallet's own start day
    d = ladder.build(data, T0 + 31 * DAY, results=results, added=lambda q: (T0 // 1000 - 1, "a1"))
    rows = {r["id"]: r for r in d["rows"]}
    r = rows["book:P_pool0_10eur"]
    assert r["study"] == "P3" and r["p3"]["trades"] == 30 and r["p3"]["pass"]
    assert [c["id"] for c in r["steps"]["5"]] == ["p3_days", "p3_mean", "p3_band", "p3_gap", "p3_taint"]
    assert all(c["ok"] for c in r["steps"]["5"]) and r["steps"]["1"][0]["ok"]
    assert r["step"] < 5                                                # steps 2 to 4 are not waived
    w = rows["book:P_pool0_wait_10eur"]
    bad = {c["id"] for c in w["steps"]["5"] if c["ok"] is False}
    assert bad == {"p3_days", "p3_mean", "p3_band", "p3_gap"}                # no trade of its own yet
    md = ladder.markdown(d)
    assert "10 EUR pump.fun paper books (P3" in md and "P_pool0_10eur" in md and "passes" in md
    assert "fails: 30 days of the 10 EUR paper book" in md and EM not in md


def test_p3_cannot_trade():
    src = (Path(R.__file__)).read_text(encoding="utf-8")
    i = src.index("def ten_books")
    body = src[i:src.index("\ndef factory_books")]
    for word in ("sign", "send_transaction", "keypair", "LiveExecutor", "live_exec"):
        assert word not in body
