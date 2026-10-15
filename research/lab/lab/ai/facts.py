"""What Pythia already knows, as short plain text for a model: prices from the
daily closes, funding, the autopilots, and the headlines of the lab's feeds
(forward report, listings, trending, learning loop, factory, models).

Every reader returns something small and never raises: a missing report is
left out, not an error. Our own models' forecasts are deliberately NOT shown,
so the model's calls stay independent of the references they are scored
against.
"""

from __future__ import annotations

import math
from pathlib import Path

from ..ops import notify
from .score import Closes

FEEDS = ("forward", "learn", "listings", "trending", "factory", "models")


def _num(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def coin_of(market_id: str) -> str | None:
    """crypto:BTC/USD -> BTC; anything that is not a coin -> None."""
    if not isinstance(market_id, str) or not market_id.startswith("crypto:"):
        return None
    sym = market_id.split(":", 1)[1]
    base = sym.replace("-", "/").split("/")[0].strip().upper()
    return base or None


def running_autopilots(state: dict | None) -> list[dict]:
    return [a for a in (state or {}).get("autopilots") or [] if a.get("state") == "running"]


def autopilot_coins(state: dict | None) -> list[str]:
    """The coins the running autopilots are assigned, in the order first seen."""
    out: list[str] = []
    for a in running_autopilots(state):
        for s in a.get("bySleeve") or []:
            if s.get("dropped"):
                continue
            for m in s.get("markets") or []:
                c = coin_of(m)
                if c and c not in out:
                    out.append(c)
    return out


def autopilot_lines(state: dict | None) -> list[str]:
    out = []
    for a in running_autopilots(state)[:8]:
        cfg = a.get("config") or {}
        pnl, dd = _num(a.get("pnlPct")), _num(a.get("drawdownPct"))
        sleeves = ", ".join(f"{s.get('name')} {100 * (_num(s.get('weight')) or 0):.0f} %"
                            for s in (a.get("bySleeve") or [])[:4] if not s.get("dropped"))
        fw = a.get("forward") or {}
        parts = [f"{cfg.get('name') or 'autopilot'} ({cfg.get('mode') or '?'}, {cfg.get('venue') or '?'})",
                 f"P&L {pnl:+.2f} %" if pnl is not None else "P&L n/a",
                 f"drawdown {dd:.2f} %" if dd is not None else None,
                 f"{int(_num(a.get('trades')) or 0)} trades",
                 f"sleeves: {sleeves}" if sleeves else None,
                 f"forward vs backtest: {fw.get('status')}" if fw.get("status") else None]
        out.append("; ".join(p for p in parts if p))
    return out


def price_line(coin: str, closes: Closes) -> str | None:
    c = [x[1] for x in closes]
    if len(c) < 31:
        return None
    last = c[-1]

    def ret(k: int) -> str:
        return f"{100 * (last / c[-1 - k] - 1):+.1f} %" if len(c) > k and c[-1 - k] else "n/a"

    rets = [math.log(c[i] / c[i - 1]) for i in range(len(c) - 30, len(c)) if c[i - 1] > 0 and c[i] > 0]
    vol = math.sqrt(sum(r * r for r in rets) / max(len(rets), 1)) * math.sqrt(365) * 100
    ma = sum(c[-200:]) / len(c[-200:]) if len(c) >= 200 else None
    hi = max(c[-365:])
    bits = [f"{coin}: close {last:,.6g} on {closes[-1][0]}", f"1d {ret(1)}", f"7d {ret(7)}", f"30d {ret(30)}",
            f"vol30 {vol:.0f} % a year"]
    if ma:
        bits.append(f"vs 200d mean {100 * (last / ma - 1):+.1f} %")
    bits.append(f"vs 1y high {100 * (last / hi - 1):+.1f} %")
    return ", ".join(bits)


def funding_lines(coins, loader=None) -> list[str]:
    """Latest settled perp funding and its 7-day mean, from the data lake."""
    if loader is None:
        try:
            from ..data import funding as loader
        except Exception:  # noqa: BLE001 - polars missing: no funding facts
            return []
    out = []
    for c in coins:
        try:
            f = loader(c)
            if f is None or f.is_empty():
                continue
            rates = [float(x) for x in f["funding_rate"].to_list()[-21:]]
        except Exception:  # noqa: BLE001 - a coin without perp history is simply left out
            continue
        if rates:
            out.append(f"{c}: last {100 * rates[-1]:+.4f} % per 8h, 7d mean {100 * sum(rates) / len(rates):+.4f} %")
    return out


def feed_lines(names=FEEDS, root: Path | None = None, items: int = 6) -> list[str]:
    """Title, status, headline and the first items of each lab feed."""
    rep = root or notify.reports_root()
    out = []
    for n in names:
        v = notify.read_json(rep / n / "latest.json")
        if not isinstance(v, dict):
            continue
        head = notify.short(notify.nodash(str(v.get("headline") or "")), 240)
        line = f"[{v.get('title') or n}] status {v.get('status') or '?'}: {head}"
        rows = []
        for it in (v.get("items") or [])[:items]:
            if isinstance(it, dict) and it.get("label"):
                val = f" {it.get('value')}" if it.get("value") not in (None, "") else ""
                st = f" ({it.get('status')})" if it.get("status") else ""
                rows.append(notify.short(notify.nodash(f"{it['label']}{val}{st}"), 120))
            elif isinstance(it, str):
                rows.append(notify.short(notify.nodash(it), 120))
        if rows:
            line += " | " + "; ".join(rows)
        out.append(line)
    return out
