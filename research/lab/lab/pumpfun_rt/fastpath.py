"""The fast path: from a token's creation event to a signed buy, in microseconds. PAPER AND DRY RUN ONLY.

Nothing here sends anything: a signed transaction leaves this module only as bytes
(and base64) for a sender, and the only senders here are the dry-run recorders.
Real sending stays in live_exec.py (LOCKED, see docs/PUMPFUN-LIVE.md); the signer
in this module's benchmark and dry run is a fake that hashes the message.

    python -m lab.pumpfun_rt.fastpath bench                 10,000 synthetic creations, internal latency
    python -m lab.pumpfun_rt.fastpath bench --capture 60    plus creation messages from the live stream
    python -m lab.pumpfun_rt.fastpath dryrun --seconds 60   the stream, built and signed (fake), nothing sent

The pieces (results/pumpfun_speed_plan.md, section 5):

  Static         the wallet's own and the programs' fixed accounts, derived once
  MintTemplate   per new mint, made from the creation event alone (bonding curve, creator, token
                 program are in it; the mint's associated accounts and the creator vault derived
                 here): the buy and the sale compiled once (txbuild.compile_template), so a signal
                 only patches the amounts, the compute-unit price and the blockhash
  BlockhashCache a recent blockhash, refreshed every BLOCKHASH_S (read-only RPC)
  FeeEstimator   the compute-unit price from recent prioritization fees of the pump.fun accounts
                 (percentile FEE_PCT), between a floor and the owner's cap
  FastPath       raw websocket message -> decode -> template -> patch -> sign -> transaction bytes,
                 each stage timed from the message's receipt
  DryRunSender   what a parallel send to several endpoints (and, behind PYTHIA_PUMPFUN_JITO=1, a
                 Jito block engine with our own tipped transaction) would have done; records only

The Jito path is only ever our OWN single buy or sale with a tip instruction inside it
(txbuild.tip, checked by txbuild.check_own(tip_ok=True)): no bundle with anyone else's
transaction, no sandwich, no front-running of other users.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import statistics
import struct
import sys
import time
import urllib.request
from collections import OrderedDict
from dataclasses import dataclass, field

from . import curve as C
from . import events as E
from . import txbuild as X

BLOCKHASH_S = 20.0
FEE_EVERY_S = 10.0
FEE_PCT = 75
FEE_FLOOR_MICRO = 10_000                    # micro-lamports per compute unit
HARD_MAX_PRIORITY_SOL = 0.01                # per transaction, whatever a setting says
TEMPLATES_MAX = 20_000
READ_METHODS = frozenset({"getLatestBlockhash", "getRecentPrioritizationFees", "getAccountInfo", "getSlot"})
JITO_ENV = "PYTHIA_PUMPFUN_JITO"


def jito_on(env=None) -> bool:
    env = os.environ if env is None else env
    return env.get(JITO_ENV) == "1"


def send_endpoints(env=None) -> list[str]:
    """The RPC endpoints a live send would go to in parallel: PYTHIA_PUMPFUN_RPC_URLS (comma separated, each
    checked by live_exec's gate), else PYTHIA_PUMPFUN_RPC, else the public endpoint."""
    env = os.environ if env is None else env
    urls = [u.strip() for u in (env.get("PYTHIA_PUMPFUN_RPC_URLS") or "").split(",") if u.strip()]
    return urls or [env.get("PYTHIA_PUMPFUN_RPC") or "https://api.mainnet-beta.solana.com"]


def max_priority_sol(env=None) -> float:
    env = os.environ if env is None else env
    try:
        v = float(env.get("PYTHIA_PUMPFUN_MAX_PRIORITY_SOL", "0.005"))
    except ValueError:
        v = 0.005
    return min(max(v, 0.0), HARD_MAX_PRIORITY_SOL)


# ---------------------------------------------------------------- read-only RPC

def rpc_reader(url: str, timeout: float = 5.0):
    """A read-only JSON-RPC caller: only the methods in READ_METHODS (nothing that changes the chain)."""
    def call(method: str, params: list):
        if method not in READ_METHODS:
            raise ValueError(f"{method} is not a read-only method")
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.loads(r.read())
        if "error" in d:
            raise RuntimeError(str(d["error"])[:200])
        return d.get("result")
    return call


class BlockhashCache:
    """A recent blockhash, refreshed when older than every_s (a blockhash is good for about a minute)."""

    def __init__(self, call, every_s: float = BLOCKHASH_S, clock=time.monotonic):
        self.call, self.every, self.clock = call, every_s, clock
        self.value: bytes | None = None
        self.text: str | None = None
        self.at = -1e18
        self.refreshes = 0
        self.errors = 0

    def refresh(self) -> None:
        try:
            r = self.call("getLatestBlockhash", [{"commitment": "confirmed"}])
            h = (r.get("value") or {}).get("blockhash")
            self.value, self.text, self.at = X.key(h), h, self.clock()
            self.refreshes += 1
        except Exception:                                    # keep the last one; the age shows it
            self.errors += 1

    def tick(self) -> None:
        if self.clock() - self.at >= self.every:
            self.refresh()

    def get(self) -> bytes:
        if self.value is None:
            self.refresh()
        if self.value is None:
            raise RuntimeError("no blockhash yet")
        return self.value

    def age_s(self) -> float:
        return self.clock() - self.at


class FeeEstimator:
    """The compute-unit price (micro-lamports) from recent prioritization fees of the given accounts: the
    FEE_PCT percentile of the non-zero ones, at least the floor, at most what keeps the transaction's
    priority fee under the owner's cap (max_priority_sol)."""

    def __init__(self, call, accounts: list[str], units: int = X.UNITS, pct: int = FEE_PCT,
                 floor: int = FEE_FLOOR_MICRO, cap_sol: float | None = None, every_s: float = FEE_EVERY_S,
                 clock=time.monotonic):
        self.call, self.accounts, self.units, self.pct, self.floor = call, accounts, units, pct, floor
        cap_sol = max_priority_sol() if cap_sol is None else min(cap_sol, HARD_MAX_PRIORITY_SOL)
        self.cap = int(cap_sol * C.LAMPORTS * 1_000_000 // max(1, units))
        self.every, self.clock = every_s, clock
        self.value = floor
        self.at = -1e18

    def refresh(self) -> None:
        try:
            rows = self.call("getRecentPrioritizationFees", [self.accounts]) or []
            fees = sorted(int(r.get("prioritizationFee") or 0) for r in rows)
            fees = [f for f in fees if f > 0]
            if fees:
                k = min(len(fees) - 1, int(round((len(fees) - 1) * self.pct / 100)))
                self.value = fees[k]
            self.at = self.clock()
        except Exception:
            pass

    def tick(self) -> None:
        if self.clock() - self.at >= self.every:
            self.refresh()

    def micro(self) -> int:
        return int(min(self.cap, max(self.floor, self.value)))

    def priority_lamports(self) -> int:
        return self.micro() * self.units // 1_000_000


# ---------------------------------------------------------------- templates

@dataclass
class Static:
    """The wallet and the programs' fixed accounts, derived once."""
    user: str
    buyback_recipient: str = X.BUYBACK_FEE_RECIPIENTS[0]     # a listed one (pump.fun's Global names them)

    def __post_init__(self):
        for seeds in ([b"global"], [b"__event_authority"], [b"user_volume_accumulator", X.key(self.user)]):
            X.pda(seeds, X.PUMP)
        X.pda([b"fee_config", X.key(X.PUMP)], X.FEE_PROGRAM)
        X.ata(self.user, X.WSOL, X.TOKEN)


@dataclass
class MintTemplate:
    mint: str
    buy: X.Compiled
    sell: X.Compiled
    buy_ixs: list = field(repr=False)
    sell_ixs: list = field(repr=False)
    tip_at: int | None = None              # the tip instruction's index in buy_ixs, when there is one

    @classmethod
    def from_create(cls, ev: dict, st: Static, tip_account: str | None = None, tip_ok: bool = False) -> "MintTemplate":
        """Both trades of a new mint from its creation event alone (nothing read over RPC)."""
        info = X.CurveInfo(ev["mint"], ev.get("token_program") or X.TOKEN, st.buyback_recipient,
                           cashback=bool(ev.get("is_cashback_enabled")))
        buy = X.pump_buy(st.user, info, 1, 1, 1)
        tip_at = None
        if tip_account is not None:
            buy = buy + [X.tip(st.user, tip_account, 1)]
            tip_at = len(buy) - 1
        sell = X.pump_sell(st.user, info, 1, 0, 1, close=True)
        X.check_own(st.user, buy, tip_ok=tip_ok)
        X.check_own(st.user, sell, tip_ok=False)
        return cls(ev["mint"], X.compile_template(st.user, buy), X.compile_template(st.user, sell), buy, sell, tip_at)

    @staticmethod
    def _patch(c: X.Compiled, ixs: list, blockhash: bytes, micro: int, data: dict[int, bytes]) -> bytes:
        m = bytearray(c.message)
        m[c.blockhash_at:c.blockhash_at + 32] = blockhash
        for i, ix in enumerate(ixs):                       # the compute-unit price
            if ix.program == X.COMPUTE_BUDGET and ix.data[:1] == b"\x03":
                o = c.data_at[i]
                m[o + 1:o + 9] = struct.pack("<Q", micro)
        for i, b in data.items():
            o = c.data_at[i]
            m[o:o + len(b)] = b
        return bytes(m)

    def buy_message(self, tokens: int, max_cost_l: int, blockhash: bytes, micro: int, tip_l: int = 0) -> bytes:
        k = next(i for i, ix in enumerate(self.buy_ixs) if ix.program == X.PUMP)
        data = {k: self.buy_ixs[k].data[:8] + struct.pack("<QQ", tokens, max_cost_l)}
        if self.tip_at is not None:
            if not 0 < tip_l <= X.MAX_TIP_LAMPORTS:
                raise ValueError("a tip must be above zero and at most the hard cap")
            data[self.tip_at] = struct.pack("<IQ", 2, tip_l)
        return self._patch(self.buy, self.buy_ixs, blockhash, micro, data)

    def sell_message(self, tokens: int, min_out_l: int, blockhash: bytes, micro: int) -> bytes:
        k = next(i for i, ix in enumerate(self.sell_ixs) if ix.program == X.PUMP)
        data = {k: self.sell_ixs[k].data[:8] + struct.pack("<QQ", tokens, min_out_l)}
        return self._patch(self.sell, self.sell_ixs, blockhash, micro, data)


class FakeSigner:
    """A stand-in signer for the benchmark, the dry run and the tests: 64 bytes of a hash, no key."""

    def __init__(self, pubkey: str):
        self.pubkey = pubkey

    def sign(self, message: bytes) -> bytes:
        return hashlib.blake2b(message, digest_size=64).digest()


# ---------------------------------------------------------------- the path

@dataclass
class Ready:
    mint: str
    slot: int
    tx_b64: str
    tokens: int
    max_cost_l: int
    bts: int | None
    us: dict                                # stage -> microseconds after the receipt


class FastPath:
    """Raw creation message in, a signed buy out, every stage timed (perf_counter_ns from the receipt)."""

    def __init__(self, st: Static, signer, blockhashes: BlockhashCache, fees: FeeEstimator,
                 stake_l: int = int(0.1 * C.LAMPORTS), slip: float = C.SLIP_TOL, accept=None,
                 tip_account: str | None = None, tip_l: int = 0, jito: bool = False):
        if tip_account is not None and not jito:
            raise ValueError("a tip needs the owner's PYTHIA_PUMPFUN_JITO=1")
        if tip_account is not None and tip_account not in X.JITO_TIP_ACCOUNTS:
            raise ValueError("not a published Jito tip account")
        self.st, self.signer, self.bh, self.fees = st, signer, blockhashes, fees
        self.stake, self.slip, self.accept = stake_l, slip, accept
        self.tip_account, self.tip_l, self.jito = tip_account, tip_l, jito
        self.templates: OrderedDict[str, MintTemplate] = OrderedDict()
        self.skipped: dict[str, int] = {}

    def template(self, ev: dict) -> MintTemplate:
        t = self.templates.get(ev["mint"])
        if t is None:
            t = MintTemplate.from_create(ev, self.st, self.tip_account, self.jito)
            self.templates[ev["mint"]] = t
            if len(self.templates) > TEMPLATES_MAX:
                self.templates.popitem(last=False)
        return t

    def _skip(self, why: str) -> None:
        self.skipped[why] = self.skipped.get(why, 0) + 1

    def on_message(self, text: str, t0_ns: int | None = None) -> Ready | None:
        t0 = t0_ns if t0_ns is not None else time.perf_counter_ns()
        try:
            d = json.loads(text)
            res = d["params"]["result"]
        except (ValueError, KeyError, TypeError):
            return None
        v = res.get("value") or {}
        if v.get("err") is not None:
            return None
        t_parse = time.perf_counter_ns()
        evs = E.events_of(v.get("logs") or [])
        create = next((ev for n, ev in evs if n == "CreateEvent"), None)
        if create is None:
            return None
        mint = create["mint"]
        if create.get("is_mayhem_mode") or create.get("is_cashback_enabled") or \
                not E.sol_quoted(create.get("quote_mint")):
            self._skip("not a plain SOL curve")
            return None
        vs, vt, rt = (create.get("virtual_sol_reserves") or 0, create.get("virtual_token_reserves") or 0,
                      create.get("real_token_reserves") or 0)
        fee_bps, dev_l = C.DEFAULT_FEE_BPS, 0
        for n, ev in evs:                                     # the creation transaction's own buys (the dev buy)
            if n == "TradeEvent" and ev.get("mint") == mint:
                vs, vt, rt = ev["virtual_sol_reserves"], ev["virtual_token_reserves"], ev["real_token_reserves"]
                fee_bps = int(ev.get("fee_basis_points") or 0) + int(ev.get("creator_fee_basis_points") or 0) or fee_bps
                if ev.get("is_buy"):
                    dev_l += int(ev.get("sol_amount") or 0)
        t_decode = time.perf_counter_ns()
        if self.accept is not None and not self.accept(create, dev_l):
            self._skip("filter")
            return None
        tpl = self.template(create)
        t_tpl = time.perf_counter_ns()
        want = C.curve_buy(self.stake, vs, vt, rt, fee_bps)
        if want <= 0:
            self._skip("nothing to buy")
            return None
        max_cost = int(self.stake * (1 + self.slip))
        msg = tpl.buy_message(want, max_cost, self.bh.get(), self.fees.micro(), self.tip_l)
        t_build = time.perf_counter_ns()
        tx = X.transaction(msg, [self.signer.sign(msg)])
        t_sign = time.perf_counter_ns()
        b64 = base64.b64encode(tx).decode()
        t_end = time.perf_counter_ns()
        us = {"parse": (t_parse - t0) / 1e3, "decode": (t_decode - t0) / 1e3, "template": (t_tpl - t0) / 1e3,
              "build": (t_build - t0) / 1e3, "sign": (t_sign - t0) / 1e3, "ready": (t_end - t0) / 1e3,
              "template_only": (t_tpl - t_decode) / 1e3}
        return Ready(mint, int((res.get("context") or {}).get("slot") or 0), b64, want, max_cost,
                     create.get("timestamp"), us)

    def sell(self, mint: str, tokens: int, min_out_l: int, t0_ns: int | None = None) -> tuple[str, float] | None:
        """A sale with the mint's ready template: (base64 transaction, microseconds from t0)."""
        t0 = t0_ns if t0_ns is not None else time.perf_counter_ns()
        tpl = self.templates.get(mint)
        if tpl is None:
            return None
        msg = tpl.sell_message(tokens, min_out_l, self.bh.get(), self.fees.micro())
        tx = X.transaction(msg, [self.signer.sign(msg)])
        return base64.b64encode(tx).decode(), (time.perf_counter_ns() - t0) / 1e3


class DryRunSender:
    """Records what a parallel send would have done: one copy per endpoint (and the Jito engine when the
    owner's flag is on), never a network call."""

    def __init__(self, endpoints: list[str], jito_url: str | None = None, env=None):
        self.endpoints = list(endpoints)
        self.jito_url = jito_url if (jito_url and jito_on(env)) else None
        self.log: list[dict] = []

    def submit(self, tx_b64: str, mint: str) -> dict:
        targets = len(self.endpoints) + (1 if self.jito_url else 0)
        rec = {"mint": mint, "bytes": len(base64.b64decode(tx_b64)), "targets": targets, "sent": False}
        self.log.append(rec)
        return rec


# ---------------------------------------------------------------- the benchmark

def synthetic_message(i: int, slot: int = 1_000, dev_sol: float = 1.0) -> str:
    """A logsSubscribe notification of a creation with a dev buy, as the stream sends it."""
    h = hashlib.sha256(str(i).encode()).digest()
    mint, creator = E.b58(h), E.b58(hashlib.sha256(h).digest())
    vs0, vt0, rt0 = 30 * C.LAMPORTS, 1_073_000_000 * C.TOKEN_UNIT, 793_100_000 * C.TOKEN_UNIT
    sol = int(dev_sol * C.LAMPORTS)
    tok = C.curve_buy(sol, vs0, vt0, rt0, 0)
    create = E.encode("CreateEvent", {"name": f"T{i}", "symbol": "T", "uri": "https://x/" + str(i), "mint": mint,
                                      "bonding_curve": X.pda([b"bonding-curve", X.key(mint)], X.PUMP),
                                      "user": creator, "creator": creator, "timestamp": 1_792_500_000,
                                      "virtual_token_reserves": vt0, "virtual_sol_reserves": vs0,
                                      "real_token_reserves": rt0, "token_total_supply": 10 ** 15,
                                      "token_program": X.TOKEN})
    trade = E.encode("TradeEvent", {"mint": mint, "sol_amount": sol, "token_amount": tok, "is_buy": True,
                                    "user": creator, "timestamp": 1_792_500_000, "virtual_sol_reserves": vs0 + sol,
                                    "virtual_token_reserves": vt0 - tok, "real_sol_reserves": sol,
                                    "real_token_reserves": rt0 - tok, "fee_basis_points": 95,
                                    "creator_fee_basis_points": 30})
    logs = ["Program ComputeBudget111111111111111111111111111111 invoke [1]",
            "Program ComputeBudget111111111111111111111111111111 success",
            f"Program {E.PUMP} invoke [1]", "Program log: Instruction: Create",
            "Program data: " + base64.b64encode(create).decode(), f"Program {E.PUMP} success",
            f"Program {E.PUMP} invoke [1]", "Program log: Instruction: Buy",
            "Program data: " + base64.b64encode(trade).decode(), f"Program {E.PUMP} success"]
    sig = E.b58(hashlib.sha512(h).digest())
    return json.dumps({"jsonrpc": "2.0", "method": "logsNotification",
                       "params": {"result": {"context": {"slot": slot}, "value": {"signature": sig, "err": None,
                                                                                "logs": logs}},
                                  "subscription": 1}})


def _fixed_rpc():
    """A stand-in for the read-only RPC in the benchmark: a fixed blockhash and a fee list."""
    bh = E.b58(hashlib.sha256(b"blockhash").digest())

    def call(method, params):
        if method == "getLatestBlockhash":
            return {"value": {"blockhash": bh, "lastValidBlockHeight": 1}}
        if method == "getRecentPrioritizationFees":
            return [{"slot": i, "prioritizationFee": 1_000 * i} for i in range(150)]
        raise ValueError(method)
    return call


def bench_path(user: str | None = None, tip: bool = False) -> FastPath:
    user = user or E.b58(hashlib.sha256(b"bench-wallet").digest())
    call = _fixed_rpc()
    st = Static(user)
    tip_acct = sorted(X.JITO_TIP_ACCOUNTS)[0] if tip else None
    return FastPath(st, FakeSigner(user), BlockhashCache(call), FeeEstimator(call, [E.PUMP], cap_sol=0.005),
                    tip_account=tip_acct, tip_l=100_000 if tip else 0, jito=tip)


def _summ(xs: list[float]) -> dict:
    xs = sorted(xs)
    if not xs:
        return {}
    q = lambda p: xs[min(len(xs) - 1, int(p * (len(xs) - 1)))]         # noqa: E731
    return {"n": len(xs), "p50": q(0.5), "p90": q(0.9), "p99": q(0.99), "max": xs[-1],
            "mean": statistics.fmean(xs)}


def bench(n: int = 10_000, messages: list[str] | None = None, tip: bool = False, first: int = 0) -> dict:
    """Internal latency of the fast path: receipt of the raw message to a signed transaction (fake signer),
    for a new mint each time (the template built on the path) and for a sale with a ready template."""
    fp = bench_path(tip=tip)
    fp.bh.get()
    msgs = messages if messages is not None else [synthetic_message(i) for i in range(first, first + n)]
    stages: dict[str, list] = {}
    sells = []
    for text in msgs:
        t0 = time.perf_counter_ns()
        r = fp.on_message(text, t0)
        if r is None:
            continue
        for k, v in r.us.items():
            stages.setdefault(k, []).append(v)
        s = fp.sell(r.mint, r.tokens, 0)
        if s is not None:
            sells.append(s[1])
    return {"messages": len(msgs), "built": len(stages.get("ready", [])),
            "stages_us": {k: _summ(v) for k, v in stages.items()}, "sell_ready_template_us": _summ(sells),
            "skipped": dict(fp.skipped), "tip": tip}


def capture(seconds: float, url: str | None = None, keep: int = 2_000) -> list[str]:
    """Raw creation messages from the live stream (read only), for the benchmark."""
    from . import latency as L
    rows = L.probe(seconds, [url] if url else L.ws_urls()[:1], keep_raw=keep)
    return [m for r in rows for m in r.get("raw_creates", [])]


def dryrun(seconds: float, rpc_url: str = "https://api.mainnet-beta.solana.com", log=print) -> dict:
    """The live stream through the fast path with read-only RPC for the blockhash and the fees, a fake
    signer and the dry-run sender: what we would have sent and how fast. Nothing is sent."""
    import asyncio

    from . import latency as L
    call = rpc_reader(rpc_url)
    user = E.b58(hashlib.sha256(b"dry-run-wallet").digest())
    try:
        glob = call("getAccountInfo", [X.pda([b"global"], X.PUMP), {"encoding": "base64"}])
        buyback = X.buyback_recipients(base64.b64decode(glob["value"]["data"][0]), "Global")[0]
    except Exception:
        buyback = X.BUYBACK_FEE_RECIPIENTS[0]
    fp = FastPath(Static(user, buyback), FakeSigner(user), BlockhashCache(call),
                  FeeEstimator(call, [E.PUMP, X.pda([b"global"], X.PUMP)]))
    sender = DryRunSender(send_endpoints(), os.environ.get("PYTHIA_PUMPFUN_JITO_URL"))
    out = {"ready_us": [], "behind_block_ms": []}

    async def run():
        import aiohttp
        url = L.ws_urls()[0]
        async with aiohttp.ClientSession() as s:
            async with s.ws_connect(url, heartbeat=None, max_msg_size=16 << 20) as ws:
                await ws.send_str(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "logsSubscribe",
                                              "params": [{"mentions": [E.PUMP]}, {"commitment": "processed"}]}))
                end = time.monotonic() + seconds
                while time.monotonic() < end:
                    try:
                        msg = await asyncio.wait_for(ws.receive(), timeout=max(0.1, end - time.monotonic()))
                    except asyncio.TimeoutError:
                        break
                    if msg.type != aiohttp.WSMsgType.TEXT:
                        break
                    t0 = time.perf_counter_ns()
                    now_ms = time.time() * 1000
                    fp.bh.tick()
                    fp.fees.tick()
                    r = fp.on_message(msg.data, t0)
                    if r is not None:
                        sender.submit(r.tx_b64, r.mint)
                        out["ready_us"].append(r.us["ready"])
                        if r.bts:
                            out["behind_block_ms"].append(now_ms - r.bts * 1000)
    asyncio.run(run())
    return {"seconds": seconds, "built": len(out["ready_us"]), "ready_us": _summ(out["ready_us"]),
            "behind_block_ms": _summ(out["behind_block_ms"]), "would_send_to": sender.log[0]["targets"]
            if sender.log else 0, "sent": 0, "cu_price_micro": fp.fees.micro(), "skipped": dict(fp.skipped)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=("bench", "dryrun"))
    ap.add_argument("--n", type=int, default=10_000)
    ap.add_argument("--capture", type=float, default=0.0, help="bench: also seconds of live creation messages")
    ap.add_argument("--seconds", type=float, default=60.0)
    a = ap.parse_args(argv)
    if a.cmd == "bench":
        res = {"synthetic": bench(a.n), "synthetic_tip": bench(min(a.n, 2_000), tip=True, first=10 ** 7)}
        if a.capture:
            msgs = capture(a.capture)
            res["captured"] = bench(messages=msgs)
        print(json.dumps(res, indent=1))
        return 0
    print(json.dumps(dryrun(a.seconds), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
