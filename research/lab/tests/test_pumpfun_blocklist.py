"""The owner's block list (blocklist.py): mints, creators, symbols and names the live bot and its paper twin
P_pool0_wait never buy (2026-10-23: three SHEKEL relaunches bought live, all lost). The matching rules, the
re-read on a change, the skip with its reason (status, one log line, skipped.jsonl), held positions left to their
exits, and the paper twin deciding like the live book.

Run from research/lab:  python -m pytest tests/test_pumpfun_blocklist.py
"""

from __future__ import annotations

import json
import os
from types import SimpleNamespace

from lab.pumpfun_rt import blocklist as BL
from lab.pumpfun_rt import collector as COL
from lab.pumpfun_rt import live_exec as LX
from lab.pumpfun_rt import pipeline as P
from test_pumpfun_live_match import CREATE, MIGRATE, POOL_BUY, PUBLIC, RULE, folders, service, shown  # noqa: F401
from test_pumpfun_rt import DEV, MINT, T0, key, note

CREATOR = key(50)


def coin(mint=None, creator=None, symbol="", name="", devs=()):
    return SimpleNamespace(mint=mint or key(60), creator=creator or key(61), devs=set(devs), symbol=symbol, name=name)


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def test_the_matching_rules(tmp_path, capsys):
    f = tmp_path / "blocked-mints.txt"
    f.write_text(f"# the owner's list\n{MINT}   # one coin\ncreator:{CREATOR}\nsymbol:SHEKEL\nSymbol: $Pepe \n"
                 "name:Moon Dog!\n\nnot a mint\nwallet:abc\nsymbol:$$$\ncreator:short\n", encoding="utf-8")
    w = BL.BlockWatch(paths=[f, tmp_path / "missing.txt"])
    assert w(RULE, coin(MINT)) == "blocked (mint)"
    assert w(RULE, coin(creator=CREATOR)) == f"blocked (creator {CREATOR[:8]})"
    assert w(RULE, coin(devs={CREATOR})) == f"blocked (creator {CREATOR[:8]})"   # the wallet that paid for it
    for s in ("SHEKEL", "$SHEKEL", "shekel ", " $she-kel"):
        assert w(RULE, coin(symbol=s)) == "blocked (symbol SHEKEL)", s
    assert w(RULE, coin(symbol="PEPE")) == "blocked (symbol $Pepe)"
    assert w(RULE, coin(name="moon  dog")) == "blocked (name Moon Dog!)"
    assert w(RULE, coin(symbol="SHEKELS", name="Moon Dog 2")) is None
    assert w(RULE, coin(symbol="MOONDOG")) is None                                 # a name entry is not a symbol
    assert w(RULE, coin(name="SHEKEL")) is None
    assert len(w.list) == 5
    out = capsys.readouterr().out
    assert out.count("ignored") == 4 and "'not a mint'" in out and "'symbol:$$$'" in out
    assert "1 mints, 1 creators, 2 symbols, 1 names blocked" in out
    assert BL.parse_line("  # only a comment") is None and BL.parse_line("") is None
    assert BL.parse_line("symbol:" + "A" * 65) is False


def test_a_match_entry_blocks_every_name_or_symbol_that_contains_its_text(tmp_path, capsys):
    """The owner's celebrity copies (2026-10-23: SpaceX AI -87 % in one candle, Tesla SpaceXSI -54 %)."""
    f = tmp_path / "blocked-mints.txt"
    f.write_text("symbol:SHEKEL\nmatch:spacex\nmatch:elon\nMATCH: Tesla  # and its copies\nmatch:ai\nmatch:$e-l\n"
                 f"match:{'a' * 65}\n", encoding="utf-8")
    w = BL.BlockWatch(paths=[f])
    assert w(RULE, coin(name="SpaceX AI", symbol="SXAI")) == "blocked (match spacex)"
    assert w(RULE, coin(name="Space Rocket", symbol="$SPACEX")) == "blocked (match spacex)"
    assert w(RULE, coin(name="Elon's Dog", symbol="DOG")) == "blocked (match elon)"
    assert w(RULE, coin(name="x", symbol="TESLA2")) == "blocked (match Tesla)"
    assert w(RULE, coin(name="Tesla SpaceXSI", symbol="TSX")) in ("blocked (match spacex)", "blocked (match Tesla)")
    assert w(RULE, coin(name="Telsa", symbol="TELSA")) is None                  # contained, not alike
    assert w(RULE, coin(name="Shekel coin", symbol="SHK")) is None              # symbol: stays exact
    assert w(RULE, coin(symbol="SHEKEL")) == "blocked (symbol SHEKEL)"          # the exact kinds first
    assert w(RULE, coin(MINT, symbol="X")) is None
    assert len(w.list) == 4 and set(w.list.matches) == {"spacex", "elon", "tesla"}
    out = capsys.readouterr().out
    assert out.count("ignored") == 3 and "'match:ai'" in out and "'match:$e-l'" in out    # under 3 letters or digits
    assert "1 symbols, 0 names, 3 matches blocked" in out
    assert BL.parse_line("match:abc") == ("match", "abc") and BL.parse_line("match: a b ") is False


