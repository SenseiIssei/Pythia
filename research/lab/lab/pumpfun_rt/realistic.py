"""R1: realistic paper for pump.fun, the paper books executed the way the live bot is. PAPER ONLY.

    python -m lab.pumpfun_rt.realistic                  the daily job: refit from the live orders, the calibration
                                                        line, reports/pumpfun_rt/realistic.{json,md}
    python -m lab.pumpfun_rt.realistic run --out DIR    R1's replay: the headline strategies ideal and realistic

The old paper model (curve.Costs: a buy lands 0.4 to 3 s after the signal, 0.1 SOL a trade) made +78 % per trade on
P_pool0_wait while the live bot with the same strategy lost money: its gains were spikes sold within seconds at
prices live never got (live buys land a median 9.8 s after the signal, sales 3.9 s after their decision). The
realistic model, the default of every pipeline paper book since R1 (live.Shadow):

  latency   the buy (signal to landing), the sale (decision to landing) and the buy's send to landing drawn per trade
            from the live bot's own fills of the last FIT_DAYS days (<data>/live/pumpfun_rt/measured.jsonl, what
            execution.json is made of): their empirical quantiles, one uniform per key (strategy, coin, side, leg)
            as curve.Costs hashes it, so a replay draws the same; a side with fewer than MIN_ORDERS live fills takes
            the fixed fallback (lognormal around the measured 9.8 s and 3.9 s). Refitted daily by this job.
  fills     at the pool or curve state of the first recorded trade at or after the landing (that trade included:
            we are not first in our slot), else FILL_WAIT_MS later on the state as it stands; the stake's own price
            impact on those reserves (curve.py arithmetic and fees); a pool buy accepts down to the quote / 1.60
            (live_exec.LIVE_POOL_BUY_TOL) and is checked against the reserves at its send (landing less the drawn
            send time): a price already run away is the live pre-send skip "price ran away (+x %)", no fee; at the
            landing a pool buy under its bound is "price ran away on landing" (6040) and pays the fee. Curve buys
            keep their cost limit, sales their min_out (0 for a protective exit), as live.
  failures  "not landed", "simulation failed" and any other live buy failure drawn at the live rates per buy, each
            with its live fee; 6040 is not drawn, it comes from the bound above (the job reports both rates).
  costs     the live median network fee (base and priority) per transaction plus the Helius Sender tip, which a
            failed transaction does not pay; the pump/PumpSwap fees from the coin's own trades.
  stake     the live bot's sizing (sizing.sized) on a paper wallet of START_SOL (0.55 SOL, about 50 EUR) per book: the
            share, limits=wallet or not, the brake and the floor from the owner's control file, the open slots from
            the app's settings, the fee reserve kept (live_exec.RESERVE_SOL), a buy refused when the paper wallet
            cannot pay it. A wallet that can no longer pay one trade is topped up to START_SOL once nothing is open
            (counted), so the book keeps trading and its P&L runs on. The owner's pause stops only the live bot.

R2 (results/pumpfun_smallwallet_r2.md): the small-wallet search's picks (SMALL) run as realistic books of their own,
each on its own START_SOL paper wallet with its sizing fixed as picked (FixedSizing, not the owner's settings); the
daily job writes their wallets in SOL and euro into realistic.md and the daily card shows them.

The old books run on as `<name>_ideal` twins until IDEAL_UNTIL (two weeks), then go. The calibration line compares
the live bot with the realistic paper twin P_pool0_wait on the same coins (entry and exit price, P&L in points);
calibrated when the median P&L difference per matched trade is within CALIB_POINTS over 7 full days. Nothing here
holds a wallet, reads a key, signs or sends; the live bot's files are only read and the live bot is unchanged.
"""

from __future__ import annotations

import argparse
import csv
import dataclasses
import hashlib
import json
import math
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from . import curve as C
from . import pipeline as P
from . import sizing as Z

FIT_DAYS = 7
MIN_ORDERS = 30
DAY_MS = 86_400_000
LAT_LO_MS, LAT_HI_MS = 0.0, 120_000.0      # a draw's range: a landing at or before the signal is the signal's slot
FILL_WAIT_MS = 2_000                      # no trade of the coin this long after the landing: the state as it stands
STUCK_MS = 10 * 60_000                    # a sale with no pool to go to is given up after this (as PaperExecutor)
START_SOL = 0.55                          # the paper wallet of every realistic book, about 50 EUR
# The live executor's numbers (tests keep them equal to live_exec's and txbuild's).
POOL_BUY_TOL = 0.60                       # live_exec.LIVE_POOL_BUY_TOL
RESERVE_SOL = 0.01                        # live_exec.RESERVE_SOL
TIP_L = 5_000                             # Helius Sender's minimum tip, live_exec.sender_tip_lamports' default
RAN_AWAY = "price ran away"               # live_exec.RAN_AWAY
RAN_AWAY_LANDING = "price ran away on landing"
# The fallback when a side has fewer than MIN_ORDERS live fills: lognormal around what the live bot measured up to
# 2026-10-23 (buys a median 9.8 s after the signal, sales 3.9 s after their decision, the send 0.5 s to landing,
# 10 to 90 % of the buys 0.75 to 28 s), and its median network fee.
FALLBACK = {"buy": (9_800.0, 1.4), "sell": (3_900.0, 1.4), "send": (530.0, 0.8)}
FALLBACK_FEE_L = 215_000
FALLBACK_FAIL = {"not landed": 0.03}
FAIL_FEE = {"not landed": 0, "simulation failed": 0}
IDEAL_UNTIL_MS = int(datetime(2026, 11, 6, tzinfo=timezone.utc).timestamp() * 1000)
IDEAL = "_ideal"
TWIN = "P_pool0_wait"                     # the live strategy, whose realistic paper twin the calibration compares
CALIB_POINTS = 5.0
CALIB_DAYS = 7
MIN_MATCHED = 10
MATCH_MS = 10 * 60_000                    # a live and a paper entry of the same coin within this are one trade
# R2 (results/pumpfun_smallwallet_r2.md): the small-wallet search's picks as paper books from its deploy, each with its
# own START_SOL paper wallet and its sizing fixed as picked (limits=wallet, floor 0), not the owner's settings:
# (book, strategy, share of the wallet, max open, brake)
SMALL = (("P_pool5_top30t_sw10o3n", "P_pool5_top30t", 0.10, 3, False),
         ("P_pool5_top30t_sw10o2n", "P_pool5_top30t", 0.10, 2, False),
         ("P_pool5_top30t_sw10o1n", "P_pool5_top30t", 0.10, 1, False))


def u_of(key: tuple) -> float:
    """The uniform of a draw's key (curve.Costs.latency hashes the same way)."""
    h = hashlib.blake2b(repr(key).encode(), digest_size=8).digest()
    return (int.from_bytes(h, "big") + 0.5) / 2 ** 64


def _q(xs, q: float) -> float | None:
    return float(np.quantile(np.asarray(xs, dtype=float), q)) if len(xs) else None


# ---------------------------------------------------------------- distributions

