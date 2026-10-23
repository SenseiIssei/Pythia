"""The gate of the stage-2 on-chain trader: every condition, checked without reading the wallet file.

Modelled on pumpfun_rt.live_exec.LiveGate (docs/ONCHAIN-STAGE2.md, section 4). The trader
swaps only when EVERY one holds, checked at start and again every minute:

  1. env PYTHIA_ONCHAIN_LIVE=1
  2. /etc/pythia/onchain-live-ack, written by the owner (mode 600): mode=test, the books and
     mints it allows, book_usd, max_total_usd, max_trade_usd, max_daily_loss_usd,
     max_convert_usd, expires (at most 90 days ahead) and the line
     "I accept that I can lose all of it". A value above its hard maximum below is refused.
  3. env PYTHIA_ONCHAIN_KEYPAIR: a wallet file the owner made with the wallet tool
     (python -m lab.onchain.wallet new), a regular file not readable by group or others,
     outside the code, with its public address next to it (<file>.pub), and NOT the pump.fun
     wallet (another file and another address)
  4. a successful `live_exec simulate` for this wallet within the last 24 hours
  5. no kill file (/etc/pythia/onchain-kill, <data>/live/onchain/KILL, or
     reports/onchain_live/KILL, the one the app's button writes)
  6. the owner's copy of Jupiter's IDL matches what the guard reads (guard.check_idl)
  7. the RPC (PYTHIA_ONCHAIN_RPC) is plain https and no bundle or relay service; Helius Sender
     (PYTHIA_ONCHAIN_SENDER) only its /fast endpoint with swqos_only=true and mev-protect=true
  8. the `cryptography` package is installed (it signs)

A book trades only when, on top of all that, the ack names it and the pre-registered proof
(research/lab/results/onchain_stage2_prereg.md; reports/onchain/proof.json, at most 36 hours
old) says it passed. Nothing here opens the wallet file, signs or sends.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import os
import stat
import time
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path

from ..pumpfun_rt import live_exec as LX
from . import guard as G
from . import mints as M

ACK_PATH = Path("/etc/pythia/onchain-live-ack")
ETC_KILL = Path("/etc/pythia/onchain-kill")
ENV_LIVE = "PYTHIA_ONCHAIN_LIVE"
ENV_KEYPAIR = "PYTHIA_ONCHAIN_KEYPAIR"
ENV_RPC = "PYTHIA_ONCHAIN_RPC"
ENV_SENDER = "PYTHIA_ONCHAIN_SENDER"
ENV_SENDER_TIP = "PYTHIA_ONCHAIN_SENDER_TIP_SOL"
ENV_IDL = "PYTHIA_ONCHAIN_IDL"
ACCEPT_LINE = LX.ACCEPT_LINE

# Hard maxima in code (test mode, the only mode stage 2 has): whatever the ack says, never more.
TEST_MAX_TOTAL_USD = 500.0
TEST_MAX_TRADE_USD = 100.0
TEST_MAX_DAILY_LOSS_USD = 100.0
TEST_MAX_CONVERT_USD = 250.0             # converts from the app, a UTC day
SMALL_MAX_TRADE_USD = 100.0              # PYTH, RENDER, JTO, POPCAT (20 to 50 bps at 1,000 USD)
SMALL = frozenset({"PYTH", "RENDER", "JTO", "POPCAT"})
MAX_BOOK_SWAPS_DAY = 40
MAX_CONVERTS_DAY = 10
MAX_ETH_SHARE = 0.25                     # WETH hangs on the Wormhole bridge
MAX_COST_BPS = 50.0                      # against Jupiter's prices; dearer, no swap
MAX_PRICE_GAP_PCT = 2.0                  # Jupiter's price against Kraken's mid
RESERVE_L = 20_000_000                   # 0.02 SOL always stays for fees
MIN_BOOK_SWAP_USD = 25.0
EXPIRES_MAX_DAYS = 90
SIMULATE_MAX_AGE_MS = 24 * 3_600_000
PROOF_MAX_AGE_MS = 36 * 3_600_000
CONFIRM_S = 60
SLIPPAGE_BPS = {"SOL": 30, "USDC": 30, "BTC": 30, "ETH": 30, "JUP": 30, "TRUMP": 30, "RAY": 30, "BONK": 75, "WIF": 75,
                "PYTH": 150, "RENDER": 150, "JTO": 150, "POPCAT": 150}
CODES: dict[str, M.Mint] = {"USDC": M.USDC, **M.COINS}          # the stage-2 list, by the coin's code
DEFAULT_RPC = LX.DEFAULT_RPC


def data_dir() -> Path:
    from ..data import ROOT
    return ROOT / "live" / "onchain"


def reports_dir() -> Path:
    from .. import report as rep
    return rep.REPORTS / "onchain_live"


def idl_path() -> Path:
    from ..data import ROOT
    return Path(os.environ.get(ENV_IDL) or (ROOT / "onchain" / "idl" / "jupiter.json"))


def proof_path() -> Path:
    from .. import report as rep
    return rep.REPORTS / "onchain" / "proof.json"


def simulate_path() -> Path:
    return data_dir() / "simulate.json"


def kill_paths() -> list[Path]:
    return [ETC_KILL, data_dir() / "KILL", reports_dir() / "KILL"]


def killed(paths: list[Path] | None = None) -> bool:
    return any(p.exists() for p in (paths if paths is not None else kill_paths()))


def slippage(a: str, b: str) -> int:
    """A swap's slippage: the looser class of its two sides."""
    return max(SLIPPAGE_BPS[a], SLIPPAGE_BPS[b])


