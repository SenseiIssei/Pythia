"""A made-up Pokemon card market served the way the Pokemon TCG API serves it.

Used by the tests only: it lets the collector run end to end against a fake
HTTP opener, day after day, so the studies, models, paper collection and
alerts have a history to work on. The prices follow a known rule (cheap cards
next to similar ones drift up), so a working forecaster has something to find.
"""

from __future__ import annotations

import json
import math
from datetime import date, timedelta
from urllib.parse import parse_qs, urlparse

import numpy as np

RARITIES = [("Common", 0.2), ("Uncommon", 0.4), ("Rare", 1.2), ("Rare Holo", 3.0), ("Double Rare", 6.0),
            ("Ultra Rare", 15.0), ("Illustration Rare", 25.0), ("Special Illustration Rare", 80.0)]
NAMES = ["Charizard ex", "Pikachu", "Umbreon VMAX", "Bulbasaur", "Squirtle", "Gengar", "Snorlax", "Psyduck",
         "Professor's Research", "Boss's Orders", "Mew ex", "Rattata", "Magikarp", "Dragonite", "Lugia V"]


class Market:
    def __init__(self, start: date, n_sets: int = 12, per_set: int = 40, seed: int = 3, signal: float = 0.01):
        rng = np.random.default_rng(seed)
        self.rng = rng
        self.signal = signal
        self.sets = []
        for i in range(n_sets):
            rel = start - timedelta(days=int(30 + (n_sets - 1 - i) * 150))
            self.sets.append({"id": f"s{i}", "name": f"Set {i}", "series": "Scarlet & Violet" if i > 6 else "Sword & Shield",
                              "printedTotal": per_set - 5, "total": per_set, "releaseDate": rel.strftime("%Y/%m/%d"),
                              "updatedAt": "2026/01/01 00:00:00", "ptcgoCode": f"S{i}",
                              "images": {"symbol": "x", "logo": "y"}})
        self.cards = []
        for s in self.sets:
            for j in range(per_set):
                rar, base = RARITIES[min(int(j / per_set * len(RARITIES) + rng.random() * 0.5), len(RARITIES) - 1)]
                name = NAMES[(j * 7 + int(s["id"][1:])) % len(NAMES)]
                sup = "Trainer" if "Professor" in name or "Boss" in name else "Pokémon"
                fair = base * (3.0 if "Charizard" in name else 1.6 if "Pikachu" in name else 1.0) * \
                    (1.5 if j >= s["printedTotal"] else 1.0)
                mis = rng.normal(0, 0.35)  # today's price off its fair value
                self.cards.append({"id": f"{s['id']}-{j + 1}", "name": name, "supertype": sup,
                                   "subtypes": ["Basic"], "types": ["Fire"], "number": str(j + 1), "rarity": rar,
                                   "artist": "A", "nationalPokedexNumbers": [6], "set": s,
                                   "images": {"small": f"https://images.pokemontcg.io/{s['id']}/{j + 1}.png",
                                              "large": f"https://images.pokemontcg.io/{s['id']}/{j + 1}_hires.png"},
                                   "_fair": math.log(max(fair, 0.05)), "_log": math.log(max(fair, 0.05)) + mis,
                                   "_eur": []})
        self.day = start

    def step(self) -> None:
        """One day: prices pull toward fair value (the signal) plus noise."""
        for c in self.cards:
            c["_log"] += self.signal * (c["_fair"] - c["_log"]) + self.rng.normal(0, 0.03)
        self.day += timedelta(days=1)

    def card_json(self, c: dict, eurusd: float) -> dict:
        usd = math.exp(c["_log"])
        eur = usd / eurusd * math.exp(self.rng.normal(-0.1, 0.1))
        c["_eur"] = (c["_eur"] + [eur])[-30:]
        e = c["_eur"]
        out = {k: v for k, v in c.items() if not k.startswith("_")}
        out["tcgplayer"] = {"url": "https://prices.pokemontcg.io/tcgplayer/" + c["id"],
                            "updatedAt": self.day.strftime("%Y/%m/%d"),
                            "prices": {"holofoil": {"low": usd * 0.8, "mid": usd, "high": usd * 2, "market": usd},
                                       "normal": {"low": usd * 0.1, "mid": usd * 0.2, "market": usd * 0.2}}}
        out["cardmarket"] = {"url": "https://prices.pokemontcg.io/cardmarket/" + c["id"],
                             "updatedAt": self.day.strftime("%Y/%m/%d"),
                             "prices": {"trendPrice": eur, "averageSellPrice": eur, "lowPrice": eur * 0.7,
                                        "avg1": e[-1], "avg7": float(np.mean(e[-7:])), "avg30": float(np.mean(e))}}
        return out

    def opener(self, eurusd: float = 1.10, fail_first: int = 0):
        """A fake urllib opener for today; `fail_first` answers that many 503s first."""
        state = {"fails": fail_first}
        cards = [self.card_json(c, eurusd) for c in self.cards]

        def open_(url: str, headers: dict, timeout: float):
            if state["fails"] > 0:
                state["fails"] -= 1
                return 503, {"Retry-After": "1"}, b""
            u = urlparse(url)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            if "eurofxref" in url:
                return 200, {}, f"<Cube currency='USD' rate='{eurusd}'/>".encode()
            page, size = int(q.get("page", 1)), int(q.get("pageSize", 250))
            if u.path.endswith("/sets"):
                rows = self.sets
            elif u.path.endswith("/cards"):
                rows = cards
            else:
                return 404, {}, b""
            body = {"data": rows[(page - 1) * size: page * size], "page": page, "pageSize": size,
                    "count": len(rows[(page - 1) * size: page * size]), "totalCount": len(rows)}
            return 200, {}, json.dumps(body).encode()

        return open_


def build_lake(days: int, start: date = date(2026, 1, 1), **kw) -> Market:
    """Run the real collector for `days` days into $PYTHIA_DATA."""
    from lab.collect import pokemon as col
    m = Market(start, **kw)
    for _ in range(days):
        cl = col.Client(opener=m.opener(), sleep=lambda s: None, spacing=0.0)
        col.collect(m.day.isoformat(), min_usd=1.0, client=cl, log=lambda *a: None)
        m.step()
    return m
