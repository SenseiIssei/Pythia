"""G1 (results/pumpfun_gap_reconcile_g1_prereg.md): P2's same-coin gap against the live twin, trade by trade. PAPER
ONLY and read only on everything live: reads the live ledger, orders, skips and measured fills, the paper ledger,
failed buys and skips and the recorded stream; changes nothing a live bot, its sizing, a wallet or the engine reads.

    python -m lab.pumpfun_rt.reconcile_g1 [--live DIR] [--paper DIR] [--root DIR] [--out results/...g1.md]
    (loads the paper ledger and the stream days of the live coins: run under flock /run/lock/pythia/heavy.lock)

The sample: live closed trades signalled at or after P1's cut (realistic.FIX_MS) that P2 (selection_p2.compute,
unchanged) pairs with a paper ledger row with a return and that the live twin (live_twin, unchanged, on these trades
only) twins. Per trade three records (live, paper, twin) and paper minus twin split exactly into signal time, entry
latency, entry size, entry price, exit rule, exit time, exit price, stake size, fees and rent and failed buys
(parts()); beside it P - L and L - T, and P2's same-coin part by era. Trade bootstrap bands. Four trials in R5's
registry, family pumpfun, counted only.
"""

from __future__ import annotations

import argparse
import bisect
import collections
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .. import metrics
from . import curve as C
from . import live_twin as LT
from . import realistic as R
from . import selection_p2 as P2

PREREG = "results/pumpfun_gap_reconcile_g1_prereg.md"
OUT = Path(__file__).resolve().parents[2] / "results" / "pumpfun_gap_reconcile_g1.md"
CUT_MS = R.FIX_MS                         # P1's cut: live trades signalled from here
DRAWS, SEED = 2_000, 0
SUM_TOL = 0.5                             # the parts must sum to the total within this many points
PARTS = ("signal", "latency", "size", "entry", "exit_rule", "exit_time", "exit", "stake", "fees", "failed")
PART_NAMES = {"signal": "signal time", "latency": "entry latency", "size": "entry size (curve impact)",
              "entry": "entry price", "exit_rule": "exit rule", "exit_time": "exit time", "exit": "exit price",
              "stake": "stake size (fixed fees)", "fees": "fees and rent", "failed": "failed buys"}
ERAS = ("ideal paper", "realistic, before the cut", "from the cut")
STALE_RULES = ("P_pool0", "P_pool0_wait")  # the pool rules whose paper rows after the cut the stale check reads


def trials() -> list[dict]:
    return [{"id": f"pumpfun:gap_g1:{k}", "family": "pumpfun", "n": 1, "sharpe": None, "source": PREREG}
            for k in ("total", "parts", "identity", "eras")]


def posthoc_trials() -> list[dict]:
    """Added after the first run (the result says so): the stale pool state check on every paper row after the cut."""
    return [{"id": "pumpfun:gap_g1:stale_reads", "family": "pumpfun", "n": 1, "sharpe": None, "source": PREREG}]


def g(e: float, x: float) -> float:
    return x / e - 1


# ---------------------------------------------------------------- the three records

def paper_record(row: dict) -> dict | None:
    """A paper ledger row as the decomposition reads it: the realised exit X (proceeds over tokens; a pool buy spends
    its stake, so tokens = stake / entry_price; the ledger's exit_price is the spot at the close), r = ret - g(E, X)."""
    f = R._f
    e, st, pro, ret = (f(row.get(k)) for k in ("entry_price", "stake_sol", "proceeds_sol", "ret"))
    if ret is None:
        return None
    x = pro * e / st if e and st and pro is not None else None
    return {"signal_ms": f(row.get("signal_ms")), "land_ms": f(row.get("land_ms")),
            "xdec_ms": f(row.get("exit_signal_ms")) or f(row.get("exit_ms")), "exit_ms": f(row.get("exit_ms")),
            "E": e, "X": x, "S": st, "ret": ret, "exit_why": row.get("exit_why") or "",
            "spot_exit": f(row.get("exit_price")), "lat_buy_ms": f(row.get("lat_buy_ms")), "bought": bool(e and x)}


