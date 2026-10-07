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
 *   sizing is gentler for smaller M (Kelly fraction 0.10, 0.20 or 0.25).
 */
export function limitsFor(monthlyPct: number): Partial<RiskLimits> {
  return {
    maxDrawdownPct: monthlyPct,
    maxDailyLossPct: Math.round((monthlyPct / 4) * 10) / 10,
    maxPositionPct: Math.min(25, Math.max(5, monthlyPct * 2)),
    kellyFraction: monthlyPct <= 5 ? 0.1 : monthlyPct <= 10 ? 0.2 : 0.25,
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
    <Card className="mb-4">
      <div className="mb-3 flex items-start gap-3">
        <HeartPulse size={18} className="mt-0.5 text-accent" />
        <div>
          <div className="font-bold text-cyber-text">How much could you lose in a bad month without it hurting?</div>
          <div className="text-sm text-cyber-text-dim">
            Pick an answer and Pythia sets its safety limits to match. You can change it any time.
          </div>
        </div>
      </div>
      <div className="mb-4 flex flex-wrap gap-2">
        {CHOICES.map((c) => (
          <button
            key={c}
            onClick={() => {
              setPick(c);
              setSaved(false);
            }}
            className={`rounded-lg border px-3 py-1.5 text-sm transition-colors ${
              pick === c
                ? "border-accent/50 bg-accent/10 text-accent"
                : "border-cyber-border text-cyber-text-dim hover:text-cyber-text"
            }`}
          >
            {c} % <span className="text-xs text-cyber-text-faint">({money(c)})</span>
          </button>
        ))}
      </div>
      <ul className="mb-4 space-y-1.5 text-sm text-cyber-text-dim">
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
        {saved && <span className="text-sm text-success">Saved. The limits apply from the next trade on.</span>}
        <button
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
