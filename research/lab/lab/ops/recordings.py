"""T13: what the lab records, what it costs on disk and who reads it.

Pre-registered in results/recordings_t13_prereg.md. One row per dataset of research/ops/jobs.yaml and per top-level
folder of <data> that is neither a dataset nor holds one, with its parts down to two folder levels (a partition
folder like date=... or symbol=... ends the descent):

  size       the bytes of every file under it now (one walk, lstat, links not followed)
  growth     a day over 7 and 30 days from <data>/_ops/disk/history.jsonl (the dataset's size against the oldest
             entry inside the window that has it, at least a day back); parts and folders without a record: the
             bytes of files modified inside the window over its days, an upper bound (a rewritten file counts whole)
  GB a month the 7-day growth times 30 (else the 30-day one), never below 0
  writers    jobs and services whose code writes the path, readers those whose code reads it, by a static scan:
             Python by its syntax tree (a path is ROOT / "a" / "b", join or Path with string arguments, a string
             holding a /, an f-string; a function that builds one is a loader, a call of it found through the
             caller's imports uses what it uses, string arguments extend a path that stopped at a variable, as in
             live("binance_um", "premium"); a use is a write when the path or a name holding it is the receiver or
             an argument of a write call, else a read), TypeScript, Rust and shell by their string paths (reads)
  verdict    read by a book or job / read by a study only / read by nobody
  last study the newest results/*.md that names the path or one of its reading studies

The entries: every enabled job (its python -m module or the script it runs), the services outside the job table
(SERVICES, the Python outside the lab package such as the recorder and the Discord bot, the app, server and engine
code) and every other runnable module (a study). An entry uses what any function of its module uses, following
calls and function references across modules. Tests are not readers. A writer's own reads of what it writes do not
count. Without a checkout of the whole repo (the lab image mounts only the lab) the app, server, engine and recorder
are not scanned; the report says which code it saw (PYTHIA_RECORDINGS_CODE, folders separated by the path separator,
adds or replaces them).

No performance number, no trial. Reads only; writes nothing but reports/recordings/latest.md and .json. It
proposes keep, thin out or stop for what nobody reads and stops nothing.

  python -m lab.ops.recordings            write the report (job recordings, weekly)
  python -m lab.ops.recordings --print    print it, write nothing
"""

from __future__ import annotations

import ast
import functools
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from . import jobs as J, notify

NAME = "recordings"
HERE = Path(__file__).resolve()
LAB = HERE.parents[2]                       # research/lab in a checkout, /app in the lab image
GB = 1024 ** 3
DAY_S = 86_400

# ---------------------------------------------------------------- the pre-registered rules
KEEP_GB_MONTH = 1.0         # under this a month an unread dataset is kept
RECENT_DAYS = 90            # a study that used it this recently keeps it
PART_DEPTH = 2              # folder levels of parts below a dataset
PART_MD_MB = 10             # parts smaller than this stay out of the markdown table (all are in the JSON)
VERDICTS = ("read by a book or job", "read by a study only", "read by nobody")

# The lab modules that run as long-lived services, outside the job table (research/ops/README.md).
SERVICES = {"pumpfun-rt": "lab.pumpfun_rt.collector", "pumpfun-live": "lab.pumpfun_rt.live_service",
            "ai-chat": "lab.ai.chat"}
SKIP_DIRS = {"node_modules", "target", "dist", "graphify-out", "__pycache__", "tests", "fixtures", "results",
             "proposals", "public"}
TEXT_EXT = {".ts", ".tsx", ".js", ".mjs", ".rs", ".sh"}
WRITE_RE = re.compile(r"^_*(write\w*|to_parquet|to_csv|sink_\w+|mkdir|makedirs|touch|save\w*|dump|append_\w+|table)$")
ROOT_RE = re.compile(r"^(ROOT|WRITE_ROOT|DATA_ROOT|DATA|DATA_DIR)$")
ROOT_ENV = {"PYTHIA_DATA", "PYTHIA_WRITE_ROOT"}
COLLECT_RE = re.compile(r"(^|\.)(collect|collector|recorder)(\.|$)")
SEG_RE = re.compile(r"^[\w.=-]+$")
PATH_RE = re.compile(r"^[\w.=-]+(/[\w.=*-]+)+/?$")
PART_SKIP_RE = re.compile(r"=|^\d{4}-\d\d-\d\d|^\d{6,}|^\d+$|^\.")
PART_MAX_SIBLINGS = 20      # a folder with more subfolders than this is keyed by symbol or version: no parts
DATE_RE = re.compile(r"\b(20\d\d-[01]\d-[0-3]\d)\b")


# ---------------------------------------------------------------- where things are

def code_roots() -> list[Path]:
    env = os.environ.get("PYTHIA_RECORDINGS_CODE")
    if env:
        return [Path(p) for p in env.split(os.pathsep) if p]
    repo = HERE.parents[4] if len(HERE.parents) > 4 else None
    if repo is not None and (repo / "research" / "recorder").is_dir():
        return [repo]
    roots = [LAB]
    ops = table_path().parent
    if ops.is_dir() and ops.resolve() != LAB.resolve():
        roots.append(ops)
    return roots


