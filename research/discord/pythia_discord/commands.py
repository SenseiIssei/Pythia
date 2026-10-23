"""The slash commands: read only, for the owner only.

Every answer is built from the files the lab and the live bot write (the reports folder,
mounted read only); no command trades, arms, changes a limit or touches the kill switch,
and there is no code here that could. respond() checks the user's id against the owner's
first; anyone else gets "nicht erlaubt" and nothing is read.

  /status   pump.fun live: on or off, mode, wallet, today's and the total P&L, stake, open
            positions (reports/pumpfun_rt/live_status.json)
  /trades   the last 10 real-money pump.fun trades (reports/pumpfun_rt/live_trades.json)
  /konten   the real-money accounts (the pump.fun wallet, live autopilots) and the paper ones
            (reports/forward/latest.json)
  /lab      the newest study reports and the model zoo (reports/<study>, reports/models)
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

COMMANDS: list[tuple[str, str]] = [
    ("status", "pump.fun live: an/aus, Wallet, P&L heute, Einsatz, offene Positionen"),
    ("trades", "Die letzten 10 Echtgeld-Trades"),
    ("konten", "Echtgeld- und Paper-Konten"),
    ("lab", "Die neuesten Studien und der Modell-Zoo"),
]
NOT_ALLOWED = "nicht erlaubt"
GREEN, RED, GREY, BLUE, ORANGE = 0x2FB344, 0xE66767, 0xA3A29A, 0x3987E5, 0xE8A33D
STALE_MS = 5 * 60_000
STATUS_DE = {"early": "noch früh", "on_track": "im Plan", "ok": "in Ordnung", "watch": "beobachten",
             "below": "darunter", "behind": "im Rückstand", "unknown": "unbekannt", "in use": "im Einsatz",
             "shadow": "Schattenlauf", "retired": "ausgemustert", "failed its gate": "an der Schwelle gescheitert"}
# Reports that are not studies (the same set as the briefing's, lab.ops.briefing.NOT_STUDIES).
NOT_STUDIES = {"learn", "forward", "notify", "trending", "listings", "models", "pokemon", "cs2", "cs2_trends",
               "cs2_weekly", "readiness", "pumpfun", "pumpfun_rt", "pumpfun_activity", "polymarket", "agent",
               "exit_shadow", "factory", "paper_review", "studies", "ai", "ai_brief", "ai_news", "ai_analyst",
               "costs"}


def reports_root() -> Path:
    data = Path(os.environ.get("PYTHIA_DATA", "/data"))
    return Path(os.environ.get("PYTHIA_REPORTS", str(data / "reports")))


def read_json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def allowed(user_id, owner_id) -> bool:
    """Only the owner: the owner's user id, compared as text; no owner set means nobody."""
    owner = str(owner_id or "").strip()
    return bool(owner) and str(user_id or "").strip() == owner


# ---------------------------------------------------------------- formatting (German)

