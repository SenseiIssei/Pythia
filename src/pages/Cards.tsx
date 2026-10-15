// Pokemon cards from the lab: prices, what moved, what the forecast expects,
// and a play-money collection that follows it. Read-only: nothing on this page
// can buy or sell a card; the owner trades by hand.

import { useCallback, useEffect, useMemo, useState } from "react";
import { ExternalLink, Layers, RefreshCw, Search } from "lucide-react";
import {
  AreaChart,
  Badge,
  BigNumber,
  Button,
  Card,
  Change,
  List,
  ListRow,
  Notice,
  Page,
  Sheet,
  Sparkline,
  Stat,
  changeTone,
  inputCls,
  money,
  signedPct,
} from "../design";
import { FilterChips, KeyStats, LoadingRows, More, Nothing, Row, Section, plural, type ChipOption, type Stat as KeyStat } from "../pagekit";
import { liveMode } from "../live";
import {
  DAYS_FOR_A_TEST,
  cardmarketStale,
  filterCards,
  headlineChange,
  pokemonView,
  predLabel,
  priceHistory,
  rowFigure,
  sortCards,
  type CardSort,
  type PokemonCard,
  type PokemonData,
} from "../pokemon";

const SORTS: ChipOption<CardSort>[] = [
  { id: "price", label: "Most valuable" },
  { id: "change", label: "Biggest moves" },
  { id: "forecast", label: "Best forecast", help: "Highest 90-day forecast first" },
  { id: "cheap", label: "Cheap vs similar", help: "Furthest below what similar cards cost" },
];

const PAGE_SIZE = 40;

const usd = (v: number | null | undefined, dp = 2) => (v == null || !Number.isFinite(v) ? "n/a" : money(v, dp));

/** The card's picture from the API, or a quiet placeholder of the same shape. */
function Thumb({ src, alt, large }: { src: string | null; alt: string; large?: boolean }) {
  const size = large ? "w-48 sm:w-56" : "h-14 w-10";
  return src ? (
    <img src={src} alt={alt} loading="lazy" className={`${size} shrink-0 rounded-lg bg-surface-2 object-cover`} />
  ) : (
    <div className={`${size} ${large ? "aspect-[63/88]" : ""} flex shrink-0 items-center justify-center rounded-lg bg-surface-2 text-faint`} aria-hidden>
      <Layers size={large ? 28 : 16} />
    </div>
  );
}

function Figure({ pct, suffix }: { pct: number | null; suffix: string }) {
  if (pct == null || !Number.isFinite(pct)) return <span className="text-[13px] text-faint">no change yet</span>;
  return <Change pct={pct} tone={changeTone(pct, 0.05)} size="sm" suffix={suffix} />;
}

function CardRow({ c, sort, onOpen }: { c: PokemonCard; sort: CardSort; onOpen: () => void }) {
  const f = rowFigure(c, sort);
  return (
    <ListRow
      leading={<Thumb src={c.image} alt="" />}
      title={c.name}
      subtitle={[c.set, c.number ? `#${c.number}` : null, c.rarity].filter(Boolean).join(" · ")}
      right={usd(c.priceUsd)}
      rightSub={<Figure pct={f.pct} suffix={f.suffix} />}
      onClick={onOpen}
    />
  );
}