def twin_record(lv: dict, book) -> dict | None:
    """The twin of live trade lv (live_twin's TwinBook) on the record's clock, None without one: bought (E, X from
    its cost, proceeds and tokens), buy failed or no buy (bought False)."""
    tw = book.twin.get(lv["i"])
    if tw is None or tw.get("miss"):
        return None
    off = tw.get("offset") or 0.0
    out = {"offset_ms": off, "signal_ms": lv["signal_ms"] + off, "S": lv["stake_l"] / C.LAMPORTS, "bought": False}
    pid = tw.get("pid")
    d, fl = book.done.get(pid), book.fails.get(pid)
    if d is not None and d["tokens"]:
        e = (d["cost_l"] / C.LAMPORTS) / (d["tokens"] / C.TOKEN_UNIT)
        x = (d["proceeds_l"] / C.LAMPORTS) / (d["tokens"] / C.TOKEN_UNIT)
        return out | {"bought": True, "E": e, "X": x, "land_ms": d["land_ms"], "xdec_ms": d["exit_signal_ms"] or d["at"],
                      "exit_ms": d["at"], "exit_why": d.get("exit_why") or "", "S": (d["stake_l"] or 1) / C.LAMPORTS,
                      "ret": (d["proceeds_l"] - d["cost_l"] - d["fees_l"]) / (d["stake_l"] or 1), "how": "bought"}
    if fl is not None:
        return out | {"ret": -fl["fee_l"] / (fl["stake_l"] or 1), "how": f"buy failed: {fl['why']}"}
    return out | {"ret": 0.0, "how": f"no buy: {tw.get('skip')}"}


def quote_at(pools: dict, mint: str, t: float | None) -> float | None:
    """The pool's effective quote reserve in SOL at the first recorded pool trade of the coin at or after t, else the
    last before; pools: mint -> sorted [(t, quote lamports)]."""
    xs = pools.get(mint) or []
    if not xs or t is None:
        return None
    i = bisect.bisect_left([a for a, _ in xs], t)
    return xs[min(i, len(xs) - 1)][1] / C.LAMPORTS


# ---------------------------------------------------------------- one trade: paper minus twin

def parts(p: dict, t: dict, path: list, q: float | None) -> dict:
    """Paper minus twin of one trade in points (x 100), split exactly (the pre-registration): signal time, entry
    latency, entry size, entry price, exit rule (exit_why differ) or exit time (agree), exit price, stake size and
    fees and rent; a twin that did not buy or a price missing: failed buys. A price of the path missing or 0 leaves
    that move at 1; no quote reserve leaves the size move at 1."""
    out = dict.fromkeys(PARTS, 0.0)
    total = (p["ret"] - t["ret"]) * 100
    if not t["bought"] or not p["bought"]:
        return out | {"failed": total, "total": total}

    def move(a, b):
        ma, mb = LT.m_at(path, a), LT.m_at(path, b)
        return ma / mb if ma and mb and a is not None and b is not None else 1.0
    et, xt, ep, xp = t["E"], t["X"], p["E"], p["X"]
    ea = et * move(p["signal_ms"] + t["land_ms"] - t["signal_ms"], t["land_ms"])
    eb = et * move(p["land_ms"], t["land_ms"])
    ec = eb * ((1 + p["S"] / q) / (1 + t["S"] / q) if q else 1.0)
    out["signal"] = (g(ea, xt) - g(et, xt)) * 100
    out["latency"] = (g(eb, xt) - g(ea, xt)) * 100
    out["size"] = (g(ec, xt) - g(eb, xt)) * 100
    out["entry"] = (g(ep, xt) - g(ec, xt)) * 100
    x1 = xt * move(p["xdec_ms"], t["xdec_ms"])
    out["exit_rule" if p["exit_why"] != t["exit_why"] else "exit_time"] = (g(ep, x1) - g(ep, xt)) * 100
    out["exit"] = (g(ep, xp) - g(ep, x1)) * 100
    rp, rt = p["ret"] - g(ep, xp), t["ret"] - g(et, xt)
    out["stake"] = (rt * t["S"] / p["S"] - rt) * 100
    out["fees"] = (rp - rt * t["S"] / p["S"]) * 100
    return out | {"total": total}


