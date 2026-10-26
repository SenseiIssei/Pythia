"""The factory report (markdown and JSON) and the short digest for the operator's chat."""

from __future__ import annotations

import math
from collections import defaultdict

import numpy as np

from ..ops import i18n
from . import evaluate

GATE_LABEL = {"is_stable": "IS halves", "oos_positive": "OOS > 0", "stress": "70 bps", "drawdown": "DD < BTC",
              "late_fill": "late fill", "twin": "twin", "deflated": "deflated", "forward": "forward"}


def _f(v, d: int = 2) -> str:
    if v is None:
        return "n/a"
    if isinstance(v, float) and not math.isfinite(v):
        return "n/a"
    return f"{v:.{d}f}"


def _pct(v) -> str:
    return "n/a" if v is None or not math.isfinite(v) else f"{v * 100:.0f} %"


def table(rows: list[list], head: list[str]) -> str:
    out = "| " + " | ".join(head) + " |\n|" + "---|" * len(head) + "\n"
    return out + "".join("| " + " | ".join(str(x) for x in r) + " |\n" for r in rows)


def tried_by(rows: list[dict], part: str) -> list[list]:
    groups: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        g = r["genome"]
        k = g["universe"]["kind"] if part == "universe" else g["signal"]["kind"]
        if part == "universe" and k == "top":
            k = f"top {g['universe']['n']}"
        groups[k].append(r["is_sharpe"])
    out = []
    for k in sorted(groups):
        x = np.array(groups[k])
        out.append([k, len(x), _f(float(np.median(x))), _f(float(x.max())), f"{(x > 0).mean() * 100:.0f} %"])
    return out


def markdown(d: dict) -> str:
    pool0, pool1 = d["pool_before"], d["pool_after"]
    md = [f"# Strategy factory, run {d['run_id']}\n",
          f"Generated {d['generated']} by `python -m lab.factory`. Panel: {d['panel']['segments']} coin "
          f"segments, {d['panel']['first']} to {d['panel']['last']}; in sample {d['windows']['is']}, held back "
          f"{d['windows']['oos']}. Costs per unit of turnover: 15, 35 (judging) and 70 bps.\n",
          "## Verdict\n", d["verdict"] + "\n",
          "## The bar\n",
          f"Every genome evaluated is a trial in the global ledger. Pool before this run: {pool0['n_trials']} "
          f"trials ({pool0['prior_trials']} hand-study trials plus {pool0['factory_trials']} factory trials), "
          f"best noise trial expected at an annual Sharpe of {pool0['sr0_annual']:.2f}. After: "
          f"{pool1['n_trials']} trials, bar {pool1['sr0_annual']:.2f}. Promotion needs deflated p above "
          f"{evaluate.DEFLATED_BAR} against that pool, positive at 70 bps, drawdown below BTC's, the late-fill and "
          f"twin checks, and 30 forward shadow days not below the backtest's 5 % quantile.\n",
          "## What it tried\n",
          f"{d['search']['evaluated']} new genomes in {d['search']['seconds']:.0f} s "
          f"({', '.join(f'{k} {v}' for k, v in d['search']['origin'].items())}; {d['search']['duplicates']} "
          f"proposals were already in the ledger and were not counted again). In-sample Sharpe at 35 bps:\n"]
    md.append(table(tried_by(d["tried"], "signal"), ["Signal", "Tried", "Median IS Sharpe", "Best", "Positive"]))
    md.append("\n" + table(tried_by(d["tried"], "universe"), ["Universe", "Tried", "Median IS Sharpe", "Best",
                                                               "Positive"]))
    md.append("\nBest of this run by fitness (in-sample Sharpe at 35 bps, for a fixed list the worse of the list "
              f"and its point-in-time twin, minus {evaluate.COMPLEXITY_COST} per moving part):\n")
    md.append(table([[r["key"], r["name"], _f(r["is_sharpe"]), _f(r.get("is_twin")),
                      f"{_f(r['is_h1'])} / {_f(r['is_h2'])}",
                      _f(r["is_turnover_yr"], 1), _f(r["is_exposure"]), r["complexity"], _f(r["fitness"])]
                     for r in d["top"]],
                    ["Key", "Genome", "IS Sharpe", "IS twin", "Halves", "Turnover/yr", "Exposure", "Parts",
                     "Fitness"]))
    md += trees_section(d)
    md.append("\n## Held back: what survived and why\n")
    md.append(f"The search sent {len(d['holdout'])} genomes (best fitness first, both in-sample halves "
              f"positive, held-back-unseen, in-sample returns correlated below "
              f"{d['diversity_corr']:.2f} with each other) to the held-back window. BTC there: Sharpe "
              f"{d['btc']['sharpe']:.2f}, drawdown {_pct(d['btc']['max_dd'])}.\n")
    if d["holdout"]:
        md.append(table([[h["key"], h["name"], _f(h["is_sharpe"]), _f(h["oos_sharpe_15bps"]),
                          _f(h["oos_sharpe_35bps"]), _f(h["oos_sharpe_70bps"]), _pct(h["oos_max_dd"]),
                          _f(h["oos_late_sharpe"]), _f(h["oos_twin_sharpe"]), _f(h["deflated_p"]),
                          h["decision"]] for h in d["holdout"]],
                        ["Key", "Genome", "IS 35", "OOS 15", "OOS 35", "OOS 70", "DD", "Late", "Twin",
                         "Deflated p", "Decision"]))
        md.append("\nWhy each one stopped where it did:\n")
        for h in d["holdout"]:
            md.append(f"- `{h['key']}` {h['decision']}: {h['why']}")
        md.append("")
    md.append("## Forward shadow books\n")
    if d["shadows"]:
        md.append(table([[s["key"], s["name"], s["entry_day"], s["status"], s["days"], _pct(s["return"]),
                          _pct(s["band"][0]) if s["days"] else "n/a", s.get("reason") or ""]
                         for s in d["shadows"]],
                        ["Key", "Genome", "Entered", "Status", "Days", "Forward", "Band 5 %", "Note"]))
    else:
        md.append("None yet.\n")
    if d["decisions"]:
        md.append("\nDecided this run:\n")
        for x in d["decisions"]:
            md.append(f"- `{x['key']}` {x['status']}: {x['reason']}")
    md.append("\n## Promoted paper books\n")
    if d["promoted"]:
        md.append(table([[b, v["name"], v["promoted"], _f(v["evidence"]["deflated_p"])]
                         for b, v in d["promoted"].items()], ["Book", "Genome", "Since", "Deflated p"]))
    else:
        md.append("None. A promoted genome becomes a paper book run by `lab.paper.families` with live quotes; "
                  "nothing the factory does can reach live trading.\n")
    md.append("\n## How to read this\n")
    md.append("- Fitness is in-sample only. The held-back window is the hand studies' own; the factory checks a "
              "handful of genomes there per run, so it is being used again and again. That is why every trial "
              "counts in the pool and why nothing is promoted without a month of forward shadow trading.\n"
              "- Core and Alpaca lists are today's survivors; their twins (the most liquid coins at the start of "
              "each year) must hold up too.\n"
              "- Shadow books fill at the decision close plus 35 bps, as the backtest does. A promoted book "
              "trades live quotes on paper and is judged again by the forward report.\n")
    return "\n".join(md)


