"""Charts for the README, rebuilt from the repository and the lab's data folder.

    python scripts/readme_charts.py               # every chart
    PYTHIA_DATA=<data folder> python scripts/readme_charts.py

Needs matplotlib. Writes PNGs to docs/img/. Nothing here is made up: every
number either comes out of a file at run time or is copied from a lab result
file named next to it, so a reader can check each bar against its source.

  hero.png             banner: the name, the tagline and the study scoreboard as a strip
  scoreboard.png       out-of-sample Sharpe of the tested crypto strategies, by verdict
  forward.png          the paper autopilots since 2026-10-15 against BTC (needs PYTHIA_DATA)
  research_funnel.png  the deflation pool over time and every study's verdict
  by_year.png          Sharpe per year, out of sample, for the books that are still running

Sources at run time:
  research/lab/README.md                       the "Results so far" table (one row per study)
  $PYTHIA_DATA/reports/forward/<date>.json     the daily forward report (06:15 UTC)
  $PYTHIA_DATA/autopilot/state.json            the autopilot engine's saved state
  $PYTHIA_DATA/autopilot-safe/state.json       the second paper account's engine state

Without PYTHIA_DATA the forward chart is skipped and the PNG already in
docs/img/ is kept.
"""

from __future__ import annotations

import glob
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyBboxPatch, Rectangle  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "img"
LAB_README = ROOT / "research" / "lab" / "README.md"

# ---------------------------------------------------------------------------
# Style. A light card with rounded corners on a transparent page, so the image
# reads as a card on GitHub's light and dark themes alike. Categorical hues are
# the validated default order (blue, orange, aqua, yellow, magenta); every
# series is also labelled directly, so no colour carries meaning alone.
# ---------------------------------------------------------------------------
SURFACE = "#fcfcfb"
BORDER = "#e3e2dd"
INK = "#0b0b0b"
INK2 = "#52514e"
MUTED = "#86857f"
GRID = "#ecebe6"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"]
BLUE = "#2a78d6"
GREEN = "#008300"
AMBER = "#eda100"
FAIL = "#cfcec8"
VIOLET = "#6250d6"
RAMP = ["#86b6ef", "#3987e5", "#1c5cab"]  # ordinal: 2024, 2025, 2026

def _font() -> str:
    """The first installed of the app's font stack (Inter, then the system UI fonts)."""
    from matplotlib import font_manager

    have = {f.name for f in font_manager.fontManager.ttflist}
    return next((f for f in ("Inter", "Segoe UI", "Helvetica Neue", "Arial") if f in have), "DejaVu Sans")


plt.rcParams.update(
    {
        "font.family": _font(),
        "font.size": 10.5,
        "text.color": INK,
        "axes.labelcolor": INK2,
        "axes.edgecolor": GRID,
        "xtick.color": INK2,
        "ytick.color": INK2,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.spines.left": False,
        "axes.facecolor": "none",
        "savefig.facecolor": "none",
    }
)


def card(fig) -> None:
    """The rounded light card behind everything."""
    fig.patch.set_alpha(0)
    fig.patches.append(
        FancyBboxPatch(
            (0.004, 0.006),
            0.992,
            0.988,
            boxstyle="round,pad=0,rounding_size=0.018",
            transform=fig.transFigure,
            facecolor=SURFACE,
            edgecolor=BORDER,
            linewidth=1.2,
            zorder=-10,
        )
    )


def titles(fig, title: str, subtitle: str, y: float = 0.93) -> None:
    fig.text(0.04, y, title, fontsize=15, fontweight="bold", color=INK, va="bottom")
    fig.text(0.04, y - 0.015, subtitle, fontsize=10.5, color=INK2, va="top")


def footnote(fig, text: str) -> None:
    fig.text(0.04, 0.035, text, fontsize=8.5, color=MUTED, va="bottom")


