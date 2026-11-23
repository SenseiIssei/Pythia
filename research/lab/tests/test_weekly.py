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
    assert "+ F3-Ledger 0" in t                                     # ladder.register_total, the ladder's own total


def test_goal_live_paper_and_capital(root):
    t = page_text(root)
    # live: -0.4 against -0.3 a week ago = -0.1 SOL = -9 EUR, a month -38.57 EUR
    assert "Live (pump.fun-Bot): Woche -0,1000 SOL = -9,00 € (Gesamt-P&L gegen 2026-10-25), auf 30 Tage -38,57 €, " \
           "zum Ziel fehlen 218,57 €" in t
    # wallet growth: 41 against 40 EUR = +1 EUR in the week, a line that does not count (W3)
    assert "Wallet-Wachstum, zählt nicht: Woche +1,00 € über 1 Bücher in EUR und SOL, auf 30 Tage +4,29 € (" in t
    # W2: small40_spy_trend made +2.5 % in 11 days, under 30 days no figure; tsmom has 30 days but no dated reports
    assert "Kapital für" not in t
    assert "Kapital-Regel: eine Zahl nur ab 30 Tagen Aufzeichnung" in t and "minus P2s Lücke +1,5 Punkte" in t
    assert "Kapital: 1 Kandidaten unter 30 Tagen Aufzeichnung: small40_spy_trend" in t
    assert "Kapital: 2 Kandidaten ohne Band" in t
    assert "Platte: 277,9 von 463,9 GB frei" in t and "Register: 2.690 Versuche" in t


# ---- W2: the capital line (results/weekly_capital_line_prereg.md)

def forward_book(root: Path, name: str, steps: list[float], costs: dict | None = None) -> None:
    """A forward book with one dated report a day from 2026-10-01 to 2026-11-01, its return compounding `steps`."""
    v, eq = 0.0, 1.0
    days = [datetime(2026, 10, 1, tzinfo=timezone.utc).timestamp() * 1000 + i * DAY for i in range(len(steps) + 1)]
    for i, t in enumerate(days):
        if i:
            eq *= 1 + steps[i - 1]
        v = (eq - 1) * 100
        p = root / "reports" / "forward" / f"{weekly.day(int(t))}.json"
        d = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"books": []}
        d["books"].append({"kind": "book", "name": name, "since": "2026-10-01", "return_pct": v})
        write(root, p.relative_to(root).as_posix(), d)
    lat = json.loads((root / "reports/forward/latest.json").read_text(encoding="utf-8"))
    lat["books"].append({"kind": "book", "name": name, "since": "2026-10-01", "return_pct": v, "days": 31,
                         "elapsed_days": 31.75} | ({"costs": costs} if costs else {}))
    write(root, "reports/forward/latest.json", lat)


def add_rows(root: Path, *rows: dict) -> None:
    lad = json.loads((root / "reports/ladder/latest.json").read_text(encoding="utf-8"))
    lad["rows"] += list(rows)
    write(root, "reports/ladder/latest.json", lad)


def steady(n: int = 31) -> list[float]:
    return [0.005 + (0.001 if i % 2 else -0.001) for i in range(n)]       # +0.5 % a day, sd 0.1 %


def expected_lower(steps: list[float]) -> float:
    mu = sum(steps) / len(steps)
    sd = (sum((x - mu) ** 2 for x in steps) / (len(steps) - 1)) ** 0.5
    return 30 * (mu - 1.96 * sd / len(steps) ** 0.5)


def cap_line(t: str, name: str) -> str | None:
    return next((ln for ln in t.splitlines() if ln.startswith(f"Kapital für 180 EUR im Monat, {name}:")), None)


def test_capital_from_the_lower_band(root):
    forward_book(root, "steady", steady())
    add_rows(root, ladder_row("steady", 1))
    m = expected_lower(steady())
    line = cap_line(page_text(root), "steady")
    assert line is not None and weekly.eur(180 / m) in line and f"untere Grenze {weekly.pct(m)} im Monat" in line
    assert "Fill-Lücke" not in line and line.endswith("(`reports/forward/latest.json`)")
    assert 0 < m < 30 * 0.005                                               # below the point, above 0


