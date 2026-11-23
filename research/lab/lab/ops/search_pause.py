"""Search pause (results/search_pause_prereg.md): what the four search jobs delivered and the pre-registered rule that
pauses their trials. Reads only; changes nothing a live bot, a wallet or the engine reads.

The rule: a search job with no candidate of its own on the ladder's step 2 in the 6 weeks before the day of judgement
(WINDOW) stops generating new trials through its existing flag in research/ops/jobs.yaml (FLAG); it keeps re-scoring
what it holds, its shadows and the paper books, and restarts when a candidate of its own reaches step 2 or on the
owner's word. Step 2 is read from the ladder's report of today and the weekly page snapshots dated in the window
(the ladder keeps no other history).

Per job: trials a week from its own ledger by run day (the weekly factory's and F2's one per behaviour, F3's trial
lines by night, G2's lines by run), its ladder ids at the highest step they reached, run, heavy-lock and CPU hours
from the job runner's records (<data>/_ops/runs; the lock wait left out, CPU = lock hours x the job's cpus, an upper
bound), the bar's rise at today's N against N without its trials (B_day: R5's daily bar a year; B_entry: the pump.fun
rules' bar per entry over R5 plus F3's ledger; G2's own bar 0.05 / its trials), and the bars in WEEKS_AHEAD weeks
with and without the pause (every other register held at today's count, new trials at their family's variance).
Five trials in R5's registry, counted only, registered before the first number.

  python -m lab.ops.search_pause            register the five trials, write results/search_pause.json, print the table
  python -m lab.ops.search_pause --print    print the table, register and write nothing
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from .. import metrics
from . import jobs as J
from . import notify

PREREG = "results/search_pause_prereg.md"
RESULTS = Path(__file__).resolve().parents[2] / "results"
TABLE = Path(__file__).resolve().parents[3] / "ops" / "jobs.yaml"
JUDGED = "2026-11-23"
WINDOW = ("2026-10-12", "2026-11-22")      # 6 calendar weeks, Monday to Sunday, before the day of judgement
RATE_FROM = "2026-10-26"                    # the projection's rate: the mean of the last 4 full weeks
WEEKS_AHEAD = 8
STEP = 2                                    # the ladder's step 2, tested
G2_GATE_P = 0.05                            # G2's bar: a DM p of 0.05 over its trials (models.core.GATE_P)
F3_LEDGER = "pumpfun_rt/factory/ledger.jsonl"

# job -> its ledger, its lines in R5 (family, source) or None, its ladder ids, the flag that pauses it and the value
# it had before.
JOBS = {
    "factory-weekly": {"key": "weekly", "label": "strategy factory W10/G1 (weekly)", "ledger": "factory/ledger.jsonl",
                       "r5": ("factory", "factory ledger"), "ids": ("weekly:",),
                       "flag": "command --budget 0", "before": "300 (search.BUDGET)"},
    "factory-small": {"key": "f2", "label": "F2 small account (daily)", "ledger": "factory/small/ledger.jsonl",
                      "r5": ("small", "small ledger"), "ids": ("F2:",),
                      "flag": "PYTHIA_FACTORY_SMALL_BUDGET 0", "before": "60"},
    "pumpfun-factory": {"key": "f3", "label": "pump.fun factory F3 (nightly)", "ledger": F3_LEDGER,
                        "r5": None, "ids": ("book:F3_",),
                        "flag": "PYTHIA_PF_FACTORY_TRIALS 0", "before": "300"},
    "model-factory": {"key": "g2", "label": "model factory G2 (daily)", "ledger": "models/factory/ledger.jsonl",
                      "r5": None, "ids": ("G2:",),
                      "flag": "PYTHIA_MODEL_FACTORY_BUDGET 0", "before": "1500"},
}


def trials() -> list[dict]:
    return [{"id": f"hand:search_pause:{k}", "family": "hand", "n": 1, "sharpe": None, "source": PREREG}
            for k in [j["key"] for j in JOBS.values()] + ["projection"]]


def _jsonl(p: Path) -> list[dict]:
    out = []
    try:
        with p.open(encoding="utf-8") as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue                    # a torn last line
                if isinstance(r, dict):
                    out.append(r)
    except OSError:
        pass
    return out


def _monday(day: str) -> str:
    d = date.fromisoformat(day[:10])
    return (d - timedelta(days=d.weekday())).isoformat()


def weeks(window: tuple[str, str] = WINDOW) -> list[str]:
    d, end = date.fromisoformat(window[0]), date.fromisoformat(window[1])
    out = []
    while d <= end:
        out.append(d.isoformat())
        d += timedelta(days=7)
    return out


# ---------------------------------------------------------------- the measures

def trial_days(job: str, rows: list[dict]) -> list[str]:
    """One run day per trial of the job's ledger: a genome repeating an earlier behaviour is no trial (as R5 counts),
    F3's lines of kind trial by night, G2's lines by run (one per key)."""
    if job == "pumpfun-factory":
        return [str(r.get("night")) for r in rows if r.get("kind") == "trial" and r.get("night")]
    seen, out = set(), []
    for r in rows:
        if not r.get("run") or r.get("same_as") or r.get("key") in seen:
            continue
        seen.add(r.get("key"))
        out.append(str(r["run"]))
    return out


def per_week(days: list[str], window: tuple[str, str] = WINDOW) -> dict[str, int]:
    out = {w: 0 for w in weeks(window)}
    for d in days:
        if window[0] <= d[:10] <= window[1]:
            out[_monday(d)] += 1
    return out


def rate(wk: dict[str, int], since: str = RATE_FROM) -> float:
    xs = [n for w, n in wk.items() if w >= since]
    return sum(xs) / len(xs) if xs else 0.0


def ladder_steps(root: Path, prefixes: tuple[str, ...], window: tuple[str, str] = WINDOW) -> dict[str, int]:
    """{ladder id: highest step in the window} of the ids with these prefixes: today's report and every weekly page
    snapshot dated inside the window."""
    maps = []
    lad = notify.read_json(root / "reports" / "ladder" / "latest.json")
    if isinstance(lad, dict):
        maps.append({str(r.get("id")): r.get("step") for r in lad.get("rows") or [] if isinstance(r, dict)})
    for p in sorted((root / "reports" / "weekly").glob("????-??-??.json")):
        if window[0] <= p.stem <= window[1]:
            w = notify.read_json(p)
            if isinstance(w, dict) and isinstance(w.get("ladder"), dict):
                maps.append(w["ladder"])
    out: dict[str, int] = {}
    for m in maps:
        for k, s in m.items():
            if str(k).startswith(prefixes) and isinstance(s, (int, float)):
                out[str(k)] = max(out.get(str(k), 0), int(s))
    return out


def verdict(steps: dict[str, int]) -> str:
    """The rule: "pause" without a candidate of its own on step 2 or higher in the window, else "keep"."""
    return "keep" if any(s >= STEP for s in steps.values()) else "pause"


def _ts(s) -> float | None:
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def lock_hours(records: list[dict], heavy: set[str], job: str, window: tuple[str, str] = WINDOW) -> dict:
    """{runs, run_h, lock_h} of the job's runs started inside the window. A run's duration includes its wait for the
    lock: its hold starts at the later of its start and the end of the last other heavy run that ended inside it. A
    skipped run holds nothing."""
    spans = [(_ts(r.get("start")), _ts(r.get("end")), r) for r in records if r.get("job") in heavy]
    spans = [(a, b, r) for a, b, r in spans if a is not None and b is not None]
    runs, run_s, lock_s = 0, 0.0, 0.0
    for a, b, r in spans:
        if r.get("job") != job or not (window[0] <= str(r.get("start"))[:10] <= window[1]):
            continue
        runs += 1
        run_s += b - a
        if r.get("status") == "skipped":
            continue
        hold = max([a] + [e for s, e, o in spans if o is not r and o.get("status") != "skipped" and a < e <= b])
        lock_s += b - hold
    return {"runs": runs, "run_h": run_s / 3600, "lock_h": lock_s / 3600}


def pool_of(rows: list[dict]) -> dict:
    """trial_pool()'s pool of all, over these registry rows."""
    fams: dict[str, list[dict]] = {}
    for r in rows:
        fams.setdefault(r.get("family") or "hand", []).append(r)
    per = {f: metrics._family_pool(rs) for f, rs in fams.items()}
    n = sum(p["n_trials"] for p in per.values())
    w = sum(p["weight"] for p in per.values())
    v = sum(p["weight"] * p["var"] for p in per.values()) / w if w else 0.0
    return {"n_trials": n, "var": v, "sr0_annual": metrics.expected_max_sharpe(v, n) * math.sqrt(365),
            "families": per}


