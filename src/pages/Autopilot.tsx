import { useMemo, useRef, useState, type ReactNode } from "react";
import {
  Activity,
  BarChart3,
  CalendarClock,
  CheckCircle2,
  Circle,
  Clock,
  FlaskConical,
  Flag,
  History,
  Lock,
  Pause,
  Pencil,
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
  AreaChart,
  Badge,
  Button,
  Card,
  Field,
  List,
  Notice,
  SectionTitle,
  Sheet,
  Toggle,
  changeTone,
  inputCls,
  money,
  signedMoney,
  signedPct,
  type Scrub,
} from "../design";
import {
  CostLines,
  Explain,
  KeyStats,
  LoadingRows,
  Meter,
  Nothing,
  Row,
  Section,
  SwitchRow,
  Term,
  plural,
  type StatTone,
} from "../pagekit";
import {
  capitalise,
  feeShare,
  floorRoom,
  modeLabel,
  moveWords,
  parseInput,
  pointsWord,
  setupProblems,
  splitCurve,
  stillToGo,
} from "../pagekit/autopilotView";
import { explain } from "../glossary";
import { ReadinessCard } from "../components/ReadinessCard";
import { RealMoneyLink } from "../components/RealMoneyLink";
import { useStore } from "../store";
import { useAdvanced } from "../uiMode";
import { autopilotVenue, demoIsApiTestOnly, exchangeName } from "../venueNames";
import { benchmark } from "../practice";
import { useMockAutopilot, type MockScenario } from "../autopilotMock";
import {
  LIVE_EDIT_PHRASE,
  LIVE_PHRASE,
  LIVE_TEST_MAX_LOSS_PCT,
  LIVE_TEST_PHRASE,
  isLiveTest,
  liveConfirmed,
  liveTestCap,
  lossAllowance,
  MEANINGFUL_DAYS,
  MEANINGFUL_TRADES,
  analyse,
  bitcoinMarket,
  blendWords,
  classRows,
  compareWithHold,
  curve,
  editForm,
  floorAtStart,
  fmtDays,
  fmtDuration,
  fmtWhen,
  forwardLine,
  isActive,
  limit,
  planEdit,
  REPICK_CHOICES,
  EXPERIMENT_HINT,
  EXPERIMENT_LABEL,
  isExperiment,
  sleeveExposure,
  autopilotClass,
  groupByMoney,
  liveVenueCash,
  realMoneyState,
  type EditForm,
  type Stop,
} from "../autopilot";
import type { AutopilotConfig, AutopilotStart, AutopilotStatus, AutopilotUpdate, Venue } from "../types";

// ── where the numbers come from ─────────────────────────────────────────────

export interface AutopilotApi {
  loading: boolean;
  /** Set only in a dev build opened with `?mockAutopilot`: the page shows sample data. */
  mocked: MockScenario | null;
  autopilots: AutopilotStatus[];
  start: (config: AutopilotStart) => Promise<void>;
  stop: (id: string, flatten: boolean) => Promise<void>;
  pause: (id: string) => Promise<void>;
  resume: (id: string) => Promise<void>;
  /** Change it in place; `confirm` for live and for a looser loss limit. */
  update: (id: string, update: AutopilotUpdate, confirm: boolean) => Promise<void>;
  /** Bitcoin bar times and closes, for the "just holding" comparison. */
  btc: { symbol: string; times?: number[]; closes?: number[] } | null;
}

export function useAutopilotApi(): AutopilotApi {
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
      update: mock.update,
      btc: { symbol: "BTC/USD", times: mock.btc.times, closes: mock.btc.closes },
    };
  }
  return {
    loading: store.portfolio.equity <= 0 && store.markets.length === 0,
    mocked: null,
    autopilots: store.autopilots,
    // The page checks the typed phrase (a capped live test has its own); the
    // engine only takes a flag, and refuses live without it.
    start: ({ confirm, ...config }: AutopilotStart) => store.startAutopilot(config, liveConfirmed(config, confirm)),
    stop: store.stopAutopilot,
    pause: store.pauseAutopilot,
    resume: store.resumeAutopilot,
    update: store.updateAutopilot,
    btc: btc ? { symbol: btc.symbol, times: store.historyTimes[btc.id], closes: store.history[btc.id] } : null,
  };
}

// ── words ───────────────────────────────────────────────────────────────────

const VENUES: { id: Venue; label: string; note: string }[] = [
  { id: "crypto", label: "Crypto exchange", note: "Open day and night. Buys and sells coins, never borrows to bet against them." },
  { id: "alpaca", label: "US shares (Alpaca)", note: "Trades only while the US market is open." },
  {
    id: "perps",
    label: "Perps, long and short",
    note: "Perpetual futures on a demo account (or practice money): the one place Pythia goes short. Never real money.",
  },
];

/** The lab's market-neutral M4 book on perps, the strategy the perps preset names. */
export const M4_PERPS = "lab:m4_perps";

function venueLabel(v: string): string {
  return VENUES.find((x) => x.id === v)?.label ?? v;
}

type Mode = AutopilotConfig["mode"];

/** Text colour for an up, down or flat amount. */
const TONE_TEXT = { up: "text-up", down: "text-down", flat: "text-ink" } as const;

// ── the page ────────────────────────────────────────────────────────────────

/**
 * The autopilot in full: an amount it trades on its own until it is stopped,
 * a limit is hit, or an end date passes. Setup when nothing runs, the running
 * view while something does, then an honest analysis and the runs that came
 * before. The Autopilot page shows this under "Full setup and analysis", so it
 * brings no page frame of its own.
 */
export function Autopilot() {
  const api = useAutopilotApi();
  const { limits } = useStore();
  const [selected, setSelected] = useState<string | null>(null);
  const [another, setAnother] = useState(false);
  const analysisRef = useRef<HTMLDivElement>(null);

  // Practice money only: the real-money runs are on the Real money page.
  const { real, practice } = groupByMoney(api.autopilots);
  const active = practice.filter(isActive).sort((a, b) => b.startedMs - a.startedMs);
  const past = practice
    .filter((a) => !isActive(a))
    .sort((a, b) => (b.stoppedMs ?? b.startedMs) - (a.stoppedMs ?? a.startedMs));
  const shown = practice.find((a) => a.config.id === selected) ?? active[0] ?? past[0];
  const advanced = useAdvanced();

  function analyseRun(id: string) {
    setSelected(id);
    requestAnimationFrame(() => analysisRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }));
  }

  return (
    <div className="min-w-0 space-y-5">
      <header className="px-1">
        <h2 className="text-xl font-semibold tracking-tight text-ink">Full setup and analysis</h2>
        <p className="mt-1 text-[15px] leading-relaxed text-muted">
          Give it an amount and it trades that amount on its own: until you stop it, until a limit you set is reached, or for ever.
        </p>
      </header>

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
          <LoadingRows label="Waiting for the engine to report its autopilots" />
        </Card>
      ) : (
        <>
          {/* Real money has its own page; in the advanced view the link is always there. */}
          {(real.length > 0 || advanced) && <RealMoneyLink count={real.filter(isActive).length} />}
          {active.length === 0 ? (
            <Setup onStart={api.start} />
          ) : (
            <>
              {active.length > 0 && (
                <section aria-label="Practice (paper and demo)" className="space-y-3">
                  <SectionTitle>Practice (paper and demo)</SectionTitle>
                  {active.map((s) => (
                    <Running key={s.config.id} s={s} api={api} onAnalyse={() => analyseRun(s.config.id)} />
                  ))}
                </section>
              )}
              {/* Several run side by side, each in a book of its own on the shared account. */}
              {another ? (
                <Setup
                  onStart={async (c) => {
                    await api.start(c);
                    setAnother(false);
                  }}
                />
              ) : (
                <Button variant="secondary" icon={Plane} onClick={() => setAnother(true)}>
                  Start another autopilot next to {active.length === 1 ? "this one" : `these ${active.length}`}
                </Button>
              )}
            </>
          )}

          {!api.mocked && <ReadinessCard />}

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
    <fieldset className="min-w-0 py-5 first:pt-0 last:pb-0">
      <legend className="float-left mb-3 flex w-full items-center gap-2 text-[15px] font-semibold text-ink">
        <span className="tabular flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-surface-2 text-[12px] font-semibold text-muted" aria-hidden>
          {n}
        </span>
        <span className="min-w-0">{title}</span>
        {tip && <Explain text={tip} label={title} />}
      </legend>
      <div className="clear-both">{children}</div>
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
  const on = danger ? "border-down bg-down/[0.08]" : "border-ink bg-surface-2";
  return (
    <label
      className={`flex min-w-0 cursor-pointer items-start gap-3 rounded-2xl border px-4 py-3 transition-colors ${
        checked ? on : "border-line hover:border-line-strong"
      }`}
    >
      <input
        type="radio"
        name={name}
        checked={checked}
        onChange={onChange}
        aria-label={title}
        className="mt-1 h-4 w-4 shrink-0"
        style={{ accentColor: danger ? "var(--color-down)" : "var(--color-accent)" }}
      />
      <span className="min-w-0">
        <span className={`flex flex-wrap items-center gap-1.5 text-[15px] font-semibold ${danger ? "text-down" : "text-ink"}`}>
          {Icon && <Icon size={15} aria-hidden className="shrink-0" />}
          {title}
          {badge}
        </span>
        <span className="mt-0.5 block text-[13px] leading-relaxed text-muted">{detail}</span>
      </span>
    </label>
  );
}

