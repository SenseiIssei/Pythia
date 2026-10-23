"""The alpha mode's trade cards: every swap of the on-chain trader in mode=alpha, to Telegram and Discord.

One card per swap that reached the chain (filled or failed), in the messages' language and, for
Discord, again in the other one (notify.Card.remake): the Alpha phase in the title, the amounts,
what it was worth in USD, the network fee, the book or "conversion", a Solscan link. The colour
bar follows the outcome by the leading emoji (notify.DISCORD_COLORS): green filled at a cost under
MAX_GOOD_COST_BPS against Jupiter's prices, orange filled dearer, red failed. Sent through
notify.send("trades", ..., discord="trades"), the real-money route the pump.fun bot's trade cards
take (#pumpfun-trades and a DM). Never raises: an alert never stops the trader.
"""

from __future__ import annotations

from . import live_gate as LG

MAX_GOOD_COST_BPS = 25.0

WORDS = {
    "de": {"filled": "Alpha-Phase: {a} zu {b} getauscht", "failed": "Alpha-Phase: Swap {a} zu {b} fehlgeschlagen",
           "summary_book": "Buch {book}, echtes Geld in kleinen Beträgen, um unsere Modelle zu messen.",
           "summary_convert": "Dein Umtausch aus der App, Alpha-Phase.",
           "summary_kill": "Notschalter: Verkauf nach USDC, Alpha-Phase.",
           "paid": "Gegeben", "got": "Erhalten", "value": "Wert", "cost": "Kosten", "fee": "Netzwerkgebühr",
           "why": "Grund", "link": "Transaktion", "footer": "On-Chain-Wallet · Alpha-Phase, kleines echtes Geld"},
    "en": {"filled": "Alpha phase: swapped {a} to {b}", "failed": "Alpha phase: swap {a} to {b} failed",
           "summary_book": "Book {book}, small real money to measure our own models.",
           "summary_convert": "Your conversion from the app, Alpha phase.",
           "summary_kill": "Kill switch: sale into USDC, Alpha phase.",
           "paid": "Paid", "got": "Got", "value": "Value", "cost": "Cost", "fee": "Network fee",
           "why": "Why", "link": "Transaction", "footer": "On-chain wallet · Alpha phase, small real money"},
}


def _amount(v: float | None, code: str) -> str:
    if v is None:
        return "n/a"
    return f"{v:,.6f}".rstrip("0").rstrip(".") + f" {code}"


def outcome_emoji(status: str, cost_bps: float | None) -> str:
    if status != "filled":
        return "🔴"
    return "🟢" if cost_bps is None or cost_bps <= MAX_GOOD_COST_BPS else "🟠"


def alpha_card(s, r: dict, lang: str = "de", fee_sol: float | None = None):
    """The card of one alpha swap `s` (live_exec.Swap) with its result `r` (live_exec.Trader.execute)."""
    from ..ops import notify
    w = WORDS.get(lang, WORDS["en"])
    status = r.get("status") or "failed"
    src, dst = LG.CODES.get(s.src), LG.CODES.get(s.dst)
    in_amt = s.in_raw / 10 ** src.decimals if src else None
    out_amt = int(r["out_raw"]) / 10 ** dst.decimals if dst and r.get("out_raw") is not None else None
    in_usd, out_usd = r.get("in_usd"), r.get("out_usd")
    cost = (in_usd - out_usd) / in_usd * 1e4 if status == "filled" and in_usd and out_usd is not None else None
    rows = [(w["paid"], _amount(in_amt, s.src), None)]
    if status == "filled":
        rows.append((w["got"], _amount(out_amt, s.dst), None))
    if in_usd is not None:
        rows.append((w["value"], f"{in_usd:,.2f} USD", None))
    if cost is not None:
        rows.append((w["cost"], f"{cost:.1f} bps", -1 if cost > MAX_GOOD_COST_BPS else None))
    if fee_sol is not None:
        rows.append((w["fee"], f"{fee_sol:.6f} SOL", None))
    if r.get("why"):
        rows.append((w["why"], str(r["why"])[:120], None))
    summary = (w["summary_book"].format(book=s.book) if s.kind == "book" else
               w["summary_kill"] if s.kind == "kill" else w["summary_convert"])
    parts = [notify.Rows(rows)]
    if r.get("sig"):
        parts.append(notify.Links([("Solscan", f"https://solscan.io/tx/{r['sig']}")], lead=w["link"]))
    card = notify.Card(outcome_emoji(status, cost), w[status if status == "filled" else "failed"].format(a=s.src, b=s.dst),
                       summary, parts, footer=w["footer"])
    card.lang, card.remake = lang, (lambda lg: alpha_card(s, r, lg, fee_sol))
    card.discord = True                                  # a real-money trade: Discord gets it too
    return card


def fee_of(sig: str | None) -> float | None:
    """The fee the swap paid, from the ledger row the executor wrote for it."""
    from . import live_exec as LX
    if not sig:
        return None
    for row in reversed(LX.read_ledger()):
        if row.get("sig") == sig:
            f = LX._f(row.get("fee_l"))
            return f / 1e9 if f is not None else None
    return None


def post_alpha(s, r: dict, view=None, send=None) -> dict | None:
    """Post the alpha card of one swap. `send` replaces notify.send (tests). Never raises."""
    try:
        from ..ops import notify
        card = alpha_card(s, r, notify.alert_lang(), fee_of(r.get("sig")))
        return (send or notify.send)("trades", [card], urgent=True, discord="trades")
    except Exception as e:                               # an alert never stops the trader
        print(f"onchain live: alpha card not sent ({type(e).__name__}: {e})", flush=True)
        return None

