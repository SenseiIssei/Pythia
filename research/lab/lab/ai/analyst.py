"""The weekly Claude analyst (X11 e1): one Sonnet call through the engine's
metered endpoint (Batches API) ranks every Alpaca coin by its expected 7-day
return, scored exactly like M2 (rank IC) in shadow.

Pre-registered in results/model_upgrades_prereg.md (e1). The model sees a
compact fact sheet per coin (7, 30 and 90-day returns, 30-day vol, distance
to the 52-week high and the 200-day mean, 28-day volume trend, 7-day funding
where a perp exists) and a few market lines (BTC, the Coinbase and Korean
premiums, stablecoin growth, DVOL). No forecast of ours is shown. It answers
per coin pUp7d (probability the close 7 days after the reference close is
higher) and expectedRank (1 = the best 7-day return of the listed coins).

Every answer is appended to <data>/ai/analyst.jsonl before its week starts,
with the references at the same moment (minus the 30-day vol, the 28-day
return, the base rate). After the week: rank IC of minus expectedRank
against the realised 7-day log return, next to the low-vol rank, 28-day
momentum and, where the M2 shadow recorded the same reference day, M2's rank;
Brier of pUp7d against the base rate. Pass (after at least 26 scored weeks):
mean weekly IC above 0 with t above 2 and above the low-vol rank's with a
paired t above 2. Shadow only: nothing reads it to trade.

  python -m lab.ai.analyst             weekly, after the M2 v2 paper book (jobs.yaml: ai-analyst)
  python -m lab.ai.analyst --dry-run   print the prompt and its size, call nothing
  python -m lab.ai.analyst --force     another call this week
  python -m lab.ai.analyst --score     rescore only, no call
"""

from __future__ import annotations

import json
import math
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from ..ops import notify
from . import engine, score

NAME = "ai_analyst"
HORIZON = 7
MIN_CLOSES = 120
MAX_TOKENS = 6000
BATCH_WAIT_SEC = 50 * 60
MIN_WEEKS = 26
PASS_T = 2.0
EVERY_DAYS = 6          # at most one call in this many days unless --force
ALIGN_HOURS = 20        # call when the M2 v2 book rebalanced this recently
FALLBACK_DAYS = 8       # or when the last call is this old

SYSTEM = """You are the weekly crypto analyst of Pythia, a paper-trading research system. Once a week you rank \
the coins the owner's paper account can trade by how you expect each to do over the next 7 days, relative to \
the others. Every number is written down before the week starts and scored afterwards against what happened, \
next to simple rules (low volatility, momentum) and the lab's own ranking model.

You get a fact sheet per coin and a few market lines. That is all you know: no news feed, nothing after the \
reference close. Do not invent news, events or figures that are not in the facts.

For every coin listed under RANK give:
- expectedRank: an integer from 1 (expected best 7-day return of the listed coins) to N (expected worst), \
each used once. Only the order is scored (rank correlation with the realised returns).
- pUp7d: the probability that the coin's close 7 days after the reference close is ABOVE it. Scored with the \
Brier score against the coin's base rate of up weeks; without a clear reason stay between 0.45 and 0.55, never \
beyond 0.25 to 0.75. Coins move together: a market-wide view moves every coin's number the same way.
- reason: one plain sentence, at most 20 words, naming the facts behind the rank.

Known facts about coin returns over a week, from the lab's own studies: relative ranks are somewhat \
predictable, absolute direction barely; low-volatility coins have tended to beat high-volatility ones; \
coins that rose most over the last few weeks have not reliably kept rising. Use your judgment on the facts \
given. Do not use em dashes. Answer with the JSON object only, in the schema given."""

SCHEMA = {
    "type": "object",
    "properties": {
        "ranking": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"coin": {"type": "string"}, "expectedRank": {"type": "integer"},
                               "pUp7d": {"type": "number"}, "reason": {"type": "string"}},
                "required": ["coin", "expectedRank", "pUp7d", "reason"],
                "additionalProperties": False,
            },
        },
        "market": {"type": "string"},
    },
    "required": ["ranking", "market"],
    "additionalProperties": False,
}


# ---------------------------------------------------------------- data

Bars = list[dict]  # oldest first: {"day": "YYYY-MM-DD", "close", "high", "qv"}


