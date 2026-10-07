// The research lab, read-only: paper books and experiment reports
// (pythia-core/src/labview.rs). The desktop app reads the synced data folder,
// the server its own.

import { invoke } from "@tauri-apps/api/core";
import { liveMode } from "./live";
import { serverUrl } from "./engine/serverEngine";

export interface PaperBook {
  name: string;
  variant: string;
  started: string;
  days: number;
  equity: number[];
  dates: string[];
  returnPct: number;
  lastRebalance: Record<string, string>;
}

export interface LabReport {
  name: string;
  updatedMs: number;
  verdict: string;
}

export interface HealthCheck {
  name: string;
  ok: boolean;
  detail: string;
}

export interface LabStatus {
  found: boolean;
  dir: string;
  books: PaperBook[];
  reports: LabReport[];
  /** The VPS's hourly look at every lab job. */
  health: { at: string; ok: boolean; checks: HealthCheck[] } | null;
}

export async function labStatus(): Promise<LabStatus> {
  switch (liveMode()) {
    case "native":
      return invoke<LabStatus>("lab_status");
    case "server": {
      const r = await fetch(`${serverUrl()}/api/lab`);
      if (!r.ok) throw new Error(`backend answered ${r.status}`);
      return (await r.json()) as LabStatus;
    }
    default:
      throw new Error("The lab view needs the desktop app or a connected backend.");
  }
}
