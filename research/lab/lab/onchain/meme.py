"""EXPERIMENT, paper only: memecoins through Jupiter for our own wallet, three pre-registered rules, a paper book each.

docs/ONCHAIN-MEME.md; the rules and the proof are pre-registered in
research/lab/results/onchain_meme_prereg.md (3 trials, counted in the global pool). The pump.fun bot
(lab.pumpfun_rt) is untouched: this module never calls pump.fun's programs, it quotes coins on
Raydium (LaunchLab included), Meteora (its dynamic bonding curve included), Orca and PumpSwap through
Jupiter.

Candidates, every run:
  trends       our own Trends file (reports/pumpfun_rt/trends.json, at most TRENDS_MAX_AGE_MS old):
               its fresh pools and hot migrated coins, with the Y9 model badges and their ranks (the place in the
               hot list, ranked by buy SOL over 5 minutes among all pump.fun coins, and in the fresh list)
  dexscreener  DexScreener's token boosts and latest profiles on Solana (what lab.ops.trending reads)
  jupiter      Jupiter's public trending lists (tokens/v2/toptrending/1h, toporganicscore/1h)
Each candidate gets its pools from DexScreener (meme_safety.best_pool). A rule that wants a coin asks
the safety check (meme_safety; a cached verdict up to PAPER_MAX_AGE_MS old) before anything is quoted.

The rules (RULES; entries, then exits checked every run on a real Jupiter sell quote):
  fresh_win       a fresh pool from the Trends file 5 to 30 min after its migration, the Y9 model's
                  win_high badge, no rug_risk badge; +50 % take profit, -25 % stop, a 20 % trailing stop
                  once +20 %, 2 h time stop, out when its best pool lost half its liquidity
  momentum_trail  a pool at least a day old with at least 50,000 USD, up 5 % over the hour and 20 % over
                  the day (DexScreener); -15 % stop, 15 % trailing stop, 24 h time stop, out when the pool
                  lost 40 % of its liquidity
  organic_trend   Jupiter's organic-score list: score at least 80, up over the hour and the day, the pool a
                  day old; +30 % take profit, -10 % stop, 10 % trailing stop once +5 %, 12 h time stop,
                  out at a 40 % liquidity drop
  trend_top       (Y10, results/pumpfun_trends_y10_prereg.md) a migrated coin ranked in the Trends file's hot top
                  5 or fresh top 3, its migration 5 minutes ago or more, no win_low badge; +30 % take profit, -20 %
                  stop, a 20 % trailing stop once +20 %, 1 h time stop, out when its best pool lost half its
                  liquidity
Every rule skips a coin the Trends file badges rug_risk, a coin it entered in the last 24 h, and holds at
most MAX_OPEN coins. A position without a sell quote for NO_QUOTE_MS is closed at zero.

The paper fill is stage 1's (paper.py): Jupiter's quoted out amount, less Solana's base fee and our
priority fee, 0.1 SOL (STAKE_L) a buy, out of a 1 SOL account per rule (journal equity on the 10,000
basis every lab book starts from, so the forward report, the Lab page and the briefing show the books).

  python -m lab.onchain.meme              one run (the job onchain-meme, every 2 minutes)
  python -m lab.onchain.meme --proof      the pre-registered proof (the job onchain-meme-proof, daily):
                                          reports/onchain_meme/proof.json and latest.md
  python -m lab.onchain.meme --dry-run    candidates, verdicts and what each rule would do; writes nothing

<data>/paper/onchain_meme_<rule>/  state.json (cash, open positions), journal.csv (a row per UTC day,
                                   rewritten each run), trades.csv (every fill with its quote)
Nothing here signs, sends or holds a key; the live path is lab.onchain.meme_live, locked.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from .. import report
from . import meme_safety as MS
from . import paper as P
from .jupiter import Jupiter, QuoteError

WSOL = "So11111111111111111111111111111111111111112"
PREFIX = "onchain_meme_"
REPORT = "onchain_meme"
STAKE_L = 100_000_000                    # 0.1 SOL a buy
START_SOL = 1.0
INDEX = 10_000.0
MAX_OPEN = 5
COOLDOWN_MS = 86_400_000
NO_QUOTE_MS = 30 * 60_000
TRENDS_MAX_AGE_MS = 120_000
MAX_CHECKS = 10                          # safety checks a run (each a few RPC reads)
QUOTE_SLIPPAGE_BPS = 200
H = 3_600_000
RULES: dict[str, dict] = {
    "fresh_win": {"label": "fresh pool 5 to 30 min after migration, Y9 win_high, no rug_risk",
                  "tp": 0.50, "stop": -0.25, "trail": 0.20, "arm": 0.20, "time_ms": 2 * H, "liq_drop": 0.50},
    "momentum_trail": {"label": "pool a day old, 50k USD, up 5 % in 1 h and 20 % in 24 h, trailing exit",
                       "tp": None, "stop": -0.15, "trail": 0.15, "arm": 0.0, "time_ms": 24 * H, "liq_drop": 0.40},
    "organic_trend": {"label": "Jupiter organic score 80+, up over 1 h and 24 h, pool a day old",
                      "tp": 0.30, "stop": -0.10, "trail": 0.10, "arm": 0.05, "time_ms": 12 * H, "liq_drop": 0.40},
    "trend_top": {"label": "migrated coin in the Trends hot top 5 or fresh top 3, 5 min or more after its migration",
                  "tp": 0.30, "stop": -0.20, "trail": 0.20, "arm": 0.20, "time_ms": H, "liq_drop": 0.50},
}
TRIALS = len(RULES)
FRESH_MIN_MS, FRESH_MAX_MS = 5 * 60_000, 30 * 60_000
MOMENTUM_MIN_LIQ = 50_000.0
MOMENTUM_H1, MOMENTUM_H24 = 5.0, 20.0
TREND_HOT_TOP, TREND_FRESH_TOP = 5, 3
TREND_MIN_AGE_MS = 5 * 60_000
ORGANIC_MIN = 80.0
DAY_AGE_MS = 24 * H
JOURNAL_COLS = ["date", "equity", "equity_sol", "held", "bought", "closed", "wins", "turnover", "exposure",
                "planned", "no_quote", "fees_sol"]
TRADE_COLS = ["ts", "id", "rule", "side", "mint", "symbol", "sol", "units_raw", "fee_sol", "ret_pct", "why",
              "price_impact_pct", "route", "source"]
# The proof (results/onchain_meme_prereg.md): every rule on its own record.
PROOF_DAYS = 30
PROOF_TRADES = 100
PROOF_TOP5_SHARE = 0.5
PROOF_POS_DAYS = 0.5
PROOF_DEFLATED = 0.95
PROOF_NO_QUOTE = 0.05


def now_ms() -> int:
    return int(time.time() * 1000)


def day_of(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d")


def book_name(rule: str) -> str:
    return PREFIX + rule


def book_dir(rule: str, root: Path | None = None) -> Path:
    from ..data import WRITE_ROOT
    return (WRITE_ROOT if root is None else root) / "paper" / book_name(rule)


def _f(v) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


# ---------------------------------------------------------------- candidates

def from_trends(doc, now: int) -> list[dict]:
    """The fresh pools and the hot migrated coins of our Trends file, when it is fresh."""
    if not isinstance(doc, dict) or now - int(doc.get("written_ms") or doc.get("t") or 0) > TRENDS_MAX_AGE_MS:
        return []
    out = []
    lists = doc.get("lists") or {}
    for name in ("fresh", "hot"):
        for i, e in enumerate(lists.get(name) or []):
            if not isinstance(e, dict) or not e.get("mint") or (name == "hot" and not e.get("migrated")):
                continue
            out.append({"mint": e["mint"], "symbol": e.get("symbol"), "source": f"trends:{name}", "trends": e,
                        "fresh": name == "fresh", "ranks": {name: i + 1}})
    return out


def from_dex(get) -> list[dict]:
    from ..ops import trending as TR
    return [{"mint": t["address"], "symbol": None, "source": f"dexscreener:{t['source']}"}
            for t in TR.dex_tokens(get) if t.get("chain") == "solana"]


def from_jupiter(jup: Jupiter) -> list[dict]:
    out = []
    for path, src in (("/tokens/v2/toptrending/1h", "jupiter:trending"),
                      ("/tokens/v2/toporganicscore/1h", "jupiter:organic")):
        try:
            got = jup.get(path, {"limit": 50})
        except QuoteError:
            continue
        for t in got or []:
            if isinstance(t, dict) and t.get("id"):
                out.append({"mint": t["id"], "symbol": t.get("symbol"), "source": src, "jup": t})
    return out


def merge(*lists: list[dict]) -> dict[str, dict]:
    """One candidate per mint; its sources joined, the Trends entry and Jupiter's entry kept."""
    out: dict[str, dict] = {}
    for lst in lists:
        for c in lst:
            m = c["mint"]
            if m == WSOL:
                continue
            have = out.setdefault(m, {"mint": m, "symbol": None, "sources": [], "trends": None, "jup": None,
                                      "fresh": False, "ranks": {}})
            have["sources"].append(c["source"])
            have["symbol"] = have["symbol"] or c.get("symbol")
            for k in ("trends", "jup"):
                if c.get(k) is not None and have[k] is None:
                    have[k] = c[k]
            have["fresh"] = have["fresh"] or bool(c.get("fresh"))
            for k, r in (c.get("ranks") or {}).items():
                have["ranks"][k] = min(r, have["ranks"].get(k, r))
    return out


