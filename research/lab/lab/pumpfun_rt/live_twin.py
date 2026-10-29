"""Live twin (results/pumpfun_live_twin_prereg.md): every live pump.fun trade replayed through the realistic executor,
and live minus twin per trade split into its parts. PAPER ONLY and read only on everything live: reads the live
ledger, orders and measured fills and the recorded stream; changes nothing a live bot, its sizing, a wallet or the
engine reads.

    python -m lab.pumpfun_rt.live_twin [--live DIR] [--root DIR] [--out results/pumpfun_live_twin.md]
    (loads whole stream days: run under flock /run/lock/pythia/heavy.lock)

Each closed live trade (ledger.csv, live modes) is signalled again at its signal_ms with its rule (filters taken off,
P_pool0_wait's pool wait and the exits unchanged) and the stake the live bot sent, on one engine fed with the recorded
days of the live coins only (slot-timed from every row of the day, as sim.day_events); a coin the record holds only
later (it lags the live feed) is signalled when the record has it, the live times moved by that lag (TwinBook).
One realistic.Book per judged UTC day,
each on realistic.fit of the live orders of every other day (leave one day out). A trade without a twin gets its
reason (coin not recorded, no pool state in the record, stream gap, P1 taint, open at the end). Live minus twin, in
points a trade, splits exactly into entry latency, entry price, exit decision time, exit price, fees and failed buys
(parts()); day-clustered percentile bootstrap bands. Five trials in R5's registry, family pumpfun, counted only.
"""

from __future__ import annotations

import argparse
import bisect
import collections
import dataclasses
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .. import metrics
from . import curve as C
from . import events as E
from . import pipeline as P
from . import realistic as R
from . import sim

PREREG = "results/pumpfun_live_twin_prereg.md"
OUT = Path(__file__).resolve().parents[2] / "results" / "pumpfun_live_twin.md"
RULES = ("P_pool0_wait", "P_cmig_model", "P_pool0")   # what the live bot ran
DRAWS, SEED = 2_000, 0
GAP_SHARE = 0.10                          # gaps of the trade's program over this share of its window: no twin
MAX_LAG_MS = 120_000                      # the record's lag behind the live signal looked for at most this long
POLL_MS = 100                             # how often the record is asked for a coin it does not hold yet
PARTS = ("latency", "entry", "exit_time", "exit", "fees", "failed")
PART_NAMES = {"latency": "entry latency", "entry": "entry price", "exit_time": "exit decision time",
              "exit": "exit price", "fees": "fees", "failed": "failed buys"}
NOT_RECORDED, NO_POOL, GAP, TAINT, OPEN = ("coin not recorded", "no pool state in the record", "stream gap",
                                           "P1 taint", "twin open at the end")
MISSES = (NOT_RECORDED, NO_POOL, GAP, TAINT, OPEN)
LIVE_MODES = ("test", "full")


def trials() -> list[dict]:
    return [{"id": f"pumpfun:live_twin:{k}", "family": "pumpfun", "n": 1, "sharpe": None, "source": PREREG}
            for k in ("total", "components", "by_day", "by_rule", "no_gap")]


def day_of(ms) -> str:
    return datetime.fromtimestamp(float(ms) / 1000, timezone.utc).strftime("%Y-%m-%d")


def _jsonl(p: Path) -> list[dict]:
    out = []
    try:
        with p.open(encoding="utf-8") as fh:
            for line in fh:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        pass
    return out


# ---------------------------------------------------------------- the live side

