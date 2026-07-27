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
  patternDayTrader: boolean;
  tradingBlocked: boolean;
  accountBlocked: boolean;
  daytradeCount: number;
  paper: boolean;
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

/** Arm/disarm live routing. Rejects if a requested venue fails verification. */
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