def lake_bars(coin: str) -> Bars:
    """Daily bars up to yesterday from the data lake (lab.klines_daily)."""
    from .. import klines_daily
    df = klines_daily.fetch(f"{coin}USDT")
    if df.is_empty():
        return []
    return [{"day": datetime.fromtimestamp(int(d) / 1e6, timezone.utc).strftime("%Y-%m-%d"), "close": float(c),
             "high": float(h), "qv": float(q)}
            for d, c, h, q in zip(df["day"].to_list(), df["close"].to_list(), df["high"].to_list(), df["qv"].to_list())
            if c]


def coins() -> list[str]:
    from .. import universe
    return list(universe.ALPACA)


def bars_for(cs, loader=lake_bars) -> dict[str, Bars]:
    out = {}
    for c in cs:
        try:
            out[c] = loader(c)
        except Exception as e:  # noqa: BLE001 - one coin's history never stops the rest
            notify.say(f"no daily bars for {c}: {type(e).__name__}", err=True)
            out[c] = []
    return out


def features(b: Bars) -> dict | None:
    """The fact-sheet numbers and the references for one coin at its last close."""
    if len(b) < MIN_CLOSES:
        return None
    c = [x["close"] for x in b]
    last = c[-1]

    def ret(k):
        return last / c[-1 - k] - 1 if len(c) > k and c[-1 - k] > 0 else None
    lr = [math.log(c[i] / c[i - 1]) for i in range(max(1, len(c) - 30), len(c)) if c[i - 1] > 0 and c[i] > 0]
    vol30 = math.sqrt(sum(r * r for r in lr) / max(len(lr), 1)) * math.sqrt(365)
    hi = max(x["high"] for x in b[-365:])
    ma200 = sum(c[-200:]) / len(c[-200:]) if len(c) >= 200 else None
    q = [x["qv"] for x in b]
    vt = (math.log((sum(q[-28:]) / 28 + 1) / (sum(q[-180:]) / len(q[-180:]) + 1)) if len(q) >= 56 else None)
    return {"ref_day": b[-1]["day"], "ref_close": last, "r7": ret(7), "r28": ret(28), "r30": ret(30), "r90": ret(90),
            "vol30": vol30, "vs_hi52": last / hi - 1 if hi else None,
            "vs_ma200": last / ma200 - 1 if ma200 else None, "volume_trend": vt}


def market_lines() -> list[str]:
    """Latest Coinbase and Korean premium (7-day means), stablecoin growth and DVOL, each with
    where it sits in its last year, from the flow collector's files. Empty when they are missing."""
    try:
        import numpy as np
        import polars as pl

        from ..experiments import m2_v3
    except Exception:  # noqa: BLE001 - no polars: no market lines
        return []
    out = []
    try:
        dv = m2_v3._flow("dvol")
        if dv is not None:
            x = dv.filter(pl.col("currency") == "BTC").sort("day_us")["close"].to_numpy()
            if len(x) > 30:
                out.append(f"BTC DVOL (30-day implied vol) {x[-1]:.0f}, higher than {100 * np.mean(x[-365:] < x[-1]):.0f} % "
                           f"of the last year")
        st = m2_v3._flow("stables")
        if st is not None:
            s = st.drop_nulls(["usdt", "usdc"]).sort("day_us")
            v = (s["usdt"] + s["usdc"]).to_numpy()
            if len(v) > 31:
                out.append(f"USDT + USDC supply {v[-1] / 1e9:.0f} bn USD, {100 * (v[-1] / v[-31] - 1):+.1f} % over 30 days")
        cb = m2_v3._flow("coinbase_btcusd_1h")
        if cb is not None:
            from ..experiments.picks import hourly_segments
            segs = hourly_segments("BTCUSDT")
            if segs:
                bn = pl.concat(segs).select(ts_us="open_time_us", bn="close")
                h = cb.select("ts_us", cb_="close").join(bn, on="ts_us").sort("ts_us").tail(24 * 7)
                if h.height > 24:
                    out.append(f"Coinbase premium over Binance, 7-day mean {100 * float((h['cb_'] / h['bn'] - 1).mean()):+.3f} %")
    except Exception as e:  # noqa: BLE001 - market lines are optional
        notify.say(f"market lines skipped: {type(e).__name__}", err=True)
    return out


