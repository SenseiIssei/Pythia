"""F3, the pump.fun factory: the typed space and its strategies, the select filter's "min", the trial's score and the
deflated bar, the ledger that only grows and a night that resumes, the held-back days scored once, the paper books
(added, retired, proposed), the model settings adopted only when better, the retrain reading them, the collector's
factory books, the reports and the card, the job. No network, no wallet.

Run from research/lab:  python -m pytest tests/test_pumpfun_factory_f3.py
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from lab.pumpfun_rt import factory as F
from lab.pumpfun_rt import model as M
from lab.pumpfun_rt import pipeline as P
from lab.pumpfun_rt import realistic as R
from lab.pumpfun_rt import sim
from lab.pumpfun_rt import smallwallet as SW
from test_pumpfun_exit_runners import Pool
from test_pumpfun_realistic import fixed_fit
from test_pumpfun_rt import SOL, T0, Fixed

optuna = pytest.importorskip("optuna")
DAY = 86_400_000
EM = "\u2014"
DAYS = ["2026-10-20", "2026-10-21", "2026-10-22", "2026-10-23"]
PLAIN = {"entry": "migration", "delay_s": 0, "wait_pool_s": 0, "win": "none", "rug": "none", "heat": False,
         "liq": False, "buyers": False, "r3": False, "block": False, "tp": 0.30, "sl": 0.20, "time_s": 300,
         "lock": False, "partial": False, "share": 0.25, "max_open": 2, "brake": True}


def sampled(n: int, seed: int = 1) -> list[dict]:
    st = optuna.create_study(sampler=optuna.samplers.RandomSampler(seed=seed))
    out = []
    for _ in range(n):
        t = st.ask()
        out.append(F.space(t))
        st.tell(t, 0.0)
    return out


# ---------------------------------------------------------------- the space and the strategies

def test_every_point_of_the_space_is_a_strategy_the_pipeline_can_run():
    for i, p in enumerate(sampled(80)):
        s = F.strategy_of(p, f"F3_{i:05d}")
        assert s.family == "E" and s.entry in ("migration", "trend") and s.p["base"] == F.KEY
        assert set(s.flt) <= {"select", "trend", "cut", "block"} and EM not in s.label
        assert s.exits.ladder[-1][1] == 1.0 and 0.05 <= s.exits.sl <= 0.5 and 30 <= s.exits.time_s <= 1800
        assert not s.exits.dev_sell and not s.exits.pull
        for label, (how, k) in (s.flt.get("select") or {}).items():
            assert label in F.SELECT and how in ("top", "min", "max")
        if s.entry == "migration":
            assert 0 <= s.p["delay_s"] <= 60 and s.p.get("wait_pool_s", 0) in (0, 5)
        else:
            assert s.p["list"] == "fresh" and 1 <= s.p["top"] <= 5 and s.p["to_s"] > s.p["from_s"] >= 60
        assert 0.05 <= p["share"] <= 0.25 and p["max_open"] in (1, 2, 3)
    a = F.strategy_of({**PLAIN, "delay_s": 2, "win": "top", "trend_models": True}, "a")
    b = F.strategy_of({**PLAIN, "delay_s": 3, "win": "top", "trend_models": False}, "b")
    assert a.flt["select"] == {"win0t": ("top", 0.3)} and b.flt["select"] == {"win5": ("top", 0.3)}


def test_the_reference_trial_is_r2s_pick():
    s, ref = F.strategy_of(F.REFERENCE, "F3_ref"), P.BY_NAME["P_pool5_top30t"]
    assert s.entry == ref.entry and s.p["delay_s"] == ref.p["delay_s"] and s.flt == ref.flt
    assert s.exits == ref.exits
    assert (F.REFERENCE["share"], F.REFERENCE["max_open"], F.REFERENCE["brake"]) == (0.10, 3, False)
    assert F.REF_BOOK in {x[0] for x in R.SMALL}


def test_the_filters_and_exits_land_where_the_pipeline_reads_them():
    p = {**PLAIN, "rug": "max", "rug_k": 0.5, "trend_models": True, "heat": True, "heat_k": 1.2, "liq": True,
         "liq_sol": 60.0, "buyers": True, "buyers_min": 12, "r3": True, "lock": True, "lock_arm": 0.10,
         "partial": True, "part_share": 0.5, "part_mult": 3.0, "win": "min", "win_k": 1.5}
    s = F.strategy_of(p, "F3_00001")
    assert s.flt["select"] == {"win0t": ("min", 1.5), "rug0t": ("max", 0.5)} and s.flt["trend"] == {"heat": 1.2}
    assert s.flt["cut"]["pool_sol"] == ("min", 60.0) and s.flt["cut"]["unique_buyers"] == ("min", 12)
    assert s.flt["cut"]["first5_share"] == P.RUG_CUT["first5_share"]
    assert s.exits.ladder == ((0.3, 0.5), (0.9, 1.0)) and s.exits.lock == ((0.1, 0.02, 1.0), (0.2, 0.1, 1.0))


class _Sel:
    def __init__(self, p):
        self.p, self.base, self.features, self.booster = p, 0.2, [], True

    def predict(self, x):
        return np.array([self.p])


def test_the_select_filter_takes_a_minimum_multiple_of_the_base_rate(monkeypatch):
    monkeypatch.setattr("lab.pumpfun_rt.selfeat.decision_features", lambda eng, tok, t: {})
    eng = sim.Engine([], costs=Fixed(), select=True)
    pipe = P.Pipeline(eng, [], P.PaperExecutor())
    for p, ok in ((0.31, True), (0.29, False)):
        eng.models = {"sel_win0": _Sel(p)}
        assert pipe.select_ok({"win0": ("min", 1.5)}, None, T0) == (ok, p)


def test_a_factory_book_trades_on_its_own_wallet_with_its_sizing():
    eng = sim.Engine([], costs=Fixed())
    owner = R.LiveConfig(wallet=True, share=1.0, brake=False, floor_sol=0.0, max_open=1)
    m = R.Model(fixed_fit(), owner)
    wallets = {}
    book = R.factory_books(eng, m, wallets, specs=[("F3_00007", PLAIN)])[0]
    assert set(wallets) == {"F3_00007"} and book.exec.model.cfg.share == 0.25 and book.exec.model.cfg.max_open == 2
    pool = Pool(eng)
    eng.advance(T0 + 1)
    pool.trade(T0 + 8_000, True, SOL // 1000)
    eng.advance(T0 + 9_000)
    p = next(iter(book.pos.values()))
    assert p["stake_l"] == int(0.13 * SOL) and book.strats["F3_00007"].p["base"] == F.KEY
    assert book.blocked is None
    assert R.factory_books(sim.Engine([], costs=Fixed()), m, {}, specs=[("F3_00008", {**PLAIN, "block": True})])[0] \
        .blocked is not None


def test_the_block_list_in_a_replay_leaves_out_its_mint_lines(tmp_path):
    f = tmp_path / "blocked.txt"
    f.write_text("MintAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA1\nsymbol:SHEKEL\n")

    class Tok:
        mint, creator, devs, symbol, name = "MintAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA1", None, (), "X", "x"
    u = F.Unminted(paths=[f])
    assert u("F3_1", Tok()) is None
    Tok.symbol = "$shekel"
    assert u("F3_1", Tok()).startswith("blocked (symbol")


# ---------------------------------------------------------------- the score and the bar

def entries(days, n=10, win=0.012, lose=-0.008, every=2):
    out = []
    for d in days:
        for i in range(n):
            t = SW.day_start(d) + 60_000 * (i + 1)
            g = win if i % every else lose
            out.append({"mint": f"m{d}{i}", "signal_ms": t, "exit_ms": t + 30_000, "failed": False, "cost": 0.1,
                        "proceeds": 0.1 + g, "fees": 0.0004, "pnl": g - 0.0004, "q_in": 85.0, "q_out": 85.0})
    return out


def test_a_trial_is_scored_by_its_median_wallet_less_the_ruin_penalty():
    good = F.score(entries(DAYS[:2]), PLAIN, DAYS[:2], F.draws(2, paths=200))
    bad = F.score(entries(DAYS[:2], win=-0.02, lose=-0.09), {**PLAIN, "share": 0.25}, DAYS[:2], F.draws(2, paths=200))
    assert good["median"] > F.START_SOL > bad["median"] and good["entries"] == 20 and good["sharpe"] > 0
    assert bad["score"] == pytest.approx(bad["median"] - F.RUIN_PENALTY * F.START_SOL * bad["p_lost80"])
    none = F.score([], PLAIN, DAYS[:2])
    assert none["median"] == pytest.approx(F.START_SOL) and none["entries"] == 0 and none["score"] == none["median"]
    out = F.score(entries(DAYS[:3]), PLAIN, DAYS[:2], F.draws(2, paths=50))
    assert out["entries"] == 20                              # a day outside the scored days does not count


def test_the_bar_rises_with_every_trial_counted():
    rng = np.random.default_rng(1)
    few, many = list(rng.normal(0, 0.05, 10)), list(rng.normal(0, 0.05, 1000))
    assert 0 < F.bar(few) < F.bar(many) and F.bar([0.1]) == 0.0
    r = {"entries": 400, "sharpe": 0.12, "skew": 0.0, "kurt": 3.0, "median": 0.7, "days": [f"d{i}" for i in range(10)]}
    assert F.deflated(r, few) > F.deflated(r, many)
    assert F.passes(r, 0.99) and not F.passes(r | {"median": 0.5}, 0.99) and not F.passes(r | {"entries": 5}, 0.99)
    assert not F.passes(r | {"days": r["days"][:9]}, 0.99)   # under MIN_DAYS scored days: no winner


def planted(rng, clean: int = 200, empty: int = 60, few: int = 40) -> tuple[list[dict], list[dict]]:
    """Trials of no skill with MIN_ENTRIES (Sharpe per entry about N(0, 0.05)), then the junk: trials with no entries
    (Sharpe 0) and with a handful (wild Sharpes)."""
    ok = [{"kind": "trial", "entries": 200, "sharpe": float(x)} for x in rng.normal(0, 0.05, clean)]
    junk = [{"kind": "trial", "entries": 0, "sharpe": 0.0} for _ in range(empty)]
    junk += [{"kind": "trial", "entries": 3, "sharpe": float(x)} for x in rng.choice([-4.0, 3.0, 6.0], few)]
    return ok, junk


def test_trials_without_min_entries_count_but_do_not_move_the_bars_noise():
    ok, junk = planted(np.random.default_rng(7))
    sh, n = F.pool(ok + junk)
    assert n == len(ok) + len(junk) and sorted(sh) == sorted(r["sharpe"] for r in ok)
    clean = F.bar(*F.pool(ok))
    assert F.bar(sh, n) == pytest.approx(F.bar([r["sharpe"] for r in ok], n))   # only the count changes
    assert clean < F.bar(sh, n) < clean * 1.1                    # 300 trials instead of 200: a little higher
    old = F.bar([r["sharpe"] for r in ok + junk])                # the variance over every trial, as before R7
    assert old > 5 * F.bar(sh, n)
    edge = {"entries": 600, "n_eff": 400.0, "sharpe": 0.3, "skew": 0.0, "kurt": 3.0, "median": 0.7,
            "days": [f"d{i}" for i in range(12)]}
    assert F.passes(edge, F.deflated(edge, sh, n)) and F.deflated(edge, sh, n) > 0.99   # a real edge passes now
    assert F.deflated(edge, [r["sharpe"] for r in ok + junk]) < 0.5                     # and could not before
    noise = edge | {"sharpe": 0.05}
    assert not F.passes(noise, F.deflated(noise, sh, n))


def test_a_trial_is_scored_per_day_with_a_standard_error_by_day():
    days = [f"2026-10-{d:02d}" for d in range(10, 22)]
    rng = np.random.default_rng(3)
    iid = [e | {"pnl": float(rng.normal(0.002, 0.01))} for e in entries(days, n=20)]
    # the same mean, but every entry of a day wins or loses with its day: 240 entries hold 12 days' evidence
    sign = rng.choice([-1.0, 1.0], len(days))
    clus = [e | {"pnl": 0.002 + 0.01 * sign[k // 20] + float(rng.normal(0, 0.001))} for k, e in enumerate(iid)]
    a, b = F.score(iid, PLAIN, days, F.draws(len(days), paths=20)), F.score(clus, PLAIN, days, F.draws(12, paths=20))
    assert a["entries"] == b["entries"] == 240 and a["days_traded"] == b["days_traded"] == 12
    assert a["n_eff"] > 100 and b["n_eff"] < 20                  # the deflation counts the days, not the entries
    assert b["hi"] - b["lo"] > 2 * (a["hi"] - a["lo"]) and a["lo"] < a["mean"] < a["hi"]
    assert len(b["day_pnl"]) == 12 and sum(b["day_pnl"]) == pytest.approx(b["mean"] * 240)
    sh = list(np.random.default_rng(1).normal(0, 0.05, 100))
    assert F.deflated(b, sh) < F.deflated(b | {"n_eff": 240.0}, sh)
    one = F.score(entries(days[:1], n=30), PLAIN, days, F.draws(12, paths=20))
    assert one["days_traded"] == 1 and one["n_eff"] == 0.0 and F.deflated(one, sh) == 0.0   # one day: no evidence
    big = iid[:49] + [iid[49] | {"pnl": 0.5}]                    # one +500 % entry among 50
    tb = F.score(big, PLAIN, days, F.draws(12, paths=20))
    assert tb["mean"] > 0.1 and tb["trimmed"] < 0.06             # the trimmed mean leaves it out


def test_the_days_held_back_the_night_before_stay_out_of_the_search(monkeypatch):
    from lab.pumpfun_rt import store
    rec = [f"2026-10-{d:02d}" for d in range(1, 21)]
    monkeypatch.setattr(store, "days", lambda root=None: rec)
    now = SW.day_start("2026-10-20") + DAY // 2
    led = [{"kind": "holdback", "id": "F3_00001", "night": "2026-10-18", "days": ["2026-10-16", "2026-10-17"]},
           {"kind": "holdback", "id": "F3_00002", "night": "2026-10-19", "days": ["2026-10-17", "2026-10-18"]},
           {"kind": "holdback", "id": "F3_00003", "night": "2026-10-20", "days": ["2026-10-18", "2026-10-19"]}]
    assert F.held_before(led, "2026-10-20") == ["2026-10-17", "2026-10-18"]   # the last night before, not tonight
    assert F.held_before([], "2026-10-20") == []
    d = F.Days(now, held=F.held_before(led, "2026-10-20"))
    assert d.days == rec[-16:-1] and d.hold == ["2026-10-18", "2026-10-19"] and len(d.days) == F.WINDOW_DAYS
    assert d.replay == d.days[:-2] and d.held == ["2026-10-17"]  # 2026-10-18 is tonight's held-back day anyway
    assert d.search == d.days[:-3] and not set(d.search) & {"2026-10-17", "2026-10-18", "2026-10-19"}
    assert len(d.search) - 2 >= F.MIN_DAYS                       # less the two first days without every model


# ---------------------------------------------------------------- the night: ledger, resume, held back

class FakeDays:
    def __init__(self):
        self.days, self.warm, self.search, self.hold = DAYS + ["2026-10-24", "2026-10-25"], [], DAYS, \
            ["2026-10-24", "2026-10-25"]
        self.replay, self.held = DAYS, []


class FakeRp:
    """A replayer without a record: a trial's entries follow its take profit (higher wins more, fewer trades)."""

    def __init__(self):
        self.d, self.runs = FakeDays(), []

    def run(self, specs, days):
        self.runs.append((len(specs), list(days)))
        return {n: entries(days, n=12, win=0.02 * p["tp"] / 0.3, lose=-0.01 * p["sl"] / 0.2) for n, p in specs}

    def scored(self):
        return self.d.search[1:]