def n_only(var: float, n: int) -> float:
    """B_day at today's pooled variance and another N: the part of the bar's move that is N alone."""
    return metrics.expected_max_sharpe(var, n) * math.sqrt(365)


def mine(r: dict, r5: tuple[str, str] | None) -> bool:
    return r5 is not None and r.get("family") == r5[0] and r.get("source") == r5[1]


def b_entry(f3_sharpes: list[float], n: int) -> float:
    from ..pumpfun_rt import factory as F
    return F.bar(f3_sharpes, n)


def _grown(rows: list[dict], adds: dict[str, int], per: dict) -> list[dict]:
    """The registry with `adds` more trials per R5 family, each block at today's variance of its family (counted only
    when the family has none yet)."""
    var = lambda f: per[f]["var"] if (per.get(f) or {}).get("weight") else None
    return rows + [{"id": f"projection:{f}", "family": f, "n": k, "sharpe": None, "var": var(f)}
                   for f, k in adds.items() if k > 0]


def build(root: Path | None = None, table: Path = TABLE, reg_rows: list[dict] | None = None) -> dict:
    root = Path(root) if root is not None else notify.data_root()
    t = J.load_table(table)
    heavy = {n for n, j in t.jobs.items() if "heavy" in j["locks"]}
    records = [r for p in sorted((root / "_ops" / "runs").glob("*.jsonl")) for r in _jsonl(p)]
    rows = metrics.read_registry() if reg_rows is None else reg_rows
    from ..pumpfun_rt import factory as F
    f3_sharpes, n_f3 = F.pool(F.read_ledger(root / F3_LEDGER))
    today = pool_of(rows)
    n_entry = today["n_trials"] + n_f3
    out_jobs = []
    for name, j in JOBS.items():
        led = _jsonl(root / j["ledger"])
        days = trial_days(name, led)
        wk = per_week(days)
        steps = ladder_steps(root, j["ids"])
        by_step = {s: sum(1 for x in steps.values() if x == s) for s in range(0, 7)}
        hrs = lock_hours(records, heavy, name)
        cpus = float((t.jobs[name].get("resources") or {}).get("cpus") or 1)
        without = pool_of([r for r in rows if not mine(r, j["r5"])])
        n_r5 = today["n_trials"] - without["n_trials"]
        n_own = n_f3 if name == "pumpfun-factory" else n_r5
        row = {"job": name, "key": j["key"], "label": j["label"], "trials_total": len(days), "r5_trials": n_r5,
               "weeks": wk, "per_week": rate(wk), "window_trials": sum(wk.values()),
               "steps": by_step, "candidates": steps, "verdict": verdict(steps), "flag": j["flag"], "before": j["before"],
               **hrs, "cpu_h": hrs["lock_h"] * cpus, "cpus": cpus,
               "b_day": today["sr0_annual"], "b_day_without": without["sr0_annual"],
               "b_day_n_only": n_only(today["var"], without["n_trials"]),
               "b_entry": b_entry(f3_sharpes, n_entry), "b_entry_without": b_entry(f3_sharpes, n_entry - n_own)}
        if name == "model-factory":
            n0 = sum(1 for d in days if d < WINDOW[0])
            row["g2_bar_p"] = G2_GATE_P / max(len(days), 1)
            row["g2_bar_p_start"] = G2_GATE_P / max(n0, 1) if n0 else None
        out_jobs.append(row)
    proj = projection(rows, today, out_jobs, f3_sharpes, n_f3)
    return {"judged": JUDGED, "window": list(WINDOW), "rate_from": RATE_FROM, "weeks_ahead": WEEKS_AHEAD,
            "today": {"r5_trials": today["n_trials"], "f3_trials": n_f3, "b_day": today["sr0_annual"],
                      "b_entry": b_entry(f3_sharpes, n_entry), "n_entry": n_entry},
            "jobs": out_jobs, "projection": proj, "trials": [x["id"] for x in trials()]}


