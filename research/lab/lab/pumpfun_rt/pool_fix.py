"""G1's stale pool state, fixed on the paper side (results/pumpfun_pool_state_fix_prereg.md). PAPER ONLY: nothing a
live bot, its sizing, a wallet or key reads changes; the engine's default (the live service, the twin) is unchanged.

    python -m lab.pumpfun_rt.pool_fix replay --fresh 0|1 --json OUT.json   one run of the window (heavy: flock)
    python -m lab.pumpfun_rt.pool_fix report --before A.json --after B.json [--out results/pumpfun_pool_state_fix.md]
                                             [--keys results/pumpfun_pool_state_fix_rows.json]

sim.Engine.pool_state dropped a pool read once the stream had given a pool trade, so a paper buy could fill on a
state up to 81 slots older than the read (HEXN 2026-10-29). With sim.Engine(fresh_pool=True), what the shadow's books
run since this study, the state is the newest by slot of pool read and pool trade. The replay: the record's days of
the window (WINDOW_FROM_MS to the end of UNTIL_DAY) through sim, the engine as the shadow builds it with the 40 books
(BOOKS: the four realistic books, P3's, R2's, E1's forward books) on the realistic executor, once without the flag and
once with it. Per book the entries (as ladder.pf_entries), the mean per entry with R7's band clustered by UTC day
(factory.by_day), the change in points and the share of entries whose entry price moved. The ledger is not
rewritten: the keys of its rows of these books on which G1's stale_fill holds go into KEYS, which realistic.stale and
every reader of these books skip and count. 41 trials in R5's registry, family pumpfun, counted only.
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .. import metrics
from . import pipeline as P
from . import realistic as R

PREREG = "results/pumpfun_pool_state_fix_prereg.md"
RESULTS = Path(__file__).resolve().parents[2] / "results"
OUT = RESULTS / "pumpfun_pool_state_fix.md"
KEYS = RESULTS / "pumpfun_pool_state_fix_rows.json"     # realistic.STALE_KEYS
WINDOW = RESULTS / "pumpfun_realistic_fit_window.md"    # 12041's sensitivity, both runs with the fix
WINDOW_FROM_MS = int(datetime(2026, 10, 24, 1, 43, tzinfo=timezone.utc).timestamp() * 1000)   # ladder.PF_REAL_FROM_MS
UNTIL_DAY = "2026-11-15"                                  # the last full UTC day at the run
DAY_MS = 86_400_000
TAIL_MS = R.R1_TAIL_MS
MOVED = 1e-6                                              # an entry price differing by more than this share moved
FOUR = ("P_pool0", "P_pool0_wait", "P_cmig_model", "P_pool0_wait_norug_half")


def books() -> list[str]:
    """The 40 books restated: the four realistic books, P3's 10 EUR books, R2's books, E1's forward books."""
    from . import slippage_e1 as E1
    return (list(FOUR) + [n for n, _ in R.TEN] + [n[0] for n in R.SMALL]
            + [f"{r}{E1.TAG}{k}" for r in E1.RULES for k in E1.PAIRS])


def trials() -> list[dict]:
    return [{"id": f"pumpfun:pool_fix:{b}", "family": "pumpfun", "n": 2, "sharpe": None, "source": PREREG}
            for b in books()] + [{"id": "pumpfun:pool_fix:ledger_stale", "family": "pumpfun", "n": 1,
                                  "sharpe": None, "source": PREREG}]


def _day(ms) -> str:
    return datetime.fromtimestamp(float(ms) / 1000, timezone.utc).strftime("%Y-%m-%d")


# ---------------------------------------------------------------- the replay

def engine(fresh: bool, warm: list[str], root, t_lo: int, t_hi: int, model: R.Model):
    """The engine as live.Shadow builds it (creator, wallet and sniper books warmed on `warm`, the shadow's models and
    categories, select, trend and social trackers) with the 40 books; fresh_pool as given."""
    from . import early as EA
    from . import sim
    from . import wallets as W
    from .categorize import BOOK_DAYS, CategoryIndex
    from .model import load
    from .slippage_e1 import shadow_books
    from .study import warm_book
    try:
        models = load()
    except Exception:  # noqa: BLE001 - as the shadow: no models, no model filter
        models = {}
    try:
        cats = CategoryIndex.load(mints=False, max_age_days=BOOK_DAYS)
    except Exception:  # noqa: BLE001
        cats = None
    eng = sim.Engine([], book=warm_book(warm, root), decisions=False, wallets=W.warm(warm, root), cats=cats,
                     models=models, snipers=EA.warm_snipers(warm, root), entry_from=t_lo, entry_until=t_hi - TAIL_MS,
                     select=True, trend=True, social=True, fresh_pool=fresh)
    wallets: dict = {}
    R.books(eng, [P.BY_NAME[n] for n in FOUR], model, wallets)
    R.ten_books(eng, model, wallets, now_ms=t_lo)
    R.small_books(eng, model, wallets)
    shadow_books(eng, model, wallets)
    return eng


