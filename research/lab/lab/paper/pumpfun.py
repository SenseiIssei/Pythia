"""pump.fun PAPER watcher and books (Solana memecoins). Read-only public data; no wallet, no key, no transaction.

    python -m lab.paper.pumpfun              one watcher run (cron, every 5 minutes)
    python -m lab.paper.pumpfun --report     the daily report and its Telegram card
    python -m lab.paper.pumpfun --dry-run    one run, printed; nothing written or posted
    python -m lab.paper.pumpfun --rebuild    replay the ledger with the funding and one-buy-per-token
                                             rules; rewrite the journals and the state (--dry-run prints)

Nothing in this module can trade. It holds no wallet, reads no key, signs and
sends nothing; every "buy" and "sell" is arithmetic on public prices, written
to a paper ledger. That is a rule of the project, not a setting.

Sources (both public, keyless, read only):

  GeckoTerminal  /networks/solana/new_pools (the newest pools on Solana, 20 a
                 page, up to MAX_PAGES pages a run, stopping at pools seen in
                 the run before) and /networks/solana/tokens/<mint>/info
                 (holders, top-10 share, mint and freeze authority, honeypot
                 flag, pump.fun's own "graduation completed"). The free public
                 API documents 30 calls a minute but cut a burst off after one
                 call when tested; calls are spaced GT_GAP_S apart, at most
                 GT_MAX_CALLS a run (INFO_PER_RUN of them token lookups), and
                 a 429 stops calls to it for the run. With MAX_PAGES pages a
                 run the watcher sees roughly the newest 100 pools of every
                 five minutes, a sample of the stream taken by time, not by
                 outcome.
  DexScreener    /tokens/v1/solana/<up to 30 mints> for the hourly and per-run
                 marks of open positions: price, liquidity in USD and in the
                 pool's two reserves. 300 calls a minute on the pair
                 endpoints; at most DS_MAX_CALLS a run, spaced DS_GAP_S.

pump.fun's own frontend API is NOT used: its terms of use (sections 6.1 and
21(h), as of 2026-10-08) forbid bots and other automatic access unless pump.fun
expressly permits it. Everything here comes from the two aggregators above.

What counts as what. A pool on GeckoTerminal's dex "pump-fun" is a new token
on pump.fun's bonding curve: every one is a candidate and is counted. A pool
on dex "pumpswap" whose base mint ends in "pump" is a token that completed its
bonding curve and migrated to PumpSwap (a graduation): that is the only moment
the rules below may buy. Pools the pages did not reach between two runs are
missed; each run records how far back it saw, so the report says how much of
the stream was covered.

Pre-registered rules (written 2026-10-15 before any paper position existed;
changing one means a new rule with a new name, never an edit):

  migration      buy every graduation whose pool holds at least $10,000 of
                 liquidity at the run that sees it. Exit after 24 hours, or on
                 a 30 % trailing stop from the highest mark since entry.
  filtered       graduations with at least $20,000 of liquidity, 300 holders
                 or more, the top 10 holders under 30 % of the supply, mint and
                 freeze authority renounced and not flagged a honeypot. Exit
                 after 72 hours or on a 40 % trailing stop.
  filtered_quick the filtered entry; exit at +100 % (take profit), after 6
                 hours, or on a 25 % trailing stop.

Each rule is a paper book (<data>/paper/pumpfun_<rule>/journal.csv, one row
per UTC day, from $10,000) that stakes a fixed $100 a token, at most 40 open
at once (a token seen while 40 are open is skipped and journaled as skipped).
A token is one graduation: a rule buys a mint once, however many PumpSwap
pools of it a run sees.

The book has the money it has. A position bought while the book's cash is
under the stake is UNFUNDED: it is followed exactly like a funded one (its
marks, its exit, its return), so the rule's per-token record stays complete,
but it moves no cash and is not in the book's equity. The book's return is
its equity (cash plus the funded positions at their marks) against $10,000,
so it cannot fall below -100 %. Before 2026-10-21 the cash went negative and
the "book return" was the sum of every trade's dollar result over $10,000
(-965 % for migration); `--rebuild` replays the ledger under these rules and
rewrites the journals and the state (see results/forward_audit.md).

Fills. Entry at the pool price of the run that sees the graduation (up to 5
minutes after it, so never the migration price itself), through constant
product AMM arithmetic on the pool's quote reserve (half its USD liquidity):
the stake less the pool fee buys reserve x stake / (reserve + stake) worth of
tokens at the spot price, which is the slippage of a pool that thin. Fees: the
PumpSwap pool fee POOL_FEE a side (pump.fun's own 1 % applies on the bonding
curve, which these rules never trade; POOL_FEE is set at the top of PumpSwap's
low market cap tier so it is not flattering), plus a Solana base and priority
fee of TX_FEE_SOL per transaction at the pool's SOL price. Exits sell through
the same arithmetic at the mark that triggers them; between marks the price is
not seen, so a stop fills where the next mark is, not at its level.

Rugs. A position whose pool liquidity falls under RUG_LIQ_USD, or whose token
has no pool on DexScreener in GONE_RUNS runs in a row spanning at least an
hour, is closed at zero: a total loss, recorded as "rug". Nothing is rounded
up because a price is still quoted on an empty pool.

Tracking. Every run marks the open positions; once an hour each is written to
<data>/paper/pumpfun/marks.csv (time, rule, token, price, liquidity, value,
return). Every paper fill is in <data>/paper/pumpfun/ledger.csv. Watcher
state: <data>/paper/pumpfun/state.json. New tokens seen per day: counts in the
state, the pools themselves in <data>/paper/pumpfun/candidates/<day>.jsonl.

Report (--report, daily): <reports>/pumpfun/latest.json with the lab feed
header (title, updated_ms, status, headline, items), latest.md and dated
copies. Alerts (category "trending", through lab.ops.notify): a closed paper
position at +100 % or better is posted at once, and the run's closes at -80 %
or worse (rugs included) are posted together, at most once an hour.

The honest expectation is in results/experiments.md: most of these tokens go
to zero. The books exist to measure how fast and how often, not to find money.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from ..data import ROOT, WRITE_ROOT
from ..ops import i18n as _i18n

NAME = "pumpfun"
GT = "https://api.geckoterminal.com/api/v2"
DEX = "https://api.dexscreener.com"
GRADUATED_DEX = "pumpswap"
LAUNCH_DEX = "pump-fun"
# GeckoTerminal documents 30 calls a minute but answered 429 after a short burst
# when this was written, so a run stays far below: one call every 6.5 s, at most 8.
MAX_PAGES = 5
GT_GAP_S, GT_MAX_CALLS = 6.5, 8
INFO_PER_RUN = 3
DS_GAP_S, DS_MAX_CALLS = 0.25, 20

STAKE_USD = 100.0
START_EQUITY = 10_000.0
MAX_OPEN = 40
POOL_FEE = 0.0125            # a side; PumpSwap's fee at the low market cap tier, rounded up
TX_FEE_SOL = 0.002           # base fee plus a priority fee, per transaction
RUG_LIQ_USD = 500.0
GONE_RUNS = 3
WIN_ALERT, LOSS_ALERT = 1.0, -0.8
HOUR_MS, DAY_MS = 3_600_000, 86_400_000

RULES: dict[str, dict] = {
    "migration": {"min_liq": 10_000.0, "filter": False, "hold_h": 24, "trail": 0.30, "take": None,
                  "label": "every graduation, liquidity $10k+, 24 h or 30 % trailing stop"},
    "filtered": {"min_liq": 20_000.0, "filter": True, "hold_h": 72, "trail": 0.40, "take": None,
                 "label": "graduations with $20k+ liquidity, 300+ holders, top 10 under 30 %, authorities "
                          "renounced; 72 h or 40 % trailing stop"},
    "filtered_quick": {"min_liq": 20_000.0, "filter": True, "hold_h": 6, "trail": 0.25, "take": 1.0,
                       "label": "the filtered entry; +100 %, 6 h or 25 % trailing stop"},
}
MIN_HOLDERS, MAX_TOP10 = 300, 30.0
CAVEAT = _i18n.t("pf_caveat", "en")       # the report's (English) caveat; posts take it in their language

Fetch = Callable[[str], object]


class RateLimited(OSError):
    """The host answered 429 or 418; no more calls to it this run."""


class Http:
    """Spaced, budgeted GET of JSON per host. A 429 blocks the host for the run."""

    def __init__(self, gaps: dict[str, float] | None = None, budgets: dict[str, int] | None = None):
        self.gaps = gaps or {"api.geckoterminal.com": GT_GAP_S, "api.dexscreener.com": DS_GAP_S}
        self.budgets = dict(budgets or {"api.geckoterminal.com": GT_MAX_CALLS, "api.dexscreener.com": DS_MAX_CALLS})
        self.last: dict[str, float] = {}
        self.blocked: set[str] = set()
        self.calls: dict[str, int] = {}

    def __call__(self, url: str):
        host = urllib.parse.urlsplit(url).netloc
        if host in self.blocked:
            raise RateLimited(f"{host} rate limited earlier in this run")
        if self.calls.get(host, 0) >= self.budgets.get(host, 10):
            raise RateLimited(f"{host}: this run's budget of calls is spent")
        wait = self.last.get(host, 0.0) + self.gaps.get(host, 1.0) - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self.last[host] = time.monotonic()
        self.calls[host] = self.calls.get(host, 0) + 1
        req = urllib.request.Request(url, headers={"User-Agent": "pythia-lab (paper research, read only)",
                                                   "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code in (418, 429):
                self.blocked.add(host)
                raise RateLimited(f"{host} HTTP {e.code}") from e
            raise


def num(v) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def iso_ms(s: str | None) -> int | None:
    if not s:
        return None
    try:
        return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp() * 1000)
    except ValueError:
        return None


def paper_dir() -> Path:
    return WRITE_ROOT / "paper" / NAME


def book_dir(rule: str) -> Path:
    return WRITE_ROOT / "paper" / f"{NAME}_{rule}"


# ---------------------------------------------------------------- AMM arithmetic

def amm_buy(usd: float, quote_reserve_usd: float, price: float, fee: float = POOL_FEE) -> float:
    """Tokens a buy of `usd` gets from a constant-product pool whose quote side holds
    quote_reserve_usd at spot `price`: the fee comes off first, then the trade moves
    the price along x * y = k."""
    if usd <= 0 or quote_reserve_usd <= 0 or price <= 0:
        return 0.0
    a = usd * (1 - fee)
    base_reserve = quote_reserve_usd / price
    return base_reserve * a / (quote_reserve_usd + a)


def amm_sell(tokens: float, quote_reserve_usd: float, price: float, fee: float = POOL_FEE) -> float:
    """USD a sale of `tokens` gets from the same pool, after the fee."""
    if tokens <= 0 or quote_reserve_usd <= 0 or price <= 0:
        return 0.0
    base_reserve = quote_reserve_usd / price
    q = tokens * (1 - fee)
    return quote_reserve_usd * q / (base_reserve + q)


def tx_cost_usd(sol_usd: float | None) -> float:
    return TX_FEE_SOL * (sol_usd if sol_usd and sol_usd > 0 else 150.0)


# ---------------------------------------------------------------- reading the sources

def new_pools(get: Fetch, since_ms: int, pages: int = MAX_PAGES) -> tuple[list[dict], dict]:
    """The newest Solana pools down to since_ms. Returns (pools, coverage), each pool
    flattened to what the rules need."""
    out, oldest, reached, errors = [], None, False, []
    for page in range(1, pages + 1):
        try:
            got = get(f"{GT}/networks/solana/new_pools?page={page}")
        except (OSError, ValueError) as e:
            errors.append(f"geckoterminal new_pools: {type(e).__name__}")
            break
        data = (got or {}).get("data") if isinstance(got, dict) else None
        if not data:
            break
        for p in data:
            a, rel = p.get("attributes") or {}, p.get("relationships") or {}
            created = iso_ms(a.get("pool_created_at"))
            base = ((rel.get("base_token") or {}).get("data") or {}).get("id", "")
            out.append({
                "pool": a.get("address"), "dex": ((rel.get("dex") or {}).get("data") or {}).get("id"),
                "mint": base.split("_", 1)[1] if "_" in base else base, "name": a.get("name"),
                "created_ms": created, "price_usd": num(a.get("base_token_price_usd")),
                "sol_usd": num(a.get("quote_token_price_usd")), "liq_usd": num(a.get("reserve_in_usd")),
                "fdv_usd": num(a.get("fdv_usd")),
            })
            if created is not None:
                oldest = created if oldest is None else min(oldest, created)
        if oldest is not None and oldest <= since_ms:
            reached = True
            break
    return out, {"oldest_ms": oldest, "reached_last_run": reached, "errors": errors}


def token_info(get: Fetch, mint: str) -> dict | None:
    """Holders and safety flags of one token from GeckoTerminal, or None."""
    try:
        got = get(f"{GT}/networks/solana/tokens/{urllib.parse.quote(mint)}/info")
    except (OSError, ValueError):
        return None
    a = ((got or {}).get("data") or {}).get("attributes") if isinstance(got, dict) else None
    if not a:
        return None
    h = a.get("holders") or {}
    dist = h.get("distribution_percentage") or {}
    lp = a.get("launchpad_details") or {}
    return {"holders": num(h.get("count")), "top10_pct": num(dist.get("top_10")),
            "mint_authority": a.get("mint_authority"), "freeze_authority": a.get("freeze_authority"),
            "honeypot": a.get("is_honeypot"), "graduated": lp.get("completed"), "symbol": a.get("symbol")}


def dex_marks(get: Fetch, mints: list[str]) -> dict[str, dict]:
    """Price and liquidity of each mint's most liquid Solana pair on DexScreener.
    A mint DexScreener answered for without any pair is in the result as {}."""
    out: dict[str, dict] = {}
    for i in range(0, len(mints), 30):
        chunk = mints[i:i + 30]
        try:
            got = get(f"{DEX}/tokens/v1/solana/{urllib.parse.quote(','.join(chunk), safe=',')}")
        except (OSError, ValueError):
            continue
        pairs = got if isinstance(got, list) else []
        for m in chunk:
            mine = [p for p in pairs if ((p.get("baseToken") or {}).get("address") or "") == m]
            best = max(mine, key=lambda p: num((p.get("liquidity") or {}).get("usd")) or 0.0, default=None)
            if best is None:
                out[m] = {}
                continue
            liq = best.get("liquidity") or {}
            out[m] = {"price_usd": num(best.get("priceUsd")), "liq_usd": num(liq.get("usd")),
                      "dex": best.get("dexId"), "pair": best.get("pairAddress")}
    return out


# ---------------------------------------------------------------- rules

def is_graduation(pool: dict) -> bool:
    return pool.get("dex") == GRADUATED_DEX and str(pool.get("mint") or "").endswith("pump")


def passes(rule: str, pool: dict, info: dict | None) -> tuple[bool, str]:
    """Whether a graduation qualifies for `rule`, and why not when it does not."""
    r = RULES[rule]
    liq = pool.get("liq_usd") or 0.0
    if liq < r["min_liq"]:
        return False, f"liquidity ${liq:,.0f} under ${r['min_liq']:,.0f}"
    if not pool.get("price_usd"):
        return False, "no price"
    if not r["filter"]:
        return True, "ok"
    if info is None:
        return False, "no holder data (not bought)"
    if (info.get("holders") or 0) < MIN_HOLDERS:
        return False, f"{info.get('holders') or 0:.0f} holders under {MIN_HOLDERS}"
    top = info.get("top10_pct")
    if top is None or top >= MAX_TOP10:
        return False, f"top 10 hold {top if top is not None else 'unknown'} %"
    if info.get("mint_authority") != "no" or info.get("freeze_authority") != "no":
        return False, "mint or freeze authority not renounced"
    if str(info.get("honeypot")).lower() == "yes":
        return False, "flagged honeypot"
    return True, "ok"


# ---------------------------------------------------------------- the books

def new_state() -> dict:
    return {"last_seen_ms": 0, "seen": {}, "positions": [], "books": {r: {"cash": START_EQUITY} for r in RULES},
            "counts": {}, "last_marks_hour": 0, "last_loss_alert_ms": 0, "runs": 0, "coverage": {}}


def _count(st: dict, day: str, key: str, n: int = 1) -> None:
    c = st["counts"].setdefault(day, {})
    c[key] = c.get(key, 0) + n


def open_positions(st: dict, rule: str | None = None) -> list[dict]:
    return [p for p in st["positions"] if p["open"] and (rule is None or p["rule"] == rule)]


def funded(p: dict) -> bool:
    """Whether a position is in the book's money (positions from before funding existed are)."""
    return p.get("funded", True)


