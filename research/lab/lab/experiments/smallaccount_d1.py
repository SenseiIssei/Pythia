"""D1: S1's and S2's pre-registered candidates on the long history, from 2018, with the same costs.

    python -m lab.experiments.smallaccount_d1              the re-run and the overlap checks (Kraken, Yahoo:
                                                           run it under the heavy lock)
    python -m lab.experiments.smallaccount_d1 --offline    without the checks that need the network

S1 and S2 (results/smallaccount_s1.md, smallaccount_s2.md) saw 2020-08 to
2026 only, in sample a bull market and out of sample a mostly rising one. Here
the same candidates, wallets and costs run on the panel with Binance's daily
bars before 2020 (lab.history.load_long_panel: BTC and ETH from 2017-08-17,
SOL from 2020-08-12) and the ETF tokens from their underlying with
S2's drift (SPY and GLD from the lab's copy): one wallet per candidate from the
close of 2017-12-31 (all USDC, the way in paid) to the last ETF close, and the
2024 window again as S2 ran it (a check that the long panel changes nothing
there). No new candidate, no new parameter, nothing tuned: S1's eight as the lab
runs them (daily, Jupiter, 50 EUR) and its two paper picks, S2's eight at 40 EUR.

Per candidate: 2018, March 2020 (the close of 2020-02-29 to that of 2020-03-31)
and 2022 (each from the close before), the whole run with its drawdown and how
long the deepest one lasted (peak to the first close back above it), S2's bar
on the whole run (drawdown under 20 % and CAGR at most 1 point below holding
SPYx) and S1's (CAGR above 0, Sharpe above BTC held, costs under half the gain).
Warm-up: the panel starts 2017-08-17, so BTC's 200-day average exists from
2018-03-04 and 365-day returns from 2018-08-17; a rule that needs them holds
USDC until then. Nothing here trades, signs or holds a key.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from . import fam_common as fc
from . import smallaccount as s1
from . import smallaccount_s2 as s2

NAME = "smallaccount_history_d1"
RESULTS = s1.RESULTS
START = "2017-12-31"                        # the wallets start at this close
PERIODS = {"2018": ("2017-12-31", "2018-12-31"), "2020-03": ("2020-02-29", "2020-03-31"),
           "2022": ("2021-12-31", "2022-12-31")}
S1_CAPITAL, S2_CAPITAL = 50.0, s2.MAIN
S1_PICKS = (("tsmom_top20", 1, 50.0), ("breakout_sol", 3, 100.0))   # S1's two paper books, Jupiter, daily
MARKER = "<!-- generated below by lab.experiments.smallaccount_d1; edit above this line only -->"


def t_of(days: np.ndarray, day: str) -> int:
    """The index of the close on `day` (or the last one before it)."""
    us = int(datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1e6)
    return int(np.searchsorted(days, us, side="right")) - 1


def _day(days: np.ndarray, t: int) -> str:
    return str((days[t] // fc.DAY_US).astype("datetime64[D]"))


def drawdown(eq: np.ndarray, days: np.ndarray) -> dict:
    """The deepest drawdown of a curve: depth, peak, trough, the first close back at the peak (None: not yet)
    and its length in days from the peak (to the end when not recovered)."""
    if len(eq) == 0:
        return {"max_dd": 0.0, "peak": None, "trough": None, "recovered": None, "days": 0}
    peak = np.maximum.accumulate(eq)
    dd = 1 - eq / peak
    tr = int(np.argmax(dd))
    pk = int(np.argmax(eq[: tr + 1]))
    back = np.flatnonzero(eq[tr:] >= eq[pk])
    rec = tr + int(back[0]) if len(back) and dd[tr] > 0 else None
    return {"max_dd": float(dd[tr]), "peak": _day(days, pk), "trough": _day(days, tr),
            "recovered": _day(days, rec) if rec is not None else None,
            "days": int(((rec if rec is not None else len(eq) - 1) - pk))}


def periods(eq: np.ndarray, days: np.ndarray, t0: int, capital: float) -> dict[str, dict]:
    """Return and drawdown inside each period, from the close before it; eq starts at the close of t0."""
    out = {}
    for k, (a, b) in PERIODS.items():
        i, j = t_of(days, a) - t0, t_of(days, b) - t0
        if i < 0 or j <= i or j >= len(eq):
            continue
        start = eq[i] if i > 0 else capital
        seg = np.r_[start, eq[i + 1: j + 1]]
        out[k] = {"ret": float(eq[j] / start - 1), "max_dd": float((1 - seg / np.maximum.accumulate(seg)).max())}
    return out


def summary(res: dict, capital: float, days: np.ndarray, t0: int) -> dict:
    eq = res["equity"]
    m = s1.measure(res, capital)
    return {**{k: m[k] for k in ("cagr", "max_dd", "sharpe", "end_eur", "costs_eur", "cost_share", "orders_yr")},
            "dd": drawdown(eq, days[t0: t0 + len(eq)]), "periods": periods(eq, days, t0, capital)}


def end_index(P: fc.Panel, etf: dict) -> int:
    return s2.windows(P, etf)["oos"][1]


def run_s1(P: fc.Panel, vs: dict, t0: int, t1: int) -> dict[str, dict]:
    """S1's candidates as the lab runs them (daily, Jupiter, 50 EUR) and its two paper picks."""
    jup = vs["jupiter"]
    todo = [(k, None, S1_CAPITAL) for k in s1.CANDIDATES] + list(S1_PICKS)
    out = {}
    oos = s1._t(P, s1.OOS_FROM)
    for key, n, cap in todo:
        W = s1.candidate(P, key, n)
        slots = n or s1.ORIGINAL_N[key]
        label = s1.variant_label(key, n, "daily") + f" · {cap:g} EUR"
        r = s1.simulate(P, W, jup, cap, t0, t1, 1, slots)
        row = {"key": key, "n": slots, "capital": cap, "label": label, **summary(r, cap, P.days, t0)}
        row["s1_window"] = s1.measure(s1.simulate(P, W, jup, cap, oos, t1, 1, slots), cap)
        out[label] = row
        print(f"  S1 {label}", flush=True)
    hold = next(r for r in out.values() if r["key"] == "btc_hold")
    for r in out.values():
        r["s1_bar"] = (r["key"] != "btc_hold" and r["cagr"] > 0 and r["sharpe"] > hold["sharpe"]
                       and r["cost_share"] is not None and r["cost_share"] < s1.DOMINATE)
    return out


