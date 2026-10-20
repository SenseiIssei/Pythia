"""One flat record per Polymarket market: identity, category, kind, fees, outcome, tokens.

Category is Polymarket's fee category (docs.polymarket.com, "Fees", 2026-10),
read from the market's tags (and the old `category` field of 2020 to 2023
markets): crypto, sports, politics, geopolitics, finance, economics, tech,
culture, mentions, weather, other. The first matching rule wins, in the order
of CATEGORY_RULES, so "Sports" beats "Politics" on a market tagged both.

Kind splits the categories by how a market is made:
  updown   a recurring "Up or Down" market on a price (5 minutes to a month),
           thousands of near-identical markets, sampled apart from the rest
  game     a single game (Gamma gives it a game start time)
  event    everything else (an election, a court case, a launch)

Fees (taker only; makers pay none):
  fee = shares * rate * (p * (1 - p)) ** exponent
with the market's own feeSchedule when Gamma gives one, else the category's
rate from the published table. Geopolitics markets are fee-free.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone

# The published taker fee rates by category (exponent 1), 2026-10.
FEE_RATE = {"crypto": 0.07, "sports": 0.05, "finance": 0.04, "politics": 0.04, "mentions": 0.04, "tech": 0.04,
            "economics": 0.05, "culture": 0.05, "weather": 0.05, "other": 0.05, "geopolitics": 0.0}
CATEGORIES = tuple(FEE_RATE)

_S = lambda *xs: frozenset(x.lower() for x in xs)  # noqa: E731
CATEGORY_RULES: list[tuple[str, frozenset]] = [
    ("sports", _S("Sports", "NBA", "NFL", "MLB", "NHL", "Soccer", "football", "american football", "Tennis", "Golf",
                  "UFC", "MMA", "Boxing", "Esports", "Chess", "Formula 1", "F1", "Cricket", "Olympics", "Games",
                  "college football", "CFB (All)", "Basketball", "Baseball", "Hockey", "Super Bowl",
                  "FIFA World Cup", "2026 FIFA World Cup", "Premier League", "Champions League", "NCAA",
                  "March Madness", "Player Futures", "Team Props", "Grand Prix", "WNBA", "La Liga", "Serie A",
                  "Bundesliga", "Ligue 1", "MLS", "EPL", "Wimbledon", "US Open", "Ballon d'Or")),
    ("crypto", _S("Crypto", "Bitcoin", "Ethereum", "Solana", "XRP", "Crypto Prices", "cryptocurrency", "NFTs", "DeFi",
                  "blockchain", "Airdrops", "FDV", "Stablecoins", "Memecoins", "Dogecoin", "Token Sales",
                  "Public Sales")),
    ("mentions", _S("Mentions", "Mention Markets", "Earnings Mentions")),
    ("weather", _S("Weather", "Climate", "Hurricanes", "Temperature", "Global Temp", "Climate & Weather")),
    ("geopolitics", _S("Geopolitics", "World", "Middle East", "Israel", "Iran", "Ukraine", "Russia", "Gaza",
                       "Foreign Policy", "international relations", "Peace Deal", "U.S. x Iran", "Nuclear",
                       "Military", "War", "China", "Taiwan", "deprecgeopolitcs", "Global Politics")),
    ("economics", _S("Economy", "Economics", "Fed", "Fed Rates", "Inflation", "CPI", "Recession", "Jobs Report",
                     "Economic Policy", "Interest Rates", "GDP", "Unemployment", "Tariffs", "Trade War", "economy1")),
    ("finance", _S("Finance", "Stocks", "Equities", "Business", "Commodities", "IPOs", "stock market", "Earnings",
                   "investment", "market predictions", "Pre-Market", "Finance Updown", "Indices", "Gold", "Oil")),
    ("tech", _S("Tech", "technology", "AI", "Science", "Big Tech", "OpenAI", "SpaceX", "Space", "Apple", "Google",
                "Elon Musk", "Coronavirus", "COVID-19")),
    ("culture", _S("Culture", "Pop Culture", "Pop-Culture", "Movies", "Music", "Awards", "Oscars", "Grammys",
                   "entertainment", "Celebrities", "TV", "Box Office", "Tweet Markets", "Twitter", "social media",
                   "Taylor Swift", "YouTube", "Netflix", "Spotify")),
    ("politics", _S("Politics", "Elections", "US Election", "Trump", "Midterms", "Global Elections", "World Elections",
                    "Primaries", "Senate Elections", "Governor Elections", "President", "Congress", "Biden",
                    "US-current-affairs", "presidential election", "2024 election", "voting", "republican party",
                    "democratic party", "Supreme Court", "Courts")),
]


def parse_ms(v) -> int | None:
    """Gamma's times: ISO with Z, 'YYYY-MM-DD HH:MM:SS+00', or a date. None when missing."""
    if v is None or v == "":
        return None
    s = str(v).strip().replace(" ", "T", 1)
    s = re.sub(r"\+00(:00)*$", "+00:00", s)
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        try:
            dt = datetime.strptime(s[:10], "%Y-%m-%d")
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def _json_list(v) -> list:
    if isinstance(v, list):
        return v
    try:
        out = json.loads(v or "[]")
        return out if isinstance(out, list) else []
    except (TypeError, ValueError):
        return []


