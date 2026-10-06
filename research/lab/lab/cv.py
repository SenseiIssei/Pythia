"""Time-series splits that cannot leak.

Walk-forward with an embargo: the model for a test period sees only data that
ended at least `embargo` before the period starts. Features in this lab look
backwards only, and labels look forward by `horizon`, so the embargo has to
cover at least the label horizon.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np

HOUR_US = 3_600_000_000


@dataclass
class Fold:
    name: str
    train: np.ndarray  # boolean masks over the frame
    test: np.ndarray


def quarter_starts(t0_us: int, t1_us: int) -> list[int]:
    d = datetime.fromtimestamp(t0_us / 1e6, tz=timezone.utc)
    y, q = d.year, (d.month - 1) // 3
    out = []
    while True:
        start = datetime(y, q * 3 + 1, 1, tzinfo=timezone.utc)
        us = int(start.timestamp() * 1e6)
        if us > t1_us:
            return out
        out.append(us)
        q += 1
        if q == 4:
            y, q = y + 1, 0


def walk_forward(ts_us: np.ndarray, first_test_us: int, embargo_h: int = 24) -> list[Fold]:
    starts = [s for s in quarter_starts(int(ts_us.min()), int(ts_us.max())) if s >= first_test_us]
    folds = []
    for i, s in enumerate(starts):
        e = starts[i + 1] if i + 1 < len(starts) else int(ts_us.max()) + 1
        test = (ts_us >= s) & (ts_us < e)
        if test.sum() == 0:
            continue
        train = ts_us < s - embargo_h * HOUR_US
        d = datetime.fromtimestamp(s / 1e6, tz=timezone.utc)
        folds.append(Fold(f"{d.year}Q{(d.month - 1) // 3 + 1}", train, test))
    return folds
