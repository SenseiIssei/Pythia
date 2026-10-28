"""Lab Live: one graph of everything that runs in the lab, for the app's Lab Live page (?page=lablive).

Built from the data folder only (read only, every 5 minutes, job `lablive`) into reports/lablive/latest.json; the
server serves that file as GET /api/lab/live and adds nothing. Nodes:

  data       the recorder (its status file), the pump.fun record, every collector job
  features   the feature store and the jobs that tag or cache inputs
  models     every model of the zoo (reports/models), the pump.fun zoo's labels, the allocator, the model jobs
  factories  the strategy factory, F2 (small accounts), F3 (pump.fun), the studies
  books      every paper book of the forward report and the paper jobs, with its step on the readiness ladder
             (lab.ops.ladder, T3), which this job also writes to reports/ladder every run
  money      the real-money bots (pump.fun, the on-chain trader)
  outputs    the briefing, the lab card, the alerts, Discord, News, health, backup

Per node: kind, name, one plain German sentence what it does, state (running, ok, late, failed, off), last and next
run (the job table in _health/jobs.json), its latest numbers, a short history for a sparkline, its last runs
(_ops/runs) and its last log lines when the job's log is mounted (PYTHIA_LOGS, default /logs; scrubbed of
addresses, keys and hosts). Edges: what feeds what (depends_on of the table plus the fixed map below).

Nothing here trades, writes a setting or reads a key: the live bots' status files are read for their state and
numbers only, never their wallet address.

  python -m lab.ops.lablive            write reports/lablive/latest.json
  python -m lab.ops.lablive --print    print it, write nothing
"""

from __future__ import annotations

import csv
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import ladder as ladder_mod, notify

COLUMNS = ("data", "features", "models", "factories", "books", "money", "outputs")
STATES = ("running", "ok", "late", "failed", "off")
RUNS_KEPT = 30
RUNS_SHOWN = 6
LOG_LINES = 8
SPARK_POINTS = 60
MINUTE = 60_000
HOUR = 60 * MINUTE

# Jobs by name: the column they sit in (first match wins), the rest go to factories (the studies).
JOB_COLUMNS = (
    ("outputs", ("briefing", "labor", "notify", "notify-pending", "discord-feed", "discord-live-fills", "weekly-report",
                 "health", "backup", "prune", "news", "lablive", "local-llm", "agent-research", "agent-care", "costs",
                 "candles-health", "dexscreener-health", "pumpfun-rt-health")),
    ("money", ("pumpfun-live-watch", "pumpfun-live-simulate", "onchain-live-watch", "onchain-live-simulate",
               "onchain-execution", "onchain-history")),
    ("features", ("features", "llm-news")),
    ("data", ("backfill", "flow-collect", "wiki-collect", "candles-live", "candles-markets", "candles-compact",
              "trending", "dexscreener-collect", "listings", "news-collect", "cs2-collect", "polymarket-daily",
              "polymarket-history", "kraken-futures-collect", "pumpfun-activity", "free-deribit", "free-hyperliquid",
              "free-feargreed", "free-macro", "free-defillama")),
    ("models", ("models", "retrain", "learn", "readiness", "m2-v3-shadow", "modern-models", "pumpfun-rt-retrain",
                "ai-brief", "ai-critic", "ai-director", "ai-weekly", "ai-analyst", "ai-news", "pumpfun-rt-categories")),
    ("books", ("paper", "forward", "exit-shadow", "cs2-run", "pokemon", "onchain-paper", "onchain-sol-book",
               "onchain-longterm", "onchain-mark", "onchain-meme", "onchain-meme-proof", "pumpfun-rt-realistic")),
)