# ---------------------------------------------------------------- the owner's confirmation

@dataclass(frozen=True)
class Ack:
    mode: str | None = None
    books: tuple = ()
    mints: tuple = ()                    # codes, e.g. ("SOL", "USDC", "BTC")
    book_usd: float = 0.0
    max_total_usd: float | None = None
    max_trade_usd: float | None = None
    max_daily_loss_usd: float | None = None
    max_convert_usd: float | None = None
    expires: str | None = None
    on_kill: str = "hold"
    problems: tuple = ()

    def view(self) -> dict:
        return {"mode": self.mode, "books": list(self.books), "mints": list(self.mints), "book_usd": self.book_usd,
                "max_total_usd": self.max_total_usd, "max_trade_usd": self.max_trade_usd,
                "max_daily_loss_usd": self.max_daily_loss_usd, "max_convert_usd": self.max_convert_usd,
                "expires": self.expires, "on_kill": self.on_kill}

    def allowed_mints(self) -> frozenset:
        return frozenset(CODES[c].mint for c in self.mints if c in CODES)


def _usd(vals: dict, k: str, path: Path, cap: float, problems: list) -> float | None:
    try:
        v = float(vals.get(k, ""))
    except ValueError:
        problems.append(f"{path} has no {k} in USD")
        return None
    if not (math.isfinite(v) and v > 0):
        problems.append(f"{path}: {k} must be above 0")
        return None
    if v > cap:
        problems.append(f"{path}: {k}={v:g} is above the hard maximum {cap:g} USD")
        return None
    return v


