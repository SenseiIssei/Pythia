"""The live name categories of pump.fun coins and the entry rule on them (the owner, 2026-10-23: the live bot bought
MAJOR BIDEN, Apple twice, ChatGPT, IShowSpeed, DuckDuckGo, GTA6, TRUMP, MrBeast and SpaceX AI that day, most of
them -76 to -86 %, and match: words in the block list are whack-a-mole). This module classifies names and says why
a coin is not bought; it never buys, signs or sends anything.

LiveClassifier, in the live service (live_service.run, every EVERY_S): the normalised name and ticker of every new
plain coin (SOL curve, no mayhem mode) the stream saw created since the last run, with the same chunks, prompt,
schema and checks as the daily job (categorize.py) and through the same local chain (lab.ai.local: the owner's PC
through the relay when it is online, else the VPS model; AI2, results/categories_local_ai2_prereg.md; until
2026-10-24 the engine's metered endpoint); a name a local model classified before (the cache, this session) is not
asked again, its coin gets the name's category at once. Its answers go to the same cats.jsonl, a line per mint with
avail_ms (when the answer was written) and the model that answered, so a replay stays point in time and the daily
job skips these names. A run that failed (no model answered, an unreadable answer) is asked again with the next
one. The calls are logged every LOG_S and are in the status ("categories"); the day's cap PYTHIA_PF_CAT_USD_DAY
(USD_DAY, 1.00 USD) stays, a local call costs nothing.

CategoryGate (Pipeline.category; the live book's strategy, and in the collector the paper twin blocklist.PAPER_RULES):
a coin whose name's category is blocked (blocklist category: lines; celebrity, copycat and scam without any) is a
skip "category celebrity" etc. as soon as its signal comes; one that reaches the buy without a category (the
classifier lagged, a coin made and migrated within seconds) is asked at once, alone, and waited for at most
ONE_TIMEOUT_S (1.5 s; the stream's loop waits that long at most); no answer by then, an error or the day's cap is a
skip "category unknown". The VPS model writes a token in 0.08 to 0.12 s and a one-name answer is about 15 tokens, so
it rarely answers in time: `python -m lab.pumpfun_rt.livecat --timing` measures it on a day of names (job
pumpfun-rt-cat-timing, results/categories_local_ai2.md). Every skip takes the pipeline's path: the status's skipped
counts, one log line, skipped.jsonl, no card. The gate reads what was appended to cats.jsonl every CHECK_S
(CategoryIndex.tail). With category:none in the list (no category blocked) the gate is off: every coin goes on,
nothing is looked up or asked at the buy; the LiveClassifier keeps classifying (the data for the models).
"""

from __future__ import annotations

import collections
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from datetime import datetime, timezone

import numpy as np

from . import categorize as K
from .blocklist import DEFAULT_CATEGORIES

EVERY_S = 30.0
ONE_TIMEOUT_S = 1.5
CHECK_S = 2.0
LOG_S = 600.0
USD_DAY = float(os.environ.get("PYTHIA_PF_CAT_USD_DAY", "1.0"))
JOB = "pumpfun-categories-live"
NAMES_KEEP = 60_000                                    # mint -> (name, ticker) for the trending list
MEM_KEEP = 100_000                                     # this session's answers, until the index has them
RETRY_KEEP = 5_000                                     # coins of failed runs asked again
ERRORS_SHOWN = 5
UNKNOWN = "category unknown"


def wall_ms() -> int:
    return int(time.time() * 1000)