def table_path() -> Path:
    env = os.environ.get("PYTHIA_JOBS_TABLE")
    if env:
        return Path(env)
    mine = LAB.parent / "ops" / "jobs.yaml"
    return mine if mine.exists() else Path(J.DEFAULT_TABLE)


def results_dir() -> Path:
    return Path(os.environ.get("PYTHIA_RECORDINGS_RESULTS") or LAB / "results")


def out_dir() -> Path:
    return notify.reports_root() / NAME


# ---------------------------------------------------------------- paths as strings: "" the root, "a/b", "*" a variable

def _add(base: str, seg: str) -> str:
    seg = seg.strip("/")
    return f"{base}/{seg}" if base and seg else base or seg


def _open(base: str) -> str:
    return base if base == "*" or base.endswith("/*") else _add(base, "*")


def _extend(ps: str, arg: str) -> str:
    """A path that stopped at a variable, continued by a call's string arguments in place of its first variable."""
    segs = ps.split("/") if ps else []
    if not arg or "*" not in segs:
        return ps
    i = segs.index("*")
    return "/".join(segs[:i] + arg.split("/") + segs[i + 1:])


def _const_path(s: str) -> str | None:
    for pre in ("/data/", "/srv/pythia-data/"):
        if s.startswith(pre):
            s = s[len(pre):]
    return s.rstrip("/") if PATH_RE.match(s) and not s.startswith(("http", "/")) else None


def base_of(ps: str) -> str:
    segs = ps.split("/") if ps else []
    while segs and segs[-1] == "*":
        segs.pop()
    return "/".join(segs)


@functools.lru_cache(maxsize=None)
def matches(ps: str, path: str, known: frozenset[str] | None = None) -> bool:
    """ps names the folder `path` or something inside it; a * segment matches any folder that exists."""
    b = base_of(ps)
    if not b or "*" not in b:
        return bool(b) and (b == path or b.startswith(path + "/"))
    bs, want = b.split("/"), path.split("/")
    if len(bs) < len(want) or any(x not in ("*", y) for x, y in zip(bs, want)):
        return False
    for i in range(len(bs), len(want) - 1, -1):        # the longest prefix with a name of its own that exists
        if all(x == "*" for x in bs[:i]):
            break
        if any(k == path or k.startswith(path + "/") for k in _expand(tuple(bs[:i]), known or frozenset())):
            return True
    return False


@functools.lru_cache(maxsize=None)
def _expand(pat: tuple[str, ...], known: frozenset[str]) -> list[str]:
    return [k for k in known if k.count("/") == len(pat) - 1 and all(x in ("*", y) for x, y in zip(pat, k.split("/")))]


# ---------------------------------------------------------------- Python by its syntax tree

def module_name(p: Path) -> str:
    parts = [p.stem] if p.stem != "__init__" else []
    d = p.parent
    while (d / "__init__.py").exists():
        parts.insert(0, d.name)
        d = d.parent
    return ".".join(parts) or p.parent.name


class Mod:
    """One Python file: its imports, functions, module-level names and literals."""

    def __init__(self, path: Path, name: str, tree: ast.Module):
        self.path, self.name, self.tree = path, name, tree
        self.imports: dict[str, tuple[str, str | None]] = {}     # local name -> (module, attribute or None)
        self.funcs: dict[str, list[ast.AST]] = {}                # name -> body statements (methods by bare name too)
        self.lits = {n.value for n in ast.walk(tree)
                     if isinstance(n, ast.Constant) and isinstance(n.value, str) and SEG_RE.match(n.value)}
        self.runnable = any(isinstance(n, ast.If) and "__main__" in ast.dump(n.test) for n in tree.body)
        self.nodes: dict[int, list[ast.AST]] = {}                # a scope's nodes, walked once
        self.parents: dict[int, ast.AST] = {}
        for n in ast.walk(tree):
            for c in ast.iter_child_nodes(n):
                self.parents[id(c)] = n
        for n in tree.body:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self.funcs[n.name] = n.body
            elif isinstance(n, ast.ClassDef):
                for m in n.body:
                    if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        self.funcs.setdefault(m.name, m.body)
        self.top = [n for n in tree.body if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]

    def resolve_imports(self, known: set[str]) -> None:
        pkg = self.name.split(".")
        if self.path.stem != "__init__":
            pkg = pkg[:-1]
        for n in ast.walk(self.tree):
            if isinstance(n, ast.Import):
                for a in n.names:
                    top = a.name.split(".")[0]
                    self.imports[a.asname or top] = (a.name if a.asname else top, None)
            elif isinstance(n, ast.ImportFrom):
                base = n.module or ""
                if n.level:
                    up = pkg[:len(pkg) - n.level + 1] if n.level > 1 else pkg
                    base = ".".join(up + ([n.module] if n.module else []))
                for a in n.names:
                    full = f"{base}.{a.name}" if base else a.name
                    self.imports[a.asname or a.name] = (full, None) if full in known else (base, a.name)


class Effects:
    __slots__ = ("reads", "writes", "ret", "calls")

    def __init__(self):
        self.reads: set[str] = set()
        self.writes: set[str] = set()
        self.ret: set[str] = set()
        self.calls: set[tuple[str, str, str]] = set()     # (module, function, string arguments)


