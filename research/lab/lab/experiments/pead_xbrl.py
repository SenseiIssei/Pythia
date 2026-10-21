"""Post-earnings announcement drift from XBRL earnings surprises on S&P 500 members.

    PYTHIA_DATA=<data> PYTHIA_REPORTS=<dir>/reports PYTHIA_XBRL_DATA=<xbrl cache> \
        python -m lab.experiments.pead_xbrl

Pre-registered in results/pead_xbrl_prereg.md (committed before this file ran). EPS from
the SEC company facts quality_issuance cached (diluted, else basic and diluted, else
basic), point in time through each 10-Q or 10-K's own accession (EDGAR submissions index:
filing date and period of report). SUE = (EPS_q - EPS_q-4) / std of that difference over
the previous 8 quarters. Top decile by trailing 365-day breakpoints, bought at the open of
the second session after the filing, held 20 or 60 sessions; long-only and top minus
bottom; 5 bps a side plus the SEC fee and TAF (survey_equities.wsim). Out of sample from
2018. Writes results/pead_xbrl.md below the marker and <reports>/pead_xbrl/latest.*.
"""

from __future__ import annotations

import gzip
import json
import math
from datetime import datetime, timezone

import numpy as np
from scipy import stats

from .. import report
from ..equities import edgar, xbrl
from ..equities import books as bk
from . import director_common as dc
from . import round_two as r2
from . import survey_equities as se

NAME = "pead_xbrl"
CONCEPTS = ("EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted", "EarningsPerShareBasic")
Q_DAYS, M9_DAYS, FY_DAYS = (70, 110), (250, 290), (340, 390)
HOLDS = (20, 60)
SEL = (np.datetime64("2011-01-01"), np.datetime64("2018-01-01"))
OOS = SEL[1]
BREAK_DAYS, BREAK_MIN = 365, 100
CAP = 0.10
BPS, BPS_STRESS = 5.0, 10.0
YEAR = bk.YEAR_DAYS


# ---------------------------------------------------------------------------
# EPS and filings
# ---------------------------------------------------------------------------

def _d(s: str) -> np.datetime64:
    return np.datetime64(s[:10], "D")


def eps_facts(cik: int) -> list[tuple]:
    """[(concept rank, start, end, val, accn, filed)] of the EPS concepts, forms 10-Q/10-K and
    their amendments' values left out."""
    f = xbrl.cache_dir() / "companyfacts" / f"CIK{cik:010d}.json.gz"
    if not f.exists():
        return []
    d = json.loads(gzip.decompress(f.read_bytes()).decode("utf-8"))
    g = (d.get("facts") or {}).get("us-gaap") or {}
    out = []
    for rank, c in enumerate(CONCEPTS):
        for v in ((g.get(c) or {}).get("units") or {}).get("USD/shares", []):
            if v.get("val") is None or not v.get("start") or not v.get("end") or not v.get("filed"):
                continue
            if v.get("form") not in ("10-Q", "10-K"):
                continue
            out.append((rank, _d(v["start"]), _d(v["end"]), float(v["val"]), v.get("accn", ""), _d(v["filed"])))
    return out


def filings(cik: int) -> list[tuple]:
    """[(filing date, period of report, accession, form)] of the original 10-Q and 10-K."""
    d = edgar.cache_dir() / "submissions"
    f = d / f"CIK{cik:010d}.json"
    if not f.exists():
        return []
    top = json.loads(f.read_text(encoding="utf-8"))
    fl = top.get("filings") or {}
    tables = [fl.get("recent") or {}]
    for page in fl.get("files") or []:
        p = d / page["name"]
        if p.exists():
            tables.append(json.loads(p.read_text(encoding="utf-8")))
    out = []
    for t in tables:
        forms = t.get("form") or []
        for i, form in enumerate(forms):
            if form not in ("10-Q", "10-K"):
                continue
            rd = (t.get("reportDate") or [""] * len(forms))[i]
            fd = (t.get("filingDate") or [""] * len(forms))[i]
            if rd and fd:
                out.append((_d(fd), _d(rd), t["accessionNumber"][i], form))
    return sorted(set(out))