def utc_day(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d")


def reason(cat: str) -> str:
    return f"category {cat}"


def max_tokens(n: int) -> int:
    """The answer's room: about 15 tokens an item, as the daily job's."""
    return K.out_tokens(n)


class Spend:
    """The day's cost of the live calls (both kinds), in USD, and the cap (USD_DAY); the local calls cost 0."""

    def __init__(self, cap: float | None = None, clock=wall_ms):
        self.cap = USD_DAY if cap is None else cap
        self.clock = clock
        self.lock = threading.Lock()
        self.day = utc_day(clock())
        self.usd = 0.0
        self.calls = 0

    def _roll(self) -> None:
        d = utc_day(self.clock())
        if d != self.day:
            self.day, self.usd, self.calls = d, 0.0, 0

    def add(self, usd: float) -> None:
        with self.lock:
            self._roll()
            self.usd += float(usd or 0.0)
            self.calls += 1

    def left(self) -> bool:
        with self.lock:
            self._roll()
            return self.usd < self.cap


def ask(names: list[tuple[str, str]], trending: list[str], day: str, poster=None, timeout: float | None = None,
        job: str = JOB) -> tuple[dict[int, str], str]:
    """One call for these (name, ticker) pairs, ids 0..n-1: the daily job's prompt, schema and checks through the
    local chain (categorize.ask; `poster` a fake of lab.ai.local.chat in the tests). ({id: code}, the model);
    categorize.NoAnswer when there was none."""
    return K.ask(day, trending, names, chat=poster, use=job, timeout=K.CALL_TIMEOUT_S if timeout is None else timeout)


class LiveClassifier:
    """The stream's new coins, classified every EVERY_S (module doc). observe() and take() run on the service's loop,
    classify() in a thread (it only looks the index up and appends to the file)."""

    def __init__(self, ix=None, d=None, poster=None, clock=wall_ms, spend: Spend | None = None, log=print,
                 lookup=None):
        self.ix = ix if ix is not None else K.CategoryIndex()
        self.d = d
        self.poster = poster
        self.clock = clock
        self.spend = spend or Spend(clock=clock)
        self.log = log
        self.lookup = lookup                            # mint -> (name, ticker) of a coin made before the start
        self.new: dict[str, tuple[str, str]] = {}       # mint -> (name, ticker), created since the last take
        self.retry: dict[str, tuple[str, str]] = {}     # the coins of a run that failed
        self.names: collections.OrderedDict = collections.OrderedDict()
        self.trades: dict[str, collections.Counter] = {}   # UTC day -> trades per mint (today and yesterday)
        self.trending: list[str] = []                   # as of the last take, for the single calls too
        self.mem: dict[str, tuple[int, str, str]] = {}  # key -> (avail_ms, code, model) answered in this session
        self.models: set[str] = set()                   # the models that answered (their trial registered)
        self.busy = False
        self.st = {"runs": 0, "coins": 0, "asked": 0, "classified": 0, "reused": 0, "dropped": 0, "errors": 0,
                   "last_ms": None, "last_error": None}
        self.since_log = {"runs": 0, "coins": 0, "asked": 0, "classified": 0, "cost_usd": 0.0}
        self.log_t = time.monotonic()
        self.err_n = 0

    # ------------------------------------------------------------ on the loop
    def observe(self, table: str, row: dict) -> None:
        mint = row.get("mint")
        if not mint:
            return
        if table == "creates":
            if row.get("quote") is not None or row.get("mayhem"):
                return
            v = (row.get("name") or "", row.get("symbol") or "")
            self.new[mint] = v
            self.names[mint] = v
            while len(self.names) > NAMES_KEEP:
                self.names.popitem(last=False)
        elif table == "trades":
            day = utc_day(int(row.get("t") or self.clock()))
            c = self.trades.get(day)
            if c is None:
                c = self.trades[day] = collections.Counter()
                for old in sorted(self.trades)[:-2]:
                    del self.trades[old]
            c[mint] += 1

    def name_of(self, mint: str) -> tuple[str, str] | None:
        v = self.names.get(mint)
        if v is None and self.lookup is not None:
            try:
                v = self.lookup(mint)
            except Exception:                           # noqa: BLE001 - a name less in the list
                v = None
        return v

    def top(self) -> list[str]:
        """The TRENDING_N most traded names of today and yesterday (UTC), as the daily job lists its day's."""
        total: collections.Counter = collections.Counter()
        for c in self.trades.values():
            total.update(c)
        out, seen = [], set()
        for mint, _ in total.most_common(TOP_SCAN):
            v = self.name_of(mint)
            if v is None:
                continue
            k = K.name_key(*v)
            if k in seen or k == "|":
                continue
            seen.add(k)
            out.append(f"{K.clean(v[0], 30)} ({K.clean(v[1], 12)})")
            if len(out) >= K.TRENDING_N:
                break
        return out

    def take(self) -> tuple[dict, list[str]] | None:
        """The coins to classify now and the trending list; None while a run is still going or nothing is new."""
        if self.busy or not (self.new or self.retry):
            return None
        batch = {**self.retry, **self.new}
        self.new, self.retry = {}, {}
        self.trending = self.top()
        self.busy = True
        return batch, self.trending

    def known(self, key: str) -> tuple[int, str, str] | None:
        """(avail_ms, code, model) of a name a local model classified (the API's rows do not count, AI2)."""
        return self.ix.local.get(key) or self.mem.get(key)

    # ------------------------------------------------------------ in a thread
    def classify(self, batch: dict[str, tuple[str, str]], trending: list[str]) -> dict:
        """One run: the coins of known names get their line at once, the new names are asked in chunks of CHUNK."""
        try:
            return self._classify(batch, trending)
        finally:
            self.busy = False

    def _classify(self, batch, trending) -> dict:
        now = self.clock()
        day = utc_day(now)
        res = {"coins": len(batch), "reused": 0, "asked": 0, "classified": 0, "dropped": 0, "cost_usd": 0.0,
               "errors": []}
        entries, by_key = [], {}
        for mint, (name, sym) in batch.items():
            k = K.name_key(name, sym)
            if k == "|":
                continue
            hit = self.known(k)
            if hit is not None:
                entries.append({"mint": mint, "key": k, "cat": hit[1], "day": day, "avail_ms": hit[0],
                                "model": hit[2]})
                res["reused"] += 1
            else:
                by_key.setdefault(k, []).append((mint, name, sym))
        order = sorted(by_key, key=lambda k: -len(by_key[k]))
        failed: dict[str, tuple[str, str]] = {}
        for i in range(0, len(order), K.CHUNK):
            keys = order[i:i + K.CHUNK]
            if not self.spend.left():
                res["errors"].append(f"day cap of {self.spend.cap:g} USD")
                break                                   # asked again tomorrow, or alone at the buy (also capped)
            res["asked"] += len(keys)
            try:
                got, model = ask([by_key[k][0][1:] for k in keys], trending, day, self.poster)
            except Exception as e:                      # NoAnswer and anything else: the next run asks again
                self.spend.add(0.0)
                res["errors"].append(f"{getattr(e, 'kind', type(e).__name__)}: {str(e)[:160]}")
                for k in keys:
                    for mint, name, sym in by_key[k]:
                        failed[mint] = (name, sym)
                continue
            self.spend.add(0.0)
            if got and model not in self.models:
                self.models.add(model)
                K.register_trial(model, lambda m: self.log(m, flush=True))
            avail = self.clock()
            res["dropped"] += len(keys) - len(got)      # the next coin of that name asks again
            for j, c in got.items():
                self.mem[keys[j]] = (avail, c, model)
                for mint, _, _ in by_key[keys[j]]:
                    entries.append({"mint": mint, "key": keys[j], "cat": c, "day": day, "avail_ms": avail,
                                    "model": model})
                res["classified"] += 1
        while len(self.mem) > MEM_KEEP:
            self.mem.pop(next(iter(self.mem)))
        if failed:
            for m, v in list(failed.items())[:RETRY_KEEP]:
                self.retry.setdefault(m, v)
        try:
            K.append(entries, self.d)
        except OSError as e:
            res["errors"].append(f"cats.jsonl not written ({type(e).__name__})")
        self._count(res)
        return res

    def _count(self, res: dict) -> None:
        st = self.st
        st["runs"] += 1
        for k in ("coins", "asked", "classified", "reused", "dropped"):
            st[k] += res[k]
        st["last_ms"] = self.clock()
        for k in ("coins", "asked", "classified"):
            self.since_log[k] += res[k]
        self.since_log["runs"] += 1
        self.since_log["cost_usd"] += res["cost_usd"]
        if res["errors"]:
            st["errors"] += 1
            st["last_error"] = res["errors"][0]
            self.err_n += 1
            if self.err_n <= ERRORS_SHOWN or self.err_n % 100 == 0:
                self.log(f"live categories: a run failed ({res['errors'][0]}); {self.err_n} so far, asked again "
                         "with the next run", flush=True)
        if time.monotonic() - self.log_t >= LOG_S:
            s = self.since_log
            self.log(f"live categories: {s['coins']:,} new coins in {s['runs']} runs, {s['asked']:,} names asked, "
                     f"{s['classified']:,} classified, ${s['cost_usd']:.4f} (today ${self.spend.usd:.4f} of "
                     f"{self.spend.cap:g})", flush=True)
            self.since_log = {"runs": 0, "coins": 0, "asked": 0, "classified": 0, "cost_usd": 0.0}
            self.log_t = time.monotonic()

    def status(self) -> dict:
        return dict(self.st, pending=len(self.new) + len(self.retry), cost_today_usd=round(self.spend.usd, 5),
                    cap_usd=self.spend.cap, every_s=EVERY_S, models=sorted(self.models))


TOP_SCAN = 400                                          # the most traded mints looked at for the trending names
_POOL: ThreadPoolExecutor | None = None


def pool() -> ThreadPoolExecutor:
    global _POOL
    if _POOL is None:
        _POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="livecat")
    return _POOL


