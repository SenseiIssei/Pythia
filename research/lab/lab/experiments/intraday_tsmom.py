"""Intraday time-series momentum: does the UTC day so far predict its last one or two hours?

    PYTHIA_AGENT_OUT=<study folder> python -m lab.experiments.intraday_tsmom

Pre-registered in results/intraday_tsmom_prereg.md (committed before this file ran).
Binance spot hourly bars (2020-01-01 to 2026-10-20) for BTC, ETH and each day's 10 most
liquid coins with a live perp (survivorship-free, decided at the previous close). Three
rules: A (00:00 to 22:00 predicts 22:00 to 24:00), B (the previous 24 hours to 22:00
predicts 22:00 to 24:00), C (00:00 to 23:00 predicts 23:00 to 24:00); position = sign of
the signal, a round trip every traded day, perp taker and maker costs. The in-sample pick
per asset judged from 2024. Writes results/intraday_tsmom.md below the marker and
<reports>/intraday_tsmom/latest.*.
"""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import polars as pl

from .. import report
from ..data import HOUR_US, ROOT
from . import director_common as dc
from . import fam_common as fc
from . import trio_common as tc
from .picks import hourly_segments

NAME = "intraday_tsmom"
LAST_DAY = "2026-10-20"
FIRST_DAY = "2020-01-01"
SPLIT = "2024-01-01"
RULES = ("A", "B", "C")
RULE_TEXT = {"A": "00:00 to 22:00 predicts 22:00 to 24:00", "B": "previous 24 h to 22:00 predicts 22:00 to 24:00",
             "C": "00:00 to 23:00 predicts 23:00 to 24:00"}
ASSETS = ("BTC", "ETH", "TOP10")
TAKER = {"BTC": 0.0005, "ETH": 0.0005, "TOP10": 0.0010}
MAKER = 0.0002
TOP_N = 10
YEARS_OOS = (2024, 2025, 2026)
DAY_US = fc.DAY_US
MIN_US = 60_000_000
LATE_MIN = 4          # the minute bar opening at hh:04 closes at hh:05


# ---------------------------------------------------------------------------
# Prices at the hours that matter
# ---------------------------------------------------------------------------

