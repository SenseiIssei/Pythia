"""Token transfers between wallets of every coin that migrated to its PumpSwap pool, for its first 30 minutes in the
pool. PAPER ONLY, read only: nothing here reads a key, signs or sends a transaction.

Why: a coordinated dump often starts with several holders sending their tokens to one wallet, which then sells in
one transaction (arXiv 2609.10246). The lab tests that as an early exit signal on paper. The program streams
(collector.py) see pump.fun and PumpSwap events only; a plain wallet-to-wallet transfer is invisible to them.

How: when the collector sees a migration it watches the coin's mint for TRANSFER_WATCH_MS. One extra websocket
connection (the first of the collector's feeds, collector.feed_urls) carries one `logsSubscribe` with
{"mentions": [<mint>]} per watched coin (at "confirmed" always: getTransaction knows nothing processed) and
`logsUnsubscribe` once the watch ends; it is open only while a coin is watched. A notification brings the logs and
the signature only, so each is sorted by its logs (log_kind):

  failed                 skipped (counted)
  pump                   pump.fun or PumpSwap invoked and no token transfer at the top level: a trade, on record
                         already (amm), skipped
  pump+transfer          a trade with a top-level token transfer next to it (a transfer and a sale in one
                         transaction, the dump in one go): fetched
  transfer               a token program logs Transfer, TransferChecked or TransferCheckedWithFee (or the logs are
                         cut off before anything is known): fetched
  silent                 an SPL Token program call that is no part of an account creation, with no trade: fetched
                         only for a coin of the SPL Token program (see below), else skipped
  none                   nothing of the kind (an account created, a burn, a close, a bot's guarded buy that did
                         not trade): skipped

What is fetched goes through a bounded queue (TRANSFER_QUEUE; more are dropped, and counted; the event loop never
waits on it) to TRANSFER_WORKERS workers that ask `getTransaction` (jsonParsed, maxSupportedTransactionVersion 0,
confirmed), all together at most TRANSFER_PER_S calls a second, once more after RETRY_S when the node has not got it
yet, and keep every transfer of the watched mint (parse_tx), top-level and inner, as one row of the store's table
"transfers":

  t (the notification's receive ms), slot, bts (block time, s), sig, mint, src and dst (the OWNERS of the source and
  destination token accounts, from the transaction's pre and post token balances; src falls back to the transfer's
  authority, which may be a delegate; dst is null when the account is in no balance list), amount (raw units), ix
  (transfer, transferChecked, transferCheckedWithFee), outer (the top-level program an inner transfer ran in; null
  for a top-level transfer), swap (the transaction also invokes pump.fun or PumpSwap; the trade's own legs inside
  those programs are never rows)

and, when the connection was down while a coin was watched, a row with ix "gap" from t0 to t: nothing between is
known for the coins watched then. A restart re-watches the migrations of the last half hour (pools.json) with a gap
from the last event before it.

What is and is not covered:
  - `mentions` matches a transaction whose accounts include the mint. TransferChecked (and ...WithFee) lists the
    mint, so every such transfer arrives. A plain `Transfer` lists only source, destination and authority: it
    arrives only when something else in the same transaction names the mint (creating the receiver's associated
    token account does; a coin sprayed to new wallets this way came in at about 1.4 transactions a second on
    2026-10-29, Token-2022's plain Transfer). The counts xfer_plain and xfer_checked show how many of each arrived;
    the plain ones that never arrive cannot be counted here (a holder-balance check against the record could
    estimate them later).
  - The SPL Token program logs no instruction names on mainnet (seen 2026-10-29: its calls show only invoke, return
    and success lines), so an SPL Token coin's transfer cannot be told from its logs. The watch asks the mint's
    owner once (`getAccountInfo`, no data) and fetches the "silent" transactions of SPL Token coins only; until that
    answer comes, and for every Token-2022 coin, they are skipped (xfer_silent). pump.fun's coins of 2026-10 are
    Token-2022 (their legs in PumpSwap trades log TransferChecked), whose program still logs.
  - A transfer in a transaction with a pump.fun or PumpSwap call is kept only when the logs show a Token-2022
    transfer at the top level; a transfer nested in another program next to a trade (some routers), and any SPL
    Token transfer next to a trade (wrapping SOL looks the same in the logs), is not fetched.
  - Swaps of the coin on any other DEX are not skipped by the logs: their token legs are rows with that DEX in
    `outer` (a study filters them by it).
  - A coin is watched from the moment its subscription is confirmed (about a second after its migration arrives);
    at most WATCH_MAX coins at once (more are counted as xfer_watch_full and not watched).

Load on the public endpoint (40 connections, 100 requests per 10 s, 100 MB per 30 s per IP, and 40 requests per
10 s for a single RPC method): one more connection; one request per coin watched and one per coin ended (a few a
minute), all of them again after a reconnect (at most WATCH_MAX); every transaction that mentions a watched mint
comes in, mostly its PumpSwap trades again, an estimated 1 to 3 MB per 30 s at 5 to 20 coins (not measured yet);
getTransaction and the one getAccountInfo per coin at most TRANSFER_PER_S together, each a new HTTPS connection, 20
per 10 s. A sprayed coin fills the queue faster than that (a few 429s and a growing queue on 2026-10-29): the
queue drops what it cannot hold, and xfer_dropped says how much.

  PYTHIA_PF_TRANSFERS      "0" switches it off (default on)
  PYTHIA_PF_TRANSFER_RPC   the HTTP RPC for getTransaction (default PYTHIA_PF_POOL_RPC, else the public endpoint)
"""

