"""The weekly leak check (job leak-check, T1): every feature, the zoo's feature builders, the active G2 shadows' specs,
the paper books' weight functions and their panel builder through the harness; reports/leak/latest.md and .json.

  python -m lab.leak                 everything
  python -m lab.leak --only books    one part: features, zoo, specs, books

A failing feature, builder or book is a red line `leak <kind> <name>` in the health check (ops/jobs.py reads
latest.json); the factories check their genomes and specs themselves before each held-back look. A part that cannot
run (its data missing) is one red result with the error, the rest still runs. Exit 0 unless the run itself breaks.
No trial, no performance number (results/leak_harness_prereg.md).
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone

import polars as pl

from .. import report
from . import checks, reason

NAME = "leak"
PARTS = ("features", "zoo", "specs", "books")
PANEL_DAYS = 900                      # the panel builder on every coin's last 900 days


def _failed(kind: str, name: str, e: Exception) -> dict:
    return {"kind": kind, "name": name, "ok": False, "runs": 0, "cuts": [], "leaks": [], "first": None,
            "error": f"{type(e).__name__}: {e}"[:300]}


def features() -> list[dict]:
    return checks.all_features() + [checks.candles(f) for f in ("1h", "1d")]


def specs() -> list[dict]:
    """The model factory's active shadows (models/factory/shadows.json), each on its target's panel."""
    from ..models import factory as mf
    members = [m for m in mf._read_json(mf.shadows_path(), {"members": []})["members"] if m.get("status") != "retired"]
    P, bad = mf.Panels(), checks.bad_inputs()
    return [checks.spec(P.get(m["target"]), m["spec"], bad) for m in members]


def books() -> list[dict]:
    from ..experiments import fam_common as fc, memecoins as w7
    from ..paper import btc_gated, memes
    out = []
    P = fc.load_panel()
    w7p = {"memes": lambda: w7.build_panel(w7.load_frames(memes.SYMBOLS)),
           "btc_gated": lambda: w7.build_panel(w7.load_frames((btc_gated.SYMBOL,)))}
    for name, fn in checks.book_functions().items():
        try:
            out.append(checks.book(name, fn, w7p[name]() if name in w7p else P))
        except Exception as e:          # noqa: BLE001 (its panel could not be built)
            out.append(_failed("book", name, e))
    del P
    long = fc.build_daily_panel()
    long = long.filter(pl.col("day") > long["day"].max() - PANEL_DAYS * checks.DAY)
    out.append(checks.panel_builder(long, fc.perp_daily_for(int(long["day"].max()))))
    return out


def run(parts=PARTS, log=print) -> dict:
    t0 = time.time()
    results = []
    for part in parts:
        t = time.time()
        try:
            rs = {"features": features, "zoo": checks.zoo, "specs": specs, "books": books}[part]()
        except Exception as e:          # noqa: BLE001 (one part's data missing must not hide the others)
            rs = [_failed({"features": "feature", "specs": "spec", "books": "book"}.get(part, part), f"({part})", e)]
        for r in rs:
            r["why"] = reason(r)
            if not r["ok"]:
                log(f"  {r['kind']} {r['name']}: {r['why']}")
        results += rs
        log(f"leak check {part}: {len(rs)} checked, {sum(not r['ok'] for r in rs)} red ({time.time() - t:.0f} s)")
    return {"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "parts": list(parts),
            "checked": len(results), "red": sum(not r["ok"] for r in results), "seconds": round(time.time() - t0),
            "results": results}


KIND = {"feature": "Features (lab.features)", "candles": "Candle windows (C1/C2)", "zoo": "Zoo feature builders",
        "spec": "G2 specs (active shadows)", "book": "Paper books and their panel"}


def markdown(d: dict) -> str:
    md = [f"# Leak check, {d['generated'][:10]}\n",
          "Every function below ran on its full data and on copies where every value after t was shuffled, shifted "
          "or missing, and on the data cut at t (T1, `results/leak_harness_prereg.md`). Anything at or before t "
          "that moves is a leak. No trial, no performance number.\n",
          f"**{d['checked']} checked, {d['red']} red** ({d['seconds']} s).\n"]
    red = [r for r in d["results"] if not r["ok"]]
    if red:
        md += ["## Red\n", "| kind | name | why |", "|---|---|---|"]
        md += [f"| {r['kind']} | {r['name']} | {r['why']} |" for r in red]
        md.append("")
    for k, title in KIND.items():
        rs = [r for r in d["results"] if r["kind"] == k]
        if not rs:
            continue
        md += [f"## {title}\n", "| name | data | result |", "|---|---|---|"]
        md += [f"| {r['name']} | {r.get('data') or 'real'} | {'pass' if r['ok'] else 'RED'}: {r['why']} |" for r in rs]
        md.append("")
    return "\n".join(md)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m lab.leak")
    ap.add_argument("--only", choices=PARTS, action="append")
    a = ap.parse_args(argv)
    d = run(tuple(a.only or PARTS))
    report.write(NAME, markdown(d), d)
    print(f"leak check: {d['checked']} checked, {d['red']} red; reports/{NAME}/latest.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
