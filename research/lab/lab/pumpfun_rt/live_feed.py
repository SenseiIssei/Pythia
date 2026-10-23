"""The live book's price feed for the app: every trade on the coins the bot holds, as it streams.

The live service (live_service.py) hands it each stream row and, once a second, the book.
It keeps, per coin the bot holds now or closed in the last KEEP_MS, the market price after
every curve or pool trade on that coin (SOL per whole token, what tokens.Token.price says,
the unit of the pipeline's entry_price), and writes reports/pumpfun_rt/live_feed.json when
something changed. The engine's endpoint pushes that file to the app over a WebSocket, which
draws the candles. It only reads: nothing here trades, signs or reads a key, and any error in
it is the feed's alone (the service catches it), never the book's.
"""

from __future__ import annotations

import time
from collections import deque

KEEP_MS = 15 * 60_000                 # a closed coin stays on the chart this long
MAX_POINTS = 3_000                    # per coin; a 5 min hold rarely has more trades than this


class LiveFeed:
    def __init__(self, keep_ms: int = KEEP_MS):
        self.keep_ms = keep_ms
        self.coins: dict[str, dict] = {}
        self.dirty = True

    # ------------------------------------------------------------ the stream
    def observe(self, table: str, row: dict, engine) -> None:
        """After the engine took the row: a trade on a watched coin adds a point."""
        if table not in ("trades", "amm"):
            return
        c = self.coins.get(row.get("mint") or "")
        if c is None:
            return
        tok = engine.tokens.get(row["mint"]) if engine is not None else None
        price = tok.price() if tok is not None else 0.0
        if not price or price <= 0:
            return
        sol = row.get("sol") if table == "trades" else row.get("quote")
        c["points"].append((int(row["t"]), price, (sol or 0) / 1e9, 1 if row.get("buy") else 0))
        self.dirty = True

    # ------------------------------------------------------------ the book
    def sync(self, book, now_ms: int) -> None:
        """Watch every coin the book holds; keep a closed one KEEP_MS with its exit."""
        pipe = getattr(book, "pipe", None)
        held = set()
        for p in (pipe.pos.values() if pipe is not None else []):
            mint = p.get("mint")
            if not mint:
                continue
            held.add(mint)
            c = self.coins.get(mint)
            if c is None:
                c = self.coins[mint] = {"mint": mint, "points": deque(maxlen=MAX_POINTS), "exit": None}
                self.dirty = True
            s = getattr(pipe, "strats", {}).get(p.get("rule"))
            ex = getattr(s, "exits", None)
            view = {"pid": p.get("pid"), "rule": p.get("rule"), "symbol": p.get("symbol"), "name": p.get("name"),
                    "venue": p.get("venue"), "state": p.get("state"), "signal_ms": p.get("signal_ms"),
                    "land_ms": p.get("land_ms"), "entry_price": p.get("entry_price"),
                    "signal_price": p.get("signal_price"), "cost_sol": (p.get("cost_l") or 0) / 1e9,
                    "mark_sol": None if p.get("mark_l") is None else p["mark_l"] / 1e9,
                    "tp": ex.ladder[0][0] if ex is not None and ex.ladder else None,
                    "sl": ex.sl if ex is not None else None, "time_s": ex.time_s if ex is not None else None}
            if any(c.get(k) != v for k, v in view.items()):
                c.update(view)
                c["exit"] = None
                self.dirty = True
        for rec in getattr(book, "closed_today", []) or []:
            c = self.coins.get(rec.get("mint") or "")
            if c is not None and c["exit"] is None and rec.get("mint") not in held \
                    and (rec.get("land_ms") is None or rec.get("land_ms") == c.get("land_ms")):
                c["exit"] = {"ms": rec.get("exit_ms"), "price": rec.get("exit_price"), "why": rec.get("exit_why"),
                             "ret": rec.get("ret"), "pnl_sol": rec.get("pnl_sol")}
                c["state"] = "closed"
                self.dirty = True
        for rec in getattr(book, "ran_away", []) or []:
            # a pool buy the price ran away from (before the send, or 6040 on landing): a quiet entry, no exit price
            mint = rec.get("mint") or ""
            if not mint or mint in held or now_ms - int(rec.get("t") or 0) > self.keep_ms:
                continue
            c = self.coins.get(mint)
            if c is None:
                c = self.coins[mint] = {"mint": mint, "points": deque(maxlen=MAX_POINTS), "exit": None, "pid": None,
                                        "rule": rec.get("rule"), "symbol": rec.get("symbol"), "name": rec.get("name"),
                                        "venue": rec.get("venue"), "signal_ms": rec.get("signal_ms"), "land_ms": None,
                                        "entry_price": None, "signal_price": None, "cost_sol": 0.0, "mark_sol": None,
                                        "tp": None, "sl": None, "time_s": None}
            if c["exit"] is None:
                c["exit"] = {"ms": rec.get("t"), "price": None, "why": rec.get("why"), "ret": None,
                             "pnl_sol": -(rec.get("fee_sol") or 0.0)}
                c["state"] = "skipped"
                self.dirty = True
        for mint in [m for m, c in self.coins.items() if m not in held]:
            c = self.coins[mint]
            end = (c["exit"] or {}).get("ms") or (c["points"][-1][0] if c["points"] else c.get("land_ms") or 0)
            if now_ms - end > self.keep_ms:
                del self.coins[mint]
                self.dirty = True

    # ------------------------------------------------------------ the file
    def snapshot(self, status: dict | None = None) -> dict:
        coins = []
        for c in sorted(self.coins.values(), key=lambda c: -(c.get("land_ms") or c.get("signal_ms") or 0)):
            coins.append({k: v for k, v in c.items() if k != "points"} |
                         {"points": [list(x) for x in c["points"]]})
        st = status or {}
        return {"t": int(time.time() * 1000), "coins": coins,
                **{k: st.get(k) for k in ("on", "balance_sol", "balance_t", "pnl_today_sol", "trades_today",
                                          "wins_today", "pnl_total_sol", "trades_total", "exposure_sol")}}
