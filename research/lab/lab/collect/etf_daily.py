"""The lab's copy of daily ETF closes (<data>/etf/daily/<SYM>.csv) downloaded again, one symbol at a time.

    python -m lab.collect.etf_daily

Readers: lab.experiments.etf_trend (SYMBOLS), the small-account books and studies (lab.paper.smallaccount,
smallaccount_s2, smallaccount_r10: SPY, QQQ, GLD), lab.history and the briefing (SPY, QQQ, GLD), EQ1's study and
paper books (lab.experiments.etf_books_eq1, lab.paper.etf_books: the UCITS funds in EUR on Xetra and IWM). Stooq first,
Yahoo's adjusted closes when Stooq serves a page (etf_trend.download); the UCITS funds (`.DE`) from Yahoo only (Stooq's
URL is for US listings). A symbol whose download fails or returns an error page keeps its old file
(etf_trend.load_csv never caches one). No study runs here. Exit 1 only when every symbol failed.
Job `etf-daily`, weekdays after the US close.
"""

from __future__ import annotations

import sys
import time

from ..experiments import etf_books_eq1 as eq1
from ..experiments import etf_trend as et

READERS = ("SPY", "QQQ", "GLD")             # smallaccount, R10, history and the briefing read these
UCITS = eq1.SYMBOLS                         # EQ1: Yahoo's .DE listings only
SYMBOLS = tuple(dict.fromkeys(et.SYMBOLS + READERS + UCITS + tuple(eq1.TWIN.values())))


def refresh(syms=SYMBOLS, fetch=et.download, pause_s: float = 1.0) -> dict[str, str]:
    """{symbol: "ok" or why it failed}; a failed symbol's file is left as it was."""
    out = {}
    for i, s in enumerate(syms):
        if i and pause_s:
            time.sleep(pause_s)
        try:
            et.load_csv(s, refresh=True, fetch=et.download_yahoo if s in UCITS and fetch is et.download else fetch)
            out[s] = "ok"
        except (et.DataUnavailable, OSError, ValueError) as e:
            out[s] = f"{type(e).__name__}: {e}"[:200]
    return out


def main(fetch=et.download, pause_s: float = 1.0) -> int:
    res = refresh(fetch=fetch, pause_s=pause_s)
    bad = {s: why for s, why in res.items() if why != "ok"}
    for s, why in bad.items():
        print(f"etf {s}: {why}; old file kept", file=sys.stderr)
    print(f"etf daily: {len(res) - len(bad)} of {len(res)} refreshed into {et.CACHE}")
    return 1 if res and len(bad) == len(res) else 0


if __name__ == "__main__":
    sys.exit(main())
