import { useStore } from "../store";
import { Button, Card, PageHeader, Badge, fmtUsd } from "../components/ui";

export function Positions() {
  const { positions, orders, flatten } = useStore();
  const recent = orders.slice(0, 25);

  return (
    <div className="animate-fade-in">
      <PageHeader title="Positions" subtitle="Open positions & recent orders across all venues" />

      <Card title="Open Positions" className="mb-4">
        {positions.length === 0 ? (
          <div className="py-6 text-center text-sm text-cyber-text-faint">
            No open positions. The engine will open some as strategies fire, or trade manually from Markets.
          </div>
        ) : (
          <div className="grid grid-cols-[1fr_auto_auto_auto_auto_auto] gap-x-4 text-sm">
            <Head>Market</Head>
            <Head right>Qty</Head>
            <Head right>Avg</Head>
            <Head right>Last</Head>
            <Head right>Unrealized</Head>
            <Head right>Action</Head>
            {positions.map((p) => (
              <RowGroup key={p.marketId}>
                <div className="flex items-center gap-2 py-2">
                  <Badge tone={p.qty >= 0 ? "green" : "red"}>{p.qty >= 0 ? "LONG" : "SHORT"}</Badge>
                  <span>{p.symbol}</span>
                </div>
                <Cell>{p.qty.toFixed(4)}</Cell>
                <Cell>{p.avgPrice.toLocaleString()}</Cell>
                <Cell>{p.lastPrice.toLocaleString()}</Cell>
                <Cell className={p.unrealized >= 0 ? "text-success" : "text-danger"}>
                  {fmtUsd(p.unrealized)}
                </Cell>
                <div className="flex items-center justify-end py-1.5">
                  <Button tone="neutral" onClick={() => flatten(p.marketId)} className="!px-2 !py-1">
                    Flatten
                  </Button>
                </div>
              </RowGroup>
            ))}
          </div>
        )}
      </Card>

      <Card title="Recent Orders">
        <div className="space-y-1 font-mono text-xs">
          {recent.length === 0 && <div className="text-cyber-text-faint">No orders yet.</div>}
          {recent.map((o) => (
            <div key={o.id} className="flex items-center gap-3 border-b border-cyber-border/50 py-1">
              <span className="text-cyber-text-faint">{new Date(o.ts).toLocaleTimeString()}</span>
              <span className={o.side === "buy" ? "text-success" : "text-danger"}>
                {o.side.toUpperCase()}
              </span>
              <span className="flex-1 text-cyber-text-dim">{o.marketId}</span>
              <span>{o.filledQty.toFixed(4)}</span>
              <Badge
                tone={
                  o.status === "filled" ? "green" : o.status === "rejected" ? "red" : "neutral"
                }
              >
                {o.status}
              </Badge>
              {o.rejectReason && <span className="text-danger">{o.rejectReason}</span>}
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}

function Head({ children, right }: { children: React.ReactNode; right?: boolean }) {
  return (
    <div className={`pb-2 text-xs uppercase text-cyber-text-faint ${right ? "text-right" : ""}`}>
      {children}
    </div>
  );
}
function Cell({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <div className={`py-2 text-right font-mono ${className}`}>{children}</div>;
}
function RowGroup({ children }: { children: React.ReactNode }) {
  return <div className="col-span-full grid grid-cols-[1fr_auto_auto_auto_auto_auto] gap-x-4 border-t border-cyber-border">{children}</div>;
}
