import { useState } from "react";
import { Blocks, Play, Plus, Trash2, Rocket, TrendingUp, Activity, ArrowDownWideNarrow, Percent } from "lucide-react";
import { Button, Card, PageHeader, Badge, Sparkline, StatCard } from "../components/ui";
import { useStore } from "../store";
import {
  backtestComposed,
  IND_LABELS,
  NEEDS_PERIOD,
  TEMPLATES,
  type Composed,
  type IndKind,
  type Operand,
  type Rule,
} from "../engine/composer";
import type { BacktestResult } from "../engine/backtest";
import type { StrategyConfig } from "../types";

const IND_KINDS: IndKind[] = ["price", "rsi", "ema", "sma", "zscore", "roc", "macdHist", "atr"];

function newRule(): Rule {
  return { left: { kind: "rsi", period: 14 }, op: "<", rightMode: "const", rightConst: 30, rightOperand: { kind: "ema", period: 50 } };
}

export function Composer() {
  const { addStrategy } = useStore();
  const [composed, setComposed] = useState<Composed>({ direction: "long", rules: [newRule()] });
  const [bars, setBars] = useState(1500);
  const [seed, setSeed] = useState(12345);
  const [vol, setVol] = useState(0.02);
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [deployName, setDeployName] = useState("");
  const [deployMsg, setDeployMsg] = useState("");

  function deploy() {
    const name = deployName.trim() || `Composed ${composed.direction}`;
    const cfg: StrategyConfig = {
      id: `composed-${Date.now().toString(36)}`,
      name,
      kind: "composed",
      venueClass: "crypto",
      state: "paper",
      universe: ["crypto:BTC/USD", "crypto:ETH/USD", "crypto:SOL/USD"],
      params: [],
      budgetPct: 10,
      pnl: 0,
      trades: 0,
      winRate: 0,
      maxDrawdown: 0,
      profitFactor: 0,
      equityCurve: [0],
      rules: structuredClone(composed),
    };
    addStrategy(cfg);
    setDeployMsg(`Deployed "${name}" to the engine (paper) — see the Strategies page.`);
    setTimeout(() => setDeployMsg(""), 4000);
  }

  function setRule(i: number, r: Rule) {
    setComposed((c) => ({ ...c, rules: c.rules.map((x, j) => (j === i ? r : x)) }));
    setResult(null);
  }
  function addRule() {
    setComposed((c) => ({ ...c, rules: [...c.rules, newRule()] }));
    setResult(null);
  }
  function removeRule(i: number) {
    setComposed((c) => ({ ...c, rules: c.rules.filter((_, j) => j !== i) }));
    setResult(null);
  }
  function run() {
    setResult(backtestComposed(composed, { bars, seed, vol }));
  }

  return (
    <div className="animate-fade-in">
      <PageHeader title="Strategy Composer" subtitle="Build a rule-based strategy and backtest it · research-only (not yet live)" />

      <Card className="mb-4">
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <span className="text-xs text-cyber-text-dim">Templates:</span>
          {TEMPLATES.map((t) => (
            <button
              key={t.name}
              onClick={() => {
                setComposed(structuredClone(t.composed));
                setResult(null);
              }}
              className="rounded-lg border border-cyber-border px-2 py-1 text-xs text-cyber-text-dim hover:border-accent/40 hover:text-accent"
            >
              {t.name}
            </button>
          ))}
        </div>

        <div className="mb-3 flex items-center gap-2 text-sm">
          <span className="text-cyber-text-dim">Enter a</span>
          <select
            value={composed.direction}
            onChange={(e) => {
              setComposed((c) => ({ ...c, direction: e.target.value as "long" | "short" }));
              setResult(null);
            }}
            className="rounded border border-cyber-border bg-cyber-surface px-2 py-1 text-cyber-text focus:border-accent focus:outline-none"
          >
            <option value="long">LONG</option>
            <option value="short">SHORT</option>
          </select>
          <span className="text-cyber-text-dim">position when ALL of:</span>
        </div>

        <div className="space-y-2">
          {composed.rules.map((r, i) => (
            <RuleRow key={i} rule={r} onChange={(x) => setRule(i, x)} onRemove={() => removeRule(i)} canRemove={composed.rules.length > 1} />
          ))}
        </div>

        <div className="mt-3">
          <Button tone="neutral" icon={Plus} onClick={addRule}>
            Add condition
          </Button>
        </div>

        <div className="mt-4 grid grid-cols-3 gap-4 border-t border-cyber-border pt-3">
          <NumField label="Bars" value={bars} onChange={setBars} step={100} min={300} max={4000} />
          <NumField label="Seed" value={seed} onChange={setSeed} step={1} min={1} max={999999} />
          <NumField label="Volatility" value={vol} onChange={setVol} step={0.001} min={0.005} max={0.05} />
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <Button tone="purple" icon={Play} onClick={run} disabled={composed.rules.length === 0}>
            Backtest this strategy
          </Button>
          <span className="text-xs text-cyber-text-faint">
            <Blocks size={11} className="mr-1 inline" />
            exits use the standard ATR stop-loss / take-profit
          </span>
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-cyber-border pt-3">
          <input
            value={deployName}
            onChange={(e) => setDeployName(e.target.value)}
            placeholder="Name it, then deploy to the live paper engine"
            className="min-w-[240px] flex-1 rounded border border-cyber-border bg-cyber-surface px-2 py-1.5 text-sm focus:border-accent focus:outline-none"
          />
          <Button tone="green" icon={Rocket} onClick={deploy} disabled={composed.rules.length === 0}>
            Deploy to engine (paper)
          </Button>
          {deployMsg && <span className="text-xs text-success">{deployMsg}</span>}
        </div>
        <div className="mt-1 text-[11px] text-cyber-text-faint">
          Runs on BTC/ETH/SOL at 10% budget, paper mode — manage it from the Strategies page like any other.
        </div>
      </Card>

      {result && (
        <>
          <div className="mb-4 grid grid-cols-2 gap-4 lg:grid-cols-4">
            <StatCard label="Total Return" value={`${result.totalReturnPct >= 0 ? "+" : ""}${result.totalReturnPct.toFixed(1)}%`} icon={TrendingUp} tone={result.totalReturnPct >= 0 ? "green" : "red"} />
            <StatCard label="Sharpe" value={result.sharpe.toFixed(2)} icon={Activity} tone={result.sharpe >= 1 ? "green" : result.sharpe >= 0 ? "cyan" : "red"} />
            <StatCard label="Max Drawdown" value={`${result.maxDrawdownPct.toFixed(1)}%`} icon={ArrowDownWideNarrow} tone="red" />
            <StatCard label="Win Rate" value={`${(result.winRate * 100).toFixed(0)}%`} sub={`${result.trades} trades`} icon={Percent} tone="purple" />
          </div>
          <Card title="Composed Strategy Equity Curve" right={<Badge tone={result.profitFactor >= 1 ? "green" : "red"}>PF {result.profitFactor.toFixed(2)}</Badge>}>
            <Sparkline data={result.equityCurve.length > 1 ? result.equityCurve : [0, 0]} height={200} tone={result.totalReturnPct >= 0 ? "green" : "red"} />
            <div className="mt-2 text-xs text-cyber-text-faint">
              Research-only on synthetic data. To trade a composed rule live it would need porting into the
              Rust + TS engines — tell me and I'll wire the winners in.
            </div>
          </Card>
        </>
      )}
    </div>
  );
}

