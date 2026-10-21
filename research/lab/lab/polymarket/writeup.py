"""The study's report: reports/polymarket_study/latest.{md,json} (results/polymarket_study.md
with PYTHIA_RESULTS). Tables only; the narrative is results/polymarket.md."""

from __future__ import annotations

from datetime import datetime, timezone

from .. import report


def _p(v, dp: int = 1, sign: bool = False) -> str:
    if v is None or v != v:
        return "n/a"
    return f"{v * 100:{'+' if sign else ''}.{dp}f} %"


def _f(v, dp: int = 4, sign: bool = False) -> str:
    if v is None or v != v:
        return "n/a"
    return f"{v:{'+' if sign else ''}.{dp}f}"


def table(head: list[str], rows: list[list]) -> str:
    out = "| " + " | ".join(head) + " |\n|" + "---|" * len(head) + "\n"
    return out + "".join("| " + " | ".join(str(c) for c in r) + " |\n" for r in rows)


def markdown(res: dict) -> str:
    d = res["data"]
    b = res["biases"]
    out = [f"# Polymarket study (Y4), run {datetime.now(timezone.utc).strftime('%Y-%m-%d')}\n",
           "Pre-registration: `results/polymarket_prereg.md`. Narrative and verdict: `results/polymarket.md`.\n",
           "## Data\n",
           f"Universe: {d['universe_markets']:,} closed markets with at least $1,000 of volume, "
           f"{d['universe_resolved']:,} of them resolved to one side. Sampled with price history: "
           f"{d['sampled_with_history']:,}; in the panel {d['markets_in_panel']:,} markets of {d['events']:,} "
           f"events, {d['states']:,} market states from {d['first']} to {d['last']}. Data folder "
           f"{d['size_mb']:,} MB.\n",
           table(["Year", "Markets", "States"], [[r["year"], f"{r['markets']:,}", f"{r['states']:,}"]
                                                 for r in d["by_year"]]),
           table(["Category", "Markets", "States"], [[r["category"], f"{r['markets']:,}", f"{r['states']:,}"]
                                                     for r in d["by_category"]]),
           "## B1. Favourite/longshot\n",
           "Outcome rate against the mean price per bucket, each market weighing one, reweighted to the "
           "universe; 95 % band from resampling whole events.\n",
           table(["Price bucket", "Markets", "Mean price", "Won", "95 % band", "Won minus price"],
                 [[r["bucket"], f"{r['markets']:,}", _p(r["price"]), _p(r["rate"]),
                   f"{_p(r['lo'])} to {_p(r['hi'])}", _p(r["diff"], sign=True)] for r in b["B1_buckets"]]),
           f"\nCalibration line `logit P(win) = a + b logit(p)`: a {_f(b['B1_line']['a'], 3, True)} "
           f"(se {_f(b['B1_line']['a_se'], 3)}), b {_f(b['B1_line']['b'], 3)} (se {_f(b['B1_line']['b_se'], 3)}). "
           "b below 1 means longshots are too dear and favourites too cheap; above 1 the reverse.\n",
           "## B2. Drift to resolution\n",
           table(["Days to end", "Markets", "a", "b (se)", "Market Brier"],
                 [[r["horizon"], f"{r['markets']:,}", _f(r["a"], 3, True), f"{_f(r['b'], 3)} ({_f(r['b_se'], 3)})",
                   _f(r["brier_market"])] for r in b["B2"]]),
           "## B3. Category and kind\n",
           table(["Category", "Kind", "Markets", "a", "b (se)", "Market Brier"],
                 [[r["category"], r["kind"], f"{r['markets']:,}", _f(r["a"], 3, True),
                   f"{_f(r['b'], 3)} ({_f(r['b_se'], 3)})", _f(r["brier_market"])] for r in b["B3"]]),
           "## B4. Volume (final volume, hindsight, descriptive)\n",
           table(["Tercile", "From $", "Markets", "a", "b (se)", "Market Brier"],
                 [[r["tercile"], f"{r['vol_from']:,.0f}", f"{r['markets']:,}", _f(r["a"], 3, True),
                   f"{_f(r['b'], 3)} ({_f(r['b_se'], 3)})", _f(r["brier_market"])] for r in b["B4_volume"]]),
           "## B5. Recent moves\n",
           f"7-day logit change added to logit(p): coefficient {_f(b['B5']['chg_7d'], 3, True)} "
           f"(se {_f(b['B5']['chg_7d_se'], 3)}); 1-day: {_f(b['B5_1d']['chg_1d'], 3, True)} "
           f"(se {_f(b['B5_1d']['chg_1d_se'], 3)}). Positive: the price under-reacts (momentum); negative: it "
           "over-reacts.\n",
           "## M. Models against the market (out of sample by quarter from 2024)\n"]
    rows = []
    for k, m in res["models"].items():
        rows.append([k[2:], f"{m['markets']:,}", _f(m["brier_market"]), _f(m["brier_model"]), _p(m["skill"], 2, True),
                     f"{_f(m['brier_diff'], 5, True)} ({_f(m['brier_diff_lo'], 5, True)} to "
                     f"{_f(m['brier_diff_hi'], 5, True)})", _f(m["logloss_market"]), _f(m["logloss_model"]),
                     f"{m['years_better']}/3", f"{m['cats_better']}/{m['cats_big']}",
                     _f(res["holm"].get(k), 3), "yes" if m["passes"] else "no"])
    out.append(table(["Model", "Markets", "Brier market", "Brier model", "Skill", "Brier gain (95 %)",
                      "Log loss market", "Log loss model", "Years better", "Categories better", "Holm p",
                      "Passes"], rows))
    if res.get("slices"):
        out.append("\n**Addendum slices** (same test, states where the history price is more likely a real "
                   "price):\n")
        rows = []
        for name, sl in res["slices"].items():
            for k in ("q_recal", "q_gbm"):
                m = sl[k]
                rows.append([name, k[2:], _p(sl["share_states"], 0), f"{m['markets']:,}", _f(m["brier_market"]),
                             _f(m["brier_model"]), _p(m["skill"], 2, True),
                             f"{_f(m['brier_diff'], 5, True)} ({_f(m['brier_diff_lo'], 5, True)} to "
                             f"{_f(m['brier_diff_hi'], 5, True)})", f"{m['years_better']}/3",
                             "yes" if m["passes"] else "no"])
        out.append(table(["Slice", "Model", "Share of states", "Markets", "Brier market", "Brier model", "Skill",
                          "Brier gain (95 %)", "Years better", "Rule met"], rows))
    if res.get("by_volume"):
        out.append("\n**By final volume** (after day one and moved; final volume is hindsight, so this only "
                   "says where the skill sits):\n")
        out.append(table(["Final volume", "Markets", "Brier market", "recal skill", "gbm skill", "gbm gain (95 %)"],
                         [[f"${r['from']:,.0f}" + (f" to ${r['to']:,.0f}" if r["to"] != float("inf") else " and up"),
                           f"{r['markets']:,}", _f(r["brier_market"]), _p(r["q_recal"]["skill"], 2, True),
                           _p(r["q_gbm"]["skill"], 2, True),
                           f"{_f(r['q_gbm']['gain'], 5, True)} ({_f(r['q_gbm']['lo'], 5, True)} to "
                           f"{_f(r['q_gbm']['hi'], 5, True)})"] for r in res["by_volume"]]))
    if res.get("live_spreads"):
        out.append("\n**Quoted spreads of the open markets** (live record, Gamma's best bid and ask; every open "
                   "market with $1,000 of liquidity, plus the first snapshot's every open market):\n")
        out.append(table(["Mid bucket", "Markets", "Median spread", "Wider than 10 cents", "Markets with $10k+",
                          "Their median spread"],
                         [[r["bucket"], f"{r['markets']:,}", _f(r["median_spread"], 3), _p(r["wide_share"], 0),
                           f"{r['liquid_markets']:,}", _f(r["liquid_median_spread"], 3)] for r in res["live_spreads"]]))
    for k, m in res["models"].items():
        out.append(f"\n**{k[2:]} by category** (Brier, market / model, markets):\n")
        out.append(table(["Category", "Market", "Model", "Markets"],
                         [[c, _f(v["market"]), _f(v["model"]), f"{v['markets']:,}"]
                          for c, v in m["by_category"].items()]))
        out.append(f"\n**{k[2:]} by days to end**:\n")
        out.append(table(["Days to end", "Market", "Model", "Markets"],
                         [[c, _f(v["market"]), _f(v["model"]), f"{v['markets']:,}"]
                          for c, v in m["by_horizon"].items()]))
    out.append("\n## P. The paper rule on the test states (historical twin)\n")
    hs = res.get("half_spreads") or {}
    out.append(f"Asks: history price plus the median half-spread of the live book record "
               f"({hs.get('n', 0):,} book sides; at least half a cent), at most $500 per market, the published "
               "taker fees by category, $10,000 start, quarter Kelly with the caps.\n")
    srows = []
    for s in res["sims"] + res["stress"]:
        srows.append([s["book"][2:], s["margin"], f"{s['spread_mult']:g}x", s["trades"], _p(s["hit_rate"]),
                      f"{_p(s['mean_ret'], 1, True)} ({_p(s['mean_ret_lo'], 1, True)} to {_p(s['mean_ret_hi'], 1, True)})",
                      f"{s['pnl']:+,.0f}", _p(s["total_return"], 1, True), _f(s["sharpe"], 2), _p(s["max_dd"]),
                      f"{s['fees']:,.0f}", _f(s.get("deflated_p"), 2)])
    out.append(table(["Forecast", "Margin", "Spread", "Trades", "Hit rate", "Mean per trade (95 %)", "P&L $",
                      "Return", "Sharpe", "Max DD", "Fees $", "Deflated p"], srows))
    if res.get("checks"):
        out.append("\n**Addendum checks** (declared after the test run, counted as trials):\n")
        out.append(table(["Forecast", "Check", "Trades", "Hit rate", "Mean per trade (95 %)", "Return", "Sharpe",
                          "Max DD", "Deflated p"],
                         [[c["book"][2:], c["check"], c["trades"], _p(c["hit_rate"]),
                           f"{_p(c['mean_ret'], 1, True)} ({_p(c['mean_ret_lo'], 1, True)} to "
                           f"{_p(c['mean_ret_hi'], 1, True)})", _p(c["total_return"], 1, True), _f(c["sharpe"], 2),
                           _p(c["max_dd"]), _f(c.get("deflated_p"), 2)] for c in res["checks"]]))
        hs = res.get("half_spreads") or {}
        if hs.get("by_age"):
            out.append("\nMedian half-spread of the live record by market age: "
                       + ", ".join(f"{a} {v * 100:.2f} cents ({hs['n_age'].get(a, 0):,} book sides)"
                                   for a, v in hs["by_age"].items()) + ".\n")
    pl_ = res["pool"]
    out.append(f"\nPool: {pl_['hand_trials']:,} hand trials, {pl_['factory_trials']:,} factory trials, "
               f"{pl_['mine']} here: {pl_['n_total']:,} (noise bar Sharpe {pl_['sr0_annual']:.2f}).\n")
    lm = res.get("live_model") or {}
    out.append(f"\nLive model: fitted on {lm.get('trained_states', 0):,} states of "
               f"{lm.get('trained_markets', 0):,} markets.\n")
    return "\n".join(out)


def feed(res: dict) -> dict:
    g = res["models"].get("q_gbm", {})
    best = max(res["sims"], key=lambda s: s["sharpe"]) if res["sims"] else {}
    head = (f"Our model {'beats' if g.get('passes') else 'does not beat'} the market price out of sample "
            f"(Brier {g.get('brier_model', 0):.4f} vs {g.get('brier_market', 0):.4f}); the best paper rule "
            f"made {best.get('total_return', 0):+.1%} on the test years.")
    items = [{"label": f"Model {k[2:]}", "value": f"{m['skill'] * 100:+.2f} %", "status": "ok" if m["passes"] else "bad",
              "detail": f"Brier skill against the market on {m['markets']:,} markets, out of sample"}
             for k, m in res["models"].items()]
    return report.feed_header("Polymarket study", "ok" if g.get("passes") else "watch", head, items)


def write(res: dict) -> None:
    data = {k: v for k, v in res.items()}
    data.update(feed(res))
    report.write("polymarket_study", markdown(res), data)