class CategoryGate:
    """Pipeline.category: (strategy, token, at_buy) -> the skip reason, or None to go on (module doc). `block`: the
    pipeline's BlockWatch (its list's category: lines), `rules`: the strategies it holds for (None: every one),
    `cls`: the service's LiveClassifier (its answers and trending list), None in the collector."""

    def __init__(self, ix, block=None, rules=None, cls: LiveClassifier | None = None, poster=None,
                 spend: Spend | None = None, d=None, clock=wall_ms, mono=time.monotonic, every_s: float = CHECK_S,
                 timeout_s: float = ONE_TIMEOUT_S, log=print, submit=None):
        self.ix = ix if ix is not None else K.CategoryIndex()
        self.block = block
        self.rules = None if rules is None else frozenset(rules)
        self.cls = cls
        self.poster = poster
        self.spend = spend or (cls.spend if cls is not None else Spend(clock=clock))
        self.d = d
        self.clock = clock
        self.mono = mono
        self.every_s = every_s
        self.timeout_s = timeout_s
        self.log = log
        self.submit = submit or (lambda f, *a: pool().submit(f, *a))
        self.checked = -1e18
        self.mem: dict[str, tuple[int, str, str]] = {}  # the single answers, until the index has them
        self.one_st = collections.Counter()             # asked, ok, timeout, failed, cap

    def blocked(self) -> frozenset:
        lst = getattr(self.block, "list", None)
        return lst.blocked_categories() if lst is not None else DEFAULT_CATEGORIES

    def known(self, key: str) -> str | None:
        if self.mono() - self.checked >= self.every_s:
            self.checked = self.mono()
            try:
                self.ix.tail()
            except Exception as e:                      # noqa: BLE001 - the last index stays
                self.log(f"live categories: cats.jsonl not read ({type(e).__name__})", flush=True)
        hit = self.ix.keys.get(key) or self.mem.get(key) or (self.cls.known(key) if self.cls is not None else None)
        return hit[1] if hit is not None else None

    def __call__(self, rule: str, tok, at_buy: bool = False) -> str | None:
        if self.rules is not None and rule not in self.rules:
            return None
        blocked = self.blocked()
        if not blocked:                                 # category:none: the gate is off
            return None
        name, sym = getattr(tok, "name", "") or "", getattr(tok, "symbol", "") or ""
        key = K.name_key(name, sym)
        c = self.known(key)
        if c is None and at_buy and key != "|":
            c = self.one(tok.mint, name, sym, key)
        if c is None:
            return UNKNOWN if at_buy else None
        return reason(c) if c in blocked else None

    def one(self, mint: str, name: str, sym: str, key: str) -> str | None:
        """This one name, asked at once; its code, or None (no answer within timeout_s, an error, the day's cap).
        The call finishes in its thread either way: a late answer is kept and written for the next coin."""
        if not self.spend.left():
            self.one_st["cap"] += 1
            return None
        self.one_st["asked"] += 1
        trending = list(self.cls.trending) if self.cls is not None else []
        t0 = time.monotonic()
        fut = self.submit(self._ask_one, mint, name, sym, key, trending)
        try:
            c = fut.result(timeout=self.timeout_s)
        except FutureTimeout:
            self.one_st["timeout"] += 1
            self.log(f"live categories: {K.clean(sym, 16)!r} asked alone, no answer within {self.timeout_s:g} s",
                     flush=True)
            return None
        except Exception as e:                          # noqa: BLE001 - NoAnswer and the rest: unknown
            self.one_st["failed"] += 1
            if self.one_st["failed"] <= ERRORS_SHOWN or self.one_st["failed"] % 100 == 0:
                self.log(f"live categories: {K.clean(sym, 16)!r} asked alone, failed "
                         f"({getattr(e, 'kind', type(e).__name__)}); {self.one_st['failed']} so far", flush=True)
            return None
        if c is None:
            self.one_st["failed"] += 1
            return None
        self.one_st["ok"] += 1
        self.log(f"live categories: {K.clean(sym, 16)!r} asked alone: {c} in {(time.monotonic() - t0) * 1000:.0f} ms",
                 flush=True)
        return c

    def _ask_one(self, mint: str, name: str, sym: str, key: str, trending: list[str]) -> str | None:
        now = self.clock()
        try:
            got, model = ask([(name, sym)], trending, utc_day(now), self.poster, timeout=self.timeout_s)
        except Exception:
            self.spend.add(0.0)
            raise
        self.spend.add(0.0)
        c = got.get(0)
        if c is not None:
            avail = self.clock()
            self.mem[key] = (avail, c, model)
            try:
                K.append([{"mint": mint, "key": key, "cat": c, "day": utc_day(avail), "avail_ms": avail,
                           "model": model}], self.d)
            except OSError:
                pass
        return c

    def status(self) -> dict:
        lst = getattr(self.block, "list", None)
        return {"blocked": sorted(self.blocked()), "default": not getattr(lst, "categories", None),
                "off": bool(lst is not None and lst.categories_off()),
                "names": len(self.ix), "one": dict(self.one_st), "cost_today_usd": round(self.spend.usd, 5),
                "cap_usd": self.spend.cap}


