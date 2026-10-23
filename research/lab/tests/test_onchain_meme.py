"""The meme module of our own wallet (lab.onchain: meme_safety, meme, meme_live, the [meme] gate in live_gate): the
per-coin safety check against recorded account data (mint and freeze authority, Token-2022, transfer fee, holders,
liquidity, age, block list, creator block), the rules on synthetic data, the paper book through quotes, the proof,
the meme gate and the locked live path end to end on a fake chain. No network, no key of anyone: every address
here is a hash of a made-up name.

Run from research/lab:  python -m pytest tests/test_onchain_meme.py
"""

from __future__ import annotations

import struct

import pytest

import test_onchain_live as TL
from lab.onchain import guard as G
from lab.onchain import live_exec as LX
from lab.onchain import live_gate as LG
from lab.onchain import live_service as SV
from lab.onchain import meme as ME
from lab.onchain import meme_live as ML
from lab.onchain import meme_safety as MS
from lab.onchain.jupiter import QuoteError
from lab.pumpfun_rt import txbuild as X
from lab.pumpfun_rt.events import WSOL

A = TL.A
MEME = A("a meme coin")
NOW = 1_792_712_000_000
H = 3_600_000


def named(prefix: str, on: bool, n: int = 1) -> list[str]:
    """Made-up addresses on the ed25519 curve (wallets) or off it (program accounts)."""
    out, i = [], 0
    while len(out) < n:
        a = A(f"{prefix} {i}")
        if X.on_curve(X.key(a)) == on:
            out.append(a)
        i += 1
    return out


WALLETS = named("holder", True, 12)
VAULT = named("pool vault owner", False)[0]
POOL_ADDR = A("the pool")
DEV = A("the dev")


# ---------------------------------------------------------------- recorded account data

def mint_data(mint_auth=None, freeze=None, supply=10 ** 15, decimals=6) -> bytes:
    opt = lambda k: (b"\x01\x00\x00\x00" + X.key(k)) if k else b"\x00" * 36
    return opt(mint_auth) + struct.pack("<QBB", supply, decimals, 1) + opt(freeze)


def t22_data(exts=((1, 108),), **kw) -> bytes:
    body = mint_data(**kw) + b"\x00" * (165 - 82) + b"\x01"
    for t, n in exts:
        body += struct.pack("<HH", t, n) + b"\x00" * n
    return body


def meta_data(update=DEV, creators=()) -> bytes:
    s = lambda v: struct.pack("<I", len(v)) + v
    out = b"\x04" + X.key(update) + X.key(MEME) + s(b"Meme") + s(b"MEME") + s(b"https://x") + struct.pack("<H", 0)
    if creators:
        out += b"\x01" + struct.pack("<I", len(creators)) + b"".join(X.key(c) + b"\x01\x64" for c in creators)
    else:
        out += b"\x00"
    return out + b"\x00\x01"


def token_acc(owner: str, amount: int) -> bytes:
    return TL.tok_data(MEME, owner, amount)


def pair(liq=50_000.0, dex="raydium", born=NOW - 2 * H, price=0.001, h1=6.0, h24=25.0, base=MEME) -> dict:
    return {"chainId": "solana", "dexId": dex, "pairAddress": POOL_ADDR, "baseToken": {"address": base, "symbol": "MEME"},
            "quoteToken": {"address": WSOL}, "liquidity": {"usd": liq}, "priceUsd": str(price),
            "priceChange": {"h1": h1, "h24": h24}, "pairCreatedAt": born}


def holders(shares=(0.02,) * 10, pool=0.4, burned=0.0) -> tuple[list, dict]:
    """getTokenLargestAccounts rows and their owners: the pool's vault, a burn, then wallets."""
    supply = 10 ** 15
    rows, owners = [("vault", int(pool * supply))], {"vault": VAULT}
    if burned:
        rows.append(("burn", int(burned * supply)))
        owners["burn"] = "1nc1nerator11111111111111111111111111111111"
    for i, s in enumerate(shares):
        rows.append((f"h{i}", int(s * supply)))
        owners[f"h{i}"] = WALLETS[i]
    return rows, owners


def judge(acc=None, meta=None, largest_owners=None, pairs=None, jup=None, blocked=(set(), set()), exceptions=(),
          now=NOW):
    acc = acc if acc is not None else G.Account(1, X.TOKEN, mint_data())
    largest, owners = largest_owners or holders()
    return MS.judge(MEME, acc, meta, largest, owners, [pair()] if pairs is None else pairs, jup, blocked,
                    set(exceptions), now)