def test_the_ledger_only_grows_and_a_night_resumes_where_it_stopped(tmp_path, monkeypatch):
    monkeypatch.setattr(F, "PATHS", 50)
    rp = FakeRp()
    far = 1e12
    mine = F.search(rp, tmp_path, "2026-10-26", 6, far, log=lambda *a: None)
    led = F.read_ledger(tmp_path / "ledger.jsonl")
    assert len(mine) == 6 == len(F.trials_of(led)) and [r["id"] for r in mine] == [F.book_id(i) for i in range(6)]
    assert mine[0]["params"]["tp"] == F.REFERENCE["tp"] and mine[0]["params"]["delay_s"] == 5   # enqueued first
    assert all(r["days"] == DAYS[1:] for r in mine) and rp.runs[0][1] == DAYS
    again = F.search(rp, tmp_path, "2026-10-26", 6, far, log=lambda *a: None)
    assert len(again) == 6 and len(rp.runs) == 1                # nothing left tonight
    more = F.search(rp, tmp_path, "2026-10-26", 9, far, log=lambda *a: None)
    assert len(more) == 9 and len(F.trials_of(F.read_ledger(tmp_path / "ledger.jsonl"))) == 9
    nxt = F.search(rp, tmp_path, "2026-10-27", 2, far, log=lambda *a: None)
    assert [r["id"] for r in nxt] == [F.book_id(9), F.book_id(10)]
    held = F.holdback(rp, tmp_path, "2026-10-26", more, log=lambda *a: None)
    assert len(held) == F.TOP_HOLD and rp.runs[-1] == (F.TOP_HOLD, rp.d.days)
    assert all(r["days"] == rp.d.hold for r in held)
    top = {r["id"] for r in sorted(more, key=lambda r: -r["score"])[:F.TOP_HOLD]}
    assert {r["id"] for r in held} == top
    n = len(rp.runs)
    assert len(F.holdback(rp, tmp_path, "2026-10-26", more, log=lambda *a: None)) == F.TOP_HOLD and len(rp.runs) == n
    led = F.read_ledger(tmp_path / "ledger.jsonl")
    assert len(led) == 11 + F.TOP_HOLD                          # every line kept


