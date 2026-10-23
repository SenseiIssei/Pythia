"""Every picture a card sends, in one look: dark surface, light ink, one blue
accent, green and red only for gains and losses, the same fonts, margins and
title block on each, sized for a phone.

render          the daily digest and the weekly report (1200 x 1440 px)
  top           equity of each running autopilot in % against BTC bought and
                held over the same span (dashed grey), the last value at the
                end of each line, moved apart so no two overlap
  bottom left   P&L per sleeve, green bars up, red bars down
  bottom right  what the autopilots hold, by value, with its share
render_trends   the CS2 Steam market summary (lab.cs2.trends): the median 7-day
                change by item group, and the day's top movers, in percent
render_trade    a closed pump.fun real-money trade (lab.pumpfun_rt.card): the
                coin's price around it as 5 s candles in % against the entry,
                entry and exit marked, take profit and stop dashed, the hold
                shaded green or red by outcome (1200 x 900 px)
render_curve    a cumulative P&L, e.g. the pump.fun day (1200 x 840 px)
render_overview the morning briefing (lab.ops.briefing): the autopilots against
                BTC and the pump.fun real-money P&L of the last days

lab.ops.notify builds the digest's data from the engine's GET /api/state
(notify.chart_data) and sends the file as a Telegram photo (and a Discord
attachment where the card goes there). Words, amounts and dates follow the
language of the messages (lang "en" or "de": 1.234,56 $, 15. Okt).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

try:  # inside the lab package
    from . import i18n
except ImportError:  # a copy next to notify.py and i18n.py
    import i18n  # type: ignore[no-redef]

try:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter
except Exception:  # noqa: BLE001 - notify sends without a chart then
    plt = None

# One dark look for every picture a card sends, readable on a phone at night and
# in daylight: the chart surface and ink of the dark theme, one blue accent, the
# categorical blue, orange, aqua, yellow for further lines, green and red only for
# gains and losses (and a trade's outcome).
BG = "#1a1a19"
INK = "#f0efec"
MUTED = "#c3c2b7"
FAINT = "#8a897f"
GRID = "#383835"
UP = "#2fb344"
DOWN = "#e66767"
FLAT = "#a3a29a"
ACCENT = "#3987e5"
# More autopilots than one: the accent first, then the other categorical hues in a fixed order.
LINE_COLORS = [ACCENT, "#d95926", "#199e70", "#c98500"]
SIZE_IN = (8.0, 9.6)
DPI = 150
FONT = {"font.family": "DejaVu Sans", "font.size": 10, "axes.titlesize": 11, "text.color": INK,
        "axes.labelcolor": MUTED, "xtick.color": MUTED, "ytick.color": MUTED}
# The common frame: the title and the subtitle at the same place on every picture.
LEFT, RIGHT, TITLE_Y, SUB_Y = 0.06, 0.94, 0.965, 0.925


def available() -> bool:
    return plt is not None


def _amount(a: float, small: str, lang: str) -> str:
    """A positive amount: $12.5k for 10,000 and up, else `small` (a format)
    of it; German 12,5 Tsd. $."""
    if a >= 10_000:
        return f"{i18n.num(a / 1000, 1, 'de')} Tsd. $" if lang == "de" else f"${a / 1000:,.1f}k"
    s = format(a, small)
    return f"{i18n.de_digits(s)} $" if lang == "de" else f"${s}"


def _money(v: float, lang: str = "en") -> str:
    """+$31.20, -$1,240, +$12.5k: a signed amount for a bar's end."""
    a = abs(v)
    return ("-" if v < 0 else "+") + _amount(a, ",.0f" if a >= 100 else ",.2f", lang)


def _tick_money(v: float, signed: bool, lang: str = "en") -> str:
    """An axis tick: $0, +$40, -$1.2k."""
    if abs(v) < 1e-9:
        return "0 $" if lang == "de" else "$0"
    a = abs(v)
    s = _amount(a, ",.0f" if a >= 10 else ",.1f", lang)
    return (("-" if v < 0 else "+") if signed else ("-" if v < 0 else "")) + s


def _plain_money(v: float, lang: str = "en") -> str:
    return _amount(v, ",.0f", lang)


def _pct_tick(v: float, lang: str = "en") -> str:
    """0 %, +3 %, +0.5 % (German +0,5 %)."""
    if abs(v) < 1e-9:
        return "0 %"
    s = f"{v:+.0f} %" if abs(v) >= 1 else f"{v:+.1f} %"
    return s.replace(".", ",") if lang == "de" else s


