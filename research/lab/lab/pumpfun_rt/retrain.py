"""The daily retrain of the real-time pump.fun models, PAPER ONLY (plan addendum 2).

    python -m lab.pumpfun_rt.retrain               evaluate, select, train, save, post the daily card
    python -m lab.pumpfun_rt.retrain --no-notify   the same without the card
    python -m lab.pumpfun_rt.retrain --dry-run     evaluate and print, save and post nothing

Runs right after the study (jobs.yaml: pumpfun-rt-retrain, depends on
pumpfun-rt-study), on the decision rows the study's replay wrote
(<data>/pumpfun_rt/rows/latest.parquet: every plain token at 3 s to 5 min, the
features known then, every label). Per label (the four registered ones and the
five exit models), a purged walk-forward in time order (folds by decision time,
a training row's label window must end the embargo before its fold starts) of:

  base features, then base plus wallet reputation, then the adopted set plus
  the name categories

A larger set is adopted only when it beats the smaller one out of sample
(model.better). Then each label's model is trained on every row with its
adopted set and saved to <data>/models/pumpfun_rt/, where the shadow book and
the pipeline's filters and exits pick it up within ten minutes.

Y9 (results/pumpfun_select_y9_prereg.md, run_y9): the select models on the study's
label rows (rows/select.parquet), walk-forward by day for reports/pumpfun_rt/select.md,
then on every row for the paper books (sel_<label>.json, sel_policy.json).

Writes reports/pumpfun_rt/models.{md,json} and posts the lab's daily card
(card.py), which needs both the study's report and this one.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

import numpy as np

from .. import report as rep
from . import model as M

EVAL_MAX_ROWS = 1_000_000
NAME = "pumpfun_rt"


def rows_path() -> Path:
    from .store import base
    return base() / "rows" / "latest.parquet"


def save_rows(table: dict[str, np.ndarray], meta: dict, path: Path | None = None) -> Path:
    """The study's decision rows, float32 except the times."""
    import polars as pl
    path = path or rows_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = {k: (v.astype(np.float64) if k in ("t", "created_ms") else v.astype(np.float32)) for k, v in table.items()}
    tmp = path.with_suffix(".tmp")
    pl.DataFrame(cols).write_parquet(tmp, compression="zstd")
    tmp.replace(path)
    path.with_suffix(".json").write_text(json.dumps(meta, default=str), encoding="utf-8")
    return path


def load_rows(path: Path | None = None) -> tuple[dict[str, np.ndarray], dict]:
    import polars as pl
    path = path or rows_path()
    df = pl.read_parquet(path)
    table = {c: df[c].to_numpy().astype(np.float64) for c in df.columns}
    try:
        meta = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        meta = {}
    return table, meta


def run(table: dict[str, np.ndarray], max_rows: int = EVAL_MAX_ROWS, log=print) -> dict:
    sel = {}
    t0 = time.time()
    for label in M.LABELS:
        s = M.select(table, label, max_rows=max_rows)
        sel[label] = s
        ev = s["evals"][s["adopted"]]
        log(f"{NAME} retrain: {label}: {s['adopted']} ({'; '.join(f'{k} {v}' for k, v in s['notes'].items())}); "
            f"{ev.get('verdict', '')}")
    sets = {k: v["features"] for k, v in sel.items()}
    final = M.train_all(table, sets=sets)
    log(f"{NAME} retrain: {sum(v['trials'] for v in sel.values())} evaluations and {len(final)} models in "
        f"{time.time() - t0:.0f} s")
    return {"select": sel, "models": final, "sets": {k: v["adopted"] for k, v in sel.items()},
            "importance": {k: M.importance(m) for k, m in final.items()}, "rows": int(len(table.get("t", [])))}


def summary(res: dict, now_ms: int) -> dict:
    """What the card, the report and the models' meta show."""
    out = {"updated_ms": now_ms, "rows": res["rows"], "labels": {}, "trials": 0}
    for label, s in res["select"].items():
        ev = s["evals"][s["adopted"]]
        pm = (ev.get("pooled") or {}).get("model") or {}
        plg = (ev.get("pooled") or {}).get("logistic") or {}
        base = (s["evals"]["base"].get("pooled") or {}).get("model") or {}
        out["labels"][label] = {"set": s["adopted"], "rows": ev.get("rows"), "folds": len(ev.get("folds", [])),
                                "auc": pm.get("auc"), "auc_base_set": base.get("auc"),
                                "brier_skill": pm.get("brier_skill"), "ece": pm.get("ece"),
                                "logistic_auc": plg.get("auc"), "rate": pm.get("rate"),
                                "useful": bool(ev.get("useful")), "verdict": ev.get("verdict", ""),
                                "notes": s["notes"]}
        out["trials"] += s["trials"]
    out["useful"] = sum(1 for v in out["labels"].values() if v["useful"])
    out["wallet_adopted"] = sum(1 for v in out["labels"].values() if "wallet" in v["set"])
    out["cat_adopted"] = sum(1 for v in out["labels"].values() if "cat" in v["set"])
    return out