def tag_labels(m: dict) -> list[str]:
    return [str(t.get("label") or "") for t in (m.get("tags") or []) if isinstance(t, dict)]


def category(m: dict) -> str:
    labels = {x.lower().strip() for x in tag_labels(m)}
    old = str(m.get("category") or "").lower().strip()
    if old:
        labels.add(old)
    for name, rule in CATEGORY_RULES:
        if labels & rule:
            return name
    q = str(m.get("question") or "").lower()
    if m.get("gameStartTime"):
        return "sports"
    for name, rx in KEYWORD_RULES:
        if rx.search(q):
            return name
    return "other"


# Old markets (2020 to 2023) mostly carry only the tag "All": their question decides.
KEYWORD_RULES: list[tuple[str, re.Pattern]] = [(n, re.compile(p)) for n, p in [
    ("sports", r"\b(nba|nfl|mlb|nhl|ufc|fifa|uefa|premier league|world cup|super bowl|stanley cup|world series|"
               r"grand slam|wimbledon|olympic|playoffs?|championship|finals|grand prix|f1|tennis|golf|boxing|"
               r"knockout|vs\.?|touchdowns?|win the (game|match|series))\b"),
    ("crypto", r"\b(bitcoin|btc|ethereum|eth|solana|sol|xrp|dogecoin|doge|ftx|binance|coinbase|crypto|nft|"
               r"airdrop|token|stablecoin|usdt|usdc|defi|memecoin|polygon|matic)\b"),
    ("mentions", r"\b(say|mention|said)\b.*\b(during|in|at)\b"),
    ("weather", r"\b(temperature|hurricane|snow|rainfall|heat ?wave|weather|tornado|degrees)\b"),
    ("geopolitics", r"\b(nato|putin|russia|ukraine|zelensky|china|xi jinping|taiwan|israel|gaza|hamas|iran|"
                    r"north korea|war|ceasefire|invade|invasion|military|nuclear|missile|troops|sanctions)\b"),
    ("economics", r"\b(fed|fomc|interest rates?|rate (hike|cut)|inflation|cpi|gdp|recession|debt ceiling|"
                  r"unemployment|jobs report|payrolls|tariffs?|treasury|yield)\b"),
    ("finance", r"\b(stock|shares|s&p|nasdaq|dow|usd/|eur/|ipo|earnings|market cap|gold|oil|brent|wti|"
                r"tesla|nvidia|apple|microsoft|amazon|bankrupt)\b"),
    ("tech", r"\b(ai|openai|chatgpt|gpt-?\d|spacex|starship|launch|iphone|google|twitter|x\.com|meta|"
             r"covid|vaccine|virus|science|mars|moon)\b"),
    ("culture", r"\b(tweet|tweets|movie|box office|album|oscars?|grammys?|emmys?|song|netflix|spotify|youtube|"
                r"celebrity|taylor swift|kanye|kardashian|tiktok|mrbeast|billboard|eurovision|time person)\b"),
    ("politics", r"\b(election|elected|president|presidential|senate|house|congress|trump|biden|harris|governor|"
                 r"parliament|prime minister|vote|votes|party|primary|nominee|impeach|cabinet|supreme court|"
                 r"mayor|referendum|poll)\b"),
]]


