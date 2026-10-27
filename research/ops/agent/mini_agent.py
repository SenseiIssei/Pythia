"""Pythia's own small coding agent for the local model (lane 5), so nothing depends on Claude Code.

    python /work/research/ops/agent/mini_agent.py --task /path/prompt.md [--rules common.md] [--root /work]

Talks to an Anthropic Messages endpoint (POST {ANTHROPIC_BASE_URL}/v1/messages, Bearer
ANTHROPIC_AUTH_TOKEN, model ANTHROPIC_MODEL), non-streaming, with tool use in Anthropic's
format. Standard library only. The Claude Code CLI spends about 12,500 tokens on its own
system prompt and tools; this one spends under 1,500, so a 48k local model keeps room.

Tools: list_files, read_file, grep, graph (graphify explain/affected), write_file, replace,
run (python -m pytest, python -m <module under research/lab>, git status/diff/add/commit;
no shell, a timeout, an output cap). Every path stays inside the root (/work); /out
(MINI_AGENT_OUT) may be written too for the report, MINI_AGENT_READ_ROOTS (colon list) read.

Context: a token estimate of the history; past MINI_AGENT_CTX (default 30000) old tool
results become one-line summaries (the latest test output stays whole); if that is not
enough, the oldest turns go and a note with the plan, the files changed and the last test
output takes their place. Limits: MINI_AGENT_MAX_TURNS (150), MINI_AGENT_WALL_S (10800),
MINI_AGENT_MAX_TOKENS (8192 a reply), MINI_AGENT_HTTP_TIMEOUT (900 s), MINI_AGENT_RUN_TIMEOUT
(900 s a command). Prints one JSON line shaped like `claude -p --output-format json`
(type, subtype, result, num_turns, is_error, terminal_reason, duration_ms, usage) to
stdout; the log of every turn goes to stderr. Exit 0 when the model ended its turn.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import shlex
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

EM_DASH = "\u2014"
SKIP_DIRS = {".git", "node_modules", "graphify-out", "__pycache__", ".pytest_cache", "target", "dist"}
READ_CAP = 400            # lines a read_file returns at most
LINE_CAP = 400            # characters a line keeps
GREP_CAP = 80             # matches a grep returns at most
LIST_CAP = 300            # paths a list_files returns at most
OUT_CAP = 8000            # characters of a command's output (head and tail)
RULES_CAP = 2400          # characters of the house rules in the system prompt
KEEP_RECENT = 4           # messages at the end whose tool results are never summarised


def env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


def est_tokens(obj) -> int:
    """About 3.5 characters a token for code and JSON; rough, on the safe side."""
    return int(len(obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False)) / 3.5) + 1


def log(msg: str) -> None:
    print(f"{time.strftime('%H:%M:%S')} mini_agent: {msg}", file=sys.stderr, flush=True)


# ---------------------------------------------------------------- the prompt

DEFAULT_RULES = """- Commit on main with the identity git is set up with: never change git config, never --author, --amend or --no-verify.
- Never use the em dash character anywhere. Commit messages carry no Co-Authored-By line and never mention Claude or AI.
- Change only the files the task allows; anything else throws the whole run away.
- Public repository: no IP addresses, host names, e-mail or wallet addresses, keys, tokens or personal paths.
- Never weaken a safety check, cap, gate, kill switch or test of the live bots.
- Every file you touch keeps its tests green and gets new tests; run them and commit only when they pass."""

SYSTEM = """You are a careful coding agent working in the git clone {root} of Pythia, a paper-first trading system. You change code with the tools below, run the tests and commit. Nobody answers questions during the run: decide yourself and keep going until the task is done.

House rules:
{rules}

Tools:
- list_files(glob): paths under the root, e.g. "research/lab/lab/**/*.py".
- grep(pattern, glob): a Python regex over files; file:line: text, at most {grep_cap} matches.
- graph(query, mode): the code graph; mode "explain" gives file:line, callers and callees of a name like "load_panel()", "affected" what depends on it. Use it before reading many files.
- read_file(path, start, lines): numbered lines, at most {read_cap} at once; read only the part you need.
- replace(path, old, new): old must match exactly once (copy it from read_file without the line numbers); prefer it to rewriting a file.
- write_file(path, content): a new file or a full rewrite.
- run(cmd, cwd): only `python -m pytest ...`, `python -m <module>` of research/lab, `git status|diff|add|commit ...`, optionally behind `flock /run/lock/pythia/heavy.lock`. No shell, no pipes; cwd is relative to the root (default research/lab when it exists).

