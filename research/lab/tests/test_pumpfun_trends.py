"""The Trends view of the paper engine (lab.pumpfun_rt.trends): the running counters and their windows, the three
lists (sorting, limits, the migrating and fresh rules), blocked coins, the badges' thresholds, the file, and that
the paper books trade exactly as without it (a synthetic stream replayed twice, compared field by field). No network.

Run from research/lab:  python -m pytest tests/test_pumpfun_trends.py
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from lab.pumpfun_rt import curve as C
from lab.pumpfun_rt import events as E
from lab.pumpfun_rt import live
from lab.pumpfun_rt import model as M
from lab.pumpfun_rt import trends as TR

SOL = C.LAMPORTS
B = TR.BUCKET_MS
T0 = 1_792_450_000_000 - 1_792_450_000_000 % B         # on a bucket edge, so the windows are exact


def key(i: int, tag: str = "") -> str:
    return E.b58(bytes([i % 256]) * 32) + tag


class Feed:
    """Rows as the collector hands them to the shadow book, with consistent curve reserves."""

    def __init__(self, sh):
        self.sh = sh
        self.curves: dict[str, list] = {}
        self.pools: dict[str, list] = {}
        self.tx = self.slot = 0

    def _on(self, table, row):
        self.sh.on_row(table, row)

    def create(self, t, mint, creator, name="Coin", symbol="CN", **kw):
        self.tx += 1
        self.slot += 1
        vs, vt, rt = 30 * SOL, 1_073_000_000 * 10 ** 6, C.INITIAL_RT
        self.curves[mint] = [vs, vt, rt, 0]
        self._on("creates", {"t": t, "tx": self.tx, "slot": self.slot, "mint": mint, "creator": creator, "vs": vs,
                             "vt": vt, "rt": rt, "name": name, "symbol": symbol, "uri": "https://ipfs.io/ipfs/x",
                             "mayhem": kw.get("mayhem", False), "cashback": False, "quote": kw.get("quote"), "user": None})

    def trade(self, t, mint, user, sol=None, tok=None, buy=True):
        vs, vt, rt, rs = self.curves[mint]
        self.tx += 1
        self.slot += 1
        if buy:
            tok = min(int(vt * sol / (vs + sol)), rt)
            vs, vt, rt, rs = vs + sol, vt - tok, rt - tok, rs + sol
        else:
            sol = int(vs * tok / (vt + tok))
            vs, vt, rt, rs = vs - sol, vt + tok, rt + tok, rs - sol
        self.curves[mint] = [vs, vt, rt, rs]
        self._on("trades", {"t": t, "tx": self.tx, "slot": self.slot, "mint": mint, "buy": buy, "sol": sol,
                            "tok": tok, "user": user, "vs": vs, "vt": vt, "rs": rs, "rt": rt, "fb": 95, "cfb": 30,
                            "sig": f"s{self.tx}", "quote": None})
        return tok

    def migrate(self, t, mint, pool):
        self._on("other", {"t": t, "kind": "complete", "mint": mint})
        self._on("other", {"t": t, "kind": "migrate", "mint": mint, "pool": pool, "sol": 85 * SOL,
                           "tok": 200_000_000 * 10 ** 6})
        self.pools[mint] = [200_000_000 * 10 ** 6, 70 * SOL]

    def amm(self, t, mint, user, quote, buy=True):
        pb, pq = self.pools[mint]
        base = int(pb * quote / (pq + quote)) if buy else int(pb * quote / max(pq - quote, 1))
        self.slot += 1
        self._on("amm", {"t": t, "mint": mint, "buy": buy, "base": base, "quote": quote, "pb": pb, "pq": pq,
                         "lpb": 20, "pfb": 5, "cfb": 5, "slot": self.slot, "user": user, "vq": None,
                         "sig": f"a{self.slot}"})
        self.pools[mint] = [pb - base, pq + quote] if buy else [pb + base, pq - quote]


def shadow(tmp_path, monkeypatch, trends=True, models=None, blocked=None):
    monkeypatch.setattr(live, "paper_dir", lambda: tmp_path / "paper")
    sh = live.Shadow("A_all_x1", models=models, alerts=False, now_ms=T0, trends=False)
    if trends:
        bl = tmp_path / "blocked-mints.txt"
        bl.write_text("# the owner's list\n" + "".join(f"{m}  # why\n" for m in blocked or []), encoding="utf-8")
        sh.trends = TR.Trends(sh.engine, tmp_path / "trends.json", sol_usd=None, blocked=[bl])
        sh.trends.sol_usd = 200.0
    return sh


# ---------------------------------------------------------------- counters and windows

def test_the_windows_count_volume_buyers_flow_and_change(tmp_path, monkeypatch):
    sh = shadow(tmp_path, monkeypatch)
    f = Feed(sh)
    m = key(1)
    now = T0 + 30 * 60_000 + 15_000
    f.create(now - 25 * 60_000, m, key(2))
    f.trade(now - 20 * 60_000, m, key(10), 4 * SOL)          # outside every window
    f.trade(now - 10 * 60_000, m, key(11), 2 * SOL)          # 15 minutes
    f.trade(now - 3 * 60_000, m, key(12), SOL)               # 5 minutes
    held = f.trade(now - 20_000, m, key(13), SOL // 4)       # 1 minute
    f.trade(now - 10_000, m, key(13), SOL // 4)               # the same buyer again
    f.trade(now - 5_000, m, key(13), tok=held, buy=False)
    snap = sh.trends.snapshot(now)
    e = snap["lists"]["hot"][0]
    assert e["mint"] == m and (e["vol_1m"], e["vol_5m"], e["vol_15m"]) == (0.5, 1.5, 3.5)
    assert e["buyers_5m"] == 2 and e["buys_5m"] == 3 and e["sells_5m"] == 1
    assert e["net_5m"] == pytest.approx(1.5 - e["sell_5m"], abs=1e-3) and 0 < e["sell_5m"] < 0.3
    assert e["chg_5m"] > 0 and e["chg_15m"] > e["chg_5m"]
    assert e["mcap_sol"] == pytest.approx(e["price_sol"] * 1e9, rel=1e-3)
    assert e["mcap_usd"] == pytest.approx(e["mcap_sol"] * 200, rel=1e-3)
    assert e["progress"] > 0 and not e["migrated"] and e["age_s"] == 25 * 60
    assert len(e["spark"]) == TR.SPARK_N and e["spark"][-1] == pytest.approx(e["mcap_sol"], rel=1e-3)
    assert e["blocked"] is False and e["flags"] == [] and e["p_win"] is None
    json.dumps(snap, allow_nan=False)
    # Fifteen quiet minutes later the coin is no longer tracked
    assert sh.trends.snapshot(now + 16 * 60_000)["lists"]["hot"] == []
    assert sh.trends.coins == {}


def test_hot_is_sorted_by_five_minute_volume_and_capped(tmp_path, monkeypatch):
    sh = shadow(tmp_path, monkeypatch)
    f = Feed(sh)
    now = T0 + 10 * 60_000
    for i in range(TR.TOP + 5):
        m = key(i, "h")
        f.create(now - 8 * 60_000, m, key(200 + i))
        f.trade(now - 60_000, m, key(100 + i), (i + 1) * SOL // 10)
    f.create(now - 8 * 60_000, "quiet", key(250))
    f.trade(now - 7 * 60_000, "quiet", key(251), 50 * SOL)    # big but outside 5 minutes
    hot = sh.trends.snapshot(now)["lists"]["hot"]
    assert len(hot) == TR.TOP
    assert [e["mint"] for e in hot[:2]] == [key(TR.TOP + 4, "h"), key(TR.TOP + 3, "h")]
    assert all(a["vol_5m"] >= b["vol_5m"] for a, b in zip(hot, hot[1:]))
    assert "quiet" not in {e["mint"] for e in hot}


def test_about_to_migrate_takes_curves_over_seventy_percent_by_progress_then_speed(tmp_path, monkeypatch):
    sh = shadow(tmp_path, monkeypatch)
    f = Feed(sh)
    now = T0 + 20 * 60_000
    for i, (sol, split) in enumerate([(50, 1), (50, 4), (40, 1), (30, 1)]):
        m = key(i, "m")
        f.create(now - 12 * 60_000, m, key(50 + i))
        # the same SOL in one go (fast) or spread over 12 minutes, the second part last minute
        if split == 1:
            f.trade(now - 60_000, m, key(60 + i), sol * SOL)
        else:
            f.trade(now - 11 * 60_000, m, key(60 + i), sol * SOL * 3 // 4)
            f.trade(now - 60_000, m, key(70 + i), sol * SOL // 4)
    mig = sh.trends.snapshot(now)["lists"]["migrating"]
    progs = {e["mint"]: e["progress"] for e in mig}
    assert set(progs) == {key(0, "m"), key(1, "m"), key(2, "m")} and all(p >= 0.7 for p in progs.values())
    assert progs[key(0, "m")] == pytest.approx(progs[key(1, "m")], abs=1e-3)
    assert [e["mint"] for e in mig[:2]] == [key(0, "m"), key(1, "m")]     # same progress: the faster first
    assert mig[0]["speed_pm"] > mig[1]["speed_pm"] > 0
    assert mig[-1]["mint"] == key(2, "m")


def test_fresh_pools_are_the_last_thirty_minutes_by_pool_activity(tmp_path, monkeypatch):
    sh = shadow(tmp_path, monkeypatch)
    f = Feed(sh)
    now = T0 + 90 * 60_000
    for i, ago in enumerate([40, 20, 10, 5]):
        m = key(i, "p")
        f.create(now - 80 * 60_000, m, key(80 + i))
        f.trade(now - (ago + 1) * 60_000, m, key(90 + i), 60 * SOL)
        f.migrate(now - ago * 60_000, m, key(120 + i))
    f.amm(now - 60_000, key(1, "p"), key(130), 3 * SOL)
    f.amm(now - 50_000, key(1, "p"), key(131), SOL, buy=False)
    f.amm(now - 40_000, key(2, "p"), key(132), SOL)
    fresh = sh.trends.snapshot(now)["lists"]["fresh"]
    assert [e["mint"] for e in fresh] == [key(1, "p"), key(2, "p"), key(3, "p")]   # 40 minutes ago is gone
    assert fresh[0]["pool_vol_5m"] == 4.0 and fresh[0]["pool_trades_5m"] == 2 and fresh[0]["migrated"]
    assert fresh[0]["progress"] is None and fresh[0]["speed_pm"] is None
    assert fresh[2]["pool_vol_5m"] == 0 and fresh[2]["migrate_ms"] == now - 5 * 60_000


def test_a_blocked_coin_is_marked_and_never_highlighted(tmp_path, monkeypatch):
    bad = key(7, "b")
    sh = shadow(tmp_path, monkeypatch, blocked=[bad])
    f = Feed(sh)
    now = T0 + 10 * 60_000
    sh.engine.book.created(key(8), T0)                        # the creator had a coin complete before
    sh.engine.book.migrated(key(8))
    for m in (bad, key(9, "b")):
        f.create(now - 5 * 60_000, m, key(8), mayhem=m == bad)
        f.trade(now - 60_000, m, key(30), 2 * SOL)
    hot = {e["mint"]: e for e in sh.trends.snapshot(now)["lists"]["hot"]}
    assert hot[bad]["blocked"] and hot[bad]["badges"] == [] and hot[bad]["flags"] == ["mayhem"]
    assert hot[key(9, "b")]["badges"] == ["creator_mig"] and hot[key(9, "b")]["creator_migrated"] == 1


def test_a_coin_quoted_in_another_coin_is_not_ranked_by_sol(tmp_path, monkeypatch):
    sh = shadow(tmp_path, monkeypatch)
    f = Feed(sh)
    now = T0 + 10 * 60_000
    f.create(now - 5 * 60_000, "usd", key(40), quote=key(41))
    f.trade(now - 60_000, "usd", key(42), 50 * SOL)          # in the other coin's units: not 50 SOL
    f.create(now - 5 * 60_000, "sol", key(43))
    f.trade(now - 60_000, "sol", key(44), SOL)
    snap = sh.trends.snapshot(now)
    assert [e["mint"] for e in snap["lists"]["hot"]] == ["sol"]
    e = snap["lists"]["migrating"][0]
    assert e["mint"] == "usd" and e["progress"] > 0.8 and e["flags"] == ["quote"]
    assert e["vol_5m"] is None and e["mcap_sol"] is None and e["mcap_usd"] is None and e["spark"] == []


# ---------------------------------------------------------------- badges

def test_the_badge_thresholds():
    b = TR.badges
    assert b({}) == []
    assert b({"p_win": 0.375, "base_win": 0.25}) == ["win_high"]               # 1.5 x base
    assert b({"p_win": 0.374, "base_win": 0.25}) == []
    assert b({"p_win": 0.125, "base_win": 0.25}) == ["win_low"]                # half the base
    assert b({"p_win": 0.126, "base_win": 0.25}) == []
    assert b({"p_win": 0.3, "base_win": 0.25, "win_label": "win0"}, {"win0": {"0.3": 0.3}}) == ["win_high"]
    assert b({"p_win": 0.299, "base_win": 0.25, "win_label": "win0"}, {"win0": {"0.3": 0.3}}) == []
    assert b({"p_rug": 0.375, "base_rug": 0.25}) == ["rug_risk"] and b({"p_rug": 0.374, "base_rug": 0.25}) == []
    assert b({"p_3x": 0.125, "base_3x": 0.0625}) == ["p3x_high"] and b({"p_3x": 0.124, "base_3x": 0.0625}) == []
    assert b({"smart_n": 2}) == ["smart"] and b({"smart_n": 1}) == []
    assert b({"creator_migrated": 1}) == ["creator_mig"] and b({"creator_migrated": 0}) == []
    assert b({"dev_sold": 0.5}) == ["dev_sold"] and b({"dev_sold": 0.49}) == []
    assert set(TR.BADGES) == {"win_high", "win_low", "rug_risk", "p3x_high", "smart", "creator_mig", "dev_sold"}
    assert all("\u2014" not in v for v in TR.BADGES.values()) and "\u2014" not in TR.NOTE


def test_the_ticker_and_the_block_list_parse(tmp_path):
    assert TR.parse_ticker({"result": {"SOLUSD": {"c": ["187.5", "1"]}}}) == 187.5
    assert TR.parse_ticker({"result": {}}) is None and TR.parse_ticker({"error": ["x"]}) is None
    p = tmp_path / "b.txt"
    p.write_text("A\n\n# c\nB # note\n", encoding="utf-8")
    assert TR.read_blocked([p, tmp_path / "missing.txt"]) == {"A", "B"}


# ---------------------------------------------------------------- the file and the books

class Stub:
    """A booster stand-in: a fixed logistic of a few features."""

    def __init__(self, k):
        self.k = k

    def predict(self, X):
        X = np.nan_to_num(np.asarray(X, dtype=float))
        return 1 / (1 + np.exp(-(X[:, :3].sum(axis=1) * self.k - 2)))


def stub_models():
    from lab.pumpfun_rt import early as EA
    from lab.pumpfun_rt.selfeat import SEL0, SEL5
    feats = EA.early_feature_list()
    return {"sel_win0": M.Fitted(Stub(0.01), None, None, 0.2, list(SEL0)),
            "sel_rug0": M.Fitted(Stub(0.02), None, None, 0.3, list(SEL0)),
            "sel_win5": M.Fitted(Stub(0.01), None, None, 0.2, list(SEL5)),
            "sel_rug5": M.Fitted(Stub(0.02), None, None, 0.3, list(SEL5)),
            "e_peak3x": M.Fitted(Stub(0.03), None, None, 0.05, feats),
            "sel_policy": {"win0": {"0.3": 0.25}}}


def stream(sh, seed=5):
    """An hour of synthetic coins: most dumped, some run and complete, their pools traded."""
    rng = np.random.default_rng(seed)
    f = Feed(sh)
    events = []
    for k in range(60):
        t0 = T0 + k * 60_000
        mint, dev = key(k, "s"), key(200 + k % 9)
        events.append((t0, 0, "create", mint, dev))
        run = rng.random() < 0.25
        for j in range(30):
            events.append((t0 + 400 * (j + 1) + int(rng.integers(0, 300)), 1, "trade", mint,
                           dev if j == 0 else key(10 + int(rng.integers(0, 80))), run, j))
        if run:
            events.append((t0 + 20_000, 2, "migrate", mint, key(150 + k)))
            for j in range(20):
                events.append((t0 + 21_000 + 900 * j, 3, "amm", mint, key(10 + int(rng.integers(0, 80))), j))
    held: dict = {}
    clock = T0
    for ev in sorted(events, key=lambda e: (e[0], e[1])):
        t, kind, mint = ev[0], ev[2], ev[3]
        while clock + 1000 <= t:                               # the collector's one-second ticks
            clock += 1000
            sh.tick(clock)
        done = mint in f.pools
        if kind == "create":
            f.create(t, mint, ev[4], symbol=f"S{mint[-3:]}")
        elif kind == "trade" and not done:
            user, run, j = ev[4], ev[5], ev[6]
            h = held.get((mint, user))
            if j > 3 and h and rng.random() < (0.2 if run else 0.5):
                f.trade(t, mint, user, tok=held.pop((mint, user)), buy=False)
            else:
                sol = int(SOL * (3.0 if run else 0.2) * (1 + rng.random()))
                held[(mint, user)] = (h or 0) + f.trade(t, mint, user, sol)
        elif kind == "migrate":
            f.migrate(t, mint, ev[4])
        elif kind == "amm":
            f.amm(t, mint, ev[4], int(SOL * (0.5 + rng.random())), buy=bool(ev[5] % 3))
    for _ in range(120):
        clock += 1000
        sh.tick(clock)
    return clock


def books(sh) -> dict:
    """Everything a paper book decided, as plain data."""
    e = sh.engine
    pipes = [{"status": p.status(), "pos": {k: dict(v) for k, v in p.pos.items()}} for p in e.pipes]
    return json.loads(json.dumps({
        "positions": e.positions, "closed": sh.closed, "failed": e.failed, "skipped": sorted(map(str, e.skipped.items())),
        "counts": dict(e.counts), "totals": sh.totals, "pipes": pipes, "open_n": dict(e.open_n),
        "wallets": dict(e.wallets.rows), "creators": dict(e.book.rows), "snipers": e.early.snipers.to_json(),
        "mkt": [len(e.early.mkt_trades), len(e.early.mkt_creates), len(e.early.mkt_done)],
        "heap": len(e.heap), "seq": e.seq, "next_pid": e.next_pid}, default=str, sort_keys=True))


def test_the_paper_books_trade_exactly_as_without_the_view(tmp_path, monkeypatch):
    a = shadow(tmp_path / "a", monkeypatch, trends=False, models=stub_models())
    (tmp_path / "b").mkdir()
    b = shadow(tmp_path / "b", monkeypatch, trends=True, models=stub_models())
    b.trends.every_ms = 5_000                                 # write often, so every read happens many times
    snaps = []
    write = b.trends.write
    b.trends.write = lambda snap: (snaps.append(snap), write(snap))
    stream(a)
    end = stream(b)
    ra, rb = books(a), books(b)
    assert len(ra["closed"]) > 50 and ra["counts"]["signals"] > 50   # the stream made the books trade
    for k in ra:
        assert ra[k] == rb[k], k
    assert len(snaps) > 500 and b.trends.errors == 0
    entries = [e for s in snaps for lst in s["lists"].values() for e in lst]
    assert any(e["p_3x"] is not None for e in entries)        # every model was read along the way
    assert any(e["p_win"] is not None and e["p_rug"] is not None for e in entries)
    assert any(e["migrated"] and e["p_3x"] is None for e in entries)
    assert any(e["progress"] is not None and e["p_win"] is None for e in entries)
    snap = json.loads((tmp_path / "b" / "trends.json").read_text(encoding="utf-8"))
    assert snap["t"] <= end and snap["models"] == {"win": True, "rug": True, "p3x": True}


def test_the_shadow_writes_the_file_on_its_tick_and_never_without_asking(tmp_path, monkeypatch):
    sh = shadow(tmp_path, monkeypatch)
    f = Feed(sh)
    f.create(T0, key(1), key(2))
    f.trade(T0 + 1_000, key(1), key(3), SOL)
    sh.tick(T0 + 2_000)
    snap = json.loads((tmp_path / "trends.json").read_text(encoding="utf-8"))
    assert [e["mint"] for e in snap["lists"]["hot"]] == [key(1)] and snap["note"] == TR.NOTE
    assert set(snap["lists"]) == {"hot", "migrating", "fresh"} and snap["sol_usd"] == 200.0
    (tmp_path / "trends.json").unlink()
    sh.tick(T0 + 5_000)                                       # not due yet
    assert not (tmp_path / "trends.json").exists()
    sh.tick(T0 + 2_000 + TR.WRITE_S * 1000)
    assert (tmp_path / "trends.json").exists()
    plain = live.Shadow("A_all_x1", models=None, alerts=False, now_ms=T0)
    assert plain.trends is None
