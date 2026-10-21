"""Six cross-sectional crypto factors as filters or tilts on the Alpaca books.

Run through `python -m lab.experiments.crypto_own` (registered in
results/crypto_own_prereg.md). Factors at the close of t, higher = worse (the prior):
ivol (60-day residual vol against BTC), max (largest daily return over 28 days), skew
(60-day skewness), vshock (log 7-day over 90-day volume), size (log 28-day volume),
rev7 (7-day log return). Ranked among the 50 most liquid eligible coins each day; the
worst third filtered, or every target tilted by 1.5 - rank. Writes results/xs_factors.md
and <reports>/xs_factors/latest.*.
"""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np

from .. import report
from . import crypto_own as co
from . import director_common as dc
from . import fam_common as fc

NAME = "xs_factors"
REF_TOP = 50
FACTORS = ("ivol", "max", "skew", "vshock", "size", "rev7")


def factors(P: fc.Panel) -> dict[str, np.ndarray]:
    lr = np.log1p(P.ret)
    b = lr[:, [P.btc]]
    m = np.isfinite(lr) & np.isfinite(b)
    x = np.where(m, lr, np.nan)
    y = np.where(m, np.broadcast_to(b, lr.shape), np.nan)
    W, MIN = 60, 40
    ex, ey = fc.rolling(x, W, MIN), fc.rolling(y, W, MIN)
    exx, eyy, exy = fc.rolling(x * x, W, MIN), fc.rolling(y * y, W, MIN), fc.rolling(x * y, W, MIN)
    with np.errstate(invalid="ignore", divide="ignore"):
        vx, vy, cxy = exx - ex ** 2, eyy - ey ** 2, exy - ex * ey
        res_var = vx - np.where(vy > 0, cxy ** 2 / np.where(vy > 0, vy, 1.0), np.nan)
        out = {"ivol": np.sqrt(np.maximum(res_var, 0.0))}
        # MAX: the largest daily return over the 28 days up to and including t.
        r = np.where(np.isfinite(P.ret), P.ret, -np.inf)
        mx = np.full_like(P.ret, -np.inf)
        for k in range(28):
            sh = np.full_like(r, -np.inf)
            sh[k:] = r[:r.shape[0] - k]
            mx = np.maximum(mx, sh)
        cnt = fc.rolling(np.where(np.isfinite(P.ret), 1.0, np.nan), 28, 1, how="sum")
        out["max"] = np.where(np.isfinite(mx) & (cnt >= 20), mx, np.nan)
        e1 = fc.rolling(lr, W, MIN)
        e2 = fc.rolling(lr ** 2, W, MIN)
        e3 = fc.rolling(lr ** 3, W, MIN)
        var = e2 - e1 ** 2
        out["skew"] = np.where(var > 0, (e3 - 3 * e1 * e2 + 2 * e1 ** 3) / np.where(var > 0, var, 1.0) ** 1.5, np.nan)
        qv_a = np.where(P.alive, np.nan_to_num(P.extra["qv"]), np.nan)
        out["vshock"] = np.log1p(fc.rolling(qv_a, 7, 5)) - np.log1p(fc.rolling(qv_a, 90, 60))
        out["size"] = np.log1p(P.adv28)
        lp = np.log(P.px)
        r7 = np.full_like(lp, np.nan)
        r7[7:] = lp[7:] - lp[:-7]
        out["rev7"] = r7
    return out


