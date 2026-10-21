"""O3: a Binance delisting hazard model as an exclusion filter on the Alpaca books.

Run through `python -m lab.experiments.crypto_own` (registered together with
kr_premium_xs and xs_factors in results/crypto_own_prereg.md).

Event: a coin segment's last bar followed by at least 30 days without a bar of the
same symbol. Rows: every day from 2020-08 and coin alive, traded, 60 days old, with a
28-day volume; label 1 if the event is 1 to 60 days ahead. LightGBM with quarterly
walk-forward from 2022-Q1 (training rows end 70 days before each quarter) against the
baseline "lowest 90-day volume". The top 5 % hazard of each day is filtered from the
books. Writes results/delist_hazard.md and <reports>/delist_hazard/latest.*.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone

import numpy as np

from .. import report
from ..data import ROOT
from . import crypto_own as co
from . import director_common as dc
from . import fam_common as fc

NAME = "delist_hazard"
H, H_SHORT = 60, 30
GAP_D = 30
LABEL_LAG = 90
EMBARGO = 10
FIRST_Q = "2022-01-01"
TOP = 0.05
AUC_MARGIN = 0.05
BOOT_DRAWS = 1000
PARAMS = dict(n_estimators=300, learning_rate=0.03, num_leaves=15, min_child_samples=200, subsample=0.8,
              subsample_freq=1, colsample_bytree=0.8, random_state=7, verbose=-1)
FEATURES = ("log_age", "log_adv28", "vol_7_28", "vol_28_90", "adv_rank", "log_amihud", "log_price", "dd_ath", "r90",
            "vol30", "hours28", "perp", "perp_removed", "funding7")
INFO_FEATURES = FEATURES + ("coinbase", "kraken")


# ---------------------------------------------------------------------------
# Events, rows, features
# ---------------------------------------------------------------------------

def events(P: fc.Panel) -> np.ndarray:
    """(N,) bool: the segment's last bar is followed by at least GAP_D days without a bar of
    its symbol, and lies at least GAP_D days before the panel end."""
    T = P.T
    last = np.minimum(P.extra["last"], T - 1)
    first = P.extra["first"]
    sym = [n.split("~")[0] for n in P.names]
    by_sym: dict[str, list[int]] = {}
    for j, s in enumerate(sym):
        by_sym.setdefault(s, []).append(j)
    ev = np.zeros(P.N, dtype=bool)
    for j in range(P.N):
        if last[j] < 0 or last[j] > T - 1 - GAP_D:
            continue
        nxt = [first[i] for i in by_sym[sym[j]] if first[i] > last[j]]
        ev[j] = (min(nxt) - last[j] > GAP_D) if nxt else True
    return ev


def features(P: fc.Panel) -> tuple[dict[str, np.ndarray], np.ndarray]:
    alive = P.alive
    qv_a = np.where(alive, np.nan_to_num(P.extra["qv"]), np.nan)
    adv7 = fc.rolling(qv_a, 7, 5)
    adv28 = P.adv28
    adv90 = fc.rolling(qv_a, 90, 60)
    rowmask = alive & P.traded & (P.age >= fc.MIN_AGE_D) & np.isfinite(adv28)
    f: dict[str, np.ndarray] = {}
    with np.errstate(invalid="ignore", divide="ignore"):
        f["log_age"] = np.log1p(np.where(alive, P.age, np.nan))
        f["log_adv28"] = np.log1p(adv28)
        f["vol_7_28"] = np.log1p(adv7) - np.log1p(adv28)
        f["vol_28_90"] = np.log1p(adv28) - np.log1p(adv90)
        f["adv_rank"] = fc.xs_rank(adv28, rowmask)
        qv = P.extra["qv"]
        ami = np.where((qv > 0) & np.isfinite(P.ret), np.abs(P.ret) / np.where(qv > 0, qv, 1.0), np.nan)
        f["log_amihud"] = np.log(fc.rolling(ami, 28, 10) + 1e-15)
        lp = np.log(P.px)
        f["log_price"] = lp
        ath = np.fmax.accumulate(np.where(alive, P.px, np.nan), axis=0)
        f["dd_ath"] = lp - np.log(ath)
        r90 = np.full_like(lp, np.nan)
        r90[90:] = lp[90:] - lp[:-90]
        f["r90"] = r90
        f["vol30"] = P.sigma
        n = co.panel_column(P, "n")
        f["hours28"] = fc.rolling(np.where(alive, np.nan_to_num(n) / 24.0, np.nan), 28, 20)
        perp = P.perp_ok.astype(float)
        f["perp"] = np.where(alive, perp, np.nan)
        prev = np.zeros_like(perp)
        prev[1:] = perp[:-1]
        seen = fc.rolling(prev, 90, 1, how="sum") > 0
        f["perp_removed"] = np.where(alive, (seen & ~P.perp_ok).astype(float), np.nan)
        f["funding7"] = fc.rolling(np.where(alive, P.funding, np.nan), 7, 1)
    f["_adv90"] = adv90
    return f, rowmask


def venue_flags(P: fc.Panel) -> dict[str, np.ndarray]:
    """Coinbase and Kraken listed by day t (information only: the lists hold what the venues still serve)."""
    out = {}
    for key, fname in (("coinbase", "coinbase_first_hour.json"), ("kraken", "kraken_first.json")):
        p = ROOT / "hist" / "listings" / fname
        first = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
        m = np.zeros((P.T, P.N))
        for j, b in enumerate(P.bases):
            t0 = first.get(b)
            if t0:
                m[:, j] = (P.days + fc.DAY_US > int(t0)).astype(float)
        out[key] = np.where(P.alive, m, np.nan)
    return out


# ---------------------------------------------------------------------------
# AUC, weighted (for the day bootstrap)
# ---------------------------------------------------------------------------

class SortedAUC:
    """AUC with row weights, the score order computed once (ties count half)."""

    def __init__(self, score: np.ndarray, y: np.ndarray):
        o = np.argsort(score, kind="stable")
        s = score[o]
        self.o = o
        self.y = y[o].astype(float)
        self.g = np.r_[0, np.cumsum(s[1:] != s[:-1])]
        self.ng = int(self.g[-1]) + 1

    def __call__(self, w: np.ndarray | None = None) -> float:
        w = np.ones(len(self.o)) if w is None else w[self.o]
        wp = np.bincount(self.g, w * self.y, self.ng)
        wn = np.bincount(self.g, w * (1 - self.y), self.ng)
        P_, N_ = wp.sum(), wn.sum()
        if P_ <= 0 or N_ <= 0:
            return float("nan")
        below = np.cumsum(wn) - wn
        return float((wp * (below + 0.5 * wn)).sum() / (P_ * N_))


def day_boot_weights(day_idx: np.ndarray, n_days: int, rng: np.random.Generator):
    """Stationary bootstrap over days (mean block 20): yields row weights = times each row's day is drawn."""
    for _ in range(BOOT_DRAWS):
        idx = np.empty(n_days, dtype=np.int64)
        idx[0] = rng.integers(0, n_days)
        jump = rng.random(n_days) < 1 / dc.BOOT_BLOCK
        fresh = rng.integers(0, n_days, n_days)
        for i in range(1, n_days):
            idx[i] = fresh[i] if jump[i] else (idx[i - 1] + 1) % n_days
        cnt = np.bincount(idx, minlength=n_days).astype(float)
        yield cnt[day_idx]


