"""Every 7-day call of the daily brief, scored like the other forecasts.

Each prediction is written down before its week (<data>/ai/predictions.jsonl,
appended, never rewritten) together with what two references said at the
same moment, from the same daily closes:

  base       the coin's share of up weeks over the last year (outside view)
  momentum   the lab's momentum rule: how often a week went up after the
             28-day return had the sign it has now, over the last two years.
             The rule the momentum paper books trade, as a probability.

Seven days after its reference close a prediction resolves: up when the
close then is above the reference close. The scores are recomputed from the
closes on every run (nothing is edited in place) and written to
reports/ai/scores.json: Brier score, log loss and hit rate per source, the
LLM's Brier score against each reference with a t statistic, reliability,
per coin and per week.

The weeks of daily predictions overlap, so neighbouring outcomes share six
days; the t statistics divide the effective sample by the horizon to account
for it (a rough Newey-West). Treat anything short of |t| > 2 as no difference.

  python -m lab.ai.score
"""

from __future__ import annotations

import json
import math
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from ..ops import notify

HORIZON = 7
BASE_DAYS = 365
MOMENTUM_DAYS = 730
LOOKBACK = 28
MIN_WINDOWS = 60
MIN_RESOLVED = 30
SOURCES = ("llm", "base", "momentum")
CLIP = 0.01

Closes = list[tuple[str, float]]  # (YYYY-MM-DD, close), oldest first


def ai_dir() -> Path:
    return notify.data_root() / "ai"


def predictions_path() -> Path:
    return ai_dir() / "predictions.jsonl"


def scores_path() -> Path:
    return notify.reports_root() / "ai" / "scores.json"


def read_predictions(path: Path | None = None) -> list[dict]:
    p = path or predictions_path()
    out = []
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return out
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("coin") and row.get("ref_day"):
            out.append(row)
    return out


def append_predictions(rows: list[dict], path: Path | None = None) -> None:
    p = path or predictions_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, allow_nan=False) + "\n")


# ---------------------------------------------------------------- the references

def _laplace(ups: int, n: int) -> float:
    return (ups + 1) / (n + 2)


def comparators(closes: Closes) -> dict:
    """What the two references say about the week after the last close."""
    c = [float(x[1]) for x in closes]
    ref = len(c) - 1
    if ref < HORIZON + 1:
        return {"base": 0.5, "momentum": 0.5, "momentum_sign": None}
    lo = max(0, ref - HORIZON - BASE_DAYS + 1)
    wins = [c[t + HORIZON] > c[t] for t in range(lo, ref - HORIZON + 1)]
    base = _laplace(sum(wins), len(wins)) if len(wins) >= MIN_WINDOWS else 0.5
    if ref < LOOKBACK:
        return {"base": base, "momentum": base, "momentum_sign": None}
    sign = c[ref] > c[ref - LOOKBACK]
    lo = max(LOOKBACK, ref - HORIZON - MOMENTUM_DAYS + 1)
    same = [c[t + HORIZON] > c[t] for t in range(lo, ref - HORIZON + 1) if (c[t] > c[t - LOOKBACK]) == sign]
    mom = _laplace(sum(same), len(same)) if len(same) >= MIN_WINDOWS else base
    return {"base": base, "momentum": mom, "momentum_sign": "up" if sign else "down"}


def resolve_day(ref_day: str) -> str:
    return (date.fromisoformat(ref_day) + timedelta(days=HORIZON)).isoformat()


# ---------------------------------------------------------------- scoring

def outcomes(rows: list[dict], closes: dict[str, Closes]) -> list[dict]:
    """Each prediction with `outcome` (1 up, 0 not) once its week is over."""
    by = {coin: dict(cs) for coin, cs in closes.items()}
    out = []
    for r in rows:
        r = dict(r)
        end = by.get(r["coin"], {}).get(resolve_day(r["ref_day"]))
        ref = r.get("ref_close")
        if end is not None and ref:
            r["end_close"] = float(end)
            r["outcome"] = 1 if float(end) > float(ref) else 0
        else:
            r["outcome"] = None
        out.append(r)
    return out


def _p(r: dict, s: str) -> float | None:
    v = r.get(f"p_{s}")
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def metrics(ps: list[float], ys: list[int]) -> dict:
    n = len(ps)
    if not n:
        return {"n": 0, "brier": None, "logloss": None, "hitRate": None, "meanP": None}
    brier = sum((p - y) ** 2 for p, y in zip(ps, ys)) / n
    ll = -sum(y * math.log(min(max(p, CLIP), 1 - CLIP)) + (1 - y) * math.log(1 - min(max(p, CLIP), 1 - CLIP))
              for p, y in zip(ps, ys)) / n
    calls = [(p > 0.5) == (y == 1) for p, y in zip(ps, ys) if p != 0.5]
    return {"n": n, "brier": brier, "logloss": ll, "hitRate": (sum(calls) / len(calls)) if calls else None,
            "meanP": sum(ps) / n}


def paired(a: list[float], b: list[float], ys: list[int]) -> dict:
    """Brier of a minus Brier of b on the same predictions (negative: a better),
    with a t statistic whose sample is shrunk by the overlap of the weeks."""
    d = [(x - y) ** 2 - (z - y) ** 2 for x, z, y in zip(a, b, ys)]
    n = len(d)
    if n < 2:
        return {"n": n, "diff": None, "t": None}
    m = sum(d) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in d) / (n - 1))
    n_eff = max(n / HORIZON, 1.0)
    t = m / (sd / math.sqrt(n_eff)) if sd > 0 else None
    return {"n": n, "diff": m, "t": t}


