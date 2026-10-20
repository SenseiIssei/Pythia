"""The live executor for the pump.fun pipeline. LOCKED unless the owner unlocks it.

It takes the same orders as the paper executor (pipeline.py) and sends them as
plain pump.fun or PumpSwap buy and sell instructions (txbuild.py) to a public
Solana RPC endpoint, taking each fill from the program's own trade event of our
wallet on the stream. It runs only inside the live service (live_service.py),
which the owner starts by hand; the collector never trades.

Two ways in, both checked when the service starts and again every minute:

FULL (the readiness path): every one of
  1. env PYTHIA_PUMPFUN_LIVE=1
  2. /etc/pythia/pumpfun-live-ack, written by the owner, naming the strategy
     (rule=P_...) and a daily loss limit in SOL (max_daily_loss_sol=0.5)
  3. reports/pumpfun_rt/latest.json, at most 36 hours old, says that strategy is
     ready: 14+ days, 300+ trades out of sample, positive with and without broken
     slots, every gate, 30+ days of the live paper shadow inside the replay's band

TEST (the owner's small real-money test of the execution, docs/PUMPFUN-LIVE.md):
  1. env PYTHIA_PUMPFUN_LIVE=1
  2. the ack file with mode=test, strategy=<P_... or auto>, max_total_sol (at most
     2.0), max_daily_loss_sol (at most 0.5), max_trade_sol (at most 0.05) and the
     line "I accept that I can lose all of it"
  3. a successful `live_exec simulate` for this wallet within the last 24 hours
  The readiness gate is skipped; every trade is tagged test, posted at once, and
  its landing latency, slippage and fees are measured (measure.py).

and in both:
  4. no kill switch file (/etc/pythia/pumpfun-kill, <data>/pumpfun_rt/KILL, or
     reports/pumpfun_rt/KILL, the one the app's kill button writes)
  5. env PYTHIA_PUMPFUN_KEYPAIR points at a wallet file the owner made with the
     wallet tool (wallet.py): a regular file, not readable by group or others,
     outside the code, with its public address next to it (<file>.pub)
  6. the owner's copies of the program IDLs (PYTHIA_PUMPFUN_IDL_DIR, default
     <data>/pumpfun_rt/idl/pump.json and pump_amm.json) match what txbuild builds
  7. the RPC endpoint (PYTHIA_PUMPFUN_RPC) is plain https, not a bundle or relay service
  8. the `cryptography` package is installed (it signs; nothing here implements a signature)

Otherwise it refuses with every reason. The wallet file is read only after every
other check passed, by load_signer, and the key never leaves the Signer object;
nothing prints, logs, writes or sends it. Nothing here generates a key (only the
owner-run wallet tool does).

Caps, whatever the environment, the ack or the app say: pipeline.HARD_* (0.1 SOL a
trade, 5 open, 0.6 SOL exposure, 1 SOL daily loss) and in test mode the test
maxima below; the app's settings (reports/pumpfun_rt/live_settings.json) can only
lower them. A total budget (test: max_total_sol) stops every buy once the losses
since the first live trade reach it. A buy also needs the wallet to keep a fee
reserve. The executor checks all of it itself, independently of the pipeline.

Only the programs' public buy and sell, and txbuild.check_own refuses anything
else before signing: no transfers out, no withdrawals, no bundles, no tips, no
private relays, nothing that front-runs other users or moves a price on purpose.
pump.fun's terms forbid bots on its website and API; this reads the public chain
and sends to a public RPC endpoint, and the owner decides with that knowledge.

    python -m lab.pumpfun_rt.live_exec check        every gate, and why it is shut
    python -m lab.pumpfun_rt.live_exec simulate     a buy and a buy-then-sell built for this wallet and
                                                    simulated on mainnet (nothing is signed or sent)
"""

from __future__ import annotations

import argparse
import base64
import csv
import json
import math
import os
import queue
import stat
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
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

# The owner's live test: hard maxima in code, whatever the ack says (an ack above them is refused).
ACCEPT_LINE = "I accept that I can lose all of it"
TEST_MAX_TOTAL_SOL = 2.0
TEST_MAX_DAILY_LOSS_SOL = 0.5
TEST_MAX_TRADE_SOL = 0.05
SIMULATE_MAX_AGE_MS = 24 * 3_600_000
DEFAULT_TEST_RULE = "P_pool60"            # the least-bad post-migration pool rule until a report says otherwise
RESERVE_SOL = 0.01                        # left in the wallet so every open position can still be sold
LEFTOVER_TRIES = 3


def data_dir() -> Path:
    from ..data import ROOT
    return ROOT / "live" / "pumpfun_rt"


def reports_dir() -> Path:
    from .. import report as rep
    return rep.REPORTS / "pumpfun_rt"


def idl_dir() -> Path:
    from ..data import ROOT
    return Path(os.environ.get(ENV_IDL) or (ROOT / "pumpfun_rt" / "idl"))


def code_root() -> Path:
    return Path(__file__).resolve().parents[3]


def live_kill_paths() -> list[Path]:
    """Every file that stops the live book: the two of every book, and the app's kill button."""
    return P.kill_paths() + [reports_dir() / "KILL"]


def live_killed() -> bool:
    return P.killed(live_kill_paths())


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, default=str), encoding="utf-8")
    tmp.replace(path)


def read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------- the owner's confirmation

@dataclass(frozen=True)
class Ack:
    mode: str | None = None                  # "test" or "full"; None when the file is missing or unusable
    rule: str | None = None                  # a pipeline strategy, or "auto" (test mode only)
    max_daily_loss_sol: float | None = None
    max_total_sol: float | None = None
    max_trade_sol: float | None = None
    problems: tuple = ()

    def view(self) -> dict:
        return {"mode": self.mode, "strategy": self.rule, "max_daily_loss_sol": self.max_daily_loss_sol,
                "max_total_sol": self.max_total_sol, "max_trade_sol": self.max_trade_sol}


def _positive(vals: dict, k: str, path: Path, cap: float | None, problems: list, refuse_above: bool) -> float | None:
    try:
        v = float(vals.get(k, ""))
    except ValueError:
        problems.append(f"{path} has no {k} in SOL")
        return None
    if not (math.isfinite(v) and v > 0):
        problems.append(f"{path}: {k} must be above 0")
        return None
    if cap is not None and v > cap:
        if refuse_above:
            problems.append(f"{path}: {k}={v:g} is above the hard maximum {cap:g} SOL")
            return None
        return cap
    return v


