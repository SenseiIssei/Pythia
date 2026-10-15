"""Champion and challenger: a retrained model replaces the running one only when it is better out of sample.

Layout, under <data>/models/:

  <name>/<version>/                 published models; the engine loads the newest
                                    (vol_1h, picks_7d), as before
  registry/<name>/candidates/<v>/   every challenger a retrain produced, with
                                    holdout.parquet: its walk-forward predictions
                                    and the features of the most recent rows
  registry/<name>/champion.json     the version in force and when it got there
  registry/<name>/decisions.jsonl   one JSON record per decision, promoted or not

The rule. A challenger must first pass its own gate (the volatility model must
beat HAR significantly, M2 must have a rank-IC t of at least 2). Then both
models are scored on the rows the champion never saw (after its training end
plus the label horizon): the champion with its own model file, the challenger
with the walk-forward predictions that produced its out-of-sample numbers.
Those walk-forward models were trained on older data than a recent champion,
which tilts the comparison toward keeping the champion, on purpose. Promotion
needs a margin (MODELS) and a minimum window; anything less keeps the champion.
Without a champion, a challenger that passes its gate is promoted.
"""

from __future__ import annotations

import json
import math
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import numpy as np
import polars as pl

from ..data import ROOT
from . import guard

HOUR_US = 3_600_000_000
DAY_US = 24 * HOUR_US
KEEP_CANDIDATES = 8

# metric: what both models are scored with on the shared window; higher_better;
# margin: how much better the challenger must be (relative for QLIKE, absolute for rank-IC);
# embargo_us: the label horizon after the champion's last training row;
# min_rows / min_days: the smallest window worth a decision.
MODELS = {
    "vol_1h": {"metric": "qlike", "higher_better": False, "margin": 0.01, "relative": True,
               "embargo_us": HOUR_US, "min_rows": 2000, "min_days": 7},
    "picks_7d": {"metric": "rank_ic", "higher_better": True, "margin": 0.005, "relative": False,
                 "embargo_us": 7 * DAY_US, "min_rows": 200, "min_days": 14},
}

# Models registered at run time (the zoo, lab.models): their own gate, score and
# champion predictor. The predictor takes the holdout frame, not a feature matrix.
HOOKS: dict[str, dict] = {}


def register(name: str, cfg: dict, gate_fn: Callable[[Path, dict], tuple[bool, str]],
             score_fn: Callable[[pl.DataFrame, np.ndarray], float],
             predictor_fn: Callable[[Path], Callable[[pl.DataFrame], np.ndarray]]) -> None:
    MODELS[name] = cfg
    HOOKS[name] = {"gate": gate_fn, "score": score_fn, "predictor": predictor_fn}


def published_dir(name: str) -> Path:
    return ROOT / "models" / name


def registry_dir(name: str) -> Path:
    return ROOT / "models" / "registry" / name


def candidates_dir(name: str) -> Path:
    return registry_dir(name) / "candidates"


def latest_version(folder: Path) -> Path | None:
    """The newest version folder with card.json and model.json, the way the engine picks one."""
    if not folder.exists():
        return None
    dirs = sorted(p for p in folder.iterdir() if (p / "card.json").is_file() and (p / "model.json").is_file())
    return dirs[-1] if dirs else None


def read_json(p: Path) -> dict | None:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def champion(name: str) -> dict | None:
    """{version, path, card}: the registry's champion if its folder is still there,
    else the newest published version (the champion before the registry existed)."""
    rec = read_json(registry_dir(name) / "champion.json")
    path = None
    if rec and rec.get("version") and (published_dir(name) / rec["version"] / "card.json").is_file():
        path = published_dir(name) / rec["version"]
    if path is None:
        path = latest_version(published_dir(name))
    if path is None:
        return None
    return {"version": path.name, "path": path, "card": read_json(path / "card.json") or {}}


# ---------------------------------------------------------------- gates and metrics

