"""The lab feed header (docs/LAB-FEEDS.md) and the reports that carry it.

No network, no lab data. Run from research/lab:  python -m pytest tests
"""

from __future__ import annotations

import pytest

from lab import report
from lab.ops import learn
from lab.paper import forward_report


def test_header_has_the_fields_the_engine_reads():
    h = report.feed_header("New listings", "watch", "Two new coins.",
                           ["plain line", {"label": "SUI/USD", "value": "new", "link": None, "importance": 90}],
                           updated_ms=5)
    assert h == {"title": "New listings", "status": "watch", "headline": "Two new coins.", "updated_ms": 5,
                 "items": [{"label": "plain line"}, {"label": "SUI/USD", "value": "new", "importance": 90}]}
    assert report.feed_header("T", "ok", "h")["updated_ms"] > 0


def test_header_refuses_what_the_app_cannot_show():
    with pytest.raises(ValueError):
        report.feed_header("T", "great", "h")
    with pytest.raises(ValueError):
        report.feed_header("T", "ok", "h", [{"value": 1}])
    assert len(report.feed_header("T", "ok", "h", [f"row {i}" for i in range(80)])["items"]) == 50


def test_forward_feed_puts_a_book_below_its_band_first():
    books = [{"name": "a", "label": "Steady", "status": "early", "return_pct": 0.1, "sentence": "Too early."},
             {"name": "b", "label": "Slipping", "status": "watch", "position": "below", "return_pct": -2.5,
              "sentence": "Below the range."}]
    f = forward_report.feed(books, [], "2 books.", 7)
    assert f["status"] == "watch" and f["updated_ms"] == 7 and f["title"] == "Forward tests"
    assert f["items"][0]["label"] == "Slipping" and f["items"][0]["value"] == "-2.50 %"
    assert forward_report.feed(books[:1], [], "1 book.", 7)["status"] == "ok"


def test_learn_feed_flags_failed_steps_and_promotions():
    d = {"headline": "Promoted vol_1h.",
         "decisions": [{"model": "vol_1h", "decision": "promoted", "why": "better"},
                       {"model": "picks", "decision": "rejected", "why": "worse"}],
         "changes": [{"area": "costs", "what": "Alpaca spread 2 bps", "why": "fills"}],
         "steps": [{"step": "m2", "status": "failed"}]}
    f = learn.feed(d, 9)
    assert f["status"] == "bad" and f["headline"] == "Promoted vol_1h."
    assert [i["label"] for i in f["items"]][:2] == ["vol_1h: promoted", "step m2 failed"]
    assert learn.feed({**d, "steps": []}, 9)["status"] == "ok"
