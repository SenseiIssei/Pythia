"""May the research agent's round go live without the owner looking at it?

    python3 guard.py <repo> <base-rev> <head-rev> --owner-name NAME --owner-email MAIL [--patterns FILE]
    python3 guard.py --closure <repo> <rev>     what the agent may not change because real money or a job
                                                 with secrets, the host network or extra volumes runs it

Prints one reason per line and exits 1 when the round is held for the owner, 0
when run_agent.sh may push, merge and deploy it (2 on wrong usage). A reason
names a path, a line number and a kind, never the private value itself.

The rule is an ALLOW list. A round may change only

    research/lab/lab/experiments/**   research/lab/lab/paper/**   research/lab/lab/factory/**
    research/lab/lab/collect/**       research/lab/results/**     research/lab/tests/**
    research/lab/proposals/**         research/lab/README.md      research/ops/jobs.yaml (job rules)

and inside those never

- lab/paper/live_copy.py and lab/paper/families.py (the live twin and the book it copies),
- a module that real money or a job with secrets runs: the import closure (computed
  here from the code at <head>, see `closure`) of every module in lab/pumpfun_rt,
  lab/ops and lab/ai, of live_copy and families, and of the command of every job of
  the base table that is not a plain lab job (env file, network, volumes, own image,
  host kind, no code mount), including the package __init__.py files on the way,
- the results files the families job reads (FAMILIES_READS),
- a .gitattributes, .gitignore, .gitmodules, gitleaks file, sitecustomize, *.pth.

Everything else holds the round, and so does:

- a file that is a symlink or a submodule, over 1 MB, binary (a NUL byte or not
  UTF-8), or named like live data or a secret (orders.jsonl, ledger.csv,
  measured.jsonl, state.json, *.env, *keypair*, ...);
- an added line, a file name or a commit message that looks private: a public
  IPv4 or IPv6 address, an e-mail address (also with %40 or (at)), a key or
  token, an api-key value, any PEM BEGIN line, a 64-number key array (also across
  lines), a base58 string of 64 to 88 characters (a Solana secret), a Windows or
  /home or /Users path with a person's name, or one of the owner's own patterns
  (domain, panel path, wallet address, e-mail) from the root-only patterns file;
- an added line with an allow marker (gitleaks:allow, secret-scan:allow), an em
  dash, or a commit message naming an assistant or carrying an attribution line;
- a commit whose author or committer is not the owner's identity;
- a head that does not descend from the base;
- a job table change outside the job rules (`table_problems`).

The diff is read with --text --no-renames --no-ext-diff --no-textconv, so no
attribute can hide a line and no rename can hide a protected path.

Standard library only, next to jobs.py, whose parser it uses.
"""

from __future__ import annotations

import ast
import ipaddress
import os
import re
import subprocess
import sys
from pathlib import Path

_here = Path(__file__).resolve().parent
for _p in (_here.parent, _here.parent.parent / "lab" / "lab" / "ops"):  # /opt/pythia-ops, or the repo
    if (_p / "jobs.py").is_file():
        sys.path.insert(0, str(_p))
        break
import jobs  # noqa: E402

LAB = "research/lab/lab/"
ALLOW_DIRS = (
    "research/lab/lab/experiments/", "research/lab/lab/paper/", "research/lab/lab/factory/",
    "research/lab/lab/collect/", "research/lab/results/", "research/lab/tests/", "research/lab/proposals/",
)
ALLOW_FILES = ("research/lab/README.md", "research/ops/jobs.yaml")
NEVER = {"research/lab/lab/paper/live_copy.py", "research/lab/lab/paper/families.py"}
# Results the families job reads when the sweep's JSON is missing (lab/paper/families.py):
# they shape the book the live twin copies.
FAMILIES_READS = re.compile(r"research/lab/results/(families_summary|family_[a-z0-9_]+|tsmom_tranches)\.md")
NEVER_NAMES = re.compile(r"(^|/)(\.gitattributes|\.gitignore|\.gitmodules|\.gitleaks\.toml|\.gitleaksignore|"
                         r"sitecustomize\.py|usercustomize\.py|[^/]*\.pth)$")
