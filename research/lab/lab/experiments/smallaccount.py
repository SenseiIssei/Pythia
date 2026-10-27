"""S1: the lab's long-only strategies with 50, 100 and 500 EUR at what Kraken and Jupiter really charge.

Pre-registered in results/smallaccount_s1_prereg.md; results in results/smallaccount_s1.md.

    python -m lab.experiments.smallaccount --snapshot   record the costs: Kraken's EUR pairs (ordermin,
                                                        costmin, lot decimals, bid and ask) and a Jupiter
                                                        quote ladder 5 to 500 USD, into results/*.csv
    python -m lab.experiments.smallaccount              the study on the sweep's daily panel (cached;
                                                        run it under the heavy lock)

The sweep charges 15 or 41 bps per unit of turnover and fills any order. Here a
wallet of cash and coin units in EUR is stepped day by day: every order pays
the venue's fee and spread (Kraken) or route cost and network fee (Jupiter),
an order under the venue's minimum is not sent, a position under it cannot be
sold (dust), units are rounded to the pair's lot. The same wallet code steps
the two paper books (lab.paper.smallaccount).

Venues (Venue below):
  kraken   Kraken Pro, lowest tier, the coin's EUR pair: taker 40 bps plus the
           snapshot's half spread; maker 25 bps and no spread as a sensitivity
           (every order filled, optimistic). Minimum max(ordermin x price,
           costmin) in EUR at the snapshot.
  jupiter  a USDC wallet on Solana: half the recorded round trip at the order's
           size, the network fee (5,000 lamports plus 0.0001 SOL priority) at
           the day's SOL price, MIN_TRADE 5 USDC, a SOL reserve held idle and
           the way there once (EUR to USDC at Kraken's taker fee, 1 USDC to
           withdraw, assumed).

Everything in USD is converted to EUR at the snapshot's EUR/USD mid for the whole
history. Coins a venue does not list today are cash, in the past too.
"""

from __future__ import annotations

import csv
import json
import math
import sys
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from . import fam_common as fc

NAME = "smallaccount_s1"
RESULTS = Path(__file__).resolve().parents[2] / "results"
KRAKEN_CSV = RESULTS / "smallaccount_kraken_pairs.csv"
JUPITER_CSV = RESULTS / "smallaccount_jupiter_quotes.csv"
CUT = "2026-10-21"
IS_FROM, OOS_FROM = "2020-08-01", "2024-01-01"
CAPITALS = (50.0, 100.0, 500.0)
LADDER = (25.0, 50.0, 100.0, 250.0, 500.0, 1_000.0, 2_500.0, 10_000.0)
CADENCES = {"daily": 1, "3 days": 3, "weekly": 7}
ANCHOR_US = int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp() * 1e6)
KRAKEN_TAKER, KRAKEN_MAKER = 0.0040, 0.0025
IDEAL_COST = 0.0041                 # the sweep's Kraken cost per unit of turnover, any size filled
KRAKEN_BASES = {"XBT": "BTC", "XDG": "DOGE"}
KRAKEN_API = "https://api.kraken.com/0/public"
JUP_RUNGS = (5.0, 10.0, 25.0, 50.0, 100.0, 250.0, 500.0)
JUP_MIN_TRADE_USD = 5.0             # lab.onchain.book.MIN_TRADE
SWAP_FEE_SOL = 0.000005 + 0.0001    # base fee plus lab.onchain.paper's priority fee
SOL_FEE_RESERVE, RENT_SOL = 0.01, 0.00204
ONRAMP_FEE, ONRAMP_WITHDRAW_USD = KRAKEN_TAKER, 1.0
DOMINATE = 0.5                      # costs at or above this share of the return before costs dominate
CAGR_SLACK = 0.02                   # capital needed: within 2 percentage points of the 10,000 EUR run
TRIALS = 8                          # the candidates; the trial registry counts the 61 configurations (R5)


# ---------------------------------------------------------------- the snapshot

def _get_json(url: str, timeout: float = 20.0) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "pythia-lab"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def kraken_base(wsname: str) -> str:
    b = wsname.split("/")[0]
    return KRAKEN_BASES.get(b, b)


