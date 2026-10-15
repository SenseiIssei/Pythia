"""Experimental lab books: rules that FAILED the lab's bar, run on paper anyway.

The owner asked for more risk and more activity on paper. These books are the
near misses of the studies, and they stay labelled as what they are in every
place they show up:

  memes_rotation     W7's near miss: the top 1 of the six Alpaca memecoins by
                     28-day return, only while that return is positive and BTC
                     is above its 200-day average. results/memecoins.md
  memes_tsmom        W7's pre-registered pick: each Alpaca memecoin held while
                     its 28-day return is positive, BTC gate, 6 slots at 40 %
                     vol. results/memecoins.md
  trend4h_pullback   W15's only family that paid: 4h EMA 24/96 trend, entries
                     by resting buy limits half a 4h vol under the close, BTC
                     gate, holds about 8 days. results/fast_maker.md

What makes them experimental, and what the engine does with it:

- Their signals carry `"experimental": true` (top level and in the evidence)
  and `"autopilot_only": true`. The engine never runs them on their own and
  the autopilot's auto pick never picks one (portfolio picks and re-picks
  included); an autopilot runs one only when it names it as a sleeve, and
  never in live mode. Its sleeve, its trade lines in Telegram and its row on
  the Research page say "experiment".
- The variant string starts with LABEL, so every list that shows a strategy's
  name shows it too.
- Their evidence is the study's own numbers with the verdict and the reason
  they failed. results/experiments.md explains each one and what forward
  evidence would change the verdict.

This module holds the labels and reads the evidence from the studies'
markdown (the exact JSON next to the caches where it exists is not needed:
the tables are rounded to two decimals, which is all the engine shows).
"""

from __future__ import annotations

import re

from ..experiments import fam_common as fc
from .families import _md_tables

LABEL = "EXPERIMENT, failed deflation"
STUDY_NOTE = "results/experiments.md"

BOOKS: dict[str, dict] = {
    "memes_rotation": {
        "variant": f"{LABEL} · memecoins top 1 by 28d return · BTC gate · Alpaca's six memecoins",
        "study": "memecoins",
        "row": ("A", "F3 rotation", "top 1 by 28d return · BTC gate"),
        "twin": ("M", "F3 rotation", "top 1 by 28d return · BTC gate"),
        "why_failed": "deflated p 0.01 over 427 trials (0.95 needed); it lost the in-sample pick to tsmom by "
                      "0.006 Sharpe; 52 % of its P&L is PEPE; bootstrap band at 35 bps -0.24 to 2.27",
        "would_change": "90 forward days with a Sharpe above 0.5 at Alpaca costs, P&L not from one coin, "
                        "drawdown under 27 %",
    },
    "memes_tsmom": {
        "variant": f"{LABEL} · memecoins tsmom 28d · BTC gate · 6 slots at 40 % vol",
        "study": "memecoins",
        "row": ("A", "F2 trend", "tsmom 28d · BTC gate"),
        "twin": ("M", "F2 trend", "tsmom 28d · BTC gate"),
        "why_failed": "out-of-sample Sharpe 0.67 below BTC buy and hold's 0.74; deflated p 0.00 over 427 trials",
        "would_change": "90 forward days above BTC's Sharpe over the same window with a drawdown under 19 %",
    },
    "trend4h_pullback": {
        "variant": f"{LABEL} · 4h EMA 24/96 trend · pullback limit 0.5 x 4h vol · 1h window · BTC gate · "
                   "Alpaca coins, maker",
        "study": "fast_maker",
        "pick": "B EMA 24/96 · p 0.5 · W 1h · BTC gate",
        "why_failed": "deflated p 0.00 over 841 trials (bar Sharpe 2.72); 2025 negative (-0.91); "
                      "survivorship-free twin 0.40; bootstrap band -0.70 to 1.92",
        "would_change": "90 forward days with a maker fill rate near the backtest's 18 %, net per round "
                        "trip above 100 bps and a Sharpe above 0.5",
    },
}


def is_experimental(name: str) -> bool:
    return name.partition("@")[0] in BOOKS


def _rows(study: str) -> list[dict]:
    try:
        text = (fc.RESULTS_DIR / f"{study}.md").read_text(encoding="utf-8")
    except OSError:
        return []
    return [r for tb in _md_tables(text) for r in tb]


def _n_trials(study: str, default: int) -> int:
    try:
        text = (fc.RESULTS_DIR / f"{study}.md").read_text(encoding="utf-8")
    except OSError:
        return default
    m = re.search(r"Deflation pool (\d+) trials", text)
    return int(m.group(1)) if m else default