from __future__ import annotations

import asyncio
import collections
import json
import os
import random
import sys
import time
import urllib.error

from . import events as E
from . import poolread
from .latency import safe_url

TOKEN = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022 = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
TOKEN_PROGRAMS = (TOKEN, TOKEN_2022)
ATA = "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL"   # the associated token account program
PUMPS = (E.PUMP, E.PUMP_AMM)
IX_TYPES = ("transfer", "transferChecked", "transferCheckedWithFee")
TRANSFER_LOGS = {"Program log: Instruction: Transfer", "Program log: Instruction: TransferChecked",
                 "Program log: Instruction: TransferCheckedWithFee"}
TRANSFER_WATCH_MS = 30 * 60_000   # a coin's transfers are recorded this long after its migration
WATCH_MAX = 30                    # coins watched at once (5 to 20 expected); a reconnect resubscribes them all
TRANSFER_QUEUE = 500              # transactions waiting for their fetch (more are dropped, and counted)
SPL_SILENT_QUEUE = 20             # a silent SPL Token call (no transfer seen in its logs) is queued only below this:
                                  # on 2026-10-29 they were 1,071 of 1,124 queued, 595 of 629 fetched held no
                                  # transfer, and the queue they filled dropped 776, logged transfers among them
TRANSFER_PER_S = 1.5              # RPC calls a second, at most, over all workers (2.0 drew 165 HTTP 429 in 25 min)
TRANSFER_WORKERS = 3              # a call can take a second on the public endpoint; one worker fell far behind
RETRY_S = 2.0                     # a transaction the node has not got yet is asked once more after this
BACKOFF_429_S = 10.0
SILENT_S = 120.0                  # a connection silent this long while coins are watched is reconnected
GAP_MIN_MS = 1000


def now_ms() -> int:
    return int(time.time() * 1000)


def enabled(env=None) -> bool:
    env = os.environ if env is None else env
    return env.get("PYTHIA_PF_TRANSFERS", "1") != "0"


def rpc_url(env=None) -> str:
    env = os.environ if env is None else env
    return (env.get("PYTHIA_PF_TRANSFER_RPC") or "").strip() or poolread.rpc_url(env)


