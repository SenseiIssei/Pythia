"""DexScreener archive (D4): rows from recorded answers, the age schedule, the shared budget and the
429 backoff, one run end to end (discovery, batching, orders, links, storage), compaction and
retention, the health check, the derived tables (point in time) and the first study's arithmetic.
Recorded answers are in tests/fixtures/dexscreener (addresses and links replaced). No network.

Run from research/lab:  python -m pytest tests/test_dexscreener.py
"""

from __future__ import annotations

import copy
import inspect
import io
import json
import urllib.error
import urllib.parse
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from lab.collect import dexscreener as ds
from lab.collect import dexscreener_derived as dd
from lab.experiments import dexscreener_d4 as st

FIX = Path(__file__).parent / "fixtures" / "dexscreener"
NOW = 1_793_081_500_000
M, H, D = ds.MIN_MS, ds.HOUR_MS, ds.DAY_MS
CFG = {"chains": ["solana"], "search": {"solana": ["pumpswap", "raydium"]}, "liq_floor_usd": 1000.0,
       "dead_drop_days": 30, "new_pair_max_age_h": 24.0, "retention_days": 0, "budget_gb": 20.0}


def fx(name: str):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("no network in tests")
    monkeypatch.setattr(ds.urllib.request, "urlopen", refuse)


def mk_pair(token: str, pair: str, created: int, liq: float | None = 20_000.0, price: float = 0.001,
            dex: str = "pumpswap", trades_h1: int = 50, boosts: int = 0, profile: bool = False) -> dict:
    p = copy.deepcopy(fx("tokens.json")[1])
    p.update({"pairAddress": pair, "dexId": dex, "pairCreatedAt": created, "priceUsd": str(price),
              "priceNative": str(price / 100), "fdv": price * 1e9, "marketCap": price * 1e9,
              "boosts": {"active": boosts}})
    p["baseToken"] = {"address": token, "name": token[:5], "symbol": token[:4]}
    p["liquidity"] = {"usd": liq, "base": 1.0, "quote": 1.0} if liq is not None else None
    if liq is None:
        p.pop("liquidity")
    p["txns"]["h1"] = {"buys": trades_h1, "sells": trades_h1}
    p["txns"]["h24"] = {"buys": trades_h1 + 1, "sells": trades_h1 + 1}
    if not profile:
        p.pop("info", None)
    return p


class Feed:
    """DexScreener answers by path; tokens answered from `pairs` (token -> list of pair dicts)."""

    def __init__(self):
        self.urls: list[str] = []
        self.pairs: dict[str, list[dict]] = {}
        self.lists = {"/token-profiles/latest/v1": fx("profiles_latest.json"),
                      "/token-boosts/latest/v1": fx("boosts_latest.json"),
                      "/token-boosts/top/v1": fx("boosts_top.json"),
                      "/community-takeovers/latest/v1": [], "/ads/latest/v1": fx("ads_latest.json")}
        self.search = fx("search.json")
        self.orders = fx("orders.json")

    def __call__(self, url: str):
        self.urls.append(url)
        u = urllib.parse.urlsplit(url)
        if u.path in self.lists:
            return copy.deepcopy(self.lists[u.path])
        if u.path.startswith("/latest/dex/search"):
            return copy.deepcopy(self.search)
        if u.path.startswith("/orders/v1/"):
            return copy.deepcopy(self.orders)
        if u.path.startswith("/tokens/v1/"):
            toks = urllib.parse.unquote(u.path.split("/")[-1]).split(",")
            assert len(toks) <= ds.BATCH
            return [copy.deepcopy(p) for t in toks for p in self.pairs.get(t, [])]
        raise AssertionError(url)

    def token_calls(self) -> list[str]:
        return [u for u in self.urls if "/tokens/v1/" in u]


def feed_with_fixture_tokens() -> Feed:
    f = Feed()
    for p in fx("tokens.json"):
        f.pairs.setdefault(p["baseToken"]["address"], []).append(p)
    return f


# ---------------------------------------------------------------- settings, rows, schedule