def _num(v) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _memes_evidence(name: str, b: dict) -> dict | None:
    rows = _rows(b["study"])

    def find(key: tuple) -> dict | None:
        u, fam, var = key
        return next((r for r in rows if r.get("universe") == u and r.get("family") == fam
                     and r.get("variant") == var), None)

    row, twin = find(b["row"]), find(b["twin"])
    pick = next((r for r in rows if r.get("family") == b["row"][1] and "pick" in r and "late_oos_35" in r), None)
    if row is None:
        return None
    return {
        "is_sharpe": _num(row.get("is_taker 35bps")),
        "oos_sharpe": _num(row.get("oos_taker 35bps")),
        "oos_sharpe_maker": _num(row.get("oos_maker 15bps")),
        "sharpe_2x_cost": _num(row.get("oos_stress 70bps")),
        "oos_max_dd": _num(row.get("dd_35")),
        "oos_cagr": _num(row.get("cagr_35")),
        "oos_vol": _num(row.get("vol_35")),
        "deflated_p": _num(row.get("deflated_p")),
        "bootstrap_90": [_num(row.get("boot35_p05")), _num(row.get("boot35_p95"))],
        "turnover_yr": _num(row.get("turnover_yr")),
        "oos_sharpe_survivorship_free": _num(twin.get("oos_taker 35bps")) if twin else None,
        "late_fill_sharpe": _num(pick.get("late_oos_35")) if pick and pick.get("pick") == b["row"][2] else None,
        "variants_tried": _n_trials(b["study"], 427),
        "cost_note": "Sharpe at 35 bps per unit of turnover (Alpaca taker 25 bps plus about 10 bps slippage); "
                     "oos_sharpe_maker at 15 bps; sharpe_2x_cost at 70 bps",
        "regime_filter": True,
        "caveat": "Experiment: failed deflation. The six memecoins are today's survivors, the in-sample years "
                  "are DOGE-heavy, and costs do not include the wider spreads of thin memecoin books in a crash.",
    }


def _trend4h_evidence(b: dict) -> dict | None:
    rows = _rows(b["study"])
    row = next((r for r in rows if r.get("variant") == b["pick"] and "twin_oos" in r), None)
    if row is None:
        return None
    every = next((r for r in rows if r.get("variant") == b["pick"] and "cagr_base" in r), {})
    return {
        "oos_cagr": _num(every.get("cagr_base")),
        "is_sharpe": _num(row.get("is_base")),
        "oos_sharpe": _num(row.get("oos_base")),
        "sharpe_2x_cost": _num(row.get("oos_taker")),
        "oos_max_dd": _num(row.get("dd_base")),
        "deflated_p": _num(row.get("deflated_p")),
        "bootstrap_90": [_num(row.get("boot_p05")), _num(row.get("boot_p95"))],
        "oos_sharpe_survivorship_free": _num(row.get("twin_oos")),
        "late_fill_sharpe": _num(row.get("late_oos")),
        "net_bps_round_trip": _num(row.get("net_bps_rt")),
        "fill_rate_orders": _num(row.get("fill_rate_orders")),
        "variants_tried": _n_trials(b["study"], 841),
        "cost_note": "Sharpe with resting maker fills (15 bps fee plus a 3 bps adverse-selection haircut, fills "
                     "only where the price trades through the limit); sharpe_2x_cost is the same rules filled "
                     "at the close at taker cost (35 bps a side, more than twice the maker cost)",
        "regime_filter": True,
        "caveat": "Experiment: failed deflation. Simulated on 1h bars; the engine enters after the paper "
                  "book's pullback limit filled, at its own maker price, so its fills differ from the backtest's.",
    }


def evidence(name: str) -> dict:
    """The study's numbers for an experimental book, as the engine reads them, with
    the experiment flag, the verdict and why it failed. `missing` when the study's
    write-up is not where it should be."""
    b = BOOKS[name]
    ev = _trend4h_evidence(b) if name == "trend4h_pullback" else _memes_evidence(name, b)
    base = {"report": b["study"], "experimental": True, "experiment": LABEL, "why_failed": b["why_failed"],
            "would_change": b["would_change"], "notes": STUDY_NOTE}
    if ev is None:
        return {**base, "missing": True}
    ev = {k: v for k, v in ev.items() if v is not None}
    p = ev.get("deflated_p")
    ev["verdict"] = f"experiment, fails: deflated p {p:.2f} <= 0.95" if p is not None else "experiment, fails"
    return {**base, "source": str(fc.RESULTS_DIR / f"{b['study']}.md"), **ev}


def mark(sig: dict, name: str) -> dict:
    """A signal made experimental: never standalone, never auto-picked, labelled."""
    sig["experimental"] = True
    sig["autopilot_only"] = True
    sig["experiment"] = {"label": LABEL, "why_failed": BOOKS[name]["why_failed"],
                         "would_change": BOOKS[name]["would_change"], "notes": STUDY_NOTE}
    return sig