def live_trades(ledger: list[dict], orders: list[dict], measured: list[dict]) -> list[dict]:
    """The closed live trades of the live modes and rules, each with what the twin needs: stake_l (the buy as sent:
    its stake_l, else limit_l / (1 + SLIP_TOL), else the ledger's stake) and xdec_ms (the last sale's decision: the
    last sell fill's signal_ms, else the last sent sell, else exit_ms)."""
    f = R._f
    sent = [o for o in orders if o.get("what") == "sent"]
    sells = [m for m in measured if m.get("what") == "fill" and m.get("side") == "sell"]
    out = []
    for r in ledger:
        if r.get("mode") not in LIVE_MODES or r.get("rule") not in RULES:
            continue
        sig, land, ex, ret = (f(r.get(k)) for k in ("signal_ms", "land_ms", "exit_ms", "ret"))
        ep, xp = f(r.get("entry_price")), f(r.get("exit_price"))
        if None in (sig, land, ex, ret) or not r.get("mint"):
            continue
        mint = r["mint"]
        buy = [o for o in sent if o.get("side") == "buy" and o.get("mint") == mint
               and ((r.get("buy_sig") and o.get("sig") == r["buy_sig"]) or sig - 1_000 <= (f(o.get("t")) or 0) <= land)]
        buy.sort(key=lambda o: (o.get("sig") != r.get("buy_sig"), -(f(o.get("t")) or 0)))
        if buy and buy[0].get("stake_l"):
            stake, src = int(buy[0]["stake_l"]), "order"
        elif buy and buy[0].get("limit_l"):
            stake, src = int(int(buy[0]["limit_l"]) / (1 + C.SLIP_TOL)), "order"
        else:
            stake, src = int((f(r.get("stake_sol")) or 0) * C.LAMPORTS), "ledger"
        xs = [f(m.get("signal_ms")) for m in sells if m.get("mint") == mint
              and land <= (f(m.get("land_ms")) or 0) <= ex + 1 and f(m.get("signal_ms")) is not None]
        if not xs:
            xs = [f(o.get("t")) for o in sent if o.get("side") == "sell" and o.get("mint") == mint
                  and land <= (f(o.get("t")) or 0) <= ex + 1]
        out.append({"i": len(out), "rule": r["rule"], "mint": mint, "symbol": r.get("symbol") or "",
                    "day": day_of(sig), "signal_ms": sig, "land_ms": land, "exit_ms": ex,
                    "xdec_ms": max(xs) if xs else ex, "entry_price": ep, "exit_price": xp, "ret": ret,
                    "stake_l": stake, "stake_src": src, "exit_why": r.get("exit_why")})
    return out


def lodo_fits(measured: list[dict], days) -> dict[str, R.Fit]:
    """Leave one day out: day -> realistic.fit of every measured row of the live modes whose UTC day is another (the
    whole record less that day, no FIT_DAYS window)."""
    rows = [m for m in measured if m.get("t") is not None and m.get("mode") in LIVE_MODES]
    now = max((int(m["t"]) for m in rows), default=0) + 1
    span = now // R.DAY_MS + 2                                   # every row since the epoch is inside the window
    return {d: R.fit([m for m in rows if day_of(m["t"]) != d], now, days=span) for d in sorted(set(days))}


# ---------------------------------------------------------------- the replay

class TwinExec(R.RealExecutor):
    """The realistic executor, unchanged; it also keeps the price path of its coins (m(t) of parts())."""

    def __init__(self, model: R.Model, path: dict):
        super().__init__(model)
        self.path = path

    def on_trade(self, table: str, row: dict) -> None:
        ps = self.path.get(row.get("mint"))
        if ps is not None:
            tok = self.pipe.eng.tokens.get(row["mint"])
            x = (float(row["t"]), tok.price()) if tok is not None else None
            if x is not None and (not ps or ps[-1] != x):         # the books share the path: once per trade
                ps.append(x)
        super().on_trade(table, row)