def run_s2(P: fc.Panel, etf: dict, v: s2.S2Venue, drifts: dict, t0: int, t1: int) -> dict[str, dict]:
    """S2's eight at 40 EUR over the long run, and the 2024 window as S2 ran it."""
    m = s2.market(P, etf, v.eurusd, drifts)
    oos = s1._t(P, s2.OOS_FROM)
    out, rets = {}, {}
    for k in s2.CANDIDATES:
        keys, W, due, rw = s2.candidate(k, m, P)
        px = s2.coin_prices(k, keys, m, P, v.eurusd)
        r = s2.simulate(px, keys, W, due, rw, m.sol_eur, v, S2_CAPITAL, t0, t1, s2.SLOTS[k])
        rets[k] = s2.daily_returns(r["equity"], S2_CAPITAL)
        o = s2.simulate(px, keys, W, due, rw, m.sol_eur, v, S2_CAPITAL, oos, t1, s2.SLOTS[k])
        out[k] = {"key": k, "capital": S2_CAPITAL, **summary(r, S2_CAPITAL, P.days, t0),
                  "s2_window": s1.measure(o, S2_CAPITAL)}
        print(f"  S2 {k}", flush=True)
    b = out["spy_hold"]
    for k, r in out.items():
        r["safe"] = r["max_dd"] < s2.SAFE_DD
        r["matches"] = r["cagr"] >= b["cagr"] - s2.MATCH_SLACK
        r["passes"] = k not in s2.REFERENCES and r["safe"] and r["matches"]
        if k != "spy_hold":
            r["boot"] = s2.bootstrap(rets[k], rets["spy_hold"])
    return out


# ---------------------------------------------------------------- the report

def _pct(v, d: int = 1) -> str:
    return "n/a" if v is None else f"{v * 100:.{d}f} %"


def _period_cells(r: dict) -> dict:
    p = r["periods"]
    return {k: (f"{_pct(p[k]['ret'])} (DD {_pct(p[k]['max_dd'], 0)})" if k in p else "n/a") for k in PERIODS}


