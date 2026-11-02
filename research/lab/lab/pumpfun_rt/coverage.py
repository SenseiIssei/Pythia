"""C1 (2026-11-02): how complete the lab's pump.fun record is, a day at a time. Read only, paper only.

    python -m lab.pumpfun_rt.coverage              yesterday and today so far (UTC) into reports/pumpfun_rt/coverage.*
    python -m lab.pumpfun_rt.coverage --days 7     the last 7 days
    python -m lab.pumpfun_rt.coverage --check      exit 1 (the job turns red) when live-mint coverage is under LIVE_MIN

The live twin (results/pumpfun_live_twin.md) found 83 of 149 live trades without a paper twin: 52 had no pool state
in the record, 20 no creation row, 11 a stream gap, and the record lagged the live feed by up to 25 s. The collector
now recovers a migration the stream lost (collector.py, C1); this says per day whether that is enough:

  migrated   coins with a migration, a completed curve or a pool read that day; the share of them with a pool read
             (pool_state), with a creation row (that day or the CREATE_DAYS - 1 before; one read late from the chain,
             creates_late, counts and is also counted apart) and with both
  live       the mints the live bot traded that day (reports/pumpfun_rt/live_trades.json, read only); covered when
             the record has the creation row and, for a pool rule, a pool read: what a paper twin needs
  gaps       every stretch with all links of a program down ("gap" rows): its program, start, end and length
  clock      receive time less block time (t - bts), in seconds, median and 90th percentile per table and over all
             rows that carry a block time; block time is whole seconds, so each offset carries up to 1 s of rounding

Nothing here is a trial: it counts the record, it tests no rule.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date, timedelta

import polars as pl

from . import events as E
from . import store

LIVE_MIN = 0.9          # the check is red when under 90 % of a day's live mints are covered
C1_FROM = "2026-11-03"  # the first full day of the record with C1 deployed; earlier days are reported, not checked
CREATE_DAYS = 3         # a coin's creation row is looked for on its day and the two before
STALE_H = 36            # the check is red when the report is older than this
KEEP_DAYS = 60
GAPS_LISTED = 50
PROGRAMS = {E.PUMP: "pump.fun", E.PUMP_AMM: "PumpSwap"}


def report_dir():
    from .. import report as rep
    return rep.REPORTS / "pumpfun_rt"


def live_trades(path=None) -> list[dict]:
    path = path or report_dir() / "live_trades.json"
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    rows = d.get("trades") if isinstance(d, dict) else d
    return [r for r in rows or [] if isinstance(r, dict) and r.get("mint") and r.get("signal_ms")]


def _q(s: pl.Series) -> dict:
    s = s.drop_nulls()
    if not len(s):
        return {"n": 0, "median_s": None, "p90_s": None}
    return {"n": len(s), "median_s": round(float(s.quantile(0.5, "linear")) / 1000, 3),
            "p90_s": round(float(s.quantile(0.9, "linear")) / 1000, 3)}


def day_coverage(day: str, live: list[dict], root=None) -> dict:
    root = root or store.base()
    d0 = date.fromisoformat(day)
    back = [(d0 - timedelta(days=k)).isoformat() for k in range(CREATE_DAYS - 1, -1, -1)]
    created = set(store.read("creates", back, root, cols=["mint"])["mint"].drop_nulls().to_list())
    late = set(store.read("creates_late", back, root, cols=["mint"])["mint"].drop_nulls().to_list())
    created |= late
    other = store.read("other", [day], root, cols=["kind", "t", "mint", "user", "t0", "bts"])
    kind = pl.col("kind")
    migrated = set(other.filter(kind.is_in(["migrate", "complete", "pool_state"]))["mint"].drop_nulls().to_list())
    pooled = set(other.filter(kind == "pool_state")["mint"].drop_nulls().to_list())
    n = len(migrated)

    def share(k):
        return round(k / n, 4) if n else None
    mig = {"coins": n, "pool_state": len(migrated & pooled), "creation": len(migrated & created),
           "both": len(migrated & pooled & created), "creation_late": len(migrated & late)}
    mig.update({f"{k}_share": share(mig[k]) for k in ("pool_state", "creation", "both")})

    mints = []
    for r in live:
        if store.day_of(int(r["signal_ms"])) != day:
            continue
        pool_rule = "pool" in str(r.get("rule") or "")
        has_c, has_p = r["mint"] in created, r["mint"] in pooled
        mints.append({"mint": r["mint"], "rule": r.get("rule"), "creation": has_c, "pool_state": has_p,
                      "covered": has_c and (has_p or not pool_rule)})
    seen = {}
    for m in mints:                              # a mint traded twice in a day counts once
        seen[m["mint"]] = m if m["mint"] not in seen else {**m, "covered": m["covered"] and seen[m["mint"]]["covered"]}
    lv = list(seen.values())
    live_out = {"mints": len(lv), "covered": sum(m["covered"] for m in lv),
                "no_creation": sum(not m["creation"] for m in lv),
                "no_pool_state": sum(not m["pool_state"] and "pool" in str(m["rule"] or "") for m in lv)}
    live_out["share"] = round(live_out["covered"] / len(lv), 4) if lv else None
    live_out["missing"] = sorted(m["mint"] for m in lv if not m["covered"])

    gaps = other.filter(kind == "gap").with_columns(len_s=(pl.col("t") - pl.col("t0")) / 1000).sort("len_s",
                                                                                                   descending=True)
    by_prog = {}
    for prog, name in PROGRAMS.items():
        g = gaps.filter(pl.col("user") == prog)
        by_prog[name] = {"n": g.height, "total_s": round(float(g["len_s"].sum() or 0), 1),
                         "max_s": round(float(g["len_s"].max() or 0), 1)}
    listed = [{"program": PROGRAMS.get(u, u), "from_ms": a, "to_ms": b, "len_s": round(s, 1)}
              for u, a, b, s in gaps.select("user", "t0", "t", "len_s").head(GAPS_LISTED).iter_rows()]

    offs, clock = [], {}
    for table in ("creates", "trades", "amm", "other"):
        df = store.read(table, [day], root, cols=["t", "bts"]).drop_nulls()
        o = (df["t"] - df["bts"] * 1000).cast(pl.Int64)
        clock[table] = _q(o)
        offs.append(o)
    clock["all"] = _q(pl.concat(offs) if offs else pl.Series([], dtype=pl.Int64))
    return {"day": day, "migrated": mig, "live": live_out, "gaps": {"by_program": by_prog, "longest": listed},
            "clock": clock}


def build(days: list[str], root=None, live_path=None, old: dict | None = None) -> dict:
    live = live_trades(live_path)
    out = dict((old or {}).get("days") or {})
    for day in days:
        out[day] = day_coverage(day, live, root)
    keep = sorted(out)[-KEEP_DAYS:]
    return {"t": int(time.time() * 1000), "live_min": LIVE_MIN, "c1_from": C1_FROM,
            "days": {d: out[d] for d in keep}}


def pct(x) -> str:
    return "n/a" if x is None else f"{x:.1%}"


def secs(x) -> str:
    return "n/a" if x is None else f"{x:.1f} s"


def report_md(res: dict) -> str:
    md = ["# pump.fun record: coverage (C1)", "",
          f"Per UTC day: migrated coins with a pool read and a creation row, the live bot's mints the record covers "
          f"(creation row, and a pool read for a pool rule), the stream gaps and the receive time's offset to block "
          f"time. The check is red under {pct(res['live_min'])} live-mint coverage on a day from {res['c1_from']} "
          f"(C1 deployed). Paper only.", "",
          "| day | migrated | pool read | creation | both | live mints | covered | no creation | no pool read | "
          "gaps pump.fun | gaps PumpSwap | longest gap | clock median | clock p90 |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for day in sorted(res["days"], reverse=True):
        r = res["days"][day]
        m, lv, g, c = r["migrated"], r["live"], r["gaps"]["by_program"], r["clock"]["all"]
        md.append(f"| {day} | {m['coins']:,} | {pct(m['pool_state_share'])} | {pct(m['creation_share'])} | "
                  f"{pct(m['both_share'])} | {lv['mints']} | {pct(lv['share'])} | {lv['no_creation']} | "
                  f"{lv['no_pool_state']} | {g['pump.fun']['n']} ({g['pump.fun']['total_s']:.0f} s) | "
                  f"{g['PumpSwap']['n']} ({g['PumpSwap']['total_s']:.0f} s) | "
                  f"{max(g['pump.fun']['max_s'], g['PumpSwap']['max_s']):.0f} s | {secs(c['median_s'])} | "
                  f"{secs(c['p90_s'])} |")
    if res["days"]:
        last = res["days"][max(res["days"])]
        md += ["", f"Clock offset on {last['day']} by table (receive less block time):", "",
               "| table | rows | median | p90 |", "|---|---|---|---|"]
        for table, q in last["clock"].items():
            md.append(f"| {table} | {q['n']:,} | {secs(q['median_s'])} | {secs(q['p90_s'])} |")
    return "\n".join(md) + "\n"


def save(res: dict) -> None:
    d = report_dir()
    d.mkdir(parents=True, exist_ok=True)
    store.write_json(d / "coverage.json", res)
    (d / "coverage.md").write_text(report_md(res), encoding="utf-8")


def check(res: dict | None = None, now_ms: int | None = None) -> tuple[bool, str]:
    """Red when the newest checked day with live mints has under LIVE_MIN of them covered, or the report is stale."""
    if res is None:
        try:
            res = json.loads((report_dir() / "coverage.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False, "pump.fun coverage: no reports/pumpfun_rt/coverage.json"
    now_ms = now_ms or int(time.time() * 1000)
    if now_ms - int(res.get("t") or 0) > STALE_H * 3_600_000:
        return False, f"pump.fun coverage: report older than {STALE_H} h"
    lim = float(res.get("live_min") or LIVE_MIN)
    days = [d for d in sorted(res.get("days") or {}) if d >= str(res.get("c1_from") or C1_FROM)
            and (res["days"][d]["live"]["mints"] or 0) > 0]
    if not days:
        return True, f"pump.fun coverage ok: no live mints on a day since {res.get('c1_from') or C1_FROM} yet"
    r = res["days"][days[-1]]
    lv, m = r["live"], r["migrated"]
    msg = (f"{days[-1]}: live mints covered {lv['covered']} of {lv['mints']} ({pct(lv['share'])}, no creation "
           f"{lv['no_creation']}, no pool read {lv['no_pool_state']}); migrated coins with pool read and creation "
           f"{pct(m['both_share'])}; clock p90 {secs(r['clock']['all']['p90_s'])}")
    if lv["share"] is not None and lv["share"] < lim:
        return False, f"pump.fun coverage under {pct(lim)}: " + msg
    return True, "pump.fun coverage ok: " + msg


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--days", type=int, default=2, help="the last N UTC days, today included")
    ap.add_argument("--check", action="store_true", help="only judge reports/pumpfun_rt/coverage.json")
    a = ap.parse_args(argv)
    if a.check:
        ok, msg = check()
        print(msg)
        return 0 if ok else 1
    today = date.fromisoformat(store.day_of(int(time.time() * 1000)))
    days = [(today - timedelta(days=k)).isoformat() for k in range(max(1, a.days) - 1, -1, -1)]
    try:
        old = json.loads((report_dir() / "coverage.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        old = None
    res = build(days, old=old)
    save(res)
    print(report_md(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())
