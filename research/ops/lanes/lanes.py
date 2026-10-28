"""The task lanes: one paid Claude Code run per task file, checked when it is queued, before it
starts, in its container before it commits and on the host before anything lands (run_lane.sh).

    python3 lanes.py queue-check TASK.md [--repo DIR]   the task file complete, its list sound and covering its brief
    python3 lanes.py check --task TASK.md [--repo /work] [--base REV] [--tests]
                                                         in the container, before a commit: what the host would do
    python3 lanes.py verdict --task T --repo R --base B --head H --owner-name N --owner-email M [--patterns F]
                                                         on the host: JSON {fatal, dropped, kept, warnings}
    python3 lanes.py prune --repo R --base B --head H --keep FILE     the commits limited to the kept paths
    python3 lanes.py retry --task T --reasons FILE --out NEW.md       the one retry, a cheaper model, the reasons
    python3 lanes.py budget --state FILE --spent FILE --max-usd X     may a run start
    python3 lanes.py record ... / report ...                          the lane's JSON for the briefing and the app
    python3 lanes.py replay FILE                                      past rejections against these rules
    python3 lanes.py trials --copy FILE --registry FILE              the run's new trials into the server's registry

The task file (task_template.md): a header between two `---` lines with `id`, `title`, `model`,
`max_usd`, `allowed:` (globs of the files the run may change), `docs:` (what it reads first) and
`tests:` (commands, run from the repository root), then the brief. A path the brief's `Files:` line
names must be covered by `allowed`; a path on NEVER never can be, whatever a task says.

What a run changes outside its list is dropped by the host (whole files, every hunk of them) and
said so in the notice; the rest lands when it passes on its own. What holds the whole run
(`fatal`): the guard's private lines and file kinds, an em dash, an allow marker, an attribution
or a foreign author, a kept module that newly imports real-money code, a job table change against
the job rules, tests that fail, nothing left. A held run gets one retry on the next cheaper model,
starting from the held commits, with the reasons in its brief.

Standard library only; next to the agent's guard.py (../agent), whose checks it uses.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import stat
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

_here = Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent / "agent"))      # research/ops/agent, or /opt/pythia-ops/agent
import guard  # noqa: E402
import jobs  # noqa: E402  (guard put its folder on the path)

# Paths no task list can open: the code that signs, sends or limits real money, what deploys and
# watches it, its tests, and the rules of the lanes and the agent themselves. The owner changes
# them by hand. Real money runs from /opt/pythia-live, which only the owner deploys (deploy_live.sh).
NEVER = (
    "research/lab/lab/pumpfun_rt/live.py", "research/lab/lab/pumpfun_rt/live_*.py",
    "research/lab/lab/pumpfun_rt/txbuild.py", "research/lab/lab/pumpfun_rt/wallet.py",
    "research/lab/lab/pumpfun_rt/fastpath.py",
    "research/lab/lab/onchain/live_*.py", "research/lab/lab/onchain/meme_live.py", "research/lab/lab/onchain/wallet.py",
    "research/lab/lab/onchain/tx.py", "research/lab/lab/onchain/swapapi.py", "research/lab/lab/onchain/jupiter.py",
    "research/lab/lab/onchain/guard.py",
    "research/lab/lab/paper/live_copy.py", "research/lab/lab/paper/families.py",
    "research/lab/tests/test_pumpfun_live*.py", "research/lab/tests/test_onchain_live*.py",
    "research/lab/tests/test_onchain_wallet*.py", "research/lab/tests/test_pumpfun_wallet_limits.py",
    "research/lab/tests/test_live_copy.py",
    "crates/pythia-core/src/pumpfun_live*.rs", "crates/pythia-core/src/onchain_live*.rs",
    "crates/pythia-core/src/vault.rs", "crates/pythia-core/src/connectors/**", "crates/pythia-core/src/execution/**",
    "server/src/guard*.rs",
    "research/ops/deploy_live.sh", "research/ops/pumpfun_live_watch.py", "research/ops/onchain_live_watch.py",
    "SAFETY.md",
    "research/ops/lanes/**", "research/ops/agent/guard.py", "research/ops/agent/test_guard.py",
    "research/ops/agent/run_agent.sh", "research/ops/agent/audit_cases.sh", "research/ops/agent/Dockerfile",
    "research/ops/deploy_ops.sh", "research/ops/deploy_lab.sh",
    ".gitleaks.toml", ".gitleaksignore", ".github/**", "scripts/hooks/**", "scripts/security-scan.sh",
)
# Dearest first; a retry goes one step down, the cheapest gets no retry.
MODELS = ("claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5")
MAX_USD = 30.0                 # no single task may ask for more
SUBJECT_MAX = 200              # a longer commit subject is a warning: the detail goes in the body
REASONS_MAX = 3000             # characters of reasons a retry's brief carries
REQUIRED = ("id", "title", "model", "max_usd", "allowed", "docs", "tests")
LISTS = ("allowed", "docs", "tests")
TEST_WORDS = {"cd", "python", "python3", "pytest", "npx", "npm", "cargo", "bash"}
ROOTS = ("research/", "docs/", "src/", "src-tauri/", "crates/", "server/", "scripts/", "cli/", "config/", "public/",
         ".github/")
TESTS = "<tests>"              # a Files line's "tests": some test file must be allowed
TABLE = guard.TABLE
EM_DASH = guard.EM_DASH


# ---------------------------------------------------------------- globs

def glob_re(g: str) -> re.Pattern:
    """`**` any number of folders, `*` and `?` inside one name, `{a,b}` either."""
    out, i = "", 0
    while i < len(g):
        if g.startswith("**/", i):
            out, i = out + "(?:[^/]+/)*", i + 3
        elif g.startswith("**", i):
            out, i = out + ".*", i + 2
        elif g[i] == "*":
            out, i = out + "[^/]*", i + 1
        elif g[i] == "?":
            out, i = out + "[^/]", i + 1
        elif g[i] == "{":
            j = g.index("}", i)                     # ValueError on an open brace
            out += "(?:" + "|".join(re.escape(a) for a in g[i + 1:j].split(",")) + ")"
            i = j + 1
        else:
            out, i = out + re.escape(g[i]), i + 1
    return re.compile(out + r"\Z")


def matches(path: str, globs) -> bool:
    return any(glob_re(g).match(path) for g in globs)


def never(path: str) -> bool:
    return matches(path, NEVER)


def expand(g: str) -> list[str]:
    """`a/{b,c}.py` -> a/b.py, a/c.py."""
    m = re.search(r"\{([^{}]*)\}", g)
    return [y for a in m.group(1).split(",") for y in expand(g[:m.start()] + a + g[m.end():])] if m else [g]


def sample(g: str) -> str:
    """A concrete path a glob matches."""
    return re.sub(r"\*\*/", "x/", expand(g)[0]).replace("**", "x").replace("*", "x").replace("?", "x")


# ---------------------------------------------------------------- the task file

@dataclass
class Task:
    id: str = ""
    title: str = ""
    model: str = ""
    max_usd: float | None = None
    allowed: list[str] = field(default_factory=list)
    docs: list[str] = field(default_factory=list)
    tests: list[str] = field(default_factory=list)
    body: str = ""
    retry_of: str = ""
    retry: bool = True
    keys: set[str] = field(default_factory=set)
    errors: list[str] = field(default_factory=list)

    def allows(self, path: str) -> bool:
        return matches(path, self.allowed) and not never(path)


def parse_task(text: str) -> Task:
    t = Task()
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---" or "---" not in [x.strip() for x in lines[1:]]:
        t.errors.append("no header: the file must start with a `---` line, the keys, and a `---` line")
        t.body = text.strip()
        return t
    end = 1 + [x.strip() for x in lines[1:]].index("---")
    cur = None
    for n, raw in enumerate(lines[1:end], 2):
        line = raw.split(" #", 1)[0].rstrip() if not raw.lstrip().startswith("- ") else raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.lstrip().startswith("- "):
            if cur is None:
                t.errors.append(f"line {n}: a list item without a key")
            else:
                getattr(t, cur).append(line.lstrip()[2:].strip().strip("'\""))
            continue
        key, sep, val = line.partition(":")
        key, val = key.strip(), val.strip()
        if not sep or not re.fullmatch(r"[a-z_]+", key):
            t.errors.append(f"line {n}: not `key: value`")
            continue
        t.keys.add(key)
        cur = None
        if key in LISTS:
            if val.startswith("[") and val.endswith("]"):
                setattr(t, key, [x.strip().strip("'\"") for x in val[1:-1].split(",") if x.strip()])
            elif val:
                t.errors.append(f"line {n}: {key} is a list (`{key}:` and then `  - item` lines)")
            else:
                cur = key
        elif key == "max_usd":
            try:
                t.max_usd = float(val)
            except ValueError:
                t.errors.append(f"line {n}: max_usd must be a number of US dollars")
        elif key == "retry":
            t.retry = val.lower() not in ("no", "false", "0", "off")
        elif key in ("id", "title", "model", "retry_of"):
            setattr(t, key, val.strip("'\""))
        else:
            t.errors.append(f"line {n}: unknown key {key}")
    t.body = "\n".join(lines[end + 1:]).strip()
    return t


def resolve(token: str) -> str:
    """A path as the briefs write it: relative to research/lab/ unless it starts with a top folder or is a root file."""
    token = token.strip().strip("`'\"").rstrip(".,;:)").lstrip("(")
    if token.startswith("./"):
        token = token[2:]
    if token.startswith(ROOTS) or "/" not in token:
        return token
    return "research/lab/" + token


_PATHLIKE = re.compile(r"^[A-Za-z0-9_.*?{},/-]+$")
_ROOTFILE = re.compile(r"^[A-Za-z0-9_.-]+\.(md|py|sh|json|ya?ml|toml|ts|tsx|rs|txt|mjs|js|html|css)$")


def brief_files(body: str) -> list[str]:
    """The globs the brief's `Files:` line asks for (prose such as `the new result file` is skipped)."""
    lines = body.splitlines()
    start = next((i for i, x in enumerate(lines) if re.match(r"^\W{0,3}files\W{0,3}:", x.strip(), re.I)), None)
    if start is None:
        return []
    text = re.sub(r"^\W{0,3}files\W{0,3}:\**", "", lines[start].strip(), flags=re.I)
    for x in lines[start + 1:]:
        if not x.strip() or re.match(r"^\W{0,3}[A-Z][a-z ]+:", x.strip()) or x.lstrip().startswith(("#", "- ")):
            break
        text += " " + x.strip()
    items, depth, cur = [], 0, ""
    for ch in text:
        depth += (ch == "{") - (ch == "}")
        if ch == "," and depth == 0:
            items.append(cur)
            cur = ""
        else:
            cur += ch
    items.append(cur)
    out = []
    for item in items:
        item = item.strip().rstrip(".")
        if item.lower() in ("tests", "their tests", "its tests", "the tests") or item.lower().endswith(" tests"):
            out.append(TESTS)
            continue
        ticks = re.findall(r"`([^`]+)`", item)
        token = ticks[0] if ticks else (item.split() or [""])[0]
        token = token.strip().rstrip(".,;:")
        if not token or not _PATHLIKE.match(token) or not ("/" in token or _ROOTFILE.match(token)):
            continue
        out.extend(resolve(g) for g in expand(token))
    return out


