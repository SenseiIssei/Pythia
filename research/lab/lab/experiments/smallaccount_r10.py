"""R10: S1's, S2's, L1's and F2's rules filled a close late, at the costs of their era, in EUR, against the right benchmark.

Pre-registered in results/smallaccount_r10_prereg.md; results in results/smallaccount_r10.md.

    python -m lab.experiments.smallaccount_r10 --snapshot   record the ECB's daily EUR/USD, the UCITS funds' Xetra
                                                            closes (Yahoo) and SPYx, QQQx and PAXG at 00:00 UTC
                                                            (CoinGecko) against Yahoo's last close, into results/
    python -m lab.experiments.smallaccount_r10              the study (run it under the heavy lock)
    python -m lab.experiments.smallaccount_r10 --kraken-fee the S1 rows again at Kraken's new-account fee,
                                                            validation only (results/kraken_fee_s1_prereg.md)

No new rule and nothing tuned: S1's two paper picks (S1's wallet), S2's five
candidates that are neither references nor tsmom1 (S2's wallet), L1's book with
its own rules (lab.onchain.longterm.simulate) and every genome F2 ever held back
(F2's wallet), each filled at the close its signal reads and one close late,
at 40 and 100 EUR, in sample 2020-08-01 to 2023-12-31 and over R6's validation
window 2024-01-01 to 2026-06-30 (the lockbox from 2026-07-01 is never read).

What changes against the studies (EraVenue and the way in and back below):
  every wallet runs in USD (USDC) and is worth its USD value at the day's ECB
  EUR/USD; the way in is EUR to USDC at Kraken (stablecoin fee, half spread, 1
  USDC to withdraw on chain), the way back at the last close sells every position
  at its era's cost and USDC to EUR at the same fee plus a SEPA fee; a swap costs
  today's recorded Jupiter quote only from the day the asset could be swapped
  on chain (ONCHAIN_FROM), before that Kraken's spot taker fee and half spread
  (the fees: lab.exec.kraken_fee, a new account's tier, results/kraken_fee_s1_prereg.md);
  the ETF tokens are their underlying's last close before 00:00 UTC (with S2's
  drift) times a draw of the token's measured deviation at 00:00 UTC, days
  without a US close drawing from the weekend's; crypto rules are judged
  against half BTC and half ETH held, the rest against a UCITS S&P 500 fund in
  EUR; the DSR of the late daily excess comes from R5's trial registry.
Nothing here signs, sends or holds a key.
"""

from __future__ import annotations

import io
import json
import math
import sys
import time
import zipfile
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from ..exec import kraken_fee as kf
from . import fam_common as fc
from . import smallaccount as s1
from . import smallaccount_s2 as s2

NAME = "smallaccount_r10"
RESULTS = s1.RESULTS
EURUSD_CSV = RESULTS / "smallaccount_r10_eurusd.csv"
UCITS_CSV = RESULTS / "smallaccount_r10_ucits.csv"
TOKENS_CSV = RESULTS / "smallaccount_r10_tokens_0000.csv"
ECB_ZIP = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.zip"
IS_FROM, VAL_FROM, VAL_TO = "2020-08-01", "2024-01-01", "2026-06-30"
CAPITALS = (40.0, 100.0)
MAIN = 40.0
JUPITER_FROM = "2021-10-01"                 # Jupiter's launch month: SOL, USDC, WETH and the Solana coins
CBBTC_FROM = "2024-11-07"                   # cbBTC live on Solana
XSTOCKS_FROM = "2025-06-30"                 # xStocks on Solana: SPYx, QQQx (and the gold token, assumed the same)
ONCHAIN_FROM = {"BTC": CBBTC_FROM, "SPY": XSTOCKS_FROM, "QQQ": XSTOCKS_FROM, "GOLD": XSTOCKS_FROM}
CEX_HALF_SPREAD = 0.0010                    # where Kraken has no EUR pair (assumed)
CEX_TAKER = kf.kraken_fee()                 # a new account's spot taker (lab.exec.kraken_fee, results/kraken_fee_s1_prereg.md)
ONCHAIN_WITHDRAW_USD = s1.ONRAMP_WITHDRAW_USD
SEPA_EUR = 0.09                             # Kraken's SEPA withdrawal (assumed)
UCITS, WORLD = "SXR8.DE", "EUNL.DE"         # iShares Core S&P 500 UCITS Acc, iShares Core MSCI World UCITS Acc (Xetra)
UCITS_HALF_SPREAD, UCITS_SELL_EUR = 0.0005, 1.0
TOKEN_IDS = {"SPY": ("sp500-xstock", "SPY"), "QQQ": ("nasdaq-xstock", "QQQ"), "GOLD": ("pax-gold", "GLD")}
SEED, SEEDS = 10, 10
SAFE_DD, MATCH_SLACK, DSR_PASS = s2.SAFE_DD, s2.MATCH_SLACK, 0.95
S1_RULES = {"tsmom1": ("tsmom_top20", 1), "breakout_sol3": ("breakout_sol", 3)}
S2_RULES = ("spy_trend", "dual_mom", "mix_6040", "trend_mix", "vol_target")
EARLY = -(2 ** 62)


def us_of(day: str) -> int:
    return int(datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1e6)


def t_of(days: np.ndarray, day: str) -> int:
    """The first index on or after `day`."""
    return int(np.searchsorted(days, us_of(day)))


def t_last(days: np.ndarray, day: str) -> int:
    """The last index on or before `day`."""
    return int(np.searchsorted(days, us_of(day), side="right")) - 1


def late(W: np.ndarray) -> np.ndarray:
    """The targets one close late: what the rule knew at close t is traded at close t+1."""
    W = np.asarray(W, dtype=float)
    return np.vstack([np.zeros((1,) + W.shape[1:]), W[:-1]])


def late_mask(x: np.ndarray) -> np.ndarray:
    return np.r_[False, np.asarray(x, dtype=bool)[:-1]]


