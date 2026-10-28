"""T1: the leak harness. No number in the lab may come from the future, checked by a machine, not by reading code.

check(fn, data) runs a function from a panel (or a frame of rows with a known-at time column) to outputs per time
on the full data and on copies where every value after t is replaced, for a sample of t (freqtrade's lookahead and
recursive analysis, G1's scrambled bars made a harness everything uses):

  look-ahead  every row after t shuffled in time, shifted (rolled) in time, or set missing (NaN for floats, a
              flipped bool, a null in a frame); any output at or before t that moves is a leak
  recursive   the data cut at t (rows after t dropped): every output at or before t equals the full run's

The input:
  a panel     an array with time on the first axis, a dict, tuple or dataclass of them (fam_common.Panel,
              factory.build.Ctx): every array whose first axis is the panel's length T is time (T from a
              `days` field when there is one); names in KEEP are cut but never changed (the time index, the
              column lists), names in SKIP are left alone (caches: a function must not read a cache of the
              full run, pass it fresh)
  a frame     a polars DataFrame, or a dict of them, each with the column `time` (when a row is known, in
              the same unit as the cuts); every numeric column but the keys is changed in the rows after t
The output: an array (T, ...) or a dict or tuple of them in panel mode; in frame mode a DataFrame with the column
`out_time` (default: `time`) and key columns (its non-numeric ones and `keys`), rows matched on them. The cuts of
a dict of frames fall where all of them have rows.

A function that raises on a changed copy could not be checked: reported as not ok ("error"), never as a pass.
The result is a plain dict (JSON): ok, the leaks found (kind, cut, first moved time, column), the first of them.
Kind adapters (factory genomes, features, zoo builders, G2 specs, paper books) are in checks.py; the weekly job
(python -m lab.leak) is __main__.py.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime, timezone

import numpy as np
import polars as pl

KINDS = ("shuffle", "shift", "nan")
KEEP = frozenset({"days", "names", "bases", "cols", "ts_us", "day", "date", "end_us", "open_time_us", "close_time_us",
                  "known_us", "funding_time_us", "asset", "symbol", "btc"})
SKIP = frozenset({"memo"})
RTOL = 1e-9
N_CUTS = 4
LO, HI = 0.5, 0.95                      # cuts between these quantiles of the time range


def when(v) -> str:
    """A time for the report: microseconds as a UTC date (and hour when not midnight), anything else as is."""
    if isinstance(v, (int, np.integer)) and abs(int(v)) > 10 ** 14:
        d = datetime.fromtimestamp(int(v) / 1e6, timezone.utc)
        return d.strftime("%Y-%m-%d" if d.hour == 0 and d.minute == 0 else "%Y-%m-%d %H:%M")
    if isinstance(v, np.datetime64):
        return str(v.astype("datetime64[D]"))
    return str(v)


# ---------------------------------------------------------------- panels

def _length(data) -> int | None:
    """T of a panel: its `days` when it has them, else the first axis of the first array found."""
    days = data.get("days") if isinstance(data, dict) else getattr(data, "days", None)
    if isinstance(days, np.ndarray):
        return len(days)
    if isinstance(data, np.ndarray):
        return data.shape[0]
    for x in _children(data):
        n = _length(x)
        if n is not None:
            return n
    return None


def _children(data) -> list:
    if isinstance(data, dict):
        return [v for k, v in data.items() if k not in SKIP]
    if isinstance(data, (list, tuple)):
        return list(data)
    if dataclasses.is_dataclass(data) and not isinstance(data, type):
        return [getattr(data, f.name) for f in dataclasses.fields(data) if f.name not in SKIP]
    return []


def _map(data, fn, T: int, name: str = ""):
    """data with every time array x replaced by fn(x, name); the rest (and SKIP) as it is."""
    if isinstance(data, np.ndarray):
        return fn(data, name) if data.ndim and data.shape[0] == T else data
    if isinstance(data, dict):
        return {k: v if k in SKIP else _map(v, fn, T, k) for k, v in data.items()}
    if isinstance(data, tuple):
        return tuple(_map(v, fn, T, name) for v in data)
    if isinstance(data, list) and any(isinstance(v, np.ndarray) for v in data):
        return [_map(v, fn, T, name) for v in data]
    if dataclasses.is_dataclass(data) and not isinstance(data, type):
        ch = {f.name: _map(getattr(data, f.name), fn, T, f.name) for f in dataclasses.fields(data)
              if f.init and f.name not in SKIP}
        return dataclasses.replace(data, **ch)
    return data


def _tail(x: np.ndarray, t: int, kind: str, rng: np.random.Generator) -> np.ndarray:
    """x with every row after t replaced."""
    x = x.copy()
    n = len(x) - t - 1
    if n <= 0:
        return x
    if kind == "shuffle":
        x[t + 1:] = x[t + 1:][rng.permutation(n)]
    elif kind == "shift":
        x[t + 1:] = np.roll(x[t + 1:], int(rng.integers(1, n)) if n > 1 else 0, axis=0)
    elif x.dtype == bool:
        x[t + 1:] = ~x[t + 1:]
    elif np.issubdtype(x.dtype, np.floating):
        x[t + 1:] = np.nan
    elif np.issubdtype(x.dtype, np.integer):
        x[t + 1:] = 0
    return x


def perturb_panel(data, t: int, kind: str, seed: int = 0, T: int | None = None):
    T = T or _length(data)
    rng = np.random.default_rng(seed)
    return _map(data, lambda x, name: x if name in KEEP else _tail(x, t, kind, rng), T)


def cut_panel(data, t: int, T: int | None = None):
    T = T or _length(data)
    return _map(data, lambda x, name: x[: t + 1], T)


def _outputs(out, T: int | None = None) -> dict[str, np.ndarray]:
    """A function's output as name -> array with time first."""
    if isinstance(out, dict):
        return {str(k): np.asarray(v) for k, v in out.items() if isinstance(v, np.ndarray) or np.ndim(v)}
    if isinstance(out, tuple):
        return {str(i): np.asarray(v) for i, v in enumerate(out)}
    return {"": np.asarray(out)}