def trees_section(d: dict) -> list[str]:
    """The expression trees (G1): how many, the best in sample, the held-back ones, readable."""
    tr = d.get("trees")
    if not tr:
        return []
    s = d["search"]
    md = ["\n## Invented building blocks (expression trees)\n",
          f"{tr['this_run']} of this run's {s['evaluated']} genomes have an expression tree as their signal, a "
          f"coin filter or a gate (share {s.get('tree_share', 0) * 100:.0f} % of the budget); "
          f"{tr['in_ledger']} trees are in the ledger, every one a trial in the pool above. A tree node costs "
          f"{evaluate.COMPLEXITY_COST + evaluate.TREE_NODE_COST:.2f} of fitness.\n"]
    b = tr.get("best")
    if b:
        md.append(f"Best tree in sample: `{b['expression']}` ({b['tree_nodes']} nodes), IS Sharpe "
                  f"{_f(b['is_sharpe'])} (halves {_f(b['is_h1'])} / {_f(b['is_h2'])}), fitness {_f(b['fitness'])}.\n")
    if tr["held_back"]:
        md.append(table([[h["key"], f"`{h['expression']}`", _f(h["is_sharpe"]), _f(h["oos_sharpe_35bps"]),
                          _f(h["deflated_p"]), h["decision"]] for h in tr["held_back"]],
                        ["Key", "Expression", "IS 35", "OOS 35", "Deflated p", "Decision"]))
    else:
        md.append("No tree was held back this run.\n")
    return md


TITLE = "Strategy factory"
STATUS_OK, STATUS_WATCH = "ok", "watch"


def status(d: dict) -> str:
    """watch when something needs the owner's eye (a new shadow book, a promotion), else ok."""
    new_shadow = any(h["decision"] == "shadow" for h in d["holdout"])
    promoted = any(x["status"] == "promoted" for x in d["decisions"])
    return STATUS_WATCH if new_shadow or promoted else STATUS_OK


