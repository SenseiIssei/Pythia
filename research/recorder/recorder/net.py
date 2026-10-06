"""Reconnect loop shared by every streaming feed."""

from __future__ import annotations

import asyncio
import logging
import time

from .state import State

log = logging.getLogger("net")
HEALTHY_SESSION_S = 60


async def reconnecting(name: str, state: State, body, on_drop=None) -> None:
    """Run `body` forever. Back off exponentially only while sessions keep dying young.

    A session that ran for a minute or more was healthy, so the next attempt
    starts after one second. Without that reset every routine disconnect after
    an earlier flap cost a full minute of data (38 minutes lost in the first week).
    """
    st = state.stream(name)
    backoff = 1.0
    while True:
        started = time.monotonic()
        try:
            await body()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            st.errors += 1
            st.note = f"{type(e).__name__}: {e}"[:200]
            log.warning("%s ended after %.0fs: %s", name, time.monotonic() - started, st.note)
        st.reconnects += 1
        if on_drop:
            on_drop()
        if time.monotonic() - started >= HEALTHY_SESSION_S:
            backoff = 1.0
        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, 60)
