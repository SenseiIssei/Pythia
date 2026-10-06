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
