"""Every paper book the lab runs, in one table, from the reports that exist.

  pumpfun_rt/realistic.json   R2's small pump.fun wallets (`small`) and F3's
                              factory books (`factory`), in SOL, less the trades
                              the late-row bug made (P1, `tainted` of each);
                              P3's 10 EUR books (`ten`) with their numbers and
                              gate (`p3`)
  smallaccount/latest.json    S1's and S2's small-account wallets, in EUR
  onchain_longterm/latest.json  L1's on-chain long-term book, in USDC
  etf_books/latest.json       EQ1's UCITS ETF books, in EUR (the Trade
                              Republic wallet, `eq1` the book's report row)
  forward/latest.json         the forward books, their return since the start
                              (a book listed above is not repeated)

A missing or unreadable report is skipped. `python -m lab.ops.paper_books`
writes reports/paper_books/latest.md.
"""

from __future__ import annotations

import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from lab.ops import notify


def _date(v) -> str | None:
    """YYYY-MM-DD from epoch ms or an ISO string."""
    if isinstance(v, (int, float)) and v > 0:
        return datetime.fromtimestamp(v / 1000, timezone.utc).strftime("%Y-%m-%d")
    if isinstance(v, str) and re.match(r"\d{4}-\d{2}-\d{2}", v):
        return v[:10]
    return None


def _num(v) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def books(data_root) -> list[dict]:
    """One dict per paper book: name, study, trades, start, value, currency, report; a pump.fun book also
    `tainted`, the late-row bug's trades (P1) its value leaves out."""
    root = Path(data_root) / "reports"
    out: list[dict] = []

    rel = "pumpfun_rt/realistic.json"
    d = notify.read_json(root / rel)
    if isinstance(d, dict):
        for key, study in (("small", "R2"), ("factory", "F3")):
            for b in d.get(key) or []:
                if isinstance(b, dict) and b.get("book"):
                    out.append({"name": b["book"], "study": study,
                                "trades": f"pump.fun coins, {b.get('strategy') or b['book']}",
                                "start": _date(d.get("realistic_since")),
                                "value": _num(b.get("sol")), "currency": "SOL", "report": rel,
                                "tainted": int(_num(b.get("tainted")) or 0)})
        for b in d.get("ten") or []:
            if isinstance(b, dict) and b.get("book"):
                out.append({"name": b["book"], "study": "P3",
                            "trades": f"pump.fun coins, {b.get('strategy') or b['book']}, 10 EUR",
                            "start": _date(b.get("since_ms")), "value": _num(b.get("sol")), "currency": "SOL",
                            "report": rel, "tainted": int(_num(b.get("tainted")) or 0), "p3": b})

    rel = "smallaccount/latest.json"
    d = notify.read_json(root / rel)
    if isinstance(d, dict) and isinstance(d.get("books"), dict):
        for name, b in d["books"].items():
            if not isinstance(b, dict):
                continue
            # variant: "EXPERIMENT, paper only · S1 small account · 50 EUR paper wallet · <rule> · ..."
            parts = [p.strip() for p in str(b.get("variant") or "").split("·")]
            m = re.search(r"\b(S\d+)\b", str(b.get("variant") or ""))
            out.append({"name": name, "study": m.group(1) if m else "S",
                        "trades": parts[3] if len(parts) > 3 else "",
                        "start": _date(b.get("started")),
                        "value": _num(b.get("equity_eur")), "currency": "EUR", "report": rel})

    rel = "onchain_longterm/latest.json"
    d = notify.read_json(root / rel)
    if isinstance(d, dict):
        out.append({"name": d.get("book") or "onchain_longterm", "study": "L1",
                    "trades": "long-term rebalancing on chain (Jupiter)",
                    "start": _date(d.get("started") or d.get("since")),
                    "value": _num(d.get("equity_usdc")), "currency": "USDC", "report": rel})

    rel = "etf_books/latest.json"
    d = notify.read_json(root / rel)
    if isinstance(d, dict) and isinstance(d.get("books"), dict):
        for name, b in d["books"].items():
            if not isinstance(b, dict):
                continue
            parts = [p.strip() for p in str(b.get("variant") or "").split("·")]
            out.append({"name": name, "study": "EQ1", "trades": parts[3] if len(parts) > 3 else "",
                        "start": _date(b.get("started")), "value": _num(b.get("equity_eur")), "currency": "EUR",
                        "report": rel, "eq1": b})

    rel = "forward/latest.json"
    d = notify.read_json(root / rel)
    if isinstance(d, dict):
        seen = {b["name"]: b for b in out}
        for b in d.get("books") or []:
            if not (isinstance(b, dict) and b.get("name") and b.get("kind", "book") == "book"):
                continue
            if b["name"] in seen:  # listed above with its wallet, only lend it the start
                seen[b["name"]]["start"] = seen[b["name"]]["start"] or _date(b.get("since"))
            else:
                out.append({"name": b["name"], "study": "forward",
                            "trades": b.get("label") or "", "start": _date(b.get("since")),
                            "value": _num(b.get("return_pct")), "currency": "% since start",
                            "report": rel})
    return out


def table(rows: list[dict]) -> str:
    lines = ["| Book | Study | Trades | Start | Wallet or equity | Report |",
             "|---|---|---|---|---|---|"]
    for r in rows:
        v = "n/a" if r["value"] is None else f"{r['value']:,.2f} {r['currency']}"
        cells = [r["name"], r["study"], r["trades"], r["start"] or "n/a", v, r["report"]]
        lines.append("| " + " | ".join(str(c).replace("|", "/") for c in cells) + " |")
    return "\n".join(lines) + "\n"


def main(data_root=None) -> int:
    root = Path(data_root) if data_root is not None else notify.data_root()
    rows = books(root)
    p = root / "reports" / "paper_books" / "latest.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    bad = sum(r.get("tainted") or 0 for r in rows)
    note = (f"\n{bad} pump.fun paper trades the late-row bug made are left out of the wallets above (P1, "
            "results/pumpfun_ledger_taint_p1.md).\n") if bad else ""
    p.write_text(f"# Paper books\n\n{len(rows)} paper books, {now}.\n\n" + table(rows) + note,
                 encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
