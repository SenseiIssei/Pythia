import { Wallet, TrendingUp, Activity, Layers, Zap } from "lucide-react";
import { useStore } from "../store";
import { Card, PageHeader, Sparkline, StatCard, fmtUsd, Badge } from "../components/ui";

const venueLabel: Record<string, string> = {
  polymarket: "Polymarket",
  crypto: "Crypto",
  alpaca: "Alpaca",
};

export function Dashboard() {
  const { portfolio, journal, positions } = useStore();
  const dayPnl = portfolio.realizedPnl + portfolio.unrealizedPnl;
  const dayPnlPct = (dayPnl / portfolio.dayStartEquity) * 100;
  const feed = journal.slice(0, 12);

  return (
    <div className="animate-fade-in">
      <PageHeader title="Dashboard" subtitle="Live cockpit · paper engine running" />

      <div className="mb-5 grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard label="Equity" value={fmtUsd(portfolio.equity)} icon={Wallet} delay={0} />
        <StatCard
          label="Today's P&L"
          value={fmtUsd(dayPnl)}
          sub={`${dayPnlPct >= 0 ? "+" : ""}${dayPnlPct.toFixed(2)}%`}
          icon={TrendingUp}
          tone={dayPnl >= 0 ? "green" : "red"}
          delay={0.05}
        />
        <StatCard
          label="Open Exposure"
          value={fmtUsd(portfolio.grossExposure)}
          sub={`${positions.length} positions`}
          icon={Layers}
          tone="purple"
          delay={0.1}
        />
        <StatCard
          label="Unrealized"
          value={fmtUsd(portfolio.unrealizedPnl)}
          icon={Zap}
          tone={portfolio.unrealizedPnl >= 0 ? "green" : "red"}
          delay={0.15}
        />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Card title="Equity Curve" className="lg:col-span-2" right={<Badge tone="cyan">simulated</Badge>}>
          <Sparkline data={portfolio.equityCurve} height={160} tone={dayPnl >= 0 ? "green" : "red"} />
          <div className="mt-2 flex justify-between text-xs text-cyber-text-faint">
            <span>start {fmtUsd(portfolio.dayStartEquity, 0)}</span>
            <span>now {fmtUsd(portfolio.equity, 0)}</span>
          </div>
        </Card>

        <Card title="Venue Balances">
          <div className="space-y-3">
            {portfolio.balances.map((b) => (
              <div key={b.venue} className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="text-sm">{venueLabel[b.venue]}</span>
                  <Badge tone={b.connected ? "green" : "neutral"}>
                    {b.connected ? "connected" : "no keys"}
                  </Badge>
                </div>
                <span className="text-sm text-cyber-text-dim">{fmtUsd(b.equity, 0)}</span>
              </div>
            ))}
          </div>
        </Card>
      </div>

      <Card title="Live Activity" className="mt-4" right={<Activity size={14} className="text-accent" />}>
        <div className="space-y-1.5 font-mono text-xs">
          {feed.length === 0 && <div className="text-cyber-text-faint">Waiting for engine events…</div>}
          {feed.map((e) => (
            <div key={e.id} className="flex items-start gap-2">
              <span className="text-cyber-text-faint">{new Date(e.ts).toLocaleTimeString()}</span>
              <FeedTag kind={e.kind} />
              <span className="text-cyber-text-dim">{e.message}</span>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}

function FeedTag({ kind }: { kind: string }) {
  const map: Record<string, string> = {
    signal: "text-purple-neon",
    fill: "text-success",
    reject: "text-danger",
    risk: "text-warning",
    order: "text-accent",
    system: "text-cyber-text-faint",
  };
  return <span className={`w-14 shrink-0 uppercase ${map[kind] ?? "text-cyber-text-faint"}`}>{kind}</span>;
}
