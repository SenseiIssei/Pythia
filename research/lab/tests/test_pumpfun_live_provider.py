"""The live pump.fun service uses the owner's paid-for provider only for the coins it watches or holds: the program-wide
links stream from the public endpoint (PYTHIA_PF_PROVIDER_FIREHOSE=1 restores the spread), one provider connection
keeps a logsSubscribe per watched or held coin (subscribed on the wait, unsubscribed on the drop, the sale, the
wait's end), at most max_subs with held coins always kept, a daily byte budget, a resubscribe after a reconnect,
which copy came first, and never a token in a log line or a file. Several providers side by side: the same
subscriptions on each, the first copy wins, a lead and a budget per provider, a provider without logsSubscribe
mentions benched for the session (said once), one that errors or refuses later until the reconnect, a report row
per provider, and no part of any URL after the host anywhere.

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
    assert LS.provider_urls(urls, ENV) == [URL]


def test_without_a_provider_nothing_of_it_runs():
    urls = COL.feed_urls({})
    assert LS.firehose_urls(urls, {}) == [PUBLIC] and LS.provider_urls(urls, {}) == []
    own = {"PYTHIA_SOLANA_WS": "wss://own.example"}
    assert LS.firehose_urls(COL.feed_urls(own), own) == ["wss://own.example"]
    assert LS.provider_urls(COL.feed_urls(own), own) == []
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
    assert "## provider vs public, watched coins" in md and "| wss://provider.example | 1 | 2 | 50% | 350 ms |" in md
    assert js["provider"][0]["n"] == 2
    # a restart the same day goes on with the day's bytes (the budget is not reset)
    assert watching().today()["bytes"] == day["bytes"]


def test_the_latency_report_has_no_provider_section_without_the_file():
    assert LT.provider_summary() is None
    assert "provider vs public" not in LT.report_md({"n": 0})


# ---------------------------------------------------------------- several providers side by side

KEYS = ("k3y-helius", "k3y-quick", "k3y-alchemy", "k3y-chain")
URLS = [f"wss://mainnet.helius.example/?api-key={KEYS[0]}",
        f"wss://name-x.quick.example/{KEYS[1]}/",
        f"wss://solana.alchemy.example/v2/{KEYS[2]}",
        f"wss://user:{KEYS[3]}@solana.alchemy.example:8443/ws/{{token}}?region=eu"]   # a second plan, same host
MANY = {"PYTHIA_SOLANA_WS_URLS": ",".join(URLS), "PYTHIA_SOLANA_TOKEN": TOKEN}
PARTS = list(KEYS) + [TOKEN, "api-key", "/v2", "/ws", "region", "user:", "8443", "name-x.quick.example/"]


def many(col=None, n: int = 2, **kw) -> LS.Providers:
    return LS.Providers(LS.provider_urls(COL.feed_urls(MANY), MANY)[:n], col, now=kw.pop("now", Clock()), **kw)


def test_every_provider_gets_the_same_subscriptions_and_the_first_copy_wins():
    urls = COL.feed_urls(MANY)
    provs = LS.provider_urls(urls, MANY)
    assert len(provs) == 4 and urls[-1] == PUBLIC and LS.firehose_urls(urls, MANY) == [PUBLIC]
    ps = LS.Providers(provs, now=Clock())
    assert [w.label for w in ps.all] == ["wss://mainnet.helius.example", "wss://name-x.quick.example",
                                         "wss://solana.alchemy.example", "wss://solana.alchemy.example#2"]
    ps.want({"w1": 1.0}, {"h1"})
    for w in ps.all:
        w.on_connect()
        assert w.target == {"h1": True, "w1": False} and sorted(subscribed(w.plan())) == ["h1", "w1"]
    svc, col, pipe = service()
    two = svc.prov = many(col)
    col.race = two.raced
    a, b = two.all
    col.handle(note("c", 101, CREATE), T0, PUBLIC)
    col.handle(note("m", 101, MIGRATE), T0 + 5, PUBLIC)
    svc.tick(T0 + 100)
    assert a.target == b.target == {POOL: False}
    b.on_message(note("x", 102, POOL_BUY), T0 + 300)                          # b first, a and public: duplicates
    a.on_message(note("x", 102, POOL_BUY), T0 + 350)
    col.handle(note("x", 102, POOL_BUY), T0 + 900, PUBLIC)
    svc.tick(T0 + 1_000)
    assert len(pipe.pos) == 1 and col.counts["duplicate"] == 2
    assert a.target == b.target == {POOL: True}                              # held: on every provider
    # each provider against the public copy, once: b by 600 ms, a by 550 ms
    assert b.today()["leads"] == [600] and a.today()["leads"] == [550]
    svc.book.status = lambda *a: {"mode": "test"}
    st = svc.status()["provider"]
    assert st["of"] == 2 and [p["host"] for p in st["providers"]] == [a.label, b.label]


def test_the_lead_counts_per_provider_whoever_came_first():
    col = LS.LiveCollector(None, lambda *x: None, amm=True, meta=False)
    ps = many(col, n=3)
    col.race = ps.raced
    a, b, c = ps.all
    col.handle(note("p", 101, POOL_BUY), T0, PUBLIC)                         # the public copy first
    a.on_message(note("p", 101, POOL_BUY), T0 + 100)
    b.on_message(note("p", 101, POOL_BUY), T0 + 40)
    col.handle(note("p", 101, POOL_BUY), T0 + 500, "wss://other.example")    # a second public copy: nothing new
    assert a.today()["leads"] == [-100] and b.today()["leads"] == [-40] and c.today()["n"] == 0
    a.on_message(note("p", 101, POOL_BUY), T0 + 900)                         # a again: counted once
    assert a.today()["n"] == 1


def test_each_provider_has_its_own_budget_and_the_others_carry_on():
    clock = Clock()
    ps = many(mb_day=0.001, now=clock)
    a, b = ps.all
    for w in ps.all:
        w.on_connect()
    ps.want({"w1": 1.0}, {"h1"})
    for w in ps.all:
        confirm(w, w.plan())
    a.on_message(note("x", 1, ["Program log: " + "a" * 2_000]), 0)           # a over its 1,000 bytes, b not
    ps.want({"w1": 1.0}, {"h1"})
    assert a.target == {} and b.target == {"h1": True, "w1": False}          # b up: a lets go of the held coin too
    assert a.benched() == "budget" and b.benched() is None
    st = ps.status()
    assert st["up"] == 1 and not st["paused"] and "00:00 UTC" in st["why"]
    b.on_down("error")                                                       # b gone: a keeps the held coin
    ps.want({"w1": 1.0}, {"h1"})
    assert a.target == {"h1": True} and b.target == {"h1": True, "w1": False}
    clock.t = DAY + 86_400 + 1
    ps.want({"w1": 1.0}, {"h1"})
    assert a.target == {"h1": True, "w1": False} and a.benched() is None


def test_a_provider_without_mentions_is_benched_for_the_session_and_said_once(capsys):
    class Refusing(FakeWS):
        async def send_str(self, m: str) -> None:
            self.out.append(m)
            d = json.loads(m)
            self.inbox.append(json.dumps({"jsonrpc": "2.0", "id": d["id"],
                                          "error": {"code": -32601, "message": URLS[1]}}))

    class Session(FakeSession):
        def ws_connect(self, url, **kw):
            self.kw.append(kw)
            ws = Refusing(self) if KEYS[1] in url else FakeWS(self)
            self.sockets.append(ws)
            return ws

    async def go():
        stop = asyncio.Event()
        session = Session(stop)
        clock = Clock()
        ps = many(now=clock)
        ps.want({"w1": 1.0}, {"h1"})
        tasks = ps.run(session, stop)
        await asyncio.wait_for(tasks[1], 10)                                 # the refusing one ends by itself
        clock.t += 600                                                       # ten minutes later
        ps.want({"w1": 1.0}, {"h1"})
        stop.set()
        await asyncio.gather(*tasks)
        return ps
    ps = asyncio.run(go())
    a, b = ps.all
    out = capsys.readouterr().out
    assert out.count("refused logsSubscribe with mentions") == 1 and "wss://name-x.quick.example" in out
    assert b.out and b.benched() == "unsupported" and b.target == {} and b.connects == 1
    assert b.status()["benched_min_today"] == 10.0 and "session" in b.status()["why"]
    assert not a.out and a.accepted >= 2                                     # the other carried on
    for p in PARTS:
        assert p not in out


def test_a_later_refusal_or_an_error_benches_until_the_reconnect():
    clock = Clock()
    pw = LS.ProviderWatch(URLS[0], now=clock)
    pw.want({"w1": 1.0, "w2": 2.0}, set())
    pw.on_connect()
    msgs = pw.plan()
    pw.on_message(json.dumps({"jsonrpc": "2.0", "id": json.loads(msgs[0])["id"], "result": 7}), 0)
    pw.on_message(json.dumps({"jsonrpc": "2.0", "id": json.loads(msgs[1])["id"], "error": {"code": -32005}}), 0)
    assert not pw.out and pw.leave == "refused"                              # took one: a limit, not the plan
    pw.on_down(pw.leave)
    assert pw.benched() == "refused" and not pw.active()
    clock.t += 90
    pw.on_connect()
    assert pw.benched() is None and pw.today()["benched_s"] == 90.0
    pw.on_down("error")
    clock.t += 30
    assert pw.status()["benched"] == "error" and pw.today()["benched_s"] == 120.0


def test_the_report_has_a_row_per_provider_and_no_part_of_any_url(capsys, folders):
    from lab import report as rep
    col = LS.LiveCollector(None, lambda *x: None, amm=True, meta=False)
    clock = Clock()
    ps = LS.Providers(LS.provider_urls(COL.feed_urls(MANY), MANY), col, now=clock)
    col.race = ps.raced
    a, b, c, d = ps.all
    a.on_message(note("p", 101, POOL_BUY), T0)
    col.handle(note("p", 101, POOL_BUY), T0 + 300, PUBLIC)
    c.on_message(note("p", 101, POOL_BUY), T0 + 400)
    d.on_message(json.dumps({"jsonrpc": "2.0", "id": 1, "error": {"code": -1, "message": URLS[3]}}), 0)
    d.pending[1] = "h1"
    d.on_message(json.dumps({"jsonrpc": "2.0", "id": 1, "error": {"code": -1, "message": URLS[3]}}), 0)
    clock.t += 3600
    ps.save()
    st = json.dumps(ps.status())
    rows = LT.provider_summary()
    assert [r["provider"] for r in rows] == sorted(w.label for w in ps.all)
    by = {r["provider"]: r for r in rows}
    assert by[a.label]["n"] == 1 and by[a.label]["share_first"] == 1.0 and by[a.label]["median_lead_ms"] == 300
    assert by[c.label]["median_lead_ms"] == -100 and by[b.label]["n"] == 0
    assert by[d.label]["benched_now"] == "unsupported" and by[d.label]["benched_h"] == 1.0
    LT.save({"n": 0})
    md = (rep.REPORTS / "pumpfun_rt" / "latency.md").read_text(encoding="utf-8")
    js = (rep.REPORTS / "pumpfun_rt" / "latency.json").read_text(encoding="utf-8")
    assert "| wss://solana.alchemy.example#2 | 1 | 0 | n/a | n/a | n/a | 0.0 | 1.0 h, now unsupported |" in md
    assert md.count("| wss://") == 4
    printed = capsys.readouterr()
    text = printed.out + printed.err + st + md + js + LS.ProviderWatch.path().read_text(encoding="utf-8")
    for p in PARTS:
        assert p not in text, p


def test_a_file_of_one_provider_still_reads(folders):
    LS.ProviderWatch.path().parent.mkdir(parents=True, exist_ok=True)
    LS.ProviderWatch.path().write_text(json.dumps({"host": "wss://provider.example", "days": {
        "2026-10-24": {"bytes": 5_000_000, "n": 4, "first": 3, "leads": [10, 20, 30, -5]}}}), encoding="utf-8")
    assert watching().today()["bytes"] == 5_000_000                          # the day's budget goes on
    rows = LT.provider_summary()
    assert rows == [{"provider": "wss://provider.example", "days": 1, "n": 4, "share_first": 0.75,
                     "median_lead_ms": 15.0, "p90_lead_ms": 27.0, "mb_day": 5.0, "benched_h": 0.0,
                     "benched_now": None}]
    LS.ProviderWatch.path().write_text(json.dumps({"providers": {"wss://h.example/v2/abc?k=1#x": {"days": {}}}}),
                                       encoding="utf-8")
    assert LT.provider_summary()[0]["provider"] == "wss://h.example"         # whatever a file holds: the host only


def test_the_pool_record_keeps_each_pools_first_minutes_with_their_feed(tmp_path):
    import gzip
    col = LS.LiveCollector(None, None, amm=True, meta=False)
    col.record = LS.PoolRecord(window_s=600, root=tmp_path, now=lambda: DAY + 60)
    col.handle(note("c1", 100, CREATE), T0)                                   # a creation: not recorded
    col.handle(note("m1", 101, MIGRATE), T0 + 1_000, PUBLIC)
    col.handle_tx(102, "b1", False, POOL_BUY, T0 + 2_000, LS.WATCH_SRC + "h.example")
    col.handle(note("b1", 102, POOL_BUY), T0 + 2_500, PUBLIC)                       # the public copy: a duplicate
    col.handle(note("b2", 103, POOL_BUY), T0 + 1_000 + 600_001)               # past the window
    assert col.record.due() and col.record.flush() == 2 and not col.record.buf
    rows = [json.loads(x) for x in gzip.open(tmp_path / "2026-10-24.jsonl.gz", "rt", encoding="utf-8")]
    assert [(r["table"], r.get("kind"), r["src"]) for r in rows] == [
        ("other", "migrate", PUBLIC), ("amm", None, LS.WATCH_SRC + "h.example")]
    assert rows[1]["mint"] == MINT and rows[1]["sig"] == "b1" and rows[1]["t"] == T0 + 2_000
    col.handle(note("b3", 104, POOL_BUY), T0 + 3_000)
    col.record.flush()                                                        # a second gzip member, one file
    assert len(list(gzip.open(tmp_path / "2026-10-24.jsonl.gz", "rt", encoding="utf-8"))) == 3
    assert col.record.status() == {"window_s": 600.0, "rows": 3, "written": 3}