function Detail({ c, stale }: { c: PokemonCard; stale: boolean }) {
  const hist = priceHistory(c);
  const ch = headlineChange(c);
  const [at, setAt] = useState<number | null>(null);
  const shown = at != null ? hist[at] : c.priceUsd;
  const when = at != null ? c.history.filter(([, p]) => p != null)[at]?.[0] : null;
  const cmFresh = c.cardmarketFresh ?? !stale;
  return (
    <div className="space-y-5">
      <div className="flex flex-col items-center gap-5 sm:flex-row sm:items-start">
        <Thumb src={c.imageLarge ?? c.image} alt={c.name} large />
        <div className="w-full min-w-0 flex-1 space-y-4">
          <div className="text-[13px] text-muted">{[c.set, c.number ? `#${c.number}` : null, c.rarity].filter(Boolean).join(" · ")}</div>
          <BigNumber
            value={usd(shown)}
            label={when ? `On ${when}` : c.priceSrc === "tcgplayer" ? `TCGplayer market${c.variant ? `, ${c.variant}` : ""}` : "Cardmarket trend in dollars"}
            sub={ch.pct != null ? <Change pct={ch.pct} tone={changeTone(ch.pct, 0.05)} suffix={ch.label} /> : <span className="text-[13px] text-muted">No change yet: the history starts with our first snapshot.</span>}
          />
          <div className="grid grid-cols-3 gap-3">
            <Stat label="30 d forecast" value={c.pred30dPct == null ? "n/a" : signedPct(c.pred30dPct, 0)} />
            <Stat label="90 d forecast" value={c.pred90dPct == null ? "n/a" : signedPct(c.pred90dPct, 0)} />
            <Stat label="Fair value" value={usd(c.fairUsd)} sub={c.fairGapPct != null ? <span className="text-muted">{signedPct(c.fairGapPct, 0)} away</span> : undefined} />
          </div>
        </div>
      </div>

      <AreaChart
        data={hist}
        height={140}
        label={`Price of ${c.name} over our daily snapshots`}
        onScrub={(s) => setAt(s ? s.index : null)}
        empty="The price line fills in as the daily snapshots arrive."
      />

      <div className="divide-y divide-line">
        <Row
          label="Forecast"
          sub={c.predSrc === "model" ? "A model that passed its out-of-sample test." : "A fixed rule from the fair-value gap. Not a tested model yet, so treat it as a guess."}
          value={predLabel(c.predSrc).split(",")[0]}
          help="How the 30 and 90 day numbers were made."
        />
        <Row
          label="Fair value"
          sub="What cards like this one (rarity, Pokemon, set age, art) cost, valued without its own set. A description, not a promise."
          value={usd(c.fairUsd)}
        />
        {c.cardmarketEur != null && (
          <Row
            label="Cardmarket (EU)"
            sub={cmFresh ? (c.spreadPct != null ? `TCGplayer is ${signedPct(c.spreadPct, 0)} against it in dollars` : undefined) : `Last refreshed ${c.cardmarketUpdated ?? "long ago"}: too old to compare.`}
            value={`€${c.cardmarketEur.toFixed(2)}`}
            tone={cmFresh ? "plain" : "warn"}
          />
        )}
      </div>

      {(c.tcgplayerUrl || c.cardmarketUrl) && (
        <div className="flex flex-wrap gap-2">
          {c.tcgplayerUrl && (
            <a href={c.tcgplayerUrl} target="_blank" rel="noreferrer" className="inline-flex min-h-[34px] items-center gap-1.5 rounded-full bg-surface-2 px-3.5 text-[13px] font-semibold text-ink hover:bg-line">
              TCGplayer <ExternalLink size={14} aria-hidden />
            </a>
          )}
          {c.cardmarketUrl && (
            <a href={c.cardmarketUrl} target="_blank" rel="noreferrer" className="inline-flex min-h-[34px] items-center gap-1.5 rounded-full bg-surface-2 px-3.5 text-[13px] font-semibold text-ink hover:bg-line">
              Cardmarket <ExternalLink size={14} aria-hidden />
            </a>
          )}
        </div>
      )}
      <p className="text-[13px] text-faint">Prices only. Pythia never buys or sells a card; you do that by hand.</p>
    </div>
  );
}

