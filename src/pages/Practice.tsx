import { useCallback, useEffect, useState, type ReactNode } from "react";
import {
  ArrowDownRight,
  ArrowUpRight,
  Clock,
  GraduationCap,
  Minus,
  Microscope,
  ReceiptText,
  Wallet,
} from "lucide-react";
import { analyse, bitcoinMarket, fmtDuration, fmtWhen, forwardLine } from "../autopilot";
import { Badge, Card, EmptyState, PageHeader, Sparkline, fmtUsd, type Tone } from "../components/ui";
import { forwardStatus, labStatus, type LabStatus } from "../lab";
import { liveMode } from "../live";
import {
  benchmark,
  benchmarkLine,
  cashReason,
  direction,
  fillRows,
  fmtPrice,
  fmtQty,
  forwardSummary,
  holdings,
  nextLabSignalMs,
  practiceAutopilots,
  signedPctText,
  signedUsd,
  tradesToday,
  usesLabSignal,
  PLUS_MINUS,
  type Direction,
  type FillRow,
} from "../practice";
import { useStore } from "../store";
import type { AutopilotStatus } from "../types";

/** How often the lab report is read again. It changes once a day. */
const LAB_REFRESH_MS = 5 * 60_000;

const DIR_STYLE: Record<Direction, { color: string; Icon: typeof ArrowUpRight; word: string }> = {
  up: { color: PLUS_MINUS.up, Icon: ArrowUpRight, word: "up" },
  down: { color: PLUS_MINUS.down, Icon: ArrowDownRight, word: "down" },
  flat: { color: PLUS_MINUS.flat, Icon: Minus, word: "unchanged" },
};

/** A signed amount in its colour, with an arrow, so it never relies on colour alone. */
function Change({ usd, pct, big }: { usd: number; pct: number; big?: boolean }) {
  const d = direction(usd);
  const { color, Icon, word } = DIR_STYLE[d];
  return (
    <span
      className={`inline-flex flex-wrap items-center gap-x-1.5 font-mono font-bold tabular-nums ${big ? "text-lg" : "text-sm"}`}
      style={{ color }}
    >
      <Icon size={big ? 18 : 14} aria-hidden className="shrink-0" />
      <span className="sr-only">{word}</span>
      <span>{signedUsd(usd)}</span>
      <span>({signedPctText(pct)})</span>
    </span>
  );
}

function PctText({ pct }: { pct: number }) {
  return (
    <span className="font-mono font-bold tabular-nums" style={{ color: DIR_STYLE[direction(pct)].color }}>
      {signedPctText(pct)}
    </span>
  );
}

const STATE_BADGE: Record<AutopilotStatus["state"], { label: string; tone: Tone }> = {
  running: { label: "running", tone: "green" },
  paused: { label: "paused", tone: "amber" },
  stopped: { label: "stopped", tone: "neutral" },
  finished: { label: "finished", tone: "neutral" },
};

function Stat({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <div className="text-[11px] font-medium uppercase tracking-wider text-cyber-text-dim">{label}</div>
      <div className="mt-0.5 break-words font-mono text-sm font-bold tabular-nums text-cyber-text">{children}</div>
    </div>
  );
}

