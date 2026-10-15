import { useState } from "react";
import {
  ArrowDownLeft,
  ArrowUpRight,
  Bell,
  ChevronDown,
  FileText,
  HelpCircle,
  PauseCircle,
  Plane,
  Plus,
  Power,
  Repeat,
  ShieldAlert,
  ShieldCheck,
  Target,
  TriangleAlert,
  Wallet,
  XCircle,
  type LucideIcon,
} from "lucide-react";
import {
  AreaChart,
  BigNumber,
  Button,
  Card,
  Change,
  Chip,
  Empty,
  List,
  ListRow,
  Notice,
  RangeChips,
  SectionTitle,
  Skeleton,
  changeTone,
  money,
  signedPct,
  type Range,
} from "../design";
import { InsightsCard } from "../components/Insights";
import { AssetSheet } from "../components/AssetDetail";
import { Explain } from "../components/ui";
import { explain } from "../glossary";
import { liveMode } from "../live";
import { openPage } from "../navigate";
import { useStore } from "../store";
import { setUiMode, useAdvanced } from "../uiMode";
import { useAutopilotApi } from "./Autopilot";
import { change, combinedCurve, combinedHoldings, inRange, positionHoldings, usefulRanges, type Point } from "../flows/homeView";
import { totals } from "../flows/autopilotView";
import { timeOfDay, timeline, type ActivityKind } from "../flows/activity";

const RANGE_WORDS: Record<Range, string> = {
  "1D": "past day",
  "1W": "past week",
  "1M": "past month",
  "1Y": "past year",
  Max: "since the start",
};

const ACTIVITY_ICON: Record<ActivityKind, LucideIcon> = {
  buy: ArrowDownLeft,
  sell: ArrowUpRight,
  rebalance: Repeat,
  autopilot: Plane,
  alert: Bell,
  risk: ShieldAlert,
  refused: XCircle,
  summary: FileText,
};

/**
 * The default view, written for someone who has never traded.
 *
 * The portfolio first, the way a banking app shows it: one big number, the
 * change in green or red, a smooth chart with ranges. Then whether it is
 * running and with what money, with the stop button; what it holds; what
 * happened today; and the few things from the lab worth knowing. Every number
 * is in plain words or currency. Anything a beginner cannot act on is not here.
 */
