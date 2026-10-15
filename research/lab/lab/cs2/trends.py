"""CS2 Steam market trends: the daily Steam price snapshots, what moved, and
whether CS2 items run on (momentum) or come back (mean reversion).

Information only. Nothing here buys or sells anything; the owner looks and
trades by hand, if at all.

Data (lab.collect.cs2 --steam-market, once a day):
  daily/steam_market/   Steam Community Market average sale prices per item
                        over the last 24 hours, 7, 30 and 90 days (USD), from
                        csgotrader's public price file, with the day's EUR per
                        USD. No volume; Steam's own endpoint refuses the lab.
  daily/skinport/       Skinport asks and sales (hourly collector): the
                        volume and the other side of the spread.

What it computes per day:
  changes      1, 7 and 30 days, from our own snapshots (USD, the 24-hour
               average) once they exist. Before that, the source's windows:
               the 24-hour average against the 7 and 30 day averages, which is
               "against its recent average", not a change over exactly that
               span; `basis` says which.
  groups       cases, sticker capsules, stickers, knives and gloves, skins by
               wear (Factory New ... Battle-Scarred), other. No free feed the
               lab uses has a skin's rarity grade, so skins are also split by
               price tier as a stand-in.
  momentum     per group, the rank correlation (IC) of an earlier move with
               the next one. From the windows on day one: the 30-day average
               against the 90-day one, then the 24 hours against the 7 days.
               From our snapshots once there are three weeks: the 7-day
               average's change over a week against its change the week
               after, per day, averaged, with a t value (overlapping days, so
               the t is generous). Above zero leans to momentum, below to
               reversion.
  spread       Steam against Skinport, after both fees: buy on Skinport at the
               lowest ask and sell on Steam at its 24-hour average (the seller
               keeps about 87 % of what the buyer pays, in Steam wallet funds
               that cannot be withdrawn), or buy on Steam at that average and
               sell on Skinport at its recent sale price (8 % fee, cash, after
               a 7-day trade lock). Doppler phases are left out (Steam names
               do not carry the phase).
  drops        cases and capsules seen for the first time, the watchlist's
               release dates and drop-pool events, and what the other cases
               did around the latest one.

Alerts (Telegram through lab.ops.notify, category cs2, at most once per item
and kind every 3 days):
  mover        a liquid item (1 EUR or more, 10 or more Skinport sales in 7
               days) that moved 15 % or more since the last snapshot, or
               before there is one, whose 24-hour average is 20 % or more off
               its 7-day average. Top 5 by size.
  case         a case up 15 % or more in 7 days, and a new case or capsule.
  spread       buying on Steam and selling on Skinport nets 5 % or more after
               fees, or Steam's premium over Skinport is far above its group's
               usual (4 robust deviations and twice its median) where the wallet route
               clears 30 %.
Every alert item links to the item's Steam Community Market listing and its
Skinport page. A summary card with a small chart goes out once a day.

  python -m lab.cs2.trends              today's analysis, alerts and summary
  python -m lab.cs2.trends --dry-run    print, post nothing, write nothing
  python -m lab.cs2.trends --no-alerts  everything but the Telegram posts

Writes <data>/cs2/trends/latest.json (the CS2 page reads it through the
hourly board), trends/alerts_state.json, trends/alerts.jsonl and the report
reports/cs2_trends/latest.{md,json} (a lab feed).
"""

from __future__ import annotations

import json
import math
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

import numpy as np
import polars as pl

from .. import report
from ..collect.cs2 import WATCHLIST, load_watchlist
from ..ops import i18n, notify
from . import market
from .model import spearman

STEAM_LISTING = "https://steamcommunity.com/market/listings/730/"
SKINPORT_ITEM = "https://skinport.com/item/"
SOURCE = "Steam prices: csgotrader.app's public price file (average sales); Skinport: its public API."

MIN_EUR = 1.0
MIN_SALES7 = 10
MOVE_SNAP = 0.15
MOVE_WINDOW = 0.20
CASE_RISE_7D = 0.15
SPREAD_CASH = 0.05
SPREAD_WALLET = 0.30
SPREAD_Z = 4.0
SPREAD_ALERTS = 3  # spread items per day in an alert; the page lists all of them
COOLDOWN_DAYS = 3
TOP = 5
MAX_IN_CARD = 8  # items in one alert message; the rest are on the page
MOMENTUM_DAYS = 21
NEW_DROP_DAYS = 45
WEARS = ["Factory New", "Minimal Wear", "Field-Tested", "Well-Worn", "Battle-Scarred"]
TIERS = [(0, 1, "under 1 EUR"), (1, 10, "1 to 10 EUR"), (10, 100, "10 to 100 EUR"), (100, 1e12, "100 EUR or more")]
PHASED = re.compile(r"(?i)\bdoppler\b")


# ---------------------------------------------------------------- links

def steam_url(name: str) -> str:
    """The item's Steam Community Market listing; the name URL-encoded whole
    ("|", "(", "★" and "™" included)."""
    return STEAM_LISTING + quote(str(name), safe="")


def skinport_slug(name: str) -> str:
    """Skinport's item page slug, as its API's item_page shows it:
    "StatTrak™ Zeus x27 | Tosai (Well-Worn)" -> "stattrak-zeus-x27-tosai-well-worn"."""
    s = str(name).replace("★", " ").replace("™", " ").lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def skinport_url(name: str, item_page: str | None = None) -> str:
    """Skinport's own item page from its API when the collector has it, else
    the same page built from the name."""
    if isinstance(item_page, str) and item_page.startswith(SKINPORT_ITEM) and " " not in item_page:
        return item_page
    return SKINPORT_ITEM + quote(skinport_slug(name), safe="-")


# ---------------------------------------------------------------- groups

def wear_of(name: str) -> str | None:
    m = re.search(r"\(([^()]+)\)\s*$", name)
    return m.group(1) if m and m.group(1) in WEARS else None


