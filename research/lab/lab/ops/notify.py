"""Push notifications to the operator's webhook: the daily digest and the health alarm.

Two jobs, one webhook (PYTHIA_ALERT_WEBHOOK, the same one the engine posts to):

  daily   after the learning loop: a short digest of what the money did.
          Each running autopilot with its equity, plus or minus today and
          since start in $ and %, against BTC, trades and fees today; the
          forward test status of every paper book; anything red in the
          hourly health check. English, under 1800 characters.
  health  after each hourly health check: when _health/system.json is not
          ok for two runs in a row, post once with what is red; once more
          when it is all green again. One bad run alone stays quiet.

  python -m lab.ops.notify                  the daily digest
  python -m lab.ops.notify --dry-run        print it, post nothing
  python3 notify.py --pending               a digest now, if one was asked for
                                            (POST /api/alerts/digest writes
                                            reports/notify/request.json) after
                                            the last digest; run every 5 minutes
  python3 notify.py --health <system.json>  the health alarm (stdlib only, so
                                            the host's health script can run
                                            this file without the lab image)

Environment: PYTHIA_ALERT_WEBHOOK (unset: print only), PYTHIA_ALERT_FORMAT
(discord, the default, posts {"content": ...}; slack posts {"text": ...}),
or instead of a webhook PYTHIA_TELEGRAM_BOT_TOKEN and PYTHIA_TELEGRAM_CHAT_ID,
which post to that chat through Telegram's sendMessage,
PYTHIA_ALERT_PREFIX (first word of every post, default Pythia), PYTHIA_DATA
and PYTHIA_REPORTS as for the rest of the lab.

Every digest (not a dry run) is written to reports/notify/latest.json as
{"ts", "text", "delivered"}, which the engine's GET /api/alerts shows as the
last digest. A digest asked for on demand does not move the snapshot the next
daily digest counts today's trades and fees from.

The webhook URL is a secret: it is never printed, logged or written to a file.
Only the standard library is used here on purpose.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

MAX_CHARS = 1800
DAY_MS = 86_400_000


def data_root() -> Path:
    return Path(os.environ.get("PYTHIA_DATA", "/data"))


def reports_root() -> Path:
    return Path(os.environ.get("PYTHIA_REPORTS", str(data_root() / "reports")))


# ---------------------------------------------------------------- posting

def config() -> tuple[str | None, str, str]:
    """(url or None, format, prefix) from the environment. Without a webhook,
    PYTHIA_TELEGRAM_BOT_TOKEN and PYTHIA_TELEGRAM_CHAT_ID send to Telegram."""
    prefix = os.environ.get("PYTHIA_ALERT_PREFIX", "Pythia").strip()
    url = (os.environ.get("PYTHIA_ALERT_WEBHOOK") or "").strip() or None
    if url is None:
        token = (os.environ.get("PYTHIA_TELEGRAM_BOT_TOKEN") or "").strip()
        if token and (os.environ.get("PYTHIA_TELEGRAM_CHAT_ID") or "").strip():
            return f"https://api.telegram.org/bot{token}/sendMessage", "telegram", prefix
        return None, "discord", prefix
    fmt = (os.environ.get("PYTHIA_ALERT_FORMAT") or "discord").strip().lower()
    fmt = {"slack": "slack", "text": "slack", "telegram": "telegram"}.get(fmt, "discord")
    return url, fmt, prefix


def body(fmt: str, text: str) -> dict:
    if fmt == "telegram":
        return {"chat_id": (os.environ.get("PYTHIA_TELEGRAM_CHAT_ID") or "").strip(), "text": text}
    return {"text": text} if fmt == "slack" else {"content": text}


def post(url: str, fmt: str, text: str, timeout: float = 10) -> tuple[bool, str | None]:
    """POST the text. Returns (ok, error); the error never contains the URL."""
    req = urllib.request.Request(url, data=json.dumps(body(fmt, text)).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": "pythia-notify"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            code = r.status
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}"
    except (urllib.error.URLError, OSError, ValueError) as e:
        # Only the kind of failure: a message could quote the host.
        reason = getattr(e, "reason", None)
        return False, f"not delivered ({type(reason).__name__ if isinstance(reason, BaseException) else type(e).__name__})"
    return (200 <= code < 300), (None if 200 <= code < 300 else f"HTTP {code}")


def clip(text: str, limit: int = MAX_CHARS) -> str:
    """Keep whole lines while they fit; say so when some had to go."""
    text = text.replace("\u2014", "-").replace("\u2013", "-")
    if len(text) <= limit:
        return text
    out: list[str] = []
    tail = "(more in the reports)"
    for line in text.split("\n"):
        if len("\n".join(out + [line, tail])) > limit:
            break
        out.append(line)
    return "\n".join(out + [tail])[:limit]


# ---------------------------------------------------------------- reading

def read_json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def write_json(p: Path, data) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, p)


def usd(v: float) -> str:
    return f"{'-' if v < 0 else '+'}${abs(v):,.2f}"


def pct(v: float | None) -> str:
    return "n/a" if v is None else f"{v:+.2f} %"


def _num(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f and abs(f) != float("inf") else None


# ---------------------------------------------------------------- the daily digest

def autopilot_lines(learn: dict | None, prev: dict, now_ms: int) -> tuple[list[str], dict, list[float]]:
    """One line per running autopilot, the snapshot for tomorrow and today's $ per autopilot."""
    lines, snap, today = [], {}, []
    for a in (learn or {}).get("autopilots") or []:
        if a.get("state") != "running":
            continue
        eq, start = _num(a.get("equity")), _num(a.get("start_capital"))
        trades, fees = int(_num(a.get("trades")) or 0), _num(a.get("fees")) or 0.0
        key = str(a.get("id") or a.get("name"))
        snap[key] = {"trades": trades, "fees": fees, "at": now_ms}
        if eq is None:
            lines.append(f"- {a.get('name', 'Autopilot')} ({a.get('mode') or '?'}): no equity reported")
            continue
        parts = [f"equity ${eq:,.2f}"]
        day_pct = _num(a.get("pnl_day_pct"))
        if day_pct is not None and day_pct > -100:
            d_usd = eq - eq / (1 + day_pct / 100)
            today.append(d_usd)
            parts.append(f"today {usd(d_usd)} ({pct(day_pct)})")
        tot_pct = _num(a.get("pnl_total_pct"))
        if start:
            parts.append(f"since start {usd(eq - start)} ({pct(tot_pct)})")
        vs = _num(a.get("vs_btc_total_pts"))
        btc = _num(a.get("btc_total_pct"))
        if vs is not None:
            parts.append(f"vs BTC {vs:+.2f} pts (BTC {pct(btc)})")
        p = prev.get(key)
        if p and 0 < now_ms - int(p.get("at") or 0) <= 36 * 3_600_000 and trades >= int(p.get("trades") or 0):
            parts.append(f"today {trades - int(p['trades'])} trades, fees ${max(fees - float(p.get('fees') or 0), 0):,.2f}")
        else:
            parts.append(f"{trades} trades, fees ${fees:,.2f} since start")
        lines.append(f"- {a.get('name', 'Autopilot')} ({a.get('mode') or '?'}): " + ", ".join(parts))
    return lines, snap, today