# ---------------------------------------------------------------------------
# Walk-forward
# ---------------------------------------------------------------------------

def quarter_starts(P: fc.Panel) -> list[int]:
    out = []
    for t, d in enumerate(P.days):
        dt = datetime.fromtimestamp(int(d) / 1e6, timezone.utc)
        if dt.day == 1 and dt.month in (1, 4, 7, 10) and int(d) >= dc.us(FIRST_Q):
            out.append(t)
    return out


def walk_forward(P: fc.Panel, X: np.ndarray, y: np.ndarray, t_row: np.ndarray, labelled: np.ndarray) -> np.ndarray:
    import lightgbm as lgb
    score = np.full(len(t_row), np.nan)
    qs = quarter_starts(P)
    for i, q in enumerate(qs):
        qe = qs[i + 1] if i + 1 < len(qs) else P.T
        tr = labelled & (t_row < q - H - EMBARGO)
        te = (t_row >= q) & (t_row < qe)
        if tr.sum() < 1000 or y[tr].sum() < 5 or not te.any():
            continue
        m = lgb.LGBMClassifier(**PARAMS)
        m.fit(X[tr], y[tr])
        score[te] = m.predict_proba(X[te])[:, 1]
    return score


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def compute(ctx: co.Ctx) -> dict:
    P = ctx.P
    T = P.T
    ev = events(P)
    last = np.minimum(P.extra["last"], T - 1)
    f, rowmask = features(P)
    f.update(venue_flags(P))
    t_idx = np.arange(T)[:, None]
    dist = last[None, :] - t_idx
    keep = rowmask & (P.days[:, None] >= fc.IS_START) & ~(ev[None, :] & (dist == 0))
    tt_, jj = np.nonzero(keep)
    y60 = (ev[jj] & (dist[tt_, jj] >= 1) & (dist[tt_, jj] <= H)).astype(int)
    y30 = (ev[jj] & (dist[tt_, jj] >= 1) & (dist[tt_, jj] <= H_SHORT)).astype(int)
    labelled = tt_ <= T - 1 - LABEL_LAG
    print(f"  rows {len(tt_):,}, events {int(ev.sum())}, positive rows {int(y60[labelled].sum()):,}", flush=True)

    X = np.column_stack([f[k][tt_, jj] for k in FEATURES])
    XI = np.column_stack([f[k][tt_, jj] for k in INFO_FEATURES])
    score = walk_forward(P, X, y60, tt_, labelled)
    print("  main model done", flush=True)
    score_i = walk_forward(P, XI, y60, tt_, labelled)
    print("  information model done", flush=True)
    adv90 = f["_adv90"][tt_, jj]
    base = -np.where(np.isfinite(adv90), adv90, f["log_adv28"][tt_, jj])
    base = np.where(np.isfinite(base), base, 0.0)

    split_t = int(np.searchsorted(P.days, fc.SPLIT))
    oos_rows = labelled & (tt_ >= split_t) & np.isfinite(score)
    years = ctx.years[tt_]

    def aucs(mask: np.ndarray, yv: np.ndarray, s: np.ndarray) -> float:
        return co_auc(s[mask], yv[mask])

    auc = {"model": aucs(oos_rows, y60, score), "baseline": aucs(oos_rows, y60, base),
           "info_model": aucs(oos_rows & np.isfinite(score_i), y60, np.nan_to_num(score_i)),
           "model_30d": aucs(oos_rows, y30, score), "baseline_30d": aucs(oos_rows, y30, base)}
    is_rows = labelled & (tt_ < split_t) & np.isfinite(score)
    auc["model_is"] = aucs(is_rows, y60, score)
    auc["baseline_is"] = aucs(is_rows, y60, base)
    per_year = []
    for yv in (2022, 2023, 2024, 2025, 2026):
        m = labelled & np.isfinite(score) & (years == yv)
        if m.any() and y60[m].sum() > 0:
            per_year.append({"year": yv, "rows": int(m.sum()), "positives": int(y60[m].sum()),
                             "model": aucs(m, y60, score), "baseline": aucs(m, y60, base)})

    # Day bootstrap of the AUC difference (out of sample).
    sel = np.flatnonzero(oos_rows)
    days_u, day_idx = np.unique(tt_[sel], return_inverse=True)
    am, ab = SortedAUC(score[sel], y60[sel]), SortedAUC(base[sel], y60[sel])
    rng = np.random.default_rng(co.SEED)
    diffs = np.array([am(w) - ab(w) for w in day_boot_weights(day_idx, len(days_u), rng)])
    auc["diff"] = auc["model"] - auc["baseline"]
    auc["diff_lo"], auc["diff_hi"] = float(np.nanpercentile(diffs, 5)), float(np.nanpercentile(diffs, 95))
    auc["model_pass"] = bool(auc["diff"] >= AUC_MARGIN and auc["diff_lo"] > 0)
    auc["killed"] = bool(auc["model"] <= auc["baseline"])

    # Flags: top 5 % hazard each day among the scored rows.
    Hm = np.full((T, P.N), np.nan)
    Hm[tt_, jj] = score
    q = fc.xs_rank(Hm, np.isfinite(Hm))
    flag = np.isfinite(q) & (q > 1 - TOP)
    fl_rows = flag[tt_, jj]
    prec = {"top5_precision": float(y60[oos_rows & fl_rows].mean()) if (oos_rows & fl_rows).any() else float("nan"),
            "base_rate": float(y60[oos_rows].mean()), "flagged_rows": int((oos_rows & fl_rows).sum())}
    fwd60 = co.fwd_log_return(P, H)[tt_, jj]
    fo = oos_rows & np.isfinite(fwd60)
    prec["fwd60_flagged"] = float(np.mean(np.expm1(fwd60[fo & fl_rows]))) if (fo & fl_rows).any() else float("nan")
    prec["fwd60_other"] = float(np.mean(np.expm1(fwd60[fo & ~fl_rows])))
    prec["fwd60_flagged_median"] = float(np.median(np.expm1(fwd60[fo & fl_rows]))) if (fo & fl_rows).any() else float("nan")
    prec["fwd60_other_median"] = float(np.median(np.expm1(fwd60[fo & ~fl_rows])))

    # Feature importance of the last main model, by gain, as information.
    import lightgbm as lgb
    tr = labelled
    imp_model = lgb.LGBMClassifier(**{**PARAMS, "importance_type": "gain"}).fit(X[tr], y60[tr])
    imp = sorted(zip(FEATURES, imp_model.feature_importances_), key=lambda x: -x[1])
    tot = sum(v for _, v in imp) or 1.0
    importance = [{"feature": k, "gain_pct": 100 * v / tot} for k, v in imp]

    # The books.
    trials, picks, held = [], [], []
    for b in co.BOOKS:
        base_live = ctx.base35[(b, "live")]
        run = co.apply(ctx, b, "live", "filter", flag)
        lrun = co.apply(ctx, b, "live", "filter", co.late(flag))
        trun = co.apply(ctx, b, "twin", "filter", flag)
        key = "hazard top 5 % excluded"
        trials += [co.trial(ctx, NAME, key, b, "mod", run, base_live),
                   co.trial(ctx, NAME, key + " · late", b, "late", lrun, base_live),
                   co.trial(ctx, NAME, key + " · twin", b, "twin", trun, ctx.base35[(b, "twin")])]
        picks.append(co.pick_row(ctx, b, key, run, lrun, trun))
        for ver in ("live", "twin"):
            hw = ctx.base[(b, ver)][3]
            hit = ((hw > 0) & flag).any(1)
            inv = (hw > 0).any(1)
            m = ctx.oos & inv
            held.append({"book": co.ORIGINAL[b], "version": ver,
                         "book_days_holding_flagged_pct": 100 * float(hit[m].mean()) if m.any() else 0.0,
                         "weight_in_flagged_pct": 100 * float(np.where(flag, hw, 0).sum(1)[m].mean()) if m.any() else 0.0})

    liq = []
    for j in np.flatnonzero(ev):
        lt = last[j]
        a = P.adv28[max(lt - 30, 0), j]
        liq.append({"coin": P.names[j], "last_day": dc.day_str(P.days[lt]), "adv28_musd_30d_before": (a or 0) / 1e6})
    liq.sort(key=lambda r: -(r["adv28_musd_30d_before"] if math.isfinite(r["adv28_musd_30d_before"]) else 0))
    ev_years: dict[int, int] = {}
    for j in np.flatnonzero(ev):
        yv = int(ctx.years[last[j]])
        ev_years[yv] = ev_years.get(yv, 0) + 1

    return {"trials": trials, "picks": picks, "auc": auc, "per_year": per_year, "precision": prec,
            "importance": importance, "held": held, "events_top": liq[:20], "event_years": ev_years,
            "n_events": int(ev.sum()), "n_rows": int(len(tt_)), "n_oos_rows": int(oos_rows.sum()),
            "n_oos_pos": int(y60[oos_rows].sum()), "first_scored": dc.day_str(P.days[int(tt_[np.isfinite(score)].min())])}


