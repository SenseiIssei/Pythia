"""The weekly analyst (X11 e1, since T15 e1b): one call a week ranks every Alpaca coin by its expected 7-day
return, scored exactly like M2 (rank IC) in shadow.

e1 (results/model_upgrades_prereg.md) asked Claude Sonnet through the engine's metered endpoint until the API
credit ran out (2026-10-28). e1b (results/analyst_local_prereg.md) asks through lab.ai.local, the chain the
briefing and the news use: the owner's large model on his PC through the relay when it is online, else the VPS
model (llama.cpp, Qwen3 4B Instruct). No API credit, no key. Each backend and model is its own series, scored on
its own; the Claude weeks stay as they are and are never mixed in.

The model sees a compact fact sheet per coin (7, 30 and 90-day returns, 30-day vol, distance to the 52-week high
and the 200-day mean, 28-day volume trend, 7-day funding where a perp exists) and a few market lines (BTC, the
Coinbase and Korean premiums, stablecoin growth, DVOL). No forecast of ours is shown. It answers per coin pUp7d
(probability the close 7 days after the reference close is higher) and expectedRank (1 = the best 7-day return
of the listed coins), one JSON object (SCHEMA). The answer is checked strictly (valid JSON, every coin once,
ranks 1 to n each once, pUp7d from 0 to 1); a bad one is asked again once on the same backend with the problem
named, then the week is skipped and logged in <data>/ai/analyst_skips.jsonl, never filled in.

Every answer is appended to <data>/ai/analyst.jsonl before its week starts, with its backend and model and the
references at the same moment (the 30-day vol, the 28-day return, the base rate). After the week: rank IC of
minus expectedRank against the realised 7-day log return, next to the low-vol rank, 28-day momentum and, where
the M2 shadow recorded the same reference day, M2's rank; Brier of pUp7d against the base rate. Pass (after at
least 26 scored weeks of one series): mean weekly IC above 0 with t above 2 and above the low-vol rank's with a
paired t above 2. Shadow only: nothing reads it to trade.

  python -m lab.ai.analyst             weekly, after the M2 v2 paper book (jobs.yaml: ai-analyst); exits 1 when
                                       no backend answered or the answer was bad twice
  python -m lab.ai.analyst --dry-run   print the prompt and its size, call nothing
  python -m lab.ai.analyst --force     another call this week
  python -m lab.ai.analyst --score     rescore only, no call
"""

from __future__ import annotations

import json
import math
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from ..ops import notify
from . import local, score

NAME = "ai_analyst"
HORIZON = 7
MIN_CLOSES = 120
OUT_PER_COIN = 40       # answer tokens a coin (the JSON entry and a short reason), plus OUT_BASE
OUT_BASE = 120
CALL_TIMEOUT = 20 * 60  # one call: the VPS model writes 2 to 9 tokens a second (ai/local_llm.jsonl)
BUDGET_SEC = 50 * 60    # every call of a run together (jobs.yaml: timeout 60m)
TRIAL_PREFIX = "hand:t15:analyst_e1b"
VPS_CONTEXT = 4096      # research/ops/local-llm.sh: -c 4096, prompt and answer together
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
- reason: at most 8 plain words naming the facts behind the rank.

