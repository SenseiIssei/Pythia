"""A4: the readiness ladder promotes on its own from step 2 to step 4 (results/ladder_promotion_a4_prereg.md).

The ladder (lab.ops.ladder) decides the steps; this job acts on its rows once a day (job `promote`):

  2 -> 3   a candidate on step 2 or higher gets one forward shadow, keyed by its ladder id, in
           <data>/promotions/shadows.json; once ever, never restarted. Each shadow is one trial of R5's registry.
           Its file <data>/promotions/shadow/<id>.csv (date, ret, trades, logged_ms) is appended once a day from
           what the ladder records: a paper book's journal, the weekly factory's shadow journal or the genome
           re-simulated on the long panel, F2's shadow wallet, the pump.fun rule's realistic paper ledger. A kind
           with no way to run it (G2's models, an F2 genome without F2's wallet) is a missing tool on the ladder.
  3 -> 4   a shadow with SHADOW_DAYS dates and SHADOW_TRADES trades after its start, logged after each date and never
           rewritten, and its step 3 on the ladder, gets one lockbox look: ready without reading a return, claimed in
           <data>/promotions/lockbox.jsonl, registered in R5, looked at, the result written, then read. A second run
           is refused; a claim without a result or a fail is final.
  4        <data>/promotions/live_ready.json: the step 4 passes only, with their evidence, venue, instrument and an
           equal share of 50 EUR; one Telegram line ("studies") when a candidate enters it. Nothing reads it here.

Paper only: nothing here trades, arms or reads a key; no live bot, wallet or engine file changes.

  python -m lab.ops.promote            the daily run (writes the promotions and the ladder's report)
  python -m lab.ops.promote --print    the registry as the ladder would show it, write nothing
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from . import ladder, notify

NAME = "promote"
PREREG = "research/lab/results/ladder_promotion_a4_prereg.md"
DAY_MS = 86_400_000
SHADOW_DAYS = ladder.SHADOW_DAYS        # 30 dates after the start (the review, gate 7)
SHADOW_TRADES = 30                      # gate 7: 30 trades or rebalances
TRADE_TURNOVER = 0.01                   # lab.paper.review: a rebalance
BUDGET_EUR = ladder.EXEC_CAP_EUR        # what the owner allowed in all for step 5
COLS = ["date", "ret", "trades", "logged_ms"]

# Why a kind cannot be run, by the ladder id's source (book, weekly, F2, G2, pumpfun).
SHADOW_MISSING = {"G2": "G2's shadows log forecast losses; no paper book trades a model",
                  "F2": "F2 runs no shadow wallet for it, and nothing starts one from the ladder's record"}
LOOK_MISSING = {"book": "no backtest of a paper book over the lockbox from its name (each book steps forward only)",
                "F2": "no UCITS S&P 500 fund series in EUR from 2026-07-01, its benchmark (R10's quotes are one snapshot)",
                "G2": SHADOW_MISSING["G2"]}
# Venue and instrument for the hand-over, by study.
VENUE = {"S1": ("Kraken", "spot"), "S2": ("Jupiter", "on-chain spot (Solana)"), "L1": ("Jupiter", "on-chain spot (Solana)"),
         "F2": ("Jupiter", "on-chain spot (Solana)"), "R2": ("pump.fun", "memecoins"), "F3": ("pump.fun", "memecoins"),
         "P3": ("pump.fun", "memecoins"), "PF": ("pump.fun", "memecoins"), "EQ1": ("Trade Republic", "ETF")}
# A look made while A4 was written: a code check of genome_look on 2026-10-29 on the newest held-back row with its
# genome stored (38c0885daa3c, checked for G1's report, not a ladder candidate), with a lab cache from before
# 2026-10-12. It saw the lockbox, so it is one look (R6) and one trial (R5): run() logs it once in
# factory/lockbox.jsonl and registers it.
DEV_LOOKS = [{"factory": "promote-dev", "run": "a4-code-check", "date": "2026-10-29", "key": "38c0885daa3c",
              "behaviour": None, "name": "rank(z_3(volume)), top 20, coin > MA50, vol < 120 %, best 10 by signal",
              "benchmark": "btc_eth", "lockbox_from": "2026-07-01", "lockbox_to": "2026-10-11", "lockbox_days": 103,
              "lockbox_sharpe": 2.664, "lockbox_excess_sharpe": -2.843, "bench_sharpe": 3.576, "looks": 1,
              "dsr": 0.045}]
NEUTRAL = ("not chosen", "perpetual futures long/short")
SPOT = ("not chosen", "crypto spot")


def source(cid: str) -> str:
    return cid.split(":", 1)[0]


def home(root: Path) -> Path:
    return root / "promotions"


def shadows_path(root: Path) -> Path:
    return home(root) / "shadows.json"


def looks_path(root: Path) -> Path:
    return home(root) / "lockbox.jsonl"


def ready_path(root: Path) -> Path:
    return home(root) / "live_ready.json"


def slug(cid: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", cid)


def shadow_rel(cid: str) -> str:
    return f"promotions/shadow/{slug(cid)}.csv"


def _num(v) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _day_ms(day: str) -> int:
    return int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp() * 1000)


# ---------------------------------------------------------------- the registry and the looks

def read_shadows(root: Path) -> dict[str, dict]:
    d = notify.read_json(shadows_path(root))
    sh = d.get("shadows") if isinstance(d, dict) else None
    return {k: v for k, v in sh.items() if isinstance(v, dict)} if isinstance(sh, dict) else {}


def write_shadows(root: Path, sh: dict[str, dict]) -> None:
    notify.write_json(shadows_path(root), {"prereg": PREREG, "shadows": sh})


def append_line(p: Path, row: dict) -> None:
    """One line, on disk before the call returns."""
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, separators=(",", ":"), default=float) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def read_looks(root: Path) -> dict[str, dict]:
    """Id to {"claimed_ms", "done": the result line or None}; the first claim and the first result count."""
    out: dict[str, dict] = {}
    for x in ladder._jsonl(looks_path(root)):
        cid = str(x.get("id") or "")
        if not cid:
            continue
        o = out.setdefault(cid, {"claimed_ms": x.get("claimed_ms"), "done": None})
        if "pass" in x and o["done"] is None:
            o["done"] = x
    return out


# ---------------------------------------------------------------- the shadows' files

def journal(root: Path, cid: str) -> list[dict]:
    try:
        with (root / shadow_rel(cid)).open(encoding="utf-8", newline="") as f:
            return list(csv.DictReader(f))
    except (OSError, csv.Error):
        return []


def _lines(root: Path, cid: str) -> list[str]:
    try:
        return (root / shadow_rel(cid)).read_text(encoding="utf-8").splitlines()[1:]
    except OSError:
        return []


def digest(lines: list[str]) -> str:
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def record(root: Path, cid: str, e: dict) -> dict:
    """Days, trades and the "before" check of one shadow from its file: dates after the start, each row logged after
    its date ended, the start registered before the first date began, and the rows the registry saw unchanged."""
    rows, lines = journal(root, cid), _lines(root, cid)
    start, n = str(e.get("start_day") or ""), int(_num(e.get("rows")) or 0)
    dates = [str(r.get("date") or "") for r in rows]
    trades = sum(int(_num(r.get("trades")) or 0) for r in rows)
    why = ""
    if len(lines) < n or digest(lines[:n]) != (e.get("digest") or digest([])):
        why = f"rewritten: the {n} rows the registry saw changed"
    elif any(d <= start for d in dates):
        why = f"a row dated on or before its start {start}"
    elif any((_num(r.get("logged_ms")) or 0) < _day_ms(r["date"]) + DAY_MS for r in rows if r.get("date")):
        why = "a row logged before its date ended"
    elif dates and (_num(e.get("start_ms")) or math.inf) > _day_ms(min(dates)):
        why = "the start was registered after its first date began"
    return {"days": len(set(dates)), "trades": trades, "before": not why, "path": shadow_rel(cid),
            "why": why or f"{len(rows)} rows logged day by day since {start}, unchanged",
            "last": max(dates) if dates else None}


def append(root: Path, cid: str, e: dict, rows: list[tuple[str, float, int]], now: int) -> int:
    """The finished dates after the start and after the file's last one, stamped with now; the registry keeps the new
    row count and digest."""
    today = ladder._day(now)
    last = max([str(r.get("date") or "") for r in journal(root, cid)] + [str(e.get("start_day") or "")])
    new = sorted({d: (d, r, t) for d, r, t in rows if last < d < today and r is not None}.values())
    p = root / shadow_rel(cid)
    if new:
        fresh = not p.exists()
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8", newline="") as fh:
            wr = csv.writer(fh, lineterminator="\n")
            if fresh:
                wr.writerow(COLS)
            wr.writerows([d, f"{r:.7f}", int(t), now] for d, r, t in new)
    lines = _lines(root, cid)
    e.update(rows=len(lines), digest=digest(lines))
    return len(new)


# ---------------------------------------------------------------- each kind's daily rows

def step_book(root: Path, e: dict, cache: dict) -> list[tuple[str, float, int]]:
    """A paper book's journal: the day's return from equity (the last row of a date), a rebalance above 0.01 turnover."""
    by: dict[str, dict] = {}
    try:
        with (root / "paper" / e["name"] / "journal.csv").open(encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                if r.get("date"):
                    by[r["date"].strip()[:10]] = r
    except (OSError, csv.Error):
        return []
    out, prev = [], None
    for d in sorted(by):
        eq = _num(by[d].get("equity"))
        if eq is not None and prev:
            out.append((d, eq / prev - 1, int((_num(by[d].get("turnover")) or 0.0) > TRADE_TURNOVER)))
        prev = eq if eq is not None else prev
    return out


def genome_row(root: Path, key: str) -> dict | None:
    """The genome and its behaviour: the weekly factory's shadow file, else its last held-back row."""
    m = notify.read_json(root / "factory" / "shadow" / f"{key}.json")
    if isinstance(m, dict) and isinstance(m.get("genome"), dict):
        return {"genome": m["genome"], "behaviour": (m.get("holdout") or {}).get("behaviour")}
    rows = [h for h in ladder._jsonl(root / "factory" / "holdout.jsonl") if h.get("key") == key]
    return rows[-1] if rows and isinstance(rows[-1].get("genome"), dict) else None


