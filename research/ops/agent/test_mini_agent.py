"""Tests of the small coding agent (mini_agent.py) against a fake model server.

    python -m pytest -q research/ops/agent/test_mini_agent.py

The fake server (http.server in a thread) plays a scripted session: read, replace, run
the tests, commit. Plus: a path escape refused, run() refusing other commands, the
summarising step and the JSON result on stdout. Needs git.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mini_agent as ma  # noqa: E402

DASH = chr(0x2014)


class Fake:
    """Answers POST /v1/messages with the scripted replies in order and records every request."""

    def __init__(self, replies):
        self.replies, self.requests, self.headers = list(replies), [], []
        fake = self

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["content-length"])))
                fake.requests.append(body)
                fake.headers.append(dict(self.headers))
                if self.path != "/v1/messages" or not fake.replies:
                    self.send_response(400)
                    self.end_headers()
                    return
                out = json.dumps(fake.replies.pop(0)).encode()
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

            def log_message(self, *a):
                pass

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self):
        self.srv.shutdown()


def tool(i, name, **inp):
    return {"type": "tool_use", "id": f"t{i}", "name": name, "input": inp}


def reply(*blocks, stop="tool_use"):
    return {"role": "assistant", "content": list(blocks), "stop_reason": stop,
            "usage": {"input_tokens": 10, "output_tokens": 5}}


def text(t):
    return {"type": "text", "text": t}


def git(root, *a):
    return subprocess.run(["git", *a], cwd=root, capture_output=True, text=True, check=True).stdout


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "work"
    lab = root / "research" / "lab"
    (lab / "lab").mkdir(parents=True)
    (lab / "tests").mkdir()
    (lab / "lab" / "__init__.py").write_text("")
    (lab / "lab" / "foo.py").write_text("def add(a, b):\n    return a - b\n")
    (lab / "tests" / "test_foo.py").write_text("from lab.foo import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n")
    git(root.parent, "init", "-q", str(root))
    git(root, "config", "user.name", "tester")
    git(root, "config", "user.email", "tester")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "base")
    return root


def test_session_read_replace_test_commit(repo, tmp_path, monkeypatch, capsys):
    fake = Fake([
        reply(text("Plan: fix add in lab/foo.py, run its test, commit."),
              tool(1, "read_file", path="research/lab/lab/foo.py")),
        reply(tool(2, "replace", path="research/lab/lab/foo.py", old="return a - b", new="return a + b")),
        reply(tool(3, "run", cmd="python -m pytest -q tests/test_foo.py")),
        reply(tool(4, "run", cmd="git add research/lab/lab/foo.py", cwd="."),
              tool(5, "run", cmd="git commit -q -m 'lab: add adds'", cwd=".")),
        reply(text("Fixed add, test passes, committed."), stop="end_turn"),
    ])
    task = tmp_path / "prompt.md"
    task.write_text("Fix add() in research/lab/lab/foo.py.")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", fake.base)
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "tok")
    monkeypatch.setenv("ANTHROPIC_MODEL", "qwen-test")
    monkeypatch.setenv("MINI_AGENT_OUT", str(tmp_path / "out"))
    try:
        rc = ma.main(["--task", str(task), "--root", str(repo)])
    finally:
        fake.close()
    res = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert rc == 0
    assert res["is_error"] is False and res["terminal_reason"] == "completed" and res["subtype"] == "success"
    assert res["num_turns"] == 5 and res["result"] == "Fixed add, test passes, committed."
    assert res["files_changed"] == ["research/lab/lab/foo.py"]
    assert (repo / "research/lab/lab/foo.py").read_text() == "def add(a, b):\n    return a + b\n"
    assert git(repo, "log", "-1", "--format=%s %an").strip() == "lab: add adds tester"
    assert git(repo, "status", "--porcelain").strip() == ""
    # what the model saw: the request shape, the file's numbered lines, the test passing
    r0 = fake.requests[0]
    assert r0["model"] == "qwen-test" and r0["messages"][0]["content"].startswith("Fix add()")
    assert {t["name"] for t in r0["tools"]} == {"list_files", "read_file", "grep", "graph", "write_file", "replace", "run"}
    assert fake.headers[0].get("Authorization") == "Bearer tok"
    seen = json.dumps(fake.requests[1]["messages"][-1])
    assert "return a - b" in seen and "    2  " in seen
    last = fake.requests[3]["messages"][-1]["content"][0]
    assert last["tool_use_id"] == "t3" and "exit 0" in last["content"] and "1 passed" in last["content"]


def test_system_prompt_is_small():
    assert ma.est_tokens(ma.system_prompt(Path("/work"), None)) + ma.est_tokens(ma.TOOLS) < 1500
    assert DASH not in ma.system_prompt(Path("/work"), None)
    long = ma.system_prompt(Path("/work"), "x" * 20000)
    assert ma.est_tokens(long) < 1500 and "(rules cut here)" in long


def test_path_escape_refused(repo, tmp_path):
    (tmp_path / "secret.txt").write_text("no")
    (repo / "link").symlink_to(tmp_path / "secret.txt")
    t = ma.Tools(repo, out=tmp_path / "out")
    for p in ["../secret.txt", str(tmp_path / "secret.txt"), "/etc/passwd", "link", "research/../../secret.txt"]:
        out, err, summary = t.call("read_file", {"path": p})
        assert err and "outside" in out, p
    assert t.call("write_file", {"path": "../x.py", "content": "x"})[1]
    assert t.call("write_file", {"path": ".git/config", "content": "x"})[1]
    assert t.call("replace", {"path": "/etc/hosts", "old": "a", "new": "b"})[1]
    assert t.call("list_files", {"glob": "../*"})[1]
    assert t.call("run", {"cmd": "git status", "cwd": ".."})[1]
    # /out may take the report, and the write is refused with an em dash in it
    assert not t.call("write_file", {"path": str(tmp_path / "out" / "report.md"), "content": "ok"})[1]
    assert t.call("write_file", {"path": "a.md", "content": f"a {DASH} b"})[1]
    assert not (tmp_path / "x.py").exists()


def test_run_refuses_other_commands(repo):
    t = ma.Tools(repo)
    for cmd in ["rm -rf /", "bash -c 'echo hi'", "python -c 'print(1)'", "python script.py", "python -m os",
                "python -m lab.missing", "python -m lab.pumpfun_rt.live", "git push", "git reset --hard",
                "git -c core.pager=x status", "git diff --output=/tmp/x", "git diff --no-index /etc/passwd a",
                "git commit --amend -m x", "git commit --author=x -m x", "git commit --no-verify -m x",
                f"git commit -m 'fix {DASH} more'", "git commit -m 'Co-Authored-By: x'",
                "git commit -m 'written by Claude'", "flock /tmp/x python -m pytest", "curl http://x", ""]:
        out, err, _ = t.call("run", {"cmd": cmd})
        assert err and out.startswith("error:"), cmd
    assert t.call("run", {"cmd": "git status"})[1] is False
    assert t.call("run", {"cmd": "python -m lab.foo"})[0].startswith("exit 0")
    assert t.check_cmd("flock /run/lock/pythia/heavy.lock python -m pytest -q")[:2] == ["flock", "/run/lock/pythia/heavy.lock"]
    assert t.check_cmd("git commit -m 'lab: ai summary'")


def test_replace_exact_and_unique(repo):
    t = ma.Tools(repo)
    (repo / "d.py").write_text("x = 1\nx = 1\n")
    assert "2 times" in t.call("replace", {"path": "d.py", "old": "x = 1", "new": "x = 2"})[0]
    assert "0 times" in t.call("replace", {"path": "d.py", "old": "y", "new": "z"})[0]
    assert not t.call("replace", {"path": "d.py", "old": "x = 1\nx", "new": "x = 2\nx"})[1]
    assert (repo / "d.py").read_text() == "x = 2\nx = 1\n"


def test_read_grep_list_caps(repo):
    t = ma.Tools(repo)
    (repo / "big.txt").write_text("".join(f"hit {i}\n" for i in range(1000)))
    out = t.read_file("big.txt", 10, 5000)
    assert out.count("\n") == ma.READ_CAP and "(lines 10 to 409 of 1000)" in out
    g = t.grep(r"hit \d+", "*.txt")
    assert g.count("big.txt:") == ma.GREP_CAP and "cut at" in g
    assert "research/lab/lab/foo.py" in t.list_files("**/*.py")
    assert t.list_files("*.nothing") == "no files match"
    assert "no code graph" in t.call("graph", {"query": "add()"})[0]


def test_summarising_step(repo):
    t = ma.Tools(repo)
    system = ma.system_prompt(repo, None)
    msgs = [{"role": "user", "content": "the task"}]
    summaries = {}
    big = "line\n" * 2000
    for i in range(6):
        msgs.append({"role": "assistant", "content": [text(f"Plan step {i}") if i == 0 else text("next"),
                                                      tool(i, "read_file", path=f"f{i}.py")]})
        msgs.append({"role": "user", "content": [{"type": "tool_result", "tool_use_id": f"t{i}", "content": big}]})
        summaries[f"t{i}"] = f"read_file(path=f{i}.py) -> 4000 lines"
    summaries["_last_test_id"] = "t1"
    t.last_test, t.changed = "$ python -m pytest\nexit 0\n3 passed", ["research/lab/lab/foo.py"]
    before = ma.history_tokens(system, msgs)
    assert not ma.compact(msgs, summaries, t, system, before + 1)
    assert ma.compact(msgs, summaries, t, system, 12000)
    assert ma.history_tokens(system, msgs) <= 12000
    results = [m["content"][0] for m in msgs if m["role"] == "user" and isinstance(m["content"], list)]
    assert results[0]["content"] == "[summary] read_file(path=f0.py) -> 4000 lines"
    assert results[1]["content"] == big                       # the last test output stays whole
    assert results[-1]["content"] == big and results[-2]["content"] == big   # the recent turns too
    assert len(msgs) == 13 and msgs[1]["content"][0]["text"] == "Plan step 0"
    # still too big: the oldest turns go, the note keeps the plan, the files and the last test
    assert ma.compact(msgs, summaries, t, system, 6000)
    first = msgs[0]["content"]
    assert first.startswith("the task") and "Plan step 0" in first and "research/lab/lab/foo.py" in first \
        and "3 passed" in first
    assert msgs[1]["role"] == "assistant" and len(msgs) < 13
    ids = {b["id"] for m in msgs if m["role"] == "assistant" for b in m["content"] if b["type"] == "tool_use"}
    assert all(b["tool_use_id"] in ids for m in msgs[1:] if m["role"] == "user" for b in m["content"])


def test_session_shortens_history_and_stops_at_max_turns(repo, tmp_path):
    (repo / "big.py").write_text("x = 1\n" * 390)
    fake = Fake([reply(text("Plan: read big.py") if i == 0 else text("again"),
                       tool(i, "read_file", path="big.py", lines=400)) for i in range(8)])
    try:
        res = ma.run_session("task", repo, base=fake.base, token="t", model="m", ctx=5000, max_turns=6,
                             out=tmp_path / "out")
    finally:
        fake.close()
    assert res["is_error"] and res["terminal_reason"] == "max_turns" and res["num_turns"] == 6
    assert res["subtype"] == "error_max_turns"
    last = fake.requests[-1]["messages"]
    assert any("[summary] read_file(path=big.py" in json.dumps(m) for m in last)
    assert all(ma.history_tokens("", r["messages"]) < 5000 + 3000 for r in fake.requests)


def test_api_error_is_reported(repo, tmp_path, monkeypatch):
    fake = Fake([])                                       # answers 400
    try:
        res = ma.run_session("task", repo, base=fake.base, token="t", model="m")
    finally:
        fake.close()
    assert res["is_error"] and res["terminal_reason"] == "api_error" and "HTTP 400" in res["result"]


def test_run_hides_the_model_token(repo, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "secret-value")
    assert "ANTHROPIC_AUTH_TOKEN" not in ma._clean_env()
