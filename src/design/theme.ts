// Light, dark or follow the system. The choice is per device (localStorage)
// and shows as data-theme on <html>; the stylesheet from tokens.ts does the rest.

import { useSyncExternalStore } from "react";
import { themeCss, type ThemeName } from "./tokens";

export type ThemePref = "system" | ThemeName;

const KEY = "pythia.theme";
const listeners = new Set<() => void>();
let current: ThemePref = read();

function read(): ThemePref {
  try {
    const v = localStorage.getItem(KEY);
    return v === "light" || v === "dark" ? v : "system";
  } catch {
    return "system";
  }
}

export function getThemePref(): ThemePref {
  return current;
}

/** What a preference shows, given whether the system is dark. */
export function resolveTheme(pref: ThemePref, systemDark: boolean): ThemeName {
  return pref === "system" ? (systemDark ? "dark" : "light") : pref;
}

function systemDark(): boolean {
  try {
    return window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? false;
  } catch {
    return false;
  }
}

/** The theme on screen right now. */
export function currentTheme(): ThemeName {
  return resolveTheme(current, typeof window === "undefined" ? false : systemDark());
}

function apply(): void {
  if (typeof document === "undefined") return;
  const root = document.documentElement;
  if (current === "system") delete root.dataset.theme;
  else root.dataset.theme = current;
}

export function setThemePref(pref: ThemePref): void {
  if (pref === current) return;
  current = pref;
  try {
    if (pref === "system") localStorage.removeItem(KEY);
    else localStorage.setItem(KEY, pref);
  } catch {
    // Not persisting is fine; not switching would not be.
  }
  apply();
  listeners.forEach((fn) => fn());
}

function subscribe(fn: () => void): () => void {
  listeners.add(fn);
  // A system switch matters while the preference is "system".
  const mq = typeof window !== "undefined" ? window.matchMedia?.("(prefers-color-scheme: dark)") : undefined;
  mq?.addEventListener?.("change", fn);
  return () => {
    listeners.delete(fn);
    mq?.removeEventListener?.("change", fn);
  };
}

export function useThemePref(): ThemePref {
  return useSyncExternalStore(subscribe, getThemePref, () => "system");
}

/** The resolved theme, re-rendering when the preference or the system changes. */
export function useTheme(): ThemeName {
  return useSyncExternalStore(subscribe, currentTheme, () => "light");
}

/** Put the token stylesheet in <head> and apply the saved theme. Call once, before render. */
export function installTheme(): void {
  if (typeof document === "undefined") return;
  if (!document.getElementById("pythia-tokens")) {
    const style = document.createElement("style");
    style.id = "pythia-tokens";
    style.textContent = themeCss();
    document.head.prepend(style);
  }
  apply();
}