Known facts about coin returns over a week, from the lab's own studies: relative ranks are somewhat \
predictable, absolute direction barely; low-volatility coins have tended to beat high-volatility ones; \
coins that rose most over the last few weeks have not reliably kept rising. Use your judgment on the facts \
given. Do not use em dashes. Answer with one JSON object only, no other text, every coin under RANK once:
{"ranking": [{"coin": "BTC", "expectedRank": 1, "pUp7d": 0.52, "reason": "..."}, ...], "market": "one short \
sentence"}"""

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


def num(v, scale=100.0, nd=1) -> str:
    return "n/a" if v is None else f"{scale * v:+.{nd}f}"


def build_prompt(day: str, feats: dict[str, dict], fund: dict[str, float | None], market: list[str]) -> str:
    """The fact sheet as one table, a row per coin (e1 wrote a sentence per coin with its close: the VPS model's
    4,096 tokens of context hold the prompt and the answer only this way; the close itself is left out, it says
    nothing about a 7-day rank, and the reference day is named once unless a coin's differs)."""
    ref = max(f["ref_day"] for f in feats.values())
    lines = [f"DATE: {day} (UTC). Horizon: 7 days from each coin's reference close ({ref} unless a row names "
             "another).", "",
             "COINS, one row each: coin | r7 | r30 | r90 (returns to the reference close, %) | vol30 (annualised, %) | "
             "vs 52w high (%) | vs 200d mean (%) | volume trend (28-day over 180-day mean volume, log) | funding 7d "
             "(%, perpetual, sum over the last 7 days, a long pays when positive)"]
    for c, f in feats.items():
        lines.append(f"{c} | {num(f['r7'])} | {num(f['r30'])} | {num(f['r90'])} | {100 * f['vol30']:.0f} | "
                     f"{num(f['vs_hi52'])} | {num(f['vs_ma200'])} | {num(f['volume_trend'], 1, 2)} | "
                     f"{num(fund.get(c), 100, 3)}" + ("" if f["ref_day"] == ref else f" | reference {f['ref_day']}"))
    if market:
        lines += ["", "MARKET:"] + ["- " + m for m in market]
    lines += ["", f"RANK ({len(feats)} coins): " + ", ".join(feats)]
    return "\n".join(lines)


def est_tokens(text: str) -> int:
    """Input tokens, roughly: Qwen's tokenizer writes every digit as one token, the rest about four characters."""
    d = sum(ch.isdigit() for ch in text)
    return int(d + (len(text) - d) / 4)


FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.S)


def parse_strict(text: str, cs: list[str]) -> tuple[dict[str, dict] | None, str]:
    """({coin: {rank, p, reason}}, "") when the answer is one JSON object (a ```json fence around it is fine) whose
    ranking holds every asked coin once with an integer expectedRank from 1 to n, each rank once, and pUp7d from 0
    to 1; else (None, the first problem in plain words, named to the model on the retry). Nothing is repaired."""
    t = (text or "").strip()
    m = FENCE.match(t)
    t = m.group(1) if m else t
    try:
        obj = json.loads(t)
    except ValueError as e:
        return None, f"not valid JSON ({getattr(e, 'msg', 'unreadable')} at character {getattr(e, 'pos', '?')})"
    if not isinstance(obj, dict) or not isinstance(obj.get("ranking"), list):
        return None, 'no "ranking" list in the JSON object'
    n, asked, got, by_rank = len(cs), set(cs), {}, {}
    for it in obj["ranking"]:
        if not isinstance(it, dict):
            return None, "an entry of ranking is not an object"
        c = str(it.get("coin") or "").strip().upper()
        if c not in asked:
            return None, f"{c or 'an entry without a coin'} was not asked for"
        if c in got:
            return None, f"{c} is listed twice"
        r, p = it.get("expectedRank"), it.get("pUp7d")
        if isinstance(r, bool) or not isinstance(r, (int, float)) or not math.isfinite(r) or r != int(r) \
                or not 1 <= r <= n:
            return None, f"{c}: expectedRank {r!r} is not an integer from 1 to {n}"
        if isinstance(p, bool) or not isinstance(p, (int, float)) or not math.isfinite(p) or not 0 <= p <= 1:
            return None, f"{c}: pUp7d {p!r} is not a number from 0 to 1"
        if int(r) in by_rank:
            return None, f"rank {int(r)} is given twice ({by_rank[int(r)]} and {c})"
        by_rank[int(r)] = c
        got[c] = {"rank": int(r), "p": float(p),
                  "reason": notify.nodash(" ".join(str(it.get("reason") or "").split()))[:200]}
    missing = [c for c in cs if c not in got]
    if missing:
        return None, "no entry for " + ", ".join(missing)
    return got, ""


