"""The daily Polymarket run: snapshot, settle, forecast, step the PAPER books, score, report, card.

    python -m lab.polymarket.daily                 snapshot, settle, step the books, report, card
    python -m lab.polymarket.daily --forecast      the Claude forecaster in between (metered, engine)
    python -m lab.polymarket.daily --dry-run       everything computed, nothing written or posted
    python -m lab.polymarket.daily --no-collect    use today's snapshot already on disk

PAPER ONLY: no wallet, no key, no order. Two books of $10,000 play money each
(results/polymarket_prereg.md, P):

  pm_model    q from M-PM1 (gradient boosting plus isotonic, lab.polymarket.study's latest
              fit on every resolved state), margin 3 points
  pm_claude   q from the newest Claude forecast under 7 days old, margin 5 points

Each day every candidate market the rule may trade gets the model's q, which is
written to forecasts/model_ledger.jsonl with the market's mid at that time, so
the model is scored forward on live markets exactly like Claude.

Files: paper/<book>/state.json, trades.csv, closed.csv, daily.csv;
forecasts/resolved.json (outcomes of the markets ever forecast or held);
reports/polymarket/latest.{md,json} with the lab feed header.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from datetime import datetime, timezone

import numpy as np
import polars as pl

from . import api, book as B, collect, forecast as F, markets as M, panel as P, store

BOOKS = {"pm_model": 0.03, "pm_claude": 0.05}
BIG_EDGE = 0.10
MAX_ALERTS = 3
MIN_SCORED = 200
DAY_MS = 86_400_000


def day_str(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d")


# ---------------------------------------------------------------- the model

class Model:
    """The saved M-PM1: LightGBM booster, isotonic map, the feature list."""

    def __init__(self):
        import lightgbm as lgb
        d = store.path("model")
        self.meta = store.read_json(d / "meta.json")
        iso = store.read_json(d / "iso.json")
        if not self.meta or not iso or not (d / "gbm.txt").exists():
            raise FileNotFoundError("no fitted model: run python -m lab.polymarket.study")
        self.booster = lgb.Booster(model_file=str(d / "gbm.txt"))
        self.iso_x, self.iso_y = np.array(iso["x"]), np.array(iso["y"])

    def predict(self, rows: list[dict]) -> np.ndarray:
        if not rows:
            return np.array([])
        df = P.encode(pl.DataFrame(rows, infer_schema_length=None))
        raw = self.booster.predict(df.select(self.meta["features"]).to_numpy().astype(float))
        return np.clip(np.interp(raw, self.iso_x, self.iso_y), 0.001, 0.999)


def load_model(log=print) -> Model | None:
    try:
        return Model()
    except Exception as e:
        log(f"model: {e}")
        return None


# ---------------------------------------------------------------- books on disk

def side_levels(books: pl.DataFrame | None) -> dict[str, dict]:
    """market_id -> {"yes": {"bids": [(p, s)], "asks": [...]}, "no": {...}}."""
    out: dict[str, dict] = {}
    if books is None or not books.height:
        return out
    for r in books.iter_rows(named=True):
        out.setdefault(r["market_id"], {})[r["side"]] = {
            "bids": list(zip(r["bid_px"] or [], r["bid_sz"] or [])),
            "asks": list(zip(r["ask_px"] or [], r["ask_sz"] or [])),
        }
    return out


def yes_mid(lv: dict | None, rec: dict | None) -> float | None:
    """YES mid from the books (both sides combined), else Gamma's best bid and ask."""
    bid = ask = None
    if lv:
        y, n = lv.get("yes") or {}, lv.get("no") or {}
        bids = [p for p, s in y.get("bids", []) if s > 0] + [1 - p for p, s in n.get("asks", []) if s > 0]
        asks = [p for p, s in y.get("asks", []) if s > 0] + [1 - p for p, s in n.get("bids", []) if s > 0]
        bid, ask = (max(bids) if bids else None), (min(asks) if asks else None)
    if (bid is None or ask is None) and rec:
        bid, ask = rec.get("best_bid"), rec.get("best_ask")
    if bid is None or ask is None or ask < bid:
        return (rec or {}).get("last_price")
    return (bid + ask) / 2


# ---------------------------------------------------------------- the steps