@dataclass(frozen=True)
class Empirical:
    """The measured values' quantile function (linear between the sorted points), clipped to the draw's range."""
    ms: tuple

    def quantile(self, u: float) -> float:
        s = self.ms
        x = float(np.interp(u, (np.arange(len(s)) + 0.5) / len(s), s))
        return min(LAT_HI_MS, max(LAT_LO_MS, x))

    def to_json(self) -> dict:
        return {"kind": "empirical", "ms": list(self.ms)}


@dataclass(frozen=True)
class Lognormal:
    median_ms: float
    sigma: float

    def quantile(self, u: float) -> float:
        return min(LAT_HI_MS, max(LAT_LO_MS, self.median_ms * math.exp(self.sigma * C._norm_ppf(u))))

    def to_json(self) -> dict:
        return {"kind": "lognormal", "median_ms": self.median_ms, "sigma": self.sigma}


def dist_of(d: dict | None, side: str):
    if d and d.get("kind") == "empirical" and d.get("ms"):
        return Empirical(tuple(sorted(float(x) for x in d["ms"])))
    if d and d.get("kind") == "lognormal":
        return Lognormal(float(d["median_ms"]), float(d["sigma"]))
    return Lognormal(*FALLBACK[side])


def describe(dist) -> dict:
    """p10, median and p90 of a distribution's draws, ms."""
    return {k: dist.quantile(q) for k, q in (("p10", 0.1), ("median", 0.5), ("p90", 0.9))}


# ---------------------------------------------------------------- the fit

def fail_kind(why) -> str | None:
    """A live buy failure's kind: 6040 (the price ran on to the landing), not landed, simulation failed, other."""
    w = str(why or "").lower()
    if "6040" in w or "ran away" in w:
        return "6040"
    if "not landed" in w:
        return "not landed"
    if "simulation failed" in w:
        return "simulation failed"
    if w.startswith("refused"):
        return None
    return "other"


@dataclass
class Fit:
    buy: object = field(default_factory=lambda: Lognormal(*FALLBACK["buy"]))
    sell: object = field(default_factory=lambda: Lognormal(*FALLBACK["sell"]))
    send: object = field(default_factory=lambda: Lognormal(*FALLBACK["send"]))
    fee_l: int = FALLBACK_FEE_L               # network fee per transaction (base and priority), as live paid
    tip_l: int = TIP_L                        # the Sender tip of every transaction that lands without an error
    fail: dict = field(default_factory=lambda: dict(FALLBACK_FAIL))     # drawn buy failures: kind -> rate per buy
    fail_fee: dict = field(default_factory=lambda: dict(FAIL_FEE))      # kind -> lamports, as live paid
    live: dict = field(default_factory=dict)  # what the fit saw (counts, sources, the live 6040 rate, window)

    def tx_l(self) -> int:
        return int(self.fee_l) + int(self.tip_l)

    def failed_l(self, kind: str | None = None) -> int:
        """A failed transaction's fee: the kind's live fee, else one that landed with an error (no tip)."""
        return int(self.fail_fee.get(kind, self.fee_l)) if kind is not None else int(self.fee_l)

    def draw_fail(self, u: float) -> str | None:
        acc = 0.0
        for k in sorted(self.fail):
            acc += float(self.fail[k])
            if u < acc:
                return k
        return None

    def to_json(self) -> dict:
        return {"buy": self.buy.to_json(), "sell": self.sell.to_json(), "send": self.send.to_json(),
                "fee_l": int(self.fee_l), "tip_l": int(self.tip_l), "fail": self.fail, "fail_fee": self.fail_fee,
                "live": self.live}

    @classmethod
    def from_json(cls, d: dict | None) -> "Fit":
        d = d or {}
        return cls(dist_of(d.get("buy"), "buy"), dist_of(d.get("sell"), "sell"), dist_of(d.get("send"), "send"),
                   int(d.get("fee_l") or FALLBACK_FEE_L), int(d.get("tip_l") if d.get("tip_l") is not None else TIP_L),
                   {k: float(v) for k, v in (d.get("fail") if d.get("fail") is not None else FALLBACK_FAIL).items()},
                   {**FAIL_FEE, **{k: int(v) for k, v in (d.get("fail_fee") or {}).items()}}, d.get("live") or {})


def fit(rows: list[dict], now_ms: int, days: int = FIT_DAYS) -> Fit:
    """The model from the live executor's measured.jsonl rows of the last `days` days (test or full mode): each side's
    landing latencies (a side under MIN_ORDERS fills: the fallback), the buy's send to landing, the median fee per
    transaction, the buy failures per kind and their fees."""
    lo = now_ms - days * DAY_MS
    rows = [r for r in rows if lo <= int(r.get("t") or 0) <= now_ms and r.get("mode") in ("test", "full")]
    fills = [r for r in rows if r.get("what") == "fill" and r.get("lat_ms") is not None]
    buys = [float(r["lat_ms"]) for r in fills if r.get("side") == "buy"]
    sells = [float(r["lat_ms"]) for r in fills if r.get("side") == "sell"]
    send = [max(0.0, float(r["send_to_land_ms"])) for r in fills
            if r.get("side") == "buy" and r.get("send_to_land_ms") is not None]
    fees = [int(r["fee_l"]) for r in rows if r.get("what") == "fee" and r.get("fee_l")]
    failed = [(fail_kind(r.get("why")), int(r.get("fee_l") or 0)) for r in rows
              if r.get("what") == "failed" and r.get("side") == "buy"]
    failed = [(k, f) for k, f in failed if k is not None]
    orders = len(buys) + len(failed)
    f = Fit()
    src = {}
    for side, xs in (("buy", buys), ("sell", sells), ("send", send)):
        ok = len(xs) >= MIN_ORDERS
        src[side] = "live" if ok else "fallback"
        if ok:
            setattr(f, side, Empirical(tuple(sorted(xs))))
    if len(fees) >= MIN_ORDERS:
        f.fee_l = int(np.median(fees))
    kinds = sorted({k for k, _ in failed})
    if orders >= MIN_ORDERS:
        f.fail = {k: sum(1 for x, _ in failed if x == k) / orders for k in kinds if k != "6040"}
        src["fail"] = "live"
    else:
        src["fail"] = "fallback"
    for k in kinds:
        f.fail_fee[k] = int(np.median([v for x, v in failed if x == k]))
    f.live = {"from_ms": lo, "to_ms": now_ms, "days": days, "buys": len(buys), "sells": len(sells),
              "buy_orders": orders, "fees": len(fees), "source": src,
              "failed": {k: sum(1 for x, _ in failed if x == k) for k in kinds},
              "rate_6040": (sum(1 for x, _ in failed if x == "6040") / orders) if orders else None}
    return f


# ---------------------------------------------------------------- files

def reports_dir() -> Path:
    from .. import report
    return report.REPORTS / "pumpfun_rt"


def fit_path() -> Path:
    return reports_dir() / "realistic.json"