def test_a_clean_classic_coin_passes_with_its_facts():
    v = judge(meta=meta_data(), jup={"id": MEME, "tags": ["verified"], "organicScore": 91, "dev": DEV})
    assert v.ok and v.reasons == []
    assert v.facts["program"] == "token" and v.facts["decimals"] == 6 and v.facts["top10_share"] == pytest.approx(0.2)
    assert v.facts["holders"]["pools_left_out"] == 1 and v.facts["jupiter"]["verified"] is True
    assert v.facts["metadata"]["update_authority"] == DEV and v.facts["pool"]["liquidity_usd"] == 50_000


@pytest.mark.parametrize("make, why", [
    (lambda: judge(acc=G.Account(1, X.TOKEN, mint_data(mint_auth=DEV))), "mint authority"),
    (lambda: judge(acc=G.Account(1, X.TOKEN, mint_data(freeze=DEV))), "freeze authority"),
    (lambda: judge(acc=G.Account(1, X.TOKEN_2022, t22_data())), "Token-2022 mint (refused, as the guard does): transfer fee"),
    (lambda: judge(acc=G.Account(1, X.TOKEN_2022, t22_data(exts=((14, 64),)))), "transfer hook"),
    (lambda: judge(acc=G.Account(1, X.TOKEN_2022, t22_data(exts=((18, 64), (19, 90))))), "metadata pointer, token metadata"),
    (lambda: judge(acc=G.Account(1, X.SYSTEM, b"")), "not an SPL mint"),
    (lambda: MS.judge(MEME, None, None, [], {}, [pair()], None, (set(), set()), set(), NOW), "does not exist"),
    (lambda: judge(largest_owners=holders(shares=(0.05,) * 10)), "top 10 holders hold 50%"),
    (lambda: judge(pairs=[pair(liq=19_000)]), "holds 19,000 USD"),
    (lambda: judge(pairs=[pair(dex="pumpfun")]), "no pool on Raydium"),
    (lambda: judge(pairs=[pair(born=NOW - 60_000)]), "1 min old"),
    (lambda: judge(pairs=[pair(born=None)]), "age of its first pool is not known"),
    (lambda: judge(blocked=({MEME}, set())), "mint is on the owner's block list"),
    (lambda: judge(jup={"id": MEME, "dev": DEV}, blocked=(set(), {DEV})), "creator"),
    (lambda: judge(meta=meta_data(update=A("x"), creators=(DEV,)), blocked=(set(), {DEV})), "creator"),
    (lambda: MS.judge(MEME, G.Account(1, X.TOKEN, mint_data()), None, None, None, [pair()], None, (set(), set()),
                      set(), NOW), "largest holders could not be read"),
])
def test_the_safety_check_refuses_with_a_plain_reason(make, why):
    v = make()
    assert not v.ok and any(why in r for r in v.reasons), v.reasons


def test_burns_and_pools_are_left_out_and_the_exception_list_lifts_only_the_authorities():
    v = judge(largest_owners=holders(shares=(0.01,) * 10, pool=0.3, burned=0.5))
    assert v.ok and v.facts["top10_share"] == pytest.approx(0.1 / 0.5)       # supply outside the burn: half
    v = judge(largest_owners=holders(shares=(0.02,) * 10, pool=0.3, burned=0.5))
    assert not v.ok and "hold 40%" in v.reasons[0]
    acc = G.Account(1, X.TOKEN, mint_data(mint_auth=DEV, freeze=DEV))
    v = judge(acc=acc, exceptions={MEME})
    assert v.ok and "exception" in v.facts
    v = judge(acc=G.Account(1, X.TOKEN_2022, t22_data()), exceptions={MEME})
    assert not v.ok and "Token-2022" in v.reasons[0]
    v = judge(largest_owners=([], {}), jup={"id": MEME, "audit": {"topHoldersPercentage": 41.0}})
    assert not v.ok and v.facts["holders_from"] == "jupiter audit"


def test_the_block_list_reads_mints_and_creators(tmp_path):
    (tmp_path / "a.txt").write_text(f"{MEME}  # rugged\ncreator: {DEV}\n# comment\n")
    (tmp_path / "b.txt").write_text("creator:\n")
    assert MS.read_blocked([tmp_path / "a.txt", tmp_path / "b.txt", tmp_path / "none"]) == ({MEME}, {DEV})


class FakeRpc:
    def __init__(self, accounts: dict, largest=None, fail=False):
        self.acc, self.lg, self.fail, self.calls = accounts, largest, fail, []

    def call(self, method, params):
        self.calls.append(method)
        if self.fail:
            raise OSError("down")
        if method == "getMultipleAccounts":
            return {"value": [TL.b64acc(self.acc.get(k)) for k in params[0]]}
        if method == "getTokenLargestAccounts":
            if self.lg is None:
                raise OSError("rate limited")
            return {"value": [{"address": a, "amount": str(n)} for a, n in self.lg]}
        raise AssertionError(method)


