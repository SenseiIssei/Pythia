"""The live shadow books, traded on PAPER as the stream arrives, inside the collector:
the study's pick and the pick with the model filter in front, and every pipeline
strategy (pipeline.STRATEGIES) through the same pipeline a live executor would use.

Nothing here trades by itself: every fill of these books is the engine's curve
arithmetic (sim.py, pipeline.PaperExecutor), written to a paper ledger. The one
exception is live_exec.attach(), which adds a live book next to the paper ones
only when every gate of the LOCKED live executor holds (see live_exec.py); with
any gate shut it adds nothing and says why. The pick comes from
<reports>/pumpfun_rt/pick.json (the daily study writes it; the default rule
until then), the models from <data>/models/pumpfun_rt/ and the name categories
from <data>/pumpfun_rt/categories/; all are re-read every RELOAD_S, so a new
day's pick or model takes over without a restart. A change of pick starts the
pick's books afresh (the ledger keeps every closed trade with its rule).

Files under <data>/paper/pumpfun_rt/:
  ledger.csv     every closed paper trade (rule, token, times, prices, return, P&L in SOL)
  failed.csv     every buy that did not fill (slippage, curve completed), with its fee
  state.json     what is open, counts, the books' totals since start
  creators.json  the creator history (written every SAVE_S, read on start)
  wallets.json   the wallet reputation (the same)

Alerts (category "trending", lab.ops.notify, English or German): a closed
paper trade at +200 % or better, at most one an hour. Positions open when the
collector stops are lost (the token state is not kept); they are written to
the ledger as "restart" with no P&L and left out of every number.
"""

from __future__ import annotations

import csv
import json
import threading
import time
from pathlib import Path

from ..data import ROOT
from . import pipeline as P
from . import strategies as S
from . import wallets as W
from .sim import Engine, feed_row, model_rule
from .tokens import CreatorBook

RELOAD_S = 600
SAVE_S = 600
BIG_WIN = 2.0
ALERT_GAP_MS = 3_600_000
LEDGER_COLS = ["rule", "family", "mint", "name", "symbol", "created_ms", "signal_ms", "land_ms", "exit_signal_ms",
               "exit_ms", "exit_why", "signal_price", "entry_price", "exit_price", "proceeds_sol", "pnl_sol", "ret",
               "hold_s", "prob", "dev_dumped", "migrated", "gap", "age_s", "progress", "lat_buy_ms", "slip"]
FAILED_COLS = ["rule", "mint", "signal_ms", "land_ms", "why", "pnl_sol"]


def paper_dir() -> Path:
    return ROOT / "paper" / "pumpfun_rt"


def reports_dir() -> Path:
    from .. import report
    return report.REPORTS / "pumpfun_rt"


def read_pick() -> str:
    try:
        name = json.loads((reports_dir() / "pick.json").read_text(encoding="utf-8")).get("pick")
        if name in S.BY_NAME:
            return name
    except (OSError, ValueError):
        pass
    return S.DEFAULT_PICK


