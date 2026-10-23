"""The live stake follows the wallet (the owner's decision, 2026-10-23). LIVE ONLY: paper books keep 0.1 SOL.

The base is the wallet's SOL plus what the open positions cost. Under PAUSE_BELOW_SOL the bot buys
nothing; under MIN_BELOW_SOL it buys MIN_STAKE_SOL; otherwise SHARE of the base. A fall of the realised
P&L curve from its peak (as a share of what the wallet held at that peak) halves the stake beyond
BRAKE_HALF and drops it to the minimum beyond BRAKE_MIN. Until the current rule has PROOF_TRADES closed
live trades with a mean return of at least 0, at most PROOF_CAP_SOL. Then at most MAX_STAKE_SOL and at
most the owner's ceiling (the ack, the app, the code caps; it rules even under the minimum), rounded
down to whole hundredths of a SOL. The daily loss limit is DAILY_LOSS_SHARE of the base at the start of
the UTC day, never above the ack's.

With the ack's limits=wallet (test mode only, the owner's decision 2026-10-23) the money limits follow the
wallet instead: SHARE (or the ack's stake_share, at most ACK_MAX_SHARE; the owner's share from the app at
most WALLET_MAX_SHARE) of the base, at least MIN_STAKE_SOL, rounded down to 0.01 SOL, the drawdown brake and
the pause under PAUSE_BELOW_SOL as above; no proof cap, no MAX_STAKE_SOL, no daily loss rule, and never more
than `room_sol` (what the wallet can pay with the fee reserve and the slippage room kept).
"""

from __future__ import annotations

import math

SHARE = 0.10
MIN_STAKE_SOL = 0.05
MAX_STAKE_SOL = 0.25
PROOF_TRADES = 50
PAUSE_BELOW_SOL = 0.25
MIN_BELOW_SOL = 0.5
BRAKE_HALF = 0.15
BRAKE_MIN = 0.30
PROOF_CAP_SOL = 0.10
DAILY_LOSS_SHARE = 0.25
ACK_MAX_SHARE = 0.50                     # the ack's stake_share with limits=wallet
WALLET_MAX_SHARE = 1.00                  # the owner's share from the app (the fee reserve always stays)


def sized(*, balance_sol: float, open_cost_sol: float, peak_pnl_sol: float, pnl_sol: float, live_trades: int,
          live_mean: float | None, ceiling_sol: float, share: float = SHARE, wallet: bool = False,
          room_sol: float | None = None) -> tuple[float, str]:
    """The stake in SOL for the next buy (0.0: pause) and why, in a few words for the app. `share` below
    SHARE lowers it (the owner's share from the app without limits=wallet); `wallet`: limits=wallet."""
    base = balance_sol + open_cost_sol
    if base < PAUSE_BELOW_SOL:
        return 0.0, f"stake paused: wallet under {PAUSE_BELOW_SOL:.2f} SOL"
    if wallet:
        return _wallet(base, balance_sol, peak_pnl_sol, pnl_sol, ceiling_sol, share, room_sol)
    share = min(SHARE, max(0.0, share))
    if base < MIN_BELOW_SOL:
        stake, why = MIN_STAKE_SOL, f"minimum {MIN_STAKE_SOL:.2f} SOL: wallet {base:.2f} SOL under {MIN_BELOW_SOL:g}"
    else:
        stake, why = max(share * base, MIN_STAKE_SOL), f"{share * 100:.0f} % of {base:.2f} SOL"
    stake, why = _brake(stake, why, balance_sol, peak_pnl_sol, pnl_sol)
    if not (live_trades >= PROOF_TRADES and live_mean is not None and live_mean >= 0) and stake > PROOF_CAP_SOL:
        stake, why = PROOF_CAP_SOL, why + f", at most {PROOF_CAP_SOL:.2f} until {PROOF_TRADES} live trades " \
                                          f"with a mean of at least 0 ({live_trades} so far)"
    if stake > MAX_STAKE_SOL:
        stake, why = MAX_STAKE_SOL, why + f", at most {MAX_STAKE_SOL:.2f}"
    if stake > ceiling_sol:
        stake, why = ceiling_sol, why + f", the owner's ceiling {ceiling_sol:g}"
    stake = max(0.0, math.floor(stake * 100 + 1e-9) / 100)
    if stake <= 0:
        return 0.0, f"stake paused: {why}"
    return stake, why


