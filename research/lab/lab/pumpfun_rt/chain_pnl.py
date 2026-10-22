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


def wallet_delta(rpc, sig: str, wallet: str) -> int | None:
    """The wallet's SOL change in one landed transaction (lamports, fee included); None while
    the node does not have it yet, or when the wallet is not in it."""
    res = rpc.call("getTransaction", [sig, {"encoding": "json", "commitment": "confirmed",
                                            "maxSupportedTransactionVersion": 0}])
    try:
        meta = res["meta"]
        keys = list(res["transaction"]["message"]["accountKeys"])
        keys += list((meta.get("loadedAddresses") or {}).get("writable") or [])
        keys += list((meta.get("loadedAddresses") or {}).get("readonly") or [])
        i = keys.index(wallet)
        return int(meta["postBalances"][i]) - int(meta["preBalances"][i])
    except (KeyError, TypeError, ValueError, IndexError):
        return None


def row_key(row: dict) -> str:
    return f"{row.get('mint')}|{int(float(row.get('exit_ms') or 0))}"


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
        if o.get("what") in ("filled", "failed") and o.get("sig") and o.get("mint"):
            out.append(o)
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
        lo = float(row.get("signal_ms") or row.get("land_ms") or 0) - EARLY_MS
        hi = float(row.get("exit_ms") or 0) + LATE_MS
        by_sig: dict = {}
        for f in fills:                                   # each signature once; a fill beats a failure line
            if f["mint"] == row.get("mint") and lo <= float(f.get("t") or 0) <= hi:
                if f["sig"] not in by_sig or (f.get("what") == "filled" and by_sig[f["sig"]].get("what") != "filled"):
                    by_sig[f["sig"]] = f
        mine = list(by_sig.values())
        if not any(f.get("side") == "buy" and f.get("what") == "filled" for f in mine)                 or not any(f.get("side") == "sell" and f.get("what") == "filled" for f in mine):
            continue
        for f in mine:
            if f["sig"] not in deltas and not throttled:
                try:
                    v = wallet_delta(rpc, f["sig"], wallet)
                except Exception:                         # a rate limit or a timeout: try again next round,
                    throttled = True                      # and never take it for "never landed"
                    continue
                time.sleep(PACE_S)
                if v is None and now - float(f.get("t") or 0) > GONE_MS:
                    v = 0                                 # never landed: it cost nothing
                if v is not None:
                    deltas[f["sig"]] = v
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
