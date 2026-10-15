"""C16: what the daily books earn on the 15 coins Alpaca lists.

    python -m lab.experiments.alpaca_universe

Pre-registered in results/alpaca_universe.md (the part above the marker was
committed before this file ran). Three groups of books on the sweep's
survivorship-free daily panel, all long-only, all through the paper books' own
weight functions:

  C  cash-left: breakout_top10, tsmom_top20 and tsmom_tranches exactly as
     defined, with every coin Alpaca does not list held as cash (what the
     autopilot does today)
  R  restricted: the same rules choosing only among the Alpaca coins, the top
     K by 28-day volume each day, K in 5, 8, 10, 15; breakout over the sweep's
     Donchian grid N 20, 55, 100 (exit N/2)
  T  the survivorship-free twin of every R: the Alpaca list is today's, so the
     twin replaces it with the 15 most liquid eligible coins at the first close
     of each year, frozen for that year

plus the per-book pick (best in-sample R at 35 bps) filled one day late (L),
and the originals and BTC buy and hold as references. Judged out of sample from
2024 at 35 bps (Alpaca taker plus slippage), deflated over every trial counted
so far. Writes results/alpaca_universe.md and
<agent-strategies>/reports/alpaca_universe.json.
"""

from __future__ import annotations

import itertools
import json
import math
from datetime import datetime, timezone

import numpy as np
from scipy import stats

from ..metrics import deflated_sharpe
from . import fam_breakout, fam_common as fc, fam_volmom
from . import tsmom_tranches as tt

NAME = "alpaca_universe"
MARKER = "<!-- generated below by lab.experiments.alpaca_universe; edit above this line only -->"
ALPACA = tt.ALPACA
COSTS = {"maker 15bps": 0.0015, "taker 35bps": 0.0035, "stress 70bps": 0.0070}
BASE = "taker 35bps"
START = 60
KS = (5, 8, 10, 15)
NS = (20, 55, 100)
LIST_SIZE = 15
YEARS = (2021, 2022, 2023, 2024, 2025, 2026)
YEARS_OOS = (2024, 2025, 2026)
ORDER_MIN = 0.001
# The prior pool and its published bar (results/regime_hmm.md).
PRIOR_TRIALS, PRIOR_SR0 = 331, 2.55
HERE_TRIALS = 46
BOOKS = ("breakout", "tsmom_daily", "tsmom_tranches")
ORIGINAL = {"breakout": "breakout_top10", "tsmom_daily": "tsmom_top20", "tsmom_tranches": "tsmom_tranches"}


# ---------------------------------------------------------------------------
# Universes
# ---------------------------------------------------------------------------

def alpaca_mask(P: fc.Panel) -> np.ndarray:
    """(N,) the columns Alpaca can trade: one of the 15 bases, the current segment of its ticker."""
    return np.array([b in ALPACA and "~" not in n for b, n in zip(P.bases, P.names)])


def top_within(P: fc.Panel, member: np.ndarray, k: int) -> np.ndarray:
    """Bool (T, N): the k eligible members with the highest 28-day volume each day.
    `member` is (N,) or (T, N)."""
    ok = P.eligible & member
    score = np.where(ok, P.adv28, -np.inf)
    rank = np.argsort(np.argsort(-score, axis=1, kind="stable"), axis=1, kind="stable")
    return ok & (rank < k)


def annual_lists(P: fc.Panel, size: int = LIST_SIZE) -> tuple[np.ndarray, dict[int, list[str]]]:
    """The twin's point-in-time list: at the first close of each calendar year (for the
    first year, the first close with any eligible coin) the `size` eligible coins with
    the highest 28-day volume, frozen until the next year. A coin that dies leaves it."""
    yr = years_of(P)
    member = np.zeros((P.T, P.N), dtype=bool)
    lists: dict[int, list[str]] = {}
    for y in np.unique(yr):
        rows = np.flatnonzero(yr == y)
        pick_row = next((t for t in rows if P.eligible[t].any()), None)
        if pick_row is None:
            continue
        score = np.where(P.eligible[pick_row], P.adv28[pick_row], -np.inf)
        cols = np.argsort(-score, kind="stable")[:size]
        cols = cols[np.isfinite(score[cols])]
        lists[int(y)] = [P.names[j] for j in cols]
        sel = np.zeros(P.N, dtype=bool)
        sel[cols] = True
        r = rows[rows >= pick_row]
        member[r] = sel[None, :]
    return member, lists