export function Home() {
  const { portfolio, positions, journal, strategies, markets, forecasts, forecastStats, live, limits, toggleKill } = useStore();
  const api = useAutopilotApi();
  const advanced = useAdvanced();
  const [range, setRange] = useState<Range>("1D");
  const [scrub, setScrub] = useState<number | null>(null);
  const [asset, setAsset] = useState<string | null>(null);
  const now = Date.now();

  const realMoney = live.armed && !live.paper && !live.dryRun;
  const running = strategies.filter((s) => s.state !== "paused" && s.id !== "manual").length;
  const realPositions = positions.filter((p) => p.live).length;
  const loading = api.loading || (portfolio.equity <= 0 && markets.length === 0);

  // With autopilots the portfolio is theirs; without, it is the practice account.
  const t = totals(api.autopilots);
  const viaAutopilots = t.count > 0;
  const full: Point[] = combinedCurve(api.autopilots, now);
  const ranges = usefulRanges(full, now);
  const shownRange: Range = ranges.includes(range) ? range : "Max";
  const pts = viaAutopilots ? inRange(full, shownRange, now) : [];
  const values = viaAutopilots ? pts.map((p) => p[1]) : portfolio.equityCurve;
  const value = viaAutopilots ? t.value : portfolio.equity;
  const delta = viaAutopilots ? change(pts) : { abs: portfolio.equity - portfolio.dayStartEquity, pct: portfolio.dayStartEquity > 0 ? ((portfolio.equity - portfolio.dayStartEquity) / portfolio.dayStartEquity) * 100 : null };
  const words = viaAutopilots ? RANGE_WORDS[shownRange] : "today";

  const shownValue = scrub != null && values[scrub] != null ? values[scrub] : value;
  const scrubWords = scrub != null && viaAutopilots && pts[scrub] ? whenWords(pts[scrub][0], shownRange) : null;
  const scrubDelta = scrub != null && values.length > 0 ? values[scrub] - values[0] : null;

  const held = viaAutopilots ? combinedHoldings(api.autopilots, positions) : positionHoldings(positions);
  const today = timeline({ journal, markets }, now).find((d) => d.label === "Today");

  return (
    <div className="mx-auto w-full max-w-2xl space-y-6 pb-8">
      <h1 className="sr-only">Home</h1>

      {/* The portfolio */}
      <section aria-label="Portfolio" className="space-y-4">
        {loading ? (
          <div className="space-y-3">
            <Skeleton className="h-4 w-28" />
            <Skeleton className="h-11 w-56" />
            <Skeleton className="h-4 w-40" />
            <Skeleton className="mt-4 h-[200px] w-full rounded-2xl" />
          </div>
        ) : (
          <>
            <BigNumber
              size="xl"
              label={
                <span className="inline-flex items-center gap-1.5">
                  {viaAutopilots ? (t.count === 1 ? "Your autopilot" : `Your ${t.count} autopilots`) : realMoney ? "Your account" : "Practice balance"}
                  <Explain text={explain("Equity")!} label="balance" />
                </span>
              }
              value={money(shownValue)}
              sub={
                scrubWords ? (
                  <Change usd={scrubDelta} tone={changeTone(scrubDelta)} suffix={scrubWords} />
                ) : (
                  <Change usd={delta.abs} pct={delta.pct} tone={changeTone(delta.abs)} suffix={words} />
                )
              }
            />
            <AreaChart
              data={values}
              height={200}
              label={`${viaAutopilots ? "Portfolio" : "Balance"} over the ${words}, ${delta.abs >= 0 ? "up" : "down"} ${money(Math.abs(delta.abs))}`}
              baseline={values.length > 1 ? values[0] : undefined}
              onScrub={(s) => setScrub(s ? s.index : null)}
              empty={viaAutopilots ? "The chart fills in as the autopilots trade." : "The chart fills in as new prices arrive."}
            />
            {viaAutopilots && <RangeChips value={shownRange} onChange={setRange} disabled={(["1D", "1W", "1M", "1Y"] as Range[]).filter((r) => !ranges.includes(r))} />}
          </>
        )}
      </section>

      {/* Is it running, is real money at risk, how do I stop it */}
      <StatusCard
        realMoney={realMoney}
        practiceArmed={live.armed && !realMoney}
        killed={limits.killSwitch}
        running={running}
        autopilots={t.count}
        loading={loading}
        realPositions={realPositions}
        blockedReason={live.armed ? live.blockedReason : undefined}
        onToggleKill={toggleKill}
      />

      {/* What it holds */}
      <section aria-labelledby="home-holdings" className="space-y-2">
        <SectionTitle>
          <span id="home-holdings">Holdings</span>
        </SectionTitle>
        <Card>
          {loading ? (
            <RowSkeletons n={3} />
          ) : held.length === 0 ? (
            <Empty icon={Wallet} title="All in cash" compact action={!viaAutopilots ? <Button size="sm" icon={Plus} onClick={() => openPage("autopilot")}>Start an autopilot</Button> : undefined}>
              {viaAutopilots ? "The autopilots hold nothing right now and wait for a signal." : "Nothing is bought yet. An autopilot buys and sells for you."}
            </Empty>
          ) : (
            <List className="-my-2">
              {held.slice(0, 8).map((h) => (
                <ListRow
                  key={h.marketId}
                  ticker={h.coin}
                  title={h.coin}
                  subtitle={`${fmtQty(h.qty)} ${h.coin.split("/")[0]}`}
                  right={money(h.value)}
                  rightSub={<Change pct={h.pnlPct} tone={changeTone(h.pnl)} size="sm" />}
                  onClick={() => setAsset(h.marketId)}
                />
              ))}
            </List>
          )}
        </Card>
      </section>

      {/* What happened today */}
      <section aria-labelledby="home-today" className="space-y-2">
        <SectionTitle
          right={
            <button type="button" onClick={() => openPage("activity")} className="rounded text-[15px] font-semibold text-accent hover:underline">
              See all
            </button>
          }
        >
          <span id="home-today">Today</span>
        </SectionTitle>
        <Card>
          {!today || today.items.length === 0 ? (
            <p className="py-1 text-[15px] text-muted">Nothing happened yet today. Trades and alerts show up here as they happen.</p>
          ) : (
            <>
              {today.summary && <p className="mb-1 text-[13px] text-muted">{today.summary}</p>}
              <List className="-mb-2">
                {today.items.slice(0, 5).map((it) => (
                  <ListRow
                    key={it.id}
                    icon={ACTIVITY_ICON[it.kind]}
                    title={it.title}
                    subtitle={it.detail}
                    right={it.amount}
                    rightSub={
                      <span className="inline-flex items-center gap-1.5 text-muted">
                        {it.real && <Chip tone="bad">Real</Chip>}
                        {timeOfDay(it.ts)}
                      </span>
                    }
                  />
                ))}
              </List>
            </>
          )}
        </Card>
      </section>

      {/* The lab's three most important things today (hidden without an engine). */}
      <InsightsCard />

      {/* What it thinks (only where a forecaster runs) */}
      <TopPredictions forecasts={forecasts} untrusted={forecastStats.trustedSources === 0} />

      <WeekReport />

      {advanced && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <MiniStat label="Markets watched" value={markets.length} />
          <MiniStat label="Strategies running" value={running} />
          <MiniStat label="Trades made today" value={journal.filter((j) => j.kind === "fill").length} />
          <MiniStat label="Things it owns" value={positions.length} />
        </div>
      )}

      <Explainer />
      <AssetSheet marketId={asset} onClose={() => setAsset(null)} />
    </div>
  );
}