def factory_ctx(cache: dict):
    """The weekly factory's context on the long panel, loaded once a run (the job holds the heavy lock)."""
    if "ctx" not in cache:
        from .. import history
        from ..factory import build
        cache["ctx"] = build.make_ctx(history.load_long_panel())
    return cache["ctx"]


def step_genome(root: Path, e: dict, cache: dict) -> list[tuple[str, float, int]]:
    """The weekly factory's shadow journal (net at 35 bps, turnover) when it runs one, else the genome re-simulated
    with the backtest's fills as factory.shadow.update does."""
    key = e["key"]
    p = root / "factory" / "shadow" / f"{key}.csv"
    if p.exists():
        with p.open(encoding="utf-8", newline="") as f:
            return [(r["date"], _num(r.get("net_ret")), int((_num(r.get("turnover")) or 0.0) > TRADE_TURNOVER))
                    for r in csv.DictReader(f) if r.get("date")]
    g = genome_row(root, key)
    if g is None:
        return []
    from ..factory import build
    c = factory_ctx(cache)
    gross, tov, _ = build.run(c, g["genome"])
    n35 = build.net(gross, tov, build.COSTS["35bps"])
    days = [datetime.fromtimestamp(int(x) / 1e6, timezone.utc).strftime("%Y-%m-%d") for x in c.days]
    return [(days[t], float(n35[t]), int((tov[t - 1] if t else 0.0) > TRADE_TURNOVER)) for t in range(c.T)]


