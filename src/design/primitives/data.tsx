import type { ReactNode } from "react";
import { ArrowDownRight, ArrowUpRight, Minus } from "lucide-react";
import { signedMoney, signedPct, type ChangeTone } from "../format";

/** A big amount, the way the eye reads it first. */
export function BigNumber({
  value,
  label,
  size = "lg",
  sub,
}: {
  value: string;
  label?: ReactNode;
  size?: "md" | "lg" | "xl";
  /** A line under the number, usually a <Change>. */
  sub?: ReactNode;
}) {
  const cls = size === "xl" ? "text-[40px] leading-[44px]" : size === "lg" ? "text-[34px] leading-tight" : "text-2xl leading-tight";
  return (
    <div className="min-w-0">
      {label && <div className="text-[13px] font-medium text-muted">{label}</div>}
      <div className={`tabular break-words font-bold tracking-tight text-ink ${cls}`}>{value}</div>
      {sub && <div className="mt-1">{sub}</div>}
    </div>
  );
}

const TONE_TEXT: Record<ChangeTone, string> = { up: "text-up", down: "text-down", flat: "text-muted" };

/** A signed change in green or red, with an arrow so it never relies on colour alone. */
export function Change({
  usd,
  pct,
  tone,
  size = "md",
  suffix,
}: {
  usd?: number | null;
  /** Percent units: 1.5 means +1.5%. */
  pct?: number | null;
  tone: ChangeTone;
  size?: "sm" | "md";
  /** A quiet word after the numbers, like "today" or "1W". */
  suffix?: ReactNode;
}) {
  const Icon = tone === "up" ? ArrowUpRight : tone === "down" ? ArrowDownRight : Minus;
  const word = tone === "up" ? "up" : tone === "down" ? "down" : "unchanged";
  return (
    <span className={`tabular inline-flex flex-wrap items-center gap-x-1 font-semibold ${TONE_TEXT[tone]} ${size === "sm" ? "text-[13px]" : "text-[15px]"}`}>
      <Icon size={size === "sm" ? 14 : 16} aria-hidden className="shrink-0" />
      <span className="sr-only">{word}</span>
      {usd != null && <span>{signedMoney(usd)}</span>}
      {pct != null && <span>{usd != null ? `(${signedPct(pct)})` : signedPct(pct)}</span>}
      {suffix && <span className="font-normal text-muted">{suffix}</span>}
    </span>
  );
}

export type ChipTone = "neutral" | "good" | "warn" | "bad" | "accent";

const CHIP_TEXT: Record<ChipTone, string> = {
  neutral: "text-muted",
  good: "text-up",
  warn: "text-warn",
  bad: "text-down",
  accent: "text-accent",
};

/**
 * A small rounded label. With onClick it is a toggle (range chips, filters):
 * the selected one is filled with ink.
 */
export function Chip({
  children,
  tone = "neutral",
  title,
  onClick,
  selected,
}: {
  children: ReactNode;
  tone?: ChipTone;
  title?: string;
  onClick?: () => void;
  selected?: boolean;
}) {
  if (onClick) {
    return (
      <button
        type="button"
        title={title}
        onClick={onClick}
        aria-pressed={selected}
        className={`inline-flex min-h-[32px] shrink-0 items-center gap-1 rounded-full px-3 text-[13px] font-semibold transition-colors ${
          selected ? "bg-primary text-on-primary" : "bg-surface-2 text-muted hover:text-ink"
        }`}
      >
        {children}
      </button>
    );
  }
  return (
    <span title={title} className={`inline-flex max-w-full items-center gap-1 truncate rounded-full bg-surface-2 px-2.5 py-0.5 text-xs font-semibold ${CHIP_TEXT[tone]}`}>
      {children}
    </span>
  );
}

/** A quiet status label: like a chip, but square-ish and smaller. */
export function Badge({ children, tone = "neutral", title }: { children: ReactNode; tone?: ChipTone; title?: string }) {
  const tint: Record<ChipTone, string> = {
    neutral: "bg-surface-2 text-muted",
    good: "bg-up/10 text-up",
    warn: "bg-warn/10 text-warn",
    bad: "bg-down/10 text-down",
    accent: "bg-accent/10 text-accent",
  };
  return (
    <span title={title} className={`inline-flex items-center whitespace-nowrap rounded-md px-1.5 py-0.5 text-[11px] font-semibold ${tint[tone]}`}>
      {children}
    </span>
  );
}

/** Label over value, for small read-outs side by side. */
export function Stat({ label, value, sub }: { label: ReactNode; value: ReactNode; sub?: ReactNode }) {
  return (
    <div className="min-w-0">
      <div className="truncate text-[13px] text-muted">{label}</div>
      <div className="tabular truncate text-[17px] font-semibold text-ink">{value}</div>
      {sub && <div className="text-[13px]">{sub}</div>}
    </div>
  );
}