function whenWords(ts: number, range: Range): string {
  const d = new Date(ts);
  if (range === "1D") return `at ${timeOfDay(ts)}`;
  const day = d.toLocaleDateString("en-GB", { day: "numeric", month: "short", ...(range === "1Y" || range === "Max" ? { year: "numeric" } : {}) });
  return range === "1W" ? `on ${day}, ${timeOfDay(ts)}` : `on ${day}`;
}

function fmtQty(q: number): string {
  const a = Math.abs(q);
  const dp = a >= 100 ? 2 : a >= 1 ? 4 : 6;
  return Number(q.toFixed(dp)).toLocaleString("en-US", { maximumFractionDigits: dp });
}

function RowSkeletons({ n }: { n: number }) {
  return (
    <div>
      {Array.from({ length: n }, (_, i) => (
        <div key={i} className="flex items-center gap-3 py-3">
          <Skeleton className="h-10 w-10 rounded-full" />
          <div className="flex-1 space-y-2">
            <Skeleton className="h-4 w-1/3" />
            <Skeleton className="h-3 w-1/2" />
          </div>
          <Skeleton className="h-4 w-16" />
        </div>
      ))}
    </div>
  );
}

function MiniStat({ label, value }: { label: string; value: number }) {
  const tip = explain(label);
  return (
    <div className="min-w-0 rounded-2xl bg-surface-2 px-4 py-3">
      <div className="flex items-center gap-1 text-[12px] text-muted">
        <span className="truncate">{label}</span>
        {tip && <Explain text={tip} label={label} />}
      </div>
      <div className="tabular text-xl font-bold text-ink">{value}</div>
    </div>
  );
}

/**
 * Whether it is running and with what money, the stop button beside it, and
 * anything that needs attention spelled out.
 */