How to work: first write a short plan (files to change, tests to add). Read the code you change and follow its style: dense, plain comments, no refactoring the task does not need. Make small edits, run the tests of the files you touch, fix what fails, then `git add` the files and `git commit -m "..."`. Old tool results may be shortened to one line to save room; read again what you still need. When done, end with a short summary of what changed and the tests run, without calling a tool."""


def system_prompt(root: Path, rules: str | None) -> str:
    rules = (rules or DEFAULT_RULES).strip()
    if len(rules) > RULES_CAP:
        rules = rules[:RULES_CAP] + "\n(rules cut here)"
    return SYSTEM.format(root=root, rules=rules, grep_cap=GREP_CAP, read_cap=READ_CAP)


def _tool(name, desc, props, required):
    return {"name": name, "description": desc,
            "input_schema": {"type": "object", "properties": props, "required": required}}


S, I = {"type": "string"}, {"type": "integer"}
TOOLS = [
    _tool("list_files", "List paths matching a glob under the root.", {"glob": S}, ["glob"]),
    _tool("read_file", "Read numbered lines of a file.", {"path": S, "start": I, "lines": I}, ["path"]),
    _tool("grep", "Regex search in files matching a glob.", {"pattern": S, "glob": S}, ["pattern"]),
    _tool("graph", "Code graph: explain or affected of a name.",
          {"query": S, "mode": {"type": "string", "enum": ["explain", "affected"]}}, ["query"]),
    _tool("write_file", "Write a whole file.", {"path": S, "content": S}, ["path", "content"]),
    _tool("replace", "Replace one exact, unique occurrence in a file.", {"path": S, "old": S, "new": S},
          ["path", "old", "new"]),
    _tool("run", "Run an allowed command (pytest, a lab module, git status/diff/add/commit).",
          {"cmd": S, "cwd": S}, ["cmd"]),
]


# ---------------------------------------------------------------- the tools

class ToolError(Exception):
    pass


class Tools:
    def __init__(self, root: Path, out: Path | None = None, read_roots: list[Path] | None = None,
                 run_timeout: int = 900):
        self.root = root.resolve()
        self.out = out.resolve() if out else None
        self.read_roots = [p.resolve() for p in read_roots or []]
        self.run_timeout = run_timeout
        self.changed: list[str] = []          # files written or replaced, in order
        self.last_test: str = ""              # the last pytest output, kept through every summary

    # paths: resolved (symlinks followed), then inside the root, /out (write) or a read root
    def path(self, p: str, write: bool = False) -> Path:
        if not isinstance(p, str) or not p.strip() or "\x00" in p:
            raise ToolError("path missing")
        raw = Path(p.strip())
        full = (raw if raw.is_absolute() else self.root / raw).resolve()
        roots = [self.root] + ([self.out] if self.out else []) + ([] if write else self.read_roots)
        if not any(full == r or full.is_relative_to(r) for r in roots):
            raise ToolError(f"path outside {self.root}: {p}")
        if full.is_relative_to(self.root) and ".git" in full.relative_to(self.root).parts:
            raise ToolError("the .git folder is off limits; use run('git ...')")
        return full

    def rel(self, full: Path) -> str:
        return str(full.relative_to(self.root)) if full.is_relative_to(self.root) else str(full)

    def walk(self, pattern: str):
        if pattern.startswith("/") or ".." in Path(pattern).parts:
            raise ToolError("the glob is relative to the root, without ..")
        pat = pattern or "**/*"
        for d, dirs, files in os.walk(self.root):
            dirs[:] = sorted(x for x in dirs if x not in SKIP_DIRS)
            for f in sorted(files):
                rel = os.path.relpath(os.path.join(d, f), self.root)
                if fnmatch.fnmatch(rel, pat) or ("/" not in pat and fnmatch.fnmatch(f, pat)) \
                        or (pat.startswith("**/") and fnmatch.fnmatch(rel, pat[3:])):
                    yield rel

    def list_files(self, glob: str = "**/*") -> str:
        out = []
        for rel in self.walk(glob):
            out.append(rel)
            if len(out) >= LIST_CAP:
                out.append(f"(cut at {LIST_CAP}; narrow the glob)")
                break
        return "\n".join(out) or "no files match"

    def read_file(self, path: str, start: int = 1, lines: int = 200) -> str:
        full = self.path(path)
        if not full.is_file():
            raise ToolError(f"no such file: {path}")
        text = full.read_text(encoding="utf-8", errors="replace").splitlines()
        start = max(1, int(start or 1))
        n = max(1, min(int(lines or 200), READ_CAP))
        part = text[start - 1:start - 1 + n]
        body = "\n".join(f"{i:>5}  {ln if len(ln) <= LINE_CAP else ln[:LINE_CAP] + ' (cut)'}"
                         for i, ln in enumerate(part, start))
        end = start + len(part) - 1
        more = f"\n(lines {start} to {end} of {len(text)})" if end < len(text) or start > 1 else ""
        return (body or f"(file has {len(text)} lines)") + more

    def grep(self, pattern: str, glob: str = "**/*") -> str:
        try:
            rx = re.compile(pattern)
        except re.error as e:
            raise ToolError(f"bad regex: {e}")
        out = []
        for rel in self.walk(glob or "**/*"):
            full = self.root / rel
            try:
                if full.stat().st_size > 1_000_000:
                    continue
                text = full.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for i, ln in enumerate(text.splitlines(), 1):
                if rx.search(ln):
                    out.append(f"{rel}:{i}: {ln.strip()[:200]}")
                    if len(out) >= GREP_CAP:
                        return "\n".join(out) + f"\n(cut at {GREP_CAP} matches; narrow the pattern or glob)"
        return "\n".join(out) or "no match"

    def graph(self, query: str, mode: str = "explain") -> str:
        if mode not in ("explain", "affected"):
            raise ToolError("mode is explain or affected")
        if not (self.root / "graphify-out").is_dir():
            raise ToolError("no code graph here (graphify-out missing); use grep")
        env = dict(_clean_env(), GRAPHIFY_BACKEND="none")
        try:
            p = subprocess.run(["graphify", mode, str(query)], cwd=self.root, env=env, capture_output=True,
                               text=True, timeout=120)
        except FileNotFoundError:
            raise ToolError("graphify is not installed; use grep")
        except subprocess.TimeoutExpired:
            raise ToolError("graphify timed out")
        return cap((p.stdout + p.stderr).strip()) or "nothing found"

    def write_file(self, path: str, content: str) -> str:
        full = self.path(path, write=True)
        if EM_DASH in content:
            raise ToolError("the content has an em dash; the rules forbid it, use a comma, colon or hyphen")
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content, encoding="utf-8")
        self._changed(full)
        return f"wrote {self.rel(full)} ({content.count(chr(10)) + 1} lines)"

    def replace(self, path: str, old: str, new: str) -> str:
        full = self.path(path, write=True)
        if not full.is_file():
            raise ToolError(f"no such file: {path}")
        if not old:
            raise ToolError("old is empty")
        if EM_DASH in new:
            raise ToolError("new has an em dash; the rules forbid it")
        text = full.read_text(encoding="utf-8")
        n = text.count(old)
        if n != 1:
            raise ToolError(f"old matches {n} times, it must match exactly once"
                            + ("; read the file again and copy the lines exactly" if n == 0 else "; add context"))
        full.write_text(text.replace(old, new, 1), encoding="utf-8")
        self._changed(full)
        line = text[:text.index(old)].count("\n") + 1
        return f"replaced in {self.rel(full)} at line {line} ({old.count(chr(10)) + 1} lines by {new.count(chr(10)) + 1})"

    def _changed(self, full: Path) -> None:
        rel = self.rel(full)
        if rel not in self.changed:
            self.changed.append(rel)

    def run(self, cmd: str, cwd: str | None = None) -> str:
        argv = self.check_cmd(cmd)
        default = self.root / "research" / "lab"
        wd = self.path(cwd) if cwd else (default if default.is_dir() else self.root)
        if not wd.is_dir() or not wd.is_relative_to(self.root):
            raise ToolError(f"cwd must be a folder inside {self.root}")
        try:
            p = subprocess.run(argv, cwd=wd, env=_clean_env(), capture_output=True, text=True,
                               timeout=self.run_timeout, stdin=subprocess.DEVNULL)
            text = f"exit {p.returncode}\n{cap((p.stdout + p.stderr).strip())}"
        except subprocess.TimeoutExpired as e:
            text = f"timed out after {self.run_timeout} s\n{cap(_s(e.stdout) + _s(e.stderr))}"
        if "pytest" in argv:
            self.last_test = f"$ {cmd}\n{text}"
        return text

    def check_cmd(self, cmd: str) -> list[str]:
        """The command as argv, or ToolError: pytest, a lab module, four git verbs; never a shell."""
        try:
            argv = shlex.split(cmd or "")
        except ValueError as e:
            raise ToolError(f"cannot parse the command: {e}")
        if len(argv) >= 3 and argv[0] == "flock" and argv[1].startswith("/run/lock/pythia/") \
                and ".." not in argv[1]:
            return argv[:2] + self.check_cmd(shlex.join(argv[2:]))
        if len(argv) >= 3 and argv[0] in ("python", "python3") and argv[1] == "-m":
            mod = argv[2]
            if mod == "pytest":
                return [sys.executable] + argv[1:]
            if re.fullmatch(r"lab(\.[A-Za-z_]\w*)+", mod) and not mod.startswith("lab.pumpfun_rt"):
                base = self.root / "research" / "lab" / Path(*mod.split("."))
                if base.with_suffix(".py").is_file() or (base / "__main__.py").is_file():
                    return [sys.executable] + argv[1:]
            raise ToolError("python -m runs only pytest or a module of research/lab (lab.x.y), "
                            "not the live bot's")
        if len(argv) >= 2 and argv[0] == "git" and argv[1] in ("status", "diff", "add", "commit"):
            for a in argv[2:]:
                if re.match(r"--(output|ext-diff|exec|author|amend|no-verify|git-dir|work-tree|"
                            r"template|reuse-message|reedit-message|fixup|squash|cleanup|"
                            r"pathspec-from-file|no-index)", a) or a in ("-c", "-C", "-n"):
                    raise ToolError(f"git option {a} is not allowed")
            if argv[1] == "commit":
                msg = " ".join(argv[2:])
                if EM_DASH in msg or re.search(r"co-authored-by|\bclaude\b", msg, re.I) or re.search(r"\bAI\b", msg):
                    raise ToolError("the commit message breaks the rules (em dash, attribution, Claude or AI)")
            return ["git", "-c", "core.hooksPath=/dev/null"] + argv[1:]
        raise ToolError("run allows only: python -m pytest ..., python -m lab.<module> ..., "
                        "git status|diff|add|commit ...")

    def call(self, name: str, args: dict) -> tuple[str, bool, str]:
        """(result, is_error, one-line summary) of one tool call."""
        fn = getattr(self, name, None) if name in {t["name"] for t in TOOLS} else None
        brief = ", ".join(f"{k}={_brief(v)}" for k, v in (args or {}).items() if k not in ("content", "old", "new"))
        try:
            if fn is None:
                raise ToolError(f"unknown tool {name}")
            out = fn(**(args or {}))
            first = out.strip().splitlines()[0] if out.strip() else ""
            return out, False, f"{name}({brief}) -> {_brief(first, 120)}, {len(out)} chars"
        except ToolError as e:
            return f"error: {e}", True, f"{name}({brief}) -> error: {_brief(str(e), 120)}"
        except TypeError as e:
            return f"error: bad arguments: {e}", True, f"{name}({brief}) -> bad arguments"
        except OSError as e:
            return f"error: {e}", True, f"{name}({brief}) -> error: {_brief(str(e), 120)}"


def _clean_env() -> dict:
    """The environment for a command, without the model's credentials."""
    return {k: v for k, v in os.environ.items()
            if not k.startswith("ANTHROPIC_") and k not in ("CLAUDE_CODE_OAUTH_TOKEN",)}


