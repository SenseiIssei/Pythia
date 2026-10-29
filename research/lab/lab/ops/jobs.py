"""Every scheduled Pythia job in one table, and the runner that runs them.

The table is research/ops/jobs.yaml (installed as /opt/pythia-ops/jobs.yaml).
One entry per job: name, schedule (5-field cron, UTC) or `depends_on` alone
(run right after its dependencies succeed), command (in the lab image, another
image, or on the host), resources, timeout, lock, enabled. This file reads it
and does the rest:

  python3 jobs.py validate                 check the table, print the jobs
  python3 jobs.py render [--dry-run]       write /etc/cron.d/pythia-jobs from it
             [--prune-legacy]              and move the old hand-written files away
  python3 jobs.py run <job> [--force]      run one job the way cron does
  python3 jobs.py status [--write]         last run, next run, failures (JSON)
  python3 jobs.py checks                   one line per check for system_health.sh
  python3 jobs.py disk                     data growth per dataset (JSON)
  python3 jobs.py prune [--dry-run]        apply the retention rules
  python3 jobs.py backup [--dry-run]       archive the important state, rotate
  python3 jobs.py restore-test             unpack the newest archive, compare checksums

Every run is wrapped the same way: an exclusive flock on
<locks>/<lock>.lock (the same kernel lock `flock(1)` takes), a hard timeout
(the process group is killed, a container is `docker kill`ed), output appended
to <logs>/<job>.log (rotated by size), and a run record (start, end, exit
code, duration, status) appended to <data>/_ops/runs/<YYYY-MM>.jsonl. After
each run <data>/_health/jobs.json is rewritten: the status the Lab page shows
and the health check reads. The first failure of a job (and its recovery) is
posted through notify.py, the same path as the health alarm.

Only the standard library, on purpose: cron runs this with the host's python3,
next to notify.py, without the lab image. The table format is a small subset
of YAML (block mappings and lists, inline [a, b] and {k: v}, quoted and plain
scalars, # comments); `parse_yaml` refuses anything else.
"""

from __future__ import annotations

import errno
import fcntl
import fnmatch
import hashlib
import json
import os
import re
import shlex
import shutil
import signal
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:  # inside the lab package
    from . import notify as _notify
except ImportError:  # /opt/pythia-ops/jobs.py next to notify.py
    try:
        import notify as _notify  # type: ignore[no-redef]
    except ImportError:  # pragma: no cover - notify.py not installed
        _notify = None

DEFAULT_TABLE = "/opt/pythia-ops/jobs.yaml"
CRON_FILE = "pythia-jobs"
# Hand-written cron files no job of the table names in `replaces` but that
# render --prune-legacy also moves away (retired before the table existed).
LEGACY_CRON = ("pythia-retrain",)
JOB_KINDS = ("lab", "image", "host")
JOB_KEYS = {"name", "description", "schedule", "kind", "image", "command", "resources", "timeout",
            "lock", "lock_wait", "depends_on", "depends_within", "enabled", "network", "env",
            "env_file", "volumes", "code", "grace", "alert", "replaces"}
STATUS_OK = "ok"


class TableError(ValueError):
    pass


# ================================================================ YAML subset

def _strip_comment(line: str) -> str:
    out, q = [], None
    for i, ch in enumerate(line):
        if q:
            if ch == q:
                q = None
        elif ch in "\"'":
            q = ch
        elif ch == "#" and (i == 0 or line[i - 1] in " \t"):
            break
        out.append(ch)
    return "".join(out).rstrip()


def _split_flow(s: str) -> list[str]:
    parts, cur, q = [], [], None
    for ch in s:
        if q:
            cur.append(ch)
            if ch == q:
                q = None
        elif ch in "\"'":
            q = ch
            cur.append(ch)
        elif ch == ",":
            parts.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    if "".join(cur).strip():
        parts.append("".join(cur).strip())
    return parts


def _key_split(text: str) -> tuple[str, str] | None:
    """'key: value' -> (key, value); None when the line is not a mapping entry."""
    q = None
    for i, ch in enumerate(text):
        if q:
            if ch == q:
                q = None
        elif ch in "\"'" and i == 0:
            q = ch
        elif ch == ":" and (i + 1 == len(text) or text[i + 1] in " \t"):
            key = text[:i].strip()
            if len(key) >= 2 and key[0] == key[-1] and key[0] in "\"'":
                key = key[1:-1]
            return key, text[i + 1:].strip()
    return None


def _scalar(s: str):
    s = s.strip()
    if s == "":
        return None
    if s[0] in "\"'":
        if len(s) < 2 or s[-1] != s[0]:
            raise TableError(f"unclosed quote: {s}")
        body = s[1:-1]
        if s[0] == '"':
            body = body.replace('\\"', '"').replace("\\\\", "\\")
        else:
            body = body.replace("''", "'")
        return body
    if s[0] == "[":
        if s[-1] != "]":
            raise TableError(f"unclosed list: {s}")
        return [_scalar(p) for p in _split_flow(s[1:-1])]
    if s[0] == "{":
        if s[-1] != "}":
            raise TableError(f"unclosed mapping: {s}")
        out = {}
        for p in _split_flow(s[1:-1]):
            kv = _key_split(p)
            if kv is None:
                raise TableError(f"not a key: value pair: {p}")
            out[kv[0]] = _scalar(kv[1])
        return out
    if s[0] in "*&!|>%@`":
        raise TableError(f"quote this value: {s}")
    low = s.lower()
    if low == "true":  # YAML 1.2: yes/no/on/off stay strings (a job may be called off)
        return True
    if low == "false":
        return False
    if low in ("null", "~"):
        return None
    if re.fullmatch(r"[-+]?\d+", s):
        return int(s)
    if re.fullmatch(r"[-+]?(\d+\.\d*|\.\d+)([eE][-+]?\d+)?", s):
        return float(s)
    return s


def parse_yaml(text: str):
    """The subset of YAML the job table uses. Raises TableError on anything else."""
    lines: list[list] = []
    for no, raw in enumerate(text.splitlines(), 1):
        if "\t" in raw[: len(raw) - len(raw.lstrip())]:
            raise TableError(f"line {no}: tabs are not allowed for indentation")
        body = _strip_comment(raw)
        if body.strip() == "" or body.strip() == "---":
            continue
        lines.append([len(body) - len(body.lstrip(" ")), body.strip(), no])

    def block(i: int, indent: int):
        if lines[i][1].startswith("- ") or lines[i][1] == "-":
            return seq(i, indent)
        return mapping(i, indent)

    def folded(i: int, indent: int) -> tuple[str, int]:
        parts = []
        while i < len(lines) and lines[i][0] > indent:
            parts.append(lines[i][1])
            i += 1
        return " ".join(parts), i

    def value_after(i: int, indent: int, rest: str, no: int, seq_ok: bool):
        """The value of a key whose text after the colon is `rest`; i is the next line."""
        if rest in (">", ">-", "|", "|-"):
            return folded(i, indent)
        if rest:
            return _scalar(rest), i
        if i < len(lines) and lines[i][0] > indent:
            return block(i, lines[i][0])
        if seq_ok and i < len(lines) and lines[i][0] == indent and lines[i][1].startswith("-"):
            return seq(i, indent)
        return None, i

    def mapping(i: int, indent: int):
        out: dict = {}
        while i < len(lines) and lines[i][0] == indent:
            _, text, no = lines[i]
            if text.startswith("-"):
                break
            kv = _key_split(text)
            if kv is None:
                raise TableError(f"line {no}: expected 'key: value', got {text!r}")
            key, rest = kv
            if key in out:
                raise TableError(f"line {no}: duplicate key {key!r}")
            out[key], i = value_after(i + 1, indent, rest, no, True)
        if i < len(lines) and lines[i][0] > indent:
            raise TableError(f"line {lines[i][2]}: unexpected indentation")
        return out, i

    def seq(i: int, indent: int):
        out: list = []
        while i < len(lines) and lines[i][0] == indent and (lines[i][1].startswith("- ") or lines[i][1] == "-"):
            _, text, no = lines[i]
            rest = text[1:].strip()
            if not rest:
                if i + 1 < len(lines) and lines[i + 1][0] > indent:
                    v, i = block(i + 1, lines[i + 1][0])
                else:
                    v, i = None, i + 1
                out.append(v)
                continue
            kv = _key_split(rest) if rest[0] not in "[{\"'" else None
            if kv is None:
                out.append(_scalar(rest))
                i += 1
                continue
            # "- key: value" opens a mapping indented to where the key starts
            lines[i] = [indent + len(text) - len(rest), rest, no]
            v, i = mapping(i, lines[i][0])
            out.append(v)
        return out, i

    if not lines:
        return {}
    v, i = block(0, lines[0][0])
    if i < len(lines):
        raise TableError(f"line {lines[i][2]}: unexpected content")
    return v