def test_a_match_entry_is_a_skip_of_the_live_book_and_the_paper_twin(tmp_path, monkeypatch):
    from lab.pumpfun_rt import live
    monkeypatch.setattr(live, "paper_dir", lambda: tmp_path)
    f = tmp_path / "b.txt"
    f.write_text("match:tes\n", encoding="utf-8")                               # create_vals: name Test
    sh = live.Shadow("A_all_x1", models=None, alerts=False, now_ms=T0, strategies=[P.BY_NAME[RULE]],
                     blocked=BL.BlockWatch(paths=[f], rules=BL.PAPER_RULES))
    col = COL.Collector(None, on_row=sh.on_row, amm=True, meta=False)
    svc, lcol, pipe = service()
    pipe.blocked = BL.BlockWatch(paths=[f])
    for c in (col, lcol):
        c.handle(note("c", 100, CREATE), T0, PUBLIC)
        c.handle(note("m", 101, MIGRATE), T0 + 400, PUBLIC)
        c.handle(note("b", 102, POOL_BUY), T0 + 800, PUBLIC)
    sh.tick(T0 + 10_000)
    svc.tick(T0 + 10_000)
    assert not pipe.pos and shown(pipe) == {"blocked (match tes)": 1}
    assert sh.engine.skipped[(RULE, "blocked (match tes)")] == 1
    rec = [json.loads(x) for x in (LX.data_dir() / "skipped.jsonl").read_text().splitlines()]
    assert [r["why"] for r in rec] == ["blocked (match tes)"]


def test_a_missing_file_is_an_empty_list_and_rules_limit_whom_it_holds_for(tmp_path):
    w = BL.BlockWatch(paths=[tmp_path / "none.txt"])
    assert len(w.list) == 0 and w(RULE, coin(MINT, symbol="SHEKEL")) is None
    f = tmp_path / "b.txt"
    f.write_text("symbol:SHEKEL\n", encoding="utf-8")
    w = BL.BlockWatch(paths=[f], rules=BL.PAPER_RULES)
    assert w("P_pool0_wait", coin(symbol="SHEKEL")) == "blocked (symbol SHEKEL)"
    assert w("P_pool0", coin(symbol="SHEKEL")) is None


def test_the_list_is_read_again_when_the_file_changes_at_most_every_2_s(tmp_path, capsys):
    f = tmp_path / "b.txt"
    clock = Clock()
    w = BL.BlockWatch(paths=[f], clock=clock)
    shekel = coin(symbol="SHEKEL")
    assert w(RULE, shekel) is None
    f.write_text("symbol:SHEKEL\nbad line\n", encoding="utf-8")
    clock.t += 1.0
    assert w(RULE, shekel) is None                                                 # not looked yet
    clock.t += 1.0
    assert w(RULE, shekel) == "blocked (symbol SHEKEL)"
    st = f.stat()
    f.write_text("symbol:OTHER\nbad line\n", encoding="utf-8")
    os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns + 10 ** 9))
    clock.t += 2.0
    assert w(RULE, shekel) is None and w(RULE, coin(symbol="other")) == "blocked (symbol OTHER)"
    out = capsys.readouterr().out
    assert out.count("'bad line'") == 1                                            # one warning, not one a read
    f.unlink()
    clock.t += 2.0
    assert w(RULE, coin(symbol="other")) is None


