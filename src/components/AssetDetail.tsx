import { useState } from "react";
import { ArrowLeft } from "lucide-react";
import {
  AreaChart,
  Badge,
  BigNumber,
  Button,
  Card,
  Change,
  Field,
  List,
  ListRow,
  Notice,
  RangeChips,
  Sheet,
  Stat,
  TickerBadge,
  changeTone,
  inputCls,
  money,
  price,
  type Range,
} from "../design";
import { inRange, usefulRanges, type Point } from "../flows/homeView";
import { useStore } from "../store";
import { useAdvanced } from "../uiMode";
import type { Market, Venue } from "../types";

export const VENUE_WORD: Record<Venue, string> = {
  polymarket: "Prediction",
  crypto: "Crypto",
  alpaca: "US share",
  perps: "Perp",
} as Record<Venue, string>;

/** A prediction market's price is a chance; everything else is dollars. */
export function priceText(m: Pick<Market, "kind" | "price">): string {
  return m.kind === "prediction" ? `${(m.price * 100).toFixed(1)}%` : price(m.price);
}

const AMOUNTS = [100, 500, 1000];

/**
 * One asset, the way a banking app shows it: price first, the change, a
 * chart with ranges, what you hold, and a practice order. Used as the detail
 * view on Markets and in a sheet from Home.
 */