# ================================================================ cron schedules

_ALIASES = {"@hourly": "0 * * * *", "@daily": "0 0 * * *", "@midnight": "0 0 * * *",
            "@weekly": "0 0 * * 0", "@monthly": "0 0 1 * *", "@yearly": "0 0 1 1 *"}
_NAMES = {"sun": 0, "mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6,
          "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8,
          "sep": 9, "oct": 10, "nov": 11, "dec": 12}


class Cron:
    """A 5-field cron schedule (minute hour day-of-month month day-of-week), UTC."""

    BOUNDS = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 7))

    def __init__(self, expr: str):
        self.expr = expr.strip()
        fields = _ALIASES.get(self.expr, self.expr).split()
        if len(fields) != 5:
            raise TableError(f"schedule {expr!r}: need 5 fields")
        sets = [self._field(f, lo, hi, expr) for f, (lo, hi) in zip(fields, self.BOUNDS)]
        self.minutes, self.hours, self.doms, self.months = (sorted(s) for s in sets[:4])
        self.dows = {d % 7 for d in sets[4]}
        self.dom_any = fields[2].startswith("*")
        self.dow_any = fields[4].startswith("*")

    @staticmethod
    def _field(f: str, lo: int, hi: int, expr: str) -> set[int]:
        out: set[int] = set()
        for part in f.lower().split(","):
            step = 1
            if "/" in part:
                part, s = part.split("/", 1)
                if not s.isdigit() or int(s) == 0:
                    raise TableError(f"schedule {expr!r}: bad step {s!r}")
                step = int(s)
            if part == "*":
                a, b = lo, hi
            elif "-" in part:
                x, y = part.split("-", 1)
                a, b = _NAMES.get(x, x), _NAMES.get(y, y)
            else:
                a = _NAMES.get(part, part)
                b = a if step == 1 else hi
            try:
                a, b = int(a), int(b)
            except ValueError:
                raise TableError(f"schedule {expr!r}: bad field {f!r}") from None
            if not (lo <= a <= hi and lo <= b <= hi and a <= b):
                raise TableError(f"schedule {expr!r}: {f!r} out of range {lo}-{hi}")
            out.update(range(a, b + 1, step))
        return out

    def _day_ok(self, d: datetime) -> bool:
        if d.month not in self.months:
            return False
        dom = d.day in self.doms
        dow = (d.weekday() + 1) % 7 in self.dows
        if self.dom_any and self.dow_any:
            return True
        if self.dom_any:
            return dow
        if self.dow_any:
            return dom
        return dom or dow  # both restricted: either one, as cron does

    def next_after(self, t: datetime) -> datetime | None:
        """First fire strictly after t."""
        day = t.replace(hour=0, minute=0, second=0, microsecond=0)
        for _ in range(1500):
            if self._day_ok(day):
                for h in self.hours:
                    for m in self.minutes:
                        c = day.replace(hour=h, minute=m)
                        if c > t:
                            return c
            day += timedelta(days=1)
        return None

    def prev_at_or_before(self, t: datetime) -> datetime | None:
        """Last fire at or before t."""
        day = t.replace(hour=0, minute=0, second=0, microsecond=0)
        for _ in range(1500):
            if self._day_ok(day):
                for h in reversed(self.hours):
                    for m in reversed(self.minutes):
                        c = day.replace(hour=h, minute=m)
                        if c <= t:
                            return c
            day -= timedelta(days=1)
        return None


# ================================================================ the table

def parse_duration(v, what: str = "duration") -> int:
    """'90s', '45m', '3h', '2d' or plain seconds -> seconds."""
    if isinstance(v, bool) or v is None:
        raise TableError(f"{what}: missing or not a duration")
    if isinstance(v, (int, float)):
        return int(v)
    m = re.fullmatch(r"\s*(\d+)\s*([smhd]?)\s*", str(v))
    if not m:
        raise TableError(f"{what}: bad duration {v!r}")
    return int(m.group(1)) * {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400}[m.group(2)]


def _as_list(v) -> list:
    if v is None:
        return []
    return list(v) if isinstance(v, list) else [v]


class Table:
    def __init__(self, raw: dict, path: str = "<table>"):
        if not isinstance(raw, dict):
            raise TableError("the table must be a mapping with a 'jobs' list")
        self.path = path
        self.raw = raw
        p = raw.get("paths") or {}
        self.data = Path(p.get("data", "/srv/pythia-data"))
        self.code = p.get("code", "/opt/pythia-lab")
        self.logs = Path(p.get("logs", "/var/log/pythia"))
        self.locks = Path(p.get("locks", "/run/lock/pythia"))
        self.ops = p.get("ops", "/opt/pythia-ops")
        self.python = p.get("python", "/usr/bin/python3")
        self.cron_dir = Path(p.get("cron_dir", "/etc/cron.d"))
        self.alert_env = p.get("alert_env", "/etc/pythia/alerts.env")
        self.min_free_gb = float(p.get("min_free_gb", 20))
        self.log_max_bytes = int(float(p.get("log_max_mb", 10)) * 1024 * 1024)
        self.log_keep = int(p.get("log_keep", 5))
        self.defaults = raw.get("defaults") or {}
        self.datasets = raw.get("datasets") or []
        self.backup = raw.get("backup") or {}
        self.feeds = raw.get("feeds") or []
        self.jobs: dict[str, dict] = {}
        for j in raw.get("jobs") or []:
            job = self._job(j)
            if job["name"] in self.jobs:
                raise TableError(f"job {job['name']!r} is listed twice")
            self.jobs[job["name"]] = job
        if not self.jobs:
            raise TableError("no jobs in the table")
        self._check_graph()
        self._check_datasets()
        self._check_feeds()

    def _job(self, j) -> dict:
        if not isinstance(j, dict) or not j.get("name"):
            raise TableError(f"every job needs a name: {j!r}")
        name = str(j["name"])
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", name):
            raise TableError(f"job {name!r}: names are lower case letters, digits and dashes")
        unknown = set(j) - JOB_KEYS
        if unknown:
            raise TableError(f"job {name}: unknown keys {sorted(unknown)}")
        d = self.defaults
        job = {k: j.get(k, d.get(k)) for k in JOB_KEYS}
        job["name"] = name
        job["enabled"] = bool(j.get("enabled", d.get("enabled", True)))
        res = dict(d.get("resources") or {})
        res.update(j.get("resources") or {})
        job["resources"] = res
        job["kind"] = j.get("kind", d.get("kind", "lab"))
        if job["kind"] not in JOB_KINDS:
            raise TableError(f"job {name}: kind must be one of {JOB_KINDS}")
        if job["kind"] == "image" and not j.get("image"):
            raise TableError(f"job {name}: kind image needs an image")
        job["image"] = j.get("image") or d.get("image") or "pythia-lab"
        job["code"] = bool(j.get("code", job["kind"] == "lab"))
        if not isinstance(job["command"], str) or not job["command"].strip():
            raise TableError(f"job {name}: command is missing")
        if job["kind"] != "host":
            try:
                shlex.split(job["command"])
            except ValueError as e:
                raise TableError(f"job {name}: command does not parse: {e}") from None
        job["timeout_s"] = parse_duration(job["timeout"] or "1h", f"job {name} timeout")
        job["grace_s"] = parse_duration(job["grace"] or "15m", f"job {name} grace")
        job["lock_wait_s"] = parse_duration(job["lock_wait"] or 0, f"job {name} lock_wait")
        job["depends_within_s"] = parse_duration(job["depends_within"] or "20h", f"job {name} depends_within")
        job["locks"] = sorted({str(x) for x in _as_list(job["lock"])} or {name})
        for lk in job["locks"]:
            if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", lk):
                raise TableError(f"job {name}: bad lock name {lk!r}")
        job["depends_on"] = [str(x) for x in _as_list(job["depends_on"])]
        job["volumes"] = [str(x) for x in _as_list(job["volumes"])]
        job["env"] = {str(k): "" if v is None else str(v) for k, v in (job["env"] or {}).items()}
        job["alert"] = j.get("alert", d.get("alert", True)) is not False
        job["env_files"] = [str(x) for x in _as_list(job["env_file"])]
        job["replaces"] = [str(x) for x in _as_list(job["replaces"])]
        for r in job["replaces"]:
            if not re.fullmatch(r"pythia-[a-z0-9-]+", r) or r == CRON_FILE:
                raise TableError(f"job {name}: replaces names a file in the cron folder like pythia-paper, not {r!r}")
        sched = j.get("schedule")
        job["schedule"] = sched
        job["cron"] = Cron(str(sched)) if sched else None
        if job["cron"] is None and not job["depends_on"]:
            raise TableError(f"job {name}: needs a schedule or depends_on")
        return job

    def _check_graph(self) -> None:
        for job in self.jobs.values():
            for dep in job["depends_on"]:
                if dep not in self.jobs:
                    raise TableError(f"job {job['name']}: depends on unknown job {dep!r}")
                if dep == job["name"]:
                    raise TableError(f"job {job['name']}: depends on itself")
        state: dict[str, int] = {}

        def visit(n: str, path: list[str]) -> None:
            if state.get(n) == 1:
                raise TableError("dependency cycle: " + " -> ".join(path + [n]))
            if state.get(n) == 2:
                return
            state[n] = 1
            for dep in self.jobs[n]["depends_on"]:
                visit(dep, path + [n])
            state[n] = 2

        for n in self.jobs:
            visit(n, [])

    def _check_datasets(self) -> None:
        seen = set()
        for ds in self.datasets:
            if not isinstance(ds, dict) or not ds.get("name") or not ds.get("path"):
                raise TableError(f"every dataset needs a name and a path: {ds!r}")
            if ds["name"] in seen:
                raise TableError(f"dataset {ds['name']!r} listed twice")
            seen.add(ds["name"])
            rel = Path(str(ds["path"]))
            if rel.is_absolute() or ".." in rel.parts:
                raise TableError(f"dataset {ds['name']}: path must be relative to the data root")
            r = ds.get("retention_days")
            if r is not None and (not isinstance(r, int) or isinstance(r, bool) or r < 1):
                raise TableError(f"dataset {ds['name']}: retention_days must be a whole number of days, at least 1")
            a = ds.get("max_age_h")
            if a is not None and (not isinstance(a, (int, float)) or isinstance(a, bool) or a <= 0):
                raise TableError(f"dataset {ds['name']}: max_age_h must be a number of hours above 0")

    def _check_feeds(self) -> None:
        seen = set()
        for f in self.feeds:
            if not isinstance(f, dict) or not f.get("name") or not f.get("status") or not f.get("max_age"):
                raise TableError(f"every feed needs a name, a status file and a max_age: {f!r}")
            if f["name"] in seen:
                raise TableError(f"feed {f['name']!r} listed twice")
            seen.add(f["name"])
            rel = Path(str(f["status"]))
            if rel.is_absolute() or ".." in rel.parts:
                raise TableError(f"feed {f['name']}: status must be relative to the data root")
            if f.get("job") and f["job"] not in self.jobs:
                raise TableError(f"feed {f['name']}: unknown job {f['job']!r}")
            f["max_age_s"] = parse_duration(f["max_age"], f"feed {f['name']} max_age")
            f["max_gaps"] = int(f.get("max_gaps") or 0)

    def chained_after(self, name: str) -> list[dict]:
        """Jobs without a schedule that run right after `name` succeeds."""
        return [j for j in self.jobs.values() if j["cron"] is None and name in j["depends_on"]]

    def job(self, name: str) -> dict:
        if name not in self.jobs:
            raise TableError(f"no job called {name!r} (have: {', '.join(sorted(self.jobs))})")
        return self.jobs[name]

    # where things go
    @property
    def ops_dir(self) -> Path:
        return self.data / "_ops"

    @property
    def status_path(self) -> Path:
        return self.data / "_health" / "jobs.json"


