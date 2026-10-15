import { useEffect, useMemo, useState } from "react";
import { LineChart, Search, Sparkles } from "lucide-react";
import { Badge, Card, Change, Empty, List, ListRow, Notice, Page, Segmented, Sparkline, changeTone, inputCls } from "../design";
import { Nothing, Section } from "../pagekit";
import { AssetDetail, VENUE_WORD, priceText } from "../components/AssetDetail";
import { fmtWhen } from "../autopilot";
import { labStatus, listingGaps, listingRows, type ListingsFeed } from "../lab";
import { liveMode } from "../live";
import { useStore } from "../store";
import type { Venue } from "../types";

const LISTINGS_REFRESH_MS = 5 * 60_000;

type Filter = Venue | "all";

const FILTERS: { id: Filter; label: string }[] = [
  { id: "all", label: "All" },
  { id: "crypto", label: "Crypto" },
  { id: "alpaca", label: "Shares" },
  { id: "polymarket", label: "Predictions" },
];

/**
 * Every market Pythia watches, as a simple list: badge, name, price and the
 * day's change. Tapping one opens its detail with a chart and a practice
 * order.
 */
export function Markets() {
  const { markets, history, barBacked, live } = useStore();
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState<string | null>(null);

  const q = query.trim().toLowerCase();
  const shown = useMemo(
    () =>
      markets
        .filter((m) => filter === "all" || m.venue === filter)
        .filter((m) => !q || m.symbol.toLowerCase().includes(q) || m.id.toLowerCase().includes(q)),
    [markets, filter, q],
  );
  const lockedVenues = live.armed ? live.venues : [];

  if (open) {
    return (
      <div className="mx-auto w-full max-w-2xl pb-8">
        <AssetDetail marketId={open} onBack={() => setOpen(null)} />
      </div>
    );
  }

  return (
    <Page title="Markets" subtitle="Crypto, US shares and prediction markets. Open one for its chart and a practice order.">
      <div className="space-y-3">
        <label className="relative block">
          <span className="sr-only">Search markets</span>
          <Search size={17} aria-hidden className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-faint" />
          <input type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search" className={`${inputCls} pl-10`} />
        </label>
        <Segmented<Filter> label="Show markets" value={filter} onChange={setFilter} options={FILTERS} />
      </div>

      {lockedVenues.length > 0 && (
        <Notice tone="warning" title={`Hand orders are locked for ${lockedVenues.join(", ")}`}>
          That venue is armed for real money, and hand orders never go live. Closing a position on the Positions page always works.
        </Notice>
      )}

      <Card>
        {shown.length === 0 ? (
          <Empty icon={LineChart} title={markets.length === 0 ? "No markets yet" : "Nothing matches"} compact>
            {markets.length === 0 ? "Markets load within a few seconds of starting." : "Try another name or the All filter."}
          </Empty>
        ) : (
          <List className="-my-2">
            {shown.map((m) => {
              const pct = m.change24h * 100;
              const h = history[m.id] ?? [];
              return (
                <ListRow
                  key={m.id}
                  ticker={m.symbol}
                  title={m.symbol}
                  subtitle={`${VENUE_WORD[m.venue] ?? m.venue}${barBacked.has(m.id) ? "" : " · simulated"}`}
                  onClick={() => setOpen(m.id)}
                  right={
                    <span className="flex items-center gap-3">
                      <span className="hidden sm:block">
                        <Sparkline data={h.slice(-120)} tone={changeTone(pct)} width={72} height={28} label={`${m.symbol}, recent prices`} />
                      </span>
                      <span>{priceText(m)}</span>
                    </span>
                  }
                  rightSub={<Change pct={pct} tone={changeTone(pct)} size="sm" />}
                />
              );
            })}
          </List>
        )}
      </Card>
      <NewListings />
    </Page>
  );
}

/** What the lab's listings watcher saw in the last 90 days (reports/listings/latest.json). */
function NewListings() {
  const [feed, setFeed] = useState<ListingsFeed | null>(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    if (liveMode() === "none") return;
    let alive = true;
    const read = async () => {
      try {
        const s = await labStatus();
        if (alive) {
          setFeed(s.listings ?? null);
          setErr("");
        }
      } catch (e) {
        if (alive) setErr(e instanceof Error ? e.message : String(e));
      }
    };
    void read();
    const t = setInterval(() => void read(), LISTINGS_REFRESH_MS);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);

  const rows = listingRows(feed);
  const gaps = listingGaps(feed);

  return (
    <Section
      title="New listings"
      help="Coins a venue started trading, seen by the lab's watcher within 10 minutes. Information only: nothing is bought."
      hint={feed ? `Last look ${feed.generated}. Alpaca is the only venue Pythia trades on.` : "Coins a venue started trading. Information only: nothing is bought."}
    >
      {rows.length === 0 ? (
        <Nothing icon={Sparkles} title={feed ? "No new coins in the last 90 days" : "No listings feed yet"}>
          {feed
            ? "The watcher looks at Alpaca, Binance, Coinbase and Kraken every 10 minutes."
            : liveMode() === "none"
              ? "The feed needs the desktop app or a connected backend."
              : err || "The lab's watcher (lab.ops.listings) writes it every 10 minutes once it runs on the lab server."}
        </Nothing>
      ) : (
        <List>
          {rows.map((r) => (
            <ListRow
              key={r.key}
              ticker={r.coin}
              title={`${r.coin} on ${r.venue}`}
              subtitle={`${r.title ?? r.symbols.join(", ")} · seen ${fmtWhen(r.tsMs)}`}
              right={r.price ?? "n/a"}
              rightSub={
                <Badge tone={r.alpaca === "yes" ? "good" : "neutral"} title="Whether Alpaca, the venue Pythia trades on, lists it">
                  {r.alpaca === "yes" ? "On Alpaca" : r.alpaca === "no" ? "Not on Alpaca" : "Alpaca unknown"}
                </Badge>
              }
            />
          ))}
        </List>
      )}
      {gaps.length > 0 && <p className="mt-2 text-[13px] text-muted">Not read on the last look: {gaps.join("; ")}.</p>}
    </Section>
  );
}