class Scanner:
    """Every Python and text file of the code roots, and what each function and entry reads and writes."""

    def __init__(self, roots: list[Path], known: set[str]):
        self.known = frozenset(known)                                  # every folder path of the data tree (a/b/c)
        self.mods: dict[str, Mod] = {}
        self.texts: dict[Path, set[str]] = {}
        for root in roots:
            for p in _files(root):
                if p.suffix == ".py":
                    try:
                        tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
                    except (SyntaxError, ValueError, OSError):
                        continue
                    name = module_name(p)
                    self.mods.setdefault(name, Mod(p, name, tree))
                else:
                    self.texts[p] = text_paths(p.read_text(encoding="utf-8", errors="replace"))
        names = set(self.mods)
        for m in self.mods.values():
            m.resolve_imports(names)
        self.fx: dict[tuple[str, str], Effects] = {}
        self.menv: dict[str, dict[str, set[str]]] = {n: {} for n in self.mods}
        for _ in range(8):
            changed = False
            for m in self.mods.values():
                env = self._scope(m, m.top, {}, Effects(), module=True)
                if env != self.menv[m.name]:
                    self.menv[m.name], changed = env, True
                for f, body in m.funcs.items():
                    e = Effects()
                    self._scope(m, body, dict(self.menv[m.name]), e)
                    old = self.fx.get((m.name, f))
                    if old is None or (old.reads, old.writes, old.ret, old.calls) != (e.reads, e.writes, e.ret,
                                                                                       e.calls):
                        self.fx[(m.name, f)] = e
                        changed = True
            if not changed:
                break

    # one scope: assignments first (two passes), then every maximal path expression is a read, a write or returned
    def _scope(self, m: Mod, body: list, env: dict, e: Effects, module: bool = False) -> dict:
        nodes = m.nodes.get(id(body))
        if nodes is None:
            nodes = m.nodes[id(body)] = [n for s in body for n in ast.walk(s)]
        for _ in range(2):
            for n in nodes:
                if isinstance(n, (ast.Assign, ast.AnnAssign)) and n.value is not None:
                    v = self._eval(m, n.value, env)
                    for t in (n.targets if isinstance(n, ast.Assign) else [n.target]):
                        if isinstance(t, ast.Name) and v:
                            env[t.id] = v
        for n in nodes:
            if isinstance(n, ast.Call):
                tgt = self._target(m, n.func)
                if tgt:
                    e.calls.add((*tgt, _str_args(n)))
            elif isinstance(n, (ast.Name, ast.Attribute)) and isinstance(getattr(n, "ctx", None), ast.Load):
                tgt = self._target(m, n)     # a function named, not called (a callback, a dispatch table)
                par = m.parents.get(id(n))
                if tgt and not (isinstance(par, ast.Call) and par.func is n):
                    e.calls.add((*tgt, ""))
            if isinstance(n, ast.Name) and not isinstance(n.ctx, ast.Load):
                continue
            v = self._eval(m, n, env) if isinstance(n, ast.expr) else None
            if isinstance(n, ast.Call) and _fname(n.func) == "table" and base_of(_str_args(n)).strip("*/"):
                e.writes.add(_str_args(n))      # the recorder's sink: table(source, name, schema)
            if not v or self._inner(m, n, env):
                continue
            par = m.parents.get(id(n))
            if isinstance(par, (ast.Assign, ast.AnnAssign)) and getattr(par, "value", None) is n:
                continue
            if isinstance(par, ast.Return):
                e.ret |= v      # the data root itself too (notify.data_root())
            elif all(not base_of(p) for p in v):
                continue
            elif self._written(m, n):
                e.writes |= v
            else:
                e.reads |= v
        for mod, f, arg in list(e.calls):
            c = self.fx.get((mod, f))
            if c is not None:
                e.reads |= {_extend(p, arg) for p in c.reads}
                e.writes |= {_extend(p, arg) for p in c.writes}
        return env if module else {}

    def _inner(self, m: Mod, n: ast.AST, env: dict) -> bool:
        """n is part of a bigger path expression (the left of a /, the argument of str or join)."""
        par = m.parents.get(id(n))
        if isinstance(par, (ast.JoinedStr, ast.FormattedValue)):
            return True
        if isinstance(par, ast.BinOp) and isinstance(par.op, ast.Div):
            return True
        if isinstance(par, ast.Attribute) and par.attr in ("joinpath", "with_suffix", "with_name", "resolve", "parent"):
            return True
        if isinstance(par, ast.Call) and n in par.args and _fname(par.func) in ("join", "joinpath", "Path", "PurePath",
                                                                                 "str", "fspath"):
            return True
        if isinstance(par, ast.Call) and n in par.args and self._eval(m, par, env):
            return True     # the argument of a path loader: the call is the expression
        return False

    def _written(self, m: Mod, n: ast.AST) -> bool:
        par = m.parents.get(id(n))
        if isinstance(par, ast.Call) and _fname(par.func) in ("str", "fspath") and n in par.args:
            n, par = par, m.parents.get(id(par))
        if isinstance(par, ast.Attribute) and par.value is n:
            call = m.parents.get(id(par))
            return isinstance(call, ast.Call) and call.func is par and bool(WRITE_RE.match(par.attr))
        if isinstance(par, ast.Call) and (n in par.args or any(k.value is n for k in par.keywords)):
            f = _fname(par.func)
            if f == "open":
                mode = par.args[1] if len(par.args) > 1 else next((k.value for k in par.keywords if k.arg == "mode"),
                                                                   None)
                return isinstance(mode, ast.Constant) and isinstance(mode.value, str) and \
                    any(c in mode.value for c in "wax+")
            return bool(f and WRITE_RE.match(f))
        return False

    def _target(self, m: Mod, f: ast.AST) -> tuple[str, str] | None:
        if isinstance(f, ast.Name):
            if f.id in m.funcs:
                return (m.name, f.id)
            imp = m.imports.get(f.id)
            if imp and imp[1] and imp[0] in self.mods and imp[1] in self.mods[imp[0]].funcs:
                return (imp[0], imp[1])
        elif isinstance(f, ast.Attribute):
            v = f.value
            if isinstance(v, ast.Name):
                if v.id in ("self", "cls") and f.attr in m.funcs:
                    return (m.name, f.attr)
                imp = m.imports.get(v.id)
                if imp:
                    mod = imp[0] if imp[1] is None else f"{imp[0]}.{imp[1]}"
                    if mod in self.mods and f.attr in self.mods[mod].funcs:
                        return (mod, f.attr)
        return None

    def _name(self, m: Mod, name: str, env: dict) -> set[str] | None:
        if name in env:
            return env[name]
        if name in self.menv.get(m.name, {}):
            return self.menv[m.name][name]
        imp = m.imports.get(name)
        if imp and imp[1] and imp[1] in self.menv.get(imp[0], {}):
            return self.menv[imp[0]][imp[1]]
        return {""} if ROOT_RE.match(name) else None

    def _vars(self, m: Mod, base: set[str]) -> set[str]:
        """A path continued by a variable: open, and every child folder named by a string of the module."""
        out = set()
        for b in base:
            out.add(_open(b))
            if b and b != "*" and not b.endswith("/*"):
                out |= {_add(b, lit) for lit in m.lits if _add(b, lit) in self.known}
        return out

    def _eval(self, m: Mod, n: ast.AST, env: dict) -> set[str] | None:
        if isinstance(n, ast.Name):
            return self._name(m, n.id, env)
        if isinstance(n, ast.Attribute):
            if ROOT_RE.match(n.attr) and isinstance(n.value, ast.Name) and n.value.id not in ("self", "cls"):
                return {""}
            if n.attr == "parent":
                v = self._eval(m, n.value, env)
                return {base_of(p).rsplit("/", 1)[0] if "/" in base_of(p) else "" for p in v} if v else None
            return None
        if isinstance(n, (ast.BoolOp, ast.IfExp)):
            vals = [self._eval(m, x, env) for x in (n.values if isinstance(n, ast.BoolOp) else [n.body, n.orelse])]
            return set().union(*[v for v in vals if v]) or None
        if isinstance(n, ast.Constant):
            p = _const_path(n.value) if isinstance(n.value, str) else None
            return {p} if p else None
        if isinstance(n, ast.JoinedStr):
            return self._fstring(m, n, env)
        if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Div):
            left = self._eval(m, n.left, env)
            if not left:
                return None
            if isinstance(n.right, ast.Constant) and isinstance(n.right.value, str):
                return {_add(b, n.right.value) for b in left}
            if isinstance(n.right, ast.JoinedStr):
                pre = _fprefix(n.right)
                return self._vars(m, {_add(b, pre) if pre else b for b in left})
            return self._vars(m, left)
        if isinstance(n, ast.Call):
            f = _fname(n.func)
            if any(isinstance(a, ast.Constant) and a.value in ROOT_ENV for a in n.args):
                return {""}
            if f in ("get", "getenv") and len(n.args) > 1:
                return self._eval(m, n.args[1], env)      # os.environ.get("PYTHIA_FREE", str(ROOT / "free"))
            if f in ("str", "fspath", "Path", "PurePath", "join", "joinpath"):
                args = list(n.args)
                if f == "joinpath" and isinstance(n.func, ast.Attribute):
                    args.insert(0, n.func.value)
                if not args:
                    return None
                cur = self._eval(m, args[0], env)
                if not cur:
                    return None
                for a in args[1:]:
                    if isinstance(a, ast.Constant) and isinstance(a.value, str):
                        cur = {_add(b, a.value) for b in cur}
                    else:
                        cur = self._vars(m, cur)
                return cur
            if isinstance(n.func, ast.Attribute) and n.func.attr in ("with_suffix", "with_name", "resolve", "absolute",
                                                                     "expanduser"):
                return self._eval(m, n.func.value, env)
            tgt = self._target(m, n.func)
            if tgt and (c := self.fx.get(tgt)) and c.ret:
                arg = _str_args(n)
                return {_extend(p, arg) for p in c.ret}
        return None

    def _fstring(self, m: Mod, n: ast.JoinedStr, env: dict) -> set[str] | None:
        vals = n.values
        if vals and isinstance(vals[0], ast.FormattedValue):
            root = self._eval(m, vals[0].value, env)
            rest = ast.JoinedStr(values=vals[1:])
            pre = _fprefix(rest)
            if not root or pre is None or not pre.startswith("/"):
                return None
            return {_add(b, pre) if len(vals) == 2 or not pre.strip("/") else _open(_add(b, pre)) for b in root}
        pre = _fprefix(n)
        if pre and "/" in pre.strip("/"):
            p = _const_path(pre.rstrip("/"))
            return {_open(p) if len(vals) > 1 else p} if p else None
        return None

    # ---------------------------------------------------------------- entries
    def module_effects(self, name: str) -> Effects:
        """What an entry does: every function of its module and the module level, with the calls followed, and the
        module level of every module of its own package it imports (what runs on import, a feature registry's paths)."""
        e = Effects()
        if name not in self.mods:
            return e
        pkg = name.rsplit(".", 1)[0] + "." if "." in name else name
        for mod in self.closure(name):
            if mod != name and not mod.startswith(pkg):
                continue        # a module far away runs its module level on import too, but registers, not reads
            m = self.mods[mod]
            self._scope(m, m.top, dict(self.menv[mod]), e)
        for f in self.mods[name].funcs:
            c = self.fx.get((name, f))
            if c:
                e.reads |= c.reads
                e.writes |= c.writes
        return e

    def closure(self, name: str) -> list[str]:
        seen, todo = [name], [name]
        while todo:
            m = self.mods[todo.pop()]
            for mod, attr in m.imports.values():
                dep = f"{mod}.{attr}" if attr and f"{mod}.{attr}" in self.mods else mod
                deps = [dep] + [dep.rsplit(".", k)[0] for k in range(1, dep.count(".") + 1)]   # and its packages
                for d in deps:
                    if d in self.mods and d not in seen:
                        seen.append(d)
                        todo.append(d)
        return seen