def queue_problems(task: Task, files: set[str] | None = None) -> list[str]:
    """Why a task may not be queued (empty: it may). `files`: the repository's files at main, when known."""
    out = list(task.errors)
    for k in REQUIRED:
        if k not in task.keys:
            out.append(f"{k} is missing (see research/ops/lanes/task_template.md)")
    if task.id and not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,60}", task.id):
        out.append("id: lower-case letters, digits and dashes, at most 61")
    if "model" in task.keys and task.model not in MODELS:
        out.append(f"model must be one of {', '.join(MODELS)}")
    if "max_usd" in task.keys and task.max_usd is not None and not (0 < task.max_usd <= MAX_USD):
        out.append(f"max_usd must be above 0 and at most {MAX_USD:g}")
    if "allowed" in task.keys and not task.allowed:
        out.append("allowed is empty: a run with nothing it may change cannot pass")
    if "tests" in task.keys and not task.tests:
        out.append("tests is empty: name the test commands the run must keep green")
    for cmd in task.tests:
        if re.search(r"[;|`<>&]|\$\(", cmd.replace("&&", " ")) or any(
                (p.split() or [""])[0] not in TEST_WORDS for p in cmd.split("&&")):
            out.append(f"tests: `{cmd}` is not a plain chain of cd, python, pytest, npx, npm, cargo or bash")
    if not task.body:
        out.append("the brief is empty")
    for g in task.allowed:
        try:
            rx = glob_re(g)
        except ValueError:
            out.append(f"allowed: {g} has an open brace")
            continue
        if g.startswith("/") or ".." in g.split("/") or "\\" in g:
            out.append(f"allowed: {g} must be a path inside the repository")
            continue
        lead = re.split(r"[*?{]", g)[0]
        if "/" not in lead and lead != g:
            out.append(f"allowed: {g} is too broad: name at least its folder")
        hit = [f for f in files or () if rx.match(f)] or [sample(g)]
        if all(never(f) for f in hit):
            out.append(f"allowed: {g} names {hit[0]}, a path on the never list (real money or the lanes' own "
                       "rules); no task can change it, the owner does that by hand")
    for d in task.docs:
        if files is not None and d not in files:
            out.append(f"docs: {d} does not exist on main")
    for want in brief_files(task.body):
        if want == TESTS:
            if not any(re.search(r"(^|/)(tests?/|test_)|_tests?\.|\.test\.", g) for g in task.allowed):
                out.append("the brief asks for tests, but allowed holds no test file: add the test files")
            continue
        concrete = [f for f in files or () if glob_re(want).match(f)]
        guess = [sample(want)] + ([sample(want) + ".py"] if want.endswith("*") else [])
        if any(never(c) for c in concrete or guess[:1]):
            out.append(f"the brief asks for {want}, which is on the never list (real money or the lanes' own "
                       "rules): the owner does that part by hand, take it out of the brief")
        elif not (all(matches(c, task.allowed) for c in concrete) if concrete
                  else any(matches(c, task.allowed) for c in guess)):
            out.append(f"the brief asks for {want}, but allowed does not cover it: add it, or the run is "
                       "rejected for a file it was told to change")
    return list(dict.fromkeys(out))


