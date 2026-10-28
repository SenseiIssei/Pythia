"""The weekly factory run and the daily shadow step.

  python -m lab.factory                    weekly: search, holdout, shadow update and review, report
  python -m lab.factory --budget 400       a different number of new genomes this run
  python -m lab.factory --tree-share 0.5   the share of them with an expression tree (G1; default 0.30,
                                           PYTHIA_FACTORY_TREE_SHARE, for the small mode too)
  python -m lab.factory --notify           also post the digest (PYTHIA_ALERT_WEBHOOK or Telegram)
  python -m lab.factory --fresh            rebuild the daily panel from the history files first
  python -m lab.factory shadow             daily: append the new days to each shadow book, review
                                           those with 30 days (posts only when one is decided, with --notify)
  python -m lab.factory digest --dry-run   print the last run's digest
  python -m lab.factory small              daily, F2: the small-account mode (small.py: 40 and 100 EUR
                                           wallets on BTC, ETH, SOL, SPYx, QQQx, PAXG, own ledger and shadows)
  python -m lab.factory export-seed        write the ledger, holdout log and active shadow
                                           books to results/factory_seed (committed, so a
                                           run made elsewhere counts on the server too)

The panel is the sweep's with Binance's daily bars of every pair before 2020 in
front (lab.history.load_long_panel, from 2017-08); a weekly run first fetches
what the long history does not have yet (once per pair, cached).

R6 (results/factory_lockbox_r6.md): "held back" is the validation window 2024-01-01
to 2026-06-30. The lockbox, 2026-07-01 on, is looked at only here, in the weekly
run (lockbox_step): every genome of this factory and of F2 that passes its gates and
the deflated excess bar gets one look per behaviour, each written to
<data>/factory/lockbox.jsonl before it is used. Each run reports its genomes'
effective N and PBO.

T2 (results/overfit_yardsticks_prereg.md): the PBO also over the whole family (family_series: every
genome of the window, one per behaviour, the evaluate.FAMILY_MAX best by fitness) with its rank logits,
and every genome held back gets a combinatorial purged CV of its in-sample days (evaluate.cpcv); the
report has one line per candidate (DSR, PBO, CPCV median and 10th percentile).

T1 (results/leak_harness_prereg.md): before its held-back look every pick goes through the leak harness
(lab.leak, leak_screen); one whose weights at or before t move when the bars after t change is rejected,
written to <data>/factory/leaks.jsonl with the reason and never picked again.

Every run first merges results/factory_seed into <data>/factory (only what is
missing; see ledger.import_seed), so trials counted on another machine are
never lost from the pool.

Writes <data>/factory/ (ledger.jsonl, holdout.jsonl, leaks.jsonl, shadow/, promoted.json,
runs/<run>.json) and reports/factory/ (dated and latest markdown and JSON;
with PYTHIA_RESULTS also <results>/factory.md). Nothing else: no engine call,
no live setting, no paper journal (a promoted book is stepped by
lab.paper.families like the other paper books).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .. import history, report
from ..ops import i18n, notify
from . import build, evaluate, grammar, search, shadow, writeup
from .ledger import (Ledger, append_jsonl, export_seed, factory_dir, import_seed, lock, lockbox_looks, log_look,
                     read_jsonl, write_json)

NAME = "factory"
HOLDOUT_PER_RUN = 6
DIVERSITY_CORR = 0.90


def _day(us: int) -> str:
    return datetime.fromtimestamp(us / 1e6, timezone.utc).strftime("%Y-%m-%d")


def strip(row: dict) -> dict:
    """The row without its in-memory return series."""
    return {k: v for k, v in row.items() if k != "is_returns"}


def pick_for_holdout(c: build.Ctx, ledger: Ledger, checked: set[str], n: int = HOLDOUT_PER_RUN) -> list[dict]:
    """The best unseen genomes by fitness, both halves positive, mutually different in sample. `checked`: keys and
    behaviours held back before; a genome that does what another does is never picked (R6)."""
    cands = [r for r in evaluate.current(ledger.rows) if r["key"] not in checked and r.get("behaviour") not in checked
             and not r.get("same_as") and r["is_h1"] > 0 and r["is_h2"] > 0
             and r["is_exposure"] >= evaluate.MIN_EXPOSURE and r["fitness"] > 0]
    cands.sort(key=lambda r: r["fitness"], reverse=True)
    chosen: list[tuple[dict, np.ndarray]] = []
    for r in cands[: n * 10]:
        x = evaluate.is_series(c, r["genome"])
        if any(_corr(x, y) > DIVERSITY_CORR for _, y in chosen):
            continue
        chosen.append((r, x))
        if len(chosen) >= n:
            break
    return [r for r, _ in chosen]


def _corr(a: np.ndarray, b: np.ndarray) -> float:
    if a.std() == 0 or b.std() == 0:
        return 0.0
    return float(np.corrcoef(a, b)[0, 1])


def verdict(d: dict) -> str:
    n_sh = sum(1 for h in d["holdout"] if h["decision"] == "shadow")
    prom = [x for x in d["decisions"] if x["status"] == "promoted"]
    if prom:
        return f"{len(prom)} genome(s) promoted to paper books after their forward month."
    if n_sh:
        return (f"{n_sh} genome(s) pass the held-back gates and start a 30-day forward shadow; none is near "
                f"promotion until then, and deflation over {d['pool_after']['n_trials']} trials must also pass.")
    return (f"Nothing survives the held-back gates this run. {len(d['holdout'])} genomes were checked; "
            f"the pool grew to {d['pool_after']['n_trials']} trials.")


def weekly(budget: int, fresh: bool, run_id: str | None, log=print, share: float | None = None) -> dict:
    t0 = time.time()
    P = history.load_long_panel(fetch=True, fresh=fresh)
    c = build.make_ctx(P)
    today = _day(int(P.days[-1]))
    run_id = run_id or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    log(f"factory {run_id}: panel {P.N} segments to {today}, {len(c.cols)} columns in play")
    seeded = import_seed()
    if any(seeded.values()):
        log(f"  merged from the seed: {seeded}")
    ledger = Ledger()
    pool_before = ledger.pool()
    share = search.tree_share() if share is None else share
    elite = search.elite_of(evaluate.current(ledger.rows))
    feats = build.feature_leaves(c)
    if feats:
        log(f"  feature store leaves in sample: {', '.join(feats)}")
    res = search.search(c, set(ledger.by_key), elite, run_id, budget, log=log, share=share,
                        leaves=grammar.LEAVES + feats)
    ledger.add([strip(r) for r in res["rows"]])
    for r in res["rows"]:                     # the ledger marks a repeated behaviour on its own copy
        if ledger.by_key[r["key"]].get("same_as"):
            r["same_as"] = ledger.by_key[r["key"]]["same_as"]
    pool = ledger.pool()
    fam = family_series(c, ledger.rows, res["rows"])

    hold_log = shadow.holdout_log()
    checked = {h["key"] for h in hold_log} | {h["behaviour"] for h in hold_log if h.get("behaviour")}
    checked |= {x["key"] for x in read_jsonl(factory_dir() / "leaks.jsonl")}
    picks = pick_for_holdout(c, ledger, checked)
    leaks = leak_screen(c, picks, factory_dir() / "leaks.jsonl", run_id, today, log)
    picks = [r for r in picks if r["key"] not in {x["key"] for x in leaks}]
    btc = evaluate.btc_benchmark(c)
    w = evaluate.windows(c)
    act = shadow.active()
    others = [(m["key"], shadow.oos_series(m)) for m in shadow.all_shadows() if m["status"] != "retired"]
    open_slots = max(0, min(shadow.MAX_NEW_PER_RUN, shadow.MAX_ACTIVE - len(act)))
    ever = shadow.ever_shadowed()
    holdout_rows = []
    for r in picks:
        h = evaluate.holdout(c, r["genome"], pool, btc)
        h["cpcv"] = evaluate.cpcv(fam[r["key"]] if r["key"] in fam else evaluate.is_series(c, r["genome"]), fam,
                                  r["key"])
        gates = evaluate.shadow_gates(r, h)
        bad = evaluate.failed(gates)
        gross, tov, _ = build.run(c, r["genome"])
        x = build.net(gross, tov, build.COSTS["35bps"])[w["oos"]]
        if bad:
            decision, why = "stopped", "; ".join(f"{writeup.GATE_LABEL.get(k, k)} fails ({gates[k]['why']})"
                                                for k in bad)
        elif r["key"] in ever:
            decision, why = "already shadowed", "ran as a shadow book before"
        elif (dup := shadow.too_close(x, others)) is not None:
            decision, why = "duplicate", f"held-back returns move with shadow {dup} (corr > {shadow.DUPLICATE_CORR})"
        elif open_slots <= 0:
            decision, why = "waiting", "passes, but every shadow slot this run is taken"
        else:
            decision = "shadow"
            why = (f"passes every held-back gate; DSR of the excess over BTC {h['deflated_p']:.2f} (needs "
                   f"{evaluate.DEFLATED_BAR} and a lockbox look by the end of its forward month)")
            shadow.start(r, h, gates, x, run_id, today)
            others.append((r["key"], x))
            open_slots -= 1
        row = {**h, "is_sharpe": r["is_sharpe"], "is_h1": r["is_h1"], "is_h2": r["is_h2"], "gates": gates,
               "decision": decision, "why": why, "genome": r["genome"]}
        holdout_rows.append(row)
        log(f"  holdout {r['key']} {decision}: {why}")
    # "waiting" genomes stay unseen-in-effect: they go back to the holdout queue next run.
    append_jsonl(factory_dir() / "holdout.jsonl",
                 [{"run": run_id, "date": today, **{k: v for k, v in h.items() if k != "band30"}}
                  for h in holdout_rows if h["decision"] != "waiting"])

    looks = lockbox_step(c, pool, btc, holdout_rows, run_id, today, log)
    upd = shadow.update(c)
    decisions = shadow.review(c, pool, btc, today)
    shadows = []
    for m in shadow.all_shadows():
        fw = shadow.forward_stats(m)
        shadows.append({"key": m["key"], "name": m["name"], "entry_day": m["entry_day"], "status": m["status"],
                        "days": fw["days"], "return": fw["return"], "band": fw["band"], "reason": m.get("reason")})

    top = sorted(res["rows"], key=lambda r: r["fitness"], reverse=True)[:10]
    d = {
        "run_id": run_id, "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "panel": {"segments": P.N, "columns_in_play": int(len(c.cols)), "first": _day(int(P.days[0])),
                  "last": today},
        "windows": {"is": f"{_day(int(c.days[w['is']][0]))} to {_day(int(c.days[w['is']][-1]))}",
                    "oos": f"{_day(int(c.days[w['oos']][0]))} to {_day(int(c.days[w['oos']][-1]))} (validation)",
                    "lockbox": f"{evaluate.LOCKBOX_FROM} to {today}" if w["lockbox"].any() else None},
        "budget": budget, "seeded": seeded, "pool_before": pool_before, "pool_after": pool,
        "search": {"evaluated": len(res["rows"]), "origin": res["origin"], "duplicates": res["duplicates"],
                   "seconds": res["seconds"], "trees": res["trees"], "tree_share": share,
                   "feature_leaves": list(feats)},
        "trees": tree_summary(res["rows"], ledger.rows, holdout_rows),
        "tried": [{"key": r["key"], "genome": r["genome"], "is_sharpe": r["is_sharpe"]} for r in res["rows"]],
        "top": [strip({k: v for k, v in r.items() if k != "genome"}) for r in top],
        "btc": btc, "diversity_corr": DIVERSITY_CORR,
        "holdout": holdout_rows, "leaks": leaks, "night": night(res["rows"], fam), "lockbox": looks,
        "shadow_update": upd, "decisions": decisions, "shadows": shadows,
        "promoted": shadow.promoted()["books"], "seconds": time.time() - t0,
        "grammar": {"max_filters": grammar.MAX_FILTERS, "max_complexity": grammar.MAX_COMPLEXITY},
    }
    d["verdict"] = verdict(d)
    write_json(factory_dir() / "runs" / f"{run_id}.json", d)
    return d


def leak_screen(c, picks: list[dict], path: Path, run_id: str, today: str, log=print, small: bool = False) -> list[dict]:
    """T1: every genome bound for the held-back window through the leak harness first (lab.leak: its weights at or
    before t must not move when every bar after t is shuffled, shifted, missing or cut). A failing one is rejected
    before its look, written to `path` with the reason and never picked again; returns those rows."""
    from .. import leak
    from ..leak import checks
    out = []
    for r in picks:
        res = checks.genome(c, r["genome"], small=small)
        if res["ok"]:
            continue
        x = {"run": run_id, "date": today, "key": r["key"], "behaviour": r.get("behaviour"),
             "name": grammar.describe(r["genome"]), "genome": r["genome"], "reason": leak.reason(res),
             "first": res["first"]}
        append_jsonl(path, [x])
        out.append(x)
        log(f"  leak check {r['key']} rejected: {x['reason']}")
    return out


def night(rows: list[dict], fam: dict[str, np.ndarray] | None = None) -> dict:
    """Effective N and PBO of this run's genomes, one per behaviour (R6), and the PBO of the whole family (T2)."""
    xs = [r.get("is_returns") for r in rows if not r.get("same_as")]
    return {"effective_n": evaluate.effective_n(xs), "pbo": evaluate.pbo(xs),
            "family": evaluate.family_pbo(fam) if fam else None,
            "same_behaviour": sum(1 for r in rows if r.get("same_as"))}


