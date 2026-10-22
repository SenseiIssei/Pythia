"""Tests of the research agent's guard (guard.py): every case of the 2026-10-22 audit.

    python -m pytest -q research/ops/agent/test_guard.py

Needs git and a POSIX system (the job runner it loads uses fcntl). The private values
the patterns must catch are assembled at run time, so this file itself holds none.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("fcntl")
sys.path.insert(0, str(Path(__file__).resolve().parent))
import guard  # noqa: E402

OWNER = ("SenseiIssei", "owner@example.com")
AT = chr(64)
PUBLIC_V4 = ".".join(["93", "184", "216", "34"])
PUBLIC_V6 = ":".join(["2a01", "4f8", "c17", "1a2b"]) + "::1"
B58 = "".join("5Kb8kLf9zgWQnogidDA76MzPL6TsZZY36hWXMssSzNydYXYB9KF"[i % 51] for i in range(88))
PEM = "-----BEGIN " + "CERTIFICATE-----"
KEY_LINES = ["key = [" + ", ".join(str(i % 256) for i in range(32)) + ",",
             "  " + ", ".join(str(200 - i) for i in range(32)) + ",", "]"]


# ---------------------------------------------------------------- the patterns

@pytest.mark.parametrize("text,kind", [
    (f"the server is {PUBLIC_V4}", "public IP address"),
    (f"ssh root{AT}{PUBLIC_V4}.", "public IP address"),
    (f"bind [{PUBLIC_V6}]:443", "public IPv6 address"),
    (f"mail me: alice{AT}mailbox.de", "e-mail address"),
    ("mail me: alice%40mailbox.de", "e-mail address"),
    ("mail me: alice (at) mailbox.de", "e-mail address"),
    (f"secret = {B58}", "base58 secret"),
    (PEM, "PEM block"),
    ("ANTHROPIC_API_KEY=" + "sk-ant-" + "a1" * 20, "key or token"),
    ("api-key=" + "Zx81" * 6, "api key value"),
    ('{"api_key": "' + "q9W" * 6 + '"}', "api key value"),
    ("c:\\users\\alice\\Desktop", "personal Windows path"),
    ("/mnt/c/" + "Users/alice/projects", "personal Windows path"),
    ("cd /home/alice", "personal home path"),
    ("open /Users/alice", "personal home path"),
    ("key = [" + ",".join(["7"] * 64) + ",]", "64-number key array"),
])
def test_each_pattern_catches_its_case(text, kind):
    assert kind in guard.private_kinds(text)


@pytest.mark.parametrize("text", [
    "documentation hosts 192.0.2.10, 198.51.100.7 and 203.0.113.9",
    "private 10.0.0.1, 192.168.1.20, 172.16.4.2 and 127.0.0.1, any 0.0.0.0",
    "IPv6 documentation 2001:db8::1, loopback ::1, link local fe80::1",
    f"write to someone{AT}example.com or {AT}example.org",
    f"icon{AT}2x.png",
    "a[1::2] at 10:30:00, mac aa:bb:cc:dd:ee:ff",
    "a sha256 3f5a0c1e9b7d2a4f6e8c0b1d3a5f7e9c2b4d6f8a0c1e3b5d7f9a1c3e5b7d9f1a",
    'api_key = os.environ["ANTHROPIC_API_KEY"]',
    "C:\\Users\\<you>\\Pythia and /home/user/x and /home/agent and /home/runner/work",
    "version 1.2.3 and 1.1.1.1",
])
def test_documentation_and_placeholders_pass(text):
    assert guard.private_kinds(text) == []


def test_owner_patterns_file(tmp_path):
    p = tmp_path / "private-patterns.txt"
    p.write_text("# the owner's own\nmy-domain.example\nre:panel/[a-z]+\n", encoding="utf-8")
    pats = guard.load_patterns(str(p))
    assert "one of the owner's private patterns" in guard.private_kinds("see MY-DOMAIN.example", pats)
    assert "one of the owner's private patterns" in guard.private_kinds("/panel/someone", pats)
    assert guard.private_kinds("nothing here", pats) == []
    (tmp_path / "empty.txt").write_text("# none\n", encoding="utf-8")
    with pytest.raises(ValueError):
        guard.load_patterns(str(tmp_path / "empty.txt"))


# ---------------------------------------------------------------- a small repository

TABLE = """\
paths:
  data: /srv/pythia-data