def pool_view(pairs: list | None, mint: str) -> dict:
    """What the rules read of a coin's pools: the best pool's liquidity, its 1 h and 24 h change, the oldest
    pool's creation time."""
    best, born = MS.best_pool(pairs or [], mint)
    if best is None:
        return {}
    ch = best.get("priceChange") or {}
    return {"liq_usd": _f((best.get("liquidity") or {}).get("usd")), "h1": _f(ch.get("h1")), "h24": _f(ch.get("h24")),
            "born_ms": born, "dex": best.get("dexId"), "symbol": (best.get("baseToken") or {}).get("symbol")}


# ---------------------------------------------------------------- the rules

def entry_why(rule: str, c: dict, now: int) -> str | None:
    """None when `rule` wants to buy the candidate now (before the safety check), else why not."""
    t = c.get("trends") or {}
    if "rug_risk" in (t.get("badges") or []):
        return "the rug model flags it"
    if t.get("blocked"):
        return "blocked"
    pool = c.get("pool") or {}
    if rule == "fresh_win":
        if not c.get("fresh") or not t.get("migrate_ms"):
            return "not a fresh pool of the Trends file"
        age = now - int(t["migrate_ms"])
        if not FRESH_MIN_MS <= age <= FRESH_MAX_MS:
            return "outside 5 to 30 min after the migration"
        if "win_high" not in (t.get("badges") or []):
            return "no win_high badge"
        return None
    if rule == "trend_top":
        ranks = c.get("ranks") or {}
        if not (ranks.get("hot", TREND_HOT_TOP + 1) <= TREND_HOT_TOP
                or ranks.get("fresh", TREND_FRESH_TOP + 1) <= TREND_FRESH_TOP):
            return "not in the Trends hot top 5 or fresh top 3"
        if not t.get("migrate_ms") or now - int(t["migrate_ms"]) < TREND_MIN_AGE_MS:
            return "not 5 min past its migration"
        if "win_low" in (t.get("badges") or []):
            return "the win model rates it low"
        return None
    if not pool.get("born_ms") or now - pool["born_ms"] < DAY_AGE_MS:
        return "its pool is not a day old"
    if rule == "momentum_trail":
        if (pool.get("liq_usd") or 0) < MOMENTUM_MIN_LIQ:
            return "under 50,000 USD in its pool"
        if (pool.get("h1") or -1e9) < MOMENTUM_H1 or (pool.get("h24") or -1e9) < MOMENTUM_H24:
            return "not up 5 % in 1 h and 20 % in 24 h"
        return None
    if rule == "organic_trend":
        j = c.get("jup") or {}
        if "jupiter:organic" not in c.get("sources", []):
            return "not on Jupiter's organic-score list"
        if (_f(j.get("organicScore")) or 0) < ORGANIC_MIN:
            return "organic score under 80"
        h1 = _f((j.get("stats1h") or {}).get("priceChange"))
        h24 = _f((j.get("stats24h") or {}).get("priceChange"))
        if h1 is None or h24 is None or h1 <= 0 or h24 <= 0:
            return "not up over 1 h and 24 h"
        return None
    return "no such rule"