# What a job does, in one German sentence; the others say their column's sentence and keep the table's description.
JOB_WHAT = {
    "features": "Der Feature-Store: legt jede Nacht die aufgezeichneten Orderbücher, Trades, Funding und Open Interest als Stundenmerkmale ab.",
    "models": "Der Modell-Zoo: trainiert nach, was fällig ist, macht Schatten-Prognosen und prüft die Drift.",
    "learn": "Die Lernschleife: rechnet die Bücher nach und prüft jede Strategie gegen ihre Hürde.",
    "forward": "Der Vorwärtsbericht: vergleicht jedes Paper-Buch mit dem, was sein Backtest erwarten ließ.",
    "paper": "Führt die Paper-Bücher einen Tag weiter, ohne echtes Geld.",
    "briefing": "Das Morgenbriefing um 9 Uhr Berlin an Telegram und Discord.",
    "labor": "Die Laborkarte um 20 Uhr Berlin: was Fabriken, Zoo und Allokator heute getan haben.",
    "health": "Prüft jede Stunde jeden Job, jeden Container, jeden Datenstrom und die Platte.",
    "news": "Schreibt aus den Ereignissen des Labors Artikel für Pythia News.",
    "lablive": "Baut diese Karte: alles, was im Labor läuft, als ein Graph.",
    "pumpfun-factory": "Die F3-Fabrik: sucht jede Nacht neue pump.fun-Regeln und prüft sie auf zurückgehaltenen Tagen.",
    "factory-small": "Die F2-Fabrik: sucht täglich Regeln für kleine Wallets zu echten Jupiter-Kosten.",
    "factory-weekly": "Die Strategie-Fabrik: wöchentliche Suche mit zurückgehaltenen Prüfungen, jeder Versuch im Ledger.",
    "factory-shadow": "Die Strategie-Fabrik im Schatten: führt ihre Kandidaten täglich auf Papier weiter.",
    "pumpfun-live-watch": "Wacht alle zwei Minuten über den Echtgeld-Bot für pump.fun und meldet sofort, wenn etwas nicht stimmt.",
    "onchain-live-watch": "Wacht alle zwei Minuten über den Echtgeld-Händler der eigenen Wallet.",
    "news-collect": "Sammelt Krypto-Schlagzeilen aus RSS-Feeds (nur Titel).",
    "llm-news": "Das lokale Modell ordnet jede neue Schlagzeile einem Thema und einer Relevanz zu.",
    "dexscreener-collect": "Liest DexScreeners Listen der beworbenen und neuen Tokens.",
    "readiness": "Prüft jeden Autopiloten gegen die vorab festgelegte Regel für echtes Geld.",
}
COLUMN_WHAT = {
    "data": "Sammelt Daten für das Labor.",
    "features": "Bereitet Eingaben für die Modelle auf.",
    "models": "Ein Modell- oder Forschungsjob.",
    "factories": "Eine Studie oder ein Forschungslauf.",
    "books": "Führt Paper-Bücher, ohne echtes Geld.",
    "money": "Hat mit echtem Geld zu tun; dieser Job liest nur und meldet.",
    "outputs": "Berichtet, meldet oder hält das System sauber.",
}

# What feeds what, beyond depends_on. Pairs whose ends are not in the graph are dropped.
EDGES = (
    ("src:recorder", "job:features"), ("src:recorder", "job:learn"), ("src:recorder", "job:paper"),
    ("job:backfill", "job:paper"), ("job:features", "job:models"), ("job:features", "job:factory-weekly"),
    ("job:kraken-futures-collect", "job:paper-funding-carry"), ("job:flow-collect", "job:models"),
    ("job:news-collect", "job:llm-news"), ("job:llm-news", "job:briefing"), ("job:news-collect", "job:ai-news"),
    ("job:dexscreener-collect", "job:trending"), ("job:dexscreener-collect", "job:dexscreener-study"),
    ("job:cs2-collect", "job:cs2-run"), ("job:polymarket-daily", "job:polymarket-study"),
    ("src:pumpfun_rt", "factory:F3"), ("src:pumpfun_rt", "job:pumpfun-rt-retrain"), ("src:pumpfun_rt", "bot:pumpfun"),
    ("src:pumpfun_rt", "job:pumpfun-rt-realistic"), ("src:pumpfun_rt", "job:pumpfun-activity"),
    ("job:pumpfun-rt-retrain", "model:allocator"), ("job:pumpfun-factory", "factory:F3"),
    ("job:factory-small", "factory:F2"), ("job:factory-weekly", "factory:strategy"),
    ("job:factory-shadow", "factory:strategy"), ("model:allocator", "bot:pumpfun"),
    ("bot:pumpfun", "job:pumpfun-live-watch"), ("bot:onchain", "job:onchain-live-watch"),
    ("job:onchain-paper", "bot:onchain"), ("job:onchain-history", "bot:onchain"),
    ("job:paper", "job:forward"), ("job:forward", "job:briefing"), ("job:forward", "job:discord-feed"),
    ("job:models", "job:discord-feed"), ("job:learn", "job:readiness"),
    ("factory:F3", "job:labor"), ("factory:F2", "job:labor"), ("model:allocator", "job:labor"),
    ("job:health", "job:briefing"), ("job:health", "job:news"), ("job:forward", "job:news"),
    ("factory:F3", "job:news"), ("factory:F2", "job:news"), ("factory:strategy", "job:news"),
    ("bot:pumpfun", "job:news"), ("bot:pumpfun", "job:briefing"), ("job:news", "job:lablive"),
    ("src:pumpfun_rt", "job:pumpfun"), ("src:pumpfun_rt", "job:pumpfun-rt-categories"),
    ("src:pumpfun_rt", "job:pumpfun-rt-health"), ("job:pumpfun", "job:pumpfun-report"),
    ("bot:pumpfun", "job:pumpfun-live-simulate"), ("bot:onchain", "job:onchain-live-simulate"),
    ("job:onchain-meme", "job:onchain-meme-proof"), ("job:onchain-meme", "job:forward"),
    ("job:onchain-mark", "job:forward"), ("job:pokemon", "job:briefing"), ("job:cs2-trends", "job:briefing"),
    ("job:retrain", "job:models"), ("job:m2-v3-shadow", "job:forward"), ("job:costs", "job:learn"),
    ("job:discord-live-fills", "bot:onchain"), ("job:health", "job:weekly-report"),
)