defaults:
  kind: lab
  image: pythia-lab
jobs:
  - name: paper-families
    schedule: "15 4 * * *"
    command: python -m lab.paper.families
    code: false
    volumes: [/opt/pythia-live:/app:ro]
  - name: paper-live-copy
    depends_on: [paper-families]
    command: python -m lab.paper.live_copy
    code: false
    volumes: [/opt/pythia-live:/app:ro]
  - name: digest
    schedule: "0 7 * * *"
    command: python -m lab.paper.digest_book
    env_file: /etc/pythia/alerts.env
  - name: book
    schedule: "0 5 * * *"
    command: python -m lab.paper.book
    lock: heavy
"""

FILES = {
    "research/lab/lab/__init__.py": "",
    "research/lab/lab/data.py": "ROOT = '/data'\n",
    "research/lab/lab/paper/__init__.py": "",
    "research/lab/lab/paper/families.py": "from ..experiments import fam_x\n",
    "research/lab/lab/paper/live_copy.py": "import json\n",
    "research/lab/lab/paper/book.py": "from ..experiments import study\n",
    "research/lab/lab/paper/digest_book.py": "from ..experiments.shared import f\n",
    "research/lab/lab/paper/helper.py": "X = 1\n",
    "research/lab/lab/experiments/__init__.py": "",
    "research/lab/lab/experiments/fam_x.py": "import importlib\nm = importlib.import_module(f'lab.experiments.fam_{1}')\n",
    "research/lab/lab/experiments/fam_y.py": "Y = 2\n",
    "research/lab/lab/experiments/shared.py": "def f():\n    return 1\n",
    "research/lab/lab/experiments/study.py": "A = 1\n",
    "research/lab/lab/pumpfun_rt/__init__.py": "",
    "research/lab/lab/pumpfun_rt/live.py": "from ..paper import helper\n",
    "research/lab/lab/ops/__init__.py": "",
    "research/lab/lab/ai/__init__.py": "",
    "research/lab/lab/factory/__init__.py": "",
    "research/lab/results/old.md": "old\n",
    "research/lab/README.md": "# Lab\n",
    "research/ops/jobs.yaml": TABLE,
    "crates/core/lib.rs": "fn main() {}\n",
    ".gitattributes": "* text=auto eol=lf\n",
}


BASE: dict = {}


def sh(repo: Path, *args: str, env: dict | None = None) -> str:
    e = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1", **(env or {})}
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True, env=e).stdout


def who(name=OWNER[0], mail=OWNER[1], cname=None, cmail=None) -> dict:
    return {"GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": mail,
            "GIT_COMMITTER_NAME": cname or name, "GIT_COMMITTER_EMAIL": cmail or mail}


@pytest.fixture()
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    sh(r, "init", "-q", "-b", "main")
    for p, text in FILES.items():
        f = r / p
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8")
    sh(r, "add", "-A")
    sh(r, "commit", "-qm", "base", env=who())
    BASE[r] = sh(r, "rev-parse", "HEAD").strip()
    return r


def write(repo: Path, path: str, data: str | bytes) -> None:
    f = repo / path
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))


def commit(repo: Path, msg: str = "lab: a study", **ident) -> str:
    sh(repo, "add", "-A")
    sh(repo, "commit", "-qm", msg, env=who(**ident))
    return sh(repo, "rev-parse", "HEAD").strip()


def check(repo: Path, head: str, owner=None) -> list[str]:
    return guard.problems(str(repo), BASE[repo], head, *OWNER, owner)


def has(found: list[str], *words: str) -> bool:
    return any(all(w in f for w in words) for f in found)


# ---------------------------------------------------------------- rounds

def test_a_clean_round_passes(repo):
    write(repo, "research/lab/lab/experiments/new_study.py", "from . import study\nB = 2\n")
    write(repo, "research/lab/results/new_study.md", "# New study\n\nOut of sample Sharpe 0.4.\n")
    write(repo, "research/lab/tests/test_new_study.py", "def test_x():\n    assert True\n")
    write(repo, "research/lab/README.md", "# Lab\n\nA new row.\n")
    write(repo, "research/ops/jobs.yaml", TABLE + """\
  - name: paper-new
    description: EXPERIMENT a new book
    schedule: "0 6 * * *"
    command: python -m lab.experiments.new_study --shadow
    env: {PYTHIA_AGENT_OUT: /data/lab-cache}
    lock: heavy