def why_not_enter(st: dict, rule: str, mint: str) -> str | None:
    """Why a rule does not buy this token now: already bought (a token is one
    graduation, whatever pools it has) or the open limit. None: it buys."""
    if any(p["rule"] == rule and p["mint"] == mint for p in st["positions"]):
        return "bought already"
    if len(open_positions(st, rule)) >= MAX_OPEN:
        return f"{MAX_OPEN} open already"
    return None


def enter(st: dict, rule: str, pool: dict, now: int, ledger: list) -> dict | None:
    if why_not_enter(st, rule, pool["mint"]):
        return None
    tx = tx_cost_usd(pool.get("sol_usd"))
    usd = STAKE_USD - tx
    tokens = amm_buy(usd, (pool["liq_usd"] or 0.0) / 2, pool["price_usd"])
    if tokens <= 0:
        return None
    # The book cannot spend money it does not have: without the stake in cash
    # the position is followed unfunded (see the module docs).
    has_cash = st["books"][rule]["cash"] >= STAKE_USD - 1e-9
    if has_cash:
        st["books"][rule]["cash"] -= STAKE_USD
    p = {"rule": rule, "mint": pool["mint"], "pool": pool.get("pool"), "name": pool.get("name"), "open": True,
         "entry_ms": now, "stake": STAKE_USD, "tokens": tokens, "entry_price": pool["price_usd"],
         "eff_price": STAKE_USD / tokens, "peak": pool["price_usd"], "last_price": pool["price_usd"],
         "last_liq": pool["liq_usd"], "sol_usd": pool.get("sol_usd"), "gone": 0, "gone_since": None,
         "value": STAKE_USD, "exit": None, "funded": has_cash}
    st["positions"].append(p)
    ledger.append({"ts_ms": now, "rule": rule, "mint": pool["mint"], "name": pool.get("name"), "side": "buy",
                   "usd": STAKE_USD, "tokens": tokens, "price": pool["price_usd"], "liq_usd": pool["liq_usd"],
                   "reason": "graduation" if has_cash else "graduation, unfunded (book cash under the stake)"})
    return p