# ---------------------------------------------------------------- the one-at-the-buy call, timed (AI2)

TIMING_N = 200
TIMING_SEED = 20261029
TIMING_LIMIT_S = 45.0                                   # each name may take this long, so its time is seen
TIMING_TRIAL = "hand:ai2:livecat_timing"
LOG_MIN_TOKENS = 12                                     # a one-name answer is about 15 tokens


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n <= 0:
        return 0.0, 1.0
    p = k / n
    c = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return float(max(0.0, (p + z * z / (2 * n) - c) / (1 + z * z / n))), \
        float(min(1.0, (p + z * z / (2 * n) + c) / (1 + z * z / n)))


def share(ok: list[bool]) -> dict:
    k, n = sum(ok), len(ok)
    lo, hi = wilson(k, n)
    return {"n": n, "in_time": k, "share": round(k / n, 4) if n else None, "ci95": [round(lo, 4), round(hi, 4)]}


def log_timing(path=None) -> dict:
    """Way 1 of the pre-registration: the successful VPS calls in <data>/ai/local_llm.jsonl (other uses), the share
    within ONE_TIMEOUT_S, of all and of those that wrote at least LOG_MIN_TOKENS."""
    from ..ops import notify
    rows = []
    try:
        for line in (path or notify.data_root() / "ai" / "local_llm.jsonl").read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if isinstance(r, dict) and r.get("backend") == "vps" and r.get("ok") and r.get("seconds") is not None:
                rows.append(r)
    except OSError:
        pass
    fast = [float(r["seconds"]) <= ONE_TIMEOUT_S for r in rows]
    big = [float(r["seconds"]) <= ONE_TIMEOUT_S for r in rows if int(r.get("tokens") or 0) >= LOG_MIN_TOKENS]
    return {"calls": share(fast), f"calls_{LOG_MIN_TOKENS}_tokens_or_more": share(big),
            "from_ms": min((int(r["ts_ms"]) for r in rows if r.get("ts_ms")), default=None),
            "to_ms": max((int(r["ts_ms"]) for r in rows if r.get("ts_ms")), default=None)}


