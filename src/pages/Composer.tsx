import { useState } from "react";
import { Blocks, Play, Plus, Trash2, Rocket, TrendingUp, Activity, ArrowDownWideNarrow, Percent } from "lucide-react";
import { Button, Card, PageHeader, Badge, Field, Sparkline, StatCard, inputCls, pnlTone } from "../components/ui";
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
import { PnlLines } from "../components/PnlBreakdown";
import { useUndo } from "../components/Confirm";

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
  const [undoNotice, offerUndo] = useUndo();

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
    setDeployMsg(`"${name}" now runs in the practice engine. Find it on the Strategies page.`);
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
    const before = composed;
    setComposed((c) => ({ ...c, rules: c.rules.filter((_, j) => j !== i) }));
    setResult(null);
    offerUndo(`Rule ${i + 1} removed.`, () => setComposed(before));
  }
  function run() {
    setResult(backtestComposed(composed, { bars, seed, vol }));
  }

  return (
    <div className="animate-fade-in mx-auto max-w-6xl">
      <PageHeader
        title="Strategy Composer"
        subtitle="Build your own buy rule from indicators, test it on simulated prices, then run it with practice money. Research only: it never trades real money."
      />

      <Card className="mb-4">
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <span className="text-xs text-cyber-text-dim">Start from a template:</span>
          {TEMPLATES.map((t) => (
            <button
              type="button"
              key={t.name}
              onClick={() => {
                // A template replaces every rule built so far; keep a way back.
                const before = composed;
                setComposed(structuredClone(t.composed));
                setResult(null);
                offerUndo(`Your rules were replaced by "${t.name}".`, () => setComposed(before));
              }}
              className="rounded-lg border border-cyber-border px-2 py-1 text-xs text-cyber-text-dim hover:border-accent/40 hover:text-accent"
            >
              {t.name}
            </button>
          ))}
        </div>

        <div className="mb-3 flex flex-wrap items-center gap-2 text-sm">
          <span className="text-cyber-text-dim">Open a</span>
          <select
            value={composed.direction}
            aria-label="Direction"
            onChange={(e) => {
              setComposed((c) => ({ ...c, direction: e.target.value as "long" | "short" }));
              setResult(null);
            }}
            className={`${inputCls} w-auto`}
          >
            <option value="long">LONG (bet on a rise)</option>
            <option value="short">SHORT (bet on a fall)</option>
          </select>
          <span className="text-cyber-text-dim">position when all of these are true:</span>
        </div>

        {undoNotice}
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

        <div className="mt-4 grid grid-cols-1 gap-3 border-t border-cyber-border pt-3 sm:grid-cols-3">
          <NumField label="Bars" value={bars} onChange={setBars} step={100} min={300} max={4000} />
          <NumField label="Seed" value={seed} onChange={setSeed} step={1} min={1} max={999999} />
          <NumField label="Volatility" value={vol} onChange={setVol} step={0.001} min={0.005} max={0.05} />
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <Button tone="purple" icon={Play} onClick={run} disabled={composed.rules.length === 0}>
            Backtest this strategy
          </Button>
          <span className="flex items-center gap-1 text-xs text-cyber-text-faint">
            <Blocks size={12} aria-hidden />
            Exits use the standard stop-loss and take-profit, measured in typical daily moves (ATR).
          </span>
        </div>

        <div className="mt-3 flex flex-wrap items-end gap-2 border-t border-cyber-border pt-3">
          <Field label="Name" className="min-w-0 flex-1 basis-56">
            <input
              value={deployName}
              onChange={(e) => setDeployName(e.target.value)}
              placeholder={`Composed ${composed.direction}`}
              className={inputCls}
            />
          </Field>
          <Button tone="green" icon={Rocket} onClick={deploy} disabled={composed.rules.length === 0}>
            Run it with practice money
          </Button>
        </div>
        {deployMsg && (
          <div role="status" className="mt-2 text-sm text-success">
            {deployMsg}
          </div>
        )}
        <div className="mt-1.5 text-xs text-cyber-text-faint">
          It runs on BTC, ETH and SOL with 10% of the practice balance. Pause or remove it on the Strategies page like
          any other.
        </div>
      </Card>

      {result && (
        <>
          <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
            <StatCard label="Net Return" value={`${result.totalReturnPct >= 0 ? "+" : ""}${result.totalReturnPct.toFixed(1)}%`} icon={TrendingUp} tone={pnlTone(result.totalReturnPct)} sub="after costs" />
            <StatCard label="Sharpe" value={result.sharpe.toFixed(2)} icon={Activity} tone={result.sharpe >= 1 ? "green" : result.sharpe >= 0 ? "neutral" : "red"} />
            <StatCard label="Max Drawdown" value={`${result.maxDrawdownPct.toFixed(1)}%`} icon={ArrowDownWideNarrow} />
            <StatCard label="Win Rate" value={`${(result.winRate * 100).toFixed(0)}%`} sub={`${result.trades} trades`} icon={Percent} />
          </div>
          <Card className="mb-4" title="Gross, costs, net" help="What the trades made before costs, what trading cost, and what was left.">
            <PnlLines pnl={result.pnl} />
          </Card>
          <Card
            title="Equity curve of the composed strategy"
            help="The test account's value over the simulated history."
            right={
              <Badge tone={result.profitFactor >= 1 ? "green" : "red"} title="Profit factor: above 1 means it made money overall">
                PF {result.profitFactor.toFixed(2)}
              </Badge>
            }
          >
            <Sparkline data={result.equityCurve.length > 1 ? result.equityCurve : [0, 0]} height={200} tone={result.totalReturnPct >= 0 ? "green" : "red"} />
            <div className="mt-2 text-xs text-cyber-text-faint">
              Tested on simulated prices only. A good result here is a reason to keep testing in practice, not proof
              that it works on a real market.
            </div>
          </Card>
        </>
      )}
    </div>
  );
}

