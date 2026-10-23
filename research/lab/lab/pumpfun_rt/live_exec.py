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
     2.0), max_daily_loss_sol (at most 0.5), max_trade_sol (at most 0.25) and the
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
  7. the RPC endpoint (PYTHIA_PUMPFUN_RPC) and every parallel one (PYTHIA_PUMPFUN_RPC_URLS) is plain https,
     not a bundle or relay service; a Jito block engine (PYTHIA_PUMPFUN_JITO_URL) only when the owner set
     PYTHIA_PUMPFUN_JITO=1, and only its single-transaction endpoint, never bundles. (The executor itself still
     sends to PYTHIA_PUMPFUN_RPC alone; the parallel and Jito paths belong to the fast path, fastpath.py,
     which is a dry run until the owner decides otherwise.)
  8. the `cryptography` package is installed (it signs; nothing here implements a signature)

Otherwise it refuses with every reason. The wallet file is read only after every
other check passed, by load_signer, and the key never leaves the Signer object;
nothing prints, logs, writes or sends it. Nothing here generates a key (only the
owner-run wallet tool does).

Caps, whatever the environment, the ack or the app say: pipeline.HARD_* (0.25 SOL a
trade, 5 open, 0.6 SOL exposure, 1 SOL daily loss) and in test mode the test
maxima below; the app's settings (reports/pumpfun_rt/live_settings.json) can only
lower them. Under that ceiling the stake follows the wallet (sizing.py: 10 % of the
wallet's SOL plus the open positions' cost, 0.05 to 0.25 SOL, braked in a drawdown,
at most 0.1 until the rule has proved itself live, paused under 0.25 SOL), and the
daily loss limit is at most a quarter of that base at the start of the UTC day.
A total budget (test: max_total_sol) stops every buy once the losses since the
first live trade reach it. A buy also needs the wallet to keep a fee reserve. The
executor checks all of it itself, independently of the pipeline.

Only the programs' public buy and sell, and txbuild.check_own refuses anything
else before signing: no transfers out, no withdrawals, no bundles, no private
relays, nothing that front-runs other users or moves a price on purpose. The only
tip is Helius Sender's: with the owner's PYTHIA_PUMPFUN_SENDER every transaction
carries exactly one, to one of Sender's listed tip accounts, at most
txbuild.HELIUS_MAX_TIP_LAMPORTS (check_own refuses more than one, a larger one, or
one without the switch). A Jito tip exists only in the fast path behind the owner's
PYTHIA_PUMPFUN_JITO=1 (see txbuild.tip).

Settling an order: the stream's trade event of our wallet is the fill. When the
stream misses it, the signature's status settles it: a transaction that landed is
read back with getTransaction and booked from the wallet's own SOL and token
changes; one that landed with an error is a failure that paid its fee; one the
node never saw is given up after GIVE_UP_MS. A send that raised is never taken as
a failure by itself (Sender or the node may have forwarded it); its status decides.
A failed sale is sent again after 1, 2, 4 ... 60 s and given up after
SELL_MAX_FAILS failures in a row (the position is marked stuck and the owner told).

Speed (docs/LATENCY.md, each behind its own switch, all off unless the owner sets PYTHIA_PUMPFUN_FAST=1 or
the single one): the landing from signatureSubscribe and an early status poll, read back at once; reads on their
own thread behind the sends; a prepared sale per open position; the blockhash and a capped fee from recent
prioritization fees in the background; Sender and the plain RPC in parallel; kept connections. None of them
changes a decision, and every transaction still passes check_own.

The day's and the total's realised P&L, which the stops count, are not counters:
they are recomputed from the ledger (whose rows the chain check corrects in place)
plus a journal of the fees of failed transactions (journal.jsonl), so a restart or
a chain correction can never count anything twice.
pump.fun's terms forbid bots on its website and API; this reads the public chain
and sends to a public RPC endpoint, and the owner decides with that knowledge.

    python -m lab.pumpfun_rt.live_exec check        every gate, and why it is shut
    python -m lab.pumpfun_rt.live_exec simulate     a buy and a buy-then-sell built for this wallet and
                                                    simulated on mainnet (nothing is signed or sent)
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import collections
import csv
import dataclasses
import json
import math
import os
import queue
import random
import stat
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from . import chain_pnl as CP
from . import curve as C
from . import pipeline as P
from . import sizing as Z
from . import txbuild as X

ACK_PATH = Path("/etc/pythia/pumpfun-live-ack")
ENV_LIVE = "PYTHIA_PUMPFUN_LIVE"
ENV_KEYPAIR = "PYTHIA_PUMPFUN_KEYPAIR"
ENV_RPC = "PYTHIA_PUMPFUN_RPC"
CHAIN_EVERY_S = 60.0                     # how often closed trades are checked against the chain
FAIL_CARD_EVERY_S = 60.0                 # at most one failure card a minute per position
ORPHAN_AFTER_MS = 600_000                # an unknown token held this long is a late buy: sell it
HOLDINGS_FRESH_MS = 60_000               # orphans are adopted only from a holdings read this young
LANDED_GRACE_MS = 5_000                  # a landed order whose stream fill has not come this long is read back
SELL_MAX_FAILS = 6                       # failed sales in a row before a position is given up as stuck
SELL_BACKOFF_MAX_S = 60                  # the wait before the next try: 1, 2, 4 ... 60 s
RUN_ID = f"{int(time.time())}-{os.getpid()}"   # this process: order lines and ledger rows carry it with the pid
ENV_IDL = "PYTHIA_PUMPFUN_IDL_DIR"
DEFAULT_RPC = "https://api.mainnet-beta.solana.com"
REPORT_MAX_AGE_MS = 36 * 3_600_000
RECHECK_S = 60.0
CONFIRM_MS = 30_000
GIVE_UP_MS = 150_000                     # longer than a 20 s cached blockhash plus its ~60 to 90 s validity
BLOCKHASH_S = 20.0
NOT_PUBLIC = ("jito", "bundle", "relay", "block-engine", "blockengine", "mev")
# The owner's switch for a Jito block engine (our own single transactions with a tip, never bundles), its URL,
# and further plain RPC endpoints for sending the same signed transaction in parallel.
ENV_JITO = "PYTHIA_PUMPFUN_JITO"
ENV_JITO_URL = "PYTHIA_PUMPFUN_JITO_URL"
ENV_RPC_URLS = "PYTHIA_PUMPFUN_RPC_URLS"
JITO_WORDS = ("jito", "block-engine", "blockengine")
# The owner's switch for Helius Sender (our own single transaction with a tiny tip, sent through the stake-
# weighted path; docs/PUMPFUN-LIVE.md section 10): its https URL with swqos_only=true, and the tip in SOL
# (Sender's minimum 0.000005 by default, never above txbuild.HELIUS_MAX_TIP_LAMPORTS).
ENV_SENDER = "PYTHIA_PUMPFUN_SENDER"
ENV_SENDER_TIP = "PYTHIA_PUMPFUN_SENDER_TIP_SOL"
SENDER_HOST_SUFFIX = ".helius-rpc.com"

# The owner's live test: hard maxima in code, whatever the ack says (an ack above them is refused).
ACCEPT_LINE = "I accept that I can lose all of it"
TEST_MAX_TOTAL_SOL = 2.0
TEST_MAX_DAILY_LOSS_SOL = 0.5
TEST_MAX_TRADE_SOL = 0.25                 # 0.05, 0.1 on 2026-10-22, 0.25 on 2026-10-23 (the stake follows the wallet)
SIMULATE_MAX_AGE_MS = 24 * 3_600_000
DEFAULT_TEST_RULE = "P_pool60"            # the least-bad post-migration pool rule until a report says otherwise
RESERVE_SOL = 0.01                        # left in the wallet so every open position can still be sold

# Speed (docs/LATENCY.md): each one off unless the owner sets it; PYTHIA_PUMPFUN_FAST=1 turns all on, a single
# switch set to 0 turns that one off again. None of them changes what is decided or what check_own accepts.
ENV_FAST = "PYTHIA_PUMPFUN_FAST"
ENV_RPC_WS = "PYTHIA_PUMPFUN_RPC_WS"      # the websocket for signatureSubscribe (default: PYTHIA_PUMPFUN_RPC as wss)
SPEED_SWITCHES = {"prepare": "PYTHIA_PUMPFUN_PREPARE_SELLS", "prefetch": "PYTHIA_PUMPFUN_PREFETCH",
                  "dynamic_fee": "PYTHIA_PUMPFUN_DYNAMIC_FEE", "parallel": "PYTHIA_PUMPFUN_PARALLEL_SEND",
                  "keepalive": "PYTHIA_PUMPFUN_KEEPALIVE", "ws_confirm": "PYTHIA_PUMPFUN_WS_CONFIRM",
                  "wake": "PYTHIA_PUMPFUN_WAKE", "send_first": "PYTHIA_PUMPFUN_SEND_FIRST"}
FAST_STATUS_MS = 2_000                    # fast: a signature's status asked 2 s after the send and every 2 s
FAST_GRACE_MS = 0                         # fast: a landed order is read back at once, not after LANDED_GRACE_MS
LANDED_RETRY_MS = 500                     # a landed transaction the node cannot return yet is asked again after this
PREFETCH_BLOCKHASH_S = 10.0               # the background refresh of the blockhash (well inside its ~60 s)
PREFETCH_EVERY_S = 0.5                    # the background loop: blockhash, fees, prepared sales
SENDER_PING_S = 5.0                       # Sender's /ping keeps its connection warm (its docs)


def backoff_ms(fails: int) -> int:
    """The wait before the next try of a sale that failed `fails` times in a row: 1, 2, 4 ... 60 s."""
    return int(min(SELL_BACKOFF_MAX_S, 2 ** max(0, fails - 1)) * 1000)


def landed(st) -> bool:
    """A signature status that says the transaction is in a confirmed block (with or without an error)."""
    return isinstance(st, dict) and st.get("confirmationStatus") in ("confirmed", "finalized")


@dataclass(frozen=True)
class Speed:
    """The free latency fixes, each behind its own switch (all off by default: the executor then works exactly
    as before)."""
    prepare: bool = False                 # a prepared sale per open position, refreshed with the blockhash
    prefetch: bool = False                # the blockhash (and the fee estimate) refreshed in the background
    dynamic_fee: bool = False             # the priority fee from recent prioritization fees, capped
    parallel: bool = False                # Sender and the plain RPC get the same signed bytes at once
    keepalive: bool = False               # persistent HTTPS connections, Sender's /ping every 5 s
    ws_confirm: bool = False              # signatureSubscribe tells a landing at once (the status poll stays)
    wake: bool = False                    # the service handles a worker result at once, not at the next second
    send_first: bool = False              # reads (status, fees, holdings) run on their own thread, never ahead of a send
    status_ms: int = CONFIRM_MS           # when a signature's status is asked (after the send, then again)
    grace_ms: int = LANDED_GRACE_MS       # how long a landed order waits for the stream's fill before it is read back
    fee_cap_sol: float = C.PRIORITY_SOL   # the dynamic fee's ceiling per transaction (today's fixed fee by default)
    ws_url: str | None = None

    def on(self) -> list[str]:
        return [k for k in SPEED_SWITCHES if getattr(self, k)]


def speed_of(env=None) -> Speed:
    """The owner's speed settings from the environment. The fee cap is never above fastpath's hard maximum."""
    from .fastpath import HARD_MAX_PRIORITY_SOL
    env = os.environ if env is None else env
    fast = env.get(ENV_FAST) == "1"
    flags = {}
    for k, name in SPEED_SWITCHES.items():
        v = (env.get(name) or "").strip()
        flags[k] = v == "1" if v in ("0", "1") else fast

    def num(name, default):
        try:
            v = float(env.get(name) or default)
        except ValueError:
            return default
        return v if math.isfinite(v) and v >= 0 else default
    fast_confirm = flags["ws_confirm"] or fast
    status = int(num("PYTHIA_PUMPFUN_STATUS_MS", FAST_STATUS_MS if fast_confirm else CONFIRM_MS))
    grace = int(num("PYTHIA_PUMPFUN_LANDED_GRACE_MS", FAST_GRACE_MS if fast_confirm else LANDED_GRACE_MS))
    cap = min(num("PYTHIA_PUMPFUN_FEE_CAP_SOL", C.PRIORITY_SOL), HARD_MAX_PRIORITY_SOL)
    ws = (env.get(ENV_RPC_WS) or "").strip() or ws_of(env.get(ENV_RPC) or DEFAULT_RPC)
    return Speed(**flags, status_ms=max(500, min(status, CONFIRM_MS)), grace_ms=min(grace, LANDED_GRACE_MS),
                 fee_cap_sol=cap, ws_url=ws if ws.startswith("wss://") else None)


def ws_of(url: str) -> str:
    """The websocket of an https RPC endpoint (the same host, path and query)."""
    return "wss://" + url[len("https://"):] if url.startswith("https://") else ""


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
    """The folder that holds the `lab` package (research/lab, or /app in the lab image), as in wallet.py."""
    return Path(__file__).resolve().parents[2]


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


