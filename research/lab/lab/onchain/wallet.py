"""The owner's wallet tool for the stage-2 on-chain trader: pumpfun_rt.wallet, with its own file and app folder.

The owner runs it himself, interactively, on the server (never a job, never a service):

    python -m lab.onchain.wallet new --out /etc/pythia/onchain-keypair.json
    python -m lab.onchain.wallet address [--keypair /etc/pythia/onchain-keypair.json]

The key is made, written (mode 600, never overwriting) and its backup shown once exactly
as for the pump.fun wallet (pumpfun_rt.wallet.cmd_new, the only code in Pythia that makes a
key). Two differences: the public address goes to reports/onchain_live/wallet.json (the
app's "On-chain wallet" section), and the tool refuses the pump.fun wallet's file. Nothing
here signs, sends or moves money.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from ..pumpfun_rt import wallet as W

DEFAULT_OUT = Path("/etc/pythia/onchain-keypair.json")


def publish_address(pub: str, now_ms: int | None = None) -> Path | None:
    """The public address for the app (reports/onchain_live/wallet.json). Best effort."""
    try:
        from .live_gate import reports_dir
        d = reports_dir()
        d.mkdir(parents=True, exist_ok=True)
        p = d / "wallet.json"
        tmp = d / "wallet.json.tmp"
        tmp.write_text(json.dumps({"address": pub, "created_ms": now_ms or int(time.time() * 1000)}), encoding="utf-8")
        tmp.replace(p)
        return p
    except OSError:
        return None


def cmd_new(out: Path, say=print, **kw) -> int:
    out = Path(out)
    if out.resolve() == W.DEFAULT_OUT.resolve() or out.name.startswith("pumpfun"):
        say(f"wallet: refused: {out} is the pump.fun wallet's file; the on-chain trader needs its own wallet")
        return 1
    kw.setdefault("publish", publish_address)
    return W.cmd_new(out, say=say, **kw)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="the owner's wallet tool for the stage-2 on-chain trader")
    sub = ap.add_subparsers(dest="cmd", required=True)
    n = sub.add_parser("new", help="make a new wallet file (refuses to overwrite); shows the backup once")
    n.add_argument("--out", type=Path, default=DEFAULT_OUT)
    a = sub.add_parser("address", help="print the public address (never opens the keypair file)")
    a.add_argument("--keypair", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args(argv)
    if args.cmd == "new":
        return cmd_new(args.out)
    return W.cmd_address(args.keypair)


if __name__ == "__main__":
    sys.exit(main())