def log_kind(logs: list[str]) -> str | None:
    """"pump", "pump+transfer", "transfer", "silent" or None for one successful transaction's logs (see above). A
    transfer log line counts only when a token program is on top of the invoke stack; an SPL Token call is silent
    unless it is inside a pump.fun or PumpSwap call or an account creation."""
    stack: list[str] = []
    pump = top = hit = silent = cut = False
    for line in logs:
        if line.startswith("Log truncated"):
            cut = True
            break
        if not line.startswith("Program "):
            continue
        if line in TRANSFER_LOGS:
            if stack and stack[-1] in TOKEN_PROGRAMS:
                hit = True
                top = top or len(stack) == 1
            continue
        parts = line.split(" ")
        if len(parts) >= 4 and parts[2] == "invoke":
            if parts[1] == TOKEN and ATA not in stack and not any(p in PUMPS for p in stack):
                silent = True
            stack.append(parts[1])
            pump = pump or parts[1] in PUMPS
        elif len(parts) >= 3 and parts[2] in ("success", "failed", "failed:"):
            if stack and stack[-1] == parts[1]:
                stack.pop()
    if pump:
        return "pump+transfer" if top else "pump"
    if hit or cut:
        return "transfer"
    return "silent" if silent else None


def _transfer(x: dict, mint: str, acct: dict) -> dict | None:
    """src, dst, amount and ix of one parsed token instruction if it moves `mint`, else None."""
    if x.get("programId") not in TOKEN_PROGRAMS:
        return None
    p = x.get("parsed")
    if not isinstance(p, dict) or p.get("type") not in IX_TYPES:
        return None
    info = p.get("info") or {}
    src, dst = acct.get(info.get("source")), acct.get(info.get("destination"))
    m = info.get("mint") or (src or dst or (None, None))[0]      # a plain Transfer names no mint: its accounts do
    if m != mint:
        return None
    amt = info.get("amount") if p["type"] == "transfer" else (info.get("tokenAmount") or {}).get("amount")
    try:
        amt = int(amt)
    except (TypeError, ValueError):
        amt = None
    return {"src": (src or (None, None))[1] or info.get("authority") or info.get("multisigAuthority"),
            "dst": (dst or (None, None))[1], "amount": amt, "ix": p["type"]}


def parse_tx(tx: dict, mint: str, sig: str, slot: int, recv_ms: int) -> list[dict]:
    """Every transfer of `mint` in one getTransaction result (jsonParsed), top-level and inner, in order, as
    store rows. Nothing of a failed transaction, nothing inside a pump.fun or PumpSwap call (the trade's own
    legs)."""
    meta = tx.get("meta") or {}
    if meta.get("err") is not None:
        return []
    msg = (tx.get("transaction") or {}).get("message") or {}
    keys = [k.get("pubkey") if isinstance(k, dict) else k for k in msg.get("accountKeys") or []]
    acct: dict[str, tuple] = {}                                  # token account -> (mint, owner)
    for b in (meta.get("preTokenBalances") or []) + (meta.get("postTokenBalances") or []):
        i = b.get("accountIndex")
        if isinstance(i, int) and 0 <= i < len(keys):
            acct[keys[i]] = (b.get("mint"), b.get("owner"))
    inner = {g.get("index"): g.get("instructions") or [] for g in meta.get("innerInstructions") or []}
    tops = msg.get("instructions") or []
    swap = any(x.get("programId") in PUMPS for x in tops) or any(
        y.get("programId") in PUMPS for g in inner.values() for y in g)
    rows = []
    for i, ix in enumerate(tops):
        outer = ix.get("programId")
        if outer in PUMPS:
            continue
        found = [(ix, None)]
        pump_h = None
        for y in inner.get(i, ()):
            h = y.get("stackHeight") or 2
            if pump_h is not None and h > pump_h:               # below a pump.fun or PumpSwap call (a router's)
                continue
            pump_h = h if y.get("programId") in PUMPS else None
            found.append((y, outer))
        for x, o in found:
            r = _transfer(x, mint, acct)
            if r is not None:
                rows.append({"t": recv_ms, "slot": tx.get("slot") or slot or None, "bts": tx.get("blockTime"),
                             "sig": sig, "mint": mint, **r, "outer": o, "swap": swap})
    return rows


