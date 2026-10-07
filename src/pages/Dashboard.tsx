import { Wallet, TrendingUp, Activity, Layers, Zap } from "lucide-react";
import { useStore } from "../store";
import { Card, PageHeader, Sparkline, StatCard, fmtUsd, Badge, EmptyState, pnlTone } from "../components/ui";

const venueLabel: Record<string, string> = {
  polymarket: "Polymarket",
  crypto: "Crypto",
  alpaca: "Alpaca (US shares)",
};

/** What each journal kind means, for the tag's tooltip. */
const KIND_HELP: Record<string, string> = {
  signal: "A strategy decided it wants to buy or sell.",
  order: "An order was sent.",
  fill: "An order was filled: the trade happened.",
  reject: "An order was refused, with the reason.",
  risk: "The risk manager stepped in or a limit changed.",
  system: "Something about the engine itself.",
};

export function Dashboard() {
  const { portfolio, journal, positions } = useStore();
  const dayPnl = portfolio.realizedPnl + portfolio.unrealizedPnl;
  const dayPnlPct = portfolio.dayStartEquity > 0 ? (dayPnl / portfolio.dayStartEquity) * 100 : 0;
  const feed = journal.slice(0, 12);
  const live = portfolio.mode === "live";

  return (
    <div className="animate-fade-in mx-auto max-w-6xl space-y-4">
      <PageHeader
        title="Dashboard"
        subtitle={live ? "Live cockpit: real orders may be placed." : "Live cockpit on the paper engine: simulated money."}
      />

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatCard label="Equity" value={fmtUsd(portfolio.equity)} icon={Wallet} delay={0} />
        <StatCard
          label="Today's P&L"
          value={fmtUsd(dayPnl)}
          sub={`${dayPnlPct >= 0 ? "+" : ""}${dayPnlPct.toFixed(2)}% today`}
          icon={TrendingUp}
          tone={pnlTone(dayPnl)}
          delay={0.05}
        />
        <StatCard
          label="Open Exposure"
          value={fmtUsd(portfolio.grossExposure)}
          sub={`${positions.length} position${positions.length === 1 ? "" : "s"}`}
          icon={Layers}
          delay={0.1}
        />
        <StatCard
          label="Unrealized"
          value={fmtUsd(portfolio.unrealizedPnl)}
          icon={Zap}
          tone={pnlTone(portfolio.unrealizedPnl)}
          delay={0.15}
        />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Card
          title="Equity Curve"
          className="lg:col-span-2"
          right={<Badge tone={live ? "red" : "neutral"}>{live ? "live" : "simulated"}</Badge>}
        >
          <Sparkline data={portfolio.equityCurve} height={160} tone={dayPnl >= 0 ? "green" : "red"} label="Equity over this session" />
          <div className="mt-2 flex justify-between font-mono text-xs text-cyber-text-faint">
            <span>start {fmtUsd(portfolio.dayStartEquity, 0)}</span>
            <span>now {fmtUsd(portfolio.equity, 0)}</span>
          </div>
        </Card>

        <Card title="Venue Balances">
          {portfolio.balances.length === 0 ? (
            <EmptyState compact icon={Wallet} title="No venues yet" />
          ) : (
            <div className="space-y-3">
              {portfolio.balances.map((b) => (
                <div key={b.venue} className="flex items-center justify-between gap-2">
                  <div className="flex min-w-0 flex-wrap items-center gap-2">
                    <span className="text-sm">{venueLabel[b.venue] ?? b.venue}</span>
                    <Badge
                      tone={b.connected ? "green" : "neutral"}
                      title={b.connected ? "Keys are set, so real data or orders can reach it" : "No keys: simulated"}
                    >
                      {b.connected ? "connected" : "simulated"}
                    </Badge>
                  </div>
                  <span className="font-mono text-sm text-cyber-text-dim">{fmtUsd(b.equity, 0)}</span>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>

      <Card title="Live Activity" icon={Activity}>
        {feed.length === 0 ? (
          <EmptyState compact icon={Activity} title="Waiting for the first engine events" />
        ) : (
          <ul className="space-y-1.5 text-xs">
            {feed.map((e) => (
              <li key={e.id} className="flex flex-wrap items-start gap-x-2 gap-y-0.5 sm:flex-nowrap">
                <span className="w-16 shrink-0 font-mono text-cyber-text-faint">{new Date(e.ts).toLocaleTimeString()}</span>
                <FeedTag kind={e.kind} />
                <span className="min-w-0 basis-full break-words text-cyber-text-dim sm:basis-auto">{e.message}</span>
              </li>
            ))}
          </ul>
        )}
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
  return (
    <span
      title={KIND_HELP[kind]}
      className={`w-14 shrink-0 font-mono uppercase ${map[kind] ?? "text-cyber-text-faint"}`}
    >
      {kind}
    </span>
  );
}
