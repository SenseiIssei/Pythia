"""The job table and its runner: parsing, rendering, locking, run records, status,
disk, retention and backup. Host jobs only (no docker), everything under tmp_path.

Run from research/lab:  python -m pytest tests/test_jobs.py
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tarfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from lab.ops import jobs

REPO_TABLE = Path(__file__).resolve().parents[2] / "ops" / "jobs.yaml"
UTC = timezone.utc


def table(tmp_path: Path, jobs_yaml: str, extra: str = "") -> jobs.Table:
    text = f"""
paths:
  data: {tmp_path}/data
  code: {tmp_path}/code
  ops: /opt/pythia-ops
  logs: {tmp_path}/logs
  locks: {tmp_path}/locks
  cron_dir: {tmp_path}/cron.d
  alert_env: {tmp_path}/alerts.env
  min_free_gb: 0
  log_max_mb: 0.001
  log_keep: 2
defaults:
  kind: host
  timeout: 30s
jobs:
{jobs_yaml}
{extra}
"""
    (tmp_path / "data").mkdir(exist_ok=True)
    p = tmp_path / "jobs.yaml"
    p.write_text(text)
    return jobs.load_table(p)


@pytest.fixture(autouse=True)
def no_alerts(monkeypatch):
    sent: list[str] = []
    monkeypatch.setattr(jobs, "_alert", lambda t, text: sent.append(text))
    return sent


# ---------------------------------------------------------------- the YAML subset

def test_repo_table_is_valid_and_matches_pyyaml():
    t = jobs.load_table(REPO_TABLE)
    assert {"backfill", "learn", "notify", "health", "backup", "prune"} <= set(t.jobs)
    assert t.jobs["notify"]["cron"] is None and t.jobs["notify"]["depends_on"] == ["learn"]
    yaml = pytest.importorskip("yaml")
    assert jobs.parse_yaml(REPO_TABLE.read_text()) == yaml.safe_load(REPO_TABLE.read_text())


def test_parser_handles_the_subset():
    v = jobs.parse_yaml("""
a: 1   # comment
b: "x # not a comment"
c: [1, two, "3"]
d: {k: v, n: 2.5}
e:
  - name: x
    deep:
      - 1
      - 2
  - plain
f:
- same indent list
g: >
  folded
  text