function Collection({ d }: { d: PokemonData }) {
  const c = d.collection;
  const curve = c.curve.map(([, v]) => v);
  return (
    <Section
      title="Paper collection"
      hint={`Play money: ${money(c.start, 0)} that follows the forecasts once a month, with the real costs of buying and selling cards by mail taken off. Nothing is bought for real.`}
      right={<Badge tone="accent">play money</Badge>}
    >
      {!c.started ? (
        <Nothing icon={Layers} title="Starts with the first daily run">
          The first month buys the ten best 90-day forecasts between $5 and $250.
        </Nothing>
      ) : (
        <div className="space-y-4">
          <BigNumber
            value={money(c.equity)}
            label="If sold today, after costs"
            sub={<Change pct={c.returnPct} tone={changeTone(c.returnPct, 0.05)} suffix={`since ${c.started}`} />}
          />
          {curve.length >= 2 && <Sparkline data={curve} height={48} fill label="Value of the paper collection" />}
          <div className="grid grid-cols-2 gap-3">
            <Stat label="At market prices" value={money(c.equityMarket)} />
            <Stat label="Cash" value={money(c.cash)} />
          </div>
          {c.holdings.length > 0 && (
            <List>
              {c.holdings.map((h) => (
                <ListRow
                  key={h.id}
                  leading={<Thumb src={h.image} alt="" />}
                  title={`${h.qty}× ${h.name}`}
                  subtitle={`${h.set ?? ""} · since ${h.bought} · ${h.why}`}
                  right={usd(h.price)}
                  rightSub={h.changePct != null ? <Change pct={h.changePct} tone={changeTone(h.changePct, 0.05)} size="sm" /> : undefined}
                />
              ))}
            </List>
          )}
          <p className="text-[13px] text-muted">
            Card costs are large: a $20 card costs about $22 to buy and fetches about $16 sold, so it has to rise about a third just to break even. The first days show that loss before any price moves.
          </p>
        </div>
      )}
    </Section>
  );
}