def kraken_rows(pairs: dict, tickers: dict) -> list[dict]:
    """One row per EUR pair from Kraken's AssetPairs and Ticker answers (their `result`), plus EUR/USD."""
    out = []
    for key, p in sorted(pairs.items()):
        ws = str(p.get("wsname") or "")
        if not (ws.endswith("/EUR") or ws == "EUR/USD") or p.get("status", "online") != "online":
            continue
        t = tickers.get(key) or tickers.get(p.get("altname", "")) or {}
        try:
            ask, bid = float(t["a"][0]), float(t["b"][0])
        except (KeyError, IndexError, TypeError, ValueError):
            continue
        if not (ask > 0 and bid > 0 and ask >= bid):
            continue
        out.append({"coin": "EURUSD" if ws == "EUR/USD" else kraken_base(ws), "pair": ws,
                    "ordermin": float(p.get("ordermin") or 0), "costmin": float(p.get("costmin") or 0),
                    "lot_decimals": int(p.get("lot_decimals") or 8), "bid": bid, "ask": ask})
    return out


def jupiter_rows(client, coins: dict, usdc, rungs=JUP_RUNGS) -> list[dict]:
    """USDC -> coin -> USDC at every rung: half the round trip in bps, Jupiter's impact and the route."""
    from ..onchain import mints as M
    from ..onchain.jupiter import QuoteError
    out = []
    for coin, m in coins.items():
        for usd in rungs:
            try:
                q = client.quote(usdc.mint, m.mint, M.raw(usdc, usd))
                back = client.quote(m.mint, usdc.mint, q.out_amount)
            except QuoteError as e:
                print(f"  {coin} {usd:g}: {e}", file=sys.stderr)
                continue
            out.append({"coin": coin, "usd": usd, "half_rt_bps": round((1 - back.out_amount / q.in_amount) / 2 * 1e4, 3),
                        "impact_pct": q.price_impact_pct, "route": "+".join(q.labels)})
    return out


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def snapshot() -> None:
    from ..onchain import mints as M
    from ..onchain.jupiter import Jupiter
    pairs = _get_json(f"{KRAKEN_API}/AssetPairs")["result"]
    tickers = _get_json(f"{KRAKEN_API}/Ticker")["result"]
    rows = kraken_rows(pairs, tickers)
    write_csv(KRAKEN_CSV, rows)
    print(f"{len(rows)} Kraken EUR pairs -> {KRAKEN_CSV.name}")
    rows = jupiter_rows(Jupiter(), M.COINS, M.USDC)
    write_csv(JUPITER_CSV, rows)
    print(f"{len(rows)} Jupiter quotes -> {JUPITER_CSV.name}")


def read_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


# ---------------------------------------------------------------- the venues

@dataclass
class Venue:
    """What a venue charges and refuses. Amounts in EUR; `sol_eur` is the day's SOL price in EUR."""
    name: str
    eurusd: float
    kraken: dict = field(default_factory=dict)      # coin -> its EUR pair's row
    ladder: dict = field(default_factory=dict)      # coin -> [(usd, half round trip bps)]
    maker: bool = False
    ideal: float | None = None                      # a flat cost per unit traded, no minimum, no lot

    def tradable(self, coin: str) -> bool:
        if self.ideal is not None:
            return True
        return coin in (self.ladder if self.name == "jupiter" else self.kraken)

    def min_eur(self, coin: str) -> float:
        if self.ideal is not None:
            return 0.0
        if self.name == "jupiter":
            return JUP_MIN_TRADE_USD / self.eurusd
        k = self.kraken[coin]
        mid = (k["bid"] + k["ask"]) / 2
        return max(k["ordermin"] * mid, k["costmin"])

    def lot(self, coin: str, units: float) -> float:
        if self.ideal is not None or self.name == "jupiter":
            return units
        q = 10 ** int(self.kraken[coin]["lot_decimals"])
        return math.floor(units * q + 1e-9) / q

    def half_rt_bps(self, coin: str, usd: float) -> float:
        rungs = self.ladder[coin]
        if usd <= rungs[0][0]:
            return rungs[0][1]
        if usd >= rungs[-1][0]:
            return rungs[-1][1] * math.sqrt(usd / rungs[-1][0])
        for (u0, c0), (u1, c1) in zip(rungs, rungs[1:]):
            if usd <= u1:
                x = math.log(usd / u0) / math.log(u1 / u0)
                return c0 + x * (c1 - c0)
        return rungs[-1][1]

    def cost(self, coin: str, eur: float, sol_eur: float) -> float:
        """What an order of `eur` costs in EUR beyond the mid."""
        if self.ideal is not None:
            return eur * self.ideal
        if self.name == "jupiter":
            return eur * max(self.half_rt_bps(coin, eur * self.eurusd), 0.0) / 1e4 + SWAP_FEE_SOL * sol_eur
        if self.maker:
            return eur * KRAKEN_MAKER
        k = self.kraken[coin]
        return eur * (KRAKEN_TAKER + (k["ask"] - k["bid"]) / (k["ask"] + k["bid"]))

    def setup(self, capital: float, slots: int, sol_eur: float) -> tuple[float, float]:
        """(EUR held idle, EUR paid once) before the first trade."""
        if self.ideal is not None or self.name != "jupiter":
            return 0.0, 0.0
        reserve = (SOL_FEE_RESERVE + RENT_SOL * (slots + 1)) * sol_eur
        return reserve, capital * ONRAMP_FEE + ONRAMP_WITHDRAW_USD / self.eurusd