h: ~
i: 'it''s'
j: off
""")
    assert v == {"a": 1, "b": "x # not a comment", "c": [1, "two", "3"], "d": {"k": "v", "n": 2.5},
                 "e": [{"name": "x", "deep": [1, 2]}, "plain"], "f": ["same indent list"],
                 "g": "folded text", "h": None, "i": "it's", "j": "off"}


@pytest.mark.parametrize("bad", [
    "a: 1\na: 2",                 # duplicate key
    "a:\n  b: 1\n    c: 2",       # bad indentation
    "a: */5 * * * *",             # unquoted alias-like value
    "a: [1, 2",                   # unclosed
    "a: 1\n\tb: 2",               # tab indentation
])
def test_parser_refuses_what_it_does_not_understand(bad):
    with pytest.raises(jobs.TableError):
        jobs.parse_yaml(bad)


@pytest.mark.parametrize("jobs_yaml,msg", [
    ("  - name: a\n    command: x", "schedule or depends_on"),
    ("  - name: a\n    schedule: \"61 * * * *\"\n    command: x", "out of range"),
    ("  - name: a\n    schedule: \"0 * * *\"\n    command: x", "5 fields"),
    ("  - name: a\n    depends_on: [b]\n    command: x", "unknown job"),
    ("  - name: a\n    depends_on: [b]\n    command: x\n  - name: b\n    depends_on: [a]\n    command: y", "cycle"),
    ("  - name: a\n    schedule: \"0 * * * *\"\n    command: x\n  - name: a\n    schedule: \"0 * * * *\"\n    command: y", "twice"),
    ("  - name: A\n    schedule: \"0 * * * *\"\n    command: x", "lower case"),
    ("  - name: a\n    schedule: \"0 * * * *\"\n    command: x\n    timeout: soon", "bad duration"),
    ("  - name: a\n    schedule: \"0 * * * *\"\n    command: x\n    tiemout: 1h", "unknown keys"),
    ("  - name: a\n    schedule: \"0 * * * *\"", "command is missing"),
    ("  - name: a\n    schedule: \"0 * * * *\"\n    command: x\n    kind: vm", "kind must be"),
])
def test_table_validation(tmp_path, jobs_yaml, msg):
    with pytest.raises(jobs.TableError, match=msg):
        table(tmp_path, jobs_yaml)


# ---------------------------------------------------------------- cron schedules

def test_cron_next_and_previous():
    c = jobs.Cron("30 6 * * *")
    t = datetime(2026, 10, 15, 6, 30, tzinfo=UTC)
    assert c.next_after(t) == datetime(2026, 10, 16, 6, 30, tzinfo=UTC)
    assert c.prev_at_or_before(t) == t
    assert c.prev_at_or_before(t - timedelta(minutes=1)) == datetime(2026, 10, 14, 6, 30, tzinfo=UTC)
    w = jobs.Cron("40 5 * * 0")  # Sundays
    assert w.next_after(t) == datetime(2026, 10, 18, 5, 40, tzinfo=UTC)
    s = jobs.Cron("3-59/15 * * * *")
    assert s.next_after(datetime(2026, 10, 15, 6, 4, tzinfo=UTC)).minute == 18
    assert jobs.Cron("*/5 * * * *").next_after(datetime(2026, 10, 15, 23, 58, tzinfo=UTC)) == \
        datetime(2026, 10, 16, 0, 0, tzinfo=UTC)
    # both day fields restricted: either matches, as cron does
    e = jobs.Cron("0 0 1 * mon")
    assert e.next_after(datetime(2026, 10, 15, tzinfo=UTC)) == datetime(2026, 10, 19, tzinfo=UTC)
    assert jobs.Cron("0 0 * * 7").dows == {0}
    assert jobs.Cron("@hourly").next_after(t) == datetime(2026, 10, 15, 7, 0, tzinfo=UTC)


# ---------------------------------------------------------------- rendering

def test_render_writes_one_cron_file(tmp_path):
    t = table(tmp_path, """
  - name: nightly
    description: the nightly one
    schedule: "30 3 * * *"
    command: echo hi
  - name: after
    depends_on: [nightly]
    command: echo after
  - name: off
    schedule: "*/10 * * * *"
    command: echo off
    enabled: false