def load_table(path: str | os.PathLike | None = None) -> Table:
    path = str(path or os.environ.get("PYTHIA_JOBS_TABLE") or DEFAULT_TABLE)
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as e:
        raise TableError(f"cannot read {path}: {e.strerror}") from None
    return Table(parse_yaml(text), path)


# ================================================================ rendering

def legacy_present(t: Table) -> dict[str, list[str]]:
    """Hand-written cron files still in the cron folder -> the jobs replacing them."""
    out: dict[str, list[str]] = {}
    for job in t.jobs.values():
        for r in job["replaces"]:
            if (t.cron_dir / r).exists():
                out.setdefault(r, []).append(job["name"])
    return out


def held(t: Table, job: dict) -> str | None:
    """The hand-written cron file that still runs this job, if any. Such a job
    stays commented out in the rendered file so it never runs twice."""
    for r in job["replaces"]:
        if (t.cron_dir / r).exists():
            return r
    return None


def render_cron(t: Table) -> str:
    """The /etc/cron.d file for every enabled job that has a schedule.

    Cron always runs the installed copy (<ops>/jobs.py with <ops>/jobs.yaml),
    whichever file the render read; deploy_ops.sh installs both first. A job
    whose hand-written file (`replaces`) is still in the cron folder is held,
    commented out, until `render --prune-legacy` moves that file away."""
    table_path = f"{t.ops}/jobs.yaml"
    runner = f"{t.ops}/jobs.py"
    out = [
        "# Pythia jobs. Generated from jobs.yaml by `jobs.py render`; edit the table, not this file.",
        "SHELL=/bin/sh",
        "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "",
    ]
    for job in sorted(t.jobs.values(), key=lambda j: j["name"]):
        desc = (job.get("description") or "").replace("\n", " ").strip()
        if job["cron"] is None:
            out.append(f"# {job['name']}: runs after {', '.join(job['depends_on'])} succeeds. {desc}".rstrip())
            continue
        line = (f"{job['schedule']} root {t.python} {runner} --table {table_path} run {job['name']}"
                f" >> {t.logs}/runner.log 2>&1")
        if desc:
            out.append(f"# {job['name']}: {desc}")
        old = held(t, job)
        if not job["enabled"]:
            out.append("# disabled: " + line)
        elif old:
            out.append(f"# held while {t.cron_dir / old} exists: " + line)
        else:
            out.append(line)
    return "\n".join(out) + "\n"


def write_cron(t: Table, dry_run: bool = False, prune_legacy: bool = False) -> list[str]:
    did = []
    if dry_run:
        sys.stdout.write(render_cron(t))
        return did
    if prune_legacy:
        keep = Path(os.environ.get("PYTHIA_LEGACY_CRON_DIR", "/etc/pythia/cron-legacy"))
        names = sorted({r for j in t.jobs.values() if j["enabled"] for r in j["replaces"]} | set(LEGACY_CRON))
        for n in names:
            f = t.cron_dir / n
            if f.exists():
                keep.mkdir(parents=True, exist_ok=True)
                shutil.move(str(f), str(keep / n))
                did.append(f"moved {f} to {keep / n}")
    t.cron_dir.mkdir(parents=True, exist_ok=True)
    dest = t.cron_dir / CRON_FILE
    tmp = t.cron_dir / f".{CRON_FILE}.tmp"
    tmp.write_text(render_cron(t), encoding="utf-8")
    os.chmod(tmp, 0o644)
    os.replace(tmp, dest)
    did.append(f"wrote {dest}")
    t.logs.mkdir(parents=True, exist_ok=True)
    # When each job went live in the rendered file: a job counts as late only
    # for fires after that (a held job's earlier fires were the old file's).
    now = _iso(_now())
    marker = t.ops_dir / "installed_at"
    if not marker.exists():
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(now + "\n")
    live = _read_json(t.ops_dir / "installed.json") or {}
    for job in t.jobs.values():
        # a job that runs after others counts from its own install too, else a new one looked late for its
        # dependencies' earlier runs (exec-dryrun, 2026-10-28)
        active = job["enabled"] and (job["cron"] is not None or job["depends_on"]) and held(t, job) is None
        if active:
            live.setdefault(job["name"], now)
        else:
            live.pop(job["name"], None)
    _write_json(t.ops_dir / "installed.json", live)
    for old, names in sorted(legacy_present(t).items()):
        did.append(f"held until {t.cron_dir / old} is gone (render --prune-legacy): {', '.join(sorted(names))}")
    return did


# ================================================================ helpers

def _now() -> datetime:
    fake = os.environ.get("PYTHIA_JOBS_NOW")  # tests only
    if fake:
        return datetime.fromisoformat(fake.replace("Z", "+00:00"))
    return datetime.now(timezone.utc).replace(microsecond=0)


def _iso(d: datetime | None) -> str | None:
    return None if d is None else d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(s) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None


def _read_json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write_json(p: Path, data) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f".{p.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, p)


def read_env_file(path: str | None) -> dict[str, str]:
    """KEY=VALUE lines (optional `export`, quotes stripped). Missing file: empty."""
    out: dict[str, str] = {}
    if not path:
        return out
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return out
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        if k.startswith("export "):
            k = k[len("export "):].strip()
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", k):
            out[k] = v
    return out