def test_config_is_solana_only_by_default_and_env_turns_chains_on(tmp_path):
    cfg = ds.config(env={})
    assert cfg["chains"] == ["solana"]
    assert {"raydium", "meteora", "orca", "pumpswap"} <= set(cfg["search"]["solana"])
    cfg = ds.config(env={"PYTHIA_DEXSCREENER_CHAINS": "solana, Base,bsc", "PYTHIA_DEXSCREENER_RETENTION_DAYS": "90"})
    assert cfg["chains"] == ["solana", "base", "bsc"] and cfg["retention_days"] == 90.0
    assert ds.config(tmp_path / "missing.json", env={})["chains"] == ["solana"]


def test_snapshot_row_from_recorded_answers():
    curve, swap = fx("tokens.json")
    r = ds.snapshot_row(curve, NOW)
    assert r["collected_at"] == NOW and r["dex"] == "pumpfun" and r["liq_usd"] is None
    assert r["boosts_active"] == 10 and r["has_profile"] and r["social_types"] == "tiktok,twitter"
    assert r["buys_h1"] == 1211 and r["sells_m5"] == 46 and r["vol_m5"] == pytest.approx(4624.05)
    assert r["pair_created_at"] == 1793078055000 and r["quote_symbol"] == "SOL" and r["links_hash"]
    assert json.loads(r["_socials"])[0]["type"] == "twitter"
    s = ds.snapshot_row(swap, NOW)
    assert s["liq_usd"] > 0 and s["fdv"] and s["mcap"]
    df = ds.frame([r, s], ds.SNAP_SCHEMA)
    assert df.height == 2 and "_socials" not in df.columns and df["collected_at"].to_list() == [NOW, NOW]


def test_schedule_thins_out_with_age():
    assert ds.interval_ms(30 * M) == 2 * M
    assert ds.interval_ms(5 * H) == 15 * M
    assert ds.interval_ms(3 * D) == H
    assert ds.interval_ms(10 * D) == D
    p = {"status": "active", "created_at": NOW - 20 * M, "last_snap": NOW - 2 * M + 20_000}
    assert ds.pair_due(p, NOW)                                  # within the slack of a 2-minute cron
    p["last_snap"] = NOW - 60_000
    assert not ds.pair_due(p, NOW)
    assert not ds.pair_due({"status": "dropped", "last_snap": 0}, NOW)
    assert ds.pair_due({"status": "dead", "created_at": NOW - 9 * D, "last_snap": NOW - D}, NOW)


def test_alive_rug_dead_and_dropped():
    assert ds.alive({"liq_usd": 1500.0}, 1000) and not ds.alive({"liq_usd": 500.0}, 1000)
    assert ds.alive({"liq_usd": None, "buys_h24": 3, "sells_h24": 0}, 1000)      # a curve that trades
    assert not ds.alive({"liq_usd": None, "buys_h24": 0, "sells_h24": 0}, 1000)
    pairs: dict = {}
    base = {"chain": "solana", "pair": "P", "token": "T", "pair_created_at": NOW - H, "buys_h24": 5, "sells_h24": 5}
    ds.update_pair(pairs, {**base, "liq_usd": 50_000.0}, NOW, 1000, 30)
    p = ds.update_pair(pairs, {**base, "liq_usd": 3_000.0}, NOW + M, 1000, 30)
    assert p["rugged"] and p["rug_at"] == NOW + M and p["status"] == "active" and p["max_liq"] == 50_000.0
    p = ds.update_pair(pairs, {**base, "liq_usd": 10.0}, NOW + H, 1000, 30)
    assert p["status"] == "dead" and p["dead_since"] == NOW + H
    p = ds.update_pair(pairs, {**base, "liq_usd": 10.0}, NOW + H + 31 * D, 1000, 30)
    assert p["status"] == "dropped" and not ds.pair_due(p, NOW + 40 * D)
    q = {"chain": "solana", "pair": "Q", "token": "T", "status": "active", "misses": 0}
    for i in range(3):
        ds.miss_pair(q, NOW + i, 30)
    assert q["status"] == "dead" and q["misses"] == 3


# ---------------------------------------------------------------- budget and backoff