def group_of(name: str) -> str:
    n = name.lower()
    if n.startswith("sticker slab"):
        return "sticker slab"
    cat = market.category(name)
    if cat == "sticker":
        return "capsule" if "capsule" in n else "sticker"
    if cat == "case":
        return "case"
    if n.endswith("package"):
        return "capsule"  # souvenir packages drop with a major, like capsules
    if cat == "knife_glove":
        return "knife or glove"
    if cat == "skin":
        w = wear_of(name)
        return f"skin, {w}" if w else "skin"
    return "other"


def tier_of(eur: float | None) -> str | None:
    if eur is None or not math.isfinite(eur):
        return None
    return next(t for lo, hi, t in TIERS if lo <= eur < hi)


# ---------------------------------------------------------------- loading

def history(root: Path | None = None) -> pl.DataFrame:
    """Every daily Steam market snapshot, one row per item and day (`date`)."""
    return market._scan(market.cs2_root(root) / "daily" / "steam_market")


def _at(hist: pl.DataFrame, day: date, back: int, slack: int) -> tuple[date | None, pl.DataFrame]:
    """The snapshot `back` days before `day`, or the nearest one up to
    `slack` days older."""
    have = set(hist["date"].unique().to_list()) if not hist.is_empty() else set()
    for extra in range(slack + 1):
        d = day - timedelta(days=back + extra)
        if d in have:
            return d, hist.filter(pl.col("date") == d)
    return None, pl.DataFrame()


def _ratio(a, b) -> float | None:
    a, b = market.finite(a), market.finite(b)
    return a / b - 1 if a and b and a > 0 and b > 0 else None


def frame(hist: pl.DataFrame, skinport: pl.DataFrame, day: date | None = None) -> tuple[pl.DataFrame, dict]:
    """Today's items with prices in EUR, changes, group, volume, spreads and
    links; and which basis each change used."""
    if hist.is_empty():
        return pl.DataFrame(), {}
    day = day or hist["date"].max()
    now = hist.filter(pl.col("date") == day)
    basis = {}
    out = now.with_columns(
        price_usd=pl.coalesce("usd_24h", "usd_7d"),
        price_basis=pl.when(pl.col("usd_24h").is_not_null()).then(pl.lit("24h")).otherwise(pl.lit("7d")),
    )
    # The spread takes the less flattering of the 24-hour and 7-day averages
    # for each route, so one odd sale on a thin day does not make a gap.
    out = out.with_columns(eur=pl.col("price_usd") * pl.col("eur_per_usd"),
                           eur_lo=pl.min_horizontal("usd_24h", "usd_7d") * pl.col("eur_per_usd"),
                           eur_hi=pl.max_horizontal("usd_24h", "usd_7d") * pl.col("eur_per_usd"))
    for col, back, slack, win in (("chg_1d", 1, 2, None), ("chg_7d", 7, 2, "usd_7d"), ("chg_30d", 30, 3, "usd_30d")):
        d0, old = _at(hist, day, back, slack)
        if d0 is not None and not old.is_empty():
            prev = old.select("name", pl.coalesce("usd_24h", "usd_7d").alias("_p"))
            out = out.join(prev, on="name", how="left").with_columns(
                (pl.col("price_usd") / pl.col("_p") - 1).alias(col)).drop("_p")
            basis[col] = f"snapshot {d0.isoformat()}"
        elif win:
            out = out.with_columns(pl.when(pl.col("usd_24h").is_not_null() & (pl.col(win) > 0))
                                   .then(pl.col("usd_24h") / pl.col(win) - 1).alias(col))
            basis[col] = f"24-hour average against the {win.split('_')[1].replace('d', '-day')} average"
        else:
            out = out.with_columns(pl.lit(None, pl.Float64).alias(col))
            basis[col] = "no earlier snapshot"
    names = out["name"].to_list()
    out = out.with_columns(group=pl.Series([group_of(n) for n in names], dtype=pl.Utf8),
                           phased=pl.Series([bool(PHASED.search(n)) for n in names], dtype=pl.Boolean))
    if not skinport.is_empty():
        # Skinport lists Doppler phases as rows of the same name: one row per name, the cheapest ask.
        sp = skinport.with_columns(sp_ref=market.ref_price(skinport)).sort("min_price", nulls_last=True) \
            .unique("name", keep="first", maintain_order=True)
        cols = ["name", pl.col("min_price").alias("sp_ask"), "sp_ref", pl.col("s7_volume").alias("sp_sales7"),
                pl.col("s24_volume").alias("sp_sales24")]
        if "item_page" in sp.columns:
            cols.append(pl.col("item_page"))
        out = out.join(sp.select(cols), on="name", how="left")
    for c in ("sp_ask", "sp_ref", "sp_sales7", "sp_sales24"):
        if c not in out.columns:
            out = out.with_columns(pl.lit(None, pl.Float64).alias(c))
    if "item_page" not in out.columns:
        out = out.with_columns(pl.lit(None, pl.Utf8).alias("item_page"))
    out = with_spreads(out)
    out = out.with_columns(
        liquid=(pl.col("eur") >= MIN_EUR) & (pl.col("sp_sales7").fill_null(0) >= MIN_SALES7),
        tier=pl.Series([tier_of(v) for v in out["eur"].to_list()], dtype=pl.Utf8))
    return out, basis


