import { useCallback, useEffect, useMemo, useState } from "react";
import { ExternalLink, Layers, RefreshCw, X } from "lucide-react";
import { Badge, Button, Card, EmptyState, Loading, Notice, PageHeader, Sparkline, inputCls } from "../components/ui";
import { liveMode } from "../live";
import {
  filterCards,
  headlineChange,
  money,
  pct,
  pokemonView,
  predLabel,
  sortCards,
  type CardSort,
  type PokemonCard,
  type PokemonData,
} from "../pokemon";

const SORTS: { id: CardSort; label: string }[] = [
  { id: "price", label: "Most valuable" },
  { id: "change", label: "Biggest moves" },
  { id: "forecast", label: "Best forecast" },
  { id: "cheap", label: "Cheapest vs similar" },
];

function tone(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v) || Math.abs(v) < 0.05) return "text-cyber-text-dim";
  return v > 0 ? "text-success" : "text-danger";
}

function Thumb({ src, alt, size = "h-14 w-10" }: { src: string | null; alt: string; size?: string }) {
  return src ? (
    <img src={src} alt={alt} loading="lazy" className={`${size} shrink-0 rounded object-cover`} />
  ) : (
    <div className={`${size} shrink-0 rounded bg-cyber-border`} aria-hidden />
  );
}

/** One row of the list: picture, name, price, change. Trade Republic plain. */
function Row({ c, onOpen }: { c: PokemonCard; onOpen: () => void }) {
  const ch = headlineChange(c);
  return (
    <button
      type="button"
      onClick={onOpen}
      className="flex w-full items-center gap-3 px-1 py-2.5 text-left transition-colors hover:bg-cyber-border/30"
    >
      <Thumb src={c.image} alt={c.name} />
      <div className="min-w-0 flex-1">
        <div className="truncate font-bold text-cyber-text">{c.name}</div>
        <div className="truncate text-xs text-cyber-text-faint">
          {c.set} {c.number ? `· ${c.number}` : ""} {c.rarity ? `· ${c.rarity}` : ""}
        </div>
      </div>
      <div className="shrink-0 text-right">
        <div className="font-mono font-bold tabular-nums text-cyber-text">{money(c.priceUsd)}</div>
        <div className={`font-mono text-xs tabular-nums ${tone(ch.pct)}`} title={ch.label}>
          {ch.pct == null ? " " : pct(ch.pct)}
        </div>
      </div>
      <div className="hidden w-24 shrink-0 text-right sm:block" title={`90-day forecast, ${predLabel(c.predSrc)}`}>
        <div className={`font-mono text-sm tabular-nums ${tone(c.pred90dPct)}`}>{pct(c.pred90dPct, 0)}</div>
        <div className="text-[10px] text-cyber-text-faint">90 d forecast</div>
      </div>
    </button>
  );
}

function Detail({ c, onClose }: { c: PokemonCard; onClose: () => void }) {
  const prices = c.history.map(([, p]) => p).filter((p): p is number => p != null);
  const ch = headlineChange(c);
  return (
    <Card
      title={c.name}
      subtitle={`${c.set ?? ""}${c.number ? ` · ${c.number}` : ""}${c.rarity ? ` · ${c.rarity}` : ""}`}
      right={
        <button type="button" onClick={onClose} aria-label="Close" className="text-cyber-text-faint hover:text-cyber-text">
          <X size={18} />
        </button>
      }
    >
      <div className="flex flex-col gap-4 sm:flex-row">
        <Thumb src={c.imageLarge ?? c.image} alt={c.name} size="h-72 w-52 self-center sm:self-start" />
        <div className="min-w-0 flex-1 space-y-4">
          <div>
            <div className="font-mono text-3xl font-bold tabular-nums text-cyber-text">{money(c.priceUsd)}</div>
            <div className={`font-mono text-sm ${tone(ch.pct)}`}>
              {ch.pct == null ? "No change yet" : `${pct(ch.pct)} · ${ch.label}`}
            </div>
            <div className="mt-1 text-xs text-cyber-text-faint">
              {c.priceSrc === "tcgplayer" ? `TCGplayer market${c.variant ? ` (${c.variant})` : ""}` : "Cardmarket trend in USD"}
              {c.cardmarketEur != null && ` · Cardmarket €${c.cardmarketEur.toFixed(2)}`}
              {c.spreadPct != null && ` · US ${pct(c.spreadPct, 0)} vs EU`}
            </div>
          </div>
          <Sparkline data={prices} tone="green" height={64} label={`Price of ${c.name} over our snapshots`} />
          <div className="grid grid-cols-3 gap-2 text-center">
            {[
              ["30 d forecast", pct(c.pred30dPct, 0), c.pred30dPct],
              ["90 d forecast", pct(c.pred90dPct, 0), c.pred90dPct],
              ["Fair value", money(c.fairUsd), c.fairGapPct],
            ].map(([label, text, v]) => (
              <div key={label as string} className="rounded-lg border border-cyber-border p-2">
                <div className={`font-mono text-sm font-bold ${tone(v as number | null)}`}>{text as string}</div>
                <div className="text-[10px] text-cyber-text-faint">{label as string}</div>
              </div>
            ))}
          </div>
          <p className="text-xs text-cyber-text-dim">
            Forecast: {predLabel(c.predSrc)}. Fair value is what similar cards (rarity, character, set age, art) cost
            {c.fairGapPct != null ? `; this one is ${pct(c.fairGapPct, 0)} from it` : ""}. A description, not a promise.
          </p>
          <div className="flex flex-wrap gap-3 text-xs">
            {c.tcgplayerUrl && (
              <a href={c.tcgplayerUrl} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-accent">
                TCGplayer <ExternalLink size={12} />
              </a>
            )}
            {c.cardmarketUrl && (
              <a href={c.cardmarketUrl} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-accent">
                Cardmarket <ExternalLink size={12} />
              </a>
            )}
          </div>
        </div>
      </div>
    </Card>
  );
}