def simulate_problems(rec, address: str | None, now_ms: int, rule: str | None = None,
                      sender: bool = False) -> list[str]:
    if not isinstance(rec, dict):
        return ["no successful simulation yet (live_exec simulate)"]
    out = []
    if sender and not rec.get("sender_tip_l"):
        out.append("Sender is on but the last simulation carried no Sender tip (run live_exec simulate again)")
    if rule in P.BY_NAME and rec.get("venue") != venue_of(rule):
        out.append(f"the last simulation was on the {rec.get('venue')}, {rule} trades the {venue_of(rule)} "
                   "(run live_exec simulate without --venue)")
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
            sender = (self.env.get(ENV_SENDER) or "").strip()
            why += simulate_problems(read_json(self.simulate_file or simulate_path()), self.address, self.now_ms(),
                                     self.rule, sender=bool(sender) and not sender_problems(sender))
        else:
            self.rule = ack.rule
            why += self._readiness(rep, ack.rule)
        if self.kill():
            why.append("the kill switch file is there")
        why += self._keypair_problems()
        why += self._idl_problems()
        why += send_problems(self.env)
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


def is_jito_engine(url: str) -> bool:
    """A Jito block engine's URL (its host names it), whatever the path."""
    try:
        host = (urllib.parse.urlsplit(url).hostname or "").lower()
    except ValueError:
        return False
    return any(w in host for w in JITO_WORDS)


def rpc_problems(url: str, env=None) -> list[str]:
    """Why an endpoint may not be sent to: not https, or a bundle, relay or MEV service. A Jito block engine is
    allowed only when the owner set PYTHIA_PUMPFUN_JITO=1, and then only its single-transaction endpoint (our
    own transaction with its tip inside; never the bundles endpoint, never anyone else's transaction)."""
    env = os.environ if env is None else env
    try:
        u = urllib.parse.urlsplit(url)
    except ValueError:
        return ["the RPC endpoint is not a URL"]
    host = (u.hostname or "").lower()
    path = (u.path or "").lower()
    if u.scheme != "https" or not host:
        return ["the RPC endpoint must be https"]
    if is_jito_engine(url):
        if env.get(ENV_JITO) != "1":
            return [f"the endpoint is a Jito block engine and {ENV_JITO} is not 1 (the owner's switch)"]
        if "bundle" in path or "bundle" in host or not path.rstrip("/").endswith("/transactions"):
            return ["only the block engine's single-transaction endpoint (/api/v1/transactions) is allowed, "
                    "never bundles"]
        if any(w in host or w in path for w in ("relay", "mev")):
            return ["the RPC endpoint looks like a relay or MEV service"]
        return []
    if any(w in host or w in path for w in NOT_PUBLIC):
        return ["the RPC endpoint looks like a bundle or relay service; only a plain public RPC is allowed"]
    return []


def sender_problems(url: str) -> list[str]:
    """Why a Sender URL may not be used: only Helius Sender over https, its /fast path, swqos_only=true
    (the single stake-weighted path with the smallest tip; never the dual route through a bundle engine)."""
    try:
        u = urllib.parse.urlsplit(url)
    except ValueError:
        return [f"{ENV_SENDER} is not a URL"]
    host = (u.hostname or "").lower()
    query = urllib.parse.parse_qs(u.query)
    out = []
    if u.scheme != "https":
        out.append(f"{ENV_SENDER} must be https")
    if not (host.endswith(SENDER_HOST_SUFFIX) and "sender" in host):
        out.append(f"{ENV_SENDER} is not a Helius Sender endpoint")
    if (u.path or "").rstrip("/") != "/fast":
        out.append(f"{ENV_SENDER} must be the /fast endpoint")
    if query.get("swqos_only") != ["true"]:
        out.append(f"{ENV_SENDER} needs swqos_only=true (the single stake-weighted path, no bundle route)")
    return out


def sender_tip_lamports(env=None) -> int:
    """The tip each Sender transaction carries: the setting, kept inside Sender's minimum and our hard cap."""
    env = os.environ if env is None else env
    try:
        sol = float(env.get(ENV_SENDER_TIP) or 0.000005)
    except ValueError:
        sol = 0.000005
    return max(X.HELIUS_MIN_TIP_LAMPORTS, min(int(round(sol * C.LAMPORTS)), X.HELIUS_MAX_TIP_LAMPORTS))


def send_problems(env=None) -> list[str]:
    """Every send endpoint the owner configured: PYTHIA_PUMPFUN_RPC, each of PYTHIA_PUMPFUN_RPC_URLS (parallel
    sending) and PYTHIA_PUMPFUN_JITO_URL (only with PYTHIA_PUMPFUN_JITO=1)."""
    env = os.environ if env is None else env
    why = rpc_problems(env.get(ENV_RPC) or DEFAULT_RPC, env)
    for u in [x.strip() for x in (env.get(ENV_RPC_URLS) or "").split(",") if x.strip()]:
        why += [f"{ENV_RPC_URLS}: {w}" for w in rpc_problems(u, env)]
    j = (env.get(ENV_JITO_URL) or "").strip()
    if j:
        if not is_jito_engine(j):
            why.append(f"{ENV_JITO_URL} is not a Jito block engine")
        else:
            why += [f"{ENV_JITO_URL}: {w}" for w in rpc_problems(j, env)]
    elif env.get(ENV_JITO) == "1" and not is_jito_engine(env.get(ENV_RPC) or ""):
        why.append(f"{ENV_JITO}=1 but no block engine is configured ({ENV_JITO_URL})")
    sender = (env.get(ENV_SENDER) or "").strip()
    if sender:
        why += sender_problems(sender)
    return why


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
    def __init__(self, url: str, timeout: float = 8.0, poster=None, keepalive: bool = False):
        if rpc_problems(url):
            raise ValueError(rpc_problems(url)[0])
        self.url, self.timeout, self.poster = url, timeout, poster
        self.n = 0
        # keepalive: idle HTTPS connections are kept and reused (newest first), so a send does not pay a new TCP
        # and TLS handshake (100 to 300 ms); a connection is used by one thread at a time
        self.keepalive = keepalive
        self.idle: list = []
        self.lock = threading.Lock()

    def _conn(self):
        import http.client
        with self.lock:
            if self.idle:
                return self.idle.pop()
        u = urllib.parse.urlsplit(self.url)
        return http.client.HTTPSConnection(u.hostname, u.port or 443, timeout=self.timeout)

    def request(self, method: str, path: str, body: bytes | None = None) -> tuple[int, bytes]:
        """One request over a kept connection; a connection the server closed meanwhile is replaced once
        (resending a signed transaction is harmless: one signature can land only once)."""
        import http.client
        for attempt in (0, 1):
            c = self._conn()
            try:
                c.request(method, path, body=body, headers={"Content-Type": "application/json",
                                                            "User-Agent": "pythia-lab"})
                r = c.getresponse()
                data = r.read()
            except (http.client.HTTPException, ConnectionError) as e:
                c.close()
                if attempt:
                    raise RuntimeError(f"{type(e).__name__}: {e}")
                continue
            except Exception:
                c.close()
                raise
            with self.lock:
                self.idle.append(c)
                del self.idle[:-4]
            return r.status, data
        raise RuntimeError("no connection")                 # pragma: no cover

    def ping(self) -> bool:
        """Sender's GET /ping on the same host: keeps a kept connection warm. Never raises."""
        try:
            return self.request("GET", "/ping")[0] == 200
        except Exception:
            return False

    def call(self, method: str, params: list):
        self.n += 1
        body = {"jsonrpc": "2.0", "id": self.n, "method": method, "params": params}
        if self.poster is not None:
            d = self.poster(method, params)
        elif self.keepalive:
            u = urllib.parse.urlsplit(self.url)
            status, raw = self.request("POST", (u.path or "/") + (f"?{u.query}" if u.query else ""),
                                       json.dumps(body).encode())
            if status != 200:
                raise RuntimeError(f"HTTP Error {status}")
            d = json.loads(raw.decode())
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

    def recent_fees(self, accounts: list[str]) -> list:
        """Recent prioritization fees of transactions that wrote these accounts (read only)."""
        return self.call("getRecentPrioritizationFees", [accounts]) or []

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

    def transaction(self, sig: str):
        """A landed transaction as the node has it (read only), None while it does not have it."""
        return self.call("getTransaction", [sig, {"encoding": "json", "commitment": "confirmed",
                                                  "maxSupportedTransactionVersion": 0}])

    def fee_of(self, sig: str) -> int | None:
        """The network fee a landed transaction paid (lamports), None when not known yet."""
        res = self.transaction(sig)
        try:
            return int(res["meta"]["fee"])
        except (KeyError, TypeError, ValueError):
            return None

    def send(self, tx: bytes, skip_preflight: bool = False) -> str:
        opts = ({"encoding": "base64", "skipPreflight": True, "maxRetries": 0} if skip_preflight else
                {"encoding": "base64", "skipPreflight": False, "preflightCommitment": "processed", "maxRetries": 2})
        return self.call("sendTransaction", [base64.b64encode(tx).decode(), opts])

    def simulate(self, tx: bytes) -> dict:
        return self.call("simulateTransaction", [base64.b64encode(tx).decode(),
                                                 {"encoding": "base64", "sigVerify": False,
                                                  "replaceRecentBlockhash": True, "commitment": "processed"}])

    def statuses(self, sigs: list[str]) -> list:
        # With the history: the node's recent status cache covers only about a minute, so a transaction
        # that landed before the check came back as unknown and was given up as "not landed" (CCC, Bundle).
        return self.call("getSignatureStatuses", [sigs, {"searchTransactionHistory": True}])["value"]


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
        self.sender: Rpc | None = None                # Helius Sender, when the owner switched it on
        self.sender_tip_l = 0                         # the tip each transaction then carries
        self.speed = Speed()
        self.fees = None                              # fastpath.FeeEstimator with the dynamic fee
        self.fee_accounts: list[str] = []             # the accounts its estimate reads (open positions' pools)
        self.prepared: dict[int, tuple] = {}          # pid -> (key, ixs, blockhash, message): a ready sale
        self.last_prepared = False                    # the last build used a prepared sale
        self.pool_x = None                            # the parallel send's two threads

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

    # ------------------------------------------------------------ speed (all of it off unless self.speed says so)
    def refresh(self) -> None:
        """The background part: with prefetch a fresh blockhash every PREFETCH_BLOCKHASH_S, so a send never waits
        for one; with the dynamic fee its estimate. Errors keep the last values (blockhash() fetches itself when
        its own is too old)."""
        if self.speed.prefetch and (self.hash is None or time.monotonic() - self.hash[0] >= PREFETCH_BLOCKHASH_S):
            try:
                self.hash = (time.monotonic(), self.rpc.blockhash())
            except Exception as e:
                print(f"live: blockhash not refreshed ({type(e).__name__}: {e})"[:200], flush=True)
        if self.speed.dynamic_fee:
            self.dynamic_fee()

    def dynamic_fee(self) -> int:
        """The priority fee from recent prioritization fees of the accounts pump.fun trades write (the open
        positions' pools and curves, the listed buyback recipients): fastpath's percentile, between its floor and
        the cap (speed.fee_cap_sol, today's fixed fee unless the owner raised it, never above fastpath's hard
        maximum). It only sets the compute-unit price; check_own sees the same instructions as before."""
        from . import fastpath as F
        accts = sorted(set(self.fee_accounts) | set(X.BUYBACK_FEE_RECIPIENTS))[:128]
        if self.fees is None:
            self.fees = F.FeeEstimator(lambda m, p: self.rpc.recent_fees(p[0]), accts, units=X.UNITS + 100_000,
                                       cap_sol=self.speed.fee_cap_sol)
        self.fees.accounts = accts
        self.fees.tick()
        self.priority_l = int(min(self.fees.priority_lamports(), self.speed.fee_cap_sol * C.LAMPORTS))
        return self.priority_l

    def _key(self, o: P.Order, pool: str | None, close: bool) -> tuple:
        return (o.mint, o.venue, pool, int(o.tokens), int(o.limit_l), bool(close), self.priority_l,
                self.sender is not None, self.sender_tip_l)

    def prepare(self, user: str, o: P.Order, pool: str | None, close: bool) -> bool:
        """A ready sale for an open position: built now (the accounts read and cached, check_own passed) and
        compiled with the current blockhash; again when the blockhash, the fee or the position changes. True
        when it is ready."""
        k = self._key(o, pool, close)
        bh = self.blockhash()
        have = self.prepared.get(o.pid)
        if have is not None and have[0] == k:
            if have[2] != bh:
                self.prepared[o.pid] = (k, have[1], bh, X.compile_message(user, have[1], bh))
            return True
        ixs = self.ixs(user, o, pool, close)
        self.prepared[o.pid] = (k, ixs, bh, X.compile_message(user, ixs, bh))
        return True

    def forget(self, keep) -> None:
        for pid in [p for p in self.prepared if p not in keep]:
            self.prepared.pop(pid, None)

    def build(self, user: str, o: P.Order, pool: str | None, close: bool) -> bytes:
        """The order's message. A prepared sale is used only when it is exactly this order (token, venue, pool,
        amount, floor, close, fee, tip); its instructions pass check_own again before they are signed."""
        have = self.prepared.get(o.pid) if o.side == "sell" else None
        self.last_prepared = False
        if have is not None and have[0] == self._key(o, pool, close):
            X.check_own(user, have[1], sender_tip_ok=self.sender is not None)
            bh = self.blockhash()
            self.last_prepared = True
            return have[3] if have[2] == bh else X.compile_message(user, have[1], bh)
        return X.compile_message(user, self.ixs(user, o, pool, close), self.blockhash())

    def curve(self, mint: str) -> X.CurveInfo:
        glob = self._cached("global", 600, lambda: self.rpc.account(X.pda([b"global"], X.PUMP))[0])
        owner = self._cached("owner:" + mint, 3600, lambda: self.rpc.account(mint)[1])
        bc = self._cached("bc:" + mint, 600,
                          lambda: self.rpc.account(X.pda([b"bonding-curve", X.key(mint)], X.PUMP))[0])
        return X.curve_info(mint, owner, glob, bc, self.idl_pump, pick=random.choice)

    def curve_complete(self, mint: str) -> bool:
        """The bonding curve read again (not from the cache): True when it is complete, so the token
        trades only in its pool now (a migration the stream may have missed)."""
        self.cache.pop("bc:" + mint, None)
        data = self._cached("bc:" + mint, 600,
                            lambda: self.rpc.account(X.pda([b"bonding-curve", X.key(mint)], X.PUMP))[0])
        return len(data) > 48 and bool(data[48])

    def pool(self, pool: str, mint: str, fresh: bool = False) -> X.PoolInfo:
        """The pool's accounts and flags; a random listed buyback fee recipient each time (as the SDK
        does, so our trades do not all lock the same account). `fresh` reads the pool account again
        (its virtual_quote_reserves moves with every v2 trade)."""
        cfg = self._cached("config", 600, lambda: self.rpc.account(X.pda([b"global_config"], X.PUMP_AMM))[0])
        owner = self._cached("owner:" + mint, 3600, lambda: self.rpc.account(mint)[1])
        if fresh:
            self.cache.pop("pool:" + pool, None)
        data = self._cached("pool:" + pool, 600, lambda: self.rpc.account(pool)[0])
        info = X.pool_info(pool, data, cfg, owner, self.idl_amm, pick=random.choice)
        if info.base_mint != mint:
            raise RuntimeError("the pool is not this token's")
        return info

    def ixs(self, user: str, o: P.Order, pool: str | None, close: bool) -> list[X.Ix]:
        if o.venue == "pool":
            if not pool:
                raise RuntimeError("no pool known for this token")
            info = self.pool(pool, o.mint)
            if not info.supports_v2():
                raise RuntimeError("the pool takes no v2 trade (a cashback coin); refused, v1 is never sent")
            if o.side == "buy":
                spend, least = pool_buy_amounts(o)
                ixs = X.amm_buy(user, info, spend, least, self.priority_l, self.idl_amm)
            else:
                ixs = X.amm_sell(user, info, o.tokens, o.limit_l, self.priority_l, close, self.idl_amm)
        else:
            info = self.curve(o.mint)
            if not info.supports_v3():
                raise RuntimeError("the curve takes no v3 trade (a cashback coin); refused, legacy is never sent")
            ixs = (X.pump_buy(user, info, o.tokens, o.limit_l, self.priority_l, self.idl_pump) if o.side == "buy" else
                   X.pump_sell(user, info, o.tokens, o.limit_l, self.priority_l, close, self.idl_pump))
        if self.sender is not None and self.sender_tip_l:
            # Sender takes a transaction only with a compute-unit price (budget() adds it) and a tip.
            ixs = ixs + [X.tip(user, random.choice(sorted(X.HELIUS_TIP_ACCOUNTS)), self.sender_tip_l)]
        X.check_own(user, ixs, sender_tip_ok=self.sender is not None)   # a plain buy or sale for this wallet
        return ixs

    def send(self, tx: bytes) -> str:
        """Through Sender when it is on (no preflight, as Sender recommends; the holdings check catches a sale
        of what is gone), else, or when Sender does not answer, through the plain RPC with its preflight.
        Sender may have forwarded a transaction even when it answers with an error: its signature's status
        is asked first, and the same signed bytes go to the plain RPC only when the node does not know it.
        The caller keeps the transaction's own signature whatever this returns, and treats an exception as
        "sent, outcome unknown" (the status settles it). With speed.parallel both get it at once (parallel())."""
        if self.sender is not None and self.speed.parallel:
            return self.parallel(tx)
        if self.sender is not None:
            try:
                return self.sender.send(tx, skip_preflight=True)
            except Exception as e:
                print(f"live: Sender did not take it ({type(e).__name__}: {e})"[:220], flush=True)
                local = X.b58(tx[1:65])
                try:
                    st = self.rpc.statuses([local])[0]
                except Exception:
                    st = None
                if st is not None:
                    print(f"live: the node already knows {local[:12]}...; not sent again", flush=True)
                    return local
                print("live: the plain RPC sends the same transaction", flush=True)
        return self.rpc.send(tx)

    def parallel(self, tx: bytes) -> str:
        """The same signed bytes to Sender (no preflight) and to the plain RPC (with its preflight) at once; the
        first that takes it answers. One transaction, one signature: it can land only once, however many
        endpoints forward it (Sender's docs allow sending to other endpoints too). Raises only when both did."""
        import concurrent.futures as cf
        if self.pool_x is None:
            self.pool_x = cf.ThreadPoolExecutor(max_workers=2, thread_name_prefix="pumpfun-send")
        jobs = {self.pool_x.submit(self.sender.send, tx, True): "Sender",
                self.pool_x.submit(self.rpc.send, tx): "the plain RPC"}
        errs = []
        for f in cf.as_completed(jobs):
            try:
                return f.result()
            except Exception as e:
                errs.append(f"{jobs[f]}: {type(e).__name__}: {e}")
        raise RuntimeError("; ".join(errs)[:200])