def with_spreads(df: pl.DataFrame) -> pl.DataFrame:
    """Both hand routes after fees (see the module text), and Steam's premium.
    Selling on Steam uses the lower of its 24-hour and 7-day averages, buying
    there the higher; selling on Skinport the lower of its ask and its recent
    sale price."""
    if "eur_lo" not in df.columns:
        df = df.with_columns(eur_lo=pl.col("eur"), eur_hi=pl.col("eur"))
    to_steam, to_sp, prem = [], [], []
    for lo, hi, ask, ref, phased in df.select("eur_lo", "eur_hi", "sp_ask", "sp_ref", "phased").iter_rows():
        if phased or not lo or not hi or not ask or not ref or lo <= 0 or ask <= 0 or ref <= 0:
            to_steam.append(None), to_sp.append(None), prem.append(None)
            continue
        sell_sp = min(ask - market.TICK, ref)
        to_steam.append(market.steam_seller_gets(lo) / ask - 1)
        to_sp.append(market.skinport_seller_gets(max(sell_sp, market.TICK)) / hi - 1)
        prem.append(lo / ref - 1)
    return df.with_columns(to_steam=pl.Series(to_steam, dtype=pl.Float64),
                           to_skinport=pl.Series(to_sp, dtype=pl.Float64),
                           steam_premium=pl.Series(prem, dtype=pl.Float64))


# ---------------------------------------------------------------- studies

def _median(s: pl.Series) -> float | None:
    s = s.drop_nulls().drop_nans() if s.dtype.is_float() else s.drop_nulls()
    return float(s.median()) if s.len() else None


def by_group(df: pl.DataFrame, key: str = "group") -> list[dict]:
    """Per group: items, liquid items, median 1/7/30-day change, median
    Steam premium over Skinport, Skinport sales in 7 days."""
    rows = []
    for (g,), x in df.filter(pl.col(key).is_not_null()).group_by(key):
        liq = x.filter(pl.col("liquid"))
        rows.append({"group": g, "items": x.height, "liquid": liq.height,
                     "median_1d": _median(liq["chg_1d"]), "median_7d": _median(liq["chg_7d"]),
                     "median_30d": _median(liq["chg_30d"]), "steam_premium": _median(liq["steam_premium"]),
                     "skinport_sales7": int(liq["sp_sales7"].fill_null(0).sum())})
    return sorted(rows, key=lambda r: -r["liquid"])


def momentum_window(df: pl.DataFrame) -> list[dict]:
    """One snapshot, the source's windows: log(30d/90d) against
    log(24h/7d), per group, liquid items only."""
    x = df.filter(pl.col("liquid") & (pl.col("usd_90d") > 0) & (pl.col("usd_30d") > 0) & (pl.col("usd_7d") > 0)
                  & (pl.col("usd_24h") > 0)).with_columns(
        past=(pl.col("usd_30d") / pl.col("usd_90d")).log(), nxt=(pl.col("usd_24h") / pl.col("usd_7d")).log())
    rows = []
    for g in ["all"] + sorted(x["group"].unique().to_list()):
        y = x if g == "all" else x.filter(pl.col("group") == g)
        ic = spearman(y["past"].to_numpy(), y["nxt"].to_numpy()) if y.height else None
        rows.append({"group": g, "items": y.height, "ic": ic, "lean": lean(ic)})
    return rows


def momentum_snapshots(hist: pl.DataFrame, groups: dict[str, str], liquid: set[str]) -> dict:
    """From our snapshots: per day t with a snapshot 7 days before and after,
    the rank IC of the 7-day average's change over the week before t with its
    change over the week after; mean and t per group. Needs MOMENTUM_DAYS."""
    if hist.is_empty():
        return {"ready": False, "days": 0, "rows": []}
    days = sorted(hist["date"].unique().to_list())
    span = (days[-1] - days[0]).days + 1
    if span < MOMENTUM_DAYS:
        return {"ready": False, "days": span, "waiting_days": MOMENTUM_DAYS - span, "rows": []}
    p = {d: dict(zip(f["name"].to_list(), f["usd_7d"].to_list())) for d, f in
         ((d, hist.filter(pl.col("date") == d)) for d in days)}
    have = set(days)
    ics: dict[str, list[float]] = {}
    for t in days:
        a, b = t - timedelta(days=7), t + timedelta(days=7)
        if a not in have or b not in have:
            continue
        per: dict[str, tuple[list, list]] = {}
        for n in liquid:
            v0, v1, v2 = p[a].get(n), p[t].get(n), p[b].get(n)
            if not v0 or not v1 or not v2:
                continue
            for g in ("all", groups.get(n, "other")):
                per.setdefault(g, ([], []))
                per[g][0].append(math.log(v1 / v0))
                per[g][1].append(math.log(v2 / v1))
        for g, (x, y) in per.items():
            ic = spearman(np.array(x), np.array(y))
            if ic is not None:
                ics.setdefault(g, []).append(ic)
    rows = []
    for g, v in sorted(ics.items(), key=lambda kv: (kv[0] != "all", kv[0])):
        m = float(np.mean(v))
        t = m / (np.std(v, ddof=1) / math.sqrt(len(v))) if len(v) > 2 and np.std(v, ddof=1) > 0 else None
        rows.append({"group": g, "days": len(v), "ic": m, "t": t, "lean": lean(m)})
    return {"ready": bool(rows), "days": span, "rows": rows}


def lean(ic: float | None) -> str:
    if ic is None:
        return "n/a"
    return "momentum" if ic >= 0.05 else "reversion" if ic <= -0.05 else "neither"


