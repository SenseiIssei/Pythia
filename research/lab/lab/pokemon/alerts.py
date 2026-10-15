"""Telegram (or webhook) alerts for Pokemon cards: strong moves, cheap cards
and new sets, each with what a buyer needs to look the card up by hand.

Uses the lab's notifier (`lab.ops.notify`, category "pokemon", so the app's
switch and the quiet hours apply): PYTHIA_TELEGRAM_BOT_TOKEN and
PYTHIA_TELEGRAM_CHAT_ID, or PYTHIA_ALERT_WEBHOOK. Unset: printed only.

  strong move   a card worth at least $20 that moved 20 % or more since the
                previous snapshot (at most 3 days back), or 35 % over 7 days.
                Before we have a previous snapshot: Cardmarket's avg1 against
                avg7, 30 % or more, on a card with a trend of 20 EUR or more,
                only where Cardmarket is fresh (none was on 2026-10-15).
  undervalued   a card at $10 to $500 whose fair value is 2 to 3 times
                its price (more is model error), from a set at least 60 days old, and whose 90-day
                forecast is positive. Until the forecast validates this rests
                on the fair-value model alone, and the message says so.
  new set       a main set (TCGplayer through tcgcsv) released within the
                last 30 days or coming within 60, first seen with at least 10
                priced singles: its 5 dearest singles. At most 2 sets a day.

Every card in an alert carries: name, set, number, rarity, the condition the
prices are for (ungraded, which printing), the price now in USD (TCGplayer
market) and EUR (Cardmarket trend and average sell price) with the date of
each and a warning when Cardmarket's is older than 14 days, fair value and
the gap to it, the 30 and 90 day forecasts with how far to trust them, the
recent change, and links to the card on Cardmarket and TCGplayer
(lab.pokemon.links). On Telegram the card pictures (small) go first as one
album, then the list.

A card is alerted at most once per kind every 7 days, a new set once
(<lake>/alerts.json). At most 5 cards per alert. An alert held back by
quiet hours or not delivered is tried again the next day.
"""

from __future__ import annotations

import json
import math
import os
from datetime import date
from pathlib import Path

import polars as pl

from ..collect.pokemon import CM_FRESH_DAYS
from ..ops import notify
from . import links

MOVE_MIN_USD, MOVE_1D, MOVE_7D = 20.0, 0.20, 0.35
CM_MOVE, CM_MIN_EUR = 0.30, 20.0
UV_MIN_USD, UV_MAX_USD, UV_GAP, UV_MIN_AGE = 10.0, 500.0, 1.0, 60
# The fair value is off by a factor of about 1.7 for a typical card (first real
# snapshot), and the largest gaps are mostly its failures (promos at 25x). Only
# a fair value of 2x to 3x the price makes a message; beyond is model error.
UV_GAP_MAX = 2.0
COOLDOWN_DAYS = 7
MAX_MOVES, MAX_UV = 5, 5
NEW_SET_CARDS, NEW_SET_MIN_SINGLES, NEW_SET_MAX = 5, 10, 2
NEW_SET_AGE = (-60, 30)
FOOTER = "Information only; nothing is bought or sold. You trade by hand."