def funding7(coin: str) -> float | None:
    try:
        from ..data import funding
        f = funding(coin)
        if f is None or f.is_empty():
            return None
        return float(sum(float(x) for x in f["funding_rate"].to_list()[-21:]))
    except Exception:  # noqa: BLE001 - a coin without perp history has no funding line
        return None


def pct(v, nd=1) -> str:
    return "n/a" if v is None else f"{100 * v:+.{nd}f} %"


def build_prompt(day: str, feats: dict[str, dict], fund: dict[str, float | None], market: list[str]) -> str:
    lines = [f"DATE: {day} (UTC). Horizon: 7 days from each coin's reference close.", "",
             "COINS (r = return to the reference close; vol30 annualised; volume trend = 28-day over 180-day "
             "mean volume, log; funding = sum over the last 7 days, perpetual, a long pays when positive):"]
    for c, f in feats.items():
        lines.append(f"- {c}: close {f['ref_close']:,.6g} on {f['ref_day']}, r7 {pct(f['r7'])}, r30 {pct(f['r30'])}, "
                     f"r90 {pct(f['r90'])}, vol30 {100 * f['vol30']:.0f} %, vs 52w high {pct(f['vs_hi52'])}, "
                     f"vs 200d mean {pct(f['vs_ma200'])}, volume trend "
                     f"{'n/a' if f['volume_trend'] is None else format(f['volume_trend'], '+.2f')}, funding 7d "
                     f"{'n/a' if fund.get(c) is None else format(100 * fund[c], '+.3f') + ' %'}")
    if market:
        lines += ["", "MARKET:"] + ["- " + m for m in market]
    lines += ["", f"RANK ({len(feats)} coins): " + ", ".join(feats)]
    return "\n".join(lines)


def parse_answer(obj, cs: list[str]) -> tuple[dict[str, dict], list[str]]:
    """{coin: {rank, p, reason}} and problems. Unknown or duplicate coins and bad numbers are
    dropped and named; ranks are re-numbered 1..n by the given order (ties by listing order)."""
    problems: list[str] = []
    if not isinstance(obj, dict) or not isinstance(obj.get("ranking"), list):
        return {}, ["no ranking list"]
    asked, got = set(cs), {}
    for it in obj["ranking"]:
        if not isinstance(it, dict):
            continue
        c = str(it.get("coin") or "").strip().upper()
        if c not in asked or c in got:
            problems.append(f"{c or '?'} {'twice' if c in got else 'was not asked for'}")
            continue
        try:
            r, p = float(it.get("expectedRank")), float(it.get("pUp7d"))
        except (TypeError, ValueError):
            problems.append(f"{c}: not a number")
            continue
        if not (math.isfinite(r) and math.isfinite(p) and 0 <= p <= 1):
            problems.append(f"{c}: rank {r} or pUp7d {p} out of range")
            continue
        got[c] = {"raw_rank": r, "p": p, "reason": notify.nodash(" ".join(str(it.get("reason") or "").split()))[:200]}
    order = sorted(got, key=lambda c: (got[c]["raw_rank"], cs.index(c)))
    for i, c in enumerate(order):
        got[c]["rank"] = i + 1
    missing = [c for c in cs if c not in got]
    if missing:
        problems.append("no rank for " + ", ".join(missing))
    return got, problems


# ---------------------------------------------------------------- record and score

def path() -> Path:
    return score.ai_dir() / "analyst.jsonl"


def read_rows() -> list[dict]:
    out = []
    try:
        text = path().read_text(encoding="utf-8")
    except OSError:
        return out
    for line in text.splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if isinstance(r, dict) and r.get("coin") and r.get("ref_day"):
            out.append(r)
    return out


def spearman(a: list[float], b: list[float]) -> float | None:
    n = len(a)
    if n < 5:
        return None

    def ranks(x):
        o = sorted(range(n), key=lambda i: x[i])
        r = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and x[o[j + 1]] == x[o[i]]:
                j += 1
            for k in range(i, j + 1):
                r[o[k]] = (i + j) / 2
            i = j + 1
        return r
    ra, rb = ranks(a), ranks(b)
    ma, mb = sum(ra) / n, sum(rb) / n
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    den = math.sqrt(sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb))
    return num / den if den > 0 else None


