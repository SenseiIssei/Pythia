// Model status: the volatility model running in shadow mode (pythia-core/src/ml.rs).
// Read-only in every runtime; nothing here can place or size an order.

import { invoke } from "@tauri-apps/api/core";
import { liveMode } from "./live";
import { serverUrl } from "./engine/serverEngine";

export type MlState = "noModel" | "rejected" | "warmingUp" | "live";
export type DriftLevel = "stable" | "shift" | "drift";

export interface MlModelInfo {
  name: string;
  version: string;
  trees: number;
  trainFromMs: number;
  trainToMs: number;
  labGainVsHarPct: number;
  labDmP: number;
}

export interface CoinForecast {
  coin: string;
  hourMs: number;
  modelVolPct: number;
  harVolPct: number;
  lastHourVolPct: number;
  weekVolPct: number;
}

export interface ShadowSummary {
  scored: number;
  sinceMs: number | null;
  qlikeModel: number | null;
  qlikeHar: number | null;
  qlikeNaive: number | null;
  gainVsHarPct: number | null;
  winRate: number | null;
}

export interface ScoredHour {
  symbol: string;
  hourMs: number;
  realised: number;
  model: number;
  har: number;
  qlikeModel: number;
  qlikeHar: number;
  qlikeNaive: number;
}

export interface FeatureDrift {
  feature: string;
  /** How differently the last week spreads over the training bins. Informational. */
  psi: number;
  /** Percent of the last week outside the range the model was trained on. The alarm. */
  outsidePct: number;
  level: DriftLevel;
}

export interface MlStatus {
  state: MlState;
  message: string;
  model: MlModelInfo | null;
  coins: CoinForecast[];
  shadow: ShadowSummary;
  recent: ScoredHour[];
  drift: FeatureDrift[];
  updatedMs: number;
  /** M2, the weekly coin ranking. Missing from older backends. */
  picks?: PicksStatus;
}

// M2 "Picks" (pythia-core/src/ml_picks.rs): weekly ranking, scored a week later.

export interface PicksModelInfo {
  name: string;
  version: string;
  trees: number;
  trainFromMs: number;
  trainToMs: number;
  horizonDays: number;
  labRankIc: number | null;
  labRankIcT: number | null;
  labRankIcLiquid50: number | null;
  typicalCoins: number | null;
  typicalWithPerpPct: number | null;
}

export interface PickView {
  symbol: string;
  rank: number;
  /** 100 = best of the day, 0 = worst. */
  percentile: number;
  score: number;
  perp: boolean;
}

export interface RankingView {
  dayMs: number;
  madeMs: number;
  version: string;
  coins: number;
  withPerp: number;
  top: PickView[];
  bottom: PickView[];
  engine: PickView[];
  notes: string[];
}

export interface WeekScore {
  dayMs: number;
  rankIc: number;
  coins: number;
  topPct: number;
  bottomPct: number;
}

export interface PicksShadowSummary {
  rankings: number;
  weeks: number;
  sinceMs: number | null;
  rankIc: number | null;
  rankIcRecent: number | null;
  rankIcT: number | null;
  hitRate: number | null;
  history: WeekScore[];
}

export interface PicksStatus {
  state: MlState;
  message: string;
  model: PicksModelInfo | null;
  running: boolean;
  latest: RankingView | null;
  shadow: PicksShadowSummary;
  drift: FeatureDrift[];
  engineNotes: string[];
  updatedMs: number;
}

/** Ranks the latest complete day now instead of waiting for the week. Ranks and records, never trades. */
export async function runPicks(): Promise<void> {
  switch (liveMode()) {
    case "native":
      await invoke("ml_picks_run");
      return;
    case "server": {
      const r = await fetch(`${serverUrl()}/api/ml/picks/run`, { method: "POST" });
      if (!r.ok) throw new Error(`backend answered ${r.status}`);
      return;
    }
    default:
      throw new Error("Models run in the desktop app or a connected backend.");
  }
}

export async function mlStatus(): Promise<MlStatus> {
  switch (liveMode()) {
    case "native":
      return invoke<MlStatus>("ml_status");
    case "server": {
      const r = await fetch(`${serverUrl()}/api/ml/status`);
      if (!r.ok) throw new Error(`backend answered ${r.status}`);
      return (await r.json()) as MlStatus;
    }
    default:
      throw new Error("Models run in the desktop app or a connected backend.");
  }
}