def _fname(f: ast.AST) -> str | None:
    return f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None


def _str_args(n: ast.Call) -> str:
    """The leading arguments of a call as a path, a variable as * ("binance_um", "premium" -> binance_um/premium,
    source, "book20" -> */book20)."""
    segs = []
    for a in n.args:
        if isinstance(a, ast.Constant) and isinstance(a.value, str) and SEG_RE.match(a.value):
            segs.append(a.value)
        elif isinstance(a, (ast.Name, ast.Attribute)):
            segs.append("*")
        else:
            break
    while segs and segs[-1] == "*":
        segs.pop()
    return "/".join(segs)


def _fprefix(n: ast.JoinedStr) -> str | None:
    """The constant text of an f-string up to its first placeholder."""
    out = ""
    for v in n.values:
        if isinstance(v, ast.Constant) and isinstance(v.value, str):
            out += v.value
        else:
            break
    return out


def _files(root: Path):
    if root.is_file():
        yield root
        return
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith("."))
        for f in sorted(files):
            p = Path(dirpath) / f
            if f.endswith(".py") and not (f.startswith("test_") or f == "conftest.py"):
                yield p
            elif p.suffix in TEXT_EXT and not re.search(r"\.(test|spec)\.|_tests?\.rs$", f):
                yield p


