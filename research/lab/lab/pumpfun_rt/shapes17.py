"""Y17: the shape of a coin's first 10, 30, 60 and 120 s as a sequence, an analog search and a small sequence model
against Y10's early model, and two realistic paper twins with a shape veto. PAPER ONLY.

    python -m lab.pumpfun_rt.shapes17 build --out DIR   the sequences and labels of every coin, DIR/shapes17.npz
    python -m lab.pumpfun_rt.shapes17 run --out DIR     the walk-forward, the twins, DIR/shapes17.{json,md}

Pre-registered in results/pumpfun_shapes_y17_prereg.md. The sequences (paths): per coin one row a second for its
first 120 s, from the curve trades the collector had received by the end of each second after the creation was
received (receive time, never slot time: what we knew then; the price is the state of the latest slot received), in
CHANNELS. The labels (labels) from the decision at H: completes within 1 h, half the price gone within 10 minutes,
the log peak within 1 h and the second of the highest price within 10 minutes, with the price on a 10 s grid for the
exit test. The models (walk) per UTC test day on the coins of the days before whose label window closed before it:
the analog search (Analog), a numpy 1D CNN (CNN, no torch in the image) and Y10's early model (exitpol.trend_features,
model.fit) on the same coins' early rows. The twins (twins): the base books' realistic paper trades from the ledger
(R1's execution on the live stream) less what the CNN of the signal's day vetoes, judged by R2's bar
(smallwallet.expectation and simulate). Nothing here holds a wallet, reads a key, signs or sends anything.
"""

from __future__ import annotations

import argparse
import csv
import heapq
import json
import math
import sys
import time
import warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from . import curve as C
from .tokens import SUPPLY

# ---------------------------------------------------------------- registered (results/pumpfun_shapes_y17_prereg.md)

HORIZONS = (10, 30, 60, 120)
T_MAX = max(HORIZONS)
CHANNELS = ("lp", "buys", "sells", "buy_sol", "sell_sol", "ubuyers", "dev_buy_sol", "dev_sell_sol", "top_sell_sol",
            "top_share", "dev_share", "progress")
TOP_N = 5
LABELS = ("mig", "rug", "peak", "exit_s")
MIG_MS = 3_600_000                          # completes within 1 h of the creation
RUG_MS = 600_000                            # half the price gone within 10 minutes after H
RUG_SHARE = 0.5
PEAK_MS = 3_600_000
EXIT_MS = 600_000
GRID_S = 10                                 # the exit test's price grid after H, 0 to 600 s
GRID = EXIT_MS // 1000 // GRID_S + 1
TEST_DAYS = ("2026-10-22", "2026-10-23", "2026-10-24", "2026-10-25", "2026-10-26")
EARLY_KIND = {10: 1, 30: 3, 60: 4, 120: 4}  # early.KINDS index of the row the baseline reads at H (t10, t30, t60)
ANALOG_K, ANALOG_POINTS, ANALOG_DIMS = 50, 20, 16
CNN_FILTERS, CNN_WIDTH, CNN_DENSE, CNN_BATCH, CNN_EPOCHS, CNN_LR = 16, 5, 32, 512, 6, 3e-3
SEED = 20261027
BOOT, BAND = 1_000, 0.90
ALPHA = 0.05
BASES = ("P_pool5_top30t_sw10o3n", "P_pool0_wait_norug")
TWIN_DAYS = ("2026-10-24", "2026-10-25", "2026-10-26")
VETOES = {"V1": ("rug", 0.80, "above"), "V2": ("peak", 0.20, "below")}
STAKE_SOL = 0.1
WALLET = dict(start=0.55, share=0.10, max_open=3, brake=False, paths=2_000, horizon=30)
DAY_MS = 86_400_000
NAN = float("nan")
P0 = C.price(30 * C.LAMPORTS, 1_073_000_000 * C.TOKEN_UNIT)    # a fresh curve's price when the create row has none


def day_start(d: str) -> int:
    return int(datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)


def day_of(ms: float) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d")


# ---------------------------------------------------------------- the sequences