def test_a_winner_needs_the_bar_and_the_held_back_days(monkeypatch):
    r = {"id": "F3_00001", "entries": 400, "sharpe": 0.3, "skew": 0.0, "kurt": 3.0, "median": 0.8, "score": 0.8,
         "days": [f"d{i}" for i in range(10)]}
    led = [{"kind": "trial", "sharpe": s, "entries": 50} for s in (0.0, 0.01, -0.01, 0.02)] + [r | {"kind": "trial"}]
    good = {"id": "F3_00001", "median": 0.6, "pnl_sol": 0.05}
    assert [x["id"] for x in F.winners([r], [good], led)] == ["F3_00001"]
    assert F.winners([r], [good | {"pnl_sol": -0.01}], led) == []
    assert F.winners([r], [], led) == []
    assert F.winners([r | {"sharpe": 0.001}], [good], led) == []
    assert F.winners([r | {"days": r["days"][:9]}], [good], led) == []    # nine scored days are not enough


# ---------------------------------------------------------------- the paper books

def state(pnl: dict) -> dict:
    return {"paper_wallets": {k: {"start_l": int(0.55 * SOL), "pnl_l": int(v * SOL), "n": 3} for k, v in pnl.items()}}


def win(i):
    return {"id": F.book_id(i), "params": PLAIN, "score": 0.7, "median": 0.7, "p_lost80": 0.0, "entries": 50,
            "dsr": 0.97, "holdback": {"median": 0.6, "pnl_sol": 0.02, "entries": 10}}


