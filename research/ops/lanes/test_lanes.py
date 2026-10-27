"""Tests of the task lanes (lanes.py): the template, the queue check, the never list, the drop and
prune, the in-container check, the retry, the budget gate, the records and the replay of the
rejections of 2026-10-26 and 27.

    python -m pytest -q research/ops/lanes/test_lanes.py

Needs git and a POSIX system (guard.py loads the job runner, which uses fcntl).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("fcntl")
HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent.parent
sys.path.insert(0, str(HERE))
import lanes  # noqa: E402

OWNER = ("SenseiIssei", "owner@example.com")
EM = chr(0x2014)
LAB = "research/lab/"


def task_text(allowed=("research/lab/lab/experiments/x1*.py", "research/lab/tests/test_x1*.py"), files_line="",
              model="claude-opus-5-5", usd="8", tests=("cd research/lab && python -m pytest -q tests/test_x1.py",),
              docs=("research/lab/README.md",), extra="") -> str:
    head = ["---", "id: 200-x1", "title: Studie (X1)", f"model: {model}", f"max_usd: {usd}", "allowed:"]
    head += [f"  - {g}" for g in allowed] + ["docs:"] + [f"  - {d}" for d in docs] + ["tests:"]
    head += [f"  - {t}" for t in tests] + ([extra] if extra else []) + ["---"]
    return "\n".join(head) + "\n# X1\n\nThe brief.\n\n" + (f"Files: {files_line}\n" if files_line else "")


def task(**k) -> lanes.Task:
    return lanes.parse_task(task_text(**k))


def repo_files() -> set[str]:
    out = subprocess.run(["git", "-C", str(REPO), "ls-files"], capture_output=True, text=True)
    return set(out.stdout.split()) if out.returncode == 0 else set()


# ---------------------------------------------------------------- globs and the never list

@pytest.mark.parametrize("glob,path,hit", [
    ("research/lab/lab/experiments/x1*.py", "research/lab/lab/experiments/x1_more.py", True),
    ("research/lab/lab/experiments/x1*.py", "research/lab/lab/experiments/sub/x1.py", False),
    ("research/lab/tests/**", "research/lab/tests/fixtures/a/b.json", True),
    ("research/lab/tests/**/*.py", "research/lab/tests/test_a.py", True),
    ("research/lab/lab/factory/{evaluate,run}.py", "research/lab/lab/factory/run.py", True),
    ("research/lab/lab/factory/{evaluate,run}.py", "research/lab/lab/factory/small.py", False),
    ("README.md", "research/lab/README.md", False),
])
def test_globs(glob, path, hit):
    assert bool(lanes.glob_re(glob).match(path)) is hit


@pytest.mark.parametrize("path", [
    "research/lab/lab/pumpfun_rt/live.py", "research/lab/lab/pumpfun_rt/live_exec.py",
    "research/lab/lab/pumpfun_rt/txbuild.py", "research/lab/lab/pumpfun_rt/wallet.py",
    "research/lab/lab/onchain/live_gate.py", "research/lab/lab/onchain/live_exec.py", "research/lab/lab/onchain/wallet.py",
    "research/lab/lab/paper/live_copy.py", "research/lab/tests/test_pumpfun_wallet_limits.py",
    "research/lab/tests/test_onchain_wallet_limits.py", "research/lab/tests/test_pumpfun_live.py",
    "crates/pythia-core/src/pumpfun_live.rs", "crates/pythia-core/src/onchain_live_tests.rs",
    "crates/pythia-core/src/connectors/sign.rs", "research/ops/deploy_live.sh", "SAFETY.md",
    "research/ops/lanes/lanes.py", "research/ops/lanes/new_rule.py", "research/ops/agent/guard.py", ".gitleaks.toml",
    ".github/workflows/ci.yml", "scripts/hooks/pre-commit",
])
def test_the_never_list_holds_real_money_and_the_rules(path):
    assert lanes.never(path)


@pytest.mark.parametrize("path", [
    "research/lab/lab/pumpfun_rt/factory.py", "research/lab/lab/pumpfun_rt/shapes17.py", "research/lab/lab/ops/briefing.py",
    "research/lab/tests/test_lablive.py", "research/lab/lab/onchain/longterm.py", "research/ops/README.md",
    "research/ops/agent/mini_agent.py", "research/ops/jobs.yaml",
])
def test_research_paths_are_not_on_it(path):
    assert not lanes.never(path)


def test_every_never_entry_names_something_and_the_live_files_exist():
    for g in lanes.NEVER:
        assert lanes.never(lanes.sample(g)), g
    for p in ("research/lab/lab/pumpfun_rt/live_exec.py", "research/lab/lab/onchain/live_gate.py",
              "research/lab/lab/pumpfun_rt/txbuild.py", "crates/pythia-core/src/pumpfun_live.rs",
              "research/ops/deploy_live.sh", "research/ops/lanes/lanes.py"):
        assert (REPO / p).is_file() and lanes.never(p), p


def test_no_task_list_can_open_the_never_list():
    t = task(allowed=("research/**", "research/lab/lab/pumpfun_rt/live_exec.py", "SAFETY.md"))
    assert not t.allows("research/lab/lab/pumpfun_rt/live_exec.py")
    assert not t.allows("research/ops/lanes/lanes.py") and not t.allows("SAFETY.md")
    assert t.allows("research/lab/lab/pumpfun_rt/factory.py")
    q = lanes.queue_problems(t, repo_files() or None)
    assert any("live_exec.py" in x and "never list" in x for x in q)
    assert any("SAFETY.md" in x and "never list" in x for x in q)
    # even a task that skipped the queue: the host drops them
    v = lanes.judge(t, [lanes.Change("research/lab/lab/pumpfun_rt/live_exec.py", added=[(1, "LIMIT = 9")]),
                        lanes.Change("research/ops/lanes/lanes.py"), lanes.Change("SAFETY.md"),
                        lanes.Change("research/lab/lab/pumpfun_rt/factory.py")], [lanes.Commit("c1", "lab: x")])
    assert set(v.dropped) == {"research/lab/lab/pumpfun_rt/live_exec.py", "research/ops/lanes/lanes.py", "SAFETY.md"}
    assert all("never list" in w for w in v.dropped.values())
    assert v.kept == ["research/lab/lab/pumpfun_rt/factory.py"] and not v.fatal


def test_a_retry_cannot_open_it_either():
    new = lanes.retry_text(task_text(allowed=("research/lab/lab/onchain/**",)), "an em dash")
    t = lanes.parse_task(new)
    assert t.allowed == ["research/lab/lab/onchain/**"] and not t.allows("research/lab/lab/onchain/live_gate.py")
    assert t.allows("research/lab/lab/onchain/longterm.py")


def test_a_broad_list_is_fine_but_the_never_list_still_wins():
    t = task(allowed=("research/lab/tests/**",), files_line="tests.")
    assert lanes.queue_problems(t) == []
    assert t.allows("research/lab/tests/test_x.py") and not t.allows("research/lab/tests/test_pumpfun_live.py")


# ---------------------------------------------------------------- the task file and the queue

def test_the_template_is_a_valid_task():
    t = lanes.parse_task((HERE / "task_template.md").read_text(encoding="utf-8"))
    assert lanes.queue_problems(t, repo_files() or None) == []
    assert t.model in lanes.MODELS and t.max_usd and t.allowed and t.tests and t.docs


def test_parse():
    t = task(extra="retry: no")
    assert (t.id, t.title, t.model, t.max_usd) == ("200-x1", "Studie (X1)", "claude-opus-5-5", 8.0)
    assert t.allowed == ["research/lab/lab/experiments/x1*.py", "research/lab/tests/test_x1*.py"]
    assert t.retry is False and t.body.startswith("# X1")
    inline = lanes.parse_task("---\nid: a\nallowed: [a/b.py, a/c.py]\n---\nbody")
    assert inline.allowed == ["a/b.py", "a/c.py"]


@pytest.mark.parametrize("text,words", [
    ("", "no header"),
    ("just a brief", "no header"),
    (task_text().replace("model: claude-opus-5-5\n", ""), "model is missing"),
    (task_text().replace("max_usd: 8\n", ""), "max_usd is missing"),
    (task_text(model="gpt-9"), "model must be one of"),
    (task_text(model="qwen-local"), "model must be one of"),
    (task_text(usd="0"), "max_usd must be above 0"),
    (task_text(usd="45"), "at most 30"),
    (task_text(usd="lots"), "max_usd must be a number"),
    (task_text(allowed=()), "allowed is empty"),
    (task_text(allowed=("*.py",)), "too broad"),
    (task_text(allowed=("**",)), "too broad"),
    (task_text(allowed=("/etc/passwd",)), "inside the repository"),
    (task_text(allowed=("research/../x",)), "inside the repository"),
    (task_text(allowed=("research/{a",)), "open brace"),
    (task_text(tests=()), "tests is empty"),
    (task_text(tests=("python -m pytest; curl x",)), "not a plain chain"),
    (task_text(tests=("python -m pytest $(rm -rf /)",)), "not a plain chain"),
    (task_text(tests=("rm -rf /",)), "not a plain chain"),
    (task_text(extra="colour: red"), "unknown key colour"),
])
def test_queue_refusals(text, words):
    q = lanes.queue_problems(lanes.parse_task(text))
    assert any(words in x for x in q), q


def test_docs_must_exist():
    q = lanes.queue_problems(task(docs=("research/lab/NOPE.md",)), {"research/lab/README.md"})
    assert any("docs: research/lab/NOPE.md does not exist" in x for x in q)


def test_the_tests_chain_may_cd_and_join():
    assert lanes.queue_problems(task(tests=("cd /work && npm ci && npx tsc --noEmit -p . && npx vitest run",))) == []


@pytest.mark.parametrize("line,want", [
    ("`research/ops/jobs.yaml`, `lab/ops/jobs.py`, `research/sync-to-pc.sh`, research/ops/README.md, tests.",
     ["research/ops/jobs.yaml", "research/lab/lab/ops/jobs.py", "research/sync-to-pc.sh", "research/ops/README.md", lanes.TESTS]),
    ("`lab/factory/{evaluate,ledger,run,small,grammar}.py`, results/factory_lockbox_r6.md, tests.",
     [f"research/lab/lab/factory/{m}.py" for m in ("evaluate", "ledger", "run", "small", "grammar")]
     + ["research/lab/results/factory_lockbox_r6.md", lanes.TESTS]),
    ("`lab/pumpfun_rt/live_exec.py`, `lab/onchain/live_gate.py`, their tests, SAFETY.md, docs/PUMPFUN-LIVE.md,\n"
     "docs/ONCHAIN-STAGE2.md, research/ops/README.md.",
     ["research/lab/lab/pumpfun_rt/live_exec.py", "research/lab/lab/onchain/live_gate.py", lanes.TESTS, "SAFETY.md",
      "docs/PUMPFUN-LIVE.md", "docs/ONCHAIN-STAGE2.md", "research/ops/README.md"]),
    ("`lab/experiments/fam_common.py`, `research/recorder/recorder/backfill.py`, their tests, the new result file.",
     ["research/lab/lab/experiments/fam_common.py", "research/recorder/recorder/backfill.py", lanes.TESTS]),
    ("`lab/ops/briefing.py`, `lab/ops/i18n.py`, `lab/ops/notify.py`, the app's alert settings page, tests.",
     ["research/lab/lab/ops/briefing.py", "research/lab/lab/ops/i18n.py", "research/lab/lab/ops/notify.py", lanes.TESTS]),
])
def test_the_files_line_of_the_review_briefs(line, want):
    assert lanes.brief_files(f"Goal: x\n\nJudged by: y.\nFiles: {line}\n\n### next") == want


def test_a_file_the_brief_asks_for_must_be_allowed():
    """R3 was rejected for exactly the files its brief asked for: now the queue says so, before any money."""
    line = "`research/ops/jobs.yaml`, `lab/ops/jobs.py`, `research/sync-to-pc.sh`, research/ops/README.md, tests."
    q = lanes.queue_problems(task(allowed=("research/ops/jobs.yaml", "research/lab/tests/test_jobs.py"), files_line=line))
    assert {x.split()[4].rstrip(",") for x in q if "allowed does not cover it" in x} == {
        "research/lab/lab/ops/jobs.py", "research/sync-to-pc.sh", "research/ops/README.md"}
    ok = task(allowed=("research/ops/jobs.yaml", "research/lab/lab/ops/jobs.py", "research/sync-to-pc.sh",
                       "research/ops/README.md", "research/lab/tests/test_jobs*.py"), files_line=line)
    assert lanes.queue_problems(ok) == []
    assert any("asks for tests" in x for x in lanes.queue_problems(task(allowed=("research/ops/jobs.yaml",),
                                                                        files_line="`research/ops/jobs.yaml`, tests.")))


def test_a_brief_that_asks_for_real_money_code_is_refused():
    q = lanes.queue_problems(task(allowed=("research/lab/tests/test_x1.py",), files_line="`lab/onchain/live_gate.py`, tests."))
    assert any("asks for research/lab/lab/onchain/live_gate.py, which is on the never list" in x for x in q)


# ---------------------------------------------------------------- the host's verdict on changes

def test_judge_drops_what_is_off_the_list_and_keeps_the_rest():
    t = task()
    v = lanes.judge(t, [lanes.Change(LAB + "lab/experiments/x1.py", "A", added=[(1, "A = 1")]),
                        lanes.Change("research/ops/README.md"), lanes.Change(".gitattributes")],
                    [lanes.Commit("c1", "lab: x1", OWNER, OWNER)], OWNER)
    assert not v.fatal and v.kept == [LAB + "lab/experiments/x1.py"]
    assert v.dropped == {"research/ops/README.md": "outside the task's allowed list",
                         ".gitattributes": "a git, scanner or interpreter control file"}


@pytest.mark.parametrize("change,words", [
    (lanes.Change(LAB + "lab/experiments/x1.py", added=[(3, f"# a {EM} b")]), "x1.py:3: an em dash"),
    (lanes.Change(LAB + "lab/experiments/x1.py", data=b"PAR1\0\0"), "a binary file"),
    (lanes.Change(LAB + "lab/experiments/x1.py", data=b"x" * 1_000_001), "over 1 MB"),
    (lanes.Change(LAB + "lab/experiments/x1.py", mode="120000"), "a symlink"),
    (lanes.Change(LAB + "lab/experiments/x1.py", added=[(1, "HOST = " + ".".join(["93", "184", "216", "34"]))]),
     "public IP address"),
    (lanes.Change(LAB + "lab/experiments/x1.py", added=[(1, "# gitleaks" + ":allow")]), "allow marker"),
    (lanes.Change(LAB + "lab/experiments/x1_ledger.py", new_imports=["lab.pumpfun_rt.txbuild"]),
     "now imports lab.pumpfun_rt.txbuild"),
])
def test_judge_holds_the_run(change, words):
    v = lanes.judge(task(), [change], [lanes.Commit("c1", "lab: x1")])
    assert any(words in x for x in v.fatal), v.fatal


@pytest.mark.parametrize("commit,words", [
    (lanes.Commit("c1", f"lab: x1 {EM} done"), "em dash in the message"),
    (lanes.Commit("c1", "lab: x1\n\nCo-Authored-By: someone"), "attribution"),
    (lanes.Commit("c1", "lab: x1", ("Someone", "x@example.com"), OWNER), "not the owner's identity"),
])
def test_judge_holds_for_the_commits(commit, words):
    if commit.author == ("", ""):
        commit.author = commit.committer = OWNER
    v = lanes.judge(task(), [lanes.Change(LAB + "lab/experiments/x1.py")], [commit], OWNER)
    assert any(words in x for x in v.fatal), v.fatal


def test_nothing_committed_and_nothing_left():
    assert lanes.judge(task(), [], []).fatal == ["nothing committed"]
    v = lanes.judge(task(), [lanes.Change("research/ops/README.md")], [lanes.Commit("c1", "x")])
    assert "nothing left once the files outside the list are dropped" in v.fatal


def test_a_long_subject_is_a_warning_only():
    v = lanes.judge(task(), [lanes.Change(LAB + "lab/experiments/x1.py")], [lanes.Commit("c1", "lab: " + "x" * 600)])
    assert not v.fatal and "subject has 605 characters" in v.warnings[0]


def test_missing_patterns_hold_on_the_host():
    v = lanes.judge(task(), [lanes.Change(LAB + "lab/experiments/x1.py")], [lanes.Commit("c1", "x")], need_patterns=True)
    assert any("private patterns file is missing" in x for x in v.fatal)


# ---------------------------------------------------------------- in a git repository

def sh(repo: Path, *args: str, env: dict | None = None) -> str:
    e = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
         "GIT_AUTHOR_NAME": OWNER[0], "GIT_AUTHOR_EMAIL": OWNER[1],
         "GIT_COMMITTER_NAME": OWNER[0], "GIT_COMMITTER_EMAIL": OWNER[1], **(env or {})}
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True, env=e).stdout


def write(repo: Path, path: str, text: str) -> None:
    f = repo / path
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text, encoding="utf-8")


TABLE = """\
paths:
  data: /srv/pythia-data