def _date_tick(d, lang: str = "en") -> str:
    """15 Oct, or 15. Okt."""
    return i18n.day_month(d, lang) if lang == "de" else d.strftime("%d %b")


def _style(ax) -> None:
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=MUTED, labelsize=9.5, length=0, pad=6)
    ax.set_facecolor(BG)


def _per_point(ax) -> float:
    """Data units of the y axis per typographic point."""
    lo, hi = ax.get_ylim()
    h = ax.get_window_extent().height * 72 / ax.figure.dpi
    return (hi - lo) / max(h, 1.0)


def _end_labels(ax, ends: list[tuple]) -> None:
    """A value at the end of each line, (x, y, colour, text): moved apart so no two
    overlap (at least 13 points), joined to its line by a short stroke in the
    line's colour; the text itself stays in ink."""
    if not ends:
        return
    gap = 13 * _per_point(ax)
    order = sorted(range(len(ends)), key=lambda i: ends[i][1])
    ys = [ends[i][1] for i in order]
    for k in range(1, len(ys)):
        ys[k] = max(ys[k], ys[k - 1] + gap)
    shift = (max(ys) - max(ends[i][1] for i in order)) / 2 if len(ys) > 1 else 0.0
    per = _per_point(ax)
    for k, i in enumerate(order):
        x, y, c, text = ends[i]
        ax.annotate(text, (x, y), xytext=(16, (ys[k] - shift - y) / per), textcoords="offset points",
                    va="center", ha="left", fontsize=10, fontweight="bold", color=INK,
                    arrowprops={"arrowstyle": "-", "color": c, "linewidth": 1.6, "shrinkA": 0, "shrinkB": 2})


def _frame(fig, title: str, subtitle: str = "") -> None:
    """The title and the subtitle, at the same place on every picture."""
    fig.text(LEFT, TITLE_Y, title if len(title) <= 60 else title[:59] + "…", fontsize=17, fontweight="bold",
             color=INK, ha="left", va="top")
    if subtitle:
        fig.text(LEFT, SUB_Y, subtitle if len(subtitle) <= 95 else subtitle[:94] + "…", fontsize=10.5,
                 color=MUTED, ha="left", va="top")


def _local(ms: int) -> datetime:
    from . import notify

    return notify.local_time(int(ms))


def _equity(ax, data: dict, lang: str = "en") -> None:
    _style(ax)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.axhline(0, color=MUTED, linewidth=0.8, alpha=0.6)
    span_ms = 0
    ends = []
    for i, ap in enumerate(data.get("autopilots") or []):
        pts = ap.get("points") or []
        if not pts:
            continue
        xs = [_local(t) for t, _ in pts]
        ys = [v for _, v in pts]
        span_ms = max(span_ms, pts[-1][0] - pts[0][0])
        color = LINE_COLORS[min(i, len(LINE_COLORS) - 1)]
        ax.plot(xs, ys, color=color, linewidth=2.4 if i == 0 else 1.6, solid_capstyle="round",
                label=ap.get("name") or "Autopilot", zorder=3)
        if i == 0:
            ax.fill_between(xs, ys, 0, color=ACCENT, alpha=0.06, zorder=1)
        ends.append((xs[-1], ys[-1], color))
    btc = data.get("btc") or []
    if btc:
        xs = [_local(t) for t, _ in btc]
        ax.plot(xs, [v for _, v in btc], color=MUTED, linewidth=1.4, linestyle=(0, (4, 3)),
                label=i18n.t("btc_hold", lang), zorder=2)
        ends.append((xs[-1], btc[-1][1], MUTED))
    _end_labels(ax, [(x, y, c, f"{i18n.num(y, 1, lang, sign=True)} %") for x, y, c in ends])
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: _pct_tick(v, lang)))
    if span_ms <= 2 * 86_400_000:
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    else:
        # The month by the language, not by the machine's locale.
        ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: _date_tick(mdates.num2date(v), lang)))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=3, maxticks=6))
    ax.margins(x=0.02)
    # Room on the right for the end labels.
    lo, hi = ax.get_xlim()
    ax.set_xlim(lo, hi + (hi - lo) * 0.12)
    leg = ax.legend(loc="upper left", frameon=True, fontsize=9, ncol=2, labelcolor=INK, handlelength=2.2,
                    facecolor=BG, edgecolor=BG, framealpha=0.85)
    if leg:
        for t in leg.get_texts():
            t.set_color(INK)


