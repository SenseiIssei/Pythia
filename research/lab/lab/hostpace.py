"""One spacing of the calls to a host for every process on the server, not only within one run.

candles-markets (lab.candles.live) and pumpfun (lab.paper.pumpfun) call GeckoTerminal's keyless API from the same
IP, so they share one quota; each spaced only its own calls, and together (2026-10-29: 429 near 10 calls a minute,
not the documented 30) candles-markets got a 429 after about 4 calls every hour and the Solana pools went stale.
Now each call to a host in GAPS takes a slot under a file lock, <write root>/ratelimit/<host>.lock, whose file
holds the wall time of the last call any process made: the caller waits until gap seconds after it, then writes
its own. The lock is held while waiting, so a second process queues behind the first. A folder that cannot be
written leaves only the process's own gap (said once on stderr), never a failed call.
"""

from __future__ import annotations

import fcntl
import json
import os
import sys
import time
from pathlib import Path

# 7.5 s: both jobs together at most 8 calls a minute, under the 429 seen near 10
GAPS = {"api.geckoterminal.com": 7.5}


class HostPace:
    def __init__(self, folder: Path, gaps: dict[str, float] | None = None, clock=None, sleep=None):
        self.folder, self.gaps = Path(folder), dict(GAPS if gaps is None else gaps)
        self.clock, self.sleep = clock, sleep
        self.warned = False

    def wait(self, host: str) -> float:
        """Blocks until the host's gap has passed since any process's last call, takes the slot; the seconds waited."""
        gap = self.gaps.get(host)
        if not gap:
            return 0.0
        clock, sleep = self.clock or time.time, self.sleep or time.sleep
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            fd = os.open(self.folder / f"{host}.lock", os.O_RDWR | os.O_CREAT, 0o644)
        except OSError as e:
            if not self.warned:
                print(f"hostpace: {host} paced in this process only ({type(e).__name__})", file=sys.stderr)
                self.warned = True
            return 0.0
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            try:
                last = float(json.loads(os.pread(fd, 256, 0).decode() or "{}").get("last", -1e18))
            except (ValueError, AttributeError, TypeError):
                last = -1e18
            wait = last + gap - clock()
            if wait > 0:
                sleep(wait)
            now = max(clock(), last + gap) if wait > 0 else clock()   # a fake sleep that does not move the clock
            blob = json.dumps({"last": now}).encode()
            os.ftruncate(fd, 0)
            os.pwrite(fd, blob, 0)
            return max(wait, 0.0)
        finally:
            os.close(fd)                                                # releases the lock
