"""What is hot on pump.fun right now, from our own chain data and our models. A VIEW: nothing here trades.

The paper engine (live.Shadow, inside the collector) hands every row it fed to the engine to Trends.observe
AFTER the engine has taken it, and Trends only reads the engine's state (tokens, the wallet and creator
books, the models), so no decision of a paper book changes with it (tests/test_pumpfun_trends.py replays a
synthetic stream with and without it, field by field). We never read pump.fun's website or API: every
number is from the curve and pool trades the collector decodes itself.

Running counters per token, no rescans: 30 s buckets (BUCKET_MS) of the last 15 minutes with buy and sale
SOL, trade counts, the buyers, the closing price and progress, curve and pool apart. A window is "the last
N minutes" to the bucket: the bucket now open and the N * 2 - 1 before it. Every WRITE_S (on the engine's
chain clock) <reports>/pumpfun_rt/trends.json gets three lists of at most TOP entries each:

  hot        by buy volume in SOL over 5 minutes (1 and 15 as columns), with unique buyers, net flow, the
             price change over 5 and 15 minutes, the market cap in SOL and USD, progress or "migrated", age;
             a coin quoted in another coin than SOL is not ranked here and has no SOL amounts (they are not SOL)
  migrating  curves above MIGRATING_MIN progress, by progress, then by speed (progress gained per minute
             over the last 5 minutes)
  fresh      coins migrated in the last FRESH_MS, by their pool's volume over 5 minutes, then the newest

Each entry, where the models exist: P(win) and P(rug) from the Y9 selection models (only once the curve
has completed: they decide at the migration, selmodel.py), P(3x) from the early model e_peak3x (only on the
curve: it was trained on the first minute and the 25/50/75 % milestones, so it is a rough read later), the
smart early buyers (wallets.WalletBook), the creator's earlier migrations (tokens.CreatorBook), the dev's
share sold, the flags (mayhem, cashback, quote not SOL, irregular curve) and "blocked" for a mint on the
owner's block list (BLOCK_PATHS, one mint per line, # comments): a blocked coin keeps its place but gets no
badge, so it is never highlighted. The badges (BADGES) are thresholds on those numbers, set here once.

SOL in USD is Kraken's public ticker (SOLUSD, no key), read in a background thread at most every SOL_USD_S;
without it the USD market cap is null.
"""

from __future__ import annotations

import collections
import json
import math
import threading
import time
import urllib.request
from pathlib import Path

import numpy as np

from . import curve as C
from .tokens import SUPPLY

BUCKET_MS = 30_000
KEEP_MS = 15 * 60_000
WINDOWS_M = (1, 5, 15)
WRITE_S = 12
TOP = 30
MIGRATING_MIN = 0.70
FRESH_MS = 30 * 60_000
SPARK_N = KEEP_MS // BUCKET_MS
SOL_USD_URL = "https://api.kraken.com/0/public/Ticker?pair=SOLUSD"
SOL_USD_S = 60
BLOCK_CHECK_S = 60
SUPPLY_TOKENS = SUPPLY / C.TOKEN_UNIT
MILESTONES = (0.25, 0.50, 0.75)

# The badges: (id, what it needs). A blocked coin gets none.
WIN_HIGH_LIFT = 1.5        # P(win) at or above the Y9 top-30 % threshold, or 1.5 x its base rate without one
WIN_LOW_LIFT = 0.5         # P(win) at or under half its base rate
RUG_LIFT = 1.5             # P(rug) at or above 1.5 x its base rate
P3X_LIFT = 2.0             # P(3x) at or above twice its base rate
SMART_MIN = 2              # smart wallets among the early buyers
CREATOR_MIG_MIN = 1        # the creator's earlier coins that completed their curve
DEV_SOLD_MIN = 0.5         # the dev sold half or more of what it bought
BADGES = {
    "win_high": f"P(win) in the top 30 % of the Y9 model's scores (or {WIN_HIGH_LIFT}x its base rate)",
    "win_low": f"P(win) at or under {WIN_LOW_LIFT}x the Y9 model's base rate",
    "rug_risk": f"P(rug) at or above {RUG_LIFT}x the Y9 model's base rate",
    "p3x_high": f"P(3x) at or above {P3X_LIFT}x the early model's base rate",
    "smart": f"{SMART_MIN} or more early buyers with a record of buying early into coins that completed",
    "creator_mig": "the creator had earlier coins complete their curve",
    "dev_sold": f"the dev sold {int(DEV_SOLD_MIN * 100)} % or more of what it bought",
}
NOTE = ("Signals from our own chain data, not advice. Our studies found no rule that wins reliably on these coins; "
        "most of them go to zero.")


