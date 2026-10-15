"""W3: breakout and momentum on every coin the Alpaca paper account lists, with a meme sleeve.

    python -m lab.experiments.alpaca36

Pre-registered in results/alpaca36.md (the part above the marker was committed
before this file existed). On the sweep's survivorship-free daily panel, all
long-only, all through the paper books' own weight functions and simulators:

  R15  reference, not counted: the three paper books with every coin outside
       the 15 Alpaca lab coins held as cash (C16's cash-left books)
  C32  the three books exactly as defined, every coin outside the 32 Alpaca
       coins in cash
  X    the rules choosing only among CORE (the 32 less the six memecoins), the
       top K by 28-day volume each day, K 10 and 15: Donchian 20 and 55 (exit
       N/2, slots K, no regime), tsmom 28d daily and in seven weekly tranches
       (regime)
  M    the meme sleeve alone, choosing among every eligible memecoin (slots 6):
       Donchian 20/10, Donchian 55/27, tsmom 28d (regime)
  S    each family's X pick with the M pick: 90 % core, 10 % sleeve, mixed daily
       at the return level (the sleeves' rebalancing is not charged)
  L    every pick (three X, one M) filled one day late

Picks: per family the X variant with the best in-sample Sharpe at 35 bps; the
M variant with the best in-sample Sharpe at 35 bps. A pick or pick plus sleeve
passes if, against the R15 book of its family out of sample at 35 bps, the six
rules of the pre-registration hold. Deflated over the prior pool (377 trials at
a bar of 2.43, results/alpaca_universe.md) plus these 21.

Implementation choices (the pre-registration leaves them open):
  * the sleeve's tsmom sizes each coin at 40 % vol over 6 slots, the sleeve's
    slot count, rather than over the day's eligible memecoin count;
  * "higher in at least 2 of 3 years" compares per-year Sharpes at 35 bps;
  * S filled late is the late core pick mixed with the late meme pick.

Writes results/alpaca36.md and <agent-strategies>/reports/alpaca36.json.
"""

from __future__ import annotations

import itertools
import json
import math
from datetime import datetime, timezone

import numpy as np
from scipy import stats

from .. import universe as uni
from ..metrics import deflated_sharpe
from . import alpaca_universe as au
from . import fam_common as fc, fam_volmom

NAME = "alpaca36"
MARKER = "<!-- generated below by lab.experiments.alpaca36; edit above this line only -->"
COSTS = au.COSTS
BASE = au.BASE
STRESS = "stress 70bps"
YEARS = au.YEARS
YEARS_OOS = au.YEARS_OOS
KS = (10, 15)
NS = (20, 55)
MEME_SLOTS = 6
MEME_SHARE = 0.10
DD_SLACK = 0.05
# The prior pool and its published bar (results/alpaca_universe.md).
PRIOR_TRIALS, PRIOR_SR0 = 377, 2.43
HERE_TRIALS = 21
BOOKS = au.BOOKS
ORIGINAL = au.ORIGINAL
SHORT = {"breakout": "breakout", "tsmom_daily": "tsmom", "tsmom_tranches": "tranches"}


# ---------------------------------------------------------------------------
# Variants
# ---------------------------------------------------------------------------

def core_variants(P: fc.Panel, core: np.ndarray) -> list[tuple[str, str, np.ndarray]]:
    """X: (book, name, W) for the rules choosing only among `core`, 8 variants."""
    out = []
    for n, k in itertools.product(NS, KS):
        out.append(("breakout", f"Donchian {n}/{n // 2} · CORE top {k}", au.breakout_on(P, au.top_within(P, core, k), n, k)))
    for k in KS:
        W = au.tsmom_weights(P, au.top_within(P, core, k))
        out.append(("tsmom_daily", f"tsmom 28d · CORE top {k} · regime · daily", W))
        out.append(("tsmom_tranches", f"tsmom 28d · CORE top {k} · regime · seven weekly tranches", W))
    return out


