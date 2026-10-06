"""Experiment reports land in /data/reports/<name>/: dated markdown + json, plus latest.*"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from .data import ROOT


def write(name: str, markdown: str, data: dict) -> None:
    d = ROOT / "reports" / name
    d.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for fname in (f"{stamp}.md", "latest.md"):
        (d / fname).write_text(markdown)
    for fname in (f"{stamp}.json", "latest.json"):
        (d / fname).write_text(json.dumps(data, indent=2, default=str))
    print(markdown)


def table(rows: list[dict], cols: list[str]) -> str:
    head = "| " + " | ".join(cols) + " |\n|" + "---|" * len(cols) + "\n"
    return head + "".join("| " + " | ".join(_fmt(r.get(c)) for c in cols) + " |\n" for r in rows)


def _fmt(v) -> str:
    if isinstance(v, float):
        return f"{v:.3f}" if abs(v) < 100 else f"{v:,.0f}"
    return str(v)
