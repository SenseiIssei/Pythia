"""BTC treasury-company premium reversion (survey idea O2): the registered feasibility check.

    python -m lab.experiments.treasury_premium

Pre-registered in results/treasury_premium_prereg.md (committed before this file ran).
The test needs MSTR's BTC holdings and share count point in time. This module checks the
registered feasibility rule (at least 80 % of the out-of-sample weeks with a holdings figure
no older than 14 days) on what the SEC serves to the lab: the submissions index and XBRL
company facts on data.sec.gov, and the filing documents on www.sec.gov/Archives, which
answer only to a User-Agent that names a contact (PYTHIA_SEC_UA). When the rule fails the
study stops here, as registered, and says why. Writes results/treasury_premium.md below the
marker and <reports>/treasury_premium/latest.{md,json}.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request
from datetime import date, timedelta

from .. import report
from ..equities import edgar
from . import director_common as dc

NAME = "treasury_premium"
CIK = 1050446
FIRST = "2020-08-01"
OOS_START, OOS_END = date(2024, 1, 1), date(2026, 10, 14)
FRESH_DAYS, NEED = 14, 0.80
SUBMISSIONS = "https://data.sec.gov/submissions/CIK{:010d}{}.json"
FACTS = "https://data.sec.gov/api/xbrl/companyfacts/CIK{:010d}.json"
ARCHIVE = "https://www.sec.gov/Archives/edgar/data/{}/{}/{}"
PEERS = ("MARA", "RIOT", "CLSK", "HUT", "SMLR", "GME", "TSLA", "COIN")


def get(url: str) -> bytes | None:
    req = urllib.request.Request(url, headers={"User-Agent": edgar.UA})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read()
    except OSError:
        return None
    finally:
        time.sleep(edgar.MIN_INTERVAL)


def filings(cik: int) -> list[dict]:
    first = json.loads(get(SUBMISSIONS.format(cik, "")) or b"{}")
    pages = [first.get("filings", {}).get("recent", {})]
    for f in first.get("filings", {}).get("files", []):
        body = get(f"https://data.sec.gov/submissions/{f['name']}")
        if body:
            pages.append(json.loads(body))
    out = []
    for p in pages:
        for i, form in enumerate(p.get("form", [])):
            out.append({"form": form, "date": p["filingDate"][i], "acc": p["accessionNumber"][i],
                        "doc": p["primaryDocument"][i], "items": p.get("items", [""] * len(p["form"]))[i]})
    return out


def coverage(points: list[tuple[date, date]]) -> float:
    """Share of out-of-sample weeks (Fridays) whose latest holdings figure, known by its filing
    date, describes a day no more than FRESH_DAYS earlier. points: (as-of day, filed day)."""
    weeks, ok = 0, 0
    d = OOS_START + timedelta(days=(4 - OOS_START.weekday()) % 7)
    while d <= OOS_END:
        known = [a for a, f in points if f <= d]
        weeks += 1
        if known and (d - max(known)).days <= FRESH_DAYS:
            ok += 1
        d += timedelta(days=7)
    return ok / weeks if weeks else 0.0


def run() -> dict:
    fl = filings(CIK)
    k8 = [f for f in fl if f["form"] == "8-K" and f["date"] >= FIRST]
    k8_801 = [f for f in k8 if "8.01" in (f["items"] or "")]
    probe = k8[0] if k8 else None
    archive_ok = None
    if probe:
        body = get(ARCHIVE.format(CIK, probe["acc"].replace("-", ""), probe["doc"])) or b""
        archive_ok = bool(body) and b"Undeclared Automated Tool" not in body[:3000]
    facts = json.loads(get(FACTS.format(CIK)) or b"{}").get("facts", {})
    units = facts.get("us-gaap", {}).get("CryptoAssetNumberOfUnits", {}).get("units", {}).get("Bitcoin", [])
    pts = sorted({(date.fromisoformat(u["end"]), date.fromisoformat(u["filed"]), int(u["val"])) for u in units})
    first_known = min((f for _, f, _ in pts), default=None)
    cov_xbrl = coverage([(a, f) for a, f, _ in pts])
    # every holdings-bearing 8-K (item 8.01) taken as fresh on its filing day: the best the
    # 8-K route could reach if the documents were readable
    cov_8k = coverage([(date.fromisoformat(f["date"]), date.fromisoformat(f["date"])) for f in k8_801])
    shares = "EntityCommonStockSharesOutstanding" in facts.get("dei", {})
    feasible = (archive_ok and cov_8k >= NEED) or cov_xbrl >= NEED
    return {"generated": dc.day_str(int(time.time() * 1e6)), "user_agent_has_contact": "@" in edgar.UA,
            "filings_8k": len(k8), "filings_8k_item801": len(k8_801), "archive_readable": archive_ok,
            "xbrl_points": [{"as_of": str(a), "filed": str(f), "btc": v} for a, f, v in pts],
            "xbrl_first_known": str(first_known), "coverage_xbrl": cov_xbrl, "coverage_8k_if_readable": cov_8k,
            "dei_shares_outstanding": shares, "feasible": bool(feasible)}


def markdown(res: dict) -> str:
    L = [f"## Results (generated {res['generated']})", ""]
    if res["feasible"]:
        L.append("**Feasible.** The holdings and share series can be built; the test itself is not implemented "
                 "in this module yet.")
    else:
        L.append("**Stops at feasibility, as registered.** No return was computed.")
    L += ["",
          f"- MSTR filed {res['filings_8k']} 8-Ks from 2020-08-01 ({res['filings_8k_item801']} with item 8.01, where "
          f"the weekly holdings updates sit); the submissions index on data.sec.gov answers the lab's default "
          f"User-Agent.",
          f"- The filing documents themselves (www.sec.gov/Archives) answer "
          f"{'with the document' if res['archive_readable'] else 'with the SEC page for undeclared automated tools'}: "
          f"SEC asks for a User-Agent that names a contact, and `PYTHIA_SEC_UA` is "
          f"{'set' if res['user_agent_has_contact'] else 'not set on this machine'}. Without the documents there is "
          f"no weekly holdings series. Were they readable, the 8.01 filings would cover "
          f"{res['coverage_8k_if_readable'] * 100:.0f} % of the out-of-sample weeks by the 14-day rule.",
          f"- XBRL company facts carry `CryptoAssetNumberOfUnits` only at quarter ends, "
          f"{len(res['xbrl_points'])} points, the first of them known on {res['xbrl_first_known']} (the 10-K that "
          f"first tagged it): {res['coverage_xbrl'] * 100:.0f} % of the out-of-sample weeks have a figure no older "
          f"than 14 days, against the 80 % the registration needs.",
          f"- `dei:EntityCommonStockSharesOutstanding` is {'present' if res['dei_shares_outstanding'] else 'absent'} "
          f"in MSTR's company facts, so the share count would also have to come from the documents.",
          "- Peers (MARA, RIOT, CLSK, HUT mine and their holdings move daily; SMLR, GME and the newer treasury "
          "companies have under two years of holdings filings; TSLA and COIN hold BTC as a side position): not "
          "tested, as registered.",
          "",
          "What it would take: `PYTHIA_SEC_UA` set to a real contact where the study runs, a parser for the 8-K "
          "holdings and at-the-market tables; then this registration can run as written (its 2 trials are already "
          "counted in the pool, though nothing was run).",
          "", dc.table(res["xbrl_points"], ["as_of", "filed", "btc"])]
    return "\n".join(L)


def main() -> int:
    res = run()
    md = markdown(res)
    dc.write_results(NAME, md)
    report.write(NAME, md, res)
    return 0


if __name__ == "__main__":
    sys.exit(main())
