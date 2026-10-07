import { Power, ShieldAlert } from "lucide-react";
import { useStore } from "../store";
import { Card, PageHeader, Meter, Button, Toggle, Badge } from "../components/ui";
import type { RiskLimits, RiskStatus, SizingMode, StrategySizing } from "../types";

interface LimitRow {
  key: keyof RiskLimits;
  label: string;
  min: number;
  max: number;
  step: number;
  unit: string;
}

const ROWS: LimitRow[] = [
  { key: "maxDailyLossPct", label: "Max daily loss", min: 1, max: 25, step: 0.5, unit: "%" },
  { key: "maxDrawdownPct", label: "Max drawdown (breaker)", min: 2, max: 50, step: 1, unit: "%" },
  { key: "maxPositionPct", label: "Max position size", min: 1, max: 50, step: 1, unit: "% equity" },
  { key: "maxGrossExposurePct", label: "Max gross exposure", min: 10, max: 100, step: 5, unit: "% equity" },
  { key: "maxCorrelatedExposurePct", label: "Max correlated exposure", min: 0, max: 100, step: 5, unit: "% equity" },
  { key: "portfolioVolTargetPct", label: "Book volatility target", min: 0, max: 80, step: 1, unit: "% / year" },
  { key: "volSpikeTrimMult", label: "Volatility spike trim", min: 0, max: 4, step: 0.25, unit: "× target" },
  { key: "perStrategyBudgetPct", label: "Per-strategy budget", min: 5, max: 60, step: 1, unit: "% equity" },
  { key: "kellyFraction", label: "Kelly fraction", min: 0.05, max: 1, step: 0.05, unit: "×" },
  { key: "volTargetPct", label: "Vol-target sizing", min: 0, max: 5, step: 0.1, unit: "%/bar" },
  { key: "stopAtrMult", label: "Stop-loss (ATR)", min: 0, max: 10, step: 0.5, unit: "×ATR" },
  { key: "takeProfitAtrMult", label: "Take-profit (ATR)", min: 0, max: 15, step: 0.5, unit: "×ATR" },
  { key: "trailingAtrMult", label: "Trailing stop (ATR)", min: 0, max: 10, step: 0.5, unit: "×ATR" },
  { key: "maxConsecutiveLosses", label: "Loss streak → cooldown", min: 0, max: 12, step: 1, unit: "losses" },
  { key: "cooldownSec", label: "Cooldown duration", min: 30, max: 1800, step: 30, unit: "s" },
  { key: "maxOrdersPerMin", label: "Max orders / min", min: 1, max: 60, step: 1, unit: "" },
  { key: "maxDataStalenessSec", label: "Max data staleness", min: 5, max: 120, step: 5, unit: "s" },
];

