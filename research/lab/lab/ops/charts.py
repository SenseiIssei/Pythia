"""The picture that goes with the daily digest and the weekly report.

One PNG, sized for a phone (1200 x 1440 px), in the app's light look: white
background, near-black ink, one blue accent, green and red only for gains
and losses.

  top          equity of each running autopilot in % against BTC bought and
               held over the same span (dashed grey), the last value at the
               end of each line
  bottom left  P&L per sleeve, green bars up, red bars down
  bottom right what the autopilots hold, by value, with its share

lab.ops.notify builds the data from the engine's GET /api/state
(notify.chart_data) and sends the file as a Telegram photo. Its words,
amounts and dates follow the language of the messages (lang "en" or "de":
1.234,56 $, 15. Okt).
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

INK = "#0b0b0d"
MUTED = "#5f5f6b"
GRID = "#e6e6ea"
UP = "#0a7d3b"
DOWN = "#c8102e"
ACCENT = "#2563eb"
# More autopilots than one: the accent first, then ink tones.
LINE_COLORS = [ACCENT, INK, "#7c7c88", "#a8a8b3"]
SIZE_IN = (8.0, 9.6)
DPI = 150


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
    ax.tick_params(colors=MUTED, labelsize=9, length=0, pad=6)
    ax.set_facecolor("white")


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
    for x, y, c in ends:
        ax.annotate(f"{i18n.num(y, 1, lang, sign=True)} %", (x, y), xytext=(6, 0), textcoords="offset points",
                    va="center", fontsize=10, fontweight="bold", color=c)
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
    leg = ax.legend(loc="upper left", frameon=False, fontsize=9, ncol=2, labelcolor=INK, handlelength=2.2)
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


def render(data: dict, path: Path | str, title: str, subtitle: str = "", lang: str = "en") -> Path:
    """Draw the chart to `path` (PNG) and return the path. `lang` ("en" or
    "de") is the language of its labels, amounts and dates."""
    if plt is None:
        raise RuntimeError("matplotlib is not installed")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({"font.family": "DejaVu Sans", "axes.titlesize": 11, "font.size": 10})
    fig = plt.figure(figsize=SIZE_IN, dpi=DPI, facecolor="white")
    try:
        gs = fig.add_gridspec(2, 2, height_ratios=[1.45, 1], hspace=0.3, wspace=0.25,
                              left=0.1, right=0.95, top=0.86, bottom=0.06)
        fig.text(0.06, 0.955, title, fontsize=16, fontweight="bold", color=INK, ha="left", va="top")
        if subtitle:
            fig.text(0.06, 0.915, subtitle, fontsize=10.5, color=MUTED, ha="left", va="top")
        _equity(fig.add_subplot(gs[0, :]), data, lang)
        _bars(fig.add_subplot(gs[1, 0]), sorted(data.get("sleeves") or [], key=lambda s: -s[1]),
              i18n.t("pnl_per_sleeve", lang), True, i18n.t("no_sleeves", lang), lang)
        _bars(fig.add_subplot(gs[1, 1]), data.get("positions") or [], i18n.t("positions", lang), False,
              i18n.t("in_cash", lang), lang)
        fig.savefig(path, dpi=DPI, facecolor="white")
    finally:
        plt.close(fig)
    return path