function StatusCard({
  realMoney,
  practiceArmed,
  killed,
  running,
  autopilots,
  loading,
  realPositions,
  blockedReason,
  onToggleKill,
}: {
  realMoney: boolean;
  practiceArmed: boolean;
  killed: boolean;
  running: number;
  autopilots: number;
  loading: boolean;
  realPositions: number;
  blockedReason?: string;
  onToggleKill: () => void;
}) {
  const problems: string[] = [];
  if (realPositions > 0 && !realMoney) {
    problems.push(`${realPositions} position${realPositions > 1 ? "s were" : " was"} bought for real earlier and ${realPositions > 1 ? "are" : "is"} still open at the broker.`);
  }
  if (blockedReason) problems.push(`New trades are on hold: ${blockedReason}`);

  let headline: string;
  let detail: string;
  let tint: string;
  let Icon: LucideIcon;
  if (killed) {
    headline = "Stopped by you";
    detail = "It is not opening anything new. It can still close what it already owns.";
    tint = "bg-down/10 text-down";
    Icon = Power;
  } else if (realMoney) {
    headline = "Running with real money";
    detail = "Orders go to a real broker and can lose real money. Stop it any time with the button.";
    tint = "bg-down text-on-down";
    Icon = TriangleAlert;
  } else if (!loading && running === 0 && autopilots === 0) {
    headline = "Paused: nothing is switched on";
    detail = "Practice mode, so nothing can be lost. It will not trade until a strategy or an autopilot runs.";
    tint = "bg-warn/10 text-warn";
    Icon = PauseCircle;
  } else {
    headline = "Running in practice mode";
    detail = practiceArmed
      ? "Fake money on real prices. A test connection to a broker is switched on, but on its practice account."
      : "Fake money on real prices. Nothing leaves this computer and nothing can be lost.";
    tint = "bg-up/10 text-up";
    Icon = ShieldCheck;
  }

  return (
    <Card label="Status">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-3">
        <div className="flex min-w-0 flex-1 basis-60 items-start gap-3">
          <span className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-full ${tint}`} aria-hidden>
            <Icon size={19} />
          </span>
          <div className="min-w-0">
            <div className="text-[15px] font-semibold leading-snug text-ink">{headline}</div>
            <p className="mt-0.5 text-[13px] leading-relaxed text-muted">{detail}</p>
          </div>
        </div>
        <Button variant={killed ? "primary" : "secondary"} size="sm" icon={Power} onClick={onToggleKill}>
          {killed ? "Let it trade again" : "Stop everything"}
        </Button>
      </div>
      {problems.length > 0 && (
        <div className="mt-4 space-y-2">
          {problems.map((p) => (
            <Notice key={p} tone="warning">
              {p}
            </Notice>
          ))}
        </div>
      )}
    </Card>
  );
}

const WEEK_KEY = "pythia.weekStart.v1";

/** Monday 00:00 UTC of the current week, in ms. */
function weekStartMs(now: number): number {
  const d = new Date(now);
  const day = (d.getUTCDay() + 6) % 7; // Monday = 0
  return Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate() - day);
}

/**
 * This week in plain words: trades made, up or down, and whether its
 * predictions have earned any trust yet. The balance at the start of the week
 * is remembered in this browser the first time the page opens that week.
 */
function WeekReport() {
  const { portfolio, journal, forecastStats } = useStore();
  const now = Date.now();
  const start = weekStartMs(now);

  let base: { week: number; equity: number; since: number } | null = null;
  try {
    base = JSON.parse(localStorage.getItem(WEEK_KEY) ?? "null");
  } catch {
    base = null;
  }
  // Only a real balance may become the week's starting point: on the first
  // render the engine has not answered yet and equity reads 0.
  const loaded = portfolio.equity > 0;
  if (!base || base.week !== start || !(base.equity > 0)) {
    base = loaded ? { week: start, equity: portfolio.equity, since: now } : null;
    if (base) {
      try {
        localStorage.setItem(WEEK_KEY, JSON.stringify(base));
      } catch {
        /* the report still works for this visit */
      }
    }
  }
  if (!base) return null;

  const fills = journal.filter((j) => j.kind === "fill" && j.ts >= start).length;
  const oldest = journal.length ? Math.min(...journal.map((j) => j.ts)) : now;
  const atLeast = oldest > start && journal.length > 0; // the journal keeps only recent entries
  const delta = portfolio.equity - base.equity;
  const sinceMonday = base.since - start < 6 * 3_600_000;
  const sinceWords = sinceMonday ? "since Monday" : `since you first opened it this week (${new Date(base.since).toLocaleDateString("en", { weekday: "long" })})`;

  const checked = forecastStats.resolved;
  const trusted = forecastStats.trustedSources;
  const moved = Math.abs(delta) >= 0.005;

  return (
    <Card title="This week">
      <p className="text-[15px] leading-relaxed text-muted">
        {fills === 0 ? (
          <>Pythia has not made any trades yet</>
        ) : (
          <>
            Pythia made{" "}
            <b className="font-semibold text-ink">
              {atLeast ? "at least " : ""}
              {fills}
            </b>{" "}
            trade{fills === 1 ? "" : "s"}
          </>
        )}{" "}
        and is{" "}
        {moved ? (
          <b className={`font-semibold ${delta >= 0 ? "text-up" : "text-down"}`}>
            {delta >= 0 ? "up" : "down"} {money(Math.abs(delta))}
          </b>
        ) : (
          <b className="font-semibold text-ink">exactly where it started</b>
        )}{" "}
        {sinceWords}.{" "}
        {checked === 0
          ? "None of its predictions has been checked against reality yet."
          : trusted === 0
            ? `Its predictions have been checked ${checked.toLocaleString()} times and none of its sources beats the market yet, so it is not betting on them.`
            : `Its predictions have been checked ${checked.toLocaleString()} times, and ${trusted} source${trusted === 1 ? " has" : "s have"} earned enough trust to be acted on.`}
      </p>
    </Card>
  );
}

/**
 * The three markets it currently has the strongest view on, in words.
 *
 * A beginner does not need the pooled log-odds; they need to know whether the
 * app disagrees with the market, by how much, and whether it has any business
 * disagreeing yet. Left out where no forecaster runs (the browser demo).
 */
function TopPredictions({ forecasts, untrusted }: { forecasts: ReturnType<typeof useStore>["forecasts"]; untrusted: boolean }) {
  if (liveMode() === "none") return null;
  const top = [...forecasts]
    .filter((f) => f.kind === "outcome")
    .sort((a, b) => Math.abs(b.edge) - Math.abs(a.edge))
    .slice(0, 3);

  return (
    <section aria-labelledby="home-thinks" className="space-y-2">
      <SectionTitle>
        <span id="home-thinks">What it thinks</span>
      </SectionTitle>
      <Card>
        {untrusted && (
          <Notice tone="info" title="It is still learning" className="mb-3">
            Every prediction is written down and checked against what happened. Until its guesses beat the market's own price, it does not act on them.
          </Notice>
        )}
        {top.length === 0 ? (
          <Empty icon={Target} title="No prediction markets yet" compact>
            They usually arrive within a few seconds of starting.
          </Empty>
        ) : (
          <List className="-my-2">
            {top.map((f) => {
              const mine = Math.round(f.ensembleP * 100);
              const mkt = Math.round(f.marketP * 100);
              const diff = mine - mkt;
              return (
                <ListRow
                  key={f.marketId}
                  icon={Target}
                  title={f.symbol}
                  subtitle={
                    <>
                      Market {mkt}%, Pythia {mine}%.{" "}
                      {Math.abs(diff) < 1 ? "It agrees." : `It thinks that is ${Math.abs(diff)} point${Math.abs(diff) === 1 ? "" : "s"} too ${diff > 0 ? "low" : "high"}.`}
                      {f.action === "hold" && ` Not acting: ${plainReason(f.reason)}`}
                    </>
                  }
                  right={`${mine}%`}
                  rightSub={<span className={diff > 0 ? "text-up" : diff < 0 ? "text-down" : "text-muted"}>{signedPct(diff, 0).replace("%", " pts")}</span>}
                />
              );
            })}
          </List>
        )}
      </Card>
    </section>
  );
}

/** Translate the engine's reason string out of trading vocabulary. */
function plainReason(reason: string): string {
  if (reason.includes("track record")) return "it has not proven itself yet.";
  if (reason.includes("round-trip cost")) return "the fees would eat the whole difference.";
  if (reason.includes("below the")) return "the difference is too small to be worth the fees.";
  if (reason.includes("no forecaster")) return "nothing has an opinion on this one.";
  return reason;
}

function Explainer() {
  const [open, setOpen] = useState(false);
  return (
    <Card>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-controls="home-explainer"
        className="flex w-full items-center gap-3 rounded-control text-left text-[15px] font-semibold text-ink"
      >
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-surface-2" aria-hidden>
          <HelpCircle size={18} />
        </span>
        What is this app actually doing?
        <ChevronDown size={18} aria-hidden className={`ml-auto shrink-0 text-faint transition-transform ${open ? "rotate-180" : ""}`} />
      </button>

      {open && (
        <div id="home-explainer" className="mt-4 space-y-3 text-[15px] leading-relaxed text-muted">
          <p>
            Pythia watches a set of markets (some prediction markets, &ldquo;will this happen?&rdquo;, some crypto, some shares) and forms an opinion about where each is
            going. When it thinks the market is wrong by enough to be worth the fees, it can place a trade.
          </p>
          <p>
            <b className="font-semibold text-ink">It starts in practice mode.</b> The balance is fake, the trades are simulated, and nothing can be lost. Turning on real
            trading takes several deliberate steps and a typed confirmation. It cannot happen by accident.
          </p>
          <p>
            <b className="font-semibold text-ink">It has to earn your trust, literally.</b> Every prediction is written down and later checked against what really
            happened. Until a source of predictions beats the market's own price over a real track record, Pythia refuses to act on it. That is why a fresh install
            mostly agrees with the market and trades very little.
          </p>
          <p>
            <b className="font-semibold text-ink">Nobody can promise you profit.</b> Not this app, not anyone. Most automated trading loses money to fees. Only ever use
            money you can afford to lose entirely.
          </p>
          <p className="text-faint">
            Want the full instrument panel with charts, strategies, backtests and risk limits?{" "}
            <button type="button" onClick={() => setUiMode("advanced")} className="font-semibold text-accent underline underline-offset-2">
              Switch on advanced view
            </button>
            . You can switch back any time at the bottom of the menu or in Settings.
          </p>
        </div>
      )}
    </Card>
  );
}