class Facts:
    """Lookups of one company's EPS facts by duration and period end."""

    def __init__(self, rows: list[tuple]):
        self.rows = rows

    def _cands(self, dur: tuple[int, int], end: np.datetime64, tol: int) -> list[tuple]:
        c = [r for r in self.rows if dur[0] <= (r[2] - r[1]).astype(int) <= dur[1]
             and abs((r[2] - end).astype(int)) <= tol]
        if not c:
            return []
        best = min(r[0] for r in c)
        return [r for r in c if r[0] == best]

    def own(self, dur, end, accn: str, tol: int = 3) -> float | None:
        """Reported in this filing, else the earliest filed."""
        c = self._cands(dur, end, tol)
        same = [r for r in c if r[4] == accn]
        if same:
            return same[0][3]
        return min(c, key=lambda r: r[5])[3] if c else None

    def asof(self, dur, end, accn: str, filed: np.datetime64, tol: int = 20) -> float | None:
        """Reported in this filing, else the latest filed on or before `filed`."""
        c = self._cands(dur, end, tol)
        same = [r for r in c if r[4] == accn]
        if same:
            return same[0][3]
        before = [r for r in c if r[5] <= filed]
        return max(before, key=lambda r: r[5])[3] if before else None


def quarter_eps(F: Facts, e: np.datetime64, accn: str, filed: np.datetime64, form: str,
                prior: bool) -> tuple[float | None, bool]:
    """EPS of the quarter ending e (prior=False, as the filing reports it) or of the quarter a
    year earlier (prior=True, the comparative, else as known at the filing); Q4 of a 10-K is
    derived from the year minus nine months when no quarter value exists. Returns (eps, derived)."""
    end = e - np.timedelta64(365, "D") if prior else e
    q = F.asof(Q_DAYS, end, accn, filed) if prior else F.own(Q_DAYS, end, accn)
    if q is not None:
        return q, False
    if form != "10-K":
        return None, False
    fy = F.asof(FY_DAYS, end, accn, filed) if prior else F.own(FY_DAYS, end, accn)
    m9 = F.asof(M9_DAYS, end - np.timedelta64(91, "D"), accn, filed, tol=25)
    if fy is None or m9 is None:
        return None, False
    return fy - m9, True


def sue_events(cik: int) -> list[dict]:
    """Every original 10-Q/10-K of the company with D and, where 8 earlier quarters allow,
    SUE; each D computed at its own filing."""
    F = Facts(eps_facts(cik))
    if not F.rows:
        return []
    out, seen = [], set()
    for filed, e, accn, form in filings(cik):
        if e in seen:
            continue          # the first original filing for a period only
        seen.add(e)
        now, der = quarter_eps(F, e, accn, filed, form, False)
        then, der0 = quarter_eps(F, e, accn, filed, form, True)
        if now is None or then is None:
            continue
        out.append({"cik": cik, "filed": filed, "end": e, "form": form, "D": now - then, "eps": now,
                    "derived": der or der0})
    out.sort(key=lambda r: r["end"])
    for i, r in enumerate(out):
        prev = [x["D"] for x in out[:i] if x["end"] < r["end"] and (r["end"] - x["end"]).astype(int) <= 750][-8:]
        sd = float(np.std(prev, ddof=1)) if len(prev) >= 6 else 0.0
        r["sue"] = r["D"] / sd if sd > 0 else math.nan
    return out


# ---------------------------------------------------------------------------
# Events on the panel
# ---------------------------------------------------------------------------

