import { useMemo } from "react";
import { AlertTriangle, TrendingDown, Trophy } from "lucide-react";
import { useStore } from "../store";
import { Card, PageHeader, Badge, Sparkline, MultiLineChart, fmtUsd } from "../components/ui";
import { costWarning } from "../components/PnlBreakdown";
import { breakdown } from "../engine/costs";
import type { PnlBreakdown, SlippageRow, StrategyConfig } from "../types";

export function Analytics() {
  const { portfolio, strategies, orders, slippage } = useStore();

  // drawdown series (% below running peak) from the equity curve
  const drawdown = useMemo(() => {
    let peak = -Infinity;
    return portfolio.equityCurve.map((v) => {
      if (v > peak) peak = v;
      return peak > 0 ? -((peak - v) / peak) * 100 : 0;
    });
  }, [portfolio.equityCurve]);
  const curMaxDD = drawdown.length ? Math.min(...drawdown) : 0;

  const ranked = useMemo(
    () => [...strategies].filter((s) => s.id !== "manual").sort((a, b) => b.pnl - a.pnl),
    [strategies]
  );

  const fills = orders.filter((o) => o.status === "filled").slice(0, 30);

  return (
    <div className="animate-fade-in">
      <PageHeader title="Analytics" subtitle="Drawdown, strategy leaderboard & trade log" />

      <Card title="Portfolio Drawdown" className="mb-4" right={<Badge tone="red">{curMaxDD.toFixed(2)}% max</Badge>}>
        <Sparkline data={drawdown.length > 1 ? drawdown : [0, 0]} height={120} tone="red" />
        <div className="mt-1 flex items-center gap-1 text-xs text-cyber-text-faint">
          <TrendingDown size={11} /> peak-to-current equity drawdown over the session
        </div>
      </Card>

      <Card title="Strategy Equity Curves" className="mb-4">
        {(() => {
          const active = ranked.filter((s) => s.equityCurve.length > 1 && (s.pnl !== 0 || s.trades > 0));
          if (active.length === 0) {
            return <div className="py-4 text-center text-xs text-cyber-text-faint">Curves appear once strategies close trades.</div>;
          }
          return <MultiLineChart height={180} series={active.map((s) => ({ label: s.name.split(" · ")[0], data: s.equityCurve }))} />;
        })()}
      </Card>

      <Card title="Strategy Leaderboard" className="mb-4" right={<Trophy size={14} className="text-warning" />}>
        <div className="overflow-x-auto">
          <div className="grid min-w-[640px] grid-cols-[1fr_auto_auto_auto_auto_auto_auto_auto] gap-x-4 text-sm">
            <Head>Strategy</Head>
            <Head right>Gross</Head>
            <Head right>Costs</Head>
            <Head right>Net</Head>
            <Head right>Trades</Head>
            <Head right>Win</Head>
            <Head right>PF</Head>
            <Head right>maxDD</Head>
            {ranked.map((s) => {
              const p = pnlOf(s);
              const warn = costWarning(p);
              return (
                <RowGroup key={s.id}>
                  <div className="flex items-center gap-2 py-2">
                    <Badge tone={s.state === "live" ? "red" : s.state === "paused" ? "neutral" : "cyan"}>{s.state}</Badge>
                    <span className="truncate">{s.name}</span>
                    {warn && (
                      <span title={warn} className="text-warning">
                        <AlertTriangle size={13} />
                      </span>
                    )}
                  </div>
                  <Cell className={p.gross >= 0 ? "text-success" : "text-danger"}>{fmtUsd(p.gross)}</Cell>
                  <Cell className={warn ? "text-warning" : "text-cyber-text-dim"}>{p.costs > 0 ? `-${fmtUsd(p.costs)}` : fmtUsd(0)}</Cell>
                  <Cell className={p.net >= 0 ? "text-success" : "text-danger"}>{fmtUsd(p.net)}</Cell>
                  <Cell>{s.trades}</Cell>
                  <Cell>{(s.winRate * 100).toFixed(0)}%</Cell>
                  <Cell className={s.profitFactor >= 1 ? "text-success" : "text-cyber-text-dim"}>{s.profitFactor.toFixed(2)}</Cell>
                  <Cell className="text-danger">{fmtUsd(s.maxDrawdown)}</Cell>
                </RowGroup>
              );
            })}
          </div>
        </div>
        <div className="mt-2 text-xs text-cyber-text-faint">
          Gross is realised P&amp;L at the quoted price; costs are fees plus slippage, booked when paid (so an open
          position's entry costs show before its P&amp;L does); net is what was kept. A warning sign marks a strategy
          whose costs exceed 40% of its gross.
        </div>
        {ranked.every((s) => s.trades === 0) && (
          <div className="mt-2 text-xs text-cyber-text-faint">No closed trades yet — stats populate as positions close.</div>
        )}
      </Card>

      <SlippageCard rows={slippage} />

      <Card title="Trade Log">
        <div className="space-y-1 font-mono text-xs">
          {fills.length === 0 && <div className="text-cyber-text-faint">No fills yet.</div>}
          {fills.map((o) => (
            <div key={o.id} className="flex items-center gap-3 border-b border-cyber-border/40 py-1">
              <span className="text-cyber-text-faint">{new Date(o.ts).toLocaleTimeString()}</span>
              <span className={o.side === "buy" ? "text-success" : "text-danger"}>{o.side.toUpperCase()}</span>
              <span className="flex-1 truncate text-cyber-text-dim">{o.marketId}</span>
              <span>{o.filledQty.toFixed(4)}</span>
              <span className="text-cyber-text-faint">@ {o.avgFillPrice}</span>
              {o.realisedSlippageBps !== undefined && (
                <span
                  className={o.realisedSlippageBps > (o.modelledSlippageBps ?? 0) * 1.5 ? "text-warning" : "text-cyber-text-dim"}
                  title="Realised slippage against the arrival price, next to what the cost model expected"
                >
                  {o.realisedSlippageBps.toFixed(1)} bps vs {(o.modelledSlippageBps ?? 0).toFixed(1)} modelled
                </span>
              )}
              <Badge tone="neutral">{o.strategyId}</Badge>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}

function Head({ children, right }: { children: React.ReactNode; right?: boolean }) {
  return <div className={`pb-2 text-xs uppercase text-cyber-text-faint ${right ? "text-right" : ""}`}>{children}</div>;
}
function Cell({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <div className={`py-2 text-right font-mono ${className}`}>{children}</div>;
}
function RowGroup({ children }: { children: React.ReactNode }) {
  return <div className="col-span-full grid grid-cols-[1fr_auto_auto_auto_auto_auto_auto_auto] gap-x-4 border-t border-cyber-border">{children}</div>;
}

/**
 * Realised slippage against the cost model, per venue. This is the number that
 * says whether the backtests were fiction: if real fills cost far more than the
 * model assumed, every backtest built on the model was too optimistic.
 */
function SlippageCard({ rows }: { rows: SlippageRow[] }) {
  return (
    <Card title="Execution: realised vs modelled slippage" className="mb-4">
      {rows.length === 0 ? (
        <div className="text-xs text-cyber-text-faint">
          No live fills yet. Every live or paper-live fill is measured against the price when the order was
          decided, and compared with what the cost model expected. The comparison means something after 30
          fills per venue. Simulated paper fills are not counted: they pay the model by construction.
        </div>
      ) : (
        <>
          <div className="grid grid-cols-[1fr_auto_auto_auto_auto] gap-x-4 text-sm">
            <Head>Venue</Head>
            <Head right>Fills</Head>
            <Head right>Median realised</Head>
            <Head right>Median modelled</Head>
            <Head right>Ratio</Head>
            {rows.map((r) => (
              <div key={r.venue} className="col-span-full grid grid-cols-[1fr_auto_auto_auto_auto] gap-x-4 border-t border-cyber-border">
                <div className="py-2 capitalize">{r.venue}</div>
                <Cell>
                  {r.fills}
                  {!r.enough && <span className="ml-1 text-[10px] text-cyber-text-faint">(&lt;30)</span>}
                </Cell>
                <Cell>{r.medianRealisedBps.toFixed(1)} bps</Cell>
                <Cell className="text-cyber-text-dim">{r.medianModelledBps.toFixed(1)} bps</Cell>
                <Cell className={r.ratio === undefined ? "text-cyber-text-faint" : r.ratio <= 1.5 ? "text-success" : "text-danger"}>
                  {r.ratio === undefined ? "n/a" : `${r.ratio.toFixed(2)}x`}
                </Cell>
              </div>
            ))}
          </div>
          <div className="mt-2 text-xs text-cyber-text-faint">
            Positive bps cost money. A ratio above 1.5x means real fills cost more than the model assumed, and
            every backtest using the model is too optimistic for that venue until it is recalibrated.
          </div>
        </>
      )}
    </Card>
  );
}

/** A strategy's gross, costs and net. A config that never traded has no ledger yet. */
function pnlOf(s: StrategyConfig): PnlBreakdown {
  return s.ledger?.pnl ?? breakdown(s.pnl, 0);
}
