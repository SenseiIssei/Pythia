import { HelpCircle, Info, Loader2, type LucideIcon } from "lucide-react";
import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { explain } from "../glossary";
import { Notice as DsNotice, type NoticeTone } from "../design/primitives/feedback";
import { Sparkline as DsSparkline, LineChart, type ChartTone } from "../design/primitives/charts";
import { Toggle as DsToggle } from "../design/primitives/controls";

// ── the shared UI kit, in the calm design system's look ─────────────────────
//
// Older pages still build on these. Their APIs stay as they were, but every
// colour now comes from the design tokens (src/design/tokens.ts), so they
// follow light and dark mode. New code should prefer src/design.
//
// Colour carries meaning and nothing else: green is up or good, red is down or
// dangerous, amber asks for caution. The one accent marks links, selection and
// research. Plain numbers are plain ink.

export type Tone = "cyan" | "purple" | "green" | "red" | "amber" | "neutral";

/** Shared look for every text input, select and textarea. */
export { inputCls } from "../design/primitives/controls";

const TEXT: Record<Tone, string> = {
  cyan: "text-ink",
  purple: "text-accent",
  green: "text-up",
  red: "text-down",
  amber: "text-warn",
  neutral: "text-ink",
};

/**
 * A small "?" that explains something in one plain sentence, on hover, on
 * keyboard focus and on tap. The bubble is portalled to the page body and kept
 * inside the viewport, so it never causes sideways scrolling on a phone and is
 * never clipped by a card.
 */
export function Explain({ text, label }: { text: string; label?: string }) {
  const ref = useRef<HTMLButtonElement>(null);
  const id = useId();
  const [pos, setPos] = useState<{ left: number; top: number; width: number; above: boolean } | null>(null);

  function place() {
    const r = ref.current?.getBoundingClientRect();
    // Gone (a hidden page has a zero-size box) or scrolled off screen: no bubble.
    if (!r || (r.width === 0 && r.height === 0) || r.bottom < 0 || r.top > window.innerHeight) return null;
    const width = Math.min(260, window.innerWidth - 16);
    const left = Math.max(8, Math.min(r.left + r.width / 2 - width / 2, window.innerWidth - width - 8));
    const above = r.bottom + 140 > window.innerHeight;
    return { left, top: above ? r.top - 6 : r.bottom + 6, width, above };
  }
  const show = () => setPos(place());
  const hide = () => setPos(null);
  const open = pos !== null;

  // Follow the "?" when the page scrolls or resizes (focusing it can scroll
  // it into view), and let go once it leaves the screen.
  useEffect(() => {
    if (!open) return;
    // Only ever moves an open bubble; a scroll that lands after a close must
    // not bring it back.
    const follow = () => setPos((p) => (p ? place() : null));
    // Some phones never focus a tapped button, so a tap elsewhere closes it too.
    const outside = (e: PointerEvent) => {
      if (!ref.current?.contains(e.target as Node)) setPos(null);
    };
    window.addEventListener("scroll", follow, true);
    window.addEventListener("resize", follow);
    document.addEventListener("pointerdown", outside);
    return () => {
      window.removeEventListener("scroll", follow, true);
      window.removeEventListener("resize", follow);
      document.removeEventListener("pointerdown", outside);
    };
  }, [open]);

  return (
    <>
      <button
        ref={ref}
        type="button"
        aria-label={label ? `What does "${label}" mean?` : "What does this mean?"}
        aria-describedby={pos ? id : undefined}
        onMouseEnter={show}
        onMouseLeave={hide}
        onFocus={show}
        onBlur={hide}
        onClick={(e) => {
          // A tap focuses and then clicks; both must open, never toggle shut.
          // Tapping anywhere else blurs the button and closes the bubble.
          e.stopPropagation();
          e.preventDefault();
          show();
        }}
        onKeyDown={(e) => e.key === "Escape" && hide()}
        className="inline-flex shrink-0 cursor-help items-center rounded-full align-middle text-faint normal-case transition-colors hover:text-ink focus-visible:text-ink"
      >
        <HelpCircle size={13} aria-hidden />
      </button>
      {pos &&
        createPortal(
          <span
            role="tooltip"
            id={id}
            style={{
              position: "fixed",
              left: pos.left,
              top: pos.top,
              width: pos.width,
              transform: pos.above ? "translateY(-100%)" : undefined,
            }}
            className="pointer-events-none z-[100] rounded-xl bg-primary px-3 py-2 font-sans text-[13px] font-normal normal-case leading-relaxed tracking-normal text-on-primary shadow-pop"
          >
            {text}
          </span>,
          document.body,
        )}
    </>
  );
}