def read_ack(path: Path = ACK_PATH, today: dt.date | None = None) -> Ack:
    """The owner's confirmation, read like pumpfun_rt.live_exec.read_ack."""
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
    problems: list[str] = []
    mode = (vals.get("mode") or "").lower()
    if mode != "test":
        return Ack(problems=(f"{path}: mode must be test (stage 2 has no other mode), not {mode or 'missing'!r}",))
    split = lambda s: tuple(x.strip() for x in (s or "").replace(";", ",").split(",") if x.strip())
    mints = tuple(c.upper() for c in split(vals.get("mints")))
    if not mints:
        problems.append(f"{path} names no mints (mints=SOL,USDC,...)")
    for c in mints:
        if c not in CODES:
            problems.append(f"{path}: {c} is not on the stage-2 list ({', '.join(CODES)})")
    books = split(vals.get("books"))
    total = _usd(vals, "max_total_usd", path, TEST_MAX_TOTAL_USD, problems)
    trade = _usd(vals, "max_trade_usd", path, TEST_MAX_TRADE_USD, problems)
    loss = _usd(vals, "max_daily_loss_usd", path, TEST_MAX_DAILY_LOSS_USD, problems)
    conv = _usd(vals, "max_convert_usd", path, TEST_MAX_CONVERT_USD, problems)
    book_usd = 0.0
    if books:
        book_usd = _usd(vals, "book_usd", path, TEST_MAX_TOTAL_USD, problems) or 0.0
        if total is not None and book_usd > total:
            problems.append(f"{path}: book_usd is above max_total_usd")
    on_kill = (vals.get("on_kill") or "hold").lower()
    if on_kill not in ("hold", "usdc"):
        problems.append(f"{path}: on_kill must be hold or usdc")
        on_kill = "hold"
    expires = vals.get("expires")
    today = today or dt.datetime.now(dt.timezone.utc).date()
    try:
        exp = dt.date.fromisoformat(expires or "")
        if exp < today:
            problems.append(f"{path} expired on {exp}")
        elif (exp - today).days > EXPIRES_MAX_DAYS:
            problems.append(f"{path}: expires is more than {EXPIRES_MAX_DAYS} days ahead")
    except ValueError:
        problems.append(f"{path} has no expires date (expires=YYYY-MM-DD, at most {EXPIRES_MAX_DAYS} days ahead)")
    if not accepted:
        problems.append(f"{path} lacks the line \"{ACCEPT_LINE}\"")
    return Ack("test", books, mints, book_usd, total, trade, loss, conv, expires, on_kill, tuple(problems))


def hard_view() -> dict:
    return {"max_total_usd": TEST_MAX_TOTAL_USD, "max_trade_usd": TEST_MAX_TRADE_USD,
            "max_daily_loss_usd": TEST_MAX_DAILY_LOSS_USD, "max_convert_usd": TEST_MAX_CONVERT_USD,
            "small_max_trade_usd": SMALL_MAX_TRADE_USD, "reserve_sol": RESERVE_L / 1e9,
            "max_converts": MAX_CONVERTS_DAY, "max_book_swaps": MAX_BOOK_SWAPS_DAY, "confirm_s": CONFIRM_S,
            "max_cost_bps": MAX_COST_BPS, "max_eth_share": MAX_ETH_SHARE}


# ---------------------------------------------------------------- the simulation record and the proof

def simulate_problems(rec, address: str | None, now_ms: int, sender: bool = False) -> list[str]:
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
    if sender and not rec.get("sender_tip_l"):
        out.append("Sender is on but the last simulation carried no Sender tip (run live_exec simulate again)")
    return out


def book_problems(book: str, ack: Ack, proof, now_ms: int) -> list[str]:
    """Why a book may not trade: not in the ack, or the pre-registered proof has not passed (steps A to C)."""
    from . import book as B
    out = []
    if book not in ack.books:
        out.append(f"the confirmation file does not name {book}")
    if book != B.NAME:
        out.append(f"{book} has no on-chain paper twin")
    if not isinstance(proof, dict):
        return out + ["no proof report (reports/onchain/proof.json; the pre-registered evidence)"]
    if now_ms - int(proof.get("updated_ms") or 0) > PROOF_MAX_AGE_MS:
        out.append("the proof report is older than 36 h")
    r = (proof.get("books") or {}).get(book)
    if not isinstance(r, dict) or r.get("passed") is not True:
        out.append(f"{book} has not passed the pre-registered on-chain evidence")
    return out


# ---------------------------------------------------------------- endpoints