def test_winners_become_books_at_most_five_and_the_weakest_goes_after_two_weeks(tmp_path):
    b = F.manage({"books": []}, [win(i) for i in range(7)], state({F.REF_BOOK: 0.10}), T0, tmp_path)
    act = [x for x in b["books"] if x["state"] == "active"]
    assert len(act) == F.MAX_BOOKS and len(b["waiting"]) == 2 and all(x["ref0"] == pytest.approx(0.10) for x in act)
    assert act[0]["label"] and act[0]["sizing"].startswith("25 %")
    for k in range(1, F.PROBATION_DAYS + 1):                 # book 0 ahead every night, book 1 the worst
        pnl = {F.REF_BOOK: 0.10 + 0.01 * k, F.book_id(0): 0.05 * k, F.book_id(1): -0.02 * k}
        pnl |= {F.book_id(i): 0.0 for i in range(2, 5)}
        b = F.manage(b, [], state(pnl), T0 + k * DAY, tmp_path)
    st = {x["book"]: x for x in b["books"]}
    assert st[F.book_id(1)]["state"] == "retired" and "without beating" in st[F.book_id(1)]["why"]
    assert sum(x["state"] == "retired" for x in b["books"]) == 1   # one a night
    assert st[F.book_id(0)]["state"] == "active" and st[F.book_id(0)].get("proposed_ms")
    prop = (tmp_path / "proposals" / f"{F.book_id(0)}.md").read_text()
    assert F.REF_BOOK in prop and "Paper only" in prop and EM not in prop
    b = F.manage(b, [win(7), win(8)], state({F.REF_BOOK: 0.3}), T0 + 15 * DAY, tmp_path)
    act = [x["book"] for x in b["books"] if x["state"] == "active"]
    assert len(act) == F.MAX_BOOKS and F.book_id(7) in act and F.book_id(8) in act   # room made for both
    assert F.book_id(0) in act                                 # the one ahead stays