def _dd_cell(r: dict) -> str:
    d = r["dd"]
    end = d["recovered"] or "not yet"
    return f"{_pct(d['max_dd'])}, {d['peak']} to {end} ({d['days']} days)"


def markdown(out: dict) -> str:
    w = out["window"]
    md = [f"Generated {out['generated']}. One wallet per candidate from the close of {w[0]} to {w[1]}, "
          f"EUR/USD {out['eurusd']:.4f}, S2's drift a year: "
          + ", ".join(f"{k} {x * 100:+.2f} %" for k, x in out["drifts"].items()) + ".\n"]
    md.append("## 1. The data\n")
    cov = out["coverage"]
    t = [{"series": c["pair"], "first": c["first"], "last": c["last"], "days": c["days"]} for c in cov]
    t += [{"series": f"{s} (etf/daily)", "first": f, "last": out["etf_last"][s], "days": ""} for s, f in
          out["etf_first"].items()]
    if out.get("checks", {}).get("paxg_first"):
        t.append({"series": "PAXGUSDT (Binance, checks only)", "first": out["checks"]["paxg_first"], "last": "",
                  "days": ""})
    md.append(fc.table(t, ["series", "first", "last", "days"]))
    md.append(f"{out['pairs_before_2020']} pair segments have daily bars before 2020 (delisted pairs included).\n")
    ch = out.get("checks") or {}
    if ch:
        md.append("## 2. Overlaps (closes more than 0.5 % apart)\n")
        t = []
        for name, label in (("binance_vs_panel", "Binance daily vs the panel"),
                            ("kraken_vs_binance", "Kraken USD vs Binance USDT"),
                            ("yahoo_vs_copy", "Yahoo now vs etf/daily")):
            for s, v in (ch.get(name) or {}).items():
                if name == "binance_vs_panel" and s not in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
                    continue
                t.append({"check": label, "series": s, "days": v["days"], "from": v["first"], "to": v["last"],
                          "over 0.5 %": v["over"], "largest": _pct(v["max_abs"], 2)})
        bp = ch.get("binance_vs_panel") or {}
        rest = [v for s, v in bp.items() if s not in ("BTCUSDT", "ETHUSDT", "SOLUSDT")]
        if rest:
            t.append({"check": "Binance daily vs the panel", "series": f"{len(rest)} other pairs, 2020-01 to 03",
                      "days": sum(v["days"] for v in rest), "from": "", "to": "",
                      "over 0.5 %": sum(v["over"] for v in rest),
                      "largest": _pct(max(v["max_abs"] for v in rest), 2)})
        md.append(fc.table(t, list(t[0])) if t else "none\n")
        off = []
        for name in ("binance_vs_panel", "kraken_vs_binance", "yahoo_vs_copy"):
            for s, v in (ch.get(name) or {}).items():
                off += [{"check": name, "series": s, "day": x["day"], "a": f"{x['a']:.4f}", "b": f"{x['b']:.4f}",
                         "diff": _pct(x["diff"], 2)} for x in v["rows"]]
        if off:
            off.sort(key=lambda x: -abs(float(x["diff"].split()[0])))
            md.append(f"Every close more than 0.5 % apart ({len(off)}; the first 40 by size, all in "
                      f"reports/{NAME}/latest.json; a is the first source of the check):\n")
            md.append(fc.table(off[:40], list(off[0])))
        pg = ch.get("paxg_vs_gld") or {}
        if pg.get("days", 0) >= 20:
            md.append(f"PAXG against GLD ({pg['first']} to {pg['last']}, {pg['days']} days): tracking error "
                      f"{_pct(pg['te_yr'])} a year, largest gap around the median ratio {_pct(pg['max_abs'])}, "
                      f"{pg['over_2pct']} days over 2 %.\n")
    md.append("## 3. S2's candidates at 40 EUR (S2's wallet, Jupiter, Sender tip, 5 USDC minimum)\n")
    t = []
    for k, r in out["s2"].items():
        t.append({"candidate": k, **_period_cells(r), "CAGR": _pct(r["cagr"]), "Sharpe": f"{r['sharpe']:.2f}",
                  "deepest drawdown": _dd_cell(r), "end EUR": f"{r['end_eur']:.2f}",
                  "bar": "reference" if k in s2.REFERENCES else ("passes" if r["passes"] else
                                                                  ("too deep" if not r["safe"] else "behind")),
                  "S2's window (2024 on)": f"{_pct(r['s2_window']['cagr'])} / {_pct(r['s2_window']['max_dd'])}"})
    md.append(fc.table(t, list(t[0])) if t else "none\n")
    md.append("Each period: the return from the close before it, in brackets the drawdown inside it. Bar: drawdown "
              "under 20 % and CAGR at least holding SPYx's minus 1 point over the whole run. S2's window: CAGR / "
              "drawdown from 2024 as S2 measured it, on the long panel.\n")
    t = []
    for k, r in out["s2"].items():
        b = r.get("boot")
        if b:
            t.append({"candidate": k, "CAGR minus SPYx": _pct(r["cagr"] - out["s2"]["spy_hold"]["cagr"]),
                      "band 5 to 95 %": f"{_pct(b['diff_p05'])} to {_pct(b['diff_p95'])}",
                      "draws above": _pct(b["diff_above_0"], 0)})
    md.append(fc.table(t, list(t[0])) if t else "none\n")
    md.append("## 4. S1's candidates (daily, Jupiter, 50 EUR, and the two paper picks)\n")
    t = []
    for r in out["s1"].values():
        t.append({"candidate": r["label"], **_period_cells(r), "CAGR": _pct(r["cagr"]), "Sharpe": f"{r['sharpe']:.2f}",
                  "deepest drawdown": _dd_cell(r), "end EUR": f"{r['end_eur']:.2f}",
                  "costs": _pct(r["cost_share"]), "S1's bar": "reference" if r["key"] == "btc_hold" else
                  ("yes" if r["s1_bar"] else "no"),
                  "S1's window (2024 on)": f"{_pct(r['s1_window']['cagr'])} / {_pct(r['s1_window']['max_dd'])}"})
    md.append(fc.table(t, list(t[0])) if t else "none\n")
    md.append("S1's bar over the whole run: CAGR above 0, Sharpe above BTC held, costs under half the gain before "
              "costs. Coins without a Solana mint are cash, as in S1.\n")
    return "\n".join(md) + "\n"


