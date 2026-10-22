"""What each live trade really did to the wallet, read back from the chain.

The live book books a closed trade from the fills it saw on the stream and the fees
it expects. The wallet sees more: the real network and priority fee, the rent of
the token account (paid on the buy, refunded when the sale closes it), the one-time
rent of the volume accumulator, pump.fun's fees as charged. The first live trade
(DLM, 2026-10-22) was booked at +0.000674 SOL while the wallet lost 0.000672 SOL.

So every closed trade is checked against the chain: its landed transactions are read
with getTransaction, and the wallet's own balance change in each (post minus pre,
which includes the fee) is summed. The ledger row then carries that truth (pnl_sol,
stake_sol as what the buys took, proceeds_sol as what the sales gave back, ret), and
the difference to what was booked goes back into the day's and the total's P&L, so
the daily loss stop and the total budget stop count what was really lost.

Read only: nothing here signs or sends anything. The transactions come from
orders.jsonl: the executor's "filled" lines and every "failed" line that carries a
signature (a sale the node refused can still land on chain and pay its fee; CCC,
2026-10-22, paid ten). A signature the node still does not know after ten minutes
never landed and counts 0. chain.json keeps every transaction's delta and every row
already checked, so each signature is read once.

A row's transactions are its own: the order lines carry the run id and the position id
(and a leftover's row the signature of its buy), so two trades of the same token close
together are never mixed up. Rows written before that are matched by token and time.

A read that fails with a rate limit (429) stops the round and is tried again next round;
any other error is counted per signature, and after MAX_TRIES that row is skipped with
a log line, so one unreadable signature never blocks the rows after it.
"""

from __future__ import annotations

import csv
import json
import threading
import time
from pathlib import Path

LAMPORTS = 1_000_000_000
LEDGER_LOCK = threading.Lock()          # write_close and the rewrite here never overlap
EARLY_MS, LATE_MS = 60_000, 1_800_000   # a row's transactions: from its signal to half an hour after its exit
GONE_MS = 600_000                       # a signature the node does not know after ten minutes never landed
PACE_S = 0.4                            # between two reads: the public node answers 429 to bursts
MAX_TRIES = 5                           # reads of one signature that fail other than by a rate limit


def tx_effect(res, wallet: str, mint: str | None = None) -> dict | None:
    """What one landed transaction (a getTransaction result) did to the wallet: its SOL change
    (lamports, fee included), the fee, the error (None when it succeeded), the block time, and with
    `mint` the change of the wallet's holding of that token (pre/postTokenBalances, owner = wallet).
    None while the node does not have it yet, or when the wallet is not in it."""
    try:
        meta = res["meta"]
        keys = list(res["transaction"]["message"]["accountKeys"])
        keys += list((meta.get("loadedAddresses") or {}).get("writable") or [])
        keys += list((meta.get("loadedAddresses") or {}).get("readonly") or [])
        keys = [k.get("pubkey") if isinstance(k, dict) else k for k in keys]
        i = keys.index(wallet)
        out = {"delta_l": int(meta["postBalances"][i]) - int(meta["preBalances"][i]),
               "fee_l": int(meta.get("fee") or 0), "err": meta.get("err"),
               "block_ms": int(res["blockTime"]) * 1000 if res.get("blockTime") else None, "tok": None}
    except (KeyError, TypeError, ValueError, IndexError, AttributeError):
        return None
    if mint:
        def held(side: str) -> int:
            n = 0
            for b in meta.get(side) or []:
                try:
                    if b.get("mint") == mint and b.get("owner") == wallet:
                        n += int(b["uiTokenAmount"]["amount"])
                except (KeyError, TypeError, ValueError, AttributeError):
                    continue
            return n
        out["tok"] = held("postTokenBalances") - held("preTokenBalances")
    return out


def wallet_delta(rpc, sig: str, wallet: str) -> int | None:
    """The wallet's SOL change in one landed transaction (lamports, fee included); None while
    the node does not have it yet, or when the wallet is not in it."""
    res = rpc.call("getTransaction", [sig, {"encoding": "json", "commitment": "confirmed",
                                            "maxSupportedTransactionVersion": 0}])
    e = tx_effect(res, wallet)
    return None if e is None else e["delta_l"]


def rate_limited(e: Exception) -> bool:
    s = f"{type(e).__name__}: {e}".lower()
    return "429" in s or "too many requests" in s or "rate limit" in s


def row_key(row: dict) -> str:
    return f"{row.get('mint')}|{int(float(row.get('exit_ms') or 0))}"


def _int(v) -> int | None:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _fills(orders_path: Path) -> list[dict]:
    out = []
    try:
        lines = orders_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    for line in lines:
        try:
            o = json.loads(line)
        except ValueError:
            continue
        # Fills, and failures that carry a signature: a failed sale can still land and pay its fee.
        # A sent line only counts as a leftover's buy (named by its signature in the row).
        if o.get("what") in ("filled", "failed", "sent") and o.get("sig") and o.get("mint"):
            out.append(o)
    return out


RANK = {"filled": 2, "failed": 1, "sent": 0}


