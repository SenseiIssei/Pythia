"""Telegram (or webhook) alerts for Pokemon cards: strong moves and cheap cards.

Uses the lab's notifier (`lab.ops.notify`): PYTHIA_TELEGRAM_BOT_TOKEN and
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

A card is alerted at most once per kind every 7 days (<lake>/alerts.json).
At most 8 moves and 5 undervalued cards per message.
"""

from __future__ import annotations

import json
import math
import os
from datetime import date
from pathlib import Path

import polars as pl

from ..ops import i18n, notify

MOVE_MIN_USD, MOVE_1D, MOVE_7D = 20.0, 0.20, 0.35
CM_MOVE, CM_MIN_EUR = 0.30, 20.0
UV_MIN_USD, UV_MAX_USD, UV_GAP, UV_MIN_AGE = 10.0, 500.0, 1.0, 60
# The fair value is off by a factor of about 1.7 for a typical card (first real
# snapshot), and the largest gaps are mostly its failures (promos at 25x). Only
# a fair value of 2x to 3x the price makes a message; beyond is model error.
UV_GAP_MAX = 2.0
COOLDOWN_DAYS = 7
MAX_MOVES, MAX_UV = 8, 5


def strong_moves(snap: pl.DataFrame) -> list[dict]:
    out = []
    for r in snap.filter(pl.col("price") >= MOVE_MIN_USD).to_dicts():
        r1, r7 = r.get("ret_1d"), r.get("ret_7d")
        move, basis = None, None
        if r1 is not None and abs(math.expm1(r1)) >= MOVE_1D:
            move, key = math.expm1(r1), "last"
        elif r7 is not None and abs(math.expm1(r7)) >= MOVE_7D:
            move, key = math.expm1(r7), "7d"
        elif r1 is None and r7 is None and (r.get("cm_trend") or 0) >= CM_MIN_EUR:
            m = r.get("cm_mom_1_7")
            if m is not None and abs(m) >= CM_MOVE:
                move, key = m, "cm"
        if move is not None:
            out.append({"card_id": r["card_id"], "name": r["name"], "set": r.get("set_name"), "price": r["price"],
                        "move": move, "basis": i18n.t(f"pk_basis_{key}"), "basis_key": key})
    return sorted(out, key=lambda x: -abs(x["move"]))


def undervalued(snap: pl.DataFrame) -> list[dict]:
    s = snap.filter(pl.col("price").is_between(UV_MIN_USD, UV_MAX_USD)
                    & pl.col("fv_gap").is_between(math.log1p(UV_GAP), math.log1p(UV_GAP_MAX))
                    & (pl.col("set_age_days") >= UV_MIN_AGE) & (pl.col("pred_90d") > 0))
    return [{"card_id": r["card_id"], "name": r["name"], "set": r.get("set_name"), "price": r["price"],
             "fair": math.exp(r["fv_log"]), "gap": math.expm1(r["fv_gap"]), "pred_90d": r["pred_90d"]}
            for r in s.sort("fv_gap", descending=True).to_dicts()]


def _cool(state: dict, kind: str, cid: str, today: str) -> bool:
    last = (state.get(kind) or {}).get(cid)
    return last is None or (date.fromisoformat(today) - date.fromisoformat(last)).days >= COOLDOWN_DAYS


def message(moves: list[dict], uv: list[dict], today: str, validated: bool, prefix: str = "Pythia",
            lang: str = "en") -> str:
    """The message to the chat, in `lang` (en or de)."""
    t = i18n.t

    def basis(m: dict) -> str:
        return t(f"pk_basis_{m['basis_key']}", lang) if m.get("basis_key") else str(m.get("basis") or "")

    lines = [t("pk_head", lang, prefix=prefix, today=i18n.iso_day(today, lang))]
    if moves:
        lines.append(t("pk_moves", lang))
        lines += [t("pk_move_line", lang, name=m["name"], set=m["set"], move=i18n.signed_pct(m["move"] * 100, 0, lang),
                    basis=basis(m), price=i18n.money(m["price"], 2, lang)) for m in moves]
    if uv:
        lines.append(t("pk_cheap", lang, note="" if validated else t("pk_unvalidated", lang)))
        lines += [t("pk_uv_line", lang, name=u["name"], set=u["set"], price=i18n.money(u["price"], 2, lang),
                    fair=i18n.money(u["fair"], 2, lang), gap=i18n.signed_pct(u["gap"] * 100, 0, lang),
                    pred=i18n.signed_pct(u["pred_90d"] * 100, 0, lang)) for u in uv]
    lines.append(t("pk_foot", lang))
    return notify.clip("\n".join(lines), lang=lang)


def run(snap: pl.DataFrame, root: Path, today: str, validated: bool, dry_run: bool = False) -> dict:
    path = root / "alerts.json"
    try:
        state = json.loads(path.read_text())
    except (OSError, ValueError):
        state = {}
    moves = [m for m in strong_moves(snap) if _cool(state, "move", m["card_id"], today)][:MAX_MOVES]
    uv = [u for u in undervalued(snap) if _cool(state, "undervalued", u["card_id"], today)][:MAX_UV]
    out = {"moves": moves, "undervalued": uv, "sent": False, "text": None}
    if not moves and not uv:
        return out
    url, fmt, prefix = notify.config()
    text = message(moves, uv, today, validated, prefix, notify.alert_lang())
    out["text"] = text
    print(text)
    if dry_run:
        return out
    if url:
        ok, err = notify.post(url, fmt, text)
        out["sent"], out["error"] = ok, err
        if not ok:
            return out  # try again tomorrow
    for kind, rows in (("move", moves), ("undervalued", uv)):
        for r in rows:
            state.setdefault(kind, {})[r["card_id"]] = today
    tmp = path.with_name(path.name + ".tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(json.dumps(state), encoding="utf-8")
    os.replace(tmp, path)
    return out
