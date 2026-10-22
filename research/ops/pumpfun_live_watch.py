#!/usr/bin/env python3
"""Watches the pump.fun live service every two minutes and tells the owner at once when it is not
trading as it should. Standard library only; runs on the host as the job "pumpfun-live-watch".

It reads what the service writes (reports/pumpfun_rt/live_status.json) and asks docker whether the
container runs. Problems, each posted once when it starts and once an hour while it lasts, and a
"fine again" when all are gone (Telegram, through notify.py, category risk):
  - the container pythia-pumpfun-live is not running
  - its status is older than STALE_S (the service hangs or its stream is dead)
  - the service is running but not trading, with its reason (the gate, a stop, the kill switch)
  - the last dry run (the 24 h test gate) failed or is older than SIM_WARN_H
  - positions from before a restart wait to be sold, or one is stuck
It never restarts, stops or changes anything; its only file is its own state.

    python3 pumpfun_live_watch.py [--data /srv/pythia-data] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

CONTAINER = "pythia-pumpfun-live"
STALE_S = 180
SIM_WARN_H = 20
REPEAT_S = 3600
ALERT_ENV = Path("/etc/pythia/alerts.env")
NOTIFY = Path(__file__).with_name("notify.py")


def container_running(name: str = CONTAINER) -> bool | None:
    """True or False from docker; None when docker cannot be asked."""
    try:
        r = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}", name], capture_output=True, text=True,
                           timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return False
    return r.stdout.strip() == "true"


def problems(status: dict | None, running: bool | None, now: float) -> dict[str, str]:
    """{key: German text} of everything wrong right now; empty when the bot trades as it should."""
    out: dict[str, str] = {}
    if running is False:
        out["down"] = "Der Live-Bot (Container) läuft nicht. Offene Positionen werden gerade nicht verwaltet."
    if status is None:
        out.setdefault("status", "Kein Status vom Live-Bot lesbar.")
        return out
    age = now - (status.get("t") or 0) / 1000
    if running is not False and age > STALE_S:
        out["stale"] = f"Der Live-Bot hat seit {age / 60:.0f} Minuten keinen Status geschrieben (hängt er?)."
    if running is not False and age <= STALE_S and status.get("running") and not status.get("on"):
        why = status.get("refusing") or "; ".join(status.get("gate") or []) or "unbekannt"
        stops = status.get("stops") or {}
        if status.get("kill"):
            why = "Notschalter ist an"
        elif stops.get("daily"):
            why = "Tagesverlust-Grenze erreicht (morgen 00:00 UTC geht es weiter)"
        elif stops.get("total"):
            why = "Gesamtbudget aufgebraucht (nur eine neue Freigabe hebt das auf)"
        out["off"] = f"Der Live-Bot kauft nicht: {why}."
    sim = status.get("simulate") or {}
    if status.get("mode") == "test" and status.get("running"):
        sim_age_h = (now - (sim.get("t") or 0) / 1000) / 3600
        if not sim.get("ok"):
            out["sim"] = "Der letzte Testlauf (Simulation) ist fehlgeschlagen; nach 24 h schließt die Freigabe."
        elif sim_age_h > SIM_WARN_H:
            out["sim"] = f"Der letzte erfolgreiche Testlauf ist {sim_age_h:.0f} h alt; nach 24 h schließt die Freigabe."
    stuck = [p for p in status.get("positions") or [] if p.get("state") == "stuck"]
    if stuck:
        out["stuck"] = f"{len(stuck)} Position(en) lassen sich nicht verkaufen: " + \
            ", ".join(p.get("symbol") or (p.get("mint") or "?")[:6] for p in stuck)
    if status.get("leftovers"):
        out["leftovers"] = f"{len(status['leftovers'])} Position(en) von vor einem Neustart werden verkauft."
    return out


def decide(now_problems: dict[str, str], state: dict, now: float) -> tuple[list[tuple[str, str]], dict]:
    """The posts to send and the new state: a problem when it starts and every REPEAT_S, all clear once."""
    posts: list[tuple[str, str]] = []
    seen = dict(state.get("seen") or {})
    for k, text in now_problems.items():
        last = seen.get(k)
        if last is None or now - last >= REPEAT_S:
            posts.append(("pump.fun Live-Bot: Achtung", text))
            seen[k] = now
    gone = [k for k in seen if k not in now_problems]
    for k in gone:
        del seen[k]
    if gone and not now_problems:
        posts.append(("pump.fun Live-Bot: wieder in Ordnung", "Er läuft und handelt wieder normal."))
    return posts, {"seen": seen, "t": now}


def read_env(path: Path) -> dict[str, str]:
    env = dict(os.environ)
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return env


def post(title: str, text: str, dry: bool) -> None:
    if dry:
        print(f"[dry-run] {title}: {text}")
        return
    try:
        subprocess.run([sys.executable, str(NOTIFY), "--event", "risk", title, text], env=read_env(ALERT_ENV),
                       capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as e:
        print(f"pumpfun-live-watch: not posted ({type(e).__name__})", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data", default=os.environ.get("PYTHIA_DATA", "/srv/pythia-data"))
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    data = Path(a.data)
    try:
        status = json.loads((data / "reports" / "pumpfun_rt" / "live_status.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        status = None
    now = time.time()
    found = problems(status, container_running(), now)
    state_file = data / "_health" / "pumpfun_live_watch.json"
    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    posts, state = decide(found, state, now)
    for title, text in posts:
        post(title, text, a.dry_run)
    if not a.dry_run:
        state_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = state_file.with_suffix(".tmp")
        tmp.write_text(json.dumps({**state, "problems": found}, ensure_ascii=False), encoding="utf-8")
        tmp.replace(state_file)
    print(json.dumps({"problems": found, "posted": len(posts)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
