import { Package, ReceiptText } from "lucide-react";
import { useStore } from "../store";
import { Badge, List, Notice, Page, changeTone, money } from "../design";
import { ConfirmAction, KeyStats, Nothing, Section, Term, num } from "../pagekit";
import type { PositionView } from "../types";

export function Positions() {
  const { positions, orders, flatten, live } = useStore();
  const recent = orders.slice(0, 25);
  const stuck = positions.some((p) => p.live) && !live.armed;
  const unrealized = positions.reduce((a, p) => a + p.unrealized, 0);
  const held = positions.reduce((a, p) => a + Math.abs(p.qty) * p.lastPrice, 0);

  return (
    <Page title="Positions" subtitle="What it holds right now, and the orders it sent recently, across all venues.">
      <KeyStats
        items={[
          { label: "Unrealized", value: money(unrealized), tone: changeTone(unrealized), sub: "gain or loss if everything were sold now" },
          { label: "Open positions", value: String(positions.length), help: "Markets it holds something in." },
          { label: "Held value", value: money(held, 0), help: "What the open positions are worth at the last price." },
        ]}
      />

      {stuck && (
        <Notice tone="danger" title="Real positions cannot be closed while disarmed">
          Those shares exist at the broker, and the simulator will not pretend to close them. Arm live execution again,
          or close them in the broker's own dashboard.
        </Notice>
      )}

      <Section title="Open positions" hint="Flatten sells everything in that market. It asks first.">
        {positions.length === 0 ? (
          <Nothing icon={Package} title="Nothing held right now">
            The engine opens positions as strategies fire. You can also place a practice order by hand on the Markets
            page.
          </Nothing>
        ) : (
          <List>
            {positions.map((p) => (
              <PositionRow key={p.key ?? p.marketId} p={p} onFlatten={() => flatten(p.key ?? p.marketId)} />
            ))}
          </List>
        )}
      </Section>

      <Section title="Recent Orders" hint="The last 25 orders, newest first.">
        {recent.length === 0 ? (
          <Nothing icon={ReceiptText} title="No orders yet" />
        ) : (
          <List>
            {recent.map((o) => (
              <div key={o.id} className="py-3">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="text-[15px] font-semibold text-ink">
                      <span className={o.side === "buy" ? "text-up" : "text-down"}>{o.side === "buy" ? "Buy" : "Sell"}</span>{" "}
                      <span className="break-all">{o.marketId}</span>
                    </div>
                    <div className="tabular text-[13px] text-muted">
                      {new Date(o.ts).toLocaleTimeString()} · {num(o.filledQty, 4)} filled
                    </div>
                  </div>
                  <div className="flex shrink-0 flex-wrap justify-end gap-1">
                    {o.route === "demo" && (
                      <Badge tone="accent" title="Sent to a venue's demo account">
                        Demo
                      </Badge>
                    )}
                    {o.route === "live" && (
                      <Badge tone="bad" title="Real money">
                        Live
                      </Badge>
                    )}
                    <Badge tone={o.status === "filled" ? "good" : o.status === "rejected" ? "bad" : "neutral"}>{o.status}</Badge>
                  </div>
                </div>
                {o.rejectReason && <p className="mt-1 break-words text-[13px] text-down">{o.rejectReason}</p>}
              </div>
            ))}
          </List>
        )}
      </Section>
    </Page>
  );
}

function PositionRow({ p, onFlatten }: { p: PositionView; onFlatten: () => void }) {
  const value = Math.abs(p.qty) * p.lastPrice;
  return (
    <div className="py-3.5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-[15px] font-semibold text-ink">{p.symbol}</span>
            <Badge title={p.qty >= 0 ? "Bought: gains if the price rises" : "Sold short: gains if the price falls"}>{p.qty >= 0 ? "Long" : "Short"}</Badge>
            {/* Real shares behave differently from simulated ones: they can
                only be closed while live routing is armed. */}
            {p.live && (
              <Badge tone="bad" title="Bought with real money at the broker">
                Real
              </Badge>
            )}
            {p.demo && (
              <Badge tone="accent" title="Filled by the venue's demo account: real API, virtual money">
                Demo
              </Badge>
            )}
          </div>
          {/* Every autopilot keeps a book of its own: two can hold the same coin. */}
          {p.book && <div className="mt-0.5 text-[13px] text-muted">Autopilot {p.bookName ?? p.book}</div>}
          <div className="tabular mt-0.5 text-[13px] text-muted">
            <Term k="Qty">{num(p.qty, 4)}</Term> · <Term k="Avg">avg {p.avgPrice.toLocaleString()}</Term> ·{" "}
            <Term k="Last">last {p.lastPrice.toLocaleString()}</Term>
          </div>
        </div>
        <div className="shrink-0 text-right">
          <div className={`tabular text-[15px] font-semibold ${p.unrealized > 0 ? "text-up" : p.unrealized < 0 ? "text-down" : "text-ink"}`}>{money(p.unrealized)}</div>
          <div className="tabular text-[13px] text-muted">{money(value)}</div>
        </div>
      </div>
      <div className="mt-2 flex justify-end">
        <ConfirmAction
          title={p.live ? `Sell ${p.symbol} for real?` : `Close ${p.symbol}?`}
          danger={!!p.live}
          variant={p.live ? "danger" : "secondary"}
          size="sm"
          question={
            p.live
              ? `Sell all ${Math.abs(p.qty).toFixed(4)} ${p.symbol} for real, at about ${money(value)}? This sends a real order and cannot be undone.`
              : p.demo
                ? `Sell the demo position in ${p.symbol} at the demo venue, about ${money(value)} of virtual money?`
                : `Close the practice position in ${p.symbol} at today's price, about ${money(value)}?`
          }
          confirmLabel={p.live ? "Yes, sell for real" : "Close it"}
          onConfirm={onFlatten}
        >
          Flatten
        </ConfirmAction>
      </div>
    </div>
  );
}