def venues(kraken_csv: Path = KRAKEN_CSV, jupiter_csv: Path = JUPITER_CSV) -> dict[str, Venue]:
    rows = read_csv(kraken_csv)
    kr = {r["coin"]: {"pair": r["pair"], "ordermin": float(r["ordermin"]), "costmin": float(r["costmin"]),
                      "lot_decimals": int(r["lot_decimals"]), "bid": float(r["bid"]), "ask": float(r["ask"])}
          for r in rows}
    fx = kr.pop("EURUSD")
    eurusd = (fx["bid"] + fx["ask"]) / 2
    lad: dict[str, list] = {}
    for r in read_csv(jupiter_csv):
        lad.setdefault(r["coin"], []).append((float(r["usd"]), float(r["half_rt_bps"])))
    lad = {c: sorted(v) for c, v in lad.items()}
    return {"kraken": Venue("kraken", eurusd, kraken=kr),
            "kraken maker": Venue("kraken", eurusd, kraken=kr, maker=True),
            "jupiter": Venue("jupiter", eurusd, ladder=lad),
            "ideal": Venue("ideal", eurusd, ideal=IDEAL_COST)}


# ---------------------------------------------------------------- the wallet

def ffill(W: np.ndarray) -> np.ndarray:
    """The target each coin has at each close: the last row that set it (NaN means leave), 0 before."""
    T = W.shape[0]
    idx = np.where(np.isnan(W), -1, np.arange(T)[:, None])
    idx = np.maximum.accumulate(idx, axis=0)
    out = W[np.maximum(idx, 0), np.arange(W.shape[1])[None, :]]
    return np.where(idx < 0, 0.0, out)


