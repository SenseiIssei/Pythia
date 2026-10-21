"""Short the Kraken perp against a spot long when Kraken's funding runs above Binance's?

    python -m lab.experiments.kraken_funding_gap [--kraken DIR]

Pre-registered in results/kraken_funding_gap_prereg.md (committed before this file ran).
Kraken Futures hourly funding and mark prices from lab.collect.kraken_futures (about a
year, from 2025-10-15), Binance USD-M funding and Binance spot hourly closes (the spot
leg's price) from the lake. Hourly decisions; at most 10 positions of 8 % notional each;
costs 35 bps a side on spot (Alpaca) and 10 bps on the perp. In sample to 2026-03-31,
out of sample 2026-04-01 to 2026-10-19. Writes results/kraken_funding_gap.md below the
marker and <reports>/kraken_funding_gap/latest.*.
"""

from __future__ import annotations

import argparse
import itertools
import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import polars as pl

from .. import report
from ..data import ROOT
from ..universe import ALPACA
from . import director_common as dc
from . import perps_common as pc

NAME = "kraken_funding_gap"
H = 3_600_000_000
START, OOS_FROM, END = "2025-10-18", "2026-04-01", "2026-10-20"   # END exclusive: last hour 2026-10-19 23:00
THETAS = (0.20, 0.50)
WINDOWS = (24, 72)
MAX_POS, NOTIONAL, SLOT = 10, 0.08, 0.10
SPOT_COST, PERP_COST = pc.ALPACA_TAKER, pc.JUDGED
MAKER_SPOT, MAKER_PERP = 0.0015, 0.0
MIN_ENTRIES = 10
KR_ALIAS = {"BTC": "XBT"}


def binance_perp(coin: str) -> str | None:
    for p in ("", "1000", "1000000"):
        s = f"{p}{coin}USDT"
        if (ROOT / "hist" / "binance_um" / "funding" / f"symbol={s}").exists():
            return s
    return None


def read_dir(d: Path, cols: list[str], since_us: int) -> pl.DataFrame:
    files = [f for f in sorted(d.glob("*.parquet")) if f.stem >= datetime.fromtimestamp(since_us / 1e6 - 86400 * 4,
                                                                                         timezone.utc).strftime("%Y-%m")]
    if not files:
        return pl.DataFrame()
    return pl.concat([pl.read_parquet(f, columns=cols) for f in files], how="vertical_relaxed")