class FakeJup:
    def __init__(self, tokens=(), quotes=None):
        self.tokens, self.quotes, self.asked = list(tokens), quotes or {}, []

    def get(self, path, params):
        self.asked.append(path)
        if path == "/tokens/v2/search":
            return [t for t in self.tokens if t["id"] == params["query"]]
        if path.startswith("/tokens/v2/top"):
            return self.tokens if "organic" in path else []
        raise QuoteError(path)

    def quote(self, in_mint, out_mint, amount, slippage_bps=50):
        f = self.quotes.get((in_mint, out_mint))
        if f is None:
            raise QuoteError("no route")
        from lab.onchain.jupiter import Quote
        return Quote(in_mint, out_mint, amount, int(f(amount)), 0.001, None, 0.0, ["Raydium"])


def sources(largest=True, fail=False, pairs=None):
    rows, owners = holders()
    acc = {MEME: G.Account(1, X.TOKEN, mint_data()), MS.metadata_address(MEME): G.Account(1, MS.METADATA_PROGRAM, meta_data())}
    for a, n in rows:
        acc[a] = G.Account(1, X.TOKEN, token_acc(owners[a], n))
    dex_calls = []

    def dex(url):
        dex_calls.append(url)
        return [pair()] if pairs is None else pairs
    src = MS.Sources(FakeRpc(acc, rows if largest else None, fail), FakeJup([{"id": MEME, "symbol": "MEME"}]), dex)
    return src, dex_calls


def test_check_reads_the_chain_jupiter_and_dexscreener_and_caches_the_verdict(tmp_path):
    src, dex_calls = sources()
    p = tmp_path / "safety.json"
    v = MS.check(MEME, src, (set(), set()), set(), NOW, cache=False)
    assert v.ok, v.reasons
    MS.save(v, p)
    assert MS.cached(MEME, 60_000, NOW + 30_000, p)["ok"] is True
    assert MS.cached(MEME, 60_000, NOW + 61_000, p) is None
    assert dex_calls and dex_calls[0].endswith(MEME)
    src, _ = sources(fail=True)
    v = MS.check(MEME, src, (set(), set()), set(), NOW, cache=False)
    assert not v.ok and "could not be read from the chain" in v.reasons[0]
    src, _ = sources(pairs="not a list")
    v = MS.check(MEME, src, (set(), set()), set(), NOW, cache=False)
    assert not v.ok and any("DexScreener" in r for r in v.reasons)


# ---------------------------------------------------------------- the rules

def cand(**kw) -> dict:
    c = {"mint": MEME, "symbol": "MEME", "sources": ["dexscreener:boosted"], "trends": None, "jup": None,
         "fresh": False, "pool": {"liq_usd": 80_000.0, "h1": 6.0, "h24": 25.0, "born_ms": NOW - 30 * H}}
    c.update(kw)
    return c


def test_entries_of_each_rule():
    t = {"migrate_ms": NOW - 10 * 60_000, "badges": ["win_high"]}
    assert ME.entry_why("fresh_win", cand(fresh=True, trends=t), NOW) is None
    assert "5 to 30" in ME.entry_why("fresh_win", cand(fresh=True, trends={**t, "migrate_ms": NOW - 60_000}), NOW)
    assert "win_high" in ME.entry_why("fresh_win", cand(fresh=True, trends={**t, "badges": []}), NOW)
    assert "rug" in ME.entry_why("fresh_win", cand(fresh=True, trends={**t, "badges": ["win_high", "rug_risk"]}), NOW)
    assert "fresh pool" in ME.entry_why("fresh_win", cand(), NOW)
    assert ME.entry_why("momentum_trail", cand(), NOW) is None
    assert "50,000" in ME.entry_why("momentum_trail", cand(pool={**cand()["pool"], "liq_usd": 30_000.0}), NOW)
    assert "up 5 %" in ME.entry_why("momentum_trail", cand(pool={**cand()["pool"], "h24": 10.0}), NOW)
    assert "a day old" in ME.entry_why("momentum_trail", cand(pool={**cand()["pool"], "born_ms": NOW - H}), NOW)
    assert "rug" in ME.entry_why("momentum_trail", cand(trends={"badges": ["rug_risk"]}), NOW)
    j = {"organicScore": 85, "stats1h": {"priceChange": 1.0}, "stats24h": {"priceChange": 3.0}}
    assert ME.entry_why("organic_trend", cand(sources=["jupiter:organic"], jup=j), NOW) is None
    assert "organic-score list" in ME.entry_why("organic_trend", cand(jup=j), NOW)
    assert "under 80" in ME.entry_why("organic_trend", cand(sources=["jupiter:organic"], jup={**j, "organicScore": 70}), NOW)
    assert "up over" in ME.entry_why("organic_trend", cand(sources=["jupiter:organic"],
                                                           jup={**j, "stats1h": {"priceChange": -1}}), NOW)