_QUOTED = re.compile(r"""["'`]([^"'`\n]{1,200})["'`]""")
_JOIN_ARGS = re.compile(r"""join\(([^()]*)\)""")
_VOLUME = re.compile(r"""\$\{?\w*data\w*\}?/([\w.=/-]+):/""", re.I)
_JOIN_CHAIN = re.compile(r"""(?:\.join\(\s*"[\w.=-]+"\s*\))+""")


def text_paths(text: str) -> set[str]:
    """String paths of a TypeScript, Rust or shell file: quoted paths, ${X}/a/b, join("a", "b"),
    .join("a").join("b"), a docker volume "$data/a:/x"."""
    out = set()
    for s in _QUOTED.findall(text):
        s = re.sub(r"^\$\{?\w+\}?/|^\$\{[^}]*\}/", "", s)
        cut = re.split(r"\$\{|\{", s)[0]
        p = _const_path(cut.rstrip("/"))
        if p:
            out.add(p if cut == s else _open(p))
    for args in _JOIN_ARGS.findall(text):
        segs = re.findall(r"""["']([\w.=-]+)["']""", args)
        if len(segs) >= 1 and "," in args:
            out.add("/".join(segs))
    for v in _VOLUME.findall(text):        # docker run -v "$data/models:/models"
        out.add(v.rstrip("/"))
    for chain in _JOIN_CHAIN.findall(text):
        out.add("/".join(re.findall(r'"([\w.=-]+)"', chain)))
    return out


# ---------------------------------------------------------------- the data folder

