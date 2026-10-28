"""P2: the selection gap between the live pump.fun bot and its paper twin (lab.pumpfun_rt.selection_p2). On a fake
live folder (orders, ledger, skipped, seen) and fake paper signals: the live runs and their rules, every live outcome
of a paper signal (traded, buy failed by kind, paused, refused by the wallet or the brake, ran away before the send,
not seen by the live feed, other), the paper's reason for every live trade without a twin, the gap splitting exactly
into its parts and the selection part into its reasons, the gate line in the calibration report, and the trials
registered before the first number. No network, no wallet; nothing live is written.

Run from research/lab:  python -m pytest tests/test_pumpfun_selection_gap_p2.py
"""

from __future__ import annotations

import csv
import json

import pytest

from lab.pumpfun_rt import realistic as R
from lab.pumpfun_rt import selection_p2 as S

T0 = 1_792_771_885_000                    # run "1792771885-1" starts here
RUN = "1792771885-1"
MIN = 60_000
LIVE_COLS = ["mode", "rule", "mint", "symbol", "signal_ms", "land_ms", "exit_ms", "exit_why", "entry_price",
             "exit_price", "ret", "run"]
PAPER_COLS = ["rule", "mint", "symbol", "signal_ms", "land_ms", "exit_signal_ms", "exit_ms", "exit_why", "ret",
              "hold_s", "slip", "pnl_sol"]


def prow(mint, t, ret, rule="P_pool0_wait", why="take", **kw):
    """A closed paper trade signalled at t, landed 1 s later, closed 30 s after that."""
    return {"rule": rule, "mint": mint, "symbol": mint, "signal_ms": t, "land_ms": t + 1_000,
            "exit_signal_ms": t + 20_000, "exit_ms": t + 31_000, "exit_why": why, "ret": ret, "hold_s": 30.0,
            "slip": 0.0, "pnl_sol": ret * 0.1, **kw}


def lrow(mint, t, ret, rule="P_pool0_wait", run=RUN):
    return {"mode": "test", "rule": rule, "mint": mint, "symbol": mint, "signal_ms": t, "land_ms": t + 6_000,
            "exit_ms": t + 60_000, "exit_why": "take", "entry_price": 1.0, "exit_price": 1 + ret, "ret": ret,
            "run": run}


def order(what, mint, t, run=RUN, **kw):
    return {"t": t, "what": what, "pid": 0, "side": "buy", "mint": mint, "venue": "pool", "run": run, "mode": "test",
            **kw}


def skip(mint, t, why, rule="P_pool0_wait", run=RUN):
    return {"t": t, "mint": mint, "rule": rule, "why": why, "run": run}


def write_csv(p, rows, cols):
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def write_jsonl(p, rows):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def t(i):
    return T0 + i * MIN


