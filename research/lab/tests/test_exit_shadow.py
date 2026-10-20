"""The exit shadow (lab.paper.exit_shadow) on synthetic books: the two frozen
rules, the append-only ledger written before the outcome, the scoring two
closes later, the once-only verdict, the feed and the digest line. No lab data.

Run from research/lab:  python -m pytest tests/test_exit_shadow.py
"""

from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest

from lab import report
from lab.experiments import fam_common as fc
from lab.ops import notify
from lab.paper import exit_shadow as xs

T = 330
START_US = int(datetime(2026, 4, 1, tzinfo=timezone.utc).timestamp() * 1_000_000)
NAMES = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"]
N = len(NAMES)
EM_DASH = chr(0x2014)
REG_ROW = (xs.REGISTERED_US - START_US) // fc.DAY_US  # the row of the registration day


def make_panel(seed: int = 3) -> fc.Panel:
    rng = np.random.default_rng(seed)
    ret = rng.normal(0.0005, 0.03, (T, N))
    ret[0] = np.nan
    px = 100 * np.cumprod(1 + np.nan_to_num(ret), axis=0)
    alive = np.ones((T, N), dtype=bool)
    idx = np.arange(T)[:, None]
    days = START_US + np.arange(T, dtype=np.int64) * fc.DAY_US
    return fc.Panel(days=days, names=list(NAMES), bases=[fc.base_of(n) for n in NAMES], close=px.copy(), px=px,
                    high=px * 1.01, low=px * 0.99, ret=ret, alive=alive, traded=alive.copy(),
                    age=np.where(alive, idx, -1), adv28=np.full((T, N), 1e8), sigma=np.full((T, N), 0.03),
                    eligible=alive & (idx >= 60), perp_ok=np.zeros((T, N), dtype=bool), funding=np.zeros((T, N)),
                    btc_on=np.ones(T, dtype=bool), btc=0,
                    extra={"rv": np.full((T, N), 0.0009), "qv": np.full((T, N), 1e8)})


def spells_of(on: int, off: int, offset: int = 0, first: int = 70) -> np.ndarray:
    """(T,) bool: held `on` closes, flat `off` closes, repeating from row `first`."""
    k = (np.arange(T) - first + offset) % (on + off)
    return (np.arange(T) >= first) & (k < on)


def books() -> dict[str, np.ndarray]:
    h = {b: np.zeros((T, N)) for b in xs.BOOKS}
    h["breakout"][100:300, 1] = 0.2                        # one long ETH spell
    h["tsmom_daily"][:, 2] = 0.15 * spells_of(45, 5)       # SOL: 45-day spells, the 40-day stop bites each
    for j, off in ((1, 0), (2, 3), (3, 5)):                # tranches: short spells in three coins
        h["tsmom_tranches"][:, j] = 0.1 * spells_of(6, 2, off)
    return h


def m14_stub(rows) -> np.ndarray:
    """z = -1 (a forecast of -9.5 % at 3 % daily vol) from the third close of a spell, +1 before."""
    return np.where(rows["days_held"].to_numpy() >= 3, -1.0, 1.0)