def test_a_blocked_coin_is_a_skip_with_its_reason_a_log_line_and_a_row(tmp_path, capsys):
    f = tmp_path / "b.txt"
    f.write_text("symbol:$tst\n", encoding="utf-8")                              # create_vals: symbol TST
    svc, col, pipe = service()
    pipe.blocked = BL.BlockWatch(paths=[f])
    col.handle(note("c", 100, CREATE), T0, PUBLIC)
    col.handle(note("m", 101, MIGRATE), T0 + 400, PUBLIC)
    col.handle(note("b", 102, POOL_BUY), T0 + 800, PUBLIC)
    svc.tick(T0 + 10_000)
    assert not pipe.pos and pipe.eng.counts["pipe_signals"] == 0
    assert shown(pipe) == {"blocked (symbol $tst)": 1}
    assert capsys.readouterr().out.count(f"live: skipped {MINT[:8]}: blocked (symbol $tst)") == 1
    rec = [json.loads(x) for x in (LX.data_dir() / "skipped.jsonl").read_text().splitlines()]
    assert [(r["mint"], r["rule"], r["why"]) for r in rec] == [(MINT, RULE, "blocked (symbol $tst)")]
    assert not (LX.data_dir() / "orders.jsonl").exists()

    for line in (MINT, f"creator:{DEV}", "name:test"):                           # the other kinds, the same way
        f.write_text(line + "\n", encoding="utf-8")
        svc, col, pipe = service()
        pipe.blocked = BL.BlockWatch(paths=[f])
        col.handle(note("c", 100, CREATE), T0, PUBLIC)
        col.handle(note("m", 101, MIGRATE), T0 + 400, PUBLIC)
        col.handle(note("b", 102, POOL_BUY), T0 + 800, PUBLIC)
        svc.tick(T0 + 10_000)
        assert not pipe.pos and list(shown(pipe)) == [pipe.blocked.list.why(MINT, [DEV], "TST", "Test")], line

    f.write_text("symbol:OTHER\n", encoding="utf-8")                              # not on the list: bought
    svc, col, pipe = service()
    pipe.blocked = BL.BlockWatch(paths=[f])
    col.handle(note("c", 100, CREATE), T0, PUBLIC)
    col.handle(note("m", 101, MIGRATE), T0 + 400, PUBLIC)
    col.handle(note("b", 102, POOL_BUY), T0 + 800, PUBLIC)
    svc.tick(T0 + 10_000)
    assert pipe.eng.counts["pipe_signals"] == 1 and len(pipe.pos) == 1


def test_a_curve_buy_asks_the_list_too(tmp_path):
    f = tmp_path / "b.txt"
    f.write_text("symbol:TST\n", encoding="utf-8")
    svc, col, pipe = service()
    pipe.blocked = BL.BlockWatch(paths=[f])
    curve = next(s for s in P.STRATEGIES if s.family != "E")
    tok = coin(MINT, DEV, "TST", "Test")                                             # asked before the curve checks
    pipe.strats[curve.name] = curve
    pipe.risk[curve.name] = pipe.risk[RULE]
    pipe.signal(curve, tok, T0)
    assert pipe.eng.skipped[(curve.name, "blocked (symbol TST)")] == 1 and not pipe.pos


def test_a_held_coin_that_becomes_blocked_is_not_sold_by_it(tmp_path):
    f = tmp_path / "b.txt"
    svc, col, pipe = service()
    pipe.blocked = BL.BlockWatch(paths=[f], every_s=0)
    col.handle(note("c", 100, CREATE), T0, PUBLIC)
    col.handle(note("m", 101, MIGRATE), T0 + 400, PUBLIC)
    col.handle(note("b", 102, POOL_BUY), T0 + 800, PUBLIC)
    svc.tick(T0 + 1_000)
    assert len(pipe.pos) == 1
    p = next(iter(pipe.pos.values()))
    state = p["state"]
    f.write_text("symbol:TST\n", encoding="utf-8")
    col.handle(note("b2", 103, POOL_BUY), T0 + 1_500, PUBLIC)
    svc.tick(T0 + 2_000)
    assert pipe.blocked(RULE, coin(symbol="TST")) == "blocked (symbol TST)"
    assert len(pipe.pos) == 1 and p["state"] == state and not p["selling"] and p["exit_why"] is None


def test_the_paper_twin_skips_like_the_live_book_and_the_other_paper_books_do_not(tmp_path, monkeypatch):
    from lab.pumpfun_rt import live
    monkeypatch.setattr(live, "paper_dir", lambda: tmp_path)
    f = tmp_path / "b.txt"
    f.write_text("symbol:TST\n", encoding="utf-8")
    sh = live.Shadow("A_all_x1", models=None, alerts=False, now_ms=T0,
                     strategies=[P.BY_NAME[RULE], P.BY_NAME["P_pool0"]],
                     blocked=BL.BlockWatch(paths=[f], rules=BL.PAPER_RULES))
    col = COL.Collector(None, on_row=sh.on_row, amm=True, meta=False)
    svc, lcol, pipe = service()
    pipe.blocked = BL.BlockWatch(paths=[f])
    for c in (col, lcol):
        c.handle(note("c", 100, CREATE), T0, PUBLIC)
        c.handle(note("m", 101, MIGRATE), T0 + 400, PUBLIC)
        c.handle(note("b", 102, POOL_BUY), T0 + 800, PUBLIC)
    sh.tick(T0 + 10_000)
    svc.tick(T0 + 10_000)
    assert sh.engine.skipped[(RULE, "blocked (symbol TST)")] == 1
    assert shown(pipe) == {"blocked (symbol TST)": 1}
    assert [k for k in sh.engine.skipped if k[0] == "P_pool0"] == [("P_pool0", "no pool state")]  # as before
