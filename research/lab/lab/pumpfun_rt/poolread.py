"""A PumpSwap pool's reserves read from the chain at its migration (F1, 2026-10-28). Read only.

The engine knew a pool's state only from its trades on the stream. The public websocket loses messages, so a pool
whose first trade came within a strategy's wait (P_pool0_wait: 5 s, by block time) was skipped for "no pool state"
106 times in the live bot's log (78 % of its "no pool state" skips that had a migration on record); the pool was
trading, the stream had not said so. Now the collector, paper and live alike, reads the pool once its migration
comes: the pool account (its two vaults and virtual_quote_reserves, txbuild's offsets) and the vaults' balances,
two getMultipleAccounts calls at "confirmed". The result is one row of the store's "other" table,

  {"kind": "pool_state", "t": receive ms, "slot": the read's slot, "mint", "pool", "pb", "pq", "vq"}

which the engine takes like a pool trade's state without being a trade (sim.Engine.pool_state): a signal waiting
for the pool's state goes on, nothing fills on it. Recorded, so a replay sees what the live bot saw.

  PYTHIA_PF_POOL_READ   "0" switches it off (default on)
  PYTHIA_PF_POOL_RPC    the HTTP RPC to read from (default the public mainnet endpoint; one read per migration)
"""

from __future__ import annotations

import base64
import json
import os
import time
import urllib.request

from .events import b58
from .txbuild import OFFSETS

DEFAULT_RPC = "https://api.mainnet-beta.solana.com"
TIMEOUT_S = 5.0
AMOUNT_OFF = 64                        # an SPL token account's amount (Token and Token-2022 alike)


def enabled(env=None) -> bool:
    env = os.environ if env is None else env
    return env.get("PYTHIA_PF_POOL_READ", "1") != "0"


def rpc_url(env=None) -> str:
    env = os.environ if env is None else env
    return (env.get("PYTHIA_PF_POOL_RPC") or "").strip() or DEFAULT_RPC


def post(url: str, method: str, params: list, timeout: float = TIMEOUT_S) -> dict:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": "pythia-lab"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def accounts(call, keys: list[str]) -> tuple[int, list[bytes | None]]:
    """(the read's slot, each account's data or None) of one getMultipleAccounts at "confirmed"."""
    d = call("getMultipleAccounts", [keys, {"encoding": "base64", "commitment": "confirmed"}])
    if d.get("error"):
        raise RuntimeError(str(d["error"])[:200])
    res = d.get("result") or {}
    out = []
    for v in res.get("value") or [None] * len(keys):
        out.append(base64.b64decode(v["data"][0]) if v and v.get("data") else None)
    return int((res.get("context") or {}).get("slot") or 0), out


def parse_pool(data: bytes) -> tuple[str, str, int]:
    """(base vault, quote vault, virtual_quote_reserves) of a PumpSwap Pool account."""
    def key_at(name):
        off = OFFSETS[("Pool", name)]
        if len(data) < off + 32:
            raise ValueError("pool account too short")
        return b58(data[off:off + 32])
    off = OFFSETS[("Pool", "virtual_quote_reserves")]
    vq = int.from_bytes(data[off:off + 16], "little", signed=True) if len(data) >= off + 16 else 0
    return key_at("pool_base_token_account"), key_at("pool_quote_token_account"), vq


def amount(data: bytes | None) -> int | None:
    if not data or len(data) < AMOUNT_OFF + 8:
        return None
    return int.from_bytes(data[AMOUNT_OFF:AMOUNT_OFF + 8], "little")


def read(mint: str, pool: str, call=None, clock=None) -> dict | None:
    """The pool_state row of a pool, or None when the pool or a vault is not there yet (or empty)."""
    url = rpc_url()
    call = call or (lambda method, params: post(url, method, params))
    _, (pdata,) = accounts(call, [pool])
    if not pdata:
        return None
    base_vault, quote_vault, vq = parse_pool(pdata)
    slot, (bdata, qdata) = accounts(call, [base_vault, quote_vault])
    pb, pq = amount(bdata), amount(qdata)
    if not pb or not pq:
        return None
    t = int(clock() if clock else time.time() * 1000)
    return {"kind": "pool_state", "t": t, "slot": slot or None, "tx": None, "mint": mint, "user": None,
            "pool": pool, "pb": pb, "pq": pq, "vq": vq}