class SigWatcher:
    """signatureSubscribe (confirmed) on the RPC's websocket for every order sent: the node says it landed, with
    or without an error, as soon as it is in a confirmed block, instead of the status poll's 30 s and the
    stream's own fill, which missed 28 of the first 65 fills (docs/LATENCY.md). Read only; its own thread and
    event loop; reconnects and subscribes again whatever is still open. The status poll stays as the fallback.
    on_status(pid, sig, status, wall_ms) is called on this thread (the executor only queues it)."""

    def __init__(self, url: str, on_status, clock=None, start: bool = True):
        self.url, self.on_status = url, on_status
        self.clock = clock or (lambda: int(time.time() * 1000))
        self.want: dict[str, int] = {}               # sig -> pid, until its notification came
        self.req: dict[int, str] = {}                 # request id -> sig
        self.subs: dict[int, str] = {}                # subscription id -> sig
        self.n = 0
        self.ws = None
        self.loop = None
        self.up = False
        self.notes = 0
        if start:
            threading.Thread(target=self._thread, name="pumpfun-sigs", daemon=True).start()

    def watch(self, sig: str, pid: int) -> None:
        self.want[sig] = pid
        while len(self.want) > 256:                  # never more than a few open; old ones are dropped
            self.want.pop(next(iter(self.want)))
        if self.loop is not None and self.ws is not None:
            try:
                asyncio.run_coroutine_threadsafe(self._sub(sig), self.loop)
            except Exception:                         # the next connection subscribes it
                pass

    def forget(self, sig: str | None) -> None:
        if sig:
            self.want.pop(sig, None)

    def message(self, sig: str) -> str:
        self.n += 1
        self.req[self.n] = sig
        return json.dumps({"jsonrpc": "2.0", "id": self.n, "method": "signatureSubscribe",
                           "params": [sig, {"commitment": "confirmed"}]})

    async def _sub(self, sig: str) -> None:
        if self.ws is not None and sig in self.want:
            await self.ws.send_str(self.message(sig))

    def handle(self, text: str) -> None:
        """One websocket message: a subscription's id, or a signature's notification."""
        try:
            d = json.loads(text)
        except ValueError:
            return
        if not isinstance(d, dict):
            return
        if d.get("id") in self.req:
            sig = self.req.pop(d["id"])
            if isinstance(d.get("result"), int):
                self.subs[d["result"]] = sig
            return
        if d.get("method") != "signatureNotification":
            return
        p = d.get("params") or {}
        sig = self.subs.pop(p.get("subscription"), None)
        v = ((p.get("result") or {}).get("value"))
        if sig is None or not isinstance(v, dict) or "err" not in v:
            return
        pid = self.want.pop(sig, None)
        if pid is None:
            return
        self.notes += 1
        self.on_status(pid, sig, {"err": v["err"], "confirmationStatus": "confirmed"}, int(self.clock()))

    def _thread(self) -> None:
        asyncio.run(self._run())

    async def _run(self) -> None:
        import aiohttp
        self.loop = asyncio.get_running_loop()
        wait = 1.0
        async with aiohttp.ClientSession() as s:
            while True:
                try:
                    async with s.ws_connect(self.url, heartbeat=20, max_msg_size=1 << 20) as ws:
                        self.ws, self.req, self.subs, self.up, wait = ws, {}, {}, True, 1.0
                        for sig in list(self.want):
                            await ws.send_str(self.message(sig))
                        async for msg in ws:
                            if msg.type != aiohttp.WSMsgType.TEXT:
                                break
                            self.handle(msg.data)
                except Exception as e:                # the status poll covers the time it is down
                    print(f"live: signature websocket down ({type(e).__name__})", flush=True)
                self.ws, self.up = None, False
                await asyncio.sleep(wait)
                wait = min(30.0, wait * 2)


def pool_buy_amounts(o: P.Order) -> tuple[int, int]:
    """A pool buy spends exactly the stake (buy_exact_quote_in_v2) and accepts no fewer tokens than the
    signal's quote on the effective reserves less the slippage tolerance: the same bound as the paper
    model's, which fails a buy whose cost for those tokens is more than SLIP_TOL above the stake."""
    spend = o.stake_l or int(o.limit_l / (1 + C.SLIP_TOL))
    return spend, max(1, int(o.tokens / (1 + C.SLIP_TOL)))


def totals_path() -> Path:
    return data_dir() / "totals.json"


def load_totals() -> dict:
    d = read_json(totals_path())
    if not isinstance(d, dict):
        d = {}
    return {"pnl_l": int(d.get("pnl_l") or 0), "since_ms": d.get("since_ms"), "trades": int(d.get("trades") or 0),
            "total_alerted": bool(d.get("total_alerted")), "day_base": d.get("day_base")}


def journal_path() -> Path:
    return data_dir() / "journal.jsonl"


def journal(rec: dict) -> None:
    """One realised amount that is in no ledger row (the fee of a failed transaction, a carried-over sum)."""
    try:
        d = data_dir()
        d.mkdir(parents=True, exist_ok=True)
        with journal_path().open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, default=str) + "\n")
    except OSError as e:
        print(f"live: journal not written ({e})", flush=True)


def read_journal() -> list[dict]:
    try:
        lines = journal_path().read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            j = json.loads(line)
        except ValueError:
            continue
        if isinstance(j, dict) and isinstance(j.get("pnl_l"), (int, float)):
            out.append(j)
    return out


def realised(day: int) -> dict:
    """The realised P&L the stops count, recomputed (never incremented): every ledger row (the chain check
    corrects them in place) plus every journal amount whose signature no settled row holds yet (a settled
    row's chain value already contains the fees of its failed transactions). For `day` (days since 1970,
    UTC) the same over the rows that closed that day and the amounts booked that day."""
    rows = read_ledger(10 ** 9)
    done = CP.absorbed(data_dir())
    out = {"total_l": 0, "day_l": 0, "trades": 0, "trades_day": 0, "wins_day": 0, "first_ms": None}
    for r in rows:
        pnl = int(round((r.get("pnl_sol") or 0.0) * C.LAMPORTS))
        out["total_l"] += pnl
        out["trades"] += 1
        ex = r.get("exit_ms")
        if ex is not None:
            out["first_ms"] = int(ex) if out["first_ms"] is None else min(out["first_ms"], int(ex))
            if int(ex) // P.DAY_MS == day:
                out["day_l"] += pnl
                out["trades_day"] += 1
                out["wins_day"] += int(pnl > 0)
    for j in read_journal():
        if j.get("sig") and j["sig"] in done:
            continue
        v, t = int(j["pnl_l"]), int(j.get("t") or 0)
        out["total_l"] += v
        if t // P.DAY_MS == day:
            out["day_l"] += v
        if t:
            out["first_ms"] = t if out["first_ms"] is None else min(out["first_ms"], t)
    return out


