"""How our on-chain swaps really execute, against the pump.fun bot's measured execution and Kraken's fees.

    python -m lab.onchain.execution      reports/onchain/execution.md and .json (the job onchain-execution)

Reads live/onchain/execution.jsonl (one line per sent swap, written by live_exec: signal to send,
send to land, the fee paid split into base, priority and Sender tip, what came out against the
quote), reports/pumpfun_rt/execution.json (the pump.fun bot's measured buys and sells) and
reports/onchain/latest.json (the paper book's probes: Kraken's one-way cost per coin; without them
the taker fee, lab.onchain.book.KRAKEN_TAKER_BPS). Says which send path landed faster. Both bots
send through Helius Sender and the plain RPC with a priority fee; when ours lands faster than the
pump.fun bot's, the report names the pieces the pump.fun executor could take over (this module
changes nothing there). Reads files only.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from . import book as B
from . import live_exec as LX

MIN_N = 5                                # fewer swaps: the comparison says it is too early


def _q(xs: list[float], q: float) -> float | None:
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    k = (len(xs) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def dist(xs: list) -> dict:
    xs = [float(x) for x in xs if isinstance(x, (int, float))]
    return {"n": len(xs), "median": _q(xs, 0.5), "p10": _q(xs, 0.1), "p90": _q(xs, 0.9)}


def _num(v) -> float | None:
    return float(v) if isinstance(v, (int, float)) else None


def total_cost_bps(r: dict) -> float | None:
    """What a filled swap really cost against Jupiter's prices: value in minus value out plus the fee and tip in USD."""
    i, o, sol = _num(r.get("in_usd")), _num(r.get("out_usd")), _num(r.get("sol_usd"))
    if not i or o is None:
        return None
    fee = ((_num(r.get("fee_l")) or 0) + (_num(r.get("tip_l")) or 0)) / 1e9 * (sol or 0)
    return (i - o + fee) / i * 1e4


def summarise(rows: list[dict]) -> dict:
    sent = [r for r in rows if r.get("sig")]
    filled = [r for r in sent if r.get("status") == "filled"]
    return {"swaps": len(sent), "filled": len(filled), "failed": len(sent) - len(filled),
            "modes": sorted({str(r.get("mode")) for r in sent if r.get("mode")}),
            "signal_to_send_ms": dist([r.get("signal_to_send_ms") for r in sent]),
            "plan_to_send_ms": dist([r.get("plan_to_send_ms") for r in sent]),
            "send_to_land_ms": dist([r.get("send_to_land_ms") for r in sent]),
            "fee_sol": dist([(_num(r.get("fee_l")) or 0) / 1e9 for r in sent if r.get("fee_l") is not None]),
            "base_sol": dist([_num(r.get("base_l")) / 1e9 for r in sent if _num(r.get("base_l")) is not None]),
            "priority_sol": dist([_num(r.get("priority_l")) / 1e9 for r in sent if _num(r.get("priority_l")) is not None]),
            "tip_sol": dist([_num(r.get("tip_l")) / 1e9 for r in sent if _num(r.get("tip_l")) is not None]),
            "quote_slip_bps": dist([r.get("quote_slip_bps") for r in filled]),
            "cost_bps": dist([r.get("cost_bps") for r in filled]),
            "total_cost_bps": dist([total_cost_bps(r) for r in filled]),
            "via": {v: sum(1 for r in sent if r.get("via") == v) for v in sorted({str(r.get("via")) for r in sent})}}


def kraken_view(latest: dict | None) -> dict:
    """Kraken's one-way cost: the paper book's probes per coin (median), else its taker fee alone."""
    probes = ((latest or {}).get("summary") or {}).get("probes") or []
    k = [p.get("kraken_oneway_bps") for p in probes if isinstance(p, dict)]
    o = [p.get("onchain_oneway_bps") for p in probes if isinstance(p, dict)]
    return {"taker_bps": B.KRAKEN_TAKER_BPS, "oneway_bps": dist(k), "paper_onchain_oneway_bps": dist(o),
            "coins": len(k)}


def compare(ours: dict, pump: dict | None) -> dict:
    """The send paths side by side: which lands faster, and what that means for the pump.fun executor."""
    a = (ours.get("send_to_land_ms") or {}).get("median")
    b = ((pump or {}).get("send_to_land_ms") or {}).get("median")
    out = {"ours_send_to_land_ms": a, "pumpfun_send_to_land_ms": b, "faster": None, "note": None}
    if ours.get("swaps", 0) < MIN_N or a is None:
        out["note"] = f"Too early: fewer than {MIN_N} on-chain swaps measured."
        return out
    if b is None:
        out["note"] = "The pump.fun bot has no measured send to land yet."
        return out
    if a < b:
        out["faster"] = "onchain"
        out["note"] = (f"The on-chain trader lands a median {a:.0f} ms after the send against {b:.0f} ms for the "
                       "pump.fun bot. Its pieces (Helius Sender and the plain RPC together, a priority fee capped in "
                       "code, the same signed bytes again every 2 s until the blockhash expires) are worth taking "
                       "over into the pump.fun executor, in a task of its own.")
    else:
        out["faster"] = "pumpfun"
        out["note"] = (f"The pump.fun bot lands faster ({b:.0f} ms against {a:.0f} ms for the on-chain trader); "
                       "nothing to take over from this path.")
    return out


