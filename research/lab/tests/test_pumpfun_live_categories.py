"""The live name categories (livecat.py; the owner, 2026-10-23: the live bot bought MAJOR BIDEN, Apple, ChatGPT,
IShowSpeed, DuckDuckGo, GTA6, TRUMP, MrBeast and SpaceX AI that day): the classifier of the stream's new coins every
30 s (the daily job's prompt, chunks and checks, the same cats.jsonl with avail_ms, the daily job skipping its names),
the entry rule of the live book and its paper twin (a blocked category is a skip with its reason, a coin without one
is asked alone at the buy, "category unknown" when that fails), the owner's category: lines, the prompt's guidance on
today's names (a fixture of the answer, no network) and the evaluation's offline rule.

Run from research/lab:  python -m pytest tests/test_pumpfun_live_categories.py
"""

from __future__ import annotations

import asyncio
import json
import time
from concurrent.futures import Future
from types import SimpleNamespace

import pytest

from lab.pumpfun_rt import blocklist as BL
from lab.pumpfun_rt import categorize as CAT
from lab.pumpfun_rt import collector as COL
from lab.pumpfun_rt import live_exec as LX
from lab.pumpfun_rt import live_service as LS
from lab.pumpfun_rt import livecat as LC
from lab.pumpfun_rt import pipeline as P
from test_pumpfun_live_match import CREATE, MIGRATE, POOL_BUY, PUBLIC, RULE, folders, service, shown  # noqa: F401
from test_pumpfun_rt import MINT, T0, key, note

KEY = CAT.name_key("Test", "TST")                                      # create_vals: name Test, symbol TST

# The names the live bot bought on 2026-10-23 and the answer the prompt's guidance asks for (a fixture of the
# endpoint's answer, not a recorded call: the tests have no key and no network).
TODAY = [("MAJOR BIDEN", "BIDEN", "celebrity"), ("Apple", "APPLE", "copycat"), ("ChatGPT", "CHATGPT", "copycat"),
         ("IShowSpeed", "SPEED", "celebrity"), ("DuckDuckGo", "DDG", "copycat"), ("GTA6", "GTA6", "copycat"),
         ("TRUMP", "TRUMP", "celebrity"), ("MrBeast", "BEAST", "celebrity"), ("SpaceX AI", "SPACEXAI", "copycat")]


@pytest.fixture(autouse=True)
def cats_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(CAT, "cat_dir", lambda: tmp_path / "categories")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-only")
    return tmp_path / "categories"


class FakeAi:
    """The engine's endpoint: every id gets `code` (or the code of its name in `by_name`)."""

    def __init__(self, code="generic", status=200, cost=0.0001, by_name=None, sleep=0.0):
        self.calls, self.code, self.status, self.cost, self.by_name, self.sleep = [], code, status, cost, by_name, sleep

    def __call__(self, url, body, tok, timeout):
        self.calls.append(dict(body, timeout=timeout))
        if self.sleep:
            time.sleep(self.sleep)
        if self.status != 200:
            return self.status, {"error": "no"}
        items = []
        for line in body["user"].split("TOKENS (id|name|ticker):", 1)[1].splitlines():
            if line[:1].isdigit():
                i, name, _ = line.split("|", 2)
                items.append({"i": int(i), "c": (self.by_name or {}).get(name, self.code)})
        return 200, {"json": {"items": items}, "costUsd": self.cost}


def now_submit(f, *a):
    """The single call in this thread (the tests' clock): a done future."""
    fut = Future()
    try:
        fut.set_result(f(*a))
    except Exception as e:                                             # noqa: BLE001
        fut.set_exception(e)
    return fut


def coin(name="Test", symbol="TST", mint=None):
    return SimpleNamespace(mint=mint or key(70), name=name, symbol=symbol, creator=None, devs=set())


def lines(d) -> list[dict]:
    p = d / "cats.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


def quiet(*a, **k):
    pass


def run_coin(col):
    col.handle(note("c", 100, CREATE), T0, PUBLIC)
    col.handle(note("m", 101, MIGRATE), T0 + 400, PUBLIC)
    col.handle(note("b", 102, POOL_BUY), T0 + 800, PUBLIC)


# ---------------------------------------------------------------- the owner's category: lines

