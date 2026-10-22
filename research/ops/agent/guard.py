"""May the research agent's branch go live without the owner looking at it?

    python3 guard.py <repo> <base-rev> <branch-rev>

Prints one reason per line and exits 1 when the branch needs the owner, 0 when
it may be merged and deployed by run_agent.sh. The agent works on research and
paper books; it may not change what trades real money, what runs as root on the
host, or what the engines and the app are built from. So a branch is held back
when it

- touches a protected path: the engines and the app (crates/, server/, src/,
  src-tauri/), the build and CI files, the host scripts and the job runner
  (research/ops/ except jobs.yaml, research/lab/lab/ops/jobs.py), the pump.fun
  live executor and wallet code, the safety and security documents;
- changes the job table in a way that reaches beyond the lab container: a host
  job, an image other than the lab's, extra volumes, env files or a network,
  or a change to the table's paths, defaults, datasets or backup sections;
- is not a fast-forward of the base (the agent has to rebase first).

Standard library only, next to jobs.py, whose parser it uses.
"""

from __future__ import annotations

import fnmatch
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import jobs  # noqa: E402  (installed next to this folder as /opt/pythia-ops/jobs.py)

PROTECTED = [
    "crates/*", "server/*", "src/*", "src-tauri/*", "cli/*", "scripts/*", ".github/*",
    "package.json", "package-lock.json", "Cargo.toml", "Cargo.lock", "vite.config.*", "index.html",
    "research/ops/*.sh", "research/ops/agent/*", "research/ops/README.md",
    "research/lab/lab/ops/jobs.py", "research/lab/Dockerfile", "research/lab/requirements.txt",
    "research/lab/lab/pumpfun_rt/live_exec.py", "research/lab/lab/pumpfun_rt/live_service.py",
    "research/lab/lab/pumpfun_rt/live.py", "research/lab/lab/pumpfun_rt/txbuild.py",
    "research/lab/lab/pumpfun_rt/wallet.py", "research/lab/lab/pumpfun_rt/fastpath.py",
    "research/recorder/*", "SAFETY.md", "SECURITY.md", "docs/PUMPFUN-LIVE.md", "docs/security/*",
    ".gitignore", ".gitleaks.toml", ".env.example",
]
LAB_IMAGE = "pythia-lab"
TABLE = "research/ops/jobs.yaml"


def git(repo: str, *args: str) -> str:
    return subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True, text=True).stdout


def table_at(repo: str, rev: str) -> jobs.Table:
    return jobs.Table(jobs.parse_yaml(git(repo, "show", f"{rev}:{TABLE}")), f"{rev}:{TABLE}")


def reach(job: dict) -> tuple:
    """What a job can touch beyond the lab container."""
    return (job["kind"], job.get("image"), tuple(job["volumes"]), tuple(job["env_files"]), job.get("network"),
            job.get("code"))


def table_problems(old: jobs.Table, new: jobs.Table) -> list[str]:
    out = []
    for section in ("paths", "defaults", "datasets", "backup"):
        if old.raw.get(section) != new.raw.get(section):
            out.append(f"the job table's {section} section changed")
    for name, before in old.jobs.items():
        sensitive = before["kind"] == "host" or before["volumes"] or before["env_files"] or before.get("network")
        if sensitive and new.jobs.get(name) != before:
            out.append(f"job {name}: it reaches beyond the lab container, so the agent may not change or remove it")
    for name, job in new.jobs.items():
        before = old.jobs.get(name)
        if before is not None and reach(before) == reach(job):
            continue
        if job["kind"] == "host":
            out.append(f"job {name}: a host job is new or changed")
        if job.get("image") not in (None, LAB_IMAGE):
            out.append(f"job {name}: image {job.get('image')!r} is not the lab image")
        if job["volumes"] or job["env_files"] or job.get("network"):
            out.append(f"job {name}: new or changed volumes, env files or network")
    return out


def problems(repo: str, base: str, head: str) -> list[str]:
    out = []
    if git(repo, "merge-base", base, head).strip() != git(repo, "rev-parse", base).strip():
        return ["the branch is not based on the current main (rebase it)"]
    changed = [p for p in git(repo, "diff", "--name-only", base, head).splitlines() if p]
    for p in changed:
        if any(fnmatch.fnmatch(p, pat) for pat in PROTECTED):
            out.append(f"protected path: {p}")
    if TABLE in changed:
        try:
            out += table_problems(table_at(repo, base), table_at(repo, head))
        except jobs.TableError as e:
            out.append(f"the job table does not load: {e}")
    return out


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__.strip().splitlines()[2].strip())
        return 2
    found = problems(*argv)
    for p in found:
        print(p)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
