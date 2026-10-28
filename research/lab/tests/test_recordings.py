"""T13 recordings inventory: a fake data folder and a fake code tree, a reader found by its path and by its loader.

Run from research/lab:  python -m pytest tests/test_recordings.py
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from lab.ops import jobs, recordings as R

UTC = timezone.utc
NOW = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
GB = 1024 ** 3
REPO_TABLE = Path(__file__).resolve().parents[2] / "ops" / "jobs.yaml"


def put(p: Path, text: str = "x", size: int | None = None, age_days: float = 0) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text if size is None else "x" * size, encoding="utf-8")
    t = NOW.timestamp() - age_days * 86400
    os.utime(p, (t, t))


CODE = {
    "lab/__init__.py": "",
    # the loaders: a path built from the data root, one stopped at a variable
    "lab/data.py": '''
import os
from pathlib import Path
import polars as pl
ROOT = Path(os.environ.get("PYTHIA_DATA", "/data"))


def live(source, table):
    return pl.scan_parquet(ROOT / source / table / "**" / "*.parquet")


def load_alpha():
    return pl.read_parquet(ROOT / "alpha" / "a.parquet")
''',
    "lab/collect/__init__.py": "",
    # the collectors: write their folder, and look at their own file (not a read)
    "lab/collect/alpha.py": '''
from ..data import ROOT


def run(df):
    d = ROOT / "alpha"
    if (d / "a.parquet").exists():
        return
    d.mkdir(parents=True, exist_ok=True)
    df.write_parquet(d / "a.parquet")


if __name__ == "__main__":
    run(None)
''',
    "lab/collect/delta.py": '''
from ..data import ROOT


def main():
    with open(ROOT / "delta" / "big.bin", "ab") as f:
        f.write(b"x")


if __name__ == "__main__":
    main()
''',
    # a private write helper is a write too
    "lab/collect/zeta.py": '''
from ..data import ROOT


def _write(p, payload):
    p.write_bytes(payload)


def main():
    _write(ROOT / "zeta" / "z.bin", b"")
''',
    "lab/paper/__init__.py": "",
    # a book: reads alpha only through the loader's name
    "lab/paper/book.py": '''
import os
from pathlib import Path
from .. import data as D
from ..data import load_alpha


def data_root():
    return Path(os.environ.get("PYTHIA_DATA", "/data"))


def main():
    return load_alpha(), D.ROOT, (data_root() / "stray" / "s.bin").exists()


if __name__ == "__main__":
    main()
''',
    "lab/experiments/__init__.py": "",
    # a study: the loader with string arguments (live("beta", "ticks") is beta/ticks)
    "lab/experiments/study.py": '''
from ..data import live


def main():
    return live("beta", "ticks").collect()


if __name__ == "__main__":
    main()
''',
    # a study only a disabled job runs: still a study
    "lab/experiments/direct.py": '''
import json
from ..data import ROOT

STATE = ROOT / "gamma" / "x.json"


def main():
    return json.loads(STATE.read_text())


if __name__ == "__main__":
    main()
''',
    # a library nobody runs reads epsilon: no reader
    "lab/lib.py": '''
from .data import ROOT


def eps():
    return (ROOT / "epsilon" / "e.bin").read_bytes()
''',
    # the app reads the stray folder by its string path; a test file is no reader
    "src/app.ts": 'const p = `${DATA}/stray/s.bin`;\nconst q = path.join(dataDir, "alpha", "a.parquet");\n',
    "src/app.test.ts": 'const p = `${DATA}/delta/big.bin`;\n',
    "lab/tests/test_x.py": 'from lab.data import ROOT\nX = (ROOT / "delta" / "big.bin").read_bytes()\n',
}

TABLE = {
    "jobs": [
        {"name": "alpha-collect", "command": "python -m lab.collect.alpha"},
        {"name": "delta-collect", "command": "python -m lab.collect.delta"},
        {"name": "paper-book", "command": "python -m lab.paper.book"},
        {"name": "zeta-collect", "command": "python -m lab.collect.zeta"},
        {"name": "direct", "command": "python -m lab.experiments.direct", "enabled": False},
    ],
    "datasets": [{"name": n, "path": n} for n in ("alpha", "beta", "gamma", "delta", "epsilon", "zeta")],
    "backup": {"include": ["epsilon"]},
}


@pytest.fixture()
def world(tmp_path):
    code, data, results = tmp_path / "code", tmp_path / "data", tmp_path / "results"
    for rel, text in CODE.items():
        put(code / rel, text)
    put(data / "alpha" / "a.parquet", size=1000)
    put(data / "beta" / "ticks" / "date=2026-10-27" / "p.parquet", size=500, age_days=1)
    put(data / "beta" / "ticks" / "date=2026-09-01" / "p.parquet", size=300, age_days=57)
    put(data / "gamma" / "x.json")
    for i in range(25):     # keyed by symbol: no parts
        put(data / "beta" / "many" / f"S{i:02d}" / "f.bin")
    put(data / "delta" / "big.bin", size=4000)
    put(data / "epsilon" / "e.bin", size=10)
    put(data / "zeta" / "z.bin", size=10)
    put(data / "stray" / "s.bin", size=2000, age_days=3)
    put(data / "stray" / "old.bin", size=1000, age_days=20)
    # the disk history: delta grows 0.1 GB a day, zeta 0.05, alpha nothing; 13 days of record
    hist = []
    for i in range(14):
        at = NOW - timedelta(days=13 - i)
        hist.append({"at": at.strftime("%Y-%m-%dT%H:%M:%SZ"), "free": 100 * GB,
                     "sizes": {"alpha": 1000, "delta": int(i * 0.1 * GB), "zeta": int(i * 0.05 * GB),
                               "epsilon": int(i * 0.2 * GB)}})
    put(data / "_ops" / "disk" / "history.jsonl", "".join(json.dumps(h) + "\n" for h in hist))
    put(results / "zeta_study.md", "# Z: an old look\n\nRun 2026-05-02 on `<data>/zeta`.\n")
    put(results / "recordings_t13.md", "# T13\n\nRun 2026-10-28: stop `<data>/delta`.\n")
    put(results / "beta_study.md", "# B\n\nRun 2026-10-20 with `lab.experiments.study`.\n")
    return R.build(NOW, data=data, roots=[code], table=TABLE, results=results)


def row(d: dict, name: str) -> dict:
    return next(r for r in d["rows"] if r["name"] == name)


def test_a_reader_by_its_loaders_name_and_the_collectors_own_look_is_no_read(world):
    a = row(world, "alpha")
    assert a["writers"] == ["job:alpha-collect"]
    assert "book:paper-book" in a["readers"] and "job:alpha-collect" not in a["readers"]
    assert "service:app:app.ts" in a["readers"], "path.join(dataDir, 'alpha', ...) in the app"
    assert a["verdict"] == "read by a book or job"


def test_a_reader_by_its_path_through_a_loader_with_string_arguments(world):
    b = row(world, "beta/ticks")
    assert b["kind"] == "part" and b["parent"] == "beta"
    assert b["readers"] == ["study:lab.experiments.study"]
    assert b["verdict"] == row(world, "beta")["verdict"] == "read by a study only"
    assert b["lastStudy"] == {"file": "results/beta_study.md", "date": "2026-10-20"}
    # no history for a part: the bytes modified in the window, an upper bound
    g = b["growthGbPerDay"]
    assert g["upperBound"] is True and g["7d"] == pytest.approx(500 / GB / 7, rel=1e-3)
    assert g["30d"] == pytest.approx(500 / GB / 30, rel=1e-3)
    assert not any(r["path"].startswith("beta/ticks/date=") for r in world["rows"]), "a partition is no part"
    assert row(world, "beta/many")["kind"] == "part"
    assert not any(r["path"].startswith("beta/many/S") for r in world["rows"]), "25 symbol folders are no parts"


def test_a_disabled_jobs_module_is_a_study_and_a_library_nobody_runs_is_no_reader(world):
    assert row(world, "gamma")["readers"] == ["study:lab.experiments.direct"]
    assert row(world, "gamma")["verdict"] == "read by a study only"
    e = row(world, "epsilon")
    assert e["readers"] == [] and e["verdict"] == "read by nobody"
    assert (e["proposal"], e["why"]) == ("keep", "in the backup (state that cannot be rebuilt)")


def test_nobody_reads_delta_tests_do_not_count_and_it_costs_three_gb_a_month(world):
    d = row(world, "delta")
    assert d["writers"] == ["job:delta-collect"] and d["readers"] == []
    assert d["verdict"] == "read by nobody"
    g = d["growthGbPerDay"]
    assert g["upperBound"] is False and g["7d"] == pytest.approx(0.1, abs=1e-6)
    assert g["30d"] == pytest.approx(0.1, abs=1e-6) and g["spanDays"]["30d"] == 13.0
    assert d["gbPerMonth"] == pytest.approx(3.0, abs=1e-3)
    assert d["proposal"] == "stop" and "no study ever used it" in d["why"]


def test_a_study_long_ago_thins_out(world):
    z = row(world, "zeta")
    assert z["writers"] == ["job:zeta-collect"], "_write(ROOT / 'zeta' / ...)"
    assert z["verdict"] == "read by nobody" and z["gbPerMonth"] == pytest.approx(1.5, abs=1e-3)
    assert z["lastStudy"] == {"file": "results/zeta_study.md", "date": "2026-05-02"}
    assert z["proposal"] == "thin out" and "179 days ago" in z["why"]


def test_a_folder_outside_the_table_is_its_own_row(world):
    s = row(world, "stray")
    assert s["kind"] == "folder" and s["bytes"] == 3000
    assert s["readers"] == ["book:paper-book", "service:app:app.ts"], "data_root() / 'stray' in the book"
    assert s["verdict"] == "read by a book or job"
    assert s["growthGbPerDay"]["7d"] == pytest.approx(2000 / GB / 7, rel=1e-3)
    assert s["growthGbPerDay"]["30d"] == pytest.approx(3000 / GB / 30, rel=1e-3)
    # _ops (the disk history) holds no dataset of this table: a folder too, and nobody's code reads it here
    assert row(world, "_ops")["kind"] == "folder" and row(world, "_ops")["proposal"] == "keep"
    assert {r["name"] for r in world["rows"] if r["kind"] != "part" and r["verdict"] == "read by nobody"} == \
        {"delta", "epsilon", "zeta", "_ops"}
    assert world["nobodyGbPerMonth"] == pytest.approx(3.0 + 1.5 + 6.0, abs=1e-2)


def test_markdown_and_publish(world, tmp_path, monkeypatch):
    md = R.markdown(world)
    assert "| **delta** | delta |" in md and "stop: 3.00 GB a month and no study ever used it" in md
    assert "≤ " in md, "an upper bound is marked"
    assert "\u2014" not in md
    monkeypatch.setenv("PYTHIA_REPORTS", str(tmp_path / "reports"))
    R.publish(world)
    out = json.loads((tmp_path / "reports" / "recordings" / "latest.json").read_text())
    assert out["counts"] == world["counts"]
    assert (tmp_path / "reports" / "recordings" / "latest.md").read_text(encoding="utf-8") == md


def test_paths_wildcards_and_text():
    known = frozenset({"kraken", "kraken/book20", "binance", "binance/book20", "hist", "hist/x"})
    assert R.matches("*/book20", "kraken", known) and R.matches("*/book20", "binance/book20", known)
    assert not R.matches("*/book20", "hist", known), "hist/book20 does not exist"
    assert not R.matches("*", "hist", known) and not R.matches("", "hist", known)
    assert R.matches("hist/x/symbol=/*", "hist/x") and not R.matches("hist", "hist/x")
    assert R._extend("*/**/*.parquet", "spread/kraken_binance") == "spread/kraken_binance/**/*.parquet"
    assert R._extend("hist/um/*/symbol=/*", "funding") == "hist/um/funding/symbol=/*"
    assert R._extend("alpha", "x") == "alpha"
    got = R.text_paths('a = "/data/paper/x.json"; b = `${root}/free/hyperliquid`;\n'
                       'c = data.join("reports").join("notify"); -v "$data/models:/models"\n'
                       'url = "https://example.org/a/b"; route = "/api/lab/live"')
    assert {"paper/x.json", "free/hyperliquid", "reports/notify", "models"} <= got
    assert not any(p.startswith(("http", "api")) for p in got)


def test_history_growth_needs_a_day():
    h = [{"at": "2026-10-28T00:00:00Z", "sizes": {"a": 0}}, {"at": "2026-10-28T06:00:00Z", "sizes": {"a": GB}}]
    assert R.history_growth(h, "a", 7) is None
    h.insert(0, {"at": "2026-10-20T00:00:00Z", "sizes": {"a": 0}})
    assert R.history_growth(h, "a", 7) is None, "the 8-day-old entry is outside the window"
    assert R.history_growth(h, "a", 30) == (pytest.approx(GB / GB / 8.25), 8.2)


def test_the_weekly_job_is_in_the_table():
    t = jobs.load_table(REPO_TABLE)
    j = t.job("recordings")
    assert j["command"] == "python -m lab.ops.recordings" and j.get("enabled", True) is not False
    assert j["schedule"].split()[4] != "*", "weekly"
