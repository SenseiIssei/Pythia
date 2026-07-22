import { useMemo, useState } from "react";
import { FlaskConical, Play } from "lucide-react";
import { useStore } from "../store";
import { Button, Card, PageHeader, Badge, Sparkline, StatCard } from "../components/ui";
import { backtest, type BacktestResult } from "../engine/backtest";
import { TrendingUp, Activity, Percent, ArrowDownWideNarrow } from "lucide-react";

export function Backtest() {
  const { strategies } = useStore();
  const testable = strategies.filter((s) => !["pairs", "prob-edge", "manual", "arb"].includes(s.kind));
  const [stratId, setStratId] = useState(testable[0]?.id ?? "");
  const [bars, setBars] = useState(1500);
  const [seed, setSeed] = useState(12345);
  const [vol, setVol] = useState(0.015);
  const [drift, setDrift] = useState(0.0002);
  const [result, setResult] = useState<BacktestResult | null>(null);

  const strat = useMemo(() => strategies.find((s) => s.id === stratId), [strategies, stratId]);

  function run() {
    if (!strat) return;
    setResult(backtest(strat, { bars, seed, vol, drift }));
  }

  return (
    <div className="animate-fade-in">
      <PageHeader title="Backtest" subtitle="Replay a strategy over synthetic history · same signal code as the live engine" />

      <Card className="mb-4">
        <div className="grid grid-cols-2 gap-4 md:grid-cols-5">
          <label className="text-xs text-cyber-text-dim">
            Strategy
            <select
              value={stratId}
              onChange={(e) => setStratId(e.target.value)}
              className="mt-1 w-full rounded border border-cyber-border bg-cyber-surface px-2 py-1.5 text-sm text-cyber-text focus:border-accent focus:outline-none"
            >
              {testable.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
          </label>
          <NumField label="Bars" value={bars} onChange={setBars} step={100} min={200} max={6000} />
          <NumField label="Seed" value={seed} onChange={setSeed} step={1} min={1} max={999999} />
          <NumField label="Volatility" value={vol} onChange={setVol} step={0.001} min={0.002} max={0.06} />
          <NumField label="Drift/bar" value={drift} onChange={setDrift} step={0.0001} min={-0.002} max={0.002} />
        </div>
        <div className="mt-3 flex items-center gap-3">
          <Button tone="purple" icon={Play} onClick={run} disabled={!strat}>
            Run backtest
          </Button>
          <span className="text-xs text-cyber-text-faint">
            <FlaskConical size={11} className="mr-1 inline" />
            {testable.length} testable strategies · pairs & Prob-Edge need multi-asset/model inputs
          </span>
        </div>
      </Card>

      {result && !result.ok && (
        <Card className="border-warning/30 bg-warning/5">
          <span className="text-sm text-warning">{result.message}</span>
        </Card>
      )}

      {result && result.ok && (
        <>
          <div className="mb-4 grid grid-cols-2 gap-4 lg:grid-cols-4">
            <StatCard label="Total Return" value={`${result.totalReturnPct >= 0 ? "+" : ""}${result.totalReturnPct.toFixed(1)}%`} icon={TrendingUp} tone={result.totalReturnPct >= 0 ? "green" : "red"} />
            <StatCard label="Sharpe" value={result.sharpe.toFixed(2)} icon={Activity} tone={result.sharpe >= 1 ? "green" : result.sharpe >= 0 ? "cyan" : "red"} />
            <StatCard label="Max Drawdown" value={`${result.maxDrawdownPct.toFixed(1)}%`} icon={ArrowDownWideNarrow} tone="red" />
            <StatCard label="Win Rate" value={`${(result.winRate * 100).toFixed(0)}%`} sub={`${result.trades} trades`} icon={Percent} tone="purple" />
          </div>
          <Card title="Backtest Equity Curve" right={<Badge tone={result.profitFactor >= 1 ? "green" : "red"}>PF {result.profitFactor.toFixed(2)}</Badge>}>
            <Sparkline data={result.equityCurve} height={200} tone={result.totalReturnPct >= 0 ? "green" : "red"} />
            <div className="mt-2 flex justify-between text-xs text-cyber-text-faint">
              <span>{result.bars} bars · seed {seed}</span>
              <span>final {result.equityCurve.length ? `$${result.equityCurve[result.equityCurve.length - 1].toFixed(0)}` : "—"}</span>
            </div>
          </Card>
          <div className="mt-3 text-xs text-cyber-text-faint">
            Synthetic geometric-Brownian data — a good backtest here is necessary, not sufficient. Live
            markets have fatter tails, slippage and thinner liquidity. Prove strategies in paper too.
          </div>
        </>
      )}
    </div>
  );
}

function NumField({ label, value, onChange, step, min, max }: { label: string; value: number; onChange: (v: number) => void; step: number; min: number; max: number }) {
  return (
    <label className="text-xs text-cyber-text-dim">
      {label}
      <input
        type="number"
        value={value}
        step={step}
        min={min}
        max={max}
        onChange={(e) => onChange(Math.max(min, Math.min(max, Number(e.target.value))))}
        className="mt-1 w-full rounded border border-cyber-border bg-cyber-surface px-2 py-1.5 text-sm text-cyber-text focus:border-accent focus:outline-none"
      />
    </label>
  );
}
