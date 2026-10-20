"""The live executor for the pump.fun pipeline. LOCKED.

It takes the same orders as the paper executor (pipeline.py) and would send them
as plain pump.fun or PumpSwap buy and sell instructions (txbuild.py) to a public
Solana RPC endpoint, taking each fill from the program's own trade event of our
wallet on the collector's stream. It does nothing unless EVERY one of these holds,
checked when the collector starts and again every minute:

  1. env PYTHIA_PUMPFUN_LIVE=1
  2. /etc/pythia/pumpfun-live-ack exists, written by the owner, naming the strategy
     (rule=P_...) and a daily loss limit in SOL (max_daily_loss_sol=0.5)
  3. reports/pumpfun_rt/latest.json, at most 36 hours old, says that strategy is
     ready: 14+ days, 300+ trades out of sample, positive with and without broken
     slots, every gate, 30+ days of the live paper shadow inside the replay's band
  4. no kill switch file (/etc/pythia/pumpfun-kill or <data>/pumpfun_rt/KILL)
  5. env PYTHIA_PUMPFUN_KEYPAIR points at a wallet file the owner made himself on
     the server: a regular file, not readable by group or others, outside the code
  6. the owner's copies of the program IDLs (PYTHIA_PUMPFUN_IDL_DIR, default
     <data>/pumpfun_rt/idl/pump.json and pump_amm.json) match what txbuild builds
  7. the RPC endpoint (PYTHIA_PUMPFUN_RPC) is plain https, not a bundle or relay service
  8. the `cryptography` package is installed (it signs; nothing here implements a signature)

Otherwise it refuses with every reason, and the books stay paper. The wallet file
is read only after every other check passed, the key never leaves the Signer
object, and nothing prints, logs, writes or sends it. Nothing here generates a key.

Hard caps in code, whatever the environment or the ack say (pipeline.HARD_*):
0.1 SOL a trade, 5 open positions, 0.6 SOL exposure, a daily loss stop (the ack's
limit, never above 1 SOL), and the kill switch (no buys, everything open sold).
The executor checks them again itself, independently of the pipeline.

Only the programs' public buy and sell: no bundles, no tips, no private relays,
nothing that front-runs other users or moves a price on purpose. pump.fun's terms
forbid bots on its website and API; this reads the public chain and would send to
a public RPC endpoint, which the terms do not cover, and the owner decides with
that knowledge (research/ops/README.md).

    python -m lab.pumpfun_rt.live_exec check                       every gate, and why it is shut
    python -m lab.pumpfun_rt.live_exec simulate --pubkey K --mint M --sol 0.01
                                                                   a buy built and simulated (no key, nothing sent)
"""

from __future__ import annotations

import argparse
import base64
import csv
import json
import os
import queue
import stat
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from . import curve as C
from . import pipeline as P
from . import txbuild as X

ACK_PATH = Path("/etc/pythia/pumpfun-live-ack")
ENV_LIVE = "PYTHIA_PUMPFUN_LIVE"
ENV_KEYPAIR = "PYTHIA_PUMPFUN_KEYPAIR"
ENV_RPC = "PYTHIA_PUMPFUN_RPC"
ENV_IDL = "PYTHIA_PUMPFUN_IDL_DIR"
DEFAULT_RPC = "https://api.mainnet-beta.solana.com"
REPORT_MAX_AGE_MS = 36 * 3_600_000
RECHECK_S = 60.0
CONFIRM_MS = 30_000
GIVE_UP_MS = 90_000
BLOCKHASH_S = 20.0
NOT_PUBLIC = ("jito", "bundle", "relay", "block-engine", "blockengine", "mev")


def data_dir() -> Path:
    from ..data import ROOT
    return ROOT / "live" / "pumpfun_rt"


def idl_dir() -> Path:
    from ..data import ROOT
    return Path(os.environ.get(ENV_IDL) or (ROOT / "pumpfun_rt" / "idl"))


def code_root() -> Path:
    return Path(__file__).resolve().parents[3]


# ---------------------------------------------------------------- the gate