def rotate_log(path: Path, max_bytes: int, keep: int) -> bool:
    """job.log -> job.log.1 -> ... -> job.log.<keep>, once it is over max_bytes."""
    try:
        if path.stat().st_size < max_bytes:
            return False
    except OSError:
        return False
    for i in range(keep, 0, -1):
        src = path.with_name(f"{path.name}.{i - 1}") if i > 1 else path
        dst = path.with_name(f"{path.name}.{i}")
        if src.exists():
            os.replace(src, dst)
    return True


# ================================================================ locks

class Locks:
    """Exclusive flocks on <dir>/<name>.lock, taken in sorted order."""

    def __init__(self, directory: Path, names: list[str]):
        self.dir = directory
        self.names = sorted(names)
        self.fds: list[int] = []

    def acquire(self, wait_s: float = 0, poll_s: float = 1.0) -> str | None:
        """None when all are held; else the name of the lock that stayed busy."""
        self.dir.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + wait_s
        for n in self.names:
            # Never through a symlink: the runner is root and a container may see this folder.
            fd = os.open(self.dir / f"{n}.lock", os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o644)
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError as e:
                    if e.errno not in (errno.EAGAIN, errno.EACCES, errno.EWOULDBLOCK):
                        raise
                    if time.monotonic() >= deadline:
                        os.close(fd)
                        self.release()
                        return n
                    time.sleep(poll_s)
            self.fds.append(fd)
        return None

    def release(self) -> None:
        for fd in self.fds:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)
        self.fds = []


def lock_busy(directory: Path, name: str) -> bool:
    p = directory / f"{name}.lock"
    if not p.exists():
        return False
    fd = os.open(p, os.O_RDWR | getattr(os, "O_NOFOLLOW", 0))
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    except OSError:
        return True
    finally:
        os.close(fd)


# ================================================================ run records

def runs_dir(t: Table) -> Path:
    return t.ops_dir / "runs"


def append_record(t: Table, rec: dict) -> None:
    d = runs_dir(t)
    d.mkdir(parents=True, exist_ok=True)
    month = (rec.get("start") or _iso(_now()))[:7]
    with open(d / f"{month}.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, sort_keys=True) + "\n")
    # Per job: the last run, the last success and the failure streak, so the
    # status needs no scan of the history.
    sp = t.ops_dir / "state" / f"{rec['job']}.json"
    st = _read_json(sp) or {}
    st["last"] = rec
    if rec["status"] == STATUS_OK:
        st["last_ok"] = rec
        st["consecutive_failures"] = 0
    elif rec["status"] in ("failed", "timeout"):
        st["consecutive_failures"] = int(st.get("consecutive_failures") or 0) + 1
    elif rec["status"] == "blocked":
        st["last_blocked"] = rec
    _write_json(sp, st)


def job_state(t: Table, name: str) -> dict:
    return _read_json(t.ops_dir / "state" / f"{name}.json") or {}


def read_records(t: Table, job: str | None = None, months: int = 2) -> list[dict]:
    d = runs_dir(t)
    files = sorted(d.glob("*.jsonl"))[-months:] if d.exists() else []
    out = []
    for f in files:
        for line in f.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if job is None or r.get("job") == job:
                out.append(r)
    return out


def _running_path(t: Table, name: str) -> Path:
    return t.ops_dir / "running" / f"{name}.json"


def _pid_alive(pid) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError, TypeError):
        return False


def running_info(t: Table, name: str) -> dict | None:
    info = _read_json(_running_path(t, name))
    if not info or not _pid_alive(info.get("pid")):
        return None
    return info


# ================================================================ running a job

def build_argv(t: Table, job: dict) -> list[str]:
    if job["kind"] == "host":
        return ["/bin/sh", "-c", job["command"]]
    r = job["resources"]
    argv = ["docker", "run", "--rm", "--name", f"pythia-job-{job['name']}", "--label", f"pythia.job={job['name']}"]
    if job.get("network"):
        argv += ["--network", str(job["network"])]
    if r.get("cpus") is not None:
        argv += ["--cpus", str(r["cpus"])]
    if r.get("memory") is not None:
        argv += ["--memory", str(r["memory"])]
    for f in env_files(job):
        argv += ["--env-file", f]
    for k, v in sorted(job["env"].items()):
        argv += ["-e", f"{k}={v}"]
    argv += ["-v", f"{t.data}:/data"]
    if job["code"]:
        argv += ["-v", f"{t.code}:/app"]
    if plain_lab_job(job):
        for p in live_controls(t.data):
            argv += ["-v", f"{t.data}/{p}:/data/{p}:ro"]
    for v in job["volumes"]:
        src = v.split(":", 1)[0]
        if src.startswith("/") and not os.path.lexists(src):
            # docker run -v would create it as an empty root folder (a missing ack file
            # would become a directory); stop the run instead.
            raise FileNotFoundError(errno.ENOENT, "volume source missing", src)
        argv += ["-v", v]
    argv.append(job["image"])
    argv += shlex.split(job["command"])
    return argv


# What a plain lab job may never write although it mounts the whole data folder: the
# real-money controls. A plain lab job (the only kind the research agent may add or change,
# research/ops/agent/guard.py) runs code from paths.code, which the agent's rounds deploy; each
# of these that exists is mounted again read only on top of /data, so such code cannot arm,
# feed or unlock real money. Jobs with env files, a network, volumes or no code mount run code
# the agent cannot change (the guard holds every module they import) and see the folder as before.
LIVE_CONTROLS = (
    "autopilot", "autopilot-safe", "engine",                     # the engines' own state
    "live",                                                      # the pump.fun live ledger, totals, dry run
    "pumpfun_rt/idl", "pumpfun_rt/KILL",                         # the owner's IDL copies, a kill switch
    "reports/pumpfun_rt/KILL", "reports/pumpfun_rt/live_settings.json",
    "lab-cache/reports/families_summary.json",                   # the sweep's pick, which shapes the book
    "lab-cache/reports/tsmom_tranches.json",                     # the live twin copies
)


def plain_lab_job(job: dict) -> bool:
    return (job["kind"] == "lab" and bool(job["code"])
            and not (job["env_files"] or job["volumes"] or job.get("network")))


def live_controls(data: Path) -> list[str]:
    """The LIVE_CONTROLS that exist under `data`, every live twin's signal folder
    (signals/*_live) and the folder of the book each twin copies (its live_copy_of)."""
    out = [p for p in LIVE_CONTROLS if (data / p).exists() and not (data / p).is_symlink()]
    sig = data / "signals"
    for d in sorted(sig.glob("*_live")) if sig.is_dir() else []:
        if d.is_symlink() or not d.is_dir():
            continue
        out.append(f"signals/{d.name}")
        rec = _read_json(d / "latest.json")
        src = rec.get("live_copy_of") if isinstance(rec, dict) else None
        if isinstance(src, str) and re.fullmatch(r"[A-Za-z0-9_.-]+", src) and src not in (".", "..") \
                and (sig / src).is_dir() and not (sig / src).is_symlink():
            out.append(f"signals/{src}")
    return list(dict.fromkeys(out))


def env_files(job: dict) -> list[str]:
    """The job's env files. One ending in `?` is optional and left out when
    missing; a missing required one stops the run before it starts."""
    out = []
    for f in job["env_files"]:
        path = f[:-1] if f.endswith("?") else f
        if os.path.isfile(path):
            out.append(path)
        elif not f.endswith("?"):
            raise FileNotFoundError(errno.ENOENT, "env file missing", path)
    return out


def _job_env(t: Table, job: dict) -> dict[str, str]:
    env = dict(os.environ)
    env.setdefault("PYTHIA_DATA", str(t.data))
    if job["kind"] == "host":
        for f in env_files(job):
            env.update(read_env_file(f))
        env.update(job["env"])
    return env


def _alert(t: Table, key: str, **kw) -> None:
    """A job alert (`job_failed`, `job_ok_again` of notify's i18n) in the
    language of the messages."""
    if _notify is None:
        return
    saved = dict(os.environ)
    try:
        os.environ.update(read_env_file(t.alert_env))
        url, fmt, prefix = _notify.config()
        if url is None:
            return
        lang = _notify.alert_lang()
        text = alert_text(key, lang, **kw)
        ok, err = _notify.post(url, fmt, _notify.clip(f"{prefix}: {text}", lang=lang))
        if not ok:
            print(f"job alert not delivered: {err}", file=sys.stderr)
    finally:
        os.environ.clear()
        os.environ.update(saved)


def alert_text(key: str, lang: str = "en", **kw) -> str:
    """A job alert's words: job x failed (exit 1) after 12 s; log ..., or job x ok again."""
    i18n = _notify.i18n
    if "status" in kw:
        k = f"job_status_{kw['status']}"
        kw["status"] = i18n.t(k, lang) if k in i18n.CATALOG["en"] else kw["status"]
    return i18n.t(key, lang, **kw)