def coin_path(t0: int, creator: str, rt0: int, p0: float, trades) -> np.ndarray:
    """One coin's (T_MAX, len(CHANNELS)) path. `trades`: (t, slot, tx, buy, sol, tok, user, vs, vt, rt) of its curve
    trades in the order received (t ascending); only those received before t0 + T_MAX s are read. Row s is what was
    known at the end of second s: a trade received at t counts in second floor((t - t0) / 1000) (0 when received
    before the creation), the price is that of the latest (slot, tx) received so far, the top holders are the
    TOP_N largest balances other than the creator's at the start of the second."""
    out = np.zeros((T_MAX, len(CHANNELS)), dtype=np.float32)
    hold: dict[str, int] = {}
    buyers: set = set()
    last = (-1, -1)
    lp, prog = 0.0, 0.0
    sec = np.zeros(7)                           # buys, sells, buy sol, sell sol, dev buy, dev sell, top sell (SOL)
    top: set = set()
    cur = -1

    def close(s: int) -> None:
        tops = heapq.nlargest(TOP_N, (v for w, v in hold.items() if w != creator))
        out[s] = (lp, math.log1p(sec[0]), math.log1p(sec[1]), math.log1p(sec[2]), math.log1p(sec[3]),
                  math.log1p(len(buyers)), math.log1p(sec[4]), math.log1p(sec[5]), math.log1p(sec[6]),
                  max(0, sum(tops)) / SUPPLY, max(0, hold.get(creator, 0)) / SUPPLY, prog)

    for t, slot, tx, buy, sol, tok, user, vs, vt, rt in trades:
        s = max(0, int((t - t0) // 1000))
        if s >= T_MAX:
            break
        if s != cur:
            for k in range(cur, s):                 # close the seconds before (no trade: the state carried)
                if k >= 0:
                    close(k)
                    sec[:] = 0
            cur = s
            top = {w for w, _ in heapq.nlargest(TOP_N, ((w, v) for w, v in hold.items() if w != creator),
                                                key=lambda x: x[1])}
        sol_ = (sol or 0) / C.LAMPORTS
        if buy:
            sec[0] += 1
            sec[2] += sol_
            buyers.add(user)
            hold[user] = hold.get(user, 0) + int(tok or 0)
            if user == creator:
                sec[4] += sol_
        else:
            sec[1] += 1
            sec[3] += sol_
            hold[user] = hold.get(user, 0) - int(tok or 0)
            if user == creator:
                sec[5] += sol_
            elif user in top:
                sec[6] += sol_
        key = (slot if slot is not None else -1, tx if tx is not None else -1)
        if key >= last and vs and vt:
            last = key
            lp = math.log(max(C.price(vs, vt), 1e-30) / p0)
            prog = C.progress(int(rt), rt0) if rt is not None else prog
    for k in range(max(cur, 0), T_MAX):
        close(k)
        sec[:] = 0
    return out


def lp_frame(trades, amm, p0_of):
    """Every price the record shows per coin, as received: (mint, t, lp) with lp the log price over the coin's
    starting price, curve trades at their reserves after the trade, pool trades at the pool's effective reserves
    after the trade."""
    import polars as pl
    p0 = pl.DataFrame({"mint": list(p0_of), "p0": list(p0_of.values())})
    cur = (trades.filter((pl.col("vs") > 0) & (pl.col("vt") > 0))
           .select("mint", "t", (pl.col("vs") / C.LAMPORTS / (pl.col("vt") / C.TOKEN_UNIT)).alias("px")))
    out = [cur]
    if amm is not None and amm.height:
        if "vq" not in amm.columns:                                # parts written before vq was recorded
            amm = amm.with_columns(pl.lit(None, dtype=pl.Int64).alias("vq"))
        q = (pl.col("pq") + pl.col("vq").fill_null(0)).clip(lower_bound=0)
        qa = pl.when(pl.col("buy")).then(q + pl.col("quote")).otherwise(q - pl.col("quote"))
        ba = pl.when(pl.col("buy")).then(pl.col("pb") - pl.col("base")).otherwise(pl.col("pb") + pl.col("base"))
        out.append(amm.filter(pl.col("pb") > 0).select("mint", "t", (qa / C.LAMPORTS / (ba / C.TOKEN_UNIT)).alias("px"))
                   .filter(pl.col("px") > 0))
    f = pl.concat(out).join(p0, on="mint").select("mint", "t", (pl.col("px") / pl.col("p0")).log().alias("lp"))
    return f.sort(["mint", "t"])


def labels(coins, lp, completes) -> dict[str, np.ndarray]:
    """Per coin (rows of `coins`: mint, t0, lp_h<H> the last known log price at each H) and H: mig, rug, peak, exit_s
    and the grid (log price over the price at H every GRID_S s after H, the last price received by then). `completes`:
    mint -> the first completion's receive time."""
    import polars as pl
    n = coins.height
    out = {k: np.full((n, len(HORIZONS)), NAN, dtype=np.float32) for k in LABELS}
    out["grid"] = np.full((n, len(HORIZONS), GRID), NAN, dtype=np.float32)
    comp = np.array([completes.get(m, math.inf) for m in coins["mint"].to_list()], dtype=float)
    t0 = coins["t0"].to_numpy().astype(float)
    base = coins.select("mint", "t0").with_row_index("i")
    lp_t = lp.select("mint", "t", "lp").sort("t")
    for j, h in enumerate(HORIZONS):
        th = t0 + h * 1000
        done = comp < th
        out["mig"][:, j] = np.where(done, NAN, (comp <= t0 + MIG_MS).astype(np.float32))
        lph = coins[f"lp_h{h}"].to_numpy().astype(float)
        c = base.with_columns(pl.Series("th", th.astype(np.int64)), pl.Series("lph", lph))
        x = (lp.join(c, on="mint").filter((pl.col("t") >= pl.col("th")) & (pl.col("t") < pl.col("th") + PEAK_MS))
             .with_columns(((pl.col("t") - pl.col("th")) // 1000).alias("s"),
                           (pl.col("lp") - pl.col("lph")).alias("r")))
        w10 = pl.col("s") < EXIT_MS // 1000
        g = x.group_by("i").agg(pl.col("r").max().alias("pk"), pl.col("r").filter(w10).min().alias("lo"),
                                pl.col("r").filter(w10).max().alias("hi"))
        g = g.join(x.filter(w10).join(g.select("i", "hi"), on="i").filter(pl.col("r") == pl.col("hi"))
                   .group_by("i").agg(pl.col("s").min().alias("at")), on="i", how="left")
        pk, lo, hi, at = (np.zeros(n), np.zeros(n), np.zeros(n), np.zeros(n))
        idx = g["i"].to_numpy()
        pk[idx] = g["pk"].fill_null(0).to_numpy()
        lo[idx] = g["lo"].fill_null(0).to_numpy()
        hi[idx] = g["hi"].fill_null(0).to_numpy()
        at[idx] = g["at"].fill_null(0).to_numpy()
        ok = np.isfinite(lph)
        out["peak"][:, j] = np.where(ok, np.maximum(pk, 0.0), NAN)
        out["rug"][:, j] = np.where(ok, (lo <= math.log(RUG_SHARE)).astype(np.float32), NAN)
        out["exit_s"][:, j] = np.where(ok, np.where(hi > 0, at, 0.0), NAN)
        q = pl.DataFrame({"i": np.repeat(np.arange(n), GRID).astype(np.uint32),
                          "k": np.tile(np.arange(GRID), n).astype(np.int32)})
        q = (q.join(c, on="i").with_columns((pl.col("th") + pl.col("k") * GRID_S * 1000).alias("t"))
             .sort("t"))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)           # sorted by t over all coins, so within each too
            y = q.join_asof(lp_t, on="t", by="mint", strategy="backward")
        y = y.filter(pl.col("t") > pl.col("th"))                # k = 0 is the price at H
        gi, gk = y["i"].to_numpy(), y["k"].to_numpy()
        val = (y["lp"] - y["lph"]).to_numpy()
        gr = np.zeros((n, GRID), dtype=np.float32)
        gr[gi, gk] = np.where(np.isfinite(val), val, 0.0)
        # a later grid point before the first trade after H keeps the price at H (0); a missing asof is 0 too
        out["grid"][:, j, :] = np.where(ok[:, None], gr, NAN)
    return out


def build_day(day: str, mints: set[str] | None, extra: set[str], root=None, log=print) -> dict | None:
    """The coins created on `day` that are in `mints` (None: every coin) or in `extra`: their paths, labels, the last
    known log price at each H and their creation time."""
    import polars as pl
    from . import store
    nd = (datetime.strptime(day, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    have = set(store.days(root))
    rd = [d for d in (day, nd) if d in have]
    cr = store.read("creates", [day], root).sort("t").unique("mint", keep="first", maintain_order=True)
    want = (set(cr["mint"].to_list()) if mints is None else mints) | extra
    cr = cr.filter(pl.col("mint").is_in(list(want)))
    if cr.height == 0:
        return None
    t_hi = int(cr["t"].max()) + T_MAX * 1000 + PEAK_MS + 1
    keep = pl.col("mint").is_in(cr["mint"].implode())
    tr = (store.read("trades", rd, root).filter(keep & (pl.col("t") < t_hi))
          .select("t", "slot", "tx", "mint", "buy", "sol", "tok", "user", "vs", "vt", "rt").sort(["mint", "t"]))
    amm = store.read("amm", rd, root).filter(keep & (pl.col("t") < t_hi))
    oth = store.read("other", rd, root).filter((pl.col("kind") == "complete") & keep)
    completes = dict(oth.group_by("mint").agg(pl.col("t").min()).iter_rows())
    p0_of, rows = {}, []
    for r in cr.iter_rows(named=True):
        p = C.price(r["vs"], r["vt"]) if r.get("vs") and r.get("vt") else P0
        p0_of[r["mint"]] = p
        rows.append((r["mint"], int(r["t"]), r.get("creator") or r.get("user") or "",
                     int(r["rt"]) if r.get("rt") else C.INITIAL_RT))
    t0_of = pl.DataFrame({"mint": [r[0] for r in rows], "t0": [r[1] for r in rows]})
    early = (tr.join(t0_of, on="mint").filter(pl.col("t") < pl.col("t0") + T_MAX * 1000)
             .sort(["mint", "t"], maintain_order=True))
    cols = [early[c].to_list() for c in ("t", "slot", "tx", "buy", "sol", "tok", "user", "vs", "vt", "rt")]
    mint_col = early["mint"].to_list()
    starts: dict[str, tuple[int, int]] = {}
    i = 0
    while i < len(mint_col):
        j = i
        m = mint_col[i]
        while j < len(mint_col) and mint_col[j] == m:
            j += 1
        starts[m] = (i, j)
        i = j
    paths = np.zeros((len(rows), T_MAX, len(CHANNELS)), dtype=np.float32)
    t0s = np.zeros(len(rows), dtype=np.int64)
    for k, (m, t0, creator, rt0) in enumerate(rows):
        a, b = starts.get(m, (0, 0))
        paths[k] = coin_path(t0, creator, rt0, p0_of[m], zip(*(c[a:b] for c in cols)))
        t0s[k] = t0
    coins = pl.DataFrame({"mint": [r[0] for r in rows], "t0": t0s,
                          **{f"lp_h{h}": paths[:, h - 1, 0].astype(float) for h in HORIZONS}})
    lab = labels(coins, lp_frame(tr, amm, p0_of), completes)
    log(f"shapes17: {day}: {len(rows):,} coins, {tr.height:,} curve trades, {amm.height:,} pool trades")
    return {"mint": np.array([r[0] for r in rows]), "t0": t0s, "paths": paths, **lab}


def early_table(root=None) -> tuple[dict, dict]:
    """rows/early.parquet's rows not dropped for a gap, by (mint, kind): the row index, and the frame (Y10's
    features, numpy)."""
    import polars as pl
    from .. import data as D
    from . import exitpol as XP
    d = Path(root) if root else D.ROOT / "pumpfun_rt"
    mints = json.loads((d / "rows" / "early.json").read_text(encoding="utf-8"))["mints"]
    feats = XP.trend_features()
    fr = pl.read_parquet(d / "rows" / "early.parquet").filter(pl.col("dropped") == 0)
    have = [c for c in feats if c in fr.columns]
    fr = fr.select(["t", "tid", "kind"] + have)
    X = {c: fr[c].to_numpy().astype(float) for c in fr.columns}
    tid = X["tid"].astype(int)
    key = {(mints[a], int(k)): i for i, (a, k) in enumerate(zip(tid, X["kind"].astype(int))) if 0 <= a < len(mints)}
    return key, X


def build(out: Path, root=None, log=print) -> Path:
    """Every day's coins with an early row at 10 s and every coin a base book signalled, into out/shapes17.npz."""
    from . import store
    key, _ = early_table(root)
    with_row = {m for (m, k) in key if k == EARLY_KIND[10]}
    led = ledger_entries()
    extra = {e["mint"] for es in led.values() for e in es}
    parts = []
    for day in store.days(root):
        r = build_day(day, with_row, extra, root, log)
        if r is not None:
            parts.append(r)
    keys = parts[0].keys()
    data = {k: np.concatenate([p[k] for p in parts]) for k in keys}
    data["has_row"] = np.array([m in with_row for m in data["mint"]])
    out.mkdir(parents=True, exist_ok=True)
    f = out / "shapes17.npz"
    np.savez_compressed(f, **data)
    log(f"shapes17: {len(data['mint']):,} coins into {f}")
    return f


# ---------------------------------------------------------------- the sequence model (numpy)

class CNN:
    """Two 1D convolutions (CNN_FILTERS filters of width CNN_WIDTH, the second dilated 2, ReLU), the mean, max and
    last value over time, a dense ReLU layer and four heads: two logits (mig, rug; logistic loss) and two values
    (peak, exit_s standardised; squared error). A NaN target is left out of its head's loss. Adam."""

    def __init__(self, channels: int, seed: int = SEED, filters: int = CNN_FILTERS, width: int = CNN_WIDTH,
                 dense: int = CNN_DENSE):
        rng = np.random.default_rng(seed)
        f, k = filters, width
        he = lambda n_in, *shape: (rng.standard_normal(shape) * math.sqrt(2.0 / n_in)).astype(np.float64)  # noqa
        self.p = {"W1": he(k * channels, k * channels, f), "b1": np.zeros(f), "W2": he(k * f, k * f, f),
                  "b2": np.zeros(f), "Wd": he(3 * f, 3 * f, dense), "bd": np.zeros(dense),
                  "Wo": he(dense, dense, 4) * 0.5, "bo": np.zeros(4)}
        self.k, self.dil = k, (1, 2)
        self.m = {n: np.zeros_like(v) for n, v in self.p.items()}
        self.v = {n: np.zeros_like(v) for n, v in self.p.items()}
        self.step = 0
        self.mu = self.sd = None
        self.ty = None

    @staticmethod
    def _cols(X, k, d):
        pad = (k - 1) // 2 * d
        T = X.shape[1]
        Xp = np.pad(X, ((0, 0), (pad, pad), (0, 0)))
        return np.stack([Xp[:, j * d:j * d + T, :] for j in range(k)], axis=2)       # (B, T, k, C)

    def forward(self, X):
        p, k = self.p, self.k
        B, T, _ = X.shape
        c1 = self._cols(X, k, self.dil[0])
        z1 = c1.reshape(B * T, -1) @ p["W1"] + p["b1"]
        h1 = np.maximum(z1, 0).reshape(B, T, -1)
        c2 = self._cols(h1, k, self.dil[1])
        z2 = c2.reshape(B * T, -1) @ p["W2"] + p["b2"]
        h2 = np.maximum(z2, 0).reshape(B, T, -1)
        am = h2.argmax(axis=1)
        g = np.concatenate([h2.mean(axis=1), h2.max(axis=1), h2[:, -1]], axis=1)
        z3 = g @ p["Wd"] + p["bd"]
        h3 = np.maximum(z3, 0)
        o = h3 @ p["Wo"] + p["bo"]
        return o, (X, c1, z1, h1, c2, z2, h2, am, g, z3, h3)

    @staticmethod
    def loss(o, Y):
        """The mean loss over the known targets of each head, summed over the heads, and its gradient."""
        d = np.zeros_like(o)
        total = 0.0
        for j in range(4):
            m = np.isfinite(Y[:, j])
            n = int(m.sum())
            if not n:
                continue
            if j < 2:
                z = o[m, j]
                pr = 1 / (1 + np.exp(-np.clip(z, -30, 30)))
                y = Y[m, j]
                total += float(np.mean(np.logaddexp(0, z) - y * z))
                d[m, j] = (pr - y) / n
            else:
                e = o[m, j] - Y[m, j]
                total += float(np.mean(e ** 2))
                d[m, j] = 2 * e / n
        return total, d

    def backward(self, cache, do):
        p, k = self.p, self.k
        X, c1, z1, h1, c2, z2, h2, am, g, z3, h3 = cache
        B, T, F = h2.shape
        gr = {"Wo": h3.T @ do, "bo": do.sum(axis=0)}
        dz3 = (do @ p["Wo"].T) * (z3 > 0)
        gr["Wd"], gr["bd"] = g.T @ dz3, dz3.sum(axis=0)
        dg = dz3 @ p["Wd"].T
        dh2 = np.repeat(dg[:, None, :F] / T, T, axis=1)
        np.add.at(dh2, (np.arange(B)[:, None], am, np.arange(F)[None, :]), dg[:, F:2 * F])
        dh2[:, -1] += dg[:, 2 * F:]
        dz2 = (dh2.reshape(B * T, F)) * (z2 > 0)
        gr["W2"], gr["b2"] = c2.reshape(B * T, -1).T @ dz2, dz2.sum(axis=0)
        dh1 = self._uncols((dz2 @ p["W2"].T).reshape(B, T, k, -1), k, self.dil[1], T)
        dz1 = dh1.reshape(B * T, -1) * (z1 > 0)
        gr["W1"], gr["b1"] = c1.reshape(B * T, -1).T @ dz1, dz1.sum(axis=0)
        return gr

    @staticmethod
    def _uncols(dc, k, d, T):
        pad = (k - 1) // 2 * d
        B, _, _, F = dc.shape
        dXp = np.zeros((B, T + 2 * pad, F))
        for j in range(k):
            dXp[:, j * d:j * d + T, :] += dc[:, :, j, :]
        return dXp[:, pad:pad + T, :]

    def _adam(self, gr, lr, b1=0.9, b2=0.999, eps=1e-8):
        self.step += 1
        for n, gv in gr.items():
            self.m[n] = b1 * self.m[n] + (1 - b1) * gv
            self.v[n] = b2 * self.v[n] + (1 - b2) * gv * gv
            mh = self.m[n] / (1 - b1 ** self.step)
            vh = self.v[n] / (1 - b2 ** self.step)
            self.p[n] -= lr * mh / (np.sqrt(vh) + eps)

    def _x(self, X):
        return np.nan_to_num((X - self.mu) / self.sd, nan=0.0, posinf=0.0, neginf=0.0)

    def fit(self, X, Y, epochs: int = CNN_EPOCHS, batch: int = CNN_BATCH, lr: float = CNN_LR, seed: int = SEED):
        """X (N, T, C) the paths, Y (N, 4): mig, rug, peak, exit_s (raw; the values standardised here)."""
        self.mu = X.reshape(-1, X.shape[2]).mean(axis=0)
        sd = X.reshape(-1, X.shape[2]).std(axis=0)
        self.sd = np.where(sd > 0, sd, 1.0)
        Y = np.asarray(Y, dtype=float).copy()
        self.ty = []
        for j in (2, 3):
            v = Y[:, j][np.isfinite(Y[:, j])]
            mu, s = (float(v.mean()), float(v.std()) or 1.0) if len(v) else (0.0, 1.0)
            self.ty.append((mu, s))
            Y[:, j] = (Y[:, j] - mu) / s
        rng = np.random.default_rng(seed)
        hist = []
        for _ in range(epochs):
            order = rng.permutation(len(X))
            tot = 0.0
            for a in range(0, len(X), batch):
                b = order[a:a + batch]
                o, cache = self.forward(self._x(X[b].astype(np.float64)))
                ls, do = self.loss(o, Y[b])
                self._adam(self.backward(cache, do), lr)
                tot += ls * len(b)
            hist.append(tot / max(len(X), 1))
        return hist

    def predict(self, X, batch: int = 4096) -> np.ndarray:
        """(N, 4): P(mig), P(rug), peak and exit_s on their own scale."""
        outs = []
        for a in range(0, len(X), batch):
            o, _ = self.forward(self._x(X[a:a + batch].astype(np.float64)))
            outs.append(o)
        o = np.concatenate(outs) if outs else np.zeros((0, 4))
        r = np.empty_like(o)
        r[:, :2] = 1 / (1 + np.exp(-np.clip(o[:, :2], -30, 30)))
        for i, j in enumerate((2, 3)):
            r[:, j] = o[:, j] * self.ty[i][1] + self.ty[i][0]
        return r


# ---------------------------------------------------------------- the analog search

def blocks(X: np.ndarray, points: int = ANALOG_POINTS) -> np.ndarray:
    """(N, T, C) to (N, min(T, points) * C): block means over time."""
    N, T, Cn = X.shape
    p = min(T, points)
    edges = np.linspace(0, T, p + 1).astype(int)
    return np.concatenate([X[:, edges[i]:edges[i + 1]].mean(axis=1) for i in range(p)], axis=1)


class Analog:
    """The ANALOG_K nearest training coins by Euclidean distance on PCA(ANALOG_DIMS) of the standardised block
    means; their mean mig, rug and peak and their median exit_s."""

    def fit(self, X, Y, k: int = ANALOG_K):
        from sklearn.decomposition import PCA
        from sklearn.neighbors import NearestNeighbors
        self.mu = X.reshape(-1, X.shape[2]).mean(axis=0)
        sd = X.reshape(-1, X.shape[2]).std(axis=0)
        self.sd = np.where(sd > 0, sd, 1.0)
        B = blocks((X - self.mu) / self.sd)
        self.pca = PCA(n_components=min(ANALOG_DIMS, B.shape[1], len(B)), random_state=SEED).fit(B)
        self.nn = NearestNeighbors(n_neighbors=min(k, len(B)), algorithm="brute").fit(self.pca.transform(B))
        self.Y = np.asarray(Y, dtype=float)
        return self

    def predict(self, X) -> np.ndarray:
        _, idx = self.nn.kneighbors(self.pca.transform(blocks((X - self.mu) / self.sd)))
        nb = self.Y[idx]                                    # (N, k, 4)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)       # a coin whose neighbours all lack a label: NaN
            return np.stack([np.nanmean(nb[:, :, 0], axis=1), np.nanmean(nb[:, :, 1], axis=1),
                             np.nanmean(nb[:, :, 2], axis=1), np.nanmedian(nb[:, :, 3], axis=1)], axis=1)


# ---------------------------------------------------------------- the baseline

def baseline_fit(X, Y, t):
    """Y10's early model per label: model.fit (LightGBM, isotonic) for mig and rug, the same parameters as a
    regressor for peak and exit_s; rows in time order. Returns a predict(X) -> (N, 4)."""
    import lightgbm as lgb
    from . import exitpol as XP
    from . import model as M
    o = np.argsort(t, kind="stable")
    X, Y = X[o], Y[o]
    feats = XP.trend_features()
    fits = []
    for j in range(4):
        m = np.isfinite(Y[:, j])
        if j < 2:
            fits.append(M.fit(X[m], Y[m, j], feats))
        elif m.sum() >= M.MIN_TRAIN:
            fits.append(lgb.LGBMRegressor(**M.PARAMS).fit(X[m], Y[m, j]))
        else:
            fits.append(float(np.nanmean(Y[:, j])) if m.any() else 0.0)

    def predict(Z):
        cols = []
        for f in fits:
            cols.append(np.full(len(Z), f) if isinstance(f, float) else f.predict(Z))
        return np.stack(cols, axis=1)
    return predict


# ---------------------------------------------------------------- the walk-forward

def targets(data: dict, j: int) -> np.ndarray:
    return np.stack([data[k][:, j] for k in LABELS], axis=1).astype(float)


def walk(data: dict, X_early: np.ndarray | None, days=TEST_DAYS, log=print, models=("cnn", "analog", "base"),
         queries: dict | None = None) -> dict:
    """Per test day and H: train on the coins with an early row created before the day whose label window closed
    before its start, predict the day's coins with an early row; `queries` {day: indices} are predicted by that
    day's CNN too (the twins), with the CNN's training predictions' quantiles for the vetoes."""
    t0 = data["t0"].astype(float)
    row = data["has_row"]
    n = len(t0)
    pred = {m: np.full((n, len(HORIZONS), 4), NAN) for m in models}
    qpred = {}
    cuts = {}
    for d in days:
        lo = day_start(d)
        te = row & (t0 >= lo) & (t0 < lo + DAY_MS)
        q = np.asarray((queries or {}).get(d, []), dtype=int)
        for j, h in enumerate(HORIZONS):
            tr = row & (t0 + (h * 1000 + PEAK_MS) < lo)
            if tr.sum() < 500 or (not te.any() and not len(q)):
                continue
            Xs = data["paths"][:, :h]
            Y = targets(data, j)
            t1 = time.time()
            if "cnn" in models:
                net = CNN(len(CHANNELS), seed=SEED + j)
                net.fit(Xs[tr], Y[tr])
                pred["cnn"][te, j] = net.predict(Xs[te])
                if len(q):
                    inn = net.predict(Xs[tr])
                    cuts[(d, h)] = {"rug": {p: float(np.quantile(inn[:, 1], p)) for p in (0.8,)},
                                    "peak": {p: float(np.quantile(inn[:, 2], p)) for p in (0.2,)}}
                    for i, v in zip(q, net.predict(Xs[q])):
                        qpred[(d, int(i), h)] = v
            if "analog" in models:
                pred["analog"][te, j] = Analog().fit(Xs[tr], Y[tr]).predict(Xs[te])
            if "base" in models and X_early is not None:
                Xe = X_early[:, j]
                ok = tr & np.isfinite(Xe).any(axis=1)
                pred["base"][te, j] = baseline_fit(Xe[ok], Y[ok], t0[ok])(Xe[te])
            log(f"shapes17: {d} H={h}: {int(tr.sum()):,} training, {int(te.sum()):,} test coins, "
                f"{time.time() - t1:.0f} s")
    return {"pred": pred, "qpred": qpred, "cuts": cuts}


# ---------------------------------------------------------------- measures with an hour-block bootstrap

def wauc(s: np.ndarray, y: np.ndarray, w: np.ndarray) -> np.ndarray:
    """AUC (ties half) for each row of weights w (D, N): sum over positives of the negatives' weight below plus half
    the tied, over the product of the weights."""
    o = np.argsort(s, kind="stable")
    s, y, w = s[o], y[o], w[:, o]
    u, inv = np.unique(s, return_inverse=True)
    wp = np.zeros((w.shape[0], len(u)))
    wn = np.zeros((w.shape[0], len(u)))
    for arr, mask in ((wp, y == 1), (wn, y == 0)):
        np.add.at(arr.T, inv[mask], w[:, mask].T)
    below = np.cumsum(wn, axis=1) - wn
    num = (wp * (below + 0.5 * wn)).sum(axis=1)
    den = wp.sum(axis=1) * wn.sum(axis=1)
    return np.where(den > 0, num / np.where(den > 0, den, 1), NAN)


def wspear(a: np.ndarray, b: np.ndarray, w: np.ndarray) -> np.ndarray:
    """Spearman for each row of weights: the weighted Pearson of the full sample's ranks."""
    from scipy.stats import rankdata
    ra, rb = rankdata(a), rankdata(b)
    sw = w.sum(axis=1, keepdims=True)
    ma, mb = (w @ ra)[:, None] / sw, (w @ rb)[:, None] / sw
    da, db = ra[None, :] - ma, rb[None, :] - mb
    cov = (w * da * db).sum(axis=1)
    va, vb = (w * da * da).sum(axis=1), (w * db * db).sum(axis=1)
    return cov / np.sqrt(np.maximum(va * vb, 1e-300))


def wmae(a, b, w):
    return (w @ np.abs(a - b)) / w.sum(axis=1)


def hour_draws(t0: np.ndarray, draws: int = BOOT, seed: int = SEED) -> tuple[np.ndarray, np.ndarray]:
    """Each row's UTC hour (an index) and (1 + draws, hours) counts: the sample itself, then the hours drawn with
    replacement. The same t0 and seed give the same draws, so two models are compared on the same ones."""
    hr = (np.asarray(t0, dtype=float) // 3_600_000).astype(np.int64)
    u, inv = np.unique(hr, return_inverse=True)
    rng = np.random.default_rng(seed)
    cnt = np.stack([np.bincount(rng.integers(0, len(u), len(u)), minlength=len(u)) for _ in range(draws)])
    return inv, np.vstack([np.ones(len(u)), cnt]).astype(float)


def measure(label: str, p: np.ndarray, y: np.ndarray, t0: np.ndarray, chunk: int = 50) -> np.ndarray:
    """The label's measure (higher is better: AUC, Spearman, or minus the mean absolute error) on the sample and on
    each hour-block draw, in chunks of draws (a draw is a weight per row)."""
    inv, cnt = hour_draws(t0)
    out = []
    for a in range(0, len(cnt), chunk):
        w = cnt[a:a + chunk][:, inv]
        if label in ("mig", "rug"):
            out.append(wauc(p, y, w))
        elif label == "peak":
            out.append(wspear(p, y, w))
        else:
            out.append(-wmae(p, y, w))
    return np.concatenate(out)


def holm(ps: list[float], alpha: float = ALPHA) -> list[bool]:
    o = np.argsort(ps)
    ok = [False] * len(ps)
    for r, i in enumerate(o):
        if ps[i] > alpha / (len(ps) - r):
            break
        ok[i] = True
    return ok


def evaluate(data: dict, wf: dict, days=TEST_DAYS) -> dict:
    """Per H and label: each model's measure on the test coins every model predicted, the difference of the CNN and
    of the analog search to the baseline with its band and one-sided p (hour blocks), Holm over all comparisons; for
    exit_s the exit test."""
    t0 = data["t0"].astype(float)
    lo, hi = day_start(days[0]), day_start(days[-1]) + DAY_MS
    pred = wf["pred"]
    rows, comps = [], []
    for j, h in enumerate(HORIZONS):
        Y = targets(data, j)
        for li, label in enumerate(LABELS):
            ok = data["has_row"] & (t0 >= lo) & (t0 < hi) & np.isfinite(Y[:, li])
            for m in pred:
                ok &= np.isfinite(pred[m][:, j, li])
            if ok.sum() < 50 or (label in ("mig", "rug") and len(set(Y[ok, li].tolist())) < 2):
                rows.append({"h": h, "label": label, "n": int(ok.sum())})
                continue
            vals = {m: measure(label, pred[m][ok, j, li], Y[ok, li], t0[ok]) for m in pred}
            r = {"h": h, "label": label, "n": int(ok.sum()), "rate": float(Y[ok, li].mean())}
            for m, v in vals.items():
                r[m] = float(v[0])
            for m in ("cnn", "analog"):
                if m not in vals or "base" not in vals:
                    continue
                dlt = vals[m] - vals["base"]
                bd = dlt[1:][np.isfinite(dlt[1:])]
                r[f"{m}_diff"] = float(dlt[0])
                r[f"{m}_band"] = [float(np.quantile(bd, (1 - BAND) / 2)), float(np.quantile(bd, (1 + BAND) / 2))]
                r[f"{m}_p"] = float((bd <= 0).mean())
                comps.append((len(rows), m, r[f"{m}_p"]))
            if label == "exit_s":
                r["exit"] = exit_test(data, wf, ok, j)
            rows.append(r)
    passed = holm([c[2] for c in comps])
    for (i, m, _), ok in zip(comps, passed):
        rows[i][f"{m}_holm"] = bool(ok)
        rows[i][f"{m}_beats"] = bool(ok and rows[i][f"{m}_band"][0] > 0)
    return {"rows": rows, "comparisons": len(comps)}


def exit_test(data: dict, wf: dict, ok: np.ndarray, j: int) -> dict:
    """The mean log price over the price at H when selling at each model's predicted second (rounded to the grid),
    at the median label second of the coins before the test days, and at the best second itself (the ceiling)."""
    t0 = data["t0"].astype(float)
    g = data["grid"][:, j, :].astype(float)
    prior = data["has_row"] & (t0 < day_start(TEST_DAYS[0])) & np.isfinite(data["exit_s"][:, j])
    med = float(np.median(data["exit_s"][prior, j])) if prior.any() else 0.0

    def at(sec):
        k = np.clip(np.rint(np.asarray(sec, dtype=float) / GRID_S), 0, GRID - 1).astype(int)
        return np.take_along_axis(g[ok], k[:, None], axis=1)[:, 0]
    out = {"median_s": med, "at_median": float(np.nanmean(at(np.full(int(ok.sum()), med)))),
           "at_best": float(np.nanmean(at(data["exit_s"][ok, j]))), "hold_600": float(np.nanmean(g[ok, -1]))}
    for m, p in wf["pred"].items():
        out[f"at_{m}"] = float(np.nanmean(at(np.clip(p[ok, j, 3], 0, EXIT_MS / 1000))))
    return out


MOVED = 0.05                                # the post-hoc subset: up 5 % or more over the start at H (log)


def references(data: dict, wf: dict, days=TEST_DAYS) -> list[dict]:
    """Not registered, descriptive: on the evaluation's test coins, one number at H against the models (the log
    price at H for rug and peak, the curve's progress for mig), on all of them and on the coins up MOVED or more at
    H (where a rug or a peak can happen at all)."""
    from scipy.stats import spearmanr
    t0 = data["t0"].astype(float)
    lo, hi = day_start(days[0]), day_start(days[-1]) + DAY_MS
    out = []
    for j, h in enumerate(HORIZONS):
        lp, prog = data["paths"][:, h - 1, CHANNELS.index("lp")], data["paths"][:, h - 1, CHANNELS.index("progress")]
        for li, label, ref in ((0, "mig", prog), (1, "rug", lp), (2, "peak", lp)):
            y = data[label][:, j].astype(float)
            ok = data["has_row"] & (t0 >= lo) & (t0 < hi) & np.isfinite(y)
            for m in wf["pred"]:
                ok &= np.isfinite(wf["pred"][m][:, j, li])
            for sub, mask in (("all", ok), ("moved", ok & (lp > MOVED))):
                yy = y[mask]
                if mask.sum() < 50 or (label != "peak" and len(set(yy.tolist())) < 2):
                    continue
                f = (lambda p_: float(wauc(p_, yy, np.ones((1, len(yy))))[0])) if label != "peak" else \
                    (lambda p_: float(spearmanr(p_, yy)[0]) if np.ptp(p_) > 0 and np.ptp(yy) > 0 else NAN)
                r = {"h": h, "label": label, "coins": sub, "n": int(mask.sum()), "one_number": f(ref[mask])}
                r.update({m: f(wf["pred"][m][mask, j, li]) for m in wf["pred"]})
                if label != "peak":
                    r["rate"] = float(yy.mean())
                out.append(r)
    return out


# ---------------------------------------------------------------- the twins

def ledger_entries(paper=None, books=BASES, days=TWIN_DAYS, taint: dict | None = None) -> dict[str, list[dict]]:
    """The base books' realistic paper trades signalled on `days`: closed trades from the ledger (the return at the
    book's own stake, at STAKE_SOL) and failed buys (their fee) from failed.csv. A closed trade the late-row bug made
    (P1, realistic.tainted) is skipped and counted per book in `taint` when given."""
    from .. import data as D
    from .realistic import tainted
    d = Path(paper) if paper else D.ROOT / "paper" / "pumpfun_rt"
    lo, hi = day_start(days[0]), day_start(days[-1]) + DAY_MS
    out = {b: [] for b in books}

    def num(x):
        try:
            return float(x)
        except (TypeError, ValueError):
            return NAN
    try:
        with open(d / "ledger.csv", newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                s = num(r.get("signal_ms"))
                if r.get("rule") in out and lo <= s < hi and r.get("stake_sol"):
                    if tainted(r):
                        if taint is not None:
                            taint[r["rule"]] = taint.get(r["rule"], 0) + 1
                        continue
                    ret = num(r.get("ret"))
                    out[r["rule"]].append({"mint": r["mint"], "created_ms": num(r.get("created_ms")), "signal_ms": s,
                                           "exit_ms": num(r.get("exit_ms")), "failed": False, "ret": ret,
                                           "pnl": ret * STAKE_SOL, "symbol": r.get("symbol")})
        with open(d / "failed.csv", newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                s = num(r.get("signal_ms"))
                if r.get("rule") in out and lo <= s < hi:
                    out[r["rule"]].append({"mint": r["mint"], "created_ms": NAN, "signal_ms": s,
                                           "exit_ms": num(r.get("land_ms")), "failed": True, "ret": NAN,
                                           "pnl": num(r.get("pnl_sol")), "why": r.get("why")})
    except OSError:
        pass
    for b in out:
        out[b].sort(key=lambda e: e["signal_ms"])
    return out


def horizon_at(age_ms: float) -> int | None:
    """The largest H not after the coin's age at the signal; None under the first."""
    hs = [h for h in HORIZONS if h * 1000 <= age_ms]
    return max(hs) if hs else None


def twin_queries(data: dict, entries: dict[str, list[dict]]) -> dict[str, list[int]]:
    """{signal day: coin indices} for the entries' coins."""
    at = {m: i for i, m in enumerate(data["mint"].tolist())}
    q: dict[str, set] = {}
    for es in entries.values():
        for e in es:
            i = at.get(e["mint"])
            if i is not None:
                q.setdefault(day_of(e["signal_ms"]), set()).add(i)
    return {d: sorted(v) for d, v in q.items()}


def vetoed(e: dict, data: dict, at: dict, wf: dict, v: str) -> bool | None:
    """True when veto v skips the entry, False when it keeps it, None when no shape is known (kept)."""
    i = at.get(e["mint"])
    if i is None:
        return None
    t0 = float(data["t0"][i])
    h = horizon_at(e["signal_ms"] - t0)
    d = day_of(e["signal_ms"])
    p, cut = wf["qpred"].get((d, i, h)), wf["cuts"].get((d, h))
    if h is None or p is None or cut is None:
        return None
    label, q, side = VETOES[v]
    x = p[1] if label == "rug" else p[2]
    thr = cut[label][q]
    return bool(x > thr) if side == "above" else bool(x < thr)


def reserves(entries: dict[str, list[dict]], root=None) -> None:
    """Each closed trade's pool SOL (the effective quote reserves of the pool's last trade received by then, before
    its first trade the first one's) at its signal and at its exit, as q_in and q_out, from the record: R2's impact
    scaling and its 2 % cap (smallwallet)."""
    import polars as pl
    from . import store
    es = [e for v in entries.values() for e in v if not e["failed"]]
    if not es:
        return
    days = sorted({day_of(e["signal_ms"]) for e in es}
                  | {day_of(e["exit_ms"]) for e in es if e["exit_ms"] == e["exit_ms"]})
    amm = store.read("amm", [d for d in days if d in set(store.days(root))], root)
    if amm.height == 0:
        return
    if "vq" not in amm.columns:
        amm = amm.with_columns(pl.lit(None, dtype=pl.Int64).alias("vq"))
    amm = (amm.filter(pl.col("mint").is_in(list({e["mint"] for e in es})))
           .select("mint", "t", ((pl.col("pq") + pl.col("vq").fill_null(0)).clip(lower_bound=0) / C.LAMPORTS)
                   .alias("q")).sort("t"))
    q = pl.DataFrame({"k": list(range(2 * len(es))), "mint": [e["mint"] for e in es] * 2,
                      "t": [int(e["signal_ms"]) for e in es] + [int(e["exit_ms"]) if e["exit_ms"] == e["exit_ms"]
                                                                else int(e["signal_ms"]) for e in es]}).sort("t")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        got = dict(q.join_asof(amm, on="t", by="mint", strategy="backward").select("k", "q").iter_rows())
        nxt = dict(q.join_asof(amm, on="t", by="mint", strategy="forward").select("k", "q").iter_rows())
    for k, v in nxt.items():                          # a pool with no trade yet at the signal: its first one
        if not got.get(k):
            got[k] = v
    for i, e in enumerate(es):
        e["q_in"], e["q_out"] = float(got.get(i) or 0.0), float(got.get(len(es) + i) or 0.0)


def wallet_entries(es: list[dict]) -> list[dict]:
    """smallwallet's entry dicts at STAKE_SOL: a closed trade costs STAKE_SOL and pays it back with its return, at
    another stake rescaled on the pool's SOL at the buy and the sale (reserves; none known: in proportion), a failed
    buy pays its fee."""
    out = []
    for e in es:
        if e["failed"]:
            out.append({"signal_ms": e["signal_ms"], "exit_ms": e["exit_ms"], "failed": True, "cost": 0.0,
                        "proceeds": 0.0, "fees": -e["pnl"], "pnl": e["pnl"], "q_in": 0.0, "q_out": 0.0})
        else:
            out.append({"signal_ms": e["signal_ms"], "exit_ms": e["exit_ms"], "failed": False, "cost": STAKE_SOL,
                        "proceeds": STAKE_SOL * (1 + e["ret"]), "fees": 0.0, "pnl": e["pnl"],
                        "q_in": e.get("q_in", 0.0), "q_out": e.get("q_out", 0.0)})
    return out


def wallet(es: list[dict], days=TWIN_DAYS, seed: int = SEED) -> dict:
    from . import smallwallet as SW
    w = WALLET
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, len(days), size=(w["paths"], w["horizon"]))
    dl = [SW.day_arrays(wallet_entries(es), d) for d in days]
    sim = SW.simulate(dl, draws, w["max_open"], [w["share"]], [w["brake"]], [w["start"]])
    o = SW.outcome(sim, 0, w["start"], 100.0 / SW.EUR_PER_SOL)
    return {k: o[k] for k in ("median", "mean", "p10", "p90", "p_double", "p_lost80", "p_ruin")}


def skipped_band(cut: list[dict], seed: int = SEED) -> dict:
    """The skipped entries' P&L at STAKE_SOL: the sum, the mean and a 90 % band of the sum (hour blocks)."""
    if not cut:
        return {"n": 0, "sum": 0.0, "mean": None, "band": [NAN, NAN]}
    pnl = np.array([e["pnl"] for e in cut], dtype=float)
    inv, cnt = hour_draws(np.array([e["signal_ms"] for e in cut], dtype=float), seed=seed)
    s = cnt[:, inv] @ pnl
    return {"n": len(cut), "sum": float(s[0]), "mean": float(pnl.mean()),
            "band": [float(np.quantile(s[1:], (1 - BAND) / 2)), float(np.quantile(s[1:], (1 + BAND) / 2))]}


def twins(data: dict, wf: dict, entries: dict[str, list[dict]], days=TWIN_DAYS) -> dict:
    """Every base and its twins by R2's bar."""
    from . import smallwallet as SW
    at = {m: i for i, m in enumerate(data["mint"].tolist())}
    out = {}
    for b, es in entries.items():
        if not es:
            out[b] = {"n": 0}
            continue
        base = {"n": len(es), "failed": sum(e["failed"] for e in es),
                "expectation": SW.expectation(wallet_entries(es), list(days)),
                "wallet": wallet(es, days)}
        hs = [horizon_at(e["signal_ms"] - float(data["t0"][at[e["mint"]]])) if e["mint"] in at else None for e in es]
        base["with_shape"] = {str(h): sum(1 for x in hs if x == h) for h in HORIZONS}
        base["no_shape"] = sum(1 for x in hs if x is None)
        base["no_reserves"] = sum(1 for e in es if not e["failed"] and not e.get("q_in"))
        r = {"base": base, "twins": {}}
        for v in VETOES:
            flags = [vetoed(e, data, at, wf, v) for e in es]
            kept = [e for e, f in zip(es, flags) if not f]
            cut = [e for e, f in zip(es, flags) if f]
            ex = SW.expectation(wallet_entries(kept), list(days)) if kept else {"n": 0}
            wl = wallet(kept, days) if kept else None
            sk = skipped_band(cut)
            win_lost = sum(1 for e in cut if not e["failed"] and e["ret"] > 0)
            bar = {"band_above_zero": bool(ex.get("lo", -1) > 0),
                   "wallet_mean_above_start": bool(wl and wl["mean"] > WALLET["start"]),
                   "skipped_band_below_zero": bool(sk["n"] and sk["band"][1] < 0),
                   "median_above_base": bool(wl and wl["median"] > base["wallet"]["median"])}
            r["twins"][v] = {"n": len(kept), "skipped": len(cut), "no_shape": sum(1 for f in flags if f is None),
                             "winners_skipped": win_lost, "expectation": ex, "wallet": wl, "skipped_pnl": sk,
                             "bar": bar, "passes": all(bar.values())}
        out[b] = r
    return out


# ---------------------------------------------------------------- the run

def load(f: Path) -> dict:
    z = np.load(f, allow_pickle=False)
    return {k: z[k] for k in z.files}


def early_matrix(data: dict, root=None) -> np.ndarray:
    """(N, len(HORIZONS), features): each coin's early row at H (EARLY_KIND), NaN without one."""
    from . import exitpol as XP
    key, X = early_table(root)
    feats = XP.trend_features()
    n = len(data["mint"])
    out = np.full((n, len(HORIZONS), len(feats)), NAN, dtype=np.float32)
    cols = [X.get(f) for f in feats]
    for i, m in enumerate(data["mint"].tolist()):
        for j, h in enumerate(HORIZONS):
            r = key.get((m, EARLY_KIND[h]))
            if r is not None:
                out[i, j] = [c[r] if c is not None else NAN for c in cols]
    return out


def save_walk(out: Path, wf: dict) -> None:
    np.savez_compressed(out / "shapes17_walk.npz", **{f"pred_{m}": v for m, v in wf["pred"].items()})
    (out / "shapes17_walk.json").write_text(json.dumps(
        {"qpred": [[d, i, h, [float(x) for x in v]] for (d, i, h), v in wf["qpred"].items()],
         "cuts": [[d, h, c] for (d, h), c in wf["cuts"].items()]}), encoding="utf-8")


def load_walk(out: Path) -> dict | None:
    """A walk saved by save_walk (the run's predictions), None without one."""
    f, g = out / "shapes17_walk.npz", out / "shapes17_walk.json"
    if not (f.exists() and g.exists()):
        return None
    z = np.load(f)
    j = json.loads(g.read_text(encoding="utf-8"))
    return {"pred": {k[5:]: z[k] for k in z.files},
            "qpred": {(d, int(i), int(h)): np.array(v) for d, i, h, v in j["qpred"]},
            "cuts": {(d, int(h)): {lab: {float(q): x for q, x in c[lab].items()} for lab in c}
                     for d, h, c in j["cuts"]}}


def run(out: Path, root=None, log=print) -> dict:
    f = out / "shapes17.npz"
    if not f.exists():
        build(out, root, log)
    data = load(f)
    bad: dict[str, int] = {}
    entries = ledger_entries(taint=bad)
    log(f"shapes17: {sum(bad.values())} ledger trades of the late-row bug skipped (P1)")
    t1 = time.time()
    Xe = early_matrix(data, root)
    log(f"shapes17: {len(data['mint']):,} coins, early rows in {time.time() - t1:.0f} s")
    wf = load_walk(out)
    if wf is None:
        wf = walk(data, Xe, log=log, queries=twin_queries(data, entries))
        save_walk(out, wf)
    ev = evaluate(data, wf)
    ev["references"] = references(data, wf)
    reserves(entries, root)
    tw = twins(data, wf, entries)
    t0 = data["t0"].astype(float)
    return {"coins": int(len(t0)), "with_row": int(data["has_row"].sum()),
            "span": [day_of(t0.min()), day_of(t0.max())], "eval": ev, "twins": tw,
            "base_rates": {f"{lab}@{h}": float(np.nanmean(data[lab][data["has_row"], j]))
                           for j, h in enumerate(HORIZONS) for lab in LABELS}}


# ---------------------------------------------------------------- report

def _f(x, fmt="{:.3f}") -> str:
    return "n/a" if x is None or (isinstance(x, float) and not math.isfinite(x)) else fmt.format(x)


def _band(b) -> str:
    return "n/a" if not b or not all(math.isfinite(v) for v in b) else f"{b[0]:+.3f} to {b[1]:+.3f}"


MEASURE = {"mig": "AUC", "rug": "AUC", "peak": "Spearman", "exit_s": "minus MAE (s)"}


def report_md(res: dict) -> str:
    ev = res["eval"]
    md = ["# pump.fun, the shape of a coin's first minutes (Y17)", "",
          f"Coins {res['coins']:,} ({res['with_row']:,} with an early row), created {res['span'][0]} to "
          f"{res['span'][1]}; test days {TEST_DAYS[0]} to {TEST_DAYS[-1]}, {ev['comparisons']} comparisons, Holm.", "",
          "| H | label | measure | test coins | rate | CNN | analog | baseline (Y10 early) | CNN - base | band | "
          "beats | analog - base | band | beats |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in ev["rows"]:
        if "base" not in r:
            md.append(f"| {r['h']} | {r['label']} | {MEASURE[r['label']]} | {r['n']} |" + " |" * 10)
            continue
        md.append(f"| {r['h']} | {r['label']} | {MEASURE[r['label']]} | {r['n']:,} | "
                  f"{_f(r.get('rate'), '{:.3f}') if r['label'] in ('mig', 'rug') else ''} | {_f(r['cnn'])} | "
                  f"{_f(r['analog'])} | {_f(r['base'])} | {_f(r.get('cnn_diff'), '{:+.3f}')} | "
                  f"{_band(r.get('cnn_band'))} | {'yes' if r.get('cnn_beats') else 'no'} | "
                  f"{_f(r.get('analog_diff'), '{:+.3f}')} | {_band(r.get('analog_band'))} | "
                  f"{'yes' if r.get('analog_beats') else 'no'} |")
    md += ["", "## Not registered: one number at H against the models", "",
           "The log price at H (rug, peak) or the curve's progress (mig) alone, on the same test coins, and on the "
           "coins "
           f"up {MOVED * 100:.0f} % or more at H. AUC (mig, rug) or Spearman (peak).", "",
           "| H | label | coins | n | rate | one number | CNN | analog | baseline |",
           "|---|---|---|---|---|---|---|---|---|"]
    for r in ev.get("references", []):
        md.append(f"| {r['h']} | {r['label']} | {r['coins']} | {r['n']:,} | {_f(r.get('rate'))} | "
                  f"{_f(r['one_number'])} | {_f(r.get('cnn'))} | {_f(r.get('analog'))} | {_f(r.get('base'))} |")
    md += ["", "## Selling at the predicted second (mean log price over the price at H)", "",
           "| H | best second (ceiling) | CNN | analog | baseline | median second of the days before | hold 600 s |",
           "|---|---|---|---|---|---|---|"]
    for r in ev["rows"]:
        x = r.get("exit")
        if x:
            md.append(f"| {r['h']} | {_f(x['at_best'], '{:+.3f}')} | {_f(x['at_cnn'], '{:+.3f}')} | "
                      f"{_f(x['at_analog'], '{:+.3f}')} | {_f(x['at_base'], '{:+.3f}')} | "
                      f"{_f(x['at_median'], '{:+.3f}')} ({x['median_s']:.0f} s) | {_f(x['hold_600'], '{:+.3f}')} |")
    md += ["", "## Realistic paper twins (R1's execution, from the ledger), R2's bar", "",
           "| book | entries | skipped | no shape | winners skipped | mean P&L per entry at 0.1 SOL | band | "
           "skipped P&L SOL | its band | 30-day median wallet | mean | ruin | passes |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for b, r in res["twins"].items():
        if not r.get("base"):
            md.append(f"| {b} | 0 |" + " |" * 11)
            continue
        e, w = r["base"]["expectation"], r["base"]["wallet"]
        md.append(f"| {b} | {r['base']['n']} | | | | {_f(e.get('mean_sol'), '{:+.4f}')} | "
                  f"{_band([e.get('lo', NAN), e.get('hi', NAN)])} | | | {w['median']:.2f} | {w['mean']:.2f} | "
                  f"{w['p_ruin'] * 100:.0f} % | base |")
        for v, x in r["twins"].items():
            e, w = x["expectation"], x["wallet"] or {}
            md.append(f"| {b} {v} | {x['n']} | {x['skipped']} | {x['no_shape']} | {x['winners_skipped']} | "
                      f"{_f(e.get('mean_sol'), '{:+.4f}')} | {_band([e.get('lo', NAN), e.get('hi', NAN)])} | "
                      f"{x['skipped_pnl']['sum']:+.3f} | {_band(x['skipped_pnl']['band'])} | "
                      f"{_f(w.get('median'), '{:.2f}')} | {_f(w.get('mean'), '{:.2f}')} | "
                      f"{_f(w.get('p_ruin', NAN) * 100, '{:.0f}')} % | {'yes' if x['passes'] else 'no'} |")
    md += ["", "A shape at the signal (the largest H not after the coin's age, from the creation's receipt): "
           + "; ".join(f"{b} " + ", ".join(f"{h} s {n}" for h, n in r["base"]["with_shape"].items())
                       + f", none {r['base']['no_shape']} (no pool reserves {r['base']['no_reserves']})"
                       for b, r in res["twins"].items() if r.get("base"))]
    return "\n".join(md) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("what", choices=("build", "run"))
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    if a.what == "build":
        build(out)
        return 0
    res = run(out)
    md = report_md(res)
    (out / "shapes17.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    (out / "shapes17.md").write_text(md, encoding="utf-8")
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