def _differ(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Bool per element: a and b differ (NaN equals NaN, a relative tolerance)."""
    if a.dtype.kind in "fc" or b.dtype.kind in "fc":
        a, b = a.astype(float), b.astype(float)
        with np.errstate(invalid="ignore"):
            same = (a == b) | (np.isnan(a) & np.isnan(b)) | np.isclose(a, b, rtol=RTOL, atol=0.0)
        return ~same
    return a != b


def _first_panel(base: dict, other: dict, t: int, columns=None) -> tuple[int, str] | None:
    """(first row at or before t that moved, its column) or None."""
    found = None
    for k, a in base.items():
        b = other.get(k)
        if b is None or b.shape[1:] != a.shape[1:] or len(b) < t + 1:
            return 0, k or "(shape)"
        d = _differ(a[: t + 1], b[: t + 1]).reshape(t + 1, -1)
        rows = np.flatnonzero(d.any(1))
        if rows.size and (found is None or rows[0] < found[0]):
            j = int(np.flatnonzero(d[rows[0]])[0])
            col = columns[j] if columns is not None and a.ndim == 2 and j < len(columns) else (str(j) if a.ndim > 1 else "")
            found = (int(rows[0]), ":".join(x for x in (k, col) if x) or "(value)")
    return found


# ---------------------------------------------------------------- frames

def _frames(data) -> dict[str, pl.DataFrame] | None:
    if isinstance(data, pl.DataFrame):
        return {"": data}
    if isinstance(data, dict) and data and all(isinstance(v, pl.DataFrame) for v in data.values()):
        return data
    return None


def _changeable(df: pl.DataFrame, time: str, keys=()) -> list[str]:
    return [c for c, d in df.schema.items() if d.is_numeric() and c != time and c not in KEEP and c not in keys]


def perturb_frame(df: pl.DataFrame, t, kind: str, time: str, seed: int = 0, keys=()) -> pl.DataFrame:
    """The rows known after t changed (their keys and time kept)."""
    after = (df[time] > t).fill_null(False).to_numpy()
    idx = np.flatnonzero(after)
    if not idx.size:
        return df
    rng = np.random.default_rng(seed)
    n = idx.size
    src = idx[rng.permutation(n)] if kind == "shuffle" else \
        idx[np.roll(np.arange(n), int(rng.integers(1, n)) if n > 1 else 0)] if kind == "shift" else None
    mask = pl.Series(after)
    out = []
    for c in _changeable(df, time, keys):
        s = df[c]
        if src is not None:
            v = s.cast(pl.Float64).to_numpy().copy()
            v[idx] = v[src]
            fill = pl.Series(c, v)
            fill = (fill.fill_nan(None) if s.null_count() else fill).cast(s.dtype, strict=False)
        else:
            fill = pl.lit(float("nan")) if s.dtype.is_float() else pl.lit(None)
        out.append(pl.when(mask).then(fill).otherwise(pl.col(c)).cast(s.dtype).alias(c))
    return df.with_columns(out)


def _keys(df: pl.DataFrame, out_time: str, keys=()) -> list[str]:
    return [out_time] + [c for c, d in df.schema.items() if c != out_time and (c in keys or not d.is_numeric())]


def _first_frame(base: pl.DataFrame, other: pl.DataFrame, t, out_time: str, keys=()) -> tuple | None:
    """(first out time at or before t whose row moved, its column) or None."""
    a = base.filter(pl.col(out_time) <= t)
    b = other.filter(pl.col(out_time) <= t) if out_time in other.columns else other.clear()
    ks = _keys(a, out_time, keys)
    if a.height != b.height or set(b.columns) != set(a.columns):
        both = a.select(ks).join(b.select(ks), on=ks, how="anti") if set(ks) <= set(b.columns) else a.select(ks)
        first = both[out_time].min() if both.height else (b[out_time].min() if b.height else t)
        return first, "(rows)"
    vals = [c for c in a.columns if c not in ks]
    a, b = a.sort(ks), b.sort(ks)
    if not a.select(ks).equals(b.select(ks)):
        d = a.select(ks).with_row_index("_i").join(b.select(ks), on=ks, how="anti")
        return (d[out_time].min() if d.height else a[out_time].min()), "(rows)"
    tm = a[out_time].to_numpy()
    found = None
    for c in vals:
        x, y = a[c], b[c]
        if x.dtype.is_numeric() and y.dtype.is_numeric():
            d = _differ(x.cast(pl.Float64).fill_null(np.nan).to_numpy(), y.cast(pl.Float64).fill_null(np.nan).to_numpy())
        else:
            d = (x != y).fill_null(True).to_numpy() & ~(x.is_null() & y.is_null()).to_numpy()
        if d.any():
            f = tm[d].min()
            if found is None or f < found[0]:
                found = (f, c)
    return found


# ---------------------------------------------------------------- the check

def _cuts(times: np.ndarray, n: int) -> list:
    u = np.unique(times)
    if len(u) < 3:
        return []
    qs = np.linspace(LO, HI, n) if n > 1 else np.array([LO])
    return sorted({u[min(int(q * (len(u) - 1)), len(u) - 2)].item() for q in qs})


def check(fn, data, *, time: str = "known_us", out_time: str | None = None, keys=(), cuts=None, n_cuts: int = N_CUTS,
          kinds=KINDS, recursive: bool = True, seed: int = 0, columns=None, labels=None, name: str = "") -> dict:
    """Run fn on data and on each changed copy; see the module's doc. cuts: row indices (panel) or times (frame),
    default n_cuts between the 50 % and 95 % quantiles. columns: names of an output's second axis (panel mode);
    labels: the time of each panel row for the report (default: the panel's days)."""
    frames = _frames(data)
    res = {"name": name, "ok": True, "runs": 0, "cuts": [], "leaks": [], "first": None, "error": None}
    out_time = out_time or time
    try:
        base = fn(data)
    except Exception as e:      # noqa: BLE001 (a function that cannot run on its own data is not checked)
        res.update(ok=False, error=f"{type(e).__name__}: {e}"[:300])
        return res
    if frames is None:
        T = _length(data)
        labels = labels if labels is not None else (data.get("days") if isinstance(data, dict)
                                                     else getattr(data, "days", None))
        base_o = _outputs(base)
        cuts = list(cuts) if cuts is not None else _cuts(np.arange(T or 0), n_cuts)
        lab = (lambda i: when(labels[i]) if labels is not None and 0 <= i < len(labels) else str(i))  # noqa: E731
    else:
        ts = [f[time].drop_nulls().to_numpy() for f in frames.values() if f.height]
        allt = np.concatenate(ts) if ts else np.array([])
        if ts:                            # where every input has rows: a cut before one starts checks nothing
            allt = allt[(allt >= max(x.min() for x in ts)) & (allt <= min(x.max() for x in ts))]
        cuts = list(cuts) if cuts is not None else _cuts(allt, n_cuts)
        lab = when
    res["cuts"] = [lab(c) for c in cuts]
    for i, t in enumerate(cuts):
        for kind in list(kinds) + (["recursive"] if recursive else []):
            try:
                if frames is None:
                    x = cut_panel(data, t, T) if kind == "recursive" else perturb_panel(data, t, kind, seed + i, T)
                    moved = _first_panel(base_o, _outputs(fn(x)), t, columns)
                else:
                    x = {k: (f.filter(pl.col(time) <= t) if kind == "recursive"
                             else perturb_frame(f, t, kind, time, seed + i, keys)) for k, f in frames.items()}
                    out = fn(x[""] if isinstance(data, pl.DataFrame) else x)
                    moved = _first_frame(base, out, t, out_time, keys)
            except Exception as e:      # noqa: BLE001
                res["leaks"].append({"kind": kind, "cut": lab(t), "first": None, "column": "(error)",
                                     "error": f"{type(e).__name__}: {e}"[:200]})
                res["runs"] += 1
                continue
            res["runs"] += 1
            if moved is not None:
                res["leaks"].append({"kind": kind, "cut": lab(t), "first": lab(moved[0]), "column": moved[1]})
        if res["leaks"]:
            break                         # the first t that shows one is the answer
    if res["leaks"]:
        real = [x for x in res["leaks"] if x["column"] != "(error)"]
        res["ok"] = False
        res["first"] = (real or res["leaks"])[0]
        if not real:
            res["error"] = res["leaks"][0]["error"]
    return res


def reason(res: dict) -> str:
    """One line for a log, a ledger or the report."""
    if res["ok"]:
        return f"no leak ({res['runs']} runs at {', '.join(res['cuts'])})"
    f = res["first"]
    if f is not None and f["kind"] == "builder":
        return f"leak: reads {f['column']}, which the weekly leak check found leaking"
    if f is None or f["column"] == "(error)":
        return "could not check: " + (res.get("error") or (f or {}).get("error") or "no output")
    kinds = sorted({x["kind"] for x in res["leaks"] if x["column"] != "(error)"})
    return f"leak: {f['column']} at {f['first']} moves when the data after {f['cut']} changes ({', '.join(kinds)})"