def co_auc(s: np.ndarray, y: np.ndarray) -> float:
    return SortedAUC(np.asarray(s, dtype=float), np.asarray(y)).__call__()


def write(ctx: co.Ctx, res: dict, fin: dict) -> None:
    a, p = res["auc"], res["precision"]
    picks = res["picks"]
    any_pass = any(r["passes"] for r in picks)
    useful = a["model_pass"] and any_pass
    md = ["# Delisting hazard (survey O3): results\n",
          f"Generated {datetime.now(timezone.utc).isoformat(timespec='seconds')}. Registered in "
          "`results/crypto_own_prereg.md` before the run. Panel to "
          f"{dc.day_str(ctx.P.days[-1])}; out of sample from 2024-01-01; books at 35 bps, coins Alpaca does not list "
          "in cash.\n",
          "## Verdict\n"]
    if a["killed"]:
        v = "Killed: the model is no better than the lowest 90-day volume out of sample."
    elif not a["model_pass"]:
        v = "Not useful: the model does not clear the baseline by the registered margin."
    else:
        v = "The model passes."
    v += (" No book improves by the gates." if not any_pass else " At least one book passes the gates.")
    v += " Useful as a filter: " + ("yes." if useful else "no.")
    md.append(v + "\n")
    md.append(f"- Out of sample (labelled rows from 2024, {res['n_oos_rows']:,} coin-days, {res['n_oos_pos']:,} "
              f"within 60 days of an event): AUC {a['model']:.3f} against the baseline's {a['baseline']:.3f}, "
              f"difference {a['diff']:+.3f}, day-bootstrap band {a['diff_lo']:+.3f} to {a['diff_hi']:+.3f} "
              f"(pass needs +0.050 and a band above 0).")
    md.append(f"- In sample (2022-23, also walk-forward): {a['model_is']:.3f} against {a['baseline_is']:.3f}. "
              f"30-day label from 2024: {a['model_30d']:.3f} against {a['baseline_30d']:.3f}. With the Coinbase and "
              f"Kraken flags (information, leaks survival): {a['info_model']:.3f}.")
    md.append(f"- The top 5 % each day: {p['top5_precision'] * 100:.1f} % of flagged coin-days are within 60 days of "
              f"an event, against a base rate of {p['base_rate'] * 100:.2f} %. Their next 60 days: mean "
              f"{p['fwd60_flagged'] * 100:+.1f} % (median {p['fwd60_flagged_median'] * 100:+.1f} %) against "
              f"{p['fwd60_other'] * 100:+.1f} % (median {p['fwd60_other_median'] * 100:+.1f} %) for the other scored coins.")
    md.append("")
    md.append("## The books\n")
    md += co.gates_lines(picks)
    md.append("")
    md.append(co.pick_table(picks))
    md.append("\nHow often the books held a flagged coin (out of sample, days with any position):\n")
    md.append(dc.table(res["held"], ["book", "version", "book_days_holding_flagged_pct", "weight_in_flagged_pct"]))
    md.append("\nThe books alone and gated BTC (35 bps, out of sample from 2024):\n")
    md.append(co.refs_table(ctx))
    md.append("\n## The model\n")
    md.append(f"{res['n_events']} events ({', '.join(f'{k}: {v}' for k, v in sorted(res['event_years'].items()))}); "
              f"{res['n_rows']:,} coin-days; first scored day {res['first_scored']}.\n")
    md.append(dc.table(res["per_year"], ["year", "rows", "positives", "model", "baseline"], fmt=".3f"))
    md.append("\nGain importance of a model fit on every labelled row (information):\n")
    md.append(dc.table(res["importance"], ["feature", "gain_pct"], fmt=".1f"))
    md.append("\nThe most liquid events (swaps and rebrands among them):\n")
    md.append(dc.table(res["events_top"], ["coin", "last_day", "adv28_musd_30d_before"]))
    md.append("\n" + co.pool_line(fin) + "\n")
    text = "\n".join(md)
    dc.write_results(NAME, text)
    data = {k: v for k, v in res.items() if k != "trials"}
    data["pool"] = fin["pool"]
    report.write(NAME, text, data)
