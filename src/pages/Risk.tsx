import { useId, type ReactNode } from "react";
import { Power } from "lucide-react";
import { useStore } from "../store";
import { Badge, Button, Card, List, Page } from "../design";
import { Explain, KeyStats, Meter, More, Row, Section, SwitchRow, clock, levelWord, pct, plural, share, type Level } from "../pagekit";
import { LIMITS, LIMIT_GROUPS, fixed, gauge, limitText, monthlyVol, riskGauges, sizingWord, spikeTrimState, type Gauge, type LimitSpec } from "../pagekit/riskLab";
import { explain } from "../glossary";
import type { RiskLimits, RiskStatus, StrategySizing } from "../types";

const ENGINE_ONLY = "Measured by the engine in the desktop app. Not available in the browser build.";

export function Risk() {
  const { limits, setLimits, portfolio, toggleKill, riskStatus, strategies } = useStore();
  const { loss, gross } = riskGauges(portfolio, limits);
  const dd = riskStatus ? gauge(riskStatus.drawdownPct, limits.maxDrawdownPct) : null;

  return (
    <Page title="Risk" subtitle="Every order, practice or real, is checked against these limits before it goes out.">
      <KeyStats
        items={[
          {
            label: "Lost today",
            value: pct(loss.value, 2),
            tone: loss.level === "over" ? "down" : loss.level === "near" ? "warn" : "plain",
            help: explain("Daily Loss Utilization"),
            sub: <GaugeLine g={loss} what="Daily loss used" of={`of the ${loss.cap}% daily limit`} />,
          },
          {
            label: "Drawdown",
            value: dd ? pct(dd.value, 2) : "n/a",
            tone: dd && dd.level !== "ok" ? (dd.level === "over" ? "down" : "warn") : "plain",
            help: explain("Portfolio Drawdown"),
            sub: dd ? <GaugeLine g={dd} what="Drawdown used" of={`of the ${dd.cap}% breaker`} /> : "Measured in the desktop app",
          },
          {
            label: "In the market",
            value: pct(gross.value, 0),
            tone: gross.level === "over" ? "down" : gross.level === "near" ? "warn" : "plain",
            help: explain("Gross Exposure Utilization"),
            sub: <GaugeLine g={gross} what="Gross exposure used" of={`of the ${gross.cap}% cap`} />,
          },
        ]}
      />

      <KillSwitch on={limits.killSwitch} onToggle={toggleKill} />

      <Section title="Adaptive controls" hint="Two automatic helpers. Both only change which trades open and how big they are.">
        <List>
          <SwitchRow
            label="Regime filter"
            hint="Skips dip-buying strategies in trending markets and trend strategies in choppy ones, so each only fires where it suits."
            on={limits.regimeFilter}
            onChange={(v) => setLimits({ regimeFilter: v })}
          />
          <SwitchRow
            label="Adaptive capital allocation"
            hint="Gives more of the budget to strategies that have done well lately, about every 60 seconds. Laggards get less, none gets nothing."
            on={limits.adaptiveAllocation}
            onChange={(v) => setLimits({ adaptiveAllocation: v })}
          />
        </List>
      </Section>

      <Section title="Right now" hint="What the risk manager measures on the open positions, against the limits below.">
        <List>
          <CorrelatedExposure status={riskStatus} capPct={limits.maxCorrelatedExposurePct} grossPct={gross.value} />
          <BookVolatility status={riskStatus} targetPct={limits.portfolioVolTargetPct} trimMult={limits.volSpikeTrimMult ?? 0} />
          <Drawdown status={riskStatus} limitPct={limits.maxDrawdownPct} />
        </List>
      </Section>

      {riskStatus && riskStatus.sizing.length > 0 && (
        <Sizing sizing={riskStatus.sizing} nameOf={(id) => strategies.find((s) => s.id === id)?.name ?? id} />
      )}

      {LIMIT_GROUPS.map((g) => (
        <Section key={g.id} title={g.title} hint={g.hint}>
          <List>
            {LIMITS.filter((l) => l.group === g.id).map((l) => (
              <LimitSlider key={l.key} spec={l} value={limits[l.key] as number} onChange={(v) => setLimits({ [l.key]: v } as Partial<RiskLimits>)} />
            ))}
          </List>
        </Section>
      ))}
    </Page>
  );
}

/** The meter under a key number, with the level in words so colour is not the only signal. */
function GaugeLine({ g, what, of }: { g: Gauge; what: string; of: string }) {
  return (
    <span className="mt-2 block space-y-1.5">
      <Meter pct={g.pct} level={g.level} label={what} />
      <span className="block">
        {of}. <LevelWord level={g.level} />
      </span>
    </span>
  );
}

