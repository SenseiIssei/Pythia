import { useEffect, useMemo, useRef, useState } from "react";
import { Card } from "../design";
import { fmtWhen } from "../autopilot";
import {
  chartFrame,
  combinedSeries,
  compareRows,
  fmtPct,
  leaderLine,
  valueAt,
  type CompareRow,
  type CompareSeries,
} from "../flows/compare";
import type { AutopilotStatus } from "../types";

const MODE: Record<CompareRow["mode"], string> = { paper: "Practice", demo: "Demo", live: "Real money" };

function seriesColor(slot: number): string {
  return `var(--color-series-${slot + 1})`;
}

function money(n: number): string {
  return `$${Math.round(n).toLocaleString("en-US")}`;
}

/** "+1.2 pts", "−0.4 pts" with a real minus sign; "n/a" when unknown. */
function pts(n: number | null): string {
  if (n == null) return "n/a";
  return `${n > 0.05 ? "+" : n < -0.05 ? "−" : ""}${Math.abs(n).toFixed(1)} pts`;
}

/**
 * Every autopilot side by side: one row each (return, against its
 * benchmark, deepest drawdown, trades, fees) and their equity curves on one
 * chart, each as a return from its own amount. Shown when two or more run.
 */
export function AutopilotCompare({ list, now }: { list: AutopilotStatus[]; now: number }) {
  const rows = useMemo(() => compareRows(list, now), [list, now]);
  const series = useMemo(() => combinedSeries(list, now), [list, now]);
  const lead = leaderLine(rows);
  const hidden = rows.filter((r) => r.slot === null).length;

  return (
    <Card label="Autopilots side by side">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-base font-semibold">Side by side</h2>
        <span className="text-muted text-xs">Each trades its own book on the shared account</span>
      </div>
      {lead && <p className="text-muted mt-1 text-sm">{lead}</p>}

      <CompareChart series={series} />
      {hidden > 0 && <p className="text-muted mt-1 text-xs">{hidden} more in the table below; the chart draws the first six by start.</p>}

      {/* Narrow screens: one block per autopilot instead of a wide table. */}
      <ul className="mt-3 sm:hidden" aria-label="Autopilots compared">
        {rows.map((r, i) => (
          <li key={r.id} className={`py-2.5 ${i > 0 ? "border-t" : ""}`} style={{ borderColor: "var(--color-line)" }}>
            <div className="flex items-center gap-2">
              <span
                aria-hidden
                className="inline-block h-2.5 w-2.5 shrink-0 rounded-full"
                style={{ background: r.slot !== null ? seriesColor(r.slot) : "transparent" }}
              />
              <span className="min-w-0 flex-1 truncate font-semibold">{r.name}</span>
              <span className={`tabular font-semibold ${r.returnPct > 0.005 ? "text-up" : r.returnPct < -0.005 ? "text-down" : ""}`}>
                {fmtPct(r.returnPct)}
              </span>
            </div>
            <dl className="text-muted mt-1 grid grid-cols-2 gap-x-3 gap-y-0.5 pl-[18px] text-xs">
              <dt>vs {r.benchLabel}</dt>
              <dd className="tabular text-right">{r.vsBenchPts == null ? "n/a" : `${r.vsBenchPts >= 0 ? "+" : "−"}${Math.abs(r.vsBenchPts).toFixed(1)} pts`}</dd>
              <dt>vs BTC above 200d</dt>
              <dd className="tabular text-right">{pts(r.vsGatedPts)}</dd>
              <dt>Deepest drawdown</dt>
              <dd className="tabular text-right">{r.maxDrawdownPct.toFixed(1)}%</dd>
              <dt>Trades · fees</dt>
              <dd className="tabular text-right">
                {r.trades} · ${r.fees.toFixed(2)}
              </dd>
              <dt>{MODE[r.mode]}</dt>
              <dd className="tabular text-right">
                {money(r.amount)}
                {!r.active ? " · stopped" : ""}
              </dd>
            </dl>
          </li>
        ))}
      </ul>

      <div className="mt-3 hidden overflow-x-auto sm:block">
        <table className="w-full min-w-[600px] text-sm">
          <caption className="sr-only">Autopilots compared: return, against the benchmark, drawdown, trades and fees</caption>
          <thead>
            <tr className="text-muted text-left text-xs">
              <th scope="col" className="py-1.5 pr-2 font-semibold">Autopilot</th>
              <th scope="col" className="py-1.5 pr-2 text-right font-semibold">Return</th>
              <th scope="col" className="py-1.5 pr-2 text-right font-semibold">vs benchmark</th>
              <th
                scope="col"
                className="py-1.5 pr-2 text-right font-semibold"
                title="Bitcoin held only while its close is above its 200-day average, over the same period"
              >
                vs BTC above 200d
              </th>
              <th scope="col" className="py-1.5 pr-2 text-right font-semibold" title="Deepest fall from a peak, and below the peak now">
                Drawdown
              </th>
              <th scope="col" className="py-1.5 pr-2 text-right font-semibold">Trades</th>
              <th scope="col" className="py-1.5 text-right font-semibold">Fees</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} className="border-t" style={{ borderColor: "var(--color-line)" }}>
                <th scope="row" className="py-2 pr-2 text-left font-normal">
                  <span className="flex items-center gap-2">
                    {r.slot !== null ? (
                      <span aria-hidden className="inline-block h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: seriesColor(r.slot) }} />
                    ) : (
                      <span aria-hidden className="inline-block h-2.5 w-2.5 shrink-0" />
                    )}
                    <span className="min-w-0">
                      <span className="block truncate font-semibold">{r.name}</span>
                      <span className="text-muted block text-xs">
                        {MODE[r.mode]} · {money(r.amount)}
                        {!r.active ? " · stopped" : ""}
                      </span>
                    </span>
                  </span>
                </th>
                <td className={`tabular py-2 pr-2 text-right font-semibold ${r.returnPct > 0.005 ? "text-up" : r.returnPct < -0.005 ? "text-down" : ""}`}>
                  {fmtPct(r.returnPct)}
                </td>
                <td className="tabular py-2 pr-2 text-right">
                  {r.vsBenchPts == null ? (
                    <span className="text-muted">n/a</span>
                  ) : (
                    <>
                      <span className="block">
                        {r.vsBenchPts > 0.05 ? "+" : r.vsBenchPts < -0.05 ? "−" : ""}
                        {Math.abs(r.vsBenchPts).toFixed(1)} pts
                      </span>
                      <span className="text-muted block text-xs">
                        {r.benchLabel} {fmtPct(r.benchPct, 1)}
                      </span>
                    </>
                  )}
                </td>
                <td className="tabular py-2 pr-2 text-right">
                  {r.vsGatedPts == null ? (
                    <span className="text-muted">n/a</span>
                  ) : (
                    <>
                      <span className="block">{pts(r.vsGatedPts)}</span>
                      <span className="text-muted block text-xs">gated {fmtPct(r.gatedPct, 1)}</span>
                    </>
                  )}
                </td>
                <td className="tabular py-2 pr-2 text-right">
                  <span className="block" title={r.curveNote ?? undefined}>
                    {r.maxDrawdownPct.toFixed(1)}%{r.curveNote ? " *" : ""}
                  </span>
                  <span className="text-muted block text-xs">now {r.drawdownPct.toFixed(1)}%</span>
                </td>
                <td className="tabular py-2 pr-2 text-right">{r.trades}</td>
                <td className="tabular py-2 text-right">
                  <span className="block">${r.fees.toFixed(2)}</span>
                  <span className="text-muted block text-xs">{r.feesPct.toFixed(2)}%</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-muted mt-2 text-xs">
        Benchmark: buying and holding Bitcoin for crypto, SPY for US shares, over the same period. Points are the return less the
        benchmark's. "BTC above 200d" is the harder yardstick: Bitcoin held only while its close is above its 200-day average, cash
        otherwise; no book the autopilots run has beaten it out of sample. Returns and fees are measured on the amount each one worked
        with, so changing an amount changes neither.
      </p>
      {rows
        .filter((r) => r.curveNote)
        .map((r) => (
          <p key={`note-${r.id}`} className="text-muted mt-1 text-xs">
            * {r.name}: {r.curveNote}
          </p>
        ))}
    </Card>
  );
}