def tstat(x: list[float]) -> float | None:
    x = [v for v in x if v is not None and math.isfinite(v)]
    n = len(x)
    if n < 3:
        return None
    m = sum(x) / n
    sd = math.sqrt(sum((v - m) ** 2 for v in x) / (n - 1))
    return m / (sd / math.sqrt(n)) if sd > 0 else None


def m2_ranks(root: Path | None = None) -> dict[str, dict[str, float]]:
    """{ref_day: {coin: M2 percentile}} from the M2 low-vol shadow files (v2 book first)."""
    base = root or (notify.data_root() / "paper")
    out: dict[str, dict[str, float]] = {}
    for book in ("picks_ls", "picks_ls_v2"):
        f = base / book / "shadow_m2_lowvol.jsonl"
        try:
            text = f.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            day = datetime.fromtimestamp(int(r["day_us"]) / 1e6, timezone.utc).strftime("%Y-%m-%d")
            out[day] = {s.removesuffix("USDT"): float(v[0]) for s, v in (r.get("ranks") or {}).items()}
    return out


def score_rows(rows: list[dict], bars: dict[str, Bars], m2: dict[str, dict[str, float]] | None = None) -> dict:
    m2 = m2 or {}
    close = {c: {x["day"]: x["close"] for x in b} for c, b in bars.items()}
    weeks = []
    for ref in sorted({r["ref_day"] for r in rows}):
        end = (date.fromisoformat(ref) + timedelta(days=HORIZON)).isoformat()
        sel = [r for r in rows if r["ref_day"] == ref and close.get(r["coin"], {}).get(end) and r.get("ref_close")]
        if len(sel) < 5:
            continue
        y = [math.log(close[r["coin"]][end] / r["ref_close"]) for r in sel]
        up = [1 if v > 0 else 0 for v in y]
        w = {"ref_day": ref, "coins": len(sel),
             "ic_analyst": spearman([-r["rank"] for r in sel], y),
             "ic_lowvol": spearman([-r["vol30"] for r in sel], y),
             "ic_momentum": spearman([r["r28"] if r.get("r28") is not None else 0.0 for r in sel], y),
             "brier_analyst": sum((r["p_up"] - u) ** 2 for r, u in zip(sel, up)) / len(sel),
             "brier_base": sum((r["p_base"] - u) ** 2 for r, u in zip(sel, up)) / len(sel)}
        m = m2.get(ref)
        if m:
            both = [(r, v) for r, v in zip(sel, y) if r["coin"] in m]
            if len(both) >= 5:
                w["ic_m2"] = spearman([m[r["coin"]] for r, _ in both], [v for _, v in both])
                w["ic_analyst_on_m2_coins"] = spearman([-r["rank"] for r, _ in both], [v for _, v in both])
        weeks.append(w)
    out = {"weeks": weeks, "scored": len(weeks), "recorded_weeks": len({r["ref_day"] for r in rows})}
    for k in ("ic_analyst", "ic_lowvol", "ic_momentum", "ic_m2", "brier_analyst", "brier_base"):
        v = [w[k] for w in weeks if w.get(k) is not None]
        out[f"mean_{k}"] = sum(v) / len(v) if v else None
    out["t_analyst"] = tstat([w["ic_analyst"] for w in weeks])
    diff = [w["ic_analyst"] - w["ic_lowvol"] for w in weeks if w["ic_analyst"] is not None and w["ic_lowvol"] is not None]
    out["t_vs_lowvol"] = tstat(diff)
    ok = (len(weeks) >= MIN_WEEKS and (out["mean_ic_analyst"] or 0) > 0 and (out["t_analyst"] or 0) > PASS_T
          and (out["t_vs_lowvol"] or 0) > PASS_T)
    out["verdict"] = (f"Too early: {len(weeks)} scored weeks of {MIN_WEEKS}." if len(weeks) < MIN_WEEKS else
                      ("Passes the registered test (opens an ensemble study, nothing more)." if ok else
                       "Fails the registered test: it stays a shadow record."))
    return out


# ---------------------------------------------------------------- the job