@pytest.fixture()
def world(tmp_path):
    """One live run of P_pool0_wait from T0 to t(60) (seen.jsonl from t(30)), one of P_pool0 later, and a paper
    signal for every outcome."""
    live, paper = tmp_path / "live", tmp_path / "paper"
    orders = [order("sent", "TRD", t(1) + 5_000), order("filled", "TRD", t(1) + 9_000, sol=1),
              order("sent", "TRD2", t(2) + 5_000), order("filled", "TRD2", t(2) + 9_000, sol=1),
              order("sent", "F6040", t(3)), order("failed", "F6040", t(3) + 2_000,
                                                  why="failed on chain: {'InstructionError': [6, {'Custom': 6040}]}"),
              order("sent", "FLAND", t(4)), order("failed", "FLAND", t(4) + 2_000, why="not landed"),
              order("sent", "FSIM", t(5)), order("failed", "FSIM", t(5) + 1_000,
                                                 why="RuntimeError: Transaction simulation failed"),
              order("sent", "RETRY", t(6)), order("failed", "RETRY", t(6) + 1_000, why="not landed"),
              order("sent", "LONLY", t(40)), order("filled", "LONLY", t(40) + 5_000, sol=1),
              order("sent", "LSKIP", t(41)), order("filled", "LSKIP", t(41) + 5_000, sol=1),
              order("sent", "LKNOWN", t(42)), order("filled", "LKNOWN", t(42) + 5_000, sol=1),
              order("sent", "P0", t(310), run="1792790000-1"), order("filled", "P0", t(310) + 5_000,
                                                                     run="1792790000-1", sol=1)]
    ledger = [lrow("TRD", t(1), -0.10), lrow("TRD2", t(2), 0.30), lrow("RETRY", t(6), 0.05),
              lrow("LONLY", t(40), -0.40), lrow("LSKIP", t(41), 0.20), lrow("LKNOWN", t(42), 0.0),
              lrow("P0", t(310), 0.10, rule="P_pool0", run="1792790000-1")]
    skipped = [skip("PAUSE", t(7), "paused by the owner since 17:42 UTC"),
               skip("WALLET", t(8), "stake paused: the wallet cannot pay one trade of 0.05 SOL (100 % of 0.04)"),
               skip("BRAKE", t(9), "max exposure"),
               skip("RAN", t(10), "price ran away (+805 %)"),
               skip("CRE", t(11), "creation not seen"),
               skip("NOPOOL", t(12), "no pool state (PumpSwap stream down)"),
               skip("PLAIN", t(13), "not a plain SOL pool"),
               skip("OTHERRULE", t(14), "max exposure", rule="P_pool0")]
    seen = [{"t": t(30), "mint": "FIRST", "rule": "P_pool0_wait", "run": RUN},
            {"t": t(31), "mint": "SEEN", "rule": "P_pool0_wait", "run": RUN},
            {"t": t(60), "mint": "LAST", "rule": "P_pool0_wait", "run": RUN}]
    write_jsonl(live / "orders.jsonl", orders)
    write_csv(live / "ledger.csv", ledger, LIVE_COLS)
    write_jsonl(live / "skipped.jsonl", skipped)
    write_jsonl(live / "seen.jsonl", seen)
    write_jsonl(live / "journal.jsonl", [])
    pl = [prow("TRD", t(1), 0.20), prow("TRD2", t(2), 0.10), prow("F6040", t(3), 2.0), prow("FLAND", t(4), -0.1),
          prow("RETRY", t(6), 0.15), prow("PAUSE", t(7), 0.5), prow("WALLET", t(8), -0.2), prow("BRAKE", t(9), 0.0),
          prow("RAN", t(10), 1.0), prow("CRE", t(11), -0.3), prow("NOPOOL", t(12), 0.1),
          prow("PLAIN", t(13), -0.5), prow("NOLOG", t(19), 0.3), prow("SEEN", t(31), 0.4),
          prow("UNSEEN", t(32), 0.6), prow("OTHERRULE", t(14), 0.2),
          prow("OFF", t(200), 9.0),                                     # no live run then
          prow("WRONGRULE", t(15), 9.0, rule="P_cmig_model"),           # live ran another rule then
          prow("TAINT", t(16), 9.0, hold_s=-1.0, exit_signal_ms=t(16) + 500),
          prow("RESTART", t(17), 9.0, why="restart"),
          prow("TRD", t(25), 5.0),                                      # a later row of the same coin: not a signal
          prow("LKNOWN", t(42), 0.1, rule="P_pool60"),                  # the collector had LKNOWN, another book
          prow("P0", t(311), 0.3, rule="P_pool0")]
    write_csv(paper / "ledger.csv", pl, PAPER_COLS)
    write_csv(paper / "failed.csv", [{"rule": "P_pool0_wait", "mint": "FSIM", "signal_ms": t(5), "land_ms": "",
                                       "why": "not landed", "pnl_sol": 0}], ["rule", "mint", "signal_ms", "land_ms",
                                                                             "why", "pnl_sol"])
    write_jsonl(paper / "skipped.jsonl", [skip("LSKIP", t(41) + 3_000, "no pool state")])
    (paper / "state.json").write_text(json.dumps({"realistic_since": t(35)}), encoding="utf-8")
    return live, paper


def by_mint(res):
    return {x["mint"]: x for x in res["signals"]}


# ---------------------------------------------------------------- runs and signals

def test_runs_have_their_rule_and_span(world):
    live, _ = world
    rs, dropped = S.runs(S.read_live(live))
    assert dropped == 0
    assert [(r["rule"], r["start"]) for r in rs] == [("P_pool0_wait", T0), ("P_pool0", 1_792_790_000_000)]
    assert rs[0]["end"] == t(60) and S.on(rs, "P_pool0_wait", t(59)) and not S.on(rs, "P_pool0_wait", t(61))
    assert S.on(rs, "P_pool0_wait", T0 - 5_000) and not S.on(rs, "P_pool0", t(1))


def test_signals_only_while_a_run_of_their_rule_was_on_without_tainted_or_restart_rows(world):
    live, paper = world
    res = S.compute(S.read_live(live), S.read_paper(paper))
    m = by_mint(res)
    assert "OFF" not in m and "WRONGRULE" not in m and "TAINT" not in m and "RESTART" not in m
    assert res["left_out"] == {"tainted": 1, "restart": 1}
    assert m["TRD"]["ret"] == 0.20                           # the first row of the coin, not the later one
    assert m["FSIM"]["ret"] is None                          # a failed paper buy: a signal without a return


# ---------------------------------------------------------------- every live outcome

