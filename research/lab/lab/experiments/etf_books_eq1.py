"""EQ1: long-term ETF books at 50 EUR, as a German retail investor can trade them (UCITS funds in EUR on Xetra).

Pre-registered in results/etf_books_eq1_prereg.md; results in results/etf_books_eq1.md and .json.

    python -m lab.experiments.etf_books_eq1 --snapshot   record the ECB's daily EUR/USD (the IWM twin of IUSN)
                                                         into results/etf_books_eq1_eurusd.csv
    PYTHIA_TRIALS_REGISTRY=<registry> python -m lab.experiments.etf_books_eq1 [--no-register]

Eight funds (FUNDS) from the lab's daily closes (<data>/etf/daily/<SYM>.csv, lab.collect.etf_daily, Yahoo's
adjusted closes), IUSN with IWM in EUR before its first close. Five books (BOOKS), each 50 EUR once or plus 50 EUR on
the first Xetra day of every month, at three brokers (BROKERS: Trade Republic, Scalable's free tier, Interactive
Brokers) with their stated fees, fractions or whole units, savings plans and the minimums below which an order is
not sent. A rule decides at close t, its orders fill at close t+1 (one close late). R6's windows: in sample
2011-06-01 to 2023-12-31, validation 2024-01-01 to 2026-06-30, every close after it dropped before anything is
computed (the lockbox is never read). Thirty trials of R5's registry (family small), registered with their in-sample
excess Sharpes before any validation number. Taxes left out. The same wallet code (Wallet, step) runs the paper books
in lab.paper.etf_books. Nothing here signs, sends or holds a key.
"""

from __future__ import annotations

import csv
import io
import json
import math
import sys
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from scipy import optimize

from .. import metrics
from . import director_common as dc
from . import etf_trend as et

NAME = "etf_books_eq1"
PREREG = "results/etf_books_eq1_prereg.md"
RESULTS = Path(__file__).resolve().parents[2] / "results"
EURUSD_CSV = RESULTS / f"{NAME}_eurusd.csv"
SUMMARY = RESULTS / f"{NAME}.json"
ECB_ZIP = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.zip"
FUNDS = {"world": "EUNL.DE", "sp500": "SXR8.DE", "europe": "EXSA.DE", "emerging": "EUNM.DE", "small": "IUSN.DE",
         "bonds": "EUNH.DE", "gold": "4GLD.DE", "cash": "XEON.DE"}
SYMBOLS = tuple(FUNDS.values())
TWIN = {"IUSN.DE": "IWM"}                    # the only short series: US small caps in EUR before IUSN's first close
SP500, WORLD, CASH = FUNDS["sp500"], FUNDS["world"], FUNDS["cash"]
HALF_SPREAD = {s: 0.0005 for s in (SP500, WORLD, FUNDS["bonds"], CASH)}
HALF_SPREAD_OTHER = 0.0010                   # EXSA, EUNM, IUSN, 4GLD (assumed)
IS_FROM, IS_TO, VAL_FROM, VAL_TO = "2011-06-01", "2023-12-31", "2024-01-01", "2026-06-30"
WINDOWS = {"is": (IS_FROM, IS_TO), "val": (VAL_FROM, VAL_TO)}
CAPITAL = TOPUP = 50.0
BAND = 0.10                                  # S1w's band: a fund trades when 10 points of equity off its target
MIN_ORDER_EUR = 10.0                         # the lab's minimum for a one-off buy or partial sell (fee 10 % or more)
FRACTION_MIN = PLAN_MIN = 1.0
SPIKE = 0.15
MOM_DAYS, MIN_HISTORY, TOP = 252, 253, 3
TREND_DAYS, VOL_DAYS, VOL_TARGET = 200, 63, 0.15
BOOKS = ("hold_sp500", "hold_world", "dual_mom", "trend_sp500", "voltarget_sp500")
BENCH = "hold_sp500"
HOLD = {"hold_sp500": SP500, "hold_world": WORLD}
WEEKLY = {"dual_mom"}
VARIANTS = ("once", "plus50")
JUDGED = "tr"                                # the ladder judges every book on its Trade Republic wallet
DSR_PASS, PBO_PASS, DD_SLACK = 0.95, 0.2, 0.05
MONTH_DAYS = 30.44