def projection(rows: list[dict], today: dict, out_jobs: list[dict], f3_sharpes: list[float], n_f3: int) -> dict:
    """The bars in WEEKS_AHEAD weeks: without the pause each job adds WEEKS_AHEAD x its weekly rate, with it the paused
    jobs add 0; everything else as today."""
    res = {}
    for case in ("without_pause", "with_pause"):
        adds: dict[str, int] = {}
        f3, g2 = n_f3, None
        for j in out_jobs:
            k = 0 if case == "with_pause" and j["verdict"] == "pause" else round(WEEKS_AHEAD * j["per_week"])
            fam = JOBS[j["job"]]["r5"]
            if fam:
                adds[fam[0]] = adds.get(fam[0], 0) + k
            elif j["job"] == "pumpfun-factory":
                f3 += k
            else:
                g2 = j["trials_total"] + k
        p = pool_of(_grown(rows, adds, today["families"]))
        res[case] = {"r5_trials": p["n_trials"], "f3_trials": f3, "b_day": p["sr0_annual"],
                     "b_day_n_only": n_only(today["var"], p["n_trials"]),
                     "b_entry": b_entry(f3_sharpes, p["n_trials"] + f3), "g2_trials": g2,
                     "g2_bar_p": G2_GATE_P / g2 if g2 else None}
    return res


