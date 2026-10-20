"""What Pythia already knows, as short plain text for a model: prices from the
daily closes, funding, the autopilots, and the headlines of the lab's feeds
(forward report, listings, trending, learning loop, factory, models).

fact_sheet() is the richer sheet the daily brief and the Telegram answers
read: every autopilot with its rules and record, the forward report and real
money readiness, flow signals (DVOL, skew, stablecoins, regional premiums),
listings, trending, the pump.fun real-time lab and the CS2 and Pokemon movers.

Every reader returns something small and never raises: a missing report is
left out, not an error. Our own models' forecasts are deliberately NOT shown,
so the model's calls stay independent of the references they are scored
against.
"""

from __future__ import annotations

import math
import os
from datetime import datetime, timezone
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


# ---------------------------------------------------------------- the richer fact sheet

# The lab feeds the daily brief and the Telegram answers read, in this order:
# forward evidence and real money readiness first, then models and studies,
# then the watchers (listings, trending, pump.fun) and the collectibles.
SHEET_FEEDS = ("forward", "readiness", "learn", "models", "factory", "flow_overlays", "listings", "trending",
               "pumpfun_rt", "memecoins", "cs2", "pokemon", "polymarket")
# Feeds whose items are movers worth more than six lines.
MOVER_FEEDS = ("cs2", "pokemon", "trending", "listings")
RECENT_STOP_MS = 7 * 86_400_000


def _pct(v, dp: int = 2, sign: bool = True) -> str | None:
    f = _num(v)
    return None if f is None else f"{f:{'+' if sign else ''}.{dp}f} %"


def _usd(v) -> str | None:
    f = _num(v)
    return None if f is None else f"${f:,.2f}"


def listed_autopilots(state: dict | None, now_ms: int | None = None) -> list[dict]:
    """Running and paused autopilots, and the ones that stopped or finished in
    the last 7 days (their record still matters for a question about them)."""
    out = []
    for a in (state or {}).get("autopilots") or []:
        st = a.get("state")
        if st in ("running", "paused"):
            out.append(a)
        elif st in ("stopped", "finished") and now_ms is not None:
            stopped = _num(a.get("stoppedMs"))
            if stopped is not None and now_ms - stopped <= RECENT_STOP_MS:
                out.append(a)
    return out


def stop_rules_text(cfg: dict) -> str:
    s = cfg.get("stop") or {}
    bits = []
    if _num(s.get("maxLossPct")) is not None:
        bits.append(f"max loss {_num(s['maxLossPct']):g} %")
    if _num(s.get("maxLossUsd")) is not None:
        bits.append(f"max loss ${_num(s['maxLossUsd']):,.0f}")
    if _num(s.get("trailingPct")) is not None:
        bits.append(f"trailing {_num(s['trailingPct']):g} % from peak")
    if _num(s.get("takeProfitPct")) is not None:
        bits.append(f"take profit {_num(s['takeProfitPct']):g} % ({s.get('onTakeProfit') or 'default'})")
    if cfg.get("flattenOnStop") is False:
        bits.append("keeps positions on stop")
    return ", ".join(bits) or "no stop rules"


def autopilot_detail(a: dict) -> str:
    """One autopilot in full: its rules, its book and its record so far."""
    cfg = a.get("config") or {}
    name = cfg.get("name") or cfg.get("id") or "autopilot"
    head = f"{name} ({cfg.get('mode') or '?'}, {cfg.get('venue') or '?'}"
    head += f", account {a['account']}" if a.get("account") else ""
    head += f", {a.get('state')})"
    start = _num(a.get("startCapital")) or _num(cfg.get("capitalUsd"))
    fees = _num(a.get("fees"))
    bench = a.get("benchmark") or {}
    fw = a.get("forward") or {}
    sleeves = "; ".join(
        f"{s.get('name')} {100 * (_num(s.get('weight')) or 0):.0f} % (P&L {_usd(s.get('pnl')) or 'n/a'}, "
        f"{int(_num(s.get('trades')) or 0)} trades{', dropped' if s.get('dropped') else ''}"
        f"{', experiment' if s.get('experimental') else ''})"
        for s in (a.get("bySleeve") or [])[:6])
    held = ", ".join(str(h) for h in (a.get("held") or [])[:10])
    parts = [
        head,
        f"capital {_usd(start)}" if start else None,
        f"equity {_usd(a.get('equity'))}" if _num(a.get("equity")) is not None else None,
        f"P&L {_pct(a.get('pnlPct'))}" if _num(a.get("pnlPct")) is not None else None,
        f"below peak {_pct(a.get('drawdownPct'), sign=False)}" if _num(a.get("drawdownPct")) is not None else None,
        f"worst drawdown {_pct(a.get('maxDrawdownPct'), sign=False)}" if _num(a.get("maxDrawdownPct")) else None,
        f"stops at equity {_usd(a.get('floorEquity'))}" if _num(a.get("floorEquity")) is not None else None,
        f"next target {_usd(a.get('targetEquity'))}" if _num(a.get("targetEquity")) is not None else None,
        f"{int(_num(a.get('trades')) or 0)} closed trades, {int(_num(a.get('orders')) or 0)} orders",
        (f"fees {_usd(fees)}" + (f" ({100 * fees / start:.2f} % of capital)" if start and fees else "")) if fees is not None else None,
        f"{int(_num(a.get('openPositions')) or 0)} open positions" + (f": {held}" if held else ""),
        f"cash {_usd(a.get('cash'))}" if _num(a.get("cash")) is not None else None,
        f"rules: {stop_rules_text(cfg)}",
        f"sleeves: {sleeves}" if sleeves else None,
        (f"vs {bench.get('name') or bench.get('symbol')}: {_pct(bench.get('excessPct'))} points"
         if _num(bench.get("excessPct")) is not None else None),
        f"forward vs backtest: {fw.get('status')}" if fw.get("status") else None,
        f"waiting: {a.get('waiting')}" if a.get("waiting") else None,
        f"paused: {a.get('pausedReason')}" if a.get("pausedReason") else None,
        f"stopped: {a.get('stopReason')}" if a.get("stopReason") else None,
        f"last action: {a.get('lastAction')}" if a.get("lastAction") else None,
    ]
    return notify.nodash("; ".join(p for p in parts if p))