def _deps_ok(t: Table, job: dict, now: datetime) -> str | None:
    """None when every dependency succeeded recently; else why not."""
    for dep in job["depends_on"]:
        if running_info(t, dep):
            return f"{dep} is still running"
        st = job_state(t, dep)
        last = st.get("last") or {}
        ok_end = _parse_iso((st.get("last_ok") or {}).get("end"))
        if last.get("status") in ("failed", "timeout", "blocked"):
            return f"{dep} last ended {last['status']}"
        if ok_end is None or (now - ok_end).total_seconds() > job["depends_within_s"]:
            return f"{dep} has not succeeded in the last {job['depends_within_s'] // 3600} h"
    return None


def run_job(t: Table, name: str, force: bool = False, chain: bool = True, _depth: int = 0) -> int:
    """Run one job as cron does. Returns the job's exit code (0 when skipped)."""
    job = t.job(name)
    if not job["enabled"] and not force:
        print(f"{name}: disabled in the table, not run (--force runs it anyway)")
        return 0
    t.logs.mkdir(parents=True, exist_ok=True)
    log_path = t.logs / f"{name}.log"
    rotate_log(log_path, t.log_max_bytes, t.log_keep)
    locks = Locks(t.locks, job["locks"])
    start = _now()
    rec = {"job": name, "start": _iso(start), "host_pid": os.getpid()}

    def finish(status: str, code: int | None, reason: str | None = None) -> dict:
        end = _now()
        rec.update(end=_iso(end), duration_s=int((end - start).total_seconds()), exit_code=code,
                   status=status, reason=reason)
        append_record(t, rec)
        return rec

    with open(log_path, "a", encoding="utf-8") as log:
        def note(msg: str) -> None:
            log.write(f"[{_iso(_now())}] pythia-jobs {name}: {msg}\n")
            log.flush()

        busy = locks.acquire(job["lock_wait_s"])
        if busy:
            note(f"skipped, lock {busy} is held by another run")
            finish("skipped", None, f"lock {busy} busy")
            write_status(t)
            return 0
        why = None
        try:
            why = None if force else _deps_ok(t, job, start)
            if why:
                note(f"blocked: {why}")
                finish("blocked", None, why)
                write_status(t)
                return 0
            argv = build_argv(t, job)
            _write_json(_running_path(t, name), {"pid": os.getpid(), "start": rec["start"]})
            note(f"start, timeout {job['timeout_s']} s, locks {','.join(job['locks'])}")
            if job["kind"] != "host":
                subprocess.run(["docker", "rm", "-f", f"pythia-job-{name}"], stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, check=False)
            code, status = _execute(argv, _job_env(t, job), log, job)
            note(f"end, {status}, exit {code}")
        except OSError as e:
            why = f"could not start: {e.strerror or e}" + (f" {e.filename}" if e.filename else "")
            note(why)
            code, status = 127, "failed"
        finally:
            try:
                _running_path(t, name).unlink()
            except OSError:
                pass
            locks.release()
    r = finish(status, code, why if code == 127 else None)
    st = job_state(t, name)
    if job["alert"] and status != STATUS_OK and st.get("consecutive_failures") == 1:
        _alert(t, "job_failed", name=name, status=status, code=code, s=r["duration_s"], log=log_path)
    elif job["alert"] and status == STATUS_OK and _was_failing(t, name):
        _alert(t, "job_ok_again", name=name)
    write_status(t)
    if status == STATUS_OK and chain and _depth < 8:
        for nxt in t.chained_after(name):
            if nxt["enabled"]:
                run_job(t, nxt["name"], chain=True, _depth=_depth + 1)
    return code


def _was_failing(t: Table, name: str) -> bool:
    recs = [r for r in read_records(t, name) if r.get("status") in (STATUS_OK, "failed", "timeout")]
    return len(recs) >= 2 and recs[-2].get("status") != STATUS_OK


def _execute(argv: list[str], env: dict, log, job: dict) -> tuple[int, str]:
    p = subprocess.Popen(argv, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                         env=env, start_new_session=True)
    try:
        code = p.wait(timeout=job["timeout_s"])
        return code, (STATUS_OK if code == 0 else "failed")
    except subprocess.TimeoutExpired:
        log.write(f"[{_iso(_now())}] pythia-jobs {job['name']}: timeout after {job['timeout_s']} s, stopping\n")
        log.flush()
        if job["kind"] != "host":
            subprocess.run(["docker", "kill", f"pythia-job-{job['name']}"], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, check=False)
        for sig, wait in ((signal.SIGTERM, 20), (signal.SIGKILL, 10)):
            try:
                os.killpg(p.pid, sig)
            except OSError:
                pass
            try:
                p.wait(timeout=wait)
                break
            except subprocess.TimeoutExpired:
                continue
        return 124, "timeout"


# ================================================================ status

def job_status(t: Table, job: dict, now: datetime, installed: datetime | None) -> dict:
    st = job_state(t, job["name"])
    last = st.get("last")
    last_ok = st.get("last_ok")
    run = running_info(t, job["name"])
    out = {
        "name": job["name"],
        "description": job.get("description") or "",
        "enabled": job["enabled"],
        "schedule": job["schedule"],
        "after": job["depends_on"] if job["cron"] is None else [],
        "depends_on": job["depends_on"],
        "kind": job["kind"],
        "timeoutS": job["timeout_s"],
        "nextRun": _iso(job["cron"].next_after(now)) if job["cron"] and job["enabled"] else None,
        "last": last,
        "lastOk": (last_ok or {}).get("end"),
        "consecutiveFailures": int(st.get("consecutive_failures") or 0),
        "running": bool(run),
        "runningSince": run.get("start") if run else None,
    }
    state, ok, detail = "ok", True, ""
    last_start = _parse_iso((last or {}).get("start"))
    old = held(t, job) if job["enabled"] else None
    if not job["enabled"]:
        state, detail = "disabled", "disabled in the table"
    elif old and not run:
        state, detail = "legacy", f"still run by {t.cron_dir / old}; render --prune-legacy hands it to the table"
    elif run:
        since = _parse_iso(run.get("start")) or now
        age = (now - since).total_seconds()
        if age > job["timeout_s"] + job["grace_s"]:
            state, ok, detail = "stuck", False, f"running for {int(age // 60)} min, past its timeout"
        else:
            state, detail = "running", f"running since {run.get('start')}"
    else:
        expected = None  # the fire this job should have started for by now
        if job["cron"] is not None:
            # the latest fire whose run should be over by now (one still
            # inside its timeout plus grace does not count yet)
            prev = job["cron"].prev_at_or_before(now)
            while prev and (now - prev).total_seconds() <= job["timeout_s"] + job["grace_s"]:
                prev = job["cron"].prev_at_or_before(prev - timedelta(minutes=1))
            expected = prev
        else:
            ends = [_parse_iso((job_state(t, d).get("last_ok") or {}).get("end")) for d in job["depends_on"]]
            ends = [e for e in ends if e]
            if ends and (now - max(ends)).total_seconds() > job["grace_s"]:
                expected = max(ends)
        if expected and installed and expected < installed:
            expected = None  # fired before the table was installed
        status = (last or {}).get("status")
        if status in ("failed", "timeout"):
            state, ok = status, False
            detail = f"last run {status}, exit {last.get('exit_code')}, {out['consecutiveFailures']} in a row"
        elif status == "blocked" and expected and last_start and last_start >= expected - timedelta(minutes=1):
            state, ok, detail = "blocked", False, f"blocked: {last.get('reason')}"
        elif expected and (last_start is None or last_start < expected - timedelta(minutes=1)):
            state, ok, detail = "late", False, f"no run since {_iso(expected)}"
        elif last is None:
            state, detail = "never", "not run yet"
        else:
            when = (last_ok or {}).get("end") or last.get("end")
            detail = f"last {status} {when}" + (f" ({last.get('reason')})" if last.get("reason") else "")
    out.update(state=state, ok=ok, detail=detail)
    return out


def build_status(t: Table, now: datetime | None = None) -> dict:
    now = now or _now()
    installed = _parse_iso(((t.ops_dir / "installed_at").read_text().strip()
                            if (t.ops_dir / "installed_at").exists() else None))
    live = _read_json(t.ops_dir / "installed.json") or {}
    jobs = [job_status(t, j, now, _parse_iso(live.get(j["name"])) or installed)
            for j in sorted(t.jobs.values(), key=lambda j: j["name"])]
    failing = [j["name"] for j in jobs if not j["ok"]]
    return {"at": _iso(now), "ok": not failing, "failing": failing, "table": t.path, "jobs": jobs,
            "disk": _read_json(t.ops_dir / "disk" / "latest.json")}


