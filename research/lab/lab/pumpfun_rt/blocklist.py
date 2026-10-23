"""The owner's block list for the live pump.fun bot and its paper twin: coins never bought.

<data>/pumpfun_rt/blocked-mints.txt (and /etc/pythia/blocked-mints.txt where it is mounted, trends.block_paths),
one entry per line, "#" starts a comment:

  <mint>              that coin
  creator:<wallet>    every coin that wallet creates (the creator, or the wallet that paid for the creation)
  symbol:<SYMBOL>     every coin whose symbol matches, case-insensitively after trimming and removing every
                      character that is not a letter or digit ("$SHEKEL" and "shekel " match symbol:SHEKEL)
  name:<text>         the same on the coin's name
  match:<text>        every coin whose name or symbol, normalized the same way, contains the text, normalized
                      ("match:spacex" blocks "SpaceX AI", "$SPACEX"; "match:elon" "Elon's Dog"; "match:tesla"
                      "TESLA2" but not "Telsa"); at least MATCH_MIN letters or digits, else the line is ignored

Read at start and again when a file changes (mtime and size, looked at most every CHECK_S). A malformed line is
ignored with one warning; a missing file is an empty list. Pipeline.signal asks before every buy (curve and pool);
a blocked coin is a skip "blocked (symbol SHEKEL)" or "blocked (match elon)" with its log line, never a buy. Held
positions keep their exits.
The app's pump.fun live page edits the same file through the server (server/src/main.rs); trends.py and the meme
module read it too (a mint there is one line; they pass the other kinds by).
"""

from __future__ import annotations

import re
import time
from pathlib import Path

CHECK_S = 2.0
PAPER_RULES = frozenset({"P_pool0_wait"})   # the paper twin of the live strategy honours the list like the live bot
ADDRESS = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
TEXT_MAX = 64                               # a symbol, name or match entry, as written
MATCH_MIN = 3                               # a match entry's letters and digits: "ai" would block half the coins


def norm(s) -> str:
    """Letters and digits only, lower case: "$SHEKEL", "shekel " and "SHEKEL" are one."""
    return "".join(c for c in str(s or "") if c.isalnum()).lower()


def parse_line(line: str) -> tuple[str, str] | None | bool:
    """(kind, value) of one line; None for an empty or comment line, False for a malformed one."""
    v = line.split("#", 1)[0].strip()
    if not v:
        return None
    kind, sep, rest = v.partition(":")
    if not sep:
        return ("mint", v) if ADDRESS.match(v) else False
    kind, rest = kind.strip().lower(), rest.strip()
    if kind == "creator":
        return ("creator", rest) if ADDRESS.match(rest) else False
    if kind in ("symbol", "name"):
        return (kind, rest) if norm(rest) and len(rest) <= TEXT_MAX else False
    if kind == "match":
        return (kind, rest) if len(norm(rest)) >= MATCH_MIN and len(rest) <= TEXT_MAX else False
    return False


class Blocklist:
    """The entries of the files: mints and creators as written, symbols, names and match texts normalized (norm)
    to the entry as written, for the reason."""

    def __init__(self):
        self.mints: set[str] = set()
        self.creators: set[str] = set()
        self.symbols: dict[str, str] = {}
        self.names: dict[str, str] = {}
        self.matches: dict[str, str] = {}

    def __len__(self) -> int:
        return len(self.mints) + len(self.creators) + len(self.symbols) + len(self.names) + len(self.matches)

    def add(self, kind: str, value: str) -> None:
        if kind == "mint":
            self.mints.add(value)
        elif kind == "creator":
            self.creators.add(value)
        else:
            {"symbol": self.symbols, "name": self.names, "match": self.matches}[kind].setdefault(norm(value), value)

    def why(self, mint: str, creators=(), symbol: str = "", name: str = "") -> str | None:
        """The skip reason of a coin on the list, None for one that is not."""
        if mint in self.mints:
            return "blocked (mint)"
        for c in creators:
            if c and c in self.creators:
                return f"blocked (creator {c[:8]})"
        s = norm(symbol)
        if s and s in self.symbols:
            return f"blocked (symbol {self.symbols[s]})"
        n = norm(name)
        if n and n in self.names:
            return f"blocked (name {self.names[n]})"
        for k, v in self.matches.items():
            if k in n or k in s:
                return f"blocked (match {v})"
        return None


def read(paths, warned: set | None = None) -> Blocklist:
    """The list from every file that exists; a malformed line warns once (per text, when `warned` is kept)."""
    bl = Blocklist()
    warned = set() if warned is None else warned
    for p in paths:
        try:
            lines = Path(p).read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        for i, line in enumerate(lines, 1):
            e = parse_line(line)
            if e is False:
                if line.strip() not in warned:
                    warned.add(line.strip())
                    print(f"blocklist: {p} line {i} ignored (not a mint, creator:, symbol:, name: or match: entry): "
                          f"{line.strip()[:80]!r}", flush=True)
            elif e:
                bl.add(*e)
    return bl


def _stamp(paths) -> tuple:
    out = []
    for p in paths:
        try:
            st = Path(p).stat()
            out.append((st.st_mtime_ns, st.st_size))
        except OSError:
            out.append(None)
    return tuple(out)


class BlockWatch:
    """Pipeline.blocked: (strategy, token) -> the skip reason of a blocked coin, else None. Reads the files at
    start and again when one changed, looked at most every every_s. `rules`: the strategies it holds for (None:
    every one of the pipeline's)."""

    def __init__(self, paths=None, rules=None, every_s: float = CHECK_S, clock=time.monotonic):
        if paths is None:
            from .trends import block_paths
            paths = block_paths()
        self.paths = [Path(p) for p in paths]
        self.rules = None if rules is None else frozenset(rules)
        self.every_s = every_s
        self.clock = clock
        self.warned: set[str] = set()
        self.stamp = _stamp(self.paths)
        self.list = read(self.paths, self.warned)
        self.checked = clock()
        if len(self.list):
            print(f"blocklist: {self.summary()}", flush=True)

    def summary(self) -> str:
        b = self.list
        return (f"{len(b.mints)} mints, {len(b.creators)} creators, {len(b.symbols)} symbols, "
                f"{len(b.names)} names" + (f", {len(b.matches)} matches" if b.matches else "") + " blocked")

    def refresh(self) -> None:
        now = self.clock()
        if now - self.checked < self.every_s:
            return
        self.checked = now
        st = _stamp(self.paths)
        if st != self.stamp:
            self.stamp = st
            self.list = read(self.paths, self.warned)
            print(f"blocklist: re-read, {self.summary()}", flush=True)

    def __call__(self, rule: str, tok) -> str | None:
        if self.rules is not None and rule not in self.rules:
            return None
        try:
            self.refresh()
        except Exception as e:                                # noqa: BLE001 - the last list stays
            print(f"blocklist: not re-read ({type(e).__name__}: {e})", flush=True)
        devs = getattr(tok, "devs", None) or ()
        creators = (getattr(tok, "creator", None), *sorted(d for d in devs if d))
        return self.list.why(tok.mint, creators, getattr(tok, "symbol", "") or "", getattr(tok, "name", "") or "")