def autopilot_details(state: dict | None, now_ms: int | None = None, limit: int = 12) -> list[str]:
    return [autopilot_detail(a) for a in listed_autopilots(state, now_ms)[:limit]]


def flow_root() -> Path:
    return Path(os.environ.get("PYTHIA_FLOW", str(notify.data_root() / "flow")))


def flow_lines(root: Path | None = None, closes: dict[str, Closes] | None = None) -> list[str]:
    """Flow and positioning from the flow lake (lab.collect.flow): Deribit DVOL
    and 25-delta skew, stablecoin supply, and the Coinbase and Upbit premiums
    against the Binance daily close. Each source on its own; one that is
    missing or unreadable is left out. Never raises."""
    try:
        import polars as pl
    except Exception:  # noqa: BLE001 - no polars: no flow facts
        return []
    base = root or flow_root()
    out: list[str] = []

    def read(name: str):
        p = base / name
        return pl.read_parquet(p) if p.exists() else None

    try:
        dv = read("dvol.parquet")
        if dv is not None and not dv.is_empty():
            for cur in ("BTC", "ETH"):
                c = dv.filter(pl.col("currency") == cur).sort("day_us")["close"].to_list()
                if len(c) >= 2:
                    wk = f", 7d ago {c[-8]:.1f}" if len(c) >= 8 else ""
                    mo = f", 30d ago {c[-31]:.1f}" if len(c) >= 31 else ""
                    out.append(f"{cur} DVOL (implied vol index) {c[-1]:.1f}{wk}{mo}")
    except Exception:  # noqa: BLE001
        pass
    try:
        sk = read("skew.parquet")
        if sk is not None and not sk.is_empty():
            for cur in ("BTC", "ETH"):
                s = sk.filter(pl.col("currency") == cur)
                if s.is_empty():
                    continue
                last = s.filter(pl.col("ts_us") == s["ts_us"].max())
                row = last.with_columns((pl.col("days") - 30).abs().alias("_d")).sort("_d").row(0, named=True)
                out.append(f"{cur} options {row['days']:.0f}d: 25-delta risk reversal {100 * row['rr25']:+.1f} vol pts, "
                           f"ATM IV {100 * row['atm_iv']:.1f} %")
    except Exception:  # noqa: BLE001
        pass
    try:
        st = read("stables.parquet")
        if st is not None and st.height >= 8:
            t = st.sort("day_us")["total"].to_list()
            line = f"stablecoin supply ${t[-1] / 1e9:,.1f} bn, 7d {100 * (t[-1] / t[-8] - 1):+.2f} %"
            if len(t) >= 31:
                line += f", 30d {100 * (t[-1] / t[-31] - 1):+.2f} %"
            out.append(line)
    except Exception:  # noqa: BLE001
        pass
    btc = {d: c for d, c in (closes or {}).get("BTC") or []}
    try:
        cb = read("coinbase_btcusd_1h.parquet")
        if cb is not None and btc and not cb.is_empty():
            cb = cb.with_columns(pl.from_epoch("ts_us", time_unit="us").alias("t")).sort("ts_us")
            # The candle opening 23:00 UTC closes with the Binance daily close.
            last = cb.filter(pl.col("t").dt.hour() == 23).tail(8)
            prem = []
            for r in last.iter_rows(named=True):
                d = r["t"].strftime("%Y-%m-%d")
                if d in btc and btc[d]:
                    prem.append((d, 1e4 * (r["close"] / btc[d] - 1)))
            if prem:
                mean7 = sum(p for _, p in prem[-7:]) / len(prem[-7:])
                out.append(f"Coinbase premium over Binance at the daily close: {prem[-1][1]:+.1f} bps on {prem[-1][0]}, "
                           f"mean of the last {len(prem[-7:])} days {mean7:+.1f} bps")
    except Exception:  # noqa: BLE001
        pass
    try:
        up, fx = read("upbit_krwbtc_1d.parquet"), read("fx_usdkrw.parquet")
        if up is not None and fx is not None and btc and not up.is_empty() and not fx.is_empty():
            up = up.sort("day_us").tail(8)
            fx = fx.sort("day_us")
            fx_days, fx_v = fx["day_us"].to_list(), fx["usdkrw"].to_list()
            prem = []
            for r in up.iter_rows(named=True):
                k = max((i for i, x in enumerate(fx_days) if x <= r["day_us"]), default=None)
                d = datetime.fromtimestamp(r["day_us"] / 1e6, timezone.utc).strftime("%Y-%m-%d")
                if k is not None and d in btc and btc[d]:
                    prem.append((d, 100 * (r["close"] / fx_v[k] / btc[d] - 1)))
            if prem:
                out.append(f"Upbit (Korea) premium over Binance: {prem[-1][1]:+.2f} % on {prem[-1][0]}, "
                           f"7 days ago {prem[0][1]:+.2f} %")
    except Exception:  # noqa: BLE001
        pass
    return out


