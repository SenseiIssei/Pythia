import { useId, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent, type ReactNode } from "react";
import { chartGeometry, nearestIndex } from "../chartPath";
import { seriesChange, type ChangeTone } from "../format";

export type ChartTone = ChangeTone | "accent";

const STROKE: Record<ChartTone, string> = {
  up: "var(--color-up)",
  down: "var(--color-down)",
  flat: "var(--color-muted)",
  accent: "var(--color-accent)",
};

export interface Scrub {
  /** Index into the data passed in. */
  index: number;
  value: number;
}

/**
 * The big chart: a smooth line with a soft fill, green when it ended up and
 * red when down. Drag, hover or use the arrow keys to read a point; the
 * parent gets it through `onScrub` and usually shows it in its BigNumber.
 */
export function AreaChart({
  data,
  height = 180,
  tone,
  label,
  baseline,
  onScrub,
  renderTip,
  empty = "The chart fills in as new prices arrive.",
}: {
  data: readonly number[];
  height?: number;
  /** Defaults to up or down from first to last point. */
  tone?: ChartTone;
  /** Describes the chart for screen readers. */
  label: string;
  /** A dotted reference line, like the value at the start of the range. */
  baseline?: number;
  onScrub?: (s: Scrub | null) => void;
  /** Text above the scrub line, given the data index. */
  renderTip?: (index: number) => ReactNode;
  empty?: ReactNode;
}) {
  const W = 600;
  const gid = useId().replace(/:/g, "");
  const box = useRef<HTMLDivElement>(null);
  const [at, setAt] = useState<number | null>(null);
  const geo = useMemo(() => chartGeometry(data, W, height, 6, 260, baseline != null ? [baseline] : []), [data, height, baseline]);

  if (!geo) {
    return (
      <div style={{ height }} className="flex items-center justify-center rounded-2xl bg-surface-2 px-4 text-center text-[13px] text-muted" role="img" aria-label={`${label}: not enough points yet`}>
        {empty}
      </div>
    );
  }

  const t: ChartTone = tone ?? seriesChange(geo.values).tone;
  const stroke = STROKE[t];

  const pick = (i: number | null) => {
    setAt(i);
    onScrub?.(i == null ? null : { index: geo.index[i], value: geo.values[i] });
  };
  const fromPointer = (e: PointerEvent) => {
    const r = box.current?.getBoundingClientRect();
    if (!r || r.width === 0) return;
    pick(nearestIndex(geo.xs, W, (e.clientX - r.left) / r.width));
  };
  const onKey = (e: KeyboardEvent) => {
    const last = geo.xs.length - 1;
    const step = Math.max(1, Math.round(geo.xs.length / 40));
    if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
      e.preventDefault();
      const base = at ?? (e.key === "ArrowLeft" ? last + 1 : -1);
      pick(Math.max(0, Math.min(last, base + (e.key === "ArrowRight" ? step : -step))));
    } else if (e.key === "Home" || e.key === "End") {
      e.preventDefault();
      pick(e.key === "Home" ? 0 : last);
    } else if (e.key === "Escape") {
      pick(null);
    }
  };

  const dot = at != null ? { left: (geo.xs[at] / W) * 100, top: (geo.ys[at] / height) * 100 } : null;

  return (
    <div
      ref={box}
      className="relative w-full touch-pan-y select-none rounded-xl outline-offset-4"
      style={{ height }}
      role="group"
      aria-roledescription="chart"
      tabIndex={0}
      aria-label={`${label}. Use the left and right arrow keys to read values.`}
      onPointerMove={fromPointer}
      onPointerDown={fromPointer}
      onPointerLeave={() => pick(null)}
      onKeyDown={onKey}
      onBlur={() => pick(null)}
    >
      <svg viewBox={`0 0 ${W} ${height}`} preserveAspectRatio="none" width="100%" height={height} aria-hidden className="block overflow-visible">
        <defs>
          <linearGradient id={`g${gid}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" style={{ stopColor: stroke, stopOpacity: 0.16 }} />
            <stop offset="100%" style={{ stopColor: stroke, stopOpacity: 0 }} />
          </linearGradient>
        </defs>
        <path d={geo.area} style={{ fill: `url(#g${gid})` }} />
        {baseline != null && Number.isFinite(baseline) && (
          <line x1={0} x2={W} y1={geo.yOf(baseline)} y2={geo.yOf(baseline)} style={{ stroke: "var(--color-faint)" }} strokeWidth={1} strokeDasharray="2 4" vectorEffect="non-scaling-stroke" />
        )}
        <path d={geo.line} fill="none" style={{ stroke }} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
      </svg>
      {dot && (
        <>
          <div className="pointer-events-none absolute inset-y-0 w-px bg-line-strong" style={{ left: `${dot.left}%` }} aria-hidden />
          <div
            className="pointer-events-none absolute h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-surface"
            style={{ left: `${dot.left}%`, top: `${dot.top}%`, background: stroke }}
            aria-hidden
          />
          {renderTip && (
            <div
              className="pointer-events-none absolute -top-6 whitespace-nowrap text-[12px] font-medium text-muted"
              style={{ left: `${dot.left}%`, transform: `translateX(${dot.left > 80 ? "-100%" : dot.left < 20 ? "0" : "-50%"})` }}
              aria-hidden
            >
              {renderTip(geo.index[at!])}
            </div>
          )}
        </>
      )}
    </div>
  );
}

/** A small line for rows and cards. No axes, no interaction. */
export function Sparkline({
  data,
  tone,
  height = 32,
  width,
  label,
  fill = false,
}: {
  data: readonly number[];
  tone?: ChartTone;
  height?: number;
  /** Fixed width in px; full width when left out. */
  width?: number;
  label?: string;
  fill?: boolean;
}) {
  const W = 120;
  const gid = useId().replace(/:/g, "");
  const geo = useMemo(() => chartGeometry(data, W, height, 2, 80), [data, height]);
  if (!geo) return <div style={{ height, width }} className="rounded-md bg-surface-2" role="img" aria-label={`${label ?? "Chart"}: not enough points yet`} />;
  const t: ChartTone = tone ?? seriesChange(geo.values).tone;
  const stroke = STROKE[t];
  return (
    <svg
      viewBox={`0 0 ${W} ${height}`}
      preserveAspectRatio="none"
      width={width ?? "100%"}
      height={height}
      role="img"
      aria-label={label ?? `Chart, ${t === "up" ? "up" : t === "down" ? "down" : "flat"} over the period shown`}
      className="block shrink-0"
    >
      {fill && (
        <>
          <defs>
            <linearGradient id={`s${gid}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" style={{ stopColor: stroke, stopOpacity: 0.14 }} />
              <stop offset="100%" style={{ stopColor: stroke, stopOpacity: 0 }} />
            </linearGradient>
          </defs>
          <path d={geo.area} style={{ fill: `url(#s${gid})` }} />
        </>
      )}
      <path d={geo.line} fill="none" style={{ stroke }} strokeWidth={1.6} strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

/** The flows' name for a small full-width chart. */
export function MiniChart({ data, tone, height = 56, label }: { data: number[]; tone: ChangeTone; height?: number; label: string }) {
  return <Sparkline data={data} tone={tone} height={height} label={label} fill />;
}

/** Several series on one scale, with a legend. Colours come from the series tokens. */
export function LineChart({ series, height = 200, label }: { series: { label: string; data: number[]; color?: string }[]; height?: number; label?: string }) {
  const W = 600;
  const all = series.flatMap((s) => s.data.filter((v) => Number.isFinite(v)));
  if (all.length < 2) {
    return (
      <div style={{ height }} className="flex items-center justify-center rounded-2xl bg-surface-2 text-[13px] text-muted">
        The chart fills in as new prices arrive.
      </div>
    );
  }
  const min = Math.min(...all);
  const max = Math.max(...all);
  const pad = 6;
  const maxLen = Math.max(...series.map((s) => s.data.length), 2);
  const color = (i: number, c?: string) => c ?? `var(--color-series-${(i % 6) + 1})`;
  return (
    <div>
      <svg viewBox={`0 0 ${W} ${height}`} preserveAspectRatio="none" width="100%" height={height} role="img" aria-label={label ?? `Chart of ${series.map((s) => s.label).join(", ")}`}>
        {[0.25, 0.5, 0.75].map((f) => (
          <line key={f} x1={0} x2={W} y1={height * f} y2={height * f} style={{ stroke: "var(--color-line)" }} strokeWidth={1} vectorEffect="non-scaling-stroke" />
        ))}
        {series.map((s, i) => {
          const g = chartGeometry(s.data, (W * (s.data.length - 1)) / (maxLen - 1 || 1), height, pad, 260, [min, max]);
          return g ? <path key={i} d={g.line} fill="none" style={{ stroke: color(i, s.color) }} strokeWidth={1.8} strokeLinejoin="round" vectorEffect="non-scaling-stroke" /> : null;
        })}
      </svg>
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[13px] text-muted">
        {series.map((s, i) => (
          <span key={i} className="flex items-center gap-1.5">
            <span className="inline-block h-2 w-2 rounded-full" style={{ background: color(i, s.color) }} aria-hidden />
            {s.label}
          </span>
        ))}
      </div>
    </div>
  );
}