def spread_study(df: pl.DataFrame) -> dict:
    """Group medians of the routes, and the unusual items."""
    x = df.filter(pl.col("liquid") & pl.col("steam_premium").is_not_null())
    if x.is_empty():
        return {"items": 0, "rows": [], "unusual": []}
    rows, unusual = [], []
    for (g,), y in x.group_by("group"):
        prem = y["steam_premium"].to_numpy()
        med = float(np.median(prem))
        mad = float(np.median(np.abs(prem - med))) * 1.4826 or 1e-9
        rows.append({"group": g, "items": y.height, "steam_premium": med,
                     "to_steam": _median(y["to_steam"]), "to_skinport": _median(y["to_skinport"]),
                     "cash_route_positive": int((y["to_skinport"] > 0).sum())})
        for r in y.iter_rows(named=True):
            z = (r["steam_premium"] - med) / mad
            why = None
            if r["to_skinport"] is not None and r["to_skinport"] >= SPREAD_CASH:
                why = "cash"
            elif z >= SPREAD_Z and r["steam_premium"] >= 2 * med and (r["to_steam"] or 0) >= SPREAD_WALLET:
                why = "premium"
            if why:
                unusual.append({**_item(r), "why": why, "z": z, "group_median": med})
    # The cash route first (rare, and cash is worth more than wallet funds), then the largest premiums.
    unusual.sort(key=lambda u: (u["why"] != "cash", -(u["to_skinport"] if u["why"] == "cash" else u["z"])))
    return {"items": x.height, "rows": sorted(rows, key=lambda r: -r["items"]), "unusual": unusual,
            "median_premium": float(x["steam_premium"].median()),
            "median_to_steam": _median(x["to_steam"]), "median_to_skinport": _median(x["to_skinport"])}


def drops(hist: pl.DataFrame, df: pl.DataFrame, day: date, watch: dict | None = None) -> dict:
    """New cases and capsules, the known releases and events, and the cases
    around the latest drop."""
    watch = watch if watch is not None else load_watchlist(WATCHLIST)
    earlier = hist.filter(pl.col("date") < day) if not hist.is_empty() else hist
    first_day = hist["date"].min() if not hist.is_empty() else None
    new = []
    if not earlier.is_empty():
        seen = set(earlier["name"].unique().to_list())
        for r in df.filter(pl.col("group").is_in(["case", "capsule"]) & ~pl.col("name").is_in(list(seen))).iter_rows(named=True):
            new.append({**_item(r), "first_seen": day.isoformat()})
    events = []
    for c in watch.get("cases") or []:
        try:
            events.append({"date": date.fromisoformat(c["released"]), "kind": "release", "items": [c["name"]]})
        except (KeyError, ValueError):
            continue
    for o in watch.get("operations") or []:
        try:
            events.append({"date": date.fromisoformat(o["start"]), "kind": "operation start",
                           "items": [o.get("case") or o.get("name") or "operation"]})
        except (KeyError, ValueError, TypeError):
            continue
    for e in watch.get("events") or []:
        try:
            events.append({"date": date.fromisoformat(e["date"]), "kind": e.get("kind") or "event",
                           "items": list(e.get("items") or [])})
        except (KeyError, ValueError, TypeError):
            continue
    for n in new:
        events.append({"date": day, "kind": "first seen", "items": [n["name"]]})
    recent = sorted([e for e in events if 0 <= (day - e["date"]).days <= NEW_DROP_DAYS], key=lambda e: e["date"])
    cases = df.filter((pl.col("group") == "case") & pl.col("eur").is_not_null())
    around = None
    if recent:
        last = recent[-1]
        others = cases.filter(~pl.col("name").is_in(last["items"]))
        d0, before = _at(hist, last["date"], 1, 3)
        since = None
        if d0 is not None and first_day is not None and d0 >= first_day:
            b = dict(zip(before["name"].to_list(), before["usd_7d"].to_list()))
            ch = [v / b[n] - 1 for n, v in zip(others["name"].to_list(), others["usd_7d"].to_list())
                  if v and b.get(n)]
            since = float(np.median(ch)) if ch else None
        around = {"date": last["date"].isoformat(), "kind": last["kind"], "items": last["items"],
                  "days_ago": (day - last["date"]).days, "other_cases_since": since,
                  "other_cases_since_basis": f"7-day average against our snapshot of {d0.isoformat()}" if since is not None
                  else "no snapshot from before the drop yet",
                  "other_cases_30d": _median(others["chg_30d"]), "other_cases_7d": _median(others["chg_7d"])}
    rising = [_item(r) for r in cases.filter(pl.col("chg_7d") >= CASE_RISE_7D).sort("chg_7d", descending=True)
              .iter_rows(named=True)]
    return {"new": new, "recent": [{**e, "date": e["date"].isoformat()} for e in recent], "around_last": around,
            "rising_cases": rising, "cases": cases.height,
            "cases_median_7d": _median(cases["chg_7d"]), "cases_median_30d": _median(cases["chg_30d"])}


# ---------------------------------------------------------------- items and alerts

def _r(v, d: int = 4):
    v = market.finite(v)
    return None if v is None else round(v, d)


def _item(r: dict) -> dict:
    return {"name": r["name"], "group": r.get("group"), "eur": _r(r.get("eur"), 2), "usd": _r(r.get("price_usd"), 2),
            "chg_1d": _r(r.get("chg_1d")), "chg_7d": _r(r.get("chg_7d")), "chg_30d": _r(r.get("chg_30d")),
            "skinport_ask": _r(r.get("sp_ask"), 2), "skinport_ref": _r(r.get("sp_ref"), 2),
            "skinport_sales7": int(r["sp_sales7"]) if market.finite(r.get("sp_sales7")) is not None else None,
            "to_steam": _r(r.get("to_steam")), "to_skinport": _r(r.get("to_skinport")),
            "steam_premium": _r(r.get("steam_premium")),
            "steam_url": steam_url(r["name"]), "skinport_url": skinport_url(r["name"], r.get("item_page"))}


def movers(df: pl.DataFrame, basis: dict) -> tuple[list[dict], list[dict], str]:
    """(top gainers, top losers, basis): the liquid items' 1-day change from
    our snapshots, else the 24-hour average against the 7-day one."""
    snap = basis.get("chg_1d", "").startswith("snapshot")
    col = "chg_1d" if snap else "chg_7d"
    x = df.filter(pl.col("liquid") & pl.col(col).is_not_null())
    up = [_item(r) | {"move": r[col]} for r in x.sort(col, descending=True).head(TOP).iter_rows(named=True) if r[col] > 0]
    down = [_item(r) | {"move": r[col]} for r in x.sort(col).head(TOP).iter_rows(named=True) if r[col] < 0]
    return up, down, (basis.get("chg_1d") if snap else basis.get("chg_7d", ""))