# ---------------------------------------------------------------- the snapshot

def ecb_rows(csv_text: str, start: str = "2017-01-01") -> list[dict]:
    """The ECB's reference rates (eurofxref-hist.csv: Date,USD,JPY,...) as USD per EUR from `start`."""
    lines = [ln for ln in csv_text.splitlines() if ln.strip()]
    head = [h.strip() for h in lines[0].split(",")]
    i = head.index("USD")
    out = []
    for ln in lines[1:]:
        x = ln.split(",")
        try:
            d, v = x[0].strip(), float(x[i])
        except (IndexError, ValueError):
            continue                                # "N/A" on a day without a fixing
        if d >= start and v > 0:
            out.append({"date": d, "eurusd": v})
    return sorted(out, key=lambda r: r["date"])


def overnight_rows(key: str, prices: list[list], closes: dict[str, float], per_unit: bool = False) -> list[dict]:
    """The token's price at each 00:00 UTC (CoinGecko's daily points) against its underlying's last close before
    it: the point at 00:00 of day D closes panel day D-1; us_day: a US close happened on D-1. per_unit: the token is
    another unit of the asset (an ounce against a GLD share), scaled by the median ratio first."""
    pts = {}
    for ms, p in prices:
        if int(ms) % 86_400_000 == 0 and p and p > 0:
            pts[(datetime.fromtimestamp(int(ms) / 1000, timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")] = float(p)
    dates = sorted(closes)
    if per_unit:
        pts = s2.per_unit(pts, closes)
    out = []
    for d in sorted(pts):
        i = int(np.searchsorted(dates, d, side="right")) - 1
        if i < 0:
            continue
        c = closes[dates[i]]
        out.append({"key": key, "date": d, "token_usd": round(pts[d], 6), "close_date": dates[i], "close": c,
                    "us_day": dates[i] == d, "dev_bps": round((pts[d] / c - 1) * 1e4, 3)})
    return out


def snapshot() -> None:
    import urllib.request
    req = urllib.request.Request(ECB_ZIP, headers={"User-Agent": "pythia-lab"})
    with urllib.request.urlopen(req, timeout=60) as r:
        z = zipfile.ZipFile(io.BytesIO(r.read()))
    rows = ecb_rows(z.read(z.namelist()[0]).decode("utf-8"))
    s1.write_csv(EURUSD_CSV, rows)
    print(f"{len(rows)} ECB fixings {rows[0]['date']} to {rows[-1]['date']} -> {EURUSD_CSV.name}")
    get = s2.Paced({"api.coingecko.com": 8.0, "query1.finance.yahoo.com": 1.0}).get
    now = int(time.time())
    t0 = int(datetime(2017, 1, 1, tzinfo=timezone.utc).timestamp())
    fund = []
    for sym in (UCITS, WORLD):
        fund += [{"symbol": sym, "date": d, "close": c} for d, c, _ in s2.yahoo_rows(get(s2.YAHOO.format(sym, t0, now)))]
    s1.write_csv(UCITS_CSV, fund)
    print(f"{len(fund)} UCITS closes -> {UCITS_CSV.name}")
    tok = []
    for key, (cg, under) in TOKEN_IDS.items():
        closes = {d: c for d, c, _ in s2.yahoo_rows(get(s2.YAHOO.format(under, now - 400 * 86_400, now)))}
        prices = (get(s2.COINGECKO.format(cg)) or {}).get("prices") or []
        tok += overnight_rows(key, prices, closes, per_unit=key == "GOLD")
    s1.write_csv(TOKENS_CSV, tok)
    print(f"{len(tok)} token prices at 00:00 UTC -> {TOKENS_CSV.name}")


# ---------------------------------------------------------------- the inputs

def series_on(days_us: np.ndarray, rows: list[dict], col: str) -> np.ndarray:
    """A daily series on the panel's days: the last value on or before each day, the first one before it starts."""
    rows = sorted(rows, key=lambda r: r["date"])
    dates = np.array([r["date"] for r in rows], dtype="datetime64[D]")
    vals = np.array([float(r[col]) for r in rows])
    x = s2.etf_on_days(days_us, dates, vals)
    return np.where(np.isfinite(x), x, vals[0])


def eurusd_on(days_us: np.ndarray, path: Path = EURUSD_CSV) -> np.ndarray:
    return series_on(days_us, s1.read_csv(path), "eurusd")


def fund_on(days_us: np.ndarray, sym: str, path: Path = UCITS_CSV) -> np.ndarray:
    """A UCITS fund's EUR close on each day (NaN before its first)."""
    rows = sorted([r for r in s1.read_csv(path) if r["symbol"] == sym], key=lambda r: r["date"])
    return s2.etf_on_days(days_us, np.array([r["date"] for r in rows], dtype="datetime64[D]"),
                          np.array([float(r["close"]) for r in rows]))


def deviations(path: Path = TOKENS_CSV) -> dict[str, dict]:
    """Per token key: the cleaned deviations at 00:00 UTC (bps) after a US close ("us") and on days without one
    ("shut"), both around the US days' mean; and what the cleaning took."""
    by: dict[str, dict[str, list]] = {}
    for r in s1.read_csv(path):
        by.setdefault(r["key"], {"us": [], "shut": []})["us" if r["us_day"] == "True" else "shut"].append(
            float(r["dev_bps"]))
    out = {}
    for k, x in by.items():
        us, shut = s2.clean(x["us"]), s2.clean(x["shut"])
        if not len(us):
            continue
        m = float(us.mean())
        out[k] = {"us": us - m, "shut": shut - m, "mean_bps": m, "n_us": len(us), "n_shut": len(shut),
                  "dropped": len(x["us"]) + len(x["shut"]) - len(us) - len(shut),
                  "us_sd_bps": float(us.std()), "shut_sd_bps": float(shut.std()) if len(shut) else None}
    return out


def token_price(base: np.ndarray, us_day: np.ndarray, dev: dict | None, seed: int, k: int) -> np.ndarray:
    """The token at each 00:00 UTC close: its underlying's last close (with drift) times one draw of the measured
    deviation, from the weekend's on days without a US close."""
    if not dev:
        return base
    rng = np.random.default_rng([seed, k])
    a = rng.choice(dev["us"], len(base))
    shut = dev["shut"] if len(dev["shut"]) else dev["us"]
    b = rng.choice(shut, len(base))
    return base * (1 + np.where(us_day, a, b) / 1e4)


def kraken_costs(path: Path = s1.KRAKEN_CSV, vol_usd: float = 0.0) -> tuple[dict[str, float], float]:
    """(coin -> Kraken's spot taker fee plus the half spread of its EUR pair, the rate USDC to EUR and back costs:
    the stablecoin fee plus USDC/EUR's half spread). The fees from lab.exec.kraken_fee at the 30-day volume."""
    out, stable = {}, kf.kraken_fee(vol_usd, stable=True)
    for r in s1.read_csv(path):
        bid, ask = float(r["bid"]), float(r["ask"])
        out[r["coin"]] = (stable if r["coin"] == "USDC" else kf.kraken_fee(vol_usd)) + (ask - bid) / (ask + bid)
    return out, out.get("USDC", stable)


# ---------------------------------------------------------------- the venue of its era

@dataclass
class EraVenue(s2.S2Venue):
    """A USD venue (eurusd 1) whose cost follows the day: today's recorded quote and network fee from the day the
    asset could be swapped on chain, Kraken's taker fee and half spread before. The SOL reserve only on chain;
    the way in and back are charged outside (way_in, way_back)."""
    fee_sol: float = s2.SWAP_FEE_SOL
    cex: dict = field(default_factory=dict)
    onchain_from: dict = field(default_factory=dict)        # coin -> first day on chain (us)
    default_from: int = 0
    day: int = 0

    def at(self, day_us: int) -> None:
        self.day = int(day_us)

    def on_chain(self, coin: str) -> bool:
        return self.day >= self.onchain_from.get(coin, self.default_from)

    def tradable(self, coin: str) -> bool:
        return coin in self.ladder if self.on_chain(coin) else True

    def cost(self, coin: str, eur: float, sol_eur: float) -> float:
        if self.on_chain(coin) and coin in self.ladder:
            return eur * max(self.half_rt_bps(coin, eur), 0.0) / 1e4 + self.fee_sol * sol_eur
        return eur * self.cex.get(coin, CEX_TAKER + CEX_HALF_SPREAD)

    def setup(self, capital: float, slots: int, sol_eur: float) -> tuple[float, float]:
        if not self.on_chain("SOL"):
            return 0.0, 0.0
        return (s1.SOL_FEE_RESERVE + s1.RENT_SOL * (slots + 1)) * sol_eur, 0.0


def era_venue(ladder: dict, fee_sol: float, cex: dict, today: bool = False) -> EraVenue:
    """today: every asset on chain from the start (today's quotes back to 2020, as S1, S2, F2 and L1 charged)."""
    on = {} if today else {c: us_of(d) for c, d in ONCHAIN_FROM.items()}
    return EraVenue("jupiter", 1.0, ladder={k: list(v) for k, v in ladder.items()}, fee_sol=fee_sol, cex=dict(cex),
                    onchain_from=on, default_from=EARLY if today else us_of(JUPITER_FROM))


def sol_on_chain(v: EraVenue, day_us: int) -> bool:
    """Whether a wallet started that day is on chain (it then pays 1 USDC to withdraw and holds the SOL reserve)."""
    v.at(day_us)
    return v.on_chain("SOL")


def way_in(cap_eur: float, fx0: float, rate: float, on_chain: bool) -> float:
    """The USDC a wallet starts with: EUR to USD at Kraken, 1 USDC to withdraw on chain."""
    return cap_eur * fx0 * (1 - rate) - (ONCHAIN_WITHDRAW_USD if on_chain else 0.0)


def way_back(equity_usd: float, held: dict, v: s1.Venue, sol_usd: float, fx1: float, rate: float) -> float:
    """The EUR on the bank account after the last close: every position sold at its cost, USDC to EUR, SEPA."""
    sell = sum(v.cost(c, x, sol_usd) for c, x in held.items() if x > 0)
    return (equity_usd - sell) * (1 - rate) / fx1 - SEPA_EUR


def in_eur(res: dict, cap_eur: float, fx: np.ndarray, t0: int, t1: int, v: s1.Venue, days: np.ndarray,
           sol_usd: float, rate: float) -> np.ndarray:
    """The USD wallet's equity in EUR at each close, the last after the way back."""
    eq = np.asarray(res["equity"], dtype=float) / fx[t0:t1 + 1]
    v.at(days[t1])
    eq[-1] = way_back(float(res["equity"][-1]), res.get("end_held") or {}, v, sol_usd, float(fx[t1]), rate)
    return eq


def measure(eq_eur: np.ndarray, cap_eur: float) -> dict:
    r = s2.daily_returns(eq_eur, cap_eur)
    p = fc.perf(r)
    return {"cagr": p["cagr"], "max_dd": p["max_dd"], "sharpe": p["sharpe"], "end_eur": float(eq_eur[-1]),
            "returns": r}


# ---------------------------------------------------------------- the market and the rules

@dataclass
class Market:
    """Everything the rules run on, in USD: S1's and S2's panel, F2's context, the venues, the FX and funds."""
    P: fc.Panel
    m: s2.Market                     # S2's market in USD, the rules read it
    fx: np.ndarray                   # EUR/USD on P's days
    v1: EraVenue                     # S1's ladder and network fee (S1, L1)
    v2: EraVenue                     # S2's ladder, network fee and Sender tip (S2, F2)
    v1_today: EraVenue
    v2_today: EraVenue
    rate: float                      # EUR to USDC and back at Kraken
    devs: dict
    c: object = None                 # F2's context (lab.factory.small.Ctx) in USD
    c_fx: np.ndarray | None = None
    c_us: np.ndarray | None = None
    f2: list = field(default_factory=list)


def token_market(mk: Market, seed: int) -> s2.Market:
    """S2's market with the tokens at 00:00 UTC drawn with `seed` (the rules keep reading mk.m)."""
    px = dict(mk.m.px)
    for i, k in enumerate(("SPY", "GOLD")):
        px[k] = token_price(mk.m.px[k], mk.m.us_day, mk.devs.get(k), seed, i)
    return replace(mk.m, px=px)


def token_ctx(mk: Market, seed: int):
    """F2's context with the tokens at 00:00 UTC drawn with `seed` on the traded prices (sig stays)."""
    from ..factory import small as f2
    c = mk.c
    px = c.px.copy()
    for i, k in enumerate(("SPY", "GOLD", "QQQ")):
        j = f2.ASSETS.index(k)
        px[:, j] = token_price(c.sig[:, j], mk.c_us, mk.devs.get(k), seed, i)
    return replace(c, px=px, memo=c.memo)


def bench_pair(px: np.ndarray, sol: np.ndarray, days: np.ndarray, v: EraVenue, cap: float, fx: np.ndarray,
               rate: float, t0: int, t1: int) -> np.ndarray:
    """Half BTC and half ETH bought at the close of t0 and held, the wallet's costs, in EUR after the way back."""
    T = len(days)
    usd = way_in(cap, float(fx[t0]), rate, sol_on_chain(v, days[t0]))
    res = s2.simulate(px, ["BTC", "ETH"], np.tile([0.5, 0.5], (T, 1)), np.zeros(T, dtype=bool),
                      np.zeros(T, dtype=bool), sol, v, usd, t0, t1, 2, days=days)
    return in_eur(res, cap, fx, t0, t1, v, days, float(sol[t1]), rate)


def bench_fund(close: np.ndarray, cap: float, t0: int, t1: int) -> np.ndarray:
    """A UCITS fund in EUR bought at the close of t0 through a free savings plan, sold at t1 at 1 EUR."""
    eq = cap * (1 - UCITS_HALF_SPREAD) * close[t0:t1 + 1] / close[t0]
    eq[-1] = eq[-1] * (1 - UCITS_HALF_SPREAD) - UCITS_SELL_EUR
    return eq


def run_s1(mk: Market, rule: str, cap: float, is_late: bool, t0: int, t1: int, today: bool = False,
           memo: dict | None = None) -> np.ndarray:
    P = mk.P
    key, n = S1_RULES[rule]
    memo = {} if memo is None else memo
    W = memo.setdefault(("s1", rule), s1.candidate(P, key, n))
    v = mk.v1_today if today else mk.v1
    usd = way_in(cap, float(mk.fx[t0]), mk.rate, sol_on_chain(v, P.days[t0]))
    res = s1.simulate(P, late(W) if is_late else W, v, usd, t0, t1, 1, n)
    return in_eur(res, cap, mk.fx, t0, t1, v, P.days, float(mk.m.sol_eur[t1]), mk.rate)


def run_s2(mk: Market, rule: str, cap: float, is_late: bool, t0: int, t1: int, today: bool = False,
           seed: int = SEED, memo: dict | None = None) -> np.ndarray:
    P = mk.P
    memo = {} if memo is None else memo
    keys, W, due, rw = memo.setdefault(("s2", rule), s2.candidate(rule, mk.m, P))
    if is_late:
        W, due, rw = late(W), late_mask(due), late_mask(rw)
    mt = memo.setdefault(("tok", seed), token_market(mk, seed))
    px = s2.coin_prices(rule, keys, mt, P, 1.0)
    v = mk.v2_today if today else mk.v2
    usd = way_in(cap, float(mk.fx[t0]), mk.rate, sol_on_chain(v, P.days[t0]))
    res = s2.simulate(px, keys, W, due, rw, mk.m.sol_eur, v, usd, t0, t1, s2.SLOTS[rule], days=P.days)
    return in_eur(res, cap, mk.fx, t0, t1, v, P.days, float(mk.m.sol_eur[t1]), mk.rate)


def run_l1(mk: Market, cap: float, is_late: bool, t0: int, t1: int, today: bool = False,
           memo: dict | None = None) -> np.ndarray:
    from ..onchain import longterm as L
    P = mk.P
    memo = {} if memo is None else memo
    W = memo.setdefault(("l1",), L.rule(P))
    v = mk.v1_today if today else mk.v1
    fee_l = L.BASE_FEE_L + L.F.CHEAP_MAX_PRIORITY_L

    def cost(c: str, usd: float, sol: float, t: int) -> float:
        v.at(P.days[t])
        if v.on_chain(c) and c in v.ladder:
            return usd * max(v.half_rt_bps(c, usd), 0.0) / 1e4 + fee_l / L.LAMPORTS * sol
        return usd * v.cex.get(c, CEX_TAKER + CEX_HALF_SPREAD)
    usd = way_in(cap, float(mk.fx[t0]), mk.rate, sol_on_chain(v, P.days[t0]))
    res = L.simulate(P, t0, t1, usd, W=late(W) if is_late else W, venue=v, swap_cost=cost)
    return in_eur(res, cap, mk.fx, t0, t1, v, P.days, float(mk.m.sol_eur[t1]), mk.rate)


def run_f2(mk: Market, g: dict, cap: float, is_late: bool, t0: int, t1: int, today: bool = False,
           seed: int = SEED, memo: dict | None = None) -> np.ndarray:
    from ..factory import small as f2
    memo = {} if memo is None else memo
    c = memo.setdefault(("ctx", seed), token_ctx(mk, seed))
    W = memo.setdefault(("f2", f2.key(g)), f2.weights(mk.c, g))
    v = f2.venue(mk.v2_today if today else mk.v2)
    usd = way_in(cap, float(mk.c_fx[t0]), mk.rate, sol_on_chain(v, c.days[t0]))
    res = f2.simulate(c, late(W) if is_late else W, g, v, usd, t0, t1)
    return in_eur(res, cap, mk.c_fx, t0, t1, v, c.days, float(c.sol_eur[t1]), mk.rate)


def f2_genomes() -> list[dict]:
    """Every genome F2 held back, once per key, in the order first held back: the seed's, then the server's."""
    from ..factory import ledger as lg
    from ..factory import small as f2
    led: dict[str, dict] = {}
    held: list[str] = []
    for d in (f2.seed_dir(), f2.small_dir()):
        for r in lg.read_jsonl(d / "ledger.jsonl"):
            led.setdefault(r["key"], r)
        for h in lg.read_jsonl(d / "holdout.jsonl"):
            if h.get("key") and h["key"] not in held:
                held.append(h["key"])
    return [{"key": k, "name": led[k].get("name") or f2.describe(led[k]["genome"]), "genome": led[k]["genome"]}
            for k in held if k in led and led[k].get("genome")]


def is_crypto_genome(g: dict) -> bool:
    from ..factory import small as f2
    return set(f2.UNIVERSES[g["universe"]["set"]]) <= set(f2.CRYPTO)


def holds_token(rule: dict) -> bool:
    return rule["study"] == "S2" or (rule["study"] == "F2" and not rule["crypto"])


def rules(mk: Market) -> list[dict]:
    out = [{"name": r, "study": "S1", "crypto": True} for r in S1_RULES]
    out += [{"name": r, "study": "S2", "crypto": False} for r in S2_RULES]
    out.append({"name": "onchain_longterm", "study": "L1", "crypto": True})
    out += [{"name": f"f2 {x['key']}", "study": "F2", "crypto": is_crypto_genome(x["genome"]), "genome": x["genome"],
             "what": x["name"]} for x in mk.f2]
    return out


def run_rule(mk: Market, rule: dict, cap: float, is_late: bool, win: str, today: bool = False, seed: int = SEED,
             memo: dict | None = None) -> np.ndarray:
    on_ctx = rule["study"] == "F2"
    days = mk.c.days if on_ctx else mk.P.days
    t0, t1 = window(days, win)
    if rule["study"] == "S1":
        return run_s1(mk, rule["name"], cap, is_late, t0, t1, today, memo)
    if rule["study"] == "S2":
        return run_s2(mk, rule["name"], cap, is_late, t0, t1, today, seed, memo)
    if rule["study"] == "L1":
        return run_l1(mk, cap, is_late, t0, t1, today, memo)
    return run_f2(mk, rule["genome"], cap, is_late, t0, t1, today, seed, memo)


def window(days: np.ndarray, win: str) -> tuple[int, int]:
    if win == "is":
        return t_of(days, IS_FROM), t_of(days, VAL_FROM) - 1
    return t_of(days, VAL_FROM), min(t_last(days, VAL_TO), len(days) - 1)


def benchmarks(mk: Market, cap: float, win: str, on_ctx: bool = False) -> dict[str, np.ndarray]:
    """The BTC/ETH wallet, BTC held alone, and the two UCITS funds, in EUR over the window."""
    if on_ctx:
        from ..factory import small as f2
        c = mk.c
        days, fx, sol = c.days, mk.c_fx, c.sol_eur
        px = c.px[:, [f2.ASSETS.index("BTC"), f2.ASSETS.index("ETH")]]
    else:
        P = mk.P
        days, fx, sol = P.days, mk.fx, mk.m.sol_eur
        px = P.px[:, [P.col("BTCUSDT"), P.col("ETHUSDT")]]
    t0, t1 = window(days, win)
    out = {"btc_eth": bench_pair(px, sol, days, mk.v2, cap, fx, mk.rate, t0, t1)}
    T = len(days)
    usd = way_in(cap, float(fx[t0]), mk.rate, sol_on_chain(mk.v2, days[t0]))
    res = s2.simulate(px[:, :1], ["BTC"], np.ones((T, 1)), np.zeros(T, dtype=bool), np.zeros(T, dtype=bool), sol,
                      mk.v2, usd, t0, t1, 1, days=days)
    out["btc"] = in_eur(res, cap, fx, t0, t1, mk.v2, days, float(sol[t1]), mk.rate)
    for f in (UCITS, WORLD):
        close = fund_on(days, f)
        out[f] = bench_fund(close, cap, t0, t1)
    return out


# ---------------------------------------------------------------- judging

def dsr_pools() -> dict[str, dict]:
    """R5's registry: the pool of all and the small family, the factory ledgers counted once by id."""
    from ..metrics import trial_pool
    from .director_common import ledger_trials
    extra = ledger_trials()
    return {"all": trial_pool(extra=extra), "small": trial_pool("small", extra=extra)}


def excess(x: np.ndarray, b: np.ndarray) -> np.ndarray:
    n = min(len(x), len(b))
    return np.asarray(x[-n:]) - np.asarray(b[-n:])


def verdict(row: dict) -> dict:
    """The pre-registered bar, late, at every size: a crypto rule CAGR above 0, Sharpe above the BTC/ETH wallet's
    and DSR 0.95 or more; a safe-path rule drawdown under 20 %, CAGR at least the fund's minus 1 point and DSR 0.95
    or more. The same test on time is shown, never used."""
    out = {}
    for fill in ("on_time", "late"):
        ok, why = True, []
        for cap in CAPITALS:
            r, b = row[f"{fill}@{cap:g}"], row[f"bench@{cap:g}"]
            if row["crypto"]:
                checks = {"CAGR > 0": r["cagr"] > 0, "Sharpe > BTC/ETH": r["sharpe"] > b["sharpe"]}
            else:
                checks = {"DD < 20 %": r["max_dd"] < SAFE_DD, "CAGR >= fund - 1 pt": r["cagr"] >= b["cagr"] - MATCH_SLACK}
            checks["DSR >= 0.95"] = r.get("dsr", 0.0) >= DSR_PASS
            for k, x in checks.items():
                if not x:
                    ok = False
                    why.append(f"{cap:g} EUR: {k}")
        out[fill] = {"passes": ok, "why": why}
    return out


def evaluate(mk: Market, pools: dict, log=print, only: list[dict] | None = None, val_only: bool = False) -> list[dict]:
    """Every rule's rows; `only` these rules, `val_only` without the in-sample Sharpes and the token draws."""
    from ..metrics import dsr
    rows = []
    todo = rules(mk) if only is None else only
    bench = {(cap, ctx): benchmarks(mk, cap, "val", ctx) for cap in CAPITALS
             for ctx in sorted({r["study"] == "F2" for r in todo})}
    memo: dict = {}
    for rule in todo:
        key = "btc_eth" if rule["crypto"] else UCITS
        ctx = rule["study"] == "F2"
        row = {k: rule[k] for k in ("name", "study", "crypto")}
        if rule.get("what"):
            row["what"] = rule["what"]
        row["benchmark"] = "BTC/ETH held" if rule["crypto"] else f"{UCITS} in EUR"
        for cap in CAPITALS:
            b = measure(bench[(cap, ctx)][key], cap)
            row[f"bench@{cap:g}"] = {k: v for k, v in b.items() if k != "returns"}
            for fill, lt in (("on_time", False), ("late", True)):
                m = measure(run_rule(mk, rule, cap, lt, "val", memo=memo), cap)
                ex = excess(m.pop("returns"), b["returns"])
                m.update({"excess_sharpe": float(ex.mean() / ex.std() * math.sqrt(365)) if ex.std() > 0 else 0.0,
                          "dsr": dsr(ex, pools["all"]), "dsr_small": dsr(ex, pools["small"])})
                row[f"{fill}@{cap:g}"] = m
        if val_only:
            row["verdict"] = verdict(row)
            rows.append(row)
            continue
        ins = {}
        for name, lt, today in (("today_on_time", False, True), ("era_on_time", False, False), ("era_late", True, False)):
            ins[name] = measure(run_rule(mk, rule, MAIN, lt, "is", today, memo=memo), MAIN)["sharpe"]
        row["is_sharpe"] = ins
        if holds_token(rule):
            xs = [measure(run_rule(mk, rule, MAIN, True, "val", seed=SEED + 1 + i, memo=memo), MAIN)
                  for i in range(SEEDS)]
            row["draws"] = {"cagr_median": float(np.median([x["cagr"] for x in xs])),
                            "max_dd_worst": float(max(x["max_dd"] for x in xs))}
        row["verdict"] = verdict(row)
        rows.append(row)
        log(f"  {rule['study']} {rule['name']}: late {row['late@40']['cagr'] * 100:.1f} % / "
            f"{row['late@100']['cagr'] * 100:.1f} %, passes late {row['verdict']['late']['passes']}")
    return rows


def bench_rows(mk: Market) -> list[dict]:
    out = []
    for cap in CAPITALS:
        for k, eq in benchmarks(mk, cap, "val").items():
            m = measure(eq, cap)
            out.append({"bench": k, "capital": cap, **{f: m[f] for f in ("cagr", "max_dd", "sharpe", "end_eur")}})
    return out


# ---------------------------------------------------------------- loading

def load(offline: bool = True, f2_ctx: bool = True) -> Market:
    from ..factory import small as f2
    P = fc.load_panel()
    etf = s2.load_etf(("SPY", "QQQ", "GLD"))
    snap = s2.load_snapshot()
    drifts = s2.drifts_from(snap, s2.tracking())
    m = s2.market(P, etf, 1.0, drifts)
    cex, rate = kraken_costs()
    v1 = s1.venues()["jupiter"]
    v2 = f2.venue(s2.venue(snap=snap))                          # QQQx under QQQ for F2; S2 reads SPY and GOLD
    mk = Market(P=P, m=m, fx=eurusd_on(P.days), v1=era_venue(v1.ladder, s1.SWAP_FEE_SOL, cex),
                v2=era_venue(v2.ladder, s2.SWAP_FEE_SOL, cex), v1_today=era_venue(v1.ladder, s1.SWAP_FEE_SOL, cex, True),
                v2_today=era_venue(v2.ladder, s2.SWAP_FEE_SOL, cex, True), rate=rate, devs=deviations())
    if not f2_ctx:
        return mk                                               # S1's rows only (the Kraken fee rerun)
    days, crypto = f2.crypto_closes()
    c = f2.make_ctx(days, crypto, etf, 1.0, f2.drifts(), None, bars=f2.crypto_bars(days))
    mk.c, mk.c_fx = c, eurusd_on(days)
    mk.c_us = np.isin((days // fc.DAY_US).astype("datetime64[D]"), etf["SPY"][0])
    mk.f2 = f2_genomes()
    return mk


# ---------------------------------------------------------------- the report

MARKER = "<!-- generated below by lab.experiments.smallaccount_r10; edit above this line only -->"


def _pct(v, d: int = 1) -> str:
    return "n/a" if v is None else f"{v * 100:.{d}f} %"


def _cell(m: dict) -> str:
    return f"{_pct(m['cagr'])} / {_pct(m['max_dd'])} / {m['sharpe']:.2f} / {m['end_eur']:.2f}"


def markdown(out: dict) -> str:
    pools = out["pools"]
    md = [f"Generated {out['generated']}. Validation {VAL_FROM} to {out['val_to']}, in sample {IS_FROM} to 2023-12-31. "
          f"EUR/USD (ECB) {out['fx']['min']:.4f} to {out['fx']['max']:.4f} over the validation window "
          f"(before R10 fixed at 1.1194). Every wallet in USD, valued in EUR at the day's rate; the way in "
          f"(Kraken {out['rate'] * 1e4:.1f} bps and 1 USDC) and the way back (positions sold, "
          f"{out['rate'] * 1e4:.1f} bps, {SEPA_EUR:.2f} EUR) are in every number.\n",
          "## 1. Late against on time, validation window (the bar)\n"]
    t = []
    for r in out["rows"]:
        for cap in CAPITALS:
            o, l, b = r[f"on_time@{cap:g}"], r[f"late@{cap:g}"], r[f"bench@{cap:g}"]
            t.append({"rule": f"{r['study']} {r['name']}", "EUR": f"{cap:g}", "on time CAGR / DD / Sharpe / end": _cell(o),
                      "late CAGR / DD / Sharpe / end": _cell(l), "benchmark": r["benchmark"],
                      "benchmark CAGR / DD / Sharpe / end": _cell(b),
                      "late DSR, pass at 0.95 or more (all / small)": f"{l['dsr']:.3f} / {l['dsr_small']:.3f}",
                      "passes late": "yes" if r["verdict"]["late"]["passes"] else "no"})
    md.append(fc.table(t, list(t[0])))
    md.append(f"DSR: of the late wallet's daily excess over its benchmark in EUR, over R5's trial registry, the pool of "
              f"all ({pools['all']['n_trials']:,} trials, noise bar {pools['all']['sr0_annual']:.2f} a year) and the "
              f"small family ({pools['small']['n_trials']:,} trials, {pools['small']['sr0_annual']:.2f}); higher is "
              "better. `passes late`: the pre-registered bar at 40 and at 100 EUR, filled one close late.\n")
    md.append("## 2. The verdict\n")
    t = [{"rule": f"{r['study']} {r['name']}", "kind": "crypto" if r["crypto"] else "safe path",
          "passes on time": "yes" if r["verdict"]["on_time"]["passes"] else "no",
          "passes late": "yes" if r["verdict"]["late"]["passes"] else "no",
          "late fails on": "; ".join(r["verdict"]["late"]["why"][:4]) + (" ..." if len(r["verdict"]["late"]["why"]) > 4 else ""),
          "late 40 EUR over 10 token draws (median CAGR / worst DD)":
              f"{_pct(r['draws']['cagr_median'])} / {_pct(r['draws']['max_dd_worst'])}" if r.get("draws") else ""}
         for r in out["rows"]]
    md.append(fc.table(t, list(t[0])))
    passed = [f"{r['study']} {r['name']}" for r in out["rows"] if r["verdict"]["late"]["passes"]]
    md.append(f"**For real money: {', '.join(passed) if passed else 'nothing'}.**\n")
    md.append("## 3. In sample at 40 EUR: what the honest costs and the late fill take (Sharpe)\n")
    t = [{"rule": f"{r['study']} {r['name']}", "today's quotes back to 2020, on time (as before)":
          f"{r['is_sharpe']['today_on_time']:.2f}", "costs of their era, on time": f"{r['is_sharpe']['era_on_time']:.2f}",
          "costs of their era, late": f"{r['is_sharpe']['era_late']:.2f}"} for r in out["rows"]]
    md.append(fc.table(t, list(t[0])))
    md.append("## 4. The benchmarks over the validation window (CAGR / DD / Sharpe / end in EUR)\n")
    t = [{"benchmark": b["bench"], "EUR": f"{b['capital']:g}", "CAGR / DD / Sharpe / end": _cell(b)} for b in out["bench"]]
    md.append(fc.table(t, list(t[0])))
    md.append("`btc_eth`: half BTC, half ETH bought once (the wallet's costs, way in and back); `btc` BTC alone; "
              f"`{UCITS}` iShares Core S&P 500 UCITS Acc, `{WORLD}` iShares Core MSCI World UCITS Acc, both in EUR on "
              "Xetra, bought through a free savings plan, sold at 1 EUR.\n")
    md.append("## 5. The inputs\n")
    t = [{"token": k, "mean at 00:00 UTC (bps)": f"{d['mean_bps']:.1f}", "after a US close: n / sd bps":
          f"{d['n_us']} / {d['us_sd_bps']:.1f}", "no US close: n / sd bps":
          f"{d['n_shut']} / {d['shut_sd_bps']:.1f}" if d.get("shut_sd_bps") is not None else "0",
          "dropped as bad prints": d["dropped"]} for k, d in out["devs"].items()]
    if t:
        md.append(fc.table(t, list(t[0])))
    md.append("Costs of their era: on chain (today's recorded quotes and network fee) from " + ", ".join(
        f"{c} {d}" for c, d in ONCHAIN_FROM.items()) + f", everything else from {JUPITER_FROM}; before that Kraken's "
        "taker fee and half spread (" + ", ".join(f"{c} {out['cex'][c] * 1e4:.1f} bps" for c in ("BTC", "ETH", "SOL")
                                                  if c in out["cex"]) + f", {(CEX_TAKER + CEX_HALF_SPREAD) * 1e4:.0f} "
        "bps without a Kraken pair). S2's premiums at the US close cleaned of " + (
        ", ".join(f"{k} {v}" for k, v in out["cleaned"].items()) or "nothing") + ".\n")
    return "\n".join(md) + "\n"


def write(out: dict, path: Path = RESULTS / f"{NAME}.md") -> None:
    head = "# R10: the small-account path, honestly costed\n\n"
    if path.exists():
        old = path.read_text(encoding="utf-8")
        if MARKER in old:
            head = old.split(MARKER)[0]
    path.write_text(head + MARKER + "\n\n" + markdown(out), encoding="utf-8")


def cleaned(path: Path = s2.PREMIUMS_CSV) -> dict[str, str]:
    """What s2.clean takes out of the picks' and QQQx's premiums: symbol -> the dropped points in bps."""
    by: dict[str, list] = {}
    for r in s1.read_csv(path):
        if r["symbol"] in ("SPYx", "QQQx", "PAXG"):
            by.setdefault(r["symbol"], []).append((r["date"], float(r["premium_bps"])))
    out = {}
    for s, xs in by.items():
        kept = set(s2.clean([x for _, x in xs]).tolist())
        gone = [f"{x:+.0f} bps on {d}" for d, x in xs if x not in kept]
        if gone:
            out[s] = ", ".join(gone)
    return out


# ---------------------------------------------------------------- the Kraken fee rerun (results/kraken_fee_s1_prereg.md)

KF_NAME, KF_PREREG = "kraken_fee_s1", "results/kraken_fee_s1_prereg.md"
KF_MARKER = "<!-- generated below by lab.experiments.smallaccount_r10 --kraken-fee; edit above this line only -->"


def kraken_fee_trials() -> list[dict]:
    """R10's S1 rows at the corrected fee: rule x size x fill, counted, family small."""
    return [{"id": f"small:kraken_fee_s1:{r}@{cap:g}:{fill}", "family": "small", "n": 1, "sharpe": None,
             "source": KF_PREREG} for r in S1_RULES for cap in CAPITALS for fill in ("on_time", "late")]


def kraken_fee_markdown(out: dict) -> str:
    md = [f"Generated {out['generated']}. Validation {VAL_FROM} to {out['val_to']} only (no in-sample number, the "
          f"lockbox shut). Fees: spot taker {out['taker'] * 100:.2f} % ({out['source']}); the way in and back "
          f"{out['rate'] * 1e4:.1f} bps (the stablecoin fee {out['stable'] * 100:.2f} % plus USDC/EUR's half "
          f"spread). Kraken before the asset was on chain: " + ", ".join(
              f"{c} {out['cex'][c] * 1e4:.1f} bps" for c in ("BTC", "ETH", "SOL") if c in out["cex"]) + ".\n"]
    t = []
    for r in out["rows"]:
        for cap in CAPITALS:
            o, l, b = r[f"on_time@{cap:g}"], r[f"late@{cap:g}"], r[f"bench@{cap:g}"]
            t.append({"rule": f"{r['study']} {r['name']}", "EUR": f"{cap:g}", "on time CAGR / DD / Sharpe / end": _cell(o),
                      "late CAGR / DD / Sharpe / end": _cell(l), "benchmark CAGR / DD / Sharpe / end": _cell(b),
                      "late DSR, pass at 0.95 or more (all / small)": f"{l['dsr']:.3f} / {l['dsr_small']:.3f}",
                      "passes late": "yes" if r["verdict"]["late"]["passes"] else "no"})
    md.append(fc.table(t, list(t[0])))
    pools = out["pools"]
    md.append(f"Benchmark: half BTC and half ETH held, the wallet's costs. DSR over R5's registry with this rerun's "
              f"{out['trials']} trials: all {pools['all']['n_trials']:,} trials (noise bar "
              f"{pools['all']['sr0_annual']:.2f} a year), small {pools['small']['n_trials']:,} "
              f"({pools['small']['sr0_annual']:.2f}); higher is better.\n")
    return "\n".join(md) + "\n"


def kraken_fee_main() -> int:
    from .. import metrics, report
    metrics.register(kraken_fee_trials())                       # before any number exists
    t0 = time.time()
    mk = load(f2_ctx=False)
    pools = dsr_pools()
    rows = evaluate(mk, pools, only=[r for r in rules(mk) if r["study"] == "S1"], val_only=True)
    cex, rate = kraken_costs()
    out = {"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "val_to": str((mk.P.days[window(mk.P.days, "val")[1]] // fc.DAY_US).astype("datetime64[D]")),
           "taker": kf.kraken_fee(), "stable": kf.kraken_fee(stable=True), "source": kf.source(), "rate": rate,
           "cex": cex, "trials": len(kraken_fee_trials()),
           "pools": {k: {"n_trials": p["n_trials"], "var": p["var"], "sr0_annual": p["sr0_annual"]} for k, p in pools.items()},
           "rows": rows, "seconds": round(time.time() - t0)}
    d = report.REPORTS / KF_NAME
    d.mkdir(parents=True, exist_ok=True)
    (d / "latest.json").write_text(json.dumps(out, indent=1, default=float), encoding="utf-8")
    path = RESULTS / f"{KF_NAME}.md"
    head = "# Kraken's new-account fee in R10's S1 rows\n\n"
    if path.exists() and KF_MARKER in path.read_text(encoding="utf-8"):
        head = path.read_text(encoding="utf-8").split(KF_MARKER)[0]
    path.write_text(head + KF_MARKER + "\n\n" + kraken_fee_markdown(out), encoding="utf-8")
    print(f"done in {out['seconds']} s; passes late: "
          f"{[r['name'] for r in rows if r['verdict']['late']['passes']] or 'nothing'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--snapshot" in argv:
        snapshot()
        return 0
    if "--kraken-fee" in argv:
        return kraken_fee_main()
    t0 = time.time()
    mk = load()
    pools = dsr_pools()
    rows = evaluate(mk, pools)
    a, b = window(mk.P.days, "val")
    cex, rate = kraken_costs()
    out = {"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "val_to": str((mk.P.days[b] // fc.DAY_US).astype("datetime64[D]")),
           "fx": {"min": float(mk.fx[a:b + 1].min()), "max": float(mk.fx[a:b + 1].max())}, "rate": rate, "cex": cex,
           "pools": {k: {"n_trials": p["n_trials"], "var": p["var"], "sr0_annual": p["sr0_annual"]} for k, p in pools.items()},
           "devs": {k: {f: v for f, v in d.items() if f not in ("us", "shut")} for k, d in mk.devs.items()},
           "cleaned": cleaned(), "rows": rows, "bench": bench_rows(mk), "seconds": round(time.time() - t0)}
    from .. import report
    d = report.REPORTS / NAME
    d.mkdir(parents=True, exist_ok=True)
    (d / "latest.json").write_text(json.dumps(out, indent=1, default=float), encoding="utf-8")
    write(out)
    print(f"done in {out['seconds']} s; passes late: "
          f"{[r['name'] for r in rows if r['verdict']['late']['passes']] or 'nothing'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