def sender_problems(url: str) -> list[str]:
    """Only Helius Sender over https, its /fast path, swqos_only=true (the single stake-weighted path, no bundle
    route) and, for swaps, mev-protect=true."""
    out = [w.replace(LX.ENV_SENDER, ENV_SENDER) for w in LX.sender_problems(url)]
    try:
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
    except ValueError:
        return out
    if q.get("mev-protect") != ["true"]:
        out.append(f"{ENV_SENDER} needs mev-protect=true (swaps go past validators tied to sandwiching)")
    return out


def sender_tip_lamports(env=None) -> int:
    from ..pumpfun_rt import txbuild as X
    env = os.environ if env is None else env
    try:
        sol = float(env.get(ENV_SENDER_TIP) or 0.000005)
    except ValueError:
        sol = 0.000005
    return max(X.HELIUS_MIN_TIP_LAMPORTS, min(int(round(sol * 1e9)), X.HELIUS_MAX_TIP_LAMPORTS))


def send_problems(env) -> list[str]:
    why = [f"{ENV_RPC}: {w}" for w in LX.rpc_problems(env.get(ENV_RPC) or DEFAULT_RPC, {})]
    s = (env.get(ENV_SENDER) or "").strip()
    if s:
        why += sender_problems(s)
    return why


# ---------------------------------------------------------------- the gate

def _address(path: str | Path | None) -> str | None:
    return LX.address_of(path)


@dataclass
class Gate:
    ack_path: Path = ACK_PATH
    env: dict | None = None
    kill: object = None
    now_ms: object = None
    idl_file: Path | None = None
    simulate_file: Path | None = None
    pumpfun_wallet_json: Path | None = None
    ack: Ack = field(default_factory=Ack)
    address: str | None = None
    idl: dict | None = None

    def __post_init__(self):
        self.env = os.environ if self.env is None else self.env
        self.kill = self.kill or killed
        self.now_ms = self.now_ms or (lambda: int(time.time() * 1000))

    def sender(self) -> str | None:
        s = (self.env.get(ENV_SENDER) or "").strip()
        return s if s and not sender_problems(s) else None

    def check(self) -> list[str]:
        why: list[str] = []
        if self.env.get(ENV_LIVE) != "1":
            why.append(f"{ENV_LIVE} is not 1")
        self.ack = read_ack(self.ack_path, dt.datetime.fromtimestamp(self.now_ms() / 1000, dt.timezone.utc).date())
        why += list(self.ack.problems)
        self.address = _address(self.env.get(ENV_KEYPAIR))
        why += self._keypair_problems()
        why += simulate_problems(LX.read_json(self.simulate_file or simulate_path()), self.address, self.now_ms(),
                                 sender=self.sender() is not None)
        if self.kill():
            why.append("the kill switch file is there")
        try:
            self.idl = json.loads((self.idl_file or idl_path()).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.idl = None
        why += G.check_idl(self.idl)
        why += send_problems(self.env)
        if not LX.crypto_ok():
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
            path.resolve().relative_to(LX.code_root())
            out.append(f"{ENV_KEYPAIR} lies inside the code folder; keep the wallet file outside it")
        except ValueError:
            pass
        if self.address is None:
            out.append(f"no public address next to the wallet file ({path.name}.pub, written by the wallet tool)")
        pf = self.env.get(LX.ENV_KEYPAIR)
        if pf and Path(pf).resolve() == path.resolve():
            out.append(f"{ENV_KEYPAIR} is the pump.fun wallet file; stage 2 needs its own wallet")
        pf_addrs = {_address(pf)} if pf else set()
        wj = LX.read_json(self.pumpfun_wallet_json or (LX.reports_dir() / "wallet.json"))
        if isinstance(wj, dict):
            pf_addrs.add(wj.get("address"))
        if self.address and self.address in pf_addrs:
            out.append("the on-chain wallet has the pump.fun wallet's address; stage 2 needs its own wallet")
        return out
