// Page-level pieces the redesigned pages share, built only from the design
// system (src/design) and its tokens: the numbers that matter on top, titled
// sections, key/value rows, a limit meter, filter chips, a switch row, folded
// detail, cost lines, a confirm button and an undo note. Pages import the
// design system's primitives from "../design" and these from "../pagekit".

import { useCallback, useEffect, useId, useState, type ReactNode } from "react";
import { ChevronDown, type LucideIcon } from "lucide-react";
import { Button, Card, Chip, ConfirmSheet, Empty, Notice, Skeleton, Toggle, changeTone, money, type ButtonVariant } from "../design";
import { Explain } from "../components/ui";
import { costWarning } from "../components/PnlBreakdown";
import { explain } from "../glossary";
import type { PnlBreakdown } from "../types";
import type { Level } from "./format";

export * from "./format";

export type StatTone = "up" | "down" | "flat" | "warn" | "plain";

const TONE_TEXT: Record<StatTone, string> = { up: "text-up", down: "text-down", flat: "text-ink", warn: "text-warn", plain: "text-ink" };

export interface Stat {
  label: string;
  value: ReactNode;
  /** Colours the value: up green, down red, warn amber; plain is the text colour. */
  tone?: StatTone;
  /** A short line under the value. */
  sub?: ReactNode;
  /** One sentence for the "?". Defaults to the glossary entry for the label. */
  help?: string;
}

/**
 * The one to three numbers a page is about, in one card at the top. The
 * first is the headline and reads largest; the rest sit under it.
 */
export function KeyStats({ items }: { items: Stat[] }) {
  const [lead, ...rest] = items;
  if (!lead) return null;
  return (
    <Card>
      <StatBlock s={lead} lead />
      {rest.length > 0 && (
        <div className={`mt-5 grid gap-4 ${rest.length === 1 ? "grid-cols-1" : "grid-cols-2"}`}>
          {rest.map((s) => (
            <StatBlock key={s.label} s={s} />
          ))}
        </div>
      )}
    </Card>
  );
}

function StatBlock({ s, lead }: { s: Stat; lead?: boolean }) {
  const tip = s.help ?? explain(s.label);
  return (
    <div className="min-w-0">
      <div className="flex items-center gap-1 text-[13px] font-medium text-muted">
        <span className="min-w-0">{s.label}</span>
        {tip && <Explain text={tip} label={s.label} />}
      </div>
      <div className={`tabular break-words font-bold tracking-tight ${lead ? "text-[34px] leading-tight" : "text-2xl leading-tight"} ${TONE_TEXT[s.tone ?? "plain"]}`}>
        {s.value}
      </div>
      {s.sub && <div className="mt-1 text-[13px] text-muted">{s.sub}</div>}
    </div>
  );
}

/**
 * A titled block: a heading, an optional sentence saying what it shows, and
 * the content in a card. `bare` leaves the card off for content that brings
 * its own.
 */
export function Section({
  title,
  hint,
  right,
  help,
  children,
  bare,
}: {
  title: string;
  hint?: ReactNode;
  right?: ReactNode;
  help?: string;
  children: ReactNode;
  bare?: boolean;
}) {
  const tip = help ?? explain(title);
  return (
    <section aria-label={title} className="space-y-2.5">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 px-1 pt-3">
        <h2 className="flex min-w-0 items-center gap-1.5 text-xl font-semibold tracking-tight text-ink">
          <span className="min-w-0">{title}</span>
          {tip && <Explain text={tip} label={title} />}
        </h2>
        {right && <div className="flex shrink-0 flex-wrap items-center gap-2">{right}</div>}
      </div>
      {hint && <p className="px-1 text-sm leading-relaxed text-muted">{hint}</p>}
      {bare ? children : <Card>{children}</Card>}
    </section>
  );
}

