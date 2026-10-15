// The calm page kit: what every redesigned page is built from. It re-exports
// the shared primitives (Card, ListRow, BigNumber, Change, Chip, ...) so a page
// imports from one place, and adds the page-level pieces on top: a header with
// the numbers that matter, key/value rows, a quiet line chart, a meter, notes,
// filter chips, a switch, form fields and the loading and empty states.

import { useCallback, useEffect, useId, useState, type ReactNode } from "react";
import { AlertTriangle, CheckCircle2, ChevronDown, Info, ShieldAlert, type LucideIcon } from "lucide-react";
import { Button as FlowButton, Card, Change, ConfirmSheet, Empty, Skeleton, type ChangeTone, type ChipTone } from "../design/flows";
import { Explain } from "../components/ui";
import { costWarning } from "../components/PnlBreakdown";
import { explain } from "../glossary";
import type { PnlBreakdown } from "../types";
import { domainOf, pathOf, ticksOf, yOf } from "./chart";
import { toneOf, usd, type Level } from "./format";
import "./pagekit.css";

export {
  BigNumber,
  Button,
  Card,
  Change,
  Chip,
  ConfirmSheet,
  Empty,
  ListRow,
  MiniChart,
  SectionTitle,
  Segmented,
  Sheet,
  Skeleton,
  type ChangeTone,
  type ChipTone,
  type SegOption,
} from "../design/flows";
export * from "./format";

/**
 * The page frame: a clear title, one plain sentence under it and room for an
 * action on the right. `wide` gives tables and charts more room on a desktop;
 * on a phone both are the full width.
 */
export function PageShell({
  title,
  subtitle,
  right,
  wide,
  children,
}: {
  title: string;
  subtitle?: ReactNode;
  right?: ReactNode;
  wide?: boolean;
  children: ReactNode;
}) {
  return (
    <div className="fl fl-page -mx-4 -mb-10 -mt-5 px-4 pb-24 pt-5 sm:-mx-6 sm:-mt-6 sm:px-6 sm:pt-6">
      <div className={`mx-auto w-full min-w-0 space-y-4 ${wide ? "max-w-3xl" : "max-w-xl"}`}>
        <header className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <h1 className="text-[28px] font-bold leading-tight tracking-tight">{title}</h1>
            {subtitle && <p className="fl-muted mt-1 text-[15px] leading-relaxed">{subtitle}</p>}
          </div>
          {right && <div className="flex shrink-0 flex-wrap items-center gap-2">{right}</div>}
        </header>
        {children}
      </div>
    </div>
  );
}

export type StatTone = ChangeTone | "warn" | "plain";

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

const STAT_TONE: Record<StatTone, string> = { up: "fl-up", down: "fl-down", flat: "", warn: "fl-warn", plain: "" };

/**
 * The one to three numbers a page is about, at the top. The first is the
 * headline and reads largest.
 */
export function KeyStats({ items }: { items: Stat[] }) {
  const [lead, ...rest] = items;
  if (!lead) return null;
  return (
    <Card>
      <StatBlock s={lead} lead />
      {rest.length > 0 && (
        <div className={`mt-4 grid gap-4 ${rest.length === 1 ? "grid-cols-1" : "grid-cols-2"}`}>
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
      <div className="fl-muted flex items-center gap-1 text-sm">
        <span className="min-w-0">{s.label}</span>
        {tip && <Explain text={tip} label={s.label} />}
      </div>
      <div className={`fl-num break-words font-bold leading-tight tracking-tight ${lead ? "text-[34px]" : "text-2xl"} ${STAT_TONE[s.tone ?? "plain"]}`}>
        {s.value}
      </div>
      {s.sub && <div className="fl-muted mt-0.5 text-sm">{s.sub}</div>}
    </div>
  );
}

/** A green or red change with an arrow, for a Stat's `sub`. */
export function Delta({ usd, pct, tone }: { usd?: number | null; pct?: number | null; tone: ChangeTone }) {
  return <Change usd={usd} pct={pct} tone={tone} size="sm" />;
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
  className = "",
}: {
  title: string;
  hint?: ReactNode;
  right?: ReactNode;
  help?: string;
  children: ReactNode;
  bare?: boolean;
  className?: string;
}) {
  const tip = help ?? explain(title);
  return (
    <section aria-label={title} className={`space-y-2 ${className}`}>
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 px-1 pt-2">
        <h2 className="flex min-w-0 items-center gap-1.5 text-lg font-semibold tracking-tight">
          <span className="min-w-0">{title}</span>
          {tip && <Explain text={tip} label={title} />}
        </h2>
        {right && <div className="flex shrink-0 flex-wrap items-center gap-2">{right}</div>}
      </div>
      {hint && <p className="fl-muted px-1 text-sm leading-relaxed">{hint}</p>}
      {bare ? children : <Card>{children}</Card>}
    </section>
  );
}

/** A list with a hairline between items. */
export function Rows({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`pk-rows ${className}`}>{children}</div>;
}

/** One label on the left, its value on the right, an optional line under the label. */
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
        <div className="flex items-center gap-1 text-[15px]">
          <span className="min-w-0 break-words">{label}</span>
          {tip && typeof label === "string" && <Explain text={tip} label={label} />}
        </div>
        {sub && <div className="fl-muted mt-0.5 break-words text-sm">{sub}</div>}
      </div>
      <div className="shrink-0 text-right">
        <div className={`fl-num text-[15px] font-semibold ${STAT_TONE[tone ?? "plain"]}`}>{value}</div>
        {valueSub && <div className="fl-muted text-sm">{valueSub}</div>}
      </div>
    </div>
  );
}

