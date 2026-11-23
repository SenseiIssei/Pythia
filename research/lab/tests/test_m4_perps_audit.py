"""The m4_perps forward record audit (results/m4_perps_forward_audit_prereg.md) on synthetic journals, bars and
files, and the fixes it led to in the forward report and the book. Offline: no network, no lab data.

Run from research/lab:  python -m pytest tests/test_m4_perps_audit.py
"""

from __future__ import annotations

import csv
import json
import os

import numpy as np
import pytest

from lab import report
from lab.paper import forward_report as fr
from lab.paper import m4_perps as mp
from lab.paper import m4_perps_audit as au

DAY, HOUR = au.DAY_US, au.HOUR_US
T0 = au.day_us("2026-11-01")


def row(date: str, equity: float, gross: float = 0.0, funding: float = 0.0, paper: float = 0.0, model: float = 0.0,
        turnover: float = 0.0, weights: dict | None = None, held: int | None = None, hour: int = 5) -> dict:
    w = weights if weights is not None else {"AUSDT": 0.05, "BUSDT": -0.05}
    return {"date": date, "equity": f"{equity:.2f}", "gross_ret_pct": str(gross), "funding_pct": str(funding),
            "paper_cost_bps": str(paper), "model_cost_bps": str(model), "turnover": str(turnover),
            "held": str(len(w) if held is None else held), "weights": json.dumps(w), "entry_hour_utc": str(hour),
            "model_trained": "2026-10-31", "dropped_unlisted": ""}


# ---------------------------------------------------------------- 1 and 2

def test_arithmetic_flags_only_a_row_that_does_not_add_up():
    e1 = 10_000 * (1 + 0.01 + 0.0001) * (1 - 5e-4)
    j = [row("2026-11-01", e1, gross=1.0, funding=0.01, paper=5.0), row("2026-11-02", e1 * 1.02, gross=2.0),
         row("2026-11-03", e1 * 1.02 * 1.01, gross=0.5)]
    bad = au.arithmetic(j)
    assert [b["date"] for b in bad] == ["2026-11-03"]


def test_calendar_counts_reruns_once_and_missing_days_as_missing():
    j = [row("2026-10-21", 10_000, weights={}, held=0), row("2026-10-21", 10_000, weights={}, held=0),
         row("2026-10-21", 9_994), row("2026-10-22", 10_070), row("2026-10-23", 10_160), row("2026-10-29", 10_300)]
    runs = [{"start_us": au.day_us(r["date"]) + 5 * HOUR, "end_us": au.day_us(r["date"]) + 5 * HOUR + i}
            for i, r in enumerate(j)]
    c = au.calendar(j, runs)
    assert (c["rows"], c["dates"], c["record_days"], c["empty_rows"]) == (6, 4, 4, 2)
    assert c["reruns"] == ["2026-10-21"]
    assert c["missing"] == ["2026-10-24", "2026-10-25", "2026-10-26", "2026-10-27", "2026-10-28"]
    assert [s["date"] for s in c["spans"]] == ["2026-10-29"] and c["spans"][0]["days"] == pytest.approx(6.0)


def test_run_times_take_each_rows_own_run_and_fall_back_to_its_hour():
    j = [row("2026-10-21", 1, hour=15), row("2026-10-21", 1, hour=15), row("2026-10-22", 1, hour=5)]
    runs = [{"start_us": au.day_us("2026-10-21") + 15 * HOUR, "end_us": au.day_us("2026-10-21") + 15 * HOUR + 9},
            {"start_us": au.day_us("2026-10-21") + 16 * HOUR, "end_us": au.day_us("2026-10-21") + 16 * HOUR + 9}]
    t = au.run_times(j, runs)
    assert [x["logged"] for x in t] == [True, True, False]
    assert t[1]["start_us"] == runs[1]["start_us"]
    assert t[2]["start_us"] == au.day_us("2026-10-22") + 5 * HOUR + 30 * 60_000_000


# ---------------------------------------------------------------- 4 and the reference prices

def test_pinned_returns_undo_the_drift():
    prev = {"AUSDT": 0.05, "BUSDT": -0.05, "CUSDT": 0.1, "DUSDT": 0.05}
    r = {"AUSDT": 0.04, "BUSDT": -0.02, "CUSDT": 0.03}
    g = sum(prev[s] * r[s] for s in r)
    cur = {s: prev[s] * (1 + r[s]) / (1 + g) for s in r}
    cur["CUSDT"] = 0.1                                          # capped at 1/k: traded, not pinned
    cur["EUSDT"] = -0.05                                        # new: not pinned; DUSDT left: not pinned
    p = au.pinned(prev, cur, g)
    assert set(p) == {"AUSDT", "BUSDT"}
    assert p["AUSDT"] == pytest.approx(0.04) and p["BUSDT"] == pytest.approx(-0.02)


