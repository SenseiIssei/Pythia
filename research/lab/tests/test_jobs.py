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
    monkeypatch.setattr(jobs, "_alert", lambda t, key, **kw: sent.append(jobs.alert_text(key, "en", **kw)))
    return sent


def test_job_alerts_in_german():
    text = jobs.alert_text("job_failed", "de", name="backfill", status="failed", code=3, s=12, log="/var/log/x.log")
    assert text == "Job backfill fehlgeschlagen (Exit-Code 3) nach 12 s; Protokoll /var/log/x.log"
    assert jobs.alert_text("job_ok_again", "de", name="backfill") == "Job backfill läuft wieder"
    assert jobs.alert_text("job_failed", "en", name="b", status="timeout", code=124, s=60, log="l") == \
        "job b timeout (exit 124) after 60 s; log l"


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
    t = table(tmp_path, '  - name: a\n    schedule: "0 * * * *"\n    command: x\n    replaces: pythia-learn')
    (tmp_path / "cron.d").mkdir()
    (tmp_path / "cron.d" / "pythia-learn").write_text("old")
    (tmp_path / "cron.d" / "pythia-retrain").write_text("retired")
    (tmp_path / "cron.d" / "pythia-unrelated").write_text("keep")
    (tmp_path / "cron.d" / "other-app").write_text("keep")
    monkeypatch.setenv("PYTHIA_LEGACY_CRON_DIR", str(tmp_path / "legacy"))
    jobs.write_cron(t, prune_legacy=True)
    assert not (tmp_path / "cron.d" / "pythia-learn").exists()
    assert (tmp_path / "legacy" / "pythia-learn").read_text() == "old"
    assert (tmp_path / "legacy" / "pythia-retrain").read_text() == "retired"
    assert (tmp_path / "cron.d" / "pythia-unrelated").exists()  # no job replaces it
    assert (tmp_path / "cron.d" / "other-app").exists()
    assert "\n0 * * * * root " in (tmp_path / "cron.d" / "pythia-jobs").read_text()


def test_a_job_is_held_while_its_hand_written_cron_file_exists(tmp_path, monkeypatch):
    t = table(tmp_path, """
  - name: learn
    schedule: "30 6 * * *"
    command: x
    replaces: pythia-learn
  - name: digest
    schedule: "35 6 * * *"
    command: y
    replaces: [pythia-learn]
  - name: fresh
    schedule: "0 * * * *"
    command: z
""")
    (tmp_path / "cron.d").mkdir()
    (tmp_path / "cron.d" / "pythia-learn").write_text("30 6 * * * root docker run ...")
    monkeypatch.setenv("PYTHIA_JOBS_NOW", "2026-10-15T05:00:00Z")
    did = jobs.write_cron(t)
    text = (tmp_path / "cron.d" / "pythia-jobs").read_text()
    live = [ln for ln in text.splitlines() if ln and not ln.startswith("#") and " root " in ln]
    assert len(live) == 1 and " run fresh " in live[0]  # never twice: the old file still runs learn
    assert f"# held while {tmp_path}/cron.d/pythia-learn exists: 30 6 * * * root" in text
    assert any("held until" in d and "digest, learn" in d for d in did)
    assert jobs.legacy_present(t) == {"pythia-learn": ["learn", "digest"]}

    monkeypatch.setenv("PYTHIA_JOBS_NOW", "2026-10-15T12:00:00Z")
    s = {j["name"]: j for j in jobs.build_status(t)["jobs"]}
    assert s["learn"]["state"] == "legacy" and s["learn"]["ok"]  # not late: the old cron runs it
    assert s["fresh"]["state"] == "late"

    # Handing over at noon: learn's 06:30 run today belonged to the old file.
    monkeypatch.setenv("PYTHIA_LEGACY_CRON_DIR", str(tmp_path / "legacy"))
    jobs.write_cron(t, prune_legacy=True)
    live = json.loads((t.ops_dir / "installed.json").read_text())
    assert live["learn"] == "2026-10-15T12:00:00Z" and live["fresh"] == "2026-10-15T05:00:00Z"
    s = {j["name"]: j for j in jobs.build_status(t)["jobs"]}
    assert s["learn"]["state"] == "never" and s["learn"]["ok"]
    monkeypatch.setenv("PYTHIA_JOBS_NOW", "2026-10-16T12:00:00Z")
    s = {j["name"]: j for j in jobs.build_status(t)["jobs"]}
    assert s["learn"]["state"] == "late"


