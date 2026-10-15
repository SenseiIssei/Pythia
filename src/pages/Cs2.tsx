import { useCallback, useEffect, useMemo, useState } from "react";
import { Crosshair, RefreshCw, Search } from "lucide-react";
import { Badge, Button, Card, EmptyState, Loading, Notice, PageHeader, Sparkline, inputCls } from "../components/ui";
import { liveMode } from "../live";
import {
  changeTone,
  cs2Board,
  eur,
  frac,
  signalInfo,
  visibleItems,
  type Cs2Board,
  type Cs2Filter,
  type Cs2Item,
  type Cs2Sort,
} from "../cs2";

const FILTERS: { id: Cs2Filter; label: string }[] = [
  { id: "all", label: "All" },
  { id: "signals", label: "Signals" },
  { id: "held", label: "Paper portfolio" },
  { id: "watch", label: "Watchlist" },
  { id: "case", label: "Cases" },
  { id: "skin", label: "Skins" },
  { id: "sticker", label: "Stickers" },
];
const SORTS: { id: Cs2Sort; label: string }[] = [
  { id: "liquid", label: "Most traded" },
  { id: "change", label: "7-day change" },
  { id: "prediction", label: "Prediction" },
  { id: "price", label: "Price" },
];
const TEXT_TONE: Record<string, string> = {
  green: "text-success",
  red: "text-danger",
  neutral: "text-cyber-text-dim",
};

/** One line of the list: name and category left, price and 7-day change right, then the model. */
function Row({ r }: { r: Cs2Item }) {
  const sig = signalInfo(r.signal);
  const pred = r.horizon === 30 ? r.pred30d : r.pred7d;
  return (
    <div className="grid grid-cols-[1fr_auto] items-center gap-x-4 gap-y-1 py-3 sm:grid-cols-[1fr_110px_120px_110px]">
      <div className="min-w-0">
        <div className="truncate text-sm font-medium text-cyber-text" title={r.name}>
          {r.name}
        </div>
        <div className="text-xs text-cyber-text-faint">
          {r.category.replace("_", " ")} · {r.sales7d} sales in 7 days · {r.listed} listed
          {r.steamPrice != null && <> · Steam {eur(r.steamPrice)}</>}
        </div>
      </div>
      <div className="text-right">
        <div className="font-mono text-sm tabular-nums text-cyber-text">{eur(r.price)}</div>
        <div className={`font-mono text-xs tabular-nums ${TEXT_TONE[changeTone(r.change7d)]}`}>{frac(r.change7d)}</div>
      </div>
      <div className="text-right max-sm:col-start-1 max-sm:text-left">
        <div className={`font-mono text-sm tabular-nums ${TEXT_TONE[changeTone(pred)]}`}>
          {pred == null ? "n/a" : frac(pred)}
        </div>
        <div className="text-xs text-cyber-text-faint">
          {r.horizon ? `next ${r.horizon} days` : "no prediction"}
          {r.gap != null && r.gap > 0 && <> · gap {frac(r.gap)}</>}
        </div>
      </div>
      <div className="text-right">
        <Badge tone={sig.tone} title={sig.help}>
          {sig.label}
        </Badge>
      </div>
    </div>
  );
}