def years_of(P: fc.Panel) -> np.ndarray:
    return np.array([int(str(np.datetime64(int(d), "us").astype("datetime64[Y]"))) for d in P.days])


# ---------------------------------------------------------------------------
# Weights
# ---------------------------------------------------------------------------

def tsmom_weights(P: fc.Panel, uni: np.ndarray, regime: bool = True,
                  lookback: int = fam_volmom.LOOKBACK) -> np.ndarray:
    """fam_volmom.base_weights on a given universe: 28-day return above 0, 40 % vol per
    coin over the day's universe count, BTC 200-day regime."""
    past = np.full_like(P.px, np.nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        past[lookback:] = P.px[lookback:] / P.px[:-lookback] - 1
    held = uni & np.isfinite(past) & (past > 0)
    W = fc.vol_sized(P, held, fam_volmom.COIN_VOL, uni.sum(1))
    if regime:
        W = W * P.btc_on[:, None]
    return W


def breakout_on(P: fc.Panel, allowed: np.ndarray, n: int, slots: int) -> np.ndarray:
    """fam_breakout.breakout_weights over every column that is ever allowed, no regime."""
    cols = np.flatnonzero(allowed.any(0))
    return fam_breakout.breakout_weights(P, cols, allowed, n, slots, regime=False)


def originals(P: fc.Panel) -> dict[str, np.ndarray]:
    """The three paper books' target matrices, exactly as lab/paper/families.py builds them."""
    top10 = P.top_liquid(10)
    cols = np.flatnonzero(top10.any(0))
    W_t = fam_volmom.base_weights(P, 20, regime=True)
    return {"breakout": fam_breakout.breakout_weights(P, cols, top10, 20, 10, regime=False),
            "tsmom_daily": W_t, "tsmom_tranches": W_t}


def cash_left(W: np.ndarray, alp: np.ndarray) -> np.ndarray:
    """Targets with every non-Alpaca column at 0 and the rest as they are (NaN stays NaN)."""
    return np.where(alp[None, :], W, 0.0)


def one_day_late(W: np.ndarray) -> np.ndarray:
    """What is decided at the close of day t is executed at the close of day t+1."""
    out = np.full_like(W, np.nan)
    out[1:] = W[:-1]
    out[0] = 0.0
    return out


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------

def sim_daily(P: fc.Panel, W: np.ndarray, start: int = START):
    """fc.simulate for a long-only book, also returning the weights held after every close.

    Returns (gross, turnover, expo, held): held[t] is the book after the trades at
    the close of day t, before drift (a coin whose series ended at t is already 0)."""
    T, N = W.shape
    w = np.zeros(N)
    gross, tov, ex = np.zeros(T), np.zeros(T), np.zeros(T)
    held = np.zeros((T, N))
    for t in range(start, T):
        tgt = np.where(np.isnan(W[t]), w, W[t])
        tgt = np.where(P.traded[t] | (tgt == w), tgt, w)
        tov[t] += np.abs(tgt - w).sum()
        w = tgt
        held[t] = w
        ex[t] = w[w > 0].sum()
        if t == T - 1:
            break
        r = np.nan_to_num(P.ret[t + 1])
        g = float(np.dot(w, r))
        gross[t + 1] = g
        w = w * (1 + r) / (1 + g) if 1 + g > 0 else np.zeros(N)
        dead = (w != 0) & ~P.alive[t + 1]
        if dead.any():
            tov[t + 1] += np.abs(w[dead]).sum()
            w[dead] = 0.0
    return gross, tov, ex, held


def sim_tranches(P: fc.Panel, W: np.ndarray):
    g, tv, ex, _, _, held = tt.simulate(P, W, record=True)
    return g, tv, ex, held


def simulate(P: fc.Panel, book: str, W: np.ndarray):
    return sim_tranches(P, W) if book == "tsmom_tranches" else sim_daily(P, W)


def drifted(P: fc.Panel, held: np.ndarray) -> np.ndarray:
    """The book going into each close, before its trades: yesterday's holdings after a
    day of prices, a dead coin at 0."""
    pre = np.zeros_like(held)
    r = np.nan_to_num(P.ret[1:])
    g = (held[:-1] * r).sum(1, keepdims=True)
    with np.errstate(invalid="ignore", divide="ignore"):
        pre[1:] = np.where(1 + g > 0, held[:-1] * (1 + r) / (1 + g), 0.0)
    pre[1:] = np.where(P.alive[1:], pre[1:], 0.0)
    return pre


def activity(P: fc.Panel, held: np.ndarray, mask: np.ndarray) -> dict:
    """Trades per month (a coin's weight going from 0 to above 0 or back) and orders per
    month (any coin-level change above ORDER_MIN of the book), over the masked days."""
    on = held > 1e-12
    flips = np.zeros_like(on)
    flips[1:] = on[1:] != on[:-1]
    pre = drifted(P, held)
    orders = np.abs(held - pre) > ORDER_MIN
    months = mask.sum() / (365 / 12)
    return {"trades_month": float(flips[mask].sum() / months), "orders_month": float(orders[mask].sum() / months),
            "coins_held": float(on[mask].sum(1).mean())}


# ---------------------------------------------------------------------------
# Measuring
# ---------------------------------------------------------------------------

def net(gross: np.ndarray, tov: np.ndarray, cost: float) -> np.ndarray:
    return gross - cost * np.r_[0.0, tov[:-1]]


def sharpe_d(x: np.ndarray) -> float:
    sd = x.std()
    return float(x.mean() / sd) if sd > 0 else 0.0


def prior_var() -> float:
    """Variance of daily trial Sharpes implied by the published bar over the prior pool."""
    g = 0.5772156649
    z = (1 - g) * stats.norm.ppf(1 - 1 / PRIOR_TRIALS) + g * stats.norm.ppf(1 - 1 / (PRIOR_TRIALS * math.e))
    return (PRIOR_SR0 / math.sqrt(365) / z) ** 2


def pooled_var(mine: list[float]) -> tuple[float, dict]:
    """The prior pool's variance pooled with this study's trial Sharpes (annual, clipped at +-3)."""
    v1, n1 = prior_var(), PRIOR_TRIALS
    x = np.clip(np.array(mine), -fc.SR_CLIP, fc.SR_CLIP) / math.sqrt(365)
    n2, v2 = len(x), float(np.var(x))
    n = n1 + n2
    v = (n1 * v1 + n2 * v2) / n
    return v, {"prior_trials": n1, "prior_var": v1, "mine": n2, "mine_var": v2, "pooled_var": v, "n_total": n,
               "sr0_annual": fc._sr0(v, n) * math.sqrt(365)}


def deflated(x: np.ndarray, n: int, var: float) -> float:
    if x.std() == 0:
        return 0.0
    return deflated_sharpe(sharpe_d(x), len(x), n, var, float(stats.skew(x)), float(stats.kurtosis(x, fisher=False)))


def boot_band(x: np.ndarray, rng: np.random.Generator, y: np.ndarray | None = None) -> tuple[float, float]:
    """5 % and 95 % of the annual Sharpe over stationary-bootstrap resamples (block 20).
    With y, of Sharpe(x) - Sharpe(y) on the same resampled days."""
    n = len(x)
    draws, block = tt.BOOT_DRAWS, tt.BOOT_BLOCK
    idx = np.empty((draws, n), dtype=np.int64)
    idx[:, 0] = rng.integers(0, n, draws)
    jump = rng.random((draws, n)) < 1 / block
    fresh = rng.integers(0, n, (draws, n))
    for i in range(1, n):
        idx[:, i] = np.where(jump[:, i], fresh[:, i], (idx[:, i - 1] + 1) % n)

    def sr(a: np.ndarray) -> np.ndarray:
        s = a[idx]
        sd = s.std(1)
        return np.where(sd > 0, s.mean(1) / np.where(sd > 0, sd, 1) * np.sqrt(365), 0.0)

    v = sr(x) if y is None else sr(x) - sr(y)
    return float(np.percentile(v, 5)), float(np.percentile(v, 95))


def describe(P: fc.Panel, group: str, book: str, name: str, run: tuple, alp: np.ndarray) -> dict:
    gross, tov, ex, held = run
    ins, oos = fc.masks(P)
    yr = years_of(P)
    row: dict = {"group": group, "book": book, "variant": name}
    for k, c in COSTS.items():
        n = net(gross, tov, c)
        row[f"is_{k}"] = fc.perf(n[ins])["sharpe"]
        row[f"oos_{k}"] = fc.perf(n[oos])["sharpe"]
    n35 = net(gross, tov, COSTS[BASE])
    po = fc.perf(n35[oos])
    row["cagr_35"], row["dd_35"] = po["cagr"], po["max_dd"]
    row["expo"] = float(ex[oos].mean())
    row["turnover_yr"] = float(tov[oos].sum() / (oos.sum() / 365))
    row.update(activity(P, held, oos))
    tot = held[oos].sum(1)
    row["non_alpaca_share"] = float(np.nanmean(np.where(tot > 0, held[oos][:, ~alp].sum(1) / np.where(tot > 0, tot, 1),
                                                        np.nan))) if (tot > 0).any() else 0.0
    for y in YEARS:
        m = (P.days >= fc.IS_START) & (yr == y)
        row[f"y{y}"] = fc.perf(n35[m])["sharpe"]
    return row


def benchmark_rows(P: fc.Panel, alp: np.ndarray) -> tuple[list[dict], np.ndarray]:
    ins, oos = fc.masks(P)
    yr = years_of(P)
    btc = np.nan_to_num(P.ret[:, P.btc])
    ew = np.zeros(P.T)
    for t in range(1, P.T):
        m = P.eligible[t - 1] & alp & np.isfinite(P.ret[t])
        ew[t] = float(P.ret[t][m].mean()) if m.any() else 0.0
    out = []
    for name, r in (("BTC buy and hold", btc), ("Alpaca coins, equal weight, buy and hold", ew)):
        po = fc.perf(r[oos])
        row = {"group": "benchmark", "book": "-", "variant": name, "is_taker 35bps": fc.perf(r[ins])["sharpe"],
               "oos_maker 15bps": po["sharpe"], "oos_taker 35bps": po["sharpe"], "oos_stress 70bps": po["sharpe"],
               "cagr_35": po["cagr"], "dd_35": po["max_dd"], "expo": 1.0}
        for y in YEARS:
            m = (P.days >= fc.IS_START) & (yr == y)
            row[f"y{y}"] = fc.perf(r[m])["sharpe"]
        out.append(row)
    return out, btc


def availability(P: fc.Panel, alp: np.ndarray) -> dict:
    """When each Alpaca coin became eligible, and how many were eligible over time."""
    _, oos = fc.masks(P)
    first = {}
    for j in np.flatnonzero(alp):
        e = np.flatnonzero(P.eligible[:, j])
        first[P.bases[j]] = str(np.datetime64(int(P.days[e[0]]), "us").astype("datetime64[D]")) if len(e) else None
    count = (P.eligible & alp).sum(1)

    def at(day: str) -> int:
        t = int(np.searchsorted(P.days, int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp() * 1e6)))
        return int(count[min(t, P.T - 1)])

    return {"first_eligible": first, "listed": int(alp.sum()), "eligible_2020_08_01": at("2020-08-01"),
            "eligible_2024_01_01": at("2024-01-01"), "eligible_oos_min": int(count[oos].min()),
            "eligible_oos_max": int(count[oos].max()), "all_through_oos": bool(count[oos].min() == alp.sum())}