def ms(row: int, hour: int = 5) -> int:
    return (START_US // 1000) + row * 86_400_000 + hour * 3_600_000


@pytest.fixture()
def reports(tmp_path, monkeypatch):
    monkeypatch.setattr(report, "REPORTS", tmp_path / "reports")
    return tmp_path / "reports"


# ---------------------------------------------------------------- the rules

def test_the_time_stop_cuts_on_the_40th_close_after_entry_and_counts_one_exit():
    P = make_panel()
    h = books()
    rec = {t: {r["book"]: r for r in xs.decide(P, h, t, m14_stub)} for t in (139, 140, 141, 300)}
    before, at, after = rec[139]["breakout_top10"], rec[140]["breakout_top10"], rec[141]["breakout_top10"]
    assert "ETHUSDT" in before["base"] and before["overlays"]["time40"]["cut"] == []
    assert before["overlays"]["time40"]["weights"] == before["base"]
    assert before["coins"]["ETHUSDT"]["days_held"] == 40
    assert at["overlays"]["time40"]["cut"] == ["ETHUSDT"] and at["overlays"]["time40"]["new"] == ["ETHUSDT"]
    assert at["overlays"]["time40"]["weights"] == {} and "ETHUSDT" in at["base"], "the freed weight is cash"
    assert after["overlays"]["time40"]["cut"] == ["ETHUSDT"] and after["overlays"]["time40"]["new"] == []
    assert rec[300]["breakout_top10"]["base"] == {}, "the spell has ended"
    assert set(at["overlays"]) == {"time40"} and set(rec[140]["tsmom_tranches"]["overlays"]) == {"m14", "time40"}


def test_the_m14_exit_cuts_below_minus_70_bps_until_the_spell_ends():
    P = make_panel()
    h = books()
    col = h["tsmom_tranches"][:, 1] > 0
    s = next(t for t in range(200, T) if col[t] and not col[t - 1])      # an ETH spell starting at s
    days = {t - s + 1: next(r for r in xs.decide(P, h, t, m14_stub) if r["book"] == "tsmom_tranches")
            for t in range(s, s + 6)}
    m = {d: r["overlays"]["m14"] for d, r in days.items()}
    assert "ETHUSDT" not in m[2]["cut"] and "ETHUSDT" in m[2]["weights"]
    assert "ETHUSDT" in m[3]["new"] and "ETHUSDT" not in m[3]["weights"]
    assert "ETHUSDT" in m[4]["cut"] and "ETHUSDT" not in m[4]["new"]
    assert days[3]["coins"]["ETHUSDT"]["m14"] == pytest.approx(-0.03 * math.sqrt(10), abs=1e-6)
    nxt = next(r for r in xs.decide(P, h, s + 8, m14_stub) if r["book"] == "tsmom_tranches")
    assert "ETHUSDT" in nxt["base"] and "ETHUSDT" not in nxt["overlays"]["m14"]["cut"], "a new spell starts uncut"
    with pytest.raises(xs.ShadowError):
        xs.decide(P, h, s, None)


def test_the_registered_numbers_are_the_ones_in_the_pre_registration():
    text = (Path(xs.__file__).resolve().parents[2] / "results" / "exit_shadow_prereg.md").read_text(encoding="utf-8")
    assert xs.MODEL_SHA256 in text and xs.REGISTERED in text
    assert xs.M14_THRESHOLD == -0.0070 and "-70 bps" in text
    assert xs.TIME_STOP == 40 and "40th close after the entry close" in text
    assert (xs.MIN_DAYS, xs.MIN_EXITS, xs.MAX_DAYS) == (90, 30, 730)
    assert "n >= 90 scored days" in text and "30 exit decisions" in text and "730 scored days" in text
    assert xs.BAND_PCT == 2.5 and "2.5th percentile" in text and str(xs.SEED) in text
    assert xs.COST == 0.0035 and "35 bps" in text
    assert EM_DASH not in text


def test_only_the_registered_model_file_is_loaded(tmp_path):
    assert xs.sha256(xs.MODEL_FILE) == xs.MODEL_SHA256, "the committed frozen file is the registered one"
    meta = json.loads(xs.MODEL_FILE.with_suffix(".meta.json").read_text(encoding="utf-8"))
    assert meta["sha256"] == xs.MODEL_SHA256 and meta["panel_end"] == "2026-10-19"
    other = tmp_path / "m14.txt"
    other.write_bytes(xs.MODEL_FILE.read_bytes() + b"\n")
    with pytest.raises(xs.ShadowError, match="not the registered"):
        xs.load_model(other)
    with pytest.raises(xs.ShadowError, match="no frozen"):
        xs.load_model(tmp_path / "missing.txt")


# ---------------------------------------------------------------- the ledger

def test_only_yesterdays_close_is_recorded_once_and_never_before_registration(tmp_path, reports):
    P, h = make_panel(), books()
    ledger = tmp_path / "ledger"
    d = xs.run(now_ms=ms(REG_ROW + 1), P=P, held=h, predict=m14_stub, ledger=ledger)
    assert d["error"] is None and d["recorded"] == 3
    rows = xs.read_jsonl(ledger / "decisions.jsonl")
    assert {r["day"] for r in rows} == {xs.REGISTERED} and len(rows) == 3
    tr = next(r for r in rows if r["book"] == "tsmom_tranches")
    assert tr["model_sha256"] == xs.MODEL_SHA256 and tr["written_ms"] == ms(REG_ROW + 1)
    first = (ledger / "decisions.jsonl").read_text(encoding="utf-8")
    assert xs.run(now_ms=ms(REG_ROW + 1, 9), P=P, held=h, predict=m14_stub, ledger=ledger)["recorded"] == 0
    assert (ledger / "decisions.jsonl").read_text(encoding="utf-8") == first, "a second run the same day adds nothing"
    # Before the registration day nothing is recorded, and a record is never late.
    early = xs.decide(P, h, REG_ROW - 1, m14_stub)
    assert xs.admissible(early, [], ms(REG_ROW)) == []
    today = xs.decide(P, h, REG_ROW + 3, m14_stub)
    assert len(xs.admissible(today, [], ms(REG_ROW + 4, 23))) == 3
    assert xs.admissible(today, [], ms(REG_ROW + 5)) == [], "written after the next close: refused"


def test_a_stale_panel_records_nothing_and_says_so(tmp_path, reports):
    P, h = make_panel(), books()
    d = xs.run(now_ms=ms(T + 3), P=P, held=h, predict=m14_stub, ledger=tmp_path / "l")
    assert d["recorded"] == 0 and "missing" in d["error"] and d["status"] == "bad"
    assert not (tmp_path / "l" / "decisions.jsonl").exists()
    assert json.loads((reports / "exit_shadow" / "latest.json").read_text())["status"] == "bad"


def test_scoring_uses_the_return_two_closes_later_and_the_drifted_turnover():
    P = make_panel()
    t = REG_ROW + 5
    day = lambda r: {"day": xs.iso(int(P.days[r])), "day_us": int(P.days[r]), "book": "breakout_top10"}  # noqa: E731
    d0 = {**day(t - 1), "base": {"ETHUSDT": 0.2}, "overlays": {"time40": {"weights": {"ETHUSDT": 0.2}, "new": []}}}
    d1 = {**day(t), "base": {"ETHUSDT": 0.2, "SOLUSDT": 0.1}, "overlays": {"time40": {"weights": {}, "new": ["ETHUSDT"]}}}
    early = xs.score_new(P, [d0, d1], [], ms(t + 2, 23))
    assert [s["day"] for s in early] == [d0["day"]], "d1's day t+2 has not closed yet"
    sc = {s["day"]: s for s in xs.score_new(P, [d0, d1], [], ms(t + 3))}
    assert set(sc) == {d0["day"], d1["day"]}
    s1 = sc[d1["day"]]
    r2, r1 = P.ret[t + 2], P.ret[t + 1]
    assert s1["return_day"] == xs.iso(int(P.days[t + 2]))
    assert s1["gross"]["base"] == pytest.approx(0.2 * r2[1] + 0.1 * r2[2])
    assert s1["gross"]["time40"] == 0.0
    g1 = 0.2 * r1[1]
    drift = 0.2 * (1 + r1[1]) / (1 + g1)
    assert s1["turnover"]["base"] == pytest.approx(abs(0.2 - drift) + 0.1)
    assert s1["turnover"]["time40"] == pytest.approx(drift)
    assert s1["net"]["time40"] == pytest.approx(-xs.COST * drift)
    assert s1["turnover_charged"] and not sc[d0["day"]]["turnover_charged"], "no record before d0: not charged"
    assert sc[d0["day"]]["turnover"]["base"] is None
    assert xs.score_new(P, [d0, d1], list(sc.values()), ms(t + 9)) == [], "each record is scored once"


# ---------------------------------------------------------------- the verdict

def test_the_verdict_is_reached_on_the_first_prefix_with_enough_exits():
    rng = np.random.default_rng(0)
    y = rng.normal(0.0, 0.02, 200)
    good = y * 0.3 + 0.002                               # less risk, more return
    one = np.ones(200, dtype=int)
    assert xs.judge(good[:89], y[:89], one[:89]) is None, "fewer than 90 days"
    v = xs.judge(good, y, one)
    assert v["passed"] and v["days"] == 90 and v["exits"] == 90 and all(v["gates"].values())
    late = np.zeros(200, dtype=int)
    late[[10, 150]] = 15
    assert xs.judge(good, y, late)["days"] == 151, "judged on the scored day of the 30th exit"
    bad = xs.judge(y - 0.003, y, one)
    assert not bad["passed"] and "Sharpe above" in bad["why"]
    assert xs.judge(good[:120], y[:120], np.zeros(120, dtype=int)) is None
    few = xs.judge(np.zeros(800), np.zeros(800), np.zeros(800, dtype=int))
    assert not few["passed"] and few["days"] == xs.MAX_DAYS and "fewer than 30 exits" in few["why"]


def test_daily_runs_reach_one_final_verdict_with_one_digest_line_per_change(tmp_path, reports):
    P, h = make_panel(), books()
    ledger = tmp_path / "ledger"
    changed = {}
    for row in range(REG_ROW + 1, REG_ROW + 105):
        d = xs.run(now_ms=ms(row), P=P, held=h, predict=m14_stub, ledger=ledger)
        assert d["error"] is None
        for c in d["changes"]:
            changed.setdefault(c["id"], []).append((row, c["from"], c["to"]))
    m14, stop = d["tests"]
    assert m14["id"] == "tsmom_tranches:m14" and m14["status"] in ("passed", "failed")
    assert m14["verdict"]["days"] == 90 and m14["verdict"]["exits"] >= 30
    assert [c[1:] for c in changed["tsmom_tranches:m14"]] == [("waiting", "collecting"), ("collecting", m14["status"])]
    assert stop["status"] == "collecting" and stop["exits"] < 30 and stop["scored_days"] == m14["scored_days"]
    assert [b["judged"] for b in d["books"]] == [False] * 3 and d["books"][1]["exits"] > 0
    verdicts = xs.read_jsonl(ledger / "verdicts.jsonl")
    assert [v["id"] for v in verdicts] == ["tsmom_tranches:m14"], "a verdict is written once"
    # A later run keeps the verdict; the ledgers only grew, line by line.
    lines = (ledger / "scores.jsonl").read_text(encoding="utf-8").splitlines()
    again = xs.run(now_ms=ms(REG_ROW + 105), P=P, held=h, predict=m14_stub, ledger=ledger)
    assert again["tests"][0]["verdict"] == m14["verdict"] and again["changes"] == []
    assert (ledger / "scores.jsonl").read_text(encoding="utf-8").splitlines()[:len(lines)] == lines
    # The feed header for the Research page.
    rep = json.loads((reports / "exit_shadow" / "latest.json").read_text(encoding="utf-8"))
    assert {"title", "updated_ms", "status", "headline", "items"} <= set(rep)
    assert rep["status"] == ("watch" if m14["status"] == "passed" else "ok") and len(rep["items"]) == 5
    assert rep["items"][0]["link"] == "study:exit_shadow_prereg"
    assert EM_DASH not in json.dumps(rep, ensure_ascii=False)


# ---------------------------------------------------------------- the digest line

def shadow_report(now: int, changes: list[dict]) -> dict:
    return {"date": datetime.fromtimestamp(now / 1000, timezone.utc).strftime("%Y-%m-%d"), "changes": changes}


def test_the_digest_gets_one_line_only_on_a_day_a_test_changes_status():
    now = int(datetime(2026, 12, 1, 6, 50, tzinfo=timezone.utc).timestamp() * 1000)
    assert notify.exit_shadow_line(None, now) is None
    assert notify.exit_shadow_line(shadow_report(now, []), now) is None
    ch = [{"id": "tsmom_tranches:m14", "overlay": "m14", "from": "collecting", "to": "passed"},
          {"id": "three_books:time40", "overlay": "time40", "from": "waiting", "to": "collecting"}]
    assert notify.exit_shadow_line(shadow_report(now - 86_400_000, ch), now) is None, "yesterday's report"
    en = notify.exit_shadow_line(shadow_report(now, ch), now, "en")
    assert en.lead == "Exit rules (shadow)"
    assert en.text == ("M14 exit on tsmom_tranches passed its forward test; nothing trades on it until you decide; "
                       "40-day stop on the three crypto books started recording")
    de = notify.exit_shadow_line(shadow_report(now, ch), now, "de")
    assert de.lead == "Ausstiegsregeln (Schatten)" and "bestanden" in de.text and "zeichnet jetzt auf" in de.text
    assert EM_DASH not in en.text + de.text
    card, _ = notify.digest_card(None, None, None, {}, now, lang="en", exit_shadow=shadow_report(now, ch))
    assert sum(1 for p in card.parts if isinstance(p, notify.Line) and p.lead == "Exit rules (shadow)") == 1
    card, _ = notify.digest_card(None, None, None, {}, now, lang="en", exit_shadow=shadow_report(now, []))
    assert not any(isinstance(p, notify.Line) and p.lead == "Exit rules (shadow)" for p in card.parts)
    assert not re.search(EM_DASH, card.render("telegram"))
