import { Package, ReceiptText } from "lucide-react";
import { useStore } from "../store";
import { Card, PageHeader, Badge, EmptyState, Notice, Term, fmtUsd } from "../components/ui";
import { ConfirmButton } from "../components/Confirm";

export function Positions() {
  const { positions, orders, flatten, live } = useStore();
  const recent = orders.slice(0, 25);
  const stuck = positions.some((p) => p.live) && !live.armed;

  return (
    <div className="animate-fade-in mx-auto max-w-6xl space-y-4">
      <PageHeader title="Positions" subtitle="What it holds right now, and the orders it sent recently, across all venues." />

      {stuck && (
        <Notice tone="danger" title="Real positions cannot be closed while disarmed">
          Those shares exist at the broker, and the simulator will not pretend to close them. Arm live execution again,
          or close them in the broker's own dashboard.
        </Notice>
      )}

      <Card title="Open positions" icon={Package}>
        {positions.length === 0 ? (
          <EmptyState icon={Package} title="Nothing held right now">
            The engine opens positions as strategies fire. You can also place a practice order by hand on the Markets
            page.
          </EmptyState>
        ) : (
          <div className="-mx-1 overflow-x-auto px-1">
            <table className="w-full min-w-[620px] text-sm">
              <thead>
                <tr className="font-mono text-[11px] uppercase tracking-wider text-cyber-text-faint">
                  <th className="pb-2 text-left font-medium">Market</th>
                  <th className="pb-2 text-right font-medium"><Term>Qty</Term></th>
                  <th className="pb-2 text-right font-medium"><Term>Avg</Term></th>
                  <th className="pb-2 text-right font-medium"><Term>Last</Term></th>
                  <th className="pb-2 text-right font-medium"><Term>Unrealized</Term></th>
                  <th className="pb-2 text-right font-medium"><Term>Flatten</Term></th>
                </tr>
              </thead>
              <tbody>
                {positions.map((p) => (
                  <tr key={p.marketId} className="border-t border-cyber-border">
                    <td className="py-2 pr-3">
                      <div className="flex flex-wrap items-center gap-1.5">
                        <Badge
                          tone="neutral"
                          title={p.qty >= 0 ? "Bought: gains if the price rises" : "Sold short: gains if the price falls"}
                        >
                          {p.qty >= 0 ? "LONG" : "SHORT"}
                        </Badge>
                        <span className="font-medium">{p.symbol}</span>
                        {/* Real shares behave differently from simulated ones: they
                            can only be closed while live routing is armed. */}
                        {p.live && (
                          <Badge tone="red" title="Bought with real money at the broker">
                            REAL
                          </Badge>
                        )}
                      </div>
                    </td>
                    <td className="py-2 text-right font-mono">{p.qty.toFixed(4)}</td>
                    <td className="py-2 text-right font-mono text-cyber-text-dim">{p.avgPrice.toLocaleString()}</td>
                    <td className="py-2 text-right font-mono">{p.lastPrice.toLocaleString()}</td>
                    <td className={`py-2 text-right font-mono ${p.unrealized >= 0 ? "text-success" : "text-danger"}`}>
                      {fmtUsd(p.unrealized)}
                    </td>
                    <td className="py-1.5 pl-3 text-right">
                      <ConfirmButton
                        tone={p.live ? "red" : "neutral"}
                        className="!px-2.5 !py-1 !text-xs"
                        question={
                          p.live
                            ? `Sell all ${Math.abs(p.qty).toFixed(4)} ${p.symbol} for real, at about ${fmtUsd(Math.abs(p.qty) * p.lastPrice)}? This sends a real order and cannot be undone.`
                            : `Close the practice position in ${p.symbol} at today's price, about ${fmtUsd(Math.abs(p.qty) * p.lastPrice)}?`
                        }
                        confirmLabel={p.live ? "Yes, sell for real" : "Close it"}
                        onConfirm={() => flatten(p.marketId)}
                      >
                        Flatten
                      </ConfirmButton>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card title="Recent Orders" icon={ReceiptText}>
        {recent.length === 0 ? (
          <EmptyState compact icon={ReceiptText} title="No orders yet" />
        ) : (
          <ul className="divide-y divide-cyber-border/60 text-xs">
            {recent.map((o) => (
              <li key={o.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-1.5">
                <span className="font-mono text-cyber-text-faint">{new Date(o.ts).toLocaleTimeString()}</span>
                <span className={`font-mono font-bold ${o.side === "buy" ? "text-success" : "text-danger"}`}>
                  {o.side.toUpperCase()}
                </span>
                <span className="min-w-0 flex-1 truncate font-mono text-cyber-text-dim">{o.marketId}</span>
                <span className="font-mono">{o.filledQty.toFixed(4)}</span>
                <Badge tone={o.status === "filled" ? "green" : o.status === "rejected" ? "red" : "neutral"}>{o.status}</Badge>
                {o.rejectReason && <span className="basis-full text-danger sm:basis-auto">{o.rejectReason}</span>}
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