def value_now(p: dict, price: float | None, liq: float | None) -> float:
    """What selling the position at this mark would bring, after fees."""
    if not price or not liq or liq < RUG_LIQ_USD:
        return 0.0
    return max(0.0, amm_sell(p["tokens"], liq / 2, price) - tx_cost_usd(p.get("sol_usd")))


def close(st: dict, p: dict, now: int, usd: float, reason: str, ledger: list, code: str = "",
          arg: dict | None = None) -> None:
    """Close a paper position. `reason` is the English record; `code` and `arg` let a
    message say it in the owner's language (reason_text)."""
    p.update(open=False, exit={"ts_ms": now, "usd": usd, "reason": reason, "code": code, "arg": arg or {},
                               "ret": usd / p["stake"] - 1, "hours": (now - p["entry_ms"]) / HOUR_MS})
    p["value"] = usd
    if funded(p):
        st["books"][p["rule"]]["cash"] += usd
    ledger.append({"ts_ms": now, "rule": p["rule"], "mint": p["mint"], "name": p.get("name"), "side": "sell",
                   "usd": usd, "tokens": p["tokens"], "price": p.get("last_price"), "liq_usd": p.get("last_liq"),
                   "reason": reason})


def mark_and_exit(st: dict, marks: dict[str, dict], now: int, ledger: list) -> list[dict]:
    """Mark every open position; close rugs, stops, targets and time exits. Returns the closes."""
    closed = []
    for p in open_positions(st):
        r = RULES[p["rule"]]
        m = marks.get(p["mint"])
        if m is None:
            continue                                     # not asked this run (budget): unchanged
        price, liq = m.get("price_usd"), m.get("liq_usd")
        if not m or price is None:
            p["gone"] += 1
            p["gone_since"] = p["gone_since"] or now
            if p["gone"] >= GONE_RUNS and now - p["gone_since"] >= HOUR_MS:
                close(st, p, now, 0.0, "rug: no pool left", ledger, "rug_gone")
                closed.append(p)
            continue
        p["gone"], p["gone_since"] = 0, None
        p["last_price"], p["last_liq"] = price, liq
        if liq is not None and liq < RUG_LIQ_USD:
            close(st, p, now, 0.0, f"rug: liquidity ${liq:,.0f}", ledger, "rug_liq", {"liq": liq})
            closed.append(p)
            continue
        p["peak"] = max(p["peak"], price)
        p["value"] = value_now(p, price, liq)
        why = None
        if r["take"] is not None and price >= p["entry_price"] * (1 + r["take"]):
            why = (f"take profit +{r['take'] * 100:.0f} %", "take", {"f": r["take"]})
        elif price <= p["peak"] * (1 - r["trail"]):
            why = (f"trailing stop {r['trail'] * 100:.0f} %", "trail", {"f": r["trail"]})
        elif now - p["entry_ms"] >= r["hold_h"] * HOUR_MS:
            why = (f"time {r['hold_h']} h", "time", {"h": r["hold_h"]})
        if why:
            close(st, p, now, p["value"], why[0], ledger, why[1], why[2])
            closed.append(p)
    return closed


