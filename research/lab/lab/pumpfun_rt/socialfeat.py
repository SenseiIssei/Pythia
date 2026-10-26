"""Y14 (results/pumpfun_social_y14_prereg.md): the coins' social links as features a decision may use. PAPER ONLY.

Free, no X API: only the links inside each coin's metadata, normalised by the collector (collector.meta_social, the
table "meta"): the X link's kind, the X handle and tweet id, the telegram handle and the website's registrable domain.
The engine's part (sim.Engine(social=True): the paper books, the daily study and the Y14 run; the live service's engine
does not have it), warmed from the record's earlier days (warm) so the counts do not start at zero after a restart.

No look-ahead, by construction: a coin counts for another only once its metadata was received (the meta row's
time), only when it was created before the coin scored (strictly earlier creation time), and as migrated only when
its migration came before the decision; the tracker is fed in time order, so a value asked at t reads what was
known at t.

  soc_known           1 with the coin's metadata read at t, 0 without it (not fetched yet, failed, not a gateway
                      uri); every other feature is NaN at 0. NaN for rows written without the tracker (before Y14)
  soc_x_kind          the X link's kind, X_KINDS' index (0 none, 1 profile, 2 status, 3 community, 4 search, 5 other)
  soc_{handle,tweet,tg,dom}_prev  earlier coins with the same X handle, tweet id, telegram handle, website domain
                      (0 when the coin has none: soc_x_kind and the flags tell that apart)
  soc_{handle,tweet,tg,dom}_mig   how many of those migrated before t
  soc_creator_handle  the creator's earlier coins with the same X handle
  soc_handle_is_name  1 when the X handle equals the coin's symbol or name (letters and digits, lower case), NaN
                      without a handle
  soc_burst10, soc_burst60  coins created in the last 10 and 60 minutes before this one that point at the same tweet
                      id or the same X handle (each coin once): a narrative race
"""

from __future__ import annotations

import bisect
import collections
import re

NAN = float("nan")
X_KINDS = ("none", "profile", "status", "community", "search", "other")    # collector.X_KINDS
KEYS = ("handle", "tweet", "tg", "dom")
COLS = {"handle": "x_handle", "tweet": "x_tweet", "tg": "tg_handle", "dom": "web_domain"}   # the meta row's columns
META_KEYS = ("x_kind",) + tuple(COLS.values())
KEEP_MS = 14 * 86_400_000                    # earlier coins remembered
WARM_DAYS = 14                               # the paper books' warm-up from the record at start (live.py)
BURSTS_MS = (("soc_burst10", 10 * 60_000), ("soc_burst60", 60 * 60_000))
SOCIAL_FEATURES = (["soc_known", "soc_x_kind"] + [f"soc_{k}_{x}" for k in KEYS for x in ("prev", "mig")]
                   + ["soc_creator_handle", "soc_handle_is_name"] + [n for n, _ in BURSTS_MS])
_ALNUM = re.compile(r"[^a-z0-9]")


def norm(s: str | None) -> str:
    return _ALNUM.sub("", (s or "").lower())


class Rec:
    __slots__ = ("t0", "mint", "creator", "mig_t")

    def __init__(self, t0: int, mint: str, creator: str, mig_t: int | None = None):
        self.t0, self.mint, self.creator, self.mig_t = t0, mint, creator, mig_t


class Key:
    """The coins of one value (one handle, tweet, telegram handle or domain), in creation order."""
    __slots__ = ("t0s", "recs", "n_mig", "creators")

    def __init__(self):
        self.t0s: list[int] = []
        self.recs: list[Rec] = []
        self.n_mig = 0                               # of recs, migrated so far
        self.creators: collections.Counter = collections.Counter()


