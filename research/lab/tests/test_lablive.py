"""Lab Live (lab.ops.lablive): the graph of everything that runs, from small fixtures of the data folder."""

import json
from pathlib import Path

from lab.ops import lablive

NOW = 1_793_100_000_000            # 2026-10-27 UTC
IP1, IP2 = ".".join(["10", "1", "2", "3"]), ".".join(["10", "0", "0", "7"])   # made up, built so no file holds one
ADDR = "Wa11et" + "x" * 38            # made up, base58 and as long as a wallet address


def put(root: Path, rel: str, data) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")
    return p


def iso(ms: int) -> str:
    return lablive.ms_iso(ms)


def fixture(root: Path) -> None:
    put(root, "_health/jobs.json", {"at": iso(NOW), "jobs": [
        {"name": "features", "enabled": True, "state": "ok", "running": True, "runningSince": "2026-10-27T13:05:00Z",
         "description": "feature store", "nextRun": "2026-10-28T02:20:00Z", "depends_on": []},
        {"name": "models", "enabled": True, "state": "ok", "description": "zoo", "nextRun": "2026-10-28T07:15:00Z",
         "last": {"start": "2026-10-27T07:15:00Z", "end": "2026-10-27T07:40:00Z"}},
        {"name": "flow-collect", "enabled": True, "state": "failed", "detail": f"exit 1 from {IP1} for {ADDR}",
         "consecutiveFailures": 2},
        {"name": "paper", "enabled": True, "state": "ok"},
        {"name": "forward", "enabled": True, "state": "ok", "depends_on": ["paper"]},
        {"name": "briefing", "enabled": True, "state": "ok"},
        {"name": "pumpfun-factory", "enabled": True, "state": "ok"},
        {"name": "pumpfun-live-watch", "enabled": False, "state": "disabled"},
    ]})
    put(root, "_ops/runs/2026-10.jsonl", "\n".join(json.dumps(r) for r in [
        {"job": "models", "start": "2026-10-26T07:15:00Z", "end": "2026-10-26T07:30:00Z", "status": "ok", "duration_s": 900},
        {"job": "models", "start": "2026-10-27T07:15:00Z", "end": "2026-10-27T07:40:00Z", "status": "ok", "duration_s": 1500},
        {"job": "flow-collect", "start": "2026-10-27T00:40:00Z", "status": "failed", "duration_s": 3},
    ]) + "\nnot json\n")
    put(root, "_health/status.json", {"at": iso(NOW - 60_000), "disk_free_gb": 150.2,
                                      "streams": {"kraken": {"stale": False}, "okx_spot": {"stale": False}}})
    put(root, "reports/models/latest.json", {"models": [
        {"code": "M2", "name": "picks_7d", "title": "Weekly coin ranking", "status": "in use", "last_status": "ok",
         "used_by": ["picks_ls (paper)"], "champion": {"version": "2026-10-25"},
         "live": {"model": 0.68, "baseline": 0.69, "gain_pct": 1.2, "win_rate": 0.58,
                  "weeks": [{"gain_pct": 1.0}, {"gain_pct": 2.0}]}},
        {"code": "M7", "name": "regime_hmm", "title": "Regime", "status": "retired"}]})
    put(root, "reports/forward/latest.json", {"generated_ms": NOW - 3_600_000, "books": [
        {"kind": "book", "name": "picks_ls", "label": "Picks long short", "return_pct": -2.5, "max_dd_pct": 4.0,
         "days": 20, "status": "watch", "since": "2026-10-07"}]})
    put(root, "paper/picks_ls/journal.csv", "date,equity,held\n2026-10-25,10000,5\n2026-10-26,9900,6\n2026-10-27,9750,4\n")
    put(root, "reports/pumpfun_rt/factory.json", {"updated_ms": NOW - 3_600_000, "night": "2026-10-27",
                                                  "trials_tonight": 300, "trials_ever": 330,
                                                  "best": [{"id": "F3_00296", "pnl_sol": 0.26}], "books": []})
    put(root, "reports/pumpfun_rt/live_status.json", {"t": NOW - 1000, "running": False, "on": False, "address": ADDR,
                                                      "balance_sol": 0.0415, "pnl_total_sol": -0.4766,
                                                      "trades_total": 149, "positions": [],
                                                      "gate": ["paused by the owner since 12:25 UTC"]})
    put(root, "reports/pumpfun_rt/allocator.json", {"updated_ms": NOW, "choice": "P_pool0_wait",
                                                    "arms": {"P_pool0_wait": {"p_best": 0.73, "weight": 0.7,
                                                                              "rewards": {"2026-10-25": 1.7, "2026-10-26": 0.4}}}})
    put(root, "logs/models.log", "x\n" * 20 + f"done for {ADDR} at {IP2}, token=abc123\nlast line\n")


def test_an_empty_data_folder_gives_an_empty_graph(tmp_path):
    g = lablive.build(tmp_path, NOW)
    assert g["columns"] == list(lablive.COLUMNS)
    assert [n["id"] for n in g["nodes"]] == ["bot:onchain"]          # the trader that never started
    assert g["nodes"][0]["state"] == "off" and g["edges"] == []