def step_f2(root: Path, e: dict, cache: dict) -> list[tuple[str, float, int]]:
    """F2's shadow wallet: the day's return of equity_eur, a trade when orders grows."""
    out, prev, orders = [], None, None
    try:
        with (root / "factory" / "small" / "shadow" / f"{e['key']}.csv").open(encoding="utf-8", newline="") as f:
            rows = [r for r in csv.DictReader(f) if r.get("date")]
    except (OSError, csv.Error):
        return []
    for r in rows:
        eq, o = _num(r.get("equity_eur")), _num(r.get("orders"))
        if eq is not None and prev:
            out.append((r["date"], eq / prev - 1, int(o is not None and orders is not None and o > orders)))
        prev, orders = (eq if eq is not None else prev), (o if o is not None else orders)
    return out


def step_rule(root: Path, e: dict, cache: dict) -> list[tuple[str, float, int]]:
    """The realistic paper ledger as the ladder reads it: a day is a date with any row of the judged rules, its return
    the sum of the rule's entry returns, its trades its entries."""
    paper = root / "paper" / "pumpfun_rt"
    rows, _ = ladder._rows(paper / "ledger.csv", ladder.PF_RULES)
    fails, _ = ladder._rows(paper / "failed.csv", ladder.PF_RULES)
    days = {ladder._day(int(r["signal_ms"])) for r in rows if str(r.get("signal_ms") or "").isdigit()}
    es, _ = ladder.pf_entries([r for r in rows if r.get("rule") == e["name"]],
                              [x for x in fails if x.get("rule") == e["name"]], ladder.PF_REAL_FROM_MS)
    by: dict[str, list[float]] = {}
    for t, r in es:
        by.setdefault(ladder._day(t), []).append(r)
    return [(d, float(sum(by.get(d, []))), len(by.get(d, []))) for d in sorted(days)]


