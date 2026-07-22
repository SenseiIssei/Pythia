// AI signal provider — runtime-agnostic front door.
//
// The engine core (`pythia_core::llm`) speaks to any of ~10 LLM providers
// (Anthropic, OpenAI, xAI/Grok, z.ai, DeepSeek, Gemini, Groq, OpenRouter,
// Mistral, local Ollama). How the frontend reaches it depends on where it runs:
//
//   native (Tauri)  → invoke commands; keys live in the OS keychain (manage here)
//   server (web)    → fetch the backend; keys live in the server's env (read-only)
//   browser (paper) → unavailable (no key store, no CORS-safe way to call models)
//
// This module hides that branching so pages just call `aiProviders()` /
// `aiSignal()` and check `aiMode()`.

import { invoke } from "@tauri-apps/api/core";
import { isTauri } from "./engine";
import { serverUrl } from "./engine/serverEngine";
import type { LlmProviderInfo, LlmSignal } from "./types";

export type AiMode = "native" | "server" | "none";

export function aiMode(): AiMode {
  if (isTauri()) return "native";
  if (serverUrl()) return "server";
  return "none";
}

/** True when keys can be entered/stored from the UI (native only). */
export function aiKeysManagedHere(): boolean {
  return aiMode() === "native";
}

export async function aiProviders(): Promise<LlmProviderInfo[]> {
  switch (aiMode()) {
    case "native":
      return invoke<LlmProviderInfo[]>("llm_providers");
    case "server": {
      const r = await fetch(serverUrl()! + "/api/llm/providers");
      if (!r.ok) throw new Error(`providers: HTTP ${r.status}`);
      return (await r.json()) as LlmProviderInfo[];
    }
    default:
      return [];
  }
}

export async function aiSignal(
  provider: string,
  model: string,
  context: string
): Promise<LlmSignal> {
  switch (aiMode()) {
    case "native":
      return invoke<LlmSignal>("llm_signal", { provider, model, context });
    case "server": {
      const r = await fetch(serverUrl()! + "/api/llm/signal", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ provider, model, context }),
      });
      if (!r.ok) throw new Error((await r.text()) || `HTTP ${r.status}`);
      return (await r.json()) as LlmSignal;
    }
    default:
      throw new Error(
        "AI signals need the desktop app or a connected backend — the browser paper build can't reach model APIs."
      );
  }
}

export async function saveAiKey(provider: string, key: string): Promise<void> {
  if (aiMode() !== "native") {
    throw new Error("Set provider keys in the server's environment (e.g. OPENAI_API_KEY).");
  }
  await invoke("save_llm_key", { provider, key });
}

export async function clearAiKey(provider: string): Promise<void> {
  if (aiMode() !== "native") return;
  await invoke("clear_llm_key", { provider });
}
