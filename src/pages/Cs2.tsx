import { useCallback, useEffect, useMemo, useState } from "react";
import { Crosshair, ExternalLink, RefreshCw, Search, ShieldCheck, TriangleAlert } from "lucide-react";
import { Badge, Button, Change, List, Notice, Page, Segmented, Sparkline, inputCls, signedPct } from "../design";
import { FilterChips, KeyStats, LoadingRows, More, Nothing, Row, Section, num, plural, type ChipOption } from "../pagekit";
import { liveMode } from "../live";
import {
  boardCounts,
  categoryLabel,
  changeTone,
  cs2Board,
  eur,
  frac,
  itemLinks,
  leanWords,
  prediction,
  signalInfo,
  visibleItems,
  type Cs2Board,
  type Cs2SteamTrends,
  type Cs2TrendItem,
  type Cs2Filter,
  type Cs2Item,
  type Cs2Sort,
} from "../cs2";

const FILTERS: ChipOption<Cs2Filter>[] = [
  { id: "all", label: "All" },
  { id: "signals", label: "Signals", help: "Buy ideas, gaps, drops and items to avoid" },
  { id: "held", label: "Paper portfolio" },
  { id: "watch", label: "Watchlist", help: "Cases, popular skins and sticker capsules the collector also prices on Steam" },
  { id: "case", label: "Cases" },
  { id: "skin", label: "Skins" },
  { id: "sticker", label: "Stickers" },
];
const SORTS: { id: Cs2Sort; label: string }[] = [
  { id: "liquid", label: "Traded" },
  { id: "change", label: "7d" },
  { id: "prediction", label: "Forecast" },
  { id: "price", label: "Price" },
];
const PAGE = 60;
const TONE_TEXT = { up: "text-up", down: "text-down", flat: "text-muted" } as const;

/** One item: name and what it is on the left, then price and 7-day change, the forecast and the signal. */
function ItemRow({ r }: { r: Cs2Item }) {
  const sig = signalInfo(r.signal);
  const p = prediction(r);
  return (
    <div className="grid grid-cols-[minmax(0,1fr)_auto] items-start gap-x-4 gap-y-1.5 py-3.5 sm:grid-cols-[minmax(0,1fr)_120px_120px_96px] sm:items-center">
      <div className="min-w-0">
        <div className="truncate text-[15px] font-semibold text-ink" title={r.name}>
          {r.name}
        </div>
        <div className="truncate text-[13px] text-muted">
          {categoryLabel(r.category)} · {plural(r.sales7d, "sale")} in 7 days
          {r.steamPrice != null && <> · Steam {eur(r.steamPrice)}</>}
        </div>
      </div>
      <div className="text-right">
        <div className="tabular text-[15px] font-semibold text-ink">{eur(r.price)}</div>
        {r.change7d != null ? <Change pct={r.change7d * 100} tone={changeTone(r.change7d)} size="sm" suffix="7d" /> : <div className="text-[13px] text-faint">no 7d change</div>}
      </div>
      <div className="min-w-0 sm:text-right">
        <div className={`tabular text-[15px] font-semibold ${TONE_TEXT[changeTone(p.value)]}`}>{p.value == null ? "n/a" : frac(p.value)}</div>
        <div className="text-[13px] text-muted">
          {p.horizon ? `next ${p.horizon} days` : "no forecast"}
          {p.horizon === 30 && r.pred7d != null && <> · 7d {frac(r.pred7d)}</>}
          {r.gap != null && r.gap > 0 && <> · gap {frac(r.gap)}</>}
        </div>
      </div>
      <div className="self-center text-right">
        <Badge tone={sig.tone} title={sig.help}>
          {sig.label}
        </Badge>
      </div>
    </div>
  );
}

function TrendLinks({ it }: { it: Cs2TrendItem }) {
  return (
    <div className="flex flex-wrap gap-x-4 text-[13px]">
      {itemLinks(it).map((l) => (
        <a key={l.label} href={l.url} target="_blank" rel="noreferrer noopener" className="inline-flex min-h-[28px] items-center gap-1 font-semibold text-accent hover:underline">
          {l.label} <ExternalLink size={12} aria-hidden />
        </a>
      ))}
    </div>
  );
}