STEPPERS = {"book": step_book, "weekly": step_genome, "F2": step_f2, "pumpfun": step_rule}


def shadow_missing(root: Path, e: dict) -> str | None:
    """Why this candidate's shadow cannot run (None: it can)."""
    s = source(e["id"])
    if s == "F2" and (root / "factory" / "small" / "shadow" / f"{e.get('key')}.csv").exists():
        return None
    if s == "weekly" and genome_row(root, e.get("key") or "") is None \
            and not (root / "factory" / "shadow" / f"{e.get('key')}.csv").exists():
        return "no genome for its key in factory/holdout.jsonl or factory/shadow"
    if s == "F2" or s not in STEPPERS:
        return SHADOW_MISSING.get(s, f"no shadow tool for {s}")
    return None


def look_missing(cid: str) -> str | None:
    """Why this candidate's lockbox look cannot be made (None: it can)."""
    s = source(cid)
    return LOOK_MISSING.get(s) or (None if s in LOOKERS else f"no lockbox tool for {s}")


# ---------------------------------------------------------------- each kind's one look

def factory_look(root: Path, e: dict) -> dict | None:
    """A look the weekly factory already made for the key or its behaviour: the one look (R6), adopted."""
    from ..factory import ledger
    beh = e.get("behaviour")
    mine = [x for x in ledger.lockbox_looks() if x.get("key") == e.get("key") or (beh and x.get("behaviour") == beh)]
    return mine[0] if mine else None


def ready_genome(root: Path, e: dict, cache: dict) -> str | None:
    if factory_look(root, e) is not None:
        return None
    from ..factory import evaluate
    if genome_row(root, e["key"]) is None:
        return "no genome for its key"
    n = int(evaluate.windows(factory_ctx(cache))["lockbox"].sum())
    return None if n >= evaluate.LOCKBOX_MIN_DAYS else f"the lockbox holds {n} of {evaluate.LOCKBOX_MIN_DAYS} days"


def genome_look(c, g: dict, pool: dict) -> dict:
    """The genome from 2026-07-01 on, net at 35 bps, its daily excess over BTC and ETH bought half and half at the
    lockbox's first close and held; DSR (higher is better) of the excess over every look so far and this one."""
    from ..factory import build, evaluate, ledger
    lb = evaluate.windows(c)["lockbox"]
    gross, tov, _ = build.run(c, g)
    x35 = build.net(gross, tov, build.COSTS["35bps"])[lb]
    P = c.P
    v = 0.5 * np.cumprod(1 + np.nan_to_num(P.ret[:, P.btc])[lb]) \
        + 0.5 * np.cumprod(1 + np.nan_to_num(P.ret[:, P.names.index("ETHUSDT")])[lb])
    bench = v / np.concatenate([[1.0], v[:-1]]) - 1
    ex = x35 - bench
    n = len(ledger.lockbox_looks()) + 1
    day = lambda us: datetime.fromtimestamp(int(us) / 1e6, timezone.utc).strftime("%Y-%m-%d")  # noqa: E731
    return {"lockbox_from": day(c.days[lb][0]), "lockbox_to": day(c.days[lb][-1]), "lockbox_days": int(lb.sum()),
            "lockbox_sharpe": evaluate.sharpe(x35), "lockbox_excess_sharpe": evaluate.sharpe(ex),
            "bench_sharpe": evaluate.sharpe(bench), "looks": n, "dsr": ledger.deflated_excess(ex, pool, n=n)}