# ---------------------------------------------------------------- what a run changed, and what the host does with it

@dataclass
class Change:
    path: str
    status: str = "M"                  # A, M or D
    mode: str = "100644"               # the new mode (120000 a symlink, 160000 a submodule)
    data: bytes | None = b""           # the file at the head, None when deleted
    added: list[tuple[int, str]] = field(default_factory=list)
    new_imports: list[str] = field(default_factory=list)   # never-list modules it imports now and did not before


@dataclass
class Commit:
    hash: str
    message: str
    author: tuple[str, str] = ("", "")
    committer: tuple[str, str] = ("", "")


@dataclass
class Verdict:
    fatal: list[str] = field(default_factory=list)
    dropped: dict[str, str] = field(default_factory=dict)
    kept: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"fatal": self.fatal, "dropped": self.dropped, "kept": self.kept, "warnings": self.warnings}


def drop_reason(path: str, task: Task) -> str | None:
    if never(path):
        return "on the never list (real money or the lanes' own rules)"
    if guard.NEVER_NAMES.search(path):
        return "a git, scanner or interpreter control file"
    if not matches(path, task.allowed):
        return "outside the task's allowed list"
    return None


def judge(task: Task, changes: list[Change], commits: list[Commit], owner: tuple[str, str] | None = None,
          patterns: list[re.Pattern] | None = None, need_patterns: bool = False) -> Verdict:
    """What the host does with a run: drop what is off the list, hold the whole run for what it cannot drop."""
    v = Verdict()
    if need_patterns and not patterns:
        v.fatal.append("the owner's private patterns file is missing, unreadable or empty, so nothing goes out")
    for c in changes:
        kinds = guard.private_kinds(c.path, patterns)
        label = "a file name that looks private" if kinds else c.path
        why = drop_reason(c.path, task)
        if why:
            v.dropped[label] = why
            continue
        v.kept.append(c.path)
        if kinds:
            v.fatal.append(f"{label} ({', '.join(kinds)})")
        if c.status == "D":
            continue
        if c.mode in ("120000", "160000"):
            v.fatal.append(f"a symlink or submodule: {label}")
            continue
        if guard.LIVE_DATA_NAMES.search(c.path):
            v.fatal.append(f"named like live data or a secret: {label}")
        data = c.data or b""
        if len(data) > guard.MAX_BYTES:
            v.fatal.append(f"over 1 MB: {label}")
            continue
        if b"\0" in data or not _utf8(data):
            v.fatal.append(f"a binary file: {label} (build fixtures in the test, or write them as text)")
            continue
        for n, text in c.added:
            for k in guard.private_kinds(text, patterns):
                v.fatal.append(f"{label}:{n}: an added line looks private ({k})")
            if guard._MARKERS.search(text):
                v.fatal.append(f"{label}:{n}: an allow marker for the secret scan")
            if EM_DASH in text:
                v.fatal.append(f"{label}:{n}: an em dash (write a colon, a comma or two sentences)")
        if guard._KEY_ARRAY.search("\n".join(t for _, t in c.added)):
            v.fatal.append(f"{label}: added lines hold a 64-number key array")
        for m in c.new_imports:
            v.fatal.append(f"{label}: now imports {m}, real-money code on the never list (copy the constant instead)")
    me = (owner[0], owner[1].lower()) if owner else None
    for c in commits:
        if me and ((c.author[0], c.author[1].lower()) != me or (c.committer[0], c.committer[1].lower()) != me):
            v.fatal.append(f"commit {c.hash}: author or committer is not the owner's identity")
        if guard._ATTRIBUTION.search(c.message):
            v.fatal.append(f"commit {c.hash}: the message names an assistant or carries an attribution line")
        if EM_DASH in c.message:
            v.fatal.append(f"commit {c.hash}: an em dash in the message")
        for k in guard.private_kinds(c.message, patterns):
            v.fatal.append(f"commit {c.hash}: the message looks private ({k})")
        subject = c.message.strip().splitlines()[0] if c.message.strip() else ""
        if len(subject) > SUBJECT_MAX:
            v.warnings.append(f"commit {c.hash}: the subject has {len(subject)} characters; keep it under "
                              f"{SUBJECT_MAX} and put the detail in the body")
    if not changes:
        v.fatal.append("nothing committed")
    elif not v.kept:
        v.fatal.append("nothing left once the files outside the list are dropped")
    v.fatal = list(dict.fromkeys(v.fatal))
    return v