/** One item of the trends: name, group and links on the left; the number it is about on the right. */
function TrendRow({ it, value, sub }: { it: Cs2TrendItem; value: number | null | undefined; sub?: string }) {
  return (
    <div className="flex items-start justify-between gap-3 py-3">
      <div className="min-w-0 flex-1">
        <div className="truncate text-[15px] font-semibold text-ink" title={it.name}>
          {it.name}
        </div>
        <div className="truncate text-[13px] text-muted">
          {[it.group, it.eur != null ? `Steam ${eur(it.eur)}` : null, it.skinport_ask != null ? `Skinport ask ${eur(it.skinport_ask)}` : null, it.skinport_sales7 ? `${it.skinport_sales7} sales in 7 d` : null]
            .filter(Boolean)
            .join(" · ")}
        </div>
        <TrendLinks it={it} />
      </div>
      <div className="shrink-0 text-right">
        <div className={`tabular text-[15px] font-semibold ${TONE_TEXT[changeTone(value)]}`}>{frac(value)}</div>
        {sub && <div className="text-[13px] text-muted">{sub}</div>}
      </div>
    </div>
  );
}

function SteamTrends({ t }: { t: Cs2SteamTrends }) {
  const movers = [...(t.movers?.up ?? []).slice(0, 5), ...(t.movers?.down ?? []).slice(0, 5)];
  const groups = (t.groups ?? []).filter((g) => g.liquid > 0).slice(0, 10);
  const win = t.momentum?.window?.find((m) => m.group === "all");
  const snap = t.momentum?.snapshots;
  const snapAll = snap?.rows?.find((m) => m.group === "all");
  const sp = t.spread;
  const cases = t.cases;
  const unusual = sp?.unusual ?? [];
  return (
    <Section
      title="Steam market trends"
      hint={`Daily Steam Community Market prices (average sales) for ${t.items != null ? num(t.items, 0) : "n/a"} items, ${t.liquid != null ? num(t.liquid, 0) : "n/a"} liquid. ${t.source ?? ""} Updated ${t.date ?? "n/a"}.`}
    >
      {t.headline && <p className="text-[13px] leading-relaxed text-muted">{t.headline}</p>}
      <div className="mt-2 divide-y divide-line">
        <Row
          label="Momentum or reversion"
          value={snapAll?.ic != null ? num(snapAll.ic, 3) : win?.ic != null ? num(win.ic, 3) : "n/a"}
          sub={
            snapAll
              ? `From our snapshots over ${plural(snapAll.days ?? 0, "day")}: ${leanWords(snapAll.lean)}.`
              : `One snapshot of the averages (30 days against 90, then a day against the week): ${leanWords(win?.lean)}. Our own test needs ${snap?.waiting_days ?? "more"} more days.`
          }
          help="Rank correlation of an earlier move with the next one across liquid items. Above zero leans momentum, below leans mean reversion."
        />
        <Row
          label="Steam against Skinport"
          value={sp?.median_premium != null ? frac(sp.median_premium, 0) : "n/a"}
          sub={
            sp?.items
              ? `Median Steam premium. After fees, Skinport to Steam nets ${frac(sp.median_to_steam, 0)} in wallet funds (Steam keeps about 13 % and the money cannot be withdrawn); Steam to Skinport nets ${frac(sp.median_to_skinport, 0)} in cash (8 % fee).`
              : "No item with both prices today."
          }
        />
        <Row
          label="Cases"
          value={cases?.median7d != null ? frac(cases.median7d) : "n/a"}
          sub={[
            `median 7 days, 30 days ${frac(cases?.median30d)}`,
            cases?.new?.length ? `new: ${cases.new.map((c) => c.name).join(", ")}` : null,
            cases?.lastDrop ? `last drop ${cases.lastDrop.items.join(", ")} on ${cases.lastDrop.date} (${cases.lastDrop.kind})${cases.lastDrop.other_cases_since != null ? `, other cases ${frac(cases.lastDrop.other_cases_since)} since` : ""}` : null,
          ]
            .filter(Boolean)
            .join(" · ")}
        />
      </div>

      {movers.length > 0 && (
        <>
          <h3 className="mt-4 text-[13px] font-semibold text-muted">Top movers · {t.movers?.basis ?? ""}</h3>
          <List>
            {movers.map((m) => (
              <TrendRow key={`m-${m.name}`} it={m} value={m.move} sub={m.chg_30d != null ? `30 d ${frac(m.chg_30d)}` : undefined} />
            ))}
          </List>
        </>
      )}

      {(cases?.rising?.length ?? 0) > 0 && (
        <>
          <h3 className="mt-4 text-[13px] font-semibold text-muted">Cases up 15 % or more in 7 days</h3>
          <List>
            {cases!.rising!.slice(0, 5).map((c) => (
              <TrendRow key={`c-${c.name}`} it={c} value={c.chg_7d} sub="7 days" />
            ))}
          </List>
        </>
      )}

      {unusual.length > 0 && (
        <More title={`Unusual spreads (${unusual.length})`}>
          <List>
            {unusual.slice(0, 10).map((u) => (
              <TrendRow
                key={`u-${u.name}`}
                it={u}
                value={u.why === "cash" ? u.to_skinport : u.steam_premium}
                sub={u.why === "cash" ? "Steam to Skinport, cash, after fees" : `Steam premium; wallet route ${frac(u.to_steam, 0)}`}
              />
            ))}
          </List>
        </More>
      )}

      {groups.length > 0 && (
        <More title="By group">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[420px] text-[13px]">
              <thead>
                <tr className="text-left text-muted">
                  <th className="py-1.5 font-semibold">Group</th>
                  <th className="py-1.5 text-right font-semibold">Liquid</th>
                  <th className="py-1.5 text-right font-semibold">7 d</th>
                  <th className="py-1.5 text-right font-semibold">30 d</th>
                  <th className="py-1.5 text-right font-semibold">Steam vs Skinport</th>
                </tr>
              </thead>
              <tbody className="tabular">
                {groups.map((g) => (
                  <tr key={g.group} className="border-t border-line">
                    <td className="py-1.5 text-ink">{g.group}</td>
                    <td className="py-1.5 text-right">{num(g.liquid, 0)}</td>
                    <td className={`py-1.5 text-right ${TONE_TEXT[changeTone(g.median_7d)]}`}>{frac(g.median_7d)}</td>
                    <td className={`py-1.5 text-right ${TONE_TEXT[changeTone(g.median_30d)]}`}>{frac(g.median_30d)}</td>
                    <td className="py-1.5 text-right">{frac(g.steam_premium, 0)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-2 text-[13px] text-muted">
            Changes: 7 days {t.basis?.chg_7d ?? "n/a"}; 30 days {t.basis?.chg_30d ?? "n/a"}. Liquid means 1 € or more and 10 or more Skinport sales in 7 days; this Steam feed has no volume.
          </p>
        </More>
      )}
      <p className="mt-3 text-[13px] text-faint">Information only. Pythia never buys or sells; open a listing and decide by hand.</p>
    </Section>
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
  const [shown, setShown] = useState(PAGE);

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

  useEffect(() => setShown(PAGE), [filter, sort, query]);

  const rows = useMemo(() => (b ? visibleItems(b.items, filter, query, sort) : []), [b, filter, query, sort]);
  const chips = useMemo(
    () => FILTERS.map((f) => ({ ...f, count: b ? visibleItems(b.items, f.id, "", "liquid").length : undefined })),
    [b],
  );

  const title = "CS2 Skins";
  const subtitle =
    "Skinport and Steam prices, a forecast for each item after fees, and a play-money portfolio. Nothing here buys or sells: you decide, and trade by hand if at all.";
  const right =
    mode !== "none" ? (
      <Button variant="secondary" size="sm" icon={RefreshCw} onClick={() => void refresh()}>
        Refresh
      </Button>
    ) : undefined;

  if (mode === "none") {
    return (
      <Page title={title} subtitle={subtitle}>
        <Section title="Not available here" hint="The board is read from the lab's data folder.">
          <Nothing icon={Crosshair} title="The CS2 board needs the desktop app or a connected server">
            This browser version cannot reach the lab's data folder, so there is nothing to show here.
          </Nothing>
        </Section>
      </Page>
    );
  }

  const p = b?.portfolio ?? null;
  const counts = b ? boardCounts(b) : { buy: 0, lookAt: 0, avoid: 0 };
  const r = b?.research ?? null;
  const days = b ? plural(b.historyDays, "day") : "";
  const bootstrap = b?.model.src7 !== "walk_forward";

  return (
    <Page title={title} subtitle={subtitle} right={right} wide>
      {!loaded && (
        <Section title="Market" bare>
          <LoadingRows rows={4} label="Reading the CS2 board" />
        </Section>
      )}
      {err && (
        <Notice tone="danger" title="Could not read the CS2 board">
          {err}
        </Notice>
      )}
      {loaded && !err && (!b || b.status !== "ok") && (
        <Section title="Market">
          <Nothing icon={Crosshair} title="No CS2 data yet">
            {b?.headline ||
              "The collector (lab.collect.cs2) and the hourly job (lab.cs2.run) fill this page once they run on the lab machine."}
          </Nothing>
        </Section>
      )}

      {b && b.status === "ok" && (
        <>
          <KeyStats
            items={[
              {
                label: "Paper portfolio",
                value: p ? eur(p.equity) : "n/a",
                tone: p ? (p.returnPct > 0.005 ? "up" : p.returnPct < -0.005 ? "down" : "plain") : "plain",
                sub: p ? `${signedPct(p.returnPct)} since ${(p.started ?? "").slice(0, 10) || "today"}, play money, after the sale fee` : "Starts at the first weekly look",
                help: "What the play-money portfolio would get for everything today on Skinport, after Skinport's sale fee. Nothing is bought or sold for real.",
              },
              {
                label: "Buy ideas",
                value: String(counts.buy),
                tone: counts.buy > 0 ? "up" : "plain",
                sub: `forecast at least 3 % above the ${b.hurdle != null ? frac(b.hurdle, 0).replace("+", "") : "10 %"} round trip`,
                help: "Liquid items whose forecast clears Skinport's fee and a spread allowance by 3 % or more. A guess, not advice.",
              },
              {
                label: "History",
                value: days,
                tone: b.historyDays < 30 ? "warn" : "plain",
                sub: bootstrap ? "Too short to test; the forecast is a bootstrap" : "Walk-forward forecast",
                help: "Days of prices the collector has gathered. The forecaster needs about two months before it can be tested on its own history.",
              },
            ]}
          />

          <Notice
            tone={b.feedStatus === "bad" ? "warning" : "info"}
            icon={b.feedStatus === "bad" ? TriangleAlert : ShieldCheck}
            title={b.headline || b.verdict}
          >
            {b.model.note}{" "}
            {bootstrap
              ? "Forecasts are before fees and relative to the median item: read them as a ranking, not a price target. "
              : "Forecasts are before fees. "}
            The 7-day change is against the {b.change7Basis}. Updated {b.generated}. Paper only: automated
            buying or selling on Steam or a skin marketplace breaks their terms, and Pythia never does it.
          </Notice>

          {b.steamTrends && b.steamTrends.date && <SteamTrends t={b.steamTrends} />}

          {b.alerts.length > 0 && (
            <Section title="Worth a look by hand" hint="Recent alerts. Gaps are after both venues' fees; Steam pays in wallet funds, not cash.">
              <List>
                {b.alerts.slice(0, 8).map((a, i) => {
                  const s = signalInfo(a.kind);
                  return (
                    <div key={`${a.name}-${a.tsMs}-${i}`} className="flex items-start gap-3 py-3">
                      <Badge tone={s.tone} title={s.help}>
                        {s.label}
                      </Badge>
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-[15px] font-semibold text-ink">{a.name}</div>
                        <div className="break-words text-[13px] text-muted">{a.text}</div>
                      </div>
                      {a.tsMs != null && <div className="shrink-0 text-[13px] text-faint">{new Date(a.tsMs).toLocaleDateString()}</div>}
                    </div>
                  );
                })}
              </List>
            </Section>
          )}

          <Section title="Market" hint={b.verdict}>
            <div className="space-y-3">
              <FilterChips options={chips} value={filter} onChange={setFilter} label="Show" />
              <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_minmax(0,320px)]">
                <label className="relative block min-w-0">
                  <Search size={16} aria-hidden className="absolute left-3 top-1/2 -translate-y-1/2 text-faint" />
                  <input className={`${inputCls} pl-9`} placeholder="Search an item" value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Search an item" />
                </label>
                <Segmented options={SORTS} value={sort} onChange={setSort} label="Sort by" />
              </div>
            </div>
            <div className="mt-3 hidden grid-cols-[minmax(0,1fr)_120px_120px_96px] gap-x-4 border-b border-line pb-2 text-[13px] text-muted sm:grid">
              <span>Item</span>
              <span className="text-right">Price, 7 days</span>
              <span className="text-right">Forecast</span>
              <span className="text-right">Signal</span>
            </div>
            {rows.length === 0 ? (
              <Nothing icon={Search} title="Nothing matches" />
            ) : (
              <>
                <List>
                  {rows.slice(0, shown).map((x) => (
                    <ItemRow key={x.name} r={x} />
                  ))}
                </List>
                {rows.length > shown && (
                  <div className="pt-3 text-center">
                    <Button variant="ghost" size="sm" onClick={() => setShown((n) => n + PAGE)}>
                      Show {Math.min(PAGE, rows.length - shown)} more of {rows.length - shown}
                    </Button>
                  </div>
                )}
              </>
            )}
          </Section>

          {p && (
            <Section
              title="Paper portfolio"
              hint="Play money in euro on Skinport prices and fee: the forecast's top picks, at most 10 items at 10 % each, looked at weekly, held at least 30 days."
            >
              {p.equityCurve.length >= 2 ? (
                <Sparkline data={p.equityCurve} height={56} fill label="Paper portfolio value over time" />
              ) : (
                <p className="text-[13px] text-muted">The chart starts after the second day.</p>
              )}
              <div className="mt-2 divide-y divide-line">
                <Row label="Value after the sale fee" value={eur(p.equity)} valueSub={`from ${eur(p.startEquity)}`} help="What selling everything today would net." />
                <Row label="Cash" value={eur(p.cash)} help="Play money not in any item." />
                <Row label="Last look" value={p.lastRebalance ?? "never"} sub="Once a week; nothing is bought unless it clears the fees by 3 %." help="The weekly rebalance date." />
              </div>
              {p.positions.length === 0 ? (
                <p className="pt-2 text-[13px] text-muted">No items held: nothing cleared the fees at the last look, so it holds cash.</p>
              ) : (
                <List className="mt-1">
                  {p.positions.map((x) => (
                    <div key={x.name} className="flex items-start justify-between gap-3 py-3">
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-[15px] font-semibold text-ink">{x.name}</div>
                        <div className="text-[13px] text-muted">
                          {num(x.qty, 0)} bought {x.bought} at {eur(x.cost)}
                        </div>
                      </div>
                      <div className="shrink-0 text-right">
                        <div className="tabular text-[15px] font-semibold text-ink">{eur(x.price)}</div>
                        <Change pct={x.returnPct ?? 0} tone={changeTone((x.returnPct ?? 0) / 100)} size="sm" />
                      </div>
                    </div>
                  ))}
                </List>
              )}
            </Section>
          )}

          {r && (
            <Section title="What the research says" hint="From the daily report. Read the history line first: most of these numbers come from very little data.">
              <div className="divide-y divide-line">
                <Row label="History" value={plural(r.historyDays ?? b.historyDays, "day")} sub={r.firstDay ? `since ${r.firstDay}` : undefined} />
                <Row
                  label="Momentum or reversion"
                  value={r.momentumIc != null ? num(r.momentumIc, 3) : "n/a"}
                  sub="Rank IC of the earlier price change with the last week's change, one snapshot. Below zero leans to reversion; part of that is how it is measured."
                  help="Rank information coefficient: how well one number orders the items by what came next. 0 is no relation, 1 is a perfect order."
                />
                <Row
                  label="Forecaster, 7 days"
                  value={r.bootstrapIc7 != null ? num(r.bootstrapIc7, 3) : "n/a"}
                  sub={`Bootstrap rank IC across ${r.bootstrapItems != null ? num(r.bootstrapItems, 0) : "n/a"} items. Not a backtest. Walk-forward: ${r.walkForward7 ?? "not run"}.`}
                />
                <Row
                  label="Skinport against Steam"
                  value={r.spread?.toSteamMedian != null ? frac(r.spread.toSteamMedian) : "n/a"}
                  sub={r.spread?.status === "ok" ? "Median of buying on Skinport and selling on Steam, after both fees, today." : (r.spread?.status ?? "No Steam prices yet.")}
                />
              </div>
              <More title="The full report">
                <p className="text-sm leading-relaxed text-muted">{r.verdict}</p>
                <p className="mt-2 text-sm leading-relaxed text-muted">
                  The full write-up, with the fees, the case study and the paper rules, is the study &ldquo;CS2 skins market&rdquo; on the
                  Research page.
                </p>
              </More>
            </Section>
          )}
        </>
      )}
    </Page>
  );
}