export function AssetDetail({ marketId, onBack }: { marketId: string; onBack?: () => void }) {
  const { markets, history, historyTimes, positions, manualOrder, barBacked, live } = useStore();
  const advanced = useAdvanced();
  const [range, setRange] = useState<Range>("1D");
  const [scrub, setScrub] = useState<number | null>(null);
  const [amount, setAmount] = useState("500");
  const [flash, setFlash] = useState<{ ok: boolean; text: string } | null>(null);
  const m = markets.find((x) => x.id === marketId);
  if (!m) {
    return <Notice tone="info">This market is not in the list right now. It comes back when its prices arrive again.</Notice>;
  }

  const closes = history[m.id] ?? [];
  const times = historyTimes[m.id];
  const now = Date.now();
  const timed: Point[] | null = times && times.length === closes.length ? times.map((t, i) => [t, closes[i]] as Point) : null;
  const ranges = timed ? usefulRanges(timed, now) : (["Max"] as Range[]);
  const shownRange: Range = ranges.includes(range) ? range : "Max";
  const pts = timed ? inRange(timed, shownRange, timed[timed.length - 1]?.[0] ?? now) : null;
  const values = pts ? pts.map((p) => p[1]) : closes;
  const first = values[0];
  const pct = timed && values.length > 1 && first ? ((values[values.length - 1] - first) / first) * 100 : m.change24h * 100;
  const words = timed ? (shownRange === "Max" ? "shown" : shownRange === "1D" ? "past day" : `past ${shownRange === "1W" ? "week" : shownRange === "1M" ? "month" : "year"}`) : "24h";

  const shown = scrub != null && values[scrub] != null ? values[scrub] : m.price;
  const pos = positions.find((p) => p.marketId === m.id && Math.abs(p.qty) > 1e-12);
  const locked = live.armed && live.venues.includes(m.venue);
  const real = barBacked.has(m.id);
  const notional = Number(amount);
  const amountOk = Number.isFinite(notional) && notional >= 1;

  function order(side: "buy" | "sell") {
    if (!m || !amountOk) return;
    const res = manualOrder(m.id, side, notional);
    setFlash(res === "ok" ? { ok: true, text: `Practice ${side === "buy" ? "buy" : "sale"} of ${money(notional, 0)} in ${m.symbol} sent.` } : { ok: false, text: `Refused: ${res}` });
    window.setTimeout(() => setFlash(null), 3500);
  }

  return (
    <div className="space-y-5">
      <div className="flex items-center gap-3">
        {onBack && (
          <button type="button" onClick={onBack} aria-label="Back to markets" className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-surface-2 text-ink hover:bg-line">
            <ArrowLeft size={17} aria-hidden />
          </button>
        )}
        <TickerBadge symbol={m.symbol} size={44} />
        <div className="min-w-0">
          <h2 className="truncate text-xl font-bold tracking-tight text-ink">{m.symbol}</h2>
          <div className="mt-0.5 flex flex-wrap items-center gap-1.5">
            <span className="text-[13px] text-muted">{VENUE_WORD[m.venue] ?? m.venue}</span>
            {/* Whether a price is real or invented is the most important fact here. */}
            <Badge tone={real ? "good" : "neutral"} title={real ? "Indicators run on real exchange candles" : "Simulated series: indicators here measure the simulator, not a market"}>
              {real ? "Real prices" : "Simulated"}
            </Badge>
          </div>
        </div>
      </div>

      <div className="space-y-4">
        <BigNumber
          size="lg"
          label={m.kind === "prediction" ? "Chance the market gives it" : "Price"}
          value={m.kind === "prediction" ? `${(shown * 100).toFixed(1)}%` : price(shown)}
          sub={<Change pct={pct} tone={changeTone(pct, 0.005)} suffix={words} />}
        />
        <AreaChart
          data={values}
          height={180}
          label={`${m.symbol} price, ${pct >= 0 ? "up" : "down"} ${Math.abs(pct).toFixed(2)} percent`}
          baseline={values.length > 1 ? values[0] : undefined}
          onScrub={(s) => setScrub(s ? s.index : null)}
        />
        {timed && ranges.length > 1 && <RangeChips value={shownRange} onChange={setRange} disabled={(["1D", "1W", "1M", "1Y"] as Range[]).filter((r) => !ranges.includes(r))} />}
      </div>

      {pos && (
        <Card title="Your position">
          <div className="grid grid-cols-3 gap-3">
            <Stat label="Holding" value={Number(pos.qty.toFixed(6)).toLocaleString("en-US")} />
            <Stat label="Worth" value={money(pos.qty * pos.lastPrice)} />
            <Stat label="Gain" value={<Change usd={pos.unrealized} tone={changeTone(pos.unrealized)} size="sm" />} />
          </div>
          {pos.live && <p className="mt-3 text-[13px] text-down">Bought with real money at the broker.</p>}
        </Card>
      )}

      <Card title="Practice order">
        {locked ? (
          <Notice tone="warning" title="Locked while this venue is armed">
            Hand orders never go live. Only a strategy with a green Strategy Passport, or the connection test on the Live page, sends a real order. Disarm to practise by hand.
          </Notice>
        ) : (
          <div className="space-y-4">
            <Field label="Amount in practice dollars">
              <div className="flex flex-wrap gap-2">
                <div className="relative min-w-[120px] flex-1">
                  <span className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-faint">$</span>
                  <input type="number" min={1} inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} className={`${inputCls} tabular pl-7`} />
                </div>
                {AMOUNTS.map((a) => (
                  <button
                    key={a}
                    type="button"
                    onClick={() => setAmount(String(a))}
                    aria-pressed={notional === a}
                    className={`min-h-[44px] rounded-control px-3 text-[13px] font-semibold ${notional === a ? "bg-primary text-on-primary" : "bg-surface-2 text-ink hover:bg-line"}`}
                  >
                    {money(a, 0)}
                  </button>
                ))}
              </div>
            </Field>
            <div className="grid grid-cols-2 gap-2">
              <Button full onClick={() => order("buy")} disabled={!amountOk}>
                Buy
              </Button>
              <Button full variant="secondary" onClick={() => order("sell")} disabled={!amountOk}>
                Sell
              </Button>
            </div>
            <p className="text-[13px] text-faint">Practice money on real prices. Nothing real is bought or sold.</p>
          </div>
        )}
        {flash && (
          <p role="status" className={`mt-3 text-[13px] font-medium ${flash.ok ? "text-up" : "text-down"}`}>
            {flash.text}
          </p>
        )}
      </Card>

      <Card title="About">
        <List className="-my-2">
          <ListRow title="Market" right={<span className="font-normal text-muted">{VENUE_WORD[m.venue] ?? m.venue}</span>} />
          <ListRow title="Change in 24 hours" right={<Change pct={m.change24h * 100} tone={changeTone(m.change24h * 100)} size="sm" />} />
          {m.modelProb != null && <ListRow title="Pythia's estimate" right={`${(m.modelProb * 100).toFixed(0)}%`} />}
          {m.regime && <ListRow title="How it moves" subtitle={m.regime === "trending" ? "Steadily in one direction" : "Back and forth"} right={advanced && m.trendStrength != null ? m.trendStrength.toFixed(2) : undefined} />}
          {m.liquidity != null && <ListRow title="Liquidity" right={money(m.liquidity, 0)} />}
          <ListRow title="Last update" right={<span className="font-normal text-muted">{new Date(m.updatedAt).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })}</span>} />
        </List>
      </Card>
    </div>
  );
}

/** The detail in a sheet, for opening an asset from anywhere. */
export function AssetSheet({ marketId, onClose }: { marketId: string | null; onClose: () => void }) {
  return (
    <Sheet open={marketId != null} onClose={onClose} title="Details" wide>
      {marketId && <AssetDetail marketId={marketId} />}
    </Sheet>
  );
}