def gate(name: str, folder: Path, card: dict) -> tuple[bool, str]:
    """The challenger's own bar, before any comparison."""
    if name in HOOKS:
        return HOOKS[name]["gate"](folder, card)
    if name == "vol_1h":
        ch = read_json(folder / "challenger.json") or {}
        if ch.get("passed") is True:
            return True, f"beats HAR by {card.get('qlike_gain_vs_har', 0) * 100:.1f} % QLIKE (DM p {card.get('dm_p_vs_har', 1):.2g})"
        return False, ch.get("why") or "did not pass its own test against HAR"
    if name == "picks_7d":
        oos = card.get("out_of_sample") or {}
        ic, t = oos.get("rank_ic"), oos.get("rank_ic_t")
        if ic is not None and t is not None and ic > 0 and t >= 2:
            return True, f"walk-forward rank-IC {ic:.3f} (t {t:.1f})"
        return False, f"walk-forward rank-IC {ic} (t {t}) below the bar (positive, t >= 2)"
    return False, f"no gate for {name}"


def qlike(target_var: np.ndarray, forecast_var: np.ndarray) -> float:
    r = np.asarray(target_var, float) / np.asarray(forecast_var, float)
    return float(np.mean(r - np.log(r) - 1))


def rank_ic(groups: np.ndarray, target: np.ndarray, score: np.ndarray) -> float:
    df = pl.DataFrame({"g": groups, "t": target, "s": score})
    ics = (df.group_by("g").agg(ic=pl.corr("s", "t", method="spearman"), n=pl.len())
           .filter(pl.col("n") >= 5)["ic"].drop_nulls().drop_nans())
    return float(ics.mean()) if len(ics) else float("nan")


def score(name: str, frame: pl.DataFrame, pred: np.ndarray) -> float:
    if name in HOOKS:
        return HOOKS[name]["score"](frame, pred)
    if name == "vol_1h":
        return qlike(frame["target"].to_numpy(), pred)
    return rank_ic(frame["ts_us"].to_numpy(), frame["target"].to_numpy(), pred)


def predictor(name: str, folder: Path) -> Callable[[np.ndarray], np.ndarray]:
    """The champion's own model file, as the engine would run it."""
    if name in HOOKS:
        return HOOKS[name]["predictor"](folder)
    card = read_json(folder / "card.json") or {}
    if name == "vol_1h":
        rv = float(card.get("residual_var", 0.0))
        if (folder / "model.txt").exists():
            # LightGBM's own file: the same trees as the model.json the engine runs.
            import lightgbm as lgb
            vol = lgb.Booster(model_file=str(folder / "model.txt"))
            return lambda X: np.exp(vol.predict(X.astype(np.float32)) + rv / 2)
        import onnxruntime as ort
        sess = ort.InferenceSession(str(folder / "model.onnx"))
        return lambda X: np.exp(sess.run(None, {"features": X.astype(np.float32)})[0].ravel() + rv / 2)
    import lightgbm as lgb
    booster = lgb.Booster(model_file=str(folder / "model.txt"))
    return lambda X: booster.predict(X.astype(np.float32))


def better(name: str, challenger: float, champ: float) -> bool:
    cfg = MODELS[name]
    if not (math.isfinite(challenger) and math.isfinite(champ)):
        return False
    m = cfg["margin"] * (abs(champ) if cfg["relative"] else 1.0)
    return challenger > champ + m if cfg["higher_better"] else challenger < champ - m


# ---------------------------------------------------------------- the decision

def _record(name: str, rec: dict) -> dict:
    guard.append_jsonl(registry_dir(name) / "decisions.jsonl", [rec])
    return rec


def _promote(name: str, cand: Path, now_ms: int, why: str) -> str:
    version = cand.name
    n = 1
    while (published_dir(name) / version).exists():
        version = f"{cand.name}-{n}"
        n += 1
    current = latest_version(published_dir(name))
    if current is not None and version <= current.name:
        # The engine loads the newest name; a promotion must sort after what is there.
        version = f"{current.name}-{n}"
    guard.copy_tree(cand, published_dir(name) / version, skip=("holdout.parquet", "challenger.json"))
    prev = read_json(registry_dir(name) / "champion.json") or {}
    history = (prev.get("history") or [])[-20:]
    if prev.get("version"):
        history.append({"version": prev["version"], "promoted_ms": prev.get("promoted_ms")})
    guard.write_json(registry_dir(name) / "champion.json",
                     {"model": name, "version": version, "candidate": cand.name, "promoted_ms": now_ms,
                      "why": why, "history": history})
    return version


