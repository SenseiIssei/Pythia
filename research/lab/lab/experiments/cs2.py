"""W8: the CS2 skins market. What the collected data says so far.

  python -m lab.experiments.cs2           the research report (also written daily by lab.cs2.run)

Sections: how much history there is; the cross-market spread between
Skinport and Steam net of fees; momentum or reversion; cases by age and
around drop pool events; the 7 and 30-day forecaster (bootstrap now,
walk-forward once there is history); the paper portfolio. Every number but
the paper portfolio's is a backtest or an in-sample fit, and the report says
how short the history behind it is.
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from pathlib import Path

import polars as pl

from .. import report
from ..collect.cs2 import load_watchlist
from ..cs2 import book, market, model


def _p(v, digits: int = 1) -> str:
    return "n/a" if v is None else f"{v * 100:+.{digits}f} %"


def _days(n: int) -> str:
    return f"{n} day" if n == 1 else f"{n} days"


def _n(v, digits: int = 3) -> str:
    return "n/a" if v is None else f"{v:.{digits}f}"


def build(root: Path | None, today: date, snap: pl.DataFrame, meta: dict, mx: dict | None) -> tuple[str, dict]:
    skin = market.daily_skinport(root)
    steam = market.daily_steam(root)
    days = int(skin["date"].n_unique()) if not skin.is_empty() else 0
    first = str(skin["date"].min()) if days else "none"
    spread = model.spread_study(skin, steam)
    cases = model.case_study(snap, today)
    events = model.event_study(mx, load_watchlist().get("events") or [])
    boot = meta.get("bootstrap") or {}
    wf = meta.get("walk_forward") or {}
    j = book.read_journal(root)
    st = book.load_state(root)
    eq = float(j[-1]["equity"]) if j else book.START_EQUITY

    b7, b30 = boot.get("h7") or {}, boot.get("h30") or {}
    w7, w30 = wf.get("h7") or {}, wf.get("h30") or {}
    if w7.get("status") == "ok":
        verdict = (f"Walk-forward 7d rank IC {_n(w7.get('ic_independent'))} (t {_n(w7.get('ic_t'), 1)}) over "
                   f"{w7.get('independent_periods')} periods; top decile {_p(w7.get('top_decile_net_per_trade'))} per trade after fees.")
    elif b7.get("status") == "ok":
        verdict = (f"Too early: {_days(days)} of history. Bootstrap (one snapshot, cross-sectional): 7d rank IC "
                   f"{_n(b7.get('ic'))}, momentum alone {_n(b7.get('ic_momentum_alone'))}.")
    else:
        verdict = f"Too early: {_days(days)} of history and no usable bootstrap fit."

    L = [f"# CS2 skins market ({today.isoformat()})", "",
         "**Read this first.** Paper only: nothing here buys or sells, and nothing will "
         "(automated trading on Steam or a skin marketplace breaks their terms). "
         f"History collected so far: **{_days(days)}** (first {first}). The bootstrap numbers come from one "
         "snapshot of Skinport's 90-day sales windows, cross-validated across items, so they are an "
         "in-sample cross-section, not a time-series backtest. The walk-forward numbers are backtests on the "
         "collector's own history and appear once there is enough of it. The paper portfolio is the only "
         "forward evidence, and it is play money.", "",
         f"**Verdict:** {verdict}", "",
         "## Data", "",
         f"- Skinport items in the latest snapshot: {snap.height}; with sales in all three windows: "
         f"{b7.get('n', 'n/a')}",
         f"- Steam price rows: {steam.height if not steam.is_empty() else 0} over "
         f"{steam['date'].n_unique() if not steam.is_empty() else 0} days",
         f"- Daily panel for the walk-forward model: {_days(wf.get('days', 0))}, {wf.get('items', 0)} liquid items", "",
         "## 1. Spread between Skinport and Steam, net of fees", "",
         "Fees: Steam keeps about 15 % of what the seller gets (5 % Steam, 10 % CS2, at least a cent each) and pays "
         f"in wallet funds that cannot be withdrawn; Skinport keeps {market.SKINPORT_SALE_FEE:.0%} of the sale and pays cash. "
         "Both routes undercut the other side's lowest ask by a cent.", ""]
    if spread.get("status") == "ok":
        L += [f"- Rows (item-days with both prices): {spread['rows']} over {spread['days']} days; items today {spread['items_today']}",
              f"- Steam's lowest ask over Skinport's, median today: {_p(spread['steam_premium_median'])}",
              f"- Skinport to Steam after fees, median today: {_p(spread['to_steam_median'])}; positive in "
              f"{spread['share_to_steam_positive']:.1%} of item-days (Steam wallet funds, not cash)",
              f"- Steam to Skinport after fees, median today: {_p(spread['to_skinport_median'])}; positive in "
              f"{spread['share_to_skinport_positive']:.1%} of item-days (cash, after a 7-day trade lock)"]
        d = spread.get("drift")
        L += [f"- Drift: median |z| of today's Steam/Skinport ratio against its own history {_n(d['median_abs_z'], 2)} "
              f"over {d['items']} items; mean daily change of the log ratio {_n(d['mean_daily_change_of_log_ratio'], 5)}"
              if d else "- Drift: needs 14 days of both prices."]
        L += ["", report.table([{k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()}
                                for r in spread["best_today"]],
                               ["name", "min_price", "steam_ask", "to_steam", "to_skinport", "steam_volume"])]
    else:
        L += [f"- {spread.get('status')}"]
        col = market.read_json(market.cs2_root(root) / "collector.json") or {}
        if col.get("steam_requested") is not None:
            L += [f"- Steam in the last collector run ({col.get('at')}): {col.get('steam_ok', 0)} of "
                  f"{col.get('steam_requested')} prices"
                  + (f"; {'; '.join(col.get('errors') or [])}" if col.get("errors") else "")]
    L += ["", "## 2. Momentum or reversion", "",
          "Bootstrap: does the change from the 30-90 day average to the 7-30 day average predict the change to the "
          "last 7 days? Positive rank IC is momentum, negative is reversion. Caution: the 7-30 day average is in "
          "both the signal and the outcome, so noise in it alone makes the rank IC negative; a reversion number "
          "here is an upper bound on real reversion until the walk-forward test, whose windows do not share days, "
          "confirms it.", "",
          f"- All items: rank IC {_n(b7.get('ic_momentum_alone'))} over {b7.get('n', 'n/a')} items",
          f"- Liquid items (20+ sales in days 7-30): {_n(b7.get('ic_momentum_liquid'))} over {b7.get('liquid_items', 'n/a')}",
          f"- Walk-forward (collected history): {w7.get('status', 'not run')}"]
    L += ["", "## 3. Cases: age, discontinuation, operations", "",
          "Release dates from `lab/collect/cs2_watchlist.json`; drop pool changes and operations are added there as "
          "events when they happen.", ""]
    if cases.get("status") == "ok":
        L += [f"- Cases with sales in all windows: {cases['cases']} ({cases['known_age']} with a known release date)",
              f"- Rank correlation of age with the 90-day change (avg 30-90 to avg 0-7): {_n(cases['ic_age_vs_change'])}", "",
              report.table(cases["by_age"], ["group", "cases", "median_change"])]
    else:
        L += [f"- {cases.get('status')}"]
    L += [f"- Event study (abnormal return from 7 days before to 30 days after, against the median case): "
          f"{events.get('status')}" + (f", mean {_p(events['mean_abnormal'])}" if events.get("mean_abnormal") is not None else "")]
    L += ["", "## 4. Forecaster of 7 and 30-day returns", "",
          "Bootstrap LightGBM, 5-fold across items (same weeks in train and test, so a market-wide move is "
          "shared): 7 days from the earlier windows' change, sales rate and trend, level, category and case age; "
          "30 days from static traits only. The 7-day model sees the 7-30 day average that is also the base of "
          "its outcome, so part of its rank IC is the measurement effect of section 2; the walk-forward test "
          "does not have it.", "",
          report.table([
              {"horizon": "7d bootstrap", "items": b7.get("n"), "rank IC": b7.get("ic"),
               "top decile minus all": b7.get("top_decile_minus_all"), "MSE model": b7.get("mse_model"),
               "MSE zero": b7.get("mse_zero"), "MSE mean": b7.get("mse_mean")},
              {"horizon": "30d bootstrap", "items": b30.get("n"), "rank IC": b30.get("ic"),
               "top decile minus all": b30.get("top_decile_minus_all"), "MSE model": b30.get("mse_model"),
               "MSE zero": b30.get("mse_zero"), "MSE mean": b30.get("mse_mean")},
          ], ["horizon", "items", "rank IC", "top decile minus all", "MSE model", "MSE zero", "MSE mean"]),
          "Walk-forward (monthly expanding refits, training labels end before the test month, rank IC from "
          "non-overlapping periods, top decile held to the horizon after "
          f"{market.round_trip_cost():.0%} round trip):", ""]
    for h, w in ((7, w7), (30, w30)):
        if w.get("status") == "ok":
            L.append(f"- {h}d: from {w['first_oos']}, rank IC {_n(w['ic_independent'])} (t {_n(w['ic_t'], 1)}, "
                     f"{w['independent_periods']} periods), top decile {_p(w['top_decile_net_per_trade'])} net per trade, "
                     f"universe {_p(w['universe_gross_per_period'])} gross, hit rate {_n(w['hit_rate_net'], 2)}")
        else:
            L.append(f"- {h}d: {w.get('status', 'not run')}")
    ret = eq / book.START_EQUITY - 1
    L += ["", "## 5. Paper portfolio (forward, play money)", "",
          f"- Equity {eq:,.2f} EUR after the sale fee ({_p(ret, 2)}) since {(st.get('started') or '')[:10] or 'not started'}, "
          f"{len(st.get('positions') or {})} positions, {len(st.get('trades') or [])} paper trades, "
          f"{len(j)} journal day{'' if len(j) == 1 else 's'}.",
          "- Rules: top 10 after fees, 10 % each, weekly look, 30-day minimum hold, Skinport prices and fee "
          "(see `lab/cs2/book.py`).", ""]
    md = "\n".join(L) + "\n"
    data = {"date": today.isoformat(), "verdict": verdict, "history_days": days, "first_day": first,
            "spread": spread, "cases": cases, "events": events, "bootstrap": boot, "walk_forward": wf,
            "paper": {"equity": eq, "return": ret, "positions": len(st.get("positions") or {}),
                      "trades": len(st.get("trades") or [])}}
    return md, data


def summary(data: dict) -> dict:
    """The few research numbers the CS2 page and the feed show, from build()'s data."""
    sp, b7, b30 = data.get("spread") or {}, (data.get("bootstrap") or {}).get("h7") or {}, (data.get("bootstrap") or {}).get("h30") or {}
    wf = data.get("walk_forward") or {}
    cases = data.get("cases") or {}

    def ok(d: dict, k: str):
        return d.get(k) if d.get("status") == "ok" else None

    return {
        "date": data.get("date"), "verdict": data.get("verdict"), "historyDays": data.get("history_days"),
        "firstDay": data.get("first_day"),
        "spread": {"status": sp.get("status"), "itemsToday": sp.get("items_today"),
                   "steamPremiumMedian": sp.get("steam_premium_median"), "toSteamMedian": sp.get("to_steam_median"),
                   "toSkinportMedian": sp.get("to_skinport_median")},
        "momentumIc": ok(b7, "ic_momentum_alone"), "momentumIcLiquid": ok(b7, "ic_momentum_liquid"),
        "bootstrapIc7": ok(b7, "ic"), "bootstrapIc30": ok(b30, "ic"), "bootstrapItems": ok(b7, "n"),
        "caseAgeIc": ok(cases, "ic_age_vs_change"),
        "walkForward7": (wf.get("h7") or {}).get("status", "not run"),
        "walkForward30": (wf.get("h30") or {}).get("status", "not run"),
    }


def main() -> int:
    today = datetime.now(timezone.utc).date()
    snap = book.snapshot(market.latest_hourly(None, "skinport_items"), market.latest_hourly(None, "skinport_sales"))
    if snap.is_empty():
        print("no CS2 snapshot yet: run python -m lab.collect.cs2 first")
        return 1
    from ..cs2.run import fit_models
    _, meta, mx = fit_models(None, snap, today)
    md, data = build(None, today, snap, meta, mx)
    report.write("cs2", md, data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