def rebalance_day(day_us: int, every: int) -> bool:
    return ((int(day_us) - ANCHOR_US) // fc.DAY_US) % every == 0


@dataclass
class Wallet:
    """Cash and coin units in EUR. `pending` holds each coin's target at its last decision."""
    cash: float
    units: dict = field(default_factory=dict)
    last: dict = field(default_factory=dict)
    idle: float = 0.0
    costs: float = 0.0
    orders: int = 0
    skipped: int = 0
    dust: int = 0

    def value(self, prices: dict) -> float:
        return self.cash + self.idle + sum(u * prices.get(c, 0.0) for c, u in self.units.items())

    def trade_equity(self, prices: dict) -> float:
        return self.cash + sum(u * prices.get(c, 0.0) for c, u in self.units.items())


def rebalance(w: Wallet, targets: dict, prices: dict, venue: Venue, sol_eur: float,
              coin_of=lambda k: k, can_trade=lambda k: True) -> list[dict]:
    """Trade the coins whose target changed since the last decision (sales first, then buys out of
    the cash); targets are weights of the wallet's trading equity. Returns the fills. A coin that
    cannot be traded today or whose order is under the minimum keeps its old decision, so it is
    tried again at the next rebalance."""
    eq = w.trade_equity(prices)
    fills = []
    sells, buys = [], []
    for k, tgt in targets.items():
        if not can_trade(k) or k not in prices or not prices[k] > 0:
            continue
        if not venue.tradable(coin_of(k)):
            tgt = 0.0
        if w.last.get(k) == tgt:
            continue
        have = w.units.get(k, 0.0) * prices[k]
        diff = tgt * eq - have
        if diff < 0 and have > 0:
            sells.append((k, tgt, -diff, have))
        elif diff > 0:
            buys.append((k, tgt, diff))
        else:
            w.last[k] = tgt
    for k, tgt, eur, have in sells:
        coin, px, mn = coin_of(k), prices[k], venue.min_eur(coin_of(k))
        if have < mn:
            w.dust += 1                                 # cannot be sold at all: stuck until the target moves
            w.last[k] = tgt
            continue
        if have - eur < mn or tgt == 0:
            eur = have
        elif eur < mn:
            w.skipped += 1
            continue
        u = w.units[k] if eur >= have else venue.lot(coin, eur / px)
        if u <= 0:
            w.skipped += 1
            continue
        eur = u * px
        c = venue.cost(coin, eur, sol_eur)
        w.units[k] -= u
        if w.units[k] <= 1e-12 or eur >= have:
            w.units.pop(k, None)
        w.cash += eur - c
        w.costs += c
        w.orders += 1
        w.last[k] = tgt
        fills.append({"key": k, "side": "sell", "eur": eur, "cost": c, "units": u, "price": px})
    want = [(k, tgt, eur) for k, tgt, eur in buys if eur >= venue.min_eur(coin_of(k))]
    w.skipped += len(buys) - len(want)
    need = sum(eur for _, _, eur in want) * 1.01
    scale = min(1.0, max(w.cash, 0.0) / need) if need > 0 else 1.0
    for k, tgt, eur in want:
        coin, px = coin_of(k), prices[k]
        eur *= scale
        if eur < venue.min_eur(coin):
            w.skipped += 1
            continue
        c = venue.cost(coin, eur, sol_eur)
        u = venue.lot(coin, (eur - c) / px)
        if u <= 0:
            w.skipped += 1
            continue
        spent = u * px + c
        w.units[k] = w.units.get(k, 0.0) + u
        w.cash -= spent
        w.costs += c
        w.orders += 1
        w.last[k] = tgt
        fills.append({"key": k, "side": "buy", "eur": u * px, "cost": c, "units": u, "price": px})
    return fills


def simulate(P: fc.Panel, W: np.ndarray, venue: Venue, capital: float, t0: int, t1: int, every: int = 1,
             slots: int = 1) -> dict:
    """The wallet from the close of day t0 (all cash) to the close of day t1, trading at the closes."""
    cols = np.flatnonzero(np.nan_to_num(np.abs(W)).sum(0) > 0)
    Wf = ffill(W[:, cols])
    px = P.px[:, cols] / venue.eurusd
    names = [P.names[j] for j in cols]
    coins = {n: fc.base_of(n) for n in names}
    sol = P.col("SOLUSDT") if "SOLUSDT" in P.names else None
    sol_eur = lambda t: float(P.px[t, sol]) / venue.eurusd if sol is not None and np.isfinite(P.px[t, sol]) else 0.0
    # A reused ticker's old segment is another asset: no venue lists it today.
    tradable = lambda n: "~" not in n
    w = Wallet(cash=capital)
    idle, once = venue.setup(capital, slots, sol_eur(t0) or 100.0 / venue.eurusd)
    w.cash -= idle + once
    w.idle, w.costs = idle, once
    eq = np.zeros(t1 - t0 + 1)
    for i, t in enumerate(range(t0, t1 + 1)):
        prices = {n: float(px[t, j]) for j, n in enumerate(names) if np.isfinite(px[t, j])}
        # A coin whose series ends here is sold at its last close, minimum or not.
        for j, n in enumerate(names):
            if n in w.units and (t + 1 >= P.T or not P.alive[t + 1, cols[j]]) and n in prices:
                eur = w.units.pop(n) * prices[n]
                c = venue.cost(coins[n], eur, sol_eur(t)) if venue.tradable(coins[n]) else 0.0
                w.cash += eur - c
                w.costs += c
                w.orders += 1
                w.last[n] = 0.0
        if rebalance_day(P.days[t], every):
            tg = {n: (float(Wf[t, j]) if tradable(n) else 0.0) for j, n in enumerate(names)}
            rebalance(w, tg, prices, venue, sol_eur(t), coin_of=coins.get,
                      can_trade=lambda n: bool(P.traded[t, cols[names.index(n)]]))
        eq[i] = w.value(prices)
    return {"equity": eq, "costs": w.costs, "orders": w.orders, "skipped": w.skipped, "dust": w.dust}


def measure(res: dict, capital: float) -> dict:
    eq = res["equity"]
    r = eq[1:] / eq[:-1] - 1
    p = fc.perf(np.r_[eq[0] / capital - 1, r])
    years = max(len(eq) / 365, 1e-9)
    profit = eq[-1] - capital
    gross = profit + res["costs"]
    return {"cagr": p["cagr"], "max_dd": p["max_dd"], "sharpe": p["sharpe"], "end_eur": float(eq[-1]),
            "costs_eur": float(res["costs"]), "cost_share": float(res["costs"] / gross) if gross > 0 else None,
            "orders_yr": res["orders"] / years, "skipped_yr": res["skipped"] / years, "dust": res["dust"]}


# ---------------------------------------------------------------- the candidates

def _breakout(P: fc.Panel, allowed: np.ndarray, n: int, slots: int, regime: bool) -> np.ndarray:
    from .fam_breakout import breakout_weights
    return breakout_weights(P, np.flatnonzero(allowed.any(0)), allowed, n, slots, regime)


def sol_member(P: fc.Panel) -> np.ndarray:
    from ..onchain import mints as M
    return np.array([fc.base_of(n) in M.COINS and "~" not in n for n in P.names])


def candidate(P: fc.Panel, key: str, n: int | None = None) -> np.ndarray:
    """The candidate's weight matrix on n coins (None: as the lab runs it)."""
    from . import alpaca_universe as au
    from . import memecoins as w7
    from .fam_volmom import base_weights
    if key in ("btc_hold", "btc_gated"):
        W = np.zeros((P.T, P.N))
        W[:, P.btc] = 1.0 if key == "btc_hold" else P.btc_on.astype(float)
        return W
    if key == "breakout_btceth":
        n = n or 2
        cols = [P.col("BTCUSDT"), P.col("ETHUSDT")][:n]
        allowed = np.zeros((P.T, P.N), dtype=bool)
        allowed[:, cols] = P.eligible[:, cols]
        return _breakout(P, allowed, 55, n, True)
    if key == "breakout_top10":
        n = n or 10
        return _breakout(P, P.top_liquid(n), 20, n, False)
    if key == "breakout_sol":
        n = n or 10
        return _breakout(P, au.top_within(P, sol_member(P), n), 20, n, False)
    if key == "tsmom_top20":
        return base_weights(P, n or 20, regime=True)
    if key == "trend_carry":
        f7 = fc.rolling(np.where(P.perp_ok, P.funding, np.nan), 7, 5, how="sum")
        top20 = P.top_liquid(20)
        crowded = np.nan_to_num(fc.xs_rank(f7, top20 & np.isfinite(f7)), nan=0) > 2 / 3
        return np.where(crowded, 0.0, base_weights(P, n or 20, regime=True))
    if key == "memes_rotation":
        return w7.rotation(P, P.eligible & w7.member(P, w7.ALPACA_MEMES)[None, :], 1)
    raise KeyError(key)


CANDIDATES = {
    "btc_hold": ("BTC bought once and held (reference)", (None,)),
    "btc_gated": ("BTC above its 200-day average, cash below", (None,)),
    "breakout_btceth": ("Donchian 55/27 on BTC and ETH, regime", (1, None)),
    "breakout_top10": ("Donchian 20/10, the most liquid coins", (1, 3, 5, None)),
    "breakout_sol": ("Donchian 20/10, coins with a Solana mint", (1, 3, 5, None)),
    "tsmom_top20": ("28d momentum, the most liquid coins, regime", (1, 3, 5, None)),
    "trend_carry": ("28d momentum without crowded funding, regime", (1, 3, 5, None)),
    "memes_rotation": ("the best of six memecoins by 28d return, BTC gate", (None,)),
}
ORIGINAL_N = {"btc_hold": 1, "btc_gated": 1, "breakout_btceth": 2, "breakout_top10": 10, "breakout_sol": 10,
              "tsmom_top20": 20, "trend_carry": 20, "memes_rotation": 1}


def variant_label(key: str, n: int | None, cadence: str) -> str:
    return f"{key} · {n or ORIGINAL_N[key]} coin{'s' if (n or ORIGINAL_N[key]) > 1 else ''} · {cadence}"


# ---------------------------------------------------------------- the study

def _t(P: fc.Panel, day: str) -> int:
    us = int(datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1e6)
    return int(np.searchsorted(P.days, us))


def windows(P: fc.Panel) -> dict[str, tuple[int, int]]:
    cut = min(_t(P, CUT), P.T - 1)
    oos = _t(P, OOS_FROM)
    return {"is": (_t(P, IS_FROM), oos - 1), "oos": (oos, cut)}


def run_grid(P: fc.Panel, vs: dict[str, Venue], capitals=CAPITALS) -> list[dict]:
    rows = []
    win = windows(P)
    for key, (_, ns) in CANDIDATES.items():
        for n in ns:
            W = candidate(P, key, n)
            slots = n or ORIGINAL_N[key]
            cads = {"daily": 1} if key == "btc_hold" else CADENCES
            for cad, every in cads.items():
                for vname in ("kraken", "jupiter", "ideal"):
                    for cap in (capitals if vname != "ideal" else (capitals[0],)):
                        row = {"key": key, "n": slots, "original": n is None, "cadence": cad, "venue": vname,
                               "capital": cap, "variant": variant_label(key, n, cad)}
                        for wname, (t0, t1) in win.items():
                            m = measure(simulate(P, W, vs[vname], cap, t0, t1, every, slots), cap)
                            row.update({f"{wname}_{k}": v for k, v in m.items()})
                        rows.append(row)
                print(f"  {variant_label(key, n, cad)}", flush=True)
    return rows


def pick(rows: list[dict], capital: float, exclude: set[str] = frozenset()) -> dict | None:
    """The pre-registered pick: the best in-sample Sharpe at the capital, btc_hold never."""
    c = [r for r in rows if r["capital"] == capital and r["venue"] != "ideal" and r["key"] != "btc_hold"
         and r["key"] not in exclude]
    return max(c, key=lambda r: r["is_sharpe"]) if c else None


def worth(rows: list[dict], capital: float) -> list[dict]:
    """Variants that pass the pre-registered bar at the capital: CAGR above 0, Sharpe above btc_hold's
    at the same capital and venue, cost share below DOMINATE."""
    hold = {r["venue"]: r["oos_sharpe"] for r in rows
            if r["key"] == "btc_hold" and r["capital"] == capital and r["venue"] != "ideal"}
    return sorted([r for r in rows if r["capital"] == capital and r["venue"] in hold and r["key"] != "btc_hold"
                   and r["oos_cagr"] > 0 and r["oos_sharpe"] > hold[r["venue"]]
                   and r["oos_cost_share"] is not None and r["oos_cost_share"] < DOMINATE],
                  key=lambda r: -r["oos_sharpe"])


def capital_needed(P: fc.Panel, rows: list[dict], vs: dict[str, Venue]) -> list[dict]:
    """Per candidate, its best cadence and coins by in-sample Sharpe at 10,000 EUR on Kraken taker,
    run along the ladder."""
    win = windows(P)
    out = []
    for key in CANDIDATES:
        best, best_s = None, -1e9
        for n in CANDIDATES[key][1]:
            W = candidate(P, key, n)
            for cad, every in ({"daily": 1} if key == "btc_hold" else CADENCES).items():
                s = measure(simulate(P, W, vs["kraken"], LADDER[-1], *win["is"], every, n or ORIGINAL_N[key]),
                            LADDER[-1])["sharpe"]
                if s > best_s:
                    best, best_s = (n, cad, every, W), s
        n, cad, every, W = best
        rungs = [{"capital": c, **measure(simulate(P, W, vs["kraken"], c, *win["oos"], every, n or ORIGINAL_N[key]), c)}
                 for c in LADDER]
        top = rungs[-1]["cagr"]
        ok = [r["cost_share"] is not None and r["cost_share"] < DOMINATE and r["cagr"] >= top - CAGR_SLACK
              for r in rungs]
        need = None
        for i in range(len(rungs)):
            if all(ok[i:]):
                need = rungs[i]["capital"]
                break
        out.append({"key": key, "variant": variant_label(key, n, cad), "rungs": rungs, "needed": need})
    return out


def _pct(v) -> str:
    return "n/a" if v is None else f"{v * 100:.1f} %"


def cost_table(vs: dict[str, Venue], coins=("BTC", "ETH", "SOL", "DOGE", "PEPE", "BONK", "WIF", "JUP")) -> list[dict]:
    """Per coin: Kraken's minimum and its cost per order, Jupiter's at 5, 25 and 100 USD (bps, network fee in)."""
    k, j = vs["kraken"], vs["jupiter"]
    sol_eur = (k.kraken["SOL"]["bid"] + k.kraken["SOL"]["ask"]) / 2 if "SOL" in k.kraken else 100.0
    out = []
    for c in coins:
        row = {"coin": c}
        if k.tradable(c):
            row["kraken_min_eur"] = f"{k.min_eur(c):.2f}"
            row["kraken_taker_bps"] = f"{k.cost(c, 100.0, sol_eur) / 100.0 * 1e4:.1f}"
        else:
            row["kraken_min_eur"] = row["kraken_taker_bps"] = "no EUR pair"
        for usd in (5.0, 25.0, 100.0):
            eur = usd / j.eurusd
            row[f"jup_{usd:g}usd_bps"] = f"{j.cost(c, eur, sol_eur) / eur * 1e4:.1f}" if j.tradable(c) else "no mint"
        out.append(row)
    return out


MARKER = "<!-- generated below by lab.experiments.smallaccount; edit above this line only -->"


def _num(v, digits: int = 2) -> str:
    return "n/a" if v is None else f"{v:.{digits}f}"


def _row(r: dict, w: str = "oos") -> dict:
    return {"CAGR": _pct(r[f"{w}_cagr"]), "max DD": _pct(r[f"{w}_max_dd"]), "Sharpe": _num(r[f"{w}_sharpe"]),
            "costs": _pct(r[f"{w}_cost_share"]), "orders/yr": f"{r[f'{w}_orders_yr']:.0f}",
            "not sent/yr": f"{r[f'{w}_skipped_yr']:.0f}", "dust": r[f"{w}_dust"]}


def probes(root: Path | None = None) -> list[dict]:
    """The on-chain paper book's own 100 USDC round trips (data/paper/onchain_breakout_top10_live/probes.csv)."""
    from ..data import ROOT
    p = (root or ROOT) / "paper" / "onchain_breakout_top10_live" / "probes.csv"
    try:
        return [{"coin": r["coin"], "date": r["date"], "half_rt_bps": f"{float(r['roundtrip_bps']) / 2:.1f}"}
                for r in read_csv(p)]
    except (OSError, KeyError, ValueError):
        return []


def markdown(res: dict) -> str:
    rows = res["rows"]
    md = [f"Generated {res['generated']}, panel cut {res['cut']}, EUR/USD {res['eurusd']:.4f} (Kraken mid). "
          "Out of sample 2024-01-01 to the cut unless a column says otherwise. `costs` is the share of the "
          "return before costs the costs took (n/a: no gain before costs); `not sent` orders under the "
          "venue's minimum; `dust` sales refused because the position was under the minimum.\n",
          "## 1. What one order costs (bps of the order, network fee included)\n",
          fc.table(res["costs"], list(res["costs"][0])),
          "Kraken: taker 40 bps plus the snapshot's half spread on the EUR pair; Jupiter: half the recorded "
          "round trip at that size plus 0.000105 SOL. The on-chain paper book's own 100 USDC probes, halved: "
          + (", ".join(f"{p['coin']} {p['half_rt_bps']}" for p in res.get("probes") or []) or "none recorded")
          + ".\n"]
    for venue, title in (("kraken", "Kraken taker"), ("jupiter", "Jupiter")):
        md.append(f"## 2{'a' if venue == 'kraken' else 'b'}. The rules as the lab runs them, daily, {title}\n")
        t = []
        for key in CANDIDATES:
            for r in rows:
                if r["key"] == key and r["original"] and r["cadence"] == "daily" and r["venue"] in (venue, "ideal"):
                    t.append({"candidate": key, "EUR": "41 bps, any size" if r["venue"] == "ideal" else f"{r['capital']:.0f}",
                              **_row(r)})
        md.append(fc.table(t, list(t[0])))
    md.append("## 3. Slower and fewer, at 50 and 100 EUR\n")
    by: dict[str, dict] = {}
    for r in rows:
        if r["venue"] != "ideal" and r["capital"] in (50.0, 100.0):
            row = by.setdefault(r["variant"], {"variant": r["variant"]})
            row["IS Sharpe (Kraken 50)"] = row.get("IS Sharpe (Kraken 50)", "")
            if r["venue"] == "kraken" and r["capital"] == 50.0:
                row["IS Sharpe (Kraken 50)"] = _num(r["is_sharpe"])
            row[f"{r['venue']} {r['capital']:.0f}"] = (f"{_pct(r['oos_cagr'])} / {_num(r['oos_sharpe'])} / "
                                                     f"{_pct(r['oos_cost_share'])} / {r['oos_orders_yr']:.0f}")
    t = list(by.values())
    md.append(fc.table(t, ["variant", "IS Sharpe (Kraken 50)", "kraken 50", "kraken 100", "jupiter 50", "jupiter 100"]))
    md.append("Each cell: CAGR / Sharpe / cost share / orders a year. Every capital and the in-sample numbers: "
              "reports/smallaccount_s1/latest.json.\n")
    md.append("## 4. Worth running (CAGR > 0, Sharpe above BTC held on the same venue, costs < 50 %)\n")
    for c, names in res["worth"].items():
        md.append(f"- {float(c):.0f} EUR: " + (", ".join(names[:8]) + (f" (+{len(names) - 8})" if len(names) > 8 else "")
                                               if names else "nothing"))
    md.append("\n## 5. Capital needed (Kraken taker, best cadence and coins in sample at 10,000 EUR)\n")
    t = []
    for c in res["capital_needed"]:
        row = {"variant": c["variant"], "needed": f"{c['needed']:,.0f} EUR" if c["needed"] else "never"}
        for r in c["rungs"]:
            row[f"{r['capital']:,.0f}"] = f"{_pct(r['cagr'])} / {_pct(r['cost_share'])}"
        t.append(row)
    md.append(fc.table(t, list(t[0])))
    md.append("Each rung: CAGR / cost share. Needed: the smallest rung from which every larger one keeps the "
              "costs under 50 % and the CAGR within 2 points of the 10,000 EUR run.\n")
    md.append("## 6. The two paper books (picked by in-sample Sharpe)\n")
    t = []
    for p in res["picks"]:
        if p:
            t.append({"book": f"{p['capital']:.0f} EUR", "variant": p["variant"], "venue": p["venue"],
                      "IS Sharpe": _num(p["is_sharpe"]), **_row(p)})
    for m in res["maker"]:
        t.append({"book": f"{m['capital']:.0f} EUR", "variant": m["variant"], "venue": "kraken maker (optimistic)",
                  "IS Sharpe": "", "CAGR": _pct(m["cagr"]), "max DD": _pct(m["max_dd"]), "Sharpe": _num(m["sharpe"]),
                  "costs": _pct(m["cost_share"]), "orders/yr": f"{m['orders_yr']:.0f}",
                  "not sent/yr": f"{m['skipped_yr']:.0f}", "dust": m["dust"]})
    if t:
        md.append(fc.table(t, list(t[0])))
    return "\n".join(md) + "\n"


def write(res: dict, path: Path = RESULTS / "smallaccount_s1.md") -> None:
    head = "# S1: the lab's strategies with 50, 100 and 500 EUR\n\n"
    if path.exists():
        old = path.read_text(encoding="utf-8")
        if MARKER in old:
            head = old.split(MARKER)[0]
    path.write_text(head + MARKER + "\n\n" + markdown(res), encoding="utf-8")


def main() -> int:
    if "--snapshot" in sys.argv:
        snapshot()
        return 0
    vs = venues()
    P = fc.load_panel()
    t0 = time.time()
    rows = run_grid(P, vs)
    need = capital_needed(P, rows, vs)
    a = pick(rows, 50.0)
    b = pick(rows, 100.0, {a["key"]}) if a else None
    maker = []
    win = windows(P)
    for p in (a, b):
        if p is None or p["venue"] != "kraken":
            continue
        W = candidate(P, p["key"], None if p["original"] else p["n"])
        m = measure(simulate(P, W, vs["kraken maker"], p["capital"], *win["oos"], CADENCES[p["cadence"]], p["n"]),
                    p["capital"])
        maker.append({"variant": p["variant"], "capital": p["capital"], **m})
    res = {"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "cut": CUT,
           "eurusd": vs["kraken"].eurusd, "rows": rows, "capital_needed": need, "picks": [a, b], "maker": maker,
           "costs": cost_table(vs), "probes": probes(),
           "worth": {str(c): [r["variant"] + " · " + r["venue"] for r in worth(rows, c)] for c in CAPITALS},
           "seconds": round(time.time() - t0)}
    from .. import report
    d = report.REPORTS / NAME
    d.mkdir(parents=True, exist_ok=True)
    (d / "latest.json").write_text(json.dumps(res, indent=1, default=float), encoding="utf-8")
    write(res)
    print(f"done in {res['seconds']} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
