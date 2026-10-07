"""M3 · Pythia-Net: our own sequence model for crypto, trained on the RTX 4080.

What it is
  A small PatchTST-style transformer. Input: the last 14 days (336 hours) of one
  coin, as hourly log return, log range, volume z-score and taker-buy share,
  with BTC's hourly return as a second channel for market context. The series
  is cut into 12-hour patches (28 tokens) and encoded.

How it learns
  1. Self-supervised pretraining: 40 % of the patches are hidden and the model
     reconstructs them. It learns how crypto series move, from every coin Binance
     ever listed, without any label. Pretraining only sees data before the first
     test quarter, so nothing from the future leaks in.
  2. Fine-tuning per quarter, walk-forward like every lab model: two heads,
       rank   the coin's next-7-day return, as a cross-sectional rank on its day
              (so the model learns which coins beat the others, not the market)
       vol    log realised variance of the next 7 days
     trained only on days a week before the quarter starts (embargo = horizon).

How it is judged
  Exactly like M2 (lab/experiments/picks.py): daily Rank-IC per quarter, and a
  weekly top-K long-only book with 25 bps per unit of turnover, against M2's
  report, plain 28-day momentum and the equal-weight universe. It has to beat
  the tree model on the same days to be worth its GPU.

Run on the PC (data from the VPS sync):
  F:/PythiaData/venv-net/Scripts/python.exe research/net/pythia_net.py --data F:/PythiaData
"""

from __future__ import annotations

import argparse
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import polars as pl
import torch
import torch.nn as nn
import torch.nn.functional as F

HOUR_US = 3_600_000_000
DAY_US = 24 * HOUR_US
WINDOW_H = 336
PATCH = 12
N_PATCH = WINDOW_H // PATCH
CHANNELS = 5  # ret, range, vol_z, taker, btc_ret
HORIZON_D = 7
MIN_HISTORY_D = 60
MIN_ADV_USD = 1_000_000
FIRST_TEST = datetime(2022, 1, 1, tzinfo=timezone.utc)
COST = 0.0025
TOP_K = [5, 10, 20]


# ── data ──────────────────────────────────────────────────────────────────────

GAP_SPLIT_US = 3 * DAY_US
JUMP_SPLIT = math.log(10)


def load_segments(root: Path, symbol: str) -> list[tuple[str, pl.DataFrame]]:
    """A symbol's hourly bars split where they stop being one asset (same rule as
    lab/experiments/picks.py): a gap over three days or a tenfold move inside an
    hour (a reused symbol like LUNA, a redenomination like QUICK) starts a new
    segment, named `SYMBOL~n` for all but the latest."""
    d = root / "hist" / "binance_spot" / "klines_1h" / f"symbol={symbol}"
    files = sorted(d.glob("*.parquet"))
    if not files:
        return []
    h = pl.concat([pl.read_parquet(f) for f in files], how="vertical_relaxed").unique("open_time_us").sort("open_time_us")
    h = h.with_columns(
        brk=((pl.col("open_time_us").diff() > GAP_SPLIT_US)
             | ((pl.col("close").log() - pl.col("close").shift(1).log()).abs() > JUMP_SPLIT)).fill_null(False)
    ).with_columns(seg=pl.col("brk").cum_sum())
    segs = [g.drop("brk", "seg") for _, g in h.group_by("seg", maintain_order=True)]
    out = []
    for j, g in enumerate(segs):
        prepared = prepare(g)
        if prepared is not None:
            out.append((symbol if j == len(segs) - 1 else f"{symbol}~{j}", prepared))
    return out


def load_hourly(root: Path, symbol: str) -> pl.DataFrame | None:
    segs = load_segments(root, symbol)
    return segs[-1][1] if segs else None


