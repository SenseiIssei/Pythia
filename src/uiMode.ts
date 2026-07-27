// Simple vs. advanced UI.
//
// The default is **simple**, and that is a deliberate stance: someone who has
// never traded should be able to open Pythia and understand what it is doing to
// their money without learning the word "drawdown" first. Everything that needs
// domain knowledge to read — order books, Kelly fractions, Brier scores, the
// strategy composer — lives behind the advanced switch.
//
// The rule for deciding where something goes: **if a beginner cannot act on it,
// it does not belong in simple mode.** Numbers they cannot influence are noise,
// and noise is how people end up clicking things they do not understand.
//
// Nothing here changes engine behaviour. Hiding a control does not disable it,
// and simple mode never hides *risk* — the mode banner, the kill switch, and any
// warning about real money are visible in both.

import { useSyncExternalStore } from "react";

export type UiMode = "simple" | "advanced";

const KEY = "pythia.uiMode";

const listeners = new Set<() => void>();
let current: UiMode = read();

function read(): UiMode {
  try {
    return localStorage.getItem(KEY) === "advanced" ? "advanced" : "simple";
  } catch {
    // Private mode, or no storage at all. Simple is the safe default.
    return "simple";
  }
}

export function getUiMode(): UiMode {
  return current;
}

export function setUiMode(mode: UiMode): void {
  if (mode === current) return;
  current = mode;
  try {
    localStorage.setItem(KEY, mode);
  } catch {
    // Not persisting is survivable; not switching would not be.
  }
  listeners.forEach((fn) => fn());
}

function subscribe(fn: () => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

/** Current UI mode, re-rendering the caller when it changes. */
export function useUiMode(): UiMode {
  return useSyncExternalStore(subscribe, getUiMode, () => "simple");
}

/** Convenience for the very common `mode === "advanced"` test. */
export function useAdvanced(): boolean {
  return useUiMode() === "advanced";
}