def test_exits_take_profit_stop_trailing_time_liquidity_and_no_quote():
    pos = {"cost_sol": 0.1001, "opened_ms": NOW - 60_000, "peak_sol": 0.1, "entry_liq_usd": 40_000.0,
           "last_quote_ms": NOW - 60_000}
    assert ME.exit_why("fresh_win", pos, 0.16, 40_000, NOW) == "take profit"
    assert ME.exit_why("fresh_win", pos, 0.07, 40_000, NOW) == "stop"
    assert ME.exit_why("fresh_win", {**pos, "peak_sol": 0.13}, 0.10, 40_000, NOW) == "trailing stop"
    assert ME.exit_why("fresh_win", {**pos, "peak_sol": 0.115}, 0.09, 40_000, NOW) is None     # trail not armed
    assert ME.exit_why("fresh_win", {**pos, "opened_ms": NOW - 3 * H}, 0.1, 40_000, NOW) == "time stop"
    assert ME.exit_why("fresh_win", pos, 0.1, 19_000, NOW) == "liquidity drop"
    assert ME.exit_why("fresh_win", pos, 0.1, None, NOW) is None
    assert ME.exit_why("fresh_win", pos, None, None, NOW) is None
    assert "closed at zero" in ME.exit_why("fresh_win", {**pos, "last_quote_ms": NOW - 31 * 60_000}, None, None, NOW)
    assert ME.exit_why("momentum_trail", {**pos, "peak_sol": 0.2}, 0.169, 40_000, NOW) == "trailing stop"
    assert ME.exit_why("momentum_trail", pos, 0.5, 40_000, NOW) is None                         # no take profit


def test_candidates_merge_sources_and_take_only_fresh_trends():
    doc = {"written_ms": NOW - 10_000, "lists": {"fresh": [{"mint": MEME, "symbol": "MEME", "migrate_ms": NOW}],
                                                 "hot": [{"mint": A("on the curve"), "migrated": False},
                                                         {"mint": A("migrated"), "migrated": True}]}}
    tr = ME.from_trends(doc, NOW)
    assert [c["mint"] for c in tr] == [MEME, A("migrated")] and tr[0]["fresh"]
    assert ME.from_trends({**doc, "written_ms": NOW - 10 * 60_000}, NOW) == []
    c = ME.merge(tr, [{"mint": MEME, "source": "jupiter:organic", "jup": {"organicScore": 90}},
                      {"mint": WSOL, "source": "jupiter:trending"}])
    assert set(c) == {MEME, A("migrated")} and c[MEME]["sources"] == ["trends:fresh", "jupiter:organic"]
    assert c[MEME]["jup"] == {"organicScore": 90} and c[MEME]["fresh"]


# ---------------------------------------------------------------- the paper book

def test_the_paper_book_buys_through_quotes_marks_and_closes(tmp_path, monkeypatch):
    monkeypatch.setattr(MS, "read_blocked", lambda paths=None: (set(), set()))
    monkeypatch.setattr(MS, "exception_paths", lambda: [])
    monkeypatch.setattr(MS, "cache_path", lambda: tmp_path / "safety.json")
    monkeypatch.setattr(ME.report, "REPORTS", tmp_path / "reports")
    price = {"sol_per_unit": 1e-4}                     # 0.1 SOL buys 1,000 units (raw 1e9 at 6 decimals)
    q = {(WSOL, MEME): lambda lam: lam / 1e9 / price["sol_per_unit"] * 1e6,
         (MEME, WSOL): lambda raw: raw / 1e6 * price["sol_per_unit"] * 1e9}
    jup = FakeJup([{"id": MEME, "symbol": "MEME", "organicScore": 90, "stats1h": {"priceChange": 2},
                    "stats24h": {"priceChange": 9}}], q)
    src, _ = sources(pairs=[pair(born=NOW - 30 * H, h1=1.0, h24=2.0)])
    out = ME.run(jup, src, NOW, tmp_path, trends_doc={})
    assert out["rules"]["organic_trend"]["bought"] == 1 and out["rules"]["momentum_trail"]["bought"] == 0
    st = ME.load_state("organic_trend", tmp_path)
    (pos,) = st["positions"].values()
    assert pos["units_raw"] == 1_000_000_000 and pos["entry_liq_usd"] == 50_000
    assert st["cash_sol"] == pytest.approx(1.0 - 0.1 - (0.000005 + 0.0001))
    j = ME.read_csv(ME.book_dir("organic_trend", tmp_path) / "journal.csv")
    assert j[-1]["bought"] == "1" and float(j[-1]["equity"]) < 10_000 and "EXPERIMENT" in st["variant"]
    out = ME.run(jup, src, NOW + 60_000, tmp_path, trends_doc={})              # cooldown: no second buy
    assert out["rules"]["organic_trend"]["bought"] == 0 and out["rules"]["organic_trend"]["open"] == 1
    price["sol_per_unit"] = 1.4e-4                                             # +40 %: take profit at +30 %
    out = ME.run(jup, src, NOW + 120_000, tmp_path, trends_doc={})
    assert out["rules"]["organic_trend"]["closed"] == 1
    trades = ME.read_csv(ME.book_dir("organic_trend", tmp_path) / "trades.csv")
    assert [t["side"] for t in trades] == ["buy", "sell"] and trades[1]["why"] == "take profit"
    assert float(trades[1]["ret_pct"]) == pytest.approx((0.14 - 0.000105) / 0.100105 * 100 - 100, abs=1e-3)
    assert (tmp_path / "reports" / "onchain_meme" / "books.json").exists()