@dataclass(frozen=True)
class Broker:
    name: str
    label: str
    fee_fixed: float          # EUR an order
    fee_pct: float            # of the order
    fee_min: float            # EUR an order at least
    fractional: bool          # one-off orders by amount; else whole units
    plan: bool                # a free fractional savings plan

    def fee(self, eur: float) -> float:
        return max(self.fee_fixed, self.fee_pct * eur, self.fee_min)


BROKERS = {
    "tr": Broker("tr", "Trade Republic", 1.0, 0.0, 0.0, True, True),
    "scalable": Broker("scalable", "Scalable Capital (free broker)", 0.99, 0.0, 0.0, False, True),
    "ibkr": Broker("ibkr", "Interactive Brokers (IBKR Pro tiered)", 0.0, 0.0005, 1.25, False, False),
}


def half_spread(sym: str) -> float:
    return HALF_SPREAD.get(sym, HALF_SPREAD_OTHER)


# ---------------------------------------------------------------- the closes

@dataclass
class Closes:
    days: np.ndarray          # datetime64[D], SXR8's Xetra days
    names: list[str]
    close: np.ndarray         # (T, N) the last close on or before each day, NaN before the first
    fresh: np.ndarray         # (T, N) the fund has its own close that day (else it is not traded)
    count: np.ndarray         # (T, N) own closes up to and including the day
    dropped: dict = field(default_factory=dict)
    twin_until: str | None = None
    first: dict = field(default_factory=dict)       # each fund's first close (the twin's where spliced)

    @property
    def T(self) -> int:
        return len(self.days)

    def col(self, sym: str) -> int:
        return self.names.index(sym)


def drop_spikes(d: np.ndarray, c: np.ndarray) -> tuple[np.ndarray, np.ndarray, int]:
    """Without the bad prints: a close more than SPIKE from the one before and more than SPIKE back the next close."""
    c = np.asarray(c, dtype=float)
    bad = np.zeros(len(c), dtype=bool)
    if len(c) > 2:
        up, back = c[1:-1] / c[:-2] - 1, c[2:] / c[1:-1] - 1
        bad[1:-1] = (np.abs(up) > SPIKE) & (np.abs(back) > SPIKE) & (np.sign(up) != np.sign(back))
    return d[~bad], c[~bad], int(bad.sum())