LIVE_DATA_NAMES = re.compile(r"(^|/)(orders\.jsonl|ledger\.csv|measured\.jsonl|state\.json|totals\.json|open\.json|"
                             r"simulate\.json|[^/]*\.env|\.env[^/]*|[^/]*keypair[^/]*|[^/]*\.pem|[^/]*\.key|id_rsa[^/]*|"
                             r"id_ed25519[^/]*|[^/]*\.p12|[^/]*\.pfx)$", re.I)
ROOT_PACKAGES = ("lab.pumpfun_rt", "lab.ops", "lab.ai")
ROOT_MODULES = ("lab.paper.live_copy", "lab.paper.families")
MAX_BYTES = 1_000_000
TABLE = "research/ops/jobs.yaml"
LAB_IMAGE = "pythia-lab"
PATTERNS_FILE = "/root/pythia-agent-secrets/private-patterns.txt"

# ---------------------------------------------------------------- private lines

_OK_IPS = {"1.1.1.1", "8.8.8.8"}       # public resolvers, not anyone's server (as the pre-commit hook)
_IPV4 = re.compile(r"(?<![0-9.])((?:25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9])"
                   r"(?:\.(?:25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9])){3})(?![0-9]|\.[0-9])")
_IPV6 = re.compile(r"(?<![0-9A-Za-z:.])((?:[0-9A-Fa-f]{0,4}:){2,7}[0-9A-Fa-f]{0,4})(?![0-9A-Za-z:])")
_EMAIL = re.compile(r"([A-Za-z0-9._%+-]+?)(?:@|%40|&#64;|\s?[\[(]at[\])]\s?)([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,})",
                    re.I)
_EMAIL_OK = re.compile(r"^(?:example\.(?:com|org|net)|[a-z0-9-]+\.example\.(?:com|org|net)|[0-9]+x\.(?:png|jpe?g|webp|gif))$",
                       re.I)
_TOKENS = re.compile(r"sk-ant-[A-Za-z0-9_-]{16,}|sk-(?:proj-)?[A-Za-z0-9]{32,}|gh[pousr]_[A-Za-z0-9]{30,}|"
                     r"github_pat_[A-Za-z0-9_]{20,}|xox[abprs]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16}|"
                     r"[0-9]{8,10}:AA[A-Za-z0-9_-]{30,}")
_API_KEY = re.compile(r"""(?i)\b[a-z0-9_]*api[_-]?key\b["']?\s*[:=]\s*(?:"[^"\s]{12,}"|'[^'\s]{12,}'|[A-Za-z0-9_\-+/=]{16,})""")
_PEM = re.compile(r"-----BEGIN [A-Z0-9 ]+-----")
_KEY_ARRAY = re.compile(r"[\[(]\s*(?:[0-9]{1,3}\s*,\s*){63}[0-9]{1,3}\s*,?\s*[\])]")
_B58 = re.compile(r"(?<![1-9A-HJ-NP-Za-km-z])[1-9A-HJ-NP-Za-km-z]{64,88}(?![1-9A-HJ-NP-Za-km-z])")
_WIN_USER = re.compile(r"(?i)(?:\b[a-z]:|/mnt/[a-z])[\\/]+users[\\/]+([^\\/\s\"'`]+)")
_HOME = re.compile(r"(?<![\w.~-])/(?:home|Users)/([A-Za-z_][A-Za-z0-9._-]*)")
_PLACEHOLDER_USERS = {"user", "users", "you", "yourname", "username", "name", "example", "public", "default",
                      "shared", "runner", "agent", "guides", "ubuntu", "admin", "all users", "default user"}
_MARKERS = re.compile(r"(?i)gitleaks:allow|secret-scan:allow")
_ATTRIBUTION = re.compile(r"(?i)co-authored-by|claude|anthropic")
EM_DASH = chr(0x2014)


def load_patterns(path: str) -> list[re.Pattern]:
    """The owner's own patterns, one a line: a literal (case-insensitive) or `re:<regex>`; `#` comments."""
    out = []
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            out.append(re.compile(line[3:], re.I) if line.startswith("re:") else re.compile(re.escape(line), re.I))
    if not out:
        raise ValueError("no pattern in it")
    return out


def _ipv6_hit(s: str) -> bool:
    groups = s.split(":")
    if not any(len(g) >= 3 for g in groups) or sum(len(g) for g in groups) < 4 or not any(c.isdigit() for c in s):
        return False
    try:
        return ipaddress.IPv6Address(s).is_global
    except ValueError:
        return False