def family_series(c: build.Ctx, rows: list[dict], fresh: list[dict]) -> dict[str, np.ndarray]:
    """T2: the in-sample returns of the family, every genome of the window one per behaviour, at most
    evaluate.FAMILY_MAX (the best by fitness); this run's from memory, the others rebuilt."""
    have = {r["key"]: r["is_returns"] for r in fresh if r.get("is_returns") is not None}
    cur = sorted((r for r in evaluate.current(rows) if not r.get("same_as")), key=lambda r: -r.get("fitness", -9.0))
    return {r["key"]: have[r["key"]] if r["key"] in have else evaluate.is_series(c, r["genome"])
            for r in cur[: evaluate.FAMILY_MAX]}


def lockbox_step(c: build.Ctx, pool: dict, btc: dict, held: list[dict], run_id: str, today: str, log=print) -> dict:
    """The only place the lockbox is looked at. Candidates: this run's held-back genomes and the active shadows
    that pass every shadow gate and the deflated excess bar, then F2's survivors (small.lockbox_step); each
    behaviour once ever, each look logged before it is used. F2's market failing does not stop the run."""
    looked = {x.get(k) for x in lockbox_looks() for k in ("key", "behaviour") if x.get(k)}
    cands = [(h, h["genome"]) for h in held if not evaluate.failed(h["gates"]) and evaluate.excess_bar(h)]
    have = {h["key"] for h, _ in cands}
    for m in shadow.active():
        if m["key"] in have:
            continue
        h = evaluate.holdout(c, m["genome"], pool, btc)
        if not evaluate.failed(evaluate.shadow_gates(m["in_sample"], h)) and evaluate.excess_bar(h):
            cands.append((h, m["genome"]))
    out: list[dict] = []
    for h, g in cands:
        if h["key"] in looked or h.get("behaviour") in looked:
            continue
        res = evaluate.lockbox(c, g, pool)
        if res is None:
            log(f"  lockbox shorter than {evaluate.LOCKBOX_MIN_DAYS} days: no look")
            break
        x = log_look({"factory": NAME, "run": run_id, "date": today, "key": h["key"], "behaviour": h.get("behaviour"),
                      "name": h["name"], "validation_dsr": h["deflated_p"], **res})
        looked |= {h["key"], h.get("behaviour")}
        log(f"  lockbox look {x['look']} {h['key']}: excess Sharpe {x['lockbox_excess_sharpe']:.2f}, "
            f"DSR {x['dsr']:.2f} over {x['looks']} looks")
        out.append(x)
    err = None
    try:
        from . import small
        out += small.lockbox_step(run_id, log=log)
    except Exception as e:      # noqa: BLE001 (the F2 market is fetched; the weekly run must still finish)
        err = f"F2 lockbox step failed: {type(e).__name__}: {e}"
        log("  " + err)
    return {"this_run": out, "all": len(lockbox_looks()), "error": err}