def find_alerts(df: pl.DataFrame, basis: dict, dr: dict, sp: dict) -> list[dict]:
    snap = basis.get("chg_1d", "").startswith("snapshot")
    col, th = ("chg_1d", MOVE_SNAP) if snap else ("chg_7d", MOVE_WINDOW)
    out = []
    x = df.filter(pl.col("liquid") & (pl.col(col).abs() >= th)).sort(pl.col(col).abs(), descending=True)
    for r in x.head(TOP).iter_rows(named=True):
        out.append({"kind": "mover", **_item(r), "move": r[col], "basis_key": "snap" if snap else "window",
                    "basis": "since yesterday's snapshot" if snap else "24-hour average against the 7-day average"})
    for n in dr.get("new") or []:
        out.append({"kind": "new_drop", **n})
    for c in (dr.get("rising_cases") or [])[:TOP]:
        out.append({"kind": "case_rise", **c})
    un = sp.get("unusual") or []
    cash = [u for u in un if u["why"] == "cash"][:SPREAD_ALERTS]
    prem = [u for u in un if u["why"] != "cash"][:max(SPREAD_ALERTS - len(cash), 1)]
    for u in cash + prem:
        out.append({"kind": "spread", **u})
    return out


def fresh_alerts(found: list[dict], state: dict, today: str) -> tuple[list[dict], dict]:
    st = {k: v for k, v in (state or {}).items() if (date.fromisoformat(today) - date.fromisoformat(v)).days < 30}
    out = []
    for a in found:
        key = f"{a['kind']}:{a['name']}"
        last = st.get(key)
        if last and (date.fromisoformat(today) - date.fromisoformat(last)).days < COOLDOWN_DAYS:
            continue
        out.append(a)
        st[key] = today
    return out, st


def pct(v, dp: int = 1, lang: str = "en") -> str:
    return i18n.signed_pct(None if v is None else v * 100, dp, lang)


def eur(v, lang: str = "en") -> str:
    if v is None:
        return i18n.t("pk_na", lang)
    return f"{i18n.num(v, 2, 'de')} €" if lang == "de" else f"€{v:,.2f}"


# The emoji of each alert kind; the words are ct_kind_<kind> in lab.ops.i18n.
ALERT_WORDS = {"mover": "📈", "new_drop": "🆕", "case_rise": "📦", "spread": "↔️"}
# The English words in reports and the page (the cards say them in the messages' language).
ALERT_NAMES = {"mover": "Moved", "new_drop": "New case or capsule", "case_rise": "Case rising",
               "spread": "Unusual spread"}


def basis_words(b: str | None, lang: str = "en") -> str:
    """A change's basis as frame() names it, in `lang`."""
    b = str(b or "")
    if b.startswith("snapshot "):
        return i18n.t("ct_basis_snap", lang, day=i18n.iso_day(b.split(" ", 1)[1], lang))
    if "7-day average" in b:
        return i18n.t("ct_basis_w7", lang)
    if "30-day average" in b:
        return i18n.t("ct_basis_w30", lang)
    return i18n.t("ct_basis_none", lang)


def group_words(g: str | None, lang: str = "en") -> str:
    """skin, Field-Tested stays (wear names are the game's); the rest in `lang`."""
    g = str(g or "?")
    head, _, wear = g.partition(", ")
    key = "ct_group_" + head.replace(" ", "_")
    word = i18n.t(key, lang) if key in i18n.CATALOG["en"] else head
    return f"{word}, {wear}" if wear else word


def lean_words(lean: str | None, lang: str = "en") -> str:
    key = f"ct_lean_{lean}"
    return i18n.t(key, lang) if key in i18n.CATALOG["en"] else i18n.t("ct_lean_n/a", lang)


def kind_words(kind: str, lang: str = "en") -> str:
    key = "ct_event_" + str(kind).replace(" ", "_")
    return i18n.t(key, lang) if key in i18n.CATALOG["en"] else str(kind)


def item_lines(i: int, a: dict, lang: str = "en") -> list:
    t = i18n.t
    k = a["kind"]
    if k == "mover":
        head = t("ct_head_mover", lang, v=pct(a["move"], 1, lang),
                 basis=t("ct_since_yesterday", lang) if a.get("basis_key") == "snap" else t("ct_basis_w7", lang))
    elif k == "case_rise":
        head = t("ct_head_case", lang, v=pct(a["chg_7d"], 1, lang))
    elif k == "new_drop":
        head = t("ct_head_new", lang)
    elif a.get("why") == "cash":
        head = t("ct_head_cash", lang, v=pct(a["to_skinport"], 1, lang))
    else:
        head = t("ct_head_premium", lang, v=pct(a["steam_premium"], 0, lang), usual=pct(a.get("group_median"), 0, lang),
                 w=pct(a["to_steam"], 0, lang))
    sp = t("ct_sp_ask", lang, ask=eur(a.get("skinport_ask"), lang))
    if a.get("skinport_sales7"):
        sp += t("ct_sp_sales", lang, n=a["skinport_sales7"])
    group = group_words((a.get("group") or "?").split(",")[0], lang)
    return [notify.Line(f"({group}) {head}", f"{i}. {a['name']}"),
            notify.Line(t("ct_item_prices", lang, steam=eur(a.get("eur"), lang), sp=sp, c7=pct(a.get("chg_7d"), 1, lang),
                          c30=pct(a.get("chg_30d"), 1, lang))),
            notify.Links([(t("ct_link_steam", lang), a["steam_url"]), ("Skinport", a["skinport_url"])])]


