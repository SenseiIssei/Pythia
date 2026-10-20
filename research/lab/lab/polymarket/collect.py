"""Collect Polymarket's public data: resolved markets with history, and a daily snapshot.

  python -m lab.polymarket.collect --history     resolved markets and their price history
                                                (resumable; finished months are skipped,
                                                the last two and every future month redone)
  python -m lab.polymarket.collect --live        today's snapshot of every open market and
                                                the order books of the candidates

Resolved set. Every closed market with at least VOL_MIN dollars of volume is
listed per end month (Gamma keyset, 100 a page). Its universe count goes to
strata.json; price history is fetched for a deterministic sample per month,
category and kind (the first CAP of the stratum ordered by a hash of the
market id, so the sample does not depend on volume, price or outcome).
Markets that resolved 50-50 or not at all are counted and left out. Each
sampled market's YES token gets:
  daily   the whole life (prices-history interval=max, fidelity 1440)
  hourly  the last 14 days before it closed (fidelity 60)
  10 min  the whole life instead, when it lived under two days

Live snapshot. Every open market with at least LIVE_MIN_LIQ of liquidity
(all of Gamma's fields that matter: best bid
and ask, spread, last price, volume, 24 h volume, liquidity, end date, fee
schedule), and for the candidates (accepting orders, not an up-or-down
market, resolving within BOOK_HORIZON_DAYS, liquidity over BOOK_MIN_LIQ) both
order books, 15 levels a side.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import polars as pl

from . import api, markets as M, store

VOL_MIN = 1000.0
START_MONTH = "2020-06"
CAP = {"event": 300, "game": 150, "updown": 40}
SHORT_LIFE_MS = 2 * 86_400_000
HOURLY_DAYS = 14
BOOK_HORIZON_DAYS = 120
BOOK_MIN_LIQ = 2000.0
BOOK_MAX = 2000
LIVE_MIN_LIQ = 1000.0  # of about 270,000 open markets (2026-10-20) about 56,000 have this much
LEVELS = 15
DAY_MS = 86_400_000


def now_ms() -> int:
    return int(time.time() * 1000)


def _month_start(y: int, m: int) -> datetime:
    return datetime(y, m, 1, tzinfo=timezone.utc)


def month_windows(start: str = START_MONTH, now: datetime | None = None, ahead_months: int = 24):
    """(label, start_iso, end_iso) for every month from `start` to `ahead_months` past now.
    Future months only hold markets that closed before their end date."""
    now = now or datetime.now(timezone.utc)
    y, m = (int(x) for x in start.split("-"))
    end_y, end_m = now.year + (now.month - 1 + ahead_months) // 12, (now.month - 1 + ahead_months) % 12 + 1
    out = []
    while (y, m) <= (end_y, end_m):
        a = _month_start(y, m)
        ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
        b = _month_start(ny, nm)
        out.append((f"{y:04d}-{m:02d}", a.strftime("%Y-%m-%dT%H:%M:%SZ"), b.strftime("%Y-%m-%dT%H:%M:%SZ")))
        y, m = ny, nm
    return out


def hkey(market_id: str) -> str:
    return hashlib.sha1(f"pm-sample:{market_id}".encode()).hexdigest()


def sample(recs: list[dict], cap: dict | None = None) -> tuple[list[dict], dict]:
    """The deterministic sample of usable resolved markets, and counts per stratum
    {"cat|kind": {"all": n, "resolved": r, "taken": k}}."""
    cap = cap or CAP
    strata: dict[str, list[dict]] = {}
    counts: dict[str, dict] = {}
    for r in recs:
        key = f"{r['category']}|{r['kind']}"
        c = counts.setdefault(key, {"all": 0, "resolved": 0, "taken": 0})
        c["all"] += 1
        if r.get("outcome") not in (0.0, 1.0) or not r.get("yes_token"):
            continue
        c["resolved"] += 1
        strata.setdefault(key, []).append(r)
    taken = []
    for key, rs in strata.items():
        rs.sort(key=lambda r: hkey(r["id"]))
        k = cap.get(key.split("|")[1], 100)
        taken.extend(rs[:k])
        counts[key]["taken"] = min(k, len(rs))
    return taken, counts


def histories(client: api.Client, rec: dict) -> list[dict]:
    """The YES price history rows of one resolved market."""
    tok = rec["yes_token"]
    close = rec.get("closed_ms") or rec.get("end_ms")
    born = rec.get("created_ms") or rec.get("start_ms")
    rows = []
    if close and born and close - born < SHORT_LIFE_MS:
        pts = client.history(tok, 10, born // 1000 - 600, close // 1000 + 600)
        rows += [{"res": "m10", "t_s": t, "p": p} for t, p in pts]
    else:
        rows += [{"res": "d", "t_s": t, "p": p} for t, p in client.history(tok, 1440)]
        if close:
            a = max(close - HOURLY_DAYS * DAY_MS, born or 0) // 1000
            rows += [{"res": "h", "t_s": t, "p": p} for t, p in client.history(tok, 60, a, close // 1000 + 3600)]
    for r in rows:
        r["market_id"] = rec["id"]
    return rows


HIST_SCHEMA = {"market_id": pl.Utf8, "res": pl.Utf8, "t_s": pl.Int64, "p": pl.Float64}


def fetch_histories(client: api.Client, recs: list[dict], workers: int = 6,
                    log=print) -> tuple[pl.DataFrame, set[str]]:
    """The history rows of `recs`, and the ids whose fetch failed (an empty history,
    as for the AMM markets before the order book, is an answer, not a failure)."""
    rows: list[dict] = []
    failed: set[str] = set()

    def one(r):
        try:
            return histories(client, r)
        except api.ApiError:
            return None

    with ThreadPoolExecutor(max_workers=workers) as ex:
        for i, (r, out) in enumerate(zip(recs, ex.map(one, recs))):
            if out is None:
                failed.add(r["id"])
            else:
                rows.extend(out)
            if (i + 1) % 500 == 0:
                log(f"    {i + 1}/{len(recs)} histories, {len(rows)} points, {len(failed)} failed")
    if failed:
        log(f"    {len(failed)} histories failed (left for the next run)")
    df = pl.DataFrame(rows, schema=HIST_SCHEMA) if rows else pl.DataFrame(schema=HIST_SCHEMA)
    return df, failed


def _frame(recs: list[dict]) -> pl.DataFrame:
    return pl.DataFrame(recs, infer_schema_length=None)


def backfill(client: api.Client | None = None, start: str = START_MONTH, only: list[str] | None = None,
             workers: int = 6, log=print, now: datetime | None = None) -> dict:
    client = client or api.Client()
    now = now or datetime.now(timezone.utc)
    st = store.read_json(store.path("state.json"), {}) or {}
    done = set(st.get("months_done") or [])
    strata = store.read_json(store.path("resolved", "strata.json"), {}) or {}
    prev =(now.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    summary = {"months": 0, "markets": 0, "new_histories": 0}
    for label, a, b in month_windows(start, now):
        if only and label not in only:
            continue
        redo = label >= prev
        if label in done and not redo:
            continue
        t0 = time.time()
        recs = []
        for m in client.markets(True, end_date_min=a, end_date_max=b, volume_num_min=VOL_MIN):
            r = M.record(m, desc_chars=600)
            if r["closed_ms"] is not None and r["closed_ms"] > now.timestamp() * 1000 + DAY_MS:
                continue
            recs.append(r)
        taken, counts = sample(recs)
        strata[label] = counts
        mp = store.path("resolved", "markets", f"{label}.parquet")
        hp = store.path("resolved", "history", f"{label}.parquet")
        old_h = store.read_parquet(hp)
        have = set(old_h["market_id"].unique().to_list()) if old_h is not None and old_h.height else set()
        todo = [r for r in taken if r["id"] not in have]
        log(f"{label}: {len(recs)} closed markets over ${VOL_MIN:,.0f}, {len(taken)} sampled, {len(todo)} to fetch")
        new_h, failed = fetch_histories(client, todo, workers, log) if todo \
            else (pl.DataFrame(schema=HIST_SCHEMA), set())
        got = set(new_h["market_id"].unique().to_list()) if new_h.height else set()
        counts["_no_history"] = {"all": 0, "resolved": 0,
                                 "taken": len([r for r in todo if r["id"] not in got and r["id"] not in failed])}
        hist = pl.concat([x for x in (old_h, new_h) if x is not None and x.height], how="vertical") \
            if (old_h is not None and old_h.height) or new_h.height else new_h
        keep = [r for r in taken if r["id"] in have or r["id"] in got]
        if keep:
            store.write_parquet(_frame(keep), mp)
        if hist.height:
            store.write_parquet(hist, hp)
        missing = len(taken) - len(keep)
        if not redo and len(failed) <= max(5, 0.02 * len(taken)):
            done.add(label)
        st["months_done"] = sorted(done)
        st["updated_ms"] = now_ms()
        store.write_json(store.path("state.json"), st)
        store.write_json(store.path("resolved", "strata.json"), strata)
        summary["months"] += 1
        summary["markets"] += len(keep)
        summary["new_histories"] += len(got)
        log(f"{label}: kept {len(keep)} with history ({missing} without: {len(failed)} failed, the rest "
            f"have none), {time.time() - t0:.0f} s, "
            f"{client.calls} calls so far")
    return summary


def lookup(client: api.Client, ids: list[str]) -> dict[str, dict]:
    """The current record of the given markets, open or closed (100 ids a call)."""
    out = {}
    ids = sorted({str(i) for i in ids if i})
    for i in range(0, len(ids), 100):
        for m in client.markets("any", id=ids[i:i + 100]):
            r = M.record(m, desc_chars=0)
            out[r["id"]] = r
    return out


# ---------------------------------------------------------------- the daily snapshot

def _levels(side: list, best_first_desc: bool) -> tuple[list[float], list[float]]:
    lv = []
    for x in side or []:
        try:
            lv.append((float(x["price"]), float(x["size"])))
        except (KeyError, TypeError, ValueError):
            continue
    lv.sort(key=lambda z: -z[0] if best_first_desc else z[0])
    lv = lv[:LEVELS]
    return [p for p, _ in lv], [s for _, s in lv]


def book_rows(books: list[dict], token_side: dict[str, tuple[str, str]], ts: int) -> list[dict]:
    out = []
    for b in books:
        tok = str(b.get("asset_id") or "")
        if tok not in token_side:
            continue
        mid, side = token_side[tok]
        bp, bs = _levels(b.get("bids"), True)
        ap, as_ = _levels(b.get("asks"), False)
        out.append({"ts_ms": ts, "market_id": mid, "side": side, "token": tok,
                    "bid_px": bp, "bid_sz": bs, "ask_px": ap, "ask_sz": as_})
    return out


def is_candidate(r: dict, ts: int) -> bool:
    end = r.get("end_ms")
    return bool(r.get("accepting") is not False and r["kind"] != "updown" and end and ts < end
                <= ts + BOOK_HORIZON_DAYS * DAY_MS and (r.get("liquidity") or 0) >= BOOK_MIN_LIQ
                and r.get("yes_token") and r.get("no_token"))


def snapshot(client: api.Client | None = None, ts: int | None = None, write: bool = True, log=print) -> dict:
    """Every open market now, and both books of the candidates. Returns {"live", "books"} frames."""
    client = client or api.Client()
    ts = ts or now_ms()
    recs = []
    for m in client.markets(False, liquidity_num_min=LIVE_MIN_LIQ):
        r = M.record(m, desc_chars=0)
        r["ts_ms"] = ts
        recs.append((r, m))
    cands = [(r, m) for r, m in recs if is_candidate(r, ts)]
    cands.sort(key=lambda x: -(x[0].get("liquidity") or 0))
    cands = cands[:BOOK_MAX]
    cid = {r["id"] for r, _ in cands}
    rows = []
    for r, m in recs:
        if r["id"] in cid:
            r["description"] = M.record(m)["description"]
        r["candidate"] = r["id"] in cid
        rows.append(r)
    token_side = {}
    for r, _ in cands:
        token_side[r["yes_token"]] = (r["id"], "yes")
        token_side[r["no_token"]] = (r["id"], "no")
    try:
        books = book_rows(client.books(list(token_side)), token_side, ts)
    except api.ApiError as e:
        log(f"books failed: {e}")
        books = []
    live = _frame(rows) if rows else pl.DataFrame()
    bk = pl.DataFrame(books) if books else pl.DataFrame()
    log(f"snapshot: {len(rows)} open markets, {len(cands)} candidates, {len(books)} books, {client.calls} calls")
    if write:
        day = datetime.fromtimestamp(ts / 1000, timezone.utc).strftime("%Y-%m-%d")
        if live.height:
            store.write_parquet(live, store.path("live", f"{day}.parquet"))
        if bk.height:
            store.write_parquet(bk, store.path("books", f"{day}.parquet"))
        gone = store.prune(today=day)
        if gone:
            log(f"budget: deleted {', '.join(gone)}")
    return {"live": live, "books": bk, "ts_ms": ts}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--history", action="store_true")
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--start", default=START_MONTH)
    ap.add_argument("--months", nargs="*")
    ap.add_argument("--workers", type=int, default=6)
    a = ap.parse_args(argv)
    if not (a.history or a.live):
        ap.error("say --history, --live or both")
    if a.live:
        snapshot()
    if a.history:
        print(backfill(start=a.start, only=a.months, workers=a.workers))
    return 0


if __name__ == "__main__":
    sys.exit(main())
