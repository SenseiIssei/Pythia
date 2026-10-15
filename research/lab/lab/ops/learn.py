"""The learning loop: every night after the forward report, learn from what traded and keep what is better.

Runs at 06:30 UTC, after lab.paper.forward_report (06:15). Each step is
isolated: one failing step is reported in the digest and the others still run.

  costs     read the autopilot engine's demo orders (GET /api/state, or an
            exported file), keep the finished ones in <data>/learn/fills.jsonl
            and write <data>/costs/learned.json: the base cost table plus a
            measured section, with a symbol's spread and impact scaled only
            once it has 30 market fills (lab.ops.fills)
  evidence  snapshot the forward report's evidence.json into
            <data>/learn/evidence_history.jsonl and say, per paper book and
            autopilot, how long it has held its status and what changed
  sweep     monthly: re-run the strategy-family sweep on fresh data in a
            staging folder, check it, publish its reports and run caches and
            say which gates flipped
  vol       weekly (Sundays): retrain the volatility model as a challenger,
            promote it only if better out of sample (lab.ops.registry)
  m2        monthly: the same for M2 (picks_7d)
  digest    reports/learn/latest.md and latest.json (plus dated copies): what
            changed, what was promoted or rejected and why, and each
            autopilot's P&L against BTC

What it can never do (lab.ops.guard): write outside its own folders, the
learned cost file, the model registry and the published model folders; call
the engine for anything but GET /api/state; change a fee, a venue default or a
symbol the base cost table does not list. It cannot change live settings, arm
live, move money or touch a risk limit, because none of those are reachable
from here: they live in the engine's state and settings, which it only reads.

  python -m lab.ops.learn                    the nightly run, steps when due
  python -m lab.ops.learn --force vol,m2     run these now whatever the schedule
  python -m lab.ops.learn --skip sweep       leave these out tonight
  python -m lab.ops.learn --no-train         costs, evidence and digest only

Environment: PYTHIA_AUTOPILOT_STATE_URLS (every autopilot engine, comma
separated, default the main account on 8788 and the safe account on 8789; the
costs come from the first, the digest lists the autopilots of all that
answer), PYTHIA_AUTOPILOT_STATE_URL (the old single engine when the list is
not set, "off" skips the engine), PYTHIA_LEARN_ORDERS_FILE (an exported /api/state or
orders file, read instead of the engine), PYTHIA_COSTS_BASE (the base cost
table, default <data>/costs/base.json), PYTHIA_AGENT_OUT (where the sweep's
published reports live, as for the paper books).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .. import report
from ..data import ROOT
from . import fills, guard, i18n, registry

NAME = "learn"
DAY_MS = 86_400_000
DEFAULT_STATE_URL = "http://127.0.0.1:8788/api/state"
STEPS = ["costs", "evidence", "sweep", "vol", "m2"]
HEAVY = {"sweep", "vol", "m2"}
# period in days, and an optional weekday (Monday 0 .. Sunday 6) the step waits for
SCHEDULE = {"sweep": (28, None), "vol": (7, 6), "m2": (28, None)}
TIMEOUT_S = {"sweep": 3 * 3600, "vol": 4 * 3600, "m2": 3 * 3600}
HISTORY_KEEP = 400


def learn_dir() -> Path:
    return ROOT / "learn"


def out_dir() -> Path:
    """Where the sweep's published reports and run caches live (fam_common.OUT)."""
    return Path(os.environ.get("PYTHIA_AGENT_OUT", str(ROOT / "agent-strategies")))