def read_json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def load_fit(path: Path | None = None) -> Fit:
    """The daily job's fit, the fallback before its first run."""
    d = read_json(path or fit_path())
    return Fit.from_json(d.get("fit") if isinstance(d, dict) else None)


@dataclass(frozen=True)
class LiveConfig:
    """The live bot's sizing settings the paper wallets follow: limits=wallet or not (the live status's ack), the
    stake's share, the brake and the floor (the owner's control.json), the open slots and a stake ceiling (the app's
    live_settings.json). Without the files the sizing's defaults."""
    wallet: bool = False
    share: float = Z.SHARE
    brake: bool = True
    floor_sol: float | None = None
    max_open: int = P.HARD_MAX_OPEN
    ceiling_sol: float = P.HARD_STAKE_SOL

    @classmethod
    def load(cls, d: Path | None = None) -> "LiveConfig":
        d = d or reports_dir()
        ctl = read_json(d / "control.json") or {}
        st = read_json(d / "live_settings.json") or {}
        ack = (read_json(d / "live_status.json") or {}).get("ack") or {}
        wallet = ack.get("limits") == "wallet"

        def num(x, lo, hi):
            try:
                v = float(x)
            except (TypeError, ValueError):
                return None
            return min(hi, max(lo, v)) if math.isfinite(v) else None
        share = Z.SHARE
        own = num(ctl.get("share"), 0.01, Z.WALLET_MAX_SHARE)
        if wallet:
            share = own if own is not None else (num(ack.get("stake_share"), 0.01, Z.ACK_MAX_SHARE) or Z.SHARE)
        elif own is not None:
            share = min(own, Z.SHARE)
        mo = num(st.get("max_open"), 0, P.HARD_MAX_OPEN)
        max_open = int(mo) if mo is not None else P.HARD_MAX_OPEN
        top = num(st.get("max_trade_sol"), 0.0, math.inf)
        ceiling = (top if top is not None else math.inf) if wallet else min(P.HARD_STAKE_SOL, top or math.inf)
        return cls(wallet, share, bool(ctl.get("brake", True)) if wallet else True,
                   num(ctl.get("floor_sol"), 0.0, 10.0) if wallet else None, max_open, ceiling)

    def to_json(self) -> dict:
        return {**dataclasses.asdict(self), "ceiling_sol": None if math.isinf(self.ceiling_sol) else self.ceiling_sol}


class Model:
    """The fit and the live settings every realistic book reads; reload() takes the day's new ones."""

    def __init__(self, fit_: Fit | None = None, cfg: LiveConfig | None = None):
        self.fit = fit_ if fit_ is not None else load_fit()
        self.cfg = cfg if cfg is not None else LiveConfig.load()

    def reload(self) -> None:
        self.fit, self.cfg = load_fit(), LiveConfig.load()


class FixedSizing:
    """R2's small-wallet books: the day's fit of `model` (which the collector reloads), the sizing settings fixed."""

    def __init__(self, model: Model, cfg: LiveConfig):
        self.model, self.cfg = model, cfg

    @property
    def fit(self) -> Fit:
        return self.model.fit

    def reload(self) -> None:
        pass


def small_cfg(share: float, max_open: int, brake: bool) -> LiveConfig:
    """A small-wallet book's sizing: limits=wallet, the share, the brake, floor 0, the slots, no ceiling."""
    return LiveConfig(True, float(share), bool(brake), 0.0, int(max_open), math.inf)


@dataclass(frozen=True)
class RealCosts(C.Costs):
    """curve.Costs of a realistic book (Engine.rule_costs): the fit's draws and its fee with the tip."""
    model: object = field(default=None, compare=False, hash=False)

    def latency(self, *key) -> float:
        f = self.model.fit
        return (f.sell if "sell" in key else f.buy).quantile(u_of(key))

    def tx_lamports(self) -> int:
        return self.model.fit.tx_l()


# ---------------------------------------------------------------- the paper wallet

@dataclass
class PaperWallet:
    """A realistic book's money: the start, every realised result (closed trades, failed buys' fees), the peak of
    the realised P&L for the brake, and the closed trades' count and mean return for the sizing's proof rule. A wallet
    that can no longer pay one trade and holds nothing is topped up to START_SOL (as the owner tops up the live one),
    counted in `refills` and `topped_l`; its P&L runs on, so a book that loses keeps saying so and keeps trading."""
    start_l: int = int(START_SOL * C.LAMPORTS)
    pnl_l: int = 0
    peak_l: int = 0
    n: int = 0
    ret_sum: float = 0.0
    refills: int = 0
    topped_l: int = 0

    def top_up(self) -> bool:
        """Back to START_SOL when the wallet (nothing open) holds less; True when it did."""
        add = int(START_SOL * C.LAMPORTS) - self.cash_l(0)
        if add <= 0:
            return False
        self.start_l += add
        self.topped_l += add
        self.refills += 1
        return True

    def book(self, pnl_l: int, ret: float | None = None) -> None:
        self.pnl_l += int(pnl_l)
        self.peak_l = max(self.peak_l, self.pnl_l)
        if ret is not None:
            self.n += 1
            self.ret_sum += float(ret)

    def cash_l(self, open_l: int) -> int:
        """What the wallet holds in SOL: the start and the realised P&L less what the open positions cost."""
        return self.start_l + self.pnl_l - int(open_l)

    def limits(self, open_l: int, cfg: LiveConfig) -> tuple[P.Limits, str | None]:
        """The Risk limits for the next buy as the live executor sizes them (LiveExecutor.sized), and the pause's
        reason when the stake is 0."""
        bal, held = self.cash_l(open_l) / C.LAMPORTS, open_l / C.LAMPORTS
        base = bal + held
        room = max(0.0, bal - RESERVE_SOL) / (1 + C.SLIP_TOL) if cfg.wallet else None
        sol, why = Z.sized(balance_sol=bal, open_cost_sol=held, peak_pnl_sol=self.peak_l / C.LAMPORTS,
                           pnl_sol=self.pnl_l / C.LAMPORTS, live_trades=self.n,
                           live_mean=self.ret_sum / self.n if self.n else None, ceiling_sol=cfg.ceiling_sol,
                           share=cfg.share, wallet=cfg.wallet, room_sol=room, brake=cfg.brake, floor_sol=cfg.floor_sol)
        exp = max(0.0, base - RESERVE_SOL) if cfg.wallet else P.HARD_MAX_EXPOSURE_SOL
        loss = math.inf if cfg.wallet else min(P.HARD_MAX_DAILY_LOSS_SOL, Z.DAILY_LOSS_SHARE * base)
        return P.Limits(sol, cfg.max_open, exp, loss), (None if sol > 0 else why)

    def to_json(self) -> dict:
        return dataclasses.asdict(self)

    @classmethod
    def from_json(cls, d: dict | None) -> "PaperWallet":
        w = cls()
        for k in ("start_l", "pnl_l", "peak_l", "n", "refills", "topped_l"):
            if isinstance((d or {}).get(k), (int, float)):
                setattr(w, k, int(d[k]))
        if isinstance((d or {}).get("ret_sum"), (int, float)):
            w.ret_sum = float(d["ret_sum"])
        return w