def _bars(ax, items: list[tuple[str, float]], title: str, signed: bool, empty: str, lang: str = "en") -> None:
    _style(ax)
    ax.set_title(title, loc="left", fontsize=11, color=INK, fontweight="bold", pad=10)
    if not items:
        ax.axis("off")
        ax.set_title(title, loc="left", fontsize=11, color=INK, fontweight="bold", pad=10)
        ax.text(0.5, 0.5, empty, ha="center", va="center", fontsize=11, color=MUTED, transform=ax.transAxes)
        return
    items = items[:7]
    labels = [lab if len(lab) <= 26 else lab[:25] + "…" for lab, _ in items][::-1]
    vals = [v for _, v in items][::-1]
    colors = [(UP if v >= 0 else DOWN) for v in vals] if signed else [ACCENT] * len(vals)
    y = list(range(len(vals)))
    ax.barh(y, vals, color=colors, height=0.42, alpha=0.9 if signed else 0.85, zorder=2)
    ax.set_yticks([])
    ax.spines["left"].set_visible(False)
    ax.grid(axis="x", color=GRID, linewidth=0.8, zorder=0)
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: _tick_money(v, signed, lang)))
    ax.xaxis.set_major_locator(matplotlib.ticker.MaxNLocator(3))
    total = sum(abs(v) for v in vals) or 1.0
    lo, hi = min(vals + [0.0]), max(vals + [0.0])
    pad = (hi - lo) * 0.5 or 1.0
    ax.set_xlim(lo - (pad if lo < 0 else 0), hi + pad)
    ax.set_ylim(-0.6, len(vals) - 0.1)
    if signed:
        ax.axvline(0, color=MUTED, linewidth=0.8, alpha=0.6)
    x0 = ax.get_xlim()[0]
    for yi, v, lab in zip(y, vals, labels):
        # The name sits above its bar, so a long one is never cut off.
        ax.text(x0, yi + 0.27, lab, ha="left", va="bottom", fontsize=9, color=INK)
        text = _money(v, lang) if signed else f"{_plain_money(v, lang)} · {abs(v) / total * 100:.0f} %"
        ax.annotate(text, (v, yi), xytext=(5 if v >= 0 else -5, 0), textcoords="offset points",
                    ha="left" if v >= 0 else "right", va="center", fontsize=9, color=INK)


def _pct_bars(ax, items: list[tuple[str, float]], title: str, empty: str, lang: str = "en") -> None:
    """Signed percent bars, green up and red down, the name above each bar."""
    _style(ax)
    ax.set_title(title, loc="left", fontsize=11, color=INK, fontweight="bold", pad=10)
    if not items:
        ax.axis("off")
        ax.text(0.5, 0.5, empty, ha="center", va="center", fontsize=11, color=MUTED, transform=ax.transAxes)
        return
    items = items[:8]
    labels = [lab if len(lab) <= 40 else lab[:39] + "…" for lab, _ in items][::-1]
    vals = [v for _, v in items][::-1]
    y = list(range(len(vals)))
    ax.barh(y, vals, color=[UP if v >= 0 else DOWN for v in vals], height=0.42, alpha=0.9, zorder=2)
    ax.set_yticks([])
    ax.spines["left"].set_visible(False)
    ax.grid(axis="x", color=GRID, linewidth=0.8, zorder=0)
    ax.xaxis.set_major_formatter(FuncFormatter(
        lambda v, _: "0 %" if abs(v) < 1e-9 else f"{i18n.num(v, 0, lang, sign=True)} %"))
    ax.xaxis.set_major_locator(matplotlib.ticker.MaxNLocator(4))
    lo, hi = min(vals + [0.0]), max(vals + [0.0])
    pad = (hi - lo) * 0.35 or 1.0
    ax.set_xlim(lo - (pad if lo < 0 else 0), hi + pad)
    ax.set_ylim(-0.6, len(vals) - 0.1)
    ax.axvline(0, color=MUTED, linewidth=0.8, alpha=0.6)
    x0 = ax.get_xlim()[0]
    for yi, v, lab in zip(y, vals, labels):
        ax.text(x0, yi + 0.27, lab, ha="left", va="bottom", fontsize=9, color=INK)
        ax.annotate(f"{i18n.num(v, 1, lang, sign=True)} %", (v, yi), xytext=(5 if v >= 0 else -5, 0),
                    textcoords="offset points", ha="left" if v >= 0 else "right", va="center", fontsize=9, color=INK)


