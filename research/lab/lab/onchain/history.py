"""Our own wallet's history, read from the chain: every movement in and out, for the app's Wallet tab. Read only.

    python -m lab.onchain.history              read what is new (the job onchain-history, every 5 min)
    python -m lab.onchain.history --address A  another public address (default: the wallet tool's file)

getSignaturesForAddress for the wallet's public address (newest first, down to the newest one
already read), then getTransaction (jsonParsed) for each, parsed into one entry per transaction:

  deposit   only coins in, the fee paid by someone else (the owner sending SOL or USDC)
  swap      one coin out, another in, our fee: from and to amounts, the price
  sent      only coins out (the owner withdrawing with his backup in his own wallet)
  failed    landed with an error: only the fee was paid
  other     nothing moved but the fee (an account closed, a memo)

Each with the fee split into base (5,000 lamports a signature), priority and the Sender tip (a
transfer to one of Helius' tip accounts), and the rent of token accounts opened or closed. Written
to reports/onchain/history.json, newest first, at most MAX_ENTRIES. The live service calls update()
after every swap; nothing here signs, sends or reads a key.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

from ..pumpfun_rt import live_exec as PX
from ..pumpfun_rt import txbuild as X
from . import live_gate as LG
from . import mints as M

WSOL = M.SOL.mint
BASE_FEE_L = 5_000                       # a signature
RENT_TOKEN_L = 2_039_280                 # a token account's rent (165 bytes)
MAX_ENTRIES = 1000
PAGE = 100
MAX_PAGES = 10
RPC_TIMEOUT = 60.0                      # the public node took 26 s for one signature page on 2026-10-28 (8 s failed)
SOL_DUST_L = 10_000                      # SOL changes this small next to a token swap are rounding of rent


def history_path() -> Path:
    from .. import report as rep
    return rep.REPORTS / "onchain" / "history.json"


def _keys(res: dict) -> list[str]:
    msg = res["transaction"]["message"]
    meta = res.get("meta") or {}
    keys = list(msg["accountKeys"])
    keys += list((meta.get("loadedAddresses") or {}).get("writable") or [])
    keys += list((meta.get("loadedAddresses") or {}).get("readonly") or [])
    return [k.get("pubkey") if isinstance(k, dict) else k for k in keys]


def _tokens(meta: dict, side: str, wallet: str) -> dict[str, tuple[int, int]]:
    """The wallet's token holdings in one side (pre or post): mint -> (raw, decimals)."""
    out: dict[str, tuple[int, int]] = {}
    for b in meta.get(side) or []:
        try:
            if b.get("owner") != wallet:
                continue
            amt = int(b["uiTokenAmount"]["amount"])
            dec = int(b["uiTokenAmount"].get("decimals") or 0)
            out[b["mint"]] = (out.get(b["mint"], (0, dec))[0] + amt, dec)
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
    return out


def _tip(res: dict, wallet: str) -> int:
    """Lamports the wallet sent to a Helius tip account (jsonParsed system transfers, inner ones too)."""
    ixs = list(res["transaction"]["message"].get("instructions") or [])
    for inner in (res.get("meta") or {}).get("innerInstructions") or []:
        ixs += list(inner.get("instructions") or [])
    n = 0
    for ix in ixs:
        p = ix.get("parsed") if isinstance(ix, dict) else None
        if not isinstance(p, dict) or ix.get("program") != "system" or p.get("type") != "transfer":
            continue
        info = p.get("info") or {}
        if info.get("source") == wallet and info.get("destination") in X.HELIUS_TIP_ACCOUNTS:
            try:
                n += int(info.get("lamports") or 0)
            except (TypeError, ValueError):
                continue
    return n


def coin_of(mint: str) -> str:
    m = M.BY_MINT.get(mint)
    return m.coin if m else mint[:4] + ".." + mint[-4:]