def _utf8(b: bytes) -> bool:
    try:
        b.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


# ---------------------------------------------------------------- git

def _git(repo: str, *args: str, binary: bool = False, env: dict | None = None):
    r = subprocess.run(["git", "-c", "core.quotePath=false", "-c", "core.hooksPath=/dev/null",
                        "-c", "core.fsmonitor=false", "-C", repo, *args],
                       check=True, capture_output=True, env=env)
    return r.stdout if binary else r.stdout.decode("utf-8", "replace")


def worktree_tree(repo: str) -> str:
    """The working tree (tracked and new files, .gitignore applied) as a tree object, the index untouched."""
    with tempfile.TemporaryDirectory() as d:
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(d) / "index")}
        _git(repo, "read-tree", "HEAD", env=env)
        _git(repo, "add", "-A", env=env)
        return _git(repo, "write-tree", env=env).strip()


def _never_modules(modules: dict[str, str]) -> set[str]:
    return {m for m, p in modules.items() if never(p) and not p.endswith("__init__.py")}


def collect(repo: str, base: str, head: str, commits_to: str | None = None) -> tuple[list[Change], list[Commit]]:
    """The changes base..head (head a commit or a tree) and the commits base..commits_to (default head)."""
    changed = guard.changes(repo, base, head)
    texts = guard.blobs(repo, [f"{head}:{p}" for st, _, _, p in changed if st != "D"])
    mods_head = guard.lab_modules(repo, head)
    mods_base = guard.lab_modules(repo, base)
    bad = _never_modules(mods_head)
    out = []
    for st, _old, new_mode, path in changed:
        data = texts.get(f"{head}:{path}") if st != "D" else None
        c = Change(path, st, new_mode, data)
        if st != "D" and new_mode not in ("120000", "160000") and data is not None and b"\0" not in data:
            c.added = guard.added_lines(repo, base, head, path)
            name = next((m for m, p in mods_head.items() if p == path), None)
            if name and not never(path):
                now = guard._imports(name, path, data, mods_head) & bad
                before = set()
                if path in mods_base.values():
                    old = guard.blobs(repo, [f"{base}:{path}"]).get(f"{base}:{path}") or b""
                    before = guard._imports(name, path, old, mods_base)
                c.new_imports = sorted(now - before)
        out.append(c)
    commits = []
    to = commits_to or head
    for rec in _git(repo, "log", "--format=%h%x1f%an%x1f%ae%x1f%cn%x1f%ce%x1f%B%x1e", f"{base}..{to}").split("\x1e"):
        if rec.strip():
            h, an, ae, cn, ce, msg = rec.strip("\n").split("\x1f", 5)
            commits.append(Commit(h, msg, (an, ae), (cn, ce)))
    return out, commits


