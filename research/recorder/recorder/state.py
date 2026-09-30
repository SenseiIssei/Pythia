"""Shared in-memory state: latest top of book per venue, and per-stream health."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Quote:
    bid: float
    ask: float
    ts_recv_us: int


@dataclass
class Stream:
    messages: int = 0
    last_us: int = 0
    reconnects: int = 0
    errors: int = 0
    note: str = ""


@dataclass
class State:
    # (venue, base) -> Quote. Kraken bases are USD-quoted, Binance bases USDT-quoted.
    quotes: dict[tuple[str, str], Quote] = field(default_factory=dict)
    streams: dict[str, Stream] = field(default_factory=dict)
    counters: dict[str, int] = field(default_factory=dict)

    def stream(self, name: str) -> Stream:
        return self.streams.setdefault(name, Stream())

    def bump(self, key: str, n: int = 1) -> None:
        self.counters[key] = self.counters.get(key, 0) + n