class TwinBook(R.Book):
    """One judged day's twins: force() signals a live trade again at its signal time on the record's clock; the
    outcome by trade. The record lags the live feed (the collector's stream hands a migration over 0 to 20 s after
    the live bot signalled on it): a coin the record does not hold yet at the live signal (a pool rule: not migrated
    yet) is asked again every POLL_MS up to MAX_LAG_MS, and the twin signals when the record has it, the lag kept as
    the trade's offset (every live time is moved by it onto the record's clock)."""

    def __init__(self, eng, strategies, executor, name: str):
        super().__init__(eng, strategies, executor, name=name, limits=R.R1_CALIB_LIMITS)
        self.twin: dict[int, dict] = {}       # live trade i -> {"pid", "offset"} or {"skip", "offset"} or {"miss"}
        self.done: dict[int, dict] = {}       # pid -> the closed position (tokens, lamports, times)
        self.fails: dict[int, dict] = {}      # pid -> the failed buy
        self.tr: dict[int, dict] = {}         # live trade i -> the trade, its offset once signalled
        self.wait_i: dict[tuple, int] = {}    # (strategy, mint) -> the live trade whose signal waits for the pool
        self._cur = None
        self._why = None

    def skip(self, name: str, mint: str, why: str) -> None:
        self._why = why
        i = self.wait_i.pop((name, mint), None) if why.startswith("no pool state") else None
        if i is not None:                                     # P_pool0_wait's wait ran out on the record
            self.twin[i] = {"miss": NO_POOL}
        super().skip(name, mint, why)

    def force(self, at: float, tr: dict) -> None:
        s = self.strats[tr["strategy"]]
        tok = self.eng.tokens.get(tr["mint"])
        if tok is None or (s.family == "E" and tok.pool is None):
            if at + POLL_MS - tr["signal_ms"] <= MAX_LAG_MS:
                self.eng.push(at + POLL_MS, "pipe", (self, "force", tr))
            else:
                self.twin[tr["i"]] = {"miss": NOT_RECORDED if tok is None else NO_POOL}
            return
        self.tr[tr["i"]] = {**tr, "offset": at - tr["signal_ms"]}
        self._cur = tr["i"]
        try:
            self.signal(s, tok, at)
        finally:
            self._cur = None

    def signal(self, s: P.Strategy, tok, t: float) -> None:
        i = self._cur if self._cur is not None else self.wait_i.pop((s.name, tok.mint), None)
        if i is None:                                         # the twin strategies signal only through force()
            return
        tr = self.tr[i]
        if s.family == "E" and (not tok.pq or not tok.pb) and not s.p.get("wait_pool_s"):
            self.twin[i] = {"miss": NO_POOL}
            return
        self.risk[s.name].limits = dataclasses.replace(R.R1_CALIB_LIMITS, stake_sol=(tr["stake_l"] + 0.5) / C.LAMPORTS)
        self._why, n0 = None, self.eng.next_pid
        super().signal(s, tok, t)
        if self.eng.next_pid > n0:
            self.twin[i] = {"pid": n0, "offset": tr["offset"]}
        elif s.name in self.waiting.get(tok.mint, {}):
            self.wait_i[(s.name, tok.mint)] = i
        else:
            self.twin[i] = {"skip": self._why or "no buy", "offset": tr["offset"]}

    def buy_failed(self, pid: int, at: float, why: str, fee_l: int) -> None:
        p = self.pos.get(pid)
        if p is not None:
            self.fails[pid] = {"why": why, "fee_l": int(fee_l), "at": at, "stake_l": p["stake_l"]}
        super().buy_failed(pid, at, why, fee_l)

    def _close(self, p: dict, at: float) -> None:
        self.done[p["pid"]] = {k: p.get(k) for k in ("tokens", "cost_l", "proceeds_l", "fees_l", "stake_l", "land_ms",
                                                     "exit_signal_ms", "signal_ms", "exit_why", "venue")} | {"at": at}
        super()._close(p, at)


def twin_strategy(rule: str, day: str) -> P.Strategy:
    """The rule as the twin trades it: entry only by force(), no filter, the stake from Risk, P_pool0_wait's wait
    for the pool on the record's clock and the exits as they are; named per judged day, its latency key the
    rule's (P.base_name)."""
    s = P.BY_NAME[rule]
    return dataclasses.replace(s, name=f"{rule}@{day}", entry="twin", flt={}, p={**s.p, "base": rule},
                               stake_sol=math.inf)


