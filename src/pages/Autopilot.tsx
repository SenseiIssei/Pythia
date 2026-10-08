import { useEffect, useId, useMemo, useRef, useState, type ReactNode } from "react";
import {
  Activity,
  ArrowLeftRight,
  BarChart3,
  CalendarClock,
  CheckCircle2,
  Circle,
  Clock,
  Flag,
  History,
  Lock,
  Pause,
  Plane,
  Play,
  Receipt,
  ShieldCheck,
  Square,
  TrendingDown,
  TrendingUp,
  TriangleAlert,
  Wallet,
  XCircle,
  type LucideIcon,
} from "lucide-react";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  Explain,
  Field,
  Loading,
  Meter,
  Notice,
  PageHeader,
  Readout,
  StatCard,
  Term,
  fmtUsd,
  inputCls,
  pnlTone,
  type Tone,
} from "../components/ui";
import { PnlLines } from "../components/PnlBreakdown";
import { explain } from "../glossary";
import { useStore } from "../store";
import { useAdvanced } from "../uiMode";
import { autopilotVenue, demoIsApiTestOnly, exchangeName } from "../venueNames";
import { useMockAutopilot, type MockScenario } from "../autopilotMock";
import {
  LIVE_PHRASE,
  MEANINGFUL_DAYS,
  MEANINGFUL_TRADES,
  analyse,
  bitcoinMarket,
  compareWithHold,
  curve,
  floorAtStart,
  fmtDays,
  fmtDuration,
  fmtWhen,
  isActive,
  limit,
  type Stop,
} from "../autopilot";
import type { AutopilotConfig, AutopilotStart, AutopilotStatus, Venue } from "../types";

// ── where the numbers come from ─────────────────────────────────────────────

interface AutopilotApi {
  loading: boolean;
  /** Set only in a dev build opened with `?mockAutopilot`: the page shows sample data. */
  mocked: MockScenario | null;
  autopilots: AutopilotStatus[];
  start: (config: AutopilotStart) => Promise<void>;
  stop: (id: string, flatten: boolean) => Promise<void>;
  pause: (id: string) => Promise<void>;
  resume: (id: string) => Promise<void>;
  /** Bitcoin bar times and closes, for the "just holding" comparison. */
  btc: { symbol: string; times?: number[]; closes?: number[] } | null;
}

function useAutopilotApi(): AutopilotApi {
  const store = useStore();
  const names = useMemo(
    () => Object.fromEntries(store.strategies.map((s) => [s.id, s.name])),
    [store.strategies],
  );
  // `import.meta.env.DEV` is a build-time constant. In a production build this
  // line becomes `null` and the sample module is left out of the bundle.
  const mock = import.meta.env.DEV ? useMockAutopilot(names) : null;
  const btc = bitcoinMarket(store.markets, store.historyTimes);

  if (mock) {
    return {
      loading: mock.loading,
      mocked: mock.scenario,
      autopilots: mock.autopilots,
      start: mock.start,
      stop: mock.stop,
      pause: mock.pause,
      resume: mock.resume,
      btc: { symbol: "BTC/USD", times: mock.btc.times, closes: mock.btc.closes },
    };
  }
  return {
    loading: store.portfolio.equity <= 0 && store.markets.length === 0,
    mocked: null,
    autopilots: store.autopilots,
    // The page checks the typed phrase; the engine only takes a flag, and
    // refuses live without it.
    start: ({ confirm, ...config }: AutopilotStart) => store.startAutopilot(config, confirm === LIVE_PHRASE),
    stop: store.stopAutopilot,
    pause: store.pauseAutopilot,
    resume: store.resumeAutopilot,
    btc: btc ? { symbol: btc.symbol, times: store.historyTimes[btc.id], closes: store.history[btc.id] } : null,
  };
}

// ── words ───────────────────────────────────────────────────────────────────

const VENUES: { id: Venue; label: string; note: string }[] = [
  { id: "crypto", label: "Crypto exchange", note: "Open day and night. Buys and sells coins, never borrows to bet against them." },
  { id: "alpaca", label: "US shares (Alpaca)", note: "Trades only while the US market is open." },
];

function venueLabel(v: string): string {
  return VENUES.find((x) => x.id === v)?.label ?? v;
}

type Mode = AutopilotConfig["mode"];

function modeBadge(mode: Mode, simple: boolean): { tone: Tone; text: string } {
  if (mode === "live") return { tone: "red", text: simple ? "REAL MONEY" : "LIVE" };
  if (mode === "demo") return { tone: "amber", text: "DEMO ACCOUNT" };
  return { tone: "green", text: simple ? "PRACTICE" : "PAPER" };
}

function signedUsd(n: number, dp = 2): string {
  return `${n > 0 ? "+" : ""}${fmtUsd(n, dp)}`;
}

function signedPct(n: number, dp = 1): string {
  return `${n > 0 ? "+" : ""}${n.toFixed(dp)}%`;
}

// ── the page ────────────────────────────────────────────────────────────────

/**
 * The autopilot: an amount it trades on its own until it is stopped, a limit
 * is hit, or an end date passes. Setup when nothing runs, the running view
 * while something does, then an honest analysis and the runs that came before.
 */
export function Autopilot() {
  const api = useAutopilotApi();
  const { limits } = useStore();
  const [selected, setSelected] = useState<string | null>(null);
  const analysisRef = useRef<HTMLDivElement>(null);

  const active = api.autopilots.filter(isActive).sort((a, b) => b.startedMs - a.startedMs);
  const past = api.autopilots
    .filter((a) => !isActive(a))
    .sort((a, b) => (b.stoppedMs ?? b.startedMs) - (a.stoppedMs ?? a.startedMs));
  const shown = api.autopilots.find((a) => a.config.id === selected) ?? active[0] ?? past[0];

  function analyseRun(id: string) {
    setSelected(id);
    requestAnimationFrame(() => analysisRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }));
  }

  return (
    <div className="animate-fade-in mx-auto max-w-4xl space-y-4">
      <PageHeader
        title="Autopilot"
        subtitle="Give it an amount and it trades that amount on its own: until you stop it, until a limit you set is reached, or for ever."
      />

      {api.mocked && (
        <Notice tone="warning" title="Sample data for development">
          This page is showing a made-up autopilot ({api.mocked}) because the address has <code>?mockAutopilot</code>.
          Nothing here is real. Only development builds can show it.
        </Notice>
      )}

      {limits.killSwitch && active.length > 0 && (
        <Notice tone="danger" title="The kill switch is on">
          The autopilot cannot open anything new until you switch it off. It can still sell what it holds.
        </Notice>
      )}

      {api.loading ? (
        <Card>
          <Loading>Waiting for the engine to report its autopilots</Loading>
        </Card>
      ) : (
        <>
          {active.length === 0 ? (
            <Setup onStart={api.start} />
          ) : (
            active.map((s) => (
              <Running key={s.config.id} s={s} api={api} onAnalyse={() => analyseRun(s.config.id)} />
            ))
          )}

          <div ref={analysisRef} className="scroll-mt-4">
            {shown && <AnalysisCard s={shown} btc={api.btc} />}
          </div>

          <PastList past={past} shownId={shown?.config.id} onAnalyse={analyseRun} />
        </>
      )}
    </div>
  );
}

// ── 1 · setup ───────────────────────────────────────────────────────────────

function Step({ n, title, help, children }: { n: number; title: string; help?: string; children: ReactNode }) {
  const tip = help ?? explain(title);
  return (
    <fieldset className="min-w-0 border-t border-cyber-border pt-4 first:border-t-0 first:pt-0">
      <legend className="mb-2 flex items-center gap-2 text-sm font-semibold text-cyber-text">
        <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full border border-accent/40 font-mono text-[11px] text-accent">
          {n}
        </span>
        {title}
        {tip && <Explain text={tip} label={title} />}
      </legend>
      {children}
    </fieldset>
  );
}