def read_ack(path: Path) -> Ack:
    """The owner's confirmation. Lines `key=value` or `key: value`; # comments; and in test mode
    the acceptance line itself."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return Ack(problems=(f"no owner confirmation file {path}",))
    vals: dict[str, str] = {}
    accepted = False
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        if line.rstrip(".").strip().lower() == ACCEPT_LINE.lower():
            accepted = True
            continue
        sep = "=" if "=" in line else ":" if ":" in line else None
        if sep is None:
            continue
        k, v = line.split(sep, 1)
        vals[k.strip().lower()] = v.strip()
    mode = (vals.get("mode") or "full").lower()
    problems: list[str] = []
    rule = vals.get("strategy") or vals.get("rule")
    if mode not in ("test", "full"):
        return Ack(problems=(f"{path}: mode must be test or full, not {mode!r}",))
    if mode == "test":
        if not rule:
            problems.append(f"{path} names no strategy (strategy=P_pool60, or strategy=auto)")
        elif rule != "auto" and rule not in P.BY_NAME:
            problems.append(f"{path} names {rule!r}, which is not a pipeline strategy")
        total = _positive(vals, "max_total_sol", path, TEST_MAX_TOTAL_SOL, problems, True)
        loss = _positive(vals, "max_daily_loss_sol", path, TEST_MAX_DAILY_LOSS_SOL, problems, True)
        trade = _positive(vals, "max_trade_sol", path, TEST_MAX_TRADE_SOL, problems, True)
        if not accepted:
            problems.append(f"{path} lacks the line \"{ACCEPT_LINE}\"")
        return Ack("test", rule, loss, total, trade, tuple(problems))
    if not rule:
        return Ack("full", None, problems=(f"{path} names no rule (rule=P_...)",))
    if rule not in P.BY_NAME:
        return Ack("full", None, problems=(f"{path} names {rule!r}, which is not a pipeline strategy",))
    loss = _positive(vals, "max_daily_loss_sol", path, P.HARD_MAX_DAILY_LOSS_SOL, problems, False)
    return Ack("full", rule, loss, problems=tuple(problems))


def resolve_rule(name: str | None, report: dict | None) -> str:
    """The test's strategy: the one the ack names, or for `auto` the least-bad pre-registered
    post-migration pool strategy of the latest study report (family E, best mean out of sample)."""
    if name and name != "auto":
        return name
    best = None
    for r in (report or {}).get("results") or []:
        if not r.get("pipeline") or r.get("family") != "E" or r.get("rule") not in P.BY_NAME:
            continue
        m = (r.get("stats") or {}).get("mean")
        m = m if isinstance(m, (int, float)) and math.isfinite(m) else -math.inf
        if best is None or m > best[0]:
            best = (m, r["rule"])
    return best[1] if best else DEFAULT_TEST_RULE


# ---------------------------------------------------------------- the owner's limits from the app

SETTING_KEYS = ("max_total_sol", "max_daily_loss_sol", "max_trade_sol", "max_open")


def settings_path() -> Path:
    return reports_dir() / "live_settings.json"


def read_settings(path: Path | None = None) -> dict:
    """The app's lower limits (the engine validates them; here every value that is not a positive
    number is ignored, and they are only ever used through min())."""
    d = read_json(path or settings_path())
    out = {}
    if isinstance(d, dict):
        for k in SETTING_KEYS:
            v = d.get(k)
            if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v > 0:
                out[k] = float(v)
    return out


def _low(*xs) -> float:
    return min(x for x in xs if x is not None)


def effective(ack: Ack, settings: dict, env=None) -> tuple[P.Limits, float | None]:
    """The limits the live book trades with, and the total budget (None in full mode without one):
    the lowest of the code's caps, the ack, the app's settings and the environment."""
    e = P.env_limits() if env is None else _env_limits(env)
    s = settings
    max_open = int(min(e.max_open, s.get("max_open", P.HARD_MAX_OPEN)))
    if ack.mode == "test":
        total = _low(TEST_MAX_TOTAL_SOL, ack.max_total_sol, s.get("max_total_sol"))
        lim = P.Limits(_low(TEST_MAX_TRADE_SOL, ack.max_trade_sol, s.get("max_trade_sol"), e.stake_sol), max_open,
                       _low(e.max_exposure_sol, total),
                       _low(TEST_MAX_DAILY_LOSS_SOL, ack.max_daily_loss_sol, s.get("max_daily_loss_sol"),
                            e.max_daily_loss_sol))
        return lim.capped(), total
    total = s.get("max_total_sol")
    lim = P.Limits(_low(e.stake_sol, s.get("max_trade_sol")), max_open,
                   _low(e.max_exposure_sol, total),
                   _low(e.max_daily_loss_sol, ack.max_daily_loss_sol or 0.0, s.get("max_daily_loss_sol")))
    return lim.capped(), total


def _env_limits(env) -> P.Limits:
    def f(name, default):
        try:
            return float(env.get(name, default))
        except (TypeError, ValueError):
            return default
    return P.Limits(f("PYTHIA_PUMPFUN_STAKE_SOL", P.HARD_STAKE_SOL), int(f("PYTHIA_PUMPFUN_MAX_OPEN", P.HARD_MAX_OPEN)),
                    f("PYTHIA_PUMPFUN_MAX_EXPOSURE_SOL", P.HARD_MAX_EXPOSURE_SOL),
                    f("PYTHIA_PUMPFUN_MAX_DAILY_LOSS_SOL", P.HARD_MAX_DAILY_LOSS_SOL)).capped()


# ---------------------------------------------------------------- the simulation record

def simulate_path() -> Path:
    return data_dir() / "simulate.json"


def address_of(keypair: str | Path | None) -> str | None:
    """The wallet's PUBLIC address from <keypair>.pub (the keypair file itself is not opened)."""
    if not keypair:
        return None
    from .wallet import address_path
    try:
        a = address_path(Path(keypair)).read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return a or None


def simulate_problems(rec, address: str | None, now_ms: int) -> list[str]:
    if not isinstance(rec, dict):
        return ["no successful simulation yet (live_exec simulate)"]
    out = []
    age = now_ms - int(rec.get("t") or 0)
    if age > SIMULATE_MAX_AGE_MS:
        out.append(f"the last simulation is {age / 3_600_000:.0f} h old (at most 24 h; run live_exec simulate)")
    if not rec.get("ok"):
        out.append("the last simulation failed (live_exec simulate shows why)")
    if address and rec.get("pubkey") != address:
        out.append("the last simulation was for another wallet")
    return out