def block_paths() -> list[Path]:
    from ..data import ROOT
    return [Path("/etc/pythia/blocked-mints.txt"), ROOT / "pumpfun_rt" / "blocked-mints.txt"]


def read_blocked(paths) -> set[str]:
    out = set()
    for p in paths:
        try:
            for line in Path(p).read_text(encoding="utf-8").splitlines():
                m = line.split("#", 1)[0].strip()
                if m:
                    out.add(m)
        except OSError:
            pass
    return out


def parse_ticker(body) -> float | None:
    """The last trade of a Kraken ticker answer (result.<pair>.c[0])."""
    try:
        v = float(next(iter(body["result"].values()))["c"][0])
    except (KeyError, TypeError, ValueError, StopIteration, IndexError, AttributeError):
        return None
    return v if 0 < v < float("inf") else None


def fetch_sol_usd(timeout: float = 5) -> float | None:
    req = urllib.request.Request(SOL_USD_URL, headers={"User-Agent": "pythia-trends"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return parse_ticker(json.load(r))


class Coin:
    """One token's buckets: [start, buy_l, sell_l, buys, sells, buyers, close price, close progress, pool buy_l,
    pool sell_l, pool trades]."""

    __slots__ = ("b", "first_t", "first_price", "first_prog", "last_t")

    def __init__(self, t: int, price: float, prog: float):
        self.b: collections.deque = collections.deque()
        self.first_t, self.first_price, self.first_prog, self.last_t = t, price, prog, t

    def bucket(self, t: int) -> list:
        b0 = t - t % BUCKET_MS
        b = self.b
        if b and b[-1][0] >= b0:                              # this bucket, or a late trade's (its own or the one before)
            return b[-1] if b[-1][0] == b0 else next((x for x in reversed(b) if x[0] <= b0), b[0])
        b.append([b0, 0, 0, 0, 0, set(), b[-1][6] if b else self.first_price, b[-1][7] if b else self.first_prog,
                  0, 0, 0])
        while b and b[0][0] < b0 - KEEP_MS:                   # the oldest kept close is the coin's first state now
            x = b.popleft()
            self.first_t, self.first_price, self.first_prog = x[0] + BUCKET_MS, x[6], x[7]
        return b[-1]


class Trends:
    def __init__(self, eng, path: Path | None = None, sol_usd=fetch_sol_usd, blocked: list | None = None,
                 every_s: float = WRITE_S):
        self.eng = eng
        self.path = path
        self.coins: dict[str, Coin] = {}
        self.migrated: dict[str, int] = {}                    # mint -> migration time, last FRESH_MS
        self.every_ms = int(every_s * 1000)
        self.last_write = 0
        self.sol_usd_fn = sol_usd
        self.sol_usd: float | None = None
        self.sol_usd_mono = -1e18
        self.sol_usd_busy = False
        self.block_paths = block_paths() if blocked is None else blocked
        self.blocked: set[str] = read_blocked(self.block_paths)
        self.block_mono = time.monotonic()
        self.errors = 0

    # ------------------------------------------------------------ the stream (after the engine took the row)
    def observe(self, table: str, r: dict) -> None:
        if table == "trades":
            self._trade(r["mint"], int(r["t"]), bool(r["buy"]), int(r["sol"] or 0), r.get("user"), False)
        elif table == "amm":
            if r.get("mint"):
                self._trade(r["mint"], int(r["t"]), bool(r["buy"]), int(r.get("quote") or 0), r.get("user"), True)
        elif table == "other" and r.get("kind") == "migrate" and r.get("mint") in self.eng.tokens:
            self.migrated.setdefault(r["mint"], int(r["t"]))

    def _trade(self, mint: str, t: int, buy: bool, sol: int, user, pool: bool) -> None:
        tok = self.eng.tokens.get(mint)
        if tok is None:
            return
        c = self.coins.get(mint)
        if c is None:
            c = self.coins[mint] = (Coin(tok.t0, tok.p0, 0.0) if t - tok.t0 <= KEEP_MS
                                    else Coin(t, tok.price(), tok.progress()))
        b = c.bucket(t)
        if buy:
            b[1] += sol
            b[3] += 1
            if user:
                b[5].add(user)
        else:
            b[2] += sol
            b[4] += 1
        if pool:
            b[8 if buy else 9] += sol
            b[10] += 1
        if b is c.b[-1]:                                      # a late delivery adds its flow, not its price
            b[6] = tok.price()
            b[7] = 1.0 if tok.complete_t is not None else tok.progress()
        c.last_t = max(c.last_t, t)

    # ------------------------------------------------------------ the clock
    def tick(self, now_ms: int) -> None:
        """Write the file every WRITE_S of chain time; an error here never reaches the engine."""
        if self.path is None or now_ms - self.last_write < self.every_ms:
            return
        self.last_write = now_ms
        try:
            self._sol_usd_due()
            self._blocked_due()
            self.write(self.snapshot(now_ms))
        except Exception as e:                                # noqa: BLE001 - a view never stops the books
            self.errors += 1
            if self.errors <= 5:
                print(f"trends: not written ({type(e).__name__}: {e})", flush=True)

    def _sol_usd_due(self) -> None:
        mono = time.monotonic()
        if self.sol_usd_fn is None or self.sol_usd_busy or mono - self.sol_usd_mono < SOL_USD_S:
            return
        self.sol_usd_mono = mono
        self.sol_usd_busy = True

        def run():
            try:
                v = self.sol_usd_fn()
                if v:
                    self.sol_usd = float(v)
            except Exception:                                 # noqa: BLE001 - the last rate stays
                pass
            finally:
                self.sol_usd_busy = False
        threading.Thread(target=run, daemon=True).start()

    def _blocked_due(self) -> None:
        mono = time.monotonic()
        if mono - self.block_mono >= BLOCK_CHECK_S:
            self.block_mono = mono
            self.blocked = read_blocked(self.block_paths)

    def write(self, snap: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(snap, separators=(",", ":"), allow_nan=False), encoding="utf-8")
        tmp.replace(self.path)

    # ------------------------------------------------------------ the lists
    def _prune(self, now_ms: int) -> None:
        lo = now_ms - KEEP_MS
        for m in [m for m, c in self.coins.items() if c.last_t < lo or m not in self.eng.tokens]:
            del self.coins[m]
        for m in [m for m, t in self.migrated.items() if t < now_ms - FRESH_MS or m not in self.eng.tokens]:
            del self.migrated[m]

    @staticmethod
    def _since(c: Coin, now_ms: int, minutes: int) -> list[list]:
        lo = now_ms - now_ms % BUCKET_MS - (minutes * 60_000 // BUCKET_MS - 1) * BUCKET_MS
        out = []
        for b in reversed(c.b):
            if b[0] < lo:
                break
            out.append(b)
        return out

    @staticmethod
    def _before(c: Coin, now_ms: int, minutes: int) -> tuple[float, float, int]:
        """The price, progress and time at the start of the window: the close of the last bucket before it,
        else the coin's first state."""
        lo = now_ms - now_ms % BUCKET_MS - (minutes * 60_000 // BUCKET_MS - 1) * BUCKET_MS
        for b in reversed(c.b):
            if b[0] < lo:
                return b[6], b[7], lo
        return c.first_price, c.first_prog, max(c.first_t, now_ms - minutes * 60_000)

    def snapshot(self, now_ms: int) -> dict:
        self._prune(now_ms)
        toks = self.eng.tokens
        # A coin quoted in another coin is not ranked by SOL (its amounts are in that coin); progress still counts.
        vol5 = {m: sum(b[1] for b in self._since(c, now_ms, 5)) for m, c in self.coins.items()
                if toks[m].quote is None}
        hot = sorted((m for m, v in vol5.items() if v > 0), key=lambda m: (-vol5[m], m))[:TOP]
        speed = {}
        mig = []
        for m, c in self.coins.items():
            tok = toks[m]
            if tok.complete_t is None and tok.progress() >= MIGRATING_MIN:
                speed[m] = self._speed(c, tok, now_ms)
                mig.append(m)
        mig = sorted(mig, key=lambda m: (-round(toks[m].progress(), 4), -speed[m], m))[:TOP]
        pool5 = {m: sum(b[8] + b[9] for b in self._since(self.coins[m], now_ms, 5))
                 if m in self.coins and toks[m].quote is None else 0 for m in self.migrated}
        fresh = sorted(self.migrated, key=lambda m: (-pool5[m], -self.migrated[m], m))[:TOP]
        cache = {m: self.entry(m, now_ms) for m in dict.fromkeys(hot + mig + fresh)}
        policy = (self.eng.models or {}).get("sel_policy") or {}
        for m, p in self.probs(list(cache), now_ms).items():
            cache[m].update(p)
            cache[m]["badges"] = [] if cache[m]["blocked"] else badges(cache[m], policy)
        models = self.eng.models or {}
        return {"t": now_ms, "written_ms": int(time.time() * 1000), "bucket_s": BUCKET_MS // 1000,
                "sol_usd": self.sol_usd, "tracked": len(self.coins),
                "lists": {"hot": [cache[m] for m in hot], "migrating": [cache[m] for m in mig],
                          "fresh": [cache[m] for m in fresh]},
                "models": {"win": _usable(models.get("sel_win0")), "rug": _usable(models.get("sel_rug0")),
                           "p3x": _usable(models.get("e_peak3x"))},
                "badges": BADGES, "limits": {"top": TOP, "migrating_min": MIGRATING_MIN,
                                             "fresh_min": FRESH_MS // 60_000},
                "note": NOTE}

    def _speed(self, c: Coin, tok, now_ms: int) -> float:
        _, p0, t0 = self._before(c, now_ms, 5)
        mins = max((now_ms - t0) / 60_000, BUCKET_MS / 60_000)
        return (tok.progress() - p0) / mins

    def entry(self, m: str, now_ms: int) -> dict:
        tok = self.eng.tokens[m]
        c = self.coins.get(m)
        win = {w: (self._since(c, now_ms, w) if c is not None else []) for w in WINDOWS_M}
        b5 = win[5]
        price = tok.price()
        mcap = price * SUPPLY_TOKENS
        chg = {}
        for w in (5, 15):
            p0 = self._before(c, now_ms, w)[0] if c is not None else 0.0
            chg[w] = price / p0 - 1 if p0 > 0 and price > 0 else None
        done = tok.complete_t is not None
        flags = [f for f, on in (("mayhem", tok.mayhem), ("cashback", tok.cashback), ("quote", tok.quote is not None),
                                 ("irregular", tok.irregular)) if on]
        blocked = m in self.blocked
        hist = tok.hist or {}
        e = {"mint": m, "name": tok.name[:40], "symbol": tok.symbol[:16], "uri": tok.uri[:200] or None,
             "created_ms": tok.t0, "age_s": round((now_ms - tok.t0) / 1000),
             **{f"vol_{w}m": _r(sum(b[1] for b in win[w]) / C.LAMPORTS) for w in WINDOWS_M},
             "sell_5m": _r(sum(b[2] for b in b5) / C.LAMPORTS),
             "net_5m": _r(sum(b[1] - b[2] for b in b5) / C.LAMPORTS),
             "buys_5m": sum(b[3] for b in b5), "sells_5m": sum(b[4] for b in b5),
             "buyers_5m": len(set().union(*(b[5] for b in b5))) if b5 else 0,
             "chg_5m": _r(chg[5]), "chg_15m": _r(chg[15]),
             "price_sol": _r(price, 6), "mcap_sol": _r(mcap), "mcap_usd": _r(mcap * self.sol_usd) if self.sol_usd else None,
             "progress": None if done else _r(tok.progress()), "migrated": done,
             "complete_ms": tok.complete_t, "migrate_ms": self.migrated.get(m, tok.migrate_t),
             "speed_pm": _r(self._speed(c, tok, now_ms)) if c is not None and not done else None,
             "pool_vol_5m": _r(sum(b[8] + b[9] for b in b5) / C.LAMPORTS), "pool_trades_5m": sum(b[10] for b in b5),
             "spark": self._spark(c, now_ms),
             "smart_n": tok.early.smart if tok.early is not None else None,
             "creator_migrated": int(hist.get("migrated") or 0), "creator_coins": int(hist.get("n") or 0),
             "dev_sold": _r(tok.dev_sold / tok.dev_bought) if tok.dev_bought else None,
             "flags": flags, "blocked": blocked}
        if tok.quote is not None:                             # its amounts are in another coin: no SOL numbers
            for k in ("vol_1m", "vol_5m", "vol_15m", "sell_5m", "net_5m", "price_sol", "mcap_sol", "mcap_usd",
                      "pool_vol_5m"):
                e[k] = None
            e["spark"] = []
        return e

    def _spark(self, c: Coin | None, now_ms: int) -> list:
        """The market cap in SOL at the close of every bucket of the last 15 minutes (carried over empty ones)."""
        if c is None:
            return []
        b0 = now_ms - now_ms % BUCKET_MS
        start = b0 - (SPARK_N - 1) * BUCKET_MS
        by = {b[0]: b[6] for b in c.b}
        last = c.first_price if c.first_t < start else None
        for b in c.b:
            if b[0] < start:
                last = b[6]
        out = []
        for k in range(SPARK_N):
            t = start + k * BUCKET_MS
            if t in by:
                last = by[t]
            if last is not None:
                out.append(_r(last * SUPPLY_TOKENS))
        return out

    # ------------------------------------------------------------ the models (read only)
    def probs(self, mints: list[str], now_ms: int) -> dict[str, dict]:
        """P(win), P(rug) and P(3x) of the coins, each model asked once for all of them (one row at a time
        costs a LightGBM call each)."""
        eng = self.eng
        models = eng.models or {}
        t = int(now_ms)
        out = {m: {"p_win": None, "p_rug": None, "p_3x": None, "base_win": None, "base_rug": None, "base_3x": None,
                   "win_label": None} for m in mints}
        asks: dict[str, list] = {}                            # model name -> [(mint, field, features)]
        e3 = models.get("e_peak3x")
        for m in mints:
            tok = eng.tokens[m]
            if tok.complete_t is not None and getattr(eng, "sel", None) is not None and tok.complete_t <= t:
                five = t - tok.complete_t >= 5_000 and _usable(models.get("sel_win5")) \
                    and _usable(models.get("sel_rug5"))
                w, r = ("sel_win5", "sel_rug5") if five else ("sel_win0", "sel_rug0")
                if _usable(models.get(w)) or _usable(models.get(r)):
                    from .selfeat import decision_features
                    f = decision_features(eng, tok, t)
                    out[m]["win_label"] = w[4:] if _usable(models.get(w)) else None
                    for name, field in ((w, "win"), (r, "rug")):
                        if _usable(models.get(name)):
                            asks.setdefault(name, []).append((m, field, f))
            elif tok.complete_t is None and _usable(e3) and getattr(eng, "early", None) is not None:
                prog = tok.progress()
                ms = max((x for x in MILESTONES if prog >= x), default=0.0)
                f = eng.features(tok, t)
                f.update(eng.early.early_features(tok, t, ms, prune=False))
                asks.setdefault("e_peak3x", []).append((m, "3x", f))
        for name, rows in asks.items():
            mdl = models[name]
            X = np.array([[float(f.get(k, math.nan)) for k in mdl.features] for _, _, f in rows], dtype=float)
            for (m, field, _), p in zip(rows, mdl.predict(X)):
                out[m][f"p_{field}"] = _r(float(p))
                out[m][f"base_{field}"] = _r(mdl.base)
        return out


def badges(e: dict, policy: dict | None = None) -> list[str]:
    """The badge ids an entry earns (BADGES); the thresholds are the constants above."""
    out = []
    pw, bw = e.get("p_win"), e.get("base_win")
    if pw is not None and bw:
        thr = ((policy or {}).get(e.get("win_label") or "win0") or {}).get("0.3")
        if (pw >= thr) if thr is not None else (pw >= WIN_HIGH_LIFT * bw):
            out.append("win_high")
        elif pw <= WIN_LOW_LIFT * bw:
            out.append("win_low")
    pr, br = e.get("p_rug"), e.get("base_rug")
    if pr is not None and br and pr >= RUG_LIFT * br:
        out.append("rug_risk")
    p3, b3 = e.get("p_3x"), e.get("base_3x")
    if p3 is not None and b3 and p3 >= P3X_LIFT * b3:
        out.append("p3x_high")
    if (e.get("smart_n") or 0) >= SMART_MIN:
        out.append("smart")
    if (e.get("creator_migrated") or 0) >= CREATOR_MIG_MIN:
        out.append("creator_mig")
    if (e.get("dev_sold") or 0) >= DEV_SOLD_MIN:
        out.append("dev_sold")
    return out


def _usable(m) -> bool:
    return m is not None and getattr(m, "booster", None) is not None


def _r(x, sig: int = 4):
    """Rounded to `sig` significant digits; None for a missing or non-finite number."""
    if x is None:
        return None
    x = float(x)
    if not math.isfinite(x):
        return None
    return float(f"{x:.{sig}g}") if x else 0.0