def max_out(n: int) -> int:
    return OUT_BASE + OUT_PER_COIN * n


def ask(prompt: str, cs: list[str], bks: list[dict], chat=None, deadline: float | None = None
        ) -> tuple[dict[str, dict] | None, dict | None, str]:
    """(answer checked by parse_strict, {"backend", "model", ...} of the call it came from, why not) through the
    local chain (lab.ai.local.chat: the relay first when online, else the VPS model). A bad answer is asked again
    once on the same backend with the problem named (the first answer is not sent back: the VPS model's context
    holds the prompt and one answer, not two); then (None, the call, why)."""
    chat = chat or local.chat
    msgs = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}]
    ans = chat(msgs, "analyst", max_out(len(cs)), deadline, timeout=CALL_TIMEOUT, bks=bks)
    if ans is None:
        return None, None, "no backend answered"
    used = [b for b in bks if b["name"] == ans["backend"]]
    ans = {**ans, "model": used[0]["model"] if used else ans["backend"]}
    got, why = parse_strict(ans["text"], cs)
    if got is not None:
        return got, ans, ""
    notify.say(f"analyst: {ans['backend']} answered badly ({why}), asked once more")
    again = prompt + (f"\n\nYOUR LAST ANSWER COULD NOT BE USED: {why}. Answer again with the JSON object only: "
                      f"every coin under RANK once, expectedRank 1 to {len(cs)} each used once, pUp7d from 0 to 1.")
    ans2 = chat([msgs[0], {"role": "user", "content": again}], "analyst:retry", max_out(len(cs)), deadline,
                timeout=CALL_TIMEOUT, bks=used or bks)
    if ans2 is None:
        return None, ans, f"{why}; no answer on the retry"
    ans2 = {**ans2, "model": ans["model"]}
    got, why2 = parse_strict(ans2["text"], cs)
    return (got, ans2, "") if got is not None else (None, ans2, f"{why}; on the retry {why2}")


def series(r: dict) -> str:
    """A record's series: e1's Claude weeks (no backend) are "claude", e1b's each backend and model its own."""
    return f"{r['backend']}:{r.get('model') or '?'}" if r.get("backend") else "claude"


def trial(backend: str, model: str) -> dict:
    """The series' one trial in R5's registry (counted only), registered before its first record."""
    slug = re.sub(r"[^a-z0-9.]+", "-", str(model).lower()).strip("-")
    return {"id": f"{TRIAL_PREFIX}_{backend}_{slug}", "family": "hand", "n": 1, "sharpe": None, "var": None,
            "source": "results/analyst_local_prereg.md (T15 e1b, weekly rank IC, counted only)"}


def register_trial(backend: str, model: str) -> None:
    from .. import metrics
    try:
        metrics.register([trial(backend, model)])
    except OSError as e:
        notify.say(f"analyst: the registry could not be written ({e}); the trial counts when it can", err=True)


# ---------------------------------------------------------------- record and score

def path() -> Path:
    return score.ai_dir() / "analyst.jsonl"


def skips_path() -> Path:
    return score.ai_dir() / "analyst_skips.jsonl"