def test_a_coin_the_safety_check_refuses_is_never_quoted(tmp_path, monkeypatch):
    monkeypatch.setattr(MS, "read_blocked", lambda paths=None: ({MEME}, set()))
    monkeypatch.setattr(MS, "exception_paths", lambda: [])
    monkeypatch.setattr(MS, "cache_path", lambda: tmp_path / "safety.json")
    monkeypatch.setattr(ME.report, "REPORTS", tmp_path / "reports")
    jup = FakeJup([{"id": MEME, "organicScore": 90, "stats1h": {"priceChange": 2}, "stats24h": {"priceChange": 9}}])
    src, _ = sources(pairs=[pair(born=NOW - 30 * H)])
    out = ME.run(jup, src, NOW, tmp_path, trends_doc={})
    assert all(r["bought"] == 0 for r in out["rules"].values())
    assert any("block list" in k for k in out["rules"]["organic_trend"]["skipped"])


def test_max_open_and_a_position_without_a_quote(tmp_path):
    st = ME.new_state("momentum_trail", NOW)
    ex = ME.Paper(FakeJup(quotes={(WSOL, m): (lambda lam: 10 ** 9) for m in WALLETS}), priority=0.0)
    for m in WALLETS[:7]:
        ME.try_entry("momentum_trail", st, ex, {"mint": m, "pool": {}}, NOW, tmp_path)
    assert len(st["positions"]) == ME.MAX_OPEN
    closed = ME.run_exits("momentum_trail", st, ex, {}, NOW + 31 * 60_000, tmp_path)
    assert len(closed) == ME.MAX_OPEN and all(float(r["ret_pct"]) == -100 for r in closed)
    assert st["day"]["no_quote"] == ME.MAX_OPEN


def test_the_proof_needs_every_check():
    journal = [{"date": f"2026-11-{d:02d}", "equity": 10_000 + 30 * d + (25 if d % 3 else -20), "planned": 10,
                "no_quote": 0} for d in range(1, 31)]
    trades = []
    for i in range(120):
        ts = NOW + i * 7 * H
        trades.append({"id": f"t{i}", "side": "buy", "ts": ts, "sol": 0.1, "fee_sol": 0.0001})
        trades.append({"id": f"t{i}", "side": "sell", "ts": ts + H, "sol": 0.1 * (1.08 if i % 4 else 0.97),
                       "fee_sol": 0.0001, "ret_pct": 8.0 if i % 4 else -3.0})
    pool = {"n_total": 2000, "var": 1e-6}
    p = ME.proof_of(journal, trades, pool)
    c = p["checks"]
    assert c["p1_days"]["passed"] and c["p2_trades"]["passed"] and c["p3_mean_band"]["passed"]
    assert c["p4_breadth"]["passed"] and c["p6_quotes"]["passed"]
    assert p["passed"] == c["p5_deflated"]["passed"]
    short = ME.proof_of(journal[:10], trades[:40], pool)
    assert not short["passed"] and not short["checks"]["p1_days"]["passed"] and not short["checks"]["p2_trades"]["passed"]
    noq = ME.proof_of([{**r, "no_quote": 2} for r in journal], trades, pool)
    assert not noq["checks"]["p6_quotes"]["passed"] and not noq["passed"]
    assert not ME.proof_of(journal, trades, None)["passed"]                  # no pool: the deflation cannot pass


def test_three_rules_are_registered_and_counted():
    assert ME.TRIALS == len(ME.RULES) == 3
    from pathlib import Path
    text = (Path(__file__).resolve().parents[1] / "results" / "onchain_meme_prereg.md").read_text(encoding="utf-8")
    for r in ME.RULES:
        assert f"`{r}`" in text


# ---------------------------------------------------------------- the gate