def r6_markdown(d: dict) -> str:
    """The R6 part of the report: the validation and lockbox windows, PBO and effective N, the lockbox looks."""
    from .small import candidate_lines, night_lines
    p = d["pool_after"]
    lb = d.get("lockbox") or {}
    md = ["## The bar after R6\n",
          f"Held back is validation now ({d['windows']['oos']}): every study since the families sweep has seen it. "
          f"The lockbox ({d['windows'].get('lockbox') or 'from ' + evaluate.LOCKBOX_FROM + ', no day yet'}) is looked "
          f"at only by this weekly run, once per behaviour; {lb.get('all', 0)} look(s) so far across the factories.",
          f"The deflated gate is on the held-back daily excess over BTC: N {p['n_trials']} (the trial registry, one "
          f"trial per behaviour; {p.get('same_behaviour', 0)} genome(s) of this ledger repeat an earlier one), the "
          f"noise variance from {p.get('excess_trials', 0)} in-sample excess Sharpes ({p.get('excess_from', 'raw')}), "
          f"noise bar excess Sharpe {p.get('excess_sr0_annual', p['sr0_annual']):.2f} (the raw Sharpe's was "
          f"{p['sr0_annual']:.2f}). Promotion also needs the lockbox look's DSR over every look at "
          f"{evaluate.LOCKBOX_BAR} or more.\n"]
    md += night_lines(d.get("night"), "this run's genomes")
    md += candidate_lines(d["holdout"], (d.get("night") or {}).get("family"), "the excess over BTC")
    md.append("## Lockbox looks this run\n")
    rows = lb.get("this_run") or []
    md.append(writeup.table([[x["look"], x["factory"], x["key"], x["lockbox_days"],
                              f"{x['lockbox_excess_sharpe']:.2f}", f"{x['dsr']:.2f}", x["looks"]] for x in rows],
                            ["look", "factory", "key", "days", "excess Sharpe", "DSR over the looks", "looks then"])
              if rows else "none\n")
    if lb.get("error"):
        md.append(lb["error"] + "\n")
    return "\n".join(md) + "\n"