def resolutions(client: api.Client, ids: set[str], log=print) -> dict[str, dict]:
    """Outcomes of the given markets, cached in forecasts/resolved.json once final."""
    path = store.path("forecasts", "resolved.json")
    known = store.read_json(path, {}) or {}
    todo = sorted(i for i in ids if i not in known)
    if todo:
        try:
            recs = collect.lookup(client, todo)
        except api.ApiError as e:
            log(f"resolutions: {e}")
            recs = {}
        for mid, r in recs.items():
            if r.get("closed") and r.get("outcome") is not None:
                known[mid] = {"outcome": r["outcome"], "closed_ms": r.get("closed_ms"), "category": r["category"]}
        store.write_json(path, known)
    return known


def eligible(live: pl.DataFrame, levels: dict[str, dict], ts: int) -> list[dict]:
    out = []
    for r in live.filter(pl.col("candidate")).iter_rows(named=True):
        if r["kind"] == "updown" or not r.get("end_ms") or not (ts < r["end_ms"] <= ts + B.MAX_DAYS * DAY_MS):
            continue
        lv = levels.get(r["id"])
        if not lv or "yes" not in lv or "no" not in lv:
            continue
        asks = [p for p, s in lv["yes"]["asks"] + lv["no"]["asks"] if s > 0]
        if not asks or not any(B.MIN_ASK <= a <= B.MAX_ASK for a in asks):
            continue
        out.append(r)
    return out


