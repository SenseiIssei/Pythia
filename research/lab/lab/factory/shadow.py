"""Forward shadow books: the holdout's survivors run forward for 30 days before any promotion.

A shadow book is the genome re-simulated every day on the freshest panel,
with the backtest's own fills (the decision close plus 35 bps per unit of
turnover). Only the days after it entered the shadow stage count, and each
recorded day is frozen: a later run appends, it never rewrites. That makes it
a forward test of the rule itself, kept apart from the paper books (which use
live quotes) until it earns a place among them.

Files under <data>/factory/shadow/: <key>.json (genome, entry, backtest
evidence, status) and <key>.csv (date, net return, gross, turnover, exposure).

After SHADOW_DAYS recorded days a shadow is reviewed once:
  promoted  the promotion bar holds (evaluate.bar_gates against today's pool)
            and the forward return is not below the backtest's 5 % quantile
            for that many days. It becomes a paper book in promoted.json, which
            lab.paper.families steps with live quotes like the other books.
            Never live: the factory has no way to reach live settings.
  retired   anything else, with the reason. A retired genome never re-enters.
"""

from __future__ import annotations

import csv
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from . import build, evaluate
from .ledger import factory_dir, read_jsonl, write_json

SHADOW_DAYS = 30
MAX_ACTIVE = 6
MAX_NEW_PER_RUN = 2
DUPLICATE_CORR = 0.90


def shadow_dir() -> Path:
    return factory_dir() / "shadow"


def promoted_path() -> Path:
    return factory_dir() / "promoted.json"


def _read_json(p: Path) -> dict | None:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def all_shadows() -> list[dict]:
    d = shadow_dir()
    if not d.exists():
        return []
    return [m for m in (_read_json(p) for p in sorted(d.glob("*.json"))) if m]


def active() -> list[dict]:
    return [m for m in all_shadows() if m.get("status") == "active"]


def journal(key: str) -> list[dict]:
    p = shadow_dir() / f"{key}.csv"
    if not p.exists():
        return []
    with p.open(newline="") as fh:
        return list(csv.DictReader(fh))


def promoted() -> dict:
    return _read_json(promoted_path()) or {"books": {}}


def book_name(key: str) -> str:
    return f"factory_{key[:8]}"


def start(is_row: dict, h: dict, gates: dict, oos_net: np.ndarray, run_id: str, entry_day: str) -> dict:
    """Open a shadow book. Its first counted day is the one after entry_day."""
    meta = {
        "key": is_row["key"], "name": is_row["name"], "genome": is_row["genome"], "status": "active",
        "entered_run": run_id, "entry_day": entry_day, "book": book_name(is_row["key"]),
        "in_sample": {k: is_row[k] for k in ("is_sharpe", "is_h1", "is_h2", "is_turnover_yr", "is_exposure",
                                             "complexity", "fitness")},
        "holdout": h, "gates": gates,
        "oos_net_35bps": [round(float(v), 7) for v in oos_net],
    }
    write_json(shadow_dir() / f"{is_row['key']}.json", meta)
    return meta


def _day(us: int) -> str:
    return datetime.fromtimestamp(us / 1e6, timezone.utc).strftime("%Y-%m-%d")


def update(c: build.Ctx) -> list[dict]:
    """Append every new finished day to each active shadow's journal. Returns what was appended."""
    out = []
    for m in active():
        g = m["genome"]
        gross, tov, expo = build.run(c, g)
        n35 = build.net(gross, tov, build.COSTS["35bps"])
        rows = journal(m["key"])
        last = rows[-1]["date"] if rows else m["entry_day"]
        eq = float(rows[-1]["equity"]) if rows else 1.0
        new = []
        for t in range(c.T):
            d = _day(int(c.days[t]))
            if d <= last:
                continue
            eq *= 1 + float(n35[t])
            new.append({"date": d, "net_ret": f"{n35[t]:.7f}", "gross_ret": f"{gross[t]:.7f}",
                        "turnover": f"{tov[t - 1] if t else 0.0:.5f}", "exposure": f"{expo[t - 1] if t else 0.0:.4f}",
                        "equity": f"{eq:.6f}"})
        if new:
            p = shadow_dir() / f"{m['key']}.csv"
            fresh = not p.exists()
            with p.open("a", newline="") as fh:
                wr = csv.DictWriter(fh, fieldnames=list(new[0]))
                if fresh:
                    wr.writeheader()
                wr.writerows(new)
        out.append({"key": m["key"], "name": m["name"], "appended": len(new), "days": len(rows) + len(new)})
    return out


