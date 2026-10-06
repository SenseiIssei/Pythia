// Live-execution & wallet controls — runtime-agnostic front door (mirrors src/ai.ts).
//
//   native (Tauri)  → invoke commands; keys in the OS keychain
//   server (web)    → fetch the backend; keys in the server's env
//   browser (paper) → unavailable (no keys, no venue reachable)

import { invoke } from "@tauri-apps/api/core";
import { isTauri } from "./engine";
import { serverUrl } from "./engine/serverEngine";
import type {
  ExchangeInfo,
  LiveConfig,
  Venue,
  WalletsSnapshot,
  WatchedAddress,
} from "./types";

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
 *
 * It is a connection test, not a strategy, so it is the one order that needs
 * no Strategy Passport. Pass `notional` 0 for the venue's minimum size.
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

const UNAVAILABLE = "Live execution needs the desktop app or a connected backend.";

/** GET a backend route, surfacing the server's own error text. */
async function get<T>(path: string): Promise<T> {
  const r = await fetch(`${serverUrl()}${path}`);
  if (!r.ok) throw new Error((await r.text()) || `HTTP ${r.status}`);
  return (await r.json()) as T;
}

/** Read-only Alpaca account check (buying power, status). */
export async function alpacaAccount(paper: boolean): Promise<AlpacaAccount> {
  switch (liveMode()) {
    case "native":
      return invoke<AlpacaAccount>("alpaca_account", { paper });
    case "server":
      return get<AlpacaAccount>(`/api/live/account?paper=${paper}`);
    default:
      throw new Error(UNAVAILABLE);
  }
}

/**
 * Read-only credential check for any venue. Places no order — this is what the
 * arm flow runs first, so a wrong key surfaces here rather than on the first
 * signal with the order already gone.
 */
export async function verifyVenue(venue: Venue, paper: boolean): Promise<string> {
  switch (liveMode()) {
    case "native":
      return invoke<string>("live_verify", { venue, paper });
    case "server": {
      const r = await get<{ ok: boolean; summary: string }>(
        `/api/live/verify?venue=${venue}&paper=${paper}`
      );
      return r.summary;
    }
    default:
      throw new Error(UNAVAILABLE);
  }
}

/**
 * Arm/disarm live routing. Rejects if a requested venue fails verification.
 * `cfg.extendedHours` opts Alpaca into the pre/post-market session; the engine
 * still only uses it while the broker reports that session running.
 */
export async function setLiveConfig(cfg: LiveConfig): Promise<void> {
  switch (liveMode()) {
    case "native":
      await invoke("set_live", { cfg });
      return;
    case "server": {
      const r = await fetch(`${serverUrl()}/api/live/config`, {
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

/** Every exchange Pythia can route to, with a `configured` flag. */
export async function listExchanges(): Promise<ExchangeInfo[]> {
  switch (liveMode()) {
    case "native":
      return invoke<ExchangeInfo[]>("exchanges");
    case "server":
      return get<ExchangeInfo[]>("/api/exchanges");
    default:
      return [];
  }
}

/**
 * Store one exchange's credentials and make it the active crypto venue.
 * Desktop only: the server reads its keys from its own environment, by design —
 * an HTTP endpoint that writes API keys would be a remote-code-execution-grade
 * hole on a box exposed to a LAN.
 */
export async function saveExchangeKeys(
  exchange: string,
  fields: Record<string, string>
): Promise<void> {
  if (liveMode() !== "native") {
    throw new Error("On the backend, exchange keys come from PYTHIA_EXCHANGE_* in its environment.");
  }
  await invoke("save_exchange_keys", { exchange, fields });
}

export async function clearExchangeKeys(exchange: string): Promise<void> {
  if (liveMode() !== "native") throw new Error("Server keys are managed in its environment.");
  await invoke("clear_exchange_keys", { exchange });
}

/** The unified balance sheet. Read-only in every runtime. */
export async function walletSnapshot(): Promise<WalletsSnapshot> {
  switch (liveMode()) {
    case "native":
      return invoke<WalletsSnapshot>("wallet_snapshot");
    case "server":
      return get<WalletsSnapshot>("/api/wallets");
    default:
      throw new Error("Wallets need the desktop app or a connected backend.");
  }
}

/** Watch-only addresses (public data — no key is ever stored). */
export async function walletAddresses(): Promise<WatchedAddress[]> {
  if (liveMode() !== "native") return [];
  return invoke<WatchedAddress[]>("wallet_addresses");
}

export async function saveWalletAddresses(list: WatchedAddress[]): Promise<void> {
  if (liveMode() !== "native") {
    throw new Error("On the backend, watched addresses come from PYTHIA_WALLETS in its environment.");
  }
  await invoke("save_wallet_addresses", { list });
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
