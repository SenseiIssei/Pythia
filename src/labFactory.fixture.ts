// A research factory panel's data as GET /api/lab/factory answers (F3 ran, F2 has no report), for the tests.

import type { LabFactory } from "./labFactory";

export const FACTORY: LabFactory = {
  found: true,
  factories: {
    F3: {
      updated_ms: 1_793_000_000_000,
      night: "2026-10-26",
      trials_ever: 330,
      trials_tonight: 300,
      bar: { sharpe: 0.1234, p: 0.95, min_entries: 20, trials: 330 },
      best: [
        { id: "F3_00042", label: "migration 5 s, top 30 %", median: 0.912, entries: 61, dsr: 0.4 },
        { id: "F3_00007", median: 0.7 },
      ],
      holdback: [{ id: "F3_00042", median: 0.48, pnl_sol: -0.031, entries: 40 }],
      winners: [],
      adopted: ["win30"],
      books: [
        { book: "F3_00011", sizing: "10 %, 3 open", sol: 0.61, eur: 97.6, pnl_sol: 0.06, proposed: true },
        { book: "F3_00003", sol: 0.5, eur: null, pnl_sol: -0.05 },
      ],
      retired: [],
      proposals: ["F3_00011"],
      sol_eur: 160,
      start_sol: 0.55,
    },
    F2: null,
  },
  zoo: {
    updated_ms: 1_793_000_000_000,
    labels: {
      win30: { pick: "lgb", days: 4, changes: [] },
      rug0t: { pick: "hgb", days: 3, changes: [{ day: "2026-10-25", from: "lgb", to: "hgb", why: "5 days ahead" }] },
    },
  },
  allocator: {
    updated_ms: 1_793_000_000_000,
    choice: "P_pool5_top30t",
    live_rule: "P_pool0_wait",
    armed: false,
    arms: {
      P_pool0_wait: { days: 9, posterior_mean: -0.004, posterior_sd: 0.01, p_best: 0.2, weight: 0.22, guarded: true },
      P_pool5_top30t: { days: 9, posterior_mean: 0.0123, posterior_sd: 0.008, p_best: 0.62, weight: 0.6, guarded: false },
      P_pool0_wait_lock: { days: 9, posterior_mean: 0.001, posterior_sd: 0.009, p_best: 0.18, weight: 0.18, guarded: false },
    },
  },
};