# ---------------------------------------------------------------- the gate

class LiveGate:
    """Every condition, checked without reading the wallet file."""

    def __init__(self, ack_path: Path = ACK_PATH, report_path: Path | None = None, env=None, kill=None,
                 now_ms=None, idl_path: Path | None = None, simulate_file: Path | None = None):
        self.ack_path = ack_path
        self.report_path = report_path
        self.env = os.environ if env is None else env
        self.kill = kill or live_killed
        self.now_ms = now_ms or (lambda: int(time.time() * 1000))
        self.idl_path = idl_path
        self.simulate_file = simulate_file
        self.ack = Ack()
        self.rule = None
        self.mode = None
        self.max_loss = None
        self.address = None
        self.idls: tuple[dict | None, dict | None] = (None, None)

    def _report(self) -> Path:
        return self.report_path if self.report_path is not None else reports_dir() / "latest.json"

    def check(self) -> list[str]:
        why: list[str] = []
        if self.env.get(ENV_LIVE) != "1":
            why.append(f"{ENV_LIVE} is not 1")
        ack = read_ack(self.ack_path)
        self.ack, self.mode, self.max_loss = ack, ack.mode, ack.max_daily_loss_sol
        why += list(ack.problems)
        rep = read_json(self._report())
        self.address = address_of(self.env.get(ENV_KEYPAIR))
        if ack.mode == "test":
            self.rule = resolve_rule(ack.rule, rep if isinstance(rep, dict) else None)
            if self.rule not in P.BY_NAME:
                why.append(f"the test strategy {self.rule} is not a pipeline strategy")
            why += simulate_problems(read_json(self.simulate_file or simulate_path()), self.address, self.now_ms())
        else:
            self.rule = ack.rule
            why += self._readiness(rep, ack.rule)
        if self.kill():
            why.append("the kill switch file is there")
        why += self._keypair_problems()
        why += self._idl_problems()
        why += rpc_problems(self.env.get(ENV_RPC) or DEFAULT_RPC)
        if not crypto_ok():
            why.append("the cryptography package is not installed (it signs)")
        return why

    def _readiness(self, rep, rule) -> list[str]:
        if not isinstance(rep, dict):
            return ["no readiness report (reports/pumpfun_rt/latest.json)"]
        why = []
        age = self.now_ms() - int(rep.get("updated_ms") or 0)
        if age > REPORT_MAX_AGE_MS:
            why.append(f"the readiness report is {age / 3_600_000:.0f} h old")
        r = (rep.get("readiness") or {}).get(rule) if rule else None
        if rule and r is None:
            why.append(f"the readiness report has no entry for {rule}")
        elif r is not None and not r.get("ready"):
            parts = [k for k in ("days_ok", "trades_ok", "positive_ok", "gates_ok", "shadow_ok") if not r.get(k)]
            why.append(f"{rule} is not ready: " + ", ".join(parts))
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
        if self.address is None:
            out.append(f"no public address next to the wallet file ({path.name}.pub, written by the wallet tool)")
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

    def balance(self, pubkey: str) -> int:
        """Lamports of a public address (read only)."""
        return int(self.call("getBalance", [pubkey, {"commitment": "confirmed"}])["value"])

    def token_balance(self, account: str) -> int:
        return int(self.call("getTokenAccountBalance", [account, {"commitment": "confirmed"}])["value"]["amount"])

    def holdings(self, owner: str) -> dict[str, int]:
        """Raw token amounts by mint for every token account of a public address (both token programs)."""
        out: dict[str, int] = {}
        for prog in (X.TOKEN, X.TOKEN_2022):
            res = self.call("getTokenAccountsByOwner", [owner, {"programId": prog},
                                                        {"encoding": "jsonParsed", "commitment": "confirmed"}])
            for a in (res or {}).get("value") or []:
                try:
                    info = a["account"]["data"]["parsed"]["info"]
                    amt = int(info["tokenAmount"]["amount"])
                except (KeyError, TypeError, ValueError):
                    continue
                if amt > 0 and info.get("mint") != X.WSOL:
                    out[info["mint"]] = out.get(info["mint"], 0) + amt
        return out

    def fee_of(self, sig: str) -> int | None:
        """The network fee a landed transaction paid (lamports), None when not known yet."""
        res = self.call("getTransaction", [sig, {"encoding": "json", "commitment": "confirmed",
                                                 "maxSupportedTransactionVersion": 0}])
        try:
            return int(res["meta"]["fee"])
        except (KeyError, TypeError, ValueError):
            return None

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

    def ixs(self, user: str, o: P.Order, pool: str | None, close: bool) -> list[X.Ix]:
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
        X.check_own(user, ixs)                                # a plain buy or sale for this wallet, nothing else
        return ixs

    def build(self, user: str, o: P.Order, pool: str | None, close: bool) -> bytes:
        return X.compile_message(user, self.ixs(user, o, pool, close), self.blockhash())


def totals_path() -> Path:
    return data_dir() / "totals.json"


def load_totals() -> dict:
    d = read_json(totals_path())
    if not isinstance(d, dict):
        d = {}
    return {"pnl_l": int(d.get("pnl_l") or 0), "since_ms": d.get("since_ms"), "trades": int(d.get("trades") or 0),
            "total_alerted": bool(d.get("total_alerted"))}