/**
 * A word with its glossary explanation next to it. Falls back to the plain word
 * when the glossary has nothing, so it is safe to use on any label.
 */
export function Term({ children, k, text }: { children: ReactNode; k?: string; text?: string }) {
  const key = k ?? (typeof children === "string" ? children : undefined);
  const tip = text ?? (key ? explain(key) : undefined);
  if (!tip) return <>{children}</>;
  return (
    <span className="inline-flex items-center gap-1">
      {children}
      <Explain text={tip} label={key} />
    </span>
  );
}

const BUTTON: Record<Tone, string> = {
  cyan: "bg-primary text-on-primary hover:opacity-90",
  purple: "bg-accent/10 text-accent hover:bg-accent/15",
  green: "bg-up/10 text-up hover:bg-up/15",
  red: "bg-down/10 text-down hover:bg-down/15",
  amber: "bg-warn/10 text-warn hover:bg-warn/15",
  neutral: "bg-surface-2 text-ink hover:bg-line",
};

export function Button({
  children,
  onClick,
  tone = "cyan",
  disabled,
  icon: Icon,
  className = "",
  size = "md",
  title,
  ariaLabel,
}: {
  children: ReactNode;
  onClick?: () => void;
  tone?: Tone;
  disabled?: boolean;
  icon?: LucideIcon;
  className?: string;
  size?: "sm" | "md";
  title?: string;
  ariaLabel?: string;
}) {
  const sizing = size === "sm" ? "min-h-[32px] gap-1.5 px-3 text-[13px]" : "min-h-[40px] gap-2 px-4 text-sm";
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={title}
      aria-label={ariaLabel}
      className={`inline-flex items-center justify-center rounded-full font-semibold transition-[opacity,background-color] active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-40 ${sizing} ${BUTTON[tone]} ${className}`}
    >
      {Icon && <Icon size={size === "sm" ? 14 : 16} aria-hidden className="shrink-0" />}
      {children}
    </button>
  );
}

export function Card({
  title,
  subtitle,
  help,
  icon: Icon,
  children,
  className = "",
  right,
}: {
  title?: string;
  subtitle?: ReactNode;
  /** One plain sentence for the "?" next to the title. Defaults to the glossary entry. */
  help?: string;
  icon?: LucideIcon;
  children: ReactNode;
  className?: string;
  right?: ReactNode;
}) {
  const tip = help ?? (title ? explain(title) : undefined);
  return (
    <section className={`rounded-card border border-line bg-surface p-5 ${className}`}>
      {(title || right) && (
        <div className="mb-4 flex flex-wrap items-start justify-between gap-x-3 gap-y-2">
          {title && (
            <div className="min-w-0 flex-1">
              <h2 className="flex items-center gap-2 text-[17px] font-semibold tracking-tight text-ink">
                {Icon && <Icon size={17} aria-hidden className="shrink-0 text-muted" />}
                <span className="min-w-0">{title}</span>
                {tip && <Explain text={tip} label={title} />}
              </h2>
              {subtitle && <p className="mt-1 text-[13px] leading-relaxed text-muted">{subtitle}</p>}
            </div>
          )}
          {right && <div className="flex shrink-0 flex-wrap items-center gap-2">{right}</div>}
        </div>
      )}
      {children}
    </section>
  );
}