function LevelWord({ level }: { level: Level }) {
  const cls = level === "over" ? "text-down" : level === "near" ? "text-warn" : "text-muted";
  return <span className={`font-semibold ${cls}`}>{levelWord(level)}</span>;
}

function KillSwitch({ on, onToggle }: { on: boolean; onToggle: () => void }) {
  return (
    <Card label="Kill switch" className={on ? "bg-down/[0.06]" : ""}>
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex min-w-0 flex-1 items-start gap-3">
          <span className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-full ${on ? "bg-down/10 text-down" : "bg-surface-2 text-ink"}`} aria-hidden>
            <Power size={18} />
          </span>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-[17px] font-semibold text-ink">Kill switch</h2>
              <Badge tone={on ? "bad" : "neutral"}>{on ? "Engaged" : "Ready"}</Badge>
            </div>
            <p className="mt-0.5 text-[13px] leading-relaxed text-muted">
              {on ? "All new buys are stopped. Only orders that close a position go out." : "One press stops all new buys everywhere, at once."}
            </p>
          </div>
        </div>
        <Button variant={on ? "secondary" : "danger"} icon={Power} onClick={onToggle}>
          {on ? "Release" : "Engage kill switch"}
        </Button>
      </div>
    </Card>
  );
}

/** One measured value against its cap: label, value, meter, and a line under it. */
function GaugeRow({ title, value, g, capWord, children }: { title: string; value: string; g: Gauge | null; capWord: string; children?: ReactNode }) {
  const tip = explain(title);
  return (
    <div className="space-y-2 py-3.5">
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-center gap-1 text-[15px] text-ink">
          <span className="min-w-0">{title}</span>
          {tip && <Explain text={tip} label={title} />}
        </div>
        <div className="tabular shrink-0 text-right text-[15px] font-semibold text-ink">{value}</div>
      </div>
      {g && (
        <>
          <Meter pct={g.pct} level={g.level} label={title} />
          <div className="text-[13px] text-muted">
            {capWord}. <LevelWord level={g.level} />
          </div>
        </>
      )}
      {children}
    </div>
  );
}

/** Correlation-adjusted exposure against its cap, next to the raw gross. */
function CorrelatedExposure({ status, capPct, grossPct }: { status: RiskStatus | null; capPct: number; grossPct: number }) {
  if (!status) return <Unmeasured title="Correlated Exposure" />;
  const g = gauge(status.correlatedExposurePct, capPct);
  const unaligned = status.unalignedPairs ?? [];
  return (
    <GaugeRow title="Correlated Exposure" value={pct(status.correlatedExposurePct, 0)} g={g} capWord={capPct > 0 ? `Of equity, against the ${capPct}% cap` : "Of equity. The cap is off"}>
      <p className="text-[13px] leading-relaxed text-muted">Raw gross is {pct(grossPct, 0)}. Positions that move together count as one bet.</p>
      {unaligned.length > 0 && (
        <p className="text-[13px] leading-relaxed text-warn">
          {plural(unaligned.length, "pair")} you hold can't be compared, because one side is on 5-minute candles and the other on live ticks. Those count as
          the worst case: moving together, and a short against them is not counted as a hedge.
        </p>
      )}
      <More title="How it is measured">
        <p className="text-[13px] leading-relaxed text-muted">
          sqrt(w&apos;Cw) over the return correlations on the Correlation page. Markets on candles are compared on the same bar times.
        </p>
      </More>
    </GaugeRow>
  );
}

/** How much the whole book swings in a typical year, against its target. */
function BookVolatility({ status, targetPct, trimMult }: { status: RiskStatus | null; targetPct: number; trimMult: number }) {
  if (!status) return <Unmeasured title="Book Volatility" />;
  const v = status.portfolioVolPct ?? 0;
  const g = gauge(v, targetPct);
  const assumed = status.volAssumed ?? [];
  const trim = spikeTrimState(targetPct, trimMult, status.volSpikeSince);
  return (
    <GaugeRow title="Book Volatility" value={`${pct(v, 1)} a year`} g={g} capWord={targetPct > 0 ? `Against the ${targetPct}% target` : "The target is off"}>
      <p className="text-[13px] leading-relaxed text-muted">
        A normal month is about {pct(monthlyVol(v), 1)}. New entries that would push it over the target are shrunk or refused; it never sizes anything up.
        {assumed.length > 0 && ` No candles yet for ${plural(assumed.length, "held market")}, counted at 5 % a day.`}
      </p>
      <div className="flex items-start gap-2 text-[13px]">
        <Badge tone={trim.tone}>{trim.word}</Badge>
        <span className="min-w-0 leading-relaxed text-muted">
          {trim.text}
          {status.lastVolTrim !== undefined && ` Last trim at ${clock(status.lastVolTrim)}.`}
        </span>
      </div>
      <More title="How it is measured">
        <p className="text-[13px] leading-relaxed text-muted">
          How far the account moves in a typical year, every position weighted by how much its market swings and things that move together counted as one.
        </p>
      </More>
    </GaugeRow>
  );
}

/** Drawdown against the breaker, and how much it is shrinking new entries. */
function Drawdown({ status, limitPct }: { status: RiskStatus | null; limitPct: number }) {
  if (!status) return <Unmeasured title="Drawdown De-risking" />;
  const g = gauge(status.drawdownPct, limitPct);
  const factor = status.deriskFactor;
  return (
    <GaugeRow title="Drawdown De-risking" value={`${share(factor)} size`} g={g} capWord={`${pct(status.drawdownPct, 2)} of the ${limitPct}% breaker`}>
      <p className={`text-[13px] leading-relaxed ${factor < 1 ? "text-warn" : "text-muted"}`}>
        {factor < 1 ? `New entries are made at ${share(factor)} of their normal size.` : "New entries are at full size."} They shrink in a straight line as the
        drawdown eats into the limit: half size at half the limit, nothing new at the breaker.
      </p>
    </GaugeRow>
  );
}

function Unmeasured({ title }: { title: string }) {
  return <Row label={title} value="n/a" sub={ENGINE_ONLY} />;
}

/** How each strategy's entries are sized: signal strength until 30 closed trades, then its own win rate and payoff. */
function Sizing({ sizing, nameOf }: { sizing: StrategySizing[]; nameOf: (id: string) => string }) {
  return (
    <Section title="Position Sizing" hint="How big each strategy's next trade will be. The number on the right is the share of the textbook bet it uses.">
      <List>
        {sizing.map((s) => {
          const mode = sizingWord(s.mode);
          const payoff = s.trades > 0 && s.payoff === undefined ? "no losses" : fixed(s.payoff);
          return (
            <Row
              key={s.strategyId}
              label={nameOf(s.strategyId)}
              sub={
                <>
                  {plural(s.trades, "trade")} · won {s.winRate === undefined ? "n/a" : share(s.winRate)} · payoff {payoff} · full Kelly {fixed(s.kelly, 3)}
                  {s.since !== undefined && <span className="block text-faint">Fresh record since {new Date(s.since).toLocaleDateString()}</span>}
                </>
              }
              value={fixed(s.kellyShrunk, 3)}
              valueSub={<Badge tone={mode.tone}>{mode.text}</Badge>}
              help={explain("Position Sizing")}
            />
          );
        })}
      </List>
      <More title="How sizing works">
        <div className="space-y-2 text-[13px] leading-relaxed text-muted">
          <p>
            Under 30 closed trades a strategy is sized off its signal strength. From 30 on, off its own record: Kelly f = p - (1 - p) / b, shrunk by n / (n + 30), at
            most a quarter of that, never above the full-strength size. A negative Kelly means no measured edge and no new entries.
          </p>
          <p>
            A strategy at size zero stays there: it opens nothing, so its record cannot recover by itself, and no timer brings it back. The way back is to change its
            parameters on the Strategies page. That starts a fresh record, sized on signal strength again until 30 new trades close, and a live strategy goes back to
            paper until its checks are run again.
          </p>
        </div>
      </More>
    </Section>
  );
}

/** One limit: label and its meaning, the value on the right, the slider under them. */
function LimitSlider({ spec, value, onChange }: { spec: LimitSpec; value: number; onChange: (v: number) => void }) {
  const id = useId();
  const tip = explain(spec.label);
  return (
    <div className="py-3.5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1 text-[15px] text-ink">
            <label htmlFor={id} className="min-w-0">
              {spec.label}
            </label>
            {tip && <Explain text={tip} label={spec.label} />}
          </div>
          <div className="mt-0.5 text-[13px] leading-snug text-muted">{spec.meaning}</div>
        </div>
        <div className="tabular max-w-[45%] shrink-0 text-right text-[15px] font-semibold text-ink">{limitText(spec, value)}</div>
      </div>
      <input
        id={id}
        type="range"
        min={spec.min}
        max={spec.max}
        step={spec.step}
        value={value}
        aria-valuetext={limitText(spec, value)}
        onChange={(e) => onChange(Number(e.target.value))}
        className="mt-3 w-full min-w-0 accent-accent"
      />
    </div>
  );
}