/** One label on the left, its value on the right, an optional line under each. */
export function Row({
  label,
  value,
  sub,
  tone,
  help,
  valueSub,
}: {
  label: ReactNode;
  value: ReactNode;
  sub?: ReactNode;
  tone?: StatTone;
  help?: string;
  valueSub?: ReactNode;
}) {
  const tip = help ?? (typeof label === "string" ? explain(label) : undefined);
  return (
    <div className="flex items-start justify-between gap-3 py-3">
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1 text-[15px] text-ink">
          <span className="min-w-0 break-words">{label}</span>
          {tip && typeof label === "string" && <Explain text={tip} label={label} />}
        </div>
        {sub && <div className="mt-0.5 break-words text-[13px] leading-snug text-muted">{sub}</div>}
      </div>
      <div className="max-w-[55%] shrink-0 text-right">
        <div className={`tabular break-words text-[15px] font-semibold ${TONE_TEXT[tone ?? "plain"]}`}>{value}</div>
        {valueSub && <div className="text-[13px] text-muted">{valueSub}</div>}
      </div>
    </div>
  );
}

/** Rows of grey bars while something loads. */
export function LoadingRows({ rows = 3, label = "Loading" }: { rows?: number; label?: string }) {
  return (
    <div role="status" aria-label={label} className="divide-y divide-line">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="flex items-center gap-3 py-3.5">
          <div className="flex-1 space-y-2">
            <Skeleton className="h-4 w-1/2" />
            <Skeleton className="h-3 w-3/4" />
          </div>
          <Skeleton className="h-4 w-16" />
        </div>
      ))}
    </div>
  );
}

const METER: Record<Level, string> = { off: "var(--color-faint)", ok: "var(--color-text)", near: "var(--color-warn)", over: "var(--color-down)" };

/** A thin bar for how full a limit is. The colour follows the level; the words next to it say the same. */
export function Meter({ pct, level = "ok", label }: { pct: number; level?: Level; label: string }) {
  const w = Math.max(0, Math.min(100, Number.isFinite(pct) ? pct : 0));
  return (
    <div role="progressbar" aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(w)} className="h-1.5 w-full overflow-hidden rounded-full bg-surface-2">
      <div className="h-full rounded-full transition-[width] duration-300" style={{ width: `${w}%`, background: METER[level] }} />
    </div>
  );
}

export interface ChipOption<T extends string> {
  id: T;
  label: string;
  help?: string;
  count?: number;
}

/** Filter chips that wrap onto a second line instead of scrolling sideways. */
export function FilterChips<T extends string>({ options, value, onChange, label }: { options: ChipOption<T>[]; value: T; onChange: (v: T) => void; label: string }) {
  return (
    <div role="group" aria-label={label} className="flex flex-wrap gap-2">
      {options.map((o) => (
        <Chip key={o.id} title={o.help} selected={o.id === value} onClick={() => onChange(o.id)}>
          {o.label}
          {o.count != null && <span className="tabular opacity-70">{o.count}</span>}
        </Chip>
      ))}
    </div>
  );
}

/** An on/off switch with its label and one line of explanation. */
export function SwitchRow({ label, hint, on, onChange, disabled }: { label: string; hint?: ReactNode; on: boolean; onChange: (v: boolean) => void; disabled?: boolean }) {
  return (
    <div className="flex items-start justify-between gap-4 py-3">
      <div className="min-w-0 flex-1">
        <div className="text-[15px] font-semibold text-ink">{label}</div>
        {hint && <div className="mt-0.5 text-[13px] leading-relaxed text-muted">{hint}</div>}
      </div>
      <Toggle label={label} on={on} onChange={onChange} disabled={disabled} />
    </div>
  );
}