export function Cs2() {
  const mode = liveMode();
  const [b, setB] = useState<Cs2Board | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [err, setErr] = useState("");
  const [filter, setFilter] = useState<Cs2Filter>("all");
  const [sort, setSort] = useState<Cs2Sort>("liquid");
  const [query, setQuery] = useState("");

  const refresh = useCallback(async () => {
    try {
      setB(await cs2Board());
      setErr("");
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setLoaded(true);
    }
  }, []);

  useEffect(() => {
    if (mode !== "none") void refresh();
  }, [mode, refresh]);

  const rows = useMemo(() => (b ? visibleItems(b.items, filter, query, sort) : []), [b, filter, query, sort]);

  const header = (
    <PageHeader
      title="CS2 Skins"
      subtitle="Skinport and Steam prices, the model's 7 and 30-day view after fees, and a play-money portfolio. Nothing here trades: you decide and trade by hand."
      right={
        mode !== "none" && (
          <Button tone="neutral" icon={RefreshCw} onClick={() => void refresh()}>
            Refresh
          </Button>
        )
      }
    />
  );

  if (mode === "none") {
    return (
      <div className="animate-fade-in mx-auto max-w-5xl">
        {header}
        <Card>
          <EmptyState icon={Crosshair} title="The CS2 board needs the desktop app or a connected server">
            It is read from the lab's data folder, which this browser version cannot reach.
          </EmptyState>
        </Card>
      </div>
    );
  }

  const p = b?.portfolio;
  return (
    <div className="animate-fade-in mx-auto max-w-5xl space-y-4">
      {header}
      {!loaded && <Loading>Reading the CS2 board</Loading>}
      {err && (
        <Notice tone="danger" title="Could not read the CS2 board">
          {err}
        </Notice>
      )}
      {loaded && !err && (!b || b.status !== "ok") && (
        <Card>
          <EmptyState icon={Crosshair} title="No CS2 data yet">
            The collector (lab.collect.cs2) and the hourly job (lab.cs2.run) fill this page once they run on the lab
            machine.
          </EmptyState>
        </Card>
      )}

      {b && b.status === "ok" && (
        <>
          <Notice tone="info" title={`${b.historyDays} days of history`}>
            {b.model.note} Predictions are before fees; a buy idea needs more than the{" "}
            {b.hurdle != null ? frac(b.hurdle, 0).replace("+", "") : ""} round trip (Skinport's fee plus a spread
            allowance). 7-day change against the {b.change7Basis}. Updated {b.generated}.
          </Notice>

          {p && (
            <Card
              title="Paper portfolio"
              subtitle="Play money in euro, Skinport prices and fee, top picks after fees, looked at weekly."
              right={
                <Badge tone={p.returnPct >= 0 ? "green" : "red"}>
                  {p.returnPct >= 0 ? "+" : "−"}
                  {Math.abs(p.returnPct).toFixed(2)} %
                </Badge>
              }
            >
              <div className="grid gap-4 md:grid-cols-[220px_1fr]">
                <div>
                  <div className="font-mono text-2xl font-bold tabular-nums text-cyber-text">{eur(p.equity)}</div>
                  <div className="text-xs text-cyber-text-faint">
                    after the sale fee, from {eur(p.startEquity)} since {(p.started ?? "").slice(0, 10) || "today"}
                  </div>
                  <div className="mt-1 text-xs text-cyber-text-faint">
                    cash {eur(p.cash)} · last look {p.lastRebalance ?? "never"}
                  </div>
                </div>
                <Sparkline data={p.equityCurve} tone={p.returnPct >= 0 ? "green" : "red"} label="Paper portfolio equity" />
              </div>
              {p.positions.length > 0 && (
                <div className="mt-3 divide-y divide-cyber-border">
                  {p.positions.map((x) => (
                    <div key={x.name} className="flex items-baseline justify-between gap-3 py-1.5 text-sm">
                      <span className="min-w-0 truncate text-cyber-text">
                        {x.qty} × {x.name}
                      </span>
                      <span className="shrink-0 font-mono text-xs tabular-nums text-cyber-text-dim">
                        {eur(x.cost)} → {eur(x.price)}{" "}
                        <span className={TEXT_TONE[changeTone((x.returnPct ?? 0) / 100)]}>
                          {frac((x.returnPct ?? 0) / 100)}
                        </span>
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </Card>
          )}

          {b.alerts.length > 0 && (
            <Card title="Recent alerts" subtitle="Where to look by hand. Gaps are after both venues' fees.">
              <div className="divide-y divide-cyber-border">
                {b.alerts.slice(0, 8).map((a, i) => (
                  <div key={`${a.name}-${a.tsMs}-${i}`} className="py-1.5 text-sm">
                    <Badge tone={signalInfo(a.kind).tone}>{signalInfo(a.kind).label}</Badge>{" "}
                    <span className="text-cyber-text">{a.name}</span>
                    <span className="text-cyber-text-dim">: {a.text}</span>
                    {a.tsMs != null && (
                      <span className="ml-1 text-xs text-cyber-text-faint">({new Date(a.tsMs).toLocaleString()})</span>
                    )}
                  </div>
                ))}
              </div>
            </Card>
          )}

          <Card title="Market" subtitle={b.verdict}>
            <div className="mb-3 flex flex-wrap items-center gap-2">
              {FILTERS.map((f) => (
                <button
                  key={f.id}
                  type="button"
                  onClick={() => setFilter(f.id)}
                  aria-pressed={filter === f.id}
                  className={`rounded-full border px-3 py-1 text-xs ${
                    filter === f.id ? "border-accent/60 text-accent" : "border-cyber-border text-cyber-text-dim"
                  }`}
                >
                  {f.label}
                </button>
              ))}
            </div>
            <div className="mb-2 flex flex-wrap items-center gap-2">
              <label className="relative min-w-0 flex-1">
                <Search size={14} aria-hidden className="absolute left-2.5 top-1/2 -translate-y-1/2 text-cyber-text-faint" />
                <input
                  className={`${inputCls} pl-8`}
                  placeholder="Search an item"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  aria-label="Search an item"
                />
              </label>
              <select
                className={`${inputCls} w-auto`}
                value={sort}
                onChange={(e) => setSort(e.target.value as Cs2Sort)}
                aria-label="Sort by"
              >
                {SORTS.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="hidden grid-cols-[1fr_110px_120px_110px] gap-x-4 border-b border-cyber-border pb-1 text-[11px] uppercase tracking-wider text-cyber-text-faint sm:grid">
              <span>Item</span>
              <span className="text-right">Price · 7 days</span>
              <span className="text-right">Prediction</span>
              <span className="text-right">Signal</span>
            </div>
            {rows.length === 0 ? (
              <EmptyState compact icon={Search} title="Nothing matches" />
            ) : (
              <div className="divide-y divide-cyber-border">
                {rows.slice(0, 150).map((r) => (
                  <Row key={r.name} r={r} />
                ))}
              </div>
            )}
          </Card>
          <p className="text-xs text-cyber-text-faint">
            Paper only. Automated buying or selling on Steam or a skin marketplace breaks their terms; Pythia never
            does it. <Badge tone="neutral">read-only</Badge>
          </p>
        </>
      )}
    </div>
  );
}