class Replay:
    """One engine, one TwinBook per judged day on its leave-one-day-out fit, every live trade's forced signal
    queued. feed() takes the recorded events in chain order (the gap rows kept by program), finish() the twins."""

    def __init__(self, trades: list[dict], fits: dict[str, R.Fit]):
        self.eng = sim.Engine([], decisions=False)
        self.trades = trades
        self.path: dict[str, list] = {t["mint"]: [] for t in trades}
        self.gaps: dict[str, list] = collections.defaultdict(list)
        self.books: dict[str, TwinBook] = {}
        for d in sorted({t["day"] for t in trades}):
            model = R.Model(fits[d], R.LiveConfig())
            strats = [twin_strategy(r, d) for r in sorted({t["rule"] for t in trades if t["day"] == d})]
            for s in strats:
                self.eng.rule_costs[s.name] = R.RealCosts(model=model)
            self.books[d] = self.eng.add_pipe(TwinBook(self.eng, strats, TwinExec(model, self.path), name=f"twin@{d}"))
        self.last = 0.0
        for t in trades:
            self.eng.push(t["signal_ms"], "pipe", (self.books[t["day"]], "force",
                                                   {**t, "strategy": f"{t['rule']}@{t['day']}"}))

    def feed(self, table: str, row: dict) -> None:
        if table == "other" and row.get("kind") == "gap":
            self.gaps[row.get("user") or ""].append((float(row.get("t0") or row["t"]), float(row["t"])))
        sim.feed_row(self.eng, table, row)
        self.last = max(self.last, float(row.get("t") or 0))

    def finish(self, t_end: float | None = None) -> list[dict]:
        self.eng.finish((t_end or self.last) + 1)
        return [outcome(t, self.books[t["day"]], self.path.get(t["mint"]) or [], self.gaps) for t in self.trades]


# ---------------------------------------------------------------- one trade: its twin and the parts

def m_at(path: list, t: float) -> float | None:
    """The coin's price at the first recorded trade at or after t, else the last before: the state at the end of that
    trade's slot (a slot's rows share its time; the first trades of a fresh pool's slot carry states up to 20 times
    off the slot's close, KIMCHICAT 2026-10-24)."""
    if not path:
        return None
    ts = [x[0] for x in path]
    i = bisect.bisect_left(ts, t)
    return path[bisect.bisect_right(ts, ts[i]) - 1][1] if i < len(path) else path[-1][1]


def g(e: float, x: float) -> float:
    return x / e - 1


def parts(lv: dict, tw: dict, path: list) -> dict:
    """Live minus twin of one trade in points (x 100), split exactly (results/pumpfun_live_twin_prereg.md): a twin
    that bought gets entry latency, entry price, exit decision time, exit price and fees; one that did not, failed
    buys. lv: entry_price, exit_price, ret, land_ms, xdec_ms; tw: bought, ret, and when bought E, X, land_ms,
    xdec_ms. A price of the path missing or 0 leaves that move at 1."""
    out = dict.fromkeys(PARTS, 0.0)
    total = (lv["ret"] - tw["ret"]) * 100
    if not tw["bought"] or not lv.get("entry_price") or not lv.get("exit_price"):
        out["failed" if not tw["bought"] else "fees"] = total
        return out | {"total": total}

    def move(a, b):
        ma, mb = m_at(path, a), m_at(path, b)
        return ma / mb if ma and mb else 1.0
    el, xl, et, xt = lv["entry_price"], lv["exit_price"], tw["E"], tw["X"]
    e1 = et * move(lv["land_ms"], tw["land_ms"])
    x1 = xt * move(lv["xdec_ms"], tw["xdec_ms"])
    out["latency"] = (g(e1, xt) - g(et, xt)) * 100
    out["entry"] = (g(el, xt) - g(e1, xt)) * 100
    out["exit_time"] = (g(el, x1) - g(el, xt)) * 100
    out["exit"] = (g(el, xl) - g(el, x1)) * 100
    out["fees"] = ((lv["ret"] - g(el, xl)) - (tw["ret"] - g(et, xt))) * 100
    return out | {"total": total}


def _cover(gaps: list, lo: float, hi: float) -> float:
    """ms of [lo, hi] under the gaps (overlaps merged)."""
    xs = sorted((max(lo, a), min(hi, b)) for a, b in gaps if b > lo and a < hi)
    n, end = 0.0, lo
    for a, b in xs:
        a = max(a, end)
        if b > a:
            n += b - a
            end = b
    return n


def gap_why(moments: list, lo: float, hi: float, gaps: list) -> tuple[bool, float]:
    """(a gap covers a moment the replay needs, the share of [lo, hi] under the gaps)."""
    hit = any(a <= m1 and b >= m0 for m0, m1 in moments for a, b in gaps)
    return hit, _cover(gaps, lo, hi) / max(1.0, hi - lo)


