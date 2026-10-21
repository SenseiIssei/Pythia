"""SEC XBRL company facts, keyless: gross profit, assets and shares outstanding as filed.

Pre-registered in results/survey_equities_prereg.md (study 4, quality_issuance).

One request per company (data.sec.gov/api/xbrl/companyfacts/CIK##########.json),
through edgar.Client: the User-Agent comes from PYTHIA_SEC_UA, at most 5
requests a second, retries on 429 and 5xx. Each company file is fetched once and
kept gzipped under <cache>/companyfacts/ (PYTHIA_XBRL_DATA overrides the
folder); `refresh` fetches again. Every value keeps the date it was filed, so a
reader can stay point in time.

  facts.parquet   (cik, concept, unit, start, end, val, form, fp, filed, accn)
                  for the concepts in CONCEPTS only
"""

from __future__ import annotations

import gzip
import json
import os
import sys
from pathlib import Path

import numpy as np

from ..experiments import equities_ranking as er
from . import edgar

FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/{}"
GROSS = ("GrossProfit",)
REVENUE = ("Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet")
COST = ("CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold")
ASSETS = ("Assets",)
SHARES = ("EntityCommonStockSharesOutstanding",)          # dei
CONCEPTS = GROSS + REVENUE + COST + ASSETS + SHARES
FORMS = ("10-K", "10-K/A", "10-Q", "10-Q/A")


def cache_dir() -> Path:
    return Path(os.environ.get("PYTHIA_XBRL_DATA", str(er.CACHE / "edgar" / "xbrl")))


def fetch_company(client: edgar.Client, cik: int, refresh: bool = False) -> dict | None:
    """The company facts JSON (None when SEC has none for the CIK)."""
    d = cache_dir() / "companyfacts"
    d.mkdir(parents=True, exist_ok=True)
    name = f"CIK{cik:010d}.json"
    f = d / (name + ".gz")
    miss = d / (name + ".none")
    if not refresh:
        if f.exists():
            try:
                return json.loads(gzip.decompress(f.read_bytes()).decode("utf-8"))
            except (OSError, EOFError, ValueError):
                f.unlink()                 # cut short when a run was killed: fetch it again
        if miss.exists():
            return None
    body = client.get(FACTS_URL.format(name))
    if body is None:
        miss.write_text("404", encoding="utf-8")
        return None
    data = json.loads(body)
    tmp = f.with_suffix(".part")
    tmp.write_bytes(gzip.compress(body, 6))
    tmp.replace(f)
    return data


def rows_of(cik: int, data: dict) -> list[tuple]:
    """(cik, concept, unit, start, end, val, form, fp, filed, accn) for CONCEPTS."""
    out = []
    for tax in ("us-gaap", "dei"):
        facts = (data.get("facts") or {}).get(tax) or {}
        for c in CONCEPTS:
            if c not in facts:
                continue
            for unit, vals in (facts[c].get("units") or {}).items():
                for v in vals:
                    if v.get("form") not in FORMS or v.get("val") is None or not v.get("filed"):
                        continue
                    out.append((cik, c, unit, v.get("start") or "", v.get("end") or "", float(v["val"]),
                                v["form"], v.get("fp") or "", v["filed"], v.get("accn") or ""))
    return out


def build(ciks: dict[str, int], refresh: bool = False, client: edgar.Client | None = None, log=print) -> Path:
    """Fetch (or read from the cache) every company and write facts.parquet."""
    import polars as pl
    client = client or edgar.Client()
    rows, seen = [], set()
    todo = sorted(set(ciks.values()))
    for i, c in enumerate(todo):
        if c in seen:
            continue
        seen.add(c)
        try:
            data = fetch_company(client, c, refresh)
        except er.DataUnavailable as e:
            log(f"xbrl: CIK {c} skipped: {e}")
            continue
        if data:
            rows += rows_of(c, data)
        if (i + 1) % 50 == 0:
            log(f"xbrl: {i + 1} of {len(todo)} companies, {client.requests} requests")
    schema = ["cik", "concept", "unit", "start", "end", "val", "form", "fp", "filed", "accn"]
    frame = pl.DataFrame(rows, schema=schema, orient="row")
    out = cache_dir() / "facts.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    frame.write_parquet(out)
    log(f"xbrl: {len(seen)} companies, {frame.height} facts, {client.requests} requests")
    return out


