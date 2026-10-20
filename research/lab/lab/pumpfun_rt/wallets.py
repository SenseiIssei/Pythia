"""Wallet reputation, kept point in time as the stream goes (plan addendum 2).

Per wallet: its early buys (one of the first EARLY_N outside buyers of a token,
within EARLY_S seconds of the creation), how many of those tokens later
completed their curve (counted when the completion is seen), and how many it
sold within FLIP_S seconds of buying (a flip). With the creator history
(tokens.CreatorBook: repeat dumpers) this gives, at any time t, what was known
about the wallets that bought a token early:

  smart       3+ early buys, of which 2+ and 20 %+ completed
  flipper     5+ early buys, 60 %+ of them flipped
  dumper      a creator that dumped 2+ of its tokens

Bounded: the least recently active wallets are forgotten (WALLETS_MAX).
"""

from __future__ import annotations

import collections
import math

EARLY_N = 20
EARLY_S = 30
FLIP_S = 30
WALLETS_MAX = 400_000
SMART_MIN_EARLY, SMART_MIN_MIG, SMART_MIN_RATE = 3, 2, 0.20
FLIP_MIN_EARLY, FLIP_MIN_RATE = 5, 0.60
KNOWN_MIN = 3
SHRINK_PRIOR, SHRINK_N = 0.03, 10
DUMPER_MIN = 2

WALLET_FEATURES = ["w_early_known", "w_smart_n", "w_flipper_share", "w_early_mig_rate", "w_dumper_buyers",
                   "w_creator_early", "w_creator_early_mig"]


def smart(r) -> bool:
    return r is not None and r[0] >= SMART_MIN_EARLY and r[1] >= SMART_MIN_MIG and r[1] / r[0] >= SMART_MIN_RATE


def flipper(r) -> bool:
    return r is not None and r[0] >= FLIP_MIN_EARLY and r[2] / r[0] >= FLIP_MIN_RATE


def shrunk_rate(r) -> float:
    early, mig = (r[0], r[1]) if r is not None else (0, 0)
    return (mig + SHRINK_PRIOR * SHRINK_N) / (early + SHRINK_N)


class WalletBook:
    """[early buys, of them completed, of them flipped] per wallet."""

    def __init__(self, cap: int = WALLETS_MAX):
        self.cap = cap
        self.rows: collections.OrderedDict[str, list] = collections.OrderedDict()

    def get(self, w: str):
        return self.rows.get(w)

    def _row(self, w: str) -> list:
        r = self.rows.get(w)
        if r is None:
            r = self.rows[w] = [0, 0, 0]
            if len(self.rows) > self.cap:
                self.rows.popitem(last=False)
        else:
            self.rows.move_to_end(w)
        return r

    def early(self, w: str) -> None:
        self._row(w)[0] += 1

    def completed(self, w: str) -> None:
        r = self.rows.get(w)
        if r is not None:
            r[1] += 1

    def flipped(self, w: str) -> None:
        r = self.rows.get(w)
        if r is not None:
            r[2] += 1

    def to_json(self) -> dict:
        return {"rows": dict(self.rows)}

    @classmethod
    def from_json(cls, d: dict) -> "WalletBook":
        b = cls()
        for k, v in (d.get("rows") or {}).items():
            if isinstance(v, list) and len(v) == 3:
                b.rows[k] = [int(x) for x in v]
        return b


class EarlyBuyers:
    """One token's early buyers with what was known of each when it bought."""

    __slots__ = ("wallets", "first_ms", "known", "smart", "flippers", "rate_sum", "dumpers", "flipped")

    def __init__(self):
        self.wallets: dict[str, int] = {}          # wallet -> its first buy time
        self.known = self.smart = self.flippers = self.dumpers = 0
        self.rate_sum = 0.0
        self.flipped: set = set()

    def add(self, w: str, t: int, book: WalletBook, creators) -> bool:
        if w in self.wallets or len(self.wallets) >= EARLY_N:
            return False
        r = book.get(w)
        self.wallets[w] = t
        if r is not None and r[0] >= KNOWN_MIN:
            self.known += 1
        self.smart += int(smart(r))
        self.flippers += int(flipper(r))
        self.rate_sum += shrunk_rate(r)
        if creators is not None:
            c = creators.rows.get(w)
            if c is not None and c[2] >= DUMPER_MIN:
                self.dumpers += 1
        book.early(w)
        return True

    def sold(self, w: str, t: int, book: WalletBook) -> None:
        t0 = self.wallets.get(w)
        if t0 is not None and w not in self.flipped and t - t0 <= FLIP_S * 1000:
            self.flipped.add(w)
            book.flipped(w)

    def features(self, creator_row) -> dict:
        n = len(self.wallets)
        nan = float("nan")
        return {"w_early_known": float(self.known), "w_smart_n": float(self.smart),
                "w_flipper_share": self.flippers / n if n else nan,
                "w_early_mig_rate": self.rate_sum / n if n else nan,
                "w_dumper_buyers": float(self.dumpers),
                "w_creator_early": float(creator_row[0]) if creator_row is not None else 0.0,
                "w_creator_early_mig": float(creator_row[1]) if creator_row is not None else 0.0}


def empty_features() -> dict:
    return {k: math.nan for k in WALLET_FEATURES}


def warm(days: list[str], root=None, book: WalletBook | None = None) -> WalletBook:
    """The wallet history from earlier days: early buys, their completions and flips
    (a summary, all of it before the record the study replays)."""
    import polars as pl
    from . import store
    book = book or WalletBook()
    if not days:
        return book
    cr = store.read("creates", days, root)
    if cr.height == 0:
        return book
    cr = cr.select("mint", pl.col("t").alias("t0"), "creator", pl.col("user").alias("payer"))
    tr = store.read("trades", days, root).select("t", "mint", "user", "buy")
    done = store.read("other", days, root)
    done = set(done.filter(pl.col("kind") == "complete")["mint"].to_list()) if done.height else set()
    x = tr.join(cr, on="mint").filter((pl.col("t") - pl.col("t0") <= EARLY_S * 1000)
                                      & (pl.col("user") != pl.col("creator"))
                                      & (pl.col("user") != pl.col("payer").fill_null("")))
    first = (x.filter(pl.col("buy")).group_by(["mint", "user"]).agg(pl.col("t").min().alias("tb"))
             .sort("tb").with_columns(pl.col("tb").rank("ordinal").over("mint").alias("k"))
             .filter(pl.col("k") <= EARLY_N))
    sells = tr.filter(~pl.col("buy")).group_by(["mint", "user"]).agg(pl.col("t").min().alias("ts"))
    first = first.join(sells, on=["mint", "user"], how="left").sort("tb")
    for r in first.iter_rows(named=True):
        w = r["user"]
        book.early(w)
        if r["mint"] in done:
            book.completed(w)
        if r["ts"] is not None and r["ts"] - r["tb"] <= FLIP_S * 1000:
            book.flipped(w)
    return book
