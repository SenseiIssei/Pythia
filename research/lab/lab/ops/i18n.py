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
        "equity": "Equity",
        "today": "Today",
        "since_start": "Since start",
        "vs_btc": "vs BTC",
        "pts": "{v} pts",
        "trades_today": "Trades today",
        "trades_today_value": "{n} · fees {fees}",
        "trades": "Trades",
        "trades_total": "{n} total · fees {fees}",
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
        "health": "Health",
        "no_health": "no health check found",
        "last_check": " (last check {h} h ago)",
        "all_green": "✅ all green{late}",
        "n_red": "🔴 {n} red: {names}{late}",
        "no_learning": "No learning report found.",
        "running_today": ("{n} autopilot running, {money} today {dot}", "{n} autopilots running, {money} today {dot}"),
        "running": ("{n} autopilot running.", "{n} autopilots running."),
        "btc_suffix": " · BTC {pct}",
        "none_running": "No autopilot running{err}.",
        "more_autopilots": "{n} more autopilots in the app",
        "no_equity": "no equity reported",
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
        "trades_week": "{n} this week",
        "trades_since": "{n} since start",
        "best_sleeve": "Best sleeve",
        "best_worst": "{best} {best_money} · worst {worst} {worst_money}",
        "weekly_summary": ("{n} autopilot: {money} this week {dot}", "{n} autopilots: {money} this week {dot}"),
        "chart_this_week": "Equity this week",
        # quiet hours and the health alarm
        "quiet_over": "Quiet hours are over",
        "held_summary": ("{n} lab post was held back from {start} to {end}.",
                         "{n} lab posts were held back from {start} to {end}."),
        "time": "Time",
        "post": "Post",
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
    },
    "de": {
        "more_rows": "+{n} weitere",
        "more_in_app": "+{n} weitere in der App",
        "more_in_reports": "(mehr in den Berichten)",
        "equity": "Wert",
        "today": "Heute",
        "since_start": "Seit Start",
        "vs_btc": "ggü. BTC",
        "pts": "{v} Pkt.",
        "trades_today": "Abschlüsse heute",
        "trades_today_value": "{n} · Gebühren {fees}",
        "trades": "Abschlüsse",
        "trades_total": "{n} insgesamt · Gebühren {fees}",
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
        "health": "Systemzustand",
        "no_health": "keine Systemprüfung gefunden",
        "last_check": " (letzte Prüfung vor {h} h)",
        "all_green": "✅ alles grün{late}",
        "n_red": "🔴 {n} rot: {names}{late}",
        "no_learning": "Kein Lernbericht gefunden.",
        "running_today": ("{n} Autopilot läuft, heute {money} {dot}", "{n} Autopiloten laufen, heute {money} {dot}"),
        "running": ("{n} Autopilot läuft.", "{n} Autopiloten laufen."),
        "btc_suffix": " · BTC {pct}",
        "none_running": "Kein Autopilot läuft{err}.",
        "more_autopilots": "{n} weitere Autopiloten in der App",
        "no_equity": "kein Wert gemeldet",
        "learning": "Lernen",
        "stale_learning": "der letzte Bericht ist vom {gen}, nicht von heute",
        "daily_title": "Tagesbericht · {day}",
        "chart_since_start": "Wert seit Start",
        "weekly_title": "Wochenbericht · {span}",
        "no_engine": "Pythia hat nicht geantwortet: diese Woche keine Zahlen.",
        "no_autopilot": "Kein Autopilot läuft.",
        "this_week": "Diese Woche",
        "below_peak": "Unter Höchststand",
        "trades_week": "{n} diese Woche",
        "trades_since": "{n} seit Start",
        "best_sleeve": "Bestes Teilportfolio",
        "best_worst": "{best} {best_money} · schwächstes {worst} {worst_money}",
        "weekly_summary": ("{n} Autopilot: diese Woche {money} {dot}", "{n} Autopiloten: diese Woche {money} {dot}"),
        "chart_this_week": "Wert diese Woche",
        "quiet_over": "Ruhezeit vorbei",
        "held_summary": ("{n} Labor-Meldung wurde von {start} bis {end} zurückgehalten.",
                         "{n} Labor-Meldungen wurden von {start} bis {end} zurückgehalten."),
        "time": "Zeit",
        "post": "Meldung",
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
    },
}

# Model titles (lab.models) in German, by code; another code keeps its title.
MODEL_TITLES_DE = {
    "M8": "Richtung am nächsten Tag",
    "M8q": "Renditespanne am nächsten Tag (Quantile 10/50/90 %)",
    "M10": "Tagesvolatilität mit Regime",
    "M11": "Slippage von Demo-Marktorders",
    "M12": "Korrelationsregime BTC ggü. US-Aktien",
}

# The factory's gates (lab.factory.writeup.GATE_LABEL) in German.
GATES_DE = {"is_stable": "IS-Hälften", "oos_positive": "OOS > 0", "stress": "70 Basispunkte", "drawdown": "DD < BTC",
            "late_fill": "späte Ausführung", "twin": "Zwilling", "deflated": "Deflation", "forward": "Vorwärtsmonat"}

# Words the lab writes into its data, said in German.
WORDS_DE = {
    # factory statuses and holdout decisions
    "promoted": "übernommen", "retired": "ausgemustert", "active": "aktiv", "shadow": "Schattenlauf",
    "stopped": "gestoppt", "already shadowed": "schon im Schattenlauf", "duplicate": "Doppelgänger",
    "waiting": "wartet",
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