def replay(fresh: bool, root=None, log=print, model: R.Model | None = None, until_day: str = UNTIL_DAY) -> dict:
    """One run of the window: per book its closed trades and failed buys (the fields the measures read)."""
    from . import sim, store
    from .study import WARM_DAYS
    model = model or R.Model()
    days = [d for d in store.days(root) if _day(WINDOW_FROM_MS) <= d <= until_day]
    warm = [d for d in store.days(root) if d < days[0]][-WARM_DAYS:]
    t_lo = WINDOW_FROM_MS
    t_hi = int(datetime.strptime(until_day, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000) + DAY_MS
    t0 = time.time()
    log(f"pool_fix: fresh_pool={fresh}, {len(days)} day(s) {days[0]} to {days[-1]}, warm-up {len(warm)}")
    eng = engine(fresh, warm, root, t_lo, t_hi, model)
    sim.replay(days, eng, root, progress=lambda d, n: log(f"pool_fix: {d} done ({n:,} events, "
                                                         f"{time.time() - t0:.0f} s)"), until_ms=t_hi)
    keep = set(books())
    out: dict = {b: [] for b in keep}
    for p in eng.pipes:
        for t in p.closed:
            if t["rule"] in keep:
                out[t["rule"]].append({k: t.get(k) for k in ("mint", "signal_ms", "land_ms", "entry_price", "ret",
                                                              "pnl_sol", "stake_sol", "exit_why")} | {"failed": False})
        for f in p.failed:
            if f["rule"] in keep:
                out[f["rule"]].append({"mint": f["mint"], "signal_ms": f["signal_ms"], "pnl_sol": f["pnl_sol"],
                                       "why": f.get("why"), "failed": True})
    return {"fresh": fresh, "days": days, "span": [t_lo, t_hi], "books": out, "fit": model.fit.to_json(),
            "config": model.cfg.to_json(), "seconds": time.time() - t0}


def model_of(run: dict) -> R.Model:
    """The fit and the sizing settings a run used, for the other run (the daily job may refit between them)."""
    c = dict(run["config"])
    c["ceiling_sol"] = float("inf") if c.get("ceiling_sol") is None else c["ceiling_sol"]
    return R.Model(R.Fit.from_json(run["fit"]), R.LiveConfig(**c))


# ---------------------------------------------------------------- the measures

def per_entry(es: list[dict], since_ms: int = WINDOW_FROM_MS, until_ms: int | None = None) -> list[tuple[int, float]]:
    """ladder.pf_entries on a run's entries: the closed trades' ret, a failed buy its fee over the median stake of
    the book's trades; signals in [since_ms, until_ms)."""
    def inside(e):
        s = R._f(e.get("signal_ms"))
        return s is not None and s >= since_ms and (until_ms is None or s < until_ms)
    out, stakes = [], []
    for e in es:
        if not e["failed"] and inside(e) and R._f(e.get("ret")) is not None and e.get("exit_why") != "restart":
            out.append((int(e["signal_ms"]), float(e["ret"])))
            stakes.append(R._f(e.get("stake_sol")) or 0.0)
    st = float(np.median([x for x in stakes if x > 0])) if any(x > 0 for x in stakes) else 0.0
    out += [(int(e["signal_ms"]), float(e["pnl_sol"]) / st) for e in es
            if e["failed"] and inside(e) and st > 0 and R._f(e.get("pnl_sol")) is not None]
    return sorted(out)


def stats(entries: list[tuple[int, float]]) -> dict:
    """Entries, the mean per entry and R7's 95 % band clustered by UTC day (factory.by_day), the days traded."""
    from . import factory as F
    if not entries:
        return {"n": 0, "mean": None, "lo": None, "hi": None, "days": 0}
    x = np.array([r for _, r in entries], dtype=float)
    days = sorted({_day(t) for t, _ in entries})
    idx = {d: i for i, d in enumerate(days)}
    b = F.by_day(x, np.array([idx[_day(t)] for t, _ in entries], dtype=int), len(days))
    return {"n": len(x), "mean": float(x.mean()), "lo": b["lo"], "hi": b["hi"], "days": b["days_traded"]}


def moved(before: list[dict], after: list[dict]) -> dict:
    """The entries of both runs matched by coin and signal time, closed in both, and how many changed their entry
    price by more than MOVED; the signals of one run only."""
    def key(e):
        return e["mint"], int(e["signal_ms"])
    a = {key(e): e for e in before if R._f(e.get("signal_ms")) is not None}
    b = {key(e): e for e in after if R._f(e.get("signal_ms")) is not None}
    both = [k for k in a if k in b and not a[k]["failed"] and not b[k]["failed"]
            and R._f(a[k].get("entry_price")) and R._f(b[k].get("entry_price"))]
    n = sum(1 for k in both if abs(float(b[k]["entry_price"]) / float(a[k]["entry_price"]) - 1) > MOVED)
    return {"matched": len(both), "moved": n, "share": n / len(both) if both else None,
            "only_before": sum(1 for k in a if k not in b), "only_after": sum(1 for k in b if k not in a),
            "fail_changed": sum(1 for k in a if k in b and a[k]["failed"] != b[k]["failed"])}


def compare(before: dict, after: dict, until_ms: int | None = None) -> dict:
    """Per book: before and after (stats), the change in points, moved."""
    out = {}
    for name in books():
        a, b = before["books"].get(name) or [], after["books"].get(name) or []
        sa, sb = stats(per_entry(a, until_ms=until_ms)), stats(per_entry(b, until_ms=until_ms))
        d = (sb["mean"] - sa["mean"]) * 100 if sa["mean"] is not None and sb["mean"] is not None else None
        out[name] = {"before": sa, "after": sb, "pts": d, "moved": moved(a, b)}
    return out


# ---------------------------------------------------------------- the ledger

def ledger_rows(ledger: list[dict]) -> list[dict]:
    """The ledger's closed rows of the books from the window's start, P1's tainted and restart rows out."""
    keep = set(books())
    return [r for r in ledger if r.get("rule") in keep and (R._f(r.get("signal_ms")) or 0) >= WINDOW_FROM_MS
            and r.get("exit_why") != "restart" and not R.tainted(r)]


def ledger_stale(ledger: list[dict], root=None) -> dict:
    """G1's stale_fill on every ledger row of the books (ledger_rows): the keys (realistic.stale_key) and per book
    the rows, the stale ones and their P&L; the stream's reads and pool trades of the coins from the window's day."""
    from . import reconcile_g1 as G
    from . import store
    rows = ledger_rows(ledger)
    days = [d for d in store.days(root) if d >= _day(WINDOW_FROM_MS)]
    reads, trades = G.reads_and_trades({r["mint"] for r in rows}, days, root)
    keys, by = [], collections.defaultdict(lambda: {"rows": 0, "stale": 0, "stale_sol": 0.0})
    last = 0
    for r in rows:
        b = by[r["rule"]]
        b["rows"] += 1
        last = max(last, int(R._f(r.get("signal_ms")) or 0))
        if G.stale_fill(r, reads.get(r["mint"]), trades.get(r["mint"]) or []):
            keys.append(R.stale_key(r))
            b["stale"] += 1
            b["stale_sol"] += R._f(r.get("pnl_sol")) or 0.0
    return {"keys": sorted(keys), "books": dict(by), "from_ms": WINDOW_FROM_MS, "to_ms": last}


def write_keys(st: dict, path: Path = KEYS) -> None:
    path.write_text(json.dumps({"source": PREREG, "rule": "reconcile_g1.stale_fill", "from_ms": st["from_ms"],
                                "to_ms": st["to_ms"], "keys": st["keys"]}, indent=0) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- the report

def _pc(x) -> str:
    return "n/a" if x is None else f"{x * 100:+.1f} %"


def _band(s: dict) -> str:
    return "n/a" if s.get("lo") is None or s["n"] < 2 else f"{_pc(s['lo'])} to {_pc(s['hi'])}"


def markdown(res: dict) -> str:
    cmp_, st, b, a = res["books"], res["ledger"], res["before_run"], res["after_run"]
    n_st = sum(x["stale"] for x in st["books"].values())
    to = datetime.fromtimestamp(st["to_ms"] / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M")
    md = ["# The stale pool state G1 found: the paper fix and every rule book restated", "",
          f"Pre-registration `{PREREG}`. Replay of the record's days {b['days'][0]} to {b['days'][-1]}, signals from "
          f"{_day(WINDOW_FROM_MS)} 01:43 UTC to {UNTIL_DAY} 24:00 UTC, the engine as the shadow builds it with the "
          f"realistic executor (the fit and the live sizing settings of the run's day, the shadow's models), once "
          f"without `sim.Engine(fresh_pool=...)` (before: a pool read dropped once the stream gave a pool trade) and "
          f"once with it (after: the newest state by slot). Entries: closed trades and failed buys (a failed buy its "
          f"fee over the book's median stake). Band: R7's 95 % band clustered by UTC day. Points: after less before. "
          f"Moved: entries of both runs on the same coin and signal, closed in both, whose entry price changed. "
          f"{len(cmp_) * 2 + 1} trials in R5's registry, family pumpfun, counted only (`pumpfun:pool_fix:*`); no "
          f"Sharpe, no DSR.", "",
          "## Per book", "",
          "| book | entries before | mean before | band before | entries after | mean after | band after | points | "
          "moved | in one run only (before / after) |", "|---|---|---|---|---|---|---|---|---|---|"]
    for name, x in cmp_.items():
        s0, s1, m = x["before"], x["after"], x["moved"]
        share = "n/a" if m["share"] is None else f"{m['moved']} of {m['matched']} ({m['share'] * 100:.1f} %)"
        md.append(f"| {name} | {s0['n']} | {_pc(s0['mean'])} | {_band(s0)} | {s1['n']} | {_pc(s1['mean'])} | "
                  f"{_band(s1)} | {'n/a' if x['pts'] is None else format(x['pts'], '+.1f')} | {share} | "
                  f"{m['only_before']} / {m['only_after']} |")
    md += ["", "## The ledger", "",
           f"`<data>/paper/pumpfun_rt/ledger.csv` is not rewritten. Its closed rows of these books signalled from "
           f"{_day(WINDOW_FROM_MS)} 01:43 UTC to {to} UTC (P1's tainted and restart rows out) on which G1's "
           f"`stale_fill` holds: {n_st}; their keys (a hash of book, coin and signal time) are in "
           f"`results/pumpfun_pool_state_fix_rows.json`, and `realistic.md` (P3's table, R2's wallets, E1's "
           f"forward table) and the ladder skip and count them (`realistic.stale`). Rows "
           f"between the run and the deploy of the fix are not checked.", "",
           "| book | ledger rows | stale | stale P&L SOL |", "|---|---|---|---|"]
    for name in cmp_:
        x = st["books"].get(name)
        if x:
            md.append(f"| {name} | {x['rows']} | {x['stale']} | {x['stale_sol']:+.4f} |")
    md += sens_lines(res.get("sens") or {})
    md += ["", "## What P3's gate and the ladder read now", ""]
    md += res.get("now") or ["n/a"]
    return "\n".join(md) + "\n"


def sensitivity(cmp_: dict, path: Path = WINDOW) -> dict:
    """12041's sensitivity (results/pumpfun_realistic_fit_window.md: the fallback against the new fit, both with
    fresh_pool on) against this study's runs on the run day's fit: what of its points stands over its fallback after
    the fix (after less its fallback) and what the engine before the fix gives (before less its fallback)."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    out = {}
    for line in text.splitlines():
        c = [x.strip() for x in line.strip().strip("|").split("|")]
        if len(c) == 8 and c[0] in cmp_ and c[2].endswith("%") and c[5].endswith("%"):
            fb, new, pts = float(c[2].rstrip(" %")), float(c[5].rstrip(" %")), float(c[7])
            x = cmp_[c[0]]
            a = None if x["after"]["mean"] is None else x["after"]["mean"] * 100
            b = None if x["before"]["mean"] is None else x["before"]["mean"] * 100
            out[c[0]] = {"fallback": fb, "new": new, "pts": pts, "after": a, "before": b,
                         "after_pts": None if a is None else a - fb, "before_pts": None if b is None else b - fb,
                         "share": None if a is None or not pts else (a - fb) / pts}
    return out


def sens_lines(sens: dict) -> list[str]:
    if not sens:
        return []
    md = ["", "## 12041's sensitivity", "",
          f"`{WINDOW.name}` (12041): the fallback against the new fit, both runs with `fresh_pool` on. Against its "
          f"fallback mean: this study's after run (the fix on, the run day's fit) and before run (the fix off). "
          f"Survives: after less its fallback, as a share of its points.", "",
          "| book | 12041 fallback | 12041 new fit | 12041 points | after | after less fallback | before | "
          "before less fallback | survives |", "|---|---|---|---|---|---|---|---|---|"]

    def f(v, unit=""):
        return "n/a" if v is None else f"{v:+.1f}{unit}"
    for name, x in sens.items():
        md.append(f"| {name} | {f(x['fallback'], ' %')} | {f(x['new'], ' %')} | {f(x['pts'])} | "
                  f"{f(x['after'], ' %')} | {f(x['after_pts'])} | {f(x['before'], ' %')} | {f(x['before_pts'])} | "
                  f"{'n/a' if x['share'] is None else format(x['share'] * 100, '.0f') + ' %'} |")
    return md


def now_lines(ledger_dir: Path | None = None, data_root: Path | None = None) -> list[str]:
    """P3's books (realistic.ten_status) and the ladder's pump.fun rows (ladder.pf_context) on today's ledger, with
    and without the stale rows (the without from the keys written)."""
    from ..ops import ladder as L
    from .live import paper_dir
    pd = ledger_dir or paper_dir()
    root = data_root or pd.parents[1]
    ledger, failed = R.read_csv(pd / "ledger.csv"), R.read_csv(pd / "failed.csv")
    state = R.read_json(pd / "state.json")
    rj = R.read_json(R.reports_dir() / "realistic.json") or {}
    eur, gap, now = R.sol_eur() or rj.get("sol_eur"), rj.get("selection"), int(time.time() * 1000)
    md = ["| P3 book | wallet EUR, all rows | wallet EUR, stale out | trades | mean | band | stale out (SOL) | "
          "gate |", "|---|---|---|---|---|---|---|---|"]
    with_ = {r["book"]: r for r in R.ten_status(state, ledger, failed, eur, gap, now, skip_stale=False)}
    for r in R.ten_status(state, ledger, failed, eur, gap, now):
        w = with_[r["book"]]
        band = "n/a" if not r["band"] else f"{_pc(r['band'][0])} to {_pc(r['band'][1])}"
        md.append(f"| {r['book']} | {'n/a' if w['eur'] is None else format(w['eur'], '.2f')} | "
                  f"{'n/a' if r['eur'] is None else format(r['eur'], '.2f')} | {r['trades']} (was {w['trades']}) | "
                  f"{_pc(r['mean'])} (was {_pc(w['mean'])}) | {band} | {r['stale']} ({r['stale_sol']:+.4f}) | "
                  f"{R.ten_gate_text(r)} |")
    ctx = L.pf_context(root, now)
    keys, R.STALE_KEYS = R.stale_keys(), frozenset()         # the same rows with the stale ones in
    was = L.pf_context(root, now)
    R.STALE_KEYS = keys
    md += ["", "| ladder rule | entries | mean | R7 band | with the stale rows: entries, mean, band | stale out | "
           "tainted out (P1) |", "|---|---|---|---|---|---|---|"]
    for rule, x in ctx["rules"].items():
        w = was["rules"][rule]
        md.append(f"| {rule} | {x['entries']} | {_pc(x['mean'])} | {_lohi(x)} | {w['entries']}, {_pc(w['mean'])}, "
                  f"{_lohi(w)} | {x.get('stale', 0)} | {x['tainted']} |")
    return md


def _lohi(x: dict) -> str:
    return "n/a" if x.get("lo") is None else f"{_pc(x['lo'])} to {_pc(x['hi'])}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="lab.pumpfun_rt.pool_fix", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    a1 = sub.add_parser("replay")
    a1.add_argument("--fresh", type=int, choices=(0, 1), required=True)
    a1.add_argument("--json", required=True)
    a1.add_argument("--like", default=None, help="the fit and sizing settings of this earlier run's JSON")
    a1.add_argument("--root", default=None)
    a2 = sub.add_parser("report")
    a2.add_argument("--before", required=True)
    a2.add_argument("--after", required=True)
    a2.add_argument("--out", default=str(OUT))
    a2.add_argument("--keys", default=str(KEYS))
    a2.add_argument("--root", default=None)
    a = ap.parse_args(sys.argv[1:] if argv is None else argv)
    metrics.register(trials())                               # before any number of this run exists
    root = Path(a.root) if a.root else None
    if a.cmd == "replay":
        res = replay(bool(a.fresh), root, model=model_of(json.loads(Path(a.like).read_text(encoding="utf-8")))
                     if a.like else None)
        Path(a.json).write_text(json.dumps(res, default=float), encoding="utf-8")
        return 0
    from .live import paper_dir
    before, after = (json.loads(Path(p).read_text(encoding="utf-8")) for p in (a.before, a.after))
    st = ledger_stale(R.read_csv(paper_dir() / "ledger.csv"), root)
    write_keys(st, Path(a.keys))
    R.STALE_KEYS = None                                      # read the keys just written
    cmp_ = compare(before, after)
    res = {"books": cmp_, "ledger": st, "before_run": before, "after_run": after, "now": now_lines(),
           "sens": sensitivity(cmp_)}
    Path(a.out).write_text(markdown(res), encoding="utf-8")
    print(f"pool_fix: {len(st['keys'])} stale ledger rows -> {a.keys}; report -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