def _ms(d: dict | None) -> str:
    if not d or d.get("median") is None:
        return "n/a"
    return f"{d['median']:,.0f} ms (10 to 90 %: {d['p10']:,.0f} to {d['p90']:,.0f})"


def _bps(d: dict | None) -> str:
    if not d or d.get("median") is None:
        return "n/a"
    return f"{d['median']:.1f} bps (10 to 90 %: {d['p10']:.1f} to {d['p90']:.1f})"


def _sol(d: dict | None) -> str:
    if not d or d.get("median") is None:
        return "n/a"
    return f"{d['median']:.6f} SOL"


def build(rows: list[dict], pump: dict | None, latest: dict | None, now_ms: int) -> dict:
    ours = summarise(rows)
    k = kraken_view(latest)
    cmp = compare(ours, pump)
    tc = (ours["total_cost_bps"] or {}).get("median")
    kk = (k["oneway_bps"] or {}).get("median") or k["taker_bps"]
    verdict = (f"{ours['swaps']} on-chain swaps sent, {ours['filled']} filled. " + (cmp["note"] or "") +
               (f" A filled swap cost a median {tc:.1f} bps in all (price, fee and tip) against {kk:.1f} bps one way "
                "at Kraken." if tc is not None else ""))
    return {"updated_ms": now_ms, "onchain": ours, "pumpfun": pump if isinstance(pump, dict) else None,
            "kraken": k, "compare": cmp, "verdict": verdict}


def markdown(rep: dict) -> str:
    o, p, k, c = rep["onchain"], rep.get("pumpfun") or {}, rep["kraken"], rep["compare"]
    lines = ["# On-chain execution", "",
             f"Updated {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(rep['updated_ms'] / 1000))}. "
             f"Modes: {', '.join(o['modes']) or 'none yet'}.", "", rep["verdict"], "",
             "| | on-chain trader | pump.fun bot |", "|---|---|---|",
             f"| swaps sent (filled) | {o['swaps']} ({o['filled']}) | {p.get('fills', 'n/a')} |",
             f"| signal to send | {_ms(o['signal_to_send_ms'])} | "
             f"{_ms(((p.get('split') or {}).get('buy') or {}).get('steps', {}).get('signal_to_queued'))} (to queued) |",
             f"| send to land | {_ms(o['send_to_land_ms'])} | {_ms(p.get('send_to_land_ms'))} |",
             f"| network fee | {_sol(o['fee_sol'])} | {_sol(p.get('fee_sol'))} |",
             f"| of it base / priority | {_sol(o['base_sol'])} / {_sol(o['priority_sol'])} | |",
             f"| Sender tip | {_sol(o['tip_sol'])} | |",
             f"| out against the quote | {_bps(o['quote_slip_bps'])} | buy slippage {_frac(p.get('slip_buy'))} |",
             f"| cost against Jupiter's prices | {_bps(o['cost_bps'])} | |",
             f"| all in (price, fee, tip) | {_bps(o['total_cost_bps'])} | |", "",
             "## Kraken", "",
             f"Taker fee {k['taker_bps']:.0f} bps. One way with the half spread, the paper book's probes over "
             f"{k['coins']} coins: {_bps(k['oneway_bps'])}; the same probes through Jupiter: "
             f"{_bps(k['paper_onchain_oneway_bps'])}.", "",
             "## Send path", "", c["note"] or "", ""]
    return "\n".join(lines)


def _frac(d: dict | None) -> str:
    if not d or d.get("median") is None:
        return "n/a"
    return f"{d['median'] * 100:+.1f} %"


def _read(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def write(now_ms: int | None = None) -> dict:
    from .. import report as R
    rep = build(LX.read_execution(), _read(R.REPORTS / "pumpfun_rt" / "execution.json"),
                _read(R.REPORTS / "onchain" / "latest.json"), now_ms or int(time.time() * 1000))
    d = R.REPORTS / "onchain"
    d.mkdir(parents=True, exist_ok=True)
    (d / "execution.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    (d / "execution.md").write_text(markdown(rep), encoding="utf-8")
    return rep


def main(argv: list[str] | None = None) -> int:
    rep = write()
    print(rep["verdict"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
