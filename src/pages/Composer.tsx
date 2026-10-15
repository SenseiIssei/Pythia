import { useState } from "react";
import { Blocks, Play, Plus, Rocket, Trash2 } from "lucide-react";
import { AreaChart, Button, Card, Chip, Field, List, Notice, Page, Segmented, changeTone, inputCls, money, signedPct } from "../design";
import { CostLines, KeyStats, Nothing, Row, Section, pct, plural, share, useUndoNote } from "../pagekit";
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
  const [undoNotice, offerUndo] = useUndoNote();

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
    <Page
      title="Strategy Composer"
      subtitle="Build your own buy rule from indicators, test it on made-up prices, then run it with practice money. It never trades real money."
    >
      <Section title="Start from a template" hint="A template replaces the rules below. You can undo it for a few seconds.">
        <div role="group" aria-label="Templates" className="flex flex-wrap gap-2">
          {TEMPLATES.map((t) => (
            <Chip
              key={t.name}
              onClick={() => {
                // A template replaces every rule built so far; keep a way back.
                const before = composed;
                setComposed(structuredClone(t.composed));
                setResult(null);
                offerUndo(`Your rules were replaced by "${t.name}".`, () => setComposed(before));
              }}
            >
              {t.name}
            </Chip>
          ))}
        </div>
      </Section>

      <Section title="Rules" hint="Long bets on a rise, short on a fall. It opens a position when all of these are true.">
        <div className="space-y-4">
          <Segmented
            label="Direction"
            value={composed.direction}
            onChange={(d) => {
              setComposed((c) => ({ ...c, direction: d }));
              setResult(null);
            }}
            options={[
              { id: "long", label: "Long" },
              { id: "short", label: "Short" },
            ]}
          />
          {undoNotice}
          <List>
            {composed.rules.map((r, i) => (
              <RuleRow key={i} n={i + 1} rule={r} onChange={(x) => setRule(i, x)} onRemove={() => removeRule(i)} canRemove={composed.rules.length > 1} />
            ))}
          </List>
          <Button variant="secondary" icon={Plus} onClick={addRule}>
            Add condition
          </Button>
        </div>
      </Section>

      <Section title="Test it" hint="Run the rules over a made-up price history.">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <NumField label="Bars" value={bars} onChange={setBars} step={100} min={300} max={4000} />
          <NumField label="Seed" value={seed} onChange={setSeed} step={1} min={1} max={999999} />
          <NumField label="Volatility" value={vol} onChange={setVol} step={0.001} min={0.005} max={0.05} />
        </div>
        <div className="mt-5">
          <Button variant="primary" icon={Play} onClick={run} disabled={composed.rules.length === 0}>
            Backtest this strategy
          </Button>
        </div>
        <p className="mt-3 text-[13px] leading-relaxed text-muted">Exits use the standard stop-loss and take-profit, measured in typical daily moves (ATR).</p>
      </Section>

      {!result && (
        <Card>
          <Nothing icon={Blocks} title="No test run yet">
            Press Backtest this strategy. Changing a rule clears the last result.
          </Nothing>
        </Card>
      )}

      {result && (
        <>
          <KeyStats
            items={[
              { label: "Net Return", value: signedPct(result.totalReturnPct, 1), tone: changeTone(result.totalReturnPct), sub: "What the test account kept after costs" },
              { label: "Max Drawdown", value: pct(result.maxDrawdownPct, 1), sub: "Worst fall from a high" },
              { label: "Win Rate", value: share(result.winRate), sub: plural(result.trades, "trade") },
            ]}
          />
          <Section title="Gross, costs, net" hint="What the trades made before costs, what trading cost, and what was left.">
            <CostLines pnl={result.pnl} />
          </Section>
          <Section title="Test account value" hint="The account's value over the made-up history.">
            <AreaChart
              data={result.equityCurve}
              height={200}
              tone={changeTone(result.totalReturnPct)}
              label="Composed strategy account value"
              renderTip={(i) => money(result.equityCurve[i], 0)}
              empty="No trades, so the value never moved."
            />
            <List className="mt-3">
              <Row
                label="Profit factor"
                value={result.profitFactor.toFixed(2)}
                tone={result.profitFactor >= 1 ? "up" : "down"}
                valueSub={result.profitFactor >= 1 ? "winners outweigh losers" : "losers outweigh winners"}
              />
              <Row label="Sharpe" value={result.sharpe.toFixed(2)} tone={result.sharpe >= 1 ? "up" : result.sharpe < 0 ? "down" : "plain"} />
            </List>
            <p className="mt-2 text-[13px] leading-relaxed text-muted">
              Tested on made-up prices only. A good result here is a reason to keep testing in practice, not proof that it works on a real market.
            </p>
          </Section>
        </>
      )}

      <Section title="Run it with practice money" hint="It runs on BTC, ETH and SOL with 10% of the practice balance. Pause or remove it on the Strategies page like any other.">
        <div className="flex flex-wrap items-end gap-3">
          <Field label="Name" className="min-w-0 flex-1 basis-56">
            <input value={deployName} onChange={(e) => setDeployName(e.target.value)} placeholder={`Composed ${composed.direction}`} className={inputCls} />
          </Field>
          <Button variant="accent" icon={Rocket} onClick={deploy} disabled={composed.rules.length === 0}>
            Run it with practice money
          </Button>
        </div>
        {deployMsg && (
          <div role="status" className="mt-3">
            <Notice tone="success">{deployMsg}</Notice>
          </div>
        )}
      </Section>
    </Page>
  );
}

