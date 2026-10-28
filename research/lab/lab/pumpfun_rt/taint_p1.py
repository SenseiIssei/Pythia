"""P1 (results/pumpfun_ledger_taint_p1_prereg.md): the realistic pump.fun ledger with and without the trades the
late-row bug made. PAPER ONLY, reads the ledger, rewrites nothing.

    python -m lab.pumpfun_rt.taint_p1 [--ledger PATH] [--out results/pumpfun_ledger_taint_p1.md]

Per book (the ledger's `rule`) and per rule (chosen: realistic.tainted; stricter: that or closed before the deploy
with slip < STRICT_SLIP), the trades, mean and median return per trade with and without the tainted rows, before
and after d84b252's deploy (realistic.FIX_MS, by exit_ms). Two trials in R5's registry, counted only, registered
before the first number.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

from .. import metrics
from . import realistic as R

PREREG = "results/pumpfun_ledger_taint_p1_prereg.md"
STRICT_SLIP = -0.5                         # the stricter rule: a fill under half the signal price before the deploy
OUT = Path(__file__).resolve().parents[2] / "results" / "pumpfun_ledger_taint_p1.md"


def trials() -> list[dict]:
    return [{"id": f"hand:p1:{k}", "family": "hand", "n": 1, "sharpe": None, "source": PREREG}
            for k in ("ledger_taint", "ledger_taint_strict")]


def strict(r: dict) -> bool:
    ex, slip = R._f(r.get("exit_ms")), R._f(r.get("slip"))
    return R.tainted(r) or (ex is not None and ex < R.FIX_MS and slip is not None and slip < STRICT_SLIP)


def conditions(rows: list[dict]) -> dict[str, int]:
    """How many rows each condition of the chosen rule flags (a row can meet several), the stricter rule's extra,
    the tainted rows' commonest exit reasons and the books with the most tainted rows."""
    c = {"hold": 0, "exit_before_land": 0, "land_before_signal": 0, "any": 0, "strict_extra": 0}
    why: dict[str, int] = {}
    book: dict[str, list[int]] = {}
    for r in rows:
        b = book.setdefault(r.get("rule") or "?", [0, 0])
        b[1] += 1
        sig, land, xsig, ex, hold = (R._f(r.get(k)) for k in ("signal_ms", "land_ms", "exit_signal_ms", "exit_ms",
                                                               "hold_s"))
        c["hold"] += bool(ex is not None and ex < R.FIX_MS and hold is not None and hold < 0)
        c["exit_before_land"] += bool(xsig is not None and land is not None and xsig < land)
        c["land_before_signal"] += bool(land is not None and sig is not None and land < sig)
        t = R.tainted(r)
        c["any"] += t
        c["strict_extra"] += bool(strict(r) and not t)
        if t:
            b[0] += 1
            why[r.get("exit_why") or "none"] = why.get(r.get("exit_why") or "none", 0) + 1
    c["why"] = sorted(why.items(), key=lambda kv: -kv[1])[:8]
    c["books"] = [(k, n, t) for k, (n, t) in sorted(book.items(), key=lambda kv: -kv[1][0])[:6]]
    return c


def stats(xs: list[float]) -> tuple[int, float | None, float | None]:
    return len(xs), (float(np.mean(xs)) if xs else None), (float(np.median(xs)) if xs else None)


def table(rows: list[dict]) -> list[dict]:
    """Per book and period (before, after the deploy, all): (n, mean, median) of every trade, of the chosen rule's
    kept ones and of the stricter rule's."""
    by: dict[tuple[str, str], list[tuple[float, bool, bool]]] = {}
    for r in rows:
        ret, ex = R._f(r.get("ret")), R._f(r.get("exit_ms"))
        if ret is None or ex is None or not r.get("rule"):
            continue
        x = (ret, R.tainted(r), strict(r))
        for k in (r["rule"], "all books"):
            by.setdefault((k, "before" if ex < R.FIX_MS else "after"), []).append(x)
            by.setdefault((k, "all"), []).append(x)
    out = []
    for (book, per), xs in sorted(by.items(), key=lambda kv: (kv[0][0] == "all books", kv[0][0],
                                                              ("before", "after", "all").index(kv[0][1]))):
        out.append({"book": book, "period": per, "all": stats([v for v, _, _ in xs]),
                    "chosen": stats([v for v, t, _ in xs if not t]), "strict": stats([v for v, _, s in xs if not s]),
                    "tainted": sum(t for _, t, _ in xs), "strict_n": sum(s for _, _, s in xs)})
    return out