def exit_why(rule: str, pos: dict, value_sol: float | None, liq_usd: float | None, now: int) -> str | None:
    """Why the position closes now (None: it holds). `value_sol` the sell quote less the fee (None: no quote)."""
    r = RULES[rule]
    if value_sol is None:
        if now - int(pos.get("last_quote_ms") or pos["opened_ms"]) >= NO_QUOTE_MS:
            return "no sell quote for 30 min (closed at zero)"
        return None
    ret = value_sol / pos["cost_sol"] - 1
    peak = max(pos.get("peak_sol") or 0.0, value_sol)
    if r["tp"] is not None and ret >= r["tp"]:
        return "take profit"
    if ret <= r["stop"]:
        return "stop"
    if peak / pos["cost_sol"] - 1 >= r["arm"] and value_sol <= peak * (1 - r["trail"]):
        return "trailing stop"
    if now - pos["opened_ms"] >= r["time_ms"]:
        return "time stop"
    e = pos.get("entry_liq_usd")
    if e and liq_usd is not None and liq_usd < e * (1 - r["liq_drop"]):
        return "liquidity drop"
    return None


# ---------------------------------------------------------------- the paper book

def new_state(rule: str, now: int) -> dict:
    return {"variant": f"EXPERIMENT, paper only · memecoins through Jupiter, {rule}: {RULES[rule]['label']} "
                       f"(0.1 SOL a buy, 1 SOL account, journal on the 10,000 basis)",
            "started": datetime.fromtimestamp(now / 1000, timezone.utc).isoformat(timespec="seconds"),
            "rule": rule, "cash_sol": START_SOL, "positions": {}, "cooldown": {}, "day": None}


