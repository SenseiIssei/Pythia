import { useEffect, useRef, useState, type ReactNode } from "react";
import type { LucideIcon } from "lucide-react";
import { Button } from "./ui";

type Tone = "cyan" | "purple" | "green" | "red" | "neutral";

/**
 * A button for anything that cannot be taken back. The first click does
 * nothing but ask, in plain words and in place; only the second click acts.
 * Escape or "Keep it" backs out. No modal, so it works wherever it sits.
 */
export function ConfirmButton({
  children,
  question,
  confirmLabel,
  onConfirm,
  icon,
  tone = "red",
  disabled,
  className = "",
}: {
  children: ReactNode;
  question: ReactNode;
  confirmLabel: string;
  onConfirm: () => void;
  icon?: LucideIcon;
  tone?: Tone;
  disabled?: boolean;
  className?: string;
}) {
  const [asking, setAsking] = useState(false);
  const keepRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!asking) return;
    keepRef.current?.focus(); // the safe choice has the focus
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setAsking(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [asking]);

  if (!asking) {
    return (
      <Button tone={tone} icon={icon} disabled={disabled} onClick={() => setAsking(true)} className={className}>
        {children}
      </Button>
    );
  }
  return (
    <span
      role="group"
      aria-label="Confirm"
      className="inline-flex max-w-full flex-wrap items-center gap-2 rounded-lg border border-danger/40 bg-danger/5 px-2.5 py-1.5 text-left text-xs text-cyber-text"
    >
      <span className="max-w-xs">{question}</span>
      <button
        type="button"
        onClick={() => {
          setAsking(false);
          onConfirm();
        }}
        className="rounded border border-danger/50 bg-danger/15 px-2 py-0.5 font-bold text-danger hover:bg-danger/25"
      >
        {confirmLabel}
      </button>
      <button
        type="button"
        ref={keepRef}
        onClick={() => setAsking(false)}
        className="rounded border border-cyber-border px-2 py-0.5 text-cyber-text-dim hover:text-cyber-text focus:outline focus:outline-1 focus:outline-accent"
      >
        Keep it
      </button>
    </span>
  );
}

/**
 * "Removed X. Undo" for a few seconds after a removal that can be put back.
 * `offer(message, undo)` shows it; the returned element renders it.
 */
export function useUndo(ms = 8000): [ReactNode, (message: string, undo: () => void) => void] {
  const [notice, setNotice] = useState<{ message: string; undo: () => void } | null>(null);
  useEffect(() => {
    if (!notice) return;
    const t = setTimeout(() => setNotice(null), ms);
    return () => clearTimeout(t);
  }, [notice, ms]);
  const el = notice ? (
    <div
      role="status"
      className="mb-3 flex items-center justify-between gap-3 rounded-lg border border-accent/30 bg-accent/5 px-3 py-2 text-sm text-cyber-text-dim"
    >
      <span>{notice.message}</span>
      <button
        type="button"
        onClick={() => {
          notice.undo();
          setNotice(null);
        }}
        className="rounded border border-accent/50 px-2 py-0.5 text-xs font-bold text-accent hover:bg-accent/10"
      >
        Undo
      </button>
    </div>
  ) : null;
  return [el, (message, undo) => setNotice({ message, undo })];
}
