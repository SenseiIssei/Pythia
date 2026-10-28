"""The live shadow books, traded on PAPER as the stream arrives, inside the collector:
the study's pick and the pick with the model filter in front, and every pipeline
strategy (pipeline.STRATEGIES) through the same pipeline a live executor would use.

Since R1 every pipeline book is REALISTIC (realistic.py): the live bot's measured latency, fills at the first recorded
trade after the landing, its bounds, failures, fees and sizing on a paper wallet of 0.55 SOL per book, under the
strategy's own name; the old books (0.4 to 3 s, 0.1 SOL) run on as `<name>_ideal` until realistic.IDEAL_UNTIL_MS.
The day's fit (reports/pumpfun_rt/realistic.json) and the live sizing settings are re-read every RELOAD_S.
R2's small-wallet picks (realistic.SMALL) run next to them as realistic books of their own, each on its own 0.55 SOL
paper wallet with its sizing fixed as picked (realistic.small_books).
P3's 10 EUR books (realistic.TEN) run the same way, each on its own 0.109 SOL paper wallet that is never topped up and
holds a token account's rent while a position is open (realistic.ten_books).
F3's factory books (factory.py, <data>/pumpfun_rt/factory/books.json) run the same way (realistic.factory_books); the
file is re-read every RELOAD_S: a new book starts, a retired one goes once it holds nothing.
E1's bound books (slippage_e1.shadow_books, results/slippage_e1_prereg.md) run the live rules with each bound pair of
its grid as `<rule>@e1_<pair>`, realistic with the live sizing on their own 0.55 SOL paper wallets.

Nothing here trades: every fill of these books is the engine's curve
arithmetic (sim.py, pipeline.PaperExecutor), written to a paper ledger. The
live book (real money) runs only in its own service, live_service.py, which the
owner starts by hand; the collector never holds a wallet. The pick comes from
<reports>/pumpfun_rt/pick.json (the daily study writes it; the default rule
until then), the models from <data>/models/pumpfun_rt/ and the name categories
from <data>/pumpfun_rt/categories/; all are re-read every RELOAD_S, so a new
day's pick or model takes over without a restart. A change of pick starts the
pick's books afresh (the ledger keeps every closed trade with its rule).

Files under <data>/paper/pumpfun_rt/:
  ledger.csv     every closed paper trade (rule, token, times, prices, return, P&L in SOL)
  failed.csv     every buy that did not fill (slippage, curve completed), with its fee
  state.json     what is open, counts, the books' totals since start, the realistic books' paper wallets and
                 realistic_since (when the realistic books took over the names)
  creators.json  the creator history (written every SAVE_S, read on start)
  wallets.json   the wallet reputation (the same)
  snipers.json   the sniper book of the X14 early features (the same)

The engine has Y10's trend tracker (trendfeat.py): the trend features of the select and early models and the
trend strategies' 10 s clock; and Y14's social tracker (socialfeat.py), warmed on start from the record's last
socialfeat.WARM_DAYS days of metadata, so the social features count the coins before the restart too.
And <reports>/pumpfun_rt/trends.json every trends.WRITE_S (trends.py, the Trends page): what is hot right now,
read from the engine after it took each row, so it changes no decision.

Rows of a coin the engine does not know yet wait up to HOLD_MS for its creation and follow it then (Hold; the live
service does the same): a migration that came before its creation was dropped here and taken there. The paper twin
of the live strategy (blocklist.PAPER_RULES) has the live bot's category rule (livecat.CategoryGate: a blocked
name category is a skip, a coin without one at the buy is asked alone at once) and writes every coin it does not buy
with its reason to
<data>/paper/pumpfun_rt/skipped.jsonl, as the live book does to its own (live_exec.paper_match reads both); a
"no pool state" while every PumpSwap link of the collector was down says so (Pipeline.feed_down).

Alerts (category "trending", lab.ops.notify, English or German): a closed
paper trade at +200 % or better, at most one an hour. Positions open when the
collector stops are lost (the token state is not kept); they are written to
the ledger as "restart" with no P&L and left out of every number.
"""

from __future__ import annotations

import collections
import csv
import json
import threading
import time
from pathlib import Path

from ..data import ROOT
from . import pipeline as P
from . import realistic as R
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
               "hold_s", "prob", "dev_dumped", "migrated", "gap", "age_s", "progress", "lat_buy_ms", "slip",
               "stake_sol"]