def alert_card(alerts: list[dict], lang: str = "en") -> notify.Card:
    t = i18n.t
    kinds = sorted({a["kind"] for a in alerts}, key=list(ALERT_WORDS).index)
    title = " · ".join(t(f"ct_kind_{k}", lang) for k in kinds)
    parts: list = []
    for i, a in enumerate(alerts[:MAX_IN_CARD], 1):
        parts += item_lines(i, a, lang)
    if len(alerts) > MAX_IN_CARD:
        parts.append(notify.Line(t("ct_more", lang, n=len(alerts) - MAX_IN_CARD)))
    return notify.Card(ALERT_WORDS[kinds[0]] if len(kinds) == 1 else notify.CATEGORIES["cs2"][1],
                       t("ct_alert_title", lang, title=title), t("ct_alert_summary", lang, n=len(alerts)), parts,
                       t("ct_foot", lang))


def ic_words(v: float | None, lang: str = "en") -> str:
    return i18n.num(v, 3, lang, sign=True) if v is not None else i18n.t("pk_na", lang)


def summary_headline(s: dict, lang: str = "en") -> str:
    t = i18n.t
    up, down = s["movers"]["up"], s["movers"]["down"]
    return (t("ct_sum_items", lang, items=i18n.num(s["items"], 0, lang), liquid=i18n.num(s["liquid"], 0, lang))
            + (t("ct_sum_top", lang, name=up[0]["name"], v=pct(up[0]["move"], 1, lang)) if up else t("ct_sum_no_up", lang))
            + (t("ct_sum_drop", lang, name=down[0]["name"], v=pct(down[0]["move"], 1, lang)) if down else "")
            + t("ct_sum_days", lang, n=s["snapshots"]))


def summary_card(s: dict, lang: str = "en") -> notify.Card:
    t = i18n.t
    rows = []
    for g in s["groups"][:7]:
        rows.append([group_words(g["group"], lang), str(g["liquid"]), pct(g["median_7d"], 1, lang),
                     pct(g["median_30d"], 1, lang), pct(g["steam_premium"], 0, lang)])
    parts: list = [notify.Table([t("ct_col_group", lang), t("ct_col_items", lang), t("pk_d", lang, h=7),
                                 t("pk_d", lang, h=30), t("ct_col_premium", lang)], rows, t("ct_table_groups", lang))]
    up, down = s["movers"]["up"][:3], s["movers"]["down"][:3]
    if up or down:
        parts.append(notify.Table([t("ct_col_mover", lang), t("ct_col_move", lang), "EUR"],
                                  [[notify.short(m["name"], 28), pct(m["move"], 1, lang), eur(m["eur"], lang)]
                                   for m in up + down],
                                  t("ct_table_movers", lang, basis=basis_words(s["movers"]["basis"], lang))))
    mom = s["momentum"]
    snapm = mom["snapshots"]
    if snapm.get("ready"):
        a = next((r for r in snapm["rows"] if r["group"] == "all"), None)
        if a:
            parts.append(notify.Line(t("ct_mom_snap", lang, ic=ic_words(a["ic"], lang), n=a["days"],
                                       t=i18n.num(a["t"] or 0, 1, lang), lean=lean_words(a["lean"], lang)),
                                     t("ct_mom_snap_lead", lang)))
    a = next((r for r in mom["window"] if r["group"] == "all"), None)
    if a and a.get("ic") is not None:
        parts.append(notify.Line(t("ct_mom_win", lang, ic=ic_words(a["ic"], lang), n=a["items"],
                                   lean=lean_words(a["lean"], lang)), t("ct_mom_win_lead", lang)))
    d = s["drops"]
    if d.get("around_last"):
        al = d["around_last"]
        others = (t("ct_drop_since", lang, v=pct(al["other_cases_since"], 1, lang))
                  if al.get("other_cases_since") is not None else
                  t("ct_drop_window", lang, c7=pct(al.get("other_cases_7d"), 1, lang),
                    c30=pct(al.get("other_cases_30d"), 1, lang)))
        parts.append(notify.Line(t("ct_drop_line", lang, items=", ".join(al["items"][:2]), kind=kind_words(al["kind"], lang),
                                   day=i18n.iso_day(al["date"], lang), n=al["days_ago"], others=others),
                                 t("ct_drop_lead", lang)))
    if d.get("rising_cases"):
        parts.append(notify.Line(", ".join(f"{c['name']} {pct(c['chg_7d'], 1, lang)}" for c in d["rising_cases"][:3]),
                                 t("ct_rising_lead", lang)))
    spd = s["spread"]
    if spd.get("items"):
        parts.append(notify.Line(t("ct_spread_line", lang, p=pct(spd["median_premium"], 0, lang),
                                   w=pct(spd["median_to_steam"], 0, lang), c=pct(spd["median_to_skinport"], 0, lang)),
                                 t("ct_spread_lead", lang)))
    return notify.Card(notify.CATEGORIES["cs2"][1], t("ct_sum_title", lang, day=i18n.iso_day(s["date"], lang)),
                       summary_headline(s, lang), parts, t("ct_sum_foot", lang))


def chart_data(s: dict, lang: str = "en") -> dict:
    t = i18n.t
    g = [(group_words(r["group"], lang), (r["median_7d"] or 0) * 100) for r in s["groups"]
         if r["median_7d"] is not None and r["liquid"] >= 5]
    m = [(x["name"], x["move"] * 100) for x in s["movers"]["up"][:4] + s["movers"]["down"][:4]]
    sub = t("ct_chart_sub", lang, day=i18n.iso_day(s["date"], lang), basis=basis_words(s["basis"].get("chg_7d"), lang))
    if s["movers"]["basis"] != s["basis"].get("chg_7d"):
        sub += t("ct_chart_sub_movers", lang, basis=basis_words(s["movers"]["basis"], lang))
    return {"groups": g[:8], "movers": m, "groups_title": t("ct_chart_groups", lang),
            "movers_title": t("ct_chart_movers", lang), "empty_groups": t("ct_chart_no_groups", lang),
            "empty_movers": t("ct_chart_no_movers", lang), "subtitle": sub}


