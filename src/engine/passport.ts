// The Strategy Passport as the browser-only paper build can know it.
//
// The real gates are computed by the Rust core (`validation.rs`) from candle
// history this build does not have, so every research gate is pending here
// and nothing can be armed. This only fills in the same shape, so the
// Strategies page looks and behaves the same in every build.

import type { Gate, Passport, StrategyConfig } from "../types";

export const GATE_NAMES = [
  "In-sample",
  "Walk-forward",
  "Cost sensitivity",
  "Parameter plateau",
  "Regime split",
  "Deflated Sharpe",
  "Paper forward test",
  "Live at minimum size",
] as const;

const MEASURES = [
  "net return, first 60 %",
  "OOS / IS Sharpe",
  "net return at 2x costs",
  "share of neighbours net-positive",
  "regimes net-positive (of 4)",
  "p-value",
  "closed trades on real prices",
  "closed live trades",
];

const UNITS: Gate["unit"][] = ["pct", "number", "pct", "share", "count", "number", "count", "count"];

function pending(id: number, reason: string, value?: number): Gate {
  return { id, name: GATE_NAMES[id - 1], status: "pending", reason, value, measure: MEASURES[id - 1], unit: UNITS[id - 1] };
}

/** Every gate pending, with the reason it cannot be judged in this build. */
export function browserPassport(s: StrategyConfig): Passport {
  const why = "needs the desktop app or a connected backend: this browser build has no candle history to check against";
  const gates: Gate[] = [1, 2, 3, 4, 5, 6].map((id) => pending(id, why));
  gates.push(
    pending(7, "the browser build runs on simulated prices, which are not a forward test of anything", s.ledger?.forwardTrades ?? 0)
  );
  gates.push(pending(8, "no live trades yet; this gate is earned at minimum size after arming", 0));
  return {
    strategyId: s.id,
    gates,
    liveReady: false,
    blockedReason: `Not ready for real money: gate 1 (in-sample) is not done. ${why[0].toUpperCase()}${why.slice(1)}.`,
    stale: false,
  };
}
