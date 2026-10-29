"""A4: the ladder promotes on its own from step 2 to step 4 (results/ladder_promotion_a4_prereg.md), on fake data: a
step-2 pass creates exactly one shadow, a shadow under its length never reaches the lockbox, the lockbox runs once and a
second run is refused, a fail (and a claim without a result) is final, live_ready.json only ever holds step-4 passes;
the "before" check, each kind's rows, the missing tools, the ladder's, weekly page's and progress page's sections, the
job in the table.

Run from research/lab:  python -m pytest tests/test_promote.py
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from lab import metrics
from lab.ops import jobs, ladder, progress, promote, weekly
from test_ladder import NOW, SPEC_ID, added, env, genome, write  # noqa: F401 - env is a fixture

REPO_TABLE = Path(__file__).resolve().parents[2] / "ops" / "jobs.yaml"
DAY = 86_400_000
GID = f"weekly:{SPEC_ID}"
G = {"universe": "top10", "rebalance": {"every": 7, "band": 0.1}}   # a genome as the holdout row keeps it


def day(i: int) -> str:
    """The i-th day after NOW's (2026-11-20)."""
    return (datetime.fromtimestamp(NOW / 1000, timezone.utc) + timedelta(days=i)).strftime("%Y-%m-%d")


def stepper(n: int = 40, trades: int = 1):
    return lambda root, e, cache: [(day(i), 0.001, trades) for i in range(1, n + 1)]


class Looker:
    """A fake look: counts its calls, passes or fails as told."""

    def __init__(self, ok: bool = True, boom: bool = False):
        self.calls, self.ok, self.boom = 0, ok, boom

    def tools(self) -> dict:
        return {"weekly": (lambda root, e, cache: None, self.look, None)}

    def look(self, root, e, cache, now):
        self.calls += 1
        if self.boom:
            raise RuntimeError("panel gone")
        return {"result": {"dsr": 0.7 if self.ok else 0.1},
                "conditions": [ladder.cond("look", True, "look 1", "factory/lockbox.jsonl"),
                               ladder.cond("bench", True, "against BTC and ETH held"),
                               ladder.cond("look_pass", self.ok, "DSR 0.70" if self.ok else "DSR 0.10 (needs 0.5)")]}