def splice_twin(own: tuple[np.ndarray, np.ndarray], twin: tuple[np.ndarray, np.ndarray],
                fx: tuple[np.ndarray, np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    """The twin's USD closes in EUR (the ECB's last rate on or before each day) before the fund's first close,
    scaled so they join it."""
    d0 = own[0][0]
    td, tc = twin
    keep = td < d0
    if not keep.any():
        return own
    td, tc = td[keep], tc[keep]
    i = np.searchsorted(fx[0], td, side="right") - 1
    ok = i >= 0
    td, eur = td[ok], tc[ok] / fx[1][i[ok]]
    if not len(td):
        return own
    eur = eur * own[1][0] / eur[-1]
    return np.concatenate([td, own[0]]), np.concatenate([eur, own[1]])


def build(series: dict[str, tuple[np.ndarray, np.ndarray]], twins: dict[str, tuple[np.ndarray, np.ndarray]] | None = None,
          fx: tuple[np.ndarray, np.ndarray] | None = None, to: str | None = VAL_TO) -> Closes:
    """The funds on SXR8's days, cut at `to` (the lockbox) before anything else; the twins spliced in."""
    cut = np.datetime64(to) if to else None
    dropped, twin_until, clean = {}, None, {}
    for s, (d, c) in series.items():
        d, c = np.asarray(d, dtype="datetime64[D]"), np.asarray(c, dtype=float)
        if cut is not None:
            d, c = d[d <= cut], c[d <= cut]
        d, c, n = drop_spikes(d, c)
        dropped[s] = n
        if s in TWIN and twins and TWIN[s] in twins and fx is not None and len(d):
            td, tc = twins[TWIN[s]]
            td, tc = np.asarray(td, dtype="datetime64[D]"), np.asarray(tc, dtype=float)
            td, tc, _ = drop_spikes(td[td <= d[0]], tc[td <= d[0]])
            d2, c2 = splice_twin((d, c), (td, tc), fx)
            if len(d2) > len(d):
                twin_until = str(d[0])
            d, c = d2, c2
        clean[s] = (d, c)
    days = clean[SP500][0]
    names = list(clean)
    T, N = len(days), len(names)
    close, fresh = np.full((T, N), np.nan), np.zeros((T, N), dtype=bool)
    for j, s in enumerate(names):
        d, c = clean[s]
        if not len(d):
            continue
        i = np.searchsorted(d, days, side="right") - 1
        ok = i >= 0
        close[ok, j] = c[i[ok]]
        fresh[:, j] = ok & (d[np.clip(i, 0, None)] == days)
    first = {s: str(d[0]) for s, (d, _) in clean.items() if len(d)}
    return Closes(days, names, close, fresh, np.cumsum(fresh, axis=0), dropped, twin_until, first)


def read_series(sym: str, cache: Path | None = None) -> tuple[np.ndarray, np.ndarray]:
    f = (cache or et.CACHE) / f"{sym}.csv"
    return et.parse_stooq(f.read_text(encoding="utf-8"))


def read_fx(path: Path = EURUSD_CSV) -> tuple[np.ndarray, np.ndarray]:
    with path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return np.array([r["date"] for r in rows], dtype="datetime64[D]"), np.array([float(r["eurusd"]) for r in rows])


def load(cache: Path | None = None, to: str | None = VAL_TO, fx_path: Path = EURUSD_CSV) -> Closes:
    series = {s: read_series(s, cache) for s in SYMBOLS}
    twins = {t: read_series(t, cache) for t in TWIN.values()}
    return build(series, twins, read_fx(fx_path), to)


# ---------------------------------------------------------------- the rules: targets at close t

def _month(d) -> int:
    return int(np.datetime64(d, "M").astype(int))


def _week(d) -> int:
    return int((np.datetime64(d, "D").astype(int) + 3) // 7)     # Monday-based weeks (1970-01-01 a Thursday)


def decides(book: str, days: np.ndarray, t: int) -> bool:
    """Is close t a decision close: the last Xetra day of its week (dual_mom) or month (the rest). Read at t+1
    (the next day's date says whether t was the last), so no calendar ahead of the fill day is needed."""
    if t + 1 >= len(days):
        return False
    f = _week if book in WEEKLY else _month
    return f(days[t]) != f(days[t + 1])


def targets(book: str, C: Closes, t: int) -> dict[str, float]:
    """The book's weights from the closes up to t (the rest cash)."""
    if book in HOLD:
        return {HOLD[book]: 1.0}
    j = C.col(SP500)
    px = C.close[: t + 1, j]
    if book == "trend_sp500":
        if t + 1 < TREND_DAYS:
            return {CASH: 1.0}
        return {SP500: 1.0} if px[-1] > np.mean(px[-TREND_DAYS:]) else {CASH: 1.0}
    if book == "voltarget_sp500":
        r = px[1:] / px[:-1] - 1
        r = r[np.isfinite(r)][-VOL_DAYS:]
        if len(r) < VOL_DAYS:
            return {CASH: 1.0}
        vol = float(np.std(r, ddof=1) * math.sqrt(252))
        w = min(1.0, VOL_TARGET / vol) if vol > 0 else 1.0
        return {SP500: w, CASH: 1.0 - w} if w < 1.0 else {SP500: 1.0}
    if book == "dual_mom":
        if t < MOM_DAYS:
            return {}
        ret = C.close[t] / C.close[t - MOM_DAYS] - 1
        ok = (C.count[t] >= MIN_HISTORY) & np.isfinite(ret) & (ret > 0)
        pick = [C.names[j] for j in np.argsort(-np.where(ok, ret, -np.inf), kind="stable")[:TOP] if ok[j]]
        return {s: 1.0 / TOP for s in pick}
    raise ValueError(book)


# ---------------------------------------------------------------- the wallet

def new_wallet(start: str, capital: float = CAPITAL) -> dict:
    """A wallet in EUR as JSON: cash, fund units, the targets of its last decision (None before the first)."""
    return {"start": start, "cash": capital, "units": {}, "tgt": None, "paid": capital, "fees": 0.0, "spread": 0.0,
            "sent": 0, "not_sent": 0, "plan_eur": 0.0, "topups": 0, "equity": capital, "day": start}


def value(w: dict, px: dict[str, float]) -> float:
    return w["cash"] + sum(u * px[s] for s, u in w["units"].items())


def plan(w: dict, amount: float, tgt: dict[str, float], px: dict, fresh: dict) -> int:
    """A savings plan: `amount` of the cash into the targets, free, in fractions, each line at least PLAN_MIN, at
    the half spread; a smaller line or a fund without a close today stays cash. Returns the lines executed."""
    n = 0
    for s, x in sorted(tgt.items()):
        line = min(amount * x, w["cash"])
        if x <= 0 or line < PLAN_MIN or not fresh.get(s):
            continue
        hs = half_spread(s)
        w["cash"] -= line
        w["units"][s] = w["units"].get(s, 0.0) + line / (px[s] * (1 + hs))
        w["spread"] += line * hs / (1 + hs)
        w["plan_eur"] += line
        n += 1
    return n


def _sell(w: dict, s: str, units: float, px: float, b: Broker) -> None:
    hs = half_spread(s)
    eur = units * px * (1 - hs)
    fee = b.fee(eur)
    w["cash"] += eur - fee
    left = w["units"][s] - units
    if left <= 1e-12:
        del w["units"][s]
    else:
        w["units"][s] = left
    w["fees"] += fee
    w["spread"] += units * px * hs
    w["sent"] += 1


def orders(w: dict, tgt: dict[str, float], px: dict, fresh: dict, b: Broker) -> list[dict]:
    """The order rule at a fill close: exits, partial sells, then buys (entries and gaps of BAND or more) from the
    cash there is. An order under the broker's minimum (one unit where it trades whole units, FRACTION_MIN at a
    fractional one) or under MIN_ORDER_EUR (not an exit) is not sent. Returns the fills."""
    E = value(w, px)
    fills = []
    held = set(w["units"])
    for s in sorted(held | set(tgt)):
        if not fresh.get(s) or s not in px or not np.isfinite(px[s]):
            continue
        x, u = tgt.get(s, 0.0), w["units"].get(s, 0.0)
        gap = x * E - u * px[s]
        if x <= 0 and u > 0:                                    # an exit: the whole position, always sent
            _sell(w, s, u, px[s], b)
            fills.append({"side": "sell", "fund": s, "units": u, "eur": u * px[s]})
        elif u > 0 and -gap >= BAND * E:
            units = -gap / px[s] if b.fractional else math.floor(-gap / px[s])
            if units * px[s] < max(MIN_ORDER_EUR, FRACTION_MIN) or units <= 0:
                w["not_sent"] += 1
                continue
            _sell(w, s, min(units, u), px[s], b)
            fills.append({"side": "sell", "fund": s, "units": min(units, u), "eur": min(units, u) * px[s]})
    want = {}
    for s, x in tgt.items():
        if x <= 0 or not fresh.get(s) or s not in px or not np.isfinite(px[s]):
            continue
        u = w["units"].get(s, 0.0)
        gap = x * E - u * px[s]
        if (u <= 0 and gap > 0) or gap >= BAND * E:
            want[s] = gap
    if want:
        need = sum(want.values()) + sum(b.fee(g) for g in want.values())
        scale = min(1.0, max(0.0, w["cash"] - sum(b.fee(g) for g in want.values())) / sum(want.values())) \
            if need > w["cash"] else 1.0
        for s, g in sorted(want.items(), key=lambda kv: -kv[1]):
            hs = half_spread(s)
            p = px[s] * (1 + hs)
            amt = g * scale
            if b.fractional:
                eur = min(amt, w["cash"] - b.fee(amt))
            else:
                n = math.floor(amt / p)
                while n > 0 and n * p + b.fee(n * p) > w["cash"]:
                    n -= 1
                eur = n * p
            if eur < max(MIN_ORDER_EUR, FRACTION_MIN) or eur <= 0:
                w["not_sent"] += 1
                continue
            fee = b.fee(eur)
            w["cash"] -= eur + fee
            w["units"][s] = w["units"].get(s, 0.0) + eur / p
            w["fees"] += fee
            w["spread"] += eur * hs / (1 + hs)
            w["sent"] += 1
            fills.append({"side": "buy", "fund": s, "units": eur / p, "eur": eur})
    return fills


def step(w: dict, book: str, variant: str, b: Broker, C: Closes, s: int) -> dict:
    """One fill close s >= 1 of one wallet, in this order: the decision of close s-1 (if it was one, or the wallet
    has never decided), the top-up on the first Xetra day of a month (plus50), a savings plan where the broker has
    one (the top-up; a hold book's first money), the order rule on the new targets. Returns the day's row (the
    wallet is changed in place)."""
    days = C.days
    px = {n: float(C.close[s, j]) for j, n in enumerate(C.names) if np.isfinite(C.close[s, j])}
    fresh = {n: bool(C.fresh[s, j]) for j, n in enumerate(C.names)}
    first = w["tgt"] is None
    dec = first or decides(book, days, s - 1)
    tgt = targets(book, C, s - 1) if dec else w["tgt"]
    flow = 0.0
    lines = 0
    if variant == "plus50" and not first and _month(days[s]) != _month(days[s - 1]):
        w["cash"] += TOPUP
        w["paid"] += TOPUP
        w["topups"] += 1
        flow = TOPUP
        if b.plan:
            lines += plan(w, TOPUP, tgt, px, fresh)
    if first and b.plan and book in HOLD:
        lines += plan(w, w["cash"], tgt, px, fresh)
    fills = orders(w, tgt, px, fresh, b) if dec else []
    w["tgt"] = tgt
    w["equity"] = value(w, px)
    w["day"] = str(days[s])
    return {"date": str(days[s]), "equity": w["equity"], "flow": flow, "decided": dec, "plan_lines": lines,
            "fills": fills, "targets": tgt}


def simulate(C: Closes, book: str, variant: str, b: Broker, i0: int, i1: int) -> dict:
    """A fresh 50 EUR wallet from close i0 (day 0, cash) to close i1: equity, the day's top-up and the wallet."""
    w = new_wallet(str(C.days[i0]))
    eq, flows = [CAPITAL], [0.0]
    for s in range(i0 + 1, i1 + 1):
        r = step(w, book, variant, b, C, s)
        eq.append(r["equity"])
        flows.append(r["flow"])
    return {"days": C.days[i0:i1 + 1], "equity": np.array(eq), "flows": np.array(flows), "wallet": w}


# ---------------------------------------------------------------- the measures

def twr(eq: np.ndarray, flows: np.ndarray) -> np.ndarray:
    """Daily time-weighted returns (the top-up taken out), 0 on day 0."""
    r = np.zeros(len(eq))
    r[1:] = (eq[1:] - flows[1:]) / eq[:-1] - 1
    return r


def calendar(days: np.ndarray, r: np.ndarray) -> np.ndarray:
    """Returns on every calendar day from the first to the last, 0 on days without a session (the registry's
    convention for daily books)."""
    off = (days - days[0]).astype(int)
    out = np.zeros(int(off[-1]) + 1)
    out[off] = r
    return out[1:]


def under_water_months(days: np.ndarray, idx: np.ndarray) -> tuple[float, float]:
    """(the longest spell under water, the one still open at the end), in months: from the last day at a peak to the
    first day back at it (or the window's end)."""
    peak, at, longest = idx[0], days[0], 0
    for d, x in zip(days, idx):
        if x >= peak:
            longest = max(longest, int((d - at).astype(int)))
            peak, at = x, d
    now = int((days[-1] - at).astype(int)) if idx[-1] < peak else 0
    return max(longest, now) / MONTH_DAYS, now / MONTH_DAYS


def irr(days: np.ndarray, eq: np.ndarray, flows: np.ndarray) -> float:
    """The money-weighted return a year: what was paid in (day 0 and the top-ups) against the end value."""
    y = (days - days[0]).astype(int) / 365.25
    cf = -flows.copy()
    cf[0] = -eq[0]
    cf[-1] += eq[-1]

    def npv(r):
        return float(np.sum(cf / (1 + r) ** y))
    try:
        return float(optimize.brentq(npv, -0.99, 10.0))
    except ValueError:
        return float("nan")


def measure(run: dict) -> dict:
    d, eq, fl = run["days"], run["equity"], run["flows"]
    r = twr(eq, fl)
    idx = np.cumprod(1 + r)
    yrs = max(1e-9, int((d[-1] - d[0]).astype(int)) / 365.25)
    x = calendar(d, r)
    uw, uw_now = under_water_months(d, idx)
    w = run["wallet"]
    return {"cagr": float(idx[-1] ** (1 / yrs) - 1), "max_dd": float(1 - np.min(idx / np.maximum.accumulate(idx))),
            "under_water_months": uw, "under_water_now": uw_now,
            "sharpe": float(x.mean() / x.std() * math.sqrt(365)) if x.std() > 0 else 0.0,
            "end": float(eq[-1]), "paid": float(w["paid"]), "mwr": irr(d, eq, fl) if fl.sum() > 0 else
            float(idx[-1] ** (1 / yrs) - 1), "sent": w["sent"], "not_sent": w["not_sent"], "fees": w["fees"],
            "spread": w["spread"], "plan_eur": w["plan_eur"], "from": str(d[0]), "to": str(d[-1])}


def months_beat(days: np.ndarray, r: np.ndarray, rb: np.ndarray) -> float:
    m = np.array([_month(x) for x in days])
    ends = np.r_[np.flatnonzero(m[1:] != m[:-1]), len(m) - 1]
    a, b = np.cumprod(1 + r)[ends], np.cumprod(1 + rb)[ends]
    ra, rb_ = a[1:] / a[:-1] - 1, b[1:] / b[:-1] - 1
    return float(np.mean(ra > rb_)) if len(ra) else float("nan")


# ---------------------------------------------------------------- the study

def configs() -> list[tuple[str, str, str]]:
    return [(bk, v, br) for bk in BOOKS for v in VARIANTS for br in BROKERS]


def trial_id(book: str, variant: str, broker: str) -> str:
    return f"small:eq1:{book}:{variant}:{broker}"


def trial_rows(ins_sharpe: dict) -> list[dict]:
    """The 30 trials: the in-sample Sharpe of the daily excess over the benchmark book; the benchmark only counted."""
    return [{"id": trial_id(*k), "family": "small", "source": PREREG,
             "sharpe": None if k[0] == BENCH else float(ins_sharpe[k])} for k in configs()]


def window(C: Closes, win: str) -> tuple[int, int]:
    a, z = WINDOWS[win]
    return int(np.searchsorted(C.days, np.datetime64(a))), int(np.searchsorted(C.days, np.datetime64(z), side="right")) - 1


def _pool(p: dict) -> dict:
    return {"n_trials": p["n_trials"], "sr0_annual": p["sr0_annual"]}


def evaluate(C: Closes, register: bool = True, log=print) -> dict:
    runs = {}
    for win in WINDOWS:
        i0, i1 = window(C, win)
        for k in configs():
            runs[k + (win,)] = simulate(C, *k[:2], BROKERS[k[2]], i0, i1)
    ret = {k: twr(r["equity"], r["flows"]) for k, r in runs.items()}
    xs = {k: ret[k] - ret[(BENCH,) + k[1:]] for k in ret}
    days = {win: runs[(BENCH, "once", JUDGED, win)]["days"] for win in WINDOWS}
    ins_sh = {}
    for k in configs():
        x = calendar(days["is"], xs[k + ("is",)])
        ins_sh[k] = float(x.mean() / x.std() * math.sqrt(365)) if x.std() > 0 else 0.0
    trials = trial_rows(ins_sh)
    if register:
        metrics.register(trials)                         # before any validation number exists
    log("  EQ1 in sample excess Sharpe: " + ", ".join(f"{':'.join(k)} {v:.2f}" for k, v in ins_sh.items()
                                                       if k[0] != BENCH and k[2] == JUDGED))
    p_all, p_fam = metrics.trial_pool(None, extra=trials), metrics.trial_pool("small", extra=trials)
    cols = [(bk, v, JUDGED) for bk in BOOKS if bk != BENCH for v in VARIANTS]
    M = np.column_stack([np.r_[calendar(days["is"], xs[k + ("is",)]), calendar(days["val"], xs[k + ("val",)])]
                         for k in cols])
    pbo = metrics.cscv(M)
    pbo_v = pbo["pbo"] if pbo else None
    rows = []
    for k in configs():
        row = {"book": k[0], "variant": k[1], "broker": k[2], "trial": trial_id(*k)}
        for win in WINDOWS:
            m = measure(runs[k + (win,)])
            b = measure(runs[(BENCH,) + k[1:] + (win,)])
            m["vs_bench_cagr"] = m["cagr"] - b["cagr"]
            m["months_beat"] = months_beat(days[win], ret[k + (win,)], ret[(BENCH,) + k[1:] + (win,)])
            row[win] = m
        if k[0] != BENCH:
            x = calendar(days["val"], xs[k + ("val",)])
            row["dsr_all"], row["dsr_small"] = metrics.dsr(x, p_all), metrics.dsr(x, p_fam)
            v, b = row["val"], measure(runs[(BENCH,) + k[1:] + ("val",)])
            row["conditions"] = {"cagr > benchmark": v["cagr"] > b["cagr"],
                                 "DD <= benchmark + 5 pts": v["max_dd"] <= b["max_dd"] + DD_SLACK,
                                 "DSR all >= 0.95": row["dsr_all"] >= DSR_PASS,
                                 "DSR small >= 0.95": row["dsr_small"] >= DSR_PASS,
                                 "PBO < 0.2": pbo_v is not None and pbo_v < PBO_PASS}
            row["pass"] = all(row["conditions"].values())
        rows.append(row)
    passed = [r["trial"] for r in rows if r.get("pass")]
    return {"rows": rows, "pbo": pbo_v, "pbo_combos": pbo["combos"] if pbo else None, "pool_all": _pool(p_all),
            "pool_small": _pool(p_fam), "trials": [t["id"] for t in trials], "trial_rows": trials, "passed": passed,
            "dropped": C.dropped, "twin_until": C.twin_until,
            "first": C.first,
            "lockbox": ("look due for " + ", ".join(passed) + " (not looked here)") if passed
            else "no look (no configuration passes validation)"}


# ---------------------------------------------------------------- the report

def _pct(v, d: int = 1) -> str:
    return "n/a" if v is None or not np.isfinite(v) else f"{v * 100:.{d}f} %"


def _cell(m: dict) -> str:
    return f"{_pct(m['cagr'])} / {_pct(m['max_dd'])} / {m['under_water_months']:.0f} / {m['sharpe']:.2f}"


def markdown(out: dict, about: dict) -> str:
    rows = out["rows"]
    md = [f"Generated {about['generated']}. In sample {IS_FROM} to {IS_TO}, validation {VAL_FROM} to {VAL_TO}, every "
          f"close after {VAL_TO} dropped before anything was computed (the lockbox not read). One close late: decided "
          f"at close t, filled at close t+1. 50 EUR on day 0; `plus50` adds 50 EUR on the first Xetra day of each "
          f"month. Small caps: IWM in EUR at the ECB's rate before IUSN's first close ({out['twin_until'] or 'none'}). "
          f"Bad prints dropped: " + ", ".join(f"{s} {n}" for s, n in out["dropped"].items() if n) + (
              "" if any(out["dropped"].values()) else "none") + ". Taxes left out, the final sale not deducted.\n",
          "## 1. Validation, late (CAGR / max DD / longest months under water / Sharpe; time-weighted)\n",
          "| book | variant | broker | validation | end EUR (paid in) | money-weighted | CAGR minus benchmark | "
          "months beat | orders sent / not sent | fees EUR | DSR all / small | passes |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        v = r["val"]
        md.append(f"| {r['book']} | {r['variant']} | {r['broker']} | {_cell(v)} | {v['end']:.2f} ({v['paid']:.0f}) | "
                  f"{_pct(v['mwr'])} | " + ("benchmark" if r["book"] == BENCH else
                                           f"{(v['vs_bench_cagr']) * 100:+.1f} pts") +
                  f" | {'' if r['book'] == BENCH else _pct(v['months_beat'], 0)} | {v['sent']} / {v['not_sent']} | "
                  f"{v['fees']:.2f} | " + ("" if r["book"] == BENCH else f"{r['dsr_all']:.3f} / {r['dsr_small']:.3f}")
                  + f" | {'' if r['book'] == BENCH else ('yes' if r['pass'] else 'no')} |")
    md.append(f"\nDSR of the daily excess over the benchmark book (same broker and variant), on calendar days, over "
              f"R5's pool of all ({out['pool_all']['n_trials']:,} trials, noise bar {out['pool_all']['sr0_annual']:.2f} "
              f"a year) and the small family ({out['pool_small']['n_trials']:,}, {out['pool_small']['sr0_annual']:.2f}); "
              f"higher is better, pass at 0.95. PBO of the eight Trade Republic configurations: "
              + (f"{out['pbo']:.2f} over {out['pbo_combos']:,} splits." if out["pbo"] is not None else "n/a.") + "\n")
    md += ["## 2. In sample, late (same columns)\n", "| book | variant | broker | in sample | end EUR (paid in) | "
           "CAGR minus benchmark | orders sent / not sent | fees EUR |", "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        v = r["is"]
        md.append(f"| {r['book']} | {r['variant']} | {r['broker']} | {_cell(v)} | {v['end']:.2f} ({v['paid']:.0f}) | "
                  + ("benchmark" if r["book"] == BENCH else f"{v['vs_bench_cagr'] * 100:+.1f} pts")
                  + f" | {v['sent']} / {v['not_sent']} | {v['fees']:.2f} |")
    fails = {}
    for r in rows:
        for c, ok in (r.get("conditions") or {}).items():
            if not ok:
                fails[c] = fails.get(c, 0) + 1
    md.append("\n## 3. The verdict\n")
    md.append(f"Passed: {', '.join(out['passed']) or 'none'}. Failed conditions over the 24 configurations: "
              + ", ".join(f"{c} {n}" for c, n in fails.items()) + f". Lockbox: {out['lockbox']}.\n")
    md.append(f"Trials (R5's registry, family small, before the validation numbers): {len(out['trials'])}, "
              f"`small:eq1:<book>:<variant>:<broker>`.\n")
    md.append("First close per fund (its own or the twin's): " + ", ".join(f"{s} {d}" for s, d in out["first"].items())
              + ".\n")
    return "\n".join(md)


HEAD = """# EQ1: long-term ETF books at 50 EUR, as a German retail investor can trade them

Pre-registered in `results/etf_books_eq1_prereg.md` (committed before the first run). Code:
`lab.experiments.etf_books_eq1`, the paper books `lab.paper.etf_books`, the closes `lab.collect.etf_daily`. Paper only:
nothing a live bot, a wallet or the engine reads changed.
"""


def summary(out: dict) -> dict:
    """What the paper books and the ladder read (results/etf_books_eq1.json): per configuration the validation
    numbers, the DSRs and the verdict, without series."""
    keep = ("cagr", "max_dd", "under_water_months", "sharpe", "end", "paid", "mwr", "vs_bench_cagr", "months_beat",
            "sent", "not_sent", "fees")
    rows = [{k: r.get(k) for k in ("book", "variant", "broker", "trial", "dsr_all", "dsr_small", "pass")}
            | {"val": {k: r["val"][k] for k in keep}, "is": {k: r["is"][k] for k in keep}} for r in out["rows"]]
    return {"study": "EQ1", "prereg": PREREG, "judged": JUDGED, "pbo": out["pbo"], "pool_all": out["pool_all"],
            "pool_small": out["pool_small"], "passed": out["passed"], "rows": rows, "window": [VAL_FROM, VAL_TO],
            "trials": out["trial_rows"]}


# ---------------------------------------------------------------- run

def ecb_rows(text: str, start: str = "2009-01-01") -> list[dict]:
    from .smallaccount_r10 import ecb_rows as rows
    return rows(text, start)


def snapshot() -> None:
    import urllib.request
    req = urllib.request.Request(ECB_ZIP, headers={"User-Agent": "pythia-lab"})
    with urllib.request.urlopen(req, timeout=60) as r:
        z = zipfile.ZipFile(io.BytesIO(r.read()))
    rows = [x for x in ecb_rows(z.read(z.namelist()[0]).decode("utf-8")) if x["date"] <= VAL_TO]
    with EURUSD_CSV.open("w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=["date", "eurusd"], lineterminator="\n")
        wr.writeheader()
        wr.writerows(rows)
    print(f"{len(rows)} ECB fixings {rows[0]['date']} to {rows[-1]['date']} -> {EURUSD_CSV.name}")


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--snapshot" in argv:
        snapshot()
        return 0
    C = load()
    out = evaluate(C, "--no-register" not in argv)
    about = {"generated": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    SUMMARY.write_text(json.dumps(summary(out), indent=1, default=float) + "\n", encoding="utf-8")
    dc.write_results(NAME, markdown(out, about), HEAD)
    print(f"passed: {out['passed'] or 'none'}; PBO {out['pbo']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