def look_genome(root: Path, e: dict, cache: dict, now: int) -> dict:
    """The factory's look adopted, else a new one logged in factory/lockbox.jsonl before it is used; judged by the
    ladder's step 4 (look made, against BTC and ETH held, DSR at least LOCKBOX_BAR)."""
    from ..factory import ledger
    x = factory_look(root, e)
    if x is None:
        g = genome_row(root, e["key"])
        res = genome_look(factory_ctx(cache), g["genome"], ledger.Ledger().pool())
        x = ledger.log_look({"factory": NAME, "date": ladder._day(now), "key": e["key"], "behaviour": e.get("behaviour"),
                             "name": e["name"], "benchmark": "btc_eth", **res})
    else:
        x = {**x, "adopted": True}
    conds = ladder.lockbox({"bench": "crypto", "key": e["key"], "behaviour": e.get("behaviour")},
                           {"looks": ledger.lockbox_looks()})
    return {"result": x, "conditions": conds}


def look_rule(root: Path, e: dict, cache: dict, now: int) -> dict:
    """The ladder's step 4 for a rule (T8's e-process on the day sums from PF_FRESH_FROM on), read once."""
    pf = ladder.pf_context(root, now)
    x = pf["rules"].get(e["name"]) or {}
    return {"result": {k: x.get(k) for k in ("entries", "e_fresh", "fresh_day", "mean")},
            "conditions": ladder.pf_lockbox({"name": e["name"]}, {"pf": pf})}


LOOKERS = {"weekly": (ready_genome, look_genome, lambda root, e: factory_look(root, e) is not None),
           "pumpfun": (lambda root, e, cache: None, look_rule, None)}


def log_dev_looks(root: Path) -> list[dict]:
    """DEV_LOOKS into the lockbox's log (once per key, numbered after the looks there) and R5's registry."""
    from .. import metrics
    metrics.register([{"id": f"promote:lockbox:dev:{x['key']}", "family": "factory", "n": 1, "sharpe": None,
                       "source": PREREG} for x in DEV_LOOKS])
    p = root / "factory" / "lockbox.jsonl"
    have = ladder._jsonl(p)
    new = [x for x in DEV_LOOKS if x["key"] not in {y.get("key") for y in have}]
    for i, x in enumerate(new):
        append_line(p, {"look": len(have) + i + 1, **x})
    return new


def look_once(root: Path, e: dict, lookers: dict, cache: dict, now: int, log=notify.say) -> str:
    """The one lockbox look of a candidate: refused when the id has any line, waits (no claim) while not ready, else
    claim, trial, look, result line, then the result read back. Returns what happened."""
    from .. import metrics
    cid = e["id"]
    if cid in read_looks(root):
        return "refused: looked at before"
    tool = lookers.get(source(cid))
    if tool is None:
        e["look"] = f"missing tool: {look_missing(cid) or 'none for its kind'}"
        return "missing tool"
    ready, look, adopted = tool
    wait = ready(root, e, cache)
    if wait:
        e["look"] = f"not ready: {wait}"
        return "waiting"
    append_line(looks_path(root), {"id": cid, "claimed_ms": now, "date": ladder._day(now)})
    if not (adopted and adopted(root, e)):
        metrics.register([{"id": f"promote:lockbox:{cid}", "family": e.get("family") or "hand", "n": 1, "sharpe": None,
                           "source": PREREG}])
    try:
        out = look(root, e, cache, now)
        res, conds = out["result"], [c for c in out["conditions"] if isinstance(c, dict)]
    except Exception as x:  # noqa: BLE001 - the claim stands: a look that died is a fail
        res, conds = {"error": f"{type(x).__name__}: {x}"}, []
    append_line(looks_path(root), {"id": cid, "date": ladder._day(now), "ms": now, "result": res, "conditions": conds,
                                   "pass": bool(conds) and all(c.get("ok") is True for c in conds)})
    done = read_looks(root)[cid]["done"]                       # written, then read
    e.update(status="passed" if done["pass"] else "failed", look=look_text(read_looks(root)[cid]))
    log(f"promote: lockbox {cid} {e['status']}")
    return e["status"]