def hour_closes(h: pl.DataFrame, days: np.ndarray) -> dict[str, np.ndarray]:
    """From hourly bars (open_time_us, close): per calendar day D the prices at 00:00
    (p0, the close of D-1's 23:00 bar), 22:00 (p22, the 21:00 bar's close), 23:00 (p23),
    24:00 (p24) and 22:00 of D-1 (p22_prev). NaN where the bar is missing."""
    d = h.select(day=(pl.col("open_time_us") // DAY_US) * DAY_US,
                 hour=(pl.col("open_time_us") % DAY_US) // HOUR_US, close=pl.col("close"))
    out = {}
    di = {int(x): i for i, x in enumerate(days)}
    for hr in (21, 22, 23):
        g = d.filter(pl.col("hour") == hr)
        v = np.full(len(days), np.nan)
        rows = np.array([di.get(int(x), -1) for x in g["day"].to_numpy()])
        ok = rows >= 0
        v[rows[ok]] = g["close"].to_numpy()[ok]
        out[hr] = v
    p0 = np.full(len(days), np.nan)
    p0[1:] = out[23][:-1]
    p22_prev = np.full(len(days), np.nan)
    p22_prev[1:] = out[21][:-1]
    return {"p0": p0, "p22": out[21], "p23": out[22], "p24": out[23], "p22_prev": p22_prev}


def signal_and_ret(px: dict[str, np.ndarray], rule: str) -> tuple[np.ndarray, np.ndarray, str]:
    """(signal, held return, entry key) for one rule."""
    with np.errstate(invalid="ignore", divide="ignore"):
        if rule == "A":
            return px["p22"] / px["p0"] - 1, px["p24"] / px["p22"] - 1, "p22"
        if rule == "B":
            return px["p22"] / px["p22_prev"] - 1, px["p24"] / px["p22"] - 1, "p22"
        return px["p23"] / px["p0"] - 1, px["p24"] / px["p23"] - 1, "p23"


def daily(sig: np.ndarray, ret: np.ndarray, cost: float) -> tuple[np.ndarray, np.ndarray]:
    """(day return, position): sign of the signal held over the window, a round trip
    (2 x cost) on every traded day, flat where anything is missing."""
    ok = np.isfinite(sig) & np.isfinite(ret)
    pos = np.where(ok, np.sign(np.nan_to_num(sig)), 0.0)
    r = pos * np.nan_to_num(ret) - 2 * cost * np.abs(pos)
    return r, pos


def minute_closes(symbol: str, days: np.ndarray) -> dict[int, np.ndarray]:
    """Close of the minute bars opening at 22:04 and 23:04 per day (prices at 22:05 and
    23:05), read lazily from the 1m archive; empty when the coin has none."""
    d = ROOT / "hist" / "binance_spot" / "klines_1m" / f"symbol={symbol}"
    files = sorted(d.glob("*.parquet"))
    if not files:
        return {}
    mins = [22 * 60 + LATE_MIN, 23 * 60 + LATE_MIN]
    m = (pl.scan_parquet([str(f) for f in files]).select("open_time_us", "close")
         .with_columns(mod=(pl.col("open_time_us") % DAY_US) // MIN_US, day=(pl.col("open_time_us") // DAY_US) * DAY_US)
         .filter(pl.col("mod").is_in(mins)).collect().unique(["day", "mod"], keep="last"))
    di = {int(x): i for i, x in enumerate(days)}
    out = {}
    for mm, key in zip(mins, (22, 23)):
        g = m.filter(pl.col("mod") == mm)
        v = np.full(len(days), np.nan)
        rows = np.array([di.get(int(x), -1) for x in g["day"].to_numpy()])
        ok = rows >= 0
        v[rows[ok]] = g["close"].to_numpy()[ok]
        out[key] = v
    return out


def late_ret(px: dict[str, np.ndarray], mins: dict[int, np.ndarray], rule: str) -> np.ndarray:
    """The held return entered five minutes late (exit unchanged)."""
    if not mins:
        return np.full(len(px["p24"]), np.nan)
    e = mins[22] if rule in ("A", "B") else mins[23]
    with np.errstate(invalid="ignore", divide="ignore"):
        return px["p24"] / e - 1


# ---------------------------------------------------------------------------
# Slope tests (information)
# ---------------------------------------------------------------------------

def slope_nw(x: np.ndarray, y: np.ndarray, lag: int = 5) -> tuple[float, float]:
    ok = np.isfinite(x) & np.isfinite(y)
    x, y = x[ok], y[ok]
    if len(x) < 10:
        return float("nan"), float("nan")
    xc = x - x.mean()
    sxx = float(xc @ xc)
    b = float(xc @ (y - y.mean())) / sxx
    e = y - y.mean() - b * xc
    u = xc * e
    s = float(u @ u)
    for k in range(1, lag + 1):
        s += 2 * (1 - k / (lag + 1)) * float(u[k:] @ u[:-k])
    return b, b / np.sqrt(s / sxx ** 2) if s > 0 else float("nan")


def slope_cluster(x: np.ndarray, y: np.ndarray, groups: np.ndarray) -> tuple[float, float]:
    ok = np.isfinite(x) & np.isfinite(y)
    x, y, g = x[ok], y[ok], groups[ok]
    if len(x) < 10:
        return float("nan"), float("nan")
    xc = x - x.mean()
    sxx = float(xc @ xc)
    b = float(xc @ (y - y.mean())) / sxx
    u = xc * (y - y.mean() - b * xc)
    _, inv = np.unique(g, return_inverse=True)
    s = float((np.bincount(inv, weights=u) ** 2).sum())
    return b, b / np.sqrt(s / sxx ** 2) if s > 0 else float("nan")


# ---------------------------------------------------------------------------
# Assets
# ---------------------------------------------------------------------------

def segment_by_name(names: set[str]) -> dict[str, pl.DataFrame]:
    """Hourly bars of panel segments by their panel name (picks.py's segmentation)."""
    out = {}
    for s in sorted({n.split("~")[0] for n in names}):
        segs = hourly_segments(s)
        for j, seg in enumerate(segs):
            nm = s if j == len(segs) - 1 else f"{s}~{j}"
            if nm in names:
                out[nm] = seg.select("open_time_us", "close")
    return out


def single(symbol: str, days: np.ndarray) -> dict:
    segs = hourly_segments(symbol)
    h = pl.concat([s.select("open_time_us", "close") for s in segs])
    return {"px": hour_closes(h, days), "mins": minute_closes(symbol, days)}


def basket(P: fc.Panel, days: np.ndarray) -> dict:
    """The day's 10 most liquid coins with a live perp, chosen at the previous close."""
    top = P.top_liquid(TOP_N, need_perp=True)
    mem = np.zeros_like(top)
    mem[1:] = top[:-1]
    cols = np.flatnonzero(mem.any(0))
    hb = segment_by_name({P.names[j] for j in cols})
    coins = []
    for j in cols:
        nm = P.names[j]
        if nm not in hb:
            continue
        px = hour_closes(hb[nm], days)
        sym = nm.split("~")[0]
        mins = minute_closes(sym, days) if "~" not in nm else {}
        coins.append({"name": nm, "member": mem[:, j], "px": px, "mins": mins})
    return {"coins": coins, "n_members": mem.sum(1)}


def asset_rule(a: dict, rule: str, cost: float, is_basket: bool) -> dict[str, np.ndarray]:
    """Day returns at `cost`, positions, the five-minute-late returns and the raw
    signal/held pairs for the slope."""
    if not is_basket:
        s, r, _ = signal_and_ret(a["px"], rule)
        d, pos = daily(s, r, cost)
        dl, _ = daily(s, late_ret(a["px"], a["mins"], rule), cost)
        return {"r": d, "pos": pos, "late": dl if a["mins"] else np.full(len(d), np.nan), "sig": s, "held": r,
                "late_cover": 1.0 if a["mins"] else 0.0}
    T = len(a["n_members"])
    tot, late_tot, traded = np.zeros(T), np.zeros(T), np.zeros(T)
    sig_all, held_all, grp = [], [], []
    late_slots, all_slots = 0.0, 0.0
    for c in a["coins"]:
        s, r, _ = signal_and_ret(c["px"], rule)
        m = c["member"]
        d, pos = daily(np.where(m, s, np.nan), r, cost)
        tot += d / TOP_N
        traded += np.abs(pos) / TOP_N
        all_slots += float(m.sum())
        if c["mins"]:
            dl, _ = daily(np.where(m, s, np.nan), late_ret(c["px"], c["mins"], rule), cost)
            late_tot += dl / TOP_N
            late_slots += float(m.sum())
        idx = np.flatnonzero(m)
        sig_all.append(s[idx])
        held_all.append(r[idx])
        grp.append(idx)
    return {"r": tot, "pos": traded, "late": late_tot, "sig": np.concatenate(sig_all), "held": np.concatenate(held_all),
            "grp": np.concatenate(grp), "late_cover": late_slots / max(all_slots, 1.0)}


def main() -> None:
    P = dc.cut_panel(fc.load_panel(), LAST_DAY)
    days = P.days
    years = dc.years_of(days)
    ins = (days >= dc.us(FIRST_DAY)) & (days < dc.us(SPLIT))
    oos = days >= dc.us(SPLIT)
    data = {"BTC": single("BTCUSDT", days), "ETH": single("ETHUSDT", days), "TOP10": basket(P, days)}
    print("prices ready", flush=True)
    ins_top = ins & (data["TOP10"]["n_members"] >= TOP_N)
    rows, judged = [], {}
    for asset in ASSETS:
        is_b = asset == "TOP10"
        a = data[asset]
        win_in = ins_top if is_b else ins
        for rule in RULES:
            o = {k: asset_rule(a, rule, v, is_b) for k, v in (("0bps", 0.0), ("maker", MAKER), ("taker", TAKER[asset]))}
            x = o["taker"]["r"]
            row = {"asset": asset, "rule": rule, "is_taker": dc.sharpe(x[win_in]), "is_0bps": dc.sharpe(o["0bps"]["r"][win_in]),
                   **{f"oos_{k}": dc.sharpe(v["r"][oos]) for k, v in o.items()},
                   "late_taker": dc.sharpe(o["taker"]["late"][oos]), "late_cover": o["taker"]["late_cover"]}
            p = dc.perf(x[oos])
            row["oos_cagr_pct"], row["oos_dd_pct"] = p["cagr"] * 100, p["max_dd"] * 100
            for y in YEARS_OOS:
                row[f"y{y}"] = dc.sharpe(x[oos & (years == y)])
            pos = o["0bps"]["pos"]
            gross = o["0bps"]["r"]
            tr = oos & (pos != 0)
            row["traded_days_pct"] = 100 * float(tr.mean() / max(oos.mean(), 1e-12))
            row["mean_bps_per_traded_day"] = float(gross[tr].sum() / max(np.abs(pos[tr]).sum(), 1e-12) * 1e4)
            row["round_trip_taker_bps"] = 2 * TAKER[asset] * 1e4
            if is_b:
                held = o["0bps"]["held"]
                sig = o["0bps"]["sig"]
                grp = o["0bps"]["grp"]
                oo = oos[grp]
                row["hit_pct"] = 100 * float((np.sign(sig[oo]) * held[oo] > 0)[np.isfinite(sig[oo] * held[oo])].mean())
                row["slope_oos"], row["slope_t_oos"] = slope_cluster(sig[oo], held[oo], grp[oo])
                row["slope_is"], row["slope_t_is"] = slope_cluster(sig[~oo], held[~oo], grp[~oo])
            else:
                s_, h_ = o["0bps"]["sig"], o["0bps"]["held"]
                hit = np.sign(s_) * h_
                row["hit_pct"] = 100 * float((hit[oos & np.isfinite(hit)] > 0).mean())
                row["slope_oos"], row["slope_t_oos"] = slope_nw(s_[oos], h_[oos])
                row["slope_is"], row["slope_t_is"] = slope_nw(s_[ins], h_[ins])
            rows.append(row)
            judged[(asset, rule)] = x
            print(asset, rule, round(row["is_taker"], 2), round(row["oos_taker"], 2), flush=True)

    # Controls: always long over the last two hours (and the last hour).
    controls = []
    for asset in ("BTC", "ETH"):
        px = data[asset]["px"]
        for lab_, e in (("22:00 to 24:00", "p22"), ("23:00 to 24:00", "p23")):
            with np.errstate(invalid="ignore", divide="ignore"):
                r = px["p24"] / px[e] - 1
            for c_lab, c in (("0bps", 0.0), ("taker", TAKER[asset])):
                d, _ = daily(np.ones(len(r)), r, c)
                controls.append({"asset": asset, "window": lab_, "cost": c_lab, "is": dc.sharpe(d[ins]),
                                 "oos": dc.sharpe(d[oos]), "mean_bps_oos": float(np.nanmean(r[oos]) * 1e4)})

    pl_ = tc.pool([r["oos_taker"] for r in rows])
    picks = []
    for asset in ASSETS:
        cand = [r for r in rows if r["asset"] == asset]
        pick = max(cand, key=lambda r: r["is_taker"])
        x = judged[(asset, pick["rule"])]
        lo, hi, above = tc.boot(x[oos])
        pick = {**pick, "boot_p05": lo, "boot_p95": hi, "boot_above0": above, "deflated_p": dc.deflated(x[oos], pl_)}
        pick["checks"] = {"1 Sharpe above 0.5 at taker": pick["oos_taker"] > 0.5,
                          "2 positive in 2 of 2024, 2025, 2026": sum(pick[f"y{y}"] > 0 for y in YEARS_OOS) >= 2,
                          "3 five minutes late above 0 at taker": pick["late_taker"] > 0,
                          "4 bootstrap 5 % above 0": lo > 0}
        pick["passes"] = all(pick["checks"].values())
        pick["verdict"] = ("pass, confirmed" if pick["deflated_p"] > 0.95 else "pass, experimental") if pick["passes"] \
            else ("kill" if pick["oos_0bps"] <= 0 else "fail")
        picks.append(pick)
    res = {"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "panel_to": dc.day_str(days[-1]),
           "rows": rows, "picks": picks, "controls": controls, "pool": pl_,
           "top10_names": sorted({c["name"] for c in data["TOP10"]["coins"]})}
    write(res)


def write(res: dict) -> None:
    md = ["# Intraday time-series momentum in BTC, ETH and the top-10 perps: results\n",
          f"Generated {res['generated']}. Registered in `results/intraday_tsmom_prereg.md` before the run. Binance spot "
          f"hourly bars to {res['panel_to']}; in sample 2020 to 2023, out of sample from 2024-01-01. Costs per side: "
          "taker 5 bps (BTC, ETH) and 10 bps (top 10), maker 2 bps; a round trip on every traded day. Daily returns, "
          "flat days as zero.\n", "## Verdict\n"]
    for p in res["picks"]:
        f = ", ".join(k for k, ok in p["checks"].items() if not ok) or "none"
        md.append(f"- **{p['asset']}**, pick rule {p['rule']} ({RULE_TEXT[p['rule']]}): **{p['verdict']}**. Out of "
                  f"sample Sharpe {p['oos_taker']:.2f} at taker, {p['oos_maker']:.2f} at maker, {p['oos_0bps']:.2f} before "
                  f"costs; years {p['y2024']:.2f} / {p['y2025']:.2f} / {p['y2026']:.2f}; five minutes late "
                  f"{p['late_taker']:.2f}; band {p['boot_p05']:.2f} to {p['boot_p95']:.2f}; drawdown {p['oos_dd_pct']:.0f} %; "
                  f"{p['mean_bps_per_traded_day']:.1f} bps per traded day before costs against a {p['round_trip_taker_bps']:.0f} "
                  f"bps taker round trip; slope t {p['slope_t_oos']:.2f}; deflated p {p['deflated_p']:.4f}. "
                  f"Failed: {f}.")
    md.append("\n## All nine trials\n")
    md.append(dc.table(res["rows"], ["asset", "rule", "is_0bps", "is_taker", "oos_0bps", "oos_maker", "oos_taker",
                                     "late_taker", "y2024", "y2025", "y2026", "oos_dd_pct", "hit_pct",
                                     "mean_bps_per_traded_day", "traded_days_pct"]))
    md.append("\n`late_taker`: entered at the 22:05 (rule C: 23:05) minute close, exit unchanged; for the top 10 only "
              "the coins with minute bars trade in that check (share of member slots: "
              + ", ".join(f"{r['rule']} {r['late_cover'] * 100:.0f} %" for r in res["rows"] if r["asset"] == "TOP10")
              + ").\n")
    md.append("\nSlope of the held return on the signal (Newey-West t, lag 5; the top 10 pooled over coin-days, t "
              "clustered by day):\n")
    md.append(dc.table(res["rows"], ["asset", "rule", "slope_is", "slope_t_is", "slope_oos", "slope_t_oos"], ".3f"))
    md.append("\n## Control: always long over the window\n")
    md.append(dc.table(res["controls"], ["asset", "window", "cost", "is", "oos", "mean_bps_oos"]))
    md.append(f"\nTop-10 coins that were members at some point: {len(res['top10_names'])}.\n")
    md.append("\n## Pool\n\n" + tc.pool_line(res["pool"]) + "\n")
    text = "\n".join(md)
    dc.write_results(NAME, text)
    report.write(NAME, text, res)


if __name__ == "__main__":
    main()