MEME_ACK = """
[meme]
rules=fresh_win,organic_trend
max_total_usd=50
max_trade_usd=10
max_daily_loss_usd=10
"""


def test_the_ack_reads_the_meme_section_and_refuses_above_its_maxima(tmp_path):
    p = tmp_path / "ack"
    p.write_text(TL.ACK + MEME_ACK)
    a = LG.read_ack(p, TL.TODAY)
    assert a.problems == () and a.meme_problems == () and a.meme_rules == ("fresh_win", "organic_trend")
    assert (a.meme_cap("total"), a.meme_cap("trade"), a.meme_cap("daily_loss")) == (50, 10, 10)
    assert a.view()["meme"]["rules"] == ["fresh_win", "organic_trend"]
    assert LG.MEME_MAX_TOTAL_USD == 50 and LG.MEME_MAX_TRADE_USD == 10 and LG.MEME_MAX_DAILY_LOSS_USD == 10
    for line, why in [("max_total_usd=51", "hard maximum 50"), ("max_trade_usd=11", "hard maximum 10"),
                      ("max_daily_loss_usd=10.5", "hard maximum 10"), ("rules=yolo", "not a pre-registered"),
                      ("rules=", "names no meme rules"), ("mints=BONK", "does not belong")]:
        key = line.split("=")[0]
        body = "\n".join(x for x in MEME_ACK.splitlines() if not x.startswith(key + "=")) + "\n" + line + "\n"
        p.write_text(TL.ACK + body)
        a = LG.read_ack(p, TL.TODAY)
        assert a.problems == () and any(why in w for w in a.meme_problems), (line, a.meme_problems)
        assert a.meme_cap("trade") == 0.0
    p.write_text(TL.ACK)
    a = LG.read_ack(p, TL.TODAY)
    assert a.meme_rules == () and a.meme_cap("total") == 0.0
    p.write_text(TL.ACK + "[yolo]\nrules=x\n")
    assert "unknown section" in LG.read_ack(p, TL.TODAY).problems[0]


def ok_ack(**kw) -> LG.Ack:
    base = dict(mode="test", mints=("SOL", "USDC"), meme_rules=("fresh_win",), meme_max_total_usd=50.0,
                meme_max_trade_usd=10.0, meme_max_daily_loss_usd=10.0)
    base.update(kw)
    return LG.Ack(**base)


PROOF = {"updated_ms": NOW - H, "rules": {"fresh_win": {"passed": True}}}


def verdict(**kw) -> dict:
    v = {"mint": MEME, "ok": True, "reasons": [], "t": NOW - 10_000, "facts": {"decimals": 6}}
    v.update(kw)
    return v


def test_meme_problems_refuse_without_section_proof_fresh_check_or_with_the_kill_file():
    assert LG.meme_problems("fresh_win", MEME, ok_ack(), PROOF, verdict(), NOW) == []
    assert any("does not name" in w for w in LG.meme_problems("fresh_win", MEME, ok_ack(meme_rules=()), PROOF,
                                                              verdict(), NOW))
    assert any("[meme]" in w for w in LG.meme_problems("fresh_win", MEME, ok_ack(meme_problems=("[meme] bad",)),
                                                       PROOF, verdict(), NOW))
    assert any("no meme proof" in w for w in LG.meme_problems("fresh_win", MEME, ok_ack(), None, verdict(), NOW))
    assert any("has not passed" in w for w in LG.meme_problems(
        "fresh_win", MEME, ok_ack(), {**PROOF, "rules": {"fresh_win": {"passed": False}}}, verdict(), NOW))
    assert any("older than 36 h" in w for w in LG.meme_problems("fresh_win", MEME, ok_ack(), {**PROOF, "updated_ms": 0},
                                                                verdict(), NOW))
    assert any("no meme proof" in w for w in LG.meme_problems("fresh_win", MEME, ok_ack(mode="alpha"), None,
                                                              verdict(), NOW))       # alpha lifts no proof
    assert any("61 s old" in w for w in LG.meme_problems("fresh_win", MEME, ok_ack(), PROOF, verdict(t=NOW - 61_000), NOW))
    assert any("refused" in w for w in LG.meme_problems("fresh_win", MEME, ok_ack(), PROOF,
                                                        verdict(ok=False, reasons=["mint authority"]), NOW))
    assert any("no safety check" in w for w in LG.meme_problems("fresh_win", MEME, ok_ack(), PROOF,
                                                                verdict(mint=A("other")), NOW))
    assert "the kill switch file is there" in LG.meme_problems("fresh_win", MEME, ok_ack(), PROOF, verdict(), NOW,
                                                               killed=True)
    assert any("no valid" in w for w in LG.meme_problems("fresh_win", MEME, ok_ack(mode=None), PROOF, verdict(), NOW))


