"""The live pump.fun service uses the owner's paid-for provider only for the coins it watches or holds: the program-wide
links stream from the public endpoint (PYTHIA_PF_PROVIDER_FIREHOSE=1 restores the spread), one provider connection
keeps a logsSubscribe per watched or held coin (subscribed on the wait, unsubscribed on the drop, the sale, the
wait's end), at most max_subs with held coins always kept, a daily byte budget, a resubscribe after a reconnect,
which copy came first, and never a token in a log line or a file.

No network: a fake websocket session, temp folders.

Run from research/lab:  python -m pytest tests/test_pumpfun_live_provider.py
"""

from __future__ import annotations

import asyncio
import json
import types

import aiohttp

from lab.pumpfun_rt import collector as COL
from lab.pumpfun_rt import latency as LT
from lab.pumpfun_rt import live_service as LS
from test_pumpfun_live_match import CREATE, MIGRATE, POOL_BUY, PUBLIC, RULE, service
from test_pumpfun_live_match import folders  # noqa: F401 - the live files in the test's folder
from test_pumpfun_rt import MINT, POOL, T0, note

TOKEN = "s3cr3t-tok"
TEMPLATE = "wss://provider.example/v1/?api-key={token}"
URL = TEMPLATE.replace("{token}", TOKEN)
ENV = {"PYTHIA_SOLANA_WS_URLS": TEMPLATE, "PYTHIA_SOLANA_TOKEN": TOKEN}
DAY = 1_792_800_000.0                                  # a UTC midnight (2026-10-24 00:00)


class Clock:
    def __init__(self, t: float = DAY + 3600):
        self.t = t

    def __call__(self) -> float:
        return self.t


def watching(col=None, **kw) -> LS.ProviderWatch:
    return LS.ProviderWatch(URL, col, now=kw.pop("now", Clock()), **kw)


def subscribed(msgs: list[str]) -> list[str]:
    return [json.loads(m)["params"][0]["mentions"][0] for m in msgs if json.loads(m)["method"] == "logsSubscribe"]


def unsubscribed(msgs: list[str]) -> list[int]:
    return [json.loads(m)["params"][0] for m in msgs if json.loads(m)["method"] == "logsUnsubscribe"]


def confirm(pw: LS.ProviderWatch, msgs: list[str], base: int = 100) -> None:
    for m in msgs:
        d = json.loads(m)
        if d["method"] == "logsSubscribe":
            pw.on_message(json.dumps({"jsonrpc": "2.0", "id": d["id"], "result": base + d["id"]}), 0)


# ---------------------------------------------------------------- the program-wide links

def test_the_firehose_links_leave_the_provider_out_unless_the_owner_asks():
    urls = COL.feed_urls(ENV)
    assert urls == [URL, PUBLIC]
    assert LS.firehose_urls(urls, ENV) == [PUBLIC]
    assert {u for u, _, _ in LS.feed_links(LS.firehose_urls(urls, ENV))} == {PUBLIC}
    on = {**ENV, "PYTHIA_PF_PROVIDER_FIREHOSE": "1"}
    assert LS.firehose_urls(urls, on) == urls
    assert URL in {u for u, _, _ in LS.feed_links(LS.firehose_urls(urls, on))}
    no_fallback = {**ENV, "PYTHIA_PF_PUBLIC_FALLBACK": "0"}               # the providers only: the public one anyway
    assert LS.firehose_urls(COL.feed_urls(no_fallback), no_fallback) == [PUBLIC]
    assert LS.provider_url(urls, ENV) == URL


def test_without_a_provider_nothing_of_it_runs():
    urls = COL.feed_urls({})
    assert LS.firehose_urls(urls, {}) == [PUBLIC] and LS.provider_url(urls, {}) is None
    own = {"PYTHIA_SOLANA_WS": "wss://own.example"}
    assert LS.firehose_urls(COL.feed_urls(own), own) == ["wss://own.example"]
    assert LS.provider_url(COL.feed_urls(own), own) is None
    svc, col, pipe = service()
    assert svc.prov is None and col.race is None
    col.handle(note("c", 101, CREATE), T0, PUBLIC)
    col.handle(note("m", 101, MIGRATE), T0 + 5, PUBLIC)
    svc.tick(T0 + 100)
    svc.book.status = lambda *a: {"mode": "test"}                          # the book's own status as it is
    assert svc.status() == {"mode": "test"} and not col.raced


# ---------------------------------------------------------------- watched and held coins

