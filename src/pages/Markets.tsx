import { Fragment, useState } from "react";
import { useStore } from "../store";
import { Button, Card, PageHeader, Badge, fmtPct } from "../components/ui";
import type { Venue } from "../types";

const venues: (Venue | "all")[] = ["all", "polymarket", "crypto", "alpaca"];

export function Markets() {
  const { markets, manualOrder } = useStore();
  const [filter, setFilter] = useState<Venue | "all">("all");
  const [notional, setNotional] = useState(500);
  const [flash, setFlash] = useState<string>("");

  const shown = markets.filter((m) => filter === "all" || m.venue === filter);

  function order(id: string, side: "buy" | "sell") {
    const res = manualOrder(id, side, notional);
    setFlash(res === "ok" ? `${side.toUpperCase()} ${id} · ${notional} paper $` : `Rejected: ${res}`);
    setTimeout(() => setFlash(""), 2500);
  }

  return (
    <div className="animate-fade-in">
      <PageHeader title="Markets" subtitle="Prediction, crypto & equity markets · paper prices" />

      <div className="mb-4 flex items-center justify-between">
        <div className="flex gap-2">
          {venues.map((v) => (
            <button
              key={v}
              onClick={() => setFilter(v)}
              className={`rounded-lg border px-3 py-1 text-xs uppercase transition-colors ${
                filter === v
                  ? "border-accent/40 bg-accent/10 text-accent"
                  : "border-cyber-border text-cyber-text-dim hover:text-cyber-text"
              }`}
            >
              {v}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-2 text-xs text-cyber-text-dim">
          order size
          <input
            type="number"
            value={notional}
            onChange={(e) => setNotional(Math.max(1, Number(e.target.value)))}
            className="w-24 rounded border border-cyber-border bg-cyber-surface px-2 py-1 text-cyber-text focus:border-accent focus:outline-none"
          />
          <span className="text-cyber-text-faint">paper $</span>
        </div>
      </div>

      {flash && (
        <div className="mb-3 rounded-lg border border-accent/30 bg-accent/5 px-3 py-1.5 text-xs text-accent">
          {flash}
        </div>
      )}

      <Card>
        <div className="grid grid-cols-[1fr_auto_auto_auto_auto] gap-x-4 gap-y-1 text-sm">
          <div className="pb-2 text-xs uppercase text-cyber-text-faint">Market</div>
          <div className="pb-2 text-right text-xs uppercase text-cyber-text-faint">Price / Prob</div>
          <div className="pb-2 text-right text-xs uppercase text-cyber-text-faint">24h</div>
          <div className="pb-2 text-right text-xs uppercase text-cyber-text-faint">Model</div>
          <div className="pb-2 text-right text-xs uppercase text-cyber-text-faint">Action</div>

          {shown.map((m) => (
            <Fragment key={m.id}>
              <div className="flex items-center gap-2 border-t border-cyber-border py-2">
                <Badge tone={m.venue === "polymarket" ? "purple" : m.venue === "crypto" ? "cyan" : "neutral"}>
                  {m.venue.slice(0, 4)}
                </Badge>
                <span>{m.symbol}</span>
                {m.regime && (
                  <span title={`trend strength ${(m.trendStrength ?? 0).toFixed(2)}`}>
                    <Badge tone={m.regime === "trending" ? "green" : "neutral"}>{m.regime}</Badge>
                  </span>
                )}
              </div>
              <div className="border-t border-cyber-border py-2 text-right font-mono">
                {m.kind === "prediction" ? `${(m.price * 100).toFixed(1)}%` : m.price.toLocaleString()}
              </div>
              <div
                className={`border-t border-cyber-border py-2 text-right font-mono ${
                  m.change24h >= 0 ? "text-success" : "text-danger"
                }`}
              >
                {fmtPct(m.change24h)}
              </div>
              <div className="border-t border-cyber-border py-2 text-right font-mono text-purple-neon">
                {m.modelProb != null ? `${(m.modelProb * 100).toFixed(0)}%` : "—"}
              </div>
              <div className="flex justify-end gap-1.5 border-t border-cyber-border py-1.5">
                <Button tone="green" onClick={() => order(m.id, "buy")} className="!px-2 !py-1">
                  Buy
                </Button>
                <Button tone="red" onClick={() => order(m.id, "sell")} className="!px-2 !py-1">
                  Sell
                </Button>
              </div>
            </Fragment>
          ))}
        </div>
      </Card>
    </div>
  );
}
