import { useMemo, useState } from "react";
import { FlaskConical, Play } from "lucide-react";
import { useStore } from "../store";
import { Button, Card, PageHeader, Badge, Field, Notice, Sparkline, StatCard, inputCls, pnlTone } from "../components/ui";
import { backtest, type BacktestResult } from "../engine/backtest";
import { costVenueFor, modelFor } from "../engine/costs";
import { PnlLines } from "../components/PnlBreakdown";
import type { StrategyConfig } from "../types";
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

  // Strategies arrive with the first engine push, possibly after this page
  // mounted, so an empty pick falls back to the first testable one.
  const strat = useMemo(
    () => strategies.find((s) => s.id === stratId) ?? (stratId ? undefined : testable[0]),
    [strategies, stratId, testable]
  );

  function run() {
    if (!strat) return;
    setResult(backtest(strat, { bars, seed, vol, drift }));
  }

  return (
    <div className="animate-fade-in mx-auto max-w-6xl">
      <PageHeader
        title="Backtest"
        subtitle="Replay a strategy over simulated price history, using the same signal code as the live engine, to see how it would have done."
      />

      <Card className="mb-4">
        <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
          <Field label="Strategy" className="col-span-2 md:col-span-1">
            <select value={strat?.id ?? ""} onChange={(e) => setStratId(e.target.value)} className={inputCls}>
              {testable.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
          </Field>
          <NumField label="Bars" value={bars} onChange={setBars} step={100} min={200} max={6000} />
          <NumField label="Seed" value={seed} onChange={setSeed} step={1} min={1} max={999999} />
          <NumField label="Volatility" value={vol} onChange={setVol} step={0.001} min={0.002} max={0.06} />
          <NumField label="Drift/bar" value={drift} onChange={setDrift} step={0.0001} min={-0.002} max={0.002} />
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <Button tone="purple" icon={Play} onClick={run} disabled={!strat}>
            Run backtest
          </Button>
          <span className="flex items-center gap-1 text-xs text-cyber-text-faint">
            <FlaskConical size={12} aria-hidden />
            {testable.length} strategies can be tested here. Pairs and Prob-Edge need several markets or a model, so
            they are left out.
          </span>
        </div>
      </Card>

      {result && !result.ok && (
        <Notice tone="warning" title="This strategy cannot be backtested here" className="mb-4">
          {result.message}
        </Notice>
      )}

      {!result && (
        <p className="text-sm text-cyber-text-faint">Pick a strategy and press Run backtest. Results appear here.</p>
      )}

      {result && result.ok && (
        <>
          <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
            <StatCard label="Net Return" value={`${result.totalReturnPct >= 0 ? "+" : ""}${result.totalReturnPct.toFixed(1)}%`} icon={TrendingUp} tone={pnlTone(result.totalReturnPct)} sub="after costs" />
            <StatCard label="Sharpe" value={result.sharpe.toFixed(2)} icon={Activity} tone={result.sharpe >= 1 ? "green" : result.sharpe >= 0 ? "neutral" : "red"} />
            <StatCard label="Max Drawdown" value={`${result.maxDrawdownPct.toFixed(1)}%`} icon={ArrowDownWideNarrow} />
            <StatCard label="Win Rate" value={`${(result.winRate * 100).toFixed(0)}%`} sub={`${result.trades} trades`} icon={Percent} />
          </div>
          <Card
            className="mb-4"
            title="Gross, costs, net"
            help="What the trades made before costs, what trading cost, and what was left."
            right={
              <Badge tone={result.pnl.costHeavy ? "amber" : "neutral"} title="The cost model used for this test">
                {costLabel(strat)}
              </Badge>
            }
          >
            <PnlLines pnl={result.pnl} />
            <div className="mt-2 text-[11px] text-cyber-text-faint">
              Gross is what the same trades would have made at the quoted price with no fees, spread or impact.
              Costs come from <span className="font-mono">config/costs.json</span> for this venue and instrument.
            </div>
          </Card>
          <Card
            title="Backtest equity curve"
            help="The test account's value over the simulated history."
            right={
              <Badge tone={result.profitFactor >= 1 ? "green" : "red"} title="Profit factor: above 1 means it made money overall">
                PF {result.profitFactor.toFixed(2)}
              </Badge>
            }
          >
            <Sparkline data={result.equityCurve} height={200} tone={result.totalReturnPct >= 0 ? "green" : "red"} />
            <div className="mt-2 flex justify-between font-mono text-xs text-cyber-text-faint">
              <span>{result.bars} bars · seed {seed}</span>
              <span>final {result.equityCurve.length ? `$${result.equityCurve[result.equityCurve.length - 1].toFixed(0)}` : "-"}</span>
            </div>
          </Card>
          <p className="mt-3 text-xs leading-relaxed text-cyber-text-faint">
            Simulated (geometric Brownian) prices: a good backtest here is necessary, not sufficient. Real markets have
            bigger surprises, slippage and fewer buyers and sellers. Prove a strategy in practice too.
          </p>
        </>
      )}
    </div>
  );
}

/** "Kraken · 40 bps taker + 2 bps spread" for the strategy's first market. */
function costLabel(s?: StrategyConfig): string {
  if (!s) return "";
  const venue = costVenueFor(s.venueClass);
  const symbol = (s.universe[0] ?? "").split(":")[1] ?? "";
  const m = modelFor(venue, symbol);
  return `${venue} · ${m.takerBps} bps fee + ${m.halfSpreadBps} bps spread per side`;
}

function NumField({ label, value, onChange, step, min, max }: { label: string; value: number; onChange: (v: number) => void; step: number; min: number; max: number }) {
  return (
    <Field label={label}>
      <input
        type="number"
        value={value}
        step={step}
        min={min}
        max={max}
        onChange={(e) => onChange(Math.max(min, Math.min(max, Number(e.target.value))))}
        className={`${inputCls} font-mono`}
      />
    </Field>
  );
}