def _num(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _days(a: str | None, b: str | None) -> int | None:
    try:
        return (date.fromisoformat(str(b)[:10]) - date.fromisoformat(str(a)[:10])).days
    except (TypeError, ValueError):
        return None


def _chg(r) -> float | None:
    """A log return as a simple one."""
    r = _num(r)
    return None if r is None else math.expm1(r)


# ---------------------------------------------------------------- what to alert

def strong_moves(snap: pl.DataFrame) -> list[dict]:
    out = []
    for r in snap.filter(pl.col("price") >= MOVE_MIN_USD).to_dicts():
        r1, r7 = r.get("ret_1d"), r.get("ret_7d")
        move, basis = None, None
        if r1 is not None and abs(math.expm1(r1)) >= MOVE_1D:
            move, basis = math.expm1(r1), "since the last snapshot"
        elif r7 is not None and abs(math.expm1(r7)) >= MOVE_7D:
            move, basis = math.expm1(r7), "over 7 days"
        elif r1 is None and r7 is None and (r.get("cm_trend") or 0) >= CM_MIN_EUR:
            m = r.get("cm_mom_1_7")
            if m is not None and abs(m) >= CM_MOVE:
                move, basis = m, "Cardmarket 1-day vs 7-day average"
        if move is not None:
            out.append({"card_id": r["card_id"], "name": r["name"], "set": r.get("set_name"), "price": r["price"],
                        "move": move, "basis": basis, "_row": r})
    return sorted(out, key=lambda x: -abs(x["move"]))


def undervalued(snap: pl.DataFrame) -> list[dict]:
    s = snap.filter(pl.col("price").is_between(UV_MIN_USD, UV_MAX_USD)
                    & pl.col("fv_gap").is_between(math.log1p(UV_GAP), math.log1p(UV_GAP_MAX))
                    & (pl.col("set_age_days") >= UV_MIN_AGE) & (pl.col("pred_90d") > 0))
    return [{"card_id": r["card_id"], "name": r["name"], "set": r.get("set_name"), "price": r["price"],
             "fair": math.exp(r["fv_log"]), "gap": math.expm1(r["fv_gap"]), "pred_90d": r["pred_90d"], "_row": r}
            for r in s.sort("fv_gap", descending=True).to_dicts()]


def new_sets(singles: pl.DataFrame | None, today: str) -> list[dict]:
    """Main sets out within the last 30 days or due within 60, on the latest
    singles snapshot, each with its dearest singles and their change since
    the snapshot before."""
    if singles is None or singles.is_empty() or "main_set" not in singles.columns:
        return []
    snap = singles["date"].max()
    s = singles.filter((pl.col("date") == snap) & pl.col("main_set") & (pl.col("market") > 0))
    prev_day = singles.filter(pl.col("date") < snap)["date"].max() if (singles["date"] < snap).any() else None
    prev = {}
    if prev_day is not None:
        p = singles.filter(pl.col("date") == prev_day)
        prev = dict(zip(p["product_id"].to_list(), p["market"].to_list()))
    out = []
    for (gid, name, pub), g in s.group_by("group_id", "group_name", "published_on"):
        age = _days(pub, today)
        if age is None or not NEW_SET_AGE[0] <= age <= NEW_SET_AGE[1] or g.height < NEW_SET_MIN_SINGLES:
            continue
        top = g.sort("market", descending=True).head(NEW_SET_CARDS).to_dicts()
        for c in top:
            old = _num(prev.get(c.get("product_id")))
            c["chg_prev"] = c["market"] / old - 1 if old else None
            c["prev_day"] = prev_day if old else None
        out.append({"set_id": str(gid), "set": name, "released": pub, "age_days": age, "singles": g.height,
                    "cards": top})
    return sorted(out, key=lambda x: (abs(x["age_days"]), x["set"]))


def _cool(state: dict, kind: str, cid: str, today: str) -> bool:
    last = (state.get(kind) or {}).get(cid)
    return last is None or (date.fromisoformat(today) - date.fromisoformat(last)).days >= COOLDOWN_DAYS


# ---------------------------------------------------------------- what a buyer needs per card

def trust(horizons: dict | None, validated: bool) -> tuple[str, str]:
    """(level, words) for the 30 and 90 day forecasts."""
    hz = horizons or {}
    done = []
    for h in ("30", "90"):
        e = hz.get(h) or hz.get(int(h)) or {}
        if e.get("validated"):
            ic, n = _num(e.get("mean_rank_ic")), e.get("test_months")
            done.append(f"{h} d tested" + (f", rank IC {ic:.2f} over {n} months" if ic is not None and n else ""))
    if len(done) == 2:
        return "tested", "tested out of sample (" + "; ".join(done) + ")"
    if done:
        return "mixed", "; ".join(done) + "; the other horizon an untested rule"
    if validated:
        return "mixed", "partly tested"
    return "low", "low, an untested rule (fair-value gap)"


def detail(r: dict, today: str, horizons: dict | None = None, validated: bool = False) -> dict:
    """Everything an alert and the page show for one card of the lake."""
    snap_day = str(r.get("date") or today)
    cm_day = r.get("cm_updated")
    cm_age = _days(cm_day, snap_day)
    eur = _num(r.get("cm_trend"))
    level, words = trust(horizons, validated)
    fv = _num(r.get("fv_log"))
    variant = r.get("tp_variant")
    ch30, ch30_src = _chg(r.get("ret_30d")), "snapshots"
    if ch30 is None and r.get("cm_fresh") and _num(r.get("cm_trend_30")) is not None:
        ch30, ch30_src = _num(r.get("cm_trend_30")), "cardmarket"
    return {
        "card_id": r.get("card_id"), "name": r.get("name"), "set": r.get("set_name"), "number": r.get("number"),
        "rarity": r.get("rarity"), "image": r.get("image_small"),
        "condition": "ungraded" + (f", {variant} printing" if variant else ""),
        "usd": _num(r.get("price")), "usd_src": "TCGplayer market" if r.get("price_src", "tcgplayer") == "tcgplayer"
        else "Cardmarket trend in USD",
        "usd_date": r.get("tp_updated") if r.get("price_src", "tcgplayer") == "tcgplayer" else cm_day,
        "eur_trend": eur, "eur_avg": _num(r.get("cm_avg_sell")) or _num(r.get("cm_avg30")),
        "eur_low_explus": _num(r.get("cm_low_explus")),
        "eur_date": cm_day if eur is not None else None, "eur_age_days": cm_age if eur is not None else None,
        "eur_stale": bool(eur is not None and (cm_age is None or cm_age > CM_FRESH_DAYS)),
        "fair": math.exp(fv) if fv is not None else None, "gap": _chg(r.get("fv_gap")),
        "pred_30d": _num(r.get("pred_30d")), "pred_90d": _num(r.get("pred_90d")),
        "trust": level, "trust_words": words,
        "chg_1d": _chg(r.get("ret_1d")), "chg_7d": _chg(r.get("ret_7d")), "chg_30d": ch30, "chg_30d_src": ch30_src,
        **links.for_card(r),
    }


def single_detail(c: dict, set_name: str, snap_day: str) -> dict:
    """The same for a single of a new set (TCGplayer through tcgcsv): no
    Cardmarket price, no fair value or forecast yet."""
    return {
        "card_id": f"tcgplayer:{c.get('product_id')}", "name": links.search_name(c.get("name")), "set": set_name,
        "number": c.get("number"), "rarity": c.get("rarity"), "image": c.get("image_url"),
        "condition": "ungraded" + (f", {c['sub_type']} printing" if c.get("sub_type") else ""),
        "usd": _num(c.get("market")), "usd_src": "TCGplayer market", "usd_date": c.get("date") or snap_day,
        "eur_trend": None, "eur_avg": None, "eur_low_explus": None, "eur_date": None, "eur_age_days": None,
        "eur_stale": False, "fair": None, "gap": None, "pred_30d": None, "pred_90d": None,
        "trust": "none", "trust_words": "no fair value or forecast: the card API does not price this set yet",
        "chg_1d": _num(c.get("chg_prev")), "chg_7d": None, "chg_30d": None, "chg_30d_src": "snapshots",
        **links.for_card({"name": c.get("name"), "url": c.get("url")}),
    }


def _usd(v) -> str:
    return "n/a" if v is None else f"${v:,.2f}"


def _eur(v) -> str:
    return "n/a" if v is None else f"€{v:,.2f}"


def _pct(v, dp: int = 0) -> str:
    return "n/a" if v is None else f"{v * 100:+.{dp}f} %"


def price_line(d: dict) -> str:
    s = f"Now {_usd(d['usd'])} ({d['usd_src']}, {d.get('usd_date') or 'date n/a'})"
    if d.get("eur_trend") is not None:
        s += f" · Cardmarket {_eur(d['eur_trend'])} trend"
        if d.get("eur_avg") is not None:
            s += f", {_eur(d['eur_avg'])} avg sell"
        s += f" ({d.get('eur_date') or 'date n/a'}"
        if d.get("eur_stale"):
            age = d.get("eur_age_days")
            s += f", ⚠️ {age} days old, stale" if age is not None else ", ⚠️ undated, stale"
        s += ")"
    else:
        s += " · no Cardmarket price"
    return s


def value_line(d: dict) -> str:
    if d.get("fair") is None and d.get("pred_90d") is None:
        w = d["trust_words"]
        return w[:1].upper() + w[1:]
    parts = []
    if d.get("fair") is not None:
        parts.append(f"Fair {_usd(d['fair'])} ({_pct(d.get('gap'))} vs price)")
    parts.append(f"forecast 30 d {_pct(d.get('pred_30d'))}, 90 d {_pct(d.get('pred_90d'))}")
    parts.append(f"trust: {d['trust_words']}")
    return " · ".join(parts)


def change_line(d: dict, move: dict | None = None) -> str:
    """The recent change: the move that made the alert first, then the other
    horizons we have (1 day is the last snapshot, a few days back at most)."""
    bits = []
    if move:
        bits.append(f"Moved {_pct(move['move'])} {move['basis']}")
    said = {"since the last snapshot": "chg_1d", "over 7 days": "chg_7d"}.get(move["basis"]) if move else None
    for k, label in (("chg_1d", "1 d"), ("chg_7d", "7 d"), ("chg_30d", "30 d")):
        v = d.get(k)
        if v is None or k == said:
            continue
        src = " (Cardmarket)" if k == "chg_30d" and d.get("chg_30d_src") == "cardmarket" else ""
        bits.append(f"{label} {_pct(v)}{src}")
    if not bits:
        return "No price change yet: our history starts with the first snapshot"
    return " · ".join(bits) if move else "Change " + " · ".join(bits)


def link_part(d: dict) -> notify.Links:
    cm = "Cardmarket" if d.get("cardmarketKind") == "product" else "Cardmarket search"
    tp = "TCGplayer" if d.get("tcgplayerKind") == "product" else "TCGplayer search"
    return notify.Links([(cm, d.get("cardmarket")), (tp, d.get("tcgplayer"))])


def card_parts(i: int, d: dict, move: dict | None = None) -> list:
    where = " · ".join(x for x in [f"{d.get('set') or '?'}" + (f" #{d['number']}" if d.get("number") else ""),
                                   d.get("rarity"), d.get("condition")] if x)
    return [notify.Line(f"({where})", f"{i}. {d.get('name')}"), notify.Line(price_line(d)), notify.Line(value_line(d)),
            notify.Line(change_line(d, move)), link_part(d)]


def photos(title: str, ds: list[dict]) -> list[tuple[str, str]]:
    """The small pictures for the album, the list of names as its caption."""
    cap = f"<b>{notify.esc(title)}</b>\n" + "\n".join(f"{i}. {notify.esc(d.get('name'))} · {_usd(d.get('usd'))}"
                                                      for i, d in enumerate(ds, 1))
    return [(d["image"], cap) for d in ds if d.get("image")]


def moves_card(moves: list[dict], details: list[dict]) -> notify.Card:
    n = len(moves)
    parts: list = []
    for i, (m, d) in enumerate(zip(moves, details), 1):
        parts += card_parts(i, d, m)
    return notify.Card(notify.CATEGORIES["pokemon"][1], f"{n} card{'s' if n != 1 else ''} moved strongly",
                       "Worth $20 or more and moved 20 % since the last snapshot or 35 % in 7 days.", parts, FOOTER)


def uv_card(uv: list[dict], details: list[dict], validated: bool) -> notify.Card:
    n = len(uv)
    parts: list = []
    for i, d in enumerate(details, 1):
        parts += card_parts(i, d)
    why = ("Priced at a third to a half of what similar cards cost, positive 90-day forecast. "
           + ("The forecast is validated." if validated else
              "Fair-value model only; the return forecast is not validated yet."))
    return notify.Card(notify.CATEGORIES["pokemon"][1], f"{n} card{'s' if n != 1 else ''} cheap next to similar ones",
                       why, parts, FOOTER)


def new_set_card(s: dict, details: list[dict]) -> notify.Card:
    when = (f"out in {-s['age_days']} days" if s["age_days"] < 0 else "out today" if s["age_days"] == 0
            else f"out {s['age_days']} days")
    parts: list = []
    for i, d in enumerate(details, 1):
        parts += card_parts(i, d)
    return notify.Card("🆕", f"New set: {s['set']}",
                       f"Released {s.get('released') or '?'} ({when}), {s['singles']} singles priced on TCGplayer. "
                       "The dearest five; prices of a set this new swing hard.", parts, FOOTER)


def message(moves: list[dict], uv: list[dict], today: str, validated: bool, prefix: str = "Pythia",
            horizons: dict | None = None, sets: list[dict] | None = None) -> str:
    """All of today's alerts as plain text (the log and the app)."""
    cards = []
    if moves:
        cards.append(moves_card(moves, [m.get("detail") or detail(m.get("_row") or m, today, horizons, validated)
                                        for m in moves]))
    if uv:
        cards.append(uv_card(uv, [u.get("detail") or detail(u.get("_row") or u, today, horizons, validated)
                                  for u in uv], validated))
    for s in sets or []:
        cards.append(new_set_card(s, s["details"]))
    text = "\n\n".join(notify.plain(c.render("telegram")) for c in cards)
    return notify.nodash(f"{prefix} cards {today}\n{text}" if text else f"{prefix} cards {today}")


def _public(x: dict) -> dict:
    return {k: v for k, v in x.items() if not k.startswith("_")}


def run(snap: pl.DataFrame, root: Path, today: str, validated: bool, dry_run: bool = False,
        horizons: dict | None = None, singles: pl.DataFrame | None = None) -> dict:
    path = root / "alerts.json"
    try:
        state = json.loads(path.read_text())
    except (OSError, ValueError):
        state = {}
    moves = [m for m in strong_moves(snap) if _cool(state, "move", m["card_id"], today)][:MAX_MOVES]
    uv = [u for u in undervalued(snap) if _cool(state, "undervalued", u["card_id"], today)][:MAX_UV]
    for x in moves + uv:
        x["detail"] = detail(x["_row"], today, horizons, validated)
    sets = [s for s in new_sets(singles, today) if (state.get("new_set") or {}).get(s["set_id"]) is None][:NEW_SET_MAX]
    for s in sets:
        s["details"] = [single_detail(c, s["set"], str(c.get("date") or today)) for c in s["cards"]]
    out = {"moves": [_public(m) for m in moves], "undervalued": [_public(u) for u in uv],
           "newSets": [{k: v for k, v in s.items() if k != "cards"} for s in sets], "sent": False, "text": None}
    if not moves and not uv and not sets:
        return out
    prefix = notify.config()[2]
    out["text"] = message(moves, uv, today, validated, prefix, horizons, sets)
    posts = []
    if moves:
        posts.append(("move", [m["card_id"] for m in moves], moves_card(moves, [m["detail"] for m in moves]),
                      photos("Strong moves", [m["detail"] for m in moves])))
    if uv:
        posts.append(("undervalued", [u["card_id"] for u in uv], uv_card(uv, [u["detail"] for u in uv], validated),
                      photos("Cheap next to similar cards", [u["detail"] for u in uv])))
    for s in sets:
        posts.append(("new_set", [s["set_id"]], new_set_card(s, s["details"]), photos(f"New set: {s['set']}", s["details"])))
    results = []
    for kind, ids, card, pics in posts:
        res = notify.send("pokemon", [card], photos=pics, dry_run=dry_run)
        results.append({"kind": kind, "delivered": res["delivered"], "reason": res["reason"], "error": res["error"]})
        if dry_run or res["reason"] == "quiet" or (res["reason"] is None and not res["delivered"]):
            continue  # not said: try again tomorrow
        for cid in ids:
            state.setdefault(kind, {})[cid] = today
    out["results"] = results
    out["sent"] = any(r["delivered"] for r in results)
    errs = [r["error"] for r in results if r["error"]]
    if errs:
        out["error"] = errs[0]
    if dry_run:
        return out
    tmp = path.with_name(path.name + ".tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(json.dumps(state), encoding="utf-8")
    os.replace(tmp, path)
    return out
