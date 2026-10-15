"""The model zoo's one cron entry point: retrain what is due, judge, shadow-score, watch drift, report.

  python -m lab.models.train --due              the daily run: retrain the zoo models that are due,
                                                then shadow forecasts, scores, drift and the report
  python -m lab.models.train --force m8,m12     retrain these now, whatever the schedule
  python -m lab.models.train --status           no retraining: shadow, drift and the report only
  python -m lab.models.train --list             print every model's spec
  --no-notify                                   do not post promotions and drift

Per zoo model (M8, M8q, M10, M11, M12), every run:

  1. load its real data (a model whose data is not there yet is "waiting for
     data" and says why; M11 waits for enough demo fills)
  2. when due (or forced): walk-forward evaluation against its baseline, a
     challenger folder under models/registry/<name>/candidates/, and the
     champion/challenger decision of lab.ops.registry: a challenger that fails
     its own gate is never promoted; one that passes replaces the champion
     only if it is better on rows the champion never saw
  3. live shadow: the champion (or, without one, the newest candidate, marked
     as such) writes down its forecast for the newest day before the outcome
     is known, into models/zoo/<name>/shadow.jsonl; recorded forecasts whose
     outcome is now known are scored against the baseline
  4. drift: the last 30 days of each input against the training deciles,
     with the engine's rules (pythia-ml drift.rs)

M1 and M2 are retrained by the nightly learning loop; M7 is retired. The
report covers them all: reports/models/latest.json (the Models page and,
through its lab feed header, docs/LAB-FEEDS.md, Home and Research) and
latest.md. A promotion, or a model whose inputs move outside their trained
range, is posted to the operator's channel (Telegram or webhook, as
lab.ops.notify), once per event.

Writes only through lab.ops.guard: models/zoo, models/registry, the zoo's
published model folders and reports/models. It reads the engine's demo
fills only from the learning loop's ledger. It cannot trade or change a book.
"""

from __future__ import annotations

import json
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .. import report
from ..data import ROOT
from ..ops import guard, i18n, notify, registry
from . import core, zoo
from .core import DAY_MS, DataUnavailable

NAME = "models"
HISTORY_DECISIONS = 12


def zoo_dir() -> Path:
    return ROOT / "models" / "zoo"


def _date(ms: int | None) -> str | None:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d") if ms else None


