"""The owner's wallet tool for the live pump.fun executor. The ONLY code in Pythia that makes a key.

The owner runs it himself, interactively, on the server (never a job, never a service):

    python -m lab.pumpfun_rt.wallet new --out /etc/pythia/pumpfun-keypair.json
    python -m lab.pumpfun_rt.wallet address [--keypair /etc/pythia/pumpfun-keypair.json]

`new` makes a fresh Solana keypair (solders), writes it as the usual 64-number
JSON array with mode 600, and refuses when the file already exists or its
folder can be read or written by everyone. It writes the PUBLIC address next to
it (`<file>.pub`) and to reports/pumpfun_rt/wallet.json for the app, prints the
address, and shows the secret ONCE as a backup string (the base58 text Phantom
and other wallets import) only after the owner types YES at an interactive
terminal. Store that string offline: it is the way to withdraw, by importing it
into a wallet of his own. Pythia never shows it again.

`address` prints the public address from `<file>.pub`. It never opens the
keypair file: the only code that reads that file is live_exec.load_signer, at
runtime, after every gate holds.

Nothing here signs, sends or moves money; nothing logs, writes or sends the
secret anywhere but the terminal it was asked for on.
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
import time
from pathlib import Path

from .events import b58

DEFAULT_OUT = Path("/etc/pythia/pumpfun-keypair.json")
CONFIRM = "YES"


def address_path(keypair: Path) -> Path:
    """Where the public address of a keypair file is kept (the app and `address` read only this)."""
    return keypair.with_name(keypair.name + ".pub")


def code_root() -> Path:
    """The folder that holds the `lab` package: research/lab in a checkout, /app in the lab image.
    One level higher would be / in the image, and every folder would count as inside the code."""
    return Path(__file__).resolve().parents[2]


def _mode(p: Path) -> int:
    return os.stat(p).st_mode


def folder_problems(folder: Path, mode_of=_mode, posix: bool | None = None) -> list[str]:
    """Why the keypair may not go into this folder: it must exist, sit outside the code, and not be
    readable or writable by everyone (on the server: chmod 700 or 750)."""
    posix = os.name == "posix" if posix is None else posix
    try:
        m = mode_of(folder)
    except OSError:
        return [f"the folder {folder} does not exist (make it first: install -d -m 700 {folder})"]
    out = []
    if not stat.S_ISDIR(m):
        out.append(f"{folder} is not a folder")
    if posix and m & 0o006:
        out.append(f"the folder {folder} can be read or written by everyone (chmod 700 {folder}, or 750)")
    try:
        folder.resolve().relative_to(code_root())
        out.append(f"{folder} lies inside the code folder; keep the wallet outside it")
    except ValueError:
        pass
    return out


def new_keypair() -> tuple[bytes, str]:
    """A fresh keypair from solders: (the 64 bytes, the public address)."""
    from solders.keypair import Keypair
    kp = Keypair()
    raw = bytes(kp)
    pub = str(kp.pubkey())
    check_pair(raw, pub)
    return raw, pub


def check_pair(raw: bytes, pub: str) -> None:
    """The file format the live signer reads: 32 bytes of seed, then the 32-byte public key."""
    if len(raw) != 64 or b58(raw[32:]) != pub:
        raise ValueError("the new keypair is not in the 64-byte layout")
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    except ImportError:
        return
    k = Ed25519PrivateKey.from_private_bytes(raw[:32])
    if k.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw) != raw[32:]:
        raise ValueError("the new keypair's halves do not belong together")


def write_new(path: Path, raw: bytes) -> None:
    """Create the file (never overwrite: O_EXCL), mode 600 from the first byte on."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    fd = os.open(path, flags, 0o600)
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(fd, 0o600)
        os.write(fd, json.dumps(list(raw)).encode())
        os.fsync(fd)
    finally:
        os.close(fd)


def publish_address(pub: str, now_ms: int | None = None) -> Path | None:
    """The public address for the app (reports/pumpfun_rt/wallet.json). Best effort."""
    try:
        from .. import report as rep
        d = rep.REPORTS / "pumpfun_rt"
        d.mkdir(parents=True, exist_ok=True)
        p = d / "wallet.json"
        tmp = d / "wallet.json.tmp"
        tmp.write_text(json.dumps({"address": pub, "created_ms": now_ms or int(time.time() * 1000)}), encoding="utf-8")
        tmp.replace(p)
        return p
    except OSError:
        return None


def is_interactive() -> bool:
    try:
        return sys.stdin.isatty() and sys.stdout.isatty()
    except (AttributeError, ValueError):
        return False


WARNING = """
The secret below controls every coin in this wallet. Whoever has it can take them.
  - Write it down or store it OFFLINE (paper, a password manager that stays local).
  - Never paste it into a chat, an email, a ticket, a screenshot or a file in a repo.
  - Pythia will not show it again; it never reads, logs or sends it.
  - To withdraw: import it into a wallet of your own (Phantom: Add wallet, Import private key)
    and send the SOL wherever you like. Pythia has no withdraw function.
"""


def cmd_new(out: Path, ask=input, say=print, interactive=None, mode_of=_mode, posix: bool | None = None,
            make=new_keypair, publish=publish_address) -> int:
    out = Path(out)
    problems = []
    if os.path.lexists(out):
        problems.append(f"{out} already exists; nothing was changed (a wallet is never overwritten)")
    pub_path = address_path(out)
    if os.path.lexists(pub_path):
        problems.append(f"{pub_path} already exists; remove it only if it belongs to no wallet you still use")
    problems += folder_problems(out.parent, mode_of=mode_of, posix=posix)
    if problems:
        say("wallet: refused:\n  - " + "\n  - ".join(problems))
        return 1
    raw, pub = make()
    try:
        write_new(out, raw)
        pub_path.write_text(pub + "\n", encoding="utf-8")
        published = publish(pub)
        say(f"wallet: created {out} (mode 600)")
        say(f"public address: {pub}")
        say(f"(also in {pub_path}" + (f" and {published}" if published else "") + "; fund it by sending SOL to it)")
        interactive = is_interactive() if interactive is None else interactive
        if not interactive:
            say("The backup secret is shown only at an interactive terminal (docker run --rm -it ...). It was NOT "
                "shown. Delete both files and run this again interactively before you fund the wallet.")
            return 0
        say(WARNING)
        answer = ask(f"Type {CONFIRM} to show the backup secret once: ")
        if (answer or "").strip() != CONFIRM:
            say("Not shown. Pythia cannot show it later. Before funding, delete both files and run this again, "
                "or back the file up yourself, offline.")
            return 0
        say("\nBACKUP SECRET (base58, shown once):\n")
        say(b58(raw))
        say("\nStore it offline now, then clear the screen (clear). It is not shown again.")
        return 0
    finally:
        del raw


def cmd_address(keypair: Path, say=print) -> int:
    p = address_path(Path(keypair))
    try:
        pub = p.read_text(encoding="utf-8").strip()
    except OSError:
        say(f"no public address at {p} (the wallet tool writes it when it makes the wallet)")
        return 1
    say(pub)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="the owner's wallet tool for the live pump.fun executor")
    sub = ap.add_subparsers(dest="cmd", required=True)
    n = sub.add_parser("new", help="make a new wallet file (refuses to overwrite); shows the backup once")
    n.add_argument("--out", type=Path, default=DEFAULT_OUT)
    a = sub.add_parser("address", help="print the public address (never opens the keypair file)")
    a.add_argument("--keypair", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args(argv)
    if args.cmd == "new":
        return cmd_new(args.out)
    return cmd_address(args.keypair)


if __name__ == "__main__":
    sys.exit(main())
