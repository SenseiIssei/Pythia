"""X9 c: is "shift" on every zoo model a property of the inputs or of the test?

    python -m lab.models.drift_study            # M8 (= M8q's inputs), M10, M12 where their data loads

Pre-registered in results/model_review_prereg.md. Bins from the training rows
before 2024-01-01; every window of the model's drift length, stepping 7 days,
checked with today's rule (core.drift_check, the model takes its worst input)
and with the calibrated rule (core.drift_calibration: per-input cuts at the
99th percentile of the training windows, k inputs over their cuts for a model
"shift"). Windows that end before 2024 are in sample, windows that start in
2024 or later out of sample. Power: one input moved by one training standard
deviation for a whole out-of-sample window.

Writes results/drift_study.md and <reports>/drift_study.json.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import polars as pl

from . import core, zoo

CUT = core.us("2024-01-01")
MODELS = ("m8_direction", "m10_vol_regime", "m12_cross_asset")
MISCALIBRATED = 0.50
ACCEPT_OOS_SHIFT = 0.20
ACCEPT_POWER = 0.90
DRIFT_REVIEW = 0.10
RESULTS = Path(__file__).resolve().parents[2] / "results"


def train_bins(spec: core.Spec, train: pl.DataFrame) -> dict:
    return {f: core.drift_bins(train[f].fill_null(np.nan).to_numpy().astype(float))
            for f in spec.features if f not in spec.calendar and f in train.columns
            and np.isfinite(train[f].fill_null(np.nan).to_numpy().astype(float)).sum() >= 50}


def plain_level(checks: dict) -> str:
    lv = [c["level"] for c in checks.values()]
    return "drift" if "drift" in lv else "shift" if "shift" in lv else "stable"


def rates(levels: list[str]) -> dict:
    n = len(levels)
    if not n:
        return {"windows": 0}
    return {"windows": n, "shift_or_worse": float(np.mean([x != "stable" for x in levels])),
            "drift": float(np.mean([x == "drift" for x in levels]))}


def power(bins: dict, panel: pl.DataFrame, train: pl.DataFrame, cal: dict, days: int) -> dict:
    """Share of (out-of-sample window, input) pairs flagged when that input alone is moved
    up by one training standard deviation over the whole window."""
    sd = {f: float(np.nanstd(train[f].fill_null(np.nan).to_numpy().astype(float))) for f in bins}
    ts = panel["ts_us"].to_numpy()
    cols = {f: panel[f].fill_null(np.nan).to_numpy().astype(float) for f in bins}
    wins = core.drift_windows(bins, panel, days, start_us=CUT)
    hit_cal = hit_plain = total = 0
    for w in wins:
        m = (ts >= w["from"]) & (ts < w["to"])
        for f in bins:
            if f not in w["checks"]:
                continue
            c = core.drift_check(bins[f], cols[f][m] + sd[f])
            if c is None:
                continue
            checks = dict(w["checks"])
            checks[f] = c
            total += 1
            hit_cal += core.calibrated_level(checks, cal)[0] != "stable"
            hit_plain += plain_level(checks) != "stable"
    return {"pairs": total, "calibrated": hit_cal / total if total else None, "plain": hit_plain / total if total else None}


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
    cal = core.drift_calibration(bins, w_is, days)
    out = {"model": spec.code, "name": name, "days": days, "inputs": len(bins), "train_rows": train.height,
           "plain_is": rates([plain_level(w["checks"]) for w in w_is]),
           "plain_oos": rates([plain_level(w["checks"]) for w in w_oos])}
    # Which inputs trip today's rule most often in sample, and why (PSI or outside share).
    trips = {}
    for f in bins:
        cs = [w["checks"][f] for w in w_is if f in w["checks"]]
        if cs:
            trips[f] = {"shift_share": float(np.mean([c["level"] != "stable" for c in cs])),
                        "psi_median": float(np.median([c["psi"] for c in cs])),
                        "psi_q99": float(np.quantile([c["psi"] for c in cs], 0.99)),
                        "outside_q99": float(np.quantile([c["outside_pct"] for c in cs], 0.99))}
    out["inputs_in_sample"] = dict(sorted(trips.items(), key=lambda kv: -kv[1]["shift_share"]))
    if cal:
        out["calibration"] = {k: v for k, v in cal.items() if k != "cuts"}
        out["cal_is"] = rates([core.calibrated_level(w["checks"], cal)[0] for w in w_is])
        out["cal_oos"] = rates([core.calibrated_level(w["checks"], cal)[0] for w in w_oos])
        out["power"] = power(bins, panel, train, cal, days)
        # Today's verdict under each rule on the newest window.
        last = core.drift_windows(bins, panel, days, start_us=int(panel["ts_us"].max()) - days * core.DAY_US)
        if last:
            out["newest_plain"] = plain_level(last[-1]["checks"])
            out["newest_calibrated"] = core.calibrated_level(last[-1]["checks"], cal)
    # Addendum (after the registered form failed): Bonferroni cuts per input, k = 1.
    cal2 = core.drift_calibration_per_input(bins, w_is, days)
    if cal2:
        out["calibration2"] = {k: v for k, v in cal2.items() if k != "cuts"}
        out["cal2_is"] = rates([core.calibrated_level(w["checks"], cal2)[0] for w in w_is])
        out["cal2_oos"] = rates([core.calibrated_level(w["checks"], cal2)[0] for w in w_oos])
        out["power2"] = power(bins, panel, train, cal2, days)
        last = core.drift_windows(bins, panel, days, start_us=int(panel["ts_us"].max()) - days * core.DAY_US)
        if last:
            out["newest_calibrated2"] = core.calibrated_level(last[-1]["checks"], cal2)
    return out


def verdict(res: list[dict]) -> dict:
    ok = [r for r in res if "cal_oos" in r]
    mis = [r["model"] for r in res if r["plain_is"].get("shift_or_worse", 0) > MISCALIBRATED]
    accept = bool(ok) and all(r["cal_oos"]["shift_or_worse"] <= ACCEPT_OOS_SHIFT for r in ok) and \
        all((r["power"]["calibrated"] or 0) >= ACCEPT_POWER for r in ok)
    review_drift = [r["model"] for r in res if r["plain_is"].get("drift", 0) > DRIFT_REVIEW]
    ok2 = [r for r in res if "cal2_oos" in r]
    accept2 = bool(ok2) and all(r["cal2_oos"]["shift_or_worse"] <= ACCEPT_OOS_SHIFT for r in ok2) and \
        all((r["power2"]["calibrated"] or 0) >= ACCEPT_POWER for r in ok2)
    return {"miscalibrated": mis, "accept_fix": accept and bool(mis), "drift_rule_review": review_drift,
            "accept_fix2_addendum": accept2 and bool(mis)}


def write(res: list[dict], v: dict) -> None:
    def p(x):
        return "n/a" if x is None else f"{x * 100:.0f} %"
    md = ["# X9 c: the zoo's drift test\n\n",
          "Generated by `python -m lab.models.drift_study` (pre-registered in `model_review_prereg.md`). Bins from "
          "training rows before 2024; windows of each model's drift length stepping 7 days; in sample = windows "
          "ending before 2024, out of sample = windows starting in 2024 or later.\n\n",
          "| model | inputs | window | windows IS / OOS | today's rule: shift IS | OOS | drift IS | OOS | calibrated k | "
          "calibrated shift IS | OOS | power plain | power calibrated |\n|---|---|---|---|---|---|---|---|---|---|---|---|---|\n"]
    for r in res:
        if "error" in r:
            md.append(f"| {r['name']} | data not available here: {r['error']} |" + " |" * 11 + "\n")
            continue
        c = r.get("calibration") or {}
        md.append(f"| {r['model']} | {r['inputs']} | {r['days']} d | {r['plain_is']['windows']} / {r['plain_oos']['windows']} | "
                  f"{p(r['plain_is'].get('shift_or_worse'))} | {p(r['plain_oos'].get('shift_or_worse'))} | "
                  f"{p(r['plain_is'].get('drift'))} | {p(r['plain_oos'].get('drift'))} | {c.get('k', 'n/a')} | "
                  f"{p((r.get('cal_is') or {}).get('shift_or_worse'))} | {p((r.get('cal_oos') or {}).get('shift_or_worse'))} | "
                  f"{p((r.get('power') or {}).get('plain'))} | {p((r.get('power') or {}).get('calibrated'))} |\n")
    for r in res:
        if "error" in r:
            continue
        md.append(f"\n## {r['model']}: inputs by how often today's rule calls them shifted in sample\n\n"
                  "| input | windows shifted | median PSI | PSI 99 % | outside 99 % |\n|---|---|---|---|---|\n")
        for f, x in list(r["inputs_in_sample"].items())[:12]:
            md.append(f"| {f} | {p(x['shift_share'])} | {x['psi_median']:.2f} | {x['psi_q99']:.2f} | {x['outside_q99']:.1f} % |\n")
        if "newest_plain" in r:
            md.append(f"\nNewest window: today's rule says {r['newest_plain']}, the calibrated rule "
                      f"{r['newest_calibrated'][0]} ({r['newest_calibrated'][1]} inputs over their cuts, k "
                      f"{r['calibration']['k']}).\n")
    md.append("\n## Addendum, chosen after the registered form failed: one cut per input, Bonferroni, k = 1\n\n"
              "Each input's cut at the 1 - 0.05 / inputs quantile of its training windows (PSI and outside share), "
              "\"shift\" when any one input is over its cut, \"drift\" when an input is outside the trained range "
              "more often than in any such training window (at least 5 %). Judged by the same acceptance rule, "
              "but it was picked after seeing the first form's numbers, so it is a candidate for the next "
              "registration, not a result.\n\n"
              "| model | quantile | shift or worse IS | OOS | drift IS | OOS | power | newest window |\n"
              "|---|---|---|---|---|---|---|---|\n")
    for r in res:
        if "cal2_oos" not in r:
            continue
        nw = r.get("newest_calibrated2")
        md.append(f"| {r['model']} | {r['calibration2']['quantile']:.4f} | {p(r['cal2_is']['shift_or_worse'])} | "
                  f"{p(r['cal2_oos']['shift_or_worse'])} | {p(r['cal2_is']['drift'])} | {p(r['cal2_oos']['drift'])} | "
                  f"{p(r['power2']['calibrated'])} | {nw[0] if nw else 'n/a'} |\n")
    md.append(f"\nAddendum form passes the acceptance rule: {'yes' if v.get('accept_fix2_addendum') else 'no'}.\n")
    md.append(f"\n**Verdict.** Miscalibrated (over {MISCALIBRATED:.0%} of in-sample windows shifted): "
              f"{', '.join(v['miscalibrated']) or 'none'}. Fix accepted: {'yes' if v['accept_fix'] else 'no'} "
              f"(needs out-of-sample shift at most {ACCEPT_OOS_SHIFT:.0%} and power at least {ACCEPT_POWER:.0%} for every "
              f"model). Drift rule (over {DRIFT_REVIEW:.0%} false alarms in sample): "
              f"{', '.join(v['drift_rule_review']) or 'none'}.\n")
    (RESULTS / "drift_study.md").write_text("".join(md), encoding="utf-8", newline="\n")


def main() -> None:
    res = []
    for name in MODELS:
        try:
            print(f"{name} ...", flush=True)
            res.append(study(name))
        except (core.DataUnavailable, OSError, ValueError, KeyError) as e:
            res.append({"name": name, "error": f"{type(e).__name__}: {str(e)[:120]}"})
    v = verdict([r for r in res if "error" not in r])
    rep = Path(os.environ.get("PYTHIA_REPORTS", "reports")) / "drift_study.json"
    rep.parent.mkdir(parents=True, exist_ok=True)
    rep.write_text(json.dumps(core.finite({"models": res, "verdict": v}), indent=1), encoding="utf-8")
    write(res, v)
    print(json.dumps(core.finite(v)), flush=True)


if __name__ == "__main__":
    main()