class LiveExecutor:
    """Same interface as pipeline.PaperExecutor. Sends from a worker thread; every result and
    fill is handed to the pipeline on the stream's own thread (poll, on_trade). Its own timers
    (when to ask for a status, when to give up, when to try a failed sale again) run on wall
    time (self.clock), never on the stream's clock, which can lag behind."""

    kind = "live"

    def __init__(self, gate: LiveGate, signer, builder, limits: P.Limits, clock=None, start: bool = True,
                 mode: str = "full", max_total_sol: float | None = None, rule: str | None = None,
                 totals: dict | None = None, on_stop=None, on_leftover=None, speed: Speed | None = None):
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
        self.on_chain = None                          # () after the ledger was corrected from the chain
        self.sell_sigs: dict[int, list[str]] = {}     # pid -> signatures of its sales that were sent
        self.buy_sigs: dict[int, list[str]] = {}      # pid -> signatures of its buys that were sent
        self.buy_sig: dict[int, str] = {}             # pid -> the buy that filled (save_open, the ledger row)
        self.verifying: dict[int, tuple] = {}         # pid -> (pend, why, fee) while its holding is read
        self.verify_sales = start                     # a failed sale reads the wallet's holding first
        self.filled_sigs: collections.OrderedDict = collections.OrderedDict()   # booked fills, newest last
        self.recent_fills: collections.deque = collections.deque(maxlen=64)      # (mint, side, tokens, wall ms)
        self.sell_fails: dict[int, int] = {}          # pid -> failed sales in a row
        self.retry_at: dict[int, int] = {}            # pid -> wall ms before which no sale of it is sent
        self.deferred: dict[int, tuple] = {}          # pid -> a sale waiting for its retry time
        self.stuck: dict[int, str] = {}               # pid -> why its sale was given up (the owner sells it)
        self.held: dict[str, int] = {}                # mint -> the wallet's holding read after a failed sale
        self.given_up: dict[str, dict] = {}           # mint -> the last buy given up as not landed
        self.orphan_pid = -1000                       # leftover ids for orphans, below the restart's
        self.trades_today = 0
        self.wins_today = 0
        self.stake: dict | None = None                # {"sol", "why"}: the stake the wallet allows (sizing.py)
        self.stake_bal_l: int | None = None           # the balance that stake was sized with
        self.speed = speed or Speed()
        if hasattr(builder, "speed"):
            builder.speed = self.speed
        self.rq: queue.Queue = queue.Queue()         # reads, on their own thread with send_first
        self.on_result = None                         # () after every worker result (the service's wake-up)
        self.watcher: SigWatcher | None = None        # signatureSubscribe, with ws_confirm
        self.want_sales: dict[int, tuple] = {}        # pid -> (order, pool, close): the sales to keep prepared
        self.last_ping = 0.0
        self.prep_failed: dict[int, float] = {}       # pid -> when its sale last failed to prepare
        self._carry()
        self._roll()                                  # the day and its P&L are set before anything books
        self.worker = None
        if start:
            self.worker = threading.Thread(target=self._work, name="pumpfun-live", daemon=True)
            self.worker.start()
            if self.speed.send_first:
                threading.Thread(target=self._work, args=(self.rq,), name="pumpfun-live-reads", daemon=True).start()
            if self.speed.prepare or self.speed.prefetch or self.speed.dynamic_fee or self.speed.keepalive:
                threading.Thread(target=self._prefetch_loop, name="pumpfun-live-prefetch", daemon=True).start()
            if signer is not None:
                threading.Thread(target=self._chain_loop, name="pumpfun-live-chain", daemon=True).start()
                if self.speed.ws_confirm and self.speed.ws_url:
                    self.watcher = SigWatcher(self.speed.ws_url, self._confirmed)

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
        if self.closed_why:
            return f"live gate shut: {self.closed_why}"
        if self.limits.stake_sol <= 0:
            return (self.stake or {}).get("why") or "stake paused"
        return None

    def sized(self, lim: P.Limits) -> P.Limits:
        """The limits with the stake the wallet allows (sizing.py) under lim's stake as the ceiling, and the
        daily loss limit at most DAILY_LOSS_SHARE of the base at the start of the UTC day (recorded once a
        day in totals.json). Without a balance read yet: no buys."""
        self.stake_bal_l = self.balance_l
        if self.balance_l is None:
            self.stake = {"sol": 0.0, "why": "stake paused: wallet balance not read yet"}
            return dataclasses.replace(lim, stake_sol=0.0)
        bal = self.balance_l / C.LAMPORTS
        open_l = sum(self.exposure.values()) + sum(int(v.get("cost_l") or 0) for v in self.leftovers.values())
        sol, why = Z.sized(balance_sol=bal, open_cost_sol=open_l / C.LAMPORTS, ceiling_sol=lim.stake_sol,
                           **Z.from_ledger(self.rule))
        self.stake = {"sol": sol, "why": why}
        day = self.clock() // P.DAY_MS
        db = self.totals.get("day_base")
        if not (isinstance(db, list) and len(db) == 2 and db[0] == day):
            db = self.totals["day_base"] = [day, bal + open_l / C.LAMPORTS]
            try:
                write_json(totals_path(), self.totals)
            except OSError as e:
                print(f"live: totals not written ({e})", flush=True)
        loss = min(lim.max_daily_loss_sol, Z.DAILY_LOSS_SHARE * float(db[1]))
        return dataclasses.replace(lim, stake_sol=sol, max_daily_loss_sol=loss)

    def _roll(self) -> None:
        d = self.clock() // P.DAY_MS
        if d != self.day:
            # The day's closed trades from the ledger and the day's journal, so a restart does not forget
            # today's losses (the daily stop counts them); a new day starts with what it already has.
            self.day = d
            self.recompute()

    def _carry(self) -> None:
        """Once, before the journal exists: whatever loss totals.json counted beyond the ledger (the fees of
        failed transactions booked before the journal) is carried into the journal, so the total budget
        forgets nothing. Only a loss is carried, never a gain."""
        if journal_path().exists() or not self.totals.get("pnl_l"):
            return
        extra = int(self.totals["pnl_l"]) - realised(0)["total_l"]
        if extra < 0:
            journal({"t": int(self.totals.get("since_ms") or self.clock()), "pnl_l": extra, "sig": None,
                     "why": "carried over from totals.json"})
            print(f"live: {-extra / C.LAMPORTS:.6f} SOL of losses outside the ledger carried into the journal",
                  flush=True)

    def recompute(self) -> None:
        """The day's and the total's realised P&L from the ledger and the journal (never incremented, so a
        correction or a restart cannot count anything twice), and the two stops."""
        if self.day is None:
            self.day = self.clock() // P.DAY_MS
        r = realised(self.day)
        self.day_pnl_l, self.trades_today, self.wins_today = r["day_l"], r["trades_day"], r["wins_day"]
        t = self.totals
        t["pnl_l"], t["trades"] = r["total_l"], r["trades"]
        if t.get("since_ms") is None and r["first_ms"] is not None:
            t["since_ms"] = r["first_ms"]
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

    def booked(self, pnl_l: int, sig: str | None = None, **info) -> None:
        """A realised amount that no ledger row carries (the fee of a failed transaction): into the journal at
        once, then the day's and the total's P&L recomputed, and the two stops with them."""
        self._roll()
        journal({"t": int(self.clock()), "pnl_l": int(pnl_l), "sig": sig, "run": RUN_ID, **info})
        self.recompute()

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
        """A sale of a position. Never while its last failure's backoff runs (it waits in `deferred`), never
        once it was given up (stuck). It sells at most what the wallet was last seen to hold, and closes the
        token account only when it sells everything the wallet holds."""
        if o.pid in self.stuck:
            return
        if self.clock() < self.retry_at.get(o.pid, 0):
            self.deferred[o.pid] = ("sell", o)
            return
        p = self.pipe.pos.get(o.pid) or {}
        left = int(p.get("left") or 0) or o.tokens
        held = self.held.get(o.mint)
        tokens = o.tokens if not held else min(o.tokens, held)
        if tokens != o.tokens:
            o = dataclasses.replace(o, tokens=tokens)
        close = tokens >= (held if held else left)
        expect = int(p["mark_l"] * tokens / p["left"]) if p.get("mark_l") and p.get("left") else None
        self.pending[o.pid] = {"side": "sell", "order": o, "sig": None, "sent_ms": self.clock(), "expect_l": expect}
        self.q.put(("send", o, self._pool_of(o.mint), close, self.sell_fails.get(o.pid, 0) > 0))

    def sell_leftover(self, pid: int, info: dict, tokens: int) -> None:
        """Sell everything of a position from before a restart (its book is gone): no floor, close. After a
        failure it waits for the backoff like any sale."""
        lo = self.leftovers[pid] = {**info, "tokens": int(tokens), "tries": self.leftovers.get(pid, {}).get("tries", 0)}
        if pid in self.stuck:
            return
        if self.clock() < self.retry_at.get(pid, 0):
            self.deferred[pid] = ("leftover", pid, info, int(tokens))
            return
        held = self.held.get(info["mint"])
        amount = int(tokens) if not held else min(int(tokens), held)
        lo["tries"] += 1
        o = P.Order(pid, "sell", info["mint"], info.get("venue") or "pool", amount, 0, self.clock(), "leftover")
        self.pending[pid] = {"side": "sell", "order": o, "sig": None, "sent_ms": self.clock(), "leftover": True}
        self.q.put(("send", o, info.get("pool"), True, self.sell_fails.get(pid, 0) > 0))

    def new_orphan_pid(self) -> int:
        self.orphan_pid -= 1
        return self.orphan_pid

    def _pool_of(self, mint: str) -> str | None:
        if self.pipe is None:
            return None
        tok = self.pipe.eng.tokens.get(mint)
        return tok.pool if tok is not None else None

    def _known(self, mint: str) -> bool:
        """A token some position, order, waiting sale or leftover of this book holds or buys."""
        if self.pipe is not None and any(p["mint"] == mint for p in self.pipe.pos.values()):
            return True
        return any(pend["order"].mint == mint for pend in self.pending.values()) \
            or any(lo.get("mint") == mint for lo in self.leftovers.values())

    # ------------------------------------------------------------ the worker thread (network and signing only)
    def _chain_loop(self, every_s: float = CHAIN_EVERY_S) -> None:
        """Every minute: the closed trades against what the wallet really saw (chain_pnl). Its own
        thread, so reading transactions never delays a send."""
        while True:
            self.chain_once()
            time.sleep(every_s)

    def chain_once(self) -> None:
        try:
            adjust, changed = CP.reconcile(self.builder.rpc, self.signer.pubkey, data_dir())
        except Exception as e:                               # the next round tries again
            print(f"live: chain check failed ({type(e).__name__}: {e})"[:200], flush=True)
            return
        if changed:
            self._put(("chain", None, adjust))

    def _work(self, q: queue.Queue | None = None) -> None:
        q = self.q if q is None else q
        while True:
            item = q.get()
            if item is None:
                return
            self.step(item)

    def _job(self, item) -> None:
        """A read (status, landed, fee, holds): on the reads' own thread with send_first, so a stop's sale never
        waits behind one; else behind the sends in the one queue, as before."""
        (self.rq if self.speed.send_first else self.q).put(item)

    def _put(self, item) -> None:
        self.results.put(item)
        if self.on_result is not None:
            try:
                self.on_result()
            except Exception:                            # the next second's poll takes it
                pass

    def _confirmed(self, pid: int, sig: str, st: dict, wall_ms: int) -> None:
        """The websocket's notification (its own thread): queued like a status read's answer."""
        self._put(("status", pid, sig, st, wall_ms))

    def _prefetch_loop(self) -> None:
        while True:
            self.prefetch_once()
            time.sleep(PREFETCH_EVERY_S)

    def prefetch_once(self) -> None:
        """The background round: the blockhash and the fee (Builder.refresh), every wanted sale prepared, and
        Sender's /ping. Never raises; nothing here sends a transaction."""
        b = self.builder
        try:
            if hasattr(b, "refresh"):
                b.refresh()
            if self.speed.prepare and hasattr(b, "prepare") and self.signer is not None:
                want = dict(self.want_sales)
                for pid, (o, pool, close) in want.items():
                    if time.monotonic() - self.prep_failed.get(pid, -1e18) < 10.0:
                        continue
                    try:
                        b.prepare(self.signer.pubkey, o, pool, close)
                    except Exception as e:                # the sale is then built when it is sent, as before
                        b.prepared.pop(pid, None)
                        if pid not in self.prep_failed:
                            print(f"live: sale of {o.mint} not prepared ({type(e).__name__}: {e})"[:200], flush=True)
                        self.prep_failed[pid] = time.monotonic()
                b.forget(want)
            sender = getattr(b, "sender", None)
            if self.speed.keepalive and sender is not None and time.monotonic() - self.last_ping >= SENDER_PING_S:
                self.last_ping = time.monotonic()
                sender.ping()
        except Exception as e:
            print(f"live: prefetch {type(e).__name__}: {e}"[:200], flush=True)

    def step(self, item) -> None:
        """One queued job: build, sign and send an order; ask for a signature's status, read a landed
        transaction back, read the wallet's holding after a failed sale, or ask for a fee."""
        kind = item[0]
        try:
            if kind == "send":
                o, pool, close = item[1], item[2], item[3]
                if len(item) > 4 and item[4] and o.side == "sell" and o.venue == "curve":
                    o, pool = self._recheck_venue(o, pool)    # a retry: the curve may have completed meanwhile
                msg = self.builder.build(self.signer.pubkey, o, pool, close)
                tx = X.transaction(msg, [self.signer.sign(msg)])
                times = {"built_ms": int(self.clock()), "prepared": bool(getattr(self.builder, "last_prepared", False))}
                # The signature is the transaction's id, known before it is sent, and it is the one kept
                # whatever the endpoint answers. An exception while sending does not prove it never went out
                # (Sender may have forwarded it): it is "sent, outcome unknown", and its status settles it.
                local_sig = X.b58(tx[1:65])
                if self.watcher is not None:                 # subscribed before it can land
                    self.watcher.watch(local_sig, o.pid)
                try:
                    answer, err = (getattr(self.builder, "send", None) or self.builder.rpc.send)(tx), None
                except Exception as e:
                    answer, err = None, f"{type(e).__name__}: {e}"[:200]
                times["sent_at_ms"] = int(self.clock())
                self._put(("sent", o.pid, local_sig, answer, err, o, times))
            elif kind == "status":
                _, pid, sig = item
                try:
                    st = self.builder.rpc.statuses([sig])[0]
                except Exception as e:                       # e.g. a 429: no answer is not "not landed"
                    print(f"live: status of {sig[:12]}... not read ({type(e).__name__}: {e}); asked again later"[:220],
                          flush=True)
                    return
                self._put(("status", pid, sig, st))
            elif kind == "landed":
                _, pid, sig, mint = item[:4]
                self._put(("landed", pid, sig, self._read_landed(sig, mint, len(item) > 4 and bool(item[4]))))
            elif kind == "fee":
                _, pid, sig = item
                self._put(("fee", pid, sig, self.builder.rpc.fee_of(sig)))
            elif kind == "holds":
                _, pid, mint = item[:3]
                self._put(("holds", pid, *self._read_holds(mint, list(item[3]) if len(item) > 3 else [])))
        except Exception as e:                               # every failure goes back to the book
            if kind == "fee":
                return
            if kind == "holds":                              # not readable: the sale counts as failed
                self._put(("holds", item[1], None, None, None))
                return
            if kind == "landed":
                self._put(("landed", item[1], item[2], None))
                return
            # Building or signing failed: nothing was sent, a plain failure without a fee.
            self._put(("error", item[1].pid if kind == "send" else item[1], f"{type(e).__name__}: {e}"[:200]))

    def _tip(self) -> int:
        return int(getattr(self.builder, "sender_tip_l", 0) or 0)

    def _recheck_venue(self, o: P.Order, pool: str | None) -> tuple[P.Order, str | None]:
        """Before a curve sale is tried again: is the curve complete (a migration the stream missed)? Then the
        sale goes to the token's pool (the one the engine knows, else the canonical PumpSwap pool)."""
        fn = getattr(self.builder, "curve_complete", None)
        if fn is None:
            return o, pool
        try:
            done = fn(o.mint)
        except Exception as e:
            print(f"live: curve of {o.mint} not read ({type(e).__name__}: {e})"[:200], flush=True)
            return o, pool
        if not done:
            return o, pool
        pool = pool or X.canonical_pool(o.mint)
        print(f"live: the curve of {o.mint} is complete; the sale goes to its pool", flush=True)
        return dataclasses.replace(o, venue="pool"), pool

    def _read_landed(self, sig: str, mint: str, tx_only: bool = False) -> dict | None:
        """A landed transaction read back: the wallet's SOL and token change (chain_pnl.tx_effect), else a
        fresh read of the wallet's holding of the token; None when neither can be read now. `tx_only` (the
        first seconds after a fast confirmation): only the transaction itself, whose amounts are exact."""
        try:
            info = CP.tx_effect(self.builder.rpc.transaction(sig), self.signer.pubkey, mint)
            if info is not None:
                return info
        except Exception as e:
            print(f"live: {sig[:12]}... not read back ({type(e).__name__}: {e})"[:200], flush=True)
        if tx_only:
            return None
        try:
            return {"held": int(self.builder.rpc.holdings(self.signer.pubkey).get(mint, 0))}
        except Exception as e:
            print(f"live: holdings not read ({type(e).__name__}: {e})"[:200], flush=True)
        return None

    def _read_holds(self, mint: str, sigs: list[str]) -> tuple[int, list | None, int | None]:
        """After a failed sale: the wallet's holding of the token, which of the position's sales really
        landed (None when the statuses cannot be read), and what the last of those brought back."""
        amount = int(self.builder.rpc.holdings(self.signer.pubkey).get(mint, 0))
        ok, got = None, None
        if sigs:
            try:
                sts = self.builder.rpc.statuses(sigs)
                ok = [s for s, st in zip(sigs, sts) if landed(st) and st.get("err") is None]
            except Exception as e:
                print(f"live: statuses not read ({type(e).__name__}: {e})"[:200], flush=True)
            if ok:
                try:
                    e = CP.tx_effect(self.builder.rpc.transaction(ok[-1]), self.signer.pubkey, mint)
                    if e is not None and e.get("err") is None:
                        got = int(e["delta_l"]) + int(e["fee_l"]) + self._tip()
                except Exception:
                    got = None
        return amount, ok, got

    def drain(self) -> None:
        """Run what is queued on this thread (a test, or an executor made with start=False): the sends first."""
        while not self.q.empty() or not self.rq.empty():
            q = self.q if not self.q.empty() else self.rq
            item = q.get_nowait()
            if item is not None:
                self.step(item)

    def stop(self) -> None:
        self.q.put(None)
        self.rq.put(None)

    # ------------------------------------------------------------ results (the stream's thread)
    def poll(self, now: float) -> None:
        """The results of the worker, on the stream's thread. `now` is the stream's time (what the pipeline
        books with); the executor's own timers use wall time (self.clock)."""
        wall = self.clock()
        while True:
            try:
                r = self.results.get_nowait()
            except queue.Empty:
                break
            kind, pid = r[0], r[1]
            if kind == "chain":
                self.recompute()                             # the corrected ledger is the truth: nothing is added
                if self.on_chain is not None:
                    self.on_chain()
                continue
            if kind == "holds":
                self._holds(pid, r[2], now, *r[3:5])
                continue
            if kind == "fee":
                if r[3] is not None:
                    write_measure({"t": self.clock(), "what": "fee", "mode": self.mode, "sig": r[2], "fee_l": r[3]})
                continue
            pend = self.pending.get(pid)
            if pend is None:
                if kind == "sent" and len(r) > 5 and r[5] is not None:
                    self._sent_after_fill(pid, r[2], r[5])   # the stream's fill came before the send's result
                continue
            if kind == "sent":
                self._sent(pid, pend, r)
            elif kind == "error":
                self._failed(pid, pend, now, r[2], 0)
            elif kind == "status":
                if pend.get("sig") != r[2] or pend.get("landed_at"):
                    continue
                st = r[3]
                if st is None:
                    if wall - pend["sent_ms"] > GIVE_UP_MS:
                        self._failed(pid, pend, now, "not landed", 0)
                elif st.get("err") is not None:
                    self._failed(pid, pend, now, f"failed on chain: {st['err']}"[:200], self._fee(failed=True))
                elif landed(st):
                    pend["landed_at"] = wall                 # landed; its fill is read back unless the stream's comes
                    pend.setdefault("confirmed_ms", int(r[4]) if len(r) > 4 else wall)
            elif kind == "landed":
                if pend.get("sig") == r[2]:
                    self._landed(pid, pend, now, wall, r[3])
        sp = self.speed
        for pid, pend in list(self.pending.items()):
            if pend.get("landed_at"):
                if not pend.get("reading") and wall - pend["landed_at"] >= sp.grace_ms:
                    pend["reading"] = True
                    # fast: the first LANDED_GRACE_MS after the confirmation only the transaction itself is booked
                    tx_only = sp.grace_ms < LANDED_GRACE_MS and wall - pend.get("confirmed_ms", wall) < LANDED_GRACE_MS
                    self._job(("landed", pid, pend["sig"], pend["order"].mint) + ((True,) if tx_only else ()))
                continue
            if pend["sig"] and wall - pend["sent_ms"] > sp.status_ms and not pend.get("asked"):
                pend["asked"] = wall
                self._job(("status", pid, pend["sig"]))
            elif pend.get("asked") and wall - pend["asked"] > sp.status_ms:
                pend["asked"] = None
        for pid, d in list(self.deferred.items()):
            if wall < self.retry_at.get(pid, 0):
                continue
            self.deferred.pop(pid, None)
            if d[0] == "leftover":
                self.sell_leftover(*d[1:])
                continue
            p = self.pipe.pos.get(pid) if self.pipe is not None else None
            if p is None or p.get("left", 0) <= 0:
                continue                                     # closed meanwhile (a late fill)
            self.sell(dataclasses.replace(d[1], tokens=min(d[1].tokens, p["left"])))
        if (sp.prepare or sp.dynamic_fee) and self.pipe is not None:
            self._want()

    def _want(self) -> None:
        """For the prefetch thread: the sale each open position would send on a protective exit (everything it
        holds, no floor, the account closed), exactly as sell() would make it, and the accounts its fee reads."""
        want, accts = {}, []
        for pid, p in self.pipe.pos.items():
            if p.get("state") != "open" or int(p.get("left") or 0) <= 0 or pid in self.stuck or pid in self.pending:
                continue
            venue = "pool" if self.pipe._pool(p) else "curve"
            pool = self._pool_of(p["mint"])
            held = self.held.get(p["mint"])
            tokens = int(p["left"]) if not held else min(int(p["left"]), held)
            want[pid] = (P.Order(pid, "sell", p["mint"], venue, tokens, 0, 0, "prepared", p.get("legs", 0)), pool,
                         tokens >= (held if held else int(p["left"])))
            accts.append(pool if venue == "pool" and pool else X.pda([b"bonding-curve", X.key(p["mint"])], X.PUMP))
        self.want_sales = want
        if hasattr(self.builder, "fee_accounts"):
            self.builder.fee_accounts = accts

    def next_wake_ms(self) -> int | None:
        """The next wall time a timer of the executor is due (a sale's retry, a landed order's read), for the
        service's wake-up; None when nothing is waiting."""
        due = [self.retry_at.get(pid, 0) for pid in self.deferred]
        due += [int(pend["landed_at"]) + self.speed.grace_ms for pend in self.pending.values()
                if pend.get("landed_at") and not pend.get("reading")]
        return min(due) if due else None

    def _sent(self, pid: int, pend: dict, r: tuple) -> None:
        """The worker sent it (or tried): the transaction's own signature is the order's, always."""
        sig = r[2]
        answer = r[3] if len(r) > 3 else sig
        err = r[4] if len(r) > 4 else None
        if len(r) > 5 and r[5] is not None:
            pend["order"] = r[5]                             # the venue may have been switched to the pool
        times = r[6] if len(r) > 6 and isinstance(r[6], dict) else {}
        pend.update(built_ms=times.get("built_ms"), sent_at_ms=times.get("sent_at_ms"), prepared=times.get("prepared"))
        pend["sig"] = sig
        (self.sell_sigs if pend["side"] == "sell" else self.buy_sigs).setdefault(pid, []).append(sig)
        if answer is not None and answer != sig:
            print(f"live: the endpoint answered {str(answer)[:24]!r}, not the transaction's signature "
                  f"{sig[:12]}...; the signature is kept", flush=True)
        if err:
            print(f"live: sending {sig[:12]}... raised ({err}); outcome unknown, its status decides"[:220],
                  flush=True)
            log_order(pend, "sent", mode=self.mode, error=err, **times)
        else:
            log_order(pend, "sent", mode=self.mode, **times)

    def _sent_after_fill(self, pid: int, sig: str, o: P.Order) -> None:
        """A send's result that arrives after its fill was booked: the signature is still recorded (the
        position's lists, its buy for save_open and the ledger row, a sent line for the chain check)."""
        (self.buy_sigs if o.side == "buy" else self.sell_sigs).setdefault(pid, []).append(sig)
        if o.side == "buy" and self.pipe is not None and pid in self.pipe.pos and pid not in self.buy_sig:
            self.buy_sig[pid] = sig
        log_order({"order": o, "sig": sig}, "sent", mode=self.mode, note="its fill came first")

    def _fee(self, failed: bool = False) -> int:
        """The fee a transaction pays: priority and base fee, and Sender's tip, which a failed transaction
        does not pay (its transfer is reverted with the rest)."""
        return self.builder.priority_l + C.BASE_FEE_LAMPORTS + (0 if failed else self._tip())

    def _failed(self, pid: int, pend: dict, now: float, why: str, fee: int) -> None:
        self.pending.pop(pid, None)
        o = pend["order"]
        if self.watcher is not None:
            self.watcher.forget(pend.get("sig"))
        log_order(pend, "failed", why=why, mode=self.mode, fee_l=fee)
        write_measure({"t": self.clock(), "what": "failed", "mode": self.mode, "side": pend["side"],
                       "venue": o.venue, "why": why, "fee_l": fee})
        if fee:
            # Paid at once (a failed transaction that landed): into the day's and the total's figures now,
            # not with the position's close (a stuck sale may never close).
            self.booked(-int(fee), sig=pend.get("sig"), pid=pid, mint=o.mint, why=why[:80])
        if pend["side"] == "buy" and why == "not landed" and pend.get("sig"):
            self.given_up[o.mint] = {"order": o, "sig": pend["sig"], "run": RUN_ID}
        if pend["side"] == "sell" and self.verify_sales:
            # An earlier sale may have landed while the stream missed its fill (CCC, 2026-10-22: sold
            # on chain, then retried every second against an empty account). Read the holding first.
            self.verifying[pid] = (pend, why, fee)
            self._job(("holds", pid, o.mint, list(self.sell_sigs.get(pid) or [])))
            return
        self._settle_failure(pid, pend, now, why, fee)

    def _landed(self, pid: int, pend: dict, now: float, wall: int, info: dict | None) -> None:
        """A landed order whose stream fill never came: booked from the transaction itself (the wallet's SOL and
        token change), else from a fresh holdings read; a landed transaction with an error is a failure that
        paid its fee."""
        o = pend["order"]
        if info is None:                                             # not readable now: again after the grace
            pend["landed_at"] = wall + max(0, LANDED_RETRY_MS - self.speed.grace_ms)   # (at least LANDED_RETRY_MS)
            pend["reading"] = False
            return
        if info.get("err") is not None:
            fee = int(info.get("fee_l") or 0) or self._fee(failed=True)
            self._failed(pid, pend, now, f"failed on chain: {info['err']}"[:200], fee)
            return
        if "delta_l" in info:
            fee = int(info["fee_l"]) + self._tip()
            tok = int(info.get("tok") or 0)
            if pend["side"] == "buy":
                tokens, amount = tok, -int(info["delta_l"]) - fee
            else:
                tokens, amount = -tok, int(info["delta_l"]) + fee
        else:
            held, fee = int(info["held"]), self._fee()
            if pend["side"] == "buy":
                tokens, amount = held, int(o.stake_l or o.limit_l)
            else:
                p = (self.pipe.pos.get(pid) if self.pipe is not None else None) or {}
                left = int(p.get("left") or o.tokens)
                tokens = max(0, left - held)
                amount = int((pend.get("expect_l") or 0) * tokens / o.tokens) if o.tokens else 0
        if tokens <= 0:
            n = pend["reads"] = pend.get("reads", 0) + 1
            print(f"live: {o.mint} {pend['side']} landed but no token change is readable yet; again later", flush=True)
            pend["landed_at"], pend["reading"] = wall + LANDED_GRACE_MS * n, False
            return
        print(f"live: {o.mint} {pend['side']} landed ({str(pend.get('sig'))[:12]}...) though the stream missed its "
              "fill; booked from the chain", flush=True)
        self._book_fill(pid, pend, info.get("block_ms") or now, tokens, amount, fee, amount, None, onchain=True)

    def _holds(self, pid: int, amount: int | None, now: float, ok: list | None = None,
               got: int | None = None) -> None:
        """The wallet's holding of a token whose sale just failed, and which of the position's sales
        really landed (`ok`, None when unknown). Nothing left: the position is closed with the sale that
        landed (a leftover with none of its own is dropped). Less left than the position thinks, with a
        sale that landed: that part is booked and the rest sold after the backoff. Else the failure stands,
        and the next try sells what the wallet holds (and closes the account only then)."""
        v = self.verifying.pop(pid, None)
        if v is None:
            return
        pend, why, fee = v
        o = pend["order"]
        sigs = self.sell_sigs.get(pid) or []
        if amount is not None:
            self.held[o.mint] = int(amount)
        sold_sig = ok[-1] if ok else (sigs[-1] if ok is None and sigs else None)
        if pend.get("leftover"):
            if amount != 0:
                self._settle_failure(pid, pend, now, why, fee)
                return
            lo = self.leftovers.pop(pid, None) or {}
            self.held.pop(o.mint, None)
            self.sell_fails.pop(pid, None)
            self.retry_at.pop(pid, None)
            if sold_sig:
                # Its own sale landed unseen: into the ledger (the book's on_leftover writes the row, which
                # the totals are recomputed from), with the signature that landed; chain_pnl settles it.
                self.filled_sigs[sold_sig] = None
                self.recent_fills.append((o.mint, "sell", int(o.tokens), int(self.clock())))
                log_order({**pend, "sig": sold_sig}, "filled", sol=int(got or 0), tokens=o.tokens, mode=self.mode,
                          onchain=True)
                if self.on_leftover is not None:
                    self.on_leftover("sold", {**lo, "pid": pid, "got_l": int(got or 0), "sig": sold_sig})
            else:
                log_order(pend, "gone", mode=self.mode, why="sold before, seen on chain")
            print(f"live: leftover {o.mint} is already sold on chain; "
                  + (f"booked from {sold_sig[:12]}..." if sold_sig else "dropped"), flush=True)
            return
        p = (self.pipe.pos.get(pid) if self.pipe is not None else None) or {}
        left = int(p.get("left") or o.tokens)
        if amount is not None and (amount == 0 or (amount < left and sold_sig)):
            sold = left - int(amount)
            if got is not None:
                got_l = int(got)
            elif sold_sig:                                  # landed, not readable: the expected proceeds
                got_l = int((pend.get("expect_l") or 0) * sold / max(1, o.tokens))
            else:                                           # gone, and none of our sales landed: nothing came back
                got_l = 0
            if sold_sig:
                self.filled_sigs[sold_sig] = None
            self.recent_fills.append((o.mint, "sell", int(sold), int(self.clock())))
            log_order({**pend, "sig": sold_sig}, "filled", sol=got_l, tokens=sold, mode=self.mode, onchain=True)
            print(f"live: {sold} of {o.mint} were sold on chain ({str(sold_sig)[:12]}...) though the stream missed "
                  "it" + ("; closed" if amount == 0 else f"; {amount} left, sold after the backoff"), flush=True)
            if amount == 0:
                self.held.pop(o.mint, None)
                self.sell_fails.pop(pid, None)
                self.retry_at.pop(pid, None)
            else:
                self._note_fail(pid)                        # the rest goes after the backoff
            self.pipe.sold(pid, now, sold, got_l, 0)        # chain_pnl books what really came back
            if pid not in self.pipe.pos:
                self.exposure.pop(pid, None)
            return
        self._settle_failure(pid, pend, now, why, fee)

    def _note_fail(self, pid: int) -> int:
        n = self.sell_fails[pid] = self.sell_fails.get(pid, 0) + 1
        self.retry_at[pid] = int(self.clock()) + backoff_ms(n)
        return n

    def _settle_failure(self, pid: int, pend: dict, now: float, why: str, fee: int) -> None:
        """A failure that stands. Its fee is in the journal already (_failed). A buy is over; a sale is tried
        again after the backoff, and given up after SELL_MAX_FAILS failures in a row."""
        o = pend["order"]
        if pend["side"] == "buy":
            self.exposure.pop(pid, None)
            self.pipe.buy_failed(pid, now, why, fee)
            return
        n = self._note_fail(pid)
        if n >= SELL_MAX_FAILS:
            self._give_up(pid, pend, why, n)
            return
        print(f"live: the sale of {o.mint} failed ({why}); try {n + 1} in {backoff_ms(n) // 1000} s"[:220], flush=True)
        if pend.get("leftover"):
            lo = self.leftovers.get(pid) or {}
            self.sell_leftover(pid, lo, self.held.get(o.mint) or lo.get("tokens", o.tokens))
            return
        self.pipe.sell_failed(pid, now, why, 0)             # resent by the pipeline, held back by sell()

    def _give_up(self, pid: int, pend: dict, why: str, n: int) -> None:
        """No more tries: the position stays, marked stuck, and the owner hears of it once."""
        o = pend["order"]
        self.stuck[pid] = why
        self.deferred.pop(pid, None)
        print(f"live: the sale of {o.mint} failed {n} times in a row ({why}); given up, marked stuck"[:220],
              flush=True)
        if pend.get("leftover"):
            lo = self.leftovers.get(pid) or {}
            lo["stuck"] = why
            info = {**lo, "why": why}
        else:
            p = (self.pipe.pos.get(pid) if self.pipe is not None else None) or {}
            p["selling"] = True                             # nothing sends it again in this run
            info = {"mint": o.mint, "symbol": p.get("symbol"), "why": why, "fails": n}
        if self.on_leftover is not None:
            self.on_leftover("stuck", info)

    def _book_fill(self, pid: int, pend: dict, t: float, tokens: int, amount_l: int, fee: int, sol_l: int,
                   fee_bps: int | None, onchain: bool = False) -> None:
        """One fill (from the stream, or read back from the chain): the pipeline books it, it is measured,
        its fee asked for. `amount_l` is a buy's cost or a sale's proceeds, after the programs' fees."""
        self.pending.pop(pid, None)
        o = pend["order"]
        sig = pend.get("sig")
        if sig:
            self.filled_sigs[sig] = None
            while len(self.filled_sigs) > 512:
                self.filled_sigs.popitem(last=False)
        if onchain:                                          # a stream copy of it may still come (no signature)
            self.recent_fills.append((o.mint, pend["side"], int(tokens), int(self.clock())))
        self.held.pop(o.mint, None)
        if pend["side"] == "sell":
            self.sell_fails.pop(pid, None)
            self.retry_at.pop(pid, None)
            self.deferred.pop(pid, None)
        log_order(pend, "filled", sol=int(sol_l), tokens=int(tokens), mode=self.mode,
                  **({"onchain": True} if onchain else {}))
        m = {"t": self.clock(), "what": "fill", "mode": self.mode, "pid": pid, "side": pend["side"],
             "venue": o.venue, "mint": o.mint, "rule": self.rule, "sig": sig,
             "signal_ms": o.signal_ms, "land_ms": int(t), "lat_ms": int(t) - o.signal_ms,
             "send_to_land_ms": int(t) - int(pend["sent_ms"]), "sol_l": int(sol_l),
             "tokens": int(tokens), "fee_bps": fee_bps, "fee_assumed_l": fee, "slip": None, "onchain": onchain,
             # wall times of each step (measure.split): queued at buy()/sell(), built and signed, the send's
             # answer, the node's confirmation (websocket or status), booked here
             "queued_ms": int(pend["sent_ms"]), "built_ms": pend.get("built_ms"), "sent_at_ms": pend.get("sent_at_ms"),
             "confirmed_ms": pend.get("confirmed_ms"), "seen_ms": int(self.clock()), "prepared": pend.get("prepared")}
        if self.watcher is not None:
            self.watcher.forget(sig)
        if pend.get("leftover"):
            lo = self.leftovers.pop(pid, {})
            write_measure(m)
            if sig:
                self._job(("fee", pid, sig))
            if self.on_leftover is not None:                 # the book writes its ledger row
                self.on_leftover("sold", {**lo, "pid": pid, "got_l": int(amount_l), "sig": sig})
            return
        if pend["side"] == "buy":
            if sig:
                self.buy_sig[pid] = sig
            p = self.pipe.pos.get(pid) or {}
            if p.get("signal_price") and tokens:
                m["slip"] = ((amount_l / C.LAMPORTS) / (tokens / C.TOKEN_UNIT)) / p["signal_price"] - 1
            self.meas[pid] = m
            self.pipe.lat[pid] = m["lat_ms"]                  # the closed trade's lat_buy_ms, as on paper
            self.exposure[pid] = int(amount_l) + fee
            self.pipe.bought(pid, t, int(tokens), int(amount_l), fee)
        else:
            if pend.get("expect_l"):
                m["slip"] = amount_l / pend["expect_l"] - 1
            self.meas[pid] = m
            self.pipe.sold(pid, t, int(tokens), int(amount_l), fee)
            if pid not in self.pipe.pos:
                self.exposure.pop(pid, None)
        write_measure(m)
        if sig:
            self._job(("fee", pid, sig))

    def _seen(self, mint: str, side: str, tokens: int) -> bool:
        """A fill of this token, side and amount booked in the last ten minutes (a stream fill without a
        signature that arrives after the chain's read-back already booked it)."""
        now = int(self.clock())
        return any(m == mint and s == side and k == tokens and now - t < 600_000 for m, s, k, t in self.recent_fills)

    def _match(self, mint: str, side: str, sig: str | None) -> int | None:
        """The pending order a fill belongs to: by its signature (the order's, or an earlier try of the same
        position's), else by token and side when the fill has no signature or the order's send result is
        not back yet."""
        cands = [pid for pid, pend in self.pending.items() if pend["order"].mint == mint and pend["side"] == side]
        if sig:
            sent = self.buy_sigs if side == "buy" else self.sell_sigs
            for pid in cands:
                if sig == self.pending[pid].get("sig") or sig in sent.get(pid, ()):
                    return pid
            cands = [pid for pid in cands if not self.pending[pid].get("sig")]
        return cands[0] if cands else None

    def on_trade(self, table: str, row: dict) -> None:
        """Our own wallet's trade on the stream is the fill; its timing and price are measured."""
        if self.signer is None or row.get("user") != self.signer.pubkey:
            return
        side = "buy" if row["buy"] else "sell"
        sig = row.get("sig") or None
        tokens = int(row["tok"])
        if (sig and sig in self.filled_sigs) or (not sig and self._seen(row["mint"], side, tokens)):
            return                                           # booked already (read back from the chain first)
        fee_bps = int(row.get("fee_bps") or C.DEFAULT_FEE_BPS)
        amount = int(row["sol"] * (1 + fee_bps / 10_000)) if side == "buy" else int(row["sol"] * (1 - fee_bps / 10_000))
        pid = self._match(row["mint"], side, sig)
        if pid is not None:
            pend = self.pending[pid]
            if sig and pend.get("sig") != sig:
                pend = {**pend, "sig": sig}                  # an earlier try of the same order is the one that landed
            self._book_fill(pid, pend, row["t"], tokens, amount, self._fee(), row["sol"], fee_bps)
            return
        self._unmatched(table, row, side, sig, tokens, amount, fee_bps)

    def _unmatched(self, table: str, row: dict, side: str, sig: str | None, tokens: int, amount: int,
                   fee_bps: int) -> None:
        """An own fill no pending order claims. A buy (one given up as not landed, or never known) is adopted at
        once and sold like a leftover; a sale goes to the open position or leftover of that token whose
        retry is waiting; anything else is left to the chain check."""
        mint = row["mint"]
        if side == "buy":
            if self._known(mint):
                print(f"live: an own buy of {mint} matches no order; the token is held by a known position, the "
                      "orphan check looks at it", flush=True)
                return
            g = self.given_up.pop(mint, None)
            buy_sig = sig or (g or {}).get("sig")
            old = (g or {}).get("order") or P.Order(0, "buy", mint, "pool" if table == "amm" else "curve", tokens,
                                                    amount, int(row["t"]))
            if buy_sig:
                self.filled_sigs[buy_sig] = None
                log_order({"order": old, "sig": buy_sig, "run": (g or {}).get("run") or "unmatched"}, "filled",
                          sol=int(row["sol"]), tokens=tokens, mode=self.mode, note="a fill no pending order claimed")
            info = {"mint": mint, "venue": "pool" if table == "amm" else "curve", "pool": self._pool_of(mint),
                    "rule": self.rule, "cost_l": amount + self._fee(), "signal_ms": int(row["t"]), "buy_sig": buy_sig}
            tok = self.pipe.eng.tokens.get(mint) if self.pipe is not None else None
            info["symbol"] = getattr(tok, "symbol", None)
            pid = self.new_orphan_pid()
            print(f"live: an own buy of {mint} matches no order (given up as not landed?); adopted and sold now",
                  flush=True)
            self.sell_leftover(pid, info, tokens)
            return
        for pid, p in (list(self.pipe.pos.items()) if self.pipe is not None else []):
            if p["mint"] == mint and p.get("state") == "open" and pid not in self.pending:
                print(f"live: an own sale of {mint} matches no order (a try thought failed landed); booked", flush=True)
                self.stuck.pop(pid, None)
                pend = {"side": "sell", "order": P.Order(pid, "sell", mint, p.get("venue") or "curve", tokens, 0,
                                                         int(row["t"]), "unmatched"), "sig": sig,
                        "sent_ms": int(row["t"]), "expect_l": None}
                self._book_fill(pid, pend, row["t"], tokens, amount, self._fee(), row["sol"], fee_bps)
                return
        for pid, lo in list(self.leftovers.items()):
            if lo.get("mint") == mint and pid not in self.pending:
                self.stuck.pop(pid, None)
                pend = {"side": "sell", "order": P.Order(pid, "sell", mint, lo.get("venue") or "pool", tokens, 0,
                                                         int(row["t"]), "leftover"), "sig": sig,
                        "sent_ms": int(row["t"]), "leftover": True}
                self._book_fill(pid, pend, row["t"], tokens, amount, self._fee(), row["sol"], fee_bps)
                return
        print(f"live: an own sale of {mint} matches nothing open; left to the chain check", flush=True)


