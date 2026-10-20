"""X11 d: a calibrated drift test (form W) and its acceptance test.

    python -m lab.models.drift_study_w

Pre-registered in results/model_upgrades_prereg.md (section d). Bins and
windows exactly as X9 (drift_study.py): deciles of the training rows before
2024, each model's drift length, stepping 7 days. Form W
(core.drift_calibration_window): per input, cuts at the q-quantiles of its
PSI and outside share over the training windows; one q per model so that at
most 5 % of training windows trip; "shift" when any input is over a cut,
"drift" when the input that tripped it spent over 5 % of the window outside
the trained range.

Acceptance, every model: (1) in-sample false alarms at most 7.5 %, each
training window judged with a calibration fitted on the other years' windows;
(2) out-of-sample (windows from 2024) shift rate at most 20 %; (3) power at
least 90 % on synthetic faults in the out-of-sample windows, one input at a
time: a two-sigma level shift, a frozen feed, a unit error (x 100). The
one-sigma power is reported for comparison with X9, not judged.

Writes results/drift_window.md and <reports>/drift_window.json.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import polars as pl

from . import core, zoo
from .drift_study import CUT, MODELS, train_bins

ACCEPT_IS = 0.075
ACCEPT_OOS = 0.20
ACCEPT_POWER = 0.90
RESULTS = Path(__file__).resolve().parents[2] / "results"
FAULTS = ("shift 2 sd", "frozen", "units x 100", "shift 1 sd (reported)")


def year(ts: int) -> int:
    return datetime.fromtimestamp(ts / 1e6, timezone.utc).year


def loyo_rate(bins: dict, w_is: list[dict], days: int) -> tuple[float, dict]:
    """Each training window judged by a calibration fitted on the other years' windows."""
    flags, by = [], {}
    for y in sorted({year(w["to"] - 1) for w in w_is}):
        rest = [w for w in w_is if year(w["to"] - 1) != y]
        mine = [w for w in w_is if year(w["to"] - 1) == y]
        cal = core.drift_calibration_window(bins, rest, days)
        if cal is None:
            continue
        f = [core.calibrated_level(w["checks"], cal)[0] != "stable" for w in mine]
        flags += f
        by[y] = float(np.mean(f)) if f else None
    return (float(np.mean(flags)) if flags else float("nan")), by


def fault_values(kind: str, v: np.ndarray, sym: np.ndarray, ts: np.ndarray, sd: float) -> np.ndarray:
    if kind == "shift 2 sd":
        return v + 2 * sd
    if kind == "shift 1 sd (reported)":
        return v + sd
    if kind == "units x 100":
        return v * 100
    # frozen: each coin held at its value on the window's first day it has one
    out = v.copy()
    for s in np.unique(sym):
        m = sym == s
        idx = np.flatnonzero(m & np.isfinite(v))
        if idx.size:
            out[m] = v[idx[np.argmin(ts[idx])]]
    return out


def power(bins: dict, panel: pl.DataFrame, train: pl.DataFrame, cal: dict, days: int) -> dict:
    sd = {f: float(np.nanstd(train[f].fill_null(np.nan).to_numpy().astype(float))) for f in bins}
    ts = panel["ts_us"].to_numpy()
    sym = panel["symbol"].cast(pl.Utf8).to_numpy()
    cols = {f: panel[f].fill_null(np.nan).to_numpy().astype(float) for f in bins}
    wins = core.drift_windows(bins, panel, days, start_us=CUT)
    hits = {k: 0 for k in FAULTS}
    total = 0
    per_input = {f: {k: [0, 0] for k in FAULTS} for f in bins}
    for w in wins:
        m = (ts >= w["from"]) & (ts < w["to"])
        for f in bins:
            if f not in w["checks"]:
                continue
            total += 1
            for k in FAULTS:
                c = core.drift_check(bins[f], fault_values(k, cols[f][m], sym[m], ts[m], sd[f]))
                if c is None:
                    continue
                checks = dict(w["checks"])
                checks[f] = c
                hit = core.calibrated_level(checks, cal)[0] != "stable"
                hits[k] += hit
                per_input[f][k][0] += hit
                per_input[f][k][1] += 1
    out = {"pairs": total, **{k: (hits[k] / total if total else None) for k in FAULTS}}
    out["weakest"] = sorted(((f, v["shift 2 sd"][0] / v["shift 2 sd"][1]) for f, v in per_input.items()
                             if v["shift 2 sd"][1]), key=lambda x: x[1])[:5]
    return out


