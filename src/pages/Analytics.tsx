import { useMemo } from "react";
import { TrendingDown, Trophy } from "lucide-react";
import { useStore } from "../store";
import { Card, PageHeader, Badge, Sparkline, MultiLineChart, fmtUsd } from "../components/ui";

export function Analytics() {
  const { portfolio, strategies, orders } = useStore();

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
        <div className="grid grid-cols-[1fr_auto_auto_auto_auto_auto] gap-x-4 text-sm">
          <Head>Strategy</Head>
          <Head right>P&L</Head>
          <Head right>Trades</Head>
          <Head right>Win</Head>
          <Head right>PF</Head>
          <Head right>maxDD</Head>
          {ranked.map((s) => (
            <RowGroup key={s.id}>
              <div className="flex items-center gap-2 py-2">
                <Badge tone={s.state === "live" ? "red" : s.state === "paused" ? "neutral" : "cyan"}>{s.state}</Badge>
                <span className="truncate">{s.name}</span>
              </div>
              <Cell className={s.pnl >= 0 ? "text-success" : "text-danger"}>{fmtUsd(s.pnl)}</Cell>
              <Cell>{s.trades}</Cell>
              <Cell>{(s.winRate * 100).toFixed(0)}%</Cell>
              <Cell className={s.profitFactor >= 1 ? "text-success" : "text-cyber-text-dim"}>{s.profitFactor.toFixed(2)}</Cell>
              <Cell className="text-danger">{fmtUsd(s.maxDrawdown)}</Cell>
            </RowGroup>
          ))}
        </div>
        {ranked.every((s) => s.trades === 0) && (
          <div className="mt-2 text-xs text-cyber-text-faint">No closed trades yet — stats populate as positions close.</div>
        )}
      </Card>

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
  return <div className="col-span-full grid grid-cols-[1fr_auto_auto_auto_auto_auto] gap-x-4 border-t border-cyber-border">{children}</div>;
}
