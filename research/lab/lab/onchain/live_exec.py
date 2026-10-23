"""The stage-2 on-chain trader's executor: real swaps through Jupiter for our own wallet. LOCKED unless the owner arms it.

It swaps only when every gate of live_gate.Gate holds (env PYTHIA_ONCHAIN_LIVE=1, the owner's
ack, the stage-2 wallet file, a simulation within 24 h, no kill file, Jupiter's IDL, the
endpoints) and the caps below allow the swap. Then, for each swap (docs/ONCHAIN-STAGE2.md):

  1. `/swap/v2/build` for our wallet with our slippage (swapapi.py); every mint of the route on
     the route allowlist, both mints classic SPL tokens on the owner's allowlist
  2. the price check: Jupiter's USD prices against Kraken's mid (at most 2 % apart) and the
     swap's cost against them (at most 50 bps); the caps against the wallet's real balances
  3. one v0 message of our own: our compute unit limit and capped price, Jupiter's setup, swap
     and cleanup, one Sender tip when Sender is on; the lookup tables read from the chain
  4. the guard over the message read back from its bytes (guard.check_message), every writable
     account read from the chain (guard.check_accounts), then simulateTransaction with the
     account diff of the wallet and all its token accounts (guard.check_effect); the unit limit
     set to 1.2 x what the simulation used and the final message guarded and simulated again
  5. signed (the Signer from pumpfun_rt.live_exec.load_signer, loaded only after every gate
     held), sent to Helius Sender and the plain RPC, the same bytes again every 2 s until the
     signature lands or the blockhash expires; only then a new quote, at most 3 tries, never
     two versions of one swap at once
  6. the landed transaction read back (getTransaction): what the wallet really gave and got goes
     into the ledger, a failure with its fee too; every step into orders.jsonl

Caps, whatever the ack says (live_gate.TEST_MAX_*, in the alpha mode the lower ALPHA_MAX_*: 100 USD
in all, 25 a swap, 25 a day): a swap at most max_trade_usd (100, the small coins 100), no buy while the wallet is worth more than max_total_usd, after the day's loss
reached max_daily_loss_usd, or under the kill switch (a sale into USDC stays allowed when the
ack says on_kill=usdc), the app's converts at most max_convert_usd and 10 a UTC day, a book
40 swaps a day and never more than its book_usd, ETH at most a quarter of max_total_usd, 0.02
SOL always left for fees, no buy while the ledger does not match the chain.

Every swap that was sent is also measured (live/onchain/execution.jsonl, read by lab.onchain.execution
for reports/onchain/execution.md): signal to send, send to land, the fee paid (base, priority, tip)
and what really came out against the quote.

The ledger is reconciled against the wallet's real balances (`reconcile`): what the wallet held
when the service started, plus every swap's change as read from the chain, plus the deposits
it saw, must equal what the chain shows. A rise is the owner's deposit (journaled); a fall
that no swap explains stops every buy and goes to the watcher. The day's and the total's
numbers are recomputed from the files, never counted up.

There is no transfer anywhere: the guard knows no instruction that moves funds out of the
wallet. Withdrawing stays with the owner's own wallet and backup (docs/ONCHAIN-STAGE2.md).

    python -m lab.onchain.live_exec check        every gate, and why it is shut
    python -m lab.onchain.live_exec simulate     SOL to USDC (and USDC to SOL when the wallet holds
                                                 USDC), 10 USD each, built for this wallet, guarded
                                                 and simulated on mainnet (nothing signed or sent)
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import math
import random
import sys
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from ..pumpfun_rt import chain_pnl as CP
from ..pumpfun_rt import live_exec as LX
from ..pumpfun_rt import txbuild as X
from ..pumpfun_rt.events import WSOL, b58
from . import guard as G
from . import live_gate as LG
from . import mints as M
from . import swapapi as S
from . import tx as T
from .jupiter import Jupiter, QuoteError

DAY_MS = 86_400_000
MAX_ATTEMPTS = 3
RESEND_S = 2.0
STATUS_S = 1.0
LAND_MAX_S = 150.0                       # longer than a blockhash's 60 to 90 s life
DEFAULT_CU_PRICE = 50_000                # micro-lamports when Jupiter suggests none
KRAKEN_URL = "https://api.kraken.com/0/public/Ticker?pair="
LEDGER_COLS = ["t", "mode", "kind", "book", "ref", "from", "to", "in_raw", "out_raw", "sol_delta_l", "fee_l", "tip_l",
               "in_usd", "out_usd", "planned_out_raw", "min_out_raw", "sig", "status", "why", "unread"]
SOL_CODE = "SOL"


def now_ms() -> int:
    return int(time.time() * 1000)


def day_of(ms: int) -> int:
    return int(ms) // DAY_MS


def _append_jsonl(path: Path, rec: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, default=str) + "\n")
    except OSError as e:
        print(f"onchain live: {path.name} not written ({e})", flush=True)


def _read_jsonl(path: Path) -> list[dict]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            j = json.loads(line)
        except ValueError:
            continue
        if isinstance(j, dict):
            out.append(j)
    return out


def orders_path() -> Path:
    return LG.data_dir() / "orders.jsonl"


def journal_path() -> Path:
    return LG.data_dir() / "journal.jsonl"


def ledger_path() -> Path:
    return LG.data_dir() / "ledger.csv"


def execution_path() -> Path:
    return LG.data_dir() / "execution.jsonl"


def read_execution() -> list[dict]:
    return _read_jsonl(execution_path())


def log_order(rec: dict) -> None:
    """Every step of every swap: planned, refused, built, sent, landed, filled, failed, expired."""
    _append_jsonl(orders_path(), {"t": now_ms(), **rec})


def journal(rec: dict) -> None:
    """What no swap row holds: the baseline at a start, the owner's deposits, unexplained differences."""
    _append_jsonl(journal_path(), {"t": now_ms(), **rec})