/** A switch that turns one optional limit on, with its input under it. */
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
    <div className="py-3">
      <div className="flex items-center justify-between gap-3">
        <span className="flex min-w-0 items-center gap-1 text-[15px] text-ink">
          <span className="min-w-0">{label}</span>
          {tip && <Explain text={tip} label={label} />}
        </span>
        <Toggle on={on} onChange={onToggle} label={label} />
      </div>
      {on && children && <div className="mt-2 flex flex-wrap items-center gap-2 text-sm text-muted">{children}</div>}
    </div>
  );
}

/** The shared input look without its full width, for inputs that sit inside a sentence. */
const inlineCls = inputCls.replace("w-full ", "");

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
    <span className="inline-flex items-center gap-1.5">
      {prefix && <span className="text-muted">{prefix}</span>}
      <input inputMode="decimal" value={value} onChange={(e) => onChange(e.target.value)} aria-label={label} className={`${inlineCls} ${width} tabular`} />
      {suffix && <span className="text-muted">{suffix}</span>}
    </span>
  );
}

/** `datetime-local` wants local time without a zone. */
function localInput(ms: number): string {
  const d = new Date(ms - new Date(ms).getTimezoneOffset() * 60_000);
  return d.toISOString().slice(0, 16);
}

function Setup({ onStart }: { onStart: (c: AutopilotStart) => Promise<void> }) {
  const { strategies, passports, live, cryptoCostVenue, autopilots } = useStore();
  const advanced = useAdvanced();
  const simple = !advanced;

  const [mode, setMode] = useState<Mode>("paper");
  const [venue, setVenue] = useState<Venue>("crypto");
  // A portfolio over crypto and US shares: paper or demo only, Pythia picks.
  const [both, setBoth] = useState(false);
  const [amount, setAmount] = useState("1000");
  const [pick, setPick] = useState<"auto" | "manual">("auto");
  const [repick, setRepick] = useState(24);
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
  // The owner chose a capped live test for strategies without a green passport.
  const [testOn, setTestOn] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const capital = parseInput(amount);
  // The exchange it would trade on, by its own name ("Bybit", not "crypto").
  // A portfolio trades both classes on the Alpaca account.
  const target = both ? "alpaca" : autopilotVenue(mode, venue, live, cryptoCostVenue);
  const targetName = exchangeName(target);
  // Experiments failed the lab's bar: never offered for real money.
  const eligible = strategies.filter((s) => s.id !== "manual" && s.venueClass === venue && !(mode === "live" && isExperiment(s)));
  const chosen = eligible.map((s) => ({ s, w: parseInput(weights[s.id] ?? "") })).filter((x) => x.w > 0);
  const weightSum = chosen.reduce((a, x) => a + x.w, 0);

  const stop: Stop = { onTakeProfit: onTp };
  if (lossPctOn) stop.maxLossPct = parseInput(lossPct);
  if (lossUsdOn) stop.maxLossUsd = parseInput(lossUsd);
  if (tpOn) stop.takeProfitPct = parseInput(tp);
  if (trailOn) stop.trailingPct = parseInput(trail);
  const endMs = endOn ? new Date(end).getTime() : undefined;
  if (endOn && endMs !== undefined && Number.isFinite(endMs)) stop.endMs = endMs;
  const plan = floorAtStart(capital > 0 ? capital : 0, stop);
  const anyLimit = lossPctOn || lossUsdOn || tpOn || trailOn || endOn;

  // What is wrong with the form, in plain sentences.
  const problems = setupProblems({
    capital,
    manual: pick === "manual",
    chosen: chosen.length,
    lossPctOn,
    lossPct: stop.maxLossPct,
    lossUsdOn,
    lossUsd: stop.maxLossUsd,
    tpOn,
    tp: stop.takeProfitPct,
    trailOn,
    trail: stop.trailingPct,
    endOn,
    endMs,
    now: Date.now(),
  });
  // The engine refuses this too; saying it here saves a round trip.
  if (!both && mode === "demo" && venue === "crypto" && demoIsApiTestOnly(live)) {
    problems.push(
      `${exchangeName(live.demoExchange)} runs its demo account on its own prices, so a demo autopilot there would be judged in a different price world than its stop rules watch. Use Bybit or Binance demo keys, Alpaca paper, or practice money.`,
    );
  }
  if (!both && venue === "perps") {
    if (mode === "live") problems.push(live.perps?.live ?? "Real-money perpetuals are switched off.");
    if (mode === "demo" && !live.perps) {
      problems.push("No perps venue is configured on the server (PYTHIA_PERPS_DEMO, docs/KRAKEN-FUTURES-DEMO.md). Practice money works without one.");
    } else if (mode === "demo" && live.perps?.demoBlocked) {
      problems.push(`The perps demo account cannot take orders: ${live.perps.demoBlocked}.`);
    }
    if (pick === "auto") problems.push("Pythia does not pick perps books on its own: choose \"I pick them\" and name the M4 book.");
  }
  const demoVenues = live.demoVenues ?? [];
  if (both && mode === "demo" && (!demoVenues.includes("alpaca") || !demoVenues.includes("crypto") || live.demoExchange !== "alpaca")) {
    problems.push(
      "A demo portfolio trades crypto and US shares on the one Alpaca paper account, so it needs the Alpaca paper keys and crypto demo orders sent there too (PYTHIA_DEMO_EXCHANGE=alpaca on the backend). Or use practice money.",
    );
  }

  // Real money: every requirement spelled out, checked here and again by the engine.
  // The live venue's own cash as Pythia last read it, never the paper account's.
  const cashRead = liveVenueCash(live, venue);
  const liveCash = cashRead?.cash;
  const cashFrom = cashRead ? `${exchangeName(cashRead.exchange)}, read ${fmtWhen(cashRead.readMs)}` : "";
  const armedHere = live.armed && !live.paper && !live.dryRun && live.venues.includes(venue);
  const ready = (id: string) => passports.get(id)?.liveReady ?? false;
  const readyCount = eligible.filter((s) => ready(s.id)).length;
  const checksOk = pick === "manual" ? chosen.length > 0 && chosen.every((x) => ready(x.s.id)) : readyCount > 0;
  // Strategies picked by hand without a green passport: a normal live start
  // is refused, a capped live test is offered instead.
  const unproven = mode === "live" && pick === "manual" ? chosen.filter((x) => !ready(x.s.id)).map((x) => x.s.name) : [];
  const liveTest = testOn && unproven.length > 0;
  const cap = liveTestCap(live);
  const otherTest = autopilots.find((a) => isActive(a) && isLiveTest(a.config))?.config.name ?? null;
  const testLoss = lossAllowance(stop, capital > 0 ? capital : 0);
  const phrase = liveTest ? LIVE_TEST_PHRASE : LIVE_PHRASE;
  const passportRow: { ok: boolean | null; text: ReactNode } = liveTest
    ? {
        ok: null,
        text: `Not passed its checks: ${unproven.join(", ")}. It runs as a capped live test, so this is allowed and the strategy stays unproven.`,
      }
    : {
        ok: checksOk,
        text:
          pick === "manual"
            ? checksOk
              ? "Every strategy you picked has passed its checks."
              : "Every strategy you pick has to have passed its checks (the Strategy Passport), or you start it as a capped live test (above)."
            : readyCount > 0
              ? `Pythia only chooses among strategies that passed their checks: ${readyCount} of ${eligible.length} here have.`
              : `None of the ${eligible.length} strategies for ${venueLabel(venue)} has passed its checks yet, so there is nothing Pythia may choose. To try one with a small amount anyway, choose "I pick them": a capped live test is offered there.`,
      };
  const testRows: { ok: boolean | null; text: ReactNode }[] = liveTest
    ? [
        {
          ok: capital > 0 && capital <= cap + 1e-9,
          text: `The amount is at most ${money(cap, 2)}, the cap for a live test.`,
        },
        {
          ok: testLoss.pct !== undefined && testLoss.pct <= LIVE_TEST_MAX_LOSS_PCT + 1e-9,
          text:
            testLoss.pct === undefined
              ? `A loss limit of at most ${LIVE_TEST_MAX_LOSS_PCT}% of the amount is set (step 4).`
              : `The loss limit is ${money(testLoss.usd ?? 0, 2)} (${testLoss.pct.toFixed(0)}%); a live test allows at most ${LIVE_TEST_MAX_LOSS_PCT}%.`,
        },
        {
          ok: !otherTest,
          text: otherTest ? `"${otherTest}" is already a live test, and only one runs at a time. Stop it first.` : "No other live test is running.",
        },
      ]
    : [];
  const requirements: { ok: boolean | null; text: ReactNode }[] = [
    {
      ok: armedHere,
      text: armedHere
        ? `Real-money trading is armed for ${targetName}.`
        : `Real-money trading has to be armed for ${targetName} on the Live page (advanced view), on the real endpoint, not dry-run.`,
    },
    passportRow,
    ...testRows,
    {
      ok: liveCash === undefined ? null : capital > 0 && capital <= liveCash,
      text:
        liveCash === undefined
          ? "The amount may not be more than the cash in the account. Pythia checks that with the exchange when it starts."
          : capital <= liveCash
            ? `The amount is within the account's cash (${money(liveCash, 0)} at ${cashFrom}). Pythia checks it again when it starts.`
            : `The amount is more than the account's cash (${money(liveCash, 0)} at ${cashFrom}).`,
    },
  ];
  const liveBlocked = mode === "live" && (requirements.some((r) => r.ok === false) || typed.trim().toUpperCase() !== phrase);

  function chooseTest(on: boolean) {
    setTestOn(on);
    setTyped("");
    if (!on) return;
    // Bring the form inside the caps; the owner still reads and confirms it.
    if (!(capital > 0) || capital > cap) setAmount(String(cap));
    if (!lossPctOn && !lossUsdOn) {
      setLossPctOn(true);
      setLossPct("20");
    }
  }
  const canStart = problems.length === 0 && !liveBlocked && !busy;

  async function start() {
    if (!canStart) return;
    setBusy(true);
    setErr("");
    const now = Date.now();
    const label = name.trim() || `${both ? "Portfolio" : "Autopilot"} ${new Date(now).toLocaleDateString("en-GB", { day: "numeric", month: "short" })}`;
    const config: AutopilotStart = both
      ? {
          // Both classes on the Alpaca account, split by evidence; the engine
          // picks the lab books of each class.
          id: `ap-${now.toString(36)}`,
          name: label,
          mode,
          venue: "alpaca",
          capitalUsd: capital,
          sleeves: [],
          repickEveryHours: repick,
          stop,
          flattenOnStop: flatten,
          portfolio: true,
        }
      : {
          id: `ap-${now.toString(36)}`,
          name: label,
          mode,
          // The engine wants the exchange, not the asset class: crypto demo runs
          // on the demo exchange, other crypto on the one selected in Settings,
          // US shares on Alpaca.
          venue: target,
          // Crypto demo on Alpaca paper is venue "alpaca" trading crypto, not shares.
          assetClass: venue,
          capitalUsd: capital,
          sleeves: pick === "manual" ? chosen.map((x) => ({ strategyId: x.s.id, weight: x.w / weightSum })) : [],
          // Re-picking applies only when Pythia chooses; 0 turns it off.
          ...(pick === "auto" ? { repickEveryHours: repick } : {}),
          stop,
          // A live test always sells everything when it stops (the engine forces it too).
          flattenOnStop: flatten || liveTest,
          ...(mode === "live" ? { confirm: typed.trim().toUpperCase() } : {}),
          ...(liveTest ? { liveTest: true } : {}),
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
        : liveTest
        ? `Comes from the ${targetName} account you funded yourself. A capped live test: at most ${money(cap, 0)}, and it can lose all of it.`
        : `Comes from the ${targetName} account you funded yourself. The autopilot buys and sells inside that account and can lose this money.`;

  return (
    <Section title="Start an autopilot" help={explain("Autopilot")} hint="Four short questions. You can stop it at any moment, whatever you choose here.">
      {live.perps && (
        <div className="mb-3 flex flex-wrap items-center gap-3 rounded-lg border border-line px-3 py-2.5 text-[13px] text-muted">
          <span className="min-w-0 flex-1 basis-64">
            The lab's market-neutral M4 book (long and short perps) on the {live.perps.label} demo account. An experiment: it
            fails the deflation test and runs for forward evidence. Never real money.
          </span>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => {
              setMode(live.perps?.demoReady ? "demo" : "paper");
              setVenue("perps");
              setBoth(false);
              setPick("manual");
              setWeights({ [M4_PERPS]: "1" });
              setName(live.perps?.demoReady ? "M4 perps (demo)" : "M4 perps (paper)");
              setLossPctOn(true);
              setLossPct("20");
            }}
          >
            Set up "M4 perps (demo)"
          </Button>
        </div>
      )}
      <div className="divide-y divide-line">
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
              onChange={() => {
                setMode("live");
                // A portfolio is paper or demo only, and perps never trade real money.
                setBoth(false);
                if (venue === "perps") setVenue("crypto");
              }}
              icon={Lock}
              title="Real money"
              danger
              detail="An account you funded. Can lose real money. Needs more steps."
            />
          </div>
          <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2" role="radiogroup" aria-label="Where it trades">
            {VENUES.filter((v) => v.id !== "perps" || mode !== "live").map((v) => (
              <Choice
                key={v.id}
                name="ap-venue"
                checked={!both && venue === v.id}
                onChange={() => {
                  setVenue(v.id);
                  setBoth(false);
                  // Pythia never picks a perps book on its own (the M4 book is an
                  // experiment): the perps choice names it.
                  if (v.id === "perps") {
                    setPick("manual");
                    setWeights({ [M4_PERPS]: "1" });
                  }
                }}
                title={
                  v.id === "crypto" || v.id === "perps"
                    ? `${v.label} · ${exchangeName(autopilotVenue(mode, v.id, live, cryptoCostVenue))}${mode === "demo" ? " demo" : ""}`
                    : v.label
                }
                detail={v.note}
              />
            ))}
            {mode !== "live" && (
              <Choice
                name="ap-venue"
                checked={both}
                onChange={() => {
                  setBoth(true);
                  setPick("auto");
                }}
                title={`Crypto and US shares${mode === "demo" ? " · Alpaca paper" : ""}`}
                detail="One amount over both, split by the evidence of each side's lab books. Crypto trades day and night, shares only while the US market is open. Practice money or demo only."
              />
            )}
          </div>
        </Step>

        {/* 2 · how much */}
        <Step n={2} title="How much" help={explain("Start amount")}>
          <div className="flex flex-wrap items-center gap-3">
            <SmallInput value={amount} onChange={setAmount} label="Amount in US dollars" prefix="$" width="w-36" />
            {capital > 0 && <span className="tabular text-[15px] font-semibold text-ink">{money(capital, 0)}</span>}
          </div>
          <p className="mt-3 text-[13px] leading-relaxed text-muted">{source}</p>
          <p className="mt-2 flex items-start gap-2 text-[13px] leading-relaxed text-muted">
            <ShieldCheck size={15} aria-hidden className="mt-0.5 shrink-0 text-accent" />
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
              badge={<Badge tone="accent">Recommended</Badge>}
              detail="It picks the strategies with the best record after costs that suit the market right now, and tells you why."
            />
            {!both && (
              <Choice
                name="ap-pick"
                checked={pick === "manual"}
                onChange={() => setPick("manual")}
                title="I pick them"
                detail="Choose strategies yourself and how much of the amount each may use."
              />
            )}
          </div>
          {pick === "auto" && (
            <div className="mt-3 space-y-2 text-[13px] leading-relaxed text-muted">
              {both ? (
                <p>
                  Each side runs the lab's strategies with real out-of-sample evidence. The amount is split between crypto
                  and US shares by the evidence of each side's best strategy per unit of its worst fall, and a side with no
                  evidence gets nothing. When it chooses again, the split moves by at most 10 points at a time. It is held
                  against a blend of Bitcoin and SPY at the same split.
                </p>
              ) : (
                <p>
                  For crypto it can run up to three of the lab's strategies together. Their targets are added up per coin, so
                  each coin is one position, and each strategy gets a share of the amount by the strength of its evidence.
                </p>
              )}
              <Field label="Choose again with fresh evidence" hint="A change is traded in at the next rebalance, only by the difference per coin. Nothing is sold off at once.">
                <select value={repick} onChange={(e) => setRepick(Number(e.target.value))} aria-label="How often it chooses again" className={`${inputCls} sm:max-w-xs`}>
                  {REPICK_CHOICES.map((c) => (
                    <option key={c.hours} value={c.hours}>
                      {c.label}
                    </option>
                  ))}
                </select>
              </Field>
            </div>
          )}
          {pick === "manual" && (
            <div className="mt-3">
              {eligible.length === 0 ? (
                <Nothing icon={Activity} title={`No strategies for ${venueLabel(venue)} yet`}>
                  They arrive with the first update from the engine.
                </Nothing>
              ) : (
                <List>
                  {eligible.map((s) => {
                    const w = parseInput(weights[s.id] ?? "");
                    const share = w > 0 && weightSum > 0 ? (w / weightSum) * 100 : 0;
                    return (
                      <div key={s.id} className="flex flex-wrap items-center gap-x-3 gap-y-2 py-3">
                        <label className="flex min-w-0 flex-1 basis-48 cursor-pointer items-center gap-2.5 text-[15px] text-ink">
                          <input
                            type="checkbox"
                            checked={w > 0}
                            onChange={(e) => setWeights((p) => ({ ...p, [s.id]: e.target.checked ? "1" : "" }))}
                            aria-label={`Use ${s.name}`}
                            className="h-4 w-4 shrink-0"
                            style={{ accentColor: "var(--color-accent)" }}
                          />
                          <span className="min-w-0 truncate">{s.name}</span>
                        </label>
                        {isExperiment(s) && (
                          <Badge tone="warn" title={EXPERIMENT_HINT}>
                            {EXPERIMENT_LABEL}
                          </Badge>
                        )}
                        {mode === "live" && (
                          <Badge tone={ready(s.id) ? "good" : "neutral"} title="Strategy Passport">
                            {ready(s.id) ? "Checks passed" : "Checks not passed"}
                          </Badge>
                        )}
                        <span className="flex items-center gap-2 text-[13px] text-muted">
                          <Term k="Strategy share">Weight</Term>
                          <SmallInput value={weights[s.id] ?? ""} onChange={(v) => setWeights((p) => ({ ...p, [s.id]: v }))} label={`Weight for ${s.name}`} width="w-16" />
                          <span className="tabular w-10 text-right text-ink">{share > 0 ? `${share.toFixed(0)}%` : "Off"}</span>
                        </span>
                      </div>
                    );
                  })}
                </List>
              )}
              {chosen.length > 0 && (
                <p className="mt-2 text-[13px] text-muted">
                  Weights are relative: 2 and 1 means two thirds and one third of {capital > 0 ? money(capital, 0) : "the amount"}.
                </p>
              )}
            </div>
          )}
        </Step>

        {/* 4 · when to stop */}
        <Step n={4} title="When to stop" help="It runs until you stop it. Each limit below is optional and ends the run on its own.">
          <div className="flex items-center gap-2 rounded-2xl bg-surface-2 px-4 py-3 text-[15px] text-ink">
            {anyLimit ? <Circle size={15} aria-hidden className="shrink-0 text-faint" /> : <CheckCircle2 size={15} aria-hidden className="shrink-0 text-accent" />}
            <span className="min-w-0">
              Run until I stop it <span className="text-[13px] text-muted">{anyLimit ? "or until a limit below" : "(no limits set)"}</span>
            </span>
          </div>
          <List className="mt-1">
            <LimitRow on={lossPctOn} onToggle={setLossPctOn} label="Stop after losing a percentage" help={explain("Floor")}>
              Stop after losing <SmallInput value={lossPct} onChange={setLossPct} label="Loss limit in percent" suffix="%" width="w-20" />
              {capital > 0 && limit(parseInput(lossPct)) && <span className="tabular text-muted">= {money((capital * parseInput(lossPct)) / 100, 0)}</span>}
            </LimitRow>
            <LimitRow on={lossUsdOn} onToggle={setLossUsdOn} label="Stop after losing an amount" help={explain("Floor")}>
              Stop after losing <SmallInput value={lossUsd} onChange={setLossUsd} label="Loss limit in dollars" prefix="$" width="w-24" />
            </LimitRow>
            <LimitRow on={tpOn} onToggle={setTpOn} label="Take profit">
              When it is up <SmallInput value={tp} onChange={setTp} label="Take profit in percent" suffix="%" width="w-20" />
              <span className="flex min-w-0 max-w-full items-center gap-1">
                <select value={onTp} onChange={(e) => setOnTp(e.target.value as "stop" | "lock")} aria-label="What happens at the take-profit" className={`${inlineCls} w-auto max-w-full`}>
                  <option value="stop">then stop</option>
                  <option value="lock">then lock it in and keep going</option>
                </select>
                {onTp === "lock" && <Explain text={explain("Lock it in")!} label="Lock it in" />}
              </span>
            </LimitRow>
            <LimitRow on={trailOn} onToggle={setTrailOn} label="Never give back more than" help={explain("Trailing limit")}>
              <SmallInput value={trail} onChange={setTrail} label="Trailing limit in percent" suffix="%" width="w-20" />
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
          </List>

          <FloorSummary capital={capital} plan={plan} stop={stop} trailOn={trailOn} endOn={endOn} />

          <div className="mt-2">
            <SwitchRow
              label="When it stops on its own, sell everything it bought"
              on={flatten || liveTest}
              onChange={setFlatten}
              disabled={liveTest}
              hint={
                liveTest
                  ? "A capped live test always does: when a loss limit or its floor stops it, it sells everything, so no real coin is left without anyone looking after it."
                  : flatten
                    ? "It ends in cash. You can still choose differently when you stop it yourself."
                    : "What it bought stays in the account, and from then on you look after it yourself."
              }
            />
          </div>

          {advanced && (
            <Field label="Name (optional)" className="mt-3 sm:max-w-xs" hint="Only for you, to tell runs apart in the list of past autopilots.">
              <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Autopilot" className={inputCls} />
            </Field>
          )}
        </Step>

        {unproven.length > 0 && (
          <div className="py-5">
            <Notice tone="warning" icon={FlaskConical} title={liveTest ? "Capped live test chosen" : "Start as capped live test"}>
              <p className="mt-2 text-sm leading-relaxed text-ink">
                {unproven.join(", ")} {unproven.length === 1 ? "has" : "have"} not passed {unproven.length === 1 ? "its" : "their"} checks
                (the Strategy Passport), so a normal real-money start is refused. You can start a small, capped live test instead:
              </p>
              <ul className="mt-2 list-disc space-y-1 pl-5 text-sm leading-relaxed text-ink">
                <li>At most {money(cap, 0)} of real money.</li>
                <li>A loss limit of at most {LIVE_TEST_MAX_LOSS_PCT}% of the amount is required.</li>
                <li>Only one live test runs at a time. Every other real-money rule still applies.</li>
                <li>
                  The strategy is unproven. It may lose, and you can lose the whole amount. Its trades never count as evidence
                  that it is ready.
                </li>
              </ul>
              <div className="mt-3">
                <Button variant={liveTest ? "secondary" : "danger"} size="sm" icon={liveTest ? undefined : FlaskConical} onClick={() => chooseTest(!liveTest)}>
                  {liveTest ? "Back to a normal real-money start" : "Start as capped live test"}
                </Button>
              </div>
            </Notice>
          </div>
        )}

        {mode === "live" && (
          <div className="py-5">
            <Notice
              tone="danger"
              icon={TriangleAlert}
              title={
                liveTest
                  ? "LIVE TEST with real money: an unproven strategy that can lose the whole amount, also while you sleep."
                  : "Real money: this autopilot can lose the whole amount, also while you sleep."
              }
            >
              <ul className="mt-3 space-y-2">
                {requirements.map((r, i) => (
                  <li key={i} className="flex items-start gap-2 text-sm text-ink">
                    {r.ok === true ? (
                      <CheckCircle2 size={16} aria-label="Done" className="mt-0.5 shrink-0 text-up" />
                    ) : r.ok === false ? (
                      <XCircle size={16} aria-label="Missing" className="mt-0.5 shrink-0 text-down" />
                    ) : (
                      <Circle size={16} aria-label="Checked at the start" className="mt-0.5 shrink-0 text-faint" />
                    )}
                    <span className="min-w-0">{r.text}</span>
                  </li>
                ))}
              </ul>
              <label className="mt-3 block text-sm text-ink">
                Type <b className="text-down">{phrase}</b> to confirm
                <input
                  value={typed}
                  onChange={(e) => setTyped(e.target.value)}
                  placeholder={phrase}
                  autoComplete="off"
                  aria-label={`Type ${phrase} to confirm`}
                  className={`${inputCls} mt-1.5 bg-surface focus:border-down sm:max-w-xs`}
                />
              </label>
            </Notice>
          </div>
        )}

        {(problems.length > 0 || err) && (
          <div className="space-y-3 py-5">
            {problems.length > 0 && (
              <ul className="space-y-1.5">
                {problems.map((p) => (
                  <li key={p} className="flex items-start gap-2 text-[13px] leading-relaxed text-warn">
                    <TriangleAlert size={14} aria-hidden className="mt-0.5 shrink-0" />
                    <span className="min-w-0">{p}</span>
                  </li>
                ))}
              </ul>
            )}
            {err && (
              <Notice tone="danger" title="It did not start">
                {err}
              </Notice>
            )}
          </div>
        )}

        <div className="flex flex-wrap items-center gap-3 pt-5">
          <Button variant={mode === "live" ? "danger" : "primary"} icon={Play} onClick={() => void start()} disabled={!canStart}>
            {busy
              ? "Starting"
              : liveTest
                ? "Start the capped live test"
                : mode === "live"
                  ? "Start with real money"
                  : mode === "demo"
                    ? "Start on the demo account"
                    : "Start the autopilot"}
          </Button>
          <span className="text-[13px] text-muted">{mode === "paper" ? "Practice money: nothing can be lost." : "You can pause or stop it at any moment."}</span>
        </div>
      </div>
    </Section>
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
        At <b className="tabular font-semibold text-ink">{money(plan.takeProfitAt, 0)}</b> it takes the profit and{" "}
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
    <div className="mt-3 rounded-2xl bg-surface-2 px-4 py-3.5">
      {plan.floor !== null ? (
        <>
          <div className="flex flex-wrap items-center gap-1.5 text-[17px] font-semibold text-ink">
            It stops at <span className="tabular">{money(plan.floor, 0)}</span> at the latest
            <Explain text={explain("Floor")!} label="Floor" />
          </div>
          <div className="mt-1 text-[13px] leading-relaxed text-muted">
            That is a loss of at most {money(capital - plan.floor, 0)} ({(((capital - plan.floor) / capital) * 100).toFixed(1)}%) of the{" "}
            {money(capital, 0)}. A sudden price jump can carry it a little past the floor before the sale goes through.
          </div>
        </>
      ) : (
        <>
          <div className="text-[17px] font-semibold text-ink">No floor: it runs until you stop it</div>
          <div className="mt-1 text-[13px] leading-relaxed text-muted">
            The general risk limits (the daily loss limit and the drawdown breaker) still apply to everything it does.
          </div>
        </>
      )}
      {lines.length > 0 && (
        <ul className="mt-2 space-y-1 text-[13px] leading-relaxed text-muted">
          {lines.map((l, i) => (
            <li key={i}>{l}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

// ── 2 · running ─────────────────────────────────────────────────────────────

const FWD_TONE = { neutral: "text-muted", good: "text-up", warn: "text-warn", bad: "text-down" } as const;
const ROOM_TONE: Record<"off" | "ok" | "near" | "over", StatTone> = { off: "plain", ok: "plain", near: "warn", over: "down" };

function Running({ s, api, onAnalyse }: { s: AutopilotStatus; api: AutopilotApi; onAnalyse: () => void }) {
  const { journal, live: liveStatus } = useStore();
  const advanced = useAdvanced();
  const simple = !advanced;
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [scrub, setScrub] = useState<Scrub | null>(null);
  const now = Date.now();
  const id = s.config.id;
  const running = s.state === "running";
  const live = s.config.mode === "live";
  // Armed or disarmed for this venue, and paused because live is disarmed.
  const liveRoute = live ? realMoneyState(s, liveStatus) : null;
  const badge = modeLabel(s.config.mode, simple, isLiveTest(s.config));
  const plan = floorAtStart(s.startCapital, s.config.stop);
  // No loss or trailing rule means no floor (the engine sends null).
  const room = floorRoom(s.equity, s.floorEquity, s.peakEquity);
  const fwd = forwardLine(s.forward);
  const { times, values } = splitCurve(curve(s, now));
  const last = values[values.length - 1] ?? s.equity;
  const fees = feeShare(s.fees, s.pnl);
  const exchange = exchangeName(s.config.venue);
  const classes = classRows(s);
  const blend = blendWords(s);

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

  return (
    <section aria-label={`Autopilot ${s.config.name}`} className="space-y-5">
      {/* status */}
      <Card as="article" label={`Status of ${s.config.name}`}>
        <div className="flex items-start gap-3">
          <span className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-full ${live ? "bg-down/10 text-down" : "bg-surface-2 text-ink"}`} aria-hidden>
            {running ? <Plane size={18} /> : <Pause size={18} />}
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xl font-semibold leading-tight text-ink">{running ? "Running" : "Paused"}</span>
              <Badge tone={badge.tone}>{badge.text}</Badge>
              {live && liveRoute && <Badge tone={liveRoute.tone}>{liveRoute.text}</Badge>}
            </div>
            <div className="mt-0.5 break-words text-[15px] text-muted">{s.config.name}</div>
          </div>
        </div>

        {live && (
          <Notice tone="danger" title={isLiveTest(s.config) ? "LIVE TEST with real money" : "Real money"} className="mt-4">
            {isLiveTest(s.config)
              ? `A capped live test: it buys and sells with real money in your ${exchange} account with a strategy that has not passed its checks, and can lose the whole amount, also while you sleep. Its trades never count as evidence that the strategy is ready.`
              : `It buys and sells with real money in your ${exchange} account and can lose it, also while you sleep.`}
          </Notice>
        )}
        {(s.config.assetClass === "perps" || (s.shortUsd ?? 0) > 0) && (
          <p className="tabular mt-3 text-[13px] leading-relaxed text-muted" aria-label="Long, short and funding">
            Long {money(s.longUsd ?? 0, 0)} · Short {money(s.shortUsd ?? 0, 0)} · Funding {signedMoney(s.funding ?? 0)} (in the
            result already; a long pays positive funding, a short receives it)
          </p>
        )}

        <p className="mt-4 text-[15px] leading-relaxed text-ink">
          {running
            ? `Trading ${money(s.startCapital, 0)} ${s.config.portfolio ? "across crypto and US shares" : `on ${exchange}`}${
                s.config.mode === "demo" ? (s.config.portfolio ? " on the Alpaca paper account" : "'s demo account") : ""
              } on its own, for ${fmtDuration(now - s.startedMs)} now.`
            : "Holding what it has and opening nothing new until you resume it."}
        </p>
        <p className="mt-1 text-[13px] text-muted">
          Started {fmtWhen(s.startedMs)}
          {s.config.stop.endMs ? `, ends ${fmtWhen(s.config.stop.endMs)} at the latest` : ", runs until you stop it or a limit is reached"}
        </p>
        {fwd && (
          <p className="mt-2 text-sm" data-testid="forward-line">
            <span className="text-muted">Against the backtest: </span>
            <span className={FWD_TONE[fwd.tone]}>{fwd.text}</span>
          </p>
        )}

        <div className="mt-4 flex flex-wrap items-center gap-2">
          {running ? (
            <Button variant="secondary" icon={Pause} disabled={busy} onClick={() => void act(() => api.pause(id))}>
              Pause
            </Button>
          ) : (
            <Button variant="secondary" icon={Play} disabled={busy} onClick={() => void act(() => api.resume(id))}>
              Resume
            </Button>
          )}
          <Button variant="secondary" icon={Pencil} disabled={busy || editing} onClick={() => setEditing(true)}>
            Edit
          </Button>
          <Button variant="danger" icon={Square} disabled={busy} onClick={() => setStopping(true)}>
            Stop
          </Button>
        </div>
        {err && (
          <Notice tone="danger" className="mt-3">
            {err}
          </Notice>
        )}
      </Card>

      <StopSheet
        open={stopping}
        live={live}
        preferFlatten={s.config.flattenOnStop}
        onClose={() => setStopping(false)}
        onStop={(f) => {
          setStopping(false);
          void act(() => api.stop(id, f));
        }}
      />

      {editing && <EditPanel s={s} api={api} onClose={() => setEditing(false)} />}

      {/* money */}
      <KeyStats
        items={[
          {
            label: "It is worth",
            value: money(s.equity, 2),
            help: explain("Equity"),
            sub: (
              <>
                <span className={TONE_TEXT[changeTone(s.pnl)]}>{moveWords(s.pnl, s.pnlPct)}</span> since it started with {money(s.startCapital, 0)}
              </>
            ),
          },
          { label: "P&L", value: signedMoney(s.pnl), tone: changeTone(s.pnl), sub: `${signedPct(s.pnlPct, 2)} after fees` },
          room
            ? {
                label: "Room to the floor",
                value: money(room.room, 0),
                tone: ROOM_TONE[room.level],
                sub: `Above ${money(room.floor, 0)}. ${room.word}.`,
              }
            : { label: "Room to the floor", value: "No floor", sub: "It stops when you stop it." },
        ]}
      />

      <Section title="Value since it started" hint="The dotted line is where it started. Drag across the chart or use the arrow keys to read a moment.">
        <div className="text-[13px] text-muted" aria-live="polite">
          {scrub ? (
            <>
              <span className="tabular text-[15px] font-semibold text-ink">{money(scrub.value, 2)}</span> on {fmtWhen(times[scrub.index] ?? now)}
            </>
          ) : (
            <>
              <span className="tabular text-[15px] font-semibold text-ink">{money(s.equity, 2)}</span> {running ? "now" : "while paused"}
            </>
          )}
        </div>
        <div className="mt-3">
          <AreaChart
            data={values}
            baseline={s.startCapital}
            tone={last >= s.startCapital ? "up" : "down"}
            label={`Value over time: started at ${money(s.startCapital, 0)}, now ${money(last, 0)}${room ? `, floor at ${money(room.floor, 0)}` : ""}`}
            onScrub={setScrub}
            empty="The chart fills in as it trades."
          />
        </div>
        {times.length > 1 && (
          <div className="mt-1 flex justify-between text-[12px] text-faint">
            <span>{fmtWhen(times[0])}</span>
            <span>{running ? "now" : "paused"}</span>
          </div>
        )}
        <List className="mt-3">
          <Row label="Started with" value={money(s.startCapital, 0)} sub="The dotted line" />
          {room ? (
            <div className="pb-3">
              <Row label="Floor" value={money(room.floor, 0)} sub="It stops on its own here" help={explain("Floor")} />
              <Meter pct={room.pct} level={room.level} label="Room left before the floor" />
              <div className="mt-1.5 text-[13px] text-muted">
                {room.word}: {money(room.room, 0)} above it
              </div>
            </div>
          ) : (
            <Row label="Floor" value="None" sub="No floor set: it stops when you stop it." help={explain("Floor")} />
          )}
          {s.config.stop.onTakeProfit === "stop" && plan.takeProfitAt !== null && (
            <Row label="Take profit" value={money(plan.takeProfitAt, 0)} sub="It takes the profit and stops here" />
          )}
        </List>
      </Section>

      <Section title="Its numbers" hint="Since it started, after every fee.">
        <List>
          <Row
            label="From its best"
            value={`${Math.abs(s.drawdownPct).toFixed(1)}%`}
            tone={s.drawdownPct > 5 ? "warn" : "plain"}
            sub={`The best was ${money(s.peakEquity, 0)}`}
          />
          <Row label="Trades" value={String(s.trades)} help="How many buys and sells it made." />
          <Row label="Fees" value={money(s.fees)} sub={fees !== null ? `${(fees * 100).toFixed(0)}% of the gain before fees` : undefined} />
        </List>
      </Section>

      <Section title="What it is doing" help="Its latest move, and why each strategy is in the mix." hint="Its latest move, and why each strategy is in the mix.">
        <div>
          <div className="text-[13px] font-medium text-muted">Last action</div>
          <p className="mt-0.5 break-words text-[15px] text-ink">{s.lastAction ?? "Nothing yet. It is waiting for its first signal."}</p>
        </div>
        {s.waiting && <p className="mt-3 rounded-2xl bg-surface-2 px-4 py-3 text-sm leading-relaxed text-muted">{s.waiting}</p>}
        {s.nextRepickMs != null && <p className="mt-2 text-[13px] text-muted">Chooses its strategies again with fresh evidence around {fmtWhen(s.nextRepickMs)}.</p>}

        {classes.length > 0 && (
          <div className="mt-4" data-testid="portfolio-classes">
            <h3 className="text-[15px] font-semibold text-ink">Split between crypto and US shares</h3>
            <p className="mt-0.5 text-[13px] leading-relaxed text-muted">
              By evidence: a side whose strategies have none gets nothing. Crypto trades day and night, US shares only while the
              US market is open.
            </p>
            <List className="mt-1">
              {classes.map((c) => (
                <div key={c.key} className="py-3">
                  <div className="flex items-start justify-between gap-3">
                    <span className="min-w-0 text-[15px] font-semibold text-ink">
                      {c.label} <span className="tabular font-normal text-muted">{c.share}</span>
                    </span>
                    <span className={`tabular shrink-0 text-[15px] font-semibold ${TONE_TEXT[changeTone(c.pnl)]}`}>{signedMoney(c.pnl)}</span>
                  </div>
                  <div className="mt-0.5 text-[13px] text-muted">{c.detail}</div>
                  {c.note && <p className="mt-1 text-[13px] leading-relaxed text-muted">{c.note}</p>}
                </div>
              ))}
            </List>
            {blend && (
              <p className="mt-2 text-[13px] text-muted">
                Held against {blend} bought and held. The blend follows the split whenever it moves.
              </p>
            )}
          </div>
        )}

        <div className="mt-3">
          {classes.length > 0 && s.bySleeve.length > 0 && <h3 className="mt-4 text-[15px] font-semibold text-ink">Its strategies</h3>}
          {s.bySleeve.length === 0 ? (
            <Nothing icon={Activity} title="Choosing its strategies">
              The strategies it picks, and why, show up here within a minute of starting.
            </Nothing>
          ) : (
            <List>
              {s.bySleeve.map((b) => (
                <div key={b.strategyId} className="py-3">
                  <div className="flex items-start justify-between gap-3">
                    <span className="min-w-0 break-words text-[15px] font-semibold text-ink">
                      {b.name}
                      {isExperiment(b) && (
                        <span className="ml-2 align-middle">
                          <Badge tone="warn" title={EXPERIMENT_HINT}>
                            {EXPERIMENT_LABEL}
                          </Badge>
                        </span>
                      )}
                    </span>
                    <span className={`tabular shrink-0 text-[15px] font-semibold ${TONE_TEXT[changeTone(b.pnl)]}`}>{signedMoney(b.pnl)}</span>
                  </div>
                  <div className="mt-0.5 text-[13px] text-muted">
                    <Term k="Strategy share">{sleeveExposure(b)}</Term> · {plural(b.trades, "trade")}
                  </div>
                  <p className="mt-1 text-[13px] leading-relaxed text-muted">{b.why}</p>
                </div>
              ))}
            </List>
          )}
        </div>

        {advanced && recent.length > 0 && (
          <div className="mt-4">
            <h3 className="text-[15px] font-semibold text-ink">Recent activity of its strategies</h3>
            <List className="mt-1">
              {recent.map((j) => (
                <div key={j.id} className="flex gap-3 py-2 text-[13px]">
                  <span className="tabular shrink-0 text-faint">{new Date(j.ts).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })}</span>
                  <span className="min-w-0 break-words text-muted">{j.message}</span>
                </div>
              ))}
            </List>
          </div>
        )}

        <div className="mt-4">
          <Button variant="secondary" size="sm" icon={BarChart3} onClick={onAnalyse}>
            How is it doing?
          </Button>
        </div>
      </Section>
    </section>
  );
}

/** The markets an autopilot trades, for the strategies it may run. */
function venueClassOf(c: AutopilotConfig): Venue {
  return autopilotClass(c);
}

/**
 * Change a running autopilot without stopping it: name, amount, strategies
 * and loss limits. Nothing is sold to make the change; the engine checks it
 * again and says why when it refuses.
 */
function EditPanel({ s, api, onClose }: { s: AutopilotStatus; api: AutopilotApi; onClose: () => void }) {
  const { strategies, live: liveStatus } = useStore();
  const [f, setF] = useState<EditForm>(() => editForm(s.config));
  const [accept, setAccept] = useState(false);
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const live = s.config.mode === "live";
  const plan = planEdit(s.config, f, liveTestCap(liveStatus));
  const venue = venueClassOf(s.config);
  const listed = new Set(s.config.sleeves.map((x) => x.strategyId));
  const eligible = strategies
    .filter((x) => x.id !== "manual" && x.venueClass === venue && !(live && isExperiment(x)))
    .sort((a, b) => Number(listed.has(b.id)) - Number(listed.has(a.id)));
  const confirmed = live ? typed.trim().toUpperCase() === LIVE_EDIT_PHRASE : !plan.looser || accept;
  const canSave = plan.changed && plan.problems.length === 0 && confirmed && !busy;
  const set = (patch: Partial<EditForm>) => setF((x) => ({ ...x, ...patch }));

  async function save() {
    if (!canSave) return;
    setBusy(true);
    setErr("");
    try {
      await api.update(s.config.id, plan.update, live || (plan.looser && accept));
      onClose();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
    setBusy(false);
  }

  return (
    <Section title="Change this autopilot" help="Change it without stopping it. Nothing is sold to make the change." hint="It keeps what it holds. Coins the new setup also wants stay, and the next rebalance trades only the difference.">
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Name">
          <input value={f.name} onChange={(e) => set({ name: e.target.value })} aria-label="Name" className={inputCls} />
        </Field>
        <Field label="Amount" hint="Lower: it scales down at the next rebalance, no fire sale.">
          <input inputMode="decimal" value={f.amount} onChange={(e) => set({ amount: e.target.value })} aria-label="Amount" className={`${inputCls} tabular`} />
        </Field>
      </div>

      <h3 className="mt-5 text-[15px] font-semibold text-ink">Strategies</h3>
      {s.config.portfolio ? (
        <p className="mt-1 text-[13px] leading-relaxed text-muted">
          Pythia picks this portfolio's strategies by evidence, for crypto and US shares each, and checks again every day.
        </p>
      ) : (
        <div className="mt-2 grid gap-2 sm:grid-cols-2" role="radiogroup" aria-label="Who picks the strategies">
          <Choice name={`edit-pick-${s.config.id}`} checked={f.pick === "auto"} onChange={() => set({ pick: "auto" })} title="Let Pythia choose" detail="It picks by evidence and checks again every day." />
          <Choice name={`edit-pick-${s.config.id}`} checked={f.pick === "manual"} onChange={() => set({ pick: "manual" })} title="I choose" detail="Give each strategy a share. Empty means not used." />
        </div>
      )}
      {f.pick === "manual" && (
        <div className="mt-2 max-h-72 overflow-y-auto pr-1">
          <List>
            {eligible.map((x) => (
              <div key={x.id} className="flex items-center justify-between gap-3 py-2">
                <span className="min-w-0 truncate text-[15px] text-ink">{x.name}</span>
                {isExperiment(x) && (
                  <Badge tone="warn" title={EXPERIMENT_HINT}>
                    {EXPERIMENT_LABEL}
                  </Badge>
                )}
                <SmallInput value={f.weights[x.id] ?? ""} onChange={(v) => set({ weights: { ...f.weights, [x.id]: v } })} label={`Share for ${x.name}`} width="w-20" />
              </div>
            ))}
          </List>
        </div>
      )}

      <h3 className="mt-5 text-[15px] font-semibold text-ink">Limits</h3>
      <p className="text-[13px] text-muted">Empty means off.</p>
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-2 text-sm text-muted">
        <label className="inline-flex flex-wrap items-center gap-1.5">
          Stop at a loss of <SmallInput value={f.lossPct} onChange={(v) => set({ lossPct: v })} label="Loss limit in percent" suffix="%" width="w-20" />
        </label>
        <label className="inline-flex flex-wrap items-center gap-1.5">
          or <SmallInput value={f.lossUsd} onChange={(v) => set({ lossUsd: v })} label="Loss limit in dollars" prefix="$" width="w-24" />
        </label>
        <label className="inline-flex flex-wrap items-center gap-1.5">
          Give back at most <SmallInput value={f.trailing} onChange={(v) => set({ trailing: v })} label="Trailing limit in percent" suffix="%" width="w-20" /> from its best
        </label>
      </div>

      {plan.problems.length > 0 && (
        <ul className="mt-3 space-y-1 text-[13px] text-warn">
          {plan.problems.map((p) => (
            <li key={p} className="flex items-start gap-2">
              <TriangleAlert size={14} aria-hidden className="mt-0.5 shrink-0" />
              <span className="min-w-0">{p}</span>
            </li>
          ))}
        </ul>
      )}
      {plan.looser && !live && (
        <label className="mt-3 flex items-start gap-2.5 text-sm text-warn">
          <input
            type="checkbox"
            checked={accept}
            onChange={(e) => setAccept(e.target.checked)}
            aria-label="Accept a bigger possible loss"
            className="mt-0.5 h-4 w-4 shrink-0"
            style={{ accentColor: "var(--color-warn)" }}
          />
          This lets it lose more than before. I accept that.
        </label>
      )}
      {live && (
        <Notice tone="danger" title={isLiveTest(s.config) ? "LIVE TEST with real money" : "Real money"} className="mt-3">
          <label className="block text-sm text-ink">
            Type <b className="text-down">{LIVE_EDIT_PHRASE}</b> to confirm
            <input
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
              placeholder={LIVE_EDIT_PHRASE}
              autoComplete="off"
              aria-label={`Type ${LIVE_EDIT_PHRASE} to confirm`}
              className={`${inputCls} mt-1.5 bg-surface focus:border-down sm:max-w-xs`}
            />
          </label>
        </Notice>
      )}
      {err && (
        <Notice tone="danger" className="mt-3">
          {err}
        </Notice>
      )}
      <div className="mt-4 flex flex-wrap gap-2">
        <Button variant={live ? "danger" : "primary"} icon={CheckCircle2} disabled={!canSave} onClick={() => void save()}>
          {busy ? "Saving" : "Save changes"}
        </Button>
        <Button variant="secondary" disabled={busy} onClick={onClose}>
          Cancel
        </Button>
      </div>
      {!plan.changed && <p className="mt-2 text-[13px] text-muted">Nothing changed yet.</p>}
    </Section>
  );
}

/**
 * Stop asks first, in a sheet: stop for good, and either sell everything or
 * keep what it bought. The choice made at the start is offered first; "Keep
 * it running" closes the sheet without doing anything.
 */
function StopSheet({
  open,
  onClose,
  onStop,
  preferFlatten,
  live,
}: {
  open: boolean;
  onClose: () => void;
  onStop: (flatten: boolean) => void;
  preferFlatten: boolean;
  live: boolean;
}) {
  const sell = (
    <Button key="sell" variant="danger" full onClick={() => onStop(true)}>
      Stop and sell everything
    </Button>
  );
  const keep = (
    <Button key="keep" variant="secondary" full onClick={() => onStop(false)}>
      Stop and keep the positions
    </Button>
  );
  return (
    <Sheet
      open={open}
      onClose={onClose}
      title="Stop the autopilot for good?"
      footer={
        <div className="grid gap-2">
          {preferFlatten ? [sell, keep] : [keep, sell]}
          <Button variant="ghost" full onClick={onClose}>
            Keep it running
          </Button>
        </div>
      }
    >
      <p className="text-[15px] leading-relaxed text-muted">
        It cannot be resumed afterwards. What should happen to what it bought?
        {live && " Kept positions stay at the exchange, and you look after them there."}
      </p>
      {live && (
        <Notice tone="danger" title="Real money" className="mt-3">
          Selling sends real orders to the exchange.
        </Notice>
      )}
    </Sheet>
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
  const strong = "font-semibold text-ink";

  const items: { icon: LucideIcon; tone: string; text: ReactNode }[] = [];

  // Against its start.
  items.push({
    icon: s.pnl >= 0 ? TrendingUp : TrendingDown,
    tone: TONE_TEXT[changeTone(s.pnl)],
    text: (
      <>
        It {active ? "has turned" : "turned"} {money(s.startCapital, 0)} into <b className={`tabular ${strong}`}>{money(s.equity, 2)}</b>:{" "}
        {Math.abs(s.pnl) < 0.005 ? (
          "no change"
        ) : (
          <b className={`tabular font-semibold ${s.pnl > 0 ? "text-up" : "text-down"}`}>
            {s.pnl > 0 ? "up" : "down"} {money(Math.abs(s.pnl), 2)} ({signedPct(s.pnlPct, 1)})
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
      tone: diff >= 0 ? "text-up" : "text-warn",
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
          would have gone <b className={`tabular ${strong}`}>{signedPct(hold.holdPct, 1)}</b>; the autopilot went{" "}
          <b className={`tabular ${strong}`}>{signedPct(hold.runPct, 1)}</b>. That is{" "}
          <b className={`font-semibold ${diff >= 0 ? "text-up" : "text-warn"}`}>{pointsWord(diff)}</b> than doing nothing
          {s.config.portfolio
            ? " with Bitcoin alone"
            : venueClassOf(s.config) === "alpaca"
              ? " with Bitcoin, though this run traded shares"
              : ""}
          .
        </>
      ),
    });
  } else {
    items.push({
      icon: BarChart3,
      tone: "text-faint",
      text: !btc
        ? "There is no Bitcoin price in this build to compare it with."
        : !btc.times || btc.times.length < 2
          ? "Comparing with just holding Bitcoin needs Bitcoin prices with dates. The desktop app and a connected server keep those; this browser version does not, so the comparison is not available here."
          : "The Bitcoin prices in memory do not reach back to this run's dates, so the comparison with just holding is not available.",
    });
  }

  // A portfolio against its own benchmark: Bitcoin and SPY at its split.
  const blend = blendWords(s);
  const mix = blend ? benchmark(s, now) : null;
  if (blend) {
    items.push({
      icon: BarChart3,
      tone: mix ? (mix.edgePct >= 0 ? "text-up" : "text-warn") : "text-faint",
      text: mix ? (
        <>
          Its own benchmark, {blend} bought and held at the same split, went <b className={`tabular ${strong}`}>{signedPct(mix.btcPct, 1)}</b>
          {mix.approximate ? " (from when a start price was known)" : ""}; the portfolio went{" "}
          <b className={`tabular ${strong}`}>{signedPct(mix.runPct, 1)}</b>. That is{" "}
          <b className={`font-semibold ${mix.edgePct >= 0 ? "text-up" : "text-warn"}`}>{pointsWord(mix.edgePct)}</b> than the blend.
        </>
      ) : (
        `Its own benchmark is ${blend} bought and held; it shows once a start price for each part is known.`
      ),
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
              <b className={strong}>{b.name}</b> {Math.abs(b.pnl) < 0.005 ? "broke even" : b.pnl > 0 ? "earned" : "lost"}{" "}
              {Math.abs(b.pnl) >= 0.005 && <b className={`tabular font-semibold ${b.pnl > 0 ? "text-up" : "text-down"}`}>{money(Math.abs(b.pnl), 2)}</b>} from{" "}
              {plural(b.trades, "trade")}
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
    tone: a.pnl.costHeavy ? "text-warn" : "text-faint",
    text:
      a.pnl.costs <= 0 ? (
        "It has paid no fees yet."
      ) : share !== undefined ? (
        <>
          Fees came to <b className={`tabular ${strong}`}>{money(a.pnl.costs, 2)}</b>, which is{" "}
          <b className={`tabular font-semibold ${a.pnl.costHeavy ? "text-warn" : "text-ink"}`}>{(share * 100).toFixed(0)}%</b> of the {money(a.pnl.gross, 2)} it
          made before fees.
          {a.pnl.costHeavy && " Above 40 % the costs are the story, not the strategies."}
        </>
      ) : (
        <>
          It paid <b className={`tabular ${strong}`}>{money(a.pnl.costs, 2)}</b> in fees and made nothing before fees, so the fees only added to
          the loss.
        </>
      ),
  });

  // Worst dip.
  items.push({
    icon: TrendingDown,
    tone: a.dip && a.dip.pct > 10 ? "text-warn" : "text-faint",
    text: a.dip ? (
      <>
        Its worst dip was <b className={`tabular ${strong}`}>{a.dip.pct.toFixed(1)}%</b> ({money(a.dip.usd, 0)}), from its high on {fmtWhen(a.dip.peakMs)} to
        the low on {fmtWhen(a.dip.troughMs)}.
      </>
    ) : (
      "It never fell below an earlier high."
    ),
  });

  // How often.
  items.push({
    icon: Clock,
    tone: "text-faint",
    text:
      a.tradesPerDay === null ? (
        "Too early to say how often it trades."
      ) : (
        <>
          It made <b className={`tabular ${strong}`}>{a.tradesPerDay.toFixed(1)}</b> trade{a.tradesPerDay.toFixed(1) === "1.0" ? "" : "s"} a day on average (
          {s.trades} in {fmtDays(a.days)}).
        </>
      ),
  });

  const m = a.maturity;
  const left = stillToGo(m.daysLeft, m.tradesLeft);

  return (
    <Section
      title={`How it did: ${s.config.name}`}
      help="A plain report on this run: against its start, against just holding Bitcoin, per strategy, and what it cost."
      hint={`${active ? "So far" : s.state === "finished" ? "Finished" : "Stopped"}, ${fmtWhen(a.startMs)} to ${active ? "now" : fmtWhen(a.endMs)}.`}
    >
      <ul className="space-y-3">
        {items.map((it, i) => (
          <li key={i} className="flex items-start gap-3 text-[15px] leading-relaxed text-muted">
            <it.icon size={16} aria-hidden className={`mt-1 shrink-0 ${it.tone}`} />
            <span className="min-w-0">{it.text}</span>
          </li>
        ))}
      </ul>

      <Notice tone={m.enough ? "info" : "warning"} className="mt-4" title={m.enough ? "Enough to start judging" : "Too early to judge"}>
        {m.enough ? (
          <>
            With {fmtDays(m.days)} and {m.trades} trades the numbers carry some weight. They still describe the past, not the future.
          </>
        ) : (
          <>
            {capitalise(fmtDays(m.days))} and {plural(m.trades, "trade")} are mostly noise: a good result can be luck, a bad one bad luck. The numbers
            start to mean something after at least {MEANINGFUL_DAYS} days and {MEANINGFUL_TRADES} trades, the same bar a strategy has to clear before it
            may use real money.
            {active ? ` ${left} to go.` : " This run ended before that."}
          </>
        )}
      </Notice>

      {advanced && (
        <div className="mt-4 border-t border-line pt-2">
          <CostLines pnl={a.pnl} />
          <List className="mt-2 border-t border-line">
            <Row label="Days" value={a.days.toFixed(1)} help="How long it has run, in days." />
            <Row label="Trades per day" value={a.tradesPerDay === null ? "n/a" : a.tradesPerDay.toFixed(2)} />
            <Row label="Worst Drawdown" value={a.dip ? `${a.dip.pct.toFixed(2)}%` : "0%"} tone={a.dip && a.dip.pct > 10 ? "warn" : "plain"} />
            <Row
              label="Cost share"
              value={share !== undefined ? `${(share * 100).toFixed(1)}%` : a.pnl.costs > 0 ? "No gross gain" : "n/a"}
              tone={a.pnl.costHeavy ? "warn" : "plain"}
            />
          </List>
        </div>
      )}
    </Section>
  );
}

// ── 4 · past runs ───────────────────────────────────────────────────────────

function PastList({ past, shownId, onAnalyse }: { past: AutopilotStatus[]; shownId?: string; onAnalyse: (id: string) => void }) {
  const simple = !useAdvanced();
  // Real-money runs and practice runs are listed apart, like the running ones.
  const groups = groupByMoney(past);
  return (
    <Section
      title="Past autopilots"
      help="Every earlier run with how it ended. Pick one to see its report above."
      hint="Every earlier run with how it ended. Tap one to see its report above."
    >
      {past.length === 0 ? (
        <Nothing icon={History} title="No finished autopilots yet">
          When an autopilot stops or finishes, it is listed here with its result.
        </Nothing>
      ) : (
        (["real", "practice"] as const).map((g) =>
          groups[g].length === 0 ? null : (
            <div key={g} className={g === "practice" && groups.real.length > 0 ? "mt-4" : ""}>
              <h3 className="text-[13px] font-semibold text-muted">{g === "real" ? "Real money" : "Practice (paper and demo)"}</h3>
              <PastRuns past={groups[g]} shownId={shownId} onAnalyse={onAnalyse} simple={simple} />
            </div>
          ),
        )
      )}
    </Section>
  );
}

function PastRuns({
  past,
  shownId,
  onAnalyse,
  simple,
}: {
  past: AutopilotStatus[];
  shownId?: string;
  onAnalyse: (id: string) => void;
  simple: boolean;
}) {
  return (
    <List>
      {past.map((p) => {
        const badge = modeLabel(p.config.mode, simple, isLiveTest(p.config));
        const end = p.stoppedMs ?? p.startedMs;
        const shown = p.config.id === shownId;
        const Icon = p.state === "finished" ? Flag : Square;
        return (
          <button
            key={p.config.id}
            type="button"
            onClick={() => onAnalyse(p.config.id)}
            aria-current={shown ? "true" : undefined}
            className={`-mx-2 block w-[calc(100%+1rem)] rounded-control px-2 py-3.5 text-left transition-colors hover:bg-surface-2 ${shown ? "bg-surface-2" : ""}`}
          >
            <span className="flex items-start justify-between gap-3">
              <span className="flex min-w-0 items-center gap-2">
                <Icon size={15} aria-hidden className="shrink-0 text-muted" />
                <span className="min-w-0 break-words text-[15px] font-semibold text-ink">{p.config.name}</span>
              </span>
              <span className="shrink-0 text-right">
                <span className={`tabular block text-[15px] font-semibold ${TONE_TEXT[changeTone(p.pnl)]}`}>{signedMoney(p.pnl)}</span>
                <span className="tabular block text-[13px] text-muted">
                  {signedPct(p.pnlPct, 1)} of {money(p.startCapital, 0)}
                </span>
              </span>
            </span>
            <span className="mt-1.5 flex flex-wrap items-center gap-1.5">
              <Badge tone={badge.tone}>{badge.text}</Badge>
              <Badge>{p.state === "finished" ? "Finished" : "Stopped"}</Badge>
              {shown && <Badge tone="accent">Showing its report</Badge>}
            </span>
            <span className="mt-1.5 flex items-start gap-1.5 text-[13px] text-muted">
              <CalendarClock size={13} aria-hidden className="mt-0.5 shrink-0" />
              <span className="min-w-0">
                {fmtWhen(p.startedMs)} to {fmtWhen(end)}, {fmtDuration(end - p.startedMs)}, {plural(p.trades, "trade")}
              </span>
            </span>
            {p.stopReason && <span className="mt-1 block break-words text-[13px] leading-snug text-muted">{p.stopReason}</span>}
          </button>
        );
      })}
    </List>
  );
}