def read_ack(path: Path) -> tuple[str | None, float | None, str | None]:
    """(rule, max daily loss in SOL, problem). Lines `key=value` or `key: value`; # comments."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None, None, f"no owner confirmation file {path}"
    vals = {}
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        sep = "=" if "=" in line else ":" if ":" in line else None
        if sep is None:
            continue
        k, v = line.split(sep, 1)
        vals[k.strip().lower()] = v.strip()
    rule = vals.get("rule")
    if not rule:
        return None, None, f"{path} names no rule (rule=P_...)"
    if rule not in P.BY_NAME:
        return None, None, f"{path} names {rule!r}, which is not a pipeline strategy"
    try:
        loss = float(vals.get("max_daily_loss_sol", ""))
    except ValueError:
        return rule, None, f"{path} has no max_daily_loss_sol in SOL"
    if not loss > 0:
        return rule, None, f"{path}: max_daily_loss_sol must be above 0"
    return rule, min(loss, P.HARD_MAX_DAILY_LOSS_SOL), None


class LiveGate:
    """Every condition, checked without reading the wallet file."""

    def __init__(self, ack_path: Path = ACK_PATH, report_path: Path | None = None, env=None, kill=None,
                 now_ms=None, idl_path: Path | None = None):
        self.ack_path = ack_path
        self.report_path = report_path
        self.env = os.environ if env is None else env
        self.kill = kill or P.killed
        self.now_ms = now_ms or (lambda: int(time.time() * 1000))
        self.idl_path = idl_path
        self.rule = None
        self.max_loss = None
        self.idls: tuple[dict | None, dict | None] = (None, None)

    def _report(self) -> Path:
        if self.report_path is not None:
            return self.report_path
        from .. import report as rep
        return rep.REPORTS / "pumpfun_rt" / "latest.json"

    def check(self) -> list[str]:
        why: list[str] = []
        if self.env.get(ENV_LIVE) != "1":
            why.append(f"{ENV_LIVE} is not 1")
        rule, loss, problem = read_ack(self.ack_path)
        self.rule, self.max_loss = rule, loss
        if problem:
            why.append(problem)
        try:
            rep = json.loads(self._report().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            rep = None
            why.append("no readiness report (reports/pumpfun_rt/latest.json)")
        if rep is not None:
            age = self.now_ms() - int(rep.get("updated_ms") or 0)
            if age > REPORT_MAX_AGE_MS:
                why.append(f"the readiness report is {age / 3_600_000:.0f} h old")
            r = (rep.get("readiness") or {}).get(rule) if rule else None
            if rule and r is None:
                why.append(f"the readiness report has no entry for {rule}")
            elif r is not None and not r.get("ready"):
                parts = [k for k in ("days_ok", "trades_ok", "positive_ok", "gates_ok", "shadow_ok") if not r.get(k)]
                why.append(f"{rule} is not ready: " + ", ".join(parts))
        if self.kill():
            why.append("the kill switch file is there")
        why += self._keypair_problems()
        why += self._idl_problems()
        why += rpc_problems(self.env.get(ENV_RPC) or DEFAULT_RPC)
        if not crypto_ok():
            why.append("the cryptography package is not installed (it signs)")
        return why

    def _keypair_problems(self) -> list[str]:
        p = self.env.get(ENV_KEYPAIR)
        if not p:
            return [f"{ENV_KEYPAIR} is not set"]
        path = Path(p)
        try:
            st = path.lstat()
        except OSError:
            return [f"{ENV_KEYPAIR} points at nothing"]
        out = []
        if not stat.S_ISREG(st.st_mode):
            out.append(f"{ENV_KEYPAIR} is not a regular file")
        if os.name == "posix" and st.st_mode & 0o077:
            out.append(f"{ENV_KEYPAIR} is readable by group or others (chmod 600)")
        try:
            path.resolve().relative_to(code_root())
            out.append(f"{ENV_KEYPAIR} lies inside the code folder; keep the wallet file outside it")
        except ValueError:
            pass
        return out

    def _idl_problems(self) -> list[str]:
        d = self.idl_path or idl_dir()
        docs = []
        for name in ("pump.json", "pump_amm.json"):
            try:
                docs.append(json.loads((d / name).read_text(encoding="utf-8")))
            except (OSError, ValueError):
                docs.append(None)
        self.idls = (docs[0], docs[1])
        return X.check_idl(docs[0], docs[1])


def crypto_ok() -> bool:
    try:
        import cryptography.hazmat.primitives.asymmetric.ed25519  # noqa: F401
    except ImportError:
        return False
    return True


def rpc_problems(url: str) -> list[str]:
    try:
        u = urllib.parse.urlsplit(url)
    except ValueError:
        return ["the RPC endpoint is not a URL"]
    host = (u.hostname or "").lower()
    if u.scheme != "https" or not host:
        return ["the RPC endpoint must be https"]
    if any(w in host or w in (u.path or "").lower() for w in NOT_PUBLIC):
        return ["the RPC endpoint looks like a bundle or relay service; only a plain public RPC is allowed"]
    return []


# ---------------------------------------------------------------- the signer

class Signer:
    """Holds the wallet key; signs messages; never shows it."""

    __slots__ = ("_key", "pubkey")

    def __init__(self, key_obj, pubkey: str):
        self._key = key_obj
        self.pubkey = pubkey

    def sign(self, message: bytes) -> bytes:
        return self._key.sign(message)

    def __repr__(self) -> str:
        return f"Signer({self.pubkey[:4]}..., key hidden)"

    __str__ = __repr__


def load_signer(path: str) -> Signer:
    """The owner's wallet file (the usual 64-number JSON array). Read here and nowhere else."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, list) or len(raw) != 64 or not all(isinstance(x, int) and 0 <= x < 256 for x in raw):
        raise ValueError("the wallet file is not a 64-byte array")
    b = bytes(raw)
    k = Ed25519PrivateKey.from_private_bytes(b[:32])
    pub = k.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    if pub != b[32:]:
        raise ValueError("the wallet file's two halves do not belong together")
    del raw, b
    return Signer(k, X.b58(pub))