@pytest.mark.parametrize("bad", ["learn", "pythia-jobs", "../pythia-x"])
def test_replaces_must_name_a_pythia_cron_file(tmp_path, bad):
    with pytest.raises(jobs.TableError, match="replaces"):
        table(tmp_path, f'  - name: a\n    schedule: "0 * * * *"\n    command: x\n    replaces: {bad}')


def test_optional_and_required_env_files(tmp_path):
    (tmp_path / "a.env").write_text("A=1\n")
    t = table(tmp_path, f"""
  - name: c
    kind: lab
    schedule: "0 * * * *"
    command: python -m lab.ops.listings
    env_file: [{tmp_path}/a.env, '{tmp_path}/b.env?']
  - name: h
    schedule: "0 * * * *"
    command: echo "A=$A"
    env_file: {tmp_path}/missing.env
""")
    argv = jobs.build_argv(t, t.job("c"))
    assert argv.count("--env-file") == 1 and f"{tmp_path}/a.env" in argv
    (tmp_path / "b.env").write_text("B=2\n")
    assert jobs.build_argv(t, t.job("c")).count("--env-file") == 2
    assert jobs.run_job(t, "h") == 127
    last = jobs.job_state(t, "h")["last"]
    assert last["status"] == "failed" and "missing.env" in last["reason"]


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
    (tmp_path / "alerts.env").write_text("")
    t = table(tmp_path, f"""
  - name: learn
    kind: lab
    schedule: "30 6 * * *"
    command: python -m lab.ops.learn --force "vol x"
    network: host
    env: {{PYTHIA_AGENT_OUT: /data/lab-cache}}
    env_file: {tmp_path}/alerts.env
    resources: {{cpus: 4, memory: 8g}}
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


def _ro_mounts(argv: list[str]) -> set[str]:
    return {argv[i + 1] for i, a in enumerate(argv[:-1]) if a == "-v" and argv[i + 1].endswith(":ro")}


def test_plain_lab_jobs_see_the_real_money_controls_read_only(tmp_path):
    (tmp_path / "alerts.env").write_text("")
    (tmp_path / "live-code").mkdir()
    t = table(tmp_path, f"""
  - name: book
    kind: lab
    schedule: "0 5 * * *"
    command: python -m lab.paper.book
  - name: digest
    kind: lab
    schedule: "0 6 * * *"
    command: python -m lab.ops.notify
    env_file: {tmp_path}/alerts.env
  - name: twin
    kind: lab
    schedule: "0 7 * * *"
    command: python -m lab.paper.live_copy
    code: false
    volumes: [{tmp_path}/live-code:/app:ro]
""")
    data = tmp_path / "data"
    for d in ("autopilot", "live/pumpfun_rt", "pumpfun_rt/idl", "signals/breakout_top10",
              "signals/breakout_top10_live", "signals/tsmom_top20", "reports/pumpfun_rt", "lab-cache/reports"):
        (data / d).mkdir(parents=True)
    (data / "signals/breakout_top10_live/latest.json").write_text(json.dumps({"live_copy_of": "breakout_top10"}))
    (data / "reports/pumpfun_rt/KILL").write_text("")
    (data / "lab-cache/reports/families_summary.json").write_text("{}")
    ro = _ro_mounts(jobs.build_argv(t, t.job("book")))
    for p in ("autopilot", "live", "pumpfun_rt/idl", "signals/breakout_top10_live", "signals/breakout_top10",
              "reports/pumpfun_rt/KILL", "lab-cache/reports/families_summary.json"):
        assert f"{data}/{p}:/data/{p}:ro" in ro, p
    assert not any("tsmom_top20" in v or "autopilot-safe" in v for v in ro)
    # Jobs whose code the agent cannot change see the folder as before.
    assert _ro_mounts(jobs.build_argv(t, t.job("digest"))) == set()
    assert _ro_mounts(jobs.build_argv(t, t.job("twin"))) == {f"{tmp_path}/live-code:/app:ro"}


def test_a_lock_is_never_taken_through_a_symlink(tmp_path):
    (tmp_path / "locks").mkdir()
    target = tmp_path / "target"
    target.write_text("keep me")
    (tmp_path / "locks" / "a.lock").symlink_to(target)
    with pytest.raises(OSError):
        jobs.Locks(tmp_path / "locks", ["a"]).acquire()
    assert target.read_text() == "keep me"


def test_a_missing_volume_source_stops_the_run(tmp_path):
    t = table(tmp_path, f"""
  - name: sim
    kind: lab
    schedule: "0 5 * * *"
    command: python -m lab.pumpfun_rt.live_exec simulate
    code: false
    volumes: [{tmp_path}/missing-ack:/etc/pythia/pumpfun-live-ack:ro]
""")
    with pytest.raises(FileNotFoundError):
        jobs.build_argv(t, t.job("sim"))
    assert not (tmp_path / "missing-ack").exists()


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


# the server's recorded disk history 2026-10-20 to 27 (free GB, tracked GB; 463.9 GB disk): free
# space fell 108 GB while the tracked folders grew 5 GB
DISK_HISTORY = [
    ("10-20T01:07", 255.8, 12.6), ("10-20T07:07", 254.9, 12.8), ("10-20T13:07", 254.2, 12.9),
    ("10-20T20:07", 247.9, 13.1), ("10-21T02:07", 236.9, 13.2), ("10-21T08:07", 235.0, 13.5),
    ("10-21T14:07", 232.0, 13.7), ("10-21T20:07", 220.0, 13.9), ("10-22T02:07", 215.9, 14.0),
    ("10-22T08:07", 215.1, 14.2), ("10-22T14:07", 214.6, 14.4), ("10-22T20:07", 203.3, 14.6),
    ("10-23T02:07", 190.9, 14.7), ("10-23T08:07", 189.0, 14.9), ("10-23T15:07", 177.4, 15.2),
    ("10-23T22:07", 167.5, 15.5), ("10-24T04:07", 164.7, 15.6), ("10-24T10:07", 164.5, 15.7),
    ("10-24T17:07", 162.9, 16.0), ("10-24T23:07", 162.0, 16.2), ("10-25T05:07", 161.5, 16.3),
    ("10-25T11:07", 160.9, 16.5), ("10-25T17:07", 159.8, 16.7), ("10-25T23:07", 158.7, 16.9),
    ("10-26T06:07", 157.9, 17.3), ("10-26T13:07", 157.0, 17.5), ("10-26T19:07", 164.5, 17.7),
    ("10-27T01:07", 154.1, 17.8), ("10-27T07:07", 147.1, 18.0)]


def test_disk_days_left_from_the_fall_in_free_space(tmp_path):
    t = table(tmp_path, '  - name: a\n    schedule: "0 4 * * *"\n    command: x', """
datasets:
  - name: d
    path: d
""")
    gb = 1024 ** 3
    hist = tmp_path / "data" / "_ops" / "disk" / "history.jsonl"
    hist.parent.mkdir(parents=True)
    # old entries carry no "used": total minus free stands in
    hist.write_text("".join(json.dumps({"at": f"2026-{at}:01Z", "free": int(free * gb), "total": int(463.9 * gb),
                                        "sizes": {"d": int(tr * gb)}}) + "\n" for at, free, tr in DISK_HISTORY))
    out = jobs.measure_disk(t, datetime(2026, 10, 27, 8, 0, tzinfo=UTC))
    assert out["at"] == "2026-10-27T07:07:01Z", "cached: the recorded entry is the latest"
    assert out["growthGbPerDay"] == pytest.approx(0.75, abs=0.05), "the tracked folders alone looked harmless"
    assert out["freeFallGbPerDay"]["7d"] == pytest.approx(15.0, abs=0.1)
    assert out["freeFallGbPerDay"]["3d"] == pytest.approx(5.8, abs=0.3)
    assert out["daysLeft"] == pytest.approx(9.8, abs=0.1) and out["ok"] is False
    assert out["trackedGb"] == 18.0 and out["untrackedGb"] == pytest.approx(298.8, abs=0.1)
    assert out["untrackedGrowthGbPerDay"] == pytest.approx(14.25, abs=0.1)
    checks = {n: (ok, d) for n, ok, d in jobs.health_checks(t, datetime(2026, 10, 27, 8, 0, tzinfo=UTC))}
    assert checks["disk"][0] is False
    assert "full in about 10 days at 14.99 GB a day" in checks["disk"][1]
    assert "298.8 GB used outside the tracked folders" in checks["disk"][1]
    # every day of the record from 10-23 on is red; a rise in free space (a cleanup) is no fall
    lines = hist.read_text().splitlines()
    for n in range(14, len(lines) + 1):
        hist.write_text("\n".join(lines[:n]) + "\n")
        at = jobs._parse_iso(json.loads(lines[n - 1])["at"])
        assert jobs.measure_disk(t, at)["ok"] is False, lines[n - 1]
    rising = [{"at": "2026-10-15T15:07:01Z", "free": 87 * gb, "total": 464 * gb, "sizes": {"d": 0}},
              {"at": "2026-10-17T15:07:01Z", "free": 270 * gb, "total": 464 * gb, "sizes": {"d": 0}}]
    hist.write_text("".join(json.dumps(h) + "\n" for h in rising))
    out = jobs.measure_disk(t, datetime(2026, 10, 17, 16, 0, tzinfo=UTC))
    assert out["freeFallGbPerDay"]["3d"] < 0 and out["daysLeft"] is None and out["ok"] is True


def test_a_stale_dataset_turns_red(tmp_path):
    t = table(tmp_path, '  - name: a\n    schedule: "0 4 * * *"\n    command: x', """
datasets:
  - name: etf
    path: etf/daily
    max_age_h: 96
  - name: empty
    path: empty
    max_age_h: 3
  - name: ageless
    path: ageless
""")
    now = datetime(2026, 10, 27, 13, 0, tzinfo=UTC)
    d = tmp_path / "data" / "etf" / "daily"
    d.mkdir(parents=True)
    (d / "SPY.parquet").write_text("x")
    (tmp_path / "data" / "ageless").mkdir()
    (tmp_path / "data" / "ageless" / "f").write_text("x")
    old = datetime(2026, 10, 13, tzinfo=UTC).timestamp()
    os.utime(d / "SPY.parquet", (old, old))
    os.utime(tmp_path / "data" / "ageless" / "f", (old, old))
    checks = {n: (ok, d) for n, ok, d in jobs.health_checks(t, now)}
    assert checks["data etf"][0] is False and "newest file 349 h old (may be 96 h)" in checks["data etf"][1]
    assert checks["data empty"][0] is False and "no file" in checks["data empty"][1]
    assert checks["data ageless"][0] is True, "no max_age_h, no age check"
    fresh = now.timestamp() - 3600
    os.utime(d / "SPY.parquet", (fresh, fresh))
    checks = {n: (ok, d) for n, ok, d in jobs.health_checks(t, now)}
    assert checks["data etf"][0] is True and "newest file 1 h old" in checks["data etf"][1]
    with pytest.raises(jobs.TableError, match="max_age_h"):
        table(tmp_path, '  - name: a\n    schedule: "0 4 * * *"\n    command: x',
              "datasets:\n  - name: d\n    path: d\n    max_age_h: 0")


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


def _backup_table(tmp_path, extra=""):
    t = table(tmp_path, """
  - name: backup
    schedule: "20 2 * * *"
    command: x
""", f"""
backup:
  dest: {tmp_path}/backup
  include: [engine, autopilot-safe, discord/channels.json]
  exclude: ["*.tmp", "*.bak-*"]
{extra}""")
    data = tmp_path / "data"
    for d in ("engine", "autopilot-safe", "discord"):
        (data / d).mkdir(parents=True, exist_ok=True)
    (data / "engine" / "state.json").write_text('{"equity": 1}')
    (data / "engine" / "state.json.bak-202610201646").write_text("old")
    (data / "autopilot-safe" / "state.json").write_text('{"equity": 2}')
    (data / "discord" / "channels.json").write_text('{"de": {}}')
    return t


def test_repo_table_backs_up_the_engines_and_the_real_account():
    t = jobs.load_table(REPO_TABLE)
    inc = jobs._backup_conf(t)["include"]
    for p in ("engine", "autopilot-safe", "pumpfun_rt/factory", "reports/pumpfun_rt/live_settings.json",
              "discord/channels.json"):
        assert p in inc
    assert not {"server", "costs", "trials"} & set(inc)
    rt = t.job("restore-test")
    assert rt["enabled"] and rt["kind"] == "host" and "restore-test" in rt["command"] and rt["locks"] == ["backup"]


def test_restore_test_unpacks_and_compares_checksums(tmp_path):
    t = _backup_table(tmp_path)
    out = jobs.backup(t, now=datetime(2026, 10, 27, 2, 20, tzinfo=UTC))
    assert out["missing"] == [] and out["files"] == 3  # the rolling .bak copy stays out
    assert "checksums" not in json.loads((t.ops_dir / "backup" / "latest.json").read_text())
    man = json.loads(Path(out["archive"] + ".json").read_text())
    assert set(man["checksums"]) == {"engine/state.json", "autopilot-safe/state.json", "discord/channels.json"}
    r = jobs.restore_test(t, now=datetime(2026, 11, 1, 3, 40, tzinfo=UTC))
    assert r["ok"] and r["files"] == 3 and not r["problems"]
    assert not list((tmp_path / "backup").glob(".restore-*"))  # the temporary folder is gone
    assert json.loads((t.ops_dir / "backup" / "restore.json").read_text())["ok"]
    # a manifest that disagrees with the archive's content fails
    man["checksums"]["engine/state.json"] = "0" * 64
    Path(out["archive"] + ".json").write_text(json.dumps(man))
    r = jobs.restore_test(t)
    assert not r["ok"] and r["differ"] == ["engine/state.json"]
    # a damaged archive fails on its sha256 before it is unpacked
    with open(out["archive"], "ab") as f:
        f.write(b"x")
    r = jobs.restore_test(t)
    assert not r["ok"] and "differs from its .sha256" in r["problems"][0]
    assert jobs.main(["--table", t.path, "restore-test"]) == 1


def test_restore_test_without_an_archive_fails(tmp_path):
    t = _backup_table(tmp_path)
    r = jobs.restore_test(t)
    assert not r["ok"] and "no archive" in r["problems"][0]


def test_health_checks_the_backup_the_off_server_copy_and_the_restore(tmp_path):
    t = _backup_table(tmp_path, "  offsite_max_age: 1d")
    day1 = datetime(2026, 10, 26, 2, 20, tzinfo=UTC)
    now = day1 + timedelta(hours=3)

    def checks(at):
        return {n: (ok, d) for n, ok, d in jobs.backup_checks(t, at)}

    c = checks(now)
    assert c["backup"][0] is False and c["backup off-server"][0] is False and c["backup restore"][0] is False
    a1 = jobs.backup(t, now=day1)
    (tmp_path / "backup" / "offsite.json").write_text(json.dumps(
        {"at": "2026-10-26T05:00:00Z", "archive": Path(a1["archive"]).name, "sha256": a1["sha256"]}))
    jobs.restore_test(t, now=now)
    c = checks(now)
    assert all(ok for ok, _d in c.values()), c
    # the next archive appears; the copy is behind it, red after a day
    jobs.backup(t, now=day1 + timedelta(days=1))
    assert checks(day1 + timedelta(days=1, hours=20))["backup off-server"][0] is True
    late = checks(day1 + timedelta(days=2, hours=1))["backup off-server"]
    assert late[0] is False and "25 h behind" in late[1]
    # a receipt whose checksum is not the server's is red
    (tmp_path / "backup" / "offsite.json").write_text(json.dumps(
        {"at": "2026-10-26T05:00:00Z", "archive": Path(a1["archive"]).name, "sha256": "f" * 64}))
    assert checks(now)["backup off-server"][0] is False
    # an entry missing from the backup is red
    shutil.rmtree(tmp_path / "data" / "discord")
    jobs.backup(t, now=day1 + timedelta(days=1, hours=1))
    assert checks(now)["backup"] == (False, "missing: discord/channels.json")
    names = {n for n, _ok, _d in jobs.health_checks(t, now)}
    assert {"backup", "backup off-server", "backup restore"} <= names


@pytest.mark.skipif(not shutil.which("sha256sum"), reason="sha256sum not installed")
def test_sync_to_pc_copies_the_newest_archive_by_checksum(tmp_path):
    t = _backup_table(tmp_path)
    a1 = jobs.backup(t, now=datetime(2026, 10, 26, 2, 20, tzinfo=UTC))
    a2 = jobs.backup(t, now=datetime(2026, 10, 27, 2, 20, tzinfo=UTC))
    # ssh that runs the remote command here
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    (bin_ / "ssh").write_text('#!/usr/bin/env bash\nwhile [ "$1" = -o ]; do shift 2; done\nshift\nexec bash -c "$*"\n')
    (bin_ / "ssh").chmod(0o755)
    pc = tmp_path / "pc"
    env = dict(os.environ, PATH=f"{bin_}:{os.environ.get('PATH', '')}", PYTHIA_VPS="vps",
               PYTHIA_VPS_DATA=str(tmp_path / "data"), PYTHIA_VPS_BACKUP=str(tmp_path / "backup"),
               PYTHIA_LOCAL=str(pc), PYTHIA_BACKUP_KEEP="1")
    script = REPO_TABLE.parents[1] / "sync-to-pc.sh"

    def sync():
        return subprocess.run(["bash", str(script)], env=env, capture_output=True, text=True, timeout=120)

    local = pc / "_backup"
    (local).mkdir(parents=True)
    old = Path(a1["archive"]).name
    shutil.copy(a1["archive"], local / old)
    new = Path(a2["archive"]).name
    (local / new).write_bytes(b"same size?")  # a stale copy under the newest name is fetched again
    r = sync()
    assert r.returncode == 0, r.stderr
    assert (pc / "engine" / "state.json").exists()
    assert (local / new).read_bytes() == Path(a2["archive"]).read_bytes()
    assert (local / f"{new}.sha256").read_text().split()[0] == a2["sha256"]
    assert not (local / old).exists()  # only the newest PYTHIA_BACKUP_KEEP stay
    rec = json.loads((tmp_path / "backup" / "offsite.json").read_text())
    assert rec["archive"] == new and rec["sha256"] == a2["sha256"]
    assert {n: ok for n, ok, _d in jobs.backup_checks(t, datetime(2026, 10, 27, 5, 0, tzinfo=UTC))}[
        "backup off-server"]
    # an archive that does not match its .sha256 on the way is not kept and no receipt is written
    (tmp_path / "backup" / "offsite.json").unlink()
    a3 = jobs.backup(t, now=datetime(2026, 10, 28, 2, 20, tzinfo=UTC))
    (Path(a3["archive"] + ".sha256")).write_text(f"{'0' * 64}  {Path(a3['archive']).name}\n")
    r = sync()
    assert r.returncode != 0
    assert not (local / Path(a3["archive"]).name).exists() and not (tmp_path / "backup" / "offsite.json").exists()
    assert "different checksum" in (pc / "sync.log").read_text()


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
    shutil.copy(src.with_name("i18n.py"), ops / "i18n.py")
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


# ---------------------------------------------------------------- the shell side

OPS = REPO_TABLE.parent


@pytest.mark.skipif(not shutil.which("rsync"), reason="rsync not installed")
def test_deploy_lab_keeps_results_and_checks_the_manifest(tmp_path):
    src = tmp_path / "src"
    (src / "lab" / "__pycache__").mkdir(parents=True)
    (src / "lab" / "__init__.py").write_text("")
    (src / "lab" / "x.py").write_text("X = 1\n")
    (src / "lab" / "__pycache__" / "x.pyc").write_text("cache")
    (src / "results").mkdir()
    (src / "results" / "from_repo.md").write_text("repo copy")
    dest = tmp_path / "dest"
    (dest / "results").mkdir(parents=True)
    (dest / "results" / "study.md").write_text("written on the server")
    (dest / "stale.py").write_text("old")
    (dest / "cache").mkdir()
    (dest / "cache" / "panel.parquet").write_text("big")

    def deploy(*extra):
        return subprocess.run(["bash", str(OPS / "deploy_lab.sh"), "--src", str(src), "--dest", str(dest), "--force",
                               *extra], capture_output=True, text=True, timeout=60)

    (src / "results" / "study.md").write_text("older repo copy")
    (src / "results" / "factory_seed").mkdir()
    (src / "results" / "factory_seed" / "ledger.jsonl").write_text("{}\n")
    r = deploy()
    assert r.returncode == 0, r.stderr
    assert "2 new files added" in r.stdout
    assert (dest / "results" / "study.md").read_text() == "written on the server"  # never replaced
    assert (dest / "results" / "from_repo.md").read_text() == "repo copy"  # new files arrive
    assert (dest / "results" / "factory_seed" / "ledger.jsonl").exists()
    assert not (dest / "stale.py").exists()
    assert (dest / "cache" / "panel.parquet").exists()  # caches are neither sent nor deleted
    assert not (dest / "lab" / "__pycache__").exists()
    man = (dest / ".deploy-manifest").read_text()
    assert "lab/x.py" in man and "results" not in man and ".pyc" not in man
    info = json.loads((dest / ".deploy-info").read_text())
    assert info["files"] == 2
    # a second deploy is a no-op and still passes; a file only the server has stays
    (dest / "results" / "server_only.md").write_text("mine")
    r = deploy()
    assert r.returncode == 0 and "0 new files added" in r.stdout, r.stderr
    assert (dest / "results" / "server_only.md").read_text() == "mine"
    # dry run changes nothing
    (src / "lab" / "y.py").write_text("")
    assert deploy("--dry-run").returncode == 0 and not (dest / "lab" / "y.py").exists()


@pytest.mark.skipif(not shutil.which("rsync") or getattr(os, "geteuid", lambda: 1)() != 0,
                    reason="rsync and root needed")
def test_deploy_live_copies_a_committed_lab_and_checks_it(tmp_path):
    repo = tmp_path / "repo"
    lab = repo / "research" / "lab"
    for p, text in (("lab/__init__.py", ""), ("lab/x.py", "X = 1\n"), ("tests/test_x.py", ""),
                    ("results/r.md", "r\n"), ("proposals/p.md", "p\n")):
        (lab / p).parent.mkdir(parents=True, exist_ok=True)
        (lab / p).write_text(text)
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}
    for args in (["init", "-q"], ["add", "-A"], ["commit", "-qm", "x"]):
        subprocess.run(["git", "-C", str(repo), *args], check=True, env=env, capture_output=True)
    dest = tmp_path / "live"

    def deploy(*extra, d=dest):
        return subprocess.run(["bash", str(OPS / "deploy_live.sh"), "--src", str(lab), "--dest", str(d), "--force",
                               *extra], capture_output=True, text=True, timeout=60)

    r = deploy()
    assert r.returncode == 0, r.stderr
    assert (dest / "lab" / "x.py").exists() and (dest / "results" / "r.md").exists()
    assert not (dest / "tests").exists() and not (dest / "proposals").exists()
    assert oct((dest / "lab" / "x.py").stat().st_mode)[-3:] == "644"
    assert json.loads((dest / ".deploy-info").read_text())["files"] == 3
    (lab / "lab" / "x.py").write_text("X = 2\n")                        # not committed
    r = deploy()
    assert r.returncode != 0 and "uncommitted" in r.stderr
    assert (dest / "lab" / "x.py").read_text() == "X = 1\n"
    assert "refusing" in deploy(d=Path("/opt/pythia-lab")).stderr


def test_deploy_lab_refuses_a_folder_without_lab_code(tmp_path):
    r = subprocess.run(["bash", str(OPS / "deploy_lab.sh"), "--src", str(tmp_path), "--dest", str(tmp_path / "d"),
                        "--force"], capture_output=True, text=True, timeout=30)
    assert r.returncode != 0 and "no lab code" in r.stderr


def test_system_health_includes_every_job(tmp_path):
    t = table(tmp_path, """
  - name: good
    schedule: "0 * * * *"
    command: echo ok
  - name: bad
    schedule: "0 * * * *"
    command: echo 'say "quoted" \\\\ back'; exit 1
""")
    jobs.run_job(t, "good")
    jobs.run_job(t, "bad")
    (tmp_path / "data" / "_health").mkdir(exist_ok=True)
    env = dict(os.environ, PYTHIA_HEALTH_DATA=str(tmp_path / "data"), PYTHIA_JOBS_PY=jobs.__file__,
               PYTHIA_JOBS_TABLE=t.path, PYTHIA_NOTIFY_PY=str(tmp_path / "none.py"),
               PATH=os.environ.get("PATH", ""))
    r = subprocess.run(["bash", str(OPS / "system_health.sh")], env=env, capture_output=True, text=True,
                       timeout=120)
    assert r.returncode == 0, r.stderr
    s = json.loads((tmp_path / "data" / "_health" / "system.json").read_text())
    by = {c["name"]: c for c in s["checks"]}
    assert by["job good"]["ok"] is True
    assert by["job bad"]["ok"] is False and "exit 1" in by["job bad"]["detail"]
    assert "disk" in by and not s["ok"]
    assert (tmp_path / "data" / "_health" / "jobs.json").exists()
