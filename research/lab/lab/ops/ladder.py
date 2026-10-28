"""The readiness ladder (T3): on which step every candidate stands, what it misses next and where the evidence is.

Pre-registered in results/readiness_ladder_prereg.md. One row per candidate: every paper book (lab.ops.paper_books),
every survivor of the weekly factory and F2 (<data>/factory/holdout.jsonl, factory/small/holdout.jsonl, a decision
other than stopped), every active shadow (the weekly factory's <data>/factory/shadow/*.json, F2's and G2's report).
Each step requires the one before:

  1 idea       a pre-registration (PREREG) committed on or before the candidate's first number
  2 tested     T1's leak check passed, filled one close late still positive, costs of their era, DSR (higher is
               better, pass at 0.95) over R5's whole registry and over its family, PBO of its family below 0.2
  3 shadow     SHADOW_DAYS days logged before the outcome (T8 checks the "before"; until then that part is open)
  4 lockbox    R6's one look made, against the right benchmark (BENCH), and passed
  5 execution  at most 50 EUR under the review's rules, judged on execution after 90 days (reports/execution)
  6 larger     only by the owner; the ladder never sets it

A condition passes, fails or is open (its tool is not there yet for this candidate: T1, T2, T8); open never blocks,
missing evidence fails. The ladder computes no performance number (no trial), reads only, and writes nothing but
reports/ladder/latest.json and .md. It proposes; it never arms, changes or sends anything.

  python -m lab.ops.ladder            write the report (the Lab Live job also writes it every run)
  python -m lab.ops.ladder --print    print the table, write nothing
"""

from __future__ import annotations

import csv
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

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
EXEC_CAP_EUR = 50.0
EXEC_NO_TOPUP_DAYS = 90
EXEC_FAILED_IN_A_ROW = 2
EXEC_COST_X, EXEC_COST_SWAPS = 2.0, 10
EXEC_DRIFT_PCT = 1.0
EXEC_DAYS = 90

# What each kind is judged against at the lockbox; what each factory's look is against (R6).
BENCH = {"crypto": "btc_eth", "small": "ucits", "neutral": "zero"}
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
    "weekly": ("factory_lockbox_r6.md", None),
    "F2": ("factory_lockbox_r6.md", None),
    "funding_carry": ("funding_carry_prereg.md", "funding_carry.md"),
    "perps_neutral": ("perps_neutral_portfolio_prereg.md", "perps_neutral_portfolio.md"),
    "btc_gated": ("gated_btc_prereg.md", "gated_btc.md"),
    "onchain_meme": ("onchain_meme_prereg.md", "onchain_meme.md"),
}
# A paper book's name in T1's weekly leak check (lab.leak.checks.book_functions).
LEAK_NAMES = {"tsmom": "families", "tsmom_regime": "families", "tsmom_top20": "families",
              "breakout_top10": "families", "memes_rotation": "memes", "memes_tsmom": "memes",
              "btc_gated": "btc_gated", "perps_neutral": "perps_neutral lowvol"}

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


def _rows_in(p: Path) -> int:
    try:
        with p.open(encoding="utf-8", newline="") as f:
            return sum(1 for _ in csv.DictReader(f))
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
    if c["kind"] in ("genome", "shadow"):
        bad = ctx["leaks"].get(c["source"], set())
        if c["key"] in bad:
            return cond("leak", False, "rejected by the leak harness", c["leak_path"])
        held = c.get("held_day")
        if held and held >= T1_FROM:
            return cond("leak", True, f"checked before its look on {held}", c["leak_path"])
        return cond("leak", None, "not checked (held back before T1)")
    rep = ctx["leak_report"]
    if rep is None:
        return cond("leak", None, "not checked (no T1 report yet)")
    want = c.get("leak_name") or c["name"]
    hit = [r for r in rep if r.get("kind") == "book" and r.get("name") == want]
    if not hit:
        return cond("leak", None, f"not checked ({want} is not in T1's book list)")
    ok = all(r.get("ok") for r in hit)
    return cond("leak", ok, "pass" if ok else str(hit[0].get("why") or "leak"), "reports/leak/latest.json")


def tested(c: dict, ctx: dict) -> list[dict]:
    """Step 2. The evidence, in order: R10's row (on-chain rules), else the factory's held-back row."""
    out = [leak_cond(c, ctx)]
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
        dsr, fam = _num(h.get("deflated_p")), _num(h.get("dsr_family"))
        out.append(cond("dsr_all", dsr is not None and dsr >= DSR_PASS,
                        "n/a" if dsr is None else f"{dsr:.3f} (higher is better)", p))
        out.append(cond("dsr_family", fam is not None and fam >= DSR_PASS,
                        "not reported" if fam is None else f"{fam:.3f} (higher is better)", p))
    else:
        why = NO_RECORD
        out += [cond("late", False, why), cond("era", False, why), cond("dsr_all", False, why),
                cond("dsr_family", False, why)]
    pbo = ctx["pbo"].get((c["source"], c.get("run"))) if c.get("run") else None
    if pbo is None:
        out.append(cond("pbo", None, "not measured (T2 not run for it)"))
    else:
        out.append(cond("pbo", pbo < PBO_MAX, f"{pbo:.2f} over its run's family", c.get("run_path") or ""))
    return out


# ---------------------------------------------------------------- steps 3 to 6

def shadow(c: dict, ctx: dict) -> list[dict]:
    n, p = c.get("days_logged"), c.get("days_path") or ""
    days = cond("days", n is not None and n >= SHADOW_DAYS,
                "no daily record" if n is None else f"{n} of {SHADOW_DAYS} days", p)
    t8 = ctx["t8"].get(c["id"])
    before = cond("before", None, "not checked (T8 not there yet)") if t8 is None else \
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