def _date(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d")


def _read_json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------- schedule

def load_state() -> dict:
    return _read_json(learn_dir() / "state.json") or {"steps": {}}


def due(step: str, state: dict, now_ms: int) -> tuple[bool, str]:
    if step not in SCHEDULE:
        return True, "nightly"
    period, weekday = SCHEDULE[step]
    s = state.get("steps", {}).get(step, {})
    last_ok, last_try = s.get("last_success_ms"), s.get("last_attempt_ms")
    if last_try and now_ms - last_try < 20 * 3_600_000:
        return False, "tried less than a day ago"
    if last_ok and now_ms - last_ok < period * DAY_MS - 12 * 3_600_000:
        return False, f"next after {_date(last_ok + period * DAY_MS)}"
    if weekday is not None and datetime.fromtimestamp(now_ms / 1000, timezone.utc).weekday() != weekday and last_ok:
        return False, "waits for its weekday"
    return True, "due" if last_ok else "never run"


def mark(state: dict, step: str, now_ms: int, ok: bool, detail: str) -> None:
    s = state.setdefault("steps", {}).setdefault(step, {})
    s["last_attempt_ms"] = now_ms
    s["last_status"] = "ok" if ok else "failed"
    s["last_detail"] = detail[:500]
    if ok:
        s["last_success_ms"] = now_ms


# ---------------------------------------------------------------- the engine, read only

def fetch_state(url: str, timeout: float = 15) -> tuple[dict | None, str | None]:
    if url.strip().lower() == "off":
        return None, "switched off (PYTHIA_AUTOPILOT_STATE_URL=off)"
    import urllib.request
    try:
        req = urllib.request.Request(guard.read_only_url(url), method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r), None
    except guard.GuardError:
        raise
    except Exception as e:  # noqa: BLE001 - the engine being down is a finding, not a crash
        return None, f"{type(e).__name__}: {e}"


def engines() -> list[dict]:
    """Every autopilot engine as {"account", "url", "state", "error"}, read
    only: an exported file (PYTHIA_LEARN_ORDERS_FILE) as the main account,
    else every URL of notify.state_urls() (PYTHIA_AUTOPILOT_STATE_URLS, or
    the old single PYTHIA_AUTOPILOT_STATE_URL). Empty when switched off."""
    from . import notify
    f = os.environ.get("PYTHIA_LEARN_ORDERS_FILE")
    if f:
        try:
            v = json.loads(Path(f).read_text(encoding="utf-8"))
            return [{"account": notify.ACCOUNT_NAMES[0], "url": f, "state": v if isinstance(v, dict) else {"orders": v},
                     "error": None}]
        except (OSError, ValueError):
            try:
                st = {"orders": fills.load_orders_file(Path(f))}
                return [{"account": notify.ACCOUNT_NAMES[0], "url": f, "state": st, "error": None}]
            except OSError as e:
                return [{"account": notify.ACCOUNT_NAMES[0], "url": f, "state": None, "error": f"{type(e).__name__}: {e}"}]
    out = []
    for account, url in notify.state_urls():
        st, err = fetch_state(url)
        out.append({"account": account, "url": url, "state": st, "error": err})
    return out


def engine_state(rows: list[dict] | None = None) -> tuple[dict | None, str, str | None]:
    """(state, where it came from, error) of the first engine, the main
    account: its demo orders are what the cost step learns from."""
    rows = engines() if rows is None else rows
    if not rows:
        return None, "off", "switched off (PYTHIA_AUTOPILOT_STATE_URL=off)"
    return rows[0]["state"], rows[0]["url"], rows[0]["error"]


# ---------------------------------------------------------------- step: costs

def step_costs(state: dict | None, now_ms: int, changes: list[dict]) -> dict:
    out = fills.run((state or {}).get("orders") if state is not None else None, now_ms)
    for sym, d in out.get("decisions", {}).items():
        if d.get("status") == "applied":
            m = out["symbols"][sym]
            changes.append({"area": "costs", "what": f"Alpaca {sym}: spread {d['applied']['halfSpreadBps']} bps, "
                                                     f"impact {d['applied']['impactCoeff']}",
                            "why": f"{m['taker_fills']} demo market fills, median {m['median_realised_bps']:.2f} bps "
                                   f"against {m['median_base_bps']:.2f} bps in the base table"})
    for v in out.get("violations", []):
        changes.append({"area": "costs", "what": "learned cost table refused", "why": v})
    return out


# ---------------------------------------------------------------- step: evidence

def read_history(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


def evidence_summary(history: list[dict]) -> dict[str, dict]:
    """Per strategy ("book:<name>" or "autopilot:<id>"): status now, since when,
    the status before, and how many of the last 30 snapshots were ok."""
    series: dict[str, list[tuple[str, dict]]] = {}
    for snap in history:
        for kind in ("books", "autopilots"):
            for name, e in (snap.get(kind) or {}).items():
                series.setdefault(f"{kind[:-1]}:{name}", []).append((snap["date"], e))
    out = {}
    for key, rows in series.items():
        rows.sort(key=lambda r: r[0])
        now = rows[-1][1].get("status")
        since = rows[-1][0]
        prev = None
        for d, e in reversed(rows[:-1]):
            if e.get("status") != now:
                prev = e.get("status")
                break
            since = d
        last30 = [e.get("status") for _, e in rows[-30:]]
        out[key] = {"status": now, "since": since, "previous": prev, "first_seen": rows[0][0],
                    "snapshots": len(rows), "ok_last30": sum(s == "ok" for s in last30),
                    "below_last30": sum(s == "below" for s in last30),
                    "return_pct": rows[-1][1].get("return_pct"), "days": rows[-1][1].get("days")}
    return out


def step_evidence(now_ms: int, changes: list[dict]) -> dict:
    ev = _read_json(report.REPORTS / "forward" / "evidence.json")
    if not ev:
        return {"note": "no forward evidence yet (reports/forward/evidence.json)", "strategies": {}}
    hp = learn_dir() / "evidence_history.jsonl"
    history = read_history(hp)
    date = _date(int(ev.get("generated_ms") or now_ms))
    snap = {"date": date, "generated_ms": ev.get("generated_ms"),
            "books": {k: {f: v.get(f) for f in ("status", "return_pct", "days", "band_low_pct", "band_high_pct")}
                      for k, v in (ev.get("books") or {}).items()},
            "autopilots": {k: {f: v.get(f) for f in ("status", "return_pct", "days", "state")}
                           for k, v in (ev.get("autopilots") or {}).items()}}
    before = evidence_summary(history)
    if not history or history[-1].get("date") != date:
        history.append(snap)
        history = history[-HISTORY_KEEP:]
        guard.write_text(hp, "".join(json.dumps(guard.finite(h), allow_nan=False) + "\n" for h in history))
    stale = date != _date(now_ms)
    summary = evidence_summary(history)
    for key, s in summary.items():
        old = before.get(key, {}).get("status")
        if old is not None and old != s["status"]:
            changes.append({"area": "evidence", "what": f"{key}: {old} -> {s['status']}",
                            "why": f"forward report of {date}, return {s['return_pct'] if s['return_pct'] is not None else 'n/a'} % after {s['days']:.0f} days"
                            if isinstance(s.get("days"), (int, float)) else f"forward report of {date}"})
        elif old is None and key not in before:
            changes.append({"area": "evidence", "what": f"{key}: first forward evidence ({s['status']})",
                            "why": f"forward report of {date}"})
    out = {"date": date, "stale": stale, "strategies": summary}
    guard.write_json(report.REPORTS / NAME / "evidence.json", {"generated_ms": now_ms, **out})
    return out


# ---------------------------------------------------------------- step: sweep and gates

def _gates(summary: dict | None) -> dict[str, dict]:
    out = {}
    for p in (summary or {}).get("picks") or []:
        key = f"{p.get('family')}/{p.get('sub')}"
        out[key] = {"variant": p.get("variant"), "passes": bool(p.get("passes")), "verdict": p.get("verdict"),
                    "deflated_p": p.get("deflated_p"), "oos_sharpe_41bps": p.get("oos_sharpe_41bps"),
                    "oos_max_dd_41bps": p.get("oos_max_dd_41bps")}
    return out


def sweep_problems(old: dict | None, new: dict | None) -> list[str]:
    """Why a fresh sweep must not replace the published one; empty means it may."""
    import math
    if not new or not new.get("picks"):
        return ["the fresh sweep wrote no picks"]
    out = []
    for p in new["picks"]:
        for k in ("deflated_p", "oos_sharpe_41bps", "oos_sharpe_15bps"):
            v = p.get(k)
            if not isinstance(v, (int, float)) or not math.isfinite(v):
                out.append(f"{p.get('family')}/{p.get('variant')}: {k} is {v}")
    if old:
        if (new.get("n_variants") or 0) < (old.get("n_variants") or 0):
            out.append(f"fewer variants than the published sweep ({new.get('n_variants')} < {old.get('n_variants')}), "
                       "which would make the deflation lenient")
        lost = set(_gates(old)) - set(_gates(new))
        if lost:
            out.append(f"picks missing from the fresh sweep: {', '.join(sorted(lost))}")
    return out


def gate_changes(old: dict | None, new: dict | None) -> list[dict]:
    a, b = _gates(old), _gates(new)
    out = []
    for key, g in b.items():
        o = a.get(key)
        if o is None:
            out.append({"pick": key, "variant": g["variant"], "was": None, "now": g["passes"], "verdict": g["verdict"]})
        elif o["passes"] != g["passes"] or o["variant"] != g["variant"]:
            out.append({"pick": key, "variant": g["variant"], "was": o["passes"], "now": g["passes"],
                        "was_variant": o["variant"], "verdict": g["verdict"]})
    return out


Runner = Callable[[list[str], dict, int], tuple[int, str]]


def run_module(args: list[str], env: dict, timeout: int) -> tuple[int, str]:
    """Run `python -m <args>` from the lab's folder; (exit code, last lines of output)."""
    cwd = Path(__file__).resolve().parents[2]
    try:
        p = subprocess.run([sys.executable, "-m", *args], cwd=cwd, env={**os.environ, **env}, capture_output=True,
                           text=True, timeout=timeout)
        tail = "\n".join((p.stdout + p.stderr).strip().splitlines()[-15:])
        return p.returncode, tail
    except subprocess.TimeoutExpired:
        return -1, f"timed out after {timeout} s"


def step_sweep(now_ms: int, changes: list[dict], decisions: list[dict], runner: Runner = run_module) -> dict:
    stage = learn_dir() / "sweep" / _date(now_ms)
    guard.check_write(stage)
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    code, tail = runner(["lab.experiments.families", "--fresh"],
                        {"PYTHIA_AGENT_OUT": str(stage), "PYTHIA_FAM_RESULTS": str(stage / "results")},
                        TIMEOUT_S["sweep"])
    if code != 0:
        raise RuntimeError(f"family sweep exited with {code}: {tail}")
    live = out_dir()
    old = _read_json(live / "reports" / "families_summary.json")
    new = _read_json(stage / "reports" / "families_summary.json")
    problems = sweep_problems(old, new)
    flips = gate_changes(old, new) if not problems else []
    rec = {"ts_ms": now_ms, "date": _date(now_ms), "model": "families_sweep", "candidate": stage.name,
           "decision": "rejected" if problems else "promoted",
           "why": "; ".join(problems) if problems else
           f"{new.get('n_variants')} variants, {sum(g['passes'] for g in _gates(new).values())} of "
           f"{len(_gates(new))} picks pass; {len(flips)} gate changes",
           "gate_changes": flips}
    if not problems:
        backup = registry.registry_dir("families_sweep") / "previous" / _date(now_ms)
        for sub in ("reports", "runs"):
            src = live / sub
            if src.exists():
                for f in src.iterdir():
                    if f.is_file():
                        guard.copy_file(f, backup / sub / f.name)
            for f in (stage / sub).iterdir() if (stage / sub).exists() else []:
                if f.is_file():
                    guard.copy_file(f, live / sub / f.name)
        # The published copy is now the record; the staging panel cache is large.
        shutil.rmtree(stage, ignore_errors=True)
    for old_stage in sorted((learn_dir() / "sweep").iterdir()):
        if old_stage.is_dir() and old_stage != stage:
            shutil.rmtree(old_stage, ignore_errors=True)
    guard.append_jsonl(registry.registry_dir("families_sweep") / "decisions.jsonl", [rec])
    decisions.append(rec)
    gates = {"generated_ms": now_ms, "published": not problems, "problems": problems,
             "gates": _gates(new if not problems else old), "changes": flips}
    guard.write_json(report.REPORTS / NAME / "gates.json", gates)
    for f in flips:
        word = "now passes" if f["now"] else "no longer passes"
        changes.append({"area": "gates", "what": f"{f['pick']} ({f['variant']}) {word}",
                        "why": f["verdict"] + (" Needs the owner's review before anything trades on it."
                                               if f["now"] else "")})
    if problems:
        changes.append({"area": "gates", "what": "fresh sweep not published", "why": "; ".join(problems)})
    return gates


# ---------------------------------------------------------------- steps: model retrains

TRAIN_ARGS = {
    "vol_1h": lambda d: ["lab.experiments.vol", "--challenger", str(d)],
    "picks_7d": lambda d: ["lab.experiments.picks", "--perp-features", "--challenger", str(d)],
}


def step_model(name: str, now_ms: int, changes: list[dict], decisions: list[dict], runner: Runner = run_module,
               champion_predict=None) -> dict:
    cand_root = registry.candidates_dir(name)
    guard.check_write(cand_root)
    cand_root.mkdir(parents=True, exist_ok=True)
    started = time.time() * 1000 - 1000
    code, tail = runner(TRAIN_ARGS[name](cand_root), {}, TIMEOUT_S["vol" if name == "vol_1h" else "m2"])
    if code != 0:
        raise RuntimeError(f"{name} retrain exited with {code}: {tail}")
    cand = registry.newest_candidate(name, int(started))
    if cand is None:
        raise RuntimeError(f"{name} retrain finished but wrote no candidate under {cand_root}")
    rec = registry.decide(name, cand, now_ms, champion_predict)
    registry.prune_candidates(name)
    decisions.append(rec)
    changes.append({"area": "models", "what": f"{name} challenger {rec['candidate']} {rec['decision']}"
                                              + (f" as {rec['published']}" if rec.get("published") else ""),
                    "why": rec["why"]})
    return rec


# ---------------------------------------------------------------- autopilots against BTC

def equity_at(history: list, ms: int) -> float | None:
    """The last recorded equity at or before ms (history is [(ts_ms, equity), ...])."""
    best = None
    for row in history or []:
        try:
            t, e = int(row[0]), float(row[1])
        except (TypeError, ValueError, IndexError):
            continue
        if t <= ms:
            best = e
        else:
            break
    return best


def autopilot_pnl(state: dict | None, now_ms: int, price_at: Callable[[int], float | None]) -> list[dict]:
    rows = []
    cache: dict[int, float | None] = {}

    def px(ms: int):
        k = int(ms) // 60_000 * 60_000
        if k not in cache:
            cache[k] = price_at(k)
        return cache[k]

    for ap in (state or {}).get("autopilots") or []:
        cfg = ap.get("config") or {}
        start_ms = int(ap.get("startedMs") or now_ms)
        end_ms = int(ap.get("stoppedMs") or now_ms)
        start = float(ap.get("startCapital") or cfg.get("capitalUsd") or 0) or None
        equity = float(ap.get("equity") or 0) or None
        hist = sorted((ap.get("history") or []), key=lambda r: r[0] if r else 0)
        day0 = max(start_ms, end_ms - DAY_MS)
        e0 = equity_at(hist, day0) or (start if day0 == start_ms else None)
        total = (equity / start - 1) * 100 if start and equity else None
        day = (equity / e0 - 1) * 100 if e0 and equity else None
        b_start, b_day0, b_end = px(start_ms), px(day0), px(end_ms)
        btc_total = (b_end / b_start - 1) * 100 if b_start and b_end else None
        btc_day = (b_end / b_day0 - 1) * 100 if b_day0 and b_end else None
        rows.append({"id": cfg.get("id", "?"), "name": cfg.get("name", "Autopilot"), "mode": cfg.get("mode"),
                     "account": ap.get("account"),
                     "state": ap.get("state"), "since": _date(start_ms), "days": (end_ms - start_ms) / DAY_MS,
                     "equity": equity, "start_capital": start, "fees": ap.get("fees"), "trades": ap.get("trades"),
                     "pnl_day_pct": day, "btc_day_pct": btc_day,
                     "pnl_total_pct": total, "btc_total_pct": btc_total,
                     "vs_btc_total_pts": total - btc_total if total is not None and btc_total is not None else None})
    rows.sort(key=lambda r: (r["state"] != "running", r["id"]))
    return rows


def btc_price_at(ms: int) -> float | None:
    from ..paper.forward_report import btc_price_at as f
    return f(ms)


# ---------------------------------------------------------------- the digest

def _pct(v) -> str:
    return "n/a" if v is None else f"{v:+.2f} %"


def headline(changes: list[dict], decisions: list[dict], aps: list[dict], steps: list[dict], lang: str = "en") -> str:
    """What changed tonight in a sentence, in `lang` (the report keeps English;
    the digest says it in the language of the messages)."""
    t = i18n.t
    parts = []
    models = [d for d in decisions if d.get("model") != "families_sweep"]
    promoted = [d for d in models if d.get("decision") == "promoted"]
    rejected = [d for d in models if d.get("decision") in ("rejected", "kept")]
    for d in decisions:
        if d.get("model") == "families_sweep":
            parts.append(t("ln_sweep_new" if d.get("decision") == "promoted" else "ln_sweep_kept", lang))
    if promoted:
        parts.append(t("ln_promoted", lang, models=", ".join(d["model"] for d in promoted)))
    if rejected:
        parts.append(t("ln_kept", lang, models=", ".join(d["model"] for d in rejected)))
    for area, key in (("costs", "ln_costs"), ("evidence", "ln_evidence"), ("gates", "ln_gates")):
        n = sum(1 for c in changes if c["area"] == area)
        if n:
            parts.append(t(key, lang, n=n))
    failed = [s["step"] for s in steps if s["status"] == "failed"]
    if failed:
        parts.append(t("ln_failed", lang, steps=", ".join(failed)))
    running = [a for a in aps if a["state"] == "running"]
    if running:
        best = max(running, key=lambda a: a["vs_btc_total_pts"] if a["vs_btc_total_pts"] is not None else -1e9)
        if best["vs_btc_total_pts"] is not None:
            parts.append(t("ln_running_best", lang, n=len(running), pts=i18n.num(best["vs_btc_total_pts"], 2, lang, sign=True)))
        else:
            parts.append(t("ln_running", lang, n=len(running)))
    text = "; ".join(parts) if parts else t("ln_nothing", lang)
    return text[0].upper() + text[1:] + "."


def markdown(d: dict) -> str:
    lines = ["# Learning loop: what changed tonight\n", f"{d['generated']}. {d['headline']}\n",
             "The loop only updates evidence, costs and models within fixed bounds. It cannot change live settings, "
             "arm live, move money or raise a risk limit.\n", "## What changed\n"]
    lines += [f"- **{c['area']}**: {c['what']}. {c['why']}" for c in d["changes"]] or ["- Nothing."]
    lines.append("\n## Promotions and rejections\n")
    if d["decisions"]:
        lines.append(report.table([{"model": x["model"], "candidate": x.get("candidate"), "champion": x.get("champion"),
                                    "decision": x["decision"], "challenger": x.get("challenger_score"),
                                    "champion_score": x.get("champion_score"), "why": x["why"]}
                                   for x in d["decisions"]],
                                  ["model", "candidate", "champion", "decision", "challenger", "champion_score", "why"]))
    else:
        lines.append("No retrain was due.\n")
    lines.append("## Autopilots against BTC\n")
    if d["autopilots"]:
        lines.append(report.table([{"autopilot": a["name"], "mode": a["mode"], "state": a["state"], "since": a["since"],
                                    "today": _pct(a["pnl_day_pct"]), "btc_today": _pct(a["btc_day_pct"]),
                                    "since_start": _pct(a["pnl_total_pct"]), "btc_since_start": _pct(a["btc_total_pct"]),
                                    "vs_btc": "n/a" if a["vs_btc_total_pts"] is None else f"{a['vs_btc_total_pts']:+.2f} pts"}
                                   for a in d["autopilots"]],
                                  ["autopilot", "mode", "state", "since", "today", "btc_today", "since_start",
                                   "btc_since_start", "vs_btc"]))
    else:
        lines.append(f"{d['engine'].get('error') or 'No autopilots.'}\n")
    costs = d.get("costs") or {}
    if costs.get("symbols"):
        lines.append("## Demo fills on the Alpaca paper account\n")
        lines.append(report.table([{"symbol": s, "market_fills": m["taker_fills"], "limit_fills": m["maker_fills"],
                                    "median_bps": m["median_realised_bps"], "base_bps": m["median_base_bps"],
                                    "maker_fill_rate": m["maker_fill_rate"], "taker_fill_rate": m["taker_fill_rate"],
                                    "status": (costs.get("decisions", {}).get(s) or {}).get("status", "n/a")}
                                   for s, m in costs["symbols"].items()],
                                  ["symbol", "market_fills", "limit_fills", "median_bps", "base_bps",
                                   "maker_fill_rate", "taker_fill_rate", "status"]))
    lines.append("## Steps\n")
    lines.append(report.table(d["steps"], ["step", "status", "detail"]))
    lines.append(f"Files written: {len(d['guardrails']['written'])}. Guardrail refusals: "
                 f"{len(d['guardrails']['refused']) or 'none'}.\n")
    return "\n".join(lines) + "\n"


def run(now_ms: int | None = None, force: set[str] | None = None, skip: set[str] | None = None,
        train: bool = True, runner: Runner = run_module, price_at=btc_price_at, champion_predict=None) -> dict:
    now_ms = now_ms or int(time.time() * 1000)
    force, skip = force or set(), skip or set()
    guard.WRITTEN.clear()
    st = load_state()
    changes: list[dict] = []
    decisions: list[dict] = []
    steps: list[dict] = []
    refused: list[str] = []
    results: dict = {}
    from . import notify
    rows = engines()
    engine, source, err = engine_state(rows)
    # Every account's autopilots for the digest; an engine that does not answer is left out.
    merged = notify.merge_states(rows)

    for step in STEPS:
        if step in skip or (step in HEAVY and not train and step not in force):
            steps.append({"step": step, "status": "skipped", "detail": "left out on request"})
            continue
        ok_due, why = due(step, st, now_ms)
        if not ok_due and step not in force:
            steps.append({"step": step, "status": "not due", "detail": why})
            continue
        try:
            if step == "costs":
                r = step_costs(engine, now_ms, changes)
                detail = (f"{r['new_orders']} new demo orders, {r['ledger_orders']} in the ledger"
                          + (f"; {r['note']}" if r.get("note") else ""))
                if engine is None:
                    detail += f"; engine not read ({err})"
            elif step == "evidence":
                r = step_evidence(now_ms, changes)
                detail = r.get("note") or (f"{len(r['strategies'])} strategies, forward report of {r['date']}"
                                           + (" (not today's)" if r.get("stale") else ""))
            elif step == "sweep":
                r = step_sweep(now_ms, changes, decisions, runner)
                detail = "published" if r["published"] else "not published: " + "; ".join(r["problems"])
            else:
                name = "vol_1h" if step == "vol" else "picks_7d"
                r = step_model(name, now_ms, changes, decisions, runner, champion_predict)
                detail = f"{r['decision']}: {r['why']}"
            results[step] = r
            mark(st, step, now_ms, True, detail)
            steps.append({"step": step, "status": "ok", "detail": detail})
        except guard.GuardError as e:
            refused.append(str(e))
            mark(st, step, now_ms, False, str(e))
            steps.append({"step": step, "status": "failed", "detail": f"guardrail: {e}"})
        except Exception as e:  # noqa: BLE001 - one step failing must not stop the others or the digest
            mark(st, step, now_ms, False, f"{type(e).__name__}: {e}")
            steps.append({"step": step, "status": "failed", "detail": f"{type(e).__name__}: {e}"[:400]})

    aps = autopilot_pnl(merged, now_ms, price_at) if merged is not None else []
    guard.write_json(learn_dir() / "state.json", st)
    data = {"generated": datetime.fromtimestamp(now_ms / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "generated_ms": now_ms, "changes": changes, "decisions": decisions, "autopilots": aps,
            "steps": steps, "costs": results.get("costs"), "gates": results.get("sweep"),
            "evidence": (results.get("evidence") or {}).get("strategies"),
            "engine": {"source": source, "reachable": engine is not None, "error": err,
                       "accounts": [{"account": r["account"], "url": r["url"], "reachable": r["state"] is not None}
                                    for r in rows]}}
    data["headline"] = headline(changes, decisions, aps, steps)
    # The digest to the chat says it in German when the messages are.
    data["headlines"] = {"de": headline(changes, decisions, aps, steps, "de")}
    data.update(feed(data, now_ms))
    guard.check_write(report.REPORTS / NAME / "latest.json")
    data["guardrails"] = {"written": sorted(set(guard.WRITTEN)), "refused": refused}
    data = guard.finite(data)
    report.write(NAME, markdown(data), data)
    return data


def feed(d: dict, now_ms: int) -> dict:
    """The common feed header (docs/LAB-FEEDS.md): bad when a step failed,
    a promoted model first, then the other decisions and changes."""
    items = [{"label": f"{x.get('model')}: {x.get('decision')}", "detail": x.get("why"),
              "status": "ok" if x.get("decision") != "rejected" else "watch",
              "importance": 80 if x.get("decision") == "promoted" else 30}
             for x in d.get("decisions") or [] if x.get("model")]
    items += [{"label": x.get("what"), "detail": x.get("why"), "value": x.get("area"), "importance": 20}
              for x in d.get("changes") or [] if x.get("what")]
    failed = [x.get("step") for x in d.get("steps") or [] if x.get("status") == "failed"]
    items += [{"label": f"step {s} failed", "status": "bad", "importance": 60} for s in failed if s]
    items.sort(key=lambda it: -it["importance"])
    return report.feed_header("Learning loop", "bad" if failed else "ok", d.get("headline") or "", items, now_ms)


def _names(flag: str) -> set[str]:
    out = set()
    for i, a in enumerate(sys.argv):
        if a == flag and i + 1 < len(sys.argv):
            out |= {x.strip() for x in sys.argv[i + 1].split(",") if x.strip()}
    unknown = out - set(STEPS)
    if unknown:
        raise SystemExit(f"unknown step(s) {sorted(unknown)}; steps are {STEPS}")
    return out


def main() -> int:
    run(force=_names("--force"), skip=_names("--skip"), train="--no-train" not in sys.argv)
    return 0


if __name__ == "__main__":
    sys.exit(main())