def write_status(t: Table, now: datetime | None = None) -> dict:
    s = build_status(t, now)
    _write_json(t.status_path, s)
    return s


# ================================================================ disk and datasets

def _du_bytes(p: Path) -> int:
    if not p.exists():
        return 0
    try:
        r = subprocess.run(["du", "-sb", str(p)], capture_output=True, text=True, timeout=600, check=False)
        if r.returncode == 0 and r.stdout.split():
            return int(r.stdout.split()[0])
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    total = 0
    for root, _dirs, files in os.walk(p):
        for f in files:
            try:
                total += os.lstat(os.path.join(root, f)).st_size
            except OSError:
                pass
    return total


def _free_fall(hist: list[dict], cur: dict, span_days: float) -> float | None:
    """Bytes a day the free space fell over about `span_days` (the oldest entry at least a day and at
    most span plus half a day back); negative when it grew, None without such an entry."""
    cur_at = _parse_iso(cur["at"])
    for h in hist:
        at = _parse_iso(h.get("at"))
        if at and h.get("free") is not None and cur.get("free") is not None \
                and timedelta(days=1) <= cur_at - at <= timedelta(days=span_days + 0.5):
            return (h["free"] - cur["free"]) / ((cur_at - at).total_seconds() / 86400)
    return None


def _used(h: dict) -> int | None:
    if h.get("used") is not None:
        return h["used"]
    return None if h.get("free") is None or h.get("total") is None else h["total"] - h["free"]


def measure_disk(t: Table, now: datetime | None = None, every_s: int = 6 * 3600, force: bool = False) -> dict:
    """Size per dataset and free space; measured at most every `every_s`, kept as history.
    Days left come from the fall in free space over 3 and 7 days (the faster one), not from the
    tracked folders alone: what fills the disk outside them (docker, caches) counts too and is
    reported as the untracked use (used minus the tracked folders)."""
    now = now or _now()
    d = t.ops_dir / "disk"
    hist_path = d / "history.jsonl"
    hist = []
    if hist_path.exists():
        for line in hist_path.read_text(encoding="utf-8").splitlines():
            try:
                hist.append(json.loads(line))
            except ValueError:
                pass
    last_at = _parse_iso(hist[-1]["at"]) if hist else None
    if force or last_at is None or (now - last_at).total_seconds() >= every_s:
        du = shutil.disk_usage(t.data) if t.data.exists() else None
        entry = {"at": _iso(now), "free": du.free if du else None, "total": du.total if du else None,
                 "used": du.used if du else None,
                 "sizes": {ds["name"]: _du_bytes(t.data / ds["path"]) for ds in t.datasets}}
        hist.append(entry)
        d.mkdir(parents=True, exist_ok=True)
        with open(hist_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, sort_keys=True) + "\n")
    cur = hist[-1]
    cur_at = _parse_iso(cur["at"])
    # growth per day against the oldest entry of the last 7 days (at least a day back)
    base = None
    for h in hist:
        at = _parse_iso(h["at"])
        if at and timedelta(days=1) <= cur_at - at <= timedelta(days=8):
            base = h
            break
    days = (cur_at - _parse_iso(base["at"])).total_seconds() / 86400 if base else None
    gb = 1024 ** 3
    rows, total_growth = [], 0.0
    for ds in t.datasets:
        size = cur["sizes"].get(ds["name"], 0)
        growth = ((size - base["sizes"].get(ds["name"], 0)) / days) if base and days else None
        if growth is not None:
            total_growth += max(growth, 0)
        max_gb = ds.get("max_gb")
        ok = max_gb is None or size <= float(max_gb) * gb
        rows.append({"name": ds["name"], "path": ds["path"], "bytes": size, "gb": round(size / gb, 2),
                     "growthGbPerDay": None if growth is None else round(growth / gb, 3),
                     "maxGb": max_gb, "retentionDays": ds.get("retention_days"), "ok": ok,
                     "description": ds.get("description") or ""})
    free = cur.get("free")
    falls = {k: _free_fall(hist, cur, n) for k, n in (("3d", 3), ("7d", 7))}
    fall = max((v for v in falls.values() if v is not None), default=None)
    days_left = (free / fall) if free is not None and fall is not None and fall > 0 else None
    disk_ok = free is not None and free / gb >= t.min_free_gb and (days_left is None or days_left >= 14)
    tracked = sum(cur["sizes"].values())
    used = _used(cur)
    untracked = None if used is None else max(used - tracked, 0)
    base_used = _used(base) if base else None
    untracked_growth = (untracked - max(base_used - sum(base["sizes"].values()), 0)) / days \
        if untracked is not None and base_used is not None and days else None
    out = {"at": cur["at"], "freeGb": None if free is None else round(free / gb, 1),
           "totalGb": None if cur.get("total") is None else round(cur["total"] / gb, 1),
           "minFreeGb": t.min_free_gb, "growthGbPerDay": round(total_growth / gb, 3) if base else None,
           "freeFallGbPerDay": {k: None if v is None else round(v / gb, 2) for k, v in falls.items()},
           "daysLeft": None if days_left is None else round(days_left, 1), "ok": disk_ok,
           "trackedGb": round(tracked / gb, 1), "untrackedGb": None if untracked is None else round(untracked / gb, 1),
           "untrackedGrowthGbPerDay": None if untracked_growth is None else round(untracked_growth / gb, 2),
           "datasets": rows}
    _write_json(d / "latest.json", out)
    return out


def health_checks(t: Table, now: datetime | None = None) -> list[tuple[str, bool, str]]:
    """(name, ok, detail) for every enabled job, the disk, every dataset, every feed of an enabled job,
    while the backup job is on, the backup (its contents, the copy off the server, the restore test), and
    a red line per leak the weekly leak check found (leak_lines)."""
    now = now or _now()
    disk = measure_disk(t, now)
    status = write_status(t, now)
    out = []
    for j in status["jobs"]:
        if not j["enabled"]:
            continue
        out.append((f"job {j['name']}", j["ok"], j["detail"]))
    if disk["freeGb"] is None:
        out.append(("disk", False, f"data root {t.data} not found"))
    else:
        fall = max((v for v in (disk.get("freeFallGbPerDay") or {}).values() if v is not None), default=None)
        left = f", full in about {disk['daysLeft']:.0f} days at {fall} GB a day" \
            if disk.get("daysLeft") is not None else ""
        other = f", {disk['untrackedGb']} GB used outside the tracked folders" \
            if disk.get("untrackedGb") is not None else ""
        out.append(("disk", disk["ok"], f"{disk['freeGb']} GB free of {disk['totalGb']}{left}{other}"))
    ages = {ds["name"]: ds["max_age_h"] for ds in t.datasets if ds.get("max_age_h") is not None}
    for ds in disk["datasets"]:
        g = "" if ds["growthGbPerDay"] is None else f", {ds['growthGbPerDay']:+} GB a day"
        cap = "" if ds["maxGb"] is None else f", limit {ds['maxGb']} GB"
        keep = "" if not ds["retentionDays"] else f", kept {ds['retentionDays']} days"
        ok, age = ds["ok"], ""
        if ds["name"] in ages:
            newest = newest_mtime(t.data / ds["path"])
            if newest is None:
                ok, age = False, f", no file (may be {ages[ds['name']]} h old)"
            else:
                h = (now.timestamp() - newest) / 3600
                ok = ok and h <= ages[ds["name"]]
                age = f", newest file {h:.0f} h old" + ("" if h <= ages[ds["name"]] else f" (may be {ages[ds['name']]} h)")
        out.append((f"data {ds['name']}", ok, f"{ds['gb']} GB{g}{cap}{keep}{age}"))
    for f in t.feeds:
        if f.get("job") and not t.jobs[f["job"]]["enabled"]:
            continue
        out.append(feed_check(t, f, now))
    if "backup" in t.jobs and t.jobs["backup"]["enabled"]:
        out.extend(backup_checks(t, now))
    out.extend(leak_lines(t))
    return out


LEAK_RED = ("feature", "candles", "zoo", "book")


def leak_lines(t: Table) -> list[tuple[str, bool, str]]:
    """T1: a red line per feature, zoo builder or paper book the weekly leak check (lab.leak, job leak-check) found
    leaking or could not check, from reports/leak/latest.json; nothing before its first report."""
    doc = _read_json(t.data / "reports" / "leak" / "latest.json")
    if not isinstance(doc, dict):
        return []
    return [(f"leak {r.get('kind')} {r.get('name')}", False, str(r.get("why") or r.get("error") or "leak")[:200])
            for r in doc.get("results") or [] if isinstance(r, dict) and not r.get("ok") and r.get("kind") in LEAK_RED]