def test_short_record_no_capital(root):
    forward_book(root, "steady", steady(12))                                # 12 days of +0.5 % a day
    lat = json.loads((root / "reports/forward/latest.json").read_text(encoding="utf-8"))
    for b in lat["books"]:
        b["since"] = "2026-10-20" if b["name"] == "steady" else b["since"]
    write(root, "reports/forward/latest.json", lat)
    add_rows(root, ladder_row("steady", 1))
    t = page_text(root)
    assert cap_line(t, "steady") is None
    assert "Kapital: 2 Kandidaten unter 30 Tagen Aufzeichnung: steady, small40_spy_trend" in t


def test_band_below_zero_no_capital(root):
    noisy = [0.002 + (0.03 if i % 2 else -0.03) for i in range(31)]        # point above 0, lower end below
    forward_book(root, "noisy", noisy)
    add_rows(root, ladder_row("noisy", 1))
    assert expected_lower(noisy) < 0 < sum(noisy)
    t = page_text(root)
    assert cap_line(t, "noisy") is None
    assert "Kapital: keins bei 1 Kandidaten (untere Grenze nach Abzügen nicht über 0): noisy" in t


def test_fill_gap_lowers_or_removes(root):
    m = expected_lower(steady())
    # modelled costs 0.31 % of capital over 31.75 days, fills 2x: 0.31 / 100 * 30 / 31.75 * 1 a month off
    forward_book(root, "gap", steady(), {"paper_pct": 0.62, "model_pct": 0.31, "ratio": 2.0, "modelled_only": False})
    # a fill gap under 1 adds nothing; one 20x the model takes the whole band
    forward_book(root, "cheap", steady(), {"paper_pct": 0.1, "model_pct": 1.0, "ratio": 0.1, "modelled_only": False})
    forward_book(root, "dear", steady(), {"paper_pct": 20.0, "model_pct": 1.0, "ratio": 20.0, "modelled_only": False})
    add_rows(root, ladder_row("gap", 1), ladder_row("cheap", 1), ladder_row("dear", 1))
    t = page_text(root)
    g = m - 0.31 / 100 * 30 / 31.75 * 1.0
    line = cap_line(t, "gap")
    assert line is not None and weekly.eur(180 / g) in line and "Fill-Lücke 2,0x abgezogen" in line
    assert "untere Grenze " + weekly.pct(g) in line
    assert weekly.eur(180 / m) in cap_line(t, "cheap") and "Fill-Lücke" not in cap_line(t, "cheap")
    assert cap_line(t, "dear") is None and "nicht über 0): dear" in t


def pumpfun_rule(name: str, lo: float, entries: int, days: float) -> dict:
    return {"id": f"pumpfun:{name}", "name": name, "short": name, "kind": "rule", "step": 1, "family": "pumpfun",
            "pumpfun": {"days_record": days, "entries": entries, "mean": lo + 0.02, "lo": lo, "hi": lo + 0.04}}