def events(ctx: se.Ctx) -> list[dict]:
    """Events with a SUE on the panel: session f (first on or after the filing), the column
    (the CIK's most liquid listing that is in the universe on f)."""
    S = ctx.S
    by_cik: dict[int, list[int]] = {}
    for j, n in enumerate(S.names):
        c = ctx.cik.get(n)
        if c is not None:
            by_cik.setdefault(int(c), []).append(j)
    out = []
    for c, cols in sorted(by_cik.items()):
        for ev in sue_events(c):
            if not np.isfinite(ev["sue"]):
                continue
            f = int(np.searchsorted(S.dates, ev["filed"]))
            if f + 2 >= S.T:
                continue
            ok = [j for j in cols if ctx.ok[f, j]]
            if not ok:
                continue
            j = max(ok, key=lambda j: np.nan_to_num(ctx.X.dv50[f, j]))
            out.append({**ev, "f": f, "j": j})
    out.sort(key=lambda r: (r["f"], r["j"]))
    return out


def deciles(evs: list[dict], dates: np.ndarray) -> None:
    """r['dec'] = 'top' / 'bottom' / '' against the SUEs of the universe's events filed in
    the BREAK_DAYS before (at least BREAK_MIN); r['decile'] 1..10 for the report."""
    filed = np.array([r["filed"] for r in evs], dtype="datetime64[D]")
    sue = np.array([r["sue"] for r in evs])
    for i, r in enumerate(evs):
        m = (filed < r["filed"]) & (filed >= r["filed"] - np.timedelta64(BREAK_DAYS, "D"))
        r["dec"], r["decile"] = "", 0
        if m.sum() < BREAK_MIN:
            continue
        qs = np.quantile(sue[m], np.linspace(0.1, 0.9, 9))
        r["decile"] = int(np.searchsorted(qs, r["sue"], side="right")) + 1
        r["dec"] = "top" if r["sue"] > qs[-1] else ("bottom" if r["sue"] < qs[0] else "")


def targets(evs: list[dict], side: str, H: int, T: int, N: int) -> dict[int, np.ndarray]:
    """Decisions at the close of t for the open of t+1 (wsim, lag 1): the active set on
    session s is every event of `side` with f+2 <= s < f+2+H, equal weight capped at CAP;
    a decision only where the set changes."""
    act = [set() for _ in range(T + 1)]
    for r in evs:
        if r["dec"] != side:
            continue
        a, b = r["f"] + 2, min(r["f"] + 2 + H, T)
        for s in range(a, b):
            act[s].add(r["j"])
    out = {}
    for t in range(T - 1):
        nxt, cur = act[t + 1], act[t]
        if nxt != cur:
            w = np.zeros(N)
            if nxt:
                w[list(nxt)] = min(1.0 / len(nxt), CAP)
            out[t] = w
    return out


def excess(ctx: se.Ctx, evs: list[dict], ew: np.ndarray, H: int) -> np.ndarray:
    """Each event's open-to-open return from f+2 over H sessions minus the equal weight's."""
    R = ctx.S.r_oo()
    out = np.full(len(evs), np.nan)
    for i, r in enumerate(evs):
        a, b = r["f"] + 2, r["f"] + 2 + H
        if b > ctx.S.T:
            continue
        x = R[a:b, r["j"]]
        if not np.isfinite(x).all():
            x = np.nan_to_num(x)
        out[i] = float(np.prod(1 + x) - np.prod(1 + np.nan_to_num(ew[a:b])))
    return out


# ---------------------------------------------------------------------------
# The study
# ---------------------------------------------------------------------------

