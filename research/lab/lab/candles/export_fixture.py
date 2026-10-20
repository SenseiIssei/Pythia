"""Write the parity fixture the engine's Rust candle module is tested against.

    cd research/lab && python -m lab.candles.export_fixture <out.json>

The output holds several series of bars and, for each, every pattern's hit
indices and every derived signal, as computed here by `lab.candles`:

  random-<seed>  a regime-switching random walk (drifting stretches long enough
                 for the trend-gated patterns, 24/7-style opens at the last
                 close, small and large gaps, dojis, shadowless bars, long
                 wicks), with flat bars, a run of flat bars, NaN bars,
                 impossible bars (high below the body) and NaN volumes mixed in.
                 One seed has no volume at all.
  fixtures       the hand-built fixtures of tests/test_candles.py, one after the
                 other (25 trending bars and the pattern each), with the index
                 at which each fixture's own pattern must fire.
  perturbed      every fixture twice with each price moved by up to +-0.08
                 (the tolerance on those bars is 0.1), so some still fire and
                 some just miss.

Prices are written with at most six decimals and volumes with at most three,
and detection runs on exactly those values, so any JSON reader that parses a
short decimal to its nearest double sees the same bars. Missing values are null.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from dataclasses import asdict
from pathlib import Path

import numpy as np

from . import DEFAULT, NAMES, PATTERNS, signals

SEEDS = (1, 2, 3, 4, 5, 6)
BARS = 800
NO_VOLUME_SEED = 4


def _round(x: np.ndarray, places: int) -> np.ndarray:
    return np.array([float(f"{v:.{places}f}") if np.isfinite(v) else np.nan for v in x])


def random_bars(seed: int, T: int = BARS):
    rng = np.random.default_rng(seed)
    o, h, l, c, v = (np.empty(T) for _ in range(5))
    price = 100.0
    drift, left, gappy = 0.0, 0, False
    for t in range(T):
        if left == 0:
            left = int(rng.integers(15, 70))
            drift = float(rng.choice([-1.0, 0.0, 1.0])) * float(rng.uniform(0.3, 1.2))
            gappy = rng.random() < 0.35                  # a stretch that gaps like a session market
        left -= 1
        unit = price * 0.01
        r = rng.random()
        if gappy and r < 0.5:
            op = price + rng.normal(drift * 0.5, 1.5) * unit
        elif r < 0.6:
            op = price                                   # 24/7: open at the last close
        elif r < 0.9:
            op = price + rng.normal(0, 0.15) * unit      # a small gap
        else:
            op = price + rng.normal(drift * 0.5, 1.2) * unit   # a large gap
        k = rng.random()
        if k < 0.15:
            body = rng.normal(0, 0.04)                   # doji
        elif k < 0.45:
            body = rng.normal(drift * 0.2, 0.3)          # small body
        else:
            body = rng.normal(drift, 1.0)
        cl = op + body * unit

        def shadow() -> float:
            s = rng.random()
            if s < 0.2:
                return 0.0
            if s < 0.55:
                return abs(rng.normal(0, 0.08))
            return float(rng.exponential(0.6))

        o[t], c[t] = op, cl
        h[t] = max(op, cl) + shadow() * unit
        l[t] = min(op, cl) - shadow() * unit
        v[t] = rng.lognormal(0, 0.4) * 1000 * (3.0 if rng.random() < 0.06 else 1.0)
        price = cl
    # Flat bars (open = high = low = close) and a run of them, so the yardstick can be zero.
    for t in rng.choice(np.arange(30, T), size=T // 50, replace=False):
        o[t] = h[t] = l[t] = c[t]
    start = int(rng.integers(100, T - 40))
    o[start:start + 14] = h[start:start + 14] = l[start:start + 14] = c[start - 1]
    c[start:start + 14] = c[start - 1]
    # Missing values, impossible bars, missing volumes.
    for t in rng.choice(np.arange(T), size=T // 100, replace=False):
        [o, h, l, c][int(rng.integers(0, 4))][t] = np.nan
    for t in rng.choice(np.arange(T), size=T // 100, replace=False):
        h[t] = min(o[t], c[t]) - 0.01 if np.isfinite(o[t] + c[t]) else h[t]
    for t in rng.choice(np.arange(T), size=T // 100, replace=False):
        if rng.random() < 0.5:
            l[t] = max(o[t], c[t]) + 0.01 if np.isfinite(o[t] + c[t]) else l[t]
        else:
            v[t] = np.nan
    return _round(o, 6), _round(h, 6), _round(l, 6), _round(c, 6), _round(v, 3)


def _test_fixtures():
    """FIXTURES and prefix() from tests/test_candles.py, the single source of the hand-built bars."""
    path = Path(__file__).resolve().parents[2] / "tests" / "test_candles.py"
    spec = importlib.util.spec_from_file_location("_candle_fixtures", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.FIXTURES, mod.prefix


def fixture_bars():
    fixtures, prefix = _test_fixtures()
    rows, expect = [], {}
    for name in sorted(fixtures):
        kind, tail = fixtures[name]
        rows += prefix(kind) + list(tail)
        expect[name] = len(rows) - 1
    a = np.array(rows, dtype=float)
    v = np.ones(len(rows))
    v[[i for j, i in enumerate(expect.values()) if j % 3 == 0]] = 2.5      # some volume-confirmed fixtures
    return a[:, 0], a[:, 1], a[:, 2], a[:, 3], v, expect


def perturbed_bars(seed: int = 99):
    """Every fixture twice, each price moved by up to +-0.08 (near is 0.1 on these bars) and the
    high and low widened to keep the bar possible: some still fire, some just miss, which is
    where a strict or loose inequality and the tolerance rules show."""
    fixtures, prefix = _test_fixtures()
    rng = np.random.default_rng(seed)
    rows = []
    for _ in range(2):
        for name in sorted(fixtures):
            kind, tail = fixtures[name]
            for o, h, l, c in prefix(kind, int(rng.integers(22, 30))):
                rows.append((o, h, l, c))
            for o, h, l, c in tail:
                o2, c2 = o + rng.uniform(-0.08, 0.08), c + rng.uniform(-0.08, 0.08)
                h2 = max(h + rng.uniform(-0.08, 0.08), o2, c2)
                l2 = min(l + rng.uniform(-0.08, 0.08), o2, c2)
                rows.append((o2, h2, l2, c2))
    a = np.array(rows, dtype=float)
    v = np.exp(rng.normal(0, 0.5, len(rows)))
    return _round(a[:, 0], 6), _round(a[:, 1], 6), _round(a[:, 2], 6), _round(a[:, 3], 6), _round(v, 3)


def _floats(x) -> list:
    return [float(v) if np.isfinite(v) else None for v in x]


def series_doc(name, o, h, l, c, v, expect=None) -> dict:
    s = signals(o, h, l, c, v=v)
    doc = {
        "name": name,
        "o": _floats(o), "h": _floats(h), "l": _floats(l), "c": _floats(c),
        "v": None if v is None else _floats(v),
        "hits": {n: np.flatnonzero(s[n]).tolist() for n in NAMES},
        "derived": {n: np.flatnonzero(s[n]).tolist()
                    for n in ("bull_confluence", "bear_confluence", "bull_at_support", "bear_at_resistance",
                              "bull_volume", "bear_volume")},
        "counts": {n: [[int(i), int(s[n][i])] for i in np.flatnonzero(s[n])] for n in ("bull_count", "bear_count")},
    }
    if expect is not None:
        for n, i in expect.items():
            assert s[n][i], f"fixture {n} did not fire at {i}"
        doc["expect"] = expect
    return doc


def build() -> dict:
    series = []
    for seed in SEEDS:
        o, h, l, c, v = random_bars(seed)
        series.append(series_doc(f"random-{seed}", o, h, l, c, None if seed == NO_VOLUME_SEED else v))
    o, h, l, c, v, expect = fixture_bars()
    series.append(series_doc("fixtures", o, h, l, c, v, expect))
    series.append(series_doc("perturbed", *perturbed_bars()))
    registry = [{"name": p.name, "bars": p.bars, "direction": p.direction, "kind": p.kind} for p in PATTERNS.values()]
    return {"params": asdict(DEFAULT), "patterns": registry, "series": series}


def fired_in(doc: dict, prefix: str) -> set[str]:
    """The patterns that fire at least once in the series whose name starts with `prefix`."""
    return {n for s in doc["series"] if s["name"].startswith(prefix) for n, idx in s["hits"].items() if idx}


def write(doc: dict, out: Path) -> None:
    """One line per series field, so a regenerated file diffs by field rather than by number."""
    lines = ["{", f' "params": {json.dumps(doc["params"])},', ' "patterns": [']
    lines += [f"  {json.dumps(p)}" + ("," if i < len(doc["patterns"]) - 1 else "")
              for i, p in enumerate(doc["patterns"])]
    lines += [" ],", ' "series": [']
    for si, s in enumerate(doc["series"]):
        keys = list(s)
        lines.append("  {")
        for ki, k in enumerate(keys):
            lines.append(f"   {json.dumps(k)}: {json.dumps(s[k], separators=(',', ':'), allow_nan=False)}"
                         + ("," if ki < len(keys) - 1 else ""))
        lines.append("  }" + ("," if si < len(doc["series"]) - 1 else ""))
    lines += [" ]", "}", ""]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8", newline="\n")


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: python -m lab.candles.export_fixture <out.json>", file=sys.stderr)
        return 2
    doc = build()
    out = Path(argv[0])
    write(doc, out)
    json.loads(out.read_text(encoding="utf-8"))
    bars = sum(len(s["o"]) for s in doc["series"])
    random, perturbed, fixtures = (fired_in(doc, p) for p in ("random", "perturbed", "fixtures"))
    print(f"wrote {out}: {len(doc['series'])} series, {bars} bars, {len(NAMES)} patterns")
    print(f"patterns firing at least once: random {len(random)}, perturbed fixtures {len(perturbed)}, "
          f"fixtures {len(fixtures)}, any {len(random | perturbed | fixtures)} of {len(NAMES)}")
    rest = sorted(set(NAMES) - random)
    if rest:
        print("not in the random series: " + ", ".join(rest))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
