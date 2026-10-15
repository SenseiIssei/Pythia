// Stand-in primitives for the redesigned flows, named like the shared design
// system (Card, ListRow, BigNumber, Change, Chip, Segmented, Sheet, Empty,
// Skeleton) so a later swap is an import change. Only tokens from
// ./flows.css; no colours of their own.

import { useEffect, useId, useRef, type ReactNode } from "react";
import { ArrowDownRight, ArrowUpRight, Minus, X, type LucideIcon } from "lucide-react";
import "./flows.css";

export type ChangeTone = "up" | "down" | "flat";

const MINUS = "−";

export function money(n: number, dp = 2): string {
  if (!Number.isFinite(n)) return "n/a";
  return n.toLocaleString("en-US", { style: "currency", currency: "USD", minimumFractionDigits: dp, maximumFractionDigits: dp });
}

/** "+$12.34", "−$5.00", "$0.00". */
export function signedMoney(n: number, dp = 2): string {
  if (!Number.isFinite(n)) return "n/a";
  const abs = money(Math.abs(n), dp);
  if (Number(Math.abs(n).toFixed(dp)) === 0) return money(0, dp);
  return `${n < 0 ? MINUS : "+"}${abs}`;
}

/** "+1.23%", "−0.40%", "0.00%". */
export function signedPct(n: number | null | undefined, dp = 2): string {
  if (n == null || !Number.isFinite(n)) return "n/a";
  const abs = Math.abs(n).toFixed(dp);
  if (Number(abs) === 0) return `${(0).toFixed(dp)}%`;
  return `${n < 0 ? MINUS : "+"}${abs}%`;
}

/** The page frame: the flows' background, a narrow centred column. */
export function Page({ title, subtitle, right, children }: { title: string; subtitle?: ReactNode; right?: ReactNode; children: ReactNode }) {
  return (
    <div className="fl fl-page -mx-4 -mb-10 -mt-5 min-h-full px-4 pb-24 pt-5 sm:-mx-6 sm:-mt-6 sm:px-6 sm:pt-6">
      <div className="mx-auto w-full max-w-xl space-y-4">
        <header className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h1 className="text-[28px] font-bold leading-tight tracking-tight">{title}</h1>
            {subtitle && <p className="fl-muted mt-1 text-sm">{subtitle}</p>}
          </div>
          {right && <div className="shrink-0">{right}</div>}
        </header>
        {children}
      </div>
    </div>
  );
}

export function Card({ children, className = "", as: As = "section", label }: { children: ReactNode; className?: string; as?: "section" | "div" | "article"; label?: string }) {
  return (
    <As aria-label={label} className={`fl-card p-4 ${className}`}>
      {children}
    </As>
  );
}

export function SectionTitle({ children, right }: { children: ReactNode; right?: ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-2 px-1 pt-2">
      <h2 className="text-lg font-semibold tracking-tight">{children}</h2>
      {right}
    </div>
  );
}

/** A big amount, the way the eye reads it first. */
export function BigNumber({ value, label, size = "lg" }: { value: string; label?: string; size?: "md" | "lg" }) {
  return (
    <div className="min-w-0">
      {label && <div className="fl-muted text-sm">{label}</div>}
      <div className={`fl-num break-words font-bold leading-tight tracking-tight ${size === "lg" ? "text-[34px]" : "text-2xl"}`}>{value}</div>
    </div>
  );
}

/** A signed change in green or red, with an arrow so it never relies on colour alone. */
export function Change({ usd, pct, tone, size = "md" }: { usd?: number | null; pct?: number | null; tone: ChangeTone; size?: "sm" | "md" }) {
  const Icon = tone === "up" ? ArrowUpRight : tone === "down" ? ArrowDownRight : Minus;
  const cls = tone === "up" ? "fl-up" : tone === "down" ? "fl-down" : "fl-muted";
  const word = tone === "up" ? "up" : tone === "down" ? "down" : "unchanged";
  return (
    <span className={`${cls} fl-num inline-flex flex-wrap items-center gap-x-1 font-semibold ${size === "sm" ? "text-sm" : "text-base"}`}>
      <Icon size={size === "sm" ? 14 : 16} aria-hidden className="shrink-0" />
      <span className="sr-only">{word}</span>
      {usd != null && <span>{signedMoney(usd)}</span>}
      {pct != null && <span>{usd != null ? `(${signedPct(pct)})` : signedPct(pct)}</span>}
    </span>
  );
}

export type ChipTone = "neutral" | "good" | "warn" | "bad";

export function Chip({ children, tone = "neutral", title }: { children: ReactNode; tone?: ChipTone; title?: string }) {
  const color = tone === "good" ? "fl-up" : tone === "bad" ? "fl-down" : tone === "warn" ? "fl-warn" : "fl-muted";
  return (
    <span title={title} className={`fl-surface-2 ${color} inline-flex max-w-full items-center gap-1 truncate rounded-full px-2.5 py-0.5 text-xs font-semibold`}>
      {children}
    </span>
  );
}

