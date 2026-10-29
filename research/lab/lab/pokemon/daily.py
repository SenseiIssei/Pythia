"""The daily Pokemon card job, after the collector: studies, fair value,
forecasts, the paper collection, alerts, the Cards page's data and the report.

  python -m lab.pokemon.daily               everything
  python -m lab.pokemon.daily --dry-run     compute and print; no collection
                                            step, no alert sent, no files
  python -m lab.pokemon.daily --no-alerts   everything but the alerts

Exits 1 after everything is written when no price source has a price of
the last three days (lab.collect.pokemon.stale_sources): the collector exits
0 on a snapshot of old prices so that this part, chained with &&, still runs
on them, and the job turns red here, with one line naming the stale sources
and since when. A single stale source is named in that line and the report,
the job stays green.

Writes
  <lake>/ui/latest.json                     the Cards page (served read-only
                                            by the engine at /api/pokemon)
  <lake>/paper/                             the paper collection
  reports/pokemon/latest.{md,json}          the daily report (Lab page)
  reports/pokemon/monthly/YYYY-MM.md        on the first run of a month, the
                                            month before: collection, trades,
                                            model status, studies
  <lake>/_derived/fv/                       fair values per day (cache)

Data and paper only. Nothing here can place an order anywhere.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import polars as pl

from .. import report
from ..collect.pokemon import lake, stale_sources
from . import alerts, collection, links, model, study
from . import data as pdata

NAME = "pokemon"
UI_TOP_PRICE, UI_TOP_PRED, UI_HISTORY = 300, 60, 180


def _f(v, digits: int = 4):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return round(x, digits) if math.isfinite(x) else None


def _chg(r):
    return None if r is None or not math.isfinite(r) else round(math.expm1(r) * 100, 2)


def ui_cards(snap: pl.DataFrame, hist: pl.DataFrame, extra_ids: set[str]) -> list[dict]:
    by_price = set(snap.sort("price", descending=True).head(UI_TOP_PRICE)["card_id"].to_list())
    by_pred = set(snap.filter(pl.col("tp_market") >= collection.MIN_PRICE)
                  .sort("pred_90d", descending=True).head(UI_TOP_PRED)["card_id"].to_list())
    ids = by_price | by_pred | extra_ids
    pick = snap.filter(pl.col("card_id").is_in(list(ids))).sort("price", descending=True)
    h = (hist.filter(pl.col("card_id").is_in(list(ids))).sort("date")
         .group_by("card_id").agg(pl.col("date").tail(UI_HISTORY), pl.col("price").tail(UI_HISTORY)))
    hmap = {r["card_id"]: list(zip(r["date"], [_f(p, 2) for p in r["price"]])) for r in h.to_dicts()}
    out = []
    for r in pick.to_dicts():
        c30 = _chg(r.get("ret_30d"))
        c30_src = "snapshots"
        if c30 is None and r.get("cm_trend_30") is not None:
            c30, c30_src = _f(r["cm_trend_30"] * 100, 2), "cardmarket"
        lk = links.for_card(r)
        out.append({
            "id": r["card_id"], "name": r["name"], "set": r.get("set_name"), "setId": r.get("set_id"),
            "number": r.get("number"), "rarity": r.get("rarity"), "releaseDate": r.get("release_date"),
            "image": r.get("image_small"), "imageLarge": r.get("image_large"),
            "priceUsd": _f(r["price"], 2), "priceSrc": r.get("price_src"), "variant": r.get("tp_variant"),
            "cardmarketEur": _f(r.get("cm_trend"), 2), "spreadPct": _chg(r.get("spread")),
            "cardmarketUpdated": r.get("cm_updated"), "cardmarketFresh": bool(r.get("cm_fresh")),
            "cardmarketAvgEur": _f(r.get("cm_avg_sell"), 2), "tcgplayerUpdated": r.get("tp_updated"),
            # The card's own page from the API, else a search for its exact name (lab.pokemon.links).
            "tcgplayerUrl": lk["tcgplayer"], "cardmarketUrl": lk["cardmarket"],
            "tcgplayerLink": lk["tcgplayerKind"], "cardmarketLink": lk["cardmarketKind"],
            "change1dPct": _chg(r.get("ret_1d")), "change7dPct": _chg(r.get("ret_7d")),
            "change30dPct": c30, "change30dSrc": c30_src,
            "pred30dPct": _f((r.get("pred_30d") or 0) * 100, 2), "pred90dPct": _f((r.get("pred_90d") or 0) * 100, 2),
            "predSrc": r.get("pred_src"),
            "fairUsd": _f(math.exp(r["fv_log"]), 2) if r.get("fv_log") is not None and math.isfinite(r["fv_log"]) else None,
            "fairGapPct": _chg(r.get("fv_gap")),
            "character": r.get("character"), "altArt": bool(r.get("alt_art")),
            "history": hmap.get(r["card_id"], []),
        })
    return out


def ui_new_sets(rows: list[dict], singles: pl.DataFrame, top: int = 6) -> list[dict]:
    """The newest main sets with their dearest singles, for the Cards page.
    Prices from TCGplayer through tcgcsv; the API itself has none for them."""
    if not rows or singles.is_empty():
        return []
    snap = singles["date"].max()
    s = singles.filter((pl.col("date") == snap) & pl.col("main_set"))
    out = []
    for r in rows[:8]:
        g = s.filter(pl.col("group_name") == r["set"]).sort("market", descending=True).head(top)
        out.append({"set": r["set"], "released": r["released"], "ageDays": r["age_days"], "singles": r["singles"],
                    "top10MeanUsd": _f(r["top10_mean_usd"], 2), "boosterBoxUsd": _f(r["booster_box_usd"], 2),
                    "cards": [{"name": c["name"], "number": c["number"], "rarity": c["rarity"],
                               "priceUsd": _f(c["market"], 2), "image": c["image_url"],
                               "url": links.tcgplayer(c["url"], c["name"])[0],
                               "cardmarketUrl": links.cardmarket(None, c["name"])[0]}
                              for c in g.to_dicts()]})
    return out


def ui_collection(d: Path) -> dict:
    st = collection.load_state(d)
    j = collection.journal(d)
    eq = float(st.get("equity") or collection.START)
    return {
        "start": collection.START, "started": st.get("started"), "equity": eq,
        "equityMarket": float(st.get("equity_market") or eq), "cash": round(float(st.get("cash") or 0), 2),
        "returnPct": round((eq / collection.START - 1) * 100, 2),
        "holdings": [{"id": h["card_id"], "name": h["name"], "set": h.get("set_name"), "image": h.get("image"),
                      "qty": h["qty"], "buyPrice": h["buy_price"], "price": h["price"], "bought": h["bought"],
                      "changePct": round((h["price"] / h["buy_price"] - 1) * 100, 2) if h["buy_price"] else None,
                      "why": f"{h.get('pred_src_at_buy', 'prior')} forecast {h.get('pred_90d_at_buy', 0) * 100:+.0f} % "
                             "for 90 days"}
                     for h in st.get("holdings") or []],
        "curve": [[r["date"], float(r["equity"])] for r in j],
        "trades": collection.trades(d)[-30:],
    }


def verdict(meta: dict, mstat: dict, fv: dict, coll: dict) -> str:
    r2 = fv.get("r2")
    return (f"{meta['cards']:,} cards on {meta['snapshot']} ({mstat['history_days']} {'day' if mstat['history_days'] == 1 else 'days'} of our own history). "
            f"Fair value explains {r2 * 100:.0f} % of log prices across sets (out of fold). " if r2 is not None else
            f"{meta['cards']:,} cards on {meta['snapshot']}. ") + mstat["sentence"] + (
            f" Paper collection {coll['returnPct']:+.1f} % after modelled card costs." if coll.get("started") else "")


def _usd(v) -> str:
    return f"${v:,.2f}" if v is not None else "n/a"


def feed(meta: dict, mstat: dict, coll: dict, al: dict, top: list[dict], now: datetime | None = None) -> dict:
    """The common lab feed header (docs/LAB-FEEDS.md) for reports/pokemon/latest.json:
    bad when the snapshot is more than two days old, watch when a card moved
    strongly or looks cheap today, ok otherwise."""
    now = now or datetime.now(timezone.utc)
    age = (now.date() - datetime.fromisoformat(meta["snapshot"]).date()).days
    moves, uv = al.get("moves") or [], al.get("undervalued") or []
    status = "bad" if age > 2 else ("watch" if moves or uv else "ok")
    fr = meta.get("freshness") or {}
    items: list[dict] = []
    for m in moves[:5]:
        items.append({"label": f"{m['name']} ({m.get('set') or '?'})", "value": f"{m['move'] * 100:+.0f} %",
                      "status": "watch", "detail": f"Moved {m['basis']}, now {_usd(m.get('price'))}. Information only.",
                      "link": "study:pokemon", "importance": min(80, 50 + abs(m["move"]) * 50)})
    for u in uv[:3]:
        items.append({"label": f"{u['name']} ({u.get('set') or '?'})", "value": f"{u['gap'] * 100:+.0f} % to fair",
                      "status": "ok", "detail": f"{_usd(u.get('price'))} against a fair value of {_usd(u.get('fair'))} "
                                                "from similar cards; " + ("the forecast is validated." if mstat["validated"]
                                                                          else "the forecast is not validated yet."),
                      "link": "study:pokemon", "importance": 45})
    if coll.get("started"):
        items.append({"label": "Paper collection (play money)", "value": f"{coll['returnPct']:+.1f} %",
                      "status": "ok" if coll["returnPct"] >= 0 else "watch",
                      "detail": f"Worth {_usd(coll['equity'])} if sold today after card costs, from "
                                f"${coll['start']:,.0f} on {coll['started']}.", "link": "study:pokemon", "importance": 25})
    for c in top[:3]:
        items.append({"label": f"{c['name']} ({c.get('set') or '?'})", "value": f"{(c.get('pred90dPct') or 0):+.0f} % in 90 d",
                      "detail": f"Now {_usd(c.get('priceUsd'))}; " + ("model forecast." if c.get("predSrc") == "model"
                                                                     else "a fixed rule, not a validated model."),
                      "link": "study:pokemon", "importance": 15})
    if fr.get("cardmarket_cards") and fr.get("cardmarket_fresh_share", 1) < 0.5:
        items.append({"label": "Cardmarket prices are stale", "value": f"{fr['cardmarket_fresh_share'] * 100:.0f} % fresh",
                      "status": "watch", "detail": f"The API last refreshed most Cardmarket prices on "
                                                   f"{fr.get('cardmarket_newest') or '?'} or before; the EU side and its "
                                                   "averages are left out until they update.",
                      "link": "study:pokemon", "importance": 20})
    n = len(moves)
    if age > 2:
        head = f"No new card prices since {meta['snapshot']}: the daily collector has not run for {age} days."
    elif moves or uv:
        parts = ([f"{n} card{'s' if n != 1 else ''} moved strongly"] if n else []) + (
            [f"{len(uv)} {'look' if len(uv) != 1 else 'looks'} cheap next to similar cards"] if uv else [])
        head = " and ".join(parts) + f" on {meta['snapshot']}. Information only; you buy and sell by hand."
    else:
        head = (f"{meta['cards']:,} card prices on {meta['snapshot']}, nothing unusual. "
                f"{mstat['history_days']} day{'s' if mstat['history_days'] != 1 else ''} of our own price history so far.")
    return report.feed_header("Pokemon cards", status, head, items)


def clean(v):
    """JSON-safe: NaN and infinities become null (the engine's reader rejects them)."""
    if isinstance(v, float):
        return v if math.isfinite(v) else None
    if isinstance(v, dict):
        return {k: clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [clean(x) for x in v]
    if isinstance(v, np.generic):
        return clean(v.item())
    return v


def _freshness_line(meta: dict) -> str:
    fr = meta.get("freshness") or {}
    stale = f"\n- Stale: {meta['stale'].split(': ', 2)[2]}." if meta.get("stale") else ""
    if not fr:
        return "- Price freshness: not recorded by this collector run." + stale
    return (f"- Price freshness: TCGplayer {fr.get('tcgplayer_fresh', 0):,} of {fr.get('tcgplayer_cards', 0):,} "
            f"updated within a week (newest {fr.get('tcgplayer_newest') or 'n/a'}); Cardmarket "
            f"{fr.get('cardmarket_fresh', 0):,} of {fr.get('cardmarket_cards', 0):,} within two weeks (newest "
            f"{fr.get('cardmarket_newest') or 'n/a'}). Stale Cardmarket rows are left out of every Cardmarket "
            "number below (trend, averages, spread)." + (
                " Sets were rebuilt from the cards (the /sets endpoint failed)." if meta.get("sets_source") == "cards"
                else "")) + stale


def _tbl(rows: list[dict], cols: list[str]) -> str:
    return report.table(rows, cols) if rows else "(no rows)\n"


def markdown(meta: dict, studies: dict, fv: dict, mstat: dict, coll: dict, al: dict, top: list[dict]) -> str:
    rel, rep, prem, spr = studies["release"], studies["reprint"], studies["premium"], studies["spread"]
    out = [f"# Pokemon cards ({meta['snapshot']})", "",
           "Data and paper only. No order is ever placed; the owner trades cards by hand.", "",
           "## Data", "",
           f"- Snapshot {meta['snapshot']}: {meta['cards']:,} cards at or above the collector's price floor, "
           f"{meta['sets']} sets, EUR/USD {meta.get('eurusd') or 'n/a'} ({meta.get('fx_source') or 'n/a'}).",
           f"- Our own price history: {mstat['history_days']} day{'' if mstat['history_days'] == 1 else 's'} over {meta['snapshots']} snapshot{'' if meta['snapshots'] == 1 else 's'}. "
           "Every return-based number below needs this history; the API itself keeps no history beyond "
           "Cardmarket's avg1 / avg7 / avg30.",
           f"- Sealed product: {meta.get('sealed') if meta.get('sealed') is not None else 'not collected'}.",
           _freshness_line(meta), "",
           "## Model status", "", mstat["sentence"], ""]
    hz = []
    for h, e in mstat["horizons"].items():
        hz.append({"horizon": f"{h} d", "labelled_rows": e.get("labelled_rows", 0), "test_months": e.get("test_months", 0),
                   "mean_rank_ic": e.get("mean_rank_ic"), "ic_t": e.get("ic_t"), "mae": e.get("mae"),
                   "mae_zero": e.get("mae_zero"), "validated": e.get("validated")})
    out += [_tbl(hz, ["horizon", "labelled_rows", "test_months", "mean_rank_ic", "ic_t", "mae", "mae_zero",
                      "validated"]),
            "Walk-forward by month, purged by the horizon; these are backtests on our own snapshots, out of sample.", "",
            "## Fair value (cross-section, not a forecast)", "",
            f"Out-of-fold R2 {fv.get('r2'):.3f} on {fv.get('cards')} cards, folds grouped by set." if fv.get("r2") is not None
            else "Not fitted (too few cards or sets).", "",
            "## Price by rarity and character (latest snapshot)", "",
            f"OLS of log price, HC1 t-statistics, R2 {prem['r2']:.3f}. Premium = price against a common, "
            "non-character Pokemon card of the same set age, all else equal.", "",
            _tbl(prem["rows"], ["feature", "premium_pct", "t", "cards"])]
    if prem.get("trend_r2") is not None and math.isfinite(prem["trend_r2"]):
        out += [f"Same features against the Cardmarket 30-day trend (trend / avg30 - 1, points; fresh Cardmarket "
                f"rows only), R2 {prem['trend_r2']:.3f}:", "", _tbl(prem["trend_rows"], ["feature", "trend_pts", "t"])]
    else:
        out += ["Who has been rising (the same features against Cardmarket's 30-day trend): not possible today, "
                "no card has a fresh Cardmarket trend. Our own snapshots replace it after 30 days.", ""]
    has_trend = any(r.get("median_trend_vs_avg30_pct") is not None for r in rel["cross"])
    out += ["## Around set release", ""]
    if has_trend:
        out += ["Cross-section now: Cardmarket trend against its 30-day average, by set age. A description of the "
                "last 30 days across sets of different ages, not one set followed over time.", "",
                _tbl(rel["cross"], ["set_age", "sets", "cards", "median_trend_vs_avg30_pct",
                                    "median_avg7_vs_avg30_pct", "median_price_usd"])]
    else:
        out += ["Cards the Pokemon TCG API prices at $2 or more, by set age (no fresh Cardmarket trend today, so "
                "no recent direction). Note the API has no price for any set of the last months.", "",
                _tbl(rel["cross"], ["set_age", "sets", "cards", "median_price_usd"])]
    if rel.get("new_sets"):
        out += ["New and coming main sets from TCGplayer (through tcgcsv.com), which the Pokemon TCG API does not "
                "price yet. Chase basket = mean of the 10 dearest singles; a negative age is a set not out yet "
                "(pre-order prices).", "",
                _tbl([{**r, "age_days": r["age_days"]} for r in rel["new_sets"]],
                     ["set", "released", "age_days", "singles", "top10_mean_usd", "median_usd", "booster_box_usd",
                      "dearest"])]
        nsp = rel.get("new_sets_panel") or {}
        if nsp.get("ready"):
            out += ["From our snapshots: 30-day change of each set's chase basket, by the set's age.", "",
                    _tbl(nsp["rows"], ["set_age", "sets", "set_days", "mean_30d_pct", "t"])]
        else:
            out += [f"Release curve of new sets from our snapshots: waiting for {nsp.get('waiting_days', 30)} more days.",
                    ""]
    if rel["panel"]["ready"]:
        out += ["From our snapshots: mean 30-day log return of a set's median card, by set age.", "",
                _tbl(rel["panel"]["rows"], ["set_age", "sets", "set_days", "mean_30d_pct", "t"])]
    else:
        out += [f"Panel from our snapshots: waiting for {rel['panel']['waiting_days']} more days.", ""]
    out += ["## Reprints", "",
            f"{rep['events']} reprint events (later printings of the same card text: name, HP, attacks, abilities; plus listed announcements); "
            f"{rep['reprinted_now']} cards reprinted in the last {study.REPRINT_WINDOW} days.", "",
            _tbl(rep["cross"], ["rarity_group", "reprinted", "others", "reprinted_trend_pct", "others_trend_pct",
                                "difference_pts"])]
    if rep["panel"]["ready"]:
        out += ["Excess return of reprinted cards over their rarity group, around the event (30-day scale):", "",
                _tbl(rep["panel"]["rows"], ["window", "cards", "card_days", "excess_30d_pct", "t"])]
    else:
        out += [f"Event study from our snapshots: waiting for {rep['panel']['waiting_days']} more days.", ""]
    out += ["## TCGplayer against Cardmarket", "",
            (f"{spr['cards']} cards with both prices (Cardmarket fresh); TCGplayer over Cardmarket (in USD): median "
             f"{spr.get('median_pct') or 0:+.1f} %, middle half {spr.get('p25_pct') or 0:+.1f} % to "
             f"{spr.get('p75_pct') or 0:+.1f} %. Shipping, import duty and fees of 15 % or more a side make most "
             "of this untradeable." if spr["cards"] else
             "No card has both a TCGplayer price and a fresh Cardmarket price today, so there is no honest spread."),
            "",
            _tbl(spr["rows"], ["tcgplayer_price", "cards", "median_pct", "share_us_30pct_dearer", "share_eu_30pct_dearer"]),
            "## Paper collection (play money)", "",
            (f"Started {coll['started']} with ${coll['start']:,.0f}. Worth ${coll['equity']:,.2f} if sold today after "
             f"costs ({coll['returnPct']:+.2f} %), ${coll['equityMarket']:,.2f} at market. {len(coll['holdings'])} cards held."
             if coll.get("started") else "Not started."), ""]
    if coll["holdings"]:
        out.append(_tbl([{"card": h["name"], "set": h["set"], "qty": h["qty"], "bought": h["bought"],
                          "buy": h["buyPrice"], "now": h["price"], "change_pct": h["changePct"]}
                         for h in coll["holdings"]], ["card", "set", "qty", "bought", "buy", "now", "change_pct"]))
    out += ["## Top forecasts today", "",
            _tbl([{"card": c["name"], "set": c["set"], "price": c["priceUsd"], "fair": c["fairUsd"],
                   "pred_90d_pct": c["pred90dPct"], "source": c["predSrc"]} for c in top],
                 ["card", "set", "price", "fair", "pred_90d_pct", "source"]),
            "## Alerts today", "",
            f"{len(al.get('moves') or [])} strong moves, {len(al.get('undervalued') or [])} undervalued cards, "
            f"{len(al.get('newSets') or [])} new-set notes" + (" (sent)." if al.get("sent") else "."),
            "",
            "Every alert lists per card: set, number, rarity, the condition the prices are for (ungraded, which "
            "printing), TCGplayer and Cardmarket prices with their dates (a Cardmarket price older than 14 days is "
            "marked stale), fair value and gap, the 30 and 90 day forecasts with how far to trust them, the recent "
            "change, and links to the card on Cardmarket and TCGplayer (the API's own product links, else a "
            "search for the exact name). Top 5 per alert, the card pictures first on Telegram."]
    return "\n".join(out) + "\n"


def monthly(d: Path, reports: Path, month: str, md_daily: str) -> None:
    """The month before `month`: collection curve, trades, today's report as the model state."""
    y, m = int(month[:4]), int(month[5:7])
    prev = f"{y - 1}-12" if m == 1 else f"{y}-{m - 1:02d}"
    j = [r for r in collection.journal(d) if r["date"].startswith(prev)]
    if not j:
        return
    t = [r for r in collection.trades(d) if r["date"].startswith(prev)]
    a, b = float(j[0]["equity"]), float(j[-1]["equity"])
    text = (f"# Pokemon paper collection, {prev}\n\nPlay money; nothing was bought or sold for real.\n\n"
            f"- Value after costs: ${a:,.2f} on {j[0]['date']} to ${b:,.2f} on {j[-1]['date']} ({(b / a - 1) * 100:+.2f} %), "
            f"{(b / collection.START - 1) * 100:+.2f} % since the start.\n- Trades in the month: {len(t)}.\n\n"
            + (report.table(t, ["date", "side", "name", "qty", "price", "cash", "why"]) if t else "") +
            "\n## State at the start of " + month + "\n\n" + md_daily)
    out = reports / NAME / "monthly"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{prev}.md").write_text(text, encoding="utf-8")


def run(dry_run: bool = False, send_alerts: bool = True, evaluate: bool = True) -> dict:
    t0 = time.time()
    root = lake()
    raw = pdata.load_cards(root)
    if raw.is_empty():
        print("pokemon: no snapshot in the lake yet; run lab.collect.pokemon first", file=sys.stderr)
        return {}
    df = pdata.with_returns(pdata.features(raw))
    df, fv = model.add_fair_value(df, None if dry_run else root / "_derived" / "fv")
    snap, mstat = model.predict(df, evaluate=evaluate)
    today = str(snap["date"].max())
    singles, sealed = pdata.load_singles(root), pdata.load_sealed(root)
    studies = study.run(df, pdata.load_catalog(root), study.read_announced(root), mstat["history_days"],
                        singles, sealed)
    meta_f = root / "meta" / f"{today}.json"
    try:
        cmeta = json.loads(meta_f.read_text())
    except (OSError, ValueError):
        cmeta = {}
    meta = {"snapshot": today, "cards": snap.height, "snapshots": df["date"].n_unique(),
            "sets": snap["set_id"].n_unique(), "eurusd": cmeta.get("eurusd"), "fx_source": cmeta.get("fx_source"),
            "sealed": cmeta.get("sealed"), "freshness": cmeta.get("freshness") or {},
            "sets_source": cmeta.get("sets_source"), "collector_errors": cmeta.get("errors") or [],
            "stale": stale_sources(root, datetime.now(timezone.utc).strftime("%Y-%m-%d"))[1]}
    pdir = root / "paper"
    month_before = collection.load_state(pdir).get("last_rebalance")
    if not dry_run:
        collection.step(snap, pdir, today, str(snap["pred_src"][0]))
    al = alerts.run(snap, root, today, mstat["validated"], dry_run=dry_run or not send_alerts,
                    horizons=mstat["horizons"], singles=singles)
    coll = ui_collection(pdir)
    extra = {h["id"] for h in coll["holdings"]} | {a["card_id"] for a in al["moves"] + al["undervalued"]}
    cards = ui_cards(snap, df, extra)
    top = sorted([c for c in cards if (c["priceUsd"] or 0) >= collection.MIN_PRICE],
                 key=lambda c: -(c["pred90dPct"] or -1e9))[:15]
    md = markdown(meta, studies, fv, mstat, coll, al, top)
    v = verdict(meta, mstat, fv, coll)
    fr = meta["freshness"]
    ui = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), "snapshot": today,
        "historyDays": mstat["history_days"], "snapshots": meta["snapshots"], "eurusd": meta["eurusd"],
        "verdict": v,
        "freshness": {"cardmarketFreshShare": fr.get("cardmarket_fresh_share"),
                      "cardmarketNewest": fr.get("cardmarket_newest"), "tcgplayerNewest": fr.get("tcgplayer_newest")},
        "model": {"validated": mstat["validated"], "sentence": mstat["sentence"],
                  "fairValueR2": fv.get("r2"),
                  "horizons": {h: {k: e.get(k) for k in ("validated", "test_months", "mean_rank_ic", "ic_t",
                                                          "mae", "mae_zero")}
                               for h, e in mstat["horizons"].items()}},
        "cards": cards, "collection": coll, "newSets": ui_new_sets(studies["release"]["new_sets"], singles),
        "alerts": {"moves": al["moves"], "undervalued": al["undervalued"], "newSets": al.get("newSets") or [],
                   "sent": al.get("sent", False)},
        "studies": {"premium": studies["premium"]["rows"], "release": studies["release"]["cross"],
                    "spread": {k: studies["spread"].get(k) for k in ("cards", "median_pct", "p25_pct", "p75_pct")}},
    }
    if dry_run:
        print(md)
        return ui
    ui_path = root / "ui" / "latest.json"
    ui_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = ui_path.with_name("latest.json.tmp")
    tmp.write_text(json.dumps(clean(ui), default=str, allow_nan=False), encoding="utf-8")
    os.replace(tmp, ui_path)
    # A copy next to the report, for an app that only sees reports/. Not
    # named latest.json, so the lab feeds do not list it as a feed.
    rp = Path(report.REPORTS) / NAME / "ui.json"
    rp.parent.mkdir(parents=True, exist_ok=True)
    rtmp = rp.with_name("ui.json.tmp")
    rtmp.write_text(json.dumps(clean(ui), default=str, allow_nan=False), encoding="utf-8")
    os.replace(rtmp, rp)
    data = {"verdict": v, "generated": ui["generated"], "meta": meta, "model": mstat,
            "fair_value": fv, "studies": studies, "collection": {k: coll[k] for k in ("started", "equity", "returnPct")},
            "alerts": {"moves": len(al["moves"]), "undervalued": len(al["undervalued"]),
                       "new_sets": len(al.get("newSets") or [])},
            "seconds": round(time.time() - t0, 1)}
    data.update(feed(meta, mstat, coll, al, top))
    report.write(NAME, md, clean(data))
    if month_before and month_before != today[:7]:
        monthly(pdir, report.REPORTS, today[:7], md)
    return ui


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-alerts", action="store_true")
    ap.add_argument("--no-eval", action="store_true", help="skip the walk-forward (faster; forecasts use the prior)")
    a = ap.parse_args(argv)
    run(dry_run=a.dry_run, send_alerts=not a.no_alerts, evaluate=not a.no_eval)
    red, line = stale_sources(lake(), datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    if line:
        print(line, file=sys.stderr)
    return 1 if red else 0


if __name__ == "__main__":
    raise SystemExit(main())