function Collection({ d }: { d: PokemonData }) {
  const c = d.collection;
  if (!c.started) return null;
  return (
    <Card
      title="Paper collection"
      subtitle={`Play money, started ${c.started} with ${money(c.start, 0)}. It follows the forecasts once a month; costs of buying and selling cards by mail are taken off. Nothing is bought for real.`}
      right={<Badge tone="neutral">play money</Badge>}
    >
      <div className="flex items-end justify-between gap-3">
        <div>
          <div className="font-mono text-2xl font-bold tabular-nums text-cyber-text">{money(c.equity)}</div>
          <div className="text-xs text-cyber-text-faint">if sold today after costs · {money(c.equityMarket)} at market</div>
        </div>
        <div className={`font-mono text-lg font-bold ${tone(c.returnPct)}`}>{pct(c.returnPct, 2)}</div>
      </div>
      <div className="mt-3">
        <Sparkline data={c.curve.map(([, v]) => v)} tone={c.returnPct >= 0 ? "green" : "red"} height={48} />
      </div>
      {c.holdings.length > 0 && (
        <div className="mt-3 divide-y divide-cyber-border">
          {c.holdings.map((h) => (
            <div key={h.id} className="flex items-center gap-3 py-2">
              <Thumb src={h.image} alt={h.name} size="h-10 w-7" />
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm text-cyber-text">
                  {h.qty}x {h.name}
                </div>
                <div className="truncate text-xs text-cyber-text-faint">
                  {h.set} · since {h.bought} · {h.why}
                </div>
              </div>
              <div className="shrink-0 text-right">
                <div className="font-mono text-sm tabular-nums">{money(h.price)}</div>
                <div className={`font-mono text-xs ${tone(h.changePct)}`}>{pct(h.changePct)}</div>
              </div>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

export function Cards() {
  const mode = liveMode();
  const [d, setD] = useState<PokemonData | null>(null);
  const [found, setFound] = useState(true);
  const [err, setErr] = useState("");
  const [sort, setSort] = useState<CardSort>("price");
  const [q, setQ] = useState("");
  const [open, setOpen] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const v = await pokemonView();
      setD(v.data);
      setFound(v.found);
      setErr("");
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    if (mode !== "none") void refresh();
  }, [mode, refresh]);

  const list = useMemo(() => (d ? sortCards(filterCards(d.cards, q), sort).slice(0, 200) : []), [d, q, sort]);
  const selected = d?.cards.find((c) => c.id === open) ?? null;

  const header = (
    <PageHeader
      title="Cards"
      subtitle="Pokemon card prices, what moved and what the model expects. Data and play money only: you buy and sell by hand."
      right={
        mode !== "none" && (
          <Button tone="neutral" size="sm" icon={RefreshCw} onClick={() => void refresh()}>
            Refresh
          </Button>
        )
      }
    />
  );

  if (mode === "none") {
    return (
      <div className="animate-fade-in mx-auto max-w-4xl">
        {header}
        <Card>
          <EmptyState icon={Layers} title="The cards need the desktop app or a connected server">
            Prices are collected daily by the lab and read from its data folder, which this browser version cannot reach.
          </EmptyState>
        </Card>
      </div>
    );
  }

  return (
    <div className="animate-fade-in mx-auto max-w-4xl space-y-4">
      {header}
      {!d && !err && found && <Loading>Reading the card prices</Loading>}
      {err && (
        <Notice tone="danger" title="Could not read the cards">
          {err}
        </Notice>
      )}
      {!found && (
        <Notice tone="warning" title="No lab data found">
          Set PYTHIA_DATA to the folder the lab syncs to.
        </Notice>
      )}
      {found && !d && !err && (
        <Notice tone="info" title="No card prices yet">
          The daily collector (lab.collect.pokemon, then lab.pokemon.daily) has not written anything yet.
        </Notice>
      )}
      {d && (
        <>
          <Notice tone={d.model.validated ? "success" : "info"} title={`Prices of ${d.snapshot}`}>
            {d.model.sentence}
          </Notice>
          {selected && <Detail c={selected} onClose={() => setOpen(null)} />}
          <Card
            right={
              <input
                className={`${inputCls} w-40 sm:w-56`}
                placeholder="Search name or set"
                value={q}
                onChange={(e) => setQ(e.target.value)}
                aria-label="Search cards"
              />
            }
            title={`${d.cards.length} cards`}
            subtitle={`${d.historyDays} day${d.historyDays === 1 ? "" : "s"} of price history so far.`}
          >
            <div className="mb-2 flex flex-wrap gap-1.5" role="tablist" aria-label="Sort">
              {SORTS.map((s) => (
                <button
                  key={s.id}
                  type="button"
                  role="tab"
                  aria-selected={sort === s.id}
                  onClick={() => setSort(s.id)}
                  className={`rounded-full px-3 py-1 text-xs ${sort === s.id ? "bg-accent/20 text-accent" : "text-cyber-text-dim hover:text-cyber-text"}`}
                >
                  {s.label}
                </button>
              ))}
            </div>
            <div className="divide-y divide-cyber-border">
              {list.map((c) => (
                <Row key={c.id} c={c} onOpen={() => setOpen(c.id)} />
              ))}
              {list.length === 0 && <div className="py-6 text-center text-sm text-cyber-text-faint">No card matches.</div>}
            </div>
          </Card>
          <Collection d={d} />
        </>
      )}
    </div>
  );
}