function OperandEditor({ o, onChange }: { o: Operand; onChange: (o: Operand) => void }) {
  return (
    <span className="inline-flex items-center gap-1">
      <select
        value={o.kind}
        onChange={(e) => onChange({ ...o, kind: e.target.value as IndKind })}
        className="rounded border border-cyber-border bg-cyber-surface px-1.5 py-1 text-xs text-cyber-text focus:border-accent focus:outline-none"
      >
        {IND_KINDS.map((k) => (
          <option key={k} value={k}>{IND_LABELS[k]}</option>
        ))}
      </select>
      {NEEDS_PERIOD[o.kind] && (
        <input
          type="number"
          value={o.period}
          min={2}
          max={200}
          onChange={(e) => onChange({ ...o, period: Math.max(2, Math.min(200, Number(e.target.value))) })}
          className="w-14 rounded border border-cyber-border bg-cyber-surface px-1.5 py-1 text-xs text-cyber-text focus:border-accent focus:outline-none"
        />
      )}
    </span>
  );
}

function RuleRow({ rule, onChange, onRemove, canRemove }: { rule: Rule; onChange: (r: Rule) => void; onRemove: () => void; canRemove: boolean }) {
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-lg border border-cyber-border bg-cyber-surface-2 px-3 py-2 text-sm">
      <OperandEditor o={rule.left} onChange={(left) => onChange({ ...rule, left })} />
      <select
        value={rule.op}
        onChange={(e) => onChange({ ...rule, op: e.target.value as "<" | ">" })}
        className="rounded border border-cyber-border bg-cyber-surface px-1.5 py-1 text-xs font-bold text-accent focus:border-accent focus:outline-none"
      >
        <option value="<">&lt;</option>
        <option value=">">&gt;</option>
      </select>
      <select
        value={rule.rightMode}
        onChange={(e) => onChange({ ...rule, rightMode: e.target.value as "const" | "indicator" })}
        className="rounded border border-cyber-border bg-cyber-surface px-1.5 py-1 text-xs text-cyber-text-dim focus:border-accent focus:outline-none"
      >
        <option value="const">value</option>
        <option value="indicator">indicator</option>
      </select>
      {rule.rightMode === "const" ? (
        <input
          type="number"
          value={rule.rightConst}
          step={0.5}
          onChange={(e) => onChange({ ...rule, rightConst: Number(e.target.value) })}
          className="w-20 rounded border border-cyber-border bg-cyber-surface px-1.5 py-1 text-xs text-cyber-text focus:border-accent focus:outline-none"
        />
      ) : (
        <OperandEditor o={rule.rightOperand} onChange={(rightOperand) => onChange({ ...rule, rightOperand })} />
      )}
      <button onClick={onRemove} disabled={!canRemove} className="ml-auto rounded p-1 text-cyber-text-faint hover:text-danger disabled:opacity-30">
        <Trash2 size={14} />
      </button>
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
