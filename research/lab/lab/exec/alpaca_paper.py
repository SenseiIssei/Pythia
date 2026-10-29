"""EQ3 (results/exec_alpaca_eq3_prereg.md): the equity books' orders on Alpaca's PAPER account, fills against the model.
PAPER ONLY: every request goes to paper-api.alpaca.markets (orders, clock, assets, positions) or data.alpaca.markets
(quotes); any other base URL is refused, there is no code path for the live one, no transfer, no account setting.

    python -m lab.exec.alpaca_paper            send today's orders, write reports/exec_alpaca/latest.md and .json
    python -m lab.exec.alpaca_paper --report   no order, no clock: re-check the open orders, write the report

Books: the paper books that trade US shares Alpaca carries (BOOKS; EQ2 has no book); their targets are the latest
`weights` row of <data>/paper/<book>/journal.csv, legs mapped by SYMBOLS (BTC is a coin and is dropped). Every book
has its own virtual wallet of WALLET_EUR in USD (EUR/USD from the dry run's Kraken cache, else EQ1's last ECB fixing)
in the module's ledger <data>/exec/alpaca_paper/state.json: cash, shares, the target last traded per leg, every
order. A leg whose target changed gets an order (sells first, shares at most what the book and the account hold;
buys notional USD at most the book's cash), market, day, regular hours; under MIN_NOTIONAL it is not sent. Sent
once: the client order id eq3-<book>-<day>-<symbol>-<side> is written to the ledger before the send, a known id is
never sent again, a send without an answer is looked up by its id. Per order: the quote at send, status, fill,
paper cost (bps against the mid at send), EQ2's model cost at that bar, acknowledgement and fill latency,
rejections and why. Per book: the ladder line, fills within LADDER_X x the model over at least LADDER_FILLS fills.
The keys come from APCA_API_KEY_ID / APCA_API_SECRET_KEY and are never logged, written or printed (scrub).
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .. import metrics, report
from ..data import ROOT, WRITE_ROOT
from ..experiments import daytrade_eq2 as eq2
from ..experiments import intraday_equities as ie
from . import dryrun

NAME = "exec_alpaca"
PREREG = "results/exec_alpaca_eq3_prereg.md"
PAPER = "https://paper-api.alpaca.markets"          # the only trading base URL this module knows
DATA = "https://data.alpaca.markets"
FEED = "iex"
EQ1_FX = Path(__file__).resolve().parents[2] / "results" / "etf_books_eq1_eurusd.csv"
WALLET_EUR = 50.0
MIN_NOTIONAL = eq2.MIN_NOTIONAL                      # Alpaca's fractional minimum, USD
LADDER_X, LADDER_FILLS = 1.5, 10
LADDER_LINE = f"fills within {LADDER_X:g}x the model's costs"
POLL_S, POLL_EVERY = 30.0, 1.0
OPEN_MIN = 9 * 60 + 30                               # 09:30 New York, the 5 minute bars of EQ2's cost model
BOOKS = {"small40_spy_trend": "S2", "small40_vol_target": "S2", "small40_spy_trend_wk": "S2",
         "small40_vol_target_wk": "S2"}
SYMBOLS = {"SPY": "SPY", "GOLD": "GLD"}             # GOLD is priced by GLD's closes in S2
OPEN = ("sending", "unknown", "new", "accepted", "pending_new", "accepted_for_bidding", "partially_filled",
        "pending_replace", "pending_cancel", "held", "calculated")
WHY = ("below 1 USD", "no quote", "not tradable", "not fractionable", "no position in the account")


class Refused(ValueError):
    """A request to anything but Alpaca's paper endpoint (or its data host for quotes)."""


def trials() -> list[dict]:
    return [{"id": f"small:eq3:exec_alpaca_{b}", "family": "small", "n": 1, "sharpe": None, "source": PREREG}
            for b in BOOKS]


# ---------------------------------------------------------------- the paper endpoint

