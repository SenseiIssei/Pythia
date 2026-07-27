// Forecasting controls — runtime-agnostic front door (mirrors src/live.ts).
//
// The forecasts themselves arrive with the engine state every tick; this module
// only covers the two things that need an explicit call: running an ensemble
// (which costs money) and changing the tunables.

import { invoke } from "@tauri-apps/api/core";
import { isTauri } from "./engine";
import { serverUrl } from "./engine/serverEngine";
import type { EnsembleRun, ForecastConfig } from "./types";

function mode(): "native" | "server" | "none" {
  if (isTauri()) return "native";
  if (serverUrl()) return "server";
  return "none";
}

const UNAVAILABLE =
  "Model ensembles need the desktop app (keys in the OS keychain) or a backend server (keys in its environment).";

/**
 * Ask every configured provider about one market, independently.
 *
 * This is the expensive operation in the app — one API call per provider — so
 * it is never automatic in the UI. `notes` is passed verbatim to every model,
 * identically, so any disagreement between them measures the question rather
 * than the prompt.
 */
export async function runEnsemble(marketId: string, notes = ""): Promise<EnsembleRun> {
  switch (mode()) {
    case "native":
      return invoke<EnsembleRun>("run_ensemble", { marketId, notes });
    case "server": {
      const r = await fetch(`${serverUrl()}/api/forecast/ensemble`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ marketId, notes }),
      });
      if (!r.ok) throw new Error((await r.text()) || `HTTP ${r.status}`);
      return (await r.json()) as EnsembleRun;
    }
    default:
      throw new Error(UNAVAILABLE);
  }
}

export async function setForecastConfig(cfg: ForecastConfig): Promise<void> {
  switch (mode()) {
    case "native":
      await invoke("set_forecast_config", { cfg });
      return;
    case "server": {
      const r = await fetch(`${serverUrl()}/api/forecast/config`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(cfg),
      });
      if (!r.ok) throw new Error((await r.text()) || `HTTP ${r.status}`);
      return;
    }
    default:
      throw new Error(UNAVAILABLE);
  }
}

export function canRunEnsemble(): boolean {
  return mode() !== "none";
}