def test_the_reports_and_the_card_show_the_books_in_euro(tmp_path, monkeypatch):
    b = F.manage({"books": []}, [win(3)], state({F.REF_BOOK: 0.10}), T0)
    rows = F.status(b, state({F.REF_BOOK: 0.15, F.book_id(3): 0.11}), 90.0)
    assert rows[0]["sol"] == pytest.approx(0.66) and rows[0]["eur"] == pytest.approx(59.4)
    assert rows[0]["ref_sol"] == pytest.approx(0.05)
    md = "\n".join(F.status_md(rows, 90.0))
    assert "59.40" in md and F.book_id(3) in md and EM not in md
    assert "Factory paper books" in R.markdown({"fit": fixed_fit().to_json(), "updated_ms": T0,
                                                "calibration": {"line": "x"}, "factory": rows, "sol_eur": 90.0})
    from lab.pumpfun_rt import card
    from test_i18n import no_english
    en = card.daily_card({}, None, {}, None, T0, "en", None, rows).render("telegram", "en")
    de = card.daily_card({}, None, {}, None, T0, "de", None, rows).render("telegram", "de")
    assert "Factory paper books" in en and "€59.40" in en and "59,40 €" in de
    no_english(de)


def test_the_collector_runs_the_factory_books_and_follows_the_file(tmp_path, monkeypatch):
    from lab.pumpfun_rt import live
    from lab.pumpfun_rt import strategies as S
    monkeypatch.setattr(live, "paper_dir", lambda: tmp_path)
    monkeypatch.setattr(F, "factory_dir", lambda: tmp_path / "factory")
    F.write_books(tmp_path / "factory", F.manage({"books": []}, [win(1)], None, T0))
    sh = live.Shadow(S.DEFAULT_PICK, alerts=False, realistic=True, real=R.Model(fixed_fit(), R.LiveConfig()),
                     now_ms=T0)
    names = {s for p in sh.engine.pipes for s in p.strats}
    assert F.book_id(1) in names and {x[0] for x in R.SMALL} <= names and "P_pool0_wait" in names
    b = F.read_books(tmp_path / "factory")
    b["books"][0]["state"] = "retired"
    b = F.manage(b, [win(2)], None, T0 + DAY)
    F.write_books(tmp_path / "factory", b)
    sh.factory_reload()
    names = {s for p in sh.engine.pipes for s in p.strats}
    assert F.book_id(2) in names and F.book_id(1) not in names
    new = next(p for p in sh.engine.pipes if F.book_id(2) in p.strats)
    assert new.on_close == sh._closed and new.on_skip == sh._skipped
    sh.save()
    assert F.book_id(2) in json.loads((tmp_path / "state.json").read_text())["paper_wallets"]
    few = live.Shadow(S.DEFAULT_PICK, alerts=False, strategies=[P.BY_NAME["P_pool0"]], realistic=True,
                      real=R.Model(fixed_fit(), R.LiveConfig()), now_ms=T0)
    assert not any(s.startswith(F.PREFIX) for p in few.engine.pipes for s in p.strats)