class Clock:
    def __init__(self):
        self.t = 0.0
        self.slept: list[float] = []

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.slept.append(s)
        self.t += s


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_http_spaces_calls_per_group_and_keeps_to_its_budget():
    c = Clock()
    http = ds.Http(sleep=c.sleep, clock=c, opener=lambda req, timeout: Resp(b"[]"))
    assert ds.group_of(f"{ds.DEX}/tokens/v1/solana/a,b") == ds.FAST
    assert ds.group_of(f"{ds.DEX}/latest/dex/search?q=x") == ds.FAST
    assert ds.group_of(f"{ds.DEX}/token-boosts/top/v1") == ds.SLOW
    assert ds.group_of(f"{ds.DEX}/orders/v1/solana/x") == ds.SLOW
    http(f"{ds.DEX}/token-boosts/top/v1")
    http(f"{ds.DEX}/token-profiles/latest/v1")
    assert c.slept == [pytest.approx(ds.SLOW_GAP_S)]
    http(f"{ds.DEX}/tokens/v1/solana/a")                        # the other group is not held back
    assert len(c.slept) == 1
    assert ds.SLOW_GAP_S >= 60 / 60 * 2 and ds.FAST_GAP_S >= 60 / 300 * 2     # half the published limits or less
    http.budgets[ds.FAST] = 2
    http(f"{ds.DEX}/tokens/v1/solana/b")
    with pytest.raises(ds.RateLimited):
        http(f"{ds.DEX}/tokens/v1/solana/c")
    assert http.left(ds.FAST) == 0 and http.left(ds.SLOW) > 0
    c.t = ds.RUN_S + 1
    assert http.left(ds.SLOW) == 0
    with pytest.raises(ds.RateLimited):
        http(f"{ds.DEX}/token-boosts/top/v1")