def main() -> None:
    ctx = se.load_ctx()
    S = ctx.S
    print("panel loaded", flush=True)
    evs = events(ctx)
    deciles(evs, S.dates)
    print(f"{len(evs)} events with a SUE", flush=True)
    ew = se.equal_weight(ctx, "cik", ctx.has_cik)
    ew_late = se.equal_weight(ctx, "cik", ctx.has_cik, lag=2)
    ew2 = se.wsim(S, se.ew_targets(ctx, ctx.has_cik)).net(2 * BPS)
    sel = (S.dates >= SEL[0]) & (S.dates < SEL[1])
    oos = S.dates >= OOS
    yrs = bk.years(S.dates)
    spy = ctx.spy

    rows, store = [], {}
    for H in HOLDS:
        lt = targets(evs, "top", H, S.T, S.N)
        bt = targets(evs, "bottom", H, S.T, S.N)
        sim = se.wsim(S, lt)
        sim_late = se.wsim(S, lt, lag=2)
        x, x2, xl = sim.net(BPS), sim.net(BPS_STRESS), sim_late.net(BPS)
        act = x - sim.expo * ew
        act2 = x2 - sim.expo * ew2
        actl = xl - sim_late.expo * ew_late
        ls = se.ls_series(S, lt, bt, BPS)
        ls2 = se.ls_series(S, lt, bt, BPS_STRESS)
        lsl = se.ls_series(S, lt, bt, BPS, lag=2)
        store[H] = {"x": x, "act": act, "act2": act2, "actl": actl, "ls": ls, "ls2": ls2, "lsl": lsl, "sim": sim}
        expo = sim.expo[oos]
        rows.append({"trial": f"long top decile · {H} sessions", "form": "long", "H": H,
                     "sel": se.sharpe(act[sel]), "oos": se.sharpe(act[oos]), "oos_2x": se.sharpe(act2[oos]),
                     "oos_late": se.sharpe(actl[oos]), "book_sel": se.sharpe(x[sel]), "book_oos": se.sharpe(x[oos]),
                     "book_cagr_pct": bk.perf(x[oos])["cagr"] * 100, "book_dd_pct": bk.perf(x[oos])["max_dd"] * 100,
                     "invested_pct": float((expo > 0).mean() * 100), "expo_mean": float(expo.mean()),
                     "turnover_yr": float(sim.tov[oos].sum() / (oos.sum() / YEAR))})
        rows.append({"trial": f"top minus bottom decile · {H} sessions", "form": "ls", "H": H,
                     "sel": se.sharpe(ls[sel]), "oos": se.sharpe(ls[oos]), "oos_2x": se.sharpe(ls2[oos]),
                     "oos_late": se.sharpe(lsl[oos]), "book_sel": math.nan, "book_oos": math.nan,
                     "book_cagr_pct": bk.perf(ls[oos])["cagr"] * 100, "book_dd_pct": bk.perf(ls[oos])["max_dd"] * 100,
                     "invested_pct": math.nan, "expo_mean": math.nan, "turnover_yr": math.nan})
        print(rows[-2]["trial"], round(rows[-2]["sel"], 2), round(rows[-2]["oos"], 2), flush=True)
        print(rows[-1]["trial"], round(rows[-1]["sel"], 2), round(rows[-1]["oos"], 2), flush=True)

    pl_ = r2.pool([r["oos"] for r in rows], year=YEAR)
    for r in rows:
        z = store[r["H"]]
        r["deflated_p"] = dc.deflated((z["act"] if r["form"] == "long" else z["ls"])[oos], pl_)

    res: dict = {"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "rows": rows, "pool": pl_,
                 "panel_to": str(S.dates[-1]), "events": len(evs),
                 "derived_share": float(np.mean([r["derived"] for r in evs])) if evs else 0.0,
                 "ew_oos": se.sharpe(ew[oos]), "spy_oos": se.sharpe(spy[oos])}
    # Long-only pick and gates.
    lp = max((r for r in rows if r["form"] == "long"), key=lambda r: r["sel"])
    z = store[lp["H"]]
    bt_ = se.boot_sharpe(z["act"][oos])
    ay = se.per_year(S.dates, z["act"], oos)
    res["long"] = {"pick": lp["trial"], "boot": bt_, "active_by_year": ay, "deflated_p": lp["deflated_p"],
                   "gates": {"1 IR above 0.3": lp["oos"] > 0.3,
                             "2 bootstrap 5 % bound of the IR above 0": bt_["p05"] > 0,
                             "3 IR above 0 with costs doubled and a day late": lp["oos_2x"] > 0 and lp["oos_late"] > 0,
                             "4 active return positive in more than half the years":
                                 sum(v > 0 for v in ay.values()) > len(ay) / 2,
                             "5 the book's Sharpe above the equal weight's": lp["book_oos"] > res["ew_oos"]}}
    res["long"]["passed"] = all(res["long"]["gates"].values())
    res["long"]["killed"] = lp["oos"] < 0.1
    res["long"]["confirmed"] = res["long"]["passed"] and lp["deflated_p"] > 0.95
    # Long/short pick and gates.
    sp = max((r for r in rows if r["form"] == "ls"), key=lambda r: r["sel"])
    z = store[sp["H"]]
    bs = se.boot_sharpe(z["ls"][oos])
    sy = se.per_year(S.dates, z["ls"], oos)
    res["ls"] = {"pick": sp["trial"], "boot": bs, "by_year": sy, "deflated_p": sp["deflated_p"],
                 "gates": {"1 Sharpe above 0.5 at 5 bps and above 0 at 10 bps": sp["oos"] > 0.5 and sp["oos_2x"] > 0,
                           "2 bootstrap 5 % bound above 0": bs["p05"] > 0,
                           "3 positive in more than half the years": sum(v > 0 for v in sy.values()) > len(sy) / 2,
                           "4 a day late above 0": sp["oos_late"] > 0}}
    res["ls"]["passed"] = all(res["ls"]["gates"].values())
    res["ls"]["confirmed"] = res["ls"]["passed"] and sp["deflated_p"] > 0.95

    # Information: excess returns per decile, IC, coverage.
    fd = S.dates[[r["f"] for r in evs]]
    dec = np.array([r["decile"] for r in evs])
    sue = np.array([r["sue"] for r in evs])
    drift = []
    for H in HOLDS:
        ex = excess(ctx, evs, ew, H)
        for lab, m in (("2011-2017", (fd >= SEL[0]) & (fd < SEL[1])), ("from 2018", fd >= OOS)):
            row = {"H": H, "window": lab}
            for k in range(1, 11):
                v = ex[m & (dec == k)]
                v = v[np.isfinite(v)]
                row[f"d{k}"] = float(v.mean() * 100) if len(v) else math.nan
            ok = m & np.isfinite(ex) & np.isfinite(sue)
            q = fd.astype("datetime64[M]").astype(np.int64) // 3
            ics = []
            for qq in np.unique(q[ok]):
                mm = ok & (q == qq)
                if mm.sum() >= 30:
                    ics.append(stats.spearmanr(sue[mm], ex[mm])[0])
            a = np.array(ics)
            row["ic"] = float(a.mean()) if len(a) else math.nan
            row["ic_t"] = float(a.mean() / a.std(ddof=1) * math.sqrt(len(a))) if len(a) > 2 else math.nan
            row["events"] = int(ok.sum())
            drift.append(row)
    res["drift"] = drift
    ys = bk.years(fd)
    res["coverage"] = [{"year": int(y), "events": int((ys == y).sum()),
                        "companies": int(len({evs[i]["cik"] for i in np.flatnonzero(ys == y)})),
                        "top": int(sum(1 for i in np.flatnonzero(ys == y) if evs[i]["dec"] == "top"))}
                       for y in np.unique(ys)]
    lag = np.array([(r["filed"] - r["end"]).astype(int) for r in evs])
    res["filing_lag_days"] = float(np.median(lag)) if len(lag) else math.nan
    write(res)