/** A big radio choice: a title and a plain sentence under it. */
function Choice({
  name,
  checked,
  onChange,
  title,
  detail,
  icon: Icon,
  danger,
  badge,
}: {
  name: string;
  checked: boolean;
  onChange: () => void;
  title: string;
  detail: ReactNode;
  icon?: LucideIcon;
  danger?: boolean;
  badge?: ReactNode;
}) {
  const on = danger
    ? "border-danger/60 bg-danger/10"
    : "border-accent/50 bg-accent/[0.07]";
  return (
    <label
      className={`flex min-w-0 cursor-pointer items-start gap-2.5 rounded-lg border px-3 py-2.5 transition-colors ${
        checked ? on : "border-cyber-border bg-cyber-bg/40 hover:border-cyber-border-bright"
      }`}
    >
      <input type="radio" name={name} checked={checked} onChange={onChange} aria-label={title} className="mt-1 shrink-0 accent-cyan-400" />
      <span className="min-w-0">
        <span className={`flex flex-wrap items-center gap-1.5 text-sm font-medium ${danger ? "text-danger" : "text-cyber-text"}`}>
          {Icon && <Icon size={14} aria-hidden className="shrink-0" />}
          {title}
          {badge}
        </span>
        <span className="mt-0.5 block text-xs leading-relaxed text-cyber-text-dim">{detail}</span>
      </span>
    </label>
  );
}

/** A checkbox that switches one optional limit on, with its input beside it. */
function LimitRow({
  on,
  onToggle,
  label,
  help,
  children,
}: {
  on: boolean;
  onToggle: (v: boolean) => void;
  label: string;
  help?: string;
  children?: ReactNode;
}) {
  const tip = help ?? explain(label);
  return (
    <div className={`rounded-lg border px-3 py-2.5 ${on ? "border-accent/40 bg-accent/[0.04]" : "border-cyber-border bg-cyber-bg/40"}`}>
      <label className="flex cursor-pointer items-center gap-2 text-sm text-cyber-text">
        <input type="checkbox" checked={on} onChange={(e) => onToggle(e.target.checked)} aria-label={label} className="shrink-0 accent-cyan-400" />
        <span className="min-w-0">{label}</span>
        {tip && <Explain text={tip} label={label} />}
      </label>
      {on && children && <div className="mt-2 flex flex-wrap items-center gap-2 pl-6 text-sm text-cyber-text-dim">{children}</div>}
    </div>
  );
}

/** The shared input look without its full width, for inputs that sit inside a sentence. */
const inlineCls = inputCls.replace("w-full ", "");

function num(s: string): number {
  const n = Number(s.replace(/[$,\s%]/g, ""));
  return Number.isFinite(n) ? n : NaN;
}

function SmallInput({
  value,
  onChange,
  label,
  suffix,
  prefix,
  width = "w-24",
}: {
  value: string;
  onChange: (v: string) => void;
  label: string;
  suffix?: string;
  prefix?: string;
  width?: string;
}) {
  return (
    <span className="inline-flex items-center gap-1">
      {prefix && <span className="text-cyber-text-faint">{prefix}</span>}
      <input
        inputMode="decimal"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        aria-label={label}
        className={`${inlineCls} ${width} font-mono`}
      />
      {suffix && <span className="text-cyber-text-faint">{suffix}</span>}
    </span>
  );
}

/** `datetime-local` wants local time without a zone. */
function localInput(ms: number): string {
  const d = new Date(ms - new Date(ms).getTimezoneOffset() * 60_000);
  return d.toISOString().slice(0, 16);
}