def model_q(model: Model, client: api.Client, cands: list[dict], levels: dict, ts: int, log=print) -> dict[str, float]:
    """M-PM1's q for each candidate, from its CLOB daily history and today's mid."""
    rows, ids = [], []
    for r in cands:
        mid = yes_mid(levels.get(r["id"]), r)
        if mid is None or not 0 < mid < 1:
            continue
        try:
            h = client.history(r["yes_token"], 1440)
        except api.ApiError:
            h = []
        t = np.array([x[0] for x in h], dtype=np.int64)
        p = np.array([x[1] for x in h], dtype=float)
        rows.append(P.live_features(r, t, p, ts // 1000, float(mid)))
        ids.append(r["id"])
    q = model.predict(rows)
    log(f"model: q for {len(ids)} markets")
    return dict(zip(ids, (float(x) for x in q)))


def step_book(bk: B.Book, cands: list[dict], qs: dict[str, float], levels: dict, ts: int) -> list[dict]:
    fills = []
    scored = []
    for r in cands:
        q = qs.get(r["id"])
        if q is None:
            continue
        mid = yes_mid(levels.get(r["id"]), r)
        scored.append((abs(q - (mid if mid is not None else q)), r, q))
    scored.sort(key=lambda x: -x[0])
    for _, r, q in scored:
        lv = levels[r["id"]]
        f = bk.consider(r, q, ts, lv["yes"]["asks"], lv["no"]["asks"])
        if f:
            f["book"] = bk.name
            f["day"] = day_str(ts)
            f["end_ms"] = r["end_ms"]
            fills.append(f)
    return fills


def forward_scores(rows: list[dict], known: dict, q_key: str) -> dict:
    """First forecast per market whose market resolved (0 or 1) after it was written,
    against the mid in the same row."""
    first: dict[str, dict] = {}
    for f in sorted(rows, key=lambda x: int(x["ts_ms"])):
        first.setdefault(str(f["market_id"]), f)
    pts = []
    for mid, f in first.items():
        k = known.get(mid)
        if not k or k["outcome"] not in (0.0, 1.0) or f.get("mid") is None:
            continue
        if k.get("closed_ms") and int(k["closed_ms"]) <= int(f["ts_ms"]):
            continue
        pts.append((float(f[q_key]), float(f["mid"]), float(k["outcome"]), f.get("event_id") or mid,
                    int(f["ts_ms"]), f.get("category") or k.get("category")))
    out = {"forecasts": len(first), "resolved": len(pts)}
    if not pts:
        return out
    q, m, y = (np.array([x[i] for x in pts]) for i in range(3))
    ev = np.array([x[3] for x in pts])
    from .study import event_boot
    eps = 0.001
    m = np.clip(m, eps, 1 - eps)
    q = np.clip(q, eps, 1 - eps)
    gain = (m - y) ** 2 - (q - y) ** 2
    d, lo, hi = event_boot(gain, np.ones(len(y)), ev, seed=5) if len(y) >= 5 else (float(gain.mean()), None, None)
    ll = lambda z: -(y * np.log(z) + (1 - y) * np.log(1 - z))  # noqa: E731
    days = (max(x[4] for x in pts) - min(x[4] for x in pts)) / DAY_MS
    out.update(brier_model=float(np.mean((q - y) ** 2)), brier_market=float(np.mean((m - y) ** 2)),
               logloss_model=float(ll(q).mean()), logloss_market=float(ll(m).mean()), brier_gain=d,
               gain_lo=lo, gain_hi=hi, span_days=days,
               passes=bool(len(y) >= MIN_SCORED and days >= 30 and lo is not None and lo > 0
                           and np.mean((q - y) ** 2) < np.mean((m - y) ** 2) and ll(q).mean() < ll(m).mean()),
               calibration=calibration(q, y), calibration_market=calibration(m, y))
    return out


def calibration(q: np.ndarray, y: np.ndarray) -> list[dict]:
    b = P.price_bucket(q)
    return [{"bucket": lab, "n": int((b == i).sum()), "mean_q": float(q[b == i].mean()),
             "rate": float(y[b == i].mean())} for i, lab in enumerate(P.PRICE_LABELS) if (b == i).sum()]


def ensemble(claude_rows: list[dict], known: dict) -> dict:
    """E: logit q = w logit(claude) + (1 - w) logit(mid), w fitted on the first half of the
    resolved first forecasts by time, judged on the second half."""
    sc = forward_scores(claude_rows, known, "p_yes")
    if sc.get("resolved", 0) < MIN_SCORED:
        return {"status": "waiting", "resolved": sc.get("resolved", 0), "needed": MIN_SCORED}
    first: dict[str, dict] = {}
    for f in sorted(claude_rows, key=lambda x: int(x["ts_ms"])):
        first.setdefault(str(f["market_id"]), f)
    pts = sorted([(int(f["ts_ms"]), float(f["p_yes"]), float(f["mid"]), float(known[m]["outcome"]),
                   f.get("event_id") or m) for m, f in first.items()
                  if m in known and known[m]["outcome"] in (0.0, 1.0) and f.get("mid") is not None
                  and not (known[m].get("closed_ms") and int(known[m]["closed_ms"]) <= int(f["ts_ms"]))])
    half = len(pts) // 2
    lg = lambda z: np.log(np.clip(z, 1e-3, 1 - 1e-3) / (1 - np.clip(z, 1e-3, 1 - 1e-3)))  # noqa: E731
    a = np.array(pts[:half], dtype=object)
    best_w, best = 0.0, math.inf
    for w in np.linspace(0, 1, 21):
        qq = 1 / (1 + np.exp(-(w * lg(a[:, 1].astype(float)) + (1 - w) * lg(a[:, 2].astype(float)))))
        s = float(np.mean((qq - a[:, 3].astype(float)) ** 2))
        if s < best:
            best_w, best = float(w), s
    rows = [{"market_id": f"{i}", "ts_ms": t, "mid": m,
             "q": float(1 / (1 + np.exp(-(best_w * lg(c) + (1 - best_w) * lg(m))))), "event_id": e}
            for i, (t, c, m, y, e) in enumerate(pts[half:])]
    kn = {f"{i}": {"outcome": y, "closed_ms": None} for i, (t, c, m, y, e) in enumerate(pts[half:])}
    s2 = forward_scores(rows, kn, "q")
    return {"status": "pass" if s2.get("passes") else "fail", "w": best_w, "test": s2}


# ---------------------------------------------------------------- the run

def run(dry_run: bool = False, do_forecast: bool = False, collect_now: bool = True, log=print) -> dict:
    client = api.Client()
    ts = int(time.time() * 1000)
    if collect_now:
        snap = collect.snapshot(client, ts, write=not dry_run, log=log)
        live, books = snap["live"], snap["books"]
    else:
        files = sorted(store.path("live").glob("*.parquet"))
        if not files:
            raise SystemExit("no snapshot on disk")
        live = pl.read_parquet(files[-1])
        books = store.read_parquet(store.path("books", files[-1].name))
        ts = int(live["ts_ms"].max())
    res: dict = {"ts_ms": ts, "day": day_str(ts), "open_markets": live.height,
                 "candidates": int(live["candidate"].sum()) if "candidate" in live.columns else 0}
    if do_forecast and not dry_run:
        try:
            res["forecast"] = F.run(live, books, ts=ts, log=log)
        except Exception as e:  # the books run even when the AI is down
            res["forecast"] = {"error": f"{type(e).__name__}: {e}"}
            log(f"forecast failed: {e}")
    levels = side_levels(books)
    recs = {r["id"]: r for r in live.iter_rows(named=True)}
    bks = {n: B.load(n, m) for n, m in BOOKS.items()}
    claude_rows = store.read_jsonl(F.ledger_path())
    model_rows = store.read_jsonl(store.path("forecasts", "model_ledger.jsonl"))
    ids = {str(f["market_id"]) for f in claude_rows + model_rows} | {k for b in bks.values() for k in b.positions}
    known = resolutions(client, ids, log=log) if not dry_run else (
        store.read_json(store.path("forecasts", "resolved.json"), {}) or {})
    # settle and mark
    settled = []
    for b in bks.values():
        for mid in list(b.positions):
            k = known.get(mid)
            if k and k.get("outcome") is not None:
                rec = b.settle(mid, float(k["outcome"]), ts)
                rec["book"] = b.name
                settled.append(rec)
            else:
                b.set_mark(mid, yes_mid(levels.get(mid), recs.get(mid)))
    # forecasts for today
    cands = eligible(live, levels, ts)
    model = load_model(log)
    q_model = model_q(model, client, cands, levels, ts, log) if model else {}
    newest = F.latest(claude_rows, ts, 7.0)
    q_claude = {m: float(f["p_yes"]) for m, f in newest.items()}
    fills = step_book(bks["pm_model"], cands, q_model, levels, ts) + \
        step_book(bks["pm_claude"], cands, q_claude, levels, ts)
    # the model's forward ledger
    mrows = []
    for r in cands:
        if r["id"] in q_model:
            mid = yes_mid(levels.get(r["id"]), r)
            mrows.append({"market_id": r["id"], "ts_ms": ts, "q": round(q_model[r["id"]], 5),
                          "mid": round(mid, 4) if mid is not None else None, "end_ms": r["end_ms"],
                          "category": r["category"], "event_id": r.get("event_id"),
                          "model_fitted_ms": (model.meta or {}).get("fitted_ms") if model else None})
    # daily rows
    daily = []
    for b in bks.values():
        cl = b.closed  # loaded from closed.csv, plus what settled today
        won = sum(1 for c in cl if str(c.get("won")) in ("True", "true", "1", "1.0"))
        daily.append({"day": day_str(ts), "book": b.name, "equity": round(b.equity(), 2), "cash": round(b.cash, 2),
                      "invested": round(b.invested(), 2), "open": len(b.positions),
                      "opened": sum(1 for f in fills if f["book"] == b.name),
                      "settled": sum(1 for s in settled if s["book"] == b.name),
                      "closed_total": len(cl), "won_total": won,
                      "realized": round(sum(float(c["pnl"]) for c in cl), 2)})
    res.update(settled=settled, fills=fills, daily=daily, model_ready=model is not None,
               q_model=len(q_model), q_claude=len(q_claude), eligible=len(cands))
    res["claude_score"] = forward_scores(claude_rows, known, "p_yes")
    res["model_score"] = forward_scores(model_rows + mrows, known, "q")
    res["ensemble"] = ensemble(claude_rows, known)
    res["ai_cost_usd"] = round(sum(float(f.get("cost_usd") or 0) for f in claude_rows), 4)
    res["claude_forecasts"] = len(claude_rows)
    if not dry_run:
        for b in bks.values():
            B.save(b)
            B.append_csv(B.book_dir(b.name) / "trades.csv", [f for f in fills if f["book"] == b.name])
            B.append_csv(B.book_dir(b.name) / "closed.csv", [s for s in settled if s["book"] == b.name])
        for row in daily:
            B.append_csv(B.book_dir(row["book"]) / "daily.csv", [row])
        store.append_jsonl(store.path("forecasts", "model_ledger.jsonl"), mrows)
    res["history"] = {b: B.read_csv(B.book_dir(b) / "daily.csv") for b in bks}
    res["open_positions"] = {n: [vars(p) for p in b.positions.values()] for n, b in bks.items()}
    return res


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--forecast", action="store_true")
    ap.add_argument("--no-collect", action="store_true")
    ap.add_argument("--no-post", action="store_true")
    a = ap.parse_args(argv)
    res = run(a.dry_run, a.forecast, not a.no_collect)
    from . import card
    card.report(res, write=not a.dry_run)
    if not a.no_post:
        card.post(res, dry_run=a.dry_run)
    print(json.dumps({k: res[k] for k in ("day", "eligible", "q_model", "q_claude", "daily")}, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