""")
    did = jobs.write_cron(t)
    text = (tmp_path / "cron.d" / "pythia-jobs").read_text()
    assert did == [f"wrote {tmp_path}/cron.d/pythia-jobs"]
    lines = [ln for ln in text.splitlines() if ln and not ln.startswith("#") and "=" not in ln]
    assert lines == [f"30 3 * * * root /usr/bin/python3 /opt/pythia-ops/jobs.py --table /opt/pythia-ops/jobs.yaml"
                     f" run nightly >> {tmp_path}/logs/runner.log 2>&1"]
    assert "# disabled: */10 * * * * root" in text
    assert "# after: runs after nightly succeeds." in text
    assert "# nightly: the nightly one" in text
    assert oct((tmp_path / "cron.d" / "pythia-jobs").stat().st_mode & 0o777) == "0o644"
    assert (t.ops_dir / "installed_at").exists()


def test_render_moves_legacy_files_away(tmp_path, monkeypatch):
    t = table(tmp_path, '  - name: a\n    schedule: "0 * * * *"\n    command: x')
    (tmp_path / "cron.d").mkdir()
    (tmp_path / "cron.d" / "pythia-learn").write_text("old")
    (tmp_path / "cron.d" / "other-app").write_text("keep")
    monkeypatch.setenv("PYTHIA_LEGACY_CRON_DIR", str(tmp_path / "legacy"))
    jobs.write_cron(t, prune_legacy=True)
    assert not (tmp_path / "cron.d" / "pythia-learn").exists()
    assert (tmp_path / "legacy" / "pythia-learn").read_text() == "old"
    assert (tmp_path / "cron.d" / "other-app").exists()


def test_render_of_the_repo_table_has_every_enabled_scheduled_job():
    t = jobs.load_table(REPO_TABLE)
    text = jobs.render_cron(t)
    for j in t.jobs.values():
        line = f" run {j['name']} >>"
        if j["cron"] is None:
            assert line not in text
        elif j["enabled"]:
            assert any(ln.startswith(j["schedule"]) and line in ln for ln in text.splitlines())
        else:
            assert f"# disabled: {j['schedule']}" in text


def test_docker_argv(tmp_path):
    t = table(tmp_path, """
  - name: learn
    kind: lab
    schedule: "30 6 * * *"
    command: python -m lab.ops.learn --force "vol x"
    network: host
    env: {PYTHIA_AGENT_OUT: /data/lab-cache}
    env_file: /etc/pythia/alerts.env
    resources: {cpus: 4, memory: 8g}
  - name: backfill
    kind: image
    image: pythia-recorder
    schedule: "30 3 * * *"
    command: python -m recorder.backfill
""")
    a = jobs.build_argv(t, t.jobs["learn"])
    assert a[:7] == ["docker", "run", "--rm", "--name", "pythia-job-learn", "--label", "pythia.job=learn"]
    assert a[a.index("--cpus") + 1] == "4" and a[a.index("--memory") + 1] == "8g"
    assert a[a.index("--network") + 1] == "host" and "--env-file" in a
    assert f"{tmp_path}/code:/app" in a and f"{tmp_path}/data:/data" in a
    assert a[-6:] == ["pythia-lab", "python", "-m", "lab.ops.learn", "--force", "vol x"]
    b = jobs.build_argv(t, t.jobs["backfill"])
    assert f"{tmp_path}/code:/app" not in b and b[-4] == "pythia-recorder"


# ---------------------------------------------------------------- running, records, logs

def test_run_records_success_and_failure(tmp_path, no_alerts):
    t = table(tmp_path, """
  - name: good
    schedule: "0 * * * *"
    command: echo hello from good
  - name: bad
    schedule: "0 * * * *"
    command: echo going down; exit 3
""")
    assert jobs.run_job(t, "good") == 0
    assert jobs.run_job(t, "bad") == 3
    assert jobs.run_job(t, "bad") == 3
    recs = jobs.read_records(t)
    assert [(r["job"], r["status"], r["exit_code"]) for r in recs] == [
        ("good", "ok", 0), ("bad", "failed", 3), ("bad", "failed", 3)]
    assert all(r["duration_s"] >= 0 and r["start"] <= r["end"] for r in recs)
    assert "hello from good" in (tmp_path / "logs" / "good.log").read_text()
    assert jobs.job_state(t, "bad")["consecutive_failures"] == 2
    # one alert for the first failure only
    assert len(no_alerts) == 1 and "job bad failed (exit 3)" in no_alerts[0]
    (tmp_path / "x").write_text("")
    t.jobs["bad"]["command"] = "true"
    assert jobs.run_job(t, "bad") == 0
    assert no_alerts[-1] == "job bad ok again"
    st = json.loads(t.status_path.read_text())
    assert st["ok"] and {j["name"]: j["state"] for j in st["jobs"]} == {"good": "ok", "bad": "ok"}


def test_timeout_kills_the_job(tmp_path):
    t = table(tmp_path, """
  - name: slow
    schedule: "0 * * * *"
    command: sleep 30
    timeout: 1s
