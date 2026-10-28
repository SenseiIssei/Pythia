"""W1: the weekly page on a fixture data folder: a ladder move against last week's snapshot, a red job and since
when, a missing report said as missing, the goal and the capital per candidate, the page's files and its short card
through notify ("studies"), the job in the table.

Run from research/lab:  python -m pytest tests/test_weekly.py
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from lab.ops import jobs, notify, weekly

NOW = int(datetime(2026, 11, 1, 18, 0, tzinfo=timezone.utc).timestamp() * 1000)
DAY = 86_400_000
REPO_TABLE = Path(__file__).resolve().parents[2] / "ops" / "jobs.yaml"


def write(root: Path, rel: str, d) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(d if isinstance(d, str) else json.dumps(d), encoding="utf-8")


def ladder_row(name: str, step: int) -> dict:
    return {"id": f"book:{name}", "name": name, "short": name, "kind": "book", "step": step,
            "next_de": "kein getesteter Bericht"}


@pytest.fixture()
def root(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHIA_DATA", str(tmp_path))
    for k in ("PYTHIA_REPORTS", "PYTHIA_ALERT_WEBHOOK", "PYTHIA_TELEGRAM_BOT_TOKEN", "PYTHIA_TELEGRAM_CHAT_ID",
              "PYTHIA_ALERT_VIA", "PYTHIA_DISCORD_BOT_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("PYTHIA_QUIET_HOURS", "off")
    write(tmp_path, "reports/ladder/latest.json", {
        "rows": [ladder_row("small40_spy_trend", 2), ladder_row("tsmom", 0), ladder_row("btc_gated", 1)],
        "registry": {"n_trials": 2690, "sr0_annual": 2.7624}})
    write(tmp_path, "reports/weekly/2026-10-25.json", {
        "date": "2026-10-25", "ladder": {"book:small40_spy_trend": 1, "book:tsmom": 1, "book:btc_gated": 1},
        "books": {"small40_spy_trend": [40.0, "EUR"]}, "failing": ["paper"], "live_pnl_sol": -0.3})
    write(tmp_path, "reports/smallaccount/latest.json", {"books": {"small40_spy_trend": {
        "variant": "EXPERIMENT, paper only · S2 small account · 40 EUR paper wallet · SPY trend · daily",
        "started": "2026-10-22T04:00:00+00:00", "capital_eur": 40.0, "equity_eur": 41.0}}})
    write(tmp_path, "reports/forward/latest.json", {"books": [
        {"kind": "book", "name": "tsmom", "since": "2026-10-02", "return_pct": -6.0}]})
    write(tmp_path, "reports/pumpfun_rt/realistic.json", {
        "sol_eur": 90.0, "small": [], "factory": [],
        "calibration": {"rule": "P_pool0_wait", "n": 14, "live": 41, "paper": 524, "d_pts": -0.4856,
                        "d_pts_mean": -2.742, "days": 4.2, "verdict": "not yet"},
        "selection": {"pts": 1.5, "gate_pts": 2.0, "pass": True}})
    write(tmp_path, "reports/pumpfun_rt/live_status.json", {"pnl_total_sol": -0.4, "trades_total": 149})
    write(tmp_path, "_health/jobs.json", {"jobs": [
        {"name": "paper", "ok": True, "state": "ok"},
        {"name": "ai-analyst", "ok": False, "state": "failed", "lastOk": "2026-10-30T18:00:00Z",
         "consecutiveFailures": 2},
        {"name": "exec-dryrun", "ok": False, "state": "late", "lastOk": None}]})
    write(tmp_path, "_ops/disk/latest.json", {"freeGb": 277.9, "totalGb": 463.9, "growthGbPerDay": 0.858,
                                              "daysLeft": None, "trackedGb": 19.9})
    write(tmp_path, "reports/lanes/101-x.json", {"name": "101-x", "title": "Kleine Konten", "status": "done",
                                                 "at": NOW // 1000 - 86_400})
    write(tmp_path, "reports/lanes/102-y.json", {"name": "102-y", "title": "Alt", "status": "done",
                                                 "at": NOW // 1000 - 30 * 86_400})
    write(tmp_path, "reports/lanes/103-z.json", {"name": "103-z", "title": "Gestoppt", "status": "stopped",
                                                 "at": NOW // 1000 - 3600})
    return tmp_path


def page_text(root: Path) -> str:
    return "\n".join(weekly.build(root, NOW)["lines"])


def test_ladder_move_up_and_back(root):
    t = page_text(root)
    assert "Nach oben: small40_spy_trend 1 Idee -> 2 getestet" in t
    assert "Zurück (gescheitert): tsmom 1 -> 0" in t
    assert "Vorwoche: 2026-10-25 (`reports/weekly/2026-10-25.json`)" in t
    assert "3 Kandidaten, höchste Stufe 2 (getestet), 1 dort (`reports/ladder/latest.json`)" in t


def test_red_job_and_since_when(root):
    t = page_text(root)
    assert ("ai-analyst: fehlgeschlagen, rot seit dem letzten Erfolg 2026-10-30 18:00 UTC (2,0 Tage), "
            "2 Fehlschläge in Folge (`_health/jobs.json`)") in t
    assert "exec-dryrun: überfällig, noch nie erfolgreich" in t
    assert "Wieder grün seit der Vorwoche: paper" in t
    assert "paper:" not in t.split("## Rot")[1].split("Wieder")[0]


def test_missing_report_said_as_missing(root):
    t = page_text(root)
    assert "Papier gegen Backtest: fehlt (`reports/paper_review/latest.json`)" in t
    assert "P3 (10-EUR-Bücher): noch keine Zahlen (`reports/pumpfun_rt/realistic.json`)" in t
    (root / "_health" / "jobs.json").unlink()
    (root / "_ops" / "disk" / "latest.json").unlink()
    (root / "reports" / "ladder" / "latest.json").unlink()
    t = page_text(root)
    assert "Jobs: fehlt (`_health/jobs.json`)" in t
    assert "Platte: fehlt (`_ops/disk/latest.json`)" in t
    assert "Leiter: fehlt (`reports/ladder/latest.json`)" in t
    assert "Kapital je Kandidat: fehlt" in t
    assert "Register: 0 Versuche" not in t and "Register:" in t   # from the trial registry instead


def test_goal_live_paper_and_capital(root):
    t = page_text(root)
    # live: -0.4 against -0.3 a week ago = -0.1 SOL = -9 EUR, a month -38.57 EUR
    assert "Live (pump.fun-Bot): Woche -0,1000 SOL = -9,00 € (Gesamt-P&L gegen 2026-10-25), auf 30 Tage -38,57 €, " \
           "zum Ziel fehlen 218,57 €" in t
    # paper: 41 against 40 EUR = +1 EUR in the week
    assert "Papier: Woche +1,00 € über 1 Bücher in EUR und SOL, auf 30 Tage +4,29 €, zum Ziel fehlen 175,71 €" in t
    # small40_spy_trend: +2.5 % in 10.75 days (paper_books' start is a date), 6.98 % a month, 180 / 0.0698 = 2,580 EUR
    line = next(ln for ln in t.splitlines() if ln.startswith("Kapital für 180 EUR im Monat, small40_spy_trend"))
    assert "2.580,00 €" in line and "(Papier, +7,0 % im Monat, 11 Tage)" in line
    assert "Kapital: keins bei 1 Kandidaten (Papierrendite nicht über 0): tsmom" in t
    assert "Kapital: 1 Kandidaten ohne gemessene Rendite" in t
    assert "Platte: 277,9 von 463,9 GB frei" in t and "Register: 2.690 Versuche" in t


def test_paper_minus_live_lanes(root):
    t = page_text(root)
    assert "Median -0,5 Punkte je Trade, Mittel -2,7 Punkte: noch nicht" in t
    assert "P2 alle Live-Signale: +1,5 Punkte je Trade, Tor unter 2: besteht" in t
    assert "Woche: 1 fertig, 1 gestoppt" in t and "Fertig: Kleine Konten" in t and "Alt" not in t


def test_first_page_without_snapshot(root):
    (root / "reports" / "weekly" / "2026-10-25.json").unlink()
    write(root, "reports/pumpfun_rt/live_trades.json", {"trades": [
        {"exit_ms": NOW - DAY, "pnl_sol": -0.05}, {"exit_ms": NOW - 9 * DAY, "pnl_sol": -1.0}]})
    t = page_text(root)
    assert "Bewegung: keine Vorwoche, nicht messbar" in t
    assert "Live (pump.fun-Bot): Woche -0,0500 SOL = -4,50 € (1 Trades in der Woche)" in t
    assert "seit Start auf 30 Tage" in t and "(keine Vorwoche)" in t


def test_run_writes_page_snapshot_and_posts_studies(root, monkeypatch):
    sent = []
    page = weekly.run(root, NOW, poster=lambda text: (sent.append(text) or True, None))
    d = root / "reports" / "weekly"
    md = (d / "2026-11-01.md").read_text(encoding="utf-8")
    assert md == (d / "latest.md").read_text(encoding="utf-8")
    assert len([ln for ln in md.splitlines() if ln.strip()]) <= weekly.MAX_LINES
    assert "\u2014" not in md
    snap = json.loads((d / "2026-11-01.json").read_text(encoding="utf-8"))
    assert snap["ladder"]["book:small40_spy_trend"] == 2 and snap["failing"] == ["ai-analyst", "exec-dryrun"]
    assert page["sent"]["delivered"] and "Pythia, Woche bis 2026-11-01" in sent[0]
    assert "Rot: 2 Jobs" in sent[0]
    # next week reads this snapshot
    assert weekly.previous(root, "2026-11-08")["date"] == "2026-11-01"
    assert weekly.previous(root, "2026-11-01")["date"] == "2026-10-25"


def test_print_writes_nothing(root, capsys):
    weekly.run(root, NOW, write=False)
    assert "# Pythia, Woche bis 2026-11-01" in capsys.readouterr().out
    assert not (root / "reports" / "weekly" / "latest.md").exists()


def test_job_in_the_table():
    t = jobs.load_table(REPO_TABLE)
    j = t.jobs["weekly-page"]
    assert j["schedule"] == "0 18 * * 0" and j["command"] == "python -m lab.ops.weekly" and j["enabled"]
    assert j["kind"] == "lab" and not j["env_files"] and not j.get("network")
    assert "studies" in notify.CATEGORIES