TRENDS_SIZE_IN = (8.0, 8.0)
TRADE_SIZE_IN = (8.0, 6.0)        # 1200 x 900 px: a Telegram photo shows it whole on a phone
CURVE_SIZE_IN = (8.0, 5.6)        # 1200 x 840 px
OVERVIEW_SIZE_IN = (8.0, 8.8)     # 1200 x 1320 px


def _figure(size: tuple, path: Path | str):
    if plt is None:
        raise RuntimeError("matplotlib is not installed")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update(FONT)
    return path, plt.figure(figsize=size, dpi=DPI, facecolor=BG)


def _save(fig, path: Path) -> Path:
    try:
        fig.savefig(path, dpi=DPI, facecolor=BG)
    finally:
        plt.close(fig)
    return path


def render_trends(data: dict, path: Path | str, title: str, subtitle: str = "", lang: str = "en") -> Path:
    """The CS2 Steam market summary: median 7-day change by group on top,
    the day's top movers below. `data`: {"groups": [(name, pct)], "movers":
    [(name, pct)], "groups_title", "movers_title", "empty_groups",
    "empty_movers"}, the words already in `lang`."""
    path, fig = _figure(TRENDS_SIZE_IN, path)
    try:
        gs = fig.add_gridspec(2, 1, height_ratios=[1, 1], hspace=0.35, left=LEFT, right=RIGHT, top=0.83, bottom=0.05)
        _frame(fig, title, subtitle)
        _pct_bars(fig.add_subplot(gs[0]), data.get("groups") or [], data.get("groups_title") or "By group",
                  data.get("empty_groups") or "No group with enough items", lang)
        _pct_bars(fig.add_subplot(gs[1]), data.get("movers") or [], data.get("movers_title") or "Top movers",
                  data.get("empty_movers") or "No liquid item moved", lang)
    except Exception:
        plt.close(fig)
        raise
    return _save(fig, path)


def render(data: dict, path: Path | str, title: str, subtitle: str = "", lang: str = "en") -> Path:
    """Draw the chart to `path` (PNG) and return the path. `lang` ("en" or
    "de") is the language of its labels, amounts and dates."""
    path, fig = _figure(SIZE_IN, path)
    try:
        gs = fig.add_gridspec(2, 2, height_ratios=[1.45, 1], hspace=0.3, wspace=0.25,
                              left=0.1, right=RIGHT, top=0.86, bottom=0.06)
        _frame(fig, title, subtitle)
        _equity(fig.add_subplot(gs[0, :]), data, lang)
        _bars(fig.add_subplot(gs[1, 0]), sorted(data.get("sleeves") or [], key=lambda s: -s[1]),
              i18n.t("pnl_per_sleeve", lang), True, i18n.t("no_sleeves", lang), lang)
        _bars(fig.add_subplot(gs[1, 1]), data.get("positions") or [], i18n.t("positions", lang), False,
              i18n.t("in_cash", lang), lang)
    except Exception:
        plt.close(fig)
        raise
    return _save(fig, path)


# ---------------------------------------------------------------- a real-money trade and a day of them

def outcome_color(v: float | None) -> str:
    """Green for a gain, red for a loss, grey for break-even (within 0.5 %) or nothing."""
    if v is None or abs(v) < 0.005:
        return FLAT
    return UP if v > 0 else DOWN


def candles(points: list[tuple], step_ms: int = 5_000) -> list[tuple]:
    """(t, price) points as (bucket start ms, open, high, low, close) per `step_ms`."""
    out: list[list] = []
    for t, p in sorted((int(t), float(p)) for t, p, *_ in points if p and p > 0):
        b = t - t % step_ms
        if out and out[-1][0] == b:
            c = out[-1]
            c[2], c[3], c[4] = max(c[2], p), min(c[3], p), p
        else:
            out.append([b, p, p, p, p])
    return [tuple(c) for c in out]


