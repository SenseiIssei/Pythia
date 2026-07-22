import { Power, ShieldAlert } from "lucide-react";
import { useStore } from "../store";
import { Card, PageHeader, Meter, Button } from "../components/ui";
import type { RiskLimits } from "../types";

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
  { key: "perStrategyBudgetPct", label: "Per-strategy budget", min: 5, max: 60, step: 1, unit: "% equity" },
  { key: "kellyFraction", label: "Kelly fraction", min: 0.05, max: 1, step: 0.05, unit: "×" },
  { key: "stopAtrMult", label: "Stop-loss (ATR)", min: 0, max: 10, step: 0.5, unit: "×ATR" },
  { key: "takeProfitAtrMult", label: "Take-profit (ATR)", min: 0, max: 15, step: 0.5, unit: "×ATR" },
  { key: "trailingAtrMult", label: "Trailing stop (ATR)", min: 0, max: 10, step: 0.5, unit: "×ATR" },
  { key: "maxConsecutiveLosses", label: "Loss streak → cooldown", min: 0, max: 12, step: 1, unit: "losses" },
  { key: "cooldownSec", label: "Cooldown duration", min: 30, max: 1800, step: 30, unit: "s" },
  { key: "maxOrdersPerMin", label: "Max orders / min", min: 1, max: 60, step: 1, unit: "" },
  { key: "maxDataStalenessSec", label: "Max data staleness", min: 5, max: 120, step: 5, unit: "s" },
];

export function Risk() {
  const { limits, setLimits, portfolio, toggleKill } = useStore();

  const dayPnl = portfolio.realizedPnl + portfolio.unrealizedPnl;
  const dayLossPct = (-dayPnl / portfolio.dayStartEquity) * 100;
  const lossUtil = (dayLossPct / limits.maxDailyLossPct) * 100;
  const exposureUtil =
    (portfolio.grossExposure / ((limits.maxGrossExposurePct / 100) * portfolio.equity)) * 100;

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
      </div>

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