def fetcher(url: str):
    """getTransaction of one signature on `url`: the result, or None while the node has not got it."""
    def fetch(sig: str):
        d = poolread.post(url, "getTransaction", [sig, {"encoding": "jsonParsed", "commitment": "confirmed",
                                                        "maxSupportedTransactionVersion": 0}], timeout=10.0)
        if d.get("error"):
            raise RuntimeError(str(d["error"])[:200])
        return d.get("result")
    return fetch


def owner_of(url: str):
    """The owner program of one account on `url` (getAccountInfo without its data), None when it is not there."""
    def owner(key: str):
        d = poolread.post(url, "getAccountInfo", [key, {"encoding": "base64", "commitment": "confirmed",
                                                        "dataSlice": {"offset": 0, "length": 0}}], timeout=10.0)
        if d.get("error"):
            raise RuntimeError(str(d["error"])[:200])
        v = (d.get("result") or {}).get("value")
        return v.get("owner") if isinstance(v, dict) else None
    return owner


class TransferWatch:
    """The coins watched, their subscriptions on the one transfer connection, the fetch queue. Everything but the
    fetch runs on the event loop and never waits; `keep` is Collector.keep, `counts` the collector's counts."""

    def __init__(self, keep, counts: collections.Counter, watch_ms: int = TRANSFER_WATCH_MS,
                 queue: int = TRANSFER_QUEUE, max_mints: int = WATCH_MAX, clock=None):
        self.keep = keep
        self.counts = counts
        self.watch_ms = watch_ms
        self.max_mints = max_mints
        self.clock = clock or now_ms
        self.until: dict[str, int] = {}                          # mint -> the end of its watch (ms)
        self.spl: dict[str, bool] = {}                           # mint -> an SPL Token coin (owner_of), once known
        self.subs: dict[int, str] = {}                           # subscription id -> mint, this connection
        self.sub_of: dict[str, int] = {}
        self.asked: dict[int, str | None] = {}                   # request id -> mint (subscribe) or None
        self.out: collections.deque[str] = collections.deque()   # requests for the connection to send
        self.q: asyncio.Queue = asyncio.Queue(maxsize=queue)
        self.req = 0
        self.next_call = 0.0                                     # monotonic time of the next RPC call allowed
        self.connected = False
        self.down_since: int | None = None                       # lost while coins were watched

    # ------------------------------------------------------------ the watch
    def watch(self, mint: str, start_ms: int) -> bool:
        """Watch a coin from its migration (start_ms) for watch_ms; False when over, known or full."""
        end = start_ms + self.watch_ms
        if not mint or mint in self.until or end <= self.clock():
            return False
        if len(self.until) >= self.max_mints:
            self.counts["xfer_watch_full"] += 1
            return False
        self.until[mint] = end
        self.counts["xfer_watched"] += 1
        if self.connected:
            self._subscribe(mint)
        try:                                                     # its token program, asked by a worker
            self.q.put_nowait((None, mint, 0, 0))
        except asyncio.QueueFull:
            self.counts["xfer_dropped"] += 1
        return True

    def expire(self) -> list[str]:
        """End the watches that are over (their subscriptions are dropped). Returns their mints."""
        now = self.clock()
        gone = [m for m, end in self.until.items() if end <= now]
        for m in gone:
            del self.until[m]
            self.spl.pop(m, None)
            sub = self.sub_of.pop(m, None)
            if sub is not None:
                self.subs.pop(sub, None)
                self._send("logsUnsubscribe", [sub], None)
            self.counts["xfer_expired"] += 1
        return gone

    def _send(self, method: str, params: list, mint: str | None) -> None:
        self.req += 1
        self.asked[self.req] = mint
        self.out.append(json.dumps({"jsonrpc": "2.0", "id": self.req, "method": method, "params": params}))

    def _subscribe(self, mint: str) -> None:
        self._send("logsSubscribe", [{"mentions": [mint]}, {"commitment": "confirmed"}], mint)

    def up(self) -> None:
        """A new connection: every watched coin subscribed again; the time it was down a gap row."""
        now = self.clock()
        self._reset()
        self.connected = True
        if self.down_since is not None and self.until:
            t0 = max(self.down_since, min(self.until.values()) - self.watch_ms)
            if now - t0 >= GAP_MIN_MS:
                self.counts["xfer_gaps"] += 1
                self.keep("transfers", {"t": now, "t0": t0, "ix": "gap"})
        self.down_since = None
        for m in self.until:
            self._subscribe(m)

    def down(self) -> None:
        self._reset()
        self.connected = False
        if self.until and self.down_since is None:
            self.down_since = self.clock()

    def _reset(self) -> None:
        self.subs.clear()
        self.sub_of.clear()
        self.asked.clear()
        self.out.clear()

    # ------------------------------------------------------------ messages
    def on_message(self, text: str, recv_ms: int) -> str | None:
        """One message of the transfer connection: an answer to a request or a notification (see note)."""
        try:
            d = json.loads(text)
        except ValueError:
            self.counts["xfer_bad_json"] += 1
            return None
        if not isinstance(d, dict):
            return None
        if d.get("method") is None and "id" in d:                # an answer
            mint = self.asked.pop(d["id"], None) if isinstance(d["id"], int) else None
            if d.get("error"):
                self.counts["xfer_rpc_error"] += 1
                if self.counts["xfer_rpc_error"] <= 5:
                    print(f"collector: transfers rpc error {str(d.get('error'))[:200]}", file=sys.stderr)
                return None
            sub = d.get("result")
            if mint is None or isinstance(sub, bool) or not isinstance(sub, int):
                return None
            if mint not in self.until:                           # ended before its answer came
                self._send("logsUnsubscribe", [sub], None)
                return None
            self.subs[sub], self.sub_of[mint] = mint, sub
            return None
        params = d.get("params") or {}
        mint = self.subs.get(params.get("subscription"))
        if mint is None:                                         # a subscription already ended
            return None
        res = params.get("result") or {}
        v = res.get("value") or {}
        return self.note(mint, (res.get("context") or {}).get("slot") or 0, v.get("signature") or "",
                         v.get("err") is not None, v.get("logs") or [], recv_ms)

    def note(self, mint: str, slot: int, sig: str, failed: bool, logs: list[str], recv_ms: int) -> str:
        """One transaction that mentions a watched mint: queued for its fetch or skipped. Returns what it was."""
        self.counts["xfer_notes"] += 1
        if failed:
            self.counts["xfer_failed"] += 1
            return "failed"
        kind = log_kind(logs) or "none"
        if kind == "silent" and self.spl.get(mint):              # an SPL Token coin's call: maybe its transfer
            if self.q.qsize() >= SPL_SILENT_QUEUE:               # behind every logged transfer, never in its way
                self.counts["xfer_spl_skipped"] += 1
                return "skipped"
            self.counts["xfer_spl_silent"] += 1
            kind = "transfer"
        if kind in ("pump", "none", "silent"):
            self.counts["xfer_" + kind] += 1
            return kind
        if kind == "pump+transfer":
            self.counts["xfer_pump_transfer"] += 1
        try:
            self.q.put_nowait((sig, mint, slot, recv_ms))
        except asyncio.QueueFull:
            self.counts["xfer_dropped"] += 1
            return "dropped"
        self.counts["xfer_queued"] += 1
        return "queued"

    # ------------------------------------------------------------ the fetch
    async def call(self, fn, arg):
        """fn(arg) in a thread, at most TRANSFER_PER_S calls a second over all workers; None on an error."""
        now = time.monotonic()
        wait = self.next_call - now
        self.next_call = max(now, self.next_call) + 1.0 / TRANSFER_PER_S
        if wait > 0:
            await asyncio.sleep(wait)
        try:
            return await asyncio.to_thread(fn, arg)
        except urllib.error.HTTPError as e:
            self.counts["xfer_429" if e.code == 429 else "xfer_fetch_error"] += 1
            if e.code == 429:
                self.next_call = max(self.next_call, time.monotonic() + BACKOFF_429_S)
        except Exception as e:                                   # noqa: BLE001 - never the URL (a provider's key)
            self.counts["xfer_fetch_error"] += 1
            if self.counts["xfer_fetch_error"] <= 5:
                print(f"collector: transfer fetch {type(e).__name__}", file=sys.stderr)
        return None

    async def worker(self, fetch, owner=None) -> None:
        """Fetches each queued transaction (TRANSFER_WORKERS of these share the rate) and keeps its transfers of the
        watched mint; a queued coin without a signature has its token program asked (owner_of)."""
        while True:
            sig, mint, slot, recv = await self.q.get()
            if sig is None:
                prog = await self.call(owner, mint) if owner is not None else None
                if prog and mint in self.until:
                    self.spl[mint] = prog == TOKEN
                continue
            tx = await self.call(fetch, sig)
            if tx is None:                                       # not on the node yet, or an error: once more
                await asyncio.sleep(RETRY_S)
                tx = await self.call(fetch, sig)
            if tx is None:
                self.counts["xfer_missing"] += 1
                continue
            self.counts["xfer_fetched"] += 1
            try:
                rows = parse_tx(tx, mint, sig, slot, recv)
            except Exception as e:                               # noqa: BLE001 - one odd transaction never stops a worker
                self.counts["xfer_parse_error"] += 1
                if self.counts["xfer_parse_error"] <= 5:
                    print(f"collector: transfer parse {type(e).__name__}: {e}", file=sys.stderr)
                continue
            if not rows:
                self.counts["xfer_no_row"] += 1
            for r in rows:
                self.counts["xfer_plain" if r["ix"] == "transfer" else "xfer_checked"] += 1
                self.keep("transfers", r)

    # ------------------------------------------------------------ the connection
    async def stream(self, session, url: str, stop: asyncio.Event) -> None:
        """The one transfer connection: open while a coin is watched, its subscriptions multiplexed on it,
        reconnected with backoff like the program links."""
        import aiohttp
        src = safe_url(url)
        backoff = 0.5
        while not stop.is_set():
            self.expire()
            if not self.until:
                await asyncio.sleep(1.0)
                continue
            t_conn = time.monotonic()
            heard = False
            try:
                async with session.ws_connect(url, heartbeat=None, max_msg_size=16 << 20, compress=0) as ws:
                    self.up()
                    last = time.monotonic()
                    recv = None
                    try:
                        while not stop.is_set():
                            self.expire()
                            while self.out:
                                await ws.send_str(self.out.popleft())
                            if not self.until:                   # nothing watched: closed until the next migration
                                break
                            if recv is None:
                                recv = asyncio.ensure_future(ws.receive())
                            done, _ = await asyncio.wait({recv}, timeout=1.0)
                            if not done:
                                if time.monotonic() - last > SILENT_S:
                                    print(f"collector: transfers silent for {SILENT_S:.0f} s, reconnecting",
                                          file=sys.stderr)
                                    break
                                continue
                            msg, recv = recv.result(), None
                            last = time.monotonic()
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                heard = True
                                self.on_message(msg.data, now_ms())
                            elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED,
                                              aiohttp.WSMsgType.CLOSING, aiohttp.WSMsgType.ERROR):
                                self.counts["xfer_closed"] += 1
                                break
                    finally:
                        if recv is not None:
                            recv.cancel()
            except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as e:
                print(f"collector: transfers {src} {type(e).__name__}", file=sys.stderr)
            self.down()
            if stop.is_set():
                break
            if not self.until:
                backoff = 0.5
                continue
            self.counts["xfer_reconnects"] += 1
            # the public endpoint closes a working connection every minute or so; with one link (not several, like
            # the program streams) a doubling wait made gaps of up to 21 s (2026-10-29): after a link that delivered,
            # it starts over (one that lasted 5 s at least: never a connect a second)
            up_s = time.monotonic() - t_conn
            if (heard and up_s > 5) or up_s > 60:
                backoff = 0.5
            await asyncio.sleep(backoff * (0.5 + random.random()))
            backoff = min(60.0, backoff * 2)

    def status(self) -> dict:
        return {"watched": len(self.until), "subscribed": len(self.subs), "connected": self.connected,
                "queue": self.q.qsize()}