def forward_line(forward: dict | None) -> str:
    if not forward:
        return "Forward test: no report."
    books = [b for b in forward.get("books") or [] if b.get("name")]
    if not books:
        return "Forward test: no paper books."
    words = ", ".join(f"{b['name']} {str(b.get('status') or 'unknown').replace('_', ' ')}" for b in books)
    when = forward.get("generated") or "?"
    return f"Forward test ({when}): {words}."


def health_lines(health: dict | None, now_ms: int) -> list[str]:
    if not health:
        return ["Health: no health check found."]
    red = [c for c in health.get("checks") or [] if not c.get("ok")]
    out = []
    at = health.get("at")
    try:
        age_h = (now_ms / 1000 - datetime.strptime(at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()) / 3600
    except (TypeError, ValueError):
        age_h = None
    if age_h is not None and age_h > 2:
        out.append(f"Health: the last check ran {age_h:.0f} h ago.")
    if not red:
        out.append("Health: all green." if not out else "Health: all green at the last check.")
    else:
        out.append(f"Health: {len(red)} red: " + "; ".join(f"{c.get('name')} ({c.get('detail')})" for c in red))
    return out


def digest(learn: dict | None, forward: dict | None, health: dict | None, prev: dict, now_ms: int,
           prefix: str = "Pythia") -> tuple[str, dict]:
    day = datetime.fromtimestamp(now_ms / 1000, timezone.utc).strftime("%Y-%m-%d")
    head = f"{prefix} daily {day}".strip()
    lines, snap, today = autopilot_lines(learn, prev, now_ms)
    out = [head]
    if learn is None:
        out.append("Learning loop: no report found.")
    else:
        gen = _num(learn.get("generated_ms"))
        if gen is not None and now_ms - gen > 30 * 3_600_000:
            out.append(f"Learning loop: the last report is from {learn.get('generated')}, not today's.")
    if lines:
        total = sum(today)
        out.append(f"Running autopilots: {len(lines)}, together {usd(total)} today." if today
                   else f"Running autopilots: {len(lines)}.")
        out += lines
    elif learn is not None:
        err = (learn.get("engine") or {}).get("error")
        out.append(f"Autopilots: none running{f' ({err})' if err else ''}.")
    out.append(forward_line(forward))
    out += health_lines(health, now_ms)
    if learn and learn.get("headline"):
        out.append(f"Learning loop: {learn['headline']}")
    return clip("\n".join(out)), snap


def notify_dir() -> Path:
    """Where the last digest and the engine's digest requests live."""
    return reports_root() / "notify"


def daily(dry_run: bool = False, now_ms: int | None = None, keep_snapshot: bool = True,
          request_ts: int | None = None) -> int:
    """The digest. `keep_snapshot` False (an on-demand digest) leaves the
    snapshot of trades and fees alone; `request_ts` is the request it answers."""
    now_ms = now_ms or int(time.time() * 1000)
    rep = reports_root()
    state_path = data_root() / "notify" / "state.json"
    st = read_json(state_path) or {}
    text, snap = digest(read_json(rep / "learn" / "latest.json"), read_json(rep / "forward" / "latest.json"),
                        read_json(data_root() / "_health" / "system.json"), st.get("autopilots") or {}, now_ms,
                        config()[2])
    print(text)
    url, fmt, _ = config()
    if dry_run:
        return 0

    def record(delivered: bool) -> None:
        latest = {"ts": now_ms, "text": text, "delivered": delivered}
        if request_ts is not None:
            latest["request"] = request_ts
        write_json(notify_dir() / "latest.json", latest)

    if not url:
        print("PYTHIA_ALERT_WEBHOOK is not set: printed only.")
        record(False)
        return 0
    ok, err = post(url, fmt, text)
    record(ok)
    if not ok:
        print(f"digest not delivered: {err}", file=sys.stderr)
        return 1
    if keep_snapshot:
        write_json(state_path, {"autopilots": snap, "last_digest_ms": now_ms})
    return 0


def pending(now_ms: int | None = None) -> int:
    """A digest now when reports/notify/request.json asks for one after the
    last digest. One request gets one digest, delivered or not: the result is
    in latest.json, and the operator can ask again."""
    req = _num((read_json(notify_dir() / "request.json") or {}).get("ts"))
    if req is None:
        print("no digest request")
        return 0
    last = read_json(notify_dir() / "latest.json") or {}
    # `request` too: the engine's clock may run ahead of this one.
    answered = max(_num(last.get("ts")) or 0, _num(last.get("request")) or 0)
    if req <= answered:
        print("no new digest request")
        return 0
    return daily(now_ms=now_ms, keep_snapshot=False, request_ts=int(req))


# ---------------------------------------------------------------- the health alarm

def health_step(system: dict | None, st: dict) -> tuple[str | None, dict]:
    """(text to post or None, new state). Counts runs, not calls: the same
    system.json (same `at`) is counted once."""
    st = dict(st)
    if not system:
        return None, st
    at = system.get("at")
    if at and at == st.get("last_at"):
        return None, st
    st["last_at"] = at
    if system.get("ok"):
        was = st.get("posted")
        st.update(bad_runs=0, posted=False)
        if was:
            return f"Health check is all green again ({at}).", st
        return None, st
    st["bad_runs"] = int(st.get("bad_runs") or 0) + 1
    if st["bad_runs"] >= 2 and not st.get("posted"):
        st["posted"] = True
        red = [c for c in system.get("checks") or [] if not c.get("ok")]
        lines = [f"Health check not ok for {st['bad_runs']} runs in a row ({at}):"]
        lines += [f"- {c.get('name')}: {c.get('detail')}" for c in red] or ["- no check named"]
        return "\n".join(lines), st
    return None, st


def health(path: Path) -> int:
    state_path = path.with_name("alert_state.json")
    text, st = health_step(read_json(path), read_json(state_path) or {})
    url, fmt, prefix = config()
    if text:
        text = clip(f"{prefix} {text}".strip() if prefix else text)
        print(text)
        if url:
            ok, err = post(url, fmt, text)
            if not ok:
                print(f"health alert not delivered: {err}", file=sys.stderr)
                return 1  # state not saved: the next run tries again
    write_json(state_path, st)
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--health" in argv:
        i = argv.index("--health")
        path = Path(argv[i + 1]) if i + 1 < len(argv) else data_root() / "_health" / "system.json"
        return health(path)
    if "--pending" in argv:
        return pending()
    return daily(dry_run="--dry-run" in argv)


if __name__ == "__main__":
    sys.exit(main())
