"""The stale pool state G1 found (results/pumpfun_pool_state_fix_prereg.md): with sim.Engine(fresh_pool=True), the
paper books' flag, a pool read of a later slot than the stream's last pool trade is the coin's state and the buy fills
on it (HEXN 2026-10-29); without it the engine is what the live service and the twin run, unchanged. Then the study's
numbers, the ledger keys every reader skips and their counts in realistic.md and the ladder.

Run from research/lab:  python -m pytest tests/test_pumpfun_pool_state_fix.py
"""

from __future__ import annotations

import pytest

from lab.pumpfun_rt import curve as C
from lab.pumpfun_rt import pool_fix as F
from lab.pumpfun_rt import realistic as R
from lab.pumpfun_rt import sim
from lab.pumpfun_rt import slippage_e1 as E1
from test_pumpfun_exit_runners import BASE0, QUOTE0, engine
from test_pumpfun_exits_y8 import LatePool
from test_pumpfun_rt import MINT, POOL, T0

DAY = 86_400_000
EM = "\u2014"
PB, PQ = BASE0 * 20 // 21, QUOTE0 * 21 // 20             # the read: the price 10 % over the trade's


def hexn(fresh: bool):
    """HEXN: the migration, the stream's one pool trade in its slot (before the signal), the collector's read 81
    slots later with more quote (0.15 s after the trade; HEXN's was 186 SOL against 105, here 5 % so the buy stays in
    its bound), no further pool trade; P_pool0's buy lands at T0 + 1 s (Fixed)."""
    eng = engine("P_pool0", fresh_pool=fresh)
    pool = LatePool(eng)
    pool.open(T0)                                          # slot 50_001
    eng.pool_state(T0 + 150, MINT, POOL, PB, PQ, slot=50_082)
    eng.advance(T0 + 5_000)
    return eng, eng.tokens[MINT]


def test_hexn_a_read_of_a_later_slot_is_the_state_and_the_fill():
    eng, tok = hexn(True)
    assert (tok.pb, tok.pq, tok.amm_slot) == (PB, PQ, 50_082)
    p = next(iter(eng.pipes[0].pos.values()))
    assert p["entry_price"] == pytest.approx(C.price(PQ, PB), rel=0.01)   # with the stake's own impact


def test_without_the_flag_the_engine_is_unchanged():
    eng, tok = hexn(False)
    assert tok.pq < QUOTE0 * 1.01 and tok.amm_slot == 50_001   # the trade's state, the read dropped (G1 pins it too)
    p = next(iter(eng.pipes[0].pos.values()))
    assert p["entry_price"] < C.price(PQ, PB) / 1.09