# ---------------------------------------------------------------- the model settings

def table(n=5000, seed=4, signal=1.5):
    rng = np.random.default_rng(seed)
    x = rng.normal(size=n)
    y = (rng.random(n) < 1 / (1 + np.exp(-signal * x))).astype(float)
    t = T0 + np.arange(n) * 60_000.0
    out = {"t": t, "unique_buyers": x, "net_sol": rng.normal(size=n)}
    for lab in M.LABELS:
        out[lab] = np.full(n, np.nan)
    out["win30"] = y
    return out


def test_model_settings_are_adopted_only_when_better_in_the_folds_and_held_back(tmp_path, monkeypatch):
    tab = table()
    hold_ms = int(tab["t"][-400])
    monkeypatch.setattr(R, "reports_dir", lambda: tmp_path)
    bad = {"n_estimators": 2, "learning_rate": 0.001, "num_leaves": 2, "min_child_samples": 1000}
    monkeypatch.setattr(F, "model_space", lambda trial: {**bad, **F.LGB_KEEP})
    pf = tmp_path / "params.json"
    out = F.tune_models(tmp_path, "2026-10-26", hold_ms, 2, 1e12, table=tab, log=lambda *a: None, params_file=pf)
    assert out["win30"]["adopted"] is False and not pf.exists() and out["win30"]["folds"] == M.FOLDS
    assert all("skipped" in out[k] for k in ("win300", "up10"))
    pf.write_text(json.dumps({"win30": {"params": bad}}))     # a poor current setting: the search's beats it
    monkeypatch.setattr(F, "model_space", lambda trial: {"n_estimators": trial.suggest_int("n_estimators", 100, 120),
                                                         "num_leaves": 7, "min_child_samples": 50} | F.LGB_KEEP)
    out = F.tune_models(tmp_path, "2026-10-27", hold_ms, 2, 1e12, table=tab, log=lambda *a: None, params_file=pf)
    v = out["win30"]
    assert v["adopted"] and v["folds_won"] >= F.ADOPT_FOLDS and v["hold_best"] < v["hold_current"]
    got = M.params_for("win30", pf)
    assert 100 <= got["n_estimators"] <= 120 and got["num_leaves"] == 7
    assert M.params_for("win300", pf) == M.PARAMS