def load(kdir: Path) -> dict:
    """Hourly matrices on boundaries b (the end of an hour): spot close, Kraken mark close,
    Kraken funding paid at b, Binance funding settled in the hour ending at b."""
    t0 = dc.us(START) - 96 * H
    t1 = dc.us(END)
    grid = np.arange(t0, t1 + H, H, dtype=np.int64)
    gi = {int(b): i for i, b in enumerate(grid)}
    coins, spot, mark, kf, bf = [], [], [], [], []
    for c in ALPACA:
        ks = f"PF_{KR_ALIAS.get(c, c)}USD"
        fp, mp = kdir / "funding" / f"{ks}.parquet", kdir / "mark_1h" / f"{ks}.parquet"
        bp = binance_perp(c)
        sd = ROOT / "hist" / "binance_spot" / "klines_1h" / f"symbol={c}USDT"
        if not (fp.exists() and mp.exists() and bp and sd.exists()):
            continue
        s = read_dir(sd, ["open_time_us", "close"], t0).unique("open_time_us")
        m = pl.read_parquet(mp)
        f = pl.read_parquet(fp)
        b = read_dir(ROOT / "hist" / "binance_um" / "funding" / f"symbol={bp}", ["funding_time_us", "funding_rate"],
                     t0).unique("funding_time_us")

        def put(ts: np.ndarray, v: np.ndarray, how: str = "set") -> np.ndarray:
            out = np.full(len(grid), np.nan) if how == "set" else np.zeros(len(grid))
            for x, y in zip(ts, v):
                i = gi.get(int(x))
                if i is not None:
                    if how == "set":
                        out[i] = y
                    else:
                        out[i] += y
            return out
        sp = put(s["open_time_us"].to_numpy() + H, s["close"].to_numpy())
        mk = put(m["ts_us"].to_numpy() + H, m["close"].to_numpy())
        if np.isfinite(sp).sum() < 0.9 * len(grid) or np.isfinite(mk).sum() < 0.9 * len(grid):
            continue
        coins.append(c)
        spot.append(sp)
        mark.append(mk)
        kf.append(put(f["ts_us"].to_numpy(), f["rate"].to_numpy()))
        bft = (b["funding_time_us"].to_numpy() // H) * H
        bf.append(put(bft, b["funding_rate"].to_numpy(), how="add"))
    S = pl.DataFrame(np.array(spot).T).fill_null(strategy="forward").to_numpy()
    M = pl.DataFrame(np.array(mark).T).fill_null(strategy="forward").to_numpy()
    with np.errstate(invalid="ignore", divide="ignore"):
        rs = np.vstack([np.full(len(coins), np.nan), S[1:] / S[:-1] - 1])
        rm = np.vstack([np.full(len(coins), np.nan), M[1:] / M[:-1] - 1])
    return {"grid": grid, "coins": coins, "rs": np.nan_to_num(rs), "rm": np.nan_to_num(rm),
            "kf": np.array(kf).T, "bf": np.array(bf).T}


def signals(D: dict, W: int) -> tuple[np.ndarray, np.ndarray]:
    kf = np.nan_to_num(D["kf"])
    have = np.isfinite(D["kf"]).astype(float)
    cs, ch, cb = np.cumsum(kf, 0), np.cumsum(have, 0), np.cumsum(D["bf"], 0)
    lag = lambda a: np.vstack([np.zeros((W, a.shape[1])), a[:-W]])  # noqa: E731
    with np.errstate(invalid="ignore", divide="ignore"):
        K = (cs - lag(cs)) / (ch - lag(ch)) * 8760
    B = (cb - lag(cb)) * 8760 / W
    K[:W] = np.nan
    return K, B


def run(D: dict, theta: float, W: int, spot_cost: float = SPOT_COST, perp_cost: float = PERP_COST) -> dict:
    """Hourly book. Decided at boundary b, held over the hour to b+1."""
    K, B = signals(D, W)
    gap = K - B
    T, N = K.shape
    grid = D["grid"]
    first = int(np.searchsorted(grid, dc.us(START)))
    last = int(np.searchsorted(grid, dc.us(END)))
    held = np.zeros(N, dtype=bool)
    pnl, fund, basis, cost, deployed = (np.zeros(T) for _ in range(5))
    entries = []
    one = NOTIONAL * (spot_cost + perp_cost)
    for t in range(first, min(last, T - 1)):
        ok = np.isfinite(gap[t])
        out = held & (~ok | (gap[t] <= 0) | (K[t] <= 0))
        held &= ~out
        cost[t + 1] -= one * out.sum()
        cand = np.flatnonzero(~held & ok & (gap[t] >= theta) & (K[t] > 0))
        free = MAX_POS - held.sum()
        if free > 0 and len(cand):
            pick = cand[np.argsort(-gap[t, cand])][:free]
            held[pick] = True
            cost[t + 1] -= one * len(pick)
            entries += [(int(grid[t]), D["coins"][i]) for i in pick]
        h = np.flatnonzero(held)
        fund[t + 1] = NOTIONAL * np.nan_to_num(D["kf"][t + 1, h]).sum()
        basis[t + 1] = NOTIONAL * (D["rs"][t + 1, h] - D["rm"][t + 1, h]).sum()
        deployed[t + 1] = SLOT * len(h)
    pnl = fund + basis + cost
    return {"pnl": pnl, "fund": fund, "basis": basis, "cost": cost, "deployed": deployed, "entries": entries,
            "K": K, "B": B}


def daily(grid: np.ndarray, x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    day = (grid - H) // (24 * H)   # an hour ending at midnight belongs to the day before
    u, inv = np.unique(day, return_inverse=True)
    return u * 24 * H, np.bincount(inv, weights=x)


def measure(D: dict, o: dict, lo_us: int, hi_us: int) -> dict:
    g = D["grid"]
    m = (g > lo_us) & (g <= hi_us)
    days, r = daily(g[m], o["pnl"][m])
    dep = o["deployed"][m].sum()
    yrs = m.sum() / 8760
    wk = pl.DataFrame({"d": days, "r": r}).with_columns(
        w=pl.from_epoch("d", time_unit="us").dt.truncate("1w")).group_by("w").agg(pl.col("r").sum())
    n_ent = sum(1 for t, _ in o["entries"] if lo_us <= t < hi_us)
    return {"entries": n_ent, "ret_capital_ann": float(o["pnl"][m].sum() / yrs),
            "carry_deployed_ann": float(o["pnl"][m].sum() / dep * 8760) if dep > 0 else float("nan"),
            "funding_deployed_ann": float(o["fund"][m].sum() / dep * 8760) if dep > 0 else float("nan"),
            "basis_deployed_ann": float(o["basis"][m].sum() / dep * 8760) if dep > 0 else float("nan"),
            "cost_deployed_ann": float(o["cost"][m].sum() / dep * 8760) if dep > 0 else float("nan"),
            "avg_positions": float(o["deployed"][m].mean() / SLOT), "sharpe": dc.sharpe(r),
            "worst_week": float(wk["r"].min()) if wk.height else float("nan"), "_daily": r}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kraken", default=str(ROOT / "kraken_futures"))
    a = ap.parse_args(argv)
    D = load(Path(a.kraken))
    lo, mid, hi = dc.us(START), dc.us(OOS_FROM), dc.us(END)
    rows, outs = [], {}
    for th, W in itertools.product(THETAS, WINDOWS):
        o = run(D, th, W)
        name = f"gap >= {th * 100:.0f} % · {W} h"
        i_, s_ = measure(D, o, lo, mid), measure(D, o, mid, hi)
        outs[name] = (o, s_)
        rows.append({"variant": name, "theta": th, "W": W, **{f"is_{k}": v for k, v in i_.items() if k != "_daily"},
                     **{f"oos_{k}": v for k, v in s_.items() if k != "_daily"}})
        print(name, i_["entries"], round(i_["ret_capital_ann"], 4), s_["entries"], round(s_["ret_capital_ann"], 4),
              flush=True)
    pick = max(rows, key=lambda r: r["is_ret_capital_ann"])
    o, s_ = outs[pick["variant"]]
    r = s_["_daily"]
    pl_ = pc.pool([x["oos_sharpe"] for x in rows])
    blo, bhi, bab = pc.boot(r)
    mk = measure(D, run(D, pick["theta"], pick["W"], MAKER_SPOT, MAKER_PERP), mid, hi)
    pk = {"variant": pick["variant"], **{k: v for k, v in s_.items() if k != "_daily"}, "boot_p05": blo,
          "boot_p95": bhi, "boot_above0": bab, "deflated_p": dc.deflated(r, pl_),
          "maker_carry_deployed_ann": mk["carry_deployed_ann"], "maker_sharpe": mk["sharpe"]}
    gates = {"1 at least 10 entries": pk["entries"] >= MIN_ENTRIES,
             "2 net carry above 5 % a year on deployed capital": pk["carry_deployed_ann"] > 0.05,
             "3 worst week above -2 %": pk["worst_week"] > -0.02,
             "4 Sharpe above 0, bootstrap 5 % above 0": pk["sharpe"] > 0 and blo > 0}
    pk["gates"] = gates
    killed = pk["entries"] < MIN_ENTRIES or not pk["carry_deployed_ann"] >= 0.02
    pk["verdict"] = ("kill" if killed else ("pass (confirmed)" if pk["deflated_p"] > 0.95 else "pass, not confirmed")
                     if all(gates.values()) else "fails")
    # Per coin, the whole year: Kraken minus Binance funding (24 h windows, annualised).
    K, B = signals(D, 24)
    m = (D["grid"] > lo) & (D["grid"] <= hi)
    coin_rows = []
    for j, c in enumerate(D["coins"]):
        kk = np.nan_to_num(D["kf"][m, j]).mean() * 8760
        bb = D["bf"][m, j].mean() * 8760
        g = (K - B)[m, j]
        coin_rows.append({"coin": c, "kraken_ann_pct": kk * 100, "binance_ann_pct": bb * 100,
                          "gap_ann_pct": (kk - bb) * 100, "share_gap_above_20": float(np.nanmean(g >= 0.20)),
                          "share_gap_above_50": float(np.nanmean(g >= 0.50))})
    res = {"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "coins": D["coins"], "rows": rows,
           "pick": pk, "pool": pl_, "per_coin": sorted(coin_rows, key=lambda x: -x["gap_ann_pct"])}
    write(res)


def write(res: dict) -> None:
    pk, pl_ = res["pick"], res["pool"]
    pct = lambda v: "n/a" if v is None or not math.isfinite(v) else f"{v * 100:.1f} %"  # noqa: E731
    md = ["# Kraken against Binance funding gaps: results\n",
          f"Generated {res['generated']}. Registered in `results/kraken_funding_gap_prereg.md` before the run.\n",
          f"{len(res['coins'])} Alpaca coins with Kraken Futures funding and marks, Binance funding and Binance spot: "
          f"{', '.join(res['coins'])}. In sample {START} to 2026-03-31, out of sample {OOS_FROM} to 2026-10-19 "
          "(hourly). Short the Kraken perp, long spot, 8 % notional a position, at most 10; 35 bps a side on spot and "
          "10 bps on the perp.\n",
          f"## Verdict\n\nPick **{pk['variant']}**: **{pk['verdict']}**. Out of sample {pk['entries']} entries, net carry "
          f"{pct(pk['carry_deployed_ann'])} a year on deployed capital (funding {pct(pk['funding_deployed_ann'])}, "
          f"basis {pct(pk['basis_deployed_ann'])}, costs {pct(pk['cost_deployed_ann'])}), {pct(pk['ret_capital_ann'])} a "
          f"year on all capital, {pk['avg_positions']:.1f} positions on average, Sharpe {pk['sharpe']:.2f} (band "
          f"{pk['boot_p05']:.2f} to {pk['boot_p95']:.2f}), worst week {pct(pk['worst_week'])}, deflated p "
          f"{pk['deflated_p']:.4f}. Maker on both legs (information): {pct(pk['maker_carry_deployed_ann'])} on deployed "
          f"capital, Sharpe {pk['maker_sharpe']:.2f}.\n"]
    for k, v in pk["gates"].items():
        md.append(f"- {k}: {'yes' if v else 'no'}")
    md.append("\n## Every variant\n")
    tab = [{**r, **{f"{w}_{k}_pct": r[f"{w}_{k}"] * 100 for w in ("is", "oos")
                    for k in ("ret_capital_ann", "carry_deployed_ann", "funding_deployed_ann", "basis_deployed_ann",
                              "cost_deployed_ann", "worst_week")}} for r in res["rows"]]
    md.append(dc.table(tab, ["variant", "is_entries", "is_ret_capital_ann_pct", "is_carry_deployed_ann_pct", "is_sharpe",
                             "oos_entries", "oos_ret_capital_ann_pct", "oos_carry_deployed_ann_pct",
                             "oos_funding_deployed_ann_pct", "oos_basis_deployed_ann_pct", "oos_cost_deployed_ann_pct",
                             "oos_avg_positions", "oos_sharpe", "oos_worst_week_pct"], ".2f"))
    md.append("\nReturns a year: on all capital, and on deployed capital (10 % a position incl. perp margin), split into "
              "Kraken funding received, basis (spot minus perp mark) and costs.\n")
    md.append("\n## Kraken against Binance funding per coin, the whole window (information only)\n")
    md.append(dc.table(res["per_coin"], ["coin", "kraken_ann_pct", "binance_ann_pct", "gap_ann_pct",
                                         "share_gap_above_20", "share_gap_above_50"], ".2f"))
    md.append("\nMean funding a year a long pays (%), and the share of hours the 24-hour gap was at least 20 % / 50 % a "
              "year.\n")
    md.append(f"\n## Pool\n\n{pl_['n_total']:,} trials ({pl_['hand_trials']:,} hand, {pl_['factory_trials']} factory, "
              f"{pl_['today_trials']} registered today); the best noise trial sits at an annual Sharpe of about "
              f"{pl_['sr0_annual']:.2f}.\n")
    text = "\n".join(md)
    dc.write_results(NAME, text)
    report.write(NAME, text, res)


if __name__ == "__main__":
    main()