def test_older_and_same_slot_reads_and_trades():
    eng = engine("P_pool0", fresh_pool=True)
    pool = LatePool(eng)
    pool.open(T0 + 100)                                    # slot 50_001
    tok = eng.tokens[MINT]
    before = (tok.pb, tok.pq)
    eng.pool_state(T0 + 200, MINT, POOL, BASE0 // 2, QUOTE0 * 2, slot=50_001)     # the same slot: the trade stays
    eng.pool_state(T0 + 210, MINT, POOL, BASE0 // 2, QUOTE0 * 2, slot=49_990)     # older: dropped
    eng.pool_state(T0 + 220, MINT, POOL, BASE0 // 2, QUOTE0 * 2)                  # no slot, a state known: dropped
    assert (tok.pb, tok.pq, tok.amm_slot) == (*before, 50_001)
    eng.pool_state(T0 + 230, MINT, POOL, BASE0 // 2, QUOTE0 * 2, slot=50_010)
    assert (tok.pb, tok.pq) == (BASE0 // 2, QUOTE0 * 2)
    pool.slot = 50_005                                     # a late trade of a slot before the read: not the state
    pool.trade(T0 + 240, True, C.LAMPORTS // 100)
    assert (tok.pb, tok.pq, tok.amm_slot) == (BASE0 // 2, QUOTE0 * 2, 50_010)
    pool.slot = 50_020                                     # a later trade moves it from its own reserves
    pool.trade(T0 + 260, True, C.LAMPORTS // 100)
    assert tok.amm_slot == 50_021 and tok.pq != QUOTE0 * 2


def test_a_read_with_no_trade_yet_counts_with_or_without_the_flag():
    for fresh in (False, True):
        eng = engine("P_pool0", fresh_pool=fresh)
        LatePool(eng)
        eng.pool_state(T0 + 50, MINT, POOL, BASE0, QUOTE0, slot=50_000)
        assert (eng.tokens[MINT].pb, eng.tokens[MINT].pq) == (BASE0, QUOTE0)


def test_the_shadow_sets_the_flag_and_the_live_service_does_not(monkeypatch):
    from lab.pumpfun_rt import live, live_service
    from lab.pumpfun_rt import model as M
    from lab.pumpfun_rt import pipeline as P
    from lab.pumpfun_rt import strategies as S
    monkeypatch.setattr(M, "load", lambda *a, **k: {})
    sh = live.Shadow(S.DEFAULT_PICK, alerts=False, now_ms=T0, strategies=[P.BY_NAME["P_pool0"]], realistic=True,
                     real=R.Model(R.Fit(), R.LiveConfig()))
    assert sh.engine.fresh_pool is True
    assert live_service.load_engine().fresh_pool is False and sim.Engine([]).fresh_pool is False


# ---------------------------------------------------------------- the ledger keys and the readers

def keys(monkeypatch, rows):
    monkeypatch.setattr(R, "STALE_KEYS", frozenset(R.stale_key(r) for r in rows))


def led(i, ret, rule="P_pool0_10eur", **kw):
    t = F.WINDOW_FROM_MS + DAY + i * 60_000
    return {"rule": rule, "mint": f"m{i}", "signal_ms": str(t), "land_ms": t + 5_000, "exit_signal_ms": t + 9_000,
            "exit_ms": t + 10_000, "hold_s": 5.0, "ret": ret, "stake_sol": 0.05, "pnl_sol": ret * 0.05,
            "exit_why": "take", **kw}


def test_the_key_hides_the_coin_and_matches_the_csvs_text(monkeypatch):
    r = led(1, 0.1)
    k = R.stale_key(r)
    assert len(k) == 16 and "m1" not in k and k == R.stale_key(r | {"signal_ms": float(r["signal_ms"])})
    assert k != R.stale_key(r | {"rule": "P_pool0"})
    monkeypatch.setattr(R, "STALE_KEYS", frozenset())
    assert not R.stale(r)
    keys(monkeypatch, [r])
    assert R.stale(r) and not R.stale(led(2, 0.1))


def test_the_keys_file_round_trips(tmp_path, monkeypatch):
    p = tmp_path / "rows.json"
    F.write_keys({"keys": [R.stale_key(led(3, 0.1))], "from_ms": 1, "to_ms": 2}, p)
    monkeypatch.setattr(R, "STALE_PATH", p)
    monkeypatch.setattr(R, "STALE_KEYS", None)
    assert R.stale(led(3, 0.1)) and not R.stale(led(4, 0.1)) and "m3" not in p.read_text()


def test_p3_skips_and_counts_the_stale_rows_and_its_wallet_loses_their_pnl(monkeypatch):
    rows = [led(i, 0.05) for i in range(12)] + [led(20, 2.0), led(21, 1.0)]
    keys(monkeypatch, rows[-2:])
    st = {"paper_wallets": {"P_pool0_10eur": R.TenWallet(pnl_l=int(0.2 * C.LAMPORTS), since_ms=T0, n=14).to_json()}}
    ten = (("P_pool0_10eur", "P_pool0"),)
    r = R.ten_status(st, rows, [], 90.0, {"pass": True}, T0 + DAY, ten=ten)[0]
    assert r["trades"] == 12 and r["mean"] == pytest.approx(0.05) and r["stale"] == 2
    assert r["stale_sol"] == pytest.approx(0.15) and r["sol"] == pytest.approx(0.109 + 0.2 - 0.15)
    w = R.ten_status(st, rows, [], 90.0, {"pass": True}, T0 + DAY, ten=ten, skip_stale=False)[0]
    assert w["trades"] == 14 and w["stale"] == 0 and w["sol"] == pytest.approx(0.309)
    md = "\n".join(R.ten_md([r], 90.0))
    assert "Left out: 2 trades filled on a stale pool state before the fix (+0.150 SOL" in md and EM not in md
    assert "stale pool state" not in "\n".join(R.ten_md([w], 90.0))


def test_r2_and_e1_skip_and_count_them(monkeypatch):
    s = led(5, 1.0, rule="P_pool5_top30t_sw10o3n")
    keys(monkeypatch, [s])
    small = (("P_pool5_top30t_sw10o3n", "P_pool5_top30t", 0.10, 3, False),)
    st = {"paper_wallets": {small[0][0]: {"start_l": int(0.55 * C.LAMPORTS), "pnl_l": int(0.1 * C.LAMPORTS), "n": 4,
                                          "refills": 0}}}
    row = R.small_status(st, 90.0, small=small, stale_=R.stale_by_book([s, led(6, 0.1, rule=s["rule"])]))[0]
    assert row["stale"] == 1 and row["sol"] == pytest.approx(0.6) and row["trades"] == 3
    assert "Left out: 1 trades filled on a stale pool state" in "\n".join(R.small_md([row], 90.0))
    e = [led(7, 0.04, rule="P_pool0_wait@e1_b05"), led(8, 3.0, rule="P_pool0_wait@e1_b05")]
    keys(monkeypatch, e[1:])
    fw = E1.forward(e, [], register=False)
    assert fw["stale"] == 1 and fw["books"]["P_pool0_wait|b05"]["mean"] == pytest.approx(0.04)
    assert "Left out: 1 trades of the `@e1_` books" in "\n".join(E1.forward_md(fw))


def test_the_ladder_skips_and_counts_them(monkeypatch):
    from lab.ops import ladder as L
    rows = [led(i, 0.05, rule="P_pool0") for i in range(5)] + [led(9, 2.0, rule="P_pool0")]
    keys(monkeypatch, rows[-1:])
    es, bad, old = L.pf_entries(rows, [], F.WINDOW_FROM_MS)
    assert len(es) == 5 and bad == 0 and old == 1 and all(x == pytest.approx(0.05) for _, x in es)
    assert F.WINDOW_FROM_MS == L.PF_REAL_FROM_MS


# ---------------------------------------------------------------- the study's numbers

def ent(mint, sig, ret, e=1.0, failed=False, **kw):
    if failed:
        return {"mint": mint, "signal_ms": sig, "pnl_sol": ret, "failed": True}
    return {"mint": mint, "signal_ms": sig, "ret": ret, "entry_price": e, "stake_sol": 0.05, "pnl_sol": ret * 0.05,
            "exit_why": "take", "failed": False, **kw}


def test_the_entries_the_band_and_the_moved_share():
    t = F.WINDOW_FROM_MS
    a = [ent("a", t + 1, 0.1), ent("b", t + DAY, -0.1), ent("c", t + 2 * DAY, 0.0), ent("d", t + 2 * DAY, -0.0005,
                                                                                         failed=True),
         ent("x", t - 1, 9.0)]
    es = F.per_entry(a)
    assert sorted(r for _, r in es) == pytest.approx([-0.1, -0.01, 0.0, 0.1])     # the fee over the median stake
    st = F.stats(es)
    assert st["n"] == 4 and st["days"] == 3 and st["lo"] < st["mean"] < st["hi"]
    assert st["mean"] == pytest.approx(-0.0025)
    b = [ent("a", t + 1, 0.05, e=1.2), ent("b", t + DAY, -0.1), ent("c", t + 2 * DAY, 0.0, failed=True),
         ent("z", t + 3 * DAY, 0.2)]
    m = F.moved(a, b)
    assert (m["matched"], m["moved"], m["only_before"], m["only_after"], m["fail_changed"]) == (2, 1, 2, 1, 1)
    c = F.compare({"books": {"P_pool0": a}}, {"books": {"P_pool0": b}})
    assert c["P_pool0"]["pts"] == pytest.approx((F.stats(F.per_entry(b))["mean"] - st["mean"]) * 100)
    assert c["P_pool0_10eur"]["before"]["n"] == 0 and c["P_pool0_10eur"]["pts"] is None


def test_the_ledger_rule_is_g1s_stale_fill(monkeypatch):
    from lab.pumpfun_rt import reconcile_g1 as G
    from lab.pumpfun_rt import store
    t = F.WINDOW_FROM_MS + DAY
    rows = [led(0, 2.0, rule="P_pool0", mint="s", land_ms=t + 6_000),          # read after an older trade: stale
            led(0, 0.1, rule="P_pool0", mint="f", land_ms=t + 6_000),          # a trade between read and fill
            led(0, 0.1, rule="P_pool0", mint="s", exit_why="restart"),
            led(0, 0.1, rule="P_old", mint="s", land_ms=t + 6_000)]           # not a restated book
    for r in rows:
        r["signal_ms"] = str(t)
    reads = {"s": (t + 150.0, 82), "f": (t + 150.0, 82)}
    trades = {"s": [(t + 0.0, 1)], "f": [(t + 0.0, 1), (t + 3_000.0, 90)]}
    monkeypatch.setattr(store, "days", lambda root=None: [F._day(F.WINDOW_FROM_MS), F._day(t)])
    monkeypatch.setattr(G, "reads_and_trades", lambda mints, days, root=None: (reads, trades))
    st = F.ledger_stale(rows)
    assert st["keys"] == [R.stale_key(rows[0])] and st["books"]["P_pool0"] == {"rows": 2, "stale": 1,
                                                                              "stale_sol": pytest.approx(0.1)}


def test_the_books_the_trials_and_the_report():
    b = F.books()
    assert len(b) == 40 and len(set(b)) == 40 and b[:4] == list(F.FOUR)
    assert {"P_pool0_10eur", "P_pool5_top30t_sw10o3n", "P_cmig_model@e1_s30"} <= set(b)
    tr = F.trials()
    assert len(tr) == 41 and sum(x["n"] for x in tr) == 81 and {x["family"] for x in tr} == {"pumpfun"}
    t = F.WINDOW_FROM_MS
    run = {"days": ["2026-10-24", "2026-11-15"]}
    res = {"books": F.compare({"books": {"P_pool0": [ent("a", t + 1, 0.1)]}},
                              {"books": {"P_pool0": [ent("a", t + 1, 0.3, e=0.5)]}}),
           "ledger": {"keys": ["k"], "books": {"P_pool0": {"rows": 3, "stale": 1, "stale_sol": 0.01}}, "from_ms": t,
                      "to_ms": t + DAY}, "before_run": run, "after_run": run, "now": ["| x |"]}
    md = F.markdown(res)
    assert "| P_pool0 | 1 | +10.0 % | n/a | 1 | +30.0 % | n/a | +20.0 | 1 of 1 (100.0 %) | 0 / 0 |" in md
    assert "| P_pool0 | 3 | 1 | +0.0100 |" in md and EM not in md


def test_12041s_sensitivity_against_the_runs(tmp_path):
    w = tmp_path / "window.md"
    w.write_text("| book | entries, fallback | mean, fallback | band, fallback | entries, new fit | mean, new fit | "
                 "band, new fit | points |\n|---|---|---|---|---|---|---|---|\n"
                 "| P_pool0 | 2573 | +1.9 % | -0.1 % to +3.8 % | 2651 | +6.1 % | +3.8 % to +8.5 % | +4.3 |\n",
                 encoding="utf-8")
    t = F.WINDOW_FROM_MS
    c = F.compare({"books": {"P_pool0": [ent("a", t + 1, 0.081)]}}, {"books": {"P_pool0": [ent("a", t + 1, 0.04)]}})
    s = F.sensitivity(c, w)
    assert list(s) == ["P_pool0"] and s["P_pool0"]["after_pts"] == pytest.approx(2.1)
    assert s["P_pool0"]["before_pts"] == pytest.approx(6.2) and s["P_pool0"]["share"] == pytest.approx(2.1 / 4.3)
    md = "\n".join(F.sens_lines(s))
    assert "| P_pool0 | +1.9 % | +6.1 % | +4.3 | +4.0 % | +2.1 | +8.1 % | +6.2 | 49 % |" in md and EM not in md
    assert F.sensitivity(c, tmp_path / "none.md") == {} and F.sens_lines({}) == []


def test_what_p3_and_the_ladder_read_now(tmp_path, monkeypatch):
    from lab.ops import ladder as L
    pd = tmp_path / "paper" / "pumpfun_rt"
    pd.mkdir(parents=True)
    rows = [led(i, 0.05, rule="P_pool0_10eur") for i in range(3)] + [led(9, 2.0, rule="P_pool0_10eur")]
    cols = list(rows[0])
    (pd / "ledger.csv").write_text(",".join(cols) + "\n" + "\n".join(",".join(str(r[c]) for c in cols) for r in rows)
                                   + "\n", encoding="utf-8")
    keys(monkeypatch, rows[-1:])
    monkeypatch.setattr(R, "reports_dir", lambda: tmp_path)
    monkeypatch.setattr(R, "sol_eur", lambda: 90.0)
    seen = []

    def ctx(root, now):
        seen.append(R.stale_keys())
        n = 1 if R.stale_keys() else 0
        return {"rules": {"P_pool0": {"entries": 5 - n, "mean": 0.01, "lo": -0.01, "hi": 0.03, "stale": n,
                                      "tainted": 0}}}
    monkeypatch.setattr(L, "pf_context", ctx)
    md = "\n".join(F.now_lines(pd, tmp_path))
    assert "| P_pool0_10eur |" in md and "3 (was 4)" in md and "| 1 (+0.1000) |" in md
    assert "| P_pool0 | 4 | +1.0 % | -1.0 % to +3.0 % | 5, +1.0 %, -1.0 % to +3.0 % | 1 | 0 |" in md
    assert seen[1] == frozenset() and R.stale_keys() == seen[0] != frozenset()      # the keys put back