# ---------------------------------------------------------------- the RPC

class Rpc:
    def __init__(self, url: str, timeout: float = 8.0, poster=None):
        if rpc_problems(url):
            raise ValueError(rpc_problems(url)[0])
        self.url, self.timeout, self.poster = url, timeout, poster
        self.n = 0

    def call(self, method: str, params: list):
        self.n += 1
        body = {"jsonrpc": "2.0", "id": self.n, "method": method, "params": params}
        if self.poster is not None:
            d = self.poster(method, params)
        else:
            req = urllib.request.Request(self.url, data=json.dumps(body).encode(), method="POST",
                                         headers={"Content-Type": "application/json", "User-Agent": "pythia-lab"})
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                d = json.loads(r.read().decode())
        if isinstance(d, dict) and d.get("error"):
            raise RuntimeError(str(d["error"].get("message") if isinstance(d["error"], dict) else d["error"])[:200])
        return d.get("result") if isinstance(d, dict) else None

    def blockhash(self) -> str:
        return self.call("getLatestBlockhash", [{"commitment": "confirmed"}])["value"]["blockhash"]

    def account(self, pubkey: str) -> tuple[bytes, str]:
        v = self.call("getAccountInfo", [pubkey, {"encoding": "base64", "commitment": "confirmed"}])["value"]
        if v is None:
            raise RuntimeError(f"no account {pubkey[:8]}")
        return base64.b64decode(v["data"][0]), v["owner"]

    def send(self, tx: bytes) -> str:
        return self.call("sendTransaction", [base64.b64encode(tx).decode(),
                                             {"encoding": "base64", "skipPreflight": False,
                                              "preflightCommitment": "processed", "maxRetries": 2}])

    def simulate(self, tx: bytes) -> dict:
        return self.call("simulateTransaction", [base64.b64encode(tx).decode(),
                                                 {"encoding": "base64", "sigVerify": False,
                                                  "replaceRecentBlockhash": True, "commitment": "processed"}])

    def statuses(self, sigs: list[str]) -> list:
        return self.call("getSignatureStatuses", [sigs, {"searchTransactionHistory": False}])["value"]


# ---------------------------------------------------------------- the executor