def exposure_by_coin(P: fc.Panel, held: np.ndarray, alp: np.ndarray, top: int = 12) -> list[dict]:
    """The coins that carry an original book's out-of-sample exposure, largest first."""
    _, oos = fc.masks(P)
    h = held[oos]
    total = h.sum()
    share = h.sum(0) / total if total > 0 else np.zeros(P.N)
    order = np.argsort(-share)[:top]
    return [{"coin": P.names[j][:-4] if "~" not in P.names[j] else P.names[j], "share": float(share[j]),
             "alpaca": bool(alp[j])} for j in order if share[j] > 0]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def restricted_variants(P: fc.Panel, member: np.ndarray) -> list[tuple[str, str, np.ndarray]]:
    """(book, name, W) for the restricted grid on a given membership (Alpaca list or twin)."""
    out = []
    for k, n in itertools.product(KS, NS):
        out.append(("breakout", f"Donchian {n}/{n // 2} · top {k}", breakout_on(P, top_within(P, member, k), n, k)))
    for k in KS:
        W = tsmom_weights(P, top_within(P, member, k))
        out.append(("tsmom_daily", f"tsmom 28d · top {k} · regime · daily", W))
        out.append(("tsmom_tranches", f"tsmom 28d · top {k} · regime · seven weekly tranches", W))
    return out