def study(name: str) -> dict:
    mod = zoo.module(name)
    spec = mod.SPEC
    panel = mod.load().sort(["ts_us", "symbol"])
    known = panel["target"].is_not_null() & panel["target"].fill_null(np.nan).is_finite()
    train = panel.filter(known & (pl.col("ts_us") < CUT))
    bins = train_bins(spec, train)
    days = spec.drift_days
    w_is = core.drift_windows(bins, train, days)
    w_oos = core.drift_windows(bins, panel, days, start_us=CUT)
    cal = core.drift_calibration_window(bins, w_is, days)
    loyo, by_year = loyo_rate(bins, w_is, days)
    lv_oos = [core.calibrated_level(w["checks"], cal)[0] for w in w_oos]
    newest = core.drift_windows(bins, panel, days, start_us=int(panel["ts_us"].max()) - days * core.DAY_US)
    out = {"model": spec.code, "name": name, "days": days, "inputs": len(bins),
           "windows_is": len(w_is), "windows_oos": len(w_oos), "quantile": cal["quantile"],
           "false_alarm_fit": cal["false_alarm_train"], "false_alarm_loyo": loyo, "loyo_by_year": by_year,
           "oos_shift": float(np.mean([x != "stable" for x in lv_oos])) if lv_oos else None,
           "oos_drift": float(np.mean([x == "drift" for x in lv_oos])) if lv_oos else None,
           "power": power(bins, panel, train, cal, days),
           "newest": core.calibrated_level(newest[-1]["checks"], cal)[0] if newest else None,
           "newest_input": core.window_score(newest[-1]["checks"], cal["cuts"])[1] if newest else None}
    p = out["power"]
    ok = {"1 in-sample false alarms (leave one year out)": loyo <= ACCEPT_IS,
          "2 out-of-sample shift rate": (out["oos_shift"] or 0) <= ACCEPT_OOS,
          "3 power, 2 sd": (p["shift 2 sd"] or 0) >= ACCEPT_POWER,
          "3 power, frozen feed": (p["frozen"] or 0) >= ACCEPT_POWER,
          "3 power, units x 100": (p["units x 100"] or 0) >= ACCEPT_POWER}
    out["failed"] = [k for k, v in ok.items() if not v]
    out["accepted"] = not out["failed"]
    return out


def write(res: list[dict], accepted: bool) -> None:
    def p(x):
        return "n/a" if x is None else f"{x * 100:.0f} %"
    md = ["# X11 d: a calibrated drift test (form W)\n\n",
          "Generated by `python -m lab.models.drift_study_w` from the pre-registration in `model_upgrades_prereg.md`. "
          "Bins from training rows before 2024, each model's drift window stepping 7 days, as in X9 c.\n\n",
          "| model | inputs | windows IS / OOS | q | false alarms, fit | leave one year out | OOS shift | OOS drift | "
          "power 2 sd | frozen | units x 100 | 1 sd (X9: 31 to 58 %) | newest window |\n"
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|\n"]
    for r in res:
        if "error" in r:
            md.append(f"| {r['name']} | data not available here: {r['error']} |" + " |" * 11 + "\n")
            continue
        w = r["power"]
        md.append(f"| {r['model']} | {r['inputs']} | {r['windows_is']} / {r['windows_oos']} | {r['quantile']} | "
                  f"{p(r['false_alarm_fit'])} | {p(r['false_alarm_loyo'])} | {p(r['oos_shift'])} | {p(r['oos_drift'])} | "
                  f"{p(w['shift 2 sd'])} | {p(w['frozen'])} | {p(w['units x 100'])} | {p(w['shift 1 sd (reported)'])} | "
                  f"{r['newest']} ({r['newest_input'] or 'none'}) |\n")
    md.append("\n| model | leave-one-year-out false alarms by year | inputs least sensitive to a 2 sd shift | failed |\n|---|---|---|---|\n")
    for r in res:
        if "error" in r:
            continue
        by = ", ".join(f"{y} {p(v)}" for y, v in r["loyo_by_year"].items())
        weak = ", ".join(f"{f} {p(v)}" for f, v in r["power"]["weakest"])
        md.append(f"| {r['model']} | {by} | {weak} | {', '.join(r['failed']) or 'none'} |\n")
    md.append(f"\n**Verdict.** Form W is {'accepted' if accepted else 'not accepted'} (needs, for every model, leave-one-year-out "
              f"false alarms at most {ACCEPT_IS:.1%}, out-of-sample shift at most {ACCEPT_OOS:.0%}, and power at least "
              f"{ACCEPT_POWER:.0%} for a 2 sd shift, a frozen feed and a unit error).\n")
    (RESULTS / "drift_window.md").write_text("".join(md), encoding="utf-8", newline="\n")


def main() -> None:
    res = []
    for name in MODELS:
        try:
            print(f"{name} ...", flush=True)
            res.append(study(name))
        except (core.DataUnavailable, OSError, ValueError, KeyError) as e:
            res.append({"name": name, "error": f"{type(e).__name__}: {str(e)[:120]}"})
    ok = [r for r in res if "error" not in r]
    accepted = bool(ok) and all(r["accepted"] for r in ok)
    rep = Path(os.environ.get("PYTHIA_REPORTS", "reports")) / "drift_window.json"
    rep.parent.mkdir(parents=True, exist_ok=True)
    rep.write_text(json.dumps(core.finite({"models": res, "accepted": accepted}), indent=1), encoding="utf-8")
    write(res, accepted)
    print(json.dumps(core.finite({"accepted": accepted, "failed": {r.get("model", r["name"]): r.get("failed") for r in res}})))


if __name__ == "__main__":
    main()
