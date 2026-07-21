import type { EngineClient } from "./client";
import { isTauri } from "./client";
import { PaperEngine } from "./paperEngine";
import { TauriEngineClient } from "./tauriEngine";

// Single app-wide engine. Native build → Rust daemon proxy; browser → paper engine.
let engine: EngineClient | null = null;

export function getEngine(): EngineClient {
  if (!engine) {
    engine = isTauri() ? new TauriEngineClient() : new PaperEngine();
    engine.start();
  }
  return engine;
}

export type { EngineClient, EngineState } from "./client";
export { isTauri } from "./client";