function Setup({ onStart }: { onStart: (c: AutopilotStart) => Promise<void> }) {
  const { strategies, passports, live, portfolio, cryptoCostVenue } = useStore();
  const advanced = useAdvanced();
  const simple = !advanced;

  const [mode, setMode] = useState<Mode>("paper");
  const [venue, setVenue] = useState<Venue>("crypto");
  const [amount, setAmount] = useState("1000");
  const [pick, setPick] = useState<"auto" | "manual">("auto");
  const [weights, setWeights] = useState<Record<string, string>>({});
  const [lossPctOn, setLossPctOn] = useState(false);
  const [lossPct, setLossPct] = useState("10");
  const [lossUsdOn, setLossUsdOn] = useState(false);
  const [lossUsd, setLossUsd] = useState("100");
  const [tpOn, setTpOn] = useState(false);
  const [tp, setTp] = useState("20");
  const [onTp, setOnTp] = useState<"stop" | "lock">("stop");
  const [trailOn, setTrailOn] = useState(false);
  const [trail, setTrail] = useState("10");
  const [endOn, setEndOn] = useState(false);
  const [end, setEnd] = useState(() => localInput(Date.now() + 30 * 86_400_000));
  const [flatten, setFlatten] = useState(true);
  const [name, setName] = useState("");
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const capital = num(amount);
  // The exchange it would trade on, by its own name ("Bybit", not "crypto").
  const target = autopilotVenue(mode, venue, live, cryptoCostVenue);
  const targetName = exchangeName(target);
  const eligible =strategies.filter((s) => s.id !== "manual" && s.venueClass === venue);
  const chosen = eligible
    .map((s) => ({ s, w: num(weights[s.id] ?? "") }))
    .filter((x) => x.w > 0);
  const weightSum = chosen.reduce((a, x) => a + x.w, 0);

  const stop: Stop = { onTakeProfit: onTp };
  if (lossPctOn) stop.maxLossPct = num(lossPct);
  if (lossUsdOn) stop.maxLossUsd = num(lossUsd);
  if (tpOn) stop.takeProfitPct = num(tp);
  if (trailOn) stop.trailingPct = num(trail);
  const endMs = endOn ? new Date(end).getTime() : undefined;
  if (endOn && endMs !== undefined && Number.isFinite(endMs)) stop.endMs = endMs;
  const plan = floorAtStart(capital > 0 ? capital : 0, stop);
  const anyLimit = lossPctOn || lossUsdOn || tpOn || trailOn || endOn;

  // What is wrong with the form, in plain sentences.
  const problems: string[] = [];
  if (!(capital > 0)) problems.push("Enter how much it may use, more than zero.");
  if (pick === "manual" && chosen.length === 0) problems.push("Pick at least one strategy and give it a share above zero.");
  if (lossPctOn && !(limit(stop.maxLossPct) && stop.maxLossPct! < 100)) problems.push("The loss limit in percent has to be between 0 and 100.");
  if (lossUsdOn && !(limit(stop.maxLossUsd) && capital > 0 && stop.maxLossUsd! < capital)) problems.push("The loss limit in dollars has to be above zero and below the amount.");
  if (tpOn && !limit(stop.takeProfitPct)) problems.push("The take-profit has to be above zero.");
  if (trailOn && !(limit(stop.trailingPct) && stop.trailingPct! < 100)) problems.push("The trailing limit has to be between 0 and 100 percent.");
  if (endOn && !(endMs && endMs > Date.now())) problems.push("The end date has to be in the future.");
  // The engine refuses this too; saying it here saves a round trip.
  if (mode === "demo" && venue === "crypto" && demoIsApiTestOnly(live)) {
    problems.push(
      `${exchangeName(live.demoExchange)} runs its demo account on its own prices, so a demo autopilot there would be judged in a different price world than its stop rules watch. Use Bybit or Binance demo keys, or practice money.`,
    );
  }

  // Real money: every requirement spelled out, checked here and again by the engine.
  const liveCash = portfolio.balances.find((b) => b.venue === venue && b.mode === "live")?.cash;
  const armedHere = live.armed && !live.paper && !live.dryRun && live.venues.includes(venue);
  const ready = (id: string) => passports.get(id)?.liveReady ?? false;
  const readyCount = eligible.filter((s) => ready(s.id)).length;
  const checksOk = pick === "manual" ? chosen.length > 0 && chosen.every((x) => ready(x.s.id)) : readyCount > 0;
  const requirements: { ok: boolean | null; text: ReactNode }[] = [
    {
      ok: armedHere,
      text: armedHere
        ? `Real-money trading is armed for ${targetName}.`
        : `Real-money trading has to be armed for ${targetName} on the Live page (advanced view), on the real endpoint, not dry-run.`,
    },
    {
      ok: checksOk,
      text:
        pick === "manual"
          ? checksOk
            ? "Every strategy you picked has passed its checks."
            : "Every strategy you pick has to have passed its checks (the Strategy Passport)."
          : readyCount > 0
            ? `Pythia only chooses among strategies that passed their checks: ${readyCount} of ${eligible.length} here have.`
            : `None of the ${eligible.length} strategies for ${venueLabel(venue)} has passed its checks yet, so there is nothing Pythia may choose.`,
    },
    {
      ok: liveCash === undefined ? null : capital > 0 && capital <= liveCash,
      text:
        liveCash === undefined
          ? "The amount may not be more than the cash in the account. Pythia checks that with the exchange when it starts."
          : capital <= liveCash
            ? `The amount is within the account's cash (${fmtUsd(liveCash, 0)}).`
            : `The amount is more than the account's cash (${fmtUsd(liveCash, 0)}).`,
    },
  ];
  const liveBlocked = mode === "live" && (requirements.some((r) => r.ok === false) || typed.trim().toUpperCase() !== LIVE_PHRASE);
  const canStart = problems.length === 0 && !liveBlocked && !busy;

  async function start() {
    if (!canStart) return;
    setBusy(true);
    setErr("");
    const now = Date.now();
    const config: AutopilotStart = {
      id: `ap-${now.toString(36)}`,
      name: name.trim() || `Autopilot ${new Date(now).toLocaleDateString("en-GB", { day: "numeric", month: "short" })}`,
      mode,
      // The engine wants the exchange, not the asset class: crypto demo runs
      // on the demo exchange, other crypto on the one selected in Settings,
      // US shares on Alpaca.
      venue: target,
      capitalUsd: capital,
      sleeves: pick === "manual" ? chosen.map((x) => ({ strategyId: x.s.id, weight: x.w / weightSum })) : [],
      stop,
      flattenOnStop: flatten,
      ...(mode === "live" ? { confirm: typed.trim().toUpperCase() } : {}),
    };
    try {
      await onStart(config);
      setTyped("");
    } catch (e) {
      // The engine is the authority: when it refuses, say why in its words.
      setErr(e instanceof Error ? e.message : String(e));
    }
    setBusy(false);
  }

  const source =
    mode === "paper"
      ? "Virtual money. Pythia sets this much practice money aside for the autopilot. Nothing real is involved and nothing can be lost."
      : mode === "demo"
        ? `Comes from ${targetName}'s demo account: a practice balance kept by ${targetName} itself. Orders really go there, but no real money moves.`
        : `Comes from the ${targetName} account you funded yourself. The autopilot buys and sells inside that account and can lose this money.`;

  return (
    <Card
      title="Start an autopilot"
      icon={Plane}
      subtitle="Four short questions. You can stop it at any moment, whatever you choose here."
      help={explain("Autopilot")}
    >
      <div className="space-y-5">
        {/* 1 · which money */}
        <Step n={1} title="Which money" help="Practice money, a demo account at the venue, or real money in an account you funded.">
          <div role="radiogroup" aria-label="Which money" className="grid grid-cols-1 gap-2 sm:grid-cols-3">
            <Choice
              name="ap-mode"
              checked={mode === "paper"}
              onChange={() => setMode("paper")}
              icon={ShieldCheck}
              title={simple ? "Practice money" : "Paper"}
              detail="Virtual money on real prices. Nothing can be lost."
            />
            <Choice
              name="ap-mode"
              checked={mode === "demo"}
              onChange={() => setMode("demo")}
              icon={Wallet}
              title="Demo account"
              detail="The venue's own practice account. Real orders, fake balance."
            />
            <Choice
              name="ap-mode"
              checked={mode === "live"}
              onChange={() => setMode("live")}
              icon={Lock}
              title="Real money"
              danger
              detail="An account you funded. Can lose real money. Needs more steps."
            />
          </div>
          <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2" role="radiogroup" aria-label="Where it trades">
            {VENUES.map((v) => (
              <Choice
                key={v.id}
                name="ap-venue"
                checked={venue === v.id}
                onChange={() => setVenue(v.id)}
                title={
                  v.id === "crypto"
                    ? `${v.label} · ${exchangeName(autopilotVenue(mode, "crypto", live, cryptoCostVenue))}${mode === "demo" ? " demo" : ""}`
                    : v.label
                }
                detail={v.note}
              />
            ))}
          </div>
        </Step>

        {/* 2 · how much */}
        <Step n={2} title="How much" help={explain("Start amount")}>
          <div className="flex flex-wrap items-center gap-2">
            <SmallInput value={amount} onChange={setAmount} label="Amount in US dollars" prefix="$" width="w-36" />
            {capital > 0 && <span className="font-mono text-sm text-cyber-text-dim">{fmtUsd(capital, 0)}</span>}
          </div>
          <p className="mt-2 text-xs leading-relaxed text-cyber-text-dim">{source}</p>
          <p className="mt-2 flex items-start gap-1.5 text-xs leading-relaxed text-cyber-text-faint">
            <ShieldCheck size={13} aria-hidden className="mt-0.5 shrink-0 text-success" />
            <span>
              Pythia never moves money out of a wallet and never withdraws from any account. Your Exodus wallet is only
              watched by its public address: nothing can be sent from it. The autopilot only buys and sells inside the
              account the money is already in.
            </span>
          </p>
        </Step>

        {/* 3 · strategies */}
        <Step n={3} title="Which strategies" help="The rule sets that decide when to buy and sell. Pythia can choose them, or you can.">
          <div role="radiogroup" aria-label="Which strategies" className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            <Choice
              name="ap-pick"
              checked={pick === "auto"}
              onChange={() => setPick("auto")}
              title="Let Pythia choose"
              badge={<Badge tone="cyan">recommended</Badge>}
              detail="It picks the strategies with the best record after costs that suit the market right now, and tells you why."
            />
            <Choice
              name="ap-pick"
              checked={pick === "manual"}
              onChange={() => setPick("manual")}
              title="I pick them"
              detail="Choose strategies yourself and how much of the amount each may use."
            />
          </div>
          {pick === "manual" && (
            <div className="mt-3 space-y-1.5">
              {eligible.length === 0 ? (
                <EmptyState icon={Activity} title={`No strategies for ${venueLabel(venue)} yet`} compact>
                  They arrive with the first update from the engine.
                </EmptyState>
              ) : (
                eligible.map((s) => {
                  const w = num(weights[s.id] ?? "");
                  const share = w > 0 && weightSum > 0 ? (w / weightSum) * 100 : 0;
                  return (
                    <div
                      key={s.id}
                      className="flex flex-wrap items-center gap-x-3 gap-y-1.5 rounded-lg border border-cyber-border bg-cyber-bg/40 px-3 py-2"
                    >
                      <label className="flex min-w-0 flex-1 basis-48 cursor-pointer items-center gap-2 text-sm">
                        <input
                          type="checkbox"
                          checked={w > 0}
                          onChange={(e) => setWeights((p) => ({ ...p, [s.id]: e.target.checked ? "1" : "" }))}
                          aria-label={`Use ${s.name}`}
                          className="shrink-0 accent-cyan-400"
                        />
                        <span className="min-w-0 truncate text-cyber-text">{s.name}</span>
                      </label>
                      {mode === "live" && (
                        <Badge tone={ready(s.id) ? "green" : "neutral"} title="Strategy Passport">
                          {ready(s.id) ? "checks passed" : "checks not passed"}
                        </Badge>
                      )}
                      <span className="flex items-center gap-2 text-xs text-cyber-text-dim">
                        <Term k="Strategy share">weight</Term>
                        <SmallInput
                          value={weights[s.id] ?? ""}
                          onChange={(v) => setWeights((p) => ({ ...p, [s.id]: v }))}
                          label={`Weight for ${s.name}`}
                          width="w-16"
                        />
                        <span className="w-12 text-right font-mono">{share > 0 ? `${share.toFixed(0)}%` : "off"}</span>
                      </span>
                    </div>
                  );
                })
              )}
              {chosen.length > 0 && (
                <p className="text-[11px] text-cyber-text-faint">
                  Weights are relative: 2 and 1 means two thirds and one third of {capital > 0 ? fmtUsd(capital, 0) : "the amount"}.
                </p>
              )}
            </div>
          )}
        </Step>

        {/* 4 · when to stop */}
        <Step n={4} title="When to stop" help="It runs until you stop it. Each limit below is optional and ends the run on its own.">
          <div className="space-y-2">
            <div className="flex items-center gap-2 rounded-lg border border-cyber-border bg-cyber-bg/40 px-3 py-2.5 text-sm text-cyber-text">
              {anyLimit ? (
                <Circle size={14} aria-hidden className="text-cyber-text-faint" />
              ) : (
                <CheckCircle2 size={14} aria-hidden className="text-accent" />
              )}
              Run until I stop it
              <span className="text-xs text-cyber-text-faint">{anyLimit ? "or until a limit below" : "(no limits set)"}</span>
            </div>
            <LimitRow on={lossPctOn} onToggle={setLossPctOn} label="Stop after losing a percentage" help={explain("Floor")}>
              stop after losing <SmallInput value={lossPct} onChange={setLossPct} label="Loss limit in percent" suffix="%" width="w-16" />
              {capital > 0 && limit(num(lossPct)) && (
                <span className="text-xs text-cyber-text-faint">= {fmtUsd((capital * num(lossPct)) / 100, 0)}</span>
              )}
            </LimitRow>
            <LimitRow on={lossUsdOn} onToggle={setLossUsdOn} label="Stop after losing an amount" help={explain("Floor")}>
              stop after losing <SmallInput value={lossUsd} onChange={setLossUsd} label="Loss limit in dollars" prefix="$" width="w-24" />
            </LimitRow>
            <LimitRow on={tpOn} onToggle={setTpOn} label="Take profit">
              <span className="flex flex-wrap items-center gap-2">
                when it is up <SmallInput value={tp} onChange={setTp} label="Take profit in percent" suffix="%" width="w-16" />
                <select
                  value={onTp}
                  onChange={(e) => setOnTp(e.target.value as "stop" | "lock")}
                  aria-label="What happens at the take-profit"
                  className={`${inlineCls} w-auto max-w-full`}
                >
                  <option value="stop">then stop</option>
                  <option value="lock">then lock it in and keep going</option>
                </select>
                {onTp === "lock" && <Explain text={explain("Lock it in")!} label="Lock it in" />}
              </span>
            </LimitRow>
            <LimitRow on={trailOn} onToggle={setTrailOn} label="Never give back more than" help={explain("Trailing limit")}>
              <SmallInput value={trail} onChange={setTrail} label="Trailing limit in percent" suffix="%" width="w-16" />
              from its best point
            </LimitRow>
            <LimitRow on={endOn} onToggle={setEndOn} label="End on a date" help="It stops on its own at this moment, whatever it is doing.">
              <input
                type="datetime-local"
                value={end}
                min={localInput(Date.now())}
                onChange={(e) => setEnd(e.target.value)}
                aria-label="End date and time"
                className={`${inlineCls} w-auto max-w-full`}
              />
            </LimitRow>
          </div>

          <FloorSummary capital={capital} plan={plan} stop={stop} trailOn={trailOn} endOn={endOn} />

          <label className="mt-3 flex cursor-pointer items-start gap-2 text-sm text-cyber-text">
            <input
              type="checkbox"
              checked={flatten}
              onChange={(e) => setFlatten(e.target.checked)}
              aria-label="When it stops on its own, sell everything it bought"
              className="mt-1 shrink-0 accent-cyan-400"
            />
            <span>
              When it stops on its own, sell everything it bought
              <span className="block text-xs text-cyber-text-faint">
                {flatten
                  ? "It ends in cash. You can still choose differently when you stop it yourself."
                  : "What it bought stays in the account, and from then on you look after it yourself."}
              </span>
            </span>
          </label>

          {advanced && (
            <Field label="Name (optional)" className="mt-3 max-w-xs" help="Only for you, to tell runs apart in the list of past autopilots.">
              <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Autopilot" className={inputCls} />
            </Field>
          )}
        </Step>

        {mode === "live" && (
          <div className="rounded-xl border border-danger/50 bg-danger/[0.07] p-4">
            <div className="flex items-start gap-2 text-sm font-semibold text-danger">
              <TriangleAlert size={16} aria-hidden className="mt-0.5 shrink-0" />
              Real money: this autopilot can lose the whole amount, also while you sleep.
            </div>
            <ul className="mt-3 space-y-1.5">
              {requirements.map((r, i) => (
                <li key={i} className="flex items-start gap-2 text-sm text-cyber-text-dim">
                  {r.ok === true ? (
                    <CheckCircle2 size={15} aria-hidden className="mt-0.5 shrink-0 text-success" />
                  ) : r.ok === false ? (
                    <XCircle size={15} aria-hidden className="mt-0.5 shrink-0 text-danger" />
                  ) : (
                    <Circle size={15} aria-hidden className="mt-0.5 shrink-0 text-cyber-text-faint" />
                  )}
                  <span>{r.text}</span>
                </li>
              ))}
            </ul>
            <label className="mt-3 block text-xs text-cyber-text-dim">
              Type <b className="font-mono text-danger">{LIVE_PHRASE}</b> to confirm
              <input
                value={typed}
                onChange={(e) => setTyped(e.target.value)}
                placeholder={LIVE_PHRASE}
                autoComplete="off"
                aria-label={`Type ${LIVE_PHRASE} to confirm`}
                className={`${inputCls} mt-1 max-w-xs focus:border-danger`}
              />
            </label>
          </div>
        )}

        {problems.length > 0 && (
          <ul className="space-y-1">
            {problems.map((p) => (
              <li key={p} className="flex items-start gap-1.5 text-xs text-warning">
                <TriangleAlert size={13} aria-hidden className="mt-0.5 shrink-0" />
                {p}
              </li>
            ))}
          </ul>
        )}
        {err && (
          <Notice tone="danger" title="It did not start">
            {err}
          </Notice>
        )}

        <div className="flex flex-wrap items-center gap-3 border-t border-cyber-border pt-4">
          <Button tone={mode === "live" ? "red" : "cyan"} icon={Play} onClick={() => void start()} disabled={!canStart}>
            {busy ? "Starting" : mode === "live" ? "Start with real money" : mode === "demo" ? "Start on the demo account" : "Start the autopilot"}
          </Button>
          <span className="text-xs text-cyber-text-faint">
            {mode === "paper" ? "Practice money: nothing can be lost." : "You can pause or stop it at any moment."}
          </span>
        </div>
      </div>
    </Card>
  );
}

