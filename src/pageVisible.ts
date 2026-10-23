// Keeping a page current without a reload. Every page stays mounted (App.tsx
// hides the others), so "visible" means: this page is the one shown and the
// browser tab is in front. Only then does a page poll its endpoints.

import { useCallback, useEffect, useRef, useState, type RefObject } from "react";

/** How often the Lab and Research pages read the lab endpoints again. */
export const LAB_POLL_MS = 30_000;
/** How often the hook looks whether the page is shown; cheap, so a page that is opened reads at once. */
const CHECK_MS = 1_000;

/** Whether a page is due: shown, and its last read is `every` old (or it never read). */
export function shouldRefresh(nowMs: number, lastMs: number, visible: boolean, every = LAB_POLL_MS): boolean {
  return visible && (lastMs <= 0 || nowMs - lastMs >= every);
}

/** "updated 14:05" in the reader's 24 hour clock; "" before the first read. */
export function updatedText(ms: number | null | undefined): string {
  if (!ms || !Number.isFinite(ms)) return "";
  const d = new Date(ms);
  return `updated ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

/** The element is laid out (no hidden page around it) and the tab is in front. */
export function isShown(el: HTMLElement | null): boolean {
  if (!el || el.offsetParent === null) return false;
  return typeof document === "undefined" || document.visibilityState !== "hidden";
}

/** Whether the page holding `ref` is shown, looked at every second. */
export function usePageVisible(ref: RefObject<HTMLElement | null>): boolean {
  const [shown, setShown] = useState(false);
  useEffect(() => {
    const check = () => setShown(isShown(ref.current));
    check();
    const id = window.setInterval(check, CHECK_MS);
    document.addEventListener("visibilitychange", check);
    return () => {
      window.clearInterval(id);
      document.removeEventListener("visibilitychange", check);
    };
  }, [ref]);
  return shown;
}

/**
 * Run `refresh` when the page holding `ref` is shown and its last read is
 * `every` old: at once when the page is opened, then every 30 s while it stays
 * in front, never while hidden. Returns when the last read finished and a
 * function for the Refresh button that reads now.
 */
export function useVisiblePoll(
  ref: RefObject<HTMLElement | null>,
  refresh: () => Promise<unknown> | void,
  every = LAB_POLL_MS,
): [number | null, () => Promise<void>] {
  const [at, setAt] = useState<number | null>(null);
  const fn = useRef(refresh);
  fn.current = refresh;
  const last = useRef(0);
  const busy = useRef(false);

  const run = useCallback(async () => {
    if (busy.current) return;
    busy.current = true;
    try {
      await fn.current();
      setAt(Date.now());
    } finally {
      // A failed read waits its turn too, so an error does not hammer the server.
      last.current = Date.now();
      busy.current = false;
    }
  }, []);

  useEffect(() => {
    const tick = () => {
      if (shouldRefresh(Date.now(), last.current, isShown(ref.current), every)) void run().catch(() => {});
    };
    tick();
    const id = window.setInterval(tick, CHECK_MS);
    document.addEventListener("visibilitychange", tick);
    return () => {
      window.clearInterval(id);
      document.removeEventListener("visibilitychange", tick);
    };
  }, [ref, every, run]);

  return [at, run];
}
