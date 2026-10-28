"""Time-series splits that cannot leak.

Walk-forward with a purge and an embargo: the model for a test period sees only
rows whose label ended before the period starts (the purge: a row's label ends
at its time plus `horizon_h`, or at a given label end) and that are at least
`embargo` before it. Features in this lab look backwards only, and labels look
forward by the horizon, so without a label end the embargo has to cover at
least the label horizon.

Combinatorial purged CV (T2, Lopez de Prado, AFML ch. 12; skfolio's
CombinatorialPurgedCV as the reference): the distinct times cut into n_groups
contiguous groups, every choice of k_test of them one split's test set, the
rest its training set, purged (a training row whose label reaches into a test
group) and embargoed (a training row within the embargo after a test group).
cpcv_paths puts each group's test values from C(n-1, k-1) splits together into
as many paths, each one out-of-sample series over every time.
"""

from __future__ import annotations

import itertools
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


def walk_forward(ts_us: np.ndarray, first_test_us: int, embargo_h: int = 24, horizon_h: int = 0,
                 label_end_us: np.ndarray | None = None) -> list[Fold]:
    """Quarterly folds. A training row is before the test start minus the embargo and its label (label_end_us, or
    its time plus horizon_h) ends before the test start (the purge)."""
    starts = [s for s in quarter_starts(int(ts_us.min()), int(ts_us.max())) if s >= first_test_us]
    end = ts_us + horizon_h * HOUR_US if label_end_us is None else np.asarray(label_end_us)
    folds = []
    for i, s in enumerate(starts):
        e = starts[i + 1] if i + 1 < len(starts) else int(ts_us.max()) + 1
        test = (ts_us >= s) & (ts_us < e)
        if test.sum() == 0:
            continue
        train = (ts_us < s - embargo_h * HOUR_US) & (end < s)
        d = datetime.fromtimestamp(s / 1e6, tz=timezone.utc)
        folds.append(Fold(f"{d.year}Q{(d.month - 1) // 3 + 1}", train, test))
    return folds


@dataclass
class Split:
    name: str
    train: np.ndarray  # boolean masks over the rows
    test: np.ndarray
    groups: tuple      # the test groups


def groups_of(ts: np.ndarray, n_groups: int) -> np.ndarray:
    """The group (0 to n_groups - 1) of every row: the distinct times in order, cut into contiguous groups of
    (nearly) equal count."""
    u = np.unique(ts)
    g = np.empty(len(u), dtype=np.int64)
    for i, part in enumerate(np.array_split(np.arange(len(u)), n_groups)):
        g[part] = i
    return g[np.searchsorted(u, ts)]


def cpcv(ts: np.ndarray, n_groups: int, k_test: int, purge: float = 0, embargo: float = 0,
         label_end: np.ndarray | None = None) -> list[Split]:
    """Every choice of k_test of n_groups contiguous groups as the test set, in itertools order. ts in any unit
    (days, microseconds); purge and embargo in the same unit. A training row is purged when its label, from its
    time to label_end (or its time plus purge), reaches into a test group's span; it is embargoed when it lies
    after a test group's last time by at most `embargo`."""
    ts = np.asarray(ts)
    g = groups_of(ts, n_groups)
    lo = np.array([ts[g == i].min() for i in range(n_groups)])
    hi = np.array([ts[g == i].max() for i in range(n_groups)])
    end = ts + purge if label_end is None else np.asarray(label_end)
    out = []
    for cmb in itertools.combinations(range(n_groups), k_test):
        test = np.isin(g, cmb)
        train = ~test
        for i in cmb:
            train &= ~((ts < lo[i]) & (end >= lo[i]))           # purge: the label reaches into the test group
            train &= ~((ts > hi[i]) & (ts <= hi[i] + embargo))  # embargo after it
        out.append(Split("+".join(map(str, cmb)), train, test, cmb))
    return out


def cpcv_paths(n_groups: int, k_test: int) -> np.ndarray:
    """(splits, groups): the path each split's test group belongs to, -1 where the group trains. Group g is tested
    in C(n-1, k-1) splits; the j-th of them (in split order) fills path j."""
    cmbs = list(itertools.combinations(range(n_groups), k_test))
    out = np.full((len(cmbs), n_groups), -1, dtype=np.int64)
    seen = np.zeros(n_groups, dtype=np.int64)
    for s, cmb in enumerate(cmbs):
        for i in cmb:
            out[s, i] = seen[i]
            seen[i] += 1
    return out


def assemble(splits: list[Split], values: list[np.ndarray], n_groups: int, k_test: int,
             ts: np.ndarray) -> np.ndarray:
    """(paths, rows): every path's out-of-sample value of each row. values[s] holds split s's value of every row
    (only its test rows are read)."""
    paths = cpcv_paths(n_groups, k_test)
    g = groups_of(np.asarray(ts), n_groups)
    out = np.full((paths.max() + 1, len(g)), np.nan)
    for s, sp in enumerate(splits):
        v = np.asarray(values[s], dtype=float)
        for i in sp.groups:
            m = g == i
            out[paths[s, i], m] = v[m]
    return out