/** Extra detail that most people never need, folded away until asked for. */
export function More({ title, children, defaultOpen = false }: { title: string; children: ReactNode; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  const id = useId();
  return (
    <div>
      <button type="button" aria-expanded={open} aria-controls={id} onClick={() => setOpen((o) => !o)} className="flex w-full items-center justify-between gap-2 py-2 text-left text-[15px] font-semibold text-ink">
        <span className="min-w-0">{title}</span>
        <ChevronDown size={18} aria-hidden className={`shrink-0 text-muted transition-transform ${open ? "rotate-180" : ""}`} />
      </button>
      {open && (
        <div id={id} className="pb-2">
          {children}
        </div>
      )}
    </div>
  );
}

/** The empty state inside a section: compact, with what to do next. */
export function Nothing({ icon, title, children, action }: { icon?: LucideIcon; title: ReactNode; children?: ReactNode; action?: ReactNode }) {
  return (
    <Empty compact icon={icon} title={title} action={action}>
      {children}
    </Empty>
  );
}

/**
 * Gross, costs and net as three rows, with the 40 % cost warning under them.
 * `fmt` renders one amount: dollars by default, or e.g. percent of capital.
 */
export function CostLines({ pnl, fmt = (n: number) => money(n) }: { pnl: PnlBreakdown; fmt?: (n: number) => string }) {
  const warn = costWarning(pnl);
  return (
    <div>
      <div className="divide-y divide-line">
        <Row label="Before costs" sub="What the trades made at the quoted price" value={fmt(pnl.gross)} tone={changeTone(pnl.gross)} help="Gross: before fees, spread and market impact." />
        <Row label="Costs" sub="Fees and slippage" value={pnl.costs > 0 ? `−${fmt(pnl.costs)}` : fmt(0)} tone={pnl.costs > 0 ? "warn" : "plain"} help="What trading cost: exchange fees, the spread and price impact." />
        <Row label="What you keep" sub="After every cost" value={fmt(pnl.net)} tone={changeTone(pnl.net)} help="Net: the result after all costs." />
      </div>
      {warn && (
        <Notice tone="warning" className="mt-2">
          {warn}
        </Notice>
      )}
    </div>
  );
}

/**
 * A button for anything that cannot be taken back. It opens a sheet that says
 * what will happen in plain words; only the button in the sheet acts.
 */
export function ConfirmAction({
  children,
  title,
  question,
  confirmLabel,
  onConfirm,
  danger = true,
  variant,
  size,
  icon,
  disabled,
}: {
  children: ReactNode;
  title?: string;
  question: ReactNode;
  confirmLabel: string;
  onConfirm: () => void;
  danger?: boolean;
  variant?: ButtonVariant;
  size?: "sm" | "md";
  icon?: LucideIcon;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const close = useCallback(() => setOpen(false), []);
  return (
    <>
      <Button variant={variant ?? (danger ? "danger" : "secondary")} size={size} icon={icon} disabled={disabled} onClick={() => setOpen(true)}>
        {children}
      </Button>
      <ConfirmSheet
        open={open}
        title={title ?? (typeof children === "string" ? children : "Are you sure?")}
        body={question}
        confirm={confirmLabel}
        danger={danger}
        onClose={close}
        onConfirm={() => {
          setOpen(false);
          onConfirm();
        }}
      />
    </>
  );
}

/**
 * "Removed X. Undo" for a few seconds after a removal that can be put back.
 * `offer(message, undo)` shows it; the returned element renders it.
 */
export function useUndoNote(ms = 8000): [ReactNode, (message: string, undo: () => void) => void] {
  const [notice, setNotice] = useState<{ message: string; undo: () => void } | null>(null);
  useEffect(() => {
    if (!notice) return;
    const t = setTimeout(() => setNotice(null), ms);
    return () => clearTimeout(t);
  }, [notice, ms]);
  const el = notice ? (
    <div role="status" className="flex items-center justify-between gap-3 rounded-2xl bg-surface-2 px-4 py-3 text-sm text-ink">
      <span className="min-w-0">{notice.message}</span>
      <Button
        variant="ghost"
        size="sm"
        onClick={() => {
          notice.undo();
          setNotice(null);
        }}
      >
        Undo
      </Button>
    </div>
  ) : null;
  return [el, (message, undo) => setNotice({ message, undo })];
}

/** Map the old six-colour tones to the calm chip tones. */
export function chipTone(t: "cyan" | "purple" | "green" | "red" | "amber" | "neutral"): "neutral" | "good" | "warn" | "bad" | "accent" {
  return t === "green" ? "good" : t === "red" ? "bad" : t === "amber" ? "warn" : t === "purple" ? "accent" : "neutral";
}

export { Explain, Term } from "../components/ui";
