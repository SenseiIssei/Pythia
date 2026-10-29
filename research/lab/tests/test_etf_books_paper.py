"""EQ1's paper books (lab.paper.etf_books) on synthetic closes: the first run starts every wallet in cash at the last
close, the next run steps each new Xetra close once and trades one close late, a rerun the same day adds nothing,
stale closes only mark, the top-up is booked on its day, the report feeds lab.ops.paper_books, and the study's 30
trials reach the registry once.

Run from research/lab:  python -m pytest tests/test_etf_books_paper.py
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone

import numpy as np
import pytest

from lab import metrics, report
from lab.experiments import etf_books_eq1 as eq1
from lab.experiments import etf_trend as et
from lab.ops import paper_books
from lab.paper import etf_books as pb

PX = {"EUNL.DE": 100.0, "SXR8.DE": 700.0, "EXSA.DE": 50.0, "EUNM.DE": 50.0, "IUSN.DE": 8.0, "EUNH.DE": 100.0,
      "4GLD.DE": 100.0, "XEON.DE": 150.0, "IWM": 200.0}


def ms(day: str) -> int:
    return int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp() * 1000) + 23 * 3_600_000


def write_closes(cache, last: str, first: str = "2025-01-02") -> None:
    d = np.arange(np.datetime64(first), np.datetime64(last) + np.timedelta64(1, "D"))
    d = d[np.is_busday(d)]
    for s, p in PX.items():
        rows = "".join(f"{x},{p * (1 + 0.0002 * i)}\n" for i, x in enumerate(d))
        (cache / f"{s}.csv").write_text("Date,Close\n" + rows, encoding="utf-8")


@pytest.fixture()
def env(tmp_path, monkeypatch):
    cache, root = tmp_path / "etf", tmp_path / "data"
    cache.mkdir()
    monkeypatch.setattr(et, "CACHE", cache)
    monkeypatch.setattr(report, "REPORTS", root / "reports")
    monkeypatch.setenv("PYTHIA_TRIALS_REGISTRY", str(tmp_path / "registry.jsonl"))
    return cache, root


def journal(root, name: str) -> list[dict]:
    with (root / "paper" / name / "journal.csv").open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_first_run_starts_in_cash_and_the_next_trades_one_close_late(env):
    cache, root = env
    write_closes(cache, "2026-10-27")
    assert pb.main([], ms("2026-10-27"), root) == 0
    st = json.loads((root / "paper" / "eq1_hold_sp500_once" / "state.json").read_text())
    assert st["started"] == st["last"] == "2026-10-27" and set(st["wallets"]) == set(eq1.BROKERS)
    assert pb.new_state("eq1_dual_mom_once", "2026-10-23", "2026-10-26")["started"] == "2026-10-26"
    assert all(w["cash"] == 50.0 and w["units"] == {} and w["tgt"] is None for w in st["wallets"].values())
    assert not (root / "paper" / "eq1_hold_sp500_once" / "journal.csv").exists()
    write_closes(cache, "2026-10-29")
    assert pb.main([], ms("2026-10-29"), root) == 0
    j = journal(root, "eq1_hold_sp500_once")
    assert [(r["date"], r["broker"]) for r in j] == [(d, b) for d in ("2026-10-28", "2026-10-29") for b in eq1.BROKERS]
    st = json.loads((root / "paper" / "eq1_hold_sp500_once" / "state.json").read_text())
    tr, ib = st["wallets"]["tr"], st["wallets"]["ibkr"]
    assert tr["units"]["SXR8.DE"] > 0 and tr["fees"] == 0 and tr["plan_eur"] == pytest.approx(50.0)
    assert ib["units"] == {} and ib["not_sent"] == 1                         # one SXR8 unit is over 700 EUR
    assert not (root / "paper" / "eq1_hold_sp500_once" / "trades.csv").exists()   # a plan is not an order
    t = list(csv.DictReader((root / "paper" / "eq1_dual_mom_once" / "trades.csv").open()))
    assert t and {r["date"] for r in t} == {"2026-10-28"} and {r["broker"] for r in t} >= {"tr"}
    # a rerun the same day adds nothing
    assert pb.main([], ms("2026-10-29"), root) == 0
    assert len(journal(root, "eq1_hold_sp500_once")) == 6


def test_stale_closes_only_mark(env):
    cache, root = env
    write_closes(cache, "2026-10-20")
    pb.main([], ms("2026-10-20"), root)
    write_closes(cache, "2026-10-22")
    pb.main([], ms("2026-11-10"), root)                                      # closes 19 days old: nothing stepped
    st = json.loads((root / "paper" / "eq1_dual_mom_once" / "state.json").read_text())
    assert st["last"] == "2026-10-20" and not (root / "paper" / "eq1_dual_mom_once" / "journal.csv").exists()
    d = json.loads((root / "reports" / "etf_books" / "latest.json").read_text())
    assert d["stale"] and d["status"] == "watch"


def test_the_top_up_is_booked_on_its_day_in_the_paper_book(env):
    cache, root = env
    write_closes(cache, "2026-10-28")
    pb.main([], ms("2026-10-28"), root)
    write_closes(cache, "2026-11-04")
    pb.main([], ms("2026-11-04"), root)
    for br in eq1.BROKERS:
        rows = [r for r in journal(root, "eq1_hold_world_plus50") if r["broker"] == br]
        assert [r["date"] for r in rows if float(r["flow_eur"])] == ["2026-11-02"]
        assert float(rows[-1]["paid_eur"]) == 100.0
        assert all(float(r["flow_eur"]) == 0 for r in journal(root, "eq1_hold_world_once"))
    st = json.loads((root / "paper" / "eq1_hold_world_plus50" / "state.json").read_text())
    assert st["wallets"]["tr"]["plan_eur"] == pytest.approx(100.0) and st["wallets"]["ibkr"]["topups"] == 1


def test_the_report_feeds_the_paper_books_and_the_trials_are_registered_once(env, tmp_path):
    cache, root = env
    write_closes(cache, "2026-10-28")
    pb.main([], ms("2026-10-28"), root)
    pb.main([], ms("2026-10-28"), root)
    books = {b["name"]: b for b in paper_books.books(root)}
    assert set(books) == set(pb.BOOKS) and all(b["study"] == "EQ1" for b in books.values())
    assert books["eq1_trend_sp500_once"]["value"] == 50.0
    assert books["eq1_trend_sp500_once"]["eq1"]["judged"] == "tr"
    if eq1.SUMMARY.exists():
        ids = [r["id"] for r in metrics._read(tmp_path / "registry.jsonl") if r["id"].startswith("small:eq1:")]
        assert len(ids) == len(set(ids)) == 30