def _brake(stake: float, why: str, balance_sol: float, peak_pnl_sol: float, pnl_sol: float) -> tuple[float, str]:
    fall = peak_pnl_sol - pnl_sol
    dd = fall / (balance_sol + fall) if fall > 0 and balance_sol + fall > 0 else 0.0
    if dd > BRAKE_MIN:
        return MIN_STAKE_SOL, why + f", drawdown {dd * 100:.0f} %: minimum"
    if dd > BRAKE_HALF:
        return max(stake / 2, MIN_STAKE_SOL), why + f", drawdown {dd * 100:.0f} %: half"
    return stake, why


def _wallet(base: float, balance_sol: float, peak_pnl_sol: float, pnl_sol: float, ceiling_sol: float, share: float,
            room_sol: float | None) -> tuple[float, str]:
    """limits=wallet: the share of the base, the brake, at least the minimum, under the owner's ceiling and what
    the wallet can pay."""
    share = min(WALLET_MAX_SHARE, max(0.0, share))
    stake, why = max(share * base, MIN_STAKE_SOL), f"{share * 100:g} % of {base:.2f} SOL (limits: wallet)"
    stake, why = _brake(stake, why, balance_sol, peak_pnl_sol, pnl_sol)
    if stake > ceiling_sol:
        stake, why = ceiling_sol, why + f", the owner's ceiling {ceiling_sol:g}"
    if room_sol is not None and stake > room_sol:
        stake, why = room_sol, why + f", at most {max(0.0, room_sol):.2f} the wallet can pay"
    stake = max(0.0, math.floor(stake * 100 + 1e-9) / 100)
    if stake < MIN_STAKE_SOL:
        return 0.0, f"stake paused: the wallet cannot pay one trade of {MIN_STAKE_SOL:.2f} SOL ({why})"
    return stake, why


def stake_for(*, balance_sol: float, open_cost_sol: float, peak_pnl_sol: float, pnl_sol: float, live_trades: int,
              live_mean: float | None, ceiling_sol: float) -> float:
    """The stake in SOL for the next buy; 0.0 means pause."""
    return sized(balance_sol=balance_sol, open_cost_sol=open_cost_sol, peak_pnl_sol=peak_pnl_sol, pnl_sol=pnl_sol,
                 live_trades=live_trades, live_mean=live_mean, ceiling_sol=ceiling_sol)[0]


def from_ledger(rule: str | None) -> dict:
    """What stake_for needs from the live ledger and journal (live_exec's own files): the number and mean
    return of `rule`'s closed live trades (test or full), and the realised P&L of every live trade with
    its peak so far (from 0), summed in time order as live_exec.realised sums it."""
    from . import chain_pnl as CP
    from . import curve as C
    from . import live_exec as LX
    rows = LX.read_ledger(10 ** 9)
    rets = [r["ret"] for r in rows if r.get("rule") == rule and r.get("mode") in ("test", "full")
            and r.get("ret") is not None]
    done = CP.absorbed(LX.data_dir())
    moves = [(int(r.get("exit_ms") or 0), int(round((r.get("pnl_sol") or 0.0) * C.LAMPORTS))) for r in rows]
    moves += [(int(j.get("t") or 0), int(j["pnl_l"])) for j in LX.read_journal()
              if not (j.get("sig") and j["sig"] in done)]
    run = peak = 0
    for _, v in sorted(moves, key=lambda m: m[0]):
        run += v
        peak = max(peak, run)
    return {"live_trades": len(rets), "live_mean": sum(rets) / len(rets) if rets else None,
            "peak_pnl_sol": peak / C.LAMPORTS, "pnl_sol": run / C.LAMPORTS}