def execution(c: dict, ctx: dict, now: int) -> list[dict]:
    """Step 5 from an execution record: {"start": day, "cap_eur", "topups": [day], "swaps": [{"ok", "cost_bps",
    "model_bps"}], "reconcile_mismatches", "drift_pct"}."""
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
    """The highest step whose conditions and those of every step before have no fail; the next step's fails; the
    open conditions up to that next step."""
    step = 0
    for k in sorted(steps):
        if any(x["ok"] is False for x in steps[k]):
            break
        step = k
    nxt = steps.get(step + 1, [])
    missing = [x for x in nxt if x["ok"] is False]
    opened = [x for k in sorted(steps) if k <= step + 1 for x in steps[k] if x["ok"] is None]
    return step, missing, opened


def next_text(missing: list[dict]) -> str:
    """The missing conditions, those with the same reason together: "a, b: why; c: why"."""
    by: dict[str, list[str]] = {}
    for x in missing:
        by.setdefault(x["value"], []).append(x["label"])
    return "; ".join(", ".join(ls) + (f": {v}" if v else "") for v, ls in by.items())


def judge(c: dict, ctx: dict, now: int) -> dict:
    steps = {1: idea(c, ctx), 2: tested(c, ctx), 3: shadow(c, ctx), 4: lockbox(c, ctx), 5: execution(c, ctx, now),
             6: [cond("owner", False, "the ladder never sets this step")]}
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
            "tainted": c.get("tainted") or 0,
            "steps": {str(k): v for k, v in steps.items()}}


# ---------------------------------------------------------------- the candidates

def _book_kind(b: dict) -> tuple[str, str | None, str, str | None]:
    """(benchmark kind, pre-registration key, family, R10 row) of a paper book."""
    s, n = b["study"], b["name"]
    if s in ("S1", "S2"):
        rule = n.split("_", 1)[1] if "_" in n else n
        return ("small" if s == "S2" else "crypto"), s, "small", f"{s} {rule}"
    if s == "L1":
        return "crypto", None, "small", f"L1 {n}"
    if s in ("R2", "F3"):
        return "crypto", s, "pumpfun", None
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
        logged = _rows_in(j) if j.exists() else None
        if logged is None and _num((fdays.get(n) or {}).get("days")) is not None:
            logged = int(fdays[n]["days"])
        out[f"book:{n}"] = {"id": f"book:{n}", "name": n, "kind": "book", "study": b["study"], "source": "book",
                            "bench": bench, "prereg": pre, "family": fam, "r10": r10, "first_day": b.get("start"),
                            "leak_name": f"smallaccount {n}" if b["study"] in ("S1", "S2") else LEAK_NAMES.get(n),
                            "days_logged": logged, "days_path": f"paper/{n}/journal.csv" if j.exists() else b["report"],
                            "tainted": b.get("tainted") or 0}
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
        c.update({"kind": "shadow", "days_logged": _rows_in(csv_p), "days_path": f"factory/shadow/{m['key']}.csv"})
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
            "leak_path": "factory/small/leaks.jsonl" if small else "factory/leaks.jsonl"}


# ---------------------------------------------------------------- what the steps read, once

def context(root: Path, results: Path = RESULTS, added=None) -> dict:
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
    return {"results": results, "added": added or git_added, "r10": r10, "pbo": pbo,
            "leaks": {"weekly": {x.get("key") for x in _jsonl(fac / "leaks.jsonl")},
                      "F2": {x.get("key") for x in _jsonl(fac / "small" / "leaks.jsonl")}},
            "leak_report": [r for r in lk.get("results") or [] if isinstance(r, dict)] if isinstance(lk, dict) else None,
            "looks": _jsonl(fac / "lockbox.jsonl"),
            "t8": {str(r.get("id")): r for r in (t8 or {}).get("rows") or [] if isinstance(r, dict)}
            if isinstance(t8, dict) else {},
            "execution": (ex or {}).get("books") or {} if isinstance(ex, dict) else {}}


def build(root: Path | None = None, now: int | None = None, results: Path = RESULTS, added=None) -> dict:
    root = Path(root) if root is not None else notify.data_root()
    now = now or notify.clock_ms()
    ctx = context(root, results, added)
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
          "(only the owner). `results/readiness_ladder_prereg.md`. DSR: higher is better, pass at 0.95"
          + (f"; R5's registry holds {reg['n_trials']:,} trials" if reg.get("n_trials") else "") + ". "
          "Open (not blocking): a tool that is not there yet for the candidate. Nothing here arms anything.\n",
          f"**{d['headline']}**\n",
          "| candidate | kind | step | next missing | open | evidence |", "|---|---|---|---|---|---|"]
    for r in d["rows"]:
        cells = [r["name"], r["kind"], f"{r['step']} {r['step_name']}", r["next"] or "-",
                 ", ".join(r["open"]) or "-", r["evidence"] or "-"]
        md.append("| " + " | ".join(notify.nodash(str(x)).replace("|", "/") for x in cells) + " |")
    if d.get("tainted"):
        md.append(f"\nThe pump.fun books' evidence leaves out {d['tainted']} paper trades the late-row bug made (P1, "
                  "results/pumpfun_ledger_taint_p1.md).")
    return "\n".join(md) + "\n"


def out_dir() -> Path:
    return notify.reports_root() / NAME


def publish(d: dict) -> None:
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
