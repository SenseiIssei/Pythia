# pump.fun engine clock audit (2026-10-29): the fix and the replay check

Pre-registered in `results/pumpfun_clock_audit_prereg.md`. No trial: R5's registry does not change.

## What was wrong (audit of d84b252)

1. The clock could run backwards: `advance()` set `now = at` without a max, and `create()`/`migrate()` scheduled
   their signals at the row's chain time. A creation or migration released late from `live.Hold` scheduled its entry
   in the past; the next row ran it, the clock went back and the following held rows were handled at their old
   times (the look-ahead of 2026-10-28 again, for creation and migration strategies).
2. A late row ran only the actions due before its own time, then was handled at `now`.
3. Metadata rows (wall clock) and pool reads (wall clock) moved the paper engine ahead of the chain clock about once
   a second; the live service (no metadata) did not. A gap row (the links' state, wall clock, up to 90 s after the
   last row) did the same.
4. With `t = now`, every row released from Hold got one arrival time while `tok.t0` is chain time: EARLY_S windows,
   buys_10s, net_sol_10s, dev_sell_t, secs_since_trade and the trackers saw squeezed time.
5. CreatorBook's last time could go back; the tap reader lost the rows appended before a rotation; a failed rotation
   closed the tap for good; the collector's held pool trades went out without their signature and stayed held.

## What changed

- `sim.py`: `push()` never schedules before the clock, `advance()` never moves it back; every row first runs what is
  due before `max(t, now)`; fills, exits, signals and scheduling use `now`, the token's state and every feature
  (token, early buyers, early, select and trend trackers) the row's chain time. A gap row marks what is open and
  moves no clock. `day_events` times a pool read no earlier than its receive time.
- `early.py`: the 5 s holder snapshot is taken before the first row past it (a held coin's snapshot was due after
  all its rows); in chain order nothing changes.
- `tokens.py`: the creator's last time and a token's last trade time take the max.
- `collector.py`: metadata and pool reads go to the books on the chain clock (`SlotClock.latest`; the store keeps
  the receive time), the tap reader drains the rotated file from its position, the tap reopens after a failed
  rotation, held pool trades go out once with their signature.
- Not changed: `live.Hold`, `HOLD_MS`, `HOLD_TABLES`, `paper_dir` (Hold already skips a failing row alone since
  868a5cd).

## The replay of 2026-10-28, before (e068d83) and after

Rules and every pipeline strategy, paper executor, default costs, select and trend on; 137 gap rows, 50 pool reads.

| | before | after |
|---|---|---|
| closed trades and failed buys | 68,936 | 68,913 |
| times the clock went back | 0 | 0 |
| trades only in one run | 23 | 0 |

Every one of the 23 is a trade of the old rule books (A_all, A_dev, B_w3, C) whose sale landed 0.01 to 2.5 s before
a link outage began: before, the gap row (timed at the link's return) advanced the clock and closed them first; now
the gap row moves no clock, the sale is still in flight when the gap is marked, and the trade is dropped as gapped
(conservative). Their P&L: A_all_x1 -105.977 to -106.007 SOL, A_all_x2 -117.999 to -117.843, A_dev_x1 -46.546 to
-46.578, A_dev_x2 -62.713 to -62.635, B_w3_x1 -17.801 to -17.785, C_20in60_x2 -10.065 to -10.035, C_50in300_x2
-3.262 to -3.233. Every pipeline book (P_*, the live strategies' paper twins) is identical, and no pool read changed
a trade. A replay feeds rows in chain order, so the held-row fixes (points 1, 2, 4) cannot show here; they show in
the live shadow and service, and the tests in `tests/test_pumpfun_clock.py` cover them (all 13 fail before the fix).
