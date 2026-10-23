import { useEffect, useId, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";
import { Button } from "./controls";

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/** What the scroll lock touches: the page's own overflow, on html and body. */
export interface ScrollRoot {
  body: { style: { overflow: string } };
  documentElement: { style: { overflow: string } };
}

let locks = 0;
let saved: [string, string] = ["", ""];

/**
 * Stop the page behind an overlay from scrolling; the returned function
 * gives it back. Nested overlays count, and only the last one to close puts
 * back what was there before the first.
 */
export function lockScroll(root: ScrollRoot = document): () => void {
  if (locks === 0) {
    saved = [root.documentElement.style.overflow, root.body.style.overflow];
    root.documentElement.style.overflow = "hidden";
    root.body.style.overflow = "hidden";
  }
  locks += 1;
  let done = false;
  return () => {
    if (done) return;
    done = true;
    locks -= 1;
    if (locks === 0) {
      root.documentElement.style.overflow = saved[0];
      root.body.style.overflow = saved[1];
    }
  };
}

/** `lockScroll` for as long as `active` is true and the component is mounted. */
export function useScrollLock(active: boolean): void {
  useEffect(() => (active ? lockScroll() : undefined), [active]);
}

/**
 * A full-screen overlay that scrolls inside itself: the first-run gate and
 * the tour. On a phone or in the DevPanel's iframe every line and the button
 * at the bottom stay reachable; the page behind it stays put.
 */
export function Screen({ children, label }: { children: ReactNode; label?: string }) {
  useScrollLock(true);
  return (
    <div className="pt-screen" data-scroll-container="" role={label ? "region" : undefined} aria-label={label}>
      {children}
    </div>
  );
}

/**
 * A sheet: slides up from the bottom on a phone, a centred dialog on a wide
 * screen. Escape and the scrim close it; Tab stays inside while it is open.
 */
export function Sheet({
  open,
  onClose,
  title,
  children,
  footer,
  wide,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  footer?: ReactNode;
  /** A wider dialog on desktop, for forms with two columns. */
  wide?: boolean;
}) {
  const id = useId();
  const ref = useRef<HTMLDivElement>(null);
  const close = useRef(onClose);
  close.current = onClose;
  useScrollLock(open);
  useEffect(() => {
    if (!open) return;
    const prev = document.activeElement as HTMLElement | null;
    ref.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        close.current();
      } else if (e.key === "Tab" && ref.current) {
        const items = [...ref.current.querySelectorAll<HTMLElement>(FOCUSABLE)];
        if (!items.length) return;
        const first = items[0];
        const last = items[items.length - 1];
        if (e.shiftKey && (document.activeElement === first || document.activeElement === ref.current)) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      prev?.focus?.();
    };
  }, [open]);
  if (!open) return null;
  return createPortal(
    <div className="pt-sheet-wrap fixed inset-0 z-50 flex items-end justify-center sm:items-center sm:p-6">
      <div className="absolute inset-0 animate-fade-in bg-black/50" onClick={onClose} aria-hidden />
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-labelledby={id}
        tabIndex={-1}
        className={`pt-sheet relative flex w-full animate-sheet-up flex-col rounded-t-sheet bg-surface text-ink shadow-sheet outline-none sm:rounded-sheet ${wide ? "sm:max-w-2xl" : "sm:max-w-md"}`}
      >
        <div className="mx-auto mt-2 h-1 w-9 rounded-full bg-line-strong sm:hidden" aria-hidden />
        <div className="flex items-center justify-between gap-2 px-5 pb-2 pt-4 sm:pt-5">
          <h2 id={id} className="text-xl font-bold tracking-tight">
            {title}
          </h2>
          <button type="button" onClick={onClose} aria-label="Close" className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-surface-2 transition-colors hover:bg-line">
            <X size={16} aria-hidden />
          </button>
        </div>
        <div className={`pt-sheet-body min-h-0 flex-1 overflow-y-auto px-5 ${footer ? "pb-5" : "pt-sheet-pad"}`} data-scroll-container="">
          {children}
        </div>
        {footer && <div className="pt-sheet-pad shrink-0 border-t border-line px-5 pt-3">{footer}</div>}
      </div>
    </div>,
    document.body,
  );
}

/** The same thing by its desktop name. */
export const Modal = Sheet;

/** Ask before something that cannot be undone. */
export function ConfirmSheet({
  open,
  title,
  body,
  confirm,
  danger,
  busy,
  error,
  onConfirm,
  onClose,
  children,
}: {
  open: boolean;
  title: string;
  body: ReactNode;
  confirm: string;
  danger?: boolean;
  busy?: boolean;
  error?: string;
  onConfirm: () => void;
  onClose: () => void;
  children?: ReactNode;
}) {
  return (
    <Sheet
      open={open}
      onClose={onClose}
      title={title}
      footer={
        <div className="grid grid-cols-2 gap-2">
          <Button variant="secondary" onClick={onClose} full>
            Cancel
          </Button>
          <Button variant={danger ? "danger" : "primary"} onClick={onConfirm} disabled={busy} full>
            {busy ? "One moment" : confirm}
          </Button>
        </div>
      }
    >
      <div className="text-[15px] text-muted">{body}</div>
      {children}
      {error && (
        <p role="alert" className="mt-3 text-sm text-down">
          {error}
        </p>
      )}
    </Sheet>
  );
}