def _mine(row: dict, fills: list[dict]) -> list[dict]:
    """The order lines of one ledger row, one per signature (a fill beats a failure, a failure a send):
    by the run id and position id the row carries (and its buy's signature), else by token and time."""
    run, pid, buy_sig = row.get("run") or None, _int(row.get("pid")), row.get("buy_sig") or None
    if run and pid is not None:
        def match(f):
            if buy_sig and f["sig"] == buy_sig:
                return True
            return f.get("what") != "sent" and str(f.get("run")) == run and _int(f.get("pid")) == pid
    else:
        lo = float(row.get("signal_ms") or row.get("land_ms") or 0) - EARLY_MS
        hi = float(row.get("exit_ms") or 0) + LATE_MS

        def match(f):
            if buy_sig and f["sig"] == buy_sig:
                return True
            return f.get("what") != "sent" and f["mint"] == row.get("mint") and lo <= float(f.get("t") or 0) <= hi
    by_sig: dict = {}
    for f in fills:
        if match(f) and (f["sig"] not in by_sig or RANK.get(f.get("what"), 0) > RANK.get(by_sig[f["sig"]].get("what"), 0)):
            by_sig[f["sig"]] = f
    return list(by_sig.values())


def absorbed(d: Path) -> set:
    """The signatures already inside a settled ledger row (their fees are in that row's chain value)."""
    try:
        cache = json.loads((d / "chain.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    out = set()
    for v in (cache.get("rows") or {}).values():
        if isinstance(v, dict) and "chain_l" in v:
            out.update(v.get("sigs") or [])
    return out


def reconcile(rpc, wallet: str, d: Path, now_ms: int | None = None) -> tuple[int, bool]:
    """Check every ledger row not yet checked against the chain and rewrite the ledger with what
    the wallet really saw. Returns (the correction to book in lamports, chain minus booked, over
    the rows checked now; whether the ledger changed)."""
    ledger, orders, cache_p = d / "ledger.csv", d / "orders.jsonl", d / "chain.json"
    try:
        cache = json.loads(cache_p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cache = {}
    deltas: dict = cache.setdefault("deltas", {})
    done: dict = cache.setdefault("rows", {})
    tries: dict = cache.setdefault("tries", {})
    with LEDGER_LOCK:
        try:
            with ledger.open(newline="", encoding="utf-8") as fh:
                reader = csv.DictReader(fh)
                cols, rows = list(reader.fieldnames or []), list(reader)
        except OSError:
            return 0, False
    fills = _fills(orders)
    now = now_ms if now_ms is not None else time.time() * 1000
    adjust, updates, throttled = 0, {}, False
    for row in rows:
        key = row_key(row)
        if key in done:
            continue
        mine = _mine(row, fills)
        buy_sig = row.get("buy_sig") or None
        if not (any(f.get("side") == "buy" and f.get("what") == "filled" for f in mine)
                or (buy_sig and any(f["sig"] == buy_sig for f in mine))) \
                or not any(f.get("side") == "sell" and f.get("what") == "filled" for f in mine):
            continue
        unreadable = None
        for f in mine:
            if f["sig"] not in deltas and not throttled:
                try:
                    v = wallet_delta(rpc, f["sig"], wallet)
                except Exception as e:                    # never taken for "never landed"
                    if rate_limited(e):                   # the node wants a pause: the next round goes on
                        print(f"chain check: rate limited at {f['sig'][:12]}...; next round", flush=True)
                        throttled = True
                        continue
                    n = tries[f["sig"]] = int(tries.get(f["sig"]) or 0) + 1
                    print(f"chain check: {f['sig'][:12]}... not readable ({type(e).__name__}: {e}), try {n} "
                          f"of {MAX_TRIES}"[:220], flush=True)
                    if n >= MAX_TRIES:
                        unreadable = f["sig"]
                    continue
                time.sleep(PACE_S)
                if v is None and now - float(f.get("t") or 0) > GONE_MS:
                    v = 0                                 # never landed: it cost nothing
                if v is not None:
                    deltas[f["sig"]] = v
        if unreadable is not None:
            done[key] = {"skipped": f"{unreadable} unreadable after {MAX_TRIES} tries", "sigs": []}
            print(f"chain check: the row {key} is skipped, {unreadable[:12]}... stays unreadable; it keeps "
                  "its booked value", flush=True)
            continue
        if any(f["sig"] not in deltas for f in mine):
            continue                                      # not readable yet: next round
        spent = -sum(deltas[f["sig"]] for f in mine if f["side"] == "buy")
        back = sum(deltas[f["sig"]] for f in mine if f["side"] == "sell")
        chain_l = back - spent
        booked_l = int(round(float(row.get("pnl_sol") or 0) * LAMPORTS))
        adjust += chain_l - booked_l
        updates[key] = {"stake_sol": f"{spent / LAMPORTS:.9f}", "proceeds_sol": f"{back / LAMPORTS:.9f}",
                        "pnl_sol": f"{chain_l / LAMPORTS:.9f}", "ret": f"{chain_l / spent:.6f}" if spent > 0 else ""}
        done[key] = {"chain_l": chain_l, "booked_l": booked_l, "sigs": [f["sig"] for f in mine]}
    if updates:
        with LEDGER_LOCK:                                 # read again: a row may have been added meanwhile
            with ledger.open(newline="", encoding="utf-8") as fh:
                reader = csv.DictReader(fh)
                cols, rows = list(reader.fieldnames or []), list(reader)
            for row in rows:
                row.update(updates.get(row_key(row), {}))
            tmp = ledger.with_suffix(".tmp")
            with tmp.open("w", newline="", encoding="utf-8") as fh:
                w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
                w.writeheader()
                w.writerows(rows)
            tmp.replace(ledger)
    tmp = cache_p.with_suffix(".tmp")
    tmp.write_text(json.dumps(cache), encoding="utf-8")
    tmp.replace(cache_p)
    return adjust, bool(updates)