def compute(ctx: co.Ctx) -> dict:
    P = ctx.P
    F = factors(P)
    ref = P.top_liquid(REF_TOP)
    trials, picks, forms, held = [], [], [], []
    for f in FACTORS:
        q = co.badness(F[f], ref)
        mods = {"filter": co.worst_third(q), "tilt": q}
        for b in co.BOOKS:
            base_live = ctx.base35[(b, "live")]
            runs = {}
            for form, M in mods.items():
                runs[form] = co.apply(ctx, b, "live", form, M)
                t = co.trial(ctx, NAME, f"{f} {form}", b, "mod", runs[form], base_live)
                trials.append(t)
                forms.append({"factor": f, "book": co.ORIGINAL[b], "form": form, "is": t.is_sr,
                              "book_is": co.sharpe(base_live[ctx.ins]), "oos": t.oos_sr,
                              "book_oos": co.sharpe(base_live[ctx.oos])})
            best = max(mods, key=lambda k: co.sharpe(co.net(runs[k][0], runs[k][1], co.COST)[ctx.ins]))
            M = mods[best]
            lrun = co.apply(ctx, b, "live", best, co.late(M))
            trun = co.apply(ctx, b, "twin", best, M)
            key = f"{f} {best}"
            trials += [co.trial(ctx, NAME, key + " · late", b, "late", lrun, base_live),
                       co.trial(ctx, NAME, key + " · twin", b, "twin", trun, ctx.base35[(b, "twin")])]
            picks.append(co.pick_row(ctx, b, key, runs[best], lrun, trun, factor=f, form=best))
            hw = ctx.base[(b, "live")][3]
            inv = (hw > 0).any(1) & ctx.oos
            held.append({"factor": f, "book": co.ORIGINAL[b],
                         "days_holding_worst_third_pct": 100 * float(((hw > 0) & mods["filter"]).any(1)[inv].mean())
                         if inv.any() else 0.0,
                         "held_weight_ranked_pct": 100 * float(np.where(np.isfinite(q), hw, 0).sum(1)[inv].mean()
                                                               / np.maximum(hw.sum(1)[inv].mean(), 1e-12))
                         if inv.any() else 0.0})
        print(f"  {f} done", flush=True)
    return {"trials": trials, "picks": picks, "forms": forms, "held": held}


def write(ctx: co.Ctx, res: dict, fin: dict) -> None:
    picks = res["picks"]
    passes = [r for r in picks if r["passes"]]
    md = ["# Cross-sectional crypto factors as book filters and tilts: results\n",
          f"Generated {datetime.now(timezone.utc).isoformat(timespec='seconds')}. Registered in "
          "`results/crypto_own_prereg.md` before the run. Panel to "
          f"{dc.day_str(ctx.P.days[-1])}; out of sample from 2024-01-01; books at 35 bps, coins Alpaca does not list "
          f"in cash; factors ranked among the {REF_TOP} most liquid eligible coins each day, higher = worse.\n",
          "## Verdict per factor\n"]
    for f in co_factors(picks):
        rows = [r for r in picks if r["factor"] == f]
        killed = all(r["oos"] < r["book_oos"] for r in rows)
        ok = [r for r in rows if r["passes"]]
        txt = ("passes on " + ", ".join(f"{r['book']} ({r['verdict']})" for r in ok)) if ok else \
            ("killed (below the book in all three)" if killed else "fails")
        md.append(f"- **{f}**: {txt}. " + "; ".join(
            f"{r['book']} {r['form']} {r['oos']:.2f} vs {r['book_oos']:.2f}" for r in rows) + ".")
    md.append("")
    md.append(f"{len(passes)} of {len(picks)} factor-book picks pass gates 1 to 5 and 7.\n")
    md.append("## Gates per pick\n")
    md += co.gates_lines(picks)
    md.append("")
    md.append(co.pick_table(picks))
    md.append("\n## Every form (35 bps)\n")
    md.append(dc.table(res["forms"], ["factor", "book", "form", "is", "book_is", "oos", "book_oos"]))
    md.append("\nHow often the books held a coin in a factor's worst third, and the share of their weight the "
              "factor ranks at all (out of sample, days with any position):\n")
    md.append(dc.table(res["held"], ["factor", "book", "days_holding_worst_third_pct", "held_weight_ranked_pct"]))
    md.append("\nThe books alone and gated BTC:\n")
    md.append(co.refs_table(ctx))
    md.append("\n" + co.pool_line(fin) + "\n")
    text = "\n".join(md)
    dc.write_results(NAME, text)
    data = {k: v for k, v in res.items() if k != "trials"}
    data["pool"] = fin["pool"]
    report.write(NAME, text, data)


def co_factors(picks: list[dict]) -> list[str]:
    return [f for f in FACTORS if any(r["factor"] == f for r in picks)]