# ---------------------------------------------------------------- the sample

def sample(live: dict, paper: dict, p2: dict, trades: list[dict], books: dict, paths: dict, pools: dict,
           stale_of=None) -> dict:
    """Every live trade at or after CUT_MS: in the sample (three records and the parts) or out with its reason.
    trades: live_twin.live_trades rows of those trades, each with `key`, its index in live['ledger']; stale_of: a
    paper row -> whether it filled on a stale pool state (stale_fill)."""
    pidx: dict[tuple, dict] = {}
    for r in paper.get("ledger") or []:
        if r.get("rule") in P2.RULES:
            k = (r["rule"], r.get("mint"), R._f(r.get("signal_ms")))
            pidx.setdefault(k, r)
    by_key = {x["live_key"]: x for x in p2["signals"] if x.get("live_key") is not None and x["ret"] is not None}
    lo = {(x["mint"], x["t"]): x["why"] for x in p2["live_only"]}
    inn, out = [], []
    for tr in trades:
        lrow = live["ledger"][tr["key"]]
        sig = by_key.get(tr["key"])
        tw = twin_record(tr, books[tr["day"]])
        base = {"rule": tr["rule"], "mint": tr["mint"], "symbol": tr["symbol"], "live_signal_ms": tr["signal_ms"]}
        if sig is None:
            out.append(base | {"why": "no P2 paper row: " + lo.get((tr["mint"], tr["signal_ms"]), "unmatched")})
            continue
        if tw is None:
            miss = (books[tr["day"]].twin.get(tr["i"]) or {}).get("miss") or LT.NOT_RECORDED
            out.append(base | {"why": f"no twin: {miss}"})
            continue
        prow = pidx.get((sig["rule"], sig["mint"], sig["t"])) or {}
        pr = paper_record(prow)
        if pr is None:
            out.append(base | {"why": "no P2 paper row: the row not found"})
            continue
        lv = {"signal_ms": tr["signal_ms"] + tw["offset_ms"], "land_ms": tr["land_ms"] + tw["offset_ms"],
              "xdec_ms": tr["xdec_ms"] + tw["offset_ms"], "exit_ms": tr["exit_ms"] + tw["offset_ms"],
              "E": tr["entry_price"], "X": tr["exit_price"], "S": tr["stake_l"] / C.LAMPORTS, "ret": tr["ret"],
              "exit_why": lrow.get("exit_why") or ""}
        path = paths.get(tr["mint"]) or []
        q = quote_at(pools, tr["mint"], pr["land_ms"])
        pr["stale"] = bool(stale_of(prow)) if stale_of else False
        pp = parts(pr, tw, path, q)
        inn.append(base | {"live": lv, "paper": pr, "twin": tw, "q_sol": q, "parts": pp,
                           "p_minus_l": (pr["ret"] - tr["ret"]) * 100, "l_minus_t": (tr["ret"] - tw["ret"]) * 100})
    return {"in": inn, "out": out}


def stats(rows: list[dict], draws: int = DRAWS, seed: int = SEED) -> dict:
    """Means of P - T, its parts, P - L and L - T over the sample and trade bootstrap 95 % bands."""
    if not rows:
        return {"n": 0}
    cols = {"total": [r["parts"]["total"] for r in rows], **{k: [r["parts"][k] for r in rows] for k in PARTS},
            "p_minus_l": [r["p_minus_l"] for r in rows], "l_minus_t": [r["l_minus_t"] for r in rows],
            "paper": [r["paper"]["ret"] * 100 for r in rows], "live": [r["live"]["ret"] * 100 for r in rows],
            "twin": [r["twin"]["ret"] * 100 for r in rows]}
    cols = {k: np.array(v, dtype=float) for k, v in cols.items()}
    out = {"n": len(rows), **{k: float(v.mean()) for k, v in cols.items()},
           "median": float(np.median(cols["total"]))}
    out["sum"] = sum(out[k] for k in PARTS)
    out["largest"] = max(PARTS, key=lambda k: abs(out[k]))
    rng = np.random.default_rng(seed)
    n = len(rows)
    bs = collections.defaultdict(list)
    for _ in range(draws):
        idx = rng.integers(0, n, n)
        for k, v in cols.items():
            bs[k].append(v[idx].mean())
    out["band"] = {k: [float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))] for k, v in bs.items()}
    return out