def test_pumpfun_per_trade_and_stake_cap(root):
    write(root, "reports/pumpfun_rt/live_status.json", {"pnl_total_sol": -0.4, "trades_total": 149, "ack": {
        "mode": "test", "strategy": "P_x", "max_trade_sol": 0.05, "stake_share": 0.25}})
    # lower band +12 % an entry minus P2's 1.5 points = 10.5 %; 3,000 entries in 30 days = 3,000 a month;
    # the most at 0.05 SOL x 90 EUR: 0.105 x 4.5 x 3,000 = 1,417.50 EUR; 180 EUR take 180 / (0.105 x 3,000) = 0.571 EUR
    # a trade, at a 25 % stake share a wallet of 2.29 EUR
    add_rows(root, pumpfun_rule("P_fast", 0.12, 3000, 30.0),
             pumpfun_rule("P_slow", 0.12, 300, 30.0),             # 141.75 EUR at most: not reachable
             pumpfun_rule("P_young", 0.12, 3000, 20.0),           # under 30 days
             pumpfun_rule("P_thin", 0.01, 3000, 30.0))            # +1 % - 1.5 points: none
    t = page_text(root)
    line = cap_line(t, "P_fast")
    assert line is not None and weekly.eur(180 / (0.105 * 3000) / 0.25) in line
    assert "pump.fun je Trade, untere Grenze nach P2 +10,5 % je Einstieg, 3.000 Trades im Monat" in line
    assert "`reports/pumpfun_rt/live_status.json`" in line and "`reports/ladder/latest.json`" in line
    assert ("Kapital: nicht erreichbar bei 1 Kandidaten (beim Live-Einsatz von höchstens 0,05 SOL je Trade bei keinem "
            "Kapital 180 EUR): P_slow") in t
    assert "Aufzeichnung: P_young, small40_spy_trend" in t
    assert "nicht über 0): P_thin" in t
    assert "Live-Einsatz von höchstens 0,05 SOL), nie aus Wallet-Wachstum" in t
    # without the live ack's cap no pump.fun figure
    write(root, "reports/pumpfun_rt/live_status.json", {"pnl_total_sol": -0.4, "trades_total": 149})
    t = page_text(root)
    assert cap_line(t, "P_fast") is None and "nicht erreichbar" not in t and "(fehlt)" in t


def test_pumpfun_wallet_growth_is_not_capital(root):
    # a 10 EUR book that grew 0.109 to 5.9 SOL in 31 days, its band per entry +0.7 % to +5 %, P2's gap +8.8 points
    real = json.loads((root / "reports/pumpfun_rt/realistic.json").read_text(encoding="utf-8"))
    real["selection"]["pts"] = 8.8
    real["ten"] = [{"book": "P_grow_10eur", "strategy": "P_grow", "start_sol": 0.109, "sol": 5.9, "trades": 2240,
                    "mean": 0.028, "band": [0.0074, 0.05], "days": 31.0, "since_ms": NOW - 31 * DAY, "pass": False}]
    write(root, "reports/pumpfun_rt/realistic.json", real)
    write(root, "reports/pumpfun_rt/live_status.json", {"pnl_total_sol": -0.4, "ack": {"max_trade_sol": 0.05,
                                                                                       "stake_share": 0.25}})
    add_rows(root, ladder_row("P_grow_10eur", 1))
    t = page_text(root)
    assert cap_line(t, "P_grow_10eur") is None and "nicht über 0): P_grow_10eur" in t
    # with P2's gap at 0.4 points: +0.34 % an entry x 2,168 trades a month x 4.5 EUR = 33 EUR, under 180: not reachable
    real["selection"]["pts"] = 0.4
    write(root, "reports/pumpfun_rt/realistic.json", real)
    t = page_text(root)
    assert cap_line(t, "P_grow_10eur") is None and "Kapital 180 EUR): P_grow_10eur" in t


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


def test_the_register_line_is_the_ladders_total(root):
    # results/trial_audit_prereg.md: the page prints the ladder's one total and the registers it sums
    write(root, "reports/ladder/latest.json", {"rows": [], "registry": {
        "n_trials": 7204, "r5_trials": 6119, "f3_trials": 1085, "sr0_annual": 2.91,
        "families": {"factory": 2134, "hand": 2242, "pumpfun": 146, "small": 1597}}})
    t = page_text(root)
    assert "Register: 7.204 Versuche = R5-Register 6.119 (factory 2.134, hand 2.242, pumpfun 146, small 1.597) " \
           "+ F3-Ledger 1.085, Rauschbalken" in t and "2,91 im Jahr" in t