def load_state(rule: str, root: Path | None = None, now: int = 0) -> dict:
    try:
        st = json.loads((book_dir(rule, root) / "state.json").read_text(encoding="utf-8"))
        if isinstance(st, dict) and "positions" in st:
            return st
    except (OSError, ValueError):
        pass
    return new_state(rule, now)


def save_state(rule: str, st: dict, root: Path | None = None) -> None:
    d = book_dir(rule, root)
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / "state.json.tmp"
    tmp.write_text(json.dumps(st, indent=1), encoding="utf-8")
    tmp.replace(d / "state.json")


def read_csv(path: Path) -> list[dict]:
    try:
        with path.open(newline="", encoding="utf-8") as fh:
            return list(csv.DictReader(fh))
    except OSError:
        return []


def append_trade(rule: str, row: dict, root: Path | None = None) -> None:
    p = book_dir(rule, root) / "trades.csv"
    p.parent.mkdir(parents=True, exist_ok=True)
    new = not p.exists()
    with p.open("a", newline="", encoding="utf-8") as fh:
        wr = csv.DictWriter(fh, fieldnames=TRADE_COLS, extrasaction="ignore")
        if new:
            wr.writeheader()
        wr.writerow(row)


def write_journal(rule: str, row: dict, root: Path | None = None) -> None:
    """The day's row, rewritten each run (one row per UTC day)."""
    p = book_dir(rule, root) / "journal.csv"
    rows = [r for r in read_csv(p) if r.get("date") != row["date"]] + [row]
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".csv.tmp")
    with tmp.open("w", newline="", encoding="utf-8") as fh:
        wr = csv.DictWriter(fh, fieldnames=JOURNAL_COLS, extrasaction="ignore")
        wr.writeheader()
        wr.writerows(rows)
    tmp.replace(p)


def _day(st: dict, now: int) -> dict:
    d = st.get("day")
    if not isinstance(d, dict) or d.get("date") != day_of(now):
        d = {"date": day_of(now), "bought": 0, "closed": 0, "wins": 0, "planned": 0, "no_quote": 0, "fees_sol": 0.0}
        st["day"] = d
    return d


class Paper:
    """Stage 1's paper fill for a memecoin against SOL: the quote's out amount, less the base and priority fee."""

    def __init__(self, jup: Jupiter, priority: float | None = None):
        self.jup = jup
        self.fee_sol = P.BASE_FEE_SOL + (P.priority_sol() if priority is None else priority)

    def buy(self, mint: str, lamports: int = STAKE_L):
        q = self.jup.quote(WSOL, mint, lamports, QUOTE_SLIPPAGE_BPS)
        return q, q.out_amount

    def sell_value(self, mint: str, units_raw: int):
        """(the quote, SOL it brings less the fee) for selling every unit."""
        q = self.jup.quote(mint, WSOL, units_raw, QUOTE_SLIPPAGE_BPS)
        return q, max(q.out_amount / 1e9 - self.fee_sol, 0.0)


