"""How late our feed hands us a pump.fun token's creation. Read only.

    python -m lab.pumpfun_rt.latency                    the record's last 24 hours: report and latency.json
    python -m lab.pumpfun_rt.latency --hours 0          the whole record
    python -m lab.pumpfun_rt.latency probe --seconds 120    a live probe of the configured endpoints

Chain time. The record has no millisecond clock of the chain, but every event
carries the program's block timestamp (`bts`, whole seconds, the cluster's
clock for that slot). Fitting `bts * 1000 + 500` against the slot number by
least squares in windows of FIT_WINDOW_MS gives the chain time of any slot
(the truncation to a second is uniform, so the half second makes the fit
unbiased) and the slot length (the slope; about 216 ms on 2026-10-20, not
the 400 ms of older documentation).

Detection latency of a creation = our receive time minus the chain time of
its slot, in ms and in slots. Two checks that need no clock at all:

  seen tip    how many newer slots we had already received any event of when
              the creation arrived (a lower bound on how far behind we are)
  slot lag    the delay behind the first event we received of the same slot

The probe asks each endpoint for its own slot notifications (slotSubscribe,
"processed") and its pump.fun log notifications at "confirmed" and
"processed", and reports how many slots and ms the logs trail the endpoint's
own tip and the block timestamp: the clock-free answer to "how late is this
provider". Endpoints: PYTHIA_SOLANA_WS_URLS (comma separated, a "{token}"
in a URL is replaced by PYTHIA_SOLANA_TOKEN, so no key is ever written into
a file of this repository), else PYTHIA_SOLANA_WS, else the public endpoint.
Only scheme and host are ever printed.

The live service's targeted provider streams (live_service.Providers, one ProviderWatch per provider) count, per
transaction of a watched or held coin that came over a provider and over a public link, which was first and by how
many ms, the bytes each provider sent and the time it was benched per day (data/live/pumpfun_rt/provider.json);
save() adds them as "provider vs public, watched coins", one row per provider.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import sys
import time
import urllib.parse
from datetime import datetime, timezone

import numpy as np

FIT_WINDOW_MS = 15 * 60_000
MIN_FIT_SLOTS = 50
DEFAULT_SLOT_MS = 400.0
BUCKETS = ((0, 1, "slot"), (1, 2, "+1"), (2, 3, "+2"), (3, 5, "+3..4"), (5, 10, "+5..9"), (10, 50, "+10..49"),
           (50, math.inf, "+50"))
PCTS = (10, 25, 50, 75, 90, 99)
DEFAULT_WS = "wss://api.mainnet-beta.solana.com"


# ---------------------------------------------------------------- endpoints

def ws_urls(env=None) -> list[str]:
    """The websocket endpoints to use, providers first: PYTHIA_SOLANA_WS_URLS (comma separated, "{token}"
    replaced by PYTHIA_SOLANA_TOKEN), else PYTHIA_SOLANA_WS, else the public endpoint. A URL whose token is
    missing is left out (it would only fail)."""
    env = os.environ if env is None else env
    token = env.get("PYTHIA_SOLANA_TOKEN") or ""
    out = []
    for u in (env.get("PYTHIA_SOLANA_WS_URLS") or "").split(","):
        u = u.strip()
        if not u:
            continue
        if "{token}" in u:
            if not token:
                continue
            u = u.replace("{token}", urllib.parse.quote(token, safe=""))
        if u.startswith(("ws://", "wss://")) and u not in out:
            out.append(u)
    if not out:
        out.append((env.get("PYTHIA_SOLANA_WS") or "").strip() or DEFAULT_WS)
    return out


def safe_url(url: str) -> str:
    """Scheme and host only: never a path, query or key in a log line or a report."""
    try:
        u = urllib.parse.urlsplit(url)
        return f"{u.scheme}://{u.hostname or '?'}"
    except ValueError:
        return "?"


# ---------------------------------------------------------------- the chain clock

class ChainClock:
    """Chain time (ms) of a slot from (slot, bts) pairs: a least-squares line per window of FIT_WINDOW_MS."""

    def __init__(self, slots, bts, window_ms: int = FIT_WINDOW_MS):
        s = np.asarray(slots, dtype=np.int64)
        b = np.asarray(bts, dtype=np.int64)
        ok = (s > 0) & (b > 0)
        s, b = s[ok], b[ok]
        if len(s):
            order = np.argsort(s, kind="stable")
            s, b = s[order], b[order]
            u, first = np.unique(s, return_index=True)
            s, b = u, b[first]
        self.ref = int(s[0]) if len(s) else 0
        y = b.astype(float) * 1000.0 + 500.0
        x = (s - self.ref).astype(float)
        starts, slopes, icepts = [], [], []
        if len(s):
            w = ((b * 1000 - int(b[0]) * 1000) // window_ms).astype(np.int64)
            for k in np.unique(w):
                m = w == k
                if m.sum() < MIN_FIT_SLOTS or np.ptp(x[m]) <= 0:
                    continue
                k1, k0 = np.polyfit(x[m], y[m], 1)
                starts.append(x[m][0])
                slopes.append(k1)
                icepts.append(k0)
            if not starts and len(s) >= 2 and np.ptp(x) > 0:
                k1, k0 = np.polyfit(x, y, 1)
                starts, slopes, icepts = [x[0]], [k1], [k0]
        self.starts = np.asarray(starts, dtype=float)
        self.slopes = np.asarray(slopes, dtype=float)
        self.icepts = np.asarray(icepts, dtype=float)

    @property
    def ok(self) -> bool:
        return len(self.starts) > 0

    def slot_ms(self) -> float:
        """The median slot length of the windows (ms)."""
        return float(np.median(self.slopes)) if self.ok else DEFAULT_SLOT_MS

    def at(self, slots) -> np.ndarray:
        """Chain time in ms of each slot (NaN without a fit)."""
        x = np.asarray(slots, dtype=float) - self.ref
        if not self.ok:
            return np.full(np.shape(x), np.nan)
        i = np.clip(np.searchsorted(self.starts, x, side="right") - 1, 0, len(self.starts) - 1)
        return self.icepts[i] + self.slopes[i] * x


# ---------------------------------------------------------------- the record

def _pct(a) -> dict:
    a = np.asarray(a, dtype=float)
    a = a[np.isfinite(a)]
    if not len(a):
        return {f"p{p}": None for p in PCTS}
    return {f"p{p}": float(np.percentile(a, p)) for p in PCTS}


def bucket_of(lag_slots: float) -> str:
    for lo, hi, name in BUCKETS:
        if lo <= lag_slots < hi:
            return name
    return BUCKETS[0][2] if lag_slots < 0 else BUCKETS[-1][2]


def frames(days: list[str], root=None) -> dict:
    """The record's creations and every event's (slot, receive time, block time), as numpy arrays."""
    import polars as pl

    from . import store
    cr = store.read("creates", days, root)
    parts = []
    for tb in ("creates", "trades", "amm", "other"):
        df = store.read(tb, days, root)
        if df.height and "slot" in df.columns:
            parts.append(df.select(pl.col("slot").cast(pl.Int64), pl.col("t").cast(pl.Int64),
                                   pl.col("bts").cast(pl.Int64), pl.lit(tb).alias("tb")))
    ev = pl.concat(parts) if parts else pl.DataFrame(schema={"slot": pl.Int64, "t": pl.Int64, "bts": pl.Int64,
                                                             "tb": pl.Utf8})
    ev = ev.filter(pl.col("slot").is_not_null() & pl.col("t").is_not_null())
    cr = cr.filter(pl.col("slot").is_not_null() & pl.col("t").is_not_null())
    return {"c_t": cr["t"].to_numpy().astype(np.int64), "c_slot": cr["slot"].to_numpy().astype(np.int64),
            "c_mint": cr["mint"].to_list(), "e_t": ev["t"].to_numpy().astype(np.int64),
            "e_slot": ev["slot"].to_numpy().astype(np.int64),
            "e_bts": ev["bts"].fill_null(0).to_numpy().astype(np.int64), "e_trade": (ev["tb"] == "trades").to_numpy()}


def measure(fr: dict, since_ms: int | None = None, until_ms: int | None = None) -> dict:
    """Detection latency of every creation in [since_ms, until_ms) (receive time), with the clock-free checks,
    the buckets in slots and the hourly percentiles. Also the delivery delay of curve trades (the NOW tier)."""
    clock = ChainClock(fr["e_slot"], fr["e_bts"])
    slot_ms = clock.slot_ms()
    ct, cs = fr["c_t"], fr["c_slot"]
    m = np.ones(len(ct), dtype=bool)
    if since_ms is not None:
        m &= ct >= since_ms
    if until_ms is not None:
        m &= ct < until_ms
    ct, cs = ct[m], cs[m]
    out: dict = {"n": int(len(ct)), "slot_ms": slot_ms, "clock_ok": clock.ok}
    if not len(ct) or not clock.ok:
        return out
    chain = clock.at(cs)
    lag = ct - chain
    lag_slots = lag / slot_ms
    # clock-free: newest slot seen before the creation arrived, and the first receive of its own slot
    et, es = fr["e_t"], fr["e_slot"]
    o = np.argsort(et, kind="stable")
    et_s, tip = et[o], np.maximum.accumulate(es[o])
    k = np.searchsorted(et_s, ct, side="left") - 1
    seen = np.where(k >= 0, tip[np.clip(k, 0, None)] - cs, 0)
    so = np.argsort(es, kind="stable")
    us, starts = np.unique(es[so], return_index=True)
    first_t = np.minimum.reduceat(et[so], starts) if len(starts) else np.zeros(0, dtype=np.int64)
    k2 = np.clip(np.searchsorted(us, cs), 0, max(0, len(us) - 1))
    hit = (len(us) > 0) & (us[k2] == cs) if len(us) else np.zeros(len(cs), dtype=bool)
    behind_first = np.where(hit, ct - first_t[k2], 0)
    names = [b[2] for b in BUCKETS]
    counts = {n: 0 for n in names}
    for x in lag_slots:
        counts[bucket_of(float(x))] += 1
    hours: dict[str, list] = {}
    for c, x in zip(chain, lag):
        h = datetime.fromtimestamp(c / 1000, timezone.utc).strftime("%Y-%m-%d %H:00")
        hours.setdefault(h, []).append(x)
    tr = fr["e_trade"]
    tdelay = et[tr] - clock.at(es[tr])
    if since_ms is not None:
        tdelay = tdelay[et[tr] >= since_ms]
    out.update({
        "lag_ms": _pct(lag), "lag_slots": _pct(lag_slots), "mean_ms": float(np.mean(lag)),
        "buckets": counts, "shares": {n: counts[n] / len(lag) for n in names},
        "within_1s": float(np.mean(lag <= 1000)), "within_2s": float(np.mean(lag <= 2000)),
        "within_5s": float(np.mean(lag <= 5000)),
        "seen_tip_slots": _pct(seen), "behind_first_ms": _pct(behind_first),
        "hours": [{"hour": h, "n": len(v), **{k_: v_ for k_, v_ in _pct(v).items() if k_ in ("p10", "p50", "p90")}}
                  for h, v in sorted(hours.items())],
        "trade_delay_ms": _pct(tdelay),
        "from_ms": int(ct.min()), "to_ms": int(ct.max())})
    return out


def trade_delays(fr: dict, n: int = 20_000, seed: int = 3) -> np.ndarray:
    """A sample of the record's curve-trade delivery delays (ms after the slot's chain time), for the NOW tier."""
    clock = ChainClock(fr["e_slot"], fr["e_bts"])
    tr = fr["e_trade"]
    d = fr["e_t"][tr] - clock.at(fr["e_slot"][tr])
    d = d[np.isfinite(d)]
    if len(d) > n:
        d = np.random.default_rng(seed).choice(d, n, replace=False)
    return np.sort(d)


def summary(days: list[str], root=None, now_ms: int | None = None, hours: float = 24.0) -> dict:
    """The record's detection latency over the last `hours` (0: all of it), for the study and the card."""
    fr = frames(days, root)
    now_ms = now_ms or int(time.time() * 1000)
    since = now_ms - int(hours * 3_600_000) if hours else None
    res = measure(fr, since_ms=since)
    res["hours_window"] = hours
    return res