const smallCls = `${inputCls} w-auto px-2 py-1 text-xs`;

function OperandEditor({ o, onChange, side }: { o: Operand; onChange: (o: Operand) => void; side: string }) {
  return (
    <span className="inline-flex items-center gap-1">
      <select
        value={o.kind}
        aria-label={`${side} indicator`}
        onChange={(e) => onChange({ ...o, kind: e.target.value as IndKind })}
        className={smallCls}
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
          aria-label={`${side} period in candles`}
          title="Period: how many candles the indicator looks back"
          onChange={(e) => onChange({ ...o, period: Math.max(2, Math.min(200, Number(e.target.value))) })}
          className={`${smallCls} !w-16 font-mono`}
        />
      )}
    </span>
  );
}

function RuleRow({ rule, onChange, onRemove, canRemove }: { rule: Rule; onChange: (r: Rule) => void; onRemove: () => void; canRemove: boolean }) {
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-lg border border-cyber-border bg-cyber-surface-2 px-3 py-2 text-sm">
      <OperandEditor o={rule.left} onChange={(left) => onChange({ ...rule, left })} side="Left" />
      <select
        value={rule.op}
        aria-label="Comparison"
        onChange={(e) => onChange({ ...rule, op: e.target.value as "<" | ">" })}
        className={`${smallCls} font-bold text-accent`}
      >
        <option value="<">is below</option>
        <option value=">">is above</option>
      </select>
      <select
        value={rule.rightMode}
        aria-label="Compare with"
        onChange={(e) => onChange({ ...rule, rightMode: e.target.value as "const" | "indicator" })}
        className={`${smallCls} text-cyber-text-dim`}
      >
        <option value="const">a number</option>
        <option value="indicator">another indicator</option>
      </select>
      {rule.rightMode === "const" ? (
        <input
          type="number"
          value={rule.rightConst}
          step={0.5}
          aria-label="Number to compare with"
          onChange={(e) => onChange({ ...rule, rightConst: Number(e.target.value) })}
          className={`${smallCls} !w-20 font-mono`}
        />
      ) : (
        <OperandEditor o={rule.rightOperand} onChange={(rightOperand) => onChange({ ...rule, rightOperand })} side="Right" />
      )}
      <button
        type="button"
        onClick={onRemove}
        disabled={!canRemove}
        aria-label="Remove this condition"
        title={canRemove ? "Remove this condition" : "A strategy needs at least one condition"}
        className="ml-auto rounded p-1 text-cyber-text-faint hover:text-danger disabled:opacity-30"
      >
        <Trash2 size={14} aria-hidden />
      </button>
    </div>
  );
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