def parse_tx(res, wallet: str, sig: str | None = None) -> dict | None:
    """One landed transaction (a getTransaction result, jsonParsed or json) as the wallet saw it; None when the
    node does not have it or the wallet is not in it."""
    try:
        meta = res["meta"]
        keys = _keys(res)
        i = keys.index(wallet)
        sol_delta = int(meta["postBalances"][i]) - int(meta["preBalances"][i])
        fee = int(meta.get("fee") or 0)
        sigs = list(res["transaction"].get("signatures") or [])
    except (KeyError, TypeError, ValueError, IndexError, AttributeError):
        return None
    payer = keys[0] == wallet
    err = meta.get("err")
    tip = _tip(res, wallet) if payer and err is None else 0          # a failed transaction moved nothing but its fee
    pre, post = _tokens(meta, "preTokenBalances", wallet), _tokens(meta, "postTokenBalances", wallet)
    opened = len([m for m in post if m not in pre and m != WSOL])
    closed = len([m for m in pre if m not in post and m != WSOL])
    rent = (opened - closed) * RENT_TOKEN_L if payer else 0         # someone else opening our account paid its rent
    # What moved besides the fee, the tip and the rent; wrapped SOL counts as SOL.
    sol = sol_delta + (fee if payer else 0) + tip + rent
    changes: dict[str, int] = {}
    decimals: dict[str, int] = {}
    for mint in set(pre) | set(post):
        d = post.get(mint, (0, 0))[0] - pre.get(mint, (0, 0))[0]
        decimals[mint] = (post.get(mint) or pre.get(mint))[1]
        if mint == WSOL:
            sol += d
        elif d:
            changes[mint] = d
    tokens_moved = bool(changes)
    if sol and not (tokens_moved and abs(sol) <= SOL_DUST_L):
        changes[WSOL] = sol
        decimals[WSOL] = 9
    moves = [{"coin": coin_of(m), "mint": m, "amount": d / 10 ** decimals.get(m, 0), "raw": d}
             for m, d in sorted(changes.items(), key=lambda kv: kv[1])]
    ins = [x for x in moves if x["raw"] > 0]
    outs = [x for x in moves if x["raw"] < 0]
    if err is not None:
        kind = "failed"
    elif ins and not outs:
        kind = "deposit"
    elif outs and not ins:
        kind = "sent"
    elif ins and outs:
        kind = "swap"
    else:
        kind = "other"
    e = {"sig": sig or (sigs[0] if sigs else None), "t": int(res["blockTime"]) * 1000 if res.get("blockTime") else None,
         "slot": res.get("slot"), "kind": kind, "ok": err is None, "err": str(err)[:160] if err is not None else None,
         "ours": payer, "moves": moves, "fee_sol": fee / 1e9 if payer else 0.0,
         "base_sol": (BASE_FEE_L * max(len(sigs), 1)) / 1e9 if payer else 0.0,
         "priority_sol": max(fee - BASE_FEE_L * max(len(sigs), 1), 0) / 1e9 if payer else 0.0,
         "tip_sol": tip / 1e9, "rent_sol": rent / 1e9,
         "from": None, "from_amount": None, "to": None, "to_amount": None, "price": None}
    if kind == "swap":
        a, b = outs[0], ins[-1]
        e.update({"from": a["coin"], "from_amount": -a["amount"], "to": b["coin"], "to_amount": b["amount"]})
        # The price of the coin that is not USDC in USDC, else what one `to` cost in `from`.
        if a["coin"] == "USDC" and b["amount"]:
            e["price"] = -a["amount"] / b["amount"]
        elif b["coin"] == "USDC" and a["amount"]:
            e["price"] = b["amount"] / -a["amount"]
        elif b["amount"]:
            e["price"] = -a["amount"] / b["amount"]
    return e


# ---------------------------------------------------------------- reading the chain

def read_file() -> dict:
    d = PX.read_json(history_path())
    return d if isinstance(d, dict) else {}


def new_signatures(rpc, address: str, until: str | None) -> list[dict]:
    """The wallet's signatures newer than `until`, newest first (at most MAX_PAGES pages)."""
    out: list[dict] = []
    before = None
    for _ in range(MAX_PAGES):
        opts = {"limit": PAGE, "commitment": "confirmed"}
        if until:
            opts["until"] = until
        if before:
            opts["before"] = before
        page = rpc.call("getSignaturesForAddress", [address, opts]) or []
        out += [p for p in page if isinstance(p, dict) and p.get("signature")]
        if len(page) < PAGE:
            break
        before = page[-1].get("signature")
    return out


def update(rpc, address: str, now_ms: int | None = None, keep: int = MAX_ENTRIES) -> dict:
    """Read what is new and write the file. A transaction the node does not return yet stays `pending` and is
    asked for again next time."""
    d = read_file()
    if d.get("address") != address:
        d = {}
    entries = [e for e in d.get("entries") or [] if isinstance(e, dict)]
    known = {e.get("sig") for e in entries}
    pending = [s for s in d.get("pending") or [] if isinstance(s, str)]
    sigs = [s["signature"] for s in new_signatures(rpc, address, entries[0]["sig"] if entries else None)]
    todo = list(dict.fromkeys(sigs + pending))
    still = []
    fresh = []
    for sig in todo:
        if sig in known:
            continue
        res = rpc.call("getTransaction", [sig, {"encoding": "jsonParsed", "commitment": "confirmed",
                                                "maxSupportedTransactionVersion": 0}])
        e = parse_tx(res, address, sig) if res else None
        if e is None:
            still.append(sig)
            continue
        fresh.append(e)
    entries = sorted(fresh + entries, key=lambda e: (e.get("t") or 0, e.get("slot") or 0), reverse=True)[:keep]
    out = {"updated_ms": now_ms or int(time.time() * 1000), "address": address, "entries": entries,
           "pending": still[:200]}
    PX.write_json(history_path(), out)
    return out


def our_address() -> str | None:
    """The on-chain wallet's public address: the trader's status, else the wallet tool's file."""
    for name in ("status.json", "wallet.json"):
        d = PX.read_json(LG.reports_dir() / name)
        if isinstance(d, dict) and isinstance(d.get("address"), str) and 32 <= len(d["address"]) <= 44:
            return d["address"]
    return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="our on-chain wallet's history from the chain (read only)")
    ap.add_argument("--address", help="a public address (default: the wallet tool's file)")
    a = ap.parse_args(argv)
    addr = a.address or our_address()
    if not addr:
        print("onchain history: no wallet yet (python -m lab.onchain.wallet new); nothing to read")
        return 0
    rpc = PX.Rpc(os.environ.get(LG.ENV_RPC) or LG.DEFAULT_RPC, timeout=RPC_TIMEOUT)
    out = update(rpc, addr)
    print(f"onchain history: {len(out['entries'])} entries, {len(out['pending'])} pending")
    return 0


if __name__ == "__main__":
    sys.exit(main())