def base_url(env=None) -> str:
    """PAPER, or Refused when APCA_API_BASE_URL names anything else."""
    env = os.environ if env is None else env
    b = (env.get("APCA_API_BASE_URL") or PAPER).strip().rstrip("/").removesuffix("/v2")
    if b != PAPER:
        raise Refused("lab.exec.alpaca_paper sends to Alpaca's paper endpoint only; APCA_API_BASE_URL names another")
    return PAPER


def keys(env=None) -> dict | None:
    env = os.environ if env is None else env
    k = (env.get("APCA_API_KEY_ID") or "").strip()
    s = (env.get("APCA_API_SECRET_KEY") or env.get("APCA_API_SECRET") or "").strip()
    return {"APCA-API-KEY-ID": k, "APCA-API-SECRET-KEY": s} if k and s else None


def scrub(text, secrets=()) -> str:
    out = str(text)
    for s in secrets:
        if s and len(s) >= 4:
            out = out.replace(s, "***")
    return out


def _http(method: str, url: str, headers: dict, body: dict | None = None, timeout: float = 15.0) -> tuple[int, dict]:
    """(HTTP status, JSON answer); an error status with its answer, OSError when nothing came back."""
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={**headers, "User-Agent": "pythia-lab", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        try:
            d = json.loads(e.read() or b"{}")
        except ValueError:
            d = {}
        return e.code, d if isinstance(d, dict) else {"message": str(d)}


class Client:
    """Alpaca's paper trading API: GETs and POST /v2/orders, nothing else. `send(method, url, headers, body)` is the
    transport (tests pass a fake server)."""

    def __init__(self, hdr: dict, base: str = PAPER, send=None):
        if base != PAPER:
            raise Refused("lab.exec.alpaca_paper sends to Alpaca's paper endpoint only")
        self._hdr, self._send = dict(hdr), send or _http
        self.secrets = tuple(hdr.values())

    def _req(self, method: str, url: str, body: dict | None = None) -> tuple[int, dict]:
        if not (url.startswith(PAPER + "/v2/") or url.startswith(DATA + "/v2/stocks/")):
            raise Refused("lab.exec.alpaca_paper sends to Alpaca's paper endpoint only")
        if method != "GET" and not (method == "POST" and url == PAPER + "/v2/orders"):
            raise Refused("lab.exec.alpaca_paper only reads and places orders")
        st, d = self._send(method, url, self._hdr, body)
        return st, d if isinstance(d, dict) else {"items": d}

    def get(self, path: str, base: str = PAPER) -> tuple[int, dict]:
        return self._req("GET", base + path)

    def clock(self) -> dict:
        st, d = self.get("/v2/clock")
        if st != 200:
            raise OSError(f"clock: HTTP {st}")
        return d

    def asset(self, sym: str) -> dict:
        st, d = self.get(f"/v2/assets/{sym}")
        return d if st == 200 else {}

    def position(self, sym: str) -> float:
        st, d = self.get(f"/v2/positions/{sym}")
        return float(d.get("qty") or 0) if st == 200 else 0.0

    def quote(self, sym: str) -> dict | None:
        st, d = self.get(f"/v2/stocks/{sym}/quotes/latest?feed={FEED}", base=DATA)
        q = d.get("quote") or {} if st == 200 else {}
        b, a = float(q.get("bp") or 0), float(q.get("ap") or 0)
        return {"bid": b, "ask": a, "mid": (a + b) / 2, "t": q.get("t")} if a > 0 and b > 0 and a >= b else None

    def submit(self, order: dict) -> tuple[int, dict]:
        return self._req("POST", PAPER + "/v2/orders", order)

    def order(self, oid: str) -> tuple[int, dict]:
        return self.get(f"/v2/orders/{oid}")

    def by_client_id(self, cid: str) -> tuple[int, dict]:
        return self.get(f"/v2/orders:by_client_order_id?client_order_id={cid}")


# ---------------------------------------------------------------- the ledger

def iso_s(t) -> float | None:
    """Seconds from Alpaca's RFC 3339 times (nanoseconds, Z or an offset)."""
    if not t:
        return None
    m = re.match(r"^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(\.\d+)?(Z|[+-]\d\d:\d\d)?$", str(t))
    if not m:
        return None
    s = m.group(1) + (m.group(2) or "")[:7] + ("+00:00" if m.group(3) in (None, "Z") else m.group(3))
    return datetime.fromisoformat(s).timestamp()


def session_bar(clock_ts) -> int:
    """The 5 minute bar of the New York session at Alpaca's clock time (its own offset), 0 from 09:30."""
    m = re.match(r"^\d{4}-\d\d-\d\dT(\d\d):(\d\d)", str(clock_ts or ""))
    return max((int(m.group(1)) * 60 + int(m.group(2)) - OPEN_MIN) // 5, 0) if m else 0


def model_bps(mid: float, bar: int) -> float:
    """EQ2's half spread and slippage a side at the mid and bar, bps."""
    return float(eq2.cost(np.array([mid]), np.array([bar]))[0]) * 1e4


def fees_bps(side: str, px: float) -> float:
    """The SEC fee and TAF a sell pays (model only; the paper account charges none), bps of the notional."""
    if side != "sell" or not px > 0:
        return 0.0
    return (ie.SEC_FEE + ie.TAF_PER_SHARE / px) * 1e4


def eurusd(root: Path) -> tuple[float, str]:
    v = dryrun._read(root / "exec" / "kraken_pairs.json") or {}
    try:
        x = dryrun.eurusd(dryrun.market(v.get("pairs") or {}), v.get("ticker") or {})
    except (KeyError, TypeError, ValueError):
        x = math.nan
    if x > 0:
        return float(x), f"Kraken EUR/USD mid of {v.get('fetched')}"
    rows = [r.split(",") for r in EQ1_FX.read_text(encoding="utf-8").splitlines()[1:] if r.strip()]
    return float(rows[-1][1]), f"ECB fixing of {rows[-1][0]}"


def legs(weights: dict) -> tuple[dict, list[str]]:
    """{symbol: target} of the legs Alpaca carries, and the dropped names (their weight stays cash)."""
    out, dropped = {}, []
    for k, w in weights.items():
        if k in SYMBOLS:
            out[SYMBOLS[k]] = out.get(SYMBOLS[k], 0.0) + max(float(w), 0.0)
        elif float(w) > 0:
            dropped.append(k)
    return out, sorted(dropped)


def load_state(path: Path) -> dict:
    s = dryrun._read(path) or {}
    return {"books": s.get("books") or {}, "orders": s.get("orders") or []}


def apply_fill(state: dict, o: dict) -> None:
    """Book the part of the order's fill not booked yet into its book's cash and shares."""
    q, px = float(o.get("filled_qty") or 0), float(o.get("fill_price") or 0)
    dq, dusd = q - float(o.get("booked_qty") or 0), q * px - float(o.get("booked_usd") or 0)
    if dq <= 0:
        return
    b = state["books"][o["book"]]
    sign = 1.0 if o["side"] == "buy" else -1.0
    b["held"][o["symbol"]] = max(float(b["held"].get(o["symbol"]) or 0) + sign * dq, 0.0)
    b["cash"] = float(b["cash"]) - sign * dusd
    o["booked_qty"], o["booked_usd"] = q, q * px


def take(o: dict, d: dict, sent_s: float | None = None) -> None:
    """Alpaca's answer about an order into the ledger row: status, fill, costs, latency, why."""
    o["id"] = d.get("id") or o.get("id")
    o["status"] = str(d.get("status") or o.get("status"))
    q, px = float(d.get("filled_qty") or 0), float(d.get("filled_avg_price") or 0)
    o["filled_qty"], o["fill_price"] = q, (px if q > 0 else None)
    if q > 0 and o.get("mid"):
        sgn = 1.0 if o["side"] == "buy" else -1.0
        o["paper_bps"] = sgn * (px / o["mid"] - 1) * 1e4
        o["filled_usd"] = q * px
    fa = iso_s(d.get("filled_at"))
    if fa is not None and o.get("sent_s"):
        o["fill_s"] = fa - o["sent_s"]
    if o["status"] == "rejected" and not o.get("why"):
        o["why"] = str(d.get("reject_reason") or d.get("message") or "rejected")


def refresh(cl: Client, state: dict, log=print) -> int:
    """Look at every order still open (or sent without an answer) again; book their fills. Returns how many."""
    n = 0
    for o in state["orders"]:
        if o.get("status") not in OPEN:
            continue
        try:
            st, d = cl.order(o["id"]) if o.get("id") else cl.by_client_id(o["cid"])
        except OSError as e:
            st, d = type(e).__name__, {}
        if st == 200 and d:
            take(o, d)
            apply_fill(state, o)
            if o["status"] == "filled":
                state["books"][o["book"]]["traded"][o["symbol"]] = o["target"]
            n += 1
        elif st == 404 and o["status"] in ("sending", "unknown"):
            o["status"], o["why"] = "not received", "Alpaca has no order with this client order id"
        else:
            log(f"exec_alpaca: {o['cid']} not readable now (HTTP {st}), next run")
    return n


# ---------------------------------------------------------------- today's orders

def plan(book: dict, targets: dict, quotes: dict) -> list[dict]:
    """The orders of one book: every leg whose target differs from the one last traded (first run: every target
    above 0) and that has no order open; sells first. USD = target x book value - held, at the mid."""
    held, traded, cash = book["held"], book["traded"], float(book["cash"])
    value = cash + sum(float(q) * (quotes.get(s) or {}).get("mid", 0.0) for s, q in held.items())
    out = []
    for s in sorted(set(targets) | {s for s, q in held.items() if float(q) > 0}):
        w = float(targets.get(s, 0.0))
        if s in book.get("open", ()) or (s in traded and abs(float(traded[s]) - w) < 1e-9) or \
                (s not in traded and w <= 0 and float(held.get(s) or 0) <= 0):
            continue
        q = quotes.get(s)
        if not q:
            out.append({"symbol": s, "target": w, "side": "buy", "usd": 0.0, "why": "no quote"})
            continue
        d = w * value - float(held.get(s) or 0) * q["mid"]
        if d < 0:
            qty = float(held.get(s) or 0) if w <= 0 else min(-d / q["mid"], float(held.get(s) or 0))
            out.append({"symbol": s, "target": w, "side": "sell", "qty": math.floor(qty * 1e9) / 1e9,
                        "usd": qty * q["mid"]})
        else:
            out.append({"symbol": s, "target": w, "side": "buy", "usd": d})
    return sorted(out, key=lambda o: o["side"] != "sell")


def place(cl: Client, state: dict, path: Path, book: str, o: dict, day: str, q: dict | None, bar: int,
          asset: dict, now=time.time, poll_s: float = POLL_S, sleep=time.sleep, log=print) -> dict:
    """One order: checked, written to the ledger before the send, sent once, polled until done or poll_s."""
    b = state["books"][book]
    cid = f"eq3-{book}-{day}-{o['symbol']}-{o['side']}"
    row = {"cid": cid, "book": book, "day": day, "symbol": o["symbol"], "side": o["side"], "target": o["target"],
           "status": "not sent", "why": o.get("why"), "bar": bar}
    if any(r["cid"] == cid for r in state["orders"]):
        return next(r for r in state["orders"] if r["cid"] == cid)
    if q:
        row.update(bid=q["bid"], ask=q["ask"], mid=q["mid"], quote_t=q.get("t"), model_bps=model_bps(q["mid"], bar))
    body = {"symbol": o["symbol"], "side": o["side"], "type": "market", "time_in_force": "day",
            "client_order_id": cid}
    if not row["why"]:
        if o["side"] == "buy":
            usd = math.floor(min(o["usd"], float(b["cash"])) * 100) / 100
            body["notional"] = f"{usd:.2f}"
            row["usd"] = usd
        else:
            qty = min(o["qty"], math.floor(max(cl.position(o["symbol"]), 0.0) * 1e9) / 1e9)
            body["qty"] = f"{qty:.9f}".rstrip("0").rstrip(".")
            row["qty"], row["usd"] = qty, qty * q["mid"]
            row["fees_bps"] = fees_bps("sell", q["mid"])
            if qty <= 0:
                row["why"] = "no position in the account"
        frac = o["side"] == "buy" or row["qty"] != int(row["qty"])
        row["why"] = (row["why"] or ("below 1 USD" if row["usd"] < MIN_NOTIONAL else None)
                      or (None if asset.get("tradable") else "not tradable")
                      or ("not fractionable" if frac and not asset.get("fractionable") else None))
    if row["why"]:
        if row["why"] == "below 1 USD":
            b["traded"][o["symbol"]] = o["target"]          # nothing worth an order: the leg is where it should be
        state["orders"].append(row)
        dryrun._write(path, state)
        return row
    row["status"], row["sent_s"] = "sending", now()
    row["sent"] = datetime.fromtimestamp(row["sent_s"], timezone.utc).isoformat(timespec="milliseconds")
    state["orders"].append(row)
    dryrun._write(path, state)                              # the id is known before the send: never sent twice
    t0 = time.monotonic()
    try:
        st, d = cl.submit(body)
    except OSError as e:
        row["ack_ms"] = (time.monotonic() - t0) * 1000
        log(f"exec_alpaca: {cid} sent without an answer ({scrub(type(e).__name__, cl.secrets)}), looked up by id")
        st, d = cl.by_client_id(cid)
        if st != 200:
            row["status"] = "unknown"
            dryrun._write(path, state)
            return row
    else:
        row["ack_ms"] = (time.monotonic() - t0) * 1000
    if st not in (200, 201):
        row["status"], row["why"] = "rejected", scrub(f"HTTP {st}: {d.get('message') or d}", cl.secrets)[:200]
        dryrun._write(path, state)
        return row
    take(row, d)
    t_end = time.monotonic() + poll_s
    while row["status"] in OPEN:                            # at least one look, then until poll_s
        sleep(POLL_EVERY)
        st, d = cl.order(row["id"])
        if st == 200:
            take(row, d)
        if time.monotonic() >= t_end:
            break
    apply_fill(state, row)
    if row["status"] == "filled":
        b["traded"][o["symbol"]] = o["target"]
    row["why"] = scrub(row.get("why"), cl.secrets) if row.get("why") else None
    dryrun._write(path, state)
    return row


def run(root: Path = ROOT, write_root: Path = WRITE_ROOT, cl: Client | None = None, send_orders: bool = True,
        now=time.time, poll_s: float = POLL_S, sleep=time.sleep, wallet: float = WALLET_EUR, register: bool = True,
        log=print) -> dict:
    if register:
        metrics.register(trials())                            # before any number exists
    path = write_root / "exec" / "alpaca_paper" / "state.json"
    state = load_state(path)
    day = datetime.fromtimestamp(now(), timezone.utc).strftime("%Y-%m-%d")
    res = {"date": day, "wallet": wallet, "base": PAPER, "feed": FEED, "error": None, "market": None, "sent": 0}
    if cl is None:
        base_url()
        hdr = keys()
        if not hdr:
            res["error"] = "APCA_API_KEY_ID / APCA_API_SECRET_KEY are not set: no order"
            return {**res, **summarise(state)}
        cl = Client(hdr)
    refresh(cl, state, log)
    dryrun._write(path, state)
    if send_orders:
        ck = cl.clock()
        res["market"] = "open" if ck.get("is_open") else "closed"
        if ck.get("is_open"):
            bar = session_bar(ck.get("timestamp"))
            fx, fx_src = eurusd(root)
            res["eurusd"], res["eurusd_source"] = fx, fx_src
            quotes, assets = {}, {}
            for bk in BOOKS:
                days = dryrun.journal_days(root / "paper" / bk / "journal.csv", window=1)
                if not days:
                    continue
                tg, dropped = legs(days[-1][1])
                b = state["books"].setdefault(bk, {"start": day, "eurusd": fx, "start_usd": wallet * fx,
                                                   "cash": wallet * fx, "held": {}, "traded": {}})
                b["journal"], b["dropped"], b["targets"] = days[-1][0], dropped, tg
                b["open"] = sorted({o["symbol"] for o in state["orders"] if o["book"] == bk and o["status"] in OPEN})
                for s in set(tg) | set(b["held"]):
                    if s not in quotes:
                        quotes[s] = cl.quote(s)
                for o in plan(b, tg, quotes):
                    if o["symbol"] not in assets:
                        assets[o["symbol"]] = cl.asset(o["symbol"])
                    place(cl, state, path, bk, o, day, quotes.get(o["symbol"]), bar, assets[o["symbol"]],
                          now=now, poll_s=poll_s, sleep=sleep, log=log)
                b.pop("open", None)
            dryrun._write(path, state)
    res["sent"] = sum(o["day"] == day and o["status"] != "not sent" for o in state["orders"])
    return {**res, **summarise(state)}


# ---------------------------------------------------------------- per book

def _w(rows: list[dict], k: str) -> float | None:
    u = sum(r["filled_usd"] for r in rows)
    return sum(r[k] * r["filled_usd"] for r in rows) / u if u > 0 else None


def judge(orders: list[dict]) -> dict:
    """Counts, notional weighted paper and model bps, their ratio, latencies and the ladder line of some orders."""
    f = [o for o in orders if o.get("filled_usd") and o.get("paper_bps") is not None and o.get("model_bps")]
    paper, model = _w(f, "paper_bps"), _w(f, "model_bps")
    ratio = paper / model if paper is not None and model else None
    ack = [o["ack_ms"] for o in orders if o.get("ack_ms") is not None]
    fill = [o["fill_s"] for o in orders if o.get("fill_s") is not None]
    ok = None if len(f) < LADDER_FILLS else bool(ratio is not None and ratio <= LADDER_X)
    return {"orders": len(orders), "sent": sum(o["status"] != "not sent" for o in orders), "filled": len(f),
            "rejected": sum(o["status"] == "rejected" for o in orders),
            "not_sent": sum(o["status"] == "not sent" for o in orders),
            "open": sum(o["status"] in OPEN for o in orders), "paper_bps": paper, "model_bps": model,
            "gap_bps": None if paper is None else paper - model, "ratio": ratio,
            "fees_bps": _w([o for o in f if o.get("fees_bps") is not None], "fees_bps"),
            "ack_ms_median": float(np.median(ack)) if ack else None,
            "fill_s_median": float(np.median(fill)) if fill else None,
            "ladder": {"line": LADDER_LINE, "ok": ok, "fills": len(f), "need": LADDER_FILLS, "x": LADDER_X,
                       "ratio": ratio}}


def summarise(state: dict) -> dict:
    books = {}
    for bk, study in BOOKS.items():
        b = state["books"].get(bk) or {}
        mine = [o for o in state["orders"] if o["book"] == bk]
        per_day = {d: judge([o for o in mine if o["day"] == d]) for d in sorted({o["day"] for o in mine})}
        books[bk] = {"study": study, "start": b.get("start"), "journal": b.get("journal"), "cash": b.get("cash"),
                     "start_usd": b.get("start_usd"), "held": b.get("held") or {}, "targets": b.get("targets") or {},
                     "dropped": b.get("dropped") or [], **judge(mine), "days": per_day,
                     "why": {w: sum(o.get("why") == w for o in mine) for w in WHY},
                     "rejections": [{"cid": o["cid"], "why": o.get("why")} for o in mine
                                    if o["status"] in ("rejected", "not received")]}
    return {"books": books, "orders": state["orders"][-40:]}


# ---------------------------------------------------------------- the report

def _b(x, d=1) -> str:
    return "-" if x is None else f"{x:+.{d}f}"


def _n(x, fmt: str) -> str:
    return "-" if x is None else format(x, fmt)


def _ok(x) -> str:
    return "open" if x is None else ("yes" if x else "no")


def markdown(res: dict) -> str:
    head = (f"Alpaca's paper account ({res['base']}, quotes {res['feed'].upper()}), no money; market "
            f"{res['market'] or 'not asked'}, {res['sent']} order(s) sent today.")
    if res.get("error"):
        head += f" **{res['error']}.**"
    md = [f"# EQ3: the equity books' orders on Alpaca's paper account ({res['date']})", "",
          f"Pre-registered in `{PREREG}`. {head} A virtual wallet of {res['wallet']:.0f} EUR in USD per book"
          + (f" (EUR/USD {res['eurusd']:.4f}, {res['eurusd_source']})." if res.get("eurusd") else "."), "",
          "Paper cost: side x (fill / mid at send - 1) in bps, notional weighted; model: EQ2's half spread (5 bps "
          "or a cent a side, doubled in the first 15 minutes) at the bar of the send. The SEC fee and TAF on sells "
          "are the model's only (the paper account charges none) and stay out of the ratio. Alpaca's paper account "
          "fills against the quote without impact: a ratio near 1 confirms the spread model, not real fills.", "",
          "## Per book", "",
          f"Ladder line: {LADDER_LINE} (ratio paper / model at most {LADDER_X:g} over at least {LADDER_FILLS} "
          "fills; fewer is open).", "",
          "| book | legs (target) | dropped | sent | filled | rejected | not sent | open | paper bps | model bps | "
          "gap | ratio | ack ms | fill s | ladder |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for bk, b in res["books"].items():
        tg = ", ".join(f"{s} {w * 100:.0f} %" for s, w in sorted(b["targets"].items())) or "-"
        lad = b["ladder"]
        md.append(f"| {bk} | {tg} | {', '.join(b['dropped']) or '-'} | {b['sent']} | {b['filled']} | "
                  f"{b['rejected']} | {b['not_sent']} | {b['open']} | {_b(b['paper_bps'])} | {_b(b['model_bps'])} | "
                  f"{_b(b['gap_bps'])} | {_n(b['ratio'], '.2f')} | {_n(b['ack_ms_median'], '.0f')} | "
                  f"{_n(b['fill_s_median'], '.1f')} | "
                  f"{_ok(lad['ok'])} ({lad['fills']}/{lad['need']}) |")
    md += ["", "## Per book and day", "", "| book | day | sent | filled | rejected | not sent | paper bps | model bps "
           "| gap |", "|---|---|---|---|---|---|---|---|---|"]
    for bk, b in res["books"].items():
        for d, j in b["days"].items():
            md.append(f"| {bk} | {d} | {j['sent']} | {j['filled']} | {j['rejected']} | {j['not_sent']} | "
                      f"{_b(j['paper_bps'])} | {_b(j['model_bps'])} | {_b(j['gap_bps'])} |")
    md += ["", "## The last orders", "", "| day | book | symbol | side | USD | bid / ask at send | status | fill | "
           "paper bps | model bps | ack ms | fill s | why |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for o in reversed(res["orders"]):
        qt = f"{o['bid']:.2f} / {o['ask']:.2f}" if o.get("bid") else "-"
        md.append(f"| {o['day']} | {o['book']} | {o['symbol']} | {o['side']} | {o.get('usd') or 0:.2f} | {qt} | "
                  f"{o['status']} | {_n(o.get('fill_price'), '.4f')} | "
                  f"{_b(o.get('paper_bps'))} | {_b(o.get('model_bps'))} | "
                  f"{_n(o.get('ack_ms'), '.0f')} | {_n(o.get('fill_s'), '.1f')} | {o.get('why') or '-'} |")
    return "\n".join(md) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="lab.exec.alpaca_paper", description=__doc__.split("\n")[0])
    ap.add_argument("--report", action="store_true", help="no order: re-check the open orders, write the report")
    a = ap.parse_args(sys.argv[1:] if argv is None else argv)
    try:
        res = run(root=ROOT, write_root=WRITE_ROOT, send_orders=not a.report)
    except Refused as e:
        print(f"exec_alpaca: refused: {e}", file=sys.stderr)
        return 2
    report.write(NAME, markdown(res), res)
    return 1 if res.get("error") else 0


if __name__ == "__main__":
    sys.exit(main())