def prepare(h: pl.DataFrame) -> pl.DataFrame | None:
    if h.height < (MIN_HISTORY_D + 20) * 24:
        return None
    # Regular hourly grid: gaps (exchange down, not yet listed) become zero
    # returns with zero volume, which the model can see as "nothing happened".
    t0, t1 = int(h["open_time_us"][0]), int(h["open_time_us"][-1])
    grid = pl.DataFrame({"open_time_us": np.arange(t0, t1 + 1, HOUR_US, dtype=np.int64)})
    h = grid.join(h, on="open_time_us", how="left").with_columns(
        pl.col("close").fill_null(strategy="forward"),
        pl.col("high").fill_null(pl.col("close")),
        pl.col("low").fill_null(pl.col("close")),
        pl.col("quote_volume").fill_null(0.0),
        pl.col("taker_buy_quote_volume").fill_null(0.0),
    ).fill_null(strategy="forward")
    lv = (pl.col("quote_volume") + 1.0).log()
    return h.select(
        "open_time_us",
        "close",
        "quote_volume",
        ret=(pl.col("close").log() - pl.col("close").shift(1).log()).fill_null(0.0).clip(-0.5, 0.5),
        rng=((pl.col("high") / pl.col("low")).log()).clip(0, 0.5),
        vol_z=(lv - lv.rolling_mean(168, min_samples=24)) / (lv.rolling_std(168, min_samples=24) + 1e-6),
        taker=(pl.col("taker_buy_quote_volume") / (pl.col("quote_volume") + 1e-9) - 0.5),
    ).fill_null(0.0).fill_nan(0.0)


