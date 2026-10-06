// Research runs on real candles: the parameter sweep behind the Optimizer page
// and the Strategy Passport. Both are computed by the Rust core (the same
// walk-forward and deflated-Sharpe code), reached the same way as live.ts:
//
//   native (Tauri)  → invoke commands
//   server (web)    → fetch the backend
//   browser (paper) → unavailable; there is no candle history or Rust core

import { invoke } from "@tauri-apps/api/core";
import { liveMode } from "./live";
import { serverUrl } from "./engine/serverEngine";
import type { Passport, SweepReport } from "./types";

/**
 * Run validation gates 1 to 6 for one strategy on daily candles. The engine
 * keeps the result, so the passport in the pushed state updates too.
 */
export async function runValidation(strategyId: string): Promise<Passport> {
  switch (liveMode()) {
    case "native":
      return invoke<Passport>("run_validation", { strategyId });
    case "server": {
      const r = await fetch(`${serverUrl()}/api/research/passport?id=${encodeURIComponent(strategyId)}`, { method: "POST" });
      if (!r.ok) throw new Error((await r.text()) || `HTTP ${r.status}`);
      return (await r.json()) as Passport;
    }
    default:
      throw new Error("The validation checks need the desktop app or a connected backend.");
  }
}

/** Whether real-candle research is reachable from this build. */
export function researchAvailable(): boolean {
  return liveMode() !== "none";
}

/** Sweep one strategy's parameter grid on daily candles (fit on 60 %, hold out 40 %). */
export async function runSweep(strategyId: string): Promise<SweepReport> {
  switch (liveMode()) {
    case "native":
      return invoke<SweepReport>("research_sweep", { strategyId });
    case "server": {
      const r = await fetch(`${serverUrl()}/api/research/sweep?id=${encodeURIComponent(strategyId)}`);
      if (!r.ok) throw new Error((await r.text()) || `HTTP ${r.status}`);
      return (await r.json()) as SweepReport;
    }
    default:
      throw new Error("Real-candle research needs the desktop app or a connected backend.");
  }
}