def tree_summary(new: list[dict], rows: list[dict], held: list[dict]) -> dict:
    """The expression trees (G1): how many this run and in the whole ledger (every one a trial in the
    pool), the best of this run in sample, and those held back with their decision."""
    mine = [r for r in new if grammar.has_tree(r["genome"])]
    best = max(mine, key=lambda r: r["fitness"], default=None)
    keep = ("key", "name", "expression", "is_sharpe", "is_h1", "is_h2", "tree_nodes", "complexity", "fitness")
    return {"this_run": len(mine), "in_ledger": sum(1 for r in rows if grammar.has_tree(r["genome"])),
            "best": {k: best.get(k) for k in keep} if best else None,
            "held_back": [{"key": h["key"], "expression": grammar.expression(h["genome"]), "is_sharpe": h["is_sharpe"],
                           "oos_sharpe_35bps": h["oos_sharpe_35bps"], "deflated_p": h["deflated_p"],
                           "decision": h["decision"]} for h in held if grammar.has_tree(h["genome"])]}


def published(d: dict) -> dict:
    """The report JSON: the common header first, then the run itself."""
    ms = int(datetime.fromisoformat(d["generated"]).timestamp() * 1000)
    return {**writeup.header(d, ms), **{k: v for k, v in d.items() if k != "verdict"}}