def test_category_lines_default_to_celebrity_copycat_and_scam(tmp_path, capsys):
    f = tmp_path / "b.txt"
    f.write_text("symbol:SHEKEL\n", encoding="utf-8")
    w = BL.BlockWatch(paths=[f])
    assert w.list.blocked_categories() == {"celebrity", "copycat", "scam"}
    f.write_text("symbol:SHEKEL\ncategory: Scam\ncategory:animal\ncategory:rocket\n", encoding="utf-8")
    w = BL.BlockWatch(paths=[f])
    assert w.list.blocked_categories() == {"scam", "animal"}
    assert w(RULE, coin("Moon Dog", "DOG")) is None                     # why() leaves categories to the gate
    out = capsys.readouterr().out
    assert "'category:rocket'" in out and "categories animal, scam" in out
    assert BL.parse_line("category:copycat") == ("category", "copycat") and BL.parse_line("category:") is False


# ---------------------------------------------------------------- the prompt's guidance, today's names

def test_the_guidance_puts_brands_in_copycat_and_real_people_in_celebrity():
    s = CAT.SYSTEM
    for w in ("famous brand", "app", "game", "AI product", "another cryptocurrency", "Apple", "ChatGPT", "GTA6",
              "DuckDuckGo"):
        assert w in s, w
    for w in ("real person", "politicians", "streamers", "founders", "athletes", "musicians", "IShowSpeed", "Biden"):
        assert w in s, w
    assert set(CAT.CATS) == {"copycat", "celebrity", "ai", "animal", "generic", "scam"}   # the code list stays


def test_todays_names_are_classified_and_skipped_with_their_category(tmp_path):
    ai = FakeAi(by_name={n: c for n, _, c in TODAY})
    got, cost = LC.ask([(n, s) for n, s, _ in TODAY], ["Apple (APPLE)"], "2026-10-23", ai)
    assert {TODAY[i][0]: c for i, c in got.items()} == {n: c for n, _, c in TODAY} and cost == ai.cost
    body = ai.calls[0]
    assert body["model"] == "claude-haiku-5-5" and body["job"] == LC.JOB and not body["batch"]
    assert body["system"] == CAT.SYSTEM and body["schema"] == CAT.SCHEMA
    assert "0|MAJOR BIDEN|BIDEN" in body["user"] and "- Apple (APPLE)" in body["user"]
    gate = LC.CategoryGate(CAT.CategoryIndex(), poster=ai, d=tmp_path, submit=now_submit, log=quiet)
    for n, s, c in TODAY:
        assert gate(RULE, coin(n, s), True) == f"category {c}", n


# ---------------------------------------------------------------- the classifier

def test_the_classifier_asks_each_new_name_once_and_writes_the_cache_point_in_time(cats_folder):
    clock = [T0]
    ai = FakeAi(code="scam")
    cls = LC.LiveClassifier(CAT.CategoryIndex(), poster=ai, clock=lambda: clock[0], log=quiet)
    cls.observe("creates", {"mint": "m1", "name": "Rug Coin", "symbol": "RUG", "quote": None, "mayhem": False})
    cls.observe("creates", {"mint": "m2", "name": "rug coin", "symbol": "$rug", "quote": None, "mayhem": False})
    cls.observe("creates", {"mint": "m3", "name": "May", "symbol": "MAY", "quote": None, "mayhem": True})
    cls.observe("creates", {"mint": "m4", "name": "Usd", "symbol": "USD", "quote": key(5), "mayhem": False})
    for _ in range(3):
        cls.observe("trades", {"mint": "m1", "t": T0})
    batch, trending = cls.take()
    assert set(batch) == {"m1", "m2"} and trending == ["Rug Coin (RUG)"]
    assert cls.take() is None                                          # a run is going
    clock[0] = T0 + 5_000
    res = cls.classify(batch, trending)
    assert res["asked"] == 1 and res["classified"] == 1 and len(ai.calls) == 1 and not ai.calls[0]["batch"]
    assert "0|Rug Coin|RUG" in ai.calls[0]["user"] and "DAY: " in ai.calls[0]["user"]
    rows = lines(cats_folder)
    assert {r["mint"] for r in rows} == {"m1", "m2"} and {r["cat"] for r in rows} == {"scam"}
    assert {r["avail_ms"] for r in rows} == {T0 + 5_000} and {r["key"] for r in rows} == {"rugcoin|rug"}
    # a later coin of the same name: its line at once, the name's first answer time, no call
    cls.observe("creates", {"mint": "m5", "name": "RUG COIN", "symbol": "rug", "quote": None, "mayhem": False})
    clock[0] = T0 + 40_000
    res = cls.classify(*cls.take())
    assert res["reused"] == 1 and res["asked"] == 0 and len(ai.calls) == 1
    assert lines(cats_folder)[-1] == {"mint": "m5", "key": "rugcoin|rug", "cat": "scam", "day": LC.utc_day(T0 + 40_000),
                                      "avail_ms": T0 + 5_000}
    ix = CAT.CategoryIndex.load()
    assert ix.at("Rug Coin", "RUG", T0 + 5_000) == "scam" and ix.at("Rug Coin", "RUG", T0 + 4_999) is None
    assert cls.status()["classified"] == 1 and cls.status()["cost_today_usd"] == pytest.approx(ai.cost)