def kind(m: dict) -> str:
    q = str(m.get("question") or "")
    labels = {x.lower() for x in tag_labels(m)}
    if "up or down" in q.lower() or "finance updown" in labels or "updown" in str(m.get("slug") or ""):
        return "updown"
    if m.get("gameStartTime") or "games" in labels:
        return "game"
    return "event"


def fee_schedule(m: dict, cat: str | None = None) -> tuple[float, float, str]:
    """(rate, exponent, source). source 'market' when Gamma gave a schedule, else 'table'."""
    fs = m.get("feeSchedule")
    if isinstance(fs, dict) and fs.get("rate") is not None:
        try:
            return float(fs["rate"]), float(fs.get("exponent") or 1.0), "market"
        except (TypeError, ValueError):
            pass
    return FEE_RATE.get(cat or category(m), 0.05), 1.0, "table"


def taker_fee(shares: float, price: float, rate: float, exponent: float = 1.0) -> float:
    """USDC fee on a taker fill, rounded to 5 decimals as the exchange does."""
    if shares <= 0 or rate <= 0 or not 0.0 < price < 1.0:
        return 0.0
    return round(shares * rate * (price * (1.0 - price)) ** exponent, 5)


def outcome_yes(m: dict) -> float | None:
    """1.0 when the first outcome won, 0.0 when the second did, 0.5 for a 50-50
    resolution, None while open or undecided. Only meaningful on a closed market."""
    px = _json_list(m.get("outcomePrices"))
    if len(px) != 2:
        return None
    try:
        a, b = float(px[0]), float(px[1])
    except (TypeError, ValueError):
        return None
    if a >= 0.99 and b <= 0.01:
        return 1.0
    if b >= 0.99 and a <= 0.01:
        return 0.0
    if abs(a - 0.5) < 0.01 and abs(b - 0.5) < 0.01:
        return 0.5
    return None


def _num(v) -> float | None:
    try:
        f = float(v)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def record(m: dict, desc_chars: int = 1500) -> dict:
    """The flat record kept for a market (resolved or open)."""
    toks = _json_list(m.get("clobTokenIds"))
    outs = _json_list(m.get("outcomes"))
    ev = (m.get("events") or [{}])[0] if isinstance(m.get("events"), list) and m.get("events") else {}
    cat = category(m)
    rate, expo, src = fee_schedule(m, cat)
    return {
        "id": str(m.get("id") or ""),
        "condition_id": str(m.get("conditionId") or ""),
        "question": str(m.get("question") or "")[:400],
        "slug": str(m.get("slug") or ""),
        "event_id": str(ev.get("id") or ""),
        "event_slug": str(ev.get("slug") or ""),
        "event_title": str(ev.get("title") or "")[:300],
        "category": cat,
        "kind": kind(m),
        "tags": "|".join(tag_labels(m))[:500],
        "neg_risk": bool(m.get("negRisk")),
        "outcome_a": str(outs[0]) if len(outs) > 0 else "",
        "outcome_b": str(outs[1]) if len(outs) > 1 else "",
        "yes_token": str(toks[0]) if len(toks) > 0 else "",
        "no_token": str(toks[1]) if len(toks) > 1 else "",
        "created_ms": parse_ms(m.get("createdAt")),
        "start_ms": parse_ms(m.get("startDate")),
        "end_ms": parse_ms(m.get("endDate")),
        "closed_ms": parse_ms(m.get("closedTime")),
        "game_ms": parse_ms(m.get("gameStartTime")),
        "closed": bool(m.get("closed")),
        "outcome": outcome_yes(m) if m.get("closed") else None,
        "volume": _num(m.get("volumeNum")) or 0.0,
        "liquidity": _num(m.get("liquidityNum")) or 0.0,
        "volume_24h": _num(m.get("volume24hr")),
        "best_bid": _num(m.get("bestBid")),
        "best_ask": _num(m.get("bestAsk")),
        "last_price": _num(m.get("lastTradePrice")),
        "spread": _num(m.get("spread")),
        "tick": _num(m.get("orderPriceMinTickSize")),
        "min_size": _num(m.get("orderMinSize")),
        "fee_rate": rate,
        "fee_exponent": expo,
        "fee_source": src,
        "accepting": bool(m.get("acceptingOrders")) if m.get("acceptingOrders") is not None else None,
        "description": str(m.get("description") or "")[:desc_chars],
        "resolution_source": str(m.get("resolutionSource") or "")[:200],
    }