# ---------------------------------------------------------------- the executor and the book

class RealExecutor(P.PaperExecutor):
    """Fills an order the way the live bot gets it (the module's docstring): the fit's latency, the first recorded
    trade at or after the landing, the live bounds, failures and fees. With a wallet the stake follows it."""

    kind = "realistic"

    def __init__(self, model: Model, wallet: PaperWallet | None = None):
        super().__init__()
        self.model, self.wallet = model, wallet
        self.wait: dict[str, list] = {}               # mint -> [[side, order, done], ...] landed, awaiting a trade

    def open_l(self) -> int:
        return sum(r.exposure() for r in self.pipe.risk.values())

    def ready(self) -> str | None:
        """The live sizing on the paper wallet, into every Risk of the book; the pause's reason when it is 0."""
        if self.wallet is None:
            return None
        open_l = self.open_l()
        lim, why = self.wallet.limits(open_l, self.model.cfg)
        if why and not open_l and self.wallet.top_up():
            lim, why = self.wallet.limits(0, self.model.cfg)
        for r in self.pipe.risk.values():
            r.limits = lim
        return why

    def buy(self, o: P.Order) -> None:
        pipe, eng, f = self.pipe, self.pipe.eng, self.model.fit
        if self.wallet is not None and \
                self.wallet.cash_l(self.open_l() - o.limit_l) < o.limit_l + int(RESERVE_SOL * C.LAMPORTS):
            return pipe.buy_failed(o.pid, o.signal_ms, "refused: wallet balance too low", 0)
        key = (P.base_name(pipe.strat_of(o.pid)), o.mint, "buy")
        lat = f.buy.quantile(u_of(key))
        pipe.lat[o.pid] = lat
        land = o.signal_ms + lat
        kind = f.draw_fail(u_of(key + ("fail",)))
        if kind is not None:
            return eng.push(land, "pipe", (self, "_failed", (o, kind)))
        if o.venue == "pool":
            send = land - min(lat, f.send.quantile(u_of(key + ("send",))))
            return eng.push(send, "pipe", (self, "_presend", (o, land)))
        eng.push(land, "pipe", (self, "_landed", ("buy", o)))

    def sell(self, o: P.Order) -> None:
        eng, r = self.pipe.eng, self.pipe.strat_of(o.pid)
        key = (P.base_name(r), o.mint, "sell") if o.leg == 0 else (P.base_name(r), o.mint, "sell", o.leg)
        eng.push(o.signal_ms + self.model.fit.sell.quantile(u_of(key)), "pipe", (self, "_landed", ("sell", o)))

    def _failed(self, at: float, data) -> None:
        o, kind = data
        self.pipe.buy_failed(o.pid, at, kind, self.model.fit.failed_l(kind))

    def _presend(self, at: float, data) -> None:
        """The live pre-send check of a pool buy on the reserves at its send: run away beyond the tolerance, a skip
        without a send or a fee; else the bound from the fresher quote, never looser than the signal's."""
        o, land = data
        pipe = self.pipe
        tok = pipe.eng.tokens.get(o.mint)
        spend = o.stake_l or int(o.limit_l / (1 + C.SLIP_TOL))
        now = C.pool_buy(spend, tok.pb, tok.pq, tok.amm_fee_bps or C.DEFAULT_FEE_BPS) \
            if tok is not None and tok.pb and tok.pq else 0
        if now > 0 and o.tokens > 0:
            run = o.tokens / now - 1
            if run > POOL_BUY_TOL:
                name = pipe.strat_of(o.pid).name
                pipe.buy_failed(o.pid, at, f"{RAN_AWAY} (+{run * 100:.0f} %)", 0)
                pipe.skip(name, o.mint, RAN_AWAY)
                return
            o = dataclasses.replace(o, least=max(int(now / (1 + POOL_BUY_TOL)), int(o.tokens / (1 + POOL_BUY_TOL))))
        pipe.eng.push(land, "pipe", (self, "_landed", ("buy", o)))

    def _landed(self, at: float, data) -> None:
        """Landed: the fill waits for the coin's next recorded trade (on_trade), at most FILL_WAIT_MS."""
        side, o = data
        item = [side, o, False]
        self.wait.setdefault(o.mint, []).append(item)
        self.pipe.eng.push(at + FILL_WAIT_MS, "pipe", (self, "_due", item))

    def on_trade(self, table: str, row: dict) -> None:
        w = self.wait.pop(row.get("mint"), None) if self.wait else None
        for item in w or ():
            if not item[2]:
                item[2] = True
                self._fill(row["t"], item[0], item[1])

    def _due(self, at: float, item: list) -> None:
        if item[2]:
            return
        item[2] = True
        w = self.wait.get(item[1].mint)
        if w is not None:
            w.remove(item)
            if not w:
                self.wait.pop(item[1].mint, None)
        self._fill(at, item[0], item[1])

    def _fill(self, at: float, side: str, o: P.Order) -> None:
        pipe = self.pipe
        eng, f = pipe.eng, self.model.fit
        c = eng.cost_of(pipe.strat_of(o.pid).name)
        tok = eng.tokens.get(o.mint)
        if side == "sell":
            v = eng.sale_value(tok, o.tokens, c)
            if v is None:                                     # curve done, pool not seen yet
                if at - o.signal_ms < STUCK_MS:
                    eng.push(at + 2_000, "pipe", (self, "_landed", ("sell", o)))
                    return None
                return pipe.sold(o.pid, at, o.tokens, 0, f.tx_l(), stuck=True)
            if v < o.limit_l:
                return pipe.sell_failed(o.pid, at, "under the floor", f.failed_l())
            return pipe.sold(o.pid, at, o.tokens, v, f.tx_l())
        if tok is None:
            return pipe.buy_failed(o.pid, at, "token gone", f.failed_l())
        if o.venue == "pool":
            if not tok.pq or not tok.pb:
                return pipe.buy_failed(o.pid, at, "no pool state", f.failed_l())
            spend = o.stake_l or int(o.limit_l / (1 + C.SLIP_TOL))
            got = C.pool_buy(spend, tok.pb, tok.pq, max(tok.amm_fee_bps, c.fee_bps_floor))
            if got <= 0:
                return pipe.buy_failed(o.pid, at, "nothing filled", f.failed_l())
            if got < (o.least or max(1, int(o.tokens / (1 + POOL_BUY_TOL)))):
                return pipe.buy_failed(o.pid, at, RAN_AWAY_LANDING, f.failed_l("6040"))
            return pipe.bought(o.pid, at, got, spend, f.tx_l())
        if not tok.on_curve:
            return pipe.buy_failed(o.pid, at, "curve completed before the buy landed", f.failed_l())
        want = min(o.tokens, tok.rt)
        if want <= 0:
            return pipe.buy_failed(o.pid, at, "nothing filled", f.failed_l())
        cost = P.curve_cost(want, tok.vs, tok.vt, max(tok.fee_bps, c.fee_bps_floor))
        if cost > o.limit_l:
            return pipe.buy_failed(o.pid, at, "slippage", f.failed_l())
        pipe.bought(o.pid, at, want, cost, f.tx_l())