# ---------------------------------------------------------------- the live path on a fake chain

OUT = 9_750_000_000                      # 9,750 MEME (6 decimals) for 0.98 SOL at 10 USD: 0.001 USD each
IN = 980_000_000


class MemeChain(TL.FakeChain):
    """The fake chain with a meme mint, 2 SOL, a SOL to MEME swap in the simulation and the read back."""

    def __init__(self, mint_owner=X.TOKEN, **kw):
        super().__init__(sol=2_000_000_000, **kw)
        self.acc[MEME] = G.Account(1, mint_owner, b"\x00" * 82)

    def __call__(self, method, params):
        if method == "simulateTransaction":
            self.calls.append(method)
            self.sims += 1
            addrs = params[1]["accounts"]["addresses"]
            post = dict(self.acc)
            post[X.ata(TL.W, MEME)] = TL.tacc(MEME, TL.W, OUT)
            post[TL.W] = G.Account(self.acc[TL.W].lamports - IN - 40_000 - G.ATA_RENT_L, X.SYSTEM, b"")
            return {"result": {"value": {"err": None, "unitsConsumed": 200_000,
                                         "accounts": [TL.b64acc(post.get(k)) for k in addrs]}}}
        if method == "getTransaction":
            self.calls.append(method)
            return {"result": {"blockTime": 1_792_712_000, "transaction": {"message": {"accountKeys": [TL.W]}},
                               "meta": {"err": None, "fee": 40_000, "preBalances": [2_000_000_000],
                                        "postBalances": [2_000_000_000 - IN - 40_000 - G.ATA_RENT_L],
                                        "preTokenBalances": [],
                                        "postTokenBalances": [{"mint": MEME, "owner": TL.W,
                                                               "uiTokenAmount": {"amount": str(OUT)}}]}}}
        return super().__call__(method, params)


def meme_trader(tmp_path, monkeypatch, chain=None, answer=None, pool_price=0.001, check=None, ack=MEME_ACK):
    tr, fc = TL.trader(tmp_path, monkeypatch, chain=chain or MemeChain(),
                       answer=answer or TL.build_answer(in_mint=WSOL, out_mint=MEME, amount=IN, out=OUT, slip=200))
    (tmp_path / "ack").write_text(TL.ACK + ack)
    assert tr.gate.check() == []
    prices = {TL.USDC: 1.0, WSOL: 10.0, TL.BTC: 100_000.0, MEME: 0.001}
    tr.prices_of = lambda mints: prices
    state = {"n": 0}

    def fresh(m):
        state["n"] += 1
        return {"mint": m, "ok": True, "reasons": [], "t": LX.now_ms(), "facts": {"decimals": 6,
                                                                                    "pool": {"price_usd": pool_price}}}
    mt = ML.MemeTrader.from_trader(tr, check=check or fresh)
    return mt, fc, state


def proof_now():
    return {"updated_ms": LX.now_ms(), "rules": {"fresh_win": {"passed": True}}}


def test_a_meme_buy_goes_through_guard_simulation_and_the_ledger(tmp_path, monkeypatch):
    mt, fc, checks = meme_trader(tmp_path, monkeypatch)
    v = LX.read_view(mt.chain, TL.W, mt.prices_of)
    LX.baseline(v)
    s, r = mt.buy("fresh_win", MEME, v, proof_now(), signal_ms=LX.now_ms())
    assert r["status"] == "filled", r
    assert s.dst == LG.MEME_PREFIX + MEME and s.in_raw == IN and s.kind == "meme" and checks["n"] >= 1
    assert fc.sims == 2 and len(mt.signer.signed) == 1
    rows = LX.read_ledger()
    assert rows[-1]["kind"] == "meme" and rows[-1]["to"] == LG.MEME_PREFIX + MEME and rows[-1]["out_raw"] == str(OUT)
    assert ML.known_mints() == {MEME: 6} and ML.positions("fresh_win")[MEME]["raw"] == OUT
    exp, complete = LX.expected_holdings()
    assert complete and exp["tokens"][MEME] == OUT            # the reconciliation knows the meme coin
    assert LX.realised(LX.day_of(LX.now_ms()))["meme_swaps"] == 1


def test_the_base_trader_never_builds_a_meme_swap(tmp_path, monkeypatch):
    mt, fc, _ = meme_trader(tmp_path, monkeypatch)
    base = LX.Trader(mt.gate, mt.chain, mt.jup, signer=mt.signer, prices=mt.prices_of, kraken=mt.kraken,
                     clock=mt.clock, sleep=mt.sleep)
    v = LX.read_view(mt.chain, TL.W, mt.prices_of)
    r = base.execute(LX.Swap("meme", "SOL", LG.MEME_PREFIX + MEME, IN, book="fresh_win"), v)
    assert r["status"] == "refused" and "two coins of the list" in r["why"] and not fc.sent