def load(ciks: dict[str, int] | None = None, refresh: bool = False):
    """facts.parquet as a polars frame (built when missing and ciks are given)."""
    import polars as pl
    f = cache_dir() / "facts.parquet"
    if f.exists() and not refresh:
        return pl.read_parquet(f)
    if ciks is None:
        raise er.DataUnavailable("no XBRL facts cached and no CIK list to build them")
    build(ciks, refresh, log=lambda m: print(m, file=sys.stderr, flush=True))
    return pl.read_parquet(f)


# ---------------------------------------------------------------------------
# Point-in-time signals
# ---------------------------------------------------------------------------

def _days(s) -> np.ndarray:
    return np.array([np.datetime64(x[:10]) if x else np.datetime64("NaT") for x in s], dtype="datetime64[D]")


def annual_gpa(facts) -> dict[int, list[tuple]]:
    """Per CIK: [(filed, fiscal year end, gross profit / assets)] from 10-K filings.
    Gross profit is GrossProfit, else revenue minus cost of revenue, a fiscal-year
    value (350 to 380 days) of that filing; assets at the same year end, same filing."""
    import polars as pl
    f = facts.filter(pl.col("form").is_in(["10-K", "10-K/A"]) & (pl.col("unit") == "USD"))
    out: dict[int, list[tuple]] = {}
    for (cik, accn), g in f.group_by(["cik", "accn"]):
        filed = min(g["filed"].to_list())
        recs = {}
        for c, s, e, v in g.select("concept", "start", "end", "val").iter_rows():
            recs.setdefault(c, []).append((s, e, v))

        def annual(names: tuple) -> dict[str, float]:
            for n in names:
                vals = {}
                for s, e, v in recs.get(n, []):
                    if not s or not e:
                        continue
                    dur = (np.datetime64(e[:10]) - np.datetime64(s[:10])).astype(int)
                    if 350 <= dur <= 380:
                        vals[e[:10]] = v
                if vals:
                    return vals
            return {}

        gp = annual(GROSS)
        if not gp:
            rev, cost = annual(REVENUE), annual(COST)
            gp = {e: rev[e] - cost[e] for e in rev if e in cost}
        assets = {}
        for s, e, v in recs.get("Assets", []):
            if e:
                assets[e[:10]] = v
        if not gp:
            continue
        # The filing's own fiscal year: its latest year end with both values.
        ends = sorted(e for e in gp if e in assets and assets[e] > 0)
        if not ends:
            continue
        e = ends[-1]
        out.setdefault(int(cik), []).append((np.datetime64(filed[:10]), np.datetime64(e), gp[e] / assets[e]))
    for k in out:
        out[k].sort()
    return out


def shares_series(facts) -> dict[int, list[tuple]]:
    """Per CIK: [(filed, cover date, shares)] from 10-K and 10-Q cover pages, share
    classes of one filing and date summed."""
    import polars as pl
    f = facts.filter((pl.col("concept") == "EntityCommonStockSharesOutstanding") & (pl.col("unit") == "shares"))
    g = (f.group_by(["cik", "accn", "end"]).agg(pl.col("val").sum(), pl.col("filed").min())
         .sort(["cik", "filed", "end"]))
    out: dict[int, list[tuple]] = {}
    for cik, _a, end, val, filed in g.iter_rows():
        if val and val > 0 and end:
            out.setdefault(int(cik), []).append((np.datetime64(filed[:10]), np.datetime64(end[:10]), float(val)))
    return out
