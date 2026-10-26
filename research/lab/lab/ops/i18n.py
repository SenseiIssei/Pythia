"""The language of the messages to the owner's chat: English or German.

Only what goes to Telegram (or the alert webhook) follows the language; the
app, the reports, the logs and the repo stay in English. The language comes
from PYTHIA_ALERT_LANG (en or de) or else from "language" in
reports/notify/settings.json, which the engine writes from the app's setting
(notify.alert_lang reads both). English is the default.

Every message is a key in CATALOG with one text per language, formatted with
str.format; a text that depends on a count is a pair (one, many). A new
message is one more key in both languages (test_i18n checks that every key
has both and the same placeholders).

Numbers shown to the owner follow the language: $1,234.56 and +3.20 % in
English, 1.234,56 $ and +3,20 % in German; days as "Thu 15 Oct" or
"Do 15. Okt"; times in Europe/Berlin.

Standard library only: notify.py imports it from next to itself on the host.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timezone

LANGS = ("en", "de")
ENV = "PYTHIA_ALERT_LANG"

WEEKDAYS = {"en": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
            "de": ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]}
MONTHS = {"en": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
          "de": ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"]}


def parse(v) -> str | None:
    """en, de, english, deutsch, german, de-DE; case ignored; None for anything else."""
    k = str(v or "").strip().lower().replace("_", "-").split("-")[0]
    return {"en": "en", "english": "en", "englisch": "en", "de": "de", "deutsch": "de", "german": "de"}.get(k)


# ---------------------------------------------------------------- numbers

def de_digits(s: str) -> str:
    """An English number in German: 1,234.56 as 1.234,56; n/a as k. A."""
    if s == "n/a":
        return "k. A."
    return s.translate(str.maketrans({",": ".", ".": ","}))


def num(v: float, dp: int = 2, lang: str = "en", sign: bool = False) -> str:
    """12,345.68 or 12.345,68; with sign, +12.3 or -12.3."""
    s = f"{v:{'+' if sign else ''},.{dp}f}"
    return de_digits(s) if lang == "de" else s


def money(v: float, dp: int = 2, lang: str = "en") -> str:
    """$12,345.68 or 12.345,68 $; a negative amount -$12.30 or -12,30 $; never minus zero."""
    s = f"{abs(v):,.{dp}f}"
    neg = v < 0 and any(c not in "0.," for c in s)
    if lang == "de":
        return f"{'-' if neg else ''}{de_digits(s)} $"
    return f"{'-' if neg else ''}${s}"


def signed_money(v: float, dp: int = 2, lang: str = "en") -> str:
    """+$12.30 or +12,30 $."""
    m = money(v, dp, lang)
    return m if m.startswith("-") else f"+{m}"


def signed_pct(v: float | None, dp: int = 2, lang: str = "en") -> str:
    """+1.20 % or +1,20 %; n/a (k. A.) for nothing; never minus zero."""
    if v is None:
        return "k. A." if lang == "de" else "n/a"
    s = f"{v:+,.{dp}f}"
    if s.startswith("-") and not any(c not in "-0.," for c in s):
        s = "+" + s[1:]
    return f"{de_digits(s) if lang == 'de' else s} %"


def frac_pct(v: float, dp: int = 1, lang: str = "en", sign: bool = True) -> str:
    """A fraction as a %: 0.123 as +12.3% (English, as the lab writes it) or +12,3 %."""
    if lang == "de":
        return f"{num(v * 100, dp, 'de', sign)} %"
    return f"{v:{'+' if sign else ''}.{dp}%}"


def eur(v: float, dp: int = 2, lang: str = "en", sign: bool = False) -> str:
    """€1.98 or 1,98 €; with sign +€1.98 or +1,98 €; never minus zero."""
    s = f"{abs(v):,.{dp}f}"
    neg = v < 0 and any(c not in "0.," for c in s)
    head = "-" if neg else ("+" if sign else "")
    return f"{head}{de_digits(s)} €" if lang == "de" else f"{head}€{s}"


def sol(v: float, dp: int = 4, lang: str = "en", sign: bool = False) -> str:
    """0.0525 SOL or 0,0525 SOL; with sign +0.0113 SOL; never minus zero."""
    s = num(v, dp, lang, sign)
    if s.startswith("-") and not any(c not in "-0.," for c in s):
        s = ("+" if sign else "") + s[1:]
    return f"{s} SOL"


def duration(s: float, lang: str = "en") -> str:
    """42 s, 4 min 59 s, 1 h 05 min (German the same, Std. for hours)."""
    s = max(int(round(s)), 0)
    if s < 60:
        return f"{s} s"
    if s < 3600:
        return f"{s // 60} min {s % 60} s" if s % 60 else f"{s // 60} min"
    return f"{s // 3600} {'Std.' if lang == 'de' else 'h'} {(s % 3600) // 60:02d} min"


def secs(ms: float, lang: str = "en") -> str:
    """A latency: 850 ms, 1.4 s (German 1,4 s), 12 s."""
    ms = max(float(ms), 0.0)
    if ms < 1000:
        return f"{ms:.0f} ms"
    return f"{num(ms / 1000, 1 if ms < 10_000 else 0, lang)} s"


def times(v: float, dp: int = 1, lang: str = "en") -> str:
    """2.5x or 2,5x."""
    s = f"{v:.{dp}f}x"
    return s.replace(".", ",") if lang == "de" else s


def short_money(v: float | None, lang: str = "en") -> str:
    """$1.2B, $3.4M, $12.0k, $950; German 1,2 Mrd. $, 3,4 Mio. $, 12,0 Tsd. $, 950 $."""
    if v is None:
        return "k. A." if lang == "de" else "n/a"
    units = {"en": (("B", 1e9), ("M", 1e6), ("k", 1e3)), "de": ((" Mrd.", 1e9), (" Mio.", 1e6), (" Tsd.", 1e3))}
    for unit, d in units["de" if lang == "de" else "en"]:
        if abs(v) >= d:
            return f"{v / d:.1f}{unit} $".replace(".", ",", 1) if lang == "de" else f"${v / d:.1f}{unit}"
    return f"{v:.0f} $" if lang == "de" else f"${v:.0f}"


def plain_num(v: float, lang: str = "en", spec: str = ".8g") -> str:
    """A number in a given format without grouping, the decimal mark per language."""
    s = format(v, spec)
    return s.replace(".", ",") if lang == "de" else s


# ---------------------------------------------------------------- dates

def day_label(d: date | datetime, lang: str = "en") -> str:
    """Thu 15 Oct, or Do 15. Okt."""
    wd, m = WEEKDAYS[_l(lang)][d.weekday()], MONTHS[_l(lang)][d.month - 1]
    return f"{wd} {d.day}. {m}" if lang == "de" else f"{wd} {d.day} {m}"


def day_month(d: date | datetime, lang: str = "en") -> str:
    """15 Oct, or 15. Okt."""
    m = MONTHS[_l(lang)][d.month - 1]
    return f"{d.day}. {m}" if lang == "de" else f"{d.day} {m}"


def span(a: date | datetime, b: date | datetime, lang: str = "en") -> str:
    """9 to 15 Oct, 28 Sep to 4 Oct; German 9. bis 15. Okt, 28. Sep bis 4. Okt."""
    ma, mb = MONTHS[_l(lang)][a.month - 1], MONTHS[_l(lang)][b.month - 1]
    if lang == "de":
        return f"{a.day}. bis {b.day}. {mb}" if a.month == b.month else f"{a.day}. {ma} bis {b.day}. {mb}"
    return f"{a.day} to {b.day} {mb}" if a.month == b.month else f"{a.day} {ma} to {b.day} {mb}"


def iso_day(s: str, lang: str = "en") -> str:
    """2026-10-15 as is in English, Do 15. Okt in German."""
    if lang != "de":
        return s
    try:
        return day_label(date.fromisoformat(str(s)[:10]), lang)
    except ValueError:
        return s


def when_iso(at: str | None, lang: str = "en", local=None) -> str:
    """A UTC time stamp (2026-10-15T08:00:00Z) as is in English, as Do 15. Okt, 10:00
    Europe/Berlin in German. `local(ms)` turns ms into the wall clock (notify.local_time)."""
    if lang != "de" or not at:
        return str(at)
    try:
        t = datetime.strptime(str(at), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return str(at)
    lt = local(int(t.timestamp() * 1000)) if local else t
    return f"{day_label(lt, lang)}, {lt.hour:02d}:{lt.minute:02d}"


def _l(lang: str) -> str:
    return lang if lang in LANGS else "en"


# ---------------------------------------------------------------- the catalog

CATALOG: dict[str, dict[str, str | tuple[str, str]]] = {
    "en": {
        # cards and posts
        "more_rows": "+{n} more",
        "more_in_app": "+{n} more in the app",
        "more_in_reports": "(more in the reports)",
        # the daily digest
        "today": "Today",
        "since_start": "Since start",
        # the table of autopilots (daily and weekly)
        "tbl_autopilot": "Autopilot",
        "tbl_value": "Value",
        "tbl_today": "Today",
        "tbl_week": "Week",
        "tbl_start": "Start",
        "tbl_vs_btc": "±BTC",
        "tbl_vs_gated": "±G",
        "tbl_legend": "Value in $, Today and Start in %, ±BTC in points against BTC since start",
        "tbl_legend_gated": ("Value in $, Today and Start in %, ±BTC in points against BTC since start, "
                             "±G against BTC held only above its 200-day average"),
        "tbl_legend_week": "Value in $, Week and Start in %, ±BTC in points against BTC this week",
        "tbl_all_mode": "; all {mode}",
        "tbl_account": "; account {account}: {names}",
        "act_orders": ("{n} order filled", "{n} orders filled"),
        "act_closed": ("{n} position closed", "{n} positions closed"),
        "act_fees": "fees {fees}",
        "deepest": "deepest {name} {pct}",
        "forward_test": "Forward test",
        "no_report": "no report",
        "no_paper_books": "no paper books",
        "fw_on_track": "✅ on track",
        "fw_ok": "✅ ok",
        "fw_watch": "👀 watch",
        "fw_early": "🌱 early",
        "fw_below": "🔻 below",
        "fw_behind": "🔻 behind",
        "fw_unknown": "unknown",
        # the exit shadow (lab.paper.exit_shadow), only on a day a test changes status
        "xs_lead": "Exit rules (shadow)",
        "xs_m14": "M14 exit on tsmom_tranches",
        "xs_time40": "40-day stop on the three crypto books",
        "xs_collecting": "{test} started recording",
        "xs_passed": "{test} passed its forward test; nothing trades on it until you decide",
        "xs_failed": "{test} failed its forward test and stays a record",
        "health": "Health",
        "no_health": "no health check found",
        "last_check": " (last check {h} h ago)",
        "all_green": "✅ all green{late}",
        "n_red": "🔴 {n} red: {names}{late}",
        "no_learning": "No learning report found.",
        "running_today": ("{n} autopilot running, {money} today {dot}", "{n} autopilots running, {money} today {dot}"),
        "running": ("{n} autopilot running.", "{n} autopilots running."),
        "btc_24h_suffix": " · BTC 24 h {pct}",
        "btc_week_suffix": " · BTC this week {pct}",
        "none_running": "No autopilot running{err}.",
        "learning": "Learning",
        "stale_learning": "the last report is from {gen}, not today's",
        "daily_title": "Daily · {day}",
        "chart_since_start": "Equity since start",
        # the weekly report
        "weekly_title": "Weekly · {span}",
        "no_engine": "The engine did not answer: no numbers this week.",
        "no_autopilot": "No autopilot is running.",
        "this_week": "This week",
        "below_peak": "Below peak",
        "best_sleeve": "Best sleeve",
        "best_worst": "{best} {best_money} · worst {worst} {worst_money}",
        "weekly_summary": ("{n} autopilot: {money} this week {dot}", "{n} autopilots: {money} this week {dot}"),
        "chart_this_week": "Equity this week",
        "ai_week_lead": "Claude API",
        "ai_week": "{money} this week, {avg} a day: {jobs}",
        # the research director (lab.ai.director)
        "dir_title": ("Research director: {n} study draft", "Research director: {n} study drafts"),
        "dir_summary": "Pre-registration drafts for you to decide on; nothing runs them. Files in {where}. Cost {cost}.",
        "dir_stop": "Stop doing",
        # the strategy critic (lab.ai.critic)
        "critic_title": ("Strategy check: {n} finding", "Strategy check: {n} findings"),
        "critic_summary": "Yesterday's trades of each autopilot against its rules. Reply /real ID or /notreal ID to score a finding.",
        "critic_confirmed": "the numbers confirm it",
        "critic_unconfirmed": "the numbers do not confirm it",
        "critic_unchecked": "not checkable from the numbers",
        "critic_marked": "Finding {id} marked as {verdict}. It counts toward the critic's score.",
        "critic_unknown": "There is no finding {id}.",
        "critic_real": "real",
        "critic_notreal": "not real",
        # questions in the chat (lab.ai.chat)
        "ask_help": ("Ask me anything about Pythia: the autopilots, the lab's reports, the market. I read the same "
                     "facts as the daily brief and answer in your language. I never trade, change settings or show "
                     "secrets. /real ID or /notreal ID scores a strategy check finding."),
        "ask_refuse_trade": ("I only answer questions. I cannot place, change or cancel orders, start or stop an "
                             "autopilot, or change any setting: that stays in the app, with you."),
        "ask_refuse_secret": "I never show keys, tokens, passwords, chat ids or server details.",
        "ask_limit": "That was the last of today's {n} questions. Ask again tomorrow (UTC).",
        "ask_failed": "No answer this time ({why}). Nothing was changed.",
        "ask_footer": "{model} · {cost} · {n} of {limit} today",
        # quiet hours and the health alarm
        "quiet_over": "Quiet hours are over",
        "held_summary": ("{n} lab post was held back from {start} to {end}.",
                         "{n} lab posts were held back from {start} to {end}."),
        "held_group": ("{title}", "{n}, the last {title}"),
        "other_posts": "Other",
        "health_green": "Health check all green again",
        "since_check": "Since the check at {at}.",
        "health_red": "Health check red for {n} runs",
        "checks_not_ok": ("{n} check not ok at {at}.", "{n} checks not ok at {at}."),
        "no_check_named": "no check named",
        # job alerts (jobs.py)
        "job_failed": "job {name} {status} (exit {code}) after {s} s; log {log}",
        "job_ok_again": "job {name} ok again",
        "job_status_failed": "failed",
        "job_status_timeout": "timeout",
        # the chart
        "btc_hold": "BTC buy and hold",
        "pnl_per_sleeve": "P&L per sleeve",
        "no_sleeves": "No sleeves",
        "positions": "Positions",
        "in_cash": "In cash",
        # CS2
        "cs2_head": "{prefix} CS2: {n} to look at (paper only, trade by hand if at all)",
        "cs2_gap": "Gap",
        "cs2_drop": "Drop",
        "cs2_more": "... and {n} more on the CS2 page",
        "cs2_to_steam": "buy on Skinport at {ask}, list on Steam at {list}: {v} after fees, paid in Steam wallet funds",
        "cs2_to_skinport": "buy on Steam at {ask}, list on Skinport at {list}: {v} after fees, cash after the 7-day trade lock",
        "cs2_drop_text": "now {ref}, {why}, {vs30} against its 30-day median ({n} sales in 7 days)",
        "cs2_why_24h": "{d} in 24 h",
        "cs2_why_7d": "{d} against its 7-day median",
        "cs2_verdict": "Paper {ret} since start, {n} positions.",
        "cs2_weekly": "{prefix} CS2 weekly: {verdict} {n} paper trades. Details on the CS2 page.",
        # Pokemon
        "pk_head": "{prefix} cards {today}",
        "pk_moves": "Strong moves:",
        "pk_move_line": "- {name} ({set}): {move} {basis}, now {price}",
        "pk_basis_last": "since the last snapshot",
        "pk_basis_7d": "over 7 days",
        "pk_basis_cm": "Cardmarket 1-day vs 7-day average",
        "pk_cheap": "Cheap next to similar cards{note}:",
        "pk_unvalidated": " (fair-value model only; the return forecast is not validated yet)",
        "pk_uv_line": "- {name} ({set}): {price}, fair {fair} ({gap}), 90 d forecast {pred}",
        "pk_foot": "Data and paper only; nothing is bought or sold.",
        # Pokemon alert cards, what a buyer needs per card (lab.pokemon.alerts)
        "pk_na": "n/a",
        "pk_date_na": "date n/a",
        "pk_ungraded": "ungraded",
        "pk_printing": ", {v} printing",
        "pk_now": "Now {price} ({src}, {date})",
        "pk_src_tcg": "TCGplayer market",
        "pk_src_cm_usd": "Cardmarket trend in USD",
        "pk_no_cm": " · no Cardmarket price",
        "pk_cm": " · Cardmarket {trend} trend",
        "pk_cm_avg": ", {avg} avg sell",
        "pk_stale": ", ⚠️ {n} days old, stale",
        "pk_stale_undated": ", ⚠️ undated, stale",
        "pk_fair": "Fair {fair} ({gap} vs price)",
        "pk_forecast": "forecast 30 d {p30}, 90 d {p90}",
        "pk_trust": "trust: {words}",
        "pk_trust_tested_h": "{h} d tested",
        "pk_trust_ic": ", rank IC {ic} over {m} months",
        "pk_trust_tested": "tested out of sample ({parts})",
        "pk_trust_mixed": "{parts}; the other horizon an untested rule",
        "pk_trust_partly": "partly tested",
        "pk_trust_low": "low, an untested rule (fair-value gap)",
        "pk_trust_none": "no fair value or forecast: the card API does not price this set yet",
        "pk_moved": "Moved {move} {basis}",
        "pk_change": "Change {bits}",
        "pk_d": "{h} d",
        "pk_no_change": "No price change yet: our history starts with the first snapshot",
        "pk_link_cm": "Cardmarket",
        "pk_link_cm_search": "Cardmarket search",
        "pk_link_tp": "TCGplayer",
        "pk_link_tp_search": "TCGplayer search",
        "pk_moves_title": ("{n} card moved strongly", "{n} cards moved strongly"),
        "pk_moves_why": "Worth $20 or more and moved 20 % since the last snapshot or 35 % in 7 days.",
        "pk_uv_title": ("{n} card cheap next to similar ones", "{n} cards cheap next to similar ones"),
        "pk_uv_why": "Priced at a third to a half of what similar cards cost, positive 90-day forecast. ",
        "pk_uv_validated": "The forecast is validated.",
        "pk_uv_unvalidated": "Fair-value model only; the return forecast is not validated yet.",
        "pk_new_title": "New set: {set}",
        "pk_new_why": ("Released {released} ({when}), {n} singles priced on TCGplayer. The dearest five; prices of "
                       "a set this new swing hard."),
        "pk_out_in": "out in {n} days",
        "pk_out_today": "out today",
        "pk_out_since": "out {n} days",
        "pk_album_moves": "Strong moves",
        "pk_album_uv": "Cheap next to similar cards",
        "pk_card_foot": "Information only; nothing is bought or sold. You trade by hand.",
        "pk_new_set_line": "New set {set}: dearest {name} {price}",
        # CS2 Steam market trends (lab.cs2.trends)
        "ct_basis_snap": "against our snapshot of {day}",
        "ct_basis_w7": "24-hour average against the 7-day average",
        "ct_basis_w30": "24-hour average against the 30-day average",
        "ct_basis_none": "no earlier snapshot",
        "ct_group_case": "case",
        "ct_group_capsule": "capsule",
        "ct_group_sticker": "sticker",
        "ct_group_sticker_slab": "sticker slab",
        "ct_group_knife_or_glove": "knife or glove",
        "ct_group_skin": "skin",
        "ct_group_other": "other",
        "ct_lean_momentum": "momentum",
        "ct_lean_reversion": "mean reversion",
        "ct_lean_neither": "neither",
        "ct_lean_n/a": "n/a",
        "ct_event_release": "release",
        "ct_event_first_seen": "first seen",
        "ct_event_operation_start": "operation start",
        "ct_event_operation_end": "operation end",
        "ct_event_left_drop_pool": "left the drop pool",
        "ct_event_entered_drop_pool": "entered the drop pool",
        "ct_head_mover": "{v} {basis}",
        "ct_since_yesterday": "since yesterday's snapshot",
        "ct_head_case": "{v} in 7 days",
        "ct_head_new": "first seen on the Steam market today",
        "ct_head_cash": "buy on Steam, sell on Skinport: {v} after fees, cash",
        "ct_head_premium": "Steam {v} over Skinport, group usually {usual}; Skinport to Steam {w} after fees, in wallet funds",
        "ct_sp_ask": "Skinport ask {ask}",
        "ct_sp_sales": ", {n} sales in 7 d",
        "ct_item_prices": "Steam {steam} (24 h average) · {sp} · 7 d {c7} · 30 d {c30}",
        "ct_link_steam": "Steam market",
        "ct_kind_mover": "Moved",
        "ct_kind_new_drop": "New case or capsule",
        "ct_kind_case_rise": "Case rising",
        "ct_kind_spread": "Unusual spread",
        "ct_more": "{n} more on the CS2 page",
        "ct_alert_title": "CS2 Steam market: {title}",
        "ct_alert_summary": ("{n} thing worth a look by hand. Steam pays sellers in wallet funds, not cash.",
                             "{n} things worth a look by hand. Steam pays sellers in wallet funds, not cash."),
        "ct_foot": "Information only; nothing is bought or sold.",
        "ct_sum_title": "CS2 Steam market · {day}",
        "ct_sum_items": "{items} items with a Steam price, {liquid} liquid; ",
        "ct_sum_top": "top mover {name} {v}",
        "ct_sum_no_up": "no liquid item up",
        "ct_sum_drop": ", biggest drop {name} {v}",
        "ct_sum_days": (". {n} day of Steam snapshots.", ". {n} days of Steam snapshots."),
        "ct_col_group": "Group",
        "ct_col_items": "Items",
        "ct_col_premium": "Steam vs SP",
        "ct_table_groups": "Liquid items, medians",
        "ct_col_mover": "Mover",
        "ct_col_move": "Move",
        "ct_table_movers": "Top movers ({basis})",
        "ct_mom_snap_lead": "Momentum, our snapshots:",
        "ct_mom_snap": "IC {ic} over {n} days, t {t}: leans {lean}",
        "ct_mom_win_lead": "Momentum, from the averages:",
        "ct_mom_win": "IC {ic} on {n} items: leans {lean} (one snapshot, a hint)",
        "ct_drop_lead": "Last drop:",
        "ct_drop_line": "{items} ({kind}, {day}, {n} days ago); other cases {others}",
        "ct_drop_since": "{v} since",
        "ct_drop_window": "7 d {c7}, 30 d {c30}",
        "ct_rising_lead": "Cases up 15 %+ in 7 d:",
        "ct_spread_lead": "Spread after fees:",
        "ct_spread_line": ("Steam {p} over Skinport (median); Skinport to Steam nets {w} in wallet funds, "
                           "Steam to Skinport {c} in cash"),
        "ct_sum_foot": "Steam prices from csgotrader.app's public file. Information only.",
        "ct_chart_title": "CS2 Steam market",
        "ct_chart_sub": "{day} · 7 days: {basis}",
        "ct_chart_sub_movers": " · movers: {basis}",
        "ct_chart_groups": "Median 7-day change by group, liquid items",
        "ct_chart_movers": "Top movers of the day",
        "ct_chart_no_groups": "No group with enough items",
        "ct_chart_no_movers": "No liquid item moved",
        # listings
        "ls_msg": "{prefix} new listing: {line}\nInformation only: nothing is bought.",
        "ls_announced": "{venue}: {title}. Alpaca: {alpaca}.",
        "ls_line_coin": "{venue} new coin {base}: {syms}. Alpaca: {alpaca}.{price}",
        "ls_line_pair": "{venue} new pair {base}: {syms}. Alpaca: {alpaca}.{price}",
        "ls_and_more": " and {n} more",
        "ls_first_price": " First price {price} {quote} ({symbol}).",
        "ls_no_price": " No price yet.",
        "ls_more": "{n} more:",
        "ls_alpaca_unknown": "unknown (no keys)",
        "ls_alpaca_yes": "lists it",
        "ls_alpaca_no": "does not list it",
        "ls_news": "Binance announcement",
        # trending
        "tr_change24": "24h change",
        "tr_volume": "Volume",
        "tr_vs_median": "{r} its 28d median",
        "tr_trades": "Trades",
        "tr_meme_lead": "Memecoin:",
        "tr_meme": "moves like this often reverse within days.",
        "tr_alert_title": "{coin} on Alpaca {pct} in 24h",
        "tr_alert_summary": "Volume surge on the paper account's list. Watch only: no order is placed.",
        "tr_hdr_coin": "Coin",
        "tr_hdr_volx": "Vol x",
        "tr_hdr_24h": "24h",
        "tr_table_title": "Alpaca coins, volume vs 28d median",
        "tr_gainers": "Binance gainers 24h",
        "tr_surges": "Binance volume surges",
        "tr_onchain": "⚠️ On-chain hype:",
        "tr_caveat": ("HIGH RISK, watch only. On-chain tokens are not on Alpaca; pumps, rug pulls and wash trading "
                      "dominate. Nothing here trades on a DEX or touches a wallet."),
        "tr_dex_line": "{pct} 24h, liq {liq}, vol {vol} [{flags}]",
        "tr_no_flags": "no flags",
        "tr_summary": ("{n} Alpaca coin with volume data, {d} on-chain tokens watched.",
                       "{n} Alpaca coins with volume data, {d} on-chain tokens watched."),
        "tr_no_data": "No source answered with data.",
        "tr_digest_title": "Trending · {day}",
        "tr_w7": ("W7 backtest: buying volume surges on the Alpaca memecoins made Sharpe {sharpe} out of sample at "
                  "35 bps (drawdown {dd} %), positive in {years} of 3 years. Not a paper book."),
        "tr_w7_line": ("W7 backtest: buying volume surges on the Alpaca memecoins paid in 2024 and lost in 2025 and "
                       "2026; not a paper book (results/memecoins.md)."),
        # the pump.fun paper books (lab.paper.pumpfun)
        "pf_caveat": ("Paper only: no wallet, no key, no transaction. Most pump.fun tokens go to zero; these books "
                      "measure how fast and how often, they are not a strategy."),
        "pf_footer": "Paper only",
        "pf_winner_title": "pump.fun paper winner {name} {ret}",
        "pf_winner_summary": "Rule {rule}: {stake} became {usd} in {hours} h ({why}).",
        "pf_losers_title": ("pump.fun paper loser: {n}", "pump.fun paper losers: {n}"),
        "pf_losers_summary": "Positions closed at -80 % or worse this run; a rug is a total loss.",
        "pf_col_token": "Token",
        "pf_col_rule": "Rule",
        "pf_col_return": "Return",
        "pf_col_why": "Why",
        "pf_col_book": "Book",
        "pf_report_title": "pump.fun paper books",
        "pf_report_summary": "Yesterday {launches} new tokens and {grads} graduations. {rules}",
        "pf_rule_line": "{rule}: {closed} closed, {rugs} rugs, book {ret}",
        "pf_rule_none": "{rule}: nothing closed yet",
        "pf_take": "take profit {pct}",
        "pf_trail": "trailing stop {pct}",
        "pf_time": "time {h} h",
        "pf_rug_liq": "rug: liquidity {usd}",
        "pf_rug_gone": "rug: no pool left",
        # the real-time pump.fun lab (lab.pumpfun_rt)
        "prt_caveat": ("Paper only: no wallet, no key, no transaction. Fills are modelled with 0.4 to 3 s of "
                       "latency after the signal; the fastest snipers land before that."),
        "prt_footer": "Paper only · real-time lab",
        "prt_win_title": "pump.fun live paper winner {name} {ret}",
        "prt_win_summary": "Shadow book {rule}: {stake} became {got} in {secs} s ({why}).",
        "prt_why_take": "take profit",
        "prt_why_stop": "stop loss",
        "prt_why_time": "time stop",
        "prt_why_stuck": "curve done, no pool seen",
        "prt_daily_title": "pump.fun real-time lab, {day}",
        "prt_daily_record": "Recorded: {tokens} new tokens, {trades} curve trades, {done} completed curves.",
        "prt_daily_book": "{book}: {n} closed, {hit} winners, {mean} mean per trade, {pnl} in all.",
        "prt_daily_book_none": "{book}: nothing closed.",
        "prt_daily_early": ("Too early to judge: {days} days of record; the bar needs 14 days and 300 trades out of "
                            "sample."),
        "prt_daily_study": "Study: {passed} of {rules} rules pass the out-of-sample bar; pick {pick}.",
        "prt_daily_model": "Model: {useful} of {labels} labels beat their baselines.",
        "prt_col_book": "Book",
        "prt_col_closed": "Closed",
        "prt_col_mean": "Mean",
        "prt_col_pnl": "P&L SOL",
        "prt_why_trail": "trailing stop",
        "prt_why_dev": "the dev sold",
        "prt_why_pull": "liquidity pulled",
        "prt_why_risk": "risk model",
        "prt_why_hazard": "hazard model",
        "prt_why_kill": "kill switch",
        "prt_all_books": "Every paper book",
        "prt_daily_books": "Paper books yesterday: {n} with closed trades, {pnl} in all.",
        "prt_daily_small": "Small-wallet paper books (from 0.55 SOL each): {books}.",
        "prt_daily_factory": "Factory paper books (F3, from 0.55 SOL each): {books}.",
        "prt_daily_alloc": ("Allocator (A1, paper): would pick {pick} (P(best) {p}, {days} days of realistic paper); "
                            "the live bot keeps {live}."),
        "prt_alloc_out": "none (every strategy under its drawdown guard)",
        "prt_daily_models": ("Models: {useful} of {labels} labels beat their baselines; wallet features adopted for "
                             "{wallet}, name categories for {cat}."),
        "prt_daily_ready": ("Closest to live: {rule}, {days} of 14 days, {trades} of 300 trades out of sample, "
                            "{shadow} of 30 shadow days, {gates}."),
        "prt_daily_ready_n": "{n} of {total} strategies are ready for live.",
        "prt_daily_latency": ("Our feed saw new tokens {med} s after their block (median; 90th percentile {p90} s), "
                              "{fast} within a second, {slot2} within two slots."),
        "prt_daily_x14": ("Exits out of sample: {pick} keeps {cap} of the best possible gain (best simple rule "
                          "{base}: {cap_base}). Early detection: the top 5 % by P(3x) reached it {prec} of the "
                          "time against {rate} for all ({lift}x)."),
        "prt_gates_pass": "the gates pass",
        "prt_gates_fail": "the gates do not pass yet",
        "prt_live_locked": "Live: locked, nothing trades real money.",
        "prt_live_on": "Live: ON for {rule}, {n} trades today, {pnl}.",
        "prt_live_refused": "Live: asked for but refused ({why}).",
        # a live pump.fun trade (lab.pumpfun_rt.live_exec, locked unless the owner unlocks it)
        "prl_buy_title": "Bought · {name}",
        "prl_head": "pump.fun · Alpha phase · {rule}",
        "prl_head_full": "pump.fun · real money · {rule}",
        "prl_sell_title": "Partial sale · {name}",
        "prl_close_title": "{ret} · {name}",
        "prl_fail_title": "Order failed · {name}",
        "prl_fail_summary": "{rule}: {why}.",
        "prl_row_stake": "Stake",
        "prl_row_tokens": "Tokens",
        "prl_row_proceeds": "Proceeds",
        "prl_row_pnl": "P&L",
        "prl_row_hold": "Held",
        "prl_row_exit": "Exit",
        "prl_row_today": "Today",
        "prl_row_day": "Day",
        "prl_row_total": "In all",
        "prl_row_wallet": "Wallet",
        "prl_row_trades": "Trades",
        "prl_row_latency": "Latency",
        "prl_trades_won": "{n} · {wins} won",
        "prl_caveat": "Real money · kill switch in the app.",
        "prl_footer": "pump.fun · real money",
        "prl_test_tag": "Alpha phase",
        "prl_test_caveat": "Alpha phase: small real-money stakes, kill switch in the app.",
        "prl_measured": "⏱ landed {lat} after the signal (model {assumed}) · slippage {slip}",
        "prl_measured_noslip": "⏱ landed {lat} after the signal (model {assumed})",
        "prl_stop_daily_title": "pump.fun daily loss stop",
        "prl_stop_daily_summary": "{lost} lost today, the limit is {limit}. No more buys until tomorrow (UTC).",
        "prl_stop_total_title": "pump.fun total budget stop",
        "prl_stop_total_summary": ("{lost} lost since the first live trade, the budget is {limit}. No more buys. "
                                   "Only a new confirmation file with a larger budget (at most 2 SOL) changes that."),
        "prl_left_sold_title": "Leftover sold · {name}",
        "prl_left_sold_summary": "A position from before the restart was sold for {sol}.",
        "prl_left_stuck_title": "Leftover NOT sold · {name}",
        "prl_left_stuck_summary": ("A position from before the restart could not be sold ({why}). Sell it in your "
                                   "own wallet (the backup imported into Phantom)."),
        "prl_stuck_title": "Sale given up · {name}",
        "prl_stuck_summary": ("The sale failed {n} times in a row ({why}). The bot stops trying and keeps the "
                              "position marked stuck. Sell it in your own wallet, or restart the service."),
        "prl_daily_title": "pump.fun {day}",
        "prl_daily_summary": "{rule}: {n} trades closed, {wins} won.",
        "prl_daily_balance_unknown": "not known",
        "prl_daily_latency": "{lat} median over {n} buys (model {assumed})",
        "prl_daily_latency_none": "no live fill yet",
        "prl_daily_failed": ("{n} order failed.", "{n} orders failed."),
        "prt_live_on_test": "Alpha phase: ON for {rule}, {n} trades today, {pnl}.",
        "prl_gate_shut_title": "pump.fun paused: no more buys",
        "prl_gate_shut_summary": ("Why: {why}. Open positions are still managed. Buying resumes within a minute "
                                  "once this is fixed."),
        "prl_gate_open_title": "pump.fun buying again",
        "prl_gate_open_summary": "Every condition holds again.",
        "prl_chart_title": "{name} · {ret}",
        "prl_chart_sub": "5 s candles · entry and exit marked · take profit and stop dashed",
        "prl_chart_entry": "entry",
        "prl_chart_exit": "exit",
        "prl_chart_tp": "take profit",
        "prl_chart_sl": "stop",
        "prl_chart_day_title": "pump.fun · P&L {day}",
        "prl_chart_day_sub": "cumulative P&L of the day's closed trades, in SOL",
        "prt_why_press": "sell pressure",
        "prt_why_leftover": "leftover after a restart",
        # the morning briefing (lab.ops.briefing)
        "bf_title": "Good morning · {day}",
        "bf_summary": "Where things stand this morning.",
        "bf_nothing": "No report is fresh enough for a briefing (all older than two days).",
        "bf_footer": "from the lab's and the engines' files, no model asked",
        "bf_pumpfun": "pump.fun · real money",
        "bf_yesterday": "Yesterday",
        "bf_best_worst": "Best / worst",
        "bf_paused": "Paused:",
        "bf_not_running": "The pump.fun bot is not running.",
        "bf_sum_pumpfun": "pump.fun {pnl}",
        "bf_real": "Real-money accounts",
        "bf_paper": "Paper and autopilots",
        "bf_paper_lead": ("{n} autopilot running", "{n} autopilots running"),
        "bf_sum_paper": "autopilots {money} today",
        "bf_books": ("{n} paper book: {counts}", "{n} paper books: {counts}"),
        "bf_small": "Small wallets (paper, EUR)",
        "bf_onchain_lt": "On-chain long-term book (paper, 0.5 SOL)",
        "bf_lab": "Lab",
        "bf_zoo_lead": "Model zoo",
        "bf_zoo": "in use {use}; shadow {shadow}; {failed} failed their gate, {retired} retired",
        "bf_zoo_news": "Decided lately",
        "bf_studies": "New results",
        "bf_pokemon": "🃏 Pokémon",
        "bf_collection": "Play collection",
        "bf_cheap": "Look cheap",
        "bf_top": "Top",
        "bf_cs2": "🎮 CS2",
        "bf_portfolio": "Play portfolio",
        "bf_hints_24h": "Hints 24 h",
        "bf_liquid": "{n} liquid items",
        "bf_coins": "🪙 Coins",
        "bf_gainer": "Top gainer",
        "bf_listings": "New listings",
        "bf_stocks": "🏛️ Stocks",
        "bf_held": "{sym} held",
        "bf_news": "News",
        "bf_markets": "Markets",
        "bf_research": "Research",
        "bf_sum_wallet": "wallet {eur}",
        "bf_autopilots": "Autopilots",
        "bf_paper_ends": "best {best}, weakest {worst}",
        "bf_paper_today": "today {money}",
        "bf_cheap_n": ("{n} looks cheap, first {top}", "{n} look cheap, first {top}"),
        "bf_hints_n": ("{n} hint, first {top}", "{n} hints, first {top}"),
        "bf_res_no_words": "finished, no report",
        "bf_res_more": "and {n} more in the app",
        "bf_res_running": "Running",
        "bf_res_queue_lead": "Queue",
        "bf_res_queue": "{n} waiting, {held} held back",
        "bf_res_budget_lead": "API credit",
        "bf_res_budget": "{left} left, reserve {reserve}",
        "bf_res_paused": "research paused",
        "bf_sum_research": ("{n} task done", "{n} tasks done"),
        # the research factories (F3 pump.fun, F2 small wallets) and A1's allocator, in the briefing and the 20:00 lab card
        "bf_factory": "Research factory",
        "bf_fac_F3": "F3 pump.fun",
        "bf_fac_F2": "F2 small wallets",
        "bf_fac_trials": ("{n} trial last night, {ever} in all", "{n} trials last night, {ever} in all"),
        "bf_fac_bar": "bar Sharpe {sharpe} against {n} trials",
        "bf_fac_best": "best new {id}: median {median} after 30 days",
        "bf_fac_hold": "held back {median}, {pnl} at 0.1 SOL",
        "bf_fac_nohold": "not held back",
        "bf_fac_none": "no new candidate",
        "bf_fac_books": "books {started} started, {retired} retired, {active} running",
        "bf_fac_winners": "winners {ids}",
        "bf_fac_models": "model settings adopted for {labels}",
        "bf_fac_models_none": "no model setting adopted",
        "bf_alloc_lead": "Allocator (A1, paper)",
        "bf_alloc": "would pick {pick}: P(best) {p}, weight {w}, daily growth {g} over {days} days{guard}; the live bot keeps {live}",
        "bf_alloc_guard": "; under the drawdown guard {arms}",
        "lb_title": "Lab · {day}",
        "lb_summary": "What the factories and the zoo did today, from their reports",
        "lb_books": "Factory books",
        "lb_proposals": "Proposals for you",
        "lb_zoo": "Model zoo (A1)",
        "lb_zoo_picks": "picks {picks}",
        "lb_zoo_changes": "changed {changes}",
        "lb_missing": "no fresh report",
        "lb_footer": "from the reports, no model asked",
        "bf_chart_title": "Morning briefing",
        "bf_chart_equity": "Autopilots since their start, against BTC",
        "bf_chart_pumpfun": "pump.fun Alpha phase, last 14 days, SOL",
        "bf_chart_none": "No autopilot running",
        # a real-money fill of an autopilot, for Discord (lab.ops.notify --live-fills)
        "lf_buy_title": "Bought · {sym}",
        "lf_sell_title": "Sold · {sym}",
        "lf_sell_title_ret": "{ret} · {sym} sold",
        "lf_summary": "{name} · {venue} · real money",
        "lf_row_qty": "Quantity",
        "lf_row_price": "Price",
        "lf_row_value": "Value",
        "lf_row_slip": "Slippage",
        "lf_footer": "real money · kill switch in the app",
        "lf_chart_sub": "P&L since the start, in $",
        # the strategy factory
        "fa_head": ("Factory {run}: {n} new strategies tried, pool now {trials} trials (noise bar Sharpe {sr0})."),
        "fa_best": "Best in sample: {name}, Sharpe {sharpe} at 35 bps.",
        "fa_held": "Held back:",
        "fa_holdout_line": "- {name}: OOS {oos}, defl p {p}, {decision}",
        "fa_shadows": "Shadow books: {n} running{list}.",
        "fa_shadow_item": "{id} {days}d {ret}",
        "fa_decision": "{status}: {name} ({reason})",
        "fa_review": "Factory shadow review:",
        "fa_promoted_reason": "passes the bar and its forward month",
        "fa_fails": "fails {gates}",
        "fa_verdict_promoted": "{n} genome(s) promoted to paper books after their forward month.",
        "fa_verdict_shadow": ("{n} genome(s) pass the held-back gates and start a 30-day forward shadow; none is near "
                              "promotion until then, and deflation over {trials} trials must also pass."),
        "fa_verdict_none": ("Nothing survives the held-back gates this run. {n} genomes were checked; "
                            "the pool grew to {trials} trials."),
        # models
        "md_head": "{prefix} models",
        "md_drift": ("{code} {title}: inputs outside the trained range ({worst}). {why}. "
                     "Forecasts may be off until the next retrain ({next})."),
        "md_drift_why": "{n} of {total} inputs spent more than 5 % of the last {days} days outside the trained range",
        "md_promoted": "{code} {title}: challenger promoted as {published}. {why}",
        # the learning loop's headline (in the daily digest)
        "ln_sweep_new": "published the refreshed family sweep",
        "ln_sweep_kept": "kept the published family sweep",
        "ln_promoted": "promoted {models}",
        "ln_kept": "kept the champion for {models}",
        "ln_costs": ("{n} cost update", "{n} cost updates"),
        "ln_evidence": ("{n} evidence change", "{n} evidence changes"),
        "ln_gates": ("{n} gate change", "{n} gate changes"),
        "ln_failed": "failed: {steps}",
        "ln_running_best": ("{n} autopilot running, best {pts} points against BTC since start",
                            "{n} autopilots running, best {pts} points against BTC since start"),
        "ln_running": ("{n} autopilot running", "{n} autopilots running"),
        "ln_nothing": "nothing changed",
        # the Polymarket paper books (lab.polymarket.card), paper only
        "pm_title": "Polymarket paper books",
        "pm_summary": "{day}: {open} open positions, {opened} opened, {settled} resolved today.",
        "pm_book_pm_model": "Model book",
        "pm_book_pm_claude": "Claude book",
        "pm_equity": "Equity",
        "pm_since_start": "Since start",
        "pm_open": "Open",
        "pm_resolved": "Resolved",
        "pm_hit": "Hit rate",
        "pm_hit_value": "{won} of {n}",
        "pm_col_book": "Book",
        "pm_col_start": "Start",
        "pm_col_hit": "Won",
        "pm_claude_line": "Claude: {n} forecasts, {r} resolved; ",
        "pm_model_line": "Model on open markets: {n} forecasts, {r} resolved; ",
        "pm_score": "Brier {model} against the market's {market}",
        "pm_score_wait": "too early to score",
        "pm_no_model": "the model is not fitted yet",
        "pm_ensemble_wait": "Ensemble: waits for {need} resolved Claude forecasts",
        "pm_ensemble_pass": "Ensemble passed its test (weight on Claude {w})",
        "pm_ensemble_fail": "Ensemble failed its test (weight on Claude {w})",
        "pm_ai_cost": "Claude cost so far {usd}",
        "pm_foot": "Paper only: no wallet, no orders. Polymarket is restricted in several countries.",
        "pm_alert_title": "Polymarket: big edge (paper)",
        "pm_alert_line": "{book} bought {side} at {ask}, forecast {q}, edge {edge} points, stake {usd}",
        "pm_alert_ends": "Ends {day}",
        "pm_side_yes": "YES",
        "pm_side_no": "NO",
    },
    "de": {
        "more_rows": "+{n} weitere",
        "more_in_app": "+{n} weitere in der App",
        "more_in_reports": "(mehr in den Berichten)",
        "today": "Heute",
        "since_start": "Seit Start",
        "tbl_autopilot": "Autopilot",
        "tbl_value": "Wert",
        "tbl_today": "Heute",
        "tbl_week": "Woche",
        "tbl_start": "Start",
        "tbl_vs_btc": "±BTC",
        "tbl_vs_gated": "±G",
        "tbl_legend": "Wert in $, Heute und Start in %, ±BTC in Punkten gegenüber BTC seit Start",
        "tbl_legend_gated": ("Wert in $, Heute und Start in %, ±BTC in Punkten gegenüber BTC seit Start, "
                             "±G gegenüber BTC nur über seinem 200-Tage-Schnitt"),
        "tbl_legend_week": "Wert in $, Woche und Start in %, ±BTC in Punkten gegenüber BTC in dieser Woche",
        "tbl_all_mode": "; alle {mode}",
        "tbl_account": "; Konto {account}: {names}",
        "act_orders": ("{n} Order ausgeführt", "{n} Orders ausgeführt"),
        "act_closed": ("{n} Position geschlossen", "{n} Positionen geschlossen"),
        "act_fees": "Gebühren {fees}",
        "deepest": "am tiefsten {name} {pct}",
        "forward_test": "Vorwärtstest",
        "no_report": "kein Bericht",
        "no_paper_books": "keine Paper-Bücher",
        "fw_on_track": "✅ im Plan",
        "fw_ok": "✅ in Ordnung",
        "fw_watch": "👀 beobachten",
        "fw_early": "🌱 noch früh",
        "fw_below": "🔻 darunter",
        "fw_behind": "🔻 im Rückstand",
        "fw_unknown": "unbekannt",
        "xs_lead": "Ausstiegsregeln (Schatten)",
        "xs_m14": "M14-Ausstieg bei tsmom_tranches",
        "xs_time40": "Zeitstopp nach 40 Tagen bei den drei Krypto-Büchern",
        "xs_collecting": "{test} zeichnet jetzt auf",
        "xs_passed": "{test} hat den Vorwärtstest bestanden; gehandelt wird damit erst, wenn du entscheidest",
        "xs_failed": "{test} ist am Vorwärtstest gescheitert und bleibt eine Akte",
        "health": "Systemzustand",
        "no_health": "keine Systemprüfung gefunden",
        "last_check": " (letzte Prüfung vor {h} h)",
        "all_green": "✅ alles grün{late}",
        "n_red": "🔴 {n} rot: {names}{late}",
        "no_learning": "Kein Lernbericht gefunden.",
        "running_today": ("{n} Autopilot läuft, heute {money} {dot}", "{n} Autopiloten laufen, heute {money} {dot}"),
        "running": ("{n} Autopilot läuft.", "{n} Autopiloten laufen."),
        "btc_24h_suffix": " · BTC 24 h {pct}",
        "btc_week_suffix": " · BTC diese Woche {pct}",
        "none_running": "Kein Autopilot läuft{err}.",
        "learning": "Lernen",
        "stale_learning": "der letzte Bericht ist vom {gen}, nicht von heute",
        "daily_title": "Tagesbericht · {day}",
        "chart_since_start": "Wert seit Start",
        "weekly_title": "Wochenbericht · {span}",
        "no_engine": "Pythia hat nicht geantwortet: diese Woche keine Zahlen.",
        "no_autopilot": "Kein Autopilot läuft.",
        "this_week": "Diese Woche",
        "below_peak": "Unter Höchststand",
        "best_sleeve": "Bestes Teilportfolio",
        "best_worst": "{best} {best_money} · schwächstes {worst} {worst_money}",
        "weekly_summary": ("{n} Autopilot: diese Woche {money} {dot}", "{n} Autopiloten: diese Woche {money} {dot}"),
        "chart_this_week": "Wert diese Woche",
        "ai_week_lead": "Claude-API",
        "ai_week": "diese Woche {money}, {avg} am Tag: {jobs}",
        "dir_title": ("Forschungsleitung: {n} Studienentwurf", "Forschungsleitung: {n} Studienentwürfe"),
        "dir_summary": ("Entwürfe für Vorab-Registrierungen, über die du entscheidest; nichts startet sie. "
                        "Dateien in {where}. Kosten {cost}."),
        "dir_stop": "Nicht weiter verfolgen",
        "critic_title": ("Strategie-Prüfung: {n} Befund", "Strategie-Prüfung: {n} Befunde"),
        "critic_summary": ("Die Orders von gestern je Autopilot gegen seine Regeln. Antworte /real ID oder "
                           "/notreal ID, um einen Befund zu bewerten."),
        "critic_confirmed": "die Zahlen bestätigen es",
        "critic_unconfirmed": "die Zahlen bestätigen es nicht",
        "critic_unchecked": "aus den Zahlen nicht prüfbar",
        "critic_marked": "Befund {id} als {verdict} markiert. Er zählt für die Trefferquote der Prüfung.",
        "critic_unknown": "Es gibt keinen Befund {id}.",
        "critic_real": "zutreffend",
        "critic_notreal": "nicht zutreffend",
        "ask_help": ("Frag mich alles zu Pythia: die Autopiloten, die Berichte des Labors, den Markt. Ich lese "
                     "dieselben Fakten wie der tägliche Kurzbericht und antworte in deiner Sprache. Ich handle "
                     "nie, ändere keine Einstellungen und zeige keine Geheimnisse. /real ID oder /notreal ID "
                     "bewertet einen Befund der Strategie-Prüfung."),
        "ask_refuse_trade": ("Ich beantworte nur Fragen. Ich kann keine Orders platzieren, ändern oder stornieren, "
                             "keinen Autopiloten starten oder stoppen und keine Einstellung ändern: das bleibt in "
                             "der App, bei dir."),
        "ask_refuse_secret": "Schlüssel, Zugangsdaten, Passwörter, Chat-IDs und Serverdetails zeige ich nie.",
        "ask_limit": "Das war die letzte der {n} Fragen für heute. Frag morgen wieder (UTC).",
        "ask_failed": "Diesmal keine Antwort ({why}). Es wurde nichts geändert.",
        "ask_footer": "{model} · {cost} · {n} von {limit} heute",
        "quiet_over": "Ruhezeit vorbei",
        "held_summary": ("{n} Labor-Meldung wurde von {start} bis {end} zurückgehalten.",
                         "{n} Labor-Meldungen wurden von {start} bis {end} zurückgehalten."),
        "held_group": ("{title}", "{n}, zuletzt {title}"),
        "other_posts": "Sonstiges",
        "health_green": "Systemprüfung wieder grün",
        "since_check": "Seit der Prüfung am {at}.",
        "health_red": "Systemprüfung seit {n} Läufen rot",
        "checks_not_ok": ("{n} Prüfung nicht in Ordnung, Stand {at}.", "{n} Prüfungen nicht in Ordnung, Stand {at}."),
        "no_check_named": "keine Prüfung genannt",
        "job_failed": "Job {name} {status} (Exit-Code {code}) nach {s} s; Protokoll {log}",
        "job_ok_again": "Job {name} läuft wieder",
        "job_status_failed": "fehlgeschlagen",
        "job_status_timeout": "abgebrochen (Zeitlimit)",
        "btc_hold": "BTC kaufen und halten",
        "pnl_per_sleeve": "GuV je Teilportfolio",
        "no_sleeves": "Keine Teilportfolios",
        "positions": "Positionen",
        "in_cash": "Nur Bargeld",
        "cs2_head": "{prefix} CS2: {n} zum Ansehen (nur Paper, wenn überhaupt von Hand handeln)",
        "cs2_gap": "Preislücke",
        "cs2_drop": "Kurssturz",
        "cs2_more": "... und {n} weitere auf der CS2-Seite",
        "cs2_to_steam": ("auf Skinport für {ask} kaufen, auf Steam für {list} einstellen: {v} nach Gebühren, "
                         "bezahlt in Steam-Guthaben"),
        "cs2_to_skinport": ("auf Steam für {ask} kaufen, auf Skinport für {list} einstellen: {v} nach Gebühren, "
                            "Bargeld nach der 7-tägigen Handelssperre"),
        "cs2_drop_text": "jetzt {ref}, {why}, {vs30} gegenüber dem 30-Tage-Median ({n} Verkäufe in 7 Tagen)",
        "cs2_why_24h": "{d} in 24 h",
        "cs2_why_7d": "{d} gegenüber dem 7-Tage-Median",
        "cs2_verdict": "Paper {ret} seit Start, {n} Positionen.",
        "cs2_weekly": "{prefix} CS2 Woche: {verdict} {n} Paper-Abschlüsse. Details auf der CS2-Seite.",
        "pk_head": "{prefix} Karten {today}",
        "pk_moves": "Starke Bewegungen:",
        "pk_move_line": "- {name} ({set}): {move} {basis}, jetzt {price}",
        "pk_basis_last": "seit dem letzten Stand",
        "pk_basis_7d": "in 7 Tagen",
        "pk_basis_cm": "Cardmarket 1-Tages- ggü. 7-Tage-Schnitt",
        "pk_cheap": "Günstig im Vergleich zu ähnlichen Karten{note}:",
        "pk_unvalidated": " (nur das Modell für den fairen Wert; die Renditeprognose ist noch nicht bestätigt)",
        "pk_uv_line": "- {name} ({set}): {price}, fairer Wert {fair} ({gap}), Prognose 90 T {pred}",
        "pk_foot": "Nur Daten und Paper; nichts wird gekauft oder verkauft.",
        "pk_na": "k. A.",
        "pk_date_na": "Datum k. A.",
        "pk_ungraded": "ungradiert",
        "pk_printing": ", Druck {v}",
        "pk_now": "Jetzt {price} ({src}, {date})",
        "pk_src_tcg": "TCGplayer-Marktpreis",
        "pk_src_cm_usd": "Cardmarket-Trend in USD",
        "pk_no_cm": " · kein Cardmarket-Preis",
        "pk_cm": " · Cardmarket {trend} Trend",
        "pk_cm_avg": ", {avg} Durchschnittsverkauf",
        "pk_stale": ", ⚠️ {n} Tage alt, veraltet",
        "pk_stale_undated": ", ⚠️ ohne Datum, veraltet",
        "pk_fair": "Fairer Wert {fair} ({gap} ggü. Preis)",
        "pk_forecast": "Prognose 30 T {p30}, 90 T {p90}",
        "pk_trust": "Vertrauen: {words}",
        "pk_trust_tested_h": "{h} T geprüft",
        "pk_trust_ic": ", Rang-IC {ic} über {m} Monate",
        "pk_trust_tested": "außerhalb der Stichprobe geprüft ({parts})",
        "pk_trust_mixed": "{parts}; der andere Horizont ist eine ungeprüfte Regel",
        "pk_trust_partly": "teilweise geprüft",
        "pk_trust_low": "niedrig, eine ungeprüfte Regel (Abstand zum fairen Wert)",
        "pk_trust_none": "kein fairer Wert und keine Prognose: die Karten-API bepreist dieses Set noch nicht",
        "pk_moved": "Bewegt {move} {basis}",
        "pk_change": "Änderung {bits}",
        "pk_d": "{h} T",
        "pk_no_change": "Noch keine Preisänderung: unser Verlauf beginnt mit dem ersten Stand",
        "pk_link_cm": "Cardmarket",
        "pk_link_cm_search": "Cardmarket-Suche",
        "pk_link_tp": "TCGplayer",
        "pk_link_tp_search": "TCGplayer-Suche",
        "pk_moves_title": ("{n} Karte hat sich stark bewegt", "{n} Karten haben sich stark bewegt"),
        "pk_moves_why": "Ab 20 $ wert und seit dem letzten Stand um 20 % oder in 7 Tagen um 35 % bewegt.",
        "pk_uv_title": ("{n} Karte günstig im Vergleich zu ähnlichen", "{n} Karten günstig im Vergleich zu ähnlichen"),
        "pk_uv_why": "Kostet ein Drittel bis die Hälfte ähnlicher Karten, positive 90-Tage-Prognose. ",
        "pk_uv_validated": "Die Prognose ist bestätigt.",
        "pk_uv_unvalidated": "Nur das Modell für den fairen Wert; die Renditeprognose ist noch nicht bestätigt.",
        "pk_new_title": "Neues Set: {set}",
        "pk_new_why": ("Erschienen {released} ({when}), {n} Einzelkarten auf TCGplayer bepreist. Die fünf teuersten; "
                       "Preise so neuer Sets schwanken stark."),
        "pk_out_in": "erscheint in {n} Tagen",
        "pk_out_today": "heute erschienen",
        "pk_out_since": "seit {n} Tagen erhältlich",
        "pk_album_moves": "Starke Bewegungen",
        "pk_album_uv": "Günstig im Vergleich zu ähnlichen Karten",
        "pk_card_foot": "Nur zur Information; nichts wird gekauft oder verkauft. Du handelst von Hand.",
        "pk_new_set_line": "Neues Set {set}: am teuersten {name} {price}",
        "ct_basis_snap": "ggü. unserem Stand vom {day}",
        "ct_basis_w7": "24-Stunden-Schnitt ggü. dem 7-Tage-Schnitt",
        "ct_basis_w30": "24-Stunden-Schnitt ggü. dem 30-Tage-Schnitt",
        "ct_basis_none": "kein früherer Stand",
        "ct_group_case": "Kiste",
        "ct_group_capsule": "Kapsel",
        "ct_group_sticker": "Sticker",
        "ct_group_sticker_slab": "Sticker-Slab",
        "ct_group_knife_or_glove": "Messer oder Handschuhe",
        "ct_group_skin": "Skin",
        "ct_group_other": "Sonstiges",
        "ct_lean_momentum": "Momentum",
        "ct_lean_reversion": "Rückkehr zum Mittel",
        "ct_lean_neither": "weder noch",
        "ct_lean_n/a": "k. A.",
        "ct_event_release": "Erscheinen",
        "ct_event_first_seen": "zuerst gesehen",
        "ct_event_operation_start": "Operationsstart",
        "ct_event_operation_end": "Operationsende",
        "ct_event_left_drop_pool": "aus dem Drop-Pool genommen",
        "ct_event_entered_drop_pool": "in den Drop-Pool aufgenommen",
        "ct_head_mover": "{v} {basis}",
        "ct_since_yesterday": "seit dem Stand von gestern",
        "ct_head_case": "{v} in 7 Tagen",
        "ct_head_new": "heute zum ersten Mal auf dem Steam-Markt",
        "ct_head_cash": "auf Steam kaufen, auf Skinport verkaufen: {v} nach Gebühren, als Bargeld",
        "ct_head_premium": ("Steam {v} über Skinport, die Gruppe sonst {usual}; Skinport nach Steam {w} nach Gebühren, "
                            "als Steam-Guthaben"),
        "ct_sp_ask": "Skinport-Angebot {ask}",
        "ct_sp_sales": ", {n} Verkäufe in 7 T",
        "ct_item_prices": "Steam {steam} (24-Stunden-Schnitt) · {sp} · 7 T {c7} · 30 T {c30}",
        "ct_link_steam": "Steam-Markt",
        "ct_kind_mover": "Bewegt",
        "ct_kind_new_drop": "Neue Kiste oder Kapsel",
        "ct_kind_case_rise": "Kiste steigt",
        "ct_kind_spread": "Ungewöhnliche Preisspanne",
        "ct_more": "{n} weitere auf der CS2-Seite",
        "ct_alert_title": "CS2 Steam-Markt: {title}",
        "ct_alert_summary": ("{n} Sache zum Ansehen von Hand. Steam zahlt Verkäufern Guthaben aus, kein Bargeld.",
                             "{n} Sachen zum Ansehen von Hand. Steam zahlt Verkäufern Guthaben aus, kein Bargeld."),
        "ct_foot": "Nur zur Information; nichts wird gekauft oder verkauft.",
        "ct_sum_title": "CS2 Steam-Markt · {day}",
        "ct_sum_items": "{items} Gegenstände mit Steam-Preis, {liquid} liquide; ",
        "ct_sum_top": "stärkster Anstieg {name} {v}",
        "ct_sum_no_up": "kein liquider Gegenstand gestiegen",
        "ct_sum_drop": ", stärkster Rückgang {name} {v}",
        "ct_sum_days": (". {n} Tag Steam-Stände.", ". {n} Tage Steam-Stände."),
        "ct_col_group": "Gruppe",
        "ct_col_items": "Anzahl",
        "ct_col_premium": "Steam ggü. SP",
        "ct_table_groups": "Liquide Gegenstände, Mediane",
        "ct_col_mover": "Gegenstand",
        "ct_col_move": "Bewegung",
        "ct_table_movers": "Größte Bewegungen ({basis})",
        "ct_mom_snap_lead": "Momentum, unsere Stände:",
        "ct_mom_snap": "IC {ic} über {n} Tage, t {t}: neigt zu {lean}",
        "ct_mom_win_lead": "Momentum, aus den Schnitten:",
        "ct_mom_win": "IC {ic} über {n} Gegenstände: neigt zu {lean} (ein Stand, nur ein Hinweis)",
        "ct_drop_lead": "Letzte Neuerscheinung:",
        "ct_drop_line": "{items} ({kind}, {day}, vor {n} Tagen); andere Kisten {others}",
        "ct_drop_since": "{v} seitdem",
        "ct_drop_window": "7 T {c7}, 30 T {c30}",
        "ct_rising_lead": "Kisten in 7 T um 15 %+ gestiegen:",
        "ct_spread_lead": "Spanne nach Gebühren:",
        "ct_spread_line": ("Steam {p} über Skinport (Median); Skinport nach Steam bringt {w} als Steam-Guthaben, "
                           "Steam nach Skinport {c} als Bargeld"),
        "ct_sum_foot": "Steam-Preise aus der öffentlichen Datei von csgotrader.app. Nur zur Information.",
        "ct_chart_title": "CS2 Steam-Markt",
        "ct_chart_sub": "{day} · 7 Tage: {basis}",
        "ct_chart_sub_movers": " · Bewegungen: {basis}",
        "ct_chart_groups": "Median der 7-Tage-Änderung je Gruppe, liquide Gegenstände",
        "ct_chart_movers": "Größte Bewegungen des Tages",
        "ct_chart_no_groups": "Keine Gruppe mit genug Gegenständen",
        "ct_chart_no_movers": "Kein liquider Gegenstand hat sich bewegt",
        "ls_msg": "{prefix} neu gelistet: {line}\nNur zur Information: es wird nichts gekauft.",
        "ls_announced": "{venue}: {title}. Alpaca: {alpaca}.",
        "ls_line_coin": "{venue} listet den neuen Coin {base}: {syms}. Alpaca: {alpaca}.{price}",
        "ls_line_pair": "{venue} listet ein neues Paar für {base}: {syms}. Alpaca: {alpaca}.{price}",
        "ls_and_more": " und {n} weitere",
        "ls_first_price": " Erster Preis {price} {quote} ({symbol}).",
        "ls_no_price": " Noch kein Preis.",
        "ls_more": "{n} weitere:",
        "ls_alpaca_unknown": "unbekannt (keine Schlüssel)",
        "ls_alpaca_yes": "führt ihn",
        "ls_alpaca_no": "führt ihn nicht",
        "ls_news": "Binance-Ankündigung",
        "tr_change24": "Änderung 24 h",
        "tr_volume": "Volumen",
        "tr_vs_median": "{r} des 28-Tage-Medians",
        "tr_trades": "Abschlüsse",
        "tr_meme_lead": "Memecoin:",
        "tr_meme": "solche Bewegungen drehen oft binnen Tagen.",
        "tr_alert_title": "{coin} bei Alpaca {pct} in 24 h",
        "tr_alert_summary": "Volumensprung auf der Liste des Paper-Kontos. Nur beobachten: es wird keine Order platziert.",
        "tr_hdr_coin": "Coin",
        "tr_hdr_volx": "Vol. x",
        "tr_hdr_24h": "24 h",
        "tr_table_title": "Alpaca-Coins, Volumen ggü. 28-Tage-Median",
        "tr_gainers": "Binance-Gewinner 24 h",
        "tr_surges": "Binance-Volumensprünge",
        "tr_onchain": "⚠️ On-Chain-Hype:",
        "tr_caveat": ("HOHES RISIKO, nur beobachten. On-Chain-Token gibt es nicht bei Alpaca; Pumps, Rug Pulls und "
                      "Scheinhandel herrschen vor. Nichts hier handelt auf einer DEX oder berührt eine Wallet."),
        "tr_dex_line": "{pct} 24 h, Liq. {liq}, Vol. {vol} [{flags}]",
        "tr_no_flags": "keine Warnzeichen",
        "tr_summary": ("{n} Alpaca-Coin mit Volumendaten, {d} On-Chain-Token beobachtet.",
                       "{n} Alpaca-Coins mit Volumendaten, {d} On-Chain-Token beobachtet."),
        "tr_no_data": "Keine Quelle hat Daten geliefert.",
        "tr_digest_title": "Im Trend · {day}",
        "tr_w7": ("W7-Backtest: Käufe bei Volumensprüngen der Alpaca-Memecoins erreichten außerhalb der Stichprobe "
                  "Sharpe {sharpe} bei 35 Basispunkten (Drawdown {dd} %), positiv in {years} von 3 Jahren. "
                  "Kein Paper-Buch."),
        "tr_w7_line": ("W7-Backtest: Käufe bei Volumensprüngen der Alpaca-Memecoins lohnten sich 2024 und verloren "
                       "2025 und 2026; kein Paper-Buch (results/memecoins.md)."),
        "pf_caveat": ("Nur Paper: keine Wallet, kein Schlüssel, keine Transaktion. Die meisten pump.fun-Token fallen "
                      "auf null; diese Bücher messen, wie schnell und wie oft, sie sind keine Strategie."),
        "pf_footer": "Nur Paper",
        "pf_winner_title": "pump.fun Paper-Gewinner {name} {ret}",
        "pf_winner_summary": "Regel {rule}: aus {stake} wurden {usd} in {hours} h ({why}).",
        "pf_losers_title": ("pump.fun Paper-Verlierer: {n}", "pump.fun Paper-Verlierer: {n}"),
        "pf_losers_summary": ("Positionen, die in diesem Lauf mit -80 % oder schlechter geschlossen wurden; "
                              "ein Rug ist ein Totalverlust."),
        "pf_col_token": "Token",
        "pf_col_rule": "Regel",
        "pf_col_return": "Rendite",
        "pf_col_why": "Grund",
        "pf_col_book": "Buch",
        "pf_report_title": "pump.fun Paper-Bücher",
        "pf_report_summary": "Gestern {launches} neue Token und {grads} Abschlüsse der Bonding-Kurve. {rules}",
        "pf_rule_line": "{rule}: {closed} geschlossen, {rugs} Rugs, Buch {ret}",
        "pf_rule_none": "{rule}: noch nichts geschlossen",
        "pf_take": "Gewinnmitnahme {pct}",
        "pf_trail": "Nachlaufender Stopp {pct}",
        "pf_time": "Zeit {h} h",
        "pf_rug_liq": "Rug: Liquidität {usd}",
        "pf_rug_gone": "Rug: kein Pool mehr",
        "prt_caveat": ("Nur Paper: keine Wallet, kein Schlüssel, keine Transaktion. Ausführungen sind mit 0,4 bis "
                       "3 s Verzögerung nach dem Signal modelliert; die schnellsten Sniper sind vorher drin."),
        "prt_footer": "Nur Paper · Echtzeit-Labor",
        "prt_win_title": "pump.fun Live-Paper-Gewinner {name} {ret}",
        "prt_win_summary": "Schattenbuch {rule}: aus {stake} wurden {got} in {secs} s ({why}).",
        "prt_why_take": "Gewinnmitnahme",
        "prt_why_stop": "Stop-Loss",
        "prt_why_time": "Zeitstopp",
        "prt_why_stuck": "Kurve voll, kein Pool gesehen",
        "prt_daily_title": "pump.fun Echtzeit-Labor, {day}",
        "prt_daily_record": ("Aufgezeichnet: {tokens} neue Token, {trades} Käufe und Verkäufe auf der Kurve, "
                             "{done} volle Kurven."),
        "prt_daily_book": ("{book}: {n} geschlossen, {hit} Gewinner, {mean} im Mittel je Position, {pnl} "
                           "insgesamt."),
        "prt_daily_book_none": "{book}: nichts geschlossen.",
        "prt_daily_early": ("Zu früh für ein Urteil: {days} Tage aufgezeichnet; die Schwelle braucht 14 Tage und "
                            "300 Positionen außerhalb der Stichprobe."),
        "prt_daily_study": ("Studie: {passed} von {rules} Regeln bestehen die Schwelle außerhalb der Stichprobe; "
                            "Auswahl {pick}."),
        "prt_daily_model": "Modell: {useful} von {labels} Zielen schlagen ihre Vergleichsmodelle.",
        "prt_col_book": "Buch",
        "prt_col_closed": "Geschl.",
        "prt_col_mean": "Mittel",
        "prt_col_pnl": "G/V SOL",
        "prt_why_trail": "Nachlaufender Stopp",
        "prt_why_dev": "der Entwickler hat verkauft",
        "prt_why_pull": "Liquidität abgezogen",
        "prt_why_risk": "Risikomodell",
        "prt_why_hazard": "Gefahrenmodell",
        "prt_why_kill": "Notschalter",
        "prt_all_books": "Alle Paper-Bücher",
        "prt_daily_books": "Paper-Bücher gestern: {n} mit geschlossenen Positionen, {pnl} insgesamt.",
        "prt_daily_small": "Paper-Bücher für die kleine Wallet (je ab 0,55 SOL): {books}.",
        "prt_daily_factory": "Paper-Bücher aus der Strategiesuche (F3, je ab 0,55 SOL): {books}.",
        "prt_daily_alloc": ("Strategie-Auswahl (A1, Paper): würde {pick} nehmen (P(beste) {p}, {days} Tage realistisches "
                            "Paper); der Live-Bot behält {live}."),
        "prt_alloc_out": "keine (jede Strategie unter ihrer Verlustbremse)",
        "prt_daily_models": ("Modelle: {useful} von {labels} Zielen schlagen ihre Vergleichsmodelle; "
                             "Wallet-Merkmale bei {wallet} übernommen, Namenskategorien bei {cat}."),
        "prt_daily_ready": ("Am nächsten an echtem Geld: {rule}, {days} von 14 Tagen, {trades} von 300 Positionen "
                            "außerhalb der Stichprobe, {shadow} von 30 Tagen im Schattenbuch, {gates}."),
        "prt_daily_ready_n": "{n} von {total} Strategien sind bereit für echtes Geld.",
        "prt_daily_latency": ("Unser Datenstrom sah neue Token {med} s nach ihrem Block (Median; 90. Perzentil "
                              "{p90} s), {fast} innerhalb einer Sekunde, {slot2} innerhalb von zwei Slots."),
        "prt_daily_x14": ("Ausstiege außerhalb der Stichprobe: {pick} behält {cap} des bestmöglichen Gewinns "
                          "(beste einfache Regel {base}: {cap_base}). Früherkennung: die obersten 5 % nach "
                          "P(3x) erreichten das Dreifache in {prec} der Fälle, alle in {rate} ({lift}-fach)."),
        "prt_gates_pass": "die Schwellen sind bestanden",
        "prt_gates_fail": "die Schwellen sind noch nicht bestanden",
        "prt_live_locked": "Echtgeld: gesperrt, nichts handelt mit echtem Geld.",
        "prt_live_on": "Echtgeld: AN für {rule}, {n} Abschlüsse heute, {pnl}.",
        "prt_live_refused": "Echtgeld: angefordert, aber verweigert ({why}).",
        "prl_buy_title": "Kauf · {name}",
        "prl_head": "pump.fun · Alpha-Phase · {rule}",
        "prl_head_full": "pump.fun · Echtgeld · {rule}",
        "prl_sell_title": "Teilverkauf · {name}",
        "prl_close_title": "{ret} · {name}",
        "prl_fail_title": "Auftrag gescheitert · {name}",
        "prl_fail_summary": "{rule}: {why}.",
        "prl_row_stake": "Einsatz",
        "prl_row_tokens": "Token",
        "prl_row_proceeds": "Erlös",
        "prl_row_pnl": "Ergebnis",
        "prl_row_hold": "Haltedauer",
        "prl_row_exit": "Ausstieg",
        "prl_row_today": "Heute",
        "prl_row_day": "Tag",
        "prl_row_total": "Gesamt",
        "prl_row_wallet": "Wallet",
        "prl_row_trades": "Abschlüsse",
        "prl_row_latency": "Latenz",
        "prl_trades_won": "{n} · {wins} gewonnen",
        "prl_caveat": "Echtgeld · Notschalter in der App.",
        "prl_footer": "pump.fun · Echtgeld",
        "prl_test_tag": "Alpha-Phase",
        "prl_test_caveat": "Alpha-Phase: kleiner Echtgeld-Einsatz, Notschalter in der App.",
        "prl_measured": "⏱ {lat} nach dem Signal gelandet (Modell {assumed}) · Schlupf {slip}",
        "prl_measured_noslip": "⏱ {lat} nach dem Signal gelandet (Modell {assumed})",
        "prl_stop_daily_title": "pump.fun Tagesverluststopp",
        "prl_stop_daily_summary": "Heute {lost} verloren, die Grenze ist {limit}. Keine Käufe mehr bis morgen (UTC).",
        "prl_stop_total_title": "pump.fun Gesamtbudget-Stopp",
        "prl_stop_total_summary": ("{lost} verloren seit dem ersten Echtgeld-Abschluss, das Budget ist {limit}. "
                                   "Keine Käufe mehr. Nur eine neue Bestätigungsdatei mit größerem Budget "
                                   "(höchstens 2 SOL) ändert das."),
        "prl_left_sold_title": "Rest verkauft · {name}",
        "prl_left_sold_summary": "Eine Position von vor dem Neustart wurde für {sol} verkauft.",
        "prl_left_stuck_title": "Rest NICHT verkauft · {name}",
        "prl_left_stuck_summary": ("Eine Position von vor dem Neustart ließ sich nicht verkaufen ({why}). Verkaufe "
                                   "sie in deiner eigenen Wallet (die Sicherung in Phantom importiert)."),
        "prl_stuck_title": "Verkauf aufgegeben · {name}",
        "prl_stuck_summary": ("Der Verkauf schlug {n} Mal hintereinander fehl ({why}). Der Bot versucht es nicht "
                              "weiter und markiert die Position als festgefahren. Verkaufe sie in deiner eigenen "
                              "Wallet oder starte den Dienst neu."),
        "prl_daily_title": "pump.fun {day}",
        "prl_daily_summary": "{rule}: {n} Abschlüsse, {wins} gewonnen.",
        "prl_daily_balance_unknown": "nicht bekannt",
        "prl_daily_latency": "{lat} Median über {n} Käufe (Modell {assumed})",
        "prl_daily_latency_none": "noch keine Echtgeld-Ausführung",
        "prl_daily_failed": ("{n} Auftrag gescheitert.", "{n} Aufträge gescheitert."),
        "prt_live_on_test": "Alpha-Phase: AN für {rule}, {n} Abschlüsse heute, {pnl}.",
        "prl_gate_shut_title": "pump.fun pausiert: keine Käufe mehr",
        "prl_gate_shut_summary": ("Grund: {why}. Offene Positionen werden weiter verwaltet. Sobald das behoben "
                                  "ist, kauft der Bot innerhalb einer Minute wieder."),
        "prl_gate_open_title": "pump.fun kauft wieder",
        "prl_gate_open_summary": "Alle Bedingungen gelten wieder.",
        "prl_chart_title": "{name} · {ret}",
        "prl_chart_sub": "5-s-Kerzen · Ein- und Ausstieg markiert · Gewinnziel und Stopp gestrichelt",
        "prl_chart_entry": "Einstieg",
        "prl_chart_exit": "Ausstieg",
        "prl_chart_tp": "Gewinnziel",
        "prl_chart_sl": "Stopp",
        "prl_chart_day_title": "pump.fun · Ergebnis {day}",
        "prl_chart_day_sub": "kumuliertes Ergebnis der geschlossenen Abschlüsse des Tages, in SOL",
        "prt_why_press": "Verkaufsdruck",
        "prt_why_leftover": "Rest nach einem Neustart",
        "bf_title": "Guten Morgen · {day}",
        "bf_summary": "Der Stand von heute früh.",
        "bf_nothing": "Kein Bericht ist frisch genug für ein Briefing (alle älter als zwei Tage).",
        "bf_footer": "aus den Dateien von Labor und Servern, ohne KI",
        "bf_pumpfun": "pump.fun · Echtgeld",
        "bf_yesterday": "Gestern",
        "bf_best_worst": "Bester / Schlechtester",
        "bf_paused": "Pausiert:",
        "bf_not_running": "Der pump.fun-Bot läuft nicht.",
        "bf_sum_pumpfun": "pump.fun {pnl}",
        "bf_real": "Echtgeld-Konten",
        "bf_paper": "Papier und Autopiloten",
        "bf_paper_lead": ("{n} Autopilot läuft", "{n} Autopiloten laufen"),
        "bf_sum_paper": "Autopiloten heute {money}",
        "bf_books": ("{n} Papierbuch: {counts}", "{n} Papierbücher: {counts}"),
        "bf_small": "Kleinkonten (Papier, EUR)",
        "bf_onchain_lt": "On-Chain-Langfristbuch (Papier, 0,5 SOL)",
        "bf_lab": "Labor",
        "bf_zoo_lead": "Modell-Zoo",
        "bf_zoo": "im Einsatz {use}; Schattenlauf {shadow}; {failed} an der Schwelle gescheitert, {retired} ausgemustert",
        "bf_zoo_news": "Zuletzt entschieden",
        "bf_studies": "Neue Ergebnisse",
        "bf_pokemon": "🃏 Pokémon",
        "bf_collection": "Spielsammlung",
        "bf_cheap": "Wirken günstig",
        "bf_top": "Vorne",
        "bf_cs2": "🎮 CS2",
        "bf_portfolio": "Spielportfolio",
        "bf_hints_24h": "Hinweise 24 h",
        "bf_liquid": "{n} liquide Skins",
        "bf_coins": "🪙 Coins",
        "bf_gainer": "Stärkster Anstieg",
        "bf_listings": "Neue Listungen",
        "bf_stocks": "🏛️ Aktien",
        "bf_held": "{sym} im Bestand",
        "bf_news": "Nachrichten",
        "bf_markets": "Märkte",
        "bf_research": "Forschung",
        "bf_sum_wallet": "Wallet {eur}",
        "bf_autopilots": "Autopiloten",
        "bf_paper_ends": "vorne {best}, hinten {worst}",
        "bf_paper_today": "heute {money}",
        "bf_cheap_n": ("{n} wirkt günstig, vorne {top}", "{n} wirken günstig, vorne {top}"),
        "bf_hints_n": ("{n} Hinweis, vorne {top}", "{n} Hinweise, vorne {top}"),
        "bf_res_no_words": "fertig, ohne Bericht",
        "bf_res_more": "und {n} weitere in der App",
        "bf_res_running": "Läuft",
        "bf_res_queue_lead": "Warteschlange",
        "bf_res_queue": "{n} warten, {held} zurückgestellt",
        "bf_res_budget_lead": "API-Guthaben",
        "bf_res_budget": "noch {left}, Reserve {reserve}",
        "bf_res_paused": "Forschung pausiert",
        "bf_sum_research": ("{n} Aufgabe fertig", "{n} Aufgaben fertig"),
        "bf_factory": "Forschungs-Fabrik",
        "bf_fac_F3": "F3 pump.fun",
        "bf_fac_F2": "F2 Kleinkonten",
        "bf_fac_trials": ("{n} Versuch heute Nacht, {ever} insgesamt", "{n} Versuche heute Nacht, {ever} insgesamt"),
        "bf_fac_bar": "Schwelle Sharpe {sharpe} gegen {n} Versuche",
        "bf_fac_best": "bester neuer {id}: Median {median} nach 30 Tagen",
        "bf_fac_hold": "zurückgehalten {median}, {pnl} bei 0,1 SOL",
        "bf_fac_nohold": "nicht zurückgehalten geprüft",
        "bf_fac_none": "kein neuer Kandidat",
        "bf_fac_books": "Bücher {started} gestartet, {retired} ausgemustert, {active} laufen",
        "bf_fac_winners": "Gewinner {ids}",
        "bf_fac_models": "Modell-Einstellungen übernommen für {labels}",
        "bf_fac_models_none": "keine Modell-Einstellung übernommen",
        "bf_alloc_lead": "Strategie-Auswahl (A1, Paper)",
        "bf_alloc": "würde {pick} nehmen: P(beste) {p}, Gewicht {w}, Tageswachstum {g} über {days} Tage{guard}; der Live-Bot bleibt bei {live}",
        "bf_alloc_guard": "; unter der Verlustbremse {arms}",
        "lb_title": "Labor · {day}",
        "lb_summary": "Heute in den Fabriken und im Zoo, aus ihren Berichten",
        "lb_books": "Fabrik-Bücher",
        "lb_proposals": "Vorschläge für dich",
        "lb_zoo": "Modell-Zoo (A1)",
        "lb_zoo_picks": "gewählt {picks}",
        "lb_zoo_changes": "gewechselt {changes}",
        "lb_missing": "kein frischer Bericht",
        "lb_footer": "aus den Berichten, ohne KI",
        "bf_chart_title": "Morgen-Briefing",
        "bf_chart_equity": "Autopiloten seit ihrem Start, gegen BTC",
        "bf_chart_pumpfun": "pump.fun Alpha-Phase, letzte 14 Tage, SOL",
        "bf_chart_none": "Kein Autopilot läuft",
        "lf_buy_title": "Kauf · {sym}",
        "lf_sell_title": "Verkauf · {sym}",
        "lf_sell_title_ret": "{ret} · {sym} verkauft",
        "lf_summary": "{name} · {venue} · Echtgeld",
        "lf_row_qty": "Menge",
        "lf_row_price": "Kurs",
        "lf_row_value": "Wert",
        "lf_row_slip": "Schlupf",
        "lf_footer": "Echtgeld · Notschalter in der App",
        "lf_chart_sub": "Ergebnis seit dem Start, in $",
        "fa_head": ("Fabrik {run}: {n} neue Strategien getestet, jetzt {trials} Versuche im Pool "
                    "(Rauschschwelle Sharpe {sr0})."),
        "fa_best": "Beste in der Stichprobe: {name}, Sharpe {sharpe} bei 35 Basispunkten.",
        "fa_held": "Außerhalb der Stichprobe geprüft:",
        "fa_holdout_line": "- {name}: OOS {oos}, defl. p {p}, {decision}",
        "fa_shadows": "Schattenbücher in Betrieb: {n}{list}.",
        "fa_shadow_item": "{id} {days} T {ret}",
        "fa_decision": "{status}: {name} ({reason})",
        "fa_review": "Fabrik-Schattenprüfung:",
        "fa_promoted_reason": "besteht die Schwelle und den Vorwärtsmonat",
        "fa_fails": "scheitert an: {gates}",
        "fa_verdict_promoted": "{n} Genom(e) nach dem Vorwärtsmonat als Paper-Bücher übernommen.",
        "fa_verdict_shadow": ("{n} Genom(e) bestehen die Prüfungen außerhalb der Stichprobe und starten einen "
                              "30-tägigen Schattenlauf; bis dahin ist keines nah an einer Übernahme, und die "
                              "Deflation über {trials} Versuche muss ebenfalls bestehen."),
        "fa_verdict_none": ("Diesmal übersteht nichts die Prüfungen außerhalb der Stichprobe. {n} Genome wurden "
                            "geprüft; der Pool wuchs auf {trials} Versuche."),
        "md_head": "{prefix} Modelle",
        "md_drift": ("{code} {title}: Eingaben außerhalb des Trainingsbereichs ({worst}). {why}. "
                     "Prognosen können bis zum nächsten Training ({next}) danebenliegen."),
        "md_drift_why": ("{n} von {total} Eingaben lagen mehr als 5 % der letzten {days} Tage außerhalb des "
                         "Trainingsbereichs"),
        "md_promoted": "{code} {title}: Herausforderer als {published} übernommen. {why}",
        "ln_sweep_new": "die erneuerte Familienauswertung veröffentlicht",
        "ln_sweep_kept": "die veröffentlichte Familienauswertung behalten",
        "ln_promoted": "übernommen: {models}",
        "ln_kept": "bisheriges Modell behalten: {models}",
        "ln_costs": ("{n} Kostenänderung", "{n} Kostenänderungen"),
        "ln_evidence": ("{n} Änderung der Belege", "{n} Änderungen der Belege"),
        "ln_gates": ("{n} Prüfänderung", "{n} Prüfänderungen"),
        "ln_failed": "fehlgeschlagen: {steps}",
        "ln_running_best": ("{n} Autopilot läuft, {pts} Punkte ggü. BTC seit Start",
                            "{n} Autopiloten laufen, der beste mit {pts} Punkten ggü. BTC seit Start"),
        "ln_running": ("{n} Autopilot läuft", "{n} Autopiloten laufen"),
        "ln_nothing": "nichts geändert",
        "pm_title": "Polymarket-Paperbücher",
        "pm_summary": "{day}: {open} offene Positionen, {opened} eröffnet, {settled} heute aufgelöst.",
        "pm_book_pm_model": "Modellbuch",
        "pm_book_pm_claude": "Claude-Buch",
        "pm_equity": "Kapital",
        "pm_since_start": "Seit Start",
        "pm_open": "Offen",
        "pm_resolved": "Aufgelöst",
        "pm_hit": "Trefferquote",
        "pm_hit_value": "{won} von {n}",
        "pm_col_book": "Buch",
        "pm_col_start": "Start",
        "pm_col_hit": "Treffer",
        "pm_claude_line": "Claude: {n} Prognosen, {r} aufgelöst; ",
        "pm_model_line": "Modell auf offenen Märkten: {n} Prognosen, {r} aufgelöst; ",
        "pm_score": "Brier {model} gegenüber {market} des Markts",
        "pm_score_wait": "zu früh für eine Wertung",
        "pm_no_model": "das Modell ist noch nicht angepasst",
        "pm_ensemble_wait": "Kombination: wartet auf {need} aufgelöste Claude-Prognosen",
        "pm_ensemble_pass": "Kombination hat ihren Test bestanden (Gewicht auf Claude {w})",
        "pm_ensemble_fail": "Kombination ist durch ihren Test gefallen (Gewicht auf Claude {w})",
        "pm_ai_cost": "Claude-Kosten bisher {usd}",
        "pm_foot": "Nur Paper: keine Wallet, keine Orders. Polymarket ist in mehreren Ländern gesperrt.",
        "pm_alert_title": "Polymarket: großer Vorsprung (Paper)",
        "pm_alert_line": "{book} kaufte {side} zu {ask}, Prognose {q}, Vorsprung {edge} Punkte, Einsatz {usd}",
        "pm_alert_ends": "Endet {day}",
        "pm_side_yes": "JA",
        "pm_side_no": "NEIN",
    },
}

# Model titles (lab.models) in German, by code; another code keeps its title.
MODEL_TITLES_DE = {
    "M8": "Richtung am nächsten Tag",
    "M8q": "Renditespanne am nächsten Tag (Quantile 10/50/90 %)",
    "M8u": "Aufwärtsspielraum am nächsten Tag (90-%-Quantil)",
    "M10": "Tagesvolatilität mit Regime",
    "M11": "Slippage von Demo-Marktorders",
    "M12": "Korrelationsregime BTC ggü. US-Aktien",
    "M13": "Frühsignale bei US-Aktien (20 Tage ggü. SPY)",
    "M14": "Restrendite gehaltener Coins (Ausstiegsmodell, 10 Tage)",
    "M15": "Restrendite gehaltener US-Aktien (Ausstiegsmodell, 10 Tage)",
}

# The factory's gates (lab.factory.writeup.GATE_LABEL) in German.
GATES_DE = {"is_stable": "IS-Hälften", "oos_positive": "OOS > 0", "stress": "70 Basispunkte", "drawdown": "DD < BTC",
            "late_fill": "späte Ausführung", "twin": "Zwilling", "deflated": "Deflation", "forward": "Vorwärtsmonat"}

# Words the lab writes into its data, said in German.
WORDS_DE = {
    # factory statuses and holdout decisions
    "promoted": "übernommen", "retired": "ausgemustert", "active": "aktiv", "shadow": "Schattenlauf",
    "stopped": "gestoppt", "already shadowed": "schon im Schattenlauf", "duplicate": "Doppelgänger",
    "waiting": "wartet", "rejected": "abgelehnt", "kept": "behalten",
    # the Claude jobs in the weekly report's spend line
    "brief": "Kurzbericht", "ask": "Fragen", "director": "Forschungsleitung", "critic": "Strategie-Prüfung",
    "weekly": "Wochenrückblick", "other": "Sonstiges",
    # what the strategy critic finds
    "churn": "Hin und Her", "fees": "Gebühren", "sizing": "Positionsgröße", "drift": "Abweichung",
    "rules": "Regelbruch",
    # trading modes
    "paper": "Paper", "demo": "Demo", "live": "Live",
    # trending risk flags
    "thin liquidity": "dünne Liquidität", "pair under 3 days old": "Paar jünger als 3 Tage",
    "FDV over 50x liquidity": "FDV über 50x Liquidität",
    "volume over 20x liquidity (wash?)": "Volumen über 20x Liquidität (Scheinhandel?)",
    "few sells (honeypot?)": "wenige Verkäufe (Verkauf gesperrt?)", "no pair found": "kein Paar gefunden",
}

# Phrases of the lab's gate and drift reasons, in order (the longer first).
PHRASES_DE = [
    ("for the baseline", "für die Vergleichsbasis"),
    ("not lower", "nicht niedriger"),
    ("lower", "niedriger"),
    ("the gate needs", "die Prüfung verlangt"),
    ("and p <", "und p <"),
    ("against the same model without regime inputs", "gegenüber demselben Modell ohne Regime-Eingaben"),
    ("the regime inputs do not add enough", "die Regime-Eingaben bringen zu wenig"),
    ("no out-of-sample rows: too little history for one fold",
     "keine Zeilen außerhalb der Stichprobe: zu wenig Verlauf für eine Faltung"),
    (" vs ", " ggü. "),
]


def t(key: str, lang: str = "en", n: int | None = None, **kw) -> str:
    """The message `key` in `lang` (English when the key has no German),
    formatted with `n` and `kw`. A (one, many) text picks by `n`."""
    lang = _l(lang)
    v = CATALOG[lang].get(key, CATALOG["en"][key])
    if isinstance(v, tuple):
        v = v[0] if n == 1 else v[1]
    return v.format(n=n, **kw) if n is not None else v.format(**kw)


def word(w: str, lang: str = "en") -> str:
    """A word the lab writes into its data, in German when there is one."""
    return WORDS_DE.get(w, w) if lang == "de" else w


def model_title(code: str, title: str, lang: str = "en") -> str:
    return MODEL_TITLES_DE.get(code, title) if lang == "de" else title


def reason(text: str, lang: str = "en") -> str:
    """A gate reason of the lab (`sm vs sb for the baseline, lower, DM p`) in German:
    the known phrases translated and the decimal points made commas."""
    if lang != "de" or not text:
        return text
    out = str(text)
    for en, de in PHRASES_DE:
        out = out.replace(en, de)
    return re.sub(r"(?<=\d)\.(?=\d)", ",", out)