/** "It stops at $8,500 at the latest", and what the other limits do, before anything starts. */
function FloorSummary({
  capital,
  plan,
  stop,
  trailOn,
  endOn,
}: {
  capital: number;
  plan: ReturnType<typeof floorAtStart>;
  stop: Stop;
  trailOn: boolean;
  endOn: boolean;
}) {
  if (!(capital > 0)) return null;
  const lines: ReactNode[] = [];
  if (plan.takeProfitAt !== null) {
    lines.push(
      <>
        At <b className="font-mono text-success">{fmtUsd(plan.takeProfitAt, 0)}</b> it takes the profit and{" "}
        {stop.onTakeProfit === "stop" ? "stops." : "keeps going, with the gain locked in."}
      </>,
    );
  }
  if (trailOn && limit(stop.trailingPct)) {
    lines.push(<>As it gains, the floor rises with it: it never gives back more than {stop.trailingPct}% from its best point.</>);
  }
  if (endOn && stop.endMs) {
    lines.push(<>It stops on {new Date(stop.endMs).toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" })} at the latest.</>);
  }
  return (
    <div className="mt-3 rounded-lg border border-accent/30 bg-accent/[0.05] px-3 py-3">
      {plan.floor !== null ? (
        <>
          <div className="flex flex-wrap items-center gap-1.5 text-base font-semibold text-cyber-text">
            It stops at <span className="font-mono text-warning">{fmtUsd(plan.floor, 0)}</span> at the latest
            <Explain text={explain("Floor")!} label="Floor" />
          </div>
          <div className="mt-0.5 text-xs text-cyber-text-dim">
            That is a loss of at most {fmtUsd(capital - plan.floor, 0)} ({(((capital - plan.floor) / capital) * 100).toFixed(1)}%) of the{" "}
            {fmtUsd(capital, 0)}. A sudden price jump can carry it a little past the floor before the sale goes through.
          </div>
        </>
      ) : (
        <>
          <div className="text-base font-semibold text-cyber-text">No floor: it runs until you stop it</div>
          <div className="mt-0.5 text-xs text-cyber-text-dim">
            The general risk limits (the daily loss limit and the drawdown breaker) still apply to everything it does.
          </div>
        </>
      )}
      {lines.length > 0 && (
        <ul className="mt-2 space-y-0.5 text-xs text-cyber-text-dim">
          {lines.map((l, i) => (
            <li key={i}>{l}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

// ── 2 · running ─────────────────────────────────────────────────────────────

function Running({ s, api, onAnalyse }: { s: AutopilotStatus; api: AutopilotApi; onAnalyse: () => void }) {
  const { journal } = useStore();
  const advanced = useAdvanced();
  const simple = !advanced;
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const now = Date.now();
  const id = s.config.id;
  const running = s.state === "running";
  const live = s.config.mode === "live";
  const badge = modeBadge(s.config.mode, simple);
  const plan = floorAtStart(s.startCapital, s.config.stop);
  // No loss or trailing rule means no floor (the engine sends null).
  const floor = s.floorEquity ?? 0;
  const room = floor > 0 ? s.equity - floor : null;
  const span = floor > 0 ? Math.max(1e-9, s.peakEquity - floor) : 0;
  const roomPct = room !== null ? (room / span) * 100 : 0;

  async function act(fn: () => Promise<void>) {
    setBusy(true);
    setErr("");
    try {
      await fn();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
    setBusy(false);
  }

  const sleeveIds = new Set(s.bySleeve.map((b) => b.strategyId));
  const recent = journal
    .filter((j) => j.ts >= s.startedMs && j.strategyId && sleeveIds.has(j.strategyId) && (j.kind === "fill" || j.kind === "reject" || j.kind === "risk"))
    .slice(0, 5);

  const box = live
    ? "border-danger/50 bg-danger/[0.07]"
    : running
      ? "border-success/35 bg-success/[0.05]"
      : "border-warning/40 bg-warning/[0.06]";

  return (
    <section aria-label={`Autopilot ${s.config.name}`} className="space-y-4">
      {/* status */}
      <div className={`rounded-xl border p-4 sm:p-5 ${box} ${live && running ? "animate-pulse-red" : ""}`}>
        <div className="flex flex-wrap items-start gap-x-4 gap-y-3">
          <div className="flex min-w-0 flex-1 basis-64 items-start gap-3">
            {running ? (
              <Plane size={24} aria-hidden className={`mt-0.5 shrink-0 ${live ? "text-danger" : "text-success"}`} />
            ) : (
              <Pause size={24} aria-hidden className="mt-0.5 shrink-0 text-warning" />
            )}
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <span className={`text-xl font-semibold leading-tight ${running ? (live ? "text-danger" : "text-success") : "text-warning"}`}>
                  {running ? "Running" : "Paused"}
                </span>
                <Badge tone={badge.tone}>{badge.text}</Badge>
                <span className="text-sm text-cyber-text-dim">{s.config.name}</span>
              </div>
              <p className="mt-1 text-sm leading-relaxed text-cyber-text-dim">
                {running
                  ? `Trading ${fmtUsd(s.startCapital, 0)} on ${exchangeName(s.config.venue)}${s.config.mode === "demo" ? "'s demo account" : ""} on its own, for ${fmtDuration(now - s.startedMs)} now.`
                  : "Holding what it has and opening nothing new until you resume it."}
              </p>
              <p className="mt-0.5 text-xs text-cyber-text-faint">
                Started {fmtWhen(s.startedMs)}
                {s.config.stop.endMs ? ` · ends ${fmtWhen(s.config.stop.endMs)} at the latest` : " · runs until you stop it or a limit is reached"}
              </p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {running ? (
              <Button tone="neutral" icon={Pause} disabled={busy} onClick={() => void act(() => api.pause(id))}>
                Pause
              </Button>
            ) : (
              <Button tone="cyan" icon={Play} disabled={busy} onClick={() => void act(() => api.resume(id))}>
                Resume
              </Button>
            )}
            <StopButton live={live} preferFlatten={s.config.flattenOnStop} disabled={busy} onStop={(f) => void act(() => api.stop(id, f))} />
          </div>
        </div>
        {err && <div className="mt-3 text-sm text-danger">{err}</div>}
      </div>

      {/* money */}
      <Card>
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-1.5 text-sm text-cyber-text-dim">
              It is worth <Explain text={explain("Equity")!} label="worth" />
            </div>
            <div className="font-mono text-3xl font-bold tabular-nums text-cyber-text sm:text-4xl">{fmtUsd(s.equity, 2)}</div>
            <div className="mt-1 text-sm">
              <span className={s.pnl >= 0 ? "text-success" : "text-danger"}>
                {Math.abs(s.pnl) < 0.005 ? "No change" : `${s.pnl > 0 ? "Up" : "Down"} ${fmtUsd(Math.abs(s.pnl), 2)} (${signedPct(s.pnlPct, 2)})`}
              </span>{" "}
              <span className="text-cyber-text-faint">since it started with {fmtUsd(s.startCapital, 0)}</span>
            </div>
          </div>
          <div className="w-full min-w-0 text-sm sm:w-56 sm:text-right">
            {room !== null ? (
              <>
                <div className="flex items-center gap-1 text-cyber-text-dim sm:justify-end">
                  <Term k="Room to the floor">Room to the floor</Term>
                </div>
                <div className={`font-mono font-bold ${roomPct > 50 ? "text-success" : roomPct > 20 ? "text-warning" : "text-danger"}`}>
                  {fmtUsd(Math.max(0, room), 0)} <span className="text-xs font-normal text-cyber-text-faint">above {fmtUsd(floor, 0)}</span>
                </div>
                <div className="mt-1">
                  <Meter pct={roomPct} tone={roomPct > 50 ? "green" : roomPct > 20 ? "amber" : "red"} label="Room left before the floor" />
                </div>
              </>
            ) : (
              <div className="text-xs text-cyber-text-faint">No floor set: it stops when you stop it.</div>
            )}
          </div>
        </div>
        <div className="mt-4">
          <EquityChart
            points={curve(s, now)}
            start={s.startCapital}
            floor={floor > 0 ? floor : null}
            takeProfit={s.config.stop.onTakeProfit === "stop" ? plan.takeProfitAt : null}
            endLabel={running ? "now" : "paused"}
          />
        </div>
      </Card>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatCard label="P&L" icon={s.pnl >= 0 ? TrendingUp : TrendingDown} tone={pnlTone(s.pnl)} value={signedUsd(s.pnl)} sub={signedPct(s.pnlPct, 2)} />
        <StatCard
          label="From its best"
          icon={TrendingDown}
          tone={s.drawdownPct > 5 ? "amber" : "neutral"}
          value={`${Math.abs(s.drawdownPct).toFixed(1)}%`}
          sub={`best was ${fmtUsd(s.peakEquity, 0)}`}
        />
        <StatCard label="Trades" icon={ArrowLeftRight} value={String(s.trades)} help="How many buys and sells it made." />
        <StatCard label="Fees" icon={Receipt} value={fmtUsd(s.fees)} sub={s.pnl + s.fees > 0 ? `${((s.fees / (s.pnl + s.fees)) * 100).toFixed(0)}% of the gain before fees` : undefined} />
      </div>

      <Card title="What it is doing" icon={Activity} help="Its latest move, and why each strategy is in the mix.">
        <div className="rounded-lg border border-cyber-border bg-cyber-bg/40 px-3 py-2.5 text-sm">
          <div className="text-[11px] uppercase tracking-wider text-cyber-text-faint">Last action</div>
          <div className="mt-0.5 text-cyber-text">{s.lastAction ?? "Nothing yet. It is waiting for its first signal."}</div>
        </div>

        <div className="mt-3 space-y-2">
          {s.bySleeve.length === 0 ? (
            <EmptyState icon={Activity} title="Choosing its strategies" compact>
              The strategies it picks, and why, show up here within a minute of starting.
            </EmptyState>
          ) : (
            s.bySleeve.map((b) => (
              <div key={b.strategyId} className="rounded-lg border border-cyber-border bg-cyber-bg/40 px-3 py-2.5">
                <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
                  <span className="min-w-0 text-sm font-medium text-cyber-text">{b.name}</span>
                  <span className={`font-mono text-sm font-bold ${b.pnl > 0.005 ? "text-success" : b.pnl < -0.005 ? "text-danger" : "text-cyber-text"}`}>
                    {signedUsd(b.pnl)}
                  </span>
                </div>
                <div className="mt-0.5 flex flex-wrap gap-x-3 text-xs text-cyber-text-faint">
                  <span>
                    <Term k="Strategy share">{(b.weight * 100).toFixed(0)}% of the amount</Term>
                  </span>
                  <span>{b.trades} trade{b.trades === 1 ? "" : "s"}</span>
                </div>
                <div className="mt-1 text-xs leading-relaxed text-cyber-text-dim">{b.why}</div>
              </div>
            ))
          )}
        </div>

        {advanced && recent.length > 0 && (
          <div className="mt-3">
            <div className="mb-1 text-[11px] uppercase tracking-wider text-cyber-text-faint">Recent activity of its strategies</div>
            <ul className="space-y-1 text-xs text-cyber-text-dim">
              {recent.map((j) => (
                <li key={j.id} className="flex gap-2">
                  <span className="shrink-0 font-mono text-cyber-text-faint">{new Date(j.ts).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })}</span>
                  <span className="min-w-0 break-words">{j.message}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        <div className="mt-3">
          <Button tone="neutral" size="sm" icon={BarChart3} onClick={onAnalyse}>
            How is it doing?
          </Button>
        </div>
      </Card>
    </section>
  );
}

/**
 * Stop asks first, in place, like ConfirmButton: stop for good, and either
 * sell everything or keep what it bought. The choice made at the start is
 * offered first; "Keep it running" has the focus.
 */
function StopButton({
  onStop,
  preferFlatten,
  live,
  disabled,
}: {
  onStop: (flatten: boolean) => void;
  preferFlatten: boolean;
  live: boolean;
  disabled?: boolean;
}) {
  const [asking, setAsking] = useState(false);
  const keepRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!asking) return;
    keepRef.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setAsking(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [asking]);

  if (!asking) {
    return (
      <Button tone="red" icon={Square} disabled={disabled} onClick={() => setAsking(true)}>
        Stop
      </Button>
    );
  }
  const choice = "rounded border px-2 py-1 font-bold";
  const sell = (
    <button key="sell" type="button" onClick={() => { setAsking(false); onStop(true); }} className={`${choice} border-danger/50 bg-danger/15 text-danger hover:bg-danger/25`}>
      Stop and sell everything
    </button>
  );
  const keep = (
    <button key="keep" type="button" onClick={() => { setAsking(false); onStop(false); }} className={`${choice} border-warning/50 bg-warning/10 text-warning hover:bg-warning/20`}>
      Stop and keep the positions
    </button>
  );
  return (
    <span
      role="group"
      aria-label="Confirm stop"
      className="flex w-full max-w-md flex-wrap items-center gap-2 rounded-lg border border-danger/40 bg-danger/5 px-3 py-2 text-left text-xs text-cyber-text"
    >
      <span className="w-full">
        Stop the autopilot for good? It cannot be resumed afterwards. What should happen to what it bought?
        {live && " Kept positions stay at the exchange, and you look after them there."}
      </span>
      {preferFlatten ? [sell, keep] : [keep, sell]}
      <button
        type="button"
        ref={keepRef}
        onClick={() => setAsking(false)}
        className="rounded border border-cyber-border px-2 py-1 text-cyber-text-dim hover:text-cyber-text focus:outline focus:outline-1 focus:outline-accent"
      >
        Keep it running
      </button>
    </span>
  );
}

/** Equity over time, with the start and the floor as lines across. */
function EquityChart({
  points,
  start,
  floor,
  takeProfit,
  endLabel,
  height = 180,
}: {
  points: [number, number][];
  start: number;
  floor: number | null;
  takeProfit: number | null;
  endLabel: string;
  height?: number;
}) {
  const gid = useId().replace(/:/g, "");
  if (points.length < 2) {
    return (
      <div style={{ height }} className="flex items-center justify-center rounded-lg border border-dashed border-cyber-border text-xs text-cyber-text-faint">
        The chart fills in as it trades.
      </div>
    );
  }
  const t0 = points[0][0];
  const t1 = Math.max(points[points.length - 1][0], t0 + 1);
  const vals = points.map((p) => p[1]);
  let lo = Math.min(...vals, start, floor ?? Infinity);
  let hi = Math.max(...vals, start);
  // Show the take-profit line only when it is near enough not to flatten everything else.
  const showTp = takeProfit !== null && takeProfit <= hi + (hi - lo) * 0.6;
  if (showTp) hi = Math.max(hi, takeProfit!);
  const pad = (hi - lo || hi * 0.01 || 1) * 0.08;
  lo -= pad;
  hi += pad;
  const y = (v: number) => height - ((v - lo) / (hi - lo)) * height;
  const x = (t: number) => ((t - t0) / (t1 - t0)) * 100;
  const line = points.map(([t, v]) => `${x(t).toFixed(2)},${y(v).toFixed(2)}`).join(" ");
  const last = vals[vals.length - 1];
  const color = last >= start ? "#22c55e" : "#ef4444";
  const pct = (v: number) => `${(y(v) / height) * 100}%`;

  return (
    <div>
      <div className="relative" style={{ height }}>
        <svg
          viewBox={`0 0 100 ${height}`}
          preserveAspectRatio="none"
          className="absolute inset-0 h-full w-full"
          role="img"
          aria-label={`Value over time: started at ${fmtUsd(start, 0)}, now ${fmtUsd(last, 0)}${floor ? `, floor at ${fmtUsd(floor, 0)}` : ""}.`}
        >
          <defs>
            <linearGradient id={`ap-fill-${gid}`} x1="0" x2="0" y1="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity="0.18" />
              <stop offset="100%" stopColor={color} stopOpacity="0" />
            </linearGradient>
          </defs>
          {[0.25, 0.5, 0.75].map((f) => (
            <line key={f} x1="0" x2="100" y1={height * f} y2={height * f} stroke="#1e1e2a" strokeWidth="0.5" vectorEffect="non-scaling-stroke" />
          ))}
          <polygon points={`0,${height} ${line} 100,${height}`} fill={`url(#ap-fill-${gid})`} />
          <line x1="0" x2="100" y1={y(start)} y2={y(start)} stroke="#9a9ab2" strokeWidth="1" strokeDasharray="4 4" vectorEffect="non-scaling-stroke" />
          {floor !== null && (
            <line x1="0" x2="100" y1={y(floor)} y2={y(floor)} stroke="#ef4444" strokeWidth="1.2" strokeDasharray="6 4" vectorEffect="non-scaling-stroke" />
          )}
          {showTp && (
            <line x1="0" x2="100" y1={y(takeProfit!)} y2={y(takeProfit!)} stroke="#22c55e" strokeWidth="1" strokeDasharray="2 4" vectorEffect="non-scaling-stroke" />
          )}
          <polyline points={line} fill="none" stroke={color} strokeWidth="1.8" vectorEffect="non-scaling-stroke" />
        </svg>
        <ChartLabel top={pct(start)} above className="text-cyber-text-dim">
          start {fmtUsd(start, 0)}
        </ChartLabel>
        {floor !== null && (
          <ChartLabel top={pct(floor)} className="text-danger">
            floor {fmtUsd(floor, 0)}
          </ChartLabel>
        )}
        {showTp && (
          <ChartLabel top={pct(takeProfit!)} above className="text-success">
            take profit {fmtUsd(takeProfit!, 0)}
          </ChartLabel>
        )}
      </div>
      <div className="mt-1 flex justify-between text-[11px] text-cyber-text-faint">
        <span>{fmtWhen(t0)}</span>
        <span>{endLabel}</span>
      </div>
    </div>
  );
}

function ChartLabel({ top, above, className, children }: { top: string; above?: boolean; className: string; children: ReactNode }) {
  return (
    <span
      style={{ top, transform: above ? "translateY(-100%)" : undefined }}
      className={`pointer-events-none absolute right-1 rounded bg-cyber-surface/80 px-1 font-mono text-[10px] leading-4 ${className}`}
    >
      {children}
    </span>
  );
}

// ── 3 · analysis ────────────────────────────────────────────────────────────

function AnalysisCard({ s, btc }: { s: AutopilotStatus; btc: AutopilotApi["btc"] }) {
  const advanced = useAdvanced();
  const now = Date.now();
  const a = analyse(s, now);
  const active = isActive(s);
  const hold = compareWithHold(a.points, btc?.times, btc?.closes, a.startMs, a.endMs);
  const over = `${fmtDays(a.days)}${a.days < 1 ? ` (${fmtDuration(a.endMs - a.startMs)})` : ""}`;

  const items: { icon: LucideIcon; tone: string; text: ReactNode }[] = [];

  // Against its start.
  items.push({
    icon: s.pnl >= 0 ? TrendingUp : TrendingDown,
    tone: s.pnl > 0.005 ? "text-success" : s.pnl < -0.005 ? "text-danger" : "text-cyber-text-faint",
    text: (
      <>
        It {active ? "has turned" : "turned"} {fmtUsd(s.startCapital, 0)} into <b className="text-cyber-text">{fmtUsd(s.equity, 2)}</b>:{" "}
        {Math.abs(s.pnl) < 0.005 ? (
          "no change"
        ) : (
          <b className={s.pnl > 0 ? "text-success" : "text-danger"}>
            {s.pnl > 0 ? "up" : "down"} {fmtUsd(Math.abs(s.pnl), 2)} ({signedPct(s.pnlPct, 1)})
          </b>
        )}{" "}
        after every fee, over {over}.
      </>
    ),
  });

  // Against just holding Bitcoin.
  if (hold) {
    const diff = hold.runPct - hold.holdPct;
    items.push({
      icon: BarChart3,
      tone: diff >= 0 ? "text-success" : "text-warning",
      text: (
        <>
          <Term k="Just holding Bitcoin">Just holding Bitcoin</Term>{" "}
          {hold.partial ? (
            <>
              over the {fmtDuration(hold.toMs - hold.fromMs)} the price history covers (from {fmtWhen(hold.fromMs)})
            </>
          ) : (
            "over the same period"
          )}{" "}
          would have gone <b className="text-cyber-text">{signedPct(hold.holdPct, 1)}</b>; the autopilot went{" "}
          <b className="text-cyber-text">{signedPct(hold.runPct, 1)}</b>. That is{" "}
          <b className={diff >= 0 ? "text-success" : "text-warning"}>
            {Math.abs(diff).toFixed(1)} percentage point{Math.abs(diff).toFixed(1) === "1.0" ? "" : "s"} {diff >= 0 ? "better" : "worse"}
          </b>{" "}
          than doing nothing{s.config.venue === "alpaca" ? " with Bitcoin, though this run traded shares" : ""}.
        </>
      ),
    });
  } else {
    items.push({
      icon: BarChart3,
      tone: "text-cyber-text-faint",
      text: !btc
        ? "There is no Bitcoin price in this build to compare it with."
        : !btc.times || btc.times.length < 2
          ? "Comparing with just holding Bitcoin needs Bitcoin prices with dates. The desktop app and a connected server keep those; this browser version does not, so the comparison is not available here."
          : "The Bitcoin prices in memory do not reach back to this run's dates, so the comparison with just holding is not available.",
    });
  }

  // Strategy by strategy.
  if (a.sleeves.length > 0) {
    items.push({
      icon: Activity,
      tone: "text-accent",
      text: (
        <>
          {a.sleeves.map((b, i) => (
            <span key={b.strategyId}>
              {i > 0 && (i === a.sleeves.length - 1 ? " and " : ", ")}
              <b className="text-cyber-text">{b.name}</b>{" "}
              {Math.abs(b.pnl) < 0.005 ? "broke even" : b.pnl > 0 ? "earned" : "lost"}{" "}
              {Math.abs(b.pnl) >= 0.005 && (
                <b className={b.pnl > 0 ? "text-success" : "text-danger"}>{fmtUsd(Math.abs(b.pnl), 2)}</b>
              )}{" "}
              from {b.trades} trade{b.trades === 1 ? "" : "s"}
            </span>
          ))}
          .
        </>
      ),
    });
  }

  // Costs.
  const share = a.pnl.costShare;
  items.push({
    icon: Receipt,
    tone: a.pnl.costHeavy ? "text-warning" : "text-cyber-text-faint",
    text:
      a.pnl.costs <= 0 ? (
        "It has paid no fees yet."
      ) : share !== undefined ? (
        <>
          Fees came to <b className="text-cyber-text">{fmtUsd(a.pnl.costs, 2)}</b>, which is{" "}
          <b className={a.pnl.costHeavy ? "text-warning" : "text-cyber-text"}>{(share * 100).toFixed(0)}%</b> of the{" "}
          {fmtUsd(a.pnl.gross, 2)} it made before fees.
          {a.pnl.costHeavy && " Above 40 % the costs are the story, not the strategies."}
        </>
      ) : (
        <>
          It paid <b className="text-cyber-text">{fmtUsd(a.pnl.costs, 2)}</b> in fees and made nothing before fees, so the fees only
          added to the loss.
        </>
      ),
  });

  // Worst dip.
  items.push({
    icon: TrendingDown,
    tone: a.dip && a.dip.pct > 10 ? "text-warning" : "text-cyber-text-faint",
    text: a.dip ? (
      <>
        Its worst dip was <b className="text-cyber-text">{a.dip.pct.toFixed(1)}%</b> ({fmtUsd(a.dip.usd, 0)}), from its high on{" "}
        {fmtWhen(a.dip.peakMs)} to the low on {fmtWhen(a.dip.troughMs)}.
      </>
    ) : (
      "It never fell below an earlier high."
    ),
  });

  // How often.
  items.push({
    icon: Clock,
    tone: "text-cyber-text-faint",
    text:
      a.tradesPerDay === null ? (
        "Too early to say how often it trades."
      ) : (
        <>
          It made <b className="text-cyber-text">{a.tradesPerDay.toFixed(1)}</b> trade{a.tradesPerDay.toFixed(1) === "1.0" ? "" : "s"} a day on
          average ({s.trades} in {fmtDays(a.days)}).
        </>
      ),
  });

  const m = a.maturity;
  const left: string[] = [];
  if (m.daysLeft > 0) left.push(`${m.daysLeft} more day${m.daysLeft === 1 ? "" : "s"}`);
  if (m.tradesLeft > 0) left.push(`${m.tradesLeft} more trade${m.tradesLeft === 1 ? "" : "s"}`);

  return (
    <Card
      title={`How it did: ${s.config.name}`}
      icon={BarChart3}
      help="A plain report on this run: against its start, against just holding Bitcoin, per strategy, and what it cost."
      subtitle={`${active ? "So far" : s.state === "finished" ? "Finished" : "Stopped"} · ${fmtWhen(a.startMs)} to ${active ? "now" : fmtWhen(a.endMs)}`}
    >
      <ul className="space-y-2.5">
        {items.map((it, i) => (
          <li key={i} className="flex items-start gap-2.5 text-sm leading-relaxed text-cyber-text-dim">
            <it.icon size={15} aria-hidden className={`mt-0.5 shrink-0 ${it.tone}`} />
            <span className="min-w-0">{it.text}</span>
          </li>
        ))}
      </ul>

      <Notice tone={m.enough ? "info" : "warning"} className="mt-4" title={m.enough ? "Enough to start judging" : "Too early to judge"}>
        {m.enough ? (
          <>
            With {fmtDays(m.days)} and {m.trades} trades the numbers carry some weight. They still describe the past, not the
            future.
          </>
        ) : (
          <>
            {fmtDays(m.days)[0].toUpperCase() + fmtDays(m.days).slice(1)} and {m.trades} trade{m.trades === 1 ? "" : "s"} are mostly
            noise: a good result can be luck, a bad one bad luck. The numbers start to mean something after at least{" "}
            {MEANINGFUL_DAYS} days and {MEANINGFUL_TRADES} trades, the same bar a strategy has to clear before it may use real money.
            {active ? ` ${left.join(" and ")} to go.` : " This run ended before that."}
          </>
        )}
      </Notice>

      {advanced && (
        <div className="mt-4 space-y-3 border-t border-cyber-border pt-4">
          <PnlLines pnl={a.pnl} compact />
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Readout label="Days" value={a.days.toFixed(1)} help="How long it has run, in days." />
            <Readout label="Trades per day" value={a.tradesPerDay === null ? "n/a" : a.tradesPerDay.toFixed(2)} />
            <Readout label="Worst Drawdown" value={a.dip ? `${a.dip.pct.toFixed(2)}%` : "0%"} tone={a.dip && a.dip.pct > 10 ? "amber" : "neutral"} />
            <Readout
              label="Cost share"
              value={share !== undefined ? `${(share * 100).toFixed(1)}%` : a.pnl.costs > 0 ? "no gross gain" : "n/a"}
              tone={a.pnl.costHeavy ? "amber" : "neutral"}
            />
          </div>
        </div>
      )}
    </Card>
  );
}

// ── 4 · past runs ───────────────────────────────────────────────────────────

function PastList({
  past,
  shownId,
  onAnalyse,
}: {
  past: AutopilotStatus[];
  shownId?: string;
  onAnalyse: (id: string) => void;
}) {
  const simple = !useAdvanced();
  return (
    <Card title="Past autopilots" icon={History} help="Every earlier run with how it ended. Pick one to see its report above.">
      {past.length === 0 ? (
        <EmptyState icon={History} title="No finished autopilots yet" compact>
          When an autopilot stops or finishes, it is listed here with its result.
        </EmptyState>
      ) : (
        <ul className="space-y-2">
          {past.map((p) => {
            const badge = modeBadge(p.config.mode, simple);
            const end = p.stoppedMs ?? p.startedMs;
            const shown = p.config.id === shownId;
            return (
              <li
                key={p.config.id}
                className={`rounded-lg border px-3 py-2.5 ${shown ? "border-accent/40 bg-accent/[0.04]" : "border-cyber-border bg-cyber-bg/40"}`}
              >
                <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-1">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      {p.state === "finished" ? (
                        <Flag size={14} aria-hidden className="shrink-0 text-accent" />
                      ) : (
                        <Square size={13} aria-hidden className="shrink-0 text-cyber-text-faint" />
                      )}
                      <span className="text-sm font-medium text-cyber-text">{p.config.name}</span>
                      <Badge tone={badge.tone}>{badge.text}</Badge>
                      <Badge tone="neutral">{p.state === "finished" ? "finished" : "stopped"}</Badge>
                    </div>
                    <div className="mt-0.5 flex items-start gap-1 text-xs text-cyber-text-faint">
                      <CalendarClock size={12} aria-hidden className="mt-0.5 shrink-0" />
                      <span className="min-w-0">
                        {fmtWhen(p.startedMs)} to {fmtWhen(end)} · {fmtDuration(end - p.startedMs)} · {p.trades} trades
                      </span>
                    </div>
                  </div>
                  <div className="flex w-full items-baseline gap-2 sm:block sm:w-auto sm:text-right">
                    <div className={`font-mono text-sm font-bold ${p.pnl > 0.005 ? "text-success" : p.pnl < -0.005 ? "text-danger" : "text-cyber-text"}`}>
                      {signedUsd(p.pnl)}
                    </div>
                    <div className="font-mono text-xs text-cyber-text-faint">
                      {signedPct(p.pnlPct, 1)} of {fmtUsd(p.startCapital, 0)}
                    </div>
                  </div>
                </div>
                {p.stopReason && <div className="mt-1 text-xs text-cyber-text-dim">{p.stopReason}</div>}
                <div className="mt-2">
                  <Button tone={shown ? "cyan" : "neutral"} size="sm" icon={BarChart3} onClick={() => onAnalyse(p.config.id)}>
                    {shown ? "Showing its report" : "Show its report"}
                  </Button>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}