def _read(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------- schedule

def due(spec: core.Spec, st: dict, now_ms: int) -> tuple[bool, str]:
    if spec.every_days <= 0:
        return False, "not retrained here"
    s = st.get("models", {}).get(spec.name, {})
    ok, tried = s.get("last_success_ms"), s.get("last_attempt_ms")
    if tried and now_ms - tried < 20 * 3_600_000:
        return False, "tried less than a day ago"
    if ok and now_ms - ok < spec.every_days * DAY_MS - 12 * 3_600_000:
        return False, f"next after {_date(ok + spec.every_days * DAY_MS)}"
    if spec.weekday is not None and ok and datetime.fromtimestamp(now_ms / 1000, timezone.utc).weekday() != spec.weekday:
        return False, "waits for its weekday"
    return True, "due" if ok else "never trained"


def next_due(spec: core.Spec, st: dict) -> str | None:
    if spec.every_days <= 0:
        return None
    ok = st.get("models", {}).get(spec.name, {}).get("last_success_ms")
    return _date(ok + spec.every_days * DAY_MS) if ok else "next run"


def mark(st: dict, name: str, now_ms: int, ok: bool, detail: str) -> None:
    s = st.setdefault("models", {}).setdefault(name, {})
    s["last_attempt_ms"] = now_ms
    s["last_status"] = "ok" if ok else "failed"
    s["last_detail"] = detail[:500]
    if ok:
        s["last_success_ms"] = now_ms


# ---------------------------------------------------------------- one zoo model

def retrain(mod, panel, now_ms: int) -> dict:
    """Evaluate, write a challenger, let the registry decide. Returns the decision record."""
    ev = core.evaluate(mod, panel)
    cand = registry.candidates_dir(mod.SPEC.name) / core.version_name(now_ms)
    guard.check_write(cand)
    core.write_candidate(mod, ev, cand, now_ms)
    guard.WRITTEN.append(str(cand))
    rec = registry.decide(mod.SPEC.name, cand, now_ms)
    registry.prune_candidates(mod.SPEC.name)
    return rec


def decisions(name: str, n: int = HISTORY_DECISIONS) -> list[dict]:
    rows = core.read_jsonl(registry.registry_dir(name) / "decisions.jsonl")[-n:]
    return [{k: r.get(k) for k in ("date", "candidate", "champion", "decision", "challenger_score", "champion_score",
                                   "window_rows", "why", "published")} for r in rows]


def model_folder(name: str) -> tuple[Path | None, str]:
    """The model to shadow-score: the champion, else the newest candidate."""
    ch = registry.champion(name)
    if ch:
        return ch["path"], "champion"
    cand = registry.newest_candidate(name)
    if cand is not None and (cand / "model.json").exists():
        return cand, "candidate"
    return None, "none"


def shadow(mod, folder: Path, role: str, panel, now_ms: int) -> dict:
    p = zoo_dir() / mod.SPEC.name / "shadow.jsonl"
    rows = core.read_jsonl(p)
    have = {(int(r["ts_us"]), str(r["symbol"])) for r in rows if "ts_us" in r}
    fitted = mod.restore(folder)
    new = core.shadow_forecasts(mod, fitted, panel, folder.name, now_ms, have)
    if new:
        for r in new:
            r["role"] = role
        rows = (rows + new)[-core.SHADOW_KEEP:]
        guard.write_text(p, "".join(json.dumps(core.finite(r), allow_nan=False) + "\n" for r in rows))
    out = core.shadow_score(mod, rows, panel)
    out["recorded_today"] = len(new)
    return out


def zoo_entry(mod, panel, st: dict, now_ms: int, alerts: list[str], prev_alerts: dict, new_alerts: dict,
              load_error: str | None, retrain_rec: dict | None, infos: list[dict] | None = None) -> dict:
    """One model's entry. Its alerts go to `alerts` in English (the report)
    and, as data for the chat's language, to `infos`."""
    s = mod.SPEC
    e = base_entry(s, st)
    folder, role = model_folder(s.name)
    card = (_read(folder / "card.json") or {}) if folder else {}
    ch = _read(registry.registry_dir(s.name) / "champion.json") or {}
    e["champion"] = ({"version": folder.name, "promoted_ms": ch.get("promoted_ms"), "why": ch.get("why"),
                      "train_to": core.iso(card.get("train_to_us"))} if role == "champion" else None)
    e["shadow_model"] = {"version": folder.name, "role": role} if folder else None
    newest = registry.newest_candidate(s.name)
    ncard = (_read(newest / "card.json") or {}) if newest else {}
    show = ncard or card
    e.update({k: show.get(k) for k in ("model_score", "baseline_score", "gain_pct", "dm_p", "folds_won")})
    e["gate"] = show.get("gate")
    e["folds_total"] = len(show.get("folds") or [])
    e["history"] = [{"label": f.get("fold"), "from": f.get("from"), "model": f.get("model"),
                     "baseline": f.get("baseline"), "rows": f.get("rows")} for f in show.get("folds") or []]
    e["candidate"] = newest.name if newest else None
    e["trained_ms"] = show.get("trained_ms")
    e["extra"] = show.get("extra") or {}
    e["decisions"] = decisions(s.name)
    if retrain_rec:
        e["last_decision"] = {k: retrain_rec.get(k) for k in ("decision", "why", "published")}
    if load_error:
        e["status"], e["status_detail"] = "waiting for data", load_error
    elif role == "champion":
        e["status"] = "in use" if s.used_by else "shadow"
        e["status_detail"] = f"champion {folder.name}; " + ((e["gate"] or {}).get("why") or "")
    elif role == "candidate":
        e["status"] = "failed its gate"
        e["status_detail"] = (f"no champion: the newest challenger {folder.name} did not pass its gate, so nothing "
                              f"may use it; it is still scored in shadow. " + ((show.get("gate") or {}).get("why") or ""))
    else:
        e["status"], e["status_detail"] = "never trained", "no challenger yet"
    if panel is not None and folder is not None:
        try:
            e["live"] = shadow(mod, folder, role, panel, now_ms)
        except Exception as ex:  # noqa: BLE001 - shadow must not stop the report
            e["live"] = {"error": f"{type(ex).__name__}: {ex}"[:300]}
        d = core.drift(card, panel, s.drift_days)
        e["drift"] = d
        if d["level"] == "drift" and prev_alerts.get(s.name, {}).get("drift") != "drift":
            info = {"kind": "drift", "code": s.code, "title": s.title, "why": d["why"], "next": e["next_due"],
                    "worst": [(x["feature"], x["outside_pct"]) for x in d["features"][:3] if x["level"] == "drift"],
                    "n": sum(x["level"] == "drift" for x in d["features"]), "total": len(d["features"]),
                    "days": s.drift_days}
            alerts.append(alert_line(info, "en"))
            if infos is not None:
                infos.append(info)
        new_alerts.setdefault(s.name, {})["drift"] = d["level"]
    if retrain_rec and retrain_rec.get("decision") == "promoted":
        info = {"kind": "promoted", "code": s.code, "title": s.title, "published": retrain_rec.get("published"),
                "why": retrain_rec.get("why")}
        alerts.append(alert_line(info, "en"))
        if infos is not None:
            infos.append(info)
    return e


def alert_line(info: dict, lang: str = "en") -> str:
    """One model alert for the chat, in `lang`. English keeps the lab's own
    reasons; German says the drift with its numbers and translates the gate's."""
    t = i18n.t
    title = i18n.model_title(info["code"], info["title"], lang)
    if info["kind"] == "drift":
        worst = ", ".join(f"{f} {p:.0f} %" for f, p in info["worst"])
        why = (t("md_drift_why", lang, n=info["n"], total=info["total"], days=info["days"]) if lang == "de"
               else info["why"])
        nxt = i18n.iso_day(str(info["next"]), lang) if info.get("next") else info.get("next")
        return t("md_drift", lang, code=info["code"], title=title, worst=worst, why=why, next=nxt)
    return t("md_promoted", lang, code=info["code"], title=title, published=info["published"],
             why=i18n.reason(str(info.get("why") or ""), lang))


def base_entry(s: core.Spec, st: dict) -> dict:
    m = st.get("models", {}).get(s.name, {})
    return {"code": s.code, "name": s.name, "title": s.title, "target": s.target, "horizon": s.horizon,
            "universe": s.universe, "metric": s.metric, "higher_better": s.higher_better, "baseline": s.baseline,
            "managed_by": s.managed_by, "shadow_where": s.shadow, "features": s.features,
            "every_days": s.every_days, "used_by": s.used_by, "use_rule": s.use_rule, "notes": s.status_note,
            "results": s.results, "last_retrain_ms": m.get("last_success_ms"), "last_attempt_ms": m.get("last_attempt_ms"),
            "last_status": m.get("last_status"), "last_detail": m.get("last_detail"), "next_due": next_due(s, st),
            "champion": None, "gate": None, "history": [], "decisions": [], "live": None, "drift": None, "extra": {}}


def learn_entry(s: core.Spec, learn_state: dict) -> dict:
    """M1 and M2: retrained by the learning loop, scored live by the engine."""
    step = "vol" if s.name == "vol_1h" else "m2"
    ls = (learn_state.get("steps") or {}).get(step, {})
    e = base_entry(s, {"models": {s.name: ls}})
    e["next_due"] = _date(ls["last_success_ms"] + s.every_days * DAY_MS) if ls.get("last_success_ms") else "next learning loop"
    ch = registry.champion(s.name)
    e["decisions"] = decisions(s.name)
    if ch:
        c = ch["card"]
        e["champion"] = {"version": ch["version"], "train_to": core.iso(c.get("train_to_us")),
                         "promoted_ms": (_read(registry.registry_dir(s.name) / "champion.json") or {}).get("promoted_ms")}
        if s.name == "vol_1h":
            g = c.get("qlike_gain_vs_har")
            e["gain_pct"] = g * 100 if isinstance(g, (int, float)) else None
            e["dm_p"] = c.get("dm_p_vs_har")
        else:
            oos = c.get("out_of_sample") or {}
            e["model_score"], e["baseline_score"] = oos.get("rank_ic"), 0.0
            e["extra"] = {"rank_ic_t": oos.get("rank_ic_t")}
        e["status"] = "in use" if s.used_by else "shadow"
        e["status_detail"] = f"champion {ch['version']}, retrained by the nightly learning loop, scored live by the engine"
    else:
        e["status"], e["status_detail"] = "not on this machine", f"no published {s.name} under <data>/models"
    e["history"] = [{"label": d["date"], "from": d["date"], "model": d["challenger_score"], "baseline": d["champion_score"]}
                    for d in e["decisions"] if d.get("challenger_score") is not None]
    return e


def retired_entry(s: core.Spec) -> dict:
    e = base_entry(s, {})
    e["status"], e["status_detail"] = "retired", s.status_note
    return e


# ---------------------------------------------------------------- the run

Poster = Callable[[str], tuple[bool, str | None]]


def post_alerts(lines: list[str], poster: Poster | None, infos: list[dict] | None = None,
                lang: str | None = None) -> dict:
    """One message with every alert. With `infos` (the same alerts as data)
    they are said in `lang` (None: the language of the messages)."""
    if not lines:
        return {"sent": 0}
    url, fmt, prefix = notify.config()
    lang = lang or notify.alert_lang()
    if infos and len(infos) == len(lines) and lang != "en":
        lines = [alert_line(i, lang) for i in infos]
    text = notify.clip(i18n.t("md_head", lang, prefix=prefix) + "\n" + "\n".join(f"- {x}" for x in lines), lang=lang)
    if poster is None:
        if url is None:
            print(text)
            return {"sent": 0, "note": "no channel configured, printed only"}
        poster = lambda t: notify.post(url, fmt, t)  # noqa: E731
    ok, err = poster(text)
    return {"sent": len(lines) if ok else 0, "error": err}


def run(now_ms: int | None = None, force: set[str] | None = None, train: bool = True, send: bool = True,
        loaders: dict[str, Callable] | None = None, poster: Poster | None = None) -> dict:
    now_ms = now_ms or int(time.time() * 1000)
    force = {zoo.by_key(k).SPEC.name for k in (force or set())}
    loaders = loaders or {}
    guard.WRITTEN.clear()
    zoo.register_all()
    st_path = zoo_dir() / "state.json"
    st = _read(st_path) or {"models": {}}
    prev_alerts = _read(zoo_dir() / "alerts.json") or {}
    new_alerts: dict = {}
    alerts: list[str] = []
    infos: list[dict] = []
    entries, steps = [], []
    learn_state = _read(ROOT / "learn" / "state.json") or {}
    for s in (zoo.M1, zoo.M2):
        entries.append(learn_entry(s, learn_state))
    entries.append(retired_entry(zoo.M7))
    for mod in zoo.zoo_modules():
        s = mod.SPEC
        panel, err, rec = None, None, None
        try:
            panel = (loaders.get(s.name) or mod.load)()
        except DataUnavailable as e:
            err = str(e)
        except Exception as e:  # noqa: BLE001 - one model's data must not stop the others
            err = f"data failed: {type(e).__name__}: {e}"[:400]
        is_due, why = due(s, st, now_ms)
        if panel is not None and train and (is_due or s.name in force):
            try:
                rec = retrain(mod, panel, now_ms)
                mark(st, s.name, now_ms, True, f"{rec['decision']}: {rec['why']}")
                steps.append({"model": s.code, "step": "retrain", "status": rec["decision"], "detail": rec["why"]})
            except Exception as e:  # noqa: BLE001
                traceback.print_exc()
                mark(st, s.name, now_ms, False, f"{type(e).__name__}: {e}")
                steps.append({"model": s.code, "step": "retrain", "status": "failed", "detail": f"{type(e).__name__}: {e}"[:300]})
        else:
            steps.append({"model": s.code, "step": "retrain", "status": "skipped",
                          "detail": err or ("left out (--status)" if not train else why)})
        try:
            entries.append(zoo_entry(mod, panel, st, now_ms, alerts, prev_alerts, new_alerts, err, rec, infos))
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            x = base_entry(s, st)
            x["status"], x["status_detail"] = "error", f"{type(e).__name__}: {e}"[:300]
            entries.append(x)
    guard.write_json(st_path, st)
    guard.write_json(zoo_dir() / "alerts.json", {**prev_alerts, **new_alerts})
    delivery = post_alerts(alerts, poster, infos) if send else {"sent": 0, "note": "--no-notify"}
    data = core.finite({"generated_ms": now_ms, "generated": datetime.fromtimestamp(now_ms / 1000, timezone.utc)
                        .strftime("%Y-%m-%d %H:%M UTC"), "models": entries, "steps": steps, "alerts": alerts,
                        "delivery": delivery, "specs": [s.public() for s in zoo.all_specs()]})
    data.update(feed(data))
    guard.check_write(report.REPORTS / NAME / "latest.json")
    report.write(NAME, markdown(data), data)
    return data


# ---------------------------------------------------------------- the lab feed header (docs/LAB-FEEDS.md)

def _gain(e: dict) -> str | None:
    g = e.get("gain_pct")
    if isinstance(g, (int, float)):
        return f"{g:+.1f} %"
    m, b = e.get("model_score"), e.get("baseline_score")
    if e.get("higher_better") and isinstance(m, (int, float)) and isinstance(b, (int, float)):
        return f"{m:.3f} vs {b:.3f}"
    return None


def feed(d: dict) -> dict:
    """Title, status, one plain headline and a row per model, for Home and Research."""
    own = [e for e in d["models"] if e["managed_by"] == "zoo"]
    passing = [e for e in own if (e.get("gate") or {}).get("passed")]
    failing = [e for e in own if e.get("gate") and not e["gate"].get("passed")]
    waiting = [e for e in own if e.get("status") == "waiting for data"]
    broken = [e for e in own if e.get("status") == "error" or e.get("last_status") == "failed"]
    drifting = [e for e in d["models"] if (e.get("drift") or {}).get("level") == "drift"]
    promoted = [s for s in d["steps"] if s.get("status") == "promoted"]
    codes = lambda xs: ", ".join(x["code"] for x in xs)  # noqa: E731
    parts = [f"{len(passing)} of {len(own)} zoo models beat their baseline out of sample"
             + (f" ({codes(passing)})" if passing else "")]
    if failing:
        parts.append(f"{codes(failing)} do not, so nothing uses them" if len(failing) > 1
                     else f"{codes(failing)} does not, so nothing uses it")
    if waiting:
        parts.append(f"{codes(waiting)} waits for data")
    head = "; ".join(parts) + "."
    if promoted:
        head += f" Promoted today: {', '.join(s['model'] for s in promoted)}."
    if drifting:
        head += f" Inputs outside the trained range: {codes(drifting)}."
    status = "bad" if broken or drifting else "watch" if promoted or waiting else "ok"
    items = []
    for e in d["models"]:
        lvl = (e.get("drift") or {}).get("level")
        passed = (e.get("gate") or {}).get("passed")
        # A shift (inputs spread differently, inside the trained range) is normal for one month: no colour.
        st = ("bad" if lvl == "drift" or e.get("status") == "error" else
              "watch" if e.get("status") == "waiting for data" else
              "ok" if passed or e.get("status") in ("in use", "shadow") else None)
        was_promoted = any(s.get("model") == e["code"] and s.get("status") == "promoted" for s in d["steps"])
        imp = 75 if lvl == "drift" else 70 if was_promoted else 30 if passed else 10
        items.append({"label": f"{e['code']} {e['title']}", "value": _gain(e) or e.get("status"), "status": st,
                      "detail": f"{e.get('status')}; vs {e['baseline']}"[:240], "importance": imp,
                      "link": "study:model_zoo"})
    return report.feed_header("Models", status, head, items, updated_ms=d["generated_ms"])


# ---------------------------------------------------------------- the report

def _n(v, nd=4) -> str:
    return "n/a" if v is None else f"{v:.{nd}f}" if isinstance(v, float) else str(v)


def markdown(d: dict) -> str:
    lines = ["# Model zoo\n", f"{d['generated']}. Every model, its score against its baseline, its last retrain, "
             "drift and who uses it. Generated by `python -m lab.models.train`.\n",
             "| Model | Status | Metric | Model | Baseline | Gain | DM p | Live (rows, gain) | Drift | Last retrain | Used by |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for e in d["models"]:
        live = e.get("live") or {}
        lv = f"{live.get('rows', 0)}, {_n(live.get('gain_pct'), 1)} %" if live.get("rows") else "n/a"
        gain = _n(e.get("gain_pct"), 1) + " %" if e.get("gain_pct") is not None else "n/a"
        lines.append(f"| {e['code']} {e['title']} | {e.get('status')} | {e['metric']} | {_n(e.get('model_score'))} | "
                     f"{_n(e.get('baseline_score'))} | {gain} | {_n(e.get('dm_p'), 3)} | {lv} | "
                     f"{(e.get('drift') or {}).get('level', 'n/a')} | {_date(e.get('last_retrain_ms')) or 'never'} | "
                     f"{', '.join(e.get('used_by') or []) or 'none'} |")
    lines.append("")
    for e in d["models"]:
        lines.append(f"## {e['code']} {e['title']}\n")
        lines.append(f"Target: {e['target']}. Horizon: {e['horizon']}. Universe: {e['universe']}. "
                     f"Baseline: {e['baseline']}.\n")
        lines.append(f"Status: **{e.get('status')}**. {e.get('status_detail') or ''}\n")
        if e.get("gate"):
            lines.append(f"Gate: {'passed' if e['gate'].get('passed') else 'failed'}. {e['gate'].get('why')}\n")
        if e.get("history") and e["managed_by"] == "zoo":
            lines.append(report.table(e["history"], ["label", "from", "rows", "model", "baseline"]))
        ex = e.get("extra") or {}
        if ex:
            keep = {k: v for k, v in ex.items() if not isinstance(v, (list, dict))}
            if keep:
                lines.append("Secondary: " + ", ".join(f"{k} {_n(v) if isinstance(v, float) else v}" for k, v in keep.items()) + ".\n")
        if e.get("use_rule"):
            lines.append(f"Use: {e['use_rule']}\n")
    lines.append("## This run\n")
    lines.append(report.table(d["steps"], ["model", "step", "status", "detail"]))
    lines.append(f"Alerts: {len(d['alerts'])} ({d['delivery'].get('sent', 0)} delivered).\n")
    return "\n".join(lines) + "\n"


def _names(flag: str) -> set[str]:
    out = set()
    for i, a in enumerate(sys.argv):
        if a == flag and i + 1 < len(sys.argv):
            out |= {x.strip() for x in sys.argv[i + 1].split(",") if x.strip()}
    for k in out:
        try:
            zoo.by_key(k)
        except KeyError:
            raise SystemExit(f"unknown model {k}; zoo models are {list(zoo.ZOO_MODULES)}")
    return out


def main() -> int:
    if "--list" in sys.argv:
        for s in zoo.all_specs():
            print(json.dumps(s.public(), indent=2))
        return 0
    train = "--status" not in sys.argv
    if train and "--due" not in sys.argv and "--force" not in sys.argv:
        raise SystemExit(__doc__)
    run(force=_names("--force"), train=train, send="--no-notify" not in sys.argv)
    return 0


if __name__ == "__main__":
    sys.exit(main())