def reliability(ps: list[float], ys: list[int], bins: int = 5) -> list[dict]:
    out = []
    for i in range(bins):
        lo, hi = i / bins, (i + 1) / bins
        sel = [(p, y) for p, y in zip(ps, ys) if (lo <= p < hi) or (i == bins - 1 and p == 1.0)]
        if sel:
            out.append({"bin": f"{lo:.1f}-{hi:.1f}", "n": len(sel), "predicted": sum(p for p, _ in sel) / len(sel),
                        "observed": sum(y for _, y in sel) / len(sel)})
    return out


def verdict(resolved: int, vs_momentum: dict, vs_base: dict) -> str:
    if resolved < MIN_RESOLVED:
        return (f"Too early: {resolved} resolved prediction{'s' if resolved != 1 else ''}; "
                f"at least {MIN_RESOLVED} before the comparison says anything.")
    words = []
    for name, v in (("the momentum rule", vs_momentum), ("the base rate", vs_base)):
        t = v.get("t")
        if t is None:
            words.append(f"no comparison with {name}")
        elif t < -2:
            words.append(f"better than {name} (t {t:.1f})")
        elif t > 2:
            words.append(f"worse than {name} (t {t:+.1f})")
        else:
            words.append(f"no measurable difference to {name} (t {t:+.1f})")
    return f"After {resolved} resolved weeks the LLM is " + "; ".join(words) + "."


def week_of(day: str) -> str:
    d = date.fromisoformat(day)
    return (d - timedelta(days=d.weekday())).isoformat()


def score(rows: list[dict], closes: dict[str, Closes], now_ms: int) -> dict:
    rows = outcomes(rows, closes)
    done = [r for r in rows if r["outcome"] is not None and all(_p(r, s) is not None for s in SOURCES)]
    ys = [int(r["outcome"]) for r in done]
    ps = {s: [_p(r, s) for r in done] for s in SOURCES}
    sources = {s: metrics(ps[s], ys) for s in SOURCES}
    vs = {"base": paired(ps["llm"], ps["base"], ys), "momentum": paired(ps["llm"], ps["momentum"], ys)}
    by_coin = []
    for coin in sorted({r["coin"] for r in done}):
        sel = [r for r in done if r["coin"] == coin]
        y = [int(r["outcome"]) for r in sel]
        by_coin.append({"coin": coin, "n": len(sel),
                        **{s: metrics([_p(r, s) for r in sel], y)["brier"] for s in SOURCES}})
    weeks = []
    for w in sorted({week_of(r["date"]) for r in done})[-26:]:
        sel = [r for r in done if week_of(r["date"]) == w]
        y = [int(r["outcome"]) for r in sel]
        weeks.append({"week": w, "n": len(sel), **{s: metrics([_p(r, s) for r in sel], y)["brier"] for s in SOURCES}})
    models = sorted({str(r.get("model") or "") for r in rows if r.get("model")})
    return notify_safe({
        "generated_ms": now_ms,
        "generated": datetime.fromtimestamp(now_ms / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "horizon_days": HORIZON,
        "predictions": len(rows),
        "resolved": len(done),
        "pending": sum(1 for r in rows if r["outcome"] is None),
        "models": models,
        "sources": sources,
        "vs": vs,
        "verdict": verdict(len(done), vs["momentum"], vs["base"]),
        "reliability": reliability(ps["llm"], ys),
        "by_coin": by_coin,
        "weeks": weeks,
        "recent": [{k: r.get(k) for k in ("date", "coin", "p_llm", "p_base", "p_momentum", "outcome", "reason")}
                   for r in sorted(done, key=lambda r: (r["date"], r["coin"]))[-40:]],
        "references": {
            "base": f"share of up weeks over the last {BASE_DAYS} days",
            "momentum": f"up weeks after a {LOOKBACK}-day return of the same sign, last {MOMENTUM_DAYS} days",
        },
        "note": "Shadow only: these predictions never size, place or veto an order.",
    })


def notify_safe(v):
    """NaN and infinities out, so the file is valid JSON for the engine."""
    if isinstance(v, float):
        return v if math.isfinite(v) else None
    if isinstance(v, dict):
        return {k: notify_safe(x) for k, x in v.items()}
    if isinstance(v, list):
        return [notify_safe(x) for x in v]
    return v


# ---------------------------------------------------------------- daily closes

def binance_closes(coin: str) -> Closes:
    """Daily closes up to yesterday from the data lake (lab.klines_daily)."""
    from .. import klines_daily
    df = klines_daily.fetch(f"{coin}USDT")
    if df.is_empty():
        return []
    return [(datetime.fromtimestamp(int(d) / 1e6, timezone.utc).strftime("%Y-%m-%d"), float(c))
            for d, c in zip(df["day"].to_list(), df["close"].to_list()) if c]


def closes_for(coins, loader=binance_closes) -> dict[str, Closes]:
    out = {}
    for c in sorted(set(coins)):
        try:
            out[c] = loader(c)
        except Exception as e:  # noqa: BLE001 - one coin's history never stops the rest
            notify.say(f"no daily closes for {c}: {type(e).__name__}", err=True)
            out[c] = []
    return out


def run(now_ms: int | None = None, loader=binance_closes, closes: dict[str, Closes] | None = None) -> dict:
    now = now_ms or notify.clock_ms()
    rows = read_predictions()
    if closes is None:
        closes = closes_for({r["coin"] for r in rows}, loader)
    data = score(rows, closes, now)
    notify.write_json(scores_path(), data)
    return data


def main(argv: list[str] | None = None) -> int:
    data = run()
    notify.say(f"{data['predictions']} predictions, {data['resolved']} resolved. {data['verdict']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