def decide(name: str, cand: Path, now_ms: int, champion_predict: Callable | None = None) -> dict:
    """Judge one challenger folder against the champion, promote it or not, and record why."""
    cfg = MODELS[name]
    card = read_json(cand / "card.json") or {}
    champ = champion(name)
    base = {"ts_ms": now_ms, "date": datetime.fromtimestamp(now_ms / 1000, timezone.utc).strftime("%Y-%m-%d"),
            "model": name, "candidate": cand.name, "champion": champ["version"] if champ else None,
            "metric": cfg["metric"], "challenger_score": None, "champion_score": None,
            "window_rows": 0, "window_days": 0}
    ok, gate_why = gate(name, cand, card)
    base["gate"] = {"passed": ok, "why": gate_why}
    if not ok:
        return _record(name, {**base, "decision": "rejected", "why": f"fails its own gate: {gate_why}"})
    if champ is None:
        v = _promote(name, cand, now_ms, "first model: passes its gate, no champion to beat")
        return _record(name, {**base, "decision": "promoted", "published": v,
                              "why": f"no champion yet and it passes its gate ({gate_why})"})
    try:
        hold = pl.read_parquet(cand / "holdout.parquet")
    except Exception as e:  # noqa: BLE001 - a missing file is a rejection, not a crash
        return _record(name, {**base, "decision": "rejected", "why": f"no holdout to compare on ({type(e).__name__})"})
    train_to = int(champ["card"].get("train_to_us") or 0)
    win = hold.filter(pl.col("ts_us") > train_to + cfg["embargo_us"]).drop_nulls(["target", "challenger"])
    days = win["ts_us"].n_unique() if name == "picks_7d" else int(
        (win["ts_us"].max() - win["ts_us"].min()) / DAY_US) + 1 if win.height else 0
    base["window_rows"], base["window_days"] = win.height, int(days)
    if win.height < cfg["min_rows"] or days < cfg["min_days"]:
        return _record(name, {**base, "decision": "kept",
                              "why": f"only {win.height} rows over {days} days the champion never saw "
                                     f"(needs {cfg['min_rows']} rows and {cfg['min_days']} days); champion stays"})
    feats = champ["card"].get("features") or []
    missing = [f for f in feats if f not in win.columns]
    if missing:
        return _record(name, {**base, "decision": "kept",
                              "why": f"the champion's features are not in the holdout ({', '.join(missing[:5])}); champion stays"})
    try:
        fn = champion_predict or predictor(name, champ["path"])
        arg = win if name in HOOKS else win.select(feats).to_numpy().astype(np.float32)
        champ_pred = np.asarray(fn(arg), float)
    except Exception as e:  # noqa: BLE001
        return _record(name, {**base, "decision": "kept", "why": f"champion could not be scored ({type(e).__name__}: {e})"})
    s_ch = score(name, win, win["challenger"].to_numpy())
    s_cp = score(name, win, champ_pred)
    base["challenger_score"], base["champion_score"] = s_ch, s_cp
    word = "lower" if not cfg["higher_better"] else "higher"
    if better(name, s_ch, s_cp):
        why = (f"{cfg['metric']} {s_ch:.4f} vs champion {s_cp:.4f} on {win.height} rows over {days} days "
               f"the champion never saw ({word} is better, margin {cfg['margin']:g})")
        v = _promote(name, cand, now_ms, why)
        return _record(name, {**base, "decision": "promoted", "published": v, "why": why})
    return _record(name, {**base, "decision": "rejected",
                          "why": f"{cfg['metric']} {s_ch:.4f} vs champion {s_cp:.4f} on {win.height} rows over "
                                 f"{days} days: not better by the margin ({word} is better, {cfg['margin']:g})"})


def newest_candidate(name: str, since_ms: int = 0) -> Path | None:
    """The candidate folder a retrain just wrote (card.json newer than since_ms)."""
    root = candidates_dir(name)
    if not root.exists():
        return None
    cards = [p for p in root.rglob("card.json") if p.stat().st_mtime * 1000 >= since_ms]
    return max(cards, key=lambda p: p.stat().st_mtime).parent if cards else None


def prune_candidates(name: str, keep: int = KEEP_CANDIDATES) -> None:
    root = candidates_dir(name)
    if not root.exists():
        return
    dirs = sorted((p.parent for p in root.rglob("card.json")), key=lambda p: p.stat().st_mtime)
    for d in dirs[:-keep]:
        guard.check_write(d)
        shutil.rmtree(d, ignore_errors=True)
