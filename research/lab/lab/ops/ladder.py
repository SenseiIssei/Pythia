"""The readiness ladder (T3): on which step every candidate stands, what it misses next and where the evidence is.

The rules: results/readiness_ladder_prereg.md (written 2026-10-29, after this code, from its audit). One row per candidate: every paper book (lab.ops.paper_books),
every survivor of the weekly factory and F2 (<data>/factory/holdout.jsonl, factory/small/holdout.jsonl, a decision
other than stopped), every active shadow (the weekly factory's <data>/factory/shadow/*.json, F2's and G2's report).
Each step requires the one before:

  1 idea       a pre-registration (PREREG) committed on or before the candidate's first number
  2 tested     T1's leak check passed (a positive record), filled one close late still positive, costs of their era,
               DSR (higher is better, pass at 0.95) over R5's whole registry and over its family as of today (dsr_now),
               PBO of its family below 0.2
  3 shadow     SHADOW_DAYS dates logged before the outcome (T8 checks the "before")
  4 lockbox    R6's one look made, against the right benchmark (BENCH), and passed
  5 execution  at most 50 EUR under the review's rules, judged on execution after 90 days (reports/execution); for
               P3's 10 EUR pump.fun books the gate for real money instead (results/ten_eur_p3_prereg.md: 30 days,
               mean and band above 0 after all costs, P2's gap under 2 points, P1's taint out), shown on its own too
  6 larger     only by the owner; the ladder never sets it

The pump.fun rules the live bot ran and the real-time report's best (PF_RULES) are judged per trade on the realistic
paper ledger (results/ladder_pumpfun_prereg.md): step 2 R7's bar (the Sharpe per entry deflated on its day-clustered
effective entries over R5 and the pumpfun family plus F3's trials, 20 entries, 10 scored days), the lat 2x stress as
the late fill, realistic execution only, P1's tainted rows out; step 3 T8's e-process on the day sums of the entries;
step 4 the same on the days after the pre-registration only; step 5 P2's selection gap and P3's 10 EUR book, absent
open (and blocking). Each rule shows its days of record, entries and the days still needed at its current mean.

A condition passes, fails or is open. Open is allowed on step 1 only (the commit date without git); from step 2 on
everything fails closed: missing evidence (no leak record, no PBO, no T8 report, a DSR deflated over far fewer trials
than today's and no series to recompute it) fails, and climb() treats an open condition there as a fail too. The ladder computes no performance number except the pump.fun rules' (five trials, pf_trials, counted in their
own DSRs and registered when the report is written), reads only, and writes nothing but reports/ladder/latest.json
and .md and those five registry lines. It proposes; it never arms, changes or sends anything.

  python -m lab.ops.ladder            write the report (the Lab Live job also writes it every run)
  python -m lab.ops.ladder --print    print the table, write nothing
"""

from __future__ import annotations

import csv
import json
import math
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from . import notify, paper_books

NAME = "ladder"
RESULTS = Path(__file__).resolve().parents[2] / "results"
DAY_MS = 86_400_000

STEPS = {0: "none", 1: "idea", 2: "tested", 3: "shadow", 4: "lockbox", 5: "execution", 6: "larger"}
STEPS_DE = {0: "keine", 1: "Idee", 2: "getestet", 3: "Schatten", 4: "Lockbox", 5: "Ausführung", 6: "größer"}

# ---------------------------------------------------------------- the pre-registered numbers
DSR_PASS = 0.95                 # metrics.dsr: higher is better
PBO_MAX = 0.2
SHADOW_DAYS = 30                # the review: 30 clean paper days
LOCKBOX_BAR = 0.5               # factory.evaluate.LOCKBOX_BAR: the look's DSR over every look so far
T1_FROM = "2026-10-28"          # genomes held back from this day on went through the leak harness first
FAIL_CLOSED_FROM = 2            # from this step on an open condition blocks like a fail
DSR_STALE = 0.9                 # a row's DSR over fewer than 90 % of today's trials is stale (DSR only falls as N grows)
EXEC_CAP_EUR = 50.0
EXEC_NO_TOPUP_DAYS = 90
EXEC_FAILED_IN_A_ROW = 2
EXEC_COST_X, EXEC_COST_SWAPS = 2.0, 10
EXEC_DRIFT_PCT = 1.0
EXEC_DAYS = 90

# What each kind is judged against at the lockbox; what each factory's look is against (R6).
BENCH = {"crypto": "btc_eth", "small": "ucits", "neutral": "zero", "pumpfun": "zero"}
BENCH_TEXT = {"btc_eth": "BTC and ETH held", "ucits": "a UCITS S&P 500 fund in EUR", "zero": "0",
              "btc": "BTC held", "spyx": "the SPYx wallet"}
LOOK_BENCH = {"factory": "btc", "weekly": "btc", "small": "spyx"}
NEUTRAL_BOOKS = {"m4_ls", "m4_perps", "picks_ls", "picks_ls_v2", "funding_carry", "perps_neutral"}
ONCHAIN_STUDIES = {"S1", "S2", "L1", "F2"}  # on-chain rules: only R10's era costs count

# A study's pre-registration and its first results file (results/). The factories' genomes: R6, a pre-registration
# under another name, before every genome held back after it.
PREREG = {
    "S1": ("smallaccount_s1_prereg.md", "smallaccount_s1.md"),
    "S2": ("smallaccount_s2_prereg.md", "smallaccount_s2.md"),
    "R2": ("pumpfun_smallwallet_r2_prereg.md", "pumpfun_smallwallet_r2.md"),
    "P3": ("ten_eur_p3_prereg.md", None),
    "weekly": ("factory_lockbox_r6.md", None),
    "F2": ("factory_lockbox_r6.md", None),
    "funding_carry": ("funding_carry_prereg.md", "funding_carry.md"),
    "perps_neutral": ("perps_neutral_portfolio_prereg.md", "perps_neutral_portfolio.md"),
    "btc_gated": ("gated_btc_prereg.md", "gated_btc.md"),
    "onchain_meme": ("onchain_meme_prereg.md", "onchain_meme.md"),
    "EQ1": ("etf_books_eq1_prereg.md", "etf_books_eq1.md"),
    "X10": ("pumpfun_realtime_plan.md", "pumpfun_realtime.md"),
    "Y6": ("pumpfun_pool0_prereg.md", None),
    "Y8": ("pumpfun_exits_y8_prereg.md", "pumpfun_exits_y8.md"),
    "Y16": ("pumpfun_rugfilter_prereg.md", "pumpfun_rugfilter.md"),
}
EQ1_JSON = "etf_books_eq1.json"     # EQ1's study numbers per book, variant and broker (lab.experiments.etf_books_eq1)
# A paper book's name in T1's weekly leak check (lab.leak.checks.book_functions).
LEAK_NAMES = {"tsmom": "families", "tsmom_regime": "families", "tsmom_top20": "families",
              "breakout_top10": "families", "memes_rotation": "memes", "memes_tsmom": "memes",
              "btc_gated": "btc_gated", "perps_neutral": "perps_neutral lowvol"}

# The pump.fun rules judged per trade (results/ladder_pumpfun_prereg.md): rule -> (pre-registration, a realistic
# paper book: E_d0_x1 runs on the old paper model only, P_pool0 is the same rule realistic).
PF_RULES = {"P_pool0_wait": ("Y8", True), "P_pool0": ("Y6", True), "P_cmig_model": ("X10", True),
            "P_pool0_wait_norug_half": ("Y16", True), "E_d0_x1": ("X10", False)}
PF_PREREG = "results/ladder_pumpfun_prereg.md"
PF_REAL_FROM_MS = int(datetime(2026, 10, 24, 1, 43, tzinfo=timezone.utc).timestamp() * 1000)   # R1's switch
PF_FRESH_FROM = "2026-10-30"            # step 4: only the days after the pre-registration
PF_REF_DAYS = 10                        # T8's REF_DAYS: the e-process's scale, not tested
PF_REF_SHARPE = 0.1                     # per entry: the e-process's horizon
PF_MIN_ENTRIES, PF_MIN_DAYS = 20, 10    # R7 (factory.MIN_ENTRIES, MIN_DAYS)
PF_LEDGER = "paper/pumpfun_rt/ledger.csv"
PF_REPORT = "reports/pumpfun_rt/realistic.json"

