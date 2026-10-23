// The Trends page: what is hot on pump.fun right now, from our own chain data
// and our models (the lab's paper engine writes it, trends.py), and
// DexScreener's list from the trending watcher. Four tabs: Hot now (buy volume
// over 5 minutes), About to migrate (curves above 70 %), Fresh pools (migrated
// in the last 30 minutes) and DexScreener. Each row: image, name, a 15 minute
// sparkline, volume, buyers, change, market cap, progress, the model badges
// (tap one for what it means) and links to DexScreener and Solscan. Read every
// 10 s while shown (a poll: the DevPanel proxy passes no websockets). Opens on
// its own with `?page=trends&embed=1`. A view only: nothing here trades.

import { useEffect, useRef, useState } from "react";
import { ExternalLink, Flame } from "lucide-react";
import { Chip, Notice, Page, Sparkline, Tabs } from "../design";
import { LoadingRows, Nothing } from "../pagekit";
import { useVisiblePoll } from "../pageVisible";
import { solscanToken } from "../pumpfunLive";
import {
  TRENDS_POLL_MS,
  ageText,
  badgeUi,
  canReadTrends,
  changeText,
  dexscreenerToken,
  directImage,
  fetchTrends,
  flagText,
  imageOfMetadata,
  isStale,
  solText,
  updatedClock,
  usdShort,
  type DexItem,
  type TrendCoin,
  type TrendList,
  type TrendsView,
} from "../trends";

export type TrendTab = TrendList | "dex";

const TABS: { id: TrendTab; label: string }[] = [
  { id: "hot", label: "Hot now" },
  { id: "migrating", label: "About to migrate" },
  { id: "fresh", label: "Fresh pools" },
  { id: "dex", label: "DexScreener" },
];

const HINT: Record<TrendTab, string> = {
  hot: "By buy volume in SOL over the last 5 minutes, curve and pool together.",
  migrating: "Curves above 70 %, the furthest first, then the fastest (progress gained per minute over 5 minutes).",
  fresh: "Coins that completed their curve in the last 30 minutes, by their pool's volume over 5 minutes.",
  dex: "DexScreener's boosted and latest tokens with their most liquid pair, from the trending watcher (every 15 minutes).",
};

// ── the coin's picture: the metadata's image when it can be read, else its letters ──

const images = new Map<string, Promise<string | null>>();

function imageFor(uri: string): Promise<string | null> {
  let p = images.get(uri);
  if (!p) {
    const direct = directImage(uri);
    p = direct
      ? Promise.resolve(direct)
      : uri.startsWith("https://")
        ? fetch(uri, { signal: AbortSignal.timeout?.(6_000) })
            .then((r) => (r.ok ? r.json() : null))
            .then(imageOfMetadata)
            .catch(() => null)
        : Promise.resolve(null);
    images.set(uri, p);
  }
  return p;
}

function CoinImage({ c }: { c: TrendCoin }) {
  const [src, setSrc] = useState<string | null>(() => directImage(c.uri));
  const [broken, setBroken] = useState(false);
  useEffect(() => {
    let live = true;
    if (c.uri && !src) void imageFor(c.uri).then((s) => live && setSrc(s));
    return () => {
      live = false;
    };
  }, [c.uri, src]);
  const letters = (c.symbol || c.name || "?").slice(0, 4).toUpperCase();
  if (src && !broken) {
    return <img src={src} alt="" loading="lazy" referrerPolicy="no-referrer" onError={() => setBroken(true)} className="h-10 w-10 shrink-0 rounded-full bg-surface-2 object-cover" />;
  }
  return (
    <span aria-hidden className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-surface-2 text-[11px] font-bold text-muted">
      {letters}
    </span>
  );
}

// ── one row ──

function Progress({ c }: { c: TrendCoin }) {
  if (c.migrated) return <span className="text-[12px] font-semibold text-accent">migrated</span>;
  const p = Math.max(0, Math.min(1, c.progress ?? 0));
  return (
    <div className="flex min-w-[90px] items-center gap-2">
      <div role="progressbar" aria-label="Curve progress" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(p * 100)} className="h-1.5 flex-1 overflow-hidden rounded-full bg-surface-2">
        <div className="h-full rounded-full" style={{ width: `${p * 100}%`, background: p >= 0.7 ? "var(--color-accent)" : "var(--color-text)" }} />
      </div>
      <span className="tabular text-[12px] text-muted">{Math.round(p * 100)} %</span>
    </div>
  );
}

