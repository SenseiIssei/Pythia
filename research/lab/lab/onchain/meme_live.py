"""The meme rules' live path in our own wallet: SOL into a memecoin and back through Jupiter. LOCKED.

docs/ONCHAIN-MEME.md. MemeTrader is the stage-2 Trader (live_exec.py) with its own caps, build and
price check for meme swaps; everything else is the Trader's own: the gate is asked before every attempt,
the kill switch right before every signature, /swap/v2/build for our wallet, the guard over the complete
message (one signer, only our own token accounts, no transfer out, no approve, no platform fee), every
writable account read from the chain (no Token-2022), the simulation with the account diff, sign, send,
land, read back, ledger, reconciliation. The base Trader refuses a meme swap outright (it is not a swap
between two coins of the list); only this class builds one.

A BUY (SOL into the coin, `buy`) needs, on top of every gate of live_gate.Gate:
  - the ack's [meme] section naming the rule, valid, its maxima at most live_gate.MEME_MAX_* (50 USD of
    meme coins in all, 10 USD a swap, 10 USD of meme losses a day)
  - the rule's pre-registered paper proof passed (reports/onchain_meme/proof.json, lab.onchain.meme --proof)
  - the mint's safety check (meme_safety) passed within the last minute, asked again before every attempt;
    that verdict is the meme allowlist: the guard's plan allows SOL and exactly that mint, the route may pass
    only the stage-2 route mints and that mint
  - SOL's Jupiter price within 2 % of Kraken's mid, the coin's Jupiter price within 5 % of its best pool's,
    the swap's cost at most MEME_MAX_COST_BPS and its minimum out holding at those prices
  - the meme caps below, the wallet's SOL reserve and a ledger that matches the chain
A SALE (the coin back into SOL) of a rule's holding needs the ack's [meme] section naming the rule and
everything the Trader enforces (a classic SPL mint, the guard, the simulation, at most the swap cap per
swap, a cost at most MEME_MAX_SELL_COST_BPS); not a fresh safety verdict, so a coin whose pool is draining
can still be sold. Under the kill switch nothing swaps (meme coins are held; the owner sells by hand).

Meme rows go into the same ledger as kind "meme", the coin as meme:<mint>; their decimals into
live/onchain/meme_mints.json, so the view, the reconciliation and the caps value them.
"""

from __future__ import annotations

import math

from ..pumpfun_rt import live_exec as PX
from ..pumpfun_rt import txbuild as X
from ..pumpfun_rt.events import WSOL
from . import guard as G
from . import live_exec as LX
from . import live_gate as LG
from . import mints as M
from . import swapapi as S

SIGNAL_MAX_MS = 5 * 60_000               # a paper entry older than this is not followed
SOL = "SOL"


def mints_path():
    return LG.data_dir() / "meme_mints.json"


def known_mints() -> dict[str, int]:
    """The meme mints this wallet ever bought, with their decimals (for the view and the caps)."""
    d = PX.read_json(mints_path())
    return {k: int(v) for k, v in d.items() if isinstance(v, int)} if isinstance(d, dict) else {}


def remember(mint: str, decimals: int) -> None:
    d = known_mints()
    if d.get(mint) != decimals:
        d[mint] = int(decimals)
        PX.write_json(mints_path(), d)


def meme_mint(s: LX.Swap) -> str | None:
    """The coin of a meme swap: exactly one side meme:<mint>, the other SOL."""
    for a, b in ((s.src, s.dst), (s.dst, s.src)):
        if a.startswith(LG.MEME_PREFIX) and b == SOL:
            return LG.mint_of(a)
    return None