def newest_mtime(p: Path) -> float | None:
    """Modification time of the newest regular file under `p` (symlinks not followed), None without one."""
    if p.is_file():
        return p.lstat().st_mtime
    newest = None
    for root, _dirs, files in os.walk(p):
        for f in files:
            try:
                st = os.lstat(os.path.join(root, f))
            except OSError:
                continue
            if stat.S_ISREG(st.st_mode) and (newest is None or st.st_mtime > newest):
                newest = st.st_mtime
    return newest


def feed_check(t: Table, f: dict, now: datetime) -> tuple[str, bool, str]:
    """One free data source (lab.collect.pit's health.json): its last run, the newest value of
    each table no older than max_age, gaps in the last 7 days at most max_gaps, schema and errors."""
    name = f"feed {f['name']}"
    doc = _read_json(t.data / f["status"])
    if not isinstance(doc, dict):
        if _first_period(t, f.get("job"), now):
            return name, True, "not run yet"
        return name, False, f"no status file {f['status']}"
    at = _parse_iso(doc.get("at"))
    bad, parts = [], []
    if at is None or (now - at).total_seconds() > f["max_age_s"]:
        bad.append(f"last run {doc.get('at') or 'unknown'}")
    for tname, h in sorted((doc.get("tables") or {}).items()):
        last = h.get("last_ts_us")
        age_h = None if last is None else (now.timestamp() - last / 1e6) / 3600
        if age_h is None:
            bad.append(f"{tname} empty")
        elif age_h * 3600 > f["max_age_s"]:
            bad.append(f"{tname} {age_h:.0f} h old")
        if not h.get("schema_ok", True):
            bad.append(f"{tname} lacks {', '.join(h.get('missing') or [])}")
        if (h.get("gaps") or 0) > f["max_gaps"]:
            bad.append(f"{tname} {h['gaps']} gaps in 7 days")
        if age_h is not None:
            parts.append(f"{tname} {age_h:.0f} h old, {h.get('rows')} rows")
    for part, err in sorted((doc.get("errors") or {}).items()):
        bad.append(f"{part} failed: {err}"[:120])
    return name, not bad, "; ".join(bad or parts)


def _installed(t: Table, name: str) -> datetime | None:
    """When the job came into the installed table (installed.json, else installed_at), None when unknown."""
    live = _read_json(t.ops_dir / "installed.json") or {}
    at = (t.ops_dir / "installed_at").read_text().strip() if (t.ops_dir / "installed_at").exists() else None
    return _parse_iso(live.get(name)) or _parse_iso(at)


def _first_period(t: Table, name: str | None, now: datetime) -> bool:
    """The job has not run yet (state never) and was installed less than one schedule period plus an hour
    ago (a chained job: one day); without an install time never."""
    job = t.jobs.get(name) if name else None
    installed = _installed(t, name) if job else None
    if job is None or installed is None or job_status(t, job, now, installed)["state"] != "never":
        return False
    period = timedelta(days=1)
    if job["cron"] is not None:
        nxt = job["cron"].next_after(now)
        after = job["cron"].next_after(nxt) if nxt else None
        if nxt and after:
            period = after - nxt
    return now - installed < period + timedelta(hours=1)


# ================================================================ retention

def prune(t: Table, dry_run: bool = False, now: datetime | None = None) -> dict:
    """Delete files older than a dataset's retention_days (by modification time).

    Only datasets with retention_days are touched, only regular files under the
    dataset's own folder, matching its `pattern` (default every file), never
    following a symlink. Empty folders left behind are removed."""
    now = now or _now()
    root = t.data.resolve()
    report = {"at": _iso(now), "dryRun": dry_run, "datasets": []}
    for ds in t.datasets:
        days = ds.get("retention_days")
        if not days:
            continue
        base = (t.data / ds["path"])
        if base.is_symlink() or not base.is_dir():
            report["datasets"].append({"name": ds["name"], "files": 0, "bytes": 0, "note": "not found"})
            continue
        if root not in base.resolve().parents and base.resolve() != root:
            raise TableError(f"dataset {ds['name']}: resolves outside the data root")
        cutoff = now.timestamp() - int(days) * 86400
        pats = [str(p) for p in _as_list(ds.get("pattern"))] or ["*"]
        n = size = 0
        for dirpath, dirnames, files in os.walk(base, topdown=False, followlinks=False):
            for f in files:
                fp = os.path.join(dirpath, f)
                if not any(fnmatch.fnmatch(f, p) for p in pats):
                    continue
                try:
                    stt = os.lstat(fp)
                except OSError:
                    continue
                if not os.path.isfile(fp) or os.path.islink(fp) or stt.st_mtime >= cutoff:
                    continue
                n += 1
                size += stt.st_size
                if not dry_run:
                    os.unlink(fp)
            if not dry_run and dirpath != str(base):
                try:
                    os.rmdir(dirpath)  # only succeeds when empty
                except OSError:
                    pass
        report["datasets"].append({"name": ds["name"], "files": n, "bytes": size, "olderThanDays": days})
    if not dry_run:
        _write_json(t.ops_dir / "prune" / "latest.json", report)
    return report


# ================================================================ backup

def _backup_conf(t: Table) -> dict:
    b = t.backup
    return {"dest": Path(b.get("dest", "/srv/pythia-backup")),
            "include": [str(x) for x in _as_list(b.get("include"))],
            "exclude": [str(x) for x in _as_list(b.get("exclude"))] or ["*.tmp", "*.lock"],
            "keep_daily": int(b.get("keep_daily", 7)), "keep_weekly": int(b.get("keep_weekly", 4))}


def backup(t: Table, dry_run: bool = False, now: datetime | None = None) -> dict:
    """tar.gz of the important state under <dest>, plus its sha256 and manifest; then rotate.

    `include` lists paths relative to the data root (folders or files; a
    missing one is listed, not fatal). Archives are written under a temporary
    name and renamed when complete, mode 600."""
    now = now or _now()
    c = _backup_conf(t)
    if not c["include"]:
        raise TableError("backup: nothing to include")
    for inc in c["include"]:
        if Path(inc).is_absolute() or ".." in Path(inc).parts:
            raise TableError(f"backup: {inc!r} must be relative to the data root")
    present = [i for i in c["include"] if (t.data / i).exists()]
    missing = [i for i in c["include"] if i not in present]
    if not present:
        raise TableError("backup: none of the included paths exist under " + str(t.data))
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    name = f"pythia-state-{stamp}.tar.gz"
    out = {"at": _iso(now), "archive": str(c["dest"] / name), "included": present, "missing": missing}
    if dry_run:
        out["dryRun"] = True
        out["wouldDelete"] = [str(p) for p in rotate_backups(c["dest"], c["keep_daily"], c["keep_weekly"],
                                                               dry_run=True, extra=[name])]
        return out
    c["dest"].mkdir(parents=True, exist_ok=True)
    os.chmod(c["dest"], 0o700)
    tmp = c["dest"] / f".{name}.part"
    files = 0

    def keep(ti: tarfile.TarInfo):
        nonlocal files
        base = os.path.basename(ti.name)
        if any(fnmatch.fnmatch(base, p) for p in c["exclude"]):
            return None
        if ti.isfile():
            files += 1
        return ti

    old_umask = os.umask(0o077)
    try:
        with tarfile.open(tmp, "w:gz") as tar:
            for inc in present:
                tar.add(str(t.data / inc), arcname=inc, filter=keep)
    finally:
        os.umask(old_umask)
    sha = _sha256_file(tmp)
    sums: dict[str, str] = {}
    with tarfile.open(tmp, "r:gz") as tar:  # it reads back; the sha256 of every file goes in the manifest
        for m in tar:
            if m.isfile():
                sums[m.name] = _sha256_file(tar.extractfile(m))
    if len(sums) != files:
        tmp.unlink()
        raise RuntimeError(f"backup: archive has {len(sums)} files, expected {files}")
    os.replace(tmp, c["dest"] / name)
    (c["dest"] / f"{name}.sha256").write_text(f"{sha}  {name}\n")
    out.update(files=files, bytes=(c["dest"] / name).stat().st_size, sha256=sha)
    _write_json(c["dest"] / f"{name}.json", dict(out, checksums=sums))
    out["deleted"] = [str(p) for p in rotate_backups(c["dest"], c["keep_daily"], c["keep_weekly"])]
    _write_json(t.ops_dir / "backup" / "latest.json", out)
    return out


_ARCH = re.compile(r"^pythia-state-(\d{8}T\d{6}Z)\.tar\.gz$")


def _sha256_file(f) -> str:
    """sha256 of a path or of an open binary file."""
    h = hashlib.sha256()
    fh = open(f, "rb") if isinstance(f, (str, os.PathLike)) else f
    try:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    finally:
        fh.close()
    return h.hexdigest()


