"""Measured execution of the live book against the paper model's assumptions.

The main purpose of the owner's live test: a paper study cannot measure our own
latency, slippage or fees (results/pumpfun_realtime.md, "What would be needed").
The live executor writes every fill, failure and network fee to
<data>/live/pumpfun_rt/measured.jsonl; this reads it and compares it with the
assumptions every paper book and the study use (curve.Costs: the latency draw,
the priority fee, the slippage limit) and with the paper shadow's own slippage
for the same strategy (<data>/paper/pumpfun_rt/ledger.csv).

    python -m lab.pumpfun_rt.measure          write the report now and print it
    python -m lab.pumpfun_rt.measure split    every fill's latency split into its steps (docs/LATENCY.md)

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


def read_orders(path=None) -> list[dict]:
    from .live_exec import data_dir
    return read_measured(path or (data_dir() / "orders.jsonl"))


STEPS = (("signal_to_queued", "signal to order (the decision; the stream's lag behind the slot's first event)"),
         ("signal_to_received", "signal to received (the deciding event's own lag on our stream)"),
         ("received_to_fed", "received to the engine (held until the coin's creation came)"),
         ("fed_to_queued", "engine to order (the strategy's checks, the gates and the sizing)"),
         ("queued_to_built", "order to built and signed"),
         ("built_to_sent", "built to the send's answer"),
         ("queued_to_sent", "order to sent (older fills: to the sent line, which waited for the next second)"),
         ("sent_to_landed", "sent to landed (the slot's time on the stream, or the block's for a read-back)"),
         ("sent_to_confirmed", "sent to the node's confirmation (websocket or status)"),
         ("landed_to_seen", "landed to booked by the bot"),
         ("signal_to_seen", "signal to booked"))


def _quart(xs: list[float]) -> dict:
    return {"n": len(xs), "p25": _q(xs, 0.25), "median": _q(xs, 0.5), "p75": _q(xs, 0.75), "p90": _q(xs, 0.9)}


def split(rows: list[dict], orders: list[dict] | None = None) -> dict:
    """Every live fill's latency in its steps, per side, in ms: signal (the stream's time of the event that
    decided it), queued (wall time at buy()/sell()), built (signed), sent (the endpoint's answer), landed (the
    stream's slot time of our fill, or the block time of one read back from the chain), confirmed (the
    websocket's or the status read's wall time) and seen (booked). Fills written before the executor recorded
    each step take queued from send_to_land_ms and sent from the order log's sent line (written at the next
    poll, so up to a second late). By how the bot learnt of the fill: from the stream, or read back from the
    chain (the stream missed it)."""
    sent_line = {}
    for o in orders or []:
        if o.get("what") == "sent" and o.get("sig"):
            sent_line.setdefault(o["sig"], o.get("sent_at_ms") or o.get("t"))
    out = {}
    for side in ("buy", "sell"):
        steps: dict[str, list[float]] = {k: [] for k, _ in STEPS}
        via = {"stream": 0, "chain": 0}
        seen_by: dict[str, list[float]] = {"stream": [], "chain": []}
        for r in rows:
            if r.get("what") != "fill" or r.get("side") != side or r.get("land_ms") is None:
                continue
            sig_ms, land = r.get("signal_ms"), r["land_ms"]
            queued = r.get("queued_ms")
            if queued is None and r.get("send_to_land_ms") is not None:
                queued = land - r["send_to_land_ms"]
            built, sent = r.get("built_ms"), r.get("sent_at_ms") or sent_line.get(r.get("sig"))
            seen = r.get("seen_ms") or r.get("t")
            conf = r.get("confirmed_ms")

            def add(k, a, b):
                if a is not None and b is not None:
                    steps[k].append(float(a) - float(b))
            add("signal_to_queued", queued, sig_ms)
            add("signal_to_received", r.get("recv_ms"), sig_ms)
            add("received_to_fed", r.get("fed_ms"), r.get("recv_ms"))
            add("fed_to_queued", queued, r.get("fed_ms"))
            add("queued_to_built", built, queued)
            add("built_to_sent", r.get("sent_at_ms"), built)
            add("queued_to_sent", sent, queued)
            add("sent_to_landed", land, sent)
            add("sent_to_confirmed", conf, sent)
            add("landed_to_seen", seen, land)
            add("signal_to_seen", seen, sig_ms)
            how = "chain" if r.get("onchain") else "stream"
            via[how] += 1
            if seen is not None:
                seen_by[how].append(float(seen) - float(land))
        out[side] = {"steps": {k: _quart(v) for k, v in steps.items()}, "via": via,
                     "landed_to_seen_by": {k: _quart(v) for k, v in seen_by.items()}}
    return out


def split_markdown(sp: dict) -> list[str]:
    def s(d, k):
        v = d.get(k)
        return "" if v is None else f"{v / 1000:.2f}"
    lines = ["| side | step | n | p25 s | median s | p75 s | p90 s |", "|---|---|---|---|---|---|---|"]
    for side in ("buy", "sell"):
        for k, label in STEPS:
            d = sp.get(side, {}).get("steps", {}).get(k) or {}
            if d.get("n"):
                lines.append(f"| {side} | {label} | {d['n']} | {s(d, 'p25')} | {s(d, 'median')} | {s(d, 'p75')} | "
                             f"{s(d, 'p90')} |")
        for how, d in (sp.get(side, {}).get("landed_to_seen_by") or {}).items():
            if d.get("n"):
                lines.append(f"| {side} | landed to booked, fill from the {how} | {d['n']} | {s(d, 'p25')} | "
                             f"{s(d, 'median')} | {s(d, 'p75')} | {s(d, 'p90')} |")
    return lines


# The per-step breakdown the owner follows day by day: receive (the deciding event reaches us), decide (our
# own time from receiving it to the order, a wait for the coin's creation included), build, send, land.
PHASES = (("receive", "signal_ms", "recv_ms"), ("decide", "recv_ms", "queued_ms"), ("build", "queued_ms", "built_ms"),
          ("send", "built_ms", "sent_at_ms"), ("land", "sent_at_ms", "land_ms"))


def phases(rows: list[dict]) -> dict:
    """Every live fill's steps per UTC day of its signal and side, in ms: {day: {side: {step: quartiles}}}. A
    fill from before a step was stamped has no value for it; "order" (signal to order: receive and decide
    together) is there for every fill, so the days before the stamps compare too."""
    import datetime as dt
    raw: dict = {}
    for r in rows:
        if r.get("what") != "fill" or r.get("signal_ms") is None or r.get("side") not in ("buy", "sell"):
            continue
        day = dt.datetime.fromtimestamp(r["signal_ms"] / 1000, dt.timezone.utc).strftime("%Y-%m-%d")
        d = raw.setdefault(day, {}).setdefault(r["side"], {k: [] for k in ("order",) + tuple(p[0] for p in PHASES)})
        at = dict(r)
        if at.get("queued_ms") is None and r.get("send_to_land_ms") is not None and r.get("land_ms") is not None:
            at["queued_ms"] = r["land_ms"] - r["send_to_land_ms"]
        for k, a, b in (("order", "signal_ms", "queued_ms"),) + PHASES:
            if at.get(a) is not None and at.get(b) is not None:
                d[k].append(float(at[b]) - float(at[a]))
    return {day: {side: {k: _quart(v) for k, v in steps.items()} for side, steps in sides.items()}
            for day, sides in raw.items()}


def phases_markdown(ph: dict) -> list[str]:
    """Median (p90) seconds of each step, one row per day and side: the next days show what changed."""
    def cell(d):
        return "" if not d or not d.get("n") else f"{d['median'] / 1000:.2f} ({d['p90'] / 1000:.2f})"
    lines = ["| day | side | fills | signal to order | receive | decide | build | send | land |",
             "|---|---|---|---|---|---|---|---|---|"]
    for day in sorted(ph):
        for side in ("buy", "sell"):
            d = ph[day].get(side)
            if not d:
                continue
            n = max(v.get("n") or 0 for v in d.values())
            lines.append(f"| {day} | {side} | {n} | {cell(d.get('order'))} | "
                         + " | ".join(cell(d.get(k)) for k, _, _ in PHASES) + " |")
    return lines


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
    if s.get("phases"):
        lines += ["## Per step, by day", "",
                  "Median (p90) in seconds. Receive: the signal (the slot's first event on our stream) to the moment "
                  "the deciding event reached the bot. Decide: from then to the order (a wait for the coin's "
                  "creation, the strategy's checks, gates and sizing). Build: built and signed. Send: the "
                  "endpoint's answer. Land: the slot's time of our fill. Fills from before a step was stamped leave it "
                  "empty; signal to order is receive and decide together.", ""] + phases_markdown(s["phases"]) \
            + [""]
    if s.get("split"):
        lines += ["## Where the time goes", ""] + split_markdown(s["split"]) + [""]
    return "\n".join(lines)


def write_report(rows: list[dict] | None = None) -> dict:
    from .live_exec import reports_dir, write_json
    rows = read_measured() if rows is None else rows
    rule = next((r.get("rule") for r in reversed(rows) if r.get("rule")), None)
    s = summarise(rows, paper=paper_slip(rule))
    s["split"] = split(rows, read_orders())
    s["phases"] = phases(rows)
    d = reports_dir()
    write_json(d / "execution.json", s)
    (d / "execution.md").write_text(markdown(s), encoding="utf-8")
    return s


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["split"]:
        print("\n".join(split_markdown(split(read_measured(), read_orders()))))
        return 0
    s = write_report()
    print(markdown(s))
    return 0


if __name__ == "__main__":
    sys.exit(main())