def forward_stats(m: dict) -> dict:
    rows = journal(m["key"])
    r = np.array([float(x["net_ret"]) for x in rows]) if rows else np.zeros(0)
    days = len(r)
    ret = float(np.prod(1 + r) - 1) if days else 0.0
    band = evaluate.boot_quantiles(np.array(m.get("oos_net_35bps") or []), days) if days else [math.nan] * 3
    return {"days": days, "return": ret, "band": band,
            "below_band": bool(days and math.isfinite(band[0]) and ret < band[0])}


def review(c: build.Ctx, pool: dict, btc: dict, today: str) -> list[dict]:
    """Decide every active shadow with SHADOW_DAYS recorded days: promote or retire."""
    decisions = []
    for m in active():
        fw = forward_stats(m)
        if fw["days"] < SHADOW_DAYS:
            continue
        h = evaluate.holdout(c, m["genome"], pool, btc)
        is_row = evaluate.in_sample(c, m["genome"], m["entered_run"])
        gates = evaluate.bar_gates(is_row, h)
        gates["forward"] = {"passed": not fw["below_band"],
                            "why": f"{fw['days']} shadow days {fw['return'] * 100:+.1f} % vs backtest 5 % quantile "
                                   f"{fw['band'][0] * 100:+.1f} %"}
        bad = evaluate.failed(gates)
        m.update(reviewed=today, review_gates=gates, review_holdout=h, forward=fw)
        if bad:
            m["status"] = "retired"
            m["reason"] = "; ".join(gates[k]["why"] for k in bad)
        else:
            m["status"] = "promoted"
            m["reason"] = "passes the bar and its forward month"
            pr = promoted()
            pr["books"][m["book"]] = {"key": m["key"], "name": m["name"], "genome": m["genome"], "promoted": today,
                                      "evidence": {"deflated_p": h["deflated_p"], "pool_trials": h["pool_trials"],
                                                   "oos_sharpe_35bps": h["oos_sharpe_35bps"],
                                                   "oos_sharpe_70bps": h["oos_sharpe_70bps"],
                                                   "oos_max_dd": h["oos_max_dd"], "forward": fw}}
            write_json(promoted_path(), pr)
        write_json(shadow_dir() / f"{m['key']}.json", m)
        decisions.append({"key": m["key"], "name": m["name"], "status": m["status"], "reason": m["reason"],
                          "failed": bad, "forward": fw})
    return decisions


def oos_series(m: dict) -> np.ndarray:
    return np.array(m.get("oos_net_35bps") or [], dtype=float)


def too_close(x: np.ndarray, others: list[tuple[str, np.ndarray]]) -> str | None:
    """The name of a book whose held-back returns move with x (correlation above DUPLICATE_CORR)."""
    for name, y in others:
        n = min(len(x), len(y))
        if n < 60:
            continue
        a, b = x[-n:], y[-n:]
        if a.std() > 0 and b.std() > 0 and float(np.corrcoef(a, b)[0, 1]) > DUPLICATE_CORR:
            return name
    return None


def ever_shadowed() -> set[str]:
    return {m["key"] for m in all_shadows()}


def holdout_log() -> list[dict]:
    return read_jsonl(factory_dir() / "holdout.jsonl")
