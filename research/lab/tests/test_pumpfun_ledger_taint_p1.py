"""P1: the pump.fun paper ledger's rows the late-row bug made (realistic.tainted). The rule (the date condition only
before d84b252's deploy, the exit decided before the landing, the landing before the signal), and every reader
skipping a tainted row, keeping an untainted one and saying how many it skipped: the allocator (A1, T9, A1's forward
check), the calibration line, the paper wallets (R2, F3) and through them the paper review and the readiness ladder,
the study's readiness, the daily card, the execution report's paper slip, S17's twins; the study's report and its
trials registered before the first number. No network, no wallet; the ledger is never rewritten.

Run from research/lab:  python -m pytest tests/test_pumpfun_ledger_taint_p1.py
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone

import pytest

from lab.pumpfun_rt import allocator as A
from lab.pumpfun_rt import allocator_t9 as T9
from lab.pumpfun_rt import card, live, measure, study, taint_p1
from lab.pumpfun_rt import realistic as R
from lab.pumpfun_rt import shapes17 as Y17

FIX = R.FIX_MS
DAY = 86_400_000
COLS = ["rule", "mint", "symbol", "signal_ms", "land_ms", "exit_signal_ms", "exit_ms", "exit_why", "entry_price",
        "exit_price", "pnl_sol", "ret", "hold_s", "gap", "slip", "stake_sol"]


def row(rule="P_pool0_wait", mint="M1", t=None, hold=10.0, xsig_d=5_000, land_d=2_000, ret=0.1, slip=0.0):
    """A closed trade signalled at t (default a day before the deploy): landing land_d later, the exit decided
    xsig_d after the signal, closed hold seconds after the landing."""
    t = FIX - DAY if t is None else t
    land = t + land_d
    return {"rule": rule, "mint": mint, "symbol": "X", "signal_ms": t, "land_ms": land, "exit_signal_ms": t + xsig_d,
            "exit_ms": land + hold * 1000, "exit_why": "take", "entry_price": 1.0, "exit_price": 1 + ret,
            "pnl_sol": ret * 0.1, "ret": ret, "hold_s": hold, "gap": "False", "slip": slip, "stake_sol": 0.1}


def bad(**kw):
    """Tainted: the exit decided before the buy landed (and closed before the landing)."""
    return row(**{"hold": -1.0, "xsig_d": 500, "ret": 2.0, **kw})


def write_csv(p, rows, cols=COLS):
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def as_csv(rows):
    """The rows as csv.DictReader gives them back (strings)."""
    return [{k: str(v) for k, v in r.items()} for r in rows]


# ---------------------------------------------------------------- the rule

def test_the_deploy_is_2026_10_28_19_40_utc():
    assert FIX == int(datetime(2026, 10, 28, 19, 40, tzinfo=timezone.utc).timestamp() * 1000)


def test_each_condition_taints_and_a_clean_row_is_kept():
    assert not R.tainted(row())
    assert R.tainted(row(hold=-0.5, xsig_d=3_000))                 # closed before the landing, before the deploy
    assert R.tainted(row(xsig_d=1_000))                             # exit decided before the landing
    assert R.tainted(row(land_d=-10))                               # landed before its signal
    assert not R.tainted(row(land_d=0, xsig_d=0, hold=0.0))         # the signal's own slot is not before it


def test_after_the_deploy_the_date_rule_never_taints():
    late = row(t=FIX + 1_000, hold=-0.5, xsig_d=3_000)
    assert late["exit_ms"] >= FIX and not R.tainted(late)
    assert not R.tainted(as_csv([late])[0])
    edge = row(t=FIX - 2_000, land_d=2_000, hold=-0.0, xsig_d=3_000)
    assert not R.tainted(edge)                                      # hold -0.0 is not below 0
    # the other two conditions are bugs at any time
    assert R.tainted(row(t=FIX + 1_000, xsig_d=1_000)) and R.tainted(row(t=FIX + 1_000, land_d=-1))


def test_empty_fields_leave_their_condition_false():
    r = {k: "" for k in COLS} | {"rule": "P_pool0_wait"}
    assert not R.tainted(r) and not R.tainted({})
    assert not R.tainted(dict(as_csv([row()])[0], hold_s="", exit_signal_ms="nan"))


def test_untainted_and_by_book_count_what_they_skip():
    rows = as_csv([row(), bad(), bad(rule="B"), row(rule="B")])
    kept, n = R.untainted(rows)
    assert n == 2 and len(kept) == 2 and not any(R.tainted(r) for r in kept)
    by = R.taint_by_book(rows)
    assert by["P_pool0_wait"][0] == 1 and by["P_pool0_wait"][1] == pytest.approx(0.2) and by["B"][0] == 1


# ---------------------------------------------------------------- the readers

def test_the_allocator_skips_and_counts_tainted_trades(tmp_path):
    arm = A.ARMS[0]
    write_csv(tmp_path / "ledger.csv", [row(rule=arm), bad(rule=arm, mint="M2"), bad(rule="not_an_arm")])
    taint: dict = {}
    tr = A.paper_trades(tmp_path, 0, taint=taint)
    assert [x[2] for x in tr[arm]] == ["M1"] and taint == {arm: 1}
    assert len(A.paper_trades(tmp_path, 0)[arm]) == 1                # without the counter the same skip
    assert "Skipped: 1 paper trades" in "\n".join(A.taint_line(taint)) and A.taint_line({}) == []


def test_a1s_daily_run_reports_the_skipped(tmp_path, monkeypatch):
    arm = A.ARMS[0]
    write_csv(tmp_path / "ledger.csv", [row(rule=arm), bad(rule=arm, mint="M2")])
    (tmp_path / "state.json").write_text(json.dumps({"realistic_since": FIX - 3 * DAY}), encoding="utf-8")
    monkeypatch.setattr(A, "live_rule", lambda path=None: None)
    doc = A.run(now_ms=FIX + DAY, paper=tmp_path, out=tmp_path / "out", log=lambda *a: None)
    assert doc["tainted"] == {arm: 1}
    assert "Skipped: 1 paper trades" in (tmp_path / "out" / "allocator.md").read_text(encoding="utf-8")


def test_t9s_paper_history_skips_and_counts(tmp_path):
    arm = A.ARMS[0]
    write_csv(tmp_path / "ledger.csv", [row(rule=arm), bad(rule=arm, mint="M2")])
    (tmp_path / "state.json").write_text(json.dumps({"realistic_since": FIX - 3 * DAY}), encoding="utf-8")
    taint: dict = {}
    rw, _, days = T9.paper_history(tmp_path, until_ms=FIX + DAY, taint=taint)
    assert taint == {arm: 1}
    day = A.day_of(row()["exit_ms"])
    assert rw[arm][day] == pytest.approx(__import__("math").log(1 + A.SHARE * 0.1))


def test_the_calibration_skips_a_tainted_paper_trade_and_says_so():
    lv = [dict(row(mint=f"M{i}", t=FIX - DAY + i * 60_000), mode="test") for i in range(3)]
    pp = [row(mint="M0", t=FIX - DAY), bad(mint="M1", t=FIX - DAY + 60_000), row(mint="M2", t=FIX - DAY + 120_000)]
    cal = R.calibrate(lv, as_csv(pp), FIX - 2 * DAY, FIX)
    assert cal["n"] == 2 and cal["paper"] == 2 and cal["tainted"] == 1
    assert "1 paper trades of the late-row bug skipped" in R.calib_line(cal, "not yet", 1.0)
    clean = R.calibrate(lv, as_csv([row(mint="M0", t=FIX - DAY)]), FIX - 2 * DAY, FIX)
    assert clean["tainted"] == 0 and "late-row" not in R.calib_line(clean, "not yet", 1.0)


def test_the_live_ledger_is_never_judged_by_the_paper_rule():
    lv = [dict(bad(mint="M0"), mode="test")]
    cal = R.calibrate(as_csv(lv), as_csv([row(mint="M0")]), FIX - 2 * DAY, FIX)
    assert cal["live"] == 1 and cal["n"] == 1 and cal["tainted"] == 0


def test_the_paper_wallets_leave_the_tainted_trades_out():
    st = {"paper_wallets": {}}
    small = (("P_x_sw", "P_x", 0.1, 3, False),)
    rows = R.small_status(st, 100.0, small=small, taint={"P_x_sw": (2, 0.05)})
    r = rows[0]
    assert r["tainted"] == 2 and r["sol"] == pytest.approx(R.START_SOL - 0.05) and r["pnl_sol"] == pytest.approx(-0.05)
    assert r["eur"] == pytest.approx(r["sol"] * 100.0)
    assert R.small_status(st, None, small=small)[0]["tainted"] == 0
    assert any("Left out: 2 trades" in x for x in R.small_md(rows, 100.0))
    assert not any("Left out" in x for x in R.small_md(R.small_status(st, None, small=small), None))


def test_the_daily_job_writes_the_count_and_the_wallets_without_them(tmp_path, monkeypatch):
    from lab import report as rep
    from lab.pumpfun_rt import live_exec as LX
    monkeypatch.setattr(rep, "REPORTS", tmp_path / "reports")
    monkeypatch.setattr(LX, "data_dir", lambda: tmp_path / "live")
    monkeypatch.setattr(live, "paper_dir", lambda: tmp_path / "paper")
    monkeypatch.setattr(R, "sol_eur", lambda: None)
    monkeypatch.setattr(R, "factory_status", lambda state, eur, taint=None: [])
    (tmp_path / "reports" / "pumpfun_rt").mkdir(parents=True)
    (tmp_path / "live").mkdir()
    book = R.SMALL[0][0]
    write_csv(tmp_path / "paper" / "ledger.csv", [row(rule=book), bad(rule=book, mint="M2")])
    out = R.daily(now_ms=FIX + DAY)
    assert out["tainted"] == 1
    s = next(x for x in out["small"] if x["book"] == book)
    assert s["tainted"] == 1 and s["sol"] == pytest.approx(R.START_SOL - 0.2)
    md = (tmp_path / "reports" / "pumpfun_rt" / "realistic.md").read_text(encoding="utf-8")
    assert "holds 1 trades the late-row bug made" in md


def test_the_paper_review_and_the_ladder_say_how_many_the_wallets_leave_out(tmp_path, monkeypatch):
    from lab.ops import ladder, paper_books
    data = tmp_path / "data"
    p = data / "reports" / "pumpfun_rt" / "realistic.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps({"realistic_since": FIX - 3 * DAY, "factory": [],
                             "small": [{"book": "P_x_sw10o3n", "strategy": "P_x", "sol": 0.5, "tainted": 3},
                                       {"book": "P_y_sw10o3n", "strategy": "P_y", "sol": 0.6}]}), encoding="utf-8")
    by = {b["name"]: b for b in paper_books.books(data)}
    assert by["P_x_sw10o3n"]["tainted"] == 3 and by["P_x_sw10o3n"]["value"] == 0.5 and by["P_y_sw10o3n"]["tainted"] == 0
    paper_books.main(data)
    assert "3 pump.fun paper trades" in (data / "reports" / "paper_books" / "latest.md").read_text(encoding="utf-8")
    monkeypatch.setenv("PYTHIA_DATA", str(data))
    res = tmp_path / "results"
    res.mkdir()
    d = ladder.build(data, FIX + DAY, results=res, added=lambda p: None)
    rows = {r["id"]: r for r in d["rows"]}
    assert rows["book:P_x_sw10o3n"]["tainted"] == 3 and rows["book:P_y_sw10o3n"]["tainted"] == 0
    assert d["tainted"] == 3 and "leaves out 3 paper trades" in ladder.markdown(d)


def test_the_studys_readiness_skips_and_counts(tmp_path):
    p = tmp_path / "ledger.csv"
    write_csv(p, [row(), bad(mint="M2"), bad(mint="M3")])
    s = study.shadow_stats(FIX + DAY, path=p)["P_pool0_wait"]
    assert s["n"] == 1 and s["mean"] == pytest.approx(0.1) and s["tainted"] == 2


def test_the_daily_card_skips_and_says_so(tmp_path):
    p = tmp_path / "ledger.csv"
    t = FIX - DAY + 3_600_000                                      # closed the day before now_ms's day
    write_csv(p, [row(t=t), bad(t=t, mint="M2")])
    now = t + DAY
    y = card.shadow_yesterday(now, path=p)["P_pool0_wait"]
    assert y["n"] == 1 and y["mean"] == pytest.approx(0.1) and y["tainted"] == 1
    c = card.daily_card({}, None, {"P_pool0_wait": y}, None, now, "en")
    assert "Left out of these numbers: 1 paper trades" in c.render("telegram", "en")
    assert "Nicht in diesen Zahlen: 1 Paper-Trades" in card.daily_card({}, None, {"P_pool0_wait": y}, None, now,
                                                                       "de").render("telegram", "de")
    c0 = card.daily_card({}, None, card.shadow_yesterday(now, path=tmp_path / "none.csv"), None, now, "en")
    assert "Left out of these numbers" not in c0.render("telegram", "en")


def test_the_execution_reports_paper_slip_skips_and_counts(tmp_path):
    p = tmp_path / "ledger.csv"
    write_csv(p, [row(slip=-0.01), bad(slip=-0.9, mint="M2")])
    s = measure.paper_slip("P_pool0_wait", path=p)
    assert s["n"] == 1 and s["median"] == pytest.approx(-0.01) and s["tainted"] == 1


def test_s17s_twins_skip_and_count(tmp_path):
    b = Y17.BASES[0]
    t = Y17.day_start(Y17.TWIN_DAYS[0]) + 3_600_000
    write_csv(tmp_path / "ledger.csv", [row(rule=b, t=t), bad(rule=b, t=t, mint="M2")])
    write_csv(tmp_path / "failed.csv", [], cols=["rule", "mint", "signal_ms", "land_ms", "pnl_sol", "why"])
    taint: dict = {}
    es = Y17.ledger_entries(tmp_path, taint=taint)[b]
    assert [e["mint"] for e in es] == ["M1"] and taint == {b: 1}


# ---------------------------------------------------------------- the study

def test_the_study_registers_its_trials_first_and_writes_the_report(tmp_path, monkeypatch):
    reg = tmp_path / "registry.jsonl"
    monkeypatch.setenv("PYTHIA_TRIALS_REGISTRY", str(reg))
    led = tmp_path / "ledger.csv"
    write_csv(led, [row(), bad(mint="M2"), row(mint="M3", slip=-0.7), row(t=FIX + 1_000, mint="M4", hold=-1.0)])
    out = tmp_path / "p1.md"
    res = taint_p1.run(led, out, log=lambda *a: None)
    ids = [json.loads(x)["id"] for x in reg.read_text(encoding="utf-8").splitlines()]
    assert "hand:p1:ledger_taint" in ids and "hand:p1:ledger_taint_strict" in ids
    c = res["conditions"]
    assert c["any"] == 1 and c["strict_extra"] == 1 and c["hold"] == 1 and c["exit_before_land"] == 1
    tot = {r["period"]: r for r in res["table"] if r["book"] == "all books"}
    assert tot["before"]["all"][0] == 3 and tot["before"]["chosen"][0] == 2 and tot["before"]["strict"][0] == 1
    assert tot["after"]["all"][0] == 1 and tot["after"]["tainted"] == 0
    md = out.read_text(encoding="utf-8")
    assert "| all books | before | 3 |" in md and chr(0x2014) not in md