class LiveExecutor:
    """Same interface as pipeline.PaperExecutor. Sends from a worker thread; every result and
    fill is handed to the pipeline on the stream's own thread (poll, on_trade)."""

    kind = "live"

    def __init__(self, gate: LiveGate, signer, builder, limits: P.Limits, clock=None, start: bool = True,
                 mode: str = "full", max_total_sol: float | None = None, rule: str | None = None,
                 totals: dict | None = None, on_stop=None, on_leftover=None):
        self.gate = gate
        self.signer = signer
        self.builder = builder
        self.limits = limits.capped()
        self.max_total_l = None if max_total_sol is None else int(max_total_sol * C.LAMPORTS)
        self.mode = mode
        self.rule = rule
        self.clock = clock or (lambda: int(time.time() * 1000))
        self.pipe = None
        self.q: queue.Queue = queue.Queue()
        self.results: queue.Queue = queue.Queue()
        self.pending: dict[int, dict] = {}            # pid -> {side, order, sig, sent_ms}
        self.exposure: dict[int, int] = {}
        self.day = None
        self.day_pnl_l = 0
        self.stop_day = None
        self.totals = totals if totals is not None else load_totals()
        self.balance_l: int | None = None             # the service's last getBalance
        self.meas: dict[int, dict] = {}               # pid -> the last fill's measurement (for its card)
        self.leftovers: dict[int, dict] = {}          # pid (negative) -> a position from before a restart
        self.on_stop = on_stop                        # (kind, value_sol) once when a stop fires
        self.on_leftover = on_leftover                # (what, info) for the cards
        self.on_gate = None                           # (reason or None) when the gate shuts or opens again
        self.closed_why: str | None = None
        self.last_check = -1e18
        self.worker = None
        if start:
            self.worker = threading.Thread(target=self._work, name="pumpfun-live", daemon=True)
            self.worker.start()

    def attach(self, pipe) -> None:
        self.pipe = pipe

    def set_limits(self, limits: P.Limits, max_total_sol: float | None) -> None:
        self.limits = limits.capped()
        self.max_total_l = None if max_total_sol is None else int(max_total_sol * C.LAMPORTS)
        if self.pipe is not None:
            for r in self.pipe.risk.values():
                r.limits = self.limits

    # ------------------------------------------------------------ gate and caps
    def ready(self) -> str | None:
        now = time.monotonic()
        if now - self.last_check >= RECHECK_S:
            self.last_check = now
            why = self.gate.check()
            if self.rule is not None and not why and (self.gate.rule != self.rule or self.gate.mode != self.mode):
                why = ["the confirmation file now names another strategy or mode; restart the live service"]
            was = self.closed_why
            self.closed_why = "; ".join(why) if why else None
            if why:
                print(f"live: refusing to buy: {self.closed_why}", flush=True)
            if self.closed_why != was and self.on_gate is not None:
                self.on_gate(self.closed_why)              # shut, or open again: the owner hears of it
        return f"live gate shut: {self.closed_why}" if self.closed_why else None

    def _roll(self) -> None:
        d = self.clock() // P.DAY_MS
        if d != self.day:
            self.day, self.day_pnl_l = d, 0

    def _caps(self, o: P.Order) -> str | None:
        lim = self.limits
        if o.limit_l > lim.stake_sol * (1 + C.SLIP_TOL) * C.LAMPORTS + 1:
            return "above the stake cap"
        if len(self.exposure) >= lim.max_open:
            return "max open positions"
        held = sum(self.exposure.values())
        if held + o.limit_l > lim.max_exposure_sol * C.LAMPORTS:
            return "max exposure"
        self._roll()
        if self.stop_day == self.day:
            return "daily loss stop"
        if max(0, -self.day_pnl_l) + held + o.limit_l > lim.max_daily_loss_sol * C.LAMPORTS:
            return "daily loss limit"
        if self.max_total_l is not None:
            if -self.totals["pnl_l"] >= self.max_total_l:
                return "total budget stop"
            if max(0, -self.totals["pnl_l"]) + held + o.limit_l > self.max_total_l:
                return "total budget"
        if self.balance_l is not None and self.balance_l < o.limit_l + int(RESERVE_SOL * C.LAMPORTS):
            return "wallet balance too low"
        if live_killed():
            return "kill switch"
        return None

    def booked(self, pnl_l: int) -> None:
        """A realised result: the day's and the total's P&L, and the two stops."""
        self._roll()
        self.day_pnl_l += int(pnl_l)
        t = self.totals
        t["pnl_l"] += int(pnl_l)
        if t.get("since_ms") is None:
            t["since_ms"] = self.clock()
        fired = []
        if self.day_pnl_l < 0 and -self.day_pnl_l >= self.limits.max_daily_loss_sol * C.LAMPORTS \
                and self.stop_day != self.day:
            self.stop_day = self.day
            fired.append(("daily", -self.day_pnl_l / C.LAMPORTS))
        if self.max_total_l is not None and t["pnl_l"] < 0 and -t["pnl_l"] >= self.max_total_l \
                and not t.get("total_alerted"):
            t["total_alerted"] = True
            fired.append(("total", -t["pnl_l"] / C.LAMPORTS))
        try:
            write_json(totals_path(), t)
        except OSError as e:
            print(f"live: totals not written ({e})", flush=True)
        for kind, v in fired:
            print(f"live: the {kind} stop fired at {v:.4f} SOL lost; no more buys", flush=True)
            if self.on_stop is not None:
                self.on_stop(kind, v)

    # ------------------------------------------------------------ orders (the stream's thread)
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
        left = p.get("left", 0)
        expect = int(p["mark_l"] * o.tokens / left) if p.get("mark_l") and left else None
        self.pending[o.pid] = {"side": "sell", "order": o, "sig": None, "sent_ms": self.clock(), "expect_l": expect}
        self.q.put(("send", o, self._pool_of(o.mint), o.tokens >= left))

    def sell_leftover(self, pid: int, info: dict, tokens: int) -> None:
        """Sell everything of a position from before a restart (its book is gone): no floor, close."""
        o = P.Order(pid, "sell", info["mint"], info.get("venue") or "pool", int(tokens), 0, self.clock(), "leftover")
        self.leftovers[pid] = {**info, "tokens": int(tokens), "tries": self.leftovers.get(pid, {}).get("tries", 0) + 1}
        self.pending[pid] = {"side": "sell", "order": o, "sig": None, "sent_ms": self.clock(), "leftover": True}
        self.q.put(("send", o, info.get("pool"), True))

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
        """One queued job: build, sign and send an order, ask for a signature's status or its fee."""
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
            elif kind == "fee":
                _, pid, sig = item
                self.results.put(("fee", pid, sig, self.builder.rpc.fee_of(sig)))
        except Exception as e:                               # every failure goes back to the book
            if kind == "fee":
                return
            self.results.put(("error", item[1].pid if kind == "send" else item[1], f"{type(e).__name__}: {e}"[:200]))

    def drain(self) -> None:
        """Run what is queued on this thread (a test, or an executor made with start=False)."""
        while not self.q.empty():
            item = self.q.get_nowait()
            if item is not None:
                self.step(item)

    def stop(self) -> None:
        self.q.put(None)

    # ------------------------------------------------------------ results (the stream's thread)
    def poll(self, now: float) -> None:
        while True:
            try:
                r = self.results.get_nowait()
            except queue.Empty:
                break
            kind, pid = r[0], r[1]
            if kind == "fee":
                if r[3] is not None:
                    write_measure({"t": self.clock(), "what": "fee", "mode": self.mode, "sig": r[2], "fee_l": r[3]})
                continue
            pend = self.pending.get(pid)
            if pend is None:
                continue
            if kind == "sent":
                pend["sig"] = r[2]
                log_order(pend, "sent", mode=self.mode)
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
        log_order(pend, "failed", why=why, mode=self.mode)
        write_measure({"t": self.clock(), "what": "failed", "mode": self.mode, "side": pend["side"],
                       "venue": pend["order"].venue, "why": why, "fee_l": fee})
        if pend.get("leftover"):
            self.booked(-fee)
            lo = self.leftovers.get(pid) or {}
            if lo.get("tries", 0) < LEFTOVER_TRIES:
                self.sell_leftover(pid, lo, lo.get("tokens", pend["order"].tokens))
            elif self.on_leftover is not None:
                self.on_leftover("stuck", {**lo, "why": why})
            return
        if pend["side"] == "buy":
            self.exposure.pop(pid, None)
            self.booked(-fee)
            self.pipe.buy_failed(pid, now, why, fee)
        else:
            self.pipe.sell_failed(pid, now, why, fee)

    def on_trade(self, table: str, row: dict) -> None:
        """Our own wallet's trade on the stream is the fill; its timing and price are measured."""
        if self.signer is None or row.get("user") != self.signer.pubkey:
            return
        for pid, pend in list(self.pending.items()):
            o = pend["order"]
            if o.mint != row["mint"] or (pend["side"] == "buy") != bool(row["buy"]):
                continue
            self.pending.pop(pid, None)
            fee_bps = int(row.get("fee_bps") or C.DEFAULT_FEE_BPS)
            fee = self._fee()
            log_order(pend, "filled", sol=row["sol"], tokens=row["tok"], mode=self.mode)
            m = {"t": self.clock(), "what": "fill", "mode": self.mode, "pid": pid, "side": pend["side"],
                 "venue": o.venue, "mint": o.mint, "rule": self.rule, "sig": pend.get("sig"),
                 "signal_ms": o.signal_ms, "land_ms": int(row["t"]), "lat_ms": int(row["t"]) - o.signal_ms,
                 "send_to_land_ms": int(row["t"]) - int(pend["sent_ms"]), "sol_l": int(row["sol"]),
                 "tokens": int(row["tok"]), "fee_bps": fee_bps, "fee_assumed_l": fee, "slip": None}
            if pend.get("leftover"):
                got = int(row["sol"] * (1 - fee_bps / 10_000))
                lo = self.leftovers.pop(pid, {})
                self.booked(got - int(lo.get("cost_l") or 0) - fee)
                write_measure(m)
                if pend.get("sig"):
                    self.q.put(("fee", pid, pend["sig"]))
                if self.on_leftover is not None:
                    self.on_leftover("sold", {**lo, "got_l": got})
                return
            if pend["side"] == "buy":
                cost = int(row["sol"] * (1 + fee_bps / 10_000))
                p = self.pipe.pos.get(pid) or {}
                if p.get("signal_price") and row["tok"]:
                    m["slip"] = ((cost / C.LAMPORTS) / (row["tok"] / C.TOKEN_UNIT)) / p["signal_price"] - 1
                self.meas[pid] = m
                self.pipe.lat[pid] = m["lat_ms"]                  # the closed trade's lat_buy_ms, as on paper
                self.exposure[pid] = cost + fee
                self.pipe.bought(pid, row["t"], int(row["tok"]), cost, fee)
            else:
                got = int(row["sol"] * (1 - fee_bps / 10_000))
                if pend.get("expect_l"):
                    m["slip"] = got / pend["expect_l"] - 1
                self.meas[pid] = m
                self.pipe.sold(pid, row["t"], int(row["tok"]), got, fee)
                if pid not in self.pipe.pos:
                    self.exposure.pop(pid, None)
            write_measure(m)
            if pend.get("sig"):
                self.q.put(("fee", pid, pend["sig"]))
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