export function Cards() {
  const mode = liveMode();
  const [d, setD] = useState<PokemonData | null>(null);
  const [found, setFound] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [err, setErr] = useState("");
  const [sort, setSort] = useState<CardSort>("price");
  const [q, setQ] = useState("");
  const [shown, setShown] = useState(PAGE_SIZE);
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
    setLoaded(true);
  }, []);

  useEffect(() => {
    if (mode !== "none") void refresh();
  }, [mode, refresh]);

  useEffect(() => setShown(PAGE_SIZE), [q, sort]);

  const all = useMemo(() => (d ? sortCards(filterCards(d.cards, q), sort) : []), [d, q, sort]);
  const selected = d?.cards.find((c) => c.id === open) ?? null;
  const stale = d ? cardmarketStale(d) : false;

  const title = "Cards";
  const subtitle = "Pokemon card prices, what moved and what the forecast expects. Data and play money only: you buy and sell by hand.";

  if (mode === "none") {
    return (
      <Page title={title} subtitle={subtitle}>
        <Section title="Not available here" hint="The prices are collected daily by the lab and read from its data folder.">
          <Nothing icon={Layers} title="Needs the desktop app or a connected server" />
        </Section>
      </Page>
    );
  }

  const stats: KeyStat[] = d
    ? [
        d.collection.started
          ? {
              label: "Play-money collection",
              value: money(d.collection.equity),
              tone: d.collection.returnPct > 0.05 ? "up" : d.collection.returnPct < -0.05 ? "down" : "plain",
              sub: `${signedPct(d.collection.returnPct, 1)} since ${d.collection.started}, after card costs`,
              help: "A pretend collection that follows the forecasts. Nothing is bought for real.",
            }
          : { label: "Cards priced", value: d.cards.length.toLocaleString("en-US"), sub: `Prices of ${d.snapshot}` },
        d.collection.started
          ? { label: "Cards priced", value: d.cards.length.toLocaleString("en-US"), sub: `Prices of ${d.snapshot}` }
          : { label: "Price history", value: plural(d.historyDays, "day") },
        {
          label: d.collection.started ? "Price history" : "Forecast",
          value: d.collection.started ? plural(d.historyDays, "day") : d.model.validated ? "tested" : "a rule",
          sub: d.model.validated ? "Passed its out-of-sample test" : `A first honest test needs about ${DAYS_FOR_A_TEST} days`,
        },
      ]
    : [];

  return (
    <Page
      title={title}
      subtitle={subtitle}
      right={
        <Button variant="secondary" size="sm" icon={RefreshCw} onClick={() => void refresh()}>
          Refresh
        </Button>
      }
    >
      {err && (
        <Notice tone="danger" title="Could not read the cards">
          {err}
        </Notice>
      )}
      {!loaded && !err && (
        <Card>
          <LoadingRows rows={4} label="Reading the card prices" />
        </Card>
      )}
      {loaded && !found && (
        <Notice tone="warning" title="No lab data found">
          Set PYTHIA_DATA to the folder the lab syncs to.
        </Notice>
      )}
      {loaded && found && !d && !err && (
        <Section title="No prices yet">
          <Nothing icon={Layers} title="The daily collector has not written anything yet">
            lab.collect.pokemon and then lab.pokemon.daily fill this page once a day.
          </Nothing>
        </Section>
      )}

      {d && (
        <>
          <KeyStats items={stats} />

          <Notice tone={d.model.validated ? "success" : "info"} title={d.model.validated ? "Forecast tested" : "Forecasts are a rule for now"}>
            {d.model.sentence}
          </Notice>
          {stale && (
            <Notice tone="warning" title="Cardmarket prices are old">
              The card API last refreshed most Cardmarket (EU) prices on {d.freshness?.cardmarketNewest ?? "an earlier date"}. Prices here are TCGplayer (US), updated daily; the EU side comes back when the API updates it.
            </Notice>
          )}

          <Section
            title="Prices"
            hint={`${plural(d.cards.length, "card")} from ${d.snapshot}: the most valuable, the best forecasts and anything that moved. Tap one for its chart and forecast.`}
            bare
          >
            <Card>
              <div className="space-y-3">
                <label className="relative block">
                  <span className="sr-only">Search cards</span>
                  <Search size={16} aria-hidden className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-faint" />
                  <input className={`${inputCls} pl-9`} placeholder="Search a name, set or rarity" value={q} onChange={(e) => setQ(e.target.value)} />
                </label>
                <FilterChips options={SORTS} value={sort} onChange={setSort} label="Sort the cards" />
              </div>
              <List className="mt-2">
                {all.slice(0, shown).map((c) => (
                  <CardRow key={c.id} c={c} sort={sort} onOpen={() => setOpen(c.id)} />
                ))}
              </List>
              {all.length === 0 && <Nothing title="No card matches" />}
              {all.length > shown && (
                <div className="pt-3">
                  <Button variant="secondary" size="sm" full onClick={() => setShown((n) => n + PAGE_SIZE)}>
                    Show {Math.min(PAGE_SIZE, all.length - shown)} more of {all.length - shown}
                  </Button>
                </div>
              )}
            </Card>
          </Section>

          <Collection d={d} />

          <Card>
            <More title="How the numbers are made">
              <div className="space-y-2 text-sm leading-relaxed text-muted">
                <p>
                  Every morning the lab saves the price of every card worth $2 or more from the Pokemon TCG API: TCGplayer in dollars and, when it is current, Cardmarket in euros. The change next to a price
                  compares our own snapshots, so it starts empty and fills in day by day.
                </p>
                <p>
                  Fair value is what similar cards cost: same rarity group, Pokemon, set age and art, learned from other sets only. Until the 30 and 90 day forecasts have passed a walk-forward test on our own
                  history, they are a fixed rule built from that gap, and this page says so.
                </p>
                <p>Updated {d.generated}.</p>
              </div>
            </More>
          </Card>
        </>
      )}

      <Sheet open={!!selected} onClose={() => setOpen(null)} title={selected?.name ?? "Card"} wide>
        {selected && <Detail c={selected} stale={stale} />}
      </Sheet>
    </Page>
  );
}
