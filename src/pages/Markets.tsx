import { useState } from "react";
import { LineChart } from "lucide-react";
import { useStore } from "../store";
import { Button, Card, PageHeader, Badge, EmptyState, Notice, Term, fmtPct, inputCls } from "../components/ui";
import type { Venue } from "../types";

const venues: { id: Venue | "all"; label: string }[] = [
  { id: "all", label: "All" },
  { id: "polymarket", label: "Predictions" },
  { id: "crypto", label: "Crypto" },
  { id: "alpaca", label: "US shares" },
];

export function Markets() {
  const { markets, manualOrder, barBacked, live } = useStore();
  const [filter, setFilter] = useState<Venue | "all">("all");
  const [notional, setNotional] = useState(500);
  const [flash, setFlash] = useState<{ ok: boolean; text: string } | null>(null);

  const shown = markets.filter((m) => filter === "all" || m.venue === filter);
  // Hand orders are practice only. On a venue armed for live routing the engine
  // refuses them, so the buttons say so up front instead of failing on click.
  const lockedVenues = live.armed ? live.venues : [];
  const locked = (v: Venue) => lockedVenues.includes(v);
  const LOCK_REASON =
    "Locked while this venue is armed: hand orders never go live. Only a strategy with a green Strategy Passport, or the connection test on the Live page, sends a real order.";

  function order(id: string, symbol: string, side: "buy" | "sell") {
    const res = manualOrder(id, side, notional);
    setFlash(
      res === "ok"
        ? { ok: true, text: `Practice ${side} of $${notional.toLocaleString()} in ${symbol} sent.` }
        : { ok: false, text: `Refused: ${res}` },
    );
    setTimeout(() => setFlash(null), 3000);
  }

  return (
    <div className="animate-fade-in mx-auto max-w-6xl space-y-4">
      <PageHeader
        title="Markets"
        subtitle="Prediction, crypto and US share markets. Buy and Sell here place practice orders by hand."
      />

      <div className="flex flex-wrap items-end justify-between gap-3">
        <div role="radiogroup" aria-label="Show markets" className="flex flex-wrap gap-1.5">
          {venues.map((v) => (
            <button
              key={v.id}
              type="button"
              role="radio"
              aria-checked={filter === v.id}
              onClick={() => setFilter(v.id)}
              className={`rounded-lg border px-3 py-1 text-xs font-medium transition-colors ${
                filter === v.id
                  ? "border-accent/40 bg-accent/10 text-accent"
                  : "border-cyber-border text-cyber-text-dim hover:border-cyber-border-bright hover:text-cyber-text"
              }`}
            >
              {v.label}
            </button>
          ))}
        </div>
        <label className="flex items-center gap-2 text-xs text-cyber-text-dim">
          <Term k="Order size">Order size</Term>
          <span className="relative">
            <span className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-cyber-text-faint">$</span>
            <input
              type="number"
              min={1}
              value={notional}
              onChange={(e) => setNotional(Math.max(1, Number(e.target.value)))}
              className={`${inputCls} w-28 pl-5 font-mono`}
            />
          </span>
          <span className="text-cyber-text-faint">practice</span>
        </label>
      </div>

      {lockedVenues.length > 0 && (
        <Notice tone="warning" title={`Buy and Sell are locked for ${lockedVenues.join(", ")}`}>
          That venue is armed for real money, and hand orders never go live: only a strategy with a green Strategy
          Passport, or the connection test on the Live page, sends a real order. Disarm to practise by hand. Closing a
          position on the Positions page always works.
        </Notice>
      )}

      {flash && (
        <div
          role="status"
          className={`rounded-lg border px-3 py-2 text-sm ${
            flash.ok ? "border-accent/30 bg-accent/5 text-accent" : "border-danger/40 bg-danger/10 text-danger"
          }`}
        >
          {flash.text}
        </div>
      )}

      <Card>
        {shown.length === 0 ? (
          <EmptyState icon={LineChart} title="No markets here yet">
            Markets load within a few seconds of starting. Try the All filter.
          </EmptyState>
        ) : (
          <div className="-mx-1 overflow-x-auto px-1">
            <table className="w-full min-w-[640px] text-sm">
              <thead>
                <tr className="font-mono text-[11px] uppercase tracking-wider text-cyber-text-faint">
                  <th className="pb-2 text-left font-medium">Market</th>
                  <th className="pb-2 text-right font-medium">
                    <Term k="Price / Prob">Price / Prob</Term>
                  </th>
                  <th className="pb-2 text-right font-medium">
                    <Term k="24h">24h</Term>
                  </th>
                  <th className="pb-2 text-right font-medium">
                    <Term k="Model">Model</Term>
                  </th>
                  <th className="pb-2 text-right font-medium">Practice order</th>
                </tr>
              </thead>
              <tbody>
                {shown.map((m) => (
                  <tr key={m.id} className="border-t border-cyber-border">
                    <td className="py-2 pr-3">
                      <div className="flex flex-wrap items-center gap-1.5">
                        <Badge tone="neutral">
                          {m.venue === "polymarket" ? "pred" : m.venue === "crypto" ? "crypto" : "share"}
                        </Badge>
                        <span className="font-medium">{m.symbol}</span>
                        {/*
                          Whether a price is real or invented is the single most
                          important fact on this page. A simulated series produces
                          perfectly plausible indicators and a perfectly meaningless
                          equity curve, so it gets said out loud on every row rather
                          than being inferred from whether keys happen to be set.
                        */}
                        <Badge
                          tone={barBacked.has(m.id) ? "green" : "neutral"}
                          title={
                            barBacked.has(m.id)
                              ? "Indicators run on real exchange candles"
                              : "Simulated series: indicators here measure the simulator, not a market"
                          }
                        >
                          {barBacked.has(m.id) ? "real bars" : "sim"}
                        </Badge>
                        {m.regime && (
                          <Badge
                            tone="neutral"
                            title={`${m.regime === "trending" ? "Moving steadily in one direction" : "Going back and forth"}; trend strength ${(m.trendStrength ?? 0).toFixed(2)}`}
                          >
                            {m.regime}
                          </Badge>
                        )}
                      </div>
                    </td>
                    <td className="py-2 text-right font-mono">
                      {m.kind === "prediction" ? `${(m.price * 100).toFixed(1)}%` : m.price.toLocaleString()}
                    </td>
                    <td className={`py-2 text-right font-mono ${m.change24h >= 0 ? "text-success" : "text-danger"}`}>
                      {fmtPct(m.change24h)}
                    </td>
                    <td className="py-2 text-right font-mono text-purple-neon">
                      {m.modelProb != null ? `${(m.modelProb * 100).toFixed(0)}%` : <span className="text-cyber-text-faint">-</span>}
                    </td>
                    <td className="py-1.5 pl-3" title={locked(m.venue) ? LOCK_REASON : undefined}>
                      <div className="flex justify-end gap-1.5">
                        <Button
                          tone="green"
                          size="sm"
                          disabled={locked(m.venue)}
                          onClick={() => order(m.id, m.symbol, "buy")}
                          ariaLabel={`Practice buy ${m.symbol}`}
                        >
                          Buy
                        </Button>
                        <Button
                          tone="red"
                          size="sm"
                          disabled={locked(m.venue)}
                          onClick={() => order(m.id, m.symbol, "sell")}
                          ariaLabel={`Practice sell ${m.symbol}`}
                        >
                          Sell
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