def reason_text(e: dict, lang: str = "en") -> str:
    """Why a position closed, in the message language (the English record when unknown)."""
    from ..ops import i18n
    code, a = e.get("code") or "", e.get("arg") or {}
    if code == "take":
        return i18n.t("pf_take", lang, pct=i18n.frac_pct(a["f"], 0, lang))
    if code == "trail":
        return i18n.t("pf_trail", lang, pct=i18n.frac_pct(a["f"], 0, lang, sign=False))
    if code == "time":
        return i18n.t("pf_time", lang, h=a["h"])
    if code == "rug_liq":
        return i18n.t("pf_rug_liq", lang, usd=i18n.money(a["liq"], 0, lang))
    if code == "rug_gone":
        return i18n.t("pf_rug_gone", lang)
    return e.get("reason", "")


def equity(st: dict, rule: str) -> float:
    """Cash plus the funded open positions at their marks. Never below zero: the
    book only buys with cash it has, and a position is worth at least nothing."""
    return st["books"][rule]["cash"] + sum(p["value"] for p in open_positions(st, rule) if funded(p))


def run(get: Fetch, now: int, st: dict | None = None, info_budget: int = INFO_PER_RUN) -> dict:
    """One watcher run. Returns {"state", "ledger", "closed", "seen", "bought", "skipped", "errors", "coverage"}."""
    st = st or new_state()
    day = datetime.fromtimestamp(now / 1000, timezone.utc).strftime("%Y-%m-%d")
    ledger: list[dict] = []
    since = st["last_seen_ms"] or now - 10 * 60_000
    pools, cov = new_pools(get, since)
    fresh = [p for p in pools if p["pool"] and p["pool"] not in st["seen"] and (p["created_ms"] or 0) > since - 60_000]
    launches = [p for p in fresh if p["dex"] == LAUNCH_DEX]
    grads = [p for p in fresh if is_graduation(p)]
    _count(st, day, "launches", len(launches))
    _count(st, day, "graduations", len(grads))
    _count(st, day, "runs")
    if not cov["reached_last_run"] and pools:
        _count(st, day, "coverage_gaps")
    for p in fresh:
        st["seen"][p["pool"]] = p["created_ms"] or now
    if pools:
        st["last_seen_ms"] = max([st["last_seen_ms"]] + [p["created_ms"] or 0 for p in pools])
    bought, skipped = [], []
    for g in grads:
        info = None
        if any(RULES[r]["filter"] for r in RULES) and (g["liq_usd"] or 0) >= min(r["min_liq"] for r in RULES.values()):
            if info_budget > 0:
                info_budget -= 1
                info = token_info(get, g["mint"])
        g["info"] = info
        for rule in RULES:
            ok, why = passes(rule, g, info)
            if ok:
                why = why_not_enter(st, rule, g["mint"]) or "no tokens at this price"
                p = enter(st, rule, g, now, ledger)
                if p is not None:
                    bought.append((rule, g))
                    _count(st, day, f"bought_{rule}")
                    if not funded(p):
                        _count(st, day, f"unfunded_{rule}")
                    continue
            skipped.append((rule, g, why))
    # Marks for every open position (the ones just bought too: their first mark).
    mints = sorted({p["mint"] for p in open_positions(st)})
    marks = dex_marks(get, mints) if mints else {}
    closed = mark_and_exit(st, marks, now, ledger)
    for p in closed:
        _count(st, day, "rugs" if p["exit"]["reason"].startswith("rug") else "closed")
    # Forget pools older than two days.
    st["seen"] = {k: v for k, v in st["seen"].items() if v >= now - 2 * DAY_MS}
    st["runs"] = st.get("runs", 0) + 1
    st["coverage"] = {"last_run_ms": now, **cov}
    st["counts"] = {d: c for d, c in st["counts"].items() if d >= _day(now - 60 * DAY_MS)}
    return {"state": st, "ledger": ledger, "closed": closed, "seen": len(fresh), "launches": len(launches),
            "graduations": grads, "bought": bought, "skipped": skipped, "marks": marks, "coverage": cov}