class Book(P.Pipeline):
    """A realistic paper book: its strategies through a RealExecutor, every realised result into its paper wallet."""

    def buy_failed(self, pid: int, at: float, why: str, fee_l: int) -> None:
        if pid in self.pos and self.exec.wallet is not None:
            self.exec.wallet.book(-int(fee_l))
        super().buy_failed(pid, at, why, fee_l)

    def _close(self, p: dict, at: float) -> None:
        super()._close(p, at)
        if self.exec.wallet is not None:
            pnl = p["proceeds_l"] - p["cost_l"] - p["fees_l"]
            self.exec.wallet.book(pnl, pnl / (p["stake_l"] or 1))

    def status(self) -> dict:
        out = super().status()
        w = self.exec.wallet
        if w is not None:
            open_l = self.exec.open_l()
            out["wallet"] = {"sol": (w.cash_l(open_l) + open_l) / C.LAMPORTS, "pnl_sol": w.pnl_l / C.LAMPORTS,
                             "trades": w.n, "refills": w.refills}
        return out


def realistic(s: P.Strategy) -> P.Strategy:
    """A strategy as a realistic book trades it: the stake is the paper wallet's (the Risk limits, as live)."""
    return dataclasses.replace(s, stake_sol=math.inf)


def ideal(s: P.Strategy) -> P.Strategy:
    """The old paper book's twin: the same strategy and latency draws under `<name>_ideal`, 0.1 SOL a trade."""
    return dataclasses.replace(s, name=s.name + IDEAL, p={**s.p, "base": P.base_name(s)},
                               label=f"{s.label}; the old paper model (0.4 to 3 s, 0.1 SOL) until 2026-11-06")


def books(eng, strategies: list[P.Strategy], model: Model, wallets: dict | None = None, kill=None) -> list[Book]:
    """One realistic book per strategy on the engine, each with its paper wallet (`wallets`: name -> PaperWallet,
    filled in for the new ones). P_pool0_wait_tol60 is left out: the realistic P_pool0_wait has the live bound."""
    wallets = wallets if wallets is not None else {}
    out = []
    for s in strategies:
        if s.p.get("buy_tol") is not None:
            continue
        w = wallets.setdefault(s.name, PaperWallet())
        eng.rule_costs[s.name] = RealCosts(model=model)
        out.append(eng.add_pipe(Book(eng, [realistic(s)], RealExecutor(model, w), name="realistic", kill=kill)))
    return out


def small_books(eng, model: Model, wallets: dict | None = None, kill=None, small=None) -> list[Book]:
    """R2: one realistic book per small-wallet pick (SMALL), on its own START_SOL paper wallet (`wallets`, filled in
    for new ones) with its fixed sizing; it draws its latency with its strategy's key, so it gets the fills of the
    strategy's own realistic book and differs only in its stakes and slots."""
    wallets = wallets if wallets is not None else {}
    out = []
    for name, base, share, max_open, brake in (SMALL if small is None else small):
        s = P.BY_NAME[base]
        v = dataclasses.replace(s, name=name, p={**s.p, "base": base}, stake_sol=math.inf,
                                label=f"{s.label}; R2 small wallet: {share * 100:g} % of the wallet, at most "
                                      f"{max_open} open, brake {'on' if brake else 'off'}, from {START_SOL} SOL")
        m = FixedSizing(model, small_cfg(share, max_open, brake))
        w = wallets.setdefault(name, PaperWallet())
        eng.rule_costs[name] = RealCosts(model=m)
        out.append(eng.add_pipe(Book(eng, [v], RealExecutor(m, w), name="realistic", kill=kill)))
    return out


def sol_eur() -> float | None:
    """One SOL in euro: notify.sol_eur (the engine's rate or Kraken's public ticker), else the owner's target file's
    last value over its SOL; None if neither."""
    try:
        from ..ops import notify
        v = notify.sol_eur()
        if v:
            return float(v)
    except Exception:                                        # noqa: BLE001 - the file next
        pass
    d = read_json(reports_dir() / "target_eur.json") or {}
    try:
        return float(d["value_eur"]) / float(d["sol"]) if float(d.get("sol") or 0) > 0 else None
    except (KeyError, TypeError, ValueError):
        return None


def small_status(state: dict | None, eur: float | None, small=None) -> list[dict]:
    """The small-wallet books' paper wallets from the collector's state.json: what each holds (its start, top-ups
    included, and every realised result; open positions at their cost), in SOL and euro, its P&L, trades, top-ups."""
    pw = (state or {}).get("paper_wallets") or {}
    out = []
    for name, base, share, max_open, brake in (SMALL if small is None else small):
        w = PaperWallet.from_json(pw.get(name)) if name in pw else None
        sol = (w.start_l + w.pnl_l) / C.LAMPORTS if w is not None else START_SOL
        out.append({"book": name, "strategy": base, "share": share, "max_open": max_open, "brake": brake,
                    "sol": sol, "eur": sol * eur if eur else None, "pnl_sol": w.pnl_l / C.LAMPORTS if w else 0.0,
                    "trades": w.n if w else 0, "refills": w.refills if w else 0, "started": w is not None})
    return out