def test_a_failed_run_is_asked_again_and_the_day_cap_stops_the_calls(cats_folder):
    ai = FakeAi(status=502)
    log = []
    cls = LC.LiveClassifier(CAT.CategoryIndex(), poster=ai, log=lambda *a, **k: log.append(a[0]))
    cls.observe("creates", {"mint": "m1", "name": "A", "symbol": "A", "quote": None})
    res = cls.classify(*cls.take())
    assert res["classified"] == 0 and res["errors"][0].startswith("failed") and set(cls.retry) == {"m1"}
    assert "a run failed" in log[0] and not lines(cats_folder)
    ai.status = 200
    res = cls.classify(*cls.take())
    assert res["classified"] == 1 and not cls.retry and len(ai.calls) == 2
    cls.spend.usd = cls.spend.cap                                      # the day's cap: nothing more is asked
    cls.observe("creates", {"mint": "m2", "name": "B", "symbol": "B", "quote": None})
    res = cls.classify(*cls.take())
    assert res["asked"] == 0 and len(ai.calls) == 2 and "day cap" in res["errors"][0]


def test_the_daily_job_skips_the_names_the_live_classifier_did(tmp_path, cats_folder):
    from test_pumpfun_pipeline import write_day
    day = write_day(tmp_path, [("Doge Cat", "DCAT"), ("Robot AI", "RAI")])
    from lab.pumpfun_rt import store
    rows = store.read("creates", [day], tmp_path).iter_rows(named=True)
    cls = LC.LiveClassifier(CAT.CategoryIndex(), poster=FakeAi(code="animal"), d=tmp_path / "categories", log=quiet)
    for r in rows:
        cls.observe("creates", r)
    assert cls.classify(*cls.take())["classified"] == 2
    ai = FakeAi()
    res = CAT.run(day, now_ms=T0 + 86_400_000, root=tmp_path, poster=ai, log=quiet)
    assert res["keys"] == 0 and res["reused"] == 2 and not ai.calls


def test_the_index_reads_only_what_was_appended_and_waits_for_a_half_line(cats_folder):
    cats_folder.mkdir(parents=True)
    p = cats_folder / "cats.jsonl"
    p.write_text(json.dumps({"mint": "a", "key": "a|a", "cat": "scam", "day": "d", "avail_ms": T0}) + "\n")
    ix = CAT.CategoryIndex.load(mints=False)
    assert ix.keys == {"a|a": (T0, "scam")}
    with p.open("a") as fh:
        fh.write(json.dumps({"mint": "b", "key": "b|b", "cat": "ai", "day": "d", "avail_ms": T0}) + "\n")
        fh.write('{"mint": "c", "key": "c|c"')
    assert ix.tail() == 1 and "b|b" in ix.keys and "c|c" not in ix.keys
    with p.open("a") as fh:
        fh.write(', "cat": "animal", "day": "d", "avail_ms": 1}\n')
    assert ix.tail() == 1 and ix.keys["c|c"] == (1, "animal") and ix.tail() == 0


# ---------------------------------------------------------------- the entry rule

