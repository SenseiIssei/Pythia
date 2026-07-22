import type { EngineClient } from "./client";
import { isTauri } from "./client";
import { PaperEngine } from "./paperEngine";
import { ServerEngineClient, serverUrl } from "./serverEngine";
import { TauriEngineClient } from "./tauriEngine";

// Single app-wide engine. Three ways to answer the one EngineClient interface:
//   · native build              → TauriEngineClient (Rust daemon over IPC)
//   · browser + VITE_PYTHIA_SERVER → ServerEngineClient (standalone backend)
//   · browser, no backend       → PaperEngine (self-contained paper demo)
let engine: EngineClient | null = null;

export function getEngine(): EngineClient {
  if (!engine) {
    if (isTauri()) {
      engine = new TauriEngineClient();
    } else {
      const url = serverUrl();
      engine = url ? new ServerEngineClient(url) : new PaperEngine();
    }
    engine.start();
  }
  return engine;
}

export type { EngineClient, EngineState } from "./client";
export { isTauri } from "./client";
