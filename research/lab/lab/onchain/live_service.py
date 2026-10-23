"""The stage-2 on-chain service: the one process that may swap real money in our own Solana wallet. Started by the owner.

    python -m lab.onchain.live_service             run until stopped (the container pythia-onchain-live)
    python -m lab.onchain.live_service --once      check the gate, write the status once, exit (never opens the
                                                   wallet file, never swaps: safe next to the running service)

Not a job; nothing starts it automatically (docs/ONCHAIN-STAGE2.md, the owner's steps). With
any gate shut it still runs, swaps nothing and keeps the app's status current (the reasons, the
wallet's public address and balances); after fixing it, restart the service. The wallet file is
opened once, by pumpfun_rt.live_exec.load_signer, only when every gate held at start; the gate is
checked again every minute and a shut gate stops every swap at once.

What it does while on:
  - the owner's converts from the app (reports/onchain_live/convert/): a request gets a proposal
    (a fresh quote within the caps: expected and minimum amount, cost, route), valid for 60 s;
    only the owner's confirm of exactly that proposal lets it swap, never below its minimum, and only
    once: the confirm is taken (live/onchain/taken/<id>) before anything is signed, so neither a
    restart nor a failed round sends it again
  - a book's targets, only for a book the ack names and the pre-registered proof passed
    (live_gate.book_problems), once per new signal: sales first, then buys
  - a meme rule's entries and exits (lab.onchain.meme_live, docs/ONCHAIN-MEME.md): a buy only for a rule
    the ack's [meme] section names, whose paper proof passed and whose coin passed the safety check within
    the last minute (live_gate.meme_problems), following the rule's paper book; its holding sold into SOL
    when the paper book closed the position
  - on the kill switch with on_kill=usdc in the ack: every coin but SOL sold into USDC
  - the ledger reconciled against the wallet every 30 s (live_exec.reconcile)

Every STATUS_S it writes, for the engine and the app (snake_case):
  reports/onchain_live/status.json   on or off and why, address, balances in USD, the day,
                                     the ack's and the hard limits, the coins, the books, the
                                     kill switch, the last simulation, the reconciliation
  reports/onchain_live/trades.json   the newest swaps from the ledger
  reports/onchain_live/values.json   the wallet's USD value and its coins' prices every 15 min
                                     (60 days), for the app's chart and the 24 h change
After every swap it reads the wallet's history from the chain again (lab.onchain.history), and in
the alpha mode every swap posts its card (lab.onchain.cards, Telegram and Discord).
It never sends money anywhere: the guard has no transfer (guard.py).
"""

from __future__ import annotations

import argparse
import json
import re
import signal
import sys
import time
from pathlib import Path

from ..pumpfun_rt import live_exec as PX
from . import guard as G
from . import live_exec as LX
from . import live_gate as LG
from . import mints as M
from . import swapapi as S
from .jupiter import QuoteError

STATUS_S = 30.0
GATE_S = 60.0
CONVERT_S = 2.0
BOOK_S = 60.0
REQUEST_MAX_MS = 600_000                 # a request nobody could propose for in 10 min expires
CONFIRM_GRACE_MS = 15_000                # a confirm written inside the 60 s is taken this long after
KEEP_MS = 7 * 86_400_000
ID = re.compile(r"^c[0-9]{13}-[0-9a-f]{4}$")
KILL_REASON = "the kill switch file is there"
VALUE_S = 900.0                          # a point of the value chart every 15 min
VALUE_KEEP_MS = 60 * 86_400_000


def convert_dir() -> Path:
    return LG.reports_dir() / "convert"


def taken_dir() -> Path:
    return LG.data_dir() / "taken"


def take(cid: str) -> bool:
    """Take a confirmed convert, once ever: False when it was taken before (the service stopped or a round failed
    while it was sent). Written in the trader's own folder, where the app cannot write; raises OSError when the
    mark cannot be written, and then nothing is signed."""
    d = taken_dir()
    d.mkdir(parents=True, exist_ok=True)
    try:
        with (d / cid).open("x", encoding="utf-8") as fh:
            fh.write(str(LX.now_ms()))
    except FileExistsError:
        return False
    return True