def eras(signals: list[dict], since: float | None) -> list[dict]:
    """P2's same-coin part (paper minus live on its matched pairs) by the era of the paper signal."""
    out = []
    for name in ERAS:
        xs = [(x["ret"] - x["live_ret"]) * 100 for x in signals
              if x["ret"] is not None and x.get("live_ret") is not None and x["reason"] == P2.TRADED
              and era_of(x["t"], since) == name]
        out.append({"era": name, "n": len(xs), "mean": float(np.mean(xs)) if xs else None})
    return out


def era_of(t: float, since: float | None) -> str:
    if t >= CUT_MS:
        return ERAS[2]
    return ERAS[1] if since is not None and t >= since else ERAS[0]


# ---------------------------------------------------------------- the replay and the record

def twin_replay(trades: list[dict], fits: dict, root=None, log=print):
    """live_twin.replay, keeping the Replay (its books and price paths)."""
    from . import store
    last = LT.day_of(max(t["exit_ms"] for t in trades))
    rp = LT.Replay(trades, fits)
    mints = sorted({t["mint"] for t in trades})
    for d in [d for d in store.days(root) if d <= last]:
        n = 0
        for tb, r in LT.coin_events(d, mints, root):
            rp.feed(tb, r)
            n += 1
        log(f"g1 twin: {d} {n:,} events of {len(mints)} coins")
    rp.finish()
    return rp


def pool_quotes(mints, days, root=None) -> dict:
    """mint -> sorted [(t, effective quote lamports before the trade)] of its recorded pool trades on those days."""
    import polars as pl
    from . import store
    root = root or store.base()
    out: dict[str, list] = collections.defaultdict(list)
    for d in days:
        for fp in sorted((root / "amm" / f"date={d}").glob("*.parquet")):
            df = pl.scan_parquet(fp).filter(pl.col("mint").is_in(list(mints))).select("t", "mint", "pq", "vq").collect()
            for r in df.iter_rows(named=True):
                if r["pq"]:
                    out[r["mint"]].append((float(r["t"]), C.effective_quote(r["pq"], r["vq"])))
    return {k: sorted(v) for k, v in out.items()}


def stale_fill(row: dict, read: tuple | None, trades: list) -> bool:
    """A paper pool buy filled on a stale state: the coin's first pool read (t, slot) came after a pool trade of an
    older slot (sim.Engine.pool_state drops a read once the stream has given a pool trade) and before the landing,
    and no pool trade came between the read and the fill (the landing plus FILL_WAIT_MS at the latest), so the
    fill took the state of the older trade. trades: the coin's sorted [(t, slot)]."""
    land = R._f(row.get("land_ms"))
    if not read or not trades or land is None or not (trades[0][0] <= read[0] < land) or trades[0][1] >= read[1]:
        return False
    i = bisect.bisect_right([a for a, _ in trades], read[0])
    return i >= len(trades) or trades[i][0] > land + R.FILL_WAIT_MS


def stale_split(rows: list[dict], reads: dict, trades: dict) -> dict:
    """rule -> {n, mean, stale: (n, mean), fresh: (n, mean)} over the paper rows (returns in %)."""
    out = {}
    for rule in STALE_RULES:
        by = {True: [], False: []}
        for r in rows:
            if r.get("rule") == rule and R._f(r.get("ret")) is not None:
                by[stale_fill(r, reads.get(r.get("mint")), trades.get(r.get("mint")) or [])].append(R._f(r["ret"]))
        allr = by[True] + by[False]
        out[rule] = {"n": len(allr), "mean": float(np.mean(allr)) * 100 if allr else None,
                     **{k: (len(by[v]), float(np.mean(by[v])) * 100 if by[v] else None)
                        for k, v in (("stale", True), ("fresh", False))}}
    return out