def test_a_blocked_category_is_a_skip_with_its_reason_a_log_line_and_a_row(tmp_path, capsys):
    svc, col, pipe = service()
    ix = CAT.CategoryIndex()
    ix.add("", KEY, "celebrity", T0)
    ai = FakeAi()
    pipe.category = LC.CategoryGate(ix, block=pipe.blocked, poster=ai, d=tmp_path, submit=now_submit)
    run_coin(col)
    svc.tick(T0 + 10_000)
    assert not pipe.pos and pipe.eng.counts["pipe_signals"] == 0 and not ai.calls
    assert shown(pipe) == {"category celebrity": 1}
    assert capsys.readouterr().out.count(f"live: skipped {MINT[:8]}: category celebrity") == 1
    rec = [json.loads(x) for x in (LX.data_dir() / "skipped.jsonl").read_text().splitlines()]
    assert [(r["mint"], r["rule"], r["why"]) for r in rec] == [(MINT, RULE, "category celebrity")]
    assert not (LX.data_dir() / "orders.jsonl").exists()

    for cat in ("copycat", "scam"):
        svc, col, pipe = service()
        ix = CAT.CategoryIndex()
        ix.add("", KEY, cat, T0)
        pipe.category = LC.CategoryGate(ix, poster=ai, d=tmp_path, submit=now_submit)
        run_coin(col)
        svc.tick(T0 + 10_000)
        assert not pipe.pos and shown(pipe) == {f"category {cat}": 1}

    svc, col, pipe = service()                                         # not blocked: bought
    ix = CAT.CategoryIndex()
    ix.add("", KEY, "animal", T0)
    pipe.category = LC.CategoryGate(ix, poster=ai, d=tmp_path, submit=now_submit)
    run_coin(col)
    svc.tick(T0 + 10_000)
    assert pipe.eng.counts["pipe_signals"] == 1 and len(pipe.pos) == 1 and not ai.calls


def test_the_owners_lines_replace_the_default_categories(tmp_path):
    f = tmp_path / "b.txt"
    f.write_text("category:scam\n", encoding="utf-8")
    svc, col, pipe = service()
    pipe.blocked = BL.BlockWatch(paths=[f])
    ix = CAT.CategoryIndex()
    ix.add("", KEY, "celebrity", T0)
    pipe.category = LC.CategoryGate(ix, block=pipe.blocked, submit=now_submit, log=quiet)
    run_coin(col)
    svc.tick(T0 + 10_000)
    assert len(pipe.pos) == 1                                          # celebrity is not on the owner's list
    assert pipe.category.status()["blocked"] == ["scam"] and not pipe.category.status()["default"]


def test_a_coin_without_a_category_is_asked_alone_at_the_buy(tmp_path, capsys):
    svc, col, pipe = service()
    ai = FakeAi(code="celebrity")
    pipe.category = LC.CategoryGate(CAT.CategoryIndex(), poster=ai, d=tmp_path, submit=now_submit)
    run_coin(col)
    svc.tick(T0 + 10_000)
    assert len(ai.calls) == 1 and ai.calls[0]["timeout"] == LC.ONE_TIMEOUT_S and "0|Test|TST" in ai.calls[0]["user"]
    assert not pipe.pos and shown(pipe) == {"category celebrity": 1}
    assert lines(tmp_path)[0]["key"] == KEY and lines(tmp_path)[0]["cat"] == "celebrity"   # kept for the next coin
    assert "'TST' asked alone: celebrity" in capsys.readouterr().out

    svc, col, pipe = service()                                         # an answer that is not blocked: bought
    pipe.category = LC.CategoryGate(CAT.CategoryIndex(), poster=FakeAi(code="generic"), d=tmp_path / "x",
                                     submit=now_submit, log=quiet)
    run_coin(col)
    svc.tick(T0 + 10_000)
    assert len(pipe.pos) == 1


def test_no_answer_is_a_skip_category_unknown(tmp_path):
    for ai in (FakeAi(status=502), FakeAi(status=402)):
        svc, col, pipe = service()
        pipe.category = LC.CategoryGate(CAT.CategoryIndex(), poster=ai, d=tmp_path, submit=now_submit, log=quiet)
        run_coin(col)
        svc.tick(T0 + 10_000)
        assert not pipe.pos and shown(pipe) == {"category unknown": 1} and len(ai.calls) == 1

    # too slow: the loop waits timeout_s at most, then skips; the late answer is kept for the next coin
    svc, col, pipe = service()
    ai = FakeAi(code="generic", sleep=0.4)
    gate = LC.CategoryGate(CAT.CategoryIndex(), poster=ai, d=tmp_path / "slow", timeout_s=0.05, log=quiet)
    pipe.category = gate
    t = time.monotonic()
    run_coin(col)
    svc.tick(T0 + 10_000)
    assert time.monotonic() - t < 0.35
    assert not pipe.pos and shown(pipe) == {"category unknown": 1} and gate.one_st["timeout"] == 1
    time.sleep(0.6)
    assert gate.mem[KEY][1] == "generic" and lines(tmp_path / "slow")[0]["cat"] == "generic"

    # the day's cap: not even asked
    gate = LC.CategoryGate(CAT.CategoryIndex(), poster=FakeAi(), d=tmp_path, submit=now_submit, log=quiet)
    gate.spend.usd = gate.spend.cap
    assert gate(RULE, coin(), True) == LC.UNKNOWN and gate.one_st["cap"] == 1
    assert gate(RULE, coin(), False) is None                           # before the buy: no call, no skip
    assert gate(RULE, coin("", ""), True) == LC.UNKNOWN                # no name at all: nothing to ask