class Builder:
    """Orders into transactions: the programs' accounts read over RPC, cached."""

    def __init__(self, rpc: Rpc, idls: tuple[dict | None, dict | None], priority_sol: float = C.PRIORITY_SOL):
        self.rpc = rpc
        self.idl_pump = X.Idl(idls[0]) if idls[0] else None
        self.idl_amm = X.Idl(idls[1]) if idls[1] else None
        self.priority_l = int(priority_sol * C.LAMPORTS)
        self.cache: dict[str, tuple[float, object]] = {}
        self.hash: tuple[float, str] | None = None

    def _cached(self, k: str, ttl: float, fn):
        hit = self.cache.get(k)
        if hit is not None and time.monotonic() - hit[0] < ttl:
            return hit[1]
        v = fn()
        self.cache[k] = (time.monotonic(), v)
        return v

    def blockhash(self) -> str:
        if self.hash is None or time.monotonic() - self.hash[0] > BLOCKHASH_S:
            self.hash = (time.monotonic(), self.rpc.blockhash())
        return self.hash[1]

    def curve(self, mint: str) -> X.CurveInfo:
        glob = self._cached("global", 600, lambda: self.rpc.account(X.pda([b"global"], X.PUMP))[0])
        owner = self._cached("owner:" + mint, 3600, lambda: self.rpc.account(mint)[1])
        bc = self._cached("bc:" + mint, 600,
                          lambda: self.rpc.account(X.pda([b"bonding-curve", X.key(mint)], X.PUMP))[0])
        return X.curve_info(mint, owner, glob, bc, self.idl_pump)

    def pool(self, pool: str, mint: str) -> X.PoolInfo:
        cfg = self._cached("config", 600, lambda: self.rpc.account(X.pda([b"global_config"], X.PUMP_AMM))[0])
        owner = self._cached("owner:" + mint, 3600, lambda: self.rpc.account(mint)[1])
        data = self._cached("pool:" + pool, 600, lambda: self.rpc.account(pool)[0])
        return X.pool_info(pool, data, cfg, owner, self.idl_amm)

    def build(self, user: str, o: P.Order, pool: str | None, close: bool) -> bytes:
        if o.venue == "pool":
            if not pool:
                raise RuntimeError("no pool known for this token")
            info = self.pool(pool, o.mint)
            ixs = (X.amm_buy(user, info, o.tokens, o.limit_l, self.priority_l, self.idl_amm) if o.side == "buy" else
                   X.amm_sell(user, info, o.tokens, o.limit_l, self.priority_l, close, self.idl_amm))
        else:
            info = self.curve(o.mint)
            ixs = (X.pump_buy(user, info, o.tokens, o.limit_l, self.priority_l, self.idl_pump) if o.side == "buy" else
                   X.pump_sell(user, info, o.tokens, o.limit_l, self.priority_l, close, self.idl_pump))
        return X.compile_message(user, ixs, self.blockhash())