def read_skips() -> list[dict]:
    try:
        text = skips_path().read_text(encoding="utf-8")
    except OSError:
        return []
    out = []
    for line in text.splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if isinstance(r, dict) and r.get("made_ms"):
            out.append(r)
    return out


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
        loader=lake_bars, chat=None, env: dict | None = None) -> int:
    now = now_ms or notify.clock_ms()
    day = datetime.fromtimestamp(now / 1000, timezone.utc).strftime("%Y-%m-%d")
    rows = read_rows()
    skips = read_skips()
    cs = coins()
    bars = bars_for(sorted(set(cs) | {r["coin"] for r in rows}), loader)
    rep = notify.reports_root() / NAME
    code = 0
    if not only_score:
        ok, why = due(now, rows + skips, force or dry_run)
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
                notify.say(f"\n[dry run] {len(SYSTEM) + len(prompt):,} characters, about {est_tokens(SYSTEM + prompt):,} "
                           f"input tokens (a digit counted as one), at most {max_out(len(feats)):,} out; the VPS "
                           f"model's context is {VPS_CONTEXT:,}")
                return 0
            bks = local.backends(env)
            got, ans, why = (ask(prompt, list(feats), bks, chat, time.monotonic() + BUDGET_SEC) if bks else
                             (None, None, "the local model is off (PYTHIA_LOCAL_LLM)"))
            if got is None:
                skip = {"date": day, "made_ms": now, "ref_day": max(f["ref_day"] for f in feats.values()),
                        "backend": ans and ans["backend"], "model": ans and ans["model"], "why": why}
                score.append_predictions([skip], skips_path())
                skips.append(skip)
                notify.say(f"analyst {day}: week skipped, {why}", err=True)
                code = 1  # the job turns red; the week stays empty
            else:
                register_trial(ans["backend"], ans["model"])     # before the series' first record
                new = []
                for c, g in got.items():
                    f = feats[c]
                    comp = score.comparators([(x["day"], x["close"]) for x in bars[c]])
                    new.append({"date": day, "made_ms": now, "coin": c, "ref_day": f["ref_day"],
                                "ref_close": f["ref_close"], "rank": g["rank"], "n": len(got), "p_up": g["p"],
                                "reason": g["reason"], "vol30": f["vol30"], "r28": f["r28"], "p_base": comp["base"],
                                "backend": ans["backend"], "model": ans["model"],
                                "seconds": round(float(ans.get("seconds") or 0), 1), "tokens": ans.get("tokens"),
                                "cost_usd_call": 0.0})
                score.append_predictions(new, path())
                rows += new
                notify.say(f"analyst {day}: {len(new)} coins ranked by {ans['model']} ({ans['backend']}, "
                           f"{float(ans.get('seconds') or 0):.0f} s)")
    by = {}
    for r in rows:
        by.setdefault(series(r), []).append(r)
    m2 = m2_ranks()
    per = {k: score_rows(v, bars, m2) for k, v in by.items()}
    last = max(rows, key=lambda r: int(r.get("made_ms") or 0), default=None)
    key = series(last) if last else None
    sc = dict(per.get(key) or score_rows([], bars, m2))
    calls = {}
    for r in rows:
        calls[r["made_ms"]] = float(r.get("cost_usd_call") or 0.0)
    who = (f"{last.get('model')} ({last.get('backend') or 'claude'})" if last else "no model yet")
    sk = max(skips, key=lambda r: int(r["made_ms"]), default=None)
    sc.update(cost_usd_total=sum(calls.values()), calls=len(calls), series=per, current_series=key,
              last_model=last and last.get("model"), last_backend=last and (last.get("backend") or "claude"),
              last_ref_day=last and last.get("ref_day"), last_made_ms=last and last.get("made_ms"), last_skip=sk, min_weeks=MIN_WEEKS,
              title="AI analyst (shadow)", status="ok", updated_ms=now,
              headline=f"Weekly ranking of the Alpaca coins by {who}, {sc['scored']} weeks scored. {sc['verdict']}",
              items=[{"label": "mean rank IC, analyst", "value": _r(sc.get("mean_ic_analyst"))},
                     {"label": "mean rank IC, low vol", "value": _r(sc.get("mean_ic_lowvol"))},
                     {"label": "mean rank IC, M2 (same days)", "value": _r(sc.get("mean_ic_m2"))}])
    notify.write_json(rep / "latest.json", sc)
    notify.say(f"{key or 'no series'}: {sc['verdict']}")
    return code


def _r(v) -> str:
    return "n/a" if v is None else f"{v:+.3f}"


def main(argv: list[str] | None = None) -> int:
    argv = list(argv or [])
    return run(dry_run="--dry-run" in argv, force="--force" in argv, only_score="--score" in argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