@pytest.mark.parametrize("change, why", [
    (dict(ack=MEME_ACK.replace("fresh_win,", "")), "does not name fresh_win"),
    (dict(check=lambda m: {"mint": m, "ok": False, "reasons": ["it has a freeze authority"], "t": LX.now_ms()}),
     "freeze authority"),
    (dict(check=lambda m: {"mint": m, "ok": True, "reasons": [], "t": LX.now_ms() - 120_000,
                           "facts": {"decimals": 6}}), "s old"),
    (dict(pool_price=0.002), "best pool"),
    (dict(answer=TL.build_answer(in_mint=WSOL, out_mint=MEME, amount=IN, out=9_000_000_000, slip=200)), "minimum out"),
    (dict(chain=MemeChain(mint_owner=X.TOKEN_2022)), "Token-2022"),
])
def test_a_meme_buy_is_refused(tmp_path, monkeypatch, change, why):
    mt, fc, _ = meme_trader(tmp_path, monkeypatch, **change)
    v = LX.read_view(mt.chain, TL.W, mt.prices_of)
    _, r = mt.buy("fresh_win", MEME, v, proof_now())
    assert r["status"] == "refused" and why in r["why"], r
    assert not fc.sent and not mt.signer.signed


def test_a_meme_buy_without_proof_or_under_the_kill_file_sends_nothing(tmp_path, monkeypatch):
    mt, fc, _ = meme_trader(tmp_path, monkeypatch)
    v = LX.read_view(mt.chain, TL.W, mt.prices_of)
    _, r = mt.buy("fresh_win", MEME, v, None)
    assert r["status"] == "refused" and "no meme proof" in r["why"]
    (tmp_path / "KILL").write_text("")
    _, r = mt.buy("fresh_win", MEME, v, proof_now())
    assert r["status"] == "refused" and "kill switch" in r["why"] and not fc.sent


def test_meme_caps_trade_total_and_daily_loss(tmp_path, monkeypatch):
    mt, fc, _ = meme_trader(tmp_path, monkeypatch)
    mt.decimals[MEME] = 6
    v = LX.read_view(mt.chain, TL.W, mt.prices_of, memes={MEME: 6})
    buy = lambda raw: LX.Swap("meme", "SOL", LG.MEME_PREFIX + MEME, raw, book="fresh_win")
    assert mt.caps(buy(IN), v) is None
    assert "above the 10 USD a meme swap" in mt.caps(buy(1_100_000_000), v)
    assert "not a meme swap" in mt.caps(LX.Swap("meme", "USDC", LG.MEME_PREFIX + MEME, 10, book="fresh_win"), v)
    v.tokens[MEME] = 45_000_000_000                       # 45 USD of the coin held: 45 + 9.8 > 50
    LX.write_row({"t": LX.now_ms(), "kind": "meme", "book": "fresh_win", "from": "SOL", "to": LG.MEME_PREFIX + MEME,
                  "in_raw": 4_500_000_000, "out_raw": 45_000_000_000, "in_usd": 45.0, "status": "filled"})
    assert "max_total_usd of the [meme] section" in mt.caps(buy(IN), v)
    v.tokens[MEME] = 30_000_000_000
    v.prices[MEME] = 0.0012                               # 36 USD worth against a cost of 45: 9 lost, then 11
    assert mt.caps(buy(500_000_000), v) is None
    v.prices[MEME] = 0.00113
    assert "meme loss" in mt.caps(buy(100_000_000), v)
    sale = LX.Swap("meme", LG.MEME_PREFIX + MEME, "SOL", 5_000_000_000, book="fresh_win")
    assert mt.caps(sale, v) is None                       # a sale under the loss stop stays allowed
    assert [s.in_raw for s in mt.sales("fresh_win", MEME, 30_000_000_000, v)] == [7_500_000_000] * 4


def test_the_service_reports_why_the_meme_rules_are_shut(tmp_path, monkeypatch):
    svc = SV.Service(gate=TL.armed(tmp_path), alerts=False, trader=None)
    (tmp_path / "ack").write_text(TL.ACK + MEME_ACK)
    monkeypatch.setattr(LG, "data_dir", lambda: tmp_path / "live")
    monkeypatch.setattr(LG, "meme_proof_path", lambda: tmp_path / "proof.json")
    monkeypatch.setattr(LG, "kill_paths", lambda: [tmp_path / "KILL"])
    svc.gate.check()
    svc.run_memes()
    assert [m["rule"] for m in svc.memes] == ["fresh_win", "organic_trend"]
    assert all(not m["allowed"] and "no meme proof" in m["why"] for m in svc.memes)
    assert not (tmp_path / "live" / "memes.json").exists()