def table_check(repo: str, base: str, head: str, task: Task) -> list[str]:
    """The guard's job rules, with the task's list for which modules a job may run."""
    try:
        old, new = guard.table_at(repo, base), guard.table_at(repo, head)
    except (subprocess.CalledProcessError, jobs.TableError) as e:
        return [f"the job table does not load: {e}"]
    held = {p: "the never list" for p in guard.lab_modules(repo, head).values() if never(p)}
    existing = set(guard.lab_modules(repo, head).values())
    return guard.table_problems(old, new, held, existing, may_run=task.allows)


def verdict_for(repo: str, base: str, head: str, task: Task, owner=None, patterns=None, need_patterns=False,
                commits_to: str | None = None) -> Verdict:
    changes, commits = collect(repo, base, head, commits_to)
    v = judge(task, changes, commits, owner, patterns, need_patterns)
    if TABLE in v.kept:
        v.fatal += table_check(repo, base, head, task)
    return v


def prune(repo: str, base: str, head: str, keep: list[str]) -> str:
    """The run's commits again on the base, each limited to the kept paths (a commit left empty goes).
    Leaves the clone's current branch at the new head and returns it."""
    mbox = _git(repo, "format-patch", "--stdout", "--binary", "--no-renames", "--no-ext-diff", f"{base}..{head}",
                "--", *[f":(literal){p}" for p in keep], binary=True)
    _git(repo, "reset", "-q", "--hard", base)
    if mbox.strip():
        subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "-C", repo, "am", "-q", "--keep-cr", "--no-3way"],
                       input=mbox, check=True, capture_output=True)
    return _git(repo, "rev-parse", "HEAD").strip()


# ---------------------------------------------------------------- the retry and the budget

def cheaper(model: str) -> str | None:
    i = MODELS.index(model) if model in MODELS else len(MODELS) - 1
    return MODELS[i + 1] if i + 1 < len(MODELS) else None


def retry_text(text: str, reasons: str) -> str | None:
    """The task file of the one retry, or None when there is none: a retry already, `retry: no`, the cheapest
    model, or nothing the run could fix (no reasons)."""
    t = parse_task(text)
    nxt = cheaper(t.model)
    if t.retry_of or not t.retry or nxt is None or not reasons.strip() or t.errors:
        return None
    usd = max(1.0, math.ceil((t.max_usd or 2.0) * 50) / 100)          # half, in cents, at least 1 USD
    head = ["---", f"id: {t.id}-retry", f"title: {t.title} (zweiter Versuch)", f"model: {nxt}", f"max_usd: {usd:g}",
            f"retry_of: {t.id}", "retry: no", "allowed:", *[f"  - {g}" for g in t.allowed],
            "docs:", *[f"  - {d}" for d in t.docs], "tests:", *[f"  - {c}" for c in t.tests], "---"]
    why = reasons.strip()[:REASONS_MAX]
    note = ("## The first run was held\n\nYour clone already holds the first run's commits on main. Fix exactly "
            "what the host said, run the check, commit the fix as a new commit (do not rewrite the first run's "
            "commits) and update /out/report.md. Do not start the task again.\n\nThe host said:\n\n"
            + "\n".join(f"- {x}" for x in why.splitlines() if x.strip()))
    return "\n".join(head) + "\n\n" + note + "\n\n## The brief\n\n" + t.body + "\n"


def spent_since(spent: list[dict], since: str) -> float:
    return sum(float(s.get("usd") or 0) for s in spent if str(s.get("at") or "") >= since)


def budget_gate(state: dict, spent: list[dict], max_usd: float) -> tuple[bool, float, str]:
    """(may start, left, why). Left = the owner's balance less what runs cost since it was set; a run starts
    only if left exceeds the reserve plus the task's max_usd, which also caps the run (--max-budget-usd)."""
    balance = float(state.get("balance_usd") or 0)
    reserve = float(state.get("reserve_usd") or 0)
    left = round(balance - spent_since(spent, str(state.get("since") or "")), 2)
    if state.get("paused"):
        return False, left, "paused by the owner"
    if left > reserve + max_usd:
        return True, left, f"{left:.2f} USD left, reserve {reserve:.2f} plus this run's {max_usd:.2f}"
    return False, left, f"{left:.2f} USD left, not above the reserve {reserve:.2f} plus this run's {max_usd:.2f}"


def read_spent(path: str) -> list[dict]:
    out = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        pass
    return out


