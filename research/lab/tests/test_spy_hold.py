"""The SPY sleeve of the Crypto + SPY forward test (lab.paper.spy_hold): one signal a month,
always 100 % SPY, explicit only. No network, no lab data.

Run from research/lab:  python -m pytest tests/test_spy_hold.py
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from lab.paper import spy_hold as sh


def ms(y, m, d, h=0) -> int:
    return int(datetime(y, m, d, h, tzinfo=timezone.utc).timestamp() * 1000)


def test_the_signal_is_all_spy_a_us_share_book_and_explicit_only():
    ev = sh.evidence("Equity sleeves ...: SPY buy and hold Sharpe 1.30, drawdown 18.8 %; U2 QQQ ...")
    assert ev["oos_sharpe"] == 1.30 and abs(ev["oos_max_dd"] - 0.188) < 1e-12
    assert ev["explicit_only"] is True and "forward test" in ev["verdict"]
    s = sh.signal(ms(2026, 11, 2, 14), ev)
    assert s["weights"] == {"SPY": 1.0} and s["asset_class"] == "us_equity" and s["autopilot_only"] is True
    assert s["evidence"]["explicit_only"] is True
    assert s["valid_until_ms"] - s["generated_ms"] == 40 * sh.DAY_MS, "valid past the next month's signal"
    assert s["as_of_ms"] == ms(2026, 11, 2)
    assert "—" not in json.dumps(s, ensure_ascii=False), "no em dash"
    # The study's line is gone: the numbers are missing, the sleeve still runs.
    assert sh.evidence("nothing here")["missing"] is True


def test_the_real_study_has_the_line_it_reads():
    ev = sh.evidence()
    assert not ev.get("missing"), ev
    assert 0 < ev["oos_sharpe"] < 3 and 0 < ev["oos_max_dd"] < 1


def test_one_signal_per_calendar_month(tmp_path, capsys):
    now = ms(2026, 10, 21, 14)
    assert sh.main([], now_ms=now, root=tmp_path) == 0
    first = sh.read_latest(tmp_path)
    assert first["generated_ms"] == now
    assert (tmp_path / "signals" / "spy_hold" / "2026-10-21.json").exists()
    # Later the same month: nothing new, the engine has nothing to trade.
    assert sh.main([], now_ms=ms(2026, 10, 30, 14), root=tmp_path) == 0
    assert sh.read_latest(tmp_path)["generated_ms"] == now
    assert "nothing to do" in capsys.readouterr().out
    # The first run in November publishes the month's signal.
    nov = ms(2026, 11, 2, 14)
    sh.main([], now_ms=nov, root=tmp_path)
    assert sh.read_latest(tmp_path)["generated_ms"] == nov
    # A dry run writes nothing.
    sh.main(["--dry-run"], now_ms=ms(2026, 12, 1, 14), root=tmp_path)
    assert sh.read_latest(tmp_path)["generated_ms"] == nov


def test_a_stale_or_foreign_signal_is_replaced_at_once():
    now = ms(2026, 10, 21)
    assert sh.due(None, now)
    assert sh.due({"strategy": "other", "generated_ms": now, "valid_until_ms": now + 1}, now)
    assert sh.due({"strategy": "spy_hold", "generated_ms": now - 1, "valid_until_ms": now - 1}, now)
    assert not sh.due({"strategy": "spy_hold", "generated_ms": now - 1, "valid_until_ms": now + 1}, now)