def test_each_live_outcome_is_found(world):
    live, paper = world
    m = by_mint(S.compute(S.read_live(live), S.read_paper(paper)))
    got = {k: (v["reason"], v["detail"]) for k, v in m.items()}
    assert got["TRD"] == (S.TRADED, S.TRADED) and m["TRD"]["live_ret"] == -0.10
    assert got["RETRY"] == (S.TRADED, S.TRADED) and m["RETRY"]["live_ret"] == 0.05   # failed, then a trade
    assert got["F6040"] == (S.FAILED, "6040")
    assert got["FLAND"] == (S.FAILED, "not landed")
    assert got["FSIM"] == (S.FAILED, "simulation failed")
    assert got["PAUSE"] == (S.PAUSED, "paused by the owner")
    assert got["WALLET"] == (S.REFUSED, "stake paused: the wallet cannot pay one trade of 0.05 SOL")
    assert got["BRAKE"] == (S.REFUSED, "max exposure")
    assert got["RAN"] == (S.RAN, R.RAN_AWAY)
    assert got["CRE"] == (S.UNSEEN, "creation not seen")
    assert got["NOPOOL"] == (S.UNSEEN, "no pool state (PumpSwap stream down)")
    assert got["UNSEEN"] == (S.UNSEEN, "never seen by the live service")
    assert got["SEEN"] == (S.OTHER, "seen, no decision")
    assert got["PLAIN"] == (S.OTHER, "not a plain SOL pool")
    assert got["NOLOG"] == (S.OTHER, S.NO_LOG)               # before seen.jsonl was written
    assert got["OTHERRULE"] == (S.OTHER, S.NO_LOG)           # a skip of another rule is not this signal's


@pytest.mark.parametrize("why,want", [
    ("paused by the owner since 08:00 UTC", S.PAUSED),
    ("stake paused: wallet under 0.25 SOL", S.REFUSED),
    ("max open positions", S.REFUSED),
    ("daily loss limit", S.REFUSED),
    ("total budget stop", S.REFUSED),
    ("refused: above the stake cap", S.REFUSED),
    ("price ran away (+167 %)", S.RAN),
    ("price ran away on landing", S.OTHER),
    ("no pool state", S.UNSEEN),
    ("blocked (symbol TRUMP)", S.OTHER),
    ("no decision", S.OTHER)])
def test_skip_reasons(why, want):
    assert S.skip_reason(why)[0] == want


# ---------------------------------------------------------------- live trades without a paper twin

def test_live_trades_without_a_paper_twin_have_the_papers_reason(world):
    live, paper = world
    res = S.compute(S.read_live(live), S.read_paper(paper))
    lo = {x["mint"]: x["why"] for x in res["live_only"]}
    assert lo == {"LSKIP": "no pool state", "LONLY": "no paper record",
                  "LKNOWN": "no paper record (the collector had the coin)"}
    assert "TRD" not in lo and "P0" not in lo


def test_a_live_trade_before_its_paper_twin_started(world):
    live, paper = world
    lv, pp = S.read_live(live), S.read_paper(paper)
    lv["ledger"].append(lrow("EARLY", T0 - 5 * MIN, 0.1))
    pp["ledger"] = [r for r in pp["ledger"] if r["rule"] != "P_pool0_wait" or R._f(r["signal_ms"]) > T0]
    lo = {x["mint"]: x["why"] for x in S.compute(lv, pp)["live_only"]}
    assert lo["EARLY"] == "no paper record (the paper twin not started yet)"


# ---------------------------------------------------------------- the gap

def test_the_gap_splits_exactly_and_the_selection_part_by_reason(world):
    live, paper = world
    res = S.compute(S.read_live(live), S.read_paper(paper))
    g = res["gap"]
    ps = [x for x in res["signals"] if x["ret"] is not None]
    pairs = [x for x in ps if x["live_ret"] is not None]
    assert g["n_paper"] == len(ps) and g["n_live"] == 7 and g["n_pairs"] == len(pairs) == 4
    assert g["P_all"] == pytest.approx(sum(x["ret"] for x in ps) / len(ps))
    assert g["P_m"] == pytest.approx(sum(x["ret"] for x in pairs) / 4)
    assert g["L_m"] == pytest.approx(sum(x["live_ret"] for x in pairs) / 4)
    assert g["L_all"] == pytest.approx((-0.1 + 0.3 + 0.05 - 0.4 + 0.2 + 0.0 + 0.1) / 7)
    assert g["gap"] == pytest.approx(g["selection"] + g["same_coins"] + g["live_own"])
    assert g["selection"] == pytest.approx(sum(g[f"term:{r}"] for r in S.REASONS))
    assert g[f"term:{S.FAILED}"] > 0                         # the 6040 coin made +200 % on paper
    for k in ("gap", "selection", "same_coins"):
        lo, hi = g["band"][k]
        assert lo <= hi