def test_429_stops_the_group_and_backs_off_across_runs():
    c = Clock()

    def opener(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", {}, None)

    http = ds.Http(sleep=c.sleep, clock=c, opener=opener)
    with pytest.raises(ds.RateLimited):
        http(f"{ds.DEX}/tokens/v1/solana/a")
    assert http.limited == {ds.FAST}
    with pytest.raises(ds.RateLimited):
        http(f"{ds.DEX}/tokens/v1/solana/b")
    st1 = {"backoff": ds.backoff_after({}, {ds.FAST}, NOW)}
    assert st1["backoff"][ds.FAST]["secs"] == ds.BACKOFF_MIN_S
    assert ds.blocked_groups(st1, NOW + 60_000) == {ds.FAST}
    st2 = {"backoff": ds.backoff_after(st1, {ds.FAST}, NOW + 3 * M)}
    assert st2["backoff"][ds.FAST]["secs"] == 2 * ds.BACKOFF_MIN_S
    big = {"backoff": {ds.FAST: {"secs": ds.BACKOFF_MAX_S, "until": 0}}}
    assert ds.backoff_after(big, {ds.FAST}, NOW)[ds.FAST]["secs"] == ds.BACKOFF_MAX_S
    assert ds.backoff_after(st2, set(), NOW + H) == {}           # a clean run after the pause resets it
    blocked = ds.Http(blocked={ds.FAST}, sleep=c.sleep, clock=c, opener=lambda r, timeout: Resp(b"[]"))
    assert blocked.left(ds.FAST) == 0
    with pytest.raises(ds.RateLimited):
        blocked(f"{ds.DEX}/tokens/v1/solana/a")


# ---------------------------------------------------------------- one run

def test_run_end_to_end_from_recorded_answers(tmp_path):
    f = feed_with_fixture_tokens()
    s = ds.run(get=f, now=NOW, cfg=CFG, root=tmp_path, data_root=tmp_path)
    b = ds.base(tmp_path)
    day = ds.day_of(NOW)
    snaps = pl.read_parquet(next((b / "snapshots" / "chain=solana" / f"date={day}").glob("*.parquet")))
    assert set(snaps["collected_at"]) == {NOW} and snaps["chain"].unique().to_list() == ["solana"]
    assert set(snaps["dex"]) >= {"pumpfun", "pumpswap"}
    disc = pl.read_parquet(next((b / "discovery" / "chain=solana" / f"date={day}").glob("*.parquet")))
    assert set(disc["source"]) >= {"profile", "boost_latest", "boost_top", "search:pumpswap"}
    assert not (b / "discovery" / "chain=base").exists() and not (b / "discovery" / "chain=bsc").exists()
    # the search answer's old pair (created long before) is not added, the young one is
    young = [p for p in f.search["pairs"] if NOW - p["pairCreatedAt"] < 24 * H]
    assert set(disc.filter(pl.col("source") == "search:pumpswap")["pair"]) == {p["pairAddress"] for p in young}
    pairs = pl.read_parquet(b / "pairs.parquet")
    assert {"first_seen", "last_seen", "status", "rugged"} <= set(pairs.columns)
    assert pairs.filter(pl.col("pair").is_in(snaps["pair"].to_list())).height == snaps["pair"].n_unique()
    orders = pl.read_parquet(next((b / "orders" / "chain=solana" / f"date={day}").glob("*.parquet")))
    assert set(orders["kind"]) == {"order", "boost"} and orders["paid_at"].min() > 0
    assert sum("/orders/v1/" in u for u in f.urls) <= ds.ORDERS_PER_RUN
    links = pl.read_parquet(next((b / "links" / "chain=solana" / f"date={day}").glob("*.parquet")))
    assert links.height >= 1 and json.loads(links["socials"][0])
    assert s["snapshots"] == snaps.height and s["errors"] == []
    state = ds.load_state(tmp_path)
    assert state["last_snapshot"] == NOW and state["search_turn"] == 0       # two words, both each run
    # takeovers and ads only every 5th run; the first run is run 1
    assert not any("/ads/latest" in u for u in f.urls)
    # nothing new: the links are not stored twice
    s2 = ds.run(get=f, now=NOW + 2 * M, cfg=CFG, root=tmp_path, data_root=tmp_path)
    assert s2["links_rows"] == 0 and s2["snapshots"] > 0


def test_tracking_batches_30_tokens_and_puts_the_youngest_first(tmp_path):
    f = Feed()
    f.lists = {k: [] for k in f.lists}
    f.search = {"pairs": []}
    tokens = {}
    for i in range(65):
        t = f"T{i:03d}".ljust(40, "1") + "pump"
        f.pairs[t] = [mk_pair(t, f"P{i:03d}".ljust(44, "1"), NOW - (i + 1) * 30_000)]
        ds.note_token(tokens, "solana", t, "profile", NOW)
    ds.save_table("tokens", tokens, ds.TOKEN_SCHEMA, tmp_path)
    ds.run(get=f, now=NOW, cfg=CFG, root=tmp_path, data_root=tmp_path)
    calls = f.token_calls()
    assert len(calls) == 3
    assert [len(urllib.parse.unquote(c.split("/")[-1]).split(",")) for c in calls] == [30, 30, 5]
    # two minutes later every pair is under an hour old, so all are due again; 20 minutes old pairs
    # are not due one minute later
    f.urls.clear()
    ds.run(get=f, now=NOW + 2 * M, cfg=CFG, root=tmp_path, data_root=tmp_path)
    assert len(f.token_calls()) == 3
    f.urls.clear()
    ds.run(get=f, now=NOW + 2 * M + 30_000, cfg=CFG, root=tmp_path, data_root=tmp_path)
    assert f.token_calls() == []
    # a pair over a day old is due every hour only, and with a short budget the young ones go first
    pairs = ds.load_table("pairs", ("chain", "pair"), tmp_path)
    old = next(iter(pairs.values()))
    old["created_at"] = NOW - 3 * D
    young = list(pairs.values())[1]
    due = ds.due_tokens(pairs, {}, NOW + 20 * M, ["solana"])
    assert due[0] == ("solana", young["token"]) or due.index(("solana", young["token"])) < due.index(("solana", old["token"]))


def test_a_token_without_pairs_is_given_up_after_three_tries(tmp_path):
    f = Feed()
    f.lists = {k: [] for k in f.lists}
    f.search = {"pairs": []}
    tokens = {}
    ds.note_token(tokens, "solana", "Ghost".ljust(40, "1") + "pump", "profile", NOW)
    ds.save_table("tokens", tokens, ds.TOKEN_SCHEMA, tmp_path)
    for i in range(5):
        ds.run(get=f, now=NOW + i * 2 * M, cfg=CFG, root=tmp_path, data_root=tmp_path)
    assert len(f.token_calls()) == ds.PENDING_TRIES


def test_pump_fun_migrations_come_from_the_real_time_collector(tmp_path):
    (tmp_path / "pumpfun_rt").mkdir()
    tok, old = "Mig1".ljust(40, "1") + "pump", "Mig2".ljust(40, "1") + "pump"
    (tmp_path / "pumpfun_rt" / "pools.json").write_text(json.dumps(
        {"PoolA".ljust(44, "1"): [tok, NOW - 10 * M], "PoolB".ljust(44, "1"): [old, NOW - 5 * H]}))
    tokens: dict = {}
    rows = ds.discover_migrations(tokens, NOW, tmp_path)
    assert [r["token"] for r in rows] == [tok] and rows[0]["source"] == "pumpfun_migration"
    assert ds.discover_migrations(tokens, NOW + M, tmp_path) == []        # once
    assert ds.discover_migrations({}, NOW, tmp_path / "nowhere") == []


def test_dry_run_writes_nothing(tmp_path):
    s = ds.run(get=feed_with_fixture_tokens(), now=NOW, cfg=CFG, root=tmp_path, data_root=tmp_path, dry_run=True)
    assert s["snapshots"] > 0 and not ds.base(tmp_path).exists()


# ---------------------------------------------------------------- storage, retention, health

def test_compact_merges_finished_days_and_prune_keeps_to_retention_and_budget(tmp_path):
    rows = [ds.snapshot_row(p, NOW - 2 * D) for p in fx("tokens.json")]
    ds.write_parts("snapshots", rows, ds.SNAP_SCHEMA, NOW - 2 * D, tmp_path)
    ds.write_parts("snapshots", rows, ds.SNAP_SCHEMA, NOW - 2 * D + M, tmp_path)
    ds.write_parts("snapshots", rows, ds.SNAP_SCHEMA, NOW, tmp_path)
    assert ds.compact(NOW, tmp_path) == 1
    old = ds.base(tmp_path) / "snapshots" / "chain=solana" / f"date={ds.day_of(NOW - 2 * D)}"
    assert [f.name for f in old.glob("*.parquet")] == ["day.parquet"]
    assert pl.read_parquet(old / "day.parquet").height == 4
    today = ds.base(tmp_path) / "snapshots" / "chain=solana" / f"date={ds.day_of(NOW)}"
    assert len(list(today.glob("*.parquet"))) == 1                         # today is left alone
    assert ds.prune({"retention_days": 0, "budget_gb": 20}, NOW, tmp_path) == []
    assert ds.prune({"retention_days": 1, "budget_gb": 0}, NOW, tmp_path) == [ds.day_of(NOW - 2 * D)]
    assert not old.exists() and today.exists()
    ds.write_parts("snapshots", rows, ds.SNAP_SCHEMA, NOW - D, tmp_path)
    assert ds.prune({"retention_days": 0, "budget_gb": 1e-9}, NOW, tmp_path) == [ds.day_of(NOW - D)]
    assert today.exists()                                                  # never today


def test_health_is_red_when_the_collector_is_stale(tmp_path):
    ok, msg = ds.check(NOW, root=tmp_path)
    assert not ok and "no run" in msg
    ds.run(get=feed_with_fixture_tokens(), now=NOW, cfg=CFG, root=tmp_path, data_root=tmp_path)
    ok, msg = ds.check(NOW + 5 * M, root=tmp_path)
    assert ok and msg.startswith("DexScreener archive ok")
    ok, msg = ds.check(NOW + 13 * M, root=tmp_path)
    assert not ok and "last run 13 min ago" in msg
    st_ = ds.load_state(tmp_path)
    st_["last"]["t"] = NOW + 20 * M                                        # runs, but writes nothing
    ds.save_state(st_, tmp_path)
    ok, msg = ds.check(NOW + 21 * M, root=tmp_path)
    assert not ok and "last snapshot" in msg


def test_main_health_exit_code(tmp_path, monkeypatch):
    monkeypatch.setattr(ds, "WRITE_ROOT", tmp_path)
    assert ds.main(["--health"]) == 1


# ---------------------------------------------------------------- derived tables

def write_history(tmp_path, scramble_after: int | None = None, seed: int = 0):
    """Three pairs: A steady for 26 h, B rugged at 3 h and gone, C found at 5 h; plus a migrated
    token with a PumpSwap and a Meteora pool. Snapshots on the collector's schedule."""
    rng = np.random.default_rng(seed)
    t0 = NOW - 2 * D
    pairs: dict = {}
    def snap(token, pair, created, at, liq, price, dex="pumpswap", boosts=0, profile=False):
        p = mk_pair(token, pair, created, liq, price, dex, boosts=boosts, profile=profile)
        if scramble_after is not None and at - created > scramble_after:
            p["priceUsd"] = str(rng.uniform(1e-6, 1)); p["liquidity"]["usd"] = float(rng.uniform(0, 1e6))
        r = ds.snapshot_row(p, at)
        ds.update_pair(pairs, r, at, 1000, 30)
        return r
    rows = []
    ages = list(range(0, H, 2 * M)) + list(range(H, D + 3 * H, 15 * M))
    A, B, C, MIG = ("TokA".ljust(40, "1") + "pump", "TokB".ljust(40, "1") + "pump", "TokC".ljust(40, "1") + "pump",
                    "TokM".ljust(40, "1") + "pump")
    for a in ages:
        rows.append(snap(A, "PairA".ljust(44, "1"), t0, t0 + a, 30_000.0, 0.001 * (3 if a > 20 * H else 1),
                         boosts=10, profile=True))
        if a <= 3 * H:
            rows.append(snap(B, "PairB".ljust(44, "1"), t0, t0 + a, 20_000.0 if a < 3 * H else 100.0, 0.001))
        if a >= 5 * H:
            rows.append(snap(C, "PairC".ljust(44, "1"), t0, t0 + a, 5_000.0, 0.002))
        rows.append(snap(MIG, "PairM1".ljust(44, "1"), t0, t0 + a, 40_000.0, 0.01))
        if a >= 2 * H:
            rows.append(snap(MIG, "PairM2".ljust(44, "1"), t0 + 2 * H, t0 + a, 10_000.0, 0.01, dex="meteora"))
    df = ds.frame(rows, ds.SNAP_SCHEMA)
    for (day,), part in df.with_columns(pl.from_epoch("collected_at", time_unit="ms").dt.strftime("%Y-%m-%d")
                                        .alias("_d")).group_by(["_d"]):
        p = ds.base(tmp_path) / "snapshots" / "chain=solana" / f"date={day}" / "day.parquet"
        ds._atomic_parquet(part.drop("_d"), p)
    ds.save_table("pairs", pairs, ds.PAIR_SCHEMA, tmp_path)
    ds.write_parts("discovery", [{"collected_at": t0, "chain": "solana", "token": MIG, "source": "pumpfun_migration"}],
                   ds.DISC_SCHEMA, t0, tmp_path)
    ds.write_parts("orders", [{"collected_at": t0, "chain": "solana", "token": A, "kind": "order",
                               "type": "tokenProfile", "status": "approved", "paid_at": t0 + 10 * M}],
                   ds.ORDER_SCHEMA, t0, tmp_path)
    return {"A": A, "B": B, "C": C, "M": MIG}


def test_outcomes_survival_paid_and_migration(tmp_path):
    tok = write_history(tmp_path)
    out = dd.build(tmp_path, NOW, 1000.0, write=True)
    o = {r["token"] + r["dex"]: r for r in out["outcomes"].to_dicts()}
    a, b, c = o[tok["A"] + "pumpswap"], o[tok["B"] + "pumpswap"], o[tok["C"] + "pumpswap"]
    assert a["trading_1h"] and a["trading_1d"] and a["trading_7d"] is None          # not 7 days old yet
    assert a["ratio_24h"] == pytest.approx(3.0) and a["paid_1h"] == "both" and a["launchpad"] == "pump.fun"
    assert b["trading_1h"] and b["trading_1d"] is False and b["rugged"] and b["rug_24h"]
    assert c["trading_1h"] is None and c["trading_1d"] is not None                    # found at 5 h
    assert c["f_liq"] is None                                                         # no 1 h snapshot
    sv = out["survival"].filter(pl.col("dex") == "all").to_dicts()[0]
    assert sv["pairs"] == 5 and sv["rugged"] == 1 and sv["known_1h"] == 4
    paid = {r["paid_1h"]: r for r in out["paid"].to_dicts()}
    assert paid["both"]["x2_24h"] == 1 and paid["none"]["rug_24h"] == 1
    mig = out["migration"].filter(pl.col("has_other_pool")).to_dicts()
    assert out["migration"].height == 4 and len(mig) == 1 and mig[0]["token"] == tok["M"]
    assert mig[0]["has_other_pool"] and mig[0]["first_other_dex"] == "meteora"
    assert mig[0]["other_after_min"] == pytest.approx(120.0) and mig[0]["pumpswap_liq_share"] == pytest.approx(0.8)
    assert (ds.base(tmp_path) / "derived" / "outcomes.parquet").exists()


def test_features_at_1h_are_point_in_time(tmp_path):
    write_history(tmp_path / "a")
    write_history(tmp_path / "b", scramble_after=90 * M, seed=7)
    fa = dd.build(tmp_path / "a", NOW, 1000.0, write=False)["outcomes"]
    fb = dd.build(tmp_path / "b", NOW, 1000.0, write=False)["outcomes"]
    cols = ["chain", "pair"] + [c for c in fa.columns if c.startswith("f_")] + ["price_1h", "trading_1h"]
    assert fa.select(cols).sort("pair").equals(fb.select(cols).sort("pair"))


# ---------------------------------------------------------------- the study

def test_net_multiple_costs_at_40_eur():
    flat = st.net_multiple(0.001, 50_000, 0.001, 50_000, "pumpswap", 150.0)
    assert 0.9 < flat < 0.97                                     # 2.5 % fee, 2 % slippage, impact, network fees
    assert st.net_multiple(0.001, 50_000, 0.001, 50_000, "raydium", 150.0) > flat
    thin = st.net_multiple(0.001, 2_000, 0.001, 2_000, "pumpswap", 150.0)
    assert thin < flat - 0.03                                    # impact against a thin pool
    assert st.net_multiple(0.001, 50_000, 0.002, 50_000, "pumpswap", 150.0) == pytest.approx(2 * flat, rel=0.02)
    assert st.net_multiple(0.001, 50_000, None, None, "pumpswap", rug=True) == 0.0
    assert st.net_multiple(0.001, 50_000, None, None, "pumpswap") is None
    assert st.net_multiple(0.001, None, 0.001, None, "pumpfun", 150.0) < 1


def test_auc_and_prediction_with_a_bar():
    assert st.auc(np.array([1.0, 2, 3, 4]), np.array([0, 0, 1, 1])) == 1.0
    assert st.auc(np.array([1.0, 2]), np.array([1, 1])) is None
    rng = np.random.default_rng(1)
    n = 200
    x = rng.normal(size=n)
    d = pl.DataFrame({"first_ts": np.arange(n), "x_log_liq": x, "x_boost": rng.normal(size=n),
                      "good": x + 0.3 * rng.normal(size=n) > 0, "m": np.where(x > 0, 1.5, 0.5),
                      "win": x > 0})
    pred = st.predict(d, ("good",))
    rows = {r["feature"]: r for r in pred["rows"]}
    assert pred["trials"] == 2 and rows["x_log_liq"]["passes"] and not rows["x_boost"]["passes"]
    b = st.rule_book(d, st.predict(d, ("win",)), "m")
    assert b["feature"] == "x_log_liq" and b["mean_pick"] > b["mean_all"]


def trending_rows(tmp_path):
    """Two boosted tokens listed from age 0.5 h: one doubles and stays, one leaves the list at 3 h."""
    rows = []
    t0 = NOW - 3 * D
    for k in range(0, 112):
        ts = t0 + k * 15 * M
        age = 0.5 + k * 0.25
        rows.append({"ts_ms": ts, "kind": "dex", "source": "boosted", "chain": "solana", "address": "Up".ljust(40, "1"),
                     "dex": "pumpswap", "pair_url": "u1", "price_usd": 0.001 * (2.5 if age > 12 else 1),
                     "liquidity_usd": 50_000.0, "fdv": 1e6, "age_h": age, "change_h1": 5.0, "volume_h24": 1e5,
                     "buys_h24": 100.0, "sells_h24": 80.0, "boost": 500.0})
        if age <= 3:
            rows.append({"ts_ms": ts, "kind": "dex", "source": "boosted", "chain": "solana", "address": "Gone".ljust(40, "1"),
                         "dex": "pumpswap", "pair_url": "u2", "price_usd": 0.001, "liquidity_usd": 20_000.0, "fdv": 5e5,
                         "age_h": age, "change_h1": -5.0, "volume_h24": 1e4, "buys_h24": 10.0, "sells_h24": 10.0,
                         "boost": 50.0})
    d = tmp_path / "trending" / "snapshots" / f"date={ds.day_of(t0)}"
    d.mkdir(parents=True)
    pl.DataFrame(rows).write_parquet(d / "000000.parquet")


def test_trending_tokens_from_the_snapshots(tmp_path):
    trending_rows(tmp_path)
    td = st.trending_tokens(st.trending_frame(tmp_path), 1000.0)
    r = {x["address"][:4]: x for x in td.to_dicts()}
    assert r["Up11"]["seen24"] and r["Up11"]["alive24"] and r["Up11"]["p24"] == pytest.approx(0.0025)
    assert not r["Gone"]["seen24"] and r["Gone"]["p_last"] == pytest.approx(0.001)
    lines, td2 = st.trending_section(td, 1000.0, 150.0)
    assert any("2 boosted tokens" in x for x in lines)
    up = td2.filter(pl.col("address").str.starts_with("Up")).to_dicts()[0]
    assert up["x2"] and up["m24"] > 2


def test_report_end_to_end(tmp_path, monkeypatch):
    write_history(tmp_path)
    trending_rows(tmp_path)
    monkeypatch.setattr(ds, "config", lambda *a, **k: dict(CFG))
    text = st.report(tmp_path, tmp_path, NOW)
    for head in ("## 1. The archive", "## 2. Top boosted", "## 3. Does a feature"):
        assert head in text
    assert "pump.fun coins after migration: 4 with a PumpSwap pool in the archive, 1 of them also on another dex (meteora 1)" in text and chr(0x2014) not in text


def test_nothing_here_can_touch_a_wallet_or_send_a_transaction():
    for mod in (ds, dd, st):
        src = inspect.getsource(mod).lower()
        for word in ("sendtransaction", "signtransaction", "keypair", "private_key", "privatekey", "secret_key",
                     "mnemonic", "seed phrase", "solana.rpc", "solders", "frontend-api"):
            assert word not in src, (mod.__name__, word)


def test_a_search_pair_is_not_fetched_twice_in_its_run_and_a_profile_asks_for_orders(tmp_path):
    f = Feed()
    f.lists = {k: [] for k in f.lists}
    young = [p for p in f.search["pairs"] if NOW - p["pairCreatedAt"] < 24 * H]
    f.pairs = {p["baseToken"]["address"]: [p] for p in young}
    s = ds.run(get=f, now=NOW, cfg=CFG, root=tmp_path, data_root=tmp_path)
    assert f.token_calls() == [] and s["snapshots"] == len(young)
    tokens = ds.load_table("tokens", ("chain", "token"), tmp_path)
    assert all(t["paid"] for t in tokens.values())               # the recorded pair has a profile
    ds.run(get=f, now=NOW + 2 * M, cfg=CFG, root=tmp_path, data_root=tmp_path)
    assert any("/orders/v1/" in u for u in f.urls)