def publish(d: dict) -> None:
    report.write(NAME, writeup.markdown(d) + "\n" + r6_markdown(d), published(d))
    results = os.environ.get("PYTHIA_RESULTS")
    if results:
        Path(results, f"{NAME}.json").write_text(json.dumps(_compact(d), indent=1, default=float),
                                                  encoding="utf-8")


def _compact(d: dict) -> dict:
    """The JSON kept in the repo: everything but the full list of genomes tried."""
    out = {k: v for k, v in published(d).items() if k != "tried"}
    out["tried_count"] = len(d["tried"])
    return out


def send(text: str, dry_run: bool) -> bool:
    """The digest as one card in the category "studies" (lab.ops.notify): the
    words before the first colon the title, the rest the summary and lines."""
    first, _, rest = text.partition("\n")
    title, _, lead = first.partition(":")
    card = notify.text_card("studies", title.strip(), (lead.strip() + "\n" + rest).strip())
    res = notify.send("studies", [card], dry_run=dry_run)
    if res["error"]:
        print(f"digest not delivered: {res['error']}", file=sys.stderr)
    return res["delivered"]


def last_run() -> dict | None:
    p = report.REPORTS / NAME / "latest.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def daily_shadow(do_notify: bool, log=print) -> dict:
    P = history.load_long_panel()
    c = build.make_ctx(P)
    today = _day(int(P.days[-1]))
    import_seed()
    pool = Ledger().pool()
    btc = evaluate.btc_benchmark(c)
    upd = shadow.update(c)
    decisions = shadow.review(c, pool, btc, today)
    out = {"date": today, "updated": upd, "decisions": decisions}
    write_json(report.REPORTS / NAME / "shadow_latest.json", out)
    for u in upd:
        log(f"shadow {u['key']}: +{u['appended']} days, {u['days']} in all")
    for x in decisions:
        log(f"decided {x['key']}: {x['status']} ({x['reason']})")
    if do_notify and decisions:
        lang = notify.alert_lang()
        send(i18n.t("fa_review", lang) + "\n" + "\n".join(writeup.decision_line(x, lang) for x in decisions),
             dry_run=False)
    return out


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["small"]:
        # F2, the small-account mode: its own grammar, costs, ledger, shadows and report (small.py).
        from . import small
        return small.main(argv[1:])
    ap = argparse.ArgumentParser(prog="python -m lab.factory")
    ap.add_argument("command", nargs="?", default="run", choices=["run", "shadow", "digest", "export-seed"])
    ap.add_argument("--budget", type=int, default=search.BUDGET)
    ap.add_argument("--tree-share", type=float, help="share of the budget for tree genomes (default 0.30)")
    ap.add_argument("--fresh", action="store_true")
    ap.add_argument("--notify", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--run-id")
    a = ap.parse_args(argv)
    if a.command == "digest":
        d = last_run()
        if d is None:
            print("no factory run yet", file=sys.stderr)
            return 1
        send(writeup.digest(d, notify.alert_lang()), dry_run=a.dry_run)
        return 0
    with lock():
        if a.command == "export-seed":
            print(json.dumps(export_seed()))
            return 0
        if a.command == "shadow":
            daily_shadow(a.notify)
            return 0
        d = weekly(a.budget, a.fresh, a.run_id, share=a.tree_share)
        publish(d)
        if a.notify:
            send(writeup.digest(d, notify.alert_lang()), dry_run=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