const TONE_TEXT = { good: "text-up", bad: "text-down", warn: "text-warn", accent: "text-accent" } as const;

function Lead({ c, tab }: { c: TrendCoin; tab: TrendList }) {
  if (tab === "migrating") {
    return (
      <>
        <div className="tabular text-[15px] font-semibold text-ink">{c.progress != null ? `${(c.progress * 100).toFixed(1)} %` : "n/a"}</div>
        <div className="tabular text-[12px] text-muted">{c.speedPm != null ? `${c.speedPm >= 0 ? "+" : ""}${(c.speedPm * 100).toFixed(1)} pts/min` : "n/a"}</div>
      </>
    );
  }
  if (tab === "fresh") {
    return (
      <>
        <div className="tabular text-[15px] font-semibold text-ink">{solText(c.poolVol5m)}</div>
        <div className="tabular text-[12px] text-muted">{c.poolTrades5m ?? 0} pool trades, 5 min</div>
      </>
    );
  }
  return (
    <>
      <div className="tabular text-[15px] font-semibold text-ink">{solText(c.vol5m)}</div>
      <div className="tabular text-[12px] text-muted">bought, 5 min</div>
    </>
  );
}

export function CoinRow({ c, tab, rules, nowMs }: { c: TrendCoin; tab: TrendList; rules: Record<string, string>; nowMs: number }) {
  const [open, setOpen] = useState<string | null>(null);
  const badges = badgeUi(c, rules);
  const shown = badges.find((b) => b.id === open);
  const chg = c.chg5m;
  const migratedAgo = c.migrateMs != null ? ageText((nowMs - c.migrateMs) / 1000) : null;
  return (
    <li className={`py-3 ${c.blocked ? "opacity-60" : ""}`} data-mint={c.mint}>
      <div className="flex items-center gap-3">
        <CoinImage c={c} />
        <div className="min-w-0 flex-1">
          <div className="flex min-w-0 items-baseline gap-1.5">
            <span className="truncate text-[15px] font-semibold text-ink">{c.name || c.symbol || c.mint.slice(0, 6)}</span>
            {c.symbol && <span className="shrink-0 text-[13px] text-muted">{c.symbol}</span>}
          </div>
          <div className="tabular truncate text-[12px] text-muted">
            {c.mcapUsd != null ? usdShort(c.mcapUsd) : solText(c.mcapSol)} cap
            {" · "}
            <span className={chg == null ? "" : chg > 0 ? "text-up" : chg < 0 ? "text-down" : ""}>{changeText(chg)} 5 min</span>
            {" · "}
            {tab === "fresh" && migratedAgo ? `migrated ${migratedAgo} ago` : `${ageText(c.ageS)} old`}
          </div>
        </div>
        <div className="hidden w-20 shrink-0 sm:block">
          <Sparkline data={c.spark} height={28} label={`${c.symbol || c.name}: market cap over the last 15 minutes`} />
        </div>
        <div className="shrink-0 text-right">
          <Lead c={c} tab={tab} />
        </div>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 pl-[52px] text-[12px] text-muted">
        <span className="tabular">{c.buyers5m ?? 0} buyers</span>
        <span className="tabular">1 min {solText(c.vol1m)}</span>
        <span className="tabular">15 min {solText(c.vol15m)}</span>
        <span className={`tabular ${c.net5m != null && c.net5m < 0 ? "text-down" : ""}`}>net {solText(c.net5m)}</span>
        <span className="tabular">{changeText(c.chg15m)} 15 min</span>
        <Progress c={c} />
      </div>
      <div className="mt-1.5 flex flex-wrap items-center gap-1.5 pl-[52px]">
        {c.blocked && (
          <Chip tone="bad" title="On the owner's block list: never highlighted">
            blocked
          </Chip>
        )}
        {c.flags.map((f) => (
          <Chip key={f} tone="warn" title="Our paper books do not trade coins with this flag">
            {flagText(f)}
          </Chip>
        ))}
        {badges.map((b) => (
          <button
            key={b.id}
            type="button"
            title={b.why}
            aria-expanded={open === b.id}
            onClick={() => setOpen(open === b.id ? null : b.id)}
            className={`inline-flex items-center rounded-full bg-surface-2 px-2.5 py-0.5 text-xs font-semibold ${TONE_TEXT[b.tone]}`}
            data-badge={b.id}
          >
            {b.label}
          </button>
        ))}
        <span className="ml-auto flex items-center gap-3 text-[12px]">
          <a href={dexscreenerToken(c.mint)} target="_blank" rel="noreferrer noopener" className="inline-flex items-center gap-1 text-muted hover:text-ink">
            DexScreener <ExternalLink size={11} aria-hidden />
          </a>
          <a href={solscanToken(c.mint)} target="_blank" rel="noreferrer noopener" className="inline-flex items-center gap-1 text-muted hover:text-ink">
            Solscan <ExternalLink size={11} aria-hidden />
          </a>
        </span>
      </div>
      {shown && <p className="mt-1.5 pl-[52px] text-[12px] leading-relaxed text-muted">{shown.why}</p>}
    </li>
  );
}