export function Risk() {
  const { limits, setLimits, portfolio, toggleKill, riskStatus, strategies } = useStore();

  const dayPnl = portfolio.realizedPnl + portfolio.unrealizedPnl;
  const dayLossPct = (-dayPnl / portfolio.dayStartEquity) * 100;
  const lossUtil = (dayLossPct / limits.maxDailyLossPct) * 100;
  const exposureUtil =
    (portfolio.grossExposure / ((limits.maxGrossExposurePct / 100) * portfolio.equity)) * 100;
  const grossPct = portfolio.equity > 0 ? (portfolio.grossExposure / portfolio.equity) * 100 : 0;

  return (
    <div className="animate-fade-in">
      <PageHeader title="Risk" subtitle="The risk manager sits above every order — paper or live" />

      {/* kill switch */}
      <Card className={`mb-4 ${limits.killSwitch ? "border-danger/50 glow-red" : ""}`}>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className={`rounded-lg p-2 ${limits.killSwitch ? "bg-danger/20 text-danger" : "bg-cyber-surface-2 text-cyber-text-dim"}`}>
              <Power size={20} />
            </div>
            <div>
              <div className="font-bold">Global Kill Switch</div>
              <div className="text-xs text-cyber-text-dim">
                {limits.killSwitch
                  ? "ENGAGED — all live buys halted, only closing intents pass"
                  : "Armed and ready. One click halts all live execution."}
              </div>
            </div>
          </div>
          <Button tone={limits.killSwitch ? "green" : "red"} icon={Power} onClick={toggleKill}>
            {limits.killSwitch ? "Release" : "Engage kill switch"}
          </Button>
        </div>
      </Card>

      {/* adaptive controls */}
      <Card title="Adaptive controls" className="mb-4">
        <div className="flex items-center justify-between border-b border-cyber-border pb-3">
          <div className="pr-4">
            <div className="font-bold">Regime filter</div>
            <div className="text-xs text-cyber-text-dim">
              Block mean-reversion strategies in trending markets and trend strategies in choppy ones —
              so strategies only fire in the conditions they suit.
            </div>
          </div>
          <Toggle on={limits.regimeFilter} onChange={(v) => setLimits({ regimeFilter: v })} />
        </div>
        <div className="flex items-center justify-between pt-3">
          <div className="pr-4">
            <div className="font-bold">Adaptive capital allocation</div>
            <div className="text-xs text-cyber-text-dim">
              Auto-weight each strategy's budget toward its recent performance (rebalanced ~every 60s).
              Winners get more capital; laggards get throttled — but none is fully starved.
            </div>
          </div>
          <Toggle on={limits.adaptiveAllocation} onChange={(v) => setLimits({ adaptiveAllocation: v })} />
        </div>
      </Card>

      {/* live utilization */}
      <div className="mb-4 grid grid-cols-1 gap-4 md:grid-cols-2">
        <Card title="Daily Loss Utilization">
          <div className="mb-2 flex justify-between text-sm">
            <span className="text-cyber-text-dim">{dayLossPct > 0 ? dayLossPct.toFixed(2) : "0.00"}% of {limits.maxDailyLossPct}%</span>
            <span className={lossUtil >= 100 ? "text-danger" : "text-cyber-text-dim"}>
              {Math.max(0, lossUtil).toFixed(0)}%
            </span>
          </div>
          <Meter pct={Math.max(0, lossUtil)} tone={lossUtil >= 80 ? "red" : "green"} />
        </Card>
        <Card title="Gross Exposure Utilization">
          <div className="mb-2 flex justify-between text-sm">
            <span className="text-cyber-text-dim">
              {(exposureUtil || 0).toFixed(0)}% of {limits.maxGrossExposurePct}% cap
            </span>
          </div>
          <Meter pct={exposureUtil || 0} tone={exposureUtil >= 80 ? "red" : "cyan"} />
        </Card>
        <CorrelatedExposureCard status={riskStatus} capPct={limits.maxCorrelatedExposurePct} grossPct={grossPct} />
        <BookVolatilityCard
          status={riskStatus}
          targetPct={limits.portfolioVolTargetPct}
          trimMult={limits.volSpikeTrimMult ?? 0}
        />
        <DrawdownCard status={riskStatus} limitPct={limits.maxDrawdownPct} />
      </div>

      {riskStatus && riskStatus.sizing.length > 0 && (
        <SizingCard sizing={riskStatus.sizing} nameOf={(id) => strategies.find((s) => s.id === id)?.name ?? id} />
      )}

      {/* editable limits */}
      <Card title="Limits" right={<ShieldAlert size={14} className="text-warning" />}>
        <div className="space-y-3">
          {ROWS.map((r) => (
            <div key={r.key} className="flex items-center gap-4 text-sm">
              <span className="w-44 text-cyber-text-dim">{r.label}</span>
              <input
                type="range"
                min={r.min}
                max={r.max}
                step={r.step}
                value={limits[r.key] as number}
                onChange={(e) => setLimits({ [r.key]: Number(e.target.value) } as Partial<RiskLimits>)}
                className="flex-1 accent-[#00f0ff]"
              />
              <span className="w-24 text-right font-mono text-accent">
                {limits[r.key] as number} {r.unit}
              </span>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}

/** Correlation-adjusted exposure against its cap, next to the raw gross. */
function CorrelatedExposureCard({
  status,
  capPct,
  grossPct,
}: {
  status: RiskStatus | null;
  capPct: number;
  grossPct: number;
}) {
  if (!status) {
    return (
      <Card title="Correlated Exposure">
        <div className="text-xs text-cyber-text-faint">Measured by the Rust engine. Not available in the browser build.</div>
      </Card>
    );
  }
  const off = capPct <= 0;
  const util = off ? 0 : (status.correlatedExposurePct / capPct) * 100;
  const unaligned = status.unalignedPairs ?? [];
  return (
    <Card title="Correlated Exposure">
      <div className="mb-2 flex justify-between text-sm">
        <span className="text-cyber-text-dim">
          {status.correlatedExposurePct.toFixed(0)}% of equity {off ? "(cap off)" : `of ${capPct}% cap`}
        </span>
        {!off && <span className={util >= 100 ? "text-danger" : "text-cyber-text-dim"}>{util.toFixed(0)}%</span>}
      </div>
      <Meter pct={util} tone={util >= 80 ? "red" : "cyan"} />
      <div className="mt-2 text-xs text-cyber-text-faint">
        Raw gross is {grossPct.toFixed(0)}%. Positions that move together count as one bet: sqrt(w&apos;Cw) over the
        return correlations on the Correlation page. Markets on candles are compared on the same bar times.
        {unaligned.length > 0 &&
          ` ${unaligned.length} pair${unaligned.length === 1 ? "" : "s"} you hold can't be compared, because one side is on 5-minute candles and the other on live ticks. Those count as the worst case: moving together, and a short against them is not counted as a hedge.`}
      </div>
    </Card>
  );
}

/** How much the whole book swings in a typical year, against its target. */
function BookVolatilityCard({
  status,
  targetPct,
  trimMult,
}: {
  status: RiskStatus | null;
  targetPct: number;
  trimMult: number;
}) {
  if (!status) {
    return (
      <Card title="Book Volatility">
        <div className="text-xs text-cyber-text-faint">Measured by the Rust engine. Not available in the browser build.</div>
      </Card>
    );
  }
  const off = targetPct <= 0;
  const pct = status.portfolioVolPct ?? 0;
  const util = off ? 0 : (pct / targetPct) * 100;
  const assumed = status.volAssumed ?? [];
  return (
    <Card title="Book Volatility">
      <div className="mb-2 flex justify-between text-sm">
        <span className="text-cyber-text-dim">
          {pct.toFixed(1)}% a year {off ? "(target off)" : `of ${targetPct}% target`}
        </span>
        {!off && <span className={util >= 100 ? "text-danger" : "text-cyber-text-dim"}>{util.toFixed(0)}%</span>}
      </div>
      <Meter pct={util} tone={util >= 80 ? "red" : "cyan"} />
      <div className="mt-2 text-xs text-cyber-text-faint">
        How far the account moves in a typical year, every position weighted by how much its market swings and
        things that move together counted as one. A normal month is about {(pct / Math.sqrt(12)).toFixed(1)}%. New
        entries that would push it over the target are shrunk or refused; it never sizes anything up.
        {assumed.length > 0 &&
          ` No candles yet for ${assumed.length} held market${assumed.length === 1 ? "" : "s"}, counted at 5 % a day.`}
      </div>
      <SpikeTrimLine status={status} targetPct={targetPct} trimMult={trimMult} />
    </Card>
  );
}

const clock = (ms: number) => new Date(ms).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

/** What the volatility spike trim is doing, in one line. */
function SpikeTrimLine({ status, targetPct, trimMult }: { status: RiskStatus; targetPct: number; trimMult: number }) {
  const on = trimMult > 0 && targetPct > 0;
  const trigger = targetPct * Math.max(1, trimMult);
  let state: string;
  if (!on) {
    state = "Spike trim is off. A spike above the target only stops new entries; nothing is sold.";
  } else if (status.volSpikeSince !== undefined) {
    const mins = Math.max(0, Math.floor((Date.now() - status.volSpikeSince) / 60_000));
    state = `Over ${trigger.toFixed(0)}% for ${mins} of 30 minutes. If it stays there, every position is cut by the same share back to ${targetPct}%.`;
  } else {
    state = `Spike trim is on: if the book stays above ${trigger.toFixed(0)}% (${trimMult}× the target) for 30 minutes, every position is cut by the same share back to ${targetPct}%. Closing only, at most once an hour.`;
  }
  return (
    <div className="mt-2 flex items-start gap-2 text-xs">
      <Badge tone={!on ? "neutral" : status.volSpikeSince !== undefined ? "red" : "cyan"}>
        {!on ? "trim off" : status.volSpikeSince !== undefined ? "spike" : "trim on"}
      </Badge>
      <span className="text-cyber-text-faint">
        {state}
        {status.lastVolTrim !== undefined && ` Last trim at ${clock(status.lastVolTrim)}.`}
      </span>
    </div>
  );
}

/** Drawdown against the breaker, and how much it is shrinking new entries. */
function DrawdownCard({ status, limitPct }: { status: RiskStatus | null; limitPct: number }) {
  if (!status) {
    return (
      <Card title="Drawdown De-risking">
        <div className="text-xs text-cyber-text-faint">Measured by the Rust engine. Not available in the browser build.</div>
      </Card>
    );
  }
  const used = limitPct > 0 ? (status.drawdownPct / limitPct) * 100 : 0;
  const factor = status.deriskFactor;
  return (
    <Card title="Drawdown De-risking">
      <div className="mb-2 flex justify-between text-sm">
        <span className="text-cyber-text-dim">
          {status.drawdownPct.toFixed(2)}% of {limitPct}% breaker
        </span>
        <span className={factor < 1 ? "text-warning" : "text-cyber-text-dim"}>
          entries at {(factor * 100).toFixed(0)}% size
        </span>
      </div>
      <Meter pct={used} tone={used >= 50 ? "red" : "green"} />
      <div className="mt-2 text-xs text-cyber-text-faint">
        New entries shrink in a straight line as the drawdown eats into the limit: half size at half the limit, nothing
        new at the breaker.
      </div>
    </Card>
  );
}

const MODE_LABEL: Record<SizingMode, { text: string; tone: "neutral" | "cyan" | "red" }> = {
  confidence: { text: "signal strength", tone: "neutral" },
  measured: { text: "measured edge", tone: "cyan" },
  noEdge: { text: "no edge, size 0", tone: "red" },
};

const pct = (x?: number) => (x === undefined ? "-" : `${(x * 100).toFixed(0)}%`);
const num = (x?: number, d = 2) => (x === undefined ? "-" : x.toFixed(d));

/** How each strategy's entries are sized: signal strength until 30 closed
 *  trades, then its own win rate and payoff. */
function SizingCard({ sizing, nameOf }: { sizing: StrategySizing[]; nameOf: (id: string) => string }) {
  return (
    <Card title="Position Sizing" className="mb-4">
      <div className="mb-3 text-xs text-cyber-text-dim">
        Under 30 closed trades a strategy is sized off its signal strength. From 30 on, off its own record: Kelly
        f = p - (1 - p) / b, shrunk by n / (n + 30), at most a quarter of that, never above the full-strength size.
        A negative Kelly means no measured edge and no new entries.
      </div>
      <div className="mb-3 text-xs text-cyber-text-dim">
        A strategy at size zero stays there: it opens nothing, so its record cannot recover by itself, and no timer
        brings it back. The way back is to change its parameters on the Strategies page. That starts a fresh record,
        sized on signal strength again until 30 new trades close, and a live strategy goes back to paper until its
        checks are run again.
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs uppercase tracking-wide text-cyber-text-faint">
              <th className="py-1.5 pr-3">Strategy</th>
              <th className="py-1.5 pr-3 text-right">Trades</th>
              <th className="py-1.5 pr-3 text-right">Won</th>
              <th className="py-1.5 pr-3 text-right">Payoff</th>
              <th className="py-1.5 pr-3 text-right">Kelly</th>
              <th className="py-1.5 pr-3 text-right">Shrunk</th>
              <th className="py-1.5">Sized on</th>
            </tr>
          </thead>
          <tbody className="tabular-nums">
            {sizing.map((s) => (
              <tr key={s.strategyId} className="border-t border-cyber-border">
                <td className="py-1.5 pr-3 font-medium text-cyber-text">
                  {nameOf(s.strategyId)}
                  {s.since !== undefined && (
                    <div className="text-[10px] font-normal text-cyber-text-faint">
                      fresh record since {new Date(s.since).toLocaleDateString()}
                    </div>
                  )}
                </td>
                <td className="py-1.5 pr-3 text-right text-cyber-text-dim">{s.trades}</td>
                <td className="py-1.5 pr-3 text-right text-cyber-text-dim">{pct(s.winRate)}</td>
                <td className="py-1.5 pr-3 text-right text-cyber-text-dim">
                  {s.trades > 0 && s.payoff === undefined ? "no losses" : num(s.payoff)}
                </td>
                <td className="py-1.5 pr-3 text-right text-cyber-text-dim">{num(s.kelly, 3)}</td>
                <td className="py-1.5 pr-3 text-right text-accent">{num(s.kellyShrunk, 3)}</td>
                <td className="py-1.5">
                  <Badge tone={MODE_LABEL[s.mode].tone}>{MODE_LABEL[s.mode].text}</Badge>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