const NOTE = {
  info: { cls: "fl-surface-2", text: "fl-text", Icon: Info },
  good: { cls: "pk-note-good", text: "fl-up", Icon: CheckCircle2 },
  warn: { cls: "pk-note-warn", text: "fl-warn", Icon: AlertTriangle },
  bad: { cls: "pk-note-bad", text: "fl-down", Icon: ShieldAlert },
} as const;

/** A short message in a soft box. `bad` is for real money or something broken. */
export function Note({
  tone = "info",
  title,
  icon,
  children,
  action,
}: {
  tone?: keyof typeof NOTE;
  title?: ReactNode;
  icon?: LucideIcon;
  children?: ReactNode;
  action?: ReactNode;
}) {
  const look = NOTE[tone];
  const Icon = icon ?? look.Icon;
  return (
    <div role={tone === "bad" || tone === "warn" ? "alert" : undefined} className={`${look.cls} flex flex-wrap items-start gap-3 rounded-2xl px-4 py-3`}>
      <Icon size={18} aria-hidden className={`mt-0.5 shrink-0 ${look.text}`} />
      <div className="min-w-0 flex-1 text-sm leading-relaxed">
        {title && <div className={`font-semibold ${look.text}`}>{title}</div>}
        {children && <div className="fl-muted">{children}</div>}
      </div>
      {action && <div className="flex shrink-0 items-center gap-2 self-center">{action}</div>}
    </div>
  );
}