""")
    t0 = datetime.now()
    assert jobs.run_job(t, "slow") == 124
    assert (datetime.now() - t0).total_seconds() < 15
    rec = jobs.read_records(t, "slow")[-1]
    assert rec["status"] == "timeout" and rec["exit_code"] == 124
    assert "timeout after 1 s" in (tmp_path / "logs" / "slow.log").read_text()


def test_a_held_lock_skips_the_run(tmp_path):
    t = table(tmp_path, """
  - name: a
    schedule: "0 * * * *"
    command: echo ran > {out}
    lock: heavy
  - name: b
    schedule: "0 * * * *"
    command: echo b
""".replace("{out}", str(tmp_path / "ran")))
    held = jobs.Locks(t.locks, ["heavy"])
    assert held.acquire() is None
    try:
        assert jobs.lock_busy(t.locks, "heavy")
        assert jobs.run_job(t, "a") == 0
        assert not (tmp_path / "ran").exists()
        rec = jobs.read_records(t, "a")[-1]
        assert rec["status"] == "skipped" and rec["reason"] == "lock heavy busy"
        assert jobs.run_job(t, "b") == 0  # another lock is not affected
    finally:
        held.release()
    assert not jobs.lock_busy(t.locks, "heavy")
    assert jobs.run_job(t, "a") == 0 and (tmp_path / "ran").exists()


def test_lock_is_the_same_kernel_lock_as_flock1(tmp_path):
    if not shutil.which("flock"):
        pytest.skip("flock(1) not installed")
    t = table(tmp_path, '  - name: a\n    schedule: "0 * * * *"\n    command: echo a\n    lock_wait: 0')
    t.locks.mkdir(parents=True)
    p = subprocess.Popen(["flock", str(t.locks / "a.lock"), "sleep", "3"])
    try:
        for _ in range(50):
            if jobs.lock_busy(t.locks, "a"):
                break
            import time
            time.sleep(0.05)
        jobs.run_job(t, "a")
        assert jobs.read_records(t, "a")[-1]["status"] == "skipped"
    finally:
        p.kill()
        p.wait()


def test_lock_wait_waits_for_the_lock(tmp_path):
    t = table(tmp_path, '  - name: a\n    schedule: "0 * * * *"\n    command: echo a\n    lock_wait: 5s')
    held = jobs.Locks(t.locks, ["a"])
    held.acquire()
    import threading
    threading.Timer(1.0, held.release).start()
    assert jobs.run_job(t, "a") == 0
    assert jobs.read_records(t, "a")[-1]["status"] == "ok"


def test_chain_and_dependencies(tmp_path):
    out = tmp_path / "order"
    t = table(tmp_path, f"""
  - name: first
    schedule: "30 6 * * *"
    command: echo first >> {out}
  - name: second
    depends_on: [first]
    command: echo second >> {out}
  - name: gated
    schedule: "0 8 * * *"
    depends_on: [first]
    command: echo gated >> {out}
""")
    # before first ever ran, the gated job is blocked, not run
    assert jobs.run_job(t, "gated") == 0
    assert jobs.read_records(t, "gated")[-1]["status"] == "blocked"
    assert jobs.run_job(t, "first") == 0
    assert out.read_text().split() == ["first", "second"]  # second chained
    assert jobs.run_job(t, "gated") == 0
    assert out.read_text().split() == ["first", "second", "gated"]
    # a failing first: no chain, and gated is blocked
    t.jobs["first"]["command"] = "exit 1"
    jobs.run_job(t, "first")
    jobs.run_job(t, "gated")
    assert out.read_text().split() == ["first", "second", "gated"]
    assert jobs.read_records(t, "gated")[-1]["reason"] == "first last ended failed"


def test_disabled_job_does_not_run_unless_forced(tmp_path):
    t = table(tmp_path, f'  - name: a\n    schedule: "0 * * * *"\n    command: touch {tmp_path}/a\n    enabled: false')
    assert jobs.run_job(t, "a") == 0 and not (tmp_path / "a").exists()
    assert jobs.run_job(t, "a", force=True) == 0 and (tmp_path / "a").exists()


def test_host_env_file_reaches_the_command_and_is_not_logged(tmp_path):
    env = tmp_path / "job.env"
    env.write_text("# secrets\nexport TOKEN='s3cret'\nOTHER=1\n")
    t = table(tmp_path, f"""
  - name: a
    schedule: "0 * * * *"
    command: test "$TOKEN" = s3cret && echo token-ok
    env_file: {env}