def make_chart(s: dict, base: Path, lang: str = "en") -> bytes | None:
    ch = notify._charts()
    if ch is None or not hasattr(ch, "render_trends"):
        return None
    path = base / "trends" / f"chart-{s['date']}.png"
    try:
        data = chart_data(s, lang)
        ch.render_trends(data, path, i18n.t("ct_chart_title", lang), data["subtitle"], lang=lang)
        return path.read_bytes()
    except Exception as e:  # noqa: BLE001 - a chart never stops the summary
        notify.say(f"chart not drawn: {type(e).__name__}: {e}", err=True)
        return None


# ---------------------------------------------------------------- the day

def summarize(hist: pl.DataFrame, skinport: pl.DataFrame, day: date | None = None, watch: dict | None = None) -> dict:
    df, basis = frame(hist, skinport, day)
    if df.is_empty():
        return {}
    day = day or hist["date"].max()
    groups = by_group(df)
    tiers = by_group(df.filter(pl.col("group").str.starts_with("skin")), "tier")
    up, down, mb = movers(df, basis)
    liquid = set(df.filter(pl.col("liquid"))["name"].to_list())
    gmap = dict(zip(df["name"].to_list(), df["group"].to_list()))
    mom = {"window": momentum_window(df), "snapshots": momentum_snapshots(hist, gmap, liquid)}
    sp = spread_study(df)
    dr = drops(hist, df, day, watch)
    found = find_alerts(df, basis, dr, sp)
    snaps = hist["date"].n_unique()
    head = (f"{df.height:,} items with a Steam price, {len(liquid):,} liquid; "
            + (f"top mover {up[0]['name']} {pct(up[0]['move'])}" if up else "no liquid item up")
            + (f", biggest drop {down[0]['name']} {pct(down[0]['move'])}" if down else "")
            + f". {snaps} day{'s' if snaps != 1 else ''} of Steam snapshots.")
    return {"date": day.isoformat(), "headline": head, "items": df.height, "liquid": len(liquid), "snapshots": snaps,
            "basis": basis, "groups": groups, "tiers": tiers, "movers": {"up": up, "down": down, "basis": mb},
            "momentum": mom, "spread": sp, "drops": dr, "alerts": found,
            "eurPerUsd": _r(df["eur_per_usd"].drop_nulls().head(1).item() if df["eur_per_usd"].drop_nulls().len() else None, 4),
            "source": SOURCE}


def markdown(s: dict) -> str:
    out = [f"# CS2 Steam market trends ({s['date']})", "",
           "Information only. Nothing is bought or sold; the owner trades by hand, if at all.", "",
           f"- {s['headline']}", f"- {s['source']}",
           f"- Changes: 1 day {s['basis'].get('chg_1d')}; 7 days {s['basis'].get('chg_7d')}; 30 days "
           f"{s['basis'].get('chg_30d')}.",
           f"- Liquid: {MIN_EUR:g} EUR or more on Steam and {MIN_SALES7} or more Skinport sales in 7 days "
           "(Steam publishes no volume in this feed).", "",
           "## By group (liquid items, medians)", "",
           report.table(s["groups"], ["group", "items", "liquid", "median_1d", "median_7d", "median_30d",
                                      "steam_premium", "skinport_sales7"]),
           "Skins by price tier (a stand-in for rarity, which no free feed here carries):", "",
           report.table(s["tiers"], ["group", "items", "liquid", "median_7d", "median_30d", "steam_premium"]),
           "## Momentum or mean reversion", "",
           "From the source's averages on the latest snapshot (30 days against 90, then 24 hours against 7 days; "
           "nested windows on one day, so a hint, not a test):", "",
           report.table(s["momentum"]["window"], ["group", "items", "ic", "lean"])]
    ms = s["momentum"]["snapshots"]
    if ms.get("ready"):
        out += ["From our snapshots (7-day average, one week against the next, per day):", "",
                report.table(ms["rows"], ["group", "days", "ic", "t", "lean"])]
    else:
        out += [f"From our snapshots: waiting for {ms.get('waiting_days', MOMENTUM_DAYS)} more days.", ""]
    sp = s["spread"]
    out += ["## Steam against Skinport, after fees", ""]
    if sp.get("items"):
        out += [f"{sp['items']} liquid items. Steam's 24-hour average is {pct(sp['median_premium'], 0)} over Skinport's "
                f"recent sale price (median). Buying on Skinport and selling on Steam nets {pct(sp['median_to_steam'], 0)} "
                f"in Steam wallet funds (which cannot be withdrawn); buying on Steam and selling on Skinport nets "
                f"{pct(sp['median_to_skinport'], 0)} in cash. The premium is mostly the price of wallet money.", "",
                report.table(sp["rows"], ["group", "items", "steam_premium", "to_steam", "to_skinport",
                                          "cash_route_positive"]),
                f"Unusual today: {len(sp['unusual'])}.", ""]
    else:
        out += ["No item with both a Steam and a Skinport price today.", ""]
    d = s["drops"]
    out += ["## Cases and drops", "",
            f"{d['cases']} cases priced; median 7 days {pct(d['cases_median_7d'])}, 30 days {pct(d['cases_median_30d'])}.",
            f"New cases or capsules today: {', '.join(n['name'] for n in d['new']) or 'none'}.",
            f"Cases up 15 % or more in 7 days: {', '.join(c['name'] for c in d['rising_cases']) or 'none'}."]
    if d.get("around_last"):
        al = d["around_last"]
        out.append(f"Last known drop: {', '.join(al['items'])} ({al['kind']}, {al['date']}). Other cases: "
                   + (f"{pct(al['other_cases_since'])} since ({al['other_cases_since_basis']})."
                      if al.get("other_cases_since") is not None else
                      f"7 days {pct(al.get('other_cases_7d'))}, 30 days {pct(al.get('other_cases_30d'))} "
                      f"({al['other_cases_since_basis']})."))
    else:
        out.append(f"No release or drop-pool event in the last {NEW_DROP_DAYS} days in the watchlist or the data.")
    out += ["", "## Alerts", "", f"{len(s['alerts'])} found today (before the 3-day cooldown)."]
    return notify.nodash("\n".join(out)) + "\n"