def test_the_retrain_trains_with_the_adopted_settings(tmp_path, monkeypatch):
    pf = tmp_path / "params.json"
    monkeypatch.setattr(M, "params_path", lambda: pf)
    tab = table(n=1500)
    assert M.params_for("win30") == M.PARAMS                 # no file: the code's settings
    pf.write_text(json.dumps({"win30": {"params": {"n_estimators": 7}}}))
    m = M.train_all(tab)["win30"]
    assert m.booster is not None and m.booster.num_trees() == 7
    ev = M.evaluate(tab, "win30", 2, ["unique_buyers"])
    assert ev["folds"]
    pf.write_text("not json")
    assert M.params_for("win30") == M.PARAMS


# ---------------------------------------------------------------- the night end to end, the replay, the job

def test_a_night_writes_the_report_with_the_bar_the_books_and_the_models(tmp_path, monkeypatch):
    from lab.pumpfun_rt import live
    monkeypatch.setattr(F, "PATHS", 50)
    asked = []
    monkeypatch.setattr(F, "Days", lambda now_ms, root=None, held=(): asked.append(list(held)) or FakeDays())
    monkeypatch.setattr(F, "Replayer", lambda days, model, root=None, log=print: FakeRp())
    monkeypatch.setattr(R, "_measured", lambda: [])
    monkeypatch.setattr(R, "sol_eur", lambda: 90.0)
    monkeypatch.setattr(live, "paper_dir", lambda: tmp_path)
    s = F.run(now_ms=T0, trials=8, model_trials=0, d=tmp_path / "f", out=tmp_path / "out", log=lambda *a: None)
    assert s["trials_tonight"] == 8 and s["trials_ever"] == 8 and len(s["holdback"]) == F.TOP_HOLD
    md = (tmp_path / "out" / "factory.md").read_text()
    assert "The bar" in md and "Held back" in md and EM not in md and "Paper only" in md
    js = json.loads((tmp_path / "out" / "factory.json").read_text())
    assert js["bar"]["trials"] == 8 and js["hold_days"] == FakeDays().hold and js["bar"]["min_days"] == F.MIN_DAYS
    assert all("lo" in r and "trimmed" in r and "n_eff" in r for r in js["best"]) and "band by day" in md
    assert "EUR" not in md.split("Factory paper books")[0]       # no euro medians
    F.run(now_ms=T0 + DAY, trials=2, model_trials=0, d=tmp_path / "f", out=tmp_path / "out", log=lambda *a: None)
    assert asked == [[], FakeDays().hold]                        # the next night leaves last night's out
    assert (tmp_path / "f" / "books.json").exists()