""")
    assert jobs.run_job(t, "a") == 0
    log = (tmp_path / "logs" / "a.log").read_text()
    assert "token-ok" in log and "s3cret" not in log
    assert "s3cret" not in t.status_path.read_text()
    assert "s3cret" not in "".join(p.read_text() for p in (t.ops_dir / "runs").glob("*.jsonl"))


def test_log_rotation(tmp_path):
    log = tmp_path / "x.log"
    for i in range(4):
        log.write_text(f"run {i}\n" * 300)
        jobs.rotate_log(log, 1000, 2)
    assert not log.exists()
    assert (tmp_path / "x.log.1").read_text().startswith("run 3")
    assert (tmp_path / "x.log.2").read_text().startswith("run 2")
    assert not (tmp_path / "x.log.3").exists()
    assert not jobs.rotate_log(tmp_path / "missing.log", 1000, 2)


# ---------------------------------------------------------------- status

def _fake_run(t, name, start: datetime, status="ok", code=0, minutes=5):
    jobs.append_record(t, {"job": name, "start": jobs._iso(start),
                           "end": jobs._iso(start + timedelta(minutes=minutes)),
                           "duration_s": minutes * 60, "exit_code": code, "status": status, "reason": None})


def test_status_file_states(tmp_path):
    t = table(tmp_path, """
  - name: fine
    schedule: "30 6 * * *"
    command: x
    timeout: 1h
  - name: late
    schedule: "0 4 * * *"
    command: x
    timeout: 1h
  - name: failing
    schedule: "0 5 * * *"
    command: x
  - name: chained
    depends_on: [fine]
    command: x
  - name: fresh
    schedule: "0 9 * * *"
    command: x
  - name: off
    schedule: "0 9 * * *"
    command: x
    enabled: false