export function DexRow({ d }: { d: DexItem }) {
  const h1 = d.changeH1 != null ? d.changeH1 / 100 : null;
  const h24 = d.changeH24 != null ? d.changeH24 / 100 : null;
  return (
    <li className="py-3" data-mint={d.address}>
      <div className="flex items-center gap-3">
        <span aria-hidden className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-surface-2 text-[11px] font-bold text-muted">
          {(d.symbol || "?").slice(0, 4).toUpperCase()}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex min-w-0 items-baseline gap-1.5">
            <span className="truncate text-[15px] font-semibold text-ink">{d.name || d.symbol}</span>
            {d.symbol && <span className="shrink-0 text-[13px] text-muted">{d.symbol}</span>}
          </div>
          <div className="tabular truncate text-[12px] text-muted">
            {usdShort(d.fdv)} FDV · {usdShort(d.liquidityUsd)} liquidity{d.dex ? ` · ${d.dex}` : ""}
            {d.ageH != null ? ` · ${ageText(d.ageH * 3600)} old` : ""}
          </div>
        </div>
        <div className="shrink-0 text-right">
          <div className="tabular text-[15px] font-semibold text-ink">{usdShort(d.volumeH24)}</div>
          <div className="tabular text-[12px] text-muted">
            <span className={h1 == null ? "" : h1 > 0 ? "text-up" : h1 < 0 ? "text-down" : ""}>{changeText(h1)} 1 h</span>
            {" · "}
            <span className={h24 == null ? "" : h24 > 0 ? "text-up" : h24 < 0 ? "text-down" : ""}>{changeText(h24)} 24 h</span>
          </div>
        </div>
      </div>
      <div className="mt-1.5 flex flex-wrap items-center gap-1.5 pl-[52px]">
        {d.flags.map((f) => (
          <Chip key={f} tone="warn">
            {f}
          </Chip>
        ))}
        <span className="ml-auto flex items-center gap-3 text-[12px]">
          <a href={d.pairUrl ?? dexscreenerToken(d.address)} target="_blank" rel="noreferrer noopener" className="inline-flex items-center gap-1 text-muted hover:text-ink">
            DexScreener <ExternalLink size={11} aria-hidden />
          </a>
          {d.chain === "solana" && (
            <a href={solscanToken(d.address)} target="_blank" rel="noreferrer noopener" className="inline-flex items-center gap-1 text-muted hover:text-ink">
              Solscan <ExternalLink size={11} aria-hidden />
            </a>
          )}
        </span>
      </div>
    </li>
  );
}

const HONEST =
  "These are signals from our own chain data, not advice. Our studies found no rule that wins reliably on these coins, and most of them go to zero.";