def _trade(pos: dict, rule: str, side: str, now: int, sol: float, fee: float, why: str | None, q=None,
           ret: float | None = None) -> dict:
    return {"ts": now, "id": pos["id"], "rule": rule, "side": side, "mint": pos["mint"], "symbol": pos.get("symbol"),
            "sol": round(sol, 9), "units_raw": pos["units_raw"], "fee_sol": round(fee, 9),
            "ret_pct": None if ret is None else round(ret * 100, 3), "why": why,
            "price_impact_pct": q.price_impact_pct if q is not None else None,
            "route": "+".join(q.labels) if q is not None else None, "source": pos.get("source")}


def run_exits(rule: str, st: dict, ex: Paper, pools: dict[str, dict], now: int, root: Path | None = None,
              write: bool = True) -> list[dict]:
    """Every open position against its sell quote: marked, and closed when an exit says so."""
    day = _day(st, now)
    out = []
    for pid, pos in list(st["positions"].items()):
        try:
            q, value = ex.sell_value(pos["mint"], int(pos["units_raw"]))
        except QuoteError:
            q, value = None, None
        why = exit_why(rule, pos, value, (pools.get(pos["mint"]) or {}).get("liq_usd"), now)
        if value is not None:
            pos.update(last_sol=value, last_quote_ms=now, peak_sol=max(pos.get("peak_sol") or 0.0, value))
        if why is None:
            continue
        day["planned"] += 1
        if value is None:
            day["no_quote"] += 1
        got = value or 0.0
        ret = got / pos["cost_sol"] - 1
        st["cash_sol"] += got
        day["closed"] += 1
        day["wins"] += ret > 0
        day["fees_sol"] += ex.fee_sol if value is not None else 0.0
        del st["positions"][pid]
        row = _trade(pos, rule, "sell", now, got, ex.fee_sol if value is not None else 0.0, why, q, ret)
        out.append(row)
        if write:
            append_trade(rule, row, root)
    return out


def try_entry(rule: str, st: dict, ex: Paper, c: dict, now: int, root: Path | None = None,
              write: bool = True) -> dict | None:
    """Buy STAKE_L of the candidate through a real quote, when the book has the cash and a free slot."""
    if len(st["positions"]) >= MAX_OPEN:
        return None
    if now - int(st["cooldown"].get(c["mint"]) or 0) < COOLDOWN_MS:
        return None
    if any(p["mint"] == c["mint"] for p in st["positions"].values()):
        return None
    cost = STAKE_L / 1e9 + ex.fee_sol
    if st["cash_sol"] < cost:
        return None
    day = _day(st, now)
    day["planned"] += 1
    try:
        q, units = ex.buy(c["mint"])
    except QuoteError:
        day["no_quote"] += 1
        return None
    if units <= 0:
        day["no_quote"] += 1
        return None
    pos = {"id": f"{rule}-{c['mint'][:8]}-{now}", "mint": c["mint"], "symbol": c.get("symbol") or
           (c.get("pool") or {}).get("symbol"), "opened_ms": now, "cost_sol": cost, "units_raw": units,
           "entry_liq_usd": (c.get("pool") or {}).get("liq_usd"), "peak_sol": STAKE_L / 1e9, "last_sol": STAKE_L / 1e9,
           "last_quote_ms": now, "source": ",".join(c.get("sources") or [])}
    st["positions"][pos["id"]] = pos
    st["cooldown"][c["mint"]] = now
    st["cash_sol"] -= cost
    day["bought"] += 1
    day["fees_sol"] += ex.fee_sol
    row = _trade(pos, rule, "buy", now, STAKE_L / 1e9, ex.fee_sol, None, q)
    if write:
        append_trade(rule, row, root)
    return row


def journal_row(st: dict, now: int) -> dict:
    day = _day(st, now)
    held = sum(p.get("last_sol") or 0.0 for p in st["positions"].values())
    eq = st["cash_sol"] + held
    return {"date": day["date"], "equity": round(eq / START_SOL * INDEX, 2), "equity_sol": round(eq, 9),
            "held": len(st["positions"]), "bought": day["bought"], "closed": day["closed"], "wins": day["wins"],
            "turnover": round((day["bought"] + day["closed"]) * STAKE_L / 1e9 / eq, 4) if eq > 0 else 0.0,
            "exposure": round(held / eq, 4) if eq > 0 else 0.0, "planned": day["planned"],
            "no_quote": day["no_quote"], "fees_sol": round(day["fees_sol"], 9)}