def look_text(x: dict | None) -> str:
    if x is None:
        return "not looked yet"
    d = x["done"]
    if d is None:
        return f"claimed {ladder._day(int(_num(x.get('claimed_ms')) or 0))}, no result written: final fail"
    if d.get("pass"):
        return f"passed on {d.get('date')}"
    bad = [c for c in d.get("conditions") or [] if c.get("ok") is not True]
    return f"failed on {d.get('date')} (final): " + ("; ".join(f"{c.get('label')}: {c.get('value')}" for c in bad)
                                                    or str((d.get("result") or {}).get("error") or "no conditions"))


# ---------------------------------------------------------------- the hand-over

def venue(e: dict) -> tuple[str, str]:
    if e.get("name") in ladder.NEUTRAL_BOOKS:
        return NEUTRAL
    return VENUE.get(str(e.get("study") or ""), SPOT)


def live_ready(root: Path, sh: dict[str, dict], looks: dict[str, dict], now: int) -> dict:
    """The step 4 passes only, from the result lines, an equal share of BUDGET_EUR each."""
    ok = [(cid, x["done"]) for cid, x in looks.items() if x["done"] and x["done"].get("pass") is True and cid in sh]
    share = math.floor(BUDGET_EUR * 100 / len(ok)) / 100 if ok else 0.0
    out = []
    for cid, d in sorted(ok, key=lambda t: t[0]):
        e = sh[cid]
        v, inst = venue(e)
        ev = ["reports/ladder/latest.json", "promotions/shadows.json", shadow_rel(cid), "promotions/lockbox.jsonl"]
        ev += [p for p in (e.get("journal"),) if p] + (["factory/lockbox.jsonl"] if source(cid) == "weekly" else [])
        out.append({"id": cid, "name": e.get("name"), "kind": e.get("kind"), "study": e.get("study"), "venue": v,
                    "instrument": inst, "share_eur": share, "date": d.get("date"), "evidence": ev})
    return {"generated": ladder._day(now), "updated_ms": now, "budget_eur": BUDGET_EUR, "prereg": PREREG,
            "candidates": out}


def card(new: list[dict]) -> notify.Card:
    return notify.Card("🚦", "Lockbox bestanden: bereit für Stufe 5", None,
                       [notify.Line(f"{c['name']} ({c['venue']}, {c['instrument']}), Anteil {c['share_eur']:.2f} EUR "
                                    f"von {BUDGET_EUR:g}") for c in new],
                       "promotions/live_ready.json, nichts handelt damit in A4")


# ---------------------------------------------------------------- what the ladder shows

def state(root: Path) -> dict:
    """What the ladder reads: the registry, each shadow's record, the looks."""
    sh = read_shadows(root)
    return {"shadows": sh, "records": {cid: record(root, cid, e) for cid, e in sh.items()}, "looks": read_looks(root),
            "ready": notify.read_json(ready_path(root))}


def summary(st: dict) -> dict:
    """The ladder report's promotions: each shadow with its days, trades, look; the hand-over's ids."""
    rows = []
    for cid, e in sorted(st["shadows"].items()):
        r = st["records"].get(cid) or {}
        rows.append({"id": cid, "name": e.get("name"), "kind": e.get("kind"), "status": e.get("status"),
                     "start_day": e.get("start_day"), "days": r.get("days", 0), "trades": r.get("trades", 0),
                     "before": r.get("before"), "why": e.get("why") or "", "look": look_text(st["looks"].get(cid))
                     if cid in st["looks"] else (e.get("look") or "not looked yet"), "path": r.get("path")})
    rd = st.get("ready") if isinstance(st.get("ready"), dict) else {}
    return {"prereg": PREREG, "shadows": rows, "need_days": SHADOW_DAYS, "need_trades": SHADOW_TRADES,
            "live_ready": [{k: c.get(k) for k in ("id", "name", "venue", "instrument", "share_eur", "date")}
                           for c in rd.get("candidates") or [] if isinstance(c, dict)],
            "counts": {s: sum(1 for x in rows if x["status"] == s)
                       for s in ("active", "missing_tool", "passed", "failed")}}


# ---------------------------------------------------------------- the daily run