def meme_tsmom(P: fc.Panel, memes: np.ndarray, slots: int = MEME_SLOTS) -> np.ndarray:
    """tsmom 28d on the eligible memecoins, 40 % vol each over `slots`, BTC regime."""
    lb = fam_volmom.LOOKBACK
    past = np.full_like(P.px, np.nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        past[lb:] = P.px[lb:] / P.px[:-lb] - 1
    member = P.eligible & memes[None, :]
    held = member & np.isfinite(past) & (past > 0)
    return fc.vol_sized(P, held, fam_volmom.COIN_VOL, slots) * P.btc_on[:, None]


def meme_variants(P: fc.Panel, memes: np.ndarray) -> list[tuple[str, str, np.ndarray]]:
    """M: the sleeve on its own, 3 variants, all on the daily simulator."""
    allowed = P.eligible & memes[None, :]
    out = [("memes", f"Donchian {n}/{n // 2} · memes · slots {MEME_SLOTS}", au.breakout_on(P, allowed, n, MEME_SLOTS))
           for n in NS]
    out.append(("memes", f"tsmom 28d · memes · slots {MEME_SLOTS} · regime", meme_tsmom(P, memes)))
    return out


def sleeve_mix(core_run: tuple, meme_run: tuple, share: float = MEME_SHARE) -> tuple:
    """(gross, turnover, expo, held) of (1 - share) in the core book and `share` in the
    sleeve, re-mixed every day at no cost."""
    return tuple((1 - share) * a + share * b for a, b in zip(core_run, meme_run))


# ---------------------------------------------------------------------------
# Deflation over the prior pool
# ---------------------------------------------------------------------------

def prior_var(trials: int = PRIOR_TRIALS, sr0: float = PRIOR_SR0) -> float:
    """Variance of daily trial Sharpes implied by the published bar over the prior pool."""
    g = 0.5772156649
    z = (1 - g) * stats.norm.ppf(1 - 1 / trials) + g * stats.norm.ppf(1 - 1 / (trials * math.e))
    return (sr0 / math.sqrt(365) / z) ** 2


def pooled_var(mine: list[float]) -> tuple[float, dict]:
    v1, n1 = prior_var(), PRIOR_TRIALS
    x = np.clip(np.array(mine, dtype=float), -fc.SR_CLIP, fc.SR_CLIP) / math.sqrt(365)
    n2, v2 = len(x), float(np.var(x)) if len(x) else 0.0
    n = n1 + n2
    v = (n1 * v1 + n2 * v2) / n
    return v, {"prior_trials": n1, "prior_var": v1, "mine": n2, "mine_var": v2, "pooled_var": v, "n_total": n,
               "sr0_annual": fc._sr0(v, n) * math.sqrt(365)}


def deflated(x: np.ndarray, n: int, var: float) -> float:
    if len(x) < 2 or x.std() == 0:
        return 0.0
    return deflated_sharpe(au.sharpe_d(x), len(x), n, var, float(stats.skew(x)), float(stats.kurtosis(x, fisher=False)))


# ---------------------------------------------------------------------------
# Judging
# ---------------------------------------------------------------------------

def year_sharpes(P: fc.Panel, n: np.ndarray, years=YEARS_OOS) -> dict[int, float]:
    yr = au.years_of(P)
    return {y: fc.perf(n[yr == y])["sharpe"] for y in years if (yr == y).sum() >= 2}


def judge(P: fc.Panel, cand: tuple, ref: tuple, late: tuple, meme: tuple | None, rng: np.random.Generator) -> dict:
    """The six rules for one candidate run against its family's R15 run, all out of sample.
    `late` is the candidate filled one day late; `meme` the sleeve's own run (S only)."""
    _, oos = fc.masks(P)
    c35, r35 = au.net(cand[0], cand[1], COSTS[BASE]), au.net(ref[0], ref[1], COSTS[BASE])
    pc, pr = fc.perf(c35[oos]), fc.perf(r35[oos])
    yc, yref = year_sharpes(P, c35), year_sharpes(P, r35)
    better_years = sum(yc[y] > yref[y] for y in yc if y in yref)
    lo, hi = au.boot_band(c35[oos], rng, r35[oos])
    s70 = fc.perf(au.net(cand[0], cand[1], COSTS[STRESS])[oos])["sharpe"]
    s_late = fc.perf(au.net(late[0], late[1], COSTS[BASE])[oos])["sharpe"]
    rules = {
        "1 higher Sharpe, 2 of 3 years": pc["sharpe"] > pr["sharpe"] and better_years >= 2,
        "2 band above 0": lo > 0,
        "3 positive at 70 bps": s70 > 0,
        "4 drawdown within +5 pp": pc["max_dd"] <= pr["max_dd"] + DD_SLACK,
        "5 positive one day late": s_late > 0,
    }
    out = {"oos_35": pc["sharpe"], "ref_oos_35": pr["sharpe"], "better_years": better_years,
           "sr_diff_p05": lo, "sr_diff_p95": hi, "oos_70": s70, "dd": pc["max_dd"], "ref_dd": pr["max_dd"],
           "late_oos_35": s_late}
    for y in YEARS_OOS:
        out[f"y{y}"] = yc.get(y, float("nan"))
        out[f"ref_y{y}"] = yref.get(y, float("nan"))
    if meme is not None:
        sm = fc.perf(au.net(meme[0], meme[1], COSTS[BASE])[oos])["sharpe"]
        out["meme_oos_35"] = sm
        rules["6 meme sleeve positive"] = sm > 0
    out["rules"] = rules
    out["failed"] = [k for k, ok in rules.items() if not ok]
    out["passes"] = not out["failed"]
    return out


def label(passes: bool, p: float) -> str:
    if not passes:
        return "fails the pass rule, no book"
    if p > 0.95:
        return "passes and survives deflation: confirmed"
    return "passes, fails deflation: forward evidence only"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_study(P: fc.Panel, seed: int = 20261015) -> dict:
    ins, oos = fc.masks(P)
    m15, m32 = uni.mask(P, uni.ALPACA15), uni.mask(P, uni.ALPACA)
    core, memes = uni.mask(P, uni.CORE), uni.mask(P, uni.MEMES)
    rng = np.random.default_rng(seed)
    rows: list[dict] = []
    runs: dict[tuple[str, str, str], tuple] = {}

    def add(group: str, book: str, name: str, run: tuple, counted: bool = True) -> dict:
        r = au.describe(P, group, book, name, run, m32)
        r["counted"] = counted
        rows.append(r)
        runs[(group, book, name)] = run
        print(f"  {group:3s} {book:15s} {name:60s} IS {r['is_taker 35bps']:5.2f} OOS {r['oos_taker 35bps']:5.2f}",
              flush=True)
        return r

    O = au.originals(P)
    ref = {}
    for b in BOOKS:
        name = ORIGINAL[b] + " · outside A15 in cash"
        add("R15", b, name, au.simulate(P, b, au.cash_left(O[b], m15)), counted=False)
        ref[b] = runs[("R15", b, name)]
    for b in BOOKS:
        add("C32", b, ORIGINAL[b] + " · outside A32 in cash", au.simulate(P, b, au.cash_left(O[b], m32)))
    xW = {}
    for b, name, W in core_variants(P, core):
        add("X", b, name, au.simulate(P, b, W))
        xW[(b, name)] = W
    mW = {}
    for b, name, W in meme_variants(P, memes):
        add("M", b, name, au.sim_daily(P, W))
        mW[name] = W

    def best(group: str, book: str) -> dict:
        cands = [r for r in rows if r["group"] == group and r["book"] == book]
        return max(cands, key=lambda r: r["is_taker 35bps"])

    picks = {b: best("X", b)["variant"] for b in BOOKS}
    meme_pick = best("M", "memes")["variant"]
    meme_run = runs[("M", "memes", meme_pick)]
    for b in BOOKS:
        add("S", b, f"90 % {picks[b]} + 10 % {meme_pick}", sleeve_mix(runs[("X", b, picks[b])], meme_run))
    late = {}
    for b in BOOKS:
        late[b] = au.simulate(P, b, au.one_day_late(xW[(b, picks[b])]))
        add("L", b, picks[b] + " · one day late", late[b])
    late_meme = au.sim_daily(P, au.one_day_late(mW[meme_pick]))
    add("L", "memes", meme_pick + " · one day late", late_meme)

    counted = [r for r in rows if r["counted"]]
    assert len(counted) == HERE_TRIALS, len(counted)
    var, pool = pooled_var([r["oos_taker 35bps"] for r in counted])
    for r in rows:
        n35 = au.net(*runs[(r["group"], r["book"], r["variant"])][:2], COSTS[BASE])
        r["deflated_p"] = deflated(n35[oos], pool["n_total"], var)
        r["boot35_p05"], r["boot35_p95"] = au.boot_band(n35[oos], rng)

    verdicts = []
    for b in BOOKS:
        for kind in ("core", "core + memes"):
            if kind == "core":
                cand, lt, mm, variant = runs[("X", b, picks[b])], late[b], None, picks[b]
                book = f"a36_{SHORT[b]}"
            else:
                variant = f"90 % {picks[b]} + 10 % {meme_pick}"
                cand, lt, mm = runs[("S", b, variant)], sleeve_mix(late[b], late_meme), meme_run
                book = f"a36_{SHORT[b]}_memes"
            j = judge(P, cand, ref[b], lt, mm, rng)
            p = next(r["deflated_p"] for r in rows if r["variant"] == variant)
            verdicts.append({"family": b, "reference": ORIGINAL[b] + " · outside A15 in cash", "candidate": variant,
                             "book": book, "deflated_p": p, **{k: v for k, v in j.items() if k != "rules"},
                             "failed": "; ".join(j["failed"]) or "-", "verdict": label(j["passes"], p)})

    cover = uni.coverage(P, uni.ALPACA)
    return {"panel_end": str(np.datetime64(int(P.days[-1]), "us").astype("datetime64[D]")),
            "segments": P.N, "oos_days": int(oos.sum()), "rows": rows, "verdicts": verdicts, "pool": pool,
            "picks": picks, "meme_pick": meme_pick, "coverage": cover,
            "eligible_core_oos": [int(x) for x in np.percentile((P.eligible & core).sum(1)[oos], [0, 50, 100])],
            "eligible_memes_oos": [int(x) for x in np.percentile((P.eligible & memes).sum(1)[oos], [0, 50, 100])]}


def main() -> None:
    res = run_study(fc.load_panel())
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
    v, pool = res["verdicts"], res["pool"]
    passed = [x for x in v if x["passes"]]
    main_cols = ["group", "book", "variant", "counted", "is_taker 35bps", "oos_maker 15bps", "oos_taker 35bps",
                 "oos_stress 70bps", "cagr_35", "dd_35", "expo", "turnover_yr", "trades_month", "coins_held",
                 "deflated_p", "boot35_p05", "boot35_p95"]
    year_cols = ["group", "book", "variant"] + [f"y{y}" for y in YEARS]
    ver_cols = ["book", "candidate", "oos_35", "ref_oos_35", "better_years", "sr_diff_p05", "sr_diff_p95", "oos_70",
                "dd", "ref_dd", "late_oos_35", "meme_oos_35", "deflated_p", "failed", "verdict"]
    cov_cols = ["coin", "in_panel", "first_bar", "first_eligible", "eligible_days_is", "history"]
    if passed:
        head_line = (f"**Verdict: {len(passed)} candidate(s) pass: "
                     + ", ".join(f"{x['book']} ({x['verdict']})" for x in passed) + ".**")
    else:
        head_line = "**Verdict: nothing passes, no paper book is added.**"
    none = [c["coin"] for c in res["coverage"] if c["history"] == "none"]
    short = [c["coin"] for c in res["coverage"] if c["history"] == "short"]
    md = [head, MARKER, "\n\n",
          f"## Results (generated {datetime.now(timezone.utc):%Y-%m-%d}, data to {res['panel_end']})\n\n",
          head_line, " ",
          " ".join(f"{x['book']}: {x['failed'] if x['failed'] != '-' else 'all six rules hold'}." for x in v),
          f" Picks: breakout {res['picks']['breakout']}; tsmom {res['picks']['tsmom_daily']}; tranches "
          f"{res['picks']['tsmom_tranches']}; sleeve {res['meme_pick']}. Deflation pool {pool['n_total']} trials "
          f"(prior {pool['prior_trials']}, here {pool['mine']}); the best noise trial is expected at an annual "
          f"Sharpe of about {pool['sr0_annual']:.2f}. Panel: {res['segments']} coin segments, out of sample "
          f"{res['oos_days']} days.\n\n",
          "### Coverage of the 32 Alpaca coins\n\n",
          f"No Binance USDT history (cannot be tested): {', '.join(none) or 'none'}. Short history (chosen out of "
          f"sample only): {', '.join(short) or 'none'}. Eligible CORE coins on out-of-sample days: min "
          f"{res['eligible_core_oos'][0]}, median {res['eligible_core_oos'][1]}, max {res['eligible_core_oos'][2]}; "
          f"eligible memecoins: {res['eligible_memes_oos'][0]} / {res['eligible_memes_oos'][1]} / "
          f"{res['eligible_memes_oos'][2]}.\n\n",
          fc.table([{k: ("-" if x is None else x) for k, x in c.items()} for c in res["coverage"]], cov_cols), "\n",
          "### Each candidate against its R15 reference (out of sample, 35 bps)\n\n",
          "`sr_diff_*` is the stationary-bootstrap 90 % band of the Sharpe difference on the same days; "
          "`better_years` counts 2024 to 2026 with a higher Sharpe; `failed` names the broken rules.\n\n",
          fc.table(v, ver_cols), "\n",
          "### Every run (in sample 2020-08 to 2023, out of sample from 2024)\n\n",
          "R15 reference (not counted), C32 cash-left on the 32, X CORE only, M meme sleeve alone, S 90/10 core "
          "plus sleeve, L one day late. Sharpe at 15 / 35 / 70 bps; CAGR, drawdown and the bootstrap band at "
          "35 bps; deflated p over the whole pool.\n\n",
          fc.table(res["rows"], main_cols), "\n",
          "### Per year (Sharpe at 35 bps)\n\n", fc.table(res["rows"], year_cols), "\n",
          f"### Deflation\n\nPrior: {pool['prior_trials']} trials, variance backed out of the published bar "
          f"({PRIOR_SR0} over {PRIOR_TRIALS}); here {pool['mine']} trials at 35 bps. Pooled bar "
          f"{pool['sr0_annual']:.2f} over {pool['n_total']}.\n"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(md), encoding="utf-8", newline="\n")
    d = fc.OUT / "reports"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{NAME}.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
