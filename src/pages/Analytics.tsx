import { useMemo } from "react";
import { AlertTriangle, TrendingDown, Trophy } from "lucide-react";
import { useStore } from "../store";
import { Card, PageHeader, Badge, EmptyState, Sparkline, MultiLineChart, Term, fmtUsd } from "../components/ui";
import { costWarning } from "../components/PnlBreakdown";
import { breakdown } from "../engine/costs";
import type { FillRoute, PnlBreakdown, SlippageRow, StrategyConfig } from "../types";

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
    <div className="animate-fade-in mx-auto max-w-6xl">
      <PageHeader
        title="Analytics"
        subtitle="How deep the dips were, which strategies earned their keep after costs, and every fill."
      />

      <Card
        title="Portfolio Drawdown"
        className="mb-4"
        right={
          <Badge tone={curMaxDD < -0.005 ? "amber" : "neutral"} title="The deepest dip below a high point so far">
            {curMaxDD.toFixed(2)}% worst
          </Badge>
        }
      >
        <Sparkline data={drawdown.length > 1 ? drawdown : [0, 0]} height={120} tone="red" label="Drawdown over the session" />
        <div className="mt-1 flex items-center gap-1 text-xs text-cyber-text-faint">
          <TrendingDown size={12} aria-hidden /> How far below its best point the account was, over this session. Zero
          is at the high.
        </div>
      </Card>

      <Card title="Strategy Equity Curves" className="mb-4">
        {(() => {
          const active = ranked.filter((s) => s.equityCurve.length > 1 && (s.pnl !== 0 || s.trades > 0));
          if (active.length === 0) {
            return (
              <EmptyState compact icon={TrendingDown} title="No curves yet">
                Each strategy's curve appears once it has closed a trade.
              </EmptyState>
            );
          }
          return <MultiLineChart height={180} series={active.map((s) => ({ label: s.name.split(" · ")[0], data: s.equityCurve }))} />;
        })()}
      </Card>

      <Card title="Strategy Leaderboard" icon={Trophy} className="mb-4">
        <div className="-mx-1 overflow-x-auto px-1">
          <div className="grid min-w-[680px] grid-cols-[1fr_auto_auto_auto_auto_auto_auto_auto] gap-x-4 text-sm">
            <Head>Strategy</Head>
            <Head right><Term>Gross</Term></Head>
            <Head right><Term>Costs</Term></Head>
            <Head right><Term>Net</Term></Head>
            <Head right><Term>Trades</Term></Head>
            <Head right><Term>Win</Term></Head>
            <Head right><Term>PF</Term></Head>
            <Head right><Term>maxDD</Term></Head>
            {ranked.map((s) => {
              const p = pnlOf(s);
              const warn = costWarning(p);
              return (
                <RowGroup key={s.id}>
                  <div className="flex items-center gap-2 py-2">
                    <Badge
                      tone={s.state === "live" ? "red" : s.state === "paused" ? "neutral" : s.state === "demo" ? "purple" : "cyan"}
                    >
                      {s.state}
                    </Badge>
                    <span className="truncate">{s.name}</span>
                    {warn && (
                      <span title={warn} aria-label={warn} className="text-warning">
                        <AlertTriangle size={13} aria-hidden />
                      </span>
                    )}
                  </div>
                  <Cell className={p.gross >= 0 ? "text-success" : "text-danger"}>{fmtUsd(p.gross)}</Cell>
                  <Cell className={warn ? "text-warning" : "text-cyber-text-dim"}>{p.costs > 0 ? `-${fmtUsd(p.costs)}` : fmtUsd(0)}</Cell>
                  <Cell className={p.net >= 0 ? "text-success" : "text-danger"}>{fmtUsd(p.net)}</Cell>
                  <Cell>{s.trades}</Cell>
                  <Cell>{(s.winRate * 100).toFixed(0)}%</Cell>
                  <Cell className={s.profitFactor >= 1 ? "text-success" : "text-cyber-text-dim"}>{s.profitFactor.toFixed(2)}</Cell>
                  <Cell className="text-cyber-text-dim">{fmtUsd(s.maxDrawdown)}</Cell>
                </RowGroup>
              );
            })}
          </div>
        </div>
        <div className="mt-2 text-xs text-cyber-text-faint">
          Gross is the closed trades at the quoted price; costs are their slippage plus every fee paid (an open
          position's entry fee shows before its P&amp;L does); net is what was kept. A warning sign marks a strategy
          whose costs exceed 40% of its gross.
        </div>
        {ranked.every((s) => s.trades === 0) && (
          <div className="mt-2 text-xs text-cyber-text-faint">No closed trades yet. The numbers fill in as positions close.</div>
        )}
      </Card>

      <SlippageCard rows={slippage} />

      <Card title="Trade Log">
        <div className="space-y-1 font-mono text-xs">
          {fills.length === 0 && <EmptyState compact icon={Trophy} title="No fills yet" />}
          {fills.map((o) => (
            <div key={o.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-cyber-border/40 py-1.5">
              <span className="text-cyber-text-faint">{new Date(o.ts).toLocaleTimeString()}</span>
              <span className={`font-bold ${o.side === "buy" ? "text-success" : "text-danger"}`}>{o.side.toUpperCase()}</span>
              <span className="min-w-0 flex-1 basis-32 truncate text-cyber-text-dim">{o.marketId}</span>
              <span>{o.filledQty.toFixed(4)}</span>
              <span className="text-cyber-text-faint">@ {o.avgFillPrice}</span>
              {o.route && o.route !== "paper" && (
                <Badge tone={o.route === "live" ? "red" : "purple"} title={ROUTE_HELP[o.route]}>
                  {o.route}
                </Badge>
              )}
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
  return (
    <div className={`pb-2 font-mono text-[11px] uppercase tracking-wider text-cyber-text-faint ${right ? "text-right" : ""}`}>
      {children}
    </div>
  );
}
function Cell({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <div className={`py-2 text-right font-mono ${className}`}>{children}</div>;
}
function RowGroup({ children }: { children: React.ReactNode }) {
  return <div className="col-span-full grid grid-cols-[1fr_auto_auto_auto_auto_auto_auto_auto] gap-x-4 border-t border-cyber-border">{children}</div>;
}

const ROUTE_HELP: Record<FillRoute, string> = {
  paper: "Simulated by Pythia: the live book walked, or the cost model",
  demo: "Filled by a venue's demo account: real API, virtual money",
  live: "Real money",
};

/**
 * Realised slippage against the cost model, per venue and route. This is the number that
 * says whether the backtests were fiction: if real fills cost far more than the
 * model assumed, every backtest built on the model was too optimistic.
 */
function SlippageCard({ rows }: { rows: SlippageRow[] }) {
  return (
    <Card title="Execution: realised vs modelled slippage" className="mb-4">
      {rows.length === 0 ? (
        <div className="text-xs text-cyber-text-faint">
          No fills measured yet. Every fill (paper on a real price, demo, live) is measured against the price when
          the order was decided, and compared with what the cost model expected. The comparison means something
          after 30 fills per venue and route.
        </div>
      ) : (
        <div className="-mx-1 overflow-x-auto px-1">
          <div className="grid min-w-[640px] grid-cols-[1fr_auto_auto_auto_auto_auto_auto] gap-x-4 text-sm">
            <Head>Venue</Head>
            <Head>Route</Head>
            <Head right>Fills</Head>
            <Head right>Median realised</Head>
            <Head right>Median modelled</Head>
            <Head right>Drift</Head>
            <Head right>Ratio</Head>
            {rows.map((r) => {
              const route = r.route ?? "live";
              return (
                <div
                  key={`${r.venue}:${route}`}
                  className="col-span-full grid grid-cols-[1fr_auto_auto_auto_auto_auto_auto] gap-x-4 border-t border-cyber-border"
                >
                  <div className="py-2 capitalize">{r.venue}</div>
                  <div className="py-2">
                    <Badge
                      tone={route === "live" ? "red" : route === "demo" ? "purple" : "cyan"}
                      title={ROUTE_HELP[route]}
                    >
                      {route}
                    </Badge>
                  </div>
                  <Cell>
                    {r.fills}
                    {!r.enough && <span className="ml-1 text-[10px] text-cyber-text-faint">(&lt;30)</span>}
                    {(r.liveFills ?? 0) > 0 && (
                      <span className="ml-1 text-[10px] text-cyber-text-faint" title="Modelled on a live order book instead of the calibrated default">
                        {r.liveFills} live book
                      </span>
                    )}
                    {(r.exhausted ?? 0) > 0 && (
                      <span className="ml-1 text-[10px] text-warning" title="Paper fills larger than the 20 book levels; the rest was priced by the impact model">
                        {r.exhausted} past book
                      </span>
                    )}
                  </Cell>
                  <Cell>{r.medianRealisedBps.toFixed(1)} bps</Cell>
                  <Cell className="text-cyber-text-dim">{r.medianModelledBps.toFixed(1)} bps</Cell>
                  <Cell className="text-cyber-text-dim">
                    {r.medianDriftBps === undefined ? "n/a" : `${r.medianDriftBps.toFixed(1)} bps`}
                  </Cell>
                  <Cell className={r.ratio === undefined ? "text-cyber-text-faint" : r.ratio <= 1.5 ? "text-success" : "text-danger"}>
                    {r.ratio === undefined ? "n/a" : `${r.ratio.toFixed(2)}x`}
                  </Cell>
                </div>
              );
            })}
          </div>
          <div className="mt-2 text-xs text-cyber-text-faint">
            Positive bps cost money. Paper rows walk the exchange's live order book level by level when one less
            than a minute old exists, so they are honest about size; demo rows are what a venue's demo account
            really filled; live rows are real money. A live or demo ratio above 1.5x means real fills cost more
            than the model assumed, and every backtest using the model is too optimistic for that venue. Drift is
            how far the book had moved from the signal price before the order was priced.
          </div>
        </div>
      )}
    </Card>
  );
}

/** A strategy's gross, costs and net. A config that never traded has no ledger yet. */
function pnlOf(s: StrategyConfig): PnlBreakdown {
  return s.ledger?.pnl ?? breakdown(s.pnl, 0);
}