""")
    now = datetime(2026, 10, 15, 8, 0, tzinfo=UTC)
    (t.ops_dir).mkdir(parents=True, exist_ok=True)
    (t.ops_dir / "installed_at").write_text("2026-10-14T12:00:00Z\n")
    _fake_run(t, "fine", datetime(2026, 10, 15, 6, 30, tzinfo=UTC))
    _fake_run(t, "late", datetime(2026, 10, 14, 4, 0, tzinfo=UTC))
    _fake_run(t, "failing", datetime(2026, 10, 15, 5, 0, tzinfo=UTC), "failed", 2)
    s = jobs.write_status(t, now)
    on_disk = json.loads(t.status_path.read_text())
    assert on_disk == s
    by = {j["name"]: j for j in s["jobs"]}
    assert by["fine"]["state"] == "ok" and by["fine"]["nextRun"] == "2026-10-16T06:30:00Z"
    assert by["fine"]["lastOk"] == "2026-10-15T06:35:00Z"
    assert by["late"]["state"] == "late" and not by["late"]["ok"]
    assert by["late"]["detail"] == "no run since 2026-10-15T04:00:00Z"
    assert by["failing"]["state"] == "failed" and by["failing"]["consecutiveFailures"] == 1
    assert by["chained"]["state"] == "late"  # fine succeeded at 06:35, chained never ran
    assert by["fresh"]["state"] == "never" and by["fresh"]["ok"]  # its first fire is still ahead
    assert by["off"]["state"] == "disabled" and by["off"]["ok"] and by["off"]["nextRun"] is None
    assert sorted(s["failing"]) == ["chained", "failing", "late"] and not s["ok"]
    # within its timeout plus grace a job is not late yet
    s2 = jobs.build_status(t, datetime(2026, 10, 16, 4, 30, tzinfo=UTC))
    assert {j["name"]: j["state"] for j in s2["jobs"]}["late"] == "late"  # still no run since 10-15
    _fake_run(t, "late", datetime(2026, 10, 16, 4, 0, tzinfo=UTC), minutes=60)
    s3 = jobs.build_status(t, datetime(2026, 10, 16, 4, 30, tzinfo=UTC))
    assert {j["name"]: j["state"] for j in s3["jobs"]}["late"] == "ok"


def test_fires_before_install_are_not_late(tmp_path):
    t = table(tmp_path, '  - name: a\n    schedule: "0 4 * * *"\n    command: x')
    t.ops_dir.mkdir(parents=True)
    (t.ops_dir / "installed_at").write_text("2026-10-15T07:00:00Z\n")
    s = jobs.build_status(t, datetime(2026, 10, 15, 8, 0, tzinfo=UTC))
    assert s["jobs"][0]["state"] == "never" and s["ok"]
    s = jobs.build_status(t, datetime(2026, 10, 16, 8, 0, tzinfo=UTC))
    assert s["jobs"][0]["state"] == "late"


def test_running_and_stuck(tmp_path):
    t = table(tmp_path, '  - name: a\n    schedule: "0 4 * * *"\n    command: x\n    timeout: 1h')
    jobs._write_json(jobs._running_path(t, "a"), {"pid": os.getpid(), "start": "2026-10-15T04:00:00Z"})
    by = jobs.build_status(t, datetime(2026, 10, 15, 4, 30, tzinfo=UTC))["jobs"][0]
    assert by["state"] == "running" and by["ok"] and by["runningSince"] == "2026-10-15T04:00:00Z"
    by = jobs.build_status(t, datetime(2026, 10, 15, 6, 0, tzinfo=UTC))["jobs"][0]
    assert by["state"] == "stuck" and not by["ok"]
    # a marker left by a dead process is ignored
    jobs._write_json(jobs._running_path(t, "a"), {"pid": 2 ** 22 + 12345, "start": "2026-10-15T04:00:00Z"})
    assert not jobs.build_status(t, datetime(2026, 10, 15, 4, 30, tzinfo=UTC))["jobs"][0]["running"]


def test_health_checks_cover_jobs_disk_and_datasets(tmp_path):
    t = table(tmp_path, """
  - name: a
    schedule: "0 4 * * *"
    command: x
  - name: off
    schedule: "0 4 * * *"
    command: x
    enabled: false
""", """
datasets:
  - name: books
    path: paper
    max_gb: 0.000001
  - name: small
    path: small
""")
    (tmp_path / "data" / "paper").mkdir()
    (tmp_path / "data" / "paper" / "j.csv").write_text("x" * 5000)
    checks = {n: (ok, d) for n, ok, d in jobs.health_checks(t, datetime(2026, 10, 15, 8, 0, tzinfo=UTC))}
    assert "job off" not in checks and checks["job a"][0] is False
    assert checks["data books"][0] is False and "limit" in checks["data books"][1]
    assert checks["data small"][0] is True
    assert checks["disk"][0] is True
    assert json.loads(t.status_path.read_text())["disk"]["datasets"][0]["name"] == "books"


def test_disk_growth_from_history(tmp_path):
    t = table(tmp_path, '  - name: a\n    schedule: "0 4 * * *"\n    command: x', """
datasets:
  - name: d
    path: d