def verdict_for(mint: str, src: MS.Sources, now: int, budget: list[int], blocked, exceptions) -> dict | None:
    """A cached verdict up to PAPER_MAX_AGE_MS old, else a new check while the run's budget lasts."""
    v = MS.cached(mint, MS.PAPER_MAX_AGE_MS, now)
    if v is not None:
        return v
    if budget[0] <= 0:
        return None
    budget[0] -= 1
    return MS.check(mint, src, blocked, exceptions, now).record()


def run(jup: Jupiter, src: MS.Sources, now: int | None = None, root: Path | None = None,
        trends_doc=None, dex_get=None, dry_run: bool = False) -> dict:
    """One run of every rule's paper book. Returns what happened, per rule."""
    now = now_ms() if now is None else now
    if trends_doc is None:
        try:
            trends_doc = json.loads((report.REPORTS / "pumpfun_rt" / "trends.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            trends_doc = None
    cands = merge(from_trends(trends_doc, now), from_dex(dex_get) if dex_get else [], from_jupiter(jup))
    states = {r: load_state(r, root, now) for r in RULES}
    held = [p["mint"] for st in states.values() for p in st["positions"].values()]
    pairs = src.pairs(list(cands) + held)
    pools = {m: pool_view(pairs.get(m), m) for m in set(cands) | set(held)}
    for m, c in cands.items():
        c["pool"] = pools.get(m) or {}
    ex = Paper(jup)
    blocked, exceptions = MS.read_blocked(), MS.read_lines(MS.exception_paths())
    budget = [MAX_CHECKS]
    out = {"t": now, "candidates": len(cands), "rules": {}}
    for rule in RULES:
        st = states[rule]
        closed = run_exits(rule, st, ex, pools, now, root, write=not dry_run)
        bought, skipped = [], {}
        for m, c in cands.items():
            why = entry_why(rule, c, now)
            if why is None:
                v = verdict_for(m, src, now, budget, blocked, exceptions) if not dry_run else MS.cached(
                    m, MS.PAPER_MAX_AGE_MS, now)
                if v is None:
                    why = "no safety verdict this run"
                elif not v.get("ok"):
                    why = "safety: " + "; ".join(v.get("reasons") or [])
            if why is not None:
                skipped[why] = skipped.get(why, 0) + 1
                continue
            row = None if dry_run else try_entry(rule, st, ex, c, now, root)
            if row is not None:
                bought.append(row)
        jr = journal_row(st, now)
        if not dry_run:
            write_journal(rule, jr, root)
            save_state(rule, st, root)
        out["rules"][rule] = {"bought": len(bought), "closed": len(closed), "open": len(st["positions"]),
                              "equity_sol": jr["equity_sol"], "skipped": skipped}
    if not dry_run:
        from ..pumpfun_rt import live_exec as PX
        PX.write_json(report.REPORTS / REPORT / "books.json", out)
    return out


# ---------------------------------------------------------------- the proof

def rule_record(rule: str, root: Path | None = None) -> tuple[list[dict], list[dict]]:
    d = book_dir(rule, root)
    return read_csv(d / "journal.csv"), read_csv(d / "trades.csv")


def proof_of(journal: list[dict], trades: list[dict], pool: dict | None) -> dict:
    """The pre-registered checks of one rule (results/onchain_meme_prereg.md, P1 to P6) from its record."""
    import numpy as np
    sells = [t for t in trades if t.get("side") == "sell" and _f(t.get("ret_pct")) is not None]
    buys = {t["id"]: t for t in trades if t.get("side") == "buy"}
    rets = [{"signal_ms": int((buys.get(t["id"]) or t)["ts"]), "ret": _f(t["ret_pct"]) / 100} for t in sells]
    cost = {i: (_f(b.get("sol")) or 0.0) + (_f(b.get("fee_sol")) or 0.0) for i, b in buys.items()}
    pnl = [(_f(t["sol"]) or 0.0) - cost.get(t["id"], STAKE_L / 1e9) for t in sells]
    eq = [START_SOL * INDEX] + [_f(r.get("equity")) or 0.0 for r in journal]
    daily = np.array([eq[i + 1] / eq[i] - 1 for i in range(len(eq) - 1) if eq[i] > 0])
    mean = float(np.mean([r["ret"] for r in rets])) if rets else None
    lo = None
    if rets:
        from ..pumpfun_rt import study as ST
        lo = ST.boot_mean(rets)[0]
        lo = None if lo != lo else lo
    total = sum(pnl)
    top5 = sum(sorted(pnl, reverse=True)[:5])
    pos_days = float((daily > 0).mean()) if len(daily) else 0.0
    dp = None
    if pool and len(daily) >= 5 and daily.std() > 0:
        try:
            from ..experiments import flow_overlays as fo
            dp = float(fo.deflated(daily, pool["n_total"], pool["var"]))
        except Exception:
            dp = None
    planned = sum(int(_f(r.get("planned")) or 0) for r in journal)
    noq = sum(int(_f(r.get("no_quote")) or 0) for r in journal)
    checks = {
        "p1_days": {"value": len(journal), "need": PROOF_DAYS, "passed": len(journal) >= PROOF_DAYS},
        "p2_trades": {"value": len(sells), "need": PROOF_TRADES, "passed": len(sells) >= PROOF_TRADES},
        "p3_mean_band": {"value": mean, "band_low": lo, "passed": bool(mean is not None and mean > 0
                                                                       and lo is not None and lo > 0)},
        "p4_breadth": {"pnl_sol": total, "top5_sol": top5, "positive_days": pos_days,
                       "passed": bool(total > 0 and top5 < PROOF_TOP5_SHARE * total and pos_days >= PROOF_POS_DAYS)},
        "p5_deflated": {"value": dp, "need": PROOF_DEFLATED, "passed": bool(dp is not None and dp > PROOF_DEFLATED)},
        "p6_quotes": {"value": noq / planned if planned else None, "need": PROOF_NO_QUOTE,
                      "passed": bool(planned and noq / planned <= PROOF_NO_QUOTE)},
    }
    return {"passed": all(c["passed"] for c in checks.values()), "checks": checks, "trades": len(sells),
            "days": len(journal)}


def global_pool() -> dict | None:
    """The lab's deflation pool (pumpfun_rt.study.pool: hand trials, the factory, pump.fun's) plus our TRIALS."""
    try:
        from ..pumpfun_rt import study as ST
        p = ST.pool([])
        return {**p, "n_total": p["n_total"] + TRIALS, "meme_trials": TRIALS}
    except Exception:
        return None


def write_proof(now: int | None = None, root: Path | None = None) -> dict:
    now = now_ms() if now is None else now
    pool = global_pool()
    rules = {r: proof_of(*rule_record(r, root), pool) for r in RULES}
    data = {"updated_ms": now, "prereg": "research/lab/results/onchain_meme_prereg.md", "trials": TRIALS,
            "pool_trials": (pool or {}).get("n_total"), "rules": rules}
    from ..pumpfun_rt import live_exec as PX
    PX.write_json(report.REPORTS / REPORT / "proof.json", data)
    passed = [r for r, v in rules.items() if v["passed"]]
    head = (f"Meme rules on paper: {', '.join(passed)} passed the pre-registered proof." if passed else
            "Meme rules on paper: none has passed the pre-registered proof; nothing may trade real money.")
    rows = [{"rule": r, "days": v["days"], "trades": v["trades"], "mean_pct": None if v["checks"]["p3_mean_band"]["value"]
             is None else round(v["checks"]["p3_mean_band"]["value"] * 100, 2),
             "passed": ", ".join(k for k, c in v["checks"].items() if c["passed"]) or "none",
             "proof": "PASSED" if v["passed"] else "not yet"} for r, v in rules.items()]
    md = ["# Meme rules on our own wallet: paper books and the proof\n", f"EXPERIMENT, paper only. {head}\n",
          report.table(rows, ["rule", "days", "trades", "mean_pct", "passed", "proof"]),
          f"\nRules and checks: research/lab/results/onchain_meme_prereg.md ({TRIALS} trials; deflated over "
          f"{(pool or {}).get('n_total', 'n/a')}). How it works: docs/ONCHAIN-MEME.md.\n"]
    report.write(REPORT, "\n".join(md), {**report.feed_header("Meme rules (paper)", "ok" if passed else "watch", head,
                                                              updated_ms=now), "verdict": head, "proof": data})
    return data


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--proof", action="store_true", help="the pre-registered proof (daily)")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    if a.proof:
        d = write_proof()
        print(json.dumps({r: v["passed"] for r, v in d["rules"].items()}))
        return 0
    from ..ops import trending as TR
    src = MS.default_sources()
    out = run(Jupiter(), src, dex_get=TR.http_json, dry_run=a.dry_run)
    print(f"onchain meme: {json.dumps(out)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