def write(out: dict, path: Path = RESULTS / f"{NAME}.md") -> None:
    head = "# D1: the small-account rules on the long history, from 2018\n\n"
    if path.exists():
        old = path.read_text(encoding="utf-8")
        if MARKER in old:
            head = old.split(MARKER)[0]
    path.write_text(head + MARKER + "\n\n" + markdown(out), encoding="utf-8")


def main() -> int:
    from .. import history
    offline = "--offline" in sys.argv
    t_start = time.time()
    frame = history.long_frame(fetch=not offline)
    P = fc.panel_from(frame)
    etf = s2.load_etf()
    snap = s2.load_snapshot()
    v = s2.venue(snap=snap)
    drifts = s2.drifts_from(snap, s2.tracking())
    vs = s1.venues()
    t0, t1 = t_of(P.days, START), end_index(P, etf)
    out = {"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "window": [_day(P.days, t0), _day(P.days, t1)], "eurusd": v.eurusd, "drifts": drifts,
           "coverage": history.coverage(frame), "pairs_before_2020": history.pairs_before(frame),
           "etf_first": {s: str(e[0][0]) for s, e in s2.load_etf(history.ETFS).items()},
           "etf_last": {s: str(e[0][-1]) for s, e in s2.load_etf(history.ETFS).items()}}
    out["s2"] = run_s2(P, etf, v, drifts, t0, t1)
    out["s1"] = run_s1(P, vs, t0, t1)
    out["checks"] = {} if offline else history.check(verbose=False)
    out["seconds"] = round(time.time() - t_start)
    from .. import report
    d = report.REPORTS / NAME
    d.mkdir(parents=True, exist_ok=True)
    (d / "latest.json").write_text(json.dumps(out, indent=1, default=float), encoding="utf-8")
    write(out)
    print(f"done in {out['seconds']} s; S2 bar {[k for k, r in out['s2'].items() if r['passes']]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
