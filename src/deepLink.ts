// Opening a page by URL, for the owner's DevPanel, which embeds the web build
// in an iframe: `?page=wallet` opens the Wallet page, `&embed=1` shows only
// that page at full width (no sidebar, no top bar, no onboarding tour; the
// legal notice only until it was accepted once) with a small "Open Pythia"
// link. Every page id works (`?page=pumpfun`, `?page=realmoney`, ...); an
// unknown one opens Home.

import { isPageId, resolvePage, type PageId } from "./nav";

export interface DeepLink {
  /** The page the URL names, after redirects; null when it names none or an unknown one. */
  page: PageId | null;
  embed: boolean;
}

const YES = new Set(["1", "true", "yes"]);

/** The page and the embed flag of a query string ("?page=wallet&embed=1"). */
export function readDeepLink(search: string): DeepLink {
  const q = new URLSearchParams(search);
  const id = (q.get("page") ?? "").trim().toLowerCase();
  const page = isPageId(id) ? resolvePage(id) : null;
  // Embedding means one page: without a known page there is nothing to embed.
  return { page, embed: page != null && YES.has((q.get("embed") ?? "").trim().toLowerCase()) };
}

/** The query that opens `id` ("?page=wallet", with embed "?page=wallet&embed=1"). */
export function pageQuery(id: PageId, embed = false): string {
  return `?page=${encodeURIComponent(id)}${embed ? "&embed=1" : ""}`;
}

/** The whole app at the same page: the URL without the embed flag. */
export function openPythiaHref(loc: { pathname: string; search: string }): string {
  const q = new URLSearchParams(loc.search);
  q.delete("embed");
  const s = q.toString();
  return `${loc.pathname}${s ? `?${s}` : ""}`;
}

export type StartScreen = "legal" | "onboarding" | "app" | "embed";

/** What the app shows first: the legal notice until accepted, then the tour (never embedded), then the app or the one page. */
export function startScreen(s: { accepted: boolean; onboarded: boolean; embed: boolean }): StartScreen {
  if (!s.accepted) return "legal";
  if (s.embed) return "embed";
  return s.onboarded ? "app" : "onboarding";
}

/** The deep link of the page this window was opened with (none outside a browser). */
export function currentDeepLink(): DeepLink {
  return typeof window === "undefined" ? { page: null, embed: false } : readDeepLink(window.location.search);
}