class Panel:
    """Per-coin hourly arrays plus daily anchors (coin, hour index, day) with labels."""

    def __init__(self, root: Path, max_coins: int | None = None):
        syms = json.loads((root / "hist" / "universe.json").read_text())
        if max_coins:
            syms = syms[:max_coins]
        btc = load_hourly(root, "BTCUSDT")
        self.btc_ret = dict(zip(btc["open_time_us"].to_list(), btc["ret"].to_list()))
        self.series: list[np.ndarray] = []
        self.times: list[np.ndarray] = []
        self.symbols: list[str] = []
        rows = []
        for s0 in syms:
            for s, h in load_segments(root, s0):
                ts = h["open_time_us"].to_numpy()
                btc_r = np.array([self.btc_ret.get(int(t), 0.0) for t in ts], dtype=np.float32)
                x = np.stack([h["ret"].to_numpy(), h["rng"].to_numpy(), h["vol_z"].to_numpy(),
                              h["taker"].to_numpy(), btc_r], axis=1).astype(np.float32)
                x[:, 0] *= 100.0  # returns in percent: comparable scales across channels
                x[:, 1] *= 100.0
                x[:, 4] *= 100.0
                ci = len(self.series)
                self.series.append(x)
                self.times.append(ts)
                self.symbols.append(s)
                close = h["close"].to_numpy()
                qv = h["quote_volume"].to_numpy()
                r = h["ret"].to_numpy()
                ended = ts[-1] < (time.time() * 1e6 - 3 * DAY_US)
                # Daily anchors at 00:00 UTC: everything before the anchor is known.
                first = int(np.ceil(ts[0] / DAY_US)) * DAY_US
                for a in range(first + MIN_HISTORY_D * DAY_US, int(ts[-1]) + 1, DAY_US):
                    i = int((a - ts[0]) // HOUR_US)  # index of the first hour after the window
                    if i < WINDOW_H or i >= len(ts):
                        continue
                    adv = qv[max(0, i - 28 * 24):i].sum() / 28.0
                    if adv < MIN_ADV_USD:
                        continue
                    j = i + HORIZON_D * 24
                    if j < len(ts):
                        fwd = math.log(close[j - 1] / close[i - 1])
                        fvol = math.log(float((r[i:j] ** 2).sum()) + 1e-10)
                    elif ended:  # delisted or replaced inside the week: return to the last close
                        fwd = math.log(close[-1] / close[i - 1])
                        fvol = math.log(float((r[i:] ** 2).sum()) + 1e-10)
                    else:
                        fwd, fvol = float("nan"), float("nan")
                    rows.append((ci, i, a, fwd, fvol))
        a = np.array(rows, dtype=np.float64)
        self.coin = a[:, 0].astype(np.int64)
        self.idx = a[:, 1].astype(np.int64)
        self.day = a[:, 2].astype(np.int64)
        self.fwd = a[:, 3]
        self.fvol = a[:, 4]
        # Cross-sectional rank of the forward return per day, mapped to a normal score.
        self.rank_target = np.full(len(a), np.nan, dtype=np.float32)
        df = pl.DataFrame({"day": self.day, "fwd": self.fwd, "row": np.arange(len(a))})
        df = df.filter(pl.col("fwd").is_not_nan())
        df = df.with_columns(n=pl.len().over("day"), r=pl.col("fwd").rank().over("day"))
        from scipy.stats import norm
        q = ((df["r"].to_numpy() - 0.5) / df["n"].to_numpy()).clip(1e-4, 1 - 1e-4)
        self.rank_target[df["row"].to_numpy()] = norm.ppf(q).astype(np.float32)
        self.static: np.ndarray | None = None
        print(f"panel: {len(self.symbols)} coins, {len(a):,} coin-days", flush=True)

    def attach_m2_features(self, root: Path) -> int:
        """M2's 16 cross-sectional feature ranks, from M2's own code, for the hybrid.

        An anchor at 00:00 of day A sees M2's features of day A - 1 (computed at
        that day's close), so nothing from day A leaks in.
        """
        import os
        import sys
        os.environ["PYTHIA_DATA"] = str(root)
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lab"))
        from lab.experiments.picks import FEATURES, build  # noqa: E402
        P = build()
        names = np.array(self.symbols)[self.coin]
        keys = pl.DataFrame({"row": np.arange(len(self.day)), "day": self.day - DAY_US, "symbol": names})
        joined = keys.join(P.select(["day", "symbol", *FEATURES]), on=["day", "symbol"], how="left").sort("row")
        self.static = joined.select(FEATURES).to_numpy().astype(np.float32)
        return len(FEATURES)

    def window(self, rows: np.ndarray) -> torch.Tensor:
        out = np.empty((len(rows), WINDOW_H, CHANNELS), dtype=np.float32)
        for k, r in enumerate(rows):
            i = self.idx[r]
            out[k] = self.series[self.coin[r]][i - WINDOW_H:i]
        return torch.from_numpy(out)


# ── model ─────────────────────────────────────────────────────────────────────

class PythiaNet(nn.Module):
    """`n_static > 0` makes it the hybrid (attempt two): the encoded price shape is
    joined by M2's cross-sectional features (liquidity, age, momentum ranks...),
    which a single coin's normalised window cannot show."""

    def __init__(self, d: int = 128, layers: int = 4, heads: int = 4, dropout: float = 0.1, n_static: int = 0):
        super().__init__()
        self.n_static = n_static
        head_in = d * 2 if n_static else d
        self.static = nn.Sequential(nn.Linear(n_static, d), nn.GELU(), nn.Linear(d, d)) if n_static else None
        self.embed = nn.Linear(PATCH * CHANNELS, d)
        self.pos = nn.Parameter(torch.zeros(1, N_PATCH + 1, d))
        self.cls = nn.Parameter(torch.zeros(1, 1, d))
        self.mask_token = nn.Parameter(torch.zeros(1, 1, d))
        enc = nn.TransformerEncoderLayer(d, heads, 4 * d, dropout, batch_first=True, norm_first=True)
        self.encoder = nn.TransformerEncoder(enc, layers)
        self.norm = nn.LayerNorm(d)
        self.recon = nn.Linear(d, PATCH * CHANNELS)
        self.rank_head = nn.Sequential(nn.Linear(head_in, d), nn.GELU(), nn.Linear(d, 1))
        self.vol_head = nn.Sequential(nn.Linear(head_in, d), nn.GELU(), nn.Linear(d, 1))
        nn.init.normal_(self.pos, std=0.02)
        nn.init.normal_(self.cls, std=0.02)

    def patches(self, x: torch.Tensor) -> torch.Tensor:
        b = x.shape[0]
        return x.reshape(b, N_PATCH, PATCH * CHANNELS)

    def encode(self, p: torch.Tensor, mask: torch.Tensor | None = None) -> torch.Tensor:
        z = self.embed(p)
        if mask is not None:
            z = torch.where(mask.unsqueeze(-1), self.mask_token.expand_as(z), z)
        z = torch.cat([self.cls.expand(z.shape[0], -1, -1), z], dim=1) + self.pos
        return self.norm(self.encoder(z))

    def forward(self, x: torch.Tensor, s: torch.Tensor | None = None):
        h = self.encode(self.patches(x))[:, 0]
        if self.static is not None:
            h = torch.cat([h, self.static(s)], dim=-1)
        return self.rank_head(h).squeeze(-1), self.vol_head(h).squeeze(-1)


def standardise(x: torch.Tensor) -> torch.Tensor:
    # Per-window, per-channel scaling (RevIN-style): the model sees shape, not level.
    mu = x.mean(dim=1, keepdim=True)
    sd = x.std(dim=1, keepdim=True) + 1e-3
    return (x - mu) / sd


# ── training ──────────────────────────────────────────────────────────────────

def pretrain(model: PythiaNet, panel: Panel, rows: np.ndarray, dev, epochs: int, batch: int, log) -> None:
    opt = torch.optim.AdamW(model.parameters(), lr=3e-4, weight_decay=0.05)
    model.train()
    for ep in range(epochs):
        perm = np.random.permutation(rows)
        tot, n = 0.0, 0
        for s in range(0, len(perm), batch):
            x = standardise(panel.window(perm[s:s + batch]).to(dev, non_blocking=True))
            p = model.patches(x)
            mask = torch.rand(p.shape[0], N_PATCH, device=dev) < 0.4
            with torch.autocast("cuda", dtype=torch.bfloat16):
                z = model.encode(p, mask)[:, 1:]
                rec = model.recon(z)
                loss = F.mse_loss(rec[mask].float(), p[mask].float())
            opt.zero_grad(set_to_none=True)
            loss.backward()  # bf16 autocast needs no loss scaling
            nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            tot += float(loss) * len(x)
            n += len(x)
        log(f"pretrain epoch {ep + 1}/{epochs}: reconstruction loss {tot / n:.4f}")


def finetune(model: PythiaNet, panel: Panel, rows: np.ndarray, dev, epochs: int, batch: int,
             listwise: bool = False) -> None:
    rows = rows[np.isfinite(panel.rank_target[rows]) & np.isfinite(panel.fvol[rows])]
    vol_mu, vol_sd = float(np.mean(panel.fvol[rows])), float(np.std(panel.fvol[rows]) + 1e-6)
    model.vol_norm = (vol_mu, vol_sd)
    if panel.static is not None:
        rows = rows[np.isfinite(panel.static[rows]).all(axis=1)]
    fresh = ("head", "static")  # new layers learn fast, the pretrained encoder slowly
    opt = torch.optim.AdamW([{"params": [p for n_, p in model.named_parameters() if n_.startswith(fresh)], "lr": 1e-3},
                             {"params": [p for n_, p in model.named_parameters() if not n_.startswith(fresh)], "lr": 1e-4}],
                            weight_decay=0.05)
    model.train()
    for _ in range(epochs):
        for b, day_ids in batches(panel, rows, batch, listwise):
            x = standardise(panel.window(b).to(dev, non_blocking=True))
            yr = torch.from_numpy(panel.rank_target[b]).to(dev)
            yv = torch.from_numpy(((panel.fvol[b] - vol_mu) / vol_sd).astype(np.float32)).to(dev)
            s_b = torch.from_numpy(panel.static[b]).to(dev) if panel.static is not None else None
            with torch.autocast("cuda", dtype=torch.bfloat16):
                pr, pv = model(x, s_b)
            pr, pv = pr.float(), pv.float()
            vol_loss = 0.5 * F.mse_loss(pv, yv)
            if listwise:
                loss = listnet_loss(pr, yr, torch.from_numpy(day_ids).to(dev)) + vol_loss
            else:
                loss = F.mse_loss(pr, yr) + vol_loss
            opt.zero_grad(set_to_none=True)
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()


def batches(panel: Panel, rows: np.ndarray, batch: int, listwise: bool):
    """Pointwise: random rows. Listwise: whole days, so every day in a batch is
    complete and the loss can compare each coin with the others of its day."""
    if not listwise:
        perm = np.random.permutation(rows)
        for s in range(0, len(perm), batch):
            yield perm[s:s + batch], None
        return
    days = panel.day[rows]
    uniq = np.random.permutation(np.unique(days))
    by_day = {d: rows[days == d] for d in uniq}
    cur, ids = [], []
    for k, d in enumerate(uniq):
        r = by_day[d]
        cur.append(r)
        ids.append(np.full(len(r), k, dtype=np.int64))
        if sum(len(c) for c in cur) >= batch:
            yield np.concatenate(cur), np.concatenate(ids)
            cur, ids = [], []
    if cur:
        yield np.concatenate(cur), np.concatenate(ids)


def listnet_loss(pred: torch.Tensor, target: torch.Tensor, day: torch.Tensor, temp: float = 1.0) -> torch.Tensor:
    """ListNet top-one cross-entropy per day: the softmax of the predictions
    should match the softmax of the true cross-sectional ranks. It optimises the
    ordering within each day, which is the task, instead of each coin's level."""
    loss, n = pred.new_zeros(()), 0
    for d in torch.unique(day):
        m = day == d
        if m.sum() < 5:
            continue
        p = F.log_softmax(pred[m] / temp, dim=0)
        t = F.softmax(target[m] / temp, dim=0)
        loss = loss - (t * p).sum()
        n += 1
    return loss / max(n, 1)


@torch.no_grad()
def predict(model: PythiaNet, panel: Panel, rows: np.ndarray, dev, batch: int) -> np.ndarray:
    model.eval()
    out = []
    for s in range(0, len(rows), batch):
        x = standardise(panel.window(rows[s:s + batch]).to(dev))
        s_b = None
        if panel.static is not None:
            s_b = torch.from_numpy(np.nan_to_num(panel.static[rows[s:s + batch]], nan=0.5)).to(dev)
        with torch.autocast("cuda", dtype=torch.bfloat16):
            pr, _ = model(x, s_b)
        out.append(pr.float().cpu().numpy())
    return np.concatenate(out) if out else np.array([])


# ── evaluation (same as M2) ──────────────────────────────────────────────────

def quarter_starts(first: datetime, last_us: int) -> list[int]:
    out, y, q = [], first.year, (first.month - 1) // 3
    while True:
        us = int(datetime(y, q * 3 + 1, 1, tzinfo=timezone.utc).timestamp() * 1e6)
        if us > last_us:
            return out
        out.append(us)
        q += 1
        if q == 4:
            y, q = y + 1, 0


def topk(days, coins, score, fwd, k):
    rets, prev = [], set()
    for d in np.unique(days)[::HORIZON_D]:
        m = np.flatnonzero(days == d)
        if len(m) < k:
            continue
        sel = m[np.argsort(-score[m])][:k]
        chosen = set(coins[sel].tolist())
        turnover = len(chosen ^ prev) / k if prev else 1.0
        rets.append(float(np.mean(np.expm1(fwd[sel]))) - turnover * COST)
        prev = chosen
    return np.array(rets)


def perf(r):
    py = 365 / HORIZON_D
    eq = np.cumprod(1 + r)
    return {"periods": len(r), "cagr": float(eq[-1] ** (py / len(r)) - 1),
            "sharpe": float(r.mean() / r.std() * np.sqrt(py)) if r.std() > 0 else 0.0,
            "max_dd": float((1 - eq / np.maximum.accumulate(eq)).max())}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="F:/PythiaData")
    ap.add_argument("--pretrain-epochs", type=int, default=3)
    ap.add_argument("--finetune-epochs", type=int, default=2)
    ap.add_argument("--batch", type=int, default=512)
    ap.add_argument("--max-coins", type=int, default=None, help="for a quick smoke test")
    ap.add_argument("--hybrid", action="store_true", help="attempt two: add M2's cross-sectional features")
    ap.add_argument("--listwise", action="store_true", help="attempt three: rank whole days (ListNet), bigger model")
    args = ap.parse_args()
    root = Path(args.data)
    dev = torch.device("cuda")
    torch.manual_seed(7)
    np.random.seed(7)
    t0 = time.time()
    variant = "pythia_net" + ("_hybrid" if args.hybrid else "") + ("_listwise" if args.listwise else "")
    out_dir = root / "reports" / variant
    out_dir.mkdir(parents=True, exist_ok=True)
    log_lines: list[str] = []

    def log(msg: str) -> None:
        line = f"{time.time() - t0:7.0f}s  {msg}"
        print(line, flush=True)
        log_lines.append(line)

    panel = Panel(root, args.max_coins)
    first_test = int(FIRST_TEST.timestamp() * 1e6)
    starts = quarter_starts(FIRST_TEST, int(panel.day.max()))
    n_static = panel.attach_m2_features(root) if args.hybrid else 0
    if n_static:
        covered = float(np.isfinite(panel.static).all(axis=1).mean())
        log(f"hybrid: {n_static} M2 features attached, {covered * 100:.0f} % of coin-days covered")
    size = dict(d=192, layers=6, heads=6) if args.listwise else {}
    model = PythiaNet(n_static=n_static, **size).to(dev)
    log(f"model: {sum(p.numel() for p in model.parameters()) / 1e6:.2f} M parameters on {torch.cuda.get_device_name(0)}")

    pre_rows = np.flatnonzero(panel.day < first_test - HORIZON_D * DAY_US)
    pretrain(model, panel, pre_rows, dev, args.pretrain_epochs, args.batch, log)
    base_state = {k: v.detach().clone() for k, v in model.state_dict().items()}

    score = np.full(len(panel.day), np.nan)
    folds = []
    for qi, s in enumerate(starts):
        e = starts[qi + 1] if qi + 1 < len(starts) else int(panel.day.max()) + 1
        tr = np.flatnonzero(panel.day < s - HORIZON_D * DAY_US)
        te = np.flatnonzero((panel.day >= s) & (panel.day < e))
        if len(te) == 0:
            continue
        model.load_state_dict(base_state)  # every quarter starts from the same pretrained encoder
        finetune(model, panel, tr, dev, args.finetune_epochs, args.batch, listwise=args.listwise)
        score[te] = predict(model, panel, te, dev, args.batch * 2)
        ok = te[np.isfinite(panel.fwd[te])]
        ics = []
        for d in np.unique(panel.day[ok]):
            m = ok[panel.day[ok] == d]
            if len(m) >= 10:
                ics.append(float(pl.DataFrame({"a": score[m], "b": panel.fwd[m]}).select(pl.corr("a", "b", method="spearman")).item() or 0.0))
        name = f"{datetime.fromtimestamp(s / 1e6, timezone.utc).year}Q{(datetime.fromtimestamp(s / 1e6, timezone.utc).month - 1) // 3 + 1}"
        folds.append({"fold": name, "days": len(ics), "rank_ic": float(np.mean(ics)) if ics else float("nan")})
        log(f"{name}: rank-IC {folds[-1]['rank_ic']:.4f} over {len(ics)} days")

    oos = np.isfinite(score) & np.isfinite(panel.fwd)
    coins = np.array(panel.symbols)[panel.coin]
    # Out-of-sample scores, for combining with M2 (research/net/ensemble.py).
    has = np.isfinite(score)
    pl.DataFrame({"day": panel.day[has], "symbol": coins[has], "score": score[has], "fwd": panel.fwd[has]}).write_parquet(
        out_dir / "scores.parquet")
    rows = []
    for k in TOP_K:
        rows.append({"strategy": f"Pythia-Net top {k}", **perf(topk(panel.day[oos], coins[oos], score[oos], panel.fwd[oos], k))})
    ew = np.array([float(np.mean(np.expm1(panel.fwd[oos][panel.day[oos] == d]))) for d in np.unique(panel.day[oos])[::HORIZON_D]])
    rows.append({"strategy": "equal-weight universe", **perf(ew)})
    ic = np.array([f["rank_ic"] for f in folds if np.isfinite(f["rank_ic"])])
    ic_t = float(ic.mean() / (ic.std() / np.sqrt(len(ic)) + 1e-12))
    m2 = {}
    m2_file = root / "reports" / "picks" / "latest.json"
    if m2_file.exists():
        m2 = json.loads(m2_file.read_text())
    title = f"# M3 · {variant} against M2\n\n"
    md = (title +
          f"{len(panel.symbols)} coins, {len(panel.day):,} coin-days, pretrained on data before 2022, fine-tuned per "
          f"quarter. {sum(p.numel() for p in model.parameters()) / 1e6:.2f} M parameters, "
          f"{(time.time() - t0) / 60:.0f} min on {torch.cuda.get_device_name(0)}.\n\n"
          f"**Rank-IC:** Pythia-Net {ic.mean():.4f} (t {ic_t:.1f}), M2 "
          f"{m2.get('rank_ic', float('nan')):.4f} (t {m2.get('rank_ic_t', float('nan')):.1f}).\n\n"
          "| strategy | periods | cagr | sharpe | max_dd |\n|---|---|---|---|---|\n"
          + "".join(f"| {r['strategy']} | {r['periods']} | {r['cagr']:.3f} | {r['sharpe']:.2f} | {r['max_dd']:.3f} |\n" for r in rows)
          + "\n## Rank-IC per quarter\n\n| fold | days | rank_ic |\n|---|---|---|\n"
          + "".join(f"| {f['fold']} | {f['days']} | {f['rank_ic']:.4f} |\n" for f in folds)
          + "\n## Training log\n\n```\n" + "\n".join(log_lines) + "\n```\n")
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for name in (f"{stamp}.md", "latest.md"):
        (out_dir / name).write_text(md, encoding="utf-8")
    (out_dir / "latest.json").write_text(json.dumps({"rows": rows, "folds": folds, "rank_ic": float(ic.mean()),
                                                     "rank_ic_t": ic_t}, indent=2))
    torch.save(model.state_dict(), out_dir / "last_fold.pt")
    print(md)


if __name__ == "__main__":
    main()
