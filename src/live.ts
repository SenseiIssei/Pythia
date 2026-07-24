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
  equity: string;
  patternDayTrader: boolean;
  daytradeCount: number;
  tradingBlocked: boolean;
  accountBlocked: boolean;
  shortingEnabled: boolean;
  paper: boolean;
}

/** One preflight check and whether it passed. */
export interface PreflightCheck {
  name: string;
  ok: boolean;
  detail: string;
}

export interface Preflight {
  ready: boolean;
  paperEndpoint: boolean;
  checks: PreflightCheck[];
}

/** Per-market answer to "why hasn't this traded?". */
export interface MarketDiag {
  marketId: string;
  symbol: string;
  price: number;
  bars: number;
  barBacked: boolean;
  quoteAgeSec: number;
  hasPosition: boolean;
  watchers: string[];
  liveWatchers: number;
  signal?: string;
  /** First gate that would stop an order; absent means the path is clear. */
  suppressed?: string;
}

/** Walk the live-routing chain for every Alpaca market. */
export async function liveDiagnostics(): Promise<MarketDiag[]> {
  switch (liveMode()) {
    case "native":
      return invoke<MarketDiag[]>("live_diagnostics");
    case "server": {
      const r = await fetch(`${serverUrl()}/api/live/diagnostics`);
      if (!r.ok) throw new Error((await r.text()) || `HTTP ${r.status}`);
      return (await r.json()) as MarketDiag[];
    }
    default:
      throw new Error("Diagnostics need the desktop app or a connected backend.");
  }
}

/**
 * Send one small order to Alpaca through the real path.
 *
 * Every other route to a first live order waits on a strategy signal that may
 * not fire for hours. This proves the whole pipeline with one click and a known
 * outcome — and is the fastest way to discover a wrong key or endpoint. Still
 * fully gated: kill switch, risk limits and the session check all apply.
 */
export async function sendTestOrder(marketId: string, notional: number): Promise<string> {
  switch (liveMode()) {
    case "native":
      return invoke<string>("send_test_order", { marketId, notional });
    case "server": {
      const r = await fetch(`${serverUrl()}/api/live/test-order`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ marketId, notional }),
      });
      if (!r.ok) throw new Error((await r.text()) || `HTTP ${r.status}`);
      return await r.text();
    }
    default:
      throw new Error("Test orders need the desktop app or a connected backend.");
  }
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
export async function setLiveConfig(
  armed: boolean,
  paper: boolean,
  dryRun: boolean,
  extendedHours = false
): Promise<void> {
  switch (liveMode()) {
    case "native":
      await invoke("set_live", { armed, paper, dryRun, extendedHours });
      return;
    case "server": {
      const r = await fetch(`${serverUrl()}/api/live/config`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ armed, paper, dryRun, extendedHours }),
      });
      if (!r.ok) throw new Error((await r.text()) || `HTTP ${r.status}`);
      return;
    }
    default:
      throw new Error("Live execution needs the desktop app or a connected backend.");
  }
}

/**
 * Turn the AI overlay on/off.
 *
 * The overlay only ever scales or vetoes a trade a rule already produced — see
 * `AiPolicy`. `maxBoost` is clamped by the backend regardless of what is sent.
 */
export async function setAiPolicy(opts: {
  enabled: boolean;
  ttlSec?: number;
  vetoConfidence?: number;
  maxBoost?: number;
}): Promise<void> {
  switch (liveMode()) {
    case "native":
      await invoke("set_ai_policy", {
        enabled: opts.enabled,
        ttlSec: opts.ttlSec,
        vetoConfidence: opts.vetoConfidence,
        maxBoost: opts.maxBoost,
      });
      return;
    case "server": {
      const r = await fetch(`${serverUrl()}/api/ai/config`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(opts),
      });
      if (!r.ok) throw new Error((await r.text()) || `HTTP ${r.status}`);
      return;
    }
    default:
      throw new Error("The AI overlay needs the desktop app or a connected backend.");
  }
}

/**
 * Run every go-live check in one call (server build only).
 *
 * Worth its own endpoint because these failures are indistinguishable from the
 * dashboard: live keys used against the paper endpoint, a data feed you aren't
 * subscribed to, an account still onboarding, a market that closed an hour ago
 * — all of them look like "armed, no trades".
 */
export async function preflight(): Promise<Preflight> {
  if (liveMode() !== "server") {
    throw new Error("Preflight runs on the backend server (GET /api/preflight).");
  }
  const r = await fetch(`${serverUrl()}/api/preflight`);
  if (!r.ok) throw new Error((await r.text()) || `HTTP ${r.status}`);
  return (await r.json()) as Preflight;
}