""")
    d = tmp_path / "data" / "d"
    d.mkdir()
    (d / "f").write_bytes(b"x" * 1024)
    day0 = datetime(2026, 10, 10, tzinfo=UTC)
    jobs.measure_disk(t, day0)
    assert jobs.measure_disk(t, day0 + timedelta(hours=1))["at"] == jobs._iso(day0)  # cached
    (d / "g").write_bytes(b"x" * (2 * 1024 ** 2))
    out = jobs.measure_disk(t, day0 + timedelta(days=2))
    assert out["datasets"][0]["growthGbPerDay"] == pytest.approx(0.001, abs=0.0006)
    assert out["daysLeft"] is not None and out["daysLeft"] > 14


# ---------------------------------------------------------------- retention

def test_prune_deletes_only_old_matching_files(tmp_path):
    t = table(tmp_path, '  - name: a\n    schedule: "0 4 * * *"\n    command: x', """
datasets:
  - name: reports
    path: reports
    retention_days: 30
    pattern: ["20??-??-??*.json"]
  - name: keep
    path: keep
""")
    r = tmp_path / "data" / "reports" / "forward"
    r.mkdir(parents=True)
    old = time_ago = datetime(2026, 10, 15, tzinfo=UTC).timestamp() - 40 * 86400
    for n in ("2026-08-01.json", "latest.json"):
        (r / n).write_text("{}")
        os.utime(r / n, (old, old))
    (r / "2026-10-14.json").write_text("{}")
    k = tmp_path / "data" / "keep"
    k.mkdir()
    (k / "2020-01-01.json").write_text("{}")
    os.utime(k / "2020-01-01.json", (time_ago, time_ago))
    now = datetime(2026, 10, 15, tzinfo=UTC)
    dry = jobs.prune(t, dry_run=True, now=now)
    assert dry["datasets"][0]["files"] == 1 and (r / "2026-08-01.json").exists()
    rep = jobs.prune(t, now=now)
    assert rep["datasets"] == [{"name": "reports", "files": 1, "bytes": 2, "olderThanDays": 30}]
    assert not (r / "2026-08-01.json").exists()
    assert (r / "latest.json").exists() and (r / "2026-10-14.json").exists()
    assert (k / "2020-01-01.json").exists()


def test_retention_must_be_positive_and_paths_relative(tmp_path):
    with pytest.raises(jobs.TableError, match="at least 1"):
        table(tmp_path, '  - name: a\n    schedule: "0 4 * * *"\n    command: x',
              "datasets:\n  - name: d\n    path: d\n    retention_days: 0")
    with pytest.raises(jobs.TableError, match="relative"):
        table(tmp_path, '  - name: a\n    schedule: "0 4 * * *"\n    command: x',
              "datasets:\n  - name: d\n    path: ../etc")


# ---------------------------------------------------------------- backup

def test_backup_archives_and_rotates(tmp_path):
    t = table(tmp_path, '  - name: a\n    schedule: "0 4 * * *"\n    command: x', f"""
backup:
  dest: {tmp_path}/backup
  keep_daily: 2
  keep_weekly: 2
  include: [paper, models, autopilot/state.json, trials]