def due(now_ms: int, rows: list[dict], force: bool) -> tuple[bool, str]:
    if force:
        return True, "forced"
    made = max((int(r.get("made_ms") or 0) for r in rows), default=0)
    age_d = (now_ms - made) / 86_400_000
    if made and age_d < EVERY_DAYS:
        return False, f"the last call is {age_d:.1f} days old"
    st = notify.read_json(notify.data_root() / "paper" / "picks_ls_v2" / "state.json") or {}
    reb = int(st.get("last_rebalance_ms") or 0)
    if reb and (now_ms - reb) / 3_600_000 <= ALIGN_HOURS:
        return True, "the M2 v2 book rebalanced today"
    if not made or age_d >= FALLBACK_DAYS:
        return True, "no call for a week"
    return False, "waiting for the M2 v2 rebalance"


def run(now_ms: int | None = None, dry_run: bool = False, force: bool = False, only_score: bool = False,
        loader=lake_bars, poster=None) -> int:
    now = now_ms or notify.clock_ms()
    day = datetime.fromtimestamp(now / 1000, timezone.utc).strftime("%Y-%m-%d")
    rows = read_rows()
    cs = coins()
    bars = bars_for(sorted(set(cs) | {r["coin"] for r in rows}), loader)
    rep = notify.reports_root() / NAME
    if not only_score:
        ok, why = due(now, rows, force or dry_run)
        if not ok:
            notify.say(f"analyst: not due ({why})")
        else:
            feats = {c: f for c in cs if (f := features(bars.get(c) or []))}
            if len(feats) < 5:
                notify.say("analyst: fewer than 5 coins with history, no call", err=True)
                return 1
            fund = {c: funding7(c) for c in feats}
            prompt = build_prompt(day, feats, fund, market_lines())
            if dry_run:
                notify.say(SYSTEM + "\n\n" + prompt)
                notify.say(f"\n[dry run] about {(len(SYSTEM) + len(prompt)) // 4:,} input tokens, at most {MAX_TOKENS} out")
                return 0
            try:
                ans = engine.complete("analyst", SYSTEM, prompt, MAX_TOKENS,
                                      model=engine.model_for("analyst", engine.REVIEW), schema=SCHEMA,
                                      effort=engine.effort_for("analyst", "medium"), batch=True,
                                      batch_wait_sec=BATCH_WAIT_SEC, poster=poster)
            except engine.AiError as e:
                notify.say(f"no analyst call: {e}", err=e.kind not in ("budget", "nokey"))
                return 0 if e.kind in ("budget", "nokey") else 1
            got, problems = parse_answer(ans.get("json"), list(feats))
            for p in problems:
                notify.say(f"analyst: {p}", err=True)
            cost = float(ans.get("costUsd") or 0.0)
            new = []
            for c, g in got.items():
                f = feats[c]
                comp = score.comparators([(x["day"], x["close"]) for x in bars[c]])
                new.append({"date": day, "made_ms": now, "coin": c, "ref_day": f["ref_day"], "ref_close": f["ref_close"],
                            "rank": g["rank"], "n": len(got), "p_up": g["p"], "reason": g["reason"],
                            "vol30": f["vol30"], "r28": f["r28"], "p_base": comp["base"],
                            "model": ans.get("servedBy") or ans.get("model") or engine.REVIEW,
                            "cost_usd_call": cost})
            score.append_predictions(new, path())
            rows += new
            notify.say(f"analyst {day}: {len(new)} coins ranked, ${cost:.4f}"
                       f"{' (batch)' if ans.get('batchId') else ''}")
    sc = score_rows(rows, bars, m2_ranks())
    calls = {}
    for r in rows:
        calls[r["made_ms"]] = float(r.get("cost_usd_call") or 0.0)
    sc.update(cost_usd_total=sum(calls.values()), calls=len(calls),
              title="AI analyst (shadow)", status="ok", updated_ms=now,
              headline=f"Weekly Claude ranking of the Alpaca coins, {sc['scored']} weeks scored. {sc['verdict']}",
              items=[{"label": "mean rank IC, analyst", "value": _r(sc.get("mean_ic_analyst"))},
                     {"label": "mean rank IC, low vol", "value": _r(sc.get("mean_ic_lowvol"))},
                     {"label": "mean rank IC, M2 (same days)", "value": _r(sc.get("mean_ic_m2"))}])
    notify.write_json(rep / "latest.json", sc)
    notify.say(sc["verdict"])
    return 0


def _r(v) -> str:
    return "n/a" if v is None else f"{v:+.3f}"


def main(argv: list[str] | None = None) -> int:
    argv = list(argv or [])
    return run(dry_run="--dry-run" in argv, force="--force" in argv, only_score="--score" in argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