def test_the_gate_reads_the_classifiers_answers_and_the_file(tmp_path, cats_folder):
    ix = CAT.CategoryIndex.load(mints=False)
    cls = LC.LiveClassifier(ix, poster=FakeAi(code="copycat"), log=quiet)
    gate = LC.CategoryGate(ix, cls=cls, submit=now_submit, every_s=0, log=quiet)
    cls.observe("creates", {"mint": "m1", "name": "Test", "symbol": "TST", "quote": None})
    cls.classify(*cls.take())
    assert gate(RULE, coin(), False) == "category copycat"
    CAT.append([{"mint": "m2", "key": "other|oth", "cat": "scam", "day": "d", "avail_ms": T0}])
    assert gate(RULE, coin("Other", "OTH"), False) == "category scam"  # appended by another process
    assert LC.CategoryGate(ix, rules={"P_pool0_wait"})("P_pool0", coin(), True) is None


def test_the_paper_twin_skips_like_the_live_book(tmp_path, monkeypatch):
    from lab.pumpfun_rt import live
    monkeypatch.setattr(live, "paper_dir", lambda: tmp_path)
    ix = CAT.CategoryIndex()
    ix.add("", KEY, "copycat", T0)
    sh = live.Shadow("A_all_x1", models=None, alerts=False, now_ms=T0,
                     strategies=[P.BY_NAME[RULE], P.BY_NAME["P_pool0"]],
                     category=LC.CategoryGate(ix, rules=BL.PAPER_RULES, submit=now_submit, log=quiet))
    col = COL.Collector(None, on_row=sh.on_row, amm=True, meta=False)
    svc, lcol, pipe = service()
    pipe.category = LC.CategoryGate(ix, submit=now_submit, log=quiet)
    for c in (col, lcol):
        run_coin(c)
    sh.tick(T0 + 10_000)
    svc.tick(T0 + 10_000)
    assert sh.engine.skipped[(RULE, "category copycat")] == 1 and shown(pipe) == {"category copycat": 1}
    assert not any(k[1].startswith("category") for k in sh.engine.skipped if k[0] == "P_pool0")


# ---------------------------------------------------------------- the service

def test_the_service_runs_the_classifier_and_shows_it_in_the_status(tmp_path, cats_folder):
    svc, col, pipe = service()
    svc.attach_categories()
    assert pipe.category is svc.cat_gate and svc.cats is not None
    svc.cats.poster = FakeAi(code="celebrity")
    col.handle(note("c", 100, CREATE), T0, PUBLIC)
    assert MINT in svc.cats.new

    async def go():
        stop = asyncio.Event()
        task = asyncio.create_task(LS.classify_loop(svc, stop, every_s=0.05))
        for _ in range(100):
            await asyncio.sleep(0.02)
            if svc.cats.st["runs"]:
                break
        stop.set()
        await task
    asyncio.run(go())
    assert lines(cats_folder)[0]["mint"] == MINT and lines(cats_folder)[0]["cat"] == "celebrity"
    col.handle(note("m", 101, MIGRATE), T0 + 400, PUBLIC)
    col.handle(note("b", 102, POOL_BUY), T0 + 800, PUBLIC)
    svc.tick(T0 + 10_000)
    assert not pipe.pos and shown(pipe) == {"category celebrity": 1}
    svc.book.status = lambda *a: {}                                    # the test gate has no ack: the block only
    st = svc.status()["categories"]
    assert st["blocked"] == ["celebrity", "copycat", "scam"] and st["default"]
    assert st["classifier"]["classified"] == 1 and st["classifier"]["every_s"] == LC.EVERY_S


# ---------------------------------------------------------------- the evaluation's offline rule

def test_the_offline_rule_uses_a_names_category_and_keeps_coins_without_one():
    from lab.pumpfun_rt import cateval as CE
    ix = CAT.CategoryIndex()
    ix.add("", "apple|apple", "copycat", T0 + 10 ** 9)                 # written the next morning: still used
    rule = CE.OfflineRule(ix)
    assert rule("X", coin("Apple", "APPLE"), False) == "category copycat"
    assert rule("X", coin("Nobody", "NB"), True) is None and rule.unknown == 1