def board_summary(s: dict) -> dict:
    """What the CS2 page shows, small: written to cs2/trends/latest.json."""
    keep = lambda xs: [{k: x.get(k) for k in ("name", "group", "eur", "move", "chg_1d", "chg_7d", "chg_30d",  # noqa: E731
                                               "skinport_ask", "skinport_sales7", "to_steam", "to_skinport",
                                               "steam_premium", "steam_url", "skinport_url", "why", "kind")
                        if k in x} for x in xs]
    return {"date": s["date"], "headline": s["headline"], "items": s["items"], "liquid": s["liquid"],
            "snapshots": s["snapshots"], "basis": s["basis"], "source": s["source"],
            "groups": s["groups"], "movers": {"up": keep(s["movers"]["up"]), "down": keep(s["movers"]["down"]),
                                              "basis": s["movers"]["basis"]},
            "momentum": {"window": s["momentum"]["window"], "snapshots": s["momentum"]["snapshots"]},
            "spread": {k: s["spread"].get(k) for k in ("items", "median_premium", "median_to_steam", "median_to_skinport")}
            | {"unusual": keep(s["spread"].get("unusual") or [])[:10]},
            "cases": {"new": keep(s["drops"]["new"]), "rising": keep(s["drops"]["rising_cases"])[:10],
                      "median7d": s["drops"]["cases_median_7d"], "median30d": s["drops"]["cases_median_30d"],
                      "lastDrop": s["drops"]["around_last"]}}


def headline_value(a: dict) -> float | None:
    """The one number an alert is about."""
    if a["kind"] == "mover":
        return a.get("move")
    if a["kind"] == "case_rise":
        return a.get("chg_7d")
    if a["kind"] == "spread":
        return a.get("to_skinport") if a.get("why") == "cash" else a.get("steam_premium")
    return a.get("chg_7d")


def feed(s: dict) -> dict:
    items = [{"label": a["name"], "value": pct(headline_value(a)), "status": "watch",
              "detail": f"{ALERT_NAMES[a['kind']]}. Information only.", "link": a["steam_url"], "importance": 50}
             for a in s["alerts"][:8]]
    return report.feed_header("CS2 Steam market", "watch" if s["alerts"] else "ok", s["headline"], items)


def clean(v):
    if isinstance(v, float):
        return v if math.isfinite(v) else None
    if isinstance(v, dict):
        return {k: clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [clean(x) for x in v]
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    if isinstance(v, np.generic):
        return clean(v.item())
    return v


def run(root: Path | None = None, now_ms: int | None = None, dry_run: bool = False, send: bool = True,
        poster=None) -> dict:
    now_ms = now_ms or int(time.time() * 1000)
    base = market.cs2_root(root)
    hist = history(root)
    if hist.is_empty():
        print("no Steam market snapshot yet: run python -m lab.collect.cs2 --steam-market", file=sys.stderr)
        return {}
    s = summarize(hist, market.latest_daily(root, "skinport"))
    st_path = base / "trends" / "alerts_state.json"
    state = market.read_json(st_path) or {}
    fresh, new_state = fresh_alerts(s["alerts"], state.get("alerts") or {}, s["date"])
    live = send and not dry_run
    lang = notify.alert_lang()
    sent = []

    def said(res: dict) -> bool:
        """Posted, or nowhere to post to; not when held by quiet hours, not
        delivered, or not meant to be sent (a dry run, --no-alerts)."""
        return live and res["reason"] != "quiet" and not (res["reason"] is None and not res["delivered"])

    alerts_said = False
    if fresh:
        res = notify.send("cs2", [alert_card(fresh, lang)], now=now_ms, dry_run=not live, poster=poster)
        sent.append({"what": "alerts", "n": len(fresh), "delivered": res["delivered"], "reason": res["reason"]})
        alerts_said = said(res)
    if not alerts_said:
        new_state = state.get("alerts") or {}  # not said: the next run tries again
    if state.get("last_summary") != s["date"]:
        image = make_chart(s, base, lang) if live else None
        res = notify.send("cs2", [summary_card(s, lang)], image=image, now=now_ms, dry_run=not live,
                          poster=poster, hold_in_quiet=False)
        sent.append({"what": "summary", "delivered": res["delivered"], "reason": res["reason"]})
        if said(res):
            state["last_summary"] = s["date"]
    s["sent"] = sent
    if dry_run:
        print(markdown(s))
        return s
    state["alerts"] = new_state
    _write_json(st_path, state)
    if alerts_said:
        with (base / "trends" / "alerts.jsonl").open("a", encoding="utf-8") as fh:
            for a in fresh:
                fh.write(json.dumps(clean({"ts_ms": now_ms, **a})) + "\n")
    _write_json(base / "trends" / "latest.json", clean(board_summary(s)))
    md = markdown(s)
    data = clean({"date": s["date"], "verdict": s["headline"], "summary": board_summary(s), "sent": sent,
                  **feed(s)})
    if root is None:
        report.write("cs2_trends", md, data)
    else:
        d = root / "reports" / "cs2_trends"
        d.mkdir(parents=True, exist_ok=True)
        (d / "latest.md").write_text(md, encoding="utf-8")
        _write_json(d / "latest.json", data)
    return s


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(clean(data), indent=2, default=str, allow_nan=False), encoding="utf-8")
    tmp.replace(path)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    s = run(dry_run="--dry-run" in argv, send="--no-alerts" not in argv)
    if s and "--dry-run" not in argv:
        print(s["headline"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