def test_a_red_leak_is_a_red_line_on_the_page(root):
    """T1b (results/leak_coverage_prereg.md): the page said all jobs were green while the health check had a red
    leak; now every red line of the leak report is on it, with its reason."""
    from lab.ops import jobs
    assert weekly.LEAK_RED == jobs.LEAK_RED
    t = page_text(root)
    assert "Leck-Prüfung (T1): fehlt (`reports/leak/latest.json`)" in t
    write(root, "reports/leak/latest.json", {"generated": "2026-11-01T06:02:35+00:00", "checked": 134, "red": 2,
                                             "results": [
        {"kind": "book", "name": "tranches_filtered tsmom_tranches_lowkr", "ok": False,
         "why": "leak: ARBUSDT at 2023-06-08 moves when the data after 2023-06-08 changes (shift, shuffle)"},
        {"kind": "spec", "name": "abc", "ok": False, "why": "leak"},
        {"kind": "book", "name": "families", "ok": True, "why": "no leak"}]})
    page = weekly.build(root, NOW)
    t = "\n".join(page["lines"])
    assert "Leck-Prüfung (T1) vom 2026-11-01: 1 rot von 134 geprüft" in t
    assert ("Leck book tranches_filtered tsmom_tranches_lowkr: leak: ARBUSDT at 2023-06-08 moves when the data "
            "after 2023-06-08 changes (shift, shuffle) (`reports/leak/latest.json`)") in t
    assert "spec abc" not in t and "Lecks: 1 rot" in page["short"]
    assert page["snapshot"]["leaks"] == ["book tranches_filtered tsmom_tranches_lowkr"]
    assert len([ln for ln in page["lines"] if ln.strip()]) <= weekly.MAX_LINES


def test_disk_line_from_the_fall_and_days_left(root):
    # _ops/disk/latest.json of 2026-11-16: the page said "Daten 32,5 GB, wachsen 0,72 GB am Tag, voll in 37 Tagen",
    # the tracked growth next to days left that come from the fall in free space
    disk = {"freeGb": 166.7, "totalGb": 463.9, "growthGbPerDay": 0.723, "freeFallGbPerDay": {"3d": 4.66, "7d": 5.39},
            "daysLeft": 30.9, "trackedGb": 32.7, "untrackedGb": 264.5,
            "topGrowing": [{"part": "docker build cache", "gbPerDay": 2.1}, {"part": "journald", "gbPerDay": 0.8}]}
    write(root, "_ops/disk/latest.json", disk)
    t = page_text(root)
    line = next(ln for ln in t.splitlines() if ln.startswith("Platte:"))
    assert "fällt 5,39 GB am Tag, voll in 31 Tagen" in line
    assert round(disk["freeGb"] / 5.39) == round(disk["daysLeft"]) == 31     # the line agrees with daysLeft
    assert "wächst am meisten: docker build cache +2,10 GB am Tag, journald +0,80 GB am Tag" in line
    assert "Datensätze 32,7 GB, +0,72 GB am Tag" in line and "reports/disk/breakdown.md" in line
    assert "wachsen 0,72" not in line
    disk.update(freeFallGbPerDay={"3d": -1.0, "7d": None}, daysLeft=None, topGrowing=[])
    write(root, "_ops/disk/latest.json", disk)
    line = next(ln for ln in page_text(root).splitlines() if ln.startswith("Platte:"))
    assert "kein Volllaufen absehbar" in line and "wächst am meisten" not in line