function OperandEditor({ o, onChange, side }: { o: Operand; onChange: (o: Operand) => void; side: string }) {
  return (
    <span className="flex min-w-0 flex-wrap items-center gap-2">
      <select value={o.kind} aria-label={`${side} indicator`} onChange={(e) => onChange({ ...o, kind: e.target.value as IndKind })} className={`${inputCls} w-auto`}>
        {IND_KINDS.map((k) => (
          <option key={k} value={k}>
            {IND_LABELS[k]}
          </option>
        ))}
      </select>
      {NEEDS_PERIOD[o.kind] && (
        <input
          type="number"
          inputMode="numeric"
          value={o.period}
          min={2}
          max={200}
          aria-label={`${side} period in candles`}
          title="Period: how many candles the indicator looks back"
          onChange={(e) => onChange({ ...o, period: Math.max(2, Math.min(200, Number(e.target.value))) })}
          className={`${inputCls} tabular !w-20`}
        />
      )}
    </span>
  );
}

function RuleRow({ n, rule, onChange, onRemove, canRemove }: { n: number; rule: Rule; onChange: (r: Rule) => void; onRemove: () => void; canRemove: boolean }) {
  return (
    <div className="flex items-start gap-3 py-3.5">
      <span className="tabular mt-3 w-5 shrink-0 text-[13px] font-semibold text-muted" aria-hidden>
        {n}
      </span>
      <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2" role="group" aria-label={`Condition ${n}`}>
        <OperandEditor o={rule.left} onChange={(left) => onChange({ ...rule, left })} side="Left" />
        <select value={rule.op} aria-label="Comparison" onChange={(e) => onChange({ ...rule, op: e.target.value as "<" | ">" })} className={`${inputCls} w-auto font-semibold`}>
          <option value="<">is below</option>
          <option value=">">is above</option>
        </select>
        <select
          value={rule.rightMode}
          aria-label="Compare with"
          onChange={(e) => onChange({ ...rule, rightMode: e.target.value as "const" | "indicator" })}
          className={`${inputCls} w-auto`}
        >
          <option value="const">a number</option>
          <option value="indicator">another indicator</option>
        </select>
        {rule.rightMode === "const" ? (
          <input
            type="number"
            inputMode="decimal"
            value={rule.rightConst}
            step={0.5}
            aria-label="Number to compare with"
            onChange={(e) => onChange({ ...rule, rightConst: Number(e.target.value) })}
            className={`${inputCls} tabular !w-24`}
          />
        ) : (
          <OperandEditor o={rule.rightOperand} onChange={(rightOperand) => onChange({ ...rule, rightOperand })} side="Right" />
        )}
      </div>
      <button
        type="button"
        onClick={onRemove}
        disabled={!canRemove}
        aria-label={`Remove condition ${n}`}
        title={canRemove ? "Remove this condition" : "A strategy needs at least one condition"}
        className="mt-1.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-muted transition-colors hover:bg-surface-2 hover:text-down disabled:cursor-not-allowed disabled:opacity-30"
      >
        <Trash2 size={16} aria-hidden />
      </button>
    </div>
  );
}

function NumField({ label, value, onChange, step, min, max }: { label: string; value: number; onChange: (v: number) => void; step: number; min: number; max: number }) {
  return (
    <Field label={label}>
      <input
        type="number"
        inputMode="decimal"
        value={value}
        step={step}
        min={min}
        max={max}
        onChange={(e) => onChange(Math.max(min, Math.min(max, Number(e.target.value))))}
        className={`${inputCls} tabular`}
      />
    </Field>
  );
}