def _s(b) -> str:
    return b.decode("utf-8", "replace") if isinstance(b, bytes) else (b or "")


def _brief(v, n: int = 60) -> str:
    s = v if isinstance(v, str) else json.dumps(v)
    s = s.replace("\n", " ")
    return s if len(s) <= n else s[:n] + "..."


def cap(text: str, n: int = OUT_CAP) -> str:
    if len(text) <= n:
        return text
    return text[:n // 4] + f"\n(... {len(text) - n} characters cut ...)\n" + text[-(n - n // 4):]


# ---------------------------------------------------------------- context discipline

def history_tokens(system: str, messages: list) -> int:
    return est_tokens(system) + est_tokens(messages) + est_tokens(TOOLS)


def compact(messages: list, summaries: dict, tools: Tools, system: str, limit: int) -> bool:
    """Shrinks the history in place when it passes the limit; True when it changed anything.

    Step 1: tool results older than the last KEEP_RECENT messages become their one-line
    summary (the last test output stays whole) and the big inputs of old writes shrink.
    Step 2, if still over: the oldest turns go; the first message (the task) gets a note
    with the plan, the files changed and the last test output."""
    if history_tokens(system, messages) <= limit:
        return False
    changed = False
    last_test_id = summaries.get("_last_test_id")
    for m in messages[:-KEEP_RECENT]:
        if not isinstance(m.get("content"), list):
            continue
        for b in m["content"]:
            if b.get("type") == "tool_result" and b.get("tool_use_id") in summaries \
                    and b.get("tool_use_id") != last_test_id and not str(b.get("content", "")).startswith("[summary]"):
                b["content"] = "[summary] " + summaries[b["tool_use_id"]]
                changed = True
            elif b.get("type") == "tool_use" and b.get("name") in ("write_file", "replace"):
                for k in ("content", "old", "new"):
                    v = b.get("input", {}).get(k)
                    if isinstance(v, str) and len(v) > 200:
                        b["input"][k] = v[:120] + f"... ({v.count(chr(10)) + 1} lines, shortened)"
                        changed = True
    if history_tokens(system, messages) <= limit:
        return changed
    plan = next((b["text"] for m in messages[1:] if m["role"] == "assistant" and isinstance(m["content"], list)
                 for b in m["content"] if b.get("type") == "text" and b.get("text", "").strip()), "")
    task = messages[0]["content"] if isinstance(messages[0]["content"], str) else json.dumps(messages[0]["content"])
    task = task.split("\n\n[context note]")[0]
    note = ("\n\n[context note] The oldest turns were dropped to save room. Your plan:\n" + plan[:1500]
            + "\nFiles changed so far: " + (", ".join(tools.changed) or "none")
            + "\nLast test output:\n" + (cap(tools.last_test, 2000) or "none yet"))
    # cut before an assistant message so every tool_result still follows its tool_use
    starts = [i for i in range(2, len(messages)) if messages[i]["role"] == "assistant"]
    for i in starts:
        kept = [{"role": "user", "content": task + note}] + messages[i:]
        if history_tokens(system, kept) <= limit or i == starts[-1]:
            messages[:] = kept
            return True
    return changed


# ---------------------------------------------------------------- the model

def post(base: str, token: str, body: dict, timeout: int) -> dict:
    req = urllib.request.Request(base.rstrip("/") + "/v1/messages", data=json.dumps(body).encode(), method="POST",
                                 headers={"content-type": "application/json", "anthropic-version": "2023-06-01",
                                          "authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def ask(base, token, body, timeout, tries: int = 3, pause: float = 5.0) -> dict:
    """One reply; retries a 429, a 5xx and a dropped connection, any other error at once."""
    for k in range(tries):
        try:
            return post(base, token, body, timeout)
        except urllib.error.HTTPError as e:
            detail = e.read()[:300].decode("utf-8", "replace")
            if e.code != 429 and e.code < 500 or k == tries - 1:
                raise RuntimeError(f"HTTP {e.code}: {detail}")
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if k == tries - 1:
                raise RuntimeError(f"no answer: {e}")
        time.sleep(pause * (k + 1))
    raise RuntimeError("no answer")


def run_session(task: str, root: Path, rules: str | None = None, *, base: str, token: str, model: str,
                ctx: int = 30000, max_turns: int = 150, wall_s: int = 10800, max_tokens: int = 8192,
                http_timeout: int = 900, run_timeout: int = 900, out: Path | None = None,
                read_roots: list[Path] | None = None) -> dict:
    t0 = time.time()
    tools = Tools(root, out=out, read_roots=read_roots, run_timeout=run_timeout)
    system = system_prompt(tools.root, rules)
    messages: list = [{"role": "user", "content": task}]
    summaries: dict = {}
    usage = {"input_tokens": 0, "output_tokens": 0}
    turns, result, reason, err = 0, "", "completed", False
    while True:
        if turns >= max_turns:
            reason, err = "max_turns", True
            break
        if time.time() - t0 > wall_s:
            reason, err = "wall_clock", True
            break
        if compact(messages, summaries, tools, system, ctx):
            log(f"history shortened to about {history_tokens(system, messages)} tokens")
        body = {"model": model, "max_tokens": max_tokens, "system": system, "tools": TOOLS, "messages": messages}
        try:
            reply = ask(base, token, body, http_timeout)
        except RuntimeError as e:
            reason, err, result = "api_error", True, str(e)
            break
        turns += 1
        for k in usage:
            usage[k] += int((reply.get("usage") or {}).get(k) or 0)
        content = reply.get("content") or []
        messages.append({"role": "assistant", "content": content})
        text = "\n".join(b.get("text", "") for b in content if b.get("type") == "text").strip()
        if text:
            result = text
        calls = [b for b in content if b.get("type") == "tool_use"]
        log(f"turn {turns}, about {history_tokens(system, messages)} tokens, "
            f"{', '.join(b.get('name', '?') for b in calls) or reply.get('stop_reason')}")
        if not calls:
            if reply.get("stop_reason") == "max_tokens":
                messages.append({"role": "user", "content": "Your reply was cut at the token limit. Continue, "
                                                            "in smaller steps."})
                continue
            break
        results = []
        for b in calls:
            out_text, is_err, summary = tools.call(b.get("name", ""), b.get("input") or {})
            summaries[b.get("id")] = summary
            if b.get("name") == "run" and not is_err and "pytest" in str((b.get("input") or {}).get("cmd")):
                summaries["_last_test_id"] = b.get("id")
            log("  " + summary)
            r = {"type": "tool_result", "tool_use_id": b.get("id"), "content": out_text}
            if is_err:
                r["is_error"] = True
            results.append(r)
        messages.append({"role": "user", "content": results})
    return {"type": "result", "subtype": "success" if not err else
            ("error_max_turns" if reason == "max_turns" else "error_during_execution"),
            "is_error": err, "result": result, "num_turns": turns, "terminal_reason": reason,
            "duration_ms": int((time.time() - t0) * 1000), "usage": usage, "files_changed": tools.changed}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--task", required=True, help="the task prompt (markdown file)")
    ap.add_argument("--rules", default=os.environ.get("MINI_AGENT_RULES"),
                    help="the house rules (e.g. common.md); built-in rules without it")
    ap.add_argument("--root", default=os.environ.get("MINI_AGENT_ROOT", "/work"))
    ap.add_argument("--max-turns", type=int, default=env_int("MINI_AGENT_MAX_TURNS", 150))
    a = ap.parse_args(argv)
    base = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
    token = os.environ.get("ANTHROPIC_AUTH_TOKEN") or os.environ.get("ANTHROPIC_API_KEY", "")
    model = os.environ.get("ANTHROPIC_MODEL", "")
    out_dir = os.environ.get("MINI_AGENT_OUT", "/out")
    try:
        task = Path(a.task).read_text(encoding="utf-8")
        rules = Path(a.rules).read_text(encoding="utf-8") if a.rules else None
        if not model:
            raise OSError("set ANTHROPIC_MODEL")
    except OSError as e:
        print(json.dumps({"type": "result", "subtype": "error_during_execution", "is_error": True,
                          "result": str(e), "num_turns": 0, "terminal_reason": "setup"}))
        return 1
    res = run_session(task, Path(a.root), rules, base=base, token=token, model=model,
                      ctx=env_int("MINI_AGENT_CTX", 30000), max_turns=a.max_turns,
                      wall_s=env_int("MINI_AGENT_WALL_S", 10800), max_tokens=env_int("MINI_AGENT_MAX_TOKENS", 8192),
                      http_timeout=env_int("MINI_AGENT_HTTP_TIMEOUT", 900),
                      run_timeout=env_int("MINI_AGENT_RUN_TIMEOUT", 900),
                      out=Path(out_dir) if out_dir else None,
                      read_roots=[Path(p) for p in os.environ.get("MINI_AGENT_READ_ROOTS", "").split(":") if p])
    print(json.dumps(res, ensure_ascii=False))
    return 1 if res["is_error"] else 0


if __name__ == "__main__":
    sys.exit(main())