def pumpfun_lines(root: Path | None = None, now_ms: int | None = None) -> list[str]:
    """The real-time pump.fun lab (lab.pumpfun_rt), from its own files: is the
    collector alive, and how the live shadow book's rules have done on paper."""
    data = root or notify.data_root()
    out: list[str] = []
    hb = notify.read_json(data / "pumpfun_rt" / "heartbeat.json")
    if isinstance(hb, dict):
        age = (now_ms - int(_num(hb.get("t")) or 0)) / 60_000 if now_ms else None
        conn = hb.get("connected") or {}
        up = sum(1 for v in conn.values() if v) if isinstance(conn, dict) else 0
        out.append(f"collector heartbeat {'%.0f min ago' % age if age is not None else 'seen'}, "
                   f"{up} of {len(conn) if isinstance(conn, dict) else 0} streams connected, "
                   f"{int(_num(hb.get('reconnects')) or 0)} reconnects, {int(_num(hb.get('pools')) or 0)} pools")
    st = notify.read_json(data / "paper" / "pumpfun_rt" / "state.json")
    if isinstance(st, dict):
        totals = st.get("totals") or {}
        rows = []
        for rule, t in sorted(totals.items(), key=lambda kv: -(_num((kv[1] or {}).get("n")) or 0))[:6]:
            n = int(_num(t.get("n")) or 0)
            if not n:
                continue
            rows.append(f"{rule}: {n} paper trades, {100 * (_num(t.get('wins')) or 0) / n:.0f} % winners, "
                        f"mean {100 * (_num(t.get('ret_sum')) or 0) / n:+.1f} %, {(_num(t.get('pnl_sol')) or 0):+.3f} SOL")
        out.append(f"shadow book pick {st.get('pick') or '?'}, {len(st.get('open') or [])} open"
                   + (" | " + "; ".join(rows) if rows else ", no closed paper trade yet"))
    return [notify.nodash(x) for x in out]


def sheet_feed_lines(root: Path | None = None) -> list[str]:
    """The lab feeds of the fact sheet, the movers' feeds with more items."""
    out = feed_lines([n for n in SHEET_FEEDS if n not in MOVER_FEEDS], root=root, items=6)
    out += feed_lines([n for n in SHEET_FEEDS if n in MOVER_FEEDS], root=root, items=10)
    return out


def fact_sheet(day: str, coins: list[str], closes: dict[str, Closes], state: dict | None, funding: list[str],
               feeds: list[str] | None = None, flow: list[str] | None = None, pumpfun: list[str] | None = None,
               now_ms: int | None = None, extra: list[tuple[str, list[str]]] | None = None) -> str:
    """Everything Pythia knows today as plain text sections. The parts not
    given are read from the lab's files; a section with nothing in it is
    left out."""
    lines = [f"DATE: {day} (UTC).", "", "PRICES (daily closes):"]
    for c in coins:
        line = price_line(c, closes.get(c) or [])
        if line:
            lines.append("- " + line)
    sections: list[tuple[str, list[str]]] = [
        ("FUNDING (perpetuals, settled)", funding),
        ("FLOW AND POSITIONING (options, stablecoins, regional premiums)",
         flow if flow is not None else flow_lines(closes=closes)),
        ("AUTOPILOTS (running, paused, and stopped in the last 7 days; paper or demo money)",
         autopilot_details(state, now_ms) or ["none"]),
        ("LAB REPORTS (headline and first items of each feed)", feeds if feeds is not None else sheet_feed_lines()),
        ("PUMP.FUN REAL TIME (paper only)", pumpfun if pumpfun is not None else pumpfun_lines(now_ms=now_ms)),
    ] + list(extra or [])
    for title, rows in sections:
        if rows:
            lines += ["", f"{title}:"] + ["- " + r for r in rows]
    return "\n".join(lines)