def outcome(lv: dict, book: TwinBook, path: list, gaps: dict) -> dict:
    """A live trade's twin (or the reason it has none) and live minus twin by part."""
    out = {k: lv[k] for k in ("i", "rule", "mint", "symbol", "day", "signal_ms", "ret", "stake_l", "stake_src")}
    tw = book.twin.get(lv["i"])
    if tw is None or tw.get("miss"):
        return out | {"twin": False, "why": (tw or {}).get("miss") or NOT_RECORDED}
    off = tw.get("offset") or 0.0
    out["offset_ms"] = off
    lv = {**lv, **{k: lv[k] + off for k in ("signal_ms", "land_ms", "xdec_ms", "exit_ms")}}   # the record's clock
    pool = P.BY_NAME[lv["rule"]].family == "E"
    gp = gaps.get(E.PUMP_AMM if pool else E.PUMP, [])
    w = R.FILL_WAIT_MS
    moments = [(lv["signal_ms"], lv["signal_ms"]), (lv["land_ms"], lv["land_ms"] + w), (lv["xdec_ms"], lv["xdec_ms"]),
               (lv["exit_ms"], lv["exit_ms"] + w)]
    hi = lv["exit_ms"]
    pid = tw.get("pid")
    d, f = book.done.get(pid), book.fails.get(pid)
    if d is not None:
        moments += [(d["land_ms"], d["land_ms"] + w), (d["exit_signal_ms"] or d["at"],) * 2, (d["at"], d["at"] + w)]
        hi = max(hi, d["at"])
    elif f is not None:
        moments.append((f["at"], f["at"] + w))
    hit, share = gap_why(moments, lv["signal_ms"], hi + w, gp)
    out["gap_share"] = share
    if hit or share >= GAP_SHARE:
        return out | {"twin": False, "why": GAP}
    if pid is not None and d is None and f is None:
        return out | {"twin": False, "why": OPEN}
    if d is not None:
        rec = next((r for r in book.closed if r.get("pid") == pid), {})
        if R.tainted(rec):
            return out | {"twin": False, "why": TAINT}
        e = (d["cost_l"] / C.LAMPORTS) / (d["tokens"] / C.TOKEN_UNIT) if d["tokens"] else None
        x = (d["proceeds_l"] / C.LAMPORTS) / (d["tokens"] / C.TOKEN_UNIT) if d["tokens"] else None
        t = {"bought": bool(e), "ret": (d["proceeds_l"] - d["cost_l"] - d["fees_l"]) / (d["stake_l"] or 1),
             "E": e, "X": x, "land_ms": d["land_ms"], "xdec_ms": d["exit_signal_ms"] or d["at"]}
        out.update(twin_ret=t["ret"], twin_land_ms=d["land_ms"], twin_exit_why=d["exit_why"], twin_how="bought")
    elif f is not None:
        t = {"bought": False, "ret": -f["fee_l"] / (f["stake_l"] or 1)}
        out.update(twin_ret=t["ret"], twin_how=f"buy failed: {f['why']}")
    else:
        t = {"bought": False, "ret": 0.0}
        out.update(twin_ret=0.0, twin_how=f"no buy: {tw.get('skip')}")
    return out | {"twin": True, "why": None, "no_gap": share == 0.0, "parts": parts(lv, t, path)}


# ---------------------------------------------------------------- the record