class Tracker:
    def __init__(self, keep_ms: int = KEEP_MS):
        self.keep_ms = keep_ms
        self.keys: dict[tuple[str, str], Key] = {}
        self.of: dict[str, tuple[Rec, dict]] = {}    # mint -> (its record, its links)
        self.order: collections.deque = collections.deque()   # (t0, mint) as added, for pruning

    # ------------------------------------------------------------ events
    def meta(self, mint: str, t0: int, creator: str, flags: dict, mig_t: int | None = None) -> None:
        """A coin's metadata received (once per coin; a failed fetch is no row here)."""
        if mint in self.of or not flags.get("ok"):
            return
        links = {k: flags.get(c) for k, c in COLS.items() if flags.get(c)}
        rec = Rec(int(t0), mint, creator or "", mig_t)
        self.of[mint] = (rec, links)
        self.order.append((rec.t0, mint))
        for k, v in links.items():
            key = self.keys.get((k, v))
            if key is None:
                key = self.keys[(k, v)] = Key()
            i = bisect.bisect_right(key.t0s, rec.t0)
            key.t0s.insert(i, rec.t0)
            key.recs.insert(i, rec)
            key.creators[rec.creator] += 1
            key.n_mig += rec.mig_t is not None
        self.prune(rec.t0)

    def migrated(self, mint: str, t: int) -> None:
        got = self.of.get(mint)
        if got is None or got[0].mig_t is not None:
            return
        got[0].mig_t = int(t)
        for k, v in got[1].items():
            self.keys[(k, v)].n_mig += 1

    def prune(self, now: int) -> None:
        """Forget the coins created more than keep_ms before now (the oldest of each value go first)."""
        lim = now - self.keep_ms
        while self.order and self.order[0][0] < lim:
            _, mint = self.order.popleft()
            rec, links = self.of.pop(mint)
            for k, v in links.items():
                key = self.keys[(k, v)]
                i = key.recs.index(rec)
                del key.t0s[i], key.recs[i]
                key.creators[rec.creator] -= 1
                key.n_mig -= rec.mig_t is not None
                if not key.recs:
                    del self.keys[(k, v)]

    # ------------------------------------------------------------ reading
    def features(self, tok, t: float) -> dict:
        """The social features of `tok` as known at t (tok: a tokens.Token, its meta set by sim.Engine.meta)."""
        f = dict.fromkeys(SOCIAL_FEATURES, NAN)
        m = tok.meta if tok.meta is not None and tok.meta_t is not None and tok.meta_t <= t else None
        if not m or not m.get("ok"):
            f["soc_known"] = 0.0
            return f
        f["soc_known"] = 1.0
        kind = m.get("x_kind")
        f["soc_x_kind"] = float(X_KINDS.index(kind)) if kind in X_KINDS else NAN
        t0 = int(tok.t0)
        hits = {}
        for k, col in COLS.items():
            v = m.get(col)
            key = self.keys.get((k, v)) if v else None
            if key is None:
                f[f"soc_{k}_prev"] = f[f"soc_{k}_mig"] = 0.0
                if k == "handle":
                    f["soc_creator_handle"] = 0.0
                continue
            i = bisect.bisect_left(key.t0s, t0)          # the coins created before this one
            later = key.recs[i:]
            f[f"soc_{k}_prev"] = float(i)
            f[f"soc_{k}_mig"] = float(key.n_mig - sum(r.mig_t is not None for r in later))
            if k == "handle":
                f["soc_creator_handle"] = float(key.creators[tok.creator] - sum(r.creator == tok.creator
                                                                                 for r in later))
            if k in ("handle", "tweet"):
                hits[k] = (key, i)
        h = m.get(COLS["handle"])
        f["soc_handle_is_name"] = (float(norm(h) in {norm(tok.symbol), norm(tok.name)} - {""})) if h else NAN
        for name, w in BURSTS_MS:
            seen = set()
            for key, i in hits.values():
                j = bisect.bisect_left(key.t0s, t0 - w)
                seen.update(r.mint for r in key.recs[j:i])
            f[name] = float(len(seen))
        return f


def warm(days: list[str], root=None, keep_ms: int = KEEP_MS) -> Tracker:
    """A tracker that already knows the coins of the record's earlier days (their metadata, creator and
    migration), in time order, as the engine would have learned them."""
    import polars as pl

    from . import store
    tr = Tracker(keep_ms)
    if not days:
        return tr
    me = store.read("meta", days, root)
    if not len(me) or "x_kind" not in me.columns:
        return tr
    me = me.filter(pl.col("ok").fill_null(False)).unique("mint", keep="first", maintain_order=True)
    cr = store.read("creates", days, root).select("mint", pl.col("t").alias("t0"), "creator").unique(
        "mint", keep="first")
    mg = store.read("other", days, root).filter(pl.col("kind") == "migrate").group_by("mint").agg(
        pl.col("t").min().alias("mig_t"))
    rows = me.join(cr, on="mint").join(mg, on="mint", how="left").sort("t")
    for r in rows.iter_rows(named=True):
        mig = r["mig_t"] if r["mig_t"] is not None and r["mig_t"] <= r["t"] else None
        tr.meta(r["mint"], r["t0"], r["creator"], r, mig)
        if r["mig_t"] is not None and mig is None:
            tr.migrated(r["mint"], r["mig_t"])
    return tr
