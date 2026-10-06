import { AlertTriangle } from "lucide-react";
import type { PnlBreakdown } from "../types";
import { fmtUsd } from "./ui";

/** Plain-language reason a result is flagged as cost-heavy, or `null` when it is not. */
export function costWarning(p: PnlBreakdown): string | null {
  if (!p.costHeavy) return null;
  if (p.costShare !== undefined) {
    return `Costs eat ${(p.costShare * 100).toFixed(0)}% of the gross result. Above 40% the costs are the story, not the strategy.`;
  }
  return "There was no gross profit, and trading still cost money. The costs alone made this a loss.";
}

/**
 * Gross, costs and net as three separate lines, with the 40 % warning.
 * `fmt` renders one amount: dollars by default, or e.g. percent of capital.
 */
export function PnlLines({
  pnl,
  fmt = (n) => fmtUsd(n),
  compact = false,
}: {
  pnl: PnlBreakdown;
  fmt?: (n: number) => string;
  compact?: boolean;
}) {
  const warn = costWarning(pnl);
  return (
    <div className={compact ? "text-xs" : "text-sm"}>
      <div className="grid grid-cols-3 gap-3">
        <Line label="Gross" hint="before fees, spread and impact" value={fmt(pnl.gross)} tone={pnl.gross >= 0 ? "text-success" : "text-danger"} />
        <Line label="Costs" hint="fees + slippage" value={pnl.costs > 0 ? `-${fmt(pnl.costs)}` : fmt(0)} tone="text-warning" />
        <Line label="Net" hint="what you keep" value={fmt(pnl.net)} tone={pnl.net >= 0 ? "text-success" : "text-danger"} />
      </div>
      {warn && (
        <div className="mt-2 flex items-start gap-1.5 rounded border border-warning/40 bg-warning/5 px-2 py-1.5 text-xs text-warning">
          <AlertTriangle size={13} className="mt-0.5 shrink-0" />
          <span>{warn}</span>
        </div>
      )}
    </div>
  );
}

function Line({ label, hint, value, tone }: { label: string; hint: string; value: string; tone: string }) {
  return (
    <div className="rounded border border-cyber-border bg-cyber-surface-2 px-2 py-1.5" title={hint}>
      <div className="text-[10px] uppercase tracking-widest text-cyber-text-faint">{label}</div>
      <div className={`font-mono font-bold ${tone}`}>{value}</div>
    </div>
  );
}