# ---------------------------------------------------------------- files, alerts, status

def log_order(pend: dict, what: str, **kw) -> None:
    o = pend["order"]
    rec = {"t": int(time.time() * 1000), "what": what, "run": pend.get("run") or RUN_ID, "pid": o.pid, "side": o.side,
           "mint": o.mint, "venue": o.venue, "tokens": o.tokens, "limit_l": o.limit_l, "why": o.why,
           "sig": pend.get("sig"), **kw}
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
               "slip", "pid", "run", "buy_sig"]
LEDGER_TEXT = ("mode", "rule", "mint", "name", "symbol", "exit_why", "run", "buy_sig")


def write_close(rec: dict) -> None:
    """One closed trade into ledger.csv. The row carries the run id and position id (and a leftover's buy
    signature), which the chain check matches its transactions by. A ledger written before those columns
    existed is rewritten once with the full header."""
    d = data_dir()
    d.mkdir(parents=True, exist_ok=True)
    p = d / "ledger.csv"
    with CP.LEDGER_LOCK:
        new = not p.exists()
        cols = LEDGER_COLS
        if not new:
            with p.open(newline="", encoding="utf-8") as fh:
                reader = csv.DictReader(fh)
                old = list(reader.fieldnames or [])
                rows = list(reader) if any(c not in old for c in LEDGER_COLS) else None
            if rows is not None:
                cols = LEDGER_COLS + [c for c in old if c not in LEDGER_COLS]
                tmp = p.with_suffix(".tmp")
                with tmp.open("w", newline="", encoding="utf-8") as fh:
                    w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
                    w.writeheader()
                    w.writerows(rows)
                tmp.replace(p)
            else:
                cols = old
        with p.open("a", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
            if new:
                w.writeheader()
            w.writerow({**rec, "run": rec.get("run") or RUN_ID})


def last_buy_order(mint: str) -> dict | None:
    """The newest buy order line for a mint in orders.jsonl (sent, filled or failed)."""
    try:
        lines = (data_dir() / "orders.jsonl").read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        try:
            o = json.loads(line)
        except ValueError:
            continue
        if o.get("mint") == mint and o.get("side") == "buy":
            return o
    return None


def day_pnl_from_ledger(day: int) -> int:
    """The realised P&L (lamports) of UTC day `day` (days since 1970): the trades that closed that day and
    the journal's amounts of that day (realised)."""
    return realised(day)["day_l"]


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
            if k is None:
                continue
            if k in LEDGER_TEXT:
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
            "exposure_sol": 0.0, "skipped": {}, "stake": None}


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
        self.fail_posted: dict[tuple, float] = {}
        self.orphan_seen: dict[str, int] = {}          # mint -> the holdings read that first showed it unknown
        self.last_limits = -1e18
        executor.on_stop = self.on_stop
        executor.on_leftover = self.on_leftover
        executor.on_chain = self.on_chain
        executor.on_gate = self.on_gate

    # ------------------------------------------------------------ the pipeline's hooks
    def on_chain(self) -> None:
        """The ledger now holds what the wallet really saw: the app's list follows it."""
        self.recent = read_ledger(100)

    def on_close(self, rec: dict) -> None:
        rec = {**rec, "mode": self.exec.mode, "run": RUN_ID, "buy_sig": self.exec.buy_sig.pop(rec.get("pid"), None)}
        write_close(rec)
        self.exec.recompute()                              # the day's and the total's P&L from the ledger
        self.refresh_limits()                              # and the stake with them
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
            key = (kind, p.get("pid"))
            now = time.monotonic()
            if now - self.fail_posted.get(key, -1e18) < FAIL_CARD_EVERY_S:
                return                                     # one card a minute per position, not one a try
            self.fail_posted[key] = now
        meas = dict(self.exec.meas.get(p.get("pid")) or {}) if kind in ("bought", "sold") else None
        day = self.exec.day_pnl_l / C.LAMPORTS
        self._post(lambda lang: [_trade_card(kind, dict(p), dict(kw), lang, day, self.exec.mode, meas)])

    def on_stop(self, kind: str, lost_sol: float) -> None:
        lim = self.exec.limits.max_daily_loss_sol if kind == "daily" else (self.exec.max_total_l or 0) / C.LAMPORTS
        self._post(lambda lang: [_stop_card(kind, lost_sol, lim, self.exec.mode, lang)])

    def on_leftover(self, what: str, info: dict) -> None:
        if what == "sold":
            # A position from before a restart or a buy that landed unseen: in the ledger like any
            # trade, so the list shows it and chain_pnl settles it from the wallet.
            cost, got, fee = int(info.get("cost_l") or 0), int(info.get("got_l") or 0), self.exec._fee()
            now = int(time.time() * 1000)
            rec = {"mode": self.exec.mode, "rule": info.get("rule") or self.rule, "mint": info.get("mint"),
                   "name": info.get("name"), "symbol": info.get("symbol"),
                   "signal_ms": info.get("signal_ms") or now, "land_ms": info.get("signal_ms") or now,
                   "exit_ms": now, "exit_why": "leftover", "legs": 1, "stake_sol": cost / C.LAMPORTS,
                   "proceeds_sol": got / C.LAMPORTS, "pnl_sol": (got - cost - fee) / C.LAMPORTS,
                   "ret": (got - cost - fee) / cost if cost else None, "pid": info.get("pid"), "run": RUN_ID,
                   "buy_sig": info.get("buy_sig")}
            write_close(rec)
            self.exec.recompute()                          # booked: the totals follow the ledger
            self.refresh_limits()                          # and the stake with them
            self.recent.insert(0, {k: rec.get(k) for k in LEDGER_COLS})
            del self.recent[100:]
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
        if time.monotonic() - self.last_limits >= RECHECK_S or self.exec.balance_l != self.exec.stake_bal_l:
            self.last_limits = time.monotonic()            # every minute, and with every new balance read
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
        ack = getattr(self.exec.gate, "ack", None)
        if ack is None or ack.mode is None:
            return
        lim, total = effective(ack, read_settings(), self.exec.gate.env)
        self.exec.set_limits(self.exec.sized(lim), total)

    def daily_card(self, day: int, stats: dict) -> None:
        from . import measure
        try:
            ex = measure.write_report()
        except Exception as e:                               # the card goes out without it
            print(f"live: execution report not written ({type(e).__name__}: {e})", flush=True)
            ex = None
        bal = self.exec.balance_l
        total = self.exec.totals["pnl_l"] / C.LAMPORTS
        rows = list(self.recent)
        self._post(lambda lang: [_daily_card(day, stats, bal, total, ex, self.exec.mode, self.rule, lang, rows)])

    # ------------------------------------------------------------ files
    def positions(self) -> list[dict]:
        out = []
        for p in (self.pipe.pos.values() if self.pipe is not None else []):
            cost = p.get("cost_l") or 0
            mark = p.get("mark_l")
            out.append({"pid": p["pid"], "mint": p["mint"], "symbol": p.get("symbol"), "name": p.get("name"),
                        "venue": p.get("venue"), "state": "stuck" if p["pid"] in self.exec.stuck else p.get("state"),
                        "tokens": p.get("left"),
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
        paused = ((ex.stake or {}).get("why") or "stake paused") if ex.limits.stake_sol <= 0 else None
        st.update(on=ex.closed_why is None and not st["kill"] and ex.stop_day != ex.day and not paused
                  and not (ex.max_total_l is not None and -ex.totals["pnl_l"] >= ex.max_total_l),
                  mode=ex.mode, rule=self.rule, positions=self.positions(),
                  leftovers=[{"pid": k, **v} for k, v in ex.leftovers.items()],
                  pnl_today_sol=ex.day_pnl_l / C.LAMPORTS, trades_today=ex.trades_today,
                  wins_today=ex.wins_today,
                  pnl_total_sol=ex.totals["pnl_l"] / C.LAMPORTS, trades_total=ex.totals["trades"],
                  since_ms=ex.totals.get("since_ms"), limits=limits_view(ex.limits, None if ex.max_total_l is None
                                                                         else ex.max_total_l / C.LAMPORTS),
                  stops={"daily": ex.stop_day == ex.day,
                         "total": ex.max_total_l is not None and -ex.totals["pnl_l"] >= ex.max_total_l},
                  exposure_sol=sum(ex.exposure.values()) / C.LAMPORTS,
                  stake=ex.stake, refusing=ex.closed_why or paused,
                  gate=[ex.closed_why] if ex.closed_why else [paused] if paused else list(why))
        if self.pipe is not None:
            sk = {k[1]: v for k, v in self.pipe.eng.skipped.items() if k[0] == self.rule}
            st["skipped"] = dict(sorted(sk.items(), key=lambda kv: -kv[1])[:8])
        return st

    def save_open(self) -> None:
        """Positions and buys in flight, so a restart can sell what is left (adopt_leftovers)."""
        rows = []
        ex = self.exec
        for p in (self.pipe.pos.values() if self.pipe is not None else []):
            pid = p["pid"]
            pend = ex.pending.get(pid) or {}
            pending = p.get("state") == "pending"
            # The real cost: what the fill took (with its fee), for the part still held. A buy still in flight
            # has no fill yet: the stake it spends (not the 30 % higher limit); its signature lets the chain
            # check settle what it really took.
            if p.get("tokens"):
                cost = int((p.get("cost_l") or 0) + (p.get("fees_l") or 0)) * p["left"] // p["tokens"]
            else:
                cost = int(p.get("stake_l") or p.get("limit_l") or 0)
            buy_sig = ex.buy_sig.get(pid) or (pend.get("sig") if pending else None) \
                or ((ex.buy_sigs.get(pid) or [None])[-1])
            rows.append({"mint": p["mint"], "venue": p.get("venue"), "pool": ex._pool_of(p["mint"]),
                         "symbol": p.get("symbol"), "name": p.get("name"), "rule": p.get("rule"),
                         "signal_ms": p.get("signal_ms"), "buy_sig": buy_sig, "cost_l": cost, "pending": pending,
                         "stuck": ex.stuck.get(pid)})
        rows += [dict(v, tries=0) for v in ex.leftovers.values()]
        write_json(data_dir() / "open.json", rows)

    def adopt_orphans(self, holdings: dict[str, int] | None, now_ms: int | None = None,
                      read_ms: int | None = None) -> int:
        """Tokens in the wallet that no position, order or leftover knows, seen in two holdings reads at
        least ORPHAN_AFTER_MS apart: a buy the executor gave up on as not landed that landed late (Bundle,
        2026-10-22). Its buy is logged as filled (so chain_pnl can settle it) and it is sold like a
        leftover. Runs on the stream's thread with the service's last holdings read, and only when that
        read (taken at `read_ms`) is at most HOLDINGS_FRESH_MS old: a stale snapshot may still show a
        token that was sold since."""
        now_ms = now_ms if now_ms is not None else int(time.time() * 1000)
        read_ms = now_ms if read_ms is None else int(read_ms)
        if now_ms - read_ms > HOLDINGS_FRESH_MS:
            return 0                                       # an old snapshot: decide nothing on it
        if not holdings:
            self.orphan_seen.clear()
            return 0
        ex = self.exec
        known = {p["mint"] for p in (ex.pipe.pos.values() if ex.pipe is not None else [])}
        known |= {pend["order"].mint for pend in ex.pending.values()}
        known |= {lo.get("mint") for lo in ex.leftovers.values()}
        for m in list(self.orphan_seen):
            if m not in holdings or m in known:
                self.orphan_seen.pop(m)
        deltas = {}
        try:
            deltas = (json.loads((data_dir() / "chain.json").read_text(encoding="utf-8")) or {}).get("deltas") or {}
        except (OSError, ValueError, AttributeError):
            pass
        n = 0
        for mint, amt in holdings.items():
            if amt <= 0 or mint in known:
                continue
            first = self.orphan_seen.setdefault(mint, read_ms)
            if read_ms - first < ORPHAN_AFTER_MS:
                continue
            buy = last_buy_order(mint)
            # The real cost where the chain check has read the buy already, else its cost limit.
            cost = int((buy or {}).get("limit_l") or 0)
            if buy and buy.get("sig") in deltas and int(deltas[buy["sig"]]) < 0:
                cost = -int(deltas[buy["sig"]])
            if buy and buy.get("sig") and buy.get("what") != "filled":
                log_order({"order": P.Order(int(buy.get("pid") or 0), "buy", mint, buy.get("venue") or "curve",
                                            int(buy.get("tokens") or amt), int(buy.get("limit_l") or 0), now_ms),
                           "sig": buy["sig"], "run": buy.get("run") or "old"}, "filled", sol=cost, tokens=amt,
                          mode=ex.mode, onchain=True, note="landed after the executor gave up on it")
            tok = ex.pipe.eng.tokens.get(mint) if ex.pipe is not None else None
            pool = tok.pool if tok is not None else None
            info = {"mint": mint, "venue": "pool" if pool else "curve", "pool": pool, "rule": self.rule,
                    "symbol": getattr(tok, "symbol", None), "cost_l": cost,
                    "signal_ms": int((buy or {}).get("t") or now_ms), "buy_sig": (buy or {}).get("sig")}
            ex.sell_leftover(ex.new_orphan_pid(), info, amt)
            self.orphan_seen.pop(mint, None)
            print(f"live: {mint} is in the wallet but in no position (a late buy); selling it", flush=True)
            n += 1
        return n

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

CHART_WAIT_S = 12.0          # a closed trade's chart waits this long, so the feed holds the time after the exit


def post_cards(make) -> None:
    """The cards to Telegram (urgent: also in quiet hours); a real-money trade card (marked by
    _trade_card) also to Discord's trades webhook, with its chart. Never raises."""
    try:
        from ..ops import notify
        cards = make(notify.alert_lang())
        trade = any(getattr(c, "discord", False) for c in cards)
        notify.send("trades", cards, urgent=True, discord="trades" if trade else None)
    except Exception as e:                                   # an alert never stops the book
        print(f"live: alert not sent ({type(e).__name__}: {e})", flush=True)


def _eur() -> float | None:
    """SOL in euro for the cards (notify.sol_eur: the engine's rate or Kraken's public ticker); None if unknown."""
    try:
        from ..ops import notify
        return notify.sol_eur()
    except Exception:                                        # the card shows SOL only
        return None


def _trade_card(kind, p, kw, lang, day_pnl_sol, mode, meas, chart_wait_s: float = CHART_WAIT_S):
    from .card import live_trade_card, trade_chart
    c = live_trade_card(kind, p, kw, lang, day_pnl_sol, mode=mode, measured=meas,
                        eur=_eur() if kind in ("bought", "sold", "closed") else None)
    if kind in ("bought", "sold", "closed"):
        c.discord = True                                     # a real-money trade: Discord gets it too
    if kind == "closed":
        try:
            c.image = trade_chart(kw.get("rec") or {}, lang, wait_s=chart_wait_s)
        except Exception as e:                               # the card goes without its picture
            print(f"live: trade chart not drawn ({type(e).__name__}: {e})", flush=True)
    return c


def _stop_card(kind, lost_sol, limit_sol, mode, lang):
    from .card import live_stop_card
    return live_stop_card(kind, lost_sol, limit_sol, mode, lang)


def _leftover_card(what, info, mode, lang):
    from .card import live_leftover_card
    c = live_leftover_card(what, info, mode, lang)
    if what == "sold":
        c.discord = True
    return c


def _gate_card(why, mode, lang):
    from .card import live_gate_card
    return live_gate_card(why, mode, lang)


def _daily_card(day, stats, balance_l, total_sol, ex, mode, rule, lang, ledger=None):
    from .card import day_chart, live_daily_card
    c = live_daily_card(day, stats, balance_l, total_sol, ex, mode, rule, lang, eur=_eur())
    try:
        c.image = day_chart(day, ledger or [], lang)
    except Exception as e:                                   # the card goes without its picture
        print(f"live: day chart not drawn ({type(e).__name__}: {e})", flush=True)
    return c


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
    speed = speed_of(env)
    rpc = rpc or Rpc(env.get(ENV_RPC) or DEFAULT_RPC, keepalive=speed.keepalive)
    lim, total = effective(gate.ack, read_settings(), env)
    builder = Builder(rpc, gate.idls)
    builder.speed = speed
    sender_url = (env.get(ENV_SENDER) or "").strip()
    if sender_url and not sender_problems(sender_url):
        builder.sender = Rpc(sender_url, keepalive=speed.keepalive)
        builder.sender_tip_l = sender_tip_lamports(env)
        print(f"live: sending through Helius Sender (stake-weighted, tip {builder.sender_tip_l} lamports), "
              "the plain RPC if it does not answer", flush=True)
    if speed.on():
        print(f"live: speed settings on: {', '.join(speed.on())}; status asked after {speed.status_ms} ms, "
              f"landed orders read back after {speed.grace_ms} ms"
              + (f", fee at most {speed.fee_cap_sol} SOL" if speed.dynamic_fee else "")
              + ("" if speed.ws_url or not speed.ws_confirm else "; no wss:// endpoint for the signature websocket"),
              flush=True)
    ex = LiveExecutor(gate, signer, builder, lim, mode=gate.ack.mode, max_total_sol=total,
                      rule=gate.rule, start=start, speed=speed)
    try:
        ex.balance_l = rpc.balance(signer.pubkey)
    except Exception as e:                                   # no buys until the service reads it
        print(f"live: balance not read ({type(e).__name__}: {e})", flush=True)
    lim = ex.sized(lim)
    ex.set_limits(lim, total)
    # The paper strategy stakes 0.1 SOL; live, the stake is the sized one in the Risk limits (at most the cap).
    s = dataclasses.replace(P.BY_NAME[gate.rule], stake_sol=P.HARD_STAKE_SOL)
    book = LiveBook(None, ex, gate.rule, alerts=alerts)
    pipe = P.Pipeline(engine, [s], ex, limits=lim, name="live", record=False, on_close=book.on_close,
                      on_event=book.on_event, kill=P.KillSwitch(live_kill_paths()))
    book.pipe = pipe
    engine.add_pipe(pipe)
    print(f"live: ON ({gate.ack.mode}) for {gate.rule}, wallet {signer.pubkey[:4]}..., stake {lim.stake_sol} SOL "
          f"({ex.stake['why']}), "
          f"at most {lim.max_open} open, {lim.max_exposure_sol} SOL exposure, daily loss stop "
          f"{lim.max_daily_loss_sol} SOL" + (f", total budget {total} SOL" if total is not None else ""), flush=True)
    return book


# ---------------------------------------------------------------- the simulation (nothing is signed or sent)

def newest_pools(path: Path | None = None, n: int = 10) -> list[tuple[str, str]]:
    """(pool, mint) of the newest migrations the collector has seen (its pools.json), newest first."""
    from . import store
    d = read_json(path or (store.base() / "pools.json"))
    if not isinstance(d, dict) or not d:
        return []
    seen = [(k, v) for k, v in d.items() if isinstance(v, list) and len(v) > 1]
    seen.sort(key=lambda kv: -int(kv[1][1]))
    return [(k, v[0]) for k, v in seen[:n]]


def newest_create(root: Path | None = None, now_ms: int | None = None, max_age_ms: int = 600_000) -> str | None:
    """The mint of the newest token the collector saw created in the last ten minutes, cashback coins
    left out (the v3 trades refuse them): a curve that is almost surely still open, for the dry run."""
    import datetime as dt
    from . import store
    now_ms = now_ms or int(time.time() * 1000)
    days = [(dt.datetime.fromtimestamp(now_ms / 1000, dt.timezone.utc) - dt.timedelta(days=k)).strftime("%Y-%m-%d")
            for k in (1, 0)]
    df = store.read("creates", days, root)
    if df.is_empty():
        return None
    if "cashback" in df.columns:
        df = df.filter(~df["cashback"].fill_null(False))
    if "quote" in df.columns:                                 # only coins quoted in SOL are traded (no USDC pairs)
        df = df.filter(df["quote"].is_null() | (df["quote"] == X.WSOL))
    df = df.filter(df["t"] >= now_ms - max_age_ms).sort("t")
    return str(df["mint"][-1]) if len(df) else None


def venue_of(rule: str) -> str:
    return "pool" if P.BY_NAME[rule].family == "E" else "curve"


def simulate(gate: LiveGate, rpc: Rpc, pubkey: str, mint: str | None = None, pool: str | None = None,
             sol: float = 0.01, now_ms: int | None = None, pools_file: Path | None = None,
             venue: str | None = None) -> dict:
    """A buy, and a buy followed by the sale of what it bought, built by txbuild for this wallet and run
    through simulateTransaction on mainnet (no signature, nothing sent). The venue is the strategy's
    unless `venue` names the other one (the gate accepts only a simulation of the strategy's own venue).
    The record is what the test gate reads; it holds no secret."""
    gate.check()
    rule = gate.rule if gate.rule in P.BY_NAME else DEFAULT_TEST_RULE
    venue = venue or venue_of(rule)
    b = Builder(rpc, gate.idls)
    lam = int(min(sol, TEST_MAX_TRADE_SOL, P.HARD_STAKE_SOL) * C.LAMPORTS)
    limit = int(lam * (1 + C.SLIP_TOL))
    rec = {"t": now_ms or int(time.time() * 1000), "ok": False, "pubkey": pubkey, "rule": rule, "venue": venue,
           "mint": mint, "pool": pool, "sol": lam / C.LAMPORTS, "buy": None, "round_trip": None, "error": None}
    try:
        if venue == "pool":
            if pool:
                if not mint:
                    raise RuntimeError("--pool needs --mint")
                rec.update(pool=pool, mint=mint)
                info = b.pool(pool, mint, fresh=True)
                if not info.supports_v2():
                    raise RuntimeError("the pool takes no v2 trade (a cashback coin); pass another --pool")
                if info.quote_mint != X.WSOL:
                    raise RuntimeError("the pool is not quoted in SOL; pass another --pool")
            else:
                # pools.json does not say a pool's quote: the newest pool quoted in SOL that takes a v2 trade
                # (a USDC pair or a cashback coin is refused by the executor, so it proves nothing here)
                info = None
                for pool_c, mint_c in newest_pools(pools_file):
                    try:
                        cand = b.pool(pool_c, mint_c, fresh=True)
                    except (RuntimeError, ValueError):
                        continue
                    if cand.quote_mint == X.WSOL and cand.supports_v2():
                        info, pool, mint = cand, pool_c, mint_c
                        break
                if info is None:
                    raise RuntimeError("no recent pool quoted in SOL that takes a v2 trade (run the collector, "
                                       "or pass --pool and --mint)")
                rec.update(pool=pool, mint=mint)
            pb, pq = rpc.token_balance(info.pool_base), rpc.token_balance(info.pool_quote)
            eff = info.effective_quote(pq)
            rec["reserves"] = {"base": pb, "quote_vault": pq, "virtual_quote": info.virtual_quote, "effective": eff}
            quote = C.pool_buy(lam, pb, eff, C.DEFAULT_FEE_BPS)
            spend, least = pool_buy_amounts(P.Order(0, "buy", mint, "pool", quote, limit, 0, stake_l=lam))
            buy = X.amm_buy(pubkey, info, spend, least, b.priority_l, b.idl_amm)
            # the round trip sells the least the buy may give, so the sale never asks for more than it got
            # (the token account keeps the rest and stays open); the emptied account is closed live
            sell = X.amm_sell(pubkey, info, least, 0, b.priority_l, False, b.idl_amm)
        else:
            if not mint:
                mint = newest_create(now_ms=now_ms)
                if not mint:
                    raise RuntimeError("no token created in the last ten minutes (run the collector, or pass --mint)")
                rec.update(mint=mint)
            data, _ = rpc.account(X.pda([b"bonding-curve", X.key(mint)], X.PUMP))
            vt, vs = int.from_bytes(data[8:16], "little"), int.from_bytes(data[16:24], "little")
            rt, done = int.from_bytes(data[24:32], "little"), bool(data[48])
            if done:
                raise RuntimeError("the curve is complete (pass a live token's --mint)")
            rec["reserves"] = {"virtual_token": vt, "virtual_sol": vs, "real_token": rt}
            tokens = C.curve_buy(lam, vs, vt, rt, C.DEFAULT_FEE_BPS)
            info = b.curve(mint)
            if not info.supports_v3():
                raise RuntimeError("the curve takes no v3 trade (a cashback coin); pass another --mint")
            buy = X.pump_buy(pubkey, info, tokens, limit, b.priority_l, b.idl_pump)
            sell = X.pump_sell(pubkey, info, tokens, 0, b.priority_l, True, b.idl_pump)
        sender = (gate.env.get(ENV_SENDER) or "").strip() if getattr(gate, "env", None) else ""
        if sender and not sender_problems(sender):
            # The live transactions then carry Sender's tip: the dry run carries it too.
            t = sender_tip_lamports(gate.env)
            buy = buy + [X.tip(pubkey, sorted(X.HELIUS_TIP_ACCOUNTS)[0], t)]
            sell = sell + [X.tip(pubkey, sorted(X.HELIUS_TIP_ACCOUNTS)[0], t)]
            rec["sender_tip_l"] = t
        X.check_own(pubkey, buy, sender_tip_ok=bool(sender))
        X.check_own(pubkey, sell, sender_tip_ok=bool(sender))
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
    sim.add_argument("--venue", choices=("pool", "curve"),
                     help="default: the strategy's; the other venue is simulated for a look, the gate ignores it")
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
    rec = simulate(gate, rpc, pubkey, a.mint, a.pool, a.sol, venue=a.venue)
    print(json.dumps({k: rec.get(k) for k in ("ok", "rule", "venue", "mint", "pool", "sol", "reserves", "buy",
                                              "round_trip", "error")}, indent=1))
    print("simulation OK: recorded for the test gate (valid 24 h)" if rec["ok"] else
          "simulation FAILED: the test gate stays shut")
    return 0 if rec["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