def _f(x, fmt="{:.3f}") -> str:
    return "n/a" if x is None or (isinstance(x, float) and not math.isfinite(x)) else fmt.format(x)


def report_md(summ: dict, importance: dict) -> str:
    md = ["# pump.fun real-time lab: models", "",
          "Paper research only. Purged walk-forward by decision time; a feature set is adopted only when it beats "
          "the smaller one out of sample (AUC +0.005 and a lower Brier score in 80 % of the folds).", "",
          f"{summ['rows']:,} decision rows; {summ['trials']} evaluations today; {summ['useful']} of "
          f"{len(summ['labels'])} labels beat their baselines; wallet features adopted for {summ['wallet_adopted']}, "
          f"name categories for {summ['cat_adopted']}.", "",
          "| label | set | rows | folds | AUC | AUC, base set | Brier skill | ECE | logistic AUC | rate | verdict |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for k, v in summ["labels"].items():
        md.append(f"| {k} | {v['set']} | {v['rows']} | {v['folds']} | {_f(v['auc'])} | {_f(v['auc_base_set'])} | "
                  f"{_f(v['brier_skill'], '{:+.3f}')} | {_f(v['ece'])} | {_f(v['logistic_auc'])} | "
                  f"{_f(v['rate'])} | {v['verdict']} |")
    md += ["", "Adoption:"]
    for k, v in summ["labels"].items():
        md.append(f"- {k}: " + "; ".join(f"{n} {w}" for n, w in v["notes"].items()))
    for k, imp in importance.items():
        if imp:
            md.append(f"\n{k} top features (gain): " + ", ".join(f"{f} {g:.2f}" for f, g in imp[:8]))
    return "\n".join(md) + "\n"


def save(res: dict, summ: dict, meta_rows: dict) -> None:
    M.save(res["models"], {"trained_ms": summ["updated_ms"], "rows": res["rows"], "sets": res["sets"],
                           "days": meta_rows.get("days"), "labels": summ["labels"],
                           "features": {k: m.features for k, m in res["models"].items()}})
    d = rep.REPORTS / NAME
    d.mkdir(parents=True, exist_ok=True)
    (d / "models.json").write_text(json.dumps(summ, indent=1, default=str), encoding="utf-8")
    (d / "models.md").write_text(report_md(summ, res["importance"]), encoding="utf-8")


def run_x14(now_ms: int, dry: bool = False, log=print) -> dict | None:
    """X14 (results/pumpfun_early_exit_plan.md): the early detection and exit study on the study's rows, paths
    and steps; then the live models (e_<label>, hz_dump10, hz_up30, hz_policy with the in-sample k*) on all of
    them, saved where the shadow books read them. Returns the card's summary, None without rows."""
    from datetime import datetime, timezone

    from . import early as EA
    from . import exitpol as XP
    try:
        data = EA.load(rows_path().parent)
    except (OSError, ValueError, KeyError) as e:
        log(f"{NAME} retrain: no X14 rows ({type(e).__name__}: {e})")
        return None
    t0 = time.time()
    res = XP.run(data, split_ms=data["meta"].get("split_ms"), log=log)
    day = datetime.fromtimestamp(now_ms / 1000, timezone.utc).strftime("%Y-%m-%d")
    md = XP.report_md(res, day)
    summ = XP.summary(res)
    if dry:
        print(md)
        return summ
    models = XP.fit_live(data, k=(res["exit"]["judge"] or {}).get("k_star") or 1.0, log=log)
    XP.save_models(models, M.model_dir())
    d = rep.REPORTS / NAME
    d.mkdir(parents=True, exist_ok=True)
    (d / "early_exit.json").write_text(json.dumps(XP.jsonable(res), indent=1, default=str), encoding="utf-8")
    (d / "early_exit.md").write_text(md, encoding="utf-8")
    log(f"{NAME} retrain: X14 in {time.time() - t0:.0f} s; exit pick {summ['pick']}, capture out of sample "
        f"{summ['capture_pick']}; peak3x top 5 % precision {summ['prec5_peak3x']}")
    return summ


def run_y9(now_ms: int, dry: bool = False, log=print) -> dict | None:
    """Y9 (results/pumpfun_select_y9_prereg.md): the select models on the study's label rows, walk-forward by day
    (the report) and on every row (the paper books' models, sel_<label>.json and sel_policy.json). None without
    rows."""
    from . import selmodel as SM
    try:
        table, meta = SM.load_rows()
    except Exception as e:                                  # no rows yet
        log(f"{NAME} retrain: no Y9 rows ({type(e).__name__}: {e})")
        return None
    if not len(table.get("t", [])):
        return None
    wf = SM.walk_forward(table)
    models = SM.train(table)
    summ = {"updated_ms": now_ms, "rows": models["sel_rows"], "days": meta.get("days"),
            "models": {k: bool(models["sel_" + k].booster is not None) for k in SM.LABELS},
            "walk_forward": {k: {x: v.get(x) for x in ("n", "rate", "model", "logistic", "ret_all", "ret_top", "n_top",
                                                       "ret_below_base", "n_below_base")}
                             for k, v in wf.items()}}
    md = select_md(summ)
    if dry:
        print(md)
        return summ
    SM.save(models)
    d = rep.REPORTS / NAME
    d.mkdir(parents=True, exist_ok=True)
    (d / "select.json").write_text(json.dumps(summ | {"days_detail": {k: v["days"] for k, v in wf.items()}},
                                              indent=1, default=str), encoding="utf-8")
    (d / "select.md").write_text(md, encoding="utf-8")
    log(f"{NAME} retrain: Y9 select models on {summ['rows']} rows, trained: {summ['models']}")
    return summ


def select_md(summ: dict) -> str:
    md = ["# pump.fun real-time lab: Y9 select models", "",
          "Paper research only. Walk-forward by UTC day (each day tested by a model trained on the days before), "
          "LightGBM against the logistic regression on the same features and the training base rate.", "",
          "| label | rows | out of sample | rate | AUC | logistic AUC | Brier skill | mean return, all | top 30 % | "
          "under the base rate |", "|---|---|---|---|---|---|---|---|---|---|"]
    for k, v in summ["walk_forward"].items():
        pm, plg = v.get("model") or {}, v.get("logistic") or {}
        md.append(f"| {k} | {summ['rows'].get(k, 0)} | {v.get('n') or 0} | {_f(v.get('rate'))} | {_f(pm.get('auc'))} | "
                  f"{_f(plg.get('auc'))} | {_f(pm.get('brier_skill'), '{:+.3f}')} | "
                  f"{_f(v.get('ret_all'), '{:+.3f}')} | "
                  f"{_f(v.get('ret_top'), '{:+.3f}')} ({v.get('n_top') or 0}) | "
                  f"{_f(v.get('ret_below_base'), '{:+.3f}')} ({v.get('n_below_base') or 0}) |")
    return "\n".join(md) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-notify", action="store_true")
    ap.add_argument("--max-rows", type=int, default=EVAL_MAX_ROWS)
    a = ap.parse_args(argv)
    now_ms = int(time.time() * 1000)
    summ = None
    try:
        table, meta = load_rows()
    except (OSError, Exception) as e:                       # no rows yet: the card still goes out
        print(f"{NAME} retrain: no decision rows ({type(e).__name__}: {e})")
        table, meta = None, {}
    if table is not None and len(table.get("t", [])):
        res = run(table, a.max_rows)
        summ = summary(res, now_ms)
        if a.dry_run:
            print(report_md(summ, res["importance"]))
        else:
            save(res, summ, meta)
    try:
        x14 = run_x14(now_ms, dry=a.dry_run)
    except Exception as e:                                  # X14 never stops the card or the other models
        print(f"{NAME} retrain: X14 failed ({type(e).__name__}: {e})")
        x14 = None
    try:
        y9 = run_y9(now_ms, dry=a.dry_run)
    except Exception as e:                                  # Y9 never stops the card or the other models
        print(f"{NAME} retrain: Y9 failed ({type(e).__name__}: {e})")
        y9 = None
    if y9 is not None and summ is not None:
        summ["y9"] = {"rows": y9["rows"], "models": y9["models"]}
    if (x14 is not None or y9 is not None) and summ is not None:
        if x14 is not None:
            summ["x14"] = x14
        if not a.dry_run:
            (rep.REPORTS / NAME / "models.json").write_text(json.dumps(summ, indent=1, default=str), encoding="utf-8")
    if a.dry_run or a.no_notify:
        return 0
    from . import card
    from ..ops import notify
    notify.send("trending", [card.daily_card_now(now_ms, summ, notify.alert_lang())], now=now_ms)
    return 0


if __name__ == "__main__":
    sys.exit(main())
