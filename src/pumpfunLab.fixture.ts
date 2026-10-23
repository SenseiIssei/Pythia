// A pump.fun lab answer for the tests, shaped like GET /api/lab/pumpfun.

import type { PumpfunLab } from "./pumpfunLab";

export const LAB: PumpfunLab = {
  found: true,
  updatedMs: 1_792_738_202_908,
  status: "bad",
  headline: "Paper only. 4 day(s) of record.",
  caveat: "Paper only: no wallet, no key, no transaction.",
  pick: "E_d0_x2",
  readiness: {
    P_pool0: { days: 4, days_ok: false, trades: 177, trades_ok: false, mean: 0.004, positive_ok: true, gates_ok: false, shadow_ok: false, ready: false },
    P_press10: { days: 4, trades: 228, mean: -0.064, ready: false },
    P_snipe_dev: { days: 4, trades: 272, mean: -0.06, ready: false },
  },
  shadow: { P_pool0: { n: 17, mean: 0.135, pnl_sol: 0.23 } },
  execution: { fills: 65, failed: 130, lat_buy_ms: { n: 33, median: 9074, p10: 572, p90: 28487 }, verdict: "33 live buys landed a median 9074 ms after the signal." },
  books: [
    {
      rule: "P_press10", entries: 2, wins: 1, mean: 0.01, pnlSol: 0.002, lastMs: 2_000,
      days: [{ day: "2026-10-23", entries: 2, mean: 0.01, pnlSol: 0.002 }],
      curve: [[1_000, 0.003], [2_000, 0.002]],
      recent: [{ exitMs: 2_000, symbol: "BBB", exitWhy: "stop", ret: -0.01, pnlSol: -0.001 }],
    },
    {
      rule: "P_pool0", entries: 1, wins: 1, mean: 0.3, pnlSol: 0.03, lastMs: 1_000,
      days: [{ day: "2026-10-23", entries: 1, mean: 0.3, pnlSol: 0.03 }],
      curve: [[1_000, 0.03]],
      recent: [{ exitMs: 1_000, symbol: "AAA", exitWhy: "tp", ret: 0.3, pnlSol: 0.03 }],
    },
    { rule: "P_new", entries: 1, wins: 0, mean: -0.1, pnlSol: -0.01, lastMs: 500, days: [], curve: [], recent: [] },
  ],
  bookDays: 7,
  ledgerMs: 3_000,
};