def coin_events(day: str, mints, root=None):
    """(table, row) of one recorded day for the given coins (and every gap row) in chain order, timed as
    sim.day_events: the slot time from every row of the day (the earliest receive time of the slot or a later
    one), a pool read never before its receive time, rows without a slot at their receive time; "recv_t" kept."""
    import polars as pl
    from . import store
    root = root or store.base()
    mints = list(mints)
    pairs, rows = [], []
    for o, tb in enumerate(sim.ORDER):
        d = root / tb / f"date={day}"
        for fp in (sorted(d.glob("*.parquet")) if d.is_dir() else ()):
            lf = pl.scan_parquet(fp)
            cols = lf.collect_schema().names()
            if "slot" in cols:
                pairs.append(lf.select(pl.col("slot").cast(pl.Int64), pl.col("t").cast(pl.Int64)).drop_nulls()
                             .group_by("slot").agg(pl.col("t").min()).collect())
            keep = pl.col("mint").is_in(mints).fill_null(False) if "mint" in cols else pl.lit(False)
            if tb == "other":
                keep = keep | (pl.col("kind") == "gap").fill_null(False)
            rows += [(o, tb, r) for r in lf.filter(keep).collect().to_dicts()]
    first: dict[int, int] = {}
    if pairs:
        ps = pl.concat(pairs).group_by("slot").agg(pl.col("t").min()).sort("slot", descending=True)
        ps = ps.with_columns(pl.col("t").cum_min())
        first = dict(zip(ps["slot"].to_list(), ps["t"].to_list()))
    keyed = []
    for n, (o, tb, r) in enumerate(rows):
        rt, slot = r.get("t") or 0, r.get("slot")
        ct = first.get(slot, rt) if slot is not None else rt
        if r.get("kind") == "pool_state":
            ct = max(ct, rt)
        keyed.append(((ct, slot is None, slot or 0, rt, r.get("tx") or 0, o, n), tb, {**r, "recv_t": rt, "t": ct}))
    keyed.sort(key=lambda k: k[0])
    for _, tb, r in keyed:
        yield tb, r


def replay(trades: list[dict], fits: dict, root=None, log=print) -> list[dict]:
    """Every live trade's outcome on the recorded days from the first to the day of the last live exit."""
    from . import store
    if not trades:
        return []
    last = day_of(max(t["exit_ms"] for t in trades))
    days = [d for d in store.days(root) if d <= last]
    rp = Replay(trades, fits)
    mints = sorted({t["mint"] for t in trades})
    for d in days:
        n = 0
        for tb, r in coin_events(d, mints, root):
            rp.feed(tb, r)
            n += 1
        log(f"live twin: {d} {n:,} events of {len(mints)} coins")
    return rp.finish()


# ---------------------------------------------------------------- the numbers

def _mean(xs) -> float | None:
    return float(np.mean(xs)) if len(xs) else None


def stats(res: list[dict], draws: int = DRAWS, seed: int = SEED) -> dict:
    """Over the twinned trades: n, mean and median of live minus twin, each part's mean, and day-clustered 95 %
    percentile bootstrap bands (days drawn with replacement, the pooled trades' mean), the same draws for all."""
    tw = [r for r in res if r.get("twin")]
    out = {"n": len(tw), "days": sorted({r["day"] for r in tw})}
    if not tw:
        return out | {"mean": None, "median": None}
    tot = np.array([r["parts"]["total"] for r in tw])
    out.update(mean=float(tot.mean()), median=float(np.median(tot)),
               live=float(np.mean([r["ret"] for r in tw]) * 100),
               twin=float(np.mean([r["twin_ret"] for r in tw]) * 100))
    for k in PARTS:
        out[k] = float(np.mean([r["parts"][k] for r in tw]))
    out["sum"] = sum(out[k] for k in PARTS)
    by = collections.defaultdict(list)
    for j, r in enumerate(tw):
        by[r["day"]].append(j)
    days = list(by)
    rng = np.random.default_rng(seed)
    cols = {"total": tot, **{k: np.array([r["parts"][k] for r in tw]) for k in PARTS}}
    bs = collections.defaultdict(list)
    for _ in range(draws):
        idx = np.concatenate([by[days[i]] for i in rng.integers(0, len(days), len(days))])
        for k, v in cols.items():
            bs[k].append(v[idx].mean())
    out["band"] = {k: [float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))] for k, v in bs.items()} \
        if len(days) > 1 else {}                              # one day: no band
    return out


def compute(res: list[dict]) -> dict:
    """The whole record, by day, by rule, the no-gap check, the misses and the haircut."""
    tw = [r for r in res if r.get("twin")]
    allst = stats(res)
    b = (allst.get("band") or {}).get("total")
    haircut = allst["mean"] if b and (b[0] > 0 or b[1] < 0) else None
    return {"n_live": len(res), "n_twin": len(tw), "all": allst,
            "by_day": {d: stats([r for r in res if r["day"] == d]) for d in sorted({r["day"] for r in res})},
            "by_rule": {k: stats([r for r in res if r["rule"] == k]) for k in RULES
                        if any(r["rule"] == k for r in res)},
            "no_gap": stats([r for r in tw if r.get("no_gap")]),
            "misses": collections.Counter((r["rule"], r["why"]) for r in res if not r.get("twin")),
            "how": collections.Counter((r.get("twin_how") or "").split(":")[0] for r in tw),
            "stake_src": collections.Counter(r["stake_src"] for r in res), "haircut": haircut,
            "offsets": [r.get("offset_ms") or 0.0 for r in tw]}