defaults:
  kind: lab
  image: pythia-lab
jobs:
  - name: book
    schedule: "0 5 * * *"
    command: python -m lab.paper.book
"""


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    r = tmp_path / "repo"
    r.mkdir()
    sh(r, "init", "-q", "-b", "main")
    sh(r, "config", "user.name", OWNER[0])
    sh(r, "config", "user.email", OWNER[1])
    for p, text in {"research/lab/lab/__init__.py": "", "research/lab/lab/paper/__init__.py": "",
                    "research/lab/lab/paper/book.py": "X = 1\n", "research/lab/lab/experiments/__init__.py": "",
                    "research/lab/lab/pumpfun_rt/__init__.py": "", "research/lab/lab/pumpfun_rt/txbuild.py": "def sign(): pass\n",
                    "research/lab/lab/pumpfun_rt/study.py": "A = 1\n", "research/ops/README.md": "# Ops\n",
                    "research/ops/jobs.yaml": TABLE, "research/lab/README.md": "# Lab\n"}.items():
        write(r, p, text)
    sh(r, "add", "-A")
    sh(r, "commit", "-qm", "base")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    return r, sh(r, "rev-parse", "HEAD").strip()


def commit(r: Path, msg: str) -> str:
    sh(r, "add", "-A")
    sh(r, "commit", "-qm", msg)
    return sh(r, "rev-parse", "HEAD").strip()


def test_verdict_and_prune_keep_only_the_list(repo):
    r, base = repo
    t = task(allowed=("research/lab/lab/experiments/x1*.py", "research/lab/tests/test_x1*.py"))
    write(r, "research/lab/lab/experiments/x1.py", "B = 2\n")
    write(r, "research/ops/README.md", "# Ops\n\nA row the task did not ask for.\n")
    commit(r, "lab: x1 and a doc")
    write(r, "research/lab/lab/pumpfun_rt/txbuild.py", "def sign(): return 'more'\n")
    commit(r, "lab: touch the signer")
    write(r, "research/lab/tests/test_x1.py", "def test_x():\n    assert True\n")
    head = commit(r, "lab: x1 tests")
    v = lanes.verdict_for(str(r), base, head, t, OWNER, None)
    assert not v.fatal and set(v.dropped) == {"research/ops/README.md", "research/lab/lab/pumpfun_rt/txbuild.py"}
    new = lanes.prune(str(r), base, head, v.kept)
    assert sh(r, "diff", "--name-only", base, new).split() == ["research/lab/lab/experiments/x1.py",
                                                                "research/lab/tests/test_x1.py"]
    assert sh(r, "log", "--format=%s", f"{base}..{new}").split("\n")[:2] == ["lab: x1 tests", "lab: x1 and a doc"]
    again = lanes.verdict_for(str(r), base, new, t, OWNER, None)
    assert not again.fatal and not again.dropped
    assert (r / "research/ops/README.md").read_text() == "# Ops\n"


def test_a_new_import_of_real_money_code_holds(repo):
    r, base = repo
    write(r, "research/lab/lab/experiments/x1.py", "from ..pumpfun_rt import txbuild\n")
    head = commit(r, "lab: x1")
    v = lanes.verdict_for(str(r), base, head, task(), OWNER, None)
    assert any("now imports lab.pumpfun_rt.txbuild" in x for x in v.fatal)


def test_the_job_table_keeps_the_guards_rules_with_the_tasks_list(repo):
    r, base = repo
    t = task(allowed=("research/lab/lab/experiments/x1*.py", "research/ops/jobs.yaml"))
    write(r, "research/lab/lab/experiments/x1.py", "B = 2\n")
    write(r, "research/ops/jobs.yaml", TABLE + "  - name: x1\n    schedule: \"0 6 * * *\"\n"
                                              "    command: python -m lab.experiments.x1\n")
    ok = commit(r, "lab: x1 job")
    assert not lanes.verdict_for(str(r), base, ok, t, OWNER, None).fatal
    write(r, "research/ops/jobs.yaml", TABLE + "  - name: x1\n    schedule: \"0 6 * * *\"\n"
                                              "    command: python -m lab.pumpfun_rt.txbuild\n")
    bad = commit(r, "lab: run the signer")
    assert any("not a module the agent may run" in x for x in lanes.verdict_for(str(r), base, bad, t, OWNER, None).fatal)


def test_check_in_the_container_sees_the_working_tree(repo, tmp_path, capsys):
    r, base = repo
    tf = tmp_path / "task.md"
    tf.write_text(task_text(tests=("python -c pass",)), encoding="utf-8")
    write(r, "research/lab/lab/experiments/x1.py", f"# one {EM} two\n")
    write(r, "research/ops/README.md", "# Ops\n\nmore\n")
    assert lanes.main(["check", "--task", str(tf), "--repo", str(r), "--base", base]) == 1
    out = capsys.readouterr().out
    assert "HOLD" in out and "x1.py:1: an em dash" in out
    assert "DROPPED" in out and "research/ops/README.md" in out and "not committed yet" in out
    assert sh(r, "status", "--porcelain").strip()             # the agent's index and tree untouched
    write(r, "research/lab/lab/experiments/x1.py", "# one, two\n")
    sh(r, "checkout", "--", "research/ops/README.md")
    commit(r, "lab: x1")
    assert lanes.main(["check", "--task", str(tf), "--repo", str(r), "--base", base, "--tests"]) == 0
    assert "ok: 1 file(s)" in capsys.readouterr().out
    assert lanes.main(["check", "--task", str(tf), "--repo", str(r)]) == 2


# ---------------------------------------------------------------- the retry, the budget, the records

def test_one_retry_a_step_cheaper_with_the_reasons():
    new = lanes.retry_text(task_text(), "research/lab/lab/experiments/x1.py:3: an em dash\ntests red: x")
    t = lanes.parse_task(new)
    assert (t.id, t.model, t.retry_of, t.retry, t.max_usd) == ("200-x1-retry", "claude-sonnet-5-5", "200-x1", False, 4.0)
    assert "- research/lab/lab/experiments/x1.py:3: an em dash" in t.body and "first run's commits" in t.body
    assert "The brief." in t.body and lanes.queue_problems(t) == []
    assert lanes.retry_text(new, "again") is None                         # one retry only
    assert lanes.parse_task(lanes.retry_text(task_text(model="claude-sonnet-5-5"), "x")).model == "claude-haiku-5-5"
    assert lanes.retry_text(task_text(model="claude-haiku-5-5"), "x") is None
    assert lanes.retry_text(task_text(extra="retry: no"), "x") is None
    assert lanes.retry_text(task_text(), "  ") is None
    assert lanes.parse_task(lanes.retry_text(task_text(usd="1.5"), "x")).max_usd == 1.0


def test_the_budget_gate_keeps_the_reserve():
    state = {"balance_usd": 40, "reserve_usd": 10, "since": "2026-10-28T00:00:00"}
    spent = [{"at": "2026-10-27T23:00:00", "usd": 99}, {"at": "2026-10-28T01:00:00", "usd": 12.5}]
    ok, left, _ = lanes.budget_gate(state, spent, 8)
    assert ok and left == 27.5                                            # 27.5 > 10 + 8
    assert not lanes.budget_gate(state, spent, 17.5)[0]                   # 27.5 is not above 27.5
    assert not lanes.budget_gate(state, spent + [{"at": "2026-10-28T02:00:00", "usd": 10}], 8)[0]
    assert not lanes.budget_gate({**state, "paused": True}, [], 1)[0]
    assert not lanes.budget_gate({}, [], 1)[0]


def test_the_budget_never_ends_below_the_reserve():
    """Every run is capped at its max_usd and starts only above reserve plus max_usd: the 2026-10-24..27 overshoot
    (78 USD past the reserve with runs up to 11.23) cannot happen."""
    state, spent = {"balance_usd": 60, "reserve_usd": 10, "since": ""}, []
    for usd in [11.23, 8.2, 6.43, 6.44, 6.06, 6.84, 4.73, 9.0, 12.0]:
        if lanes.budget_gate(state, spent, 12)[0]:
            spent.append({"at": "x", "usd": min(usd, 12)})
    assert lanes.budget_gate(state, spent, 0)[1] >= 10


def test_run_cost():
    assert lanes.run_cost('{"type": "result", "total_cost_usd": 3.2104}', 8) == 3.2104
    assert lanes.run_cost("noise\nnot json", 8) == 8.0


def test_the_records_feed_the_briefing_and_the_news(tmp_path):
    t = task()
    rec = lanes.lane_record(t, "done", commit="abc1234def5678", base="f" * 40, files=["a.py"],
                            dropped={"research/ops/README.md": "outside"}, usd=3.5, at=1_793_100_000)
    assert rec["name"] == "200-x1" and rec["commit"] == "abc1234def56" and rec["status"] == "done"
    rep = lanes.research_report([rec, lanes.lane_record(t, "stopped", reason="Zurückgehalten: x", at=1_793_000_000)],
                                [], 2, ["A2"], {"balance_usd": 20, "reserve_usd": 10, "since": ""},
                                [{"at": "a", "usd": 12}], now_ms=1)
    assert [d["ok"] for d in rep["done"]] == [True, False] and rep["done"][0]["at"] == 1_793_100_000_000
    assert "research/ops/README.md" in rep["done"][0]["why"] and rep["done"][0]["commit"] == "abc1234def56"
    assert rep["budget"] == {"balance_usd": 20.0, "left_usd": 8.0, "reserve_usd": 10.0, "since": "", "paused": True}
    assert (rep["queued"], rep["held"]) == (2, ["A2"])


def test_the_prompt_carries_the_list_the_check_and_the_never_list():
    p = lanes.prompt_text(task(), (HERE / "lane.md").read_text(encoding="utf-8"))
    assert "- research/lab/lab/experiments/x1*.py" in p and "lanes.py check --task /lane/task.md" in p
    assert "research/lab/lab/pumpfun_rt/live_exec.py" not in p or "live_*.py" in p
    assert "## The never list" in p and p.rstrip().endswith("The brief.")


def test_no_em_dash_in_the_lane_files():
    for f in HERE.iterdir():
        if f.is_file() and f.suffix in (".py", ".md", ".sh", ".json"):
            assert EM not in f.read_text(encoding="utf-8"), f.name


def test_the_runner_gates_caps_and_checks_before_it_pushes():
    sh_text = (HERE / "run_lane.sh").read_text(encoding="utf-8")
    assert subprocess.run(["bash", "-n", str(HERE / "run_lane.sh")]).returncode == 0
    i = sh_text.index
    assert i("L budget") < i("docker run --rm --name \"pythia-lane\"") < i("L verdict") < i("L prune") \
        < i("tests red") < i('"$gitleaks" git /repo') < i("tgit push")
    assert '--max-budget-usd "$max_usd"' in sh_text and "L queue-check" in sh_text and "L retry" in sh_text
    # the check the agent runs is main's copy, at the path lane.md names
    assert "tgit archive \"$base\" research/ops/lanes research/ops/agent/guard.py research/lab/lab/ops/jobs.py" in sh_text
    assert "/lane/research/ops/lanes/lanes.py" in (HERE / "lane.md").read_text(encoding="utf-8")


# ---------------------------------------------------------------- the replay of 2026-10-26 and 27

def replay() -> list[tuple[dict, dict]]:
    doc = json.loads((HERE / "replay_2026-10-27.json").read_text(encoding="utf-8"))
    return [(c, lanes.replay_case(c)) for c in doc["cases"]]


def test_the_replay_gives_each_case_its_outcome():
    for case, r in replay():
        assert r["outcome"] == case["expect"], (case["name"], r)


def test_the_replay_meets_the_goal():
    rows = replay()
    old = [(c, r) for c, r in rows if not c["after_review"]]
    assert len(old) == 12                                                  # the review's 12 rejections
    started = [(c, r) for c, r in rows if r["outcome"] != "refused at the queue"]
    accepted = [c for c, r in started if r["outcome"].startswith("accepted")]
    assert len(accepted) / len(started) >= 0.8                            # at least 4 of 5 paid runs
    # no started run is held or loses a file its brief asked for
    for case, r in started:
        asked = lanes.brief_files(lanes.parse_task(case["task"]).body)
        for p in r.get("dropped") or {}:
            assert not any(lanes.glob_re(w).match(p) for w in asked if w != lanes.TESTS), (case["name"], p)
    # the money the 12 lost to rejections, by what the rules do with it
    paid = {c["name"]: r["outcome"] for c, r in old if c["usd"]}
    assert sum(c["usd"] for c, _ in old if c["usd"]) == pytest.approx(49.93)
    assert sorted(n for n, o in paid.items() if o.startswith("accepted")) == [
        "108-small-factory", "113-social-paper", "115-model-factory", "117-data-free", "119-modern-models"]
    r1 = next(r for c, r in rows if c["name"] == "11760-r01-caps")
    assert r1["outcome"] == "refused at the queue" and any("never list" in x for x in r1["reasons"])
