"""The daily refresh of <data>/etf/daily (lab.collect.etf_daily) with a fake download. No network.

Run from research/lab:  python -m pytest tests/test_etf_daily.py
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lab.collect import etf_daily
from lab.experiments import etf_trend as et
from lab.ops import jobs

OPS = Path(__file__).resolve().parents[2] / "ops"
OLD = "Date,Close\n2026-10-12,100\n2026-10-13,101\n"
NEW = "Date,Close\n2026-10-26,110\n2026-10-27,111\n"


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(et, "CACHE", tmp_path / "etf" / "daily")
    et.CACHE.mkdir(parents=True)
    for s in etf_daily.SYMBOLS:
        (et.CACHE / f"{s}.csv").write_text(OLD)
    return et.CACHE


def test_a_failed_symbol_keeps_its_old_file_the_others_are_rewritten(cache):
    def fetch(sym):
        if sym == "GLD":
            raise et.DataUnavailable("GLD (Yahoo): HTTP Error 429")
        if sym == "TLT":
            return "<html>Exceeded the daily hits limit</html>"     # an error page, never cached
        return NEW
    res = etf_daily.refresh(fetch=fetch, pause_s=0)
    assert set(res) == set(etf_daily.SYMBOLS)
    assert res["GLD"].startswith("DataUnavailable") and res["TLT"].startswith("DataUnavailable")
    assert (cache / "GLD.csv").read_text() == OLD and (cache / "TLT.csv").read_text() == OLD
    assert all((cache / f"{s}.csv").read_text() == NEW for s in etf_daily.SYMBOLS if s not in ("GLD", "TLT"))


def test_exit_code_non_zero_only_when_every_symbol_failed(cache):
    def down(sym):
        raise OSError("down")
    assert etf_daily.main(fetch=down, pause_s=0) == 1
    assert all((cache / f"{s}.csv").read_text() == OLD for s in etf_daily.SYMBOLS)
    assert etf_daily.main(fetch=lambda s: NEW if s == "SPY" else "quota", pause_s=0) == 0
    assert (cache / "SPY.csv").read_text() == NEW and (cache / "QQQ.csv").read_text() == OLD


def test_every_reader_of_the_folder_is_refreshed():
    from lab import history
    from lab.ops import briefing
    need = set(et.SYMBOLS) | set(history.ETFS) | set(briefing.ETFS) | {"SPY", "QQQ", "GLD"}  # smallaccount, R10
    assert need <= set(etf_daily.SYMBOLS) and len(etf_daily.SYMBOLS) == len(set(etf_daily.SYMBOLS))


def test_the_job_runs_after_the_us_close_on_weekdays():
    t = jobs.load_table(OPS / "jobs.yaml")
    j = t.jobs["etf-daily"]
    assert j["command"] == "python -m lab.collect.etf_daily" and j["kind"] == "lab" and j["enabled"]
    assert j["schedule"] == "30 22 * * 1-5" and 0 < j["timeout_s"] <= 3600
    assert jobs.plain_lab_job(j), "no env file, network or volume"
    assert any(d["name"] == "etf" and d["path"] == "etf/daily" and d["max_age_h"] == 96 for d in t.datasets)


def test_eq1s_ucits_funds_come_from_yahoo_only(cache, monkeypatch):
    from lab.experiments import etf_books_eq1 as eq1
    assert set(eq1.SYMBOLS) | set(eq1.TWIN.values()) <= set(etf_daily.SYMBOLS)
    asked = []
    monkeypatch.setattr(et, "download_yahoo", lambda s: asked.append(s) or NEW)
    monkeypatch.setattr(et, "download_stooq", lambda s, timeout=30.0: (_ for _ in ()).throw(AssertionError(s)) if
                        s.endswith(".DE") else NEW)
    res = etf_daily.refresh(pause_s=0)
    assert all(res[s] == "ok" for s in eq1.SYMBOLS) and set(eq1.SYMBOLS) <= set(asked)
    assert all((cache / f"{s}.csv").read_text() == NEW for s in eq1.SYMBOLS)