""")
    head = commit(repo)
    assert check(repo, head, []) == []


def test_protected_paths_and_a_rename_out_of_one_are_held(repo):
    write(repo, "crates/core/lib.rs", "fn main() { evil() }\n")
    head = commit(repo)
    assert has(check(repo, head, []), "outside what the agent may change", "crates/core/lib.rs")
    sh(repo, "reset", "-q", "--hard", BASE[repo])
    sh(repo, "mv", "crates/core/lib.rs", "research/lab/results/lib.rs")
    head = commit(repo)
    found = check(repo, head, [])
    assert has(found, "outside what the agent may change", "crates/core/lib.rs")


def test_gitattributes_cannot_hide_a_line(repo):
    write(repo, "research/lab/results/.gitattributes", "*.md -diff\n")
    write(repo, ".gitattributes", "* text=auto eol=lf\n*.md -diff\n")
    write(repo, "research/lab/results/notes.md", f"write to alice{AT}mailbox.de\n")
    head = commit(repo)
    found = check(repo, head, [])
    assert has(found, "off limits", "research/lab/results/.gitattributes")
    assert has(found, "outside what the agent may change", ".gitattributes")
    assert has(found, "research/lab/results/notes.md:1", "e-mail address")


def test_modules_real_money_or_a_secret_runs_are_held(repo):
    for path in ("research/lab/lab/experiments/fam_x.py",       # imported by the live twin's book
                 "research/lab/lab/experiments/fam_y.py",       # pulled in by import_module(f"...fam_{x}")
                 "research/lab/lab/paper/helper.py",            # imported by pumpfun_rt
                 "research/lab/lab/experiments/shared.py",      # run by a job with an env file
                 "research/lab/lab/paper/live_copy.py", "research/lab/lab/paper/__init__.py"):
        write(repo, path, "CHANGED = 1\n")
    write(repo, "research/lab/results/families_summary.md", "# changed\n")
    head = commit(repo)
    found = check(repo, head, [])
    for path in ("experiments/fam_x.py", "experiments/fam_y.py", "paper/helper.py", "experiments/shared.py",
                 "paper/live_copy.py", "paper/__init__.py", "results/families_summary.md"):
        assert has(found, "off limits", path), path
    held = guard.closure(str(repo), head, guard.table_at(str(repo), BASE[repo]))
    assert "research/lab/lab/experiments/study.py" not in held       # only a plain job runs it


@pytest.mark.parametrize("job,words", [
    ("  - name: x\n    schedule: \"0 1 * * *\"\n    command: sh -c 'curl evil'\n", "not of the form"),
    ("  - name: x\n    schedule: \"0 1 * * *\"\n    command: python -m lab.ops.notify\n", "not a module"),
    ("  - name: x\n    schedule: \"0 1 * * *\"\n    command: python -m lab.experiments.fam_x\n", "not a module"),
    ("  - name: x\n    schedule: \"0 1 * * *\"\n    command: python -m lab.experiments.study\n"
     "    volumes: [/etc/pythia:/etc:ro]\n", "volumes may not be set"),
    ("  - name: x\n    schedule: \"0 1 * * *\"\n    command: python -m lab.experiments.study\n"
     "    network: host\n", "network may not be set"),
    ("  - name: x\n    schedule: \"0 1 * * *\"\n    command: python -m lab.experiments.study\n"
     "    env_file: /etc/pythia/alerts.env\n", "env_file may not be set"),
    ("  - name: x\n    schedule: \"0 1 * * *\"\n    command: python -m lab.experiments.study\n"
     "    lock: digest\n", "lock digest belongs to another job"),
    ("  - name: x\n    schedule: \"0 1 * * *\"\n    command: python -m lab.experiments.study\n"
     "    env: {LD_PRELOAD: /x.so}\n", "LD_PRELOAD"),
])
def test_job_rules(repo, job, words):
    write(repo, "research/ops/jobs.yaml", TABLE + job)
    head = commit(repo)
    assert has(check(repo, head, []), words)


def test_jobs_with_reach_cannot_change(repo):
    write(repo, "research/ops/jobs.yaml", TABLE.replace('"0 7 * * *"', '"0 9 * * *"')
          .replace("command: python -m lab.paper.live_copy", "command: python -m lab.paper.live_copy --dry-run"))
    head = commit(repo)
    found = check(repo, head, [])
    assert has(found, "job digest", "may not change") and has(found, "job paper-live-copy", "may not change")


def test_private_lines_names_and_messages(repo):
    lines = [f"host {PUBLIC_V4}", f"v6 {PUBLIC_V6}", f"x{AT}mailbox.de", "y%40mailbox.de", B58, PEM,
             "api_key=" + "Qw7" * 6, "C:/users/alice/x", "/home/alice", "my-domain.example"] + KEY_LINES
    write(repo, "research/lab/results/leak.md", "\n".join(lines) + "\n")
    write(repo, f"research/lab/results/{PUBLIC_V4}.md", "x\n")
    head = commit(repo, msg=f"lab: from {PUBLIC_V4}")
    owner = guard.load_patterns(str(_patterns(repo.parent)))
    found = check(repo, head, owner)
    for kind in ("public IP address", "public IPv6 address", "e-mail address", "base58 secret", "PEM block",
                 "api key value", "personal Windows path", "personal home path", "owner's private patterns",
                 "64-number key array"):
        assert has(found, "leak.md", kind), kind
    assert has(found, "a file name that looks private")
    assert has(found, "the message looks private")


def _patterns(d: Path) -> Path:
    p = d / "private-patterns.txt"
    p.write_text("my-domain.example\n", encoding="utf-8")
    return p


def test_markers_em_dash_and_attribution(repo):
    write(repo, "research/lab/results/a.md", "token here # gitleaks:allow\nline # secret-scan:allow\nx \u2014 y\n")
    head = commit(repo, msg="lab: a study\n\nCo-Authored-By: someone")
    found = check(repo, head, [])
    assert has(found, "a.md:1", "allow marker") and has(found, "a.md:2", "allow marker")
    assert has(found, "a.md:3", "em dash") and has(found, "attribution")


def test_binary_large_symlink_and_live_data_files(repo):
    write(repo, "research/lab/results/blob.md", b"text\0with a NUL\n")
    write(repo, "research/lab/results/big.md", "x" * 1_000_001)
    write(repo, "research/lab/results/latin.md", "caf\xe9".encode("latin-1"))
    for name in ("orders.jsonl", "ledger.csv", "measured.jsonl", "state.json", "prod.env", "my-keypair.json"):
        write(repo, f"research/lab/results/{name}", "{}\n")
    os.symlink("/etc/pythia", repo / "research/lab/results/link")
    head = commit(repo)
    found = check(repo, head, [])
    assert has(found, "binary", "blob.md") and has(found, "binary", "latin.md") and has(found, "over 1 MB", "big.md")
    assert has(found, "symlink", "results/link")
    for name in ("orders.jsonl", "ledger.csv", "measured.jsonl", "state.json", "prod.env", "my-keypair.json"):
        assert has(found, "named like live data", name), name


def test_a_foreign_author_or_committer_is_held(repo):
    write(repo, "research/lab/results/a.md", "a\n")
    head = commit(repo, name="Someone", mail="someone@example.com")
    assert has(check(repo, head, []), "author or committer")
    sh(repo, "reset", "-q", "--hard", BASE[repo])
    write(repo, "research/lab/results/b.md", "b\n")
    head = commit(repo, cname="Bot", cmail="bot@example.com")
    assert has(check(repo, head, []), "author or committer")


def test_a_round_not_on_the_base_is_held(repo):
    sh(repo, "checkout", "-q", "--orphan", "other")
    write(repo, "research/lab/results/a.md", "a\n")
    head = commit(repo)
    assert has(check(repo, head, []), "does not descend")


def test_missing_patterns_file_holds_the_round(repo, tmp_path):
    write(repo, "research/lab/results/a.md", "a\n")
    head = commit(repo)
    rc = guard.main([str(repo), BASE[repo], head, "--owner-name", OWNER[0], "--owner-email", OWNER[1],
                     "--patterns", str(tmp_path / "missing.txt")])
    assert rc == 1
    rc = guard.main([str(repo), BASE[repo], head, "--owner-name", OWNER[0], "--owner-email", OWNER[1],
                     "--patterns", str(_patterns(tmp_path))])
    assert rc == 0