def _pc(x) -> str:
    return "n/a" if x is None else f"{x * 100:+.1f} %"


def markdown(tab: list[dict], cond: dict, n_rows: int) -> str:
    md = ["# P1: the realistic pump.fun ledger without the trades the late-row bug made", "",
          f"Pre-registration `{PREREG}`. Ledger `<data>/paper/pumpfun_rt/ledger.csv` ({n_rows:,} rows), read only. "
          f"Deploy of d84b252: {R.FIX_DAY}; before and after by exit_ms. Returns per trade (`ret`, the book's own "
          "stake). Two trials in R5's registry, counted only (`hand:p1:ledger_taint`, `hand:p1:ledger_taint_strict`); no Sharpe, no DSR, "
          "no pass or fail.", "",
          "## The rule", "",
          "Chosen (`realistic.tainted`, what every reader skips): closed before the deploy with hold_s < 0, or "
          "exit_signal_ms < land_ms, or land_ms < signal_ms. Stricter (reported only): that, or closed before the "
          f"deploy with slip < {STRICT_SLIP:g} (a fill under half the signal price; a real dump between signal and "
          "landing gives the same row, so the ledger alone cannot tell these apart).", "",
          "| condition | rows |", "|---|---|",
          f"| closed before the deploy, hold_s < 0 | {cond['hold']} |",
          f"| exit_signal_ms < land_ms | {cond['exit_before_land']} |",
          f"| land_ms < signal_ms | {cond['land_before_signal']} |",
          f"| chosen rule (any of the above) | {cond['any']} |",
          f"| stricter rule, rows beyond the chosen | {cond['strict_extra']} |", "",
          "Tainted rows by exit reason: " + ", ".join(f"{k} {v:,}" for k, v in cond["why"]) + ".", "",
          "Most tainted books (tainted of all rows): " + ", ".join(
              f"{b} {n:,} of {t:,}" for b, n, t in cond["books"]) + ". The snipe and press books' exits on the "
          "dev's sale or a pulled pool are decided at the signal itself, before the buy lands; the rule fixed in the "
          "pre-registration counts them as tainted too, so these books lose far more rows than the pool books.", "",
          "## Per book", "",
          "Books with a tainted row under either rule; the totals over every book last.", "",
          "| book | period | trades | mean | median | tainted | kept | mean kept | median kept | strict dropped | "
          "mean strict | median strict |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    hit = {r["book"] for r in tab if r["strict_n"]}
    for r in tab:
        if r["book"] not in hit and r["book"] != "all books":
            continue
        (n, m, me), (nk, mk, mek), (_, ms, mes) = r["all"], r["chosen"], r["strict"]
        md.append(f"| {r['book']} | {r['period']} | {n} | {_pc(m)} | {_pc(me)} | {r['tainted']} | {nk} | {_pc(mk)} | "
                  f"{_pc(mek)} | {r['strict_n']} | {_pc(ms)} | {_pc(mes)} |")
    md += ["", f"{len({r['book'] for r in tab}) - 1} books in the ledger, {len(hit - {'all books'})} with a row the "
           "stricter rule drops."]
    return "\n".join(md) + "\n"


def run(ledger: Path, out: Path, register: bool = True, log=print) -> dict:
    if register:
        metrics.register(trials())                            # before any number exists
    rows = R.read_csv(ledger)
    tab, cond = table(rows), conditions(rows)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(markdown(tab, cond, len(rows)), encoding="utf-8")
    log(f"p1: {cond['any']} tainted rows of {len(rows):,}, the stricter rule {cond['strict_extra']} more -> {out}")
    return {"conditions": cond, "table": tab}


def main(argv: list[str] | None = None) -> int:
    from .live import paper_dir
    ap = argparse.ArgumentParser(prog="lab.pumpfun_rt.taint_p1", description=__doc__.split("\n")[0])
    ap.add_argument("--ledger", default=None)
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args(sys.argv[1:] if argv is None else argv)
    run(Path(a.ledger) if a.ledger else paper_dir() / "ledger.csv", Path(a.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