def test_the_graph_from_the_data_folder(tmp_path):
    fixture(tmp_path)
    g = lablive.build(tmp_path, NOW, logs=tmp_path / "logs")
    n = {x["id"]: x for x in g["nodes"]}
    # Every column, every kind of node.
    assert {"src:recorder", "job:features", "job:models", "model:M2", "model:M7", "factory:F3", "book:picks_ls",
            "bot:pumpfun", "job:briefing", "model:allocator"} <= set(n)
    assert n["job:flow-collect"]["column"] == "data" and n["job:features"]["column"] == "features"
    assert n["book:picks_ls"]["column"] == "books" and n["bot:pumpfun"]["column"] == "money"
    assert n["job:briefing"]["column"] == "outputs" and n["factory:F3"]["column"] == "factories"
    # States.
    assert n["job:features"]["state"] == "running" and n["job:features"]["now"] == "läuft seit 13:05 UTC"
    assert n["job:flow-collect"]["state"] == "failed"
    assert n["job:pumpfun-live-watch"]["state"] == "off"
    assert n["model:M7"]["state"] == "off" and n["bot:pumpfun"]["state"] == "off"
    assert n["src:recorder"]["state"] == "running"
    assert g["counts"]["failed"] == 1 and sum(g["counts"].values()) == len(g["nodes"])
    # Runs, numbers, history.
    m = n["job:models"]
    assert [r["duration_s"] for r in m["runs"]] == [1500, 900] and m["spark"] == [900, 1500]
    assert m["last_run"] == "2026-10-27T07:40:00Z" and m["next_run"] == "2026-10-28T07:15:00Z"
    bk = n["book:picks_ls"]
    assert {"label": "Rendite", "value": "-2,5 %"} in bk["numbers"]
    assert {"label": "Offene Positionen", "value": "4"} in bk["numbers"] and bk["spark"] == [10000, 9900, 9750]
    m2 = {x["label"]: x["value"] for x in n["model:M2"]["numbers"]}
    assert m2["Letzte Prognose, Fehler"] == "0,6800" and m2["Trefferquote"] == "58 %"
    assert n["model:M2"]["spark"] == [1.0, 2.0]
    f3 = {x["label"]: x["value"] for x in n["factory:F3"]["numbers"]}
    assert f3["Versuche letzte Nacht"] == "300" and f3["Bester Kandidat"] == "F3_00296"
    # The factory's state follows its job; the allocator's next run its job's.
    assert n["factory:F3"]["state"] == "ok"
    # Edges: depends_on, the fixed map, a model to the book that uses it.
    e = {(x["from"], x["to"]) for x in g["edges"]}
    assert ("job:paper", "job:forward") in e and ("job:features", "job:models") in e
    assert ("job:models", "model:M2") in e and ("model:M2", "book:picks_ls") in e
    assert ("job:flow-collect", "job:features") in e and ("book:picks_ls", "job:forward") in e
    assert "job:features" in n["job:models"]["inputs"] and "model:M2" in n["job:models"]["outputs"]
    assert all(a in n and b in n for a, b in e)


def test_logs_are_scrubbed_and_no_address_is_written(tmp_path):
    fixture(tmp_path)
    g = lablive.build(tmp_path, NOW, logs=tmp_path / "logs")
    n = {x["id"]: x for x in g["nodes"]}
    logs = n["job:models"]["logs"]
    assert logs[-1] == "last line" and len(logs) == lablive.LOG_LINES
    assert "done for <adresse> at <ip>, token=<weg>" in logs
    text = json.dumps(g)
    assert ADDR not in text and IP1 not in text and IP2 not in text


def test_main_writes_the_file(tmp_path, monkeypatch):
    fixture(tmp_path)
    monkeypatch.setenv("PYTHIA_DATA", str(tmp_path))
    monkeypatch.delenv("PYTHIA_REPORTS", raising=False)
    monkeypatch.setenv("PYTHIA_LOGS", str(tmp_path / "nologs"))
    assert lablive.main([]) == 0
    g = json.loads((tmp_path / "reports/lablive/latest.json").read_text(encoding="utf-8"))
    assert g["nodes"] and g["edges"] and g["updated_ms"]


def test_aliases_for_the_news():
    g = {"nodes": [{"id": "book:tsmom", "kind": "book", "aliases": ["tsmom"]},
                   {"id": "job:paper", "kind": "job", "aliases": ["paper"]},
                   {"id": "model:M2", "kind": "model", "aliases": ["M2", "picks_7d", ""]}]}
    assert lablive.aliases(g) == {"tsmom": "book:tsmom", "M2": "model:M2", "picks_7d": "model:M2"}


def test_numbers_the_german_way():
    assert lablive.de(1234.5, 1) == "1.234,5" and lablive.de(None) == "-"
    assert lablive.de_pct(2.0) == "+2,0 %" and lablive.de_pct(-0.4) == "-0,4 %"