def test_a_watched_coin_is_subscribed_on_its_wait_and_dropped_when_the_wait_ends():
    svc, col, pipe = service()
    svc.prov = watching(col)
    col.handle(note("c", 101, CREATE), T0, PUBLIC)
    col.handle(note("m", 101, MIGRATE), T0 + 5, PUBLIC)
    svc.tick(T0 + 100)
    assert MINT in pipe.waiting and svc.prov.target == {POOL: False}
    svc.prov.on_connect()
    msgs = svc.prov.plan()
    assert subscribed(msgs) == [POOL] and len(msgs) == 1
    assert svc.prov.plan() == []                                             # asked once, until the answer
    confirm(svc.prov, msgs)
    assert svc.prov.subs == {POOL: 101}
    svc.tick(T0 + 7_000)                                                     # the 5 s wait is over: no pool state
    assert not pipe.waiting and pipe.eng.skipped[(RULE, "no pool state")] == 1
    assert svc.prov.target == {} and unsubscribed(svc.prov.plan()) == [101] and svc.prov.subs == {}


def test_a_held_coin_keeps_its_stream_until_it_is_sold():
    svc, col, pipe = service()
    svc.prov = watching(col)
    col.handle(note("c", 101, CREATE), T0, PUBLIC)
    col.handle(note("m", 101, MIGRATE), T0 + 5, PUBLIC)
    svc.tick(T0 + 100)
    svc.prov.on_connect()
    confirm(svc.prov, svc.prov.plan())
    # the pool's first trade comes over the provider's stream first: the same path, the buy, the coin held
    svc.prov.on_message(note("b", 102, POOL_BUY), T0 + 400)
    col.handle(note("b", 102, POOL_BUY), T0 + 1_400, PUBLIC)                 # the public copy: a duplicate
    svc.tick(T0 + 500)
    assert len(pipe.pos) == 1 and svc.prov.target == {POOL: True} and svc.prov.plan() == []
    assert col.counts["duplicate"] == 1
    p = next(iter(pipe.pos.values()))
    pipe.pos.pop(p["pid"])                                                   # sold: as Pipeline._close
    pipe._unindex(p)
    svc.tick(T0 + 60_000)
    assert svc.prov.target == {} and unsubscribed(svc.prov.plan()) == [101]


def test_held_coins_survive_the_cap_the_oldest_watched_go_first():
    pw = watching(max_subs=3)
    pw.want({"w1": 1.0, "w2": 2.0, "w3": 3.0, "w4": 4.0}, {"h1"})
    assert pw.target == {"h1": True, "w4": False, "w3": False} and pw.cut == 2
    pw.want({"w1": 1.0, "w2": 2.0}, {"h1", "h2", "h3", "h4"})               # more held than the cap: all kept
    assert pw.target == {a: True for a in ("h1", "h2", "h3", "h4")} and pw.cut == 2
    pw.on_connect()
    assert sorted(subscribed(pw.plan())) == ["h1", "h2", "h3", "h4"]


def test_the_daily_budget_pauses_watched_coins_but_not_held_ones_until_midnight():
    clock = Clock()
    pw = watching(mb_day=0.001, now=clock)                                   # 1,000 bytes a day
    pw.want({"w1": 1.0}, {"h1"})
    assert pw.target == {"h1": True, "w1": False} and not pw.status()["paused"]
    pw.on_connect()
    confirm(pw, pw.plan())
    pw.on_message(note("x", 1, ["Program log: " + "a" * 2_000]), 0)          # the bytes count, whatever they are
    pw.want({"w1": 1.0}, {"h1"})
    assert pw.target == {"h1": True}
    st = pw.status()
    assert st["paused"] and "00:00 UTC" in st["why"] and st["mb_today"] > 0.001
    assert unsubscribed(pw.plan()) == [102] and pw.subs == {"h1": 101}
    clock.t = DAY + 86_400 + 1                                               # the next UTC day
    pw.want({"w1": 1.0}, {"h1"})
    assert pw.target == {"h1": True, "w1": False} and not pw.status()["paused"]


# ---------------------------------------------------------------- the connection