def test_the_bootstrap_is_seeded_and_an_empty_side_gives_no_number():
    sig = [{"ret": 0.1, "reason": S.TRADED, "live_ret": 0.0}, {"ret": 0.5, "reason": S.UNSEEN, "live_ret": None}]
    a, b = S.gap(sig, [0.0, -0.1], draws=200), S.gap(sig, [0.0, -0.1], draws=200)
    assert a["band"] == b["band"] and a["gap"] == pytest.approx(0.3 - (-0.05))
    assert S.gap(sig, [])["gap"] is None and S.gap([], [0.1])["gap"] is None


def test_the_realistic_part_keeps_only_what_came_after_realistic_since(world):
    live, paper = world
    pp = S.read_paper(paper)
    res = S.compute(S.read_live(live), pp, since=pp["since"])
    assert {x["mint"] for x in res["signals"]} == {"P0"} and res["gap"]["n_live"] == 4


# ---------------------------------------------------------------- the gate line and the report

def test_the_gate_line_passes_under_2_points(world):
    live, paper = world
    sel = S.gate(live, paper)
    assert sel["pts"] == pytest.approx(S.compute(S.read_live(live), S.read_paper(paper))["gap"]["gap"] * 100)
    assert sel["pass"] is (sel["pts"] < 2.0) and sel["gate_pts"] == 2.0
    assert sel["line"].startswith("paper minus live on all live signals")
    g = {"gap": 0.019, "n_paper": 1, "n_live": 1, "P_all": 0.0, "L_all": 0.0, "selection": 0.0, "same_coins": 0.0,
         "live_own": 0.0, "band": {}}
    assert "passes the ladder's gate" in S.line({"gap": g})
    assert "fails the ladder's gate" in S.line({"gap": {**g, "gap": 0.02}})
    assert "not measured" in S.line({"gap": {"gap": None}})


def test_the_calibration_report_carries_the_gate_line(world):
    live, paper = world
    sel = S.gate(live, paper)
    d = {"updated_ms": T0, "fit": R.Fit().to_json(), "config": {}, "calibration": {"line": "live vs realistic"},
         "selection": sel}
    md = R.markdown(d)
    assert md.index("live vs realistic") < md.index(sel["line"])
    assert sel["line"] not in R.markdown({**d, "selection": None})


def test_the_study_registers_its_trials_first_and_writes_the_report(world, tmp_path, monkeypatch):
    live, paper = world
    reg = tmp_path / "registry.jsonl"
    monkeypatch.setenv("PYTHIA_TRIALS_REGISTRY", str(reg))
    out = tmp_path / "p2.md"
    res = S.run(live, paper, out, log=lambda *a: None)
    ids = [json.loads(x)["id"] for x in reg.read_text(encoding="utf-8").splitlines()]
    assert {f"hand:p2:{k}" for k in ("paper_minus_live", "selection", "same_coins", "reasons",
                                     "paper_minus_live_realistic")} <= set(ids)
    assert res["realistic"]["since"] == t(35)
    md = out.read_text(encoding="utf-8")
    assert "paper minus live on all live signals" in md and "| P_pool0_wait | buy failed | 3 |" in md
    assert "no paper record (the collector had the coin)" in md and chr(0x2014) not in md


def test_nothing_live_is_written(world):
    live, paper = world
    before = {p.name: p.read_bytes() for p in list(live.iterdir()) + list(paper.iterdir())}
    S.gate(live, paper)
    S.compute(S.read_live(live), S.read_paper(paper))
    assert {p.name: p.read_bytes() for p in list(live.iterdir()) + list(paper.iterdir())} == before


def test_the_daily_job_writes_the_gate_line_into_the_calibration_report(world, tmp_path, monkeypatch):
    from lab import report as rep
    from lab.pumpfun_rt import live as L
    from lab.pumpfun_rt import live_exec as LX
    live, paper = world
    monkeypatch.setattr(rep, "REPORTS", tmp_path / "reports")
    monkeypatch.setattr(LX, "data_dir", lambda: live)
    monkeypatch.setattr(L, "paper_dir", lambda: paper)
    (tmp_path / "reports" / "pumpfun_rt").mkdir(parents=True)
    R.daily(t(400))
    d = json.loads((tmp_path / "reports" / "pumpfun_rt" / "realistic.json").read_text(encoding="utf-8"))
    assert d["selection"]["pts"] == pytest.approx(S.gate(live, paper)["pts"])
    md = (tmp_path / "reports" / "pumpfun_rt" / "realistic.md").read_text(encoding="utf-8")
    assert "paper minus live on all live signals" in md and chr(0x2014) not in md