def save(fig, name: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    fig.savefig(path, dpi=180, pil_kwargs={"optimize": True})
    plt.close(fig)
    print(f"wrote {path.relative_to(ROOT)}")


# ---------------------------------------------------------------------------
# Data copied from the lab's result files. Out of sample from 2024-01-01 to
# October 2026, net of costs. Spot books at 35 bps per unit of turnover (Alpaca
# taker plus slippage), coins Alpaca does not list held in cash.
# ---------------------------------------------------------------------------
BENCH, PASS, EXPERIMENT, FAILED = "bench", "pass", "experiment", "failed"

# (label, Sharpe, verdict, cost note, source)
SCOREBOARD = [
    ("BTC bought and held", 0.74, BENCH, "", "results/gated_btc.md, G's own record"),
    ("BTC only above its 200-day average", 0.68, BENCH, "35 bps", "results/gated_btc.md, G's own record"),
    ("M4 residual, perps long/short", 0.96, PASS, "41 bps", "results/m4_residual.md, holdout Sharpe of the residual"),
    ("Funding carry, perps long/short", 0.74, PASS, "10 bps", "results/funding_carry.md, holdout 2024-01-01 to 2026-10-18"),
    ("Breakout top 10 (Donchian 20/10)", 1.17, EXPERIMENT, "35 bps", "results/gated_btc.md, Books and G, book_oos"),
    ("Memecoin rotation, top 1, BTC gate", 1.15, EXPERIMENT, "35 bps", "results/memecoins.md, F3 near miss"),
    ("Momentum tranches, Korean premium filter", 0.87, EXPERIMENT, "35 bps", "results/kr_premium_xs.md, tsmom_tranches filter"),
    ("Momentum tranches, MAX filter", 0.85, EXPERIMENT, "35 bps", "results/xs_factors.md, max on tsmom_tranches"),
    ("4h trend, pullback maker entries", 0.71, EXPERIMENT, "maker", "results/gated_btc.md, trend4h_pullback book_oos"),
    ("Memecoin momentum, BTC gate", 0.67, EXPERIMENT, "35 bps", "results/memecoins.md, overall pick F2"),
    ("Momentum in seven weekly tranches", 0.65, EXPERIMENT, "35 bps", "results/gated_btc.md, tsmom_tranches book_oos"),
    ("Factory genome, 5 lowest-vol of top 20", 0.88, FAILED, "35 bps", "results/genome_gates.md, reproduced 0.876 (killed)"),
    ("Basket, vol-managed with BTC gate", 0.64, FAILED, "35 bps", "results/vol_managed.md, basket pick"),
    ("BTC covered call, vol premium filter", 0.60, FAILED, "3 vol pts", "results/btc_vrp.md, pick CC F (killed)"),
    ("Momentum top 20", 0.54, FAILED, "35 bps", "results/gated_btc.md, tsmom_top20 (killed by gated BTC)"),
    ("Momentum with mirror shorts, perps", 0.27, FAILED, "10 bps", "results/trend_shorts.md, tsmom pick"),
    ("Breakout with bad-week flow model", 0.03, FAILED, "35 bps", "results/flow_overlays.md, combined overlay"),
    ("Breakout, meta-label skips weak entries", 0.00, FAILED, "35 bps", "results/meta_daily.md, S1"),
    ("Best candlestick rule, crypto 4h", -1.06, FAILED, "35 bps", "results/candles.md, B long-only rules"),
]

# Expected best annual Sharpe of pure noise over the whole pool of counted
# trials (results/xs_factors.md and results/kr_premium_xs.md: "Pool: 1,836
# trials ... the best noise trial sits at an annual Sharpe of about 2.69").
NOISE_BAR = 2.69
POOL_NOW = 1836

# The deflation pool as each day's last study reported it.
POOL_HISTORY = [
    ("2026-10-07", 100, "families_summary.md: nine families, 100 variants"),
    ("2026-10-08", 154, "breakout_study.md: 154 trials"),
    ("2026-10-11", 183, "blend_study.md: 183 trials"),
    ("2026-10-12", 184, "tsmom_tranches.md: 184 trials"),
    ("2026-10-13", 265, "fast_strategies.md: 265 trials"),
    ("2026-10-14", 356, "vol_managed.md: 356 trials"),
    ("2026-10-15", 1106, "flow_overlays.md: pool 1,106 (factory's first 300 genomes included)"),
    ("2026-10-20", 1668, "equities_training.md: pool of 1,668"),
    ("2026-10-21", 1836, "xs_factors.md: pool 1,836"),
]

# Every row of the "Results so far" table in research/lab/README.md, by verdict.
OUTCOMES = {
    "failed": "Failed or killed",
    "experiment": "Runs on paper, failed deflation",
    "pass": "Passed as registered, not confirmed",
    "model": "Model beats its baseline",
    "open": "Too early, not run or forward only",
    "audit": "Audit or measurement",
}
VERDICTS = {
    "`spread`": "failed", "`vol`": "model", "`meta`": "failed", "`tsmom`": "experiment",
    "`momentum2`": "experiment", "`carry`": "failed", "`xs_daily` (M4)": "failed",
    "`xs_daily` round 3 (M4, funding-aware)": "failed", "`regime` (M5)": "failed",
    "`vol_daily` (M6)": "failed", "`breakout_study`": "experiment", "`blend_study`": "failed",
    "`etf_trend`": "failed", "`tsmom_tranches`": "experiment", "`fast_strategies`": "failed",
    "`vol_managed`": "failed", "`meta_daily` (C14)": "failed", "`regime_hmm` (M7)": "failed",
    "`alpaca_universe` (C16)": "failed", "`alpaca36` (W3)": "failed", "`cs2` (W8)": "open",
    "`pokemon` (W9)": "open", "`factory` (W10)": "failed", "`memecoins` (W7)": "failed",
    "`listings` (W6)": "failed", "`equities_ranking` (M9)": "failed",
    "`intraday_equities` (W4)": "failed", "`model_zoo` (W11)": "model", "`fast_maker` (W15)": "failed",
    "`experiments` (X3)": "experiment", "`overnight` (X7 A)": "failed",
    "`book_portfolio` (X7 B)": "failed", "`flow_overlays` (X6)": "failed",
    "`model_review` (X9)": "model", "`model_upgrades` (X11)": "model",
    "`equities_training` (X16 A, B1, C)": "failed", "`exit_overlays` (X16 B2, M14)": "failed",
    "`pumpfun_rt` (X8)": "open", "`pumpfun_rt` pipeline (X10)": "open",
    "`pumpfun_rt` early and exits (X14)": "open", "`pumpfun_rt` speed (Y3)": "failed",
    "`candles_study` (X15)": "failed", "`polymarket` (Y4)": "failed", "`forward_audit` (Y1)": "audit",
    "`gated_btc` (director draft)": "failed", "`autopilot_optimization` (Z2)": "audit",
    "`equity_sleeve` (Z2, forward)": "open", "`genome_gates` (director draft)": "failed",
    "`m4_residual` (director draft)": "pass", "`delist_hazard` (O3)": "model",
    "`kr_premium_xs` (O4)": "experiment", "`xs_factors`": "experiment",
    "`pumpfun_activity` (O9)": "open", "`earnings_premium` (survey 3)": "failed",
    "`index_deletions` (survey 4)": "failed", "`seasonality` (survey 6)": "failed",
    "`quality_issuance` (survey 7)": "failed", "`turn_of_month` (survey 8)": "failed",
    "`insider_purchases` (survey 10)": "open", "`vix_carry` (survey #2)": "failed",
    "`etf_routing` (survey O1)": "failed", "`crypto_open_gap` (survey O6)": "failed",
    "`treasury_premium` (survey O2)": "open", "`btc_vrp` (survey #9)": "failed",
    "`funding_carry` (survey #1)": "pass", "`trend_shorts` (survey #5)": "failed",
    "`flush_long` (survey O5)": "failed", "`kraken_funding_gap` (survey O7)": "failed",
    "`costs`": "audit",
}
OUTCOME_COLORS = {
    "failed": FAIL, "experiment": AMBER, "pass": GREEN, "model": BLUE, "open": "#e9e8e3", "audit": "#9d9c96",
}

# Sharpe per calendar year, out of sample (2026 to each study's data end).
BY_YEAR = [
    ("Breakout top 10", (2.19, 0.32, -0.02), "results/gated_btc.md, Per year, b2024 to b2026 (35 bps)"),
    ("Momentum tranches", (1.67, -0.08, 0.25), "results/gated_btc.md, Per year (35 bps)"),
    ("BTC above 200-day", (1.44, -0.52, 1.19), "results/gated_btc.md, G's own record at k = 1"),
    ("M4 residual (perps)", (1.08, 1.13, 0.65), "results/m4_residual.md, every year (41 bps)"),
    ("Funding carry (perps)", (0.75, 1.46, -0.06), "results/funding_carry.md, the pick (10 bps)"),
]


def lab_rows() -> list[str]:
    """First cell of every study row in the lab README's results table."""
    text = LAB_README.read_text(encoding="utf-8")
    block = text.split("## Results so far", 1)[1].split("\n## ", 1)[0]
    rows = [line.split("|")[1].strip() for line in block.splitlines() if line.startswith("| `")]
    unknown = [r for r in rows if r not in VERDICTS]
    if unknown:
        sys.exit(f"classify these lab README rows in VERDICTS first: {unknown}")
    return rows


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------
LEGEND = [
    (BENCH, INK2, "Benchmark"),
    (PASS, GREEN, "Passed as registered, not confirmed"),
    (EXPERIMENT, AMBER, "Runs on paper, failed deflation"),
    (FAILED, FAIL, "Failed or killed"),
]
COLOR = {k: c for k, c, _ in LEGEND}


def scoreboard() -> None:
    order = {BENCH: 0, PASS: 1, EXPERIMENT: 2, FAILED: 3}
    rows = sorted(SCOREBOARD, key=lambda r: (order[r[2]], -r[1]))
    n = len(rows)
    fig = plt.figure(figsize=(10.5, 0.36 * n + 2.6))
    card(fig)
    top = 1 - 1.15 / fig.get_figheight()
    ax = fig.add_axes([0.37, 0.95 / fig.get_figheight(), 0.58, top - 1.0 / fig.get_figheight()])
    titles(
        fig,
        "Nothing beats the noise bar",
        "Out-of-sample Sharpe from 2024-01-01, net of costs. The dashed line is what the best of "
        f"{POOL_NOW:,} counted pure-noise trials would show.",
        y=1 - 0.42 / fig.get_figheight(),
    )
    ys = list(range(n))[::-1]
    for y, (label, sharpe, verdict, cost, _src) in zip(ys, rows):
        ax.barh(y, sharpe, height=0.62, color=COLOR[verdict], zorder=3)
        # Negative values are labelled right of zero so the label never meets the names.
        ax.text(max(sharpe, 0) + 0.04, y, f"{sharpe:.2f}", va="center", ha="left",
                fontsize=9.5, color=INK, fontweight="bold" if verdict != FAILED else "normal")
        name = label + (f"  ({cost})" if cost else "")
        ax.text(-0.025, y, name, transform=ax.get_yaxis_transform(), va="center", ha="right", fontsize=9.6,
                color=INK if verdict != FAILED else INK2)
    ax.axvline(0, color=INK2, linewidth=0.8, zorder=4)
    ax.axvline(NOISE_BAR, color=INK, linewidth=1.3, linestyle=(0, (4, 3)), zorder=4)
    ax.text(NOISE_BAR - 0.05, n - 0.35, f"noise bar {NOISE_BAR:.2f}", ha="right", va="center", fontsize=9, color=INK)
    ax.set_xlim(-1.3, 3.0)
    ax.set_ylim(-0.7, n - 0.3)
    ax.set_yticks([])
    ax.grid(axis="x", color=GRID, linewidth=0.8, zorder=0)
    ax.tick_params(axis="x", length=0, labelsize=9)
    ax.spines["bottom"].set_visible(False)
    handles = [Rectangle((0, 0), 1, 1, color=c) for _, c, _ in LEGEND]
    fig.legend(handles, [t for _, _, t in LEGEND], loc="lower left", bbox_to_anchor=(0.035, 0.035),
               ncol=4, frameon=False, fontsize=9, handlelength=1.0, handleheight=1.0, columnspacing=1.4)
    save(fig, "scoreboard.png")


def _ms(t: float) -> datetime:
    return datetime.fromtimestamp(t / 1000, timezone.utc).replace(tzinfo=None)


def forward(data: Path) -> dict | None:
    state_path = data / "autopilot" / "state.json"
    if not state_path.exists():
        print(f"skip forward.png: {state_path} not found")
        return None
    state = json.loads(state_path.read_text(encoding="utf-8"))
    running = [a for a in state["autopilots"] if a["state"] == "running"]
    reports = []
    for path in sorted(glob.glob(str(data / "reports" / "forward" / "2026-*.json"))):
        reports.append(json.loads(Path(path).read_text(encoding="utf-8")))

    series = []
    btc = None
    for a in running:
        cfg = a["config"]
        start = a["startedMs"]
        pts = [(start, 0.0)]
        bpts = [(start, 0.0)]
        names: list[str] = []
        for rep in reports:
            if rep["generated_ms"] <= start:
                continue
            for row in rep["autopilots"]:
                if row["name"] == cfg["id"] and row.get("state") == "running" and row.get("return_pct") is not None:
                    pts.append((rep["generated_ms"], row["return_pct"]))
                    bpts.append((rep["generated_ms"], row["btc_return_pct"]))
                    names.append(row["label"])
        # The latest point from the engine state: equity over the amount it works with.
        if len(a.get("capitalLog") or []) > 1:
            sys.exit(f"{cfg['id']}: the amount changed; measure on the time-weighted capital first")
        t_last, eq_last = a["history"][-1]
        pts.append((t_last, (eq_last / a["startCapital"] - 1) * 100))
        btc_now = state["prices"]["crypto:BTC/USD"][0]
        bpts.append((t_last, (btc_now / a["btcStart"] - 1) * 100))
        names.append(cfg["name"])
        clean = []
        for nm in names:
            nm = re.sub(r"^Test\s*\W\s*", "", nm)
            if not clean or clean[-1] != nm:
                clean.append(nm)
        label = ", then ".join(clean).replace(" (experiment)", "*")
        series.append((cfg["id"], label, pts, cfg["startCapital"] if "startCapital" in cfg else a["startCapital"]))
        if cfg["id"] == "ap_autopick":
            btc = bpts

    safe_note = ""
    safe_path = data / "autopilot-safe" / "state.json"
    if safe_path.exists():
        safe = json.loads(safe_path.read_text(encoding="utf-8"))
        for a in safe["autopilots"]:
            if a["state"] == "running":
                ret = (a["history"][-1][1] / a["startCapital"] - 1) * 100
                safe_note = (f"A sixth autopilot on a second ${a['startCapital']:,.0f} paper account stands at "
                             f"{ret:+.2f} % (it has not traded yet).")

    # Main first, then by final return.
    series.sort(key=lambda s: (s[0] != "ap_autopick", -s[2][-1][1]))
    fig = plt.figure(figsize=(11, 5.6))
    card(fig)
    titles(fig, "Forward record: the paper autopilots since 15 October 2026",
           "Return on the amount each autopilot trades, Alpaca paper account, against BTC bought and held "
           "over the same days. Not a backtest.", y=0.915)
    ax = fig.add_axes([0.07, 0.18, 0.55, 0.62])
    ends = []
    for i, (_id, label, pts, _cap) in enumerate(series):
        xs = [_ms(t) for t, _ in pts]
        ys = [v for _, v in pts]
        ax.plot(xs, ys, color=SERIES[i % len(SERIES)], linewidth=2, zorder=3, solid_capstyle="round")
        ax.plot(xs[-1], ys[-1], "o", color=SERIES[i % len(SERIES)], markersize=6,
                markeredgecolor=SURFACE, markeredgewidth=1.5, zorder=4)
        ends.append((ys[-1], f"{label}  {ys[-1]:+.2f} %", SERIES[i % len(SERIES)]))
    if btc:
        xs = [_ms(t) for t, _ in btc]
        ys = [v for _, v in btc]
        ax.plot(xs, ys, color=INK, linewidth=1.6, linestyle=(0, (4, 3)), zorder=2)
        ends.append((ys[-1], f"BTC bought and held  {ys[-1]:+.2f} %", INK))
    ax.axhline(0, color=INK2, linewidth=0.8, zorder=1)
    ax.grid(axis="y", color=GRID, linewidth=0.8, zorder=0)
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:+.0f} %" if v else "0"))
    ax.xaxis.set_major_locator(mdates.DayLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    ax.tick_params(length=0, labelsize=9)
    ax.spines["bottom"].set_visible(False)
    # Direct labels at the right edge, spread so they never overlap.
    lo, hi = ax.get_ylim()
    gap = (hi - lo) * 0.075
    ends.sort(key=lambda e: e[0])
    placed: list[float] = []
    for v, _, _ in ends:
        placed.append(max(v, placed[-1] + gap) if placed else v)
    over = placed[-1] - (hi - gap * 0.3) if placed else 0
    if over > 0:
        placed = [p - over for p in placed]
    for (v, text, color), y in zip(ends, placed):
        ax.text(1.045, y, text, transform=ax.get_yaxis_transform(), va="center", fontsize=9, color=INK)
        ax.plot([1.025], [y], marker="s", markersize=7, color=color, transform=ax.get_yaxis_transform(),
                clip_on=False)
    note = ("* experimental lab book. Points: the daily forward report (06:15 UTC) and the engine's latest "
            "saved state.\n")
    footnote(fig, note + safe_note)
    save(fig, "forward.png")
    return {"autopilots": len(series) + (1 if safe_note else 0)}


def research_funnel(rows: list[str]) -> None:
    fig = plt.figure(figsize=(10.5, 4.9))
    card(fig)
    titles(fig, "Every try is counted, and most ideas fail",
           "Left: trials in the deflation pool. Right: the verdict of every study in the lab README, one square each.",
           y=0.905)
    ax = fig.add_axes([0.075, 0.17, 0.38, 0.6])
    xs = [datetime.strptime(d, "%Y-%m-%d") for d, _, _ in POOL_HISTORY]
    ys = [v for _, v, _ in POOL_HISTORY]
    ax.step(xs, ys, where="post", color=BLUE, linewidth=2, zorder=3)
    ax.fill_between(xs, ys, step="post", color=BLUE, alpha=0.08, zorder=2)
    ax.plot(xs, ys, "o", color=BLUE, markersize=5, markeredgecolor=SURFACE, markeredgewidth=1.2, zorder=4)
    for (d, v, _), x in zip(POOL_HISTORY, xs):
        if d in ("2026-10-07", "2026-10-15", "2026-10-21"):
            ax.annotate(f"{v:,}", (x, v), xytext=(0, 7), textcoords="offset points", ha="center",
                        fontsize=9, color=INK, fontweight="bold")
    ax.set_ylim(0, max(ys) * 1.18)
    ax.xaxis.set_major_locator(mdates.DayLocator(interval=3))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ax.grid(axis="y", color=GRID, linewidth=0.8, zorder=0)
    ax.tick_params(length=0, labelsize=9)
    ax.spines["bottom"].set_visible(False)

    counts = {k: 0 for k in OUTCOMES}
    for r in rows:
        counts[VERDICTS[r]] += 1
    order = ["failed", "experiment", "pass", "model", "open", "audit"]
    cells = [k for k in order for _ in range(counts[k])]
    wx = fig.add_axes([0.5, 0.17, 0.2, 0.6])
    cols = 10
    nrows = (len(cells) + cols - 1) // cols
    for i, k in enumerate(cells):
        r, c = divmod(i, cols)
        wx.add_patch(FancyBboxPatch((c + 0.09, nrows - 1 - r + 0.09), 0.82, 0.82,
                                    boxstyle="round,pad=0,rounding_size=0.14",
                                    facecolor=OUTCOME_COLORS[k], edgecolor=BORDER if k == "open" else "none",
                                    linewidth=0.8))
    wx.set_xlim(0, cols)
    wx.set_ylim(nrows - 10, nrows)
    wx.set_aspect("equal")
    wx.axis("off")
    ly = 0.74
    for k in order:
        fig.patches.append(FancyBboxPatch((0.725, ly - 0.012), 0.016, 0.034, boxstyle="round,pad=0,rounding_size=0.004",
                                          transform=fig.transFigure, facecolor=OUTCOME_COLORS[k],
                                          edgecolor=BORDER if k == "open" else "none"))
        fig.text(0.75, ly + 0.005, f"{counts[k]}", fontsize=11, fontweight="bold", color=INK, va="center")
        fig.text(0.78, ly + 0.005, OUTCOMES[k], fontsize=9.5, color=INK2, va="center")
        ly -= 0.088
    footnote(fig, f"{len(rows)} studies. Pool counts from the results files; verdicts from research/lab/README.md.")
    save(fig, "research_funnel.png")


def by_year() -> None:
    fig = plt.figure(figsize=(10.5, 4.6))
    card(fig)
    titles(fig, "Sharpe by year, out of sample",
           "2026 runs to each study's data end (September or October). Breakout and funding carry are flat in 2026; "
           "the BTC gate is not.", y=0.9)
    ax = fig.add_axes([0.07, 0.2, 0.9, 0.56])
    width = 0.24
    for i, (name, vals, _src) in enumerate(BY_YEAR):
        for j, v in enumerate(vals):
            x = i + (j - 1) * (width + 0.03)
            ax.bar(x, v, width=width, color=RAMP[j], zorder=3)
            ax.text(x, v + (0.05 if v >= 0 else -0.05), f"{v:.2f}", ha="center",
                    va="bottom" if v >= 0 else "top", fontsize=8.5, color=INK)
    ax.axhline(0, color=INK2, linewidth=0.8, zorder=4)
    ax.set_xticks(range(len(BY_YEAR)))
    ax.set_xticklabels([n for n, _, _ in BY_YEAR], fontsize=9.6, color=INK)
    ax.set_ylim(-0.8, 2.5)
    ax.grid(axis="y", color=GRID, linewidth=0.8, zorder=0)
    ax.tick_params(length=0, labelsize=9)
    ax.spines["bottom"].set_visible(False)
    handles = [Rectangle((0, 0), 1, 1, color=c) for c in RAMP]
    fig.legend(handles, ["2024", "2025", "2026"], loc="lower right", bbox_to_anchor=(0.965, 0.02), ncol=3,
               frameon=False, fontsize=9, handlelength=1.0, handleheight=1.0)
    footnote(fig, "Sources: results/gated_btc.md, results/m4_residual.md, results/funding_carry.md.")
    save(fig, "by_year.png")


def hero(rows: list[str], autopilots: int | None) -> None:
    fig = plt.figure(figsize=(12, 3.7))
    card(fig)
    failed = sum(1 for r in rows if VERDICTS[r] == "failed")
    fig.text(0.05, 0.66, "Pythia", fontsize=40, fontweight="bold", color=INK, va="bottom")
    fig.text(0.05, 0.6, "A paper-first trading cockpit that counts every try.", fontsize=15, color=INK2, va="top")
    chips = [
        (f"{len(rows)}", "studies run"),
        (f"{failed}", "failed, on the record"),
        (f"{POOL_NOW:,}", "trials deflated"),
    ]
    if autopilots:
        chips.append((f"{autopilots}", "paper autopilots"))
    x = 0.05
    for big, small in chips:
        fig.text(x, 0.22, big, fontsize=21, fontweight="bold", color=BLUE, va="bottom")
        fig.text(x, 0.19, small, fontsize=9.5, color=INK2, va="top")
        x += 0.115

    # The scoreboard as a strip: every tested strategy on one Sharpe axis.
    ax = fig.add_axes([0.56, 0.24, 0.40, 0.62])
    lanes = {BENCH: 3, PASS: 2, EXPERIMENT: 1, FAILED: 0}
    for label, sharpe, verdict, _cost, _src in SCOREBOARD:
        ax.plot(sharpe, lanes[verdict], "o", markersize=11, color=COLOR[verdict],
                markeredgecolor=SURFACE, markeredgewidth=1.6, zorder=3)
    ax.axvline(NOISE_BAR, color=INK, linewidth=1.3, linestyle=(0, (4, 3)))
    ax.text(NOISE_BAR - 0.06, 3.6, "noise bar", ha="right", fontsize=9, color=INK)
    ax.axvline(0, color=INK2, linewidth=0.8)
    ax.set_yticks(list(lanes.values()))
    ax.set_yticklabels(["Benchmark", "Passed, unconfirmed", "On paper", "Failed"], fontsize=9.5, color=INK2)
    ax.set_xlim(-1.3, 3.0)
    ax.set_ylim(-0.6, 4.0)
    ax.grid(axis="x", color=GRID, linewidth=0.8, zorder=0)
    ax.tick_params(length=0, labelsize=9)
    ax.spines["bottom"].set_visible(False)
    ax.set_xlabel("Out-of-sample Sharpe from 2024, net of costs", fontsize=9, color=INK2)
    save(fig, "hero.png")


def main() -> None:
    rows = lab_rows()
    data = os.environ.get("PYTHIA_DATA")
    info = forward(Path(data)) if data else None
    if not data:
        print("skip forward.png: set PYTHIA_DATA to the lab's data folder")
    scoreboard()
    research_funnel(rows)
    by_year()
    hero(rows, info["autopilots"] if info else None)


if __name__ == "__main__":
    main()