def render_trade(data: dict, path: Path | str, title: str, subtitle: str = "", lang: str = "en") -> Path:
    """One closed trade: the coin's price around it as 5 s candles (a line when there are
    too few), in % against the entry price, the hold span shaded in the outcome's colour,
    entry and exit marked, take profit and stop as dashed lines.

    `data`: {"points": [(ms, price, ...)], "entry": (ms, price), "exit": (ms, price) or None,
    "tp": fraction (0.3 for +30 %) or None, "sl": fraction (0.2 for -20 %) or None,
    "ret": the trade's return as a fraction (the accent) or None}."""
    entry_ms, entry_px = data["entry"]
    ex = data.get("exit")
    accent = outcome_color(data.get("ret"))
    path, fig = _figure(TRADE_SIZE_IN, path)
    try:
        ax = fig.add_axes((0.1, 0.1, 0.72, 0.72))
        _frame(fig, title, subtitle)
        _style(ax)
        ax.grid(axis="y", color=GRID, linewidth=0.8, zorder=0)

        def pct(p: float) -> float:
            return (p / entry_px - 1) * 100

        def X(ms: int) -> float:                  # one unit on the time axis: matplotlib's date numbers
            return mdates.date2num(_local(ms))

        cs = candles(data.get("points") or [])
        if len(cs) >= 6:
            w = 5 / 86_400 * 0.7
            for b, o, h, lo, c in cs:
                x = X(b + 2_500)
                col = MUTED if c >= o else FAINT
                ax.vlines(x, pct(lo), pct(h), color=col, linewidth=0.9, zorder=2)
                y0, y1 = sorted((pct(o), pct(c)))
                ax.bar(x, max(y1 - y0, 0.0001), width=w, bottom=y0, color=col, edgecolor=col, linewidth=0.5, zorder=3)
        else:
            pts = sorted((int(t), float(p)) for t, p, *_ in data.get("points") or [] if p and p > 0)
            if pts:
                ax.plot([X(t) for t, _ in pts], [pct(p) for _, p in pts], color=MUTED, linewidth=2, zorder=3)
        x_in = X(entry_ms)
        ax.axhline(0, color=FAINT, linewidth=0.8, zorder=1)
        if ex is not None:
            x_out = X(ex[0])
            ax.axvspan(x_in, x_out, color=accent, alpha=0.12, zorder=0, linewidth=0)
        ys = [0.0]
        for c in cs:
            ys += [pct(c[2]), pct(c[3])]
        # The plan's lines, labelled inside the right edge.
        lines = []
        if data.get("tp") is not None:
            lines.append((data["tp"] * 100, UP, f"{i18n.t('prl_chart_tp', lang)} {i18n.num(data['tp'] * 100, 0, lang, True)} %"))
        if data.get("sl") is not None:
            lines.append((-data["sl"] * 100, DOWN, f"{i18n.t('prl_chart_sl', lang)} {i18n.num(-data['sl'] * 100, 0, lang, True)} %"))
        for y, col, _ in lines:
            ax.axhline(y, color=col, linewidth=1.2, linestyle=(0, (5, 4)), alpha=0.9, zorder=1)
            ys.append(y)
        if ex is not None:
            ys.append(pct(ex[1]))
        lo, hi = min(ys), max(ys)
        pad = (hi - lo) * 0.12 or 1.0
        ax.set_ylim(lo - pad, hi + pad)
        ax.margins(x=0.03)
        for y, col, text in lines:
            ax.annotate(text, (1.0, y), xycoords=("axes fraction", "data"), xytext=(6, 0), textcoords="offset points",
                        ha="left", va="center", fontsize=9.5, color=MUTED)
        ax.scatter([x_in], [0.0], marker="^", s=120, color=INK, edgecolor=BG, linewidth=1.5, zorder=5)
        marks = [(x_in, 0.0, f"{i18n.t('prl_chart_entry', lang)}", INK)]
        if ex is not None:
            y_out = pct(ex[1])
            ax.scatter([X(ex[0])], [y_out], marker="v", s=140, color=accent, edgecolor=BG, linewidth=1.5, zorder=5)
            marks.append((X(ex[0]), y_out, f"{i18n.t('prl_chart_exit', lang)} {i18n.num(y_out, 1, lang, True)} %",
                          INK))
        # Entry label below its marker, the exit's above or below its marker away from the entry's.
        for k, (x, y, text, col) in enumerate(marks):
            up = k == 1 and y >= 0
            ax.annotate(text, (x, y), xytext=(0, 12 if up else -16), textcoords="offset points",
                        ha="center", va="bottom" if up else "top", fontsize=9.5, fontweight="bold", color=col,
                        zorder=6)
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: _pct_tick(v, lang)))
        lo_x, hi_x = ax.get_xlim()
        span_s = (hi_x - lo_x) * 86_400
        step = next((k for k in (5, 10, 15, 30, 60, 120, 300, 600, 900, 1800) if span_s / k <= 5), 3600)
        ax.xaxis.set_major_locator(mdates.SecondLocator(bysecond=range(0, 60, step)) if step < 60 else
                                   mdates.MinuteLocator(byminute=range(0, 60, step // 60)) if step < 3600 else
                                   mdates.HourLocator())
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S" if step < 60 else "%H:%M"))
    except Exception:
        plt.close(fig)
        raise
    return _save(fig, path)


def _curve(ax, points: list[tuple[int, float]], unit: str, lang: str = "en", dp: int = 3) -> None:
    """A cumulative amount as a step line from 0, green above and red below, the last value at its end."""
    _style(ax)
    ax.grid(axis="y", color=GRID, linewidth=0.8, zorder=0)
    ax.axhline(0, color=FAINT, linewidth=0.8, zorder=1)
    pts = sorted(points)
    xs = [_local(t) for t, _ in pts]
    ys = [v for _, v in pts]
    if len(xs) == 1:
        xs, ys = [xs[0], xs[0]], [0.0, ys[0]]
    last = ys[-1] if ys else 0.0
    col = outcome_color(last if abs(last) >= 1e-9 else None) if ys else FLAT
    if xs:
        ax.step(xs, ys, where="post", color=col, linewidth=2.2, zorder=3)
        ax.fill_between(xs, ys, 0, step="post", where=[y >= 0 for y in ys], color=UP, alpha=0.12, zorder=2)
        ax.fill_between(xs, ys, 0, step="post", where=[y < 0 for y in ys], color=DOWN, alpha=0.12, zorder=2)
        ax.scatter(xs[-1:], ys[-1:], s=36, color=col, zorder=4)
    ax.margins(x=0.03, y=0.15)
    lo, hi = ax.get_xlim()
    ax.set_xlim(lo, hi + (hi - lo) * 0.14)
    if xs:
        _end_labels(ax, [(xs[-1], ys[-1], col, f"{i18n.num(ys[-1], dp, lang, True)} {unit}")])
    ax.yaxis.set_major_formatter(FuncFormatter(
        lambda v, _: "0" if abs(v) < 1e-12 else i18n.num(v, dp if abs(v) < 1 else 2, lang, True)))
    span = (pts[-1][0] - pts[0][0]) if len(pts) > 1 else 0
    if span <= 2 * 86_400_000:
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    else:
        ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: _date_tick(mdates.num2date(v), lang)))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=3, maxticks=6))