def _num(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f and f not in (float("inf"), float("-inf")) else None


def de(v: float, dp: int = 2, sign: bool = False) -> str:
    """1.234,56 with an optional sign."""
    s = f"{abs(v):,.{dp}f}".replace(",", "_").replace(".", ",").replace("_", ".")
    return ("+" if v > 0 else "-" if v < 0 else "") + s if sign else ("-" + s if v < 0 else s)


def sol(v, dp: int = 4, sign: bool = False) -> str:
    v = _num(v)
    return "k. A." if v is None else f"{de(v, dp, sign)} SOL"


def pct(frac, dp: int = 1) -> str:
    v = _num(frac)
    return "k. A." if v is None else f"{de(v * 100, dp, True)} %"


def berlin(ms) -> datetime:
    """Europe/Berlin without tzdata: CET, CEST from the last Sunday of March to that of October (01:00 UTC)."""
    t = datetime.fromtimestamp(float(ms) / 1000, timezone.utc)

    def last_sunday(month: int) -> datetime:
        d = datetime(t.year, month, 31, 1, tzinfo=timezone.utc)
        return d - timedelta(days=(d.weekday() + 1) % 7)

    summer = last_sunday(3) <= t < last_sunday(10)
    return t + timedelta(hours=2 if summer else 1)


def when(ms) -> str:
    return berlin(ms).strftime("%d.%m. %H:%M") if _num(ms) else "?"


def short_address(a) -> str:
    a = str(a or "")
    return f"{a[:4]}…{a[-4:]}" if len(a) > 12 else (a or "k. A.")


def clip(s, n: int) -> str:
    s = " ".join(str(s or "").split()).replace("**", "")
    return s if len(s) <= n else s[:n - 1].rstrip() + "…"


def embed(title: str, description: str, color: int = BLUE, fields: list[tuple[str, str, bool]] | None = None,
          footer: str | None = None) -> dict:
    e: dict = {"title": clip(title, 250), "description": description[:4000], "color": color}
    if fields:
        e["fields"] = [{"name": clip(n, 250), "value": (v or "-")[:1024], "inline": i} for n, v, i in fields[:25]]
    if footer:
        e["footer"] = {"text": clip(footer, 200)}
    return e


# ---------------------------------------------------------------- the answers

def status_embed(st: dict | None, now_ms: int) -> dict:
    if not isinstance(st, dict):
        return embed("pump.fun live", "Kein Status: reports/pumpfun_rt/live_status.json fehlt.", GREY)
    on, running = bool(st.get("on")), bool(st.get("running"))
    age = now_ms - int(_num(st.get("t")) or 0)
    if not running or age > STALE_MS:
        head, color = "⚪ läuft nicht" + (f" (Status {age // 60_000} min alt)" if age > STALE_MS else ""), GREY
    elif st.get("kill"):
        head, color = "🛑 Notschalter an", RED
    elif on:
        head, color = "🟢 an", GREEN
    else:
        head, color = "🟠 aus", ORANGE
    mode = {"test": "Test (Alpha-Phase)", "full": "voll"}.get(str(st.get("mode")), str(st.get("mode") or "k. A."))
    pnl = _num(st.get("pnl_today_sol"))
    stake = _num((st.get("stake") or {}).get("sol")) or _num((st.get("limits") or {}).get("max_trade_sol"))
    fields = [
        ("Modus", f"{mode} · {st.get('rule') or '?'}", True),
        ("Wallet", f"{short_address(st.get('address'))} · {sol(st.get('balance_sol'))}", True),
        ("P&L heute", f"{sol(pnl, sign=True)} · {int(_num(st.get('trades_today')) or 0)} Trades, "
                      f"{int(_num(st.get('wins_today')) or 0)} gewonnen", False),
        ("P&L gesamt", f"{sol(st.get('pnl_total_sol'), sign=True)} · {int(_num(st.get('trades_total')) or 0)} Trades",
         True),
        ("Einsatz", sol(stake) + (f" ({clip((st.get('stake') or {}).get('why'), 80)})"
                                  if (st.get("stake") or {}).get("why") else ""), True),
    ]
    pos = [p for p in st.get("positions") or [] if isinstance(p, dict)]
    lines = []
    for p in pos[:10]:
        cost, mark = _num(p.get("cost_sol")), _num(p.get("mark_sol"))
        ret = f" · {pct(mark / cost - 1)}" if cost and mark is not None else ""
        lines.append(f"{clip(p.get('symbol') or p.get('name') or '?', 16)}: {sol(cost)}{ret}"
                     + (" · hängt" if p.get("state") == "stuck" else ""))
    fields.append((f"Offene Positionen ({len(pos)})", "\n".join(lines) or "keine", False))
    lim = st.get("limits") or {}
    if lim:
        fields.append(("Grenzen", f"Tagesverlust {sol(lim.get('max_daily_loss_sol'))} · Budget "
                                  f"{sol(lim.get('max_total_sol'))} · max. {int(_num(lim.get('max_open')) or 0)} offen",
                       False))
    why = "; ".join(str(g) for g in (st.get("gate") or [])[:3]) or st.get("refusing")
    stops = [k for k, v in (st.get("stops") or {}).items() if v]
    desc = f"**{head}**"
    if not on and why:
        desc += f"\nWarum: {clip(why, 300)}"
    if stops:
        desc += "\nStopp: " + ", ".join({"daily": "Tagesverlust", "total": "Budget"}.get(s, s) for s in stops)
    return embed("pump.fun live", desc, color, fields, footer=f"Stand {when(st.get('t'))} · nur lesen")


def trades_embed(rows, n: int = 10) -> dict:
    trades = [t for t in (rows or []) if isinstance(t, dict) and _num(t.get("exit_ms"))]
    trades.sort(key=lambda t: _num(t["exit_ms"]), reverse=True)
    if not trades:
        return embed("Letzte Echtgeld-Trades", "Noch keine Trades.", GREY)
    lines = []
    for t in trades[:n]:
        p = _num(t.get("pnl_sol")) or 0.0
        dot = "🟢" if p > 0 else "🔴" if p < 0 else "⚪"
        lines.append(f"{dot} {when(t['exit_ms'])} **{clip(t.get('symbol') or t.get('name') or '?', 14)}** "
                     f"{pct(t.get('ret'))} · {sol(p, sign=True)} · {clip(t.get('exit_why') or '?', 12)}")
    total = sum(_num(t.get("pnl_sol")) or 0.0 for t in trades[:n])
    return embed(f"Letzte {min(n, len(trades))} Echtgeld-Trades", "\n".join(lines),
                 GREEN if total > 0 else RED if total < 0 else GREY,
                 footer=f"Summe {sol(total, sign=True)} · pump.fun · nur lesen")


def konten_embed(status: dict | None, forward: dict | None) -> dict:
    real, paper = [], []
    if isinstance(status, dict) and status.get("address"):
        real.append(f"pump.fun Wallet {short_address(status.get('address'))}: {sol(status.get('balance_sol'))}, "
                    f"gesamt {sol(status.get('pnl_total_sol'), sign=True)}")
    aps = [a for a in ((forward or {}).get("autopilots") or []) if isinstance(a, dict)]
    for a in aps:
        eq, ret = _num(a.get("equity")), _num(a.get("return_pct"))
        line = (f"{clip(a.get('label') or a.get('name'), 40)} ({str(a.get('venue') or '?').replace('_', ' ')}): "
                f"{de(eq, 2) + ' $' if eq is not None else 'k. A.'}"
                + (f" · {de(ret, 1, True)} %" if ret is not None else ""))
        (real if a.get("mode") == "live" else paper).append(line)
    books = [b for b in ((forward or {}).get("books") or []) if isinstance(b, dict)]
    fields = [("💰 Echtgeld", "\n".join(real[:10]) or "keins", False),
              (f"📄 Paper und Demo ({len(paper)})", "\n".join(paper[:12]) + (f"\n+{len(paper) - 12} weitere"
                                                                              if len(paper) > 12 else "") or "keins",
               False)]
    if books:
        counts: dict[str, int] = {}
        for b in books:
            counts[str(b.get("status") or "unbekannt")] = counts.get(str(b.get("status") or "unbekannt"), 0) + 1
        fields.append((f"📒 Paper-Bücher ({len(books)})",
                       ", ".join(f"{n} {STATUS_DE.get(k, k.replace('_', ' '))}"
                                 for k, n in sorted(counts.items(), key=lambda kv: -kv[1])),
                       False))
    gen = (forward or {}).get("generated")
    return embed("Konten", "Echtgeld und Paper, aus dem Live-Status und dem Forward-Bericht.", BLUE, fields,
                 footer=f"Forward-Bericht {gen}" if gen else "nur lesen")


def newest_studies(root: Path, n: int = 6) -> list[tuple[str, int, dict]]:
    out = []
    try:
        dirs = list(root.iterdir())
    except OSError:
        return []
    for d in dirs:
        p = d / "latest.json"
        if d.name in NOT_STUDIES or not p.is_file():
            continue
        try:
            at = int(p.stat().st_mtime * 1000)
        except OSError:
            continue
        out.append((d.name, at, p))
    out.sort(key=lambda x: -x[1])
    return [(name, at, read_json(p) or {}) for name, at, p in out[:n]]


def lab_embed(models: dict | None, studies: list[tuple[str, int, dict]]) -> dict:
    lines = []
    for name, at, rep in studies:
        verdict = rep.get("verdict") or rep.get("headline") if isinstance(rep, dict) else None
        lines.append(f"**{name}** ({when(at)}): {clip(verdict, 160) if isinstance(verdict, str) else 'kein Urteil'}")
    fields = []
    ms = [m for m in ((models or {}).get("models") or []) if isinstance(m, dict) and m.get("code")]
    if ms:
        by: dict[str, list[str]] = {}
        for m in ms:
            by.setdefault(str(m.get("status") or "?"), []).append(str(m["code"]))
        fields.append((f"🧠 Modell-Zoo ({len(ms)})",
                       "\n".join(f"{STATUS_DE.get(k, k)}: {', '.join(v)}" for k, v in sorted(by.items())), False))
    return embed("Lab", "\n".join(lines) or "Keine Studienberichte.", BLUE, fields, footer="nur lesen")


def respond(name: str, user_id, owner_id, now_ms: int, root: Path | None = None) -> dict:
    """The answer to one command: {"content", "embeds", "ephemeral"}. The owner check first."""
    if not allowed(user_id, owner_id):
        return {"content": NOT_ALLOWED, "embeds": [], "ephemeral": True}
    root = root or reports_root()
    if name == "status":
        e = status_embed(read_json(root / "pumpfun_rt" / "live_status.json"), now_ms)
    elif name == "trades":
        d = read_json(root / "pumpfun_rt" / "live_trades.json")
        e = trades_embed(d.get("trades") if isinstance(d, dict) else d)
    elif name == "konten":
        e = konten_embed(read_json(root / "pumpfun_rt" / "live_status.json"),
                         read_json(root / "forward" / "latest.json"))
    elif name == "lab":
        e = lab_embed(read_json(root / "models" / "latest.json"), newest_studies(root))
    else:
        return {"content": "unbekannter Befehl", "embeds": [], "ephemeral": True}
    return {"content": None, "embeds": [e], "ephemeral": True}
