"""Where to look a card up by hand: its Cardmarket and TCGplayer pages.

The Pokemon TCG API gives every card it prices a `cardmarket.url` and a
`tcgplayer.url` (prices.pokemontcg.io/cardmarket/<id> and .../tcgplayer/<id>,
which redirect to the product page on the market). The collector keeps them
as `cm_url` and `tp_url`; tcgcsv singles carry TCGplayer's own product URL.
Those are used as they are, when they point at one of the hosts below.

Without one, the link is a search on the market for the card's exact name.
The set's name is not put in the query: Cardmarket's search matches product
names, and its single cards are named after the card (with a set code, not
the set's name), so name plus set name risks an empty result page. The alert
and the page name the set next to the link, and the search lists every
printing with its set. Every query is URL-encoded, so a name like
"Professor's Research" or "Pikachu & Zekrom-GX" cannot break the link.

Nothing here fetches anything; the owner opens the links.
"""

from __future__ import annotations

import re
from urllib.parse import quote, urlsplit

CARDMARKET_SEARCH = "https://www.cardmarket.com/en/Pokemon/Products/Search"
TCGPLAYER_SEARCH = "https://www.tcgplayer.com/search/pokemon/product"

CARDMARKET_HOSTS = {"prices.pokemontcg.io", "www.cardmarket.com", "cardmarket.com"}
TCGPLAYER_HOSTS = {"prices.pokemontcg.io", "www.tcgplayer.com", "tcgplayer.com", "shop.tcgplayer.com"}


def _clean(s) -> str:
    return " ".join(str(s or "").split())


def known_url(u, hosts: set[str], path_prefix: str | None = None) -> str | None:
    """`u` when it is an https URL on one of `hosts` (and, on the API's
    redirect host, under `path_prefix`), else None."""
    if not isinstance(u, str) or not u.strip():
        return None
    u = u.strip()
    try:
        p = urlsplit(u)
    except ValueError:
        return None
    if p.scheme != "https" or (p.hostname or "").lower() not in hosts or p.username or p.password:
        return None
    if any(ord(c) <= 32 or c in '"<>\\`' for c in u):
        return None
    if path_prefix and (p.hostname or "").lower() == "prices.pokemontcg.io" and not p.path.startswith(path_prefix):
        return None
    return u


# TCGplayer names the singles of new sets "Mew ex - 152/128" or "Mew - R/RGB":
# the number after the dash is not part of the card's name elsewhere.
_NUMBER_SUFFIX = re.compile(r"\s+-\s+[A-Za-z]{0,6}\d*[A-Za-z]*/[A-Za-z0-9]+$|\s+-\s+\d+[A-Za-z]?$")


def search_name(name) -> str:
    """The card's name as a market lists it: whitespace folded, a trailing
    TCGplayer number (" - 152/128") dropped."""
    s = _clean(name)
    t = _NUMBER_SUFFIX.sub("", s).strip()
    return t or s


def cardmarket_search(name: str) -> str:
    return f"{CARDMARKET_SEARCH}?searchString={quote(search_name(name), safe='')}"


def tcgplayer_search(name: str) -> str:
    return f"{TCGPLAYER_SEARCH}?productLineName=pokemon&q={quote(search_name(name), safe='')}&view=grid"


def cardmarket(cm_url, name) -> tuple[str | None, str]:
    """(url, kind): the card's own page ("product") or a search ("search");
    (None, "none") without a name either."""
    u = known_url(cm_url, CARDMARKET_HOSTS, "/cardmarket/")
    if u:
        return u, "product"
    return (cardmarket_search(name), "search") if _clean(name) else (None, "none")


def tcgplayer(tp_url, name) -> tuple[str | None, str]:
    u = known_url(tp_url, TCGPLAYER_HOSTS, "/tcgplayer/")
    if u:
        return u, "product"
    return (tcgplayer_search(name), "search") if _clean(name) else (None, "none")


def for_card(row: dict) -> dict:
    """Both links of a card row (lake columns, or a tcgcsv single with `url`)."""
    name = row.get("name")
    cm, cm_kind = cardmarket(row.get("cm_url"), name)
    tp, tp_kind = tcgplayer(row.get("tp_url") or row.get("url"), name)
    return {"cardmarket": cm, "cardmarketKind": cm_kind, "tcgplayer": tp, "tcgplayerKind": tp_kind}