def provider_label(label: str) -> str:
    """A provider's label from the file as scheme and host again (and a "#2" of a second plan), whatever it holds."""
    base, _, n = str(label).partition("#")
    return safe_url(base) + (f"#{n}" if n.isdigit() else "")


def provider_summary(path=None) -> list[dict] | None:
    """One row per provider of the live service's provider file, over the days it keeps: transactions over both,
    the provider's share first, its median and p90 lead (ms; negative: the public copy was first), the MB received
    per day (mean of the days), the hours benched and why it is benched now. None without the file."""
    if path is None:
        from . import live_exec as LX
        path = LX.data_dir() / "provider.json"
    try:
        f = json.loads(path.read_text(encoding="utf-8"))
        provs = f.get("providers")
        if not isinstance(provs, dict):                      # a file of one provider (task 90)
            provs = {str(f.get("host") or "?"): {"days": f.get("days") or {}}}
    except (OSError, ValueError, AttributeError):
        return None
    out = []
    for label, p in sorted(provs.items()):
        days = [v for v in ((p or {}).get("days") or {}).values() if isinstance(v, dict)] if isinstance(p, dict) else []
        leads = [x for v in days for x in v.get("leads") or [] if isinstance(x, (int, float))]
        n = sum(int(v.get("n") or 0) for v in days)
        first = sum(int(v.get("first") or 0) for v in days)
        b = p.get("benched") if isinstance(p, dict) else None
        out.append({"provider": provider_label(label), "days": len(days), "n": n,
                    "share_first": first / n if n else None,
                    "median_lead_ms": float(np.median(leads)) if leads else None,
                    "p90_lead_ms": float(np.percentile(leads, 90)) if leads else None,
                    "mb_day": round(sum(v.get("bytes") or 0 for v in days) / 1e6 / len(days), 2) if days else 0.0,
                    "benched_h": round(sum(float(v.get("benched_s") or 0) for v in days) / 3600, 2),
                    "benched_now": b if b in ("unsupported", "budget", "refused", "error", "closed") else None})
    return out