""")
    data = tmp_path / "data"
    (data / "paper" / "tsmom").mkdir(parents=True)
    (data / "paper" / "tsmom" / "journal.csv").write_text("date,eq\n")
    (data / "paper" / "tsmom" / "state.json.tmp").write_text("partial")
    (data / "models").mkdir()
    (data / "models" / "champion.json").write_text("{}")
    (data / "autopilot").mkdir()
    (data / "autopilot" / "state.json").write_text("{}")
    start = datetime(2026, 9, 1, 2, 20, tzinfo=UTC)
    outs = [jobs.backup(t, now=start + timedelta(days=i)) for i in range(20)]
    first = outs[0]
    assert first["missing"] == ["trials"] and first["files"] == 3
    with tarfile.open(outs[-1]["archive"]) as tar:
        names = sorted(m.name for m in tar.getmembers() if m.isfile())
    assert names == ["autopilot/state.json", "models/champion.json", "paper/tsmom/journal.csv"]
    left = sorted(p.name for p in (tmp_path / "backup").glob("*.tar.gz"))
    # the last two days, plus the newest of each of the last two ISO weeks
    assert left == ["pythia-state-20260913T022000Z.tar.gz", "pythia-state-20260919T022000Z.tar.gz",
                    "pythia-state-20260920T022000Z.tar.gz"]
    assert len(list((tmp_path / "backup").glob("*.sha256"))) == 3
    assert oct(Path(outs[-1]["archive"]).stat().st_mode & 0o777) == "0o600"
    sha = (tmp_path / "backup" / (Path(outs[-1]["archive"]).name + ".sha256")).read_text().split()[0]
    assert sha == outs[-1]["sha256"]
    dry = jobs.backup(t, dry_run=True, now=start + timedelta(days=21))
    assert dry["dryRun"] and len(left) == len(list((tmp_path / "backup").glob("*.tar.gz")))


def test_backup_refuses_absolute_or_empty(tmp_path):
    t = table(tmp_path, '  - name: a\n    schedule: "0 4 * * *"\n    command: x',
              f"backup:\n  dest: {tmp_path}/b\n  include: [/etc]")
    with pytest.raises(jobs.TableError, match="relative"):
        jobs.backup(t)
    t = table(tmp_path, '  - name: a\n    schedule: "0 4 * * *"\n    command: x',
              f"backup:\n  dest: {tmp_path}/b\n  include: [nothing-here]")
    with pytest.raises(jobs.TableError, match="none of the included"):
        jobs.backup(t)


# ---------------------------------------------------------------- command line

def test_cli(tmp_path, capsys):
    t = table(tmp_path, '  - name: a\n    schedule: "0 4 * * *"\n    command: echo cli')
    p = t.path
    assert jobs.main(["--table", p, "validate"]) == 0
    assert "1 jobs, 0 datasets: ok" in capsys.readouterr().out
    assert jobs.main(["--table", p, "run", "a"]) == 0
    assert jobs.main(["--table", p, "status"]) == 0
    assert json.loads(capsys.readouterr().out)["jobs"][0]["state"] == "ok"
    assert jobs.main(["--table", p, "run", "nope"]) == 2
    assert jobs.main(["--table", str(tmp_path / "missing.yaml"), "validate"]) == 2
    assert jobs.main(["--table", p, "checks"]) == 0
    out = capsys.readouterr().out
    assert "job a\ttrue\t" in out and "disk\t" in out


def test_runs_standalone_with_the_host_python(tmp_path):
    """Cron runs the file directly, next to notify.py, outside the package."""
    ops = tmp_path / "ops"
    ops.mkdir()
    src = Path(jobs.__file__)
    shutil.copy(src, ops / "jobs.py")
    shutil.copy(src.with_name("notify.py"), ops / "notify.py")
    t = table(tmp_path, '  - name: a\n    schedule: "0 4 * * *"\n    command: echo standalone')
    r = subprocess.run(["python3", "-I", str(ops / "jobs.py"), "--table", t.path, "run", "a"],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert "standalone" in (tmp_path / "logs" / "a.log").read_text()


def test_frequent_job_is_late_only_past_its_window(tmp_path):
    t = table(tmp_path, '  - name: a\n    schedule: "*/5 * * * *"\n    command: x\n    timeout: 2m\n    grace: 10m')
    t.ops_dir.mkdir(parents=True)
    (t.ops_dir / "installed_at").write_text("2026-10-01T00:00:00Z\n")
    _fake_run(t, "a", datetime(2026, 10, 15, 8, 0, tzinfo=UTC), minutes=1)
    states = {m: jobs.build_status(t, datetime(2026, 10, 15, 8, m, tzinfo=UTC))["jobs"][0]["state"]
              for m in (4, 12, 16, 18)}
    assert states == {4: "ok", 12: "ok", 16: "ok", 18: "late"}