def test_days_without_a_run_are_missing_not_zero(root):
    """m4_perps' audit: the job did not run from 2026-11-05 to 11-09, the dated reports kept printing its last run
    (+7.82 % from 11-04 on); those reports are no point, and the next run's step covers all its days."""
    start = datetime(2026, 10, 1, tzinfo=timezone.utc).timestamp() * 1000
    runs = list(range(0, 10)) + list(range(15, 20))           # no run on days 10 to 14, the reports go on
    eq, v, rows = 1.0, {}, []
    for i in range(20):
        if i in runs:
            eq *= 1.01 if i % 2 else 0.995
            v[i] = (eq - 1) * 100
        last = max(r for r in runs if r <= i)
        day = weekly.day(int(start + i * DAY))
        write(root, f"reports/forward/{day}.json", {"books": [
            {"kind": "book", "name": "gappy", "since": "2026-10-01", "return_pct": v[last],
             "last": weekly.day(int(start + last * DAY))}]})
    pts = weekly.history(root, "forward/latest.json", "gappy", {})
    assert [weekly.day(t) for t, _, _ in pts] == [weekly.day(int(start + i * DAY)) for i in runs]
    steps = [(b[1] / a[1] - 1) / ((b[0] - a[0]) / DAY) for a, b in zip(pts, pts[1:])]
    assert len(steps) == len(runs) - 1 and 0.0 not in steps
    assert weekly.lower_monthly(pts) == pytest.approx(expected_lower(steps))


def test_days_without_a_run_are_no_days_of_record(root):
    """31 calendar days since the start but 28 days the book ran on (forward's `days`): under 30, no figure."""
    forward_book(root, "steady", steady())
    add_rows(root, ladder_row("steady", 1))
    assert cap_line(page_text(root), "steady") is not None
    lat = json.loads((root / "reports/forward/latest.json").read_text(encoding="utf-8"))
    for b in lat["books"]:
        b["days"] = 28 if b["name"] == "steady" else b.get("days")
    write(root, "reports/forward/latest.json", lat)
    t = page_text(root)
    assert cap_line(t, "steady") is None and "unter 30 Tagen Aufzeichnung: steady" in t


# ---- W3: the paper line by the capital rule (results/weekly_paper_line_prereg.md)

def paper_line(t: str) -> str:
    return next(ln for ln in t.splitlines() if ln.startswith("Papier nach der Kapital-Regel:"))


def small_book(root: Path, name: str, steps: list[float], capital: float = 40.0) -> None:
    """A small-account EUR book started 2026-10-01 with one dated report a day, its equity compounding `steps`."""
    eq = capital
    for i in range(len(steps) + 1):
        if i:
            eq *= 1 + steps[i - 1]
        t = int(datetime(2026, 10, 1, tzinfo=timezone.utc).timestamp() * 1000 + i * DAY)
        rel = f"reports/smallaccount/{weekly.day(t)}.json"
        p = root / rel
        d = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"books": {}}
        d["books"][name] = {"started": "2026-10-01T00:00:00+00:00", "capital_eur": capital, "equity_eur": eq}
        write(root, rel, d)
    lat = json.loads((root / "reports/smallaccount/latest.json").read_text(encoding="utf-8"))
    lat["books"][name] = {"variant": "EXPERIMENT, paper only · S1 small account · 40 EUR paper wallet · x · daily",
                          "started": "2026-10-01T00:00:00+00:00", "capital_eur": capital, "equity_eur": eq}
    write(root, "reports/smallaccount/latest.json", lat)


def ten_book(root: Path, sol: float, lo: float = 0.12, gap: float = 1.5, trades: int = 3000, days: float = 30.0):
    real = json.loads((root / "reports/pumpfun_rt/realistic.json").read_text(encoding="utf-8"))
    real["selection"]["pts"] = gap
    real["ten"] = [{"book": "P_grow_10eur", "strategy": "P_grow", "start_sol": 0.109, "sol": sol, "trades": trades,
                    "band": [lo, lo + 0.04], "days": days, "since_ms": NOW - int(days * DAY), "pass": False}]
    write(root, "reports/pumpfun_rt/realistic.json", real)
    write(root, "reports/pumpfun_rt/live_status.json", {"pnl_total_sol": -0.4, "ack": {"max_trade_sol": 0.05,
                                                                                       "stake_share": 0.25}})


