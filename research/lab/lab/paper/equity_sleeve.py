"""The Crypto + SPY forward test, judged as registered (results/equity_sleeve_prereg.md).

    python -m lab.paper.equity_sleeve                 the record so far and the verdict (markdown)
    python -m lab.paper.equity_sleeve --json          the same as JSON
    python -m lab.paper.equity_sleeve --reference     add the backtest of the exact mix (context, not judged)
    options: --treatment ID --control ID (defaults below), --reports DIR (<data>/reports/forward)

Written after the registration and implementing it, nothing else:

- Each autopilot's equity once a day from the daily forward report
  (reports/forward/<day>.json). Point 0 is the first report after both have run
  24 hours; 90 days later the test ends. A day without a report merges into the
  next return and is named. A restart of either (another start time) restarts
  the test from the first report after it.
- Sharpe: mean / sd of the daily returns x sqrt(365). Max drawdown on the daily
  equity points.
- Pass: Sharpe(treatment) > Sharpe(control), drawdown(treatment) < drawdown(control),
  and the 5 % quantile of Sharpe(treatment) - Sharpe(control) over a stationary
  block bootstrap of the paired daily returns (mean block 10 days, 4,000 draws,
  seed 20261021) above 0.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

from .. import report

TREATMENT = "ap_crypto_spy"
CONTROL = "ap_breakout_alone"
DAYS = 90
YEAR = 365
BLOCK = 10
DRAWS = 4000
SEED = 20261021
DAY_MS = 86_400_000


def read_reports(d: Path) -> list[dict]:
    """The daily forward reports in date order (files named YYYY-MM-DD.json)."""
    out = []
    for p in sorted(Path(d).glob("20??-??-??.json")):
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return out


def _row(rep: dict, ap_id: str) -> dict | None:
    return next((a for a in rep.get("autopilots") or [] if a.get("name") == ap_id), None)


def record(reports: list[dict], treatment: str = TREATMENT, control: str = CONTROL) -> dict:
    """(times, equity treatment, equity control, gaps, restarts) from the reports,
    from point 0 on, at most DAYS days."""
    times, et, ec, gaps, notes = [], [], [], [], []
    started = None
    for rep in sorted(reports, key=lambda r: int(r.get("generated_ms") or 0)):
        t, c = _row(rep, treatment), _row(rep, control)
        if not t or not c:
            continue
        key = (t.get("started_ms"), c.get("started_ms"))
        if started is not None and key != started:
            notes.append(f"restart seen in the report of {rep.get('generated')}: the test starts again from there")
            times, et, ec, gaps = [], [], [], []
        started = key
        if min(float(t.get("elapsed_days") or 0), float(c.get("elapsed_days") or 0)) < 1:
            continue
        if t.get("state") not in ("running", "paused") or c.get("state") not in ("running", "paused"):
            notes.append(f"one of them is {t.get('state')}/{c.get('state')} in the report of {rep.get('generated')}")
            break
        ms = int(rep.get("generated_ms") or 0)
        if times and ms - times[0] > DAYS * DAY_MS + DAY_MS // 2:
            break
        if times and ms - times[-1] > 1.5 * DAY_MS:
            gaps.append(rep.get("generated"))
        times.append(ms)
        et.append(float(t["equity"]))
        ec.append(float(c["equity"]))
    return {"times": times, "treatment": et, "control": ec, "gaps": gaps, "notes": notes}


def sharpe(r: np.ndarray) -> float:
    sd = r.std(ddof=1) if len(r) > 1 else 0.0
    return float(r.mean() / sd * math.sqrt(YEAR)) if sd > 0 else 0.0


def max_dd(eq: np.ndarray) -> float:
    if len(eq) == 0:
        return 0.0
    return float((1 - eq / np.maximum.accumulate(eq)).max())


def boot_diff(rt: np.ndarray, rc: np.ndarray, draws: int = DRAWS, block: int = BLOCK, seed: int = SEED) -> np.ndarray:
    """Stationary block bootstrap (Politis and Romano) of Sharpe(t) - Sharpe(c) on the same days."""
    n = len(rt)
    rng = np.random.default_rng(seed)
    p = 1.0 / block
    out = np.empty(draws)
    for k in range(draws):
        idx = np.empty(n, dtype=int)
        i = rng.integers(n)
        for j in range(n):
            if j > 0 and rng.random() < p:
                i = rng.integers(n)
            idx[j] = i
            i = (i + 1) % n
        out[k] = sharpe(rt[idx]) - sharpe(rc[idx])
    return out


def judge(rec: dict) -> dict:
    et, ec = np.array(rec["treatment"]), np.array(rec["control"])
    days = (rec["times"][-1] - rec["times"][0]) / DAY_MS if len(rec["times"]) > 1 else 0.0
    out = {"days": days, "points": len(et), "gaps": rec["gaps"], "notes": rec["notes"]}
    if len(et) < 3:
        return {**out, "verdict": "early", "sentence": "Not started yet, or under three daily points."}
    rt, rc = et[1:] / et[:-1] - 1, ec[1:] / ec[:-1] - 1
    st, sc, dt, dc = sharpe(rt), sharpe(rc), max_dd(et), max_dd(ec)
    b = boot_diff(rt, rc)
    p05, p95 = float(np.percentile(b, 5)), float(np.percentile(b, 95))
    rules = {"sharpe_higher": st > sc, "drawdown_lower": dt < dc, "band_above_zero": p05 > 0}
    out.update(sharpe_treatment=st, sharpe_control=sc, dd_treatment=dt, dd_control=dc,
               return_treatment=float(et[-1] / et[0] - 1), return_control=float(ec[-1] / ec[0] - 1),
               boot_p05=p05, boot_p95=p95, rules=rules)
    if days < DAYS - 0.5:
        out["verdict"] = "running"
        out["sentence"] = (f"Day {days:.0f} of {DAYS}: Sharpe {st:.2f} against {sc:.2f}, drawdown {dt:.1%} against "
                           f"{dc:.1%}. Not judged before day {DAYS}.")
    elif all(rules.values()):
        out["verdict"] = "pass"
        out["sentence"] = "Pass: higher Sharpe, lower drawdown and the bootstrap band above zero."
    elif rules["sharpe_higher"] and rules["drawdown_lower"]:
        out["verdict"] = "consistent"
        out["sentence"] = "Consistent with X7 B, not shown: higher Sharpe and lower drawdown, the band includes zero."
    else:
        out["verdict"] = "fail"
        out["sentence"] = "X7 B's after-the-fact count did not hold forward."
    return out


def reference() -> dict | None:
    """The exact mix on the existing panel, as context only (not part of the judgement):
    80 % breakout_top10 at 35 bps and 20 % SPY bought and held, the SPY sleeve set back to
    20 % on the first day of each month, against breakout_top10 alone, out of sample from
    2024. None when the lab data is not there."""
    try:
        from ..experiments import book_portfolio as bp
        days, books = bp.crypto_books()
        eq = bp.equity_series(days)
    except Exception:  # noqa: BLE001 - context only
        return None
    b, spy = books["breakout_top10"], eq["spy"]
    w = 0.2
    net = np.zeros(len(days))
    for t in range(len(days)):
        d = days[t].astype(object)
        if t == 0 or d.day == 1:
            moved = abs(w - 0.2)
            w = 0.2
            net[t] -= moved * 0.0035 + moved * 0.0002
        g = (1 - w) * b[t] + w * spy[t]
        net[t] += g
        w = w * (1 + spy[t]) / (1 + g) if 1 + g > 0 else 0.2
    m = days >= bp.SPLIT
    eq_m, eq_b = np.cumprod(1 + net[m]), np.cumprod(1 + b[m])
    return {"from": str(days[m][0]), "to": str(days[m][-1]),
            "sharpe_mix": sharpe(net[m]), "sharpe_breakout": sharpe(b[m]),
            "dd_mix": max_dd(eq_m), "dd_breakout": max_dd(eq_b)}


def markdown(res: dict, ref: dict | None = None) -> str:
    lines = ["# Crypto + SPY forward test (results/equity_sleeve_prereg.md)\n", res["sentence"] + "\n"]
    if res.get("rules"):
        lines.append(f"- Sharpe {res['sharpe_treatment']:.2f} (treatment) against {res['sharpe_control']:.2f} (control)")
        lines.append(f"- drawdown {res['dd_treatment']:.1%} against {res['dd_control']:.1%}")
        lines.append(f"- return {res['return_treatment']:+.2%} against {res['return_control']:+.2%}")
        lines.append(f"- bootstrap of the Sharpe difference: 5 % {res['boot_p05']:+.2f}, 95 % {res['boot_p95']:+.2f}")
        lines.append(f"- {res['points']} daily points over {res['days']:.1f} days")
    for g in res.get("gaps") or []:
        lines.append(f"- no report the day before {g}: merged into the next return")
    for n in res.get("notes") or []:
        lines.append(f"- {n}")
    if ref:
        lines.append(f"\nContext, not judged: the exact mix on the existing panel ({ref['from']} to {ref['to']}): "
                     f"Sharpe {ref['sharpe_mix']:.2f} against {ref['sharpe_breakout']:.2f} for breakout_top10 alone, "
                     f"drawdown {ref['dd_mix']:.1%} against {ref['dd_breakout']:.1%}.")
    return "\n".join(lines) + "\n"


def _arg(argv: list[str], key: str, default: str) -> str:
    return argv[argv.index(key) + 1] if key in argv and argv.index(key) + 1 < len(argv) else default


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    d = Path(_arg(argv, "--reports", str(report.REPORTS / "forward")))
    rec = record(read_reports(d), _arg(argv, "--treatment", TREATMENT), _arg(argv, "--control", CONTROL))
    res = judge(rec)
    ref = reference() if "--reference" in argv else None
    text = json.dumps({**res, "reference": ref}, indent=1, default=float) if "--json" in argv else markdown(res, ref)
    sys.stdout.buffer.write(text.encode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
