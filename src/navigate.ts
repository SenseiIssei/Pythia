// Moving to another page from inside a page (Home's insights open Research).
// The sidebar owns the current page; pages ask for a change with an event.

import type { PageId } from "./nav";

const EVENT = "pythia:open-page";

export function openPage(id: PageId): void {
  window.dispatchEvent(new CustomEvent<PageId>(EVENT, { detail: id }));
}

/** Calls `fn` whenever a page asks to open another; returns the unsubscribe. */
export function onOpenPage(fn: (id: PageId) => void): () => void {
  const h = (e: Event) => fn((e as CustomEvent<PageId>).detail);
  window.addEventListener(EVENT, h);
  return () => window.removeEventListener(EVENT, h);
}