def after_cut(paper: dict) -> list[dict]:
    """The paper rows of STALE_RULES signalled at or after the cut, P1's tainted and restart rows out."""
    return [r for r in paper.get("ledger") or [] if r.get("rule") in STALE_RULES
            and (R._f(r.get("signal_ms")) or 0) >= CUT_MS and r.get("exit_why") != "restart" and not R.tainted(r)]


def reads_and_trades(mints, days, root=None) -> tuple[dict, dict]:
    """(mint -> its first pool read (t, slot), mint -> its sorted pool trades [(t, slot)]) of those days."""
    import polars as pl
    from . import store
    root = root or store.base()
    mints = list(mints)
    reads, trades = {}, collections.defaultdict(list)
    for d in days:
        for fp in sorted((root / "other" / f"date={d}").glob("*.parquet")):
            df = pl.scan_parquet(fp).filter((pl.col("kind") == "pool_state").fill_null(False)
                                            & pl.col("mint").is_in(mints)).select("mint", "t", "slot").collect()
            for m, t, sl in df.iter_rows():
                if sl is not None and (m not in reads or t < reads[m][0]):
                    reads[m] = (float(t), int(sl))
        for fp in sorted((root / "amm" / f"date={d}").glob("*.parquet")):
            df = pl.scan_parquet(fp).filter(pl.col("mint").is_in(mints)).select("mint", "t", "slot").collect()
            for m, t, sl in df.iter_rows():
                trades[m].append((float(t), int(sl or 0)))
    return reads, {k: sorted(v) for k, v in trades.items()}


def stream_days(root=None) -> list[str]:
    """The recorded days from the cut's day on."""
    from . import store
    return [d for d in store.days(root) if d >= LT.day_of(CUT_MS)]


# ---------------------------------------------------------------- the report

def _pt(x) -> str:
    return "n/a" if x is None else f"{x:+.1f}"


def _band(st: dict, k: str) -> str:
    b = (st.get("band") or {}).get(k)
    return "n/a" if not b else f"{b[0]:+.1f} to {b[1]:+.1f}"


def _hm(ms) -> str:
    return "" if ms is None else datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%H:%M:%S")


def _s(a, b) -> str:
    return "" if a is None or b is None else f"{(a - b) / 1000:+.1f}"


def _px(x) -> str:
    return "" if not x else f"{x * 1e9:.2f}"