def read_journal() -> list[dict]:
    return _read_jsonl(journal_path())


def write_row(row: dict) -> None:
    p = ledger_path()
    with CP.LEDGER_LOCK:
        p.parent.mkdir(parents=True, exist_ok=True)
        new = not p.exists()
        with p.open("a", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=LEDGER_COLS, extrasaction="ignore")
            if new:
                w.writeheader()
            w.writerow({k: row.get(k, "") if row.get(k) is not None else "" for k in LEDGER_COLS})


def read_ledger() -> list[dict]:
    try:
        with ledger_path().open(newline="", encoding="utf-8") as fh:
            return list(csv.DictReader(fh))
    except OSError:
        return []


def rewrite_ledger(rows: list[dict]) -> None:
    p = ledger_path()
    with CP.LEDGER_LOCK:
        tmp = p.with_suffix(".tmp")
        with tmp.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=LEDGER_COLS, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
        tmp.replace(p)


def _i(v) -> int:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def _f(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- the chain

class Chain:
    """The reads a swap needs, over pumpfun_rt.live_exec.Rpc (plain https, no bundle or relay)."""

    def __init__(self, rpc: LX.Rpc):
        self.rpc = rpc

    def multiple(self, keys: list[str], commitment: str = "processed") -> dict[str, G.Account | None]:
        out: dict[str, G.Account | None] = {}
        keys = list(dict.fromkeys(keys))
        for i in range(0, len(keys), 100):
            part = keys[i:i + 100]
            res = self.rpc.call("getMultipleAccounts", [part, {"encoding": "base64", "commitment": commitment}])
            vals = (res or {}).get("value") or [None] * len(part)
            for k, v in zip(part, vals):
                out[k] = G.account_of(v)
        return out

    def tables(self, addrs: list[str]) -> dict[str, list[str]]:
        """The lookup tables' contents as the chain has them (never Jupiter's lists)."""
        out = {}
        for k, a in self.multiple(addrs, "confirmed").items():
            if a is None or a.owner != T.ALT_PROGRAM:
                raise RuntimeError(f"the lookup table {k[:8]} is not one")
            out[k] = T.parse_table(a.data)
        return out

    def token_accounts(self, owner: str) -> dict[str, G.Account]:
        out = {}
        for prog in (X.TOKEN, X.TOKEN_2022):
            res = self.rpc.call("getTokenAccountsByOwner", [owner, {"programId": prog},
                                                            {"encoding": "base64", "commitment": "confirmed"}])
            for v in (res or {}).get("value") or []:
                a = G.account_of((v or {}).get("account"))
                if a is not None and v.get("pubkey"):
                    out[str(v["pubkey"])] = a
        return out

    def blockhash(self) -> tuple[str, int]:
        v = self.rpc.call("getLatestBlockhash", [{"commitment": "confirmed"}])["value"]
        return v["blockhash"], int(v["lastValidBlockHeight"])

    def height(self) -> int:
        return int(self.rpc.call("getBlockHeight", [{"commitment": "confirmed"}]))

    def simulate(self, tx: bytes, addresses: list[str]) -> dict:
        import base64
        return self.rpc.call("simulateTransaction", [base64.b64encode(tx).decode(), {
            "encoding": "base64", "sigVerify": False, "replaceRecentBlockhash": False, "commitment": "processed",
            "accounts": {"encoding": "base64", "addresses": addresses}}]) or {}


# ---------------------------------------------------------------- the wallet's view

@dataclass
class View:
    """The wallet as the chain shows it now, with Jupiter's USD prices."""
    t: int
    sol_l: int
    tokens: dict[str, int]                       # raw units by mint (wSOL left out)
    prices: dict[str, float]                     # USD by mint
    frozen: list[str] = field(default_factory=list)

    def held(self, code: str) -> int:
        m = LG.CODES[code]
        return self.sol_l if m.mint == WSOL else self.tokens.get(m.mint, 0)

    def usd(self, code: str, raw: int | None = None) -> float | None:
        m = LG.CODES[code]
        p = self.prices.get(m.mint)
        if p is None:
            return None
        return (self.held(code) if raw is None else raw) / 10 ** m.decimals * p

    def total_usd(self) -> float | None:
        tot = 0.0
        for code in LG.CODES:
            if self.held(code) <= 0:
                continue
            v = self.usd(code)
            if v is None:
                return None
            tot += v
        return tot


def read_view(chain: Chain, wallet: str, prices_of) -> View:
    sol = int(chain.rpc.call("getBalance", [wallet, {"commitment": "confirmed"}])["value"])
    tokens: dict[str, int] = {}
    frozen = []
    for k, a in chain.token_accounts(wallet).items():
        t = G.parse_token(a.data) if a.owner == X.TOKEN else None
        if t is None:
            continue
        if len(a.data) == 165 and a.data[108] == 2:
            frozen.append(t.mint)
        if t.mint != WSOL:
            tokens[t.mint] = tokens.get(t.mint, 0) + t.amount
    return View(now_ms(), sol, tokens, prices_of([m.mint for m in LG.CODES.values()]), frozen)


def kraken_mid(code: str, fetch=None) -> float | None:
    """Kraken's mid in USD for a coin of the list (public ticker, read only); None when it has none."""
    pair = {"BTC": "XBTUSD"}.get(code, f"{code}USD")
    try:
        if fetch is not None:
            d = fetch(pair)
        else:
            req = urllib.request.Request(KRAKEN_URL + pair, headers={"User-Agent": "pythia-lab"})
            with urllib.request.urlopen(req, timeout=8) as r:
                d = json.loads(r.read().decode())
        v = next(iter((d.get("result") or {}).values()))
        return (float(v["a"][0]) + float(v["b"][0])) / 2
    except Exception:
        return None


# ---------------------------------------------------------------- one swap

@dataclass
class Swap:
    kind: str                                    # "convert" (the owner's, from the app), "book" or "kill" (on_kill=usdc)
    src: str                                     # coin codes of live_gate.CODES
    dst: str
    in_raw: int
    book: str | None = None
    ref: str | None = None                       # the convert's id
    min_out_raw: int = 0                         # a confirmed proposal's minimum: a new quote may not be worse
    signal_ms: int | None = None                 # when it was asked for: the owner's confirm, the signal file, the kill

    def record(self) -> dict:
        return {"kind": self.kind, "from": self.src, "to": self.dst, "in_raw": self.in_raw, "book": self.book,
                "ref": self.ref, "min_out_raw": self.min_out_raw}


@dataclass
class Prepared:
    plan: G.Plan
    build: S.Build
    message: bytes
    lvbh: int
    fees: dict
    effect: dict
    units: int | None
    in_usd: float | None
    out_usd: float | None
    cost_bps: float | None


def realised(day: int) -> dict:
    """The day's numbers, recomputed from the ledger (never counted up)."""
    out = {"swaps": 0, "book_swaps": {}, "converts": 0, "convert_usd": 0.0, "kill": 0, "fees_l": 0}
    for r in read_ledger():
        if day_of(_i(r.get("t"))) != day or r.get("status") not in ("filled", "failed"):
            continue
        out["swaps"] += 1
        out["fees_l"] += _i(r.get("fee_l"))
        if r.get("kind") == "convert":
            out["converts"] += 1
            out["convert_usd"] += _f(r.get("in_usd")) or 0.0
        elif r.get("kind") == "kill":
            out["kill"] += 1
        elif r.get("kind") == "book":
            out["book_swaps"][r.get("book")] = out["book_swaps"].get(r.get("book"), 0) + 1
    return out


def deposits_usd(day: int) -> float:
    return sum(_f(j.get("usd")) or 0.0 for j in read_journal() if j.get("kind") == "deposit"
               and day_of(_i(j.get("t"))) == day)


def days_path() -> Path:
    return LG.data_dir() / "days.json"


def day_start_usd(view: View, total: float | None) -> float | None:
    """The wallet's USD value at the first look of the UTC day (kept in days.json, so a restart keeps it)."""
    d = LX.read_json(days_path())
    d = d if isinstance(d, dict) else {}
    k = str(day_of(view.t))
    if k not in d and total is not None:
        d = {k: total, **{kk: v for kk, v in d.items() if _i(kk) >= day_of(view.t) - 30}}
        LX.write_json(days_path(), d)
    return _f(d.get(k))


def day_loss_usd(view: View, total: float | None) -> float | None:
    start = day_start_usd(view, total)
    if start is None or total is None:
        return None
    return start - (total - deposits_usd(day_of(view.t)))


class Trader:
    """Swaps for our wallet. `signer` is None for the dry run (simulate) and in the shadow; then nothing is sent."""

    def __init__(self, gate: LG.Gate, chain: Chain, jup: Jupiter, signer=None, sender: LX.Rpc | None = None,
                 tip_l: int = 0, prices=None, kraken=kraken_mid, clock=time.monotonic, sleep=time.sleep, on_wait=None):
        self.gate, self.chain, self.jup, self.signer = gate, chain, jup, signer
        self.sender, self.tip_l = sender, (tip_l if sender is not None else 0)
        self.prices_of = prices or Jupiter().prices
        self.kraken, self.clock, self.sleep, self.on_wait = kraken, clock, sleep, on_wait
        self.wallet = signer.pubkey if signer is not None else gate.address
        self.reconciled: dict | None = None
        self.idl = G.JupIdl(gate.idl) if gate.idl else G.JupIdl(None)

    # ------------------------------------------------ caps

    def caps(self, s: Swap, v: View, killed: bool | None = None) -> str | None:
        """Why this swap may not go now (None: it may), from the ack, the code's maxima and the real balances."""
        ack = self.gate.ack
        if ack.mode not in LG.MODES:
            return "no valid confirmation file"
        if s.src not in LG.CODES or s.dst not in LG.CODES or s.src == s.dst:
            return "not a swap between two coins of the list"
        if s.src not in ack.mints or s.dst not in ack.mints:
            return f"{s.src} or {s.dst} is not among the confirmation file's mints"
        if s.in_raw <= 0:
            return "nothing to swap"
        if v.held(s.src) < s.in_raw:
            return f"the wallet holds less {s.src} than the swap needs"
        if LG.CODES[s.src].mint in v.frozen or LG.CODES[s.dst].mint in v.frozen:
            return "a token account of this coin is frozen"
        in_usd = v.usd(s.src, s.in_raw)
        if in_usd is None:
            return f"no USD price for {s.src}"
        lim = ack.cap("trade")
        if s.src in LG.SMALL or s.dst in LG.SMALL:
            lim = min(lim, LG.SMALL_MAX_TRADE_USD)
        if in_usd > lim + 1e-9:
            return f"{in_usd:.2f} USD is above the {lim:g} USD a swap"
        selling = s.dst == "USDC"
        killed = LG.killed() if killed is None else killed
        if killed:
            if not (s.kind == "kill" and selling and ack.on_kill == "usdc"):
                return "the kill switch file is there"
        elif s.kind == "kill":
            return "a kill sale without the kill switch"
        total = v.total_usd()
        if total is None:
            return "the wallet's USD value is not known (a price is missing)"
        if not selling and total > ack.cap("total"):
            return f"the wallet is worth {total:.2f} USD, above max_total_usd: only sales into USDC"
        loss = day_loss_usd(v, total)
        if not selling and loss is not None and loss >= ack.cap("daily_loss"):
            return f"the day's loss reached {loss:.2f} USD: only sales into USDC until tomorrow (UTC)"
        if not selling and self.reconciled is not None and not self.reconciled.get("ok"):
            return "the ledger does not match the chain: no buys until it is explained"
        day = realised(day_of(v.t))
        if s.kind == "convert":
            if day["converts"] >= LG.MAX_CONVERTS_DAY:
                return f"already {LG.MAX_CONVERTS_DAY} converts today"
            if day["convert_usd"] + in_usd > ack.cap("convert") + 1e-9:
                return "the day's convert limit (max_convert_usd) would be passed"
        elif s.kind == "book":
            if s.book not in ack.books:
                return f"the confirmation file does not name {s.book}"
            if day["book_swaps"].get(s.book, 0) >= LG.MAX_BOOK_SWAPS_DAY:
                return f"already {LG.MAX_BOOK_SWAPS_DAY} swaps of {s.book} today"
        elif s.kind == "kill":
            if day["kill"] >= LG.MAX_BOOK_SWAPS_DAY:
                return f"already {LG.MAX_BOOK_SWAPS_DAY} kill sales today"
        else:
            return "an unknown kind of swap"
        if s.dst == "ETH":
            eth = (v.usd("ETH") or 0.0) + in_usd
            if eth > LG.MAX_ETH_SHARE * ack.cap("total"):
                return "ETH (WETH, bridged) would pass a quarter of max_total_usd"
        reserve = LG.RESERVE_L + G.MAX_PRIORITY_L + G.BASE_FEE_L + X.HELIUS_MAX_TIP_LAMPORTS + G.ATA_RENT_L
        spend = s.in_raw if s.src == SOL_CODE else 0
        if v.sol_l - spend < reserve:
            return "the swap would leave less than the SOL reserve for fees"
        return None

    # ------------------------------------------------ build, guard, simulate

    def _prices_ok(self, s: Swap, v: View, b: S.Build) -> tuple[float, float, float]:
        mi, mo = LG.CODES[s.src], LG.CODES[s.dst]
        pi, po = v.prices.get(mi.mint), v.prices.get(mo.mint)
        if not pi or not po:
            raise G.Refused("no Jupiter price for one side")
        for code, p in ((s.src, pi), (s.dst, po)):
            k = self.kraken(code)
            if k is None or k <= 0:
                raise G.Refused(f"no Kraken price for {code} to check Jupiter's against")
            if abs(p / k - 1) * 100 > LG.MAX_PRICE_GAP_PCT:
                raise G.Refused(f"Jupiter's {code} price is more than {LG.MAX_PRICE_GAP_PCT:g} % from Kraken's")
        in_usd = b.in_amount / 10 ** mi.decimals * pi
        out_usd = b.out_amount / 10 ** mo.decimals * po
        cost = (in_usd - out_usd) / in_usd * 1e4 if in_usd > 0 else 1e9
        if cost > LG.MAX_COST_BPS:
            raise G.Refused(f"the swap costs {cost:.0f} bps against Jupiter's prices (at most {LG.MAX_COST_BPS:g})")
        return in_usd, out_usd, cost

    def _compile(self, b: S.Build, units: int, price: int, blockhash: str, tables: dict) -> bytes:
        ixs = [X.compute_limit(units), X.compute_price(price)] + b.ixs()
        if self.sender is not None and self.tip_l:
            ixs.append(X.tip(self.wallet, random.choice(sorted(X.HELIUS_TIP_ACCOUNTS)), self.tip_l))
        return T.compile_v0(self.wallet, ixs, blockhash, tables)

    def _guarded_simulation(self, plan: G.Plan, msg_bytes: bytes, tables: dict) -> tuple[dict, dict, dict]:
        if 1 + 64 + len(msg_bytes) > T.MAX_TX_BYTES:
            raise OverflowError("the transaction is too large")
        msg = T.decompile(msg_bytes, tables)
        fees = G.check_message(plan, msg, self.idl, sender_tip_ok=self.sender is not None)
        writable = msg.writable_keys()
        G.check_accounts(plan, self.chain.multiple(writable))
        mine = list(self.chain.token_accounts(self.wallet))
        addrs = list(dict.fromkeys([self.wallet] + mine + sorted(plan.expected())))
        pre = self.chain.multiple(addrs)
        res = self.chain.simulate(T.unsigned(msg_bytes), addrs)
        val = res.get("value") if isinstance(res, dict) and "value" in res else res
        if not isinstance(val, dict):
            raise RuntimeError("no simulation result")
        if val.get("err") is not None:
            logs = [line for line in (val.get("logs") or []) if "rror" in line][-2:]
            raise RuntimeError(f"the simulation failed: {str(val.get('err'))[:120]} {' | '.join(logs)[:200]}")
        post = {k: G.account_of(a) for k, a in zip(addrs, val.get("accounts") or [])}
        if len(post) != len(addrs):
            raise RuntimeError("the simulation returned fewer accounts than asked")
        effect = G.check_effect(plan, pre, post, fees["max_fee_l"])
        effect["units"] = val.get("unitsConsumed")
        return fees, effect, val

    def prepare(self, s: Swap, v: View) -> Prepared:
        """Build, guard and simulate one swap for our wallet; raises on any refusal (nothing is signed)."""
        if not self.wallet:
            raise G.Refused("no wallet address")
        mi, mo = LG.CODES[s.src], LG.CODES[s.dst]
        slip = LG.slippage(s.src, s.dst)
        allowed = self.gate.ack.allowed_mints() or frozenset({M.SOL.mint, M.USDC.mint})
        for code, m in ((s.src, mi), (s.dst, mo)):
            G.check_mint(m.mint, self.chain.multiple([m.mint], "confirmed").get(m.mint))
        last: Exception | None = None
        for max_acc in S.MAX_ACCOUNTS:
            b = S.build(self.jup, mi.mint, mo.mint, s.in_raw, self.wallet, slip, max_acc)
            bad = [m for m in b.route_mints if m not in G.ROUTE_MINTS]
            if bad:
                raise G.Refused(f"the route passes through a mint not on the route list ({bad[0][:6]})")
            in_usd, out_usd, cost = self._prices_ok(s, v, b)
            ours = G.min_out(b.out_amount, slip)
            plan = G.Plan(self.wallet, mi.mint, mo.mint, s.in_raw, max(ours, s.min_out_raw), slip, allowed)
            if s.min_out_raw and ours < s.min_out_raw:
                raise G.Refused("the new quote is worse than the confirmed minimum")
            tables = self.chain.tables(b.tables)
            blockhash, lvbh = self.chain.blockhash()
            price = b.cu_price if b.cu_price else DEFAULT_CU_PRICE
            units = G.MAX_UNITS
            try:
                msg = self._compile(b, units, min(price, G.MAX_PRIORITY_L * 1_000_000 // units), blockhash, tables)
                fees, effect, val = self._guarded_simulation(plan, msg, tables)
            except OverflowError as e:
                last = e
                continue
            used = int(val.get("unitsConsumed") or 0)
            if used > 0:
                units = min(G.MAX_UNITS, max(100_000, int(used * 1.2) + 10_000))
                msg = self._compile(b, units, min(price, G.MAX_PRIORITY_L * 1_000_000 // units), blockhash, tables)
                fees, effect, val = self._guarded_simulation(plan, msg, tables)
            return Prepared(plan, b, msg, lvbh, fees, effect, used or None, in_usd, out_usd, cost)
        raise G.Refused(f"the transaction does not fit even with fewer accounts ({last})")

    # ------------------------------------------------ send and land

    def _send(self, tx: bytes) -> None:
        for name, r in (("Sender", self.sender), ("RPC", self.chain.rpc)):
            if r is None:
                continue
            try:
                r.send(tx, skip_preflight=True)
            except Exception as e:                       # the signature's status decides, not the answer
                print(f"onchain live: {name} did not take it ({type(e).__name__}: {e})"[:200], flush=True)

    def _land(self, tx: bytes, sig: str, lvbh: int) -> str:
        """'landed', 'err' (landed with an error, its fee paid) or 'expired' (the blockhash passed, never landed)."""
        t0 = self.clock()
        last_send = -1e18
        while True:
            now = self.clock()
            if now - last_send >= RESEND_S:
                self._send(tx)
                last_send = now
            try:
                st = self.chain.rpc.statuses([sig])[0]
            except Exception:
                st = None
            if LX.landed(st):
                return "err" if st.get("err") is not None else "landed"
            try:
                over = self.chain.height() > lvbh
            except Exception:
                over = False
            if over or now - t0 > LAND_MAX_S:
                try:
                    st = self.chain.rpc.statuses([sig])[0]
                except Exception:
                    st = None
                if LX.landed(st):
                    return "err" if st.get("err") is not None else "landed"
                if over:
                    return "expired"
                return "unknown"
            if self.on_wait:
                self.on_wait()
            self.sleep(STATUS_S)

    def _read_back(self, sig: str, s: Swap, tries: int = 10) -> dict | None:
        """What the landed transaction did to the wallet, from the chain (as chain_pnl does)."""
        mi, mo = LG.CODES[s.src], LG.CODES[s.dst]
        for _ in range(tries):
            try:
                res = self.chain.rpc.transaction(sig)
            except Exception:
                res = None
            if res:
                a = CP.tx_effect(res, self.wallet, None if mi.mint == WSOL else mi.mint)
                b = CP.tx_effect(res, self.wallet, None if mo.mint == WSOL else mo.mint)
                if a is not None and b is not None:
                    sol = a["delta_l"]
                    fee = a["fee_l"]
                    in_raw = -(sol + fee) if mi.mint == WSOL else -(a["tok"] or 0)
                    out_raw = (sol + fee) if mo.mint == WSOL else (b["tok"] or 0)
                    return {"sol_delta_l": sol, "fee_l": fee, "in_raw": in_raw, "out_raw": out_raw, "err": a["err"],
                            "block_ms": a.get("block_ms")}
            self.sleep(1.0)
        return None

    def execute(self, s: Swap, v: View, gate_why=None) -> dict:
        """One swap from caps to ledger. Returns {"status": filled | failed | refused, ...}."""
        if self.signer is None:
            return {"status": "refused", "why": "no signer (the gate was shut at start)"}
        log_order({"what": "planned", **s.record()})
        plan_ms = now_ms()
        why = self.caps(s, v)
        if why:
            log_order({"what": "refused", "why": why, **s.record()})
            return {"status": "refused", "why": why}
        for attempt in range(1, MAX_ATTEMPTS + 1):
            shut = gate_why() if gate_why else []
            if shut:
                log_order({"what": "refused", "why": "; ".join(shut), **s.record()})
                return {"status": "refused", "why": "; ".join(shut)}
            try:
                p = self.prepare(s, v)
            except (G.Refused, QuoteError, RuntimeError, ValueError, KeyError, TypeError, OSError) as e:
                why = f"{type(e).__name__}: {e}"[:300]
                log_order({"what": "refused", "attempt": attempt, "why": why, **s.record()})
                return {"status": "refused", "why": why}
            tx = T.transaction(p.message, self.signer.sign(p.message))
            sig = b58(tx[1:65])
            log_order({"what": "sent", "attempt": attempt, "sig": sig, "units": p.units, "fees": p.fees,
                       "expected_out": p.build.out_amount, "min_out_raw": p.plan.min_out_raw,
                       "cost_bps": p.cost_bps, "route": p.build.labels, **s.record()})
            sent_ms = now_ms()
            outcome = self._land(tx, sig, p.lvbh)
            seen_ms = now_ms()
            if outcome == "expired":
                log_order({"what": "expired", "attempt": attempt, "sig": sig, **s.record()})
                continue
            if outcome == "unknown":
                why = "no status after the waiting time; the ledger check settles it"
                log_order({"what": "failed", "attempt": attempt, "sig": sig, "why": why, **s.record()})
                self._row(s, p, sig, "failed", why, None)
                self._measure(s, p, v, sig, "failed", attempt, plan_ms, sent_ms, None, None)
                return {"status": "failed", "why": why, "sig": sig}
            back = self._read_back(sig, s)
            status = "filled" if outcome == "landed" else "failed"
            why = None if status == "filled" else "landed with an error (its fee is paid)"
            self._row(s, p, sig, status, why, back)
            self._measure(s, p, v, sig, status, attempt, plan_ms, sent_ms, seen_ms, back)
            log_order({"what": status, "attempt": attempt, "sig": sig, "why": why, **(back or {}), **s.record()})
            return {"status": status, "why": why, "sig": sig,
                    "out_raw": (back or {}).get("out_raw") if status == "filled" else None,
                    "in_usd": p.in_usd, "out_usd": p.out_usd}
        why = f"not landed after {MAX_ATTEMPTS} tries"
        log_order({"what": "failed", "why": why, **s.record()})
        return {"status": "failed", "why": why}

    def _row(self, s: Swap, p: Prepared, sig: str, status: str, why: str | None, back: dict | None) -> None:
        mo = LG.CODES[s.dst]
        out_usd = None
        if back and status == "filled":
            px = p.out_usd / (p.build.out_amount / 10 ** mo.decimals) if p.build.out_amount and p.out_usd else None
            out_usd = back["out_raw"] / 10 ** mo.decimals * px if px else None
        write_row({"t": now_ms(), "mode": self.gate.ack.mode, "kind": s.kind, "book": s.book, "ref": s.ref,
                   "from": s.src, "to": s.dst, "in_raw": (back or {}).get("in_raw", s.in_raw if status == "filled" else 0),
                   "out_raw": (back or {}).get("out_raw", 0) if status == "filled" else 0,
                   "sol_delta_l": (back or {}).get("sol_delta_l", ""), "fee_l": (back or {}).get("fee_l", ""),
                   "tip_l": p.fees.get("tip_l"), "in_usd": round(p.in_usd, 4) if p.in_usd is not None else "",
                   "out_usd": round(out_usd, 4) if out_usd is not None else "", "planned_out_raw": p.build.out_amount,
                   "min_out_raw": p.plan.min_out_raw, "sig": sig, "status": status, "why": why,
                   "unread": "" if back is not None else "1"})

    def _measure(self, s: Swap, p: Prepared, v: View, sig: str, status: str, attempt: int, plan_ms: int,
                 sent_ms: int, seen_ms: int | None, back: dict | None) -> None:
        """One sent swap's timing, fee and cost against its quote (live/onchain/execution.jsonl). Never raises."""
        try:
            fee = (back or {}).get("fee_l")
            tip = int(p.fees.get("tip_l") or 0)
            base = G.BASE_FEE_L if fee is not None else None
            out = (back or {}).get("out_raw") if status == "filled" else None
            planned = p.build.out_amount
            sol_usd = v.prices.get(M.SOL.mint)
            rec = {"t": now_ms(), "mode": self.gate.ack.mode, "kind": s.kind, "book": s.book, "ref": s.ref,
                   "from": s.src, "to": s.dst, "sig": sig, "status": status, "attempt": attempt,
                   "via": "sender+rpc" if self.sender is not None else "rpc",
                   "signal_ms": s.signal_ms, "plan_ms": plan_ms, "sent_ms": sent_ms, "seen_ms": seen_ms,
                   "block_ms": (back or {}).get("block_ms"),
                   "signal_to_send_ms": sent_ms - s.signal_ms if s.signal_ms else None,
                   "plan_to_send_ms": sent_ms - plan_ms,
                   "send_to_land_ms": seen_ms - sent_ms if seen_ms is not None else None,
                   "fee_l": fee, "base_l": base, "priority_l": max(int(fee) - base, 0) if fee is not None else None,
                   "tip_l": tip, "sol_usd": sol_usd, "in_raw": s.in_raw, "planned_out_raw": planned, "out_raw": out,
                   "quote_slip_bps": round((planned - out) / planned * 1e4, 3) if out is not None and planned else None,
                   "cost_bps": round(p.cost_bps, 3) if p.cost_bps is not None else None,
                   "in_usd": round(p.in_usd, 4) if p.in_usd is not None else None,
                   "out_usd": round(p.out_usd * out / planned, 4) if out is not None and planned and p.out_usd else None}
            _append_jsonl(execution_path(), rec)
        except Exception as e:                           # a measurement never stops a swap's booking
            print(f"onchain live: execution not measured ({type(e).__name__}: {e})"[:200], flush=True)

    # ------------------------------------------------ the ledger against the chain

    def reread(self) -> int:
        """Rows whose transaction could not be read yet, read again (as chain_pnl does). Returns how many."""
        rows = read_ledger()
        n = 0
        for r in rows:
            if r.get("unread") != "1" or not r.get("sig"):
                continue
            s = Swap(r.get("kind") or "", r.get("from") or "", r.get("to") or "", _i(r.get("in_raw")))
            if s.src not in LG.CODES or s.dst not in LG.CODES:
                continue
            back = self._read_back(r["sig"], s, tries=1)
            if back is None:
                if now_ms() - _i(r.get("t")) > CP.GONE_MS and r.get("status") == "failed":
                    r.update(unread="", in_raw=0, out_raw=0, sol_delta_l=0, fee_l=0, why=(r.get("why") or "") +
                             "; never landed")
                    n += 1
                continue
            filled = back.get("err") is None
            r.update(unread="", sol_delta_l=back["sol_delta_l"], fee_l=back["fee_l"],
                     in_raw=back["in_raw"] if filled else 0, out_raw=back["out_raw"] if filled else 0,
                     status="filled" if filled else "failed")
            n += 1
        if n:
            rewrite_ledger(rows)
        return n


def expected_holdings() -> tuple[dict | None, bool]:
    """What the wallet should hold: the last baseline, plus every swap row after it, plus the deposits after it.
    Returns ({"sol_l", "tokens"}, whether every row is read back)."""
    base = None
    j = read_journal()
    for e in j:
        if e.get("kind") == "baseline":
            base = e
    if base is None:
        return None, True
    t0 = _i(base.get("t"))
    sol = _i(base.get("sol_l"))
    tok = {k: _i(v) for k, v in (base.get("tokens") or {}).items()}
    complete = True
    for r in read_ledger():
        if _i(r.get("t")) < t0:
            continue
        if r.get("unread") == "1":
            complete = False
            continue
        sol += _i(r.get("sol_delta_l"))
        if r.get("status") != "filled":
            continue
        for code, sign, k in ((r.get("from"), -1, "in_raw"), (r.get("to"), 1, "out_raw")):
            m = LG.CODES.get(code or "")
            if m is not None and m.mint != WSOL:
                tok[m.mint] = tok.get(m.mint, 0) + sign * _i(r.get(k))
    for e in j:
        if e.get("kind") in ("deposit", "unexplained") and _i(e.get("t")) >= t0:
            if e.get("mint") == WSOL:
                sol += _i(e.get("raw"))
            elif e.get("mint"):
                tok[e["mint"]] = tok.get(e["mint"], 0) + _i(e.get("raw"))
    return {"sol_l": sol, "tokens": tok}, complete


def baseline(v: View) -> None:
    journal({"kind": "baseline", "sol_l": v.sol_l, "tokens": dict(v.tokens)})


def reconcile(v: View) -> dict:
    """The ledger against the chain. A rise is the owner's deposit (journaled, valued at today's price); a fall
    that no swap explains is journaled as unexplained once and keeps `ok` false until the next start."""
    exp, complete = expected_holdings()
    if exp is None:
        baseline(v)
        return {"t": v.t, "ok": True, "diffs": []}
    if not complete:
        return {"t": v.t, "ok": True, "diffs": [], "pending": True}
    diffs, bad = [], False
    checks = [(WSOL, v.sol_l, exp["sol_l"])] + [(m, v.tokens.get(m, 0), exp["tokens"].get(m, 0))
                                                 for m in set(v.tokens) | set(exp["tokens"])]
    for mint, have, want in checks:
        d = have - want
        if d == 0:
            continue
        mm = M.BY_MINT.get(mint)
        usd = d / 10 ** mm.decimals * v.prices.get(mint, 0.0) if mm else None
        if d > 0:
            journal({"kind": "deposit", "mint": mint, "raw": d, "usd": round(usd, 4) if usd is not None else None})
            continue
        sym = mm.coin if mm else mint[:6]
        diffs.append(f"{sym}: {d} raw units fewer than the ledger explains")
        journal({"kind": "unexplained", "mint": mint, "raw": d, "usd": round(usd, 4) if usd is not None else None})
        bad = True
    if any(e.get("kind") == "unexplained" and _i(e.get("t")) >= _base_t() for e in read_journal()):
        bad = True
    return {"t": v.t, "ok": not bad, "diffs": diffs}


def _base_t() -> int:
    t = 0
    for e in read_journal():
        if e.get("kind") == "baseline":
            t = _i(e.get("t"))
    return t


# ---------------------------------------------------------------- a book's swaps

def book_state(book: str, book_usd: float) -> dict:
    """The book's part of the wallet, from its filled ledger rows: USDC and coin units (raw)."""
    usdc = int(book_usd * 10 ** M.USDC.decimals)
    units: dict[str, int] = {}
    for r in read_ledger():
        if r.get("kind") != "book" or r.get("book") != book or r.get("status") != "filled":
            continue
        for code, sign, k in ((r.get("from"), -1, "in_raw"), (r.get("to"), 1, "out_raw")):
            if code == "USDC":
                usdc += sign * _i(r.get(k))
            elif code in LG.CODES:
                units[code] = units.get(code, 0) + sign * _i(r.get(k))
    return {"usdc_raw": usdc, "units": {c: u for c, u in units.items() if u > 0}}


def book_swaps(book: str, ack: LG.Ack, v: View, weights: dict) -> list[Swap]:
    """The swaps that bring the book's part to the signal's weights: sales first, then buys out of the book's
    USDC; nothing under MIN_BOOK_SWAP_USD, nothing beyond what the wallet really holds, only allowed coins."""
    from . import book as B
    st = book_state(book, ack.book_usd)
    tgt, _ = B.split_targets(weights)
    tgt = {c: w for c, w in tgt.items() if c in ack.mints}
    marks = {}
    for c in set(st["units"]) | set(tgt):
        m = LG.CODES[c]
        if v.prices.get(m.mint) and v.prices.get(M.USDC.mint):
            marks[c] = v.prices[m.mint] / v.prices[M.USDC.mint]
    paper = {"usdc": st["usdc_raw"] / 1e6, "marks": marks,
             "units": {c: u / 10 ** LG.CODES[c].decimals for c, u in st["units"].items()}}
    equity = paper["usdc"] + sum(u * marks.get(c, 0.0) for c, u in paper["units"].items())
    sells, buys = B.plan(paper, tgt, equity, LG.MIN_BOOK_SWAP_USD)

    def pieces(c: str, raw: int, usd: float | None) -> list[int]:
        """An order above the swap cap (25 USD in the alpha mode) as several swaps, each under it with room."""
        lim = min(ack.cap("trade"), LG.SMALL_MAX_TRADE_USD) if c in LG.SMALL else ack.cap("trade")
        if not usd or lim <= 0 or usd <= lim * 0.98:
            return [raw]
        n = math.ceil(usd / (lim * 0.98))
        part = raw // n
        return [part] * (n - 1) + [raw - part * (n - 1)]

    out = []
    for c, units in sells:
        raw = min(int(units * 10 ** LG.CODES[c].decimals), st["units"].get(c, 0), v.held(c))
        if raw > 0:
            out += [Swap("book", c, "USDC", r, book=book) for r in pieces(c, raw, v.usd(c, raw))]
    cash = min(st["usdc_raw"], v.held("USDC"))
    for c, usdc in buys:
        raw = min(int(usdc * 1e6), cash)
        if raw >= LG.MIN_BOOK_SWAP_USD * 1e6:
            out += [Swap("book", "USDC", c, r, book=book) for r in pieces(c, raw, raw / 1e6)]
            cash -= raw
    return out


# ---------------------------------------------------------------- the dry run and the gate check

def setup(gate: LG.Gate, signer=None, rpc: LX.Rpc | None = None, on_wait=None) -> Trader:
    rpc = rpc or LX.Rpc(gate.env.get(LG.ENV_RPC) or LG.DEFAULT_RPC)
    s = gate.sender()
    sender = LX.Rpc(s) if s else None
    return Trader(gate, Chain(rpc), S.client(gate.env), signer=signer, sender=sender,
                  tip_l=LG.sender_tip_lamports(gate.env) if sender else 0, on_wait=on_wait)


def simulate(gate: LG.Gate, trader: Trader | None = None, usd: float = 10.0) -> dict:
    """SOL to USDC and, when the wallet holds USDC, USDC to SOL, `usd` each: built for the wallet's public address,
    guarded and simulated on mainnet. Nothing is signed or sent. Writes live/onchain/simulate.json."""
    gate.check()
    rec = {"t": now_ms(), "ok": False, "pubkey": gate.address, "swaps": [], "sender_tip_l": 0}
    if not gate.address:
        rec["why"] = f"no public address next to {LG.ENV_KEYPAIR}"
        LX.write_json(LG.simulate_path(), rec)
        return rec
    tr = trader or setup(gate)
    tr.wallet = gate.address
    rec["sender_tip_l"] = tr.tip_l
    try:
        v = read_view(tr.chain, gate.address, tr.prices_of)
    except Exception as e:
        rec["why"] = f"the wallet could not be read ({type(e).__name__}: {e})"[:300]
        LX.write_json(LG.simulate_path(), rec)
        return rec
    tries = []
    psol, pusdc = v.prices.get(M.SOL.mint), v.prices.get(M.USDC.mint)
    if psol:
        tries.append(Swap("convert", "SOL", "USDC", M.raw(M.SOL, usd / psol)))
    if pusdc and v.held("USDC") >= M.raw(M.USDC, usd / pusdc):
        tries.append(Swap("convert", "USDC", "SOL", M.raw(M.USDC, usd / pusdc)))
    ok = bool(tries)
    for s in tries:
        one = {"from": s.src, "to": s.dst, "in_raw": s.in_raw}
        try:
            p = tr.prepare(s, v)
            one.update(ok=True, units=p.units, fees=p.fees, expected_out=p.build.out_amount,
                       min_out_raw=p.plan.min_out_raw, cost_bps=p.cost_bps, route=p.build.labels)
        except Exception as e:
            one.update(ok=False, why=f"{type(e).__name__}: {e}"[:300])
            ok = False
        rec["swaps"].append(one)
    rec["ok"] = ok
    if not tries:
        rec["why"] = "no price for SOL"
    LX.write_json(LG.simulate_path(), rec)
    return rec


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="the stage-2 on-chain trader (locked until the owner arms it)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check", help="every gate, and why it is shut")
    sm = sub.add_parser("simulate", help="build, guard and simulate two small swaps for this wallet; never sends")
    sm.add_argument("--usd", type=float, default=10.0)
    a = ap.parse_args(argv)
    gate = LG.Gate()
    if a.cmd == "check":
        why = gate.check()
        print("on-chain live: " + (f"every gate holds ({gate.ack.mode} mode)" if not why else
                                    "LOCKED:\n  - " + "\n  - ".join(why)))
        return 0 if not why else 1
    rec = simulate(gate, usd=min(max(a.usd, 1.0), 25.0))
    print(json.dumps(rec, indent=1, default=str))
    return 0 if rec.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