export function StatCard({
  label,
  value,
  icon: Icon,
  tone = "neutral",
  delay: _delay = 0,
  sub,
  help,
}: {
  label: string;
  value: ReactNode;
  icon: LucideIcon;
  tone?: Tone;
  /** Kept for older callers; cards no longer animate in. */
  delay?: number;
  sub?: ReactNode;
  /** Overrides the glossary entry for this label. */
  help?: string;
}) {
  const tip = help ?? explain(label);
  return (
    <div className="min-w-0 rounded-card border border-line bg-surface p-5">
      <div className="flex items-center gap-1.5 text-muted">
        <Icon size={15} aria-hidden className="shrink-0 text-faint" />
        <span className="min-w-0 text-[13px] font-medium leading-tight">{label}</span>
        {tip && <Explain text={tip} label={label} />}
      </div>
      <div className={`mt-2 break-words font-mono text-2xl font-bold tracking-tight tabular-nums ${TEXT[tone]}`}>{value}</div>
      {sub && <div className="mt-1 text-[13px] text-muted">{sub}</div>}
    </div>
  );
}

export function PageHeader({ title, subtitle, right }: { title: string; subtitle?: ReactNode; right?: ReactNode }) {
  return (
    <header className="mb-6 flex flex-wrap items-end justify-between gap-3 pt-1">
      <div className="min-w-0">
        <h1 className="text-[28px] font-bold leading-tight tracking-tight text-ink">{title}</h1>
        {subtitle && <p className="mt-1 max-w-2xl text-[15px] leading-relaxed text-muted">{subtitle}</p>}
      </div>
      {right && <div className="flex shrink-0 flex-wrap items-center gap-2">{right}</div>}
    </header>
  );
}

export function Toggle({
  on,
  onChange,
  label,
  disabled,
}: {
  on: boolean;
  onChange: (v: boolean) => void;
  /** What the switch controls, for screen readers. */
  label?: string;
  disabled?: boolean;
}) {
  return <DsToggle on={on} onChange={onChange} label={label} disabled={disabled} />;
}

export function Badge({ tone, children, title }: { tone: Tone; children: ReactNode; title?: string }) {
  const map: Record<Tone, string> = {
    cyan: "bg-accent/10 text-accent",
    purple: "bg-accent/10 text-accent",
    green: "bg-up/10 text-up",
    red: "bg-down/10 text-down",
    amber: "bg-warn/10 text-warn",
    neutral: "bg-surface-2 text-muted",
  };
  return (
    <span title={title} className={`inline-flex items-center whitespace-nowrap rounded-full px-2 py-0.5 text-[11px] font-semibold ${map[tone]}`}>
      {children}
    </span>
  );
}

export function Meter({ pct, tone = "cyan", label }: { pct: number; tone?: Tone; label?: string }) {
  const clamped = Math.max(0, Math.min(100, Number.isFinite(pct) ? pct : 0));
  const bar: Record<Tone, string> = {
    cyan: "bg-ink",
    purple: "bg-accent",
    green: "bg-up",
    red: "bg-down",
    amber: "bg-warn",
    neutral: "bg-muted",
  };
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(clamped)}
      className="h-1.5 w-full overflow-hidden rounded-full bg-surface-2"
    >
      <div className={`h-full rounded-full transition-[width] duration-500 ${bar[tone]}`} style={{ width: `${clamped}%` }} />
    </div>
  );
}

/**
 * A boxed message. `info` explains, `success` reassures, `warning` asks for
 * care, `danger` is about real money or something broken.
 */