def main() -> None:
    P = fc.load_panel()
    ins, oos = fc.masks(P)
    alp = alpaca_mask(P)
    rng = np.random.default_rng(20261014)
    rows, series = [], {}

    def add(group: str, book: str, name: str, W: np.ndarray) -> dict:
        run = simulate(P, book, W)
        r = describe(P, group, book, name, run, alp)
        rows.append(r)
        series[(group, book, name)] = (run, W)
        print(f"  {group} {book:15s} {name:60s} IS {r['is_taker 35bps']:5.2f} OOS {r['oos_taker 35bps']:5.2f}",
              flush=True)
        return r

    O = originals(P)
    for b in BOOKS:
        add("O", b, ORIGINAL[b], O[b])
    for b in BOOKS:
        add("C", b, ORIGINAL[b] + " · non-Alpaca coins in cash", cash_left(O[b], alp))
    for b, name, W in restricted_variants(P, alp):
        add("R", b, name + " · Alpaca coins", W)
    member, lists = annual_lists(P)
    for b, name, W in restricted_variants(P, member):
        add("T", b, name + " · twin (yearly top 15 list)", W)

    picks = {}
    for b in BOOKS:
        cand = [r for r in rows if r["group"] == "R" and r["book"] == b]
        pk = max(cand, key=lambda r: r["is_taker 35bps"])
        twin_name = pk["variant"].replace(" · Alpaca coins", " · twin (yearly top 15 list)")
        twin = next(r for r in rows if r["group"] == "T" and r["book"] == b and r["variant"] == twin_name)
        W = series[("R", b, pk["variant"])][1]
        late = add("L", b, pk["variant"] + " · one day late", one_day_late(W))
        picks[b] = {"pick": pk, "twin": twin, "late": late}

    # Deflation over everything counted: C, R, T and L here, the prior pool before.
    counted = [r for r in rows if r["group"] in ("C", "R", "T", "L")]
    assert len(counted) == HERE_TRIALS, len(counted)
    var, pool = pooled_var([r["oos_taker 35bps"] for r in counted])
    n_total = pool["n_total"]
    for r in rows:
        (g, tv, _, _), _ = series[(r["group"], r["book"], r["variant"])]
        x = net(g, tv, COSTS[BASE])[oos]
        r["deflated_p"] = deflated(x, n_total, var)
        r["boot35_p05"], r["boot35_p95"] = boot_band(x, rng)

    bench, btc = benchmark_rows(P, alp)
    btc_dd = fc.perf(btc[oos])["max_dd"]
    yr = years_of(P)
    verdicts = []
    for b in BOOKS:
        pk, tw, lt = picks[b]["pick"], picks[b]["twin"], picks[b]["late"]
        c = next(r for r in rows if r["group"] == "C" and r["book"] == b)
        (gp, tp, _, _), _ = series[("R", b, pk["variant"])]
        (gc, tc, _, _), _ = series[("C", b, c["variant"])]
        xp, xc = net(gp, tp, COSTS[BASE]), net(gc, tc, COSTS[BASE])
        diff = xp - xc
        dlo, dhi = boot_band(xp[oos], rng, xc[oos])
        years_better = sum(pk[f"y{y}"] > c[f"y{y}"] for y in YEARS_OOS)
        lab_bar = (pk["oos_taker 35bps"] > 0 and pk["oos_stress 70bps"] > 0 and pk["dd_35"] < btc_dd
                   and pk["deflated_p"] > 0.95)
        beats = pk["oos_taker 35bps"] > c["oos_taker 35bps"] and years_better >= 2
        checks = tw["oos_taker 35bps"] > 0 and lt["oos_taker 35bps"] > 0
        why = []
        if pk["oos_taker 35bps"] <= 0 or pk["oos_stress 70bps"] <= 0:
            why.append("Sharpe not above 0 at 35 and 70 bps")
        if pk["dd_35"] >= btc_dd:
            why.append(f"drawdown {pk['dd_35'] * 100:.0f} % not below BTC's {btc_dd * 100:.0f} %")
        if pk["deflated_p"] <= 0.95:
            why.append(f"deflated p {pk['deflated_p']:.2f} <= 0.95")
        if not beats:
            why.append(f"does not beat cash-left ({pk['oos_taker 35bps']:.2f} vs {c['oos_taker 35bps']:.2f}, "
                       f"better in {years_better} of 3 years)")
        if not checks:
            why.append(f"twin {tw['oos_taker 35bps']:.2f} / late {lt['oos_taker 35bps']:.2f}")
        verdicts.append({
            "book": b, "original": ORIGINAL[b], "pick": pk["variant"], "pick_is_35": pk["is_taker 35bps"],
            "pick_oos_35": pk["oos_taker 35bps"], "pick_oos_70": pk["oos_stress 70bps"], "pick_dd": pk["dd_35"],
            "pick_deflated_p": pk["deflated_p"], "cash_oos_35": c["oos_taker 35bps"], "cash_dd": c["dd_35"],
            "twin_oos_35": tw["oos_taker 35bps"], "late_oos_35": lt["oos_taker 35bps"],
            "diff_sharpe": sharpe_d(diff[oos]) * math.sqrt(365), "sr_diff_p05": dlo, "sr_diff_p95": dhi,
            "years_better": years_better,
            **{f"diff_{y}": float(diff[oos & (yr == y)].sum()) for y in YEARS_OOS},
            "lab_bar": lab_bar, "beats_cash": beats, "checks": checks, "passes": lab_bar and beats and checks,
            "why": "; ".join(why) if why else "passes"})

    res = {"panel_end": str(np.datetime64(int(P.days[-1]), "us").astype("datetime64[D]")), "segments": P.N,
           "oos_days": int(oos.sum()), "rows": rows, "benchmarks": bench, "verdicts": verdicts, "pool": pool,
           "availability": availability(P, alp), "twin_lists": lists, "btc_dd": btc_dd,
           "exposure": {b: exposure_by_coin(P, series[("O", b, ORIGINAL[b])][0][3], alp) for b in BOOKS}}
    write(res)


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def write(res: dict) -> None:
    path = fc.RESULTS_DIR / f"{NAME}.md"
    try:
        head = path.read_text(encoding="utf-8").split(MARKER)[0]
    except OSError:
        head = f"# {NAME}\n\n"
    rows, v, pool, av = res["rows"], res["verdicts"], res["pool"], res["availability"]
    main_cols = ["group", "book", "variant", "is_taker 35bps", "oos_maker 15bps", "oos_taker 35bps",
                 "oos_stress 70bps", "cagr_35", "dd_35", "expo", "turnover_yr", "trades_month", "orders_month",
                 "coins_held", "non_alpaca_share", "deflated_p", "boot35_p05", "boot35_p95"]
    year_cols = ["group", "book", "variant"] + [f"y{y}" for y in YEARS]
    ver_cols = ["book", "pick", "pick_is_35", "pick_oos_35", "pick_oos_70", "pick_dd", "pick_deflated_p",
                "cash_oos_35", "twin_oos_35", "late_oos_35", "diff_sharpe", "sr_diff_p05", "sr_diff_p95",
                "diff_2024", "diff_2025", "diff_2026", "passes"]
    n_pass = sum(x["passes"] for x in v)
    md = [head, MARKER, "\n\n",
          f"## Results (generated {datetime.now(timezone.utc):%Y-%m-%d}, data to {res['panel_end']})\n\n",
          f"**Verdict: {'nothing passes' if n_pass == 0 else f'{n_pass} pick(s) pass'}.** "
          + " ".join(f"{x['original']}: {x['why']}." for x in v)
          + f" Deflation pool {pool['n_total']} trials (prior {pool['prior_trials']}, here {pool['mine']}); "
            f"the best noise trial is expected at an annual Sharpe of about {pool['sr0_annual']:.2f}. "
            f"Panel: {res['segments']} coin segments, out of sample {res['oos_days']} days.\n\n",
          "### The Alpaca coins through time\n\n",
          f"{av['listed']} of the 15 are in the panel as current segments. Eligible (alive, 60 days old, 1 M USD "
          f"a day): {av['eligible_2020_08_01']} on 2020-08-01, {av['eligible_2024_01_01']} on 2024-01-01, "
          f"{av['eligible_oos_min']} to {av['eligible_oos_max']} on every out-of-sample day. First eligible day: "
          + ", ".join(f"{k} {d}" for k, d in sorted(av["first_eligible"].items(), key=lambda kv: kv[1] or "")) + ".\n\n",
          "### Each pick against the cash-left book (out of sample, 35 bps)\n\n",
          "`diff_*` is the pick minus the cash-left book, daily net returns; `diff_2024` to `diff_2026` are its "
          "summed returns per year; `sr_diff_*` the stationary-bootstrap 90 % band of the Sharpe difference.\n\n",
          fc.table(v, ver_cols), "\n",
          "### Every book (in sample 2020-08 to 2023, out of sample from 2024)\n\n",
          "O original (reference), C cash-left, R restricted to the Alpaca coins, T the survivorship-free twin "
          "(yearly top 15 list), L the pick one day late. Sharpe at 15 / 35 / 70 bps; CAGR, drawdown and the "
          "bootstrap band at 35 bps; trades and orders per month out of sample; `non_alpaca_share` the share of "
          "exposure in coins Alpaca does not list; deflated p over the whole pool.\n\n",
          fc.table(res["benchmarks"] + rows, main_cols), "\n",
          "### Per year (Sharpe at 35 bps)\n\n", fc.table(res["benchmarks"] + rows, year_cols), "\n",
          "### Where the originals' exposure sits (out of sample)\n\n"]
    for b, ex in res["exposure"].items():
        md.append(f"- {ORIGINAL[b]}: " + ", ".join(
            f"{e['coin']} {e['share'] * 100:.0f} %{'' if e['alpaca'] else ' (not on Alpaca)'}" for e in ex) + "\n")
    md.append("\n### The twin's yearly lists\n\n")
    for y, names in res["twin_lists"].items():
        md.append(f"- {y}: " + ", ".join(n[:-4] if "~" not in n else n for n in names) + "\n")
    md.append(f"\n### Deflation\n\nPrior: {pool['prior_trials']} trials, variance backed out of the published bar "
              f"({PRIOR_SR0} over {PRIOR_TRIALS}); here {pool['mine']} trials at 35 bps. Pooled bar "
              f"{pool['sr0_annual']:.2f} over {pool['n_total']}.\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(md), encoding="utf-8")
    d = fc.OUT / "reports"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{NAME}.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
