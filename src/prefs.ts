// Preferences — the non-secret settings that sit beside the keys.
//
// Desktop only: they're stored in the OS keychain alongside the credentials and
// read by the Rust daemon. The backend-server build takes the same settings from
// its environment instead (see .env.example), so there's nothing to edit here.

import { invoke } from "@tauri-apps/api/core";
import { isTauri } from "./engine";

export interface Prefs {
  /** Alpaca market-data feed: `iex` (free tier) or `sip` (paid subscription). */
  alpacaFeed: string;
  /** Candle size every indicator runs on. */
  barTimeframe: string;
  /** Provider id the background AI overlay polls with. */
  aiProvider: string;
  /** Empty → that provider's default model. */
  aiModel: string;
  /** Thinking depth: low | medium | high | xhigh | max. */
  aiEffort: string;
  /** Seconds between overlay calls — one market per pass, so also the cost dial. */
  aiIntervalSec: number;
}

export const DEFAULT_PREFS: Prefs = {
  alpacaFeed: "iex",
  barTimeframe: "5Min",
  aiProvider: "anthropic",
  aiModel: "",
  aiEffort: "low",
  aiIntervalSec: 120,
};

export const TIMEFRAMES = ["1Min", "5Min", "15Min", "30Min", "1Hour", "1Day"];
export const EFFORTS = ["low", "medium", "high", "xhigh", "max"];

export function prefsAvailable(): boolean {
  return isTauri();
}

export async function getPrefs(): Promise<Prefs> {
  if (!isTauri()) return DEFAULT_PREFS;
  return invoke<Prefs>("get_prefs");
}

/** Returns the stored values — the daemon sanitizes, so they may differ from what was sent. */
export async function savePrefs(next: Prefs): Promise<Prefs> {
  if (!isTauri()) throw new Error("Preferences are stored by the desktop app.");
  return invoke<Prefs>("save_prefs", { next });
}

/**
 * Spend one cheap model call to prove a saved key actually works.
 *
 * "Saved" and "works" are different claims. A typo'd key still shows a green
 * badge, and the only symptom is a model that quietly never has an opinion.
 */
export async function testLlmKey(provider: string): Promise<string> {
  if (!isTauri()) throw new Error("Key testing is available in the desktop app.");
  return invoke<string>("test_llm_key", { provider });
}
