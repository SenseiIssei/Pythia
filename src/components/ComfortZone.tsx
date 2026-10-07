import { useState } from "react";
import { HeartPulse, RotateCcw } from "lucide-react";
import { Button, Card, fmtUsd } from "./ui";
import { useStore } from "../store";
import { resetOnboarding } from "./Onboarding";
import type { RiskLimits } from "../types";

const CHOICES = [2, 5, 10, 20];

/**
 * The risk limits, set by answering one question instead of five settings.
 *
 * The rule, from the monthly loss someone could live with (M %):
 *   the drawdown breaker trips at M (a bad month cannot quietly go past it);
 *   the daily loss cap is M / 4 (four bad days in a row reach the monthly line);
 *   one position is at most 2M, capped 5 to 25 % (it halving costs at most M);
 *   sizing is gentler for smaller M (Kelly fraction 0.10, 0.20 or 0.25);
 *   the whole book swings little enough that a bad month (two standard
 *   deviations) stays inside M: an annual volatility of M / 2 * sqrt(12).
 */
export function limitsFor(monthlyPct: number): Partial<RiskLimits> {
  return {
    maxDrawdownPct: monthlyPct,
    maxDailyLossPct: Math.round((monthlyPct / 4) * 10) / 10,
    maxPositionPct: Math.min(25, Math.max(5, monthlyPct * 2)),
    kellyFraction: monthlyPct <= 5 ? 0.1 : monthlyPct <= 10 ? 0.2 : 0.25,
    portfolioVolTargetPct: Math.round((monthlyPct / 2) * Math.sqrt(12)),
  };
}

export function ComfortZone() {
  const { portfolio, limits, setLimits } = useStore();
  const [pick, setPick] = useState<number>(() =>
    CHOICES.reduce((a, b) => (Math.abs(b - limits.maxDrawdownPct) < Math.abs(a - limits.maxDrawdownPct) ? b : a)),
  );
  const [saved, setSaved] = useState(false);
  const plan = limitsFor(pick);
  const eq = portfolio.equity;
  const money = (pct: number) => fmtUsd((eq * pct) / 100, 0);

  return (
    <Card
      title="How careful should it be?"
      icon={HeartPulse}
      subtitle="How much could you lose in a bad month without it hurting? Pick an answer and Pythia sets its safety limits to match. You can change it any time."
    >
      <div role="radiogroup" aria-label="A bad month could cost" className="mb-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
        {CHOICES.map((c) => (
          <button
            key={c}
            type="button"
            role="radio"
            aria-checked={pick === c}
            onClick={() => {
              setPick(c);
              setSaved(false);
            }}
            className={`rounded-lg border px-3 py-2 text-left transition-colors ${
              pick === c
                ? "border-accent/50 bg-accent/10 text-accent"
                : "border-cyber-border bg-cyber-bg/40 text-cyber-text-dim hover:border-cyber-border-bright hover:text-cyber-text"
            }`}
          >
            <div className="font-mono text-base font-bold">{c} %</div>
            <div className="font-mono text-xs text-cyber-text-faint">{money(c)}</div>
          </button>
        ))}
      </div>
      <div className="mb-1.5 text-xs font-medium text-cyber-text-faint">With that answer:</div>
      <ul className="mb-4 list-disc space-y-1.5 pl-5 text-sm text-cyber-text-dim marker:text-cyber-text-faint">
        <li>
          If it is down <b className="text-cyber-text">{money(plan.maxDrawdownPct!)}</b> from its best point, it
          stops buying anything new until you let it.
        </li>
        <li>
          On a day it loses <b className="text-cyber-text">{money(plan.maxDailyLossPct!)}</b>, it stops for the rest
          of that day.
        </li>
        <li>
          It never puts more than <b className="text-cyber-text">{money(plan.maxPositionPct!)}</b> into any one
          thing.
        </li>
        <li>
          It holds only as much as can swing about <b className="text-cyber-text">{money(pick / 2)}</b> in a normal
          month, counting things that move together as one.
        </li>
        <li>
          It bets {plan.kellyFraction! <= 0.1 ? "very carefully" : plan.kellyFraction! <= 0.2 ? "carefully" : "moderately"}{" "}
          on each idea.
        </li>
      </ul>
      <div className="flex flex-wrap items-center gap-3">
        <Button
          onClick={() => {
            setLimits(plan);
            setSaved(true);
          }}
        >
          Use these limits
        </Button>
        {saved && (
          <span role="status" className="text-sm text-success">
            Saved. The limits apply from the next trade on.
          </span>
        )}
        <button
          type="button"
          onClick={() => {
            resetOnboarding();
            window.location.reload();
          }}
          className="ml-auto flex items-center gap-1.5 text-xs text-cyber-text-faint hover:text-cyber-text"
        >
          <RotateCcw size={12} /> Show the introduction again
        </button>
      </div>
    </Card>
  );
}
