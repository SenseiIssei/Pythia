import type { ReactNode } from "react";
import { ChevronRight, type LucideIcon } from "lucide-react";
import { tickerHue, tickerOf } from "../format";

/**
 * The page frame: a calm column with a big title. `wide` gives tables and
 * grids room on a desktop; the default column reads like a phone app.
 */
export function Page({
  title,
  subtitle,
  right,
  children,
  wide,
}: {
  title: string;
  subtitle?: ReactNode;
  right?: ReactNode;
  children: ReactNode;
  wide?: boolean;
}) {
  return (
    <div className={`mx-auto w-full ${wide ? "max-w-5xl" : "max-w-2xl"} space-y-5 pb-8`}>
      <header className="flex flex-wrap items-end justify-between gap-3 pt-1">
        <div className="min-w-0">
          <h1 className="text-[28px] font-bold leading-tight tracking-tight text-ink">{title}</h1>
          {subtitle && <p className="mt-1 max-w-xl text-[15px] leading-relaxed text-muted">{subtitle}</p>}
        </div>
        {right && <div className="flex shrink-0 flex-wrap items-center gap-2">{right}</div>}
      </header>
      {children}
    </div>
  );
}

/**
 * A card: a soft surface with a hairline. Optional title row with something
 * on the right (a link, a chip, a button).
 */
export function Card({
  children,
  className = "",
  as: As = "section",
  label,
  title,
  right,
  padded = true,
}: {
  children: ReactNode;
  className?: string;
  as?: "section" | "div" | "article";
  /** Accessible name when there is no visible title. */
  label?: string;
  title?: ReactNode;
  right?: ReactNode;
  /** False for cards whose rows run edge to edge. */
  padded?: boolean;
}) {
  return (
    <As aria-label={label} className={`rounded-card border border-line bg-surface ${padded ? "p-5" : ""} ${className}`}>
      {(title || right) && (
        <div className={`mb-3 flex items-center justify-between gap-3 ${padded ? "" : "px-5 pt-5"}`}>
          {title && <h2 className="min-w-0 text-[17px] font-semibold tracking-tight text-ink">{title}</h2>}
          {right && <div className="flex shrink-0 items-center gap-2">{right}</div>}
        </div>
      )}
      {children}
    </As>
  );
}

/** A section heading between cards, with an optional action on the right. */
export function SectionTitle({ children, right }: { children: ReactNode; right?: ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-2 px-1 pt-3">
      <h2 className="text-xl font-semibold tracking-tight text-ink">{children}</h2>
      {right}
    </div>
  );
}

/** A round badge with a ticker's letters, coloured by a stable hue. */
export function TickerBadge({ symbol, size = 40 }: { symbol: string; size?: number }) {
  const t = tickerOf(symbol);
  const hue = tickerHue(symbol);
  return (
    <span
      aria-hidden
      className="flex shrink-0 items-center justify-center rounded-full font-bold tracking-tight"
      style={{
        width: size,
        height: size,
        fontSize: t.length > 3 ? size * 0.26 : size * 0.3,
        background: `hsl(${hue} 70% 50% / 0.14)`,
        color: `hsl(${hue} 55% var(--ticker-l, 32%))`,
      }}
    >
      {t}
    </span>
  );
}

/**
 * One simple row: a leading badge or icon, a title and a line under it, an
 * amount on the right. A row with onClick is a button and gets a chevron.
 */
export function ListRow({
  icon: Icon,
  ticker,
  leading,
  title,
  subtitle,
  right,
  rightSub,
  onClick,
  chevron,
  selected,
}: {
  icon?: LucideIcon;
  /** Shows a TickerBadge for this symbol. */
  ticker?: string;
  /** Anything else on the left. */
  leading?: ReactNode;
  title: ReactNode;
  subtitle?: ReactNode;
  right?: ReactNode;
  rightSub?: ReactNode;
  onClick?: () => void;
  /** Defaults to on for clickable rows without a right side. */
  chevron?: boolean;
  selected?: boolean;
}) {
  const showChevron = chevron ?? (!!onClick && !right && !rightSub);
  const body = (
    <>
      {leading}
      {!leading && ticker && <TickerBadge symbol={ticker} />}
      {!leading && !ticker && Icon && (
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-surface-2 text-ink" aria-hidden>
          <Icon size={18} />
        </span>
      )}
      <span className="min-w-0 flex-1 text-left">
        <span className="block truncate text-[15px] font-semibold text-ink">{title}</span>
        {subtitle && <span className="block break-words text-[13px] leading-snug text-muted">{subtitle}</span>}
      </span>
      {(right || rightSub) && (
        <span className="shrink-0 text-right">
          {right && <span className="tabular block text-[15px] font-semibold text-ink">{right}</span>}
          {rightSub && <span className="block text-[13px]">{rightSub}</span>}
        </span>
      )}
      {showChevron && <ChevronRight size={18} aria-hidden className="shrink-0 text-faint" />}
    </>
  );
  const base = "flex w-full items-center gap-3 py-3.5";
  return onClick ? (
    <button
      type="button"
      onClick={onClick}
      aria-current={selected ? "true" : undefined}
      className={`${base} -mx-2 w-[calc(100%+1rem)] rounded-control px-2 transition-colors hover:bg-surface-2 ${selected ? "bg-surface-2" : ""}`}
    >
      {body}
    </button>
  ) : (
    <div className={base}>{body}</div>
  );
}

/** Rows with hairlines between them. */
export function List({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`divide-y divide-line ${className}`}>{children}</div>;
}