/** Everything below the header, given what was read (rendered by tests without a server). */
export function TrendsBody({ v, tab, onTab, nowMs }: { v: TrendsView; tab: TrendTab; onTab: (t: TrendTab) => void; nowMs: number }) {
  const rows = tab === "dex" ? null : v.lists[tab];
  const stale = v.present && isStale(v, nowMs);
  const noModels = v.present && !v.models.win && !v.models.rug && !v.models.p3x;
  return (
    <>
      <Notice tone="info" title="Signals, not advice">
        {HONEST}
      </Notice>
      {!v.present && tab !== "dex" && (
        <Notice tone="warning" title="No trends yet">
          The paper engine writes them every 12 s once it runs with this version (the container pythia-pumpfun-rt).
        </Notice>
      )}
      {stale && (
        <Notice tone="warning" title="Not current">
          The paper engine last wrote {v.writtenMs != null ? `${ageText((nowMs - v.writtenMs) / 1000)} ago` : "at an unknown time"}; it may be stopped.
        </Notice>
      )}
      <Tabs options={TABS} value={tab} onChange={onTab} label="Trend lists" />
      <p className="px-1 text-[13px] leading-relaxed text-muted">
        {HINT[tab]}
        {tab !== "dex" && noModels ? " No model is loaded yet, so there are no model badges." : ""}
      </p>
      {rows != null ? (
        rows.length === 0 ? (
          <Nothing icon={Flame} title="Nothing here right now">
            {tab === "migrating" ? "No curve is above 70 % with a trade in the last 15 minutes." : tab === "fresh" ? "No coin migrated in the last 30 minutes." : "No buys in the last 5 minutes."}
          </Nothing>
        ) : (
          <ul className="divide-y divide-line" aria-label={TABS.find((t) => t.id === tab)?.label}>
            {rows.map((c) => (
              <CoinRow key={c.mint} c={c} tab={tab as TrendList} rules={v.badges} nowMs={nowMs} />
            ))}
          </ul>
        )
      ) : !v.dex || v.dex.items.length === 0 ? (
        <Nothing icon={Flame} title="No DexScreener list">
          The trending watcher (lab.ops.trending) has not written one yet.
        </Nothing>
      ) : (
        <>
          {v.dex.caveat && <p className="px-1 text-[12px] text-faint">{v.dex.caveat}</p>}
          <ul className="divide-y divide-line" aria-label="DexScreener">
            {v.dex.items.map((d) => (
              <DexRow key={`${d.chain}:${d.address}`} d={d} />
            ))}
          </ul>
          {v.dex.updatedMs != null && <p className="px-1 text-[12px] text-faint">DexScreener list {updatedClock(v.dex.updatedMs)}</p>}
        </>
      )}
      {v.present && (
        <p className="px-1 text-[12px] text-faint">
          {v.tracked ?? 0} coins with a trade in the last 15 minutes
          {v.solUsd != null ? ` · 1 SOL = $${v.solUsd.toFixed(2)} (Kraken)` : " · no SOL price, market caps in SOL"}
        </p>
      )}
    </>
  );
}

export function Trends() {
  const ref = useRef<HTMLDivElement>(null);
  const [v, setV] = useState<TrendsView | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [tab, setTab] = useState<TrendTab>("hot");
  const [at] = useVisiblePoll(
    ref,
    () =>
      canReadTrends()
        ? fetchTrends()
            .then((nv) => {
              setV(nv);
              setErr(null);
            })
            .catch((e) => setErr(e instanceof Error ? e.message : String(e)))
        : undefined,
    TRENDS_POLL_MS,
  );
  const stamp = v?.writtenMs ?? at;
  return (
    <div ref={ref}>
      <Page
        wide
        title="Trends"
        subtitle="What is hot on pump.fun right now, from the trades our own collector reads off the chain, with our models' read on each coin."
        right={stamp ? <span className="tabular text-[13px] text-muted">{updatedClock(stamp)}</span> : undefined}
      >
        {!canReadTrends() ? (
          <Notice tone="info" title="Needs the server" icon={Flame}>
            The trends are read from the connected backend on the server.
          </Notice>
        ) : err && !v ? (
          <Notice tone="warning" title="Could not read the trends">
            {err}
          </Notice>
        ) : !v ? (
          <LoadingRows rows={6} label="Reading the trends" />
        ) : (
          <TrendsBody v={v} tab={tab} onTab={setTab} nowMs={Date.now()} />
        )}
      </Page>
    </div>
  );
}