def walk_sizes(root: Path, now_s: float, depth: int) -> dict[str, list[int]]:
    """Folder path -> [bytes, bytes modified in 7 days, in 30 days], for every folder down to `depth` levels."""
    acc: dict[str, list[int]] = {}

    def rec(d: Path, rel: list[str]):
        try:
            it = list(os.scandir(d))
        except OSError:
            return
        for de in it:
            try:
                if de.is_symlink():
                    continue
                if de.is_dir(follow_symlinks=False):
                    if len(rel) < depth:
                        acc.setdefault("/".join(rel + [de.name]), [0, 0, 0])
                    rec(Path(de.path), rel + [de.name])
                    continue
                st = de.stat(follow_symlinks=False)
            except OSError:
                continue
            age = now_s - st.st_mtime
            for i in range(1, min(len(rel), depth) + 1):
                a = acc["/".join(rel[:i])]
                a[0] += st.st_size
                a[1] += st.st_size if age <= 7 * DAY_S else 0
                a[2] += st.st_size if age <= 30 * DAY_S else 0

    rec(root, [])
    return acc


def read_history(path: Path) -> list[dict]:
    out = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                h = json.loads(line)
            except ValueError:
                continue
            if isinstance(h, dict) and J._parse_iso(h.get("at")) and isinstance(h.get("sizes"), dict):
                out.append(h)
    except OSError:
        pass
    return out


def history_growth(hist: list[dict], name: str, days: int) -> tuple[float, float] | None:
    """(GB a day, days spanned) of a dataset over the window, from the disk history; None without a day of record."""
    have = [h for h in hist if name in h["sizes"]]
    if len(have) < 2:
        return None
    cur = have[-1]
    cur_at = J._parse_iso(cur["at"])
    base = next((h for h in have if (cur_at - J._parse_iso(h["at"])).total_seconds() <= days * DAY_S), None)
    if base is None:
        return None
    span = (cur_at - J._parse_iso(base["at"])).total_seconds() / DAY_S
    if span < 1:
        return None
    return (cur["sizes"][name] - base["sizes"][name]) / GB / span, round(span, 1)


# ---------------------------------------------------------------- the inventory

def rows_of(table: dict, data: Path, acc: dict[str, list[int]]) -> list[dict]:
    """Datasets of the table, the other top-level folders, and their parts."""
    ds = [{"name": d["name"], "path": str(d["path"]).strip("/"), "kind": "dataset",
           "description": d.get("description") or ""} for d in table.get("datasets") or [] if d.get("path")]
    paths = {d["path"] for d in ds}
    for top in sorted(p for p in acc if "/" not in p):
        if not any(p == top or p.startswith(top + "/") for p in paths):
            ds.append({"name": top, "path": top, "kind": "folder", "description": ""})
    kids: dict[str, int] = {}
    for p in acc:
        if "/" in p:
            kids[p.rsplit("/", 1)[0]] = kids.get(p.rsplit("/", 1)[0], 0) + 1
    out = []
    for d in ds:
        out.append({**d, "parent": None})
        for p in sorted(acc):
            rel = p[len(d["path"]) + 1:] if p.startswith(d["path"] + "/") else None
            if not rel or rel.count("/") >= PART_DEPTH or any(PART_SKIP_RE.search(s) for s in rel.split("/")):
                continue
            if kids.get(p.rsplit("/", 1)[0], 0) > PART_MAX_SIBLINGS:
                continue
            if any(q != d["path"] and (p == q or p.startswith(q + "/")) for q in paths):
                continue        # a dataset of its own (free/xstocks inside free)
            out.append({"name": f"{d['name']}/{rel}", "path": p, "kind": "part", "description": "",
                        "parent": d["name"]})
    return out


def entries(scan: Scanner, table: dict) -> list[dict]:
    """Every job, service and study with what its code reads and writes."""
    out, seen = [], set()
    by_base = {p.name: p for p in scan.texts}
    for j in table.get("jobs") or []:
        if j.get("enabled") is False:
            continue
        cmd = str(j.get("command") or "")
        e = Effects()
        mods = [f"{x}.__main__" if f"{x}.__main__" in scan.mods else x for x in re.findall(r"-m\s+([\w.]+)", cmd)]
        for mod in mods:
            seen.add(mod)
            x = scan.module_effects(mod)
            e.reads |= x.reads
            e.writes |= x.writes
        for tok in re.findall(r"[\w./-]+\.(?:py|sh)\b", cmd):
            base = Path(tok).name
            mod = next((n for n, m in scan.mods.items() if m.path.name == base), None)
            if mod and tok.endswith(".py"):
                seen.add(mod)
                x = scan.module_effects(mod)
                e.reads |= x.reads
                e.writes |= x.writes
            elif base in by_base:
                seen.add(str(by_base[base]))
                e.reads |= scan.texts[by_base[base]]
        book = j["name"].startswith("paper") or any(m.startswith("lab.paper.") for m in mods)
        out.append({"id": f"{'book' if book else 'job'}:{j['name']}", "kind": "book" if book else "job",
                    "reads": e.reads, "writes": e.writes,
                    "collector": "collect" in j["name"] or any(COLLECT_RE.search(m) for m in mods)})
    for name, mod in SERVICES.items():
        if mod in scan.mods:
            seen.add(mod)
            x = scan.module_effects(mod)
            out.append({"id": f"service:{name}", "kind": "service", "reads": x.reads, "writes": x.writes,
                        "collector": bool(COLLECT_RE.search(mod))})
    lab_pkgs = {"lab"}
    for name, m in sorted(scan.mods.items()):
        if name in seen:
            continue
        top = name.split(".")[0]
        outside = top not in lab_pkgs and _service_of(m.path) is not None
        if outside or m.runnable:
            x = scan.module_effects(name)
            if x.reads or x.writes:
                kind = "service" if outside else "study"
                ident = f"service:{_service_of(m.path)}:{name}" if outside else f"study:{name}"
                out.append({"id": ident, "kind": kind, "reads": x.reads, "writes": x.writes,
                            "collector": bool(COLLECT_RE.search(name))})
    for p, ps in sorted(scan.texts.items()):
        if str(p) in seen or not ps:
            continue
        out.append({"id": f"service:{_service_of(p) or 'code'}:{p.name}", "kind": "service", "reads": ps,
                    "writes": set(), "collector": False})
    return out