def write_measure(rec: dict) -> None:
    """One measured fill, failure or fee: data_dir()/measured.jsonl, read by measure.py."""
    try:
        d = data_dir()
        d.mkdir(parents=True, exist_ok=True)
        with (d / "measured.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, default=str) + "\n")
    except OSError as e:
        print(f"live: measurement not written ({e})", flush=True)


LEDGER_COLS = ["mode", "rule", "mint", "name", "symbol", "signal_ms", "land_ms", "exit_ms", "exit_why", "legs",
               "entry_price", "exit_price", "stake_sol", "proceeds_sol", "pnl_sol", "ret", "hold_s", "lat_buy_ms",
               "slip"]


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


def read_ledger(limit: int = 100) -> list[dict]:
    """The newest closed live trades, newest first."""
    p = data_dir() / "ledger.csv"
    if not p.exists():
        return []
    with p.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    out = []
    for r in rows[-limit:][::-1]:
        rec = {}
        for k, v in r.items():
            if k in ("mode", "rule", "mint", "name", "symbol", "exit_why"):
                rec[k] = v or None
            else:
                try:
                    rec[k] = float(v) if v not in ("", None) else None
                except ValueError:
                    rec[k] = None
        out.append(rec)
    return out


def status_path() -> Path:
    return reports_dir() / "live_status.json"


def status(gate: LiveGate | None = None) -> dict:
    """For the daily card: asked for, on, refused (with the reasons), today's trades and P&L."""
    asked = os.environ.get(ENV_LIVE) == "1"
    out = {"asked": asked, "on": False, "why": [], "rule": None, "mode": None, "trades_today": 0,
           "pnl_today_sol": 0.0}
    st = read_json(status_path())
    if isinstance(st, dict) and int(time.time() * 1000) - int(st.get("t") or 0) < 10 * 60_000:
        out.update(asked=True, on=bool(st.get("on")), rule=st.get("rule"), mode=st.get("mode"),
                   trades_today=st.get("trades_today", 0), pnl_today_sol=st.get("pnl_today_sol", 0.0),
                   why=list(st.get("gate") or []))
        return out
    if asked:
        g = gate or LiveGate()
        out["why"] = g.check()
    return out


def hard_view() -> dict:
    return {"test": {"max_total_sol": TEST_MAX_TOTAL_SOL, "max_daily_loss_sol": TEST_MAX_DAILY_LOSS_SOL,
                     "max_trade_sol": TEST_MAX_TRADE_SOL},
            "full": {"max_daily_loss_sol": P.HARD_MAX_DAILY_LOSS_SOL, "max_trade_sol": P.HARD_STAKE_SOL},
            "max_open": P.HARD_MAX_OPEN, "max_exposure_sol": P.HARD_MAX_EXPOSURE_SOL, "reserve_sol": RESERVE_SOL}


def limits_view(lim: P.Limits, total: float | None) -> dict:
    return {"max_trade_sol": lim.stake_sol, "max_open": lim.max_open, "max_exposure_sol": lim.max_exposure_sol,
            "max_daily_loss_sol": lim.max_daily_loss_sol, "max_total_sol": total}


def base_status(gate: LiveGate, why: list[str], address: str | None, balance_l: int | None, balance_t: int | None,
                holdings: dict | None = None) -> dict:
    """What the app shows whether the book is on or not."""
    totals = load_totals()
    ack = gate.ack
    lim = total = None
    if ack.mode:
        lim, total = effective(ack, read_settings(), gate.env)
    sim = read_json(simulate_path())
    return {"t": int(time.time() * 1000), "running": True, "on": False, "mode": ack.mode, "rule": gate.rule,
            "address": address, "balance_sol": None if balance_l is None else balance_l / C.LAMPORTS,
            "balance_t": balance_t, "holdings": [{"mint": k, "amount": v} for k, v in (holdings or {}).items()],
            "positions": [], "leftovers": [], "pnl_today_sol": 0.0, "trades_today": 0, "wins_today": 0,
            "pnl_total_sol": totals["pnl_l"] / C.LAMPORTS, "trades_total": totals["trades"],
            "since_ms": totals["since_ms"], "gate": list(why), "refusing": "; ".join(why) or None,
            "ack": ack.view(), "settings": read_settings(), "limits": limits_view(lim, total) if lim else None,
            "hard": hard_view(), "stops": {"daily": False, "total": bool(totals.get("total_alerted"))},
            "kill": live_killed(),
            "simulate": {"t": sim.get("t"), "ok": sim.get("ok"), "venue": sim.get("venue"), "mint": sim.get("mint")}
            if isinstance(sim, dict) else None,
            "exposure_sol": 0.0, "skipped": {}}


class LiveBook:
    """The live pipeline: one strategy, the LiveExecutor, its files, limits and alerts."""

    def __init__(self, pipe: P.Pipeline | None, executor: LiveExecutor, rule: str, alerts: bool = True,
                 poster=None):
        self.pipe, self.exec, self.rule = pipe, executor, rule
        self.alerts = alerts
        self.poster = poster or post_cards
        self.closed_today: list[dict] = []
        self.recent: list[dict] = read_ledger(100)
        self.card_day = None
        self.day_stats = {"n": 0, "wins": 0, "pnl_sol": 0.0, "failed": 0}
        self.last_limits = -1e18
        executor.on_stop = self.on_stop
        executor.on_leftover = self.on_leftover
        executor.on_gate = self.on_gate

    # ------------------------------------------------------------ the pipeline's hooks
    def on_close(self, rec: dict) -> None:
        rec = {**rec, "mode": self.exec.mode}
        write_close(rec)
        self.exec.totals["trades"] += 1
        self.exec.booked(int(rec["pnl_sol"] * C.LAMPORTS))
        self.closed_today.append(rec)
        self.recent.insert(0, {k: rec.get(k) for k in LEDGER_COLS})
        del self.recent[100:]
        self.day_stats["n"] += 1
        self.day_stats["wins"] += int(rec["pnl_sol"] > 0)
        self.day_stats["pnl_sol"] += rec["pnl_sol"]

    def on_event(self, kind: str, p: dict, kw: dict) -> None:
        if kind not in ("bought", "sold", "closed", "buy_failed", "sell_failed"):
            return
        if kind == "buy_failed" and str(kw.get("why", "")).startswith("refused"):
            return                                         # a refusal by the caps is not a trade
        if kind in ("buy_failed", "sell_failed"):
            self.day_stats["failed"] += 1
        meas = dict(self.exec.meas.get(p.get("pid")) or {}) if kind in ("bought", "sold") else None
        self._post(lambda lang: [_trade_card(kind, dict(p), dict(kw), lang, self.exec.day_pnl_l / C.LAMPORTS,
                                             self.exec.mode, meas)])

    def on_stop(self, kind: str, lost_sol: float) -> None:
        lim = self.exec.limits.max_daily_loss_sol if kind == "daily" else (self.exec.max_total_l or 0) / C.LAMPORTS
        self._post(lambda lang: [_stop_card(kind, lost_sol, lim, self.exec.mode, lang)])

    def on_leftover(self, what: str, info: dict) -> None:
        self._post(lambda lang: [_leftover_card(what, info, self.exec.mode, lang)])

    def on_gate(self, why: str | None) -> None:
        self._post(lambda lang: [_gate_card(why, self.exec.mode, lang)])

    def _post(self, make) -> None:
        if not self.alerts:
            return
        threading.Thread(target=self.poster, args=(make,), daemon=True).start()

    # ------------------------------------------------------------ the service's clock
    def tick(self, now_ms: int, wall_ms: int | None = None) -> None:
        wall_ms = wall_ms or int(time.time() * 1000)
        if time.monotonic() - self.last_limits >= RECHECK_S:
            self.last_limits = time.monotonic()
            self.refresh_limits()
        day = wall_ms // P.DAY_MS
        if self.card_day is None:
            self.card_day = day
        elif day != self.card_day:
            stats, self.day_stats = self.day_stats, {"n": 0, "wins": 0, "pnl_sol": 0.0, "failed": 0}
            ended = self.card_day
            self.card_day = day
            self.daily_card(ended, stats)

    def refresh_limits(self) -> None:
        ack = self.exec.gate.ack
        if ack.mode is None:
            return
        lim, total = effective(ack, read_settings(), self.exec.gate.env)
        self.exec.set_limits(lim, total)

    def daily_card(self, day: int, stats: dict) -> None:
        from . import measure
        try:
            ex = measure.write_report()
        except Exception as e:                               # the card goes out without it
            print(f"live: execution report not written ({type(e).__name__}: {e})", flush=True)
            ex = None
        bal = self.exec.balance_l
        total = self.exec.totals["pnl_l"] / C.LAMPORTS
        self._post(lambda lang: [_daily_card(day, stats, bal, total, ex, self.exec.mode, self.rule, lang)])

    # ------------------------------------------------------------ files
    def positions(self) -> list[dict]:
        out = []
        for p in (self.pipe.pos.values() if self.pipe is not None else []):
            cost = p.get("cost_l") or 0
            mark = p.get("mark_l")
            out.append({"pid": p["pid"], "mint": p["mint"], "symbol": p.get("symbol"), "name": p.get("name"),
                        "venue": p.get("venue"), "state": p.get("state"), "tokens": p.get("left"),
                        "cost_sol": cost * (p["left"] / p["tokens"]) / C.LAMPORTS if p.get("tokens") else
                        p.get("limit_l", 0) / C.LAMPORTS,
                        "mark_sol": None if mark is None else mark / C.LAMPORTS,
                        "signal_ms": p.get("signal_ms"), "land_ms": p.get("land_ms"),
                        "pool": self.exec._pool_of(p["mint"]) if self.exec.pipe is not None else None})
        return out

    def status(self, address: str | None, balance_t: int | None, holdings: dict | None, why: list[str]) -> dict:
        ex = self.exec
        st = base_status(ex.gate, why, address or ex.signer.pubkey, ex.balance_l, balance_t, holdings)
        ex._roll()
        day = int(time.time() * 1000) // P.DAY_MS
        self.closed_today = [r for r in self.closed_today if r["exit_ms"] // P.DAY_MS == day]
        st.update(on=ex.closed_why is None and not st["kill"] and ex.stop_day != ex.day
                  and not (ex.max_total_l is not None and -ex.totals["pnl_l"] >= ex.max_total_l),
                  mode=ex.mode, rule=self.rule, positions=self.positions(),
                  leftovers=[{"pid": k, **v} for k, v in ex.leftovers.items()],
                  pnl_today_sol=ex.day_pnl_l / C.LAMPORTS, trades_today=len(self.closed_today),
                  wins_today=sum(1 for r in self.closed_today if r["pnl_sol"] > 0),
                  pnl_total_sol=ex.totals["pnl_l"] / C.LAMPORTS, trades_total=ex.totals["trades"],
                  since_ms=ex.totals.get("since_ms"), limits=limits_view(ex.limits, None if ex.max_total_l is None
                                                                         else ex.max_total_l / C.LAMPORTS),
                  stops={"daily": ex.stop_day == ex.day,
                         "total": ex.max_total_l is not None and -ex.totals["pnl_l"] >= ex.max_total_l},
                  exposure_sol=sum(ex.exposure.values()) / C.LAMPORTS,
                  refusing=ex.closed_why, gate=[ex.closed_why] if ex.closed_why else list(why))
        if self.pipe is not None:
            sk = {k[1]: v for k, v in self.pipe.eng.skipped.items() if k[0] == self.rule}
            st["skipped"] = dict(sorted(sk.items(), key=lambda kv: -kv[1])[:8])
        return st

    def save_open(self) -> None:
        """Positions and buys in flight, so a restart can sell what is left (adopt_leftovers)."""
        rows = []
        for p in (self.pipe.pos.values() if self.pipe is not None else []):
            rows.append({"mint": p["mint"], "venue": p.get("venue"), "pool": self.exec._pool_of(p["mint"]),
                         "symbol": p.get("symbol"), "rule": p.get("rule"),
                         "cost_l": int(p.get("cost_l") * p["left"] / p["tokens"]) if p.get("tokens") else
                         int(p.get("limit_l") or 0)})
        rows += [dict(v, tries=0) for v in self.exec.leftovers.values()]
        write_json(data_dir() / "open.json", rows)

    def adopt_leftovers(self, holdings: dict[str, int] | None = None) -> int:
        """At start: every position the last run left open whose tokens are still in the wallet is sold."""
        rows = read_json(data_dir() / "open.json")
        if not isinstance(rows, list) or not rows:
            return 0
        if holdings is None:
            try:
                holdings = self.exec.builder.rpc.holdings(self.exec.signer.pubkey)
            except Exception as e:
                print(f"live: could not read the wallet's tokens for leftovers ({type(e).__name__}: {e})", flush=True)
                return 0
        n = 0
        for k, r in enumerate(rows):
            amt = holdings.get(r.get("mint"), 0)
            if amt > 0:
                n += 1
                self.exec.sell_leftover(-(k + 1), r, amt)
        print(f"live: {n} position(s) from before the restart are being sold", flush=True)
        return n


# ---------------------------------------------------------------- the cards

def post_cards(make) -> None:
    try:
        from ..ops import notify
        notify.send("trades", make(notify.alert_lang()), urgent=True)
    except Exception as e:                                   # an alert never stops the book
        print(f"live: alert not sent ({type(e).__name__}: {e})", flush=True)


def _trade_card(kind, p, kw, lang, day_pnl_sol, mode, meas):
    from .card import live_trade_card
    return live_trade_card(kind, p, kw, lang, day_pnl_sol, mode=mode, measured=meas)


def _stop_card(kind, lost_sol, limit_sol, mode, lang):
    from .card import live_stop_card
    return live_stop_card(kind, lost_sol, limit_sol, mode, lang)


def _leftover_card(what, info, mode, lang):
    from .card import live_leftover_card
    return live_leftover_card(what, info, mode, lang)


def _gate_card(why, mode, lang):
    from .card import live_gate_card
    return live_gate_card(why, mode, lang)


def _daily_card(day, stats, balance_l, total_sol, ex, mode, rule, lang):
    from .card import live_daily_card
    return live_daily_card(day, stats, balance_l, total_sol, ex, mode, rule, lang)


# ---------------------------------------------------------------- attaching the book

def attach(engine, gate: LiveGate | None = None, rpc: Rpc | None = None, load=load_signer, alerts: bool = True,
           start: bool = True) -> LiveBook | None:
    """Called by the live service at start. None (and nothing trades) unless every gate holds."""
    env = gate.env if gate is not None else os.environ
    if env.get(ENV_LIVE) != "1":
        return None
    gate = gate or LiveGate()
    why = gate.check()
    if why:
        print("live: PYTHIA_PUMPFUN_LIVE=1 but live trading stays OFF:\n  - " + "\n  - ".join(why), flush=True)
        return None
    signer = load(env[ENV_KEYPAIR])
    if gate.address and signer.pubkey != gate.address:
        print("live: the wallet file and its .pub address do not match; live trading stays OFF", flush=True)
        return None
    rpc = rpc or Rpc(env.get(ENV_RPC) or DEFAULT_RPC)
    lim, total = effective(gate.ack, read_settings(), env)
    ex = LiveExecutor(gate, signer, Builder(rpc, gate.idls), lim, mode=gate.ack.mode, max_total_sol=total,
                      rule=gate.rule, start=start)
    s = P.BY_NAME[gate.rule]
    book = LiveBook(None, ex, gate.rule, alerts=alerts)
    pipe = P.Pipeline(engine, [s], ex, limits=lim, name="live", record=False, on_close=book.on_close,
                      on_event=book.on_event, kill=P.KillSwitch(live_kill_paths()))
    book.pipe = pipe
    engine.add_pipe(pipe)
    print(f"live: ON ({gate.ack.mode}) for {gate.rule}, wallet {signer.pubkey[:4]}..., stake {lim.stake_sol} SOL, "
          f"at most {lim.max_open} open, {lim.max_exposure_sol} SOL exposure, daily loss stop "
          f"{lim.max_daily_loss_sol} SOL" + (f", total budget {total} SOL" if total is not None else ""), flush=True)
    return book


# ---------------------------------------------------------------- the simulation (nothing is signed or sent)

def newest_pool(path: Path | None = None) -> tuple[str, str] | None:
    """(pool, mint) of the newest migration the collector has seen (its pools.json)."""
    from . import store
    d = read_json(path or (store.base() / "pools.json"))
    if not isinstance(d, dict) or not d:
        return None
    best = max(d.items(), key=lambda kv: int(kv[1][1]) if isinstance(kv[1], list) and len(kv[1]) > 1 else 0)
    return best[0], best[1][0]


def simulate(gate: LiveGate, rpc: Rpc, pubkey: str, mint: str | None = None, pool: str | None = None,
             sol: float = 0.01, now_ms: int | None = None, pools_file: Path | None = None) -> dict:
    """A buy, and a buy followed by the sale of what it bought, built by txbuild for this wallet and run
    through simulateTransaction on mainnet (no signature, nothing sent). The record is what the test
    gate reads; it holds no secret."""
    gate.check()
    rule = gate.rule if gate.rule in P.BY_NAME else DEFAULT_TEST_RULE
    venue = "pool" if P.BY_NAME[rule].family == "E" else "curve"
    b = Builder(rpc, gate.idls)
    lam = int(min(sol, TEST_MAX_TRADE_SOL, P.HARD_STAKE_SOL) * C.LAMPORTS)
    limit = int(lam * (1 + C.SLIP_TOL))
    rec = {"t": now_ms or int(time.time() * 1000), "ok": False, "pubkey": pubkey, "rule": rule, "venue": venue,
           "mint": mint, "pool": pool, "sol": lam / C.LAMPORTS, "buy": None, "round_trip": None, "error": None}
    try:
        if venue == "pool":
            if not pool:
                hit = newest_pool(pools_file)
                if hit is None:
                    raise RuntimeError("no recent pool known (run the collector, or pass --pool and --mint)")
                pool, mint = hit
            if not mint:
                raise RuntimeError("--pool needs --mint")
            rec.update(pool=pool, mint=mint)
            info = b.pool(pool, mint)
            pb, pq = rpc.token_balance(info.pool_base), rpc.token_balance(info.pool_quote)
            tokens = C.pool_buy(lam, pb, pq, C.DEFAULT_FEE_BPS)
            buy = X.amm_buy(pubkey, info, tokens, limit, b.priority_l, b.idl_amm)
            sell = X.amm_sell(pubkey, info, tokens, 0, b.priority_l, True, b.idl_amm)
        else:
            if not mint:
                raise RuntimeError("a curve strategy needs --mint (a live token's mint)")
            data, _ = rpc.account(X.pda([b"bonding-curve", X.key(mint)], X.PUMP))
            vt, vs = int.from_bytes(data[8:16], "little"), int.from_bytes(data[16:24], "little")
            tokens = C.curve_buy(lam, vs, vt, vt, C.DEFAULT_FEE_BPS)
            info = b.curve(mint)
            buy = X.pump_buy(pubkey, info, tokens, limit, b.priority_l, b.idl_pump)
            sell = X.pump_sell(pubkey, info, tokens, 0, b.priority_l, True, b.idl_pump)
        X.check_own(pubkey, buy)
        X.check_own(pubkey, sell)
        bh = b.blockhash()
        for name, ixs in (("buy", buy), ("round_trip", X.round_trip(buy, sell))):
            msg = X.compile_message(pubkey, ixs, bh)
            res = rpc.simulate(X.transaction(msg, [bytes(64)] * X.signers_of(msg)))
            v = (res or {}).get("value") or {}
            rec[name] = {"err": v.get("err"), "units": v.get("unitsConsumed"), "logs": (v.get("logs") or [])[-6:]}
        rec["ok"] = rec["buy"]["err"] is None and rec["round_trip"]["err"] is None
    except Exception as e:
        rec["error"] = f"{type(e).__name__}: {e}"[:300]
    write_json(simulate_path(), rec)
    return rec


# ---------------------------------------------------------------- the command line

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="the live executor of the pump.fun pipeline")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check", help="every gate, and why it is shut")
    sim = sub.add_parser("simulate", help="simulate a buy and a buy-then-sell for the wallet (nothing is sent)")
    sim.add_argument("--pubkey", help="default: the wallet's public address (<keypair>.pub)")
    sim.add_argument("--mint")
    sim.add_argument("--pool", help="a PumpSwap pool (default: the newest migration the collector saw)")
    sim.add_argument("--sol", type=float, default=0.01)
    a = ap.parse_args(argv)
    gate = LiveGate()
    if a.cmd == "check":
        why = gate.check()
        print(f"mode {gate.mode or 'none'}, strategy {gate.rule or 'none'}")
        if why:
            print("live trading is OFF:\n  - " + "\n  - ".join(why))
            return 1
        print(f"every gate holds for {gate.rule} ({gate.mode}); the live service would trade it after a (re)start")
        return 0
    gate.check()
    pubkey = a.pubkey or gate.address or address_of(os.environ.get(ENV_KEYPAIR) or "/etc/pythia/pumpfun-keypair.json")
    if not pubkey:
        print("no wallet address: make the wallet first (python -m lab.pumpfun_rt.wallet new) or pass --pubkey")
        return 1
    rpc = Rpc(os.environ.get(ENV_RPC) or DEFAULT_RPC)
    rec = simulate(gate, rpc, pubkey, a.mint, a.pool, a.sol)
    print(json.dumps({k: rec[k] for k in ("ok", "rule", "venue", "mint", "pool", "sol", "buy", "round_trip", "error")},
                     indent=1))
    print("simulation OK: recorded for the test gate (valid 24 h)" if rec["ok"] else
          "simulation FAILED: the test gate stays shut")
    return 0 if rec["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