def render_curve(points: list[tuple[int, float]], path: Path | str, title: str, subtitle: str = "",
                 lang: str = "en", unit: str = "SOL") -> Path:
    """A cumulative P&L over a day (or longer): [(ms, running total)] as a step line."""
    path, fig = _figure(CURVE_SIZE_IN, path)
    try:
        ax = fig.add_axes((0.12, 0.11, 0.74, 0.7))
        _frame(fig, title, subtitle)
        _curve(ax, points, unit, lang)
    except Exception:
        plt.close(fig)
        raise
    return _save(fig, path)


def render_overview(data: dict, path: Path | str, title: str, subtitle: str = "", lang: str = "en") -> Path:
    """The morning briefing's one picture: the autopilots' equity in % against BTC on top
    (data as for render: "autopilots", "btc", "equity_title"), and when there is one the
    pump.fun real-money P&L of the last days below ("pumpfun": [(ms, running SOL)],
    "pumpfun_title"). A panel without data is left out; with neither, it says "empty"."""
    pf = data.get("pumpfun") or []
    eq = bool(data.get("autopilots"))
    path, fig = _figure(OVERVIEW_SIZE_IN if eq and pf else CURVE_SIZE_IN, path)
    try:
        _frame(fig, title, subtitle)
        n = int(eq) + int(bool(pf))
        gs = fig.add_gridspec(max(n, 1), 1, height_ratios=[1.5, 1][:n] if n == 2 else None, hspace=0.32,
                              left=0.12, right=0.86, top=0.85 if n == 2 else 0.8, bottom=0.06 if n == 2 else 0.11)
        k = 0
        if eq:
            top = fig.add_subplot(gs[k])
            k += 1
            _equity(top, data, lang)
            top.set_title(data.get("equity_title") or "", loc="left", fontsize=11, color=INK, fontweight="bold", pad=10)
        if pf:
            ax = fig.add_subplot(gs[k])
            _curve(ax, pf, "SOL", lang)
            ax.set_title(data.get("pumpfun_title") or "pump.fun", loc="left", fontsize=11, color=INK,
                         fontweight="bold", pad=10)
        if not n:
            fig.text(0.5, 0.45, data.get("empty") or "", ha="center", va="center", fontsize=11, color=MUTED)
    except Exception:
        plt.close(fig)
        raise
    return _save(fig, path)