FAILED_COLS = ["rule", "mint", "signal_ms", "land_ms", "why", "pnl_sol"]
HOLD_MS = 120_000                                       # rows of a coin not known yet wait this long for its creation
HOLD_TABLES = ("trades", "amm", "other")
SKIP_KEEP = 5_000


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
    """Rows appended under the file's header; a file whose header lacks one of `cols` is rewritten once with them
    (the old columns kept after them, the old rows with the new ones empty)."""
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    if not new:
        with path.open(newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            old = list(reader.fieldnames or [])
            keep = list(reader) if old and any(c not in old for c in cols) else None
        if keep is not None:
            cols = cols + [c for c in old if c not in cols]
            tmp = path.with_suffix(".tmp")
            with tmp.open("w", newline="", encoding="utf-8") as fh:
                w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
                w.writeheader()
                w.writerows(keep)
            tmp.replace(path)
        elif old:
            cols = old
    with path.open("a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        if new:
            w.writeheader()
        for r in rows:
            w.writerow(r)


class Hold:
    """Rows of a coin the engine does not know yet (trades, pool trades, completion, migration) wait up to hold_ms
    for its creation and are fed after it in the order they came: the links race, and a coin made and migrated in
    one slot often has its migration first, which the engine drops for good. Older held rows are dropped (trades
    of coins made before the engine knew them, mostly); when a migration was among them, on_lost(mint) is told.
    The live service and the paper books both hold, so both decide on the same rows."""

    def __init__(self, engine, feed, on_lost=None, hold_ms: int = HOLD_MS, clock=time.monotonic):
        self.engine, self.feed, self.on_lost, self.hold_ms, self.clock = engine, feed, on_lost, hold_ms, clock
        self.held: dict[str, list] = {}                     # mint -> [(clock s, table, row)] in the order they came

    def row(self, table: str, row: dict) -> bool:
        """True when the row waits for its coin's creation (the caller feeds it otherwise)."""
        mint = row.get("mint")
        if table in HOLD_TABLES and mint and mint not in self.engine.tokens:
            self.held.setdefault(mint, []).append((self.clock(), table, row))
            return True
        return False

    def release(self, mints) -> None:
        """The held rows of these coins, in the order they came, once the engine knows the coin."""
        for m in mints:
            for _, table, row in self.held.pop(m, ()):
                self.feed(table, row)

    def purge(self) -> None:
        cut = self.clock() - self.hold_ms / 1000
        old = []
        for m, rows in self.held.items():                   # in the order their first row came
            if rows[0][0] >= cut:
                break
            old.append(m)
        for m in old:
            rows = self.held.pop(m)
            if self.on_lost is not None and any(t == "other" and r.get("kind") == "migrate" for _, t, r in rows):
                self.on_lost(m)


class Shadow:
    def __init__(self, pick: str, models: dict | None = None, book: CreatorBook | None = None,
                 alerts: bool = True, now_ms: int | None = None, wallets: W.WalletBook | None = None, cats=None,
                 strategies: list | None = None, kill=None, trends: bool = False, blocked=None, category=None,
                 realistic: bool = False, real: R.Model | None = None, paper_wallets: dict | None = None,
                 small=None, factory=None, ten=None):
        from .model import Filter
        self.pick = pick
        self.book = book or CreatorBook()
        rule = S.BY_NAME[pick]
        self.models = models or {}
        if small is None:                                     # R2's small-wallet books go with the full set
            small = R.SMALL if strategies is None else ()
        if ten is None:                                       # P3's 10 EUR books too
            ten = R.TEN if strategies is None else ()
        self.factory_on = factory is None and strategies is None    # F3: the factory's books with the full set
        if factory is None:
            factory = self._factory_specs() if self.factory_on else ()
        e1 = strategies is None
        strategies = P.STRATEGIES if strategies is None else strategies
        kill = kill or P.KillSwitch()
        now = now_ms or int(time.time() * 1000)
        # R1: the strategies' realistic books under their names, the old paper books as <name>_ideal until the date
        self.real = (real or R.Model()) if realistic else None
        self.paper_wallets = paper_wallets if paper_wallets is not None else {}
        old = ([R.ideal(s) for s in strategies] if now < R.IDEAL_UNTIL_MS else []) if realistic else strategies
        self.engine = Engine([rule, model_rule(rule)], book=self.book, decisions=False,
                             model=Filter(self.models) if self.models else None, on_close=self._closed,
                             strategies=old, wallets=wallets, cats=cats, models=self.models, kill=kill,
                             select=True, trend=True, social=True)
        if realistic:
            R.books(self.engine, strategies, self.real, self.paper_wallets, kill=kill)
            R.small_books(self.engine, self.real, self.paper_wallets, kill=kill, small=small)   # R2
            R.ten_books(self.engine, self.real, self.paper_wallets, kill=kill, ten=ten, now_ms=now)   # P3
            R.factory_books(self.engine, self.real, self.paper_wallets, kill=kill, specs=factory)   # F3
            if e1:                                            # E1: the bound grid's forward books, the full set only
                from .slippage_e1 import shadow_books
                shadow_books(self.engine, self.real, self.paper_wallets, kill=kill)
        self.kill, self.blocked, self.category, self.feed_down = kill, blocked, category, None
        for pipe in self.engine.pipes:
            pipe.on_close = self._closed
            pipe.blocked = pipe.blocked or blocked            # the owner's block list (blocklist.PAPER_RULES)
            pipe.category = category                          # the live bot's category rule (livecat.CategoryGate)
            pipe.on_skip = self._skipped
        self.hold = Hold(self.engine, self._feed, on_lost=self._lost)
        self.skips: list[dict] = []                           # the twin's coins not bought, for skipped.jsonl
        self.skip_seen: collections.OrderedDict = collections.OrderedDict()
        self.live = None                                      # always None here: the live book is live_service.py's
        self.cats_mtime = 0.0
        self.closed: list[dict] = []
        self.failed_seen = 0
        self.alerts = alerts
        self.last_alert_ms = 0
        self.last_reload = time.monotonic()
        self.last_save = time.monotonic()
        self.model_mtime = self._model_mtime()
        self.totals: dict[str, dict] = {}
        self.started_ms = now
        self.realistic_since = now if realistic else None
        self.trends = None
        if trends:                                            # a view only: off in the tests that do not ask for it
            from .trends import Trends
            self.trends = Trends(self.engine, reports_dir() / "trends.json")

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
    def load(cls) -> "Shadow":
        from .blocklist import PAPER_RULES, BlockWatch
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
        from .livecat import CategoryGate
        cats = CategoryIndex.load(mints=False, max_age_days=BOOK_DAYS)
        rules = PAPER_RULES | {n for n, b in R.TEN if b in PAPER_RULES}   # P3's twin of the live rule too
        blocked = BlockWatch(rules=rules)
        try:
            st = json.loads((paper_dir() / "state.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            st = {}
        pw = {k: R.wallet_of(k, v) for k, v in (st.get("paper_wallets") or {}).items()}
        sh = cls(read_pick(), load(), book, wallets=wallets, cats=cats, trends=True, blocked=blocked,
                 category=CategoryGate(cats, block=blocked, rules=rules), realistic=True, paper_wallets=pw)
        sh.realistic_since = st.get("realistic_since") or sh.realistic_since
        try:                                                  # Y14: the social features know the days before
            from . import socialfeat as SO
            from . import store
            sh.engine.social = SO.warm(store.days()[-SO.WARM_DAYS:])
        except Exception as e:                                # noqa: BLE001 - a fresh tracker then
            print(f"shadow: social warm-up skipped ({type(e).__name__}: {e})", flush=True)
        sh.cats_mtime = cls._cats_mtime()
        try:                                                  # X14: the sniper book of the early features
            from .early import SniperBook
            sh.engine.early.snipers = SniperBook.from_json(
                json.loads((paper_dir() / "snipers.json").read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass
        try:
            lost = [dict(p, exit_why="restart", pnl_sol=None, ret=None) for p in st.get("open") or []]
            append_csv(paper_dir() / "ledger.csv", LEDGER_COLS, lost)
        except (OSError, ValueError):
            pass
        if st.get("pick") == sh.pick:
            sh.totals = st.get("totals") or {}
        if st and not st.get("realistic_since"):            # R1's first start: the totals so far were the old model's
            sh.totals = {(k + R.IDEAL if k in P.BY_NAME else k): v for k, v in sh.totals.items()}
        print(f"shadow: paper books {sh.pick} and {sh.pick}+model, and the pipeline strategies "
              + ", ".join(s.name for s in P.STRATEGIES) + " realistic (live latency, fills, failures, fees and "
              f"sizing on {R.START_SOL} SOL each)"
              + (", the small-wallet books " + ", ".join(x[0] for x in R.SMALL) if R.SMALL else "")
              + ", E1's bound books <rule>@e1_<pair>"
              + (", with the old books as <name>_ideal"
                                                       if any(p.name == "paper" for p in sh.engine.pipes) else "")
              + ("" if sh.models else " (no model yet: the model-filtered books skip every signal)"), flush=True)
        return sh

    # ------------------------------------------------------------ the stream
    def on_row(self, table: str, row: dict) -> None:
        if self.hold.row(table, row):
            return
        self._feed(table, row)
        if table == "creates" and row.get("mint") in self.hold.held:
            self.hold.release([row["mint"]])

    def _feed(self, table: str, row: dict) -> None:
        feed_row(self.engine, table, row)
        if self.trends is not None:                           # after the engine: it only reads what the row did
            try:
                self.trends.observe(table, row)
            except Exception as e:                            # noqa: BLE001 - the view never stops the books
                self.trends.errors += 1
                if self.trends.errors <= 5:
                    print(f"trends: row skipped ({type(e).__name__}: {e})", flush=True)

    def watch_feed(self, col) -> None:
        """The collector's link state: a "no pool state" while every PumpSwap link was down says so."""
        from .events import PUMP_AMM
        self.feed_down = lambda a, b: col.was_down(PUMP_AMM, a, b)
        for pipe in self.engine.pipes:
            pipe.feed_down = self.feed_down

    def _lost(self, mint: str) -> None:
        """A migration whose coin's creation never came: a skip of every migration strategy, as live."""
        for pipe in self.engine.pipes:
            for s in pipe.strats.values():
                if s.entry == "migration":
                    pipe.skip(s.name, mint, "creation not seen")

    def _skipped(self, name: str, mint: str, why: str) -> None:
        """A coin the paper twin of the live strategy did not buy: its first reason, once (save writes it)."""
        from .blocklist import PAPER_RULES
        if name not in PAPER_RULES or not mint or (name, mint) in self.skip_seen:
            return
        self.skip_seen[(name, mint)] = None
        if len(self.skip_seen) > SKIP_KEEP:
            self.skip_seen.popitem(last=False)
        self.skips.append({"t": int(time.time() * 1000), "mint": mint, "rule": name, "why": why})

    def tick(self, now_ms: int) -> None:
        self.hold.purge()
        self.engine.advance(now_ms)
        for pipe in self.engine.pipes:                        # the live executor's results, the kill switch
            pipe.poll(now_ms)
        if self.trends is not None:
            self.trends.tick(now_ms)
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
            self.totals = {k: v for k, v in self.totals.items() if k in P.BY_NAME or k.endswith(R.IDEAL)}
        if mt != self.model_mtime:
            self.model_mtime = mt
            self.models = load()
            self.engine.model = Filter(self.models) if self.models else None
            self.engine.models = self.models
        if self.real is not None:
            self.real.reload()                                # the day's fit and the live sizing settings
            old = [p for p in self.engine.pipes if p.name == "paper" and not p.pos and not p.waiting]
            if old and time.time() * 1000 >= R.IDEAL_UNTIL_MS:   # the _ideal twins go once their two weeks are over
                for p in old:
                    self.engine.pipes.remove(p)
                self.engine._index_rules()
                print("shadow: the _ideal paper books ended (realistic.IDEAL_UNTIL_MS)", flush=True)
        if self.real is not None and self.factory_on:
            self.factory_reload()
        ct = self._cats_mtime()
        if ct != self.cats_mtime:
            from .categorize import BOOK_DAYS, CategoryIndex
            self.cats_mtime = ct
            if getattr(self.engine.cats, "path", None) is not None:
                self.engine.cats.tail()                       # the live classifier appends every 30 s: the new lines
            else:
                self.engine.cats = CategoryIndex.load(mints=False, max_age_days=BOOK_DAYS)

    @staticmethod
    def _factory_specs() -> list:
        try:
            from .factory import active_specs
            return active_specs()
        except Exception as e:                                # noqa: BLE001 - the books run without them
            print(f"shadow: factory books not read ({type(e).__name__}: {e})", flush=True)
            return []

    def factory_reload(self) -> None:
        """F3: the factory's active books as books.json has them now: a new one starts on its own paper wallet, a
        retired one goes once it holds nothing and waits for nothing."""
        from .factory import PREFIX
        specs = self._factory_specs()
        want = {n for n, _ in specs}
        mine = {n: p for p in self.engine.pipes if p.name == "realistic" for n in p.strats if n.startswith(PREFIX)}
        new = [(n, x) for n, x in specs if n not in mine]
        gone = [p for n, p in mine.items() if n not in want and not p.pos and not p.waiting]
        for p in gone:
            self.engine.pipes.remove(p)
        if gone:
            self.engine._index_rules()
        for pipe in R.factory_books(self.engine, self.real, self.paper_wallets, kill=self.kill, specs=new):
            pipe.on_close = self._closed
            pipe.blocked = pipe.blocked or self.blocked
            pipe.category = self.category
            pipe.on_skip = self._skipped
            pipe.feed_down = self.feed_down
        if new or gone:
            print(f"shadow: factory books started {[n for n, _ in new]}, ended "
                  f"{[n for n, p in mine.items() if p in gone]}", flush=True)

    def _closed(self, rec: dict) -> None:
        self.closed.append(rec)
        tot = self.totals.setdefault(rec["rule"], {"n": 0, "wins": 0, "pnl_sol": 0.0, "ret_sum": 0.0})
        if not rec.get("gap"):
            tot["n"] += 1
            tot["wins"] += int(rec["ret"] > 0)
            tot["pnl_sol"] += rec["pnl_sol"]
            tot["ret_sum"] += rec["ret"]
        if self.alerts and rec["ret"] >= BIG_WIN and not rec.get("gap") and "@e1_" not in str(rec["rule"]) \
                and rec["exit_ms"] - self.last_alert_ms >= ALERT_GAP_MS:   # E1's bound books post no winners
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
        skips, self.skips = self.skips, []
        if skips:
            with (d / "skipped.jsonl").open("a", encoding="utf-8") as fh:
                fh.writelines(json.dumps(k) + "\n" for k in skips)
        if len(self.engine.failed) > 10_000:
            self.engine.failed = []
            self.failed_seen = 0
        keep = ("rule", "family", "mint", "name", "symbol", "created_ms", "signal_ms", "land_ms", "signal_price",
                "entry_price")
        opened = [p for p in self.engine.positions.values() if p["state"] == "open"]
        for pipe in self.engine.pipes:
            if pipe.name in ("paper", "realistic"):
                opened += [p for p in pipe.pos.values() if p["state"] == "open"]
        st = {"t": int(time.time() * 1000), "pick": self.pick, "started_ms": self.started_ms, "totals": self.totals,
              "open": [{k: p.get(k) for k in keep} for p in opened], "status": self.status(),
              "realistic_since": self.realistic_since,
              "paper_wallets": {k: w.to_json() for k, w in self.paper_wallets.items()}}
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
            tmp = d / "snipers.json.tmp"
            tmp.write_text(json.dumps(self.engine.early.snipers.to_json(), separators=(",", ":")), encoding="utf-8")
            tmp.replace(d / "snipers.json")


def winner_card(rec: dict, lang: str = "en"):
    from ..ops import i18n, notify
    from .card import WHY as why
    t = i18n.t
    name = rec.get("symbol") or rec.get("name") or rec["mint"][:8]
    return notify.Card(
        "🚀", t("prt_win_title", lang, name=str(name)[:20], ret=i18n.frac_pct(rec["ret"], 0, lang)),
        t("prt_win_summary", lang, rule=rec["rule"],
          stake=f"{i18n.num(rec.get('stake_sol') or S.STAKE_SOL, 2, lang)} SOL",
          got=f"{i18n.num(rec['proceeds_sol'], 3, lang)} SOL", secs=i18n.num(rec["hold_s"], 0, lang),
          why=t(why.get(rec.get("exit_why"), "prt_why_time"), lang)),
        [notify.Line(t("prt_caveat", lang))], footer=t("prt_footer", lang))


def post_winner(rec: dict) -> None:
    try:
        from ..ops import notify
        notify.send("trending", [winner_card(rec, notify.alert_lang())], now=rec["exit_ms"])
    except Exception as e:                                   # an alert never stops the collector
        print(f"shadow: alert not sent ({type(e).__name__}: {e})", flush=True)