def _pt(x) -> str:
    return "n/a" if x is None else f"{x:+.1f}"


def _band(st: dict, k: str = "total") -> str:
    b = (st.get("band") or {}).get(k)
    return ("one day" if st.get("n") else "n/a") if not b else f"{b[0]:+.1f} to {b[1]:+.1f}"


def table_md(rows: list[tuple[str, dict]]) -> list[str]:
    md = ["| | twins | live | twin | live minus twin: mean | median | day band | "
          + " | ".join(PART_NAMES[k] for k in PARTS) + " | sum of parts |",
          "|---|---|---|---|---|---|---|" + "---|" * (len(PARTS) + 1)]
    for name, st in rows:
        if not st.get("n"):
            md.append(f"| {name} | 0 |" + " |" * (len(PARTS) + 7))
            continue
        md.append(f"| {name} | {st['n']} | {st['live']:+.1f} % | {st['twin']:+.1f} % | {_pt(st['mean'])} | "
                  f"{_pt(st['median'])} | {_band(st)} | " + " | ".join(_pt(st[k]) for k in PARTS)
                  + f" | {_pt(st['sum'])} |")
    return md


def markdown(c: dict, fits: dict) -> str:
    a = c["all"]
    md = ["# Live twin: every live pump.fun trade replayed through the realistic executor", "",
          f"Pre-registration `{PREREG}`. Read only: `<data>/live/pumpfun_rt` (ledger, orders, measured) and the "
          "recorded stream `<data>/pumpfun_rt`. Each live trade signalled again at its signal_ms with its rule and the "
          "stake it sent, through `realistic.RealExecutor` on the leave-one-day-out fit. Points a trade (live return "
          f"less twin return, x 100). Bands: day-clustered 95 % percentile bootstrap, {DRAWS:,} draws, seed {SEED}, "
          f"over {len(a.get('days') or [])} days. Five trials in R5's registry, family pumpfun, counted only "
          "(`pumpfun:live_twin:*`); no Sharpe, no DSR.", "",
          "Beyond the pre-registration, fixed after two earlier runs (the first: 30 twins, most misses \"coin not "
          "recorded\", live minus twin +2.1 points; the second, with the lag below: 66 twins, -2.5 points, the "
          "latency and entry price parts +76.7 and -76.6 from one trade): the record lags the live feed (a migration "
          "reaches the collector up to 25 s after the live bot signalled on it), so a coin the record does not hold "
          f"yet at the live signal (a pool rule: not migrated yet) is asked again every {POLL_MS} ms up to "
          f"{MAX_LAG_MS // 1000} s and the twin signals when the record has it, every live time moved by that lag "
          "onto the record's clock; P_pool0_wait keeps its 5 s wait for the pool's first trade on the record's "
          "clock (the record has no pool reads on these days, so without it every such coin would be \"no pool "
          "state\"); m(t) is the state at the end of the slot of the "
          "first trade at or after t (a slot's rows share its time; the first trades of a fresh pool's slot carry "
          "states up to 20 times off, KIMCHICAT 2026-10-24, which put +2,140 points into one trade's latency part "
          "and -2,141 into its entry price).", "",
          "## The answer", "",
          f"- Twins: {c['n_twin']} of {c['n_live']} live trades; every miss named below.",
          f"- Live minus twin: mean {_pt(a.get('mean'))} points a trade (day band {_band(a)}), median "
          f"{_pt(a.get('median'))}; live {_pt(a.get('live'))} %, twin {_pt(a.get('twin'))} % on the same trades.",
          "- Parts (mean points a trade): " + ", ".join(f"{PART_NAMES[k]} {_pt(a.get(k))} ({_band(a, k)})"
                                                         for k in PARTS)
          + f"; their sum {_pt(a.get('sum'))} against the total {_pt(a.get('mean'))}.",
          (f"- The day band excludes 0: paper books would need a haircut of {-c['haircut']:.1f} points a trade "
           f"(live minus twin {_pt(c['haircut'])}: each paper trade's return {_pt(c['haircut'])} points; proposed "
           "only, no book, gate or live file reads it)." if c["haircut"] is not None else
           "- The day band includes 0: no haircut is proposed on this record."), "",
          "## Live minus twin", "", *table_md([("all", a), ("no gap in the window (check)", c["no_gap"])]), "",
          "By day (UTC, the signal's):", "", *table_md(list(c["by_day"].items())), "",
          "By rule:", "", *table_md(list(c["by_rule"].items())), "",
          f"The record's lag: {sum(1 for x in c['offsets'] if x > 0)} of {len(c['offsets'])} twins signalled "
          f"after the live signal, median {np.median(c['offsets']) / 1000 if c['offsets'] else 0:.1f} s, at most "
          f"{max(c['offsets'], default=0) / 1000:.1f} s.", "",
          "Twin outcomes: " + ", ".join(f"{k} {v}" for k, v in sorted(c["how"].items())) + "; stakes from "
          + ", ".join(f"the {k} {v}" for k, v in sorted(c["stake_src"].items())) + ".", "",
          "## Live trades without a twin", "",
          f"{c['n_live'] - c['n_twin']} of {c['n_live']}. Coin not recorded: no creation row of it in the replayed "
          "days (the engine knows a coin only from its creation; the paper books miss it alike). No pool state in "
          "the record: no recorded pool trade within the rule's wait (P_pool0: at the signal) and no pool read on "
          "these days, where the live bot had its own. Stream gap: a gap of the trade's program over a moment the "
          f"replay needs or {GAP_SHARE * 100:.0f} % of its window.", "",
          "| rule | reason | trades |", "|---|---|---|"]
    md += [f"| {r} | {w} | {n} |" for (r, w), n in sorted(c["misses"].items(), key=lambda kv: (kv[0][0], -kv[1]))]
    md += ["", "## The leave-one-day-out fits", "", "| judged day | buy fills | sell fills | buy median s | "
           "sell median s | source |", "|---|---|---|---|---|---|"]
    for d, f in sorted(fits.items()):
        lv = f.live
        md.append(f"| {d} | {lv.get('buys')} | {lv.get('sells')} | {R.describe(f.buy)['median'] / 1000:.1f} | "
                  f"{R.describe(f.sell)['median'] / 1000:.1f} | "
                  + ", ".join(f"{k} {v}" for k, v in sorted((lv.get('source') or {}).items())) + " |")
    return "\n".join(md) + "\n"