def write_bars(root, sym: str, rows: list[tuple[int, float, float, float, float]]) -> None:
    import polars as pl
    d = root / "hist" / "binance_spot" / "klines_1h" / f"symbol={sym}"
    d.mkdir(parents=True, exist_ok=True)
    pl.DataFrame({"open_time_us": [r[0] for r in rows], "open": [r[1] for r in rows], "high": [r[2] for r in rows],
                  "low": [r[3] for r in rows], "close": [r[4] for r in rows]}).write_parquet(d / "2026-11.parquet")


def test_prices_interpolate_inside_the_hour_and_bound_by_its_range(tmp_path):
    write_bars(tmp_path, "AUSDT", [(T0 + 5 * HOUR, 100.0, 103.0, 99.0, 102.0),
                                   (T0 + DAY + 5 * HOUR, 110.0, 112.0, 104.0, 106.0)])
    px = au.Prices(tmp_path, T0, T0 + DAY)
    assert px.at("spot", "AUSDT", T0 + 5 * HOUR + HOUR // 4) == pytest.approx(100.5)
    assert px.at("spot", "AUSDT", T0 + 7 * HOUR) is None                       # no bar holds it
    assert px.ret("spot", "AUSDT", T0 + 5 * HOUR, T0 + DAY + 5 * HOUR) == pytest.approx(0.1)
    lo, hi = px.span("AUSDT", T0 + 5 * HOUR + 1, T0 + DAY + 5 * HOUR + 1)
    assert lo == pytest.approx(104 / 103 - 1) and hi == pytest.approx(112 / 99 - 1)
    assert px.at("spot", "ZZZUSDT", T0) is None


def test_files_take_day_and_month_files_that_overlap(tmp_path):
    for n in ("2026-09", "2026-10", "2026-11-01", "2026-11-02", "2026-11-09"):
        (tmp_path / f"{n}.parquet").write_text("")
    got = [p.stem for p in au.files(tmp_path, au.day_us("2026-10-20"), au.day_us("2026-11-02"))]
    assert got == ["2026-10", "2026-11-01", "2026-11-02"]


def test_an_off_coin_day_is_explained_only_by_finer_bars_or_the_hour_range():
    assert au.explain(-0.0902, -0.0899, None) == "minute bars"
    assert au.explain(0.0, None, (-0.025, 0.004)) == "inside the hour bars"
    assert au.explain(0.0, None, (-0.025, -0.012)) is None                   # a stale mark the bars cannot hold
    assert au.explain(0.0, -0.013, (-0.025, -0.012)) is None


def test_spot_and_kraken_symbols():
    assert au.spot_of("1000PEPEUSDT") == "PEPEUSDT" and au.spot_of("BTCUSDT") == "BTCUSDT"
    assert au.kraken_of("BTCUSDT") == "PF_XBTUSD" and au.kraken_of("1000BONKUSDT") == "PF_BONKUSD"
    assert au.hl_spot("kPEPE") == "PEPEUSDT" and au.hl_mult("kPEPE") == 1000 and au.hl_spot("KAVA") == "KAVAUSDT"


# ---------------------------------------------------------------- 3: the decision day the run had

def test_perp_day_known_from_the_archive_file_time(tmp_path):
    d = tmp_path / "hist" / "binance_um" / "klines_1d" / "symbol=BTCUSDT"
    d.mkdir(parents=True)
    p = d / "2026-11-20.parquet"
    p.write_text("")
    written = au.day_us("2026-11-22") + 3 * HOUR + 35 * 60_000_000
    os.utime(p, (written / 1e6, written / 1e6))
    run = au.day_us("2026-11-21") + 5 * HOUR
    assert not au.perp_day_known(au.day_us("2026-11-20"), run, tmp_path)       # written the morning after
    assert au.perp_day_known(au.day_us("2026-11-20"), run + DAY, tmp_path)
    # compacted into the month file: the same two-day rule
    assert au.perp_day_known(au.day_us("2026-10-27"), au.day_us("2026-10-29") + 5 * HOUR, tmp_path)
    assert not au.perp_day_known(au.day_us("2026-10-28"), au.day_us("2026-10-29") + 5 * HOUR, tmp_path)


def test_reconcile_and_drift():
    assert au.reconcile({"A": 0.05, "B": -0.05}, {"A": 0.055, "C": -0.05}) == [
        {"perp": "B", "booked": -0.05, "rebuilt": 0.0}, {"perp": "C", "booked": 0.0, "rebuilt": -0.05}]
    assert au.reconcile({"A": 0.005}, {"A": -0.004})[0]["perp"] == "A"            # opposite sides
    w = au.drift({"A": 0.05, "B": -0.05}, {"A": 0.1, "B": None})
    assert w["A"] == pytest.approx(0.055 / 1.005) and w["B"] == pytest.approx(-0.05 / 1.005)


# ---------------------------------------------------------------- 6: costs

def test_costs_split_the_fill_and_restate_the_ratio_at_the_bands_cost():
    j = [row("2026-11-01", 1, turnover=1.0, paper=5.65, model=41.0),
         row("2026-11-02", 1, turnover=0.1, paper=0.6, model=4.1), row("2026-11-03", 1)]
    c = au.costs(j, 8.77e-4)
    assert c["bad"] == [] and len(c["rows"]) == 2
    assert c["half_bps_per_unit"] == pytest.approx((6.25 - 5.5) / 1.1)
    assert c["ratio_41"] == pytest.approx(6.25 / 45.1)
    assert c["ratio_band"] == pytest.approx(6.25 / (1.1 * 8.77))
    assert au.costs([row("2026-11-01", 1, turnover=1.0, paper=4.0, model=41.0)], None)["bad"] == ["2026-11-01"]


# ---------------------------------------------------------------- the fixes

def write_journal(root, book: str, rows: list[dict]) -> list[dict]:
    d = root / "paper" / book
    d.mkdir(parents=True, exist_ok=True)
    with (d / "journal.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    return fr.read_journal(book, root)


@pytest.fixture()
def reports(tmp_path, monkeypatch):
    monkeypatch.setattr(report, "REPORTS", tmp_path / "reports")
    monkeypatch.setattr(fr, "ROOT", tmp_path)
    return tmp_path


def test_forward_report_counts_a_rerun_once(reports):
    """m4_perps ran three times on 2026-10-21 (two with an empty book): 30 rows through 11-22 were 28 days."""
    rows = [row("2026-10-21", 10_000, weights={}, held=0), row("2026-10-21", 10_000, weights={}, held=0)]
    rows += [row(f"2026-10-{21 + i:02d}", 10_000 * 1.001 ** (i + 1), turnover=0.1 if i % 2 else 0.0)
             for i in range(9)]
    r = fr.book_row("m4_perps", write_journal(reports, "m4_perps", rows))
    assert r["days"] == 9 and r["gate7"]["days"] == 9 and r["elapsed_days"] == 8


def test_forward_report_restates_the_41_bps_model_cost(reports):
    """The journal booked m4_residual's 41 bps a unit traded; the band (M4L) paid 5 bps plus DT1's proxy."""
    rows = [row("2026-11-01", 9_994.35, turnover=1.0, paper=5.65, model=41.0),
            row("2026-11-02", 10_000, turnover=0.1, paper=0.6, model=4.1),
            row("2026-11-03", 10_010, turnover=0.1, paper=0.6, model=0.88)]          # booked after the fix
    c = fr.book_row("m4_perps", write_journal(reports, "m4_perps", rows))["costs"]
    assert c["model_pct"] == pytest.approx((8.8 + 0.88 + 0.88) / 100)
    assert c["ratio"] == pytest.approx(6.85 / 10.56)
    other = fr.book_row("m4_ls", write_journal(reports, "m4_ls", rows))["costs"]      # no other book restated
    assert other["model_pct"] == pytest.approx((41.0 + 4.1 + 0.88) / 100)


def test_the_books_model_cost_is_the_bands():
    """m4_perps' journal model cost per unit traded is what its band's backtest paid: Kraken's taker plus DT1's
    proxy (m4l_series.json: 5.0 + 3.77 bps), the rate the forward report restates old rows at."""
    assert mp.MODEL_COST == pytest.approx(5e-4 + 3.77e-4, abs=0.05e-4)
    assert fr.MODEL_RESTATED["m4_perps"] == (pytest.approx(41e-4), pytest.approx(mp.MODEL_COST))


def test_gap_parts_add_up_to_the_gap(tmp_path):
    """Two books on one coin each, flat funding and costs: the parts and the residual add up to the gap."""
    write_bars(tmp_path, "AUSDT", [(T0 + h * HOUR, 100 + h, 100 + h, 100 + h, 100 + h + 1) for h in range(0, 72)])
    write_bars(tmp_path, "BUSDT", [(T0 + h * HOUR, 50.0, 50.0, 50.0, 50.0) for h in range(0, 72)])
    book = [row(au.date_of(T0 + i * DAY), 10_000 * (1 + 0.01 * i), gross=1.0 if i else 0.0,
                weights={"AUSDT": 0.05}) for i in range(3)]
    twin = [dict(row(au.date_of(T0 + i * DAY), 10_000 * (1 + 0.004 * i), gross=0.4 if i else 0.0,
                     weights={}), equity_usd=str(230.0)) for i in range(1, 3)]
    runs = [{"start_us": T0 + i * DAY + 5 * HOUR, "end_us": T0 + i * DAY + 5 * HOUR} for i in range(3)]
    truns = [{"start_us": T0 + i * DAY + 6 * HOUR, "end_us": T0 + i * DAY + 6 * HOUR} for i in range(1, 3)]
    pos = {twin[0]["date"]: {"B": (0.23, 50.0)}}
    g = au.gap(book, runs, twin, truns, pos, au.Prices(tmp_path, T0, T0 + 2 * DAY))
    assert g["total"] == pytest.approx(0.02 - 0.008, abs=1e-6)
    assert sum(g["parts"].values()) == pytest.approx(g["total"])
    assert g["parts"]["timing"] == pytest.approx(0.01, abs=1e-3)              # the book's day before the twin
    assert np.isfinite(list(g["sub"].values())).all()