# ---------------------------------------------------------------- the table

def _f(x, d=2) -> str:
    return "n/a" if x is None else f"{x:,.{d}f}"


def markdown(d: dict) -> str:
    md = [f"Judged {d['judged']} on the window {d['window'][0]} to {d['window'][1]}; rate: mean of the weeks from "
          f"{d['rate_from']}.", "",
          "| job | trials ever | in the window | a week (last 4) | candidates by step (0/1/2+) | verdict | runs | "
          "run h | heavy-lock h | CPU h (cap) | B_day today / without (N only) | B_entry today / without |",
          "|---|---:|---:|---:|---|---|---:|---:|---:|---:|---|---|"]
    for j in d["jobs"]:
        s = j["steps"]
        md.append(f"| {j['job']} | {j['trials_total']:,} | {j['window_trials']:,} | {j['per_week']:,.0f} | "
                  f"{s[0]}/{s[1]}/{sum(v for k, v in s.items() if k >= STEP)} | {j['verdict']} | {j['runs']} | "
                  f"{j['run_h']:.1f} | {j['lock_h']:.1f} | {j['cpu_h']:.1f} | {_f(j['b_day'], 3)} / "
                  f"{_f(j['b_day_without'], 3)} ({_f(j['b_day_n_only'], 3)}) | {_f(j['b_entry'], 4)} / {_f(j['b_entry_without'], 4)} |")
    g2 = next((j for j in d["jobs"] if j["job"] == "model-factory"), None)
    if g2:
        md += ["", f"G2's own bar: p < {g2['g2_bar_p']:.2g} today, {_f(g2.get('g2_bar_p_start'), 6)} at the window's "
               f"start."]
    md += ["", "| in " + str(d["weeks_ahead"]) + " weeks | R5 trials | F3 trials | B_day (N only) | B_entry | G2 trials | "
           "G2 bar p |", "|---|---:|---:|---:|---:|---:|---:|",
           f"| today | {d['today']['r5_trials']:,} | {d['today']['f3_trials']:,} | {d['today']['b_day']:.3f} "
           f"({d['today']['b_day']:.3f}) | "
           f"{d['today']['b_entry']:.4f} | {g2['trials_total'] if g2 else 0:,} | "
           f"{g2['g2_bar_p'] if g2 else 0:.2g} |"]
    for case, label in (("without_pause", "without the pause"), ("with_pause", "with the pause")):
        p = d["projection"][case]
        md.append(f"| {label} | {p['r5_trials']:,} | {p['f3_trials']:,} | {p['b_day']:.3f} ({p['b_day_n_only']:.3f}) | "
                  f"{p['b_entry']:.4f} | "
                  f"{p['g2_trials'] or 0:,} | {_f(p['g2_bar_p'], 8) if p['g2_bar_p'] else 'n/a'} |")
    md += ["", "Restart: a job restarts (its flag back to its value before) when one of its own ladder ids stands on "
           "step 2 or higher, or on the owner's word."]
    for j in d["jobs"]:
        md.append(f"- {j['job']}: {j['verdict']}, flag {j['flag']} (before {j['before']}); ids "
                  f"{', '.join(JOBS[j['job']]['ids'])}, on step 2 or higher now: "
                  f"{', '.join(k for k, v in j['candidates'].items() if v >= STEP) or 'none'}")
    return "\n".join(md) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="lab.ops.search_pause")
    ap.add_argument("--print", action="store_true", help="print only: register and write nothing")
    ap.add_argument("--out", default=str(RESULTS / "search_pause.json"))
    a = ap.parse_args(sys.argv[1:] if argv is None else argv)
    if not a.print:
        metrics.register(trials())                           # the five trials, before the numbers
    d = build()
    if not a.print:
        Path(a.out).write_text(json.dumps(d, indent=1, default=float) + "\n", encoding="utf-8")
    print(markdown(d))
    return 0


if __name__ == "__main__":
    sys.exit(main())
