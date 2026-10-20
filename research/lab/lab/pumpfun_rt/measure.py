"""Measured execution of the live book against the paper model's assumptions.

The main purpose of the owner's live test: a paper study cannot measure our own
latency, slippage or fees (results/pumpfun_realtime.md, "What would be needed").
The live executor writes every fill, failure and network fee to
<data>/live/pumpfun_rt/measured.jsonl; this reads it and compares it with the
assumptions every paper book and the study use (curve.Costs: the latency draw,
the priority fee, the slippage limit) and with the paper shadow's own slippage
for the same strategy (<data>/paper/pumpfun_rt/ledger.csv).

    python -m lab.pumpfun_rt.measure          write the report now and print it

Output: reports/pumpfun_rt/execution.json and execution.md. The study adds the
summary to its daily report ("Measured execution"); the live daily card shows
the latency against the assumption. Nothing here changes a paper number: the
replays keep the pre-registered assumptions, the comparison is reported.
"""

from __future__ import annotations

import csv
import json
import math
import sys
import time

from . import curve as C


def _q(xs: list[float], q: float) -> float | None:
    if not xs:
        return None
    s = sorted(xs)
    k = (len(s) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def _dist(xs: list[float]) -> dict:
    return {"n": len(xs), "median": _q(xs, 0.5), "p10": _q(xs, 0.1), "p90": _q(xs, 0.9)}


def read_measured(path=None) -> list[dict]:
    from .live_exec import data_dir
    p = path or (data_dir() / "measured.jsonl")
    out = []
    try:
        with open(p, encoding="utf-8") as fh:
            for line in fh:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        pass
    return out


def paper_slip(rule: str | None, path=None) -> dict:
    """The paper shadow's modelled slippage of the same strategy (its ledger's `slip`)."""
    from .live import paper_dir
    p = path or (paper_dir() / "ledger.csv")
    xs = []
    try:
        with open(p, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                if rule and r.get("rule") != rule:
                    continue
                try:
                    xs.append(float(r["slip"]))
                except (KeyError, TypeError, ValueError):
                    continue
    except OSError:
        pass
    return _dist(xs)


def summarise(rows: list[dict], costs: C.Costs | None = None, paper: dict | None = None) -> dict:
    costs = costs or C.Costs()
    fills = [r for r in rows if r.get("what") == "fill"]
    fees = {r["sig"]: int(r["fee_l"]) for r in rows if r.get("what") == "fee" and r.get("sig")}
    failed = [r for r in rows if r.get("what") == "failed"]
    buys = [r for r in fills if r.get("side") == "buy"]
    sells = [r for r in fills if r.get("side") == "sell"]
    lat_buy = [float(r["lat_ms"]) for r in buys if r.get("lat_ms") is not None]
    lat_sell = [float(r["lat_ms"]) for r in sells if r.get("lat_ms") is not None]
    send = [float(r["send_to_land_ms"]) for r in fills if r.get("send_to_land_ms") is not None]
    slip_buy = [float(r["slip"]) for r in buys if r.get("slip") is not None]
    slip_sell = [float(r["slip"]) for r in sells if r.get("slip") is not None]
    fee_l = [fees[r["sig"]] for r in fills if r.get("sig") in fees]
    rules = sorted({r.get("rule") for r in fills if r.get("rule")})
    lb = _dist(lat_buy)
    assumed = {"lat_median_ms": costs.lat_median_ms, "lat_lo_ms": costs.lat_lo_ms, "lat_hi_ms": costs.lat_hi_ms,
               "tx_fee_sol": costs.tx_lamports() / C.LAMPORTS, "slip_tol": costs.slip_tol}
    out = {"updated_ms": int(time.time() * 1000), "modes": sorted({r.get("mode") for r in rows if r.get("mode")}),
           "rules": rules, "fills": len(fills), "buys": len(buys), "sells": len(sells),
           "lat_buy_ms": lb, "lat_sell_ms": _dist(lat_sell), "send_to_land_ms": _dist(send),
           "slip_buy": _dist(slip_buy), "slip_sell": _dist(slip_sell),
           "fee_sol": {k: (v / C.LAMPORTS if v is not None else None) for k, v in _dist(fee_l).items() if k != "n"}
           | {"n": len(fee_l)},
           "failed": len(failed), "failed_why": _count(r.get("why") for r in failed),
           "assumed": assumed, "paper_slip": paper or {"n": 0, "median": None, "p10": None, "p90": None},
           "lat_ratio": (lb["median"] / costs.lat_median_ms) if lb["median"] is not None else None}
    out["verdict"] = verdict(out)
    return out


def _count(xs) -> dict:
    out: dict[str, int] = {}
    for x in xs:
        k = str(x or "?")
        k = "slippage or limit" if "slippage" in k.lower() or "6001" in k or "6002" in k else k[:60]
        out[k] = out.get(k, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def verdict(s: dict) -> str:
    lb = s["lat_buy_ms"]
    if not lb["n"]:
        return "No live fills yet: nothing measured."
    a = s["assumed"]
    word = ("slower than" if lb["median"] > a["lat_median_ms"] * 1.1 else
            "faster than" if lb["median"] < a["lat_median_ms"] * 0.9 else "in line with")
    out = (f"{lb['n']} live buys landed a median {lb['median']:.0f} ms after the signal "
           f"(10 to 90 %: {lb['p10']:.0f} to {lb['p90']:.0f} ms), {word} the paper assumption of "
           f"{a['lat_median_ms']:.0f} ms ({a['lat_lo_ms']:.0f} to {a['lat_hi_ms']:.0f}).")
    sb = s["slip_buy"]
    if sb["n"]:
        ps = s["paper_slip"]
        out += f" Buy slippage median {sb['median'] * 100:+.1f} %"
        out += (f" against {ps['median'] * 100:+.1f} % on paper for the same strategy." if ps.get("median") is not None
                else ".")
    f = s["fee_sol"]
    if f.get("n"):
        out += f" Network fee median {f['median']:.6f} SOL against {a['tx_fee_sol']:.6f} assumed."
    if s["failed"]:
        out += f" {s['failed']} orders failed."
    if s["lat_ratio"] is not None and s["lat_ratio"] > 1.1:
        out += (" The paper model flatters: compare the study's doubled-latency column, not its base column.")
    return out


def markdown(s: dict) -> str:
    def ms(d):
        return "n/a" if d["median"] is None else f"{d['median']:.0f} ({d['p10']:.0f} to {d['p90']:.0f})"

    def pc(d):
        return "n/a" if d.get("median") is None else (f"{d['median'] * 100:+.2f} % "
                                                     f"({d['p10'] * 100:+.2f} to {d['p90'] * 100:+.2f})")
    a = s["assumed"]
    lines = ["# pump.fun live execution, measured", "", s["verdict"], "",
             f"Modes: {', '.join(s['modes']) or 'none'}; strategies: {', '.join(s['rules']) or 'none'}.", "",
             "| what | measured, median (10 to 90 %) | n | paper assumption |", "|---|---|---|---|",
             f"| buy latency, signal to landing, ms | {ms(s['lat_buy_ms'])} | {s['lat_buy_ms']['n']} | "
             f"{a['lat_median_ms']:.0f} ({a['lat_lo_ms']:.0f} to {a['lat_hi_ms']:.0f}) |",
             f"| sale latency, signal to landing, ms | {ms(s['lat_sell_ms'])} | {s['lat_sell_ms']['n']} | the same |",
             f"| send to landing, ms | {ms(s['send_to_land_ms'])} | {s['send_to_land_ms']['n']} | |",
             f"| buy slippage against the signal price | {pc(s['slip_buy'])} | {s['slip_buy']['n']} | "
             f"paper shadow {pc(s['paper_slip'])}, limit {a['slip_tol'] * 100:.0f} % |",
             f"| sale proceeds against the mark at the exit signal | {pc(s['slip_sell'])} | {s['slip_sell']['n']} | "
             f"the curve at landing |",
             f"| network fee per transaction, SOL | "
             f"{'n/a' if not s['fee_sol'].get('n') else format(s['fee_sol']['median'], '.6f')} | "
             f"{s['fee_sol'].get('n', 0)} | {a['tx_fee_sol']:.6f} |", "",
             f"Failed orders: {s['failed']}" + ("" if not s["failed_why"] else " (" + ", ".join(
                 f"{k} {v}" for k, v in s["failed_why"].items()) + ")"), ""]
    return "\n".join(lines)


def write_report(rows: list[dict] | None = None) -> dict:
    from .live_exec import reports_dir, write_json
    rows = read_measured() if rows is None else rows
    rule = next((r.get("rule") for r in reversed(rows) if r.get("rule")), None)
    s = summarise(rows, paper=paper_slip(rule))
    d = reports_dir()
    write_json(d / "execution.json", s)
    (d / "execution.md").write_text(markdown(s), encoding="utf-8")
    return s


def main(argv: list[str] | None = None) -> int:
    s = write_report()
    print(markdown(s))
    return 0


if __name__ == "__main__":
    sys.exit(main())