# The conditions in both languages, for the report and the briefing.
COND = {
    "prereg": ("pre-registered", "vorregistriert"),
    "prereg_date": ("pre-registered before its first number", "vor der ersten Zahl vorregistriert"),
    "leak": ("leak check passed (T1)", "Leck-Prüfung bestanden (T1)"),
    "late": ("one close late still positive", "einen Schluss später noch positiv"),
    "era": ("costs of their era", "Kosten ihrer Zeit"),
    "dsr_all": ("DSR over the whole registry >= 0.95", "DSR über das ganze Register >= 0,95"),
    "dsr_family": ("DSR over its family >= 0.95", "DSR über ihre Familie >= 0,95"),
    "pbo": ("PBO of its family < 0.2 (T2)", "PBO ihrer Familie < 0,2 (T2)"),
    "days": (f"{SHADOW_DAYS} days logged", f"{SHADOW_DAYS} Tage aufgezeichnet"),
    "before": ("logged before the outcome (T8)", "vor dem Ergebnis aufgezeichnet (T8)"),
    "look": ("R6's lockbox look made", "R6-Lockbox-Blick gemacht"),
    "bench": ("against the right benchmark", "gegen den richtigen Vergleich"),
    "look_pass": ("lockbox look passed", "Lockbox-Blick bestanden"),
    "record": ("an execution record", "eine Ausführungs-Aufzeichnung"),
    "cap": (f"at most {EXEC_CAP_EUR:g} EUR", f"höchstens {EXEC_CAP_EUR:g} EUR"),
    "topup": (f"no top-up for {EXEC_NO_TOPUP_DAYS} days", f"{EXEC_NO_TOPUP_DAYS} Tage nicht aufgestockt"),
    "reconcile": ("no reconciliation mismatch", "kein Abgleich-Fehler"),
    "failed": (f"never {EXEC_FAILED_IN_A_ROW} failed swaps in a row",
               f"nie {EXEC_FAILED_IN_A_ROW} gescheiterte Swaps in Folge"),
    "costs": (f"costs at most {EXEC_COST_X:g}x the model over {EXEC_COST_SWAPS} swaps",
              f"Kosten höchstens {EXEC_COST_X:g}x Modell über {EXEC_COST_SWAPS} Swaps"),
    "drift": (f"at most {EXEC_DRIFT_PCT:g} % drift from the paper twin",
              f"höchstens {EXEC_DRIFT_PCT:g} % Abweichung vom Papier-Zwilling"),
    "exec_days": (f"{EXEC_DAYS} days judged on execution", f"{EXEC_DAYS} Tage nach Ausführung beurteilt"),
    "owner": ("only the owner decides", "nur der Besitzer entscheidet"),
    "p3_days": ("30 days of the 10 EUR paper book", "30 Tage des 10-EUR-Papierbuchs"),
    "p3_mean": ("mean per trade above 0 after all costs", "Mittel je Trade nach allen Kosten über 0"),
    "p3_band": ("the band's lower end above 0", "untere Bandgrenze über 0"),
    "p3_gap": ("P2's paper minus live under 2 points", "P2: Papier minus live unter 2 Punkten"),
    "p3_taint": ("P1's taint excluded", "P1-Fehlzeilen ausgeschlossen"),
    "p3_book": ("a 10 EUR paper book (P3)", "ein 10-EUR-Papierbuch (P3)"),
    "pf_taint": ("P1's tainted rows out", "P1-Fehlzeilen draußen"),
    "pf_late": ("latency doubled still positive", "doppelte Latenz noch positiv"),
    "pf_era": ("realistic execution only", "nur realistische Ausführung"),
    "pf_scored": (f"{PF_MIN_ENTRIES} entries on {PF_MIN_DAYS} scored days",
                  f"{PF_MIN_ENTRIES} Einstiege an {PF_MIN_DAYS} gewerteten Tagen"),
    "pf_edge": ("edge shown per trade (T8's e-process)", "Vorteil je Trade gezeigt (T8-E-Prozess)"),
    "pf_fresh": (f"edge shown from {PF_FRESH_FROM} on, against 0", f"Vorteil ab {PF_FRESH_FROM} gezeigt, gegen 0"),
}


NO_RECORD = "no tested record"


def cond(cid: str, ok: bool | None, value: str = "", path: str = "") -> dict:
    """One condition: ok True (passes), False (fails, or its evidence is missing) or None (open)."""
    return {"id": cid, "label": COND[cid][0], "ok": ok, "value": value, "path": path}


def _num(v) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _day(ms) -> str | None:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d") if ms else None


def _jsonl(p: Path) -> list[dict]:
    try:
        lines = p.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            r = json.loads(line) if line.strip() else None
        except ValueError:
            continue
        if isinstance(r, dict):
            out.append(r)
    return out


def _days_in(p: Path) -> int:
    """Logged days of a journal or shadow CSV: its unique dates (the date column, else the first; the first 10
    characters), so a rerun's second row of a day is not a second day."""
    try:
        with p.open(encoding="utf-8", newline="") as f:
            rd = csv.reader(f)
            head = next(rd, [])
            i = head.index("date") if "date" in head else 0
            return len({r[i].strip()[:10] for r in rd if len(r) > i and r[i].strip()})
    except (OSError, csv.Error):
        return 0


# ---------------------------------------------------------------- the dates of the pre-registrations