def run_cost(claude_json: str, max_usd: float) -> float:
    """What a run cost from `claude -p --output-format json`; when that cannot be read, its cap."""
    try:
        for line in reversed(claude_json.strip().splitlines()):
            d = json.loads(line)
            if isinstance(d, dict) and isinstance(d.get("total_cost_usd"), (int, float)):
                return round(float(d["total_cost_usd"]), 4)
    except ValueError:
        pass
    return float(max_usd)


# ---------------------------------------------------------------- the trials a run registered

TRIALS_MAX = 64 * 1024 * 1024   # bytes of a run's registry copy read at most


def _registry_ids(path: str) -> tuple[set[str], bool]:
    """The ids of a registry file and whether it ends without a newline (a torn last line)."""
    ids, torn = set(), False
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return ids, False
    for line in data.decode("utf-8", "replace").splitlines():
        try:
            r = json.loads(line) if line.strip() else None
        except ValueError:
            continue
        if isinstance(r, dict) and isinstance(r.get("id"), str) and r["id"]:
            ids.add(r["id"])
    return ids, bool(data) and not data.endswith(b"\n")


def merge_trials(copy: str, registry: str) -> int:
    """Append the lines of a run's registry copy whose id the server's registry lacks, unchanged and in order
    (lab.metrics.register's rule: append only, the first line of an id wins); returns how many. The run writes
    its trials into the copy because the data folder is read only to it, and every run counts, held or landed:
    a stopped study looked at the data too. A missing copy adds nothing; the copy is read without following a
    symlink (the agent can write its folder) and capped; lines that are not a JSON object with an id are skipped."""
    try:
        fd = os.open(copy, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_NOCTTY)
    except OSError:
        return 0
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return 0
        with os.fdopen(fd, "rb", closefd=False) as f:
            data = f.read(TRIALS_MAX + 1)
    finally:
        os.close(fd)
    lines = data.decode("utf-8", "replace").splitlines()
    if len(data) > TRIALS_MAX:
        lines = lines[:-1]                                   # the cut last line
    have, torn = _registry_ids(registry)
    new = []
    for line in lines:
        try:
            r = json.loads(line) if line.strip() else None
        except ValueError:
            continue                                         # a torn line of a killed run
        if isinstance(r, dict) and isinstance(r.get("id"), str) and r["id"] and r["id"] not in have:
            have.add(r["id"])
            new.append(line.strip())
    if new:
        Path(registry).parent.mkdir(parents=True, exist_ok=True)
        with open(registry, "a", encoding="utf-8") as fh:
            fh.write(("\n" if torn else "") + "\n".join(new) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
    return len(new)


def prompt_text(task: Task, rules: str) -> str:
    """What the run gets: the lane's rules, its list, what to read, its tests, the never list, the brief."""
    parts = [rules.strip(), "## Allowed (everything else is dropped)", "\n".join(f"- {g}" for g in task.allowed),
             "## Read first", "\n".join(f"- {d}" for d in task.docs) or "- (nothing named)",
             "## Tests that must stay green", "\n".join(f"- `{c}`" for c in task.tests),
             "## The never list (no task can change these)", ", ".join(NEVER),
             f"## The task: {task.title}", task.body]
    return "\n\n".join(parts) + "\n"


# ---------------------------------------------------------------- records for the briefing, the news and the app

def lane_record(task: Task, status: str, reason: str = "", commit: str = "", base: str = "", report: str = "",
                files: list[str] | None = None, dropped: dict | None = None, usd: float | None = None,
                at: int | None = None) -> dict:
    """reports/lanes/<id>.json, the fields lab.ops.news reads plus what the lane added."""
    return {"name": task.id, "title": task.title or task.id, "status": status, "at": int(at or time.time()),
            "base": base[:12], "commit": commit[:12], "reason": reason[:2000], "report": report[:20000],
            "files": files or [], "dropped": dropped or {}, "model": task.model, "usd": usd,
            "retry_of": task.retry_of or None}


def research_report(records: list[dict], running: list[dict], queued: int, held: list[str], state: dict,
                    spent: list[dict], now_ms: int | None = None, n: int = 40) -> dict:
    """reports/research/latest.json for the briefing: the last runs, what runs and waits, the budget."""
    recs = sorted((r for r in records if isinstance(r, dict) and r.get("name")), key=lambda r: -int(r.get("at") or 0))
    done = []
    for r in recs[:n]:
        ok = r.get("status") == "done"
        why = r.get("reason") or ""
        if ok and r.get("dropped"):
            why = (why + " " if why else "") + "Verworfen (nicht auf der Liste): " + ", ".join(sorted(r["dropped"]))
        d = {"title": r.get("title") or r["name"], "ok": ok, "at": int(r.get("at") or 0) * 1000, "why": why[:300],
             "usd": r.get("usd")}
        if r.get("commit"):
            d["commit"] = r["commit"]
        done.append(d)
    ok, left, _ = budget_gate({**state, "paused": False}, spent, 0.0)
    return {"updated_ms": int(now_ms or time.time() * 1000), "done": done, "running": running, "queued": queued,
            "held": held, "budget": {"balance_usd": float(state.get("balance_usd") or 0), "left_usd": left,
                                     "reserve_usd": float(state.get("reserve_usd") or 0),
                                     "since": state.get("since"),
                                     "paused": bool(state.get("paused")) or left <= float(state.get("reserve_usd") or 0)}}


# ---------------------------------------------------------------- the replay

def replay_case(case: dict) -> dict:
    """One past rejection against these rules: refused at the queue, accepted (with what is dropped) or held."""
    task = parse_task(case["task"])
    files = set(case.get("repo_files") or [])
    q = queue_problems(task, files or None)
    if q:
        return {"outcome": "refused at the queue", "usd": 0.0, "reasons": q}
    changes = [Change(c["path"], c.get("status", "M"), c.get("mode", "100644"),
                      c.get("text", "x\n").encode() if not c.get("binary") else b"PAR1\0",
                      [(i + 1, x.replace("EMDASH", EM_DASH)) for i, x in enumerate(c.get("added") or [])])
               for c in case.get("changes") or []]
    v = judge(task, changes, [Commit("c0", case.get("message", "lab: a study"))])
    if case.get("gitleaks") and v.kept:
        v.fatal.append("gitleaks found something in the commits")
    if not v.fatal:
        return {"outcome": "accepted" + (", files dropped" if v.dropped else ""), "usd": case.get("usd"),
                "dropped": v.dropped}
    return {"outcome": "held, one retry on " + (cheaper(task.model) or "no model") if retry_text(
        case["task"], "\n".join(v.fatal)) else "held", "usd": case.get("usd"), "reasons": v.fatal}


# ---------------------------------------------------------------- the commands

def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def _repo_files(repo: str, rev: str = "HEAD") -> set[str]:
    return set(x for x in _git(repo, "ls-tree", "-r", "-z", "--name-only", rev).split("\0") if x)


def _print_verdict(v: Verdict, task: Task) -> None:
    if v.fatal:
        print("HOLD (the host refuses the whole run until these are fixed):")
        print("\n".join(f"  {x}" for x in v.fatal))
    if v.dropped:
        print("DROPPED (the host removes these files and keeps the rest; undo them, or ask for them in the task):")
        print("\n".join(f"  {p}: {w}" for p, w in v.dropped.items()))
    for w in v.warnings:
        print(f"WARN {w}")
    if not v.fatal and not v.dropped:
        print(f"ok: {len(v.kept)} file(s), all on the task's list; allowed: {', '.join(task.allowed)}")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="lanes.py", description=__doc__.strip().splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    q = sub.add_parser("queue-check")
    q.add_argument("task")
    q.add_argument("--repo")
    c = sub.add_parser("check")
    c.add_argument("--task", default=os.environ.get("LANE_TASK", "/lane/task.md"))
    c.add_argument("--repo", default="/work")
    c.add_argument("--base", default=os.environ.get("AGENT_BASE", ""))
    c.add_argument("--tests", action="store_true", help="also run the task's tests")
    v = sub.add_parser("verdict")
    for a in ("--task", "--repo", "--base", "--head"):
        v.add_argument(a, required=True)
    v.add_argument("--owner-name", default=os.environ.get("PYTHIA_AGENT_GIT_NAME", "SenseiIssei"))
    v.add_argument("--owner-email", default=os.environ.get("PYTHIA_AGENT_GIT_EMAIL", ""))
    v.add_argument("--patterns", default=os.environ.get("PYTHIA_AGENT_PRIVATE_PATTERNS", guard.PATTERNS_FILE))
    p = sub.add_parser("prune")
    for a in ("--repo", "--base", "--head", "--keep"):
        p.add_argument(a, required=True)
    r = sub.add_parser("retry")
    for a in ("--task", "--reasons", "--out"):
        r.add_argument(a, required=True)
    b = sub.add_parser("budget")
    b.add_argument("--state", required=True)
    b.add_argument("--spent", required=True)
    b.add_argument("--max-usd", type=float, required=True)
    rc = sub.add_parser("record")
    rc.add_argument("--task", required=True)
    rc.add_argument("--status", choices=("done", "stopped"), required=True)
    rc.add_argument("--out", required=True)
    for a in ("--reason", "--commit", "--base", "--report", "--verdict"):
        rc.add_argument(a, default="")
    rc.add_argument("--usd", type=float)
    rc.add_argument("--files", default="")
    rp = sub.add_parser("report")
    for a in ("--records", "--queue", "--state", "--spent", "--out"):
        rp.add_argument(a, required=True)
    rp.add_argument("--running", default="")
    pr = sub.add_parser("prompt")
    pr.add_argument("--task", required=True)
    pr.add_argument("--rules", default=str(_here / "lane.md"))
    fd = sub.add_parser("field")
    fd.add_argument("--task", required=True)
    fd.add_argument("key", choices=("id", "title", "model", "max_usd", "retry_of"))
    co = sub.add_parser("cost")
    co.add_argument("--file", required=True)
    co.add_argument("--max-usd", type=float, required=True)
    rl = sub.add_parser("replay")
    rl.add_argument("file")
    tr = sub.add_parser("trials")
    tr.add_argument("--copy", required=True)
    tr.add_argument("--registry", required=True)
    a = ap.parse_args(argv)

    if a.cmd == "queue-check":
        try:
            task = parse_task(_read(a.task))
        except OSError:
            print("task.md is missing or unreadable")
            return 1
        found = queue_problems(task, _repo_files(a.repo) if a.repo else None)
        print("\n".join(found) if found else f"ok: {task.id} may be queued ({task.model}, at most {task.max_usd:g} USD)")
        return 1 if found else 0

    if a.cmd == "check":
        task = parse_task(_read(a.task))
        if not a.base:
            print("no base: give --base REV (the run's start, AGENT_BASE in the lane's container)")
            return 2
        base = a.base
        tree = worktree_tree(a.repo)
        verdict = verdict_for(a.repo, base, tree, task, commits_to="HEAD")
        if verdict.fatal == ["nothing committed"]:
            verdict.fatal = ["nothing changed yet"]
        dirty = _git(a.repo, "status", "--porcelain")
        if dirty.strip():
            verdict.warnings.append("not committed yet (the host sees only commits): "
                                    + ", ".join(x[3:] for x in dirty.splitlines()[:10]))
        if a.tests:
            for cmd in task.tests:
                t = subprocess.run(cmd, shell=True, cwd=a.repo, capture_output=True, text=True)
                if t.returncode:
                    verdict.fatal.append(f"tests red: {cmd} (exit {t.returncode}): "
                                         + " ".join((t.stdout + t.stderr).strip().splitlines()[-3:])[:400])
        _print_verdict(verdict, task)
        return 1 if verdict.fatal or verdict.dropped else 0

    if a.cmd == "verdict":
        task = parse_task(_read(a.task))
        try:
            pats = guard.load_patterns(a.patterns)
        except (OSError, ValueError):
            pats = None
        owner = (a.owner_name, a.owner_email) if a.owner_email else None
        out = verdict_for(a.repo, a.base, a.head, task, owner, pats, need_patterns=True)
        if owner is None:
            out.fatal.append("no owner identity given (--owner-email), so nothing goes out")
        print(json.dumps(out.as_dict(), ensure_ascii=False))
        return 1 if out.fatal else 0

    if a.cmd == "prune":
        keep = [x for x in _read(a.keep).splitlines() if x.strip()]
        print(prune(a.repo, a.base, a.head, keep))
        return 0

    if a.cmd == "retry":
        new = retry_text(_read(a.task), _read(a.reasons))
        if new is None:
            print("no retry (a retry already, retry: no, the cheapest model, or no reasons)")
            return 1
        Path(a.out).write_text(new, encoding="utf-8")
        print(f"retry: {parse_task(new).id} on {parse_task(new).model}")
        return 0

    if a.cmd == "budget":
        try:
            state = json.loads(_read(a.state))
        except (OSError, ValueError):
            print(f"no budget: {a.state} is missing or not JSON, so no run starts")
            return 1
        ok, _left, why = budget_gate(state, read_spent(a.spent), a.max_usd)
        print(("ok: " if ok else "no run: ") + why)
        return 0 if ok else 1

    if a.cmd == "record":
        task = parse_task(_read(a.task))
        task.id = task.id or Path(a.task).resolve().parent.name
        verdict = json.loads(_read(a.verdict)) if a.verdict else {}
        report = _read(a.report) if a.report and Path(a.report).is_file() else ""
        files = [x for x in (_read(a.files).splitlines() if a.files else []) if x.strip()]
        rec = lane_record(task, a.status, a.reason, a.commit, a.base, report, files, verdict.get("dropped"), a.usd)
        out = Path(a.out) / f"{task.id}.json"
        tmp = out.with_suffix(".tmp")
        tmp.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(out)
        return 0

    if a.cmd == "report":
        recs = []
        for f in sorted(Path(a.records).glob("*.json")):
            try:
                recs.append(json.loads(f.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
        qdir = Path(a.queue)
        tasks = sorted(qdir.glob("*/task.md")) if qdir.is_dir() else []
        held = [parse_task(t.read_text(encoding="utf-8")).title or t.parent.name for t in tasks
                if (t.parent / "HOLD").exists()]
        running = [{"title": a.running, "since": int(time.time() * 1000), "waiting": False}] if a.running else []
        try:
            state = json.loads(_read(a.state))
        except (OSError, ValueError):
            state = {}
        rep = research_report(recs, running, len(tasks) - len(held), held, state, read_spent(a.spent))
        out = Path(a.out)
        tmp = out.with_suffix(".tmp")
        tmp.write_text(json.dumps(rep, ensure_ascii=False), encoding="utf-8")
        tmp.replace(out)
        return 0

    if a.cmd == "prompt":
        sys.stdout.write(prompt_text(parse_task(_read(a.task)), _read(a.rules)))
        return 0

    if a.cmd == "field":
        val = getattr(parse_task(_read(a.task)), a.key)
        print(f"{val:g}" if isinstance(val, float) else (val or ""))
        return 0

    if a.cmd == "cost":
        try:
            text = _read(a.file)
        except OSError:
            text = ""
        print(f"{run_cost(text, a.max_usd):g}")
        return 0

    if a.cmd == "trials":
        print(f"trials: {merge_trials(a.copy, a.registry)} new into {a.registry}")
        return 0

    if a.cmd == "replay":
        cases = json.loads(_read(a.file))["cases"]
        for case in cases:
            r = replay_case(case)
            print(f"{case['name']}: {r['outcome']}" + (f" ({'; '.join(r.get('reasons') or [])[:200]})"
                                                       if r.get("reasons") else ""))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