def _user_ok(name: str) -> bool:
    n = name.strip().lower()
    return n in _PLACEHOLDER_USERS or n[:1] in "<%$({["


def private_kinds(text: str, owner: list[re.Pattern] | None = None) -> list[str]:
    """What in `text` looks private, by kind; never the value."""
    kinds = []
    for m in _IPV4.finditer(text):
        ip = m.group(1)
        if ip not in _OK_IPS and ipaddress.IPv4Address(ip).is_global:
            kinds.append("public IP address")
            break
    if any(_ipv6_hit(m.group(1)) for m in _IPV6.finditer(text)):
        kinds.append("public IPv6 address")
    for m in _EMAIL.finditer(text):
        dom = m.group(2)
        if not _EMAIL_OK.match(dom) and not (m.group(1).lower() == "git" and dom.lower() == "github.com"):
            kinds.append("e-mail address")
            break
    if _TOKENS.search(text):
        kinds.append("key or token")
    if _API_KEY.search(text):
        kinds.append("api key value")
    if _PEM.search(text):
        kinds.append("PEM block")
    if _KEY_ARRAY.search(text):
        kinds.append("64-number key array")
    for m in _B58.finditer(text):
        s = m.group(0)
        if any(c.isupper() for c in s) and any(c.islower() for c in s) and any(c.isdigit() for c in s):
            kinds.append("base58 secret")
            break
    if any(not _user_ok(m.group(1)) for m in _WIN_USER.finditer(text)):
        kinds.append("personal Windows path")
    if any(not _user_ok(m.group(1)) for m in _HOME.finditer(text)):
        kinds.append("personal home path")
    if owner and any(p.search(text) for p in owner):
        kinds.append("one of the owner's private patterns")
    return kinds


# ---------------------------------------------------------------- git

def git(repo: str, *args: str, binary: bool = False):
    r = subprocess.run(["git", "-c", "core.quotePath=false", "-C", repo, *args], check=True, capture_output=True)
    return r.stdout if binary else r.stdout.decode("utf-8", "replace")


def blobs(repo: str, specs: list[str]) -> dict[str, bytes | None]:
    """`git cat-file --batch` for many `<rev>:<path>` at once; None when missing."""
    if not specs:
        return {}
    r = subprocess.run(["git", "-C", repo, "cat-file", "--batch"], input="".join(s + "\n" for s in specs).encode(),
                       capture_output=True, check=True)
    out, data, i = {}, r.stdout, 0
    for spec in specs:
        nl = data.index(b"\n", i)
        head = data[i:nl].split()
        i = nl + 1
        if len(head) < 3 or head[1] == b"missing":
            out[spec] = None
            continue
        size = int(head[2])
        out[spec] = data[i:i + size]
        i += size + 1
    return out


def changes(repo: str, base: str, head: str) -> list[tuple[str, str, str, str]]:
    """(status, old mode, new mode, path) per changed path, renames split into a delete and an add."""
    raw = git(repo, "diff", "--raw", "-z", "--no-renames", "--no-abbrev", "--no-ext-diff", base, head, binary=True)
    parts = raw.split(b"\0")
    out, i = [], 0
    while i < len(parts) - 1:
        meta = parts[i].decode()
        path = parts[i + 1].decode("utf-8", "replace")
        i += 2
        f = meta.lstrip(":").split()
        out.append((f[4][0], f[0], f[1], path))
    return out


def added_lines(repo: str, base: str, head: str, path: str) -> list[tuple[int, str]]:
    """(line number in the new file, text) of every added line, no attribute or driver in the way."""
    diff = git(repo, "diff", "--text", "--no-renames", "--no-ext-diff", "--no-textconv", "--no-color", "-U0",
               base, head, "--", f":(literal){path}")
    out, n = [], 0
    for line in diff.splitlines():
        if line.startswith("@@"):
            m = re.match(r"@@ -\S+ \+(\d+)", line)
            n = int(m.group(1)) if m else 0
        elif line.startswith("+") and not line.startswith("+++"):
            out.append((n, line[1:]))
            n += 1
    return out


# ---------------------------------------------------------------- what real money or a secret runs

def lab_modules(repo: str, rev: str) -> dict[str, str]:
    """Module name -> repo path of every lab module at `rev`."""
    out = {}
    for p in git(repo, "ls-tree", "-r", "-z", "--name-only", rev, "--", LAB.rstrip("/")).split("\0"):
        if p.endswith(".py"):
            parts = p[len("research/lab/"):-3].split("/")
            if parts[-1] == "__init__":
                parts = parts[:-1]
            out[".".join(parts)] = p
    return out