def _day(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d")


# ---------------------------------------------------------------- files

def _append_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as fh:
        wr = csv.DictWriter(fh, fieldnames=list(rows[0]), extrasaction="ignore")
        if new:
            wr.writeheader()
        for r in rows:
            wr.writerow(r)


def hourly_marks(st: dict, now: int) -> list[dict]:
    """Once an hour, a row per open position."""
    hour = now // HOUR_MS
    if hour <= st.get("last_marks_hour", 0):
        return []
    st["last_marks_hour"] = hour
    return [{"ts_ms": now, "rule": p["rule"], "mint": p["mint"], "name": p.get("name"), "price": p["last_price"],
             "liq_usd": p["last_liq"], "value": round(p["value"], 4), "ret": round(p["value"] / p["stake"] - 1, 4),
             "hours": round((now - p["entry_ms"]) / HOUR_MS, 2)} for p in open_positions(st)]


def journal_rows(st: dict, now: int) -> dict[str, dict]:
    day = _day(now)
    out = {}
    for rule in RULES:
        closed = [p for p in st["positions"] if p["rule"] == rule and not p["open"] and _day(p["exit"]["ts_ms"]) == day]
        c = st["counts"].get(day, {})
        bought = c.get(f"bought_{rule}", 0)
        unfunded = c.get(f"unfunded_{rule}", 0)
        held = [p for p in open_positions(st, rule) if funded(p)]
        eq = equity(st, rule)
        out[rule] = book_row(day, eq, len(held), bought - unfunded, sum(funded(p) for p in closed),
                             sum(funded(p) and p["exit"]["reason"].startswith("rug") for p in closed),
                             sum(p["value"] for p in held), unfunded)
    return out


def book_row(day: str, eq: float, held: int, bought: int, closed: int, rugs: int, value: float,
             unfunded: int) -> dict:
    """One journal row. Counts are the book's funded positions; `unfunded` the buys the
    rule made that day without the cash for them. Exposure is what the funded positions
    are worth over the equity (0 for a book with nothing left)."""
    return {"date": day, "equity": round(eq, 2), "held": held, "bought": bought, "closed": closed, "rugs": rugs,
            "turnover": round((bought + closed) * STAKE_USD / START_EQUITY, 4),
            "exposure": round(value / eq, 4) if eq > 1e-9 else 0.0, "unfunded": unfunded}


def write_journal(rule: str, row: dict) -> None:
    d = book_dir(rule)
    d.mkdir(parents=True, exist_ok=True)
    p = d / "journal.csv"
    rows = []
    if p.exists():
        with p.open(newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
    rows = [r for r in rows if r.get("date") != row["date"]] + [row]
    tmp = p.with_suffix(".csv.tmp")
    with tmp.open("w", newline="", encoding="utf-8") as fh:
        wr = csv.DictWriter(fh, fieldnames=list(row))
        wr.writeheader()
        for r in rows:
            wr.writerow({k: r.get(k, "") for k in row})
    tmp.replace(p)
    sf = d / "state.json"
    if not sf.exists():
        sf.write_text(json.dumps({"variant": f"EXPERIMENT, paper only · pump.fun {rule}: {RULES[rule]['label']}",
                                  "started": datetime.now(timezone.utc).isoformat(timespec="seconds")}, indent=1))


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def replay(ledger: list[dict], marks: list[dict], now: int) -> dict:
    """The books from the ledger (every paper fill) under the rules as they are now: one buy
    per token and rule, and a buy without the stake in cash is unfunded (it moves no cash).
    The open positions are valued at their last hourly mark (marks.csv), else at the stake.

    Returns {"rows": {rule: [journal row per UTC day]}, "cash": {rule: cash},
    "funded": {(rule, mint): bool} for every token kept, "dupes": {rule: buys dropped}}."""
    # Fills before the marks of the same run (a mark row is written after the run's fills).
    events = [(int(r["ts_ms"]), 0, r) for r in ledger] + [(int(m["ts_ms"]), 1, m) for m in marks]
    events.sort(key=lambda e: (e[0], e[1]))

    def next_day(d: str) -> str:
        return _day(int(datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000) + DAY_MS)
    cash = {r: START_EQUITY for r in RULES}
    opened: dict[tuple[str, str], dict] = {}     # (rule, mint) -> {"funded", "value"}
    kept: dict[tuple[str, str], bool] = {}
    dupes = {r: 0 for r in RULES}
    rows: dict[str, list[dict]] = {r: [] for r in RULES}
    day_counts = {r: {"bought": 0, "unfunded": 0, "closed": 0, "rugs": 0} for r in RULES}

    def close_day(day: str) -> None:
        for rule in RULES:
            held = [o for (r, _), o in opened.items() if r == rule and o["funded"]]
            value = sum(o["value"] for o in held)
            c = day_counts[rule]
            rows[rule].append(book_row(day, cash[rule] + value, len(held), c["bought"], c["closed"], c["rugs"],
                                       value, c["unfunded"]))
            day_counts[rule] = {"bought": 0, "unfunded": 0, "closed": 0, "rugs": 0}

    day = _day(events[0][0]) if events else _day(now)
    for ts, kind, r in events:
        while _day(ts) > day:
            close_day(day)
            day = next_day(day)
        rule, mint = r.get("rule"), r.get("mint")
        if rule not in RULES:
            continue
        key = (rule, mint)
        if kind == 1:
            if key in opened:
                opened[key]["value"] = float(r["value"])
            continue
        usd = float(r["usd"])
        if r["side"] == "buy":
            if key in kept:
                dupes[rule] += 1
                continue
            ok = cash[rule] >= STAKE_USD - 1e-9
            if ok:
                cash[rule] -= STAKE_USD
                day_counts[rule]["bought"] += 1
            else:
                day_counts[rule]["unfunded"] += 1
            kept[key] = ok
            opened[key] = {"funded": ok, "value": STAKE_USD}
        elif key in opened:
            o = opened.pop(key)
            if o["funded"]:
                cash[rule] += usd
                day_counts[rule]["closed"] += 1
                day_counts[rule]["rugs"] += str(r.get("reason", "")).startswith("rug")
    while day <= _day(now):
        close_day(day)
        day = next_day(day)
    return {"rows": rows, "cash": cash, "funded": kept, "dupes": dupes}


def rebuild_state(st: dict, res: dict) -> dict:
    """The state brought in line with a replay: a second buy of a token by the same rule is
    dropped, every position kept gets its funding, every book its replayed cash."""
    seen: set[tuple[str, str]] = set()
    keep = []
    for p in sorted(st["positions"], key=lambda p: p["entry_ms"]):
        key = (p["rule"], p["mint"])
        if key in seen:
            continue
        seen.add(key)
        p["funded"] = res["funded"].get(key, True)
        keep.append(p)
    st["positions"] = keep
    for rule, cash in res["cash"].items():
        st["books"][rule]["cash"] = cash
    for rule, rows in res["rows"].items():
        for row in rows:
            c = st["counts"].get(row["date"])
            if c is not None:
                c[f"bought_{rule}"] = row["bought"] + row["unfunded"]
                c[f"unfunded_{rule}"] = row["unfunded"]
    return st


def rebuild(now: int, dry: bool = False) -> dict:
    """--rebuild: replay the ledger and rewrite the journals and the state."""
    d = paper_dir()
    res = replay(read_csv(d / "ledger.csv"), read_csv(d / "marks.csv"), now)
    st = load_state()
    if st is not None:
        rebuild_state(st, res)
    for rule, rows in res["rows"].items():
        print(f"{rule}: {len(rows)} days, equity {rows[-1]['equity'] if rows else START_EQUITY:,.2f}, "
              f"{res['dupes'][rule]} repeated buys of a token dropped, "
              f"{sum(r['unfunded'] for r in rows)} buys without the cash for them")
        if dry or not rows:
            continue
        p = book_dir(rule) / "journal.csv"
        tmp = p.with_suffix(".csv.tmp")
        tmp.parent.mkdir(parents=True, exist_ok=True)
        with tmp.open("w", newline="", encoding="utf-8") as fh:
            wr = csv.DictWriter(fh, fieldnames=list(rows[0]))
            wr.writeheader()
            wr.writerows(rows)
        tmp.replace(p)
    if st is not None and not dry:
        save_state(st)
    return res


def save_state(st: dict) -> None:
    d = paper_dir()
    d.mkdir(parents=True, exist_ok=True)
    # Closed positions older than 60 days leave the state; the ledger keeps them.
    cut = st["coverage"].get("last_run_ms", 0) - 60 * DAY_MS
    st["positions"] = [p for p in st["positions"] if p["open"] or p["exit"]["ts_ms"] >= cut]
    tmp = d / "state.json.tmp"
    tmp.write_text(json.dumps(st, indent=1))
    tmp.replace(d / "state.json")


def load_state() -> dict | None:
    try:
        return json.loads((paper_dir() / "state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------- alerts

def pct(x: float) -> str:
    return f"{x * 100:+.0f} %"


def alert_cards(closed: list[dict], st: dict, now: int, lang: str = "en") -> list:
    """Big paper winners at once; big losers (rugs too) together, at most once an hour.
    Every word from the message catalog (lab.ops.i18n), English or German."""
    from ..ops import i18n, notify
    t = i18n.t
    cards = []
    for p in closed:
        e = p["exit"]
        if e["ret"] >= WIN_ALERT:
            cards.append(notify.Card(
                "🚀", t("pf_winner_title", lang, name=p.get("name") or p["mint"][:8],
                        ret=i18n.frac_pct(e["ret"], 0, lang)),
                t("pf_winner_summary", lang, rule=p["rule"], stake=i18n.money(p["stake"], 0, lang),
                  usd=i18n.money(e["usd"], 0, lang), hours=i18n.num(e["hours"], 1, lang), why=reason_text(e, lang)),
                [notify.Line(t("pf_caveat", lang))], footer=t("pf_footer", lang)))
    losers = [p for p in closed if p["exit"]["ret"] <= LOSS_ALERT]
    if losers and now - st.get("last_loss_alert_ms", 0) >= HOUR_MS:
        st["last_loss_alert_ms"] = now
        rows = [[(p.get("name") or p["mint"][:8])[:18], p["rule"], i18n.frac_pct(p["exit"]["ret"], 0, lang),
                 reason_text(p["exit"], lang)[:24]] for p in losers[:10]]
        cards.append(notify.Card(
            "🪦", t("pf_losers_title", lang, n=len(losers)), t("pf_losers_summary", lang),
            [notify.Table([t("pf_col_token", lang), t("pf_col_rule", lang), t("pf_col_return", lang),
                           t("pf_col_why", lang)], rows, more=max(0, len(losers) - 10)),
             notify.Line(t("pf_caveat", lang))], footer=t("pf_footer", lang)))
    return cards


# ---------------------------------------------------------------- daily report

def summary(st: dict, now: int, ledger_rows: list[dict] | None = None) -> dict:
    """Per rule over every closed position in the state (funded or not: the rule's record per
    token): count, rugs, median and mean return per trade, hit rate, the best and worst; the
    book's equity and return (funded positions only); plus yesterday's counts."""
    rules = {}
    for rule in RULES:
        closed = [p for p in st["positions"] if p["rule"] == rule and not p["open"]]
        rets = sorted(p["exit"]["ret"] for p in closed)
        n = len(rets)
        rules[rule] = {
            "label": RULES[rule]["label"], "equity": round(equity(st, rule), 2),
            "return_pct": round((equity(st, rule) / START_EQUITY - 1) * 100, 2),
            "open": sum(funded(p) for p in open_positions(st, rule)),
            "unfunded_open": sum(not funded(p) for p in open_positions(st, rule)),
            "funded_closed": sum(funded(p) for p in closed), "closed": n,
            "rugs": sum(p["exit"]["reason"].startswith("rug") for p in closed),
            "median_ret": rets[n // 2] if n else None, "mean_ret": sum(rets) / n if n else None,
            "hit_rate": sum(r > 0 for r in rets) / n if n else None,
            "zero_share": sum(r <= -0.9 for r in rets) / n if n else None,
            "best": max(closed, key=lambda p: p["exit"]["ret"], default=None),
            "worst": min(closed, key=lambda p: p["exit"]["ret"], default=None),
        }
    y = _day(now - DAY_MS)
    return {"rules": rules, "yesterday": st["counts"].get(y, {}), "day": y}


def report(st: dict, now: int) -> tuple[dict, str]:
    s = summary(st, now)
    y = s["yesterday"]
    stale = now - (st.get("coverage") or {}).get("last_run_ms", 0) > 2 * HOUR_MS
    status = "bad" if stale else "watch"
    launches, grads = y.get("launches", 0), y.get("graduations", 0)
    parts = [f"Yesterday the watcher saw {launches} new pump.fun tokens and {grads} graduations"
             + (f" ({grads / launches * 100:.1f} %)" if launches else "")]
    for rule, r in s["rules"].items():
        if r["closed"]:
            parts.append(f"{rule}: {r['closed']} closed, {r['rugs']} rugs, median {pct(r['median_ret'])} and mean "
                         f"{pct(r['mean_ret'])} per trade, book {r['return_pct']:+.1f} %")
        else:
            parts.append(f"{rule}: nothing closed yet")
    headline = ("Paper only. " if not stale else "The watcher has not run for over 2 hours. ") + "; ".join(parts) + "."
    items = []
    for rule, r in s["rules"].items():
        items.append({"label": f"pump.fun {rule}", "value": f"{r['return_pct']:+.1f} %",
                      "status": "bad" if r["return_pct"] < -20 else "watch",
                      "detail": f"{r['label']}. Book: equity ${r['equity']:,.0f} from ${START_EQUITY:,.0f}, "
                                f"{r['open']} open. Per trade: {r['closed']} closed, {r['rugs']} rugs"
                                + (f", mean {pct(r['mean_ret'])}, hit rate {r['hit_rate'] * 100:.0f} %, "
                                   f"{r['zero_share'] * 100:.0f} % at -90 % or worse" if r["closed"] else "")
                                + (f"; {r['unfunded_open']} open without the book's money (its cash is under the "
                                   f"${STAKE_USD:,.0f} stake)" if r["unfunded_open"] else ""),
                      "link": "study:experiments", "importance": 30})
        for tag, p in (("best", r["best"]), ("worst", r["worst"])):
            if p:
                items.append({"label": f"{rule} {tag}: {p.get('name') or p['mint'][:8]}", "value": pct(p["exit"]["ret"]),
                              "status": "ok" if p["exit"]["ret"] > 0 else "bad",
                              "detail": f"{p['exit']['reason']} after {p['exit']['hours']:.1f} h", "importance": 10})
    cov = y.get("coverage_gaps", 0)
    items.append({"label": "Coverage", "value": f"{y.get('runs', 0)} runs",
                  "status": "watch" if cov else "ok",
                  "detail": f"{cov} runs did not reach back to the run before (graduations in between may be missed)",
                  "importance": 5})
    from .. import report as rep
    data = {**rep.feed_header("pump.fun paper watcher", status, headline, items, updated_ms=now),
            "caveat": CAVEAT, "summary": json.loads(json.dumps(s, default=str)), "rules": RULES}
    md = [f"# pump.fun paper watcher ({_day(now)})", "", CAVEAT, "", headline, "",
          "Book: equity (cash plus the funded positions at their marks) against $10,000. Per trade: every "
          "token the rule bought, funded or not, each against its own $100 stake.", "",
          "| rule | book equity | book return | open | closed trades | rugs | median per trade | mean per trade "
          "| hit rate |", "|---|---|---|---|---|---|---|---|---|"]
    for rule, r in s["rules"].items():
        md.append(f"| {rule} | ${r['equity']:,.0f} | {r['return_pct']:+.1f} % | {r['open']} | {r['closed']} | {r['rugs']} | "
                  f"{pct(r['median_ret'])} | {pct(r['mean_ret'])} | {(r['hit_rate'] * 100):.0f} % |" if r["closed"] else
                  f"| {rule} | ${r['equity']:,.0f} | {r['return_pct']:+.1f} % | {r['open']} | 0 | 0 | n/a | n/a | n/a |")
    return data, "\n".join(md) + "\n"


def report_card(data: dict, lang: str = "en"):
    """The daily card, in the message language (the report itself stays English)."""
    from ..ops import i18n, notify
    t = i18n.t
    s = data["summary"]
    y = s.get("yesterday") or {}
    lines = []
    rows = []
    for rule, r in s["rules"].items():
        ret = i18n.signed_pct(r["return_pct"], 1, lang)
        rows.append([rule, ret])
        lines.append(t("pf_rule_line", lang, rule=rule, closed=r["closed"], rugs=r["rugs"], ret=ret) if r["closed"]
                     else t("pf_rule_none", lang, rule=rule))
    summary = t("pf_report_summary", lang, launches=y.get("launches", 0), grads=y.get("graduations", 0),
                rules="; ".join(lines) + ".")
    return notify.Card("🎰", t("pf_report_title", lang), summary,
                       [notify.Table([t("pf_col_rule", lang), t("pf_col_book", lang)], rows),
                        notify.Line(t("pf_caveat", lang))], footer=t("pf_footer", lang))


# ---------------------------------------------------------------- main

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--rebuild", action="store_true")
    a = ap.parse_args(argv)
    from ..ops import notify
    now = int(time.time() * 1000)
    if a.rebuild:
        rebuild(now, dry=a.dry_run)
        return 0
    st = load_state() or new_state()
    if a.report:
        data, md = report(st, now)
        if a.dry_run:
            print(md)
            return 0
        from .. import report as rep
        rep.write(NAME, md, data)
        notify.send("trending", [report_card(data, notify.alert_lang())], now=now)
        return 0
    res = run(Http(), now, st)
    if a.dry_run:
        print(json.dumps({"seen": res["seen"], "launches": res["launches"],
                          "graduations": [g.get("name") for g in res["graduations"]],
                          "bought": [(r, g.get("name")) for r, g in res["bought"]],
                          "skipped": [(r, g.get("name"), w) for r, g, w in res["skipped"]][:20],
                          "closed": [(p["rule"], p.get("name"), p["exit"]) for p in res["closed"]],
                          "coverage": res["coverage"]}, indent=1, default=str))
        return 0
    st = res["state"]
    _append_csv(paper_dir() / "ledger.csv", res["ledger"])
    _append_csv(paper_dir() / "marks.csv", hourly_marks(st, now))
    day = _day(now)
    cand = [{k: g.get(k) for k in ("pool", "mint", "name", "dex", "created_ms", "price_usd", "liq_usd", "fdv_usd", "info")}
            for g in res["graduations"]]
    if cand:
        p = paper_dir() / "candidates" / f"{day}.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as fh:
            for c in cand:
                fh.write(json.dumps(c, default=str) + "\n")
    for rule, row in journal_rows(st, now).items():
        write_journal(rule, row)
    cards = alert_cards(res["closed"], st, now, notify.alert_lang())
    save_state(st)
    if cards:
        notify.send("trending", cards, now=now)
    print(f"{NAME}: {res['seen']} new pools, {res['launches']} launches, {len(res['graduations'])} graduations, "
          f"{len(res['bought'])} paper buys, {len(res['closed'])} closes"
          + (f"; errors: {', '.join(res['coverage']['errors'])}" if res["coverage"]["errors"] else ""))
    return 0 if not res["coverage"]["errors"] or res["seen"] else 1


if __name__ == "__main__":
    sys.exit(main())
