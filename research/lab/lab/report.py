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


FEED_STATUSES = ("ok", "watch", "bad")


def feed_header(title: str, status: str, headline: str, items: list | None = None,
                updated_ms: int | None = None) -> dict:
    """The common header that makes reports/<name>/latest.json show up in the
    app's Research page and Home insights (docs/LAB-FEEDS.md). Merge it into
    the data passed to write(); the rest of the report stays as it is.

    items: dicts with a label and optionally value, status, detail, link
    (a URL or "study:<name>") and importance (0..100), or plain strings."""
    if status not in FEED_STATUSES:
        raise ValueError(f"status must be one of {FEED_STATUSES}, not {status!r}")
    rows = []
    for it in items or []:
        if isinstance(it, str):
            rows.append({"label": it})
            continue
        if not it.get("label"):
            raise ValueError(f"a feed item needs a label: {it!r}")
        rows.append({k: v for k, v in it.items() if v is not None})
    return {"title": title, "status": status, "headline": headline,
            "updated_ms": updated_ms if updated_ms is not None else int(datetime.now(timezone.utc).timestamp() * 1000),
            "items": rows[:50]}


def table(rows: list[dict], cols: list[str]) -> str:
    head = "| " + " | ".join(cols) + " |\n|" + "---|" * len(cols) + "\n"
    return head + "".join("| " + " | ".join(_fmt(r.get(c)) for c in cols) + " |\n" for r in rows)


def _fmt(v) -> str:
    if isinstance(v, float):
        return f"{v:.3f}" if abs(v) < 100 else f"{v:,.0f}"
    return str(v)