const H = 200;
const PAD = { top: 10, right: 12, bottom: 22, left: 44 };

/** The equity curves as a return from each one's own amount, on one axis. */
function CompareChart({ series }: { series: CompareSeries[] }) {
  const box = useRef<HTMLDivElement>(null);
  const [w, setW] = useState(600);
  const [hover, setHover] = useState<number | null>(null);

  useEffect(() => {
    const el = box.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver((e) => setW(Math.max(260, Math.round(e[0].contentRect.width))));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const frame = chartFrame(series);
  if (!frame) {
    return (
      <div className="bg-surface-2 mt-3 flex h-24 items-center justify-center rounded-xl text-sm" role="img" aria-label="Not enough history yet to draw">
        <span className="text-muted">Not enough history yet to draw them together.</span>
      </div>
    );
  }
  const { t0, t1, lo, hi, ticks } = frame;
  const iw = w - PAD.left - PAD.right;
  const ih = H - PAD.top - PAD.bottom;
  const x = (t: number) => PAD.left + ((t - t0) / (t1 - t0)) * iw;
  const y = (v: number) => PAD.top + (1 - (v - lo) / (hi - lo)) * ih;
  const path = (pts: [number, number][]) => pts.map(([t, v], i) => `${i === 0 ? "M" : "L"}${x(t).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  const direct = series.length <= 4;
  const hoverT = hover !== null ? Math.min(t1, Math.max(t0, t0 + ((hover - PAD.left) / iw) * (t1 - t0))) : null;
  const at = hoverT !== null ? series.map((s) => ({ s, v: valueAt(s.points, hoverT) })).filter((r) => r.v !== null) : [];

  function move(clientX: number) {
    const r = box.current?.getBoundingClientRect();
    if (!r) return;
    const px = Math.min(Math.max(clientX - r.left, PAD.left), PAD.left + iw);
    setHover(px);
  }

  return (
    <div className="mt-3">
      {/* Legend: always there for two or more, so identity is never colour alone. */}
      <ul className="mb-2 flex flex-wrap gap-x-3 gap-y-1 text-xs" aria-label="Legend">
        {series.map((s) => (
          <li key={s.id} className="flex items-center gap-1.5">
            <span aria-hidden className="inline-block h-0.5 w-4 rounded" style={{ background: seriesColor(s.slot) }} />
            <span>{s.name}</span>
          </li>
        ))}
      </ul>
      <div
        ref={box}
        className="relative w-full select-none"
        onMouseMove={(e) => move(e.clientX)}
        onMouseLeave={() => setHover(null)}
        onTouchStart={(e) => move(e.touches[0].clientX)}
        onTouchMove={(e) => move(e.touches[0].clientX)}
        onTouchEnd={() => setHover(null)}
      >
        <svg width={w} height={H} role="img" aria-label="Return of each autopilot since its start, percent, over time">
          {ticks.map((v) => (
            <g key={v}>
              <line
                x1={PAD.left}
                x2={PAD.left + iw}
                y1={y(v)}
                y2={y(v)}
                stroke="var(--color-line)"
                strokeWidth={Math.abs(v) < 1e-9 ? 1.5 : 1}
                strokeDasharray={Math.abs(v) < 1e-9 ? undefined : "2 3"}
              />
              <text x={PAD.left - 6} y={y(v) + 3} textAnchor="end" fontSize={10} fill="var(--color-muted)">
                {fmtPct(v, Math.abs(hi - lo) < 4 ? 1 : 0)}
              </text>
            </g>
          ))}
          <text x={PAD.left} y={H - 6} fontSize={10} fill="var(--color-muted)">
            {fmtWhen(t0)}
          </text>
          <text x={PAD.left + iw} y={H - 6} fontSize={10} fill="var(--color-muted)" textAnchor="end">
            {fmtWhen(t1)}
          </text>
          {series.map((s) => (
            <path
              key={s.id}
              d={path(s.points)}
              fill="none"
              stroke={seriesColor(s.slot)}
              strokeWidth={2}
              strokeLinejoin="round"
              strokeLinecap="round"
            />
          ))}
          {series.map((s) => {
            const last = s.points[s.points.length - 1];
            return (
              <circle
                key={s.id}
                cx={x(last[0])}
                cy={y(last[1])}
                r={4}
                fill={seriesColor(s.slot)}
                stroke="var(--color-surface)"
                strokeWidth={2}
              />
            );
          })}
          {direct &&
            series.map((s) => {
              const last = s.points[s.points.length - 1];
              const right = x(last[0]) > PAD.left + iw * 0.7;
              return (
                <text
                  key={s.id}
                  x={x(last[0]) + (right ? -8 : 8)}
                  y={y(last[1]) - 7}
                  fontSize={11}
                  fontWeight={600}
                  textAnchor={right ? "end" : "start"}
                  fill="var(--color-text)"
                  stroke="var(--color-surface)"
                  strokeWidth={3}
                  paintOrder="stroke"
                >
                  {fmtPct(last[1], 1)}
                </text>
              );
            })}
          {hover !== null && <line x1={hover} x2={hover} y1={PAD.top} y2={PAD.top + ih} stroke="var(--color-muted)" strokeWidth={1} />}
          {hover !== null &&
            at.map(({ s, v }) => (
              <circle key={s.id} cx={hover} cy={y(v as number)} r={4} fill={seriesColor(s.slot)} stroke="var(--color-surface)" strokeWidth={2} />
            ))}
        </svg>
        {hover !== null && hoverT !== null && at.length > 0 && (
          // In the corner away from the crosshair, so it never covers it or
          // runs off a narrow screen.
          <div
            className="rounded-card border border-line bg-surface pointer-events-none absolute top-1 z-10 max-w-[70%] px-2.5 py-1.5 text-xs shadow-sm"
            style={hover > PAD.left + iw / 2 ? { left: PAD.left + 4 } : { right: PAD.right + 4 }}
          >
            <div className="text-muted mb-0.5">{fmtWhen(hoverT)}</div>
            {at
              .sort((a, b) => (b.v as number) - (a.v as number))
              .map(({ s, v }) => (
                <div key={s.id} className="flex items-center gap-1.5 whitespace-nowrap">
                  <span aria-hidden className="inline-block h-2 w-2 rounded-full" style={{ background: seriesColor(s.slot) }} />
                  <span>{s.name}</span>
                  <span className="tabular ml-auto pl-2 font-semibold">{fmtPct(v, 2)}</span>
                </div>
              ))}
          </div>
        )}
      </div>
    </div>
  );
}
