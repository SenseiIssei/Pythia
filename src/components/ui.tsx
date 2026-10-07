import { motion } from "framer-motion";
import {
  CheckCircle2,
  HelpCircle,
  Info,
  Loader2,
  ShieldAlert,
  TriangleAlert,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { explain } from "../glossary";

// ── shared neon UI kit ──────────────────────────────────────────────────────
//
// Colour carries meaning and nothing else: green is good, red is bad or
// dangerous, amber asks for caution. Cyan is the accent for headings and
// controls, purple marks research and AI. Plain numbers are plain white.

export type Tone = "cyan" | "purple" | "green" | "red" | "amber" | "neutral";

/** Shared look for every text input, select and textarea. */
export const inputCls =
  "w-full min-w-0 rounded-md border border-cyber-border-bright bg-cyber-bg/60 px-2.5 py-1.5 text-sm text-cyber-text placeholder:text-cyber-text-faint transition-colors hover:border-cyber-text-faint focus:border-accent focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/30 disabled:cursor-not-allowed disabled:opacity-50";

const TEXT: Record<Tone, string> = {
  cyan: "text-accent",
  purple: "text-purple-neon",
  green: "text-success",
  red: "text-danger",
  amber: "text-warning",
  neutral: "text-cyber-text",
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

  function show() {
    const r = ref.current?.getBoundingClientRect();
    if (!r) return;
    const width = Math.min(260, window.innerWidth - 16);
    const left = Math.max(8, Math.min(r.left + r.width / 2 - width / 2, window.innerWidth - width - 8));
    const above = r.bottom + 140 > window.innerHeight;
    setPos({ left, top: above ? r.top - 6 : r.bottom + 6, width, above });
  }
  const hide = () => setPos(null);

  useEffect(() => {
    if (!pos) return;
    const close = () => setPos(null);
    window.addEventListener("scroll", close, true);
    window.addEventListener("resize", close);
    return () => {
      window.removeEventListener("scroll", close, true);
      window.removeEventListener("resize", close);
    };
  }, [pos]);

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
          e.stopPropagation();
          e.preventDefault();
          if (pos) hide();
          else show();
        }}
        onKeyDown={(e) => e.key === "Escape" && hide()}
        className="inline-flex shrink-0 cursor-help items-center rounded-full align-middle text-cyber-text-faint normal-case transition-colors hover:text-accent focus-visible:text-accent"
      >
        <HelpCircle size={12} aria-hidden />
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
            className="pointer-events-none z-[100] rounded-lg border border-cyber-border-bright bg-cyber-surface-2 px-3 py-2 font-sans text-xs normal-case leading-relaxed tracking-normal text-cyber-text shadow-xl shadow-black/50"
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
  cyan: "bg-accent/10 border-accent/35 text-accent hover:bg-accent/20 hover:border-accent/60",
  purple: "bg-purple-neon/10 border-purple-neon/35 text-purple-neon hover:bg-purple-neon/20 hover:border-purple-neon/60",
  green: "bg-success/10 border-success/35 text-success hover:bg-success/20 hover:border-success/60",
  red: "bg-danger/10 border-danger/35 text-danger hover:bg-danger/20 hover:border-danger/60",
  amber: "bg-warning/10 border-warning/35 text-warning hover:bg-warning/20 hover:border-warning/60",
  neutral: "bg-cyber-surface-2 border-cyber-border-bright text-cyber-text hover:bg-cyber-border-bright",
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
  const sizing = size === "sm" ? "gap-1.5 px-2.5 py-1 text-xs" : "gap-2 px-3 py-1.5 text-sm";
  return (
    <motion.button
      type="button"
      whileHover={disabled ? undefined : { scale: 1.02 }}
      whileTap={disabled ? undefined : { scale: 0.98 }}
      onClick={onClick}
      disabled={disabled}
      title={title}
      aria-label={ariaLabel}
      className={`inline-flex items-center justify-center rounded-lg border font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${sizing} ${BUTTON[tone]} ${className}`}
    >
      {Icon && <Icon size={size === "sm" ? 13 : 15} aria-hidden />}
      {children}
    </motion.button>
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
    <section className={`rounded-xl border border-cyber-border bg-cyber-surface p-4 sm:p-5 ${className}`}>
      {(title || right) && (
        <div className="mb-3 flex flex-wrap items-start justify-between gap-x-3 gap-y-2">
          {title && (
            <div className="min-w-0 flex-1">
              <h2 className="flex items-center gap-1.5 font-mono text-sm font-bold text-accent">
                {Icon && <Icon size={15} aria-hidden className="shrink-0" />}
                <span className="min-w-0">{title}</span>
                {tip && <Explain text={tip} label={title} />}
              </h2>
              {subtitle && <p className="mt-1 text-xs leading-relaxed text-cyber-text-dim">{subtitle}</p>}
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
  delay = 0,
  sub,
  help,
}: {
  label: string;
  value: ReactNode;
  icon: LucideIcon;
  tone?: Tone;
  delay?: number;
  sub?: ReactNode;
  /** Overrides the glossary entry for this label. */
  help?: string;
}) {
  const tip = help ?? explain(label);
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay }}
      className="min-w-0 rounded-xl border border-cyber-border bg-cyber-surface p-4"
    >
      <div className="flex items-center gap-1.5 text-cyber-text-dim">
        <Icon size={14} aria-hidden className={`shrink-0 ${tone === "neutral" ? "text-cyber-text-faint" : TEXT[tone]}`} />
        <span className="min-w-0 truncate text-[11px] font-medium uppercase tracking-wider">{label}</span>
        {tip && <Explain text={tip} label={label} />}
      </div>
      <div className={`mt-2 break-words font-mono text-xl font-bold tabular-nums sm:text-2xl ${TEXT[tone]}`}>{value}</div>
      {sub && <div className="mt-1 text-xs text-cyber-text-faint">{sub}</div>}
    </motion.div>
  );
}