def _archives(dest: Path) -> list[tuple[datetime, str]]:
    """(stamp, name) of every archive under dest, oldest first."""
    names = [p.name for p in dest.glob("pythia-state-*.tar.gz")] if dest.exists() else []
    return sorted((datetime.strptime(m.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc), n)
                  for n in names if (m := _ARCH.match(n)))


def restore_test(t: Table, now: datetime | None = None) -> dict:
    """Unpack the newest archive into a temporary folder under <dest> and compare
    every file's sha256 with the archive's manifest (and the archive's with its
    .sha256). Writes <data>/_ops/backup/restore.json; ok false on any difference."""
    now = now or _now()
    c = _backup_conf(t)
    arch = _archives(c["dest"])
    out: dict = {"at": _iso(now), "ok": False, "problems": []}
    bad = out["problems"]
    if not arch:
        bad.append(f"no archive under {c['dest']}")
    else:
        name = arch[-1][1]
        path = c["dest"] / name
        out["archive"] = str(path)
        side = c["dest"] / f"{name}.sha256"
        want = side.read_text().split()[0] if side.exists() else None
        if want is None:
            bad.append(f"{name}.sha256 missing")
        elif _sha256_file(path) != want:
            bad.append("archive sha256 differs from its .sha256")
        man = _read_json(c["dest"] / f"{name}.json")
        sums = man.get("checksums") if isinstance(man, dict) else None
        if not isinstance(sums, dict) or not sums:
            bad.append(f"{name}.json has no checksums")
        if not bad:
            tmp = Path(tempfile.mkdtemp(prefix=".restore-", dir=c["dest"]))
            try:
                with tarfile.open(path, "r:gz") as tar:
                    for m in tar:
                        parts = Path(m.name).parts
                        if not m.isfile() or Path(m.name).is_absolute() or ".." in parts:
                            continue
                        target = tmp.joinpath(*parts)
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with tar.extractfile(m) as src, open(target, "wb") as dst:
                            shutil.copyfileobj(src, dst, 1 << 20)
                got = {p.relative_to(tmp).as_posix(): _sha256_file(p) for p in tmp.rglob("*") if p.is_file()}
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
            lost = sorted(set(sums) - set(got))
            differ = sorted(k for k in sums if k in got and got[k] != sums[k])
            extra = sorted(set(got) - set(sums))
            out.update(files=len(got), lost=lost[:20], differ=differ[:20], extra=extra[:20])
            if lost or differ or extra:
                bad.append(f"{len(lost)} files lost, {len(differ)} differ, {len(extra)} not in the manifest")
    out["ok"] = not bad
    _write_json(t.ops_dir / "backup" / "restore.json", out)
    return out


def backup_checks(t: Table, now: datetime) -> list[tuple[str, bool, str]]:
    """The last backup has every included entry; its copy off the server (the receipt
    research/sync-to-pc.sh leaves in <dest>/offsite.json) is behind the newest archive
    for at most backup.offsite_max_age; the last restore test passed."""
    c = _backup_conf(t)
    out = []
    last = _read_json(t.ops_dir / "backup" / "latest.json")
    if not isinstance(last, dict):
        out.append(("backup", False, "no backup report yet"))
    else:
        miss = last.get("missing") or []
        out.append(("backup", not miss, (f"missing: {', '.join(miss)}" if miss else
                    f"{Path(str(last.get('archive'))).name}, {last.get('files')} files, "
                    f"{(last.get('bytes') or 0) / 1e6:.0f} MB")))
    max_age = parse_duration(t.backup.get("offsite_max_age", "1d"), "backup offsite_max_age")
    rec = _read_json(c["dest"] / "offsite.json")
    m = _ARCH.match(str(rec.get("archive", ""))) if isinstance(rec, dict) else None
    if not m:
        out.append(("backup off-server", False, "no copy off the server yet (research/sync-to-pc.sh)"))
    else:
        stamp = datetime.strptime(m.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        newer = [s for s, _n in _archives(c["dest"]) if s > stamp]
        behind_h = (now - newer[0]).total_seconds() / 3600 if newer else 0.0
        side = c["dest"] / f"{rec['archive']}.sha256"
        sha_ok = not side.exists() or side.read_text().split()[0] == rec.get("sha256")
        detail = f"{rec['archive']} checked {rec.get('at') or 'unknown'}"
        if newer:
            detail += f", {behind_h:.0f} h behind the newest archive"
        if not sha_ok:
            detail += ", checksum differs from the server's"
        out.append(("backup off-server", sha_ok and behind_h * 3600 <= max_age, detail))
    r = _read_json(t.ops_dir / "backup" / "restore.json")
    if not isinstance(r, dict):
        out.append(("backup restore", False, "never tested: python3 /opt/pythia-ops/jobs.py run restore-test --force"))
    else:
        what = f"{Path(str(r.get('archive'))).name}, {r.get('files')} files" if r.get("archive") else ""
        out.append(("backup restore", bool(r.get("ok")),
                    f"tested {r.get('at')}: " + ("; ".join(r.get("problems") or []) or what)))
    return out


def rotate_backups(dest: Path, keep_daily: int, keep_weekly: int, dry_run: bool = False,
                   extra: list[str] | None = None) -> list[Path]:
    """Keep the newest archive of each of the last `keep_daily` days and of each
    of the last `keep_weekly` ISO weeks; delete the rest (with their .sha256 and .json)."""
    names = [p.name for p in dest.glob("pythia-state-*.tar.gz")] if dest.exists() else []
    names += extra or []
    stamped = sorted(((datetime.strptime(m.group(1), "%Y%m%dT%H%M%SZ"), n)
                      for n in set(names) if (m := _ARCH.match(n))), reverse=True)
    keep: set[str] = set()
    days: list = []
    weeks: list = []
    for ts, n in stamped:
        d = ts.date()
        w = ts.isocalendar()[:2]
        if d not in days and len(days) < keep_daily:
            days.append(d)
            keep.add(n)
        if w not in weeks and len(weeks) < keep_weekly:
            weeks.append(w)
            keep.add(n)
    gone = []
    for _ts, n in stamped:
        if n in keep:
            continue
        gone.append(dest / n)
        if not dry_run:
            for suffix in ("", ".sha256", ".json"):
                p = dest / f"{n}{suffix}"
                if p.exists():
                    p.unlink()
    return gone


# ================================================================ command line

def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    table_path = None
    if "--table" in argv:
        i = argv.index("--table")
        if i + 1 >= len(argv):
            print("--table needs a path", file=sys.stderr)
            return 2
        table_path = argv[i + 1]
        del argv[i:i + 2]
    flags = {a for a in argv if a.startswith("--")}
    args = [a for a in argv if not a.startswith("--")]
    if not args or args[0] in ("help", "-h"):
        print(__doc__)
        return 0 if args else 2
    cmd = args[0]
    try:
        t = load_table(table_path)
        if cmd == "validate":
            for j in sorted(t.jobs.values(), key=lambda j: j["name"]):
                when = j["schedule"] or "after " + ", ".join(j["depends_on"])
                print(f"{'on ' if j['enabled'] else 'off'}  {j['name']:<22} {when:<16} {j['kind']:<5} "
                      f"timeout {j['timeout_s']}s lock {','.join(j['locks'])}")
            print(f"{len(t.jobs)} jobs, {len(t.datasets)} datasets: ok")
            return 0
        if cmd == "render":
            for line in write_cron(t, "--dry-run" in flags, "--prune-legacy" in flags):
                print(line)
            return 0
        if cmd == "run":
            if len(args) < 2:
                print("run needs a job name", file=sys.stderr)
                return 2
            return run_job(t, args[1], force="--force" in flags, chain="--no-chain" not in flags)
        if cmd == "status":
            s = write_status(t) if "--write" in flags else build_status(t)
            print(json.dumps(s, indent=2))
            return 0
        if cmd == "checks":
            for name, ok, detail in health_checks(t):
                print(f"{name}\t{'true' if ok else 'false'}\t{detail}".replace("\n", " "))
            return 0
        if cmd == "disk":
            print(json.dumps(measure_disk(t, force="--now" in flags), indent=2))
            return 0
        if cmd == "prune":
            print(json.dumps(prune(t, dry_run="--dry-run" in flags), indent=2))
            return 0
        if cmd == "backup":
            print(json.dumps(backup(t, dry_run="--dry-run" in flags), indent=2))
            return 0
        if cmd == "restore-test":
            r = restore_test(t)
            print(json.dumps(r, indent=2))
            return 0 if r["ok"] else 1
    except TableError as e:
        print(f"jobs table: {e}", file=sys.stderr)
        return 2
    print(f"unknown command {cmd!r}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