def timing(day: str | None = None, n: int = TIMING_N, chat=None, root=None, log=print, mono=time.monotonic,
           log_path=None) -> dict:
    """Way 2: n distinct names of a UTC day (the last complete one in the store), drawn with TIMING_SEED, each asked
    alone as the gate asks, one after another, each allowed TIMING_LIMIT_S. Per model: the share answered with a
    valid code within ONE_TIMEOUT_S (Wilson 95 %), the median and 90th percentile seconds of the answers."""
    from . import store
    if day is None:
        done = [x for x in store.days(None if root is None else root) if x < utc_day(wall_ms())]
        day = done[-1] if done else utc_day(wall_ms() - 86_400_000)
    rows, trending = K.day_tokens(day, root)
    names: dict[str, tuple[str, str]] = {}
    for r in rows:
        if r["key"] != "|":
            names.setdefault(r["key"], (r["name"], r["symbol"]))
    order = sorted(names)
    pick = sorted(np.random.default_rng(TIMING_SEED).choice(len(order), size=min(n, len(order)), replace=False)) \
        if order else []
    calls = []
    for i in pick:
        t0 = mono()
        try:
            got, model = ask([names[order[i]]], trending, day, chat, timeout=TIMING_LIMIT_S, job=JOB + ":timing")
            c, why = got.get(0), None if got.get(0) else "dropped"
        except K.NoAnswer as e:
            c, model, why = None, None, e.kind
        calls.append({"seconds": round(mono() - t0, 3), "ok": c is not None, "model": model, "why": why})
    by: dict[str, dict] = {}
    for m in sorted({c["model"] or "none" for c in calls}):
        cs = [c for c in calls if (c["model"] or "none") == m]
        sec = [c["seconds"] for c in cs if c["ok"]]
        by[m] = dict(share([c["ok"] and c["seconds"] <= ONE_TIMEOUT_S for c in cs]),
                     answered=len(sec), median_s=round(float(np.median(sec)), 2) if sec else None,
                     p90_s=round(float(np.percentile(sec, 90)), 2) if sec else None,
                     why={w: sum(1 for c in cs if c["why"] == w) for w in sorted({c["why"] for c in cs if c["why"]})})
    res = {"day": day, "names": len(order), "n": len(calls), "seed": TIMING_SEED, "limit_s": ONE_TIMEOUT_S,
           "all": share([c["ok"] and c["seconds"] <= ONE_TIMEOUT_S for c in calls]), "by_model": by,
           "log": log_timing(log_path), "at_ms": wall_ms()}
    for m in by:
        if m != "none" and by[m]["answered"]:
            K.register_trial(m, log, TIMING_TRIAL)
    if res["log"]["calls"]["n"]:
        K.register_trial(f"vps:{os.environ.get('PYTHIA_LOCAL_LLM_MODEL') or 'qwen3-4b-instruct'}", log, TIMING_TRIAL)
    for m, v in by.items():
        log(f"livecat timing: {m}: {v['in_time']} of {v['n']} names in {ONE_TIMEOUT_S:g} s "
            f"({100 * (v['share'] or 0):.1f} %, 95 % {100 * v['ci95'][0]:.1f} to {100 * v['ci95'][1]:.1f} %), "
            f"median {v['median_s']} s, p90 {v['p90_s']} s")
    lg = res["log"][f"calls_{LOG_MIN_TOKENS}_tokens_or_more"]
    log(f"livecat timing: the call log: {lg['in_time']} of {lg['n']} VPS calls with {LOG_MIN_TOKENS} tokens or more "
        f"within {ONE_TIMEOUT_S:g} s")
    return res


def write_timing(res: dict, d=None) -> None:
    from .. import report as rep
    out = rep.REPORTS / "pumpfun_rt"
    out.mkdir(parents=True, exist_ok=True)
    (out / "livecat_timing.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    d = d or K.cat_dir()
    d.mkdir(parents=True, exist_ok=True)
    with (d / "timing.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(res, separators=(",", ":")) + "\n")


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--timing" not in argv:
        print(__doc__.strip().splitlines()[0])
        return 2
    day = argv[argv.index("--day") + 1] if "--day" in argv else None
    res = timing(day)
    write_timing(res)
    return 0 if any(v["answered"] for v in res["by_model"].values()) or not res["n"] else 1


if __name__ == "__main__":
    sys.exit(main())