def positions(rule: str | None = None, day: int | None = None) -> dict:
    """Per meme mint, from the filled ledger rows (of one rule, or all): raw units held, their cost in USD, and the
    day's realised P&L in USD (sales at their USD value less the cost they take out)."""
    out: dict[str, dict] = {}
    for r in LX.read_ledger():
        if r.get("kind") != "meme" or r.get("status") != "filled" or (rule and r.get("book") != rule):
            continue
        frm, to = r.get("from") or "", r.get("to") or ""
        if to.startswith(LG.MEME_PREFIX):
            p = out.setdefault(LG.mint_of(to), {"raw": 0, "cost_usd": 0.0, "day_pnl_usd": 0.0})
            p["raw"] += LX._i(r.get("out_raw"))
            p["cost_usd"] += LX._f(r.get("in_usd")) or 0.0
        elif frm.startswith(LG.MEME_PREFIX):
            p = out.setdefault(LG.mint_of(frm), {"raw": 0, "cost_usd": 0.0, "day_pnl_usd": 0.0})
            sold = min(LX._i(r.get("in_raw")), p["raw"])
            basis = p["cost_usd"] * sold / p["raw"] if p["raw"] > 0 else 0.0
            p["raw"] -= sold
            p["cost_usd"] -= basis
            if day is not None and LX.day_of(LX._i(r.get("t"))) == day:
                p["day_pnl_usd"] += (LX._f(r.get("out_usd")) or 0.0) - basis
    return out


def meme_value(v: LX.View, mints: dict[str, int]) -> float | None:
    """What the wallet's meme coins are worth at Jupiter's prices (None: one has no price)."""
    tot = 0.0
    for mint, dec in mints.items():
        raw = v.tokens.get(mint, 0)
        if raw <= 0:
            continue
        p = v.prices.get(mint)
        if not p:
            return None
        tot += raw / 10 ** dec * p
    return tot


def day_loss(v: LX.View, mints: dict[str, int]) -> float | None:
    """The day's meme loss in USD: realised losses of the day's sales plus every open meme position below its
    cost (a gain offsets; None when a price is missing)."""
    pnl = 0.0
    for mint, p in positions(day=LX.day_of(v.t)).items():
        pnl += p["day_pnl_usd"]
        if p["raw"] > 0:
            px = v.prices.get(mint)
            dec = mints.get(mint)
            if not px or dec is None:
                return None
            pnl += min(p["raw"], v.tokens.get(mint, 0)) / 10 ** dec * px - p["cost_usd"]
    return -pnl