def git_added(path: Path) -> tuple[int, str] | None:
    """When the file was first committed (author time, epoch seconds) and in which commit; None without git (the
    lab server has none)."""
    try:
        r = subprocess.run(["git", "log", "--diff-filter=A", "--format=%at %H", "--", path.name], cwd=path.parent,
                           capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    xs = [(int(a), h) for a, h in (ln.split() for ln in r.stdout.splitlines() if ln.strip())
          if a.isdigit()] if r.returncode == 0 else []
    return min(xs) if xs else None


def title_day(path: Path) -> str | None:
    try:
        head = path.read_text(encoding="utf-8").split("\n", 1)[0]
    except OSError:
        return None
    m = re.search(r"\d{4}-\d{2}-\d{2}", head)
    return m.group() if m else None


def idea(c: dict, ctx: dict) -> list[dict]:
    """Step 1: the study's pre-registration exists and was committed on or before the candidate's first number
    (its results file's commit, else its own first day)."""
    pre = PREREG.get(c.get("prereg") or "")
    if not pre:
        return [cond("prereg", False, f"no pre-registration known for {c.get('prereg') or c['name']}")]
    results = ctx["results"]
    p = results / pre[0]
    rel = f"research/lab/results/{pre[0]}"
    if not p.exists():
        return [cond("prereg", False, f"{pre[0]} missing", rel)]
    added = ctx["added"]
    a = added(p)
    first = added(results / pre[1]) if pre[1] and (results / pre[1]).exists() else None
    if a is not None and first is not None:
        ok = a[1] != first[1] and a[0] <= first[0]          # its own commit, before the results' commit
        v = f"committed {_day(a[0] * 1000)}, its results {_day(first[0] * 1000)}" + (
            "" if a[1] != first[1] else " in the same commit")
    else:
        pday = _day(a[0] * 1000) if a is not None else title_day(p)
        fday = _day(first[0] * 1000) if first is not None else c.get("first_day")
        if pday is None or fday is None:
            ok, v = None, "commit date not checked (no git, no date in its title)" if pday is None else \
                f"pre-registered {pday}, no first number to compare"
        else:
            ok, v = pday <= fday, f"pre-registered {pday}, first number {fday}"
    return [cond("prereg", True, pre[0], rel), cond("prereg_date", ok, v, rel)]


# ---------------------------------------------------------------- step 2: the tested record

def r10_rows(root: Path, results: Path) -> dict[str, dict]:
    """R10's rows by "<study> <name>": the worst of 40 and 100 EUR for the late CAGR and both DSRs, and the kind.
    From reports/smallaccount_r10/latest.json, else the table in results/smallaccount_r10.md."""
    out: dict[str, dict] = {}
    d = notify.read_json(root / "reports" / "smallaccount_r10" / "latest.json")
    if isinstance(d, dict) and isinstance(d.get("rows"), list):
        for r in d["rows"]:
            sizes = [r.get(k) for k in ("late@40", "late@100") if isinstance(r.get(k), dict)]
            if not sizes:
                continue
            out[f"{r.get('study')} {r.get('name')}"] = {
                "late_cagr": min(_num(s.get("cagr")) or 0.0 for s in sizes) * 100,
                "dsr_all": min(_num(s.get("dsr")) or 0.0 for s in sizes),
                "dsr_family": min(_num(s.get("dsr_small")) or 0.0 for s in sizes),
                "crypto": bool(r.get("crypto")), "path": "reports/smallaccount_r10/latest.json"}
        return out
    try:
        text = (results / "smallaccount_r10.md").read_text(encoding="utf-8")
    except OSError:
        return out
    for line in text.split("## 2.")[0].splitlines():
        cells = [x.strip() for x in line.strip().strip("|").split("|")]
        if len(cells) != 8 or not re.fullmatch(r"\d+", cells[1]):
            continue
        late = re.match(r"(-?[\d.]+) %", cells[3])
        dsr = re.match(r"([\d.]+) / ([\d.]+)", cells[6])
        if not late or not dsr:
            continue
        x = {"late_cagr": float(late.group(1)), "dsr_all": float(dsr.group(1)), "dsr_family": float(dsr.group(2)),
             "crypto": "BTC/ETH" in cells[4], "path": "research/lab/results/smallaccount_r10.md"}
        old = out.get(cells[0])
        out[cells[0]] = x if old is None else {**old, **{k: min(old[k], x[k]) for k in ("late_cagr", "dsr_all",
                                                                                         "dsr_family")}}
    return out


def leak_cond(c: dict, ctx: dict) -> dict:
    """Passes only on a positive record: a genome's clean check in leak_passed.jsonl (run.leak_screen), a book's
    passing row in T1's weekly report. A rejection, no record or no report fails."""
    if c["kind"] in ("genome", "shadow"):
        if c["key"] in ctx["leaks"].get(c["source"], set()):
            return cond("leak", False, "rejected by the leak harness", c["leak_path"])
        ok = ctx["leak_ok"].get(c["source"], {}).get(c["key"])
        if ok:
            return cond("leak", True, f"no leak, checked on {ok}", c["leak_ok_path"])
        held = c.get("held_day")
        return cond("leak", False, "no clean leak record" + (" (held back before T1)" if held and held < T1_FROM
                                                             else ""), c["leak_ok_path"])
    rep = ctx["leak_report"]
    if rep is None:
        return cond("leak", False, "not checked (no T1 report)", "reports/leak/latest.json")
    want = c.get("leak_name") or c["name"]
    hit = [r for r in rep if r.get("kind") == "book" and r.get("name") == want]
    if not hit:
        return cond("leak", False, f"not checked ({want} is not in T1's book list)", "reports/leak/latest.json")
    ok = all(r.get("ok") for r in hit)
    return cond("leak", ok, "pass" if ok else str(hit[0].get("why") or "leak"), "reports/leak/latest.json")


def eq1_tested(c: dict, ctx: dict) -> list[dict]:
    """Step 2 of an EQ1 ETF book from its study row at the judged broker (results/etf_books_eq1.json): late CAGR over
    validation, the brokers' stated costs, the DSRs of its excess over the benchmark book (stale against today's
    registry as dsr_now) and the study's PBO."""
    d = ctx.get("eq1") or {}
    p = f"research/lab/results/{EQ1_JSON}"
    r = (d.get("rows") or {}).get((c.get("eq1_book"), c.get("eq1_topup"), d.get("judged")))
    if not r:
        return [cond(x, False, NO_RECORD) for x in ("late", "era", "dsr_all", "dsr_family", "pbo")]
    v = r.get("val") or {}
    cagr = _num(v.get("cagr"))
    out = [cond("late", cagr is not None and cagr > 0, "n/a" if cagr is None else
                f"late CAGR {cagr * 100:.1f} % a year (EQ1, {d.get('judged')}, validation)", p),
           cond("era", True, "the brokers' stated fees, minimums and whole units (EQ1's pre-registration)", p)]
    if c.get("eq1_book") == "hold_sp500":
        why = "the benchmark itself: no excess to deflate"
        out += [cond("dsr_all", False, why, p), cond("dsr_family", False, why, p)]
    else:
        h = {"deflated_p": r.get("dsr_all"), "pool_trials": (d.get("pool_all") or {}).get("n_trials"),
             "dsr_family": r.get("dsr_small"), "family_trials": (d.get("pool_small") or {}).get("n_trials")}
        (dsr, dv), (fam, fv) = dsr_now(h, "small", ctx)
        out += [cond("dsr_all", dsr is not None and dsr >= DSR_PASS, dv, p),
                cond("dsr_family", fam is not None and fam >= DSR_PASS, fv, p)]
    pbo = _num(d.get("pbo"))
    out.append(cond("pbo", pbo is not None and pbo < PBO_MAX, "not measured" if pbo is None else
                    f"{pbo:.2f} over EQ1's eight Trade Republic configurations", p))
    return out


def eq1_row(c: dict, ctx: dict) -> dict | None:
    """What the ladder shows of an EQ1 book: the study's validation CAGR, drawdown, months under water and the
    difference to the benchmark book at the judged broker, and the paper wallet now."""
    d = ctx.get("eq1") or {}
    r = (d.get("rows") or {}).get((c.get("eq1_book"), c.get("eq1_topup"), d.get("judged"))) or {}
    v, b = r.get("val") or {}, c.get("eq1") or {}
    return {"broker": d.get("judged"), **{k: v.get(k) for k in ("cagr", "max_dd", "under_water_months",
                                                               "vs_bench_cagr", "months_beat")},
            "benchmark": c.get("eq1_book") == "hold_sp500", "equity_eur": b.get("equity_eur"),
            "paid_eur": b.get("paid_eur")}


def tested(c: dict, ctx: dict) -> list[dict]:
    """Step 2. The evidence, in order: R10's row (on-chain rules), else the factory's held-back row (EQ1's books:
    their study, eq1_tested)."""
    out = [leak_cond(c, ctx)]
    if c.get("study") == "EQ1":
        return out + eq1_tested(c, ctx)
    r10 = ctx["r10"].get(c.get("r10") or "")
    h = c.get("holdout")
    if r10:
        p = r10["path"]
        out.append(cond("late", r10["late_cagr"] > 0, f"late CAGR {r10['late_cagr']:.1f} % a year (R10, the worse "
                                                      "of 40 and 100 EUR)", p))
        out.append(cond("era", True, "R10: the costs of their era", p))
        out.append(cond("dsr_all", r10["dsr_all"] >= DSR_PASS, f"{r10['dsr_all']:.3f} (higher is better)", p))
        out.append(cond("dsr_family", r10["dsr_family"] >= DSR_PASS,
                        f"{r10['dsr_family']:.3f} over the small family (higher is better)", p))
    elif h:
        p = c["holdout_path"]
        if c["source"] == "weekly":
            late = _num(h.get("oos_late_sharpe"))
            out.append(cond("late", late is not None and late > 0,
                            "n/a" if late is None else f"late Sharpe {late:.2f} at 35 bps", p))
            st = (h.get("gates") or {}).get("stress") or {}
            out.append(cond("era", bool(st.get("passed")), "exchange rule, 70 bps stress: "
                            + str(st.get("why") or "not run"), p))
        else:
            late = _num(h.get("oos_late_cagr"))
            out.append(cond("late", late is not None and late > 0,
                            "n/a" if late is None else f"late CAGR {late * 100:.1f} % a year", p))
            out.append(cond("era", False, "today's Jupiter quotes back to 2018; R10 has no row for it", p))
        (dsr, dv), (fam, fv) = dsr_now(h, c["family"], ctx)
        out.append(cond("dsr_all", dsr is not None and dsr >= DSR_PASS, dv, p))
        out.append(cond("dsr_family", fam is not None and fam >= DSR_PASS, fv, p))
    else:
        why = NO_RECORD
        out += [cond("late", False, why), cond("era", False, why), cond("dsr_all", False, why),
                cond("dsr_family", False, why)]
    pbo = ctx["pbo"].get((c["source"], c.get("run"))) if c.get("run") else None
    if pbo is None:
        out.append(cond("pbo", False, "not measured (T2 not run for it)", c.get("run_path") or ""))
    else:
        out.append(cond("pbo", pbo < PBO_MAX, f"{pbo:.2f} over its run's family", c.get("run_path") or ""))
    return out


def dsr_now(h: dict, family: str, ctx: dict) -> tuple[tuple[float | None, str], tuple[float | None, str]]:
    """(value, text) of the DSR over all and over the family of a held-back row, as of today's registry (R5). With
    its excess series stored (oos_excess_returns) both are recomputed: N today's of all and of the family, the
    variance the family's in-sample excess one (ledger.pool and ledger.deflated_excess). Without it the row's own
    numbers count only while its trial counts are at least DSR_STALE of today's; else None (fails) with why."""
    pool = ctx.get("pool")
    if pool is None:
        why = "R5's registry not readable"
        return (None, why), (None, why)
    n_all, n_fam = pool["n_trials"], pool["families"].get(family, 0)
    x = h.get("oos_excess_returns")
    if isinstance(x, list) and x:
        from ..factory import ledger
        a = np.array([v for v in map(_num, x) if v is not None], dtype=float)
        var = pool["excess_var"].get(family, pool["var"])
        d_all = ledger.deflated(a, {"n_trials": n_all, "var": var})
        d_fam = ledger.deflated(a, {"n_trials": n_fam, "var": var})
        return ((d_all, f"{d_all:.3f} recomputed over today's {n_all:,} trials (higher is better)"),
                (d_fam, f"{d_fam:.3f} recomputed over today's {n_fam:,} {family} trials (higher is better)"))
    out = []
    for v, n, now, what in ((h.get("deflated_p"), h.get("pool_trials"), n_all, "trials"),
                            (h.get("dsr_family"), h.get("family_trials"), n_fam, f"{family} trials")):
        v, n = _num(v), _num(n)
        if v is None:
            out.append((None, "not reported"))
        elif n is None or n < DSR_STALE * now:
            out.append((None, f"stale: {v:.3f} over {'?' if n is None else f'{n:,.0f}'} {what}, today {now:,}, "
                              "no stored series to recompute"))
        else:
            out.append((v, f"{v:.3f} over {n:,.0f} {what}, today {now:,} (higher is better)"))
    return out[0], out[1]


# ---------------------------------------------------------------- steps 3 to 6

def shadow(c: dict, ctx: dict) -> list[dict]:
    n, p = c.get("days_logged"), c.get("days_path") or ""
    days = cond("days", n is not None and n >= SHADOW_DAYS,
                "no daily record" if n is None else f"{n} of {SHADOW_DAYS} days", p)
    t8 = ctx["t8"].get(c["id"])
    before = cond("before", False, "not checked (no T8 report for it)", "reports/shadow/latest.json") if t8 is None else \
        cond("before", bool(t8.get("ok")), str(t8.get("why") or ""), "reports/shadow/latest.json")
    return [days, before]


def lockbox(c: dict, ctx: dict) -> list[dict]:
    want = BENCH[c["bench"]]
    mine = [x for x in ctx["looks"] if x.get("key") == c.get("key")
            or (c.get("behaviour") and x.get("behaviour") == c.get("behaviour"))] if c.get("key") else []
    if not mine:
        return [cond("look", False, "never looked at in the lockbox (2026-07-01 on)", "factory/lockbox.jsonl")]
    x = mine[0]
    got = x.get("benchmark") or LOOK_BENCH.get(str(x.get("factory")), "?")
    dsr = _num(x.get("dsr"))
    return [cond("look", True, f"look {x.get('look')} on {x.get('date')}", "factory/lockbox.jsonl"),
            cond("bench", got == want, f"against {BENCH_TEXT.get(got, got)}, needs {BENCH_TEXT[want]}",
                 "factory/lockbox.jsonl"),
            cond("look_pass", dsr is not None and dsr >= LOCKBOX_BAR,
                 "n/a" if dsr is None else f"DSR {dsr:.2f} over {x.get('looks')} looks (needs {LOCKBOX_BAR})",
                 "factory/lockbox.jsonl")]


def p3_gate(c: dict) -> list[dict]:
    """Step 5 of a P3 book: the gate for real money from realistic.json's `ten` row (realistic.ten_status)."""
    b, p = c.get("p3") or {}, "reports/pumpfun_rt/realistic.json"
    g = b.get("gate") or {}

    def pc(x):
        return "n/a" if _num(x) is None else f"{x * 100:+.1f} %"
    band = b.get("band") if isinstance(b.get("band"), list) and len(b["band"]) == 2 else None
    pts = _num(b.get("gap_pts"))
    return [cond("p3_days", bool(g.get("days")), f"{_num(b.get('days')) or 0:.1f} of 30 days", p),
            cond("p3_mean", bool(g.get("mean")), f"{pc(b.get('mean'))} over {b.get('trades') or 0} trades", p),
            cond("p3_band", bool(g.get("band")), "no band (under 10 trades)" if band is None
                 else f"{pc(band[0])} to {pc(band[1])}", p),
            cond("p3_gap", bool(g.get("gap")), "not measured" if pts is None else f"{pts:+.1f} points", p),
            cond("p3_taint", bool(g.get("taint")), f"{b.get('tainted') or 0} tainted trades left out", p)]


def execution(c: dict, ctx: dict, now: int) -> list[dict]:
    """Step 5 from an execution record: {"start": day, "cap_eur", "topups": [day], "swaps": [{"ok", "cost_bps",
    "model_bps"}], "reconcile_mismatches", "drift_pct"}. A P3 book: its gate (p3_gate)."""
    if c.get("study") == "P3":
        return p3_gate(c)
    r = ctx["execution"].get(c["name"]) or ctx["execution"].get(c["id"])
    p = "reports/execution/latest.json"
    if not isinstance(r, dict):
        return [cond("record", False, "no real-money execution record (the 50 EUR phase has not started)", p)]
    start = str(r.get("start") or "")
    try:
        t0 = int(datetime.fromisoformat(start[:10]).replace(tzinfo=timezone.utc).timestamp() * 1000)
    except ValueError:
        return [cond("record", False, "the record has no start day", p)]
    days = (now - t0) / DAY_MS
    cap = _num(r.get("cap_eur"))
    tops = [d for d in r.get("topups") or [] if isinstance(d, str) and d[:10] >= start[:10]]
    early = [d for d in tops if (datetime.fromisoformat(d[:10]).replace(tzinfo=timezone.utc).timestamp() * 1000 - t0)
             / DAY_MS < EXEC_NO_TOPUP_DAYS]
    swaps = [s for s in r.get("swaps") or [] if isinstance(s, dict)]
    run = worst = 0
    for s in swaps:
        run = 0 if s.get("ok") else run + 1
        worst = max(worst, run)
    last = [s for s in swaps if s.get("ok")][-EXEC_COST_SWAPS:]
    cost, model = sum(_num(s.get("cost_bps")) or 0 for s in last), sum(_num(s.get("model_bps")) or 0 for s in last)
    ratio = cost / model if model > 0 else None
    mism = int(_num(r.get("reconcile_mismatches")) or 0)
    drift = _num(r.get("drift_pct"))
    return [cond("record", True, f"since {start[:10]}, {len(swaps)} swaps", p),
            cond("cap", cap is not None and cap <= EXEC_CAP_EUR, "n/a" if cap is None else f"{cap:g} EUR", p),
            cond("topup", not early, f"{len(early)} top-up(s) in the first {EXEC_NO_TOPUP_DAYS} days", p),
            cond("reconcile", mism == 0, f"{mism} mismatch(es)", p),
            cond("failed", worst < EXEC_FAILED_IN_A_ROW, f"at most {worst} in a row", p),
            cond("costs", len(last) >= EXEC_COST_SWAPS and ratio is not None and ratio <= EXEC_COST_X,
                 f"{len(last)} swaps" + ("" if ratio is None else f", {ratio:.2f}x the model"), p),
            cond("drift", drift is not None and abs(drift) <= EXEC_DRIFT_PCT,
                 "n/a" if drift is None else f"{drift:+.2f} %", p),
            cond("exec_days", days >= EXEC_DAYS, f"{days:.0f} of {EXEC_DAYS} days", p)]


def climb(steps: dict[int, list[dict]]) -> tuple[int, list[dict], list[dict]]:
    """The highest step whose conditions and those of every step before have no fail (from FAIL_CLOSED_FROM on an
    open condition is a fail); the next step's fails; the open conditions up to that next step that do not block."""
    def blocks(k: int, x: dict) -> bool:
        return x["ok"] is False or (x["ok"] is None and k >= FAIL_CLOSED_FROM)
    step = 0
    for k in sorted(steps):
        if any(blocks(k, x) for x in steps[k]):
            break
        step = k
    nxt = steps.get(step + 1, [])
    missing = [x for x in nxt if blocks(step + 1, x)]
    opened = [x for k in sorted(steps) if k <= step + 1 for x in steps[k] if x["ok"] is None and not blocks(k, x)]
    return step, missing, opened


def next_text(missing: list[dict]) -> str:
    """The missing conditions, those with the same reason together: "a, b: why; c: why"."""
    by: dict[str, list[str]] = {}
    for x in missing:
        by.setdefault(x["value"], []).append(x["label"])
    return "; ".join(", ".join(ls) + (f": {v}" if v else "") for v, ls in by.items())


def judge(c: dict, ctx: dict, now: int) -> dict:
    if c["kind"] == "rule":
        c = {**c, "first_day": ctx["pf"]["first"].get(c["name"])}
        steps = {1: idea(c, ctx), 2: pf_tested(c, ctx), 3: pf_shadow(c, ctx), 4: pf_lockbox(c, ctx),
                 5: pf_execution(c, ctx)}
    else:
        steps = {1: idea(c, ctx), 2: tested(c, ctx), 3: shadow(c, ctx), 4: lockbox(c, ctx), 5: execution(c, ctx, now)}
    steps[6] = [cond("owner", False, "the ladder never sets this step")]
    step, missing, opened = climb(steps)
    ev = next((x["path"] for x in missing if x["path"]), "") or next(
        (x["path"] for x in reversed(steps.get(step, [])) if x["path"]), "")
    return {"id": c["id"], "name": c["name"], "short": c.get("short") or c["name"], "kind": c["kind"],
            "study": c.get("study") or "",
            "benchmark": BENCH_TEXT[BENCH[c["bench"]]], "step": step, "step_name": STEPS[step],
            "next": next_text(missing),
            "next_de": "kein getesteter Bericht" if missing and all(x["value"] == NO_RECORD for x in missing)
            else "; ".join(COND[x["id"]][1] for x in missing),
            "missing": [x["id"] for x in missing], "open": [x["id"] for x in opened], "evidence": ev,
            "tainted": (ctx["pf"]["rules"][c["name"]]["tainted"] if c["kind"] == "rule" else c.get("tainted")) or 0,
            **({"p3": p3_row(c["p3"])} if c.get("p3") else {}),
            **({"eq1": eq1_row(c, ctx)} if c.get("study") == "EQ1" else {}),
            **({"pumpfun": pf_row(c, ctx)} if c["kind"] == "rule" else {}),
            "steps": {str(k): v for k, v in steps.items()}}


def p3_row(b: dict) -> dict:
    """What the ladder shows of a P3 book: its wallet in EUR, trades, mean and median per trade after all costs, the
    band, days, the gate."""
    return {k: b.get(k) for k in ("eur", "sol", "trades", "mean", "median", "band", "days", "pass", "can_pay")}


# ---------------------------------------------------------------- the pump.fun rules, per trade

def pf_trials() -> list[dict]:
    return [{"id": f"pumpfun:ladder:{r}", "family": "pumpfun", "n": 1, "sharpe": None, "source": PF_PREREG}
            for r in PF_RULES]


def _rows(p: Path, keep) -> tuple[list[dict], bool]:
    """The rows of a paper CSV whose first column (rule) is in keep, and whether the file was read."""
    try:
        with p.open(encoding="utf-8", newline="") as f:
            rd = csv.reader(f)
            head = next(rd, [])
            return [dict(zip(head, r)) for r in rd if r and r[0] in keep], True
    except (OSError, csv.Error):
        return [], False


def pf_entries(rows: list[dict], fails: list[dict], since_ms: int) -> tuple[list[tuple[int, float]], int]:
    """One rule's entries since since_ms in signal order, (signal_ms, return): its closed trades (ret, every cost of
    the fit in it) less P1's tainted rows and the restart closes, and its failed buys (the fee over the median stake of
    its trades); and how many tainted rows were left out."""
    from ..pumpfun_rt import realistic as R
    out, stakes, bad = [], [], 0
    for r in rows:
        sig, ret = R._f(r.get("signal_ms")), R._f(r.get("ret"))
        if sig is None or ret is None or sig < since_ms or r.get("exit_why") == "restart":
            continue
        if R.tainted(r):
            bad += 1
            continue
        out.append((int(sig), ret))
        stakes.append(R._f(r.get("stake_sol")) or 0.0)
    st = float(np.median([x for x in stakes if x > 0])) if any(x > 0 for x in stakes) else 0.0
    for x in fails:
        sig, pnl = R._f(x.get("signal_ms")), R._f(x.get("pnl_sol"))
        if sig is not None and pnl is not None and sig >= since_ms and st > 0:
            out.append((int(sig), pnl / st))
    return sorted(out), bad


def pf_record(entries: list[tuple[int, float]], now: int, n_all: int | None, n_fam: int | None,
              sharpes: list[float] | None) -> dict:
    """R7's numbers of one rule's entries (factory.by_day, factory.deflated over n_all and n_fam with F3's per-entry
    Sharpes as the noise), T8's e-process on the day sums (step 3 after the first PF_REF_DAYS days, step 4 on the
    days from PF_FRESH_FROM on) and the days still needed at its current mean."""
    from ..paper import power
    from ..pumpfun_rt import factory as F
    from scipy import stats as st
    x = np.array([r for _, r in entries], dtype=float)
    n = len(x)
    out = {"entries": n, "days_record": (now - entries[0][0]) / DAY_MS if n else 0.0, "mean": None, "lo": None,
           "hi": None, "n_eff": 0.0, "days_traded": 0, "sharpe": 0.0, "dsr_all": None, "dsr_family": None,
           "e": None, "e_fresh": None, "edge_day": None, "fresh_day": None, "to_bar": None, "to_power": None}
    if not n:
        return out
    days = sorted({_day(t) for t, _ in entries})
    idx = {d: i for i, d in enumerate(days)}
    day = np.array([idx[_day(t)] for t, _ in entries], dtype=int)
    sd = float(x.std(ddof=1)) if n > 1 else 0.0
    r = {"entries": n, "sharpe": float(x.mean() / sd) if sd > 0 else 0.0,
         "skew": float(((x - x.mean()) ** 3).mean() / sd ** 3) if sd > 0 else 0.0,
         "kurt": float(((x - x.mean()) ** 4).mean() / sd ** 4) if sd > 0 else 3.0} | F.by_day(x, day, len(days))
    out.update({"mean": float(x.mean()), "lo": r["lo"], "hi": r["hi"], "n_eff": r["n_eff"],
                "days_traded": r["days_traded"], "sharpe": r["sharpe"]})
    ok = sharpes is not None and len([v for v in sharpes if math.isfinite(v)]) >= 2
    if ok and n_all:
        out["dsr_all"] = F.deflated(r, sharpes, n_all)
    if ok and n_fam:
        out["dsr_family"] = F.deflated(r, sharpes, n_fam)
    ys = np.array(r["day_pnl"], dtype=float)                  # the day sums of the entries' returns
    if len(days) > PF_REF_DAYS and float(np.mean(ys[:PF_REF_DAYS] ** 2)) > 0:
        ref = day < PF_REF_DAYS
        per_day = F.by_day(x[ref], day[ref], PF_REF_DAYS)["n_eff"] / PF_REF_DAYS
        if per_day > 0:
            horizon = (power.z_sum() / PF_REF_SHARPE) ** 2 / per_day
            rho = power.rho_for(float(np.mean(ys[:PF_REF_DAYS] ** 2)), horizon)
            e = power.e_path(ys[PF_REF_DAYS:], rho)
            k = power.first_cross(e)
            out.update({"e": float(e[-1]), "edge_day": days[PF_REF_DAYS + k] if k is not None else None})
            fresh = [i for i in range(PF_REF_DAYS, len(days)) if days[i] >= PF_FRESH_FROM]
            if fresh:
                ef = power.e_path(ys[fresh], rho)
                k = power.first_cross(ef)
                out.update({"e_fresh": float(ef[-1]), "fresh_day": days[fresh[k]] if k is not None else None})
    rate = r["n_eff"] / out["days_record"] if out["days_record"] > 0 else 0.0
    s = r["sharpe"]
    if rate > 0 and ok and n_all:
        sr0 = F.bar(sharpes, n_all)
        q = 1 - r["skew"] * s + (r["kurt"] - 1) / 4 * s ** 2
        need = 1 + (float(st.norm.ppf(F.BAR_P)) * math.sqrt(q) / (s - sr0)) ** 2 if s > sr0 and q > 0 else math.inf
        out["to_bar"] = max(need / rate - out["days_record"], PF_MIN_DAYS - r["days_traded"], 0.0)
    if rate > 0:
        need = power.fixed_days(s)                           # (z_0.95 + z_0.80)^2 / S^2 entries, inf at S <= 0
        out["to_power"] = max(need / rate - out["days_record"], PF_REF_DAYS + 1 - r["days_traded"], 0.0)
    return out


def pf_context(root: Path, now: int) -> dict:
    """What the pump.fun rules' steps read, once: each rule's record (pf_record) from the paper ledger since realistic
    execution began, the lat 2x stress of the real-time report, P2's selection gap and P3's books of realistic.json,
    R5's pool with pf_trials and F3's ledger."""
    from ..pumpfun_rt import factory as F
    paper = root / "paper" / "pumpfun_rt"
    st = notify.read_json(paper / "state.json")
    since = max(PF_REAL_FROM_MS, int(_num((st or {}).get("realistic_since")) or 0) if isinstance(st, dict) else 0)
    rows, read = _rows(paper / "ledger.csv", PF_RULES)
    fails, _ = _rows(paper / "failed.csv", PF_RULES)
    f3 = F.read_ledger(root / "pumpfun_rt" / "factory" / "ledger.jsonl")
    sharpes, n_f3 = F.pool(f3)
    n_all = n_fam = None
    try:
        from .. import metrics
        p = metrics.trial_pool(extra=pf_trials())
        n_all = p["n_trials"] + n_f3
        n_fam = p["families"].get("pumpfun", {}).get("n_trials", 0) + n_f3
    except Exception:  # noqa: BLE001 - fails closed: no pool, no DSR passes
        pass
    lt = notify.read_json(root / "reports" / "pumpfun_rt" / "latest.json")
    lat = {}
    for r in (lt or {}).get("results") or [] if isinstance(lt, dict) else []:
        m = _num((((r or {}).get("stress") or {}).get("lat2x") or {}).get("mean")) if isinstance(r, dict) else None
        if m is not None:
            lat[r.get("rule")] = m
    rj = notify.read_json(root / PF_REPORT)
    rj = rj if isinstance(rj, dict) else {}
    out = {"read": read, "since": since, "n_all": n_all, "n_fam": n_fam, "n_f3": n_f3, "lat2x": lat,
           "selection": rj.get("selection") if isinstance(rj.get("selection"), dict) else None,
           "ten": {str(t.get("book")): t for t in rj.get("ten") or [] if isinstance(t, dict)}, "rules": {},
           "first": {}}
    for r in rows:                                            # step 1's first number: the rule's first ledger day
        t = _num(int(r["signal_ms"])) if str(r.get("signal_ms") or "").isdigit() else None
        if t is not None and (r["rule"] not in out["first"] or _day(t) < out["first"][r["rule"]]):
            out["first"][r["rule"]] = _day(t)
    for rule, (_, real) in PF_RULES.items():
        es, bad = pf_entries([r for r in rows if r.get("rule") == rule], [x for x in fails if x.get("rule") == rule],
                             since) if real else ([], 0)
        out["rules"][rule] = {**pf_record(es, now, n_all, n_fam, sharpes if len(sharpes) >= 2 else None),
                              "tainted": bad, "realistic": real}
    return out


def _pc(x) -> str:
    return "n/a" if _num(x) is None else f"{x * 100:+.1f} %"


def pf_tested(c: dict, ctx: dict) -> list[dict]:
    """Step 2 of a pump.fun rule: P1 out, lat 2x above 0, realistic execution, R7's entries and days, both DSRs."""
    pf, p = ctx["pf"], PF_LEDGER
    x = pf["rules"][c["name"]]
    out = [cond("pf_taint", pf["read"], f"{x['tainted']} tainted rows left out (P1)" if pf["read"] else
                "no paper ledger", p)]
    lat = pf["lat2x"].get(c["name"])
    out.append(cond("pf_late", lat is not None and lat > 0, "not in the real-time report" if lat is None else
                    f"{_pc(lat)} a trade at twice the latency (lat 2x, out of sample)", "reports/pumpfun_rt/latest.json"))
    if not x["realistic"]:
        why = "no realistic record: it runs on the old paper model only"
        return out + [cond("pf_era", False, why, p), cond("pf_scored", False, why, p), cond("dsr_all", False, why, p),
                      cond("dsr_family", False, why, p)]
    out.append(cond("pf_era", x["entries"] > 0, f"realistic since {_day(pf['since'])}, {x['entries']} entries", p))
    out.append(cond("pf_scored", x["entries"] >= PF_MIN_ENTRIES and x["days_traded"] >= PF_MIN_DAYS,
                    f"{x['entries']} entries on {x['days_traded']} of {PF_MIN_DAYS} days", p))
    for k, n, what in (("dsr_all", pf["n_all"], "trials"), ("dsr_family", pf["n_fam"], "pumpfun trials")):
        v = x[k]
        out.append(cond(k, v is not None and v >= DSR_PASS, "no pool (R5 or F3's ledger unreadable)" if v is None
                        else f"{v:.3f} per entry over {n:,} {what}, {x['n_eff']:.0f} effective entries "
                             "(higher is better)", p))
    return out


def pf_shadow(c: dict, ctx: dict) -> list[dict]:
    x = ctx["pf"]["rules"][c["name"]]
    e = x["e"]
    v = (f"edge shown on {x['edge_day']}" if x["edge_day"] else f"E {e:.2f} of 20") if e is not None else \
        f"no test before {PF_REF_DAYS + 1} days with entries"
    return [cond("pf_edge", bool(x["edge_day"]), v, PF_LEDGER)]


def pf_lockbox(c: dict, ctx: dict) -> list[dict]:
    x = ctx["pf"]["rules"][c["name"]]
    e = x["e_fresh"]
    v = (f"edge shown on {x['fresh_day']}" if x["fresh_day"] else f"E {e:.2f} of 20") if e is not None else \
        f"no day from {PF_FRESH_FROM} on after the first {PF_REF_DAYS}"
    return [cond("pf_fresh", bool(x["fresh_day"]), v, PF_LEDGER)]


def pf_execution(c: dict, ctx: dict) -> list[dict]:
    """Step 5: P2's selection gap (under 2 points) and P3's gate of the rule's 10 EUR book; absent is open."""
    pf, p = ctx["pf"], PF_REPORT
    sel = pf["selection"]
    pts = _num((sel or {}).get("pts"))
    gap = cond("p3_gap", None, "open: no P2 selection gap in realistic.json", p) if sel is None else \
        cond("p3_gap", sel.get("pass") is True, "not measured" if pts is None else f"{pts:+.1f} points (P2)", p)
    ten = pf["ten"].get(f"{c['name']}_10eur")
    if ten is None:
        return [gap, cond("p3_book", None, "open: no 10 EUR paper book (P3) for it", p)]
    return [gap] + [x for x in p3_gate({"p3": ten}) if x["id"] != "p3_gap"]


def pf_row(c: dict, ctx: dict) -> dict:
    x = ctx["pf"]["rules"][c["name"]]
    return {k: x[k] for k in ("days_record", "entries", "n_eff", "days_traded", "mean", "lo", "hi", "dsr_all",
                              "dsr_family", "e", "e_fresh", "to_bar", "to_power", "tainted", "realistic")}


def _days_left(v) -> str:
    if v is None:
        return "n/a"
    return "never at its mean" if not math.isfinite(v) else f"{v:,.0f}"


def pf_md(rows: list[dict]) -> list[str]:
    if not rows:
        return []
    md = ["", f"pump.fun rules per trade ({PF_PREREG}): the realistic paper record since "
          f"{_day(PF_REAL_FROM_MS)} 01:43 UTC, P1's tainted rows out; mean per entry with R7's band (clustered by UTC "
          f"day); DSR per entry over R5 and F3's trials, all / pumpfun (higher is better, pass at {DSR_PASS}); E: T8's "
          "e-process on the day sums (edge at 20); days still needed at the current mean per entry to step 2's bar "
          "and to T8's power at 0.", "",
          "| rule | step | next missing | days of record | entries (effective) | mean per entry | band | DSR | E | "
          "days needed: bar / power |", "|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        x = r["pumpfun"]
        dsr = "n/a" if x["dsr_all"] is None else f"{x['dsr_all']:.3f} / {x['dsr_family']:.3f}"
        cells = [r["name"], f"{r['step']} {r['step_name']}", r["next"] or "-", f"{x['days_record']:.1f}",
                 f"{x['entries']} ({x['n_eff']:.0f})", _pc(x["mean"]),
                 "n/a" if x["lo"] is None else f"{_pc(x['lo'])} to {_pc(x['hi'])}", dsr,
                 "n/a" if x["e"] is None else f"{x['e']:.2f}", f"{_days_left(x['to_bar'])} / {_days_left(x['to_power'])}"]
        md.append("| " + " | ".join(notify.nodash(str(v)).replace("|", "/") for v in cells) + " |")
    return md


# ---------------------------------------------------------------- the candidates

def _book_kind(b: dict) -> tuple[str, str | None, str, str | None]:
    """(benchmark kind, pre-registration key, family, R10 row) of a paper book."""
    s, n = b["study"], b["name"]
    if s in ("S1", "S2"):
        rule = n.split("_", 1)[1] if "_" in n else n
        return ("small" if s == "S2" else "crypto"), s, "small", f"{s} {rule}"
    if s == "L1":
        return "crypto", None, "small", f"L1 {n}"
    if s in ("R2", "F3", "P3"):
        return "crypto", s, "pumpfun", None
    if s == "EQ1":
        return "small", "EQ1", "small", None
    pre = n if n in PREREG else ("onchain_meme" if n.startswith("onchain_meme_") else None)
    return ("neutral" if n in NEUTRAL_BOOKS else "crypto"), pre, "hand", None


def candidates(root: Path, now: int) -> list[dict]:
    rep = root / "reports"
    out: dict[str, dict] = {}
    fw = notify.read_json(rep / "forward" / "latest.json")
    fdays = {str(b.get("name")): b for b in (fw or {}).get("books") or [] if isinstance(b, dict)} \
        if isinstance(fw, dict) else {}
    for b in paper_books.books(root):
        bench, pre, fam, r10 = _book_kind(b)
        n = b["name"]
        j = root / "paper" / n / "journal.csv"
        logged = _days_in(j) if j.exists() else None
        if logged is None and _num((fdays.get(n) or {}).get("days")) is not None:
            logged = int(fdays[n]["days"])
        out[f"book:{n}"] = {"id": f"book:{n}", "name": n, "kind": "book", "study": b["study"], "source": "book",
                            "bench": bench, "prereg": pre, "family": fam, "r10": r10, "first_day": b.get("start"),
                            "leak_name": f"smallaccount {n}" if b["study"] in ("S1", "S2") else LEAK_NAMES.get(n),
                            "days_logged": logged, "days_path": f"paper/{n}/journal.csv" if j.exists() else b["report"],
                            "tainted": b.get("tainted") or 0, "p3": b.get("p3"),
                            **({"eq1": b["eq1"], "eq1_book": b["eq1"].get("book"), "eq1_topup": b["eq1"].get("topup")}
                               if isinstance(b.get("eq1"), dict) else {})}
    fac = root / "factory"
    for source, d, hp in (("weekly", fac, "factory/holdout.jsonl"), ("F2", fac / "small", "factory/small/holdout.jsonl")):
        rows = _jsonl(d / "holdout.jsonl")
        last = {}
        for h in rows:
            if h.get("key"):
                last[h["key"]] = h
        for k, h in last.items():
            if h.get("decision") in (None, "stopped"):
                continue
            out[f"{source}:{k}"] = genome(source, h, hp, "genome")
    for p in sorted((fac / "shadow").glob("*.json")):
        m = notify.read_json(p)
        if not isinstance(m, dict) or m.get("status") != "active" or not m.get("key"):
            continue
        h = {**(m.get("holdout") or {}), "key": m["key"], "name": m.get("name"), "run": m.get("entered_run"),
             "date": m.get("entry_day")}
        c = out.get(f"weekly:{m['key']}") or genome("weekly", h, "factory/holdout.jsonl", "shadow")
        csv_p = fac / "shadow" / f"{m['key']}.csv"
        c.update({"kind": "shadow", "days_logged": _days_in(csv_p), "days_path": f"factory/shadow/{m['key']}.csv"})
        out[c["id"]] = c
    f2 = notify.read_json(rep / "smallaccount" / "factory.json")
    f2_held = {h["key"]: h for h in _jsonl(fac / "small" / "holdout.jsonl") if h.get("key")}
    for m in (f2 or {}).get("shadows") or [] if isinstance(f2, dict) else []:
        if not isinstance(m, dict) or m.get("status") != "active" or not m.get("key"):
            continue
        c = out.get(f"F2:{m['key']}") or genome("F2", {**f2_held.get(m["key"], {}), "key": m["key"],
                                                         "name": m.get("name")}, "factory/small/holdout.jsonl", "shadow")
        c.update({"kind": "shadow", "days_logged": int(_num(m.get("days")) or 0) if m.get("days") is not None else None,
                  "days_path": "reports/smallaccount/factory.json"})
        out[c["id"]] = c
    g2 = notify.read_json(rep / "models" / "factory.json")
    for m in (g2 or {}).get("shadows") or [] if isinstance(g2, dict) else []:
        if not isinstance(m, dict) or m.get("status") == "retired" or not m.get("key"):
            continue
        out[f"G2:{m['key']}"] = {"id": f"G2:{m['key']}", "name": f"G2 {m.get('target') or ''} {m['key']}".strip(),
                                 "short": f"G2 {str(m['key'])[:8]}",
                                 "kind": "model", "study": "G2", "source": "G2", "bench": "crypto", "prereg": None,
                                 "family": "hand", "key": None, "days_logged": _num(m.get("scored_days")),
                                 "days_path": "reports/models/factory.json", "first_day": m.get("added_day")}
    if (root / PF_LEDGER).exists() or (root / PF_REPORT).exists():
        for rule, (pre, _) in PF_RULES.items():
            out[f"pumpfun:{rule}"] = {"id": f"pumpfun:{rule}", "name": rule, "kind": "rule", "study": "PF",
                                      "source": "pumpfun", "bench": "pumpfun", "prereg": pre, "family": "pumpfun"}
    return list(out.values())


def genome(source: str, h: dict, path: str, kind: str) -> dict:
    k = h["key"]
    small = source == "F2"
    return {"id": f"{source}:{k}", "name": f"{source} {k} {h.get('name') or ''}".strip(),
            "short": f"{source} {k[:8]}", "kind": kind,
            "study": source, "source": source, "key": k, "behaviour": h.get("behaviour"),
            "bench": "small" if small else "crypto", "prereg": source, "family": "small" if small else "factory",
            "r10": f"F2 f2 {k}" if small else None, "holdout": h, "holdout_path": path, "run": h.get("run"),
            "run_path": f"factory/{'small/' if small else ''}runs/{h.get('run')}.json", "held_day": h.get("date"),
            "first_day": h.get("date") or h.get("run"),
            "leak_path": "factory/small/leaks.jsonl" if small else "factory/leaks.jsonl",
            "leak_ok_path": "factory/small/leak_passed.jsonl" if small else "factory/leak_passed.jsonl"}


# ---------------------------------------------------------------- what the steps read, once

def context(root: Path, results: Path = RESULTS, added=None, now: int | None = None) -> dict:
    fac = root / "factory"
    pbo: dict = {}
    for source, d in (("weekly", fac / "runs"), ("F2", fac / "small" / "runs")):
        for p in sorted(d.glob("*.json")) if d.is_dir() else []:
            r = notify.read_json(p)
            fam = ((r or {}).get("night") or {}).get("family") if isinstance(r, dict) else None
            if isinstance(fam, dict) and _num(fam.get("pbo")) is not None:
                pbo[(source, p.stem)] = float(fam["pbo"])
    lk = notify.read_json(root / "reports" / "leak" / "latest.json")
    t8 = notify.read_json(root / "reports" / "shadow" / "latest.json")
    ex = notify.read_json(root / "reports" / "execution" / "latest.json")
    r10 = r10_rows(root, results)
    eq = notify.read_json(results / EQ1_JSON)
    eq = {**eq, "rows": {(r.get("book"), r.get("variant"), r.get("broker")): r for r in eq.get("rows") or []
                         if isinstance(r, dict)}} if isinstance(eq, dict) else {}
    pf = pf_context(root, now or notify.clock_ms()) if (root / PF_LEDGER).exists() or (root / PF_REPORT).exists() \
        else None
    return {"results": results, "eq1": eq, "added": added or git_added, "r10": r10, "pbo": pbo, "pool": today_pool(),
            "pf": pf,
            "leaks": {"weekly": {x.get("key") for x in _jsonl(fac / "leaks.jsonl")},
                      "F2": {x.get("key") for x in _jsonl(fac / "small" / "leaks.jsonl")}},
            "leak_ok": {s: {x["key"]: str(x.get("date") or "") for x in _jsonl(d / "leak_passed.jsonl")
                            if x.get("key") and x.get("ok") is True}
                        for s, d in (("weekly", fac), ("F2", fac / "small"))},
            "leak_report": [r for r in lk.get("results") or [] if isinstance(r, dict)] if isinstance(lk, dict) else None,
            "looks": _jsonl(fac / "lockbox.jsonl"),
            "t8": {str(r.get("id")): r for r in (t8 or {}).get("rows") or [] if isinstance(r, dict)}
            if isinstance(t8, dict) else {},
            "execution": (ex or {}).get("books") or {} if isinstance(ex, dict) else {}}


def today_pool() -> dict | None:
    """Today's R5 pool for dsr_now: N of all and of each family, the variance of all and each factory family's
    in-sample excess variance (the variance of all below ledger.EXCESS_MIN excess Sharpes, as ledger.pool); None
    when the registry cannot be read (every DSR then fails)."""
    try:
        from .. import metrics
        from ..factory import ledger
        p = metrics.trial_pool()
        ev = {}
        for f in ("factory", "small"):
            v, n = ledger.excess_var(f)
            ev[f] = v if n >= ledger.EXCESS_MIN else p["var"]
        return {"n_trials": p["n_trials"], "var": p["var"], "excess_var": ev,
                "families": {f: x["n_trials"] for f, x in p["families"].items()}}
    except Exception:  # noqa: BLE001 - fails closed: no pool, no DSR passes
        return None


def build(root: Path | None = None, now: int | None = None, results: Path = RESULTS, added=None) -> dict:
    root = Path(root) if root is not None else notify.data_root()
    now = now or notify.clock_ms()
    ctx = context(root, results, added, now)
    rows = sorted((judge(c, ctx, now) for c in candidates(root, now)), key=lambda r: (-r["step"], len(r["missing"]), r["name"].lower()))
    counts = {str(k): sum(1 for r in rows if r["step"] == k) for k in STEPS}
    top = rows[0]["step"] if rows else 0
    headline = (f"{len(rows)} candidates; the highest step is {top} ({STEPS[top]}), "
                f"{counts[str(top)]} there. Nothing is armed: the ladder only proposes.") if rows else "no candidate"
    pool = None
    try:
        from .. import metrics
        p = metrics.trial_pool()
        pool = {"n_trials": p["n_trials"], "sr0_annual": p["sr0_annual"]}
    except Exception:  # noqa: BLE001 - the header's pool is information only
        pass
    items = [{"label": r["name"], "value": f"{r['step']} {r['step_name']}", "detail": r["next"] or "-",
              "status": "ok" if r["step"] >= 4 else "watch"} for r in rows[:10]]
    return {"title": "Readiness ladder", "status": "watch", "headline": headline, "updated_ms": now, "items": items,
            "generated": _day(now), "steps": STEPS, "counts": counts, "registry": pool,
            "tainted": sum(r["tainted"] for r in rows),
            "constants": {"dsr_pass": DSR_PASS, "pbo_max": PBO_MAX, "shadow_days": SHADOW_DAYS,
                          "lockbox_bar": LOCKBOX_BAR, "exec_cap_eur": EXEC_CAP_EUR, "exec_days": EXEC_DAYS},
            "rows": rows}


def markdown(d: dict) -> str:
    reg = d.get("registry") or {}
    md = [f"# Readiness ladder, {d['generated']}\n",
          "Each step requires the one before: 1 idea (pre-registered), 2 tested (leak check, one close late, costs of "
          "their era, DSR over the registry and the family, PBO), 3 shadow, 4 lockbox, 5 execution (50 EUR), 6 larger "
          "(only the owner). `results/readiness_ladder_prereg.md`. DSR: higher is better, pass at 0.95, as of today's "
          "registry"
          + (f"; R5's registry holds {reg['n_trials']:,} trials" if reg.get("n_trials") else "") + ". "
          "Open (not blocking, step 1 only): the commit date without git. From step 2 on missing evidence fails. "
          "Nothing here arms anything.\n",
          f"**{d['headline']}**\n",
          "| candidate | kind | step | next missing | open | evidence |", "|---|---|---|---|---|---|"]
    for r in d["rows"]:
        cells = [r["name"], r["kind"], f"{r['step']} {r['step_name']}", r["next"] or "-",
                 ", ".join(r["open"]) or "-", r["evidence"] or "-"]
        md.append("| " + " | ".join(notify.nodash(str(x)).replace("|", "/") for x in cells) + " |")
    ten = [r for r in d["rows"] if r.get("p3")]
    if ten:
        def pc(x):
            return "n/a" if _num(x) is None else f"{x * 100:+.1f} %"
        md += ["", "10 EUR pump.fun paper books (P3, results/ten_eur_p3_prereg.md): the gate for real money (step 5; "
               "30 days, mean and the band's lower end above 0 after all costs, P2's gap under 2 points, P1's taint "
               "out). Passing proposes; only the owner decides.", "",
               "| book | wallet EUR | trades | mean | median | 95 % band | days | gate |",
               "|---|---|---|---|---|---|---|---|"]
        for r in ten:
            x = r["p3"]
            band = x.get("band") if isinstance(x.get("band"), list) and len(x["band"]) == 2 else None
            gate = "passes" if x.get("pass") else "fails: " + ", ".join(
                COND[c["id"]][0] for c in r["steps"]["5"] if c["ok"] is False)
            cells = [r["name"], "n/a" if _num(x.get("eur")) is None else f"{x['eur']:.2f}", x.get("trades") or 0,
                     pc(x.get("mean")), pc(x.get("median")), "n/a" if band is None else f"{pc(band[0])} to "
                     f"{pc(band[1])}", f"{_num(x.get('days')) or 0:.1f}", gate]
            md.append("| " + " | ".join(notify.nodash(str(v)).replace("|", "/") for v in cells) + " |")
    eq = [r for r in d["rows"] if r.get("eq1")]
    if eq:
        def pc(x, sign=""):
            return "n/a" if _num(x) is None else f"{x * 100:{sign}.1f} %"
        md += ["", "EQ1's ETF books (results/etf_books_eq1.md): the study's validation window at the judged broker, "
               "time-weighted, one close late, against holding SXR8 (the benchmark book); the paper wallet now.", "",
               "| book | broker | CAGR | max DD | longest months under water | CAGR minus benchmark | months beat | "
               "paper wallet EUR (paid in) |", "|---|---|---|---|---|---|---|---|"]
        for r in eq:
            x = r["eq1"]
            cells = [r["name"], x.get("broker") or "n/a", pc(x.get("cagr")), pc(x.get("max_dd")),
                     "n/a" if _num(x.get("under_water_months")) is None else f"{x['under_water_months']:.0f}",
                     "benchmark" if x.get("benchmark") else pc(x.get("vs_bench_cagr"), "+"),
                     "" if x.get("benchmark") else pc(x.get("months_beat")),
                     "n/a" if _num(x.get("equity_eur")) is None else
                     f"{x['equity_eur']:.2f} ({_num(x.get('paid_eur')) or 0:.0f})"]
            md.append("| " + " | ".join(notify.nodash(str(v)).replace("|", "/") for v in cells) + " |")
    md += pf_md([r for r in d["rows"] if r.get("pumpfun")])
    if d.get("tainted"):
        md.append(f"\nThe pump.fun books' evidence leaves out {d['tainted']} paper trades the late-row bug made (P1, "
                  "results/pumpfun_ledger_taint_p1.md).")
    return "\n".join(md) + "\n"


def out_dir() -> Path:
    return notify.reports_root() / NAME


def publish(d: dict) -> None:
    if any(r.get("kind") == "rule" for r in d.get("rows") or []):
        from .. import metrics
        metrics.register(pf_trials())                         # the pump.fun rules' five trials, before the numbers
    notify.write_json(out_dir() / "latest.json", d)
    (out_dir() / "latest.md").write_text(markdown(d), encoding="utf-8")


def by_book(d: dict | None) -> dict[str, dict]:
    """Book name to its row, for Lab Live's nodes."""
    return {r["id"][5:]: r for r in (d or {}).get("rows") or [] if str(r.get("id", "")).startswith("book:")}


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    d = build()
    if "--print" in argv:
        notify.say(markdown(d))
        return 0
    publish(d)
    notify.say(f"ladder: {len(d['rows'])} candidates, by step {d['counts']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