class LiveExecutor:
    """Same interface as pipeline.PaperExecutor. Sends from a worker thread; every result and
    fill is handed to the pipeline on the collector's own thread (poll, on_trade)."""

    kind = "live"

    def __init__(self, gate: LiveGate, signer, builder, limits: P.Limits, clock=None, start: bool = True):
        self.gate = gate
        self.signer = signer
        self.builder = builder
        self.limits = limits.capped()
        self.clock = clock or (lambda: int(time.time() * 1000))
        self.pipe = None
        self.q: queue.Queue = queue.Queue()
        self.results: queue.Queue = queue.Queue()
        self.pending: dict[int, dict] = {}            # pid -> {side, order, sig, sent_ms}
        self.exposure: dict[int, int] = {}
        self.day = None
        self.day_pnl_l = 0
        self.closed_why: str | None = None
        self.last_check = -1e18
        self.worker = None
        if start:
            self.worker = threading.Thread(target=self._work, name="pumpfun-live", daemon=True)
            self.worker.start()

    def attach(self, pipe) -> None:
        self.pipe = pipe

    # ------------------------------------------------------------ gate and caps
    def ready(self) -> str | None:
        now = time.monotonic()
        if now - self.last_check >= RECHECK_S:
            self.last_check = now
            why = self.gate.check()
            self.closed_why = "; ".join(why) if why else None
            if why:
                print(f"live: refusing to buy: {self.closed_why}", flush=True)
        return f"live gate shut: {self.closed_why}" if self.closed_why else None

    def _caps(self, o: P.Order) -> str | None:
        lim = self.limits
        if o.limit_l > lim.stake_sol * (1 + C.SLIP_TOL) * C.LAMPORTS + 1:
            return "above the stake cap"
        if len(self.exposure) >= lim.max_open:
            return "max open positions"
        if sum(self.exposure.values()) + o.limit_l > lim.max_exposure_sol * C.LAMPORTS:
            return "max exposure"
        d = self.clock() // P.DAY_MS
        if d != self.day:
            self.day, self.day_pnl_l = d, 0
        if max(0, -self.day_pnl_l) + sum(self.exposure.values()) + o.limit_l > lim.max_daily_loss_sol * C.LAMPORTS:
            return "daily loss limit"
        if P.killed():
            return "kill switch"
        return None

    def booked(self, pnl_l: int) -> None:
        d = self.clock() // P.DAY_MS
        if d != self.day:
            self.day, self.day_pnl_l = d, 0
        self.day_pnl_l += int(pnl_l)

    # ------------------------------------------------------------ orders (the collector's thread)
    def buy(self, o: P.Order) -> None:
        why = self.ready() or self._caps(o)
        if why:
            self.pipe.buy_failed(o.pid, self.clock(), f"refused: {why}", 0)
            return
        self.exposure[o.pid] = o.limit_l
        self.pending[o.pid] = {"side": "buy", "order": o, "sig": None, "sent_ms": self.clock()}
        self.q.put(("send", o, self._pool_of(o.mint), False))

    def sell(self, o: P.Order) -> None:
        p = self.pipe.pos.get(o.pid) or {}
        self.pending[o.pid] = {"side": "sell", "order": o, "sig": None, "sent_ms": self.clock()}
        self.q.put(("send", o, self._pool_of(o.mint), o.tokens >= p.get("left", 0)))

    def _pool_of(self, mint: str) -> str | None:
        tok = self.pipe.eng.tokens.get(mint)
        return tok.pool if tok is not None else None

    # ------------------------------------------------------------ the worker thread (network and signing only)
    def _work(self) -> None:
        while True:
            item = self.q.get()
            if item is None:
                return
            self.step(item)

    def step(self, item) -> None:
        """One queued job: build, sign and send an order, or ask for a signature's status."""
        kind = item[0]
        try:
            if kind == "send":
                _, o, pool, close = item
                msg = self.builder.build(self.signer.pubkey, o, pool, close)
                tx = X.transaction(msg, [self.signer.sign(msg)])
                sig = self.builder.rpc.send(tx)
                self.results.put(("sent", o.pid, sig))
            elif kind == "status":
                _, pid, sig = item
                st = self.builder.rpc.statuses([sig])[0]
                self.results.put(("status", pid, sig, st))
        except Exception as e:                               # every failure goes back to the book
            self.results.put(("error", item[1].pid if kind == "send" else item[1], f"{type(e).__name__}: {e}"[:200]))

    def drain(self) -> None:
        """Run what is queued on this thread (a test, or an executor made with start=False)."""
        while not self.q.empty():
            item = self.q.get_nowait()
            if item is not None:
                self.step(item)

    def stop(self) -> None:
        self.q.put(None)

    # ------------------------------------------------------------ results (the collector's thread)
    def poll(self, now: float) -> None:
        while True:
            try:
                r = self.results.get_nowait()
            except queue.Empty:
                break
            kind, pid = r[0], r[1]
            pend = self.pending.get(pid)
            if pend is None:
                continue
            if kind == "sent":
                pend["sig"] = r[2]
                log_order(pend, "sent")
            elif kind == "error":
                self._failed(pid, pend, now, r[2], 0)
            elif kind == "status":
                st = r[3]
                if st and st.get("err"):
                    self._failed(pid, pend, now, f"failed on chain: {st['err']}"[:200], self._fee())
                elif st is None and now - pend["sent_ms"] > GIVE_UP_MS:
                    self._failed(pid, pend, now, "not landed", 0)
        for pid, pend in list(self.pending.items()):
            if pend["sig"] and now - pend["sent_ms"] > CONFIRM_MS and not pend.get("asked"):
                pend["asked"] = now
                self.q.put(("status", pid, pend["sig"]))
            elif pend.get("asked") and now - pend["asked"] > CONFIRM_MS:
                pend["asked"] = None

    def _fee(self) -> int:
        return self.builder.priority_l + C.BASE_FEE_LAMPORTS

    def _failed(self, pid: int, pend: dict, now: float, why: str, fee: int) -> None:
        self.pending.pop(pid, None)
        log_order(pend, "failed", why=why)
        if pend["side"] == "buy":
            self.exposure.pop(pid, None)
            self.booked(-fee)
            self.pipe.buy_failed(pid, now, why, fee)
        else:
            self.pipe.sell_failed(pid, now, why, fee)

    def on_trade(self, table: str, row: dict) -> None:
        """Our own wallet's trade on the stream is the fill."""
        if self.signer is None or row.get("user") != self.signer.pubkey:
            return
        for pid, pend in list(self.pending.items()):
            o = pend["order"]
            if o.mint != row["mint"] or (pend["side"] == "buy") != bool(row["buy"]):
                continue
            self.pending.pop(pid, None)
            fee_bps = int(row.get("fee_bps") or C.DEFAULT_FEE_BPS)
            fee = self._fee()
            log_order(pend, "filled", sol=row["sol"], tokens=row["tok"])
            if pend["side"] == "buy":
                cost = int(row["sol"] * (1 + fee_bps / 10_000))
                self.exposure[pid] = cost + fee
                self.pipe.bought(pid, row["t"], int(row["tok"]), cost, fee)
            else:
                got = int(row["sol"] * (1 - fee_bps / 10_000))
                self.pipe.sold(pid, row["t"], int(row["tok"]), got, fee)
                if pid not in self.pipe.pos:
                    self.exposure.pop(pid, None)
            return