def test_paper_line_no_book_counts(root):
    page = weekly.build(root, NOW)
    t = "\n".join(page["lines"])
    line = paper_line(t)
    assert line.startswith("Papier nach der Kapital-Regel: +0,00 € im Monat aus 0 Büchern mit 30 Tagen und Band")
    assert "zum Ziel fehlen 180,00 €" in line and "weekly_paper_line_prereg.md" in line
    # small40_spy_trend has 10 days, tsmom 30 days but no dated reports: named, not added
    assert "Papier, nicht addiert: 1 unter 30 Tagen (small40_spy_trend); 1 ohne Band (tsmom) (" in t
    assert "Papier (Kapital-Regel): Monat +0,00 € aus 0 Büchern, fehlen 180,00 €" in page["short"]
    assert not any(s.startswith("Papier: ") or "Wallet" in s for s in page["short"])
    assert "Papier: Woche" not in t and "Wallet-Wachstum, zählt nicht: Woche +1,00 €" in t


def test_paper_line_one_book_counts_at_its_money_paid_in(root):
    small_book(root, "small40_steady", steady(), 40.0)     # 31 days, grew about 17 %: the band times 40, not 46.8
    forward_book(root, "steady", steady())                 # a forward book in %: no stake in EUR, not added
    m = expected_lower(steady())
    t = page_text(root)
    line = paper_line(t)
    assert f"{weekly.eur(m * 40, True)} im Monat aus 1 Büchern" in line
    assert f"zum Ziel fehlen {weekly.eur(180 - m * 40)}" in line and f": small40_steady {weekly.eur(m * 40, True)} (" in line
    assert "1 ohne Einsatz in EUR (steady)" in t


def test_paper_line_pumpfun_cap_and_p2_gap(root):
    # a 10 EUR book that grew to 5.9 SOL: half its wallet would be 2.95 SOL a trade, the cap takes 0.05;
    # lower end +12 % minus P2's 1.5 points = 10.5 % x 0.05 SOL x 90 EUR x 3,000 trades = 1,417.50 EUR a month
    ten_book(root, 5.9)
    line = paper_line(page_text(root))
    assert ": P_grow_10eur +1.417,50 € (" in line and "+1.417,50 € im Monat aus 1 Büchern" in line
    assert "beim Einsatz von höchstens 0,05 SOL" in line and "zum Ziel fehlen 0,00 €" in line
    # P2's gap at 8.8 points: (0.12 - 0.088) x 4.5 x 3,000 = 432 EUR
    ten_book(root, 5.9, gap=8.8)
    assert ": P_grow_10eur +432,00 € (" in paper_line(page_text(root))
    # a band per entry below P2's gap is added as it is: (0.0074 - 0.088) x 4.5 x 3,000 = -1,088.10 EUR
    ten_book(root, 5.9, lo=0.0074, gap=8.8)
    line = paper_line(page_text(root))
    assert "-1.088,10 € im Monat aus 1 Büchern" in line and "zum Ziel fehlen 1.268,10 €" in line


def test_paper_line_pumpfun_stake_under_the_cap(root):
    # a wallet that shrank to 0.06 SOL stakes half of it, 0.03 SOL: 0.105 x 0.03 x 90 x 3,000 = 850.50 EUR
    ten_book(root, 0.06)
    assert ": P_grow_10eur +850,50 € (" in paper_line(page_text(root))
    from lab.pumpfun_rt import realistic
    assert weekly.TEN_SHARE == realistic.TEN_SHARE
    # under 30 days or without the live cap: not added
    ten_book(root, 5.9, days=20.0)
    t = page_text(root)
    assert "aus 0 Büchern" in paper_line(t) and "2 unter 30 Tagen (P_grow_10eur, small40_spy_trend)" in t
    ten_book(root, 5.9)
    write(root, "reports/pumpfun_rt/live_status.json", {"pnl_total_sol": -0.4})
    t = page_text(root)
    assert "aus 0 Büchern" in paper_line(t) and "höchstens (fehlt)" in paper_line(t)
    assert "2 ohne Band (P_grow_10eur, tsmom)" in t