def small_md(rows: list[dict], eur: float | None) -> list[str]:
    if not rows:
        return []
    md = [f"Small-wallet paper books (R2, results/pumpfun_smallwallet_r2.md): {START_SOL} SOL each from the deploy, "
          f"sizing fixed as picked; 1 SOL = {'n/a' if not eur else format(eur, '.2f')} EUR.", "",
          "| book | strategy | share | max open | brake | wallet SOL | wallet EUR | P&L SOL | trades | top-ups |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        eur_ = "n/a" if r["eur"] is None else f"{r['eur']:.2f}"
        md.append(f"| {r['book']} | {r['strategy']} | {r['share'] * 100:g} % | {r['max_open']} | "
                  f"{'on' if r['brake'] else 'off'} | {r['sol']:.3f} | {eur_} | {r['pnl_sol']:+.3f} | {r['trades']} | "
                  f"{r['refills']} |")
    return md + [""]


# ---------------------------------------------------------------- calibration

def _f(x) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def calibrate(live_rows: list[dict], paper_rows: list[dict], since_ms: int, until_ms: int, rule: str = TWIN) -> dict:
    """The live bot against the realistic paper twin on the same coins (each side's first closed entry of a coin from
    since_ms to until_ms, entered within MATCH_MS of each other): the paper's entry and exit price over the live's
    less 1, and the P&L difference in points (paper return less live return, x 100)."""
    def first(rows, live):
        out = {}
        for r in rows:
            sig, ret = _f(r.get("signal_ms")), _f(r.get("ret"))
            if r.get("rule") != rule or sig is None or ret is None or not since_ms <= sig < until_ms:
                continue
            if live and r.get("mode") not in ("test", "full"):
                continue
            if not live and r.get("exit_why") == "restart":
                continue
            if r.get("mint") and (r["mint"] not in out or sig < _f(out[r["mint"]]["signal_ms"])):
                out[r["mint"]] = r
        return out
    lv, pp = first(live_rows, True), first(paper_rows, False)
    pairs = []
    for m, a in lv.items():
        b = pp.get(m)
        if b is None or abs(_f(a["signal_ms"]) - _f(b["signal_ms"])) > MATCH_MS:
            continue
        le, lx, pe, px = (_f(a.get("entry_price")), _f(a.get("exit_price")), _f(b.get("entry_price")),
                          _f(b.get("exit_price")))
        pairs.append({"mint": m, "symbol": a.get("symbol") or b.get("symbol"), "signal_ms": int(_f(a["signal_ms"])),
                      "live_ret": _f(a["ret"]), "paper_ret": _f(b["ret"]),
                      "d_entry": pe / le - 1 if pe and le else None, "d_exit": px / lx - 1 if px and lx else None,
                      "d_pts": (_f(b["ret"]) - _f(a["ret"])) * 100})

    def med(k):
        xs = [p[k] for p in pairs if p[k] is not None]
        return float(np.median(xs)) if xs else None
    d = [p["d_pts"] for p in pairs]
    return {"rule": rule, "from_ms": since_ms, "to_ms": until_ms, "live": len(lv), "paper": len(pp), "n": len(pairs),
            "d_entry": med("d_entry"), "d_exit": med("d_exit"), "d_pts": med("d_pts"),
            "d_pts_mean": float(np.mean(d)) if d else None,
            "live_mean": float(np.mean([p["live_ret"] for p in pairs])) if pairs else None,
            "paper_mean": float(np.mean([p["paper_ret"] for p in pairs])) if pairs else None,
            "pairs": sorted(pairs, key=lambda p: p["signal_ms"])}


def verdict(cal: dict, days_covered: float) -> str:
    """calibrated, not calibrated, or not yet (under CALIB_DAYS of realistic paper or MIN_MATCHED matched trades)."""
    if days_covered < CALIB_DAYS or cal["n"] < MIN_MATCHED or cal["d_pts"] is None:
        return "not yet"
    return "calibrated" if abs(cal["d_pts"]) <= CALIB_POINTS else "not calibrated"


def read_csv(p: Path) -> list[dict]:
    try:
        with p.open(newline="", encoding="utf-8") as fh:
            return list(csv.DictReader(fh))
    except OSError:
        return []


def calib_line(cal: dict, word: str, days_covered: float) -> str:
    def pc(x):
        return "n/a" if x is None else f"{x * 100:+.1f} %"
    pts = "n/a" if cal["d_pts"] is None else f"{cal['d_pts']:+.1f} points"
    return (f"live vs realistic paper ({cal['rule']}, {days_covered:.1f} of {CALIB_DAYS} days): {cal['n']} matched "
            f"trades of {cal['live']} live and {cal['paper']} paper; entry price {pc(cal['d_entry'])}, exit price "
            f"{pc(cal['d_exit'])}, P&L median {pts} per trade (paper less live): {word}")


def daily(now_ms: int | None = None, write: bool = True) -> dict:
    """The daily job: the fit from the last FIT_DAYS days of live orders, the live settings, the calibration line of
    the last CALIB_DAYS days (realistic paper only: since state.json's realistic_since), into realistic.json/md and
    one row a day in realistic_calib.csv."""
    from . import measure
    from .live import paper_dir
    from .live_exec import data_dir
    now_ms = now_ms or int(time.time() * 1000)
    f = fit(measure.read_measured(data_dir() / "measured.jsonl"), now_ms)
    since = (read_json(paper_dir() / "state.json") or {}).get("realistic_since")
    lo = now_ms - CALIB_DAYS * DAY_MS
    start = max(lo, int(since)) if since else now_ms
    cal = calibrate(read_csv(data_dir() / "ledger.csv"), read_csv(paper_dir() / "ledger.csv"), start, now_ms)
    covered = (now_ms - start) / DAY_MS
    word = verdict(cal, covered)
    eur = sol_eur()
    out = {"updated_ms": now_ms, "fit": f.to_json(), "config": LiveConfig.load().to_json(),
           "realistic_since": since, "calibration": cal | {"days": covered, "verdict": word,
                                                           "line": calib_line(cal, word, covered)},
           "sol_eur": eur, "small": small_status(read_json(paper_dir() / "state.json"), eur)}
    if write:
        from .live_exec import write_json
        d = reports_dir()
        write_json(d / "realistic.json", out)
        (d / "realistic.md").write_text(markdown(out), encoding="utf-8")
        day = datetime.fromtimestamp(now_ms / 1000, timezone.utc).strftime("%Y-%m-%d")
        rows = [r for r in read_csv(d / "realistic_calib.csv") if r.get("day") != day]
        rows.append({"day": day, "n": cal["n"], "d_entry": cal["d_entry"], "d_exit": cal["d_exit"],
                     "d_pts": cal["d_pts"], "days": round(covered, 2), "verdict": word})
        cols = ["day", "n", "d_entry", "d_exit", "d_pts", "days", "verdict"]
        tmp = d / "realistic_calib.csv.tmp"
        with tmp.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
        tmp.replace(d / "realistic_calib.csv")
    return out


def markdown(d: dict) -> str:
    f = Fit.from_json(d["fit"])
    src = (f.live or {}).get("source") or {}

    def ms(dist):
        x = describe(dist)
        return f"{x['median'] / 1000:.1f} s (10 to 90 %: {x['p10'] / 1000:.1f} to {x['p90'] / 1000:.1f} s)"
    fails = ", ".join(f"{k} {v * 100:.1f} %" for k, v in sorted(f.fail.items())) or "none"
    r6 = (f.live or {}).get("rate_6040")
    cfg = d.get("config") or {}
    return "\n".join([
        "# pump.fun realistic paper", "",
        d["calibration"]["line"], "",
        f"The model every pipeline paper book trades by (lab/pumpfun_rt/realistic.py), fitted "
        f"{datetime.fromtimestamp(d['updated_ms'] / 1000, timezone.utc):%Y-%m-%d %H:%M} UTC from the live bot's "
        f"orders of the last {FIT_DAYS} days ({(f.live or {}).get('buys', 0)} buys, {(f.live or {}).get('sells', 0)} "
        f"sales; a side with fewer than {MIN_ORDERS} takes the fixed fallback).", "",
        "| what | model | source |", "|---|---|---|",
        f"| buy, signal to landing | {ms(f.buy)} | {src.get('buy', 'fallback')} |",
        f"| sale, decision to landing | {ms(f.sell)} | {src.get('sell', 'fallback')} |",
        f"| buy, send to landing (the pre-send check) | {ms(f.send)} | {src.get('send', 'fallback')} |",
        f"| network fee per transaction | {f.fee_l / C.LAMPORTS:.6f} SOL, Sender tip {f.tip_l / C.LAMPORTS:.6f} SOL "
        f"| {'live' if (f.live or {}).get('fees', 0) >= MIN_ORDERS else 'fallback'} |",
        f"| buy failures drawn per buy | {fails} | {src.get('fail', 'fallback')} |",
        f"| live 6040 rate per buy (modelled by the 60 % bound, not drawn) | "
        f"{'n/a' if r6 is None else f'{r6 * 100:.1f} %'} | live |", "",
        f"Paper wallet {START_SOL} SOL per book; sizing as live: limits {'wallet' if cfg.get('wallet') else 'fixed'}, "
        f"share {cfg.get('share', Z.SHARE) * 100:g} %, brake {'on' if cfg.get('brake', True) else 'off'}, floor "
        f"{cfg.get('floor_sol') if cfg.get('floor_sol') is not None else Z.PAUSE_BELOW_SOL} SOL, at most "
        f"{cfg.get('max_open', P.HARD_MAX_OPEN)} open, reserve {RESERVE_SOL} SOL.", "",
        *small_md(d.get("small") or [], d.get("sol_eur"))])


# ---------------------------------------------------------------- R1: the headline strategies, ideal and realistic

HEADLINE = (("P_pool0", "Y6"), ("P_pool0_wait", "Y8"), ("P_pool0_norug", "Y9"), ("P_pool0_top30", "Y9"),
            ("P_pool0_norug_top30", "Y9"), ("P_pool5_top30", "Y9"), ("P_pool0_smart2", "Y9"),
            ("P_pool0_wait_run20", "Y11"), ("P_pool0_wait_run20w", "Y11"), ("P_pool0_wait_lock", "Y12"),
            ("P_pool0_wait_lock_tight", "Y12"), ("P_pool0_wait_lock_half", "Y12"), ("P_pool0_wait_free10", "Y15"),
            ("P_pool0_wait_free30", "Y15"), ("P_pool0_wait_free_any", "Y15"), ("P_pool0_wait_free10_tight", "Y15"))
R1_STAKE_SOL = 0.1
R1_LIMITS = P.Limits(R1_STAKE_SOL, 4, P.HARD_MAX_EXPOSURE_SOL, P.HARD_MAX_DAILY_LOSS_SOL)
R1_CALIB_LIMITS = P.Limits(R1_STAKE_SOL, 1_000, math.inf, math.inf)
R1_TAIL_MS = 15 * 60_000
R1_KINDS = {"I": "ideal (old paper model, 0.1 SOL)", "R": "realistic fills, 0.1 SOL",
            "W": f"realistic, live sizing from {START_SOL} SOL"}


def run_r1(root=None, until_ms: int | None = None, log=print, model: Model | None = None) -> dict:
    """One replay of the record with three books per headline strategy (I the old model at 0.1 SOL, at most 4 open;
    R the realistic fills at 0.1 SOL, at most 4 open; W realistic with the live sizing on a START_SOL wallet) and the
    calibration books (P_pool0_wait realistic and ideal at 0.1 SOL without a slot, exposure or loss limit: every coin
    the strategy signals, so each of the live bot's coins has its paper trade). The Y9 filters on Y9's walk-forward
    models (select9: trained at the end of each day for the next), so they trade from the second recorded day; every
    book draws its latency with its strategy's own key. The fit: the live orders of the FIT_DAYS days to the cutoff."""
    from . import early as EA
    from . import select9 as S9
    from . import selfeat as SF
    from . import selmodel as SM
    from . import sim, store
    from . import wallets as W
    from .study import WARM_DAYS, WINDOW_DAYS, span_of, warm_book
    from datetime import timedelta
    model = model or Model(fit(_measured(), until_ms or int(time.time() * 1000)))   # the live orders up to the cutoff
    all_days = [d for d in store.days(root) if until_ms is None or d <= SF.day_of(until_ms)]
    days = all_days[-WINDOW_DAYS:]
    if not days:
        return {"empty": True}
    warm = [d for d in all_days if d < days[0]][-WARM_DAYS:]
    t_lo, t_hi = span_of(days, root)
    t_hi = t_hi if until_ms is None else min(t_hi, until_ms)
    log(f"r1: {len(days)} day(s) {days[0]} to {days[-1]}, warm-up {len(warm)}")
    t0 = time.time()
    eng = sim.Engine([], book=warm_book(warm, root), decisions=False, entry_until=t_hi - R1_TAIL_MS,
                     wallets=W.warm(warm, root), snipers=EA.warm_snipers(warm, root), select=True)
    dm = S9.DayModels()
    dm.eng = eng
    eng.models = dm
    lab = eng.add_pipe(SF.LabelPipe(eng, S9.scenarios()["B"]))
    pipes = {}
    for name, _ in HEADLINE:
        s = P.BY_NAME[name]
        v = {k: dataclasses.replace(s, name=f"{name}@{k}", p={**s.p, "base": name}, stake_sol=R1_STAKE_SOL)
             for k in ("I", "R")}
        pipes[v["I"].name] = eng.add_pipe(P.Pipeline(eng, [v["I"]], P.PaperExecutor(), limits=R1_LIMITS,
                                                     name=v["I"].name))
        eng.rule_costs[v["R"].name] = RealCosts(model=model)
        pipes[v["R"].name] = eng.add_pipe(Book(eng, [v["R"]], RealExecutor(model), limits=R1_LIMITS,
                                               name=v["R"].name))
        w = realistic(dataclasses.replace(s, name=f"{name}@W", p={**s.p, "base": name}))
        eng.rule_costs[w.name] = RealCosts(model=model)
        pipes[w.name] = eng.add_pipe(Book(eng, [w], RealExecutor(model, PaperWallet()), name=w.name))
    s = P.BY_NAME[TWIN]
    cb = dataclasses.replace(s, name=f"{TWIN}@C", p={**s.p, "base": TWIN}, stake_sol=R1_STAKE_SOL)
    eng.rule_costs[cb.name] = RealCosts(model=model)
    cb_i = dataclasses.replace(cb, name=f"{TWIN}@CI")
    pipes[cb.name] = eng.add_pipe(Book(eng, [cb], RealExecutor(model), name=cb.name))
    pipes[cb_i.name] = eng.add_pipe(P.Pipeline(eng, [cb_i], P.PaperExecutor(), name=cb_i.name))
    for n in (cb.name, cb_i.name):                          # a measuring book: no slot, exposure or loss limit
        pipes[n].risk[n].limits = R1_CALIB_LIMITS
    trained = {}

    def next_day(day: str, n: int) -> None:
        nd = (datetime.strptime(day, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
        ms = SM.train(lab.table(), until_ms=SM.day_start(nd))
        dm.by_day[nd] = ms
        trained[nd] = [k for k in SM.LABELS if ms["sel_" + k].booster is not None]
        log(f"r1: {day} done ({n:,} events, {time.time() - t0:.0f} s); models for {nd}: {trained[nd]}")
    sim.replay(days, eng, root, progress=next_day, until_ms=t_hi)
    log(f"r1: replay in {time.time() - t0:.0f} s")
    ent = {}
    for n, p in pipes.items():
        e = [dict(t, failed=False) for t in p.closed]
        e += [{"mint": f["mint"], "signal_ms": f["signal_ms"], "exit_ms": f["land_ms"], "pnl_sol": f["pnl_sol"],
               "ret": f["pnl_sol"] / R1_STAKE_SOL, "failed": True, "why": f["why"]} for f in p.failed]
        ent[n] = sorted(e, key=lambda x: x["exit_ms"])
    wallets = {n: {"pnl_sol": p.exec.wallet.pnl_l / C.LAMPORTS, "trades": p.exec.wallet.n,
                   "refills": p.exec.wallet.refills}
               for n, p in pipes.items() if isinstance(p, Book) and p.exec.wallet is not None}
    return {"days": days, "span": (t_lo, t_hi), "entries": ent, "wallets": wallets, "trained": trained,
            "skipped": {f"{k[0]}: {k[1]}": v for k, v in eng.skipped.items() if "@" in k[0]},
            "gaps": list(eng.gaps), "fit": model.fit.to_json(), "config": model.cfg.to_json()}


def _measured() -> list[dict]:
    from . import measure
    from .live_exec import data_dir
    return measure.read_measured(data_dir() / "measured.jsonl")


def book_stats(e: list[dict]) -> dict:
    """Entries (closed trades and failed buys; a failed buy or a pre-send skip is an entry that lost its fee),
    their mean and median return, the P&L in SOL, the win share, the largest fall of the P&L and the failures."""
    out = {"n": len(e), "failed": sum(1 for x in e if x["failed"])}
    if not e:
        return out
    from .exitlab import max_drawdown
    trades = [x for x in e if not x["failed"]]
    r = np.array([x["ret"] for x in trades]) if trades else np.array([])
    pnl = np.array([x["pnl_sol"] for x in e])
    out.update(trades=len(trades), mean=float(r.mean()) if len(r) else None,
               median=float(np.median(r)) if len(r) else None, pnl_sol=float(pnl.sum()),
               win=float((r > 0).mean()) if len(r) else None, max_dd_sol=max_drawdown(list(pnl)),
               stake=float(np.median([x.get("stake_sol") or R1_STAKE_SOL for x in trades])) if trades else None,
               fails={k: sum(1 for x in e if x["failed"] and _why(x) == k) for k in
                      sorted({_why(x) for x in e if x["failed"]})})
    return out


def _why(x: dict) -> str:
    w = x.get("why") or ""
    return RAN_AWAY if w.startswith(RAN_AWAY + " (") else w


def r1_markdown(res: dict, cal: dict, cal_i: dict) -> str:
    def pc(x):
        return "" if x is None else f"{x * 100:+.1f} %"

    def sol(x):
        return "" if x is None else f"{x:+.3f}"
    f = Fit.from_json(res["fit"])
    lines = ["| study | strategy | ideal n | ideal mean | ideal P&L SOL | realistic n | realistic mean | "
             "realistic P&L SOL | failed or skipped at the buy | live sizing: trades | P&L SOL | top-ups to "
             f"{START_SOL} SOL |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for name, study in HEADLINE:
        a, b, w = (book_stats(res["entries"][f"{name}@{k}"]) for k in ("I", "R", "W"))
        ww = res["wallets"].get(f"{name}@W") or {}
        lines.append(f"| {study} | {name} | {a.get('trades', 0)} | {pc(a.get('mean'))} | {sol(a.get('pnl_sol'))} | "
                     f"{b.get('trades', 0)} | {pc(b.get('mean'))} | {sol(b.get('pnl_sol'))} | {b['failed']} | "
                     f"{w.get('trades', 0)} | {sol(ww.get('pnl_sol'))} | {ww.get('refills', 0)} |")
    return "\n".join([
        f"Record {res['days'][0]} to {res['days'][-1]} "
        f"({datetime.fromtimestamp(res['span'][0] / 1000, timezone.utc):%Y-%m-%d %H:%M} to "
        f"{datetime.fromtimestamp(res['span'][1] / 1000, timezone.utc):%Y-%m-%d %H:%M} UTC). Fit: buy "
        f"{describe(f.buy)['median'] / 1000:.1f} s, sale {describe(f.sell)['median'] / 1000:.1f} s median, fee "
        f"{f.fee_l / C.LAMPORTS:.6f} + tip {f.tip_l / C.LAMPORTS:.6f} SOL; {(f.live or {}).get('buys', 0)} live buys, "
        f"{(f.live or {}).get('sells', 0)} sales.", "", *lines, "",
        "Calibration on the record (the live bot's P_pool0_wait trades against the paper books on the same coins, "
        "0.1 SOL, no slot or loss limit):", "",
        "| paper model | matched | entry price, paper over live | exit price | P&L median, points | P&L mean, points "
        "| live mean | paper mean |", "|---|---|---|---|---|---|---|---|",
        *[f"| {lab} | {c['n']} | {pc(c['d_entry'])} | {pc(c['d_exit'])} | "
          f"{'' if c['d_pts'] is None else format(c['d_pts'], '+.1f')} | "
          f"{'' if c['d_pts_mean'] is None else format(c['d_pts_mean'], '+.1f')} | {pc(c['live_mean'])} | "
          f"{pc(c['paper_mean'])} |" for lab, c in (("realistic", cal), ("ideal (old)", cal_i))], ""])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="lab.pumpfun_rt.realistic")
    ap.add_argument("cmd", nargs="?", default="daily", choices=("daily", "run"))
    ap.add_argument("--out", default=None)
    ap.add_argument("--until", default=None, help="run: replay up to this UTC time (YYYY-MM-DDTHH:MM)")
    a = ap.parse_args(sys.argv[1:] if argv is None else argv)
    if a.cmd == "daily":
        d = daily()
        print(markdown(d))
        return 0
    until = int(datetime.strptime(a.until, "%Y-%m-%dT%H:%M").replace(tzinfo=timezone.utc).timestamp() * 1000) \
        if a.until else None
    res = run_r1(until_ms=until)
    if res.get("empty"):
        print("r1: no recorded days")
        return 1
    from .live_exec import data_dir
    live = read_csv(data_dir() / "ledger.csv")
    lo, hi = res["span"]
    cal = calibrate(live, [dict(t, rule=TWIN) for t in res["entries"][f"{TWIN}@C"] if not t["failed"]], lo, hi)
    cal_i = calibrate(live, [dict(t, rule=TWIN) for t in res["entries"][f"{TWIN}@CI"] if not t["failed"]], lo, hi)
    md = r1_markdown(res, cal, cal_i)
    print(md)
    out = Path(a.out) if a.out else reports_dir()
    out.mkdir(parents=True, exist_ok=True)
    (out / "realistic_r1.md").write_text(md, encoding="utf-8")
    keep = {k: v for k, v in res.items() if k != "entries"}
    keep["stats"] = {n: book_stats(e) for n, e in res["entries"].items()}
    keep["calibration"] = {"realistic": cal, "ideal": cal_i}
    (out / "realistic_r1.json").write_text(json.dumps(keep, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