def test_the_replayer_runs_trials_on_a_synthetic_record(tmp_path, monkeypatch):
    from lab.pumpfun_rt import store
    from test_pumpfun_rt import synth_store
    synth_store(tmp_path, hours=4)
    monkeypatch.setattr(store, "base", lambda: tmp_path)
    rec = store.days(tmp_path)
    days = F.Days(SW.day_start(rec[-1]) + DAY, tmp_path)
    assert days.days == rec and days.hold == [] and days.search == rec == days.replay   # too few days to hold back
    assert F.Days(SW.day_start(rec[-1]), tmp_path).days == rec[:-1]     # today's day is not full yet
    rp = F.Replayer(days, R.Model(fixed_fit(), R.LiveConfig()), tmp_path, log=lambda *a: None)
    specs = [(F.book_id(i), p) for i, p in enumerate(sampled(4, seed=3) + [PLAIN, {**PLAIN, "block": True}])]
    ent = rp.run(specs, days.days)
    assert set(ent) == {n for n, _ in specs} and all(isinstance(v, list) for v in ent.values())


def test_the_job_runs_nightly_under_the_heavy_lock():
    from lab.ops import jobs
    from test_jobs import REPO_TABLE
    j = jobs.load_table(REPO_TABLE).jobs["pumpfun-factory"]
    assert j["schedule"] == "0 1 * * *" and j["command"] == "python -m lab.pumpfun_rt.factory"
    assert j["timeout_s"] <= 2.5 * 3600 and "heavy" in j["locks"] and j["resources"]["cpus"] == 3
    assert j["env"]["PYTHIA_PF_FACTORY_TRIALS"] == "300"
    from pathlib import Path
    assert "optuna" in (Path(__file__).resolve().parents[1] / "requirements.txt").read_text()


def test_the_trial_budget_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv("PYTHIA_PF_FACTORY_TRIALS", "30")
    assert F._env_int("PYTHIA_PF_FACTORY_TRIALS", F.TRIALS) == 30
    monkeypatch.setenv("PYTHIA_PF_FACTORY_TRIALS", "x")
    assert F._env_int("PYTHIA_PF_FACTORY_TRIALS", F.TRIALS) == F.TRIALS


def test_f3_cannot_trade():
    import inspect
    src = inspect.getsource(F).lower()
    for word in ("sendtransaction", "keypair", "private_key", "solders", "liveexecutor"):
        assert word not in src


def test_the_models_report_says_which_labels_have_the_factorys_settings(tmp_path, monkeypatch):
    from lab.pumpfun_rt import labels_r2 as L2
    from lab.pumpfun_rt import retrain as RT
    pf = tmp_path / "params.json"
    monkeypatch.setattr(M, "params_path", lambda: pf)
    monkeypatch.setitem(M.PARAMS, "n_estimators", 10)
    rng = np.random.default_rng(3)
    n = 1_500
    tab = {"t": T0 + np.arange(n) * 60_000.0}
    for f in M.FEATURES:
        tab[f] = rng.normal(size=n)
    for k in list(M.LABELS) + list(L2.REAL_ROW.values()):
        tab[k] = (rng.random(n) < 0.3).astype(float)
    res = RT.run(tab, log=lambda *a: None)
    assert "the code's for every label" in RT.report_md(RT.summary(res, T0), res["importance"])
    pf.write_text(json.dumps({"up30": {"params": {"n_estimators": 12}}}))
    md = RT.report_md(RT.summary(res, T0), res["importance"])
    assert "the factory's (F3, pumpfun_rt/factory/params.json) for up30" in md and EM not in md