def append_csv(path: Path, cols: list[str], rows: list[dict]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        if new:
            w.writeheader()
        for r in rows:
            w.writerow(r)


class Shadow:
    def __init__(self, pick: str, models: dict | None = None, book: CreatorBook | None = None,
                 alerts: bool = True, now_ms: int | None = None, wallets: W.WalletBook | None = None, cats=None,
                 strategies: list | None = None, kill=None):
        from .model import Filter
        self.pick = pick
        self.book = book or CreatorBook()
        rule = S.BY_NAME[pick]
        self.models = models or {}
        self.engine = Engine([rule, model_rule(rule)], book=self.book, decisions=False,
                             model=Filter(self.models) if self.models else None, on_close=self._closed,
                             strategies=P.STRATEGIES if strategies is None else strategies,
                             wallets=wallets, cats=cats, models=self.models, kill=kill or P.KillSwitch())
        for pipe in self.engine.pipes:
            pipe.on_close = self._closed
        self.live = None                                      # live_exec.LiveBook, only when every gate holds
        self.cats_mtime = 0.0
        self.closed: list[dict] = []
        self.failed_seen = 0
        self.alerts = alerts
        self.last_alert_ms = 0
        self.last_reload = time.monotonic()
        self.last_save = time.monotonic()
        self.model_mtime = self._model_mtime()
        self.totals: dict[str, dict] = {}
        self.started_ms = now_ms or int(time.time() * 1000)

    # ------------------------------------------------------------ loading
    @staticmethod
    def _model_mtime() -> float:
        from .model import model_dir
        try:
            return max(p.stat().st_mtime for p in model_dir().glob("*.json"))
        except (ValueError, OSError):
            return 0.0

    @staticmethod
    def _cats_mtime() -> float:
        from .categorize import cat_dir
        try:
            return (cat_dir() / "cats.jsonl").stat().st_mtime
        except OSError:
            return 0.0

    @classmethod
    def load(cls, live: bool = True) -> "Shadow":
        from .categorize import BOOK_DAYS, CategoryIndex
        from .model import load
        book = None
        try:
            book = CreatorBook.from_json(json.loads((paper_dir() / "creators.json").read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass
        wallets = None
        try:
            wallets = W.WalletBook.from_json(json.loads((paper_dir() / "wallets.json").read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass
        sh = cls(read_pick(), load(), book, wallets=wallets,
                 cats=CategoryIndex.load(mints=False, max_age_days=BOOK_DAYS))
        sh.cats_mtime = cls._cats_mtime()
        if live:
            from . import live_exec
            sh.live = live_exec.attach(sh.engine)            # None unless every gate of the live executor holds
        try:
            st = json.loads((paper_dir() / "state.json").read_text(encoding="utf-8"))
            lost = [dict(p, exit_why="restart", pnl_sol=None, ret=None) for p in st.get("open") or []]
            append_csv(paper_dir() / "ledger.csv", LEDGER_COLS, lost)
            if st.get("pick") == sh.pick:
                sh.totals = st.get("totals") or {}
        except (OSError, ValueError):
            pass
        print(f"shadow: paper books {sh.pick} and {sh.pick}+model, and the pipeline strategies "
              + ", ".join(s.name for s in P.STRATEGIES)
              + ("" if sh.models else " (no model yet: the model-filtered books skip every signal)"), flush=True)
        return sh

    # ------------------------------------------------------------ the stream
    def on_row(self, table: str, row: dict) -> None:
        feed_row(self.engine, table, row)

    def tick(self, now_ms: int) -> None:
        self.engine.advance(now_ms)
        for pipe in self.engine.pipes:                        # the live executor's results, the kill switch
            pipe.poll(now_ms)
        mono = time.monotonic()
        if mono - self.last_reload >= RELOAD_S:
            self.last_reload = mono
            self.reload()

    def reload(self) -> None:
        """A new pick starts new books; a new model replaces the filter's model."""
        from .model import Filter, load
        pick = read_pick()
        mt = self._model_mtime()
        if pick != self.pick:
            print(f"shadow: the study's pick is now {pick} (was {self.pick}); new books", flush=True)
            self.save()
            self.pick = pick
            rule = S.BY_NAME[pick]
            self.engine.rules = [rule, model_rule(rule)]
            self.engine._index_rules()
            self.totals = {k: v for k, v in self.totals.items() if k in P.BY_NAME}
        if mt != self.model_mtime:
            self.model_mtime = mt
            self.models = load()
            self.engine.model = Filter(self.models) if self.models else None
            self.engine.models = self.models
        ct = self._cats_mtime()
        if ct != self.cats_mtime:
            from .categorize import BOOK_DAYS, CategoryIndex
            self.cats_mtime = ct
            self.engine.cats = CategoryIndex.load(mints=False, max_age_days=BOOK_DAYS)

    def _closed(self, rec: dict) -> None:
        self.closed.append(rec)
        tot = self.totals.setdefault(rec["rule"], {"n": 0, "wins": 0, "pnl_sol": 0.0, "ret_sum": 0.0})
        if not rec.get("gap"):
            tot["n"] += 1
            tot["wins"] += int(rec["ret"] > 0)
            tot["pnl_sol"] += rec["pnl_sol"]
            tot["ret_sum"] += rec["ret"]
        if self.alerts and rec["ret"] >= BIG_WIN and not rec.get("gap") \
                and rec["exit_ms"] - self.last_alert_ms >= ALERT_GAP_MS:
            self.last_alert_ms = rec["exit_ms"]
            threading.Thread(target=post_winner, args=(rec,), daemon=True).start()

    # ------------------------------------------------------------ files
    def status(self) -> dict:
        e = self.engine
        return {"pick": self.pick, "model": bool(self.models), "open": len(e.positions), "tokens": len(e.tokens),
                "closed": len(self.closed), "failed": len(e.failed), "totals": self.totals,
                "pipes": [p.status() for p in e.pipes], "live": self.live is not None,
                "wallets": len(e.wallets.rows), "categories": len(e.cats) if e.cats is not None else 0,
                "skipped": {f"{k[0]}: {k[1]}": v for k, v in e.skipped.items()}}

    def save(self) -> None:
        d = paper_dir()
        d.mkdir(parents=True, exist_ok=True)
        rows, self.closed = self.closed, []
        self.engine.closed = []                               # the ledger has them; memory stays bounded
        append_csv(d / "ledger.csv", LEDGER_COLS, rows)
        fails = self.engine.failed[self.failed_seen:]
        self.failed_seen = len(self.engine.failed)
        append_csv(d / "failed.csv", FAILED_COLS, fails)
        if len(self.engine.failed) > 10_000:
            self.engine.failed = []
            self.failed_seen = 0
        keep = ("rule", "family", "mint", "name", "symbol", "created_ms", "signal_ms", "land_ms", "signal_price",
                "entry_price")
        opened = [p for p in self.engine.positions.values() if p["state"] == "open"]
        for pipe in self.engine.pipes:
            if pipe.name == "paper":
                opened += [p for p in pipe.pos.values() if p["state"] == "open"]
        st = {"t": int(time.time() * 1000), "pick": self.pick, "started_ms": self.started_ms, "totals": self.totals,
              "open": [{k: p.get(k) for k in keep} for p in opened], "status": self.status()}
        if self.live is not None:
            self.live.save()
        tmp = d / "state.json.tmp"
        tmp.write_text(json.dumps(st, default=str), encoding="utf-8")
        tmp.replace(d / "state.json")
        mono = time.monotonic()
        if mono - self.last_save >= SAVE_S:
            self.last_save = mono
            tmp = d / "creators.json.tmp"
            tmp.write_text(json.dumps(self.book.to_json()), encoding="utf-8")
            tmp.replace(d / "creators.json")
            tmp = d / "wallets.json.tmp"
            tmp.write_text(json.dumps(self.engine.wallets.to_json(), separators=(",", ":")), encoding="utf-8")
            tmp.replace(d / "wallets.json")


def winner_card(rec: dict, lang: str = "en"):
    from ..ops import i18n, notify
    from .card import WHY as why
    t = i18n.t
    name = rec.get("symbol") or rec.get("name") or rec["mint"][:8]
    return notify.Card(
        "🚀", t("prt_win_title", lang, name=str(name)[:20], ret=i18n.frac_pct(rec["ret"], 0, lang)),
        t("prt_win_summary", lang, rule=rec["rule"], stake=f"{i18n.num(S.STAKE_SOL, 2, lang)} SOL",
          got=f"{i18n.num(rec['proceeds_sol'], 3, lang)} SOL", secs=i18n.num(rec["hold_s"], 0, lang),
          why=t(why.get(rec.get("exit_why"), "prt_why_time"), lang)),
        [notify.Line(t("prt_caveat", lang))], footer=t("prt_footer", lang))


def post_winner(rec: dict) -> None:
    try:
        from ..ops import notify
        notify.send("trending", [winner_card(rec, notify.alert_lang())], now=rec["exit_ms"])
    except Exception as e:                                   # an alert never stops the collector
        print(f"shadow: alert not sent ({type(e).__name__}: {e})", flush=True)
