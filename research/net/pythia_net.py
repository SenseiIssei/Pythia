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

def load_hourly(root: Path, symbol: str) -> pl.DataFrame | None:
    d = root / "hist" / "binance_spot" / "klines_1h" / f"symbol={symbol}"
    files = sorted(d.glob("*.parquet"))
    if not files:
        return None
    h = pl.concat([pl.read_parquet(f) for f in files], how="vertical_relaxed").unique("open_time_us").sort("open_time_us")
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
        for s in syms:
            h = load_hourly(root, s)
            if h is None:
                continue
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
                delisted_inside = j >= len(ts) and ts[-1] < (time.time() * 1e6 - 3 * DAY_US)
                if j < len(ts):
                    fwd = math.log(close[j - 1] / close[i - 1])
                    fvol = math.log(float((r[i:j] ** 2).sum()) + 1e-10)
                elif delisted_inside:  # keep the losers: return to the last close
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
        print(f"panel: {len(self.symbols)} coins, {len(a):,} coin-days", flush=True)

    def window(self, rows: np.ndarray) -> torch.Tensor:
        out = np.empty((len(rows), WINDOW_H, CHANNELS), dtype=np.float32)
        for k, r in enumerate(rows):
            i = self.idx[r]
            out[k] = self.series[self.coin[r]][i - WINDOW_H:i]
        return torch.from_numpy(out)


# ── model ─────────────────────────────────────────────────────────────────────

class PythiaNet(nn.Module):
    def __init__(self, d: int = 128, layers: int = 4, heads: int = 4, dropout: float = 0.1):
        super().__init__()
        self.embed = nn.Linear(PATCH * CHANNELS, d)
        self.pos = nn.Parameter(torch.zeros(1, N_PATCH + 1, d))
        self.cls = nn.Parameter(torch.zeros(1, 1, d))
        self.mask_token = nn.Parameter(torch.zeros(1, 1, d))
        enc = nn.TransformerEncoderLayer(d, heads, 4 * d, dropout, batch_first=True, norm_first=True)
        self.encoder = nn.TransformerEncoder(enc, layers)
        self.norm = nn.LayerNorm(d)
        self.recon = nn.Linear(d, PATCH * CHANNELS)
        self.rank_head = nn.Sequential(nn.Linear(d, d), nn.GELU(), nn.Linear(d, 1))
        self.vol_head = nn.Sequential(nn.Linear(d, d), nn.GELU(), nn.Linear(d, 1))
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

    def forward(self, x: torch.Tensor):
        h = self.encode(self.patches(x))[:, 0]
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


def finetune(model: PythiaNet, panel: Panel, rows: np.ndarray, dev, epochs: int, batch: int) -> None:
    rows = rows[np.isfinite(panel.rank_target[rows]) & np.isfinite(panel.fvol[rows])]
    vol_mu, vol_sd = float(np.mean(panel.fvol[rows])), float(np.std(panel.fvol[rows]) + 1e-6)
    model.vol_norm = (vol_mu, vol_sd)
    head_params = list(model.rank_head.parameters()) + list(model.vol_head.parameters())
    opt = torch.optim.AdamW([{"params": head_params, "lr": 1e-3},
                             {"params": [p for n_, p in model.named_parameters() if "head" not in n_], "lr": 1e-4}],
                            weight_decay=0.05)
    model.train()
    for _ in range(epochs):
        perm = np.random.permutation(rows)
        for s in range(0, len(perm), batch):
            b = perm[s:s + batch]
            x = standardise(panel.window(b).to(dev, non_blocking=True))
            yr = torch.from_numpy(panel.rank_target[b]).to(dev)
            yv = torch.from_numpy(((panel.fvol[b] - vol_mu) / vol_sd).astype(np.float32)).to(dev)
            with torch.autocast("cuda", dtype=torch.bfloat16):
                pr, pv = model(x)
                loss = F.mse_loss(pr.float(), yr) + 0.5 * F.mse_loss(pv.float(), yv)
            opt.zero_grad(set_to_none=True)
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()


@torch.no_grad()
def predict(model: PythiaNet, panel: Panel, rows: np.ndarray, dev, batch: int) -> np.ndarray:
    model.eval()
    out = []
    for s in range(0, len(rows), batch):
        x = standardise(panel.window(rows[s:s + batch]).to(dev))
        with torch.autocast("cuda", dtype=torch.bfloat16):
            pr, _ = model(x)
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
    args = ap.parse_args()
    root = Path(args.data)
    dev = torch.device("cuda")
    torch.manual_seed(7)
    np.random.seed(7)
    t0 = time.time()
    out_dir = root / "reports" / "pythia_net"
    out_dir.mkdir(parents=True, exist_ok=True)
    log_lines: list[str] = []

    def log(msg: str) -> None:
        line = f"{time.time() - t0:7.0f}s  {msg}"
        print(line, flush=True)
        log_lines.append(line)

    panel = Panel(root, args.max_coins)
    first_test = int(FIRST_TEST.timestamp() * 1e6)
    starts = quarter_starts(FIRST_TEST, int(panel.day.max()))
    model = PythiaNet().to(dev)
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
        finetune(model, panel, tr, dev, args.finetune_epochs, args.batch)
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
    md = ("# M3 · Pythia-Net against M2\n\n"
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