# ---------------------------------------------------------------- files, alerts, status

def log_order(pend: dict, what: str, **kw) -> None:
    o = pend["order"]
    rec = {"t": int(time.time() * 1000), "what": what, "pid": o.pid, "side": o.side, "mint": o.mint, "venue": o.venue,
           "tokens": o.tokens, "limit_l": o.limit_l, "why": o.why, "sig": pend.get("sig"), **kw}
    try:
        d = data_dir()
        d.mkdir(parents=True, exist_ok=True)
        with (d / "orders.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, default=str) + "\n")
    except OSError as e:
        print(f"live: order log not written ({e})", flush=True)


LEDGER_COLS = ["rule", "mint", "name", "symbol", "signal_ms", "land_ms", "exit_ms", "exit_why", "legs", "entry_price",
               "exit_price", "stake_sol", "proceeds_sol", "pnl_sol", "ret", "hold_s"]


def write_close(rec: dict) -> None:
    d = data_dir()
    d.mkdir(parents=True, exist_ok=True)
    p = d / "ledger.csv"
    new = not p.exists()
    with p.open("a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=LEDGER_COLS, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerow(rec)


def status(gate: LiveGate | None = None) -> dict:
    """For the daily card: asked for, on, refused (with the reasons), today's trades and P&L."""
    asked = os.environ.get(ENV_LIVE) == "1"
    out = {"asked": asked, "on": False, "why": [], "rule": None, "trades_today": 0, "pnl_today_sol": 0.0}
    try:
        st = json.loads((data_dir() / "state.json").read_text(encoding="utf-8"))
        if int(time.time() * 1000) - int(st.get("t") or 0) < 10 * 60_000:
            out.update(on=bool(st.get("on")), rule=st.get("rule"), trades_today=st.get("trades_today", 0),
                       pnl_today_sol=st.get("pnl_today_sol", 0.0))
    except (OSError, ValueError):
        pass
    if asked and not out["on"]:
        g = gate or LiveGate()
        out["why"] = g.check()
    return out


class LiveBook:
    """The live pipeline inside the collector: one strategy, the LiveExecutor, its files and alerts."""

    def __init__(self, pipe: P.Pipeline, executor: LiveExecutor, rule: str):
        self.pipe, self.exec, self.rule = pipe, executor, rule
        self.closed_today: list[dict] = []

    def on_close(self, rec: dict) -> None:
        write_close(rec)
        self.exec.booked(int(rec["pnl_sol"] * C.LAMPORTS) + 0)
        self.closed_today.append(rec)

    def on_event(self, kind: str, p: dict, kw: dict) -> None:
        if kind not in ("bought", "sold", "closed", "buy_failed", "sell_failed"):
            return
        if kind == "buy_failed" and str(kw.get("why", "")).startswith("refused"):
            return                                         # a refusal by the caps is not a trade
        threading.Thread(target=post_live, args=(kind, dict(p), dict(kw), self.exec.day_pnl_l / C.LAMPORTS),
                         daemon=True).start()

    def save(self) -> None:
        day = int(time.time() * 1000) // P.DAY_MS
        self.closed_today = [r for r in self.closed_today if r["exit_ms"] // P.DAY_MS == day]
        st = {"t": int(time.time() * 1000), "on": self.exec.closed_why is None, "rule": self.rule,
              "trades_today": len(self.closed_today), "pnl_today_sol": self.exec.day_pnl_l / C.LAMPORTS,
              "open": len(self.pipe.pos), "exposure_sol": sum(self.exec.exposure.values()) / C.LAMPORTS,
              "refusing": self.exec.closed_why}
        d = data_dir()
        d.mkdir(parents=True, exist_ok=True)
        tmp = d / "state.json.tmp"
        tmp.write_text(json.dumps(st), encoding="utf-8")
        tmp.replace(d / "state.json")


def post_live(kind: str, p: dict, kw: dict, day_pnl_sol: float) -> None:
    try:
        from ..ops import notify
        from .card import live_trade_card
        notify.send("trades", [live_trade_card(kind, p, kw, notify.alert_lang(), day_pnl_sol)], urgent=True)
    except Exception as e:                                   # an alert never stops the book
        print(f"live: alert not sent ({type(e).__name__}: {e})", flush=True)


def attach(engine, gate: LiveGate | None = None) -> LiveBook | None:
    """Called by the collector at start. None (and the books stay paper) unless every gate holds."""
    if os.environ.get(ENV_LIVE) != "1":
        return None
    gate = gate or LiveGate()
    why = gate.check()
    if why:
        print("live: PYTHIA_PUMPFUN_LIVE=1 but live trading stays OFF:\n  - " + "\n  - ".join(why), flush=True)
        return None
    signer = load_signer(os.environ[ENV_KEYPAIR])
    rpc = Rpc(os.environ.get(ENV_RPC) or DEFAULT_RPC)
    limits = P.env_limits()
    limits = P.Limits(limits.stake_sol, limits.max_open, limits.max_exposure_sol,
                      min(limits.max_daily_loss_sol, gate.max_loss or 0.0)).capped()
    ex = LiveExecutor(gate, signer, Builder(rpc, gate.idls), limits)
    s = P.BY_NAME[gate.rule]
    book = LiveBook(None, ex, gate.rule)
    pipe = P.Pipeline(engine, [s], ex, limits=limits, name="live", record=False, on_close=book.on_close,
                      on_event=book.on_event, kill=P.KillSwitch())
    book.pipe = pipe
    engine.add_pipe(pipe)
    print(f"live: ON for {gate.rule}, wallet {signer.pubkey[:4]}..., stake {limits.stake_sol} SOL, at most "
          f"{limits.max_open} open, {limits.max_exposure_sol} SOL exposure, daily loss stop "
          f"{limits.max_daily_loss_sol} SOL", flush=True)
    return book


# ---------------------------------------------------------------- the command line

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="the locked live executor of the pump.fun pipeline")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check", help="every gate, and why it is shut")
    sim = sub.add_parser("simulate", help="build a buy and simulate it (public key only, nothing is sent)")
    sim.add_argument("--pubkey", required=True)
    sim.add_argument("--mint", required=True)
    sim.add_argument("--sol", type=float, default=0.01)
    a = ap.parse_args(argv)
    gate = LiveGate()
    if a.cmd == "check":
        why = gate.check()
        if why:
            print("live trading is OFF:\n  - " + "\n  - ".join(why))
            return 1
        print(f"every gate holds for {gate.rule}; the collector would trade it live after a restart")
        return 0
    gate.check()
    rpc = Rpc(os.environ.get(ENV_RPC) or DEFAULT_RPC)
    b = Builder(rpc, gate.idls)
    lam = int(min(a.sol, P.HARD_STAKE_SOL) * C.LAMPORTS)
    o = P.Order(0, "buy", a.mint, "curve", 1, int(lam * (1 + C.SLIP_TOL)), 0)
    data, _ = rpc.account(X.pda([b"bonding-curve", X.key(a.mint)], X.PUMP))
    vt, vs = int.from_bytes(data[8:16], "little"), int.from_bytes(data[16:24], "little")
    o.tokens = C.curve_buy(lam, vs, vt, vt, C.DEFAULT_FEE_BPS)
    msg = b.build(a.pubkey, o, None, False)
    res = rpc.simulate(X.transaction(msg, [bytes(64)] * X.signers_of(msg)))
    print(json.dumps({"err": res["value"].get("err"), "units": res["value"].get("unitsConsumed"),
                      "logs": (res["value"].get("logs") or [])[-8:]}, indent=1))
    return 0 if not res["value"].get("err") else 1


if __name__ == "__main__":
    sys.exit(main())
