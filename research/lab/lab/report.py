"""Experiment reports land in /data/reports/<name>/: dated markdown + json, plus latest.*

PYTHIA_REPORTS moves them elsewhere (on the PC the data folder is a sync
mirror that must not be written into). PYTHIA_RESULTS, when set, also gets a
copy of the markdown as <name>.md, which is how research/lab/results/ in the
repo is filled.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .data import ROOT

REPORTS = Path(os.environ.get("PYTHIA_REPORTS", ROOT / "reports"))


def write(name: str, markdown: str, data: dict) -> None:
    d = REPORTS / name
    d.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for fname in (f"{stamp}.md", "latest.md"):
        (d / fname).write_text(markdown, encoding="utf-8")
    for fname in (f"{stamp}.json", "latest.json"):
        (d / fname).write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    results = os.environ.get("PYTHIA_RESULTS")
    if results:
        Path(results).mkdir(parents=True, exist_ok=True)
        (Path(results) / f"{name}.md").write_text(markdown, encoding="utf-8")
    print(markdown)


def table(rows: list[dict], cols: list[str]) -> str:
    head = "| " + " | ".join(cols) + " |\n|" + "---|" * len(cols) + "\n"
    return head + "".join("| " + " | ".join(_fmt(r.get(c)) for c in cols) + " |\n" for r in rows)


def _fmt(v) -> str:
    if isinstance(v, float):
        return f"{v:.3f}" if abs(v) < 100 else f"{v:,.0f}"
    return str(v)