/** Rows of grey bars while something loads. */
export function LoadingRows({ rows = 3, label = "Loading" }: { rows?: number; label?: string }) {
  return (
    <div role="status" aria-label={label}>
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="flex items-center gap-3 py-3">
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

/** The empty state: what is missing and what to do about it. */
export function Nothing({ icon, title, children, action }: { icon?: LucideIcon; title: string; children?: ReactNode; action?: ReactNode }) {
  return <Empty icon={icon} title={title} action={action}>{children}</Empty>;
}

const METER: Record<Level, string> = { off: "var(--fl-muted)", ok: "var(--fl-text)", near: "var(--fl-warn)", over: "var(--fl-down)" };

/** A thin bar for how full a limit is. Colour follows the level, the label says it in words. */
export function Meter({ pct, level = "ok", label }: { pct: number; level?: Level; label: string }) {
  const w = Math.max(0, Math.min(100, Number.isFinite(pct) ? pct : 0));
  return (
    <div role="progressbar" aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(w)} className="pk-track h-1.5 w-full overflow-hidden rounded-full">
      <div className="h-full rounded-full transition-[width] duration-300" style={{ width: `${w}%`, background: METER[level] }} />
    </div>
  );
}

export const SERIES_COLORS = ["var(--fl-text)", "var(--pk-accent)", "var(--pk-s2)", "var(--pk-s3)", "var(--pk-s4)", "var(--pk-s5)"];

export interface Series {
  label: string;
  data: number[];
  color?: string;
}

/**
 * The calm line chart: one shared scale, a few hairline gridlines with their
 * values, the first series in the text colour and the rest in quiet colours,
 * a legend under it when there is more than one line. `tone` colours a single
 * line green or red by how it ended.
 */
export function LineChart({
  series,
  height = 180,
  label,
  format = (v: number) => v.toLocaleString("en-US", { maximumFractionDigits: 2 }),
  tone,
  empty = "The chart fills in as new data arrives.",
}: {
  series: Series[];
  height?: number;
  label: string;
  format?: (v: number) => string;
  tone?: ChangeTone;
  empty?: string;
}) {
  const d = domainOf(series.map((s) => s.data));
  const len = Math.max(2, ...series.map((s) => s.data.length));
  if (!d || series.every((s) => s.data.filter(Number.isFinite).length < 2)) {
    return (
      <div style={{ height }} className="fl-surface-2 fl-muted flex items-center justify-center rounded-xl px-4 text-center text-sm">
        {empty}
      </div>
    );
  }
  const w = 600;
  const ticks = ticksOf(d, 3);
  const single = series.length === 1;
  const colorOf = (s: Series, i: number) =>
    s.color ?? (single && tone ? (tone === "up" ? "var(--fl-up)" : tone === "down" ? "var(--fl-down)" : "var(--fl-text)") : SERIES_COLORS[i % SERIES_COLORS.length]);
  return (
    <figure className="min-w-0">
      <div className="relative" style={{ height }}>
        <svg viewBox={`0 0 ${w} ${height}`} preserveAspectRatio="none" width="100%" height={height} role="img" aria-label={label} className="block overflow-visible">
          {ticks.map((t) => (
            <line key={t} x1={0} x2={w} y1={yOf(t, d, height)} y2={yOf(t, d, height)} stroke="var(--fl-line)" strokeWidth={1} vectorEffect="non-scaling-stroke" />
          ))}
          {series.map((s, i) => (
            <path
              key={s.label}
              d={pathOf(s.data, d, w, height, len)}
              fill="none"
              stroke={colorOf(s, i)}
              strokeWidth={i === 0 ? 2 : 1.6}
              strokeLinejoin="round"
              strokeLinecap="round"
              vectorEffect="non-scaling-stroke"
            />
          ))}
        </svg>
        {ticks.map((t) => (
          <span key={t} aria-hidden className="fl-muted fl-num pointer-events-none absolute right-0 -translate-y-full pb-0.5 text-[11px]" style={{ top: yOf(t, d, height) }}>
            {format(t)}
          </span>
        ))}
      </div>
      {!single && (
        <figcaption className="mt-3 flex flex-wrap gap-x-4 gap-y-1.5 text-sm">
          {series.map((s, i) => (
            <span key={s.label} className="inline-flex min-w-0 items-center gap-1.5">
              <span className="inline-block h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: colorOf(s, i) }} aria-hidden />
              <span className="fl-muted truncate">{s.label}</span>
            </span>
          ))}
        </figcaption>
      )}
    </figure>
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
    <div role="radiogroup" aria-label={label} className="flex flex-wrap gap-2">
      {options.map((o) => {
        const on = o.id === value;
        return (
          <button
            key={o.id}
            type="button"
            role="radio"
            aria-checked={on}
            title={o.help}
            onClick={() => onChange(o.id)}
            className={`fl-focus min-h-[36px] rounded-full px-3.5 text-sm font-semibold transition-colors ${on ? "fl-btn-primary" : "fl-surface-2 fl-text"}`}
          >
            {o.label}
            {o.count != null && <span className={`ml-1.5 ${on ? "" : "fl-muted"}`}>{o.count}</span>}
          </button>
        );
      })}
    </div>
  );
}

/** An on/off switch with its label and one line of explanation. */
export function SwitchRow({
  label,
  hint,
  on,
  onChange,
  disabled,
}: {
  label: string;
  hint?: ReactNode;
  on: boolean;
  onChange: (v: boolean) => void;
  disabled?: boolean;
}) {
  const id = useId();
  return (
    <div className="flex items-start justify-between gap-4 py-3">
      <div className="min-w-0 flex-1">
        <div id={id} className="text-[15px] font-semibold">
          {label}
        </div>
        {hint && <div className="fl-muted mt-0.5 text-sm leading-relaxed">{hint}</div>}
      </div>
      <button type="button" role="switch" aria-checked={on} aria-labelledby={id} disabled={disabled} onClick={() => onChange(!on)} className="pk-switch mt-0.5" />
    </div>
  );
}

/** A labelled input, select or textarea. Wrap the control; use `inputCls` on it. */
export function Field({ label, hint, help, children, className = "" }: { label: string; hint?: ReactNode; help?: string; children: ReactNode; className?: string }) {
  const tip = help ?? explain(label);
  return (
    <label className={`block min-w-0 ${className}`}>
      <span className="fl-muted mb-1 flex items-center gap-1 text-sm font-medium">
        {label}
        {tip && <Explain text={tip} label={label} />}
      </span>
      {children}
      {hint && <span className="fl-muted mt-1 block text-xs leading-snug">{hint}</span>}
    </label>
  );
}

/** The calm look for inputs, selects and textareas. */
export const inputCls = "fl-input fl-num text-[15px]";

/** Extra detail that most people never need, folded away until asked for. */
export function More({ title, children, defaultOpen = false }: { title: string; children: ReactNode; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  const id = useId();
  return (
    <div>
      <button type="button" aria-expanded={open} aria-controls={id} onClick={() => setOpen((o) => !o)} className="fl-focus flex w-full items-center justify-between gap-2 py-2 text-left text-[15px] font-semibold">
        <span className="min-w-0">{title}</span>
        <ChevronDown size={18} aria-hidden className={`shrink-0 transition-transform ${open ? "rotate-180" : ""}`} />
      </button>
      {open && (
        <div id={id} className="pb-2">
          {children}
        </div>
      )}
    </div>
  );
}

/** Map the old six-colour tones to the calm chip tones. */
export function chipTone(t: "cyan" | "purple" | "green" | "red" | "amber" | "neutral"): ChipTone {
  return t === "green" ? "good" : t === "red" ? "bad" : t === "amber" ? "warn" : "neutral";
}

export { Explain, Term } from "../components/ui";

/**
 * Gross, costs and net as three rows, with the 40 % cost warning under them.
 * `fmt` renders one amount: dollars by default, or e.g. percent of capital.
 */
export function CostLines({ pnl, fmt = (n: number) => usd(n) }: { pnl: PnlBreakdown; fmt?: (n: number) => string }) {
  const warn = costWarning(pnl);
  return (
    <div>
      <Rows>
        <Row label="Before costs" sub="What the trades made at the quoted price" value={fmt(pnl.gross)} tone={toneOf(pnl.gross)} help="Gross: before fees, spread and market impact." />
        <Row label="Costs" sub="Fees and slippage" value={pnl.costs > 0 ? `−${fmt(pnl.costs)}` : fmt(0)} tone={pnl.costs > 0 ? "warn" : "plain"} help="What trading cost: exchange fees, the spread and price impact." />
        <Row label="What you keep" sub="After every cost" value={fmt(pnl.net)} tone={toneOf(pnl.net)} help="Net: the result after all costs." />
      </Rows>
      {warn && (
        <div className="mt-2">
          <Note tone="warn">{warn}</Note>
        </div>
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
  icon,
  disabled,
}: {
  children: ReactNode;
  title?: string;
  question: ReactNode;
  confirmLabel: string;
  onConfirm: () => void;
  danger?: boolean;
  variant?: "primary" | "secondary" | "danger" | "ghost";
  icon?: LucideIcon;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const close = useCallback(() => setOpen(false), []);
  return (
    <>
      <FlowButton variant={variant ?? (danger ? "danger" : "secondary")} icon={icon} disabled={disabled} onClick={() => setOpen(true)}>
        {children}
      </FlowButton>
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
    <div role="status" className="fl-surface-2 flex items-center justify-between gap-3 rounded-2xl px-4 py-3 text-sm">
      <span className="min-w-0">{notice.message}</span>
      <FlowButton
        variant="secondary"
        onClick={() => {
          notice.undo();
          setNotice(null);
        }}
      >
        Undo
      </FlowButton>
    </div>
  ) : null;
  return [el, (message, undo) => setNotice({ message, undo })];
}