def _read(p: Path):
    return PX.read_json(p)


def _post(title: str, text: str) -> None:
    try:
        from ..ops import notify
        notify.send("trades", notify.text_card("trades", title, text), urgent=True)
    except Exception as e:                               # an alert never stops the trader
        print(f"onchain live: alert not sent ({type(e).__name__}: {e})", flush=True)


def values_path() -> Path:
    return LG.reports_dir() / "values.json"


def add_value(v: LX.View, total: float | None, now_ms: int) -> bool:
    """One point of the value chart (USD total, the prices of the coins held and SOL), at most every VALUE_S."""
    if total is None:
        return False
    d = _read(values_path())
    pts = [p for p in (d.get("points") if isinstance(d, dict) else None) or [] if isinstance(p, dict)]
    if pts and now_ms - int(pts[-1].get("t") or 0) < VALUE_S * 1000:
        return False
    prices = {c: v.prices.get(m.mint) for c, m in LG.CODES.items() if (c == "SOL" or v.held(c) > 0) and v.prices.get(m.mint)}
    pts = [p for p in pts if now_ms - int(p.get("t") or 0) <= VALUE_KEEP_MS] + \
        [{"t": now_ms, "usd": round(total, 4), "prices": prices}]
    PX.write_json(values_path(), {"points": pts})
    return True


def ui(code: str, raw) -> float | None:
    try:
        return int(raw) / 10 ** LG.CODES[code].decimals
    except (KeyError, TypeError, ValueError):
        return None


def trades_view(limit: int = 100) -> list[dict]:
    out = []
    for r in reversed(LX.read_ledger()):
        src, dst = r.get("from") or "", r.get("to") or ""
        fee = LX._f(r.get("fee_l"))
        out.append({"t": LX._i(r.get("t")), "kind": r.get("kind"), "book": r.get("book") or None, "from": src, "to": dst,
                    "in_amount": ui(src, r.get("in_raw")) if src in LG.CODES else None,
                    "out_amount": ui(dst, r.get("out_raw")) if dst in LG.CODES and r.get("status") == "filled" else None,
                    "in_usd": LX._f(r.get("in_usd")), "out_usd": LX._f(r.get("out_usd")),
                    "fee_sol": fee / 1e9 if fee is not None else None, "sig": r.get("sig") or None,
                    "status": r.get("status"), "why": r.get("why") or None})
        if len(out) >= limit:
            break
    return out


