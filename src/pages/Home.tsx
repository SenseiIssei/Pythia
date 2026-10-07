import { useState } from "react";
import {
  ShieldCheck,
  TriangleAlert,
  Power,
  ChevronDown,
  Eye,
  Activity,
  ArrowLeftRight,
  Package,
  HelpCircle,
  PauseCircle,
  Target,
  CheckCircle2,
  type LucideIcon,
} from "lucide-react";
import { Button, Card, EmptyState, Explain, Loading, Sparkline, fmtUsd, type Tone } from "../components/ui";
import { explain } from "../glossary";
import { liveMode } from "../live";
import { useStore } from "../store";
import { setUiMode } from "../uiMode";

/**
 * The default view, written for someone who has never traded.
 *
 * It answers the questions in the order they matter: is it running, is real
 * money at risk, is it making or losing money, is anything wrong, and how do I
 * stop it. All of that sits in the first card, with the stop button. Below it:
 * the balance, what it is doing, the week, and what it thinks. Every number is
 * in plain words or currency: no basis points, no P&L, no drawdown, no Sharpe.
 * Anything a beginner cannot act on is not here.
 */
export function Home() {
  const { portfolio, positions, journal, strategies, markets, forecasts, forecastStats, live, limits, toggleKill } =
    useStore();

  const realMoney = live.armed && !live.paper && !live.dryRun;
  const change = portfolio.equity - portfolio.dayStartEquity;
  const changePct = portfolio.dayStartEquity > 0 ? (change / portfolio.dayStartEquity) * 100 : 0;
  const running = strategies.filter((s) => s.state !== "paused" && s.id !== "manual").length;
  const tradesToday = journal.filter((j) => j.kind === "fill").length;
  const realPositions = positions.filter((p) => p.live).length;
  const loading = portfolio.equity <= 0 && markets.length === 0;

  return (
    <div className="animate-fade-in mx-auto max-w-3xl space-y-4">
      <h1 className="sr-only">Home</h1>

      {/* 1 · Is it running, is real money at risk, is anything wrong, how do I stop it. */}
      <StatusCard
        realMoney={realMoney}
        practiceArmed={live.armed && !realMoney}
        killed={limits.killSwitch}
        running={running}
        change={change}
        loading={loading}
        realPositions={realPositions}
        blockedReason={live.armed ? live.blockedReason : undefined}
        onToggleKill={toggleKill}
      />

      {/* 2 · How am I doing? */}
      <Card>
        {loading ? (
          <Loading>Starting the engine and reading prices</Loading>
        ) : (
          <>
            <div className="flex items-center gap-1.5 text-sm text-cyber-text-dim">
              {realMoney ? "Your account is worth" : "Your practice balance is"}
              <Explain text={explain("Equity")!} label="balance" />
            </div>
            <div className="mt-1 font-mono text-3xl font-bold tabular-nums text-cyber-text sm:text-4xl">
              {fmtUsd(portfolio.equity, 2)}
            </div>
            <div className="mt-1 flex flex-wrap items-baseline gap-x-2 text-sm">
              <ChangeText change={change} pct={changePct} />
              <span className="text-cyber-text-faint">started the day at {fmtUsd(portfolio.dayStartEquity, 2)}</span>
            </div>
            <div className="mt-4">
              <Sparkline
                data={portfolio.equityCurve}
                height={110}
                tone={change >= 0 ? "green" : "red"}
                label={`Balance over time, ${change >= 0 ? "up" : "down"} today`}
              />
            </div>
          </>
        )}
      </Card>

      {/* 3 · What is it doing? */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <PlainStat label="Markets watched" value={String(markets.length)} icon={Eye} />
        <PlainStat label="Strategies running" value={String(running)} icon={Activity} />
        <PlainStat label="Trades made today" value={String(tradesToday)} icon={ArrowLeftRight} />
        <PlainStat
          label="Things it owns"
          value={String(positions.length)}
          icon={Package}
          hint={realPositions > 0 ? `${realPositions} bought for real` : undefined}
        />
      </div>

      {/* The week in one paragraph. */}
      <WeekReport />

      {/* 4 · What does it think? */}
      <TopPredictions forecasts={forecasts} untrusted={forecastStats.trustedSources === 0} />

      <Explainer />
    </div>
  );
}

function ChangeText({ change, pct }: { change: number; pct: number }) {
  if (Math.abs(change) < 0.005) {
    return <span className="font-medium text-cyber-text-dim">No change today</span>;
  }
  const up = change > 0;
  return (
    <span className={`font-medium ${up ? "text-success" : "text-danger"}`}>
      {up ? "Up" : "Down"} {fmtUsd(Math.abs(change), 2)} today ({up ? "+" : ""}
      {pct.toFixed(2)}%)
    </span>
  );
}

/**
 * The first thing on the page. One headline that says whether it is running
 * and with what money, three short answers underneath, the stop button beside
 * it, and anything that needs attention spelled out.
 */
function StatusCard({
  realMoney,
  practiceArmed,
  killed,
  running,
  change,
  loading,
  realPositions,
  blockedReason,
  onToggleKill,
}: {
  realMoney: boolean;
  practiceArmed: boolean;
  killed: boolean;
  running: number;
  change: number;
  loading: boolean;
  realPositions: number;
  blockedReason?: string;
  onToggleKill: () => void;
}) {
  const problems: string[] = [];
  if (realPositions > 0 && !realMoney) {
    problems.push(
      `${realPositions} position${realPositions > 1 ? "s were" : " was"} bought for real earlier and ${
        realPositions > 1 ? "are" : "is"
      } still open at the broker.`,
    );
  }
  if (blockedReason) problems.push(`New trades are on hold: ${blockedReason}`);

  let headline: string;
  let detail: string;
  let tone: "green" | "red" | "amber";
  let Icon: LucideIcon;
  if (killed) {
    headline = "Stopped by you";
    detail = "It is not opening anything new. It can still close what it already owns.";
    tone = "red";
    Icon = Power;
  } else if (realMoney) {
    headline = "Running with real money";
    detail = "Orders go to a real broker and can lose real money. Stop it any time with the button.";
    tone = "red";
    Icon = TriangleAlert;
  } else if (!loading && running === 0) {
    headline = "Paused: no strategy is switched on";
    detail = "Practice mode, so nothing can be lost. It will not trade until a strategy runs again.";
    tone = "amber";
    Icon = PauseCircle;
  } else {
    headline = "Running in practice mode";
    detail = practiceArmed
      ? "Fake money on real prices. A test connection to a broker is switched on, but on its practice account."
      : "Fake money on real prices. Nothing leaves this computer and nothing can be lost.";
    tone = "green";
    Icon = ShieldCheck;
  }

  const box = {
    green: "border-success/35 bg-success/[0.06]",
    red: "border-danger/50 bg-danger/10",
    amber: "border-warning/40 bg-warning/[0.07]",
  }[tone];
  const text = { green: "text-success", red: "text-danger", amber: "text-warning" }[tone];

  const moved = Math.abs(change) >= 0.005;
  return (
    <section
      aria-label="Status"
      className={`rounded-xl border p-4 sm:p-5 ${box} ${realMoney && !killed ? "animate-pulse-red" : ""}`}
    >
      <div className="flex flex-wrap items-start gap-x-4 gap-y-3">
        <div className="flex min-w-0 flex-1 basis-64 items-start gap-3">
          <Icon size={22} aria-hidden className={`mt-0.5 shrink-0 ${text}`} />
          <div className="min-w-0">
            <div className={`text-lg font-semibold leading-tight ${text}`}>{headline}</div>
            <p className="mt-1 text-sm leading-relaxed text-cyber-text-dim">{detail}</p>
          </div>
        </div>
        <Button tone={killed ? "cyan" : "red"} icon={Power} onClick={onToggleKill}>
          {killed ? "Let it trade again" : "Stop everything"}
        </Button>
      </div>

      <dl className="mt-4 grid grid-cols-3 gap-2">
        <Answer q="Real money?" a={realMoney ? "Yes" : "No, practice"} tone={realMoney ? "red" : "green"} />
        <Answer
          q="Today"
          a={loading ? "Waiting" : !moved ? "No change" : `${change > 0 ? "Up" : "Down"} ${fmtUsd(Math.abs(change), 2)}`}
          tone={loading || !moved ? "neutral" : change > 0 ? "green" : "red"}
          plain
        />
        <Answer
          q="Anything wrong?"
          a={problems.length === 0 ? "No" : `${problems.length} to check`}
          tone={problems.length === 0 ? "green" : "amber"}
        />
      </dl>

      {problems.length > 0 && (
        <ul className="mt-3 space-y-1.5">
          {problems.map((p) => (
            <li key={p} className="flex items-start gap-2 text-sm text-warning">
              <TriangleAlert size={14} aria-hidden className="mt-0.5 shrink-0" />
              <span>{p}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/** `plain` drops the icon: a down day is a number, not an alarm. */
function Answer({ q, a, tone, plain }: { q: string; a: string; tone: Tone; plain?: boolean }) {
  const color =
    tone === "green" ? "text-success" : tone === "red" ? "text-danger" : tone === "amber" ? "text-warning" : "text-cyber-text";
  const Mark = plain ? null : tone === "green" ? CheckCircle2 : tone === "neutral" ? null : TriangleAlert;
  return (
    <div className="min-w-0 rounded-lg border border-cyber-border bg-cyber-bg/50 px-2.5 py-2 sm:px-3">
      <dt className="text-[11px] text-cyber-text-faint">{q}</dt>
      <dd className={`mt-0.5 flex items-start gap-1.5 text-[13px] font-semibold leading-snug sm:text-sm ${color}`}>
        {Mark && <Mark size={14} aria-hidden className="mt-0.5 hidden shrink-0 sm:block" />}
        <span className="min-w-0">{a}</span>
      </dd>
    </div>
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
  if (!base) {
    return (
      <Card title="This week">
        <Loading>Waiting for the first numbers from the engine</Loading>
      </Card>
    );
  }

  const fills = journal.filter((j) => j.kind === "fill" && j.ts >= start).length;
  const oldest = journal.length ? Math.min(...journal.map((j) => j.ts)) : now;
  const atLeast = oldest > start && journal.length > 0; // the journal keeps only recent entries
  const change = portfolio.equity - base.equity;
  const sinceMonday = base.since - start < 6 * 3_600_000;
  const sinceWords = sinceMonday
    ? "since Monday"
    : `since you first opened it this week (${new Date(base.since).toLocaleDateString("en", { weekday: "long" })})`;

  const checked = forecastStats.resolved;
  const trusted = forecastStats.trustedSources;
  const moved = Math.abs(change) >= 0.005;

  return (
    <Card title="This week">
      <p className="text-sm leading-relaxed text-cyber-text-dim">
        {fills === 0 ? (
          <>This week Pythia has not made any trades yet</>
        ) : (
          <>
            This week Pythia made <b className="text-cyber-text">{atLeast ? "at least " : ""}{fills}</b> trade
            {fills === 1 ? "" : "s"}
          </>
        )}{" "}
        and is{" "}
        {moved ? (
          <b className={change >= 0 ? "text-success" : "text-danger"}>
            {change >= 0 ? "up" : "down"} {fmtUsd(Math.abs(change), 2)}
          </b>
        ) : (
          <b className="text-cyber-text">exactly where it started</b>
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

function PlainStat({
  label,
  value,
  icon: Icon,
  hint,
}: {
  label: string;
  value: string;
  icon: LucideIcon;
  hint?: string;
}) {
  return (
    <div className="min-w-0 rounded-xl border border-cyber-border bg-cyber-surface px-3 py-3">
      <div className="mb-1 flex items-center gap-1.5 text-[11px] text-cyber-text-faint">
        <Icon size={12} aria-hidden className="shrink-0" />
        <span className="min-w-0 truncate">{label}</span>
        {explain(label) && <Explain text={explain(label)!} label={label} />}
      </div>
      <div className="font-mono text-xl font-bold tabular-nums">{value}</div>
      {hint && <div className="mt-0.5 text-[11px] text-warning">{hint}</div>}
    </div>
  );
}

/**
 * The three markets it currently has the strongest view on, in words.
 *
 * A beginner does not need the pooled log-odds; they need to know whether the
 * app disagrees with the market, by how much, and whether it has any business
 * disagreeing yet.
 */
function TopPredictions({
  forecasts,
  untrusted,
}: {
  forecasts: ReturnType<typeof useStore>["forecasts"];
  untrusted: boolean;
}) {
  const top = [...forecasts]
    .filter((f) => f.kind === "outcome")
    .sort((a, b) => Math.abs(b.edge) - Math.abs(a.edge))
    .slice(0, 3);
  // The forecasting layer lives in the Rust core; the browser demo has none.
  const noForecaster = liveMode() === "none";

  return (
    <Card title="What it thinks" subtitle="Its strongest opinions on prediction markets, next to what everyone else thinks.">
      {noForecaster ? (
        <EmptyState icon={Target} title="Predictions need the desktop app" compact>
          Forecasts are made by the engine in the desktop app or on a connected server. This browser version only
          practises trading.
        </EmptyState>
      ) : (
        <>
          {untrusted && (
            <div className="mb-3 rounded-lg border border-warning/30 bg-warning/[0.06] px-3 py-2 text-sm leading-relaxed text-cyber-text-dim">
              <b className="text-warning">It is still learning.</b> Every prediction it makes is written down and
              checked against what actually happened. Until its guesses beat the market's own price, it does not act on
              them, so right now it mostly agrees with the market on purpose.
            </div>
          )}
          {top.length === 0 ? (
            <EmptyState icon={Target} title="No prediction markets yet" compact>
              They usually arrive within a few seconds of starting.
            </EmptyState>
          ) : (
            <div className="space-y-2">
              {top.map((f) => {
                const mine = Math.round(f.ensembleP * 100);
                const mkt = Math.round(f.marketP * 100);
                const diff = mine - mkt;
                return (
                  <div key={f.marketId} className="rounded-lg border border-cyber-border bg-cyber-bg/40 px-3 py-2.5">
                    <div className="mb-1 text-sm font-medium text-cyber-text">{f.symbol}</div>
                    <div className="text-sm text-cyber-text-dim">
                      Everyone else says <b className="font-mono text-cyber-text">{mkt}%</b> likely. Pythia says{" "}
                      <b className="font-mono text-accent">{mine}%</b>.{" "}
                      {Math.abs(diff) < 1 ? (
                        <span className="text-cyber-text-faint">It agrees.</span>
                      ) : (
                        <span className="text-cyber-text-faint">
                          It thinks that is {Math.abs(diff)} point{Math.abs(diff) === 1 ? "" : "s"} too{" "}
                          {diff > 0 ? "low" : "high"}.
                        </span>
                      )}
                    </div>
                    {f.action === "hold" && (
                      <div className="mt-1 text-xs text-cyber-text-faint">Not acting on it: {plainReason(f.reason)}</div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </>
      )}
    </Card>
  );
}

/** Translate the engine's reason string out of trading vocabulary. */
function plainReason(reason: string): string {
  if (reason.includes("track record")) {
    return "it has not proven itself yet.";
  }
  if (reason.includes("round-trip cost")) {
    return "the fees would eat the whole difference.";
  }
  if (reason.includes("below the")) {
    return "the difference is too small to be worth the fees.";
  }
  if (reason.includes("no forecaster")) {
    return "nothing has an opinion on this one.";
  }
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
        className="flex w-full items-center gap-2 rounded-md text-left text-sm font-medium text-accent"
      >
        <HelpCircle size={15} aria-hidden />
        What is this app actually doing?
        <ChevronDown size={14} aria-hidden className={`ml-auto transition-transform ${open ? "rotate-180" : ""}`} />
      </button>

      {open && (
        <div id="home-explainer" className="mt-3 space-y-3 text-sm leading-relaxed text-cyber-text-dim">
          <p>
            Pythia watches a set of markets (some prediction markets, &ldquo;will this happen?&rdquo;, some crypto,
            some shares) and forms an opinion about where each is going. When it thinks the market is wrong by enough to
            be worth the fees, it can place a trade.
          </p>
          <p>
            <b className="text-cyber-text">It starts in practice mode.</b> The balance is fake, the trades are
            simulated, and nothing can be lost. Turning on real trading takes several deliberate steps and a typed
            confirmation. It cannot happen by accident.
          </p>
          <p>
            <b className="text-cyber-text">It has to earn your trust, literally.</b> Every prediction is written down
            and later checked against what really happened. Until a source of predictions beats the market's own price
            over a real track record, Pythia refuses to act on it. That is why a fresh install mostly agrees with the
            market and trades very little.
          </p>
          <p>
            <b className="text-cyber-text">Nobody can promise you profit.</b> Not this app, not anyone. Most automated
            trading loses money to fees. Only ever use money you can afford to lose entirely.
          </p>
          <p className="text-cyber-text-faint">
            Want the full instrument panel with charts, strategies, backtests and risk limits?{" "}
            <button
              type="button"
              onClick={() => setUiMode("advanced")}
              className="font-medium text-accent underline underline-offset-2 hover:text-glow-cyan"
            >
              Switch on advanced view
            </button>
            . You can switch back any time at the bottom of the menu or in Settings.
          </p>
        </div>
      )}
    </Card>
  );
}