class MemeTrader(LX.Trader):
    """`check(mint) -> verdict record` runs the safety check now (meme_safety.check(...).record())."""

    def __init__(self, *a, check=None, **kw):
        super().__init__(*a, **kw)
        self.check = check
        self.decimals: dict[str, int] = known_mints()

    @classmethod
    def from_trader(cls, tr: LX.Trader, check=None) -> "MemeTrader":
        m = cls(tr.gate, tr.chain, tr.jup, signer=tr.signer, sender=tr.sender, tip_l=tr.tip_l, prices=tr.prices_of,
                kraken=tr.kraken, clock=tr.clock, sleep=tr.sleep, on_wait=tr.on_wait, check=check)
        m.wallet, m.reconciled = tr.wallet, tr.reconciled
        return m

    # ------------------------------------------------ caps

    def caps(self, s: LX.Swap, v: LX.View, killed: bool | None = None) -> str | None:
        ack = self.gate.ack
        if ack.mode not in LG.MODES:
            return "no valid confirmation file"
        mint = meme_mint(s)
        if s.kind != "meme" or mint is None:
            return "not a meme swap (SOL against one meme coin)"
        if ack.meme_problems:
            return ack.meme_problems[0]
        if s.book not in ack.meme_rules:
            return f"the confirmation file's [meme] section does not name {s.book}"
        dec = self.decimals.get(mint)
        if dec is None:
            return "the coin's decimals are not known (no safety check yet)"
        if s.in_raw <= 0:
            return "nothing to swap"
        buying = s.src == SOL
        if (v.sol_l if buying else v.tokens.get(mint, 0)) < s.in_raw:
            return "the wallet holds less than the swap needs"
        if mint in v.frozen:
            return "a token account of this coin is frozen"
        price = v.prices.get(M.SOL.mint) if buying else v.prices.get(mint)
        if not price:
            return "no USD price for the swap's input"
        in_usd = s.in_raw / (1e9 if buying else 10 ** dec) * price
        if in_usd > ack.meme_cap("trade") + 1e-9:
            return f"{in_usd:.2f} USD is above the {ack.meme_cap('trade'):g} USD a meme swap"
        why = self.kill_why(s, killed)
        if why:
            return why
        mints = {**self.decimals, **v.memes}
        if buying:
            held = meme_value(v, mints)
            if held is None:
                return "a meme coin of the wallet has no price"
            if held + in_usd > ack.meme_cap("total") + 1e-9:
                return f"meme coins would pass max_total_usd of the [meme] section ({held:.2f} USD held)"
            loss = day_loss(v, mints)
            if loss is None or loss >= ack.meme_cap("daily_loss"):
                return "the day's meme loss reached max_daily_loss_usd (or is not known): no meme buys until tomorrow"
            if self.reconciled is not None and not self.reconciled.get("ok"):
                return "the ledger does not match the chain: no buys until it is explained"
            total = v.total_usd()
            if total is None:
                return "the wallet's USD value is not known (a price is missing)"
            if total > ack.cap("total"):
                return f"the wallet is worth {total:.2f} USD, above max_total_usd: no buys"
        if LX.realised(LX.day_of(v.t))["meme_swaps"] >= LG.MEME_MAX_SWAPS_DAY:
            return f"already {LG.MEME_MAX_SWAPS_DAY} meme swaps today"
        reserve = LG.RESERVE_L + G.MAX_PRIORITY_L + G.BASE_FEE_L + X.HELIUS_MAX_TIP_LAMPORTS + 2 * G.ATA_RENT_L
        if v.sol_l - (s.in_raw if buying else 0) < reserve:
            return "the swap would leave less than the SOL reserve for fees"
        return None

    # ------------------------------------------------ build, guard, simulate

    def _meme_prices_ok(self, s: LX.Swap, v: LX.View, b: S.Build, mint: str) -> tuple[float, float, float]:
        dec = self.decimals[mint]
        psol, pm = v.prices.get(M.SOL.mint), v.prices.get(mint)
        if not psol or not pm:
            raise G.Refused("no Jupiter price for one side")
        k = self.kraken(SOL)
        if k is None or not k > 0:
            raise G.Refused("no Kraken price for SOL to check Jupiter's against")
        if abs(psol / k - 1) * 100 > LG.MAX_PRICE_GAP_PCT:
            raise G.Refused(f"Jupiter's SOL price is more than {LG.MAX_PRICE_GAP_PCT:g} % from Kraken's")
        buying = s.src == SOL
        if buying:
            ref = (((self.verdict or {}).get("facts") or {}).get("pool") or {}).get("price_usd")
            if not ref or abs(pm / ref - 1) * 100 > LG.MEME_MAX_PRICE_GAP_PCT:
                raise G.Refused(f"Jupiter's price of the coin is more than {LG.MEME_MAX_PRICE_GAP_PCT:g} % from its "
                                "best pool's (or the pool has none)")
        limit = LG.MEME_MAX_COST_BPS if buying else LG.MEME_MAX_SELL_COST_BPS
        p_in, d_in, p_out, d_out = (k, 9, pm, dec) if buying else (pm, dec, k, 9)
        in_usd = b.in_amount / 10 ** d_in * p_in
        out_usd = b.out_amount / 10 ** d_out * p_out
        fair = in_usd / p_out * 10 ** d_out
        if G.min_out(b.out_amount, LG.MEME_SLIPPAGE_BPS) < fair * (1e4 - LG.MEME_SLIPPAGE_BPS - limit) / 1e4:
            raise G.Refused(f"the minimum out is below the input's worth less {LG.MEME_SLIPPAGE_BPS} bps slippage "
                            f"and {limit:g} bps")
        cost = (in_usd - out_usd) / in_usd * 1e4 if in_usd > 0 else 1e9
        if cost > limit:
            raise G.Refused(f"the meme swap costs {cost:.0f} bps (at most {limit:g})")
        return in_usd, out_usd, cost

    def prepare(self, s: LX.Swap, v: LX.View) -> LX.Prepared:
        """Build, guard and simulate one meme swap; raises on any refusal (nothing is signed). The plan allows SOL
        and this one mint, nothing else."""
        if not self.wallet:
            raise G.Refused("no wallet address")
        mint = meme_mint(s)
        if mint is None or mint not in self.decimals:
            raise G.Refused("not a meme swap with a checked coin")
        in_mint, out_mint = (WSOL, mint) if s.src == SOL else (mint, WSOL)
        slip = LG.MEME_SLIPPAGE_BPS
        allowed = frozenset({WSOL, mint})
        routes = G.ROUTE_MINTS | {mint}
        self.check_jupiter()
        for m in (in_mint, out_mint):
            G.check_mint(m, self.chain.multiple([m], "confirmed").get(m))
        last: Exception | None = None
        for max_acc in S.MAX_ACCOUNTS:
            b = S.build(self.jup, in_mint, out_mint, s.in_raw, self.wallet, slip, max_acc)
            bad = [m for m in b.route_mints if m not in routes]
            if bad:
                raise G.Refused(f"the route passes through a mint not on the route list ({bad[0][:6]})")
            in_usd, out_usd, cost = self._meme_prices_ok(s, v, b, mint)
            ours = G.min_out(b.out_amount, slip)
            plan = G.Plan(self.wallet, in_mint, out_mint, s.in_raw, max(ours, s.min_out_raw), slip, allowed)
            if s.min_out_raw and ours < s.min_out_raw:
                raise G.Refused("the new quote is worse than the confirmed minimum")
            tables = self.chain.tables(b.tables)
            blockhash, lvbh = self.chain.blockhash()
            price = b.cu_price if b.cu_price else LX.DEFAULT_CU_PRICE
            units = G.MAX_UNITS
            try:
                msg = self._compile(b, units, min(price, G.MAX_PRIORITY_L * 1_000_000 // units), blockhash, tables)
                fees, effect, val = self._guarded_simulation(plan, msg, tables)
            except OverflowError as e:
                last = e
                continue
            used = int(val.get("unitsConsumed") or 0)
            if used > 0:
                units = min(G.MAX_UNITS, max(100_000, int(used * 1.2) + 10_000))
                msg = self._compile(b, units, min(price, G.MAX_PRIORITY_L * 1_000_000 // units), blockhash, tables)
                fees, effect, val = self._guarded_simulation(plan, msg, tables)
            return LX.Prepared(plan, b, msg, lvbh, fees, effect, used or None, in_usd, out_usd, cost)
        raise G.Refused(f"the transaction does not fit even with fewer accounts ({last})")

    def _row(self, s: LX.Swap, p: LX.Prepared, sig: str, status: str, why: str | None, back: dict | None) -> None:
        mint = meme_mint(s)
        dec = 9 if s.dst == SOL else self.decimals.get(mint, 0)
        out_usd = None
        if back and status == "filled" and p.build.out_amount and p.out_usd:
            out_usd = back["out_raw"] / 10 ** dec * (p.out_usd / (p.build.out_amount / 10 ** dec))
        LX.write_row({"t": LX.now_ms(), "mode": self.gate.ack.mode, "kind": s.kind, "book": s.book, "ref": s.ref,
                      "from": s.src, "to": s.dst,
                      "in_raw": (back or {}).get("in_raw", s.in_raw if status == "filled" else 0),
                      "out_raw": (back or {}).get("out_raw", 0) if status == "filled" else 0,
                      "sol_delta_l": (back or {}).get("sol_delta_l", ""), "fee_l": (back or {}).get("fee_l", ""),
                      "tip_l": p.fees.get("tip_l"), "in_usd": round(p.in_usd, 4) if p.in_usd is not None else "",
                      "out_usd": round(out_usd, 4) if out_usd is not None else "",
                      "planned_out_raw": p.build.out_amount, "min_out_raw": p.plan.min_out_raw, "sig": sig,
                      "status": status, "why": why, "unread": "" if back is not None else "1"})

    # ------------------------------------------------ a rule's orders

    verdict: dict | None = None

    def fresh_verdict(self, mint: str) -> dict | None:
        """The mint's verdict when it is under a minute old, else a new check (None without a checker)."""
        now = LX.now_ms()
        v = self.verdict
        if isinstance(v, dict) and v.get("mint") == mint and 0 <= now - int(v.get("t") or 0) <= \
                LG.MEME_CHECK_MAX_AGE_MS - 5_000:
            return v
        if self.check is None:
            return None
        try:
            self.verdict = self.check(mint)
        except Exception as e:                           # a failed check is a refusal
            self.verdict = {"mint": mint, "ok": False, "reasons": [f"the check failed ({type(e).__name__})"],
                            "t": now}
        return self.verdict

    def buy(self, rule: str, mint: str, v: LX.View, proof, gate_why=None, signal_ms: int | None = None
            ) -> tuple[LX.Swap | None, dict]:
        """One meme buy of up to the [meme] section's swap cap, only when live_gate.meme_problems is empty (asked
        again before every attempt, with a verdict under a minute old)."""
        ack = self.gate.ack

        def meme_why() -> list[str]:
            killed = LG.killed() or bool(self.gate.kill())
            return LG.meme_problems(rule, mint, ack, proof, self.fresh_verdict(mint), LX.now_ms(), killed)

        why = meme_why()
        if why:
            LX.log_order({"what": "refused", "kind": "meme", "book": rule, "to": LG.MEME_PREFIX + mint,
                          "why": "; ".join(why)[:300]})
            return None, {"status": "refused", "why": "; ".join(why)}
        dec = (self.verdict.get("facts") or {}).get("decimals")
        if not isinstance(dec, int):
            return None, {"status": "refused", "why": "the safety check did not read the coin's decimals"}
        self.decimals[mint] = dec
        remember(mint, dec)
        psol = v.prices.get(M.SOL.mint)
        if not psol:
            return None, {"status": "refused", "why": "no USD price for SOL"}
        raw = int(ack.meme_cap("trade") * 0.98 / psol * 1e9)
        s = LX.Swap("meme", SOL, LG.MEME_PREFIX + mint, raw, book=rule, signal_ms=signal_ms)
        return s, self.execute(s, v, gate_why=lambda: (gate_why() if gate_why else []) + meme_why())

    def sales(self, rule: str, mint: str, raw: int, v: LX.View) -> list[LX.Swap]:
        """A rule's holding of `mint` back into SOL: what the wallet really holds, in pieces under the swap cap."""
        raw = min(raw, v.tokens.get(mint, 0))
        dec, px = self.decimals.get(mint), v.prices.get(mint)
        if raw <= 0 or dec is None:
            return []
        lim = self.gate.ack.meme_cap("trade")
        usd = raw / 10 ** dec * px if px else None
        n = math.ceil(usd / (lim * 0.98)) if usd and lim > 0 and usd > lim * 0.98 else 1
        part = raw // n
        parts = [part] * (n - 1) + [raw - part * (n - 1)]
        return [LX.Swap("meme", LG.MEME_PREFIX + mint, SOL, r, book=rule, signal_ms=LX.now_ms()) for r in parts if r > 0]