def provider_md(rows: list[dict] | None) -> list[str]:
    if rows is None:
        return []
    md = ["", "## provider vs public, watched coins", "",
          "Transactions of the coins the live bot watched or held that came over a provider and a public link, one "
          "row per provider over the days kept (lead: how much earlier the provider's copy was; negative, the public "
          "one was first; benched: refused, errored, closed or out of its day's budget).", ""]
    if not rows:
        return md + ["Nothing measured yet."]
    md += ["| provider | days | n | provider first | median lead | p90 lead | MB a day | benched |",
           "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        def ms(x):
            return "n/a" if x is None else f"{x:.0f} ms"
        first = "n/a" if r["share_first"] is None else f"{r['share_first']:.0%}"
        bench = f"{r['benched_h']:.1f} h" + (f", now {r['benched_now']}" if r["benched_now"] else "")
        md.append(f"| {r['provider']} | {r['days']} | {r['n']:,} | {first} | {ms(r['median_lead_ms'])} "
                  f"| {ms(r['p90_lead_ms'])} | {r['mb_day']:.1f} | {bench} |")
    return md


def report_md(res: dict) -> str:
    def s(x):
        return "n/a" if x is None else f"{x / 1000:.1f} s"
    if not res.get("n") or "lag_ms" not in res:
        return "\n".join(["# pump.fun detection latency", "", "No creations in the window."]
                         + provider_md(res.get("provider"))) + "\n"
    lm, ls = res["lag_ms"], res["lag_slots"]
    md = ["# pump.fun detection latency", "",
          f"{res['n']:,} creations; slot length {res['slot_ms']:.0f} ms (fitted from the block timestamps).", "",
          "| | p10 | p25 | p50 | p75 | p90 | p99 |", "|---|---|---|---|---|---|---|",
          "| behind the block (chain clock) | " + " | ".join(s(lm[f"p{p}"]) for p in PCTS) + " |",
          "| in slots | " + " | ".join(f"{ls[f'p{p}']:.0f}" for p in PCTS) + " |",
          "| newer slots already seen (no clock) | " + " | ".join(f"{res['seen_tip_slots'][f'p{p}']:.0f}"
                                                              for p in PCTS) + " |",
          "| behind the first event of the slot (no clock) | " + " | ".join(s(res['behind_first_ms'][f'p{p}'])
                                                                       for p in PCTS) + " |",
          "| curve trades behind the block | " + " | ".join(s(res['trade_delay_ms'][f'p{p}']) for p in PCTS) + " |",
          "", "| seen | creations | share |", "|---|---|---|"]
    for name, n in res["buckets"].items():
        md.append(f"| {name} | {n:,} | {res['shares'][name]:.1%} |")
    md += ["", f"Within 1 s: {res['within_1s']:.1%}, within 2 s: {res['within_2s']:.1%}, within 5 s: "
               f"{res['within_5s']:.1%}.", "", "| hour (UTC) | creations | p10 | p50 | p90 |", "|---|---|---|---|---|"]
    for h in res["hours"]:
        md.append(f"| {h['hour']} | {h['n']:,} | {s(h['p10'])} | {s(h['p50'])} | {s(h['p90'])} |")
    return "\n".join(md + provider_md(res.get("provider"))) + "\n"


def save(res: dict) -> None:
    from .. import report as rep
    try:                                                     # the live service's provider stream, when it has one
        prov = provider_summary()
    except Exception:
        prov = None
    if prov is not None:
        res = {**res, "provider": prov}
    d = rep.REPORTS / "pumpfun_rt"
    d.mkdir(parents=True, exist_ok=True)
    (d / "latency.json").write_text(json.dumps(res, indent=1, default=float), encoding="utf-8")
    (d / "latency.md").write_text(report_md(res), encoding="utf-8")


# ---------------------------------------------------------------- the live probe

class Probe:
    """One endpoint: its own processed tip, and the lag of its pump.fun log notifications behind it."""

    def __init__(self, url: str):
        self.url = url
        self.tip = 0
        self.lag: dict[str, list] = {"confirmed": [], "processed": []}
        self.ms: dict[str, list] = {"confirmed": [], "processed": []}
        self.create: dict[str, list] = {"confirmed": [], "processed": []}
        self.raw_creates: list[str] = []

    def on_slot(self, text: str) -> None:
        try:
            d = json.loads(text)
            s = int(((d.get("params") or {}).get("result") or {}).get("slot") or 0)
        except (ValueError, TypeError, AttributeError):
            return
        self.tip = max(self.tip, s)

    def on_logs(self, text: str, commitment: str, recv_ms: int, keep_raw: int = 0) -> None:
        from . import events as E
        try:
            d = json.loads(text)
        except ValueError:
            return
        res = (d.get("params") or {}).get("result") if isinstance(d, dict) else None
        if not res:
            return
        v = res.get("value") or {}
        slot = (res.get("context") or {}).get("slot") or 0
        if v.get("err") is not None or not slot:
            return
        if self.tip:
            self.lag[commitment].append(self.tip - slot)
        for name, ev in E.events_of(v.get("logs") or []):
            ts = ev.get("timestamp")
            if ts:
                self.ms[commitment].append(recv_ms - ts * 1000)
            if name == "CreateEvent":
                self.create[commitment].append(self.tip - slot if self.tip else None)
                if keep_raw and len(self.raw_creates) < keep_raw:
                    self.raw_creates.append(text)

    def result(self) -> dict:
        out = {"endpoint": safe_url(self.url)}
        for c in ("confirmed", "processed"):
            cl = [x for x in self.create[c] if x is not None]
            out[c] = {"messages": len(self.lag[c]), "behind_tip_slots": _pct(self.lag[c]),
                      "behind_block_ms": _pct(self.ms[c]), "creations": len(self.create[c]),
                      "creation_behind_tip_slots": _pct(cl)}
        return out


async def _probe(url: str, seconds: float, keep_raw: int = 0) -> Probe:
    import aiohttp
    from . import events as E
    p = Probe(url)

    async def slots(session):
        async with session.ws_connect(url, heartbeat=None, max_msg_size=16 << 20) as ws:
            await ws.send_str(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "slotSubscribe"}))
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    p.on_slot(msg.data)

    async def logs(session, commitment):
        async with session.ws_connect(url, heartbeat=None, max_msg_size=16 << 20) as ws:
            await ws.send_str(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "logsSubscribe",
                                          "params": [{"mentions": [E.PUMP]}, {"commitment": commitment}]}))
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    p.on_logs(msg.data, commitment, int(time.time() * 1000), keep_raw)

    async with aiohttp.ClientSession() as session:
        tasks = [asyncio.create_task(slots(session)), asyncio.create_task(logs(session, "confirmed")),
                 asyncio.create_task(logs(session, "processed"))]
        await asyncio.sleep(seconds)
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    return p


def probe(seconds: float = 120.0, urls: list[str] | None = None, keep_raw: int = 0) -> list[dict]:
    """Probe every endpoint one after the other (three connections each, read only)."""
    out = []
    for u in urls or ws_urls():
        p = asyncio.run(_probe(u, seconds, keep_raw))
        r = p.result()
        r["seconds"] = seconds
        if keep_raw:
            r["raw_creates"] = p.raw_creates
        out.append(r)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", nargs="?", default="record", choices=("record", "probe"))
    ap.add_argument("--hours", type=float, default=24.0, help="the record's last N hours (0: all)")
    ap.add_argument("--seconds", type=float, default=120.0, help="probe: seconds per endpoint")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "probe":
        for r in probe(a.seconds):
            print(json.dumps(r, indent=1))
        return 0
    from . import store
    days = store.days()
    if not days:
        print("pumpfun_rt latency: nothing recorded yet")
        return 1
    res = summary(days, hours=a.hours, now_ms=None if a.hours else None)
    print(report_md(res))
    if not a.dry_run:
        save(res)
    return 0


if __name__ == "__main__":
    sys.exit(main())