export function Notice(props: {
  tone?: NoticeTone;
  title?: ReactNode;
  icon?: LucideIcon;
  children?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return <DsNotice {...props} />;
}

/** What a section says when there is nothing to show yet, and what to do about it. */
export function EmptyState({
  icon: Icon = Info,
  title,
  children,
  action,
  compact,
}: {
  icon?: LucideIcon;
  title: ReactNode;
  children?: ReactNode;
  action?: ReactNode;
  compact?: boolean;
}) {
  return (
    <div className={`flex flex-col items-center text-center ${compact ? "gap-1.5 py-5" : "gap-2 py-10"}`}>
      <div className={`flex items-center justify-center rounded-full bg-surface-2 text-ink ${compact ? "h-10 w-10" : "h-12 w-12"}`}>
        <Icon size={compact ? 17 : 21} aria-hidden />
      </div>
      <div className="mt-1 text-[15px] font-semibold text-ink">{title}</div>
      {children && <div className="max-w-md text-[13px] leading-relaxed text-muted">{children}</div>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}

/** A quiet spinner with words, for anything that has to wait for an answer. */
export function Loading({ children = "Loading" }: { children?: ReactNode }) {
  return (
    <div role="status" className="flex items-center gap-2 py-3 text-sm text-muted">
      <Loader2 size={15} aria-hidden className="animate-spin" />
      {children}
    </div>
  );
}

/** A labelled control. The label wraps the control, so clicking it focuses the input. */
export function Field({
  label,
  hint,
  help,
  children,
  className = "",
}: {
  label: string;
  hint?: ReactNode;
  help?: string;
  children: ReactNode;
  className?: string;
}) {
  const tip = help ?? explain(label);
  return (
    <label className={`block min-w-0 ${className}`}>
      <span className="mb-1.5 flex items-center gap-1 text-[13px] font-medium text-muted">
        {label}
        {tip && <Explain text={tip} label={label} />}
      </span>
      {children}
      {hint && <span className="mt-1.5 block text-[12px] leading-snug text-faint">{hint}</span>}
    </label>
  );
}

/** A label above a number, for small read-outs inside a card. */
export function Readout({
  label,
  value,
  tone = "neutral",
  help,
}: {
  label: string;
  value: ReactNode;
  tone?: Tone;
  help?: string;
}) {
  const tip = help ?? explain(label);
  return (
    <div className="min-w-0">
      <div className="flex items-center gap-1 text-[12px] font-medium text-muted">
        <span className="truncate">{label}</span>
        {tip && <Explain text={tip} label={label} />}
      </div>
      <div className={`font-mono text-[15px] font-semibold tabular-nums ${TEXT[tone]}`}>{value}</div>
    </div>
  );
}

const CHART_TONE: Record<Tone, ChartTone> = {
  green: "up",
  red: "down",
  purple: "accent",
  cyan: "up",
  amber: "accent",
  neutral: "flat",
};

/** A small chart: green when it ended up, red when down, unless a tone says otherwise. */
export function Sparkline({
  data,
  tone = "cyan",
  height = 48,
  label,
}: {
  data: number[];
  tone?: Tone;
  height?: number;
  /** Describes the chart for screen readers. */
  label?: string;
}) {
  if (data.length < 2) {
    return (
      <div style={{ height }} className="flex items-center justify-center rounded-xl bg-surface-2 text-[13px] text-muted">
        The chart fills in as new prices arrive.
      </div>
    );
  }
  const up = data[data.length - 1] >= data[0];
  return <DsSparkline data={data} tone={up ? CHART_TONE[tone] : "down"} height={height} label={label} fill />;
}

/** Several lines on one scale, with a legend. */
export function MultiLineChart({ series, height = 200 }: { series: { label: string; data: number[]; color?: string }[]; height?: number }) {
  return <LineChart series={series} height={height} />;
}

/** Green when up, red when down, plain when it has not moved. */
export function pnlTone(n: number, epsilon = 0.005): Tone {
  return n > epsilon ? "green" : n < -epsilon ? "red" : "neutral";
}

export function fmtUsd(n: number, dp = 2): string {
  const sign = n < 0 ? "-" : "";
  return `${sign}$${Math.abs(n).toLocaleString("en-US", { minimumFractionDigits: dp, maximumFractionDigits: dp })}`;
}

export function fmtPct(n: number, dp = 1): string {
  return `${n >= 0 ? "+" : ""}${(n * 100).toFixed(dp)}%`;
}