/** One simple row: icon, title and a line under it, an amount on the right. */
export function ListRow({
  icon: Icon,
  title,
  subtitle,
  right,
  rightSub,
  onClick,
}: {
  icon?: LucideIcon;
  title: ReactNode;
  subtitle?: ReactNode;
  right?: ReactNode;
  rightSub?: ReactNode;
  onClick?: () => void;
}) {
  const body = (
    <>
      {Icon && (
        <span className="fl-surface-2 flex h-10 w-10 shrink-0 items-center justify-center rounded-full" aria-hidden>
          <Icon size={18} />
        </span>
      )}
      <span className="min-w-0 flex-1 text-left">
        <span className="block truncate text-[15px] font-semibold">{title}</span>
        {subtitle && <span className="fl-muted block break-words text-sm">{subtitle}</span>}
      </span>
      {(right || rightSub) && (
        <span className="shrink-0 text-right">
          {right && <span className="fl-num block text-[15px] font-semibold">{right}</span>}
          {rightSub && <span className="block text-sm">{rightSub}</span>}
        </span>
      )}
    </>
  );
  return onClick ? (
    <button type="button" onClick={onClick} className="fl-focus flex w-full items-center gap-3 py-3">
      {body}
    </button>
  ) : (
    <div className="flex w-full items-center gap-3 py-3">{body}</div>
  );
}

export interface SegOption<T extends string> {
  id: T;
  label: string;
}

export function Segmented<T extends string>({
  options,
  value,
  onChange,
  label,
}: {
  options: SegOption<T>[];
  value: T;
  onChange: (v: T) => void;
  label: string;
}) {
  return (
    <div role="radiogroup" aria-label={label} className="fl-surface-2 grid gap-1 rounded-full p-1" style={{ gridTemplateColumns: `repeat(${options.length}, minmax(0, 1fr))` }}>
      {options.map((o) => {
        const on = o.id === value;
        return (
          <button
            key={o.id}
            type="button"
            role="radio"
            aria-checked={on}
            onClick={() => onChange(o.id)}
            className={`fl-focus min-h-[36px] truncate rounded-full px-2 text-sm font-semibold transition-colors ${on ? "fl-card shadow-sm" : "fl-muted"}`}
            style={on ? { borderRadius: 999 } : undefined}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

export function Button({
  children,
  onClick,
  variant = "primary",
  disabled,
  full,
  type = "button",
  icon: Icon,
}: {
  children: ReactNode;
  onClick?: () => void;
  variant?: "primary" | "secondary" | "danger" | "ghost";
  disabled?: boolean;
  full?: boolean;
  type?: "button" | "submit";
  icon?: LucideIcon;
}) {
  return (
    <button type={type} onClick={onClick} disabled={disabled} className={`fl-btn fl-btn-${variant} ${full ? "w-full" : ""}`}>
      {Icon && <Icon size={16} aria-hidden />}
      {children}
    </button>
  );
}

/**
 * A sheet: slides up from the bottom on a phone, a centred dialog on a wide
 * screen. Escape and the scrim close it.
 */
export function Sheet({
  open,
  onClose,
  title,
  children,
  footer,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  footer?: ReactNode;
}) {
  const id = useId();
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const prev = document.activeElement as HTMLElement | null;
    ref.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      prev?.focus?.();
    };
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fl fixed inset-0 z-50 flex items-end justify-center sm:items-center">
      <div className="fl-scrim absolute inset-0" onClick={onClose} aria-hidden />
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-labelledby={id}
        tabIndex={-1}
        className="fl-sheet relative flex max-h-[92vh] w-full flex-col rounded-t-3xl outline-none sm:max-w-md sm:rounded-3xl"
      >
        <div className="flex items-center justify-between gap-2 px-5 pb-2 pt-5">
          <h2 id={id} className="text-xl font-bold tracking-tight">
            {title}
          </h2>
          <button type="button" onClick={onClose} aria-label="Close" className="fl-focus fl-surface-2 rounded-full p-2">
            <X size={16} aria-hidden />
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-5 pb-4">{children}</div>
        {footer && <div className="fl-line border-t px-5 pb-5 pt-3">{footer}</div>}
      </div>
    </div>
  );
}

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
      <div className="fl-muted text-[15px]">{body}</div>
      {children}
      {error && (
        <p role="alert" className="fl-down mt-3 text-sm">
          {error}
        </p>
      )}
    </Sheet>
  );
}

export function Empty({ icon: Icon, title, children, action }: { icon?: LucideIcon; title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center px-4 py-10 text-center">
      {Icon && (
        <span className="fl-surface-2 mb-3 flex h-14 w-14 items-center justify-center rounded-full" aria-hidden>
          <Icon size={24} />
        </span>
      )}
      <h3 className="text-lg font-semibold">{title}</h3>
      {children && <p className="fl-muted mt-1 max-w-sm text-sm">{children}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function Skeleton({ className = "h-4 w-full" }: { className?: string }) {
  return <div className={`fl-skeleton ${className}`} aria-hidden />;
}

/** A small line chart, green when it ended up, red when down. */
export function MiniChart({ data, tone, height = 56, label }: { data: number[]; tone: ChangeTone; height?: number; label: string }) {
  const pts = data.filter((v) => Number.isFinite(v));
  if (pts.length < 2) return <div style={{ height }} className="fl-surface-2 rounded-lg" role="img" aria-label={`${label}: not enough points yet`} />;
  const w = 300;
  const min = Math.min(...pts);
  const max = Math.max(...pts);
  const span = max - min || 1;
  const d = pts
    .map((v, i) => `${i === 0 ? "M" : "L"}${((i / (pts.length - 1)) * w).toFixed(1)},${(height - 2 - ((v - min) / span) * (height - 4)).toFixed(1)}`)
    .join(" ");
  const stroke = tone === "down" ? "var(--fl-down)" : tone === "up" ? "var(--fl-up)" : "var(--fl-muted)";
  return (
    <svg viewBox={`0 0 ${w} ${height}`} preserveAspectRatio="none" width="100%" height={height} role="img" aria-label={label}>
      <path d={d} fill="none" stroke={stroke} strokeWidth={2} vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
    </svg>
  );
}
