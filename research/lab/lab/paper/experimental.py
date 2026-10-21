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
  btc_gated          BTC at full weight while its close is above its 200-day
                     average, cash otherwise: the gate the books lean on, held
                     alone (proposed by the gated_btc study; below plain BTC on
                     Sharpe from 2024). results/gated_btc.md
  tsmom_tranches_lowmax  tsmom_tranches without the coins in the worst third by
                     28-day MAX among the 50 most liquid (the xs_factors study's
                     only pass; its improvement failed deflation).
                     results/xs_factors.md

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
    "btc_gated": {
        "variant": f"{LABEL} · BTC only while its close is above its 200-day average · full weight · daily",
        "study": "gated_btc",
        "row": "BTC above its 200-day average, k = 1",
        "why_failed": "deflated p 0.00 over 1,724 trials; out of sample from 2024 its Sharpe (0.68 at 35 bps) is "
                      "below BTC bought and held (0.74): it halves the drawdown (33 % vs 53 %), it does not add "
                      "return; 2025 negative (-0.52)",
        "would_change": "a forward year in which its drawdown stays at most two thirds of BTC's over the same "
                        "days and its Sharpe is not below BTC's",
    },
    "tsmom_tranches_lowmax": {
        "variant": f"{LABEL} · tsmom_tranches without the worst third by 28-day MAX among the 50 most liquid coins "
                   "· seven weekly tranches · BTC regime",
        "study": "xs_factors",
        "row": ("tsmom_tranches", "max filter"),
        "why_failed": "the improvement over tsmom_tranches has a deflated p of 0.01 over the 94 trials of its "
                      "registration (0.95 needed); 1 of 18 factor and book picks passed, about what chance gives",
        "would_change": "90 forward days in which it beats the tsmom_tranches paper book over the same days on "
                        "Sharpe with a drawdown no larger",
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
    """The registered 5-minute run (results/fast_maker_5m.md) where it exists, else the 1h run."""
    row, rows, study = None, [], b["study"]
    for study in (f"{b['study']}_5m", b["study"]):
        rows = _rows(study)
        row = next((r for r in rows if r.get("variant") == b["pick"] and "twin_oos" in r), None)
        if row is not None:
            break
    if row is None:
        return None
    every = next((r for r in rows if r.get("variant") == b["pick"] and "cagr_base" in r), {})
    return {
        "report": study,
        "source": str(fc.RESULTS_DIR / f"{study}.md"),
        "bars": "5m" if study.endswith("_5m") else "1h",
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
        "variants_tried": _n_trials(study, 841),
        "cost_note": "Sharpe with resting maker fills (15 bps fee plus a 3 bps adverse-selection haircut, fills "
                     "only where the price trades through the limit); sharpe_2x_cost is the same rules filled "
                     "at the close at taker cost (35 bps a side, more than twice the maker cost)",
        "regime_filter": True,
        "caveat": "Experiment: failed deflation. The paper book simulates the study's fills on live 1h bars; "
                  "the engine enters after the paper book's pullback limit filled, at its own maker price, so its "
                  "fills differ from the backtest's.",
    }


def _gated_btc_evidence(b: dict) -> dict | None:
    """G at full weight from results/gated_btc.md (the study that proposed the book)."""
    row = next((r for r in _rows(b["study"]) if r.get("variant") == b["row"]), None)
    if row is None:
        return None
    cagr, dd = _num(row.get("cagr_pct")), _num(row.get("dd_pct"))
    return {
        "is_sharpe": _num(row.get("is")),
        "oos_sharpe": _num(row.get("oos_35")),
        "sharpe_2x_cost": _num(row.get("oos_70")),
        "oos_cagr": cagr / 100 if cagr is not None else None,
        "oos_max_dd": dd / 100 if dd is not None else None,
        "deflated_p": _num(row.get("deflated_p")),
        "bootstrap_90": [_num(row.get("boot_p05")), _num(row.get("boot_p95"))],
        "late_fill_sharpe": _num(row.get("late")),
        "turnover_yr": _num(row.get("turnover_yr")),
        "variants_tried": 1724,
        "cost_note": "Sharpe at 35 bps per unit of turnover (Alpaca taker 25 bps plus about 10 bps slippage); "
                     "sharpe_2x_cost at 70 bps",
        "regime_filter": True,
        "caveat": "Experiment: failed deflation, and below BTC bought and held on Sharpe from 2024. It is the BTC "
                  "200-day gate the lab's books already depend on, held in BTC alone: a single coin, about ten "
                  "switches a year.",
    }


def _factor_evidence(b: dict) -> dict | None:
    """The pick's row in results/xs_factors.md (the study that proposed the book)."""
    book, variant = b["row"]
    row = next((r for r in _rows(b["study"]) if r.get("book") == book and r.get("variant") == variant
                and "deflated_diff" in r), None)
    if row is None:
        return None
    cagr, dd = _num(row.get("cagr_pct")), _num(row.get("dd_pct"))
    return {
        "is_sharpe": _num(row.get("is")),
        "oos_sharpe": _num(row.get("oos")),
        "book_oos_sharpe": _num(row.get("book_oos")),
        "sharpe_2x_cost": _num(row.get("oos70")),
        "oos_cagr": cagr / 100 if cagr is not None else None,
        "oos_max_dd": dd / 100 if dd is not None else None,
        "deflated_p": _num(row.get("deflated_pool")),
        "deflated_p_improvement": _num(row.get("deflated_diff")),
        "bootstrap_90_improvement": [_num(row.get("band_lo")), _num(row.get("band_hi"))],
        "late_fill_sharpe": _num(row.get("late")),
        "oos_sharpe_survivorship_free": _num(row.get("twin")),
        "minus_gated_btc_sharpe": _num(row.get("dg")),
        "variants_tried": 1836,
        "cost_note": "Sharpe at 35 bps per unit of turnover (Alpaca taker 25 bps plus about 10 bps slippage), "
                     "coins Alpaca does not list held as cash; sharpe_2x_cost at 70 bps",
        "regime_filter": True,
        "caveat": "Experiment: the improvement failed deflation. One of 18 factor and book picks passed, so a "
                  "lucky pick is the plain reading; the forward record decides.",
    }


def evidence(name: str) -> dict:
    """The study's numbers for an experimental book, as the engine reads them, with
    the experiment flag, the verdict and why it failed. `missing` when the study's
    write-up is not where it should be."""
    b = BOOKS[name]
    if name == "trend4h_pullback":
        ev = _trend4h_evidence(b)
    elif name == "btc_gated":
        ev = _gated_btc_evidence(b)
    elif name == "tsmom_tranches_lowmax":
        ev = _factor_evidence(b)
    else:
        ev = _memes_evidence(name, b)
    base = {"report": b["study"], "experimental": True, "experiment": LABEL, "why_failed": b["why_failed"],
            "would_change": b["would_change"], "notes": STUDY_NOTE}
    if ev is None:
        return {**base, "missing": True}
    ev = {k: v for k, v in ev.items() if v is not None}
    p = ev.get("deflated_p")
    ev["verdict"] = f"experiment, fails: deflated p {p:.2f} <= 0.95" if p is not None else "experiment, fails"
    return {**base, "source": str(fc.RESULTS_DIR / f"{b['study']}.md"), **ev}   # ev may name its own report


def mark(sig: dict, name: str) -> dict:
    """A signal made experimental: never standalone, never auto-picked, labelled."""
    sig["experimental"] = True
    sig["autopilot_only"] = True
    sig["experiment"] = {"label": LABEL, "why_failed": BOOKS[name]["why_failed"],
                         "would_change": BOOKS[name]["would_change"], "notes": STUDY_NOTE}
    return sig