def header(d: dict, updated_ms: int) -> dict:
    """The common report header (title, updatedMs, status, headline, items) the app's lab view reads.

    Items: the pool, the best genome in sample, every held-back check with its
    decision, every shadow book and every promotion, most important first."""
    p = d["pool_after"]
    items = [{"label": "Trials counted", "value": str(p["n_trials"]), "status": "ok",
              "detail": f"{p['prior_trials']} hand-study trials plus {p['factory_trials']} factory trials; "
                        f"noise bar Sharpe {p['sr0_annual']:.2f}", "importance": 30}]
    for x in d["decisions"]:
        items.append({"label": f"{x['status'].capitalize()}: {x['name']}", "value": x["key"],
                      "status": "watch" if x["status"] == "promoted" else "ok", "detail": x["reason"],
                      "importance": 95 if x["status"] == "promoted" else 60})
    for h in d["holdout"]:
        items.append({"label": h["name"], "value": f"OOS Sharpe {_f(h['oos_sharpe_35bps'])} at 35 bps, "
                                                   f"deflated p {_f(h['deflated_p'])}",
                      "status": "watch" if h["decision"] == "shadow" else "ok",
                      "detail": f"{h['decision']}: {h['why']}", "importance": 80 if h["decision"] == "shadow" else 40})
    for sh in d["shadows"]:
        if sh["status"] != "active":
            continue
        items.append({"label": f"Shadow: {sh['name']}", "value": f"{sh['days']} of 30 days, {_pct(sh['return'])}",
                      "status": "ok", "detail": f"entered {sh['entry_day']}", "importance": 50})
    if d["top"]:
        b = d["top"][0]
        items.append({"label": f"Best in sample: {b['name']}", "value": f"IS Sharpe {_f(b['is_sharpe'])}",
                      "status": "ok", "detail": "in-sample only; not evidence by itself", "importance": 20})
    items.sort(key=lambda it: -it["importance"])
    return {"title": TITLE, "updatedMs": int(updated_ms), "status": status(d), "headline": d["verdict"],
            "items": items[:50], "verdict": d["verdict"]}


def decision_line(x: dict, lang: str = "en") -> str:
    """One shadow decision: Promoted: name (why), in `lang`. In German a
    retired genome names the gates it failed instead of the numbers."""
    if lang != "de":
        return f"{x['status'].capitalize()}: {x['name']} ({x['reason']})"
    if x.get("status") == "promoted":
        why = i18n.t("fa_promoted_reason", lang)
    elif x.get("failed"):
        why = i18n.t("fa_fails", lang, gates=", ".join(i18n.GATES_DE.get(k, k) for k in x["failed"]))
    else:
        why = i18n.reason(str(x.get("reason") or ""), lang)
    status = i18n.word(str(x.get("status")), lang)
    return i18n.t("fa_decision", lang, status=status[:1].upper() + status[1:], name=x["name"], reason=why)


def verdict_text(d: dict, lang: str = "en") -> str:
    """The run's verdict; English is the report's own."""
    if lang != "de":
        return d["verdict"]
    trials = d["pool_after"]["n_trials"]
    prom = [x for x in d["decisions"] if x["status"] == "promoted"]
    n_sh = sum(1 for h in d["holdout"] if h["decision"] == "shadow")
    if prom:
        return i18n.t("fa_verdict_promoted", lang, n=len(prom))
    if n_sh:
        return i18n.t("fa_verdict_shadow", lang, n=n_sh, trials=trials)
    return i18n.t("fa_verdict_none", lang, n=len(d["holdout"]), trials=trials)


def digest(d: dict, lang: str = "en") -> str:
    """Short text for Telegram or a webhook: what was tried, what survived, why."""
    t = i18n.t
    p = d["pool_after"]
    lines = [t("fa_head", lang, run=d["run_id"], n=d["search"]["evaluated"], trials=p["n_trials"],
               sr0=i18n.num(p["sr0_annual"], 2, lang))]
    if d["top"]:
        b = d["top"][0]
        lines.append(t("fa_best", lang, name=b["name"], sharpe=i18n.num(b["is_sharpe"], 2, lang)))
    if d["holdout"]:
        lines.append(t("fa_held", lang))
        for h in d["holdout"]:
            lines.append(t("fa_holdout_line", lang, name=h["name"], oos=i18n.num(h["oos_sharpe_35bps"], 2, lang),
                           p=i18n.num(h["deflated_p"], 2, lang), decision=i18n.word(h["decision"], lang)))
    act = [s for s in d["shadows"] if s["status"] == "active"]
    items = ", ".join(t("fa_shadow_item", lang, id=s["key"][:6], days=s["days"],
                        ret=i18n.frac_pct(s["return"], 1, lang)) for s in act)
    lines.append(t("fa_shadows", lang, n=len(act), list=f": {items}" if act else ""))
    for x in d["decisions"]:
        lines.append(decision_line(x, lang))
    lines.append(verdict_text(d, lang))
    return "\n".join(lines)