def trade_md(rows: list[dict]) -> list[str]:
    md = ["Times in s on the record's clock (live moved by the twin's offset), from the twin's signal; prices in SOL "
          "per 1e9 token units (x 1e9); returns in %.", "",
          "| coin | day | offset s | paper signal | live / paper / twin landing | stake L / P / T SOL | Q SOL | "
          "entry L / P / T | exit why L / P / T | exit decision L / P / T | exit L / P / T | ret L / P / T | "
          "P - T | largest part | paper fill on a stale pool state |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda r: r["live_signal_ms"]):
        lv, p, t, pp = r["live"], r["paper"], r["twin"], r["parts"]
        t0 = t["signal_ms"]
        big = max(PARTS, key=lambda k: abs(pp[k]))
        md.append(
            f"| {r['symbol'].strip() or r['mint'][:6]} | {LT.day_of(r['live_signal_ms'])[5:]} "
            f"{_hm(r['live_signal_ms'])} | {t['offset_ms'] / 1000:+.1f} | {_s(p['signal_ms'], t0)} | "
            f"{_s(lv['land_ms'], t0)} / {_s(p['land_ms'], t0)} / {_s(t.get('land_ms'), t0)} | "
            f"{lv['S']:.3f} / {p['S']:.3f} / {t['S']:.3f} | {'' if r['q_sol'] is None else round(r['q_sol'])} | "
            f"{_px(lv['E'])} / {_px(p['E'])} / {_px(t.get('E'))} | {lv['exit_why']} / {p['exit_why']} / "
            f"{t.get('exit_why') or t.get('how')} | {_s(lv['xdec_ms'], t0)} / {_s(p['xdec_ms'], t0)} / "
            f"{_s(t.get('xdec_ms'), t0)} | {_px(lv['X'])} / {_px(p['X'])} / {_px(t.get('X'))} | "
            f"{lv['ret'] * 100:+.1f} / {p['ret'] * 100:+.1f} / {t['ret'] * 100:+.1f} | {pp['total']:+.1f} | "
            f"{PART_NAMES[big]} {pp[big]:+.1f} | {'yes' if p.get('stale') else 'no'} |")
    return md


def markdown(res: dict) -> str:
    st, smp = res["stats"], res["sample"]
    md = ["# G1: P2's same-coin gap against the live twin, trade by trade", "",
          f"Pre-registration `{PREREG}`. Read only: `<data>/live/pumpfun_rt`, `<data>/paper/pumpfun_rt` and the "
          f"recorded stream. Live trades signalled at or after {R.FIX_DAY} (P1's cut) with a P2 paper row "
          "(`selection_p2.compute`, unchanged) and a twin (`live_twin`, unchanged, these trades only). Points a "
          f"trade, each side's return on its own stake. Bands: trade bootstrap, {DRAWS:,} draws, seed {SEED}. Four "
          "trials in R5's registry, family pumpfun, counted only (`pumpfun:gap_g1:*`); no Sharpe, no DSR.", "",
          "## The answer", ""]
    if st.get("n"):
        md += [f"- Sample: {st['n']} of {res['n_after']} live trades after the cut (every one left out named below).",
               f"- Paper minus twin (P - T): {_pt(st['total'])} points a trade (band {_band(st, 'total')}), median "
               f"{_pt(st['median'])}; paper {_pt(st['paper'])} %, twin {_pt(st['twin'])} %, live {_pt(st['live'])} %.",
               f"- Paper minus live (P - L, P2's same-coin difference on these trades) {_pt(st['p_minus_l'])} (band "
               f"{_band(st, 'p_minus_l')}); live minus twin (L - T) {_pt(st['l_minus_t'])} (band "
               f"{_band(st, 'l_minus_t')}); check: {_pt(st['p_minus_l'])} = {_pt(st['total'])} - "
               f"({_pt(st['l_minus_t'])}).",
               "- Parts of P - T (mean points a trade): " + ", ".join(f"{PART_NAMES[k]} {_pt(st[k])} "
                                                                       f"({_band(st, k)})" for k in PARTS)
               + f"; their sum {_pt(st['sum'])} against the total {_pt(st['total'])} ("
               + ("within" if abs(st["sum"] - st["total"]) <= SUM_TOL else "NOT within")
               + f" {SUM_TOL} points).",
               f"- Largest part: {PART_NAMES[st['largest']]} ({_pt(st[st['largest']])})."]
    else:
        md += [f"- No live trade after the cut has both a P2 paper row and a twin ({res['n_after']} after the cut)."]
    md += ["", "## The bridge to the headline numbers", "",
           "P2's same-coin part (paper minus live on its matched pairs) by the era of the paper signal; the twin's "
           "-2.5 is 2026-10-22 to 24, no trade after the cut.", "",
           "| era | matched pairs | paper minus live, mean points |", "|---|---|---|"]
    md += [f"| {e['era']} | {e['n']} | {_pt(e['mean'])} |" for e in res["eras"]]
    md += ["", "## Paper fills on a stale pool state (added after the first run)", "",
           f"Every paper row of {', '.join(STALE_RULES)} signalled from the cut, P1's tainted and restart rows out. "
           "Stale: the coin's first pool read came after a pool trade of an older slot (the engine, "
           "`sim.Engine.pool_state`, drops a read once the stream has given a pool trade) and before the landing, "
           "and no pool trade came between the read and the fill, so the buy filled on the older trade's state. "
           "One trial more, `pumpfun:gap_g1:stale_reads`, counted.", "",
           "| rule | rows | mean | stale: rows | stale: mean | the rest: rows | the rest: mean |",
           "|---|---|---|---|---|---|---|"]
    for rule, x in (res.get("stale") or {}).items():
        md.append(f"| {rule} | {x['n']} | {_pt(x['mean'])} % | {x['stale'][0]} | {_pt(x['stale'][1])} % | "
                  f"{x['fresh'][0]} | {_pt(x['fresh'][1])} % |")
    md += ["", "## Three records a trade", "", *trade_md(smp["in"]), "",
           "Parts of each trade (points):", "",
           "| coin | " + " | ".join(PART_NAMES[k] for k in PARTS) + " | sum | P - T |",
           "|---|" + "---|" * (len(PARTS) + 2)]
    for r in sorted(smp["in"], key=lambda r: r["live_signal_ms"]):
        pp = r["parts"]
        md.append(f"| {r['symbol'].strip() or r['mint'][:6]} {_hm(r['live_signal_ms'])} | "
                  + " | ".join(_pt(pp[k]) for k in PARTS) + f" | {_pt(sum(pp[k] for k in PARTS))} | "
                  f"{_pt(pp['total'])} |")
    c = collections.Counter(x["why"] for x in smp["out"])
    md += ["", "## Live trades after the cut left out", "", "| why | trades |", "|---|---|"]
    md += [f"| {k} | {v} |" for k, v in c.most_common()]
    return "\n".join(md) + "\n"


def run(live_dir: Path, paper_dir: Path, root: Path | None, out: Path, register: bool = True, log=print) -> dict:
    if register:
        metrics.register(trials() + posthoc_trials())         # before any number of this run exists
    live, paper = P2.read_live(live_dir), P2.read_paper(paper_dir)
    p2 = P2.compute(live, paper)
    measured = LT._jsonl(live_dir / "measured.jsonl")
    trades = LT.live_trades(live["ledger"], live["orders"], measured)
    key = {(r.get("mint"), R._f(r.get("signal_ms"))): i for i, r in enumerate(live["ledger"])}
    trades = [{**t, "key": key[(t["mint"], t["signal_ms"])]} for t in trades if t["signal_ms"] >= CUT_MS]
    trades = [{**t, "i": i} for i, t in enumerate(trades)]
    res = {"n_after": len(trades), "eras": eras(p2["signals"], R._f(paper.get("since")))}
    if trades:
        fits = LT.lodo_fits(measured, [t["day"] for t in trades])
        rp = twin_replay(trades, fits, root, log)
        days = sorted({t["day"] for t in trades} | {LT.day_of(t["exit_ms"]) for t in trades})
        pools = pool_quotes({t["mint"] for t in trades}, days, root)
    rows = after_cut(paper)
    reads, trs = reads_and_trades({r["mint"] for r in rows} | {t["mint"] for t in trades}, stream_days(root), root)
    res["stale"] = stale_split(rows, reads, trs)

    def stale_of(r):
        return stale_fill(r, reads.get(r.get("mint")), trs.get(r.get("mint")) or [])
    res["sample"] = sample(live, paper, p2, trades, rp.books, rp.path, pools, stale_of) if trades else \
        {"in": [], "out": []}
    res["stats"] = stats(res["sample"]["in"])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(markdown(res), encoding="utf-8")
    st = res["stats"]
    log(f"g1: {st.get('n', 0)} of {res['n_after']} trades, paper minus twin {_pt(st.get('total'))} points, "
        f"largest {PART_NAMES.get(st.get('largest'), 'n/a')} -> {out}")
    return res


def main(argv: list[str] | None = None) -> int:
    from .live import paper_dir
    from .live_exec import data_dir
    ap = argparse.ArgumentParser(prog="lab.pumpfun_rt.reconcile_g1", description=__doc__.split("\n")[0])
    ap.add_argument("--live", default=None)
    ap.add_argument("--paper", default=None)
    ap.add_argument("--root", default=None)
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--json", default=None, help="the sample's records as JSON here too")
    a = ap.parse_args(sys.argv[1:] if argv is None else argv)
    r = run(Path(a.live) if a.live else data_dir(), Path(a.paper) if a.paper else paper_dir(),
            Path(a.root) if a.root else None, Path(a.out))
    if a.json:
        Path(a.json).write_text(json.dumps(r["sample"], default=float, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
