#!/usr/bin/env python3
"""Watches the stage-2 on-chain trader every two minutes and tells the owner at once when it is not
trading as it should, quiet hours or not. Standard library only; runs on the host as the job
"onchain-live-watch", in pumpfun_live_watch.py's style (its docker check, state and posting).

It reads what the service writes (reports/onchain_live/status.json, live/onchain/orders.jsonl) and
asks docker whether the container runs. Problems, each posted once when it starts and once an hour
while it lasts, and a "fine again" when all are gone (Telegram and Discord through notify.py,
category risk):
  - the container pythia-onchain-live is not running (only once it was ever started: a container or
    a status file exists; before the owner arms anything it stays quiet)
  - its status is older than STALE_S (the service hangs)
  - the service is running but not trading, with its reason (the gate, a stop, the kill switch)
  - the last simulation (the 24 h gate) failed or is older than SIM_WARN_H
  - the ledger does not match the chain, or a token account of the wallet is frozen
  - a swap was sent and has not settled for HANG_S (a hanging order)
It never restarts, stops or changes anything; its only file is its own state.

    python3 onchain_live_watch.py [--data /srv/pythia-data] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pumpfun_live_watch as PW  # noqa: E402

CONTAINER = "pythia-onchain-live"
STALE_S = 180
SIM_WARN_H = 20
HANG_S = 300
SETTLED = ("filled", "failed", "expired", "refused")


def container_state(name: str = CONTAINER) -> str | None:
    """"running", "stopped", "missing" from docker; None when docker cannot be asked."""
    try:
        r = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}", name], capture_output=True, text=True,
                           timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return "missing"
    return "running" if r.stdout.strip() == "true" else "stopped"


def hanging(orders: list[dict], now: float) -> list[str]:
    """Signatures sent more than HANG_S ago whose swap has no later settled line."""
    last: dict[str, dict] = {}
    for o in orders:
        k = o.get("sig") if o.get("what") == "sent" else None
        if k:
            last[k] = o
        elif o.get("sig") in last and o.get("what") in SETTLED:
            del last[o["sig"]]
    return [s for s, o in last.items() if now - (o.get("t") or 0) / 1000 > HANG_S]


def problems(status: dict | None, state: str | None, orders: list[dict], now: float) -> dict[str, str]:
    """{key: German text} of everything wrong right now; empty when the trader runs as it should."""
    out: dict[str, str] = {}
    if state == "missing" and status is None:
        return out                                          # never started: nothing armed, nothing to watch
    if state in ("stopped", "missing"):
        out["down"] = "Der On-Chain-Händler (Container) läuft nicht."
    if status is None:
        out.setdefault("status", "Kein Status vom On-Chain-Händler lesbar.")
        return out
    age = now - (status.get("t") or 0) / 1000
    up = state not in ("stopped", "missing")
    if up and age > STALE_S:
        out["stale"] = f"Der On-Chain-Händler hat seit {age / 60:.0f} Minuten keinen Status geschrieben (hängt er?)."
    fresh = up and age <= STALE_S
    if fresh and status.get("running") and not status.get("on"):
        stops = status.get("stops") or {}
        why = "; ".join(status.get("gate") or []) or "unbekannt"
        if status.get("kill"):
            why = "Notschalter ist an"
        out["off"] = f"Der On-Chain-Händler handelt nicht: {why}."
        if stops.get("daily"):
            out["daily"] = "Tagesverlust-Grenze erreicht: bis 00:00 UTC nur Verkäufe nach USDC."
    elif fresh and (status.get("stops") or {}).get("daily"):
        out["daily"] = "Tagesverlust-Grenze erreicht: bis 00:00 UTC nur Verkäufe nach USDC."
    if fresh and (status.get("stops") or {}).get("total"):
        out["total"] = "Die Wallet ist mehr wert als max_total_usd: nur noch Verkäufe nach USDC."
    sim = status.get("simulate") or {}
    if status.get("mode") == "test" and status.get("running"):
        sim_age_h = (now - (sim.get("t") or 0) / 1000) / 3600
        if not sim.get("ok"):
            out["sim"] = "Die letzte Simulation ist fehlgeschlagen oder fehlt; ohne sie bleibt der Händler zu."
        elif sim_age_h > SIM_WARN_H:
            out["sim"] = f"Die letzte erfolgreiche Simulation ist {sim_age_h:.0f} h alt; nach 24 h schließt die Freigabe."
    rec = status.get("reconcile") or {}
    if rec and rec.get("ok") is False:
        out["ledger"] = "Ledger und Chain stimmen nicht überein, keine Käufe: " + \
            ("; ".join(rec.get("diffs") or []) or "siehe Journal")[:300]
    if status.get("frozen"):
        out["frozen"] = f"{len(status['frozen'])} Token-Konto/Konten der Wallet sind eingefroren."
    hung = hanging(orders, now)
    if hung:
        out["hang"] = f"{len(hung)} Swap(s) gesendet und seit über {HANG_S // 60} Minuten ohne Ergebnis."
    return out


def decide(now_problems: dict[str, str], state: dict, now: float) -> tuple[list[tuple[str, str]], dict]:
    posts, new = PW.decide(now_problems, state, now)
    posts = [(t.replace("pump.fun Live-Bot", "On-Chain-Wallet"), x if "wieder normal" not in x else
              "Der On-Chain-Händler läuft wieder normal.") for t, x in posts]
    return posts, new


def read_orders(path: Path, keep: int = 400) -> list[dict]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()[-keep:]
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            o = json.loads(line)
        except ValueError:
            continue
        if isinstance(o, dict):
            out.append(o)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data", default=os.environ.get("PYTHIA_DATA", "/srv/pythia-data"))
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    data = Path(a.data)
    try:
        status = json.loads((data / "reports" / "onchain_live" / "status.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        status = None
    now = time.time()
    found = problems(status, container_state(), read_orders(data / "live" / "onchain" / "orders.jsonl"), now)
    state_file = data / "_health" / "onchain_live_watch.json"
    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    posts, state = decide(found, state, now)
    for title, text in posts:
        PW.post(title, text, a.dry_run)
    if not a.dry_run:
        state_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = state_file.with_suffix(".tmp")
        tmp.write_text(json.dumps({**state, "problems": found}, ensure_ascii=False), encoding="utf-8")
        tmp.replace(state_file)
    print(json.dumps({"problems": found, "posted": len(posts)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