def run(root: Path | None = None, now: int | None = None, build=None, steppers: dict | None = None,
        lookers: dict | None = None, poster=None, publish: bool = True, log=notify.say) -> dict:
    """build() gives the ladder (ladder.build on root); steppers and lookers replace each kind's tools (tests)."""
    from .. import metrics
    root = Path(root) if root is not None else notify.data_root()
    now = now or notify.clock_ms()
    build = build or (lambda: ladder.build(root, now))
    steppers = STEPPERS if steppers is None else steppers
    lookers = LOOKERS if lookers is None else lookers
    cache: dict = {}
    log_dev_looks(root)
    sh = read_shadows(root)
    rows = build()["rows"]
    new = []
    for r in rows:                                            # 2 -> 3: one shadow per id, ever
        if r.get("step", 0) >= 2 and r["id"] not in sh:
            s = source(r["id"])
            e = {"id": r["id"], "name": r.get("name"), "kind": r.get("kind"), "study": r.get("study") or "",
                 "family": r.get("family") or "hand", "start_day": ladder._day(now), "start_ms": now,
                 "status": "active", "rows": 0, "digest": digest([])}
            if s in ("weekly", "F2", "G2"):
                e["key"] = r["id"].split(":", 1)[1]
            if s == "book":
                e["journal"] = f"paper/{r.get('name')}/journal.csv"
            if s == "weekly":
                e["behaviour"] = (genome_row(root, e["key"]) or {}).get("behaviour")
            sh[r["id"]] = e
            new.append({"id": f"promote:shadow:{r['id']}", "family": e["family"], "n": 1, "sharpe": None,
                        "source": PREREG})
    if new:
        metrics.register(new)                                 # before any shadow day is written
    for e in sh.values():
        if e.get("status") in ("active", "missing_tool"):
            why = shadow_missing(root, e)
            e.update(status="missing_tool" if why else "active", why=why or "")
    write_shadows(root, sh)
    stepped = {}
    for cid, e in sh.items():
        if e["status"] == "active" and source(cid) in steppers:
            stepped[cid] = append(root, cid, e, steppers[source(cid)](root, e, cache), now)
    write_shadows(root, sh)

    by = {r["id"]: r for r in build()["rows"]}                # 3 -> 4: the ladder's step 3 and the shadow's own
    looks = read_looks(root)
    done = []
    for cid, e in sh.items():
        if cid in looks:
            e.update(status="passed" if (looks[cid]["done"] or {}).get("pass") is True else "failed",
                     look=look_text(looks[cid]))
            continue
        if e["status"] != "active":
            continue
        rec = record(root, cid, e)
        if rec["days"] < SHADOW_DAYS or rec["trades"] < SHADOW_TRADES or not rec["before"] \
                or (by.get(cid) or {}).get("step", 0) < 3:
            e["look"] = "not looked yet: " + (f"{rec['days']} of {SHADOW_DAYS} days, {rec['trades']} of "
                                              f"{SHADOW_TRADES} trades" if rec["before"] else rec["why"])
            continue
        done.append((cid, look_once(root, e, lookers, cache, now, log)))
    write_shadows(root, sh)

    looks = read_looks(root)                                  # 4: the hand-over, step 4 passes only
    old = notify.read_json(ready_path(root))
    had = {c.get("id") for c in (old or {}).get("candidates") or [] if isinstance(c, dict)} if isinstance(old, dict) \
        else set()
    rd = live_ready(root, sh, looks, now)
    notify.write_json(ready_path(root), rd)
    fresh = [c for c in rd["candidates"] if c["id"] not in had]
    sent = notify.send("studies", [card(fresh)], now=now, poster=poster) if fresh else None
    if publish:
        ladder.publish(ladder.build(root, now))
    out = {"new": [x["id"][len("promote:shadow:"):] for x in new], "stepped": stepped, "looks": done,
           "live_ready": [c["id"] for c in rd["candidates"]], "sent": sent}
    log(f"promote: {len(sh)} shadows, new {out['new'] or 'none'}, looks {done or 'none'}, "
        f"live_ready {out['live_ready'] or 'none'}")
    return out


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--print" in argv:
        notify.say(json.dumps(summary(state(notify.data_root())), indent=1, ensure_ascii=False))
        return 0
    run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