class FakeWS:
    def __init__(self, session):
        self.session = session
        self.out: list[str] = []
        self.inbox: list = []

    async def send_str(self, m: str) -> None:
        self.out.append(m)
        d = json.loads(m)
        if d["method"] == "logsSubscribe":
            self.inbox.append(json.dumps({"jsonrpc": "2.0", "id": d["id"], "result": 500 + d["id"]}))

    async def receive(self):
        await asyncio.sleep(0)
        if self.inbox:
            return types.SimpleNamespace(type=aiohttp.WSMsgType.TEXT, data=self.inbox.pop(0))
        if len(self.session.sockets) >= 2:
            self.session.stop.set()
        return types.SimpleNamespace(type=aiohttp.WSMsgType.CLOSE, data=None)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class FakeSession:
    def __init__(self, stop, fail: int = 0):
        self.stop = stop
        self.fail = fail
        self.sockets: list[FakeWS] = []
        self.kw: list[dict] = []

    def ws_connect(self, url, **kw):
        self.kw.append(kw)
        if self.fail:
            self.fail -= 1
            raise aiohttp.ClientError(f"Cannot connect to host {url}")      # carries the URL with the key
        ws = FakeWS(self)
        self.sockets.append(ws)
        return ws


def test_every_stream_is_subscribed_again_after_a_reconnect(monkeypatch):
    async def go():
        stop = asyncio.Event()
        session = FakeSession(stop)
        pw = watching()
        pw.want({"w1": 1.0}, {"h1"})
        await asyncio.wait_for(pw.run(session, stop), 10)
        return pw, session
    pw, session = asyncio.run(go())
    first, second = session.sockets
    assert sorted(subscribed(first.out)) == ["h1", "w1"]
    assert sorted(subscribed(second.out)) == ["h1", "w1"]                   # everything again on the new link
    assert pw.connects == 2 and not pw.connected and pw.subs == {}
    assert session.kw[0]["heartbeat"]                                        # pings keep the idle stream open


def test_no_token_in_any_log_line_or_file(capsys, folders):
    async def go():
        stop = asyncio.Event()
        session = FakeSession(stop, fail=1)
        pw = watching()
        pw.want({}, {"h1"})
        await asyncio.wait_for(pw.run(session, stop), 10)
        return pw
    pw = asyncio.run(go())
    pw.on_connect()
    msgs = pw.plan()
    rid = json.loads(msgs[0])["id"]
    pw.on_message(json.dumps({"jsonrpc": "2.0", "id": rid, "error": {"code": -32602, "message": URL}}), 0)
    pw.save()
    svc, col, pipe = service()
    svc.prov = pw
    svc.book.status = lambda *a: {"mode": "test"}
    st = json.dumps(svc.status())
    printed = capsys.readouterr()
    text = printed.out + printed.err + st + LS.ProviderWatch.path().read_text(encoding="utf-8")
    assert "provider wss://provider.example ClientError" in printed.out
    assert "refused a subscription (code -32602)" in printed.out
    assert TOKEN not in text and "api-key" not in text and "/v1" not in text
    assert pw.status()["host"] == "wss://provider.example"


# ---------------------------------------------------------------- which copy came first

def test_the_lead_per_transaction_over_both_and_the_latency_report(folders):
    from lab import report as rep
    svc, col, pipe = service()
    pw = svc.prov = watching(col)
    col.race = pw.raced
    pw.on_message(note("a", 101, POOL_BUY), T0)                              # the provider first by 900 ms
    col.handle(note("a", 101, POOL_BUY), T0 + 900, PUBLIC)
    col.handle(note("a", 101, POOL_BUY), T0 + 950, PUBLIC)                   # a third copy: counted once
    col.handle(note("b", 102, POOL_BUY), T0 + 1_000, PUBLIC)                 # the public one first by 200 ms
    pw.on_message(note("b", 102, POOL_BUY), T0 + 1_200)
    col.handle(note("c", 103, POOL_BUY), T0 + 1_000, PUBLIC)                 # public only: nothing to compare
    col.handle(note("c", 103, POOL_BUY), T0 + 1_100, "wss://other.example")
    day = pw.today()
    assert day["n"] == 2 and day["first"] == 1 and sorted(day["leads"]) == [-200, 900] and day["bytes"] > 0
    pw.save()
    rows = LT.provider_summary()
    assert rows[0]["n"] == 2 and rows[0]["share_first"] == 0.5 and rows[0]["median_lead_ms"] == 350.0
    LT.save({"n": 0})
    md = (rep.REPORTS / "pumpfun_rt" / "latency.md").read_text(encoding="utf-8")
    js = json.loads((rep.REPORTS / "pumpfun_rt" / "latency.json").read_text(encoding="utf-8"))
    assert "## provider vs public, watched coins" in md and "| 2 | 50% | 350 ms |" in md
    assert js["provider"][0]["n"] == 2
    # a restart the same day goes on with the day's bytes (the budget is not reset)
    assert watching().today()["bytes"] == day["bytes"]


def test_the_latency_report_has_no_provider_section_without_the_file():
    assert LT.provider_summary() is None
    assert "provider vs public" not in LT.report_md({"n": 0})
