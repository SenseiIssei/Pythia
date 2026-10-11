"""Blend and turnover study of the two sweep candidates that run as paper books.

    python -m lab.experiments.blend_study

Pre-registered in results/blend_study.md (the section above the generated part
was committed before this file ran). Three parts:

  1. blend   breakout_top10 (A) and tsmom_top20 (B), optionally with the
             low-turnover Donchian 55/27 BTC+ETH regime book (C), as
             sub-accounts: equal capital or inverse volatility, with and
             without a book vol target. 12 variants.
  2. turnover B rebalanced daily or weekly with no-trade bands; A's signal
             checked daily, every 3 days or weekly. 9 new variants.
  3. combined the blend pick rebuilt from the part 2 picks, if they differ.

After the pre-registration one robustness check was added and counted: a weekly
pick re-run with the rebalance on each of the other six weekdays.

Ground: the sweep's cached panel (copied into $PYTHIA_AGENT_OUT/cache, so the
panel is the one the sweep judged), its split and cost convention. The long-only
simulator here is fam_common.simulate plus a no-trade band; with band 0 it
reproduces fam_common.simulate exactly, which is asserted. The sweep's 100
trials and the breakout study's 54 are read from $PYTHIA_DATA/agent-strategies
and $PYTHIA_DATA/agent-breakout (read only) and counted in the deflation.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np
from scipy import stats

from ..data import ROOT
from . import breakout_study as bs
from . import fam_breakout, fam_volmom
from . import fam_common as fc

NAME = "blend_study"
SWEEP = ROOT / "agent-strategies"
BREAKOUT = ROOT / "agent-breakout"
START = 60
COSTS = {"15bps": 0.0015, "41bps": 0.0041, "80bps": 0.0080}
REWEIGHT, RESCALE = 30, 7          # days between capital re-sets and vol-target re-sets
VOL_WIN, BOOK_VOL_WIN = 90, 60     # sleeve vol window (as fam_ensemble), book vol window
MAX_SCALE = 3.0
VOL_TARGETS = (None, 0.15, 0.25)
WEIGHTINGS = ("equal capital", "inverse vol")
BANDS = {"0": 0.0, "20 %": 0.2, "50 %": 0.5, "entries and exits only": math.inf}
B_REBALANCE = {"daily": 1, "weekly": 7}
A_EVERY = {"daily": 1, "every 3 days": 3, "weekly": 7}
YEARS = range(2021, 2027)
BOOT_DRAWS, BOOT_BLOCK = 10_000, 20
MARKER = "<!-- generated below by lab.experiments.blend_study; edit above this line only -->"


@dataclass
class Book:
    """A long-only book's daily series: gross return earned on day t, one-way turnover
    traded at the close of day t (charged on t+1), gross exposure after the close of t."""
    name: str
    gross: np.ndarray
    turnover: np.ndarray
    expo: np.ndarray

    def net(self, cost: float) -> np.ndarray:
        return self.gross - cost * np.r_[0.0, self.turnover[:-1]]


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------

def sim_long(P: fc.Panel, W: np.ndarray, name: str = "", rebalance: np.ndarray | None = None,
             band: float = 0.0, start: int = START) -> Book:
    """fc.simulate for long-only weights, with a no-trade band.

    On a rebalance day a held coin whose target is not zero is resized only when
    |target - current| > band x target. Entries (current 0) and exits (target 0)
    always trade. band = inf trades entries and exits only.
    """
    T, N = W.shape
    if rebalance is None:
        rebalance = np.ones(T, dtype=bool)
    w = np.zeros(N)
    gross, tov, expo = np.zeros(T), np.zeros(T), np.zeros(T)
    for t in range(start, T - 1):
        if rebalance[t]:
            tgt = np.where(np.isnan(W[t]), w, W[t])
            tgt = np.where(P.traded[t] | (tgt == w), tgt, w)
            if band > 0:
                resize = (w > 0) & (tgt > 0)
                small = resize & (np.abs(tgt - w) <= band * np.where(resize, tgt, 1.0))
                tgt = np.where(small, w, tgt)
            tov[t] += np.abs(tgt - w).sum()
            w = tgt
        r = np.nan_to_num(P.ret[t + 1])
        g = float(np.dot(w, r))
        gross[t + 1] = g
        expo[t] = w.sum()
        w = w * (1 + r) / (1 + g) if 1 + g > 0 else np.zeros(N)
        dead = (w != 0) & ~P.alive[t + 1]
        if dead.any():
            tov[t + 1] += np.abs(w[dead]).sum()
            w[dead] = 0.0
    return Book(name, gross, tov, expo)


def breakout_every(P: fc.Panel, cols: np.ndarray, allowed: np.ndarray, n: int, slots: int, regime: bool,
                   every: int = 1) -> np.ndarray:
    """fam_breakout.breakout_weights with the signal checked only every `every` days.

    On a check day the rule is the base rule; in between nothing is entered or
    exited (NaN rows: positions drift). every = 1 is the base, asserted equal."""
    px = P.px[:, cols]
    hi = fc.rolling_extreme(px, n, "max")
    lo = fc.rolling_extreme(px, n // 2, "min")
    with np.errstate(invalid="ignore"):
        enter = (px > hi) & allowed[:, cols]
        leave = (px < lo) | ~P.alive[:, cols]
    with np.errstate(invalid="ignore", divide="ignore"):
        size = np.minimum(fam_breakout.COIN_VOL / (P.sigma[:, cols] * np.sqrt(365)) / slots, 1.0 / slots)
    size = np.nan_to_num(size)
    W = np.full((P.T, P.N), np.nan)
    held = np.zeros(len(cols), dtype=bool)
    for t in range(P.T):
        row = np.full(len(cols), np.nan)
        if t % every == 0:
            if regime and not P.btc_on[t]:
                row[:] = 0.0
                held[:] = False
            else:
                ex = held & leave[t]
                en = ~held & enter[t] & (size[t] > 0)
                row[ex] = 0.0
                row[en] = size[t, en]
                held = (held & ~ex) | en
        W[t, cols] = row
    W[:, np.setdiff1d(np.arange(P.N), cols)] = 0.0
    return W


def blend(sleeves: list[Book], weighting: str, vol_target: float | None, name: str = "",
          start: int = START) -> Book:
    """Sleeves as sub-accounts of one book.

    Capital fractions b are re-set every REWEIGHT days (equal, or proportional to
    1 / RMS of each sleeve's daily return over VOL_WIN days); with a vol target
    the whole allocation is scaled by s = target / (annualised RMS of the
    unscaled blend over BOOK_VOL_WIN days), re-set every RESCALE days, s <= 3.
    The book's gross exposure is capped at 1 on every close. Between re-sets the
    allocations drift with the sleeves' returns. A change of allocation is
    charged as |change| x the sleeve's exposure; a sleeve's own trades as its
    turnover x its allocation. Everything is decided at the close of t from
    returns up to t and earns day t+1.
    """
    K = len(sleeves)
    G = np.array([s.gross for s in sleeves])
    TV = np.array([s.turnover for s in sleeves])
    EX = np.array([s.expo for s in sleeves])
    T = G.shape[1]
    ms = fc.rolling((G ** 2).T, VOL_WIN, int(VOL_WIN * 0.8)).T
    a = np.zeros(K)
    b = np.full(K, 1.0 / K)
    s = 1.0
    gross, tov, expo = np.zeros(T), np.zeros(T), np.zeros(T)
    for t in range(start, T - 1):
        tgt = a.copy()
        reset = False
        if (t - start) % REWEIGHT == 0:
            if weighting == "inverse vol":
                v = ms[:, t]
                with np.errstate(divide="ignore", invalid="ignore"):
                    inv = np.where(np.isfinite(v) & (v > 0), 1 / np.sqrt(v), 0.0)
                b = inv / inv.sum() if inv.sum() > 0 else np.full(K, 1.0 / K)
            else:
                b = np.full(K, 1.0 / K)
            reset = True
        if vol_target is not None and (t - start) % RESCALE == 0:
            lo = max(0, t - BOOK_VOL_WIN + 1)
            hist = (b[:, None] * G[:, lo:t + 1]).sum(0)
            vol = math.sqrt(float(np.mean(hist ** 2)) * 365) if t + 1 - lo >= BOOK_VOL_WIN * 0.8 else 0.0
            s = min(MAX_SCALE, vol_target / vol) if vol > 0 else 1.0
            reset = True
        if reset:
            tgt = b * s
        e = float((tgt * EX[:, t]).sum())
        if e > 1 + 1e-9:                # float drift of a fully invested book is not a breach
            tgt = tgt / e
        tov[t] += float((np.abs(tgt - a) * EX[:, t]).sum() + (tgt * TV[:, t]).sum())
        a = tgt
        expo[t] = float((a * EX[:, t]).sum())
        g = float((a * G[:, t + 1]).sum())
        gross[t + 1] = g
        a = a * (1 + G[:, t + 1]) / (1 + g) if 1 + g > 0 else np.zeros(K)
    return Book(name, gross, tov, expo)


# ---------------------------------------------------------------------------
# The legs
# ---------------------------------------------------------------------------

def leg_a(P: fc.Panel, every: int = 1) -> np.ndarray:
    top10 = P.top_liquid(10)
    cols = np.flatnonzero(top10.any(0))
    return breakout_every(P, cols, top10, 20, 10, regime=False, every=every)


def leg_c(P: fc.Panel) -> np.ndarray:
    majors = np.array([P.col("BTCUSDT"), P.col("ETHUSDT")])
    return breakout_every(P, majors, P.eligible, 55, 2, regime=True)


def leg_b(P: fc.Panel) -> np.ndarray:
    return fam_volmom.base_weights(P, 20, regime=True)


# ---------------------------------------------------------------------------
# Measuring
# ---------------------------------------------------------------------------

def years(P: fc.Panel) -> np.ndarray:
    return np.array([int(str(np.datetime64(int(d), "us").astype("datetime64[Y]"))) for d in P.days])


def describe(P: fc.Panel, b: Book) -> dict:
    ins, oos = fc.masks(P)
    row = {"variant": b.name}
    for k, c in COSTS.items():
        n = b.net(c)
        pi, po = fc.perf(n[ins]), fc.perf(n[oos])
        row[f"is_{k}"] = pi["sharpe"]
        row[f"oos_{k}"] = po["sharpe"]
        row[f"cagr_{k}"] = po["cagr"]
        row[f"dd_{k}"] = po["max_dd"]
    row["vol"] = fc.perf(b.net(COSTS["15bps"])[oos])["vol"]
    row["turnover_yr"] = float(b.turnover[oos].sum() / (oos.sum() / 365))
    row["cost_41_pct_yr"] = row["turnover_yr"] * COSTS["41bps"] * 100
    row["expo"] = float(b.expo[oos].mean())
    return row


def per_year(P: fc.Panel, b: Book, yr: np.ndarray) -> dict:
    """Sharpe at 41 bps per calendar year (2020 is 2020-08 on), and with each year dropped."""
    full = (P.days >= fc.IS_START)
    n41 = b.net(COSTS["41bps"])
    out = {"full_41": fc.perf(n41[full])["sharpe"]}
    for y in range(2020, 2027):
        m = full & (yr == y)
        out[f"y{y}"] = fc.perf(n41[m])["sharpe"]
        out[f"r{y}"] = float(np.prod(1 + n41[m]) - 1)
        out[f"drop{y}"] = fc.perf(n41[full & (yr != y)])["sharpe"]
    out["years_positive"] = int(sum(out[f"y{y}"] > 0 for y in YEARS))
    out["worst_drop"] = min(out[f"drop{y}"] for y in range(2020, 2027))
    out["carried"] = out["worst_drop"] <= 0.5 * out["full_41"]
    return out


def trial_row(x_oos: np.ndarray, label: str) -> dict:
    return bs.trial_row(x_oos, label)


def boot_idx(n: int, block: float, draws: int, rng: np.random.Generator) -> np.ndarray:
    """Politis-Romano stationary bootstrap indices, (draws, n)."""
    idx = np.empty((draws, n), dtype=np.int64)
    idx[:, 0] = rng.integers(0, n, draws)
    jump = rng.random((draws, n)) < 1 / block
    fresh = rng.integers(0, n, (draws, n))
    for i in range(1, n):
        idx[:, i] = np.where(jump[:, i], fresh[:, i], (idx[:, i - 1] + 1) % n)
    return idx


def _sr(s: np.ndarray) -> np.ndarray:
    sd = s.std(1)
    return np.where(sd > 0, s.mean(1) / np.where(sd > 0, sd, 1) * np.sqrt(365), 0.0)


def boot_sharpe(x: np.ndarray, idx: np.ndarray) -> dict:
    bs_ = _sr(x[idx])
    return {"sharpe": fc.perf(x)["sharpe"], "p05": float(np.percentile(bs_, 5)),
            "p95": float(np.percentile(bs_, 95)), "share_above_0": float(np.mean(bs_ > 0))}


def boot_diff(x: np.ndarray, y: np.ndarray, idx: np.ndarray) -> dict:
    """Sharpe(x) - Sharpe(y) on paired resamples."""
    d = _sr(x[idx]) - _sr(y[idx])
    return {"diff": fc.perf(x)["sharpe"] - fc.perf(y)["sharpe"], "p05": float(np.percentile(d, 5)),
            "p95": float(np.percentile(d, 95)), "share_above_0": float(np.mean(d > 0))}


# ---------------------------------------------------------------------------
# The trials already counted elsewhere
# ---------------------------------------------------------------------------

def sweep_rows() -> list[dict]:
    return bs.sweep_rows()


def breakout_study_rows() -> list[dict]:
    """The breakout study's 54 counted trials, rebuilt from its report (Sharpe at 15 bps out of sample)."""
    rep = json.loads((BREAKOUT / "reports" / "breakout_study.json").read_text(encoding="utf-8"))
    out = [{"variant": bs.label(r["entry"], r["exit"], r["top"]), "oos_sharpe_15bps": r["oos_15bps"]}
           for r in rep["grid"] if not r["in_sweep"]]
    ex = {e["case"]: e for e in rep["execution"]}
    for case in ("fill at next open", "fill at close + 1h", "fill at close + 4h", "fill at close + 12h",
                 "fill a day late (next close)", "close + breakout-day spread"):
        out.append({"variant": f"breakout study · {case}", "oos_sharpe_15bps": ex[case]["oos_15bps"]})
    out.append({"variant": "breakout study · 80 bps", "oos_sharpe_15bps": rep["base"]["oos_80bps"]})
    out.append({"variant": "breakout study · volume confirmed", "oos_sharpe_15bps": rep["volume_filter"]["oos_15bps"]})
    assert len(out) == rep["n_study"] == 54, len(out)
    return out


def grid_returns(P: fc.Panel) -> np.ndarray:
    """Out-of-sample net returns at 15 bps of the breakout study's 46 new grid cells (for the
    correlation-based trial count; its 8 other trials are near-copies of the base)."""
    _, oos = fc.masks(P)
    rows = []
    for ne in bs.ENTRIES:
        for dv in bs.EXIT_DIVS:
            for top in bs.TOPS:
                if top == 10 and dv == 2 and ne in fam_breakout.NS:
                    continue
                s = bs.simulate(P, bs.weights(P, ne, ne // dv, top))
                rows.append(bs.net(s, COSTS["15bps"])[oos])
    return np.array(rows)


def deflations(row: dict, pool: list[dict], n_eff: dict) -> dict:
    return {"full pool, sweep rule": bs.deflate_one(row, pool),
            "effective trials (mean correlation)": bs.deflate_one(row, pool, n_eff["avg_corr"]),
            "effective trials (eigenvalues)": bs.deflate_one(row, pool, n_eff["eigen"]),
            "one trial (probabilistic Sharpe vs 0)": bs.deflate_one(row, [row])}


def judge(row: dict, py: dict, defl: dict, bench_dd: float) -> tuple[bool, str]:
    why = []
    p = defl["full pool, sweep rule"]["p"]
    if p <= 0.95:
        why.append(f"deflated p {p:.2f} <= 0.95")
    if row["oos_41bps"] <= 0:
        why.append(f"Sharpe at 41 bps {row['oos_41bps']:.2f} <= 0")
    if row["dd_41bps"] >= bench_dd:
        why.append(f"drawdown {row['dd_41bps'] * 100:.0f} % not below the universe's {bench_dd * 100:.0f} %")
    if py["years_positive"] < 4:
        why.append(f"positive in {py['years_positive']} of 6 years")
    if py["carried"]:
        why.append(f"carried by one year (worst drop {py['worst_drop']:.2f} vs full {py['full_41']:.2f})")
    return (not why), ("passes" if not why else "fails: " + "; ".join(why))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    P = fc.load_panel()
    ins, oos = fc.masks(P)
    yr = years(P)
    rng = np.random.default_rng(20261011)
    res: dict = {"panel_end": str(np.datetime64(int(P.days[-1]), "us").astype("datetime64[D]")), "segments": P.N}
    trials: list[tuple[str, np.ndarray]] = []       # every new return series, counted

    # The legs, reproducing the sweep.
    WA, WB, WC = leg_a(P), leg_b(P), leg_c(P)
    top10 = P.top_liquid(10)
    cols10 = np.flatnonzero(top10.any(0))
    assert np.array_equal(np.isnan(WA), np.isnan(fam_breakout.breakout_weights(P, cols10, top10, 20, 10, False)))
    A = sim_long(P, WA, "A breakout_top10 (Donchian 20/10 · top 10)")
    B = sim_long(P, WB, "B tsmom_top20 (28d · top 20 · regime)")
    C = sim_long(P, WC, "C Donchian 55/27 · BTC+ETH · regime")
    for bk, W in ((A, WA), (B, WB), (C, WC)):
        g = fc.simulate(P, W, start=START)[0]
        assert np.allclose(bk.gross, g), f"{bk.name} does not reproduce fam_common.simulate"
    pool = sweep_rows()
    by_name = {r["variant"]: r for r in pool}
    for bk, v in ((A, "Donchian 20/10 · top 10 liquid"), (B, "tsmom 28d · top 20 · regime · none"),
                  (C, "Donchian 55/27 · BTC+ETH · regime")):
        assert abs(fc.perf(bk.net(COSTS["15bps"])[oos])["sharpe"] - by_name[v]["oos_sharpe_15bps"]) < 1e-9, v
    legs = [describe(P, x) for x in (A, B, C)]
    res["legs"] = legs
    n15 = {k: x.net(COSTS["15bps"])[oos] for k, x in (("A", A), ("B", B), ("C", C))}
    res["leg_corr"] = {f"{a}-{b}": float(np.corrcoef(n15[a], n15[b])[0, 1]) for a, b in (("A", "B"), ("A", "C"), ("B", "C"))}
    print("legs", json.dumps([{k: round(v, 3) if isinstance(v, float) else v for k, v in r.items()} for r in legs]),
          flush=True)

    # Part 1: the blend.
    blends: list[tuple[dict, Book, tuple]] = []
    for sname, sl in (("A + B", [A, B]), ("A + B + C", [A, B, C])):
        for wt in WEIGHTINGS:
            for vt in VOL_TARGETS:
                nm = f"{sname} · {wt} · " + ("no vol target" if vt is None else f"vol target {vt * 100:.0f} %")
                bk = blend(sl, wt, vt, nm)
                blends.append((describe(P, bk), bk, (sname, wt, vt)))
                trials.append((nm, bk.net(COSTS["15bps"])[oos]))
    res["blends"] = [r for r, _, _ in blends]
    bpick_row, bpick, bpick_cfg = max(blends, key=lambda x: x[0]["is_15bps"])
    res["blend_pick"] = bpick_row["variant"]
    idx = boot_idx(int(oos.sum()), BOOT_BLOCK, BOOT_DRAWS, rng)
    vs = []
    for leg in (A, B, C):
        for k in ("15bps", "41bps"):
            vs.append({"leg": leg.name, "cost": k,
                       **boot_diff(bpick.net(COSTS[k])[oos], leg.net(COSTS[k])[oos], idx)})
    res["blend_vs_legs"] = vs
    res["blends_beating_both_41"] = int(sum(r["oos_41bps"] > max(legs[0]["oos_41bps"], legs[1]["oos_41bps"])
                                            for r, _, _ in blends))
    print("blend pick", bpick_row["variant"], round(bpick_row["oos_41bps"], 3), flush=True)

    # Part 2: turnover.
    b_cfg = []
    for rname, k in B_REBALANCE.items():
        for bname, band in BANDS.items():
            nm = f"B · {rname} · band {bname}"
            bk = B if (k == 1 and band == 0) else sim_long(P, WB, nm, fc.every(P, k) if k > 1 else None, band)
            bk.name = nm if bk is not B else B.name
            row = {**describe(P, bk), "rebalance": rname, "band": bname, "base": bk is B}
            b_cfg.append((row, bk))
            if bk is not B:
                trials.append((nm, bk.net(COSTS["15bps"])[oos]))
    a_cfg = []
    for ename, k in A_EVERY.items():
        if k == 1:
            a_cfg.append(({**describe(P, A), "check": ename, "base": True}, A))
            continue
        nm = f"A · signal {ename}"
        bk = sim_long(P, leg_a(P, k), nm)
        a_cfg.append(({**describe(P, bk), "check": ename, "base": False}, bk))
        trials.append((nm, bk.net(COSTS["15bps"])[oos]))
    res["b_turnover"] = [r for r, _ in b_cfg]
    res["a_turnover"] = [r for r, _ in a_cfg]
    b_pick_row, b_pick = max(b_cfg, key=lambda x: x[0]["is_41bps"])
    a_pick_row, a_pick = max(a_cfg, key=lambda x: x[0]["is_41bps"])
    res["b_pick"], res["a_pick"] = b_pick_row["variant"], a_pick_row["variant"]
    res["b_recommend"] = (not b_pick_row["base"]) and b_pick_row["oos_41bps"] > legs[1]["oos_41bps"]
    res["a_recommend"] = (not a_pick_row["base"]) and a_pick_row["oos_41bps"] > legs[0]["oos_41bps"]
    print("turnover picks", res["a_pick"], "|", res["b_pick"], flush=True)

    # Part 3: the blend pick from the part 2 picks.
    p3 = None
    if b_pick is not B or a_pick is not A:
        sname, wt, vt = bpick_cfg
        sl = [a_pick, b_pick] + ([C] if sname == "A + B + C" else [])
        nm = f"{bpick_row['variant']} · legs {a_pick_row['check']} / {b_pick_row['rebalance']} band {b_pick_row['band']}"
        bk = blend(sl, wt, vt, nm)
        p3 = (describe(P, bk), bk)
        trials.append((nm, bk.net(COSTS["15bps"])[oos]))
        res["part3"] = p3[0]

    # Robustness, added after the pre-registration and counted: does a weekly pick depend on the
    # day of the week it trades? The same rule with the rebalance day shifted by 1 to 6 days.
    tranches = None
    if b_pick_row["rebalance"] == "weekly":
        band = BANDS[b_pick_row["band"]]
        ph, books = [], []
        for off in range(7):
            day = datetime.fromtimestamp(P.days[off] / 1e6, timezone.utc).strftime("%A")
            if off == 0:
                bk = b_pick
            else:
                mask = ((np.arange(P.T) - off) % 7) == 0
                bk = sim_long(P, WB, f"B · weekly on {day} · band {b_pick_row['band']}", mask, band)
                trials.append((bk.name, bk.net(COSTS["15bps"])[oos]))
            ph.append({**describe(P, bk), "weekday": day})
            books.append(bk)
        # The phase-free version: seven tranches, one rebalanced on each weekday, 1/7 of the capital each.
        nm = f"B · seven weekly tranches · band {b_pick_row['band']}"
        tr7 = blend(books, "equal capital", None, nm)
        trials.append((nm, tr7.net(COSTS["15bps"])[oos]))
        ph.append({**describe(P, tr7), "weekday": "all seven, 1/7 each"})
        res["b_phase"] = ph
        res["b_phase_median_41"] = float(np.median([r["oos_41bps"] for r in ph[:7]]))
        tranches = (ph[-1], tr7)
        res["b_pick_vs_base"] = [{"cost": k, **boot_diff(b_pick.net(COSTS[k])[oos], B.net(COSTS[k])[oos], idx)}
                                 for k in COSTS]

    # Deflation over the full pool.
    bo_rows = breakout_study_rows()
    mine = [trial_row(x, nm) for nm, x in trials]
    full_pool = pool + bo_rows + mine
    R = np.vstack([bs.sweep_returns(P), grid_returns(P)] + [x[None] for _, x in trials])
    with np.errstate(invalid="ignore", divide="ignore"):
        n_eff = bs.effective_trials(R)    # a few trials are flat out of sample: correlation 0
    res["n_trials"] = {"sweep": len(pool), "breakout_study": len(bo_rows), "this_study": len(trials),
                       "total": len(full_pool)}
    res["n_eff"] = n_eff
    bench = fc.benchmarks(P)
    bench_dd = fc.perf(bench["ew"][oos])["max_dd"]
    res["bench"] = {"btc": describe(P, Book("BTC buy and hold", bench["btc"], np.zeros(P.T), np.ones(P.T))),
                    "ew": describe(P, Book("equal-weight universe", bench["ew"], np.zeros(P.T), np.ones(P.T)))}
    judged = []
    cands = [("blend pick", bpick_row, bpick), ("A turnover pick", a_pick_row, a_pick),
             ("B turnover pick", b_pick_row, b_pick)]
    if p3 is not None:
        cands.append(("part 3", p3[0], p3[1]))
    if tranches is not None:
        cands.append(("B weekly, phase-free (check)", tranches[0], tranches[1]))
    cands += [("leg A (reference)", legs[0], A), ("leg B (reference)", legs[1], B), ("leg C (reference)", legs[2], C)]
    for role, row, bk in cands:
        tr = trial_row(bk.net(COSTS["15bps"])[oos], row["variant"])
        defl = deflations(tr, full_pool, n_eff)
        py = per_year(P, bk, yr)
        ok, why = judge(row, py, defl, bench_dd)
        x41 = bk.net(COSTS["41bps"])[oos]
        judged.append({"role": role, "variant": row["variant"], "row": row, "per_year": py, "deflation": defl,
                       "skew": tr["oos_skew"], "kurt": tr["oos_kurt"],
                       "boot_41": boot_sharpe(x41, idx), "passes": ok, "verdict": why})
    res["judged"] = judged
    res["trials"] = [nm for nm, _ in trials]
    print(json.dumps([{k: j[k] for k in ("role", "variant", "verdict")} for j in judged], indent=1), flush=True)
    write(P, res)


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def _p(v: float) -> str:
    return f"{v * 100:.0f} %"


def write(P: fc.Panel, res: dict) -> None:
    t = fc.table
    path = fc.RESULTS_DIR / f"{NAME}.md"
    head = path.read_text(encoding="utf-8").split(MARKER)[0].rstrip() + "\n\n"
    cols = ["variant", "is_15bps", "oos_15bps", "oos_41bps", "oos_80bps", "cagr_41bps", "dd_41bps", "vol",
            "turnover_yr", "cost_41_pct_yr", "expo"]
    n = res["n_trials"]
    md = [MARKER, "\n\n## Results (generated)\n\n",
          f"Panel: {res['segments']} coin segments, ending {res['panel_end']}. In sample 2020-08 to 2023, out of "
          f"sample from 2024-01-01 ({int(fc.masks(P)[1].sum())} days). Sharpe annualised, "
          "net of the cost named; cagr, dd (max drawdown) and the cost drag at 41 bps (cost_41_pct_yr, % of "
          "equity a year) out of sample.\n\n",
          "### Legs (reproduce the sweep)\n\n", t(res["legs"], cols),
          "\nCorrelation of the legs' out-of-sample daily returns at 15 bps: "
          + ", ".join(f"{k} {v:.2f}" for k, v in res["leg_corr"].items()) + ".\n\n",
          "### Part 1: blends\n\n", t(sorted(res["blends"], key=lambda r: -r["is_15bps"]), cols),
          f"\nIn-sample pick: **{res['blend_pick']}**. Blends with a higher out-of-sample Sharpe at 41 bps than "
          f"both A and B: {res['blends_beating_both_41']} of {len(res['blends'])}.\n\n",
          "Pick against each leg, paired stationary bootstrap of the out-of-sample Sharpe difference (pick minus "
          f"leg, mean block {BOOT_BLOCK} days, {BOOT_DRAWS:,} draws):\n\n",
          t(res["blend_vs_legs"], ["leg", "cost", "diff", "p05", "p95", "share_above_0"]),
          "\n### Part 2: turnover\n\nB, tsmom_top20:\n\n",
          t(res["b_turnover"], ["rebalance", "band"] + cols[1:]),
          f"\nIn-sample pick at 41 bps: **{res['b_pick']}**; recommended over the base: "
          f"{'yes' if res['b_recommend'] else 'no'}.\n\nA, breakout_top10:\n\n",
          t(res["a_turnover"], ["check"] + cols[1:]),
          f"\nIn-sample pick at 41 bps: **{res['a_pick']}**; recommended over the base: "
          f"{'yes' if res['a_recommend'] else 'no'}.\n\n"]
    if "part3" in res:
        md += ["### Part 3: blend of the turnover picks\n\n", t([res["part3"]], cols), "\n"]
    if "b_phase" in res:
        md += ["### Robustness of the weekly pick (added after the pre-registration, counted)\n\n"
               "The same rule with the weekly rebalance on each day of the week (the study's weekly grid "
               "trades on the panel's first weekday):\n\n",
               t(res["b_phase"], ["weekday"] + cols[1:]),
               f"\nMedian of the seven weekdays at 41 bps: {res['b_phase_median_41']:.2f}.\n"
               "\nWeekly pick against the daily base, paired bootstrap of the out-of-sample Sharpe difference:\n\n",
               t(res["b_pick_vs_base"], ["cost", "diff", "p05", "p95", "share_above_0"]), "\n"]
    md += ["### Judged against the pass rule\n\n",
           f"Pool: {n['sweep']} sweep + {n['breakout_study']} breakout study + {n['this_study']} this study = "
           f"**{n['total']} trials**. Effective trials from the correlation of their out-of-sample returns "
           f"(sweep, the breakout grid and this study): {res['n_eff']['avg_corr']:.0f} by mean correlation, "
           f"{res['n_eff']['eigen']:.1f} by eigenvalues.\n\n"]
    rows = []
    for j in res["judged"]:
        d = j["deflation"]
        rows.append({"role": j["role"], "variant": j["variant"], "oos_15bps": j["row"]["oos_15bps"],
                     "oos_41bps": j["row"]["oos_41bps"], "dd_41bps": j["row"]["dd_41bps"],
                     "sr0": d["full pool, sweep rule"]["sr0_annual"], "p_pool": d["full pool, sweep rule"]["p"],
                     "p_eff_corr": d["effective trials (mean correlation)"]["p"],
                     "p_eff_eigen": d["effective trials (eigenvalues)"]["p"],
                     "p_one_trial": d["one trial (probabilistic Sharpe vs 0)"]["p"],
                     "boot41_p05": j["boot_41"]["p05"], "boot41_p95": j["boot_41"]["p95"],
                     "years_pos": j["per_year"]["years_positive"], "verdict": j["verdict"]})
    md += [t(rows, list(rows[0])), "\nSharpe at 41 bps per calendar year (2020 is 2020-08 on; 2021 to 2023 "
           "in sample), and the full-period Sharpe with that year dropped:\n\n"]
    yrows = []
    for j in res["judged"]:
        py = j["per_year"]
        yrows.append({"variant": j["variant"], "full": py["full_41"],
                      **{str(y): py[f"y{y}"] for y in range(2020, 2027)},
                      **{f"w/o {y}": py[f"drop{y}"] for y in range(2020, 2027)}})
    md += [t(yrows, list(yrows[0])), "\nReturn at 41 bps per calendar year:\n\n"]
    rrows = [{"variant": j["variant"], **{str(y): _p(j["per_year"][f"r{y}"]) for y in range(2020, 2027)}}
             for j in res["judged"]]
    md += [t(rrows, list(rrows[0])),
           f"\nBenchmarks out of sample (no costs): BTC Sharpe {res['bench']['btc']['oos_15bps']:.2f}, drawdown "
           f"{_p(res['bench']['btc']['dd_15bps'])}; equal-weight universe Sharpe {res['bench']['ew']['oos_15bps']:.2f}, "
           f"drawdown {_p(res['bench']['ew']['dd_15bps'])}.\n\n"
           f"Trials of this study ({n['this_study']}): " + "; ".join(res["trials"]) + ".\n"]
    path.write_text(head + "".join(md), encoding="utf-8")
    d = fc.OUT / "reports"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{NAME}.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