@pytest.fixture()
def quiet(monkeypatch):
    for k in ("PYTHIA_REPORTS", "PYTHIA_ALERT_WEBHOOK", "PYTHIA_TELEGRAM_BOT_TOKEN", "PYTHIA_TELEGRAM_CHAT_ID",
              "PYTHIA_ALERT_VIA", "PYTHIA_DISCORD_BOT_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("PYTHIA_QUIET_HOURS", "off")


def go(env, at: int = 0, steps=None, looker: Looker | None = None, sent: list | None = None) -> dict:
    """One daily run at day `at`, the real ladder on the test's data."""
    data, results = env
    now = NOW + at * DAY
    return promote.run(data, now, build=lambda: ladder.build(data, now, results=results, added=added()),
                       steppers={"weekly": steps or stepper()}, lookers=(looker or Looker()).tools(),
                       poster=lambda text: ((sent if sent is not None else []).append(text) or True, None),
                       publish=False, log=lambda s: None)


def row(env, at: int = 0) -> dict:
    data, results = env
    return {r["id"]: r for r in ladder.build(data, NOW + at * DAY, results=results, added=added())["rows"]}[GID]


def trials() -> list[str]:
    return [r["id"] for r in metrics.read_registry() if r["id"].startswith("promote:")]


# ---------------------------------------------------------------- 2 -> 3

def test_a_step_2_pass_creates_exactly_one_shadow(env, quiet):
    data, _ = env
    genome(data, 2, genome=G)
    assert row(env)["step"] == 2
    out = go(env)
    assert out["new"] == [GID]
    sh = promote.read_shadows(data)
    assert list(sh) == [GID] and sh[GID]["status"] == "active" and sh[GID]["start_day"] == day(0)
    assert sh[GID]["key"] == SPEC_ID and sh[GID]["behaviour"] == "beh1" and sh[GID]["family"] == "factory"
    for at in (1, 2, 3):
        assert go(env, at)["new"] == []
    assert list(promote.read_shadows(data)) == [GID]
    assert [t for t in trials() if ":dev:" not in t] == [f"promote:shadow:{GID}"]   # one trial, registered once


def test_step_1_gets_no_shadow_and_a_fall_back_keeps_the_one_it_has(env, quiet):
    data, _ = env
    genome(data, 2, genome=G, pbo=0.5)                                       # PBO fails: step 1
    assert go(env)["new"] == [] and promote.read_shadows(data) == {}
    genome(data, 2, genome=G)
    go(env, 1)
    genome(data, 2, genome=G, pbo=0.5)
    go(env, 2)
    genome(data, 2, genome=G)
    assert go(env, 3)["new"] == [] and promote.read_shadows(data)[GID]["start_day"] == day(1)


# ---------------------------------------------------------------- 3 -> 4

def test_a_shadow_under_its_length_never_reaches_the_lockbox(env, quiet):
    data, _ = env
    genome(data, 2, genome=G)
    lk = Looker()
    go(env, looker=lk)
    go(env, 30, steps=stepper(29), looker=lk)                      # 29 days, 29 trades
    go(env, 40, steps=stepper(40, trades=0), looker=lk)            # 40 days, still 29 trades
    assert lk.calls == 0 and not promote.looks_path(data).exists()
    r = row(env, 40)
    assert r["step"] == 2 and r["missing"] == ["trades"] and r["promotion"] == "active"
    assert "29 of 30" in r["next"]


def test_the_lockbox_runs_once_and_a_second_run_is_refused(env, quiet):
    data, _ = env
    genome(data, 2, genome=G)
    lk, sent = Looker(), []
    go(env, looker=lk)
    out = go(env, 35, looker=lk, sent=sent)
    assert out["looks"] == [(GID, "passed")] and lk.calls == 1
    lines = [json.loads(x) for x in promote.looks_path(data).read_text().splitlines()]
    assert [("claimed_ms" in x, "pass" in x) for x in lines] == [(True, False), (False, True)]   # claim, then result
    assert f"promote:lockbox:{GID}" in trials()
    for at in (36, 37):
        assert go(env, at, looker=lk)["looks"] == []
    e = promote.read_shadows(data)[GID]
    assert promote.look_once(data, e, lk.tools(), {}, NOW + 38 * DAY) == "refused: looked at before"
    assert lk.calls == 1 and len(promote.looks_path(data).read_text().splitlines()) == 2
    r = row(env, 37)
    assert r["step"] == 4 and r["missing"] == ["record"] and r["promotion"] == "passed"
    rd = json.loads(promote.ready_path(data).read_text())
    assert [(c["id"], c["share_eur"], c["venue"], c["instrument"]) for c in rd["candidates"]] == \
        [(GID, 50.0, "not chosen", "crypto spot")]
    assert f"promotions/shadow/{promote.slug(GID)}.csv" in rd["candidates"][0]["evidence"]
    assert len(sent) == 1 and "Lockbox bestanden" in sent[0] and "50.00 EUR" in sent[0]   # once, when it entered


def test_a_fail_is_final(env, quiet):
    data, _ = env
    genome(data, 2, genome=G)
    lk = Looker(ok=False)
    go(env, looker=lk)
    assert go(env, 35, looker=lk)["looks"] == [(GID, "failed")]
    lk.ok = True
    for at in (36, 60):
        assert go(env, at, looker=lk)["looks"] == []
    assert lk.calls == 1 and promote.read_shadows(data)[GID]["status"] == "failed"
    assert json.loads(promote.ready_path(data).read_text())["candidates"] == []
    r = row(env, 60)
    assert r["step"] == 3 and r["missing"] == ["look_pass"]


def test_a_look_that_dies_or_a_claim_without_a_result_is_a_final_fail(env, quiet):
    data, _ = env
    genome(data, 2, genome=G)
    lk = Looker(boom=True)
    go(env, looker=lk)
    assert go(env, 35, looker=lk)["looks"] == [(GID, "failed")]
    assert "panel gone" in promote.read_shadows(data)[GID]["look"]
    promote.looks_path(data).write_text(json.dumps({"id": GID, "claimed_ms": NOW}) + "\n")   # the run died
    lk.boom = False
    assert go(env, 36, looker=lk)["looks"] == [] and lk.calls == 1
    r = row(env, 36)
    assert r["step"] == 3 and r["missing"] == ["look"] and "no result written: final" in r["next"]


def test_live_ready_only_ever_holds_step_4_passes(env, quiet):
    data, _ = env
    rows = {"pumpfun:aaa": 2, "pumpfun:bbb": 2, "pumpfun:ccc": 1}
    now = lambda at: NOW + at * DAY  # noqa: E731

    def build_at(at):
        return lambda: {"rows": [{"id": k, "name": k, "kind": "rule", "study": "PF", "step": v + (at >= 30 and v >= 2)}
                                 for k, v in rows.items()]}
    ok = {"pumpfun:aaa": True, "pumpfun:bbb": False}
    look = lambda root, e, cache, n: {"result": {}, "conditions": [ladder.cond("look_pass", ok[e["id"]], "")]}  # noqa: E731
    tools = {"pumpfun": (lambda root, e, cache: None, look, None)}
    for at in (0, 35, 36):
        promote.run(data, now(at), build=build_at(at), steppers={"pumpfun": stepper()}, lookers=tools, publish=False,
                    poster=lambda text: (True, None), log=lambda s: None)
        rd = json.loads(promote.ready_path(data).read_text())
        assert {c["id"] for c in rd["candidates"]} <= {"pumpfun:aaa"}
    assert [c["id"] for c in rd["candidates"]] == ["pumpfun:aaa"] and rd["budget_eur"] == 50.0
    assert set(promote.read_shadows(data)) == {"pumpfun:aaa", "pumpfun:bbb"}    # ccc never stood on step 2


def test_the_job_itself_refuses_a_short_shadow_whatever_the_ladder_says(env, quiet):
    data, _ = env
    lk = Looker()
    b = lambda: {"rows": [{"id": "pumpfun:r1", "name": "r1", "kind": "rule", "step": 3}]}  # noqa: E731
    for at, n in ((0, 0), (31, 30)):
        promote.run(data, NOW + at * DAY, build=b, steppers={"pumpfun": stepper(n, trades=0)}, lookers={"pumpfun": lk.tools()["weekly"]},
                    publish=False, log=lambda s: None)
    assert lk.calls == 0 and "0 of 30 trades" in promote.read_shadows(data)["pumpfun:r1"]["look"]


def test_equal_shares_round_down():
    sh = {f"pumpfun:r{i}": {"name": f"r{i}", "study": "PF", "kind": "rule"} for i in range(3)}
    looks = {k: {"claimed_ms": 1, "done": {"pass": True, "date": "2026-12-01"}} for k in sh}
    rd = promote.live_ready(Path("."), sh, looks, NOW)
    assert [c["share_eur"] for c in rd["candidates"]] == [16.66] * 3
    assert {c["venue"] for c in rd["candidates"]} == {"pump.fun"}


# ---------------------------------------------------------------- the shadow's file

def test_rows_are_appended_after_the_start_and_before_today_only_and_a_rewrite_fails(env, quiet):
    data, _ = env
    genome(data, 2, genome=G)
    go(env, steps=lambda root, e, cache: [(day(-1), 0.5, 1), (day(0), 0.5, 1)])
    e = promote.read_shadows(data)[GID]
    assert promote.journal(data, GID) == [] and promote.record(data, GID, e)["before"]
    go(env, 3, steps=lambda root, e, cache: [(day(i), 0.01, 1) for i in range(-1, 5)])
    rows = promote.journal(data, GID)
    assert [r["date"] for r in rows] == [day(1), day(2)] and all(int(r["logged_ms"]) == NOW + 3 * DAY for r in rows)
    e = promote.read_shadows(data)[GID]
    assert promote.record(data, GID, e)["before"] and e["rows"] == 2
    p = data / promote.shadow_rel(GID)
    p.write_text(p.read_text().replace("0.0100000", "0.0500000", 1))
    rec = promote.record(data, GID, e)
    assert not rec["before"] and "rewritten" in rec["why"]
    assert row(env, 3)["missing"][-1] == "logged"


def test_a_row_logged_before_its_date_ended_fails(tmp_path):
    e = {"start_day": "2026-11-20", "start_ms": NOW, "rows": 0, "digest": promote.digest([])}
    write(tmp_path, promote.shadow_rel(GID), "date,ret,trades,logged_ms\n2026-11-21,0.01,1," f"{NOW + DAY}\n")
    e.update(rows=1, digest=promote.digest(promote._lines(tmp_path, GID)))
    rec = promote.record(tmp_path, GID, e)
    assert not rec["before"] and "before its date ended" in rec["why"]


def test_a_paper_books_rows_from_its_journal(tmp_path):
    write(tmp_path, "paper/tsmom/journal.csv", "date,equity,turnover\n2026-11-20,100,0.5\n2026-11-21,101,0.0\n"
          "2026-11-22,99,0.2\n2026-11-22,101,0.2\n")
    got = promote.step_book(tmp_path, {"name": "tsmom"}, {})
    assert [(d, round(r, 4), t) for d, r, t in got] == [("2026-11-21", 0.01, 0), ("2026-11-22", 0.0, 1)]


def test_a_weekly_genome_from_the_factorys_shadow_and_an_f2_wallet(tmp_path):
    write(tmp_path, f"factory/shadow/{SPEC_ID}.csv", "date,net_ret,turnover\n2026-11-21,0.002,0.3\n2026-11-22,-0.001,0\n")
    assert promote.step_genome(tmp_path, {"key": SPEC_ID}, {}) == [("2026-11-21", 0.002, 1), ("2026-11-22", -0.001, 0)]
    write(tmp_path, "factory/small/shadow/k2.csv", "date,equity_eur,orders\n2026-11-21,40,2\n2026-11-22,42,2\n"
          "2026-11-23,42,3\n")
    got = promote.step_f2(tmp_path, {"key": "k2"}, {})
    assert [(d, round(r, 4), t) for d, r, t in got] == [("2026-11-22", 0.05, 0), ("2026-11-23", 0.0, 1)]


# ---------------------------------------------------------------- the missing tools

def test_kinds_that_cannot_run_are_missing_tools(tmp_path):
    assert "forecast" in promote.shadow_missing(tmp_path, {"id": "G2:m1", "key": "m1"})
    assert "F2 runs no shadow wallet" in promote.shadow_missing(tmp_path, {"id": "F2:k2", "key": "k2"})
    write(tmp_path, "factory/small/shadow/k2.csv", "date,equity_eur,orders\n")
    assert promote.shadow_missing(tmp_path, {"id": "F2:k2", "key": "k2"}) is None
    assert promote.shadow_missing(tmp_path, {"id": "book:tsmom"}) is None
    assert "UCITS" in promote.look_missing("F2:k2") and "backtest of a paper book" in promote.look_missing("book:tsmom")
    assert promote.look_missing(GID) is None and promote.look_missing("pumpfun:P_pool0") is None


def test_a_missing_tool_shows_on_the_ladder_and_starts_nothing(tmp_path, quiet, monkeypatch):
    monkeypatch.setenv("PYTHIA_DATA", str(tmp_path))
    b = lambda: {"rows": [{"id": "G2:m1", "name": "G2 m1", "kind": "model", "study": "G2", "step": 2}]}  # noqa: E731
    promote.run(tmp_path, NOW, build=b, lookers={}, publish=False, log=lambda s: None)
    e = promote.read_shadows(tmp_path)["G2:m1"]
    assert e["status"] == "missing_tool" and not (tmp_path / promote.shadow_rel("G2:m1")).exists()
    c = ladder.promoted_shadow({"id": "G2:m1"}, e, {"promo": promote.state(tmp_path)})
    assert [x["id"] for x in c] == ["tool"] and "forecast" in c[0]["value"]
    assert ladder.COND["tool"][1] == "Werkzeug fehlt"
    c = ladder.promoted_lockbox({"id": "book:tsmom"}, {"status": "active"}, {"promo": promote.state(tmp_path)})
    assert c[0]["id"] == "tool" and c[0]["ok"] is False


def test_a_book_with_its_shadow_done_waits_for_its_lockbox_tool(tmp_path, quiet, monkeypatch):
    monkeypatch.setenv("PYTHIA_DATA", str(tmp_path))
    b = lambda: {"rows": [{"id": "book:tsmom", "name": "tsmom", "kind": "book", "study": "hand", "step": 3}]}  # noqa: E731
    for at in (0, 40):
        promote.run(tmp_path, NOW + at * DAY, build=b, steppers={"book": stepper()}, publish=False, log=lambda s: None)
    e = promote.read_shadows(tmp_path)["book:tsmom"]
    assert e["status"] == "active" and e["look"].startswith("missing tool:") and not promote.looks_path(tmp_path).exists()


# ---------------------------------------------------------------- where it shows

def test_the_ladder_report_weekly_page_and_progress_show_the_promotions(env, quiet):
    data, results = env
    genome(data, 2, genome=G)
    go(env)
    go(env, 35)
    d = ladder.build(data, NOW + 35 * DAY, results=results, added=added())
    p = d["promotions"]
    assert p["counts"]["passed"] == 1 and p["live_ready"][0]["id"] == GID
    md = ladder.markdown(d)
    assert "Promotions (A4" in md and "passed on" in md and "live_ready.json: weekly" in md and "\u2014" not in md
    write(data, "reports/ladder/latest.json", d)
    page = weekly.build(data, NOW + 35 * DAY)
    line = next(x for x in page["lines"] if x.startswith("Beförderungen"))
    assert "Lockbox 1 bestanden" in line and f"weekly {SPEC_ID}" in line and "\u2014" not in line
    pr = progress.build(data, NOW + 35 * DAY)["ladder"]["promotions"]
    assert pr["shadows"][0]["status"] == "passed" and pr["shadows"][0]["days"] == 34
    assert pr["live_ready"][0]["share_eur"] == 50.0


def test_the_look_made_while_a4_was_written_is_logged_once_and_counted(env, quiet):
    data, _ = env
    genome(data, 2, genome=G)
    for at in (0, 1):
        go(env, at)
    looks = [json.loads(x) for x in (data / "factory" / "lockbox.jsonl").read_text().splitlines()]
    assert [(x["look"], x["key"], x["factory"]) for x in looks] == [(1, "38c0885daa3c", "promote-dev")]
    assert "promote:lockbox:dev:38c0885daa3c" in trials()


def test_the_job_is_in_the_table():
    j = jobs.load_table(REPO_TABLE).jobs["promote"]
    assert j["command"] == "python -m lab.ops.promote" and j["kind"] == "lab" and j["enabled"]
    assert j["schedule"] == "50 8 * * *" and "heavy" in j["locks"] and j["timeout_s"] <= 3600
    assert jobs.plain_lab_job(j), "no env file, network or volume"
