import { Package, ReceiptText } from "lucide-react";
import { useStore } from "../store";
import { Chip, ConfirmAction, KeyStats, Nothing, Note, PageShell, Rows, Section, Term, num, toneOf, usd } from "../pagekit";
import type { PositionView } from "../types";

export function Positions() {
  const { positions, orders, flatten, live } = useStore();
  const recent = orders.slice(0, 25);
  const stuck = positions.some((p) => p.live) && !live.armed;
  const unrealized = positions.reduce((a, p) => a + p.unrealized, 0);
  const held = positions.reduce((a, p) => a + Math.abs(p.qty) * p.lastPrice, 0);

  return (
    <PageShell title="Positions" subtitle="What it holds right now, and the orders it sent recently, across all venues.">
      <KeyStats
        items={[
          { label: "Unrealized", value: usd(unrealized), tone: toneOf(unrealized), sub: "gain or loss if everything were sold now" },
          { label: "Open positions", value: String(positions.length), help: "Markets it holds something in." },
          { label: "Held value", value: usd(held, 0), help: "What the open positions are worth at the last price." },
        ]}
      />

      {stuck && (
        <Note tone="bad" title="Real positions cannot be closed while disarmed">
          Those shares exist at the broker, and the simulator will not pretend to close them. Arm live execution again,
          or close them in the broker's own dashboard.
        </Note>
      )}

      <Section title="Open positions" hint="Flatten sells everything in that market. It asks first.">
        {positions.length === 0 ? (
          <Nothing icon={Package} title="Nothing held right now">
            The engine opens positions as strategies fire. You can also place a practice order by hand on the Markets
            page.
          </Nothing>
        ) : (
          <Rows>
            {positions.map((p) => (
              <PositionRow key={p.marketId} p={p} onFlatten={() => flatten(p.marketId)} />
            ))}
          </Rows>
        )}
      </Section>

      <Section title="Recent Orders" hint="The last 25 orders, newest first.">
        {recent.length === 0 ? (
          <Nothing icon={ReceiptText} title="No orders yet" />
        ) : (
          <Rows>
            {recent.map((o) => (
              <div key={o.id} className="py-3">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="text-[15px] font-semibold">
                      <span className={o.side === "buy" ? "fl-up" : "fl-down"}>{o.side === "buy" ? "Buy" : "Sell"}</span>{" "}
                      <span className="break-all">{o.marketId}</span>
                    </div>
                    <div className="fl-muted fl-num text-sm">
                      {new Date(o.ts).toLocaleTimeString()} · {num(o.filledQty, 4)} filled
                    </div>
                  </div>
                  <div className="flex shrink-0 flex-wrap justify-end gap-1">
                    {o.route === "demo" && <Chip title="Sent to a venue's demo account">Demo</Chip>}
                    {o.route === "live" && (
                      <Chip tone="bad" title="Real money">
                        Live
                      </Chip>
                    )}
                    <Chip tone={o.status === "filled" ? "good" : o.status === "rejected" ? "bad" : "neutral"}>{o.status}</Chip>
                  </div>
                </div>
                {o.rejectReason && <p className="fl-down mt-1 break-words text-sm">{o.rejectReason}</p>}
              </div>
            ))}
          </Rows>
        )}
      </Section>
    </PageShell>
  );
}

function PositionRow({ p, onFlatten }: { p: PositionView; onFlatten: () => void }) {
  const value = Math.abs(p.qty) * p.lastPrice;
  return (
    <div className="py-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-[15px] font-semibold">{p.symbol}</span>
            <Chip title={p.qty >= 0 ? "Bought: gains if the price rises" : "Sold short: gains if the price falls"}>{p.qty >= 0 ? "Long" : "Short"}</Chip>
            {/* Real shares behave differently from simulated ones: they can
                only be closed while live routing is armed. */}
            {p.live && (
              <Chip tone="bad" title="Bought with real money at the broker">
                Real
              </Chip>
            )}
            {p.demo && <Chip title="Filled by the venue's demo account: real API, virtual money">Demo</Chip>}
          </div>
          <div className="fl-muted fl-num mt-0.5 text-sm">
            <Term k="Qty">{num(p.qty, 4)}</Term> · <Term k="Avg">avg {p.avgPrice.toLocaleString()}</Term> · <Term k="Last">last {p.lastPrice.toLocaleString()}</Term>
          </div>
        </div>
        <div className="shrink-0 text-right">
          <div className={`fl-num text-[15px] font-semibold ${p.unrealized > 0 ? "fl-up" : p.unrealized < 0 ? "fl-down" : ""}`}>{usd(p.unrealized)}</div>
          <div className="fl-muted fl-num text-sm">{usd(value)}</div>
        </div>
      </div>
      <div className="mt-2 flex justify-end">
        <ConfirmAction
          title={p.live ? `Sell ${p.symbol} for real?` : `Close ${p.symbol}?`}
          danger={!!p.live}
          variant={p.live ? "danger" : "secondary"}
          question={
            p.live
              ? `Sell all ${Math.abs(p.qty).toFixed(4)} ${p.symbol} for real, at about ${usd(value)}? This sends a real order and cannot be undone.`
              : p.demo
                ? `Sell the demo position in ${p.symbol} at the demo venue, about ${usd(value)} of virtual money?`
                : `Close the practice position in ${p.symbol} at today's price, about ${usd(value)}?`
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