def run(live_dir: Path, root: Path | None, out: Path, register: bool = True, log=print) -> dict:
    if register:
        metrics.register(trials())                            # before any number exists
    trades = live_trades(R.read_csv(live_dir / "ledger.csv"), _jsonl(live_dir / "orders.jsonl"),
                         _jsonl(live_dir / "measured.jsonl"))
    fits = lodo_fits(_jsonl(live_dir / "measured.jsonl"), [t["day"] for t in trades])
    res = replay(trades, fits, root, log)
    c = compute(res)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(markdown(c, fits), encoding="utf-8")
    log(f"live twin: {c['n_twin']} of {c['n_live']} twins, live minus twin {_pt(c['all'].get('mean'))} points "
        f"(day band {_band(c['all'])}) -> {out}")
    return {"trades": res, "compute": c}


def main(argv: list[str] | None = None) -> int:
    from .live_exec import data_dir
    ap = argparse.ArgumentParser(prog="lab.pumpfun_rt.live_twin", description=__doc__.split("\n")[0])
    ap.add_argument("--live", default=None)
    ap.add_argument("--root", default=None)
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--json", default=None, help="every trade's outcome as JSON here too")
    a = ap.parse_args(sys.argv[1:] if argv is None else argv)
    r = run(Path(a.live) if a.live else data_dir(), Path(a.root) if a.root else None, Path(a.out))
    if a.json:
        Path(a.json).write_text(json.dumps(r["trades"], default=float, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
