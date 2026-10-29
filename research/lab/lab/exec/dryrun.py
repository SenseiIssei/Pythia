"""L1 (results/exec_dryrun_l1_prereg.md): the orders a 50 EUR Kraken spot account would place for a paper book.
DRY RUN ONLY: no key, no account, no order sent. The only requests are public GETs to api.kraken.com/0/public/.

    python -m lab.exec.dryrun            write reports/exec_dryrun/latest.md and .json
    python -m lab.exec.dryrun --print    print the report, write no report (the caches and the registry still)

Books: S1's and S2's small-account books, the tsmom books and L1's on-chain tsmom1 (BOOKS); their targets are the
`weights` column of <data>/paper/<book>/journal.csv. The venue: Kraken's AssetPairs (both asset classes) and Ticker,
cached in <data>/exec/kraken_pairs.json, daily closes (OHLC, 1440) in <data>/exec/kraken_ohlc.json, refreshed after
CACHE_H hours (the stale cache when Kraken does not answer). A coin trades on its EUR pair, else on its USD pair
plus the EUR to USD conversion (FX_FEE). The fee: the pair's AssetPairs tiers when Kraken fills them (empty on
2026-10-28), else the published spot schedule (FEE_SCHEDULE), the tier by the account's own 30-day USD volume;
market orders (taker), the maker fee next to it.

One order (`size`): units = EUR / price rounded down to lot_decimals (a sell at most what is held, a buy at most
the cash after its fee), the limit price rounded to pair_decimals; not placed when it rounds to 0, under ordermin
or under costmin. `orders`: today's targets bought from a fresh 50 EUR wallet at the ask. `replay`: the journal's
last WINDOW_DAYS days from a 50 EUR wallet, an order for every coin whose target changed, at the daily close.
Per book: orders a 50 EUR account could not place, the weight left off target, the return gap held minus target
(a year), fees as a share of the wallet a month. One counted trial per book in R5's registry.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from .. import metrics, report
from ..data import ROOT, WRITE_ROOT
from . import kraken_fee as kf

NAME = "exec_dryrun"
PREREG = "results/exec_dryrun_l1_prereg.md"
API = "https://api.kraken.com/0/public"
WALLET_EUR = 50.0
WINDOW_DAYS = 30
CACHE_H = 20
FX_FEE = kf.kraken_fee(stable=True)  # Kraken's published stablecoin and FX pairs, 0 USD tier
EPS = 1e-9
BASES = {"XBT": "BTC", "XDG": "DOGE"}
ALIAS = {"GOLD": "PAXG", "SPY": "SPYx"}
# Kraken's published spot schedule (lab.exec.kraken_fee, the lab's one source). Used while AssetPairs' own `fees`
# lists are empty.
FEE_SCHEDULE = kf.FEE_SCHEDULE
BOOKS = {"small50_tsmom1": "S1", "small100_breakout_sol3": "S1", "small40_spy_trend": "S2",
         "small40_vol_target": "S2", "tsmom": "tsmom", "tsmom_regime": "tsmom", "tsmom_top20": "tsmom",
         "tsmom_tranches": "tsmom", "tsmom_tranches_lowkr": "tsmom", "tsmom_tranches_lowmax": "tsmom",
         "onchain_longterm": "L1"}
WHY = ("no pair", "no price", "rounds to 0", "below ordermin", "below costmin")


def trials() -> list[dict]:
    return [{"id": f"small:l1:exec_dryrun_{b}", "family": "small", "n": 1, "sharpe": None, "source": PREREG}
            for b in BOOKS]


# ---------------------------------------------------------------- the venue (public, read only)

def _get(path: str, timeout: float = 20.0) -> dict:
    """One public GET; Kraken's `result`. No key, no signature, no body."""
    req = urllib.request.Request(f"{API}/{path}", headers={"User-Agent": "pythia-lab"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.loads(r.read())
    if d.get("error"):
        raise ValueError(f"kraken {path}: {d['error']}")
    return d["result"]


def _read(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write(p: Path, data) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, p)


def load_venue(path: Path, now_s: float, get=_get, log=print) -> dict:
    """{"fetched", "fetched_s", "pairs", "ticker", "stale"}: the cache when younger than CACHE_H, else Kraken's
    AssetPairs and Ticker of both asset classes (the stale cache when Kraken does not answer)."""
    old = _read(path)
    if old and now_s - float(old.get("fetched_s") or 0) < CACHE_H * 3600:
        return {**old, "stale": False}
    try:
        pairs = {**get("AssetPairs"), **get("AssetPairs?aclass_base=tokenized_asset")}
        ticker = {**get("Ticker"), **get("Ticker?asset_class=tokenized_asset")}
    except (OSError, ValueError) as e:
        if not old:
            raise
        log(f"exec_dryrun: Kraken did not answer ({e}), the cache of {old.get('fetched')} is used")
        return {**old, "stale": True}
    v = {"fetched": datetime.fromtimestamp(now_s, timezone.utc).isoformat(timespec="seconds"), "fetched_s": now_s,
         "pairs": pairs, "ticker": ticker}
    _write(path, v)
    return {**v, "stale": False}


def market(pairs: dict) -> dict:
    """coin -> its pair's rules: the online EUR pair, else the USD pair; a key equal to its altname first."""
    out: dict[str, dict] = {}
    for key, p in sorted(pairs.items(), key=lambda kv: (kv[0] != kv[1].get("altname"), kv[0])):
        ws = str(p.get("wsname") or "")
        if "/" not in ws or p.get("status", "online") != "online":
            continue
        b, q = ws.split("/", 1)
        if q not in ("EUR", "USD"):
            continue
        coin = BASES.get(b, b)
        if coin in out and (out[coin]["quote"] == "EUR" or q == "USD"):
            continue
        out[coin] = {"pair": ws, "key": key, "quote": q, "aclass": p.get("aclass_base") or "currency",
                     "ordermin": float(p.get("ordermin") or 0), "costmin": float(p.get("costmin") or 0),
                     "lot_decimals": int(p.get("lot_decimals", 8)), "pair_decimals": int(p.get("pair_decimals", 8)),
                     "fees": p.get("fees") or [], "fees_maker": p.get("fees_maker") or []}
    return out


def rule_of(mk: dict, coin: str) -> dict | None:
    return mk.get(ALIAS.get(coin, coin))


def quote(ticker: dict, rule: dict | None) -> tuple[float, float]:
    """(bid, ask) of the pair, (nan, nan) when the ticker lacks it."""
    t = (ticker.get(rule["key"]) if rule else None) or {}
    try:
        return float(t["b"][0]), float(t["a"][0])
    except (KeyError, IndexError, TypeError, ValueError):
        return math.nan, math.nan


def eurusd(mk: dict, ticker: dict) -> float:
    b, a = quote(ticker, mk.get("EUR"))
    return (a + b) / 2 if a > 0 and b > 0 else math.nan


def fee_rate(rule: dict, vol_usd: float = 0.0, maker: bool = False) -> float:
    """The fee as a share of the order: the pair's tiers from AssetPairs when Kraken fills them, else the published
    schedule (lab.exec.kraken_fee); the last tier whose 30-day USD volume the account reached; plus the FX fee on
    a USD pair."""
    fx = kf.kraken_fee(vol_usd, maker, stable=True) if rule["quote"] == "USD" else 0.0
    return kf.kraken_fee(vol_usd, maker, tiers=rule.get("fees_maker" if maker else "fees")) + fx


# ---------------------------------------------------------------- one order

def size(coin: str, rule: dict | None, eur: float, price: float, fx: float, held: float = math.inf,
         cash: float = math.inf, vol_usd: float = 0.0) -> dict:
    """One order of `eur` (above 0 a buy, below a sell) at `price` in the pair's quote, `fx` EUR per quote unit:
    units before and after rounding down to the lot, the limit price on the pair's decimals, placed or why not,
    fee (taker) and the maker fee in EUR. A sell at most `held` units, a buy at most the cash after its fee."""
    buy = eur > 0
    o = {"coin": coin, "pair": rule["pair"] if rule else None, "side": "buy" if buy else "sell", "eur": eur,
         "units_raw": None, "units": 0.0, "price": None, "ordermin": None, "cost_eur": 0.0, "fee_eur": 0.0,
         "fee_maker_eur": 0.0, "cut": False, "placed": False, "why": ""}
    if rule is None:
        o["why"] = "no pair"
        return o
    o["ordermin"] = rule["ordermin"]
    if not (price > 0 and fx > 0):
        o["why"] = "no price"
        return o
    px = round(price, rule["pair_decimals"])
    taker, maker = fee_rate(rule, vol_usd), fee_rate(rule, vol_usd, True)
    raw = abs(eur) / (px * fx)
    cap = cash / (px * fx * (1 + taker)) if buy else held
    q = 10 ** rule["lot_decimals"]
    units = math.floor(min(raw, cap) * q + 1e-6) / q
    o.update(units_raw=raw, units=units, price=px, cut=bool(cap < raw - EPS))
    if units <= 0:
        o["why"] = "rounds to 0"
    elif units < rule["ordermin"] - EPS:
        o["why"] = "below ordermin"
    elif units * px < rule["costmin"] - EPS:
        o["why"] = "below costmin"
    else:
        cost = units * px * fx
        o.update(placed=True, cost_eur=cost, fee_eur=cost * taker, fee_maker_eur=cost * maker)
    return o


def _fx(rule: dict | None, usd: float) -> float:
    return 1.0 if rule is None or rule["quote"] == "EUR" else 1 / usd if usd > 0 else math.nan


def orders(weights: dict, mk: dict, ticker: dict, usd: float, wallet: float = WALLET_EUR) -> list[dict]:
    """Today's targets bought from a fresh wallet, all cash, at the ask, the biggest first; drift = the weight
    the order leaves of the wallet minus the target."""
    out, cash = [], wallet
    for coin, w in sorted(weights.items(), key=lambda kv: -kv[1]):
        if not w > 0:
            continue
        rule = rule_of(mk, coin)
        o = size(coin, rule, w * wallet, quote(ticker, rule)[1], _fx(rule, usd), cash=cash)
        if o["placed"]:
            cash -= o["cost_eur"] + o["fee_eur"]
        o.update(target=w, drift=o["cost_eur"] / wallet - w)
        out.append(o)
    return out


# ---------------------------------------------------------------- the replay

def replay(days: list[tuple[str, dict]], mk: dict, closes: dict, usd: dict, usd_now: float = math.nan,
           wallet: float = WALLET_EUR) -> dict:
    """The journal's days [(date, {coin: target})] from a `wallet` of cash: each day an order for every coin whose
    target changed (sells first), traded to target at the close of the bar ending at the day's 00:00 UTC
    (closes: pair key -> {date: close}; usd: date -> EUR/USD, else usd_now). An order with nothing to trade is
    none. The weight off target after each day, the next day's return gap held minus target, fees."""
    cash, held, prev, last_px = wallet, {}, {}, {}
    log, out, offs, gaps, e_prev, px_prev = [], [], [], [], {}, {}
    for day, w in days:
        ex = usd.get(day) or usd_now
        px = {}
        for c in set(w) | set(held) | set(prev):
            r = rule_of(mk, c)
            p = (closes.get(r["key"]) or {}).get(day) if r else None
            p = p * _fx(r, ex) if p else last_px.get(c)
            if p and p > 0:
                px[c] = last_px[c] = p
        V = cash + sum(u * px.get(c, 0.0) for c, u in held.items())
        d0 = datetime.strptime(day, "%Y-%m-%d")
        vol = sum(u for d, u in log if (d0 - datetime.strptime(d, "%Y-%m-%d")).days < 30)
        changed = [c for c in set(w) | set(prev) if abs(w.get(c, 0.0) - prev.get(c, 0.0)) > EPS]
        todo = []
        for c in changed:
            eur = w.get(c, 0.0) * V - held.get(c, 0.0) * px.get(c, 0.0)
            if abs(eur) > EPS and (eur > 0 or held.get(c, 0.0) > 0):
                todo.append((eur > 0, c, eur))
        for _, c, eur in sorted(todo):
            r = rule_of(mk, c)
            fx = _fx(r, ex)
            o = size(c, r, eur, px[c] / fx if c in px and fx > 0 else math.nan, fx, held.get(c, 0.0), cash, vol)
            if o["placed"]:
                sgn = 1 if o["side"] == "buy" else -1
                held[c] = held.get(c, 0.0) + sgn * o["units"]
                cash += -sgn * o["cost_eur"] - o["fee_eur"]
                log.append((day, o["cost_eur"] / ex if ex > 0 else 0.0))
            V = cash + sum(u * px.get(k, 0.0) for k, u in held.items())
            o.update(day=day, target=w.get(c, 0.0), drift=(held.get(c, 0.0) * px.get(c, 0.0) / V if V > 0 else 0.0)
                     - w.get(c, 0.0))
            out.append(o)
        if e_prev:
            gaps.append(sum(e * (px[c] / px_prev[c] - 1) for c, e in e_prev.items()
                            if c in px and px_prev.get(c)))
        e_prev = {c: (held.get(c, 0.0) * px.get(c, 0.0) / V if V > 0 else 0.0) - w.get(c, 0.0)
                  for c in set(w) | set(held)}
        offs.append(sum(abs(e) for e in e_prev.values()))
        px_prev, prev = dict(px), dict(w)
    n_days = ((datetime.strptime(days[-1][0], "%Y-%m-%d") - datetime.strptime(days[0][0], "%Y-%m-%d")).days + 1
              if days else 0)
    why = {k: sum(1 for o in out if o["why"] == k) for k in WHY}
    fees, fees_m = sum(o["fee_eur"] for o in out), sum(o["fee_maker_eur"] for o in out)
    g = np.array(gaps, dtype=float)
    return {"days": len(days), "span_days": n_days, "orders": len(out), "placed": sum(o["placed"] for o in out),
            "not_placed": len(out) - sum(o["placed"] for o in out), "why": why,
            "share_not_placed": (len(out) - sum(o["placed"] for o in out)) / len(out) if out else None,
            "off_mean": float(np.mean(offs)) if offs else None,
            "te_annual_pct": float(g.std(ddof=1) * math.sqrt(365) * 100) if len(g) > 1 else None,
            "gap_annual_pct": float(g.mean() * 365 * 100) if len(g) else None,
            "fees_eur": fees, "fees_month_pct": fees / n_days * 30 / wallet * 100 if n_days else None,
            "fees_maker_month_pct": fees_m / n_days * 30 / wallet * 100 if n_days else None,
            "wallet_end_eur": cash + sum(u * last_px.get(c, 0.0) for c, u in held.items()), "list": out}


def journal_days(path: Path, window: int = WINDOW_DAYS) -> list[tuple[str, dict]]:
    """[(date, {coin: target})] of the journal's last `window` days, one row a date (the last)."""
    if not path.exists():
        return []
    by: dict[str, dict] = {}
    with path.open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                w = json.loads(r.get("weights") or "{}")
            except ValueError:
                continue
            if r.get("date") and isinstance(w, dict):
                by[r["date"]] = {str(k).removesuffix("USDT"): float(v) for k, v in w.items() if v is not None}
    if not by:
        return []
    last = datetime.strptime(max(by), "%Y-%m-%d")
    lo = (last - timedelta(days=window - 1)).strftime("%Y-%m-%d")
    return [(d, by[d]) for d in sorted(by) if d >= lo]


def load_closes(path: Path, rules: list[dict], now_s: float, get=_get, pause: float = 1.0, log=print) -> dict:
    """pair key -> {date the bar closes: close} from Kraken's public daily OHLC, the cache when younger than
    CACHE_H; only closed bars."""
    cache = _read(path) or {}
    out, dirty = {}, False
    for r in {r["key"]: r for r in rules}.values():
        c = cache.get(r["key"]) or {}
        if now_s - float(c.get("fetched_s") or 0) >= CACHE_H * 3600:
            q = f"OHLC?pair={r['key']}&interval=1440" + ("&asset_class=tokenized_asset"
                                                          if r["aclass"] == "tokenized_asset" else "")
            try:
                res = get(q)
                rows = next(v for k, v in res.items() if k != "last")
                c = {"fetched_s": now_s, "closes": {
                    datetime.fromtimestamp(int(b[0]) + 86400, timezone.utc).strftime("%Y-%m-%d"): float(b[4])
                    for b in rows if int(b[0]) + 86400 <= now_s}}
                cache[r["key"]], dirty = c, True
            except (OSError, ValueError, StopIteration, IndexError, TypeError) as e:
                log(f"exec_dryrun: no daily closes for {r['pair']} ({e})")
            time.sleep(pause)
        out[r["key"]] = c.get("closes") or {}
    if dirty:
        _write(path, cache)
    return out


# ---------------------------------------------------------------- the report

def _pc(x, d=1) -> str:
    return "n/a" if x is None else f"{x:.{d}f} %"


def _g(x) -> str:
    return "-" if x is None else f"{x:.8g}"


def markdown(res: dict) -> str:
    v = res["venue"]
    md = [f"# L1: 50 EUR on Kraken spot, dry run ({res['date']})", "",
          f"Pre-registered in `{PREREG}`. No key, no account, no order sent. Kraken's public answers of "
          f"{v['fetched']}{' (stale: Kraken did not answer)' if v['stale'] else ''}; fee: {v['fee_source']}, "
          f"taker {v['taker_pct']:.2f} %, maker {v['maker_pct']:.2f} % at the account's tier; EUR/USD "
          f"{v['eurusd']:.4f}. A wallet of {res['wallet']:.0f} EUR for every book.", "",
          "## Per book, the replay", "",
          f"The journal's last {WINDOW_DAYS} days: an order for every coin whose target changed, at Kraken's daily "
          "close. Off target: the mean of the summed |held - target| weights after each day. Gap: held minus target "
          "on the next day's closes, a year (fees apart). Fees: a share of the wallet a month, the first day's "
          "buy-in included (on a few days it dominates).", "",
          "| book | study | days | orders | not placed | why | off target | tracking error | gap | fees taker | "
          "fees maker |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for b in res["books"]:
        r = b["replay"]
        if not r["days"]:
            md.append(f"| {b['book']} | {b['study']} | 0 | no journal | | | | | | | |")
            continue
        why = ", ".join(f"{k} {n}" for k, n in r["why"].items() if n) or "-"
        md.append(f"| {b['book']} | {b['study']} | {r['days']} | {r['orders']} | {r['not_placed']} "
                  f"({_pc(None if r['share_not_placed'] is None else r['share_not_placed'] * 100, 0)}) | {why} | "
                  f"{_pc(None if r['off_mean'] is None else r['off_mean'] * 100)} | {_pc(r['te_annual_pct'])} | "
                  f"{_pc(r['gap_annual_pct'])} | {_pc(r['fees_month_pct'], 2)} | {_pc(r['fees_maker_month_pct'], 2)} |")
    md += ["", "## Today's orders from a fresh wallet", "",
           "The latest journal row's targets bought at the ask; units before and after rounding down to the lot.", ""]
    for b in res["books"]:
        md.append(f"**{b['book']}** ({b['date'] or 'no journal'}): " + (
            "no target above 0." if not b["orders"] else ""))
        if b["orders"]:
            md += ["", "| coin | pair | target | EUR | units | rounded | ordermin | limit | placed | fee EUR | drift |",
                   "|---|---|---|---|---|---|---|---|---|---|---|"]
            for o in b["orders"]:
                md.append(f"| {o['coin']} | {o['pair'] or '-'} | {o['target'] * 100:.2f} % | {o['eur']:.2f} | "
                          f"{_g(o['units_raw'])} | {_g(o['units'])} | {_g(o['ordermin'])} | {_g(o['price'])} | "
                          f"{'yes' if o['placed'] else o['why']} | {o['fee_eur']:.4f} | {o['drift'] * 100:+.2f} % |")
        md.append("")
    return "\n".join(md) + "\n"


def run(root: Path = ROOT, write_root: Path = WRITE_ROOT, now_s: float | None = None, get=_get, pause: float = 1.0,
        wallet: float = WALLET_EUR, register: bool = True, log=print) -> dict:
    if register:
        metrics.register(trials())                            # before any number exists
    now_s = time.time() if now_s is None else now_s
    cache = write_root / "exec"
    v = load_venue(cache / "kraken_pairs.json", now_s, get, log)
    mk = market(v["pairs"])
    usd_now = eurusd(mk, v["ticker"])
    days = {b: journal_days(root / "paper" / b / "journal.csv") for b in BOOKS}
    coins = {c for d in days.values() for _, w in d for c in w}
    rules = [r for r in (rule_of(mk, c) for c in sorted(coins)) if r] + ([mk["EUR"]] if "EUR" in mk else [])
    closes = load_closes(cache / "kraken_ohlc.json", rules, now_s, get, pause, log)
    usd = closes.get(mk["EUR"]["key"], {}) if "EUR" in mk else {}
    books = []
    for b, study in BOOKS.items():
        d = days[b]
        books.append({"book": b, "study": study, "date": d[-1][0] if d else None,
                      "orders": orders(d[-1][1], mk, v["ticker"], usd_now, wallet) if d else [],
                      "replay": replay(d, mk, closes, usd, usd_now, wallet)})
    t0 = {"quote": "EUR", "fees": [], "fees_maker": []}
    some = next((r for r in mk.values() if r["quote"] == "EUR"), t0)
    fee_source = ("AssetPairs' fee tiers" if some["fees"] else
                  f"{kf.source()} (AssetPairs' fee lists are empty)")
    return {"date": datetime.fromtimestamp(now_s, timezone.utc).strftime("%Y-%m-%d"), "wallet": wallet,
            "venue": {"fetched": v.get("fetched"), "stale": v["stale"], "eurusd": usd_now, "fee_source": fee_source,
                      "taker_pct": fee_rate({**some, "quote": "EUR"}) * 100,
                      "maker_pct": fee_rate({**some, "quote": "EUR"}, maker=True) * 100, "pairs": len(mk)},
            "books": books}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="lab.exec.dryrun", description=__doc__.split("\n")[0])
    ap.add_argument("--print", action="store_true", help="print the report, write no report")
    ap.add_argument("--wallet", type=float, default=WALLET_EUR)
    a = ap.parse_args(sys.argv[1:] if argv is None else argv)
    res = run(wallet=a.wallet)
    md = markdown(res)
    if a.print:
        print(md)
    else:
        report.write(NAME, md, res)
    return 0


if __name__ == "__main__":
    sys.exit(main())