def _imports(name: str, path: str, src: bytes, modules: dict[str, str]) -> set[str]:
    try:
        tree = ast.parse(src)
    except (SyntaxError, ValueError):
        return set()
    pkg = name if path.endswith("__init__.py") else name.rpartition(".")[0]
    found: set[str] = set()

    def add(mod: str) -> None:
        while mod.startswith("lab"):
            if mod in modules:
                found.add(mod)
            mod = mod.rpartition(".")[0]

    def prefix(mod: str) -> None:
        for m in modules:
            if m.startswith(mod):
                add(m)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                add(a.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                parts = pkg.split(".")
                base = ".".join(parts[:len(parts) - (node.level - 1)])
                mod = f"{base}.{node.module}" if node.module else base
            else:
                mod = node.module or ""
            add(mod)
            for a in node.names:
                add(f"{mod}.{a.name}")
        elif isinstance(node, ast.Call) and node.args:
            fn = node.func
            fname = fn.attr if isinstance(fn, ast.Attribute) else fn.id if isinstance(fn, ast.Name) else ""
            if fname not in ("import_module", "__import__"):
                continue
            arg = node.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                add(arg.value)
            elif isinstance(arg, ast.JoinedStr):
                lead = ""
                for v in arg.values:
                    if isinstance(v, ast.Constant):
                        lead += str(v.value)
                    elif (isinstance(v, ast.FormattedValue) and isinstance(v.value, ast.Name)
                          and v.value.id == "__package__"):
                        lead += pkg
                    else:
                        break
                if lead.startswith("lab"):
                    prefix(lead)
    return found


def job_modules(command: str) -> list[str]:
    return re.findall(r"-m\s+(lab(?:\.[A-Za-z0-9_]+)+)", command)


def sensitive(raw_job: dict, job: dict) -> bool:
    """A job that reaches beyond a plain lab container: secrets, the host network, volumes, its own image."""
    return bool(job["kind"] != "lab" or "image" in raw_job or "code" in raw_job or job["volumes"]
                or job["env_files"] or job.get("network") or job["name"] in UNCHANGEABLE_JOBS)


def closure(repo: str, rev: str, table: jobs.Table | None) -> dict[str, str]:
    """Every lab module real money or a sensitive job runs, at `rev`, with the root that pulls it in."""
    modules = lab_modules(repo, rev)
    src = blobs(repo, [f"{rev}:{p}" for p in modules.values()])
    roots = {m: "itself" for m in modules if m.startswith(tuple(p + "." for p in ROOT_PACKAGES)) or m in ROOT_PACKAGES}
    for m in ROOT_MODULES:
        roots[m] = "the live twin"
    if table is not None:
        for name, job in table.jobs.items():
            raw = next(j for j in table.raw.get("jobs") or [] if str(j.get("name")) == name)
            if sensitive(raw, job):
                for m in job_modules(job["command"]):
                    roots.setdefault(m, f"job {name}")
                    roots.setdefault(f"{m}.__main__", f"job {name}")      # python -m <package>
    roots = {m: w for m, w in roots.items() if m in modules}
    why: dict[str, str] = {}
    todo = []
    for m, w in roots.items():
        for p in [m] + [m.rsplit(".", k)[0] for k in range(1, m.count("."))]:
            if p in modules and p not in why:
                why[p] = w if p == m else f"{w} (its package)"
                todo.append(p)
    while todo:
        m = todo.pop()
        for d in _imports(m, modules[m], src.get(f"{rev}:{modules[m]}") or b"", modules):
            if d not in why:
                why[d] = f"{m}"
                todo.append(d)
    return {modules[m]: w for m, w in why.items()}


def allowed(path: str) -> bool:
    return path in ALLOW_FILES or path.startswith(ALLOW_DIRS)


def excluded(path: str, held: dict[str, str]) -> str | None:
    """Why an allowed path is still off limits, or None."""
    if path in NEVER:
        return "the live twin's code"
    if FAMILIES_READS.fullmatch(path):
        return "a result the families job reads"
    if NEVER_NAMES.search(path):
        return "a git, scanner or interpreter control file"
    if path in held:
        return f"real money or a job with secrets runs it (via {held[path]})"
    return None


# ---------------------------------------------------------------- the job table

UNCHANGEABLE_JOBS = {"paper-live-copy", "paper-families"}
NEW_JOB_KEYS = {"name", "description", "schedule", "command", "resources", "timeout", "grace", "lock", "lock_wait",
                "depends_on", "depends_within", "enabled", "env", "alert"}
PLAIN_COMMAND = re.compile(r"python -m (lab(?:\.[a-z0-9_]+)+)(?: [A-Za-z0-9_.,=:-]+)*")
ENV_KEY = re.compile(r"PYTHIA_(?!PUMPFUN)[A-Z0-9_]+")
SHARED_LOCK = "heavy"


def table_at(repo: str, rev: str) -> jobs.Table:
    return jobs.Table(jobs.parse_yaml(git(repo, "show", f"{rev}:{TABLE}")), f"{rev}:{TABLE}")


def table_problems(old: jobs.Table, new: jobs.Table, held: dict[str, str], existing: set[str]) -> list[str]:
    out = []
    for section in sorted((set(old.raw) | set(new.raw)) - {"jobs"}):
        if old.raw.get(section) != new.raw.get(section):
            out.append(f"the job table's {section} section changed")
    old_raw = {str(j.get("name")): j for j in old.raw.get("jobs") or []}
    new_raw = {str(j.get("name")): j for j in new.raw.get("jobs") or []}
    taken = set(old.jobs) | {lk for j in old.jobs.values() for lk in j["locks"]}
    for name, job in old.jobs.items():
        if sensitive(old_raw[name], job) and new_raw.get(name) != old_raw[name]:
            out.append(f"job {name}: real money, a secret, the host network or a volume, so the agent may not "
                       "change or remove it")
    for name, raw in new_raw.items():
        if name in old_raw and raw == old_raw[name]:
            continue
        if name in old.jobs and sensitive(old_raw[name], old.jobs[name]):
            continue                                            # reported above
        job = new.jobs[name]
        extra = set(raw) - NEW_JOB_KEYS
        if extra:
            out.append(f"job {name}: {', '.join(sorted(extra))} may not be set by the agent")
        if name not in old_raw or raw.get("command") != old_raw[name].get("command"):
            m = PLAIN_COMMAND.fullmatch(str(raw.get("command") or ""))
            if not m:
                out.append(f"job {name}: the command is not of the form python -m lab.<module> [args]")
            else:
                path = f"research/lab/{m.group(1).replace('.', '/')}"
                cands = [f"{path}.py", f"{path}/__main__.py", f"{path}/__init__.py"]
                if not any(c in existing and allowed(c) and not excluded(c, held) for c in cands):
                    out.append(f"job {name}: {m.group(1)} is not a module the agent may run as a job")
        for k in (job["env"] or {}):
            if not ENV_KEY.fullmatch(k):
                out.append(f"job {name}: environment variable {k} may not be set by the agent")
        for lk in job["locks"]:
            if lk not in (name, SHARED_LOCK) and lk in (taken | set(new.jobs)) - {name}:
                out.append(f"job {name}: lock {lk} belongs to another job")
    return out


# ---------------------------------------------------------------- the round

def problems(repo: str, base: str, head: str, owner_name: str, owner_email: str,
             owner: list[re.Pattern] | None) -> list[str]:
    try:
        if git(repo, "merge-base", base, head).strip() != git(repo, "rev-parse", f"{base}^{{commit}}").strip():
            return ["the round does not descend from the base (main moved or history was rewritten)"]
    except subprocess.CalledProcessError:
        return ["the round does not descend from the base"]
    out: list[str] = []
    if owner is None:
        out.append("the owner's private patterns file is missing, unreadable or empty, so nothing goes out")
    try:
        base_table = table_at(repo, base)
    except (subprocess.CalledProcessError, jobs.TableError) as e:
        base_table = None
        out.append(f"the base job table does not load: {e}")
    # At the base and at the head, so neither an edit nor a new file can step out of it.
    held = {**closure(repo, head, base_table), **closure(repo, base, base_table)}

    # who
    for line in git(repo, "log", "--format=%an%x1f%ae%x1f%cn%x1f%ce%x1f%h", f"{base}..{head}").splitlines():
        an, ae, cn, ce, h = line.split("\x1f")
        if (an, ae.lower()) != (owner_name, owner_email.lower()) or (cn, ce.lower()) != (owner_name, owner_email.lower()):
            out.append(f"commit {h}: author or committer is not the owner's identity")

    # what
    changed = changes(repo, base, head)
    texts = blobs(repo, [f"{head}:{p}" for st, _, _, p in changed if st != "D"])
    for st, old_mode, new_mode, path in changed:
        kinds = private_kinds(path, owner)
        label = "a file name that looks private" if kinds else path
        if kinds:
            out.append(f"{label} ({', '.join(kinds)})")
        if not allowed(path):
            out.append(f"outside what the agent may change: {label}")
        else:
            why = excluded(path, held)
            if why:
                out.append(f"off limits ({why}): {label}")
        if st == "D":
            continue
        if new_mode in ("120000", "160000"):
            out.append(f"a symlink or submodule: {label}")
            continue
        if LIVE_DATA_NAMES.search(path):
            out.append(f"named like live data or a secret: {label}")
        data = texts.get(f"{head}:{path}") or b""
        if len(data) > MAX_BYTES:
            out.append(f"over 1 MB: {label}")
            continue
        try:
            if b"\0" in data:
                raise UnicodeDecodeError("utf-8", data, 0, 1, "NUL byte")
            data.decode("utf-8")
        except UnicodeDecodeError:
            out.append(f"a binary file: {label}")
            continue
        lines = added_lines(repo, base, head, path)
        for n, text in lines:
            for k in private_kinds(text, owner):
                out.append(f"{label}:{n}: an added line looks private ({k})")
            if _MARKERS.search(text):
                out.append(f"{label}:{n}: an allow marker for the secret scan")
            if EM_DASH in text:
                out.append(f"{label}:{n}: an em dash")
        joined = "\n".join(t for _, t in lines)
        if _KEY_ARRAY.search(joined) and not any("64-number" in o and o.startswith(f"{label}:") for o in out):
            out.append(f"{label}: added lines hold a 64-number key array")

    # why
    for line in git(repo, "log", "--format=%h%x1f%B%x1e", f"{base}..{head}").split("\x1e"):
        if not line.strip():
            continue
        h, _, msg = line.strip().partition("\x1f")
        if _ATTRIBUTION.search(msg):
            out.append(f"commit {h}: the message names an assistant or carries an attribution line")
        if EM_DASH in msg:
            out.append(f"commit {h}: an em dash in the message")
        for k in private_kinds(msg, owner):
            out.append(f"commit {h}: the message looks private ({k})")

    if TABLE in {p for _, _, _, p in changed} and base_table is not None:
        try:
            out += table_problems(base_table, table_at(repo, head), held, set(lab_modules(repo, head).values()))
        except (subprocess.CalledProcessError, jobs.TableError) as e:
            out.append(f"the job table does not load: {e}")
    return list(dict.fromkeys(out))


def main(argv: list[str]) -> int:
    import argparse
    ap = argparse.ArgumentParser(usage=__doc__.strip().splitlines()[2].strip())
    ap.add_argument("--closure", action="store_true")
    ap.add_argument("repo")
    ap.add_argument("base")
    ap.add_argument("head", nargs="?")
    ap.add_argument("--owner-name", default=os.environ.get("PYTHIA_AGENT_GIT_NAME", "SenseiIssei"))
    ap.add_argument("--owner-email", default=os.environ.get("PYTHIA_AGENT_GIT_EMAIL", ""))
    ap.add_argument("--patterns", default=os.environ.get("PYTHIA_AGENT_PRIVATE_PATTERNS", PATTERNS_FILE))
    try:
        a = ap.parse_args(argv)
    except SystemExit:
        return 2
    if a.closure:
        held = closure(a.repo, a.base, table_at(a.repo, a.base))
        for path in sorted(p for p in held if allowed(p)):
            print(f"{path}  <- {held[path]}")
        return 0
    if not a.head or not a.owner_email:
        print("usage: guard.py <repo> <base> <head> --owner-email MAIL (or PYTHIA_AGENT_GIT_EMAIL)")
        return 2
    try:
        owner = load_patterns(a.patterns)
    except (OSError, ValueError):
        owner = None
    found = problems(a.repo, a.base, a.head, a.owner_name, a.owner_email, owner)
    for p in found:
        print(p)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