def _service_of(p: Path) -> str | None:
    """The part of the repo a file outside the lab package belongs to (recorder, discord, app, server, engine)."""
    parts = p.resolve().parts
    if "research" in parts:
        i = parts.index("research")
        sub = parts[i + 1] if len(parts) > i + 1 else None
        return None if sub in ("lab", None) else sub
    for key, label in (("src", "app"), ("server", "server"), ("crates", "engine"), ("src-tauri", "desktop"),
                       ("cli", "cli"), ("scripts", "scripts")):
        if key in parts:
            return label
    return None if LAB in p.resolve().parents else "ops"


def read_results(results: Path) -> dict[str, str]:
    out = {}
    for f in sorted(results.glob("*.md")) if results.is_dir() else []:
        if f.name.startswith(NAME):
            continue        # this inventory's own write-up names every folder; it is no study
        try:
            out[f.name] = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            pass
    return out


def last_study(texts: dict[str, str], path: str, studies: list[str], today: str) -> dict | None:
    """The newest results/*.md that names the path (as <data>/p, /data/p or `p`) or one of its reading studies."""
    pats = [(path, re.compile(r"(<data>/|/data/|`)" + re.escape(path) + r"(/|`|\b)"))]
    pats += [(s, re.compile(r"\b" + re.escape(s) + r"\b")) for s in studies]
    best = None
    for name, text in texts.items():
        if not any(key in text and p.search(text) for key, p in pats):
            continue
        head = [d for d in DATE_RE.findall("\n".join(text.splitlines()[:5])) if d <= today]
        alld = [d for d in DATE_RE.findall(text) if d <= today]
        day = head[0] if head else (max(alld) if alld else None)
        if day and (best is None or day > best["date"]):
            best = {"file": f"results/{name}", "date": day}
    return best