function AutopilotCard({ s, now }: { s: AutopilotStatus; now: number }) {
  const { positions, orders, markets, history, historyTimes } = useStore();
  const a = analyse(s, now);
  const btcMarket = bitcoinMarket(markets, historyTimes);
  const bench = benchmark(s, now, btcMarket ? historyTimes[btcMarket.id] : undefined, btcMarket ? history[btcMarket.id] : undefined);
  const held = holdings(s, positions);
  const today = tradesToday(s, orders, now);
  const active = s.state === "running" || s.state === "paused";
  // The engine reports the forward status only while it runs.
  const fwd = active ? forwardLine(s.forward) : null;
  const badge = STATE_BADGE[s.state];
  const nextSignal = nextLabSignalMs(now);
  const modeLabel = s.config.mode === "demo" ? "demo, play money" : s.config.mode === "paper" ? "paper, play money" : "real money";

  return (
    <Card>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <h2 className="break-words font-mono text-sm font-bold text-accent">{s.config.name}</h2>
          <p className="mt-0.5 text-xs text-cyber-text-dim">
            {active ? "Running for" : "Ran for"} {fmtDuration(a.endMs - s.startedMs)}, started with {fmtUsd(s.startCapital, 2)}
          </p>
        </div>
        <div className="flex flex-wrap gap-1.5">
          <Badge tone={badge.tone}>{badge.label}</Badge>
          <Badge tone={s.config.mode === "live" ? "red" : "cyan"}>{modeLabel}</Badge>
        </div>
      </div>

      <div className="mt-3">
        <div className="text-xs text-cyber-text-dim">Worth now</div>
        <div className="break-words font-mono text-3xl font-bold tabular-nums text-cyber-text sm:text-4xl">
          {fmtUsd(s.equity, 2)}
        </div>
        <div className="mt-1">
          <Change usd={s.pnl} pct={s.pnlPct} big />
        </div>
        <p className="mt-1 text-sm text-cyber-text-dim">
          {bench ? benchmarkLine(bench) : "No Bitcoin price from its start yet, so there is nothing to compare with."}
        </p>
        {bench && (
          <p className="mt-0.5 text-xs text-cyber-text-faint">
            Bitcoin <PctText pct={bench.btcPct} /> vs this autopilot <PctText pct={bench.runPct} />
          </p>
        )}
      </div>

      <div className="mt-3">
        <Sparkline
          data={a.points.map((p) => p[1])}
          tone="green"
          height={56}
          label={`Equity of ${s.config.name}, ${direction(s.pnl) === "down" ? "down" : "up or level"} since its start`}
        />
      </div>

      <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Trades today">{today}</Stat>
        <Stat label="Completed trades">{s.trades}</Stat>
        <Stat label="Fees paid">{fmtUsd(s.fees, 2)}</Stat>
        <Stat label="Holding">{held.length === 0 ? "cash" : `${held.length} coin${held.length === 1 ? "" : "s"}`}</Stat>
      </div>

      <div className="mt-4">
        <h3 className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-wider text-cyber-text-dim">
          <Wallet size={13} aria-hidden /> What it holds now
        </h3>
        {held.length === 0 ? (
          <p className="mt-1 text-sm text-cyber-text">{cashReason(s)}</p>
        ) : (
          <ul className="mt-1 divide-y divide-cyber-border">
            {held.map((h) => (
              <li key={h.marketId} className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5 py-1.5">
                <span className="min-w-0 font-mono text-sm text-cyber-text">
                  <span className="font-bold">{h.coin}</span>{" "}
                  <span className="text-cyber-text-dim">
                    {fmtQty(h.qty)} · {fmtUsd(h.value, 2)}
                  </span>
                </span>
                <Change usd={h.pnl} pct={h.pnlPct} />
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="mt-4 space-y-1 text-sm">
        {active && usesLabSignal(s) && (
          <p className="flex items-start gap-1.5 text-cyber-text-dim">
            <Clock size={14} aria-hidden className="mt-0.5 shrink-0" />
            <span>
              Next lab signal: <span className="font-mono text-cyber-text">{fmtWhen(nextSignal)}</span> (about 04:15 UTC
              daily, in {fmtDuration(nextSignal - now)})
            </span>
          </p>
        )}
        {active && !usesLabSignal(s) && (
          <p className="flex items-start gap-1.5 text-cyber-text-dim">
            <Clock size={14} aria-hidden className="mt-0.5 shrink-0" />
            <span>Its strategies look for signals on every new price.</span>
          </p>
        )}
        {fwd && (
          <p className="flex items-start gap-1.5 text-cyber-text-dim">
            <Microscope size={14} aria-hidden className="mt-0.5 shrink-0" />
            <span>Forward test: {fwd.text}</span>
          </p>
        )}
      </div>
    </Card>
  );
}

function FillItem({ f }: { f: FillRow }) {
  const buy = f.side === "buy";
  return (
    <li className="py-2">
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
        <span className="min-w-0 font-mono text-sm">
          <span className="font-bold" style={{ color: buy ? PLUS_MINUS.up : PLUS_MINUS.down }}>
            {buy ? "BUY" : "SELL"}
          </span>{" "}
          <span className="font-bold text-cyber-text">{f.coin}</span>{" "}
          <span className="text-cyber-text-dim">
            {fmtQty(f.qty)} @ {fmtPrice(f.price)}
          </span>
        </span>
        <Badge tone={f.badge.tone}>{f.badge.label}</Badge>
      </div>
      <div className="mt-0.5 flex flex-wrap gap-x-3 text-xs text-cyber-text-faint">
        <span>{fmtWhen(f.ts)}</span>
        <span>
          fee {f.fee != null ? <span className="font-mono text-cyber-text-dim">{fmtUsd(f.fee, 4)}</span> : f.feeNote}
        </span>
        {f.liquidity && <span>{f.liquidity}</span>}
        {f.autopilot && <span className="break-words">{f.autopilot}</span>}
      </div>
    </li>
  );
}

function ForwardCard({ lab, err }: { lab: LabStatus | null; err: string }) {
  const sum = forwardSummary(lab?.forward);
  return (
    <Card
      title="Forward tests"
      icon={Microscope}
      help="Every strategy is also run forward on real prices with play money, and held against what its backtest expected over the same days."
    >
      {err ? (
        <p className="text-sm text-cyber-text-dim">The lab report could not be read: {err}</p>
      ) : !sum ? (
        <p className="text-sm text-cyber-text-dim">
          {liveMode() === "none"
            ? "The forward tests are read from the lab, which needs the desktop app or a connected server."
            : "No forward report yet. The lab writes one every day."}
        </p>
      ) : (
        <>
          <p className="text-sm text-cyber-text">{sum.verdict}</p>
          <p className="mt-1 text-xs text-cyber-text-faint">
            {sum.total} tracked: {sum.onTrack} on track, {sum.ahead} better than expected, {sum.watch} worth watching,{" "}
            {sum.early} too early to say. Report from {fmtWhen(sum.generatedMs)}.
          </p>
          <ul className="mt-2 divide-y divide-cyber-border">
            {sum.rows.map((r) => {
              const st = forwardStatus(r.status);
              return (
                <li key={`${r.kind}:${r.name}`} className="py-2">
                  <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
                    <span className="min-w-0 break-words text-sm font-medium text-cyber-text">
                      {r.label || r.name}
                      {r.kind === "autopilot" && <span className="text-cyber-text-faint"> · autopilot</span>}
                    </span>
                    <span className="flex flex-wrap items-center gap-2">
                      {r.returnPct != null && <PctText pct={r.returnPct} />}
                      <Badge tone={st.tone}>{st.label}</Badge>
                    </span>
                  </div>
                  <p className="mt-0.5 text-xs text-cyber-text-dim">{r.sentence}</p>
                </li>
              );
            })}
          </ul>
        </>
      )}
    </Card>
  );
}

/**
 * The practice view: every running or recent autopilot on play money, in
 * the numbers a beginner asks for first. Is it making money, and is that
 * better than just holding Bitcoin? What does it hold, what did it trade,
 * and what did it pay for that?
 */
export function Practice() {
  const { autopilots, orders, markets } = useStore();
  const [now, setNow] = useState(() => Date.now());
  const [lab, setLab] = useState<LabStatus | null>(null);
  const [labErr, setLabErr] = useState("");

  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 30_000);
    return () => clearInterval(t);
  }, []);

  const readLab = useCallback(async () => {
    try {
      setLab(await labStatus());
      setLabErr("");
    } catch (e) {
      setLabErr(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    if (liveMode() === "none") return;
    void readLab();
    const t = setInterval(() => void readLab(), LAB_REFRESH_MS);
    return () => clearInterval(t);
  }, [readLab]);

  const shown = practiceAutopilots(autopilots, now);
  const fills = fillRows(orders, markets, shown, 20);

  return (
    <div className="animate-fade-in mx-auto max-w-3xl space-y-4">
      <PageHeader
        title="Practice"
        subtitle="Your autopilots trading play money: on the Alpaca paper account (demo) or in Pythia's simulator (paper). No real money moves here."
      />

      {shown.length === 0 ? (
        <Card>
          <EmptyState icon={GraduationCap} title="No autopilot is running">
            Start one on the Autopilot page with play money. It shows up here with how much it has made or lost, and how
            that compares with simply holding Bitcoin.
          </EmptyState>
        </Card>
      ) : (
        shown.map((s) => <AutopilotCard key={s.config.id} s={s} now={now} />)
      )}

      <Card title="Latest fills" icon={ReceiptText} help="Every order that was filled, newest first: what, how much, at what price and what it cost in fees.">
        {fills.length === 0 ? (
          <p className="text-sm text-cyber-text-dim">No fills yet.</p>
        ) : (
          <ul className="divide-y divide-cyber-border">
            {fills.map((f) => (
              <FillItem key={f.id} f={f} />
            ))}
          </ul>
        )}
      </Card>

      <ForwardCard lab={lab} err={labErr} />
    </div>
  );
}