def write(res: dict) -> None:
    lo, sh = res["long"], res["ls"]
    lp = next(r for r in res["rows"] if r["trial"] == lo["pick"])
    sp = next(r for r in res["rows"] if r["trial"] == sh["pick"])
    lv = ("**Pass" + (", confirmed.**" if lo["confirmed"] else ", experimental (fails deflation).**")) if lo["passed"] \
        else ("**Kill.**" if lo["killed"] else "**Fail.**")
    sv = ("**Pass" + (", confirmed.**" if sh["confirmed"] else ", experimental (fails deflation).**")) if sh["passed"] \
        else "**Fail.**"
    md = ["# Post-earnings drift from XBRL surprises: results\n",
          f"Generated {res['generated']}. Registered in `results/pead_xbrl_prereg.md` before the run.\n",
          f"Point-in-time S&P 500 members with a CIK, sessions to {res['panel_to']}; {res['events']:,} 10-Q and 10-K "
          f"filings with a SUE ({res['derived_share'] * 100:.0f} % with a Q4 derived from the year minus nine months); "
          f"median {res['filing_lag_days']:.0f} days from period end to filing. Entry at the open of the second session "
          "after the filing. Selection 2011 to 2017, out of sample from 2018. 5 bps a side plus SEC fee and TAF; "
          f"the universe's equal weight makes Sharpe {res['ew_oos']:.2f} out of sample, SPY {res['spy_oos']:.2f}.\n",
          f"## Long-only: {lv} Pick: **{lo['pick']}**\n"]
    md += [f"- {k}: {'yes' if ok else 'no'}" for k, ok in lo["gates"].items()]
    md.append(f"\nIR {lp['oos']:.2f} out of sample (bootstrap band {lo['boot']['p05']:.2f} to {lo['boot']['p95']:.2f}), "
              f"{lp['oos_2x']:.2f} with costs doubled, {lp['oos_late']:.2f} a day late; the book's Sharpe "
              f"{lp['book_oos']:.2f}, {lp['book_cagr_pct']:.1f} % a year, drawdown {lp['book_dd_pct']:.0f} %, invested on "
              f"{lp['invested_pct']:.0f} % of sessions. Deflated p {lo['deflated_p']:.4f}. Active return by year: "
              + ", ".join(f"{y} {v * 100:+.1f} %" for y, v in lo["active_by_year"].items()) + ".\n")
    md.append(f"## Top minus bottom decile: {sv} Pick: **{sh['pick']}**\n")
    md += [f"- {k}: {'yes' if ok else 'no'}" for k, ok in sh["gates"].items()]
    md.append(f"\nSharpe {sp['oos']:.2f} out of sample (bootstrap band {sh['boot']['p05']:.2f} to "
              f"{sh['boot']['p95']:.2f}), {sp['oos_2x']:.2f} at 10 bps, {sp['oos_late']:.2f} a day late, drawdown "
              f"{sp['book_dd_pct']:.0f} %. Deflated p {sh['deflated_p']:.4f}. By year: "
              + ", ".join(f"{y} {v * 100:+.1f} %" for y, v in sh["by_year"].items()) + ".\n")
    md.append("## Every trial\n")
    md.append(dc.table(res["rows"], ["trial", "sel", "oos", "oos_2x", "oos_late", "book_sel", "book_oos",
                                     "book_cagr_pct", "book_dd_pct", "invested_pct", "turnover_yr", "deflated_p"]))
    md.append("\nLong rows: `sel` and `oos` are the IR of the active return (the book minus its invested share times "
              "the equal weight), `book_*` the book itself; long/short rows: the book's Sharpe. Annualised over 252 "
              "sessions.\n")
    md.append("\n## Drift by SUE decile (information only)\n")
    md.append(dc.table(res["drift"], ["H", "window", "events"] + [f"d{k}" for k in range(1, 11)] + ["ic", "ic_t"]))
    md.append("\nMean return of each decile's events from the open of f+2 over H sessions minus the equal weight's, "
              "in %; deciles by the trailing 365-day breakpoints. `ic`: mean quarterly Spearman of SUE with that "
              "excess return, t over quarters.\n")
    md.append("\nCoverage (filings with a SUE on a member with a CIK, by filing year):\n")
    md.append(dc.table(res["coverage"], ["year", "events", "companies", "top"]))
    md.append("\n## Pool\n\n" + r2.pool_line(res["pool"]) + "\n")
    text = "\n".join(md)
    dc.write_results(NAME, text)
    report.write(NAME, text, res)


if __name__ == "__main__":
    main()