export function PageHeader({ title, subtitle, right }: { title: string; subtitle?: ReactNode; right?: ReactNode }) {
  return (
    <header className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div className="min-w-0">
        <h1 className="font-mono text-xl font-bold tracking-tight text-cyber-text text-glow-cyan sm:text-2xl">{title}</h1>
        {subtitle && <p className="mt-1 max-w-2xl text-sm leading-relaxed text-cyber-text-dim">{subtitle}</p>}
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
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!on)}
      className={`relative h-6 w-11 shrink-0 rounded-full border transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
        on ? "border-accent/50 bg-accent/30" : "border-cyber-border-bright bg-cyber-surface-2"
      }`}
    >
      <motion.span
        layout
        transition={{ type: "spring", stiffness: 500, damping: 30 }}
        className={`absolute top-0.5 h-4 w-4 rounded-full ${on ? "right-0.5 bg-accent" : "left-0.5 bg-cyber-text-faint"}`}
      />
    </button>
  );
}

export function Badge({ tone, children, title }: { tone: Tone; children: ReactNode; title?: string }) {
  const map: Record<Tone, string> = {
    cyan: "border-accent/40 text-accent",
    purple: "border-purple-neon/40 text-purple-neon",
    green: "border-success/40 text-success",
    red: "border-danger/40 text-danger",
    amber: "border-warning/40 text-warning",
    neutral: "border-cyber-border-bright text-cyber-text-dim",
  };
  return (
    <span
      title={title}
      className={`inline-flex items-center whitespace-nowrap rounded-md border px-2 py-0.5 text-[11px] font-medium ${map[tone]}`}
    >
      {children}
    </span>
  );
}

export function Meter({ pct, tone = "cyan", label }: { pct: number; tone?: Tone; label?: string }) {
  const clamped = Math.max(0, Math.min(100, Number.isFinite(pct) ? pct : 0));
  const bar: Record<Tone, string> = {
    cyan: "bg-accent",
    purple: "bg-purple-neon",
    green: "bg-success",
    red: "bg-danger",
    amber: "bg-warning",
    neutral: "bg-cyber-text-dim",
  };
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(clamped)}
      className="h-2 w-full overflow-hidden rounded-full bg-cyber-surface-2"
    >
      <motion.div
        className={`h-full rounded-full ${bar[tone]}`}
        initial={{ width: 0 }}
        animate={{ width: `${clamped}%` }}
        transition={{ duration: 0.4 }}
      />
    </div>
  );
}

/**
 * A boxed message. `info` explains, `success` reassures, `warning` asks for
 * care, `danger` is about real money or something broken.
 */
export function Notice({
  tone = "info",
  title,
  icon,
  children,
  action,
  className = "",
}: {
  tone?: "info" | "success" | "warning" | "danger";
  title?: ReactNode;
  icon?: LucideIcon;
  children?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  const look = {
    info: { box: "border-accent/25 bg-accent/5", text: "text-accent", Icon: Info },
    success: { box: "border-success/35 bg-success/[0.07]", text: "text-success", Icon: CheckCircle2 },
    warning: { box: "border-warning/35 bg-warning/[0.07]", text: "text-warning", Icon: TriangleAlert },
    danger: { box: "border-danger/45 bg-danger/10", text: "text-danger", Icon: ShieldAlert },
  }[tone];
  const Icon = icon ?? look.Icon;
  return (
    <div
      role={tone === "danger" || tone === "warning" ? "alert" : undefined}
      className={`flex flex-wrap items-start gap-3 rounded-xl border px-4 py-3 ${look.box} ${className}`}
    >
      <Icon size={18} aria-hidden className={`mt-0.5 shrink-0 ${look.text}`} />
      <div className="min-w-0 flex-1 text-sm leading-relaxed text-cyber-text-dim">
        {title && <div className={`font-semibold ${look.text}`}>{title}</div>}
        {children}
      </div>
      {action && <div className="flex shrink-0 items-center gap-2 self-center">{action}</div>}
    </div>
  );
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
    <div className={`flex flex-col items-center text-center ${compact ? "gap-1.5 py-4" : "gap-2 py-8"}`}>
      <div className="rounded-full border border-cyber-border-bright bg-cyber-surface-2 p-2.5 text-cyber-text-faint">
        <Icon size={compact ? 16 : 20} aria-hidden />
      </div>
      <div className="text-sm font-medium text-cyber-text">{title}</div>
      {children && <div className="max-w-md text-xs leading-relaxed text-cyber-text-dim">{children}</div>}
      {action && <div className="mt-1">{action}</div>}
    </div>
  );
}

