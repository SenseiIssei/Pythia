import { useId, useRef, type KeyboardEvent, type ReactNode } from "react";
import type { LucideIcon } from "lucide-react";
import { Chip } from "./data";

export type ButtonVariant = "primary" | "secondary" | "danger" | "ghost" | "accent";

const VARIANT: Record<ButtonVariant, string> = {
  primary: "bg-primary text-on-primary hover:opacity-90",
  secondary: "bg-surface-2 text-ink hover:bg-line",
  danger: "bg-down text-on-down hover:opacity-90",
  ghost: "bg-transparent text-ink hover:bg-surface-2",
  accent: "bg-accent text-on-accent hover:opacity-90",
};

/** A pill button. Primary is ink on paper; there is at most one per screen. */
export function Button({
  children,
  onClick,
  variant = "primary",
  disabled,
  full,
  type = "button",
  icon: Icon,
  size = "md",
  className = "",
  ariaLabel,
  title,
}: {
  children: ReactNode;
  onClick?: () => void;
  variant?: ButtonVariant;
  disabled?: boolean;
  full?: boolean;
  type?: "button" | "submit";
  icon?: LucideIcon;
  size?: "sm" | "md";
  className?: string;
  ariaLabel?: string;
  title?: string;
}) {
  const sizing = size === "sm" ? "min-h-[34px] px-3.5 text-[13px] gap-1.5" : "min-h-[46px] px-5 text-[15px] gap-2";
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      aria-label={ariaLabel}
      title={title}
      className={`inline-flex items-center justify-center rounded-full font-semibold transition-[opacity,background-color] disabled:cursor-not-allowed disabled:opacity-40 ${sizing} ${VARIANT[variant]} ${full ? "w-full" : ""} ${className}`}
    >
      {Icon && <Icon size={size === "sm" ? 14 : 16} aria-hidden className="shrink-0" />}
      {children}
    </button>
  );
}

/** A round icon-only button, for close, more and back. */
export function IconButton({ icon: Icon, label, onClick, className = "" }: { icon: LucideIcon; label: string; onClick?: () => void; className?: string }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      title={label}
      className={`inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-surface-2 text-ink transition-colors hover:bg-line ${className}`}
    >
      <Icon size={17} aria-hidden />
    </button>
  );
}

export interface SegOption<T extends string> {
  id: T;
  label: string;
}

/** Move between radio-like options with the arrow keys, as a radiogroup should. */
function arrowNav<T extends string>(e: KeyboardEvent, options: SegOption<T>[], value: T, onChange: (v: T) => void, refs: (HTMLButtonElement | null)[]) {
  const i = options.findIndex((o) => o.id === value);
  const step = e.key === "ArrowRight" || e.key === "ArrowDown" ? 1 : e.key === "ArrowLeft" || e.key === "ArrowUp" ? -1 : 0;
  if (!step) return;
  e.preventDefault();
  const next = (i + step + options.length) % options.length;
  onChange(options[next].id);
  refs[next]?.focus();
}

/** Two to five options in one pill; the chosen one sits on a raised surface. */
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
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  return (
    <div role="radiogroup" aria-label={label} className="grid gap-1 rounded-full bg-surface-2 p-1" style={{ gridTemplateColumns: `repeat(${options.length}, minmax(0, 1fr))` }}>
      {options.map((o, i) => {
        const on = o.id === value;
        return (
          <button
            key={o.id}
            ref={(el) => {
              refs.current[i] = el;
            }}
            type="button"
            role="radio"
            aria-checked={on}
            tabIndex={on ? 0 : -1}
            onClick={() => onChange(o.id)}
            onKeyDown={(e) => arrowNav(e, options, value, onChange, refs.current)}
            className={`min-h-[36px] truncate rounded-full px-2 text-sm font-semibold transition-colors ${on ? "bg-raised text-ink shadow-card" : "text-muted hover:text-ink"}`}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

/** Underlined tabs for switching sections of one page. */
export function Tabs<T extends string>({
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
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  return (
    <div role="tablist" aria-label={label} className="pt-noscrollbar flex gap-5 overflow-x-auto border-b border-line">
      {options.map((o, i) => {
        const on = o.id === value;
        return (
          <button
            key={o.id}
            ref={(el) => {
              refs.current[i] = el;
            }}
            type="button"
            role="tab"
            aria-selected={on}
            tabIndex={on ? 0 : -1}
            onClick={() => onChange(o.id)}
            onKeyDown={(e) => arrowNav(e, options, value, onChange, refs.current)}
            className={`-mb-px shrink-0 border-b-2 pb-2.5 pt-1 text-[15px] font-semibold transition-colors ${on ? "border-ink text-ink" : "border-transparent text-muted hover:text-ink"}`}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

/** The chart ranges, as a row of chips. */
export const RANGES = ["1D", "1W", "1M", "1Y", "Max"] as const;
export type Range = (typeof RANGES)[number];

export function RangeChips<T extends string = Range>({
  value,
  onChange,
  options = RANGES as unknown as readonly T[],
  label = "Chart range",
  disabled = [],
}: {
  value: T;
  onChange: (v: T) => void;
  options?: readonly T[];
  label?: string;
  /** Ranges without enough data yet. */
  disabled?: readonly T[];
}) {
  return (
    <div role="group" aria-label={label} className="pt-noscrollbar flex gap-1.5 overflow-x-auto">
      {options.map((r) =>
        disabled.includes(r) ? (
          <span key={r} className="inline-flex min-h-[32px] shrink-0 items-center rounded-full px-3 text-[13px] font-semibold text-faint opacity-60" title="Not enough history yet">
            {r}
          </span>
        ) : (
          <Chip key={r} selected={r === value} onClick={() => onChange(r)}>
            {r}
          </Chip>
        ),
      )}
    </div>
  );
}

/** An on/off switch. */
export function Toggle({ on, onChange, label, disabled }: { on: boolean; onChange: (v: boolean) => void; label?: string; disabled?: boolean }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!on)}
      className={`relative h-[30px] w-[50px] shrink-0 rounded-full transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${on ? "bg-up" : "bg-line-strong"}`}
    >
      <span className={`absolute top-[3px] h-6 w-6 rounded-full bg-white shadow-card transition-[left] duration-200 ${on ? "left-[23px]" : "left-[3px]"}`} />
    </button>
  );
}

/** The look of every text input, select and textarea. */
export const inputCls =
  "w-full min-w-0 min-h-[44px] rounded-control border border-transparent bg-surface-2 px-3.5 py-2 text-[15px] text-ink placeholder:text-faint transition-colors hover:border-line-strong focus:border-accent focus:outline-none disabled:cursor-not-allowed disabled:opacity-50";

/** A labelled control. The label wraps the control, so clicking it focuses the input. */
export function Field({ label, hint, children, className = "", error }: { label: ReactNode; hint?: ReactNode; children: ReactNode; className?: string; error?: string }) {
  const id = useId();
  return (
    <label className={`block min-w-0 ${className}`}>
      <span className="mb-1.5 block text-[13px] font-medium text-muted">{label}</span>
      {children}
      {hint && !error && <span className="mt-1.5 block text-[13px] leading-snug text-faint">{hint}</span>}
      {error && (
        <span id={id} role="alert" className="mt-1.5 block text-[13px] leading-snug text-down">
          {error}
        </span>
      )}
    </label>
  );
}