def build(now: datetime | None = None, data: Path | None = None, roots: list[Path] | None = None,
          table: dict | None = None, results: Path | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    data = data or notify.data_root()
    if table is None:
        table = J.parse_yaml(table_path().read_text(encoding="utf-8"))
    roots = roots or code_roots()
    results = results or results_dir()
    depth = max([str(d.get("path", "")).strip("/").count("/") + 1 for d in table.get("datasets") or []] + [1]) \
        + PART_DEPTH
    acc = walk_sizes(data, now.timestamp(), depth)
    scan = Scanner(roots, set(acc))
    ents = entries(scan, table)
    hist = read_history(data / "_ops" / "disk" / "history.jsonl")
    backup = [str(p).strip("/") for p in ((table.get("backup") or {}).get("include") or [])]
    today = now.strftime("%Y-%m-%d")
    texts = read_results(results)
    rows = []
    for r in rows_of(table, data, acc):
        size, b7, b30 = acc.get(r["path"], [0, 0, 0])
        g7 = history_growth(hist, r["name"], 7) if r["kind"] == "dataset" else None
        g30 = history_growth(hist, r["name"], 30) if r["kind"] == "dataset" else None
        upper = g7 is None and g30 is None
        if upper:
            g7, g30 = (b7 / GB / 7, 7.0), (b30 / GB / 30, 30.0)
        per_day = g7[0] if g7 else g30[0] if g30 else None
        writers = sorted(e["id"] for e in ents if any(matches(p, r["path"], scan.known) for p in e["writes"]))
        # a collector's reads of what it writes itself (its state, an append) are not reads
        readers = [e for e in ents if any(matches(p, r["path"], scan.known) for p in e["reads"])
                   and not (e["collector"] and e["id"] in writers)]
        if any(e["kind"] in ("job", "book", "service") for e in readers):
            verdict = VERDICTS[0]
        elif readers:
            verdict = VERDICTS[1]
        else:
            verdict = VERDICTS[2]
        studies = [e["id"].split(":", 1)[1] for e in readers if e["kind"] == "study"]
        last = last_study(texts, r["path"], studies, today)
        month = None if per_day is None else _sig(max(per_day, 0) * 30)
        row = {**r, "bytes": size, "gb": round(size / GB, 3),
               "growthGbPerDay": {"7d": None if not g7 else _sig(g7[0]), "30d": None if not g30 else _sig(g30[0]),
                                  "spanDays": {"7d": g7 and g7[1], "30d": g30 and g30[1]}, "upperBound": upper},
               "gbPerMonth": month, "writers": writers, "readers": sorted(e["id"] for e in readers),
               "verdict": verdict, "lastStudy": last}
        if verdict == VERDICTS[2]:
            row["proposal"], row["why"] = proposal(row, backup, today)
        rows.append(row)
    counts = {v: sum(1 for r in rows if r["kind"] != "part" and r["verdict"] == v) for v in VERDICTS}
    return {"at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "data": str(data), "code": [str(p) for p in roots],
            "repoScanned": any((p / "research" / "recorder").is_dir() or (p / "src").is_dir() for p in roots),
            "files": {"python": len(scan.mods), "text": len(scan.texts)}, "entries": len(ents),
            "historyFrom": hist[0]["at"] if hist else None, "counts": counts, "rows": rows,
            "nobodyGbPerMonth": round(sum(r["gbPerMonth"] or 0 for r in rows
                                          if r["kind"] != "part" and r["verdict"] == VERDICTS[2]), 3)}


def proposal(row: dict, backup: list[str], today: str) -> tuple[str, str]:
    """Keep, thin out or stop for a dataset nobody reads (the pre-registered order)."""
    p = row["path"]
    if any(p == b or p.startswith(b + "/") or b.startswith(p + "/") for b in backup):
        return "keep", "in the backup (state that cannot be rebuilt)"
    month = row["gbPerMonth"]
    if month is None or month < KEEP_GB_MONTH:
        return "keep", f"costs {'an unknown amount' if month is None else f'{month:.2f} GB'} a month"
    last = row.get("lastStudy")
    if last:
        age = (datetime.strptime(today, "%Y-%m-%d") - datetime.strptime(last["date"], "%Y-%m-%d")).days
        if age <= RECENT_DAYS:
            return "keep", f"{last['file']} used it {age} days ago"
        return "thin out", f"{last['file']} used it {age} days ago"
    return "stop", f"{month:.2f} GB a month and no study ever used it"


# ---------------------------------------------------------------- the report

def _sig(x: float) -> float:
    return float(f"{x:.4g}")


def _gb(v) -> str:
    return "-" if v is None else f"{v:,.2f}"


def _list(xs: list[str], n: int = 4) -> str:
    if not xs:
        return "-"
    return ", ".join(xs[:n]) + (f" and {len(xs) - n} more" if len(xs) > n else "")


def markdown(d: dict) -> str:
    L = [f"# Recordings: who reads what the lab records ({d['at'][:10]})", "",
         "T13 (`results/recordings_t13_prereg.md`). One row per dataset of jobs.yaml and per other folder of the data "
         "root, with its parts. Writers and readers by a static scan of the code for the path and its loaders; "
         "growth from the disk history (≤: from file times, an upper bound). No trial; it stops nothing.", "",
         f"Code scanned: {', '.join(d['code'])} ({d['files']['python']} Python, {d['files']['text']} other files, "
         f"{d['entries']} jobs, services and studies). Disk history from {d['historyFrom'] or '-'}."]
    if not d["repoScanned"]:
        L.append("Only the lab and ops code was scanned: what the app, server, engine and recorder read is missing "
                 "(PYTHIA_RECORDINGS_CODE).")
    L += ["", " · ".join(f"{v}: {n}" for v, n in d["counts"].items()) +
          f" · read by nobody costs {_gb(d['nobodyGbPerMonth'])} GB a month", "",
          "| dataset | path | GB | GB a day 7d / 30d | GB a month | verdict | written by | read by | last study "
          "| proposal |",
          "|---|---|--:|--:|--:|---|---|---|---|---|"]
    for r in d["rows"]:
        if r["kind"] == "part" and r["bytes"] < PART_MD_MB * 1024 ** 2:
            continue
        g = r["growthGbPerDay"]
        mark = "≤ " if g["upperBound"] else ""
        span = g["spanDays"].get("30d")
        g30 = _gb(g["30d"]) + (f" ({span:g} d)" if span and not g["upperBound"] and span < 29 else "")
        last = r["lastStudy"]
        name = f"· {r['name']}" if r["kind"] == "part" else f"**{r['name']}**" if r["kind"] == "dataset" else r["name"]
        L.append(f"| {name} | {r['path']} | {_gb(r['gb'])} | {mark}{_gb(g['7d'])} / {g30} "
                 f"| {mark}{_gb(r['gbPerMonth'])} "
                 f"| {r['verdict']} | {_list(r['writers'], 2)} | {_list(r['readers'])} "
                 f"| {last['file'][8:] + ' ' + last['date'] if last else '-'} "
                 f"| {r.get('proposal', '')}{': ' + r['why'] if r.get('why') else ''} |")
    return "\n".join(L) + "\n"


def publish(d: dict) -> None:
    notify.write_json(out_dir() / "latest.json", d)
    (out_dir() / "latest.md").write_text(markdown(d), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    t0 = time.time()
    d = build()
    if "--print" in argv:
        notify.say(markdown(d))
        return 0
    publish(d)
    notify.say(f"recordings: {len(d['rows'])} rows, {d['counts']}, nobody {d['nobodyGbPerMonth']} GB a month, "
               f"{time.time() - t0:.0f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