/** A quiet spinner with words, for anything that has to wait for an answer. */
export function Loading({ children = "Loading" }: { children?: ReactNode }) {
  return (
    <div role="status" className="flex items-center gap-2 py-3 text-sm text-cyber-text-dim">
      <Loader2 size={15} aria-hidden className="animate-spin text-accent" />
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
      <span className="mb-1 flex items-center gap-1 text-xs font-medium text-cyber-text-dim">
        {label}
        {tip && <Explain text={tip} label={label} />}
      </span>
      {children}
      {hint && <span className="mt-1 block text-[11px] leading-snug text-cyber-text-faint">{hint}</span>}
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
      <div className="flex items-center gap-1 text-[10px] font-medium uppercase tracking-wider text-cyber-text-faint">
        <span className="truncate">{label}</span>
        {tip && <Explain text={tip} label={label} />}
      </div>
      <div className={`font-mono text-sm font-bold tabular-nums ${TEXT[tone]}`}>{value}</div>
    </div>
  );
}

const STROKE: Record<Tone, string> = {
  green: "#22c55e",
  red: "#ef4444",
  purple: "#a855f7",
  cyan: "#00f0ff",
  amber: "#f59e0b",
  neutral: "#9a9ab2",
};

// tiny inline sparkline / equity curve
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
      <div
        style={{ height }}
        className="flex items-center justify-center rounded-lg border border-dashed border-cyber-border text-xs text-cyber-text-faint"
      >
        The chart fills in as new prices arrive.
      </div>
    );
  }
  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;
  const w = 100;
  const pts = data
    .map((v, i) => {
      const x = (i / (data.length - 1)) * w;
      const y = height - ((v - min) / range) * height;
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(" ");
  const last = data[data.length - 1];
  const first = data[0];
  const up = last >= first;
  return (
    <svg
      viewBox={`0 0 ${w} ${height}`}
      preserveAspectRatio="none"
      className="w-full"
      style={{ height }}
      role="img"
      aria-label={label ?? `Chart, ${up ? "up" : "down"} over the period shown`}
    >
      <polyline
        points={pts}
        fill="none"
        stroke={up ? STROKE[tone] : STROKE.red}
        strokeWidth={1.5}
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}

// Multi-series line chart with grid, shared y-scale and a legend.
const CHART_PALETTE = ["#00f0ff", "#a855f7", "#22c55e", "#f59e0b", "#ef4444", "#38bdf8", "#e879f9", "#84cc16"];

export function MultiLineChart({
  series,
  height = 200,
}: {
  series: { label: string; data: number[]; color?: string }[];
  height?: number;
}) {
  const all = series.flatMap((s) => s.data);
  if (all.length < 2) {
    return (
      <div
        style={{ height }}
        className="flex items-center justify-center rounded-lg border border-dashed border-cyber-border text-xs text-cyber-text-faint"
      >
        The chart fills in as new prices arrive.
      </div>
    );
  }
  const min = Math.min(...all);
  const max = Math.max(...all);
  const range = max - min || 1;
  const w = 100;
  const maxLen = Math.max(...series.map((s) => s.data.length), 2);
  const toPoints = (data: number[]) =>
    data
      .map((v, i) => {
        const x = (i / (maxLen - 1)) * w;
        const y = height - ((v - min) / range) * height;
        return `${x.toFixed(2)},${y.toFixed(2)}`;
      })
      .join(" ");
  return (
    <div>
      <svg
        viewBox={`0 0 ${w} ${height}`}
        preserveAspectRatio="none"
        className="w-full"
        style={{ height }}
        role="img"
        aria-label={`Chart of ${series.map((s) => s.label).join(", ")}`}
      >
        {[0.25, 0.5, 0.75].map((f) => (
          <line key={f} x1="0" x2={w} y1={height * f} y2={height * f} stroke="#1e1e2a" strokeWidth="0.5" vectorEffect="non-scaling-stroke" />
        ))}
        {series.map((s, i) => (
          <polyline key={i} points={toPoints(s.data)} fill="none" stroke={s.color ?? CHART_PALETTE[i % CHART_PALETTE.length]} strokeWidth={1.5} vectorEffect="non-scaling-stroke" />
        ))}
      </svg>
      <div className="mt-2 flex flex-wrap gap-3 text-xs text-cyber-text-dim">
        {series.map((s, i) => (
          <span key={i} className="flex items-center gap-1.5">
            <span className="inline-block h-2 w-2 rounded-full" style={{ background: s.color ?? CHART_PALETTE[i % CHART_PALETTE.length] }} />
            {s.label}
          </span>
        ))}
      </div>
    </div>
  );
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
