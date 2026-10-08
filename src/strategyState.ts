import type { StrategyState } from "./types";

/**
 * Ask the engine to switch a strategy and return why it refused, or "" when
 * it did not. The engine refuses for reasons the page must show: a passport
 * that is not green, missing demo keys, or an autopilot that runs the
 * strategy and sets its state itself. Tauri rejects with a plain string, the
 * server with an Error; both come back as the sentence.
 */
export async function changeStrategyState(
  set: (id: string, s: StrategyState) => Promise<void>,
  id: string,
  state: StrategyState,
): Promise<string> {
  try {
    await set(id, state);
    return "";
  } catch (e) {
    return e instanceof Error ? e.message : String(e);
  }
}
