// Live-execution controls — runtime-agnostic front door (mirrors src/ai.ts).
//
//   native (Tauri)  → invoke commands; Alpaca keys in the OS keychain
//   server (web)    → fetch the backend; Alpaca keys in the server's env
//   browser (paper) → unavailable (no keys, no broker reachable)

import { invoke } from "@tauri-apps/api/core";
import { isTauri } from "./engine";
import { serverUrl } from "./engine/serverEngine";

export type LiveMode = "native" | "server" | "none";

export interface AlpacaAccount {
  status: string;
  currency: string;
  cash: string;
  buyingPower: string;
  portfolioValue: string;
  patternDayTrader: boolean;
  tradingBlocked: boolean;
  accountBlocked: boolean;
  paper: boolean;
}

export function liveMode(): LiveMode {
  if (isTauri()) return "native";
  if (serverUrl()) return "server";
  return "none";
}

/** Read-only Alpaca account check (buying power, status). */
export async function alpacaAccount(paper: boolean): Promise<AlpacaAccount> {
  switch (liveMode()) {
    case "native":
      return invoke<AlpacaAccount>("alpaca_account", { paper });
    case "server": {
      const r = await fetch(`${serverUrl()}/api/live/account?paper=${paper}`);
      if (!r.ok) throw new Error((await r.text()) || `HTTP ${r.status}`);
      return (await r.json()) as AlpacaAccount;
    }
    default:
      throw new Error("Live execution needs the desktop app or a connected backend.");
  }
}

/** Arm/disarm live routing. */
export async function setLiveConfig(armed: boolean, paper: boolean, dryRun: boolean): Promise<void> {
  switch (liveMode()) {
    case "native":
      await invoke("set_live", { armed, paper, dryRun });
      return;
    case "server": {
      const r = await fetch(`${serverUrl()}/api/live/config`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ armed, paper, dryRun }),
      });
      if (!r.ok) throw new Error((await r.text()) || `HTTP ${r.status}`);
      return;
    }
    default:
      throw new Error("Live execution needs the desktop app or a connected backend.");
  }
}
