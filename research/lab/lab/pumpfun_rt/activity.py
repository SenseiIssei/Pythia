"""Daily pump.fun activity series (survey O9), recorded forward. Information only.

    python -m lab.pumpfun_rt.activity             every finished day still in the record
    python -m lab.pumpfun_rt.activity --dry-run   print the rows, write nothing

Registered in results/pumpfun_activity_prereg.md: per UTC day the tokens created,
curves completed, tokens migrated, the migration rate, the curve volume in SOL and the
distinct curve traders, with the share of the day the pump.fun stream was connected
(`coverage`) and every count also divided by it (`*_adj`). A day with coverage of at
least 0.9 is complete. Nothing is judged before 180 complete days.

The series is merged into <reports>/pumpfun_activity/series.csv every day: a day whose
record partition is gone (the record deletes its oldest days when over budget) keeps
its stored row. The report <reports>/pumpfun_activity/latest.json carries the lab feed
header. Part files that were synced next to their compacted day file are read once.
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import polars as pl

from .. import report
from . import store
from .events import PUMP

NAME = "pumpfun_activity"
DAY_MS = 86_400_000
EDGE_MS = 5 * 60_000
COMPLETE = 0.9
JUDGE_DAYS = 180
COLS = ("day", "creations", "completions", "migrations", "migration_rate", "sol_volume", "traders", "coverage",
        "complete", "creations_adj", "completions_adj", "migrations_adj", "sol_volume_adj", "traders_adj")


def out_dir() -> Path:
    return report.REPORTS / NAME


def day_ms(day: str) -> int:
    return int(datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)


def next_day(day: str) -> str:
    return (datetime.strptime(day, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")


def coverage(first_ms: int | None, last_ms: int | None, gaps: list[tuple[int, int]], d0: int) -> float:
    """Share of the day the stream was connected: from the first to the last event (the day's
    edges when the first or last event is within 5 minutes of them), minus the gaps."""
    if first_ms is None or last_ms is None:
        return 0.0
    d1 = d0 + DAY_MS
    a = d0 if first_ms - d0 <= EDGE_MS else first_ms
    b = d1 if d1 - last_ms <= EDGE_MS else last_ms
    if b <= a:
        return 0.0
    iv = sorted((max(a, g0), min(b, g1)) for g0, g1 in gaps if g1 > a and g0 < b)
    lost, cur0, cur1 = 0, None, None
    for g0, g1 in iv:
        if cur1 is None or g0 > cur1:
            if cur1 is not None:
                lost += cur1 - cur0
            cur0, cur1 = g0, g1
        else:
            cur1 = max(cur1, g1)
    if cur1 is not None:
        lost += cur1 - cur0
    return max(0.0, (b - a - lost) / DAY_MS)


def day_row(day: str, root: Path | None = None) -> dict:
    d0 = day_ms(day)
    c = store.read("creates", [day], root).unique()
    t = store.read("trades", [day], root).unique()
    o = store.read("other", [day, next_day(day)], root).unique()
    in_day = (pl.col("t") >= d0) & (pl.col("t") < d0 + DAY_MS)
    c = c.filter(in_day)
    t = t.filter(in_day)
    ev = o.filter(in_day)
    creations = c["mint"].n_unique() if c.height else 0
    completions = ev.filter(pl.col("kind") == "complete")["mint"].n_unique()
    migrations = ev.filter(pl.col("kind") == "migrate")["mint"].n_unique()
    sol_t = t.filter(pl.col("quote").is_null()) if "quote" in t.columns else t
    sol = float(sol_t["sol"].sum() or 0) / 1e9 if sol_t.height else 0.0
    traders = t["user"].n_unique() if t.height else 0
    times = pl.concat([c.select("t"), t.select("t")]) if (c.height or t.height) else pl.DataFrame({"t": []})
    first = int(times["t"].min()) if times.height else None
    last = int(times["t"].max()) if times.height else None
    g = o.filter((pl.col("kind") == "gap") & (pl.col("user") == PUMP))
    gaps = [(int(a), int(b)) for a, b in zip(g["t0"].to_list(), g["t"].to_list()) if a is not None and b is not None]
    cov = coverage(first, last, gaps, d0)
    row = {"day": day, "creations": creations, "completions": completions, "migrations": migrations,
           "migration_rate": migrations / creations if creations else 0.0, "sol_volume": sol, "traders": traders,
           "coverage": cov, "complete": cov >= COMPLETE}
    for k in ("creations", "completions", "migrations", "sol_volume", "traders"):
        row[f"{k}_adj"] = row[k] / cov if cov > 0 else 0.0
    return row


def read_series(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8", newline="") as f:
        return {r["day"]: r for r in csv.DictReader(f)}


def write_series(path: Path, rows: dict[str, dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        for d in sorted(rows):
            w.writerow({k: rows[d].get(k) for k in COLS})
    tmp.replace(path)


def as_bool(v) -> bool:
    return v is True or str(v).lower() in ("true", "1")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = out_dir() / "series.csv"
    rows = read_series(path)
    for day in store.days():
        if day >= today:
            continue
        r = day_row(day)
        rows[day] = r
        print(f"  {day}: {r['creations']} created, {r['migrations']} migrated, {r['sol_volume']:.0f} SOL, "
              f"coverage {r['coverage']:.2f}", flush=True)
    if a.dry_run:
        return 0
    write_series(path, rows)
    done = [r for r in rows.values() if as_bool(r["complete"])]
    last = rows[max(rows)] if rows else None
    if last:
        headline = (f"{last['day']}: {int(float(last['creations'])):,} tokens created, "
                    f"{int(float(last['migrations'])):,} migrated, {float(last['sol_volume']):,.0f} SOL on the curves "
                    f"(coverage {float(last['coverage']) * 100:.0f} %). Forward record: {len(done)} of {JUDGE_DAYS} "
                    "complete days; nothing is judged before then.")
    else:
        headline = "No finished day in the record yet."
    items = [{"label": d, "value": f"{int(float(rows[d]['creations'])):,} created, "
                                   f"{float(rows[d]['sol_volume']):,.0f} SOL",
              "detail": f"migration rate {float(rows[d]['migration_rate']) * 100:.1f} %, coverage "
                        f"{float(rows[d]['coverage']) * 100:.0f} %"} for d in sorted(rows)[-7:][::-1]]
    data = {**report.feed_header("pump.fun activity", "ok", headline, items), "complete_days": len(done),
            "judge_after": JUDGE_DAYS, "series": [rows[d] for d in sorted(rows)]}
    md = ["# pump.fun activity (forward record)\n", headline + "\n",
          "Registered in `results/pumpfun_activity_prereg.md`. Information only until "
          f"{JUDGE_DAYS} complete days.\n",
          "| day | created | completed | migrated | rate | SOL | traders | coverage |", "|---|---|---|---|---|---|---|---|"]
    for d in sorted(rows)[-30:]:
        r = rows[d]
        md.append(f"| {d} | {int(float(r['creations']))} | {int(float(r['completions']))} | "
                  f"{int(float(r['migrations']))} | {float(r['migration_rate']) * 100:.1f} % | "
                  f"{float(r['sol_volume']):,.0f} | {int(float(r['traders']))} | {float(r['coverage']) * 100:.0f} % |")
    out = out_dir()
    out.mkdir(parents=True, exist_ok=True)
    (out / "latest.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    (out / "latest.json").write_text(json.dumps(data, indent=1, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