# Base58 runs (addresses, signatures), long hex or token-like strings, IPv4 and e-mail addresses, URL queries.
SCRUB = (
    (re.compile(r"\b[1-9A-HJ-NP-Za-km-z]{32,90}\b"), "<adresse>"),
    (re.compile(r"\b[0-9a-fA-F]{32,}\b"), "<hex>"),
    (re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b"), "<ip>"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "<mail>"),
    (re.compile(r"(https?://[^\s?#]+)[?#]\S*"), r"\1"),
    (re.compile(r"(?i)\b(key|token|secret|password|api[_-]?key|auth)(\s*[=:]\s*)\S+"), r"\1\2<weg>"),
)


def scrub(line: str, n: int | None = 300) -> str:
    s = notify.nodash(str(line)).rstrip()
    for rx, sub in SCRUB:
        s = rx.sub(sub, s)
    return s[:n] if n else s


def _num(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x and abs(x) != float("inf") else None


def de(x, d: int = 2, unit: str = "") -> str:
    """A number the German way (1.234,5), with an optional unit after a space."""
    v = _num(x)
    if v is None:
        return "-"
    s = f"{v:,.{d}f}".replace(",", "_").replace(".", ",").replace("_", ".")
    return f"{s} {unit}".strip()


def de_pct(x, d: int = 1, sign: bool = True) -> str:
    v = _num(x)
    if v is None:
        return "-"
    return ("+" if sign and v > 0 else "") + de(v, d) + " %"


def iso_ms(s) -> int | None:
    if not isinstance(s, str) or not s:
        return None
    try:
        return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp() * 1000)
    except ValueError:
        return None


def ms_iso(ms) -> str | None:
    v = _num(ms)
    return datetime.fromtimestamp(v / 1000, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if v else None


def stamp(d) -> int | None:
    if not isinstance(d, dict):
        return None
    for k in ("updated_ms", "updatedMs", "generated_ms", "generatedMs", "t", "ts"):
        v = _num(d.get(k))
        if v and v > 1e12:
            return int(v)
    return None


def column_of(job: str) -> str:
    for col, names in JOB_COLUMNS:
        if job in names:
            return col
    if job.startswith("paper-"):
        return "books"
    if job.endswith("-collect") or job.startswith("free-"):
        return "data"
    return "factories"


def job_state(j: dict) -> str:
    if not j.get("enabled", True) or j.get("state") == "disabled":
        return "off"
    if j.get("running"):
        return "running"
    st = str(j.get("state") or "")
    if st in ("failed", "blocked", "timeout"):
        return "failed"
    if st in ("late", "stuck", "overdue"):
        return "late"
    return "ok"


# ---------------------------------------------------------------- reading

def read_runs(root: Path, now: int) -> dict[str, list[dict]]:
    """The runner's records of this and last month, per job, oldest first, the last RUNS_KEPT each."""
    d = root / "_ops" / "runs"
    out: dict[str, list[dict]] = {}
    files = sorted(d.glob("*.jsonl"))[-2:] if d.is_dir() else []
    for p in files:
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if isinstance(r, dict) and r.get("job"):
                out.setdefault(str(r["job"]), []).append(
                    {"start": r.get("start"), "end": r.get("end"), "status": r.get("status"),
                     "duration_s": _num(r.get("duration_s")), "exit_code": r.get("exit_code")})
    return {k: v[-RUNS_KEPT:] for k, v in out.items()}


def log_tail(name: str, logs: Path | None, n: int = LOG_LINES) -> list[str]:
    if logs is None or not re.fullmatch(r"[a-z0-9-]+", name):
        return []
    p = logs / f"{name}.log"
    try:
        with p.open("rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - 16_384))
            text = f.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return [scrub(ln) for ln in lines[-n:]]


def journal_series(p: Path, col: str = "equity", n: int = SPARK_POINTS) -> tuple[list[float], dict]:
    """The last n values of a book's journal column and its last row."""
    try:
        with p.open(encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
    except (OSError, csv.Error):
        return [], {}
    vals = [v for v in (_num(r.get(col)) for r in rows[-n:]) if v is not None]
    return vals, (rows[-1] if rows else {})


# ---------------------------------------------------------------- the graph

def node(nid: str, kind: str, name: str, column: str, what: str, **kw) -> dict:
    n = {"id": nid, "kind": kind, "name": name, "column": column, "what": what, "detail": "", "state": "ok",
         "now": "", "last_run": None, "next_run": None, "numbers": [], "spark": [], "spark_label": "",
         "runs": [], "logs": [], "inputs": [], "outputs": [], "job": None}
    n.update(kw)
    return n


def fresh_state(at: int | None, now: int, max_age_ms: int, base: str = "ok") -> str:
    if base in ("off", "failed", "running"):
        return base
    if at is None or now - at > max_age_ms:
        return "late"
    return base


def job_nodes(jobs: list[dict], runs: dict, logs: Path | None, now: int) -> list[dict]:
    out = []
    for j in jobs:
        name = str(j.get("name") or "")
        if not name:
            continue
        col = column_of(name)
        st = job_state(j)
        last = j.get("last") if isinstance(j.get("last"), dict) else {}
        rr = runs.get(name, [])
        since = str(j.get("runningSince") or "")[11:16]
        doing = {"running": f"läuft seit {since} UTC" if since else "läuft gerade",
                 "off": "ausgeschaltet in der Jobtabelle",
                 "failed": f"letzter Lauf fehlgeschlagen ({notify.short(scrub(j.get('detail') or ''), 120)})"}.get(st)
        if doing is None:
            doing = f"wartet auf den nächsten Lauf ({str(j.get('nextRun') or '')[:16].replace('T', ' ')} UTC)" \
                if j.get("nextRun") else "läuft nach seinen Vorgängern"
        nums = [{"label": "Läufe in Folge fehlgeschlagen", "value": str(int(_num(j.get("consecutiveFailures")) or 0))}]
        durs = [r["duration_s"] for r in rr if r.get("duration_s") is not None]
        if durs:
            nums.append({"label": "Dauer zuletzt", "value": de(durs[-1], 0, "s")})
        out.append(node(
            f"job:{name}", "job", name, col, JOB_WHAT.get(name, COLUMN_WHAT[col]),
            detail=notify.nodash(str(j.get("description") or "")), state=st, now=doing,
            last_run=last.get("end") or last.get("start"), next_run=j.get("nextRun"), numbers=nums,
            spark=durs[-SPARK_POINTS:], spark_label="Dauer der letzten Läufe in Sekunden",
            runs=list(reversed(rr[-RUNS_SHOWN:])), logs=log_tail(name, logs), job=name,
            schedule=j.get("schedule"), depends_on=[str(x) for x in (j.get("depends_on") or j.get("after") or [])]))
    return out


def recorder_node(root: Path, now: int) -> dict | None:
    st = notify.read_json(root / "_health" / "status.json")
    if not isinstance(st, dict):
        return None
    at = iso_ms(st.get("at"))
    streams = st.get("streams") if isinstance(st.get("streams"), dict) else {}
    stale = sorted(k for k, v in streams.items() if isinstance(v, dict) and v.get("stale"))
    state = "late" if at is None or now - at > 15 * MINUTE else ("late" if stale else "running")
    nums = [{"label": "Datenströme", "value": str(len(streams))},
            {"label": "davon veraltet", "value": ", ".join(stale) if stale else "keiner"}]
    if _num(st.get("disk_free_gb")) is not None:
        nums.append({"label": "Platte frei", "value": de(st["disk_free_gb"], 1, "GB")})
    return node("src:recorder", "source", "Rekorder", "data",
                "Zeichnet rund um die Uhr Orderbücher und Trades von Binance, Kraken, Bybit, OKX und Coinbase auf.",
                state=state, now="zeichnet auf" if state == "running" else "keine frische Statusdatei",
                last_run=ms_iso(at), numbers=nums)


def pumpfun_record_node(rep: Path, now: int) -> dict | None:
    tr = notify.read_json(rep / "pumpfun_rt" / "trends.json")
    lt = notify.read_json(rep / "pumpfun_rt" / "latest.json")
    if not isinstance(tr, dict) and not isinstance(lt, dict):
        return None
    t = tr.get("trends", tr) if isinstance(tr, dict) else {}
    at = _num((t or {}).get("written_ms")) or stamp(lt)
    state = "running" if at and now - at < 5 * MINUTE else "late"
    nums = []
    if isinstance(t, dict) and _num(t.get("tracked")) is not None:
        nums.append({"label": "Coins mit Trade in 15 min", "value": de(t["tracked"], 0)})
    return node("src:pumpfun_rt", "source", "pump.fun-Aufzeichnung", "data",
                "Liest jeden pump.fun-Trade direkt von der Chain und führt damit die Paper-Engine.",
                state=state, now="liest die Chain" if state == "running" else "schreibt gerade nichts",
                last_run=ms_iso(at), numbers=nums)


def model_nodes(rep: Path, now: int) -> list[dict]:
    out = []
    zoo = notify.read_json(rep / "models" / "latest.json")
    for m in (zoo or {}).get("models") or [] if isinstance(zoo, dict) else []:
        if not isinstance(m, dict) or not m.get("code"):
            continue
        status = str(m.get("status") or "")
        st = "off" if status == "retired" else "failed" if m.get("last_status") not in (None, "ok") else "ok"
        nums = [{"label": "Status", "value": status or "-"}]
        live = m.get("live") if isinstance(m.get("live"), dict) else {}
        if _num(live.get("model")) is not None:
            nums.append({"label": "Letzte Prognose, Fehler", "value": de(live["model"], 4)})
            nums.append({"label": "Basislinie", "value": de(live.get("baseline"), 4)})
        gain = _num(live.get("gain_pct")) if live else None
        gain = gain if gain is not None else _num(m.get("gain_pct"))
        if gain is not None:
            nums.append({"label": "Besser als die Basislinie", "value": de_pct(gain)})
        if _num(live.get("win_rate")) is not None:
            nums.append({"label": "Trefferquote", "value": de_pct(100 * live["win_rate"], 0, sign=False)})
        champ = (m.get("champion") or {}).get("version") if isinstance(m.get("champion"), dict) else None
        if champ:
            nums.append({"label": "Champion", "value": str(champ)})
        weeks = [w for w in (live.get("weeks") or []) if isinstance(w, dict)]
        spark = [v for v in (_num(w.get("gain_pct")) for w in weeks) if v is not None]
        title = notify.nodash(str(m.get("title") or m.get("name")))
        out.append(node(f"model:{m['code']}", "model", f"{m['code']} {title}", "models",
                        f"Ein Modell des Zoos: {title}. Ziel: {notify.short(notify.nodash(str(m.get('target') or '-')), 140)}",
                        detail=notify.nodash(str(m.get("status_detail") or m.get("use_rule") or "")), state=st,
                        now="im Ruhestand" if st == "off" else f"wartet auf das Nachtraining ({m.get('next_due') or '-'})",
                        last_run=ms_iso(m.get("last_retrain_ms")), numbers=nums, spark=spark,
                        spark_label="Vorsprung vor der Basislinie je Woche, %", job="models",
                        aliases=[str(m["code"]), str(m.get("name") or "")],
                        used_by=[str(u).split(" ")[0] for u in m.get("used_by") or []]))
    pz = notify.read_json(rep / "pumpfun_rt" / "zoo.json")
    at = stamp(pz)
    for label, v in ((pz or {}).get("labels") or {}).items() if isinstance(pz, dict) else []:
        if not isinstance(v, dict):
            continue
        pick = v.get("pick")
        loss = _num((v.get("nday") or {}).get(pick)) if isinstance(v.get("nday"), dict) else None
        nums = [{"label": "Auswahl", "value": str(pick or "-")}, {"label": "Tage bewertet", "value": str(v.get("days") or 0)}]
        if loss is not None:
            nums.append({"label": "Verlust der Auswahl", "value": de(loss, 4)})
        nums.append({"label": "Mitglieder", "value": ", ".join(str(x) for x in v.get("members") or []) or "-"})
        out.append(node(f"model:zoo-{label}", "model", f"pump.fun-Zoo {label}", "models",
                        f"Die Modelle für das Label {label} der pump.fun-Coins; der Selektor wählt täglich das beste.",
                        state=fresh_state(at, now, 30 * HOUR), now=f"wählt {pick}" if pick else "noch keine Wahl",
                        last_run=ms_iso(at), numbers=nums, job="pumpfun-rt-retrain"))
    al = notify.read_json(rep / "pumpfun_rt" / "allocator.json")
    if isinstance(al, dict):
        at = stamp(al)
        ch = al.get("choice")
        arm = (al.get("arms") or {}).get(ch) if isinstance(al.get("arms"), dict) else None
        nums = [{"label": "Wahl", "value": str(ch or "-")}, {"label": "Regel des Live-Bots", "value": str(al.get("live_rule") or "-")}]
        if isinstance(arm, dict):
            nums.append({"label": "P(beste)", "value": de_pct(100 * (_num(arm.get("p_best")) or 0), 0, sign=False)})
            nums.append({"label": "Gewicht", "value": de_pct(100 * (_num(arm.get("weight")) or 0), 0, sign=False)})
        rew = (arm or {}).get("rewards") if isinstance((arm or {}).get("rewards"), dict) else {}
        out.append(node("model:allocator", "model", "Allokator", "models",
                        "Wählt unter den pump.fun-Regeln die, die nach den letzten Tagen am ehesten die beste ist; er steuert den Live-Bot nie.",
                        state=fresh_state(at, now, 30 * HOUR), now=notify.short(notify.nodash(str(al.get("why") or "")), 200),
                        last_run=ms_iso(at), numbers=nums, spark=[_num(x) for _, x in sorted(rew.items()) if _num(x) is not None],
                        spark_label="Tagesertrag der Wahl", job="pumpfun-rt-retrain"))
    return out


def factory_nodes(rep: Path, now: int) -> list[dict]:
    out = []
    f3 = notify.read_json(rep / "pumpfun_rt" / "factory.json")
    if isinstance(f3, dict):
        at = stamp(f3)
        best = next((b for b in f3.get("best") or [] if isinstance(b, dict) and b.get("id")), {})
        nums = [{"label": "Versuche letzte Nacht", "value": de(f3.get("trials_tonight"), 0)},
                {"label": "Versuche insgesamt", "value": de(f3.get("trials_ever"), 0)},
                {"label": "Bester Kandidat", "value": str(best.get("id") or "-")}]
        if _num(best.get("pnl_sol")) is not None:
            nums.append({"label": "dessen Ergebnis", "value": de(best["pnl_sol"], 3, "SOL")})
        nums.append({"label": "Bücher", "value": str(len(f3.get("books") or []))})
        out.append(node("factory:F3", "factory", "F3 pump.fun-Fabrik", "factories", JOB_WHAT["pumpfun-factory"],
                        state=fresh_state(at, now, 30 * HOUR), now=f"Nacht {f3.get('night') or '-'} fertig",
                        last_run=ms_iso(at), numbers=nums, job="pumpfun-factory", aliases=["F3"],
                        books=[str(b.get("book")) for b in f3.get("books") or [] if isinstance(b, dict) and b.get("book")]))
    f2 = notify.read_json(rep / "smallaccount" / "factory.json")
    if isinstance(f2, dict):
        at = stamp(f2)
        nums = [{"label": "Geprüft heute", "value": de((f2.get("search") or {}).get("evaluated"), 0)},
                {"label": "Versuche im Pool", "value": de((f2.get("pool_after") or {}).get("n_trials"), 0)},
                {"label": "Schatten-Wallets", "value": str(len(f2.get("shadows") or []))}]
        out.append(node("factory:F2", "factory", "F2 Fabrik für kleine Konten", "factories", JOB_WHAT["factory-small"],
                        detail=notify.nodash(str(f2.get("headline") or "")), state=fresh_state(at, now, 30 * HOUR),
                        now=f"Lauf {f2.get('run_id') or '-'} fertig", last_run=ms_iso(at), numbers=nums,
                        job="factory-small", aliases=["F2"]))
    fs = notify.read_json(rep / "factory" / "latest.json")
    if isinstance(fs, dict):
        at = stamp(fs)
        nums = [{"label": "Versuche im Pool", "value": de((fs.get("pool_after") or {}).get("n_trials"), 0)},
                {"label": "Schatten", "value": str(len(fs.get("shadows") or []))},
                {"label": "Befördert", "value": str(len(fs.get("promoted") or []))}]
        out.append(node("factory:strategy", "factory", "Strategie-Fabrik", "factories", JOB_WHAT["factory-weekly"],
                        detail=notify.nodash(str(fs.get("headline") or "")), state=fresh_state(at, now, 8 * 24 * HOUR),
                        now=f"Lauf {fs.get('run_id') or '-'} fertig", last_run=ms_iso(at), numbers=nums,
                        job="factory-weekly"))
    return out


def book_nodes(root: Path, rep: Path, now: int, steps: dict[str, dict] | None = None) -> list[dict]:
    """Every forward book and autopilot; `steps` (lab.ops.ladder.by_book) adds its step on the readiness ladder."""
    fw = notify.read_json(rep / "forward" / "latest.json")
    if not isinstance(fw, dict):
        return []
    steps = steps or {}
    at = stamp(fw)
    out = []
    for b in (fw.get("books") or []) + (fw.get("autopilots") or []):
        if not isinstance(b, dict) or not b.get("name") or not re.fullmatch(r"[\w.-]+", str(b["name"])):
            continue
        name = str(b["name"])
        spark, last = journal_series(root / "paper" / name / "journal.csv")
        state_file = notify.read_json(root / "paper" / name / "state.json")
        equity = _num(b.get("equity")) or (_num(state_file.get("equity")) if isinstance(state_file, dict) else None) \
            or (spark[-1] if spark else None)
        nums = [{"label": "Rendite", "value": de_pct(b.get("return_pct"))},
                {"label": "Größter Rückgang", "value": de_pct(b.get("max_dd_pct"), sign=False)},
                {"label": "Tage", "value": de(b.get("days"), 0)}]
        if equity is not None:
            nums.insert(0, {"label": "Kapital", "value": de(equity, 2)})
        held = _num(last.get("held")) if last else None
        if held is not None:
            nums.append({"label": "Offene Positionen", "value": de(held, 0)})
        lad = steps.get(name)
        if lad is not None:
            nums.append({"label": "Stufe", "value": f"{lad['step']} {ladder_mod.STEPS_DE[lad['step']]}"})
            if lad.get("next_de"):
                nums.append({"label": "Es fehlt", "value": notify.short(lad["next_de"], 90)})
        status = str(b.get("status") or b.get("state") or "")
        st = "off" if status in ("stopped", "retired", "off") else "late" if status in ("behind", "stale") else "ok"
        st = fresh_state(at, now, 30 * HOUR, st)
        label = notify.nodash(str(b.get("label") or name))
        kind = "autopilot" if b.get("kind") == "autopilot" else "book"
        out.append(node(f"book:{name}", kind, label, "books",
                        ("Ein Autopilot auf Papier: " if kind == "autopilot" else "Ein Paper-Buch: ")
                        + notify.short(notify.nodash(str(b.get("variant") or label)), 160),
                        detail=notify.nodash(str(b.get("sentence") or "")), state=st,
                        now=f"Status {status or '-'}, {de(b.get('days'), 0)} Tage seit {b.get('since') or '-'}",
                        last_run=ms_iso(at), numbers=nums, spark=spark, spark_label="Kapital je Tag",
                        job="paper", aliases=[name],
                        ladder=None if lad is None else {"step": lad["step"], "next": lad.get("next_de") or "",
                                                         "evidence": lad.get("evidence") or ""}))
    return out


def bot_nodes(rep: Path, root: Path, now: int) -> list[dict]:
    out = []
    ls = notify.read_json(rep / "pumpfun_rt" / "live_status.json")
    if isinstance(ls, dict):
        running = bool(ls.get("running")) and bool(ls.get("on"))
        at = stamp(ls)
        st = "running" if running and at and now - at < 10 * MINUTE else "off" if not running else "late"
        nums = [{"label": "Guthaben", "value": de(ls.get("balance_sol"), 3, "SOL")},
                {"label": "Ergebnis gesamt", "value": de(ls.get("pnl_total_sol"), 3, "SOL")},
                {"label": "Trades gesamt", "value": de(ls.get("trades_total"), 0)},
                {"label": "Offene Positionen", "value": str(len(ls.get("positions") or []))},
                {"label": "Regel", "value": str(ls.get("rule") or "-")}]
        gate = [scrub(g) for g in ls.get("gate") or [] if isinstance(g, str)]
        out.append(node("bot:pumpfun", "bot", "pump.fun Echtgeld-Bot", "money",
                        "Der kleine Echtgeld-Bot für pump.fun: kauft und verkauft nach einer Regel, mit festen Grenzen und Notaus.",
                        state=st, now="handelt" if st == "running" else ("aus: " + "; ".join(gate)) if gate else "aus",
                        last_run=ms_iso(at), numbers=nums, aliases=["pumpfun live", "Live-Bot"]))
    os_ = notify.read_json(rep / "onchain_live" / "status.json")
    if isinstance(os_, dict):
        running = bool(os_.get("running") or os_.get("on"))
        at = stamp(os_)
        nums = [{"label": k, "value": de(os_.get(f), 2)} for k, f in (("Wert in USDC", "value_usdc"), ("Ergebnis", "pnl_usdc"))
                if _num(os_.get(f)) is not None]
        out.append(node("bot:onchain", "bot", "On-chain Echtgeld-Händler", "money",
                        "Der Händler der eigenen Solana-Wallet; gesperrt, bis der Besitzer ihn freigibt.",
                        state="running" if running else "off", now="handelt" if running else "aus",
                        last_run=ms_iso(at), numbers=nums))
    else:
        out.append(node("bot:onchain", "bot", "On-chain Echtgeld-Händler", "money",
                        "Der Händler der eigenen Solana-Wallet; gesperrt, bis der Besitzer ihn freigibt.",
                        state="off", now="nie gestartet"))
    return out


def link(nodes: dict[str, dict]) -> list[dict]:
    """The edges: the fixed map, depends_on of the table, models to the books that use them, F3 to its books."""
    pairs = list(EDGES)
    for n in nodes.values():
        for dep in n.get("depends_on") or []:
            pairs.append((f"job:{dep}", n["id"]))
        for b in n.get("used_by") or []:
            pairs.append((n["id"], f"book:{b}"))
        for b in n.get("books") or []:
            pairs.append((n["id"], f"book:{b}"))
        if n["kind"] in ("book", "autopilot"):
            pairs.append((n["id"], "job:forward"))
        if n["kind"] == "model" and n["id"].startswith("model:M"):
            pairs.append(("job:models", n["id"]))
        if n["kind"] == "model" and n["id"].startswith("model:zoo-"):
            pairs.append(("src:pumpfun_rt", n["id"]))
            pairs.append((n["id"], "model:allocator"))
        if n["kind"] == "job" and n["column"] == "data" and n["id"] != "job:features":
            pairs.append((n["id"], "job:features"))
        if n["kind"] == "job" and n["column"] == "books" and n["id"].startswith("job:paper-"):
            pairs.append((n["id"], "job:forward"))
    seen, edges = set(), []
    for a, b in pairs:
        if a in nodes and b in nodes and a != b and (a, b) not in seen:
            seen.add((a, b))
            edges.append({"from": a, "to": b})
            nodes[a]["outputs"].append(b)
            nodes[b]["inputs"].append(a)
    return edges


def build(root: Path | None = None, now: int | None = None, logs: Path | None = None, ladder: dict | None = None) -> dict:
    """`ladder`: the readiness ladder (lab.ops.ladder.build), built here when not given."""
    rep = notify.reports_root() if root is None else root / "reports"
    root = root or notify.data_root()
    now = now or notify.clock_ms()
    if ladder is None:
        try:
            ladder = ladder_mod.build(root, now)
        except Exception as e:  # noqa: BLE001 - the map goes on without the steps
            notify.say(f"lablive: the ladder failed ({type(e).__name__}: {e})", err=True)
    steps = ladder_mod.by_book(ladder)
    hj = notify.read_json(root / "_health" / "jobs.json")
    jobs = [j for j in (hj or {}).get("jobs") or [] if isinstance(j, dict)] if isinstance(hj, dict) else []
    runs = read_runs(root, now)
    found: list[dict] = []
    for part in (lambda: [recorder_node(root, now), pumpfun_record_node(rep, now)],
                 lambda: job_nodes(jobs, runs, logs, now), lambda: model_nodes(rep, now),
                 lambda: factory_nodes(rep, now), lambda: book_nodes(root, rep, now, steps),
                 lambda: bot_nodes(rep, root, now)):
        try:
            found += [n for n in part() if n]
        except Exception as e:  # noqa: BLE001 - one broken source never empties the map
            notify.say(f"lablive: a source failed ({type(e).__name__}: {e})", err=True)
    nodes: dict[str, dict] = {}
    for n in found:
        nodes.setdefault(n["id"], n)
    # An entity whose job failed or is off says so; one whose job runs now pulses.
    for n in nodes.values():
        j = nodes.get(f"job:{n['job']}") if n["kind"] != "job" and n.get("job") else None
        if j is not None:
            if j["state"] in ("failed", "running") and n["state"] in ("ok", "late"):
                n["state"] = j["state"]
            n["next_run"] = n["next_run"] or j["next_run"]
    edges = link(nodes)
    for n in nodes.values():
        for k in ("depends_on", "used_by", "books"):
            n.pop(k, None)
    order = {c: i for i, c in enumerate(COLUMNS)}
    out = sorted(nodes.values(), key=lambda n: (order[n["column"]], n["kind"] == "job", n["name"].lower()))
    counts = {s: sum(1 for n in out if n["state"] == s) for s in STATES}
    return {"updated_ms": now, "generated": ms_iso(now), "columns": list(COLUMNS), "states": list(STATES),
            "counts": counts, "nodes": out, "edges": edges, "health_at": (hj or {}).get("at") if isinstance(hj, dict) else None}


def aliases(graph: dict) -> dict[str, str]:
    """Name to node id, for the news articles: every book, model and factory by its own names."""
    out = {}
    for n in graph.get("nodes") or []:
        if n.get("kind") in ("book", "autopilot", "model", "factory", "bot"):
            for a in n.get("aliases") or []:
                if isinstance(a, str) and len(a) >= 2:
                    out[a] = n["id"]
    return out


def out_path() -> Path:
    return notify.reports_root() / "lablive" / "latest.json"


def logs_dir() -> Path | None:
    p = Path(os.environ.get("PYTHIA_LOGS", "/logs"))
    return p if p.is_dir() else None


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    lad = None
    try:
        lad = ladder_mod.build()
    except Exception as e:  # noqa: BLE001 - the map goes on without the steps
        notify.say(f"lablive: the ladder failed ({type(e).__name__}: {e})", err=True)
    g = build(logs=logs_dir(), ladder=lad or {})
    if "--print" in argv:
        notify.say(json.dumps(g, indent=1, ensure_ascii=False)[:20000])
        return 0
    notify.write_json(out_path(), g)
    if lad:
        ladder_mod.publish(lad)                 # T3: reports/ladder, every run (it only reads small files)
    notify.say(f"lablive: {len(g['nodes'])} nodes, {len(g['edges'])} edges, {g['counts']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