class Service:
    def __init__(self, gate: LG.Gate | None = None, load=PX.load_signer, rpc=None, trader: LX.Trader | None = None,
                 alerts: bool = True, clock=time.time):
        self.gate = gate or LG.Gate()
        self.load, self.rpc, self.trader, self.alerts, self.clock = load, rpc, trader, alerts, clock
        self.why: list[str] = []
        self.on = False
        self.view: LX.View | None = None
        self.view_err: str | None = None
        self.books: list[dict] = []
        self.memes: list[dict] = []
        self.meme_trader = None
        self.last = {"status": -1e18, "gate": -1e18, "convert": -1e18, "book": -1e18}
        self.stopped = False

    # ------------------------------------------------ start and gate

    def start(self, arm: bool = True) -> None:
        """`arm` False (--once): the gate is checked and the status written, the wallet file is never opened."""
        self.why = self.gate.check()
        signer = None
        if not arm:
            self.why.append("a check only (--once): the wallet file is not opened, nothing swaps")
        if not self.why:
            try:
                signer = self.load(self.gate.env[LG.ENV_KEYPAIR])
                if signer.pubkey != self.gate.address:
                    self.why = ["the wallet file and its .pub do not belong together"]
                    signer = None
            except Exception as e:                       # an unreadable wallet file: nothing swaps
                self.why = [f"the wallet file could not be read ({type(e).__name__})"]
                signer = None
        if self.trader is None:
            try:
                self.trader = LX.setup(self.gate, signer, self.rpc, on_wait=self.on_wait)
            except Exception as e:
                self.why.append(f"no RPC ({type(e).__name__}: {e})"[:200])
        elif signer is not None:
            self.trader.signer, self.trader.wallet = signer, signer.pubkey
        self.on = signer is not None and self.trader is not None and not self.why
        if self.on:
            got = LX.recover()                          # swaps sent before a stop, never booked: read back, never resent
            if got:
                print(f"onchain live: {len(got)} swap(s) sent before the stop are read back from the chain", flush=True)
            self.refresh_view()
            if self.view is not None:
                LX.baseline(self.view)                  # every start: what the wallet holds now is the base
                self.trader.reconciled = {"t": self.view.t, "ok": True, "diffs": []}
            mode = self.gate.ack.mode
            print(f"onchain live: ON ({mode}) for {self.gate.address}", flush=True)
            if self.alerts:
                _post("On-chain wallet: live" + (" (Alpha phase)" if mode == "alpha" else ""),
                      f"The on-chain trader is on ({mode} mode) for {self.gate.address}.")
        else:
            print("onchain live: nothing swaps. Why:\n  - " + "\n  - ".join(self.why or ["see above"])
                  + "\nFix it and restart the service.", flush=True)
            if self.trader is not None and self.gate.address and self.view is None:
                self.refresh_view()

    def gate_why(self, keep_kill: bool = True) -> list[str]:
        why = self.gate.check()
        return why if keep_kill else [w for w in why if w != KILL_REASON]

    def recheck(self) -> None:
        self.why = self.gate.check()
        if self.on and [w for w in self.why if w != KILL_REASON]:
            self.on = False
            print("onchain live: the gate shut; nothing swaps until a restart:\n  - " + "\n  - ".join(self.why),
                  flush=True)
            if self.alerts:
                _post("On-chain wallet: stopped", "The gate shut: " + "; ".join(self.why)[:600])

    def on_wait(self) -> None:
        """Called while a swap waits for its landing: the status stays fresh."""
        if self.clock() - self.last["status"] >= STATUS_S:
            self.write_status()

    # ------------------------------------------------ the wallet

    def refresh_view(self) -> None:
        if self.trader is None or not (self.trader.wallet or self.gate.address):
            return
        try:
            from . import meme_live as ML
            self.view = LX.read_view(self.trader.chain, self.trader.wallet or self.gate.address, self.trader.prices_of,
                                     memes=ML.known_mints())
            self.view_err = None
        except Exception as e:
            self.view_err = f"{type(e).__name__}: {e}"[:200]

    def reconcile(self) -> None:
        if not self.on or self.view is None:
            return
        try:
            self.trader.reread()
            r = LX.reconcile(self.view)
        except Exception as e:
            print(f"onchain live: reconcile failed ({type(e).__name__}: {e})"[:220], flush=True)
            return
        was = (self.trader.reconciled or {}).get("ok", True)
        self.trader.reconciled = r
        if was and not r.get("ok") and self.alerts:
            _post("On-chain wallet: ledger differs", "No buys until explained: " + "; ".join(r.get("diffs") or [])[:600])

    def status(self) -> dict:
        v, ack = self.view, self.gate.ack
        bal, total, day = [], None, {"start_usd": None, "pnl_usd": None, "swaps": 0, "converts": 0, "convert_usd": 0.0}
        if v is not None:
            for code, m in LG.CODES.items():
                raw = v.held(code)
                if raw <= 0:
                    continue
                bal.append({"coin": code, "symbol": m.symbol, "mint": m.mint, "amount": raw / 10 ** m.decimals,
                            "usd": v.usd(code), "price_usd": v.prices.get(m.mint)})
            total = v.total_usd()
            r = LX.realised(LX.day_of(v.t))
            start = LX.day_start_usd(v, total)
            day = {"start_usd": start, "pnl_usd": None if start is None or total is None else
                   total - start - LX.deposits_usd(LX.day_of(v.t)), "swaps": r["swaps"], "converts": r["converts"],
                   "convert_usd": r["convert_usd"]}
        lim = None
        if ack.mode:
            lim = {"max_total_usd": ack.cap("total"), "max_trade_usd": ack.cap("trade"),
                   "max_daily_loss_usd": ack.cap("daily_loss"), "max_convert_usd": ack.cap("convert"),
                   "meme_max_total_usd": ack.meme_cap("total"), "meme_max_trade_usd": ack.meme_cap("trade"),
                   "meme_max_daily_loss_usd": ack.meme_cap("daily_loss")}
        loss = -(day["pnl_usd"]) if day["pnl_usd"] is not None else None
        sim = _read(LG.simulate_path())
        rec = self.trader.reconciled if self.trader is not None else None
        why = list(self.why) + ([f"the wallet could not be read: {self.view_err}"] if self.view_err else [])
        return {"t": LX.now_ms(), "running": True, "on": self.on and not LG.killed(), "mode": ack.mode, "gate": why,
                "address": (self.trader.wallet if self.trader is not None else None) or self.gate.address,
                "sol_lamports": v.sol_l if v is not None else None, "balances": bal, "total_usd": total, "day": day,
                "ack": ack.view(), "hard": LG.hard_view(ack.mode), "limits": lim,
                "coins": [{"coin": c, "symbol": m.symbol, "mint": m.mint, "decimals": m.decimals,
                           "allowed": c in ack.mints} for c, m in LG.CODES.items()],
                "kill": LG.killed(), "simulate": {"t": sim.get("t"), "ok": sim.get("ok")} if isinstance(sim, dict) else None,
                "books": self.books, "memes": self.memes, "reconcile": rec,
                "stops": {"daily": bool(lim and loss is not None and loss >= lim["max_daily_loss_usd"]),
                          "total": bool(lim and total is not None and total > lim["max_total_usd"])},
                "frozen": list(v.frozen) if v is not None else []}

    def write_status(self) -> None:
        self.last["status"] = self.clock()
        try:
            st = self.status()
            PX.write_json(LG.reports_dir() / "status.json", st)
            PX.write_json(LG.reports_dir() / "trades.json", {"trades": trades_view()})
            if self.view is not None:
                add_value(self.view, st.get("total_usd"), st["t"])
        except OSError as e:
            print(f"onchain live: status not written ({e})", flush=True)

    # ------------------------------------------------ converts

    def _result(self, cid: str, status: str, why: str | None = None, **kw) -> None:
        PX.write_json(convert_dir() / f"{cid}.result.json", {"id": cid, "status": status, "why": why,
                                                             "sig": kw.get("sig"), "out_amount": kw.get("out_amount"),
                                                             "t": LX.now_ms()})

    def propose(self, cid: str, req: dict) -> None:
        d = convert_dir()
        src, dst = str(req.get("from") or ""), str(req.get("to") or "")
        try:
            amount = float(req.get("amount"))
        except (TypeError, ValueError):
            amount = 0.0
        prop = {"id": cid, "from": src, "to": dst, "amount": amount, "t": LX.now_ms(), "status": "refused", "why": None}
        try:
            if not self.on or self.trader is None or self.trader.signer is None:
                raise G.Refused("the trader is off: " + ("; ".join(self.why) or "not armed"))
            if src not in LG.CODES or dst not in LG.CODES or src == dst or not amount > 0:
                raise G.Refused("not a convert between two coins of the list")
            self.refresh_view()
            v = self.view
            if v is None:
                raise G.Refused("the wallet could not be read")
            s = LX.Swap("convert", src, dst, M.raw(LG.CODES[src], amount), ref=cid)
            why = self.trader.caps(s, v)
            if why:
                raise G.Refused(why)
            slip = LG.slippage(src, dst)
            b = S.build(self.trader.jup, LG.CODES[src].mint, LG.CODES[dst].mint, s.in_raw, self.trader.wallet, slip)
            bad = [m for m in b.route_mints if m not in G.ROUTE_MINTS]
            if bad:
                raise G.Refused(f"the route passes through a mint not on the route list ({bad[0][:6]})")
            in_usd, _, cost = self.trader._prices_ok(s, v, b)
            mo = G.min_out(b.out_amount, slip)
            price = min(b.cu_price or LX.DEFAULT_CU_PRICE, G.MAX_PRIORITY_L * 1_000_000 // G.MAX_UNITS)
            fee_max = G.BASE_FEE_L + price * G.MAX_UNITS // 1_000_000 + (self.trader.tip_l or 0)
            prop.update(in_raw=str(s.in_raw), expected_out=ui(dst, b.out_amount), min_out=ui(dst, mo),
                        min_out_raw=str(mo), cost_bps=round(cost, 2), in_usd=round(in_usd, 2), route=b.labels,
                        price_impact_pct=round(b.price_impact_pct, 4), fee_sol=fee_max / 1e9, slippage_bps=slip,
                        expires_ms=prop["t"] + LG.CONFIRM_S * 1000, status="proposed")
        except (G.Refused, QuoteError, RuntimeError, ValueError, OSError) as e:
            prop["why"] = str(e)[:300]
        PX.write_json(d / f"{cid}.proposal.json", prop)
        LX.log_order({"what": "proposed" if prop["status"] == "proposed" else "refused", "ref": cid,
                      "from": src, "to": dst, "why": prop["why"], "min_out_raw": prop.get("min_out_raw")})
        if prop["status"] == "refused":
            self._result(cid, "refused", prop["why"])

    def _taken_before(self, cid: str) -> None:
        sig = next((o.get("sig") for o in reversed(LX._read_jsonl(LX.orders_path()))
                    if o.get("what") == "sent" and o.get("ref") == cid), None)
        self._result(cid, "failed", "taken before, and the service stopped while it was sent: not sent again; "
                     "the ledger check reads what the chain did", sig=sig)

    def confirmed(self, cid: str, prop: dict, conf: dict) -> None:
        now = LX.now_ms()
        if conf.get("id") != cid or conf.get("proposal_t") != prop.get("t") or \
                str(conf.get("min_out_raw")) != str(prop.get("min_out_raw")):
            self._result(cid, "refused", "the confirm does not belong to this proposal")
            return
        if (taken_dir() / cid).exists():
            self._taken_before(cid)
            return
        exp = int(prop.get("expires_ms") or 0)
        if int(conf.get("t") or 0) > exp or now > exp + CONFIRM_GRACE_MS:
            self._result(cid, "expired", "confirmed too late; ask for a new quote")
            return
        if not self.on or self.trader is None:
            self._result(cid, "refused", "the trader is off")
            return
        try:
            fresh = take(cid)
        except OSError as e:
            self._result(cid, "failed", f"the confirm could not be marked as taken ({e}); nothing was signed")
            return
        if not fresh:
            self._taken_before(cid)
            return
        self.refresh_view()
        if self.view is None:
            self._result(cid, "failed", "the wallet could not be read")
            return
        s = LX.Swap("convert", prop["from"], prop["to"], int(prop["in_raw"]), ref=cid, min_out_raw=int(prop["min_out_raw"]),
                    signal_ms=int(conf.get("t") or 0) or None)
        r = self.trader.execute(s, self.view, gate_why=lambda: self.gate_why(keep_kill=False))
        self._result(cid, r["status"], r.get("why"), sig=r.get("sig"), out_amount=ui(s.dst, r.get("out_raw")))
        self._after(r, s)

    def converts(self) -> None:
        d = convert_dir()
        if not d.is_dir():
            return
        now = LX.now_ms()
        for p in sorted(d.glob("*.request.json")):
            cid = p.name[:-len(".request.json")]
            if not ID.match(cid):
                continue
            if (d / f"{cid}.result.json").exists():
                if now - int(p.stat().st_mtime * 1000) > KEEP_MS:
                    for part in ("request", "proposal", "confirm", "result"):
                        (d / f"{cid}.{part}.json").unlink(missing_ok=True)
                    (taken_dir() / cid).unlink(missing_ok=True)
                continue
            req = _read(p)
            if not isinstance(req, dict) or req.get("id") != cid:
                self._result(cid, "refused", "an unreadable request")
                continue
            prop = _read(d / f"{cid}.proposal.json")
            if prop is None:
                if now - int(req.get("t") or 0) > REQUEST_MAX_MS:
                    self._result(cid, "expired", "no proposal in time")
                else:
                    self.propose(cid, req)
                continue
            conf = _read(d / f"{cid}.confirm.json")
            if isinstance(conf, dict):
                self.confirmed(cid, prop, conf)
            elif now > int(prop.get("expires_ms") or 0) + CONFIRM_GRACE_MS:
                self._result(cid, "expired", "not confirmed within 60 s")

    # ------------------------------------------------ books and the kill switch

    def _after(self, r: dict, s: LX.Swap) -> None:
        self.refresh_view()
        if r["status"] in ("filled", "failed"):
            self.read_history()
        if r["status"] in ("filled", "failed") and self.alerts and self.gate.ack.mode == "alpha":
            from . import cards
            cards.post_alpha(s, r, self.view)
        elif r["status"] in ("filled", "failed") and self.alerts:
            _post(f"On-chain wallet: {s.src} to {s.dst} {r['status']}",
                  f"{s.kind}{' ' + s.book if s.book else ''}: {ui(s.src, s.in_raw)} {s.src}"
                  + (f" for {ui(s.dst, r.get('out_raw'))} {s.dst}" if r.get("out_raw") else "")
                  + (f". {r['why']}" if r.get("why") else ""))

    def read_history(self) -> None:
        """The wallet's history from the chain again, so a swap shows in the app at once. Never raises."""
        addr = (self.trader.wallet if self.trader is not None else None) or self.gate.address
        if self.trader is None or not addr:
            return
        try:
            from . import history as H
            H.update(self.trader.chain.rpc, addr)
        except Exception as e:                           # the history job reads it again within minutes
            print(f"onchain live: history not read ({type(e).__name__}: {e})"[:200], flush=True)

    def run_books(self) -> None:
        from ..data import ROOT
        from . import book as B
        ack = self.gate.ack
        state = _read(LG.data_dir() / "books.json")
        state = state if isinstance(state, dict) else {}
        proof = _read(LG.proof_path())
        now = LX.now_ms()
        out = []
        for name in ack.books:
            why = LG.book_problems(name, ack, proof, now)
            sig, sig_why = B.read_signal(ROOT, now, B.SIGNAL) if not why else (None, "")
            if not why and sig is None:
                why = [f"no fresh signal ({sig_why})"]
            out.append({"book": name, "allowed": not why, "why": "; ".join(why) or None})
            if why or not self.on or self.view is None or LG.killed():
                continue
            sid = str(sig.get("as_of_ms") or sig.get("valid_until_ms") or "")
            if state.get(name) == sid:
                continue
            try:
                signal_ms = int((ROOT / "signals" / B.SIGNAL / "latest.json").stat().st_mtime * 1000)
            except OSError:
                signal_ms = now
            state[name] = sid                            # once per signal, whatever happens to its swaps
            PX.write_json(LG.data_dir() / "books.json", state)
            for s in LX.book_swaps(name, ack, self.view, sig.get("weights") or {}):
                s.signal_ms = signal_ms
                r = self.trader.execute(s, self.view, gate_why=self.gate_why)
                self._after(r, s)
        self.books = out

    def run_memes(self) -> None:
        """The meme rules the ack's [meme] section names, following their paper books (lab.onchain.meme): a new
        paper entry (under meme_live.SIGNAL_MAX_MS old, once) is bought only when live_gate.meme_problems is empty;
        a live holding whose paper position closed is sold into SOL. Nothing under the kill switch."""
        from ..data import ROOT
        from . import meme as ME
        from . import meme_live as ML
        from . import meme_safety as MS
        ack = self.gate.ack
        out = []
        if not ack.meme_rules:
            self.memes = out
            return
        proof = _read(LG.meme_proof_path())
        now = LX.now_ms()
        killed = LG.killed()
        state = _read(LG.data_dir() / "memes.json")
        state = state if isinstance(state, dict) else {}
        done = state.setdefault("done", {})
        mt = None
        if self.on and self.trader is not None and self.view is not None and not killed:
            if self.meme_trader is None:
                from ..ops import trending as TR
                from .jupiter import Jupiter
                src = MS.Sources(self.trader.chain.rpc, Jupiter(), TR.http_json)
                self.meme_trader = ML.MemeTrader.from_trader(self.trader, check=lambda m: MS.check(m, src).record())
            mt = self.meme_trader
            mt.signer, mt.wallet, mt.reconciled = self.trader.signer, self.trader.wallet, self.trader.reconciled
        for rule in ack.meme_rules:
            why = LG.meme_rule_problems(rule, ack, proof, now, killed)
            paper = ME.load_state(rule, ROOT, now) if rule in ME.RULES else {"positions": {}}
            opens = paper.get("positions") or {}
            out.append({"rule": rule, "allowed": not why, "why": "; ".join(why) or None, "paper_open": len(opens)})
            if mt is None:
                continue
            for mint, pos in ML.positions(rule).items():
                if pos["raw"] <= 0 or any(p.get("mint") == mint for p in opens.values()):
                    continue
                for s in mt.sales(rule, mint, pos["raw"], self.view):
                    self._after_meme(mt.execute(s, self.view, gate_why=self.gate_why), s)
            if why:
                continue
            for pid, p in opens.items():
                if pid in done or not 0 <= now - int(p.get("opened_ms") or 0) <= ML.SIGNAL_MAX_MS:
                    continue
                done[pid] = now                          # once per paper entry, whatever happens to its swap
                state["done"] = {k: t for k, t in done.items() if now - int(t) < 7 * 86_400_000}
                PX.write_json(LG.data_dir() / "memes.json", state)
                s, r = mt.buy(rule, p["mint"], self.view, proof, gate_why=self.gate_why,
                              signal_ms=int(p.get("opened_ms") or now))
                if s is not None:
                    self._after_meme(r, s)
                elif r.get("why"):
                    print(f"onchain live: meme {rule} {p['mint'][:8]} refused: {r['why']}"[:300], flush=True)
        self.memes = out

    def _after_meme(self, r: dict, s: LX.Swap) -> None:
        self.refresh_view()
        if r["status"] in ("filled", "failed"):
            self.read_history()
            if self.alerts:
                _post(f"On-chain wallet: meme {s.book} {r['status']}",
                      f"{s.src} to {s.dst}" + (f" ({r['in_usd']:.2f} USD)" if r.get("in_usd") else "")
                      + (f". {r['why']}" if r.get("why") else ""))

    def liquidate(self) -> None:
        """Under the kill switch with on_kill=usdc: every coin but SOL and USDC into USDC, a swap at a time."""
        if not (self.on and LG.killed() and self.gate.ack.on_kill == "usdc" and self.view is not None):
            return
        for code in self.gate.ack.mints:
            if code in ("SOL", "USDC") or self.view.held(code) <= 0:
                continue
            lim = self.gate.ack.cap("trade")
            usd = self.view.usd(code)
            raw = self.view.held(code)
            if usd and usd > lim:
                raw = int(raw * lim / usd * 0.98)
            s = LX.Swap("kill", code, "USDC", raw, signal_ms=LX.now_ms())
            r = self.trader.execute(s, self.view, gate_why=lambda: self.gate_why(keep_kill=False))
            self._after(r, s)
            return

    # ------------------------------------------------ the loop

    def step(self) -> None:
        now = self.clock()
        if now - self.last["gate"] >= GATE_S:
            self.last["gate"] = now
            self.recheck()
        if now - self.last["status"] >= STATUS_S:
            self.refresh_view()
            self.reconcile()
            self.write_status()
        if now - self.last["convert"] >= CONVERT_S:
            self.last["convert"] = now
            self.converts()
        if now - self.last["book"] >= BOOK_S:
            self.last["book"] = now
            self.run_books()
            self.run_memes()
            self.liquidate()

    def run(self) -> None:
        signal.signal(signal.SIGTERM, lambda *_: setattr(self, "stopped", True))
        while not self.stopped:
            try:
                self.step()
            except Exception as e:                       # one bad round never ends the service
                print(f"onchain live: round failed ({type(e).__name__}: {e})"[:300], flush=True)
            time.sleep(1.0)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="the stage-2 on-chain service (locked until the owner arms it)")
    ap.add_argument("--once", action="store_true", help="check the gate, write the status once, exit")
    a = ap.parse_args(argv)
    svc = Service()
    svc.start(arm=not a.once)
    svc.run_books()                                      # off (--once): only why each book may or may not trade
    svc.run_memes()
    svc.write_status()
    if a.once:
        print(json.dumps({"on": svc.on, "gate": svc.why}, indent=1))
        return 0
    svc.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
